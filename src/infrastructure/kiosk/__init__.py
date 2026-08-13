"""Kiosk rejimi infrastrukturu — nəzarətçi proses (bölmə 5)."""

from src.infrastructure.kiosk.watchdog import (
    FALLBACK_MAX_RESTARTS_PER_WINDOW,
    FALLBACK_RESTART_BACKOFF_SECONDS,
    KioskWatchdog,
    RestartRecord,
    WatchdogOutcome,
)

__all__ = [
    "FALLBACK_MAX_RESTARTS_PER_WINDOW",
    "FALLBACK_RESTART_BACKOFF_SECONDS",
    "KioskWatchdog",
    "RestartRecord",
    "WatchdogOutcome",
]
