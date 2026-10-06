"""Builds test fixtures that mirror the real Clubessential tee sheet markup.

The row templates below were copied from the live Wanumetonomy tee sheet on
2026-10-06 (member names replaced). Re-run this script to regenerate the
fixture files:  python tests/make_fixtures.py
"""
from pathlib import Path

HERE = Path(__file__).parent / "fixtures"

TIME_TD = (
    '<td style="border-bottom: 1px solid rgb(85, 85, 85);" class="{p} {p}TimeText TimeText">'
    '<span class="timeText">{time}<br> <span class="startTee"> 1<sup>st</sup> TEE </span> </span></td>'
)

OPEN_TEE = (
    '<div class="{held}"> <span class=" ##ISCROSSOVER##"> <div class="openTee ##COURSENAME##"> '
    '<div style="width: 100%; cursor: pointer;line-height:25px;" onclick="{onclick}">'
    '<span style="font-size: 12px; font-family: Arial;"> <span class="requestText">Request</span> '
    '<span class="reserveText">Reserve</span> <span class="eventTee"> Event </span> </span></div> </div> </span> </div>'
)


def res_td(p, inner):
    return (
        f'<td style="width: 60px; border-bottom: 1px solid rgb(85, 85, 85);" class="{p}ResSection {p} openTC">'
        f"{inner}</td>"
    )


def party_td(p, title="", block="", reserved=""):
    blocked = "resSectionBlocked1" if block else "resSection"
    return (
        f'<td class="partyHolder {p}Party " style=""> <span style="font-family: Arial;"> <div class="{blocked}"> '
        f'<span class="title"> <span class="blockBorder">{block}</span> '
        f'<span class="timeRangeTitle {title}" style=""> {title}</span> {reserved}</span></div> </span> </td>'
    )


def players(names, edit_id=None, mine=False, need=False):
    onclick = f"javascript:LaunchTeeEditor({edit_id});" if edit_id else ""
    cls = "hasUserInRes" if mine else ("hasNeedPlayerRes" if need else "")
    out = []
    for n in names:
        kind = "NC_TBDPlayer NC_NeedPlayer" if n == "Need Player" else (
            "NC_GuestPlayer" if "Guest" in n else "NC_MemberPlayer")
        out.append(
            f'<div class="{kind} playerJQ"><div class="playerName noPlayerSelect"><span class="cancelTrashButton"></span>'
            f'<span class="fullName">{n} </span></div> <div class="needPlayerName" onclick="{onclick}">JOIN</div></div>'
        )
    return (
        f'<div class="NC_Reserved NC_Reserved{len(names)} resJQ"> <span class="##PLAYERSELECTCLASS## {cls} "> '
        f'<div class="partyinfo" style="float: left;"> <div onclick="{onclick}" class="clickEdit"><span class="editbutton">Edit</span></div> '
        f'<span class="reservedtext">Reserved</span> {"".join(out)}</div> </span> </div>'
    )


def row(time, *, kind, date="10/10/2026", title="", block="", names=None, edit_id=None, mine=False,
        need=False, held=False, xsome=4):
    open_slot = kind == "open"
    p = "NC_TimeSlotPanelSlotAvailable" if open_slot else "NC_TimeSlotPanelNoSlots"
    if open_slot:
        onclick = f"javascript:LaunchReserver('1','{date}','{time}','1','0','{xsome}','false','');"
        inner = '<div class="reSection">' + OPEN_TEE.format(
            held="NC_AdminHeld openJQ" if held else "NC_AdminSlotAvailable openJQ", onclick=onclick) + "</div>"
    elif kind == "full_party":  # four players: no reserve widget at all
        inner = '<div class="reSection"> </div>'
    else:
        wrap = "reSectionBlocked" if block else "reSection"
        inner = f'<div class="{wrap}">' + OPEN_TEE.format(held="NC_AdminSlotAvailable openJQ", onclick="") + "</div>"
    reserved = players(names, edit_id, mine, need) if names else ""
    return (
        f'<tr class="{p}Full {p}"> {TIME_TD.format(p=p, time=time)} {res_td(p, inner)} '
        f"{party_td(p, title, block, reserved)} </tr>"
    )


def page(header, rows, next_avail=""):
    return (
        "<html><body><div>Please call the golf shop for same day bookings.</div>"
        f"<div>The next available tee times become available on {next_avail}.</div>"
        f'<table><tr><td class="header">{header}</td></tr>\n' + "\n".join(rows) + "\n</table></body></html>"
    )


SAT = page("Wanumetonomy - Saturday, October 10, 2026", [
    row("12:01 AM", kind="none", title="Proshop Only"),
    row("7:00 AM", kind="none", block="WANU CUP FINALS"),
    row("11:30 AM", kind="none", block="SATURDAY WEEKEND LADIES"),
    row("12:06 PM", kind="none", names=["Member X", "Member X"]),
    row("12:15 PM", kind="full_party", names=["Member X", "Member X", "Guest Tbd", "guest Tbd"]),
    row("1:00 PM", kind="none", block="SATURDAY 12:00ERS"),
    row("1:45 PM", kind="open"),                       # a dropped time we'd want
    row("1:54 PM", kind="open", held=True),            # someone else is mid-booking
    row("2:30 PM", kind="none", names=["Member X", "Guest", "Guest"]),
    row("2:39 PM", kind="full_party", names=["Member X", "Member Me", "Guest TBA", "Guest TBA"],
        edit_id=37973, mine=True),
    row("3:51 PM", kind="open"),
    row("4:09 PM", kind="none", names=["Member X", "Need Player"], edit_id=38009, need=True),
    row("4:18 PM", kind="open"),
    row("5:57 PM", kind="open"),
])

MON = page("Wanumetonomy - Monday, October 12, 2026", [
    row("12:24 PM", kind="none", block="MONDAY 12:00ERS"),
    row("12:33 PM", kind="none", date="10/12/2026", names=["Member X"]),
    row("2:30 PM", kind="none"),   # empty but not bookable online for this member
    row("3:00 PM", kind="open", date="10/12/2026", xsome=2),  # only two spots (hypothetical)
])

UNOPENED = page("Wanumetonomy - Tuesday, October 20, 2026", [
    row("7:00 AM", kind="none"),
    row("1:00 PM", kind="none"),
], next_avail="Tuesday, October 13, 2026 12:00 AM")

if __name__ == "__main__":
    HERE.mkdir(exist_ok=True)
    (HERE / "sheet_2026-10-10.html").write_text(SAT)
    (HERE / "sheet_2026-10-12.html").write_text(MON)
    (HERE / "sheet_2026-10-20.html").write_text(UNOPENED)
    print("fixtures written to", HERE)
