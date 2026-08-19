"""«Yeni Tapşırıq» yolu — dialoq + `TaskReviewController._on_create`.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL VAR
──────────────────────────────────────────────────────────────────────────────
`TasksScreen`-də «Yeni Tapşırıq» düyməsi VARDI və `create_requested` siqnalını
yayırdı, lakin heç bir kontroller onu dinləmirdi: menecer basırdı, heç nə
olmurdu — yəni GUI-dan tapşırıq yaratmağın HEÇ BİR yolu yox idi, halbuki
`TaskWorkflowUseCase.assign` tam işlək idi.

Testlər iki şeyi kilidləyir: (1) dialoqun prioritet dəyərləri domen enum-u ilə
üst-üstə düşür — ekran `TaskPriority`-ni İDXAL ETMİR (qat sırası), ona görə
uyğunluq yalnız testlə qorunur; (2) kontroller formanı use case-ə DOĞRU
ötürür və naive `datetime`-ı tz-aware-ə çevirir.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import pytest

from src.domain.entities.task import TaskPriority
from src.presentation.controllers import screen_data as screen_data_module
from src.presentation.controllers import tasks as tasks_module
from src.presentation.controllers.tasks import TaskReviewController
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ASSIGNEE = uuid.uuid4()


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _Signal:
    def __init__(self) -> None:
        self._slots: list[Any] = []

    def connect(self, slot: Any) -> None:
        self._slots.append(slot)

    def emit(self, *args: Any) -> None:
        for slot in self._slots:
            slot(*args)


class _Screen:
    def __init__(self) -> None:
        self.approved = _Signal()
        self.rejected = _Signal()
        self.create_requested = _Signal()
        self.errors: list[tuple[str, str]] = []

    def show_error(self, *, title: str, message: str, on_retry: Any = None, **_: Any) -> None:
        self.errors.append((title, message))


class _Tasks:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.assignments: list[dict[str, Any]] = []

    def assign(self, **kwargs: Any) -> Any:
        if self.failure is not None:
            raise self.failure
        self.assignments.append(kwargs)
        return object()


class _Connection:
    def __init__(self, rows: list[dict[str, Any]], *, failure: Exception | None = None) -> None:
        self._rows = rows
        self._failure = failure

    def execute(self, _sql: str, _params: Any) -> _Connection:
        if self._failure is not None:
            raise self._failure
        return self

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _Uow:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection


class _Session:
    def __init__(self, *, tasks: _Tasks, connection: _Connection) -> None:
        self.tenant_id = TENANT
        self.tasks = tasks
        self.uow = _Uow(connection)
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(self, *, rows: list[dict[str, Any]], failure: Exception | None = None) -> None:
        self.tasks = _Tasks()
        self._rows = rows
        self._failure = failure
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(
            tasks=self.tasks, connection=_Connection(self._rows, failure=self._failure)
        )
        self.sessions.append(created)
        yield created


class _Actor:
    id = uuid.uuid4()


class _Binder:
    populated: ClassVar[list[str]] = []

    def __init__(self, context: Any, actor: Any) -> None:
        pass

    def populate(self, key: str, _screen: Any) -> None:
        _Binder.populated.append(key)


ROWS = [{"id": ASSIGNEE, "first_name": "Aysel", "last_name": "Quliyeva"}]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    _Binder.populated = []
    monkeypatch.setattr(screen_data_module, "ScreenDataBinder", _Binder)
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        tasks_module, "_inform", lambda _s, title, message: shown.append((title, message))
    )
    return shown


def _payload(**overrides: Any) -> dict[str, Any]:
    base = {
        "title": "Vitrin şəklini yenilə",
        "assignee_id": ASSIGNEE,
        "deadline": datetime.now(UTC) + timedelta(days=1),
        "description": "Yeni kolleksiya",
        "priority": "HIGH",
        "requires_evidence": True,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# Dialoq ↔ domen uyğunluğu
# --------------------------------------------------------------------------- #


@requires_qt
def test_dialog_priorities_match_the_domain_enum() -> None:
    """Ekran `TaskPriority`-ni idxal ETMİR — uyğunluğu yalnız bu test qoruyur."""
    from src.presentation.screens.group_f import NewTaskDialog

    dialog_values = {value for value, _label in NewTaskDialog.PRIORITIES}

    assert dialog_values == {member.value for member in TaskPriority}


# --------------------------------------------------------------------------- #
# Kontroller
# --------------------------------------------------------------------------- #


def test_create_passes_the_form_to_the_use_case() -> None:
    context = _Context(rows=ROWS)
    screen = _Screen()
    controller = TaskReviewController(context, _Actor())  # type: ignore[arg-type]

    controller._create(screen, _payload())  # type: ignore[arg-type]

    draft = context.tasks.assignments[0]["draft"]
    assert draft.title == "Vitrin şəklini yenilə"
    assert draft.assignee_id == ASSIGNEE
    assert draft.priority is TaskPriority.HIGH
    assert draft.requires_evidence is True
    assert context.sessions[-1].committed is True
    assert _Binder.populated == ["tasks"]


def test_a_naive_deadline_is_made_timezone_aware() -> None:
    """`QDateTime.toPython()` naive qaytarır — domen tz-aware TƏLƏB EDİR."""
    context = _Context(rows=ROWS)
    screen = _Screen()
    controller = TaskReviewController(context, _Actor())  # type: ignore[arg-type]

    # NAIVE QƏSDƏNDİR — testin MÖVZUSU məhz budur: `QDateTime.toPython()`
    # tz-siz `datetime` qaytarır və kontroller onu bağlamalıdır.
    naive = datetime(2026, 9, 1, 18, 0)  # noqa: DTZ001
    controller._create(screen, _payload(deadline=naive))  # type: ignore[arg-type]

    draft = context.tasks.assignments[0]["draft"]
    assert draft.deadline.tzinfo is not None


def test_every_task_gets_its_own_identifier() -> None:
    """`task_id` ÇAĞIRAN TƏRƏFDƏN gəlir — iki tapşırıq eyni id ala bilməz."""
    context = _Context(rows=ROWS)
    screen = _Screen()
    controller = TaskReviewController(context, _Actor())  # type: ignore[arg-type]

    controller._create(screen, _payload())  # type: ignore[arg-type]
    controller._create(screen, _payload(title="İkinci"))  # type: ignore[arg-type]

    ids = [call["task_id"] for call in context.tasks.assignments]
    assert ids[0] != ids[1]


def test_a_failed_assignment_reports_and_skips_the_reread() -> None:
    context = _Context(rows=ROWS)
    context.tasks.failure = KompasOSError("səlahiyyət yoxdur")
    screen = _Screen()
    controller = TaskReviewController(context, _Actor())  # type: ignore[arg-type]

    controller._create(screen, _payload())  # type: ignore[arg-type]

    assert context.tasks.assignments == []
    assert context.sessions[-1].committed is False
    assert _Binder.populated == []


# --------------------------------------------------------------------------- #
# İşçi siyahısı
# --------------------------------------------------------------------------- #


def test_the_employee_list_is_read_before_the_form_opens() -> None:
    context = _Context(rows=ROWS)
    controller = TaskReviewController(context, _Actor())  # type: ignore[arg-type]

    employees = controller._read_employees(_Screen())  # type: ignore[arg-type]

    assert employees == [(ASSIGNEE, "Aysel Quliyeva")]


def test_an_unreadable_employee_list_is_distinguished_from_an_empty_one(
    _isolate: list[tuple[str, str]],
) -> None:
    """`None` = oxuna bilmədi, `[]` = həqiqətən işçi yoxdur — iki ayrı izah."""
    context = _Context(rows=[], failure=KompasOSError("baza əlçatmazdır"))
    controller = TaskReviewController(context, _Actor())  # type: ignore[arg-type]

    assert controller._read_employees(_Screen()) is None  # type: ignore[arg-type]
    assert len(_isolate) == 1

    empty = TaskReviewController(_Context(rows=[]), _Actor())  # type: ignore[arg-type]
    assert empty._read_employees(_Screen()) == []  # type: ignore[arg-type]


def test_attach_connects_the_create_button() -> None:
    """Qüsurun ÖZÜ: `create_requested` heç yerə bağlı deyildi."""
    context = _Context(rows=ROWS)
    screen = _Screen()
    TaskReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    assert screen.create_requested._slots != []
