"""Baza keçidi (Cloud ↔ Private Server) value object-ləri — bölmə 2.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA VƏZİYYƏT MAŞINI
──────────────────────────────────────────────────────────────────────────────
Baza keçidi tətbiqin ƏN TƏHLÜKƏLİ əməliyyatıdır: yarımçıq qalarsa, məlumatın
bir hissəsi köhnə, bir hissəsi yeni serverdə olar və hansının doğru olduğu
sonradan müəyyən edilə bilməz. Ona görə "sadəcə connection string dəyiş"
yanaşması QƏSDƏN seçilməyib — hər addım adlandırılır, jurnala yazılır və
uğursuzluqda geri qaytarılır.

Bölmə 2-nin dörd tələbi bu modulda struktur şəklindədir:

    1. keçid YALNIZ maintenance window-da     → `MigrationPhase` sırası
    2. sessiyalar read-only rejimə keçir      → `OPEN_WINDOW` fazası
    3. offline bufer TAM sinxronlaşır         → `DRAIN_BUFFER` fazası
    4. pre-flight checksum + avtomatik rollback → `ChecksumPair.matched`

──────────────────────────────────────────────────────────────────────────────
CHECKSUM NİYƏ "BƏRABƏRDİRMİ" SUALINA ENDİRİLİR
──────────────────────────────────────────────────────────────────────────────
Miqrasiyanın düzgünlüyünü sübut etməyin praktik yolu mənbə və hədəfin eyni
barmaq izini verməsidir. Fərqlənirsə, HANSININ səhv olduğunu bilmək lazım
deyil — hər iki halda cavab eynidir: geri qaytar. Bu sadələşdirmə qərarı
"qismən uğurlu miqrasiya" adlı ən təhlükəli nəticəni struktur olaraq bağlayır.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Final

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.scheduling import require_aware
from src.shared.exceptions import KompasOSError

#: Bufer boşalmasını gözləmək üçün yuxarı hədd. Aşılarsa keçid BAŞLAMIR —
#: sinxronlaşmamış yazı ilə miqrasiya məlumat itkisi deməkdir.
#: FALLBACK — HƏQİQİ MƏNBƏ `system_limits.DB_MIGRATION_DRAIN_TIMEOUT_SECONDS`
#: (seed: migrations/033). KEÇİDİN ÖZ SIRASI (`MigrationPhase`) və checksum
#: bərabərliyi şərti PARAMETR DEYİL — onlar struktur qaydalardır; konfiqurasiya
#: edilən yalnız "nə qədər gözləyək".
DEFAULT_DRAIN_TIMEOUT_SECONDS: Final[int] = int(
    DEFAULT_LIMITS[SystemLimitKey.DB_MIGRATION_DRAIN_TIMEOUT_SECONDS]
)
#: Maintenance window-un ağlabatan yuxarı həddi. Uzun pəncərə = uzun kəsinti.
#: FALLBACK — HƏQİQİ MƏNBƏ `system_limits.DB_MIGRATION_MAX_WINDOW_MINUTES`.
MAX_WINDOW_MINUTES: Final[int] = int(DEFAULT_LIMITS[SystemLimitKey.DB_MIGRATION_MAX_WINDOW_MINUTES])
#: Geri qaytarma səbəbi üçün minimum uzunluq (audit modeli ilə eyni).
#: ROOT PARAMETRİ DEYİL: audit mətn qaydasının güzgüsüdür (`FineAppeal`,
#: `EXCEPTION_REVIEW_NOTE_MIN_LENGTH` ilə eyni ailə) — mətn uzunluğu biznes
#: siyasəti deyil, sənədləşdirmə minimumudur.
MIN_ROLLBACK_REASON_LENGTH: Final[int] = 10


class MigrationError(KompasOSError):
    """Baza keçidi icra edilə bilmədi."""

    user_message = "Baza keçidi tamamlana bilmədi. Sistem köhnə bazada işləməyə davam edir."


class MaintenanceWindowError(MigrationError):
    """Keçid maintenance window olmadan başladılmağa çalışıldı."""

    user_message = "Baza keçidi yalnız texniki fasilə rejimində icra oluna bilər."


class DatabaseTarget(str, Enum):
    """`db_migration_events.source_target` — DB CHECK-i ilə eyni dəyərlər."""

    CLOUD = "CLOUD"
    PRIVATE_SERVER = "PRIVATE_SERVER"

    @property
    def label_az(self) -> str:
        return {
            DatabaseTarget.CLOUD: "Bulud (Supabase)",
            DatabaseTarget.PRIVATE_SERVER: "Şəxsi server",
        }[self]

    def opposite(self) -> DatabaseTarget:
        """Keçidin qarşı tərəfi — panel yalnız iki hədəf arasında işləyir."""
        return (
            DatabaseTarget.PRIVATE_SERVER if self is DatabaseTarget.CLOUD else DatabaseTarget.CLOUD
        )


class MigrationPhase(str, Enum):
    """Keçidin addımları — SIRASI dəyişdirilə bilməz.

    Sıra təsadüfi deyil: bufer boşalmadan checksum hesablansaydı, mənbə
    hələ dəyişməkdə olardı və barmaq izi mənasız çıxardı.
    """

    OPEN_WINDOW = "OPEN_WINDOW"
    DRAIN_BUFFER = "DRAIN_BUFFER"
    PREFLIGHT_CHECKSUM = "PREFLIGHT_CHECKSUM"
    COPY_DATA = "COPY_DATA"
    POSTFLIGHT_CHECKSUM = "POSTFLIGHT_CHECKSUM"
    SWITCH_CONNECTION = "SWITCH_CONNECTION"
    CLOSE_WINDOW = "CLOSE_WINDOW"

    @property
    def label_az(self) -> str:
        return _PHASE_LABELS_AZ[self]

    @property
    def order(self) -> int:
        return _PHASE_ORDER.index(self)


_PHASE_ORDER: Final[tuple[MigrationPhase, ...]] = (
    MigrationPhase.OPEN_WINDOW,
    MigrationPhase.DRAIN_BUFFER,
    MigrationPhase.PREFLIGHT_CHECKSUM,
    MigrationPhase.COPY_DATA,
    MigrationPhase.POSTFLIGHT_CHECKSUM,
    MigrationPhase.SWITCH_CONNECTION,
    MigrationPhase.CLOSE_WINDOW,
)

_PHASE_LABELS_AZ: Final[dict[MigrationPhase, str]] = {
    MigrationPhase.OPEN_WINDOW: "Texniki fasilə açılır (sessiyalar read-only)",
    MigrationPhase.DRAIN_BUFFER: "Offline bufer sinxronlaşdırılır",
    MigrationPhase.PREFLIGHT_CHECKSUM: "Mənbə bazanın barmaq izi hesablanır",
    MigrationPhase.COPY_DATA: "Məlumat köçürülür",
    MigrationPhase.POSTFLIGHT_CHECKSUM: "Hədəf bazanın barmaq izi yoxlanılır",
    MigrationPhase.SWITCH_CONNECTION: "Bağlantı yeni bazaya yönləndirilir",
    MigrationPhase.CLOSE_WINDOW: "Texniki fasilə bağlanır",
}

#: Bütün fazalar — ekranda gedişat göstəricisi üçün.
ALL_PHASES: Final[tuple[MigrationPhase, ...]] = _PHASE_ORDER


class MigrationStatus(str, Enum):
    """`db_migration_events.status` — DB CHECK-i ilə eyni dəyərlər."""

    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        return self is not MigrationStatus.IN_PROGRESS

    @property
    def label_az(self) -> str:
        return {
            MigrationStatus.IN_PROGRESS: "Davam edir",
            MigrationStatus.COMPLETED: "Tamamlandı",
            MigrationStatus.ROLLED_BACK: "Geri qaytarıldı",
            MigrationStatus.FAILED: "Uğursuz",
        }[self]


@dataclass(frozen=True)
class ChecksumPair:
    """Mənbə və hədəf bazanın barmaq izləri."""

    preflight: str
    postflight: str | None = None

    @property
    def matched(self) -> bool:
        """Uyğunluq. `postflight` YOXDURSA `False`.

        Fail-closed: hesablanmamış barmaq izi "uyğun gəlir" sayılsaydı,
        checksum addımının sükutla atlanması miqrasiyanı uğurlu göstərərdi.
        """
        return self.postflight is not None and self.preflight == self.postflight

    @property
    def verdict_az(self) -> str:
        if self.postflight is None:
            return "Hədəf barmaq izi hesablanmayıb"
        return "Barmaq izləri uyğundur" if self.matched else "BARMAQ İZLƏRİ FƏRQLƏNİR"


@dataclass(frozen=True)
class MaintenanceWindow:
    """Texniki fasilə — keçidin YEGANƏ icazəli konteksti (bölmə 2)."""

    opened_at: datetime
    max_minutes: int = MAX_WINDOW_MINUTES
    closed_at: datetime | None = None

    def __post_init__(self) -> None:
        require_aware(self.opened_at, field="opened_at")
        if self.closed_at is not None:
            require_aware(self.closed_at, field="closed_at")
            if self.closed_at < self.opened_at:
                raise MaintenanceWindowError("Fasilənin bağlanması açılışdan əvvəl ola bilməz")
        if not 0 < self.max_minutes <= MAX_WINDOW_MINUTES:
            raise MaintenanceWindowError(
                f"Texniki fasilə 1–{MAX_WINDOW_MINUTES} dəqiqə aralığında olmalıdır"
            )

    @property
    def is_open(self) -> bool:
        return self.closed_at is None

    @property
    def deadline(self) -> datetime:
        return self.opened_at + timedelta(minutes=self.max_minutes)

    def is_expired(self, *, now: datetime) -> bool:
        """Pəncərə vaxtı bitibmi.

        Bitmiş pəncərədə davam etmək istifadəçiləri gözlənildiyindən uzun
        müddət read-only rejimdə saxlayardı — kəsinti planlaşdırıldığından
        uzun olarsa, əməliyyat dayandırılmalıdır.
        """
        require_aware(now, field="now")
        return self.is_open and now > self.deadline

    def remaining_minutes(self, *, now: datetime) -> int:
        require_aware(now, field="now")
        return max(0, int((self.deadline - now).total_seconds() // 60))

    def closed(self, *, now: datetime) -> MaintenanceWindow:
        require_aware(now, field="now")
        return MaintenanceWindow(
            opened_at=self.opened_at, max_minutes=self.max_minutes, closed_at=now
        )


@dataclass(frozen=True)
class MigrationPlan:
    """Keçidin əvvəlcədən göstərilən planı — təsdiq modalının məzmunu.

    Panel bu planı istifadəçiyə GÖSTƏRİR və yalnız təsdiqdən sonra icra
    başlayır: "hara keçirəm, nə qədər sürəcək, nə bloklanacaq" sualları
    klik anında cavablanmalıdır.
    """

    source: DatabaseTarget
    destination: DatabaseTarget
    window_minutes: int = MAX_WINDOW_MINUTES
    drain_timeout_seconds: int = DEFAULT_DRAIN_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.source is self.destination:
            raise MigrationError(
                "Mənbə və hədəf baza eyni ola bilməz",
                user_message="Keçid üçün fərqli baza seçin.",
            )
        if self.drain_timeout_seconds <= 0:
            raise MigrationError("Bufer gözləmə müddəti müsbət olmalıdır")

    def summary_az(self) -> str:
        return (
            f"{self.source.label_az} → {self.destination.label_az}\n"
            f"Texniki fasilə: maks. {self.window_minutes} dəqiqə.\n"
            f"Fasilə ərzində bütün sessiyalar YALNIZ-OXU rejimində olacaq."
        )


__all__ = [
    "ALL_PHASES",
    "DEFAULT_DRAIN_TIMEOUT_SECONDS",
    "MAX_WINDOW_MINUTES",
    "MIN_ROLLBACK_REASON_LENGTH",
    "ChecksumPair",
    "DatabaseTarget",
    "MaintenanceWindow",
    "MaintenanceWindowError",
    "MigrationError",
    "MigrationPhase",
    "MigrationPlan",
    "MigrationStatus",
]
