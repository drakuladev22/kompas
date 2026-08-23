"""Yarış vəziyyəti (race condition) qapaqlarının testləri.

Sərhəd-hal auditi altı boşluq aşkarladı; bu modul onlardan İKİSİNİ əhatə edir:

    * Sübut şəkli növbəsində "claim" mexanizmi (iki işçi eyni şəkli Drive-a
      İKİ dəfə yükləyə bilirdi);
    * DB-səviyyəli struktur zəmanətlərin SQL mənbələrində HƏLƏ DƏ mövcud
      olması (qismən unikal indeks + `chk_fine_published` istisnası).

──────────────────────────────────────────────────────────────────────────────
SQL TESTLƏRİ NİYƏ MƏTN ÜZƏRİNDƏ İŞLƏYİR
──────────────────────────────────────────────────────────────────────────────
İndeks və trigger yalnız canlı PostgreSQL-də icra olunur, vahid testlərdə isə
sahtə repo-lar var — yəni `database/tests/test_guards.sql` YALNIZ CI-dakı
`db-schema` job-unda işləyir. `tests/unit/test_db_guard_parity.py` məhz həmin
boşluğu bağlamaq üçün SQL mətnini oxuyur; burada eyni naxış təkrarlanır.
Sual "qayda DB tərəfində varmı", cavab isə mənbədən oxunur; sintaksisi CI
icra edir.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest

from src.domain.value_objects.identifiers import StoreId
from src.domain.value_objects.storage import StorageProviderKind, StorageReference
from src.infrastructure.storage.upload_queue import (
    FALLBACK_CLAIM_STALE_AFTER_SECONDS,
    EvidenceUploadQueue,
    EvidenceUploadWorker,
    UploadOwnerType,
    UploadStatus,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA_FILE: Final = PROJECT_ROOT / "database" / "schema.sql"
MIGRATIONS_DIR: Final = PROJECT_ROOT / "database" / "migrations"
GUARD_TEST_FILE: Final = PROJECT_ROOT / "database" / "tests" / "test_guards.sql"

STORE = StoreId(uuid.uuid4())
AUGUST: Final = datetime(2026, 8, 15, 10, 30, tzinfo=UTC)

_LINE_COMMENT_RE: Final = re.compile(r"--[^\n]*")


def _png() -> bytes:
    """Real PNG — `validate_evidence_payload` imza yoxlamasından keçməlidir."""
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _sql_without_comments(path: Path) -> str:
    """`--` şərhlərini atır.

    Miqrasiya faylları sonunda ŞƏRHƏ ALINMIŞ DOWN bloku saxlayır (CLAUDE.md
    §7) və orada qaydanın ƏKSİ yazılıdır. Şərhlər atılmasa, "faylda var"
    yoxlaması məhz DOWN blokundakı sətri tapıb yanlış nəticə verərdi.
    """
    return _LINE_COMMENT_RE.sub("", path.read_text(encoding="utf-8"))


def _normalized(text: str) -> str:
    """Ardıcıl boşluqları tək boşluğa yığır — SQL formatlaması sərbəst olsun."""
    return re.sub(r"\s+", " ", text)


def _index_predicate(normalized_sql: str, index_name: str) -> str:
    """İndeksin `WHERE` predikatı — MƏHZ `CREATE` ifadəsindən.

    Sadəcə ada görə bölmək YETƏRSİZDİR: miqrasiya faylında eyni ad `DROP
    INDEX` və `COMMENT ON INDEX` ifadələrində də keçir, ilk uyğunluq isə
    `DROP` olur — nəticədə test boş sətri yoxlayıb yalançı nəticə verərdi.
    """
    anchor = f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name}"
    assert anchor in normalized_sql, f"'{index_name}' üçün CREATE ifadəsi tapılmadı"
    return normalized_sql.split(anchor, 1)[1].split(";", 1)[0]


# --------------------------------------------------------------------------- #
# Sübut növbəsi — atomik "claim"
# --------------------------------------------------------------------------- #


#: SAAS-3 — iki sabit, çünki iki fərqli sual ölçülür: adi növbə
#: (`QUEUE_TENANT`) və köhnə SQLite faylından KÖÇÜRÜLƏN sətir
#: (`LEGACY_TENANT`). Köçürmə testinin predmeti sxemdir, kirayəçi
#: süzgəci deyil — ona görə həmin növbə köhnə sətrin kirayəçisi ilə açılır.
QUEUE_TENANT: str = str(uuid.uuid4())
LEGACY_TENANT: str = str(uuid.uuid4())


@pytest.fixture
def queue(tmp_path: Path) -> Iterator[EvidenceUploadQueue]:
    q = EvidenceUploadQueue(
        tmp_path / "uploads.db", spool_dir=tmp_path / "spool", tenant_id=QUEUE_TENANT
    )
    yield q
    q.close()


def _enqueue(queue: EvidenceUploadQueue, *, now: datetime = AUGUST) -> str:
    return queue.enqueue(
        # SAAS-3: sətir növbənin KİRAYƏÇİSİ ilə eyni olmalıdır.
        tenant_id=QUEUE_TENANT,
        owner_type=UploadOwnerType.FINE,
        owner_id=str(uuid.uuid4()),
        store_id=STORE,
        filename="sübut.png",
        content=_png(),
        taken_at=now,
        now=now,
    )


class _CountingProvider:
    """Hər `upload()` çağırışını sayır — ikiqat yükləmə dərhal görünür."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.owner_types: list[str] = []

    def upload(
        self,
        _content: bytes,
        filename: str,
        _store_id: uuid.UUID,
        _taken_at: datetime,
        *,
        owner_type: str = "FINE",
    ) -> StorageReference:
        # `owner_type` real provider-in imzasını təkrarlayır (SEC-018): işçi
        # onu HƏMİŞƏ açar söz kimi ötürür, sahtə isə yalnız qəbul edir.
        self.owner_types.append(owner_type)
        self.calls.append(filename)
        return StorageReference(
            provider=StorageProviderKind.GOOGLE_DRIVE,
            file_id=f"drive-{len(self.calls)}",
            connection_id=uuid.uuid4(),
        )


class _Factory:
    def __init__(self, provider: object, *, available: bool = True) -> None:
        self._provider = provider
        self.available = available

    def active(self) -> object:
        if not self.available:
            raise RuntimeError("aktiv Drive bağlantısı yoxdur")
        return self._provider


def test_claim_removes_the_item_from_the_pending_view(queue: EvidenceUploadQueue) -> None:
    """Claim edilmiş element ikinci işçiyə GÖRÜNMÜR."""
    entry_id = _enqueue(queue)

    claimed = queue.claim_pending(now=AUGUST)

    assert [item.id for item in claimed] == [entry_id]
    assert claimed[0].status is UploadStatus.PROCESSING, "qaytarılan obyekt claim-i gizlədir"
    assert queue.claim_pending(now=AUGUST) == [], "ikinci işçi eyni elementi götürdü"
    assert queue.pending(now=AUGUST) == []
    entry = queue.get(entry_id)
    assert entry is not None
    assert entry.status is UploadStatus.PROCESSING


def test_pending_and_claim_are_scoped_to_the_queues_own_tenant(tmp_path: Path) -> None:
    """D2 (dövrə audit): tenant-siz növbə faylı KEÇMİŞ tenant-ı yükləmirdi.

    `evidence_uploads.db` bir DATA QOVLUĞUNA bağlıdır, tenant-a YOX
    (`resolve_data_file`). Maşın YENİ tenant üçün yenidən quraşdırılsa (və ya
    köhnə fayl silinməyibsə), köhnə tenant-ın gözləyən sətirləri qalırdı.
    Filtrsiz `claim_pending()` onları CARİ (`self._factory.active()`)
    tenant-ın Drive-ına yükləyirdi — sübut zənciri qırılırdı: `file_id` A-nın
    `fines` sətrinə yazılır, fayl B-nin Drive-ındadır.

    Konstruktora `tenant_id` verildikdə (kompozisiya kökünün YEGANƏ yolu,
    bax `composition.py::evidence_queue`) B tenant-ının növbəsi A-nın
    sətrini nə `pending()`-də, nə `claim_pending()`-də GÖRMƏMƏLİDİR.
    """
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    # A tenant-ı ÖZ növbəsini qurur və bir şəkil əlavə edir — B-nin növbəsi
    # İLƏ EYNİ SQLite faylını paylaşır (köhnə quraşdırmanın qalığı ssenarisi).
    queue_a = EvidenceUploadQueue(
        tmp_path / "uploads.db", spool_dir=tmp_path / "spool", tenant_id=tenant_a
    )
    queue_a.enqueue(
        tenant_id=tenant_a,
        owner_type=UploadOwnerType.FINE,
        owner_id=str(uuid.uuid4()),
        store_id=STORE,
        filename="a.png",
        content=_png(),
        taken_at=AUGUST,
        now=AUGUST,
    )
    queue_a.close()

    queue_b = EvidenceUploadQueue(
        tmp_path / "uploads.db", spool_dir=tmp_path / "spool", tenant_id=tenant_b
    )
    try:
        assert queue_b.pending(now=AUGUST) == [], "B tenant-ı A-nın sətrini görür"
        assert queue_b.claim_pending(now=AUGUST) == [], "B tenant-ı A-nın sətrini claim etdi"
    finally:
        queue_b.close()


def test_tenant_id_none_keeps_the_old_unscoped_behaviour(queue: EvidenceUploadQueue) -> None:
    """`tenant_id=None` (defolt) — bu faylın DİGƏR testlərinin tarixçəsi.

    Kompozisiya kökü onu HƏMİŞƏ ötürür (bax `composition.py`), amma sinif
    ÖZÜ `tenant_id` tələb ETMİR — çoxlu mövcud testin (bu faylda, `test_
    drive_storage.py`, `test_audit_and_queue_recovery.py`, `test_security_
    hardening.py`) sınaq niyyəti tenant izolyasiyası DEYİL və onları
    dəyişməyə ehtiyac yaratmamalıdır.
    """
    _enqueue(queue)
    assert len(queue.pending(now=AUGUST)) == 1
    assert len(queue.claim_pending(now=AUGUST + timedelta(seconds=1))) == 1


def test_two_workers_upload_the_photo_only_once(queue: EvidenceUploadQueue) -> None:
    """TAPINTININ ÖZÜ: paralel iki işçi → Drive-a BİR fayl.

    Əvvəl `pending()` sadəcə oxuyurdu, ona görə hər iki işçi eyni sətri görür
    və eyni şəkli iki dəfə yükləyirdi (yetim fayl + boşuna kvota).
    """
    _enqueue(queue)
    provider = _CountingProvider()
    first = EvidenceUploadWorker(queue=queue, provider_factory=_Factory(provider))
    second = EvidenceUploadWorker(queue=queue, provider_factory=_Factory(provider))

    report_1 = first.run_once(now=AUGUST)
    report_2 = second.run_once(now=AUGUST)

    assert report_1.uploaded == 1
    assert report_2.attempted == 0, "ikinci işçi artıq götürülmüş elementi işlədi"
    assert len(provider.calls) == 1, "şəkil Drive-a İKİ dəfə yükləndi"


def test_claim_is_released_when_there_is_no_connection(queue: EvidenceUploadQueue) -> None:
    """Yükləmə CƏHD EDİLMƏYİBSƏ claim dərhal geri qaytarılır.

    Əks halda şəkillər köhnəlmə müddəti (10 dəq.) boyu "görünməz" qalar və
    bağlantı bərpa olunan kimi göndərilməzdi.
    """
    _enqueue(queue)
    worker = EvidenceUploadWorker(
        queue=queue, provider_factory=_Factory(_CountingProvider(), available=False)
    )

    report = worker.run_once(now=AUGUST)

    assert report.skipped_no_connection is True
    assert len(queue.pending(now=AUGUST)) == 1, "claim geri buraxılmadı"


def test_stuck_claim_is_recovered_after_the_stale_window(queue: EvidenceUploadQueue) -> None:
    """Proses `PROCESSING`-də çökübsə element ƏBƏDİ ilişmir."""
    entry_id = _enqueue(queue)
    queue.claim_pending(now=AUGUST)  # "çökmüş" işçi — heç vaxt tamamlamır

    just_before = AUGUST + timedelta(seconds=FALLBACK_CLAIM_STALE_AFTER_SECONDS - 1)
    assert queue.claim_pending(now=just_before) == [], "köhnəlmə vaxtından əvvəl geri alındı"

    at_stale = AUGUST + timedelta(seconds=FALLBACK_CLAIM_STALE_AFTER_SECONDS)
    recovered = queue.claim_pending(now=at_stale)

    assert [item.id for item in recovered] == [entry_id]


def test_failed_upload_returns_to_pending_after_backoff(queue: EvidenceUploadQueue) -> None:
    """`mark_failed` elementi `PROCESSING`-dən `PENDING`-ə qaytarır.

    Qaytarmasaydı, backoff bitsə də element `PENDING` seçiminə düşməzdi və
    yalnız köhnəlmə müddətindən sonra bərpa olunardı — yəni retry cədvəli
    (30s → 2dq → 10dq) sükutla mənasız olardı.
    """
    entry_id = _enqueue(queue)
    queue.claim_pending(now=AUGUST)

    queue.mark_failed(entry_id, "Drive əlçatmazdır", now=AUGUST)

    entry = queue.get(entry_id)
    assert entry is not None
    assert entry.status is UploadStatus.PENDING
    assert queue.pending(now=AUGUST) == [], "backoff tətbiq olunmadı"
    assert len(queue.pending(now=AUGUST + timedelta(seconds=31))) == 1


def test_legacy_queue_file_gets_the_processing_status(tmp_path: Path) -> None:
    """Köhnə SQLite faylında `CHECK` `PROCESSING`-i tanımırdı.

    Köçürmə olmasaydı, ikiqat yükləməni əngəlləyən mexanizm məhz köhnə
    quraşdırmalarda `IntegrityError` verərdi — yəni ən çox lazım olan yerdə
    işləməzdi (eyni səbəb Faza 3-də `REJECTED` üçün də olmuşdu).
    """
    import sqlite3

    db_path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(db_path)
    legacy.executescript(
        """
        CREATE TABLE evidence_uploads (
            id TEXT PRIMARY KEY, seq INTEGER NOT NULL, tenant_id TEXT NOT NULL,
            fine_id TEXT NOT NULL, store_id TEXT NOT NULL, filename TEXT NOT NULL,
            spool_path TEXT NOT NULL, taken_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK (status IN ('PENDING', 'UPLOADED', 'FAILED', 'REJECTED')),
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
            LEGACY_TENANT,
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

    queue = EvidenceUploadQueue(db_path, spool_dir=tmp_path / "spool", tenant_id=LEGACY_TENANT)
    try:
        assert queue.get("köhnə-1") is not None, "köçürmə sətri itirdi"
        claimed = queue.claim_pending(now=AUGUST)
        assert [item.id for item in claimed] == ["köhnə-1"]
        entry = queue.get("köhnə-1")
        assert entry is not None
        assert entry.status is UploadStatus.PROCESSING
    finally:
        queue.close()


def test_legacy_queue_file_without_owner_columns_is_backfilled(tmp_path: Path) -> None:
    """#17: `fine_id` → `owner_type`/`owner_id` köçürməsi məlumat İTİRMİR.

    Bu, `_ensure_owner_columns()` üçün MƏCBURİ ssenaridir (Faza 7 tapşırığı):
    istifadəçinin diskində artıq gözləyən (hələ Drive-a yüklənməmiş) sübut
    şəkilləri OLA BİLƏR — sxem köçürülərkən onların sətri İTMƏMƏLİDİR və
    köhnə `fine_id`-dən `owner_type='FINE'` DÜZGÜN çıxarılmalıdır.
    """
    import sqlite3

    db_path = tmp_path / "legacy_no_owner.db"
    fine_id = str(uuid.uuid4())
    legacy = sqlite3.connect(db_path)
    # Bu, #17-dən DƏRHAL ƏVVƏLKİ sxemdir — 5 statuslu `CHECK`, lakin
    # `owner_type`/`owner_id` sütunları HƏLƏ YOXDUR.
    legacy.executescript(
        """
        CREATE TABLE evidence_uploads (
            id TEXT PRIMARY KEY, seq INTEGER NOT NULL, tenant_id TEXT NOT NULL,
            fine_id TEXT NOT NULL, store_id TEXT NOT NULL, filename TEXT NOT NULL,
            spool_path TEXT NOT NULL, taken_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK (status IN ('PENDING', 'PROCESSING', 'UPLOADED',
                                  'FAILED', 'REJECTED')),
            attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
            queued_at TEXT NOT NULL, next_attempt_at TEXT NOT NULL,
            uploaded_at TEXT, drive_file_id TEXT, connection_id TEXT
        );
        CREATE INDEX idx_evidence_ready
            ON evidence_uploads (status, next_attempt_at, seq);
        """
    )
    spool_path = tmp_path / "spool" / "köhnə-2.bin"
    legacy.execute(
        "INSERT INTO evidence_uploads (id, seq, tenant_id, fine_id, store_id, filename,"
        " spool_path, taken_at, queued_at, next_attempt_at)"
        " VALUES ('köhnə-2', 1, ?, ?, ?, 'a.png', ?, ?, ?, ?)",
        (
            LEGACY_TENANT,
            fine_id,
            str(STORE),
            str(spool_path),
            AUGUST.isoformat(),
            AUGUST.isoformat(),
            AUGUST.isoformat(),
        ),
    )
    legacy.commit()
    legacy.close()

    queue = EvidenceUploadQueue(db_path, spool_dir=tmp_path / "spool", tenant_id=LEGACY_TENANT)
    try:
        entry = queue.get("köhnə-2")
        assert entry is not None, "köçürmə sətri itirdi"
        assert entry.owner_type is UploadOwnerType.FINE
        assert entry.owner_id == fine_id
        # Oxu yolları (`pending`/`claim_pending`) da köçürülmüş sətri normal
        # görməlidir — backfill YALNIZ sütunları doldurur, statusu POZMUR.
        assert [item.id for item in queue.pending(now=AUGUST)] == ["köhnə-2"]
    finally:
        queue.close()


def test_zero_stale_window_falls_back_to_the_default(tmp_path: Path) -> None:
    """Səhv konfiqurasiya qorumanı SÜKUTLA söndürməməlidir."""
    queue = EvidenceUploadQueue(
        tmp_path / "q.db",
        spool_dir=tmp_path / "spool",
        claim_stale_after_seconds=0,
        tenant_id=QUEUE_TENANT,
    )
    try:
        _enqueue(queue)
        queue.claim_pending(now=AUGUST)
        # Defolta qayıtmasaydı, element claim edilən anda köhnəlmiş sayılardı.
        assert queue.claim_pending(now=AUGUST) == []
    finally:
        queue.close()


# --------------------------------------------------------------------------- #
# DB struktur zəmanətləri — SQL mənbələrində mövcudluq
# --------------------------------------------------------------------------- #


def test_partial_unique_index_exists_in_schema_and_migration() -> None:
    """Qayda İKİ yerdədir (CLAUDE.md §5) və hər ikisi eyni şərti yazır."""
    index_name = "uq_fines_one_live_auto_delay_per_leave"
    for path in (SCHEMA_FILE, MIGRATIONS_DIR / "015_race_condition_guards.sql"):
        sql = _normalized(_sql_without_comments(path))
        assert index_name in sql, f"{path.name}: indeks yoxdur"
        assert "ON fines (leave_request_id)" in sql, f"{path.name}: indeks sütunu dəyişib"
        assert "source = 'AUTO_DELAY'" in sql, f"{path.name}: mənbə şərti yoxdur"
        assert "status IN ('PENDING_REVIEW', 'PUBLISHED', 'REDUCED')" in sql, (
            f"{path.name}: diri status siyahısı dəyişib"
        )


def test_the_index_never_covers_reversed_rows() -> None:
    """⚠️ ƏN İNCƏ ŞƏRT: `REVERSED` indeksdən KƏNARDA qalmalıdır.

    Saga kompensasiyası cəriməni `REVERSED` edir. Ölü sətir indeks yerini
    tutsaydı, işçinin həmin STEP 3-ü təkrar təsdiqlətməsi ƏBƏDİ bloklanardı —
    yəni qapaq özü yeni qüsur yaradardı.
    """
    for path in (SCHEMA_FILE, MIGRATIONS_DIR / "015_race_condition_guards.sql"):
        sql = _normalized(_sql_without_comments(path))
        predicate = _index_predicate(sql, "uq_fines_one_live_auto_delay_per_leave")
        assert "REVERSED" not in predicate, f"{path.name}: REVERSED indeksə düşür!"


def test_check_constraint_allows_the_never_published_reversal() -> None:
    """`chk_fine_published` kompensasiyanın yazılmasına icazə verməlidir.

    `discard_in_review()` `published_at`-ı NULL saxlayır. Köhnə məhdudiyyət
    `PENDING_REVIEW`-dan fərqli hər statusda onun dolu olmasını tələb edirdi,
    yəni kompensasiya CHECK pozuntusu ilə çökərdi və cərimə `PENDING_REVIEW`
    yetim sətir kimi qalardı.
    """
    for path in (SCHEMA_FILE, MIGRATIONS_DIR / "015_race_condition_guards.sql"):
        sql = _normalized(_sql_without_comments(path))
        assert "status = 'REVERSED' AND published_at IS NULL" in sql, (
            f"{path.name}: kompensasiya budağı yoxdur"
        )


def test_check_constraint_requires_drive_evidence_for_published_manual_camera_fines() -> None:
    """`chk_fine_published` (081, T3, DEEP-GAP dövrə 4) — sübutsuz NƏŞR bloklanır.

    `photo_evidence_url` MANUAL_CAMERA axınında LOKAL NÖVBƏ AÇARINI saxlayır
    (`upload_queue.py`), Drive-a çatdığını SÜBUT ETMİR — `evidence_drive_
    file_id` (migrations/002) HƏQİQİ göstəricidir. Bu test `migrations/081`-
    in dörd budağının hamısını (015-in ÜÇÜ + YENİ evidence budağı) daşıdığını
    təsdiqləyir.

    `schema.sql` BU MİQRASİYA ilə YENİLƏNMİR (qəsdən) — `evidence_drive_
    file_id` sütunu bazis `fines` tərifində YOXDUR (CLAUDE.md §7). Ona görə
    schema.sql BURADA YOXLANILMIR — yalnız `081`-in özü.
    """
    path = MIGRATIONS_DIR / "081_fine_published_requires_drive_evidence.sql"
    sql = _normalized(_sql_without_comments(path))

    # 015-in üç budağı İTİRİLMƏYİB (saga kompensasiyası çökməsin).
    assert "status = 'PENDING_REVIEW'" in sql
    assert "published_at IS NOT NULL AND appeal_window_closes_at IS NOT NULL" in sql
    assert "status = 'REVERSED' AND published_at IS NULL" in sql

    # YENİ (081) budaq: EXPORTABLE statusda MANUAL_CAMERA sübutu tələb edir.
    assert "status NOT IN ('PUBLISHED', 'REDUCED')" in sql, (
        "evidence budağı `EXPORTABLE_STATUSES`-ə (PUBLISHED+REDUCED) uyğun deyil"
    )
    assert "source <> 'MANUAL_CAMERA'" in sql
    assert "evidence_drive_file_id IS NOT NULL" in sql
    # İrs sətir istisnası (`team-lead`-in qərarı — ölçmə mümkün olmadığı üçün
    # `NOT VALID` əvəzinə açıq budaq): 002-dən ƏVVƏLKİ sübut HTTP URL-idir.
    assert "photo_evidence_url LIKE 'http%'" in sql


def test_guard_suite_covers_the_new_race_conditions() -> None:
    """SQL guard dəsti yeni qapaqları da yoxlayır (CI `db-schema` job-u)."""
    sql = GUARD_TEST_FILE.read_text(encoding="utf-8")

    assert "TEST 25" in sql, "ikinci diri AUTO_DELAY cəriməsi testi yoxdur"
    assert "TEST 26" in sql, "REVERSED sətrin bloklamadığını yoxlayan test yoxdur"
    assert "TEST 27" in sql, "ikinci açıq icazə testi yoxdur"
    assert "TEST 28" in sql, "TIMEOUT_ESCALATED paritet testi yoxdur"
    assert "TEST 29" in sql, "etiraz pəncərəsinin başlanğıc anı testi yoxdur"
    assert "TEST 30" in sql, "PENDING_REVIEW export sızması testi yoxdur"

    # YEKUN SAYĞAC SABİT ƏDƏDLƏ MÜQAYİSƏ EDİLMİR: dəst böyüdükcə (məs. TEST
    # 31/32 — Root/CEO prioritet ayrılığı) sabit yazılış hər dəfə köhnəlir və
    # düzəliş "testi yenilə" refleksinə çevrilir. Bunun əvəzinə İDDİA
    # GÜCLƏNDİRİLİR: sayğac faylın ƏN BÖYÜK `TEST N` nömrəsi ilə eyni
    # olmalıdır — yəni yeni test əlavə edib sayğacı unutmaq da tutulur.
    numbers = {int(match) for match in re.findall(r"TEST (\d+)", sql)}
    assert numbers, "SQL guard dəstində heç bir `TEST N` başlığı tapılmadı"
    assert f"%/{max(numbers)}" in sql, (
        f"yekun sayğac ən böyük test nömrəsi ({max(numbers)}) ilə uyğun gəlmir"
    )


# --------------------------------------------------------------------------- #
# Cərimə/export düzgünlüyü — domen ↔ SQL pariteti
# --------------------------------------------------------------------------- #


def test_export_filter_is_built_from_the_domain_source() -> None:
    """SQL status siyahısı `Fine.EXPORTABLE_STATUSES`-dən QURULUR.

    Siyahı SQL-də əl ilə təkrar yazılsaydı, domendə status dəsti dəyişəndə
    sorğu sükutla köhnə qalardı — tapıntının ilkin səbəbi məhz budur:
    miqrasiya 003 `v_exportable_fines`-i yenilədi, `list_exportable` isə
    `status <> 'REVERSED'` modelində qaldı.
    """
    from src.domain.entities.fine import EXPORTABLE_STATUSES, FineStatus
    from src.infrastructure.persistence.repositories import (
        _EXPORTABLE_FINES_WHERE,
        _EXPORTABLE_STATUS_LITERALS,
    )

    for status in EXPORTABLE_STATUSES:
        assert f"'{status.value}'" in _EXPORTABLE_STATUS_LITERALS

    # PENDING_REVIEW HEÇ VAXT export-a düşmür (bölmə 6, hüquqi risk).
    assert FineStatus.PENDING_REVIEW.value not in _EXPORTABLE_STATUS_LITERALS
    assert FineStatus.REVERSED.value not in _EXPORTABLE_STATUS_LITERALS

    # Determinizm: dəst sırasızdır, sorğu mətni isə sabit olmalıdır.
    assert _EXPORTABLE_STATUS_LITERALS == "'PUBLISHED', 'REDUCED'"

    # DÖRD şərtin hamısı sorğudadır (`Fine.is_exportable` ilə birebir).
    assert "status IN ('PUBLISHED', 'REDUCED')" in _EXPORTABLE_FINES_WHERE
    assert "published_at IS NOT NULL" in _EXPORTABLE_FINES_WHERE
    assert "appeal_window_closes_at <= %s" in _EXPORTABLE_FINES_WHERE
    assert "exported_period IS NULL" in _EXPORTABLE_FINES_WHERE
    # Köhnə, sızmağa imkan verən şərt geri qayıtmamalıdır.
    assert "REVERSED" not in _EXPORTABLE_FINES_WHERE


def test_an_undecided_appeal_blocks_the_export_in_domain_sql_and_view() -> None:
    """M-6 dördüncü şərti ÜÇ qatda da eynidir: domen, repository, görünüş.

    Qayda yalnız domendə olsaydı, ekranı yan keçən export skripti mübahisəli
    cəriməni yenə tutardı; yalnız SQL-də olsaydı, `Fine.is_exportable()`-ə
    güvənən hesabat qatı onu hesablamaya daxil edərdi (CLAUDE.md §5).
    """
    from pathlib import Path

    from src.infrastructure.persistence.repositories import (
        _EXPORTABLE_FINES_WHERE,
        _UNDECIDED_APPEAL_EXISTS,
    )

    # 1. Repository sorğusu — qərarsız etirazı olan sətir SÜZÜLÜR.
    assert "NOT " in _EXPORTABLE_FINES_WHERE
    assert "fine_appeals" in _EXPORTABLE_FINES_WHERE
    for status in ("'PENDING'", "'EXPIRED'"):
        assert status in _UNDECIDED_APPEAL_EXISTS, (
            f"{status} etirazı QƏRARSIZDIR — export kilidi onu əhatə etməlidir"
        )

    # 2. DB görünüşü — miqrasiya 052 eyni şərti `v_exportable_fines`-ə yazır.
    migration = (
        Path(__file__).resolve().parents[2]
        / "database"
        / "migrations"
        / "052_dual_control_timeout_and_disputed_fine_export_lock.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE OR REPLACE VIEW v_exportable_fines" in migration
    assert "fa.status IN ('PENDING', 'EXPIRED')" in migration
    assert "NOT EXISTS" in migration


def test_appeal_window_trigger_counts_from_publication() -> None:
    """`trg_fine_appeal_window` `published_at`-dan sayır, `now()`-dan YOX."""
    for path in (SCHEMA_FILE, MIGRATIONS_DIR / "016_appeal_window_and_open_leave_parity.sql"):
        sql = _normalized(_sql_without_comments(path))
        body = sql.split("FUNCTION set_fine_appeal_window()", 1)[1].split("LANGUAGE plpgsql", 1)[0]

        assert "NEW.published_at + make_interval" in body, f"{path.name}: sayğac nəşrdən sayılmır"
        assert "now() + make_interval" not in body, f"{path.name}: köhnə `now()` düsturu qalıb"
        assert "IF NEW.published_at IS NULL THEN" in body, (
            f"{path.name}: nəşr olunmamış cərimə üçün erkən çıxış yoxdur"
        )
        # Trigger nəşri (UPDATE) də tutmalıdır — əks halda SQL ilə nəşr
        # olunan cərimənin pəncərəsi heç vaxt açılmazdı.
        assert "BEFORE INSERT OR UPDATE ON fines" in sql, f"{path.name}: UPDATE əhatə olunmayıb"


def test_exportable_view_uses_the_frozen_window() -> None:
    """Görünüş DONDURULMUŞ sütuna baxır — cari limitdən yenidən hesablamır.

    Domen dəyəri `publish()` anında dondurur; görünüş isə `published_at +
    CARİ limit` hesablayırdı. Root limiti 72 → 24 saata endirsəydi, artıq
    nəşr olunmuş cərimələrin pəncərəsi RETROAKTİV bağlanardı.
    """
    for path in (SCHEMA_FILE, MIGRATIONS_DIR / "016_appeal_window_and_open_leave_parity.sql"):
        sql = _normalized(_sql_without_comments(path))
        view = sql.split("CREATE OR REPLACE VIEW v_exportable_fines AS", 1)[1].split(";", 1)[0]

        assert "f.status IN ('PUBLISHED', 'REDUCED')" in view, f"{path.name}: status filtri dəyişib"
        assert "f.appeal_window_closes_at <= now()" in view, f"{path.name}: dondurulmuş sütun yox"
        assert "make_interval" not in view, f"{path.name}: pəncərə yenidən hesablanır"


def test_open_leave_index_matches_the_domain_is_open_set() -> None:
    """İndeksin status dəsti `LeaveStatus.is_open` ilə eynidir."""
    from src.domain.entities.leave_request import LeaveStatus

    open_values = sorted(status.value for status in LeaveStatus if status.is_open)
    assert open_values == ["OUTSIDE", "PENDING_RETURN_VERIFICATION", "TIMEOUT_ESCALATED"]

    for path in (SCHEMA_FILE, MIGRATIONS_DIR / "016_appeal_window_and_open_leave_parity.sql"):
        sql = _normalized(_sql_without_comments(path))
        predicate = _index_predicate(sql, "uq_leave_one_open_per_employee")
        for value in open_values:
            assert f"'{value}'" in predicate, f"{path.name}: '{value}' indeksdə yoxdur"


def test_repository_translates_the_unique_violation() -> None:
    """Xam `UniqueViolation` istifadəçiyə ÇATMIR — iş qaydası istisnası olur.

    STEP 1-in cüt kliki DB indeksinə dəyir. Tərcümə olmasaydı, ekranda
    "duplicate key value violates unique constraint" görünərdi; halbuki
    istifadəçiyə lazım olan cavab "sizin artıq açıq icazəniz var"dır.
    """
    from psycopg import errors as pg_errors

    from src.application.use_cases.leave_verification import OperationNotPermittedError
    from src.infrastructure.persistence.repositories import PostgresLeaveRequestRepository

    class _Cursor:
        def __enter__(self) -> _Cursor:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _sql: str, _params: tuple[Any, ...]) -> None:
            raise pg_errors.UniqueViolation("duplicate key value violates unique constraint")

    class _Conn:
        def cursor(self) -> _Cursor:
            return _Cursor()

    class _Context:
        tenant_id = uuid.uuid4()

    from src.domain.entities.leave_request import LeaveRequest
    from src.domain.value_objects.identifiers import (
        EmployeeId,
        LeaveRequestId,
        TenantId,
    )

    repository = PostgresLeaveRequestRepository(_Conn(), _Context())  # type: ignore[arg-type]
    request = LeaveRequest(
        request_id=LeaveRequestId(uuid.uuid4()),
        tenant_id=TenantId(uuid.uuid4()),
        employee_id=EmployeeId(uuid.uuid4()),
        store_id=STORE,
        requested_time=AUGUST,
    )

    with pytest.raises(OperationNotPermittedError, match="açıq icazə"):
        repository.save(request)
