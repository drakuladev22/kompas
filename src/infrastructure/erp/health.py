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
(migration 004; `connector_type` sütunu migration 050-də əlavə olunub) ki,
gələcək telemetriya və hesabatlar eyni tərifi paylaşsın.

──────────────────────────────────────────────────────────────────────────────
«GECİKMƏ» ÜÇ TİPDƏ ÜÇ FƏRQLİ ŞEYDİR (1c.md)
──────────────────────────────────────────────────────────────────────────────
`sync_delay_seconds` sütunu ŞƏBƏKƏ GECİKMƏSİ DEYİL — o, "son uğurlu
sinxronizasiyadan bəri keçən vaxt"dır və bu tərif hər üç bağlantı növü üçün
eyni dərəcədə mənalıdır (fayl mübadiləsində "faylın nə vaxt oxunduğu").

Şəbəkə gecikməsi yalnız `ConnectionTestResult.elapsed_ms`-dədir və orada da
mənası tipə görə dəyişir: HTTP-də serverin cavab müddəti, COM-da obyektin
qurulma müddəti, faylda isə qovluğun oxunma müddəti. Ona görə mətn
`ConnectorType.latency_meaning_az`-dan gəlir — ekran onu özü uydurmur.

DİAQNOZ MƏTNİ DƏ TİPƏ GÖRƏ DƏYİŞİR: "şəbəkə əlaqəsini yoxlayın" məsləhəti
qovluqdan oxuyan bir server üçün YANILDICIDIR — orada baxılası şey ixrac
tapşırığı və qovluğun əlçatanlığıdır.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from src.domain.value_objects.erp import (
    DEFAULT_SYNC_INTERVAL_SECONDS,
    ConnectorType,
    display_address_for,
)
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
    #: DEFOLT `HTTP` — köhnə sətirlər və `connector_type` sütununu OXUMAYAN
    #: çağıranlar (məs. İdarə Paneli xəbərdarlığı) üçün.
    connector_type: ConnectorType = ConnectorType.HTTP
    #: `erp_servers.port` — yalnız HTTP-də mənalıdır (bax `address`).
    port: int = 0

    @property
    def address(self) -> str:
        """Ekranda göstərilən ünvan — port yalnız HTTP-də görünür.

        Ekran `f"{host}:{port}"` qursaydı, fayl serveri
        «\\\\anbar\\1c_exchange:0» kimi görünərdi. Qayda domendə, `ErpServer.
        display_address`-dədir və burada həmin funksiya İSTİFADƏ OLUNUR —
        ikinci nüsxə yazmaq iki mətnin bir gün ayrılması demək olardı.
        """
        return display_address_for(self.connector_type, self.host, self.port)

    @property
    def latency_meaning_az(self) -> str:
        """Ölçülən müddətin bu tip üçün MƏNASI (bax modul başlığı)."""
        return self.connector_type.latency_meaning_az

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
            return self._stale_diagnosis()
        if self.health is ServerHealth.DEGRADED:
            return self._degraded_diagnosis()
        return "Server normal işləyir."

    def _stale_diagnosis(self) -> str:
        """«Uzun müddətdir məlumat gəlmir» — səbəb tipə görə fərqlidir."""
        if self.connector_type is ConnectorType.FILE_EXCHANGE:
            return (
                "Uzun müddətdir yeni fayl oxunmayıb — 1C-dəki gecəlik ixrac "
                "tapşırığının işlədiyini və mübadilə qovluğunun əlçatan olduğunu "
                "yoxlayın."
            )
        if self.connector_type is ConnectorType.COM:
            return (
                "Uzun müddətdir yeni məlumat gəlmir — 1C platformasının bu kompüterdə "
                "işlək olduğunu və bazanın açıq olduğunu yoxlayın."
            )
        return (
            "Uzun müddətdir yeni məlumat gəlmir — 1C serverinin işlək olduğunu "
            "və şəbəkə əlaqəsini yoxlayın."
        )

    def _degraded_diagnosis(self) -> str:
        """Ardıcıl uğursuzluqlar — ehtimal olunan səbəb tipə görə dəyişir."""
        attempts = f"Son {self.consecutive_failures} cəhd uğursuz olub"
        if self.connector_type is ConnectorType.FILE_EXCHANGE:
            return (
                f"{attempts} — mübadilə qovluğu əlçatmaz ola bilər və ya fayl formatı "
                "gözlənilənə uyğun deyil."
            )
        if self.connector_type is ConnectorType.COM:
            return (
                f"{attempts} — 1C COM komponenti, baza adı və ya istifadəçi/şifrə "
                "problemi ola bilər."
            )
        return f"{attempts} — istifadəçi adı/şifrə və ya şəbəkə əlaqəsi problemi ola bilər."

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
                SELECT server_id, server_name, host, port, connector_type, status, health,
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
        sync_interval_seconds=row.get("sync_interval_seconds") or DEFAULT_SYNC_INTERVAL_SECONDS,
        last_successful_sync=row.get("last_successful_sync"),
        sync_delay_seconds=int(delay) if delay is not None else None,
        last_error=row.get("last_error"),
        last_error_at=row.get("last_error_at"),
        connector_type=ConnectorType.parse(row.get("connector_type")),
        port=int(row.get("port") or 0),
    )


__all__ = ["ErpHealthMonitor", "ServerHealth", "ServerHealthRow"]
