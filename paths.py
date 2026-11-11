"""One database location shared by the app and the Android background service."""
import os

from .platform_info import current_platform


def data_dir(fallback: str) -> str:
    if current_platform() == "android":
        try:
            from android.storage import app_storage_path
            return app_storage_path()
        except Exception:
            pass
    os.makedirs(fallback, exist_ok=True)
    return fallback


def db_path(fallback_dir: str) -> str:
    return os.path.join(data_dir(fallback_dir), "harara.db")
