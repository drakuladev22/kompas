"""DB sətri ↔ domen aqreqatı çevirmələri — Faza 3.2.

QAYDA: domen entity-ləri DB-ni tanımır, ona görə çevirmə BURADA, tək yerdə
saxlanılır. Sütun adı dəyişikliyi yalnız bu faylı toxundurur.

HASH-LƏR ENTITY-DƏ SAXLANILMIR: `pin_hash` və `password_hash` domen
`Employee` obyektinə KEÇMİR — onlar ayrıca `Credentials` DTO-su ilə
qaytarılır. Səbəb: entity log-a, DTO-ya və ya GUI-yə ötürülə bilər; sirr
orada olmamalıdır.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.domain.entities.attendance_record import (
    AttendanceRecord,
    CheckInStatus,
    RejectionDetails,
)
from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.fine import Fine, FineSource, FineStatus
from src.domain.entities.leave_request import (
    LeaveRequest,
    LeaveStatus,
    ManualOverride,
)
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import (
    PermissionEffect,
    RolePriority,
)
from src.domain.value_objects.credentials import EmailAddress, Username
from src.domain.value_objects.identifiers import (
    AttendanceRecordId,
    EmployeeId,
    FineId,
    FineReviewBatchId,
    FineTypeId,
    LeaveRequestId,
    LeaveTypeId,
    PositionId,
    StoreId,
    TenantId,
)
from src.domain.value_objects.money import Money
from src.domain.value_objects.penalty import LeavePenalty

Row = dict[str, Any]


@dataclass(frozen=True)
class Credentials:
    """İşçinin sirr materialı — entity-dən AYRI daşınır.

    `__repr__` maskalanıb: bu obyekt heç vaxt log-a düşməməlidir.
    """

    employee_id: EmployeeId
    pin_hash: str | None
    password_hash: str | None
    pepper_version: int

    def __repr__(self) -> str:  # pragma: no cover - sadə maskalama
        return f"Credentials(employee_id={self.employee_id}, ***REDACTED***)"

    __str__ = __repr__


# --------------------------------------------------------------------------- #
# Position
# --------------------------------------------------------------------------- #


def position_from_row(row: Row) -> Position:
    return Position(
        position_id=PositionId(row["id"]),
        code=row["code"],
        name_az=row["name_az"],
        priority=RolePriority(row["priority"]),
        tenant_id=TenantId(row["tenant_id"]) if row.get("tenant_id") else None,
        is_system=row["is_system"],
        is_camera_type=row["is_camera_type"],
        is_active=row["is_active"],
    )


def apply_position_flags(position: Position, flag_codes: list[str]) -> Position:
    """Rol flag-lərini bərpa edir.

    DİQQƏT: `Position.grant()` qoruyucu qaydaları yoxlayır və DB-dən gələn
    tarixi məlumatı rədd edə bilər (məs. qayda sonradan sərtləşibsə).
    Ona görə burada BİRBAŞA daxili çoxluğa yazılır — DB artıq öz trigger-ləri
    ilə qaydaları tətbiq edib, təkrar yoxlama mövcud məlumatı "oxunmaz" edərdi.
    """
    position._granted_flags.update(flag_codes)
    return position


# --------------------------------------------------------------------------- #
# Employee
# --------------------------------------------------------------------------- #


def employee_from_row(row: Row, position: Position) -> Employee:
    employee = Employee(
        employee_id=EmployeeId(row["id"]),
        tenant_id=TenantId(row["tenant_id"]),
        position=position,
        first_name=row["first_name"],
        last_name=row["last_name"],
        store_id=StoreId(row["store_id"]) if row.get("store_id") else None,
        username=Username.parse(row["username"]) if row.get("username") else None,
        notification_email=(
            EmailAddress.parse(row["notification_email"]) if row.get("notification_email") else None
        ),
        has_password=bool(row.get("password_hash")),
        has_pin=bool(row.get("pin_hash")),
        must_change_password=row.get("must_change_password", False),
        is_active=row.get("is_active", True),
        profile_photo_url=row.get("profile_photo_url"),
        hire_date=row.get("hire_date"),
        date_of_birth=row.get("date_of_birth"),
    )
    employee.pin_security.failed_attempts = row.get("pin_failed_attempts", 0)
    employee.pin_security.locked_until = row.get("pin_locked_until")
    employee.pin_security.pepper_version = row.get("pepper_version", 1)
    return employee


def credentials_from_row(row: Row) -> Credentials:
    return Credentials(
        employee_id=EmployeeId(row["id"]),
        pin_hash=row.get("pin_hash"),
        password_hash=row.get("password_hash"),
        pepper_version=row.get("pepper_version", 1),
    )


def apply_overrides(employee: Employee, rows: list[Row]) -> Employee:
    for row in rows:
        employee.apply_override(
            PermissionOverride(
                flag_code=row["flag_code"],
                effect=PermissionEffect(row["effect"]),
                granted_by=EmployeeId(row["granted_by"]),
                expires_at=row.get("expires_at"),
            )
        )
    return employee


def apply_store_assignments(employee: Employee, store_ids: list[Any]) -> Employee:
    for store_id in store_ids:
        employee.assign_store(StoreId(store_id))
    return employee


# --------------------------------------------------------------------------- #
# LeaveRequest
# --------------------------------------------------------------------------- #


def leave_request_from_row(row: Row, override_row: Row | None = None) -> LeaveRequest:
    request = LeaveRequest(
        request_id=LeaveRequestId(row["id"]),
        tenant_id=TenantId(row["tenant_id"]),
        employee_id=EmployeeId(row["employee_id"]),
        store_id=StoreId(row["store_id"]),
        requested_time=row["requested_time"],
        leave_type_id=LeaveTypeId(row["leave_type_id"]) if row.get("leave_type_id") else None,
        allowance_minutes=row.get("requested_minutes", 0),
        ntp_verified=row.get("requested_ntp_verified", False),
        status=LeaveStatus(row["status"]),
    )
    request.return_claimed_time = row.get("return_claimed_time")
    request.actual_return_time = row.get("actual_return_time")
    request.verified_at = row.get("verified_at")
    request.verified_by = EmployeeId(row["verified_by"]) if row.get("verified_by") else None
    request.escalated_at = row.get("escalated_at")

    if row.get("delay_minutes") is not None and row.get("actual_return_time"):
        request.penalty = LeavePenalty(
            elapsed_minutes=row.get("requested_minutes", 0) + row["delay_minutes"],
            allowance_minutes=row.get("requested_minutes", 0),
            delay_minutes=row["delay_minutes"],
            total_minutes=row.get("total_minutes", 0),
        )

    if override_row is not None:
        # `REJECTED` sətri (M-5): insan rəddi VƏ YA timeout ləğvi. Vaxt möhürü
        # kimi `created_at` işlədilir — sətir append-only yazılır, yəni onun
        # yaradılma anı elə qərarın verildiyi andır. Ayrıca `rejected_at`
        # sütunu əlavə etmək RƏDD EDİLDİ: eyni məlumatın ikinci nüsxəsi
        # olardı və miqrasiya tələb edərdi.
        rejected = override_row["status"] == "REJECTED"
        request.override = ManualOverride(
            operator_id=EmployeeId(override_row["operator_id"]),
            system_time=override_row["system_time"],
            overridden_time=override_row["overridden_time"],
            reason=override_row["reason"],
            delta_minutes=override_row["delta_minutes"],
            requires_dual_control=override_row["status"] in ("PENDING_DUAL_CONTROL", "REJECTED")
            or override_row.get("approved_by") is not None,
            approved_by=EmployeeId(override_row["approved_by"])
            if override_row.get("approved_by")
            else None,
            approved_at=override_row.get("approved_at"),
            rejected_by=EmployeeId(override_row["approved_by"])
            if rejected and override_row.get("approved_by")
            else None,
            rejected_at=override_row.get("created_at") if rejected else None,
            rejection_reason=override_row.get("rejection_reason") if rejected else None,
        )

    # Bərpa edilmiş obyekt YENİ hadisə yaratmamalıdır.
    request.discard_events()
    return request


def leave_request_to_params(request: LeaveRequest) -> dict[str, Any]:
    return {
        "id": request.id,
        "tenant_id": request.tenant_id,
        "employee_id": request.employee_id,
        "store_id": request.store_id,
        "leave_type_id": request.leave_type_id,
        "requested_time": request.requested_time,
        "requested_ntp_verified": request.ntp_verified,
        "return_claimed_time": request.return_claimed_time,
        "actual_return_time": request.actual_return_time,
        "verified_at": request.verified_at,
        "verified_by": request.verified_by,
        "status": request.status.value,
        "requested_minutes": request.allowance_minutes,
        "delay_minutes": request.penalty.delay_minutes if request.penalty else 0,
        "total_minutes": request.penalty.total_minutes
        if request.penalty
        else request.allowance_minutes,
        "was_manual_override": request.override is not None,
        "escalated_at": request.escalated_at,
    }


# --------------------------------------------------------------------------- #
# AttendanceRecord
# --------------------------------------------------------------------------- #


def attendance_from_row(row: Row) -> AttendanceRecord:
    record = AttendanceRecord(
        record_id=AttendanceRecordId(row["id"]),
        tenant_id=TenantId(row["tenant_id"]),
        employee_id=EmployeeId(row["employee_id"]),
        store_id=StoreId(row["store_id"]),
        work_date=row["work_date"],
        status=CheckInStatus(row["check_in_status"]),
    )
    record.requested_at = row.get("requested_at")
    record.verified_at = row.get("verified_at")
    record.verified_by = EmployeeId(row["verified_by"]) if row.get("verified_by") else None
    record.escalated_at = row.get("escalated_at")
    record.ntp_verified = row.get("ntp_verified", False)
    record.is_unauthorized_absence = row.get("is_unauthorized_absence", False)

    if row.get("reject_reason"):
        record.rejection = RejectionDetails(
            operator_id=EmployeeId(row["verified_by"])
            if row.get("verified_by")
            else EmployeeId(row["employee_id"]),
            reason=row["reject_reason"],
            rejected_at=row.get("rejected_at") or row["created_at"],
        )
        record.rejection_count = 1

    record.discard_events()
    return record


def attendance_to_params(record: AttendanceRecord) -> dict[str, Any]:
    lateness = record.lateness
    return {
        "id": record.id,
        "tenant_id": record.tenant_id,
        "employee_id": record.employee_id,
        "store_id": record.store_id,
        "work_date": record.work_date,
        "check_in_status": record.status.value,
        "requested_at": record.requested_at,
        "verified_at": record.verified_at,
        "verified_by": record.verified_by,
        "reject_reason": record.rejection.reason if record.rejection else None,
        "rejected_at": record.rejection.rejected_at if record.rejection else None,
        "is_late": lateness.is_late if lateness else False,
        "late_minutes": lateness.late_minutes if lateness else 0,
        "is_unauthorized_absence": record.is_unauthorized_absence,
        "ntp_verified": record.ntp_verified,
        "escalated_at": record.escalated_at,
    }


# --------------------------------------------------------------------------- #
# Fine
# --------------------------------------------------------------------------- #


def fine_from_row(row: Row) -> Fine:
    fine = Fine(
        fine_id=FineId(row["id"]),
        tenant_id=TenantId(row["tenant_id"]),
        employee_id=EmployeeId(row["employee_id"]),
        store_id=StoreId(row["store_id"]),
        source=FineSource(row["source"]),
        amount=Money(Decimal(str(row["amount"]))),
        issued_at=row["issued_at"],
        fine_type_id=FineTypeId(row["fine_type_id"]) if row.get("fine_type_id") else None,
        leave_request_id=LeaveRequestId(row["leave_request_id"])
        if row.get("leave_request_id")
        else None,
        issued_by=EmployeeId(row["issued_by"]) if row.get("issued_by") else None,
        photo_evidence_url=row.get("photo_evidence_url"),
    )
    # DB-dəki faktiki pəncərə saxlanılır (konstruktor yenidən hesablayır).
    #
    # `appeal_window_hours` ÖTÜRÜLMÜR və bu, qəsdəndir: `fines` cədvəlində belə
    # sütun YOXDUR — nəşr anında hesablanmış NƏTİCƏ (`appeal_window_closes_at`)
    # saxlanılır (miqrasiya 016). Yəni bərpa olunmuş obyektdə sahə sinif
    # defoltunda (72) qalır və bu, YALNIZ `publish()` üçün əhəmiyyətlidir.
    # Həmin yolda dəyər tenant limitindən açıq şəkildə ötürülür
    # (`MonthlyFineReviewUseCase.publish_batch`), ona görə burada sətirdən
    # oxumağa ehtiyac yoxdur. Artıq nəşr olunmuş cərimədə isə aşağıdakı
    # DONDURULMUŞ sütun tək həqiqətdir — onu saatdan yenidən hesablamaq
    # (`published_at + hours`) Root limiti dəyişdikdə işçinin etiraz müddətini
    # RETROAKTİV uzadar/qısaldardı.
    fine.appeal_window_closes_at = row.get("appeal_window_closes_at")
    fine.status = FineStatus(row["status"])
    fine.published_at = row.get("published_at")
    fine.reviewed_by = EmployeeId(row["reviewed_by"]) if row.get("reviewed_by") else None
    fine.review_decision_reason = row.get("review_decision_reason")
    fine.reversed_by = EmployeeId(row["reversed_by"]) if row.get("reversed_by") else None
    fine.reversed_at = row.get("reversed_at")
    fine.reversal_reason = row.get("reversal_reason")
    fine.exported_period = row.get("exported_period")
    # SEC-8: sütun ARTIQ SELECT-dədir (`PostgresFineRepository._SELECT`) —
    # əvvəllər burada heç toxunulmurdu, yəni "bu cərimə hansı partiyada nəşr
    # olundu?" sualı bərpa olunmuş obyektdə HƏMİŞƏ cavabsız qalırdı, halbuki
    # `publish()`/`discard_in_review()` onu yaddaşda düzgün təyin edirdi.
    fine.review_batch_id = (
        FineReviewBatchId(row["review_batch_id"]) if row.get("review_batch_id") else None
    )
    # D7: `idempotency_key` xam `uuid.UUID`-dir (`FineId` kimi domen NewType-i
    # DEYİL) — psycopg sütunu artıq düzgün tiplə qaytarır, çevirməyə ehtiyac
    # yoxdur (bax `fine.py:57`-dəki idxal).
    fine.idempotency_key = row.get("idempotency_key")
    # M-6: TÖRƏMƏ sütun (`fines`-də saxlanmır) — sorğu onu `fine_appeals`
    # üzərindən `EXISTS(...)` ilə hesablayır. Sütun gəlmirsə (məs. yalnız
    # `fines`-i seçən köhnə/xarici sorğu) `False` qalır; həmin yolda export
    # qərarı verilmir, ona görə fail-open riski yaranmır — export namizədləri
    # HƏMİŞƏ `PostgresFineRepository`-nin `_SELECT`-indən gəlir.
    fine.has_open_appeal = bool(row.get("has_open_appeal", False))
    fine.discard_events()
    return fine


def fine_to_params(fine: Fine) -> dict[str, Any]:
    return {
        "id": fine.id,
        "tenant_id": fine.tenant_id,
        "employee_id": fine.employee_id,
        "store_id": fine.store_id,
        "source": fine.source.value,
        "fine_type_id": fine.fine_type_id,
        "leave_request_id": fine.leave_request_id,
        "amount": fine.amount.amount,
        "fine_date": fine.issued_at.date(),
        "issued_by": fine.issued_by,
        "photo_evidence_url": fine.photo_evidence_url,
        "status": fine.status.value,
        "reversed_by": fine.reversed_by,
        "reversed_at": fine.reversed_at,
        "reversal_reason": fine.reversal_reason,
        "appeal_window_closes_at": fine.appeal_window_closes_at,
        "published_at": fine.published_at,
        "reviewed_by": fine.reviewed_by,
        "review_decision_reason": fine.review_decision_reason,
        "exported_period": fine.exported_period,
        # SEC-8: əvvəllər BURADA da YOX idi — `save()` onu heç vaxt bazaya
        # göndərmirdi (bax `PostgresFineRepository.save`-in şərhi).
        "review_batch_id": fine.review_batch_id,
        # D7: ikiqat manual cərimə göndərişinin qarşısını alan açar
        # (migrations/074) — `None` `AUTO_DELAY`/köhnə sətirlər üçün normaldır.
        "idempotency_key": fine.idempotency_key,
    }


def utc_or_none(value: datetime | None) -> datetime | None:
    return value


__all__ = [
    "Credentials",
    "apply_overrides",
    "apply_position_flags",
    "apply_store_assignments",
    "attendance_from_row",
    "attendance_to_params",
    "credentials_from_row",
    "employee_from_row",
    "fine_from_row",
    "fine_to_params",
    "leave_request_from_row",
    "leave_request_to_params",
    "position_from_row",
]
