"""GUI kompozisiya kökü — obyekt qrafı (Faza 5/6 bağlantısı).

`app.py` PƏNCƏRƏ və EKRAN qrafını qurur; bu modul isə onların arxasındakı
USE CASE qrafını qurur. İkisinin ayrı olması qəsdəndir: `app.py` bazadan
tamamilə asılı olmadan (önizləmə rejimi, dizayn yoxlaması) işləyə bilməlidir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ USE CASE-LƏR HƏR ƏMƏLİYYATDA YENİDƏN QURULUR
──────────────────────────────────────────────────────────────────────────────
Repository-lər BAĞLANTIYA bağlıdır (`PostgresUnitOfWork._build_repositories`),
bağlantı isə tranzaksiya sərhədidir. Use case-i bir dəfə qurub saxlasaydıq, o,
artıq bağlanmış bir bağlantıya istinad edərdi.

Ona görə naxış belədir::

    with context.session() as session:
        session.leave_verification.claim_return(...)
        session.commit()

`session()` yeni `UnitOfWork` açır, use case-ləri onun repo-ları ilə qurur və
çıxışda bağlayır. Bu, "hər ekran əməliyyatı = bir tranzaksiya" qaydasını
struktur olaraq təmin edir.

──────────────────────────────────────────────────────────────────────────────
İNFRASTRUKTUR LİMİTLƏRİ BURADAN QOŞULUR (Faza 10.2, ikinci dalğa)
──────────────────────────────────────────────────────────────────────────────
`src/infrastructure/` altındakı 20 sinif `limits: InfrastructureLimits | None`
parametri qəbul edir, lakin onu QURAN yalnız BU fayldır. Qurulmasaydı hər sinif
`InfrastructureLimits()` (portsuz) ilə işləyərdi — yəni 51 parametr ROOT
ekranında GÖRÜNƏR, Root onları dəyişər və HEÇ NƏ baş verməzdi. Faza 10-un
bağlamaq istədiyi qüsur məhz budur.

İKİ QURAŞDIRMA YOLU VAR və fərq qəsdəndir:

  1. `ApplicationContext.infrastructure_limits()` — UZUN ÖMÜRLÜ obyektlər üçün
     (sübut növbəsi, Drive fabriki, offline bufer, DB hovuzu). Onlar sessiyadan
     uzun yaşayır, ona görə arxasında `_RootLimitReader` durur: hər oxu üçün
     QISA, yalnız-oxu bir iş vahidi açılır.
  2. `_build_session` daxilindəki `session_limits` — SESSİYA ÖMÜRLÜ obyektlər
     üçün (`PostgresNotifier`, `NightlyBackupService`, `OneCConnectorFactory`).
     Onlar onsuz da açıq tranzaksiyanın içindədir və `repo("limits")` EYNİ
     bağlantını işlədir: hər ekran əməliyyatında ikinci bağlantı açmaq hovuzdan
     lazımsız tutum tələb edərdi.

KEŞ YOXDUR (bax `InfrastructureLimits` başlığı): Root sürüşdürücünü tərpədən
kimi növbəti çağırış yeni dəyəri görməlidir.

──────────────────────────────────────────────────────────────────────────────
LİSENZİYA QAPISI
──────────────────────────────────────────────────────────────────────────────
Bölmə 8: `LICENSE_INACTIVE` vəziyyətində "tətbiq tam bağlanır (heç bir modul,
o cümlədən PIN handshake, işləmir)". `license_state()` həmin qərarı verir və
`app.py` ona görə ya `LicenseInactiveScreen`, ya da normal axını göstərir.
"""

from __future__ import annotations

import socket
import threading
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any, Final

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.infrastructure.config.limits import InfrastructureLimits
from src.infrastructure.timekeeping.clock import SystemClock
from src.infrastructure.timekeeping.server_time import (
    PostgresServerTimeProbe,
    ServerTimeService,
)
from src.shared.data_paths import resolve_data_file
from src.shared.event_bus import get_event_bus
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from src.application.use_cases.announcements import AnnouncementUseCase
    from src.application.use_cases.annual_leave import AnnualLeaveUseCase
    from src.application.use_cases.attrition_risk import AttritionRiskUseCase
    from src.application.use_cases.audit_query import AuditQueryUseCase
    from src.application.use_cases.authentication import SessionManagementUseCase
    from src.application.use_cases.backup_access import BackupAccessUseCase
    from src.application.use_cases.behavior_baseline import BehaviorBaselineUseCase
    from src.application.use_cases.break_glass import BreakGlassUseCase
    from src.application.use_cases.bulk_operations import (
        BulkEmployeeImportUseCase,
        StoreTemplateUseCase,
    )
    from src.application.use_cases.campaign_periods import CampaignPeriodsUseCase
    from src.application.use_cases.catalog_management import (
        ChecklistItemTemplateUseCase,
        FineTypeCatalogUseCase,
        LeaveTypeCatalogUseCase,
        WorkModeCatalogUseCase,
    )
    from src.application.use_cases.daily_attendance import DailyAttendanceSheetUseCase
    from src.application.use_cases.dashboard_layout import DashboardLayoutUseCase
    from src.application.use_cases.db_switch import DatabaseSwitchUseCase
    from src.application.use_cases.device_registry import DeviceRegistryUseCase
    from src.application.use_cases.employee_documents import EmployeeDocumentUseCase
    from src.application.use_cases.employee_profile import EmployeeProfileAccessUseCase
    from src.application.use_cases.employee_transfer import TransferRequestUseCase
    from src.application.use_cases.erp_connection import ErpConnectionWizardUseCase
    from src.application.use_cases.exception_engine import ExceptionEngineUseCase
    from src.application.use_cases.executive_digest import ExecutiveDigestUseCase
    from src.application.use_cases.export_preflight import ExportPreflightUseCase
    from src.application.use_cases.face_control import (
        FaceControlExemptionUseCase,
        FaceEnrollmentUseCase,
        FaceLockReleaseUseCase,
        FaceReEnrollmentUseCase,
        FaceVerificationLogRetentionUseCase,
        FaceVerificationUseCase,
    )
    from src.application.use_cases.field_reports import FieldReportUseCase
    from src.application.use_cases.fine_management import (
        FineAppealUseCase,
        ManualFineUseCase,
    )
    from src.application.use_cases.fine_review import MonthlyFineReviewUseCase
    from src.application.use_cases.first_run_setup import FirstRunSetupUseCase
    from src.application.use_cases.leave_verification import LeaveVerificationUseCase
    from src.application.use_cases.morning_check_in import MorningCheckInUseCase
    from src.application.use_cases.multi_store_benchmark import MultiStoreBenchmarkUseCase
    from src.application.use_cases.offboarding_checklist import (
        EmployeeOffboardingChecklistUseCase,
    )
    from src.application.use_cases.open_shift_market import OpenShiftMarketUseCase
    from src.application.use_cases.overtime_tracking import OvertimeTrackingUseCase
    from src.application.use_cases.performance_reviews import PerformanceReviewUseCase
    from src.application.use_cases.permission_guards import (
        PermissionHierarchyGuardUseCase,
    )
    from src.application.use_cases.plugin_management import PluginManagementUseCase
    from src.application.use_cases.pos_threshold import POSThresholdUseCase
    from src.application.use_cases.position_management import PositionManagementUseCase
    from src.application.use_cases.reporting import MonthlyReportUseCase
    from src.application.use_cases.root_control import RootControlUseCase
    from src.application.use_cases.sales_points import SalesPointsUseCase
    from src.application.use_cases.sales_review_queue import SalesReviewQueueUseCase
    from src.application.use_cases.shift_handoff import ShiftHandoffUseCase
    from src.application.use_cases.shift_scheduling import (
        ShiftPlanningUseCase,
        ShiftSwapUseCase,
    )
    from src.application.use_cases.staffing_pattern import StaffingPatternUseCase
    from src.application.use_cases.support_chat import (
        SupportChatUseCase,
        SupportInboxUseCase,
    )
    from src.application.use_cases.sync_conflicts import SyncConflictUseCase
    from src.application.use_cases.task_workflow import TaskWorkflowUseCase
    from src.application.use_cases.telegram_config import TelegramConfigUseCase
    from src.application.use_cases.tenant_branding import TenantBrandingUseCase
    from src.application.use_cases.user_management import EmployeeDraft, UserManagementUseCase
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import Clock, NtpVerifier
    from src.domain.value_objects.identifiers import EmployeeId, TenantId
    from src.domain.value_objects.time_integrity import TimeIntegrityStatus
    from src.infrastructure.erp.servers import ErpServerRepository
    from src.infrastructure.licensing.client import LicenseClient
    from src.infrastructure.persistence.connection import PostgresUnitOfWork
    from src.infrastructure.persistence.connection_types import TenantDatabase

_log = get_logger(__name__)
_error_log = get_logger(__name__, channel=LogChannel.ERROR)


class _NullNtp:
    """Ölçmə mənbəyi olmayan `NtpVerifier` — bax `ApplicationContext.__init__`."""

    def verified_now(self) -> tuple[datetime, bool]:
        return datetime.now(UTC), False

    def drift_seconds(self) -> float | None:
        return None


def _batch_limits(batch: threading.local | None) -> Any | None:
    """Aktiv açılış toplusunun `limits` repo-su — yoxdursa `None` (PERF-4).

    `read_batch()` sapa görə bir iş vahidi saxlayır. Limit körpüləri
    `ApplicationContext.session()`-dan KEÇMİR (onlar `Session`-u yox, repo-nu
    istəyir), ona görə toplunu BURADAN görürlər. Toplu yoxdursa `None` qayıdır
    və çağıran öz qısa tranzaksiyasını açır — köhnə davranış.
    """
    if batch is None:
        return None
    uow = getattr(batch, "uow", None)
    if uow is None:
        return None
    return uow.repository("limits")


def _drop_batch(batch: threading.local) -> None:
    """Paylaşılan toplunu buraxır — sınan sorğudan SONRA məcburidir.

    PostgreSQL sınan sorğudan sonra tranzaksiyanı ABORTED saxlayır: həmin
    tranzaksiyada NÖVBƏTİ hər sorğu da sınar. `ApplicationContext.session()`
    eyni qərarı verir; burada təkrarlanır, çünki limit yolu oradan keçmir.
    """
    batch.uow = None
    batch.session = None
    _log.warning("READ_BATCH_ABORTED", extra={"reason": "limit oxusu"})


class _RootLimitReader:
    """`system_limits`-in SESSİYADAN-KƏNAR oxu körpüsü (`LimitReader`).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ AYRICA KÖRPÜ — REPO-NU BİRBAŞA SAXLAMAQ OLMAZDI
    ──────────────────────────────────────────────────────────────────────────
    `uow.repository("limits")` BAĞLANTIYA bağlıdır və tranzaksiya bitəndə ölür.
    Sübut növbəsi, Drive fabriki və offline bufer isə tətbiq işlədikcə yaşayır
    və limiti ÇAĞIRIŞ ANINDA oxuyur — həmin an artıq başqa bir sessiyadır.
    Ona görə burada repo DEYİL, `Database` saxlanılır və hər oxu üçün qısa,
    yalnız-oxu bir iş vahidi açılır (`commit` YOXDUR — çıxışda rollback olur,
    oxu üçün doğru davranış).

    ──────────────────────────────────────────────────────────────────────────
    İKİNCİ BAĞLANTI KİLİD YARADIRMI — XEYR
    ──────────────────────────────────────────────────────────────────────────
    Oxu açıq bir tranzaksiyanın İÇİNDƏN də çağırıla bilər (məs. bildiriş
    göndərilərkən). Sadə `SELECT` PostgreSQL-də təsdiqlənməmiş `UPDATE`-i
    GÖZLƏMİR (MVCC) — köhnə versiyanı oxuyur, yəni öz-özünə kilidlənmə
    mümkün deyil. Ən pis hal: dəyər həmin an bir tranzaksiya köhnədir.

    Xəta ATILMIR: uğursuzluq `InfrastructureLimits._raw` tərəfindən tutulur və
    fallback işə düşür (bax orada — "cavabsız qaldıqda fallback").

    ──────────────────────────────────────────────────────────────────────────
    AÇILIŞ TOPLUSU VARSA YENİ BAĞLANTI AÇILMIR (PERF-4)
    ──────────────────────────────────────────────────────────────────────────
    Yuxarıdakı «hər oxu üçün qısa iş vahidi» qaydası oxu TƏK olanda ucuzdur,
    açılış anında isə DEYİL. Canlı ölçü (uzaq Supabase, girişdən sonrakı
    `show_admin`): bu körpü DÖRD dəfə çağırılır və hər çağırış tam bir
    tranzaksiya açır — `set_config` ilə RLS konteksti ~411 ms, sorğunun özü
    ~206 ms. Yəni cəmi **4.53 saniyə**, halbuki həmin anda `read_batch()`
    ARTIQ açıq bir tranzaksiya saxlayır və oxu ora düşsəydi yalnız sorğu
    qiyməti qalardı.

    Ona görə körpü topluya BAXIR: sapda aktiv `read_batch` varsa onun iş
    vahidini işlədir, yoxdursa köhnə davranış (öz qısa tranzaksiyası) olduğu
    kimi qalır. Sap-yerli obyektin ÖZÜ ötürülür (nüsxə deyil) — `read_batch`
    onu açıb-bağladıqca körpü avtomatik uyğunlaşır.

    PAYLAŞILAN TRANZAKSİYADA XƏTA TOPLUNU SÖNDÜRÜR: PostgreSQL sınan sorğudan
    sonra tranzaksiyanı ABORTED saxlayır, yəni növbəti HƏR oxu da sınardı.
    `ApplicationContext.session()` eyni qərarı verir (`READ_BATCH_ABORTED`) —
    burada təkrarlanır, çünki bu yol `session()`-dan KEÇMİR.
    """

    __slots__ = ("_batch", "_database")

    def __init__(self, database: TenantDatabase, *, batch: threading.local | None = None) -> None:
        self._database = database
        self._batch = batch

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
        batch = self._batch
        shared = _batch_limits(batch)
        if batch is not None and shared is not None:
            try:
                borrowed: str = shared.get_str(tenant_id, key, default)
            except Exception:
                # Çağıran `InfrastructureLimits._raw`-dır və o, istisnanı tutub
                # fallback-a keçir — yəni limit oxunmur, LAKİN açılış davam edir.
                _drop_batch(batch)
                raise
            return borrowed
        with self._database.unit_of_work(tenant_id) as uow:
            value: str = uow.repository("limits").get_str(tenant_id, key, default)
            return value


class _StandaloneLimits:
    """`SystemLimits` portunun SESSİYADAN-KƏNAR tam tətbiqi (Faza 11).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `_RootLimitReader` KİFAYƏT ETMİR
    ──────────────────────────────────────────────────────────────────────────
    Yuxarıdakı körpü `LimitReader`-dir: yalnız `get_str`. `JobRunner` isə
    domenin `SystemLimits` PORTUNU gözləyir və dövrənin başında `all_for()`
    ilə TAM nüsxə oxuyur — dörd planlayıcı parametrini bir sorğuda alsın deyə
    (uzun icra ərzində Root dəyəri dəyişsə, eyni dövrənin işləri müxtəlif
    icarə müddəti ilə işləyərdi, bax `JobRunner.run_due`).

    Planlayıcı `Session`-dan UZUN yaşayır (GUI-də `QTimer`, CLI-da tək icra),
    ona görə repo-nu saxlaya bilməz — repo bağlantıya bağlıdır. Naxış
    `_RootLimitReader` ilə eynidir: `Database` saxlanılır, hər oxu üçün QISA
    bir iş vahidi açılır.

    PORTUN QALAN METODLARI DA TƏTBİQ OLUNUR (planlayıcı yalnız `all_for`
    çağırsa da): natamam obyekt `# type: ignore` tələb edərdi və o susdurma
    gələcəkdə port genişlənəndə ƏSL uyğunsuzluğu da gizlədərdi.

    ──────────────────────────────────────────────────────────────────────────
    OXU METODLARI AÇILIŞ TOPLUSUNA QOŞULUR (PERF-4)
    ──────────────────────────────────────────────────────────────────────────
    Planlayıcı taymeri məhz GİRİŞ anında qurulur (`_start_scheduler_timer`) və
    dövrənin uzunluğunu `all_for()` ilə oxuyur. Canlı ölçüdə bu TƏK oxu
    **2.08 saniyə** çəkirdi: sorğunun özü ~206 ms idi, qalanı hovuzdan İKİNCİ
    bağlantı almaq (~1.2 s) və ona RLS konteksti tətbiq etmək. Halbuki həmin
    anda `read_batch()` artıq bir bağlantı saxlayır.

    YAZI (`set_value`) VƏ `describe` TOPLUYA QOŞULMUR: toplu YALNIZ OXU
    üçündür (bax `read_batch` başlığı) — orada `commit()` bütün toplunu
    təsdiqləyərdi. `describe` isə nadir, ekran-tərəfi çağırışdır.
    """

    __slots__ = ("_batch", "_database")

    def __init__(self, database: TenantDatabase, *, batch: threading.local | None = None) -> None:
        self._database = database
        self._batch = batch

    def get_int(self, tenant_id: TenantId, key: str, default: int) -> int:
        batch = self._batch
        shared = _batch_limits(batch)
        if batch is not None and shared is not None:
            try:
                borrowed: int = shared.get_int(tenant_id, key, default)
            except Exception:
                _drop_batch(batch)
                raise
            return borrowed
        with self._database.unit_of_work(tenant_id) as uow:
            value: int = uow.repository("limits").get_int(tenant_id, key, default)
            return value

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
        batch = self._batch
        shared = _batch_limits(batch)
        if batch is not None and shared is not None:
            try:
                borrowed: str = shared.get_str(tenant_id, key, default)
            except Exception:
                _drop_batch(batch)
                raise
            return borrowed
        with self._database.unit_of_work(tenant_id) as uow:
            value: str = uow.repository("limits").get_str(tenant_id, key, default)
            return value

    def all_for(self, tenant_id: TenantId) -> dict[str, str]:
        batch = self._batch
        shared = _batch_limits(batch)
        if batch is not None and shared is not None:
            try:
                borrowed: dict[str, str] = shared.all_for(tenant_id)
            except Exception:
                _drop_batch(batch)
                raise
            return borrowed
        with self._database.unit_of_work(tenant_id) as uow:
            snapshot: dict[str, str] = uow.repository("limits").all_for(tenant_id)
            return snapshot

    def describe(self, tenant_id: TenantId) -> list[dict[str, object]]:
        with self._database.unit_of_work(tenant_id) as uow:
            rows: list[dict[str, object]] = uow.repository("limits").describe(tenant_id)
            return rows

    def set_value(
        self, tenant_id: TenantId, key: str, value: str, *, changed_by: EmployeeId
    ) -> None:
        # YAZI YOLU `commit` TƏLƏB EDİR — oxu metodlarında commit YOXDUR
        # (çıxışda rollback olur, oxu üçün doğru davranış). Bu qol planlayıcı
        # tərəfindən çağırılmır; portun tamlığı üçün var (bax sinif başlığı).
        with self._database.unit_of_work(tenant_id, user_id=changed_by) as uow:
            uow.repository("limits").set_value(tenant_id, key, value, changed_by=changed_by)
            uow.commit()


class _StandaloneAudit:
    """`AuditTrail` portunun SESSİYADAN-KƏNAR tətbiqi — planlayıcı üçün.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ AUDİT BURADA AYRI TRANZAKSİYADADIR
    ──────────────────────────────────────────────────────────────────────────
    Layihənin qaydası budur: audit sətri onu doğuran əməliyyatla EYNİ
    tranzaksiyada yazılır (`connection.py`-dakı `"audit"` qeydiyyatı). Bura
    həmin qaydanın istisnası DEYİL, ondan KƏNARDADIR: planlayıcının yazdığı
    sətir bir aqreqatın dəyişməsini deyil, DÖVRƏNİN ÖZÜNÜ qeyd edir ("7 iş
    icra olundu, biri uğursuz") və hər işin öz yazısı onsuz da öz sessiyasında
    commit olunub.

    Onu işlərin hər hansı birinin tranzaksiyasına bağlamaq mümkün deyil:
    dövrənin hesabatı BÜTÜN işlər bitəndən sonra hazır olur, o vaxta qədər
    həmin sessiyalar bağlanıb. Alternativ — dövrə boyu bir açıq tranzaksiya
    saxlamaq — CLAUDE.md §6-nın açıq qadağasıdır (`pg_dump` dəqiqələrlə çəkir).

    `AuditTrail.record()` İSTİSNA UDMUR (CLAUDE.md §5): burada da udulmur —
    xəta yuxarı çıxır və `JobRunner.run_due` çağıranına (CLI çıxış kodu / GUI
    log-u) çatır.
    """

    __slots__ = ("_database",)

    def __init__(self, database: TenantDatabase) -> None:
        self._database = database

    def record(
        self,
        *,
        tenant_id: TenantId,
        actor_id: EmployeeId | None,
        action: str,
        entity_type: str,
        entity_id: object | None = None,
        before_state: dict[str, object] | None = None,
        after_state: dict[str, object] | None = None,
        reason: str | None = None,
    ) -> None:
        with self._database.unit_of_work(tenant_id, user_id=actor_id) as uow:
            uow.audit.record(
                tenant_id=tenant_id,
                actor_id=actor_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                before_state=before_state,
                after_state=after_state,
                reason=reason,
            )
            uow.commit()


class _LazyBufferDrain:
    """`OfflineBufferDrain` — SQLite buferini YALNIZ ilk sorğuda açır.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ TƏNBƏL
    ──────────────────────────────────────────────────────────────────────────
    `Session` HƏR ekran əməliyyatında qurulur, `OfflineBuffer` konstruktoru
    isə SQLite faylı açır (WAL jurnalı, `PRAGMA`-lar, sxem icrası). Onu hər
    sessiyada açmaq bir iş günündə minlərlə fayl deskriptoru demək olardı —
    halbuki bufer YALNIZ baza keçidində (`DatabaseSwitchUseCase`) oxunur.

    ──────────────────────────────────────────────────────────────────────────
    XƏTA UDULMUR
    ──────────────────────────────────────────────────────────────────────────
    Bufer açıla bilmirsə istisna ÖTÜRÜLÜR. `0` qaytarmaq daha "yumşaq"
    görünərdi, lakin `_run_phases` addım 2-də məhz bu rəqəmə baxıb "bütün
    offline yazılar göndərildi" qərarını verir — yəni sükutlu `0` keçidi
    sinxronlaşmamış məlumat üzərində başladardı və həmin yazılar itərdi.
    """

    def __init__(self, limits: InfrastructureLimits) -> None:
        self._adapter: Any = None
        # Bufer `OFFLINE_RETRY_BACKOFF_SECONDS`/`OFFLINE_SQLITE_TIMEOUT_SECONDS`
        # oxuyur; pəncərə İNDİ ötürülür ki, Root dəyəri faktiki işləsin.
        self._limits = limits

    def _ensure(self) -> Any:
        if self._adapter is None:
            from src.infrastructure.offline.buffer import OfflineBuffer  # noqa: PLC0415
            from src.infrastructure.persistence.migration import (  # noqa: PLC0415
                BufferDrainAdapter,
            )
            from src.infrastructure.security.encryption import (  # noqa: PLC0415
                EncryptionService,
            )

            # AÇAR `.env.example`-dəki MÖVCUD `KOMPASOS_SQLITE_PATH`-dir.
            # Yeni ad (məs. `KOMPASOS_OFFLINE_BUFFER_PATH`) uydursaydıq, eyni
            # fayl üçün İKİ konfiqurasiya açarı yaranardı və quraşdırıcı
            # birini doldurub digərinin işlədiyini düşünərdi. Həmin açar
            # təyin olunubsa DAVRANIŞ EYNİDİR — o, hər şeydən üstündür.
            #
            # DEFOLT isə artıq `./data/...` DEYİL: cari qovluq paketlənmiş
            # `.exe`-də ixtiyaridir (System32 / Program Files) və orada SQLite
            # faylı YARADILA BİLMİR — offline bufer məhz ilk yazı anında
            # çökərdi. Köhnə `./data/offline_buffer.db` hələ mövcuddursa o
            # işlədilməyə davam edir (göndərilməmiş yazı itməsin) — səbəb və
            # niyə köçürmə edilmədiyi `shared/data_paths.py` başlığındadır.
            path = resolve_data_file("KOMPASOS_SQLITE_PATH", "offline_buffer.db")
            self._adapter = BufferDrainAdapter(
                OfflineBuffer(path, encryption=EncryptionService(), limits=self._limits)
            )
        return self._adapter

    def pending_count(self, tenant_id: TenantId) -> int:
        count: int = self._ensure().pending_count(tenant_id)
        return count

    def flush(self, tenant_id: TenantId) -> int:
        remaining: int = self._ensure().flush(tenant_id)
        return remaining

    @property
    def opened_buffer(self) -> Any:
        """ARTIQ açılmış buferi qaytarır, YOXDURSA `None` — AÇMIR.

        `v2backlog.md` Faza 5.1 planlayıcı işi buferin yaşını ölçür, LAKİN
        onu YARATMAMALIDIR: heç vaxt offline yazı olmamış quraşdırmada boş
        SQLite faylı yaratmaq «offline rejim var» təəssüratı verərdi və
        `_ensure()`-in bütün tənbəllik səbəbini (yuxarı) pozardı.
        """
        adapter = self._adapter
        return getattr(adapter, "buffer", None) if adapter is not None else None


class _LazyFaceEngine:
    """`CameraCapture` + `FaceMatcher` — mühərriki YALNIZ ilk üz əməliyyatında qurur.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ TƏNBƏL — ÖLÇÜLMÜŞ SƏBƏB
    ──────────────────────────────────────────────────────────────────────────
    `_LazyBufferDrain` ilə eyni naxış, lakin daha ağır qiymətlə: `import
    face_recognition` sətri modul səviyyəsində Dlib-in ÜÇ model faylını
    (68-nöqtə landmark, ResNet encoder, frontal detektor) yaddaşa yükləyir —
    bu maşında ölçülmüş qiymət ~1.0 saniyə və ~150 MB-dır.

    `Session` HƏR ekran əməliyyatında qurulur. Mühərriki orada birbaşa
    qursaydıq, həmin bir saniyə İLK sessiyaya — yəni tətbiqin açılışına —
    düşərdi, üstəlik Face Control əhatəsindən KƏNARDA qalan mağazalarda
    (bənd 15) həmin yük HEÇ VAXT istifadə edilməzdi.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ HƏR İKİ PORT BİR SİNİFDƏ
    ──────────────────────────────────────────────────────────────────────────
    İki ayrı proxy iki ayrı `face_engine()` çağırışı demək olardı — nəticə
    eyni olardı (kontekst onu keşləyir), lakin "kamera hansı nüsxədəndir?"
    sualı iki yerdən cavablanardı. Bir proxy = bir mənbə.
    """

    def __init__(self, resolve: Callable[[], tuple[Any, Any]]) -> None:
        self._resolve = resolve

    def is_available(self) -> bool:
        camera, _ = self._resolve()
        available: bool = camera.is_available()
        return available

    def capture(self, *, count: int = 1, gesture: Any = None) -> list[Any]:
        camera, _ = self._resolve()
        frames: list[Any] = camera.capture(count=count, gesture=gesture)
        return frames

    def extract(self, frame: Any, *, gesture: Any = None) -> Any:
        _, matcher = self._resolve()
        return matcher.extract(frame, gesture=gesture)

    def distance(self, reference: Any, candidate: Any) -> float:
        _, matcher = self._resolve()
        result: float = matcher.distance(reference, candidate)
        return result


class StartupFailureKind(str, Enum):
    """Başlanğıc uğursuzluğunun NÖVÜ — ekran davranışını bu təyin edir (DB-4 Faza 4).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ TƏK MƏTN KİFAYƏT ETMİR
    ──────────────────────────────────────────────────────────────────────────
    Əvvəl bütün başlanğıc xətaları eyni fatal ekrana, eyni tək mətnlə düşürdü.
    Nəticədə üç TAMAMİLƏ FƏRQLİ vəziyyət eyni görünürdü:

        * server müvəqqəti əlçatmazdır → doğru hərəkət YENİDƏN CƏHDDİR;
        * bağlantı heç vaxt konfiqurasiya edilməyib → doğru hərəkət
          AYARLARI DAXİL ETMƏKDİR (təkrar cəhd HEÇ VAXT işləməyəcək);
        * parol dəyişib/açılmır → yenə ayarlar, lakin BAŞQA səbəblə.

    İstifadəçi ekranda «internetinizi yoxlayın» görüb şəbəkəni yoxlayırdı,
    halbuki `connection.json` faylı ümumiyyətlə yox idi. Növ bu üç halı
    ayırır və hər birinə DÜZGÜN düyməni verir.

    `str, Enum` — layihə konvensiyası (CLAUDE.md §4): `.value` audit/log
    çıxışında sabit qalır.
    """

    #: Server/şəbəkə əlçatmazdır — konfiqurasiya DÜZGÜNDÜR.
    DATABASE_UNREACHABLE = "DATABASE_UNREACHABLE"
    #: Heç bir mənbədə bağlantı məlumatı yoxdur (`DATABASE_URL` və fayl boş).
    CREDENTIALS_MISSING = "CREDENTIALS_MISSING"
    #: Məlumat VAR, lakin işləmir: parol yanlış, fayl korlanıb, açar dəyişib.
    CREDENTIALS_INVALID = "CREDENTIALS_INVALID"
    #: Quraşdırma kimliyi (`installation.json`) oxuna/yazıla bilmədi.
    IDENTITY_UNAVAILABLE = "IDENTITY_UNAVAILABLE"

    @property
    def is_configuration_problem(self) -> bool:
        """Bağlantı Ayarları ekranı KÖMƏK EDƏRMİ.

        Şəbəkə nasazlığında ayarları açmaq istifadəçini düzgün olan dəyərləri
        «düzəltməyə» sövq edərdi — yəni işləyən konfiqurasiyanı pozardı.

        DİQQƏT — bu xassə HAZIRDA heç bir ekran seçimini idarə ETMİR:
        «Yenidən Cəhd Et» artıq HEÇ VAXT ayarlar ekranını açmır (səbəb
        `app.py::_on_startup_failed` içindədir). Xassə TƏSNİFATIN
        özü kimi qalır — nasazlığın konfiqurasiyadan, yoxsa mühitdən gəldiyini
        ayırır və jurnal/test bu ayrımı işlədir. Ona ekran bağlamazdan əvvəl
        həmin şərhi oxuyun.
        """
        return self in {
            StartupFailureKind.CREDENTIALS_MISSING,
            StartupFailureKind.CREDENTIALS_INVALID,
        }


class StartupError(KompasOSError):
    """Tətbiq işə düşə bilmədi — fatal başlanğıc ekranı göstərilir.

    Bölmə 8 (EHTİYAT DƏSTƏK KANALI): "hər fatal başlanğıc-xətası ekranında
    statik e-poçt ünvanı göstərilir" — çünki tətbiq açılmırsa müştəri
    tətbiq-daxili chat-ə çata bilmir.
    """

    user_message = "KompasOS işə düşə bilmədi."

    def __init__(
        self,
        message: str,
        *,
        user_message: str | None = None,
        context: dict[str, Any] | None = None,
        kind: StartupFailureKind = StartupFailureKind.DATABASE_UNREACHABLE,
    ) -> None:
        super().__init__(message, user_message=user_message, context=context)
        self.kind = kind
        # Növ log-a da düşür: dəstək zəngində «hansı ekran göründü?» sualının
        # cavabı jurnaldan oxunmalıdır, istifadəçinin yaddaşından yox.
        self.context.setdefault("failure_kind", kind.value)


@dataclass
class Session:
    """Bir tranzaksiya ərzində qurulmuş use case dəsti.

    Sahələr `Any`-dir: repo-lar Protocol-lara UYĞUNLAŞIR (miras almır) və
    hər birini konkret tiplə annotasiya etmək bu faylı 60 sətir `cast`-a
    çevirərdi. Tip təhlükəsizliyi use case-lərin ÖZ imzalarındadır.
    """

    uow: PostgresUnitOfWork
    tenant_id: TenantId

    leave_verification: LeaveVerificationUseCase
    morning_check_in: MorningCheckInUseCase
    shift_planning: ShiftPlanningUseCase
    shift_swaps: ShiftSwapUseCase
    # --- #16 Açıq Növbə Bazarı (kompasos11.md Faza 6) ----------------------- #
    #
    # `shift_swaps` ilə YAN-YANA dayanır, lakin ONDAN ASILI DEYİL: bu, ayrı
    # axındır (admin elan edir → ilk basan işçi tutur). Ortaq olan yeganə şey
    # `shift_planning`-dir — təqvimin yeganə yazma nöqtəsi.
    open_shifts: OpenShiftMarketUseCase
    daily_attendance: DailyAttendanceSheetUseCase
    manual_fines: ManualFineUseCase
    fine_appeals: FineAppealUseCase
    # --- Aylıq Cərimə İcmalı (bölmə 4, miqrasiya 003) ----------------------- #
    #
    # `FineStatus.PUBLISHED`-ə YEGANƏ yol budur. Use case ARTIQ yazılmışdı,
    # lakin `Session`-a qoşulmamışdı — yəni onu çağıracaq bir yol YOX idi və
    # zəncir bütövlükdə ölü qalırdı: cərimə `PENDING_REVIEW` doğulur → nəşr
    # olunmur → işçi onu görmür → etiraz pəncərəsi açılmır
    # (`appeal_window_closes_at` YALNIZ nəşrdə dolur) → `EXPORTABLE_STATUSES`
    # heç vaxt ödənmir, yəni HEÇ BİR cərimə maaşdan kəsilmir.
    #
    # `manual_fines` ilə YAN-YANA dayanır və ONDAN ASILI DEYİL: biri cəriməni
    # YARADIR (kamera-tipli rol, `can_issue_fines`), digəri onu AÇIR
    # (`can_publish_fines`, kamera roluna HEÇ VAXT verilmir — miqrasiya 003,
    # `excludes_camera_role`). İkisini bir use case-ə yığmaq vəzifə
    # ayrılığını kodda görünməz edərdi.
    fine_review: MonthlyFineReviewUseCase
    tasks: TaskWorkflowUseCase
    sales_points: SalesPointsUseCase
    reports: MonthlyReportUseCase
    audit_query: AuditQueryUseCase
    users: UserManagementUseCase
    positions: PositionManagementUseCase
    support: SupportChatUseCase
    # CHAT-1: eyni cədvəlin CAVABLAYAN ucu — «Daxili Müraciətlər» və
    # «Texniki Dəstək» bölmələri. İki bölmə, TƏK use case (kanal arqumentdir).
    support_inbox: SupportInboxUseCase
    telegram_config: TelegramConfigUseCase
    sync_conflicts: SyncConflictUseCase
    devices: DeviceRegistryUseCase
    branding: TenantBrandingUseCase
    setup: FirstRunSetupUseCase
    root_control: RootControlUseCase
    permission_guard: PermissionHierarchyGuardUseCase

    # --- Faza 5/6 ekranlarının arxası -------------------------------------- #
    #
    # Bu use case-lər ARTIQ yazılmışdı, lakin `Session`-a qoşulmamışdı — yəni
    # onları çağıracaq bir yol YOX idi və ekranlar boş qalırdı
    # (`tests/unit/test_screen_binding_coverage.py::PENDING_LIVE_BINDING`).
    # Onları burada qurmaq "ekran → use case" zəncirinin tək əskik halqası idi.
    work_modes: WorkModeCatalogUseCase
    fine_types: FineTypeCatalogUseCase
    leave_types: LeaveTypeCatalogUseCase
    backups: BackupAccessUseCase
    plugins: PluginManagementUseCase
    dashboard_layout: DashboardLayoutUseCase
    db_switch: DatabaseSwitchUseCase
    sales_review: SalesReviewQueueUseCase
    employee_profile: EmployeeProfileAccessUseCase
    erp_connections: ErpConnectionWizardUseCase
    # --- 1C konfiqurasiyasının OXU yolu (1c.md GUI fazası) ------------------ #
    #
    # `erp_connections` ilə EYNİ repo obyekti, lakin AYRI rol: sihirbaz mövcud
    # serveri redaktəyə açanda növə xas parametrləri (COM sorğu ayarları, fayl
    # sütun adları) formaya yükləməlidir. Use case-də belə bir metod YOXDUR və
    # onu ora əlavə etmək use case-i "sahə oxuyucusu"na çevirərdi (eyni əsas
    # `refresh()`-in siyahını birbaşa oxumasında izah olunub).
    #
    # SİRR EKRANA GETMİR: kontroller yalnız `ConnectorConfig.public_values()`
    # ötürür (bax `controllers/erp_servers.py` başlığı) və hər oxunuş
    # `security.log`-a `ERP_CREDENTIALS_ACCESSED` sətri yazır.
    erp_server_configs: ErpServerRepository

    # --- Vahid İstisna Motoru (#9, Faza 3) ---------------------------------- #
    #
    # Motor İNDİ #8-in `BehaviorAnomalyRule`-u ilə qeydiyyatlı qurulur (Faza 5,
    # bax `_build_session`-dəki `register_rule(...)` çağırışı) — motorun ÖZÜ
    # (`exception_engine.py`) DƏYİŞMƏDƏN qaldı, rule-registry məhz bunun üçün
    # seçilmişdi.
    #
    # `run()` Faza 11-ə qədər HEÇ VAXT ÇAĞIRILMIRDI: motor yazılıb, test edilib
    # və buraya qoşulub, lakin onu tətikləyən yol yox idi — nəticədə #9
    # İstisnalar ekranı həmişə boş qalırdı. İndi `EXCEPTION_ENGINE_RUN`
    # planlaşdırılmış işi onu gündəlik işlədir (`_register_scheduled_jobs`).
    exceptions: ExceptionEngineUseCase

    # --- #7 POS Səlahiyyət Siyasəti (sənədləşdirmə, kompasos11.md Faza 4) --- #
    #
    # YALNIZ statik siyasət qeydi: 1C-yə bağlantı yoxdur, Vahid İstisna
    # Motoruna heç nə göndərmir (struktur qərar A). `UsersScreen`-in "POS
    # Səlahiyyəti" bəndi bunu çağırır (bax `controllers/pos_threshold.py`).
    pos_threshold: POSThresholdUseCase

    # --- #17 İşçi Sənədləri (kompasos11.md Faza 7) --------------------------- #
    #
    # `UsersScreen`-in "Sənədlər" bəndi bunu çağırır (bax
    # `controllers/employee_documents.py`). `shift_planning`-in `documents`
    # asılılığı (`DocumentComplianceAdvisor`) da EYNİ repo-nu işlədir — bax
    # aşağıdakı `planning = ShiftPlanningUseCase(...)` qurulması.
    employee_documents: EmployeeDocumentUseCase

    # --- #19 Elan (Broadcast) (kompasos11.md Faza 8) ------------------------- #
    #
    # `screens/announcements.py`-in YAZI (yayımla/geri çək) VƏ OXU (admin
    # siyahısı) yolu; İşçi Ana Ekranının kart oxuşu da EYNİ obyektdəndir
    # (`controllers/announcements.py::EmployeeAnnouncementController`).
    announcements: AnnouncementUseCase

    # --- #20 Performans Qiymətləndirməsi (kompasos11.md Faza 8) -------------- #
    #
    # `screens/performance_review.py`-in YAZI yolu; işçinin ÖZ tarixçəsi
    # (`group_g.ProfileScreen`) da EYNİ obyektin `list_own()` metodundan gəlir.
    performance_reviews: PerformanceReviewUseCase

    # --- #8 İşçi Davranış Baz Xətti (kompasos11.md Faza 5) ------------------ #
    #
    # EKRANI YOXDUR — `recalculate_all()` planlaşdırılmış işdir
    # (`docs/scheduler_setup.md`, `fine_management.expire_stale` ilə eyni
    # naxış). Faza 11-dən etibarən onu `BEHAVIOR_BASELINE_RECALC` işi ÇAĞIRIR
    # (bax `_register_scheduled_jobs`) və məhz ona görə `EXCEPTION_ENGINE_RUN`
    # -dan ƏVVƏL qeydiyyatdan keçir; qayda özü `exceptions` sahəsinə artıq
    # qoşulub (yuxarı bax).
    behavior_baselines: BehaviorBaselineUseCase

    # --- #15 Norma üstü iş saatları (kompasos11.md Faza 6) ------------------ #
    #
    # ƏSAS YOLU `daily_attendance`-dır: tabel təsdiqləndikdə aşım avtomatik
    # yazılır (bax `daily_attendance.py` başlığı). Sahə isə OXU yolunu açır —
    # `overtime_for_period()` HR hesabatı üçün `can_view_employee_reports`
    # tələb edir. İkisi ayrı olmasaydı, hesabata baxmaq istəyən HR təsadüfən
    # yenidən-hesablamanı işə salardı.
    overtime: OvertimeTrackingUseCase

    # --- #13 Tarixi-nümunə kadr təklifi (kompasos11.md Faza 6) -------------- #
    #
    # İKİ YOLU VAR: `recalculate_for_store()` planlaşdırılmış işdir
    # (`STAFFING_PATTERN_REFRESH` — hər AKTİV mağaza üçün ayrıca çağırılır,
    # bax `_job_staffing_pattern`), `suggestions_for()` isə Növbə
    # Matrisi ekranının məsləhət kartını doldurur. Təklif HEÇ NƏ bloklamır və
    # HEÇ NƏ təyin etmir — `shift_planning`-ə çağırışı YOXDUR və olmamalıdır
    # (kompasos11.md #13: "qeyri-məcburi göstərici").
    staffing_pattern: StaffingPatternUseCase

    # --- #21 İşdən Çıxma Riski Balı (kompasos11.md Faza 9) ------------------ #
    #
    # İKİ YOLU VAR: `recalculate_all()` planlaşdırılmış gecəlik iş
    # (`ATTRITION_RISK_RECALC`), `list_for_tenant()` isə
    # `screens/attrition_risk.py`-in `can_view_attrition_risk` OXU yolu
    # (bax `controllers/attrition_risk.py`). Bildiriş zənciri (Store Manager
    # → HR_Admin) `recalculate_all()`-ın DAXİLİNDƏDİR — ekranın YOXDUR.
    attrition_risk: AttritionRiskUseCase

    # --- #24 Çox-Mağaza Benchmark Dashboard (kompasos11.md Faza 9A) --------- #
    #
    # YALNIZ OXU YOLU — bu widget-lər `controllers/screen_data.py`-dan
    # bağlanır, ÖZ kontrolleri YOXDUR (bax use case modul başlığı). Dörd
    # metod (`ranking`/`store_vs_network`/`trend`/`outliers`) TƏK repo
    # (`multi_store_benchmark`) üzərində işləyir.
    multi_store_benchmark: MultiStoreBenchmarkUseCase

    # --- #26+#27 Sahə hesabatları (kompas1.md Faza 3) ----------------------- #
    #
    # VAHİD NÜVƏ, İKİ ŞABLON (Struktur Qərar A): mağaza auditi və insident
    # bildirişi EYNİ use case-dən keçir, fərq kataloqdadır. İKİNCİ sahə
    # (`field_reports_incident` kimi) BURADA OLMAMALIDIR — o, qərarı
    # kompozisiya kökünə sızdırardı.
    #
    # `TaskWorkflowUseCase`-i ASILILIQ kimi alır (Struktur Qərar B): uğursuz
    # bloklayıcı bənd mövcud Tapşırıq Mühərrikini çağırır, yeni motor yazmır.
    # `notify_overdue_audits()` isə `FIELD_REPORT_AUDIT_REMINDER` gecəlik
    # işinin girişidir (bax `_register_scheduled_jobs`).
    field_reports: FieldReportUseCase

    # --- #28 İllik Məzuniyyət Balansı (kompas1.md Faza 4) ------------------- #
    #
    # ÜÇÜNCÜ, AYRI MEXANİZM. Sessiyada onsuz da olan `leave_verification`
    # (STEP1/STEP2 gündaxili icazə, DƏQİQƏ) və `shift_planning` (Shift Matrix
    # istirahət günü, PLAN) ilə QARIŞDIRILMAMALIDIR — bu, GÜN əsaslı illik
    # haqqdır (bax `entities/annual_leave.py` başlığı). Hər üçü eyni sessiyada
    # yaşayır, lakin bir-birini ÇAĞIRMIR.
    #
    # `shifts=repo("shifts")`: Shift Matrix YALNIZ OXUNUR — hansı günün
    # istirahət olduğunu bilmək üçün. Təsdiqlənmiş məzuniyyət növbə planını
    # DƏYİŞMİR (`ShiftSwapUseCase.approve`-dan qəsdən fərqli).
    #
    # `run_year_rollover()` isə `ANNUAL_LEAVE_YEAR_ROLLOVER` gecəlik işinin
    # girişidir (bax `_register_scheduled_jobs`).
    annual_leave: AnnualLeaveUseCase

    # --- #29 Toplu Əməliyyatlar (kompas1.md Faza 5) -------------------------- #
    #
    # CSV işçi idxalı VƏ mağaza şablonu AYRI SAHƏLƏRDİR (iki AYRI use case),
    # lakin İKİSİ DƏ `can_perform_bulk_operations`-a bağlıdır (bax
    # `bulk_operations.py` başlığı). CSV idxalının SƏTİR-SƏTİR yazı yolu
    # (`create_employee()`-ə çağırış) `_build_session`-dəki
    # `_bulk_create_employee_row` closure-udur — bax orada, "TRANZAKSİYA
    # SƏRHƏDİ".
    bulk_employee_import: BulkEmployeeImportUseCase
    store_templates: StoreTemplateUseCase

    # --- #30 Planlaşdırılmış İcra Xülasəsi (kompas1.md Faza 6) --------------- #
    #
    # İKİ YOLU VAR: `configure`/`deactivate`/`list_for_management` Root Control
    # Center-in `can_configure_executive_digest` yazı yoludur, `run()` isə
    # `EXECUTIVE_DIGEST_RUN` gecəlik işinin girişidir (bax `_register_
    # scheduled_jobs`). Metriklər YENİ hesablanmır — `multi_store_benchmark`
    # provayderi VƏ `exceptions` portu ÇAĞIRILIR (bax use case modul başlığı,
    # "1C SƏRHƏDİ").
    executive_digest: ExecutiveDigestUseCase

    # --- HR-D/A/E/F/G Export təcrübəsi (kompas1.md Faza 8) ------------------ #
    #
    # `reports` (MonthlyReportUseCase) ilə YAN-YANA, ONDAN ASILI DEYİL: sətir
    # hesablaması ORADA qalır (Faza 7-nin `work_norm` zənciri toxunulmur), bu
    # sahə isə həmin sətirlərin ÜZƏRİNDƏ dörd yeni sual verir — şübhəli sətir,
    # manual düzəliş, dövr-müqayisəsi, rol filtri.
    #
    # İKİ AYRI SAHƏ NİYƏ: `reports` YALNIZ oxuyur və heç bir cədvələ yazmır;
    # bu isə `export_manual_corrections`-a YAZIR və audit doğurur. Birləşdirmək
    # hesabat çıxarmaq (mühasib) ilə tabeli dəyişmək (HR) məsuliyyətlərini
    # bir obyektdə qarışdırardı.
    export_preflight: ExportPreflightUseCase

    # --- Face Control — üz təsdiqi (facecontrol.md, Faza 2 + Faza 3) --------- #
    #
    # BEŞ USE CASE-in HAMISI QOŞULUB. Faza 2-də yalnız ikisi (istisna + jurnal
    # təmizləməsi) qoşulmuşdu, çünki qalan üçü `FaceMatcher`/`CameraCapture`
    # portlarını tələb edir və onların adapterləri Faza 3-dədir. Faza 3 həmin
    # adapterləri (`infrastructure/security/face_matcher.py`,
    # `infrastructure/kiosk/camera.py`) əlavə etdi və siyahı tamamlandı.
    #
    # ADAPTERLƏR `ApplicationContext.face_engine()`-dƏN GƏLİR, burada
    # qurulmur: kamera FİZİKİ cihazdır və `Session` hər əməliyyatda yenidən
    # qurulduğu üçün burada açsaydıq, hər ekran hərəkəti ikinci `VideoCapture`
    # yaradıb cihazı bloklayardı.
    #
    # Nəzarətli qeydiyyat (bənd 1) — `can_manage_employees` + ÖZÜNƏ-qeydiyyat
    # qadağası (qayda use case-dədir).
    face_enrollment: FaceEnrollmentUseCase
    # Yenidən-qeydiyyat (bənd 2) — köhnə vektor `REPLACED` statusu ilə arxivə
    # düşür, səbəb MƏCBURİDİR.
    face_re_enrollment: FaceReEnrollmentUseCase
    # Üz qapısı (bənd 3–7, 9, 12, 15, 18). MÖVCUD PIN axınının İÇİNƏ
    # yazılmır — `morning_check_in`/`leave_verification` imzaları toxunulmaz
    # qaldı; qapı onların ÖNÜNDƏ, kiosk kontrollerindən çağırılır.
    face_verification: FaceVerificationUseCase
    # İstisnaların idarəsi (bənd 14) — YALNIZ Root/CEO
    # (`can_manage_face_exemptions`, hardlock 2). `expire_due()` isə
    # `FACE_EXEMPTION_EXPIRY` gecəlik işinin girişidir.
    face_exemptions: FaceControlExemptionUseCase
    # Üz kilidinin VAXTINDAN ƏVVƏL açılması (bənd 4-ün ödənilməmiş tərəfi) —
    # EYNİ səlahiyyət qapısı (`can_manage_face_exemptions`, hardlock 2), çünki
    # hər ikisi konkret işçi üçün üz qapısını yumşaldır (bax
    # `FaceLockReleaseUseCase` başlığı: `can_manage_employees` niyə rədd edildi).
    face_lock_release: FaceLockReleaseUseCase
    # Doğrulama jurnalının saxlama müddəti (bənd 17) — `FACE_LOG_RETENTION`
    # gecəlik işinin girişi. EKRANI YOXDUR (`behavior_baselines` ilə eyni
    # naxış): yeganə çağırış nöqtəsi planlayıcıdır.
    face_log_retention: FaceVerificationLogRetentionUseCase

    # --- SEC-011 sessiya müddəti (SEC-5 iş müqaviləsi) ----------------------- #
    #
    # `issue`/`validate`/`touch`/`revoke` — `app.py::_start_session_guard`
    # (giriş, `SessionGuard.touch`) və `controllers/profile.py::
    # _on_close_sessions` (uzaqdan ləğv) buradan keçir. `AuthSessionRepository`
    # portu domen tipi (`AuthSession`) qaytardığı üçün `ports.py`-dadır.
    sessions: SessionManagementUseCase

    # --- `v2backlog.md` Faza 3.3/3.4 — HR lifecycle (köçürmə + offboarding) - #
    #
    # Filiallar-arası daimi köçürmə sorğusu (`ShiftSwapUseCase` ilə EYNİ
    # forma) VƏ struktur offboarding checklist-i — EKRANLARI HƏLƏ YOXDUR
    # (ayrıca tapşırılacaq), bura yalnız obyekt qrafı qurulub ki, gələcək
    # kontroller onları `Session`-dan bir addımda ala bilsin.
    #
    # `offboarding_checklists`: `checklist_templates` İLƏ EYNİ repo-nu
    # (`checklist_item_templates`) PAYLAŞIR, ad məkanı `owner_type`/
    # `owner_key` ilə ayrılır (bax `catalog_management.py` başlığı).
    # `start_checklist()` HƏLƏLİK `users.deactivate_employee()`-dən
    # ÇAĞIRILMIR — `UserManagementUseCase`-də bu portu qəbul edən açar söz
    # yoxdur (bax `_build_session`-dəki qurulma yerinin şərhi).
    transfer_requests: TransferRequestUseCase
    checklist_templates: ChecklistItemTemplateUseCase
    offboarding_checklists: EmployeeOffboardingChecklistUseCase

    # `v2backlog.md` Faza 5.3/5.4 — növbə təhvili qeydi və fövqəladə giriş.
    # İKİSİ DƏ `Session`-dadır (ayrı, uzun-ömürlü obyekt DEYİL), çünki hər
    # ikisi YAZI yoludur və repo-lar bağlantıya bağlıdır (CLAUDE.md §6).
    # Break-glass üçün bu, əlavə məna daşıyır: qrantın statusu ilə audit
    # sətri EYNİ tranzaksiyada yazılır.
    shift_handoffs: ShiftHandoffUseCase
    break_glass: BreakGlassUseCase

    # `v2backlog.md` Faza 6.4 — kampaniya dövrləri (Root/CEO yazı yolu).
    # `Session`-dadır, çünki repo bağlantıya bağlıdır və audit EYNI
    # tranzaksiyada olmalıdır (`shift_handoffs` ilə eyni əsaslandırma).
    campaign_periods: CampaignPeriodsUseCase

    def commit(self) -> None:
        self.uow.commit()

    @property
    def preferences(self) -> Any:
        """`user_preferences` repo-su — tema və dashboard düzülüşü."""
        return self.uow.repository("preferences")

    @property
    def report_facts(self) -> Any:
        """Hesabat rəqəmlərinin SQL mənbəyi."""
        return self.uow.repository("report_facts")

    @property
    def export_roster(self) -> Any:
        """Kadr vəziyyəti + rol kodu (kompas1.md Faza 8, bəndlər A və G).

        `report_facts` ilə EYNİ obyektə YÖNƏLMİR: bu, `export_correction_
        repository.py`-dəki AYRI sinifdir. Səbəb orada izah olunub — biri PUL
        sətirlərinin, digəri META məlumatın (kim aktivdir, kim nəyi düzəldib)
        mənbəyidir və birinin sorğusuna toxunmaq digərinin rəqəmini
        dəyişməməlidir.
        """
        return self.uow.repository("export_roster")

    @property
    def limits(self) -> Any:
        return self.uow.repository("limits")

    @property
    def toggles(self) -> Any:
        return self.uow.repository("toggles")

    @property
    def notifications(self) -> Any:
        """Header zəngi + bildiriş panelinin oxu yolu (bölmə 7).

        Use case YOXDUR və bu, qəsdəndir: siyahını göstərmək və sətri
        "oxundu" etmək heç bir iş qaydası daşımır (səlahiyyət yoxlaması,
        status keçidi, hesablama yoxdur). Bunun üçün use case yaratmaq
        `screen_data._fines`-də izah edilən səhvin təkrarı olardı — use
        case-i göstəriş vasitəsinə çevirmək.
        """
        return self.uow.repository("notifications")

    def max_upload_bytes(self) -> int:
        """`system_limits.MAX_UPLOAD_SIZE_BYTES` (bölmə 3, defolt 5 MB).

        `ApplicationContext.run_evidence_uploads()` hər dövrədə bunu oxuyur və
        `DriveProviderFactory`-yə ötürür ki, şəkil həddi koda deyil, ROOT
        İdarə Mərkəzinə bağlı olsun. `google_drive.MAX_UPLOAD_BYTES` yalnız
        fallback-dır (limit mənbəyi olmayan yollar üçün).
        """
        key = SystemLimitKey.MAX_UPLOAD_SIZE_BYTES
        limit: int = self.limits.get_int(self.tenant_id, key.value, int(DEFAULT_LIMITS[key]))
        return limit


def _cooldown_elapsed(raw: str | None, *, now: datetime, hours: int) -> bool:
    """Təkrar-susma pəncərəsi bitibmi (Faza 5.2).

    Yazı YOXDURSA və ya OXUNMURSA `True` — naməlum vəziyyətdə xəbərdarlıq
    göndərmək, göndərməməkdən yaxşıdır (`OfflineBacklogMonitor.should_alert`
    ilə eyni qərar).
    """
    if raw is None:
        return True
    try:
        last = datetime.fromisoformat(raw)
    except ValueError:
        return True
    return now - last >= timedelta(hours=hours)


class ApplicationContext:
    """Tətbiqin canlı obyekt qrafı — `main.py --gui` bunu qurur."""

    def __init__(
        self,
        *,
        database: TenantDatabase,
        tenant_id: TenantId,
        license_client: LicenseClient | None = None,
        ntp: NtpVerifier | None = None,
        self_hosted: bool = False,
    ) -> None:
        self._database = database
        self._tenant_id = tenant_id
        self._license = license_client
        #: `read_batch()` üçün SAPA GÖRƏ paylaşılan sessiya (PERF-3).
        #: Qlobal olsaydı fon sapları eyni bağlantını paylaşardı — səbəbi
        #: həmin metodun izahındadır.
        self._read_batch = threading.local()
        # ──────────────────────────────────────────────────────────────────
        # `self_hosted` NİYƏ AYRI BAYRAQDIR
        # ──────────────────────────────────────────────────────────────────
        # Sihirbaz `license_tenants` sətrini YALNIZ bu bayraq açıq olduqda
        # yaradır. Lisenziyalı quraşdırmada (identifikator təchizatçıdan
        # gəlir) sətir onsuz da mövcuddur; mövcud deyilsə isə onu BURADAN
        # yaratmaq lisenziya qapısını yan keçmək olardı — pulsuz "AKTIV"
        # tenant yaratmağın yolu məhz belə açılır. Ona görə həmin halda
        # sihirbaz açıq xəta verir, sükutla sətir YARATMIR.
        self._self_hosted = self_hosted
        # NTP yoxlayıcısı verilməyibsə `_NullNtp` işlədilir: o, HƏMİŞƏ
        # "təsdiqlənməyib" qaytarır, lakin sürüşmə ÖLÇÜLMƏYİB deyir. Nəticədə
        # `TIME_DRIFT_DETECTED` bloku işə DÜŞMÜR (ölçmə yoxdur, hədd
        # müqayisə edilə bilmir) — ölçə bilməmək əməliyyatı dayandırmamalıdır.
        self._ntp: NtpVerifier = ntp or _NullNtp()
        # Sübut yükləmə qatı TƏNBƏLdir: növbə SQLite faylı və Drive klienti
        # yalnız ilk cərimə/ilk dövrə zamanı yaradılır. Örtük açılışını
        # şəbəkəyə və diskə bağlamamaq üçün belədir.
        self._evidence_queue: Any = None
        self._drive_factory: Any = None
        self._drive_limit: int | None = None
        # Offline bufer də TƏNBƏLdir və eyni səbəbdəndir: `Session` HƏR
        # əməliyyatda qurulur, bufer konstruktoru isə SQLite faylı açır (WAL
        # jurnalı + sxem icrası). Hər sessiyada yeni bağlantı açmaq dəstək
        # tutumunu tükəndirərdi — halbuki bufer YALNIZ baza keçidində lazımdır.
        self._offline_drain: Any = None
        # Planlayıcı da TƏNBƏLdir və eyni səbəbdəndir: reyestr qurulanda hər
        # iş üçün bir log sətri yazılır və `PostgresScheduledJobRepository`
        # `Database`-ə bağlanır. Önizləmə/dizayn rejimində və ilk dövrəyə
        # qədər bunlara ehtiyac yoxdur. TƏK NÜSXƏ olması isə MƏCBURİDİR:
        # ikinci `JobRunner` ikinci `instance_id` demək olardı və eyni proses
        # öz icarəsini "başqasının" kimi görərdi.
        self._job_runner: Any = None
        # Üz təsdiqi mühərriki də TƏNBƏLdir və səbəbi ən ağırıdır: `face_
        # recognition` idxalı Dlib-in üç model faylını (68-nöqtə landmark,
        # encoder, detektor) yükləyir və `cv2.VideoCapture` cihaz açılışı
        # Windows-da bir saniyəyə qədər çəkir. Örtük açılışında hər ikisini
        # etmək bütün mağazalara — o cümlədən Face Control əhatəsindən kənarda
        # qalanlara (bənd 15) — bu qiyməti ödədərdi.
        #
        # TƏK NÜSXƏ olması MƏCBURİDİR: `Session` HƏR əməliyyatda yenidən
        # qurulur, kamera isə fiziki cihazdır — hər sessiyada ikinci
        # `VideoCapture` açmaq cihazı bloklayardı.
        self._face_engine: tuple[Any, Any] | None = None
        # Vendor break-glass bildiricisi (Faza 5.4). MÜŞTƏRİ QURAŞDIRMASINDA
        # `None` QALIR VƏ BU, GÖZLƏNİLƏN HALDIR — DB-3 qərarı (bax
        # `connection_types.py` başlığı): müştəri vendor bazasına nə yazır,
        # nə oxuyur. Bildirici yalnız `KOMPASOS_VENDOR_DSN` təyin edilmiş
        # mühitdə (təchizatçının maşını, staging) qurulur.
        #
        # BİR DƏFƏ, TƏNBƏL qurulur: `VendorDatabase.from_env()` hovuz açır və
        # onu hər `Session` üçün təkrarlamaq dəstək tutumunu yeyərdi.
        # `False` = «cəhd edildi, yoxdur» (təkrar cəhd edilmir); `None` =
        # «hələ cəhd edilməyib».
        self._break_glass_reporter_cache: Any = None
        # İnfrastruktur pəncərəsi BİR DƏFƏ qurulur və paylaşılır: obyekt
        # vəziyyət saxlamır (nə keş, nə bağlantı), yalnız `Database` + tenant
        # daşıyır — hər istehlakçı üçün yenisini qurmaq eyni nəticəni verər,
        # lakin "hansı nüsxə doğrudur" sualını yaradardı.
        self._infrastructure_limits = InfrastructureLimits(
            limits=_RootLimitReader(database, batch=self._read_batch), tenant_id=tenant_id
        )
        # ──────────────────────────────────────────────────────────────────
        # VAXT SERVER LÖVBƏRLİDİR (TIME-1)
        # ──────────────────────────────────────────────────────────────────
        # Əvvəl burada — yuxarıda, `self_hosted` sətrinin yanında —
        # `SystemClock()`, yəni Windows saatı vardı. Bütün domen qatı `Clock`
        # portundan oxuduğu üçün həmin BİR sətir bütün davamiyyət, cərimə və
        # timeout hesabını mağaza PC-sinin saatına bağlayırdı: saatı 20 dəqiqə
        # geri çəkmək gecikməni və onun cəriməsini silərdi.
        #
        # İndi vaxt Postgres `clock_timestamp()`-dan lövbərlənir, aradakı
        # müddət isə `time.monotonic()` ilə ölçülür — sistem saatının
        # dəyişməsi nəticəyə TƏSİR ETMİR.
        #
        # QURULMA YERİ QƏSDƏN BURADIR, `__init__`-in SONUNDA: servis
        # `_infrastructure_limits`-dən asılıdır (sinxronizasiya intervalı ROOT
        # parametridir) və o, yuxarıdakı sətirdə yenicə qurulur.
        #
        # `SystemClock` yox olmur — lövbər hələ alınmayıbsa (tətbiqin ilk
        # anları, baza əlçatmaz) FALLBACK odur; həmin halda
        # `time_integrity_status()` `UNTRUSTED` qaytarır, yəni sistem
        # bilmədiyini GİZLƏTMİR.
        self._server_time = ServerTimeService(
            probe=PostgresServerTimeProbe(database),
            fallback_clock=SystemClock(),
            limits=self._infrastructure_limits,
            machine_name=socket.gethostname(),
            on_manipulation=self._on_clock_manipulation,
        )
        self._clock: Clock = self._server_time

    @property
    def database(self) -> TenantDatabase:
        return self._database

    @property
    def self_hosted(self) -> bool:
        """Tenant identifikatoru bu maşında yaranıb (lisenziya qeydi yoxdur)."""
        return self._self_hosted

    def infrastructure_limits(self) -> InfrastructureLimits:
        """`src/infrastructure/` siniflərinin ROOT pəncərəsi (bax modul başlığı).

        UZUN ÖMÜRLÜ istehlakçılar üçündür. Sessiyanın içində qurulan obyektlər
        `_build_session`-dakı `session_limits`-i alır — orada açıq bağlantı
        onsuz da var və ikinci bağlantı açmaq lazımsızdır.
        """
        return self._infrastructure_limits

    @property
    def tenant_id(self) -> TenantId:
        return self._tenant_id

    # ------------------------------ lisenziya -------------------------------- #

    def license_blocked(self) -> bool:
        """Tətbiq `LICENSE_INACTIVE` səbəbindən tam bağlanmalıdırmı (bölmə 8).

        Klient qoşulmayıbsa `False` — lisenziya yoxlanışının OLMAMASI tətbiqi
        bloklamamalıdır. Bu, qəsdən seçilmiş fail-open istiqamətidir: bölmə 8
        yalnız `expires_at` KEÇDİKDƏ bloklamağı tələb edir, "yoxlaya bilmədim"
        halı isə `LICENSE_UNVERIFIED` xəbərdarlığıdır (bloklamır).
        """
        if self._license is None:
            return False
        try:
            return bool(self._license.current_state().is_blocked)
        except Exception:
            _error_log.exception("LICENSE_CHECK_FAILED")
            return False

    def license_screen_text(self) -> tuple[str, str, str]:
        """`LicenseInactiveScreen` üçün başlıq/izah/əlaqə mətni (bölmə 8).

        Bölmə 8: ekran "ümumi/qeyri-müəyyən xəta mesajı OLMAMALIDIR — səbəbi,
        son ödəniş/borc tarixini və ödəniş üçün əlaqə vasitəsini açıq şəkildə
        göstərməlidir". Mətn `license_status.blocked_screen_text()`-dədir;
        burada yalnız cari vəziyyət ona ötürülür.
        """
        from src.application.use_cases.license_status import (  # noqa: PLC0415
            blocked_screen_text,
        )

        if self._license is None:
            return (
                "Lisenziya yoxlanıla bilmir",
                "Lisenziya klienti konfiqurasiya edilməyib.",
                "",
            )
        return blocked_screen_text(self._license.current_state())

    # --------------------------- ilk quraşdırma ------------------------------ #

    def complete_setup(self, payload: dict[str, object]) -> None:
        """Sihirbaz formasını use case-in gözlədiyi drafts-a çevirir və icra edir.

        Çevirmə BURADA edilir, ekranda YOX: ekran yalnız sahələri toplayır və
        domen tiplərini (`Username`, `EmailAddress`) tanımır. Validasiya həmin
        tiplərin öz konstruktorlarındadır — səhv format burada istisna atır və
        `app.py` onu istifadəçiyə göstərir.
        """
        from src.application.use_cases.first_run_setup import (  # noqa: PLC0415
            InviteDraft,
            RootAccountDraft,
            StoreDraft,
        )
        from src.domain.value_objects.credentials import (  # noqa: PLC0415
            EmailAddress,
            Username,
        )

        root_raw = _as_mapping(payload.get("root"))
        email_raw = str(root_raw.get("email", "")).strip()
        root = RootAccountDraft(
            first_name=str(root_raw.get("first_name", "")),
            last_name=str(root_raw.get("last_name", "")),
            username=Username.parse(str(root_raw.get("username", ""))),
            password=str(root_raw.get("password", "")),
            recovery_email=EmailAddress.parse(email_raw) if email_raw else None,
        )
        stores = [
            StoreDraft(
                code=str(item.get("code", "")),
                name=str(item.get("name", "")),
                brand=str(item.get("brand", "")),
                address=str(item.get("address", "")),
            )
            for item in _as_sequence(payload.get("stores"))
        ]
        invites = [
            InviteDraft(
                first_name=str(item.get("first_name", "")),
                last_name=str(item.get("last_name", "")),
                username=Username.parse(str(item.get("username", ""))),
                role_code=str(item.get("role_code", "HR_ADMIN")),
                temporary_password=str(item.get("temporary_password", "")),
                notification_email=_optional_email(item.get("email")),
            )
            for item in _as_sequence(payload.get("invites"))
        ]

        with self.session() as session:
            session.setup.complete(
                tenant_id=self._tenant_id,
                root=root,
                stores=stores,
                invites=invites,
                # Tenant sətri YALNIZ identifikator bu maşında yaranıbsa
                # burada qurulur — səbəbi `__init__`-dəki `_self_hosted`
                # şərhindədir (lisenziya qapısının yan keçilməməsi).
                provision_tenant=self._self_hosted,
            )
            session.commit()
        _log.info(
            "FIRST_RUN_SETUP_COMPLETED",
            extra={
                "store_count": len(stores),
                "invite_count": len(invites),
                "self_hosted": self._self_hosted,
            },
        )

        # 1C server addımı QƏSDƏN quraşdırma tranzaksiyasından KƏNARDADIR:
        # sihirbazın 3-cü addımı keçilə bilər (bölmə 7) və serverin qeydi
        # uğursuz olarsa artıq yaradılmış `CEO` hesabı geri qaytarılmamalıdır —
        # əks halda istifadəçi yanlış server ünvanına görə bütün quraşdırmanı
        # itirərdi. Uğursuzluq yalnız jurnala düşür, sonradan «ERP / 1C
        # Serverləri» ekranından əlavə edilə bilər.
        server_raw = _as_mapping(payload.get("server"))
        if str(server_raw.get("host", "")).strip():
            self._register_first_server(server_raw)

    def _register_first_server(self, raw: dict[str, object]) -> None:
        """Sihirbazdakı istəyə görə 1C serverini qeyd edir (bölmə 7).

        Server DEAKTİV yaradılır (`activate=False`): spesifikasiya (sətir 216)
        "yeni ayar yalnız test uğurlu olduqdan sonra aktivləşir" deyir, sihirbaz
        isə bağlantını sınamır. Aktivləşdirmə «ERP / 1C Serverləri» ekranındakı
        `[Bağlantını Test Et]` addımından sonra baş verir.
        """
        from src.domain.value_objects.erp import ErpServerDraft  # noqa: PLC0415
        from src.infrastructure.erp.servers import ErpServerRepository  # noqa: PLC0415
        from src.infrastructure.security.encryption import EncryptionService  # noqa: PLC0415

        host, port = _split_host_port(str(raw.get("host", "")).strip())
        try:
            repository = ErpServerRepository(self._database, self._tenant_id, EncryptionService())
            repository.create(
                ErpServerDraft(
                    server_name=str(raw.get("name", "")).strip() or "1C Server",
                    host=host,
                    port=port,
                    username=str(raw.get("username", "")).strip(),
                    password=str(raw.get("password", "")),
                    infobase=str(raw.get("infobase", "")).strip(),
                ),
                activate=False,
            )
            _log.info("FIRST_RUN_SERVER_REGISTERED", extra={"host": host, "port": port})
        except Exception:
            _error_log.exception("FIRST_RUN_SERVER_FAILED")

    # --------------------------- sübut yükləməsi ----------------------------- #
    #
    # NİYƏ CƏRİMƏ DRIVE-I GÖZLƏMİR
    # ─────────────────────────────────────────────────────────────────────────
    # Bölmə 4: cərimə qeydi DƏRHAL yazılır, şəkil isə arxa planda yüklənir.
    # Ona görə ekran `evidence_queue()`-a yazır (lokal disk + SQLite indeks),
    # `run_evidence_uploads()` isə taymerlə çağırılır. Şəbəkə yoxdursa cərimə
    # yenə yaranır — bu, qəsdən seçilmiş sıradır.

    def evidence_queue(self) -> Any:
        """Sübut şəkillərinin lokal növbəsi (`EvidenceUploadQueue`)."""
        if self._evidence_queue is None:
            from src.infrastructure.security.encryption import (  # noqa: PLC0415
                EncryptionService,
            )
            from src.infrastructure.storage.upload_queue import (  # noqa: PLC0415
                EvidenceUploadQueue,
            )

            # `KOMPASOS_EVIDENCE_QUEUE_PATH` təyin olunubsa davranış EYNİDİR.
            # Defolt isə istifadəçi məlumat qovluğudur: paketlənmiş `.exe`-nin
            # cari qovluğu (System32 / Program Files) yazıla bilməz və ilk
            # sübut şəkli `unable to open database file` ilə itərdi. Şəkillərin
            # baytları `evidence_spool/` qovluğunda — indeksin YANINDA —
            # saxlandığı üçün köhnə fayl mövcud olduqda yol DƏYİŞMİR; səbəb
            # `shared/data_paths.py` başlığındadır (köçürmə qəsdən yoxdur).
            path = resolve_data_file("KOMPASOS_EVIDENCE_QUEUE_PATH", "evidence_uploads.db")
            # Növbə faylı diskə YAZMAZDAN ƏVVƏL ölçünü yoxlayır, hədd isə
            # Root-dan idarə olunur — provider ilə eyni mənbə (bölmə 3).
            # `limits` növbənin İKİNCİ ROOT parametrini açır
            # (`UPLOAD_CLAIM_STALE_AFTER_SECONDS`): "claim" edilmiş element
            # nə vaxt yenidən götürülə bilər.
            # `encryption` (SEC-4) İSTEHSALAT yolunda MƏCBURİDİR: sinif özü
            # `None`-u qəbul edir (sınaq/diaqnostika kontekstləri şifrələməsiz
            # qurula bilsin deyə, bax `EvidenceUploadQueue.__init__` başlığı),
            # LAKİN `None` ötürülsə BÜTÜN yeni yazılar da açıq (`is_encrypted=
            # False`) qalır — kompozisiya kökü onu ötürməsə SEC-4 "fantom
            # düzəliş" olardı: fayl yazılıb, testi keçib, amma istehsalatda heç
            # kim çağırmır (bu dövrədə dəfələrlə görülən qüsur sinfi).
            #
            # Köhnə spool sətirləri BACKFILL EDİLMİR: onlar faktiki AÇIQ
            # yazılıb, `is_encrypted=1`-ə "düzəltmək" yalan olardı — oxucu
            # bayrağa görə şərti deşifrə edir. `enqueue()`-da şifrələmə
            # uğursuz olsa istisna YUXARI ötürülür (operator sinxron gözləyir,
            # foto hələ onun əlindədir → "yenidən cəhd edin"). Arxa-plan
            # `read_plaintext()`-də `DecryptionError` → `mark_rejected()`
            # (`mark_failed` YOX — açar problemi backoff ilə həll olunmur);
            # spool faylı SİLİNMİR, `requeue_rejected()` açar bərpa olunanda
            # sübutu qaytarır.
            self._evidence_queue = EvidenceUploadQueue(
                path,
                # D2 (dövrə audit): `tenant_id` VERİLMƏSƏ `claim_pending()`
                # QLOBAL FIFO-dur — köhnə/başqa tenant-a aid sətirlər CARİ
                # (`self._factory.active()`) tenant-ın Drive-ına yüklənə
                # bilər (bax `upload_queue.py::__init__` şərhi). Bu YEGANƏ
                # kompozisiya yoludur, ona görə `None` buraya HEÇ VAXT
                # ötürülmür.
                tenant_id=str(self._tenant_id),
                max_upload_bytes=self._upload_limit(),
                limits=self._infrastructure_limits,
                encryption=EncryptionService(),
            )
        return self._evidence_queue

    def _upload_limit(self) -> int:
        """Cari `MAX_UPLOAD_SIZE_BYTES` — oxuna bilmirsə provider defoltu.

        Baza əlçatmazlığı burada İSTİSNA ATMIR: verilməli cavab "şəkil qəbul
        edilsinmi" deyil, "hansı hədlə" idi. Cavabsız qaldıqda fallback
        işləyir və cərimə axını dayanmır (bax `upload_queue` başlığı).
        """
        from src.infrastructure.storage.google_drive import MAX_UPLOAD_BYTES  # noqa: PLC0415

        try:
            with self.session() as session:
                return int(session.max_upload_bytes())
        except Exception:
            _log.warning("EVIDENCE_LIMIT_FALLBACK", extra={"bytes": MAX_UPLOAD_BYTES})
            return MAX_UPLOAD_BYTES

    def drive_providers(self, *, max_upload_bytes: int) -> Any:
        """Aktiv Drive bağlantısı üçün provider fabriki — yoxdursa `None`.

        `max_upload_bytes` ROOT İdarə Mərkəzindən gəlir və fabrik hər dəfə
        deyil, YALNIZ dəyər dəyişəndə yenidən qurulur: fabrik provider-ləri
        (HTTP klienti + token) keşləyir və hər dövrədə onu atmaq lazımsız
        token yeniləməsi deməkdir. Root sürüşdürücünü tərpədən kimi növbəti
        dövrə yeni həddi tətbiq edir.

        `None` qaytarır Google OAuth klient məlumatları təyin edilməyibsə —
        bu, xəta DEYİL: Drive qoşulmamış quraşdırmada cərimələr yenə yaranır,
        şəkillər isə növbədə gözləyir (bax `upload_queue` başlığı).
        """
        if self._drive_factory is not None and self._drive_limit == max_upload_bytes:
            return self._drive_factory

        import os  # noqa: PLC0415

        client_id = os.environ.get("KOMPASOS_GOOGLE_CLIENT_ID", "").strip()
        client_secret = os.environ.get("KOMPASOS_GOOGLE_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            return None

        from src.infrastructure.security.encryption import EncryptionService  # noqa: PLC0415
        from src.infrastructure.storage.connections import (  # noqa: PLC0415
            DriveConnectionRepository,
            DriveProviderFactory,
        )
        from src.infrastructure.storage.drive_api import OAuthClient  # noqa: PLC0415
        from src.infrastructure.storage.image_cache import ImageCache  # noqa: PLC0415

        # `limits` fabrikdən provider-ə və HTTP klientinə ÖTÜRÜLÜR (bax
        # `DriveProviderFactory.for_connection`): JPEG keyfiyyəti, Drive
        # taymautu, token marjası və təkrar cəhd sayı Root-dan gəlir. Keş də
        # ayrıca alır — TTL/disk tavanı onun öz parametrləridir.
        self._drive_factory = DriveProviderFactory(
            repository=DriveConnectionRepository(self._database, self._tenant_id),
            encryption=EncryptionService(),
            oauth=OAuthClient(client_id=client_id, client_secret=client_secret),
            cache=ImageCache(limits=self._infrastructure_limits),
            store_names=self._store_names(),
            max_upload_bytes=max_upload_bytes,
            limits=self._infrastructure_limits,
        )
        self._drive_limit = max_upload_bytes
        return self._drive_factory

    def invalidate_drive_providers(self) -> None:
        """Keşlənmiş fabriki atır — hesab dəyişəndə çağırılır.

        Fabrik provider-ləri (HTTP klienti + token) bağlantı ID-sinə görə
        keşləyir. Yeni hesab qoşulduqda köhnə keş həmin an KÖHNƏ hesaba yazmağa
        davam edərdi; bir sətir daşınmayan, lakin tapılması çətin qüsurdur.
        """
        self._drive_factory = None
        self._drive_limit = None

    def run_evidence_uploads(self) -> int:
        """Növbəni bir dəfə boşaldır — yüklənən şəkillərin sayını qaytarır.

        Taymerdən çağırılır və HEÇ VAXT istisna atmır: fon işi interfeysi
        çökdürməməlidir (bax `EvidenceUploadWorker.run_once` daxilindəki eyni
        prinsip — bir şəklin nasazlığı növbəni dayandırmır).
        """
        try:
            with self.session() as session:
                limit = session.max_upload_bytes()
            factory = self.drive_providers(max_upload_bytes=limit)
            if factory is None:
                return 0

            from src.infrastructure.storage.upload_queue import (  # noqa: PLC0415
                EvidenceUploadWorker,
            )

            queue = self.evidence_queue()
            # Növbə tətbiq işlədikcə yaşayır — Root sürüşdürücünü tərpədəndə
            # onun ön-yoxlaması da yeni həddi bilməlidir, əks halda iki tərəf
            # (növbə və provider) eyni fayla fərqli cavab verərdi. Sətir məhz
            # burada dayanır ki, növbə faylı tənbəl qalsın (bax konstruktor).
            queue.set_max_upload_bytes(limit)
            worker = EvidenceUploadWorker(
                queue=queue,
                provider_factory=factory,
                on_uploaded=self._attach_evidence,
            )
            return worker.run_once().uploaded
        except Exception:
            _error_log.exception("EVIDENCE_UPLOAD_RUN_FAILED")
            return 0

    def _attach_evidence(self, owner_type: str, owner_id: str, reference: Any) -> None:
        """Yükləmə bitdikdən sonra sahib sətri yeniləyir — #17 ÜMUMİLƏŞDİRİLMİŞ növbə.

        `EvidenceUploadWorker` artıq ÜÇ sahib növünü daşıyır (bax
        `upload_queue.py` başlığı: `fine_id` → `owner_type`/`owner_id`). Geri-
        çağırış `owner_type`-a görə sahibin CƏDVƏLİNİ seçir — hər üç qolda AKTOR
        YOXDUR (fon işçisindən gəlir), bax `_attach_fine_evidence`/
        `_attach_employee_document_evidence`/`_attach_field_report_evidence`
        başlıqları.

        `FINE` SON QOLDUR (şərtsiz `return`): növbədə `owner_type` sütunu
        köhnə buraxılışdan BOŞ gələ bilər (`fine_id` dövründən qalma sətirlər,
        bax `upload_queue.py` miqrasiya bölməsi) və o sətirlərin hamısı
        cərimə şəklidir — defolt qolu dəyişsəydik, köhnə spool sükutla səhv
        cədvələ yazılardı.
        """
        from src.infrastructure.storage.upload_queue import (  # noqa: PLC0415
            UploadOwnerType,
        )

        if owner_type == UploadOwnerType.EMPLOYEE_DOCUMENT.value:
            self._attach_employee_document_evidence(owner_id, reference)
            return
        if owner_type == UploadOwnerType.FIELD_REPORT.value:
            self._attach_field_report_evidence(owner_id, reference)
            return
        if owner_type == UploadOwnerType.SUPPORT_MESSAGE.value:
            self._attach_support_message_evidence(owner_id, reference)
            return
        if owner_type == UploadOwnerType.FINE_APPEAL.value:
            self._attach_fine_appeal_evidence(owner_id, reference)
            return
        self._attach_fine_evidence(owner_id, reference)

    def _attach_fine_appeal_evidence(self, appeal_id: str, reference: Any) -> None:
        """`fine_appeals.document_ref`-i yeniləyir (DEEP-GAP UX-4).

        `str(reference)` YAZILIR — `employee_documents.file_ref` və
        `support_messages.attachment_ref` ilə EYNİ format (provider + bağlantı
        + fayl ID-si bir mətndə). Sütun adı `_url` DEYİL, çünki dəyər URL
        deyil: private Drive faylının «linki olan hər kəs» yolu YOXDUR
        (`value_objects/storage.py`).

        SIFIR SƏTİR XƏTA DEYİL: cərimə ləğv olunubsa etiraz sətri `CASCADE`
        ilə silinmiş ola bilər. Belə halda yazılacaq yer yoxdur — istisna
        atsaydıq növbə eyni sətri əbədi təkrarlayardı (`link_pending`
        mexanizmi), halbuki səbəb aradan qalxan deyil.

        AKTOR YOXDUR: geri-çağırış fon işçisindən gəlir (qonşu dörd
        `_attach_*` metodunun eyni qərarı).
        """
        import uuid  # noqa: PLC0415

        from src.domain.value_objects.identifiers import AppealId  # noqa: PLC0415

        with self.session() as session:
            updated = session.uow.repository("appeals").attach_document(
                AppealId(uuid.UUID(appeal_id)), reference=str(reference)
            )
            session.commit()
        if not updated:
            _log.warning("APPEAL_DOCUMENT_OWNER_MISSING", extra={"appeal_id": appeal_id})

    def _attach_support_message_evidence(self, message_id: str, reference: Any) -> None:
        """`support_messages.attachment_ref`-i yeniləyir (CHAT-1 Faza 6).

        `str(reference)` YAZILIR — `employee_documents.file_ref` ilə EYNİ
        format (provider + bağlantı + fayl ID-si bir mətndə), yəni ekran
        tərəfində ikinci oxucu yazılmır.

        AKTOR YOXDUR: geri-çağırış fon işçisindən gəlir və orada sessiya
        istifadəçisi mövcud deyil (eyni qərar üç qonşu metoddadır).
        """
        import uuid  # noqa: PLC0415

        from src.domain.value_objects.identifiers import SupportMessageId  # noqa: PLC0415

        with self.session() as session:
            session.uow.repository("support").attach_file(
                SupportMessageId(uuid.UUID(message_id)),
                reference=str(reference),
                filename=getattr(reference, "filename", "") or "",
            )
            session.commit()

    def _attach_fine_evidence(self, fine_id: str, reference: Any) -> None:
        """`fines` sətrini yeniləyir — köçürmədən ƏVVƏLKİ `_attach_evidence`-in ÖZÜ."""
        import uuid  # noqa: PLC0415

        from src.domain.value_objects.identifiers import FineId  # noqa: PLC0415

        with self.session() as session:
            session.uow.fines.attach_drive_evidence(
                FineId(uuid.UUID(fine_id)),
                file_id=reference.file_id,
                connection_id=reference.connection_id,
            )
            session.commit()

    def _attach_employee_document_evidence(self, document_id: str, reference: Any) -> None:
        """`employee_documents.file_ref`-i yeniləyir (#17, Faza 7).

        `str(reference)` (`StorageReference.__str__` → `cache_key`) YAZILIR:
        sənəd cədvəlində `fines`-dəki kimi AYRICA `drive_file_id`/
        `connection_id` sütunları YOXDUR — tək `file_ref TEXT` sahəsi var, ona
        görə üç dəyəri (provider, bağlantı, fayl ID-si) BİR mətndə saxlamaq
        yeni miqrasiya tələb etmədən kifayət edir.

        Səlahiyyət/domen qaydası TƏKRARLANMIR —
        `EmployeeDocumentUseCase.attach_uploaded_file` bunu artıq edir (bax
        onun başlığı: aktor yoxdur, domen qaydası isə entity-də qalır).
        """
        import uuid  # noqa: PLC0415

        from src.domain.value_objects.identifiers import (  # noqa: PLC0415
            EmployeeDocumentId,
        )

        with self.session() as session:
            session.employee_documents.attach_uploaded_file(
                tenant_id=session.tenant_id,
                document_id=EmployeeDocumentId(uuid.UUID(document_id)),
                file_ref=str(reference),
            )
            session.commit()

    def _attach_field_report_evidence(self, owner_id: str, reference: Any) -> None:
        """Sahə hesabatının VƏ YA checklist bəndinin foto istinadını yazır (#26+#27).

        `str(reference)` (`StorageReference.__str__` → `cache_key`) YAZILIR:
        `field_reports.photo_refs` və `field_report_checklist_items.photo_ref`
        MƏTN sahələridir (migrations/037) — `fines`-dəki kimi ayrıca
        `drive_file_id`/`connection_id` sütunları YOXDUR.

        HESABAT/BƏND AYRIMI BURADA EDİLMİR: `owner_id` hər ikisi üçün eyni
        formada gəlir və use case onu birmənalı həll edir (UUID qlobal
        unikaldır — bax `FieldReportUseCase.attach_uploaded_photo` başlığı).
        Kompozisiya kökündə ikinci `if` yazsaydıq, həmin qərar İKİ yerdə
        yaşayardı.
        """
        import uuid  # noqa: PLC0415

        from src.domain.value_objects.identifiers import FieldReportId  # noqa: PLC0415

        with self.session() as session:
            session.field_reports.attach_uploaded_photo(
                tenant_id=session.tenant_id,
                owner_id=FieldReportId(uuid.UUID(owner_id)),
                photo_ref=str(reference),
            )
            session.commit()

    def _store_names(self) -> Any:
        """`store_id → ad` — Drive qovluq adları üçün (bax `StoreNameResolver`)."""
        from src.infrastructure.storage.google_drive import (  # noqa: PLC0415
            StoreNameResolver,
        )

        resolver = StoreNameResolver()
        try:
            with self._database.unit_of_work(self._tenant_id) as uow:
                rows = uow.connection.execute(
                    "SELECT id, name FROM stores WHERE tenant_id = %s",
                    (self._tenant_id,),
                ).fetchall()
        except Exception:
            # Adlar tapılmasa provider "Mağaza-xxxxxxxx" işlədir — qovluq adı
            # gözəl olmaz, lakin yükləmə DAYANMAMALIDIR.
            _error_log.exception("STORE_NAMES_LOAD_FAILED")
            return resolver
        for row in rows:
            resolver.register(row["id"], str(row["name"]))
        return resolver

    def ntp_drift_seconds(self) -> float | None:
        """Ölçülmüş saat sürüşməsi — ölçülməyibsə `None` (bax `_NullNtp`).

        `None` "sürüşmə yoxdur" DEMƏK DEYİL, "ölçülməyib" deməkdir və Sistem
        Sağlamlığı ekranı bu fərqi saxlamalıdır: `0.0` göstərmək ölçülməmiş
        saatı "ideal" kimi təqdim edərdi və problem gizli qalardı.
        """
        try:
            return self._ntp.drift_seconds()
        except Exception:
            _error_log.exception("NTP_DRIFT_READ_FAILED")
            return None

    # ------------------------- server-lövbərli vaxt --------------------------- #

    @property
    def clock(self) -> Clock:
        """Tətbiqin vaxt mənbəyi — server lövbərli (TIME-1).

        Təqdimat qatı bunu YALNIZ göstərmək üçün alır (canlı saat). Yazma
        yolları vaxtı use case-lərdən götürür və onlar onsuz da eyni port
        nüsxəsini alır — ekranın öz `datetime.now()` çağırışı olsaydı, o,
        bu qatın bütün mənasını yan keçərdi.
        """
        return self._clock

    def start_time_sync(self) -> None:
        """Server vaxtı sinxronizasiyasını başladır (TIME-1).

        Örtük açılışında çağırılır. Uğursuzluq DAYANDIRICI DEYİL: lövbər
        qurulmasa `Clock` fallback saata düşür və vəziyyət `UNTRUSTED` olur —
        tətbiqin işə düşməməsi vaxtın təxmini olmasından pis nəticədir.
        """
        try:
            self._server_time.start()
        except Exception:
            _error_log.exception("SERVER_TIME_START_FAILED")

    def stop_time_sync(self) -> None:
        """Arxa fon sapını dayandırır — bağlanma yolunda çağırılır."""
        with suppress(Exception):
            self._server_time.stop()

    def time_integrity_status(self) -> TimeIntegrityStatus:
        """Vaxtın hazırkı etibarlılıq səviyyəsi — ekran və audit üçün."""
        return self._server_time.status()

    def server_time_health(self) -> dict[str, object]:
        """Sistem Sağlamlığı ekranı üçün sətir (bölmə 6)."""
        try:
            return self._server_time.health
        except Exception:
            _error_log.exception("SERVER_TIME_HEALTH_READ_FAILED")
            return {}

    def _on_clock_manipulation(self, offset_seconds: float, threshold_seconds: float) -> None:
        """PC saatı serverdən çox fərqlənir → HR_Admin-ə bildiriş (TIME-1 Faza 4).

        ──────────────────────────────────────────────────────────────────────
        AŞKARLAMA SÖNDÜRÜLƏ BİLMİR — YALNIZ ÇATDIRILMA
        ──────────────────────────────────────────────────────────────────────
        `LOCAL_CLOCK_MANIPULATION_NOTIFY = 0` yazılsa bu metod bildiriş
        GÖNDƏRMİR, lakin hadisə `security.log`-a onsuz da düşüb (bax
        `ServerTimeService._check_manipulation`). Yəni Root susdura biləcəyi
        şey xəbərdarlığın ÇATDIRILMASIDIR, faktın QEYDƏ ALINMASI yox —
        fırıldaqçılıq siqnalının konfiqurasiya ilə silinməsi onu siqnal
        olmaqdan çıxarardı.

        ARXA FON SAPINDAN ÇAĞIRILIR: istisna buradan yuxarı qalxsa
        sinxronizasiya dövrəsini pozar, ona görə hər şey udulur və jurnala
        yazılır.
        """
        try:
            if self._infrastructure_limits.int_of(SystemLimitKey.LOCAL_CLOCK_MANIPULATION_NOTIFY):
                self._send_clock_manipulation_notice(offset_seconds, threshold_seconds)
        except Exception:
            _error_log.exception("CLOCK_MANIPULATION_NOTIFY_FAILED")

    def _send_clock_manipulation_notice(self, offset_seconds: float, threshold: float) -> None:
        """Bildirişi yazır — `DriveQuotaMonitor._notify` ilə eyni naxış."""
        from src.infrastructure.notifications.notifier import PostgresNotifier  # noqa: PLC0415

        machine = socket.gethostname()
        direction = "geri" if offset_seconds > 0 else "irəli"
        minutes = abs(offset_seconds) / 60.0
        PostgresNotifier(self._database, limits=self._infrastructure_limits).notify(
            tenant_id=self._tenant_id,
            # `recipient_id=None` → tenant səviyyəli bildiriş; marşrutlaşdırma
            # icazə flag-inə görə olur, ayrıca alıcı siyahısı SAXLANMIR.
            recipient_id=None,
            category="CLOCK_MANIPULATION",
            title_az="Saat manipulyasiyası aşkarlandı",
            body_az=(
                f"«{machine}» kompüterinin saatı server vaxtından {minutes:.0f} dəqiqə "
                f"{direction} qalıb (icazə verilən hədd {threshold / 60:.0f} dəqiqə). "
                "Qeydlərin vaxtı server saatı ilə yazılır — dəyişiklik onlara təsir "
                "etməyib. Bu, saatı dəyişməyə cəhdin göstəricisidir."
            ),
            is_critical=True,
        )

    # --------------------------- üz təsdiqi qatı ----------------------------- #
    #
    # BƏND 5 BU METODUN BÜTÜN MƏNASIDIR
    # ─────────────────────────────────────────────────────────────────────────
    # Kitabxana (Dlib və ya OpenCV) yüklənə bilmirsə üç variant vardı:
    #   (a) tətbiqi açmamaq — üz təsdiqi sistemin BİR qatıdır, onun ucbatından
    #       mağazanı dayandırmaq həddindən artıq cəzadır;
    #   (b) üz təsdiqini sükutla keçmək — `facecontrol.md` bənd 5-in MƏHZ
    #       qadağan etdiyi «səssiz yalnız-PIN» rejimi;
    #   (c) kameranı ƏLÇATMAZ elan etmək — use case mövcud eskalasiya kanalına
    #       (`VERIFICATION_TIMEOUT`) düşür və hər təsdiq HR_Admin/CEO-nun
    #       manual qərarına gedir.
    # Seçilən (c)-dir: sistem işləyir, lakin üz qapısının yerinə İNSAN qapısı
    # qoyulur və nasazlıq System Health Monitor-da görünür.

    def face_engine(self) -> tuple[Any, Any]:
        """`(CameraCapture, FaceMatcher)` cütü — ilk üz əməliyyatında qurulur.

        İKİSİ BİRLİKDƏ QAYTARILIR, çünki uğursuzluq halında hər ikisi EYNİ
        `UnavailableFaceEngine` nüsxəsi olmalıdır: ayrı-ayrı qursaydıq, «işləyən
        kamera + işləməyən mühərrik» kimi yarım vəziyyət mümkün olardı və o
        halda doğrulama `is_available()` qapısını keçib mühərrikdə çökərdi.
        """
        if self._face_engine is not None:
            return self._face_engine

        from src.infrastructure.kiosk.camera import (  # noqa: PLC0415
            OpenCvCameraCapture,
            UnavailableFaceEngine,
            camera_available,
        )
        from src.infrastructure.security.face_matcher import (  # noqa: PLC0415
            DlibFaceMatcher,
            engine_available,
        )

        if not camera_available() or not engine_available():
            reason = "cv2" if not camera_available() else "face_recognition"
            # SÜKUTLA KEÇMİR: `error.log`-a KRİTİK sətir düşür, çünki bu
            # vəziyyət quraşdırma qüsurudur və dərhal düzəldilməlidir.
            _error_log.critical("FACE_ENGINE_UNAVAILABLE", extra={"missing": reason})
            fallback = UnavailableFaceEngine(reason=reason)
            self._face_engine = (fallback, fallback)
            return self._face_engine

        try:
            self._face_engine = (
                OpenCvCameraCapture(device_index=_camera_index()),
                DlibFaceMatcher(),
            )
        except Exception as exc:
            # Model faylı yoxdursa (paketləmə səhvi) `DlibFaceMatcher`
            # konstruktoru çökür. Nəticə eynidir: eskalasiya, keçid YOX.
            _error_log.exception("FACE_ENGINE_INIT_FAILED", extra={"error": str(exc)})
            fallback = UnavailableFaceEngine(reason="init_failed")
            self._face_engine = (fallback, fallback)
        return self._face_engine

    def close_face_engine(self) -> None:
        """Kamera tutacağını buraxır — tətbiq bağlananda çağırılır.

        İSTİSNA ATMIR: bağlanma yolu heç vaxt bir cihaz sürücüsünün ucbatından
        dayanmamalıdır (`run_evidence_uploads` ilə eyni prinsip).
        """
        if self._face_engine is None:
            return
        camera = self._face_engine[0]
        self._face_engine = None
        closer = getattr(camera, "close", None)
        if closer is None:
            return
        try:
            closer()
        except Exception:
            _error_log.exception("FACE_CAMERA_CLOSE_FAILED")

    # --------------------------- baza keçidi qatı ---------------------------- #

    def offline_drain(self) -> Any:
        """`OfflineBufferDrain` — bufer ilk SORĞUDA açılır (bax konstruktor)."""
        if self._offline_drain is None:
            # AÇAR SÖZLƏ ötürülür (mövqe ilə YOX): "limits qəbul edən hər sinif
            # `limits=` almalıdır" statik yoxlaması mövqeli arqumenti görmür və
            # bu sətri yalançı-boşluq kimi bildirərdi.
            self._offline_drain = _LazyBufferDrain(limits=self._infrastructure_limits)
        return self._offline_drain

    def migrator(self) -> Any:
        """`DatabaseMigrator` — iki hədəfin DSN-i mühitdən gəlir.

        Şəxsi server DSN-i BOŞ ola bilər və bu, xəta deyil: müştərilərin
        əksəriyyəti yalnız buludda işləyir. Həmin halda keçid cəhdi
        `PgDumpMigrator._require_dsn`-dən aydın Azərbaycanca mesajla qayıdır
        («Şəxsi server bağlantısı konfiqurasiya edilməyib») — burada `None`
        qaytarmaq isə use case-i tamamilə qurulmamış saxlayardı və ekran
        səbəbi göstərə bilməzdi.

        Obyekt KEŞLƏNMİR: `PgDumpMigrator` `switch_active()` ilə seçilmiş
        hədəfi yaddaşda saxlayır, lakin keçid bir dəfəlik texniki əməliyyatdır
        və hər sessiyada yeni nüsxə qurmaq heç bir resurs tutmur (konstruktor
        nə fayl, nə bağlantı açır).
        """
        import os  # noqa: PLC0415

        from src.domain.value_objects.infrastructure import DatabaseTarget  # noqa: PLC0415
        from src.infrastructure.persistence.migration import (  # noqa: PLC0415
            PgDumpMigrator,
            read_scalar,
        )

        return PgDumpMigrator(
            dsn_by_target={
                DatabaseTarget.CLOUD: os.environ.get("DATABASE_URL", "").strip(),
                DatabaseTarget.PRIVATE_SERVER: os.environ.get(
                    "KOMPASOS_PRIVATE_SERVER_DSN", ""
                ).strip(),
            },
            checksum_reader=read_scalar,
        )

    # ---------------------------- planlayıcı qatı ---------------------------- #

    def job_runner(self) -> Any:
        """`JobRunner` — işləri qeydiyyatdan keçmiş, TƏK nüsxə (bax konstruktor).

        İKİ GİRİŞ NÖQTƏSİ EYNİ OBYEKTİ ALIR: GUI-dəki `QTimer`
        (`include_heavy=False`) və CLI-dakı `--run-scheduled-jobs`
        (`include_heavy=True`). Ayrı-ayrı nüsxələr qursaydıq, hər biri öz
        `instance_id`-si ilə imzalayardı və eyni prosesin iki dövrəsi
        bir-birini «başqa terminal» kimi görərdi.
        """
        if self._job_runner is None:
            self._job_runner = self._build_job_runner()
        return self._job_runner

    def run_scheduled_jobs(self, *, include_heavy: bool) -> Any:
        """Vaxtı çatmış işləri bir dəfə icra edir və hesabatı qaytarır.

        İSTİSNA UDULMUR — `run_evidence_uploads`-dan FƏRQLİ olaraq. Səbəb:
        orada verilməli cavab "şəkil göndərildimi" idi və göndərilməməsi
        interfeysi maraqlandırmır; burada isə CLI çıxış kodu məhz bu çağırışın
        nəticəsindən çıxır (`main.py --run-scheduled-jobs`) və sükutla udulmuş
        nasazlıq Windows Task Scheduler-ə "uğurlu" kimi görünərdi — yəni gecə
        işlərinin dayandığı HEÇ VAXT aşkarlanmazdı.

        GUI tərəfi isə istisnanı ÖZÜ udur (`app.py::_run_scheduled_jobs`,
        `_drain_upload_queue` naxışı) — fon dövrəsi pəncərəni çökdürməməlidir.
        """
        report: Any = self.job_runner().run_due(
            tenant_id=self._tenant_id, include_heavy=include_heavy
        )
        return report

    def _build_job_runner(self) -> Any:
        """Planlayıcını qurur və işləri SIRA İLƏ qeydiyyatdan keçirir."""
        from src.application.use_cases.job_runner import JobRunner  # noqa: PLC0415
        from src.infrastructure.persistence.scheduled_job_repository import (  # noqa: PLC0415
            PostgresScheduledJobRepository,
        )
        from src.shared.runtime import process_instance_id  # noqa: PLC0415

        runner = JobRunner(
            # Repo `PostgresUnitOfWork`-ə QOŞULMUR və bu qəsdəndir: icarə
            # DƏRHAL commit olunmalıdır, əks halda digər terminal onu yalnız
            # iş bitəndən sonra görərdi (bax repo modul başlığı).
            runs=PostgresScheduledJobRepository(self._database),
            # AÇAR SÖZLƏ: `limits` qəbul edən hər sinif `limits=` almalıdır
            # (`test_root_control_parameter_parity` mövqeli ötürməni görmür).
            limits=_StandaloneLimits(self._database, batch=self._read_batch),
            audit=_StandaloneAudit(self._database),
            clock=self._clock,
            instance_id=process_instance_id(),
        )
        self._register_scheduled_jobs(runner)
        return runner

    def _register_scheduled_jobs(self, runner: Any) -> None:
        """Reyestrin YEGANƏ doldurulma nöqtəsi — nüvə heç bir işi tanımır.

        ──────────────────────────────────────────────────────────────────────
        SIRA İŞ QAYDASIDIR, ZÖVQ MƏSƏLƏSİ DEYİL
        ──────────────────────────────────────────────────────────────────────
        `BEHAVIOR_BASELINE_RECALC` `EXCEPTION_ENGINE_RUN`-dan ƏVVƏLDİR, çünki
        motorun `BehaviorAnomalyRule`-u məhz baz xəttini oxuyur (bax
        `_build_session`-dakı `register_rule(...)`). Tərsinə qeyd etsəydik,
        motor həmişə DÜNƏNKİ baz xətti ilə müqayisə edərdi və hər anomaliya
        bir gün gecikərdi — səhv görünməz olardı, çünki istisna YENƏ yaranır,
        sadəcə bir gün sonra. `ScheduledJobRegistry` sırasını `dict` sırası
        ilə qoruyur (bax `exception_rules.py` başlığı: "NİYƏ SIRA QORUNUR").

        ──────────────────────────────────────────────────────────────────────
        `EXCEPTION_ENGINE_RUN` İNDİYƏ QƏDƏR HEÇ VAXT ÇAĞIRILMAYIB
        ──────────────────────────────────────────────────────────────────────
        Motor Faza 3-dən bəri yazılıb və test edilib, `Session.exceptions`-a da
        qoşulub — lakin onu ÇAĞIRAN heç bir yol yox idi. Nəticədə #9 İstisnalar
        ekranı bu günə kimi HƏMİŞƏ boş qalırdı. Bu qeydiyyat həmin zənciri
        bağlayır.

        ──────────────────────────────────────────────────────────────────────
        ÇƏKİ VƏ RİTM SEÇİMLƏRİ
        ──────────────────────────────────────────────────────────────────────
        İşlərin əksəriyyəti `DAILY`-dir: hamısı CARİ vəziyyəti yenidən
        hesablayan gün-vahidli əməliyyatlardır (pəncərə DÜNƏNlə bitir).
        `FINE_EXPIRE_STALE` isə `HOURLY`-dir — o, DB-dəki
        `cron_close_expired_appeals` işinin tətbiq qatındakı əkizidir və həmin
        cron `schema.sql`-da `'0 * * * *'` ilə, yəni saatda bir dəfə
        qeydiyyatdan keçib. Ritmi fərqli seçsəydik, eyni qayda `pg_cron`-lu və
        `pg_cron`-suz quraşdırmada FƏRQLİ vaxtda işləyər və 72 saatlıq etiraz
        pəncərəsinin bağlanma anı quraşdırmadan asılı olardı (bax
        `fine_management.expire_stale` docstring-i, Variant B).
        `DUAL_CONTROL_OVERRIDE_TIMEOUT` də `HOURLY`-dir və səbəbi eynidir:
        həddi DƏQİQƏ ilə ölçülən qayda gündəlik ritmlə təsadüfi işləyərdi.

        Yalnız `NIGHTLY_BACKUP` `HEAVY`-dir: `pg_dump` xarici prosesdir və
        dəqiqələrlə çəkir — GUI axınında icra olunsaydı interfeys donardı.
        """
        from src.application.use_cases.job_runner import (  # noqa: PLC0415
            JobCadence,
            JobWeight,
            ScheduledJob,
        )

        for key, handler, cadence, weight in (
            # 1. Baz xətti — MOTORDAN ƏVVƏL (bax yuxarı).
            (
                "BEHAVIOR_BASELINE_RECALC",
                self._job_behavior_baseline,
                JobCadence.DAILY,
                JobWeight.LIGHT,
            ),
            # 2. Vahid İstisna Motoru — təzə baz xətti üzərində işləyir.
            (
                "EXCEPTION_ENGINE_RUN",
                self._job_exception_engine,
                JobCadence.DAILY,
                JobWeight.LIGHT,
            ),
            (
                "STAFFING_PATTERN_REFRESH",
                self._job_staffing_pattern,
                JobCadence.DAILY,
                JobWeight.LIGHT,
            ),
            (
                "EMPLOYEE_DOCUMENT_EXPIRY_NOTICE",
                self._job_document_expiry,
                JobCadence.DAILY,
                JobWeight.LIGHT,
            ),
            (
                "ATTRITION_RISK_RECALC",
                self._job_attrition_risk,
                JobCadence.DAILY,
                JobWeight.LIGHT,
            ),
            # #26 — audit tezliyi xatırlatması (kompas1.md Faza 3). YENİ
            # cron/taymer YAZILMIR: mövcud planlayıcıya BİR sətir qeydiyyat.
            # `LIGHT`, çünki iş TƏK aqreqat sorğusu + filial sayı qədər
            # bildiriş sətridir (21 filial) — GUI axınını dondurmur.
            # `DAILY`, çünki interval GÜN vahidlidir: saatlıq icra eyni
            # xəbərdarlığı gün ərzində 24 dəfə göndərərdi.
            (
                "FIELD_REPORT_AUDIT_REMINDER",
                self._job_field_report_audit_reminder,
                JobCadence.DAILY,
                JobWeight.LIGHT,
            ),
            # #28 — illik məzuniyyət accrual-ı, köçürməsi və "istifadə et ya
            # itir" son tarixi (kompas1.md Faza 4). YENİ cron/taymer
            # YAZILMIR: mövcud planlayıcıya BİR sətir qeydiyyat.
            #
            # `DAILY`, "hər 1 yanvar" DEYİL: terminal həmin gecə söndürülmüş
            # ola bilər və şərt qoyulsaydı köçürmə BÜTÜN İL üçün itərdi
            # (`job_runner.py`: "GECİKMİŞ İCRA"). Gündəlik icra zərərsizdir,
            # çünki `run_year_rollover` İDEMPOTENTDİR — haqq TƏYİN edilir,
            # ARTIRILMIR.
            #
            # `LIGHT`: iş bir aqreqasiya sorğusu + işçi sayı qədər UPSERT-dir
            # (235 sətir) — GUI axınını dondurmur.
            (
                "ANNUAL_LEAVE_YEAR_ROLLOVER",
                self._job_annual_leave_rollover,
                JobCadence.DAILY,
                JobWeight.LIGHT,
            ),
            # CHAT-1 (tg1.md Faza 6) — «Həll olundu → Bağlandı» avtomatik
            # keçidi və «Gözləmədə» xatırlatması. YENİ cron/taymer YAZILMIR:
            # mövcud planlayıcıya BİR sətir qeydiyyat.
            #
            # `DAILY`, `HOURLY` DEYİL: hər iki müddət GÜN vahidlidir
            # (`SUPPORT_AUTO_CLOSE_DAYS`, `SUPPORT_WAITING_REMINDER_DAYS`) və
            # saatlıq icra eyni sətirləri 24 dəfə yoxlayardı — nəticə eyni,
            # yük iyirmi dörd qat.
            #
            # `LIGHT`: iş iki indeksli sorğu + tapılan sətir qədər UPDATE-dir.
            # Praktikada gündə bir neçə sətir olur.
            (
                "SUPPORT_STATUS_MAINTENANCE",
                self._job_support_status_maintenance,
                JobCadence.DAILY,
                JobWeight.LIGHT,
            ),
            # `facecontrol.md` bənd 14 — istisnaların müddət-bitməsi. SIRA
            # TƏSADÜFİ DEYİL: `EXCEPTION_ENGINE_RUN`-dan SONRA, çünki bitmiş
            # istisna motorun tapıntılarına təsir etmir, lakin `BEHAVIOR_
            # BASELINE_RECALC` kimi ağır işlərdən sonra icra olunması gecə
            # dövrəsinin yükünü bərabər paylayır.
            #
            # `DAILY`: müddət GÜN vahidlidir. `HOURLY` seçsəydik, eyni istisna
            # üçün gün ərzində 24 icra cəhdi olardı — hər biri boş sorğu.
            # `LIGHT`: bir indeksli sorğu + bitən sətir qədər UPDATE.
            #
            # GECİKMƏ TƏHLÜKƏSİZLİK BOŞLUĞU YARATMIR: `FaceExemption.
            # is_active_at()` HƏM statusa, HƏM `expires_at`-a baxır — yəni
            # terminal bir həftə söndürülü qalsa belə, istisna faktiki olaraq
            # ÖZ TARİXİNDƏ bitir; gecəlik iş yalnız sətrin statusunu təmizləyir.
            (
                "FACE_EXEMPTION_EXPIRY",
                self._job_face_exemption_expiry,
                JobCadence.DAILY,
                JobWeight.LIGHT,
            ),
            # `facecontrol.md` bənd 17 — doğrulama jurnalının saxlama müddəti.
            # `DAILY` + `LIGHT`: tək `DELETE` (indeksli, `idx_face_verification_
            # log_retention`). YENİ cron/taymer YAZILMIR — mövcud planlayıcıya
            # bir sətir qeydiyyat (`NIGHTLY_BACKUP` naxışı).
            (
                "FACE_LOG_RETENTION",
                self._job_face_log_retention,
                JobCadence.DAILY,
                JobWeight.LIGHT,
            ),
            (
                "FINE_EXPIRE_STALE",
                self._job_expire_stale_appeals,
                JobCadence.HOURLY,
                JobWeight.LIGHT,
            ),
            # M-5 — dual-control təsdiq müddəti. `HOURLY`, çünki hədd DƏQİQƏ
            # vahidlidir (defolt 480) və gündəlik icra ən pis halda 24 saatlıq
            # xəta verərdi — yəni Root-un təyin etdiyi müddət praktikada
            # təsadüfi işləyərdi. `LIGHT`: bir indeksli sorğu + ləğv olunan
            # sətir qədər UPDATE (`FINE_EXPIRE_STALE` ilə eyni ölçü).
            #
            # GECİKMİŞ İCRA TƏHLÜKƏSİZ DEYİL, ONA GÖRƏ QAPI İKİ YERDƏDİR:
            # terminal söndürülü qalsa da, `approve_dual_control` təsdiqdən
            # ƏVVƏL müddəti özü yoxlayır — yəni vaxtı keçmiş sorğu bu iş heç
            # vaxt işləməsə belə təsdiqlənə bilmir.
            (
                "DUAL_CONTROL_OVERRIDE_TIMEOUT",
                self._job_expire_pending_overrides,
                JobCadence.HOURLY,
                JobWeight.LIGHT,
            ),
            # #30 — planlaşdırılmış icra xülasəsi (kompas1.md Faza 6). YENİ
            # cron/taymer YAZILMIR: mövcud planlayıcıya BİR sətir qeydiyyat
            # (`ExecutiveDigestUseCase.run`, bax onun modul başlığı).
            #
            # SIRA SONUNCUDUR, TƏSADÜF DEYİL: `BEHAVIOR_BASELINE_RECALC`,
            # `EXCEPTION_ENGINE_RUN`, `ATTRITION_RISK_RECALC` bu sıradan
            # ƏVVƏLDƏDİR — xülasə həmin işlərin BUGÜNKÜ yenidən-hesablanmış
            # nəticəsini (açıq istisna sayı, turnover balı) OXUYUR. Tərsinə
            # qeyd etsəydik, xülasə DÜNƏNKİ ədədlərlə göndərilərdi.
            #
            # `DAILY`: `JobCadence`-də `WEEKLY` YOXDUR (`job_runner.py`
            # başlığı) — iş HƏR GÜN işə düşür, HƏFTƏLİK konfiqurasiyanın bu
            # gün DUE olub-olmadığını `run()`-un ÖZÜ qərarlaşdırır (bax
            # `executive_digest.py::_due_window`).
            #
            # `LIGHT`: DB oxu (bir neçə aqreqat sorğu) + e-poçt — GUI axınını
            # dondurmur (`FIELD_REPORT_AUDIT_REMINDER` ilə eyni çəki qərarı).
            (
                "EXECUTIVE_DIGEST_RUN",
                self._job_executive_digest,
                JobCadence.DAILY,
                JobWeight.LIGHT,
            ),
            # Drive kvota nəzarəti (Faza 3.9). `DriveQuotaMonitor` yazılıb, test
            # edilib və ixrac olunub — LAKİN onu ÇAĞIRAN heç bir yol yox idi.
            # Nəticədə 90% xəbərdarlığı və avtomatik `ACTIVE → QUOTA_EXCEEDED`
            # keçidi HEÇ VAXT baş vermirdi; Drive-ın dolduğu yalnız növbəti
            # yükləmə `DriveQuotaExceededError` ilə çökəndə bilinirdi. Söhbət
            # cərimə SÜBUT şəkillərindən gedir — mübahisə halında cərimənin
            # yeganə əsaslandırmasından — ona görə xəbərdarlıqsız itmə
            # qəbuledilməzdir (`EXCEPTION_ENGINE_RUN` ilə eyni boşluq növü).
            #
            # `DAILY`: modulun öz modeli gündəlikdir (`quota_monitor.py` başlığı,
            # "TƏKRAR XƏBƏRDARLIQ QORUNMASI") və hədd GÜN vahidli
            # `DRIVE_QUOTA_WARNING_COOLDOWN_DAYS` ilə susdurulur. `HOURLY`
            # seçsəydik, kvota 90%-i keçən gün 24 Drive API sorğusu edilərdi və
            # xəbərdarlıq yenə günə bir dəfə gedərdi — yəni yalnız kvota
            # limitini yeyərdik.
            #
            # `LIGHT`: bir HTTP `about` sorğusu + ən çoxu iki `UPDATE`. `HEAVY`
            # yalnız `pg_dump` üçün ayrılıb (bax yuxarıdakı əsaslandırma).
            #
            # YENİ `SystemLimitKey` YARADILMIR: həm hədd
            # (`DRIVE_QUOTA_WARNING_RATIO`), həm təkrar-susma müddəti
            # (`DRIVE_QUOTA_WARNING_COOLDOWN_DAYS`) ARTIQ `system_limits`-dədir
            # (seed: migrations/032) və monitor onları YOXLAMA ANINDA oxuyur.
            (
                "DRIVE_QUOTA_CHECK",
                self._job_drive_quota_check,
                JobCadence.DAILY,
                JobWeight.LIGHT,
            ),
            # DEEP-GAP OP-1 — ÜÇ İŞ YAZILMIŞDI, LAKİN HEÇ VAXT İŞƏ DÜŞMÜRDÜ.
            # Hər üçünün use case metodu mövcud, testli və sənədlidir; yalnız
            # bu siyahıya salınmamışdı, yəni istehsalatda ölü idi. Ən ağırı
            # birincisidir: davamiyyət hesabatı `unauthorized_absence` sütununu
            # oxuyur, onu YAZAN yol isə yox idi.
            (
                "MORNING_ABSENCE_DETECTION",
                self._job_detect_absences,
                JobCadence.DAILY,
                JobWeight.LIGHT,
            ),
            (
                "TASK_OVERDUE_ESCALATION",
                self._job_task_escalation,
                JobCadence.HOURLY,
                JobWeight.LIGHT,
            ),
            (
                "DEVICE_INACTIVITY_BLOCK",
                self._job_block_inactive_devices,
                JobCadence.DAILY,
                JobWeight.LIGHT,
            ),
            (
                "OPEN_SHIFT_EXPIRY",
                self._job_expire_open_shifts,
                JobCadence.DAILY,
                JobWeight.LIGHT,
            ),
            (
                "VERIFICATION_TIMEOUT_ESCALATION",
                self._job_escalate_verification_timeouts,
                JobCadence.HOURLY,
                JobWeight.LIGHT,
            ),
            (
                "RETENTION_PURGE",
                self._job_retention_purge,
                JobCadence.DAILY,
                JobWeight.LIGHT,
            ),
            # `v2backlog.md` Faza 3.1/3.2/3.3 — HR lifecycle-in ÜÇ gecəlik işi.
            # Use case metodları YAZILIB, testlidir və `Session`-a qoşulub
            # (bax `_build_session`), lakin BU siyahıya salınmamışdı — yəni
            # `EXCEPTION_ENGINE_RUN`/DEEP-GAP OP-1 ilə EYNİ boşluq növü
            # (yazılıb, çağıran yoxdur). `DAILY`+`LIGHT`: hər üçü GÜN vahidli
            # tarix müqayisəsi + tapılan sətir qədər UPDATE-dir, xarici
            # proses yoxdur (`STAFFING_PATTERN_REFRESH` ilə eyni çəki qərarı).
            (
                "TRANSFER_REQUEST_SCHEDULED_APPLY",
                self._job_scheduled_transfers,
                JobCadence.DAILY,
                JobWeight.LIGHT,
            ),
            # QAPI SINIĞI (composition-un ÖZÜNÜN sənədləşdirdiyi boşluq) —
            # bu iki iş HAZIRDA 0 QAYTARIR: `UserManagementUseCase.
            # deactivate_scheduled_employees`/`anonymize_former_employees`
            # `scheduled_deactivation_reader`/`retention_candidate_reader`
            # portlarını oxuyur (bax aşağıdakı `users = UserManagementUseCase
            # (...)` çağırışı), LAKİN infra bu İKİ Protocol-u (`ports.py`-dakı
            # `ScheduledDeactivationCandidateReader`/`RetentionAnonymization
            # CandidateReader`) HƏLƏ HEÇ BİR repo-da İMPLEMENTASİYA ETMƏYİB —
            # `PostgresEmployeeRepository`-də `list_due_for_scheduled_
            # deactivation`/`list_pending_anonymization` metodları YOXDUR.
            # Qeydiyyat qəsdən BURADADIR: adapter gələndə YALNIZ
            # `composition.py`-da port bağlanmalı olsun, job artıq yerindədir
            # və o an SÜKUTLA "ölü" qalmayacaq.
            (
                "EMPLOYEE_SCHEDULED_DEACTIVATION_RUN",
                self._job_scheduled_employee_deactivation,
                JobCadence.DAILY,
                JobWeight.LIGHT,
            ),
            (
                "FORMER_EMPLOYEE_ANONYMIZATION_RUN",
                self._job_former_employee_anonymization,
                JobCadence.DAILY,
                JobWeight.LIGHT,
            ),
            # `v2backlog.md` Faza 5 — sistem davamlılığının ÜÇ gecə/saat işi.
            #
            # `BREAK_GLASS_EXPIRY` HOURLY-dir, DƏQİQƏLİK DEYİL və bu, təhlükə
            # YARATMIR: səlahiyyətin qüvvədə olması `BreakGlassGrant.
            # is_effective_at()` ilə HƏR yoxlamada vaxta görə hesablanır —
            # planlayıcı yalnız statusu təmizləyir (audit oxunuşu üçün).
            # Dəqiqəlik iş eyni nəticəni 60 dəfə artıq sorğu ilə verərdi.
            (
                "BREAK_GLASS_EXPIRY",
                self._job_break_glass_expiry,
                JobCadence.HOURLY,
                JobWeight.LIGHT,
            ),
            # Vendor bildirişinin təkrar cəhdi — GÜNDƏLİK kifayətdir: sətir
            # yerli bazada onsuz da tamdır, mərkəzi nüsxə isə hesabat
            # məqsədlidir (bax `break_glass_reporter.py` başlığı).
            (
                "BREAK_GLASS_VENDOR_RETRY",
                self._job_break_glass_vendor_retry,
                JobCadence.DAILY,
                JobWeight.LIGHT,
            ),
            # Faza 5.1 — uzun-müddətli offline xəbərdarlığı. HOURLY: hədd
            # SAAT vahidlidir (`OFFLINE_BACKLOG_MAX_HOURS`), gündəlik yoxlama
            # 24 saatlıq həddi 24 saat gecikdirə bilərdi.
            (
                "OFFLINE_BACKLOG_CHECK",
                self._job_offline_backlog_check,
                JobCadence.HOURLY,
                JobWeight.LIGHT,
            ),
            # Faza 5.2 — disk/RAM nasazlığının filialın texniki-məsuluna
            # bildirilməsi. HOURLY: dolan disk saatlar ərzində dolur, günlərlə
            # yox (`DRIVE_QUOTA_CHECK`-in GÜNDƏLİK olmasından fərqli səbəb —
            # kvota həftələrlə dözür).
            (
                "HARDWARE_HEALTH_CHECK",
                self._job_hardware_health_check,
                JobCadence.HOURLY,
                JobWeight.LIGHT,
            ),
            ("NIGHTLY_BACKUP", self._job_nightly_backup, JobCadence.DAILY, JobWeight.HEAVY),
        ):
            runner.register(ScheduledJob(key=key, handler=handler, cadence=cadence, weight=weight))

    @property
    def _break_glass_reporter(self) -> Any:
        """Vendor bildiricisi — TƏNBƏL, tapılmazsa `None` (DB-3, bax `__init__`).

        İDXAL DA TƏNBƏLDİR: modul `VendorDatabase`-i idxal edir və açılış
        yolunda əlavə modul yükləmək açılış sürətinə haqsız qiymət qoyardı —
        fövqəladə giriş isə nadir yoldur.

        VENDOR BAZASININ ƏLÇATMAZLIĞI TƏTBİQİ DAYANDIRMIR: `VendorConnection
        Error` udulur və bildirici söndürülür. Fövqəladə giriş həmin anda da
        işləməlidir — yerli sətir tamdır, `vendor_synced_at` NULL qalır və
        gecəlik iş yenidən cəhd edir.
        """
        if self._break_glass_reporter_cache is None:
            from src.infrastructure.licensing.break_glass_reporter import (  # noqa: PLC0415
                VendorGatewayBreakGlassReporter,
            )
            from src.infrastructure.persistence.connection_types import (  # noqa: PLC0415
                VendorDatabase,
            )

            try:
                vendor = VendorDatabase.from_env()
            except Exception as exc:
                _log.warning("BREAK_GLASS_VENDOR_UNAVAILABLE", extra={"error": str(exc)})
                vendor = None
            self._break_glass_reporter_cache = (
                VendorGatewayBreakGlassReporter(vendor) if vendor is not None else False
            )
        return self._break_glass_reporter_cache or None

    def _job_break_glass_expiry(self, context: Any) -> str:
        """Faza 5.4 — vaxtı keçmiş sorğuları/səlahiyyətləri bağlayır."""
        with self.session() as session:
            closed = session.break_glass.expire_due(tenant_id=context.tenant_id)
            session.commit()
        return f"{closed} fövqəladə giriş sətri bağlandı"

    def _job_break_glass_vendor_retry(self, context: Any) -> str:
        """Faza 5.4 — mərkəzi bazaya çatmamış sətirləri yenidən göndərir.

        Bildirici yoxdursa (müştəri quraşdırması, DB-3) use case DƏRHAL 0
        qaytarır — iş `FAILED` OLMUR: bildiricinin olmaması nasazlıq deyil,
        gözlənilən vəziyyətdir (`_job_drive_quota_check`-in eyni qərarı).
        """
        with self.session() as session:
            sent = session.break_glass.retry_vendor_reports(tenant_id=context.tenant_id)
            session.commit()
        return f"{sent} sətir mərkəzi bazaya göndərildi"

    def _job_offline_backlog_check(self, context: Any) -> str:
        """Faza 5.1 — offline buferin yaşı/həcmi həddi aşıbsa HR-ə xəbərdarlıq.

        BUFER QURULMAYIBSA İŞ SAKİT DAYANIR (`_job_drive_quota_check` naxışı):
        offline bufer TƏNBƏLdir və heç vaxt yazı olmamış quraşdırmada SQLite
        faylı ola bilməz — bu, xəta deyil.

        `mark_alerted()` YALNIZ bildiriş göndərildikdən SONRA çağırılır:
        `Notifier` istisna atsa təkrar-susma pəncərəsi bağlanmamalıdır (bax
        `backlog.py`).
        """
        buffer = self._offline_buffer_if_present()
        if buffer is None:
            return "offline bufer qurulmayıb"

        from src.infrastructure.offline.backlog import (  # noqa: PLC0415
            OfflineBacklogMonitor,
        )

        monitor = OfflineBacklogMonitor(buffer, limits=self._infrastructure_limits)
        tenant_text = str(context.tenant_id)
        assessment = monitor.assess(tenant_id=tenant_text, now=context.now)
        if not monitor.should_alert(assessment, tenant_id=tenant_text, now=context.now):
            return assessment.summary_az

        # `Session` BİLDİRİCİ SAXLAMIR (`notifier` `_build_session`-un yerli
        # dəyişənidir) — planlayıcı işi onu ÖZÜ qurur. Bu, `_job_nightly_
        # backup`-ın `DriveConnectionRepository`-ni sessiyadan KƏNARDA
        # qurmasının eyni naxışıdır: bildiriş yazısı öz qısa iş vahidini açır.
        self._notify(
            tenant_id=context.tenant_id,
            # `can_manage_employees` auditoriyası (HR) — konkret alıcı
            # YOXDUR, çünki problem MAĞAZANINDIR, bir şəxsin deyil.
            recipient_id=None,
            category="OFFLINE_BACKLOG",
            title_az="Uzun-müddətli offline rejim",
            body_az=(
                f"{assessment.summary_az} Giriş və davamiyyət İŞLƏMƏYƏ "
                "DAVAM EDİR — məlumat serverə hələ çatmayıb."
            ),
        )
        monitor.mark_alerted(tenant_id=tenant_text, now=context.now)
        return f"XƏBƏRDARLIQ: {assessment.summary_az}"

    def _job_hardware_health_check(self, context: Any) -> str:
        """Faza 5.2 — disk/RAM həddi aşıbsa filialın texniki-məsuluna bildiriş.

        ALICI SEÇİMİ İKİ PİLLƏLİDİR: bu PC-nin qeydiyyatdan keçmiş cihazı →
        onun filialı → filialın `technical_contact_employee_id`-si. Zəncirin
        hər hansı halqası yoxdursa alıcı `None` olur, yəni bildiriş
        KATEQORİYA auditoriyasına gedir — nasazlıq xəbəri SÜKUTLA İTMİR
        (`migrations/089`-un `NULL = defolt kanal` şərhi).
        """
        from src.infrastructure.erp.system_health import (  # noqa: PLC0415
            disk_metric,
            memory_metric,
        )

        problems = [
            metric
            for metric in (
                disk_metric(limits=self._infrastructure_limits),
                memory_metric(limits=self._infrastructure_limits),
            )
            if metric.level.needs_attention
        ]
        if not problems:
            return "disk/RAM normaldır"

        # Təkrar-susma pəncərəsi offline bufer faylında saxlanılır — SƏBƏB:
        # aparat nasazlığı MAŞINA aiddir, kirayəçiyə yox, və məhz disk dolu
        # olanda bazaya yazmaq mümkün olmaya bilər (`backlog.py` naxışı).
        buffer = self._offline_buffer_if_present()
        cooldown_hours = self._infrastructure_limits.int_of(
            SystemLimitKey.HEALTH_HARDWARE_ALERT_COOLDOWN_HOURS
        )
        alert_key = f"hardware_alerted_at:{context.tenant_id}"
        if buffer is not None and not _cooldown_elapsed(
            buffer.read_meta(alert_key), now=context.now, hours=cooldown_hours
        ):
            return "xəbərdarlıq təkrar-susma pəncərəsindədir"

        summary = "; ".join(f"{metric.title_az}: {metric.value_az}" for metric in problems)
        recipient = self._technical_contact()
        self._notify(
            tenant_id=context.tenant_id,
            recipient_id=recipient,
            category="HARDWARE_HEALTH",
            title_az="Kiosk/POS aparat nasazlığı",
            body_az=(
                f"{summary}. Ətraflı: "
                + " ".join(metric.detail_az for metric in problems if metric.detail_az)
            ),
        )
        if buffer is not None:
            buffer.write_meta(alert_key, context.now.isoformat())
        return f"XƏBƏRDARLIQ: {summary}"

    def _notify(
        self,
        *,
        tenant_id: Any,
        recipient_id: Any,
        category: str,
        title_az: str,
        body_az: str,
    ) -> None:
        """Planlayıcı işlərinin bildiriş yolu — öz qısa iş vahidi ilə.

        `is_critical=True` SABİTDİR: bu yolu YALNIZ Faza 5-in iki nasazlıq
        işi çağırır və hər ikisi e-poçt fallback-ı tələb edir (panelə baxan
        olmaya bilər — nasazlıq iş saatından kənarda baş verir).
        """
        from src.infrastructure.notifications.notifier import (  # noqa: PLC0415
            PostgresNotifier,
        )

        PostgresNotifier(self._database, limits=self._infrastructure_limits).notify(
            tenant_id=tenant_id,
            recipient_id=recipient_id,
            category=category,
            title_az=title_az,
            body_az=body_az,
            is_critical=True,
        )

    def _technical_contact(self) -> Any:
        """Bu PC-nin filialına təyin edilmiş texniki-məsul şəxs, ya `None`.

        HEÇ BİR HALDA İSTİSNA ATMIR: alıcının tapılmaması bildirişi
        dayandırmamalıdır (bax `_job_hardware_health_check`).
        """
        from src.infrastructure.config.device_identity import (  # noqa: PLC0415
            load_device_id,
        )

        try:
            device_id = load_device_id()
            if device_id is None:
                return None
            with self.session() as session:
                device = session.uow.repository("devices").get(device_id)
                if device is None or device.store_id is None:
                    return None
                return session.uow.repository("stores").technical_contact(
                    self._tenant_id, device.store_id
                )
        except Exception as exc:  # alıcı tapılmaması bildirişi dayandırmır
            _log.warning("HARDWARE_ALERT_RECIPIENT_UNRESOLVED", extra={"error": str(exc)})
            return None

    def _offline_buffer_if_present(self) -> Any:
        """Mövcud offline buferi qaytarır, YOXDURSA QURMUR.

        `offline_drain()`-dən FƏRQİ budur: o, buferi lazım olanda YARADIR
        (baza keçidi yolu), bu isə yalnız MÖVCUDUNU verir. Planlayıcı işi
        heç vaxt yazı olmamış quraşdırmada SQLite faylı yaratmamalıdır —
        yaradılan boş bufer «offline rejim var» təəssüratı verərdi.
        """
        drain = self._offline_drain
        return drain.opened_buffer if drain is not None else None

    def _job_drive_quota_check(self, context: Any) -> str:
        """Faza 3.9 — aktiv Drive hesabının kvotasını yoxlayır.

        DRIVE QURULMAYIBSA İŞ SAKİT DAYANIR: `drive_providers()` OAuth klient
        məlumatları olmadıqda `None` qaytarır və bu, XƏTA DEYİL — `.env.example`
        həmin açarların boş qala biləcəyini açıq yazır (cərimələr normal yaranır,
        şəkillər lokal növbədə gözləyir). İstisna atsaydıq, Drive işlətməyən
        quraşdırmada gecəlik hesabat HƏR GÜN `FAILED` göstərərdi və əsl
        nasazlıqlar həmin səs-küydə itərdi.

        MONİTOR ÖZÜ DƏ ŞƏBƏKƏ NASAZLIĞINI UDUR (`QuotaCheckResult.error`) —
        token/şəbəkə problemi işi çökdürmür, `drive_connections.last_error`-a
        yazılır. Burada onu mətnə çeviririk ki, planlayıcı hesabatında görünsün.

        `context.now` PLANLAYICIDAN gəlir (`Clock` portu ilə eyni mənbə):
        təkrar-xəbərdarlıq pəncərəsi (`DRIVE_QUOTA_WARNING_COOLDOWN_DAYS`)
        gecikmiş icrada da FAKTİKİ ana görə hesablanır və `datetime.now()`
        heç yerdə çağırılmır.

        `_job_nightly_backup` naxışı: `DriveConnectionRepository` `Session`-dan
        KƏNARDA qurulur, çünki o, `Database` alıb hər əməliyyat üçün öz qısa
        iş vahidini açır — Drive API çağırışı boyu tranzaksiya saxlamaq
        CLAUDE.md §6-nın qadağasıdır (şəbəkə taymautu kilidi uzadardı).
        """
        from src.infrastructure.notifications.notifier import PostgresNotifier  # noqa: PLC0415
        from src.infrastructure.storage.connections import (  # noqa: PLC0415
            DriveConnectionRepository,
        )
        from src.infrastructure.storage.quota_monitor import DriveQuotaMonitor  # noqa: PLC0415

        with self.session() as session:
            max_upload_bytes = int(session.max_upload_bytes())
        factory = self.drive_providers(max_upload_bytes=max_upload_bytes)
        if factory is None:
            return "Drive konfiqurasiya edilməyib — kvota yoxlaması atlandı"

        monitor = DriveQuotaMonitor(
            repository=DriveConnectionRepository(self._database, self._tenant_id),
            provider_factory=factory,
            # Xəbərdarlıq TENANT səviyyəsinə gedir (`recipient_id=None`) və
            # marşrutlaşdırma `can_manage_drive_connection` flag-inə görə olur —
            # yəni ayrıca alıcı siyahısı SAXLANMIR (bax `quota_monitor._notify`).
            notifier=PostgresNotifier(self._database, limits=self._infrastructure_limits),
            tenant_id=self._tenant_id,
            # Hədd və təkrar-susma müddəti ROOT-dan; AÇIQ dəyər ötürülmür ki,
            # Root sürüşdürücünü tərpədəndə növbəti icra onu görsün.
            limits=self._infrastructure_limits,
        )
        result = monitor.check(now=context.now)

        if result.error:
            return f"Kvota oxunmadı: {result.error}"
        if not result.checked:
            return "Aktiv Drive bağlantısı yoxdur"

        parts = [f"kvota {result.quota.percent}%" if result.quota else "kvota naməlum"]
        if result.marked_exceeded:
            parts.append("bağlantı QUOTA_EXCEEDED işarələndi")
        if result.warning_sent:
            parts.append("xəbərdarlıq göndərildi")
        return ", ".join(parts)

    # --------------------------- planlanmış işlər ---------------------------- #
    #
    # HƏR İŞ ÖZ SESSİYASINI AÇIR VƏ COMMIT EDİR — kontroller naxışının eynisi
    # (CLAUDE.md §6): dövrə boyu tək tranzaksiya saxlamaq `pg_dump` müddətində
    # kilid tutardı və bir işin çökməsi ARTIQ TAMAMLANMIŞ işlərin yazısını da
    # geri qaytarardı, halbuki nüvənin qaydası qismən uğurdur.
    #
    # Hamısı `context.now`-u ötürür: vaxt `Clock` portundan gəlir və gecikmiş
    # icrada (kompüter gecə söndürülüb) hesablama pəncərəsi FAKTİKİ ana görə
    # qurulur — `datetime.now()` heç yerdə çağırılmır.

    def _job_behavior_baseline(self, context: Any) -> str:
        """#8 — işçi davranış baz xəttini yenidən hesablayır."""
        with self.session() as session:
            report = session.behavior_baselines.recalculate_all(context.tenant_id, now=context.now)
            session.commit()
        return f"{report.employees_updated} işçinin baz xətti yeniləndi"

    def _job_exception_engine(self, context: Any) -> str:
        """#9 — Vahid İstisna Motorunu işlədir (bax `_register_scheduled_jobs`)."""
        with self.session() as session:
            report = session.exceptions.run(tenant_id=context.tenant_id, now=context.now)
            session.commit()
        return (
            f"{report.evaluated_rules} qayda, {report.created_total} yeni istisna, "
            f"{report.duplicate_total} təkrar atlandı"
        )

    def _job_staffing_pattern(self, context: Any) -> str:
        """#13 — hər AKTİV mağaza üçün həftə-günü ortalarını yeniləyir.

        MAĞAZA SİYAHISI ÜÇÜN YENİ REPO YARADILMIR: `multi_store_benchmark`
        repo-sunun `active_stores()` metodu artıq məhz bu sorğunu edir
        (`SELECT id, name FROM stores WHERE tenant_id = %s AND is_active`).
        İkinci bir siyahı mənbəyi qursaydıq, «aktiv mağaza» tərifi iki yerdə
        yaşayar və biri dəyişəndə digəri sükutla köhnə qalardı.

        BİR MAĞAZANIN XƏTASI DÖVRƏNİ DAYANDIRIR (burada təcrid YOXDUR) və bu
        qəsdəndir: siyahı eyni sorğudan gəlir, yəni bir mağazada çöküş
        məlumatın deyil, bağlantının problemidir — qalan mağazaları sınamaq
        eyni xətanı təkrarlayardı. Nüvə onsuz da bu işi `FAILED` yazır və
        digər İŞLƏR davam edir.
        """
        with self.session() as session:
            stores = session.uow.repository("multi_store_benchmark").active_stores(
                context.tenant_id
            )
            weekdays = 0
            for store_id in stores:
                report = session.staffing_pattern.recalculate_for_store(
                    context.tenant_id, store_id=store_id, now=context.now
                )
                weekdays += report.weekdays_updated
            session.commit()
        return f"{len(stores)} mağaza, {weekdays} həftə-günü yeniləndi"

    def _job_document_expiry(self, context: Any) -> str:
        """#17 — bitmə tarixi yaxınlaşan sənədlər üçün xəbərdarlıq."""
        with self.session() as session:
            sent = session.employee_documents.notify_expiring_documents(context.tenant_id)
            session.commit()
        return f"{sent} sənəd xəbərdarlığı göndərildi"

    def _job_attrition_risk(self, context: Any) -> str:
        """#21 — işdən çıxma riski balını yenidən hesablayır."""
        with self.session() as session:
            report = session.attrition_risk.recalculate_all(context.tenant_id, now=context.now)
            session.commit()
        return (
            f"{report.employees_updated} bal yeniləndi, "
            f"{report.high_risk_count} yüksək risk, {report.notifications_sent} bildiriş"
        )

    def _job_field_report_audit_reminder(self, context: Any) -> str:
        """#26 — audit intervalı keçmiş filiallar üçün xatırlatma.

        `context.now` PLANLAYICIDAN gəlir və use case-in `Clock`-u ilə eyni
        mənbədən qidalanır (`_StandaloneLimits`/`JobRunner` eyni `self._clock`
        alır) — yəni "neçə gün keçib" hesablaması iki fərqli anla
        aparılmır.
        """
        with self.session() as session:
            result = session.field_reports.notify_overdue_audits(context.tenant_id)
            session.commit()
        return f"{result.checked} filialdan {result.overdue_count}-i audit intervalını keçib"

    def _job_support_status_maintenance(self, context: Any) -> str:
        """CHAT-1 — «Həll olundu» müraciətlərin bağlanması + xatırlatmalar.

        `context.now` PLANLAYICIDAN gəlir: gecikmiş icrada (kompüter gecə
        söndürülüb) hesablama FAKTİKİ ana görə aparılır və `datetime.now()`
        heç yerdə çağırılmır — eyni qərar `_job_annual_leave_rollover`-dədir.
        """
        with self.session() as session:
            result = session.support_inbox.run_maintenance(
                tenant_id=context.tenant_id, now=context.now
            )
            session.commit()
        return (
            f"{result['closed']} müraciət avtomatik bağlandı, "
            f"{result['reminded']} xatırlatma göndərildi"
        )

    def _job_annual_leave_rollover(self, context: Any) -> str:
        """#28 — illik haqq, köçürmə və "istifadə et ya itir" son tarixi.

        `context.now` PLANLAYICIDAN gəlir: gecikmiş icrada (kompüter gecə
        söndürülüb) hesablama FAKTİKİ ana görə aparılır və `datetime.now()`
        heç yerdə çağırılmır.

        İDEMPOTENTDİR — planlayıcı at-least-once icra edir və eyni il üçün
        ikinci icra balansı ikiqat ARTIRMIR (bax `AnnualLeaveUseCase.
        run_year_rollover` docstring-i).
        """
        with self.session() as session:
            report = session.annual_leave.run_year_rollover(
                tenant_id=context.tenant_id, now=context.now
            )
            session.commit()
        return (
            f"{report.year}: {report.balances_written} balans yazıldı, "
            f"{report.carried_over_days} gün köçürüldü, "
            f"{report.forfeited_days} gün itdi"
        )

    def _job_face_exemption_expiry(self, context: Any) -> str:
        """Bənd 14 — müddəti bitmiş Face Control istisnalarını bağlayır.

        `context.now` PLANLAYICIDAN gəlir (`Clock` portu ilə eyni mənbə):
        gecikmiş icrada (kompüter gecə söndürülüb) müqayisə FAKTİKİ ana görə
        aparılır və `datetime.now()` heç yerdə çağırılmır.

        İDEMPOTENTDİR — `list_due_for_expiry` yalnız `ACTIVE` sətirləri
        qaytarır, yəni ikinci icra heç nə tapmır (planlayıcının at-least-once
        zəmanəti üçün məcburi şərt).
        """
        with self.session() as session:
            expired = session.face_exemptions.expire_due(
                tenant_id=context.tenant_id, now=context.now
            )
            session.commit()
        return f"{expired} istisnanın müddəti bitdi"

    def _job_face_log_retention(self, context: Any) -> str:
        """Bənd 17 — saxlama müddətindən köhnə doğrulama qeydlərini silir.

        SİLMƏ, ANONİMLƏŞDİRMƏ YOX: jurnalda foto və vektor yoxdur, yalnız
        nəticə və bal var. 12 aylıq defolt mövcud Davranış Anomaliyası
        pəncərəsindən (30 gün) qat-qat genişdir — həmin hesablama POZULMUR.
        """
        with self.session() as session:
            removed = session.face_log_retention.purge(tenant_id=context.tenant_id, now=context.now)
            session.commit()
        return f"{removed} üz-doğrulama qeydi silindi"

    def _job_detect_absences(self, context: Any) -> str:
        """Gün sonunda «İcazəsiz Qayıb» təyinetməsi (DEEP-GAP OP-1).

        ──────────────────────────────────────────────────────────────────────
        BU İŞ NİYƏ İNDİ ƏLAVƏ OLUNUR
        ──────────────────────────────────────────────────────────────────────
        `MorningCheckInUseCase.detect_absences()` yazılıb, test edilib və
        sənəddə «gün sonunda işləyir» kimi təsvir olunub — LAKİN onu çağıran
        HEÇ BİR yol yox idi (`grep` bütün `src/` üzrə sıfır nəticə). Hesabat və
        export qatı isə `unauthorized_absence` sütununu OXUYUR, yəni sütunun
        DOLDURULDUĞUNU fərz edir. Nəticə: qayıb heç vaxt qeydə alınmırdı.

        `work_date` DÜNƏNdir, bugün DEYİL: iş gecə yarısından sonra işləyir və
        həmin anda «bu gün» hələ başlamayıb. Gecə növbəsi sərhədi
        `resolve_work_date` ilə həll olunur, yəni burada sadə `-1 gün` kifayət
        edir (növbə gününün özü domendə hesablanır).
        """
        from datetime import timedelta  # noqa: PLC0415

        work_date = (self.clock.now() - timedelta(days=1)).date()
        with self.session() as session:
            marked = session.morning_check_in.detect_absences(context.tenant_id, work_date)
            session.commit()
        return f"{marked} işçi «İcazəsiz Qayıb» kimi işarələndi ({work_date})"

    def _job_task_escalation(self, context: Any) -> str:
        """Son tarixi keçmiş tapşırıqları eskalasiya edir (DEEP-GAP OP-1).

        `escalate_overdue` modul başlığında «Onu istifadəçi deyil, planlayıcı
        çağırır» yazılıb — lakin planlayıcıda qeydiyyatı YOX İDİ. `HOURLY`:
        son tarix saat dəqiqliyindədir, gündəlik dövrə eskalasiyanı 23 saata
        qədər gecikdirərdi.
        """
        with self.session() as session:
            result = session.tasks.escalate_overdue(tenant_id=context.tenant_id)
            session.commit()
        return f"{result.escalated} tapşırıq gecikmiş kimi işarələndi"

    def _job_block_inactive_devices(self, context: Any) -> str:
        """Passivlik həddini keçmiş cihazları bloklayır (DEEP-GAP OP-1).

        Məqsəd lisenziya sayğacıdır: illər əvvəl silinmiş mağazanın PC-si
        əbədi yer tutmamalıdır. Aktor YOXDUR — `blocked_by=None` audit-də
        «avtomatik» kimi görünür.
        """
        with self.session() as session:
            blocked = session.devices.block_inactive_devices(tenant_id=context.tenant_id)
            session.commit()
        return f"{len(blocked)} passiv cihaz bloklandı"

    def _job_expire_open_shifts(self, context: Any) -> str:
        """Tarixi keçmiş açıq növbə elanlarını bağlayır (DEEP-GAP OP-4).

        `DAILY` — elanın vahidi GÜNdür (`shift_date`), saatlıq dövrə eyni
        sətirləri 24 dəfə boş yoxlayardı. `LIGHT`: indeksli sorğu + tapılan
        sətir qədər şərtli `UPDATE`.

        AKTOR YOXDUR: qərarı insan vermir, MÜDDƏT bitir — audit `actor_id=None`
        ilə yazılır (`FINE_EXPIRE_STALE` ilə eyni forma və eyni səbəb).
        """
        with self.session() as session:
            closed = session.open_shifts.expire_stale_postings(context.tenant_id)
            session.commit()
        return f"{closed} tarixi keçmiş elan bağlandı"

    def _job_escalate_verification_timeouts(self, context: Any) -> str:
        """45 dəqiqədən çox gözləyən təsdiqləri eskalasiya edir — HƏR İKİ tərəf (DEEP-GAP OP-2).

        ──────────────────────────────────────────────────────────────────────
        HƏDD KAĞIZ ÜZƏRİNDƏ QALMIŞDI
        ──────────────────────────────────────────────────────────────────────
        `VERIFICATION_TIMEOUT_MINUTES` Root açarı var, `escalate_timeouts()`
        yazılıb və testlidir — LAKİN onu çağıran yol YOX İDİ. Nəticə: operator
        naharda ikən işçinin «Mən Qayıtdım» sorğusu 🟡-da SONSUZ qalırdı, işçi
        növbəti icazəni ala bilmirdi (sorğu açıq sayılır) və HR heç nə
        bilmirdi. Hədd yalnız sənəddə işləyirdi.

        ──────────────────────────────────────────────────────────────────────
        ESKALASİYA QƏRAR VERMİR — SƏLAHİYYƏT GENİŞLƏNMİR
        ──────────────────────────────────────────────────────────────────────
        Hər iki metod statusu 🟡 SAXLAYIR (nə təsdiq, nə rədd): yalnız möhür
        vurulur və HR_Admin/CEO-ya bildiriş gedir. Ona görə aktorsuz icra
        təhlükəsizdir — manual təsdiq/rədd yolu isə yenə səlahiyyət qapısının
        arxasındadır və orada aktor VAR.

        İDEMPOTENTLİK MÖHÜRDƏDİR: hər sətir yalnız BİR DƏFƏ qalxır
        (`escalated_at`), yəni saatlıq dövrə eyni sətri təkrar-təkrar
        bildirmir.

        Bildiriş `recipient_id=None` ilə gedir — HR_Admin/CEO növbəsinə düşür,
        konkret şəxsə yox (use case-in öz qərarı, burada təkrarlanmır).
        """
        with self.session() as session:
            returns = session.leave_verification.escalate_timeouts(context.tenant_id)
            # GİRİŞ TƏRƏFİ — AKTORSUZ İMZA (DEEP-GAP OP-2, ikinci yarı).
            # `escalate_timeouts(tenant_id, operator_id)` mağaza dəstini
            # operatorun kamera təyinatından çıxarır və planlayıcıda AKTOR
            # YOXDUR; uydurma aktor audit izini yalanlaşdırardı. Ona görə
            # domen AYRI, kirayəçi-geniş metod verdi. İkisi EYNİ işdədir,
            # çünki hər ikisi EYNİ həddi (`VERIFICATION_TIMEOUT_MINUTES`)
            # izləyir — ayrı işlərə bölsəydik, eyni 45 dəqiqəlik vəd iki
            # fərqli gecikmə ilə yerinə yetirilərdi.
            check_ins = session.morning_check_in.escalate_timeouts_for_tenant(context.tenant_id)
            session.commit()
        return f"{returns} qayıdış, {check_ins} giriş təsdiqi eskalasiya olundu"

    def _job_retention_purge(self, context: Any) -> str:
        """Sonsuz yığılan iki cədvəli saxlama müddətinə görə təmizləyir (SAAS-6).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ BİR İŞ, İKİ CƏDVƏL
        ──────────────────────────────────────────────────────────────────────
        Hər ikisi EYNİ sualın cavabıdır: «tamamlanmış qeyd nə qədər saxlanır?»
        və hər ikisi EYNİ Root açarından (`EVIDENCE_UPLOAD_RETENTION_DAYS`)
        oxuyur. İki ayrı iş yazsaydıq, planlayıcı hesabatında iki sətir olardı
        və biri sükutla söndürüləndə digəri «hər şey təmizlənir» təəssüratı
        yaradardı.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ TƏMİZLƏMƏ PLANLAYICIDADIR, REPOZİTORİYADA DEYİL
        ──────────────────────────────────────────────────────────────────────
        `purge_uploaded` / `purge_resolved` KƏSİM ANINI arqument kimi alır və
        Root açarını ÖZLƏRİ oxumur (`purge_synced` / `purge_older_than` ilə
        eyni imza qərarı) — belə olduqda repozitoriya siyasətdən asılı qalmır
        və test determinstik vaxtla işləyir. Siyasəti oxuyan tərəf BURADIR.

        UĞURSUZLUQ İŞİ ÇÖKDÜRMÜR, LAKİN SÜKUTLA DA KEÇMİR: hər iki addım öz
        nəticəsini mətnə yazır, xəta isə planlayıcının `FAILED` hesabatına
        düşür — «zibil yığılır» vəziyyəti görünməz qalmamalıdır.

        `context.now` PLANLAYICIDAN gəlir (`_job_drive_quota_check`-dəki eyni
        səbəb): gecikmiş icrada da kəsim FAKTİKİ ana görə hesablanır.
        """
        from datetime import timedelta  # noqa: PLC0415

        key = SystemLimitKey.EVIDENCE_UPLOAD_RETENTION_DAYS
        with self.session() as session:
            # `max_upload_bytes()` ilə EYNİ oxu naxışı: dəyər ROOT-dan gəlir,
            # `DEFAULT_LIMITS` isə YALNIZ fallback-dır (sətir seed edilməyibsə).
            days = session.limits.get_int(session.tenant_id, key.value, int(DEFAULT_LIMITS[key]))
        cutoff = context.now - timedelta(days=days)

        # Sübut növbəsi LOKAL SQLite-dadır (kirayəçiyə görə ayrılmır — fayl
        # onsuz da BİR kirayəçinin maşınındadır, bax SAAS-3), konflikt cədvəli
        # isə Postgres-dədir və öz sessiyasını tələb edir.
        uploads = self.evidence_queue().purge_uploaded(older_than=cutoff)
        with self.session() as session:
            conflicts = session.uow.repository("sync_conflicts").purge_resolved(cutoff=cutoff)
            session.commit()
        return f"{uploads} yüklənmiş sətir, {conflicts} həll edilmiş konflikt silindi ({days} gün)"

    def _job_expire_stale_appeals(self, context: Any) -> str:
        """Cavabsız qalmış cərimə etirazlarını bağlayır (72 saatlıq pəncərə)."""
        with self.session() as session:
            closed = session.fine_appeals.expire_stale(context.tenant_id)
            session.commit()
        return f"{closed} etiraz cavabsız bağlandı"

    def _job_expire_pending_overrides(self, context: Any) -> str:
        """M-5 — ikinci təsdiqi gözləyən vaxt düzəlişlərini ləğv edir.

        `FINE_EXPIRE_STALE` ilə eyni naxış: müddət `system_limits`-dədir, iş
        yalnız onu TƏTBİQ edir. Avtomatik təsdiq YOXDUR (bax use case).
        """
        with self.session() as session:
            expired = session.leave_verification.expire_pending_overrides(context.tenant_id)
            session.commit()
        return f"{expired} vaxt düzəlişi təsdiqsiz ləğv olundu"

    def _job_scheduled_transfers(self, context: Any) -> str:
        """`v2backlog.md` Faza 3.3 — planlaşdırılmış filiallar-arası köçürmələri tətbiq edir."""
        with self.session() as session:
            applied = session.transfer_requests.apply_scheduled_transfers(context.tenant_id)
            session.commit()
        return f"{applied} köçürmə tətbiq edildi"

    def _job_scheduled_employee_deactivation(self, context: Any) -> str:
        """`v2backlog.md` Faza 3.1 — planlaşdırılmış tarixi çatan işçiləri deaktiv edir.

        `_register_scheduled_jobs`-dakı QAPI SINIĞI qeydinə bax: oxuyucu
        portu hələ bağlanmayıb, ona görə bu iş HAZIRDA HƏMİŞƏ 0 qaytarır.
        """
        with self.session() as session:
            deactivated = session.users.deactivate_scheduled_employees(context.tenant_id)
            session.commit()
        return f"{deactivated} işçi planlaşdırılmış tarixlə deaktiv edildi"

    def _job_former_employee_anonymization(self, context: Any) -> str:
        """`v2backlog.md` Faza 3.2 — retensiya müddəti keçmiş keçmiş işçiləri anonimləşdirir.

        `_register_scheduled_jobs`-dakı QAPI SINIĞI qeydinə bax: oxuyucu
        portu hələ bağlanmayıb, ona görə bu iş HAZIRDA HƏMİŞƏ 0 qaytarır.
        """
        with self.session() as session:
            anonymized = session.users.anonymize_former_employees(context.tenant_id)
            session.commit()
        return f"{anonymized} keçmiş işçi anonimləşdirildi"

    def _job_executive_digest(self, context: Any) -> str:
        """#30 — planlaşdırılmış icra xülasəsi (bax `_register_scheduled_jobs`).

        `context.scheduled_for` ötürülür, `context.now` DEYİL — həftəlik
        tezliyin "bu gün DUE-durmu?" sualı MAĞAZANIN yerli təqvim gününə
        əsaslanır (bax `ExecutiveDigestUseCase.run` docstring-i).
        """
        with self.session() as session:
            report = session.executive_digest.run(
                tenant_id=context.tenant_id, now=context.now, scheduled_for=context.scheduled_for
            )
            session.commit()
        return f"{report.evaluated} konfiqurasiyadan {report.sent}-i göndərildi"

    def _job_nightly_backup(self, context: Any) -> str:
        """Gecəlik ehtiyat nüsxə + saxlama müddəti bitmiş faylların təmizliyi.

        YEGANƏ `HEAVY` İŞ. `NightlyBackupService` `Session`-dan KƏNARDA
        qurulur, çünki o, `Database` alıb öz iş vahidini açır (`pg_dump` xarici
        prosesdir və dəqiqələrlə çəkir — açıq tranzaksiya saxlamaq CLAUDE.md
        §6-nın qadağasıdır). Limit pəncərəsi ona görə UZUN ÖMÜRLÜ
        `infrastructure_limits()`-dir, sessiya ömürlü `session_limits` yox.

        `create()` və `prune()` BİR işdədir: təmizlik yalnız yeni nüsxə
        UĞURLA yazıldıqdan sonra mənalıdır — əks sıra disk dolu olanda son
        işlək nüsxəni silib yenisini yarada bilməmək riski yaradardı.
        """
        from src.infrastructure.backup.service import NightlyBackupService  # noqa: PLC0415

        service = NightlyBackupService(self._database, limits=self._infrastructure_limits)
        record = service.create(context.tenant_id)
        removed = service.prune(context.tenant_id)
        return f"nüsxə {record.size_bytes} bayt, {removed} köhnəlmiş fayl silindi"

    # ------------------------------- sessiya --------------------------------- #

    @contextmanager
    def session(self, *, user_id: EmployeeId | None = None) -> Iterator[Session]:
        """Bir tranzaksiya + onun üzərində qurulmuş use case dəsti.

        `read_batch()` aktiv olduqda YENİ tranzaksiya açılmır — mövcud olan
        təkrar istifadə edilir (bax həmin metodun izahı).

        AKTOR ŞƏRTİ: toplu yalnız `user_id` verilmədikdə, VƏ YA toplunun öz
        aktoru ilə eyni olduqda təkrar istifadə edilir. BAŞQA aktor istənirsə
        çağırış öz sessiyasını alır — əks halda `app.user_id` GUC-u səhv
        şəxsi göstərərdi.

        `user_id=None` halının topluya düşməsi TƏHLÜKƏSİZDİR: `app.user_id`
        heç bir RLS OXU siyasətində işlənmir — onu yalnız `position_permissions`
        üzərindəki `DELETE` trigger-i oxuyur (miqrasiya 046), yəni yazma yolu.
        Deməli aktoru olan tranzaksiyada aktorsuz oxu APARMAQ nəticəni nə
        daraldır, nə genişləndirir.
        """
        shared = getattr(self._read_batch, "session", None)
        if shared is not None and (
            user_id is None or user_id == getattr(self._read_batch, "user_id", None)
        ):
            try:
                yield shared
            except Exception:
                # ────────────────────────────────────────────────────────────
                # BİR SINAN OXU TOPLUNU ÖLDÜRÜR — VƏ BU, QƏSDƏNDİR
                # ────────────────────────────────────────────────────────────
                # PostgreSQL sorğu xətasından sonra tranzaksiyanı ABORTED
                # vəziyyətinə salır: həmin tranzaksiyada NÖVBƏTİ hər sorğu
                # «current transaction is aborted» ilə dayanır. Toplu olmasaydı
                # bu, YALNIZ bir oxuya təsir edərdi (hər biri öz sessiyasında
                # idi) — yəni birləşdirmə dayanıqlılığı azaldır.
                #
                # Ona görə ilk xətada toplu SÖNDÜRÜLÜR: sonrakı oxular yenidən
                # ÖZ sessiyalarını açır və köhnə, dayanıqlı davranış qayıdır.
                # Yalnız BU oxu itir.
                #
                # ALTERNATİV RƏDD EDİLDİ — hər oxunu `SAVEPOINT`-ə salmaq
                # izolyasiyanı saxlayardı, lakin SAVEPOINT + RELEASE iki əlavə
                # gediş-gəlişdir; 12 oxu üçün bu, ~5 saniyə deməkdir və
                # optimallaşdırmanın ÖZÜNÜ yeyərdi.
                self._read_batch.session = None
                self._read_batch.user_id = None
                # İş vahidi də buraxılır: `_RootLimitReader` ona BİRBAŞA baxır
                # (PERF-4) və ABORTED tranzaksiyada növbəti limit oxusu da
                # sınardı — yəni bir sınan oxu limitləri də yıxardı.
                self._read_batch.uow = None
                _log.warning("READ_BATCH_ABORTED", extra={"reason": "sorğu xətası"})
                raise
            return
        with self._database.unit_of_work(self._tenant_id, user_id=user_id) as uow:
            # ──────────────────────────────────────────────────────────────
            # AÇIQ SESSİYA VARKƏN LİMİT OXUSU İKİNCİ TRANZAKSİYA AÇMIR (PERF-5)
            # ──────────────────────────────────────────────────────────────
            # Ölçüldü (canlı baza, gediş-gəliş ~206 ms): «Sistem Sağlamlığı»
            # ekranı 3.8 saniyə çəkirdi və onun İKİ sessiyası vardı —
            # birincisi ekranın öz oxusu, ikincisi isə həmin oxunun İÇİNDƏ
            # `NtpVerifier`-in soruşduğu `NTP_*` limiti (`InfrastructureLimits.
            # _raw` → `_RootLimitReader.get_str`). Sessiyanın öz yükü ~0.63 s
            # olduğu üçün bu, xalis itki idi: eyni sapda ARTIQ AÇIQ, eyni
            # kirayəçiyə aid tranzaksiya vardı.
            #
            # `read_batch()`-in `uow` paylaşması (PERF-4) məhz bu problemi
            # açılış yolunda həll edirdi; burada həmin mexanizm EKRAN
            # sessiyalarına da şamil olunur. `session` sahəsi TOXUNULMUR —
            # yalnız `uow`: yəni yuvalanmış `session()` çağırışları KÖHNƏ
            # davranışı (öz tranzaksiyası) saxlayır və bu, qəsdəndir, çünki
            # onların aktoru fərqli ola bilər (yuxarıdakı AKTOR ŞƏRTİ).
            #
            # DAXİLDƏKİ toplu SAHİBİ DEYİLİK: `read_batch()` onsuz da aktivdirsə
            # yuxarıdakı budaq işə düşür və bura ÇATILMIR.
            previous = getattr(self._read_batch, "uow", None)
            self._read_batch.uow = uow
            try:
                yield self._build_session(uow)
            finally:
                # Bərpa: sessiya bağlananda paylaşım DA bitir — bağlanmış
                # tranzaksiyanın iş vahidi sonrakı limit oxusuna verilsəydi,
                # oxu «bağlantı qaytarılıb» xətası ilə sınardı.
                self._read_batch.uow = previous

    @contextmanager
    def read_batch(self, *, user_id: EmployeeId | None = None) -> Iterator[bool]:
        """Ardıcıl OXULARI BİR tranzaksiyada birləşdirir (PERF-3).

        ──────────────────────────────────────────────────────────────────────
        PROBLEM: PANELİN AÇILIŞI 13 TRANZAKSİYA İDİ
        ──────────────────────────────────────────────────────────────────────
        `show_admin()` girişdən sonra bir sıra kiçik oxu edir — saxlanmış tema,
        aktiv modullar, plugin siyahısı, planlayıcı intervalı, cərimə növləri,
        işçi adları, bildiriş sayğacı, dəstək nişanları, kontekst altyazıları.
        Hər biri ÖZ sessiyasını açırdı. Ölçüldü (uzaq baza, gediş-gəliş
        ~206 ms): 13 sessiya → `show_admin` **18 saniyə**, üstəlik ilk ekran.
        Sessiyanın öz yükü (BEGIN + kontekst + bağlanış) təxminən 0.63 s-dir,
        yəni vaxtın yarıdan çoxu SORĞU DEYİL, tranzaksiya açıb-bağlamaq idi.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ SAPA GÖRƏ AYRI (`threading.local`)
        ──────────────────────────────────────────────────────────────────────
        `BackgroundTask` bəzi ekranlarda (server sağlamlığı, ERP sınağı) FON
        SAPINDA öz sessiyasını açır. Paylaşılan istinad qlobal olsaydı, həmin
        sap əsas sapın psycopg bağlantısına eyni anda yazar və bağlantı
        vəziyyəti pozulardı — bu, sükutlu və təkrarlanması çətin nasazlıqdır.
        `threading.local` ilə toplu YALNIZ onu açan sapa aiddir; digər saplar
        həmişə öz tranzaksiyalarını alır.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ «UZUN TRANZAKSİYA QADAĞASI»-nı POZMUR (CLAUDE.md §6)
        ──────────────────────────────────────────────────────────────────────
        Qadağa PANELİN ÖMRÜ boyu açıq qalan sessiyaya aiddir: panel saatlarla
        açıq durur və o müddətdə kilid saxlamaq olmaz. Bu toplu isə AÇILIŞ
        BURSTUdur — saniyələrlə ölçülür və `with` bloku bitən kimi bağlanır.
        Kontrollerlərin əməliyyat-başına-sessiya qaydası DƏYİŞMİR.

        YALNIZ OXU ÜÇÜNDÜR: daxildə `commit()` çağırılarsa, o, topludakı BÜTÜN
        işi təsdiqləyər. Yazı yolları (kontrollerlər) topludan KƏNARDA qalır.

        ──────────────────────────────────────────────────────────────────────
        TOPLU AÇILA BİLMƏSƏ AXIN DAYANMIR
        ──────────────────────────────────────────────────────────────────────
        Tranzaksiyanı açmaq özü uğursuz ola bilər (hovuz tükənib, bağlantı
        qırılıb). Bu, YALNIZ optimallaşdırmadır — onun uğursuzluğu girişi
        dayandırmamalıdır. Belə halda toplusuz davam edilir: hər oxu yenidən
        öz sessiyasını açır, yəni panel yavaş, LAKİN işlək qalır. Səbəb loga
        düşür ki, «niyə yavaşdır?» sualı cavabsız qalmasın.

        ──────────────────────────────────────────────────────────────────────
        QAYTARILAN `bool` NİYƏ VAR (UI-1)
        ──────────────────────────────────────────────────────────────────────
        Toplu AÇILA BİLMƏSƏ çağıran (`show_admin`) 1-2 saniyəlik gözləntisi
        13-sessiyalı ~18 saniyəyə geri qayıdığını BİLMƏLİDİR — əks halda
        bloklama müddətinin göstəricisi (`flush_ui`/busy vəziyyəti) yalnız
        "adi" halı nəzərə alıb erkən sönə bilər. Log tək başına KİFAYƏT ETMİR:
        o, operatora deyil, istifadəçiyə çatmalıdır. `True` = toplu aktivdir
        (yeni açılıb VƏ YA yuvalanıb — hər ikisində oxular sürətlidir),
        `False` = yalnız fallback halında, oxular köhnə yavaş yola qayıdıb.
        """
        if getattr(self._read_batch, "session", None) is not None:
            yield True  # yuvalanma — sahibi kənardadır, ikinci dəfə açmırıq
            return

        with ExitStack() as stack:
            try:
                uow = stack.enter_context(
                    self._database.unit_of_work(self._tenant_id, user_id=user_id)
                )
            except Exception:
                _error_log.exception("READ_BATCH_UNAVAILABLE")
                yield False  # toplusuz davam — davranış köhnə (yavaş) yola qayıdır
                return

            self._read_batch.session = self._build_session(uow)
            self._read_batch.user_id = user_id
            # İŞ VAHİDİNİN ÖZÜ DƏ PAYLAŞILIR (PERF-4): `Session` yalnız use
            # case qrafıdır və `system_limits` repo-suna yol vermir. Açılışdakı
            # limit oxuları isə `_RootLimitReader`-dən keçir — o, `session()`-ı
            # ÇAĞIRMIR, ona görə iş vahidini birbaşa görməlidir, əks halda hər
            # oxu üçün ikinci tranzaksiya açardı (ölçü: 4 oxu = 4.53 saniyə).
            self._read_batch.uow = uow
            try:
                yield True
            finally:
                self._read_batch.session = None
                self._read_batch.user_id = None
                self._read_batch.uow = None

    def _build_session(self, uow: PostgresUnitOfWork) -> Session:  # noqa: PLR0915
        """Use case qrafını cari `UnitOfWork`-un repo-ları ilə qurur.

        `PLR0915` (çox ifadə) BURADA SUSDURULUB — səbəb `pyproject.toml`-dakı
        ekran qurucuları istisnası ilə eynidir: bu, mürəkkəb MƏNTİQ deyil,
        BUDAQSIZ quraşdırma ardıcıllığıdır — hər use case üçün bir yerli
        idxal və bir konstruktor çağırışı. Faza 6 ona üç yeni use case əlavə
        etdi və hədd (50) keçildi.

        Onu `_build_session_part_1/2()`-yə bölmək oxunaqlığı ARTIRMAZDI:
        `Session` dataclass-ının sahələri bir yerdə qurulmalıdır, əks halda
        "bu use case hansı repo-nu alır?" sualının cavabı iki metod arasında
        parçalanardı. Əsl məntiq (lisenziya qapısı, tenant konteksti) ayrıca
        kiçik metodlardadır və bu istisnadan KƏNARDADIR.
        """
        from src.application.use_cases.announcements import (  # noqa: PLC0415
            AnnouncementUseCase,
        )
        from src.application.use_cases.annual_leave import (  # noqa: PLC0415
            AnnualLeaveUseCase,
        )
        from src.application.use_cases.attrition_risk import (  # noqa: PLC0415
            AttritionRiskUseCase,
        )
        from src.application.use_cases.audit_query import AuditQueryUseCase  # noqa: PLC0415
        from src.application.use_cases.authentication import (  # noqa: PLC0415
            SessionManagementUseCase,
        )
        from src.application.use_cases.backup_access import (  # noqa: PLC0415
            BackupAccessUseCase,
        )
        from src.application.use_cases.behavior_baseline import (  # noqa: PLC0415
            BehaviorAnomalyRule,
            BehaviorBaselineUseCase,
        )
        from src.application.use_cases.break_glass import (  # noqa: PLC0415
            BreakGlassUseCase,
        )
        from src.application.use_cases.bulk_operations import (  # noqa: PLC0415
            BulkEmployeeImportUseCase,
            StoreTemplateUseCase,
        )
        from src.application.use_cases.catalog_management import (  # noqa: PLC0415
            ChecklistItemTemplateUseCase,
            FineTypeCatalogUseCase,
            LeaveTypeCatalogUseCase,
            WorkModeCatalogUseCase,
        )
        from src.application.use_cases.daily_attendance import (  # noqa: PLC0415
            DailyAttendanceSheetUseCase,
        )
        from src.application.use_cases.dashboard_layout import (  # noqa: PLC0415
            DashboardLayoutUseCase,
        )
        from src.application.use_cases.db_switch import (  # noqa: PLC0415
            DatabaseSwitchUseCase,
        )
        from src.application.use_cases.device_registry import (  # noqa: PLC0415
            DeviceRegistryUseCase,
        )
        from src.application.use_cases.document_compliance import (  # noqa: PLC0415
            DocumentComplianceAdvisor,
        )
        from src.application.use_cases.dual_control_guard import (  # noqa: PLC0415
            DualControlDeadlockGuardUseCase,
        )
        from src.application.use_cases.employee_documents import (  # noqa: PLC0415
            EmployeeDocumentUseCase,
        )
        from src.application.use_cases.employee_profile import (  # noqa: PLC0415
            EmployeeProfileAccessUseCase,
        )
        from src.application.use_cases.employee_transfer import (  # noqa: PLC0415
            TransferRequestUseCase,
        )
        from src.application.use_cases.erp_connection import (  # noqa: PLC0415
            ErpConnectionWizardUseCase,
        )
        from src.application.use_cases.exception_engine import (  # noqa: PLC0415
            ExceptionEngineUseCase,
        )
        from src.application.use_cases.executive_digest import (  # noqa: PLC0415
            ExecutiveDigestUseCase,
        )
        from src.application.use_cases.export_preflight import (  # noqa: PLC0415
            ExportPreflightUseCase,
        )
        from src.application.use_cases.face_control import (  # noqa: PLC0415
            FaceControlExemptionUseCase,
            FaceEnrollmentUseCase,
            FaceLockReleaseUseCase,
            FaceMismatchExceptionRule,
            FaceReEnrollmentUseCase,
            FaceVerificationLogRetentionUseCase,
            FaceVerificationUseCase,
            OverdueFaceEnrollmentRule,
        )
        from src.application.use_cases.face_duplicates import (  # noqa: PLC0415
            DuplicateFaceExceptionRule,
        )
        from src.application.use_cases.field_reports import (  # noqa: PLC0415
            FieldReportUseCase,
        )
        from src.application.use_cases.fine_management import (  # noqa: PLC0415
            FineAppealUseCase,
            ManualFineUseCase,
            UnansweredFineAppealRule,
        )
        from src.application.use_cases.fine_review import (  # noqa: PLC0415
            HeldFineForInactiveEmployeeRule,
            MonthlyFineReviewUseCase,
            OverdueFineReviewRule,
        )
        from src.application.use_cases.first_run_setup import (  # noqa: PLC0415
            FirstRunSetupUseCase,
        )
        from src.application.use_cases.labor_compliance import (  # noqa: PLC0415
            LaborComplianceAdvisor,
        )
        from src.application.use_cases.leave_verification import (  # noqa: PLC0415
            LeaveVerificationUseCase,
        )
        from src.application.use_cases.morning_check_in import (  # noqa: PLC0415
            MorningCheckInUseCase,
        )
        from src.application.use_cases.multi_store_benchmark import (  # noqa: PLC0415
            MultiStoreBenchmarkUseCase,
        )
        from src.application.use_cases.offboarding_checklist import (  # noqa: PLC0415
            EmployeeOffboardingChecklistUseCase,
        )
        from src.application.use_cases.open_shift_market import (  # noqa: PLC0415
            OpenShiftMarketUseCase,
        )
        from src.application.use_cases.overtime_tracking import (  # noqa: PLC0415
            OvertimeTrackingUseCase,
        )
        from src.application.use_cases.performance_reviews import (  # noqa: PLC0415
            PerformanceReviewUseCase,
        )
        from src.application.use_cases.permission_guards import (  # noqa: PLC0415
            PermissionHierarchyGuardUseCase,
        )
        from src.application.use_cases.plugin_management import (  # noqa: PLC0415
            PluginManagementUseCase,
        )
        from src.application.use_cases.pos_threshold import (  # noqa: PLC0415
            POSThresholdUseCase,
        )
        from src.application.use_cases.position_management import (  # noqa: PLC0415
            PositionManagementUseCase,
        )
        from src.application.use_cases.reporting import MonthlyReportUseCase  # noqa: PLC0415
        from src.application.use_cases.root_control import (  # noqa: PLC0415
            RootControlUseCase,
        )
        from src.application.use_cases.sales_points import SalesPointsUseCase  # noqa: PLC0415
        from src.application.use_cases.sales_review_queue import (  # noqa: PLC0415
            SalesReviewQueueUseCase,
        )
        from src.application.use_cases.shift_handoff import (  # noqa: PLC0415
            ShiftHandoffUseCase,
        )
        from src.application.use_cases.shift_scheduling import (  # noqa: PLC0415
            ShiftPlanningUseCase,
            ShiftSwapUseCase,
        )
        from src.application.use_cases.staffing_pattern import (  # noqa: PLC0415
            StaffingPatternUseCase,
        )
        from src.application.use_cases.support_chat import (  # noqa: PLC0415
            SupportChatUseCase,
            SupportInboxUseCase,
        )
        from src.application.use_cases.sync_conflicts import (  # noqa: PLC0415
            SyncConflictUseCase,
        )
        from src.application.use_cases.task_workflow import (  # noqa: PLC0415
            TaskWorkflowUseCase,
        )
        from src.application.use_cases.telegram_config import (  # noqa: PLC0415
            TelegramConfigUseCase,
        )
        from src.application.use_cases.tenant_branding import (  # noqa: PLC0415
            TenantBrandingUseCase,
        )
        from src.application.use_cases.user_management import (  # noqa: PLC0415
            UserManagementUseCase,
        )
        from src.domain.exception_rules import ExceptionRuleRegistry  # noqa: PLC0415
        from src.infrastructure.backup.service import NightlyBackupService  # noqa: PLC0415
        from src.infrastructure.erp.one_c_connector import (  # noqa: PLC0415
            OneCConnectorFactory,
        )
        from src.infrastructure.erp.sales import (  # noqa: PLC0415
            PostgresSalesReviewRepository,
        )
        from src.infrastructure.erp.servers import (  # noqa: PLC0415
            ErpServerRepository,
            PostgresStoreServerMappingRepository,
        )
        from src.infrastructure.notifications.notifier import PostgresNotifier  # noqa: PLC0415
        from src.infrastructure.notifications.telegram import (  # noqa: PLC0415
            TelegramSupportGateway,
        )
        from src.infrastructure.plugins.signature import (  # noqa: PLC0415
            PluginSignatureVerifier,
            trust_store_from_env,
        )
        from src.infrastructure.security.encryption import EncryptionService  # noqa: PLC0415
        from src.infrastructure.security.hashing import HashingService  # noqa: PLC0415
        from src.presentation.plugin_surface import (  # noqa: PLC0415
            PluginRegistrySurface,
        )
        from src.shared.saga_orchestrator import SagaOrchestrator  # noqa: PLC0415
        from src.shared.saga_policies import policy_for  # noqa: PLC0415
        from src.shared.security_events import FailSoftSecurityEventRecorder  # noqa: PLC0415

        repo = uow.repository
        clock = self._clock
        ntp = self._ntp
        audit = uow.audit
        # SESSİYA ÖMÜRLÜ ROOT pəncərəsi: aşağıdakı üç infrastruktur obyekti
        # (bildirişçi, ehtiyat nüsxə xidməti, 1C konnektor fabriki) YALNIZ bu
        # tranzaksiya ərzində yaşayır, ona görə AÇIQ bağlantının repo-sundan
        # oxuyur — `_RootLimitReader` hər oxu üçün ikinci bağlantı açardı və
        # bu, hər ekran əməliyyatında təkrarlanardı (bax modul başlığı).
        session_limits = InfrastructureLimits(limits=repo("limits"), tenant_id=self._tenant_id)

        # ─────────────────────────────────────────────────────────────────────
        # TELEGRAM ŞLÜZÜ — AYARLARI HƏR ÇAĞIRIŞDA REPO-DAN OXUYUR
        # ─────────────────────────────────────────────────────────────────────
        # `settings_provider` use case-i DEYİL, REPOZİTORİYANI çağırır: use
        # case şlüzü `probe` kimi saxlayır və tərsinə asılılıq dövrə yaradardı.
        # Repo isə heç kimi tanımır — dövrə qapanmır.
        #
        # Vaxt `clock.now`-dandır (`datetime.now()` YOX): `telegram_sent_at`
        # server-lövbərli vaxtdan gəlməlidir (TIME-1), əks halda Windows saatı
        # sürüşdükdə mesaj sırası pozulardı.
        telegram_repository = repo("telegram_config")
        telegram_gateway = TelegramSupportGateway(
            settings_provider=lambda: telegram_repository.load(self._tenant_id),
            limits=session_limits,
            now=clock.now,
        )
        notifier = PostgresNotifier(self._database, limits=session_limits)
        # Üz təsdiqi adapterləri TƏNBƏL proxy ilə ötürülür: `face_engine()`
        # BURADA çağırılsaydı, `import face_recognition` (ölçülmüş ~1.0 s +
        # ~150 MB model yükü) İLK sessiyada — yəni tətbiqin açılışında — baş
        # verərdi. Proxy sayəsində qiymət yalnız FAKTİKİ üz əməliyyatında
        # ödənilir və Face Control əhatəsindən kənar mağazalar (bənd 15) onu
        # heç vaxt ödəmir. Kitabxana yüklənə bilmirsə proxy-nin arxasında
        # `UnavailableFaceEngine` durur və axın eskalasiyaya düşür — bənd 5.
        face_engine = _LazyFaceEngine(self.face_engine)
        # #17 İşçi Sənədləri (Faza 7) — BURAYA (əvvəllər `Session(...)` çağırışının
        # içində, aşağıda `employee_documents=` açarında idi) köçürüldü ki, EYNİ
        # instansiya `FaceEnrollmentUseCase`-ə `consent_documents` portu kimi
        # ötürülə bilsin (Faza 3.6). `BiometricConsentRecorder` Protocol-unu
        # `EmployeeDocumentUseCase.create_document` strukturla ÖDƏYİR — ayrı
        # adapter/repo lazım deyil (bax `face_control.py`-dakı Protocol başlığı).
        employee_documents = EmployeeDocumentUseCase(
            documents=repo("employee_documents"),
            employees=repo("employees"),
            limits=repo("limits"),
            audit=audit,
            clock=clock,
            notifier=notifier,
        )
        # İKİ YERDƏ LAZIMDIR (`users` ilə eyni naxış): həm `Session.face_
        # enrollment` sahəsi, həm də `FaceReEnrollmentUseCase` onu ALIR —
        # yenidən-qeydiyyat kadr çəkilişi/keyfiyyət süzgəci/orta vektor
        # məntiqini TƏKRARLAMIR, qeydiyyat use case-inin metodunu çağırır.
        face_enrollment = FaceEnrollmentUseCase(
            profiles=repo("face_embeddings"),
            camera=face_engine,
            matcher=face_engine,
            # `limits`: kadr sayı (`FACE_ENROLLMENT_FRAME_COUNT`), keyfiyyət
            # həddi (`FACE_ENROLLMENT_MIN_QUALITY`) və köhnəlmə intervalı
            # (`FACE_REENROLLMENT_REMINDER_MONTHS`) — üçü də ROOT-dandır.
            limits=repo("limits"),
            audit=audit,
            clock=clock,
            # SEC-025 şərti: tenant-da neçə aktiv admin var. Yalnız bootstrap
            # yolu (İlk Quraşdırma Sihirbazı) işlədir — bax
            # `FaceEnrollmentUseCase.enroll_first_account`.
            admins=repo("employees"),
            # Faza 3.6 — razılıq sənədinin arxivi (yuxarıdakı `employee_
            # documents` instansiyası, `BiometricConsentRecorder` kimi).
            # BAĞLANMAMIŞDAN ƏVVƏL: `capture_and_store` razılıq sənədini
            # SÜKUTLA YAZMIRDI (yalnız üz vektorunun ÖZÜ saxlanılırdı) — audit
            # jurnalında "razılıq soruşuldu, sənəd yaradılmadı" ilə "sənəd
            # arxivi HEÇ QURULMAYIB" halları eyni görünürdü.
            consent_documents=employee_documents,
        )

        # 1C REPO-LARI `uow.repository`-DƏ DEYİL — bu, qəsdəndir: onlar
        # `Database` alır və öz iş vahidini açır (bax `ErpServerRepository`),
        # çünki sinxronizasiya worker-i də eyni sinifləri GUI-dən tamamilə
        # kənarda işlədir. Onları bağlantı-səviyyəli repo-lara çevirmək həmin
        # yolu qırardı; şifrələmə isə burada YOX, repo-nun içində qalır.
        erp_servers = ErpServerRepository(self._database, self._tenant_id, EncryptionService())

        planning = ShiftPlanningUseCase(
            shifts=repo("shifts"),
            leave_requests=uow.leave_requests,
            audit=audit,
            clock=clock,
            notifier=notifier,
            # #14 — əmək qanunu məsləhətçisi. EYNİ `shifts` repo-su ötürülür:
            # xəbərdarlıq təyinatın YAZILDIĞI andakı planı görməlidir, ikinci
            # bağlantı isə hələ commit olunmamış sətri görməzdi.
            labor=LaborComplianceAdvisor(
                shifts=repo("shifts"),
                work_modes=repo("work_modes"),
                limits=repo("limits"),
            ),
            # #17 — sənəd bloklama məsləhətçisi. EYNİ bağlantıdakı repo:
            # hələ commit olunmamış sənəd dəyişikliyi (məs. eyni tranzaksiyada
            # `is_blocking` söndürülübsə) də nəzərə alınmalıdır.
            documents=DocumentComplianceAdvisor(
                documents=repo("employee_documents"),
                clock=clock,
            ),
            # #28 — təsdiqlənmiş illik məzuniyyət xəbərdarlığı. EYNİ bağlantı,
            # eyni səbəb: məzuniyyət elə bu tranzaksiyada təsdiqlənmişsə (toplu
            # əməliyyat yolu) təyinat onu DƏRHAL görməlidir. Repo YALNIZ
            # OXUNUR — matris məzuniyyəti dəyişmir, məzuniyyət matrisi
            # (bax `entities/annual_leave.py` başlığı).
            annual_leave=repo("annual_leave_requests"),
        )

        # XAL USE CASE-i YEREL DƏYİŞƏNDİR, çünki İKİ yerdə lazımdır: həm
        # `Session.sales_points`, həm də «Şübhəli Satışlar» növbəsinin
        # `points` asılılığı. İkinci nüsxə qursaydıq, eyni satışın xal
        # köçürməsi iki fərqli obyektdən keçərdi və `transfer_for_transaction`
        # daxilindəki modul yoxlaması iki dəfə oxunardı — nəticə eyni olsa da,
        # "hansı nüsxə doğrudur" sualı sonradan çaşdırıcı olur.
        sales_points = SalesPointsUseCase(
            points=repo("sales_points"),
            rewards=repo("rewards"),
            audit=audit,
            clock=clock,
            notifier=notifier,
            toggles=repo("toggles"),
            # AÇIQ BAĞLANTININ repo-su ötürülür (ikinci bağlantı YOX): xal
            # kursu (`SALES_POINTS_CURRENCY_PER_POINT`) mükafat yazısı ilə EYNİ
            # tranzaksiyada oxunmalıdır — Root kursu həmin an dəyişsəydi, ikinci
            # bağlantıdan oxunan dəyər yazılan sətirlə uyğunsuz olardı.
            limits=repo("limits"),
        )

        # VAHİD İSTİSNA MOTORU YEREL DƏYİŞƏNDİR, çünki qurulduqdan SONRA
        # #8-in qaydası ona `register_rule(...)` ilə qoşulur — motorun ÖZÜ
        # (`exception_engine.py`) buna görə DƏYİŞMİR, yalnız BU fayl (Faza 5-in
        # tək bağlantı nöqtəsi) yeni bir sətir alır (bax `exception_rules.py`
        # başlığı: reyestr məhz bu genişlənməni DDL-siz etmək üçün seçilib).
        exception_engine = ExceptionEngineUseCase(
            exceptions=repo("exceptions"),
            sources=repo("exception_sources"),
            registry=ExceptionRuleRegistry(),
            limits=repo("limits"),
            audit=audit,
            clock=clock,
            notifier=notifier,
        )
        exception_engine.register_rule(
            BehaviorAnomalyRule(
                baselines=repo("behavior_baselines"),
                checkins=repo("checkin_history"),
            )
        )
        # `facecontrol.md` bənd 16 — MISMATCH hadisələri HR-in VAHİD siyahısına
        # da düşür. Motorun ÖZÜ yenə DƏYİŞMİR: bu, ikinci bir `register_rule`
        # çağırışıdır və `FACE_MISMATCH` mənbəyi kataloqa migrations/047 ilə
        # seed edilib.
        #
        # ⚠️ BU, DƏRHAL-BİLDİRİŞİ ƏVƏZ ETMİR: uyğunsuzluq anında
        # `FaceVerificationUseCase` HR_Admin/Store Manager-ə təcili bildiriş
        # göndərir (bənd 3). Qayda isə gecəlik motorla işləyir — ikisini
        # birləşdirsəydik, sistemdəki ən güclü fırıldaqçılıq siqnalı bir
        # gecəlik gecikmə qazanardı.
        exception_engine.register_rule(
            FaceMismatchExceptionRule(verification_log=repo("face_verification_log"))
        )

        # ──────────────────────────────────────────────────────────────────
        # DÖRD YENİ QAYDA — HR-1/HR-2/HR-3 və UX-7 (DEEP-GAP)
        # ──────────────────────────────────────────────────────────────────
        # Hamısı EYNİ naxışdadır: motorun ÖZÜ dəyişmir, hər biri bir sətir
        # `register_rule(...)` alır. Qeydiyyatsız qalan qayda İŞLƏYİR, lakin
        # tapıntısı HEÇ BİR ekrana çatmır — yəni «yazılıb, çağırılmır» sinfi
        # (`test_composition_optional_port_wiring.py` başlığı) burada da
        # keçərlidir.
        #
        # MƏNBƏ KODLARI KATALOQDA OLMALIDIR (`exception_sources`, miqrasiya
        # 087): motor tapıntını `FOREIGN KEY`-ə görə yaza bilmirsə sükutla
        # atır — yəni seed olmadan dörd qayda da TƏSİRSİZ qalır.
        exception_engine.register_rule(
            # HR-1 — cavabsız cərimə etirazı. Avtomatik QƏRAR YOXDUR: qayda
            # yalnız GÖRÜNƏN edir (M-6 export kilidi toxunulmaz qalır).
            UnansweredFineAppealRule(appeals=repo("appeals"), fines=uow.fines)
        )
        exception_engine.register_rule(
            # HR-2 — nəşr gözləyən cərimə. Avtomatik NƏŞR YOXDUR.
            OverdueFineReviewRule(fines=uow.fines, employees=uow.employees)
        )
        exception_engine.register_rule(
            # HR-3 — deaktiv işçinin nəşr olunmayan cəriməsi. HR-2 ilə
            # KƏSİŞMİR (o, deaktiv işçini kənarda saxlayır) — eyni sətir iki
            # mənbədə görünsəydi HR iki fərqli həll yolu axtarardı.
            HeldFineForInactiveEmployeeRule(fines=uow.fines, employees=uow.employees)
        )
        exception_engine.register_rule(
            # UX-7 — möhləti keçmiş üz qeydiyyatı. Kiosk BLOKLANMIR (səbəb
            # qaydanın öz başlığındadır): qeydiyyat self-service deyil, yəni
            # bloklama işçini BAŞQASININ hərəkətsizliyinə görə cəzalandırardı.
            OverdueFaceEnrollmentRule(employees=repo("face_embeddings"))
        )
        exception_engine.register_rule(
            # v2backlog.md Faza 6.2 — eyni üzlü ikinci qeydiyyat şübhəsi.
            # Mənbə kataloqu migrations/102-də seedlənib; seed olmasa motor
            # tapıntını sükutla ATAR (087 dərsi). Sorğu LAQEYDDİR — bax qayda
            # başlığı.
            DuplicateFaceExceptionRule(profiles=repo("face_embeddings"))
        )

        # #15 AŞIM İZLƏYİCİSİ YEREL DƏYİŞƏNDİR, çünki İKİ yerdə lazımdır: həm
        # `Session.overtime` (HR-ın oxu yolu), həm də tabel təsdiqinin yan
        # təsiri (`daily_attendance`). İki nüsxə qursaydıq, eyni günün aşımı
        # iki fərqli obyektdən keçərdi və Root limitləri iki dəfə oxunardı —
        # nəticə eyni olsa da, "hansı nüsxə doğrudur" sualı sonradan çaşdırır
        # (`sales_points` ilə eyni əsaslandırma).
        overtime_tracking = OvertimeTrackingUseCase(
            overtime_log=repo("overtime_log"),
            worked_hours=repo("worked_hours"),
            limits=repo("limits"),
            notifier=notifier,
            clock=clock,
        )
        # TAPŞIRIQ MÜHƏRRİKİ YEREL DƏYİŞƏNDİR, çünki İKİ yerdə lazımdır: həm
        # `Session.tasks` (Tapşırıq Paneli), həm də #26 auditinin uğursuz
        # BLOKLAYICI bəndindən doğan avtomatik düzəliş tapşırığı (Struktur
        # Qərar B: yeni motor yazılmır, MÖVCUDU çağırılır). İki nüsxə
        # qursaydıq, avtomatik tapşırıq `TASK_ENGINE` toggle-ını və audit
        # yazısını AYRI obyektdən keçirərdi — nəticə eyni olsa da, "hansı
        # nüsxə doğrudur" sualı sonradan çaşdırır (`sales_points` və
        # `overtime_tracking` ilə eyni əsaslandırma).
        task_workflow = TaskWorkflowUseCase(
            tasks=repo("tasks"),
            audit=audit,
            clock=clock,
            notifier=notifier,
            toggles=repo("toggles"),
            # Faza 4.2 — öz-düzəliş tavanı Root-dan oxunsun: `limits=` olmadan
            # use case `DEFAULT_LIMITS`-ə düşər və Root dəyişikliyi ona ÇATMAZDı
            # (`overtime_tracking` ilə eyni qayda).
            limits=repo("limits"),
        )

        # İSTİFADƏÇİ İDARƏETMƏSİ YEREL DƏYİŞƏNDİR, çünki İKİ yerdə lazımdır:
        # həm `Session.users` (Users ekranı), həm də toplu CSV idxalının
        # sətir-sətir yazı yolu (`_bulk_create_employee_row` aşağıda). İkinci
        # nüsxə qursaydıq, eyni Dual-Control deadlock qoruyucusu İKİ AYRI
        # obyektdə yaşayardı (`sales_points`/`overtime_tracking` ilə eyni
        # əsaslandırma).
        # `v2backlog.md` Faza 3.3 — filiallar-arası daimi köçürmə sorğusu.
        # `ShiftSwapUseCase` ilə EYNİ FORMA (sorğu → HR_Admin təsdiqi), lakin
        # AYRI use case: `employees.store_id`-ni DƏYİŞDİRİR, növbə matrisinə
        # TOXUNMUR (bax `employee_transfer.py` modul başlığı).
        transfer_requests = TransferRequestUseCase(
            transfers=repo("employee_transfer_requests"),
            employees=uow.employees,
            audit=audit,
            clock=clock,
            notifier=notifier,
            # `limits`: tarixçə səhifə ölçüsü — `SHIFT_SWAP_HISTORY_PAGE_SIZE`
            # bölüşülür, `employee_transfer.py` YENİ açar YARATMIR (bax
            # `_history_page_size`).
            limits=repo("limits"),
        )

        # `v2backlog.md` Faza 5.3 — növbə təhvili qeydi. `MorningCheckInUseCase`-in
        # METODU DEYİL, ayrı use case (səbəb `shift_handoff.py` başlığında) —
        # lakin EYNİ `Session`-dadır ki, `[İşə Başladım]` ekranı ikisini bir
        # addımda ala bilsin.
        shift_handoffs = ShiftHandoffUseCase(
            handoffs=repo("shift_handoff_notes"),
            audit=audit,
            clock=clock,
            # `limits`: qeydin uzunluğu və görünmə pəncərəsi — İKİSİ DƏ Root
            # parametridir (migrations/100).
            limits=repo("limits"),
        )

        # `v2backlog.md` Faza 5.4 — break-glass fövqəladə giriş.
        # `vendor_reporter` İSTƏYƏ BAĞLIDIR: özünə-host quraşdırmada mərkəzi
        # vendor bazası olmaya bilər (`.env.example`-in `KOMPASOS_PRIVATE_
        # SERVER_DSN` naxışı). `None` olsa sətir YERLİ olaraq tam qalır və
        # `vendor_synced_at` NULL-da qalır — gecəlik iş onu sonsuz təkrar
        # cəhdlə yormasın deyə `retry_vendor_reports()` reporter yoxdursa
        # DƏRHAL 0 qaytarır (bax orada).
        break_glass = BreakGlassUseCase(
            grants=repo("break_glass"),
            employees=uow.employees,
            audit=audit,
            clock=clock,
            notifier=notifier,
            limits=repo("limits"),
            vendor_reporter=self._break_glass_reporter,
        )

        # `v2backlog.md` Faza 6.4 — kampaniya dövrləri (Root/CEO yazı yolu).
        campaign_periods = CampaignPeriodsUseCase(
            repository=repo("campaign_periods"),
            audit=audit,
            clock=clock,
        )

        # `v2backlog.md` Faza 3.4 — struktur offboarding checklist. HƏR İKİSİ
        # EYNİ `checklist_item_templates` repo-suna gedir — ad məkanı
        # `owner_type`/`owner_key` ilə ayrılır, TƏK cədvəl İKİ domenin
        # infrastrukturudur (bax `catalog_management.py` başlığı, migrations/088).
        # YUXARIDA QURULUR (`users`-dən ƏVVƏL) — `offboarding_checklists`
        # aşağıda `UserManagementUseCase`-in `OffboardingChecklistStarter`
        # portuna EYNİ instansiya kimi ötürülür (bax orada).
        checklist_templates = ChecklistItemTemplateUseCase(
            repository=repo("checklist_item_templates"),
            audit=audit,
            clock=clock,
        )
        offboarding_checklists = EmployeeOffboardingChecklistUseCase(
            checklists=repo("employee_offboarding_checklists"),
            templates=repo("checklist_item_templates"),
            audit=audit,
            clock=clock,
            notifier=notifier,
        )

        users = UserManagementUseCase(
            employees=uow.employees,
            credentials=uow.employees,
            audit=audit,
            clock=clock,
            camera_assignments=repo("camera_assignments"),
            # Rol dəyişikliyində anti-fraud override-larını süzmək üçün.
            flags=repo("permission_flags"),
            # PIN/şifrə sıfırlaması sahibinə bildiriş göndərir (bölmə 2).
            notifier=notifier,
            # Son Dual-Control təsdiqçisi itiriləndə xəbərdarlıq (bölmə 3).
            deadlock_guard=DualControlDeadlockGuardUseCase(
                uow.employees,
                notifier,
                # PRE-EXISTING boşluq (wiring qapısının tapıntısı, bugünkü
                # DEEP-GAP işindən DEYİL) — `security_events` BAĞLANMIRDI,
                # son dual-control təsdiqçisi itiriləndə təhlükəsizlik
                # hadisəsi jurnala düşmürdü. `notifier` ilə EYNİ "SEC-7,
                # QEYD-ŞƏRTSİZ yazılır" naxışıdır (bax use case-in öz
                # şərhi). SARILMIŞ forma MƏCBURİDİR — `face_verification`
                # ilə EYNİ qərar: yazı uğursuzluğu deadlock yoxlamasının
                # ÖZÜNÜ dayandırmamalıdır.
                security_events=FailSoftSecurityEventRecorder(repo("security_events")),
            ),
            # `facecontrol.md` bənd 8 — işçi deaktiv ediləndə üz vektoru HƏMİN
            # ANDA silinir. EYNİ `uow` bağlantısı MƏCBURİDİR: `is_active =
            # FALSE` yazısı ilə vektorun silinməsi bir tranzaksiyada olmalıdır,
            # əks halda biri commit olunub digəri geri qayıda bilərdi.
            face_embeddings=repo("face_embeddings"),
            # DEEP-GAP D2 — `PostgresOpenFineExposureReader` (`repositories.py`)
            # indi bağlanır: deaktiv edilən işçinin AÇIQ cərimə/etiraz izi
            # yoxlanılır (bölmə 4/6). `fines` İLƏ EYNİ `uow` bağlantısıdır.
            fine_exposure=repo("fine_exposure"),
            # HR-4 — işdən çıxma anında AÇIQ qalan bağlantılar (icazə, tapşırıq,
            # tutulmuş növbə, istifadə olunmamış məzuniyyət, sənəd, üz şablonu).
            # `fine_exposure` ilə EYNİ `uow` bağlantısı və EYNİ ön-yoxlama anı:
            # admin qərar verməzdən ƏVVƏL siyahını görür, sistem isə qərarı
            # BLOKLAMIR (bax `OffboardingReview` başlığı).
            offboarding_signals=repo("offboarding_signals"),
            # Faza 3.2 — retensiya müddətinin (`FORMER_EMPLOYEE_DATA_
            # RETENTION_MONTHS`) mənbəyi. BAĞLANMASAYDI `_retention_months()`
            # SÜKUTLA `DEFAULT_LIMITS`-ə düşürdü — Root bu müddəti dəyişsə
            # belə, `anonymize_former_employees` HƏMİŞƏ defolt dəyərlə
            # işləyərdi.
            limits=repo("limits"),
            # Faza 3.5 — `SalesPointsUseCase.award_referral_bonus` `Referral
            # BonusAwarder`-i strukturla ÖDƏYİR (ayrı adapter LAZIM DEYİL).
            # `sales_points` YUXARIDA yerli dəyişən kimi qurulub. BAĞLANMASAYDI
            # `create_employee` `referred_by_employee_id`-ni YENƏ YAZARDI,
            # LAKİN bonus SÜKUTLA verilməzdi — tövsiyə tarixi qeydə düşür,
            # mükafat isə itir, ikisi arasındakı uyğunsuzluq görünməz qalardı.
            referral_bonus=sales_points,
            # Faza 3.4 — YUXARIDA qurulan `offboarding_checklists` İLƏ EYNİ
            # instansiya (`OffboardingChecklistStarter`-i `start_checklist()`
            # strukturla ödəyir). BAĞLANMASAYDI `deactivate_employee`/
            # `deactivate_scheduled_employees` checklist-i SÜKUTLA
            # BAŞLATMAZDI — işçi deaktiv olunardı, avadanlıq-qaytarma/son-
            # hesablaşma bəndləri isə heç vaxt yaranmazdı.
            offboarding_checklists=offboarding_checklists,
            # Faza 3.1/3.2 — `infra` hər iki oxucunu MÖVCUD `Postgres
            # EmployeeRepository`-yə əlavə etdi (yeni sinif/repo açarı YOX,
            # `employees` strukturla ÖDƏYİR: `list_due_for_scheduled_
            # deactivation`/`list_pending_anonymization`). BAĞLANMAMIŞDAN
            # ƏVVƏL: `deactivate_scheduled_employees`/`anonymize_former_
            # employees` HƏR GECƏ CRON-dan (`_register_scheduled_jobs`)
            # çağırılırdı, LAKİN `None` oxuyucu ilə HƏMİŞƏ 0 qaytarırdı —
            # çökmürdü, sadəcə heç nə etmirdi.
            scheduled_deactivation_reader=repo("employees"),
            retention_candidate_reader=repo("employees"),
        )

        def _bulk_create_employee_row(
            *,
            tenant_id: TenantId,
            actor: Employee,
            employee_id: EmployeeId,
            draft: EmployeeDraft,
            initial_password: str,
        ) -> Employee:
            """Toplu CSV idxalının SƏTİR-SƏTİR yazı yolu (#29).

            HƏR ÇAĞIRIŞ ÖZ TRANZAKSİYASINDADIR (bax `bulk_operations.py`
            başlığı, "TRANZAKSİYA SƏRHƏDİ"): uğurlu sətir DƏRHAL commit
            olunur, ona görə növbəti sətrin uğursuzluğu ONU geri qaytarmır
            (QİSMƏN İDXAL). Uğursuz sətirdə tranzaksiya ROLLBACK edilir ki,
            `uow` TƏMİZ vəziyyətdə növbəti sətrə keçsin — əks halda
            PostgreSQL-in "aborted transaction" vəziyyəti QALAN BÜTÜN
            sətirləri də uğursuz edərdi.
            """
            try:
                created = users.create_employee(
                    tenant_id=tenant_id,
                    actor=actor,
                    employee_id=employee_id,
                    draft=draft,
                    initial_password=initial_password,
                )
            except Exception:
                uow.rollback()
                raise
            uow.commit()
            return created

        bulk_employee_import = BulkEmployeeImportUseCase(
            employees=uow.employees,
            positions=uow.positions,
            stores=repo("stores"),
            create_employee_row=_bulk_create_employee_row,
            # `HashingService` `application/use_cases/authentication.py`-də
            # DƏ birbaşa idxal olunur (təkrar YOX) — müvəqqəti şifrə
            # generasiyası üçün. `session_limits`: eyni `InfrastructureLimits`
            # örtüyü `kiosk.py`/`app.py`-dakı giriş axınının işlətdiyi ilə
            # EYNİDİR (şifrə siyasəti bir yerdə dəyişir).
            hashing=HashingService(limits=session_limits),
            bulk_log=repo("bulk_import_log"),
            audit=audit,
            clock=clock,
            # `BULK_IMPORT_MAX_ROWS` / `BULK_IMPORT_PREVIEW_ERROR_LIMIT` —
            # Root-dan idarə olunur (seed: migrations/041).
            limits=repo("limits"),
        )

        return Session(
            uow=uow,
            tenant_id=self._tenant_id,
            leave_verification=LeaveVerificationUseCase(
                leave_requests=uow.leave_requests,
                fines=uow.fines,
                employees=uow.employees,
                leave_types=repo("leave_types"),
                camera_assignments=repo("camera_assignments"),
                # Nahar/Çay sayğacı (nahar.md) — `uow`-un EYNİ bağlantısından
                # gəlir: STEP1-in sorğu yazısı ilə sayğac artımı bir
                # tranzaksiyada olmalıdır (bax `connection.py`-dakı qeyd).
                break_usage=repo("break_usage"),
                clock=clock,
                ntp=ntp,
                limits=repo("limits"),
                toggles=repo("toggles"),
                # `SagaOrchestrator()` ƏVVƏL SIFIR arqumentlə qurulurdu (D6):
                # hər sessiyada TƏZƏ boş `InMemorySagaStateRepository` yaranır
                # və uzlaşma gözləyən əməliyyatın izi `with` bloku bitən kimi
                # İTİRDİ — `PENDING_RECONCILIATION` vəziyyəti heç vaxt
                # bərpa oluna bilmirdi. `state_repository=repo("saga_state")`
                # (infra, `PostgresSagaStateRepository`) izi DAVAMLI saxlayır.
                # `event_bus=get_event_bus()` D2-də ARTIQ eyni blokda idxal
                # olunub (yuxarı bax) — QLOBAL bus, İKİNCİ instans YOX.
                #
                # `policy_resolver=policy_for` (D9): `main.py::build_container`
                # EYNİ funksiyanı bağlayır (özü sənədləşdirir: "kompozisiya
                # kökündə" verilməlidir). Bağlamasaydıq GUI yolu HƏMİŞƏ ən
                # sərt defolt siyasəti (`ON_ANY_FAILURE`) işlədərdi və
                # `saga_policies` reyestri GUI üçün ÖLÜ KOD qalardı — eyni
                # saga CLI-dan icra olunanda BAŞQA, GUI-dən icra olunanda
                # BAŞQA siyasətlə davranardı. CLI/GUI eyni əməliyyatı EYNİ
                # qaydalarla idarə etməlidir (D3-lə eyni sinif: mexanizm
                # mövcuddur, bağlanmayıbsa "səbəbsiz fərq" yaranır).
                saga=SagaOrchestrator(
                    event_bus=get_event_bus(),
                    state_repository=repo("saga_state"),
                    policy_resolver=policy_for,
                ),
                audit=audit,
                notifier=notifier,
                # `LeaveVerifiedEvent` (D2) — QLOBAL `get_event_bus()` bağlanır,
                # BURADA YENİ instans QURULMUR: `main.py`-dakı universal audit
                # dinləyicisi (sətir ~108) `main.py:71`-in ÖZ bağladığı bus-a
                # abunədir. Ayrı `EventBus()` qursaydıq, GUI-nin yaydığı hadisə
                # CLI-nin dinləyicisinə heç vaxt çatmazdı — iki İZOLƏ olunmuş
                # bus mövcud olardı və düzəlişin bütün mənası itərdi.
                # YALNIZ `LeaveVerificationUseCase`: qalan use case-lərdə
                # dinləyici YOXDUR (`_drain()` qərarı, CLAUDE.md naxışı) —
                # onlara bus bağlamaq sənədləşdirilmiş qərarı pozardı.
                event_bus=get_event_bus(),
            ),
            morning_check_in=MorningCheckInUseCase(
                attendance=uow.attendance,
                shifts=repo("shifts"),
                employees=uow.employees,
                camera_assignments=repo("camera_assignments"),
                clock=clock,
                ntp=ntp,
                limits=repo("limits"),
                toggles=repo("toggles"),
                audit=audit,
                notifier=notifier,
            ),
            shift_planning=planning,
            shift_swaps=ShiftSwapUseCase(
                swaps=repo("shift_swaps"),
                planning=planning,
                toggles=repo("toggles"),
                audit=audit,
                clock=clock,
                notifier=notifier,
                # `SHIFT_SWAP_MAX_LEAD_DAYS` — dəyişmə sorğusunun neçə gün
                # əvvəldən verilə biləcəyi. Port ötürülmədən açar ROOT ekranında
                # görünür, lakin modul fallback-ı işləməyə davam edərdi.
                limits=repo("limits"),
            ),
            open_shifts=OpenShiftMarketUseCase(
                postings=repo("open_shifts"),
                # EYNİ `planning` obyekti: elan tutulanda təqvim məhz Shift
                # Matrix-in yazma funksiyası ilə yenilənir (bölmə 3 "məntiq
                # təkrarlanmır"), ikinci bir yazma yolu YARANMIR.
                planning=planning,
                # Uyğunluq yoxlaması üçün YALNIZ oxu: işçinin həmin gün artıq
                # iş növbəsi varmı.
                shifts=repo("shifts"),
                limits=repo("limits"),
                toggles=repo("toggles"),
                audit=audit,
                clock=clock,
                notifier=notifier,
            ),
            daily_attendance=DailyAttendanceSheetUseCase(
                sheets=repo("sheets"),
                facts=repo("attendance_facts"),
                audit=audit,
                clock=clock,
                notifier=notifier,
                # #15 — təsdiqdən sonra norma üstü saatlar jurnala yazılır.
                # Tabelin öz axını (ön-doldurma → müqayisə → təsdiq) DƏYİŞMİR.
                overtime=overtime_tracking,
                # DEEP-GAP D1 — bu port BAĞLANMAMIŞDI: `ANNUAL_LEAVE_COUNTS_
                # AS_WORKED_DAY` Root parametri istehsalatda TƏSİRSİZ qalırdı,
                # `_counting_policy()` həmişə `AttendanceCountingPolicy.
                # defaults()`-a düşürdü (bax use case-in öz şərhi).
                limits=repo("limits"),
            ),
            manual_fines=ManualFineUseCase(
                fines=uow.fines,
                fine_types=repo("fine_types"),
                camera_assignments=repo("camera_assignments"),
                limits=repo("limits"),
                toggles=repo("toggles"),
                audit=audit,
                clock=clock,
                notifier=notifier,
            ),
            fine_appeals=FineAppealUseCase(
                appeals=repo("appeals"),
                fines=uow.fines,
                audit=audit,
                clock=clock,
                notifier=notifier,
                # İşçi tarixçəsinin səhifə ölçüsü Root parametridir
                # (`FINE_APPEAL_HISTORY_PAGE_SIZE`, migrations/060) — əvvəl
                # repozitoriya defoltunda gizlənmişdi.
                limits=repo("limits"),
            ),
            # REPOSITORY ARQUMENTİ YOXDUR VƏ BU, QƏSDƏNDİR: `publish_batch`
            # cərimələri YADDAŞDA (`dict[FineId, Fine]`) alır və mutasiya edir,
            # yazma isə ÇAĞIRANA aiddir (bax `controllers/fine_review.py`).
            # Beləliklə bütün dəst TƏK `commit()`-də yazılır — "bir anda
            # görünür" tələbi (use case başlığı) məhz bu yolla texniki
            # zəmanətə çevrilir.
            #
            # `limits` MƏCBURİDİR (use case-in öz şərhi): etiraz pəncərəsi
            # nəşr anında DONDURULUR və sonradan düzəldilə bilmir.
            fine_review=MonthlyFineReviewUseCase(
                clock=clock,
                audit=audit,
                notifier=notifier,
                limits=repo("limits"),
                # SEC-8 — "bu cərimə hansı partiyada nəşr olundu?" sualının
                # TƏK mənbəyi (`monthly_fine_review_batches`, `Fine`-in
                # ÜSTÜNDƏ yaşamır, bax use case başlığı). Açar `infra` ilə
                # ƏVVƏLCƏDƏN razılaşdırılıb (`team-lead`) — repo hələ
                # YAZILMAYIBSA `mypy`/işə salınma xətası GÖZLƏNİLƏNDİR, bu
                # sətir öz tərəfini artıq TAMAMLAYIB.
                review_batches=repo("fine_review_batches"),
                # DEEP-GAP D2 — bu port ƏVVƏL BAĞLANMAMIŞDI, yəni deaktiv
                # işçinin cəriməsi `_is_employee_inactive()`-in yoxlamasından
                # KEÇMƏDƏN nəşr olunurdu (istehsalatda qapı SÖNÜK idi, halbuki
                # use case-in ÖZÜ artıq yazılmışdı). `PostgresEmployeeRepository.
                # get()` MÖVCUDDUR, ona görə bura TƏHLÜKƏSİZ bağlanır.
                employees=repo("employees"),
                # DEEP-GAP T3 — indi bağlıdır: `PostgresFineRepository.
                # unsynced_evidence_ids()` yazıldı (`repositories.py`, TƏK
                # `id = ANY(%s)` sorğusu, `evidence_upload_status` sütunu).
                # Kamera cərimələrinin nəşri artıq sübutun HƏQİQƏTƏN Drive-a
                # yükləndiyini yoxlayır (SEC-8).
                evidence_sync=repo("fines"),
            ),
            tasks=task_workflow,
            sales_points=sales_points,
            # `limits`: Faza 7 — `[Xüsusi Aralıq]` seçiminin maksimum uzunluğu
            # (`REPORT_RANGE_MAX_DAYS`) və norma saatın hüquqi tavanı
            # (`OVERTIME_DAILY_NORM_HOURS`) ROOT-dandır. Port ötürülməsəydi,
            # parametr ROOT ekranında görünər, lakin TƏSİRSİZ qalardı
            # (`test_root_control_parameter_parity` bu boşluğu qapıya çevirib).
            reports=MonthlyReportUseCase(limits=repo("limits")),
            # kompas1.md Faza 8 — export təcrübəsi. `reports` ilə YAN-YANA
            # dayanır, lakin ONU ƏVƏZ ETMİR: sətirləri yenə `reports` hesablayır,
            # bu use case yalnız onların üzərində doğrulama/düzəliş/müqayisə
            # aparır (bax `export_preflight.py` başlığı).
            #
            # `limits`: dörd ROOT parametri (anomaliya faizi, minimum işçi sayı,
            # əhəmiyyətli fərq həddi, səbəbin minimum uzunluğu) — seed:
            # migrations/044.
            export_preflight=ExportPreflightUseCase(
                corrections=repo("export_corrections"),
                roster=repo("export_roster"),
                audit=audit,
                clock=clock,
                limits=repo("limits"),
            ),
            # --- Face Control (facecontrol.md Faza 2 + Faza 3) ---------------
            #
            # `face_engine` TƏNBƏL proxy-dir və hər üç use case-ə EYNİ nüsxə
            # ötürülür (bax `_LazyFaceEngine` + `ApplicationContext.
            # face_engine`): kamera fiziki cihazdır, ikinci tutacaq onu
            # bloklayardı.
            face_enrollment=face_enrollment,
            # Yenidən-qeydiyyat qeydiyyat use case-inin ÖZÜNÜ alır, onun
            # məntiqini TƏKRARLAMIR (bax `FaceReEnrollmentUseCase` başlığı):
            # kadr çəkilişi/keyfiyyət süzgəci/orta vektor TƏK yerdə qalmalıdır.
            face_re_enrollment=FaceReEnrollmentUseCase(
                enrollment=face_enrollment,
                profiles=repo("face_embeddings"),
                audit=audit,
                clock=clock,
            ),
            # `toggles`: üz qapısı MÖVCUD `CAMERA_VERIFICATION` moduluna
            # tabedir (yeni qlobal açar YARADILMADI — səbəbi use case-in
            # "MODUL QAPISI" şərhindədir). `store_scope`: bənd 15-in pilot
            # süzgəci; BOŞ cədvəl = qlobal davranış, yəni indiki vəziyyət.
            face_verification=FaceVerificationUseCase(
                profiles=repo("face_embeddings"),
                verification_log=repo("face_verification_log"),
                exemptions=repo("face_exemptions"),
                store_scope=repo("face_store_scope"),
                camera=face_engine,
                matcher=face_engine,
                # `limits`: bənzərlik həddi, aşağı-etibar həddi, MISMATCH
                # kilid həddi, liveness kataloqu və bənd 18-in vaxt həddi —
                # beşi də ROOT parametridir (seed: migrations/047).
                limits=repo("limits"),
                toggles=repo("toggles"),
                audit=audit,
                clock=clock,
                notifier=notifier,
                # SEC-7 — SARILMIŞ forma MƏCBURİDİR (bax `app.py::
                # _SessionScopedLogin.login` eyni şərhi): üz doğrulaması
                # kamera-tipli sətirdə çalışır, `security_events` yazısının
                # uğursuzluğu doğrulamanın ÖZÜNÜ dayandırmamalıdır.
                security_events=FailSoftSecurityEventRecorder(repo("security_events")),
                # T1 (DEEP-GAP Faza 4) — `identify_for_login()` (1:N kiosk üz
                # girişi) HEÇ BİR sürət-limitinə bağlı deyildi (bax use case-in
                # "T1 — TERMİNAL THROTTLE" bölməsi): foto/video ilə limitsiz
                # cəhd mümkün idi. XAM repo, SARILMIR — `authenticate_with_pin`
                # (`controllers/kiosk.py`) ilə EYNİ SEC-01 qərarı: bu, TƏHLÜKƏ­
                # SİZLİK QAPISININ ÖZÜDÜR, fail-soft bükücü onu sükutla
                # söndürərdi.
                pin_throttle=repo("pin_throttle"),
                # AF-2 — 1:N ÜZ SAYĞACI PIN SAYĞACINDAN AYRILDI. Ortaq sayğac
                # zamanı kameraya baxan kənar şəxs bütün mağazanın PIN girişini
                # dayandıra bilirdi (xidmətdən imtina): 1:N-də cəhd edən şəxs
                # heç bir kimlik təqdim etmir, yəni «eyni terminalda eyni adam»
                # fərziyyəsi yoxdur. Hədd DƏYİŞMİR — hər iki kanal EYNİ
                # `KIOSK_STORE_PIN_*` açarlarını oxuyur (miqrasiya 086).
                # `pin_throttle` ilə eyni qərar: XAM repo, fail-soft SARILMIR.
                face_throttle=repo("face_throttle"),
            ),
            # `limits=repo("limits")` — AÇIQ BAĞLANTININ repo-su: istisnanın
            # maksimum müddəti (`FACE_EXEMPTION_MAX_DAYS`) sətrin yazıldığı
            # tranzaksiyada oxunmalıdır. İkinci bağlantı Root-un həmin an
            # dəyişdirdiyi dəyəri fərqli görə bilərdi.
            face_exemptions=FaceControlExemptionUseCase(
                exemptions=repo("face_exemptions"),
                limits=repo("limits"),
                # SEC-020: istisna YALNIZ kompensasiya edici nəzarət (dual-control)
                # açıq olduqda verilə/uzadıla bilər — bənd 14-ün şərti.
                toggles=repo("toggles"),
                audit=audit,
                clock=clock,
                notifier=notifier,
            ),
            # `profiles` EYNİ bağlantıdandır: sayğac/kilid sütunları
            # `employees` sətrindədir və açılış həmin tranzaksiyada
            # görünməlidir. `limits` isə yalnız `FACE_REENROLLMENT_REMINDER_
            # MONTHS` üçündür — "yenidən qeydiyyat tövsiyə olunurmu?" sualı
            # kilidin özünə deyil, onun SƏBƏBİNƏ aiddir (bənd 13).
            face_lock_release=FaceLockReleaseUseCase(
                profiles=repo("face_embeddings"),
                limits=repo("limits"),
                audit=audit,
                clock=clock,
                notifier=notifier,
            ),
            face_log_retention=FaceVerificationLogRetentionUseCase(
                verification_log=repo("face_verification_log"),
                # `FACE_VERIFICATION_LOG_RETENTION_MONTHS` — hüquqi tələb
                # yurisdiksiyaya görə dəyişir, ona görə Root-dan idarə olunur.
                limits=repo("limits"),
                audit=audit,
                clock=clock,
            ),
            # SEC-011/SEC-5 — `"auth_sessions"` açarı `infra`-nın
            # `PostgresAuthSessionRepository`-sidir (`connection.py`).
            # `limits` MÜDDƏTLƏRİN ÖZÜNÜ (`ADMIN_PANEL_SESSION_IDLE_TIMEOUT_
            # MINUTES` və s.) `system_limits`-dən oxuyur — `app.py`-dakı
            # `SessionGuard` YERLİ taymerləri ÜÇÜN eyni açarları AYRICA oxuyur
            # (bax `app.py::_admin_panel_idle_timeout_minutes`), çünki client
            # məcburi çıxışı server dəstəyi OLMADAN da işləməlidir.
            sessions=SessionManagementUseCase(
                sessions=repo("auth_sessions"),
                clock=clock,
                limits=repo("limits"),
                audit=audit,
            ),
            audit_query=AuditQueryUseCase(
                reader=repo("audit_reader"),
                audit=audit,
                clock=clock,
                # Səhifə ölçüsü (`AUDIT_LOG_DEFAULT/MAX_PAGE_SIZE`) Root-dandır:
                # audit cədvəli ən sürətli böyüyən cədvəldir və hansı sayın
                # şəbəkəyə/GUI-yə uyğun olduğu quraşdırmadan asılıdır.
                limits=repo("limits"),
            ),
            # `users` YUXARIDA yerli dəyişən kimi qurulub — bax orada
            # ("İKİ yerdə lazımdır", toplu CSV idxalı ilə paylaşılır).
            users=users,
            # `transfer_requests`/`checklist_templates`/`offboarding_
            # checklists` YUXARIDA yerli dəyişən kimi qurulub (Faza 3.3/3.4,
            # bax orada) — üçü də `users`-dən HƏMİN blokun içindəcə qurulur.
            transfer_requests=transfer_requests,
            checklist_templates=checklist_templates,
            offboarding_checklists=offboarding_checklists,
            # Faza 5.3/5.4 — YUXARIDA qurulub (bax orada).
            shift_handoffs=shift_handoffs,
            break_glass=break_glass,
            campaign_periods=campaign_periods,
            permission_guard=PermissionHierarchyGuardUseCase(
                audit=audit,
                clock=clock,
                # PRE-EXISTING boşluq (wiring qapısının tapıntısı, bugünkü
                # DEEP-GAP işindən DEYİL) — `security_events` BAĞLANMIRDI:
                # `apply()`-in `AuthorizationError` atdığı hər hal (kiminsə
                # öz səlahiyyətindən yuxarı toxunma cəhdi, Strict Hierarchy/
                # Self-Escalation Guard rəddi) təhlükəsizlik hadisəsi
                # jurnalına DÜŞMÜRDÜ. SARILMIŞ forma MƏCBURİDİR — `face_
                # verification`/`deadlock_guard` ilə EYNİ SEC-7 qərarı: yazı
                # uğursuzluğu icazə rəddinin ÖZÜNÜ dayandırmamalıdır.
                security_events=FailSoftSecurityEventRecorder(repo("security_events")),
            ),
            positions=PositionManagementUseCase(
                positions=uow.positions,
                flags=repo("permission_flags"),
                audit=audit,
                clock=clock,
            ),
            support=SupportChatUseCase(
                tickets=repo("support"),
                toggles=repo("toggles"),
                clock=clock,
                # `SUPPORT_THREAD_PAGE_SIZE` — mesaj lentinin uzunluğu.
                limits=repo("limits"),
                telegram=telegram_gateway,
            ),
            support_inbox=SupportInboxUseCase(
                tickets=repo("support"),
                toggles=repo("toggles"),
                clock=clock,
                audit=audit,
                limits=repo("limits"),
                telegram=telegram_gateway,
                # «Gözləmədə» xatırlatması işçiyə TƏTBİQ-DAXİLİ bildirişlə
                # gedir (tg1.md Faza 6): e-poçt məcburi deyil, çünki işçinin
                # e-poçtu boş ola bilər (`.env.example`: yalnız bildiriş üçün).
                notifier=notifier,
            ),
            telegram_config=TelegramConfigUseCase(
                repository=repo("telegram_config"),
                audit=audit,
                clock=clock,
                probe=telegram_gateway,
            ),
            sync_conflicts=SyncConflictUseCase(
                repository=repo("sync_conflicts"),
                audit=audit,
                clock=clock,
                # `SYNC_CONFLICT_PAGE_SIZE` — konflikt növbəsinin səhifəsi.
                limits=repo("limits"),
            ),
            branding=TenantBrandingUseCase(
                repository=repo("branding"),
                audit=audit,
                clock=clock,
            ),
            devices=DeviceRegistryUseCase(
                devices=repo("devices"),
                # Aktiv mağaza siyahısı YALNIZ avtomatik təsdiq üçün lazımdır
                # (`DEVICE_APPROVAL_REQUIRED = 0` + tək mağaza şərti) —
                # bax `device_registry.py` başlığı.
                stores=repo("active_stores"),
                audit=audit,
                clock=clock,
                # `MAX_REGISTERED_DEVICES`, `DEVICE_APPROVAL_REQUIRED`,
                # `DEVICE_INACTIVITY_DAYS`.
                limits=repo("limits"),
                notifier=notifier,
            ),
            setup=FirstRunSetupUseCase(
                employees=uow.employees,
                positions=uow.positions,
                stores=repo("stores"),
                audit=audit,
                clock=clock,
                # `SETUP_RECOMMENDED_ADMIN_COUNT` — sihirbazın "neçə admin
                # tövsiyə olunur" xəbərdarlığı. Sihirbaz ƏN ERKƏN axındır,
                # lakin BURADA bağlantı artıq var (sessiya açılıb), ona görə
                # port ötürülür; bağlantısız yol (`limits=None`) use case-in
                # öz defoltu kimi qalır — bax `first_run_setup.py` başlığı.
                limits=repo("limits"),
                # Özünə-host edilən quraşdırmada `license_tenants` sətrini
                # sihirbaz yaradır (bax `first_run_setup.TenantProvisioning`).
                # Lisenziyalı quraşdırmada port ötürülür, lakin ÇAĞIRILMIR —
                # qərar `complete(provision_tenant=…)` bayrağındadır.
                provisioning=repo("tenant_provisioning"),
            ),
            root_control=RootControlUseCase(
                limits=repo("limits"),
                toggles=repo("toggles"),
                flags=repo("permission_flags"),
                # SEC-020: `DUAL_CONTROL` aktiv üz-təsdiqi istisnalarının yeganə
                # kompensasiya edici nəzarətidir — söndürmə cəhdi həmin siyahını
                # oxumadan qərar verə bilməz. EYNİ bağlantıdan gəlir ki, Root
                # düyməni basdığı anda mövcud olan sətirlər görünsün.
                face_exemptions=repo("face_exemptions"),
                audit=audit,
                clock=clock,
            ),
            # ---------------- Faza 5/6 ekranlarının arxası ------------------ #
            #
            # ÜÇ KATALOQ, ÜÇ AYRI USE CASE: hər biri öz flag-ını yoxlayır
            # (`can_manage_work_modes` / `_fine_types` / `_leave_types`) və
            # onları bir sinifdə birləşdirmək HR-a cərimə qiymətini dəyişmək
            # imkanı verərdi (bax `catalog_management.py` başlığı).
            work_modes=WorkModeCatalogUseCase(
                repository=repo("work_modes"),
                audit=audit,
                clock=clock,
            ),
            fine_types=FineTypeCatalogUseCase(
                repository=repo("fine_types"),
                audit=audit,
                clock=clock,
            ),
            leave_types=LeaveTypeCatalogUseCase(
                repository=repo("leave_types"),
                audit=audit,
                clock=clock,
            ),
            backups=BackupAccessUseCase(
                catalog=repo("backup_records"),
                # `NightlyBackupService` gecə planlayıcısının da işlətdiyi
                # SİNİFdir — `BackupAccessUseCase` yalnız onun üzərinə
                # `can_manage_backups` qapısını qoyur (bax use case başlığı).
                # `limits`: saxlama müddəti və `pg_dump` taymautu Root-dan.
                operations=NightlyBackupService(self._database, limits=session_limits),
                audit=audit,
                clock=clock,
                # İKİ AYRI PƏNCƏRƏ, QƏSDƏN: `operations` xidməti `Database`
                # alır və öz iş vahidini açır, ona görə ona `session_limits`
                # (sessiya ömürlü örtük) gedir; use case-in ÖZÜ isə domen
                # portunu (`SystemLimits`) gözləyir və AÇIQ bağlantının
                # repo-sundan oxuyur — `BACKUP_HISTORY_PAGE_SIZE` məhz burada
                # işlənir. Birini digərinin yerinə vermək tip səhvi olardı.
                limits=repo("limits"),
            ),
            plugins=PluginManagementUseCase(
                registry=repo("plugins"),
                # Etibar reyestri BOŞ ola bilər — o zaman heç bir plugin
                # quraşdırılmır (fail-closed, bax `trust_store_from_env`).
                verifier=PluginSignatureVerifier(trust_store_from_env()),
                audit=audit,
                clock=clock,
            ),
            dashboard_layout=DashboardLayoutUseCase(
                store=repo("preferences"),
                clock=clock,
                toggles=repo("toggles"),
                # `limits`: şəbəkənin sütun sayı (`DASHBOARD_GRID_COLUMNS`) —
                # ROOT parametridir (audit G-5, migrations/054).
                limits=repo("limits"),
                # Plugin-lərin verdiyi panel bölmələri (audit G-3). Səth
                # TƏNBƏLDİR: `plugins` cədvəli yalnız Panel Qurucusu açılanda
                # oxunur, hər sessiya qurulanda yox.
                plugin_widgets=PluginRegistrySurface(repo("plugins"), self._tenant_id),
            ),
            db_switch=DatabaseSwitchUseCase(
                read_only=repo("read_only"),
                buffer=self.offline_drain(),
                migrator=self.migrator(),
                events=repo("migration_events"),
                audit=audit,
                clock=clock,
                notifier=notifier,
            ),
            sales_review=SalesReviewQueueUseCase(
                repository=PostgresSalesReviewRepository(self._database, self._tenant_id),
                points=sales_points,
                audit=audit,
                clock=clock,
                # `SALES_REVIEW_QUEUE_PAGE_SIZE` — şübhəli satış növbəsinin
                # səhifəsi. `repository` öz iş vahidini açsa da, limit oxusu
                # AÇIQ bağlantıdan gedir: səhifə ölçüsü ekranın parametridir,
                # növbənin deyil.
                limits=repo("limits"),
            ),
            # Profil ekranı YALNIZ `Clock` alır: o, məlumat OXUMUR, verilmiş
            # profilə kimin baxa biləcəyini həll edir (bax use case başlığı).
            employee_profile=EmployeeProfileAccessUseCase(clock=clock),
            erp_connections=ErpConnectionWizardUseCase(
                servers=erp_servers,
                # `limits`: 1C sorğusunun taymautu və təkrar cəhd sayı Root-dan
                # gəlir — fabrik onu qurduğu HƏR `OneCConnector`-a ötürür.
                connectors=OneCConnectorFactory(erp_servers.credentials_for, limits=session_limits),
                audit=audit,
                mappings=PostgresStoreServerMappingRepository(self._database, self._tenant_id),
                # `limits`: fayl-mübadiləsi serverinin defolt sinxronizasiya
                # dövrü ROOT-dandır (`ERP_FILE_EXCHANGE_SYNC_INTERVAL_SECONDS`).
                # Port ötürülməsəydi parametr ROOT ekranında görünər, lakin
                # yeni serverə TƏSİR ETMƏZDİ — səssiz uğursuzluq.
                limits=repo("limits"),
            ),
            # Sihirbazın redaktə axını üçün EYNİ repo obyekti (bax `Session`
            # sahəsindəki izah) — ikinci nüsxə qurmaq eyni serverin iki fərqli
            # şifrələmə kontekstinə düşməsi riski demək olardı.
            erp_server_configs=erp_servers,
            # REYESTR HƏR SESSİYADA YENİDƏN QURULUR — qəsdən: use case-lər
            # bağlantıya bağlıdır və sessiyadan uzun yaşamır (bax bu faylın
            # başlığı). Qaydanın özü isə vəziyyətsizdir; onu qlobal saxlamaq
            # sessiyalar arasında paylaşılan dəyişkən vəziyyət yaradardı.
            exceptions=exception_engine,
            # #7 POS Səlahiyyət Siyasəti (sənədləşdirmə, Faza 4) — audit EYNİ
            # tranzaksiyada, çünki yazı və audit sətri birlikdə commit olmalıdır.
            pos_threshold=POSThresholdUseCase(
                thresholds=repo("pos_thresholds"),
                limits=repo("limits"),
                audit=audit,
                clock=clock,
            ),
            # #17 İşçi Sənədləri (Faza 7) — audit EYNİ tranzaksiyada.
            # `notify_expiring_documents` gecəlik iş üçün ELƏCƏ DƏ əlçatandır
            # (`behavior_baselines`/`overtime` ilə eyni naxış, yuxarı bax).
            # İnstansiya YUXARIDA, `face_enrollment`-dən ƏVVƏL qurulub (bax
            # həmin bloku) — EYNİ obyekt `consent_documents` portuna da gedir.
            employee_documents=employee_documents,
            # #19 Elan (Broadcast, Faza 8) — `Notifier` QƏSDƏN ÖTÜRÜLMÜR (bax
            # use case başlığı: çatdırılma store-scoping sorğusu ÜZƏRİNDƏN
            # gedir, `notifications` cədvəlinin mağaza süzgəci yoxdur).
            announcements=AnnouncementUseCase(
                announcements=repo("announcements"),
                limits=repo("limits"),
                audit=audit,
                clock=clock,
            ),
            # #20 Performans Qiymətləndirməsi (Faza 8) — audit EYNİ
            # tranzaksiyada (CLAUDE.md §5), bildiriş işçiyə ŞƏXSİ sətirlədir.
            performance_reviews=PerformanceReviewUseCase(
                reviews=repo("performance_reviews"),
                employees=repo("employees"),
                limits=repo("limits"),
                audit=audit,
                clock=clock,
                notifier=notifier,
            ),
            # #8 İşçi Davranış Baz Xətti (Faza 5) — gecəlik yenidən-hesablama.
            # Eyni iki repo-nu (`behavior_baselines`, `checkin_history`)
            # `BehaviorAnomalyRule` ilə PAYLAŞIR — hər ikisi EYNİ tranzaksiyada
            # olduğu üçün hesablama və qaydanın gördüyü məlumat UYĞUNDUR.
            behavior_baselines=BehaviorBaselineUseCase(
                checkins=repo("checkin_history"),
                baselines=repo("behavior_baselines"),
                limits=repo("limits"),
                clock=clock,
            ),
            # #13 Tarixi-nümunə kadr təklifi (Faza 6) — 1C-yə TOXUNMUR.
            # `planning` ilə eyni sessiyada qurulur, lakin BİR-BİRİNƏ
            # BAĞLANMIR: təklif heç vaxt təyinat yaratmır (kompasos11.md #13).
            staffing_pattern=StaffingPatternUseCase(
                history=repo("staffing_history"),
                suggestions=repo("staffing_patterns"),
                limits=repo("limits"),
                clock=clock,
            ),
            # #15 Norma üstü iş saatları (Faza 6) — `daily_attendance` ilə EYNİ
            # nüsxə (yuxarıdakı yerli dəyişən), yəni təsdiqin yazdığı sətirlə
            # hesabatın oxuduğu sətir eyni tranzaksiyadan görünür.
            overtime=overtime_tracking,
            # #21 İşdən Çıxma Riski Balı (Faza 9) — `attrition_signals`/
            # `attrition_scores` EYNİ obyektdir (bax `connection.py`-dakı
            # `PostgresAttritionRepository` qeydiyyatı), yəni gecəlik iş
            # oxuduğu siqnalla yazdığı nəticəni EYNİ tranzaksiyada görür.
            attrition_risk=AttritionRiskUseCase(
                signals=repo("attrition_signals"),
                scores=repo("attrition_scores"),
                employees=repo("employees"),
                limits=repo("limits"),
                audit=audit,
                clock=clock,
                notifier=notifier,
            ),
            # #24 Çox-Mağaza Benchmark Dashboard (Faza 9A) — YALNIZ-OXU, bax
            # use case modul başlığı.
            multi_store_benchmark=MultiStoreBenchmarkUseCase(
                provider=repo("multi_store_benchmark"),
                limits=repo("limits"),
                clock=clock,
            ),
            # #26+#27 Sahə hesabatları (kompas1.md Faza 3) — VAHİD nüvə.
            # `tasks=task_workflow`: MÖVCUD Tapşırıq Mühərriki ötürülür (yerli
            # dəyişən, yuxarı bax) — audit EYNİ tranzaksiyada, `TASK_ENGINE`
            # toggle-ı EYNİ obyektdən oxunur.
            field_reports=FieldReportUseCase(
                reports=repo("field_reports"),
                catalog=repo("field_report_catalog"),
                tasks=task_workflow,
                limits=repo("limits"),
                audit=audit,
                clock=clock,
                notifier=notifier,
                # Faza 4.1 — gündəlik açılış/bağlanış checklist-i EYNİ şablon
                # kataloqunu işlədir (`checklist_item_templates`, migrations/
                # 088). Qoşulmadıqda gündəlik tiplər bənd siyahısını GÖRMÜRDÜ —
                # `test_composition_optional_port_wiring` məhz bunu tutdu.
                checklist_templates=repo("checklist_item_templates"),
            ),
            # #28 İllik Məzuniyyət Balansı (kompas1.md Faza 4) — ÜÇÜNCÜ, AYRI
            # mexanizm (bax `Session.annual_leave` şərhi).
            #
            # `limits=repo("limits")` MƏCBURİDİR, "yaxşı olardı" DEYİL: on ROOT
            # parametrinin HAMISI bu portdan oxunur və port ötürülməsəydi,
            # `AnnualLeavePolicy.defaults()` işə düşərdi — yəni Root 21 günü
            # 28-ə qaldırar, ekran təsdiqləyər, sistem isə 21 ilə işləməyə
            # davam edərdi ("görünür, dəyişdirilir, təsirsiz" qüsuru —
            # `test_root_control_parameter_parity.py` bunu qapıya çevirib).
            #
            # `shifts=repo("shifts")`: EYNİ repo `shift_planning`-in də
            # mənbəyidir, yəni hələ commit olunmamış növbə dəyişikliyi
            # məzuniyyət gününün hesablanmasında dərhal görünür.
            annual_leave=AnnualLeaveUseCase(
                balances=repo("annual_leave_balances"),
                requests=repo("annual_leave_requests"),
                shifts=repo("shifts"),
                limits=repo("limits"),
                audit=audit,
                clock=clock,
                notifier=notifier,
            ),
            # `bulk_employee_import` YUXARIDA yerli dəyişən kimi qurulub —
            # `_bulk_create_employee_row` closure-u `uow`/`users`-ə bağlıdır.
            bulk_employee_import=bulk_employee_import,
            store_templates=StoreTemplateUseCase(
                templates=repo("store_templates"),
                # EYNİ port `FirstRunSetupUseCase`-in İSTİFADƏ ETDİYİ port —
                # mağaza yaratmağın İKİNCİ yolu İCAD EDİLMİR (bax
                # `bulk_operations.py` başlığı).
                stores=repo("stores"),
                bulk_log=repo("bulk_import_log"),
                audit=audit,
                clock=clock,
            ),
            # #30 Planlaşdırılmış İcra Xülasəsi (kompas1.md Faza 6) — MÖVCUD
            # `multi_store_benchmark`/`exceptions` portları ÇAĞIRILIR, YENİ
            # hesablama qurulmur (bax use case modul başlığı, "1C SƏRHƏDİ").
            # `facts=repo("executive_digest_facts")`: EYNİ obyekt `configs=`
            # ilə (bax `connection.py`-dakı `executive_digest` yerli dəyişəni),
            # yəni gecikən-check-in sayı VƏ konfiqurasiya EYNİ tranzaksiyada
            # oxunur.
            executive_digest=ExecutiveDigestUseCase(
                configs=repo("executive_digest_config"),
                facts=repo("executive_digest_facts"),
                benchmark=repo("multi_store_benchmark"),
                exceptions=repo("exceptions"),
                limits=repo("limits"),
                audit=audit,
                clock=clock,
                notifier=notifier,
            ),
        )


def _camera_index() -> int:
    """`KOMPASOS_CAMERA_INDEX` — boşdursa sistemdəki BİRİNCİ kamera (0).

    YARARSIZ DƏYƏR TƏTBİQİ ÇÖKDÜRMÜR, defolta qayıdır: bu dəyər heç bir
    təhlükəsizlik qərarı vermir (kimin keçdiyini müəyyən etmir), yalnız hansı
    cihazın oxunacağını göstərir. Yanlış indeks onsuz da cihazın açılmaması —
    yəni bənd 5-in eskalasiyası — ilə nəticələnir və System Health Monitor-da
    görünür; `.env` yazı səhvinə görə bütün örtüyü bağlamaq isə həddindən
    artıq cəza olardı.
    """
    import os  # noqa: PLC0415

    raw = os.environ.get("KOMPASOS_CAMERA_INDEX", "").strip()
    if not raw:
        return 0
    try:
        return int(raw)
    except ValueError:
        _log.warning("FACE_CAMERA_INDEX_INVALID", extra={"raw_value": raw})
        return 0


def build_context(
    *,
    tenant_id_env: str = "KOMPASOS_TENANT_ID",
    allow_generate: bool = True,
) -> ApplicationContext:
    """Mühit dəyişənlərindən canlı kontekst qurur.

    ──────────────────────────────────────────────────────────────────────────
    TENANT İDENTİFİKATORUNUN OLMAMASI XƏTA DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Əvvəl `KOMPASOS_TENANT_ID` boş olduqda burada fatal xəta atılırdı və
    istifadəçi «Quraşdırma tamamlanmayıb» dalanına düşürdü. Halbuki sıfırdan
    quraşdırmada həmin dəyişən TƏRİFƏ GÖRƏ boşdur — onu dolduracaq İlk
    Quraşdırma Sihirbazı isə məhz həmin xəta ucbatından heç vaxt açılmırdı.

    İndi kimlik `shared/installation.py`-da həll olunur (mühit → yerli fayl →
    yeni UUID) və "ən üst hesab varmı?" sualı BAZAYA verilir — yəni ilk açılış
    sihirbaza, ikinci açılış girişə gedir.

    Raises:
        StartupError: Baza əlçatan deyilsə, və ya kimlik oxuna/yazıla
            bilmirsə. Xəta MESAJI istifadəçiyə göstərilir və orada əlaqə
            e-poçtu olur (bölmə 8) — "işə düşmədi" mesajı ilə kimsəsiz qalan
            müştəri ən pis haldır.
    """
    from src.domain.value_objects.identifiers import TenantId  # noqa: PLC0415
    from src.infrastructure.persistence.connection_types import TenantDatabase  # noqa: PLC0415
    from src.shared.installation import (  # noqa: PLC0415
        InstallationIdentityError,
        resolve_installation_identity,
    )

    try:
        identity = resolve_installation_identity(
            env_key=tenant_id_env, allow_generate=allow_generate
        )
    except InstallationIdentityError as exc:
        raise StartupError(
            exc.message,
            user_message=exc.user_message,
            context=exc.context,
            kind=StartupFailureKind.IDENTITY_UNAVAILABLE,
        ) from exc

    tenant_id = TenantId(identity.tenant_id)

    database: TenantDatabase | None = None
    try:
        # `TenantDatabase` — `Database` DEYİL: bu bağlantı MÜŞTƏRİNİNDİR və
        # `ApplicationContext`-dən aşağıya axan hər yol onu məhz belə gözləyir.
        # Bura `VendorDatabase` gəlsəydi, bütün iş sorğuları lisenziya bazasına
        # gedər və nəticə "sətir tapılmadı" kimi görünərdi (DB-4 Faza 1).
        database = TenantDatabase()
        database.open()
    except Exception as exc:
        _error_log.exception("DATABASE_OPEN_FAILED")
        # UĞURSUZ HOVUZ BAĞLANIR — TƏKRAR CƏHD ONU YIĞARDI (DB-4 Faza 4)
        # ------------------------------------------------------------------
        # `psycopg_pool` `open(wait=True)` çağırışında işçi saplarını istisna
        # atılmazdan ƏVVƏL başladır. Funksiya artıq bir dəfə çağırılan yol
        # deyil: «Yenidən Cəhd Et» düyməsi onu istənilən sayda təkrarlayır və
        # hər uğursuz cəhd bir dəstə asılı sap qoyardı. Sızma yalnız uzun
        # müddət qoşula bilməyən maşında — yəni məhz düymənin çox basıldığı
        # halda — görünərdi.
        #
        # `database` `None` ola bilər: DSN-in özü həll olunmadıqda (`Database`
        # konstruktorunda `build_dsn_from_env()`) obyekt heç yaranmır.
        if database is not None:
            with suppress(Exception):
                database.close()
        raise classify_connection_failure(exc) from exc

    context = ApplicationContext(
        database=database,
        tenant_id=tenant_id,
        self_hosted=not identity.is_licensed,
    )
    _apply_root_pool_limits(context)
    _log.info(
        "APPLICATION_CONTEXT_BUILT",
        extra={
            "tenant_id": str(tenant_id),
            "identity_source": identity.source.value,
            "superseded_local_id": (
                str(identity.superseded_local_id) if identity.superseded_local_id else None
            ),
        },
    )
    return context


#: Konfiqurasiya problemini bildirən SQLSTATE-lər — təkrar cəhd KÖMƏK ETMİR.
#: `28P01` yanlış parol, `28000` yanlış avtorizasiya (rol yoxdur/icazəsizdir),
#: `3D000` isə göstərilən BAZA ADI yoxdur. Üçü də ayarlar ekranına aiddir;
#: qalan hər şey (şəbəkə, DNS, taymaut, server bağlıdır) təkrar cəhdə aiddir.
_CONFIGURATION_SQLSTATES: Final[frozenset[str]] = frozenset({"28P01", "28000", "3D000"})


def classify_connection_failure(exc: BaseException) -> StartupError:
    """Bağlantı nasazlığını NÖVƏ görə ayırır (DB-4 Faza 4).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ İSTİSNANIN TİPİ İLƏ KİFAYƏTLƏNMİRİK
    ──────────────────────────────────────────────────────────────────────────
    `psycopg` yanlış parolu da, əlçatmaz hostu da `OperationalError` kimi
    verir — yəni tip tək başına «şəbəkə» ilə «parol»u ayıra bilmir. Ayırıcı
    SQLSTATE-dir və o, sətir mətnindən fərqli olaraq lokalizasiyadan və
    server versiyasından ASILI DEYİL (mətnə baxsaydıq, Postgres-in dil
    parametri dəyişdikdə təsnifat sükutla sıradan çıxardı).

    Səhv təsnifatın qiyməti yüksəkdir: şəbəkə nasazlığını «ayarlar səhvdir»
    kimi göstərmək istifadəçini DÜZGÜN dəyərləri dəyişməyə sövq edər.
    Ona görə defolt HƏMİŞƏ `DATABASE_UNREACHABLE`-dir — tanınmayan hər nasazlıq
    təkrar cəhd yoluna düşür, çünki o yol heç nəyi pozmur.
    """
    from src.infrastructure.config.connection_file import ConnectionFileError  # noqa: PLC0415
    from src.shared.exceptions import ConfigurationError  # noqa: PLC0415

    if isinstance(exc, ConfigurationError):
        # `build_dsn_from_env()` heç bir mənbə tapmadı — nə dəyişən, nə fayl.
        return StartupError(
            "Baza bağlantısı konfiqurasiya edilməyib",
            user_message=exc.user_message,
            context=exc.context,
            kind=StartupFailureKind.CREDENTIALS_MISSING,
        )

    if isinstance(exc, ConnectionFileError):
        # Fayl VAR, lakin oxunmur: korlanıb və ya parol açılmır.
        return StartupError(
            "Bağlantı konfiqurasiyası oxunmadı",
            user_message=exc.user_message,
            context=exc.context,
            kind=StartupFailureKind.CREDENTIALS_INVALID,
        )

    sqlstate = str(getattr(exc, "sqlstate", "") or "")
    if sqlstate in _CONFIGURATION_SQLSTATES:
        return StartupError(
            "Baza bağlantı məlumatları qəbul edilmədi",
            user_message=(
                "Server bağlantı məlumatlarını qəbul etmədi — istifadəçi adı, "
                "parol və ya baza adı yanlışdır. «Bağlantı Ayarları» ekranından "
                "dəyərləri yoxlayın."
            ),
            context={"sqlstate": sqlstate},
            kind=StartupFailureKind.CREDENTIALS_INVALID,
        )

    return StartupError(
        "Baza bağlantısı qurula bilmədi",
        user_message=(
            "Bazaya qoşulmaq mümkün olmadı. İnternet bağlantısını yoxlayın; "
            "problem davam edərsə dəstəklə əlaqə saxlayın."
        ),
        context={"sqlstate": sqlstate} if sqlstate else {},
        kind=StartupFailureKind.DATABASE_UNREACHABLE,
    )


def _apply_root_pool_limits(context: ApplicationContext) -> None:
    """Hovuz ölçüsünü ROOT dəyərinə gətirir — BOOTSTRAP PARADOKSUNUN həlli.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ HOVUZ ÖZ LİMİTİNİ QURULARKƏN OXUYA BİLMİR
    ──────────────────────────────────────────────────────────────────────────
    `DB_POOL_MIN_SIZE`/`DB_POOL_MAX_SIZE` `system_limits` cədvəlindədir, o
    cədvəli oxumaq üçün isə HOVUZ lazımdır. Yəni hovuz öz ölçüsünü qurularkən
    bilə bilməz. Həll: hovuz `DEFAULT_LIMITS` fallback-ları ilə qalxır, bağlantı
    işlədikdən və tenant məlum olduqdan SONRA `resize()` ilə ROOT dəyərinə
    gətirilir (bax `Database.apply_root_pool_limits`).

    XƏTA UDULUR: limit oxuna bilmirsə tətbiq İŞLƏMƏYƏ DAVAM ETMƏLİDİR —
    fallback hovuzu onsuz da işlək ölçüdədir və "hovuz ölçüsünü oxuya
    bilmədim" səbəbi ilə mağazanı bağlamaq mütənasib olmayan reaksiyadır.

    ──────────────────────────────────────────────────────────────────────────
    ÜÇ OXU BİR TRANZAKSİYADADIR (PERF-4)
    ──────────────────────────────────────────────────────────────────────────
    Burada ÜÇ limit oxunur (`DB_POOL_MIN_SIZE`, `DB_POOL_MAX_SIZE`,
    `DB_CONNECT_TIMEOUT_SECONDS`) və hər biri `_RootLimitReader`-dən keçir.
    Toplu AÇILMASA hər oxu öz tranzaksiyasını açır: uzaq bazada ölçüldü —
    RLS konteksti ~410 ms + sorğu ~207 ms, yəni cəmi **2.59 saniyə**, üstəlik
    bu, SPLASH müddətinin içindədir (istifadəçi giriş formasını gözləyir).
    `read_batch()` üçünü bir tranzaksiyaya yığır və limitlərin repo keşi
    sayəsində sorğu da BİR dəfə gedir.

    AKTOR YOXDUR (`user_id=None`) və bu, DÜZGÜNDÜR: giriş hələ baş verməyib,
    oxu isə tenant-səviyyəlidir (bax `session()` başlığı — `app.user_id`
    heç bir RLS OXU siyasətində işlənmir).
    """
    try:
        with context.read_batch():
            min_size, max_size = context.database.apply_root_pool_limits(
                context.infrastructure_limits()
            )
    except Exception:
        _error_log.exception("DB_POOL_ROOT_LIMITS_NOT_APPLIED")
        return
    _log.info("DB_POOL_ROOT_LIMITS_APPLIED", extra={"min_size": min_size, "max_size": max_size})


def _as_mapping(raw: object) -> dict[str, Any]:
    """Sihirbaz yükündən sözlük çıxarır — yararsız tip BOŞ sözlük olur.

    İstisna atmır: sahə yoxdursa draft konstruktorları onsuz da anlaşılan
    Azərbaycanca xəta verir ("Ad sahəsini doldurun"), halbuki `KeyError`
    istifadəçiyə heç nə demir.
    """
    return dict(raw) if isinstance(raw, dict) else {}


def _as_sequence(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, (list, tuple)):
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _optional_email(raw: object) -> Any:
    """Boş/yararsız e-poçt `None` olur — dəvətdə e-poçt MƏCBURİ deyil.

    Yararsız formatda istisna atmaq bütün quraşdırmanı dayandırardı, halbuki
    e-poçt yalnız BİLDİRİŞ kanalıdır (giriş identifikatoru istifadəçi adıdır,
    SEC-016). Səhv ünvan sonradan profil ekranından düzəldilir.
    """
    from src.domain.value_objects.credentials import EmailAddress  # noqa: PLC0415

    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return EmailAddress.parse(text)
    except Exception:
        _log.warning("SETUP_INVITE_EMAIL_IGNORED")
        return None


def _split_host_port(raw: str, *, default_port: int = 1541) -> tuple[str, int]:
    """«192.168.1.10:1541» → («192.168.1.10», 1541).

    Sihirbaz TƏK sahə soruşur (maketdə belədir), `ErpServerDraft` isə ayrı
    `host`/`port` gözləyir. Port göstərilməyibsə 1C-nin standart portu
    işlədilir; yararsız port da defolta düşür, çünki bu addım istəyə görədir
    və server onsuz da DEAKTİV yaradılır.
    """
    host, separator, port_text = raw.rpartition(":")
    if not separator:
        return (raw, default_port)
    try:
        return (host, int(port_text))
    except ValueError:
        return (raw, default_port)


__all__ = [
    "ApplicationContext",
    "Session",
    "StartupError",
    "StartupFailureKind",
    "build_context",
    "classify_connection_failure",
]
