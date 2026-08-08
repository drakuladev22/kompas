"""Domen hadisə müqavilələrinin (contract) testləri.

Bu testlər hadisə sahələrinin adlarını və tiplərini "dondurur" — Faza 2-də
use case-lər bu sahələrə güvənəcək, ona görə təsadüfi ad dəyişikliyi burada
tutulmalıdır.
"""

from __future__ import annotations

import uuid
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.domain import events as domain_events
from src.shared.event_bus import DomainEvent, EventBus

pytestmark = pytest.mark.unit


def _all_event_classes() -> list[type[DomainEvent]]:
    return [
        getattr(domain_events, name)
        for name in domain_events.__all__
        if isinstance(getattr(domain_events, name), type)
    ]


def test_all_exported_events_are_domain_events() -> None:
    classes = _all_event_classes()
    assert len(classes) == len(domain_events.__all__)
    for klass in classes:
        assert issubclass(klass, DomainEvent), f"{klass.__name__} DomainEvent deyil"
        assert is_dataclass(klass), f"{klass.__name__} dataclass deyil"


def test_all_events_are_frozen() -> None:
    """Hadisələr dəyişməz olmalıdır — audit izi sonradan redaktə edilə bilməz."""
    for klass in _all_event_classes():
        instance_params = klass.__dataclass_params__  # type: ignore[attr-defined]
        assert instance_params.frozen, f"{klass.__name__} frozen deyil"


def test_leave_verified_event_contract() -> None:
    """Spesifikasiya bölmə 1-də adı açıq çəkilən hadisə."""
    now = datetime.now(tz=UTC)
    event = domain_events.LeaveVerifiedEvent(
        leave_request_id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        operator_id=uuid.uuid4(),
        requested_time=now,
        verified_actual_time=now,
        delay_minutes=0,
        total_minutes=60,
        was_manual_override=False,
    )

    names = {f.name for f in fields(event)}
    assert {
        "leave_request_id",
        "employee_id",
        "operator_id",
        "requested_time",
        "verified_actual_time",
        "delay_minutes",
        "total_minutes",
        "was_manual_override",
    } <= names
    assert event.event_name == "LeaveVerifiedEvent"


def test_manual_time_override_event_contract() -> None:
    """Spesifikasiya bölmə 1-də adı açıq çəkilən ikinci hadisə."""
    now = datetime.now(tz=UTC)
    event = domain_events.ManualTimeOverrideEvent(
        leave_request_id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        operator_id=uuid.uuid4(),
        system_time=now,
        overridden_time=now,
        delta_minutes=35,
        reason="Kameradan təsdiqləndi, işçi 12:35-də qayıtdı",
        requires_dual_control=True,
    )

    assert event.requires_dual_control is True
    assert event.delta_minutes == 35
    assert len(event.reason) >= 10  # bölmə 4, validasiya 3


def test_event_is_immutable() -> None:
    event = domain_events.TimeDriftDetectedEvent(
        drift_seconds=95.0, ntp_server="pool.ntp.org", machine_name="KIOSK-01"
    )
    with pytest.raises(Exception):  # noqa: B017 - FrozenInstanceError
        event.drift_seconds = 1.0  # type: ignore[misc]


def test_fine_issued_event_uses_decimal() -> None:
    """Pul məbləği float DEYİL, Decimal olmalıdır (yuvarlaqlaşdırma xətası riski)."""
    event = domain_events.FineIssuedEvent(
        fine_id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        store_id=uuid.uuid4(),
        source="MANUAL_CAMERA",
        amount=Decimal("10.50"),
        issued_by=uuid.uuid4(),
        fine_type_id=uuid.uuid4(),
    )
    assert isinstance(event.amount, Decimal)


def test_absence_event_uses_date_not_datetime() -> None:
    event = domain_events.UnauthorizedAbsenceDetectedEvent(
        employee_id=uuid.uuid4(), store_id=uuid.uuid4(), absence_date=date(2026, 8, 8)
    )
    assert isinstance(event.absence_date, date)


def test_events_flow_through_bus(event_bus: EventBus) -> None:
    """Bütün hadisələr audit dinləyicisi tərəfindən tutulmalıdır."""
    caught: list[DomainEvent] = []
    event_bus.subscribe(DomainEvent, caught.append)

    event_bus.publish_sync(
        domain_events.MorningCheckInRequestedEvent(
            attendance_record_id=uuid.uuid4(),
            employee_id=uuid.uuid4(),
            store_id=uuid.uuid4(),
            requested_at=datetime.now(tz=UTC),
            ntp_verified=True,
        )
    )
    event_bus.publish_sync(
        domain_events.SyncConflictDetectedEvent(
            table_name="fines",
            record_id=uuid.uuid4(),
            local_version="{}",
            remote_version="{}",
        )
    )

    assert len(caught) == 2
    assert {e.event_name for e in caught} == {
        "MorningCheckInRequestedEvent",
        "SyncConflictDetectedEvent",
    }
