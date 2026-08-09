"""Supabase/PostgreSQL persistence qatı — Faza 3.

SEC-008 MÜQAVİLƏSİ: repository-lərə YALNIZ aktiv `PostgresUnitOfWork`
vasitəsilə çıxmaq olar; UoW `tenant_id` olmadan yaradıla bilmir və tranzaksiya
açılan kimi `SET LOCAL app.tenant_id` icra edir. Kontekstsiz sorğu YAZMAQ
struktur olaraq mümkün deyil.
"""

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
    "PostgresEmployeeRepository",
    "PostgresFineRepository",
    "PostgresLeaveRequestRepository",
    "PostgresPositionRepository",
    "PostgresUnitOfWork",
    "TenantContext",
    "TenantContextError",
    "build_dsn_from_env",
]
