#!/usr/bin/env bash
# Commit the site + latest status.json to the `status` branch (served by GitHub Pages).
set -euo pipefail
cd "${STATUS_DIR:-_status}"
cp ../site/index.html index.html
touch .nojekyll
git add -A
if git diff --cached --quiet; then exit 0; fi
git -c user.name="tee-time-watcher" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
    commit -q -m "status $(date -u +%Y-%m-%dT%H:%MZ)"
git push -q origin HEAD:status || { git pull -q --rebase -X theirs origin status && git push -q origin HEAD:status; }
