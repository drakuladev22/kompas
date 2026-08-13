"""Tipləşdirilmiş identifikatorlar.

NİYƏ: sistemdə onlarla UUID sahəsi var (`employee_id`, `store_id`,
`operator_id`, `leave_request_id`, ...). Hamısı sadəcə `UUID` olsaydı, birini
digərinin yerinə ötürmək tip yoxlayıcısından KEÇƏRDİ — və bu, cərimə səhv
işçiyə yazılması kimi maliyyə nəticəli səhvlərə gətirib çıxarardı.

`NewType` ilə hər identifikator ayrıca tipdir: MyPy `EmployeeId` gözlənilən
yerə `StoreId` ötürülməsini XƏTA kimi göstərir, lakin işləmə zamanı əlavə
yük yoxdur (hələ də adi `UUID`-dir).
"""

from __future__ import annotations

import uuid
from typing import NewType

# --- Tenant & təşkilat ------------------------------------------------------ #
TenantId = NewType("TenantId", uuid.UUID)
StoreId = NewType("StoreId", uuid.UUID)
PositionId = NewType("PositionId", uuid.UUID)

# --- İnsanlar --------------------------------------------------------------- #
EmployeeId = NewType("EmployeeId", uuid.UUID)

# --- İş axınları ------------------------------------------------------------ #
LeaveRequestId = NewType("LeaveRequestId", uuid.UUID)
AttendanceRecordId = NewType("AttendanceRecordId", uuid.UUID)
OverrideId = NewType("OverrideId", uuid.UUID)
FineId = NewType("FineId", uuid.UUID)
FineTypeId = NewType("FineTypeId", uuid.UUID)
LeaveTypeId = NewType("LeaveTypeId", uuid.UUID)
AppealId = NewType("AppealId", uuid.UUID)
TaskId = NewType("TaskId", uuid.UUID)
ShiftAssignmentId = NewType("ShiftAssignmentId", uuid.UUID)
ShiftSwapRequestId = NewType("ShiftSwapRequestId", uuid.UUID)
DailySheetId = NewType("DailySheetId", uuid.UUID)
WorkModeId = NewType("WorkModeId", uuid.UUID)
#: Vahid İstisna Jurnalının sətri (#9). Ayrıca tip: istisna sətri işçi, mağaza
#: və cərimə identifikatorları ilə YAN-YANA gəzir və birini digərinin yerinə
#: ötürmək yanlış işçinin qeydini bağlamaq demək olardı.
ExceptionId = NewType("ExceptionId", uuid.UUID)
#: POS Səlahiyyət Siyasəti sətri (#7, kompasos11.md Faza 4) — sənədləşdirmə
#: qeydi. Ayrıca tip: audit yazısındakı `entity_id` işçi ID-si ilə
#: qarışdırılsaydı, "kimin həddi dəyişdi?" sualı səhv cavablanardı.
PosThresholdId = NewType("PosThresholdId", uuid.UUID)
#: Açıq Növbə elanı (#16, kompasos11.md Faza 6). Ayrıca tip: elan İD-si ilə
#: ondan doğan `ShiftAssignmentId` bir-birinə ÇOX YAXIN kontekstdə gəzir
#: (elan tutulanda dərhal təyinat yaranır) və birini digərinin yerinə ötürmək
#: səhv işçinin növbəsini ləğv etmək demək olardı.
OpenShiftPostingId = NewType("OpenShiftPostingId", uuid.UUID)
#: İşçi sənədi/müqaviləsi (#17, kompasos11.md Faza 7). Ayrıca tip: bir işçinin
#: BİRDƏN ÇOX sənəd sətri ola bilər (migrations/020 şərhi — köhnə müqavilə
#: SİLİNMİR), yəni `EmployeeId`-dən fərqli olaraq bu ID sətir-səviyyəlidir və
#: audit `entity_id`-sində işçi ID-si ilə qarışdırılsaydı "hansı sənəd
#: dəyişdi?" sualı cavabsız qalardı.
EmployeeDocumentId = NewType("EmployeeDocumentId", uuid.UUID)
#: Elan (broadcast) sətri (#19, kompasos11.md Faza 8). Ayrıca tip: elanın
#: müəllif ID-si (`created_by`, `EmployeeId`) ilə eyni kontekstdə gəzir və
#: audit `entity_id`-sində qarışdırılsaydı "hansı elan dəyişdi?" sualı
#: cavabsız qalardı.
AnnouncementId = NewType("AnnouncementId", uuid.UUID)
#: Performans qiymətləndirməsi sətri (#20, kompasos11.md Faza 8). Ayrıca tip:
#: eyni sətir həm `EmployeeId` (qiymətləndirilən), həm `reviewer_id`
#: (qiymətləndirən) daşıyır — üçüncü, sətir-səviyyəli ID olmasaydı, audit
#: "hansı QİYMƏTLƏNDİRMƏ dəyişdi?" sualı işçi ID-si ilə qarışa bilərdi.
PerformanceReviewId = NewType("PerformanceReviewId", uuid.UUID)

# --- Dəstək (bölmə 8) ------------------------------------------------------- #
SupportTicketId = NewType("SupportTicketId", uuid.UUID)
SupportMessageId = NewType("SupportMessageId", uuid.UUID)

# --- Satış xalları & mükafat (bölmə 6) -------------------------------------- #
SalesTransactionId = NewType("SalesTransactionId", uuid.UUID)
PointsEntryId = NewType("PointsEntryId", uuid.UUID)
RewardId = NewType("RewardId", uuid.UUID)
RedemptionId = NewType("RedemptionId", uuid.UUID)

# --- İnfrastruktur ---------------------------------------------------------- #
ErpServerId = NewType("ErpServerId", uuid.UUID)
SessionId = NewType("SessionId", uuid.UUID)
PluginId = NewType("PluginId", uuid.UUID)


def new_employee_id() -> EmployeeId:
    return EmployeeId(uuid.uuid4())


def new_tenant_id() -> TenantId:
    return TenantId(uuid.uuid4())


def new_store_id() -> StoreId:
    return StoreId(uuid.uuid4())


def new_position_id() -> PositionId:
    return PositionId(uuid.uuid4())


def new_leave_request_id() -> LeaveRequestId:
    return LeaveRequestId(uuid.uuid4())


def new_attendance_record_id() -> AttendanceRecordId:
    return AttendanceRecordId(uuid.uuid4())


def new_override_id() -> OverrideId:
    return OverrideId(uuid.uuid4())


def new_fine_id() -> FineId:
    return FineId(uuid.uuid4())


def new_task_id() -> TaskId:
    return TaskId(uuid.uuid4())


def new_session_id() -> SessionId:
    return SessionId(uuid.uuid4())


def new_points_entry_id() -> PointsEntryId:
    return PointsEntryId(uuid.uuid4())


def new_redemption_id() -> RedemptionId:
    return RedemptionId(uuid.uuid4())


def new_appeal_id() -> AppealId:
    return AppealId(uuid.uuid4())


def new_shift_assignment_id() -> ShiftAssignmentId:
    return ShiftAssignmentId(uuid.uuid4())


def new_shift_swap_request_id() -> ShiftSwapRequestId:
    return ShiftSwapRequestId(uuid.uuid4())


def new_daily_sheet_id() -> DailySheetId:
    return DailySheetId(uuid.uuid4())


def new_support_ticket_id() -> SupportTicketId:
    return SupportTicketId(uuid.uuid4())


def new_support_message_id() -> SupportMessageId:
    return SupportMessageId(uuid.uuid4())


def new_exception_id() -> ExceptionId:
    return ExceptionId(uuid.uuid4())


def new_pos_threshold_id() -> PosThresholdId:
    return PosThresholdId(uuid.uuid4())


def new_open_shift_posting_id() -> OpenShiftPostingId:
    return OpenShiftPostingId(uuid.uuid4())


def new_employee_document_id() -> EmployeeDocumentId:
    return EmployeeDocumentId(uuid.uuid4())


def new_announcement_id() -> AnnouncementId:
    return AnnouncementId(uuid.uuid4())


def new_performance_review_id() -> PerformanceReviewId:
    return PerformanceReviewId(uuid.uuid4())


__all__ = [
    "AnnouncementId",
    "AppealId",
    "AttendanceRecordId",
    "DailySheetId",
    "EmployeeDocumentId",
    "EmployeeId",
    "ErpServerId",
    "ExceptionId",
    "FineId",
    "FineTypeId",
    "LeaveRequestId",
    "LeaveTypeId",
    "OpenShiftPostingId",
    "OverrideId",
    "PerformanceReviewId",
    "PluginId",
    "PointsEntryId",
    "PosThresholdId",
    "PositionId",
    "RedemptionId",
    "RewardId",
    "SalesTransactionId",
    "SessionId",
    "ShiftAssignmentId",
    "ShiftSwapRequestId",
    "StoreId",
    "SupportMessageId",
    "SupportTicketId",
    "TaskId",
    "TenantId",
    "WorkModeId",
    "new_announcement_id",
    "new_appeal_id",
    "new_attendance_record_id",
    "new_daily_sheet_id",
    "new_employee_document_id",
    "new_employee_id",
    "new_exception_id",
    "new_fine_id",
    "new_leave_request_id",
    "new_open_shift_posting_id",
    "new_override_id",
    "new_performance_review_id",
    "new_points_entry_id",
    "new_pos_threshold_id",
    "new_position_id",
    "new_redemption_id",
    "new_session_id",
    "new_shift_assignment_id",
    "new_shift_swap_request_id",
    "new_store_id",
    "new_support_message_id",
    "new_support_ticket_id",
    "new_task_id",
    "new_tenant_id",
]
