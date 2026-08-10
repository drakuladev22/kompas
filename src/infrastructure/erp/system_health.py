"""System Health Monitor — DB ping, disk istifadəsi, NTP sürüşməsi (bölmə 6).

    "SYSTEM HEALTH MONITOR (`can_view_system_health` flag-i ilə görünür):
     Real-time DB Ping, 1C Sync Delay (hər server üzrə ayrıca), Disk Usage,
     NTP Drift Status."

Dörd göstəricinin İKİSİ artıq mövcud idi:
    * 1C Sync Delay — `erp/health.py` (`ErpHealthMonitor`, server üzrə sətir)
    * NTP Drift     — `timekeeping/ntp.py` (`NtpDriftChecker`)

Bu modul qalan ikisini (DB ping, disk) əlavə edir və dördünü BİR görünüşdə
birləşdirir ki, ekran dörd ayrı mənbəyi özü yığmasın.

──────────────────────────────────────────────────────────────────────────────
DİSK NİYƏ MÜHÜMDÜR
──────────────────────────────────────────────────────────────────────────────
Mağaza PC-sində üç şey diskə yazır: offline SQLite buferi, gündəlik loglar və
şəkil yükləmə növbəsi. Disk dolduqda ÜÇÜ də sükutla dayanır — PIN handshake
işləyir, amma yazı getmir. Bu, ən çətin aşkarlanan nasazlıq növüdür, ona görə
xəbərdarlıq həddi (85%) faktiki dolmadan xeyli əvvəldədir.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Final

from src.shared.logger import get_logger

if TYPE_CHECKING:
    from src.infrastructure.erp.health import ServerHealthRow
    from src.infrastructure.persistence.connection import Database

_log = get_logger(__name__)

#: Boş yer bu faizdən aşağı düşərsə xəbərdarlıq, kritikdən aşağı düşərsə xəta.
DISK_WARNING_PERCENT: Final[float] = 85.0
DISK_CRITICAL_PERCENT: Final[float] = 95.0

#: DB ping bu müddətdən uzun çəkərsə "yavaş" sayılır (millisaniyə).
DB_PING_SLOW_MS: Final[int] = 500


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


def disk_metric(path: Path | None = None) -> HealthMetric:
    """Disk istifadəsi — tətbiqin yazdığı diskə görə.

    Ölçmə `Path.cwd()`-dən aparılır (və ya verilmiş yoldan), çünki bizi
    maraqlandıran məhz TƏTBİQİN yazdığı disk-dir, sistem diski deyil —
    mağaza PC-lərində bunlar fərqli ola bilər.
    """
    target = path or Path.cwd()
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

    if used_percent >= DISK_CRITICAL_PERCENT:
        level = HealthLevel.CRITICAL
        detail = (
            "Disk demək olar ki, doludur. Offline bufer, loglar və şəkil "
            "növbəsi yazıla bilməyəcək — yer boşaldın."
        )
    elif used_percent >= DISK_WARNING_PERCENT:
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


def database_metric(database: Database) -> HealthMetric:
    """DB ping — bağlantı canlıdırmı və nə qədər gecikir."""
    from time import perf_counter  # noqa: PLC0415 — yalnız ölçmə anında lazımdır

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
    if elapsed_ms >= DB_PING_SLOW_MS:
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


def ntp_metric(drift_seconds: float | None, *, max_drift: int = 60) -> HealthMetric:
    """NTP sürüşməsi — bölmə 2-dəki `TIME_DRIFT_DETECTED` həddi ilə eyni."""
    if drift_seconds is None:
        return HealthMetric(
            key="ntp",
            title_az="Saat sinxronizasiyası",
            level=HealthLevel.UNKNOWN,
            value_az="Ölçülməyib",
            detail_az="NTP serverinə çatmaq mümkün olmadı (port 123 bağlı ola bilər).",
        )

    drift = abs(drift_seconds)
    if drift > max_drift:
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
    if drift > max_drift / 2:
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
    max_drift: int = 60,
    disk_path: Path | None = None,
) -> SystemHealthSnapshot:
    """Dörd göstəricini bir mənzərədə birləşdirir (bölmə 6)."""
    return SystemHealthSnapshot(
        metrics=[
            database_metric(database),
            ntp_metric(drift_seconds, max_drift=max_drift),
            disk_metric(disk_path),
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
    "DB_PING_SLOW_MS",
    "DISK_CRITICAL_PERCENT",
    "DISK_WARNING_PERCENT",
    "HealthLevel",
    "HealthMetric",
    "SystemHealthSnapshot",
    "build_snapshot",
    "database_metric",
    "disk_metric",
    "ntp_metric",
]
