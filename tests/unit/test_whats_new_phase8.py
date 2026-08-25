"""«Nə Yeni?» versiya-qeydləri — `v2backlog.md` Faza 8.2.

Hər test funksiyanın BİR iddiasını sınayır:

  * nəşr YALNIZ `can_publish_whats_new` ilə, oxu YALNIZ
    `can_view_whats_new` ilə (İKİ flag İKİ rol);
  * etiket/başlıq/mətn yoxlamaları domendədir (DB CHECK güzgüsü);
  * ləğv SOFT-delete-dir və audit-lənir.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from src.application.use_cases.whats_new import (
    MAX_VERSION_LABEL_LENGTH,
    PUBLISH_WHATS_NEW_FLAG,
    VIEW_WHATS_NEW_FLAG,
    WhatsNewEntry,
    WhatsNewPermissionError,
    WhatsNewUseCase,
)
from src.domain.value_objects.identifiers import EmployeeId, TenantId
from tests.fixtures.fakes import FakeClock

TENANT = TenantId(uuid.uuid4())
NOW = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)


@dataclass
class _Repo:
    rows: dict[str, WhatsNewEntry] = field(default_factory=dict)

    def list_entries(self, tenant_id: TenantId, *, include_inactive: bool) -> list[WhatsNewEntry]:
        return [row for row in self.rows.values() if include_inactive or row.is_active]

    def create(
        self,
        tenant_id: TenantId,
        *,
        version_label: str,
        title_az: str,
        body_az: str,
        created_by_id: object,
    ) -> WhatsNewEntry:
        entry = WhatsNewEntry(
            entry_id=str(uuid.uuid4()),
            version_label=version_label,
            title_az=title_az,
            body_az=body_az,
            is_active=True,
            created_at=NOW,
        )
        self.rows[entry.entry_id] = entry
        return entry

    def deactivate(self, tenant_id: TenantId, entry_id: str) -> bool:
        row = self.rows.get(entry_id)
        if row is None or not row.is_active:
            return False
        self.rows[entry_id] = WhatsNewEntry(
            entry_id=row.entry_id,
            version_label=row.version_label,
            title_az=row.title_az,
            body_az=row.body_az,
            is_active=False,
            created_at=row.created_at,
        )
        return True


@dataclass
class _Audit:
    actions: list[str] = field(default_factory=list)

    def record(self, **kwargs: Any) -> None:
        self.actions.append(str(kwargs["action"]))


def _employee(flags: tuple[str, ...]) -> Any:
    from src.domain.entities.employee import Employee, PermissionOverride
    from src.domain.entities.position import Position
    from src.domain.value_objects.authorization import PermissionEffect, RolePriority
    from src.domain.value_objects.credentials import Username

    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=Position(
            position_id=uuid.uuid4(),  # type: ignore[arg-type]
            code="ROOT" if flags else "ADMIN",
            name_az="Ad",
            priority=RolePriority.EXECUTIVE if flags else RolePriority.ADMIN,
            tenant_id=TENANT,
            is_system=True,
        ),
        first_name="Ad",
        last_name="Soyad",
        username=Username(f"u.{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )
    for flag in flags:
        employee.apply_override(
            PermissionOverride(
                flag_code=flag, effect=PermissionEffect.GRANT, granted_by=employee.id
            )
        )
    return employee


def _use_case() -> tuple[WhatsNewUseCase, _Repo, _Audit]:
    repo, audit = _Repo(), _Audit()
    use_case = WhatsNewUseCase(
        repository=repo,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    return use_case, repo, audit


def test_publish_requires_the_flag_and_is_audited() -> None:
    use_case, _, audit = _use_case()

    with pytest.raises(WhatsNewPermissionError):
        use_case.publish(
            tenant_id=TENANT,
            actor=_employee((VIEW_WHATS_NEW_FLAG,)),  # yalnız OXU — nəşr YOX
            version_label="0.3.0",
            title_az="Yeni buraxılış",
            body_az="Bu buraxılışda bir çox düzəliş var.",
        )
    assert not audit.actions

    created = use_case.publish(
        tenant_id=TENANT,
        actor=_employee((PUBLISH_WHATS_NEW_FLAG,)),
        version_label="0.3.0",
        title_az="Yeni buraxılış",
        body_az="Bu buraxılışda bir çox düzəliş var.",
    )
    assert created.is_active
    assert "WHATS_NEW_PUBLISHED" in audit.actions


def test_entry_fields_are_validated_in_the_use_case() -> None:
    """Etiket uzunluğu DB CHECK-in güzgüsüdür — ekranı yan keçən skript də düşsün."""
    use_case, repo, _ = _use_case()
    actor = _employee((PUBLISH_WHATS_NEW_FLAG,))
    good_title, good_body = "Başlıq", "Kifayət qədər uzun mətn."

    with pytest.raises(Exception, match="çox uzundur"):
        use_case.publish(
            tenant_id=TENANT,
            actor=actor,
            version_label="x" * (MAX_VERSION_LABEL_LENGTH + 1),
            title_az=good_title,
            body_az=good_body,
        )
    with pytest.raises(Exception, match="Başlıq"):
        use_case.publish(
            tenant_id=TENANT, actor=actor, version_label="0.3.0", title_az="ab", body_az=good_body
        )
    assert not repo.rows

    use_case.publish(
        tenant_id=TENANT,
        actor=actor,
        version_label="0.3.0",
        title_az=good_title,
        body_az=good_body,
    )
    assert len(repo.rows) == 1


def test_list_needs_only_the_view_flag() -> None:
    """OXU üçün nəşr flag-i TƏLƏB OLUNMUR — iki rol ayrıdır."""
    use_case, _, _ = _use_case()
    publisher = _employee((PUBLISH_WHATS_NEW_FLAG,))
    viewer = _employee((VIEW_WHATS_NEW_FLAG,))

    use_case.publish(
        tenant_id=TENANT,
        actor=publisher,
        version_label="0.3.0",
        title_az="Yeni buraxılış",
        body_az="Bu buraxılışda bir çox düzəliş var.",
    )

    entries = use_case.list_entries(tenant_id=TENANT, actor=viewer)
    assert len(entries) == 1
    with pytest.raises(WhatsNewPermissionError):
        use_case.list_entries(tenant_id=TENANT, actor=_employee(()))


def test_deactivation_is_soft_and_audited() -> None:
    use_case, repo, audit = _use_case()
    actor = _employee((PUBLISH_WHATS_NEW_FLAG,))
    created = use_case.publish(
        tenant_id=TENANT,
        actor=actor,
        version_label="0.3.0",
        title_az="Yeni buraxılış",
        body_az="Bu buraxılışda bir çox düzəliş var.",
    )

    use_case.deactivate(tenant_id=TENANT, actor=actor, entry_id=created.entry_id)

    stored = repo.rows[created.entry_id]
    assert stored.is_active is False  # sətir SİLİNMİR — soft delete
    assert "WHATS_NEW_DEACTIVATED" in audit.actions

    with pytest.raises(Exception, match="tapılmadı"):
        use_case.deactivate(tenant_id=TENANT, actor=actor, entry_id=created.entry_id)
