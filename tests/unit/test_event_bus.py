"""Event Bus testləri."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

import pytest

from src.shared.event_bus import DomainEvent, EventBus, get_event_bus, reset_event_bus

pytestmark = pytest.mark.unit


@dataclass(frozen=True, kw_only=True)
class SampleEvent(DomainEvent):
    payload: str = "test"


@dataclass(frozen=True, kw_only=True)
class ChildSampleEvent(SampleEvent):
    extra: int = 0


def test_domain_event_has_defaults() -> None:
    event = SampleEvent()
    assert isinstance(event.event_id, uuid.UUID)
    assert event.occurred_at.tzinfo is not None
    assert event.event_name == "SampleEvent"
    assert event.to_dict()["event_name"] == "SampleEvent"


def test_sync_handler_receives_event(event_bus: EventBus) -> None:
    received: list[SampleEvent] = []
    event_bus.subscribe(SampleEvent, received.append)

    event_bus.publish_sync(SampleEvent(payload="salam"))

    assert len(received) == 1
    assert received[0].payload == "salam"


@pytest.mark.asyncio
async def test_async_handler_receives_event(event_bus: EventBus) -> None:
    received: list[SampleEvent] = []

    async def handler(event: SampleEvent) -> None:
        received.append(event)

    event_bus.subscribe(SampleEvent, handler)
    await event_bus.publish(SampleEvent(payload="async"))

    assert [event.payload for event in received] == ["async"]


@pytest.mark.asyncio
async def test_mixed_sync_and_async_handlers(event_bus: EventBus) -> None:
    order: list[str] = []

    def sync_handler(_: SampleEvent) -> None:
        order.append("sync")

    async def async_handler(_: SampleEvent) -> None:
        order.append("async")

    event_bus.subscribe(SampleEvent, sync_handler)
    event_bus.subscribe(SampleEvent, async_handler)
    await event_bus.publish(SampleEvent())

    assert sorted(order) == ["async", "sync"]


def test_base_type_subscription_catches_subclass(event_bus: EventBus) -> None:
    """Audit handler-i `DomainEvent`-ə abunə olub HƏR hadisəni tutmalıdır."""
    caught: list[DomainEvent] = []
    event_bus.subscribe(DomainEvent, caught.append)

    event_bus.publish_sync(ChildSampleEvent(extra=5))

    assert len(caught) == 1
    assert isinstance(caught[0], ChildSampleEvent)


def test_priority_controls_execution_order(event_bus: EventBus) -> None:
    order: list[str] = []
    event_bus.subscribe(SampleEvent, lambda _: order.append("normal"), priority=100)
    event_bus.subscribe(SampleEvent, lambda _: order.append("first"), priority=10)
    event_bus.subscribe(SampleEvent, lambda _: order.append("last"), priority=900)

    event_bus.publish_sync(SampleEvent())

    assert order == ["first", "normal", "last"]


def test_handler_failure_is_isolated(event_bus: EventBus) -> None:
    """Bir handler çökür, digəri yenə də icra olunur."""
    survivors: list[str] = []

    def broken(_: SampleEvent) -> None:
        raise RuntimeError("qəsdən xəta")

    event_bus.subscribe(SampleEvent, broken, priority=1)
    event_bus.subscribe(SampleEvent, lambda _: survivors.append("ok"), priority=2)

    event_bus.publish_sync(SampleEvent())

    assert survivors == ["ok"]
    assert event_bus.stats["failed_handlers"] == 1


def test_strict_bus_reraises(strict_event_bus: EventBus) -> None:
    def broken(_: SampleEvent) -> None:
        raise ValueError("qəsdən")

    strict_event_bus.subscribe(SampleEvent, broken)

    with pytest.raises(ValueError, match="qəsdən"):
        strict_event_bus.publish_sync(SampleEvent())


def test_unsubscribe(event_bus: EventBus) -> None:
    received: list[SampleEvent] = []
    subscription = event_bus.subscribe(SampleEvent, received.append)

    assert event_bus.unsubscribe(subscription) is True
    event_bus.publish_sync(SampleEvent())

    assert received == []
    assert event_bus.unsubscribe(subscription) is False


def test_subscribe_rejects_non_event_type(event_bus: EventBus) -> None:
    with pytest.raises(TypeError):
        event_bus.subscribe(str, lambda _: None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_publish_without_handlers_is_noop(event_bus: EventBus) -> None:
    await event_bus.publish(SampleEvent())
    assert event_bus.stats["published"]["SampleEvent"] == 1


@pytest.mark.asyncio
async def test_async_handlers_run_concurrently(event_bus: EventBus) -> None:
    """İki 50ms-lik handler ardıcıl deyil, paralel işləməlidir."""
    started: list[str] = []

    async def slow_a(_: SampleEvent) -> None:
        started.append("a")
        await asyncio.sleep(0.05)

    async def slow_b(_: SampleEvent) -> None:
        started.append("b")
        await asyncio.sleep(0.05)

    event_bus.subscribe(SampleEvent, slow_a)
    event_bus.subscribe(SampleEvent, slow_b)

    loop = asyncio.get_running_loop()
    start = loop.time()
    await event_bus.publish(SampleEvent())
    elapsed = loop.time() - start

    assert sorted(started) == ["a", "b"]
    assert elapsed < 0.09, "handler-lər ardıcıl işləyir, paralel olmalıdır"


def test_get_event_bus_is_singleton() -> None:
    reset_event_bus()
    assert get_event_bus() is get_event_bus()
    reset_event_bus()
