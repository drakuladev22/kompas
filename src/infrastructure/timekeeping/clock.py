"""Vaxt mənbəyi (`Clock` portunun implementasiyası) — Faza 3.4.

NİYƏ AYRICA PORT: bütün domen/tətbiq qatı `datetime.now()`-u BİRBAŞA çağırmır,
`Clock` portundan alır. Bu, iki problemi eyni anda həll edir:

    1. Testlərdə vaxt sabitlənə bilir (`FakeClock`).
    2. Vaxt mənbəyini bir yerdən NTP-düzəlişli mənbəyə keçirmək mümkündür
       (`NtpCorrectedClock`) — yüzlərlə çağırış yerini dəyişmədən.

HƏMİŞƏ tz-aware UTC qaytarılır. Naive `datetime` QADAĞANDIR: DB sütunları
`TIMESTAMPTZ`-dir və naive dəyər sükutla server saat qurşağında şərh olunardı.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from src.infrastructure.timekeeping.ntp import NtpDriftChecker

#: Azərbaycan saat qurşağı (UTC+4, yay saatı tətbiq olunmur — 2016-dan bəri).
#: UI-da göstərmək üçün; SAXLANMA həmişə UTC-dir.
BAKU_UTC_OFFSET: Final[timedelta] = timedelta(hours=4)


class SystemClock:
    """OS saatı. `Clock` portunun standart implementasiyası."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class NtpCorrectedClock:
    """OS saatı + NTP ilə ölçülmüş sürüşmə düzəlişi.

    Kritik fərq: bu, OS saatını DƏYİŞMİR (bunun üçün administrator hüququ
    lazımdır və bütün maşına təsir edir) — sadəcə oxunan hər dəyərə ölçülmüş
    fərqi əlavə edir. Sürüşmə ölçülməyibsə düzəliş 0-dır.
    """

    def __init__(self, checker: NtpDriftChecker) -> None:
        self._checker = checker

    def now(self) -> datetime:
        offset = self._checker.offset_seconds() or 0.0
        return datetime.now(UTC) + timedelta(seconds=offset)


def to_baku(moment: datetime) -> datetime:
    """UTC → Bakı yerli vaxtı (yalnız GÖSTƏRMƏK üçün)."""
    if moment.tzinfo is None:
        raise ValueError("Naive datetime qadağandır — tz-aware dəyər verin")
    return moment.astimezone(UTC) + BAKU_UTC_OFFSET


__all__ = ["BAKU_UTC_OFFSET", "NtpCorrectedClock", "SystemClock", "to_baku"]
