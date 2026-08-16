"""Faza 5/6 use case-lərinin QƏRARLARI — kataloq, tapşırıq, xal, ROOT, istifadəçi.

BAZA LAZIM DEYİL: bütün portlar saxta obyektlə əvəz olunur və yalnız
"kim nə edə bilər / hansı əməliyyat audit-lənir" sualları yoxlanılır.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from src.application.use_cases.catalog_management import (
    CatalogPermissionError,
    FineTypeCatalogUseCase,
    LeaveTypeCatalogUseCase,
    WorkModeCatalogUseCase,
)
from src.application.use_cases.root_control import (
    CompensatingControlLockedError,
    RootControlError,
    RootControlUseCase,
    StructuralModuleError,
)
from src.application.use_cases.sales_points import SalesPointsError, SalesPointsUseCase
from src.application.use_cases.task_workflow import (
    TaskDraft,
    TaskNotFoundError,
    TaskWorkflowError,
    TaskWorkflowUseCase,
)
from src.application.use_cases.user_management import (
    EmployeeDraft,
    UserManagementUseCase,
)
from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.position import Position
from src.domain.entities.sales_points import PointsEntry
from src.domain.entities.task import Task, TaskStatus
from src.domain.policies import FeatureModule, SystemLimitKey
from src.domain.value_objects.authorization import (
    AuthorizationError,
    PermissionEffect,
    PermissionFlag,
    RolePriority,
)
from src.domain.value_objects.catalogs import FineType, LeaveType, WorkMode
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.face_recognition import FaceExemption
from src.domain.value_objects.gamification import (
    PointsPeriod,
    RedemptionStatus,
    RewardItem,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PointsEntryId,
    RedemptionId,
    RewardId,
    StoreId,
    TaskId,
    TenantId,
    new_face_exemption_id,
)
from src.domain.value_objects.money import Money
from tests.fixtures.fakes import InMemoryFaceExemptions

NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
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
        self.records: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.records.append(kwargs)

    def actions(self) -> list[str]:
        return [record["action"] for record in self.records]


class _Notifier:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[dict[str, Any]] = []
        self._fail = fail

    def notify(self, **kwargs: Any) -> None:
        if self._fail:
            raise RuntimeError("SMTP əlçatmazdır")
        self.sent.append(kwargs)


class _CatalogRepo:
    def __init__(self, entries: list[Any] | None = None) -> None:
        self.entries = entries or []
        self.saved: list[Any] = []
        self.deactivated: list[Any] = []

    def list_all(self, tenant_id: TenantId, *, include_inactive: bool = False) -> list[Any]:
        if include_inactive:
            return self.entries
        return [entry for entry in self.entries if entry.is_active]

    def get(self, entry_id: Any) -> Any:
        return self.entries[0] if self.entries else None

    def save(self, tenant_id: TenantId, entry: Any, *, changed_by: EmployeeId) -> None:
        self.saved.append(entry)

    def deactivate(self, tenant_id: TenantId, entry_id: Any, *, changed_by: EmployeeId) -> None:
        self.deactivated.append(entry_id)

    def get_default_duration(self, leave_type_id: Any) -> int | None:
        return None


def _position(code: str, priority: RolePriority) -> Position:
    return Position(
        position_id=uuid.uuid4(),  # type: ignore[arg-type]
        code=code,
        name_az=code.title(),
        priority=priority,
        tenant_id=TENANT,
        is_system=True,
    )


def _employee(
    *,
    code: str = "ROOT",
    # Defolt aktor `Root`-dur, yəni pilləsi də `RolePriority.ROOT` (0) olmalıdır.
    # Əvvəl burada `EXECUTIVE` yazılırdı, çünki `Root` və `CEO` eyni pilləni
    # paylaşırdı — həmin model artıq yoxdur (bax `RolePriority` docstring-i).
    priority: RolePriority = RolePriority.ROOT,
    flags: tuple[str, ...] = (),
    employee_id: EmployeeId | None = None,
) -> Employee:
    employee = Employee(
        employee_id=employee_id or EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=_position(code, priority),
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


# --------------------------------------------------------------------------- #
# Kataloq idarəetməsi
# --------------------------------------------------------------------------- #


def test_catalog_change_requires_the_flag() -> None:
    repo, audit = _CatalogRepo(), _Audit()
    use_case = WorkModeCatalogUseCase(repository=repo, audit=audit, clock=_Clock())

    with pytest.raises(CatalogPermissionError, match="can_manage_work_modes"):
        use_case.save(TENANT, _employee(flags=()), WorkMode(name="Səhər", tenant_id=TENANT))
    assert not repo.saved


def test_selection_list_needs_no_permission() -> None:
    """Kamera Operatorunun cərimə növü siyahısı boş qalmamalıdır."""
    repo = _CatalogRepo(
        [FineType(name="Gecikmə", tenant_id=TENANT, standard_amount=Money(Decimal("10.00")))]
    )
    use_case = FineTypeCatalogUseCase(repository=repo, audit=_Audit(), clock=_Clock())
    assert len(use_case.list_for_selection(TENANT)) == 1


def test_management_list_shows_deactivated_entries_too() -> None:
    """Root deaktiv sətri yenidən aktivləşdirə bilməlidir."""
    repo = _CatalogRepo(
        [
            LeaveType(name="Nahar", tenant_id=TENANT),
            LeaveType(
                name="Siqaret",
                tenant_id=TENANT,
                is_active=False,
                deactivated_at=NOW,
            ),
        ]
    )
    use_case = LeaveTypeCatalogUseCase(repository=repo, audit=_Audit(), clock=_Clock())
    actor = _employee(flags=("can_manage_leave_types",))

    assert len(use_case.list_for_management(TENANT, actor)) == 2
    assert len(use_case.list_for_selection(TENANT)) == 1


def test_fine_type_price_change_records_the_previous_value() -> None:
    """`can_issue_fines` sui-istifadəsini aşkarlamağın yeganə yolu budur."""
    previous = FineType(name="Gecikmə", tenant_id=TENANT, standard_amount=Money(Decimal("50.00")))
    repo, audit = _CatalogRepo([previous]), _Audit()
    use_case = FineTypeCatalogUseCase(repository=repo, audit=audit, clock=_Clock())

    from src.domain.value_objects.identifiers import FineTypeId

    use_case.save(
        TENANT,
        _employee(flags=("can_manage_fine_types",)),
        FineType(
            name="Gecikmə",
            tenant_id=TENANT,
            standard_amount=Money(Decimal("150.00")),
            fine_type_id=FineTypeId(uuid.uuid4()),
        ),
    )

    entry = audit.records[-1]
    assert entry["action"] == "FINE_TYPE_SAVED"
    assert entry["before_state"]["standard_amount"] == "50.00"
    assert entry["after_state"]["standard_amount"] == "150.00"


def test_deactivation_is_audited_not_deleted() -> None:
    repo, audit = _CatalogRepo(), _Audit()
    use_case = WorkModeCatalogUseCase(repository=repo, audit=audit, clock=_Clock())

    from src.domain.value_objects.identifiers import WorkModeId

    mode_id = WorkModeId(uuid.uuid4())
    use_case.deactivate(TENANT, _employee(flags=("can_manage_work_modes",)), mode_id)

    assert repo.deactivated == [mode_id]
    assert audit.actions() == ["WORK_MODE_DEACTIVATED"]


# --------------------------------------------------------------------------- #
# Tapşırıq axını
# --------------------------------------------------------------------------- #


class _TaskRepo:
    def __init__(self, tasks: list[Task] | None = None) -> None:
        self.tasks = {task.id: task for task in (tasks or [])}
        self.saves = 0

    def get(self, task_id: TaskId) -> Task | None:
        return self.tasks.get(task_id)

    def list_for_assignee(self, employee_id: EmployeeId, *, open_only: bool = True) -> list[Task]:
        return list(self.tasks.values())

    def list_awaiting_review(self, tenant_id: TenantId) -> list[Task]:
        return list(self.tasks.values())

    def list_overdue(self, tenant_id: TenantId, *, now: datetime) -> list[Task]:
        return [task for task in self.tasks.values() if task.is_overdue(now=now)]

    def save(self, task: Task) -> None:
        self.tasks[task.id] = task
        self.saves += 1


def _make_task(*, assignee: EmployeeId, manager: EmployeeId, hours: int = 8) -> Task:
    return Task(
        task_id=TaskId(uuid.uuid4()),
        tenant_id=TENANT,
        title="Vitrini yenilə",
        assignee_id=assignee,
        assigned_by=manager,
        deadline=NOW + timedelta(hours=hours),
        created_at=NOW,
    )


def test_assigning_requires_the_assign_flag() -> None:
    repo = _TaskRepo()
    use_case = TaskWorkflowUseCase(tasks=repo, audit=_Audit(), clock=_Clock(), notifier=_Notifier())
    with pytest.raises(TaskWorkflowError, match="can_assign_tasks"):
        use_case.assign(
            tenant_id=TENANT,
            actor=_employee(flags=()),
            draft=TaskDraft(
                title="Test", assignee_id=EmployeeId(uuid.uuid4()), deadline=NOW + timedelta(days=1)
            ),
            task_id=TaskId(uuid.uuid4()),
        )


def test_assignee_is_notified() -> None:
    repo, notifier = _TaskRepo(), _Notifier()
    use_case = TaskWorkflowUseCase(tasks=repo, audit=_Audit(), clock=_Clock(), notifier=notifier)
    assignee = EmployeeId(uuid.uuid4())

    use_case.assign(
        tenant_id=TENANT,
        actor=_employee(flags=("can_assign_tasks",)),
        draft=TaskDraft(
            title="Vitrini yenilə", assignee_id=assignee, deadline=NOW + timedelta(days=1)
        ),
        task_id=TaskId(uuid.uuid4()),
    )

    assert notifier.sent[0]["recipient_id"] == assignee


def test_only_the_assignee_can_submit_evidence() -> None:
    """Səlahiyyət deyil, SAHİBLİK yoxlanılır."""
    assignee = _employee(code="SATICI", priority=RolePriority.OPERATIONAL)
    other = _employee(code="SATICI", priority=RolePriority.OPERATIONAL)
    task = _make_task(assignee=assignee.id, manager=EmployeeId(uuid.uuid4()))
    repo = _TaskRepo([task])
    use_case = TaskWorkflowUseCase(tasks=repo, audit=_Audit(), clock=_Clock(), notifier=_Notifier())

    with pytest.raises(TaskWorkflowError, match="təyin olunduğu işçi"):
        use_case.submit_evidence(
            tenant_id=TENANT, actor=other, task_id=task.id, evidence_urls=["https://drive/1.jpg"]
        )


def test_approval_needs_the_separate_review_flag() -> None:
    """Bölmə 6: təsdiq `can_assign_tasks` DEYİL, ayrıca flag tələb edir."""
    manager = _employee(flags=("can_assign_tasks",))
    assignee = _employee(code="SATICI", priority=RolePriority.OPERATIONAL)
    task = _make_task(assignee=assignee.id, manager=manager.id)
    task.submit_evidence(evidence_urls=["https://drive/1.jpg"], submitted_at=NOW)

    repo = _TaskRepo([task])
    use_case = TaskWorkflowUseCase(tasks=repo, audit=_Audit(), clock=_Clock(), notifier=_Notifier())

    with pytest.raises(TaskWorkflowError, match="can_approve_task_evidence"):
        use_case.approve(tenant_id=TENANT, actor=manager, task_id=task.id)


def test_missing_task_raises_a_dedicated_error() -> None:
    use_case = TaskWorkflowUseCase(
        tasks=_TaskRepo(), audit=_Audit(), clock=_Clock(), notifier=_Notifier()
    )
    with pytest.raises(TaskNotFoundError):
        use_case.approve(
            tenant_id=TENANT,
            actor=_employee(flags=("can_approve_task_evidence",)),
            task_id=TaskId(uuid.uuid4()),
        )


def test_escalation_survives_a_failing_notifier() -> None:
    """Bildiriş kanalı sıradan çıxsa, digər tapşırıqlar eskalasiyasız qalmamalıdır."""
    task = _make_task(assignee=EmployeeId(uuid.uuid4()), manager=EmployeeId(uuid.uuid4()), hours=1)
    repo, audit = _TaskRepo([task]), _Audit()
    use_case = TaskWorkflowUseCase(
        tasks=repo,
        audit=audit,
        clock=_Clock(NOW + timedelta(hours=5)),
        notifier=_Notifier(fail=True),
    )

    result = use_case.escalate_overdue(tenant_id=TENANT)

    assert result.escalated_count == 1
    assert "TASK_DEADLINE_ESCALATED" in audit.actions()
    assert task.status is TaskStatus.OVERDUE


def test_escalation_is_not_repeated_on_the_next_cycle() -> None:
    task = _make_task(assignee=EmployeeId(uuid.uuid4()), manager=EmployeeId(uuid.uuid4()), hours=1)
    repo = _TaskRepo([task])
    use_case = TaskWorkflowUseCase(
        tasks=repo, audit=_Audit(), clock=_Clock(NOW + timedelta(hours=5)), notifier=_Notifier()
    )

    assert use_case.escalate_overdue(tenant_id=TENANT).escalated_count == 1
    assert use_case.escalate_overdue(tenant_id=TENANT).escalated_count == 0


# --------------------------------------------------------------------------- #
# Satış xalları
# --------------------------------------------------------------------------- #


class _PointsRepo:
    def __init__(self, entries: list[PointsEntry] | None = None) -> None:
        self.entries = {entry.id: entry for entry in (entries or [])}

    def get(self, entry_id: PointsEntryId) -> PointsEntry | None:
        return self.entries.get(entry_id)

    def list_for_employee(
        self, employee_id: EmployeeId, *, period: PointsPeriod
    ) -> list[PointsEntry]:
        return [e for e in self.entries.values() if e.employee_id == employee_id]

    def list_disputes(self, tenant_id: TenantId) -> list[PointsEntry]:
        return [e for e in self.entries.values() if e.has_open_dispute]

    def save(self, entry: PointsEntry) -> None:
        self.entries[entry.id] = entry


class _RewardRepo:
    def __init__(self, rewards: dict[RewardId, RewardItem] | None = None) -> None:
        self.rewards = rewards or {}
        self.redemptions: dict[RedemptionId, Any] = {}

    def list_rewards(
        self, tenant_id: TenantId, *, include_inactive: bool = False
    ) -> list[tuple[RewardId, RewardItem]]:
        return [
            (rid, item) for rid, item in self.rewards.items() if include_inactive or item.is_active
        ]

    def get_reward(self, reward_id: RewardId) -> RewardItem | None:
        return self.rewards.get(reward_id)

    def save_reward(self, tenant_id: TenantId, reward_id: RewardId, reward: RewardItem) -> None:
        self.rewards[reward_id] = reward

    def list_redemptions(self, tenant_id: TenantId, *, pending_only: bool = False) -> list[Any]:
        values = list(self.redemptions.values())
        if pending_only:
            return [r for r in values if r.status is RedemptionStatus.REQUESTED]
        return values

    def get_redemption(self, redemption_id: RedemptionId) -> Any:
        return self.redemptions.get(redemption_id)

    def save_redemption(self, redemption: Any) -> None:
        self.redemptions[redemption.id] = redemption


def _points_entry(*, employee: EmployeeId, points: int = 40) -> PointsEntry:
    return PointsEntry(
        entry_id=PointsEntryId(uuid.uuid4()),
        tenant_id=TENANT,
        employee_id=employee,
        store_id=STORE,
        points=points,
        awarded_at=NOW,
    )


def _points_use_case(
    *, points: _PointsRepo, rewards: _RewardRepo, audit: _Audit | None = None
) -> SalesPointsUseCase:
    return SalesPointsUseCase(
        points=points,
        rewards=rewards,
        audit=audit or _Audit(),
        clock=_Clock(),
        notifier=_Notifier(),
    )


def test_balance_subtracts_held_points() -> None:
    worker = _employee(code="SATICI", priority=RolePriority.OPERATIONAL)
    points = _PointsRepo([_points_entry(employee=worker.id, points=500)])
    rewards = _RewardRepo({RewardId(uuid.uuid4()): RewardItem(name="Kupon", cost_points=200)})
    use_case = _points_use_case(points=points, rewards=rewards)

    reward_id = next(iter(rewards.rewards))
    use_case.request_reward(
        tenant_id=TENANT,
        actor=worker,
        reward_id=reward_id,
        redemption_id=RedemptionId(uuid.uuid4()),
    )

    balance = use_case.balance_for(worker.id, tenant_id=TENANT)
    assert balance.earned == 500
    assert balance.held == 200
    assert balance.available == 300


def test_employee_cannot_dispute_someone_elses_points() -> None:
    owner = _employee(code="SATICI", priority=RolePriority.OPERATIONAL)
    intruder = _employee(code="SATICI", priority=RolePriority.OPERATIONAL)
    entry = _points_entry(employee=owner.id)
    use_case = _points_use_case(points=_PointsRepo([entry]), rewards=_RewardRepo())

    with pytest.raises(SalesPointsError, match="öz xal qeydinə"):
        use_case.open_dispute(
            tenant_id=TENANT, actor=intruder, entry_id=entry.id, reason="Mənim xalımdır"
        )


def test_dispute_decision_requires_the_points_flag() -> None:
    worker = _employee(code="SATICI", priority=RolePriority.OPERATIONAL)
    entry = _points_entry(employee=worker.id)
    use_case = _points_use_case(points=_PointsRepo([entry]), rewards=_RewardRepo())

    with pytest.raises(SalesPointsError, match="can_manage_sales_points"):
        use_case.decide_dispute(
            tenant_id=TENANT, actor=worker, entry_id=entry.id, reason="Qərar verildi"
        )


def test_zero_correction_is_recorded_as_a_reversal() -> None:
    """Ekranda «0» yazan istifadəçinin niyyəti tam ləğvdir."""
    worker = _employee(code="SATICI", priority=RolePriority.OPERATIONAL)
    manager = _employee(flags=("can_manage_sales_points",))
    entry = _points_entry(employee=worker.id)
    audit = _Audit()
    use_case = _points_use_case(points=_PointsRepo([entry]), rewards=_RewardRepo(), audit=audit)

    use_case.decide_dispute(
        tenant_id=TENANT,
        actor=manager,
        entry_id=entry.id,
        corrected_points=0,
        reason="Satış tamamilə başqa işçiyə aiddir",
    )
    assert "POINTS_REVERSED" in audit.actions()


def test_reset_notice_is_silent_outside_the_window() -> None:
    worker = _employee(code="SATICI", priority=RolePriority.OPERATIONAL)
    use_case = _points_use_case(
        points=_PointsRepo([_points_entry(employee=worker.id)]), rewards=_RewardRepo()
    )

    result = use_case.send_reset_notices(tenant_id=TENANT, employee_ids=[worker.id])
    assert result.notified_count == 0


def test_reset_notice_skips_employees_with_no_points() -> None:
    """«0 xalınız sıfırlanacaq» mesajı məlumat vermir."""
    worker = _employee(code="SATICI", priority=RolePriority.OPERATIONAL)
    notice_day = PointsPeriod.containing(date(2026, 8, 1)).notice_on()
    use_case = SalesPointsUseCase(
        points=_PointsRepo(),
        rewards=_RewardRepo(),
        audit=_Audit(),
        clock=_Clock(datetime.combine(notice_day, datetime.min.time(), tzinfo=UTC)),
        notifier=_Notifier(),
    )

    result = use_case.send_reset_notices(tenant_id=TENANT, employee_ids=[worker.id])
    assert result.notified_count == 0
    assert result.skipped_zero_balance == 1


def test_reset_notice_reaches_employees_with_a_balance() -> None:
    worker = _employee(code="SATICI", priority=RolePriority.OPERATIONAL)
    notice_day = PointsPeriod.containing(date(2026, 12, 20)).notice_on()
    clock = _Clock(datetime.combine(notice_day, datetime.min.time(), tzinfo=UTC))
    entry = PointsEntry(
        entry_id=PointsEntryId(uuid.uuid4()),
        tenant_id=TENANT,
        employee_id=worker.id,
        store_id=STORE,
        points=120,
        awarded_at=clock.now(),
    )
    notifier = _Notifier()
    use_case = SalesPointsUseCase(
        points=_PointsRepo([entry]),
        rewards=_RewardRepo(),
        audit=_Audit(),
        clock=clock,
        notifier=notifier,
    )

    result = use_case.send_reset_notices(tenant_id=TENANT, employee_ids=[worker.id])

    assert result.notified == [worker.id]
    assert "sıfırlanacaq" in notifier.sent[0]["title_az"]


# --------------------------------------------------------------------------- #
# ROOT Control Center
# --------------------------------------------------------------------------- #


class _Limits:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.written: list[tuple[str, str]] = []

    def get_int(self, tenant_id: TenantId, key: str, default: int) -> int:
        return default

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
        return default

    def all_for(self, tenant_id: TenantId) -> dict[str, str]:
        return {}

    def describe(self, tenant_id: TenantId) -> list[dict[str, Any]]:
        return self.rows

    def set_value(
        self, tenant_id: TenantId, key: str, value: str, *, changed_by: EmployeeId
    ) -> None:
        self.written.append((key, value))


class _Toggles:
    def __init__(
        self, *, structural: bool = False, rows: list[dict[str, Any]] | None = None
    ) -> None:
        self._structural = structural
        self.rows = rows or []
        self.written: list[tuple[str, bool, str | None]] = []

    def is_enabled(self, tenant_id: TenantId, module_key: str) -> bool:
        return True

    def describe(self, tenant_id: TenantId) -> list[dict[str, Any]]:
        return self.rows

    def is_structural(self, tenant_id: TenantId, module_key: str) -> bool:
        return self._structural

    def set_enabled(
        self,
        tenant_id: TenantId,
        module_key: str,
        *,
        enabled: bool,
        changed_by: EmployeeId,
        confirmation: str | None = None,
    ) -> None:
        self.written.append((module_key, enabled, confirmation))


class _Flags:
    def __init__(self, existing: dict[str, PermissionFlag] | None = None) -> None:
        self.existing = existing or {}
        self.created: list[PermissionFlag] = []

    def get(self, code: str) -> PermissionFlag | None:
        return self.existing.get(code)

    def list_all(self) -> list[PermissionFlag]:
        return list(self.existing.values())

    def create(self, flag: PermissionFlag, *, created_by: EmployeeId) -> None:
        self.created.append(flag)


def _root_use_case(
    *,
    limits: _Limits | None = None,
    toggles: _Toggles | None = None,
    flags: _Flags | None = None,
    audit: _Audit | None = None,
    face_exemptions: InMemoryFaceExemptions | None = None,
) -> RootControlUseCase:
    return RootControlUseCase(
        limits=limits or _Limits(),
        toggles=toggles or _Toggles(),
        flags=flags or _Flags(),
        # SEC-020 — defolt BOŞ siyahı: aktiv üz-təsdiqi istisnası olmayan
        # kirayəçi mövcud bütün testlərin ssenarisidir, yəni davranış DƏYİŞMİR.
        face_exemptions=face_exemptions or InMemoryFaceExemptions([]),
        audit=audit or _Audit(),
        clock=_Clock(),
    )


def test_limits_are_completed_with_defaults() -> None:
    """Root nəyin QÜVVƏDƏ olduğunu görməlidir, nəyin bazada yazıldığını yox."""
    use_case = _root_use_case()
    views = use_case.list_limits(
        tenant_id=TENANT, actor=_employee(flags=("can_manage_system_limits",))
    )

    keys = {view.key for view in views}
    assert keys == {limit.value for limit in SystemLimitKey}
    assert all(view.is_known_key for view in views)


def test_unknown_stored_limit_is_shown_but_flagged() -> None:
    limits = _Limits([{"limit_key": "KOHNE_LIMIT", "limit_value": "5"}])
    use_case = _root_use_case(limits=limits)

    views = use_case.list_limits(
        tenant_id=TENANT, actor=_employee(flags=("can_manage_system_limits",))
    )
    stale = [view for view in views if view.key == "KOHNE_LIMIT"]
    assert stale and not stale[0].is_known_key


def test_limit_change_is_audited_with_the_previous_value() -> None:
    limits, audit = _Limits(), _Audit()
    use_case = _root_use_case(limits=limits, audit=audit)

    use_case.set_limit(
        tenant_id=TENANT,
        actor=_employee(flags=("can_manage_system_limits",)),
        key=SystemLimitKey.DUAL_CONTROL_THRESHOLD_MINUTES,
        value="45",
    )

    assert limits.written == [("DUAL_CONTROL_THRESHOLD_MINUTES", "45")]
    assert audit.records[-1]["before_state"] == {"value": "30"}


def test_empty_limit_value_is_refused() -> None:
    use_case = _root_use_case()
    with pytest.raises(RootControlError):
        use_case.set_limit(
            tenant_id=TENANT,
            actor=_employee(flags=("can_manage_system_limits",)),
            key=SystemLimitKey.PIN_LOCKOUT_MINUTES,
            value="   ",
        )


def test_structural_module_needs_a_written_confirmation() -> None:
    toggles = _Toggles(structural=True)
    use_case = _root_use_case(toggles=toggles)

    with pytest.raises(StructuralModuleError):
        use_case.set_module_enabled(
            tenant_id=TENANT,
            actor=_employee(flags=("can_manage_system_limits",)),
            module_key="CAMERA_VERIFICATION",
            enabled=False,
            confirmation="ok",
        )
    assert not toggles.written


def test_structural_module_disables_with_a_proper_confirmation() -> None:
    toggles = _Toggles(structural=True)
    use_case = _root_use_case(toggles=toggles)

    use_case.set_module_enabled(
        tenant_id=TENANT,
        actor=_employee(flags=("can_manage_system_limits",)),
        module_key="CAMERA_VERIFICATION",
        enabled=False,
        confirmation="Razıyam, söndürülsün",
    )
    assert toggles.written[0][1] is False


def test_enabling_never_needs_a_confirmation() -> None:
    toggles = _Toggles(structural=True)
    use_case = _root_use_case(toggles=toggles)

    use_case.set_module_enabled(
        tenant_id=TENANT,
        actor=_employee(flags=("can_manage_system_limits",)),
        module_key="CAMERA_VERIFICATION",
        enabled=True,
    )
    assert toggles.written[0][1] is True


# --------------------------------------------------------------------------- #
# SEC-020 — kompensasiya edici nəzarətin şərti kilidi
# --------------------------------------------------------------------------- #
#
# BAĞLANAN BOŞLUQ: `facecontrol.md` bənd 14 PIN-only istisnasının YEGANƏ
# əvəzləyicisi kimi `DUAL_CONTROL` axınını göstərir, həmin modul isə adi
# (struktur-olmayan) toggle idi — yəni Root bir kliklə istisnalı işçini
# kompensasiyasız qoya bilirdi.


def _active_face_exemption() -> FaceExemption:
    return FaceExemption(
        exemption_id=new_face_exemption_id(),
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        granted_by=EmployeeId(uuid.uuid4()),
        reason="Tibbi arayış — üz nahiyəsində sarğı var",
        granted_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=30),
    )


def test_dual_control_cannot_be_disabled_while_a_face_exemption_is_active() -> None:
    """Struktur zəmanət sadə toggle ilə söndürülə bilməz (CLAUDE.md §5)."""
    toggles = _Toggles()
    use_case = _root_use_case(
        toggles=toggles, face_exemptions=InMemoryFaceExemptions([_active_face_exemption()])
    )

    with pytest.raises(CompensatingControlLockedError) as caught:
        use_case.set_module_enabled(
            tenant_id=TENANT,
            actor=_employee(flags=("can_manage_system_limits",)),
            module_key=FeatureModule.DUAL_CONTROL.value,
            enabled=False,
        )

    # Mesaj SƏBƏBİ (neçə istisna) və NÖVBƏTİ ADDIMI deyir — «Sistem xətası» yox.
    assert "1 aktiv" in caught.value.user_message
    assert "ləğv" in caught.value.user_message
    # Yazı BAŞ VERMƏYİB: qapı sükutlu "heç nə etmə" deyil, əməliyyat ləğvidir.
    assert not toggles.written


def test_disabling_dual_control_works_once_the_exemptions_are_gone() -> None:
    """KİLİD ƏBƏDİ DEYİL — açar Root-un öz əlindədir.

    Bu yoxlama olmasa, guard "həmişə bloklayan" versiyaya sürüşə bilər və
    modul bir daha heç vaxt söndürülə bilməzdi.
    """
    toggles = _Toggles()
    use_case = _root_use_case(toggles=toggles, face_exemptions=InMemoryFaceExemptions([]))

    use_case.set_module_enabled(
        tenant_id=TENANT,
        actor=_employee(flags=("can_manage_system_limits",)),
        module_key=FeatureModule.DUAL_CONTROL.value,
        enabled=False,
    )

    assert toggles.written[0] == (FeatureModule.DUAL_CONTROL.value, False, None)


def test_an_expired_exemption_no_longer_locks_the_module() -> None:
    """Meyar `list_active` ilə eynidir — müddəti keçmiş sətir kilidləmir.

    Gecəlik iş işləməyəndə (terminal söndürülüb) `ACTIVE` sətir faktiki olaraq
    bitmiş olur. Yalnız statusa baxsaydıq, cron-un işləməməsi modulu ƏBƏDİ
    kilidləyərdi.
    """
    stale = FaceExemption(
        exemption_id=new_face_exemption_id(),
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        granted_by=EmployeeId(uuid.uuid4()),
        reason="Tibbi arayış — üz nahiyəsində sarğı var",
        granted_at=NOW - timedelta(days=40),
        expires_at=NOW - timedelta(days=1),
    )
    toggles = _Toggles()
    use_case = _root_use_case(toggles=toggles, face_exemptions=InMemoryFaceExemptions([stale]))

    use_case.set_module_enabled(
        tenant_id=TENANT,
        actor=_employee(flags=("can_manage_system_limits",)),
        module_key=FeatureModule.DUAL_CONTROL.value,
        enabled=False,
    )

    assert toggles.written[0][1] is False


def test_the_compensation_lock_touches_only_the_compensating_module() -> None:
    """REQRESSİYA QAPISI: qayda DARDIR — başqa modul sərbəst söndürülür."""
    toggles = _Toggles()
    use_case = _root_use_case(
        toggles=toggles, face_exemptions=InMemoryFaceExemptions([_active_face_exemption()])
    )

    use_case.set_module_enabled(
        tenant_id=TENANT,
        actor=_employee(flags=("can_manage_system_limits",)),
        module_key=FeatureModule.SHIFT_SWAP.value,
        enabled=False,
    )

    assert toggles.written[0] == (FeatureModule.SHIFT_SWAP.value, False, None)


def test_enabling_the_compensating_module_is_never_blocked() -> None:
    """AÇMAQ heç vaxt bloklanmır — əks halda vəziyyət düzəldilə bilməzdi."""
    toggles = _Toggles()
    use_case = _root_use_case(
        toggles=toggles, face_exemptions=InMemoryFaceExemptions([_active_face_exemption()])
    )

    use_case.set_module_enabled(
        tenant_id=TENANT,
        actor=_employee(flags=("can_manage_system_limits",)),
        module_key=FeatureModule.DUAL_CONTROL.value,
        enabled=True,
    )

    assert toggles.written[0][1] is True


def test_the_compensation_lock_runs_after_the_permission_check() -> None:
    """Səlahiyyəti olmayan aktor kilidin mesajını GÖRMƏMƏLİDİR.

    «N aktiv üz-təsdiqi istisnası var» cavabı özü məlumatdır: kimin üz
    təsdiqindən azad olduğunu bilmək hücum planlaşdırmaq üçün yararlıdır
    (`FaceControlExemptionUseCase.list_active` ilə eyni qərar). Ona görə
    səlahiyyət qapısı ƏVVƏL gəlir.
    """
    toggles = _Toggles()
    use_case = _root_use_case(
        toggles=toggles, face_exemptions=InMemoryFaceExemptions([_active_face_exemption()])
    )

    with pytest.raises(RootControlError) as caught:
        use_case.set_module_enabled(
            tenant_id=TENANT,
            actor=_employee(),
            module_key=FeatureModule.DUAL_CONTROL.value,
            enabled=False,
        )

    assert not isinstance(caught.value, CompensatingControlLockedError)
    assert "istisna" not in caught.value.user_message


def test_only_root_may_create_a_permission_flag() -> None:
    """Bölmə 3: «yeni flag yaratma, YALNIZ Root»."""
    use_case = _root_use_case()
    ceo = _employee(code="CEO", priority=RolePriority.EXECUTIVE, flags=("can_manage_permissions",))

    with pytest.raises(RootControlError, match="YALNIZ Root"):
        use_case.create_flag(
            tenant_id=TENANT, actor=ceo, flag=PermissionFlag(code="can_test", category="TEST")
        )


def test_duplicate_flag_is_refused() -> None:
    existing = PermissionFlag(code="can_test", category="TEST")
    use_case = _root_use_case(flags=_Flags({"can_test": existing}))

    with pytest.raises(RootControlError, match="artıq mövcuddur"):
        use_case.create_flag(
            tenant_id=TENANT,
            actor=_employee(flags=("can_manage_permissions",)),
            flag=existing,
        )


def test_root_creates_a_new_flag_and_it_is_audited() -> None:
    flags, audit = _Flags(), _Audit()
    use_case = _root_use_case(flags=flags, audit=audit)

    use_case.create_flag(
        tenant_id=TENANT,
        actor=_employee(flags=("can_manage_permissions",)),
        flag=PermissionFlag(code="can_view_kpi", category="HESABAT"),
    )

    assert [flag.code for flag in flags.created] == ["can_view_kpi"]
    assert "PERMISSION_FLAG_CREATED" in audit.actions()


# --------------------------------------------------------------------------- #
# İstifadəçi idarəetməsi
# --------------------------------------------------------------------------- #


class _EmployeeRepo:
    def __init__(self, employees: list[Employee] | None = None) -> None:
        self.employees = {e.id: e for e in (employees or [])}
        self.saved: list[Employee] = []
        #: `create()` ilə yaradılanlar — `save()`-dən AYRI saxlanılır, çünki
        #: istehsalatda da ayrıdır (`save()` `UPDATE`-dir, sətir yaratmır).
        self.created: list[Employee] = []

    def get(self, employee_id: EmployeeId) -> Employee | None:
        return self.employees.get(employee_id)

    def get_by_username(self, tenant_id: TenantId, username: Username) -> Employee | None:
        return None

    def find_by_pin_candidates(self, tenant_id: TenantId, store_id: StoreId) -> list[Employee]:
        return []

    def count_active_with_flag(self, tenant_id: TenantId, flag_code: str) -> int:
        return 1

    def save(self, employee: Employee) -> None:
        self.employees[employee.id] = employee
        self.saved.append(employee)

    def create(
        self,
        employee: Employee,
        *,
        raw_password: str | None = None,
        raw_pin: str | None = None,
    ) -> None:
        self.employees[employee.id] = employee
        self.created.append(employee)


class _Credentials:
    def __init__(self) -> None:
        self.passwords: list[tuple[EmployeeId, bool]] = []
        self.pins: list[EmployeeId] = []
        self.lockouts_cleared: list[EmployeeId] = []

    def set_password(
        self, employee_id: EmployeeId, *, raw_password: str, must_change: bool
    ) -> None:
        self.passwords.append((employee_id, must_change))

    def set_pin(self, employee_id: EmployeeId, *, raw_pin: str) -> None:
        self.pins.append(employee_id)

    def clear_pin_lockout(self, employee_id: EmployeeId) -> None:
        self.lockouts_cleared.append(employee_id)


def _user_use_case(
    *, employees: _EmployeeRepo, credentials: _Credentials, audit: _Audit
) -> UserManagementUseCase:
    return UserManagementUseCase(
        employees=employees, credentials=credentials, audit=audit, clock=_Clock()
    )


def test_admin_reset_password_always_forces_a_change() -> None:
    """Adminin bildiyi şifrə daimi qala bilməz."""
    target = _employee(code="SATICI", priority=RolePriority.OPERATIONAL)
    repo, creds, audit = _EmployeeRepo([target]), _Credentials(), _Audit()
    use_case = _user_use_case(employees=repo, credentials=creds, audit=audit)

    use_case.reset_password(
        tenant_id=TENANT,
        actor=_employee(flags=("can_reset_password",)),
        employee_id=target.id,
        new_password="Yeni-Şifrə-123",
    )

    assert creds.passwords == [(target.id, True)]
    assert target.must_change_password
    assert "PASSWORD_RESET_BY_ADMIN" in audit.actions()


def test_pin_reset_also_clears_the_lockout() -> None:
    """Yeni PIN 15 dəqiqə gözləyən işçiyə kömək etməzdi."""
    target = _employee(code="SATICI", priority=RolePriority.OPERATIONAL)
    repo, creds = _EmployeeRepo([target]), _Credentials()
    use_case = _user_use_case(employees=repo, credentials=creds, audit=_Audit())

    use_case.reset_pin(
        tenant_id=TENANT,
        actor=_employee(flags=("can_reset_pin",)),
        employee_id=target.id,
        new_pin="4821",
    )

    assert creds.lockouts_cleared == [target.id]


def test_lower_rank_cannot_reset_a_higher_rank_password() -> None:
    """STRICT HIERARCHY GUARD şifrə sıfırlama yolu ilə yan keçilə bilməz."""
    ceo = _employee(code="CEO", priority=RolePriority.EXECUTIVE)
    hr = _employee(
        code="HR_ADMIN", priority=RolePriority.OPERATIONAL, flags=("can_reset_password",)
    )
    repo = _EmployeeRepo([ceo, hr])
    use_case = _user_use_case(employees=repo, credentials=_Credentials(), audit=_Audit())

    with pytest.raises(AuthorizationError, match="HIERARCHY"):
        use_case.reset_password(
            tenant_id=TENANT, actor=hr, employee_id=ceo.id, new_password="Yeni-Şifrə-123"
        )


def test_cannot_assign_a_position_above_your_own() -> None:
    """Onsuz HR_Admin yeni Root yaradıb həmin hesabla daxil ola bilərdi."""
    hr = _employee(
        code="HR_ADMIN", priority=RolePriority.OPERATIONAL, flags=("can_manage_employees",)
    )
    use_case = _user_use_case(
        employees=_EmployeeRepo([hr]), credentials=_Credentials(), audit=_Audit()
    )

    with pytest.raises(AuthorizationError, match="rol təyin edilə bilməz"):
        use_case.create_employee(
            tenant_id=TENANT,
            actor=hr,
            employee_id=EmployeeId(uuid.uuid4()),
            draft=EmployeeDraft(
                first_name="Yeni",
                last_name="Root",
                position=_position("ROOT", RolePriority.ROOT),
            ),
            initial_pin="4821",
        )


def test_root_can_now_create_a_ceo_account() -> None:
    """PRİORİTET AYRILIĞININ FUNKSİONAL QAZANCI (reqressiya qapısı).

    `_assert_may_assign_position` aktorun rolunun hədəf roldan CİDDİ ŞƏKİLDƏ
    yuxarıda olmasını tələb edir. Köhnə modeldə `Root` və `CEO` hər ikisi
    prioritet 0-da idi, yəni `Root` YENİ CEO HESABI YARADA BİLMİRDİ —
    iyerarxiyanın ən üstündəki istifadəçi öz birbaşa tabeliyindəki rolu
    təyin edə bilmirdi. Bu, səhv modelin sükutla yaratdığı funksional qüsur
    idi. İndi `Root` (0) `CEO`-nu (1) ciddi şəkildə üstələyir və axın işləyir.

    `Root` → `Root` istiqaməti isə BLOKLU qalır (bərabər pillə) — bu, qəsdli
    məhdudiyyətdir və yuxarıdakı test onu artıq qoruyur.
    """
    root = _employee(flags=("can_manage_employees",))
    repo = _EmployeeRepo([root])
    use_case = _user_use_case(employees=repo, credentials=_Credentials(), audit=_Audit())

    created = use_case.create_employee(
        tenant_id=TENANT,
        actor=root,
        employee_id=EmployeeId(uuid.uuid4()),
        draft=EmployeeDraft(
            first_name="Yeni",
            last_name="CEO",
            position=_position("CEO", RolePriority.EXECUTIVE),
        ),
        initial_pin="4821",
    )

    assert created.position.code == "CEO"
    assert created.position.priority is RolePriority.EXECUTIVE


def test_root_can_now_deactivate_a_ceo_account() -> None:
    """`_assert_may_manage` də prioritet ayrılığından FAYDA GÖRÜR.

    Köhnə modeldə `Root` (0) `CEO`-nu (0) ÜSTƏLƏMİRDİ, yəni `Root` çıxıb
    getmiş CEO-nun hesabını deaktiv edə BİLMİRDİ — tenant sahibi öz
    sistemində ən həssas hesabı bağlaya bilmirdi. Bu, səhv modelin sükutla
    yaratdığı ikinci funksional qüsur idi (birincisi: CEO hesabı yaratmaq).

    `CEO` → `Root` istiqaməti isə BAĞLIDIR və aşağıdakı `assert` onu ayrıca
    təsbit edir — düzəliş yalnız BİR istiqaməti açır.
    """
    root = _employee(flags=("can_manage_employees",))
    ceo = _employee(code="CEO", priority=RolePriority.EXECUTIVE)
    repo, audit = _EmployeeRepo([root, ceo]), _Audit()
    use_case = _user_use_case(employees=repo, credentials=_Credentials(), audit=audit)

    deactivated = use_case.deactivate_employee(
        tenant_id=TENANT, actor=root, employee_id=ceo.id, reason="Vəzifədən azad edildi"
    )

    assert deactivated.is_active is False
    assert "EMPLOYEE_DEACTIVATED" in audit.actions()

    # Əks istiqamət: CEO `Root` hesabına toxuna bilmir.
    ceo_actor = _employee(
        code="CEO", priority=RolePriority.EXECUTIVE, flags=("can_manage_employees",)
    )
    repo_2 = _EmployeeRepo([root, ceo_actor])
    use_case_2 = _user_use_case(employees=repo_2, credentials=_Credentials(), audit=_Audit())

    with pytest.raises(AuthorizationError, match="HIERARCHY"):
        use_case_2.deactivate_employee(
            tenant_id=TENANT, actor=ceo_actor, employee_id=root.id, reason="Test"
        )


def test_multi_store_assignment_is_camera_operator_only() -> None:
    root = _employee(flags=("can_manage_employees",))
    use_case = _user_use_case(
        employees=_EmployeeRepo([root]), credentials=_Credentials(), audit=_Audit()
    )

    from src.application.use_cases.user_management import UserManagementError

    with pytest.raises(UserManagementError, match="Kamera"):
        use_case.create_employee(
            tenant_id=TENANT,
            actor=root,
            employee_id=EmployeeId(uuid.uuid4()),
            draft=EmployeeDraft(
                first_name="Adi",
                last_name="Satıcı",
                position=_position("SATICI", RolePriority.OPERATIONAL),
                camera_store_ids=(STORE,),
            ),
            initial_pin="4821",
        )


def test_self_deactivation_is_blocked() -> None:
    """Sistemin son adminini itirmək riski."""
    root = _employee(flags=("can_manage_employees",))
    use_case = _user_use_case(
        employees=_EmployeeRepo([root]), credentials=_Credentials(), audit=_Audit()
    )

    from src.application.use_cases.user_management import UserManagementError

    with pytest.raises(UserManagementError, match="öz hesabını"):
        use_case.deactivate_employee(
            tenant_id=TENANT, actor=root, employee_id=root.id, reason="Test"
        )


def test_deactivation_never_deletes_the_row() -> None:
    target = _employee(code="SATICI", priority=RolePriority.OPERATIONAL)
    repo, audit = _EmployeeRepo([target]), _Audit()
    use_case = _user_use_case(employees=repo, credentials=_Credentials(), audit=audit)

    use_case.deactivate_employee(
        tenant_id=TENANT,
        actor=_employee(flags=("can_manage_employees",)),
        employee_id=target.id,
        reason="İşdən çıxdı",
    )

    assert target.id in repo.employees
    assert not target.is_active
    assert audit.records[-1]["reason"] == "İşdən çıxdı"


# --------------------------------------------------------------------------- #
# Feature Toggle-ların RETROAKTİV-TƏSİRSİZLİYİ (bölmə 3, bənd 2)
# --------------------------------------------------------------------------- #
#
# Qayda: modul söndürüldükdə YALNIZ yeni instansiya bloklanır. Mövcud
# qeydlər toxunulmaz qalır, silinmir və axınını normal tamamlayır. Aşağıdakı
# testlər hər üç modul üçün bu iki tərəfi AYRICA yoxlayır — yalnız "bloklandı"
# testi yazsaydıq, "hamısını dayandır" səhv tətbiqi də keçərdi.


class _DisablingToggles:
    """Verilmiş modulları söndürülmüş göstərən sadə toggle mənbəyi."""

    def __init__(self, *disabled: str) -> None:
        self.disabled = set(disabled)

    def is_enabled(self, tenant_id: TenantId, module_key: str) -> bool:
        return module_key not in self.disabled


def test_disabled_task_engine_blocks_new_assignments() -> None:
    from src.domain.policies import FeatureModule

    repo = _TaskRepo()
    use_case = TaskWorkflowUseCase(
        tasks=repo,
        audit=_Audit(),
        clock=_Clock(),
        notifier=_Notifier(),
        toggles=_DisablingToggles(FeatureModule.TASK_ENGINE.value),
    )

    with pytest.raises(TaskWorkflowError, match="TASK_ENGINE"):
        use_case.assign(
            tenant_id=TENANT,
            actor=_employee(flags=("can_assign_tasks",)),
            draft=TaskDraft(
                title="Test",
                assignee_id=EmployeeId(uuid.uuid4()),
                deadline=NOW + timedelta(days=1),
            ),
            task_id=TaskId(uuid.uuid4()),
        )
    assert repo.saves == 0


def test_disabled_task_engine_still_lets_existing_tasks_finish() -> None:
    """RETROAKTİV-TƏSİRSİZLİK: mövcud tapşırıq sübutunu yükləyə bilir."""
    from src.domain.policies import FeatureModule

    worker = _employee(code="SATICI", priority=RolePriority.OPERATIONAL)
    manager = _employee(flags=("can_assign_tasks",))
    task = _make_task(assignee=worker.id, manager=manager.id)
    repo = _TaskRepo([task])
    use_case = TaskWorkflowUseCase(
        tasks=repo,
        audit=_Audit(),
        clock=_Clock(),
        notifier=_Notifier(),
        toggles=_DisablingToggles(FeatureModule.TASK_ENGINE.value),
    )

    updated = use_case.submit_evidence(
        tenant_id=TENANT,
        actor=worker,
        task_id=task.id,
        evidence_urls=["https://drive.example/1"],
    )
    assert updated.id == task.id
    assert task.id in repo.tasks, "Söndürülmüş modul mövcud qeydi SİLMƏMƏLİDİR"


def test_disabled_sales_points_blocks_new_reward_requests() -> None:
    from src.domain.policies import FeatureModule

    worker = _employee(code="SATICI", priority=RolePriority.OPERATIONAL)
    reward_id = RewardId(uuid.uuid4())
    rewards = _RewardRepo({reward_id: RewardItem(name="Kupon", cost_points=10)})
    use_case = SalesPointsUseCase(
        points=_PointsRepo([_points_entry(employee=worker.id, points=500)]),
        rewards=rewards,
        audit=_Audit(),
        clock=_Clock(),
        notifier=_Notifier(),
        toggles=_DisablingToggles(FeatureModule.SALES_POINTS.value),
    )

    with pytest.raises(SalesPointsError, match="SALES_POINTS"):
        use_case.request_reward(
            tenant_id=TENANT,
            actor=worker,
            reward_id=reward_id,
            redemption_id=RedemptionId(uuid.uuid4()),
        )
    assert not rewards.redemptions


def test_disabled_sales_points_keeps_historic_points_readable() -> None:
    """Qazanılmış xallar söndürmədən SONRA da balansda görünməlidir."""
    from src.domain.policies import FeatureModule

    worker = _employee(code="SATICI", priority=RolePriority.OPERATIONAL)
    points = _PointsRepo([_points_entry(employee=worker.id, points=500)])
    use_case = SalesPointsUseCase(
        points=points,
        rewards=_RewardRepo(),
        audit=_Audit(),
        clock=_Clock(),
        notifier=_Notifier(),
        toggles=_DisablingToggles(FeatureModule.SALES_POINTS.value),
    )

    assert use_case.balance_for(worker.id, tenant_id=TENANT).available == 500
    # Yeni xal isə yazılmır — sətir sayı dəyişmir.
    before = len(points.entries)
    awarded = use_case.award_for_sale(
        tenant_id=TENANT,
        employee_id=worker.id,
        store_id=STORE,
        transaction_id=uuid.uuid4(),  # type: ignore[arg-type]
        gross_amount=Decimal("500.00"),
    )
    assert awarded is None
    assert len(points.entries) == before
