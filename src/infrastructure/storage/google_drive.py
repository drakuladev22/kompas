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
#: mənbəyi DEYİL: bölmə 3 həddi ROOT İdarə Mərkəzindən idarə olunan limit
#: kimi sadalayır. Provider həddi konstruktorda alır; verilmədikdə bu dəyər
#: işləyir (məs. planlayıcı işləri, tenant konteksti olmayan çağırışlar).
MAX_UPLOAD_BYTES: Final[int] = 5 * 1024 * 1024

#: Tanınan şəkil formatlarının imza baytları.
#:
#: NİYƏ UZANTI KİFAYƏT ETMİR — uzantı fayl adının bir hissəsidir, yəni onu
#: yazan tərəf seçir: `zerarli.exe` → `sekil.jpg` adı ilə növbəyə düşə bilər.
#: Məzmun yoxlaması indiyədək YALNIZ Pillow-un `Image.open()` çağırışında
#: dolayı yolla baş verirdi; Pillow isə istəyə bağlı asılılıqdır
#: (`_downscale` onun yoxluğunda baytları olduğu kimi buraxır) — yəni tək
#: qat idi. İmza yoxlaması Pillow-dan ASILI OLMAYAN ikinci qatdır.
#:
#: WEBP siyahıdadır, çünki `ALLOWED_EXTENSIONS` onu qəbul edir; imzası
#: `RIFF....WEBP` şəklindədir və ayrıca yoxlanılır.
_JPEG_MAGIC: Final[bytes] = b"\xff\xd8\xff"
_PNG_MAGIC: Final[bytes] = b"\x89PNG\r\n\x1a\n"
_RIFF_MAGIC: Final[bytes] = b"RIFF"
_WEBP_TAG: Final[bytes] = b"WEBP"


class EvidenceValidationError(StorageError):
    """Fayl sübut şəkli ola bilməz — TƏKRAR CƏHD nəticəni dəyişməz.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ AYRICA SİNİF
    ──────────────────────────────────────────────────────────────────────────
    `StorageError`-un digər törəmələri (`DriveApiError`, `DriveQuotaExceeded
    Error`, `NoActiveDriveConnectionError`) MÜVƏQQƏTİdir: şəbəkə qayıdanda və
    ya admin yeni hesab qoşanda eyni bayt uğurla yüklənir. Ölçü/uzantı/imza
    pozuntusu isə heç vaxt düzəlmir — onu adi nasazlıqla eyni yola salmaq
    sonsuz retry dövrəsi yaradır (bax `upload_queue.mark_rejected`).

    `StorageError`-dan miras alır ki, mövcud tutucular (`except StorageError`,
    `except KompasOSError`) və `user_message` axını POZULMASIN.
    """


def validate_evidence_payload(
    file_bytes: bytes, filename: str, *, max_bytes: int = MAX_UPLOAD_BYTES
) -> None:
    """Sübut şəklinin ölçü/uzantı/imza yoxlaması — qayda BİR yerdədir.

    Həm provider (`GoogleDriveStorageProvider._validate`), həm də lokal növbə
    (`EvidenceUploadQueue.enqueue`) bunu çağırır. Qayda iki yerdə təkrar
    yazılsaydı, biri dəyişəndə digəri sükutla köhnə qalardı; halbuki növbə
    yararsız faylı diskə yazır və provider onu sonradan rədd edir — iki tərəf
    EYNİ cavabı verməlidir.

    Raises:
        EvidenceValidationError: Fayl qəbul edilə bilməz (daimi qərar).
    """
    if not file_bytes:
        raise EvidenceValidationError("Boş fayl yüklənə bilməz")
    if len(file_bytes) > max_bytes:
        megabytes = max_bytes // (1024 * 1024)
        raise EvidenceValidationError(
            f"Şəkil {megabytes} MB-dan böyükdür",
            user_message=f"Şəkil çox böyükdür (maksimum {megabytes} MB).",
            context={"bytes": len(file_bytes), "limit": max_bytes},
        )
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if suffix not in ALLOWED_EXTENSIONS:
        raise EvidenceValidationError(
            f"Dəstəklənməyən format: {suffix or '(uzantı yoxdur)'}",
            user_message="Yalnız .jpg, .png və .webp formatları qəbul olunur.",
        )
    if not _looks_like_image(file_bytes):
        raise EvidenceValidationError(
            "Fayl məzmunu şəkil deyil",
            user_message="Seçilmiş fayl şəkil deyil (JPEG, PNG və ya WEBP olmalıdır).",
            context={"head": file_bytes[:4].hex()},
        )


def _looks_like_image(data: bytes) -> bool:
    """İlk baytlar tanınan şəkil imzasına uyğundurmu.

    İmza UZANTI ilə tutuşdurulmur (məs. `.jpg` adlı PNG rədd edilmir): belə
    uyğunsuzluq zərərsizdir və onsuz da `_downscale` hər şeyi JPEG-ə çevirir.
    Burada cavablandırılan sual dardır — bu ümumiyyətlə şəkildirmi?
    """
    if data.startswith((_JPEG_MAGIC, _PNG_MAGIC)):
        return True
    return data.startswith(_RIFF_MAGIC) and data[8:12] == _WEBP_TAG


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
        """Yükləmə ön-şərtləri — qayda `validate_evidence_payload`-dadır.

        Metod SAXLANILIR (çağırış yerləri və testlər ona bağlıdır), lakin
        məntiq modul səviyyəsinə çıxarılıb ki, lokal növbə də EYNİ qaydanı
        işlədə bilsin. Tenant həddi (`self._max_upload_bytes`) məhz burada
        tətbiq olunur — modul funksiyası onu arqument kimi alır.
        """
        validate_evidence_payload(file_bytes, filename, max_bytes=self._max_upload_bytes)


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
    "EvidenceValidationError",
    "GoogleDriveStorageProvider",
    "StoreNameResolver",
    "validate_evidence_payload",
]
