from __future__ import annotations

import threading

from sqlalchemy.orm import Session

from .models import AppSetting


GLOBAL_DOWNLOAD_PAUSE_KEY = "native_downloads_paused"
DOWNLOAD_CONTROL_LOCK = threading.RLock()


def global_downloads_paused(db: Session) -> bool:
    setting = db.get(AppSetting, GLOBAL_DOWNLOAD_PAUSE_KEY)
    return bool(setting and str(setting.value).strip().casefold() == "true")


def set_global_download_pause(db: Session, paused: bool) -> None:
    value = "true" if paused else "false"
    setting = db.get(AppSetting, GLOBAL_DOWNLOAD_PAUSE_KEY)
    if setting is None:
        db.add(
            AppSetting(
                key=GLOBAL_DOWNLOAD_PAUSE_KEY,
                value=value,
                is_secret=False,
            )
        )
    else:
        setting.value = value
        setting.is_secret = False
