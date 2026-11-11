[app]
title = Harara
package.name = harara
package.domain = org.harara
source.dir = .
source.include_exts = py,kv,png,jpg
source.exclude_dirs = tests, tools, bin, .buildozer, .venv
version = 1.0.3

# Harara logo (replaces the default Kivy icon)
icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png
android.presplash_color = #0B0E1F

# Python + Kivy app; pyjnius gives access to Android's BatteryManager/PowerManager.
# plyer is copied into the project folder (pip install --no-deps --target . plyer), so
# python-for-android does not need its pip step. cryptography needs Rust: left out for now.
requirements = python3,kivy==2.3.1,pyjnius,android

orientation = portrait
fullscreen = 0

# Background monitoring (becomes org.harara.harara.ServiceMonitor)
services = Monitor:service/main.py:foreground

# POST_NOTIFICATIONS: alerts (Android 13+)
# PACKAGE_USAGE_STATS: "Power-hungry apps" screen (user enables it in Settings › Usage access)
android.permissions = POST_NOTIFICATIONS, FOREGROUND_SERVICE, WAKE_LOCK, PACKAGE_USAGE_STATS

# TM255 privacy review: keep harara.db out of automatic Google cloud backups.
# Users move data with the encrypted backup in Settings instead.
android.allow_backup = False

android.api = 33
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
