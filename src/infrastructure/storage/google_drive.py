"""`EvidenceStorageProvider`-in Google Drive implementasiyası — Faza 3.9.

Bu sinif üç hissəni birləşdirir:

    `DriveApiClient`  — REST çağırışları
    `FolderResolver`  — `KompasOS/{Mağaza}/{İl-Ay}/` lazy yaradılması
    `ImageCache`      — lokal fayl keşi (ekranda birbaşa göstərmək üçün)

──────────────────────────────────────────────────────────────────────────────
THUMBNAIL NİYƏ DRIVE-DAN DEYİL, LOKAL YARADILIR
──────────────────────────────────────────────────────────────────────────────
Drive-ın `thumbnailLink` sahəsi var, lakin: (a) qısa müddətli imzalı URL-dir,
(b) onu almaq üçün AYRICA `files.get` sorğusu lazımdır, (c) URL-in özünü
çəkmək üçüncü sorğudur. Yəni siyahıdakı hər sətir üçün 2–3 şəbəkə gedişi.

Bunun əvəzinə: yükləmə zamanı şəkil onsuz da kiçildilir (bölmə 6 bunu
tələb edir), oxuma zamanı tam bayt BİR dəfə çəkilib keşlənir, thumbnail
isə həmin baytlardan LOKAL yaradılıb ayrıca keşlənir. Nəticə: ikinci
açılışda şəbəkə sorğusu SIFIRDIR.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import TYPE_CHECKING, Final
from uuid import UUID

from src.domain.value_objects.storage import (
    FULL_MAX_EDGE,
    THUMBNAIL_MAX_EDGE,
    ImageSize,
    QuotaStatus,
    StorageError,
    StorageProviderKind,
    StorageReference,
)
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from src.domain.value_objects.identifiers import StoreId
    from src.infrastructure.storage.drive_api import DriveApiClient
    from src.infrastructure.storage.folder_resolver import FolderResolver
    from src.infrastructure.storage.image_cache import ImageCache

_log = get_logger(__name__)

#: Yükləmə zamanı JPEG keyfiyyəti — 85 gözlə seçilməyən itki verir və
#: faylı orijinaldan ~4–6 dəfə kiçildir.
JPEG_QUALITY: Final[int] = 85
ALLOWED_EXTENSIONS: Final[frozenset[str]] = frozenset({".jpg", ".jpeg", ".png", ".webp"})
#: Bölmə 6: maksimum 5 MB — DEFOLT dəyər.
#:
#: Bu, `system_limits.MAX_UPLOAD_SIZE_BYTES`-in FALLBACK-ıdır, tək həqiqət
#: mənbəyi DEYİL: bölmə 3 həddi Root Control Center-dən idarə olunan limit
#: kimi sadalayır. Provider həddi konstruktorda alır; verilmədikdə bu dəyər
#: işləyir (məs. planlayıcı işləri, tenant konteksti olmayan çağırışlar).
MAX_UPLOAD_BYTES: Final[int] = 5 * 1024 * 1024


class StoreNameResolver:
    """`store_id → mağaza adı` — qovluq adı üçün.

    Ayrıca sinif, çünki provider-in DB-ni tanımasını istəmirik: adları
    çağıran tərəf (use case) verir və ya bu kiçik keş DB-dən oxuyur.
    """

    def __init__(self, names: dict[str, str] | None = None) -> None:
        self._names = dict(names or {})

    def register(self, store_id: StoreId, name: str) -> None:
        self._names[str(store_id)] = name

    def name_for(self, store_id: StoreId) -> str:
        return self._names.get(str(store_id), f"Mağaza-{str(store_id)[:8]}")


class GoogleDriveStorageProvider:
    """Cərimə sübut şəkilləri üçün Drive saxlanması.

    YALNIZ cərimə sübutuna aiddir — profil şəkli və tapşırıq sübutu
    Supabase Storage-da qalır və bu sinifdən KEÇMİR.
    """

    def __init__(
        self,
        *,
        api: DriveApiClient,
        folders: FolderResolver,
        cache: ImageCache,
        connection_id: UUID,
        store_names: StoreNameResolver | None = None,
        max_upload_bytes: int = MAX_UPLOAD_BYTES,
    ) -> None:
        self._api = api
        self._folders = folders
        self._cache = cache
        self._connection_id = connection_id
        self._store_names = store_names or StoreNameResolver()
        # `system_limits.MAX_UPLOAD_SIZE_BYTES` — kompozisiya kökü onu
        # tenant üçün oxuyub ötürür (bax `composition.py`). Sıfır və ya
        # mənfi dəyər həddi SÖNDÜRMÜR, defolta qaytarır: səhv konfiqurasiya
        # 5 MB-lıq qorumanı sükutla itirməməlidir.
        self._max_upload_bytes = max_upload_bytes if max_upload_bytes > 0 else MAX_UPLOAD_BYTES

    # ------------------------------- yükləmə ---------------------------------- #

    def upload(
        self,
        file_bytes: bytes,
        filename: str,
        store_id: StoreId,
        taken_at: datetime,
    ) -> StorageReference:
        self._validate(file_bytes, filename)
        payload, mime = _downscale(file_bytes, FULL_MAX_EDGE)

        folder_id = self._folders.resolve(
            store_id=store_id,
            store_name=self._store_names.name_for(store_id),
            moment=taken_at,
        )
        safe_name = _unique_name(filename, taken_at)
        file_id = self._api.upload_file(
            filename=safe_name, content=payload, parent_id=folder_id, mime_type=mime
        )

        reference = StorageReference.drive(
            file_id=file_id, connection_id=self._connection_id, folder_id=folder_id
        )
        # Yeni yüklənən şəkil dərhal keşə qoyulur: operator cəriməni
        # yaratdıqdan sonra siyahıda onu görmək üçün Drive-a getməsin.
        self._cache.put(reference, ImageSize.FULL, payload)
        return reference

    # -------------------------------- oxuma ----------------------------------- #

    def get_image_bytes(
        self, reference: StorageReference, size: ImageSize = ImageSize.FULL
    ) -> bytes:
        cached = self._cache.get(reference, size)
        if cached is not None:
            return cached

        if reference.provider is not StorageProviderKind.GOOGLE_DRIVE:
            raise StorageError(
                f"Bu provider yalnız Drive istinadlarını oxuyur: {reference.provider.value}",
                context={"provider": reference.provider.value},
            )

        full = self._cache.get(reference, ImageSize.FULL)
        if full is None:
            full = self._api.download_file(reference.file_id)
            self._cache.put(reference, ImageSize.FULL, full)

        if size is ImageSize.FULL:
            return full

        thumbnail, _ = _downscale(full, THUMBNAIL_MAX_EDGE)
        self._cache.put(reference, ImageSize.THUMBNAIL, thumbnail)
        return thumbnail

    # -------------------------------- silmə ----------------------------------- #

    def delete(self, reference: StorageReference) -> bool:
        removed = self._api.delete_file(reference.file_id)
        self._cache.invalidate(reference)
        return removed

    # -------------------------------- kvota ----------------------------------- #

    def quota(self) -> QuotaStatus:
        return self._api.quota()

    # ------------------------------- daxili ----------------------------------- #

    def _validate(self, file_bytes: bytes, filename: str) -> None:
        if not file_bytes:
            raise StorageError("Boş fayl yüklənə bilməz")
        if len(file_bytes) > self._max_upload_bytes:
            megabytes = self._max_upload_bytes // (1024 * 1024)
            raise StorageError(
                f"Şəkil {megabytes} MB-dan böyükdür",
                user_message=f"Şəkil çox böyükdür (maksimum {megabytes} MB).",
                context={"bytes": len(file_bytes), "limit": self._max_upload_bytes},
            )
        suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
        if suffix not in ALLOWED_EXTENSIONS:
            raise StorageError(
                f"Dəstəklənməyən format: {suffix or '(uzantı yoxdur)'}",
                user_message="Yalnız .jpg, .png və .webp formatları qəbul olunur.",
            )


def _unique_name(filename: str, taken_at: datetime) -> str:
    """Eyni adlı iki fayl bir qovluqda qarışmasın deyə vaxt-möhürü əlavə edir.

    Drive eyniadlı fayllara icazə verir (ID-lər fərqlidir), lakin insan
    qovluğa baxanda "photo.jpg" adlı 40 fayl faydasızdır.
    """
    stamp = taken_at.strftime("%Y%m%d-%H%M%S")
    stem = filename.rsplit(".", 1)[0][:60] if "." in filename else filename[:60]
    return f"{stamp}_{stem}.jpg"


def _downscale(data: bytes, max_edge: int) -> tuple[bytes, str]:
    """Şəkli maksimum kənara sığdırır və JPEG-ə çevirir.

    `Pillow` yoxdursa (məs. yalnız domen testləri işləyirsə) orijinal
    baytlar olduğu kimi qaytarılır — kiçiltmə OPTİMALLAŞDIRMADIR, məntiqin
    düzgünlüyü ondan asılı deyil.
    """
    try:
        from PIL import Image  # noqa: PLC0415 - istəyə bağlı asılılıq
    except ImportError:  # pragma: no cover - Pillow layihə asılılığıdır
        _log.warning("PILLOW_UNAVAILABLE", extra={"impact": "şəkil kiçildilmədi"})
        return data, "image/jpeg"

    with Image.open(io.BytesIO(data)) as source:
        # RGB-yə çevirmə MƏCBURİDİR: PNG/WebP alfa kanalı ilə gələ bilər və
        # JPEG alfa dəstəkləmir — çevirmə olmasa `save()` istisna atardı.
        rendered = source.convert("RGB")
        rendered.thumbnail((max_edge, max_edge))
        buffer = io.BytesIO()
        rendered.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buffer.getvalue(), "image/jpeg"


__all__ = [
    "ALLOWED_EXTENSIONS",
    "MAX_UPLOAD_BYTES",
    "GoogleDriveStorageProvider",
    "StoreNameResolver",
]
