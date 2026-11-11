# Harara – honest phone temperature monitor

Harara is a Python (Kivy) app for Android and iPhone. It reads the phone's real
temperature, alerts the user when it passes a safe limit, and suggests practical
actions that reduce heat. It never claims to "cool" the phone.

## What the app does

| Screen | What it shows |
|---|---|
| 1. Welcome | App idea, start monitoring, allow notifications |
| 2. Home | Temperature gauge, battery %, charger status, change in the last hour, a tip |
| 3. Alert | Shown when the temperature passes the user's limit (plus a system notification) |
| 4. Suggested actions | Lower brightness, unplug, open power saving, see heavy apps, tips |
| 5. Temperature log | Bar chart for today / this week, peak, average, number of alerts, hottest moment |
| 6. Power-hungry apps | Apps used most in the last hour (Android) |
| 7. Settings | Alert limit (35–48 °C), background monitoring, auto brightness, alerts while charging, °C/°F |

## Where the data comes from

| | Android (Pyjnius) | iPhone (Pyobjus) |
|---|---|---|
| Temperature | `BatteryManager.EXTRA_TEMPERATURE` – exact °C | Not available – Apple gives no number |
| Heat level | `PowerManager.getCurrentThermalStatus()` (Android 10+) | `NSProcessInfo.thermalState` (Normal / Warm / Hot / Critical) |
| Battery & charging | `ACTION_BATTERY_CHANGED` intent | `UIDevice.batteryLevel / batteryState` |
| Background | Foreground service (`service/main.py`) | Only while the app is open |
| Other apps | `UsageStatsManager` screen time (needs *Usage access*) | Not available |

On a laptop the app uses a **simulator**, so you can develop and demo it without a phone.

## Project structure

```
main.py            App + the 7 screens (logic)
harara.kv          Layout and design of the screens (Kivy language)
core/rules.py      Heat levels, alert rules, suggested actions (pure Python, unit-tested)
core/sensors.py    Android / iPhone / simulated sensors
core/storage.py    SQLite: readings, alerts, settings, statistics
core/actions.py    Brightness, open system settings, notifications
core/usage.py      Most-used apps (Android)
service/main.py    Android background monitoring service
tests/             Unit tests (pytest)
tools/screenshots.py  Saves a PNG of every screen
buildozer.spec     Android build settings
```

## Run on your laptop (Windows, Mac or Linux)

```bash
pip install -r requirements.txt
python main.py          # opens a phone-sized window with simulated data
python -m pytest tests  # 26 tests for the core logic
```

## Build the Android app (.apk)

Buildozer runs on Linux. On a Windows laptop, install **WSL** (Ubuntu) first, then inside it:

```bash
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip python3-venv build-essential \
     autoconf automake libtool pkg-config zlib1g-dev libncurses-dev cmake libffi-dev libssl-dev
python3 -m venv ~/bz && source ~/bz/bin/activate
pip install buildozer cython setuptools
cp -r /mnt/c/harara-app ~/harara-app && cd ~/harara-app && rm -rf .venv harara.db
buildozer android debug          # first build takes a while (downloads the Android SDK/NDK)
cp bin/*.apk /mnt/c/harara-app/  # copy the APK back to Windows
```

The APK appears in `bin/`. Copy it to the phone and install it (allow "install unknown apps").
After installing: allow notifications, and for screen 6 enable *Settings › Usage access › Harara*.

## Build the iPhone app (needs a Mac with Xcode)

```bash
pip install kivy-ios
toolchain build python3 kivy pyobjus plyer
toolchain create Harara /path/to/harara-app
open harara-ios/harara.xcodeproj   # run on the iOS Simulator or an iPhone
```

## Honest limits

- An app cannot cool a phone. Harara reduces heat sources and tells the user what to do.
- Android apps cannot switch power saving on or close other apps by themselves; Harara opens the right system screen.
- Brightness is lowered for the Harara window (Android) or the screen (iPhone) while the app is open.
- iPhone gives only a heat level, and limits background work, so monitoring there runs while the app is open.
