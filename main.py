"""Android background service: keeps monitoring while the app is closed.

Started from main.py (start_android_service). Buildozer turns the line
`services = Monitor:service/main.py:foreground` into org.harara.harara.ServiceMonitor.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import actions                      # noqa: E402
from core.paths import db_path                # noqa: E402
from core.rules import AlertPolicy, format_temp  # noqa: E402
from core.sensors import make_sensor          # noqa: E402
from core.storage import Store                # noqa: E402

INTERVAL_S = 60


def run():
    store = Store(db_path(os.getcwd()))
    sensor = make_sensor()
    policy = AlertPolicy()
    last_prune = 0.0
    while True:
        # Re-read settings each loop so changes made in the app apply here too.
        if not store.get_bool("background_monitoring"):
            break
        policy.limit_c = store.get_float("limit_c")
        policy.alert_while_charging = store.get_bool("alert_while_charging")
        unit = store.get("unit")

        r = sensor.read()
        store.add_reading(r)
        if policy.should_alert(r):
            policy.mark_sent(r.timestamp)
            store.add_alert(r)
            actions.notify(f"Your phone is hot: {format_temp(r.temp_c, unit)}",
                           f"Above your safe limit ({format_temp(policy.limit_c, unit)}). "
                           "Open Harara for suggested actions.")
        if time.time() - last_prune > 86400:
            store.prune(30)
            last_prune = time.time()
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    run()
