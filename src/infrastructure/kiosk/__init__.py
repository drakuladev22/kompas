"""Kiosk rejimi infrastrukturu — nəzarətçi proses (bölmə 5)."""

from src.infrastructure.kiosk.watchdog import (
    DEFAULT_RESTART_BACKOFF_SECONDS,
    MAX_RESTARTS_PER_WINDOW,
    KioskWatchdog,
    RestartRecord,
    WatchdogOutcome,
)

__all__ = [
    "DEFAULT_RESTART_BACKOFF_SECONDS",
    "MAX_RESTARTS_PER_WINDOW",
    "KioskWatchdog",
    "RestartRecord",
    "WatchdogOutcome",
]
