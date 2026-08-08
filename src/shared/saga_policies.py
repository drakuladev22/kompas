"""Saga reconciliation siyasətlərinin AÇIQ reyestri (qərar SEC-003).

PROBLEM (Faza 1 risk siyahısı A3):
    Spesifikasiya bölmə 1 hərfi mənada deyir ki, hər hansı addım uğursuz
    olarsa əməliyyat `PENDING_RECONCILIATION` statusuna keçməlidir — yəni
    kompensasiya UĞURLU olsa belə. Bu, audit-kritik zəncirlər üçün doğrudur,
    lakin BÜTÜN sagalara tətbiq edilsə, adi şəbəkə kəsintiləri də HR-ın
    reconciliation növbəsini doldurar → xəbərdarlıq yorğunluğu (alert fatigue)
    → real problemlər gözdən qaçar.

QƏRAR:
    Siyasət saga-ya görə AÇIQ şəkildə burada təyin olunur. Reyestrdə
    OLMAYAN hər saga defolt olaraq ƏN SƏRT siyasətlə (`ON_ANY_FAILURE`) işləyir
    — yəni yeni saga əlavə edən developer səhvən "yumşaq" rejimə düşə bilməz
    (fail-safe default).

MEYAR:
    `ON_ANY_FAILURE` — əməliyyat pul, davamiyyət qeydi, icazə/rol və ya audit
        izinə toxunursa. Yarımçıq qalması hüquqi/maliyyə nəticəsi doğurur.
    `ON_COMPENSATION_FAILURE` — əməliyyat yalnız köməkçi/təkrarlana bilən
        işdir (bildiriş, keş, telemetriya). Kompensasiya işlədisə insan
        müdaxiləsinə ehtiyac yoxdur.
"""

from __future__ import annotations

from typing import Final

from src.shared.saga_orchestrator import ReconciliationPolicy

# --------------------------------------------------------------------------- #
# Saga adları (SagaOrchestrator.execute(name=...) ilə eyni olmalıdır)
# --------------------------------------------------------------------------- #

SAGA_LEAVE_VERIFICATION: Final[str] = "LeaveVerification"
SAGA_MORNING_CHECK_IN: Final[str] = "MorningCheckIn"
SAGA_MANUAL_TIME_OVERRIDE: Final[str] = "ManualTimeOverride"
SAGA_DUAL_CONTROL_APPROVAL: Final[str] = "DualControlApproval"
SAGA_MANUAL_FINE_ISSUE: Final[str] = "ManualFineIssue"
SAGA_FINE_APPEAL_DECISION: Final[str] = "FineAppealDecision"
SAGA_PERMISSION_CHANGE: Final[str] = "PermissionChange"
SAGA_SHIFT_SWAP_APPROVAL: Final[str] = "ShiftSwapApproval"
SAGA_DB_MIGRATION: Final[str] = "DatabaseMigration"
SAGA_POINTS_CORRECTION: Final[str] = "SalesPointsCorrection"
SAGA_PAYROLL_EXPORT: Final[str] = "PayrollExport"
SAGA_TENANT_PROVISIONING: Final[str] = "TenantProvisioning"

SAGA_NOTIFICATION_DISPATCH: Final[str] = "NotificationDispatch"
SAGA_TELEMETRY_UPLOAD: Final[str] = "TelemetryUpload"
SAGA_CRASH_REPORT_UPLOAD: Final[str] = "CrashReportUpload"
SAGA_PROFILE_PHOTO_UPLOAD: Final[str] = "ProfilePhotoUpload"
SAGA_CHANGELOG_PUSH: Final[str] = "ChangelogPush"


# --------------------------------------------------------------------------- #
# Reyestr
# --------------------------------------------------------------------------- #

#: Audit-kritik: pul, davamiyyət, icazə, audit izi. Hər uğursuzluq insan
#: nəzarətini tələb edir (spesifikasiya bölmə 1-in hərfi tələbi).
AUDIT_CRITICAL_SAGAS: Final[frozenset[str]] = frozenset(
    {
        SAGA_LEAVE_VERIFICATION,
        SAGA_MORNING_CHECK_IN,
        SAGA_MANUAL_TIME_OVERRIDE,
        SAGA_DUAL_CONTROL_APPROVAL,
        SAGA_MANUAL_FINE_ISSUE,
        SAGA_FINE_APPEAL_DECISION,
        SAGA_PERMISSION_CHANGE,
        SAGA_SHIFT_SWAP_APPROVAL,
        SAGA_DB_MIGRATION,
        SAGA_POINTS_CORRECTION,
        SAGA_PAYROLL_EXPORT,
        SAGA_TENANT_PROVISIONING,
    }
)

#: Köməkçi/təkrarlana bilən: kompensasiya işlədisə insan müdaxiləsi lazım deyil.
BEST_EFFORT_SAGAS: Final[frozenset[str]] = frozenset(
    {
        SAGA_NOTIFICATION_DISPATCH,
        SAGA_TELEMETRY_UPLOAD,
        SAGA_CRASH_REPORT_UPLOAD,
        SAGA_PROFILE_PHOTO_UPLOAD,
        SAGA_CHANGELOG_PUSH,
    }
)


def policy_for(saga_name: str) -> ReconciliationPolicy:
    """Saga adına görə reconciliation siyasətini qaytarır.

    Naməlum saga → ƏN SƏRT siyasət (fail-safe default). Yeni saga əlavə edən
    developer reyestrə yazmağı unutsa belə, sistem "sükutla yumşaq" olmur.
    """
    if saga_name in BEST_EFFORT_SAGAS:
        return ReconciliationPolicy.ON_COMPENSATION_FAILURE
    return ReconciliationPolicy.ON_ANY_FAILURE


def assert_registry_is_consistent() -> None:
    """İki dəstin kəsişməməsini yoxlayır (startup/test invariantı)."""
    overlap = AUDIT_CRITICAL_SAGAS & BEST_EFFORT_SAGAS
    if overlap:
        raise ValueError(
            f"Saga siyasət reyestri ziddiyyətlidir — həm audit-kritik, həm "
            f"best-effort kimi işarələnib: {sorted(overlap)}"
        )
