"""Drives the club website with a headless browser: sign in, read a day's tee sheet, book a time."""
from __future__ import annotations

import logging
import re
from datetime import date

from playwright.sync_api import Page, TimeoutError as PWTimeout

from .sheet import Slot, parse_sheet

log = logging.getLogger(__name__)

SITE = "https://wanumetonomy.com"
LOGIN_URL = f"{SITE}/login"
HOME_URL = f"{SITE}/default.aspx?p=dynamicmodule&pageid=7&ssid=100033&vnf=1"
TEE_SHEET_URL = f"{SITE}/Default.aspx?p=dynamicmodule&pageid=21&tt=booking&ssid=100067&vnf=1"
FORM = "ctl01_ctrl_MakeTeeTime_"


class LoginError(RuntimeError):
    pass


class Club:
    def __init__(self, page: Page, username: str, password: str):
        self.page = page
        self.username = username
        self.password = password
        page.set_default_timeout(30_000)

    # ── session ──────────────────────────────────────────────
    def _logged_out(self, check_nav: bool = False) -> bool:
        """Private pages bounce signed-out visitors to the public home page (p=home)."""
        p = self.page
        if "p=home" in p.url.lower() or p.url.rstrip("/").lower().endswith("/login"):
            return True
        if p.locator("input[type=password]:visible").count() > 0:
            return True
        return check_nav and p.locator("a:has-text('Logout')").count() == 0

    def login(self) -> None:
        p = self.page
        log.info("signing in")
        p.goto(LOGIN_URL, wait_until="domcontentloaded")
        # The login page names its fields in globals (txtUsernameClientID / txtPasswordClientID).
        ids = p.evaluate("""() => ({
            u: typeof txtUsernameClientID !== 'undefined' ? txtUsernameClientID : null,
            pw: typeof txtPasswordClientID !== 'undefined' ? txtPasswordClientID : null })""")
        user = p.locator(f"#{ids['u']}") if ids.get("u") else p.locator("input[placeholder='Username']").first
        pw = p.locator(f"#{ids['pw']}") if ids.get("pw") else p.locator("input[type=password]").first
        user.fill(self.username)
        pw.fill(self.password)
        # Sign In runs a 3-step encrypted handshake over AJAX, then redirects to the member home.
        p.locator("#btnSecureLogin").click()
        try:
            p.wait_for_url(lambda u: "/login" not in u.lower(), timeout=45_000)
            p.wait_for_load_state("domcontentloaded")
        except PWTimeout:
            pass
        p.goto(HOME_URL, wait_until="domcontentloaded")
        if self._logged_out(check_nav=True):
            raise LoginError("Sign-in failed — check the CLUB_USERNAME / CLUB_PASSWORD secrets.")
        log.info("signed in")

    # ── reading ──────────────────────────────────────────────
    def _open_tee_sheet(self) -> None:
        p = self.page
        p.goto(TEE_SHEET_URL, wait_until="domcontentloaded")
        if self._logged_out() or not p.evaluate("typeof changeDate === 'function'"):
            self.login()
            p.goto(TEE_SHEET_URL, wait_until="domcontentloaded")
            if not p.evaluate("typeof changeDate === 'function'"):
                raise RuntimeError("Tee sheet did not load after signing in.")

    def sheet_html(self, day: date) -> str:
        p = self.page
        if "pageid=21" not in p.url or not p.evaluate("typeof changeDate === 'function'"):
            self._open_tee_sheet()
        try:
            self._change_date(day)
        except Exception:
            if not self._logged_out():
                raise
            self._open_tee_sheet()       # session expired mid-run: sign in again and retry once
            self._change_date(day)
        html = p.content()
        sheet = parse_sheet(html)
        if sheet.day and sheet.day != day:
            raise RuntimeError(f"Asked for {day} but the club showed {sheet.day}.")
        return html

    def _change_date(self, day: date) -> None:
        """Same as clicking the date arrows: the page posts back and re-renders for that day."""
        p = self.page
        target = f"{day.month}/{day.day}/{day.year}"
        header = f"{day.strftime('%B')} {day.day}, {day.year}"  # "October 10, 2026"
        try:
            with p.expect_navigation(wait_until="domcontentloaded", timeout=30_000):
                try:
                    p.evaluate(f"changeDate('{target}')")
                except Exception:
                    pass  # the page unloading mid-call is expected
        except PWTimeout:
            pass  # some skins refresh in place instead of reloading
        p.wait_for_function(
            "h => document.body && document.body.innerText.includes(h)"
            " && document.querySelectorAll('span.timeText').length > 0",
            arg=header, timeout=30_000)

    # ── booking ──────────────────────────────────────────────
    def book(self, slot: Slot, day: date, party_size: int) -> tuple[bool, str]:
        """Book a NEW tee time for this slot: you as player 1, TBD for the rest."""
        p = self.page
        url = slot.book_url()
        if not url:
            return False, "slot has no booking link"
        p.goto(url, wait_until="domcontentloaded")
        if self._logged_out():
            self.login()
            p.goto(url, wait_until="domcontentloaded")
        p.wait_for_function(f"typeof $find === 'function' && !!$find('{FORM}drpPartySize_tCombo')")

        shown = p.evaluate(f"$find('{FORM}drpTime_tCombo').get_text()").strip()
        if shown.replace(" ", "").upper() != slot.time.replace(" ", "").upper():
            return False, f"booking form opened for {shown!r}, expected {slot.time}"

        if party_size > 1:
            p.evaluate(f"$find('{FORM}drpPartySize_tCombo').findItemByValue('{party_size}').select()")
            p.wait_for_selector(f"#{FORM}P{party_size}_PCombo_PlayerName_Input", state="visible")
            p.wait_for_load_state("networkidle")
            for i in range(2, party_size + 1):
                box = p.locator(f"#{FORM}P{i}_PCombo_PlayerName_Input")
                box.click()
                p.locator(".TBDSpecialSelect:visible").first.click()
                p.wait_for_function(
                    f"$find('{FORM}P{i}_PCombo_PlayerName').get_text() !== 'Type Player Name'", timeout=10_000)

        with p.expect_navigation(wait_until="domcontentloaded", timeout=45_000):
            p.locator(f"#{FORM}lbBook").click()
        after = re.sub(r"\s+", " ", p.inner_text("body"))[:400]

        # Confirm on the tee sheet itself.
        sheet = parse_sheet(self.sheet_html(day))
        if any(s.mine and s.time == slot.time for s in sheet.slots):
            return True, "booked"
        return False, f"club did not confirm the booking. Page said: {after}"
