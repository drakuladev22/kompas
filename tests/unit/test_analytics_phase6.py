"""Analitika genişlənməsi — `v2backlog.md` Faza 6.

Hər bölmə funksiyanın «əsas iddiasını» sınayır:

  6.2 — dublikat qayda EYNİ toleransı işlədir ki, doğrulama ilə eyni
        «eynilik» tərifi olsun; hər cüt GÜNDƏ BİR dəfə yazılır; fərqli
        ölçülü vektorlar MÜQAYISƏSİZ sayılır (yalan pozitiv yox).
  6.4 — kampaniya dövrü YALNIZ Root/CEO-da (`can_manage_campaign_periods`),
        tarix sırası domendə yoxlanılır və ləğv SOFT-delete-dir.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import pytest

from src.application.use_cases.campaign_periods import (
    MANAGE_CAMPAIGNS_FLAG,
    CampaignPeriod,
    CampaignPeriodsUseCase,
    CampaignPermissionError,
)
from src.application.use_cases.face_duplicates import DuplicateFaceExceptionRule
from src.domain.value_objects.exception_signals import (
    DUPLICATE_FACE_SOURCE,
    ExceptionFinding,
    RuleEvaluationContext,
)
from src.domain.value_objects.face_recognition import FaceEmbedding
from src.domain.value_objects.identifiers import EmployeeId, StoreId, TenantId
from tests.fixtures.fakes import FakeClock

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
NOW = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)


@dataclass
class _ProfileStub:
    employee_id: EmployeeId
    tenant_id: TenantId
    store_id: StoreId | None
    embedding: FaceEmbedding | None


def _profile_stub(embedding: tuple[float, ...] | None) -> Any:
    return _ProfileStub(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        store_id=STORE,
        embedding=None if embedding is None else FaceEmbedding(values=embedding),
    )


class _Reader:
    def __init__(self, *profiles: Any) -> None:
        self.profiles = list(profiles)

    def list_all_profiles(self, tenant_id: TenantId) -> list[Any]:
        return [p for p in self.profiles if p.tenant_id == tenant_id]


def _context(limits: dict[str, str] | None = None) -> RuleEvaluationContext:
    return RuleEvaluationContext(
        tenant_id=TENANT,
        as_of=NOW,
        limits=limits or {"FACE_MATCH_TOLERANCE": "0.5"},
    )


# --------------------------------------------------------------------------- #
# 6.2 — Dublikat aşkarlaması
# --------------------------------------------------------------------------- #


def test_duplicate_rule_finds_a_close_pair() -> None:
    close = _profile_stub((0.0, 0.0))
    twin = _profile_stub((0.2, 0.0))
    rule = DuplicateFaceExceptionRule(profiles=_Reader(close, twin))

    findings = rule.evaluate(_context())
    assert len(findings) == 1
    finding: ExceptionFinding = findings[0]
    assert rule.source_code == DUPLICATE_FACE_SOURCE
    # Cütün İKİ tərəfi də kontekstdədir (subyekt + cüt) — sıra ID-ya görədir.
    both_ids = {str(close.employee_id), str(twin.employee_id)}
    assert str(finding.context["pair_employee_id"]) in both_ids
    assert str(finding.employee_id) in both_ids
    assert finding.dedupe_key is not None and NOW.date().isoformat() in finding.dedupe_key


def test_duplicate_rule_uses_the_same_tolerance_as_verification() -> None:
    """Sistem «eyni adam» demək üçün HANSI həddi işlədirsə, dublikat da ONU."""
    left = _profile_stub((0.0, 0.0))
    right = _profile_stub((0.45, 0.0))  # məsafə 0.45 < 0.5, amma > 0.3
    rule = DuplicateFaceExceptionRule(profiles=_Reader(left, right))

    assert len(rule.evaluate(_context({"FACE_MATCH_TOLERANCE": "0.5"}))) == 1
    assert rule.evaluate(_context({"FACE_MATCH_TOLERANCE": "0.3"})) == []


def test_duplicate_rule_skips_dimension_mismatch_and_unenrolled() -> None:
    old_version = _profile_stub((0.1, 0.1, 0.1))  # fərqli ölçü — kitabxana dəyişib
    current = _profile_stub((0.1, 0.1))
    unenrolled = _profile_stub(None)  # qeydiyyatsız işçi cütlüyə girə bilməz
    other_tenant = _profile_stub((0.1, 0.1))
    other_tenant.tenant_id = TenantId(uuid.uuid4())

    rule = DuplicateFaceExceptionRule(
        profiles=_Reader(old_version, current, unenrolled, other_tenant)
    )
    assert rule.evaluate(_context()) == []


# --------------------------------------------------------------------------- #
# 6.4 — Kampaniya dövrləri
# --------------------------------------------------------------------------- #


class _CampaignRepo:
    def __init__(self) -> None:
        self.rows: dict[str, CampaignPeriod] = {}

    def list_periods(self, tenant_id: TenantId, *, include_inactive: bool) -> list[CampaignPeriod]:
        return [row for row in self.rows.values() if include_inactive or row.is_active]

    def create(
        self,
        tenant_id: TenantId,
        *,
        name: str,
        start_date: date,
        end_date: date,
        created_by_id: object,
    ) -> CampaignPeriod:
        period = CampaignPeriod(
            period_id=str(uuid.uuid4()),
            name=name,
            start_date=start_date,
            end_date=end_date,
            is_active=True,
        )
        self.rows[period.period_id] = period
        return period

    def deactivate(self, tenant_id: TenantId, period_id: str) -> bool:
        row = self.rows.get(period_id)
        if row is None or not row.is_active:
            return False
        self.rows[period_id] = CampaignPeriod(
            period_id=row.period_id,
            name=row.name,
            start_date=row.start_date,
            end_date=row.end_date,
            is_active=False,
        )
        return True


class _Audit:
    def __init__(self) -> None:
        self.actions: list[str] = []

    def record(self, **kwargs: Any) -> None:
        self.actions.append(str(kwargs["action"]))


def _employee_with(flags: tuple[str, ...]) -> Any:
    from src.domain.entities.employee import Employee, PermissionOverride
    from src.domain.entities.position import Position
    from src.domain.value_objects.authorization import PermissionEffect, RolePriority
    from src.domain.value_objects.credentials import Username

    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=Position(
            position_id=uuid.uuid4(),  # type: ignore[arg-type]
            code="CEO" if flags else "ADMIN",
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


@pytest.fixture()
def campaign_env() -> tuple[Any, _CampaignRepo, _Audit]:
    repo, audit = _CampaignRepo(), _Audit()
    use_case = CampaignPeriodsUseCase(
        repository=repo,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    return use_case, repo, audit


def test_only_flag_holder_manages_campaigns(
    campaign_env: tuple[Any, _CampaignRepo, _Audit],
) -> None:
    use_case, _, _ = campaign_env
    stranger = _employee_with(())
    holder = _employee_with((MANAGE_CAMPAIGNS_FLAG,))
    with pytest.raises(CampaignPermissionError):
        use_case.create_period(
            tenant_id=TENANT,
            actor=stranger,
            name="Novruz",
            start_date=date(2026, 3, 17),
            end_date=date(2026, 3, 31),
        )
    with pytest.raises(CampaignPermissionError):
        use_case.periods(tenant_id=TENANT, actor=stranger)
    created = use_case.create_period(
        tenant_id=TENANT,
        actor=holder,
        name="Novruz",
        start_date=date(2026, 3, 17),
        end_date=date(2026, 3, 31),
    )
    assert created.is_active


def test_campaign_dates_are_validated_in_the_domain_layer(
    campaign_env: tuple[Any, _CampaignRepo, _Audit],
) -> None:
    use_case, _, _ = campaign_env
    ceo = _employee_with((MANAGE_CAMPAIGNS_FLAG,))
    with pytest.raises(Exception, match="başlanğıcdan"):
        use_case.create_period(
            tenant_id=TENANT,
            actor=ceo,
            name="Tərs aralıq",
            start_date=date(2026, 3, 31),
            end_date=date(2026, 3, 17),
        )


def test_deactivation_is_soft_and_audited(
    campaign_env: tuple[Any, _CampaignRepo, _Audit],
) -> None:
    use_case, repo, audit = campaign_env
    ceo = _employee_with((MANAGE_CAMPAIGNS_FLAG,))
    created = use_case.create_period(
        tenant_id=TENANT,
        actor=ceo,
        name="Novruz kampaniyası",
        start_date=date(2026, 3, 17),
        end_date=date(2026, 3, 31),
    )
    use_case.deactivate_period(tenant_id=TENANT, actor=ceo, period_id=created.period_id)

    stored = repo.rows[created.period_id]
    assert stored.is_active is False  # sətir SİLİNMİR — soft delete
    assert "CAMPAIGN_PERIOD_CREATED" in audit.actions
    assert "CAMPAIGN_PERIOD_DEACTIVATED" in audit.actions
