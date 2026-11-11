"""Summary of one 'app session': the user starts it, uses an app, then stops it.

Harara can only read its own numbers (temperature and battery) while it is open,
so a session is recorded by the user, not by watching other apps. On iPhone the
temperature is not a number, so the summary uses battery only there.
"""
from dataclasses import dataclass

MIN_MINUTES_FOR_RATE = 5      # shorter sessions are too noisy to give a per-hour rate


@dataclass
class SessionSummary:
    name: str
    minutes: float
    temp_rise: float | None        # °C, end minus start (None when unknown)
    peak_temp: float | None
    battery_drop: int | None       # points lost; None if charged during the session
    drain_per_hour: float | None   # points per hour; None if too short or unknown


def summarize(name: str, start_ts: float, end_ts: float,
              start_temp, end_temp, peak_temp, start_batt, end_batt,
              charged: bool) -> SessionSummary:
    minutes = max(0.0, (end_ts - start_ts) / 60.0)
    rise = None if start_temp is None or end_temp is None else end_temp - start_temp
    drop = None
    if start_batt is not None and end_batt is not None and not charged:
        drop = start_batt - end_batt
    rate = None
    if drop is not None and minutes >= MIN_MINUTES_FOR_RATE:
        rate = drop * 60.0 / minutes
    return SessionSummary(name, minutes, rise, peak_temp, drop, rate)


def parse_harara_url(raw: str):
    """Read harara://start?app=Name or harara://stop. Returns (action, name) or None."""
    from urllib.parse import parse_qs, urlparse
    u = urlparse((raw or "").strip())
    if u.scheme != "harara":
        return None
    action = u.netloc or u.path.strip("/")
    if action not in ("start", "stop"):
        return None
    name = parse_qs(u.query).get("app", [""])[0].strip()[:40]
    if action == "start" and not name:
        return None
    return action, name
