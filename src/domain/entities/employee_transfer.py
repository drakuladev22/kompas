"""Filiallar-arası daimi köçürmə sorğusu (`v2backlog.md` Faza 3.3).

──────────────────────────────────────────────────────────────────────────────
`ShiftSwapRequest` İLƏ QARIŞDIRILMAMALIDIR
──────────────────────────────────────────────────────────────────────────────
`ShiftSwapRequest` (`entities/shift.py`) BİR GÜNLÜK rejim dəyişikliyidir —
Store Manager yalnız TÖVSİYƏ yazır, təsdiq etmir. Bu isə `employees.store_id`-
nin DAİMİ dəyişikliyidir, `can_approve_transfer_request` sahibi (HR_Admin)
TƏSDİQ EDİR. Struktur (status enum-u, `decided_*` üçlüyü) ŞÜURLU şəkildə
`ShiftSwapRequest`-dən TƏKRARLANIR, aqreqat özü YOX — səbəb `migrations/088`
başlığındadır: "günlük rejim" sütunları transfer sorğusunda mənasız qalardı
və əksinə.

──────────────────────────────────────────────────────────────────────────────
GERİ ÇƏKMƏ (`withdraw`) NİYƏ AYRICA METODDUR, `reject()`-in TƏKRARI DEYİL
──────────────────────────────────────────────────────────────────────────────
`can_approve_transfer_request` `DEADLOCK_CRITICAL_FLAGS`-dədir (bölmə 3): əgər
sonuncu daşıyıcısı itirilsə, `PENDING_APPROVAL` sorğu HEÇ VAXT son hala
çatmayacaq — `ShiftSwapRequest`-in `can_approve_shift_swap` üçün TAPILAN eyni
struktur boşluğu (bax komanda rəhbərinə göndərilən audit). `_decide()` özü
"öz sorğusunu özü təsdiqləyə bilməz" qadağası daşıyır (vəzifə ayrılığı) və bu
qadağa DÜZGÜNDÜR — LAKİN "geri çəkmək" bir QƏRAR VERMƏK deyil, öz sorğusunu
LƏĞV ETMƏKDİR: işçi kiməsə TƏSDİQ/RƏDD "vermir", sadəcə tələbindən əl çəkir.
Ona görə `withdraw()` `_decide()`-i ÇAĞIRMIR — status DB `employee_transfer_
status` enum-unda (`PENDING_APPROVAL`/`APPROVED`/`REJECTED`, migrations/088)
AYRICA "WITHDRAWN" dəyəri YOXDUR (schema-migration-engineer bunu Faza 1-də
konsolidasiya edib, buraya yeni miqrasiya əlavə etmək bu sahənin işi deyil) —
sorğu `REJECTED`-ə keçir, LAKİN `decided_by == requested_by` şərti onu
menecerin rəddindən AYIRD EDİR (`is_withdrawn` property). Bu, `chk_transfer_
decision` DB məhdudiyyətini (qərar veriləndə `decided_by` MƏCBURİDİR)
sxem dəyişikliyi TƏLƏB ETMƏDƏN ödəyir.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Final

from src.domain.entities.base import AggregateRoot, DomainRuleError
from src.domain.events import TransferDecidedEvent, TransferRequestedEvent
from src.domain.value_objects.identifiers import (
    EmployeeId,
    StoreId,
    TenantId,
    TransferRequestId,
)
from src.domain.value_objects.scheduling import require_aware
from src.shared.text import normalise_decision_text

#: `employee_transfer_requests.reason` — DB `CHECK (char_length(trim(reason)) >= 5)`.
MIN_TRANSFER_REASON_LENGTH: Final[int] = 5
#: Rədd/geri çəkmə izahı — `ShiftSwapRequest` ilə eyni standart.
MIN_TRANSFER_DECISION_REASON_LENGTH: Final[int] = 10


class TransferStatus(str, Enum):
    """`employee_transfer_requests.status` — DB `employee_transfer_status` enum-u ilə EYNİ."""

    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

    @property
    def is_decided(self) -> bool:
        return self is not TransferStatus.PENDING_APPROVAL


class EmployeeTransferRequest(AggregateRoot):
    """Filiallar-arası daimi köçürmə sorğusu.

        PENDING_APPROVAL ──approve()───> APPROVED   (employees.store_id yenilənir)
                 │
                 ├────reject(səbəb)────> REJECTED    (decided_by = TƏSDİQÇİ)
                 │
                 └────withdraw(səbəb)──> REJECTED    (decided_by = SORĞUÇU özü)

    Hər üç keçid TERMİNALDIR: qərar/geri çəkmə bir dəfə verilir, işçi lazım
    gələrsə YENİ sorğu göndərir (`ShiftSwapRequest` ilə eyni fəlsəfə).
    """

    def __init__(
        self,
        *,
        request_id: TransferRequestId,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        from_store_id: StoreId,
        to_store_id: StoreId,
        reason: str,
        requested_by: EmployeeId,
        created_at: datetime,
        effective_date: date | None = None,
        status: TransferStatus = TransferStatus.PENDING_APPROVAL,
        decided_by: EmployeeId | None = None,
        decision_reason: str | None = None,
        decided_at: datetime | None = None,
        emit_created_event: bool = True,
    ) -> None:
        super().__init__()
        if from_store_id == to_store_id:
            raise DomainRuleError(
                "Köçürmə sorğusunda mənbə və hədəf mağaza eyni ola bilməz",
                user_message="Yeni filial hazırkı filialdan fərqli olmalıdır.",
                context={"store_id": str(from_store_id)},
            )
        cleaned_reason = normalise_decision_text(reason)
        if len(cleaned_reason) < MIN_TRANSFER_REASON_LENGTH:
            raise DomainRuleError(
                f"Sorğu səbəbi minimum {MIN_TRANSFER_REASON_LENGTH} simvol olmalıdır",
                user_message="Səbəbi bir az ətraflı yazın.",
                context={"length": len(cleaned_reason)},
            )

        self.id = request_id
        self.tenant_id = tenant_id
        self.employee_id = employee_id
        self.from_store_id = from_store_id
        self.to_store_id = to_store_id
        self.reason = cleaned_reason
        self.requested_by = requested_by
        self.effective_date = effective_date
        self.status = status
        self.decided_by = decided_by
        self.decision_reason = decision_reason
        self.decided_at = decided_at
        self.created_at = require_aware(created_at, field="created_at")

        # Repository-dən bərpa edilən obyekt hadisə YAYMAMALIDIR (`ShiftSwapRequest`
        # ilə eyni qayda) — əks halda hər oxunuş "yeni sorğu göndərildi" bildirişi
        # göndərərdi.
        if emit_created_event and status is TransferStatus.PENDING_APPROVAL:
            self.record_event(
                TransferRequestedEvent(
                    tenant_id=tenant_id,
                    request_id=request_id,
                    employee_id=employee_id,
                    from_store_id=from_store_id,
                    to_store_id=to_store_id,
                    reason=cleaned_reason,
                )
            )

    @property
    def is_withdrawn(self) -> bool:
        """`REJECTED`, LAKİN qərarı VERƏN sorğunu GÖNDƏRƏNİN ÖZÜDÜR.

        DB sxemində ayrıca `WITHDRAWN` statusu yoxdur (modul başlığı) — bu
        property həmin fərqi kodda görünən edir: ekran "HR rədd etdi" ilə
        "işçi geri çəkdi" mesajlarını bununla ayırd edir.
        """
        return self.status is TransferStatus.REJECTED and self.decided_by == self.requested_by

    # ------------------------------- qərar ----------------------------------- #

    def approve(self, *, approver_id: EmployeeId, decided_at: datetime) -> None:
        """`[Təsdiqlə]` — çağıran tərəf ardınca `employees.store_id`-ni yeniləyir."""
        self._decide(approved=True, approver_id=approver_id, decided_at=decided_at, reason=None)

    def reject(self, *, approver_id: EmployeeId, decided_at: datetime, reason: str) -> None:
        """`[Rədd Et]` — səbəb MƏCBURİDİR (işçiyə bildirişdə göstərilir)."""
        cleaned = normalise_decision_text(reason)
        if len(cleaned) < MIN_TRANSFER_DECISION_REASON_LENGTH:
            raise DomainRuleError(
                f"Rədd səbəbi minimum {MIN_TRANSFER_DECISION_REASON_LENGTH} simvol olmalıdır",
                user_message="Rədd səbəbini ətraflı yazın.",
                context={"length": len(cleaned)},
            )
        self._decide(approved=False, approver_id=approver_id, decided_at=decided_at, reason=cleaned)

    def _decide(
        self,
        *,
        approved: bool,
        approver_id: EmployeeId,
        decided_at: datetime,
        reason: str | None,
    ) -> None:
        self._require_pending("Bu sorğu artıq qərar alıb")
        if approver_id == self.employee_id:
            # Öz sorğusunu özü təsdiqləmək vəzifə ayrılığını pozar
            # (`ShiftSwapRequest._decide` ilə eyni qayda).
            raise DomainRuleError(
                "İşçi öz köçürmə sorğusunu özü təsdiqləyə/rədd edə bilməz",
                user_message="Öz sorğunuza qərar verə bilməzsiniz.",
                context={"employee_id": str(self.employee_id)},
            )

        self.status = TransferStatus.APPROVED if approved else TransferStatus.REJECTED
        self.decided_by = approver_id
        self.decided_at = require_aware(decided_at, field="decided_at")
        self.decision_reason = reason
        self.record_event(
            TransferDecidedEvent(
                tenant_id=self.tenant_id,
                request_id=self.id,
                approver_id=approver_id,
                approved=approved,
                reason=reason,
            )
        )

    # ------------------------------ geri çəkmə -------------------------------- #

    def withdraw(self, *, withdrawn_at: datetime, reason: str | None = None) -> None:
        """İşçi öz sorğusunu, təsdiq gözlədiyi müddətdə, ÖZÜ ləğv edir.

        `security` sahəsinin `can_approve_transfer_request`-i `DEADLOCK_
        CRITICAL_FLAGS`-ə saldığı üçün bu, sadəcə rahatlıq DEYİL — sonuncu
        təsdiqçi itəndə belə sorğu ƏBƏDİ açıq QALMIR (modul başlığı).
        `_decide()`-in vəzifə-ayrılığı qadağasından İSTİSNADIR: bura "kiməsə
        qərar vermək" deyil, "öz tələbindən əl çəkmək"dir.
        """
        self._require_pending("Bu sorğu artıq qərar alıb — geri çəkilə bilməz")
        self.status = TransferStatus.REJECTED
        self.decided_by = self.requested_by
        self.decided_at = require_aware(withdrawn_at, field="withdrawn_at")
        self.decision_reason = (
            normalise_decision_text(reason) if reason else "İşçi sorğunu geri çəkdi"
        )
        self.record_event(
            TransferDecidedEvent(
                tenant_id=self.tenant_id,
                request_id=self.id,
                approver_id=self.requested_by,
                approved=False,
                reason=self.decision_reason,
            )
        )

    def _require_pending(self, message: str) -> None:
        if self.status.is_decided:
            raise DomainRuleError(
                message,
                user_message="Bu sorğu artıq emal edilib.",
                context={"status": self.status.value},
            )

    def __repr__(self) -> str:
        return (
            f"EmployeeTransferRequest(id={self.id}, employee={self.employee_id}, "
            f"{self.from_store_id}->{self.to_store_id}, status={self.status.value})"
        )


__all__ = [
    "MIN_TRANSFER_DECISION_REASON_LENGTH",
    "MIN_TRANSFER_REASON_LENGTH",
    "EmployeeTransferRequest",
    "TransferStatus",
]
