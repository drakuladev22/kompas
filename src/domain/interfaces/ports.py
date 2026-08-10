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

from src.domain.entities.appeal import FineAppeal
from src.domain.entities.attendance_record import AttendanceRecord
from src.domain.entities.attendance_sheet import AttendanceFact, DailyAttendanceSheet
from src.domain.entities.employee import Employee
from src.domain.entities.fine import Fine
from src.domain.entities.leave_request import LeaveRequest
from src.domain.entities.position import Position
from src.domain.entities.sales_points import PointsEntry, RewardRedemption
from src.domain.entities.shift import ShiftAssignment, ShiftSwapRequest
from src.domain.entities.task import Task
from src.domain.value_objects.authorization import PermissionFlag
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
from src.domain.value_objects.gamification import PointsPeriod, RewardItem
from src.domain.value_objects.identifiers import (
    AppealId,
    AttendanceRecordId,
    EmployeeId,
    ErpServerId,
    FineId,
    FineTypeId,
    LeaveRequestId,
    LeaveTypeId,
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
    """ROOT Control Center-dəki konfiqurasiya edilə bilən limitlər (bölmə 3)."""

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
        üçün — bölmə 3 həmin limiti Root Control Center-dən idarə olunan
        parametr kimi sadalayır və onu oxumaq üçün cəm lazımdır.

        YALNIZ `VERIFIED` sorğular sayılır: hələ təsdiqlənməmiş sorğunun
        faktiki müddəti məlum deyil (operator vaxtı əl ilə düzəldə bilər),
        ona görə açıq sorğunu cəmə qatmaq yanlış rəqəm verərdi.
        """
        ...

    def save(self, request: LeaveRequest) -> None: ...


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
    "AttendanceFactProvider",
    "AttendanceRepository",
    "AuditTrail",
    "CameraAssignmentRepository",
    "Clock",
    "DailyAttendanceSheetRepository",
    "DatabaseMigrator",
    "EmployeeRepository",
    "ErpConnectorFactory",
    "ErpServerRegistry",
    "EventPublisher",
    "EvidenceStorageProvider",
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
    "PermissionFlagRepository",
    "PositionRepository",
    "ReadOnlyModeController",
    "RewardRepository",
    "SalesDataConnector",
    "SalesPointsRepository",
    "ShiftRepository",
    "ShiftSwapRepository",
    "SystemLimits",
    "TaskRepository",
    "UnitOfWork",
    "WorkModeRepository",
]
