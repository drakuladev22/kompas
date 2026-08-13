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

──────────────────────────────────────────────────────────────────────────────
İCAZƏLİ FORMAT SİYAHISI NİYƏ SAHİB-TİPİNƏ GÖRƏ AYRILIR (SEC-018)
──────────────────────────────────────────────────────────────────────────────
Növbə Faza 7-də ÜMUMİLƏŞDİRİLDİ: eyni spool iki sahibi daşıyır — cərimə
sübutu (`FINE`) və işçi sənədi (`EMPLOYEE_DOCUMENT`, bax `upload_queue`
başlığı). İki sahibin qəbul etdiyi məzmun isə EYNİ DEYİL:

* Cərimə sübutu kameradan gələn FOTO-dur. Ora PDF qəbul etməyin heç bir
  əməliyyat səbəbi yoxdur, hücum səthini isə genişləndirər: PDF konteyner
  formatıdır (JavaScript, qoşma fayl, xarici istinad daşıya bilər) və
  `%PDF` bayrağı ilə gələn bayt sırası şəkil kimi renderlənə bilmədiyi
  üçün onu YOXLAYAN İNSAN da yoxdur.
* İşçi sənədi (müqavilə, şəxsiyyət vəsiqəsi) PRAKTİKADA PDF olur — modul
  yalnız şəkil qəbul etsəydi, əsas istifadə halı işləməzdi.

Ona görə vahid `ALLOWED_EXTENSIONS` GENİŞLƏNDİRİLMİR (bu, cərimə tərəfini
də açardı), sahib-tipinə görə SEÇİLƏN siyahı işlədilir. Naməlum sahib tipi
ən DAR siyahıya (yalnız şəkil) düşür — fail-closed.

Siyahının özü `system_limits`-ə ÇIXARILMADI; səbəb `_ALLOWED_BY_OWNER`
şərhindədir (CLAUDE.md §5 sualına verilən cavab).
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import TYPE_CHECKING, Final
from uuid import UUID

from src.domain.policies import SystemLimitKey
from src.domain.value_objects.storage import (
    FULL_MAX_EDGE,
    THUMBNAIL_MAX_EDGE,
    ImageSize,
    QuotaStatus,
    StorageError,
    StorageProviderKind,
    StorageReference,
)
from src.infrastructure.config.limits import InfrastructureLimits, fallback_int
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from src.domain.value_objects.identifiers import StoreId
    from src.infrastructure.storage.drive_api import DriveApiClient
    from src.infrastructure.storage.folder_resolver import FolderResolver
    from src.infrastructure.storage.image_cache import ImageCache

_log = get_logger(__name__)

#: Yükləmə zamanı JPEG keyfiyyəti — 85 gözlə seçilməyən itki verir və
#: faylı orijinaldan ~4–6 dəfə kiçildir.
#:
#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits` (`EVIDENCE_JPEG_QUALITY`,
#: seed: migrations/032). Keyfiyyət SÜBUT dəyəri ilə kanal yükü arasındakı
#: mübadilədir: mübahisəli cərimədə şəkil oxunaqlı olmalıdır, zəif kanalda
#: isə hər şəkil dəqiqələrlə yüklənə bilər. Aşağı hüdud 40-dır — ondan aşağı
#: keyfiyyətdə şəkil sübut kimi yararsız olardı.
FALLBACK_JPEG_QUALITY: Final[int] = fallback_int(SystemLimitKey.EVIDENCE_JPEG_QUALITY)

#: Sahib tipi açarları MƏTNDİR, `UploadOwnerType` enum-u DEYİL.
#:
#: Enum `upload_queue.py`-dadır və HƏMİN modul bu modulu idxal edir
#: (`validate_evidence_payload`, `MAX_UPLOAD_BYTES`). Tərs istiqamətdə idxal
#: dairəvi asılılıq yaradardı; enum-u bura köçürmək isə növbənin ictimai adını
#: (`upload_queue.UploadOwnerType`) və onu idxal edən beş çağırış yerini
#: dəyişərdi. Ona görə sərhəd `enum.value` səviyyəsindədir — işçi də geri
#: çağırışda EYNİ qərarı verir (bax `EvidenceUploadWorker.on_uploaded`).
#: Sürüşmə testlə bağlanır: `test_owner_type_keys_match_the_queue_enum`.
FINE_OWNER_TYPE: Final[str] = "FINE"
EMPLOYEE_DOCUMENT_OWNER_TYPE: Final[str] = "EMPLOYEE_DOCUMENT"

PDF_EXTENSION: Final[str] = ".pdf"
PDF_MIME_TYPE: Final[str] = "application/pdf"

#: Cərimə sübutu üçün YEGANƏ icazəli dəst — Faza 3.9-dakı davranışın EYNİSİ.
IMAGE_EXTENSIONS: Final[frozenset[str]] = frozenset({".jpg", ".jpeg", ".png", ".webp"})
#: İşçi sənədləri: şəkil + PDF (bax modul başlığı, SEC-018).
DOCUMENT_EXTENSIONS: Final[frozenset[str]] = IMAGE_EXTENSIONS | {PDF_EXTENSION}
#: KÖHNƏ AD — SİLİNMİR: xarici çağırış yerləri (`storage/__init__`, testlər)
#: ona bağlıdır və mənası dəyişmir (şəkil dəsti). Yeni kod
#: `allowed_extensions_for()` işlətməlidir.
ALLOWED_EXTENSIONS: Final[frozenset[str]] = IMAGE_EXTENSIONS

#: NİYƏ `system_limits`-DƏ DEYİL (CLAUDE.md §5 sualına cavab, SEC-018).
#:
#: `MAX_UPLOAD_SIZE_BYTES` konfiqurasiyadır, çünki o, MİQDARDIR: Root onu
#: dəyişəndə qorumanın NÖVÜ dəyişmir, yalnız həddi sürüşür — və səhv dəyər
#: (0/mənfi) fallback-a qayıdır, yəni konfiqurasiya qorumanı SÖNDÜRƏ BİLMİR.
#: Uzantı siyahısı isə hücum SƏTHİNİN ÖZÜDÜR: cədvələ bir sətir (`.svg`,
#: `.html`, `.exe`) əlavə etmək icra oluna bilən məzmuna yol açardı və —
#: daha pisi — həmin format üçün imza yoxlaması OLMADIĞINDAN aşağıdakı
#: məzmun qatı sükutla keçilərdi. Yəni konfiqurasiya ən güclü qatı ləğv
#: edərdi. Bu, "struktur zəmanət" tərifinə düşür (CLAUDE.md §5), ona görə
#: siyahı KODDA qalır. Formatın həqiqətən artması lazım olsa, o, yeni imza
#: yoxlaması + yeni test tələb edən KOD dəyişikliyidir.
_ALLOWED_BY_OWNER: Final[dict[str, frozenset[str]]] = {
    FINE_OWNER_TYPE: IMAGE_EXTENSIONS,
    EMPLOYEE_DOCUMENT_OWNER_TYPE: DOCUMENT_EXTENSIONS,
}

#: Rədd mətnləri sahib tipinə görə seçilir və HƏRFİ SABİTDİR (formatlanmır):
#: `frozenset`-dən qurulan sətir təsadüfi sıralanardı, cərimə tərəfindəki
#: mövcud mətn isə hərfi-hərfinə qorunmalıdır (davranış dəyişmir).
_FORMAT_MESSAGES: Final[dict[str, str]] = {
    FINE_OWNER_TYPE: "Yalnız .jpg, .png və .webp formatları qəbul olunur.",
    EMPLOYEE_DOCUMENT_OWNER_TYPE: "Yalnız .jpg, .png, .webp və .pdf formatları qəbul olunur.",
}
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
#: PDF imzası. ISO 32000-1 sənədin `%PDF-<versiya>` ilə BAŞLAMASINI tələb edir
#: (bəzi oxucular ilk 1 KB-da axtarır — biz axtarmırıq: "başlanğıcda olsun"
#: qaydası daha dardır və qanuni sənədlərin hamısı ona uyğun gəlir).
_PDF_MAGIC: Final[bytes] = b"%PDF-"


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


def allowed_extensions_for(owner_type: str) -> frozenset[str]:
    """Sahib tipinin icazəli uzantıları — naməlum tip üçün ƏN DAR dəst.

    Fail-closed: `_ALLOWED_BY_OWNER`-də olmayan (məs. gələcəkdə əlavə edilən,
    lakin burada unudulan) sahib tipi avtomatik olaraq YALNIZ şəkil qəbul edir.
    Əks qərar — naməlum tipə geniş dəst vermək — yeni sahib növünü qoşan
    proqramçının SÜKUTLA PDF-i açmasına səbəb olardı.
    """
    return _ALLOWED_BY_OWNER.get(owner_type, IMAGE_EXTENSIONS)


def is_pdf_upload(filename: str) -> bool:
    """Fayl PDF kimi yüklənirmi — kiçiltmə/MIME qərarı buna baxır.

    Yalnız UZANTIYA baxır və bu, kifayətdir: məzmun uyğunluğu
    `validate_evidence_payload`-da MƏCBURİ yoxlanılır, yəni bu funksiya
    çağırılanda `.pdf` adının arxasında həqiqətən `%PDF-` durur.
    """
    return _suffix_of(filename) == PDF_EXTENSION


def _suffix_of(filename: str) -> str:
    """Kiçik hərfli uzantı (`.png`) — uzantı yoxdursa boş sətir."""
    return ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""


def validate_evidence_payload(
    file_bytes: bytes,
    filename: str,
    *,
    max_bytes: int = MAX_UPLOAD_BYTES,
    owner_type: str = FINE_OWNER_TYPE,
) -> None:
    """Yükün ölçü/uzantı/imza yoxlaması — qayda BİR yerdədir.

    Həm provider (`GoogleDriveStorageProvider._validate`), həm də lokal növbə
    (`EvidenceUploadQueue.enqueue`) bunu çağırır. Qayda iki yerdə təkrar
    yazılsaydı, biri dəyişəndə digəri sükutla köhnə qalardı; halbuki növbə
    yararsız faylı diskə yazır və provider onu sonradan rədd edir — iki tərəf
    EYNİ cavabı verməlidir.

    Args:
        owner_type: `UploadOwnerType.value` (mətn). İcazəli uzantı dəstini
            MƏHZ bu seçir (bax modul başlığı). Defolt `FINE`-dır — ən dar
            dəst, yəni parametri ötürməyi unudan çağırış yeri qorumanı
            zəiflətmir, sərtləşdirir.

    Raises:
        EvidenceValidationError: Fayl qəbul edilə bilməz (daimi qərar).
    """
    allowed = allowed_extensions_for(owner_type)
    # Cərimə tərəfindəki mətnlər HƏRFİ-HƏRFİNƏ saxlanılır (davranış dəyişmir);
    # sənəd tərəfində "Şəkil" sözü yanlış olardı — orada PDF də qanunidir.
    noun = "Fayl" if PDF_EXTENSION in allowed else "Şəkil"

    if not file_bytes:
        raise EvidenceValidationError("Boş fayl yüklənə bilməz")
    if len(file_bytes) > max_bytes:
        megabytes = max_bytes // (1024 * 1024)
        raise EvidenceValidationError(
            f"{noun} {megabytes} MB-dan böyükdür",
            user_message=f"{noun} çox böyükdür (maksimum {megabytes} MB).",
            context={"bytes": len(file_bytes), "limit": max_bytes},
        )
    suffix = _suffix_of(filename)
    if suffix not in allowed:
        raise EvidenceValidationError(
            f"Dəstəklənməyən format: {suffix or '(uzantı yoxdur)'}",
            user_message=_FORMAT_MESSAGES.get(owner_type, _FORMAT_MESSAGES[FINE_OWNER_TYPE]),
            context={"owner_type": owner_type},
        )
    if suffix == PDF_EXTENSION:
        # PDF-də UZANTI–MƏZMUN UYĞUNLUĞU MƏCBURİDİR, şəkillərdən fərqli olaraq
        # (`_looks_like_image` başlığı: `.jpg` adlı PNG buraxılır). Səbəb:
        # şəkil yolunda baytlar `_downscale`-dən keçib YENİDƏN JPEG kimi
        # yazılır — yəni Drive-a gedən fayl həmişə şəkildir. PDF yolunda isə
        # kiçiltmə YOXDUR, bayt olduğu kimi saxlanır; burada uyğunluğu
        # yoxlamasaq, `.pdf` adı ilə İSTƏNİLƏN məzmun Drive-a düşərdi.
        if not file_bytes.startswith(_PDF_MAGIC):
            raise EvidenceValidationError(
                "Fayl məzmunu PDF deyil",
                user_message="Seçilmiş fayl düzgün PDF deyil (məzmun PDF imzası ilə başlamır).",
                context={"head": file_bytes[:5].hex()},
            )
        return
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
        limits: InfrastructureLimits | None = None,
    ) -> None:
        self._api = api
        self._folders = folders
        self._cache = cache
        self._connection_id = connection_id
        self._store_names = store_names or StoreNameResolver()
        self._limits = limits or InfrastructureLimits()
        # `system_limits.MAX_UPLOAD_SIZE_BYTES` — kompozisiya kökü onu
        # tenant üçün oxuyub ötürür (bax `composition.py`). Sıfır və ya
        # mənfi dəyər həddi SÖNDÜRMÜR, defolta qaytarır: səhv konfiqurasiya
        # 5 MB-lıq qorumanı sükutla itirməməlidir.
        self._max_upload_bytes = max_upload_bytes if max_upload_bytes > 0 else MAX_UPLOAD_BYTES

    def _jpeg_quality(self) -> int:
        """Sıxılma keyfiyyəti — HƏR ŞƏKİLDƏ oxunur.

        Provider Drive bağlantısı ilə birlikdə uzun yaşayır; keyfiyyəti
        konstruktorda dondursaydıq, Root kanalı yüngülləşdirmək üçün etdiyi
        dəyişikliyi ancaq yenidən başlatmadan sonra görərdi.
        """
        return self._limits.int_of(SystemLimitKey.EVIDENCE_JPEG_QUALITY)

    def _full_max_edge(self) -> int:
        """Yüklənən şəklin maksimum kənarı — `_jpeg_quality()` ilə eyni səbəb.

        Modul sabiti (`FULL_MAX_EDGE`) yalnız fallback-dır: portu olmayan
        çağırış yolları (test, offline provider) onu görür.
        """
        edge = self._limits.int_of(SystemLimitKey.EVIDENCE_FULL_MAX_EDGE_PX)
        # Sıfır/mənfi kənar `_downscale`-i mənasız edərdi (şəkil bir piksellik
        # ləkəyə çevrilər və sübut kimi işə yaramazdı) — fallback qoruyur.
        return edge if edge > 0 else FULL_MAX_EDGE

    def _thumbnail_max_edge(self) -> int:
        """Siyahıdakı kiçik şəklin maksimum kənarı — mənbə `system_limits`."""
        edge = self._limits.int_of(SystemLimitKey.EVIDENCE_THUMBNAIL_MAX_EDGE_PX)
        return edge if edge > 0 else THUMBNAIL_MAX_EDGE

    # ------------------------------- yükləmə ---------------------------------- #

    def upload(
        self,
        file_bytes: bytes,
        filename: str,
        store_id: StoreId,
        taken_at: datetime,
        *,
        owner_type: str = FINE_OWNER_TYPE,
    ) -> StorageReference:
        """Args:
        owner_type: `UploadOwnerType.value` — icazəli formatı seçir (SEC-018).
            YALNIZ AÇAR SÖZ ilə verilir və defoltu `FINE`-dır: `Evidence
            StorageProvider` portunun imzası (dörd mövqe arqumenti) POZULMUR,
            köhnə çağırış yerləri isə əvvəlki — ən dar — davranışı alır.
        """
        self._validate(file_bytes, filename, owner_type=owner_type)
        if is_pdf_upload(filename):
            # PDF KİÇİLDİLMİR: `_downscale` Pillow ilə şəkil açır, PDF-də isə
            # bu istisna atardı. Sənəd onsuz da MƏTNDİR — "kənar ölçüsü" anlayışı
            # yoxdur və hər hansı çevirmə imzalı müqaviləni DƏYİŞDİRMƏK olardı.
            payload, mime = file_bytes, PDF_MIME_TYPE
        else:
            payload, mime = _downscale(file_bytes, self._full_max_edge(), self._jpeg_quality())

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
        if not is_pdf_upload(filename):
            # Yeni yüklənən şəkil dərhal keşə qoyulur: operator cəriməni
            # yaratdıqdan sonra siyahıda onu görmək üçün Drive-a getməsin.
            #
            # PDF KEŞLƏNMİR: keş ŞƏKİL keşidir (`ImageCache`) və oradan gələn
            # bayt `get_image_bytes(THUMBNAIL)` yolunda `_downscale`-ə verilir —
            # PDF orada istisna atardı. Sənəd ekranda şəkil kimi göstərilmir,
            # yəni keşdən heç bir fayda da yoxdur.
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

        thumbnail, _ = _downscale(full, self._thumbnail_max_edge(), self._jpeg_quality())
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

    def _validate(
        self, file_bytes: bytes, filename: str, *, owner_type: str = FINE_OWNER_TYPE
    ) -> None:
        """Yükləmə ön-şərtləri — qayda `validate_evidence_payload`-dadır.

        Metod SAXLANILIR (çağırış yerləri və testlər ona bağlıdır), lakin
        məntiq modul səviyyəsinə çıxarılıb ki, lokal növbə də EYNİ qaydanı
        işlədə bilsin. Tenant həddi (`self._max_upload_bytes`) məhz burada
        tətbiq olunur — modul funksiyası onu arqument kimi alır.

        Format siyahısı sahib tipindən gəlir (SEC-018); `owner_type`
        verilmədikdə `FINE` — yəni yalnız şəkil — tətbiq olunur.
        """
        validate_evidence_payload(
            file_bytes, filename, max_bytes=self._max_upload_bytes, owner_type=owner_type
        )


def _unique_name(filename: str, taken_at: datetime) -> str:
    """Eyni adlı iki fayl bir qovluqda qarışmasın deyə vaxt-möhürü əlavə edir.

    Drive eyniadlı fayllara icazə verir (ID-lər fərqlidir), lakin insan
    qovluğa baxanda "photo.jpg" adlı 40 fayl faydasızdır.

    UZANTI: şəkillər üçün həmişə `.jpg`, çünki `_downscale` hər şeyi JPEG-ə
    çevirir və adın məzmuna uyğun olması Drive-da faylı açanın işini
    asanlaşdırır. PDF kiçildilmədiyi üçün onun uzantısı SAXLANILIR — `.jpg`
    adlı PDF-i Drive-ın önizləməsi də, admin də aça bilməzdi.
    """
    stamp = taken_at.strftime("%Y%m%d-%H%M%S")
    stem = filename.rsplit(".", 1)[0][:60] if "." in filename else filename[:60]
    extension = PDF_EXTENSION if is_pdf_upload(filename) else ".jpg"
    return f"{stamp}_{stem}{extension}"


def _downscale(
    data: bytes, max_edge: int, quality: int = FALLBACK_JPEG_QUALITY
) -> tuple[bytes, str]:
    """Şəkli maksimum kənara sığdırır və JPEG-ə çevirir.

    `Pillow` yoxdursa (məs. yalnız domen testləri işləyirsə) orijinal
    baytlar olduğu kimi qaytarılır — kiçiltmə OPTİMALLAŞDIRMADIR, məntiqin
    düzgünlüyü ondan asılı deyil.

    `quality` ARQUMENT kimi gəlir: funksiya saf çevirmədir və `system_limits`-ə
    özü müraciət etməməlidir (provider onu artıq oxuyub ötürür). Defolt yalnız
    provider-siz birbaşa çağırışlar üçündür.
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
        rendered.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue(), "image/jpeg"


__all__ = [
    "ALLOWED_EXTENSIONS",
    "DOCUMENT_EXTENSIONS",
    "EMPLOYEE_DOCUMENT_OWNER_TYPE",
    "FINE_OWNER_TYPE",
    "IMAGE_EXTENSIONS",
    "MAX_UPLOAD_BYTES",
    "PDF_EXTENSION",
    "PDF_MIME_TYPE",
    "EvidenceValidationError",
    "GoogleDriveStorageProvider",
    "StoreNameResolver",
    "allowed_extensions_for",
    "is_pdf_upload",
    "validate_evidence_payload",
]
