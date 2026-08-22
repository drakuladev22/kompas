"""MORNING CHECK-IN HANDSHAKE aqreqatı (spesifikasiya bölmə 4).

Bu, 3-STEP LEAVE VERIFICATION-dan FƏRQLİ, ONDAN ƏVVƏL baş verən axındır:
icazə/qayıdış GÜN ƏRZİNDƏ, bu isə GÜNÜN ƏVVƏLİNDƏ.

VƏZİYYƏT MAŞINI::

    ⚪ NOT_STARTED
          ↓  [STEP A: İşə Başladım]  (Kiosk, NTP-yə qarşı yoxlanılmış möhür)
    🟡 PENDING_VERIFICATION
          ↓                ↓                    ↓
    [STEP C: Təsdiqlə]  [STEP C: Rədd Et]   [45 dəq. timeout]
          ↓                ↓                    ↓
    🟢 VERIFIED        ⚪ NOT_STARTED       HR_Admin/CEO manual həlli
                       (+ HR-a bildiriş)

"İCAZƏSİZ QAYIB" QAYDASI (bölmə 4):
    Gün off-day kimi işarələnməyibsə VƏ həmin gün üçün `🟢 VERIFIED` statusuna
    çatan qeyd YOXDURSA (gün sonuna qədər) → avtomatik "İcazəsiz Qayıb".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from src.domain.entities.base import (
    AggregateRoot,
    DomainRuleError,
    InvalidStateTransitionError,
)
from src.domain.events import (
    MorningCheckInRejectedEvent,
    MorningCheckInRequestedEvent,
    MorningCheckInVerifiedEvent,
    UnauthorizedAbsenceDetectedEvent,
    VerificationTimeoutEscalatedEvent,
)
from src.domain.value_objects.identifiers import (
    AttendanceRecordId,
    EmployeeId,
    StoreId,
    TenantId,
)
from src.domain.value_objects.scheduling import (
    LatenessAssessment,
    assess_lateness,
    require_aware,
)
from src.shared.text import normalise_decision_text

#: Rədd səbəbi üçün minimum uzunluq — override səbəbi ilə eyni standart.
MIN_REJECT_REASON_LENGTH = 10


class CheckInStatus(str, Enum):
    """Morning Check-in statusu (`attendance_records.check_in_status` ilə eyni)."""

    NOT_STARTED = "NOT_STARTED"  # ⚪ Günə Başlamayıb
    PENDING_VERIFICATION = "PENDING_VERIFICATION"  # 🟡 Giriş Təsdiqi Gözləyir
    VERIFIED = "VERIFIED"  # 🟢 Mağazada

    #: QƏSDƏN İSTİFADƏ OLUNMUR — `reject()` statusu `NOT_STARTED`-ə qaytarır,
    #: çünki bölmə 4 açıq şəkildə deyir: "status ⚪ Günə Başlamayıb-a QAYIDIR"
    #: (işçi yenidən cəhd edə bilməlidir). Dəyər DB enum-u ilə paritet üçün
    #: saxlanılır: `check_in_status` tipində mövcuddur və köhnə/xarici mənbədən
    #: gələn sətir bu dəyəri daşısa, mapper çökməməlidir.
    #: Rədd faktı `rejection` və `rejection_count` sahələrində saxlanılır.
    REJECTED = "REJECTED"

    @property
    def is_present_in_store(self) -> bool:
        """İşçi `[İcazə İstəyirəm]` düyməsini görə bilirmi (bölmə 4)."""
        return self is CheckInStatus.VERIFIED


@dataclass(frozen=True)
class RejectionDetails:
    """STEP C rədd yolu — HR_Admin/Store Manager-ə araşdırma üçün gedir."""

    operator_id: EmployeeId
    reason: str
    rejected_at: datetime


class AttendanceRecord(AggregateRoot):
    """Bir işçinin bir günə aid davamiyyət qeydi."""

    def __init__(
        self,
        *,
        record_id: AttendanceRecordId,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        store_id: StoreId,
        work_date: date,
        status: CheckInStatus = CheckInStatus.NOT_STARTED,
    ) -> None:
        super().__init__()
        self.id = record_id
        self.tenant_id = tenant_id
        self.employee_id = employee_id
        self.store_id = store_id
        self.work_date = work_date

        self.status = status
        self.requested_at: datetime | None = None
        self.verified_at: datetime | None = None
        self.verified_by: EmployeeId | None = None
        self.rejection: RejectionDetails | None = None
        self.escalated_at: datetime | None = None
        self.ntp_verified = False
        self.lateness: LatenessAssessment | None = None
        self.is_unauthorized_absence = False
        #: Neçə dəfə rədd edilib — təkrarlanan rədd araşdırma siqnalıdır.
        self.rejection_count = 0

    # ------------------------------ STEP A ---------------------------------- #

    def request_check_in(self, *, requested_at: datetime, ntp_verified: bool) -> None:
        """STEP A — Kiosk-da `[İşə Başladım]`. Status `🟡` olur."""
        require_aware(requested_at, field="requested_at")

        if self.status is CheckInStatus.VERIFIED:
            raise DomainRuleError(
                "İşçi artıq bu gün üçün təsdiqlənib",
                user_message="Siz artıq bu gün işə başlamısınız.",
            )
        if self.status is CheckInStatus.PENDING_VERIFICATION:
            raise DomainRuleError(
                "Giriş təsdiqi artıq gözlənilir",
                user_message="Kamera Operatorunun təsdiqini gözləyin.",
            )

        self.requested_at = requested_at
        self.ntp_verified = ntp_verified
        self.status = CheckInStatus.PENDING_VERIFICATION
        self.is_unauthorized_absence = False
        self.escalated_at = None

        self.record_event(
            MorningCheckInRequestedEvent(
                attendance_record_id=self.id,
                employee_id=self.employee_id,
                store_id=self.store_id,
                requested_at=requested_at,
                ntp_verified=ntp_verified,
                tenant_id=self.tenant_id,
                actor_id=self.employee_id,
            )
        )

    # ------------------------------ STEP C ---------------------------------- #

    def verify(
        self,
        *,
        operator_id: EmployeeId,
        verified_at: datetime,
        scheduled_start: datetime | None = None,
        late_tolerance_minutes: int = 0,
    ) -> LatenessAssessment:
        """STEP C — `[İşçini Təsdiqlə]`.

        Bölmə 4: "günün rəsmi başlama vaxtı bu an kimi qeydə alınır."

        Gecikmə burada hesablanır, lakin CƏRİMƏ YARATMIR — yalnız Gündəlik
        Tabeldə "Gecikib" işarəsi və hesabat üçündür.
        """
        require_aware(verified_at, field="verified_at")
        self._require_verifiable()

        lateness = assess_lateness(
            verified_at=verified_at,
            scheduled_start=scheduled_start,
            tolerance_minutes=late_tolerance_minutes,
        )

        self.verified_at = verified_at
        self.verified_by = operator_id
        self.status = CheckInStatus.VERIFIED
        self.lateness = lateness
        self.is_unauthorized_absence = False

        self.record_event(
            MorningCheckInVerifiedEvent(
                attendance_record_id=self.id,
                employee_id=self.employee_id,
                store_id=self.store_id,
                verified_at=verified_at,
                operator_id=operator_id,
                is_late=lateness.is_late,
                work_mode_start=scheduled_start,
                tenant_id=self.tenant_id,
                actor_id=operator_id,
            )
        )
        return lateness

    def reject(self, *, operator_id: EmployeeId, reason: str, rejected_at: datetime) -> None:
        """STEP C rədd yolu (bölmə 4, ROBUSTLUQ düzəlişi).

        Məs. görüntüdə başqa şəxs PIN-dən istifadə edib. Status `⚪`-ya qayıdır
        və HR_Admin/Store Manager-ə DƏRHAL bildiriş gedir.
        """
        require_aware(rejected_at, field="rejected_at")
        self._require_verifiable()

        cleaned = normalise_decision_text(reason)
        if len(cleaned) < MIN_REJECT_REASON_LENGTH:
            raise DomainRuleError(
                f"Rədd səbəbi minimum {MIN_REJECT_REASON_LENGTH} simvol olmalıdır",
                user_message=f"Səbəb ən azı {MIN_REJECT_REASON_LENGTH} simvol olmalıdır.",
            )

        self.rejection = RejectionDetails(
            operator_id=operator_id, reason=cleaned, rejected_at=rejected_at
        )
        self.rejection_count += 1
        # Bölmə 4: "status ⚪ Günə Başlamayıb-a QAYIDIR" — işçi yenidən cəhd edə bilər.
        self.status = CheckInStatus.NOT_STARTED
        self.requested_at = None
        self.escalated_at = None

        self.record_event(
            MorningCheckInRejectedEvent(
                attendance_record_id=self.id,
                employee_id=self.employee_id,
                store_id=self.store_id,
                operator_id=operator_id,
                reason=cleaned,
                tenant_id=self.tenant_id,
                actor_id=operator_id,
            )
        )

    # ----------------------------- TIMEOUT ---------------------------------- #

    def escalate_timeout(self, *, now: datetime, timeout_minutes: int = 45) -> bool:
        """45 dəqiqəlik timeout — STEP 2 ilə EYNİ mexanizm (bölmə 4).

        Status `🟡` olaraq QALIR: işçi limbo-da qalmasın deyə HR_Admin/CEO
        manual təsdiq/rədd edə bilir, lakin növbə ekranından itmir.
        """
        require_aware(now, field="now")
        if self.status is not CheckInStatus.PENDING_VERIFICATION:
            return False
        if self.escalated_at is not None or self.requested_at is None:
            return False

        waiting = int((now - self.requested_at).total_seconds() // 60)
        if waiting < timeout_minutes:
            return False

        self.escalated_at = now
        self.record_event(
            VerificationTimeoutEscalatedEvent(
                subject_type="MORNING_CHECK_IN",
                subject_id=self.id,
                employee_id=self.employee_id,
                store_id=self.store_id,
                waiting_minutes=waiting,
                tenant_id=self.tenant_id,
            )
        )
        return True

    # ------------------------- İCAZƏSİZ QAYIB -------------------------------- #

    def mark_unauthorized_absence(self, *, is_off_day: bool) -> bool:
        """Gün sonunda "İcazəsiz Qayıb" təyinetməsi (bölmə 4).

        Args:
            is_off_day: Shift Calendar-da off-day kimi işarələnibmi.

        Returns:
            Qayıb BU çağırışda təyin edildisə `True`.
        """
        if is_off_day:
            return False
        if self.status is CheckInStatus.VERIFIED:
            return False
        if self.is_unauthorized_absence:
            return False

        self.is_unauthorized_absence = True
        self.record_event(
            UnauthorizedAbsenceDetectedEvent(
                employee_id=self.employee_id,
                store_id=self.store_id,
                absence_date=self.work_date,
                tenant_id=self.tenant_id,
            )
        )
        return True

    # ------------------------------ köməkçi --------------------------------- #

    @property
    def can_request_leave(self) -> bool:
        """STEP 1 (`[İcazə İstəyirəm]`) aktivdirmi — bölmə 4."""
        return self.status.is_present_in_store

    @property
    def is_awaiting_operator(self) -> bool:
        return self.status is CheckInStatus.PENDING_VERIFICATION

    def _require_verifiable(self) -> None:
        if self.status is not CheckInStatus.PENDING_VERIFICATION:
            raise InvalidStateTransitionError(
                f"Təsdiq/rədd üçün status 'PENDING_VERIFICATION' olmalıdır, "
                f"cari: '{self.status.value}'",
                context={"actual": self.status.value},
            )

    def __repr__(self) -> str:
        return (
            f"AttendanceRecord(employee={self.employee_id}, date={self.work_date}, "
            f"status={self.status.value})"
        )


__all__ = [
    "MIN_REJECT_REASON_LENGTH",
    "AttendanceRecord",
    "CheckInStatus",
    "RejectionDetails",
]
