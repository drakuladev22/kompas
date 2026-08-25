"""System Health Monitor — DB ping, disk istifadəsi, NTP sürüşməsi (bölmə 6).

    "SYSTEM HEALTH MONITOR (`can_view_system_health` flag-i ilə görünür):
     Real-time DB Ping, 1C Sync Delay (hər server üzrə ayrıca), Disk Usage,
     NTP Drift Status."

Dörd göstəricinin İKİSİ artıq mövcud idi:
    * 1C Sync Delay — `erp/health.py` (`ErpHealthMonitor`, server üzrə sətir)
    * NTP Drift     — `timekeeping/ntp.py` (`NtpDriftChecker`)

Bu modul qalan ikisini (DB ping, disk) əlavə edir və dördünü BİR görünüşdə
birləşdirir ki, ekran dörd ayrı mənbəyi özü yığmasın.

BEŞİNCİ GÖSTƏRİCİ — YADDAŞ (RAM), `v2backlog.md` Faza 5.2: «System Health
Monitor-a disk/RAM-monitorinqi əlavə et». Disk ARTIQ var idi, RAM yox idi.

──────────────────────────────────────────────────────────────────────────────
DİSK NİYƏ MÜHÜMDÜR
──────────────────────────────────────────────────────────────────────────────
Mağaza PC-sində üç şey diskə yazır: offline SQLite buferi, gündəlik loglar və
şəkil yükləmə növbəsi. Disk dolduqda ÜÇÜ də sükutla dayanır — PIN handshake
işləyir, amma yazı getmir. Bu, ən çətin aşkarlanan nasazlıq növüdür, ona görə
xəbərdarlıq həddi (85%) faktiki dolmadan xeyli əvvəldədir.

──────────────────────────────────────────────────────────────────────────────
RAM NİYƏ `psutil` OLMADAN ÖLÇÜLÜR
──────────────────────────────────────────────────────────────────────────────
`psutil` bu layihənin asılılıqlarında YOXDUR və yalnız bir metrik üçün
əlavə edilməsi paketlənmiş `.exe`-ni (SETUP-1) böyüdər, üstəlik binar
uzantı olduğu üçün PyInstaller tərəfində ayrıca hook tələb edərdi. Windows-da
eyni rəqəm `kernel32.GlobalMemoryStatusEx` ilə, Linux-da (CI və test mühiti)
`/proc/meminfo` ilə ONSUZ DA əlçatandır — hər ikisi standart kitabxana ilə
oxunur. Heç biri işləməzsə metrik `UNKNOWN` olur: SÜKUTLA «hər şey qaydasında»
göstərmək ən pis cavabdır.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Final

from src.domain.policies import SystemLimitKey
from src.infrastructure.config.limits import (
    InfrastructureLimits,
    fallback_float,
    fallback_int,
)
from src.shared.data_paths import default_data_dir
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.infrastructure.erp.health import ServerHealthRow
    from src.infrastructure.persistence.connection import Database

_log = get_logger(__name__)

#: DÖRDÜ DƏ FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`HEALTH_DISK_WARNING_PERCENT`, `HEALTH_DISK_CRITICAL_PERCENT`,
#: `HEALTH_DB_PING_SLOW_MS`, `NTP_MAX_DRIFT_SECONDS`; seed: migrations/032,
#: sonuncu `schema.sql`-dədir). Hədlər quraşdırmadan asılıdır: 128 GB SSD-li
#: kioskda "85% doludur" ilə 2 TB serverdə eyni faiz tamamilə fərqli qalıq
#: yer deməkdir, DB ping həddi isə şəbəkə məsafəsi ilə dəyişir.
FALLBACK_DISK_WARNING_PERCENT: Final[float] = fallback_float(
    SystemLimitKey.HEALTH_DISK_WARNING_PERCENT
)
FALLBACK_DISK_CRITICAL_PERCENT: Final[float] = fallback_float(
    SystemLimitKey.HEALTH_DISK_CRITICAL_PERCENT
)
FALLBACK_DB_PING_SLOW_MS: Final[int] = fallback_int(SystemLimitKey.HEALTH_DB_PING_SLOW_MS)
FALLBACK_MAX_DRIFT_SECONDS: Final[int] = fallback_int(SystemLimitKey.NTP_MAX_DRIFT_SECONDS)
#: Yaddaş hədləri — Faza 5.2. Disk ilə EYNİ səbəbdən Root parametridir
#: (`migrations/100`): 4 GB-lıq kiosk ilə 32 GB-lıq serverdə eyni faiz tamam
#: fərqli qalıq deməkdir.
FALLBACK_MEMORY_WARNING_PERCENT: Final[float] = fallback_float(
    SystemLimitKey.HEALTH_MEMORY_WARNING_PERCENT
)
FALLBACK_MEMORY_CRITICAL_PERCENT: Final[float] = fallback_float(
    SystemLimitKey.HEALTH_MEMORY_CRITICAL_PERCENT
)


class HealthLevel(str, Enum):
    """Göstəricinin vəziyyəti — ekranda rəng bunu izləyir."""

    OK = "OK"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"

    @property
    def needs_attention(self) -> bool:
        return self in (HealthLevel.WARNING, HealthLevel.CRITICAL)


@dataclass(frozen=True)
class HealthMetric:
    """Bir göstərici — ekranın bir sətri."""

    key: str
    title_az: str
    level: HealthLevel
    value_az: str
    detail_az: str = ""

    @property
    def is_ok(self) -> bool:
        return self.level is HealthLevel.OK


@dataclass(frozen=True)
class SystemHealthSnapshot:
    """Dörd göstəricinin bir anlıq mənzərəsi."""

    metrics: list[HealthMetric]
    servers: list[ServerHealthRow]

    @property
    def worst_level(self) -> HealthLevel:
        """Ekranın başlığındakı ümumi vəziyyət."""
        if any(metric.level is HealthLevel.CRITICAL for metric in self.metrics):
            return HealthLevel.CRITICAL
        if any(metric.level.needs_attention for metric in self.metrics):
            return HealthLevel.WARNING
        if any(row.health.needs_attention for row in self.servers):
            return HealthLevel.WARNING
        return HealthLevel.OK

    @property
    def problem_count(self) -> int:
        return sum(1 for metric in self.metrics if metric.level.needs_attention) + sum(
            1 for row in self.servers if row.health.needs_attention
        )


def _existing_ancestor(path: Path) -> Path:
    """Yolun özü, mövcud deyilsə mövcud olan ən yaxın ana qovluq.

    Kök qovluğa qədər qalxır və onu qaytarır: kök də yoxdursa (disk qopub)
    çağıran tərəf `OSError` alacaq və metrik «Ölçülə bilmədi» olacaq — bu,
    həmin halda DÜZGÜN cavabdır.
    """
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return path


def disk_metric(
    path: Path | None = None, *, limits: InfrastructureLimits | None = None
) -> HealthMetric:
    """Disk istifadəsi — tətbiqin yazdığı diskə görə.

    Ölçmə MƏLUMAT QOVLUĞUNDAN aparılır (və ya verilmiş yoldan), çünki bizi
    maraqlandıran məhz TƏTBİQİN yazdığı disk-dir, sistem diski deyil —
    mağaza PC-lərində bunlar fərqli ola bilər.

    Əvvəl `Path.cwd()` işlədilirdi və bu, sənədləşdirilmiş məqsədə ZİDD idi:
    qısayoldan açılan `.exe`-də CWD `C:\\Windows\\System32`, kiosk
    alt-prosesində isə `C:\\Program Files\\KompasOS` olur — hər ikisi
    proqramın heç nə YAZMADIĞI yerlərdir (SETUP-1).

    İlk açılışda məlumat qovluğu hələ yaradılmamış ola bilər; belə halda
    mövcud olan ən yaxın ANA qovluq ölçülür. `shutil.disk_usage` olmayan yolda
    istisna atır və metrik «Ölçülə bilmədi» olardı — yəni xəbərdarlıq məhz ən
    çox lazım olan anda (təzə quraşdırma, dolu disk) susardı.

    `limits` verilməzsə fallback hədlər işləyir: monitorun ÖZÜ baza
    əlçatmazlığında da cavab verməlidir — əks halda "baza cavab vermir"
    diaqnozunu göstərəcək ekran həmin bazadan asılı olardı.
    """
    resolved = limits or InfrastructureLimits()
    warning_percent = resolved.float_of(SystemLimitKey.HEALTH_DISK_WARNING_PERCENT)
    critical_percent = resolved.float_of(SystemLimitKey.HEALTH_DISK_CRITICAL_PERCENT)
    target = path or _existing_ancestor(default_data_dir())
    try:
        usage = shutil.disk_usage(target)
    except OSError as exc:
        _log.warning("DISK_USAGE_UNAVAILABLE", extra={"path": str(target), "error": str(exc)})
        return HealthMetric(
            key="disk",
            title_az="Disk istifadəsi",
            level=HealthLevel.UNKNOWN,
            value_az="Ölçülə bilmədi",
            detail_az=str(target),
        )

    used_percent = (usage.used / usage.total * 100) if usage.total else 0.0
    free_gb = usage.free / (1024**3)

    if used_percent >= critical_percent:
        level = HealthLevel.CRITICAL
        detail = (
            "Disk demək olar ki, doludur. Offline bufer, loglar və şəkil "
            "növbəsi yazıla bilməyəcək — yer boşaldın."
        )
    elif used_percent >= warning_percent:
        level = HealthLevel.WARNING
        detail = "Disk dolmağa yaxındır — köhnə log və nüsxələri təmizləyin."
    else:
        level = HealthLevel.OK
        detail = ""

    return HealthMetric(
        key="disk",
        title_az="Disk istifadəsi",
        level=level,
        value_az=f"{used_percent:.0f}% dolu · {free_gb:.1f} GB boş",
        detail_az=detail,
    )


def read_memory_usage() -> tuple[float, float] | None:
    """(istifadə faizi, boş GB) və ya ölçülə bilmirsə `None`.

    İKİ YOL, PLATFORMAYA GÖRƏ (bax modul başlığı). Heç biri işləməzsə `None`
    qaytarılır — istisna ATILMIR, çünki bu funksiya sağlamlıq ekranının
    çəkilmə yolundadır və orada atılan istisna «monitorun özü çökdü»
    deməkdir: ən çox lazım olan anda ekran açılmazdı.
    """
    # `os.name` işlədilir, `sys.platform` YOX: `sys.platform == "win32"`
    # müqayisəsini mypy PLATFORMAYA GÖRƏ həll edir və Windows-da yoxlanışda
    # Linux yolu «əlçatmaz kod» kimi işarələnir — halbuki hər iki yol
    # istehsalatda da, testdə də canlıdır.
    if os.name == "nt":
        return _windows_memory()
    return _proc_meminfo_memory()


def _windows_memory() -> tuple[float, float] | None:
    """`GlobalMemoryStatusEx` — `psutil`-in Windows-da oxuduğu EYNİ mənbə."""
    import ctypes  # noqa: PLC0415 — yalnız Windows yolunda lazımdır

    class _MemoryStatusEx(ctypes.Structure):
        # `ctypes.Structure` sahə cədvəlinin TƏLƏB etdiyi formadır.
        _fields_ = (
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        )

    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(_MemoryStatusEx)
    try:
        kernel32 = ctypes.WinDLL("kernel32")  # type: ignore[attr-defined,unused-ignore]
        ok = kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    except (AttributeError, OSError) as exc:  # pragma: no cover — yalnız Windows-da
        _log.warning("MEMORY_USAGE_UNAVAILABLE", extra={"error": str(exc)})
        return None
    if not ok:  # pragma: no cover — API uğursuzluğu
        return None
    return float(status.dwMemoryLoad), status.ullAvailPhys / (1024**3)


def _proc_meminfo_memory() -> tuple[float, float] | None:
    """Linux/`/proc/meminfo` — CI və test mühiti bu yolu işlədir.

    `MemAvailable` seçilir, `MemFree` YOX: `MemFree` keş və buferləri «dolu»
    sayır və Linux-da praktik olaraq HƏMİŞƏ kiçikdir — o rəqəmlə hər sistem
    daim KRİTİK görünərdi.
    """
    try:
        raw = Path("/proc/meminfo").read_text(encoding="utf-8")
    except OSError:
        return None
    values: dict[str, int] = {}
    for line in raw.splitlines():
        name, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[name] = int(parts[0])  # kB
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable")
    if not total or available is None:
        return None
    used_percent = (total - available) / total * 100
    return used_percent, available / (1024**2)


def memory_metric(
    *,
    limits: InfrastructureLimits | None = None,
    reader: Callable[[], tuple[float, float] | None] | None = None,
) -> HealthMetric:
    """Yaddaş (RAM) istifadəsi — `v2backlog.md` Faza 5.2.

    `reader` YALNIZ test üçün deyil: kiosk PC-lərində gələcəkdə fərqli ölçmə
    mənbəyi (məs. aparat agentindən gələn dəyər) qoşula bilər və o zaman bu
    funksiya dəyişmir. `disk_metric`-in `path` parametri ilə eyni növ giriş.
    """
    resolved = limits or InfrastructureLimits()
    warning_percent = resolved.float_of(SystemLimitKey.HEALTH_MEMORY_WARNING_PERCENT)
    critical_percent = resolved.float_of(SystemLimitKey.HEALTH_MEMORY_CRITICAL_PERCENT)
    measured = (reader or read_memory_usage)()
    if measured is None:
        return HealthMetric(
            key="memory",
            title_az="Yaddaş (RAM)",
            level=HealthLevel.UNKNOWN,
            value_az="Ölçülə bilmədi",
            detail_az="Bu platformada yaddaş ölçüsü oxunmur.",
        )

    used_percent, free_gb = measured
    if used_percent >= critical_percent:
        level = HealthLevel.CRITICAL
        detail = (
            "Yaddaş demək olar ki, doludur. Tətbiq yavaşlayacaq və ya "
            "əməliyyat sistemi tərəfindən dayandırıla bilər — PC-ni yenidən "
            "başladın və artıq proqramları bağlayın."
        )
    elif used_percent >= warning_percent:
        level = HealthLevel.WARNING
        detail = "Yaddaş dolmağa yaxındır — açıq proqramları bağlayın."
    else:
        level = HealthLevel.OK
        detail = ""

    return HealthMetric(
        key="memory",
        title_az="Yaddaş (RAM)",
        level=level,
        value_az=f"{used_percent:.0f}% dolu · {free_gb:.1f} GB boş",
        detail_az=detail,
    )


def database_metric(
    database: Database, *, limits: InfrastructureLimits | None = None
) -> HealthMetric:
    """DB ping — bağlantı canlıdırmı və nə qədər gecikir."""
    from time import perf_counter  # noqa: PLC0415 — yalnız ölçmə anında lazımdır

    slow_ms = (limits or InfrastructureLimits()).int_of(SystemLimitKey.HEALTH_DB_PING_SLOW_MS)
    started = perf_counter()
    try:
        healthy = database.health_check()
    except Exception as exc:
        _log.warning("DB_PING_FAILED", extra={"error": str(exc)})
        return HealthMetric(
            key="database",
            title_az="Baza bağlantısı",
            level=HealthLevel.CRITICAL,
            value_az="Əlçatmaz",
            detail_az="Bazaya qoşulmaq mümkün olmadı — şəbəkə və konfiqurasiyanı yoxlayın.",
        )

    elapsed_ms = int((perf_counter() - started) * 1000)
    if not healthy:
        return HealthMetric(
            key="database",
            title_az="Baza bağlantısı",
            level=HealthLevel.CRITICAL,
            value_az="Cavab vermir",
            detail_az="Bağlantı var, lakin sorğu uğursuz oldu.",
        )
    if elapsed_ms >= slow_ms:
        return HealthMetric(
            key="database",
            title_az="Baza bağlantısı",
            level=HealthLevel.WARNING,
            value_az=f"{elapsed_ms} ms (yavaş)",
            detail_az="Şəbəkə gecikməsi yüksəkdir — ekranlar ləng açıla bilər.",
        )
    return HealthMetric(
        key="database",
        title_az="Baza bağlantısı",
        level=HealthLevel.OK,
        value_az=f"{elapsed_ms} ms",
    )


def ntp_metric(
    drift_seconds: float | None,
    *,
    max_drift: int | None = None,
    limits: InfrastructureLimits | None = None,
) -> HealthMetric:
    """NTP sürüşməsi — bölmə 2-dəki `TIME_DRIFT_DETECTED` həddi ilə eyni.

    `max_drift` AÇIQ verilməzsə `NTP_MAX_DRIFT_SECONDS` ROOT açarından oxunur
    — həmin açarı `timekeeping/ntp.py` və `leave_verification` da işlədir,
    yəni monitorun göstərdiyi hədd bloklamanın FAKTİKİ həddi ilə eynidir.
    Ayrı ədəd saxlasaydıq, ekran "normaldır" deyəndə axın bloklana bilərdi.
    """
    threshold = (
        max_drift
        if max_drift is not None
        else (limits or InfrastructureLimits()).int_of(SystemLimitKey.NTP_MAX_DRIFT_SECONDS)
    )
    if drift_seconds is None:
        return HealthMetric(
            key="ntp",
            title_az="Saat sinxronizasiyası",
            level=HealthLevel.UNKNOWN,
            value_az="Ölçülməyib",
            detail_az="NTP serverinə çatmaq mümkün olmadı (port 123 bağlı ola bilər).",
        )

    drift = abs(drift_seconds)
    if drift > threshold:
        return HealthMetric(
            key="ntp",
            title_az="Saat sinxronizasiyası",
            level=HealthLevel.CRITICAL,
            value_az=f"{drift:.0f} san fərq",
            detail_az=(
                "TIME_DRIFT_DETECTED — PIN handshake və vaxt düzəlişi BLOKLANIB. "
                "Kompüterin saatını NTP ilə sinxronlaşdırın."
            ),
        )
    if drift > threshold / 2:
        return HealthMetric(
            key="ntp",
            title_az="Saat sinxronizasiyası",
            level=HealthLevel.WARNING,
            value_az=f"{drift:.0f} san fərq",
            detail_az="Sürüşmə həddə yaxınlaşır — saat mənbəyini yoxlayın.",
        )
    return HealthMetric(
        key="ntp",
        title_az="Saat sinxronizasiyası",
        level=HealthLevel.OK,
        value_az=f"{drift:.0f} san fərq",
    )


def build_snapshot(
    *,
    database: Database,
    servers: list[ServerHealthRow],
    drift_seconds: float | None,
    max_drift: int | None = None,
    disk_path: Path | None = None,
    limits: InfrastructureLimits | None = None,
    memory_reader: Callable[[], tuple[float, float] | None] | None = None,
) -> SystemHealthSnapshot:
    """BEŞ göstəricini bir mənzərədə birləşdirir (bölmə 6 + Faza 5.2 RAM).

    `limits` BİR DƏFƏ həll olunur və dörd göstəriciyə ötürülür: eyni anlıq
    mənzərənin sətirləri EYNİ konfiqurasiyanı görməlidir (Root ölçmə
    ortasında dəyəri dəyişsə, ekranda yarısı köhnə hədlə hesablanardı).

    RAM sətri diskin DƏRHAL ARDINCA gəlir — ikisi eyni sualın («bu PC-nin
    resursu tükənirmi?») iki üzüdür və ekranda ayrı yerlərə düşsəydi operator
    onları bir problem kimi oxumazdı.
    """
    resolved = limits or InfrastructureLimits()
    return SystemHealthSnapshot(
        metrics=[
            database_metric(database, limits=resolved),
            ntp_metric(drift_seconds, max_drift=max_drift, limits=resolved),
            disk_metric(disk_path, limits=resolved),
            memory_metric(limits=resolved, reader=memory_reader),
            _sync_summary(servers),
        ],
        servers=servers,
    )


def _sync_summary(servers: list[ServerHealthRow]) -> HealthMetric:
    """1C sinxronizasiyasının XÜLASƏSİ — detallar server sətirlərindədir."""
    if not servers:
        return HealthMetric(
            key="erp_sync",
            title_az="1C sinxronizasiyası",
            level=HealthLevel.UNKNOWN,
            value_az="Server əlavə edilməyib",
            detail_az="ERP panelindən ən azı bir 1C serveri əlavə edin.",
        )

    problems = [row for row in servers if row.health.needs_attention]
    if not problems:
        return HealthMetric(
            key="erp_sync",
            title_az="1C sinxronizasiyası",
            level=HealthLevel.OK,
            value_az=f"{len(servers)} server normal",
        )
    return HealthMetric(
        key="erp_sync",
        title_az="1C sinxronizasiyası",
        level=HealthLevel.WARNING,
        value_az=f"{len(problems)}/{len(servers)} server diqqət tələb edir",
        detail_az="; ".join(f"{row.server_name}: {row.diagnosis}" for row in problems[:3]),
    )


__all__ = [
    "FALLBACK_DB_PING_SLOW_MS",
    "FALLBACK_DISK_CRITICAL_PERCENT",
    "FALLBACK_DISK_WARNING_PERCENT",
    "FALLBACK_MAX_DRIFT_SECONDS",
    "FALLBACK_MEMORY_CRITICAL_PERCENT",
    "FALLBACK_MEMORY_WARNING_PERCENT",
    "HealthLevel",
    "HealthMetric",
    "SystemHealthSnapshot",
    "build_snapshot",
    "database_metric",
    "disk_metric",
    "memory_metric",
    "ntp_metric",
    "read_memory_usage",
]
