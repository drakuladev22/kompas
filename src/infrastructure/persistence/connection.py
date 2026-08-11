"""DB bağlantısı və Unit of Work (spesifikasiya bölmə 2, SEC-008) — Faza 3.1.

──────────────────────────────────────────────────────────────────────────────
ƏSAS DİZAYN QƏRARI: RLS KONTEKSTİNİ UNUTMAQ MÜMKÜN DEYİL
──────────────────────────────────────────────────────────────────────────────
SEC-008 müqaviləsi tələb edir ki, HƏR tranzaksiya `SET LOCAL app.tenant_id`
icra etsin. Sənədə yazmaq kifayət deyil — bir yerdə unudulsa, fail-closed
siyasət sorğuları sükutla BOŞ qaytaracaq və səbəbi tapmaq çətin olacaq.

Ona görə burada struktur həll tətbiq olunur:

    * Repository-lərə YALNIZ aktiv `UnitOfWork` vasitəsilə çıxmaq olar.
    * `UnitOfWork` `tenant_id` OLMADAN yaradıla bilmir (konstruktor tələbi).
    * Tranzaksiya açılan kimi `SET LOCAL` avtomatik icra olunur.
    * `SET LOCAL` (adi `SET` YOX) — connection pool-da dəyər növbəti
      istifadəçiyə SIZMIR.

Yəni "kontekst təyin etməyi unutmaq" üçün proqramçı bilərəkdən repo-nu
UoW-dan kənarda yaratmalıdır — bu isə tip səviyyəsində görünür.

──────────────────────────────────────────────────────────────────────────────
BAĞLANTI: SESSION POOLER
──────────────────────────────────────────────────────────────────────────────
Supabase-in BİRBAŞA host-u (`db.<ref>.supabase.co`) yalnız IPv6-dır və IPv4
şəbəkələrindən (mağaza PC-ləri daxil) ÇATMIR. Session Pooler istifadə olunur:
`aws-0-<region>.pooler.supabase.com:5432`, user `postgres.<ref>` və ya
`kompasos_app.<ref>`.

Tətbiq `postgres` DEYİL, `kompasos_app` rolu ilə qoşulmalıdır (SEC-009) —
owner RLS və append-only trigger-lərini yan keçir.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Any, Final, cast
from urllib.parse import urlparse

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from src.domain.value_objects.identifiers import EmployeeId, TenantId
from src.shared.exceptions import ConfigurationError, KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

SCHEMA: Final[str] = "kompasos"
DEFAULT_POOL_MIN: Final[int] = 1
DEFAULT_POOL_MAX: Final[int] = 8
DEFAULT_TIMEOUT_SECONDS: Final[float] = 15.0

#: Owner rolları — bunlarla qoşulmaq RLS-i yan keçir (yalnız miqrasiya üçün).
OWNER_ROLE_PREFIXES: Final[tuple[str, ...]] = ("postgres", "supabase_admin")


class DatabaseError(KompasOSError):
    """DB əməliyyatı uğursuz oldu."""

    user_message = "Verilənlər bazası ilə əlaqədə problem yarandı."


class TenantContextError(KompasOSError):
    """Tenant konteksti olmadan məlumata müraciət cəhdi."""

    user_message = "Daxili konfiqurasiya xətası. Administratorla əlaqə saxlayın."


@dataclass(frozen=True)
class TenantContext:
    """Bir tranzaksiyanın tenant/istifadəçi konteksti."""

    tenant_id: TenantId
    user_id: EmployeeId | None = None

    def as_settings(self) -> dict[str, str]:
        settings = {"app.tenant_id": str(self.tenant_id)}
        if self.user_id is not None:
            settings["app.user_id"] = str(self.user_id)
        return settings


def build_dsn_from_env() -> str:
    """`DATABASE_URL`-dən DSN qurur və owner rolu ilə qoşulmanı xəbərdarlıqla qeyd edir."""
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        raise ConfigurationError(
            "`DATABASE_URL` təyin edilməyib",
            context={"hint": "Session Pooler DSN-i istifadə edin, birbaşa host YOX"},
        )

    parsed = urlparse(dsn)
    username = (parsed.username or "").split(".")[0]
    if username.startswith(OWNER_ROLE_PREFIXES):
        # SEC-009: owner RLS-dən azaddır — istehsalatda bu, çox-tenant
        # izolyasiyasının tam itməsi deməkdir.
        _security_log.critical(
            "DB_CONNECTED_AS_OWNER",
            extra={
                "role": username,
                "impact": "RLS və append-only trigger-ləri YAN KEÇİLİR",
                "action": "kompasos_app rolundan istifadə edin (SEC-009)",
            },
        )
    if parsed.hostname and parsed.hostname.startswith("db."):
        _log.warning(
            "DB_DIRECT_HOST_IN_USE",
            extra={
                "host": parsed.hostname,
                "impact": "birbaşa host yalnız IPv6-dır — IPv4 şəbəkələrindən çatmır",
                "action": "aws-0-<region>.pooler.supabase.com istifadə edin",
            },
        )
    return dsn


class Database:
    """Bağlantı pool-unun sahibi. Tətbiqdə TƏK nüsxə (DI singleton)."""

    def __init__(
        self,
        dsn: str | None = None,
        *,
        admin_dsn: str | None = None,
        min_size: int = DEFAULT_POOL_MIN,
        max_size: int = DEFAULT_POOL_MAX,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        open_pool: bool = True,
    ) -> None:
        """
        Args:
            dsn: Tətbiq bağlantısı — `kompasos_app` rolu, RLS-ə TABEDİR.
            admin_dsn: İSTƏYƏ BAĞLI owner bağlantısı (`postgres`). YALNIZ
                tenant yaratma/miqrasiya kimi provisioning əməliyyatları
                üçün. Verilməzsə `system_scope()` tətbiq bağlantısını
                istifadə edir və tenant-a aid cədvəllər GÖRÜNMÜR (RLS).
                İstehsalatda bu adətən `None` olmalıdır — owner credential-ı
                işləyən tətbiqdə saxlamaq lazımsız risk yaradır.
        """
        self._dsn = dsn or build_dsn_from_env()
        self._admin_dsn = admin_dsn or os.environ.get("DATABASE_ADMIN_URL") or None
        self._pool = self._make_pool(self._dsn, min_size, max_size, timeout)
        self._admin_pool = (
            self._make_pool(self._admin_dsn, 1, 2, timeout) if self._admin_dsn else None
        )
        if open_pool:
            self.open()

    @staticmethod
    def _make_pool(dsn: str, min_size: int, max_size: int, timeout: float) -> ConnectionPool:
        return ConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout,
            open=False,
            kwargs={
                "row_factory": dict_row,
                "autocommit": False,
                "options": f"-c search_path={SCHEMA},public",
            },
        )

    def open(self) -> None:
        self._pool.open(wait=True, timeout=DEFAULT_TIMEOUT_SECONDS)
        if self._admin_pool is not None:
            self._admin_pool.open(wait=True, timeout=DEFAULT_TIMEOUT_SECONDS)
            _security_log.warning(
                "DB_ADMIN_POOL_OPENED",
                extra={
                    "impact": "owner bağlantısı mövcuddur — RLS yan keçilə bilər",
                    "action": "istehsalatda admin_dsn təyin edilməməlidir",
                },
            )
        _log.info("DB_POOL_OPENED", extra={"schema": SCHEMA})

    def close(self) -> None:
        self._pool.close()
        if self._admin_pool is not None:
            self._admin_pool.close()
        _log.info("DB_POOL_CLOSED")

    @property
    def has_admin_access(self) -> bool:
        return self._admin_pool is not None

    def unit_of_work(
        self, tenant_id: TenantId, *, user_id: EmployeeId | None = None
    ) -> PostgresUnitOfWork:
        """Tenant konteksti ilə yeni Unit of Work.

        `tenant_id` MƏCBURİDİR — RLS kontekstini unutmaq mümkün deyil.
        """
        return PostgresUnitOfWork(self._pool, TenantContext(tenant_id=tenant_id, user_id=user_id))

    @contextmanager
    def system_scope(self) -> Iterator[Connection[dict[str, Any]]]:
        """Tenant-dan KƏNAR cədvəllər üçün bağlantı (RLS konteksti YOXDUR).

        ──────────────────────────────────────────────────────────────────
        ADLANDIRMA QEYDİ: bu metod əvvəl `privileged()` adlanırdı — YANILDICI
        ad idi. O, heç bir imtiyaz VERMİR: tətbiq rolu hələ də RLS-ə tabedir.
        Sadəcə `app.tenant_id` təyin edilmir.
        ──────────────────────────────────────────────────────────────────

        Nəticə: tenant-a aid cədvəllər (employees, leave_requests, ...) BOŞ
        görünür — bu, fail-closed siyasətin düzgün işləməsidir, səhv deyil.

        İSTİFADƏ SAHƏSİ: yalnız tenant-a aid OLMAYAN cədvəllər —
        `license_tenants`, `permission_flags`, `scheduled_job_runs`,
        `crash_reports`.

        `admin_dsn` verilibsə owner bağlantısı istifadə olunur (provisioning,
        miqrasiya, test setup) və bu, ayrıca KRİTİK log yazısı yaradır.
        """
        if self._admin_pool is not None:
            _security_log.warning(
                "DB_ADMIN_CONNECTION_USED",
                extra={"impact": "RLS yan keçilir", "schema": SCHEMA},
            )
            with self._admin_pool.connection() as conn:
                yield cast("Connection[dict[str, Any]]", conn)
                return

        _log.debug("DB_SYSTEM_SCOPE", extra={"schema": SCHEMA})
        with self._pool.connection() as conn:
            yield cast("Connection[dict[str, Any]]", conn)

    def health_check(self) -> bool:
        """System Health Monitor üçün sadə DB ping (bölmə 6)."""
        try:
            with self._pool.connection() as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
                return cur.fetchone() is not None
        except psycopg.Error as exc:
            _log.error("DB_HEALTH_CHECK_FAILED", extra={"error": str(exc)})
            return False


class PostgresUnitOfWork:
    """Tranzaksiya sərhədi + repository-lərə yeganə giriş nöqtəsi.

    İstifadə::

        with db.unit_of_work(tenant_id, user_id=actor_id) as uow:
            employee = uow.employees.get(employee_id)
            uow.employees.save(employee)
            uow.commit()          # açıq commit — unutmaq rollback deməkdir

    `commit()` çağırılmazsa tranzaksiya GERİ QAYTARILIR. Bu, qəsdəndir:
    "yadımdan çıxdı" halında yarımçıq yazı qalmasın.
    """

    def __init__(self, pool: ConnectionPool, context: TenantContext) -> None:
        self._pool = pool
        self._context = context
        self._conn: Connection[dict[str, Any]] | None = None
        self._committed = False
        self._entered = False
        # Repo-lar `__enter__`-də qurulur — UoW-dan kənarda mövcud deyillər.
        self._repositories: dict[str, Any] = {}

    # ------------------------------ kontekst -------------------------------- #

    def __enter__(self) -> PostgresUnitOfWork:
        # `row_factory=dict_row` pool `kwargs`-ında təyin olunub, lakin
        # `ConnectionPool` generic parametri bunu statik bilmir — cast bunu
        # sənədləşdirir.
        conn = cast("Connection[dict[str, Any]]", self._pool.getconn())
        self._conn = conn
        self._entered = True
        self._committed = False
        try:
            conn.execute("BEGIN")
            self._apply_tenant_context()
            self._build_repositories()
        except Exception:
            self._release(rollback=True)
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # Açıq commit yoxdursa GERİ QAYTARILIR — sükutla yarımçıq yazı olmaz.
        self._release(rollback=not self._committed or exc_type is not None)

    def _apply_tenant_context(self) -> None:
        """SEC-008: `SET LOCAL` — pool-da növbəti istifadəçiyə sızmır."""
        if self._conn is None:  # pragma: no cover - invariant
            raise TenantContextError("Bağlantı yoxdur")
        for key, value in self._context.as_settings().items():
            # `SET LOCAL` parametr bind-i dəstəkləmir, ona görə `set_config()`
            # istifadə olunur — dəyər hələ də PARAMETRLƏŞDİRİLMİŞDİR (bölmə 2:
            # "100% Parameterized SQL Queries"), sətir birləşdirmə YOXDUR.
            self._conn.execute("SELECT set_config(%s, %s, true)", (key, value))

    def _build_repositories(self) -> None:
        # Dövri idxaldan qaçmaq üçün yerli idxal (repo-lar bu modulu tanıyır).
        from src.infrastructure.persistence.audit import (  # noqa: PLC0415
            PostgresAuditReader,
            PostgresAuditTrail,
        )
        from src.infrastructure.persistence.catalog_repositories import (  # noqa: PLC0415
            PostgresFineTypeRepository,
            PostgresRewardRepository,
            PostgresSalesPointsRepository,
            PostgresTaskRepository,
            PostgresWorkModeRepository,
        )
        from src.infrastructure.persistence.config_repositories import (  # noqa: PLC0415
            PostgresCameraAssignmentRepository,
            PostgresFeatureToggles,
            PostgresLeaveTypeRepository,
            PostgresPermissionFlagRepository,
            PostgresShiftRepository,
            PostgresStoreWriter,
            PostgresSystemLimits,
        )
        from src.infrastructure.persistence.migration import (  # noqa: PLC0415
            PostgresMigrationEventLog,
            SessionReadOnlyController,
        )
        from src.infrastructure.persistence.notification_repositories import (  # noqa: PLC0415
            PostgresNotificationRepository,
        )
        from src.infrastructure.persistence.platform_repositories import (  # noqa: PLC0415
            PostgresBackupCatalog,
            PostgresPluginRegistry,
        )
        from src.infrastructure.persistence.preferences import (  # noqa: PLC0415
            PostgresUserPreferences,
        )
        from src.infrastructure.persistence.report_repositories import (  # noqa: PLC0415
            PostgresReportFactProvider,
        )
        from src.infrastructure.persistence.repositories import (  # noqa: PLC0415
            PostgresAttendanceRepository,
            PostgresEmployeeRepository,
            PostgresFineRepository,
            PostgresLeaveRequestRepository,
            PostgresPositionRepository,
        )
        from src.infrastructure.persistence.support_repositories import (  # noqa: PLC0415
            PostgresSupportTicketRepository,
        )
        from src.infrastructure.persistence.sync_conflict_repository import (  # noqa: PLC0415
            PostgresSyncConflictRepository,
        )
        from src.infrastructure.persistence.workflow_repositories import (  # noqa: PLC0415
            PostgresAttendanceFactProvider,
            PostgresDailyAttendanceSheetRepository,
            PostgresFineAppealRepository,
            PostgresShiftSwapRepository,
        )

        if self._conn is None:  # pragma: no cover - invariant
            raise TenantContextError("Bağlantı yoxdur")
        conn = self._conn
        # HAMISI EYNİ BAĞLANTIDADIR — bu, təsadüf deyil: bir use case bir neçə
        # repo-ya toxunur (məs. icazə təsdiqi status + cərimə + audit yazır) və
        # onlar EYNİ tranzaksiyada olmalıdır. Ayrı bağlantı işlətsəydik,
        # `commit()` yalnız birini yazar, digəri asılı qalardı.
        self._repositories = {
            "employees": PostgresEmployeeRepository(conn, self._context),
            "positions": PostgresPositionRepository(conn, self._context),
            "leave_requests": PostgresLeaveRequestRepository(conn, self._context),
            "attendance": PostgresAttendanceRepository(conn, self._context),
            "fines": PostgresFineRepository(conn, self._context),
            # Audit iş vahidinin İÇİNDƏDİR: yazı onu doğuran əməliyyatla eyni
            # tranzaksiyada olmalıdır (bax `audit.py` başlığı).
            "audit": PostgresAuditTrail(conn),
            "audit_reader": PostgresAuditReader(conn),
            # --- Faza 5/6 qatları --------------------------------------------
            "shifts": PostgresShiftRepository(conn, self._context),
            "shift_swaps": PostgresShiftSwapRepository(conn, self._context),
            "sheets": PostgresDailyAttendanceSheetRepository(conn, self._context),
            "attendance_facts": PostgresAttendanceFactProvider(conn, self._context),
            "appeals": PostgresFineAppealRepository(conn, self._context),
            "tasks": PostgresTaskRepository(conn, self._context),
            "sales_points": PostgresSalesPointsRepository(conn, self._context),
            "rewards": PostgresRewardRepository(conn, self._context),
            "work_modes": PostgresWorkModeRepository(conn, self._context),
            "fine_types": PostgresFineTypeRepository(conn, self._context),
            "leave_types": PostgresLeaveTypeRepository(conn, self._context),
            "limits": PostgresSystemLimits(conn, self._context),
            "toggles": PostgresFeatureToggles(conn, self._context),
            "permission_flags": PostgresPermissionFlagRepository(conn, self._context),
            "camera_assignments": PostgresCameraAssignmentRepository(conn, self._context),
            "stores": PostgresStoreWriter(conn, self._context),
            "preferences": PostgresUserPreferences(conn, self._context),
            "report_facts": PostgresReportFactProvider(conn, self._context),
            "support": PostgresSupportTicketRepository(conn, self._context),
            "sync_conflicts": PostgresSyncConflictRepository(conn, self._context),
            # Bildirişin YAZISI `PostgresNotifier`-dədir (öz tranzaksiyası ilə);
            # burada qeydiyyatdan keçən yalnız OXU və "oxundu" işarəsidir.
            "notifications": PostgresNotificationRepository(conn, self._context),
            # --- Platforma vəziyyəti (Faza 5/6 ekran bağlantısı) --------------
            # Plugin reyestri və nüsxə kataloqu EYNİ bağlantıdadır, çünki hər
            # ikisinin əməliyyatı `audit_logs`-a yazır (`PluginManagementUseCase`,
            # `BackupAccessUseCase`) və audit yazısı onu doğuran əməliyyatla
            # eyni tranzaksiyada olmalıdır — audit sətri ROLLBACK olunanda
            # əməliyyat da geri qayıtmalıdır (bax `audit.py` başlığı).
            "plugins": PostgresPluginRegistry(conn, self._context),
            "backup_records": PostgresBackupCatalog(conn, self._context),
            # Baza keçidi: yalnız-oxu bayrağı `system_limits`-də, hadisə
            # jurnalı isə `db_migration_events`-dədir (bax `migration.py`).
            "read_only": SessionReadOnlyController(conn, self._context),
            "migration_events": PostgresMigrationEventLog(conn, self._context),
        }

    def _release(self, *, rollback: bool) -> None:
        if self._conn is None:
            return
        try:
            self._conn.execute("ROLLBACK" if rollback else "COMMIT")
        except psycopg.Error as exc:  # pragma: no cover - bağlantı qırılıb
            _log.error("UOW_RELEASE_FAILED", extra={"error": str(exc)})
        finally:
            self._pool.putconn(cast("Any", self._conn))
            self._conn = None
            self._entered = False
            self._repositories.clear()

    # ------------------------------ tranzaksiya ------------------------------ #

    def commit(self) -> None:
        """Dəyişiklikləri təsdiqləyir. Çağırılmazsa geri qaytarılır."""
        self._require_active()
        assert self._conn is not None
        self._conn.execute("COMMIT")
        # Növbəti əməliyyatlar üçün yeni tranzaksiya + kontekst.
        self._conn.execute("BEGIN")
        self._apply_tenant_context()
        self._committed = True

    def rollback(self) -> None:
        self._require_active()
        assert self._conn is not None
        self._conn.execute("ROLLBACK")
        self._conn.execute("BEGIN")
        self._apply_tenant_context()
        self._committed = False

    # ------------------------------ repo-lar --------------------------------- #

    @property
    def employees(self) -> Any:
        return self._repository("employees")

    @property
    def positions(self) -> Any:
        return self._repository("positions")

    @property
    def leave_requests(self) -> Any:
        return self._repository("leave_requests")

    @property
    def attendance(self) -> Any:
        return self._repository("attendance")

    @property
    def fines(self) -> Any:
        return self._repository("fines")

    @property
    def audit(self) -> Any:
        """`AuditTrail` — bölmə 3/4/7-nin tələb etdiyi `audit_logs` yazıcısı."""
        return self._repository("audit")

    def repository(self, name: str) -> Any:
        """Ad ilə repo — Faza 5/6 qatlarının 20+ repo-su üçün.

        Hər biri üçün ayrıca `@property` yazmaq bu sinfi 100 sətir uzadardı
        və heç bir əlavə tip təhlükəsizliyi verməzdi (property-lər onsuz da
        `Any` qaytarır — repo-lar Protocol-lara uyğunlaşır, miras almır).
        Kompozisiya kökü adları bir yerdə saxlayır.
        """
        return self._repository(name)

    @property
    def connection(self) -> Connection[dict[str, Any]]:
        """Xam bağlantı — yalnız repo-ların əhatə etmədiyi sorğular üçün."""
        self._require_active()
        assert self._conn is not None
        return self._conn

    @property
    def context(self) -> TenantContext:
        return self._context

    def _repository(self, name: str) -> Any:
        self._require_active()
        return self._repositories[name]

    def _require_active(self) -> None:
        if not self._entered or self._conn is None:
            raise TenantContextError(
                "UnitOfWork aktiv deyil — repository-lərə yalnız "
                "`with db.unit_of_work(tenant_id) as uow:` daxilində müraciət olunur "
                "(SEC-008: RLS konteksti olmadan sorğu boş nəticə qaytarardı)",
                context={"tenant_id": str(self._context.tenant_id)},
            )

    def __repr__(self) -> str:
        state = "aktiv" if self._entered else "bağlı"
        return f"PostgresUnitOfWork(tenant={self._context.tenant_id}, {state})"


__all__ = [
    "OWNER_ROLE_PREFIXES",
    "SCHEMA",
    "Database",
    "DatabaseError",
    "PostgresUnitOfWork",
    "TenantContext",
    "TenantContextError",
    "build_dsn_from_env",
]
