"""Növbə aqreqatları — Shift Matrix və Shift Swap (spesifikasiya bölmə 3).

──────────────────────────────────────────────────────────────────────────────
İKİ AYRI MEXANİZM, BİR CƏDVƏL
──────────────────────────────────────────────────────────────────────────────
Bölmə 3 növbənin İKİ yolla dəyişdiyini deyir:

    1. **ADMIN-BİRBAŞA-REDAKTƏ** — `can_manage_shifts` sahibi (Root/CEO/
       HR_Admin/Admin) Interactive Shift Matrix-dən günü dəyişir.
    2. **İŞÇİ-TƏRƏFİ SELF-SERVICE** — işçi sorğu göndərir, `can_approve_shift_swap`
       sahibi təsdiqləyir; təsdiqdə eyni yeniləmə funksiyası çağırılır.

Hər ikisi EYNİ `shift_assignments` sətrinə yazır, lakin `source` sütunu ilə
fərqlənir (`ADMIN_MATRIX` / `SHIFT_SWAP`). Bölmə 3 açıq deyir: "eyni yeniləmə
funksiyasından istifadə edərək — məntiq təkrarlanmır". Ona görə `ShiftAssignment`
BİRDİR və sorğu onu YARATMIR, yalnız təsdiqdən sonra ona çevrilir.

──────────────────────────────────────────────────────────────────────────────
SORĞU TƏQVİMƏ TOXUNMUR — NİYƏ ENTITY BUNU QORUYUR
──────────────────────────────────────────────────────────────────────────────
Bölmə 3: "Sorğu dərhal `PENDING_APPROVAL` statusuna keçir. **Təqvimdə HEÇ BİR
dəyişiklik baş vermir** və işçi öz standart növbəsinə çıxmağa məcburdur."

`ShiftSwapRequest` ona görə `ShiftAssignment`-dən TAMAMİLƏ ayrı aqreqatdır:
əgər sorğu birbaşa təyinatı dəyişdirsəydi, işçi "sorğu göndərdim, deməli
sabah gəlmirəm" nəticəsinə gələ bilərdi — real mağazada bu, işçisiz açılmış
növbə deməkdir.

──────────────────────────────────────────────────────────────────────────────
STORE MANAGER NİYƏ TƏSDİQ ETMİR
──────────────────────────────────────────────────────────────────────────────
Bölmə 3 (düzəliş): Store Manager sorğunu TƏSDİQ ETMİR, yalnız `manager_note`
ilə HR-a tövsiyə yazır. Entity bunu struktur olaraq ayırır: `attach_manager_note()`
statusu DƏYİŞMİR, yalnız `decide()` dəyişir. Beləliklə "menecer təsdiqlədi"
vəziyyəti heç vaxt yarana bilmir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Final

from src.domain.entities.base import AggregateRoot, DomainRuleError
from src.domain.events import ShiftSwapDecidedEvent, ShiftSwapRequestedEvent
from src.domain.value_objects.identifiers import (
    EmployeeId,
    ShiftAssignmentId,
    ShiftSwapRequestId,
    StoreId,
    TenantId,
    WorkModeId,
)
from src.domain.value_objects.scheduling import require_aware
from src.shared.text import normalise_decision_text

#: `shift_swap_requests.reason` — DB `CHECK (char_length(trim(reason)) >= 5)`.
MIN_SWAP_REASON_LENGTH: Final[int] = 5
#: Rədd/təsdiq qərarının izahı — cərimə ləğvi ilə eyni minimum.
MIN_DECISION_REASON_LENGTH: Final[int] = 10


class ShiftSource(str, Enum):
    """`shift_assignments.source` — dəyişikliyin MƏNBƏYİ.

    Auditdə "bu günü kim dəyişdi?" sualının cavabı `assigned_by`-dır, "NİYƏ
    dəyişdi?" sualının cavabı isə budur: admin planlaması, yoxsa işçinin
    təsdiqlənmiş sorğusu.
    """

    ADMIN_MATRIX = "ADMIN_MATRIX"
    SHIFT_SWAP = "SHIFT_SWAP"


class SwapStatus(str, Enum):
    """`shift_swap_requests.status` — DB `shift_swap_status` enum-u ilə EYNİ."""

    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

    @property
    def is_decided(self) -> bool:
        return self is not SwapStatus.PENDING_APPROVAL


@dataclass(frozen=True)
class ShiftAssignment:
    """Bir işçinin bir günü (`shift_assignments` sətri).

    `frozen=True`: təqvim hüceyrəsi dəyişdirilmir, YENİSİ yazılır. Bu, "köhnə
    və yeni dəyər" cütünü audit üçün əldə saxlamağı asanlaşdırır — dəyişən
    obyektdə köhnə dəyər artıq itmiş olardı.

    DB `chk_shift_mode` məhdudiyyəti burada təkrarlanır (defense-in-depth):
    istirahət günündə iş rejimi ola bilməz, iş günündə isə MƏCBURİDİR.
    """

    assignment_id: ShiftAssignmentId
    tenant_id: TenantId
    employee_id: EmployeeId
    shift_date: date
    is_off_day: bool = False
    work_mode_id: WorkModeId | None = None
    assigned_by: EmployeeId | None = None
    source: ShiftSource = ShiftSource.ADMIN_MATRIX

    def __post_init__(self) -> None:
        if self.is_off_day and self.work_mode_id is not None:
            raise DomainRuleError(
                "İstirahət gününə iş rejimi təyin edilə bilməz",
                user_message="İstirahət günü üçün iş rejimi seçilmir.",
                context={"shift_date": self.shift_date.isoformat()},
            )
        if not self.is_off_day and self.work_mode_id is None:
            raise DomainRuleError(
                "İş günü üçün iş rejimi MƏCBURİDİR — onsuz gecikmə hesablana bilməz",
                user_message="İş günü üçün iş rejimi seçin.",
                context={"shift_date": self.shift_date.isoformat()},
            )

    @property
    def is_working_day(self) -> bool:
        return not self.is_off_day

    def with_mode(
        self,
        work_mode_id: WorkModeId,
        *,
        assigned_by: EmployeeId,
        source: ShiftSource = ShiftSource.ADMIN_MATRIX,
    ) -> ShiftAssignment:
        """İş günü kimi yenidən təyin edir."""
        return ShiftAssignment(
            assignment_id=self.assignment_id,
            tenant_id=self.tenant_id,
            employee_id=self.employee_id,
            shift_date=self.shift_date,
            is_off_day=False,
            work_mode_id=work_mode_id,
            assigned_by=assigned_by,
            source=source,
        )

    def as_off_day(
        self,
        *,
        assigned_by: EmployeeId,
        source: ShiftSource = ShiftSource.ADMIN_MATRIX,
    ) -> ShiftAssignment:
        """İstirahət gününə çevirir (iş rejimi avtomatik silinir)."""
        return ShiftAssignment(
            assignment_id=self.assignment_id,
            tenant_id=self.tenant_id,
            employee_id=self.employee_id,
            shift_date=self.shift_date,
            is_off_day=True,
            work_mode_id=None,
            assigned_by=assigned_by,
            source=source,
        )

    def to_audit_state(self) -> dict[str, object]:
        """Audit `before_state`/`after_state` üçün düz sözlük."""
        return {
            "shift_date": self.shift_date.isoformat(),
            "is_off_day": self.is_off_day,
            "work_mode_id": str(self.work_mode_id) if self.work_mode_id else None,
            "source": self.source.value,
        }


class ShiftSwapRequest(AggregateRoot):
    """İşçinin göndərdiyi növbə dəyişmə sorğusu.

        PENDING_APPROVAL ──approve()──> APPROVED  (Shift Matrix yenilənir)
                 │
                 └────reject(səbəb)──> REJECTED  (işçiyə səbəblə bildiriş)

    Hər iki qərar TERMİNALDIR: bir dəfə verilmiş qərar dəyişdirilmir, işçi
    lazım gələrsə YENİ sorğu göndərir. Əks halda təsdiqlənmiş sorğu sonradan
    rədd edilə bilər və işçi artıq planını qurmuş olardı.
    """

    def __init__(
        self,
        *,
        request_id: ShiftSwapRequestId,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        target_date: date,
        reason: str,
        created_at: datetime,
        requested_mode_id: WorkModeId | None = None,
        store_id: StoreId | None = None,
        status: SwapStatus = SwapStatus.PENDING_APPROVAL,
        manager_note: str | None = None,
        manager_id: EmployeeId | None = None,
        decided_by: EmployeeId | None = None,
        decision_reason: str | None = None,
        decided_at: datetime | None = None,
        emit_created_event: bool = True,
    ) -> None:
        super().__init__()
        cleaned_reason = normalise_decision_text(reason)
        if len(cleaned_reason) < MIN_SWAP_REASON_LENGTH:
            raise DomainRuleError(
                f"Sorğu səbəbi minimum {MIN_SWAP_REASON_LENGTH} simvol olmalıdır",
                user_message="Səbəbi bir az ətraflı yazın.",
                context={"length": len(cleaned_reason)},
            )

        self.id = request_id
        self.tenant_id = tenant_id
        self.employee_id = employee_id
        self.store_id = store_id
        self.target_date = target_date
        self.requested_mode_id = requested_mode_id
        self.reason = cleaned_reason
        self.status = status
        self.manager_note = manager_note
        self.manager_id = manager_id
        self.decided_by = decided_by
        self.decision_reason = decision_reason
        self.decided_at = decided_at
        self.created_at = require_aware(created_at, field="created_at")

        # Repository-dən bərpa edilən obyekt hadisə YAYMAMALIDIR — əks halda
        # hər oxunuş "yeni sorğu göndərildi" bildirişi göndərərdi.
        if emit_created_event and status is SwapStatus.PENDING_APPROVAL:
            self.record_event(
                ShiftSwapRequestedEvent(
                    tenant_id=tenant_id,
                    request_id=request_id,
                    employee_id=employee_id,
                    target_date=target_date,
                    reason=cleaned_reason,
                )
            )

    # ------------------------------ menecer ---------------------------------- #

    def attach_manager_note(self, *, manager_id: EmployeeId, note: str) -> None:
        """Store Manager-in tövsiyəsi — STATUSU DƏYİŞMİR (bölmə 3).

        Menecer sorğunu HR-a "yönləndirir", təsdiq etmir. Statusun burada
        toxunulmaz qalması həmin qaydanın struktur zəmanətidir.
        """
        self._require_pending("Qərar verilmiş sorğuya qeyd əlavə edilə bilməz")
        cleaned = normalise_decision_text(note)
        if not cleaned:
            raise DomainRuleError(
                "Menecer qeydi boş ola bilməz",
                user_message="Qeyd mətnini yazın.",
            )
        self.manager_note = cleaned
        self.manager_id = manager_id

    # ------------------------------- qərar ----------------------------------- #

    def approve(self, *, approver_id: EmployeeId, decided_at: datetime) -> None:
        """`[Təsdiqlə]` — çağıran tərəf ardınca Shift Matrix-i yeniləyir."""
        self._decide(
            approved=True,
            approver_id=approver_id,
            decided_at=decided_at,
            reason=None,
        )

    def reject(self, *, approver_id: EmployeeId, decided_at: datetime, reason: str) -> None:
        """`[Rədd Et]` — səbəb MƏCBURİDİR (işçiyə bildirişdə göstərilir)."""
        cleaned = normalise_decision_text(reason)
        if len(cleaned) < MIN_DECISION_REASON_LENGTH:
            raise DomainRuleError(
                f"Rədd səbəbi minimum {MIN_DECISION_REASON_LENGTH} simvol olmalıdır",
                user_message="Rədd səbəbini ətraflı yazın.",
                context={"length": len(cleaned)},
            )
        self._decide(
            approved=False,
            approver_id=approver_id,
            decided_at=decided_at,
            reason=cleaned,
        )

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
            # Öz sorğusunu özü təsdiqləmək vəzifə ayrılığını pozar.
            raise DomainRuleError(
                "İşçi öz növbə dəyişmə sorğusunu özü təsdiqləyə/rədd edə bilməz",
                user_message="Öz sorğunuza qərar verə bilməzsiniz.",
                context={"employee_id": str(self.employee_id)},
            )

        self.status = SwapStatus.APPROVED if approved else SwapStatus.REJECTED
        self.decided_by = approver_id
        self.decided_at = require_aware(decided_at, field="decided_at")
        self.decision_reason = reason
        self.record_event(
            ShiftSwapDecidedEvent(
                tenant_id=self.tenant_id,
                request_id=self.id,
                approver_id=approver_id,
                approved=approved,
                reason=reason,
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
            f"ShiftSwapRequest(id={self.id}, employee={self.employee_id}, "
            f"date={self.target_date}, status={self.status.value})"
        )


__all__ = [
    "MIN_DECISION_REASON_LENGTH",
    "MIN_SWAP_REASON_LENGTH",
    "ShiftAssignment",
    "ShiftSource",
    "ShiftSwapRequest",
    "SwapStatus",
]
