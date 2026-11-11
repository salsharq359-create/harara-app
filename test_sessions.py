import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.rules import Reading
from core.sessions import summarize
from core.storage import Store


def test_rate_and_rise_for_a_long_session():
    s = summarize("Game", 0, 3600, 30.0, 38.0, 39.0, 80, 60, charged=False)
    assert s.temp_rise == 8.0
    assert s.battery_drop == 20
    assert round(s.drain_per_hour, 1) == 20.0
    assert s.peak_temp == 39.0


def test_short_session_has_no_rate():
    s = summarize("Quick", 0, 120, 30.0, 31.0, 31.0, 80, 79, charged=False)
    assert s.drain_per_hour is None
    assert s.battery_drop == 1


def test_charging_session_has_no_drop():
    s = summarize("Charge", 0, 3600, 30.0, 33.0, 34.0, 50, 90, charged=True)
    assert s.battery_drop is None and s.drain_per_hour is None


def test_iphone_session_without_temperature():
    s = summarize("Video", 0, 1800, None, None, None, 90, 84, charged=False)
    assert s.temp_rise is None
    assert s.drain_per_hour == 12.0


def test_store_start_end_and_recent():
    st = Store(":memory:")
    now = time.time()
    sid = st.start_session("Game", Reading(now - 600, 30.0, "normal", 80, False, "desktop"))
    assert st.active_session()[1] == "Game"
    st.add_reading(Reading(now - 300, 36.0, "warm", 75, False, "desktop"))
    st.end_session(sid, Reading(now, 37.0, "warm", 70, False, "desktop"))
    assert st.active_session() is None
    rows = st.recent_sessions()
    assert rows[0]["name"] == "Game"
    assert rows[0]["peak"] == 36.0
    assert rows[0]["charged"] is False


from core.sessions import parse_harara_url


def test_parse_start_and_stop():
    assert parse_harara_url("harara://start?app=PUBG") == ("start", "PUBG")
    assert parse_harara_url("harara://start?app=%D9%84%D8%B9%D8%A8%D8%A9") == ("start", "لعبة")
    assert parse_harara_url("harara://stop") == ("stop", "")


def test_parse_rejects_bad_input():
    assert parse_harara_url("https://example.com") is None
    assert parse_harara_url("harara://start") is None
    assert parse_harara_url("harara://delete?app=x") is None
    assert parse_harara_url("") is None
