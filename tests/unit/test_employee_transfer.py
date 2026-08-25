"""Filiallar-arası köçürmə sorğusu — entity + `TransferRequestUseCase` (`v2backlog.md` Faza 3.3).

BAZA LAZIM DEYİL — `test_phase5_use_cases.py`/`test_shift_scheduling.py` ilə
EYNİ naxış: bütün portlar sahtə obyektlərlə əvəz olunur.

──────────────────────────────────────────────────────────────────────────────
NİYƏ MƏHZ BUNLAR YOXLANILIR
──────────────────────────────────────────────────────────────────────────────
`withdraw()` `_decide()`-in vəzifə-ayrılığı qadağasından İSTİSNADIR — bu
İSTİSNA yalnız «öz sorğusunu geri çəkmək» üçündür, «başqasının sorğusunu geri
çəkmək» üçün DEYİL. Səlahiyyət sərhədini (`TransferRequestUseCase.withdraw`)
VƏ vəzifə-ayrılığını (`EmployeeTransferRequest._decide`) AYRI-AYRI yoxlamaq
lazımdır, çünki onlar İKİ FƏRQLİ qatdadır (istifadə hal / entity) — biri
pozulsa digəri gizlədə bilər.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest

from src.application.use_cases.employee_transfer import (
    APPROVE_TRANSFER_FLAG,
    TransferNotFoundError,
    TransferPermissionError,
    TransferRequestError,
    TransferRequestUseCase,
)
from src.domain.entities.base import DomainRuleError
from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.employee_transfer import EmployeeTransferRequest, TransferStatus
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import PermissionEffect, RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    StoreId,
    TenantId,
    new_transfer_request_id,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
TENANT = TenantId(uuid.uuid4())
STORE_A = StoreId(uuid.uuid4())
STORE_B = StoreId(uuid.uuid4())


# --------------------------------------------------------------------------- #
# Saxta portlar — `test_phase5_use_cases.py` ilə EYNİ üslub
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


class _TransferRepo:
    """`EmployeeTransferRequestRepository` — yaddaşda."""

    def __init__(self) -> None:
        self.items: dict[Any, EmployeeTransferRequest] = {}

    def get(self, request_id: Any) -> EmployeeTransferRequest | None:
        return self.items.get(request_id)

    def list_pending(
        self, tenant_id: TenantId, *, to_store_id: StoreId | None = None
    ) -> list[EmployeeTransferRequest]:
        return [
            r
            for r in self.items.values()
            if r.tenant_id == tenant_id
            and r.status is TransferStatus.PENDING_APPROVAL
            and (to_store_id is None or r.to_store_id == to_store_id)
        ]

    def list_for_employee(
        self, employee_id: EmployeeId, *, limit: int
    ) -> list[EmployeeTransferRequest]:
        return [r for r in self.items.values() if r.employee_id == employee_id][:limit]

    def find_open_for_employee(self, employee_id: EmployeeId) -> EmployeeTransferRequest | None:
        for r in self.items.values():
            if r.employee_id == employee_id and r.status is TransferStatus.PENDING_APPROVAL:
                return r
        return None

    def list_due_for_effect(
        self, tenant_id: TenantId, *, as_of: date
    ) -> list[EmployeeTransferRequest]:
        """Portun kontraktı: `APPROVED`, `effective_date <= as_of`, VƏ HƏLƏ
        icra olunmayıb (`employees.store_id != to_store_id`) — bax portun
        docstring-i, `use_cases/employee_transfer.py` başlığı."""
        return [
            r
            for r in self.items.values()
            if r.tenant_id == tenant_id
            and r.status is TransferStatus.APPROVED
            and r.effective_date is not None
            and r.effective_date <= as_of
        ]

    def save(self, request: EmployeeTransferRequest) -> None:
        self.items[request.id] = request


def _position(code: str, priority: RolePriority) -> Position:
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
    code: str = "SATICI",
    priority: RolePriority = RolePriority.OPERATIONAL,
    flags: tuple[str, ...] = (),
    store_id: StoreId | None = STORE_A,
) -> Employee:
    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=_position(code, priority),
        first_name="Ad",
        last_name="Soyad",
        store_id=store_id,
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


class Ctx:
    def __init__(self) -> None:
        self.clock = _Clock()
        self.transfers = _TransferRepo()
        self.employees = _EmployeeRepo()
        self.audit = _Audit()
        self.notifier = _Notifier()

    def use_case(self) -> TransferRequestUseCase:
        return TransferRequestUseCase(
            transfers=self.transfers,  # type: ignore[arg-type]
            employees=self.employees,  # type: ignore[arg-type]
            audit=self.audit,  # type: ignore[arg-type]
            clock=self.clock,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
        )


@pytest.fixture
def ctx() -> Ctx:
    return Ctx()


# --------------------------------------------------------------------------- #
# Entity qaydaları
# --------------------------------------------------------------------------- #


def test_source_and_target_store_cannot_be_the_same() -> None:
    with pytest.raises(DomainRuleError, match="eyni ola bilməz"):
        EmployeeTransferRequest(
            request_id=new_transfer_request_id(),
            tenant_id=TENANT,
            employee_id=EmployeeId(uuid.uuid4()),
            from_store_id=STORE_A,
            to_store_id=STORE_A,
            reason="Ailə səbəbi",
            requested_by=EmployeeId(uuid.uuid4()),
            created_at=NOW,
        )


def test_worker_cannot_approve_their_own_transfer() -> None:
    """Vəzifə ayrılığı — `_decide()` daxilində."""
    worker = EmployeeId(uuid.uuid4())
    request = EmployeeTransferRequest(
        request_id=new_transfer_request_id(),
        tenant_id=TENANT,
        employee_id=worker,
        from_store_id=STORE_A,
        to_store_id=STORE_B,
        reason="Ailə səbəbi",
        requested_by=worker,
        created_at=NOW,
    )
    with pytest.raises(DomainRuleError, match="öz köçürmə sorğusunu özü"):
        request.approve(approver_id=worker, decided_at=NOW)


def test_reject_requires_a_reason_of_minimum_length() -> None:
    request = EmployeeTransferRequest(
        request_id=new_transfer_request_id(),
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        from_store_id=STORE_A,
        to_store_id=STORE_B,
        reason="Ailə səbəbi",
        requested_by=EmployeeId(uuid.uuid4()),
        created_at=NOW,
    )
    with pytest.raises(DomainRuleError, match="Rədd səbəbi"):
        request.reject(approver_id=EmployeeId(uuid.uuid4()), decided_at=NOW, reason="qısa")


def test_a_decided_request_cannot_be_decided_again() -> None:
    request = EmployeeTransferRequest(
        request_id=new_transfer_request_id(),
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        from_store_id=STORE_A,
        to_store_id=STORE_B,
        reason="Ailə səbəbi",
        requested_by=EmployeeId(uuid.uuid4()),
        created_at=NOW,
    )
    request.approve(approver_id=EmployeeId(uuid.uuid4()), decided_at=NOW)

    with pytest.raises(DomainRuleError, match="artıq qərar alıb"):
        request.reject(
            approver_id=EmployeeId(uuid.uuid4()),
            decided_at=NOW,
            reason="Gec qaldı, artıq qərar var",
        )


def test_withdraw_is_indistinguishable_from_a_manager_rejection_without_the_property() -> None:
    """`is_withdrawn` — DB-də ayrıca status yoxdur, fərq YALNIZ bu property ilə görünür."""
    worker = EmployeeId(uuid.uuid4())
    request = EmployeeTransferRequest(
        request_id=new_transfer_request_id(),
        tenant_id=TENANT,
        employee_id=worker,
        from_store_id=STORE_A,
        to_store_id=STORE_B,
        reason="Ailə səbəbi",
        requested_by=worker,
        created_at=NOW,
    )
    request.withdraw(withdrawn_at=NOW)

    assert request.status is TransferStatus.REJECTED
    assert request.is_withdrawn is True
    assert request.decided_by == worker


def test_a_manager_rejection_is_not_flagged_as_withdrawn() -> None:
    worker = EmployeeId(uuid.uuid4())
    manager = EmployeeId(uuid.uuid4())
    request = EmployeeTransferRequest(
        request_id=new_transfer_request_id(),
        tenant_id=TENANT,
        employee_id=worker,
        from_store_id=STORE_A,
        to_store_id=STORE_B,
        reason="Ailə səbəbi",
        requested_by=worker,
        created_at=NOW,
    )
    request.reject(approver_id=manager, decided_at=NOW, reason="Filial dolğunluğu")

    assert request.is_withdrawn is False


def test_withdraw_bypasses_the_self_decision_ban_by_design() -> None:
    """`withdraw()` `_decide()`-i ÇAĞIRMIR — vəzifə-ayrılığı qadağası bura AİD DEYİL."""
    worker = EmployeeId(uuid.uuid4())
    request = EmployeeTransferRequest(
        request_id=new_transfer_request_id(),
        tenant_id=TENANT,
        employee_id=worker,
        from_store_id=STORE_A,
        to_store_id=STORE_B,
        reason="Ailə səbəbi",
        requested_by=worker,
        created_at=NOW,
    )
    # Öz sorğusunu `approve()`/`reject()` ilə qərarlandırmaq QADAĞANDIR
    # (yuxarıdakı test), lakin `withdraw()` HEÇ BİR belə yoxlama aparmır.
    request.withdraw(withdrawn_at=NOW)
    assert request.status is TransferStatus.REJECTED


# --------------------------------------------------------------------------- #
# `TransferRequestUseCase.submit`
# --------------------------------------------------------------------------- #


def test_an_employee_without_a_current_store_cannot_submit(ctx: Ctx) -> None:
    worker = _employee(store_id=None)
    with pytest.raises(TransferRequestError, match="Cari filialı olmayan"):
        ctx.use_case().submit(
            tenant_id=TENANT, employee=worker, to_store_id=STORE_B, reason="Ailə səbəbi"
        )


def test_a_second_open_request_is_refused(ctx: Ctx) -> None:
    worker = _employee()
    use_case = ctx.use_case()
    use_case.submit(tenant_id=TENANT, employee=worker, to_store_id=STORE_B, reason="Ailə səbəbi")

    with pytest.raises(TransferRequestError, match="artıq gözləyən"):
        use_case.submit(tenant_id=TENANT, employee=worker, to_store_id=STORE_B, reason="Yenə eyni")


def test_a_successful_submission_is_audited_and_notified(ctx: Ctx) -> None:
    worker = _employee()
    ctx.use_case().submit(
        tenant_id=TENANT, employee=worker, to_store_id=STORE_B, reason="Ailə səbəbi"
    )

    assert ctx.audit.actions() == ["TRANSFER_REQUESTED"]
    assert ctx.notifier.sent[0]["category"] == "TRANSFER_REQUEST_PENDING"


# --------------------------------------------------------------------------- #
# Səlahiyyət — açıq istisna, sükutla "heç nə etmə" YOX (CLAUDE.md §6)
# --------------------------------------------------------------------------- #


def test_approve_requires_the_flag(ctx: Ctx) -> None:
    worker = _employee()
    request = ctx.use_case().submit(
        tenant_id=TENANT, employee=worker, to_store_id=STORE_B, reason="Ailə səbəbi"
    )
    outsider = _employee(flags=())

    with pytest.raises(TransferPermissionError, match=APPROVE_TRANSFER_FLAG):
        ctx.use_case().approve(tenant_id=TENANT, approver=outsider, request_id=request.id)


def test_reject_requires_the_flag(ctx: Ctx) -> None:
    worker = _employee()
    request = ctx.use_case().submit(
        tenant_id=TENANT, employee=worker, to_store_id=STORE_B, reason="Ailə səbəbi"
    )
    outsider = _employee(flags=())

    with pytest.raises(TransferPermissionError, match=APPROVE_TRANSFER_FLAG):
        ctx.use_case().reject(
            tenant_id=TENANT, approver=outsider, request_id=request.id, reason="Kifayət qədər uzun"
        )


def test_the_pending_inbox_requires_the_flag_too(ctx: Ctx) -> None:
    outsider = _employee(flags=())
    with pytest.raises(TransferPermissionError, match=APPROVE_TRANSFER_FLAG):
        ctx.use_case().pending_inbox(tenant_id=TENANT, actor=outsider)


def test_a_request_id_that_does_not_exist_raises_not_found(ctx: Ctx) -> None:
    approver = _employee(flags=(APPROVE_TRANSFER_FLAG,))
    with pytest.raises(TransferNotFoundError):
        ctx.use_case().approve(
            tenant_id=TENANT, approver=approver, request_id=new_transfer_request_id()
        )


# --------------------------------------------------------------------------- #
# `withdraw()` — YALNIZ sorğunu göndərən özü
# --------------------------------------------------------------------------- #


def test_withdraw_requires_no_special_flag_but_only_the_requester_may_call_it(ctx: Ctx) -> None:
    """Səlahiyyət sərhədi: `can_approve_transfer_request` YOX, "sən özünsənmi" sualı."""
    worker = _employee()
    stranger = _employee()
    request = ctx.use_case().submit(
        tenant_id=TENANT, employee=worker, to_store_id=STORE_B, reason="Ailə səbəbi"
    )

    with pytest.raises(TransferPermissionError, match="Yalnız sorğunu göndərən"):
        ctx.use_case().withdraw(tenant_id=TENANT, employee=stranger, request_id=request.id)

    # Sorğu TOXUNULMAMIŞ qalır — yad işçinin cəhdi sükutla keçmir, LAKİN
    # sorğunun ÖZÜNÜ də dəyişdirmir.
    assert ctx.transfers.get(request.id).status is TransferStatus.PENDING_APPROVAL  # type: ignore[union-attr]


def test_the_requester_can_withdraw_their_own_request(ctx: Ctx) -> None:
    worker = _employee()
    request = ctx.use_case().submit(
        tenant_id=TENANT, employee=worker, to_store_id=STORE_B, reason="Ailə səbəbi"
    )

    withdrawn = ctx.use_case().withdraw(tenant_id=TENANT, employee=worker, request_id=request.id)

    assert withdrawn.is_withdrawn is True
    assert "TRANSFER_WITHDRAWN" in ctx.audit.actions()


# --------------------------------------------------------------------------- #
# `approve()` — dərhal / planlaşdırılmış
# --------------------------------------------------------------------------- #


def test_approval_without_an_effective_date_moves_the_employee_immediately(ctx: Ctx) -> None:
    worker = _employee()
    ctx.employees.items[worker.id] = worker
    approver = _employee(flags=(APPROVE_TRANSFER_FLAG,))
    request = ctx.use_case().submit(
        tenant_id=TENANT, employee=worker, to_store_id=STORE_B, reason="Ailə səbəbi"
    )

    ctx.use_case().approve(tenant_id=TENANT, approver=approver, request_id=request.id)

    assert ctx.employees.get(worker.id).store_id == STORE_B  # type: ignore[union-attr]


def test_approval_with_a_future_effective_date_does_not_move_the_employee_yet(ctx: Ctx) -> None:
    worker = _employee()
    ctx.employees.items[worker.id] = worker
    approver = _employee(flags=(APPROVE_TRANSFER_FLAG,))
    request = ctx.use_case().submit(
        tenant_id=TENANT,
        employee=worker,
        to_store_id=STORE_B,
        reason="Ailə səbəbi",
        effective_date=date(2026, 9, 1),
    )

    ctx.use_case().approve(tenant_id=TENANT, approver=approver, request_id=request.id)

    assert ctx.employees.get(worker.id).store_id == STORE_A  # type: ignore[union-attr]
    assert ctx.transfers.get(request.id).status is TransferStatus.APPROVED  # type: ignore[union-attr]


# --------------------------------------------------------------------------- #
# `apply_scheduled_transfers` — planlaşdırılmış iş, idempotent
# --------------------------------------------------------------------------- #


def test_apply_scheduled_transfers_moves_only_due_and_unapplied_requests(ctx: Ctx) -> None:
    worker = _employee()
    ctx.employees.items[worker.id] = worker
    approver = _employee(flags=(APPROVE_TRANSFER_FLAG,))
    request = ctx.use_case().submit(
        tenant_id=TENANT,
        employee=worker,
        to_store_id=STORE_B,
        reason="Ailə səbəbi",
        effective_date=date(2026, 8, 20),
    )
    ctx.use_case().approve(tenant_id=TENANT, approver=approver, request_id=request.id)

    applied = ctx.use_case().apply_scheduled_transfers(TENANT)

    assert applied == 1
    assert ctx.employees.get(worker.id).store_id == STORE_B  # type: ignore[union-attr]
    assert "TRANSFERS_AUTO_APPLIED" in ctx.audit.actions()


def test_apply_scheduled_transfers_is_idempotent_via_the_store_id_guard(ctx: Ctx) -> None:
    """İKİNCİ QAT — `list_due_for_effect` artıq süzür, `_apply_store_change` TƏKRAR yoxlayır."""
    worker = _employee()
    ctx.employees.items[worker.id] = worker
    approver = _employee(flags=(APPROVE_TRANSFER_FLAG,))
    request = ctx.use_case().submit(
        tenant_id=TENANT,
        employee=worker,
        to_store_id=STORE_B,
        reason="Ailə səbəbi",
        effective_date=date(2026, 8, 20),
    )
    ctx.use_case().approve(tenant_id=TENANT, approver=approver, request_id=request.id)
    ctx.use_case().apply_scheduled_transfers(TENANT)
    ctx.audit.records.clear()

    # İkinci çağırış: `list_due_for_effect` sahtəsi HƏLƏ `request`-i qaytarır
    # (o, `employees.store_id`-i yoxlamır — real repo YOXLAYARDI), lakin
    # `_apply_store_change`-in ÖZÜ (`employee.store_id == request.to_store_id`)
    # onu SÜKUTLA rədd edir — bu, use case-in İKİNCİ QAT qoruması.
    applied_again = ctx.use_case().apply_scheduled_transfers(TENANT)

    assert applied_again == 0
    assert ctx.audit.actions() == []
