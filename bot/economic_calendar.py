from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone


def fetch_calendar(config, now=None):
    now = now or datetime.now(timezone.utc)
    request = urllib.request.Request(config["url"], headers={"User-Agent": "USDJPY-Signal-Bot/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        rows = json.loads(response.read().decode("utf-8"))
    currencies = set(config["currencies"])
    impact = config["impact"].lower()
    events = []
    for row in rows:
        if row.get("country") not in currencies or str(row.get("impact", "")).lower() != impact:
            continue
        event_time = datetime.fromisoformat(row["date"]).astimezone(timezone.utc)
        minutes = (event_time - now).total_seconds() / 60
        events.append({"title": row.get("title", "Economic event"), "currency": row["country"],
                       "time": event_time, "minutes_until": minutes})
    events.sort(key=lambda x: x["time"])
    danger = [x for x in events if -config["minutes_after"] <= x["minutes_until"] <= config["minutes_before"]]
    upcoming = [x for x in events if 0 < x["minutes_until"] <= 24 * 60]
    return {"danger": danger, "upcoming": upcoming[:3], "error": None}


def safe_fetch_calendar(config, now=None):
    try:
        return fetch_calendar(config, now)
    except Exception as exc:
        return {"danger": [], "upcoming": [], "error": str(exc)}
