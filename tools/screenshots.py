"""Run the app on a desktop and save a PNG of every screen (for reports/posters).

    xvfb-run -s "-screen 0 1280x1024x24" python3 tools/screenshots.py out_dir
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from kivy.clock import Clock  # noqa: E402

import main  # noqa: E402
from core.rules import Reading, level_from_temp  # noqa: E402

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "screenshots")
os.makedirs(OUT, exist_ok=True)
ORDER = ["welcome", "home", "alert", "actions", "log", "apps", "settings"]


class ShotApp(main.HararaApp):
    def on_start(self):
        self.sensor.temp_c = 41.4          # a hot, charging phone for the demo
        self.sensor.charging = True
        self.policy.cooldown_s = 1e9       # only one alert during the run
        self.step = 0
        Clock.schedule_once(self.next_shot, 1.0)

    def next_shot(self, *_):
        if self.step:
            name = ORDER[self.step - 1]
            path = os.path.join(OUT, f"{self.step}_{name}.png")
            self.root.export_to_png(path)
            print("saved", path)
        if self.step == len(ORDER):
            self.stop()
            return
        name = ORDER[self.step]
        if name == "alert":
            r = Reading(main.time.time(), 43.0, level_from_temp(43.0), 71, True, "desktop")
            self.sensor.temp_c = 43.0
            self.send_alert(r)
        if name == "actions":
            self.actions_start = 43.0
            self.toggle_brightness(True)
        self.go(name)
        self.step += 1
        Clock.schedule_once(self.next_shot, 0.8)


if __name__ == "__main__":
    ShotApp().run()
