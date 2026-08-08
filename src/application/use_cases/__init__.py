"""Use case-lər — Faza 2.

Hər use case bir istifadəçi niyyətini icra edir və domen aqreqatlarını
orkestrasiya edir. Konkret infrastruktur BURADA idxal olunmur — yalnız
`domain.interfaces.ports` portları (DI ilə ötürülür).
"""

from src.application.use_cases.dual_control_guard import (
    DeadlockCheckResult,
    DualControlDeadlockGuardUseCase,
)
from src.application.use_cases.leave_verification import (
    LeaveVerificationUseCase,
    ModuleDisabledError,
    OperationNotPermittedError,
    TimeDriftError,
    VerificationOutcome,
)
from src.application.use_cases.morning_check_in import (
    CheckInOutcome,
    MorningCheckInUseCase,
)
from src.application.use_cases.permission_guards import (
    CONTROL_PERMISSIONS_FLAG,
    PermissionChangeRequest,
    PermissionHierarchyGuardUseCase,
)

__all__ = [
    "CONTROL_PERMISSIONS_FLAG",
    "CheckInOutcome",
    "DeadlockCheckResult",
    "DualControlDeadlockGuardUseCase",
    "LeaveVerificationUseCase",
    "ModuleDisabledError",
    "MorningCheckInUseCase",
    "OperationNotPermittedError",
    "PermissionChangeRequest",
    "PermissionHierarchyGuardUseCase",
    "TimeDriftError",
    "VerificationOutcome",
]
