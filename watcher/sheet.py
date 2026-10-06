"""Parse a Clubessential (NetCaddy) member tee sheet into structured slots.

How the club's page marks each row (learned from the live site):
  * Bookable, fully open  -> row has an onclick LaunchReserver('course','date','time','hole','numholes','xsome',...)
                             and no NC_Reserved party block.
  * Held                  -> same as open but the widget class is NC_AdminHeld (someone has the booking
                             form open; it frees up again after ~10 minutes if they don't finish).
  * Blocked               -> blockBorder text, e.g. "WANU CUP FINALS", or a timeRangeTitle like "Proshop Only".
  * Booked                -> an NC_Reserved block listing players; "hasUserInRes" means you're in it.
  * Unavailable           -> empty row with no LaunchReserver (not bookable online for you, or not open yet).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, time

from bs4 import BeautifulSoup

RESERVER_RE = re.compile(
    r"LaunchReserver\('(?P<course>[^']*)','(?P<date>[^']*)','(?P<time>[^']*)','(?P<hole>[^']*)',"
    r"'(?P<numholes>[^']*)','(?P<xsome>[^']*)'"
)
EDITOR_RE = re.compile(r"LaunchTeeEditor\((\d+)\)")
HEADER_RE = re.compile(r"Wanumetonomy\s*-\s*[A-Za-z]+,\s*([A-Za-z]+ \d{1,2}, \d{4})")
TIME_RE = re.compile(r"\d{1,2}:\d{2}\s*[AP]M", re.I)

SITE = "https://wanumetonomy.com"


def parse_time(s: str) -> time:
    return datetime.strptime(s.strip().upper().replace(" ", ""), "%I:%M%p").time()


def fmt_time(t: time) -> str:
    return t.strftime("%I:%M %p").lstrip("0")


@dataclass
class Slot:
    time: str                  # "1:45 PM"
    status: str                # open | held | booked | blocked | unavailable
    spots: int = 0             # open spots when status is open/held
    label: str = ""            # block name, e.g. "WANU CUP FINALS"
    players: int = 0           # number of players booked
    mine: bool = False         # you're in this tee time
    tee_time_id: int | None = None
    reserver: dict = field(default_factory=dict)

    @property
    def t(self) -> time:
        return parse_time(self.time)

    def book_url(self) -> str | None:
        """Direct link to the club's own booking form for this slot (holds it ~10 min while open)."""
        r = self.reserver
        if not r:
            return None
        return (
            f"{SITE}/default.aspx?p=NetcaddyPop&tt=MakeTeeTime&NoModResize=1&NoNav=1&ShowFooter=False"
            f"&courseid={r['course']}&date={r['date']}&time={r['time'].replace(' ', '%20')}"
            f"&hole={r['hole']}&numholes={r['numholes']}&xsome={r['xsome']}&startletter="
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["book_url"] = self.book_url()
        return d


@dataclass
class Sheet:
    day: date | None
    slots: list[Slot]
    opens_at: str = ""         # "Tuesday, October 13, 2026 12:00 AM" when the date isn't bookable yet

    def open_slots(self, party_size: int = 4) -> list[Slot]:
        return [s for s in self.slots if s.status == "open" and s.spots >= party_size]

    def my_slots(self) -> list[Slot]:
        return [s for s in self.slots if s.mine]


def parse_sheet(html: str) -> Sheet:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    day = None
    m = HEADER_RE.search(text)
    if m:
        day = datetime.strptime(m.group(1), "%B %d, %Y").date()

    opens_at = ""
    m = re.search(r"next available tee times become available on ([^.]+?)\.", text)
    if m:
        opens_at = m.group(1).strip()

    slots: list[Slot] = []
    seen = set()
    for span in soup.select("span.timeText"):
        row = span.find_parent("tr")
        if row is None or id(row) in seen:
            continue
        seen.add(id(row))
        tm = TIME_RE.search(span.get_text(" ", strip=True))
        if not tm:
            continue
        slots.append(_parse_row(row, fmt_time(parse_time(tm.group(0)))))
    return Sheet(day=day, slots=slots, opens_at=opens_at)


def _parse_row(row, t: str) -> Slot:
    slot = Slot(time=t, status="unavailable")

    block = row.select_one(".blockBorder")
    title = row.select_one(".timeRangeTitle")
    label = (block.get_text(" ", strip=True) if block else "") or (title.get_text(" ", strip=True) if title else "")
    slot.label = label

    party = row.select_one(".NC_Reserved")
    if party is not None:
        names = [n.get_text(" ", strip=True) for n in party.select(".fullName")]
        slot.players = sum(1 for n in names if n and n.lower() != "need player")
        slot.mine = party.select_one(".hasUserInRes") is not None
        em = EDITOR_RE.search(str(party))
        if em:
            slot.tee_time_id = int(em.group(1))
        slot.status = "booked"
        return slot

    reserver = None
    for el in row.select("[onclick]"):
        rm = RESERVER_RE.search(el.get("onclick", ""))
        if rm:
            reserver = rm.groupdict()
            break

    if reserver:
        slot.reserver = reserver
        try:
            slot.spots = int(reserver["xsome"])
        except ValueError:
            slot.spots = 0
        slot.status = "held" if row.select_one(".NC_AdminHeld") else "open"
    elif label:
        slot.status = "blocked"
    return slot
