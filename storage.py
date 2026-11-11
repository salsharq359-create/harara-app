"""SQLite storage for readings, alerts and settings."""
import sqlite3
import time

from .rules import Reading

DEFAULT_SETTINGS = {
    "onboarded": "0",
    "limit_c": "40",
    "background_monitoring": "1",
    "auto_brightness": "1",
    "alert_while_charging": "1",
    "weekly_report": "0",
    "unit": "C",
}


class Store:
    def __init__(self, path: str = "harara.db"):
        # timeout: wait instead of failing when the app and the background
        # service write at the same moment (SQLite allows one writer at a time).
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=5.0)
        if path != ":memory:":
            # WAL: readers (charts) never block the writer (service) and vice versa.
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS readings (
                ts REAL NOT NULL, temp_c REAL, level TEXT NOT NULL,
                battery INTEGER, charging INTEGER NOT NULL, source TEXT);
            CREATE INDEX IF NOT EXISTS readings_ts ON readings(ts);
            CREATE TABLE IF NOT EXISTS alerts (ts REAL NOT NULL, temp_c REAL, level TEXT);
            CREATE INDEX IF NOT EXISTS alerts_ts ON alerts(ts);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                start_ts REAL NOT NULL, end_ts REAL, start_temp REAL, end_temp REAL,
                start_batt INTEGER, end_batt INTEGER);
            CREATE INDEX IF NOT EXISTS sessions_start ON sessions(start_ts);
        """)
        self.db.commit()

    # ---------- settings ----------
    def get(self, key: str) -> str:
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else DEFAULT_SETTINGS[key]

    def get_bool(self, key: str) -> bool:
        return self.get(key) == "1"

    def get_float(self, key: str) -> float:
        return float(self.get(key))

    def set(self, key: str, value) -> None:
        if isinstance(value, bool):
            value = "1" if value else "0"
        self.db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, str(value)))
        self.db.commit()

    # ---------- readings ----------
    def add_reading(self, r: Reading) -> None:
        self.db.execute("INSERT INTO readings VALUES (?,?,?,?,?,?)",
                        (r.timestamp, r.temp_c, r.level, r.battery_pct, int(r.charging), r.source))
        self.db.commit()

    def add_alert(self, r: Reading) -> None:
        self.db.execute("INSERT INTO alerts VALUES (?,?,?)", (r.timestamp, r.temp_c, r.level))
        self.db.commit()

    def temp_change(self, seconds: float = 3600, now: float | None = None):
        """Latest temperature minus the oldest one in the window (None if unknown)."""
        now = now or time.time()
        rows = self.db.execute(
            "SELECT temp_c FROM readings WHERE ts>=? AND temp_c IS NOT NULL ORDER BY ts",
            (now - seconds,)).fetchall()
        if len(rows) < 2:
            return None
        return rows[-1][0] - rows[0][0]

    def stats(self, since: float) -> dict:
        peak, avg = self.db.execute(
            "SELECT MAX(temp_c), AVG(temp_c) FROM readings WHERE ts>=?", (since,)).fetchone()
        alerts = self.db.execute("SELECT COUNT(*) FROM alerts WHERE ts>=?", (since,)).fetchone()[0]
        hottest = self.db.execute(
            "SELECT ts, temp_c, charging FROM readings WHERE ts>=? AND temp_c IS NOT NULL "
            "ORDER BY temp_c DESC LIMIT 1", (since,)).fetchone()
        return {"peak": peak, "avg": avg, "alerts": alerts, "hottest": hottest}

    def buckets(self, since: float, bucket_s: float, count: int) -> list:
        """Max temperature per time bucket, oldest first (None = no data)."""
        out = [None] * count
        for ts, temp in self.db.execute(
                "SELECT ts, temp_c FROM readings WHERE ts>=? AND temp_c IS NOT NULL", (since,)):
            i = int((ts - since) // bucket_s)
            if 0 <= i < count:
                out[i] = temp if out[i] is None else max(out[i], temp)
        return out

    def level_buckets(self, since: float, bucket_s: float, count: int) -> list:
        """Hottest heat level per bucket (used on iPhone, which has no numbers)."""
        order = ["normal", "warm", "hot", "critical"]
        out = [None] * count
        for ts, level in self.db.execute("SELECT ts, level FROM readings WHERE ts>=?", (since,)):
            i = int((ts - since) // bucket_s)
            if 0 <= i < count:
                if out[i] is None or order.index(level) > order.index(out[i]):
                    out[i] = level
        return out

    def level_stats(self, since: float) -> dict:
        """iPhone log: hottest level, share of time at Hot or above, alerts, hottest moment."""
        order = ["normal", "warm", "hot", "critical"]
        rows = self.db.execute("SELECT ts, level, charging FROM readings WHERE ts>=? ORDER BY ts",
                               (since,)).fetchall()
        alerts = self.db.execute("SELECT COUNT(*) FROM alerts WHERE ts>=?", (since,)).fetchone()[0]
        if not rows:
            return {"peak": None, "hot_share": None, "alerts": alerts, "hottest": None}
        peak = max((r[1] for r in rows), key=order.index)
        hot = sum(1 for r in rows if order.index(r[1]) >= order.index("hot"))
        first = next(r for r in rows if r[1] == peak)
        return {"peak": peak, "hot_share": hot / len(rows), "alerts": alerts,
                "hottest": (first[0], peak, first[2])}

    # ---------- app sessions ----------
    def start_session(self, name: str, r: Reading) -> int:
        cur = self.db.execute(
            "INSERT INTO sessions(name, start_ts, start_temp, start_batt) VALUES (?,?,?,?)",
            (name, r.timestamp, r.temp_c, r.battery_pct))
        self.db.commit()
        return cur.lastrowid

    def active_session(self):
        """(id, name, start_ts) of the session still running, or None."""
        return self.db.execute(
            "SELECT id, name, start_ts FROM sessions WHERE end_ts IS NULL "
            "ORDER BY id DESC LIMIT 1").fetchone()

    def end_session(self, sid: int, r: Reading) -> None:
        self.db.execute("UPDATE sessions SET end_ts=?, end_temp=?, end_batt=? WHERE id=?",
                        (r.timestamp, r.temp_c, r.battery_pct, sid))
        self.db.commit()

    def recent_sessions(self, limit: int = 6) -> list:
        """Finished sessions, newest first, with peak temperature and charging flag."""
        rows = self.db.execute(
            "SELECT id, name, start_ts, end_ts, start_temp, end_temp, start_batt, end_batt "
            "FROM sessions WHERE end_ts IS NOT NULL ORDER BY start_ts DESC LIMIT ?",
            (limit,)).fetchall()
        out = []
        for sid, name, start, end, st, et, sb, eb in rows:
            peak, charged = self.db.execute(
                "SELECT MAX(temp_c), MAX(charging) FROM readings WHERE ts>=? AND ts<=?",
                (start, end)).fetchone()
            out.append({"name": name, "start": start, "end": end, "start_temp": st,
                        "end_temp": et, "start_batt": sb, "end_batt": eb,
                        "peak": peak, "charged": bool(charged)})
        return out

    def prune(self, keep_days: int = 30) -> None:
        cutoff = time.time() - keep_days * 86400
        self.db.execute("DELETE FROM readings WHERE ts<?", (cutoff,))
        self.db.execute("DELETE FROM alerts WHERE ts<?", (cutoff,))
        self.db.execute("DELETE FROM sessions WHERE end_ts IS NOT NULL AND end_ts<?", (cutoff,))
        self.db.commit()
