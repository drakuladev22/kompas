"""Repository və servis portları (Protocol) — Faza 2.3.

ASILILIQ İSTİQAMƏTİ: domen bu portları TƏYİN EDİR, infrastruktur onları
İMPLEMENTASİYA EDİR (Faza 3). Domen heç vaxt `psycopg`, `supabase` və ya
`httpx` idxal etmir — beləliklə biznes qaydaları DB-siz test oluna bilir.

`Protocol` (ABC yox) seçilib: implementasiyalar bu fayldan miras almağa
məcbur deyil — Faza 3-dəki Supabase repo-ları sadəcə uyğun metodları
təqdim edir (structural typing).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable
from uuid import UUID

from src.domain.annual_leave_rules import AnnualLeaveRolloverInput
from src.domain.attrition_rules import AttritionRiskScore
from src.domain.entities.announcement import Announcement
from src.domain.entities.annual_leave import AnnualLeaveBalance, AnnualLeaveRequest
from src.domain.entities.appeal import FineAppeal
from src.domain.entities.attendance_record import AttendanceRecord
from src.domain.entities.attendance_sheet import AttendanceFact, DailyAttendanceSheet
from src.domain.entities.auth_session import AuthSession
from src.domain.entities.employee import Employee
from src.domain.entities.employee_document import EmployeeDocument
from src.domain.entities.exception_record import ExceptionRecord
from src.domain.entities.field_report import FieldReport
from src.domain.entities.fine import Fine
from src.domain.entities.leave_request import LeaveRequest
from src.domain.entities.open_shift import OpenShiftPosting, OpenShiftSlot
from src.domain.entities.performance_review import PerformanceReview
from src.domain.entities.pos_threshold import POSPermissionThreshold
from src.domain.entities.position import Position
from src.domain.entities.registered_device import RegisteredDevice
from src.domain.entities.sales_points import PointsEntry, RewardRedemption
from src.domain.entities.shift import ShiftAssignment, ShiftSwapRequest
from src.domain.entities.task import Task
from src.domain.policies import BreakKind
from src.domain.value_objects.authorization import PermissionFlag, RolePriority
from src.domain.value_objects.behavior_signals import BehaviorBaseline, CheckInObservation
from src.domain.value_objects.branding import TenantBranding
from src.domain.value_objects.catalogs import FineType, LeaveType, WorkMode
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.erp import (
    ConnectionTestResult,
    ErpServer,
    ErpServerDraft,
    ErpServerStatus,
    OneCSaleRecord,
    SyncCursor,
)
from src.domain.value_objects.exception_signals import (
    ExceptionFinding,
    ExceptionSource,
    RuleEvaluationContext,
)
from src.domain.value_objects.executive_digest import ExecutiveDigestConfig
from src.domain.value_objects.export_corrections import ExportCorrection
from src.domain.value_objects.face_recognition import (
    FaceEmbedding,
    FaceExemption,
    FaceFrame,
    FaceProfile,
    FaceSample,
    FaceStoreScope,
    FaceVerificationLogEntry,
    LivenessGesture,
)
from src.domain.value_objects.field_reports import (
    FieldReportCategory,
    FieldReportTemplate,
    StoreAuditGap,
)
from src.domain.value_objects.gamification import PointsPeriod, RewardItem
from src.domain.value_objects.identifiers import (
    AnnouncementId,
    AnnualLeaveRequestId,
    AppealId,
    AttendanceRecordId,
    BulkImportLogId,
    DeviceId,
    EmployeeDocumentId,
    EmployeeId,
    ErpServerId,
    ExceptionId,
    ExecutiveDigestConfigId,
    FaceExemptionId,
    FieldReportId,
    FieldReportItemId,
    FineId,
    FineTypeId,
    LeaveRequestId,
    LeaveTypeId,
    OpenShiftPostingId,
    PointsEntryId,
    PositionId,
    RedemptionId,
    RewardId,
    SessionId,
    ShiftSwapRequestId,
    StoreId,
    StoreTemplateId,
    TaskId,
    TenantId,
    WorkModeId,
)
from src.domain.value_objects.infrastructure import (
    ChecksumPair,
    DatabaseTarget,
    MigrationStatus,
)
from src.domain.value_objects.job_runs import ScheduledJobRun
from src.domain.value_objects.licensing import (
    CheckInRequest,
    CrashReport,
    LicenseSnapshot,
)
from src.domain.value_objects.machine_identity import MachineIdentityHash
from src.domain.value_objects.overtime import OvertimeEntry, WorkedSpan
from src.domain.value_objects.pin_throttle import TerminalPinThrottle
from src.domain.value_objects.scheduling import TimeRange
from src.domain.value_objects.staffing_signals import (
    StaffingPatternSuggestion,
    StoreDayHeadcount,
)
from src.domain.value_objects.storage import ImageSize, StorageReference
from src.domain.value_objects.store_templates import StoreTemplate
from src.shared.event_bus import DomainEvent

# --------------------------------------------------------------------------- #
# İnfrastruktur servisləri
# --------------------------------------------------------------------------- #


@runtime_checkable
class Clock(Protocol):
    """Vaxt mənbəyi — testdə sabitlənə bilən.

    Domen kodu `datetime.now()` ÇAĞIRMIR: əks halda vaxt-həssas qaydalar
    (timeout, lockout, etiraz pəncərəsi) determinstik test oluna bilməzdi.
    """

    def now(self) -> datetime:
        """Cari UTC vaxtı (tz-aware)."""
        ...


@runtime_checkable
class NtpVerifier(Protocol):
    """NTP saat sürüşməsi yoxlayıcısı (spesifikasiya bölmə 2, KRİTİK).

    Fərq 60 saniyədən çoxdursa `TIME_DRIFT_DETECTED` — PIN handshake və
    override kimi vaxt-kritik əməliyyatlar müvəqqəti bloklanır.
    """

    def verified_now(self) -> tuple[datetime, bool]:
        """`(vaxt, ntp_ilə_təsdiqləndi)` qaytarır."""
        ...

    def drift_seconds(self) -> float | None:
        """Son ölçülmüş sürüşmə; ölçülməyibsə `None`."""
        ...


@runtime_checkable
class SystemLimits(Protocol):
    """ROOT İdarə Mərkəzindəki konfiqurasiya edilə bilən limitlər (bölmə 3)."""

    def get_int(self, tenant_id: TenantId, key: str, default: int) -> int: ...

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str: ...

    def all_for(self, tenant_id: TenantId) -> dict[str, str]: ...

    def describe(self, tenant_id: TenantId) -> list[dict[str, object]]:
        """ROOT ekranı üçün tam təsvir — min/max hüdudları və izahla."""
        ...

    def set_value(
        self, tenant_id: TenantId, key: str, value: str, *, changed_by: EmployeeId
    ) -> None:
        """`changed_by` MƏCBURİDİR — «kim dəyişdi» sualı cavablanmalıdır."""
        ...


@runtime_checkable
class FeatureToggles(Protocol):
    """Modul aç/bağla vəziyyəti (bölmə 3).

    RETROAKTİV TƏSİR QAYDASI: deaktivasiya YALNIZ yeni instansiyalara təsir
    edir — mövcud qeydlər öz axınını normal tamamlayır.
    """

    def is_enabled(self, tenant_id: TenantId, module_key: str) -> bool: ...

    def describe(self, tenant_id: TenantId) -> list[dict[str, object]]:
        """ROOT ekranı üçün — struktur-kritik bayrağı ilə birlikdə."""
        ...

    def is_structural(self, tenant_id: TenantId, module_key: str) -> bool: ...

    def set_enabled(
        self,
        tenant_id: TenantId,
        module_key: str,
        *,
        enabled: bool,
        changed_by: EmployeeId,
        confirmation: str | None = None,
    ) -> None:
        """Struktur-kritik modulun söndürülməsi yazılı təsdiq TƏLƏB EDİR."""
        ...


@runtime_checkable
class Notifier(Protocol):
    """Bildiriş portu — in-app + kritik hallarda e-poçt fallback (bölmə 7)."""

    def notify(
        self,
        *,
        tenant_id: TenantId,
        recipient_id: EmployeeId | None,
        category: str,
        title_az: str,
        body_az: str,
        is_critical: bool = False,
    ) -> None: ...


@runtime_checkable
class EvidenceStorageProvider(Protocol):
    """Cərimə sübut şəkillərinin saxlanma portu (bölmə 4, 6).

    ADLANDIRMA QEYDİ: tələbdə `IEvidenceStorageProvider` yazılmışdı. Bu
    layihədəki 13 portun heç birində `I` prefiksi yoxdur (`Clock`,
    `Notifier`, `EmployeeRepository`, ...) — tək istisna yaratmaq oxucunu
    "bu niyə fərqlidir?" sualı ilə qarşılaşdırardı. Məzmun eynidir.

    ──────────────────────────────────────────────────────────────────────
    NİYƏ `get_access_url` YOXDUR
    ──────────────────────────────────────────────────────────────────────
    Fayllar PRIVATE-dır. Private Drive faylını `<img src=...>` kimi
    göstərmək mümkün deyil — Google autentifikasiyasız sorğunu bloklayır.
    GUI bayt-ları alıb özü render edir (PySide6 `QPixmap`).

    Bu port YALNIZ cərimə sübutuna aiddir. Profil şəkli və tapşırıq sübutu
    Supabase Storage-da qalır (tələb belədir) — onlar bu portdan KEÇMİR.
    """

    def upload(
        self,
        file_bytes: bytes,
        filename: str,
        store_id: StoreId,
        taken_at: datetime,
    ) -> StorageReference:
        """Şəkli mağaza/ay qovluğuna yükləyir və istinadını qaytarır.

        Qovluq iyerarxiyası (`KompasOS/{Mağaza}/{İl-Ay}/`) TƏLƏB OLUNDUQDA
        avtomatik yaradılır — admin əvvəlcədən heç nə hazırlamır.
        """
        ...

    def get_image_bytes(
        self, reference: StorageReference, size: ImageSize = ImageSize.FULL
    ) -> bytes:
        """Şəklin baytlarını qaytarır (ekranda BİRBAŞA göstərmək üçün)."""
        ...

    def delete(self, reference: StorageReference) -> bool: ...


@runtime_checkable
class SalesDataConnector(Protocol):
    """Bir 1C serverindən satış oxuma portu (bölmə 6, 7).

    Konkret protokol (OData/HTTP) infrastrukturda qalır — domen yalnız
    "test et" və "kursordan sonrakı satışları gətir" əməliyyatlarını tanıyır.
    """

    def test_connection(self) -> ConnectionTestResult:
        """Host + autentifikasiya + baza adı + sənəd adını BİR addımda yoxlayır."""
        ...

    def fetch_sales(self, cursor: SyncCursor, *, page_size: int = ...) -> list[OneCSaleRecord]:
        """Kursordan sonrakı KEÇİRİLMİŞ sənədləri gətirir."""
        ...

    def close(self) -> None: ...


@runtime_checkable
class ErpConnectorFactory(Protocol):
    """Konnektor yaradıcısı — credential-ların deşifrəsi burada qalır.

    İki fərqli giriş nöqtəsi var, çünki sihirbaz HƏLƏ SAXLANMAMIŞ
    konfiqurasiyanı test edir (`for_draft`), sinxronizasiya isə saxlanmış
    serverlə işləyir (`for_server`).
    """

    def for_draft(self, draft: ErpServerDraft) -> SalesDataConnector: ...

    def for_server(self, server_id: ErpServerId) -> SalesDataConnector: ...


@runtime_checkable
class ErpServerRegistry(Protocol):
    """1C server siyahısının idarəsi (bölmə 7 — Bağlantı Sihirbazı)."""

    def require(self, server_id: ErpServerId) -> ErpServer: ...

    def list_all(self) -> list[ErpServer]: ...

    def syncable(self) -> list[ErpServer]:
        """Sinxronizasiya dövrünə daxil olan serverlər (`INACTIVE` xaric)."""
        ...

    def create(
        self,
        draft: ErpServerDraft,
        *,
        created_by: EmployeeId | None = None,
        activate: bool = True,
    ) -> ErpServer: ...

    def update(
        self,
        server_id: ErpServerId,
        draft: ErpServerDraft,
        *,
        updated_by: EmployeeId | None = None,
        backup_previous: bool = True,
    ) -> ErpServer: ...

    def set_status(
        self,
        server_id: ErpServerId,
        status: ErpServerStatus,
        *,
        changed_by: EmployeeId | None = None,
        reason: str | None = None,
    ) -> None: ...

    def rollback(self, server_id: ErpServerId, *, actor_id: EmployeeId | None = None) -> ErpServer:
        """Sonuncu DOĞRULANMIŞ konfiqurasiyanı bərpa edir (bir kliklə)."""
        ...

    def mark_sync_started(self, server_id: ErpServerId, *, now: datetime | None = None) -> None: ...

    def record_success(
        self, server_id: ErpServerId, cursor: SyncCursor, *, now: datetime | None = None
    ) -> None: ...

    def record_failure(
        self, server_id: ErpServerId, message: str, *, now: datetime | None = None
    ) -> None: ...


@runtime_checkable
class LicenseGateway(Protocol):
    """Lisenziya qeydini oxuyan port (bölmə 8).

    Ayrıca lisenziya serveri YOXDUR — qeyd mövcud Supabase layihəsindəki
    `license_tenants` cədvəlindədir və tenant onu YALNIZ OXUYUR.

    Uğursuzluq QAYTARILAN DƏYƏRLƏ deyil, XƏTA ilə bildirilir
    (`LicenseUnavailableError` / `LicenseNotFoundError`) — belə olduqda
    "cavab gəlmədi"-ni sükutla "hər şey qaydasındadır" kimi oxumaq mümkün
    deyil. Qərarı (bloklamaq/bloklamamaq) yuxarıdakı qat verir.
    """

    def check_in(self, request: CheckInRequest) -> LicenseSnapshot:
        """Dövri yoxlama — qeydin cari vəziyyətini qaytarır."""
        ...

    def report_crash(self, report: CrashReport) -> None:
        """Anonimləşdirilmiş crash hesabatını yazır (bölmə 8)."""
        ...


@runtime_checkable
class LicenseStateStore(Protocol):
    """Son oxunuşun YERLİ, şifrələnmiş keşi.

    Offline qrace-in mövcud olması üçün oxunuş tətbiq bağlansa da qalmalıdır;
    həmçinin `LICENSE_INACTIVE` ekranındakı əlaqə məlumatı baza ƏLÇATMAZ
    olduqda da göstərilə bilməlidir.
    """

    def load(self) -> LicenseSnapshot | None: ...

    def save(self, snapshot: LicenseSnapshot) -> None: ...

    def first_run_at(self) -> datetime | None:
        """Tətbiqin bu PC-də ilk işə düşməsi — heç vaxt yoxlama olmadıqda
        qrace bundan sayılır."""
        ...

    def clock_high_water(self) -> datetime | None:
        """İndiyədək görülmüş ən böyük an — müddət müqayisəsi bununla
        möhkəmləndirilir (saatı geri çəkməklə lisenziya açılmasın)."""
        ...

    def clock_rollback_detected(self, now: datetime) -> bool:
        """Yerli saat əvvəl görülmüş ən yüksək andan geriyə çəkilibmi."""
        ...


@runtime_checkable
class AuditTrail(Protocol):
    """Audit log yazıcısı — append-only (bölmə 4, SEC-007)."""

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
    ) -> None: ...


@runtime_checkable
class SecurityEventRepository(Protocol):
    """`security_events` yazıcısı (SEC-7, `schema.sql` §16) — GİRİŞ/İCAZƏ hadisələri.

    `AuditTrail` İLƏ EYNİ NAXIŞDA — ayrıca dataclass YOX, açıq keyword
    arqumentlər — çünki hər ikisi ÇOX SAYDA fərqli use case-dən çağırılan,
    YALNIZ-YAZAN (append-only) köməkçi sinklərdir. Fərqli davranış: `AuditTrail`
    uğursuzluqda əməliyyatı geri qaytarır ("audit istisna udmur", CLAUDE.md §5),
    bu port İSƏ FAIL-SOFT-dur — istehsalatda YALNIZ `src.shared.security_events.
    FailSoftSecurityEventRecorder` bağlanmalıdır (kompozisiya kökündə), xam
    implementasiya BİRBAŞA use case-ə verilməməlidir.
    """

    def record(
        self,
        *,
        tenant_id: TenantId,
        event_type: str,
        employee_id: EmployeeId | None = None,
        username_attempt: str | None = None,
        ip_address: str | None = None,
        machine_name: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None: ...


@runtime_checkable
class EventPublisher(Protocol):
    """Aqreqatların topladığı hadisələri yayımlayır (tranzaksiyadan SONRA)."""

    async def publish_all(self, events: tuple[DomainEvent, ...]) -> None: ...


# --------------------------------------------------------------------------- #
# Repository-lər
# --------------------------------------------------------------------------- #


@runtime_checkable
class BrandingRepository(Protocol):
    """Kirayəçinin vizual kimliyi (TENANT-1 Faza 2).

    `get()` HEÇ VAXT `None` qaytarmır — sətir yoxdursa `DEFAULT_BRANDING`
    verilir. Səbəb: brendinq oxunuşu tətbiqin AÇILIŞ yolundadır və hər
    çağıran tərəfin `None` yoxlaması yazması tələb olunsaydı, biri unudulanda
    başlıq zolağı boş qalardı. Defolt dəyər «brendinq təyin edilməyib»
    halının DÜZGÜN cavabıdır, boşluq deyil.
    """

    def get(self, tenant_id: TenantId) -> TenantBranding: ...

    def save(
        self, tenant_id: TenantId, branding: TenantBranding, *, updated_by: EmployeeId
    ) -> None:
        """`updated_by` MƏCBURİDİR — «kim dəyişdi» sualı cavablanmalıdır."""
        ...


@runtime_checkable
class ActiveStoreLookup(Protocol):
    """Kirayəçinin aktiv mağazalarının identifikatorları.

    DAR PORT — tam `StoreRepository` DEYİL. Layihədə belə bir port heç vaxt
    olmayıb: mağaza sətirləri hər yerdə konkret sorğularla oxunur
    (`benchmark_repository`, `field_report_repositories`). Geniş port əlavə
    etmək mövcud olmayan bir abstraksiyanı vəd etmək olardı; bura yalnız
    FAKTİKİ ehtiyac yazılıb — «kirayəçidə neçə mağaza var və hansılar».
    """

    def list_active(self, tenant_id: TenantId) -> list[StoreId]: ...


@runtime_checkable
class DeviceRegistry(Protocol):
    """Qeydiyyatdan keçmiş cihazlar (DEVICE-1).

    `count_active()` AYRICA metoddur, `len(list_by_status(ACTIVE))` DEYİL:
    lisenziya sayğacı hər açılışda oxunur və minlərlə sətri gətirib saymaq
    şəbəkə/yaddaş qiymətini heç nə üçün ödəmək olardı. Sayğac `COUNT(*)`
    ilə bazada hesablanır.
    """

    def get(self, device_id: DeviceId) -> RegisteredDevice | None: ...

    def find_by_short_code(self, tenant_id: TenantId, short_code: str) -> RegisteredDevice | None:
        """Admin telefonla söylənilən kodla cihazı tapır."""
        ...

    def short_code_exists(self, tenant_id: TenantId, short_code: str) -> bool:
        """Kod artıq işlədilirmi — təkrar yaratma dövrəsi üçün."""
        ...

    def list_by_status(
        self, tenant_id: TenantId, status: str, *, limit: int
    ) -> list[RegisteredDevice]: ...

    def list_all(self, tenant_id: TenantId, *, limit: int) -> list[RegisteredDevice]: ...

    def count_active(self, tenant_id: TenantId) -> int: ...

    def count_pending(self, tenant_id: TenantId) -> int: ...

    def save(self, device: RegisteredDevice) -> None: ...


@runtime_checkable
class EmployeeRepository(Protocol):
    def get(self, employee_id: EmployeeId) -> Employee | None: ...

    def get_by_username(self, tenant_id: TenantId, username: Username) -> Employee | None: ...

    def find_by_pin_candidates(self, tenant_id: TenantId, store_id: StoreId) -> list[Employee]:
        """Mağazadakı aktiv, PIN-i olan işçilər.

        PIN unikal DEYİL — hash müqayisəsi use case səviyyəsində, işçi-işçi
        aparılır (PIN `employee_id`-yə bağlı hash-lənir, SEC-005).
        """
        ...

    def save(self, employee: Employee) -> None: ...

    def update_credentials(
        self,
        employee_id: EmployeeId,
        *,
        pin_hash: str | None = None,
        password_hash: str | None = None,
        pepper_version: int | None = None,
    ) -> None:
        """Sirr hash-larını AYRICA yazır — `None` verilən sahə TOXUNULMUR.

        NİYƏ `save()`-dən AYRIDIR: hash `Employee` entity-sində saxlanılmır
        (təsadüfən log-a və ya DTO-ya düşməsin deyə), ona görə `save()`
        `password_hash`/`pin_hash` sütunlarına ümumiyyətlə toxunmur. Nəticədə
        yalnız `save()` çağıran bir axın müvəqqəti şifrəni HESABLAYIB
        GÖSTƏRƏ, lakin YAZMAYA bilər — məhz bu boşluq
        `EmergencyAccessRecoveryUseCase.recover()`-da vardı: admin ekranda
        işləməyən bir şifrə görürdü.
        NİYƏ PORTDADIR: yazma yolu tətbiq qatından çağırılmalıdır, əks halda
        use case sirri yazmaq üçün infrastruktur sinfini tanımalı olardı.
        """
        ...

    def count_active_with_flag(self, tenant_id: TenantId, flag_code: str) -> int:
        """Dual-Control Deadlock Guard üçün (bölmə 3)."""
        ...

    def count_active_ranked_at_or_above(self, tenant_id: TenantId, priority: RolePriority) -> int:
        """Verilən pillədə və ondan YUXARIDA olan aktiv işçilərin sayı.

        DİQQƏT: `RolePriority`-də KİÇİK rəqəm DAHA YÜKSƏK səlahiyyətdir, yəni
        şərt `<=`-dir — «`EXECUTIVE` və ondan yuxarı» = `Root` + `CEO`.

        NİYƏ FLAG-LA SAYMAQ KİFAYƏT ETMİR (SETUP-3): «tenant-da ən üst hesab
        varmı?» sualı əvvəl `can_manage_license` flag-i ilə cavablanırdı,
        halbuki həmin flag səviyyə-1 hardlock daşıyır və YALNIZ `Root`-a
        verilir. Sihirbaz isə `CEO` yaradır — nəticədə hesab yarandıqdan
        SONRA da sayğac 0 qalırdı və sihirbaz hər açılışda yenidən çıxırdı.
        İyerarxiya pilləsi bu sualın TƏBİİ ölçüsüdür: custom rol da düzgün
        sayılır, çünki onun da prioriteti var.
        """
        ...


@runtime_checkable
class AuthSessionRepository(Protocol):
    """`auth_sessions` sətrinin davamlı saxlanması (SEC-011, schema.sql §17b).

    NİYƏ `ports.py`-DA, `authentication.py`-nın YANINDA DEYİL (CLAUDE.md §3):
    qaytardığı `AuthSession` domen tipidir (`entities/auth_session.py`) —
    port yalnız domen tipi qaytardığı üçün BURADA yaşayır, `ReportFactProvider`
    (`use_cases/reporting.py`) ilə TƏRS haldır (o, tətbiq strukturu qaytarır).
    """

    def save(self, session: AuthSession) -> None:
        """Upsert (`id` ilə) — `issue()` yeni sətir yaradır, `touch()`/`revoke()`
        mövcudu yeniləyir. `token_hash` UNIQUE-dir; toqquşma davranışı infra
        implementasiyasının qərarıdır (SEC-5 müqaviləsi, infra bölməsi)."""
        ...

    def get(self, session_id: SessionId) -> AuthSession | None:
        """Admin-in uzaqdan ləğv axını üçün — id ilə birbaşa tapır."""
        ...

    def get_by_token_hash(self, tenant_id: TenantId, token_hash: str) -> AuthSession | None:
        """`validate()`/`touch()` üçün. AÇIQ token DEYİL, onun SHA-256 heşi ilə
        axtarır — açıq token bu port sərhədindən HEÇ VAXT keçmir."""
        ...

    def list_recent_for_user(
        self, tenant_id: TenantId, user_id: EmployeeId, *, limit: int = 10
    ) -> list[AuthSession]:
        """Profil ekranının "Sessiyalarım" siyahısı — ən yeni ƏVVƏL, aktiv/
        bağlı FƏRQİ QOYULMADAN (bağlı sətir də "nə vaxt, hansı cihazdan"
        sualının cavabıdır).

        `limit=10`: `PANEL_LIMIT` (`notification_repositories.py`) presedenti
        ilə EYNİ kateqoriya — ekran görünüşünün dizayn sabitidir, biznes/
        siyasət həddi DEYİL (Root-a verilmir, CLAUDE.md §5)."""
        ...


@runtime_checkable
class PinThrottleRepository(Protocol):
    """`store_pin_throttle` sətrinin davamlı saxlanması (SEC-01/SEC-05, dövrə 3).

    NİYƏ `ports.py`-DA: qaytardığı `TerminalPinThrottle` domen tipidir
    (`value_objects/pin_throttle.py`) — `AuthSessionRepository` ilə EYNİ
    əsaslandırma (CLAUDE.md §3).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ AÇAR `machine_key`-dir, `store_id` DEYİL (SEC-05)
    ──────────────────────────────────────────────────────────────────────────
    `store_id` `KOMPASOS_STORE_ID` mühit dəyişənindən gəlir və ADMIN HÜQUQU
    OLMADAN dəyişdirilə bilər (`HKCU\\Environment`) — açar olsaydı, hücumçu
    həddə yaxınlaşanda onu dəyişib TƏZƏ sayğac alardı. `MachineIdentityHash`
    (Windows `MachineGuid`, `HKEY_LOCAL_MACHINE`, admin-only) əvəzinə işlədilir
    — bax onun öz modul başlığı. `store_id` sətrin MƏLUMAT sahəsidir (klon
    aşkarlaması üçün, bax `PinHandshakeUseCase`-in "KLON AŞKARLAMASI" bölməsi).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ PƏNCƏRƏ/KİLİD ARİFMETİKASI İSTEHSALATDA DB TRİGGER-İNDƏDİR, PYTHON-DAN
    ÇAĞIRILMIR (AMMA DOMENDƏ SPESİFİKASİYA OLARAQ MÖVCUDDUR)
    ──────────────────────────────────────────────────────────────────────────
    TIME-1: server-vaxtına bağlı hesablama client-in göndərdiyi dəyərdən
    ASILI OLA BİLMƏZ. `record_failure()` YALNIZ NƏTİCƏNİ (`failed_count`,
    `window_started_at`, `locked_until`) qaytarır — HANSI dəyərin
    göndəriləcəyini YOX, çünki göndərilən HƏR HANSI vaxt dəyəri trigger
    tərəfindən İGNORED olunur (infra qərarı).

    Sabit-pəncərə SEMANTİKASININ ÖZÜ isə (dövrə 4 düzəlişi) `TerminalPinThrottle.
    advance_after_failure()`-də İCRA OLUNAN SPESİFİKASİYA kimi yazılıb —
    istehsalat kodu bunu ÇAĞIRMIR, AMMA sınaq sahtəsi (`InMemoryPinThrottle`)
    çağırır və infra-nın SQL trigger-i EYNİ qaydaları TƏKRARLAMALIDIR
    (CLAUDE.md §7: "sütun yox, qayda dəyişirsə hər iki yer"). Bax onun öz
    modul başlığı — "sayğac ƏBƏDİ kilid" qüsuru MƏHZ bu qaydanın YAZILI
    olmamasından yaranmışdı.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `get_for_update` MƏCBURİDİR (`RowLockingLeaveRequests`-in isinstance-
    optional naxışından FƏRQLİ OLARAQ)
    ──────────────────────────────────────────────────────────────────────────
    `LeaveRequest`-də kilidsiz oxu qəbul edilə bilirdi, çünki DB-dəki qismən
    unikal indeks İKİNCİ, MÜSTƏQİL qoruma qatı idi. Burada belə ikinci qat
    YOXDUR — `get_for_update` protokolun ADİ (məcburi) üzvüdür.

    ──────────────────────────────────────────────────────────────────────────
    UĞURLU GİRİŞDƏ SIFIRLAMA YOXDUR — BU PROTOKOLDA "RESET" METODU QƏSDƏN YOXDUR
    ──────────────────────────────────────────────────────────────────────────
    ARCHITECT-in qərarı (security-nin arqumenti ilə): sıfırlama olsaydı,
    hücumçu N-1 cəhd edib növbəti QANUNİ girişi gözləməklə sayğacı PULSUZ
    təmizləyərdi. Sabit pəncərə (`TerminalPinThrottle.window_started_at`/
    `advance_after_failure`) təbii decay verir — sıfırlama İSTİFADƏÇİ-
    səviyyəli `PinSecurityState`-də mənalıdır (orada HƏMİN ŞƏXS öz kimliyini
    sübut edir), BURADA yox (kim uğurla girsə də, DİGƏR işçilərin PIN-inə
    qarşı davam edən sınaq HƏLƏ mümkündür).
    """

    def get_for_update(
        self, tenant_id: TenantId, machine_key: MachineIdentityHash
    ) -> TerminalPinThrottle | None:
        """`SELECT ... FOR UPDATE` — sətir tapılmadıqda `None` (bu maşında
        HƏLƏ heç bir uğursuz PIN cəhdi qeydə alınmayıb). `PinHandshakeUseCase.
        authenticate()` PIN yoxlaması İLƏ EYNİ tranzaksiyada çağırır."""
        ...

    def record_failure(
        self, tenant_id: TenantId, machine_key: MachineIdentityHash, *, store_id: StoreId
    ) -> TerminalPinThrottle:
        """Atomik artırma (`INSERT ... ON CONFLICT DO UPDATE ... RETURNING`) —
        DB trigger sabit-pəncərə hesablamasını ÖZÜ edir (bax `TerminalPinThrottle.
        advance_after_failure`-in eyni qaydaları — trigger onlarla UYĞUN
        olmalıdır). `store_id` HƏR çağırışda YENİLƏNİR (son görülən mağaza)
        — klon aşkarlamasının mənbəyi budur.

        VACİB: bu metod `save()`-in uğursuzluğunu UDMUR — çağıran (`PinHandshake
        UseCase`) əməliyyatı geri qaytarmalıdır ki, sayğac YAZILMADAN "PIN
        yanlışdır" göstərmək SEC-01-in kök səbəbinin (sükutla söndürülmüş
        qoruma) TƏKRARI olmasın."""
        ...

    def update_last_seen_store(
        self, tenant_id: TenantId, machine_key: MachineIdentityHash, *, store_id: StoreId
    ) -> None:
        """Klon aşkarlanandan (`get_for_update`-in qaytardığı `store_id`
        CARİ `store_id`-dən FƏRQLİDİR) SONRA sətri yeniləyir ki, EYNİ klon
        HƏR PIN cəhdində TƏKRAR siqnal göndərməsin — YALNIZ dəyişiklik anında
        bir dəfə. Sətir ARTIQ mövcud olmalıdır (bu metod yalnız `get_for_update`
        DOLU sətir qaytarandan sonra çağırılır)."""
        ...


@runtime_checkable
class FaceThrottleRepository(Protocol):
    """`store_face_throttle` — 1:N ÜZLƏ GİRİŞİN TERMİNAL sayğacı (AF-2).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ AYRI CƏDVƏL — VƏ NİYƏ ORTAQ SAYĞAC QƏRARI DƏYİŞDİRİLDİ
    ──────────────────────────────────────────────────────────────────────────
    `identify_for_login()` (1:N) rəddləri əvvəl `store_pin_throttle`-a, yəni
    PIN girişi ilə ORTAQ sayğaca yazılırdı. Həmin qərar sənədli idi və məntiqi
    də aydın idi: «iki müstəqil sayğac hücumçuya büdcəni İKİ QAT edərdi,
    halbuki qorunan şey EYNİ terminaldır».

    Lakin o mühakimə «eyni terminalda EYNİ ADAM cəhd edir» fərziyyəsinə
    əsaslanır. 1:N üz girişində bu fərziyyə YOXDUR: kameranın qarşısına
    KEÇƏN İSTƏNİLƏN adam — o cümlədən mağazanın işçisi olmayan kənar şəxs —
    sayğacı artıra bilir və heç bir kimlik təqdim etmir. Nəticədə bir neçə
    dəfə kameraya baxmaq BÜTÜN mağazanın PIN girişini dayandırırdı, yəni
    qoruma XİDMƏTDƏN İMTİNA vasitəsinə çevrilirdi (AF-2).

    İki riskdən hansının ağır olduğu SİYASƏT qərarıdır və o, verilib:
    DoS aradan qaldırılır, büdcənin iki qat olması isə QƏBUL EDİLİR.

    ──────────────────────────────────────────────────────────────────────────
    HƏDD YENİ ROOT AÇARI DEYİL — MÖVCUD İKİSİ PAYLAŞILIR
    ──────────────────────────────────────────────────────────────────────────
    Üz kanalı `KIOSK_STORE_PIN_MAX_FAILED_ATTEMPTS` və
    `KIOSK_STORE_PIN_LOCKOUT_MINUTES` dəyərlərini işlədir. Ayrı açar
    yaradılmadı: yeni ədəd icad etmək əvəzinə Root hər iki kanalı BİR
    parametrlə tənzimləyir və büdcənin iki qat olmasını həmin dəyəri
    endirməklə kompensasiya edə bilir. İki ayrı açar olsaydı, «ümumi büdcə
    nə qədərdir?» sualının cavabı iki sətrin cəmindən çıxarılmalı olardı.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ EYNİ `TerminalPinThrottle` TİPİ
    ──────────────────────────────────────────────────────────────────────────
    Sətrin FORMASI eynidir (açar, sayğac, sabit pəncərə, kilid) və
    `advance_after_failure()` spesifikasiyası da eynidir. Yeni dəyər obyekti
    yaratmaq həmin arifmetikanın İKİNCİ nüsxəsini doğurardı və `pin_throttle.py`
    başlığındakı «sayğac ƏBƏDİ kilid» qüsuru iki yerdə ayrı-ayrı təkrarlana
    bilərdi. Fərq CƏDVƏLDƏDİR, tipdə yox.

    ──────────────────────────────────────────────────────────────────────────
    UĞURLU GİRİŞDƏ SIFIRLAMA YOXDUR
    ──────────────────────────────────────────────────────────────────────────
    `PinThrottleRepository`-nin eyni qərarı: sıfırlama olsaydı, hücumçu N-1
    cəhddən sonra qanuni bir girişi gözləyib sayğacı pulsuz təmizləyərdi.
    Sabit pəncərə təbii decay verir.

    ⚠️ DB TƏLƏBİ: `store_face_throttle` cədvəli `migrations/075`-in
    `store_pin_throttle` ilə EYNİ formada olmalıdır (PK `(tenant_id,
    machine_key)`, `machine_key ~ '^[0-9a-f]{64}$'`, server-vaxtlı sabit
    pəncərə trigger-i). Sütunlar və trigger məntiqi TƏKRARLANIR, ÇÜNKİ
    onlar EYNİ qaydadır — fərq yalnız hansı kanalın sayıldığındadır.
    """

    def get_for_update(
        self, tenant_id: TenantId, machine_key: MachineIdentityHash
    ) -> TerminalPinThrottle | None:
        """`SELECT ... FOR UPDATE`; sətir yoxdursa `None` (hələ uğursuz üz
        cəhdi qeydə alınmayıb)."""
        ...

    def record_failure(
        self, tenant_id: TenantId, machine_key: MachineIdentityHash, *, store_id: StoreId
    ) -> TerminalPinThrottle:
        """Atomik artırma — `PinThrottleRepository.record_failure` ilə EYNİ
        müqavilə: sabit-pəncərə hesablaması DB trigger-indədir (TIME-1) və
        metod istisnanı UDMUR (sayğac yazılmadan «üz tanınmadı» göstərmək
        SEC-01-in kök səbəbinin təkrarı olardı)."""
        ...


@runtime_checkable
class PositionRepository(Protocol):
    def get(self, position_id: PositionId) -> Position | None: ...

    def get_by_code(self, tenant_id: TenantId, code: str) -> Position | None: ...

    def list_for_tenant(self, tenant_id: TenantId) -> list[Position]: ...

    def save(self, position: Position) -> None: ...


@runtime_checkable
class PermissionFlagRepository(Protocol):
    """System Permission Registry (bölmə 3) — yalnız Root yeni flag yaradır."""

    def get(self, code: str) -> PermissionFlag | None: ...

    def list_all(self) -> list[PermissionFlag]: ...

    def create(self, flag: PermissionFlag, *, created_by: EmployeeId) -> None: ...


@runtime_checkable
class LeaveRequestRepository(Protocol):
    def get(self, request_id: LeaveRequestId) -> LeaveRequest | None: ...

    def find_open_for_employee(self, employee_id: EmployeeId) -> LeaveRequest | None:
        """Açıq (🔵/🟡) sorğu — ikinci STEP 1-i bloklayır."""
        ...

    def list_pending_verification(self, store_ids: list[StoreId]) -> list[LeaveRequest]:
        """Kamera Operatorunun növbəsi — YALNIZ təyin edilmiş mağazalar."""
        ...

    def list_due_for_timeout(
        self, tenant_id: TenantId, *, now: datetime, timeout_minutes: int
    ) -> list[LeaveRequest]: ...

    def list_pending_dual_control(self, tenant_id: TenantId) -> list[LeaveRequest]:
        """İkinci təsdiq gözləyən manual vaxt düzəlişləri (M-5).

        NİYƏ AYRICA SORĞU: `list_due_for_timeout` yalnız TƏSDİQ gözləyən
        icazələri gətirir (status 🟡). Düzəliş sorğusu isə icazə artıq
        təsdiqləndikdən sonra da gözləyə bilər — iki fərqli SLA, iki fərqli
        süzgəc. Birini digərinin üstünə yığmaq "hansı timeout işlədi?"
        sualını cavabsız qoyardı.

        Vaxt HƏDDİ arqument DEYİL: hansı sətrin köhnəldiyini
        `LeaveRequest.expire_override(now=, timeout_minutes=)` qərarlaşdırır,
        çünki hədd `system_limits`-dədir və Root onu gün ərzində dəyişə bilər
        (`break_overuse_for_day` ilə eyni əsaslandırma).
        """
        ...

    def monthly_used_minutes(self, employee_id: EmployeeId, *, year: int, month: int) -> int:
        """İşçinin həmin ay ərzində TƏSDİQLƏNMİŞ icazə dəqiqələrinin cəmi.

        `system_limits.MONTHLY_LEAVE_MINUTES_LIMIT` (defolt 240) ilə müqayisə
        üçün — bölmə 3 həmin limiti ROOT İdarə Mərkəzindən idarə olunan
        parametr kimi sadalayır və onu oxumaq üçün cəm lazımdır.

        YALNIZ `VERIFIED` sorğular sayılır: hələ təsdiqlənməmiş sorğunun
        faktiki müddəti məlum deyil (operator vaxtı əl ilə düzəldə bilər),
        ona görə açıq sorğunu cəmə qatmaq yanlış rəqəm verərdi.
        """
        ...

    def save(self, request: LeaveRequest) -> None: ...


@runtime_checkable
class RowLockingLeaveRequests(Protocol):
    """SƏTİR KİLİDLİ oxu — YALNIZ yazma axını üçün (yarış vəziyyəti qapağı).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ AYRICA PROTOKOL, `LeaveRequestRepository`-yə ƏLAVƏ SAHƏ DEYİL
    ──────────────────────────────────────────────────────────────────────────
    STEP 3-ü iki operator eyni anda təsdiqləyə bilir: `get()` → `verify()` →
    `save()` ardıcıllığında oxu ilə yazı arasında pəncərə var və hər iki
    tranzaksiya "status hələ 🟡-dir" görür. Nəticə İKİ ayrı cərimə sətri, yəni
    işçidən iki dəfə pul kəsilməsi olardı.

    Kilid `LeaveRequestRepository`-nin MƏCBURİ üzvü edilsəydi, portu artıq
    həyata keçirən hər tərəf (sahtə repo-lar, plugin-lər, gələcək oxu-yalnız
    adapterlər) sükutla sıradan çıxardı. Ona görə qabiliyyət AYRICA protokolla
    elan olunur: use case `isinstance` ilə soruşur, dəstəkləyən repo kilidli
    oxunu verir, dəstəkləməyən isə köhnə yolla işləməyə davam edir.

    Kilidsiz repo-da qoruma İTMİR — ikinci qat DB-dədir: `fines` üzərindəki
    qismən unikal indeks (miqrasiya 015) ikinci cəriməni onsuz da rədd edir.
    """

    def get_for_update(self, request_id: LeaveRequestId) -> LeaveRequest | None:
        """`SELECT ... FOR UPDATE` — sətri tranzaksiya sonuna qədər kilidləyir."""
        ...

    def find_open_for_employee_locked(self, employee_id: EmployeeId) -> LeaveRequest | None:
        """`find_open_for_employee`-nin STEP 2 (`claim_return`) üçün kilidli variantı
        (D-R2-02 audit tapıntısı, dövrə 2).

        STEP 2-də İKİ eyni-anlı çağırış (işçinin cihazda ikiqat toxunması / şəbəkə
        təkrarı) hər ikisi kilidsiz oxuda `OUTSIDE` görüb entity-səviyyəli
        `_require_status` qoruğunu KEÇƏ bilirdi — nəticə `LEAVE_RETURN_CLAIMED`-in
        İKİQAT audit yazısı VƏ `return_claimed_time`-ın son-commit-edən sorğuya
        görə qeyri-deterministik (last-write-wins) qalması idi; bu sahə isə
        `resolved_return_time()` vasitəsilə gecikmə/cərimə hesabına birbaşa
        daxil olur. STEP 3-ün (`get_for_update`) elə buradakı eyni əsaslandırması
        keçərlidir — YALNIZ açar fərqlidir (`request_id` deyil, `employee_id`,
        çünki STEP 2 anında sorğunun ID-si hələ çağırana ötürülmür)."""
        ...


@runtime_checkable
class AttendanceRepository(Protocol):
    def get(self, record_id: AttendanceRecordId) -> AttendanceRecord | None: ...

    def get_for_day(self, employee_id: EmployeeId, work_date: date) -> AttendanceRecord | None: ...

    def list_pending_verification(self, store_ids: list[StoreId]) -> list[AttendanceRecord]: ...

    def list_expected_on(self, tenant_id: TenantId, work_date: date) -> list[AttendanceRecord]:
        """ "İcazəsiz Qayıb" hesablaması üçün — planlaşdırılmış iş günləri."""
        ...

    def save(self, record: AttendanceRecord) -> None: ...


@runtime_checkable
class RowLockingAttendance(Protocol):
    """Morning Check-in yazma axını üçün sətir kilidli oxu.

    Eyni səbəb `RowLockingLeaveRequests`-dəki kimidir: STEP C-də `[Təsdiqlə]`
    və `[Rədd Et]` eyni sətrə yazır. Kilidsiz halda hər iki operator
    `PENDING_VERIFICATION` görür, hər ikisi audit yazır və DB-də yalnız
    SONUNCU status qalır — yəni audit jurnalı ilə faktiki status bir-birini
    təkzib edərdi. Kilid sayəsində ikinci operator təzə statusu oxuyur və
    `_require_record` onu audit yazılmamışdan ƏVVƏL bloklayır.
    """

    def get_for_day_for_update(
        self, employee_id: EmployeeId, work_date: date
    ) -> AttendanceRecord | None:
        """`SELECT ... FOR UPDATE` — günün qeydini kilidləyərək oxuyur."""
        ...


@runtime_checkable
class FineRepository(Protocol):
    def get(self, fine_id: FineId) -> Fine | None: ...

    def list_for_employee_month(
        self, employee_id: EmployeeId, *, year: int, month: int
    ) -> list[Fine]: ...

    def list_exportable(self, tenant_id: TenantId, *, now: datetime) -> list[Fine]:
        """Bölmə 6 LOCK MEXANİZMİ: pəncərə bağlı VƏ REVERSED deyil."""
        ...

    def save(self, fine: Fine) -> None:
        """D7 audit tapıntısı: `idempotency_key` doludursa VƏ eyni
        `(tenant_id, idempotency_key)` cütü ARTIQ mövcuddursa, implementasiya
        `DuplicateFineSubmissionError` atmalıdır (`fine_management.py`) —
        xam `UniqueViolation` YOX (`PostgresLeaveRequestRepository.save()`
        ilə EYNİ naxış)."""
        ...

    def get_by_idempotency_key(self, tenant_id: TenantId, key: UUID) -> Fine | None:
        """D7: `DuplicateFineSubmissionError` tutulduqdan SONRA mövcud
        cərimənin ÖZÜNÜ tapmaq üçün — `save()`-in atdığı istisna hansı sətrin
        toqquşduğunu daşımır, bu metod onu AYRICA sorğulayır."""
        ...


@runtime_checkable
class RangeScopedFineReader(Protocol):
    """Seçilmiş tarix aralığındakı BÜTÜN cərimələr (kompas1.md Faza 8).

    ──────────────────────────────────────────────────────────────────────────
    AYRI PROTOKOL, `FineRepository`-yə METOD ƏLAVƏSİ DEYİL
    ──────────────────────────────────────────────────────────────────────────
    `PlanFactProvider`-in Faza 7-dəki qərarı ilə EYNİ: mövcud protokola metod
    əlavə etmək onu ödəyən HƏR sinfi (o cümlədən testlərdəki sahtələri) dərhal
    uyğunsuz edərdi — halbuki icazə/cərimə axınının bu məlumata ehtiyacı
    yoxdur. Eyni repository sinfi hər iki protokolu ödəyir.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ SÜZGƏC YOXDUR — VƏ NİYƏ BU, LOCK-U ZƏİFLƏTMİR
    ──────────────────────────────────────────────────────────────────────────
    `list_exportable` üç şərti SQL-də tətbiq edir (status, pəncərə, əvvəlki
    export). Bu metod isə aralığa düşən HƏR cərimə sətrini qaytarır — çünki
    çağıran tərəf `MonthlyReportUseCase.build_bonus_penalty`-dir və o, üç
    KATEQORİYA hesablayır:

        * TUTULAN     — `Fine.is_exportable(now=...)` `True` deyir;
        * TƏXİRƏ SALINAN — 72 saatlıq etiraz pəncərəsi HƏLƏ AÇIQ
          (`open_appeal_count`);
        * ARTIQ TUTULMUŞ — `exported_period` doludur, üst-üstə düşən aralıq
          (`already_exported_count` + `already_exported_periods`).

    Son iki kateqoriya SQL-də kəsilsəydi, sayğaclar HƏMİŞƏ sıfır olardı və
    atlama SÜKUTLA baş verərdi — məhz `reporting.py` başlığının qadağan etdiyi
    hal ("ATLANMA SÜKUTLA BAŞ VERMİR").

    QƏRAR VERƏN YER DƏYİŞMİR: hansı cərimənin TUTULA BİLDİYİNİ yenə yalnız
    `Fine.is_exportable(now=...)` müəyyən edir. Bu metod yalnız «hansı
    cərimələrə BAXILIR» sualını cavablandırır (Struktur Qərar D).

    Aralıq `fine_date` üzrədir — cərimənin AİD OLDUĞU gün, yazıldığı an yox:
    gecikmiş yazılan cərimə hadisənin baş verdiyi dövrə düşməlidir.
    """

    def list_in_range(self, tenant_id: TenantId, *, start: date, end: date) -> list[Fine]: ...


@runtime_checkable
class LeaveTypeRepository(Protocol):
    def get_default_duration(self, leave_type_id: LeaveTypeId) -> int | None:
        """İcazə Növünün standart müddəti (BR-001 güzəşt mənbəyi)."""
        ...

    def list_all(self, tenant_id: TenantId, *, include_inactive: bool = False) -> list[LeaveType]:
        """Kataloq ekranı üçün. Defolt YALNIZ aktivlər — seçim siyahısı təhlükəsiz olsun."""
        ...

    def save(self, tenant_id: TenantId, entry: LeaveType, *, changed_by: EmployeeId) -> None: ...

    def deactivate(
        self, tenant_id: TenantId, leave_type_id: LeaveTypeId, *, changed_by: EmployeeId
    ) -> None:
        """SOFT DELETE — tarixi qeydlərə toxunmur (bölmə 4)."""
        ...

    def break_kind_of(self, leave_type_id: LeaveTypeId) -> BreakKind | None:
        """Seçilmiş icazə növü sistem fasiləsidirmi (`leave_types.break_kind`).

        STEP1 hansı sayğacı artıracağını məhz bundan öyrənir. `None` = adi
        icazə növü, sayğaca DÜŞMÜR (nahar.md: Nahar/Çay ümumi kataloqdan
        AYRI, xüsusi bir qatdır).

        NİYƏ `list_all()` ÜZƏRİNDƏN AXTARILMIR: STEP1 bir sətir üçün bütün
        kataloqu oxumamalıdır — tək açarla gedən sorğu həm ucuz, həm də
        deaktiv edilmiş növ üçün də doğru cavab verir (kataloq siyahısı
        defolt yalnız aktivləri gətirir).
        """
        ...


# --------------------------------------------------------------------------- #
# Nahar / Çay fasiləsinin gündəlik sayğacı (nahar.md)
# --------------------------------------------------------------------------- #


@runtime_checkable
class DailyBreakUsageRepository(Protocol):
    """`daily_break_usage` — gündə neçə dəfə fasilə başladığının sayğacı.

    ──────────────────────────────────────────────────────────────────────────
    BU PORT HEÇ NƏ BLOKLAMIR
    ──────────────────────────────────────────────────────────────────────────
    Say-həddi ROOT parametridir (`BreakAllowance`) və aşılma yalnız
    XƏBƏRDARLIQ doğurur (nahar.md §MƏNTİQ, bənd 2 — açıq göstəriş). Ona görə
    burada nə "artıra bilərəmmi?" sualı, nə də hədd arqumenti var: repository
    sayır, siyasət isə domendə qiymətləndirilir.
    """

    def record_use(
        self,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        *,
        kind: BreakKind,
        on_date: date,
        at: datetime,
    ) -> int:
        """Sayğacı BİR vahid artırır və YENİ dəyəri qaytarır.

        ATOMİK OLMALIDIR (UPSERT): iki kiosk terminalı eyni anda STEP1
        göndərsə, "oxu → artır → yaz" ardıcıllığı bir artımı itirərdi və
        işçi limitə çatmadan xəbərdarlıq görməzdi.

        Yeni dəyərin QAYTARILMASI da qəsdidir: çağıran tərəf ekranda dərhal
        "3-cü çay fasiləsi" yaza bilsin deyə ikinci sorğu ATMAMALIDIR —
        aralıqda başqa terminal sayğacı yenidən artıra bilər.
        """
        ...

    def count_for_day(self, employee_id: EmployeeId, *, kind: BreakKind, on_date: date) -> int:
        """Həmin gün üçün tək növün sayğacı (sətir yoxdursa 0)."""
        ...

    def usage_for_day(self, employee_id: EmployeeId, *, on_date: date) -> dict[BreakKind, int]:
        """Hər iki növün sayğacı — İşçi Ana Ekranı ikisini birlikdə göstərir.

        Sətri olmayan növ `0` ilə qaytarılır: ekran "məlumat yoxdur" ilə
        "hələ istifadə edilməyib" arasında fərq qoymamalıdır.
        """
        ...

    def usage_rows_for_day(
        self, tenant_id: TenantId, *, on_date: date
    ) -> list[tuple[EmployeeId, BreakKind, int]]:
        """HR panelinin gündəlik icmalı — kirayəçi üzrə bütün sayğaclar.

        HƏDD BURADA TƏTBİQ EDİLMİR: sorğu bütün sətirləri gətirir, aşılmanı
        isə `BreakAllowance.is_exceeded` müəyyən edir. Əks halda hədd İKİ
        yerdə — SQL-də və domendə — yaşayardı və Root dəyəri dəyişəndə biri
        arxada qalardı.
        """
        ...


# --------------------------------------------------------------------------- #
# Kataloqlar (bölmə 4) — İş Rejimləri & Cərimə Növləri
# --------------------------------------------------------------------------- #


@runtime_checkable
class WorkModeRepository(Protocol):
    """`can_manage_work_modes` ekranının məlumat mənbəyi."""

    def list_all(
        self, tenant_id: TenantId, *, include_inactive: bool = False
    ) -> list[WorkMode]: ...

    def get(self, work_mode_id: WorkModeId) -> WorkMode | None: ...

    def save(self, tenant_id: TenantId, entry: WorkMode, *, changed_by: EmployeeId) -> None: ...

    def deactivate(
        self, tenant_id: TenantId, work_mode_id: WorkModeId, *, changed_by: EmployeeId
    ) -> None: ...


@runtime_checkable
class FineTypeRepository(Protocol):
    """`can_manage_fine_types` ekranının məlumat mənbəyi.

    ANTİ-FRAUD: Kamera Operatorunun seçim siyahısı YALNIZ buradan gəlir —
    sərbəst məbləğ yazmaq mümkün deyil (bölmə 4).
    """

    def list_all(
        self, tenant_id: TenantId, *, include_inactive: bool = False
    ) -> list[FineType]: ...

    def get(self, fine_type_id: FineTypeId) -> FineType | None: ...

    def save(self, tenant_id: TenantId, entry: FineType, *, changed_by: EmployeeId) -> None: ...

    def deactivate(
        self, tenant_id: TenantId, fine_type_id: FineTypeId, *, changed_by: EmployeeId
    ) -> None: ...


# --------------------------------------------------------------------------- #
# Tapşırıqlar & satış xalları (bölmə 6)
# --------------------------------------------------------------------------- #


@runtime_checkable
class TaskRepository(Protocol):
    def get(self, task_id: TaskId) -> Task | None: ...

    def list_for_assignee(self, employee_id: EmployeeId, *, open_only: bool = True) -> list[Task]:
        """İşçinin öz tapşırıqları — İşçi Ana Ekranı və Tapşırıq Paneli."""
        ...

    def list_awaiting_review(self, tenant_id: TenantId) -> list[Task]:
        """`can_approve_task_evidence` sahibinin inbox-u."""
        ...

    def list_overdue(self, tenant_id: TenantId, *, now: datetime) -> list[Task]:
        """Eskalasiya planlayıcısının mənbəyi — yalnız hələ bildirilməmişlər."""
        ...

    def save(self, task: Task) -> None: ...


@runtime_checkable
class SalesPointsRepository(Protocol):
    def get(self, entry_id: PointsEntryId) -> PointsEntry | None: ...

    def list_for_employee(
        self, employee_id: EmployeeId, *, period: PointsPeriod
    ) -> list[PointsEntry]:
        """Dövr üzrə sətirlər — balans "cari dövrün cəmi"dir (bölmə 6)."""
        ...

    def list_disputes(self, tenant_id: TenantId) -> list[PointsEntry]:
        """YALNIZ `PENDING` etirazlar — MÜDDƏT-BİTMƏ işinin giriş siyahısı.

        `expire_stale_disputes` məhz bunu oxuyur: müddəti bitirmək YALNIZ hələ
        bağlanmamış sətirlərə aiddir. İDARƏÇİ İNBOX-U ÜÇÜN İSƏ BU METOD
        KİFAYƏT ETMİR — bax `list_undecided_disputes`.
        """
        ...

    def list_undecided_disputes(self, tenant_id: TenantId) -> list[PointsEntry]:
        """QƏRAR VERİLMƏMİŞ etirazlar — `PENDING` **və** `EXPIRED` (M-6).

        `FineAppealRepository.list_undecided()` ilə EYNİ naxış və EYNİ səbəb:
        `expire_stale_disputes` yalnız `PENDING` sətirləri axtarır, idarəçinin
        gələnlər qutusu isə müddəti bitmiş, LAKİN cavabsız qalmış sətirləri də
        GÖRMƏLİDİR. Əks halda `EXPIRED` sətir heç bir ekranda görünməzdi və
        `PointsEntry.has_undecided_dispute` ilə açıq saxlanılan qərar imkanı
        praktikada çatılmaz olardı — yəni bir ölü-son digəri ilə əvəzlənərdi.

        Sıra `points_appeals.created_at` üzrədir: ən çox gözləyən sətir
        siyahının BAŞINDA olmalıdır.
        """
        ...

    def save(self, entry: PointsEntry) -> None: ...


@runtime_checkable
class RewardRepository(Protocol):
    """Mükafat kataloqu + mübadilə qeydləri (bölmə 6)."""

    def list_rewards(
        self, tenant_id: TenantId, *, include_inactive: bool = False
    ) -> list[tuple[RewardId, RewardItem]]: ...

    def get_reward(self, reward_id: RewardId) -> RewardItem | None: ...

    def save_reward(self, tenant_id: TenantId, reward_id: RewardId, reward: RewardItem) -> None: ...

    def list_redemptions(
        self, tenant_id: TenantId, *, pending_only: bool = False
    ) -> list[RewardRedemption]: ...

    def get_redemption(self, redemption_id: RedemptionId) -> RewardRedemption | None: ...

    def save_redemption(self, redemption: RewardRedemption) -> None: ...


@runtime_checkable
class ShiftRepository(Protocol):
    def is_off_day(self, employee_id: EmployeeId, work_date: date) -> bool: ...

    def scheduled_start(self, employee_id: EmployeeId, work_date: date) -> datetime | None:
        """İş Rejiminə görə planlaşdırılmış başlanğıc — gecikmə hesablaması üçün."""
        ...

    def get_assignment(
        self, employee_id: EmployeeId, work_date: date
    ) -> ShiftAssignment | None: ...

    def schedules_for(
        self, employee_id: EmployeeId, days: tuple[date, date]
    ) -> dict[date, TimeRange]:
        """D10 audit tapıntısı: verilmiş İKİ gün üçün İş Rejiminin (`WorkMode`
        HƏLL OLUNMUŞ) `TimeRange`-ləri, BİR sorğuda.

        `MorningCheckInUseCase`-in gecə-növbəsi gün-təyini üçündür (bax
        `scheduling.resolve_work_date`): çağıran `(bugün, dünən)` cütünü
        verir, nəticə YALNIZ sabit saatlı (`WorkMode.schedule is not None`)
        VƏ iş günü olan (istirahət deyil) günləri ehtiva edir — digərləri
        sözlükdə YOXDUR (açar-yoxdursa "bu gün üçün əhatə sual doğurmur").

        NİYƏ İKİ AYRI `scheduled_start()` ÇAĞIRIŞI DEYİL: PERF-1/2/3 dərsi —
        iki gediş-gəliş əvəzinə bir sorğu (`shift_date IN (%s, %s)`).
        """
        ...

    def list_range(
        self,
        tenant_id: TenantId,
        *,
        start: date,
        end: date,
        store_id: StoreId | None = None,
        employee_ids: list[EmployeeId] | None = None,
    ) -> list[ShiftAssignment]:
        """Shift Matrix-in bir dövrü — mağaza/işçi üzrə süzülə bilər.

        Süzgəc parametrləri "canlı görünmə scopinqi" (bölmə 3) üçündür:
        işçi yalnız özünü, Store Manager öz filialını, HR bütün şəbəkəni görür.
        """
        ...

    def save_assignment(self, assignment: ShiftAssignment) -> None:
        """UPSERT — `(employee_id, shift_date)` unikaldır."""
        ...

    def clear_assignment(self, employee_id: EmployeeId, work_date: date) -> None:
        """Planı tamamilə silir (planlaşdırılmamış vəziyyətə qaytarır)."""
        ...


@runtime_checkable
class FineAppealRepository(Protocol):
    """`fine_appeals` — 72-saatlıq etiraz (bölmə 4).

    `get_for_fine()` ayrıca metoddur, çünki DB-də `UNIQUE (fine_id)` var:
    "bu cəriməyə artıq etiraz var?" sualı ən çox verilən sualdır və onu
    siyahı süzgəci ilə cavablandırmaq 21 filialın bütün etirazlarını
    oxumaq demək olardı.
    """

    def get(self, appeal_id: AppealId) -> FineAppeal | None: ...

    def get_for_fine(self, fine_id: FineId) -> FineAppeal | None: ...

    def list_pending(self, tenant_id: TenantId) -> list[FineAppeal]: ...

    def list_undecided(self, tenant_id: TenantId) -> list[FineAppeal]:
        """QƏRAR VERİLMƏMİŞ etirazlar — `PENDING` **və** `EXPIRED` (M-6).

        `list_pending`-dən FƏRQİ və niyə ikisi də lazımdır: `expire_stale`
        yalnız hələ bağlanmamış (`PENDING`) sətirləri axtarır, HR inbox-u isə
        müddəti bitmiş, lakin cavabsız qalmış sətirləri də GÖRMƏLİDİR — əks
        halda `EXPIRED` sətir heç bir ekranda görünməz, cərimə isə mübahisəli
        qalıb export-a düşməzdi (`Fine.is_exportable`). Yəni gizli, əbədi
        bloklanmış qeyd yaranardı.
        """
        ...

    def list_for_employee(self, employee_id: EmployeeId, *, limit: int) -> list[FineAppeal]:
        """İşçinin etiraz tarixçəsi — `limit` MƏCBURİ arqumentdir.

        DEFOLT DƏYƏR QƏSDƏN YOXDUR. Əvvəl `limit: int = 50` yazılmışdı və
        çağıran onu ötürmürdü: hədd faktiki qüvvədə idi, lakin nə Root
        panelində görünürdü, nə də dəyişdirilə bilirdi. İndi mənbə
        `SystemLimitKey.FINE_APPEAL_HISTORY_PAGE_SIZE`-dir və defoltun
        olmaması növbəti çağıranın onu unutmasının qarşısını alır — tip
        yoxlayıcısı dayandırır, sükutla keçmir.
        """
        ...

    def save(self, appeal: FineAppeal) -> None: ...


@runtime_checkable
class ShiftSwapRepository(Protocol):
    """`shift_swap_requests` (bölmə 3 — işçi-tərəfi self-service)."""

    def get(self, request_id: ShiftSwapRequestId) -> ShiftSwapRequest | None: ...

    def list_pending(
        self, tenant_id: TenantId, *, store_id: StoreId | None = None
    ) -> list[ShiftSwapRequest]: ...

    def list_for_employee(self, employee_id: EmployeeId, *, limit: int) -> list[ShiftSwapRequest]:
        """İşçinin sorğu tarixçəsi — `limit` MƏCBURİ (bax `FineAppealRepository`).

        Mənbə: `SystemLimitKey.SHIFT_SWAP_HISTORY_PAGE_SIZE`.
        """
        ...

    def find_open_for_date(
        self, employee_id: EmployeeId, target_date: date
    ) -> ShiftSwapRequest | None:
        """Eyni günə ikinci açıq sorğunun qarşısını almaq üçün."""
        ...

    def save(self, request: ShiftSwapRequest) -> None: ...


@runtime_checkable
class OpenShiftPostingRepository(Protocol):
    """`open_shift_postings` (#16 — açıq növbə bazarı, kompasos11.md Faza 6).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ ÜMUMİ `save()` YOXDUR
    ──────────────────────────────────────────────────────────────────────────
    Digər repo-larda naxış `save(aqreqat)` UPSERT-idir. Burada QƏSDƏN
    fərqlidir: statusu dəyişən hər keçidin ÖZ metodu var (`claim`, `cancel`)
    və hər ikisi ŞƏRTLİ `UPDATE` qaytarır (uğurlu/uğursuz).

    Səbəb yarışdır. `save(posting)` olsaydı, çağıran tərəf "oxu → dəyiş →
    yaz" ardıcıllığını qurardı; iki paralel işçi eyni elanı oxuyub HƏR İKİSİ
    `CLAIMED` yazardı və ikinci yazı birincinin `claimed_by` dəyərini
    ÜSTÜNDƏN yazardı. Metodun ÖZÜ şərti UPDATE olduqda bu səhvi etmək
    mümkün deyil — imza yanlış istifadəni struktur olaraq bağlayır.

    `post()` isə sadə INSERT-dir: yeni elan heç bir mövcud sətirlə yarışmır
    (eyni slot üçün ikinci açıq elanı DB-dəki qismən unikal indeks kəsir).
    """

    def get(self, posting_id: OpenShiftPostingId) -> OpenShiftPosting | None: ...

    def get_for_update(self, posting_id: OpenShiftPostingId) -> OpenShiftPosting | None:
        """`SELECT ... FOR UPDATE` — sətri tranzaksiya sonuna qədər kilidləyir.

        `get()` ekranların siyahı yolunda işlədilir; ona kilid qoymaq hər
        baxışı yazı-kilidinə çevirərdi (`RowLockingLeaveRequests` ilə eyni
        qərar).
        """
        ...

    def list_open(
        self,
        tenant_id: TenantId,
        *,
        store_id: StoreId | None = None,
        from_date: date | None = None,
        limit: int = 100,
    ) -> list[OpenShiftPosting]:
        """Açıq elanlar — işçinin gördüyü siyahı və admin panelinin mənbəyi."""
        ...

    def find_open_for_slot(
        self, tenant_id: TenantId, slot: OpenShiftSlot
    ) -> OpenShiftPosting | None:
        """Eyni slot üçün ikinci açıq elanın qarşısını almaq üçün."""
        ...

    def list_claimed(
        self,
        *,
        employee_id: EmployeeId | None = None,
        from_date: date | None = None,
        limit: int = 100,
    ) -> list[OpenShiftPosting]:
        """TUTULMUŞ elanlar — `[Geri Ver]` düyməsinin oxu yolu (OP-4).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ `list_open`-a PARAMETR ƏLAVƏ EDİLMƏDİ
        ──────────────────────────────────────────────────────────────────────
        `list_open` adı ilə şərtini birlikdə daşıyır (`WHERE status = 'OPEN'`)
        və onu `status` parametri ilə genişləndirmək adı yalana çevirərdi.
        Üstəlik indeksləri də FƏRQLİDİR: açıq elanlar
        `idx_open_shift_postings_open` (mağaza + tarix) ilə oxunur, tutulmuş
        sətirlər isə `uq_open_shift_one_claim_per_employee_day` (işçi + tarix)
        yolu ilə — bir metodda birləşdirilsəydi, sorğu planı çağırışdan asılı
        olaraq dəyişər və hansı indeksin işlədiyi görünməzdi.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ `tenant_id` ARQUMENTİ YOXDUR (bu portdakı DİGƏR metodlardan FƏRQLİ)
        ──────────────────────────────────────────────────────────────────────
        Kirayəçi süzgəci implementasiyada bağlantının ÖZ kontekstindən
        (`_BaseRepository._tenant`) gəlir. Bu, SAAS-1 istiqamətidir: `tenant_id`
        arqument BORCU yalnız AŞAĞI düşməlidir və yeni metod onu ARTIRA
        bilməz (`infrastructure/persistence/tenant_argument_audit.py`).
        Mövcud metodlar köhnə imza ilə qalır — onları köçürmək ayrı işdir.

        Args:
            employee_id: `None` = kirayəçidəki BÜTÜN tutulmuş elanlar (admin
                görünüşü); doludursa yalnız həmin işçinin tutduqları.
            from_date: `None` = tarix süzgəci YOXDUR. Çağıran tərəf «bugündən
                etibarən» qərarını ÖZÜ verir — bax `OpenShiftMarketUseCase.
                list_claimed_for_employee` şərhi (keçmiş növbəni geri vermək
                mənasızdır, LAKİN bu, repo-nun deyil, iş qaydasının qərarıdır).

        Returns:
            `CLAIMED` statuslu elanlar, `shift_date` üzrə ARTAN sırada — işçi
            ən yaxın növbəsini siyahının BAŞINDA görməlidir.
        """
        ...

    def count_claims_in_month(self, employee_id: EmployeeId, *, year: int, month: int) -> int:
        """İşçinin həmin ayda tutduğu elan sayı (aylıq tavan yoxlaması)."""
        ...

    def post(self, posting: OpenShiftPosting) -> None:
        """Yeni elanı YAZIR (INSERT) — mövcud sətri yeniləmir."""
        ...

    def claim(
        self,
        *,
        posting_id: OpenShiftPostingId,
        employee_id: EmployeeId,
        claimed_at: datetime,
    ) -> bool:
        """ŞƏRTLİ `UPDATE ... WHERE status = 'OPEN'`.

        Returns:
            `True` — bu çağırış yarışı UDDU; `False` — elan artıq bağlıdır
            (başqası tutub və ya ləğv edilib). İstisna ATILMIR: uduzmaq
            texniki nasazlıq deyil, axının NORMAL nəticəsidir və çağıran
            tərəf onu istifadəçi mesajına çevirir.
        """
        ...

    def cancel(
        self,
        *,
        posting_id: OpenShiftPostingId,
        cancelled_by: EmployeeId,
        cancelled_at: datetime,
        reason: str,
    ) -> bool:
        """ŞƏRTLİ `UPDATE` — yalnız HƏLƏ AÇIQ elan ləğv edilə bilər."""
        ...

    def release(
        self,
        *,
        posting_id: OpenShiftPostingId,
        released_by: EmployeeId,
        released_at: datetime,
    ) -> bool:
        """ŞƏRTLİ `UPDATE ... WHERE status = 'CLAIMED'` — tutma geri alınır (OP-4).

        `claimed_by`/`claimed_at` `NULL`-a çevrilir və status `OPEN` olur.
        `claim()` ilə EYNİ formadadır və eyni səbəbdən şərtlidir: geri buraxma
        ilə ləğv bir-biri ilə YARIŞIR (admin elanı ləğv edərkən işçi eyni anda
        geri verə bilər) və uduzan tərəf 0 sətir yeniləyib `False` almalıdır.

        `released_by` SƏTRƏ YAZILMIR — cədvəldə belə sütun YOXDUR və əlavə
        edilməsi də LAZIM DEYİL: geri buraxanın kimliyi audit sətrindədir
        (`OPEN_SHIFT_RELEASED`) və sətrin ÖZÜ yenidən `OPEN` olduğu üçün orada
        saxlanılsaydı `chk_open_shift_claim` invariantını pozardı. Parametr
        yalnız implementasiyanın öz jurnalı/izi üçün ötürülür.

        ⚠️ DB TƏLƏBİ: `migrations/019`-un `enforce_open_shift_claim_transition()`
        trigger-i hazırda (a) statusun `OPEN`-dən ÇIXMASINDAN başqa hər keçidi
        rədd edir, (b) `CLAIMED` sətirdə `claimed_by`-ı DONDURUR. Bu metodun
        işləməsi üçün trigger `CLAIMED → OPEN` keçidini (və yalnız həmin keçid
        zamanı `claimed_by`-ın `NULL`-a düşməsini) İCAZƏLİ etməlidir — qalan
        qadağalar OLDUĞU KİMİ qalmalıdır («ilk basan qazanır» zəmanəti
        `CLAIMED → CLAIMED` sahib dəyişikliyinə qarşıdır və o, POZULMAMALIDIR).

        Returns:
            Sətir HƏQİQƏTƏN geri buraxıldımı. `False` = elan artıq `CLAIMED`
            deyil (ləğv edilib və ya paralel geri buraxılıb).
        """
        ...

    def expire(self, *, posting_id: OpenShiftPostingId, expired_at: datetime) -> bool:
        """ŞƏRTLİ `UPDATE ... WHERE status = 'OPEN'` — tarixi keçmiş elanı bağlayır (OP-4).

        `cancel()`-DAN AYRI METODDUR və bu, qəsdəndir: `cancel()` İNSAN
        qərarıdır (`cancelled_by` MƏCBURİ, səbəb sərbəst mətn), bu isə
        AVTOMATİKDİR — aktoru YOXDUR. İkisini bir metoda yığmaq `cancelled_by:
        EmployeeId | None` demək olardı və o zaman İNSAN yolunda da `None`
        ötürmək mümkün olardı, yəni «kim ləğv etdi?» sualı sükutla cavabsız
        qala bilərdi.

        Sətrə `cancelled_by = NULL`, `cancelled_at = expired_at` və sabit
        `cancel_reason` (`open_shift.EXPIRED_CANCEL_REASON`) yazılır.

        ⚠️ DB TƏLƏBİ: `chk_open_shift_cancel` hazırda `cancelled_by IS NOT
        NULL` tələb edir. Şərt `cancelled_at IS NOT NULL`-a köklənməlidir —
        domendəki `_require_consistent_state()` ARTIQ belə yoxlayır (CLAUDE.md
        §5: hər qayda İKİ yerdə və eyni formada).

        Returns:
            Sətir bağlandımı. `False` = elan artıq `OPEN` deyil (paralel
            tutma/ləğv qabaqlayıb).
        """
        ...


# --------------------------------------------------------------------------- #
# Vahid İstisna Motoru (#9) — qayda müqaviləsi, jurnal və mənbə kataloqu
# --------------------------------------------------------------------------- #


@runtime_checkable
class ExceptionRule(Protocol):
    """İstisna Motoruna qoşulan BİR aşkarlama qaydası.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ BU PORT `ports.py`-DADIR
    ──────────────────────────────────────────────────────────────────────────
    Qayda yalnız DOMEN tipləri qaytarır (`ExceptionFinding`) və yalnız domen
    tipi qəbul edir (`RuleEvaluationContext`). Layihə qaydası budur: domen
    tipləri ilə işləyən port `ports.py`-a gedir; tətbiq qatının strukturunu
    qaytaran port (məs. `ReportFactProvider`) isə use case faylının yanında
    qalır. Qayda tətbiq qatında (Faza 5) həyata keçiriləcək, lakin `Protocol`
    strukturaldır — miras tələb olunmur, domen tətbiq qatını TANIMIR.

    ──────────────────────────────────────────────────────────────────────────
    QAYDANIN ÖHDƏLİKLƏRİ
    ──────────────────────────────────────────────────────────────────────────
    * `source_code` `exception_sources` kataloqundakı sətirlə EYNİ olmalıdır
      (`FOREIGN KEY`); əks halda motor tapıntını yazmadan atır və icra
      hesabatında "naməlum mənbə" kimi göstərir.
    * `evaluate()` YAZMIR — nə `exceptions`-a, nə audit-ə. Yazı, təkrar
      yoxlaması, ciddiyyət defoltu və bildiriş MOTORDADIR.
    * `evaluate()` `datetime.now()` çağırmır — vaxt `context.as_of`-dadır.
    * Bütün həddlər `context.limit_int(...)` ilə oxunur (`system_limits`).
    """

    @property
    def source_code(self) -> str:
        """`exception_sources.code` — reyestrin açarı (BÖYÜK hərflərlə)."""
        ...

    @property
    def name_az(self) -> str:
        """Qaydanın texniki adı — log/icra hesabatı üçün (Azərbaycanca).

        Ekranda görünən mənbə adı BURADAN GƏLMİR: o, `exception_sources.
        name_az` sütunundadır və Root onu redaktə edə bilir.
        """
        ...

    def evaluate(self, context: RuleEvaluationContext) -> list[ExceptionFinding]:
        """Bir kirayəçi üçün anomaliyaları hesablayır.

        Tapıntı yoxdursa BOŞ siyahı qaytarılır — `None` yox, çünki "heç nə
        tapılmadı" ilə "hesablaya bilmədim" fərqli hallardır və ikincisi
        istisna ilə bildirilməlidir.
        """
        ...


@runtime_checkable
class ExceptionRepository(Protocol):
    """`exceptions` — Vahid İstisna Jurnalı (#9).

    `delete()` YOXDUR və olmayacaq: DB-də `REVOKE DELETE` var (migrations/018),
    çünki rədd edilmiş istisna da "buna baxıldı və əsassız sayıldı" faktının
    sübutudur. Portda silmə metodu olsaydı, qadağa yalnız DB-də qalar və kodda
    "niyə işləmir?" sualı doğurardı.
    """

    def get(self, exception_id: ExceptionId) -> ExceptionRecord | None: ...

    def find_by_dedupe(
        self, tenant_id: TenantId, *, source: str, dedupe_key: str
    ) -> ExceptionRecord | None:
        """Təkrar-yaratma qapağı — `uq_exceptions_dedupe` indeksinin kod tərəfi.

        STATUSDAN ASILI DEYİL: bağlanmış (REVIEWED/DISMISSED) tapıntı da
        "artıq mövcuddur" sayılır, əks halda gecəlik icra rədd edilmiş
        istisnanı sabah yenidən açardı.
        """
        ...

    def list_open(
        self,
        tenant_id: TenantId,
        *,
        store_ids: list[StoreId] | None = None,
        limit: int = 200,
    ) -> list[ExceptionRecord]:
        """ "İstisnalar" ekranının əsas sorğusu — ən yenisi əvvəldə.

        `store_ids` mağaza-əhatəli görünmə üçündür (Mağaza Meneceri yalnız öz
        filialını görür). `None` = süzgəc yoxdur; BOŞ siyahı isə "heç bir
        mağazaya çıxışı yoxdur" deməkdir və heç nə qaytarmır (fail-safe).
        """
        ...

    def save(self, record: ExceptionRecord) -> None:
        """UPSERT — `ON CONFLICT (id)`."""
        ...


@runtime_checkable
class ExceptionSourceCatalog(Protocol):
    """`exception_sources` — genişlənə bilən mənbə kataloqu (#9).

    Yeni mənbə DDL-siz, bir `INSERT` ilə əlavə olunur; söndürmə isə
    `is_active = FALSE` ilə edilir (soft delete), çünki keçmiş istisnalar hansı
    qaydadan doğduğunu göstərə bilməlidir.
    """

    def get(self, tenant_id: TenantId, code: str) -> ExceptionSource | None: ...

    def list_all(
        self, tenant_id: TenantId, *, include_inactive: bool = False
    ) -> list[ExceptionSource]:
        """Ekranın mənbə-badge sözlüyü. Defolt YALNIZ aktivlər."""
        ...


# --------------------------------------------------------------------------- #
# #7 POS Səlahiyyət Siyasəti (sənədləşdirmə/siyasət qeydi, kompasos11.md Faza 4)
# --------------------------------------------------------------------------- #


@runtime_checkable
class POSThresholdRepository(Protocol):
    """`pos_permission_thresholds` — işçi başına BİR diri sətir (UPSERT).

    `delete()` YOXDUR və olmayacaq: DB-də `REVOKE DELETE` var
    (migrations/018) — səlahiyyət geri alınsa da (`POSPermissionThreshold.
    revoke()`) sətir SİLİNMİR, çünki "o gün bu işçinin hansı səlahiyyəti var
    idi?" sualı HR/audit araşdırmasında cavabsız qalmamalıdır.
    """

    def get_for_employee(
        self, tenant_id: TenantId, employee_id: EmployeeId
    ) -> POSPermissionThreshold | None:
        """İşçinin diri (aktiv və ya geri alınmış) hədd sətri."""
        ...

    def save(self, record: POSPermissionThreshold) -> None:
        """UPSERT — `ON CONFLICT (tenant_id, employee_id)`."""
        ...


# --------------------------------------------------------------------------- #
# #17 İşçi Sənədləri (kompasos11.md Faza 7)
# --------------------------------------------------------------------------- #


@runtime_checkable
class EmployeeDocumentRepository(Protocol):
    """`employee_documents` — bir işçinin BİRDƏN ÇOX sətri ola bilər.

    `delete()` YOXDUR: DB-də `REVOKE DELETE` var (migrations/020) — sənəd
    "keçmiş növbə təyinatının niyə icazəli olduğunu" sübut etdiyi üçün soft
    delete ilə idarə olunur (`EmployeeDocument.deactivate()`).
    """

    def get(self, document_id: EmployeeDocumentId) -> EmployeeDocument | None: ...

    def list_for_employee(
        self, tenant_id: TenantId, employee_id: EmployeeId, *, include_inactive: bool = False
    ) -> list[EmployeeDocument]:
        """İşçi redaktə ekranının "Sənədlər" bölməsi — ən yenisi əvvəldə."""
        ...

    def list_blocking_for_employee(
        self, tenant_id: TenantId, employee_id: EmployeeId
    ) -> list[EmployeeDocument]:
        """Aktiv, `is_blocking=TRUE` sətirlər — Shift Matrix konflikt yoxlaması
        üçün (`idx_employee_documents_blocking`, migrations/020).
        """
        ...

    def list_expiring(self, tenant_id: TenantId, *, on_or_before: date) -> list[EmployeeDocument]:
        """Aktiv, bitmə tarixi `on_or_before`-a qədər olan sətirlər —
        bitmə xəbərdarlığı üçün (`idx_employee_documents_expiring`).
        """
        ...

    def save(self, record: EmployeeDocument) -> None:
        """UPSERT — `id` ilə (işçi başına çox sətir ola bildiyi üçün `id`
        `pos_permission_thresholds`-dəki `(tenant_id, employee_id)`-dən
        fərqli olaraq TƏK konflikt açarıdır).
        """
        ...


# --------------------------------------------------------------------------- #
# #26+#27 Sahə hesabatları (kompas1.md Faza 3)
# --------------------------------------------------------------------------- #


@runtime_checkable
class FieldReportCatalog(Protocol):
    """`field_report_types` + `field_report_categories` — genişlənmə nöqtəsi.

    İKİ CƏDVƏL, TƏK PORT: hər ikisi EYNİ suala xidmət edir ("forma açılanda
    nə göstərilsin?") və hər ikisi eyni tranzaksiyada, eyni sətir tərəfindən
    oxunur. Ayrı portlar `composition.py`-da iki qeydiyyat, use case-də iki
    arqument yaradardı — halbuki heç bir çağıran birini digərisiz işlətmir
    (`ExceptionSourceCatalog`-un tək port olması ilə eyni əsaslandırma).

    `save()`/`delete()` YOXDUR: kataloq sətirləri `migrations/037` ilə seed
    edilir və Root onları GUI-dan deyil, sətir səviyyəsində idarə edir
    (`ExceptionSourceCatalog` ilə eyni sərhəd). Söndürmə `is_active = FALSE`
    ilədir — keçmiş hesabatlar hansı formadan doğduğunu göstərə bilməlidir.
    """

    def get_template(self, tenant_id: TenantId, code: str) -> FieldReportTemplate | None:
        """Şablon (`STORE_AUDIT`, `INCIDENT`, ...) — `None` = naməlum kod."""
        ...

    def list_templates(
        self, tenant_id: TenantId, *, include_inactive: bool = False
    ) -> list[FieldReportTemplate]:
        """Forma seçicisinin siyahısı. Defolt YALNIZ aktivlər."""
        ...

    def get_category(self, tenant_id: TenantId, code: str) -> FieldReportCategory | None:
        """Kateqoriya — marşrutlama qaydası (`route_to_role`) buradan oxunur."""
        ...

    def list_categories(
        self,
        tenant_id: TenantId,
        *,
        report_type: str | None = None,
        include_inactive: bool = False,
    ) -> list[FieldReportCategory]:
        """`idx_field_report_categories_type` indeksinin sorğusu.

        `report_type=None` = bütün şablonların kateqoriyaları (Root/hesabat
        ekranı üçün); dolu dəyər isə forma açılışının sorğusudur.
        """
        ...


@runtime_checkable
class FieldReportRepository(Protocol):
    """`field_reports` + `field_report_checklist_items` — VAHİD aqreqat.

    Checklist bəndləri üçün AYRI port YOXDUR: bənd valideyn hesabatsız
    mənasızdır (birləşmiş FK `(tenant_id, report_id)`, `ON DELETE CASCADE`)
    və `save()` hesabatı bəndləri ilə birlikdə yazır — aqreqat sərhədi
    məhz budur.

    `delete()` YOXDUR: DB-də `REVOKE DELETE` var (migrations/037) — insident
    hesabatı mübahisədə SÜBUTDUR, rədd edilmiş (`DISMISSED`) olsa belə.
    """

    def get(self, report_id: FieldReportId) -> FieldReport | None: ...

    def find_by_item(self, tenant_id: TenantId, item_id: FieldReportItemId) -> FieldReport | None:
        """Checklist bəndinin İD-si ilə VALİDEYN hesabatı tapır.

        Asinxron yükləmə geri-çağırışı üçün: növbə yalnız `owner_id` daşıyır
        və bəndə aid foto üçün o, bəndin İD-sidir. Aqreqat sərhədi
        pozulmasın deyə bənd TƏK BAŞINA qaytarılmır — bütün hesabat
        yüklənir, dəyişiklik `save()` ilə birlikdə yazılır.
        """
        ...

    def list_open(
        self,
        tenant_id: TenantId,
        *,
        store_ids: list[StoreId] | None = None,
        report_type: str | None = None,
        limit: int = 200,
    ) -> list[FieldReport]:
        """`idx_field_reports_open` sorğusu — ən yenisi əvvəldə.

        `store_ids` mağaza-əhatəli görünmə üçündür (Mağaza Meneceri yalnız
        öz filialını görür). `None` = süzgəc yoxdur; BOŞ siyahı isə "heç bir
        mağazaya çıxışı yoxdur" deməkdir və heç nə qaytarmır (fail-safe,
        `ExceptionRepository.list_open` ilə eyni qərar).
        """
        ...

    def save(self, report: FieldReport) -> None:
        """UPSERT — hesabat `ON CONFLICT (id)`, bəndlər isə ayrı-ayrılıqda."""
        ...

    def list_route_recipients(
        self, tenant_id: TenantId, *, role_code: str, store_id: StoreId | None = None
    ) -> list[EmployeeId]:
        """Rol kodunu AKTİV işçilərə çevirir (#27 marşrutu + düzəliş tapşırığı).

        FK YOXDUR (migrations/037: `positions.code` yalnız kirayəçi daxilində
        unikaldır), ona görə mövcudluğu MƏHZ BU sorğu yoxlayır: naməlum rol
        BOŞ siyahı qaytarır — istisna ATMIR. Səbəb: Root kataloqda rol adını
        səhv yazsa, insident bildirişi ÜMUMİYYƏTLƏ yazıla bilməzdi; boş
        siyahı isə use case-i ehtiyat yoluna salır.

        `store_id` düzəliş tapşırığı üçündür: mağaza rəhbəri ŞƏBƏKƏ üzrə
        deyil, HƏMİN filial üzrə axtarılır — əks halda 21 filialın bütün
        menecerləri bir mağazanın uğursuz bəndi üçün tapşırıq alardı.
        """
        ...

    def stores_missing_audit(
        self, tenant_id: TenantId, *, now: datetime, interval_days: int
    ) -> list[StoreAuditGap]:
        """Sonuncu auditi `interval_days`-dən köhnə (və ya HEÇ OLMAYAN) filiallar.

        Şablon süzgəci KODA YAZILMIR: sorğu `field_report_types.
        requires_checklist` sütununa baxır — yəni gələcəkdə əlavə edilən
        checklist-li şablon (məs. "Təchizat yoxlaması") də avtomatik "audit"
        sayılır və bu metod dəyişmir (Struktur Qərar A).

        `now` ARQUMENTDİR, DB-nin `now()` funksiyası DEYİL: vaxt mənbəyi
        `Clock` portudur (CLAUDE.md §4) — əks halda gecəlik iş determinstik
        test edilə bilməzdi. `days_since` də həmin ana görə hesablanır.
        """
        ...


# --------------------------------------------------------------------------- #
# #28 İllik Məzuniyyət Balansı (kompas1.md Faza 4)
# --------------------------------------------------------------------------- #


@runtime_checkable
class AnnualLeaveBalanceRepository(Protocol):
    """`annual_leave_balances` — İLLİK haqq (migrations/037).

    ──────────────────────────────────────────────────────────────────────────
    `LeaveRequestRepository` İLƏ QARIŞDIRILMAMALIDIR
    ──────────────────────────────────────────────────────────────────────────
    O port GÜNDAXİLİ icazənin (STEP1/STEP2, dəqiqə əsaslı) sətirlərini idarə
    edir və `monthly_used_minutes()` metodu aylıq 240 dəqiqəlik tavana aiddir.
    Bu port isə GÜN əsaslı illik haqqı idarə edir və həmin tavanla heç bir
    əlaqəsi yoxdur (bax `entities/annual_leave.py` başlığı).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ ÜMUMİ `save()` YOXDUR
    ──────────────────────────────────────────────────────────────────────────
    `OpenShiftPostingRepository` ilə EYNİ qərar və eyni səbəb: `save(balance)`
    imzası çağıran tərəfi "oxu → dəyiş → yaz" naxışına dəvət edərdi və məhz
    bu naxış yarışı UDUZUR — iki paralel təsdiq eyni `used_days` dəyərini
    oxuyub hər ikisi "kifayətdir" deyərdi, ikinci yazı isə birincinin
    çıxdığı günü üstündən yazardı. Ona görə balansı dəyişdirən hər əməliyyat
    ŞƏRTLİ `UPDATE`-dir və uğur/uğursuzluq qaytarır.
    """

    def get(self, employee_id: EmployeeId, *, year: int) -> AnnualLeaveBalance | None: ...

    def list_for_year(
        self, tenant_id: TenantId, *, year: int, limit: int = 500
    ) -> list[AnnualLeaveBalance]:
        """HR panelinin "bu ilin balansları" siyahısı (`idx_..._year` sorğusu)."""
        ...

    def set_entitlement(
        self,
        *,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        year: int,
        entitled_days: Decimal,
        carried_over_days: Decimal,
        updated_by: EmployeeId | None,
    ) -> bool:
        """İDEMPOTENT UPSERT — haqqı TƏYİN edir, ARTIRMIR.

        `ON CONFLICT (tenant_id, employee_id, year) DO UPDATE SET ... = EXCLUDED
        ...` naxışı: il dönümü işi at-least-once icra olunur (bax `job_runner.py`
        başlığı) və `+=` yazılsaydı ikinci icra balansı ikiqat artırardı.

        `updated_by is None` = SİSTEM (planlaşdırılmış iş). Bu, sadəcə boş
        sütun deyil — ƏL İLƏ edilmiş düzəlişi qorumaq üçün şərtdir: sistem
        yazısı yalnız `updated_by IS NULL` olan sətri yeniləyir, yəni HR-ın
        düzəltdiyi rəqəm gecə işi tərəfindən sükutla geri qaytarılmır.

        Returns:
            Sətir yaradıldı/yeniləndimi. `False` = əl ilə düzəlişə toxunulmadı.
        """
        ...

    def consume(self, *, employee_id: EmployeeId, year: int, days: Decimal) -> bool:
        """ŞƏRTLİ `UPDATE` — balans mənfiyə DÜŞƏ BİLMƏZ (yarış qapağı).

        Şərt (`used_days + %s <= entitled_days + carried_over_days`) SORĞUNUN
        İÇİNDƏDİR: onu Python-da yoxlamaq oxu ilə yazı arasında pəncərə
        qoyardı və iki paralel təsdiqin HƏR İKİSİ keçərdi
        (`open_shift_repository.claim` ilə hərfən eyni naxış).

        Returns:
            `True` = bir sətir yeniləndi. `False` = balans çatmır VƏ YA sətir
            yoxdur — çağıran tərəf ikisini fərqləndirmək üçün `get()` edir.
        """
        ...

    def release(self, *, employee_id: EmployeeId, year: int, days: Decimal) -> bool:
        """Ləğv edilmiş məzuniyyətin gününü geri qaytarır (şərti `UPDATE`).

        `GREATEST(0, used_days - %s)` işlədilir: təkrar ləğv (və ya
        planlayıcının təkrar icrası) `used_days`-i mənfiyə salmamalıdır.
        """
        ...

    def expire_carryover(self, *, tenant_id: TenantId, year: int) -> int:
        """ "İstifadə et ya itir" — istifadə olunmamış köçürməni sıfırlayır.

        `SET carried_over_days = LEAST(carried_over_days, used_days)` —
        İDEMPOTENTDİR (ikinci icrada heç nə dəyişmir) və `used_days <=
        entitled_days + carried_over_days` `CHECK`-ini poza bilmir.

        Returns:
            Toxunulan sətir sayı (`rowcount`) — iş hesabatının rəqəmi.
        """
        ...

    def list_rollover_inputs(
        self, tenant_id: TenantId, *, year: int
    ) -> list[AnnualLeaveRolloverInput]:
        """İl dönümü işinin girişi: AKTİV işçi + işə qəbul + KEÇƏN ilin qalığı.

        Aqreqasiya SQL-dədir (`entitled + carried_over - used`), çünki 235
        işçinin sətrini yaddaşa gətirib Python-da çıxmaq gecə işi üçün
        mənasız yükdür (`count_claims_in_month` ilə eyni qərar).

        KEÇƏN İL SƏTRİ OLMAYAN işçi də qayıdır (qalığı sıfır) — əks halda
        yeni işə düşən işçinin bu il üçün balansı HEÇ VAXT yaranmazdı.
        """
        ...


@runtime_checkable
class AnnualLeaveRequestRepository(Protocol):
    """`annual_leave_requests` — sorğu və təsdiqi (migrations/037).

    `save()` UPSERT-dir (`ShiftSwapRepository` naxışı), çünki sorğunun
    statusu bir aqreqat daxilində dəyişir və yarış nöqtəsi burada DEYİL —
    o, balansdadır. Üst-üstə düşən TƏSDİQLƏNMİŞ aralıqları isə DB `EXCLUDE
    USING gist` qapağı kəsir; repo həmin pozuntunu tutub AZƏRBAYCAN DİLİNDƏ
    izaha çevirməlidir, xam `psycopg` xətası ekrana çıxmamalıdır.
    """

    def get(self, request_id: AnnualLeaveRequestId) -> AnnualLeaveRequest | None: ...

    def get_for_update(self, request_id: AnnualLeaveRequestId) -> AnnualLeaveRequest | None:
        """`SELECT ... FOR UPDATE` — YALNIZ yazma axını üçün.

        `get()` siyahı/ekran yollarında işlədilir; ona kilid qoymaq hər
        baxışı yazı-kilidinə çevirərdi (`RowLockingLeaveRequests` ilə eyni
        qərar).
        """
        ...

    def list_pending(self, tenant_id: TenantId, *, limit: int = 200) -> list[AnnualLeaveRequest]:
        """`idx_annual_leave_requests_pending` sorğusu — ən erkən başlayan əvvəldə."""
        ...

    def list_for_employee(
        self, employee_id: EmployeeId, *, limit: int = 50
    ) -> list[AnnualLeaveRequest]:
        """İşçi profilindəki "məzuniyyət tarixçəsi" (`idx_..._employee`)."""
        ...

    def find_overlapping_approved(
        self, employee_id: EmployeeId, *, start: date, end: date
    ) -> AnnualLeaveRequest | None:
        """`EXCLUDE` qapağının OXU tərəfi — istifadəçiyə erkən xəbərdarlıq.

        Qapağı ƏVƏZ ETMİR: paralel iki təsdiqdə bu yoxlama uduzur və qərarı
        DB verir (bax `save()`). Məqsədi yalnız odur ki, normal halda
        istifadəçi səbəbi FORMANI DOLDURMAZDAN ƏVVƏL görsün.
        """
        ...

    def save(self, request: AnnualLeaveRequest) -> None:
        """UPSERT (`ON CONFLICT (id) DO UPDATE`).

        Raises:
            KompasOSError: `excl_annual_leave_no_overlap` pozulduqda — xam
                DB xətası deyil, izah edilmiş Azərbaycan dilində mesaj.
        """
        ...


# --------------------------------------------------------------------------- #
# #29 Toplu Əməliyyatlar (kompas1.md Faza 5)
# --------------------------------------------------------------------------- #


@runtime_checkable
class BulkImportLogRepository(Protocol):
    """`bulk_import_log` (migrations/037) — HƏR toplu əməliyyatın AQREQAT izi.

    İKİ-FAZALI YAZI QƏSDƏNDİR (bax `application/use_cases/bulk_operations.py`
    başlığı, "TRANZAKSİYA SƏRHƏDİ"): `start()` əməliyyat BAŞLAYANDA
    `finished_at = NULL` ilə sətir açır, `finish()` isə sonda YEKUN rəqəmləri
    yazır. Proses arada çökərsə sətir `finished_at = NULL` qalır — bu, GİZLİ
    DEYİL, Root panelində "yarımçıq qalıb" kimi görünür (bax `chk_bulk_import_
    counts`/`finished_at` şərhi, migrations/037).

    `DELETE` heç vaxt YOXDUR: cədvəldə `REVOKE DELETE` var (audit qeydidir).
    """

    def start(
        self,
        *,
        log_id: BulkImportLogId,
        tenant_id: TenantId,
        import_type: str,
        performed_by: EmployeeId,
        file_ref: str | None,
        row_count: int,
        performed_at: datetime,
    ) -> None: ...

    def finish(
        self,
        *,
        log_id: BulkImportLogId,
        success_count: int,
        error_count: int,
        error_summary: str | None,
        finished_at: datetime,
    ) -> None: ...

    def list_recent(self, tenant_id: TenantId, *, limit: int = 50) -> list[dict[str, object]]:
        """Root panelinin "son toplu əməliyyatlar" siyahısı (`idx_bulk_import_log_recent`).

        `dict` qaytarır, tam entity DEYİL: bu, YALNIZ-OXU hesabat sətridir,
        heç bir domen qaydası daşımır (`WorkModeCatalogUseCase.list_for_
        management`-dən fərqli olaraq buranın yazma tərəfi YOXDUR).
        """
        ...


@runtime_checkable
class StoreTemplateRepository(Protocol):
    """`store_templates` (migrations/037) — bax `StoreTemplate` başlığı.

    `save()` YALNIZ YARADIR (`ON CONFLICT (id) DO NOTHING` naxışı): şablon
    yarandıqdan sonra `config_snapshot` DƏYİŞMİR — yeni versiya YENİ şablon
    kimi qeydə alınır (`export_manual_corrections`-dakı "düzəliş YENİ sətirdir"
    qaydası ilə eyni ruh, migrations/037 başlığı).
    """

    def get(self, template_id: StoreTemplateId) -> StoreTemplate | None: ...

    def list_for_tenant(
        self, tenant_id: TenantId, *, include_inactive: bool = False
    ) -> list[StoreTemplate]: ...

    def save(self, tenant_id: TenantId, entry: StoreTemplate) -> None: ...

    def deactivate(
        self, tenant_id: TenantId, template_id: StoreTemplateId, *, changed_by: EmployeeId
    ) -> None: ...


# --------------------------------------------------------------------------- #
# #30 Planlaşdırılmış İcra Xülasəsi (kompas1.md Faza 6)
# --------------------------------------------------------------------------- #


@runtime_checkable
class ExecutiveDigestConfigRepository(Protocol):
    """`executive_digest_config` — kimə, nə tezlikdə, hansı metriklərlə.

    `list_route_recipients` `FieldReportRepository`-dəkinin AYRI NÜSXƏSİDİR
    (bilərəkdən — bax `infrastructure/persistence/executive_digest_
    repository.py` başlığı): iki bounded-context bir-birini ÇAĞIRMIR, kiçik
    sorğu təkrarı bunun ödənişidir.
    """

    def get(self, config_id: ExecutiveDigestConfigId) -> ExecutiveDigestConfig | None: ...

    def list_for_tenant(
        self, tenant_id: TenantId, *, include_inactive: bool = False
    ) -> list[ExecutiveDigestConfig]:
        """İdarəetmə ekranı (`include_inactive=True`) VƏ planlayıcı
        (`include_inactive=False`) EYNİ metoddan bəslənir."""
        ...

    def save(self, entry: ExecutiveDigestConfig) -> ExecutiveDigestConfig:
        """UPSERT — `ON CONFLICT (tenant_id, recipient_role, frequency)`.

        Yaradılmış/yenilənmiş sətri (DB-nin verdiyi `id` daxil) qaytarır —
        çağıran tərəf yeni sətrin İD-sini AYRICA sorğu ilə axtarmamalıdır.
        """
        ...

    def deactivate(
        self, tenant_id: TenantId, config_id: ExecutiveDigestConfigId, *, changed_by: EmployeeId
    ) -> None: ...

    def mark_sent(
        self, tenant_id: TenantId, config_id: ExecutiveDigestConfigId, *, sent_at: datetime
    ) -> None:
        """`last_sent_at`-i yeniləyir — planlayıcının TƏKRAR-GÖNDƏRMƏ qapısı
        (bax `application/use_cases/executive_digest.py` başlığı)."""
        ...

    def list_route_recipients(self, tenant_id: TenantId, *, role_code: str) -> list[EmployeeId]:
        """Rol kodunu AKTİV işçilərə çevirir (`FieldReportRepository.
        list_route_recipients` ilə EYNİ sorğu naxışı, `store_id` süzgəci
        YOXDUR: xülasə mağaza-səviyyəli deyil, şəbəkə-miqyaslıdır)."""
        ...


# --------------------------------------------------------------------------- #
# HR-D Export düzəlişləri (kompas1.md Faza 8)
# --------------------------------------------------------------------------- #


@runtime_checkable
class ExportCorrectionRepository(Protocol):
    """`export_manual_corrections` (migrations/037 §10).

    NİYƏ `update()`/`delete()` YOXDUR — VƏ BU, UNUDULMA DEYİL: miqrasiya həmin
    iki hüququ tətbiq rolundan AÇIQ ŞƏKİLDƏ geri alır ("düzəlişin özü düzəldilə
    bilsəydi, kim nəyi nəyə dəyişdi izi geri yazıla bilərdi"). Portda belə bir
    metod olsaydı, o, hər çağırışda DB xətası ilə bitərdi — yəni müqavilə
    yalan danışardı. Yenidən düzəliş `save()`-in YENİ sətridir.

    `list_for_range` `tenant_id`-ni AÇIQ arqument kimi alır (RLS-ə ƏLAVƏ ikinci
    qat, CLAUDE.md §6) və `export_type` ilə süzülür: davamiyyət faylının
    düzəlişi premiya faylına tətbiq olunmamalıdır.
    """

    def save(self, entry: ExportCorrection) -> None:
        """Yeni düzəliş sətrini YAZIR — mövcud sətri YENİLƏMİR."""
        ...

    def list_for_range(
        self,
        tenant_id: TenantId,
        *,
        export_type: str,
        start: date,
        end: date,
    ) -> list[ExportCorrection]:
        """Aralığa düşən düzəlişlər — `corrected_at` üzrə ARTAN sırada.

        Sıra MÜQAVİLƏNİN BİR HİSSƏSİDİR, təsadüf deyil: eyni sahəyə bir neçə
        düzəliş varsa, SONUNCU qalib gəlir (`export_preflight.apply_
        corrections`). Sıra qeyri-müəyyən olsaydı, tətbiq olunan dəyər hər
        oxuda dəyişə bilərdi.
        """
        ...


# --------------------------------------------------------------------------- #
# #19 Elan (Broadcast) (kompasos11.md Faza 8)
# --------------------------------------------------------------------------- #


@runtime_checkable
class AnnouncementRepository(Protocol):
    """`announcements` + `announcement_targets` (#19).

    NİYƏ ÜMUMİ `save()` YOXDUR: `post()` sadə INSERT-dir (parent sətir +
    hədəf sətirləri — bax `OpenShiftPostingRepository.post` eyni qərarı),
    `withdraw()` isə YALNIZ soft-delete sahələrini toxunan ŞƏRTLİ UPDATE-dir.
    Elanın MƏTNİ/ƏHATƏSİ yaradıldıqdan sonra DƏYİŞMİR (yeni elan tələb edir) —
    ona görə "redaktə" metodu ÜMUMİYYƏTLƏ yoxdur.
    """

    def get(self, tenant_id: TenantId, announcement_id: AnnouncementId) -> Announcement | None: ...

    def list_recent(self, tenant_id: TenantId, *, limit: int = 50) -> list[Announcement]:
        """Admin panelinin siyahısı — YARADAN görür, əhatədən ASILI OLMADAN."""
        ...

    def list_visible_for_store(
        self, tenant_id: TenantId, store_id: StoreId | None, *, created_after: datetime
    ) -> list[Announcement]:
        """İşçi Ana Ekranının store-scoping oxusu (#19).

        `store_id=None` — yalnız `scope=ALL` elanlar qayıdır (mağazası
        olmayan işçi `STORE_LIST` elanlarını görmür, bax `Announcement.
        visible_to_store` başlığı).
        """
        ...

    def post(self, record: Announcement) -> None:
        """Yeni elanı yazır (parent + hədəf sətirləri) — YENİLƏMİR."""
        ...

    def withdraw(
        self,
        *,
        tenant_id: TenantId,
        announcement_id: AnnouncementId,
        deactivated_by: EmployeeId,
        deactivated_at: datetime,
    ) -> bool:
        """ŞƏRTLİ `UPDATE ... WHERE is_active` — artıq geri çəkilmiş sətri
        ikinci dəfə "geri çəkməyin" qarşısını alır. Təsir olunub-olunmadığını
        qaytarır (`OpenShiftPostingRepository.cancel` ilə eyni naxış).
        """
        ...


# --------------------------------------------------------------------------- #
# #20 Performans Qiymətləndirməsi (kompasos11.md Faza 8)
# --------------------------------------------------------------------------- #


@runtime_checkable
class PerformanceReviewRepository(Protocol):
    """`performance_reviews` — bir işçi + bir dövr = BİR sətir (UNIQUE)."""

    def get(
        self, tenant_id: TenantId, employee_id: EmployeeId, period: str
    ) -> PerformanceReview | None:
        """Eyni dövr üçün MÖVCUD sətri tapır — UPSERT-in "oxu" tərəfi."""
        ...

    def list_for_employee(
        self, tenant_id: TenantId, employee_id: EmployeeId
    ) -> list[PerformanceReview]:
        """İşçinin ÖZ tarixçəsi (Profil ekranı) və reviewer-in keçmiş dövrlər
        siyahısı — dövr azalan sırada (ən yenisi əvvəldə).
        """
        ...

    def save(self, record: PerformanceReview) -> None:
        """UPSERT — `ON CONFLICT (tenant_id, employee_id, period)`
        (`pos_permission_thresholds` ilə EYNİ naxış: `id` yeniləmədə
        toxunulmur, sətrin identifikatoru daimi qalır).
        """
        ...


# --------------------------------------------------------------------------- #
# #8 İşçi Davranış Baz Xətti (kompasos11.md Faza 5)
# --------------------------------------------------------------------------- #


@runtime_checkable
class BehaviorBaselineRepository(Protocol):
    """`employee_behavior_baseline` — işçi başına BİR törəmə sətir (#8).

    `delete()` VAR (digər Faza 5 repo-larından fərqli olaraq): migrations/018
    bu cədvələ tam `GRANT ... DELETE` verir, çünki sətir "tam törəmə
    məlumatdır" — işçi profili silinərkən (CASCADE) və ya köhnəlmiş baz
    xəttini təmizləyərkən itkisi sübut itkisi DEYİL, `attendance_records`-dan
    istənilən an yenidən hesablana bilər.
    """

    def get_for_employee(
        self, tenant_id: TenantId, employee_id: EmployeeId
    ) -> BehaviorBaseline | None: ...

    def list_for_tenant(self, tenant_id: TenantId) -> list[BehaviorBaseline]:
        """`BehaviorAnomalyRule`-un "bütün işçilər üçün adət" sorğusu."""
        ...

    def save(self, baseline: BehaviorBaseline) -> None:
        """UPSERT — `ON CONFLICT (tenant_id, employee_id)`."""
        ...


# --------------------------------------------------------------------------- #
# #21 İşdən Çıxma Riski Balı (kompasos11.md Faza 9)
# --------------------------------------------------------------------------- #


@runtime_checkable
class AttritionRiskScoreRepository(Protocol):
    """`attrition_risk_scores` — GÜNLÜK tarixçə (#21).

    Bura QAYTARILAN `AttritionRiskScore` SAF DOMEN TİPİDİR (`domain.
    attrition_rules`), ona görə port `ports.py`-dadır — xam siqnal yığımı isə
    tətbiq qatının strukturunu (`EmployeeAttritionSignals`) qaytardığı üçün
    `application.use_cases.attrition_risk`-in ÖZÜNDƏ təyin olunur
    (`ReportFactProvider` naxışı, CLAUDE.md — "port tətbiq qatının
    strukturunu qaytarırsa use case faylının yanında təyin olunur").
    """

    def save(self, score: AttritionRiskScore) -> None:
        """UPSERT — `ON CONFLICT (tenant_id, employee_id, score_date)`."""
        ...

    def get_latest_for_employee(
        self, tenant_id: TenantId, employee_id: EmployeeId
    ) -> AttritionRiskScore | None:
        """Ən son (ən böyük `score_date`) sətir — dublikat bildirişin qarşısını
        almaq üçün (yeni bal əvvəlkindən DƏYİŞMƏYİBSƏ bildiriş TƏKRARLANMIR,
        bax `AttritionRiskUseCase._notify_high_risk` başlığı)."""
        ...

    def list_latest_for_tenant(self, tenant_id: TenantId) -> list[AttritionRiskScore]:
        """Hər işçinin ƏN SON balı, ekranın "ən riskli işçilər" siyahısı üçün."""
        ...


@runtime_checkable
class CheckInHistoryProvider(Protocol):
    """`attendance_records.verified_at` xam giriş anları (#8).

    Gecəlik baz xətt hesablaması VƏ anomaliya qaydası EYNİ portdan oxuyur —
    bax `value_objects.behavior_signals` modul başlığı: iki ayrı sorğu
    "check-in nədir?" tərifinin vaxtla iki fərqli cavabına gətirə bilərdi.
    """

    def list_checkins(
        self, tenant_id: TenantId, *, since: date, until: date
    ) -> list[CheckInObservation]:
        """`[since, until]` (daxil) tarix aralığında TƏSDİQLƏNMİŞ girişlər."""
        ...


# --------------------------------------------------------------------------- #
# #13 Tarixi-nümunə əsaslı kadr təklifi (kompasos11.md Faza 6)
# --------------------------------------------------------------------------- #


@runtime_checkable
class StaffingHistoryProvider(Protocol):
    """ "Bu mağaza filan gün neçə işçi ilə işləyib?" — XAM mənbə (#13).

    1C-YƏ TOXUNMUR: port `attendance_records` üzərində qurulur, satış datası
    ilə heç bir əlaqəsi yoxdur (kompasos11.md struktur qərar D). Ona görə
    imzada nə `SyncCursor`, nə `OneCSaleRecord` var — bu porta 1C
    implementasiyası VERİLƏ BİLMƏZ, çünki qaytardığı tip fiziki iştirak
    faktıdır, satış həcmi deyil.

    `CheckInHistoryProvider`-dən AYRIDIR (ikisi də davamiyyətdən oxusa da):
    o, işçi başına ANLARı verir (davranış baz xətti üçün), bu isə mağaza
    başına SAYı. Birləşdirilsəydi, hər təklif hesablaması on minlərlə giriş
    anını tətbiq qatına daşıyıb orada saymalı olardı — halbuki sayma
    `COUNT(DISTINCT ...)` ilə bazada bir sətirdə edilir.
    """

    def headcount_by_day(
        self, tenant_id: TenantId, *, store_id: StoreId, since: date, until: date
    ) -> list[StoreDayHeadcount]:
        """`[since, until]` (daxil) aralığında GÜN ÜZRƏ fərqli işçi sayı.

        Müşahidəsi olmayan gün siyahıda OLMUR (sıfırla doldurulmur) — bax
        `StaffingPatternUseCase.recalculate_for_store` şərhi: "məlumat yoxdur"
        ilə "sıfır işçi lazımdır" eyni şey deyil.
        """
        ...


@runtime_checkable
class StaffingPatternRepository(Protocol):
    """`staffing_pattern_suggestions` — mağaza + həftə günü = BİR sətir (#13).

    `delete()` VAR OLA BİLƏRDİ (migrations/019 tətbiq roluna `DELETE` verir),
    lakin portda YOXDUR: təklif UPSERT ilə yenilənir və köhnə sətrin silinməsi
    üçün heç bir iş axını mövcud deyil. Mağaza silinəndə `ON DELETE CASCADE`
    onsuz da təmizləyir.
    """

    def list_for_store(
        self, tenant_id: TenantId, store_id: StoreId
    ) -> list[StaffingPatternSuggestion]:
        """Bir mağazanın bütün həftə günləri üçün mövcud təklifləri."""
        ...

    def save(self, suggestion: StaffingPatternSuggestion) -> None:
        """UPSERT — `ON CONFLICT (tenant_id, store_id, weekday)`."""
        ...


@runtime_checkable
class DailyAttendanceSheetRepository(Protocol):
    """`daily_attendance_sheets` + `..._lines` (bölmə 3)."""

    def get_for_day(self, store_id: StoreId, sheet_date: date) -> DailyAttendanceSheet | None: ...

    def list_unconfirmed(
        self, tenant_id: TenantId, *, up_to: date
    ) -> list[DailyAttendanceSheet]: ...

    def save(self, sheet: DailyAttendanceSheet) -> None: ...


@runtime_checkable
class AttendanceFactProvider(Protocol):
    """Tabelin ön-doldurulması üçün xam faktlar (bölmə 3).

    Ayrıca port olması qəsdəndir: faktlar ÜÇ mənbədən yığılır (davamiyyət,
    icazə, növbə planı) və bu birləşdirmə SQL-də bir dəfə edilir. Use case
    üç repo-nu ayrı-ayrı gəzsəydi, 21 filialın bir günü üçün yüzlərlə sorğu
    yaranardı (N+1).
    """

    def facts_for(self, store_id: StoreId, work_date: date) -> list[AttendanceFact]: ...


@runtime_checkable
class WorkedHoursProvider(Protocol):
    """Bir günün ÖLÇÜLƏ BİLƏN iş pəncərələri (#15).

    `AttendanceFactProvider`-dan AYRIDIR, çünki fərqli sual verir: o, tabelin
    STATUSUNU (işdə/qayıb/istirahət), bu isə günün UZUNLUĞUNU çıxarır. Eyni
    porta yığılsaydı, tabelin hər açılışı — gündə onlarla dəfə — növbə saatı
    və icazə dəqiqələrini də gətirməli olardı, halbuki onlar YALNIZ təsdiq
    anında bir dəfə lazımdır.
    """

    def spans_for(self, store_id: StoreId, work_date: date) -> list[WorkedSpan]:
        """Həmin mağazanın həmin günündəki iş pəncərələri (təsdiqlənmiş giriş)."""
        ...


@runtime_checkable
class OvertimeLogRepository(Protocol):
    """`overtime_log` (migrations/019) — işçi-gün başına BİR sətir (#15).

    `DELETE` metodu QƏSDƏN YOXDUR: miqrasiya tətbiq rolundan `DELETE`
    hüququnu AÇIQ ŞƏKİLDƏ geri alır (`REVOKE DELETE ON overtime_log`), çünki
    sətir əmək saatı iddiasının sübutudur. Yenidən hesablama sətri SİLMİR,
    ÜSTÜNDƏN YAZIR (`hours_over_norm = 0.00` da qanuni nəticədir).
    """

    def save(self, entry: OvertimeEntry) -> None:
        """UPSERT — `ON CONFLICT (tenant_id, employee_id, work_date)`."""
        ...

    def list_for_period(
        self, tenant_id: TenantId, *, start: date, end: date
    ) -> list[OvertimeEntry]:
        """`[start, end]` (daxil) aralığındakı bütün sətirlər."""
        ...

    def list_for_employee_period(
        self, tenant_id: TenantId, employee_id: EmployeeId, *, start: date, end: date
    ) -> list[OvertimeEntry]:
        """Bir işçinin aralıqdakı sətirləri — həftəlik toplamanın mənbəyi."""
        ...


@runtime_checkable
class CameraAssignmentRepository(Protocol):
    """Kamera Operatoru → mağaza(lar) (bölmə 4).

    FAIL-SAFE: təyinat yoxdursa BOŞ siyahı qaytarılır və operator heç nə görmür.
    """

    def stores_for_operator(self, operator_id: EmployeeId) -> list[StoreId]: ...

    def assign(
        self, operator_id: EmployeeId, store_id: StoreId, *, assigned_by: EmployeeId
    ) -> None:
        """Təyinat əlavə edir — İDEMPOTENT.

        Eyni təyinatın təkrarı xəta VERMİR: admin ekranı bütün seçilmiş
        mağazaları göndərir və artıq mövcud olanların çökməsi "yadda saxla"
        düyməsini yararsız edərdi.
        """
        ...

    def unassign(self, operator_id: EmployeeId, store_id: StoreId) -> None: ...


# --------------------------------------------------------------------------- #
# Face Control — üz təsdiqi (facecontrol.md, Faza 2)
# --------------------------------------------------------------------------- #
#
# ALTI PORT, BİR QAYDA: domen `face_recognition` (Dlib) kitabxanasını GÖRMÜR.
# Alignment (bənd 10), landmark aşkarlaması, məsafə hesablaması və kamera
# sürücüsü infrastruktur adapterlərindədir; burada yalnız onların MÜQAVİLƏSİ
# var. Beləliklə anti-fraud məntiqi (hədd zolağı, kilid sayğacı, cross-check)
# ağır bir kitabxana quraşdırılmadan test oluna bilir.
#
# BİOMETRİK MÜQAVİLƏ (migrations/047-nin dörd qaydası) BU PORTLARA DA AİDDİR:
#   * heç bir port KADR saxlamır və ya qaytarmır (yalnız emal edir);
#   * `FaceEmbeddingRepository` şifrələməni ÖZÜ edir — use case açıq mətn
#     vektoru ilə işləyir, DB isə yalnız token görür (bax `face_repository.py`);
#   * `purge()` VEKTORU SİLİR VƏ ARXİVDƏ İZ QOYUR — ikisi bir metodda, çünki
#     ayrı olsaydı, biri unudulanda biometrik məlumat sükutla sağ qalardı.


@runtime_checkable
class FaceMatcher(Protocol):
    """Üz-tanıma mühərriki (`facecontrol.md` bənd 3, 7, 10, 11, 12).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `extract` VƏ `distance` AYRI METODLARDIR
    ──────────────────────────────────────────────────────────────────────────
    "Bu kadr bu işçiyə uyğundurmu?" şəklində TƏK metod daha sadə görünürdü və
    rədd edildi: MISMATCH halında EYNİ kadr mağazanın BÜTÜN qeydiyyatlı
    işçiləri ilə müqayisə olunur (cross-check, bənd 3). Tək metodla hər
    müqayisə üçün kadr yenidən emal edilər — yəni alignment və embedding
    hesablaması işçi sayı qədər təkrarlanardı (kioskda saniyələr).

    ALIGNMENT PORTUN İÇİNDƏDİR, AYRICA METOD DEYİL: bənd 10 onu HƏM
    enrollment, HƏM hər doğrulama üçün MƏCBURİ edir. Ayrıca metod olsaydı,
    onu çağırmağı unudan bir axın sükutla daha aşağı dəqiqliklə işləyərdi —
    və heç bir test bunu tutmazdı, çünki nəticə yenə "işləyir".
    """

    def extract(self, frame: FaceFrame, *, gesture: LivenessGesture | None = None) -> FaceSample:
        """Kadrdan üzü düzləndirib (alignment) vektoru və keyfiyyət balını çıxarır.

        Args:
            gesture: Tələb olunan canlılıq hərəkəti (bənd 6). `None` =
                yoxlama İSTƏNİLMİR (enrollment: admin fiziki olaraq oradadır
                və prosesi özü idarə edir) — belə halda nəticədə
                `liveness_confirmed=True` gəlir.

        Üz tapılmasa `embedding=None` qaytarılır — İSTİSNA ATILMIR: bu, gündəlik
        və gözlənilən haldır (işıq, bucaq) və `NO_FACE_DETECTED` axınına
        çevrilir (bənd 3). İstisna atsaydıq, adi işıq problemi kioskda xəta
        ekranı kimi görünərdi.
        """
        ...

    def distance(self, reference: FaceEmbedding, candidate: FaceEmbedding) -> float:
        """İki vektor arasındakı MƏSAFƏ (kiçik = daha oxşar).

        VAHİD QƏSDƏN KİTABXANANINKIDIR: `FACE_MATCH_TOLERANCE` və
        `FACE_LOW_CONFIDENCE_TOLERANCE` Root ekranında məhz bu vahiddə
        göstərilir. Faiz qaytarsaydıq, Root-un gördüyü ədəd ilə kitabxananın
        cavabı arasında gizli bir çevirmə sabiti oturardı və həmin sabit özü
        hardcode edilmiş qərara çevrilərdi (migrations/047, `confidence_score`
        şərhi).
        """
        ...


@runtime_checkable
class CameraCapture(Protocol):
    """Kiosk veb-kamerası (bənd 1, 5).

    NASAZLIQ SÜKUTLA "PIN-ONLY"A ÇEVRİLMİR (bənd 5) — məhz ona görə
    `is_available()` AYRICA metoddur: use case nasazlığı BİR şərtdə görür və
    mövcud timeout-eskalasiya kanalına yönləndirir. Nasazlığı yalnız "boş
    kadr siyahısı" ilə ifadə etsəydik, "kamera işləyir, amma üz görünmür"
    (`NO_FACE_DETECTED`, texniki, sayğacsız) ilə "kamera ümumiyyətlə yoxdur"
    (eskalasiya tələb edən) halları eyni cavaba yığılardı.
    """

    def is_available(self) -> bool:
        """Kamera fiziki olaraq bağlıdır və açıla bilirmi."""
        ...

    def capture(self, *, count: int = 1, gesture: LivenessGesture | None = None) -> list[FaceFrame]:
        """Kadr(lar) çəkir — DİSKƏ YAZMIR, yalnız yaddaşda qaytarır.

        Args:
            count: Neçə kadr (`FACE_ENROLLMENT_FRAME_COUNT` — bənd 11).
                Doğrulamada 1-dir.
            gesture: Ekranda göstəriləcək canlılıq göstərişi (bənd 6). Hərəkət
                SERVERDƏ seçilir və bura ötürülür — adapterin ÖZÜ seçsəydi,
                seçim kiosk maşınında olardı və təsadüfilik yerli koddan asılı
                qalardı.

        Boş siyahı qaytarmaq QANUNİDİR (işçi vaxtında hərəkəti etmədi) və
        `NO_FACE_DETECTED` kimi emal olunur.
        """
        ...


@runtime_checkable
class FaceEmbeddingRepository(Protocol):
    """`employees` sətrinin üz sahələri + `face_embedding_history` arxivi.

    ŞİFRƏLƏMƏ BU PORTUN ARXASINDADIR: implementasiya (`face_repository.py`)
    mövcud `EncryptionService`-i işlədir və use case AÇIQ vektorla işləyir.
    Alternativ — use case-də şifrələmək — RƏDD EDİLDİ: tətbiq qatı onda
    infrastruktur sinfini birbaşa idxal edərdi və "hansı sütun şifrəlidir?"
    qərarı iki qatda yaşayardı (`ErpServerRegistry` ilə eyni naxış).
    """

    def get_profile(self, employee_id: EmployeeId) -> FaceProfile | None:
        """İşçinin üz profili (vektor AÇIQ mətndə — deşifrə edilmiş).

        İşçi yoxdursa `None`; qeydiyyatsız işçidə `embedding is None` olan
        profil qaytarılır — ikisi FƏRQLİDİR: birincisi "belə işçi yoxdur",
        ikincisi "işçi var, üzü qeydiyyatda deyil" (istisnalı işçi və ya yeni
        işə götürülən) və axınları da fərqlidir.
        """
        ...

    def save_enrollment(
        self,
        employee_id: EmployeeId,
        *,
        embedding: FaceEmbedding,
        enrolled_at: datetime,
    ) -> None:
        """İstinad vektorunu yazır (şifrələyərək) və qeydiyyat anını möhürləyir.

        İKİSİ BİRLİKDƏ YAZILIR, çünki sxem onları `chk_employee_face_
        enrollment_pair` ilə bağlayıb: vektorsuz tarix «qeydiyyatlı görünən,
        doğrulana bilməyən» işçi, tarixsiz vektor isə heç vaxt köhnəlməyən
        qeydiyyat yaradardı (bənd 13).
        """
        ...

    def archive(
        self,
        employee_id: EmployeeId,
        *,
        archived_by: EmployeeId | None,
        reason: str | None,
        archived_at: datetime,
    ) -> bool:
        """Cari vektoru `REPLACED` statusu ilə arxivə köçürür (bənd 2).

        Returns:
            Arxivlənəcək qeydiyyat VAR İDİmi. `False` = ilk qeydiyyatdır.
        """
        ...

    def purge(
        self,
        employee_id: EmployeeId,
        *,
        purged_by: EmployeeId | None,
        reason: str | None,
        purged_at: datetime,
    ) -> bool:
        """Vektoru SİLİR və arxivdə `PURGED` izi qoyur (bənd 8).

        İKİ İŞ BİR METODDADIR VƏ BU, TƏHLÜKƏSİZLİK QƏRARIDIR: yalnız
        `employees.face_embedding`-i təmizləmək biometrik məlumatı ARXİVDƏ
        sağ saxlayardı (migrations/047 bunu açıq izah edir). Ayrı metodlar
        olsaydı, çağıran birini unuda bilərdi və qayda sükutla pozulardı.

        Returns:
            Silinəcək vektor VAR İDİmi (idempotentlik üçün — ikinci
            deaktivasiya çağırışı xəta vermir).
        """
        ...

    def save_security(
        self,
        employee_id: EmployeeId,
        *,
        mismatch_attempts: int,
        locked_until: datetime | None,
    ) -> None:
        """MISMATCH sayğacını və üz kilidini yazır (bənd 3, 4).

        SAYĞAC PIN SAYĞACINA TOXUNMUR: `pin_failed_attempts` və
        `pin_locked_until` sütunları bu metoddan HEÇ VAXT yazılmır — iki
        sayğacın ayrılığı sxem səviyyəsində ifadə olunub və kod tərəfi onu
        pozmamalıdır.
        """
        ...

    def list_store_profiles(
        self, tenant_id: TenantId, store_id: StoreId, *, exclude: EmployeeId | None = None
    ) -> list[FaceProfile]:
        """EYNİ MAĞAZANIN qeydiyyatlı işçiləri — MISMATCH cross-check-i (bənd 3).

        ƏHATƏ QƏSDƏN MAĞAZA İLƏ MƏHDUDDUR: bütün şəbəkə (235 işçi) üzrə
        axtarış həm yavaşdır, həm də yalançı-müsbətə meyllidir — kioskda
        duran adamın 100 km uzaqdakı filialın işçisi olması ehtimalı, iki
        nəfərin təsadüfən oxşar çıxması ehtimalından aşağıdır.
        """
        ...

    def list_stale_enrollments(
        self, tenant_id: TenantId, *, enrolled_before: datetime
    ) -> list[FaceProfile]:
        """«Köhnəlmiş» qeydiyyatlar (bənd 13) — admin panelinin tövsiyə siyahısı.

        BLOKLAMIR: siyahı yalnız göstərilir. Kəsim tarixi use case-də
        `FACE_REENROLLMENT_REMINDER_MONTHS`-dan hesablanır, SQL-də yox — Root
        həddi dəyişəndə siyahı DƏRHAL yenilənməlidir (`break_overuse_for_day`
        ilə eyni əsaslandırma).
        """
        ...


@runtime_checkable
class FaceVerificationLogRepository(Protocol):
    """`face_verification_log` — hər cəhdin jurnalı (bənd 9, 12, 17, 18).

    `UPDATE` YOXDUR VƏ OLMAYACAQ: miqrasiya tətbiq rolundan `UPDATE`
    hüququnu AÇIQ geri alır — jurnal sətri FAKTdır və biri MISMATCH-i
    sonradan SUCCESS-ə çevirə bilməməlidir. `DELETE` isə VAR, lakin yalnız
    saxlama müddəti təmizləməsi üçün (`purge_older_than`).
    """

    def record(self, entry: FaceVerificationLogEntry) -> None:
        """Cəhdi jurnala yazır — vektor/kadr YAZILMIR, yalnız nəticə və bal."""
        ...

    def purge_older_than(self, tenant_id: TenantId, *, cutoff: datetime) -> int:
        """Saxlama müddətindən köhnə sətirləri TAM SİLİR (bənd 17).

        Anonimləşdirmə DEYİL, silmə: jurnalda foto və vektor onsuz da yoxdur,
        yalnız nəticə və bal var — anonimləşdirmə həmin sətirləri hesabat
        üçün yararsız edər, lakin heç bir əlavə məxfilik qazandırmazdı.

        Returns: Silinən sətir sayı (planlaşdırılmış işin hesabat sətri).
        """
        ...

    def list_mismatches_since(
        self, tenant_id: TenantId, *, since: datetime
    ) -> list[FaceVerificationLogEntry]:
        """Verilmiş andan sonrakı MISMATCH sətirləri (bənd 16).

        İstisna Motoruna qoşulan qayda bunu oxuyur. Motorun ÖZÜ dəyişmir —
        `FACE_MISMATCH` mənbəyi kataloqa seed edilib, qayda isə reyestrə bir
        `register_rule()` çağırışı ilə qoşulur.
        """
        ...


@runtime_checkable
class FaceExemptionRepository(Protocol):
    """`face_control_exemptions` — PIN-only istisnası (bənd 14).

    `delete()` YOXDUR: miqrasiya tətbiq rolundan `DELETE`-i geri alır — ləğv
    edilmiş və müddəti bitmiş istisna «həmin gün bu işçi niyə üz təsdiqindən
    keçmirdi?» sualının yeganə struktur cavabıdır.
    """

    def active_for(self, employee_id: EmployeeId, *, now: datetime) -> FaceExemption | None:
        """İşçinin BU ANDA qüvvədə olan istisnası.

        Sorğu HƏM statusa, HƏM `expires_at`-a baxır: gecəlik iş işləməmiş ola
        bilər (terminal söndürülüb) və `ACTIVE` sətrin müddəti faktiki olaraq
        bitmiş olardı. Yalnız statusa baxsaydıq, söndürülmüş terminal istisnanı
        — yəni üz təsdiqindən azadlığı — sükutla uzadardı.
        """
        ...

    def get(self, exemption_id: FaceExemptionId) -> FaceExemption | None: ...

    def save(self, exemption: FaceExemption) -> None:
        """UPSERT — `ON CONFLICT (id)`."""
        ...

    def list_due_for_expiry(self, tenant_id: TenantId, *, now: datetime) -> list[FaceExemption]:
        """Müddəti bitmiş, lakin hələ `ACTIVE` sətirlər — gecəlik işin girişi."""
        ...

    def list_active(self, tenant_id: TenantId, *, now: datetime) -> list[FaceExemption]:
        """Qüvvədə olan istisnalar — Root/CEO idarəetmə ekranının siyahısı."""
        ...


@runtime_checkable
class FaceStoreScopeRepository(Protocol):
    """`face_control_store_scope` — mağaza-səviyyəli aktivlik (bənd 15).

    QLOBAL TOGGLE MEXANİZMİNƏ TOXUNMUR: bu, onun ÜSTÜNDƏ DARALDICI süzgəcdir.
    AKTİV sətir yoxdursa davranış BUGÜNKÜ ilə eynidir — qlobal toggle nə
    deyirsə, o olur (`FaceStoreScope.is_global`).
    """

    def active_scope(self, tenant_id: TenantId) -> FaceStoreScope:
        """Aktiv mağazalar dəsti. Boş dəst = QLOBAL davranış."""
        ...

    def set_active(
        self, tenant_id: TenantId, store_id: StoreId, *, active: bool, changed_by: EmployeeId
    ) -> None:
        """Mağazanı əhatəyə salır/çıxarır — SOFT DELETE ilə.

        Çıxarma sətri SİLMİR (`is_active = FALSE`): «bu mağazada Face Control
        üç ay işlədi, sonra söndürüldü» faktı keçmiş kilidlərin qanuniliyini
        izah edən yeganə mənbədir.
        """
        ...


# --------------------------------------------------------------------------- #
# Baza keçidi (bölmə 2 — Hybrid DB Switcher)
# --------------------------------------------------------------------------- #


@runtime_checkable
class ReadOnlyModeController(Protocol):
    """Aktiv sessiyaları yalnız-oxu rejiminə keçirir (bölmə 2).

    Keçid zamanı yazı davam etsəydi, köçürülmüş məlumat elə köçürmə anında
    köhnələrdi və checksum heç vaxt uyğun gəlməzdi.
    """

    def enter_read_only(self, tenant_id: TenantId, *, reason: str) -> None: ...

    def leave_read_only(self, tenant_id: TenantId) -> None: ...

    def is_read_only(self, tenant_id: TenantId) -> bool: ...


@runtime_checkable
class OfflineBufferDrain(Protocol):
    """Sinxronlaşmamış offline yazıların vəziyyəti."""

    def pending_count(self, tenant_id: TenantId) -> int: ...

    def flush(self, tenant_id: TenantId) -> int:
        """Növbəni boşaltmağa cəhd edir; qalan sətir sayını qaytarır."""
        ...


@runtime_checkable
class DatabaseMigrator(Protocol):
    """Faktiki köçürmə əməliyyatları (`pg_dump`/`pg_restore` və ya replikasiya)."""

    def checksum(self, target: DatabaseTarget) -> str:
        """Bazanın barmaq izi — miqrasiyanın düzgünlüyünün yeganə sübutu."""
        ...

    def copy(self, *, source: DatabaseTarget, destination: DatabaseTarget) -> None: ...

    def switch_active(self, target: DatabaseTarget) -> None:
        """Tətbiqin işlədiyi bazanı dəyişir (konfiqurasiya + bağlantı hovuzu)."""
        ...

    def rollback(self, *, to: DatabaseTarget, reason: str) -> None: ...


@runtime_checkable
class MigrationEventLog(Protocol):
    """`db_migration_events` — keçid tarixçəsi (bölmə 2)."""

    def start(
        self,
        *,
        tenant_id: TenantId,
        initiated_by: EmployeeId,
        source: DatabaseTarget,
        destination: DatabaseTarget,
        window_start: datetime,
    ) -> str:
        """Yeni sətir yaradır və onun ID-sini qaytarır."""
        ...

    def finish(
        self,
        event_id: str,
        *,
        status: MigrationStatus,
        checksums: ChecksumPair | None = None,
        buffer_flushed: bool = False,
        rolled_back: bool = False,
        rollback_reason: str | None = None,
        window_end: datetime | None = None,
    ) -> None: ...

    def history(self, tenant_id: TenantId, *, limit: int = 20) -> list[dict[str, object]]: ...


@runtime_checkable
class ScheduledJobRepository(Protocol):
    """`app_scheduled_job_runs` — planlanmış işin İCARƏSİ və nəticəsi (Faza 11).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `get()` + `save()` NAXIŞI YOXDUR
    ──────────────────────────────────────────────────────────────────────────
    Digər repo-larda naxış `save(aqreqat)` UPSERT-idir. Burada QƏSDƏN
    fərqlidir və səbəb `OpenShiftPostingRepository`-dəki ilə eynidir: sistem
    21 mağazada, hər mağazada bir neçə terminalda işləyir və hamısı EYNİ
    gecə işini görməyə çalışır.

    `get()` → yoxla → `save()` ardıcıllığı bu şəraitdə UDUZUR: iki terminal
    eyni anda "qeyd yoxdur" görüb hər ikisi işi icra edər — baz xətti iki
    dəfə hesablanar, HR eyni sənəd üçün iki e-poçt alar. Ona görə götürmə
    TƏK atomik metoddur (`acquire`) və qərarı DB verir, Python yox.

    ──────────────────────────────────────────────────────────────────────────
    HƏR METOD ÖZ TRANZAKSİYASINDA COMMIT OLUNUR
    ──────────────────────────────────────────────────────────────────────────
    `acquire()` çağıranın tranzaksiyasında qalsaydı, icarə yalnız İŞ BİTDİKDƏN
    sonra görünərdi — yəni bütün müdafiə mənasını itirərdi (digər terminal
    icarəni GÖRMƏDƏN eyni işi başlayardı). Üstəlik ağır iş (`pg_dump`)
    dəqiqələrlə çəkir və o müddət boyu açıq tranzaksiya saxlamaq CLAUDE.md
    §6-nın açıq şəkildə qadağan etdiyi naxışdır.
    """

    def acquire(
        self,
        *,
        tenant_id: TenantId,
        job_key: str,
        scheduled_for: datetime,
        instance_id: str,
        now: datetime,
        leased_until: datetime,
        max_attempts: int,
    ) -> bool:
        """İcarəni ATOMİK götürür. `True` = bu instansiya icra etməlidir.

        `False` üç halın hər hansı biridir və onlar QƏSDƏN ayrılmır: slot
        artıq uğurla tamamlanıb, başqa instansiya onu indi icra edir, və ya
        cəhd tavanı dolub. Çağıran tərəf üçün nəticə eynidir — "sən icra
        etmirsən" — və ayırmaq üçün əlavə sorğu atmaq yarışın özünü geri
        gətirərdi (oxunan cavab yazı anında artıq köhnə olardı).
        """
        ...

    def mark_succeeded(
        self,
        *,
        tenant_id: TenantId,
        job_key: str,
        scheduled_for: datetime,
        instance_id: str,
        finished_at: datetime,
        result_detail: str | None = None,
    ) -> bool:
        """Uğurlu bitişi yazır. `False` = icarə artıq bu instansiyada deyil.

        `instance_id` şərti MƏCBURİDİR: icarəsi bitmiş, lakin hələ işləyən
        instansiya nəticəsini YENİ sahibin üstünə yazmamalıdır.
        """
        ...

    def mark_failed(
        self,
        *,
        tenant_id: TenantId,
        job_key: str,
        scheduled_for: datetime,
        instance_id: str,
        finished_at: datetime,
        error: str,
    ) -> bool:
        """Uğursuzluğu və səbəbini yazır. `False` = icarə artıq bu instansiyada deyil."""
        ...

    def get(
        self, *, tenant_id: TenantId, job_key: str, scheduled_for: datetime
    ) -> ScheduledJobRun | None:
        """Bir slotun qeydi — diaqnostika və sağlamlıq ekranı üçün.

        İCRA YOLUNDA İŞLƏDİLMİR: "əvvəlcə oxu, sonra götür" naxışı məhz
        bağlanmaq istənən qüsurdur (bax sinif başlığı).
        """
        ...


@runtime_checkable
class UnitOfWork(Protocol):
    """Tranzaksiya sərhədi.

    RLS MÜQAVİLƏSİ (SEC-008): `begin()` hər tranzaksiyanın əvvəlində
    `SET LOCAL app.tenant_id` icra etməlidir — əks halda fail-closed siyasət
    bütün sorğuları boş qaytaracaq.
    """

    def __enter__(self) -> UnitOfWork: ...

    def __exit__(self, *args: object) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


__all__ = [
    "AnnouncementRepository",
    "AnnualLeaveBalanceRepository",
    "AnnualLeaveRequestRepository",
    "AttendanceFactProvider",
    "AttendanceRepository",
    "AttritionRiskScoreRepository",
    "AuditTrail",
    "AuthSessionRepository",
    "BehaviorBaselineRepository",
    "BulkImportLogRepository",
    "CameraAssignmentRepository",
    "CameraCapture",
    "CheckInHistoryProvider",
    "Clock",
    "DailyAttendanceSheetRepository",
    "DailyBreakUsageRepository",
    "DatabaseMigrator",
    "EmployeeRepository",
    "ErpConnectorFactory",
    "ErpServerRegistry",
    "EventPublisher",
    "EvidenceStorageProvider",
    "ExceptionRepository",
    "ExceptionRule",
    "ExceptionSourceCatalog",
    "ExecutiveDigestConfigRepository",
    "ExportCorrectionRepository",
    "FaceEmbeddingRepository",
    "FaceExemptionRepository",
    "FaceMatcher",
    "FaceStoreScopeRepository",
    "FaceVerificationLogRepository",
    "FeatureToggles",
    "FieldReportCatalog",
    "FieldReportRepository",
    "FineAppealRepository",
    "FineRepository",
    "FineTypeRepository",
    "LeaveRequestRepository",
    "LeaveTypeRepository",
    "LicenseGateway",
    "LicenseStateStore",
    "MigrationEventLog",
    "Notifier",
    "NtpVerifier",
    "OfflineBufferDrain",
    "OpenShiftPostingRepository",
    "OvertimeLogRepository",
    "POSThresholdRepository",
    "PerformanceReviewRepository",
    "PermissionFlagRepository",
    "PinThrottleRepository",
    "PositionRepository",
    "RangeScopedFineReader",
    "ReadOnlyModeController",
    "RewardRepository",
    "RowLockingAttendance",
    "RowLockingLeaveRequests",
    "SalesDataConnector",
    "SalesPointsRepository",
    "ScheduledJobRepository",
    "SecurityEventRepository",
    "ShiftRepository",
    "ShiftSwapRepository",
    "StoreTemplateRepository",
    "SystemLimits",
    "TaskRepository",
    "UnitOfWork",
    "WorkModeRepository",
    "WorkedHoursProvider",
]
