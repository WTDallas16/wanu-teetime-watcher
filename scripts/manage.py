"""Edit config.yml from the "Manage watches" GitHub action (keeps the comments at the top).

  python scripts/manage.py add --date 2026-10-17 [--before "1:30 PM"] [--after "9:00 AM"] [--note "..."]
  python scripts/manage.py remove --date 2026-10-17
  python scripts/manage.py pause | resume | autobook-on | autobook-off | clear-past
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

CONFIG = Path(__file__).resolve().parent.parent / "config.yml"
TODAY = datetime.now(ZoneInfo("America/New_York")).date()


def norm_time(s: str | None) -> str | None:
    if not s or not s.strip():
        return None
    t = s.strip().upper().replace(".", "")
    for fmt in ("%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H:%M"):
        try:
            return datetime.strptime(t, fmt).strftime("%I:%M %p").lstrip("0")
        except ValueError:
            pass
    sys.exit(f"Couldn't read the time {s!r}. Use something like 1:30 PM.")


def norm_date(s: str | None) -> str:
    if not s or not s.strip():
        sys.exit("A date is required, e.g. 2026-10-17 or 10/17.")
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m/%d", "%m-%d"):
        try:
            yearless = "%Y" not in fmt and "%y" not in fmt
            d = (datetime.strptime(f"{s.replace('-', '/')}/{TODAY.year}", fmt.replace("-", "/") + "/%Y") if yearless
                 else datetime.strptime(s, fmt)).date()
            if yearless:
                if d < TODAY:
                    d = d.replace(year=TODAY.year + 1)
            return d.isoformat()
        except ValueError:
            pass
    sys.exit(f"Couldn't read the date {s!r}. Use 2026-10-17 or 10/17.")


def set_scalar(text: str, key: str, value: str) -> str:
    new, n = re.subn(rf"^{key}:.*$", f"{key}: {value}", text, flags=re.M)
    if not n:
        sys.exit(f"{key} not found in config.yml")
    return new


def write_watches(text: str, watches: list[dict]) -> str:
    head = text[: text.index("\nwatches:")] + "\nwatches:"
    if not watches:
        return head + " []\n"
    lines = []
    for w in sorted(watches, key=lambda w: w["date"]):
        lines.append(f'  - date: "{w["date"]}"')
        for k in ("before", "after", "note"):
            if w.get(k):
                v = str(w[k]).replace('"', "'")
                lines.append(f'    {k}: "{v}"')
    return head + "\n" + "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["add", "remove", "pause", "resume", "autobook-on", "autobook-off", "clear-past"])
    ap.add_argument("--date")
    ap.add_argument("--before")
    ap.add_argument("--after")
    ap.add_argument("--note")
    a = ap.parse_args(argv)

    text = CONFIG.read_text()
    watches = [w for w in (yaml.safe_load(text).get("watches") or []) if w and w.get("date")]
    for w in watches:
        w["date"] = str(w["date"])
    live = [w for w in watches if date.fromisoformat(w["date"]) >= TODAY]

    if a.action == "pause":
        text = set_scalar(text, "enabled", "false"); msg = "Paused"
    elif a.action == "resume":
        text = set_scalar(text, "enabled", "true"); msg = "Resumed"
    elif a.action == "autobook-on":
        text = set_scalar(text, "auto_book", "true"); msg = "Auto-book on"
    elif a.action == "autobook-off":
        text = set_scalar(text, "auto_book", "false"); msg = "Auto-book off"
    elif a.action == "clear-past":
        text = write_watches(text, live); msg = f"Removed {len(watches) - len(live)} past watch(es)"
    elif a.action == "add":
        d = norm_date(a.date)
        entry = {"date": d, "before": norm_time(a.before), "after": norm_time(a.after), "note": (a.note or "").strip()}
        live = [w for w in live if w["date"] != d] + [entry]
        text = write_watches(text, live)
        msg = f"Watching {d}" + (f" before {entry['before']}" if entry["before"] else "")
    else:  # remove
        d = norm_date(a.date)
        if not any(w["date"] == d for w in live):
            sys.exit(f"No watch for {d}.")
        text = write_watches(text, [w for w in live if w["date"] != d])
        msg = f"Stopped watching {d}"

    yaml.safe_load(text)  # never write a broken file
    CONFIG.write_text(text)
    print(msg)


if __name__ == "__main__":
    main()
