"""Read the phone's temperature, battery and charging state.

- Android: exact battery temperature from the ACTION_BATTERY_CHANGED intent
  (BatteryManager.EXTRA_TEMPERATURE, tenths of °C) via Pyjnius, plus the
  system thermal status (PowerManager, Android 10+).
- iPhone: Apple gives no number, only NSProcessInfo.thermalState
  (nominal / fair / serious / critical) via Pyobjus, plus UIDevice battery info.
- Desktop: a simulator, so the app can be developed and demoed on a laptop.
"""
import math
import random
import time

from .platform_info import current_platform
from .rules import (Reading, level_from_android_thermal_status,
                    level_from_ios_thermal_state, level_from_temp, worst_level)


class AndroidSensor:
    source = "android"

    def __init__(self):
        from jnius import autoclass
        self._autoclass = autoclass
        self.Intent = autoclass("android.content.Intent")
        self.IntentFilter = autoclass("android.content.IntentFilter")
        self.BatteryManager = autoclass("android.os.BatteryManager")
        self.Context = autoclass("android.content.Context")
        self.VERSION = autoclass("android.os.Build$VERSION")
        self._filter = self.IntentFilter(self.Intent.ACTION_BATTERY_CHANGED)

    def _context(self):
        # Works both inside the app (activity) and in the background service.
        try:
            activity = self._autoclass("org.kivy.android.PythonActivity").mActivity
            if activity is not None:
                return activity
        except Exception:
            pass
        return self._autoclass("org.kivy.android.PythonService").mService

    def read(self) -> Reading:
        ctx = self._context()
        intent = ctx.registerReceiver(None, self._filter)   # sticky broadcast, no receiver needed
        bm = self.BatteryManager
        temp_c = intent.getIntExtra(bm.EXTRA_TEMPERATURE, -1000) / 10.0
        level = intent.getIntExtra(bm.EXTRA_LEVEL, -1)
        scale = intent.getIntExtra(bm.EXTRA_SCALE, 100) or 100
        plugged = intent.getIntExtra(bm.EXTRA_PLUGGED, 0) > 0

        heat = level_from_temp(temp_c) if temp_c > -100 else None
        if self.VERSION.SDK_INT >= 29:                       # Android 10+
            pm = ctx.getSystemService(self.Context.POWER_SERVICE)
            heat = worst_level(heat, level_from_android_thermal_status(pm.getCurrentThermalStatus()))

        return Reading(timestamp=time.time(),
                       temp_c=temp_c if temp_c > -100 else None,
                       level=heat or "normal",
                       battery_pct=int(level * 100 / scale) if level >= 0 else None,
                       charging=plugged, source=self.source)


class IOSSensor:
    source = "ios"

    def __init__(self):
        from pyobjus import autoclass
        self.process_info = autoclass("NSProcessInfo").processInfo()
        self.device = autoclass("UIDevice").currentDevice()
        self.device.setBatteryMonitoringEnabled_(True)

    @staticmethod
    def _get(obj, name, default):
        """pyobjus exposes Objective-C properties as plain values, not methods."""
        try:
            value = getattr(obj, name)
            return value() if callable(value) else value
        except Exception as exc:
            print(f"[harara] could not read {name}: {exc}")
            return default

    def read(self) -> Reading:
        state = int(self._get(self.process_info, "thermalState", 0))
        battery = float(self._get(self.device, "batteryLevel", -1.0))      # -1.0 when unknown
        battery_state = int(self._get(self.device, "batteryState", 0))     # 2 = charging, 3 = full
        return Reading(timestamp=time.time(), temp_c=None,
                       level=level_from_ios_thermal_state(state),
                       battery_pct=int(battery * 100) if battery >= 0 else None,
                       charging=battery_state in (2, 3), source=self.source)


class SimulatedSensor:
    """Smooth, realistic-looking values for demos on a laptop."""
    source = "desktop"

    def __init__(self, start_c: float = 36.0, seed: int | None = None):
        self._rng = random.Random(seed)
        self.temp_c = start_c
        self.battery = 68
        self.charging = True
        self._t0 = time.time()

    def read(self) -> Reading:
        t = time.time() - self._t0
        target = 39.5 + 3.5 * math.sin(t / 40.0) + (1.5 if self.charging else 0.0)
        self.temp_c += (target - self.temp_c) * 0.25 + self._rng.uniform(-0.3, 0.3)
        if self.charging:
            self.battery = min(100, self.battery + 1)
        else:
            self.battery = max(5, self.battery - 1)
        return Reading(timestamp=time.time(), temp_c=round(self.temp_c, 1),
                       level=level_from_temp(self.temp_c), battery_pct=self.battery,
                       charging=self.charging, source=self.source)


def make_sensor():
    """Pick the right sensor for the platform; fall back to the simulator."""
    plat = current_platform()
    try:
        if plat == "android":
            return AndroidSensor()
        if plat == "ios":
            return IOSSensor()
    except Exception as exc:          # keep the app usable if a native call fails
        print(f"[harara] native sensor unavailable ({exc}); using simulator")
    return SimulatedSensor()
