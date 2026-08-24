"""FINAL-UI reqressiya qapısının BASELINE-ı — BU FAYL AVTOMATİK YARADILIB.

Əl İLƏ REDAKTƏ ETMƏYİN. Yeniləmək üçün:

    .venv/Scripts/python.exe -m tests.tools.refresh_ui_baseline

Nə üçün bu fayl var və nəyi qoruyur: `tests/unit/test_ui_screen_regression_
gate.py` başlığına baxın. Məlum ölü elementlər (bu baseline-ın SİLİNMƏSİNƏ
səbəb OLMAYAN, artıq mövcud boşluqlar) `ui_screen_known_dead_elements.py`-
dədir.
"""

from __future__ import annotations

from tests.fixtures.ui_screen_scanner import ScreenClassSignature, ScreenKey

UI_SCREEN_BASELINE: dict[ScreenKey, ScreenClassSignature] = {
    ("announcements.py", "AnnouncementComposeDialog"): ScreenClassSignature(
        signals=("submitted",),
        setters=(),
        connect_count=3,
    ),
    ("announcements.py", "AnnouncementsScreen"): ScreenClassSignature(
        signals=(
            "create_requested",
            "withdraw_requested",
        ),
        setters=("set_announcements",),
        connect_count=2,
    ),
    ("annual_leave.py", "AnnualLeaveInboxScreen"): ScreenClassSignature(
        signals=(
            "approve_requested",
            "reject_requested",
            "refresh_requested",
        ),
        setters=("set_requests",),
        connect_count=3,
    ),
    ("annual_leave.py", "AnnualLeaveRequestDialog"): ScreenClassSignature(
        signals=("submitted",),
        setters=(),
        connect_count=3,
    ),
    ("attrition_risk.py", "AttritionRiskScreen"): ScreenClassSignature(
        signals=("refresh_requested",),
        setters=("set_scores",),
        connect_count=1,
    ),
    ("base.py", "ContentSwitcher"): ScreenClassSignature(
        signals=("reload_requested",),
        setters=("set_content",),
        connect_count=2,
    ),
    ("base.py", "Screen"): ScreenClassSignature(
        signals=("reload_requested",),
        setters=("set_section_error",),
        connect_count=1,
    ),
    ("bulk_operations.py", "BulkImportResultDialog"): ScreenClassSignature(
        signals=(),
        setters=(),
        connect_count=2,
    ),
    ("bulk_operations.py", "BulkOperationsScreen"): ScreenClassSignature(
        signals=(
            "preview_requested",
            "import_requested",
            "capture_requested",
            "apply_requested",
            "deactivate_requested",
        ),
        setters=(
            "set_preview",
            "set_import_message",
            "set_templates",
            "set_template_message",
        ),
        connect_count=6,
    ),
    ("bulk_operations.py", "StoreTemplateApplyDialog"): ScreenClassSignature(
        signals=("submitted",),
        setters=(),
        connect_count=2,
    ),
    ("bulk_operations.py", "StoreTemplateCaptureDialog"): ScreenClassSignature(
        signals=("submitted",),
        setters=(),
        connect_count=2,
    ),
    ("devices.py", "DeviceAdminScreen"): ScreenClassSignature(
        signals=(
            "approve_requested",
            "block_requested",
            "reactivate_requested",
            "reassign_requested",
            "accept_fingerprint_requested",
            "refresh_requested",
        ),
        setters=(
            "set_stores",
            "set_usage",
            "set_pending",
            "set_devices",
        ),
        connect_count=7,
    ),
    ("devices.py", "DevicePendingScreen"): ScreenClassSignature(
        signals=("recheck_requested",),
        setters=(
            "set_device",
            "set_busy",
        ),
        connect_count=1,
    ),
    ("face_control.py", "FaceEnrollmentScreen"): ScreenClassSignature(
        signals=(
            "subject_changed",
            "capture_requested",
            "re_enroll_requested",
            "retake_requested",
            "refresh_requested",
        ),
        setters=(
            "set_employees",
            "set_camera",
            "set_result",
            "set_frames",
            "set_busy",
        ),
        connect_count=5,
    ),
    ("face_control.py", "FaceExemptionScreen"): ScreenClassSignature(
        signals=(
            "grant_requested",
            "revoke_requested",
            "refresh_requested",
        ),
        setters=(
            "set_employees",
            "set_limits",
            "set_exemptions",
        ),
        connect_count=3,
    ),
    ("face_control.py", "FaceSetupRequiredScreen"): ScreenClassSignature(
        signals=(
            "enroll_requested",
            "skipped",
        ),
        setters=(
            "set_employee_name",
            "set_deadline_notice",
            "set_busy",
            "set_error",
        ),
        connect_count=2,
    ),
    ("face_control.py", "FaceVerificationOverlay"): ScreenClassSignature(
        signals=(
            "retry_requested",
            "dismissed",
        ),
        setters=("set_result",),
        connect_count=2,
    ),
    ("field_reports.py", "ChecklistEntry"): ScreenClassSignature(
        signals=(),
        setters=(),
        connect_count=0,
    ),
    ("field_reports.py", "FieldReportFormValues"): ScreenClassSignature(
        signals=(),
        setters=(),
        connect_count=0,
    ),
    ("field_reports.py", "FieldReportScreen"): ScreenClassSignature(
        signals=(
            "submit_requested",
            "progress_requested",
            "close_requested",
        ),
        setters=(
            "set_templates",
            "set_categories",
            "set_stores",
            "set_photo_limit",
            "set_detail_min_length",
            "set_open_reports",
            "set_list_notice",
            "set_form_message",
        ),
        connect_count=16,
    ),
    ("fine_review.py", "FineReviewGroup"): ScreenClassSignature(
        signals=(),
        setters=(),
        connect_count=0,
    ),
    ("fine_review.py", "FineReviewRow"): ScreenClassSignature(
        signals=(),
        setters=(),
        connect_count=0,
    ),
    ("fine_review.py", "MonthlyFineReviewScreen"): ScreenClassSignature(
        signals=(
            "period_selected",
            "refresh_requested",
            "decision_requested",
            "group_decision_requested",
            "publish_requested",
        ),
        setters=(
            "set_periods",
            "set_decision_options",
            "set_groups",
            "set_decision",
        ),
        connect_count=7,
    ),
    ("fine_review.py", "PublishConfirmDialog"): ScreenClassSignature(
        signals=("confirmed",),
        setters=(),
        connect_count=2,
    ),
    ("fine_review.py", "PublishSummary"): ScreenClassSignature(
        signals=(),
        setters=(),
        connect_count=0,
    ),
    ("group_a_entry.py", "AdminLoginScreen"): ScreenClassSignature(
        signals=(
            "submitted",
            "face_login_requested",
        ),
        setters=(
            "set_face_login_available",
            "set_error",
            "set_busy",
        ),
        connect_count=3,
    ),
    ("group_a_entry.py", "ConnectionSettingsScreen"): ScreenClassSignature(
        signals=(
            "submitted",
            "cancelled",
        ),
        setters=(
            "set_diagnostics",
            "populate",
            "set_error",
            "set_status",
            "set_busy",
        ),
        connect_count=3,
    ),
    ("group_a_entry.py", "FatalStartupScreen"): ScreenClassSignature(
        signals=("retry_requested",),
        setters=(),
        connect_count=1,
    ),
    ("group_a_entry.py", "FirstRunWizard"): ScreenClassSignature(
        signals=(
            "completed",
            "cancelled",
        ),
        setters=("set_busy",),
        connect_count=3,
    ),
    ("group_a_entry.py", "SplashScreen"): ScreenClassSignature(
        signals=("finished",),
        setters=("set_status",),
        connect_count=0,
    ),
    ("group_a_entry.py", "_WizardStep"): ScreenClassSignature(
        signals=(),
        setters=("set_state",),
        connect_count=0,
    ),
    ("group_a_kiosk.py", "EmployeeHomeScreen"): ScreenClassSignature(
        signals=(
            "action_requested",
            "photo_change_requested",
            "logout_requested",
            "tasks_requested",
            "rewards_requested",
            "appeal_requested",
            "open_shift_claim_requested",
            "open_shift_release_requested",
            "annual_leave_request_requested",
        ),
        setters=(
            "set_status",
            "set_break_options",
            "set_tasks",
            "set_points",
            "set_fines",
            "set_claimed_shifts",
            "set_open_shifts",
            "set_open_shift_message",
            "set_annual_leave_balance",
            "set_annual_leave_message",
            "set_announcements",
        ),
        connect_count=10,
    ),
    ("group_a_kiosk.py", "PinDots"): ScreenClassSignature(
        signals=(),
        setters=(
            "set_filled",
            "set_error",
            "set_colors",
        ),
        connect_count=0,
    ),
    ("group_a_kiosk.py", "PinPadScreen"): ScreenClassSignature(
        signals=(
            "submitted",
            "face_login_requested",
        ),
        setters=(
            "set_face_login_available",
            "set_clock",
            "set_busy",
        ),
        connect_count=2,
    ),
    ("group_b.py", "FineEntryScreen"): ScreenClassSignature(
        signals=("submitted",),
        setters=(
            "set_price",
            "set_success_message",
            "set_fines",
        ),
        connect_count=1,
    ),
    ("group_b.py", "ManualTimeOverrideDialog"): ScreenClassSignature(
        signals=("submitted",),
        setters=(),
        connect_count=5,
    ),
    ("group_b.py", "OperatorQueueScreen"): ScreenClassSignature(
        signals=(
            "approve_requested",
            "reject_requested",
            "adjust_requested",
            "filter_changed",
            "store_filter_changed",
            "bulk_reject_requested",
        ),
        setters=(
            "set_entries",
            "set_filter",
            "set_store_filter",
        ),
        connect_count=7,
    ),
    ("group_b.py", "PhotoDropZone"): ScreenClassSignature(
        signals=("file_selected",),
        setters=("set_file",),
        connect_count=0,
    ),
    ("group_b.py", "QueueEntry"): ScreenClassSignature(
        signals=(),
        setters=(),
        connect_count=0,
    ),
    ("group_b.py", "QueueRow"): ScreenClassSignature(
        signals=(
            "approve_requested",
            "reject_requested",
            "adjust_requested",
            "selection_changed",
        ),
        setters=(),
        connect_count=4,
    ),
    ("group_c.py", "ChangeRoleDialog"): ScreenClassSignature(
        signals=("submitted",),
        setters=(),
        connect_count=2,
    ),
    ("group_c.py", "DailyRosterScreen"): ScreenClassSignature(
        signals=(
            "approve_requested",
            "draft_saved",
        ),
        setters=(
            "set_stats",
            "set_mismatch",
            "set_rows",
        ),
        connect_count=2,
    ),
    ("group_c.py", "DashboardScreen"): ScreenClassSignature(
        signals=(
            "ranking_metric_changed",
            "ranking_row_selected",
        ),
        setters=(
            "set_layout",
            "set_break_overuse",
            "set_summary",
            "set_network_size",
            "set_fines_by_branch",
            "set_leave_usage",
            "set_leaders",
            "set_server_health",
            "set_ranking_table",
            "set_store_vs_network",
            "set_metric_trend",
            "set_outliers",
        ),
        connect_count=2,
    ),
    ("group_c.py", "EmployeeDocumentDialog"): ScreenClassSignature(
        signals=(
            "document_added",
            "deactivate_requested",
        ),
        setters=("set_documents",),
        connect_count=4,
    ),
    ("group_c.py", "NewUserDialog"): ScreenClassSignature(
        signals=("submitted",),
        setters=(),
        connect_count=3,
    ),
    ("group_c.py", "PermissionMatrixScreen"): ScreenClassSignature(
        signals=(
            "role_selected",
            "saved",
            "role_create_requested",
        ),
        setters=(
            "set_roles",
            "set_active_role",
            "set_matrix",
        ),
        connect_count=5,
    ),
    ("group_c.py", "PosThresholdDialog"): ScreenClassSignature(
        signals=(
            "submitted",
            "revoke_requested",
        ),
        setters=(),
        connect_count=3,
    ),
    ("group_c.py", "RankingEntry"): ScreenClassSignature(
        signals=(),
        setters=(),
        connect_count=0,
    ),
    ("group_c.py", "ResetPasswordDialog"): ScreenClassSignature(
        signals=("submitted",),
        setters=(),
        connect_count=2,
    ),
    ("group_c.py", "ResetPinDialog"): ScreenClassSignature(
        signals=("submitted",),
        setters=(),
        connect_count=2,
    ),
    ("group_c.py", "RoleCreateDialog"): ScreenClassSignature(
        signals=("submitted",),
        setters=(),
        connect_count=2,
    ),
    ("group_c.py", "ShiftPlanningScreen"): ScreenClassSignature(
        signals=(
            "publish_requested",
            "month_changed",
            "open_shift_post_requested",
            "open_shift_cancel_requested",
            "open_shift_release_requested",
            "work_mode_selected",
        ),
        setters=(
            "set_month",
            "set_window_label",
            "set_work_modes",
            "set_work_mode_norm",
            "set_matrix",
            "set_summary",
            "set_open_shift_postings",
            "set_claimed_open_shifts",
            "set_staffing_pattern",
        ),
        connect_count=6,
    ),
    ("group_c.py", "ShiftSwapScreen"): ScreenClassSignature(
        signals=(
            "approved",
            "rejected",
            "selected",
        ),
        setters=(
            "set_counts",
            "set_requests",
            "set_detail",
        ),
        connect_count=3,
    ),
    ("group_c.py", "UsersScreen"): ScreenClassSignature(
        signals=(
            "create_requested",
            "action_requested",
            "search_changed",
            "status_filter_changed",
        ),
        setters=(
            "set_permitted_actions",
            "set_users",
        ),
        connect_count=3,
    ),
    ("group_d.py", "AuditScreen"): ScreenClassSignature(
        signals=(
            "export_requested",
            "filters_changed",
            "page_changed",
        ),
        setters=(
            "set_total",
            "set_entries",
            "set_pagination",
        ),
        connect_count=5,
    ),
    ("group_d.py", "BackupScreen"): ScreenClassSignature(
        signals=(
            "backup_now_requested",
            "restore_requested",
        ),
        setters=(
            "set_schedule_label",
            "set_backups",
            "set_storage",
        ),
        connect_count=2,
    ),
    ("group_d.py", "DriveConnectionScreen"): ScreenClassSignature(
        signals=(
            "connect_requested",
            "cancel_requested",
        ),
        setters=(
            "set_active",
            "set_history",
            "set_connect_message",
        ),
        connect_count=2,
    ),
    ("group_d.py", "ErpServersScreen"): ScreenClassSignature(
        signals=(
            "test_all_requested",
            "create_requested",
            "server_selected",
        ),
        setters=(
            "set_servers",
            "set_mapping",
            "set_last_sync",
        ),
        connect_count=3,
    ),
    ("group_d.py", "HealthScreen"): ScreenClassSignature(
        signals=(
            "recheck_requested",
            "conflicts_requested",
        ),
        setters=(
            "set_last_check",
            "set_metrics",
            "set_latencies",
            "set_alerts",
            "set_conflict_action",
        ),
        connect_count=2,
    ),
    ("group_d.py", "RestoreConfirmDialog"): ScreenClassSignature(
        signals=("confirmed",),
        setters=(),
        connect_count=2,
    ),
    ("group_d.py", "RootControlScreen"): ScreenClassSignature(
        signals=(
            "applied",
            "module_toggled",
            "flag_created",
            "face_scope_changed",
            "branding_changed",
            "telegram_saved",
            "telegram_active_changed",
            "telegram_test_requested",
        ),
        setters=(
            "set_telegram",
            "set_telegram_message",
            "set_telegram_busy",
            "set_branding",
            "set_branding_status",
            "set_face_scope",
            "set_face_tolerance",
            "set_limits",
            "set_break_limits",
            "set_modules",
            "set_module_message",
            "set_registry",
        ),
        connect_count=9,
    ),
    ("group_d.py", "ServerConnectionWizard"): ScreenClassSignature(
        signals=(
            "test_requested",
            "saved",
        ),
        setters=(
            "set_busy",
            "set_test_result",
        ),
        connect_count=4,
    ),
    ("group_d.py", "SettingsScreen"): ScreenClassSignature(
        signals=(
            "theme_selected",
            "notification_changed",
            "password_change_requested",
            "sessions_close_requested",
            "saved",
        ),
        setters=(
            "set_notification_prefs",
            "set_security_info",
            "set_notification",
        ),
        connect_count=5,
    ),
    ("group_d.py", "_ConnectorCard"): ScreenClassSignature(
        signals=(),
        setters=("set_selected",),
        connect_count=0,
    ),
    ("group_d.py", "_TestSpinner"): ScreenClassSignature(
        signals=(),
        setters=(),
        connect_count=1,
    ),
    ("group_e.py", "ChatBubble"): ScreenClassSignature(
        signals=(),
        setters=(),
        connect_count=0,
    ),
    ("group_e.py", "LicenseInactiveScreen"): ScreenClassSignature(
        signals=(),
        setters=(),
        connect_count=0,
    ),
    ("group_e.py", "SupportChatWidget"): ScreenClassSignature(
        signals=(
            "message_sent",
            "opened",
            "closed",
            "channel_selected",
        ),
        setters=("set_unread",),
        connect_count=7,
    ),
    ("group_f.py", "FineAppealInboxScreen"): ScreenClassSignature(
        signals=(
            "accepted",
            "rejected",
        ),
        setters=("set_appeals",),
        connect_count=2,
    ),
    ("group_f.py", "FineAppealScreen"): ScreenClassSignature(
        signals=(
            "appeal_started",
            "appeal_submitted",
        ),
        setters=(
            "set_summary",
            "set_history",
        ),
        connect_count=2,
    ),
    ("group_f.py", "NewTaskDialog"): ScreenClassSignature(
        signals=("submitted",),
        setters=(),
        connect_count=2,
    ),
    ("group_f.py", "SalesPointsScreen"): ScreenClassSignature(
        signals=(
            "appeal_requested",
            "reward_requested",
            "dispute_decided",
        ),
        setters=(
            "set_disputes",
            "set_balance",
            "set_history",
            "set_catalog",
        ),
        connect_count=4,
    ),
    ("group_f.py", "TaskCard"): ScreenClassSignature(
        signals=(
            "approved",
            "rejected",
        ),
        setters=(),
        connect_count=2,
    ),
    ("group_f.py", "TasksScreen"): ScreenClassSignature(
        signals=(
            "create_requested",
            "approved",
            "rejected",
        ),
        setters=(
            "set_summary",
            "set_tasks",
        ),
        connect_count=3,
    ),
    ("group_f.py", "UnassignedSalesScreen"): ScreenClassSignature(
        signals=(
            "rematch_requested",
            "assigned",
            "bulk_assign_requested",
        ),
        setters=(
            "set_low_confidence_threshold",
            "set_sales",
        ),
        connect_count=3,
    ),
    ("group_g.py", "NotificationItem"): ScreenClassSignature(
        signals=("clicked",),
        setters=(),
        connect_count=0,
    ),
    ("group_g.py", "NotificationPanel"): ScreenClassSignature(
        signals=(
            "notification_clicked",
            "mark_all_read_requested",
            "see_all_requested",
            "filter_changed",
        ),
        setters=(
            "set_notifications",
            "set_filter",
        ),
        connect_count=4,
    ),
    ("group_g.py", "ProfileScreen"): ScreenClassSignature(
        signals=(
            "saved",
            "photo_change_requested",
            "password_change_requested",
            "close_other_sessions_requested",
        ),
        setters=(
            "set_face_enrollment",
            "set_performance_history",
            "set_account",
            "set_role_info",
            "set_sessions",
            "set_identity",
        ),
        connect_count=5,
    ),
    ("group_h.py", "CatalogEntryDialog"): ScreenClassSignature(
        signals=("submitted",),
        setters=(),
        connect_count=2,
    ),
    ("group_h.py", "CatalogScreen"): ScreenClassSignature(
        signals=(
            "create_requested",
            "edit_requested",
            "toggle_requested",
        ),
        setters=("set_entries",),
        connect_count=3,
    ),
    ("group_h.py", "ExportCorrectionDialog"): ScreenClassSignature(
        signals=("submitted",),
        setters=(),
        connect_count=2,
    ),
    ("group_h.py", "HelpCenterScreen"): ScreenClassSignature(
        signals=(
            "topic_selected",
            "support_requested",
        ),
        setters=("set_visible_topics",),
        connect_count=2,
    ),
    ("group_h.py", "HelpTopicCard"): ScreenClassSignature(
        signals=(),
        setters=(),
        connect_count=0,
    ),
    ("group_h.py", "ReportExportScreen"): ScreenClassSignature(
        signals=(
            "preflight_requested",
            "export_requested",
            "role_filter_changed",
            "range_changed",
            "correction_requested",
        ),
        setters=(
            "set_period",
            "set_lock_summary",
            "set_range_selection",
            "set_range_message",
            "set_role_options",
            "set_row_values",
            "set_validation_findings",
            "set_period_comparison",
            "set_corrections",
            "set_correction_access",
            "set_preflight_message",
        ),
        connect_count=6,
    ),
    ("group_h.py", "TopicChip"): ScreenClassSignature(
        signals=("clicked",),
        setters=(),
        connect_count=0,
    ),
    ("group_i.py", "DashboardBuilderScreen"): ScreenClassSignature(
        signals=(
            "layout_changed",
            "reset_requested",
        ),
        setters=("set_widgets",),
        connect_count=4,
    ),
    ("group_i.py", "ExceptionsScreen"): ScreenClassSignature(
        signals=(
            "reviewed_requested",
            "dismissed_requested",
        ),
        setters=("set_exceptions",),
        connect_count=2,
    ),
    ("group_i.py", "InfrastructureScreen"): ScreenClassSignature(
        signals=(
            "switch_requested",
            "history_requested",
        ),
        setters=(
            "set_active_target",
            "set_warnings",
            "set_phase_state",
            "set_history",
        ),
        connect_count=2,
    ),
    ("group_i.py", "MigrationConfirmDialog"): ScreenClassSignature(
        signals=("confirmed",),
        setters=(),
        connect_count=2,
    ),
    ("group_i.py", "PhaseRow"): ScreenClassSignature(
        signals=(),
        setters=("set_state",),
        connect_count=0,
    ),
    ("group_i.py", "PluginPageScreen"): ScreenClassSignature(
        signals=(),
        setters=("set_rows",),
        connect_count=0,
    ),
    ("group_i.py", "PluginScreen"): ScreenClassSignature(
        signals=(
            "install_requested",
            "toggle_requested",
            "remove_requested",
        ),
        setters=("set_plugins",),
        connect_count=4,
    ),
    ("group_i.py", "WidgetRow"): ScreenClassSignature(
        signals=(
            "toggled",
            "moved",
            "placement_changed",
        ),
        setters=("set_visible_state",),
        connect_count=5,
    ),
    ("open_shift.py", "OpenShiftMarketCard"): ScreenClassSignature(
        signals=(
            "post_requested",
            "cancel_requested",
            "release_requested",
        ),
        setters=(
            "set_postings",
            "set_claimed",
        ),
        connect_count=3,
    ),
    ("open_shift.py", "OpenShiftPostDialog"): ScreenClassSignature(
        signals=("submitted",),
        setters=(),
        connect_count=2,
    ),
    ("performance_review.py", "PerformanceReviewScreen"): ScreenClassSignature(
        signals=(
            "employee_selected",
            "submit_requested",
        ),
        setters=(
            "set_employees",
            "set_kpi_catalog",
            "set_period",
            "set_history",
        ),
        connect_count=2,
    ),
    ("recovery_console.py", "RecoveryConsoleScreen"): ScreenClassSignature(
        signals=(
            "test_requested",
            "save_requested",
            "check_tables_requested",
            "provision_requested",
            "open_logs_requested",
            "open_config_requested",
            "closed",
        ),
        setters=(
            "populate",
            "set_diagnostics",
            "set_failure_reason",
            "set_status",
            "set_error",
            "set_busy",
            "set_progress",
        ),
        connect_count=7,
    ),
    ("support_inbox.py", "SupportInboxScreen"): ScreenClassSignature(
        signals=(
            "thread_selected",
            "reply_requested",
            "status_change_requested",
            "filters_changed",
            "refresh_requested",
            "attachment_requested",
        ),
        setters=(
            "set_stores",
            "set_positions",
            "set_status_counts",
            "set_threads",
            "set_thread",
            "set_message",
        ),
        connect_count=17,
    ),
    ("sync_conflicts.py", "SyncConflictScreen"): ScreenClassSignature(
        signals=(
            "conflict_selected",
            "resolve_requested",
            "refresh_requested",
        ),
        setters=(
            "set_conflicts",
            "set_comparison",
            "set_resolutions",
            "set_note_min_length",
        ),
        connect_count=4,
    ),
}
