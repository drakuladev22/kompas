"""Use case-lər — Faza 2.

Hər use case bir istifadəçi niyyətini icra edir və domen aqreqatlarını
orkestrasiya edir. Konkret infrastruktur BURADA idxal olunmur — yalnız
`domain.interfaces.ports` portları (DI ilə ötürülür).
"""

from src.application.use_cases.catalog_management import (
    FINE_TYPES_FLAG,
    LEAVE_TYPES_FLAG,
    WORK_MODES_FLAG,
    CatalogChange,
    CatalogPermissionError,
    FineTypeCatalogUseCase,
    LeaveTypeCatalogUseCase,
    WorkModeCatalogUseCase,
)
from src.application.use_cases.dashboard_layout import (
    WIDGET_CATALOG,
    DashboardLayoutUseCase,
    DashboardView,
    DashboardWidget,
)
from src.application.use_cases.db_switch import (
    SWITCH_DB_FLAG,
    DatabaseSwitchUseCase,
    MigrationReport,
)
from src.application.use_cases.developer_console import (
    CrashDashboard,
    CrashGroup,
    CrashRecord,
    SlaState,
    SupportInbox,
    TicketRecord,
    TicketView,
)
from src.application.use_cases.dual_control_guard import (
    DeadlockCheckResult,
    DualControlDeadlockGuardUseCase,
)
from src.application.use_cases.employee_profile import (
    VIEW_EMPLOYEE_REPORTS_FLAG,
    EmployeeProfileAccessUseCase,
    EmployeeProfileView,
    ProfileAccessDeniedError,
)
from src.application.use_cases.erp_connection import (
    MANAGE_ERP_SERVERS_FLAG,
    ConnectionNotVerifiedError,
    ErpConnectionError,
    ErpConnectionWizardUseCase,
    SaveOutcome,
)
from src.application.use_cases.fine_review import (
    PUBLISH_FINES_FLAG,
    FineDecision,
    FineReviewError,
    MonthlyFineReviewUseCase,
    PublishResult,
    ReviewDecision,
)
from src.application.use_cases.leave_verification import (
    LeaveVerificationUseCase,
    ModuleDisabledError,
    OperationNotPermittedError,
    TimeDriftError,
    VerificationOutcome,
)
from src.application.use_cases.license_status import (
    MANAGE_LICENSE_FLAG,
    LicenseOverview,
    LicenseStatusUseCase,
    LicenseViewError,
    blocked_screen_text,
)
from src.application.use_cases.morning_check_in import (
    CheckInOutcome,
    MorningCheckInUseCase,
)
from src.application.use_cases.payment_reminders import (
    PaymentReminderUseCase,
    ReminderMessage,
    TenantBilling,
)
from src.application.use_cases.permission_guards import (
    CONTROL_PERMISSIONS_FLAG,
    PermissionChangeRequest,
    PermissionHierarchyGuardUseCase,
)
from src.application.use_cases.plugin_management import (
    MANAGE_PLUGINS_FLAG,
    InstalledPlugin,
    PluginManagementUseCase,
)
from src.application.use_cases.reporting import (
    EXPORT_REPORTS_FLAG,
    AttendanceRow,
    BonusPenaltyRow,
    BonusPenaltySelection,
    EmployeeAttendanceFacts,
    EmployeeSalesFacts,
    MonthlyReportUseCase,
    ReportPeriod,
    ReportPermissionError,
)
from src.application.use_cases.root_control import (
    MANAGE_LIMITS_FLAG,
    MANAGE_PERMISSIONS_FLAG,
    LimitView,
    ModuleView,
    RootControlError,
    RootControlUseCase,
    StructuralModuleError,
)
from src.application.use_cases.sales_points import (
    MANAGE_POINTS_FLAG,
    ResetNoticeResult,
    SalesPointsError,
    SalesPointsUseCase,
)
from src.application.use_cases.task_workflow import (
    APPROVE_EVIDENCE_FLAG,
    ASSIGN_TASKS_FLAG,
    EscalationResult,
    TaskDraft,
    TaskWorkflowError,
    TaskWorkflowUseCase,
)
from src.application.use_cases.user_management import (
    MANAGE_EMPLOYEES_FLAG,
    CredentialWriter,
    EmployeeDraft,
    EmployeeNotFoundError,
    UserManagementError,
    UserManagementUseCase,
)

__all__ = [
    "APPROVE_EVIDENCE_FLAG",
    "ASSIGN_TASKS_FLAG",
    "CONTROL_PERMISSIONS_FLAG",
    "EXPORT_REPORTS_FLAG",
    "FINE_TYPES_FLAG",
    "LEAVE_TYPES_FLAG",
    "MANAGE_EMPLOYEES_FLAG",
    "MANAGE_ERP_SERVERS_FLAG",
    "MANAGE_LICENSE_FLAG",
    "MANAGE_LIMITS_FLAG",
    "MANAGE_PERMISSIONS_FLAG",
    "MANAGE_PLUGINS_FLAG",
    "MANAGE_POINTS_FLAG",
    "PUBLISH_FINES_FLAG",
    "SWITCH_DB_FLAG",
    "VIEW_EMPLOYEE_REPORTS_FLAG",
    "WIDGET_CATALOG",
    "WORK_MODES_FLAG",
    "AttendanceRow",
    "BonusPenaltyRow",
    "BonusPenaltySelection",
    "CatalogChange",
    "CatalogPermissionError",
    "CheckInOutcome",
    "ConnectionNotVerifiedError",
    "CrashDashboard",
    "CrashGroup",
    "CrashRecord",
    "CredentialWriter",
    "DashboardLayoutUseCase",
    "DashboardView",
    "DashboardWidget",
    "DatabaseSwitchUseCase",
    "DeadlockCheckResult",
    "DualControlDeadlockGuardUseCase",
    "EmployeeAttendanceFacts",
    "EmployeeDraft",
    "EmployeeNotFoundError",
    "EmployeeProfileAccessUseCase",
    "EmployeeProfileView",
    "EmployeeSalesFacts",
    "ErpConnectionError",
    "ErpConnectionWizardUseCase",
    "EscalationResult",
    "FineDecision",
    "FineReviewError",
    "FineTypeCatalogUseCase",
    "InstalledPlugin",
    "LeaveTypeCatalogUseCase",
    "LeaveVerificationUseCase",
    "LicenseOverview",
    "LicenseStatusUseCase",
    "LicenseViewError",
    "LimitView",
    "MigrationReport",
    "ModuleDisabledError",
    "ModuleView",
    "MonthlyFineReviewUseCase",
    "MonthlyReportUseCase",
    "MorningCheckInUseCase",
    "OperationNotPermittedError",
    "PaymentReminderUseCase",
    "PermissionChangeRequest",
    "PermissionHierarchyGuardUseCase",
    "PluginManagementUseCase",
    "ProfileAccessDeniedError",
    "PublishResult",
    "ReminderMessage",
    "ReportPeriod",
    "ReportPermissionError",
    "ResetNoticeResult",
    "ReviewDecision",
    "RootControlError",
    "RootControlUseCase",
    "SalesPointsError",
    "SalesPointsUseCase",
    "SaveOutcome",
    "SlaState",
    "StructuralModuleError",
    "SupportInbox",
    "TaskDraft",
    "TaskWorkflowError",
    "TaskWorkflowUseCase",
    "TenantBilling",
    "TicketRecord",
    "TicketView",
    "TimeDriftError",
    "UserManagementError",
    "UserManagementUseCase",
    "VerificationOutcome",
    "WorkModeCatalogUseCase",
    "blocked_screen_text",
]
