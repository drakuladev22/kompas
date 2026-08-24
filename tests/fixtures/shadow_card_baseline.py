"""`shadow=True` reqressiya qapısının BASELINE-ı — BU FAYL AVTOMATİK YARADILIB.

Əl İLƏ REDAKTƏ ETMƏYİN. Yeniləmək üçün (YALNIZ runtime ölçüsü YAŞIL olandan
SONRA — bax `refresh_shadow_card_baseline.py` başlığı):

    .venv/Scripts/python.exe -m tests.tools.refresh_shadow_card_baseline

Nə üçün bu fayl var: `tests/unit/test_shadow_card_width_gate.py` başlığına
baxın.

──────────────────────────────────────────────────────────────────────────────
BU SAY (ÇAĞIRIŞ YERİ) `tests/e2e/test_shadow_card_width_budget.py`-nin ÖLÇDÜYÜ
SAYDAN (RENDER OLUNAN KART) FƏRQLİDİR — UYĞUNSUZLUQ DEYİL
──────────────────────────────────────────────────────────────────────────────
Bu baseline ÇAĞIRIŞ YERİNƏ görə sayır (bir `shadow=True` sətri = bir giriş).
`group_h.py`-də `_REPORT_CARDS` adlı İKİ elementli dövrə İÇİNDƏ TƏK bir
`shadow=True` çağırışı var — o, İKİ real widget yaradır. Yəni runtime testi
(HƏR RENDER OLUNAN widget-i sayır) bu baseline-dan BİR ARTIQ nəticə görəcək.
Fərq gələcəkdə "bir giriş çatmır" deyə axtarışa səbəb OLMAMALIDIR — bu,
skanın SƏHVİ deyil, İKİ ölçünün TƏBİƏTİDİR (çağırış yeri / real widget sayı).
"""

from __future__ import annotations

from tests.fixtures.shadow_card_scanner import ShadowCardKey

SHADOW_CARD_BASELINE: frozenset[ShadowCardKey] = frozenset(
    {
        ("announcements.py", "AnnouncementComposeDialog", "__init__", 0),
        ("annual_leave.py", "AnnualLeaveRequestDialog", "__init__", 0),
        ("bulk_operations.py", "BulkImportResultDialog", "__init__", 0),
        ("bulk_operations.py", "StoreTemplateApplyDialog", "__init__", 0),
        ("bulk_operations.py", "StoreTemplateCaptureDialog", "__init__", 0),
        ("devices.py", "DeviceAdminScreen", "__init__", 0),
        ("devices.py", "DevicePendingScreen", "__init__", 0),
        ("field_reports.py", "FieldReportScreen", "_build_actions_card", 0),
        ("field_reports.py", "FieldReportScreen", "_build_form_card", 0),
        ("fine_review.py", "PublishConfirmDialog", "__init__", 0),
        ("group_a_entry.py", "AdminLoginScreen", "__init__", 0),
        ("group_a_entry.py", "ConnectionSettingsScreen", "__init__", 0),
        ("group_a_entry.py", "FatalStartupScreen", "__init__", 0),
        ("group_b.py", "FineEntryScreen", "_build_form", 0),
        ("group_b.py", "ManualTimeOverrideDialog", "__init__", 0),
        ("group_c.py", "DashboardScreen", "__init__", 0),
        ("group_c.py", "DashboardScreen", "__init__", 1),
        ("group_c.py", "DashboardScreen", "_build_break_overuse_card", 0),
        ("group_c.py", "DashboardScreen", "_build_outlier_card", 0),
        ("group_c.py", "DashboardScreen", "_build_ranking_card", 0),
        ("group_c.py", "DashboardScreen", "_build_store_vs_network_card", 0),
        ("group_c.py", "DashboardScreen", "_build_trend_card", 0),
        ("group_d.py", "RestoreConfirmDialog", "__init__", 0),
        ("group_e.py", "LicenseInactiveScreen", "__init__", 0),
        ("group_e.py", "SupportChatWidget", "_build_panel", 0),
        ("group_f.py", "NewTaskDialog", "__init__", 0),
        ("group_g.py", "NotificationPanel", "__init__", 0),
        ("group_h.py", "CatalogEntryDialog", "__init__", 0),
        ("group_h.py", "ExportCorrectionDialog", "__init__", 0),
        ("group_h.py", "ReportExportScreen", "__init__", 0),
        ("group_h.py", "ReportExportScreen", "_build_card", 0),
        ("group_i.py", "MigrationConfirmDialog", "__init__", 0),
        ("open_shift.py", "OpenShiftPostDialog", "__init__", 0),
        ("performance_review.py", "PerformanceReviewScreen", "_build_form_card", 0),
        ("performance_review.py", "PerformanceReviewScreen", "_build_history_card", 0),
        ("support_inbox.py", "SupportInboxScreen", "_build_list_panel", 0),
        ("sync_conflicts.py", "SyncConflictScreen", "_build_list_card", 0),
    }
)
