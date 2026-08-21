"""`UsersScreen`/`EmployeeDocumentDialog` ↔ `controllers/employee_documents.py` — REAL Qt e2e.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, ikinci beşlik)
──────────────────────────────────────────────────────────────────────────────
`controllers/employee_documents.py` `tests/` daxilində HEÇ YERDƏ adı
çəkilmirdi (3 yazı yolu: sənəd yaratma, fayl növbəyə yazma, deaktivasiya —
hər biri `.commit()` çağırır). Burada REAL `UsersScreen`-in "···" menyusu
(REAL `QAction.trigger()`), REAL `EmployeeDocumentDialog` və REAL "Deaktiv
Et" düyməsi işə salınır.

`EmployeeDocumentDialog.exec()` MODAL-dır — `AnnouncementComposeDialog` ilə
EYNİ trik: `exec()` REAL sahə doldurma + REAL düymə kliki ilə əvəz olunur ki,
test sapı bloklanmasın (bax `test_announcements_screen_e2e.py::_patched_exec`).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any

import pytest

from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()
EMPLOYEE_ID = uuid.uuid4()
STORE_ID = uuid.uuid4()
FULL_NAME = "Aygün Məmmədova"


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _click(widget: Any, text: str) -> None:
    from PySide6.QtWidgets import QPushButton

    button = next(b for b in widget.findChildren(QPushButton) if b.text() == text)
    button.click()


def _trigger_menu_action(screen: Any, label: str) -> None:
    """`UsersScreen`-in "···" menyusundakı REAL `QAction`-ı taparaq işə salır."""
    from PySide6.QtWidgets import QPushButton

    ellipsis = next(b for b in screen.findChildren(QPushButton) if b.text() == "···")
    menu = ellipsis.menu()
    action = next(a for a in menu.actions() if a.text() == label)
    action.trigger()


def _user_row(full_name: str = FULL_NAME) -> dict[str, str]:
    return {"full_name": full_name, "username": "aygun.m", "role": "Satıcı", "store": "Mərkəz"}


class _FakeDoc:
    def __init__(self, doc_id: Any) -> None:
        self.id = doc_id


class _FakeDocumentEntity:
    """`EmployeeDocument`-in yerini tutur — `_to_row()` bu atributları OXUYUR."""

    def __init__(
        self,
        *,
        document_id: Any = None,
        doc_type: str = "PASPORT",
        doc_number: str | None = "AA1234567",
        expiry_date: Any = None,
        is_active: bool = True,
        is_blocking: bool = False,
    ) -> None:
        self.id = document_id or uuid.uuid4()
        self.doc_type = doc_type
        self.doc_number = doc_number
        self.expiry_date = expiry_date
        self.is_active = is_active
        self.is_blocking = is_blocking

    def is_expired_on(self, _today: Any) -> bool:
        return False


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _Row(dict):
    pass


class _Connection:
    def __init__(self, employees: list[tuple[str, str, str]]) -> None:
        self._employees = employees

    def execute(self, _sql: str, _params: Any = None) -> _Connection:
        return self

    def fetchall(self) -> list[_Row]:
        return [
            _Row(id=eid, first_name=first, last_name=last) for eid, first, last in self._employees
        ]


class _Employee:
    def __init__(self, store_id: Any) -> None:
        self.store_id = store_id


class _EmployeesRepo:
    def __init__(self, store_id: Any) -> None:
        self._store_id = store_id

    def get(self, _employee_id: Any) -> _Employee:
        return _Employee(self._store_id)


class _Uow:
    def __init__(self, employees: list[tuple[str, str, str]], store_id: Any) -> None:
        self.connection = _Connection(employees)
        self.employees = _EmployeesRepo(store_id)


class _EmployeeDocuments:
    def __init__(self) -> None:
        self.documents: list[dict[str, str]] = []
        self.creates: list[dict[str, Any]] = []
        self.deactivations: list[dict[str, Any]] = []
        self.create_error: KompasOSError | None = None
        self.deactivate_error: KompasOSError | None = None

    def list_for_employee(self, *, tenant_id: Any, actor: Any, employee_id: Any) -> list[Any]:
        return list(self.documents)

    def create_document(self, *, tenant_id: Any, actor: Any, employee_id: Any, draft: Any) -> Any:
        if self.create_error is not None:
            raise self.create_error
        doc_id = uuid.uuid4()
        self.creates.append({"employee_id": employee_id, "draft": draft})
        return _FakeDoc(doc_id)

    def deactivate_document(self, **kwargs: Any) -> None:
        if self.deactivate_error is not None:
            raise self.deactivate_error
        self.deactivations.append(kwargs)


class _Session:
    def __init__(
        self, docs: _EmployeeDocuments, employees: list[tuple[str, str, str]], store_id: Any
    ) -> None:
        self.tenant_id = TENANT
        self.employee_documents = docs
        self.uow = _Uow(employees, store_id)
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _EvidenceQueue:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []
        self.error: KompasOSError | None = None

    def enqueue(self, **kwargs: Any) -> None:
        if self.error is not None:
            raise self.error
        self.enqueued.append(kwargs)


class _Context:
    def __init__(
        self,
        docs: _EmployeeDocuments,
        *,
        employees: list[tuple[str, str, str]] | None = None,
        store_id: Any = STORE_ID,
    ) -> None:
        self._docs = docs
        self._employees = (
            employees if employees is not None else [(str(EMPLOYEE_ID), "Aygün", "Məmmədova")]
        )
        self._store_id = store_id
        self.tenant_id = TENANT
        self.sessions: list[_Session] = []
        self.evidence = _EvidenceQueue()
        self.upload_runs = 0

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(self._docs, self._employees, self._store_id)
        self.sessions.append(created)
        yield created

    def evidence_queue(self) -> _EvidenceQueue:
        return self.evidence

    def run_evidence_uploads(self) -> int:
        self.upload_runs += 1
        return 0


class _Actor:
    id = ACTOR_ID


def _attach(context: Any, theme: Any, *, qtbot: Any) -> Any:
    """Real `UsersScreen`-i qurur, kontrolleri bağlayır — hər testin başlanğıcı EYNİDİR."""
    from src.presentation.background_task import InlineExecutor
    from src.presentation.controllers.employee_documents import UsersEmployeeDocumentController
    from src.presentation.screens.group_c import UsersScreen

    screen = UsersScreen(theme)
    qtbot.addWidget(screen)
    screen.set_users([_user_row()])
    UsersEmployeeDocumentController(context, _Actor(), executor=InlineExecutor()).attach(screen)  # type: ignore[arg-type]
    return screen


def _patched_dialog_exec(
    monkeypatch: pytest.MonkeyPatch,
    *,
    doc_type: str = "PASPORT",
    doc_number: str = "AZ1234567",
    expiry_text: str = "",
    blocking: bool = False,
) -> None:
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_c import EmployeeDocumentDialog

    def fake_exec(self: EmployeeDocumentDialog) -> int:
        self._doc_type.set_text(doc_type)
        self._doc_number.set_text(doc_number)
        self._expiry.set_text(expiry_text)
        self._blocking.setChecked(blocking)
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Sənəd Əlavə Et")
        submit.click()
        return 0

    monkeypatch.setattr(EmployeeDocumentDialog, "exec", fake_exec)


# --------------------------------------------------------------------------- #
# 1. Real "···" → "Sənədlər" → real dialoq açılır
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_real_menu_action_opens_the_dialog_with_existing_documents(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_c import EmployeeDocumentDialog

    docs = _EmployeeDocuments()
    docs.documents = [_FakeDocumentEntity()]
    context = _Context(docs)
    screen = _attach(context, theme, qtbot=qtbot)

    captured: list[EmployeeDocumentDialog] = []
    original_init = EmployeeDocumentDialog.__init__

    def _spy_init(self: EmployeeDocumentDialog, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        captured.append(self)

    monkeypatch.setattr(EmployeeDocumentDialog, "__init__", _spy_init)
    monkeypatch.setattr(EmployeeDocumentDialog, "exec", lambda self: 0)  # bağlanmasın, sınamayaq

    _trigger_menu_action(screen, "Sənədlər")  # ÇÖKMƏMƏLİDİR, bloklanmamalıdır

    assert len(captured) == 1
    dialog = captured[0]
    texts = [b.text() for b in dialog.findChildren(QPushButton)]
    assert "Deaktiv Et" in texts  # mövcud sənədin sətri REAL göstərilib


@requires_qt
def test_an_employee_not_found_shows_an_error_and_does_not_open_the_dialog(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_c import EmployeeDocumentDialog

    context = _Context(_EmployeeDocuments(), employees=[])  # heç bir işçi tapılmır
    screen = _attach(context, theme, qtbot=qtbot)

    opened: list[Any] = []
    monkeypatch.setattr(EmployeeDocumentDialog, "__init__", lambda self, *a, **k: opened.append(1))

    _trigger_menu_action(screen, "Sənədlər")

    assert opened == []
    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 2. Real "Sənəd Əlavə Et" — uğur, boş sahə, yanlış tarix, ekstremal mətn
# --------------------------------------------------------------------------- #


@requires_qt
def test_creating_a_document_via_the_real_dialog_commits_without_a_file(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    docs = _EmployeeDocuments()
    context = _Context(docs)
    screen = _attach(context, theme, qtbot=qtbot)

    _patched_dialog_exec(monkeypatch, doc_type="PASPORT", doc_number="AZ1234567")
    _trigger_menu_action(screen, "Sənədlər")

    assert len(docs.creates) == 1
    draft = docs.creates[0]["draft"]
    assert draft.doc_type == "PASPORT"
    assert draft.doc_number == "AZ1234567"
    assert any(s.committed for s in context.sessions)
    assert context.evidence.enqueued == [], "fayl seçilməyib — növbəyə HEÇ NƏ yazılmamalıdır"


@requires_qt
def test_an_empty_doc_type_is_rejected_by_the_real_dialog_before_any_write(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_c import EmployeeDocumentDialog

    docs = _EmployeeDocuments()
    context = _Context(docs)
    screen = _attach(context, theme, qtbot=qtbot)

    def fake_exec(self: EmployeeDocumentDialog) -> int:
        # Sənəd növü BOŞ buraxılır — real "Sənəd Əlavə Et" kliki dialoqun ÖZ
        # yoxlamasında dayanmalıdır.
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Sənəd Əlavə Et")
        submit.click()
        assert self._doc_type.has_error
        return self.reject()

    monkeypatch.setattr(EmployeeDocumentDialog, "exec", fake_exec)

    _trigger_menu_action(screen, "Sənədlər")

    assert docs.creates == []


@requires_qt
def test_a_malformed_expiry_date_shows_a_real_error_and_writes_nothing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    docs = _EmployeeDocuments()
    context = _Context(docs)
    screen = _attach(context, theme, qtbot=qtbot)

    _patched_dialog_exec(monkeypatch, expiry_text="12.08.2026")  # ISO deyil

    _trigger_menu_action(screen, "Sənədlər")  # ÇÖKMƏMƏLİDİR

    assert docs.creates == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_hostile_and_extreme_text_in_real_fields_passes_through_without_crashing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    docs = _EmployeeDocuments()
    context = _Context(docs)
    screen = _attach(context, theme, qtbot=qtbot)

    hostile_number = "'; DROP TABLE employee_documents; -- 🔥" + "A" * 10_000
    _patched_dialog_exec(monkeypatch, doc_type="MÜQAVİLƏ", doc_number=hostile_number)

    _trigger_menu_action(screen, "Sənədlər")  # ÇÖKMƏMƏLİDİR

    assert len(docs.creates) == 1
    assert docs.creates[0]["draft"].doc_number == hostile_number


@requires_qt
def test_create_failure_from_the_use_case_shows_the_domain_message(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    docs = _EmployeeDocuments()
    docs.create_error = KompasOSError(
        "no permission", user_message="Sənəd əlavə etmək səlahiyyətiniz yoxdur."
    )
    context = _Context(docs)
    screen = _attach(context, theme, qtbot=qtbot)

    _patched_dialog_exec(monkeypatch)

    _trigger_menu_action(screen, "Sənədlər")  # ÇÖKMƏMƏLİDİR

    # `_load()` (dialoqu AÇARKƏN edilən OXU) da öz sessiyasını commit edir —
    # bu, YAZI sessiyası deyil. Əsl yoxlama: heç bir sənəd YARANMAYIB.
    assert docs.creates == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_a_missing_store_still_creates_the_document_but_reports_the_upload_gap(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    """Mağazasız işçi — sənəd YARANIR (commit), fayl isə AÇIQ izahla növbəyə düşmür."""
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_c import EmployeeDocumentDialog

    docs = _EmployeeDocuments()
    context = _Context(docs, store_id=None)
    screen = _attach(context, theme, qtbot=qtbot)

    scan = tmp_path / "skan.pdf"
    scan.write_bytes(b"%PDF-1.4 test")

    def fake_exec(self: EmployeeDocumentDialog) -> int:
        self._doc_type.set_text("PASPORT")
        self._file_path = str(scan)
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Sənəd Əlavə Et")
        submit.click()
        return 0

    monkeypatch.setattr(EmployeeDocumentDialog, "exec", fake_exec)

    _trigger_menu_action(screen, "Sənədlər")  # ÇÖKMƏMƏLİDİR

    assert len(docs.creates) == 1
    assert any(s.committed for s in context.sessions)
    assert context.evidence.enqueued == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_selecting_a_file_enqueues_it_and_triggers_the_background_upload(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_c import EmployeeDocumentDialog

    docs = _EmployeeDocuments()
    context = _Context(docs, store_id=STORE_ID)
    screen = _attach(context, theme, qtbot=qtbot)

    scan = tmp_path / "muqavile.pdf"
    scan.write_bytes(b"%PDF-1.4 test")

    def fake_exec(self: EmployeeDocumentDialog) -> int:
        self._doc_type.set_text("MÜQAVİLƏ")
        self._file_path = str(scan)
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Sənəd Əlavə Et")
        submit.click()
        return 0

    monkeypatch.setattr(EmployeeDocumentDialog, "exec", fake_exec)

    _trigger_menu_action(screen, "Sənədlər")  # ÇÖKMƏMƏLİDİR

    assert len(context.evidence.enqueued) == 1
    enqueued = context.evidence.enqueued[0]
    assert enqueued["filename"] == "muqavile.pdf"
    assert context.upload_runs == 1, "seçilmiş fayl FON işini dərhal işə salmalı idi"


@requires_qt
def test_an_unreadable_file_shows_an_error_but_the_document_row_still_exists(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    """Fayl seçilib, lakin diskdən oxuna bilmir (məs. qovluq seçilib) — sənəd qeydi qalır."""
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_c import EmployeeDocumentDialog

    docs = _EmployeeDocuments()
    context = _Context(docs)
    screen = _attach(context, theme, qtbot=qtbot)

    unreadable_dir = tmp_path / "qovluq"
    unreadable_dir.mkdir()

    def fake_exec(self: EmployeeDocumentDialog) -> int:
        self._doc_type.set_text("PASPORT")
        self._file_path = str(unreadable_dir)  # QOVLUQ — `read_bytes()` OSError atır
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Sənəd Əlavə Et")
        submit.click()
        return 0

    monkeypatch.setattr(EmployeeDocumentDialog, "exec", fake_exec)

    _trigger_menu_action(screen, "Sənədlər")  # ÇÖKMƏMƏLİDİR

    assert len(docs.creates) == 1
    assert context.evidence.enqueued == []
    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 3. Real "Deaktiv Et" — real sətir, real səbəb modalı
# --------------------------------------------------------------------------- #


@requires_qt
def test_deactivating_via_the_real_row_button_and_reason_prompt_commits(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog, QPushButton

    from src.presentation.screens.group_c import EmployeeDocumentDialog

    document_id = uuid.uuid4()
    docs = _EmployeeDocuments()
    docs.documents = [_FakeDocumentEntity(document_id=document_id)]
    context = _Context(docs)
    screen = _attach(context, theme, qtbot=qtbot)

    monkeypatch.setattr(
        QInputDialog,
        "getMultiLineText",
        staticmethod(lambda *a, **k: ("Sənəd köhnəlib", True)),
    )

    def fake_exec(self: EmployeeDocumentDialog) -> int:
        deactivate = next(b for b in self.findChildren(QPushButton) if b.text() == "Deaktiv Et")
        deactivate.click()
        return 0

    monkeypatch.setattr(EmployeeDocumentDialog, "exec", fake_exec)

    _trigger_menu_action(screen, "Sənədlər")

    assert len(docs.deactivations) == 1
    deactivation = docs.deactivations[0]
    assert str(deactivation["document_id"]) == str(document_id)
    assert deactivation["reason"] == "Sənəd köhnəlib"
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_declining_the_deactivate_reason_prompt_writes_nothing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog, QPushButton

    from src.presentation.screens.group_c import EmployeeDocumentDialog

    docs = _EmployeeDocuments()
    docs.documents = [_FakeDocumentEntity()]
    context = _Context(docs)
    screen = _attach(context, theme, qtbot=qtbot)

    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("", False)))

    def fake_exec(self: EmployeeDocumentDialog) -> int:
        deactivate = next(b for b in self.findChildren(QPushButton) if b.text() == "Deaktiv Et")
        deactivate.click()
        return 0

    monkeypatch.setattr(EmployeeDocumentDialog, "exec", fake_exec)

    _trigger_menu_action(screen, "Sənədlər")

    assert docs.deactivations == []


@requires_qt
def test_a_malformed_document_id_from_a_stale_row_does_not_crash(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    from src.presentation.screens.group_c import EmployeeDocumentDialog

    docs = _EmployeeDocuments()
    context = _Context(docs)
    screen = _attach(context, theme, qtbot=qtbot)

    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("səbəb", True))
    )

    def fake_exec(self: EmployeeDocumentDialog) -> int:
        self.deactivate_requested.emit("not-a-uuid")  # ÇÖKMƏMƏLİDİR
        return self.reject()

    monkeypatch.setattr(EmployeeDocumentDialog, "exec", fake_exec)

    _trigger_menu_action(screen, "Sənədlər")

    assert docs.deactivations == []
    assert screen.switcher().current_state() == "error"
