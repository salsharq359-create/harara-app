"""Things the app can actually do to reduce heat, per platform.

Honest limits:
- An app can dim its OWN window on Android, or the screen on iPhone, while it is open.
- It cannot switch power saving on by itself; it opens the system screen instead.
- It cannot close other apps; it opens the system app settings instead.
"""
from .platform_info import current_platform

PLATFORM = current_platform()


def set_brightness(fraction: float) -> bool:
    """Dim the screen while Harara is open. Returns True if it worked."""
    fraction = max(0.05, min(1.0, fraction))
    try:
        if PLATFORM == "android":
            from android.runnable import run_on_ui_thread
            from jnius import autoclass

            @run_on_ui_thread
            def _apply():
                window = autoclass("org.kivy.android.PythonActivity").mActivity.getWindow()
                params = window.getAttributes()
                params.screenBrightness = fraction
                window.setAttributes(params)

            _apply()
            return True
        if PLATFORM == "ios":
            from pyobjus import autoclass as objc_class
            objc_class("UIScreen").mainScreen().setBrightness_(fraction)
            return True
    except Exception as exc:
        print(f"[harara] brightness change failed: {exc}")
    return False


def _start_android_settings(action_name: str) -> bool:
    from jnius import autoclass
    Intent = autoclass("android.content.Intent")
    Settings = autoclass("android.provider.Settings")
    activity = autoclass("org.kivy.android.PythonActivity").mActivity
    activity.startActivity(Intent(getattr(Settings, action_name)))
    return True


def open_power_saver_settings() -> bool:
    try:
        if PLATFORM == "android":
            return _start_android_settings("ACTION_BATTERY_SAVER_SETTINGS")
        if PLATFORM == "ios":
            return _open_ios_settings()
    except Exception as exc:
        print(f"[harara] could not open power saver settings: {exc}")
    return False


def open_app_management() -> bool:
    try:
        if PLATFORM == "android":
            return _start_android_settings("ACTION_APPLICATION_SETTINGS")
        if PLATFORM == "ios":
            return _open_ios_settings()
    except Exception as exc:
        print(f"[harara] could not open app settings: {exc}")
    return False


def open_usage_access_settings() -> bool:
    """Android only: the user must allow 'Usage access' for the apps list."""
    try:
        if PLATFORM == "android":
            return _start_android_settings("ACTION_USAGE_ACCESS_SETTINGS")
    except Exception as exc:
        print(f"[harara] could not open usage access settings: {exc}")
    return False


def _open_ios_settings() -> bool:
    """Open Harara's page in the iPhone Settings app.

    iOS 18 ignores the old openURL: call, so use openURL:options:completionHandler:
    (empty options, no completion handler) and only fall back to openURL: on old iOS.
    """
    from pyobjus import autoclass, objc_str
    app = autoclass("UIApplication").sharedApplication()
    url = autoclass("NSURL").URLWithString_(objc_str("app-settings:"))
    try:
        options = autoclass("NSDictionary").dictionary()
        app.openURL_options_completionHandler_(url, options, None)
    except Exception as exc:
        print(f"[harara] openURL:options: failed ({exc}); trying openURL:")
        app.openURL_(url)
    return True


def request_notification_permission() -> None:
    """Android 13+ needs POST_NOTIFICATIONS at runtime."""
    if PLATFORM != "android":
        return
    try:
        from android.permissions import Permission, request_permissions
        request_permissions([Permission.POST_NOTIFICATIONS])
    except Exception as exc:
        print(f"[harara] permission request failed: {exc}")


def notify(title: str, message: str) -> bool:
    """System notification (Android/desktop). iPhone uses the in-app Alert screen instead:
    plyer has no iOS notification backend, and iOS stops Harara when it leaves the screen."""
    if PLATFORM == "ios":
        return False
    try:
        from plyer import notification
        notification.notify(title=title, message=message, app_name="Harara", timeout=10)
        return True
    except Exception as exc:
        print(f"[harara] notification failed: {exc}")
        return False
