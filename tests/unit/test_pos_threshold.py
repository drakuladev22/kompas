"""#7 POS Səlahiyyət Siyasəti (kompasos11.md Faza 4) — sənədləşdirmə qeydi.

BAZA LAZIM DEYİL: bütün portlar sahtə obyektlərlə əvəz olunur.

──────────────────────────────────────────────────────────────────────────────
NƏ QORUNUR
──────────────────────────────────────────────────────────────────────────────
1. SXEM SƏRHƏDİ — `max_discount_pct` HƏMİŞƏ 0–100 arasındadır (DB `CHECK`-in
   domen güzgüsü), müstəqil olaraq Root ceiling-dən.
2. ROOT TAVANI — `set_threshold()` `system_limits.POS_MAX_DISCOUNT_PCT_CEILING`-i
   yoxlayır; bərpa (`__init__`) YOX, çünki köhnə sətir retroaktiv pozulmamalıdır.
3. SƏLAHİYYƏT — `can_manage_pos_thresholds` olmadan nə oxu, nə yazı.
4. SELF-ESCALATION GUARD — aktor özünə hədd təyin edə bilməz.
5. STRICT HIERARCHY GUARD — aktor yalnız CİDDİ ŞƏKİLDƏ aşağı pilləyə hədd
   təyin edə bilər (bərabər pillə də bloklanır).
6. AUDIT — hər yazı/geri-alma `audit_logs`-a düşür (before/after snapshot).
7. TENANT İZOLYASİYASI — başqa kirayəçinin aktoru/subyekti rədd edilir.
8. 1C/EXCEPTION ENGINE TOXUNUŞU YOXDUR — use case heç bir belə port qəbul
   ETMİR (konstruktor imzası bunun struktur sübutudur).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.use_cases.pos_threshold import (
    MANAGE_POS_THRESHOLDS_FLAG,
    POSThresholdDraft,
    POSThresholdNotFoundError,
    POSThresholdUseCase,
)
from src.domain.entities.base import DomainRuleError, InvalidStateTransitionError
from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.pos_threshold import POSPermissionThreshold
from src.domain.entities.position import Position
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.authorization import (
    AuthorizationError,
    PermissionEffect,
    RolePriority,
)
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import EmployeeId, TenantId, new_pos_threshold_id
from tests.fixtures.fakes import FakeClock, FakeSystemLimits, InMemoryPOSThresholds, RecordingAudit

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
TENANT = TenantId(uuid.uuid4())
OTHER_TENANT = TenantId(uuid.uuid4())


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _employee(
    *,
    priority: RolePriority = RolePriority.OPERATIONAL,
    flags: tuple[str, ...] = (MANAGE_POS_THRESHOLDS_FLAG,),
    tenant_id: TenantId = TENANT,
) -> Employee:
    position = Position(
        position_id=uuid.uuid4(),  # type: ignore[arg-type]
        code=f"ROLE_{priority.name}_{uuid.uuid4().hex[:6]}",
        name_az="Sınaq rolu",
        priority=priority,
        tenant_id=tenant_id,
        is_system=True,
    )
    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=tenant_id,
        position=position,
        first_name="Aynur",
        last_name="Hüseynova",
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


def _threshold(
    *,
    employee_id: EmployeeId,
    tenant_id: TenantId = TENANT,
    max_discount_pct: Decimal = Decimal("10"),
    is_active: bool = True,
    deactivated_at: datetime | None = None,
    deactivated_by: EmployeeId | None = None,
) -> POSPermissionThreshold:
    return POSPermissionThreshold(
        threshold_id=new_pos_threshold_id(),
        tenant_id=tenant_id,
        employee_id=employee_id,
        max_discount_pct=max_discount_pct,
        can_void=False,
        can_refund=False,
        note="Sınaq qeydi",
        updated_by=None,
        created_at=NOW,
        updated_at=NOW,
        is_active=is_active,
        deactivated_at=deactivated_at,
        deactivated_by=deactivated_by,
    )


def _draft(
    *,
    pct: Decimal = Decimal("10"),
    void: bool = False,
    refund: bool = False,
    note: str | None = None,
) -> POSThresholdDraft:
    return POSThresholdDraft(max_discount_pct=pct, can_void=void, can_refund=refund, note=note)


def _use_case(
    *, limits: dict[str, str] | None = None
) -> tuple[POSThresholdUseCase, InMemoryPOSThresholds, RecordingAudit]:
    repository = InMemoryPOSThresholds()
    audit = RecordingAudit()
    use_case = POSThresholdUseCase(
        thresholds=repository,
        limits=FakeSystemLimits(limits),
        audit=audit,
        clock=FakeClock(NOW),
    )
    return use_case, repository, audit


# --------------------------------------------------------------------------- #
# 1. AQREQAT — SXEM SƏRHƏDİ VƏ ROOT TAVANI
# --------------------------------------------------------------------------- #


def test_negative_percentage_is_rejected_at_construction() -> None:
    with pytest.raises(DomainRuleError, match="0"):
        _threshold(employee_id=EmployeeId(uuid.uuid4()), max_discount_pct=Decimal("-1"))


def test_over_hundred_percentage_is_rejected_at_construction() -> None:
    with pytest.raises(DomainRuleError, match="100"):
        _threshold(employee_id=EmployeeId(uuid.uuid4()), max_discount_pct=Decimal("101"))


def test_zero_and_hundred_are_valid_boundaries() -> None:
    low = _threshold(employee_id=EmployeeId(uuid.uuid4()), max_discount_pct=Decimal("0"))
    high = _threshold(employee_id=EmployeeId(uuid.uuid4()), max_discount_pct=Decimal("100"))
    assert low.max_discount_pct == Decimal("0")
    assert high.max_discount_pct == Decimal("100")


def test_inactive_row_without_decider_is_rejected() -> None:
    """`chk_pos_threshold_deactivation` güzgüsü — kim/nə vaxt sualı cavabsız qalmamalıdır."""
    with pytest.raises(DomainRuleError, match="deaktivasiya"):
        _threshold(employee_id=EmployeeId(uuid.uuid4()), is_active=False)


def test_set_threshold_enforces_the_root_ceiling_below_the_schema_bound() -> None:
    """Root ceiling sxem sərhədindən (100) DAHA SƏRT ola bilər."""
    record = _threshold(employee_id=EmployeeId(uuid.uuid4()))

    with pytest.raises(DomainRuleError, match="Root həddini"):
        record.set_threshold(
            max_discount_pct=Decimal("50"),
            can_void=False,
            can_refund=False,
            note=None,
            updated_by=EmployeeId(uuid.uuid4()),
            now=NOW,
            ceiling_pct=Decimal("40"),
        )


def test_set_threshold_reactivates_a_revoked_row() -> None:
    actor_id = EmployeeId(uuid.uuid4())
    record = _threshold(employee_id=EmployeeId(uuid.uuid4()))
    record.revoke(deactivated_by=actor_id, now=NOW)
    assert not record.is_active

    record.set_threshold(
        max_discount_pct=Decimal("25"),
        can_void=True,
        can_refund=True,
        note="Yenidən verildi",
        updated_by=actor_id,
        now=NOW,
    )

    assert record.is_active
    assert record.deactivated_at is None
    assert record.deactivated_by is None
    assert record.max_discount_pct == Decimal("25")


def test_revoke_is_not_reentrant() -> None:
    record = _threshold(employee_id=EmployeeId(uuid.uuid4()))
    record.revoke(deactivated_by=EmployeeId(uuid.uuid4()), now=NOW)

    with pytest.raises(InvalidStateTransitionError, match="geri alınıb"):
        record.revoke(deactivated_by=EmployeeId(uuid.uuid4()), now=NOW)


# --------------------------------------------------------------------------- #
# 2. USE CASE — SƏLAHİYYƏT VƏ İZOLYASİYA
# --------------------------------------------------------------------------- #


def test_unauthorized_actor_is_blocked_not_silently_ignored() -> None:
    use_case, _, audit = _use_case()
    actor = _employee(flags=())
    subject = _employee(priority=RolePriority.STAFF)

    with pytest.raises(AuthorizationError, match=MANAGE_POS_THRESHOLDS_FLAG):
        use_case.set_threshold(
            tenant_id=TENANT,
            actor=actor,
            subject=subject,
            draft=_draft(),
        )
    assert audit.entries == []


def test_reading_also_requires_the_flag() -> None:
    use_case, _, _ = _use_case()
    actor = _employee(flags=())

    with pytest.raises(AuthorizationError, match=MANAGE_POS_THRESHOLDS_FLAG):
        use_case.get_threshold(tenant_id=TENANT, actor=actor, employee_id=EmployeeId(uuid.uuid4()))


def test_actor_from_another_tenant_is_rejected() -> None:
    use_case, _, _ = _use_case()
    actor = _employee(tenant_id=OTHER_TENANT)
    subject = _employee(priority=RolePriority.STAFF)

    with pytest.raises(AuthorizationError, match="kirayəçiyə aid deyil"):
        use_case.set_threshold(
            tenant_id=TENANT,
            actor=actor,
            subject=subject,
            draft=_draft(),
        )


def test_subject_from_another_tenant_is_rejected() -> None:
    use_case, _, _ = _use_case()
    actor = _employee(priority=RolePriority.EXECUTIVE)
    subject = _employee(priority=RolePriority.STAFF, tenant_id=OTHER_TENANT)

    with pytest.raises(AuthorizationError, match="Hədəf işçi"):
        use_case.set_threshold(
            tenant_id=TENANT,
            actor=actor,
            subject=subject,
            draft=_draft(),
        )


# --------------------------------------------------------------------------- #
# 3. SELF-ESCALATION VƏ STRICT HIERARCHY
# --------------------------------------------------------------------------- #


def test_self_assignment_is_blocked() -> None:
    use_case, _, audit = _use_case()
    actor = _employee(priority=RolePriority.EXECUTIVE)

    with pytest.raises(AuthorizationError, match="SELF-ESCALATION"):
        use_case.set_threshold(
            tenant_id=TENANT,
            actor=actor,
            subject=actor,
            draft=_draft(),
        )
    assert audit.entries == []


def test_equal_rank_is_blocked_by_strict_hierarchy() -> None:
    """Bərabər pillə də bloklanır — yalnız CİDDİ ŞƏKİLDƏ aşağı icazəlidir."""
    use_case, _, audit = _use_case()
    actor = _employee(priority=RolePriority.ADMIN)
    subject = _employee(priority=RolePriority.ADMIN)

    with pytest.raises(AuthorizationError, match="HIERARCHY"):
        use_case.set_threshold(
            tenant_id=TENANT,
            actor=actor,
            subject=subject,
            draft=_draft(),
        )
    assert audit.entries == []


def test_lower_actor_cannot_set_threshold_for_higher_subject() -> None:
    use_case, _, audit = _use_case()
    actor = _employee(priority=RolePriority.STAFF)
    subject = _employee(priority=RolePriority.EXECUTIVE)

    with pytest.raises(AuthorizationError, match="HIERARCHY"):
        use_case.set_threshold(
            tenant_id=TENANT,
            actor=actor,
            subject=subject,
            draft=_draft(),
        )
    assert audit.entries == []


def test_higher_actor_can_set_threshold_for_lower_subject() -> None:
    use_case, repository, _ = _use_case()
    actor = _employee(priority=RolePriority.EXECUTIVE)
    subject = _employee(priority=RolePriority.STAFF)

    use_case.set_threshold(
        tenant_id=TENANT,
        actor=actor,
        subject=subject,
        draft=_draft(pct=Decimal("15"), void=True),
    )

    assert repository.items[subject.id].max_discount_pct == Decimal("15")


# --------------------------------------------------------------------------- #
# 4. YAZI, OXU VƏ AUDIT
# --------------------------------------------------------------------------- #


def test_value_is_saved_and_read_back() -> None:
    use_case, _, _ = _use_case()
    actor = _employee(priority=RolePriority.EXECUTIVE)
    subject = _employee(priority=RolePriority.STAFF)

    use_case.set_threshold(
        tenant_id=TENANT,
        actor=actor,
        subject=subject,
        draft=_draft(pct=Decimal("22.50"), void=True, refund=True, note="Test səbəbi"),
    )
    fetched = use_case.get_threshold(tenant_id=TENANT, actor=actor, employee_id=subject.id)

    assert fetched is not None
    assert fetched.max_discount_pct == Decimal("22.50")
    assert fetched.can_void is True
    assert fetched.can_refund is True
    assert fetched.note == "Test səbəbi"


def test_set_threshold_writes_an_audit_entry_with_before_and_after() -> None:
    use_case, _, audit = _use_case()
    actor = _employee(priority=RolePriority.EXECUTIVE)
    subject = _employee(priority=RolePriority.STAFF)

    use_case.set_threshold(
        tenant_id=TENANT,
        actor=actor,
        subject=subject,
        draft=_draft(),
    )

    assert audit.actions() == ["POS_THRESHOLD_SET"]
    entry = audit.entries[0]
    assert entry["actor_id"] == actor.id
    assert entry["entity_type"] == "pos_permission_thresholds"
    assert entry["before_state"] is None
    assert entry["after_state"]["max_discount_pct"] == "10"


def test_second_set_threshold_records_the_previous_value_as_before_state() -> None:
    use_case, _, audit = _use_case()
    actor = _employee(priority=RolePriority.EXECUTIVE)
    subject = _employee(priority=RolePriority.STAFF)
    common = {"tenant_id": TENANT, "actor": actor, "subject": subject}

    use_case.set_threshold(**common, draft=_draft())
    use_case.set_threshold(**common, draft=_draft(pct=Decimal("30"), void=True))

    assert audit.actions() == ["POS_THRESHOLD_SET", "POS_THRESHOLD_SET"]
    second_entry = audit.entries[1]
    assert second_entry["before_state"]["max_discount_pct"] == "10"
    assert second_entry["after_state"]["max_discount_pct"] == "30"


def test_revoke_deactivates_and_is_audited() -> None:
    use_case, repository, audit = _use_case()
    actor = _employee(priority=RolePriority.EXECUTIVE)
    subject = _employee(priority=RolePriority.STAFF)
    use_case.set_threshold(tenant_id=TENANT, actor=actor, subject=subject, draft=_draft())

    use_case.revoke_threshold(tenant_id=TENANT, actor=actor, subject=subject)

    assert repository.items[subject.id].is_active is False
    assert audit.actions() == ["POS_THRESHOLD_SET", "POS_THRESHOLD_REVOKED"]
    assert audit.entries[1]["after_state"]["is_active"] is False


def test_revoke_requires_the_flag_and_hierarchy_too() -> None:
    use_case, _, _ = _use_case()
    actor = _employee(flags=())
    subject = _employee(priority=RolePriority.STAFF)

    with pytest.raises(AuthorizationError):
        use_case.revoke_threshold(tenant_id=TENANT, actor=actor, subject=subject)


def test_revoking_a_nonexistent_threshold_raises_not_found() -> None:
    use_case, _, _ = _use_case()
    actor = _employee(priority=RolePriority.EXECUTIVE)
    subject = _employee(priority=RolePriority.STAFF)

    with pytest.raises(POSThresholdNotFoundError):
        use_case.revoke_threshold(tenant_id=TENANT, actor=actor, subject=subject)


# --------------------------------------------------------------------------- #
# 5. SƏRHƏD DƏYƏRLƏRİ (0, 100, mənfi, 100-dən böyük)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("100")])
def test_boundary_percentages_are_accepted(value: Decimal) -> None:
    use_case, repository, _ = _use_case()
    actor = _employee(priority=RolePriority.EXECUTIVE)
    subject = _employee(priority=RolePriority.STAFF)

    use_case.set_threshold(tenant_id=TENANT, actor=actor, subject=subject, draft=_draft(pct=value))

    assert repository.items[subject.id].max_discount_pct == value


@pytest.mark.parametrize("value", [Decimal("-1"), Decimal("100.01"), Decimal("500")])
def test_out_of_range_percentages_are_rejected(value: Decimal) -> None:
    use_case, repository, audit = _use_case()
    actor = _employee(priority=RolePriority.EXECUTIVE)
    subject = _employee(priority=RolePriority.STAFF)

    with pytest.raises(DomainRuleError):
        use_case.set_threshold(
            tenant_id=TENANT, actor=actor, subject=subject, draft=_draft(pct=value)
        )
    assert repository.items == {}
    assert audit.entries == []


def test_ceiling_from_system_limits_is_enforced_end_to_end() -> None:
    """Root `POS_MAX_DISCOUNT_PCT_CEILING`-i 40-a endirsə, 50 rədd edilir."""
    use_case, repository, audit = _use_case(
        limits={SystemLimitKey.POS_MAX_DISCOUNT_PCT_CEILING.value: "40"}
    )
    actor = _employee(priority=RolePriority.EXECUTIVE)
    subject = _employee(priority=RolePriority.STAFF)

    with pytest.raises(DomainRuleError, match="Root həddini"):
        use_case.set_threshold(
            tenant_id=TENANT, actor=actor, subject=subject, draft=_draft(pct=Decimal("50"))
        )
    assert repository.items == {}
    assert audit.entries == []


def test_default_ceiling_matches_the_schema_bound() -> None:
    """Seed edilmədikdə defolt 100-dür — sxem sərhədi ilə eyni (əlavə məhdudiyyət yoxdur)."""
    assert DEFAULT_LIMITS[SystemLimitKey.POS_MAX_DISCOUNT_PCT_CEILING] == "100"


# --------------------------------------------------------------------------- #
# 6. TENANT İZOLYASİYASI (repository səviyyəsi)
# --------------------------------------------------------------------------- #


def test_repository_does_not_leak_rows_across_tenants() -> None:
    use_case_a, repository, _ = _use_case()
    actor_a = _employee(priority=RolePriority.EXECUTIVE, tenant_id=TENANT)
    subject_a = _employee(priority=RolePriority.STAFF, tenant_id=TENANT)
    use_case_a.set_threshold(tenant_id=TENANT, actor=actor_a, subject=subject_a, draft=_draft())

    use_case_b = POSThresholdUseCase(
        thresholds=repository,
        limits=FakeSystemLimits(),
        audit=RecordingAudit(),
        clock=FakeClock(NOW),
    )
    actor_b = _employee(priority=RolePriority.EXECUTIVE, tenant_id=OTHER_TENANT)

    assert (
        use_case_b.get_threshold(tenant_id=OTHER_TENANT, actor=actor_b, employee_id=subject_a.id)
        is None
    )
