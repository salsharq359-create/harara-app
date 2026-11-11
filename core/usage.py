"""Which apps were used most in the last hour.

Android does not give third-party apps a per-app battery percentage, so Harara
shows foreground time from UsageStatsManager (needs the 'Usage access' permission).
iPhone gives no information about other apps at all.
"""
import time
from dataclasses import dataclass

from .platform_info import current_platform


@dataclass
class AppUsage:
    name: str
    minutes: float
    share: float      # 0..1 of the total foreground time in the window


def _shares(items: list) -> list:
    total = sum(m for _, m in items) or 1.0
    return [AppUsage(n, m, m / total) for n, m in items]


def top_apps(window_s: float = 3600, limit: int = 5):
    """List of AppUsage, [] if permission is missing, or None if unsupported (iPhone)."""
    plat = current_platform()
    if plat == "ios":
        return None
    if plat == "desktop":
        return _shares([("Game app", 23.0), ("Video player", 12.5),
                        ("Camera", 8.0), ("Maps", 5.0)])
    try:
        from jnius import autoclass
        Context = autoclass("android.content.Context")
        UsageStatsManager = autoclass("android.app.usage.UsageStatsManager")
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        usm = activity.getSystemService(Context.USAGE_STATS_SERVICE)
        pm = activity.getPackageManager()
        now_ms = int(time.time() * 1000)
        stats = usm.queryUsageStats(UsageStatsManager.INTERVAL_DAILY, now_ms - int(window_s * 1000), now_ms)
        if stats is None or stats.isEmpty():
            return []                                   # permission not granted yet
        own = activity.getPackageName()
        items = []
        for i in range(stats.size()):
            s = stats.get(i)
            pkg = s.getPackageName()
            minutes = s.getTotalTimeInForeground() / 60000.0
            if pkg == own or minutes < 0.5:
                continue
            try:
                name = str(pm.getApplicationLabel(pm.getApplicationInfo(pkg, 0)))
            except Exception:
                name = pkg
            items.append((name, minutes))
        items.sort(key=lambda x: x[1], reverse=True)
        return _shares(items[:limit])
    except Exception as exc:
        print(f"[harara] usage stats failed: {exc}")
        return []
