# Wanumetonomy tee time watcher

Watches the club's tee sheet for tee times that members drop, pushes a notification to your
phone the moment an earlier time opens up, and gives you a one-tap link to book it.

- **Day watch:** any open foursome before your current tee time that day, or before
  `default_cutoff` (2:00 PM) when you have no tee time that day.
- **Specific time:** any open foursome before the time you give.
- Times under 24 hours away are flagged *call the pro shop* and never auto-booked.
- Optional **auto-book** takes the earliest match the moment it appears: a new tee time under your name with
  TBD players. You cancel the old tee time yourself. If you hold two tee times on the same day, it reminds you.
- **Pause** anytime. It also switches itself off between Dec 31 and Mar 15.

## How it works

| Piece | Where |
|---|---|
| Watcher (Python + headless Chromium) | GitHub Actions, `.github/workflows/watch.yml`. It runs from 6 AM to 10 PM ET and checks every 2 minutes. |
| Settings & watched dates | `config.yml` (edit it, or use the **Manage watches** action from the GitHub app) |
| Your booking site | GitHub Pages, served from the `status` branch |
| Push notifications | [ntfy](https://ntfy.sh): free app, no account |

The club's site is Clubessential. The watcher signs in the same way you do and reads the same tee sheet.
**Book** opens the club's own booking form for that time, and the form holds the time for about 10 minutes.

## Setup (one time)

1. **Secrets:** Settings → Secrets and variables → Actions → *New repository secret*:
   - `CLUB_USERNAME`: your member login
   - `CLUB_PASSWORD`: your club password
   - `NTFY_TOPIC`: your private channel name (long and random; anyone who knows it can read your alerts)
2. **Phone:** install **ntfy** (App Store / Google Play), tap **+**, and subscribe to that same topic name.
3. **Site:** Settings → Pages → *Deploy from a branch* → `status` / `(root)`. The `status` branch appears after the first run.
4. **First run:** Actions → *Watch tee sheet* → **Run workflow**.
5. On your phone, sign in once to the club website in your browser, so **Book** links open straight into the form.

## Everyday use

- **Add or remove a date:** in the GitHub app, open Actions → *Manage watches* → **Run workflow**.
  Pick *add watch*, enter a date (`10/17`) and optionally a time (`1:30 PM`).
- **Pause / resume / auto-book on/off:** same action.
- **Off-season:** nothing to do. You can also disable the *Watch tee sheet* workflow entirely.

## Development

```
pip install -r requirements.txt pytest && python -m playwright install chromium
python tests/make_fixtures.py
python -m pytest -q
```
The parser tests use tee sheet markup copied from the live site (names removed). `tests/test_club_mock.py` drives the
real browser automation (sign-in, changing dates, an expired session) against a fake copy of the site.

## Notes

- GitHub's schedule can start runs a few minutes late. Each run covers about 25 minutes, so there's always one in line behind it.
- GitHub pauses schedules in repos with no activity for 60 days. If that happens, re-enable the workflow from the Actions tab.
- The watcher's traffic comes from GitHub's servers, not your home connection. The club does see your member account
  loading the tee sheet regularly. Every 2 minutes is gentle, so keep it there.
