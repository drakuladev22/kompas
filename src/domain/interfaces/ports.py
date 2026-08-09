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

from src.domain.entities.attendance_record import AttendanceRecord
from src.domain.entities.employee import Employee
from src.domain.entities.fine import Fine
from src.domain.entities.leave_request import LeaveRequest
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import PermissionFlag
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    AttendanceRecordId,
    EmployeeId,
    FineId,
    LeaveRequestId,
    LeaveTypeId,
    PositionId,
    StoreId,
    TenantId,
)
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


@runtime_checkable
class FeatureToggles(Protocol):
    """Modul aç/bağla vəziyyəti (bölmə 3).

    RETROAKTİV TƏSİR QAYDASI: deaktivasiya YALNIZ yeni instansiyalara təsir
    edir — mövcud qeydlər öz axınını normal tamamlayır.
    """

    def is_enabled(self, tenant_id: TenantId, module_key: str) -> bool: ...


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


@runtime_checkable
class ShiftRepository(Protocol):
    def is_off_day(self, employee_id: EmployeeId, work_date: date) -> bool: ...

    def scheduled_start(self, employee_id: EmployeeId, work_date: date) -> datetime | None:
        """İş Rejiminə görə planlaşdırılmış başlanğıc — gecikmə hesablaması üçün."""
        ...


@runtime_checkable
class CameraAssignmentRepository(Protocol):
    """Kamera Operatoru → mağaza(lar) (bölmə 4).

    FAIL-SAFE: təyinat yoxdursa BOŞ siyahı qaytarılır və operator heç nə görmür.
    """

    def stores_for_operator(self, operator_id: EmployeeId) -> list[StoreId]: ...


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
    "AttendanceRepository",
    "AuditTrail",
    "CameraAssignmentRepository",
    "Clock",
    "EmployeeRepository",
    "EventPublisher",
    "FeatureToggles",
    "FineRepository",
    "LeaveRequestRepository",
    "LeaveTypeRepository",
    "Notifier",
    "NtpVerifier",
    "PermissionFlagRepository",
    "PositionRepository",
    "ShiftRepository",
    "SystemLimits",
    "UnitOfWork",
]
