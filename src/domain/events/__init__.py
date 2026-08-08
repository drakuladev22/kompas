"""Domen hadisələri — modullar-arası yeganə kommunikasiya vasitəsi.

Spesifikasiya bölmə 1 iki hadisəni açıq şəkildə adlandırır:
`LeaveVerifiedEvent` və `ManualTimeOverrideEvent`. Aşağıdakı qalan hadisələr
Faza 2-də yazılacaq use case-lərin ehtiyac duyacağı skeletlərdir — yalnız
hadisə müqaviləsi (contract) təyin olunur, biznes məntiqi Faza 2-dədir.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from src.shared.event_bus import DomainEvent

# --------------------------------------------------------------------------- #
# Morning Check-in (bölmə 4 — GÜNÜN BAŞLANĞICI)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class MorningCheckInRequestedEvent(DomainEvent):
    """STEP A: işçi Kiosk-da `[İşə Başladım]` basdı → status `🟡`."""

    attendance_record_id: uuid.UUID
    employee_id: uuid.UUID
    store_id: uuid.UUID
    requested_at: datetime
    ntp_verified: bool


@dataclass(frozen=True, kw_only=True)
class MorningCheckInVerifiedEvent(DomainEvent):
    """STEP C (Option A): Kamera Operatoru təsdiqlədi → status `🟢 Mağazada`."""

    attendance_record_id: uuid.UUID
    employee_id: uuid.UUID
    store_id: uuid.UUID
    verified_at: datetime
    operator_id: uuid.UUID
    is_late: bool
    work_mode_start: datetime | None


@dataclass(frozen=True, kw_only=True)
class MorningCheckInRejectedEvent(DomainEvent):
    """STEP C (Rədd yolu): uyğunsuzluq → status `⚪`, HR/Store Manager-ə bildiriş."""

    attendance_record_id: uuid.UUID
    employee_id: uuid.UUID
    store_id: uuid.UUID
    operator_id: uuid.UUID
    reason: str


@dataclass(frozen=True, kw_only=True)
class UnauthorizedAbsenceDetectedEvent(DomainEvent):
    """ "İCAZƏSİZ QAYIB" qaydası (bölmə 4) — gün sonunda avtomatik təyin olunur."""

    employee_id: uuid.UUID
    store_id: uuid.UUID
    absence_date: date


# --------------------------------------------------------------------------- #
# 3-Step Leave Verification (bölmə 4)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class LeaveRequestedEvent(DomainEvent):
    """STEP 1: `[İcazə İstəyirəm]` — `Requested_Time` rəsmi qeydə alındı."""

    leave_request_id: uuid.UUID
    employee_id: uuid.UUID
    store_id: uuid.UUID
    leave_type_id: uuid.UUID
    requested_time: datetime
    ntp_verified: bool


@dataclass(frozen=True, kw_only=True)
class LeaveReturnClaimedEvent(DomainEvent):
    """STEP 2: `[Mən Qayıtdım]` — status `🟡 Gözləyir (Kamera Təsdiqi)`."""

    leave_request_id: uuid.UUID
    employee_id: uuid.UUID
    claimed_at: datetime


@dataclass(frozen=True, kw_only=True)
class LeaveVerifiedEvent(DomainEvent):
    """STEP 3: Kamera Operatoru qayıdışı təsdiqlədi (spesifikasiya bölmə 1).

    `verified_actual_time` — cərimə düsturunun YEGANƏ mənbəyidir; operatorun
    düyməni kliklədiyi vaxt DEYİL (bax bölmə 4 PENALTY LOGIC).
    """

    leave_request_id: uuid.UUID
    employee_id: uuid.UUID
    operator_id: uuid.UUID
    requested_time: datetime
    verified_actual_time: datetime
    delay_minutes: int
    total_minutes: int
    was_manual_override: bool


@dataclass(frozen=True, kw_only=True)
class ManualTimeOverrideEvent(DomainEvent):
    """`[Vaxtı Əllə Təyin Et]` (spesifikasiya bölmə 1 və 4).

    30+ dəqiqəlik fərq `requires_dual_control=True` yaradır və HR_Admin/CEO
    təsdiqinə yönləndirilir.
    """

    leave_request_id: uuid.UUID
    employee_id: uuid.UUID
    operator_id: uuid.UUID
    system_time: datetime
    overridden_time: datetime
    delta_minutes: int
    reason: str
    requires_dual_control: bool


@dataclass(frozen=True, kw_only=True)
class DualControlApprovalRequestedEvent(DomainEvent):
    """İkinci təsdiq gözlənilir — e-poçt fallback kanalına düşür (bölmə 7)."""

    override_id: uuid.UUID
    leave_request_id: uuid.UUID
    operator_id: uuid.UUID
    delta_minutes: int


@dataclass(frozen=True, kw_only=True)
class DualControlDecisionEvent(DomainEvent):
    override_id: uuid.UUID
    approver_id: uuid.UUID
    approved: bool
    reason: str | None


@dataclass(frozen=True, kw_only=True)
class VerificationTimeoutEscalatedEvent(DomainEvent):
    """45 dəqiqəlik timeout — HR_Admin/Store Manager-ə eskalasiya (bölmə 4)."""

    subject_type: str  # "MORNING_CHECK_IN" | "LEAVE_RETURN"
    subject_id: uuid.UUID
    employee_id: uuid.UUID
    store_id: uuid.UUID
    waiting_minutes: int


# --------------------------------------------------------------------------- #
# Cərimələr (bölmə 4)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class FineIssuedEvent(DomainEvent):
    fine_id: uuid.UUID
    employee_id: uuid.UUID
    store_id: uuid.UUID
    source: str  # AUTO_DELAY | MANUAL_CAMERA
    amount: Decimal
    issued_by: uuid.UUID | None
    fine_type_id: uuid.UUID | None


@dataclass(frozen=True, kw_only=True)
class FineAppealSubmittedEvent(DomainEvent):
    appeal_id: uuid.UUID
    fine_id: uuid.UUID
    employee_id: uuid.UUID
    reason: str


@dataclass(frozen=True, kw_only=True)
class FineReversedEvent(DomainEvent):
    """Cərimə ləğv edildi — orijinal qeyd SİLİNMİR, yalnız `REVERSED` statusu."""

    fine_id: uuid.UUID
    appeal_id: uuid.UUID | None
    decided_by: uuid.UUID
    new_amount: Decimal


# --------------------------------------------------------------------------- #
# Növbə & Tabel (bölmə 3, 4)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class ShiftAssignmentChangedEvent(DomainEvent):
    employee_id: uuid.UUID
    shift_date: date
    old_work_mode_id: uuid.UUID | None
    new_work_mode_id: uuid.UUID | None
    changed_by: uuid.UUID


@dataclass(frozen=True, kw_only=True)
class ShiftSwapRequestedEvent(DomainEvent):
    request_id: uuid.UUID
    employee_id: uuid.UUID
    target_date: date
    reason: str


@dataclass(frozen=True, kw_only=True)
class ShiftSwapDecidedEvent(DomainEvent):
    request_id: uuid.UUID
    approver_id: uuid.UUID
    approved: bool
    reason: str | None


@dataclass(frozen=True, kw_only=True)
class DailyAttendanceSheetConfirmedEvent(DomainEvent):
    sheet_id: uuid.UUID
    store_id: uuid.UUID
    sheet_date: date
    confirmed_by: uuid.UUID
    mismatch_count: int


# --------------------------------------------------------------------------- #
# Tapşırıqlar (bölmə 6)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class TaskAssignedEvent(DomainEvent):
    task_id: uuid.UUID
    assignee_id: uuid.UUID
    assigned_by: uuid.UUID
    deadline: datetime


@dataclass(frozen=True, kw_only=True)
class TaskEvidenceSubmittedEvent(DomainEvent):
    task_id: uuid.UUID
    assignee_id: uuid.UUID
    evidence_count: int


@dataclass(frozen=True, kw_only=True)
class TaskEvidenceReviewedEvent(DomainEvent):
    task_id: uuid.UUID
    reviewer_id: uuid.UUID
    approved: bool
    reason: str | None


@dataclass(frozen=True, kw_only=True)
class TaskDeadlineEscalatedEvent(DomainEvent):
    task_id: uuid.UUID
    assignee_id: uuid.UUID
    assigned_by: uuid.UUID
    overdue_minutes: int


# --------------------------------------------------------------------------- #
# İcazələr & Sistem (bölmə 3)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class PermissionChangedEvent(DomainEvent):
    """Rol-defolt və ya fərdi override dəyişikliyi — tam audit tələb edir."""

    subject_user_id: uuid.UUID | None
    position_id: uuid.UUID | None
    flag_code: str
    old_value: bool | None
    new_value: bool | None
    changed_by: uuid.UUID


@dataclass(frozen=True, kw_only=True)
class SystemLimitChangedEvent(DomainEvent):
    limit_key: str
    old_value: str
    new_value: str
    changed_by: uuid.UUID


@dataclass(frozen=True, kw_only=True)
class FeatureToggleChangedEvent(DomainEvent):
    module_key: str
    enabled: bool
    changed_by: uuid.UUID


# --------------------------------------------------------------------------- #
# İnfrastruktur & Lisenziya (bölmə 2, 5, 8)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class TimeDriftDetectedEvent(DomainEvent):
    """NTP fərqi 60 saniyəni keçdi → vaxt-kritik əməliyyatlar bloklanır."""

    drift_seconds: float
    ntp_server: str
    machine_name: str


@dataclass(frozen=True, kw_only=True)
class SyncConflictDetectedEvent(DomainEvent):
    """Audit-kritik cədvəldə konflikt → HR_Admin-ə manual həll üçün."""

    table_name: str
    record_id: uuid.UUID
    local_version: str
    remote_version: str


@dataclass(frozen=True, kw_only=True)
class LicenseStatusChangedEvent(DomainEvent):
    tenant_id_value: uuid.UUID
    old_status: str
    new_status: str


__all__ = [
    "DailyAttendanceSheetConfirmedEvent",
    "DualControlApprovalRequestedEvent",
    "DualControlDecisionEvent",
    "FeatureToggleChangedEvent",
    "FineAppealSubmittedEvent",
    "FineIssuedEvent",
    "FineReversedEvent",
    "LeaveRequestedEvent",
    "LeaveReturnClaimedEvent",
    "LeaveVerifiedEvent",
    "LicenseStatusChangedEvent",
    "ManualTimeOverrideEvent",
    "MorningCheckInRejectedEvent",
    "MorningCheckInRequestedEvent",
    "MorningCheckInVerifiedEvent",
    "PermissionChangedEvent",
    "ShiftAssignmentChangedEvent",
    "ShiftSwapDecidedEvent",
    "ShiftSwapRequestedEvent",
    "SyncConflictDetectedEvent",
    "SystemLimitChangedEvent",
    "TaskAssignedEvent",
    "TaskDeadlineEscalatedEvent",
    "TaskEvidenceReviewedEvent",
    "TaskEvidenceSubmittedEvent",
    "TimeDriftDetectedEvent",
    "UnauthorizedAbsenceDetectedEvent",
    "VerificationTimeoutEscalatedEvent",
]
