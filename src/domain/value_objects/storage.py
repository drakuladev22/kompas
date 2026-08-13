"""Sübut şəkli saxlanma istinadları (spesifikasiya bölmə 4, 6).

──────────────────────────────────────────────────────────────────────────────
NİYƏ "ISTINAD" (REFERENCE), URL DEYİL
──────────────────────────────────────────────────────────────────────────────
Əvvəlki model `fines.photo_evidence_url` — bir mətn sahəsi — idi. Google
Drive-a keçidlə bu kifayət etmir, çünki fayl İKİ məlumatla tapılır:

    * hansı Drive HESABINDA (bağlantı) olduğu, və
    * həmin hesabda faylın ID-si.

Bağlantı ID-si olmasa, admin Drive dolduqda yeni hesab qoşan kimi BÜTÜN köhnə
şəkillərə keçid qırılardı — sistem onları yeni hesabda axtarardı və tapmazdı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `get_access_url` YOXDUR
──────────────────────────────────────────────────────────────────────────────
Fayllar qəsdən PRIVATE saxlanılır ("linki olan hər kəs" paylaşımı YOXDUR),
çünki bunlar işçilərin iş yerindəki şəkilləridir. Private fayl üçün "linki
ver" strategiyası işləmir: Google autentifikasiyasız sorğunu bloklayır.
Ona görə istinad yalnız `bytes` gətirmək üçün istifadə olunur.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final
from uuid import UUID

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.shared.exceptions import KompasOSError

#: `KompasOS/{Mağaza}/{İl-Ay}/` iyerarxiyasının kök qovluğu.
DRIVE_ROOT_FOLDER_NAME: Final[str] = "KompasOS"

#: Siyahı görünüşlərində göstərilən kiçik şəklin maksimum kənarı (piksel).
#: FALLBACK — HƏQİQİ MƏNBƏ `system_limits.EVIDENCE_THUMBNAIL_MAX_EDGE_PX`
#: (seed: migrations/033).
THUMBNAIL_MAX_EDGE: Final[int] = int(DEFAULT_LIMITS[SystemLimitKey.EVIDENCE_THUMBNAIL_MAX_EDGE_PX])
#: Yükləmə zamanı tam ölçünün maksimum kənarı — 5 MB-lıq orijinal hər dəfə
#: şəbəkədən çəkilməsin deyə (bölmə 6 onsuz da "avtomatik kiçildilmə" tələb edir).
#: FALLBACK — HƏQİQİ MƏNBƏ `system_limits.EVIDENCE_FULL_MAX_EDGE_PX`. Kənarın
#: özü Drive kvotası ilə mübahisədə şəklin oxunaqlığı arasındakı balansdır —
#: hər ikisi müəssisədən asılıdır, ona görə koda yazılmır.
FULL_MAX_EDGE: Final[int] = int(DEFAULT_LIMITS[SystemLimitKey.EVIDENCE_FULL_MAX_EDGE_PX])


class StorageError(KompasOSError):
    """Sübut şəklinin saxlanması/oxunması uğursuz oldu."""

    user_message = "Sübut şəkli ilə əlaqədə problem yarandı."


class StorageProviderKind(str, Enum):
    """Şəklin harada saxlandığı.

    `SUPABASE_STORAGE` köçürülmədən ƏVVƏLKİ cərimələr üçün qalır — həmin
    şəkillər yerlərində oxunmağa davam edir, geriyə köçürülmür.
    """

    GOOGLE_DRIVE = "GOOGLE_DRIVE"
    SUPABASE_STORAGE = "SUPABASE_STORAGE"


class ImageSize(str, Enum):
    """Hansı ölçünün istənildiyi.

    Siyahılarda (Cərimələrim, Cərimələr) `THUMBNAIL`, şəklə klikləndikdə
    `FULL` istifadə olunur — 50 sətirlik siyahı üçün 50 tam şəkil çəkmək
    həm yavaş, həm də Drive kvotası baxımından israfdır.
    """

    THUMBNAIL = "THUMBNAIL"
    FULL = "FULL"


@dataclass(frozen=True)
class StorageReference:
    """Bir sübut şəklinin ünvanı.

    DB-də üç sütuna açılır: `evidence_drive_file_id`,
    `evidence_drive_connection_id` və (köhnə qeydlər üçün)
    `photo_evidence_url`.
    """

    provider: StorageProviderKind
    file_id: str
    #: Hansı Drive hesabı. `SUPABASE_STORAGE` üçün `None`.
    connection_id: UUID | None = None
    #: Yerləşdiyi qovluq — diaqnostika və "Drive-da aç" düyməsi üçün.
    folder_id: str | None = None

    def __post_init__(self) -> None:
        if not self.file_id.strip():
            raise StorageError("Fayl identifikatoru boş ola bilməz")
        if self.provider is StorageProviderKind.GOOGLE_DRIVE and self.connection_id is None:
            # Bu, tam olaraq yuxarıda təsvir olunan səhvdir: bağlantısız
            # Drive istinadı hesab dəyişdikdən sonra tapılmaz olur.
            raise StorageError(
                "Drive istinadı `connection_id` olmadan yaradıla bilməz — "
                "hesab dəyişdikdə fayl tapılmazdı",
                context={"file_id": self.file_id},
            )

    @classmethod
    def drive(
        cls, *, file_id: str, connection_id: UUID, folder_id: str | None = None
    ) -> StorageReference:
        return cls(
            provider=StorageProviderKind.GOOGLE_DRIVE,
            file_id=file_id,
            connection_id=connection_id,
            folder_id=folder_id,
        )

    @classmethod
    def legacy_supabase(cls, url: str) -> StorageReference:
        """Köçürülmədən əvvəlki `photo_evidence_url` qeydləri üçün."""
        return cls(provider=StorageProviderKind.SUPABASE_STORAGE, file_id=url)

    @property
    def cache_key(self) -> str:
        """Lokal fayl-keşi üçün sabit açar."""
        return f"{self.provider.value}:{self.connection_id or '-'}:{self.file_id}"

    def __str__(self) -> str:
        return self.cache_key


@dataclass(frozen=True)
class QuotaStatus:
    """Drive hesabının yer vəziyyəti (bölmə 7 — dəstək yükünü azaldır)."""

    used_bytes: int
    total_bytes: int | None

    @property
    def usage_ratio(self) -> float:
        """0.0–1.0. Limitsiz hesab (`total_bytes is None`) → 0.0."""
        if not self.total_bytes:
            return 0.0
        return min(1.0, self.used_bytes / self.total_bytes)

    @property
    def percent(self) -> int:
        return round(self.usage_ratio * 100)

    @property
    def is_full(self) -> bool:
        return self.usage_ratio >= 1.0


__all__ = [
    "DRIVE_ROOT_FOLDER_NAME",
    "FULL_MAX_EDGE",
    "THUMBNAIL_MAX_EDGE",
    "ImageSize",
    "QuotaStatus",
    "StorageError",
    "StorageProviderKind",
    "StorageReference",
]
