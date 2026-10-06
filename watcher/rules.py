"""Settings + the decision logic: which open tee times are worth telling you about."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from .sheet import Sheet, Slot, fmt_time, parse_time

TZ = ZoneInfo("America/New_York")
LOOKAHEAD_DAYS = 8  # the club opens the sheet 7 days out


@dataclass
class Watch:
    day: date
    before: time | None = None
    after: time | None = None
    note: str = ""

    @property
    def key(self) -> str:
        return self.day.isoformat()


@dataclass
class Config:
    enabled: bool
    season_start: tuple[int, int]
    season_end: tuple[int, int]
    active_start: time
    active_end: time
    check_every_minutes: int
    default_cutoff: time
    party_size: int
    min_hours_notice: float
    auto_book: bool
    watches: list[Watch]


def _hm(s: str) -> time:
    return datetime.strptime(str(s), "%H:%M").time()


def _md(s: str) -> tuple[int, int]:
    m, d = str(s).split("-")
    return int(m), int(d)


def load_config(path: str | Path = "config.yml") -> Config:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    season = raw.get("season") or {}
    hours = raw.get("active_hours") or {}
    watches = []
    for w in raw.get("watches") or []:
        if not w or not w.get("date"):
            continue
        watches.append(Watch(
            day=date.fromisoformat(str(w["date"])),
            before=parse_time(w["before"]) if w.get("before") else None,
            after=parse_time(w["after"]) if w.get("after") else None,
            note=str(w.get("note") or ""),
        ))
    return Config(
        enabled=bool(raw.get("enabled", True)),
        season_start=_md(season.get("start", "01-01")),
        season_end=_md(season.get("end", "12-31")),
        active_start=_hm(hours.get("start", "00:00")),
        active_end=_hm(hours.get("end", "23:59")),
        check_every_minutes=max(1, int(raw.get("check_every_minutes", 2))),
        default_cutoff=parse_time(raw.get("default_cutoff", "2:00 PM")),
        party_size=int(raw.get("party_size", 4)),
        min_hours_notice=float(raw.get("min_hours_notice", 24)),
        auto_book=bool(raw.get("auto_book", False)),
        watches=sorted(watches, key=lambda w: w.day),
    )


# ── when to run ────────────────────────────────────────────────

def in_season(cfg: Config, now: datetime) -> bool:
    md = (now.month, now.day)
    return cfg.season_start <= md <= cfg.season_end


def in_active_hours(cfg: Config, now: datetime) -> bool:
    return cfg.active_start <= now.time() <= cfg.active_end


def live_watches(cfg: Config, now: datetime) -> list[Watch]:
    """Watches for today through the end of the club's booking window."""
    today = now.date()
    return [w for w in cfg.watches if today <= w.day <= today + timedelta(days=LOOKAHEAD_DAYS)]


def idle_reason(cfg: Config, now: datetime) -> str | None:
    if not cfg.enabled:
        return "paused"
    if not in_season(cfg, now):
        return "off-season"
    if not live_watches(cfg, now):
        return "nothing to watch"
    if not in_active_hours(cfg, now):
        return "outside active hours"
    return None


# ── what counts as a good tee time ─────────────────────────────

@dataclass
class Match:
    slot: Slot
    day: date
    call_shop: bool          # inside the notice window: phone the pro shop instead

    @property
    def when(self) -> datetime:
        return datetime.combine(self.day, self.slot.t, TZ)

    def to_dict(self) -> dict:
        return {
            "time": self.slot.time,
            "spots": self.slot.spots,
            "call_shop": self.call_shop,
            "book_url": self.slot.book_url(),
        }


def cutoff_for(watch: Watch, sheet: Sheet, cfg: Config) -> tuple[time, str]:
    """Return (cutoff, why). Specific time > your existing booking > default."""
    if watch.before:
        return watch.before, "your target time"
    mine = sorted(s.t for s in sheet.my_slots())
    if mine:
        return mine[0], "your current tee time"
    return cfg.default_cutoff, "default cutoff"


def find_matches(watch: Watch, sheet: Sheet, cfg: Config, now: datetime) -> list[Match]:
    cutoff, _ = cutoff_for(watch, sheet, cfg)
    out = []
    for s in sheet.open_slots(cfg.party_size):
        t = s.t
        if t >= cutoff:
            continue
        if watch.after and t < watch.after:
            continue
        when = datetime.combine(watch.day, t, TZ)
        if when <= now:
            continue
        call_shop = (when - now) < timedelta(hours=cfg.min_hours_notice)
        out.append(Match(slot=s, day=watch.day, call_shop=call_shop))
    return sorted(out, key=lambda m: m.slot.t)


def describe_cutoff(watch: Watch, sheet: Sheet, cfg: Config) -> dict:
    cutoff, why = cutoff_for(watch, sheet, cfg)
    return {"cutoff": fmt_time(cutoff), "cutoff_source": why}
