"""Supabase/PostgreSQL persistence qatı — Faza 3.

SEC-008 MÜQAVİLƏSİ: repository-lərə YALNIZ aktiv `PostgresUnitOfWork`
vasitəsilə çıxmaq olar; UoW `tenant_id` olmadan yaradıla bilmir və tranzaksiya
açılan kimi `SET LOCAL app.tenant_id` icra edir. Kontekstsiz sorğu YAZMAQ
struktur olaraq mümkün deyil.
"""

from src.infrastructure.persistence.catalog_repositories import (
    PostgresFineTypeRepository,
    PostgresRewardRepository,
    PostgresSalesPointsRepository,
    PostgresTaskRepository,
    PostgresWorkModeRepository,
)
from src.infrastructure.persistence.config_repositories import (
    PostgresCameraAssignmentRepository,
    PostgresFeatureToggles,
    PostgresLeaveTypeRepository,
    PostgresPermissionFlagRepository,
    PostgresShiftRepository,
    PostgresSystemLimits,
)
from src.infrastructure.persistence.connection import (
    Database,
    DatabaseError,
    PostgresUnitOfWork,
    TenantContext,
    TenantContextError,
    build_dsn_from_env,
)
from src.infrastructure.persistence.mappers import Credentials
from src.infrastructure.persistence.repositories import (
    PostgresAttendanceRepository,
    PostgresEmployeeRepository,
    PostgresFineRepository,
    PostgresLeaveRequestRepository,
    PostgresPositionRepository,
)

__all__ = [
    "Credentials",
    "Database",
    "DatabaseError",
    "PostgresAttendanceRepository",
    "PostgresCameraAssignmentRepository",
    "PostgresEmployeeRepository",
    "PostgresFeatureToggles",
    "PostgresFineRepository",
    "PostgresFineTypeRepository",
    "PostgresLeaveRequestRepository",
    "PostgresLeaveTypeRepository",
    "PostgresPermissionFlagRepository",
    "PostgresPositionRepository",
    "PostgresRewardRepository",
    "PostgresSalesPointsRepository",
    "PostgresShiftRepository",
    "PostgresSystemLimits",
    "PostgresTaskRepository",
    "PostgresUnitOfWork",
    "PostgresWorkModeRepository",
    "TenantContext",
    "TenantContextError",
    "build_dsn_from_env",
]
