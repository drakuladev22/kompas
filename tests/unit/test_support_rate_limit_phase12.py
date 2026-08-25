"""Dəstək-chat sui-istifadə qorunması — `v2backlog.md` Faza 12.1.

Hər test funksiyanın BİR iddiasını sınayır:

  * qiflənmiş istifadəçinin mesajı RƏDD edilir, sayğaca toxunmur;
  * qifləmə yoxdursa mesaj gedir və UĞURLU mesaj SAYILIR;
  * xəta mətni qifləmənin MÜDDƏTİNİ açıq yazır (PIN-lockout naxışı).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.application.use_cases.support_chat import (
    SupportChatUseCase,
    SupportRateLimitError,
)
from src.domain.value_objects.identifiers import TenantId
from tests.fixtures.fakes import (
    FakeClock,
    FakeFeatureToggles,
    FakeSupportChatThrottle,
)

TENANT = TenantId(uuid.uuid4())
NOW = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)


class _Tickets:
    """Minimal `SupportTicketRepository` sahtəsi — `send` yolunun izi."""

    def __init__(self) -> None:
        self.appended = 0

    def find_open_ticket(self, tenant_id: Any, *, channel: Any, opened_by: Any) -> None:
        return None

    def open_ticket(self, **kwargs: Any) -> None:
        pass

    def raise_urgency(self, ticket_id: Any) -> None:
        pass

    def append_message(self, **kwargs: Any) -> None:
        self.appended += 1

    def get_thread(self, ticket_id: Any) -> Any:
        # `_require_thread` + `_push_to_telegram`-ın oxuduğu minimal səth;
        # status OPEN olduğu üçün keçid yazısı da baş vermir.
        from types import SimpleNamespace

        from src.domain.value_objects.support import SupportChannel, SupportTicketStatus

        return SimpleNamespace(
            ticket_status=SupportTicketStatus.OPEN,
            opened_by=None,
            channel=SupportChannel.TECHNICAL,
            is_open=True,
        )

    def set_status(self, ticket_id: Any, *, status: Any, at: Any) -> None:
        pass


def _employee() -> Any:
    from src.domain.entities.employee import Employee, PermissionOverride
    from src.domain.entities.position import Position
    from src.domain.value_objects.authorization import PermissionEffect, RolePriority
    from src.domain.value_objects.credentials import Username

    employee = Employee(
        employee_id=uuid.uuid4(),  # type: ignore[arg-type]
        tenant_id=TENANT,
        position=Position(
            position_id=uuid.uuid4(),  # type: ignore[arg-type]
            code="ADMIN",
            name_az="Ad",
            priority=RolePriority.ADMIN,
            tenant_id=TENANT,
            is_system=True,
        ),
        first_name="Ad",
        last_name="Soyad",
        username=Username(f"u.{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )
    employee.apply_override(
        PermissionOverride(
            flag_code="can_contact_support",
            effect=PermissionEffect.GRANT,
            granted_by=employee.id,
        )
    )
    return employee


def _chat(throttle: FakeSupportChatThrottle, tickets: _Tickets) -> SupportChatUseCase:
    return SupportChatUseCase(  # type: ignore[arg-type]
        tickets=tickets,
        toggles=FakeFeatureToggles(),
        clock=FakeClock(NOW),
        throttle=throttle,
    )


def test_locked_user_is_rejected_without_counting() -> None:
    throttle = FakeSupportChatThrottle(locked_until=NOW + timedelta(minutes=5))
    tickets = _Tickets()
    chat = _chat(throttle, tickets)

    with pytest.raises(SupportRateLimitError) as exc_info:
        chat.send(tenant_id=TENANT, actor=_employee(), body="Kamera işləmir kömək edin.")

    assert "5 dəqiqə" in str(exc_info.value.user_message)
    assert tickets.appended == 0  # mesaj YAZILMADI
    assert not throttle.registered  # rədd edilən mesaj SAYILMADI


def test_unlocked_user_sends_and_is_registered() -> None:
    throttle = FakeSupportChatThrottle()
    tickets = _Tickets()
    chat = _chat(throttle, tickets)
    actor = _employee()

    thread = chat.send(tenant_id=TENANT, actor=actor, body="Kamera işləmir kömək edin.")

    assert thread is not None
    assert len(throttle.registered) == 1  # uğurlu mesaj SAYILDI


def test_error_message_states_the_remaining_minutes() -> None:
    locked_until = NOW + timedelta(minutes=7)
    error = SupportRateLimitError(locked_until=locked_until, now=NOW)

    assert "7 dəqiqə" in error.user_message
