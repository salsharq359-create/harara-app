"""Detect which platform the app is running on, without importing Kivy."""
import os
import sys


def current_platform() -> str:
    """Return 'android', 'ios' or 'desktop'."""
    if "ANDROID_ARGUMENT" in os.environ or "ANDROID_PRIVATE" in os.environ:
        return "android"
    if sys.platform == "ios" or "KIVY_BUILD" in os.environ and os.environ["KIVY_BUILD"] == "ios":
        return "ios"
    return "desktop"
