"""Plugin API müqavilələri (spesifikasiya bölmə 1) — Faza 2.7.

SANDBOX QAYDASI (spesifikasiyadan):
    "Plugin-lər ayrıca prosesdə icra olunur, birbaşa DB credentials-a çıxışı
    olmur, yalnız whitelisted API səthi üzərindən işləyir. Yalnız Root/CEO
    tərəfindən rəqəmsal imza ilə təsdiqlənmiş plugin-lər yüklənə bilər."

ÜÇ MÜDAFİƏ QATI:
    1. **İmza** — yüklənmədən ƏVVƏL Ed25519 imzası yoxlanılır.
    2. **Proses izolyasiyası** — plugin ayrı `subprocess`-də işləyir; host-un
       yaddaşına, DB bağlantısına və mühit dəyişənlərinə çıxışı YOXDUR.
    3. **Whitelist API** — plugin yalnız açıq şəkildə icazə verilmiş metodları
       çağıra bilir; hər çağırış icazə flag-i ilə yoxlanılır.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.shared.exceptions import KompasOSError


class PluginError(KompasOSError):
    """Plugin əməliyyatı uğursuz oldu."""

    user_message = "Plugin yüklənə bilmədi."


class PluginSignatureError(PluginError):
    """Rəqəmsal imza yoxdur, yararsızdır və ya naməlum açarla verilib."""

    user_message = "Plugin imzası etibarsızdır — yüklənmə bloklandı."


class PluginPermissionError(PluginError):
    """Plugin whitelist-də olmayan API-yə müraciət etdi."""

    user_message = "Plugin icazəsi olmayan əməliyyat tələb etdi."


class PluginTimeoutError(PluginError):
    """Plugin cavab vermədi — proses dayandırıldı."""

    user_message = "Plugin cavab vermir və dayandırıldı."


class PluginStatus(str, Enum):
    """`plugins.status` ilə eyni."""

    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISABLED = "DISABLED"


class PluginCapability(str, Enum):
    """Whitelist API səthi — plugin YALNIZ bunları çağıra bilər.

    DİQQƏT: bu siyahıda DB bağlantısı, fayl sistemi, şəbəkə və ya sirr
    oxumaq YOXDUR və heç vaxt olmamalıdır. Plugin məlumatı yalnız host-un
    verdiyi hazır DTO-lar üzərindən görür.
    """

    #: Yalnız-oxu aqreqasiya edilmiş məlumat (PII YOX).
    READ_AGGREGATED_METRICS = "read_aggregated_metrics"
    #: Dashboard-a custom widget əlavə etmək.
    RENDER_WIDGET = "render_widget"
    #: Menyuya custom səhifə qeydiyyatı.
    REGISTER_PAGE = "register_page"
    #: 3-cü tərəf ERP konnektoru — host tərəfindən idarə olunan sorğu.
    ERP_TRANSFORM = "erp_transform"
    #: Hesabat üçün məlumat çevirmə (saf funksiya).
    REPORT_TRANSFORM = "report_transform"


@dataclass(frozen=True)
class PluginManifest:
    """Plugin-in özünü təqdim etdiyi metadata (`plugins.manifest`)."""

    name: str
    version: str
    publisher: str
    capabilities: frozenset[PluginCapability]
    entry_point: str
    description_az: str = ""
    #: Plugin-in tələb etdiyi icazə flag-ləri — host bunları istifadəçidə yoxlayır.
    required_flags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise PluginError("Plugin adı boş ola bilməz")
        if not self.capabilities:
            raise PluginError(
                f"'{self.name}': heç bir capability tələb edilmir — plugin mənasızdır"
            )
        unknown = {c for c in self.capabilities if not isinstance(c, PluginCapability)}
        if unknown:
            raise PluginPermissionError(f"'{self.name}': naməlum capability: {unknown}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "publisher": self.publisher,
            "capabilities": sorted(c.value for c in self.capabilities),
            "entry_point": self.entry_point,
            "description_az": self.description_az,
            "required_flags": sorted(self.required_flags),
        }


@dataclass(frozen=True)
class PluginRequest:
    """Plugin-dən host-a gələn çağırış."""

    capability: PluginCapability
    payload: dict[str, Any]


@dataclass(frozen=True)
class PluginResponse:
    """Host-dan plugin-ə qayıdan cavab."""

    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None


__all__ = [
    "PluginCapability",
    "PluginError",
    "PluginManifest",
    "PluginPermissionError",
    "PluginRequest",
    "PluginResponse",
    "PluginSignatureError",
    "PluginStatus",
    "PluginTimeoutError",
]
