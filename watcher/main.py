"""Entry point: python -m watcher.main

Runs checks every `check_every_minutes` until --max-minutes is up (GitHub Actions starts a
fresh run on a schedule), then exits. Writes status.json (for the site) and state.json
(what it has already told you about) into --out.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time as _time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from . import notify
from .rules import (TZ, Config, Match, describe_cutoff, find_matches, idle_reason, live_watches,
                    load_config)
from .sheet import Slot, parse_sheet

log = logging.getLogger("watcher")

FetchFn = Callable[["date"], str]          # day -> tee sheet html
BookFn = Callable[[Slot, "date"], tuple]   # (slot, day) -> (ok, message)


def now_et() -> datetime:
    return datetime.now(TZ)


def nice_day(d) -> str:
    return d.strftime("%a %b ") + str(d.day)          # "Sat Oct 10"


class Watcher:
    def __init__(self, cfg: Config, out_dir: Path, fetch: FetchFn, book: BookFn | None = None):
        self.cfg = cfg
        self.out = out_dir
        self.fetch = fetch
        self.book = book
        self.out.mkdir(parents=True, exist_ok=True)
        self.state = self._load("state.json", {"seen": {}, "booked": {}, "reminded": {}, "alerts": {}})
        self.failures = 0

    # ── files ────────────────────────────────────────────────
    def _load(self, name, default):
        f = self.out / name
        try:
            return json.loads(f.read_text())
        except Exception:
            return default

    def _save(self, name, data):
        (self.out / name).write_text(json.dumps(data, indent=2, default=str) + "\n")

    def write_status(self, mode: str, watches: list[dict] | None = None, message: str = "") -> bool:
        """Write status.json. Returns True when something other than timestamps changed."""
        prev = self._load("status.json", {})
        status = {
            "mode": mode,                      # watching | paused | off-season | idle | error
            "message": message,
            "checked_at": now_et().isoformat(timespec="seconds"),
            "check_every_minutes": self.cfg.check_every_minutes,
            "auto_book": self.cfg.auto_book,
            "party_size": self.cfg.party_size,
            "default_cutoff": self.cfg.default_cutoff.strftime("%I:%M %p").lstrip("0"),
            "min_hours_notice": self.cfg.min_hours_notice,
            "watches": watches if watches is not None else prev.get("watches", []),
        }
        self._save("status.json", status)
        strip = lambda s: json.dumps({k: v for k, v in s.items() if k != "checked_at"} | {
            "watches": [{k: v for k, v in w.items() if k != "checked_at"} for w in s.get("watches", [])]},
            sort_keys=True)
        return strip(status) != strip(prev) if prev else True

    # ── one pass over every live watch ───────────────────────
    def check_once(self) -> bool:
        now = now_et()
        cards, changed = [], False
        for w in live_watches(self.cfg, now):
            card = {"date": w.key, "label": nice_day(w.day), "note": w.note,
                    "before": w.before.strftime("%I:%M %p").lstrip("0") if w.before else None,
                    "checked_at": now.isoformat(timespec="seconds")}
            try:
                sheet = parse_sheet(self.fetch(w.day))
            except Exception as e:
                log.exception("could not read %s", w.key)
                card["error"] = str(e)[:200]
                cards.append(card)
                self.failures += 1
                continue
            matches = find_matches(w, sheet, self.cfg, now)
            card |= describe_cutoff(w, sheet, self.cfg)
            card["my_times"] = [s.time for s in sheet.my_slots()]
            card["opens_at"] = sheet.opens_at if not sheet.open_slots(1) and not card["my_times"] else ""
            card["matches"] = [m.to_dict() for m in matches]
            card["open_after_cutoff"] = len(sheet.open_slots(self.cfg.party_size)) - len(matches)
            cards.append(card)
            changed |= self._handle(w.key, w.day, matches, card)
        self.failures = 0 if all("error" not in c for c in cards) else self.failures
        self._save("state.json", self.state)
        changed |= self.write_status("watching", cards)
        return changed

    def _handle(self, key, day, matches: list[Match], card: dict) -> bool:
        seen = set(self.state["seen"].get(key, []))
        current = {m.slot.time for m in matches}
        new = [m for m in matches if m.slot.time not in seen]
        self.state["seen"][key] = sorted(current)

        if new and self.cfg.auto_book:
            target = next((m for m in matches if not m.call_shop
                           and m.slot.time not in self.state["booked"].get(key, [])), None)
            if target and self.book:
                self.state["booked"].setdefault(key, []).append(target.slot.time)
                ok, msg = self.book(target.slot, day)
                self._booking_alert(day, target, ok, msg, card)
                if ok:
                    new = [m for m in new if m is not target]

        if new:
            self._new_times_alert(day, new, card)

        mine = card.get("my_times", [])
        if len(mine) >= 2 and self.state["reminded"].get(key) != mine:
            self.state["reminded"][key] = mine
            notify.send(f"You have {len(mine)} tee times {nice_day(day)}",
                        f"{', '.join(mine)}. Cancel the one you don't need so a member can use it.",
                        click=notify.TEE_SHEET_URL, tags=["golf", "warning"],
                        actions=[notify.view("Open tee sheet", notify.TEE_SHEET_URL)])
        return bool(new) or current != seen

    def _new_times_alert(self, day, new: list[Match], card: dict):
        first = new[0]
        times = ", ".join(m.slot.time for m in new)
        title = (f"{first.slot.time} opened — {nice_day(day)}" if len(new) == 1
                 else f"{len(new)} earlier times opened — {nice_day(day)}")
        why = f"Earlier than {card['cutoff']} ({card['cutoff_source']})."
        if first.call_shop:
            msg = f"{times}. {why} It's under {self.cfg.min_hours_notice:g}h out — call the pro shop to book."
            actions = [notify.view("Call pro shop", notify.PRO_SHOP_TEL)]
            click = notify.PRO_SHOP_TEL
        else:
            msg = f"{times}. {why} Tap Book to open the club's booking form (it holds the time for ~10 min)."
            actions = [notify.view(f"Book {first.slot.time}", first.slot.book_url())]
            click = first.slot.book_url()
        if notify.site_url():
            actions.append(notify.view("All open times", notify.site_url()))
        notify.send(title, msg, click=click, actions=actions, priority=5, tags=["golf", "rotating_light"])
        log.info("ALERT %s: %s", day, times)

    def _booking_alert(self, day, m: Match, ok: bool, msg: str, card: dict):
        if ok:
            others = [t for t in card.get("my_times", []) if t != m.slot.time]
            extra = f" Remember to cancel your {', '.join(others)}." if others else ""
            notify.send(f"Booked {m.slot.time} — {nice_day(day)}",
                        f"Auto-booked with TBD players.{extra}", click=notify.TEE_SHEET_URL,
                        priority=5, tags=["golf", "white_check_mark"],
                        actions=[notify.view("Open tee sheet", notify.TEE_SHEET_URL)])
        else:
            notify.send(f"Couldn't auto-book {m.slot.time} — {nice_day(day)}",
                        f"{msg[:300]} Tap to try it yourself.", click=m.slot.book_url(),
                        priority=5, tags=["golf", "x"],
                        actions=[notify.view(f"Book {m.slot.time}", m.slot.book_url())])

    def error_alert(self, text: str):
        last = self.state["alerts"].get("error")
        if last and datetime.fromisoformat(last) > now_et() - timedelta(hours=6):
            return
        self.state["alerts"]["error"] = now_et().isoformat()
        self._save("state.json", self.state)
        notify.send("Tee time watcher needs attention", text[:400], priority=3, tags=["warning"])


# ── run loop ─────────────────────────────────────────────────

def refresh_config(cfg_path: Path) -> None:
    """Pull the latest config.yml from GitHub so pausing/editing takes effect mid-run."""
    url = os.environ.get("CONFIG_URL")
    if not url:
        return
    try:
        with urllib.request.urlopen(f"{url}?t={int(_time.time())}", timeout=10) as r:
            body = r.read()
        if body.strip():
            cfg_path.write_bytes(body)
    except Exception as e:
        log.warning("config refresh failed (%s); keeping current copy", e)


def _gh_output(key: str, value: str):
    """Tell GitHub Actions whether the expensive steps (browser install) are needed."""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")
    print(f"{key}={value}")


def publish(cmd: str | None):
    if cmd:
        subprocess.run(cmd, shell=True, check=False)


def run(args) -> int:
    cfg_path = Path(args.config)
    out = Path(args.out)
    deadline = _time.monotonic() + args.max_minutes * 60
    cfg = load_config(cfg_path)

    reason = idle_reason(cfg, now_et())
    if reason:
        w = Watcher(cfg, out, fetch=lambda d: "")
        mode = {"paused": "paused", "off-season": "off-season"}.get(reason, "idle")
        if w.write_status(mode, message=reason):
            publish(args.publish_cmd)
        log.info("nothing to do: %s", reason)
        _gh_output("active", "false")
        return 0
    if args.check_only:
        _gh_output("active", "true")
        return 0

    username, password = os.environ.get("CLUB_USERNAME"), os.environ.get("CLUB_PASSWORD")
    if not username or not password:
        log.error("CLUB_USERNAME / CLUB_PASSWORD are not set")
        return 2

    from playwright.sync_api import sync_playwright
    from .club import Club, LoginError

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1100, "height": 1400})
        club = Club(page, username, password)
        fetch = club.sheet_html
        book = lambda slot, day: club.book(slot, day, cfg.party_size)
        w = Watcher(cfg, out, fetch=fetch, book=book)
        try:
            club.login()
        except LoginError as e:
            w.write_status("error", [], str(e))
            w.error_alert(str(e))
            publish(args.publish_cmd)
            return 1

        while True:
            started = _time.monotonic()
            changed = w.check_once()
            if w.failures >= 3:
                w.error_alert("Can't read the tee sheet (3 checks in a row). It'll keep trying.")
            if changed:
                publish(args.publish_cmd)

            refresh_config(cfg_path)
            cfg = w.cfg = load_config(cfg_path)
            reason = idle_reason(cfg, now_et())
            if reason:
                w.write_status({"paused": "paused", "off-season": "off-season"}.get(reason, "idle"),
                               message=reason)
                break
            wait = cfg.check_every_minutes * 60 - (_time.monotonic() - started)
            if _time.monotonic() + max(wait, 0) + 60 > deadline:
                break
            _time.sleep(max(wait, 0))
        browser.close()
    publish(args.publish_cmd)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yml")
    ap.add_argument("--out", default="_status")
    ap.add_argument("--max-minutes", type=float, default=25)
    ap.add_argument("--publish-cmd", default=None, help="shell command run whenever status changes")
    ap.add_argument("--once", action="store_true", help="single check, then exit")
    ap.add_argument("--check-only", action="store_true", help="only decide whether a run is needed")
    args = ap.parse_args(argv)
    if args.once:
        args.max_minutes = 0
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
