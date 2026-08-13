"""Cərimə sübut şəkillərinin Drive-da saxlanması testləri (Faza 3.9).

Tələbin 6-cı bölməsindəki ssenarilər burada yoxlanılır:
    * qovluğun avtomatik yaradılması və keşin işləməsi,
    * ay dəyişəndə YENİ qovluq,
    * lokal şəkil keşinin ikinci sorğunu Drive-a buraxmaması,
    * yükləmə-retry (Drive müvəqqəti əlçatmazdır),
    * kvota həddi xəbərdarlığı,
    * hesab dəyişikliyində köhnə istinadların qorunması.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from src.domain.value_objects.identifiers import StoreId
from src.domain.value_objects.storage import (
    ImageSize,
    QuotaStatus,
    StorageError,
    StorageProviderKind,
    StorageReference,
)
from src.infrastructure.storage.folder_resolver import (
    FolderResolver,
    InMemoryDriveFolderCache,
    sanitize_folder_name,
    year_month,
)
from src.infrastructure.storage.google_drive import (
    ALLOWED_EXTENSIONS,
    EMPLOYEE_DOCUMENT_OWNER_TYPE,
    FINE_OWNER_TYPE,
    GoogleDriveStorageProvider,
    StoreNameResolver,
    allowed_extensions_for,
)
from src.infrastructure.storage.image_cache import ImageCache
from src.infrastructure.storage.quota_monitor import DriveQuotaMonitor
from src.infrastructure.storage.upload_queue import (
    EvidenceUploadQueue,
    EvidenceUploadWorker,
    UploadOwnerType,
    UploadStatus,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

CONNECTION_A = uuid.uuid4()
CONNECTION_B = uuid.uuid4()
STORE_1 = StoreId(uuid.uuid4())
STORE_2 = StoreId(uuid.uuid4())
AUGUST = datetime(2026, 8, 15, 10, 30, tzinfo=UTC)
SEPTEMBER = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)


def _png(width: int = 8, height: int = 8) -> bytes:
    """Real PNG yaradır.

    Bayt-bayt yazılmış "kiçik PNG" sabiti yazmaq cazibədardır, lakin bir
    simvol səhvi bütün test faylını "broken data stream" ilə dağıdır və
    səbəb testin ÖZÜNDƏ olduğu halda kodda axtarılır. Pillow onsuz da
    layihə asılılığıdır — şəkli o yaratsın.
    """
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (width, height), (200, 40, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


TINY_PNG = _png()


# --------------------------------------------------------------------------- #
# Sahtə Drive API
# --------------------------------------------------------------------------- #


class FakeDriveApi:
    """Drive API-nin yaddaşdakı əvəzi — hər çağırış sayılır."""

    def __init__(self) -> None:
        self.folders: dict[tuple[str | None, str], str] = {}
        self.files: dict[str, bytes] = {}
        self.find_calls = 0
        self.create_calls = 0
        self.download_calls = 0
        self.upload_calls = 0
        self.uploads: list[dict[str, Any]] = []
        self.fail_uploads_with: Exception | None = None
        self.quota_value = QuotaStatus(used_bytes=1_000, total_bytes=100_000)

    def find_folder(self, name: str, *, parent_id: str | None = None) -> str | None:
        self.find_calls += 1
        return self.folders.get((parent_id, name))

    def create_folder(self, name: str, *, parent_id: str | None = None) -> str:
        self.create_calls += 1
        folder_id = f"folder-{len(self.folders) + 1}"
        self.folders[(parent_id, name)] = folder_id
        return folder_id

    def ensure_folder(self, name: str, *, parent_id: str | None = None) -> str:
        existing = self.find_folder(name, parent_id=parent_id)
        return existing if existing else self.create_folder(name, parent_id=parent_id)

    def upload_file(
        self, *, filename: str, content: bytes, parent_id: str, mime_type: str = "image/jpeg"
    ) -> str:
        self.upload_calls += 1
        if self.fail_uploads_with is not None:
            raise self.fail_uploads_with
        # Ad + MIME saxlanılır: PDF-in kiçildilmədən və DÜZGÜN MIME ilə
        # getdiyini yoxlayan testlər (SEC-018) başqa cür göstərə bilməzdi.
        self.uploads.append({"filename": filename, "mime_type": mime_type, "bytes": content})
        file_id = f"file-{len(self.files) + 1}"
        self.files[file_id] = content
        return file_id

    def download_file(self, file_id: str) -> bytes:
        self.download_calls += 1
        return self.files[file_id]

    def delete_file(self, file_id: str) -> bool:
        return self.files.pop(file_id, None) is not None

    def quota(self) -> QuotaStatus:
        return self.quota_value


@pytest.fixture
def api() -> FakeDriveApi:
    return FakeDriveApi()


@pytest.fixture
def cache(tmp_path: Path) -> ImageCache:
    return ImageCache(tmp_path / "img", ttl_seconds=3600, max_bytes=10_000_000)


@pytest.fixture
def provider(api: FakeDriveApi, cache: ImageCache) -> GoogleDriveStorageProvider:
    names = StoreNameResolver()
    names.register(STORE_1, "Yataş Babək")
    names.register(STORE_2, "Bellona Nərimanov")
    return GoogleDriveStorageProvider(
        api=api,  # type: ignore[arg-type]
        folders=FolderResolver(
            api=api,  # type: ignore[arg-type]
            cache=InMemoryDriveFolderCache(),
            connection_id=CONNECTION_A,
        ),
        cache=cache,
        connection_id=CONNECTION_A,
        store_names=names,
    )


# --------------------------------------------------------------------------- #
# StorageReference invariantları
# --------------------------------------------------------------------------- #


def test_drive_reference_requires_connection_id() -> None:
    """Bağlantısız Drive istinadı hesab dəyişdikdən sonra tapılmaz olardı."""
    with pytest.raises(StorageError, match="connection_id"):
        StorageReference(provider=StorageProviderKind.GOOGLE_DRIVE, file_id="abc")


def test_legacy_supabase_reference_needs_no_connection() -> None:
    """Köçürülmədən əvvəlki qeydlər öz yerində oxunmağa davam edir."""
    reference = StorageReference.legacy_supabase("https://supabase/storage/x.jpg")

    assert reference.provider is StorageProviderKind.SUPABASE_STORAGE
    assert reference.connection_id is None


def test_empty_file_id_rejected() -> None:
    with pytest.raises(StorageError):
        StorageReference.drive(file_id="   ", connection_id=CONNECTION_A)


# --------------------------------------------------------------------------- #
# Qovluq strukturu və aylıq rotasiya
# --------------------------------------------------------------------------- #


def test_upload_creates_store_and_month_folders(
    provider: GoogleDriveStorageProvider, api: FakeDriveApi
) -> None:
    """Admin heç nə hazırlamır — `KompasOS/{Mağaza}/{İl-Ay}` özü yaranır."""
    provider.upload(TINY_PNG, "sübut.png", STORE_1, AUGUST)

    created = set(api.folders)
    assert (None, "KompasOS") in created
    assert any(name == "Yataş Babək" for _, name in created)
    assert any(name == "2026-08" for _, name in created)


def test_second_upload_same_store_and_month_creates_no_new_folder(
    provider: GoogleDriveStorageProvider, api: FakeDriveApi
) -> None:
    """Tələb 6: ardıcıl iki yükləmə YALNIZ BİR dəfə qovluq yaratmalıdır."""
    provider.upload(TINY_PNG, "bir.png", STORE_1, AUGUST)
    after_first = api.create_calls
    find_calls_after_first = api.find_calls

    provider.upload(TINY_PNG, "iki.png", STORE_1, AUGUST)

    assert api.create_calls == after_first, "ikinci yükləmə yeni qovluq yaratdı"
    assert api.find_calls == find_calls_after_first, "keş işləmədi — Drive-a sorğu getdi"


def test_month_change_creates_a_different_folder(
    provider: GoogleDriveStorageProvider, api: FakeDriveApi
) -> None:
    """Aylıq rotasiya: sentyabr avqustun qovluğuna YAZMAMALIDIR."""
    august_ref = provider.upload(TINY_PNG, "avqust.png", STORE_1, AUGUST)
    september_ref = provider.upload(TINY_PNG, "sentyabr.png", STORE_1, SEPTEMBER)

    assert august_ref.folder_id != september_ref.folder_id
    assert any(name == "2026-09" for _, name in api.folders)


def test_different_stores_get_different_folders(
    provider: GoogleDriveStorageProvider,
) -> None:
    first = provider.upload(TINY_PNG, "a.png", STORE_1, AUGUST)
    second = provider.upload(TINY_PNG, "b.png", STORE_2, AUGUST)

    assert first.folder_id != second.folder_id


def test_year_month_format_matches_db_constraint() -> None:
    assert year_month(datetime(2026, 1, 5, tzinfo=UTC)) == "2026-01"
    assert year_month(datetime(2026, 12, 31, tzinfo=UTC)) == "2026-12"


def test_store_name_keeps_azerbaijani_letters() -> None:
    """Drive-a insan baxır — "Yatas Babek" yazısı qəbuledilməzdir."""
    assert sanitize_folder_name("Yataş Babək") == "Yataş Babək"


def test_store_name_strips_query_breaking_characters() -> None:
    assert "'" not in sanitize_folder_name("O'Neill / Mağaza")
    assert "/" not in sanitize_folder_name("O'Neill / Mağaza")


def test_empty_store_name_falls_back() -> None:
    assert sanitize_folder_name("   ") == "Adsız Mağaza"


def test_folder_cache_is_keyed_by_connection() -> None:
    """Hesab dəyişəndə eyni mağaza/ay üçün YENİ hesabda yeni qovluq lazımdır."""
    cache = InMemoryDriveFolderCache()
    cache.put(CONNECTION_A, STORE_1, "2026-08", "folder-A")

    assert cache.get(CONNECTION_A, STORE_1, "2026-08") == "folder-A"
    assert cache.get(CONNECTION_B, STORE_1, "2026-08") is None


# --------------------------------------------------------------------------- #
# Şəkil keşi
# --------------------------------------------------------------------------- #


def test_second_read_does_not_hit_drive(
    provider: GoogleDriveStorageProvider, api: FakeDriveApi
) -> None:
    """Tələb 6: ikinci çağırış keşdən gəlməlidir."""
    reference = provider.upload(TINY_PNG, "a.png", STORE_1, AUGUST)
    provider._cache.clear()  # yükləmə anındakı keşi sıfırlayırıq

    provider.get_image_bytes(reference, ImageSize.FULL)
    downloads_after_first = api.download_calls
    provider.get_image_bytes(reference, ImageSize.FULL)

    assert downloads_after_first == 1
    assert api.download_calls == 1, "ikinci oxuma Drive-a getdi"


def test_thumbnail_is_generated_locally_without_extra_download(
    provider: GoogleDriveStorageProvider, api: FakeDriveApi
) -> None:
    reference = provider.upload(TINY_PNG, "a.png", STORE_1, AUGUST)
    provider._cache.clear()

    provider.get_image_bytes(reference, ImageSize.FULL)
    provider.get_image_bytes(reference, ImageSize.THUMBNAIL)
    provider.get_image_bytes(reference, ImageSize.THUMBNAIL)

    assert api.download_calls == 1, "thumbnail üçün əlavə şəbəkə sorğusu getdi"


def test_uploaded_image_is_immediately_cached(
    provider: GoogleDriveStorageProvider, api: FakeDriveApi
) -> None:
    """Operator cəriməni yaradan kimi siyahıda şəkli görməlidir."""
    reference = provider.upload(TINY_PNG, "a.png", STORE_1, AUGUST)

    provider.get_image_bytes(reference, ImageSize.FULL)

    assert api.download_calls == 0


def test_cache_survives_new_instance(tmp_path: Path) -> None:
    reference = StorageReference.drive(file_id="f1", connection_id=CONNECTION_A)
    first = ImageCache(tmp_path / "c")
    first.put(reference, ImageSize.FULL, b"data")

    second = ImageCache(tmp_path / "c")
    assert second.get(reference, ImageSize.FULL) == b"data"


def test_expired_cache_entry_is_dropped(tmp_path: Path) -> None:
    reference = StorageReference.drive(file_id="f1", connection_id=CONNECTION_A)
    cache = ImageCache(tmp_path / "c", ttl_seconds=-1)
    cache.put(reference, ImageSize.FULL, b"data")

    assert cache.get(reference, ImageSize.FULL) is None


def test_cache_evicts_when_over_size_limit(tmp_path: Path) -> None:
    cache = ImageCache(tmp_path / "c", max_bytes=2_500)
    for index in range(5):
        cache.put(
            StorageReference.drive(file_id=f"f{index}", connection_id=CONNECTION_A),
            ImageSize.FULL,
            b"x" * 1000,
        )

    assert cache.stats.total_bytes <= 2_500


def test_cache_key_separates_connections() -> None:
    """Eyni fayl ID-si iki hesabda fərqli fayldır — keş onları qarışdırmamalıdır."""
    first = StorageReference.drive(file_id="same", connection_id=CONNECTION_A)
    second = StorageReference.drive(file_id="same", connection_id=CONNECTION_B)

    assert first.cache_key != second.cache_key


def test_delete_removes_from_cache(provider: GoogleDriveStorageProvider, api: FakeDriveApi) -> None:
    reference = provider.upload(TINY_PNG, "a.png", STORE_1, AUGUST)

    assert provider.delete(reference) is True
    assert provider._cache.get(reference, ImageSize.FULL) is None


# --------------------------------------------------------------------------- #
# Yükləmə validasiyası
# --------------------------------------------------------------------------- #


def test_oversized_upload_rejected(provider: GoogleDriveStorageProvider) -> None:
    with pytest.raises(StorageError, match="MB"):
        provider.upload(b"x" * (6 * 1024 * 1024), "boyuk.jpg", STORE_1, AUGUST)


@pytest.mark.parametrize("filename", ["sened.pdf", "arxiv.zip", "uzantisiz"])
def test_disallowed_extension_rejected(provider: GoogleDriveStorageProvider, filename: str) -> None:
    with pytest.raises(StorageError, match="format"):
        provider.upload(TINY_PNG, filename, STORE_1, AUGUST)


def test_empty_file_rejected(provider: GoogleDriveStorageProvider) -> None:
    with pytest.raises(StorageError):
        provider.upload(b"", "a.jpg", STORE_1, AUGUST)


def test_filename_gets_timestamp_prefix(
    provider: GoogleDriveStorageProvider, api: FakeDriveApi
) -> None:
    """Bir qovluqda 40 ədəd "photo.jpg" insan üçün faydasızdır."""
    captured: list[str] = []
    original = api.upload_file

    def spy(*, filename: str, **kwargs: Any) -> str:
        captured.append(filename)
        return original(filename=filename, **kwargs)

    api.upload_file = spy  # type: ignore[assignment]
    provider.upload(TINY_PNG, "photo.png", STORE_1, AUGUST)

    assert captured[0].startswith("20260815-103000_")


# --------------------------------------------------------------------------- #
# Asinxron yükləmə növbəsi və retry
# --------------------------------------------------------------------------- #


@pytest.fixture
def queue(tmp_path: Path) -> Iterator[EvidenceUploadQueue]:
    q = EvidenceUploadQueue(tmp_path / "uploads.db", spool_dir=tmp_path / "spool")
    yield q
    q.close()


class FakeFactory:
    def __init__(self, provider: object, *, available: bool = True) -> None:
        self._provider = provider
        self.available = available

    def active(self) -> object:
        if not self.available:
            raise RuntimeError("aktiv Drive bağlantısı yoxdur")
        return self._provider


def test_enqueued_upload_is_pending(queue: EvidenceUploadQueue) -> None:
    fine_id = uuid.uuid4()
    queue.enqueue(
        tenant_id=str(uuid.uuid4()),
        owner_type=UploadOwnerType.FINE,
        owner_id=str(fine_id),
        store_id=STORE_1,
        filename="a.png",
        content=TINY_PNG,
        taken_at=AUGUST,
        now=AUGUST,
    )

    pending = queue.pending(now=AUGUST)
    assert len(pending) == 1
    assert pending[0].read_bytes() == TINY_PNG


def test_worker_uploads_and_clears_queue(
    queue: EvidenceUploadQueue, provider: GoogleDriveStorageProvider
) -> None:
    queue.enqueue(
        tenant_id=str(uuid.uuid4()),
        owner_type=UploadOwnerType.FINE,
        owner_id=str(uuid.uuid4()),
        store_id=STORE_1,
        filename="a.png",
        content=TINY_PNG,
        taken_at=AUGUST,
        now=AUGUST,
    )
    worker = EvidenceUploadWorker(queue=queue, provider_factory=FakeFactory(provider))

    report = worker.run_once(now=AUGUST)

    assert report.uploaded == 1
    assert queue.counts()[UploadStatus.UPLOADED.value] == 1
    assert queue.pending(now=AUGUST) == []


def test_failed_upload_stays_queued_with_backoff(
    queue: EvidenceUploadQueue, provider: GoogleDriveStorageProvider, api: FakeDriveApi
) -> None:
    """Drive müvəqqəti əlçatmazdır — şəkil İTMİR, təkrar cəhd olunur."""
    api.fail_uploads_with = RuntimeError("Drive əlçatmazdır")
    queue.enqueue(
        tenant_id=str(uuid.uuid4()),
        owner_type=UploadOwnerType.FINE,
        owner_id=str(uuid.uuid4()),
        store_id=STORE_1,
        filename="a.png",
        content=TINY_PNG,
        taken_at=AUGUST,
        now=AUGUST,
    )
    worker = EvidenceUploadWorker(queue=queue, provider_factory=FakeFactory(provider))

    report = worker.run_once(now=AUGUST)

    assert report.failed == 1
    assert queue.pending(now=AUGUST) == [], "backoff tətbiq olunmadı"
    assert len(queue.pending(now=AUGUST + timedelta(seconds=31))) == 1


def test_retry_succeeds_after_drive_recovers(
    queue: EvidenceUploadQueue, provider: GoogleDriveStorageProvider, api: FakeDriveApi
) -> None:
    api.fail_uploads_with = RuntimeError("müvəqqəti nasazlıq")
    queue.enqueue(
        tenant_id=str(uuid.uuid4()),
        owner_type=UploadOwnerType.FINE,
        owner_id=str(uuid.uuid4()),
        store_id=STORE_1,
        filename="a.png",
        content=TINY_PNG,
        taken_at=AUGUST,
        now=AUGUST,
    )
    worker = EvidenceUploadWorker(queue=queue, provider_factory=FakeFactory(provider))
    worker.run_once(now=AUGUST)

    api.fail_uploads_with = None
    report = worker.run_once(now=AUGUST + timedelta(minutes=1))

    assert report.uploaded == 1


def test_worker_without_active_connection_keeps_items(
    queue: EvidenceUploadQueue, provider: GoogleDriveStorageProvider
) -> None:
    """Kvota dolub və ya hesab hələ qoşulmayıb — şəkillər gözləyir."""
    queue.enqueue(
        tenant_id=str(uuid.uuid4()),
        owner_type=UploadOwnerType.FINE,
        owner_id=str(uuid.uuid4()),
        store_id=STORE_1,
        filename="a.png",
        content=TINY_PNG,
        taken_at=AUGUST,
        now=AUGUST,
    )
    worker = EvidenceUploadWorker(
        queue=queue, provider_factory=FakeFactory(provider, available=False)
    )

    report = worker.run_once(now=AUGUST)

    assert report.skipped_no_connection is True
    assert len(queue.pending(now=AUGUST)) == 1


def test_callback_receives_reference(
    queue: EvidenceUploadQueue, provider: GoogleDriveStorageProvider
) -> None:
    """`fines` sətrini yeniləmək üçün geri çağırış."""
    seen: list[tuple[str, str, StorageReference]] = []
    fine_id = uuid.uuid4()
    queue.enqueue(
        tenant_id=str(uuid.uuid4()),
        owner_type=UploadOwnerType.FINE,
        owner_id=str(fine_id),
        store_id=STORE_1,
        filename="a.png",
        content=TINY_PNG,
        taken_at=AUGUST,
        now=AUGUST,
    )
    worker = EvidenceUploadWorker(
        queue=queue,
        provider_factory=FakeFactory(provider),
        on_uploaded=lambda otype, oid, ref: seen.append((otype, oid, ref)),
    )
    worker.run_once(now=AUGUST)

    assert seen[0][0] == UploadOwnerType.FINE.value
    assert seen[0][1] == str(fine_id)
    assert seen[0][2].connection_id == CONNECTION_A


def test_callback_failure_does_not_lose_upload(
    queue: EvidenceUploadQueue, provider: GoogleDriveStorageProvider
) -> None:
    """Şəkil Drive-dadır — DB yeniləməsinin nasazlığı onu itirməməlidir."""

    def boom(_otype: str, _oid: str, _ref: StorageReference) -> None:
        raise RuntimeError("DB əlçatmazdır")

    queue.enqueue(
        tenant_id=str(uuid.uuid4()),
        owner_type=UploadOwnerType.FINE,
        owner_id=str(uuid.uuid4()),
        store_id=STORE_1,
        filename="a.png",
        content=TINY_PNG,
        taken_at=AUGUST,
        now=AUGUST,
    )
    worker = EvidenceUploadWorker(
        queue=queue, provider_factory=FakeFactory(provider), on_uploaded=boom
    )

    report = worker.run_once(now=AUGUST)

    assert report.uploaded == 1


# --------------------------------------------------------------------------- #
# SEC-018 — sənəd PDF-i: icazəli format sahib tipinə görə seçilir
# --------------------------------------------------------------------------- #

#: Minimal, imzası QANUNİ PDF (bax `google_drive._PDF_MAGIC` şərhi).
TINY_PDF = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"


def test_owner_type_keys_match_the_queue_enum() -> None:
    """`google_drive` sahib tipini MƏTNLƏ tanıyır (dairəvi idxaldan qaçmaq üçün).

    Enum dəyəri dəyişsəydi, format siyahısı sükutla ən dar dəstə düşər və
    sənəd PDF-ləri rədd edilməyə başlayardı — bu test həmin sürüşməni tutur.
    """
    assert UploadOwnerType.FINE.value == FINE_OWNER_TYPE
    assert UploadOwnerType.EMPLOYEE_DOCUMENT.value == EMPLOYEE_DOCUMENT_OWNER_TYPE
    assert allowed_extensions_for(FINE_OWNER_TYPE) == ALLOWED_EXTENSIONS
    assert ".pdf" not in allowed_extensions_for(FINE_OWNER_TYPE)
    assert ".pdf" in allowed_extensions_for(EMPLOYEE_DOCUMENT_OWNER_TYPE)


def test_document_pdf_is_stored_byte_for_byte(
    provider: GoogleDriveStorageProvider, api: FakeDriveApi
) -> None:
    """PDF kiçildilmir: imzalı müqavilə Drive-a OLDUĞU KİMİ getməlidir."""
    reference = provider.upload(
        TINY_PDF, "müqavilə.pdf", STORE_1, AUGUST, owner_type=EMPLOYEE_DOCUMENT_OWNER_TYPE
    )

    assert api.uploads[0]["bytes"] == TINY_PDF, "PDF baytları dəyişdirilib"
    assert api.uploads[0]["mime_type"] == "application/pdf"
    assert api.uploads[0]["filename"].endswith(".pdf"), "PDF `.jpg` adı ilə saxlanıb"
    assert reference.file_id in api.files


def test_document_pdf_is_not_placed_in_the_image_cache(
    provider: GoogleDriveStorageProvider, api: FakeDriveApi
) -> None:
    """Keş ŞƏKİL keşidir: PDF ora düşsə, thumbnail yolu Pillow-da qırılardı."""
    reference = provider.upload(
        TINY_PDF, "müqavilə.pdf", STORE_1, AUGUST, owner_type=EMPLOYEE_DOCUMENT_OWNER_TYPE
    )

    assert provider.get_image_bytes(reference) == TINY_PDF
    assert api.download_calls == 1, "PDF şəkil keşindən qaytarıldı"


def test_fine_evidence_still_refuses_pdf_at_the_provider(
    provider: GoogleDriveStorageProvider, api: FakeDriveApi
) -> None:
    """Cərimə tərəfi DƏYİŞMİR — sahib tipi verilməsə də ən dar siyahı işləyir."""
    with pytest.raises(StorageError, match="format"):
        provider.upload(TINY_PDF, "sübut.pdf", STORE_1, AUGUST)

    with pytest.raises(StorageError, match="format"):
        provider.upload(TINY_PDF, "sübut.pdf", STORE_1, AUGUST, owner_type=FINE_OWNER_TYPE)

    assert api.upload_calls == 0, "rədd edilmiş fayl Drive-a getdi"


def test_fake_pdf_is_refused_at_the_provider(
    provider: GoogleDriveStorageProvider, api: FakeDriveApi
) -> None:
    """`.pdf` adlı icra faylı: uzantı keçir, MƏZMUN imzası saxlayır."""
    with pytest.raises(StorageError, match="PDF"):
        provider.upload(
            b"MZ\x90\x00" + b"\x00" * 32,
            "müqavilə.pdf",
            STORE_1,
            AUGUST,
            owner_type=EMPLOYEE_DOCUMENT_OWNER_TYPE,
        )

    assert api.upload_calls == 0


def test_document_image_is_still_downscaled_to_jpeg(
    provider: GoogleDriveStorageProvider, api: FakeDriveApi
) -> None:
    """Sənəd tərəfində ŞƏKİL yolu dəyişmir: kiçildilir və JPEG kimi saxlanır."""
    provider.upload(
        TINY_PNG, "vəsiqə.png", STORE_1, AUGUST, owner_type=EMPLOYEE_DOCUMENT_OWNER_TYPE
    )

    assert api.uploads[0]["mime_type"] == "image/jpeg"
    assert api.uploads[0]["filename"].endswith(".jpg")
    assert api.uploads[0]["bytes"] != TINY_PNG, "şəkil kiçildilmədən getdi"


def test_document_pdf_travels_through_queue_and_worker(
    queue: EvidenceUploadQueue, provider: GoogleDriveStorageProvider, api: FakeDriveApi
) -> None:
    """Uçdan-uca: növbənin ön-yoxlaması və provider EYNİ cavabı verir.

    Sahib tipi ötürülməsəydi, PDF ya `enqueue`-da, ya da işçidə `REJECTED`
    olardı — yəni sənəd modulu əsas istifadə halında işləməzdi.
    """
    document_id = uuid.uuid4()
    queue.enqueue(
        tenant_id=str(uuid.uuid4()),
        owner_type=UploadOwnerType.EMPLOYEE_DOCUMENT,
        owner_id=str(document_id),
        store_id=STORE_1,
        filename="müqavilə.pdf",
        content=TINY_PDF,
        taken_at=AUGUST,
        now=AUGUST,
    )
    seen: list[tuple[str, str, StorageReference]] = []
    worker = EvidenceUploadWorker(
        queue=queue,
        provider_factory=FakeFactory(provider),
        on_uploaded=lambda otype, oid, ref: seen.append((otype, oid, ref)),
    )

    report = worker.run_once(now=AUGUST)

    assert report.uploaded == 1
    assert report.rejected == 0
    assert api.uploads[0]["mime_type"] == "application/pdf"
    assert seen[0][0] == UploadOwnerType.EMPLOYEE_DOCUMENT.value
    assert seen[0][1] == str(document_id)
    assert queue.counts()[UploadStatus.UPLOADED.value] == 1


# --------------------------------------------------------------------------- #
# Kvota nəzarəti
# --------------------------------------------------------------------------- #


class FakeConnectionRepo:
    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.quota_updates: list[tuple[QuotaStatus, bool]] = []
        self.warnings_marked = 0
        self.errors: list[str] = []

    def get_active(self) -> Any:
        return self.connection

    def update_quota(
        self, _cid: Any, quota: QuotaStatus, *, now: Any = None, mark_exceeded: bool = False
    ) -> None:
        self.quota_updates.append((quota, mark_exceeded))

    def mark_quota_warning_sent(self, _cid: Any, *, now: Any = None) -> None:
        self.warnings_marked += 1

    def record_error(self, _cid: Any, message: str) -> None:
        self.errors.append(message)


class FakeQuotaFactory:
    def __init__(self, quota: QuotaStatus | Exception) -> None:
        self._quota = quota

    def for_connection(self, _cid: Any) -> Any:
        quota = self._quota

        class _Provider:
            def quota(self) -> QuotaStatus:
                if isinstance(quota, Exception):
                    raise quota
                return quota

        return _Provider()


class RecordingNotifier:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def notify(self, **kwargs: Any) -> None:
        self.messages.append(kwargs)


def make_connection(**overrides: Any) -> Any:
    from src.infrastructure.storage.connections import DriveConnection, DriveConnectionStatus

    defaults: dict[str, Any] = {
        "id": CONNECTION_A,
        "tenant_id": uuid.uuid4(),
        "google_account_email": "kompas@sirket.az",
        "status": DriveConnectionStatus.ACTIVE,
    }
    defaults.update(overrides)
    return DriveConnection(**defaults)


def make_monitor(repo: Any, quota: QuotaStatus | Exception) -> tuple[Any, RecordingNotifier]:
    notifier = RecordingNotifier()
    monitor = DriveQuotaMonitor(
        repository=repo,
        provider_factory=FakeQuotaFactory(quota),  # type: ignore[arg-type]
        notifier=notifier,  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),  # type: ignore[arg-type]
    )
    return monitor, notifier


def test_quota_below_threshold_sends_no_warning() -> None:
    repo = FakeConnectionRepo(make_connection())
    monitor, notifier = make_monitor(repo, QuotaStatus(used_bytes=50, total_bytes=100))

    result = monitor.check(now=AUGUST)

    assert result.checked is True
    assert result.warning_sent is False
    assert notifier.messages == []


def test_quota_at_ninety_percent_warns() -> None:
    repo = FakeConnectionRepo(make_connection())
    monitor, notifier = make_monitor(repo, QuotaStatus(used_bytes=90, total_bytes=100))

    result = monitor.check(now=AUGUST)

    assert result.warning_sent is True
    assert notifier.messages[0]["is_critical"] is True
    assert "90%" in notifier.messages[0]["body_az"]


def test_quota_full_marks_exceeded_and_says_fines_still_work() -> None:
    """Xəbərdarlıq operatoru çaşdırmamalıdır: cərimə yaratmaq bloklanmır."""
    repo = FakeConnectionRepo(make_connection())
    monitor, notifier = make_monitor(repo, QuotaStatus(used_bytes=100, total_bytes=100))

    result = monitor.check(now=AUGUST)

    assert result.marked_exceeded is True
    assert repo.quota_updates[-1][1] is True
    assert "BLOKLANMAYIB" in notifier.messages[0]["body_az"]


def test_repeat_warning_suppressed_within_cooldown() -> None:
    """Alarm yorğunluğu: eyni xəbərdarlıq hər gün göndərilməməlidir."""
    repo = FakeConnectionRepo(make_connection(quota_warning_sent_at=AUGUST - timedelta(days=1)))
    monitor, notifier = make_monitor(repo, QuotaStatus(used_bytes=95, total_bytes=100))

    monitor.check(now=AUGUST)

    assert notifier.messages == []


def test_warning_repeats_after_cooldown() -> None:
    repo = FakeConnectionRepo(make_connection(quota_warning_sent_at=AUGUST - timedelta(days=30)))
    monitor, notifier = make_monitor(repo, QuotaStatus(used_bytes=95, total_bytes=100))

    monitor.check(now=AUGUST)

    assert len(notifier.messages) == 1


def test_quota_check_failure_is_recorded_not_raised() -> None:
    repo = FakeConnectionRepo(make_connection())
    monitor, notifier = make_monitor(repo, RuntimeError("şəbəkə yoxdur"))

    result = monitor.check(now=AUGUST)

    assert result.checked is False
    assert result.error is not None
    assert repo.errors, "xəta bağlantı sətrinə yazılmadı"
    assert notifier.messages == []


def test_no_active_connection_is_not_an_error() -> None:
    repo = FakeConnectionRepo(None)
    monitor, notifier = make_monitor(repo, QuotaStatus(used_bytes=0, total_bytes=100))

    result = monitor.check(now=AUGUST)

    assert result.checked is False
    assert result.error is None
    assert notifier.messages == []


def test_unlimited_account_reports_zero_usage_ratio() -> None:
    assert QuotaStatus(used_bytes=10_000, total_bytes=None).usage_ratio == 0.0
    assert QuotaStatus(used_bytes=10_000, total_bytes=None).is_full is False


# --------------------------------------------------------------------------- #
# Hesab dəyişikliyi (connection swap)
# --------------------------------------------------------------------------- #


def test_old_reference_still_points_to_old_connection(api: FakeDriveApi, cache: ImageCache) -> None:
    """Tələb 1: yeni hesab qoşulanda köhnə şəkillərə keçidlər POZULMAMALIDIR."""
    old_provider = GoogleDriveStorageProvider(
        api=api,  # type: ignore[arg-type]
        folders=FolderResolver(
            api=api,  # type: ignore[arg-type]
            cache=InMemoryDriveFolderCache(),
            connection_id=CONNECTION_A,
        ),
        cache=cache,
        connection_id=CONNECTION_A,
    )
    old_reference = old_provider.upload(TINY_PNG, "kohne.png", STORE_1, AUGUST)

    # Admin yeni hesab qoşur.
    new_provider = GoogleDriveStorageProvider(
        api=api,  # type: ignore[arg-type]
        folders=FolderResolver(
            api=api,  # type: ignore[arg-type]
            cache=InMemoryDriveFolderCache(),
            connection_id=CONNECTION_B,
        ),
        cache=cache,
        connection_id=CONNECTION_B,
    )
    new_reference = new_provider.upload(TINY_PNG, "yeni.png", STORE_1, SEPTEMBER)

    assert old_reference.connection_id == CONNECTION_A, "köhnə istinad dəyişdi"
    assert new_reference.connection_id == CONNECTION_B
    # Köhnə şəkil hələ də oxunur.
    assert old_provider.get_image_bytes(old_reference, ImageSize.FULL)


# --------------------------------------------------------------------------- #
# Yükləmə həddi — ROOT limiti (bölmə 3, bənd 1)
# --------------------------------------------------------------------------- #


def test_upload_limit_comes_from_the_constructor_not_a_hardcoded_5mb(
    api: FakeDriveApi, cache: ImageCache
) -> None:
    """`MAX_UPLOAD_SIZE_BYTES` Root tərəfindən dəyişdirilə bilməlidir.

    Provider həddi konstruktorda alır; `MAX_UPLOAD_BYTES` yalnız FALLBACK-dır
    (limit mənbəyi qoşulmayan yollar üçün). Sabit 5 MB tətbiq olunsaydı, Root
    panelindəki dəyər heç bir təsir etməzdi.
    """
    names = StoreNameResolver()
    names.register(STORE_1, "Yataş Babək")
    provider = GoogleDriveStorageProvider(
        api=api,  # type: ignore[arg-type]
        folders=FolderResolver(
            api=api,  # type: ignore[arg-type]
            cache=InMemoryDriveFolderCache(),
            connection_id=CONNECTION_A,
        ),
        cache=cache,
        connection_id=CONNECTION_A,
        store_names=names,
        max_upload_bytes=1024,
    )

    with pytest.raises(StorageError, match="böyük"):
        provider.upload(b"x" * 2048, "sekil.jpg", STORE_1, AUGUST)


def test_non_positive_upload_limit_falls_back_to_the_default(
    api: FakeDriveApi, cache: ImageCache
) -> None:
    """Bazada 0/mənfi dəyər yükləməni TAM bloklamamalıdır.

    Səhv konfiqurasiya "heç nə yüklənə bilmir" vəziyyəti yaratmamalıdır —
    fail-open istiqaməti layihədə toggle-larda da seçilib.
    """
    names = StoreNameResolver()
    names.register(STORE_1, "Yataş Babək")
    provider = GoogleDriveStorageProvider(
        api=api,  # type: ignore[arg-type]
        folders=FolderResolver(
            api=api,  # type: ignore[arg-type]
            cache=InMemoryDriveFolderCache(),
            connection_id=CONNECTION_A,
        ),
        cache=cache,
        connection_id=CONNECTION_A,
        store_names=names,
        max_upload_bytes=0,
    )

    reference = provider.upload(TINY_PNG, "sekil.png", STORE_1, AUGUST)
    assert reference is not None
