"""Heat levels, alert decisions and suggested actions.

Pure Python: no Android / iOS / Kivy imports, so everything here is unit-tested.
"""
from dataclasses import dataclass, field

# Heat levels shared by both platforms.
NORMAL, WARM, HOT, CRITICAL = "normal", "warm", "hot", "critical"
LEVEL_ORDER = [NORMAL, WARM, HOT, CRITICAL]
LEVEL_LABEL = {NORMAL: "Normal", WARM: "Warm", HOT: "Hot", CRITICAL: "Critical"}

# Battery temperature bands in °C (Android gives an exact number).
WARM_FROM = 35.0
HOT_FROM = 40.0
CRITICAL_FROM = 45.0


def level_from_temp(temp_c: float) -> str:
    """Classify an exact battery temperature (Android)."""
    if temp_c >= CRITICAL_FROM:
        return CRITICAL
    if temp_c >= HOT_FROM:
        return HOT
    if temp_c >= WARM_FROM:
        return WARM
    return NORMAL


def level_from_ios_thermal_state(state: int) -> str:
    """Map NSProcessInfo.thermalState (0 nominal .. 3 critical) to our levels."""
    return LEVEL_ORDER[max(0, min(3, int(state)))]


def level_from_android_thermal_status(status: int) -> str:
    """Map PowerManager.getCurrentThermalStatus() (0 none .. 6 shutdown)."""
    if status <= 0:
        return NORMAL
    if status <= 2:          # LIGHT, MODERATE
        return WARM
    if status == 3:          # SEVERE
        return HOT
    return CRITICAL          # CRITICAL, EMERGENCY, SHUTDOWN


def worst_level(*levels: str) -> str:
    """Return the hottest of several levels (ignores None)."""
    present = [lv for lv in levels if lv]
    return max(present, key=LEVEL_ORDER.index) if present else NORMAL


def c_to_f(temp_c: float) -> float:
    return temp_c * 9.0 / 5.0 + 32.0


def format_temp(temp_c, unit: str = "C", with_unit: bool = True) -> str:
    """'41°C' / '106°F'; '--' when the platform gives no number (iPhone)."""
    if temp_c is None:
        return "--"
    value = c_to_f(temp_c) if unit == "F" else temp_c
    return f"{value:.0f}°{unit}" if with_unit else f"{value:.0f}°"


@dataclass
class Reading:
    """One sample of the phone's state."""
    timestamp: float
    temp_c: float | None          # None on iPhone (Apple gives no number)
    level: str                    # normal / warm / hot / critical
    battery_pct: int | None
    charging: bool
    source: str = "desktop"       # android / ios / desktop


def is_over_limit(reading: Reading, limit_c: float) -> bool:
    """Exact temperature when we have one, otherwise the heat level."""
    if reading.temp_c is not None:
        return reading.temp_c >= limit_c
    return LEVEL_ORDER.index(reading.level) >= LEVEL_ORDER.index(HOT)


@dataclass
class AlertPolicy:
    """Decides when to notify, so the user is not spammed."""
    limit_c: float = 40.0
    cooldown_s: float = 600.0           # at most one alert every 10 minutes
    alert_while_charging: bool = True
    last_alert_ts: float = field(default=-1e18)

    def should_alert(self, reading: Reading) -> bool:
        if not is_over_limit(reading, self.limit_c):
            return False
        if reading.charging and not self.alert_while_charging:
            return False
        return reading.timestamp - self.last_alert_ts >= self.cooldown_s

    def mark_sent(self, ts: float) -> None:
        self.last_alert_ts = ts


@dataclass
class Suggestion:
    key: str          # used by the UI to run the matching action
    title: str
    detail: str
    kind: str         # 'toggle', 'button' or 'tip'


def suggestions_for(reading: Reading, brightness_lowered: bool = False,
                    power_saver_on: bool = False, heavy_apps: int = 0) -> list:
    """Ordered list of practical actions for the current situation."""
    out = []
    hotish = LEVEL_ORDER.index(reading.level) >= LEVEL_ORDER.index(WARM)
    if reading.charging and hotish:
        out.append(Suggestion("unplug", "Unplug the charger",
                              "Charging while hot is the biggest heat source.", "tip"))
    out.append(Suggestion("brightness", "Lower brightness to 40%",
                          "The screen is one of the main heat sources.", "toggle"))
    if not power_saver_on:
        out.append(Suggestion("power_saver", "Power saving mode",
                              "Limits background work and CPU speed.", "button"))
    if heavy_apps:
        out.append(Suggestion("heavy_apps", f"Heavy apps ({heavy_apps})",
                              "See which apps you used most in the last hour.", "button"))
    out.append(Suggestion("pause_games", "Pause games for now",
                          "Games and long video recording heat the phone fast.", "tip"))
    out.append(Suggestion("shade", "Keep the phone out of direct sunlight",
                          "Especially inside a parked car.", "tip"))
    if brightness_lowered:
        for s in out:
            if s.key == "brightness":
                s.title = "Brightness lowered to 40%"
    return out
