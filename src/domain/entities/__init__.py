"""Domen aqreqatları — biznes qaydalarının daşıyıcısı.

QAYDA: aqreqat heç vaxt yararsız vəziyyətə keçə bilməz. Hər vəziyyət keçidi
bir metoddur və ön-şərtləri özü yoxlayır — "yoxlamağı unutdum" sinfindən olan
səhvlər struktur olaraq bağlanır.

Hadisələr BİRBAŞA yayımlanmır: `record_event()` ilə toplanır, use case
tranzaksiya uğurla bitdikdən sonra `collect_events()` ilə götürüb yayımlayır
(bax `base.AggregateRoot`).
"""

from src.domain.entities.attendance_record import (
    AttendanceRecord,
    CheckInStatus,
    RejectionDetails,
)
from src.domain.entities.base import (
    AggregateRoot,
    DomainRuleError,
    InvalidStateTransitionError,
    utc_now,
)
from src.domain.entities.employee import (
    ADMIN_TIER_ROLES,
    Employee,
    PermissionOverride,
    PinSecurityState,
)
from src.domain.entities.fine import (
    DEFAULT_APPEAL_WINDOW_HOURS,
    Fine,
    FineSource,
    FineStatus,
)
from src.domain.entities.leave_request import (
    MIN_OVERRIDE_REASON_LENGTH,
    TIMEOUT_RESOLVER_ROLES,
    LeaveRequest,
    LeaveStatus,
    ManualOverride,
)
from src.domain.entities.position import Position

__all__ = [
    "ADMIN_TIER_ROLES",
    "DEFAULT_APPEAL_WINDOW_HOURS",
    "MIN_OVERRIDE_REASON_LENGTH",
    "TIMEOUT_RESOLVER_ROLES",
    "AggregateRoot",
    "AttendanceRecord",
    "CheckInStatus",
    "DomainRuleError",
    "Employee",
    "Fine",
    "FineSource",
    "FineStatus",
    "InvalidStateTransitionError",
    "LeaveRequest",
    "LeaveStatus",
    "ManualOverride",
    "PermissionOverride",
    "PinSecurityState",
    "Position",
    "RejectionDetails",
    "utc_now",
]
