import json
from datetime import date, datetime
from pathlib import Path

import pytest

from watcher import main as M, notify
from watcher.rules import TZ, Watch, find_matches, idle_reason, load_config, cutoff_for
from watcher.sheet import parse_sheet, parse_time

FX = Path(__file__).parent / "fixtures"
SAT = date(2026, 10, 10)


def sheet(name):
    return parse_sheet((FX / name).read_text())


def cfg(tmp_path, **over):
    base = {
        "enabled": True, "season": {"start": "03-15", "end": "12-31"},
        "active_hours": {"start": "06:00", "end": "22:00"}, "check_every_minutes": 2,
        "default_cutoff": "2:00 PM", "party_size": 4, "min_hours_notice": 24, "auto_book": False,
        "watches": [{"date": "2026-10-10"}],
    }
    base.update(over)
    p = tmp_path / "config.yml"
    import yaml
    p.write_text(yaml.safe_dump(base))
    return load_config(p)


# ── parsing ────────────────────────────────────────────────────

def test_parse_saturday_statuses():
    s = sheet("sheet_2026-10-10.html")
    assert s.day == SAT
    by = {x.time: x for x in s.slots}
    assert by["12:01 AM"].status == "blocked" and by["12:01 AM"].label == "Proshop Only"
    assert by["7:00 AM"].status == "blocked" and by["7:00 AM"].label == "WANU CUP FINALS"
    assert by["12:06 PM"].status == "booked" and by["12:06 PM"].players == 2
    assert by["4:09 PM"].status == "booked" and by["4:09 PM"].players == 1  # "Need Player" isn't a player
    assert by["1:45 PM"].status == "open" and by["1:45 PM"].spots == 4
    assert by["1:54 PM"].status == "held"
    mine = s.my_slots()
    assert [m.time for m in mine] == ["2:39 PM"] and mine[0].tee_time_id == 37973


def test_book_url_matches_club_link():
    s = sheet("sheet_2026-10-10.html")
    url = next(x for x in s.slots if x.time == "1:45 PM").book_url()
    assert "tt=MakeTeeTime" in url and "date=10/10/2026" in url and "time=1:45%20PM" in url and "xsome=4" in url


def test_empty_but_unbookable_row_is_not_open():
    s = sheet("sheet_2026-10-12.html")
    by = {x.time: x for x in s.slots}
    assert by["2:30 PM"].status == "unavailable"
    assert by["3:00 PM"].status == "open" and by["3:00 PM"].spots == 2
    assert s.open_slots(4) == [] and len(s.open_slots(2)) == 1


def test_unopened_date():
    s = sheet("sheet_2026-10-20.html")
    assert s.opens_at.startswith("Tuesday, October 13, 2026")
    assert s.open_slots(1) == []


# ── rules ──────────────────────────────────────────────────────

def test_day_watch_uses_my_booking_as_cutoff(tmp_path):
    c = cfg(tmp_path)
    s = sheet("sheet_2026-10-10.html")
    w = c.watches[0]
    assert cutoff_for(w, s, c) == (parse_time("2:39 PM"), "your current tee time")
    now = datetime(2026, 10, 7, 9, 0, tzinfo=TZ)
    ms = find_matches(w, s, c, now)
    assert [m.slot.time for m in ms] == ["1:45 PM"]       # held 1:54 and later 3:51+ excluded
    assert ms[0].call_shop is False


def test_day_watch_without_booking_uses_default(tmp_path):
    c = cfg(tmp_path, watches=[{"date": "2026-10-12"}], party_size=2)
    s = sheet("sheet_2026-10-12.html")
    assert cutoff_for(c.watches[0], s, c)[1] == "default cutoff"
    now = datetime(2026, 10, 8, 9, 0, tzinfo=TZ)
    assert find_matches(c.watches[0], s, c, now) == []   # 3:00 PM is after the 2:00 PM default


def test_specific_time_and_after(tmp_path):
    c = cfg(tmp_path, watches=[{"date": "2026-10-10", "before": "4:30 PM", "after": "2:00 PM"}])
    s = sheet("sheet_2026-10-10.html")
    now = datetime(2026, 10, 7, 9, 0, tzinfo=TZ)
    assert [m.slot.time for m in find_matches(c.watches[0], s, c, now)] == ["3:51 PM", "4:18 PM"]


def test_inside_24h_flags_call_shop(tmp_path):
    c = cfg(tmp_path)
    s = sheet("sheet_2026-10-10.html")
    now = datetime(2026, 10, 9, 18, 0, tzinfo=TZ)
    ms = find_matches(c.watches[0], s, c, now)
    assert ms and ms[0].call_shop


def test_idle_reasons(tmp_path):
    assert idle_reason(cfg(tmp_path, enabled=False), datetime(2026, 10, 7, 9, tzinfo=TZ)) == "paused"
    assert idle_reason(cfg(tmp_path), datetime(2026, 1, 7, 9, tzinfo=TZ)) == "off-season"
    assert idle_reason(cfg(tmp_path), datetime(2026, 10, 7, 23, tzinfo=TZ)) == "outside active hours"
    assert idle_reason(cfg(tmp_path), datetime(2026, 10, 11, 9, tzinfo=TZ)) == "nothing to watch"
    assert idle_reason(cfg(tmp_path), datetime(2026, 10, 7, 9, tzinfo=TZ)) is None


# ── end to end with fake site + captured notifications ─────────

@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(notify, "send", lambda title, msg, **kw: out.append((title, msg, kw)) or True)
    monkeypatch.setattr(M, "now_et", lambda: datetime(2026, 10, 7, 9, 0, tzinfo=TZ))
    return out


def test_alerts_once_then_again_if_it_reappears(tmp_path, sent):
    c = cfg(tmp_path)
    html = {"v": (FX / "sheet_2026-10-10.html").read_text()}
    w = M.Watcher(c, tmp_path / "out", fetch=lambda d: html["v"])

    w.check_once()
    assert len(sent) == 1 and sent[0][0] == "1:45 PM opened — Sat Oct 10"
    assert "Book 1:45 PM" in sent[0][2]["actions"][0]["label"]

    w.check_once()                       # same sheet → no repeat
    assert len(sent) == 1

    # someone grabs it: the reserve link disappears
    html["v"] = (FX / "sheet_2026-10-10.html").read_text().replace(
        "LaunchReserver('1','10/10/2026','1:45 PM'", "Nope('1','10/10/2026','1:45 PM'")
    w.check_once()
    assert len(sent) == 1
    html["v"] = (FX / "sheet_2026-10-10.html").read_text()   # dropped again
    w.check_once()
    assert len(sent) == 2

    status = json.loads((tmp_path / "out" / "status.json").read_text())
    card = status["watches"][0]
    assert status["mode"] == "watching" and card["cutoff"] == "2:39 PM"
    assert card["my_times"] == ["2:39 PM"] and card["matches"][0]["time"] == "1:45 PM"


def test_auto_book_calls_book_and_reports(tmp_path, sent):
    c = cfg(tmp_path, auto_book=True)
    calls = []
    w = M.Watcher(c, tmp_path / "out", fetch=lambda d: (FX / "sheet_2026-10-10.html").read_text(),
                  book=lambda slot, day: calls.append(slot.time) or (True, "booked"))
    w.check_once()
    assert calls == ["1:45 PM"]
    assert sent[0][0] == "Booked 1:45 PM — Sat Oct 10" and "cancel your 2:39 PM" in sent[0][1]
    w.check_once()
    assert calls == ["1:45 PM"]            # never retries the same time


def test_two_bookings_reminder(tmp_path, sent):
    c = cfg(tmp_path)
    html = (FX / "sheet_2026-10-10.html").read_text()
    # pretend we also hold 12:06
    html = html.replace('##PLAYERSELECTCLASS##  "', '##PLAYERSELECTCLASS## hasUserInRes "', 1)
    w = M.Watcher(c, tmp_path / "out", fetch=lambda d: html)
    w.check_once()
    titles = [s[0] for s in sent]
    assert "You have 2 tee times Sat Oct 10" in titles
    # cutoff now follows the earliest booking, so 1:45 no longer qualifies
    assert not any("opened" in t for t in titles)
