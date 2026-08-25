"""`v2backlog.md` Faza 3 HR-lifecycle: planlaşdırılmış deaktivasiya, anonimləşdirmə,
işçi tövsiyəsi bonusu (`entities/employee.py`, `use_cases/user_management.py`,
`use_cases/sales_points.py`).

──────────────────────────────────────────────────────────────────────────────
BURADA XÜSUSİ QORUNAN ÜÇ ŞEY
──────────────────────────────────────────────────────────────────────────────
1. Anonimləşdirmə `audit_logs`-a TOXUNMUR — hüquqi tələb (modul başlığı,
   `Employee.anonymize_personal_data` şərhi). `RecordingAudit.entries`-in BOŞ
   qaldığını yoxlamaq bu tələbin ÖZÜNÜ kilidləyir.
2. `anonymize_former_employees` idempotentdir (`data_anonymized_at` markeri).
   `at-least-once` planlayıcı eyni işçini iki dəfə gətirə bilər.
3. `Clock` portu — planlaşdırılmış tarixlər (`scheduled_deactivation_date`,
   retensiya kəsimi) HƏMİŞƏ `FakeClock` üzərindən, `datetime.now()` YOX.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest

from src.application.use_cases.sales_points import SalesPointsUseCase
from src.application.use_cases.user_management import UserManagementUseCase
from src.domain.entities.base import DomainRuleError
from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.position import Position
from src.domain.policies import FeatureModule, SystemLimitKey
from src.domain.value_objects.authorization import PermissionEffect, RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import EmployeeId, PositionId, StoreId, TenantId

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())


# --------------------------------------------------------------------------- #
# Saxta portlar
# --------------------------------------------------------------------------- #


class _Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class _Audit:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.entries.append(kwargs)

    def actions(self) -> list[str]:
        return [str(e["action"]) for e in self.entries]


class _Notifier:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def notify(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)


class _EmployeeRepo:
    def __init__(self, employees: list[Employee] | None = None) -> None:
        self.items: dict[EmployeeId, Employee] = {e.id: e for e in (employees or [])}
        self.saved: list[Employee] = []

    def get(self, employee_id: EmployeeId) -> Employee | None:
        return self.items.get(employee_id)

    def save(self, employee: Employee) -> None:
        self.items[employee.id] = employee
        self.saved.append(employee)


class _Credentials:
    """`CredentialWriter` — bu faylın testlərində HEÇ VAXT çağırılmır (aktorsuz iş)."""


class _ScheduledDeactivationReader:
    def __init__(self, due: list[Employee] | None = None) -> None:
        self.due = due or []
        self.queried_as_of: list[date] = []

    def list_due_for_scheduled_deactivation(
        self, tenant_id: TenantId, *, as_of: date
    ) -> list[Employee]:
        self.queried_as_of.append(as_of)
        return self.due


class _RetentionReader:
    def __init__(self, candidates: list[Employee] | None = None) -> None:
        self.candidates = candidates or []
        self.queried_cutoffs: list[datetime] = []

    def list_pending_anonymization(
        self, tenant_id: TenantId, *, deactivated_before: datetime
    ) -> list[Employee]:
        self.queried_cutoffs.append(deactivated_before)
        return self.candidates


def _position(code: str = "SATICI", priority: RolePriority = RolePriority.OPERATIONAL) -> Position:
    return Position(
        position_id=PositionId(uuid.uuid4()),
        code=code,
        name_az=code.title(),
        priority=priority,
        tenant_id=TENANT,
        is_system=True,
    )


def _employee(
    *,
    is_active: bool = True,
    data_anonymized_at: datetime | None = None,
    flags: tuple[str, ...] = (),
    store_id: StoreId | None = STORE,
) -> Employee:
    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=_position(),
        first_name="Ad",
        last_name="Soyad",
        store_id=store_id,
        username=Username(f"u.{uuid.uuid4().hex[:8]}"),
        has_password=True,
        is_active=is_active,
        data_anonymized_at=data_anonymized_at,
    )
    for flag in flags:
        employee.apply_override(
            PermissionOverride(
                flag_code=flag, effect=PermissionEffect.GRANT, granted_by=employee.id
            )
        )
    return employee


class Ctx:
    def __init__(self) -> None:
        self.clock = _Clock()
        self.employees = _EmployeeRepo()
        self.audit = _Audit()
        self.notifier = _Notifier()
        self.scheduled_reader = _ScheduledDeactivationReader()
        self.retention_reader = _RetentionReader()

    def user_management(self, *, wired: bool = True) -> UserManagementUseCase:
        return UserManagementUseCase(
            employees=self.employees,  # type: ignore[arg-type]
            credentials=_Credentials(),  # type: ignore[arg-type]
            audit=self.audit,  # type: ignore[arg-type]
            clock=self.clock,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
            scheduled_deactivation_reader=self.scheduled_reader if wired else None,  # type: ignore[arg-type]
            retention_candidate_reader=self.retention_reader if wired else None,  # type: ignore[arg-type]
        )


@pytest.fixture
def ctx() -> Ctx:
    return Ctx()


# --------------------------------------------------------------------------- #
# Entity: `Employee.anonymize_personal_data`
# --------------------------------------------------------------------------- #


def test_an_active_employee_cannot_be_anonymized() -> None:
    employee = _employee(is_active=True)
    with pytest.raises(DomainRuleError, match="Aktiv işçinin"):
        employee.anonymize_personal_data(now=NOW)


def test_anonymization_clears_pii_but_keeps_username_and_hire_date() -> None:
    employee = _employee(is_active=False)
    employee.hire_date = date(2020, 1, 1)
    original_username = employee.username

    changed = employee.anonymize_personal_data(now=NOW)

    assert changed is True
    assert employee.first_name == "Anonimləşdirilib"
    assert employee.last_name == ""
    assert employee.notification_email is None
    assert employee.profile_photo_url is None
    assert employee.date_of_birth is None
    assert employee.data_anonymized_at == NOW
    # FK-lar VƏ statistik faktlar TOXUNULMUR (modul başlığı).
    assert employee.username == original_username
    assert employee.hire_date == date(2020, 1, 1)
    assert employee.position.code == "SATICI"


def test_anonymization_is_a_idempotent_no_op_the_second_time() -> None:
    employee = _employee(is_active=False)
    employee.anonymize_personal_data(now=NOW)
    first_marker = employee.data_anonymized_at

    changed_again = employee.anonymize_personal_data(now=NOW)

    assert changed_again is False
    assert employee.data_anonymized_at == first_marker  # təkrar YAZILMADI


# --------------------------------------------------------------------------- #
# `deactivate_scheduled_employees` — planlaşdırılmış iş (aktorsuz)
# --------------------------------------------------------------------------- #


def test_deactivate_scheduled_returns_zero_when_the_reader_port_is_not_wired(ctx: Ctx) -> None:
    """Köhnə kompozisiya (`None` port) sükutla ESKİ davranışda qalır."""
    use_case = ctx.user_management(wired=False)
    assert use_case.deactivate_scheduled_employees(TENANT) == 0
    assert ctx.audit.entries == []


def test_deactivates_every_due_active_candidate(ctx: Ctx) -> None:
    worker = _employee(is_active=True)
    worker.scheduled_deactivation_date = date(2026, 8, 19)
    ctx.scheduled_reader.due = [worker]
    use_case = ctx.user_management()

    count = use_case.deactivate_scheduled_employees(TENANT)

    assert count == 1
    assert worker.is_active is False
    assert ctx.audit.actions() == ["EMPLOYEE_SCHEDULED_DEACTIVATION"]
    assert ctx.notifier.sent[0]["category"] == "EMPLOYEE_SCHEDULED_DEACTIVATION"
    # `Clock` portu — bugünün tarixi `_now.date()`-dən gəlir, `datetime.now()` yox.
    assert ctx.scheduled_reader.queried_as_of == [NOW.date()]


def test_an_already_inactive_candidate_is_skipped_idempotently(ctx: Ctx) -> None:
    """`at-least-once`: reader eyni işçini TƏKRAR gətirə bilər — artıq deaktivdirsə keçilir."""
    worker = _employee(is_active=False)  # AT-LEAST-ONCE-un ikinci gəlişini simulyasiya edir
    ctx.scheduled_reader.due = [worker]
    use_case = ctx.user_management()

    count = use_case.deactivate_scheduled_employees(TENANT)

    assert count == 0
    assert ctx.audit.entries == []
    assert ctx.notifier.sent == []


# --------------------------------------------------------------------------- #
# `anonymize_former_employees` — retensiya, `audit_logs`-suz, idempotent
# --------------------------------------------------------------------------- #


def test_anonymize_returns_zero_when_the_reader_port_is_not_wired(ctx: Ctx) -> None:
    use_case = ctx.user_management(wired=False)
    assert use_case.anonymize_former_employees(TENANT) == 0


def test_anonymize_former_employees_never_writes_to_audit_logs(ctx: Ctx) -> None:
    """HÜQUQİ TƏLƏB — bu funksiya `self._audit.record(...)`-u HEÇ ÇAĞIRMIR."""
    former = _employee(is_active=False)
    ctx.retention_reader.candidates = [former]
    use_case = ctx.user_management()

    anonymized = use_case.anonymize_former_employees(TENANT)

    assert anonymized == 1
    assert former.data_anonymized_at == NOW
    assert ctx.audit.entries == []  # <- QƏSDLİ İSTİSNA, bax modul başlığı
    assert former in ctx.employees.saved


def test_anonymize_former_employees_is_idempotent_across_two_runs(ctx: Ctx) -> None:
    former = _employee(is_active=False)
    ctx.retention_reader.candidates = [former]
    use_case = ctx.user_management()

    first_run = use_case.anonymize_former_employees(TENANT)
    marker_after_first = former.data_anonymized_at
    saved_count_after_first = len(ctx.employees.saved)

    # İKİNCİ İCRA: `at-least-once` planlayıcı EYNİ namizədi YENƏ gətirir.
    second_run = use_case.anonymize_former_employees(TENANT)

    assert first_run == 1
    assert second_run == 0  # TƏSİRSİZ — markerin ÖZÜ bunu bloklayır
    assert former.data_anonymized_at == marker_after_first
    assert len(ctx.employees.saved) == saved_count_after_first  # İKİNCİ `save()` YOXDUR
    assert ctx.audit.entries == []


# --------------------------------------------------------------------------- #
# `sales_points.SalesPointsUseCase.award_referral_bonus` (Faza 3.5)
# --------------------------------------------------------------------------- #


class _FakeSystemLimits:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {}

    def get_int(self, tenant_id: TenantId, key: str, default: int) -> int:
        return int(self.values.get(key, default))

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
        return self.values.get(key, default)

    def all_for(self, tenant_id: TenantId) -> dict[str, str]:
        return dict(self.values)

    def describe(self, tenant_id: TenantId) -> list[dict[str, object]]:
        return []

    def set_value(
        self, tenant_id: TenantId, key: str, value: str, *, changed_by: EmployeeId
    ) -> None:
        self.values[key] = value


class _FakeToggles:
    def __init__(self, disabled: set[str] | None = None) -> None:
        self.disabled = disabled or set()

    def is_enabled(self, tenant_id: TenantId, module_key: str) -> bool:
        return module_key not in self.disabled


class _PointsRepo:
    def __init__(self) -> None:
        self.saved: list[Any] = []

    def save(self, entry: Any) -> None:
        self.saved.append(entry)


class _RewardRepo:
    """`RewardRepository` — bu testlərdə çağırılmır, yalnız konstruktor tələb edir."""


def _points_use_case(
    *,
    audit: _Audit,
    clock: _Clock,
    toggles: _FakeToggles | None = None,
    limits: _FakeSystemLimits | None = None,
    points: _PointsRepo | None = None,
) -> tuple[SalesPointsUseCase, _PointsRepo]:
    repo = points or _PointsRepo()
    use_case = SalesPointsUseCase(
        points=repo,  # type: ignore[arg-type]
        rewards=_RewardRepo(),  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=clock,  # type: ignore[arg-type]
        notifier=_Notifier(),  # type: ignore[arg-type]
        toggles=toggles,  # type: ignore[arg-type]
        limits=limits,  # type: ignore[arg-type]
    )
    return use_case, repo


def test_referral_bonus_is_skipped_when_the_module_is_disabled() -> None:
    audit = _Audit()
    use_case, repo = _points_use_case(
        audit=audit,
        clock=_Clock(),
        toggles=_FakeToggles(disabled={FeatureModule.SALES_POINTS.value}),
    )

    result = use_case.award_referral_bonus(
        tenant_id=TENANT,
        referrer_id=EmployeeId(uuid.uuid4()),
        referrer_store_id=STORE,
        new_employee_id=EmployeeId(uuid.uuid4()),
    )

    assert result is None
    assert repo.saved == []
    assert audit.entries == []


def test_referral_bonus_is_skipped_when_the_referrer_has_no_store() -> None:
    """`PointsEntry.store_id` MƏCBURİDİR — çoxlu-mağazalı roldan tövsiyə real ssenaridir."""
    audit = _Audit()
    use_case, repo = _points_use_case(audit=audit, clock=_Clock())

    result = use_case.award_referral_bonus(
        tenant_id=TENANT,
        referrer_id=EmployeeId(uuid.uuid4()),
        referrer_store_id=None,
        new_employee_id=EmployeeId(uuid.uuid4()),
    )

    assert result is None
    assert repo.saved == []


def test_referral_bonus_is_skipped_when_the_root_configured_points_are_zero() -> None:
    audit = _Audit()
    limits = _FakeSystemLimits({SystemLimitKey.EMPLOYEE_REFERRAL_BONUS_POINTS.value: "0"})
    use_case, repo = _points_use_case(audit=audit, clock=_Clock(), limits=limits)

    result = use_case.award_referral_bonus(
        tenant_id=TENANT,
        referrer_id=EmployeeId(uuid.uuid4()),
        referrer_store_id=STORE,
        new_employee_id=EmployeeId(uuid.uuid4()),
    )

    assert result is None
    assert repo.saved == []


def test_a_successful_referral_bonus_saves_a_points_entry_and_is_audited() -> None:
    audit = _Audit()
    referrer_id = EmployeeId(uuid.uuid4())
    new_employee_id = EmployeeId(uuid.uuid4())
    use_case, repo = _points_use_case(audit=audit, clock=_Clock())

    result = use_case.award_referral_bonus(
        tenant_id=TENANT,
        referrer_id=referrer_id,
        referrer_store_id=STORE,
        new_employee_id=new_employee_id,
    )

    assert result == 50  # DEFAULT_LIMITS[EMPLOYEE_REFERRAL_BONUS_POINTS]
    assert len(repo.saved) == 1
    entry = repo.saved[0]
    assert entry.employee_id == referrer_id
    assert entry.store_id == STORE
    assert entry.points == 50
    assert audit.actions() == ["REFERRAL_BONUS_AWARDED"]
    assert audit.entries[0]["after_state"]["new_employee_id"] == str(new_employee_id)
