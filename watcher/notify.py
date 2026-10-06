"""Push notifications through ntfy (https://ntfy.sh) — free app for iOS/Android, no account."""
from __future__ import annotations

import json
import logging
import os
import urllib.request

log = logging.getLogger(__name__)

PRO_SHOP_TEL = "tel:+14018475141"
TEE_SHEET_URL = "https://wanumetonomy.com/Default.aspx?p=dynamicmodule&pageid=21&tt=booking&ssid=100067&vnf=1"


def send(title: str, message: str, *, click: str | None = None, actions: list[dict] | None = None,
         priority: int = 4, tags: list[str] | None = None) -> bool:
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    payload = {"topic": topic, "title": title, "message": message, "priority": priority,
               "tags": tags or ["golf"]}
    if click:
        payload["click"] = click
    if actions:
        payload["actions"] = actions[:3]  # ntfy allows up to 3 buttons
    if not topic:
        log.warning("NTFY_TOPIC not set — would have sent: %s", json.dumps(payload))
        return False
    req = urllib.request.Request(server, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return 200 <= r.status < 300
    except Exception as e:  # never let a notification failure stop the watcher
        log.error("ntfy send failed: %s", e)
        return False


def view(label: str, url: str) -> dict:
    return {"action": "view", "label": label, "url": url, "clear": True}


def site_url() -> str | None:
    return os.environ.get("SITE_URL") or None
