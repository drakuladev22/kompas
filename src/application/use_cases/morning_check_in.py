"""MORNING CHECK-IN use case-i (spesifikasiya bölmə 4) — Faza 2.5.

STEP A → STEP B (növbə) → STEP C (təsdiq/rədd), plus 45 dəqiqəlik timeout və
gün sonunda "İcazəsiz Qayıb" təyinetməsi.

3-STEP LEAVE VERIFICATION-dan FƏRQLİ olaraq bu axın tək aqreqata toxunur
(`attendance_records`), ona görə Saga LAZIM DEYİL — sadə tranzaksiya kifayətdir.
Bu, qəsdən seçimdir: hər əməliyyatı Saga-ya salmaq reconciliation növbəsini
lazımsız yükləyərdi (bax SEC-003).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from src.application.use_cases.leave_verification import (
    ModuleDisabledError,
    OperationNotPermittedError,
    TimeDriftError,
)
from src.domain.entities.attendance_record import AttendanceRecord, CheckInStatus
from src.domain.interfaces.ports import (
    AttendanceRepository,
    AuditTrail,
    CameraAssignmentRepository,
    Clock,
    EmployeeRepository,
    FeatureToggles,
    Notifier,
    NtpVerifier,
    RowLockingAttendance,
    ShiftRepository,
    SystemLimits,
)
from src.domain.policies import DEFAULT_LIMITS, FeatureModule, SystemLimitKey
from src.domain.value_objects.authorization import DUAL_CONTROL_APPROVAL_FLAG
from src.domain.value_objects.identifiers import (
    EmployeeId,
    StoreId,
    TenantId,
    new_attendance_record_id,
)
from src.domain.value_objects.scheduling import LatenessAssessment, resolve_work_date
from src.shared.logger import get_logger

_log = get_logger(__name__)


@dataclass(frozen=True)
class CheckInOutcome:
    """STEP C-nin nəticəsi."""

    record: AttendanceRecord
    lateness: LatenessAssessment | None
    was_rejected: bool = False


class MorningCheckInUseCase:
    """Günün başlanğıcı — işə giriş təsdiqi axını."""

    def __init__(
        self,
        *,
        attendance: AttendanceRepository,
        shifts: ShiftRepository,
        employees: EmployeeRepository,
        camera_assignments: CameraAssignmentRepository,
        clock: Clock,
        ntp: NtpVerifier,
        limits: SystemLimits,
        toggles: FeatureToggles,
        audit: AuditTrail,
        notifier: Notifier,
    ) -> None:
        self._attendance = attendance
        self._shifts = shifts
        self._employees = employees
        self._camera_assignments = camera_assignments
        self._clock = clock
        self._ntp = ntp
        self._limits = limits
        self._toggles = toggles
        self._audit = audit
        self._notifier = notifier

    # ------------------------------ STEP A ---------------------------------- #

    def start_day(
        self,
        *,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        store_id: StoreId,
        work_date: date | None = None,
    ) -> AttendanceRecord:
        """`[İşə Başladım]` — status `🟡 Giriş Təsdiqi Gözləyir`."""
        self._require_module(tenant_id, FeatureModule.CAMERA_VERIFICATION)
        requested_at, ntp_ok = self._verified_now(tenant_id, operation="STEP_A")
        day = work_date or self._resolve_work_date(employee_id, at=requested_at)

        record = self._attendance.get_for_day(employee_id, day)
        if record is None:
            record = AttendanceRecord(
                record_id=new_attendance_record_id(),
                tenant_id=tenant_id,
                employee_id=employee_id,
                store_id=store_id,
                work_date=day,
            )

        record.request_check_in(requested_at=requested_at, ntp_verified=ntp_ok)
        self._attendance.save(record)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=employee_id,
            action="MORNING_CHECK_IN_REQUESTED",
            entity_type="attendance_records",
            entity_id=record.id,
            after_state={
                "requested_at": requested_at.isoformat(),
                "ntp_verified": ntp_ok,
                "work_date": day.isoformat(),
            },
        )
        return record

    # ------------------------------ STEP B ---------------------------------- #

    def pending_queue(self, operator_id: EmployeeId) -> list[AttendanceRecord]:
        """Kamera Operatorunun giriş-təsdiqi növbəsi.

        FAIL-SAFE (bölmə 4): təyinat yoxdursa BOŞ siyahı — "defolt hər şeyi
        göstər" DEYİL, "defolt heç nəyi göstərmə".
        """
        stores = self._camera_assignments.stores_for_operator(operator_id)
        if not stores:
            _log.info(
                "CAMERA_OPERATOR_WITHOUT_STORES",
                extra={"operator_id": str(operator_id)},
            )
            return []
        return self._attendance.list_pending_verification(stores)

    # ------------------------------ STEP C ---------------------------------- #

    def verify(
        self,
        *,
        tenant_id: TenantId,
        operator_id: EmployeeId,
        employee_id: EmployeeId,
        work_date: date | None = None,
    ) -> CheckInOutcome:
        """`[İşçini Təsdiqlə]` — günün rəsmi başlama vaxtı qeydə alınır."""
        verified_at, _ = self._verified_now(tenant_id, operation="STEP_C_VERIFY")
        day = work_date or self._resolve_work_date(employee_id, at=verified_at)
        # Kilidli oxu: `[Təsdiqlə]` və `[Rədd Et]` eyni sətrə yazır. Kilidsiz
        # halda hər iki operator `PENDING_VERIFICATION` görür, hər ikisi audit
        # yazır və DB-də yalnız sonuncu status qalır — audit jurnalı ilə
        # faktiki vəziyyət bir-birini təkzib edərdi (bax `RowLockingAttendance`).
        record = self._require_record_locked(employee_id, day)
        self._require_camera_permission(operator_id, record)
        self._require_operator_scope(operator_id, record.store_id)

        lateness = record.verify(
            operator_id=operator_id,
            verified_at=verified_at,
            scheduled_start=self._shifts.scheduled_start(employee_id, day),
            late_tolerance_minutes=self._limit_int(
                tenant_id, SystemLimitKey.LATE_TOLERANCE_MINUTES
            ),
        )
        self._attendance.save(record)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=operator_id,
            action="MORNING_CHECK_IN_VERIFIED",
            entity_type="attendance_records",
            entity_id=record.id,
            after_state={
                "verified_at": verified_at.isoformat(),
                "is_late": lateness.is_late,
                "late_minutes": lateness.late_minutes,
            },
        )
        return CheckInOutcome(record=record, lateness=lateness)

    def reject(
        self,
        *,
        tenant_id: TenantId,
        operator_id: EmployeeId,
        employee_id: EmployeeId,
        reason: str,
        work_date: date | None = None,
    ) -> CheckInOutcome:
        """`[Rədd Et]` — məs. görüntüdə başqa şəxs PIN-dən istifadə edib.

        Status `⚪`-ya qayıdır və HR_Admin/Store Manager-ə DƏRHAL bildiriş gedir.
        """
        rejected_at, _ = self._verified_now(tenant_id, operation="STEP_C_REJECT")
        day = work_date or self._resolve_work_date(employee_id, at=rejected_at)
        # Kilidli oxu — `verify()` ilə eyni səbəb (paralel təsdiq/rədd yarışı).
        record = self._require_record_locked(employee_id, day)
        self._require_camera_permission(operator_id, record)
        self._require_operator_scope(operator_id, record.store_id)

        record.reject(operator_id=operator_id, reason=reason, rejected_at=rejected_at)
        self._attendance.save(record)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=operator_id,
            action="MORNING_CHECK_IN_REJECTED",
            entity_type="attendance_records",
            entity_id=record.id,
            after_state={"rejected_at": rejected_at.isoformat()},
            reason=reason,
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=None,  # HR_Admin + Store Manager
            category="CHECK_IN_REJECTED",
            title_az="İşə giriş təsdiqi rədd edildi",
            body_az=(
                f"Kamera Operatoru giriş təsdiqini rədd etdi. Səbəb: {reason}. "
                f"Araşdırma tələb oluna bilər."
            ),
            is_critical=True,
        )
        return CheckInOutcome(record=record, lateness=None, was_rejected=True)

    # ----------------------------- TIMEOUT ---------------------------------- #

    def escalate_timeouts(self, tenant_id: TenantId, operator_id: EmployeeId) -> int:
        """45 dəqiqəlik timeout — status `🟡` QALIR (bölmə 4)."""
        now = self._clock.now()
        timeout = self._limit_int(tenant_id, SystemLimitKey.VERIFICATION_TIMEOUT_MINUTES)
        stores = self._camera_assignments.stores_for_operator(operator_id)
        escalated = 0

        for record in self._attendance.list_pending_verification(stores):
            if not record.escalate_timeout(now=now, timeout_minutes=timeout):
                continue
            self._attendance.save(record)
            escalated += 1
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=None,
                category="CHECK_IN_TIMEOUT",
                title_az="İşə giriş təsdiqi gecikir",
                body_az=(
                    f"İşçinin giriş təsdiqi {timeout} dəqiqədən çoxdur gözləyir. "
                    f"HR_Admin və ya CEO manual təsdiq/rədd edə bilər "
                    f"(Mağaza Meneceri YOX — cüt nəzarət pilləliyi)."
                ),
                is_critical=True,
            )
        return escalated

    # ------------------------- İCAZƏSİZ QAYIB -------------------------------- #

    def detect_absences(self, tenant_id: TenantId, work_date: date) -> int:
        """Gün sonunda "İcazəsiz Qayıb" təyinetməsi (bölmə 4).

        QAYDA: off-day kimi işarələnməyibsə VƏ `🟢 VERIFIED` qeyd yoxdursa →
        avtomatik "İcazəsiz Qayıb". Attendance Report bu sütunu buradan alır.
        """
        marked = 0
        for record in self._attendance.list_expected_on(tenant_id, work_date):
            is_off_day = self._shifts.is_off_day(record.employee_id, work_date)
            if not record.mark_unauthorized_absence(is_off_day=is_off_day):
                continue
            self._attendance.save(record)
            marked += 1
            self._audit.record(
                tenant_id=tenant_id,
                actor_id=None,
                action="UNAUTHORIZED_ABSENCE_DETECTED",
                entity_type="attendance_records",
                entity_id=record.id,
                after_state={"work_date": work_date.isoformat()},
            )

        if marked:
            _log.info(
                "ABSENCES_DETECTED",
                extra={
                    "tenant_id": str(tenant_id),
                    "work_date": work_date.isoformat(),
                    "count": marked,
                },
            )
        return marked

    # ------------------------------ köməkçi --------------------------------- #

    def employee_can_request_leave(self, employee_id: EmployeeId, work_date: date) -> bool:
        """STEP 1 aktivdirmi — yalnız `🟢 Mağazada` statusundan (bölmə 4)."""
        record = self._attendance.get_for_day(employee_id, work_date)
        return record is not None and record.can_request_leave

    def _require_record(self, employee_id: EmployeeId, work_date: date) -> AttendanceRecord:
        record = self._attendance.get_for_day(employee_id, work_date)
        if record is None:
            raise OperationNotPermittedError(
                "Bu gün üçün davamiyyət qeydi yoxdur",
                user_message="İşçi bu gün üçün işə başlama sorğusu göndərməyib.",
                context={
                    "employee_id": str(employee_id),
                    "work_date": work_date.isoformat(),
                },
            )
        if record.status is not CheckInStatus.PENDING_VERIFICATION:
            raise OperationNotPermittedError(
                f"Təsdiq/rədd üçün status 'PENDING_VERIFICATION' olmalıdır, "
                f"cari: '{record.status.value}'",
                user_message="Bu sorğu artıq emal edilib.",
                context={"status": record.status.value},
            )
        return record

    def _require_record_locked(self, employee_id: EmployeeId, work_date: date) -> AttendanceRecord:
        """`_require_record`-in YAZMA axını üçün sətir-kilidli variantı.

        Mövcud oxu-yalnız yol (`employee_can_request_leave`, növbə siyahısı)
        TOXUNULMAZ qalır — kilid yalnız STEP C təsdiq/rədd axınındadır.
        Repo kilidi dəstəkləmirsə davranış əvvəlki kimidir: statusu
        `_require_record` yenə yoxlayır, sadəcə oxu ilə yazı arasındakı
        pəncərə bağlanmır.

        Sətir tapılmadıqda (və ya statusu artıq dəyişibsə) yoxlama yenə
        `_require_record`-a həvalə olunur — istisna mətni və şərt TƏK YERDƏ
        qalır, iki nüsxə bir-birindən sürüşə bilməz.
        """
        repository = self._attendance
        if not isinstance(repository, RowLockingAttendance):
            return self._require_record(employee_id, work_date)
        record = repository.get_for_day_for_update(employee_id, work_date)
        if record is None or record.status is not CheckInStatus.PENDING_VERIFICATION:
            return self._require_record(employee_id, work_date)
        return record

    def _require_camera_permission(self, operator_id: EmployeeId, record: AttendanceRecord) -> None:
        """`can_verify_returns` yoxlaması (bölmə 3).

        STEP B/C giriş-təsdiqi eyni flag-lə idarə olunur — bölmə 4 onu açıq
        deyir: flag-in təsviri "STEP 3 və Morning Check-in təsdiqi"dir.

        Timeout keçibsə (`escalated_at` doludur) HR_Admin/CEO operator əvəzinə
        təsdiq/rədd edə bilər — bölmə 4: "işçi günü boyu limbo-da qalmasın".
        Store Manager bu yola DÜŞMÜR, çünki qapı olaraq
        `can_approve_dual_control_override` yoxlanılır və həmin flag anti-fraud
        qaydasına görə ona heç vaxt verilə bilməz.
        """
        operator = self._employees.get(operator_id)
        if operator is None:
            raise OperationNotPermittedError(
                "Əməliyyatı aparan istifadəçi tapılmadı",
                context={"operator_id": str(operator_id)},
            )

        now = self._clock.now()
        if operator.has_permission("can_verify_returns", now=now):
            return
        if record.escalated_at is not None and operator.has_permission(
            DUAL_CONTROL_APPROVAL_FLAG, now=now
        ):
            _log.info(
                "CHECK_IN_TIMEOUT_ACTOR",
                extra={"actor_id": str(operator_id), "record_id": str(record.id)},
            )
            return

        raise OperationNotPermittedError(
            "'can_verify_returns' səlahiyyəti olmadan giriş təsdiqi mümkün deyil",
            user_message="Bu əməliyyat üçün səlahiyyətiniz yoxdur.",
            context={"operator_id": str(operator_id)},
        )

    def _require_operator_scope(self, operator_id: EmployeeId, store_id: StoreId) -> None:
        allowed = self._camera_assignments.stores_for_operator(operator_id)
        if store_id not in allowed:
            raise OperationNotPermittedError(
                "Operator bu mağazaya təyin edilməyib",
                user_message="Bu mağaza sizin nəzarətinizdə deyil.",
                context={"operator_id": str(operator_id), "store_id": str(store_id)},
            )

    def _verified_now(self, tenant_id: TenantId, *, operation: str) -> tuple[datetime, bool]:
        moment, ntp_ok = self._ntp.verified_now()
        if ntp_ok:
            return moment, True

        drift = self._ntp.drift_seconds()
        max_drift = self._limit_int(tenant_id, SystemLimitKey.NTP_MAX_DRIFT_SECONDS)
        if drift is not None and abs(drift) > max_drift:
            raise TimeDriftError(
                f"Saat sürüşməsi {drift:.1f} s — hədd {max_drift} s. '{operation}' bloklandı.",
                context={"drift_seconds": drift, "operation": operation},
            )
        return moment, False

    def _resolve_work_date(self, employee_id: EmployeeId, *, at: datetime) -> date:
        """`work_date` ötürülmədikdə iş gününü TƏYİN EDİR (D10 audit tapıntısı).

        ƏVVƏL sadəcə `at.date()` idi — gecə növbəsi (22:00–06:00) işçisi
        GECƏYARIDAN SONRA daxil olanda YANLIŞ təqvim gününə yazılırdı, çünki
        onun növbəsi ƏVVƏLKİ günə təyin olunub (bax `work_norm.py`: "növbə
        HƏMİŞƏ başladığı günə yazılır"). İki namizəd günün (bugün, dünən)
        HƏLL OLUNMUŞ cədvəlini BİR sorğuda (`schedules_for`, PERF-1/2/3)
        gətirib xalis domen funksiyasına (`resolve_work_date`) ötürür — TƏXMİN
        YOX, DƏQİQ `TimeRange.covers()` yoxlaması (bax funksiyanın öz şərhi).
        """
        today = at.date()
        yesterday = today - timedelta(days=1)
        schedules = self._shifts.schedules_for(employee_id, (today, yesterday))
        return resolve_work_date(at, schedules=schedules)

    def _require_module(self, tenant_id: TenantId, module: FeatureModule) -> None:
        if not self._toggles.is_enabled(tenant_id, module.value):
            raise ModuleDisabledError(
                f"'{module.value}' modulu deaktiv edilib",
                context={"module": module.value},
            )

    def _limit_int(self, tenant_id: TenantId, key: SystemLimitKey) -> int:
        return self._limits.get_int(tenant_id, key.value, int(DEFAULT_LIMITS[key]))


__all__ = ["CheckInOutcome", "MorningCheckInUseCase"]
