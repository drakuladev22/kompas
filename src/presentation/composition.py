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

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.infrastructure.config.limits import InfrastructureLimits
from src.infrastructure.timekeeping.clock import SystemClock
from src.shared.data_paths import resolve_data_file
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from src.application.use_cases.announcements import AnnouncementUseCase
    from src.application.use_cases.annual_leave import AnnualLeaveUseCase
    from src.application.use_cases.attrition_risk import AttritionRiskUseCase
    from src.application.use_cases.audit_query import AuditQueryUseCase
    from src.application.use_cases.backup_access import BackupAccessUseCase
    from src.application.use_cases.behavior_baseline import BehaviorBaselineUseCase
    from src.application.use_cases.bulk_operations import (
        BulkEmployeeImportUseCase,
        StoreTemplateUseCase,
    )
    from src.application.use_cases.catalog_management import (
        FineTypeCatalogUseCase,
        LeaveTypeCatalogUseCase,
        WorkModeCatalogUseCase,
    )
    from src.application.use_cases.daily_attendance import DailyAttendanceSheetUseCase
    from src.application.use_cases.dashboard_layout import DashboardLayoutUseCase
    from src.application.use_cases.db_switch import DatabaseSwitchUseCase
    from src.application.use_cases.employee_documents import EmployeeDocumentUseCase
    from src.application.use_cases.employee_profile import EmployeeProfileAccessUseCase
    from src.application.use_cases.erp_connection import ErpConnectionWizardUseCase
    from src.application.use_cases.exception_engine import ExceptionEngineUseCase
    from src.application.use_cases.executive_digest import ExecutiveDigestUseCase
    from src.application.use_cases.export_preflight import ExportPreflightUseCase
    from src.application.use_cases.field_reports import FieldReportUseCase
    from src.application.use_cases.fine_management import (
        FineAppealUseCase,
        ManualFineUseCase,
    )
    from src.application.use_cases.first_run_setup import FirstRunSetupUseCase
    from src.application.use_cases.leave_verification import LeaveVerificationUseCase
    from src.application.use_cases.morning_check_in import MorningCheckInUseCase
    from src.application.use_cases.multi_store_benchmark import MultiStoreBenchmarkUseCase
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
    from src.application.use_cases.shift_scheduling import (
        ShiftPlanningUseCase,
        ShiftSwapUseCase,
    )
    from src.application.use_cases.staffing_pattern import StaffingPatternUseCase
    from src.application.use_cases.support_chat import SupportChatUseCase
    from src.application.use_cases.sync_conflicts import SyncConflictUseCase
    from src.application.use_cases.task_workflow import TaskWorkflowUseCase
    from src.application.use_cases.user_management import EmployeeDraft, UserManagementUseCase
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import NtpVerifier
    from src.domain.value_objects.identifiers import EmployeeId, TenantId
    from src.infrastructure.licensing.client import LicenseClient
    from src.infrastructure.persistence.connection import Database, PostgresUnitOfWork

_log = get_logger(__name__)
_error_log = get_logger(__name__, channel=LogChannel.ERROR)


class _NullNtp:
    """Ölçmə mənbəyi olmayan `NtpVerifier` — bax `ApplicationContext.__init__`."""

    def verified_now(self) -> tuple[datetime, bool]:
        return datetime.now(UTC), False

    def drift_seconds(self) -> float | None:
        return None


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
    """

    __slots__ = ("_database",)

    def __init__(self, database: Database) -> None:
        self._database = database

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
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
    """

    __slots__ = ("_database",)

    def __init__(self, database: Database) -> None:
        self._database = database

    def get_int(self, tenant_id: TenantId, key: str, default: int) -> int:
        with self._database.unit_of_work(tenant_id) as uow:
            value: int = uow.repository("limits").get_int(tenant_id, key, default)
            return value

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
        with self._database.unit_of_work(tenant_id) as uow:
            value: str = uow.repository("limits").get_str(tenant_id, key, default)
            return value

    def all_for(self, tenant_id: TenantId) -> dict[str, str]:
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

    def __init__(self, database: Database) -> None:
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


class StartupError(KompasOSError):
    """Tətbiq işə düşə bilmədi — fatal başlanğıc ekranı göstərilir.

    Bölmə 8 (EHTİYAT DƏSTƏK KANALI): "hər fatal başlanğıc-xətası ekranında
    statik e-poçt ünvanı göstərilir" — çünki tətbiq açılmırsa müştəri
    tətbiq-daxili chat-ə çata bilmir.
    """

    user_message = "KompasOS işə düşə bilmədi."


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
    tasks: TaskWorkflowUseCase
    sales_points: SalesPointsUseCase
    reports: MonthlyReportUseCase
    audit_query: AuditQueryUseCase
    users: UserManagementUseCase
    positions: PositionManagementUseCase
    support: SupportChatUseCase
    sync_conflicts: SyncConflictUseCase
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


class ApplicationContext:
    """Tətbiqin canlı obyekt qrafı — `main.py --gui` bunu qurur."""

    def __init__(
        self,
        *,
        database: Database,
        tenant_id: TenantId,
        license_client: LicenseClient | None = None,
        ntp: NtpVerifier | None = None,
    ) -> None:
        self._database = database
        self._tenant_id = tenant_id
        self._license = license_client
        self._clock = SystemClock()
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
        # İnfrastruktur pəncərəsi BİR DƏFƏ qurulur və paylaşılır: obyekt
        # vəziyyət saxlamır (nə keş, nə bağlantı), yalnız `Database` + tenant
        # daşıyır — hər istehlakçı üçün yenisini qurmaq eyni nəticəni verər,
        # lakin "hansı nüsxə doğrudur" sualını yaradardı.
        self._infrastructure_limits = InfrastructureLimits(
            limits=_RootLimitReader(database), tenant_id=tenant_id
        )

    @property
    def database(self) -> Database:
        return self._database

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
            )
            session.commit()
        _log.info(
            "FIRST_RUN_SETUP_COMPLETED",
            extra={"store_count": len(stores), "invite_count": len(invites)},
        )

        # 1C server addımı QƏSDƏN quraşdırma tranzaksiyasından KƏNARDADIR:
        # sihirbazın 3-cü addımı keçilə bilər (bölmə 7) və serverin qeydi
        # uğursuz olarsa artıq yaradılmış Root hesabı geri qaytarılmamalıdır —
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
            self._evidence_queue = EvidenceUploadQueue(
                path,
                max_upload_bytes=self._upload_limit(),
                limits=self._infrastructure_limits,
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
        self._attach_fine_evidence(owner_id, reference)

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
            limits=_StandaloneLimits(self._database),
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
        Yeddi işdən altısı `DAILY`-dir: hamısı CARİ vəziyyəti yenidən hesablayan
        gün-vahidli əməliyyatlardır (pəncərə DÜNƏNlə bitir). `FINE_EXPIRE_STALE`
        isə `HOURLY`-dir — o, DB-dəki `cron_close_expired_appeals` işinin tətbiq
        qatındakı əkizidir və həmin cron `schema.sql`-da `'0 * * * *'` ilə,
        yəni saatda bir dəfə qeydiyyatdan keçib. Ritmi fərqli seçsəydik, eyni
        qayda `pg_cron`-lu və `pg_cron`-suz quraşdırmada FƏRQLİ vaxtda işləyər
        və 72 saatlıq etiraz pəncərəsinin bağlanma anı quraşdırmadan asılı
        olardı (bax `fine_management.expire_stale` docstring-i, Variant B).

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
            (
                "FINE_EXPIRE_STALE",
                self._job_expire_stale_appeals,
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
            ("NIGHTLY_BACKUP", self._job_nightly_backup, JobCadence.DAILY, JobWeight.HEAVY),
        ):
            runner.register(ScheduledJob(key=key, handler=handler, cadence=cadence, weight=weight))

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

    def _job_expire_stale_appeals(self, context: Any) -> str:
        """Cavabsız qalmış cərimə etirazlarını bağlayır (72 saatlıq pəncərə)."""
        with self.session() as session:
            closed = session.fine_appeals.expire_stale(context.tenant_id)
            session.commit()
        return f"{closed} etiraz cavabsız bağlandı"

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
        """Bir tranzaksiya + onun üzərində qurulmuş use case dəsti."""
        with self._database.unit_of_work(self._tenant_id, user_id=user_id) as uow:
            yield self._build_session(uow)

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
        from src.application.use_cases.backup_access import (  # noqa: PLC0415
            BackupAccessUseCase,
        )
        from src.application.use_cases.behavior_baseline import (  # noqa: PLC0415
            BehaviorAnomalyRule,
            BehaviorBaselineUseCase,
        )
        from src.application.use_cases.bulk_operations import (  # noqa: PLC0415
            BulkEmployeeImportUseCase,
            StoreTemplateUseCase,
        )
        from src.application.use_cases.catalog_management import (  # noqa: PLC0415
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
        from src.application.use_cases.field_reports import (  # noqa: PLC0415
            FieldReportUseCase,
        )
        from src.application.use_cases.fine_management import (  # noqa: PLC0415
            FineAppealUseCase,
            ManualFineUseCase,
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
        from src.application.use_cases.shift_scheduling import (  # noqa: PLC0415
            ShiftPlanningUseCase,
            ShiftSwapUseCase,
        )
        from src.application.use_cases.staffing_pattern import (  # noqa: PLC0415
            StaffingPatternUseCase,
        )
        from src.application.use_cases.support_chat import SupportChatUseCase  # noqa: PLC0415
        from src.application.use_cases.sync_conflicts import (  # noqa: PLC0415
            SyncConflictUseCase,
        )
        from src.application.use_cases.task_workflow import (  # noqa: PLC0415
            TaskWorkflowUseCase,
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
        from src.infrastructure.plugins.signature import (  # noqa: PLC0415
            PluginSignatureVerifier,
            trust_store_from_env,
        )
        from src.infrastructure.security.encryption import EncryptionService  # noqa: PLC0415
        from src.infrastructure.security.hashing import HashingService  # noqa: PLC0415
        from src.shared.saga_orchestrator import SagaOrchestrator  # noqa: PLC0415

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
        notifier = PostgresNotifier(self._database, limits=session_limits)

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
        )

        # İSTİFADƏÇİ İDARƏETMƏSİ YEREL DƏYİŞƏNDİR, çünki İKİ yerdə lazımdır:
        # həm `Session.users` (Users ekranı), həm də toplu CSV idxalının
        # sətir-sətir yazı yolu (`_bulk_create_employee_row` aşağıda). İkinci
        # nüsxə qursaydıq, eyni Dual-Control deadlock qoruyucusu İKİ AYRI
        # obyektdə yaşayardı (`sales_points`/`overtime_tracking` ilə eyni
        # əsaslandırma).
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
            deadlock_guard=DualControlDeadlockGuardUseCase(uow.employees, notifier),
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
                saga=SagaOrchestrator(),
                audit=audit,
                notifier=notifier,
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
            permission_guard=PermissionHierarchyGuardUseCase(audit=audit, clock=clock),
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
            ),
            sync_conflicts=SyncConflictUseCase(
                repository=repo("sync_conflicts"),
                audit=audit,
                clock=clock,
                # `SYNC_CONFLICT_PAGE_SIZE` — konflikt növbəsinin səhifəsi.
                limits=repo("limits"),
            ),
            setup=FirstRunSetupUseCase(
                employees=uow.employees,
                positions=uow.positions,
                stores=repo("stores"),
                credentials=uow.employees,
                audit=audit,
                clock=clock,
                # `SETUP_RECOMMENDED_ADMIN_COUNT` — sihirbazın "neçə admin
                # tövsiyə olunur" xəbərdarlığı. Sihirbaz ƏN ERKƏN axındır,
                # lakin BURADA bağlantı artıq var (sessiya açılıb), ona görə
                # port ötürülür; bağlantısız yol (`limits=None`) use case-in
                # öz defoltu kimi qalır — bax `first_run_setup.py` başlığı.
                limits=repo("limits"),
            ),
            root_control=RootControlUseCase(
                limits=repo("limits"),
                toggles=repo("toggles"),
                flags=repo("permission_flags"),
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
            ),
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
            employee_documents=EmployeeDocumentUseCase(
                documents=repo("employee_documents"),
                employees=repo("employees"),
                limits=repo("limits"),
                audit=audit,
                clock=clock,
                notifier=notifier,
            ),
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


def build_context(*, tenant_id_env: str = "KOMPASOS_TENANT_ID") -> ApplicationContext:
    """Mühit dəyişənlərindən canlı kontekst qurur.

    Raises:
        StartupError: Baza və ya tenant konfiqurasiyası yoxdursa. Xəta MESAJI
            istifadəçiyə göstərilir və orada əlaqə e-poçtu olur (bölmə 8) —
            "işə düşmədi" mesajı ilə kimsəsiz qalan müştəri ən pis haldır.
    """
    import os  # noqa: PLC0415
    import uuid  # noqa: PLC0415

    from src.domain.value_objects.identifiers import TenantId  # noqa: PLC0415
    from src.infrastructure.persistence.connection import Database  # noqa: PLC0415

    raw_tenant = os.environ.get(tenant_id_env, "").strip()
    if not raw_tenant:
        raise StartupError(
            f"`{tenant_id_env}` təyin edilməyib",
            user_message=(
                "Quraşdırma tamamlanmayıb: tenant identifikatoru təyin edilməyib. "
                "Quraşdırma sənədinə baxın və ya dəstəklə əlaqə saxlayın."
            ),
            context={"missing_env": tenant_id_env},
        )

    try:
        tenant_id = TenantId(uuid.UUID(raw_tenant))
    except ValueError as exc:
        raise StartupError(
            "Tenant identifikatoru düzgün UUID deyil",
            user_message="Quraşdırma faylındakı tenant identifikatoru yararsızdır.",
            context={"value": raw_tenant},
        ) from exc

    try:
        database = Database()
        database.open()
    except Exception as exc:
        _error_log.exception("DATABASE_OPEN_FAILED")
        raise StartupError(
            "Baza bağlantısı qurula bilmədi",
            user_message=(
                "Bazaya qoşulmaq mümkün olmadı. İnternet bağlantısını yoxlayın; "
                "problem davam edərsə dəstəklə əlaqə saxlayın."
            ),
        ) from exc

    context = ApplicationContext(database=database, tenant_id=tenant_id)
    _apply_root_pool_limits(context)
    _log.info("APPLICATION_CONTEXT_BUILT", extra={"tenant_id": str(tenant_id)})
    return context


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
    """
    try:
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


__all__ = ["ApplicationContext", "Session", "StartupError", "build_context"]
