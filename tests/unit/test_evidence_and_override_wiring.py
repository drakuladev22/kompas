"""Sübut yükləməsi və manual vaxt düzəlişinin bağlantı testləri.

Hər iki axın ROOT Control Center limitini işlədir və məhz ona görə burada
yoxlanılır (bölmə 3, bənd 1):

    * `MAX_UPLOAD_SIZE_BYTES` → `DriveProviderFactory(max_upload_bytes=...)`
    * `DUAL_CONTROL_THRESHOLD_MINUTES` → `ManualTimeOverrideDialog`

Testlər Qt-siz və bazasız işləyir: kontrollerlər yalnız `ApplicationContext`
protokolunun kiçik bir hissəsinə toxunur, ona görə sahtə kontekst kifayətdir.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from src.infrastructure.storage.upload_queue import UploadOwnerType
from src.presentation.background_task import InlineExecutor
from src.presentation.controllers.camera_queue import _combine
from src.presentation.controllers.fine_entry import NO_STORES_MESSAGE, FineEntryController

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
STORE = uuid.uuid4()
WORKER = uuid.uuid4()
FINE_TYPE = uuid.uuid4()
CONNECTION_A = uuid.uuid4()


# --------------------------------------------------------------------------- #
# Vaxt birləşdirmə
# --------------------------------------------------------------------------- #


def test_combine_keeps_the_reference_day() -> None:
    reference = datetime(2026, 8, 10, 14, 10, tzinfo=UTC)
    combined = _combine(reference, "13:40")

    assert combined is not None
    assert combined.astimezone().hour == 13
    assert combined.astimezone().minute == 40


def test_combine_does_not_roll_to_the_next_day_for_earlier_times() -> None:
    """Düzəliş adətən ƏVVƏLƏ olur — bunu gecə yarısı hadisəsi saymaq olmaz."""
    reference = datetime(2026, 8, 10, 14, 10, tzinfo=UTC)
    combined = _combine(reference, "09:05")

    assert combined is not None
    assert combined.astimezone().date() == reference.astimezone().date()


@pytest.mark.parametrize("text", ["", "abc", "25:00", "12:75", "12", "12:30:45"])
def test_combine_rejects_bad_input(text: str) -> None:
    assert _combine(datetime(2026, 8, 10, 14, 10, tzinfo=UTC), text) is None


# --------------------------------------------------------------------------- #
# Cərimə formasının yazı yolu
# --------------------------------------------------------------------------- #


class _Screen:
    """`show_error` çağırışlarını yığan minimal ekran əvəzi.

    `clear_photo`/`set_success_message` DEEP-GAP U1-lə, `clear_employee`
    isə DEEP-GAP OP-6 ilə əlavə olundu — `FineEntryController._issue`-un
    UĞUR yolu bunları çağırır (bax onun başlığı), sahtə onlarsız
    `AttributeError` atardı.
    """

    def __init__(self) -> None:
        self.errors: list[tuple[str, str]] = []
        self.photo_cleared = False
        self.employee_cleared = False
        self.success_message = ""

    def show_error(self, *, title: str, message: str, **_: Any) -> None:
        self.errors.append((title, message))

    def clear_photo(self) -> None:
        self.photo_cleared = True

    def clear_employee(self) -> None:
        self.employee_cleared = True

    def set_success_message(self, message: str) -> None:
        self.success_message = message


class _Queue:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        #: Növbənin ön-yoxlaması (`validate_evidence_payload`) yararsız faylı
        #: rədd edəndə atılan istisna — sahtədə də eyni davranış modellənir.
        self.failure = failure

    def enqueue(self, **kwargs: Any) -> str:
        if self.failure is not None:
            raise self.failure
        self.calls.append(kwargs)
        return f"entry-{len(self.calls)}"


class _Fines:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.issued: list[dict[str, Any]] = []
        self.pending: list[Any] = []
        self.failure = failure

    def issue(self, **kwargs: Any) -> Any:
        if self.failure is not None:
            raise self.failure
        self.issued.append(kwargs)
        return object()

    def mark_evidence_pending(self, fine_id: Any) -> None:
        self.pending.append(fine_id)


class _Session:
    def __init__(self, fines: _Fines) -> None:
        self.tenant_id = TENANT
        self.manual_fines = fines
        self.committed = False
        self.uow = type("_Uow", (), {"fines": fines})()

    def commit(self) -> None:
        self.committed = True

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _Context:
    def __init__(self, fines: _Fines) -> None:
        self.tenant_id = TENANT
        self.queue = _Queue()
        self.sessions: list[_Session] = []
        self.upload_runs = 0
        self._fines = fines

    def session(self, **_: Any) -> _Session:
        created = _Session(self._fines)
        self.sessions.append(created)
        return created

    def evidence_queue(self) -> _Queue:
        return self.queue

    def run_evidence_uploads(self) -> int:
        self.upload_runs += 1
        return 0


class _Actor:
    """Kontrollerin toxunduğu YEGANƏ sahə — sessiya `user_id` üçün."""

    id = uuid.uuid4()


def _controller(context: Any) -> FineEntryController:
    # `InlineExecutor`: bu testlər MƏNTİQİ ölçür, sapı yox — nəticə dərhal,
    # hadisə dövrü gözləmədən qayıdır (bax `background_task.py`).
    controller = FineEntryController(  # type: ignore[arg-type]
        context, actor=_Actor(), executor=InlineExecutor()
    )
    controller._fine_types = {"Gecikmə": FINE_TYPE}
    controller._stores = {"Bellona 28 May": STORE}
    controller._employees = {"Aysel Quliyeva": WORKER}
    return controller


def _payload(photo: Any) -> dict[str, str]:
    return {
        "fine_type": "Gecikmə",
        "store": "Bellona 28 May",
        "employee": "Aysel Quliyeva",
        "photo_path": str(photo),
    }


def test_evidence_is_spooled_before_the_fine_row_is_written(tmp_path: Any) -> None:
    """Sıra pozulsa "sübutu olmayan cərimə" yarana bilər (bölmə 4 qadağası)."""
    photo = tmp_path / "sekil.jpg"
    photo.write_bytes(b"binary-image")

    fines = _Fines()
    context = _Context(fines)
    screen = _Screen()
    _controller(context)._on_submitted(screen, _payload(photo))

    assert screen.errors == []
    assert context.queue.calls, "Şəkil növbəyə düşməlidir"
    assert context.queue.calls[0]["content"] == b"binary-image"
    # Cəriməyə gedən sübut istinadı məhz növbə açarıdır.
    assert fines.issued[0]["evidence_reference"] == "entry-1"
    # Növbə `owner_id`-ni bilir, cərimə də EYNİ id ilə yazılır (#17: `fine_id`
    # → `owner_type`/`owner_id` ümumiləşdirilib, bax `upload_queue.py` başlığı).
    from src.infrastructure.storage.upload_queue import UploadOwnerType

    assert context.queue.calls[0]["owner_type"] is UploadOwnerType.FINE
    assert context.queue.calls[0]["owner_id"] == str(fines.issued[0]["fine_id"])
    assert fines.pending == [fines.issued[0]["fine_id"]]
    # `sessions[0]` — cərimə tranzaksiyası. Sonrakı sessiya siyahının
    # yenilənməsinə aiddir və commit-ə ehtiyacı yoxdur.
    assert context.sessions[0].committed
    # DEEP-GAP U1 — foto TƏMİZLƏNMƏLİ, operator bir təsdiq mesajı almalıdır.
    assert screen.photo_cleared
    assert "Aysel Quliyeva" in screen.success_message


def test_upload_is_attempted_immediately_after_the_fine(tmp_path: Any) -> None:
    photo = tmp_path / "sekil.jpg"
    photo.write_bytes(b"x")

    context = _Context(_Fines())
    _controller(context)._on_submitted(_Screen(), _payload(photo))

    assert context.upload_runs == 1


def test_unknown_selection_never_reaches_the_use_case(tmp_path: Any) -> None:
    """Ad→ID xəritəsində olmayan seçim SÜKUTLA yanlış işçiyə yazılmamalıdır."""
    photo = tmp_path / "sekil.jpg"
    photo.write_bytes(b"x")

    fines = _Fines()
    context = _Context(fines)
    screen = _Screen()
    payload = _payload(photo) | {"employee": "Naməlum Şəxs"}
    _controller(context)._on_submitted(screen, payload)

    assert not fines.issued
    assert not context.queue.calls
    assert screen.errors and "seçilməlidir" in screen.errors[0][1]


def test_operator_without_stores_gets_the_reason(tmp_path: Any) -> None:
    photo = tmp_path / "sekil.jpg"
    photo.write_bytes(b"x")

    controller = _controller(_Context(_Fines()))
    controller._stores = {}
    screen = _Screen()
    controller._on_submitted(screen, _payload(photo))

    assert screen.errors == [("Cərimə yaradıla bilmədi", NO_STORES_MESSAGE)]


def test_missing_photo_file_is_reported_not_crashed() -> None:
    context = _Context(_Fines())
    screen = _Screen()
    _controller(context)._on_submitted(screen, _payload("C:/yoxdur/sekil.jpg"))

    assert not context.queue.calls
    assert screen.errors and screen.errors[0][0] == "Şəkil oxunmadı"


def test_use_case_failure_reports_the_domain_message(tmp_path: Any) -> None:
    from src.shared.exceptions import KompasOSError

    class _DeniedError(KompasOSError):
        user_message = "Bu mağazada cərimə yaza bilməzsiniz."

    photo = tmp_path / "sekil.jpg"
    photo.write_bytes(b"x")

    context = _Context(_Fines(failure=_DeniedError("scope")))
    screen = _Screen()
    _controller(context)._on_submitted(screen, _payload(photo))

    assert screen.errors == [("Cərimə yaradılmadı", "Bu mağazada cərimə yaza bilməzsiniz.")]
    assert not context.sessions[0].committed
    assert context.upload_runs == 0, "Cərimə yaranmayıbsa yükləmə də başlamamalıdır"


def test_rejected_photo_stops_the_flow_with_a_visible_reason(tmp_path: Any) -> None:
    """Yararsız şəkil növbənin ön-yoxlamasında kəsilir — SƏSSİZ deyil.

    Növbə `.exe`/böyük faylı artıq `enqueue()`-da rədd edir. Kontroller həmin
    istisnanı `KompasOSError` kimi tutur, yəni səbəb operatorun ekranına
    çıxır; cərimə isə sübutsuz yazılmır (bölmə 4 qadağası).
    """
    from src.infrastructure.storage.google_drive import EvidenceValidationError

    photo = tmp_path / "sekil.jpg"
    photo.write_bytes(b"MZ\x90\x00 icra fayli")

    fines = _Fines()
    context = _Context(fines)
    context.queue = _Queue(
        failure=EvidenceValidationError(
            "Fayl məzmunu şəkil deyil",
            user_message="Seçilmiş fayl şəkil deyil (JPEG, PNG və ya WEBP olmalıdır).",
        )
    )
    screen = _Screen()
    _controller(context)._on_submitted(screen, _payload(photo))

    assert screen.errors == [
        ("Cərimə yaradılmadı", "Seçilmiş fayl şəkil deyil (JPEG, PNG və ya WEBP olmalıdır).")
    ]
    assert not fines.issued, "sübutsuz cərimə yazıldı"
    assert context.upload_runs == 0


# --------------------------------------------------------------------------- #
# `MAX_UPLOAD_SIZE_BYTES` → Drive fabriki
# --------------------------------------------------------------------------- #


def _context_without_db() -> Any:
    """Bazaya toxunmayan `ApplicationContext` — yalnız fabrik yolu üçün."""
    from src.presentation.composition import ApplicationContext

    return ApplicationContext(
        database=object(),  # type: ignore[arg-type]
        tenant_id=TENANT,  # type: ignore[arg-type]
    )


def test_drive_factory_is_absent_without_oauth_credentials(monkeypatch: Any) -> None:
    """Google açarları yoxdursa Drive qatı QURULMUR — bu, xəta deyil.

    Bağlantısız quraşdırmada cərimələr yenə yaranır, şəkillər isə lokal
    növbədə gözləyir (bax `upload_queue` modul başlığı).
    """
    monkeypatch.delenv("KOMPASOS_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("KOMPASOS_GOOGLE_CLIENT_SECRET", raising=False)

    assert _context_without_db().drive_providers(max_upload_bytes=1024) is None


def test_drive_factory_carries_the_root_limit(monkeypatch: Any) -> None:
    """Hədd `system_limits`-dən gəlir, provider-in 5 MB defoltundan yox."""
    monkeypatch.setenv("KOMPASOS_GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("KOMPASOS_GOOGLE_CLIENT_SECRET", "secret")

    context = _context_without_db()
    # `_store_names` bazaya girir və orada uğursuz olur — kontekst bunu udur
    # və boş resolver qaytarır, ona görə fabrik yenə qurulur.
    factory = context.drive_providers(max_upload_bytes=777)

    assert factory is not None
    assert factory._max_upload_bytes == 777


def test_changing_the_limit_rebuilds_the_factory(monkeypatch: Any) -> None:
    """Root sürüşdürücünü tərpədəndə növbəti dövrə YENİ həddi tətbiq etməlidir."""
    monkeypatch.setenv("KOMPASOS_GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("KOMPASOS_GOOGLE_CLIENT_SECRET", "secret")

    context = _context_without_db()
    first = context.drive_providers(max_upload_bytes=1000)
    same = context.drive_providers(max_upload_bytes=1000)
    changed = context.drive_providers(max_upload_bytes=2000)

    assert same is first, "Dəyər dəyişməyibsə token yenidən alınmamalıdır"
    assert changed is not first
    assert changed._max_upload_bytes == 2000


def test_upload_run_reads_the_limit_from_the_session(monkeypatch: Any) -> None:
    """Zəncir bütövdür: `system_limits` → sessiya → fabrik → provider.

    Bu test məhz həlqəni yoxlayır. Fabrik `None` qaytarsa (OAuth açarları
    yoxdur) dövrə 0 ilə bitir — bu, gözlənilən davranışdır, xəta deyil.
    """
    from contextlib import contextmanager

    monkeypatch.setenv("KOMPASOS_GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("KOMPASOS_GOOGLE_CLIENT_SECRET", "secret")

    context = _context_without_db()
    seen: list[int] = []

    class _LimitSession:
        def max_upload_bytes(self) -> int:
            return 4242

    @contextmanager
    def _fake_session(**_: Any) -> Any:
        yield _LimitSession()

    monkeypatch.setattr(context, "session", _fake_session)
    monkeypatch.setattr(
        context,
        "drive_providers",
        lambda *, max_upload_bytes: seen.append(max_upload_bytes),
    )

    assert context.run_evidence_uploads() == 0
    assert seen == [4242], "Fabrikə ROOT limiti ötürülməlidir"


def test_upload_run_never_raises(monkeypatch: Any) -> None:
    """Fon işi interfeysi çökdürməməlidir."""
    context = _context_without_db()

    def _boom(**_: Any) -> Any:
        raise RuntimeError("baza əlçatmazdır")

    monkeypatch.setattr(context, "session", _boom)
    assert context.run_evidence_uploads() == 0


# --------------------------------------------------------------------------- #
# `_attach_evidence` — #17: `owner_type`-a görə sahib cədvəlin seçilməsi
# --------------------------------------------------------------------------- #


def test_attach_evidence_routes_a_fine_to_the_fines_repository(monkeypatch: Any) -> None:
    """Köçürmədən ƏVVƏLKİ tək-sahib davranış — `FINE` üçün DƏYİŞMİR."""
    from contextlib import contextmanager

    from src.domain.value_objects.storage import StorageReference

    context = _context_without_db()
    calls: list[Any] = []

    class _FinesRepo:
        def attach_drive_evidence(self, fine_id: Any, *, file_id: str, connection_id: Any) -> None:
            calls.append((fine_id, file_id, connection_id))

    class _Session:
        def __init__(self) -> None:
            self.uow = type("_Uow", (), {"fines": _FinesRepo()})()
            self.committed = False

        def commit(self) -> None:
            self.committed = True

    session = _Session()

    @contextmanager
    def _fake_session(**_: Any) -> Any:
        yield session

    monkeypatch.setattr(context, "session", _fake_session)
    fine_id = uuid.uuid4()
    reference = StorageReference.drive(file_id="drive-1", connection_id=CONNECTION_A)

    context._attach_evidence(UploadOwnerType.FINE.value, str(fine_id), reference)

    assert calls == [(fine_id, "drive-1", CONNECTION_A)]
    assert session.committed


def test_attach_evidence_routes_an_employee_document_to_the_document_use_case(
    monkeypatch: Any,
) -> None:
    """#17: YENİ qol — sənəd skanı `attach_uploaded_file`-a getməlidir."""
    from contextlib import contextmanager

    from src.domain.value_objects.storage import StorageReference

    context = _context_without_db()
    calls: list[dict[str, Any]] = []

    class _Documents:
        def attach_uploaded_file(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    class _Session:
        def __init__(self) -> None:
            self.tenant_id = TENANT
            self.employee_documents = _Documents()
            self.committed = False

        def commit(self) -> None:
            self.committed = True

    session = _Session()

    @contextmanager
    def _fake_session(**_: Any) -> Any:
        yield session

    monkeypatch.setattr(context, "session", _fake_session)
    document_id = uuid.uuid4()
    reference = StorageReference.drive(file_id="drive-2", connection_id=CONNECTION_A)

    context._attach_evidence(UploadOwnerType.EMPLOYEE_DOCUMENT.value, str(document_id), reference)

    assert len(calls) == 1
    assert calls[0]["document_id"] == document_id
    assert calls[0]["file_ref"] == str(reference)
    assert session.committed
