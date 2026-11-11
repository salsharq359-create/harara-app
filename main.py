"""Harara – honest phone temperature monitor (Python + Kivy).

Runs on Android, iPhone and (with simulated data) on a laptop for development.
"""
import os
import time
from datetime import datetime

from core.platform_info import current_platform

PLATFORM = current_platform()
if PLATFORM == "desktop":
    from kivy.config import Config
    Config.set("graphics", "width", "390")
    Config.set("graphics", "height", "640")   # fits a 768-px laptop screen with the taskbar
    Config.set("graphics", "resizable", "1")

from kivy.app import App
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import (BooleanProperty, ListProperty, NumericProperty,
                             StringProperty)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager
from kivy.uix.switch import Switch
from kivy.uix.widget import Widget

from core import actions, packet, usage
from core.algorithms import RollingWindow
from core.rules import (LEVEL_LABEL, AlertPolicy, format_temp, is_over_limit,
                        suggestions_for)
from core.paths import db_path
from core.sensors import make_sensor
from core.sessions import parse_harara_url, summarize
from core.storage import Store

NAVY = (0.075, 0.157, 0.247, 1)
ORANGE = (0.918, 0.345, 0.047, 1)
ORANGE_DARK = (0.761, 0.255, 0.047, 1)
TEAL = (0.059, 0.463, 0.431, 1)
GREY = (0.29, 0.353, 0.427, 1)
TRACK = (0.965, 0.894, 0.847, 1)
BAR = (0.3, 0.36, 0.43, 1)          # 6.9:1 on white (WCAG 1.4.11), darker than the orange hot bars
LEVEL_COLOR = {"normal": TEAL, "warm": (0.706, 0.325, 0.035, 1),
               "hot": ORANGE, "critical": (0.498, 0.114, 0.114, 1)}
FAST_RISE_C = 5.0          # °C rise within 10 minutes that triggers the early warning
LEVEL_BG = {"normal": (0.851, 0.941, 0.925, 1), "warm": (0.984, 0.922, 0.784, 1),
            "hot": (0.992, 0.878, 0.8, 1), "critical": (0.992, 0.85, 0.85, 1)}


# ---------------------------------------------------------------- widgets
class Card(BoxLayout):
    bg = ListProperty([0.949, 0.957, 0.969, 1])
    radius = NumericProperty(dp(14))


class Pill(Button):
    bg = ListProperty(list(NAVY))
    fg = ListProperty([1, 1, 1, 1])
    outline = BooleanProperty(False)


class Logo(Widget):
    """Thermometer icon drawn with Kivy graphics."""


class TempGauge(Widget):
    frac = NumericProperty(0.6)          # 0..1 of the ring
    ring = ListProperty(list(ORANGE))


class BarChart(Widget):
    values = ListProperty([])            # numbers (°C) or None
    limit = NumericProperty(40)
    lo = NumericProperty(25)
    hi = NumericProperty(50)

    def on_values(self, *_):
        self.redraw()

    def on_size(self, *_):
        self.redraw()

    def on_pos(self, *_):
        self.redraw()

    def redraw(self):
        self.canvas.clear()
        n = len(self.values)
        if not n or self.width < 10:
            return
        gap = dp(5)
        w = (self.width - gap * (n - 1)) / n
        span = self.hi - self.lo
        with self.canvas:
            for i, v in enumerate(self.values):
                if v is None:
                    continue
                h = max(dp(4), self.height * (min(v, self.hi) - self.lo) / span)
                Color(*(ORANGE if v >= self.limit else BAR))
                RoundedRectangle(pos=(self.x + i * (w + gap), self.y), size=(w, h),
                                 radius=[dp(4), dp(4), 0, 0])
            y = self.y + self.height * (self.limit - self.lo) / span
            Color(*ORANGE_DARK)
            Rectangle(pos=(self.x, y - dp(0.75)), size=(self.width, dp(1.5)))


class UsageBar(Widget):
    share = NumericProperty(0.5)
    bar = ListProperty(list(ORANGE))


class NavBar(BoxLayout):
    current = StringProperty("home")


class ActionRow(Card):
    title = StringProperty("")
    detail = StringProperty("")


class AppRow(Card):
    name = StringProperty("")
    minutes = StringProperty("")
    share = NumericProperty(0)
    bar = ListProperty(list(ORANGE))


class SessionRow(Card):
    title = StringProperty("")
    detail = StringProperty("")


# ---------------------------------------------------------------- screens
class WelcomeScreen(Screen):
    pass


class HomeScreen(Screen):
    pass


class AlertScreen(Screen):
    pass


class ActionsScreen(Screen):
    def on_pre_enter(self, *_):
        app = App.get_running_app()
        if app.actions_start is None and app.last and app.last.temp_c is not None:
            app.actions_start = app.last.temp_c
        app.update_after_text()
        self.build_rows()

    def build_rows(self):
        app = App.get_running_app()
        box = self.ids.rows
        box.clear_widgets()
        if not app.last:
            return
        apps = usage.top_apps() or []
        for s in suggestions_for(app.last, app.brightness_lowered, heavy_apps=len(apps)):
            row = ActionRow(title=s.title, detail=s.detail)
            if s.kind == "toggle":
                sw = Switch(active=app.brightness_lowered, size_hint_x=None, width=dp(70))
                sw.bind(active=lambda _w, on: app.toggle_brightness(on))
                row.add_widget(sw)
            elif s.kind == "button":
                btn = Pill(text="Open" if s.key == "power_saver" else "View",
                           size_hint=(None, None), width=dp(72), height=dp(44))
                btn.font_size = "13sp"
                btn.bind(on_release=lambda _b, k=s.key: app.run_action(k))
                row.add_widget(btn)
            else:
                row.add_widget(Label(text="Tip", color=GREY, size_hint_x=None, width=dp(44),
                                     font_size="13sp"))
            box.add_widget(row)


def clock_label(ts: float, minutes: bool = False) -> str:
    """'7pm' / '7:03pm'. Portable: Windows strftime has no '%-I' (no-padding) flag."""
    d = datetime.fromtimestamp(ts)
    hour = d.hour % 12 or 12
    ampm = "am" if d.hour < 12 else "pm"
    return f"{hour}:{d.minute:02d}{ampm}" if minutes else f"{hour}{ampm}"


class LogScreen(Screen):
    week = BooleanProperty(False)

    def on_pre_enter(self, *_):
        self.refresh()

    def on_week(self, *_):
        self.refresh()

    def refresh(self):
        app = App.get_running_app()
        if PLATFORM == "ios":
            self.refresh_levels(app)
            return
        now = time.time()
        if self.week:
            since, step, n = now - 7 * 86400, 86400, 7
            labels = [datetime.fromtimestamp(since + i * step + step).strftime("%a") for i in (0, 3, 6)]
        else:
            since, step, n = now - 86400, 7200, 12
            labels = [clock_label(since + i * step) for i in (0, 4, 8, 11)]
        chart = self.ids.chart
        chart.limit = app.policy.limit_c
        chart.values = app.store.buckets(since, step, n)
        self.ids.axis.text = "      ".join(labels)
        st = app.store.stats(since)
        unit = app.unit
        self.ids.peak.value = format_temp(st["peak"], unit, False) if st["peak"] else "--"
        self.ids.avg.value = format_temp(st["avg"], unit, False) if st["avg"] else "--"
        self.ids.alerts.value = str(st["alerts"])
        if st["hottest"]:
            ts, temp, charging = st["hottest"]
            when = clock_label(ts, minutes=True)
            self.ids.hottest.text = f"{when} · {'while charging' if charging else 'on battery'}"
            self.ids.hottest_temp.text = format_temp(temp, unit, False)
        else:
            self.ids.hottest.text = "No data yet"
            self.ids.hottest_temp.text = ""


    def refresh_levels(self, app):
        """iPhone: Apple gives a heat level, not a number, so chart and stats use levels."""
        from core.rules import LEVEL_ORDER
        now = time.time()
        if self.week:
            since, step, n = now - 7 * 86400, 86400, 7
            labels = [datetime.fromtimestamp(since + i * step + step).strftime("%a") for i in (0, 3, 6)]
        else:
            since, step, n = now - 86400, 7200, 12
            labels = [clock_label(since + i * step) for i in (0, 4, 8, 11)]
        chart = self.ids.chart
        chart.lo, chart.hi, chart.limit = 0, 4, 3          # bars: 1 Normal .. 4 Critical; line at Hot
        chart.values = [None if lv is None else LEVEL_ORDER.index(lv) + 1
                        for lv in app.store.level_buckets(since, step, n)]
        self.ids.axis.text = "      ".join(labels)
        st = app.store.level_stats(since)
        self.ids.peak.value = LEVEL_LABEL[st["peak"]] if st["peak"] else "--"
        self.ids.peak.label = "Hottest level"
        self.ids.avg.value = "--" if st["hot_share"] is None else f"{st['hot_share'] * 100:.0f}%"
        self.ids.avg.label = "Time hot"
        self.ids.alerts.value = str(st["alerts"])
        if st["hottest"]:
            ts, level, charging = st["hottest"]
            self.ids.hottest.text = (f"{clock_label(ts, minutes=True)} · "
                                     f"{'while charging' if charging else 'on battery'}")
            self.ids.hottest_temp.text = LEVEL_LABEL[level]
        else:
            self.ids.hottest.text = "No data yet"
            self.ids.hottest_temp.text = ""


class AppsScreen(Screen):
    def on_pre_enter(self, *_):
        self.refresh_sessions()
        box = self.ids.rows
        box.clear_widgets()
        apps = usage.top_apps()
        if apps is None:
            self.ids.note.text = ("iPhone does not let apps see how other apps use power. "
                                  "Open Settings › Battery to see the list.")
            return
        if not apps:
            self.ids.note.text = "Allow “Usage access” for Harara to see which apps you used most."
            return
        self.ids.note.text = "Screen time in the last hour"
        colors = [ORANGE, (0.706, 0.325, 0.035, 1), (0.42, 0.498, 0.584, 1), (0.42, 0.498, 0.584, 1)]
        for i, a in enumerate(apps):
            box.add_widget(AppRow(name=a.name, minutes=f"{a.minutes:.0f} min", share=a.share,
                                  bar=list(colors[min(i, 3)])))


    def refresh_sessions(self, message: str = ""):
        app = App.get_running_app()
        active = app.store.active_session()
        self.ids.session_btn.text = "Stop session" if active else "Start session"
        if message:
            status = message
        elif active:
            status = f"Running: {active[1]} since {clock_label(active[2], minutes=True)}"
        else:
            status = "Not running."
        self.ids.session_status.text = status
        rows = self.ids.session_rows
        rows.clear_widgets()
        for s in app.store.recent_sessions(6):
            m = summarize(s["name"], s["start"], s["end"], s["start_temp"], s["end_temp"],
                          s["peak"], s["start_batt"], s["end_batt"], s["charged"])
            parts = [f"{m.minutes:.0f} min"]
            if m.temp_rise is not None:
                parts.append(f"heat {m.temp_rise:+.1f}°")
            if m.peak_temp is not None:
                parts.append(f"peak {m.peak_temp:.0f}°")
            elif s["start_temp"] is None:
                parts.append("iPhone: heat as level only")
            if m.drain_per_hour is not None:
                parts.append(f"battery -{m.drain_per_hour:.0f}%/h")
            elif m.battery_drop is None:
                parts.append("charged during session")
            rows.add_widget(SessionRow(title=m.name, detail=" · ".join(parts)))


class SettingsScreen(Screen):
    def on_pre_enter(self, *_):
        app = App.get_running_app()
        s = app.store
        self.ids.limit.value = s.get_float("limit_c")
        self.ids.bg.active = s.get_bool("background_monitoring")
        self.ids.auto.active = s.get_bool("auto_brightness")
        self.ids.charging.active = s.get_bool("alert_while_charging")
        self.ids.weekly.active = s.get_bool("weekly_report")


# ---------------------------------------------------------------- app
class HararaApp(App):
    title = "Harara"
    temp_text = StringProperty("--")
    level = StringProperty("normal")
    level_text = StringProperty("Normal")
    battery_text = StringProperty("--")
    charger_text = StringProperty("--")
    change_text = StringProperty("--")
    change_label = StringProperty("Last hour")
    tip_text = StringProperty("")
    gauge_frac = NumericProperty(0)
    limit_text = StringProperty("40°C")
    unit = StringProperty("C")
    alert_title = StringProperty("")
    alert_big = StringProperty("--")
    alert_body = StringProperty("")
    after_text = StringProperty("")
    platform_name = StringProperty(PLATFORM)
    brightness_lowered = BooleanProperty(False)
    backup_status = StringProperty("Readings are compressed, checked with CRC-32 and encrypted with your passphrase.")

    def load_kv(self, filename=None):
        # Load harara.kv next to this file, whatever the App subclass is called.
        Builder.load_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), "harara.kv"))
        return True

    def build(self):
        self.store = Store(db_path(self.user_data_dir))
        self.store.prune(30)                      # privacy: keep 30 days of history
        self.sensor = make_sensor()
        self.policy = AlertPolicy(limit_c=self.store.get_float("limit_c"),
                                  alert_while_charging=self.store.get_bool("alert_while_charging"))
        self.unit = self.store.get("unit")
        self.limit_text = format_temp(self.policy.limit_c, self.unit)
        self.last = None
        self.actions_start = None
        self.window = RollingWindow(span_s=600)     # last 10 minutes, O(1) per reading
        if PLATFORM == "desktop" and os.environ.get("HARARA_DEMO_HISTORY", "1") == "1":
            seed_demo_history(self.store)

        sm = ScreenManager(transition=NoTransition())
        for cls, name in [(WelcomeScreen, "welcome"), (HomeScreen, "home"), (AlertScreen, "alert"),
                          (ActionsScreen, "actions"), (LogScreen, "log"), (AppsScreen, "apps"),
                          (SettingsScreen, "settings")]:
            sm.add_widget(cls(name=name))
        sm.current = "home" if self.store.get_bool("onboarded") else "welcome"
        self.sm = sm
        self.tick()
        Clock.schedule_interval(self.tick, 3 if PLATFORM == "desktop" else 30)
        if PLATFORM == "ios":
            Clock.schedule_interval(self.handle_url_inbox, 2)
        return sm

    def on_start(self):
        if PLATFORM == "android" and self.store.get_bool("background_monitoring"):
            start_android_service()
        self.handle_url_inbox()

    def on_resume(self):
        self.handle_url_inbox()

    def handle_url_inbox(self, *_):
        """iPhone: a harara://start?app=Name link writes a file (see ios.yml); read it here."""
        if PLATFORM != "ios":
            return
        path = os.path.join(self.user_data_dir, "harara_pending_url.txt")
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as fh:
                raw = fh.read()
            os.remove(path)
        except OSError:
            return
        cmd = parse_harara_url(raw)
        if cmd is None:
            return
        action, name = cmd
        screen = self.sm.get_screen("apps")
        active = self.store.active_session()
        if active:
            r = self.sensor.read()
            self.store.add_reading(r)
            self.store.end_session(active[0], r)
        if action == "stop":
            screen.refresh_sessions("Session saved.")
            return
        r = self.sensor.read()
        self.store.add_reading(r)
        self.store.start_session(name, r)
        screen.refresh_sessions(f"Started: {name}. Keep Harara open while you use it.")
        self.go("apps")

    # ---------- monitoring loop
    def tick(self, *_):
        r = self.sensor.read()
        self.last = r
        self.store.add_reading(r)
        self.level = r.level
        self.level_text = LEVEL_LABEL[r.level]
        self.temp_text = format_temp(r.temp_c, self.unit, False) if r.temp_c is not None else self.level_text
        self.gauge_frac = (min(max((r.temp_c - 25) / 25.0, 0.04), 1) if r.temp_c is not None
                           else [0.25, 0.5, 0.75, 1.0][["normal", "warm", "hot", "critical"].index(r.level)])
        self.battery_text = f"{r.battery_pct}%" if r.battery_pct is not None else "--"
        self.charger_text = "Plugged" if r.charging else "Battery"
        if PLATFORM == "ios":
            # No numbers on iPhone: show the hottest level of the last hour instead.
            peak = self.store.level_stats(time.time() - 3600)["peak"]
            self.change_label = "Hottest (1h)"
            self.change_text = LEVEL_LABEL[peak] if peak else "--"
        else:
            change = self.store.temp_change(3600)
            self.change_text = "--" if change is None else f"{change:+.0f}°"
        self.window.push(r.timestamp, r.temp_c)
        rise = self.window.rise()
        tips = suggestions_for(r, self.brightness_lowered)
        if is_over_limit(r, self.policy.limit_c):
            self.tip_text = f"{tips[0].title}. {tips[0].detail}"
        elif rise is not None and rise >= FAST_RISE_C:
            # early warning: heating fast but still under the limit
            self.tip_text = (f"Heating fast: +{rise:.0f}° in 10 min. "
                             f"{tips[0].title} before it reaches {format_temp(self.policy.limit_c, self.unit)}.")
        else:
            self.tip_text = ("All good. Harara checks every 30 seconds while it is open."
                             if PLATFORM == "ios" else
                             "All good. Harara keeps watching in the background.")
        self.update_after_text()
        if self.policy.should_alert(r):
            self.send_alert(r)

    def update_after_text(self):
        r = self.last
        if self.actions_start is not None and r is not None and r.temp_c is not None:
            self.after_text = (f"Started at {format_temp(self.actions_start, self.unit)}, "
                               f"now {format_temp(r.temp_c, self.unit)}")

    def send_alert(self, r):
        self.policy.mark_sent(r.timestamp)
        self.store.add_alert(r)
        self.alert_big = (format_temp(r.temp_c, self.unit, False) if r.temp_c is not None
                          else LEVEL_LABEL[r.level])
        if r.temp_c is not None:
            self.alert_title = f"Your phone is hot: {format_temp(r.temp_c, self.unit)}"
            self.alert_body = (f"Above the safe limit ({format_temp(self.policy.limit_c, self.unit)}). "
                               "Tap See fixes for suggested actions.")
        else:
            self.alert_title = f"Heat level: {LEVEL_LABEL[r.level]}"
            self.alert_body = "Your iPhone is running hot. Tap See fixes for suggested actions."
        actions.notify(self.alert_title, self.alert_body)
        if self.store.get_bool("auto_brightness"):
            self.toggle_brightness(True)
        if self.sm.current in ("home", "log", "apps"):
            self.sm.current = "alert"

    # ---------- user actions
    def go(self, name):
        self.sm.current = name

    def toggle_session(self, name: str):
        """Start a session for the typed app name, or stop the running one."""
        screen = self.sm.get_screen("apps")
        active = self.store.active_session()
        if active:
            r = self.sensor.read()
            self.store.add_reading(r)            # so the session's peak includes this moment
            self.store.end_session(active[0], r)
            screen.refresh_sessions("Session saved.")
            return
        name = (name or "").strip()
        if not name:
            screen.refresh_sessions("Type the app name first, then start.")
            return
        r = self.sensor.read()
        self.store.add_reading(r)
        self.store.start_session(name, r)
        screen.refresh_sessions(f"Started: {name}. Keep Harara open while you use it.")

    def finish_onboarding(self):
        self.store.set("onboarded", True)
        actions.request_notification_permission()
        self.go("home")

    def toggle_brightness(self, on):
        self.brightness_lowered = bool(on)
        actions.set_brightness(0.4 if on else 1.0)

    def run_action(self, key):
        if key == "power_saver":
            actions.open_power_saver_settings()
        elif key == "heavy_apps":
            self.go("apps")

    def manage_apps(self):
        if usage.top_apps() == []:
            actions.open_usage_access_settings()
        else:
            actions.open_app_management()

    def set_limit(self, value):
        value = round(value)
        self.store.set("limit_c", value)
        self.policy.limit_c = value
        self.limit_text = format_temp(value, self.unit)

    def set_setting(self, key, value):
        self.store.set(key, bool(value))
        if key == "alert_while_charging":
            self.policy.alert_while_charging = bool(value)
        if key == "background_monitoring" and PLATFORM == "android":
            start_android_service() if value else stop_android_service()

    def export_backup(self, passphrase):
        """Compressed + CRC-framed + AES-GCM encrypted backup of the last 30 days (core/packet.py)."""
        if len(passphrase) < 8:
            self.backup_status = "Use a passphrase of at least 8 characters."
            return
        rows = self.store.db.execute(
            "SELECT CAST(ts AS INTEGER), temp_c, battery, charging FROM readings ORDER BY ts").fetchall()
        seen, readings = set(), []
        for ts, temp, batt, chg in rows:
            if ts not in seen:                       # one reading per second at most
                seen.add(ts)
                readings.append((ts, temp, batt, bool(chg)))
        path = os.path.join(self.user_data_dir, time.strftime("harara-backup-%Y%m%d.harara"))
        try:
            size = packet.export_backup(readings, passphrase, path)
        except ImportError:                          # build made without the 'cryptography' recipe
            self.backup_status = "Encrypted backup is not available in this build."
            return
        self.backup_status = f"Saved {len(readings):,} readings in {size / 1024:.1f} KB: {os.path.basename(path)}"

    def set_unit(self, unit):
        self.unit = unit
        self.store.set("unit", unit)
        self.limit_text = format_temp(self.policy.limit_c, unit)
        self.tick()


# ---------------------------------------------------------------- helpers
def start_android_service():
    try:
        from jnius import autoclass
        service = autoclass("org.harara.harara.ServiceMonitor")
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        service.start(activity, "")
    except Exception as exc:
        print(f"[harara] could not start background service: {exc}")


def stop_android_service():
    try:
        from jnius import autoclass
        service = autoclass("org.harara.harara.ServiceMonitor")
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        service.stop(activity)
    except Exception as exc:
        print(f"[harara] could not stop background service: {exc}")


def seed_demo_history(store):
    """Desktop only: fill the last 7 days with simulated readings so the Log charts have data.

    Runs again whenever the last 24 hours are almost empty (e.g. the laptop app was not opened
    yesterday). Never used on a phone: there the log only holds real readings.
    """
    now = time.time()
    recent = store.db.execute("SELECT COUNT(*) FROM readings WHERE ts>=?", (now - 86400,)).fetchone()[0]
    if recent >= 100:
        return
    import math
    import random
    from core.rules import Reading, level_from_temp
    rng = random.Random(7)
    store.db.execute("DELETE FROM readings WHERE ts>=?", (now - 7 * 86400,))
    store.db.execute("DELETE FROM alerts WHERE ts>=?", (now - 7 * 86400,))
    for i in range(7 * 24 * 6):                 # every 10 minutes for 7 days
        ts = now - 7 * 86400 + i * 600
        d = datetime.fromtimestamp(ts)
        temp = 33 + 3 * math.sin((d.hour - 9) / 24 * 2 * math.pi) + rng.uniform(-1, 1)
        if d.hour in (20, 21) and d.weekday() != 4:   # evening gaming while charging
            temp += 7 + rng.uniform(-1.5, 1)
        charging = d.hour in (20, 21, 22, 7)
        r = Reading(ts, round(temp, 1), level_from_temp(temp), 60, charging, "desktop")
        store.db.execute("INSERT INTO readings VALUES (?,?,?,?,?,?)",
                         (r.timestamp, r.temp_c, r.level, r.battery_pct, int(r.charging), r.source))
        if temp >= 43 and rng.random() < 0.15:
            store.db.execute("INSERT INTO alerts VALUES (?,?,?)", (r.timestamp, r.temp_c, r.level))
    store.db.commit()


def show_startup_error(err: str):
    """If the app crashes on start, show the error on screen instead of closing silently."""
    from kivy.uix.scrollview import ScrollView

    class ErrorApp(App):
        def build(self):
            lbl = Label(text="Harara could not start:\n\n" + err, halign="left", valign="top",
                        font_size="12sp", size_hint_y=None, padding=(dp(12), dp(40)))
            lbl.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
                     texture_size=lambda w, v: setattr(w, "height", v[1]))
            sv = ScrollView()
            sv.add_widget(lbl)
            return sv

    ErrorApp().run()


if __name__ == "__main__":
    try:
        HararaApp().run()
    except Exception:
        import traceback
        error_text = traceback.format_exc()
        print(error_text)
        show_startup_error(error_text)
