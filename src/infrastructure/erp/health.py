"""System Health Monitor — server üzrə sətirlər (bölmə 6, 7) — Faza 3.10.

Spesifikasiya bölmə 6: *"SYSTEM HEALTH MONITOR (`can_view_system_health`
flag-i ilə görünür): Real-time DB Ping, 1C Sync Delay **(hər server üzrə
ayrıca)**, Disk Usage, NTP Drift Status."*

Bölmə 7: *"Özü-özünü diaqnostika edən sağlamlıq monitoru: hər server üzrə
problem aşkarlandıqda səbəbi ehtimal edir və birbaşa «[Bu Serverin Ayarlarını
Aç]» düyməsi təklif edir."*

──────────────────────────────────────────────────────────────────────────────
NİYƏ TƏKLİF MƏTNİ BURADA, GUI-DƏ DEYİL
──────────────────────────────────────────────────────────────────────────────
"Səbəbi ehtimal etmək" bir QAYDADIR, rəsm deyil: hansı əlamətin hansı
səbəbə işarə etdiyi (heç vaxt sinxronlaşmayıb → konfiqurasiya; ardıcıl
xətalar → şəbəkə/credential; köhnə sync → server sönüb) məhz burada, test
edilə bilən yerdə saxlanılır. GUI (Faza 5) yalnız mətni göstərir və düyməni
çəkir — eyni məntiqi ikinci dəfə yazmır.

Sağlamlıq STATUSUNUN özü `v_erp_server_health` görünüşündə hesablanır
(migration 004) ki, gələcək telemetriya və hesabatlar eyni tərifi paylaşsın.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from src.shared.logger import get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.value_objects.identifiers import TenantId
    from src.infrastructure.persistence.connection import Database

_log = get_logger(__name__)


class ServerHealth(str, Enum):
    """`v_erp_server_health.health` — görünüşdəki CASE ilə eyni dəyərlər."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    NEVER_SYNCED = "NEVER_SYNCED"
    INACTIVE = "INACTIVE"

    @property
    def needs_attention(self) -> bool:
        """Monitor sətri diqqət çəkən rənglə göstərilirmi.

        `INACTIVE` daxil DEYİL — o, adminin QƏSDƏN verdiyi qərardır, problem
        deyil. Onu xəbərdarlıq kimi göstərmək "həmişə qırmızı" monitor
        yaradardı və real problem itərdi.
        """
        return self in (ServerHealth.DEGRADED, ServerHealth.STALE, ServerHealth.NEVER_SYNCED)


@dataclass(frozen=True)
class ServerHealthRow:
    """Monitorun bir sətri — bir 1C serveri."""

    server_id: str
    server_name: str
    host: str
    health: ServerHealth
    status: str
    consecutive_failures: int
    mapped_stores: int
    sync_interval_seconds: int
    last_successful_sync: datetime | None = None
    sync_delay_seconds: int | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None

    @property
    def diagnosis(self) -> str:
        """Texniki-olmayan dildə ehtimal olunan səbəb (bölmə 7)."""
        if self.health is ServerHealth.INACTIVE:
            return "Server administrator tərəfindən deaktiv edilib."
        if self.health is ServerHealth.NEVER_SYNCED:
            if self.mapped_stores == 0:
                return (
                    "Server heç vaxt sinxronlaşmayıb və ona heç bir mağaza bağlanmayıb — "
                    "əvvəlcə Server↔Mağaza xəritələməsini qurun."
                )
            return (
                "Server heç vaxt sinxronlaşmayıb — bağlantı parametrlərini "
                "«Bağlantını Test Et» ilə yoxlayın."
            )
        if self.health is ServerHealth.STALE:
            return (
                "Uzun müddətdir yeni məlumat gəlmir — 1C serverinin işlək olduğunu "
                "və şəbəkə əlaqəsini yoxlayın."
            )
        if self.health is ServerHealth.DEGRADED:
            return (
                f"Son {self.consecutive_failures} cəhd uğursuz olub — istifadəçi adı/şifrə "
                "və ya şəbəkə əlaqəsi problemi ola bilər."
            )
        return "Server normal işləyir."

    @property
    def suggests_settings(self) -> bool:
        """«[Bu Serverin Ayarlarını Aç]» düyməsi göstərilsinmi."""
        return self.health.needs_attention


class ErpHealthMonitor:
    """`v_erp_server_health` görünüşünü oxuyur."""

    def __init__(self, database: Database, tenant_id: TenantId) -> None:
        self._database = database
        self._tenant_id = tenant_id

    def rows(self) -> list[ServerHealthRow]:
        with self._database.unit_of_work(self._tenant_id) as uow, uow.connection.cursor() as cur:
            cur.execute(
                """
                SELECT server_id, server_name, host, status, health,
                       consecutive_failures, mapped_stores, sync_interval_seconds,
                       last_successful_sync, sync_delay_seconds, last_error, last_error_at
                  FROM v_erp_server_health
                 ORDER BY server_name
                """
            )
            return [_row_to_health(row) for row in cur.fetchall()]

    def problems(self) -> list[ServerHealthRow]:
        """Yalnız diqqət tələb edən sətirlər — bildiriş üçün."""
        return [row for row in self.rows() if row.health.needs_attention]


def _row_to_health(row: dict[str, Any]) -> ServerHealthRow:
    delay = row.get("sync_delay_seconds")
    return ServerHealthRow(
        server_id=str(row["server_id"]),
        server_name=row["server_name"],
        host=row["host"],
        health=ServerHealth(row["health"]),
        status=str(row["status"]),
        consecutive_failures=row.get("consecutive_failures") or 0,
        mapped_stores=row.get("mapped_stores") or 0,
        sync_interval_seconds=row.get("sync_interval_seconds") or 300,
        last_successful_sync=row.get("last_successful_sync"),
        sync_delay_seconds=int(delay) if delay is not None else None,
        last_error=row.get("last_error"),
        last_error_at=row.get("last_error_at"),
    )


__all__ = ["ErpHealthMonitor", "ServerHealth", "ServerHealthRow"]
