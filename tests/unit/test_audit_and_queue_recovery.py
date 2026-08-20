"""Üç ayrı "vəd verilib, kod yerinə yetirmir" boşluğunun qapıları.

    1. Drive razılığı — SEC-017 həssas əməliyyatı yalnız FAYL jurnalına
       düşürdü; `audit_logs`-a yazılmırdı, yəni Root panelinin «Audit»
       ekranında görünmürdü və rotasiya ilə itirdi.
    2. `UploadStatus.REJECTED` — `mark_rejected()` docstring-i «admin onu
       yenidən növbəyə sala bilər» deyirdi, lakin belə bir metod YOX idi.
    3. Növbədəki "gecikib" həddi — sabit 22 dəqiqə `VERIFICATION_TIMEOUT_MINUTES`
       Root tərəfindən dəyişildikdə eskalasiyadan SONRA xəbərdarlıq verirdi.

Testlər Qt və baza TƏLƏB ETMİR: kontroller sahtə kontekstlə, növbə isə real
SQLite faylı ilə (tmp_path) işləyir.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.infrastructure.storage.google_drive import EvidenceValidationError
from src.infrastructure.storage.upload_queue import (
    EvidenceUploadQueue,
    EvidenceUploadWorker,
    UploadOwnerType,
    UploadStatus,
)
from src.presentation.background_task import InlineExecutor
from src.presentation.controllers.drive_connection import DriveConnectionController
from src.presentation.controllers.screen_data import (
    LATE_QUEUE_MINUTES,
    late_threshold_minutes,
)

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR = uuid.uuid4()
STORE = uuid.uuid4()
FINE = uuid.uuid4()
MOMENT = datetime(2026, 8, 11, 9, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# 1. Drive razılığı → `audit_logs`
# --------------------------------------------------------------------------- #


class _Audit:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.entries: list[dict[str, Any]] = []
        self.failure = failure

    def record(self, **kwargs: Any) -> None:
        if self.failure is not None:
            raise self.failure
        self.entries.append(kwargs)


class _Session:
    def __init__(self, audit: _Audit) -> None:
        self.uow = type("_Uow", (), {"audit": audit})()
        self.committed = False

    def commit(self) -> None:
        self.committed = True

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _Context:
    def __init__(self, audit: _Audit) -> None:
        self.tenant_id = TENANT
        self.sessions: list[_Session] = []
        self.invalidated = 0
        self.upload_runs = 0
        self._audit = audit

    def session(self, **_: Any) -> _Session:
        created = _Session(self._audit)
        self.sessions.append(created)
        return created

    def invalidate_drive_providers(self) -> None:
        self.invalidated += 1

    def run_evidence_uploads(self) -> int:
        self.upload_runs += 1
        return 0


class _Actor:
    id = ACTOR


class _Connection:
    """`DriveConnectionRepository.connect()`-in qaytardığı obyektin əvəzi."""

    def __init__(self, status: str = "ACTIVE") -> None:
        self.id = uuid.uuid4()
        self.google_account_email = "mağaza@şirkət.az"
        self.status = type("_S", (), {"value": status})()
        self.quota_used_bytes: int | None = None
        self.quota_total_bytes: int | None = None
        self.connected_at = MOMENT
        self.archived_at = None


class _Repository:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection
        self.connect_calls: list[dict[str, Any]] = []

    def connect(self, **kwargs: Any) -> _Connection:
        self.connect_calls.append(kwargs)
        return self.connection

    def list_all(self) -> list[_Connection]:
        return [self.connection]


class _Flow:
    def __init__(self) -> None:
        self.closed = False

    def exchange(self, code: str) -> Any:
        del code
        return type(
            "_Credentials",
            (),
            {"account_email": "mağaza@şirkət.az", "refresh_token": "gizli-token"},
        )()

    def close(self) -> None:
        self.closed = True


class _Screen:
    def __init__(self) -> None:
        self.errors: list[tuple[str, str]] = []
        self.active: list[dict[str, Any]] = []
        self.history: list[Any] = []
        self.cleared = 0

    def show_error(self, *, title: str, message: str, **_: Any) -> None:
        self.errors.append((title, message))

    def set_active(self, **kwargs: Any) -> None:
        self.active.append(kwargs)

    def set_history(self, rows: Any) -> None:
        self.history.append(rows)

    def clear_pending(self) -> None:
        self.cleared += 1


def _no_encryption() -> Any:
    return object()


def _controller(
    audit: _Audit, monkeypatch: Any
) -> tuple[DriveConnectionController, _Context, _Repository, _Screen]:
    context = _Context(audit)
    # `InlineExecutor`: bu testlər MƏNTİQİ ölçür, sapı yox — nəticə dərhal,
    # hadisə dövrü gözləmədən qayıdır (bax `background_task.py`).
    controller: DriveConnectionController = DriveConnectionController(  # type: ignore[arg-type]
        context, _Actor(), executor=InlineExecutor()
    )
    repository = _Repository(_Connection())
    monkeypatch.setattr(controller, "_repository", lambda: repository)
    # Şifrələmə xidməti bu testdə heç nə etmir: yoxlanan şey token-in
    # ŞİFRƏLƏNMƏSİ deyil, audit sətrinin YAZILMASIDIR.
    monkeypatch.setattr(controller, "_encryption", _no_encryption)
    controller._flow = _Flow()
    return controller, context, repository, _Screen()


def test_successful_consent_writes_a_db_audit_row(monkeypatch: Any) -> None:
    """Hansı hesabın nə vaxt qoşulduğu `audit_logs`-da qalmalıdır (SEC-017)."""
    audit = _Audit()
    controller, context, repository, screen = _controller(audit, monkeypatch)

    controller._complete(screen, "auth-code")

    assert len(audit.entries) == 1
    entry = audit.entries[0]
    assert entry["action"] == "DRIVE_CONNECTION_ESTABLISHED"
    assert entry["entity_type"] == "drive_connections"
    assert entry["entity_id"] == repository.connection.id
    assert entry["actor_id"] == ACTOR
    assert entry["after_state"]["account"] == "mağaza@şirkət.az"
    # Sessiya commit edilməlidir — əks halda `PostgresUnitOfWork` geri qaytarır
    # və audit sətri heç vaxt yazılmazdı.
    assert context.sessions[0].committed
    assert screen.errors == []


def test_refresh_token_never_reaches_the_audit_row(monkeypatch: Any) -> None:
    """Token yalnız kontrollerin yaddaşında bir an mövcud olur."""
    audit = _Audit()
    controller, _, _, screen = _controller(audit, monkeypatch)

    controller._complete(screen, "auth-code")

    assert "gizli-token" not in str(audit.entries)


def test_audit_failure_is_reported_to_the_user_not_swallowed(monkeypatch: Any) -> None:
    """Bağlantı qalır (geri qaytarıla bilməz), lakin sükut QADAĞANDIR.

    İstisnanı yuxarı ötürsək, uğurla qurulmuş bağlantı "qoşulmadı" kimi
    görünər və administrator eyni hesabı təkrar-təkrar qoşmağa çalışardı.
    """
    audit = _Audit(failure=RuntimeError("audit cədvəli əlçatmazdır"))
    controller, context, repository, screen = _controller(audit, monkeypatch)

    controller._complete(screen, "auth-code")

    assert repository.connect_calls, "Bağlantı yazılmalı idi"
    assert screen.errors and screen.errors[0][0] == "Audit izi yazılmadı"
    # Uğur yolunun qalan addımları DAYANMIR: keş atılır, növbə boşaldılır.
    assert context.invalidated == 1
    assert context.upload_runs == 1


def test_revoked_connection_is_not_shown_as_active(monkeypatch: Any) -> None:
    """RAZILIQ LƏĞVİNDƏN SONRA EKRAN «Aktiv» GÖSTƏRMƏMƏLİDİR.

    Əvvəl kontroller yalnız `status == "ACTIVE"` sətrini axtarırdı, `REVOKED`
    isə enum-da ümumiyyətlə yox idi — nəticədə istifadəçi Google-da razılığı
    geri alanda ekran vəziyyəti dəyişmirdi və problem yalnız növbəti yükləmə
    çökəndə bilinirdi.
    """
    audit = _Audit()
    controller, _context, repository, screen = _controller(audit, monkeypatch)
    repository.connection = _Connection(status="REVOKED")

    controller.refresh(screen)

    shown = screen.active[-1]
    assert shown["status_text"] == "İcazə ləğv edilib"
    assert shown["status_text"] != "Aktiv"
    assert shown["tone"] == "danger"
    # Hesabın adı GÖRÜNMƏLİDİR: «Qoşulmayıb» yazsaydıq, administrator hansı
    # hesabın icazəsinin ləğv olunduğunu bilməzdi.
    assert shown["account"] == "mağaza@şirkət.az"


def test_quota_exceeded_connection_is_also_shown_with_its_real_state(
    monkeypatch: Any,
) -> None:
    """Eyni boşluq `QUOTA_EXCEEDED`-də də vardı — «Qoşulmayıb» səbəbi gizlədirdi."""
    audit = _Audit()
    controller, _context, repository, screen = _controller(audit, monkeypatch)
    repository.connection = _Connection(status="QUOTA_EXCEEDED")

    controller.refresh(screen)

    assert screen.active[-1]["status_text"] == "Yer qalmayıb"
    assert screen.active[-1]["tone"] == "warning"


def test_archived_only_history_still_reads_as_not_connected(monkeypatch: Any) -> None:
    """Yalnız arxiv sətri qalıbsa cari hesab YOXDUR — mətn bunu açıq deyir."""
    audit = _Audit()
    controller, _context, repository, screen = _controller(audit, monkeypatch)
    repository.connection = _Connection(status="ARCHIVED")

    controller.refresh(screen)

    assert screen.active[-1]["status_text"] == "Qoşulmayıb"
    assert screen.active[-1]["account"] is None


# --------------------------------------------------------------------------- #
# 2. `REJECTED` → yenidən növbəyə
# --------------------------------------------------------------------------- #


@pytest.fixture
def queue(tmp_path: Path) -> Any:
    q = EvidenceUploadQueue(tmp_path / "uploads.db", spool_dir=tmp_path / "spool")
    yield q
    q.close()


def _enqueue(queue: EvidenceUploadQueue) -> str:
    return queue.enqueue(
        tenant_id=str(TENANT),
        owner_type=UploadOwnerType.FINE,
        owner_id=str(FINE),
        store_id=STORE,  # type: ignore[arg-type]
        filename="sübut.jpg",
        content=b"\xff\xd8\xffbinary-image",
        taken_at=MOMENT,
        now=MOMENT,
    )


def test_rejected_entry_can_be_returned_to_the_queue(queue: EvidenceUploadQueue) -> None:
    """Root həddi qaldırdıqda sübut şəkli əbədi əlçatmaz qalmamalıdır."""
    entry_id = _enqueue(queue)
    queue.mark_rejected(entry_id, "Fayl həddi aşır", now=MOMENT)
    assert queue.get(entry_id).status is UploadStatus.REJECTED

    assert queue.requeue_rejected(entry_id, now=MOMENT) is True

    entry = queue.get(entry_id)
    assert entry.status is UploadStatus.PENDING
    assert entry.last_error is None, "Köhnə səbəb yeni cəhdə yapışıb qalmamalıdır"
    assert [item.id for item in queue.pending(now=MOMENT)] == [entry_id]


def test_requeue_is_limited_to_rejected_rows(queue: EvidenceUploadQueue) -> None:
    """`UPLOADED` sətri geri qaytarmaq eyni şəkli İKİNCİ dəfə yükləyərdi."""
    entry_id = _enqueue(queue)

    assert queue.requeue_rejected(entry_id, now=MOMENT) is False
    assert queue.get(entry_id).status is UploadStatus.PENDING
    assert queue.requeue_rejected("belə-element-yoxdur", now=MOMENT) is False


def test_requeue_refuses_when_the_spool_file_is_gone(queue: EvidenceUploadQueue) -> None:
    """Fayl yoxdursa `PENDING` etmək ƏBƏDİ backoff dövrəsi yaradardı."""
    entry_id = _enqueue(queue)
    queue.mark_rejected(entry_id, "Fayl həddi aşır", now=MOMENT)
    Path(queue.get(entry_id).spool_path).unlink()

    assert queue.requeue_rejected(entry_id, now=MOMENT) is False
    assert queue.get(entry_id).status is UploadStatus.REJECTED


class _RejectingProvider:
    """Hər yükləməni validasiya xətası ilə rədd edən provider."""

    def upload(self, *_: Any, **__: Any) -> Any:
        # `**__`: işçi sahib tipini AÇAR SÖZ ilə ötürür (SEC-018) — real
        # provider onu qəbul edir, bu sahtə isə arqumentlərə baxmır.
        raise EvidenceValidationError(
            "Fayl həddi aşır",
            user_message="Şəkil çox böyükdür.",
        )


class _Factory:
    def __init__(self, provider: Any) -> None:
        self._provider = provider

    def active(self) -> Any:
        return self._provider


def test_requeued_entry_is_validated_again_and_does_not_loop(
    queue: EvidenceUploadQueue,
) -> None:
    """Bir düymə = BİR əlavə cəhd. Hədd hələ kiçikdirsə element yenə çıxır."""
    entry_id = _enqueue(queue)
    queue.mark_rejected(entry_id, "Fayl həddi aşır", now=MOMENT)
    queue.requeue_rejected(entry_id, now=MOMENT)

    worker = EvidenceUploadWorker(queue=queue, provider_factory=_Factory(_RejectingProvider()))
    report = worker.run_once(now=MOMENT + timedelta(seconds=1))

    assert report.rejected == 1
    assert queue.get(entry_id).status is UploadStatus.REJECTED
    # İkinci dövrə elementi ÖZ-ÖZÜNƏ geri qaytarmır — sonsuz dövrə yoxdur.
    assert worker.run_once(now=MOMENT + timedelta(seconds=2)).attempted == 0


# --------------------------------------------------------------------------- #
# 3. "Gecikib" həddi ROOT limitindən
# --------------------------------------------------------------------------- #


class _Limits:
    def __init__(self, value: int | None = None, *, failure: Exception | None = None) -> None:
        self.value = value
        self.failure = failure

    def get_int(self, tenant_id: Any, key: str, default: int) -> int:
        del tenant_id, key
        if self.failure is not None:
            raise self.failure
        return self.value if self.value is not None else default


class _LimitSession:
    def __init__(self, limits: _Limits) -> None:
        self.limits = limits
        self.tenant_id = TENANT


@pytest.mark.parametrize(
    ("timeout", "expected"),
    [
        (45, 22),  # spesifikasiyadakı defolt — köhnə sabitlə eyni nəticə
        (20, 10),  # Root endirdi → xəbərdarlıq da irəli sürüşür
        (90, 45),  # Root qaldırdı → erkən xəbərdarlıq səs-küyə çevrilmir
        (1, 1),  # sıfır hədd HƏR sətri "gecikmiş" göstərərdi
    ],
)
def test_late_threshold_follows_the_live_timeout(timeout: int, expected: int) -> None:
    session = _LimitSession(_Limits(timeout))
    assert late_threshold_minutes(session) == expected  # type: ignore[arg-type]


def test_default_limit_reproduces_the_documented_constant() -> None:
    """Sabitin şərhi "45-in yarısı" deyir — defolt dəyişsə test bunu tutur."""
    default = int(DEFAULT_LIMITS[SystemLimitKey.VERIFICATION_TIMEOUT_MINUTES])
    session = _LimitSession(_Limits(None))

    assert late_threshold_minutes(session) == default // 2  # type: ignore[arg-type]
    assert default // 2 == LATE_QUEUE_MINUTES


def test_unreadable_limit_falls_back_instead_of_disabling_the_warning() -> None:
    """Limit oxunmadıqda növbə "hər şey qaydasında" kimi görünməməlidir."""
    session = _LimitSession(_Limits(failure=RuntimeError("baza əlçatmazdır")))

    assert late_threshold_minutes(session) == LATE_QUEUE_MINUTES  # type: ignore[arg-type]
