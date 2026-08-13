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
from typing import Protocol, runtime_checkable

from src.domain.attrition_rules import AttritionRiskScore
from src.domain.entities.announcement import Announcement
from src.domain.entities.appeal import FineAppeal
from src.domain.entities.attendance_record import AttendanceRecord
from src.domain.entities.attendance_sheet import AttendanceFact, DailyAttendanceSheet
from src.domain.entities.employee import Employee
from src.domain.entities.employee_document import EmployeeDocument
from src.domain.entities.exception_record import ExceptionRecord
from src.domain.entities.fine import Fine
from src.domain.entities.leave_request import LeaveRequest
from src.domain.entities.open_shift import OpenShiftPosting, OpenShiftSlot
from src.domain.entities.performance_review import PerformanceReview
from src.domain.entities.pos_threshold import POSPermissionThreshold
from src.domain.entities.position import Position
from src.domain.entities.sales_points import PointsEntry, RewardRedemption
from src.domain.entities.shift import ShiftAssignment, ShiftSwapRequest
from src.domain.entities.task import Task
from src.domain.value_objects.authorization import PermissionFlag
from src.domain.value_objects.behavior_signals import BehaviorBaseline, CheckInObservation
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
from src.domain.value_objects.gamification import PointsPeriod, RewardItem
from src.domain.value_objects.identifiers import (
    AnnouncementId,
    AppealId,
    AttendanceRecordId,
    EmployeeDocumentId,
    EmployeeId,
    ErpServerId,
    ExceptionId,
    FineId,
    FineTypeId,
    LeaveRequestId,
    LeaveTypeId,
    OpenShiftPostingId,
    PointsEntryId,
    PositionId,
    RedemptionId,
    RewardId,
    ShiftSwapRequestId,
    StoreId,
    TaskId,
    TenantId,
    WorkModeId,
)
from src.domain.value_objects.infrastructure import (
    ChecksumPair,
    DatabaseTarget,
    MigrationStatus,
)
from src.domain.value_objects.licensing import (
    CheckInRequest,
    CrashReport,
    LicenseSnapshot,
)
from src.domain.value_objects.overtime import OvertimeEntry, WorkedSpan
from src.domain.value_objects.staffing_signals import (
    StaffingPatternSuggestion,
    StoreDayHeadcount,
)
from src.domain.value_objects.storage import ImageSize, StorageReference
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
class EventPublisher(Protocol):
    """Aqreqatların topladığı hadisələri yayımlayır (tranzaksiyadan SONRA)."""

    async def publish_all(self, events: tuple[DomainEvent, ...]) -> None: ...


# --------------------------------------------------------------------------- #
# Repository-lər
# --------------------------------------------------------------------------- #


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

    def count_active_with_flag(self, tenant_id: TenantId, flag_code: str) -> int:
        """Dual-Control Deadlock Guard üçün (bölmə 3)."""
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

    def save(self, fine: Fine) -> None: ...


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
        """`can_manage_sales_points` sahibinin etiraz inbox-u."""
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

    def list_for_employee(
        self, employee_id: EmployeeId, *, limit: int = 50
    ) -> list[FineAppeal]: ...

    def save(self, appeal: FineAppeal) -> None: ...


@runtime_checkable
class ShiftSwapRepository(Protocol):
    """`shift_swap_requests` (bölmə 3 — işçi-tərəfi self-service)."""

    def get(self, request_id: ShiftSwapRequestId) -> ShiftSwapRequest | None: ...

    def list_pending(
        self, tenant_id: TenantId, *, store_id: StoreId | None = None
    ) -> list[ShiftSwapRequest]: ...

    def list_for_employee(
        self, employee_id: EmployeeId, *, limit: int = 50
    ) -> list[ShiftSwapRequest]: ...

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
    "AttendanceFactProvider",
    "AttendanceRepository",
    "AttritionRiskScoreRepository",
    "AuditTrail",
    "BehaviorBaselineRepository",
    "CameraAssignmentRepository",
    "CheckInHistoryProvider",
    "Clock",
    "DailyAttendanceSheetRepository",
    "DatabaseMigrator",
    "EmployeeRepository",
    "ErpConnectorFactory",
    "ErpServerRegistry",
    "EventPublisher",
    "EvidenceStorageProvider",
    "ExceptionRepository",
    "ExceptionRule",
    "ExceptionSourceCatalog",
    "FeatureToggles",
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
    "PositionRepository",
    "ReadOnlyModeController",
    "RewardRepository",
    "RowLockingAttendance",
    "RowLockingLeaveRequests",
    "SalesDataConnector",
    "SalesPointsRepository",
    "ShiftRepository",
    "ShiftSwapRepository",
    "SystemLimits",
    "TaskRepository",
    "UnitOfWork",
    "WorkModeRepository",
    "WorkedHoursProvider",
]
