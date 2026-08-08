"""Aqreqat bazisi — domen hadisələrinin toplanması.

NAXIŞ: entity-lər hadisələri Event Bus-a BİRBAŞA yayımlamır. Onlar hadisəni
daxili siyahıda TOPLAYIR; use case tranzaksiya UĞURLA bitdikdən sonra
`collect_events()` ilə götürüb yayımlayır.

NİYƏ: əks halda DB yazısı geri qaytarılsa belə (rollback, saga kompensasiyası)
hadisə artıq yayımlanmış olardı — dinləyicilər baş verməmiş bir şeyə reaksiya
verər, e-poçt göndərilər, cərimə hesablanardı. Bu naxış həmin sinif səhvləri
struktur olaraq bağlayır.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.shared.event_bus import DomainEvent
from src.shared.exceptions import KompasOSError


class DomainRuleError(KompasOSError):
    """Biznes qaydası pozuldu — entity yararsız vəziyyətə keçə bilməz."""

    user_message = "Bu əməliyyat mövcud vəziyyətdə mümkün deyil."


class InvalidStateTransitionError(DomainRuleError):
    """Vəziyyət maşınında icazəsiz keçid cəhdi."""


def utc_now() -> datetime:
    """Domen qatının yeganə vaxt mənbəyi (testdə `Clock` portu ilə əvəzlənir)."""
    return datetime.now(tz=UTC)


class AggregateRoot:
    """Domen hadisələrini toplayan aqreqat kökü.

    QEYD: `ABC` DEYİL — abstrakt metodu yoxdur, yalnız ortaq hadisə-toplama
    davranışı verir. Süni `@abstractmethod` əlavə etmək törəmə siniflərə
    mənasız yük olardı.
    """

    def __init__(self) -> None:
        self._pending_events: list[DomainEvent] = []

    def record_event(self, event: DomainEvent) -> None:
        """Hadisəni növbəyə qoyur — HƏLƏ yayımlamır."""
        self._pending_events.append(event)

    def collect_events(self) -> tuple[DomainEvent, ...]:
        """Toplanmış hadisələri qaytarır və növbəni boşaldır.

        Yalnız tranzaksiya commit olunduqdan SONRA çağırılmalıdır.
        """
        events = tuple(self._pending_events)
        self._pending_events.clear()
        return events

    def discard_events(self) -> None:
        """Hadisələri atır — rollback/kompensasiya halında."""
        self._pending_events.clear()

    @property
    def has_pending_events(self) -> bool:
        return bool(self._pending_events)


__all__ = [
    "AggregateRoot",
    "DomainRuleError",
    "InvalidStateTransitionError",
    "utc_now",
]
