import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.rules import (AlertPolicy, Reading, format_temp, level_from_android_thermal_status,
                        level_from_ios_thermal_state, level_from_temp, suggestions_for, worst_level)
from core.sensors import SimulatedSensor
from core.storage import Store


def reading(temp=41.0, level=None, charging=False, ts=1000.0):
    return Reading(ts, temp, level or (level_from_temp(temp) if temp is not None else "normal"),
                   68, charging, "test")


def test_levels_from_temperature():
    assert level_from_temp(30) == "normal"
    assert level_from_temp(35) == "warm"
    assert level_from_temp(40) == "hot"
    assert level_from_temp(45.2) == "critical"


def test_level_boundaries():
    assert [level_from_temp(x) for x in (34.9, 35)] == ["normal", "warm"]
    assert [level_from_temp(x) for x in (39.9, 40)] == ["warm", "hot"]
    assert [level_from_temp(x) for x in (44.9, 45)] == ["hot", "critical"]


def test_platform_level_mapping():
    assert [level_from_ios_thermal_state(i) for i in range(4)] == ["normal", "warm", "hot", "critical"]
    assert level_from_android_thermal_status(0) == "normal"
    assert level_from_android_thermal_status(2) == "warm"
    assert level_from_android_thermal_status(3) == "hot"
    assert level_from_android_thermal_status(6) == "critical"
    assert worst_level("warm", None, "hot") == "hot"


def test_format_temp():
    assert format_temp(41) == "41°C"
    assert format_temp(40, "F") == "104°F"
    assert format_temp(None) == "--"


def test_alert_policy_limit_and_cooldown():
    p = AlertPolicy(limit_c=40, cooldown_s=600)
    assert not p.should_alert(reading(39.9))
    r = reading(41, ts=1000)
    assert p.should_alert(r)
    p.mark_sent(r.timestamp)
    assert not p.should_alert(reading(42, ts=1300))      # inside cooldown
    assert p.should_alert(reading(42, ts=1700))          # cooldown over


def test_alert_policy_iphone_uses_level():
    p = AlertPolicy(limit_c=40)
    assert not p.should_alert(reading(None, level="warm"))
    assert p.should_alert(reading(None, level="hot"))


def test_alert_while_charging_switch():
    p = AlertPolicy(limit_c=40, alert_while_charging=False)
    assert not p.should_alert(reading(43, charging=True))
    assert p.should_alert(reading(43, charging=False))


def test_suggestions_put_unplug_first_when_charging_hot():
    keys = [s.key for s in suggestions_for(reading(42, charging=True), heavy_apps=3)]
    assert keys[0] == "unplug"
    assert "heavy_apps" in keys and "brightness" in keys
    keys = [s.key for s in suggestions_for(reading(30, charging=True))]
    assert "unplug" not in keys


def test_store_settings_readings_stats(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    assert s.get_float("limit_c") == 40
    s.set("limit_c", 42)
    s.set("auto_brightness", False)
    assert s.get_float("limit_c") == 42 and not s.get_bool("auto_brightness")

    now = time.time()
    for i, t in enumerate([36.0, 38.5, 44.0, 41.0]):
        s.add_reading(reading(t, ts=now - 3000 + i * 900))
    s.add_alert(reading(44.0, ts=now - 1200))
    st = s.stats(now - 3600)
    assert st["peak"] == 44.0 and st["alerts"] == 1
    assert round(st["avg"], 2) == 39.88
    assert s.temp_change(3600, now) == 5.0
    b = s.buckets(now - 3600, 900, 4)
    assert b[0] == 36.0 and max(x for x in b if x) == 44.0


def test_simulator_stays_realistic():
    sensor = SimulatedSensor(seed=1)
    for _ in range(50):
        r = sensor.read()
        assert 25 < r.temp_c < 55 and 0 <= r.battery_pct <= 100
