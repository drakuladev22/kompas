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
#: Sahə hesabatı — mağaza auditi VƏ insident bildirişi (#26+#27, kompas1.md
#: Faza 3). VAHİD tip, şablon başına ayrı tip YOX: `field_reports` bir
#: cədvəldir və hesabatın şablonu `type` sütununda yaşayır (Struktur Qərar A).
#: İki tip yaratmaq həmin qərarı KODA sızdırardı — funksiya imzaları
#: "audit ID-si" ilə "insident ID-si" arasında seçim etməli olardı, halbuki
#: hər ikisi eyni cədvəlin eyni sətridir.
FieldReportId = NewType("FieldReportId", uuid.UUID)
#: Sahə hesabatının checklist bəndi (#26). Ayrıca tip: bənd ID-si valideyn
#: hesabatın ID-si ilə EYNİ çağırışda gəzir (foto istinadı bəndə, mətn isə
#: hesabata bağlanır) və birini digərinin yerinə ötürmək səhv bəndi
#: "keçdi" işarələmək demək olardı.
FieldReportItemId = NewType("FieldReportItemId", uuid.UUID)
#: İLLİK məzuniyyət sorğusu (#28, kompas1.md Faza 4). `LeaveRequestId` İLƏ
#: QARIŞDIRILMAMALIDIR VƏ MƏHZ ONA GÖRƏ AYRICA TİPDİR: `LeaveRequestId`
#: GÜNDAXİLİ icazənin (STEP1/STEP2, dəqiqə əsaslı, cərimə doğuran) sətridir,
#: bu isə uzun-müddətli illik haqqın GÜN əsaslı sətri. İkisi eyni ekranda,
#: eyni işçi üçün yan-yana gəzir; `uuid.UUID` kimi eyni tip olsaydılar, birini
#: digərinin yerinə ötürmək gündaxili icazəni "təsdiqlənmiş məzuniyyət" kimi
#: göstərmək və ya balansdan səhv gün çıxmaq demək olardı — mypy bunu tuta
#: bilməzdi (bax `entities/annual_leave.py` başlığı: ÜÇ AYRI KONSEPT).
AnnualLeaveRequestId = NewType("AnnualLeaveRequestId", uuid.UUID)
#: İllik məzuniyyət balansı sətri (#28). İşçi + il üçün BİR sətir olsa da
#: (`UNIQUE (tenant_id, employee_id, year)`), sətrin öz İD-si var və audit
#: `entity_id`-si məhz odur: `EmployeeId` yazılsaydı, "2025-ci ilin balansı"
#: ilə "2026-cı ilin balansı" audit izində fərqlənməzdi.
AnnualLeaveBalanceId = NewType("AnnualLeaveBalanceId", uuid.UUID)
#: Toplu əməliyyat jurnalının sətri (#29, kompas1.md Faza 5, `bulk_import_log`).
#: Ayrıca tip: audit `entity_id`-sində `EmployeeId` ilə qarışdırılsaydı, "hansı
#: TOPLU idxal dəyişdi?" sualı icraçının öz ID-si ilə qarışa bilərdi — halbuki
#: bir icraçı eyni gündə bir neçə toplu idxal apara bilər.
BulkImportLogId = NewType("BulkImportLogId", uuid.UUID)
#: Mağaza şablonu sətri (#29, `store_templates`). Ayrıca tip: `based_on_store_id`
#: (`StoreId`) İLƏ EYNİ çağırışda gəzir (`apply()` mənbə mağazanı OXUYUR, şablonu
#: TƏTBİQ edir) — ikisini qarışdırmaq səhv mağazanı "mənbə" kimi göstərə bilərdi.
StoreTemplateId = NewType("StoreTemplateId", uuid.UUID)
#: Planlaşdırılmış icra xülasəsinin konfiqurasiya sətri (#30, kompas1.md
#: Faza 6, `executive_digest_config`). Ayrıca tip: audit `entity_id`-sində
#: `EmployeeId`/`TenantId` ilə qarışdırılsaydı, "hansı KONFİQURASİYA sətri
#: dəyişdi?" sualı (bir kirayəçidə rol+tezlik başına bir neçə sətir ola bilər)
#: cavabsız qalardı.
ExecutiveDigestConfigId = NewType("ExecutiveDigestConfigId", uuid.UUID)
#: Export-öncəsi ƏL İLƏ düzəliş sətri (HR-D, kompas1.md Faza 8,
#: `export_manual_corrections`). Ayrıca tip: sətir HƏM işçiyə (`employee_id`),
#: HƏM düzəlişi edənə (`corrected_by`) bağlıdır və audit `entity_id`-si məhz
#: DÜZƏLİŞİN özüdür. `EmployeeId` yazılsaydı, "hansı düzəliş geri götürüldü?"
#: sualı cavabsız qalardı — bir işçinin eyni günü üçün bir neçə ardıcıl düzəliş
#: sətri ola bilər (düzəliş DƏYİŞMİR, yenisi YAZILIR — migrations/037 başlığı).
ExportCorrectionId = NewType("ExportCorrectionId", uuid.UUID)
#: Face Control istisnası (`facecontrol.md` bənd 14, `face_control_exemptions`).
#: Ayrıca tip: sətir EYNİ ANDA üç işçi identifikatoru daşıyır — istisnadan
#: yararlanan (`employee_id`), onu verən Root/CEO (`granted_by`) və ləğv edən
#: (`revoked_by`). Dördüncü, SƏTİR-səviyyəli ID olmasaydı, audit `entity_id`-si
#: bunlardan biri ilə qarışar və "hansı istisna ləğv edildi?" sualı cavabsız
#: qalardı (bir işçinin ardıcıl bir neçə istisnası ola bilər — sətirlər heç vaxt
#: silinmir, yalnız `EXPIRED`/`REVOKED` olur).
FaceExemptionId = NewType("FaceExemptionId", uuid.UUID)

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
#: Qeydiyyatdan keçmiş PC (DEVICE-1). Ayrıca tip: cihaz identifikatoru
#: `StoreId` ilə YAN-YANA gəzir (cihaz filiala təyin olunur) və birini
#: digərinin yerinə ötürmək bütün bir filialı bloklamaq demək olardı.
DeviceId = NewType("DeviceId", uuid.UUID)


def new_employee_id() -> EmployeeId:
    return EmployeeId(uuid.uuid4())


def new_tenant_id() -> TenantId:
    return TenantId(uuid.uuid4())


def new_store_id() -> StoreId:
    return StoreId(uuid.uuid4())


def new_device_id() -> DeviceId:
    return DeviceId(uuid.uuid4())


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


def new_field_report_id() -> FieldReportId:
    return FieldReportId(uuid.uuid4())


def new_field_report_item_id() -> FieldReportItemId:
    return FieldReportItemId(uuid.uuid4())


def new_annual_leave_request_id() -> AnnualLeaveRequestId:
    return AnnualLeaveRequestId(uuid.uuid4())


def new_annual_leave_balance_id() -> AnnualLeaveBalanceId:
    return AnnualLeaveBalanceId(uuid.uuid4())


def new_bulk_import_log_id() -> BulkImportLogId:
    return BulkImportLogId(uuid.uuid4())


def new_store_template_id() -> StoreTemplateId:
    return StoreTemplateId(uuid.uuid4())


def new_executive_digest_config_id() -> ExecutiveDigestConfigId:
    return ExecutiveDigestConfigId(uuid.uuid4())


def new_export_correction_id() -> ExportCorrectionId:
    return ExportCorrectionId(uuid.uuid4())


def new_face_exemption_id() -> FaceExemptionId:
    return FaceExemptionId(uuid.uuid4())


__all__ = [
    "AnnouncementId",
    "AnnualLeaveBalanceId",
    "AnnualLeaveRequestId",
    "AppealId",
    "AttendanceRecordId",
    "BulkImportLogId",
    "DailySheetId",
    "DeviceId",
    "EmployeeDocumentId",
    "EmployeeId",
    "ErpServerId",
    "ExceptionId",
    "ExecutiveDigestConfigId",
    "ExportCorrectionId",
    "FaceExemptionId",
    "FieldReportId",
    "FieldReportItemId",
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
    "StoreTemplateId",
    "SupportMessageId",
    "SupportTicketId",
    "TaskId",
    "TenantId",
    "WorkModeId",
    "new_announcement_id",
    "new_annual_leave_balance_id",
    "new_annual_leave_request_id",
    "new_appeal_id",
    "new_attendance_record_id",
    "new_bulk_import_log_id",
    "new_daily_sheet_id",
    "new_device_id",
    "new_employee_document_id",
    "new_employee_id",
    "new_exception_id",
    "new_executive_digest_config_id",
    "new_export_correction_id",
    "new_face_exemption_id",
    "new_field_report_id",
    "new_field_report_item_id",
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
    "new_store_template_id",
    "new_support_message_id",
    "new_support_ticket_id",
    "new_task_id",
    "new_tenant_id",
]
