"""Kiosk rejimi infrastrukturu — nəzarətçi proses (bölmə 5) + veb-kamera.

Kamera adapteri (`facecontrol.md` Faza 3) məhz bura qoyulub, `security/`
altına yox: o, ÜZ haqqında heç nə bilmir — sadəcə kiosk avadanlığından kadr
oxuyur. Üz-tanıma mühərriki isə `security/face_matcher.py`-dədir, çünki onun
işi biometrik qərardır.
"""

from src.infrastructure.kiosk.camera import (
    DEFAULT_FRAME_INTERVAL_SECONDS,
    DEFAULT_GESTURE_FRAMES,
    DEFAULT_GESTURE_WINDOW_SECONDS,
    DEFAULT_WARMUP_FRAMES,
    CameraUnavailableError,
    OpenCvCameraCapture,
    UnavailableFaceEngine,
    camera_available,
)
from src.infrastructure.kiosk.watchdog import (
    FALLBACK_MAX_RESTARTS_PER_WINDOW,
    FALLBACK_RESTART_BACKOFF_SECONDS,
    KioskWatchdog,
    RestartRecord,
    WatchdogOutcome,
)

__all__ = [
    "DEFAULT_FRAME_INTERVAL_SECONDS",
    "DEFAULT_GESTURE_FRAMES",
    "DEFAULT_GESTURE_WINDOW_SECONDS",
    "DEFAULT_WARMUP_FRAMES",
    "FALLBACK_MAX_RESTARTS_PER_WINDOW",
    "FALLBACK_RESTART_BACKOFF_SECONDS",
    "CameraUnavailableError",
    "KioskWatchdog",
    "OpenCvCameraCapture",
    "RestartRecord",
    "UnavailableFaceEngine",
    "WatchdogOutcome",
    "camera_available",
]
