"""`UsersEmployeeDocumentController` yazı yolu (`controllers/employee_documents.py`, ARCH-04).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ
──────────────────────────────────────────────────────────────────────────────
Kontroller `pyproject.toml`-un `omit = ["*/presentation/*"]` istisnası
SİLİNƏNDƏN sonra 0% örtüklü çıxdı (dövrə 2/3 audit, ARCH-04) — `tests/`
daxilində adı belə çəkilmirdi. Fayl işçinin ŞƏXSİ/HÜQUQİ sənədlərini (sanitar
kitabça, müqavilə və s.) yazır — bloklayıcı sənədin vaxtı bitəndə növbə
təyinatına təsir edir (bax `document_compliance.py`).

`EmployeeDocumentUseCase`-in ÖZÜ (guard, hesablama) `test_employee_documents.py`-də
ölçülür. Burada YALNIZ kontrollerin ÖZ məsuliyyəti: (a) `commit()`-in doğru
sırada çağırılması, (b) rədd edilmiş yazının geri qaytarılması, (c) yazıdan
sonra dialoqun cədvəlinin YENİDƏN doldurulması, (d) sənəd sətri YARANDIQDAN
SONRA fayl yükləməsinin uğursuz olduğu "A variantı" halı (modul başlığı),
(e) boş/xəta hallarında ekranın göstərdiyi.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any, ClassVar

import pytest

from src.domain.entities.employee_document import EmployeeDocument
from src.domain.value_objects.identifiers import (
    EmployeeDocumentId,
    TenantId,
    new_employee_document_id,
)
from src.infrastructure.storage.upload_queue import UploadOwnerType
from src.presentation.background_task import InlineExecutor
from src.presentation.controllers import screen_data as screen_data_module
from src.presentation.controllers.employee_documents import UsersEmployeeDocumentController
from src.shared.exceptions import KompasOSError

pytestmark = pytest.mark.unit

TENANT: Any = TenantId(uuid.uuid4())
EMPLOYEE = uuid.uuid4()
NOW = datetime(2026, 8, 8, 9, 0, tzinfo=UTC)


def _make_document(
    *, is_active: bool = True, is_blocking: bool = True, expiry: date | None = None
) -> EmployeeDocument:
    document = EmployeeDocument(
        document_id=new_employee_document_id(),
        tenant_id=TENANT,
        employee_id=EMPLOYEE,  # type: ignore[arg-type]
        doc_type="SANITAR_KITABCA",
        doc_number="AB-123",
        file_ref=None,
        expiry_date=expiry,
        is_blocking=is_blocking,
        uploaded_by=None,
        created_at=NOW,
        updated_at=NOW,
    )
    if not is_active:
        document.deactivate(reason="test üçün", deactivated_by=EMPLOYEE, now=NOW)  # type: ignore[arg-type]
    return document


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _Screen:
    def __init__(self) -> None:
        self.errors: list[tuple[str, str]] = []

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


class _Dialog:
    def __init__(self) -> None:
        self.set_documents_calls: list[list[dict[str, str]]] = []
        self.cleared = False

    def set_documents(self, rows: list[dict[str, str]]) -> None:
        self.set_documents_calls.append(rows)

    def clear_form(self) -> None:
        self.cleared = True


class _EmployeeDocuments:
    def __init__(
        self, *, failure: Exception | None = None, existing: list[Any] | None = None
    ) -> None:
        self.failure = failure
        self.existing = existing or []
        self.created: list[dict[str, Any]] = []
        self.deactivated: list[dict[str, Any]] = []

    def list_for_employee(self, *, tenant_id: Any, actor: Any, employee_id: Any) -> list[Any]:
        if self.failure is not None:
            raise self.failure
        return self.existing

    def create_document(self, *, tenant_id: Any, actor: Any, employee_id: Any, draft: Any) -> Any:
        if self.failure is not None:
            raise self.failure
        document = _make_document()
        self.created.append({"employee_id": employee_id, "draft": draft, "document": document})
        return document

    def deactivate_document(
        self, *, tenant_id: Any, actor: Any, document_id: Any, reason: str
    ) -> None:
        if self.failure is not None:
            raise self.failure
        self.deactivated.append({"document_id": document_id, "reason": reason})


class _Employees:
    def __init__(self, *, store_id: Any = "store-1", known: bool = True) -> None:
        self._store_id = store_id
        self._known = known

    def get(self, employee_id: Any) -> Any:
        if not self._known:
            return None
        return type("_Employee", (), {"store_id": self._store_id})()


class _Row(dict):
    pass


class _Connection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def execute(self, _sql: str, _params: Any) -> _Connection:
        return self

    def fetchall(self) -> list[_Row]:
        return [_Row(r) for r in self._rows]


class _Uow:
    def __init__(self, *, employees: _Employees, rows: list[dict[str, Any]]) -> None:
        self.employees = employees
        self.connection = _Connection(rows)


class _Session:
    def __init__(
        self, *, docs: _EmployeeDocuments, employees: _Employees, rows: list[dict[str, Any]]
    ) -> None:
        self.tenant_id = TENANT
        self.employee_documents = docs
        self.uow = _Uow(employees=employees, rows=rows)
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Queue:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[dict[str, Any]] = []

    def enqueue(self, **kwargs: Any) -> str:
        if self.failure is not None:
            raise self.failure
        self.calls.append(kwargs)
        return "entry-1"


class _Context:
    def __init__(
        self,
        *,
        docs: _EmployeeDocuments,
        employees: _Employees,
        rows: list[dict[str, Any]] | None = None,
        queue: _Queue | None = None,
    ) -> None:
        self._docs = docs
        self._employees = employees
        self._rows = (
            rows
            if rows is not None
            else [{"id": EMPLOYEE, "first_name": "Aysel", "last_name": "Quliyeva"}]
        )
        self.sessions: list[_Session] = []
        self.tenant_id = TENANT
        self._queue = queue or _Queue()
        self.upload_runs = 0

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(docs=self._docs, employees=self._employees, rows=self._rows)
        self.sessions.append(created)
        yield created

    def evidence_queue(self) -> _Queue:
        return self._queue

    def run_evidence_uploads(self) -> int:
        self.upload_runs += 1
        return 0


class _Actor:
    id = uuid.uuid4()


class _Binder:
    populated: ClassVar[list[str]] = []

    def __init__(self, context: Any, actor: Any) -> None:
        pass

    def populate(self, key: str, screen: Any) -> None:
        _Binder.populated.append(key)


@pytest.fixture(autouse=True)
def _binder(monkeypatch: pytest.MonkeyPatch) -> None:
    _Binder.populated = []
    monkeypatch.setattr(screen_data_module, "ScreenDataBinder", _Binder)


def _controller(context: _Context) -> UsersEmployeeDocumentController:
    # `InlineExecutor`: bu testlər MƏNTİQİ ölçür, sapı yox — nəticə dərhal,
    # hadisə dövrü gözləmədən qayıdır (bax `background_task.py`).
    return UsersEmployeeDocumentController(  # type: ignore[arg-type]
        context, _Actor(), executor=InlineExecutor()
    )


# --------------------------------------------------------------------------- #
# `_load` (`_open_dialog`/`_refresh_dialog`-un oxu nüvəsi)
# --------------------------------------------------------------------------- #


def test_load_reports_a_missing_employee_and_commits_nothing() -> None:
    context = _Context(docs=_EmployeeDocuments(), employees=_Employees(), rows=[])
    screen = _Screen()

    employee_id, rows = _controller(context)._load(screen, "Naməlum")

    assert employee_id is None
    assert rows == []
    assert screen.errors == [
        ("İşçi tapılmadı", "Bu işçi artıq siyahıda deyil. Səhifəni yeniləyin.")
    ]
    assert context.sessions[0].committed is False


def test_load_converts_documents_and_commits() -> None:
    active_ok = _make_document(is_blocking=True, expiry=date(2030, 1, 1))
    inactive = _make_document(is_active=False)
    docs = _EmployeeDocuments(existing=[active_ok, inactive])
    context = _Context(docs=docs, employees=_Employees())
    screen = _Screen()

    employee_id, rows = _controller(context)._load(screen, "Aysel Quliyeva")

    assert employee_id == EMPLOYEE
    assert screen.errors == []
    assert context.sessions[0].committed is True
    assert [r["status"] for r in rows] == ["Aktiv", "Deaktiv"]


def test_load_surfaces_a_domain_error() -> None:
    denial = KompasOSError("no permission", user_message="Sənədlərə baxmaq icazəniz yoxdur.")
    context = _Context(docs=_EmployeeDocuments(failure=denial), employees=_Employees())
    screen = _Screen()

    employee_id, rows = _controller(context)._load(screen, "Aysel Quliyeva")

    assert employee_id is None
    assert rows == []
    assert screen.errors == [("Sənədlər açıla bilmədi", "Sənədlərə baxmaq icazəniz yoxdur.")]


def test_load_survives_an_unexpected_failure() -> None:
    context = _Context(
        docs=_EmployeeDocuments(failure=RuntimeError("baza əlçatmazdır")), employees=_Employees()
    )
    screen = _Screen()

    employee_id, _rows = _controller(context)._load(screen, "Aysel Quliyeva")

    assert employee_id is None
    assert screen.errors == [("Sənədlər açıla bilmədi", "Məlumat yüklənmədi. Yenidən cəhd edin.")]


# --------------------------------------------------------------------------- #
# `_add` — yeni sənəd yazı yolu
# --------------------------------------------------------------------------- #


def test_add_without_a_file_commits_and_refreshes_without_touching_the_queue() -> None:
    """ "A variantı": fayl seçilməyibsə sənəd YENƏ DƏ yaranır, növbəyə TOXUNULMUR."""
    docs = _EmployeeDocuments()
    queue = _Queue()
    context = _Context(docs=docs, employees=_Employees(), queue=queue)
    screen = _Screen()
    dialog = _Dialog()

    _controller(context)._add(
        screen,
        dialog,
        employee_id=EMPLOYEE,
        full_name="Aysel Quliyeva",
        doc_type="SANITAR_KITABCA",
        doc_number="",
        expiry_text="",
        blocking=True,
        file_path="",
    )

    assert screen.errors == []
    assert context.sessions[0].committed is True
    assert docs.created, "sənəd sətri yaranmalıdır"
    assert queue.calls == [], "fayl seçilməyibsə növbəyə YAZILMAMALIDIR"
    assert dialog.cleared is True
    assert len(dialog.set_documents_calls) == 1, "cədvəl YENİDƏN doldurulmalıdır"


def test_add_with_a_file_enqueues_it_after_the_document_row_exists(tmp_path: Any) -> None:
    photo = tmp_path / "kitabca.jpg"
    photo.write_bytes(b"skan-icerigi")
    docs = _EmployeeDocuments()
    queue = _Queue()
    context = _Context(docs=docs, employees=_Employees(store_id="store-9"), queue=queue)
    screen = _Screen()

    _controller(context)._add(
        screen,
        _Dialog(),
        employee_id=EMPLOYEE,
        full_name="Aysel Quliyeva",
        doc_type="SANITAR_KITABCA",
        doc_number="",
        expiry_text="",
        blocking=True,
        file_path=str(photo),
    )

    assert screen.errors == []
    assert len(queue.calls) == 1
    call = queue.calls[0]
    assert call["owner_type"] is UploadOwnerType.EMPLOYEE_DOCUMENT
    assert call["owner_id"] == str(docs.created[0]["document"].id)
    assert call["store_id"] == "store-9"
    assert call["content"] == b"skan-icerigi"
    assert context.upload_runs == 1, "yüklənmə DƏRHAL bir dəfə sınanmalıdır"


def test_add_rejects_a_malformed_expiry_date_before_opening_a_session() -> None:
    context = _Context(docs=_EmployeeDocuments(), employees=_Employees())
    screen = _Screen()

    _controller(context)._add(
        screen,
        _Dialog(),
        employee_id=EMPLOYEE,
        full_name="Aysel Quliyeva",
        doc_type="SANITAR_KITABCA",
        doc_number="",
        expiry_text="31-12-2026",  # ISO DEYİL
        blocking=True,
        file_path="",
    )

    assert context.sessions == [], "yanlış tarix sessiya AÇMAMALIDIR"
    assert screen.errors == [
        (
            "Tarix yanlışdır",
            "Bitmə tarixini YYYY-AA-GG formatında yazın (məs. 2026-12-31).",
        )
    ]


def test_a_rejected_add_does_not_commit_or_refresh() -> None:
    denial = KompasOSError(
        "hierarchy denied", user_message="Bu işçiyə sənəd əlavə edə bilməzsiniz."
    )
    docs = _EmployeeDocuments(failure=denial)
    context = _Context(docs=docs, employees=_Employees())
    screen = _Screen()
    dialog = _Dialog()

    _controller(context)._add(
        screen,
        dialog,
        employee_id=EMPLOYEE,
        full_name="Aysel Quliyeva",
        doc_type="SANITAR_KITABCA",
        doc_number="",
        expiry_text="",
        blocking=True,
        file_path="",
    )

    assert context.sessions[0].committed is False
    assert screen.errors == [("Sənəd əlavə edilmədi", "Bu işçiyə sənəd əlavə edə bilməzsiniz.")]
    assert dialog.cleared is False
    assert dialog.set_documents_calls == []


def test_an_unexpected_add_failure_shows_a_generic_message() -> None:
    docs = _EmployeeDocuments(failure=RuntimeError("bağlantı kəsildi"))
    context = _Context(docs=docs, employees=_Employees())
    screen = _Screen()

    _controller(context)._add(
        screen,
        _Dialog(),
        employee_id=EMPLOYEE,
        full_name="Aysel Quliyeva",
        doc_type="SANITAR_KITABCA",
        doc_number="",
        expiry_text="",
        blocking=True,
        file_path="",
    )

    assert context.sessions[0].committed is False
    assert screen.errors == [("Sənəd əlavə edilmədi", "Dəyişiklik saxlanmadı. Yenidən cəhd edin.")]


# --------------------------------------------------------------------------- #
# `_enqueue_file` — sənəd sətri ARTIQ VAR, fayl YOX
# --------------------------------------------------------------------------- #


def test_enqueue_file_warns_but_keeps_the_document_row_when_the_employee_has_no_store(
    tmp_path: Any,
) -> None:
    photo = tmp_path / "s.jpg"
    photo.write_bytes(b"x")
    context = _Context(docs=_EmployeeDocuments(), employees=_Employees())
    screen = _Screen()

    _controller(context)._enqueue_file(
        screen, document_id=EmployeeDocumentId(uuid.uuid4()), store_id=None, file_path=str(photo)
    )

    assert "Sənəd qeydi YARADILDI" in screen.errors[0][1]
    assert context.upload_runs == 0


def test_enqueue_file_reports_an_unreadable_file() -> None:
    context = _Context(docs=_EmployeeDocuments(), employees=_Employees())
    screen = _Screen()

    _controller(context)._enqueue_file(
        screen,
        document_id=EmployeeDocumentId(uuid.uuid4()),
        store_id="store-1",
        file_path="C:/yolu-yoxdur/heç-vaxt-mövcud-olmayan.jpg",
    )

    assert screen.errors[0][0] == "Fayl oxunmadı"
    assert "Sənəd qeydi YARADILDI" in screen.errors[0][1]


def test_enqueue_file_reports_an_unexpected_queue_failure_without_crashing(tmp_path: Any) -> None:
    photo = tmp_path / "s.jpg"
    photo.write_bytes(b"x")
    context = _Context(
        docs=_EmployeeDocuments(),
        employees=_Employees(),
        queue=_Queue(failure=RuntimeError("disk doludur")),
    )
    screen = _Screen()

    _controller(context)._enqueue_file(
        screen,
        document_id=EmployeeDocumentId(uuid.uuid4()),
        store_id="store-1",
        file_path=str(photo),
    )

    assert screen.errors == [
        ("Fayl yüklənmədi", "Fayl növbəyə yerləşdirilmədi. Sənəd qeydi YARADILDI.")
    ]
    assert context.upload_runs == 0


def test_enqueue_file_reports_a_domain_failure_from_the_queue(tmp_path: Any) -> None:
    photo = tmp_path / "s.jpg"
    photo.write_bytes(b"x")
    denial = KompasOSError("quota", user_message="Yükləmə limiti aşılıb.")
    context = _Context(
        docs=_EmployeeDocuments(), employees=_Employees(), queue=_Queue(failure=denial)
    )
    screen = _Screen()

    _controller(context)._enqueue_file(
        screen,
        document_id=EmployeeDocumentId(uuid.uuid4()),
        store_id="store-1",
        file_path=str(photo),
    )

    assert screen.errors == [("Fayl yüklənmədi", "Yükləmə limiti aşılıb.")]
    assert context.upload_runs == 0


# --------------------------------------------------------------------------- #
# `_deactivate` — Qt daxil olma qutusu ilə
# --------------------------------------------------------------------------- #


def _patch_input_dialog(monkeypatch: pytest.MonkeyPatch, *, accepted: bool, text: str) -> None:
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: (text, accepted))
    )


def test_deactivate_does_nothing_when_the_admin_cancels(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_input_dialog(monkeypatch, accepted=False, text="")
    context = _Context(docs=_EmployeeDocuments(), employees=_Employees())

    _controller(context)._deactivate(
        _Screen(), _Dialog(), full_name="Aysel Quliyeva", document_id_text=str(uuid.uuid4())
    )

    assert context.sessions == []


def test_deactivate_does_nothing_when_the_reason_is_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    """Boş səbəb qəbul edilmiş sayılsa belə — audit sətirsiz qala bilməz."""
    _patch_input_dialog(monkeypatch, accepted=True, text="   ")
    context = _Context(docs=_EmployeeDocuments(), employees=_Employees())

    _controller(context)._deactivate(
        _Screen(), _Dialog(), full_name="Aysel Quliyeva", document_id_text=str(uuid.uuid4())
    )

    assert context.sessions == []


def test_deactivate_shows_an_error_on_a_malformed_document_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QA-13 (dövrə 3 audit) DÜZƏLDİ: yanlış ID artıq EKRANA görünən xəta verir.

    Əvvəl bu hal SÜKUTLA loga düşürdü, ekranda heç nə göstərilmirdi — admin
    "Deaktiv Et" basır, ekran SUSURDU (nə xəta, nə təsdiq). Bu, NORMAL UI
    axınında baş VERMƏMƏLİDİR (`document_id_text` dialoqun öz siyahısından
    gəlir), amma baş versə (köhnəlmiş sətir, gələcək bir UI uyğunsuzluğu),
    admin İNDİ SƏBƏBİ GÖRÜR. Test ARTIQ DÜZƏLMİŞ davranışı sənədləşdirir
    (əvvəlki adı "silently gives up" idi — artıq doğru deyil).
    """
    _patch_input_dialog(monkeypatch, accepted=True, text="silinmə səbəbi")
    context = _Context(docs=_EmployeeDocuments(), employees=_Employees())
    screen = _Screen()

    _controller(context)._deactivate(
        screen, _Dialog(), full_name="Aysel Quliyeva", document_id_text="uuid-deyil"
    )

    assert context.sessions == []  # sessiya BELƏ AÇILMIR — ID sessiyadan ƏVVƏL yoxlanılır
    assert screen.errors == [
        ("Sənəd deaktiv edilmədi", "Sənəd identifikatoru düzgün deyil. Səhifəni yeniləyin.")
    ]


def test_an_unexpected_deactivate_failure_shows_a_generic_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_input_dialog(monkeypatch, accepted=True, text="səbəb")
    context = _Context(
        docs=_EmployeeDocuments(failure=RuntimeError("bağlantı kəsildi")), employees=_Employees()
    )
    screen = _Screen()

    _controller(context)._deactivate(
        screen, _Dialog(), full_name="Aysel Quliyeva", document_id_text=str(uuid.uuid4())
    )

    assert context.sessions[-1].committed is False
    assert screen.errors == [
        ("Sənəd deaktiv edilmədi", "Dəyişiklik saxlanmadı. Yenidən cəhd edin.")
    ]


def test_a_successful_deactivate_commits_and_refreshes(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_input_dialog(monkeypatch, accepted=True, text="işdən çıxıb")
    docs = _EmployeeDocuments()
    context = _Context(docs=docs, employees=_Employees())
    screen = _Screen()
    dialog = _Dialog()
    document_id = uuid.uuid4()

    _controller(context)._deactivate(
        screen, dialog, full_name="Aysel Quliyeva", document_id_text=str(document_id)
    )

    assert screen.errors == []
    assert context.sessions[-1].committed is True
    assert docs.deactivated[0]["reason"] == "işdən çıxıb"
    assert len(dialog.set_documents_calls) == 1


def test_a_rejected_deactivate_does_not_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_input_dialog(monkeypatch, accepted=True, text="səbəb")
    denial = KompasOSError("hierarchy denied", user_message="Bu sənədi deaktiv edə bilməzsiniz.")
    context = _Context(docs=_EmployeeDocuments(failure=denial), employees=_Employees())
    screen = _Screen()
    dialog = _Dialog()

    _controller(context)._deactivate(
        screen, dialog, full_name="Aysel Quliyeva", document_id_text=str(uuid.uuid4())
    )

    assert context.sessions[-1].committed is False
    assert screen.errors == [("Sənəd deaktiv edilmədi", "Bu sənədi deaktiv edə bilməzsiniz.")]
    assert dialog.set_documents_calls == []


# --------------------------------------------------------------------------- #
# `_to_row` — status törəməsi
# --------------------------------------------------------------------------- #


def test_to_row_marks_an_inactive_document_regardless_of_expiry() -> None:
    from src.presentation.controllers.employee_documents import _to_row

    document = _make_document(is_active=False, is_blocking=True, expiry=date(2020, 1, 1))
    assert _to_row(document)["status"] == "Deaktiv"


def test_to_row_marks_an_active_blocking_expired_document_as_bitib() -> None:
    from src.presentation.controllers.employee_documents import _to_row

    document = _make_document(is_active=True, is_blocking=True, expiry=date(2020, 1, 1))
    assert _to_row(document)["status"] == "Bitib"


def test_to_row_marks_an_active_non_blocking_document_as_active_even_when_expired() -> None:
    from src.presentation.controllers.employee_documents import _to_row

    document = _make_document(is_active=True, is_blocking=False, expiry=date(2020, 1, 1))
    assert _to_row(document)["status"] == "Aktiv"


# --------------------------------------------------------------------------- #
# `_on_action` — yönləndirmə
# --------------------------------------------------------------------------- #


def test_unrelated_actions_are_ignored() -> None:
    context = _Context(docs=_EmployeeDocuments(), employees=_Employees())
    controller = _controller(context)
    opened: list[str] = []
    controller._open_dialog = lambda screen, name: opened.append(name)  # type: ignore[method-assign]

    controller._on_action(_Screen(), "reset_pin", "Aysel Quliyeva")

    assert opened == []
    assert context.sessions == []


def test_the_matching_action_opens_the_dialog() -> None:
    context = _Context(docs=_EmployeeDocuments(), employees=_Employees())
    controller = _controller(context)
    opened: list[str] = []
    controller._open_dialog = lambda screen, name: opened.append(name)  # type: ignore[method-assign]

    controller._on_action(_Screen(), "employee_documents", "Aysel Quliyeva")

    assert opened == ["Aysel Quliyeva"]
