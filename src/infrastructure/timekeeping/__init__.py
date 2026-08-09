"""Vaxt infrastrukturu — `Clock` və `NtpVerifier` portlarının implementasiyası.

Modul adı qəsdən `time` DEYİL: standart kitabxananın `time` modulu ilə
qarışdırılması oxucunu çaşdırardı.
"""

from src.infrastructure.timekeeping.clock import (
    BAKU_UTC_OFFSET,
    NtpCorrectedClock,
    SystemClock,
    to_baku,
)
from src.infrastructure.timekeeping.ntp import (
    DEFAULT_MAX_DRIFT_SECONDS,
    DEFAULT_SERVERS,
    NtpDriftChecker,
    NtpError,
    NtpSample,
    SntpClient,
)

__all__ = [
    "BAKU_UTC_OFFSET",
    "DEFAULT_MAX_DRIFT_SECONDS",
    "DEFAULT_SERVERS",
    "NtpCorrectedClock",
    "NtpDriftChecker",
    "NtpError",
    "NtpSample",
    "SntpClient",
    "SystemClock",
    "to_baku",
]
