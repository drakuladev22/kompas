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

from src.domain.policies import SystemLimitKey
from src.domain.value_objects.identifiers import EmployeeId, TenantId
from src.infrastructure.config.limits import (
    INFRA_LIMIT_BOUNDS,
    InfrastructureLimits,
    fallback_float,
    fallback_int,
)
from src.shared.exceptions import ConfigurationError, KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

SCHEMA: Final[str] = "kompasos"

#: ÜÇÜ DƏ FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits` (`DB_POOL_MIN_SIZE`,
#: `DB_POOL_MAX_SIZE`, `DB_CONNECT_TIMEOUT_SECONDS`; seed: migrations/032).
#:
#: BOOTSTRAP PARADOKSU — NİYƏ FALLBACK BURADA XÜSUSİ ƏHƏMİYYƏTLİDİR:
#: hovuz `system_limits`-i OXUMAQ ÜÇÜN LAZIMDIR, yəni ilk açılışda dəyəri
#: bazadan almaq mümkün deyil. Ona görə hovuz həmişə fallback ilə qalxır və
#: ROOT dəyəri SONRA — bağlantı işlədikdən sonra — `apply_root_pool_limits()`
#: ilə tətbiq olunur (`ConnectionPool.resize`). Alternativ (dəyəri mühit
#: dəyişənindən oxumaq) rədd edildi: onda parametrin İKİ mənbəyi olardı və
#: ROOT ekranındakı rəqəm real vəziyyəti göstərməzdi.
FALLBACK_POOL_MIN: Final[int] = fallback_int(SystemLimitKey.DB_POOL_MIN_SIZE)
FALLBACK_POOL_MAX: Final[int] = fallback_int(SystemLimitKey.DB_POOL_MAX_SIZE)
FALLBACK_TIMEOUT_SECONDS: Final[float] = fallback_float(SystemLimitKey.DB_CONNECT_TIMEOUT_SECONDS)

#: Owner rolları — bunlarla qoşulmaq RLS-i yan keçir (yalnız miqrasiya üçün).
OWNER_ROLE_PREFIXES: Final[tuple[str, ...]] = ("postgres", "supabase_admin")


def _clamped_pool_settings(min_size: int, max_size: int, timeout: float) -> tuple[int, int, float]:
    """Hovuz parametrlərini SƏRT aralığa sıxır və uyğunluğu bərpa edir.

    İki mərhələ var, çünki tək-tək klamp kifayət etmir: `min_size` və
    `max_size` ayrı-ayrılıqda hüdud daxilində olub bir-birinə ZİDD ola bilər
    (məs. min=32, max=4). `psycopg_pool` belə cütdə istisna atır və tətbiq
    ÜMUMİYYƏTLƏ açılmazdı — ona görə `max_size` minimumdan aşağı düşəndə
    yuxarı qaldırılır.
    """
    min_bounds = INFRA_LIMIT_BOUNDS[SystemLimitKey.DB_POOL_MIN_SIZE]
    max_bounds = INFRA_LIMIT_BOUNDS[SystemLimitKey.DB_POOL_MAX_SIZE]
    timeout_bounds = INFRA_LIMIT_BOUNDS[SystemLimitKey.DB_CONNECT_TIMEOUT_SECONDS]

    safe_min = min(max(min_size, int(min_bounds[0])), int(min_bounds[1]))
    safe_max = min(max(max_size, int(max_bounds[0])), int(max_bounds[1]))
    safe_max = max(safe_max, safe_min)
    safe_timeout = min(max(timeout, float(timeout_bounds[0])), float(timeout_bounds[1]))

    if (safe_min, safe_max, safe_timeout) != (min_size, max_size, timeout):
        _log.warning(
            "DB_POOL_SETTINGS_CLAMPED",
            extra={
                "requested": {"min": min_size, "max": max_size, "timeout": timeout},
                "applied": {"min": safe_min, "max": safe_max, "timeout": safe_timeout},
            },
        )
    return safe_min, safe_max, safe_timeout


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
    """DSN-i həll edir: `DATABASE_URL` → konfiqurasiya faylı (DB-4 Faza 2).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ İKİ MƏNBƏ VAR VƏ SIRA MƏHZ BELƏDİR
    ──────────────────────────────────────────────────────────────────────────
    Mühit dəyişəni HƏMİŞƏ üstündür: inkişaf mühiti, CI və konteyner
    quraşdırmaları onunla işləyir. Fayl onları üstələsəydi, testlər maşındakı
    təsadüfi konfiqurasiyadan asılı olardı.

    Fayl isə PAKETLƏNMİŞ quraşdırma üçündür. Ondan əvvəl yeganə yol mühit
    dəyişəni idi — Start menyusundan açılan `.exe`-də isə o, boş olur (tətbiq
    `.env` faylını OXUMUR). Yəni müştəri maşınında bağlantı ÜMUMİYYƏTLƏ
    qurula bilmirdi (bax `infrastructure/config/connection_file.py`).

    Raises:
        ConfigurationError: heç bir mənbə yoxdursa. Mesaj istifadəçini
            Bağlantı Ayarları ekranına yönləndirir — «dəyişən təyin edin»
            göstərişi mağaza işçisi üçün mənasızdır.
    """
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        dsn = _dsn_from_connection_file()
    if not dsn:
        raise ConfigurationError(
            "Baza bağlantısı konfiqurasiya edilməyib",
            user_message=(
                "Baza bağlantısı konfiqurasiya edilməyib. «Bağlantı Ayarları» "
                "ekranından server məlumatlarını daxil edin."
            ),
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


def _dsn_from_connection_file() -> str:
    r"""`%PROGRAMDATA%\KompasOS\connection.json` → DSN (yoxdursa boş sətir).

    XƏTA UDULMUR: fayl VAR, lakin oxunmursa (korlanıb, parol açılmır) səbəb
    yuxarı qaldırılır — «konfiqurasiya yoxdur» ilə «konfiqurasiya sınıqdır»
    istifadəçi üçün tamamilə fərqli iki haldır və birincisi yeni quraşdırma,
    ikincisi isə nasazlıqdır.
    """
    from src.infrastructure.config.connection_file import load_settings  # noqa: PLC0415

    settings = load_settings()
    return settings.dsn() if settings is not None else ""


def probe_dsn(dsn: str, *, timeout: int = 10) -> None:
    """Verilmiş DSN ilə TƏK bağlantı açıb dərhal bağlayır (DB-4 Faza 4).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ HOVUZ DEYİL, TƏK BAĞLANTI
    ──────────────────────────────────────────────────────────────────────────
    Bu funksiya «Bağlantı Ayarları» ekranı üçündür: istifadəçi dəyərləri yazır,
    YADDA SAXLAMAZDAN ƏVVƏL onların işlədiyi yoxlanılmalıdır. `Database()`
    qursaydıq, hovuz açılışı bir neçə bağlantı yaradar və uğursuzluqda
    `psycopg`-nin ORİJİNAL istisnası hovuz taymautunun altında itərdi — halbuki
    ekran məhz həmin istisnanın SQLSTATE-inə görə «parol yanlışdır» ilə
    «server əlçatmazdır» arasında seçim edir.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ SINAQ MƏCBURİDİR — «YADDA SAXLA VƏ GÖR» KİFAYƏT ETMİR
    ──────────────────────────────────────────────────────────────────────────
    Yoxlamasız yazsaydıq, səhv dəyər faylda QALARDI və tətbiq növbəti açılışda
    yenə eyni fatal ekrana düşərdi — istifadəçi isə artıq «düzəltdim» sanardı.
    Yanlış konfiqurasiyanı diskə yazmamaq onu geri qaytarmaqdan ucuzdur.

    Raises:
        psycopg.Error: bağlantı qurulmadı. İstisna QƏSDƏN sarğılanmır —
            çağıran tərəf onu SQLSTATE ilə təsnif edir (bax
            `composition.classify_connection_failure`).
    """
    with psycopg.connect(dsn, connect_timeout=timeout) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
        cur.fetchone()
    _log.info("DSN_PROBE_OK")


class Database:
    """Bağlantı pool-unun sahibi. Tətbiqdə TƏK nüsxə (DI singleton)."""

    def __init__(
        self,
        dsn: str | None = None,
        *,
        admin_dsn: str | None = None,
        min_size: int = FALLBACK_POOL_MIN,
        max_size: int = FALLBACK_POOL_MAX,
        timeout: float = FALLBACK_TIMEOUT_SECONDS,
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
        # Verilən dəyərlər DƏRHAL klamp edilir: hovuz ölçüsü `0` və ya mənfi
        # olsa tətbiq heç bir sorğu edə bilməzdi və səbəbi yalnız DSN/limit
        # sətrinə baxmaqla tapılardı (bax `config/limits.py` başlığı).
        self._min_size, self._max_size, self._timeout = _clamped_pool_settings(
            min_size, max_size, timeout
        )
        self._pool = self._make_pool(self._dsn, self._min_size, self._max_size, self._timeout)
        self._admin_pool = (
            self._make_pool(self._admin_dsn, 1, 2, self._timeout) if self._admin_dsn else None
        )
        if open_pool:
            self.open()

    def apply_root_pool_limits(self, limits: InfrastructureLimits) -> tuple[int, int]:
        """ROOT-dakı hovuz ölçüsünü CANLI hovuza tətbiq edir.

        Bootstrap paradoksunun həlli (bax modul sabitlərinin şərhi): hovuz
        fallback ilə qalxır, bu metod isə bağlantı işlədikdən SONRA — tenant
        məlum olanda — çağırılır və `ConnectionPool.resize()` ilə ölçünü
        Root-un yazdığı dəyərə gətirir. Prosesi yenidən başlatmaq TƏLƏB
        OLUNMUR.

        Taymaut DƏYİŞMİR: `psycopg_pool` onu yalnız qurulma anında qəbul edir
        və yeni dəyər üçün hovuzu bağlayıb yenidən açmaq lazım gələrdi —
        işləyən sessiyada bu, bütün açıq tranzaksiyaları qırardı. Taymaut
        növbəti başlanğıcda qüvvəyə minir.

        Qaytarır: tətbiq edilmiş `(min_size, max_size)` — çağıran onu loga
        yazmaq və ya ekranda göstərmək üçün istifadə edir.
        """
        min_size, max_size, _ = _clamped_pool_settings(
            limits.int_of(SystemLimitKey.DB_POOL_MIN_SIZE),
            limits.int_of(SystemLimitKey.DB_POOL_MAX_SIZE),
            limits.float_of(SystemLimitKey.DB_CONNECT_TIMEOUT_SECONDS),
        )
        if (min_size, max_size) == (self._min_size, self._max_size):
            return min_size, max_size
        self._pool.resize(min_size=min_size, max_size=max_size)
        self._min_size, self._max_size = min_size, max_size
        _log.info("DB_POOL_RESIZED", extra={"min_size": min_size, "max_size": max_size})
        return min_size, max_size

    @property
    def pool_settings(self) -> tuple[int, int, float]:
        """Qüvvədə olan `(min_size, max_size, timeout)` — diaqnostika üçün."""
        return self._min_size, self._max_size, self._timeout

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
        self._pool.open(wait=True, timeout=self._timeout)
        if self._admin_pool is not None:
            self._admin_pool.open(wait=True, timeout=self._timeout)
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
        from src.infrastructure.persistence.announcement_repository import (  # noqa: PLC0415
            PostgresAnnouncementRepository,
        )
        from src.infrastructure.persistence.annual_leave_repository import (  # noqa: PLC0415
            PostgresAnnualLeaveBalanceRepository,
            PostgresAnnualLeaveRequestRepository,
        )
        from src.infrastructure.persistence.attrition_repository import (  # noqa: PLC0415
            PostgresAttritionRepository,
        )
        from src.infrastructure.persistence.audit import (  # noqa: PLC0415
            PostgresAuditReader,
            PostgresAuditTrail,
        )
        from src.infrastructure.persistence.behavior_repositories import (  # noqa: PLC0415
            PostgresBehaviorBaselineRepository,
            PostgresCheckInHistoryProvider,
        )
        from src.infrastructure.persistence.benchmark_repository import (  # noqa: PLC0415
            PostgresMultiStoreBenchmarkRepository,
        )
        from src.infrastructure.persistence.branding_repository import (  # noqa: PLC0415
            PostgresBrandingRepository,
        )
        from src.infrastructure.persistence.break_usage_repository import (  # noqa: PLC0415
            PostgresDailyBreakUsageRepository,
        )
        from src.infrastructure.persistence.bulk_operations_repository import (  # noqa: PLC0415
            PostgresBulkImportLogRepository,
            PostgresStoreTemplateRepository,
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
            PostgresTenantProvisioning,
        )
        from src.infrastructure.persistence.device_repository import (  # noqa: PLC0415
            PostgresActiveStoreLookup,
            PostgresDeviceRegistry,
        )
        from src.infrastructure.persistence.employee_document_repository import (  # noqa: PLC0415
            PostgresEmployeeDocumentRepository,
        )
        from src.infrastructure.persistence.exception_repositories import (  # noqa: PLC0415
            PostgresExceptionRepository,
            PostgresExceptionSourceCatalog,
        )
        from src.infrastructure.persistence.executive_digest_repository import (  # noqa: PLC0415
            PostgresExecutiveDigestConfigRepository,
        )
        from src.infrastructure.persistence.export_correction_repository import (  # noqa: PLC0415
            PostgresExportCorrectionRepository,
        )
        from src.infrastructure.persistence.face_repository import (  # noqa: PLC0415
            PostgresFaceEmbeddingRepository,
            PostgresFaceExemptionRepository,
            PostgresFaceStoreScopeRepository,
            PostgresFaceVerificationLogRepository,
        )
        from src.infrastructure.persistence.field_report_repositories import (  # noqa: PLC0415
            PostgresFieldReportCatalog,
            PostgresFieldReportRepository,
        )
        from src.infrastructure.persistence.migration import (  # noqa: PLC0415
            PostgresMigrationEventLog,
            SessionReadOnlyController,
        )
        from src.infrastructure.persistence.notification_repositories import (  # noqa: PLC0415
            PostgresNotificationRepository,
        )
        from src.infrastructure.persistence.open_shift_repository import (  # noqa: PLC0415
            PostgresOpenShiftPostingRepository,
        )
        from src.infrastructure.persistence.overtime_repositories import (  # noqa: PLC0415
            PostgresOvertimeLogRepository,
            PostgresWorkedHoursProvider,
        )
        from src.infrastructure.persistence.performance_review_repository import (  # noqa: PLC0415
            PostgresPerformanceReviewRepository,
        )
        from src.infrastructure.persistence.platform_repositories import (  # noqa: PLC0415
            PostgresBackupCatalog,
            PostgresPluginRegistry,
        )
        from src.infrastructure.persistence.pos_policy_repository import (  # noqa: PLC0415
            PostgresPOSThresholdRepository,
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
        from src.infrastructure.persistence.staffing_repositories import (  # noqa: PLC0415
            PostgresStaffingHistoryProvider,
            PostgresStaffingPatternRepository,
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
        from src.infrastructure.security.encryption import EncryptionService  # noqa: PLC0415

        if self._conn is None:  # pragma: no cover - invariant
            raise TenantContextError("Bağlantı yoxdur")
        conn = self._conn
        # #21 (Faza 9) — TƏK nüsxə aşağıda İKİ açarla ("attrition_signals",
        # "attrition_scores") qeydiyyatdan keçir (bax `attrition_repository.py`
        # başlığı: "bir sinif iki protokolu birlikdə tətbiq edir"). Dict
        # literalının İÇİNDƏ ikinci dəfə qurmaq həm iki ayrı bağlantı təhlükəsi
        # yaradardı, həm də oxucuya "bunlar EYNİ obyektdir" faktını gizlədərdi.
        attrition = PostgresAttritionRepository(conn, self._context)
        # #30 (kompas1.md Faza 6) — EYNİ naxış: TƏK nüsxə İKİ açarla
        # ("executive_digest_config", "executive_digest_facts") qeydiyyatdan
        # keçir (bax `executive_digest_repository.py` başlığı).
        executive_digest = PostgresExecutiveDigestConfigRepository(conn, self._context)
        # kompas1.md Faza 8 (HR-D) — ÜÇÜNCÜ dəfə EYNİ naxış: tək nüsxə iki
        # açarla ("export_corrections", "export_roster"). İkisi bir sinifdədir,
        # çünki düzəliş yazıldıqdan SONRA doğrulama həmin (hələ commit
        # olunmamış) sətri görməlidir — bax `export_correction_repository.py`
        # başlığı.
        export_corrections = PostgresExportCorrectionRepository(conn, self._context)
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
            # --- #16 Açıq Növbə Bazarı (Faza 6) -------------------------------
            # Elan cədvəli və `shifts` EYNİ bağlantıdadır — MƏCBURİDİR: elan
            # tutulanda `shift_assignments`-ə təyinat yazılır və hər ikisi bir
            # tranzaksiyada olmalıdır. Ayrı bağlantıda elan "tutulmuş", təqvim
            # isə boş qala bilərdi.
            "open_shifts": PostgresOpenShiftPostingRepository(conn, self._context),
            "sheets": PostgresDailyAttendanceSheetRepository(conn, self._context),
            "attendance_facts": PostgresAttendanceFactProvider(conn, self._context),
            "appeals": PostgresFineAppealRepository(conn, self._context),
            "tasks": PostgresTaskRepository(conn, self._context),
            "sales_points": PostgresSalesPointsRepository(conn, self._context),
            "rewards": PostgresRewardRepository(conn, self._context),
            "work_modes": PostgresWorkModeRepository(conn, self._context),
            "fine_types": PostgresFineTypeRepository(conn, self._context),
            "leave_types": PostgresLeaveTypeRepository(conn, self._context),
            # --- Nahar / Çay fasiləsinin gündəlik sayğacı (nahar.md) -----------
            # `leave_types` VƏ `leave_requests` İLƏ EYNİ BAĞLANTIDA olması
            # MƏCBURİDİR: STEP1 sorğunu yazır, dərhal ardınca sayğacı artırır
            # və hər ikisi eyni tranzaksiyada olmalıdır. Ayrı bağlantıda
            # rollback edilmiş STEP1 sayğacı artırılmış qoyardı — işçi
            # yaranmamış fasiləyə görə gündəlik haqqını itirərdi.
            "break_usage": PostgresDailyBreakUsageRepository(conn, self._context),
            "limits": PostgresSystemLimits(conn, self._context),
            "toggles": PostgresFeatureToggles(conn, self._context),
            "permission_flags": PostgresPermissionFlagRepository(conn, self._context),
            "camera_assignments": PostgresCameraAssignmentRepository(conn, self._context),
            "stores": PostgresStoreWriter(conn, self._context),
            # İlk Quraşdırma Sihirbazının tenant sətri — `stores` İLƏ EYNİ
            # BAĞLANTIDA olması MƏCBURİDİR: mağaza sətrinin `tenant_id`-si
            # həmin tenant sətrinə xarici açarla bağlıdır və ikisi bir
            # tranzaksiyada görünməlidir. Ayrı bağlantıda mağaza yazısı hələ
            # commit olunmamış tenant-ı görməz və FK pozuntusu ilə dayanardı.
            "tenant_provisioning": PostgresTenantProvisioning(conn, self._context),
            "preferences": PostgresUserPreferences(conn, self._context),
            "report_facts": PostgresReportFactProvider(conn, self._context),
            "support": PostgresSupportTicketRepository(conn, self._context),
            "sync_conflicts": PostgresSyncConflictRepository(conn, self._context),
            # --- Cihaz qeydiyyatı (DEVICE-1) ----------------------------------
            # Cihaz reyestri və aktiv mağaza siyahısı EYNİ bağlantıdadır:
            # avtomatik təsdiq mağaza SAYINI oxuyub cihazı həmin mağazaya
            # bağlayır və ikisi bir tranzaksiyada görünməlidir — əks halda
            # paralel yaradılan mağaza «tək mağaza» şərtini görünməz şəkildə
            # pozar və cihaz səhv filiala təyin olunardı.
            "devices": PostgresDeviceRegistry(conn, self._context),
            # --- Tenant brendinqi (TENANT-1) ----------------------------------
            # Brendinq AÇILIŞ yolunda oxunur (başlıq zolağı, splash) —
            # sessiyanın ilk sorğularından biridir və ayrı bağlantı açmaq
            # açılışa ikinci gediş-dönüş əlavə edərdi.
            "branding": PostgresBrandingRepository(conn, self._context),
            "active_stores": PostgresActiveStoreLookup(conn, self._context),
            # --- Vahid İstisna Motoru (#9) ------------------------------------
            # Jurnal və mənbə kataloqu EYNİ bağlantıdadır: motor istisnanı
            # yazarkən mənbənin `is_active`/`default_severity` dəyərini oxuyur
            # və hər ikisi bir tranzaksiyada görünməlidir (mənbə söndürüləndə
            # yarımçıq icra yeni sətir yazmasın).
            "exceptions": PostgresExceptionRepository(conn, self._context),
            "exception_sources": PostgresExceptionSourceCatalog(conn, self._context),
            # --- #8 İşçi Davranış Baz Xətti (Faza 5) ---------------------------
            # Baz xətt cədvəli və xam giriş mənbəyi EYNİ bağlantıda: gecəlik
            # yenidən-hesablama hər ikisini bir tranzaksiyada oxuyub yazır.
            "behavior_baselines": PostgresBehaviorBaselineRepository(conn, self._context),
            "checkin_history": PostgresCheckInHistoryProvider(conn, self._context),
            # --- #15 Norma üstü iş saatları (Faza 6) ---------------------------
            # Jurnal və iş pəncərəsi mənbəyi EYNİ bağlantıdadır, çünki yazı
            # TABELİN TƏSDİQİ ilə eyni tranzaksiyada baş verir: təsdiq geri
            # qayıdarsa, ondan çıxan aşım sətri də qayıtmalıdır (əks halda
            # imzalanmamış günün "sübutu" bazada qalardı).
            "overtime_log": PostgresOvertimeLogRepository(conn, self._context),
            "worked_hours": PostgresWorkedHoursProvider(conn, self._context),
            # --- #13 Tarixi-nümunə kadr təklifi (Faza 6) ----------------------
            # Təklif cədvəli və xam davamiyyət mənbəyi EYNİ bağlantıdadır:
            # yenidən-hesablama eyni tranzaksiyada oxuyub yazır, yəni yarımçıq
            # icra yarısı köhnə, yarısı yeni pəncərədən çıxmış təklif qoymur.
            # 1C-YƏ HEÇ BİR BAĞLANTI YOXDUR (kompasos11.md struktur qərar D).
            "staffing_patterns": PostgresStaffingPatternRepository(conn, self._context),
            "staffing_history": PostgresStaffingHistoryProvider(conn, self._context),
            # --- #7 POS Səlahiyyət Siyasəti (sənədləşdirmə, Faza 4) -----------
            # Eyni bağlantıda: yazı + audit BİR tranzaksiyada olmalıdır (bax
            # `audit.py` başlığı — audit yazısı istisna udmur, CLAUDE.md §5).
            "pos_thresholds": PostgresPOSThresholdRepository(conn, self._context),
            # --- #17 İşçi Sənədləri (Faza 7) -----------------------------------
            # Eyni bağlantıda: yazı + audit BİR tranzaksiyada (audit istisna
            # udmur, CLAUDE.md §5). Shift Matrix-in `documents` asılılığı da
            # BU repo-nu işlədir (bax `composition.py` — eyni bağlantı,
            # hələ commit olunmamış sənəd dəyişikliyi görünsün deyə).
            "employee_documents": PostgresEmployeeDocumentRepository(conn, self._context),
            # --- #19/#20 Ünsiyyət və Performans (Faza 8) -----------------------
            # Eyni bağlantıda: yazı + audit BİR tranzaksiyada (audit istisna
            # udmur, CLAUDE.md §5). İkisi ARASI ƏLAQƏ YOXDUR (ayrı aqreqatlar,
            # ayrı use case-lər) — yan-yana qeydiyyat sırf oxunaqlılıq üçündür.
            "announcements": PostgresAnnouncementRepository(conn, self._context),
            "performance_reviews": PostgresPerformanceReviewRepository(conn, self._context),
            # --- #21 İşdən Çıxma Riski (Faza 9) --------------------------------
            # `attrition` YUXARIDA quruldu (bax dict-dən ƏVVƏLKİ şərh) — burada
            # YALNIZ İKİ açarla qeydə alınır, YENİDƏN QURULMUR.
            "attrition_signals": attrition,
            "attrition_scores": attrition,
            # --- #24 Çox-Mağaza Benchmark Dashboard (Faza 9A) ------------------
            # YALNIZ-OXU aqreqasiya — heç bir başqa repo ilə eyni tranzaksiya
            # tələb etmir (yazı yolu yoxdur, bax use case modul başlığı).
            "multi_store_benchmark": PostgresMultiStoreBenchmarkRepository(conn, self._context),
            # --- #26+#27 Sahə hesabatları (kompas1.md Faza 3) ------------------
            # Eyni bağlantıda: hesabat + checklist bəndləri + düzəliş tapşırığı
            # + audit BİR tranzaksiyada olmalıdır. Tapşırıq `catalog_
            # repositories.PostgresTaskRepository` ilə yazılır (Struktur Qərar B:
            # mövcud Tapşırıq Mühərriki) — o da elə bu dict-dədir, yəni
            # uğursuz bənd ilə ondan doğan tapşırıq ATOMİKDİR: biri yazılıb
            # digəri yazılmayan vəziyyət mümkün deyil.
            "field_reports": PostgresFieldReportRepository(conn, self._context),
            "field_report_catalog": PostgresFieldReportCatalog(conn, self._context),
            # --- #28 İllik məzuniyyət balansı (kompas1.md Faza 4) --------------
            # Eyni bağlantıda: sorğunun statusu, balansın azalması və audit BİR
            # tranzaksiyada olmalıdır. Ayrı bağlantılarda təsdiq yazılıb balans
            # azalmamış qala bilərdi — yəni işçi pulsuz gün alardı.
            #
            # GÜNDAXİLİ İCAZƏ İLƏ QARIŞDIRILMASIN: `leave_requests` (yuxarıda)
            # STEP1/STEP2 axınının dəqiqə əsaslı sətirləridir və bu iki repo
            # bir-birini ÇAĞIRMIR (bax `entities/annual_leave.py` başlığı).
            "annual_leave_balances": PostgresAnnualLeaveBalanceRepository(conn, self._context),
            "annual_leave_requests": PostgresAnnualLeaveRequestRepository(conn, self._context),
            # --- #29 Toplu Əməliyyatlar (kompas1.md Faza 5) --------------------
            # Eyni bağlantıda: CSV idxalının YEKUN jurnal sətri (`finish()`) və
            # ƏMƏLİYYAT səviyyəli audit sətri BİR tranzaksiyada olmalıdır — bax
            # `application/use_cases/bulk_operations.py` başlığı (TRANZAKSİYA
            # SƏRHƏDİ). Fərdi sətirlərin özü isə `composition.py`-dəki
            # `_bulk_create_employee_row` closure-u vasitəsilə AYRI-AYRI
            # commit olunur.
            "bulk_import_log": PostgresBulkImportLogRepository(conn, self._context),
            "store_templates": PostgresStoreTemplateRepository(conn, self._context),
            # --- #30 Planlaşdırılmış İcra Xülasəsi (kompas1.md Faza 6) ---------
            # TƏK nüsxə İKİ açarla qeydiyyatdan keçir (`PostgresAttritionRepository`
            # ilə EYNİ naxış, yuxarı bax "attrition_signals"/"attrition_scores"
            # şərhi): konfiqurasiya sətri VƏ gecikən-check-in sayı EYNİ
            # tranzaksiyada oxunur — ikinci bağlantı lazım deyil.
            "executive_digest_config": executive_digest,
            "executive_digest_facts": executive_digest,
            # --- HR-D Export düzəlişləri (kompas1.md Faza 8) -------------------
            # Düzəliş sətri VƏ kadr vəziyyəti EYNİ bağlantıdadır — MƏCBURİDİR:
            # düzəliş + audit sətri bir tranzaksiyada olmalıdır (audit istisna
            # udmur, CLAUDE.md §5), doğrulama isə həmin tranzaksiya daxilində
            # yeni sətri dərhal görməlidir.
            "export_corrections": export_corrections,
            "export_roster": export_corrections,
            # --- Face Control — üz təsdiqi (facecontrol.md, migrations/047) ----
            # DÖRDÜ DƏ EYNİ BAĞLANTIDADIR VƏ BU, MƏCBURİDİR:
            #   * MISMATCH halında sayğac (`employees` üz sütunları) ilə jurnal
            #     sətri BİR tranzaksiyada yazılır — ayrı bağlantıda "kilid
            #     qoyuldu, lakin səbəbi jurnalda yoxdur" vəziyyəti mümkün
            #     olardı və kilidin qanuniliyi sübut edilə bilməzdi;
            #   * yenidən-qeydiyyatda arxiv sətri ilə yeni vektor atomikdir
            #     (arxivsiz üstündən yazma bənd 2-nin qadağasıdır);
            #   * deaktivasiyada `is_active = FALSE` ilə vektorun silinməsi
            #     atomikdir (bənd 8) — biri yazılıb digəri yazılmayan hal
            #     biometrik məlumatı sahibsiz qoyardı.
            #
            # ŞİFRƏLƏMƏ REPO-NUN İÇİNDƏDİR: `EncryptionService` MƏHZ BURADA
            # qurulur və `ErpServerRepository` naxışını təkrarlayır — tətbiq
            # qatı açıq vektorla işləyir, bazaya isə yalnız token yazılır.
            "face_embeddings": PostgresFaceEmbeddingRepository(
                conn, self._context, EncryptionService()
            ),
            "face_verification_log": PostgresFaceVerificationLogRepository(conn, self._context),
            "face_exemptions": PostgresFaceExemptionRepository(conn, self._context),
            "face_store_scope": PostgresFaceStoreScopeRepository(conn, self._context),
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
    "FALLBACK_POOL_MAX",
    "FALLBACK_POOL_MIN",
    "FALLBACK_TIMEOUT_SECONDS",
    "OWNER_ROLE_PREFIXES",
    "SCHEMA",
    "Database",
    "DatabaseError",
    "PostgresUnitOfWork",
    "TenantContext",
    "TenantContextError",
    "build_dsn_from_env",
    "probe_dsn",
]
