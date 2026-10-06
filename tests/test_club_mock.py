"""Exercise the real browser automation (sign-in, date change, session expiry) against a
fake copy of the club site served through Playwright request interception."""
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs

import pytest

pw = pytest.importorskip("playwright.sync_api")

from watcher.club import Club, LoginError, HOME_URL, LOGIN_URL, TEE_SHEET_URL
from watcher.sheet import parse_sheet

FX = Path(__file__).parent / "fixtures"

LOGIN_PAGE = """<html><body><script>
var txtUsernameClientID='u_box', txtPasswordClientID='p_box';
function go(){ if(document.getElementById('u_box').value==='member1' && document.getElementById('p_box').value==='secret'){
  document.cookie='sess=1; path=/'; setTimeout(function(){location.href='%s'},300);} }
</script><input type=text id=u_box placeholder=Username><input type=password id=p_box>
<input type=button id=btnSecureLogin value='Sign In' onclick='go();return false;'></body></html>""" % HOME_URL

HOME = "<html><body>WELCOME BACK <a href='/x?logout=true'>Logout</a></body></html>"
PUBLIC = "<html><body>Public Home <a href='/login'>Member Login</a></body></html>"


def sheet_page(day_file):
    body = (FX / day_file).read_text()
    form = ("<form method=post id=f><input id=txtDate name=txtDate></form><script>"
            "function changeDate(d){document.getElementById('txtDate').value=d;document.getElementById('f').submit();}"
            "</script><a href='/x?logout=true'>Logout</a>")
    return body.replace("<body>", "<body>" + form, 1)


@pytest.fixture
def site():
    state = {"expire_next": False, "logins": 0}
    with pw.sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        page = ctx.new_page()

        def handler(route, request):
            url = request.url
            cookies = request.headers.get("cookie", "")
            signed_in = "sess=1" in cookies and not state["expire_next"]
            if url.startswith(LOGIN_URL):
                state["logins"] += 1
                state["expire_next"] = False
                return route.fulfill(body=LOGIN_PAGE, content_type="text/html")
            if "p=home" in url:
                return route.fulfill(body=PUBLIC, content_type="text/html")
            if not signed_in:
                # what the real site does: a tiny page whose script bounces to the public home page
                return route.fulfill(content_type="text/html", body="<html><head><script>"
                                     "window.location.href='https://wanumetonomy.com/default.aspx?p=home&E=6';"
                                     "</script></head><body></body></html>")
            if url == HOME_URL:
                return route.fulfill(body=HOME, content_type="text/html")
            if url == TEE_SHEET_URL:
                if request.method == "POST":
                    d = parse_qs(request.post_data or "").get("txtDate", [""])[0]
                    name = {"10/10/2026": "sheet_2026-10-10.html", "10/12/2026": "sheet_2026-10-12.html"}.get(d, "sheet_2026-10-20.html")
                else:
                    name = "sheet_2026-10-20.html"
                return route.fulfill(body=sheet_page(name), content_type="text/html")
            return route.fulfill(status=404, body="nope")

        page.route("https://wanumetonomy.com/**", handler)
        yield page, state
        browser.close()


def test_login_and_read_two_days(site):
    page, state = site
    club = Club(page, "member1", "secret")
    club.login()
    sat = parse_sheet(club.sheet_html(date(2026, 10, 10)))
    assert sat.day == date(2026, 10, 10) and [s.time for s in sat.my_slots()] == ["2:39 PM"]
    mon = parse_sheet(club.sheet_html(date(2026, 10, 12)))
    assert mon.day == date(2026, 10, 12)
    assert state["logins"] == 1


def test_bad_password(site):
    page, _ = site
    with pytest.raises(LoginError):
        Club(page, "member1", "wrong").login()


def test_recovers_when_session_expires(site):
    page, state = site
    club = Club(page, "member1", "secret")
    club.login()
    club.sheet_html(date(2026, 10, 10))
    state["expire_next"] = True        # club drops the session
    sat = parse_sheet(club.sheet_html(date(2026, 10, 10)))
    assert sat.day == date(2026, 10, 10) and state["logins"] == 2
