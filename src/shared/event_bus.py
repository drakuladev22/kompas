"""Async/sync Event Bus (spesifikasiya bölmə 1).

QAYDA: Modullar bir-biri ilə BİRBAŞA əlaqə saxlamır. Bütün modullar-arası
kommunikasiya bu bus üzərindən, `DomainEvent` törəmələri vasitəsilə gedir.

Xüsusiyyətlər:
    * Sinxron (`publish_sync`) və asinxron (`publish`) yayım — Qt UI thread-i
      bloklamadan istifadə üçün.
    * İyerarxik abunəlik: bazis tipə abunə olan handler bütün törəmə
      hadisələri də alır (məs. audit handler-i `DomainEvent`-ə abunə olur).
    * Handler izolyasiyası: bir handler-in çökməsi digərlərini dayandırmır,
      xəta `error.log`-a yazılır.
    * Handler-lər qeydiyyat sırası ilə, `priority` dəyərinə görə icra olunur.

İstifadə::

    bus = get_event_bus()
    bus.subscribe(LeaveVerifiedEvent, on_leave_verified)
    await bus.publish(LeaveVerifiedEvent(leave_request_id=..., ...))
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

from src.shared.logger import LogChannel, get_logger

_log = get_logger(__name__)
_error_log = get_logger(__name__, channel=LogChannel.ERROR)


# --------------------------------------------------------------------------- #
# Hadisə bazisi
# --------------------------------------------------------------------------- #


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Bütün domen hadisələrinin dəyişməz (immutable) bazisi.

    Attributes:
        event_id: Hadisənin unikal identifikatoru (idempotentlik/dedup üçün).
        occurred_at: UTC vaxt möhürü.
        correlation_id: Eyni iş axınına (saga, istifadəçi əməliyyatı) aid
            hadisələri bir-birinə bağlayan ID — audit izi üçün kritikdir.
        tenant_id: Çox-tenant mühitdə hadisənin aid olduğu tenant.
        actor_id: Hadisəni yaradan istifadəçi (varsa).
    """

    event_id: uuid.UUID = field(default_factory=uuid.uuid4)
    occurred_at: datetime = field(default_factory=_utc_now)
    correlation_id: uuid.UUID | None = None
    tenant_id: uuid.UUID | None = None
    actor_id: uuid.UUID | None = None

    @property
    def event_name(self) -> str:
        """Log/audit üçün hadisə adı."""
        return type(self).__name__

    def to_dict(self) -> dict[str, Any]:
        """Audit log-a yazmaq üçün serializasiya."""
        raw: dict[str, Any] = asdict(self) if is_dataclass(self) else dict(vars(self))
        raw["event_name"] = self.event_name
        return raw


TEvent = TypeVar("TEvent", bound=DomainEvent)

SyncHandler = Callable[[Any], None]
AsyncHandler = Callable[[Any], Awaitable[None]]
EventHandler = SyncHandler | AsyncHandler


@dataclass(frozen=True)
class Subscription:
    """`unsubscribe()` üçün qaytarılan token."""

    event_type: type[DomainEvent]
    handler: EventHandler
    priority: int
    subscription_id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass(order=True)
class _Registration:
    priority: int
    sequence: int
    handler: EventHandler = field(compare=False)
    subscription_id: uuid.UUID = field(compare=False)
    is_async: bool = field(compare=False, default=False)


# --------------------------------------------------------------------------- #
# Event Bus
# --------------------------------------------------------------------------- #


class EventBus:
    """Thread-safe, prosesdaxili event bus.

    Qeyd: Bu bus PROSES DAXİLİdir. Prosesləri aşan yayım (məs. sandbox-lu
    plugin prosesləri — Faza 2, və ya Supabase Realtime — Faza 3) ayrıca
    adapter ilə bu bus-a körpülənir; nüvə məntiq dəyişmir.
    """

    def __init__(self, *, raise_on_handler_error: bool = False) -> None:
        self._registry: dict[type[DomainEvent], list[_Registration]] = defaultdict(list)
        self._lock = threading.RLock()
        self._sequence = 0
        self._raise_on_handler_error = raise_on_handler_error
        #: Diaqnostika üçün sadə sayğaclar (System Health Monitor — Faza 3).
        self._published_count: dict[str, int] = defaultdict(int)
        self._failed_handler_count: int = 0

    # ----------------------------- abunəlik ------------------------------- #

    def subscribe(
        self,
        event_type: type[TEvent],
        handler: EventHandler,
        *,
        priority: int = 100,
    ) -> Subscription:
        """Handler-i hadisə tipinə abunə edir.

        Args:
            event_type: Hadisə sinfi. Bazis sinfə abunəlik bütün törəmələri tutur.
            handler: Sinxron `def` və ya asinxron `async def` funksiya.
            priority: Kiçik dəyər əvvəl icra olunur (defolt 100).
        """
        if not (inspect.isclass(event_type) and issubclass(event_type, DomainEvent)):
            raise TypeError(f"event_type DomainEvent törəməsi olmalıdır, alındı: {event_type!r}")
        if not callable(handler):
            raise TypeError("handler çağırıla bilən (callable) olmalıdır")

        with self._lock:
            self._sequence += 1
            registration = _Registration(
                priority=priority,
                sequence=self._sequence,
                handler=handler,
                subscription_id=uuid.uuid4(),
                is_async=inspect.iscoroutinefunction(handler),
            )
            self._registry[event_type].append(registration)
            self._registry[event_type].sort()

        _log.debug(
            "EVENT_SUBSCRIBED",
            extra={
                "event_type": event_type.__name__,
                "handler": getattr(handler, "__qualname__", repr(handler)),
                "priority": priority,
            },
        )
        return Subscription(
            event_type=event_type,
            handler=handler,
            priority=priority,
            subscription_id=registration.subscription_id,
        )

    def unsubscribe(self, subscription: Subscription) -> bool:
        """Abunəliyi ləğv edir. Tapılmadıqda `False` qaytarır."""
        with self._lock:
            registrations = self._registry.get(subscription.event_type, [])
            for index, registration in enumerate(registrations):
                if registration.subscription_id == subscription.subscription_id:
                    registrations.pop(index)
                    return True
        return False

    def clear(self) -> None:
        """Bütün abunəlikləri silir (əsasən testlər üçün)."""
        with self._lock:
            self._registry.clear()
            self._published_count.clear()
            self._failed_handler_count = 0

    # ------------------------------ yayım --------------------------------- #

    def _resolve_handlers(self, event: DomainEvent) -> list[_Registration]:
        """MRO boyunca yürüyərək bazis-tip abunəliklərini də toplayır."""
        collected: list[_Registration] = []
        with self._lock:
            for klass in type(event).__mro__:
                if not (inspect.isclass(klass) and issubclass(klass, DomainEvent)):
                    continue
                collected.extend(self._registry.get(klass, ()))
        collected.sort()
        return collected

    async def publish(self, event: DomainEvent) -> None:
        """Hadisəni asinxron yayımlayır.

        Async handler-lər paralel (`asyncio.gather`), sync handler-lər ayrı
        thread-də (`asyncio.to_thread`) icra olunur ki, event loop bloklanmasın.
        Handler xətaları izolyasiya edilir və `error.log`-a yazılır.
        """
        registrations = self._resolve_handlers(event)
        self._published_count[event.event_name] += 1

        _log.debug(
            "EVENT_PUBLISHED",
            extra={
                "event_name": event.event_name,
                "event_id": str(event.event_id),
                "correlation_id": str(event.correlation_id) if event.correlation_id else None,
                "handler_count": len(registrations),
            },
        )

        if not registrations:
            return

        async def _invoke(registration: _Registration) -> None:
            try:
                if registration.is_async:
                    await registration.handler(event)  # type: ignore[misc]
                else:
                    await asyncio.to_thread(registration.handler, event)
            except Exception as exc:
                self._on_handler_error(event, registration, exc)

        await asyncio.gather(*(_invoke(reg) for reg in registrations))

    def publish_sync(self, event: DomainEvent) -> None:
        """Hadisəni sinxron kontekstdə (məs. Qt slot-u) yayımlayır.

        Sync handler-lər dərhal, ardıcıl icra olunur. Async handler-lər:
        * işləyən event loop varsa → `create_task` ilə planlaşdırılır;
        * yoxdursa → müvəqqəti loop-da (`asyncio.run`) icra olunur.
        """
        registrations = self._resolve_handlers(event)
        self._published_count[event.event_name] += 1

        try:
            running_loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        for registration in registrations:
            try:
                if registration.is_async:
                    # `is_async` yoxlanıldığı üçün handler mütləq coroutine
                    # qaytarır — union tipi burada daraldılır.
                    coro = cast("Coroutine[Any, Any, None]", registration.handler(event))
                    if running_loop is not None:
                        running_loop.create_task(coro)
                    else:
                        asyncio.run(coro)
                else:
                    registration.handler(event)
            except Exception as exc:
                self._on_handler_error(event, registration, exc)

    def _on_handler_error(
        self, event: DomainEvent, registration: _Registration, exc: Exception
    ) -> None:
        self._failed_handler_count += 1
        _error_log.exception(
            "EVENT_HANDLER_FAILED",
            extra={
                "event_name": event.event_name,
                "event_id": str(event.event_id),
                "handler": getattr(
                    registration.handler, "__qualname__", repr(registration.handler)
                ),
            },
        )
        if self._raise_on_handler_error:
            raise exc

    # ---------------------------- diaqnostika ----------------------------- #

    @property
    def stats(self) -> dict[str, Any]:
        """System Health Monitor (Faza 3) üçün sadə metrikalar."""
        with self._lock:
            return {
                "subscription_count": sum(len(regs) for regs in self._registry.values()),
                "event_types": len(self._registry),
                "published": dict(self._published_count),
                "failed_handlers": self._failed_handler_count,
            }

    def handler_count(self, event_type: type[DomainEvent]) -> int:
        """Verilmiş tipə (yalnız birbaşa) abunə olan handler sayı."""
        with self._lock:
            return len(self._registry.get(event_type, ()))


# --------------------------------------------------------------------------- #
# Prosesdaxili tək nüsxə (DI Container tərəfindən də qeydiyyata alınır)
# --------------------------------------------------------------------------- #

_bus_singleton: EventBus | None = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Qlobal `EventBus` nüsxəsini qaytarır (lazy, thread-safe)."""
    global _bus_singleton
    if _bus_singleton is None:
        with _bus_lock:
            if _bus_singleton is None:
                _bus_singleton = EventBus()
    return _bus_singleton


def reset_event_bus() -> None:
    """Qlobal bus-u sıfırlayır — YALNIZ testlər üçün."""
    global _bus_singleton
    with _bus_lock:
        _bus_singleton = None
