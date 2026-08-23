"""Təhlükəsizlik auditindən sonra bağlanan boşluqların reqressiya testləri.

Hər test BİR konkret hücum girişini təsvir edir və onun artıq zərərsiz
olduğunu göstərir. Testlər qəsdən dardır: mövcud davranışın qorunduğunu
göstərən testlər öz fayllarında qalır (`test_drive_storage.py`,
`test_updates_and_backup.py`) — burada YALNIZ yeni qorunma yoxlanılır.

    Tapıntı 2  tooltip mətni HTML kimi şərh olunurdu
    Tapıntı 3  sübut növbəsi faylı yoxlamadan qəbul edirdi (sonsuz retry)
    Tapıntı 4  baza şifrəsi `pg_dump` əmr sətrində görünürdü
    Tapıntı 5  format YALNIZ uzantıdan təyin olunurdu
    Tapıntı 6  audit axtarışındakı `%`/`_` ILIKE naxışını təhrif edirdi

Tapıntı 1 (QLabel `AutoText`) widget yaradılmasını tələb edir, ona görə
`tests/e2e/test_widget_text_safety.py`-dədir.
"""

from __future__ import annotations

import sqlite3
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from src.application.use_cases.audit_query import AuditFilter
from src.domain.value_objects.identifiers import StoreId
from src.domain.value_objects.infrastructure import DatabaseTarget
from src.domain.value_objects.storage import StorageError
from src.infrastructure.persistence.audit import PostgresAuditReader
from src.infrastructure.persistence.dsn import dsn_without_password, password_env
from src.infrastructure.persistence.migration import PgDumpMigrator
from src.infrastructure.storage.folder_resolver import FolderResolver, InMemoryDriveFolderCache
from src.infrastructure.storage.google_drive import (
    EvidenceValidationError,
    GoogleDriveStorageProvider,
    validate_evidence_payload,
)
from src.infrastructure.storage.image_cache import ImageCache
from src.infrastructure.storage.upload_queue import (
    EvidenceUploadQueue,
    EvidenceUploadWorker,
    UploadOwnerType,
    UploadStatus,
)
from src.presentation.widgets.safe_text import plain_tooltip

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

pytestmark = pytest.mark.unit

TENANT = str(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
CONNECTION = uuid.uuid4()
AUGUST = datetime(2026, 8, 15, 10, 30, tzinfo=UTC)

#: Şifrəsi olan DSN — testlərdə "sızmamalı olan sirr" budur.
SECRET = "P@rol-123"
DSN_WITH_PASSWORD = f"postgres://kompas:{SECRET}@db.kompas.az:5432/kompasos"


def _png(width: int = 8, height: int = 8) -> bytes:
    """Real PNG (bax `test_drive_storage._png` — eyni səbəb)."""
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (width, height), (10, 90, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


TINY_PNG = _png()
#: Windows icra faylının imzası — "sekil.jpg" adı ilə göndərilən hücum yükü.
FAKE_IMAGE = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 64


# --------------------------------------------------------------------------- #
# Tapıntı 2 — tooltip zəngin mətn kimi şərh olunurdu
# --------------------------------------------------------------------------- #


def test_ordinary_tooltip_text_is_returned_untouched() -> None:
    """Davranış dəyişmir: adi ad escape edilmir, ekranda olduğu kimi qalır."""
    assert plain_tooltip("Rəşad Məmmədov") == "Rəşad Məmmədov"
    assert plain_tooltip("Cərimə & etiraz") == "Cərimə & etiraz"
    assert plain_tooltip("") == ""


@pytest.mark.parametrize(
    "attack",
    [
        "<b>Rəşad</b>",
        "<img src=x onerror=1>",
        "<a href='file:///C:/Windows/win.ini'>klik</a>",
        "&lt;b&gt;",
    ],
)
def test_markup_in_tooltip_is_neutralised(attack: str) -> None:
    """Qt tooltip-i `setTextFormat`-a tabe deyil — işarə burada söndürülür."""
    result = plain_tooltip(attack)

    assert result.startswith("<html>") and result.endswith("</html>")
    # Örtükdən sonra bir dənə də olsun açıq bucaq mötərizəsi qalmır, yəni
    # Qt-nin zəngin-mətn parseri heç bir teq görmür.
    inner = result[len("<html>") : -len("</html>")]
    assert "<" not in inner
    assert ">" not in inner


def test_no_screen_creates_a_bare_qlabel() -> None:
    """Yeni ekran `QLabel(...)` yazsa, mətn rejimi yenidən təxminə qalardı.

    Qorunma bir yerdə (`primitives.plain_label`) mərkəzləşdirilib; bu test
    onun YAN KEÇİLMƏDİYİNİ mühafizə edir. Mənbə mətnini oxuyur, çünki sual
    "widget necə davranır" deyil, "kod hansı yolla yazılıb"dır — ikincisi
    yalnız statik yoxlama ilə cavablanır.
    """
    root = Path(__file__).resolve().parents[2] / "src" / "presentation"
    offenders = [
        f"{path.relative_to(root)}:{number}"
        for path in root.rglob("*.py")
        if path.name != "primitives.py"  # fabrikanın ÖZÜ (yeganə icazəli yer)
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "QLabel(" in line
    ]

    assert offenders == [], f"birbaşa QLabel(...) qalıb: {offenders}"


def test_developer_panel_labels_declare_plain_text() -> None:
    """Developer Paneli ayrı paketdir — `plain_label` idxal etmir, ona görə
    hər etiketi öz sətri ilə `PlainText` elan edir. Sayğaclar bərabər olmalıdır.
    """
    source = (Path(__file__).resolve().parents[2] / "src" / "developer_panel" / "ui.py").read_text(
        encoding="utf-8"
    )

    assert source.count("QLabel(") == source.count("setTextFormat(Qt.TextFormat.PlainText)")


# --------------------------------------------------------------------------- #
# Tapıntı 3 və 5 — sübut faylının yoxlanması
# --------------------------------------------------------------------------- #


@pytest.fixture
def queue(tmp_path: Path) -> Iterator[EvidenceUploadQueue]:
    # SAAS-3: növbə BİR kirayəçiyə bağlıdır — `_enqueue` EYNİ `TENANT`-i işlədir.
    q = EvidenceUploadQueue(tmp_path / "uploads.db", spool_dir=tmp_path / "spool", tenant_id=TENANT)
    yield q
    q.close()


def _provider(tmp_path: Path, *, max_upload_bytes: int) -> GoogleDriveStorageProvider:
    class _Api:
        def find_folder(self, name: str, *, parent_id: str | None = None) -> str | None:
            return None

        def create_folder(self, name: str, *, parent_id: str | None = None) -> str:
            return "folder-1"

        def ensure_folder(self, name: str, *, parent_id: str | None = None) -> str:
            return "folder-1"

        def upload_file(self, **kwargs: Any) -> str:
            return "file-1"

    api = _Api()
    return GoogleDriveStorageProvider(
        api=api,  # type: ignore[arg-type]
        folders=FolderResolver(
            api=api,  # type: ignore[arg-type]
            cache=InMemoryDriveFolderCache(),
            connection_id=CONNECTION,
        ),
        cache=ImageCache(tmp_path / "img"),
        connection_id=CONNECTION,
        max_upload_bytes=max_upload_bytes,
    )


def _enqueue(
    queue: EvidenceUploadQueue,
    *,
    content: bytes,
    filename: str,
    owner_type: UploadOwnerType = UploadOwnerType.FINE,
) -> str:
    """`owner_type` DEFOLTU `FINE`-dır — mövcud çağırışların davranışı dəyişmir."""
    return queue.enqueue(
        tenant_id=TENANT,
        owner_type=owner_type,
        owner_id=str(uuid.uuid4()),
        store_id=STORE,
        filename=filename,
        content=content,
        taken_at=AUGUST,
        now=AUGUST,
    )


def test_executable_disguised_as_a_photo_never_reaches_the_spool(
    queue: EvidenceUploadQueue, tmp_path: Path
) -> None:
    """`.jpg` adı ilə göndərilən `.exe` diskə YAZILMIR və növbəyə düşmür."""
    with pytest.raises(EvidenceValidationError, match="şəkil"):
        _enqueue(queue, content=FAKE_IMAGE, filename="sekil.jpg")

    assert list((tmp_path / "spool").iterdir()) == [], "yararsız fayl diskə yazıldı"
    assert queue.pending(now=AUGUST) == []


#: Yararsız yüklər. Baytlar FUNKSİYA arxasındadır: 6 MB-lıq sabiti birbaşa
#: `parametrize`-ə vermək pytest-in test adını həmin baytlardan qurmasına
#: səbəb olur (meqabaytlarla çıxış).
_BAD_PAYLOADS: dict[str, Any] = {
    "imza-uygun-deyil": (lambda: FAKE_IMAGE, "sekil.jpg"),
    "qadagan-uzanti": (lambda: TINY_PNG, "zerarli.exe"),
    "hedd-asilib": (lambda: b"x" * (6 * 1024 * 1024), "boyuk.jpg"),
    "bos-fayl": (lambda: b"", "bos.jpg"),
}


@pytest.mark.parametrize("case", list(_BAD_PAYLOADS))
def test_unusable_payload_is_reported_to_the_operator(
    queue: EvidenceUploadQueue, case: str
) -> None:
    """Rədd səssiz DEYİL: `user_message` ekrana çıxan Azərbaycanca mətndir.

    `FineEntryController._issue` məhz `KompasOSError.user_message`-i göstərir,
    yəni bu mətn operatorun gördüyü sətirdir.
    """
    make_content, filename = _BAD_PAYLOADS[case]

    with pytest.raises(EvidenceValidationError) as error:
        _enqueue(queue, content=make_content(), filename=filename)

    assert error.value.user_message.strip(), "operatora səbəb çatmır"
    assert isinstance(error.value, StorageError), "mövcud tutucular sınar"


def test_valid_photo_still_enters_the_queue(queue: EvidenceUploadQueue) -> None:
    """Davranış dəyişmir: düzgün şəkil əvvəlki kimi növbəyə düşür."""
    entry_id = _enqueue(queue, content=TINY_PNG, filename="sübut.png")

    pending = queue.pending(now=AUGUST)
    assert [item.id for item in pending] == [entry_id]


def test_webp_is_still_accepted(queue: EvidenceUploadQueue) -> None:
    """İmza yoxlaması `ALLOWED_EXTENSIONS`-dakı WEBP-i kəsməməlidir."""
    webp = b"RIFF" + (100).to_bytes(4, "little") + b"WEBPVP8 " + b"\x00" * 80

    assert _enqueue(queue, content=webp, filename="sübut.webp")


def test_content_check_does_not_depend_on_pillow() -> None:
    """Pillow olmayan mühitdə də imza yoxlaması işləyir — funksiya təmizdir."""
    with pytest.raises(EvidenceValidationError):
        validate_evidence_payload(b"%PDF-1.7 sened", "sekil.png")

    validate_evidence_payload(b"\xff\xd8\xff" + b"\x00" * 32, "sekil.jpg")


# --------------------------------------------------------------------------- #
# SEC-018 — icazəli format SAHİB TİPİNƏ görə ayrılır (PDF yalnız sənəddə)
# --------------------------------------------------------------------------- #

#: Minimal, lakin QANUNİ başlıqlı PDF. Məzmun yoxlaması yalnız imzaya baxır
#: (bax `google_drive._PDF_MAGIC` şərhi), ona görə tam sənəd qurmaq artıqdır.
TINY_PDF = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"


def test_employee_document_pdf_is_accepted(queue: EvidenceUploadQueue) -> None:
    """Əsas istifadə halı: müqavilə PDF-dir və növbəyə DÜŞMƏLİDİR."""
    entry_id = _enqueue(
        queue,
        content=TINY_PDF,
        filename="müqavilə.pdf",
        owner_type=UploadOwnerType.EMPLOYEE_DOCUMENT,
    )

    assert [item.id for item in queue.pending(now=AUGUST)] == [entry_id]


def test_pdf_named_file_with_foreign_content_is_rejected(
    queue: EvidenceUploadQueue, tmp_path: Path
) -> None:
    """HÜCUM: `.pdf` adı ilə göndərilən `.exe` — məzmun imzası onu tutur."""
    with pytest.raises(EvidenceValidationError, match="PDF"):
        _enqueue(
            queue,
            content=FAKE_IMAGE,
            filename="müqavilə.pdf",
            owner_type=UploadOwnerType.EMPLOYEE_DOCUMENT,
        )

    assert list((tmp_path / "spool").iterdir()) == [], "saxta PDF diskə yazıldı"
    assert queue.pending(now=AUGUST) == []


def test_fine_evidence_still_refuses_pdf(queue: EvidenceUploadQueue, tmp_path: Path) -> None:
    """Cərimə sübutu FOTO-dur: qanuni PDF belə ora düşmür (hücum səthi dar qalır)."""
    with pytest.raises(EvidenceValidationError, match="format"):
        _enqueue(queue, content=TINY_PDF, filename="sübut.pdf")

    assert list((tmp_path / "spool").iterdir()) == []
    assert queue.pending(now=AUGUST) == []


def test_pdf_rejection_message_names_the_allowed_formats() -> None:
    """Rədd səssiz deyil — operator hansı formatın qəbul edildiyini oxuyur."""
    with pytest.raises(EvidenceValidationError) as error:
        validate_evidence_payload(TINY_PDF, "sübut.pdf")

    assert ".pdf" not in error.value.user_message, "cərimə mətni PDF vəd etməməlidir"

    with pytest.raises(EvidenceValidationError) as document_error:
        validate_evidence_payload(
            TINY_PDF, "müqavilə.docx", owner_type=UploadOwnerType.EMPLOYEE_DOCUMENT.value
        )

    assert ".pdf" in document_error.value.user_message


def test_unknown_owner_type_falls_back_to_the_narrowest_list() -> None:
    """Fail-closed: siyahıda olmayan sahib tipi PDF-i AÇMIR."""
    with pytest.raises(EvidenceValidationError, match="format"):
        validate_evidence_payload(TINY_PDF, "sənəd.pdf", owner_type="TASK_PROOF")

    validate_evidence_payload(TINY_PNG, "şəkil.png", owner_type="TASK_PROOF")


def test_permanently_invalid_item_leaves_the_retry_loop(
    queue: EvidenceUploadQueue, tmp_path: Path
) -> None:
    """Hədd sonradan aşağı salınıb — element SONSUZ təkrar cəhdə düşməməlidir.

    Bu, tapıntının əsas ssenarisidir: növbədəki (əvvəllər qanuni) şəkil
    provider-in yeni həddini keçmir. Köhnə davranış `FAILED` + backoff idi,
    yəni hər 10 dəqiqədən bir eyni rədd cavabı.
    """
    entry_id = _enqueue(queue, content=TINY_PNG, filename="sübut.png")
    worker = EvidenceUploadWorker(
        queue=queue,
        provider_factory=_Factory(_provider(tmp_path, max_upload_bytes=16)),
    )

    report = worker.run_once(now=AUGUST)

    assert report.rejected == 1
    assert report.failed == 0, "daimi qüsur müvəqqəti nasazlıqla qarışdırıldı"
    entry = queue.get(entry_id)
    assert entry is not None
    assert entry.status is UploadStatus.REJECTED
    # Backoff cədvəlinin sonuna qədər getsək belə element geri qayıtmır.
    assert queue.pending(now=AUGUST + timedelta(days=7)) == []
    assert entry.spool_path.exists(), "bayt itdi — hədd geri qaldırılsa bərpa mümkün olmalıdır"


def test_transient_drive_failure_is_still_retried(
    queue: EvidenceUploadQueue, tmp_path: Path
) -> None:
    """QIRMIZI XƏTT: şəbəkə nasazlığı rədd DEYİL — şəkil növbədə qalır."""
    provider = _provider(tmp_path, max_upload_bytes=5 * 1024 * 1024)

    def boom(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("Drive əlçatmazdır")

    provider._api.upload_file = boom  # type: ignore[method-assign, union-attr]
    _enqueue(queue, content=TINY_PNG, filename="sübut.png")
    worker = EvidenceUploadWorker(queue=queue, provider_factory=_Factory(provider))

    report = worker.run_once(now=AUGUST)

    assert report.failed == 1
    assert report.rejected == 0
    assert len(queue.pending(now=AUGUST + timedelta(seconds=31))) == 1


def test_legacy_queue_file_gets_the_rejected_status(tmp_path: Path) -> None:
    """Köhnə SQLite faylında `CHECK` yalnız üç dəyər tanıyırdı.

    Miqrasiya olmasaydı, `mark_rejected` məhz köhnə quraşdırmalarda
    `IntegrityError` verərdi — yəni sonsuz dövrəni qıran mexanizm ən çox
    lazım olan yerdə işləməzdi.
    """
    db_path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(db_path)
    legacy.executescript(
        """
        CREATE TABLE evidence_uploads (
            id TEXT PRIMARY KEY, seq INTEGER NOT NULL, tenant_id TEXT NOT NULL,
            fine_id TEXT NOT NULL, store_id TEXT NOT NULL, filename TEXT NOT NULL,
            spool_path TEXT NOT NULL, taken_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK (status IN ('PENDING', 'UPLOADED', 'FAILED')),
            attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
            queued_at TEXT NOT NULL, next_attempt_at TEXT NOT NULL,
            uploaded_at TEXT, drive_file_id TEXT, connection_id TEXT
        );
        CREATE INDEX idx_evidence_ready
            ON evidence_uploads (status, next_attempt_at, seq);
        """
    )
    legacy.execute(
        "INSERT INTO evidence_uploads (id, seq, tenant_id, fine_id, store_id, filename,"
        " spool_path, taken_at, queued_at, next_attempt_at)"
        " VALUES ('köhnə-1', 1, ?, ?, ?, 'a.png', ?, ?, ?, ?)",
        (
            TENANT,
            str(uuid.uuid4()),
            str(STORE),
            str(tmp_path / "spool" / "köhnə-1.bin"),
            AUGUST.isoformat(),
            AUGUST.isoformat(),
            AUGUST.isoformat(),
        ),
    )
    legacy.commit()
    legacy.close()

    queue = EvidenceUploadQueue(db_path, spool_dir=tmp_path / "spool", tenant_id=TENANT)
    try:
        assert queue.get("köhnə-1") is not None, "köçürmə sətri itirdi"
        queue.mark_rejected("köhnə-1", "Şəkil çox böyükdür", now=AUGUST)
        entry = queue.get("köhnə-1")
        assert entry is not None
        assert entry.status is UploadStatus.REJECTED
        assert queue.pending(now=AUGUST + timedelta(days=1)) == []
    finally:
        queue.close()


class _Factory:
    def __init__(self, provider: object) -> None:
        self._provider = provider

    def active(self) -> object:
        return self._provider


# --------------------------------------------------------------------------- #
# Tapıntı 4 — baza şifrəsi əmr sətrində
# --------------------------------------------------------------------------- #


def _migrator(runner: Any = None) -> PgDumpMigrator:
    return PgDumpMigrator(
        dsn_by_target={
            DatabaseTarget.CLOUD: DSN_WITH_PASSWORD,
            DatabaseTarget.PRIVATE_SERVER: f"postgres://kompas:{SECRET}@10.0.0.5:5432/kompasos",
        },
        runner=runner,
    )


def test_migration_command_line_never_carries_the_password() -> None:
    """`ps`/Process Explorer ilə oxunan arqumentlərdə şifrə OLMAMALIDIR."""
    captured: list[Sequence[str]] = []

    def spy(command: Sequence[str]) -> int:
        captured.append(list(command))
        return 0

    _migrator(spy).copy(source=DatabaseTarget.CLOUD, destination=DatabaseTarget.PRIVATE_SERVER)

    assert len(captured) == 2, "əmrlərin sayı/sırası dəyişdi"
    flat = " ".join(part for command in captured for part in command)
    assert SECRET not in flat
    # Davranış eynidir: host/baza hələ də verilir, yalnız şifrə çıxıb.
    assert "db.kompas.az" in flat
    assert captured[0][0] == "pg_dump"
    assert captured[1][0] == "pg_restore"


def test_migration_password_travels_through_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Şifrə itmir — `pg_dump` onu `PGPASSWORD`-dən oxuyur."""
    seen: list[dict[str, Any]] = []

    class _Completed:
        returncode = 0
        stderr = b""

    def fake_run(command: Sequence[str], **kwargs: Any) -> Any:
        seen.append({"command": list(command), "env": kwargs.get("env")})
        return _Completed()

    monkeypatch.setattr(subprocess, "run", fake_run)
    _migrator().copy(source=DatabaseTarget.CLOUD, destination=DatabaseTarget.PRIVATE_SERVER)

    assert seen, "əmr ümumiyyətlə icra olunmadı"
    for call in seen:
        assert SECRET not in " ".join(call["command"])
        assert call["env"]["PGPASSWORD"] == SECRET


def test_dsn_without_password_keeps_everything_else() -> None:
    assert dsn_without_password(DSN_WITH_PASSWORD) == (
        "postgres://kompas@db.kompas.az:5432/kompasos"
    )
    # Şifrəsiz DSN toxunulmadan qaytarılır.
    assert dsn_without_password("postgres://kompas@localhost/db") == (
        "postgres://kompas@localhost/db"
    )
    assert password_env("postgres://kompas@localhost/db") == {}


# --------------------------------------------------------------------------- #
# Tapıntı 6 — audit axtarışındakı ILIKE naxışı
# --------------------------------------------------------------------------- #


def test_wildcards_in_audit_search_are_escaped() -> None:
    """`%` yazan istifadəçi süzgəci "hamısını göstər"ə çevirə bilməməlidir."""
    clauses, params = PostgresAuditReader._where(
        uuid.uuid4(),  # type: ignore[arg-type]
        AuditFilter(search="100%_gecikmə"),
    )

    assert "ESCAPE" in clauses
    assert params[-1] == "%100\\%\\_gecikmə%"


def test_audit_search_text_stays_a_bound_parameter() -> None:
    """Hücum sətri SQL mətninə deyil, parametrə düşür."""
    attack = "'; DROP TABLE audit_logs; --"
    clauses, params = PostgresAuditReader._where(
        uuid.uuid4(),  # type: ignore[arg-type]
        AuditFilter(search=attack),
    )

    assert "DROP" not in clauses
    assert clauses.count("%s") == len(params)
    # Mətn dəyər kimi qalır; yalnız `_` joker simvolu hərfiləşir.
    assert params[-1] == "%'; DROP TABLE audit\\_logs; --%"
