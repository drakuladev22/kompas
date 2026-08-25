"""Filiallar-arası daimi köçürmə sorğusu (`v2backlog.md` Faza 3.3).

──────────────────────────────────────────────────────────────────────────────
NİYƏ `ShiftSwapUseCase`-in TAM NÜSXƏSİDİR, LAKİN AYRI FAYLDADIR
──────────────────────────────────────────────────────────────────────────────
`shift_scheduling.py`-a əlavə etmək YANLIŞ olardı: o fayl `Shift Matrix`
(gündəlik/həftəlik rejim planlaması) domenidir, bu isə HR-ın STRUKTUR
qərarıdır (`employees.store_id`-nin DAİMİ dəyişikliyi). `entities/employee_
transfer.py` başlığındakı əsaslandırma: struktur şüurlu təkrarlanır, MODUL
YOX — ikisini bir faylda saxlamaq iki fərqli domeni qarışdırardı.

──────────────────────────────────────────────────────────────────────────────
`effective_date` NİYƏ İKİ FƏRQLİ YAZI ANI YARADIR
──────────────────────────────────────────────────────────────────────────────
`effective_date IS NULL` → `approve()` `employees.store_id`-ni DƏRHAL yeniləyir
(HR sorğunu təsdiqlədiyi an işçi artıq yeni filialdadır). `effective_date`
DOLUDURSA → təsdiq sorğunun statusunu dəyişir, LAKİN `store_id`-yə TOXUNMUR;
faktiki köçürmə `apply_scheduled_transfers()` (mövcud `job_runner.py`
cron-naxışı) həmin tarix çatanda edir — `UserManagementUseCase.
deactivate_scheduled_employees` ilə EYNİ naxış (Faza 3.1).

İKİNCİ BİR "TƏTBİQ OLUNDU" SÜTUNU YOXDUR (migrations/088 bunu əlavə etmir) —
idempotentlik `employees.store_id <> to_store_id` şərti ilə təmin olunur:
köçürmə TƏTBİQ OLUNDUQDAN sonra bu şərt artıq doğru deyil, ona görə cron onu
BİR DƏFƏ görür. `EmployeeTransferRequestRepository.list_due_for_effect`
kontraktı bunu TƏLƏB EDİR (bax portun docstring-i).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.domain.entities.employee_transfer import EmployeeTransferRequest
from src.domain.value_objects.identifiers import new_transfer_request_id
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import date

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        Clock,
        EmployeeRepository,
        EmployeeTransferRequestRepository,
        Notifier,
        SystemLimits,
    )
    from src.domain.value_objects.identifiers import (
        StoreId,
        TenantId,
        TransferRequestId,
    )

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

APPROVE_TRANSFER_FLAG = "can_approve_transfer_request"


class TransferRequestError(KompasOSError):
    """Köçürmə sorğusu əməliyyatı yerinə yetirilə bilmədi."""

    user_message = "Köçürmə sorğusu ilə bağlı əməliyyat icra edilə bilmədi."


class TransferPermissionError(TransferRequestError):
    user_message = "Bu əməliyyat üçün səlahiyyətiniz yoxdur."


class TransferNotFoundError(TransferRequestError):
    user_message = "Bu köçürmə sorğusu tapılmadı."


class TransferRequestUseCase:
    """İşçi-tərəfi sorğu + HR_Admin təsdiqi — `ShiftSwapUseCase` ilə EYNİ forma."""

    def __init__(
        self,
        *,
        transfers: EmployeeTransferRequestRepository,
        employees: EmployeeRepository,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier,
        limits: SystemLimits | None = None,
    ) -> None:
        self._transfers = transfers
        self._employees = employees
        self._audit = audit
        self._clock = clock
        self._notifier = notifier
        self._limits = limits

    # ------------------------------- göndər ---------------------------------- #

    def submit(
        self,
        *,
        tenant_id: TenantId,
        employee: Employee,
        to_store_id: StoreId,
        reason: str,
        effective_date: date | None = None,
    ) -> EmployeeTransferRequest:
        """İşçi Ana Ekranından `[Köçürmə Sorğusu]`."""
        if employee.store_id is None:
            raise TransferRequestError(
                "Cari filialı olmayan işçi köçürmə sorğusu göndərə bilməz",
                user_message="Sorğu üçün mövcud filialınız qeydə alınmalıdır.",
                context={"employee_id": str(employee.id)},
            )
        if self._transfers.find_open_for_employee(employee.id) is not None:
            raise TransferRequestError(
                "İşçinin artıq gözləyən köçürmə sorğusu var",
                user_message="Sizin artıq təsdiq gözləyən köçürmə sorğunuz var.",
                context={"employee_id": str(employee.id)},
            )

        request = EmployeeTransferRequest(
            request_id=new_transfer_request_id(),
            tenant_id=tenant_id,
            employee_id=employee.id,
            from_store_id=employee.store_id,
            to_store_id=to_store_id,
            reason=reason,
            requested_by=employee.id,
            created_at=self._clock.now(),
            effective_date=effective_date,
        )
        self._transfers.save(request)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=employee.id,
            action="TRANSFER_REQUESTED",
            entity_type="employee_transfer_requests",
            entity_id=request.id,
            after_state={
                "from_store_id": str(request.from_store_id),
                "to_store_id": str(request.to_store_id),
                "status": request.status.value,
            },
            reason=request.reason,
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=None,  # `can_approve_transfer_request` sahibləri
            category="TRANSFER_REQUEST_PENDING",
            title_az="Yeni filial köçürmə sorğusu",
            body_az=(
                f"{employee.full_name} filiallar-arası köçürmə istəyir. Səbəb: {request.reason}"
            ),
            is_critical=False,
        )
        return request

    # ------------------------------- inbox ----------------------------------- #

    def pending_inbox(
        self, *, tenant_id: TenantId, actor: Employee, to_store_id: StoreId | None = None
    ) -> list[EmployeeTransferRequest]:
        """`can_approve_transfer_request` sahibinin təsdiq növbəsi."""
        self._require_approver(actor)
        return self._transfers.list_pending(tenant_id, to_store_id=to_store_id)

    def my_requests(self, employee: Employee) -> list[EmployeeTransferRequest]:
        """İşçinin öz sorğu tarixçəsi — səlahiyyət tələb olunmur."""
        page_size = self._history_page_size(employee.tenant_id)
        return self._transfers.list_for_employee(employee.id, limit=page_size)

    # -------------------------------- qərar ---------------------------------- #

    def approve(
        self, *, tenant_id: TenantId, approver: Employee, request_id: TransferRequestId
    ) -> EmployeeTransferRequest:
        """`[Təsdiqlə]` — `effective_date IS NULL`-dursa `employees.store_id` DƏRHAL yenilənir."""
        self._require_approver(approver)
        request = self._require_request(request_id)
        now = self._clock.now()

        request.approve(approver_id=approver.id, decided_at=now)
        self._transfers.save(request)

        applied_immediately = False
        if request.effective_date is None:
            applied_immediately = self._apply_store_change(request)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=approver.id,
            action="TRANSFER_APPROVED",
            entity_type="employee_transfer_requests",
            entity_id=request.id,
            after_state={
                "status": request.status.value,
                "to_store_id": str(request.to_store_id),
                "effective_date": (
                    request.effective_date.isoformat() if request.effective_date else None
                ),
                "applied_immediately": applied_immediately,
            },
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=request.employee_id,
            category="TRANSFER_DECIDED",
            title_az="Köçürmə sorğunuz təsdiqləndi",
            body_az=(
                "Köçürmə sorğunuz təsdiqləndi."
                if applied_immediately or request.effective_date is None
                else f"Köçürmə sorğunuz təsdiqləndi — {request.effective_date.isoformat()} "
                f"tarixindən etibarlı olacaq."
            ),
            is_critical=False,
        )
        return request

    def reject(
        self, *, tenant_id: TenantId, approver: Employee, request_id: TransferRequestId, reason: str
    ) -> EmployeeTransferRequest:
        """`[Rədd Et]` — səbəb MƏCBURİDİR (işçiyə bildirişdə göstərilir)."""
        self._require_approver(approver)
        request = self._require_request(request_id)

        request.reject(approver_id=approver.id, decided_at=self._clock.now(), reason=reason)
        self._transfers.save(request)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=approver.id,
            action="TRANSFER_REJECTED",
            entity_type="employee_transfer_requests",
            entity_id=request.id,
            after_state={"status": request.status.value},
            reason=request.decision_reason,
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=request.employee_id,
            category="TRANSFER_DECIDED",
            title_az="Köçürmə sorğunuz rədd edildi",
            body_az=f"Səbəb: {request.decision_reason}",
            is_critical=True,
        )
        return request

    def withdraw(
        self, *, tenant_id: TenantId, employee: Employee, request_id: TransferRequestId
    ) -> EmployeeTransferRequest:
        """`[Sorğunu Geri Çək]` — `can_approve_transfer_request` DEADLOCK-CRITICAL-dır.

        `security` sahəsi bu flag-i `DEADLOCK_CRITICAL_FLAGS`-ə saldı, çünki
        sonuncu təsdiqçi itəndə sorğu ƏBƏDİ `PENDING_APPROVAL`-da qalardı
        (`ShiftSwapRequest`-in tapılmış eyni boşluğu). Bu metod işçiyə ÖZ
        sorğusundan çıxış yolu verir — `EmployeeTransferRequest.withdraw()`
        vəzifə-ayrılığı qadağasından İSTİSNADIR (modul başlığı: qərar vermək
        deyil, tələbdən əl çəkməkdir).
        """
        request = self._require_request(request_id)
        if request.employee_id != employee.id:
            raise TransferPermissionError(
                "Yalnız sorğunu göndərən işçi onu geri çəkə bilər",
                context={"employee_id": str(employee.id), "request_id": str(request_id)},
            )
        request.withdraw(withdrawn_at=self._clock.now())
        self._transfers.save(request)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=employee.id,
            action="TRANSFER_WITHDRAWN",
            entity_type="employee_transfer_requests",
            entity_id=request.id,
            after_state={"status": request.status.value},
            reason=request.decision_reason,
        )
        return request

    # ------------------------------ planlanmış -------------------------------- #

    def apply_scheduled_transfers(self, tenant_id: TenantId) -> int:
        """`effective_date` çatmış TƏSDİQLƏNMİŞ köçürmələri icra edir (Faza 3.3).

        PLANLAŞDIRILMIŞ İŞDİR (bax `UserManagementUseCase.
        deactivate_scheduled_employees` ilə EYNİ forma) — actor YOXDUR.

        Returns:
            İcra edilən köçürmə sayı.
        """
        today = self._clock.now().date()
        due = self._transfers.list_due_for_effect(tenant_id, as_of=today)
        applied = 0
        for request in due:
            if self._apply_store_change(request):
                applied += 1
        if applied:
            self._audit.record(
                tenant_id=tenant_id,
                actor_id=None,
                action="TRANSFERS_AUTO_APPLIED",
                entity_type="employees",
                after_state={"applied_count": applied},
                reason="Planlaşdırılmış köçürmə tarixi çatdı",
            )
        return applied

    # ------------------------------- köməkçi --------------------------------- #

    def _apply_store_change(self, request: EmployeeTransferRequest) -> bool:
        """`employees.store_id`-ni yeniləyir. İDEMPOTENT: artıq keçilibsə `False`.

        `list_due_for_effect` kontraktı ARTIQ `store_id <> to_store_id`
        şərtini tətbiq edir (portun docstring-i), LAKİN bu, İKİNCİ QATDIR —
        `approve()`-dan DƏRHAL çağırıldıqda repository süzgəci işə düşmür.
        """
        employee = self._employees.get(request.employee_id)
        if employee is None or employee.store_id == request.to_store_id:
            return False
        employee.store_id = request.to_store_id
        self._employees.save(employee)
        return True

    def _history_page_size(self, tenant_id: TenantId) -> int:
        from src.application.root_limits import limit_int  # noqa: PLC0415
        from src.domain.policies import SystemLimitKey  # noqa: PLC0415

        return limit_int(self._limits, tenant_id, SystemLimitKey.SHIFT_SWAP_HISTORY_PAGE_SIZE)

    def _require_request(self, request_id: TransferRequestId) -> EmployeeTransferRequest:
        request = self._transfers.get(request_id)
        if request is None:
            raise TransferNotFoundError(
                "Köçürmə sorğusu tapılmadı", context={"request_id": str(request_id)}
            )
        return request

    def _require_approver(self, actor: Employee) -> None:
        if not actor.has_permission(APPROVE_TRANSFER_FLAG, now=self._clock.now()):
            _audit_log.warning(
                "TRANSFER_PERMISSION_DENIED",
                extra={"actor_id": str(actor.id), "flag": APPROVE_TRANSFER_FLAG},
            )
            raise TransferPermissionError(
                f"«{APPROVE_TRANSFER_FLAG}» səlahiyyəti yoxdur",
                context={"actor_id": str(actor.id)},
            )


__all__ = [
    "APPROVE_TRANSFER_FLAG",
    "TransferNotFoundError",
    "TransferPermissionError",
    "TransferRequestError",
    "TransferRequestUseCase",
]
