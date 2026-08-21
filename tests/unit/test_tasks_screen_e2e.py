"""`TasksScreen` ↔ `TaskReviewController` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3)
──────────────────────────────────────────────────────────────────────────────
`test_task_review_controller.py` və `test_controller_dead_guards.py` sahtə
`_Screen` siniflə (siqnal + siyahı) ölçür — REAL `TasksScreen`, REAL
`TaskCard`, REAL `NewTaskDialog` heç vaxt qurulmur. Burada Kanban kartının
REAL "Təsdiqlə"/"Rədd Et" düymələri və "Yeni Tapşırıq" formasının REAL
sahələri klikllənir/doldurulur.

`refresh()` `ScreenDataBinder`-dən keçir (`controllers/tasks.py::refresh`
başlığı: oxu məntiqi TƏKRARLANMIR). Onu bu faylda REAL DB olmadan ölçmək üçün
`screen_data_module.ScreenDataBinder` sahtələnir — eyni qərar
`test_controller_dead_guards.py`-dədir. Kartların ÖZÜ isə `TasksScreen.
set_tasks()` REAL metodu ilə (ekranın həm maket, həm canlı yoldan istifadə
etdiyi ictimai API) əl ilə render olunur ki, real düymələr klikllənə bilsin.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, ClassVar

import pytest

from src.domain.entities.task import MIN_REJECTION_REASON_LENGTH
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()
TASK_ID = str(uuid.uuid4())
EMPLOYEE_ID = str(uuid.uuid4())


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


def _task_row(*, task_id: str = TASK_ID) -> dict[str, str]:
    return {
        "id": task_id,
        "title": "Anbarı təmizlə",
        "description": "Həftəlik təmizlik",
        "assignee": "Aygün Məmmədova",
        "due": "25.08.2026 18:00",
        "status_text": "",
    }


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


class _Uow:
    def __init__(self, employees: list[tuple[str, str, str]]) -> None:
        self.connection = _Connection(employees)


class _Tasks:
    def __init__(self) -> None:
        self.approvals: list[Any] = []
        self.rejections: list[dict[str, Any]] = []
        self.assignments: list[dict[str, Any]] = []
        self.approve_error: KompasOSError | None = None
        self.reject_error: KompasOSError | None = None
        self.assign_error: KompasOSError | None = None

    def approve(self, **kwargs: Any) -> None:
        if self.approve_error is not None:
            raise self.approve_error
        self.approvals.append(kwargs)

    def reject(self, **kwargs: Any) -> None:
        if self.reject_error is not None:
            raise self.reject_error
        self.rejections.append(kwargs)

    def assign(self, **kwargs: Any) -> None:
        if self.assign_error is not None:
            raise self.assign_error
        self.assignments.append(kwargs)


class _Session:
    def __init__(self, tasks: _Tasks, employees: list[tuple[str, str, str]]) -> None:
        self.tenant_id = TENANT
        self.tasks = tasks
        self.uow = _Uow(employees)
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(self, tasks: _Tasks, employees: list[tuple[str, str, str]] | None = None) -> None:
        self._tasks = tasks
        self._employees = employees or []
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(self._tasks, self._employees)
        self.sessions.append(created)
        yield created


class _Actor:
    id = ACTOR_ID


class _Binder:
    """`screen_data.ScreenDataBinder`-in yerini tutur — `test_controller_dead_guards.py` ilə
    eyni naxış."""

    calls: ClassVar[list[str]] = []

    def __init__(self, context: Any, actor: Any) -> None:
        pass

    def populate(self, key: str, _screen: Any) -> None:
        _Binder.calls.append(key)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from src.presentation.controllers import screen_data as screen_data_module

    _Binder.calls = []
    monkeypatch.setattr(screen_data_module, "ScreenDataBinder", _Binder)
    # `_inform()` (`controllers/tasks.py`) real `QMessageBox.exec()` çağırır —
    # modal event loop test sapını əbədi bloklardı. Hər testdə lazım deyilsə
    # də, avtomatik tətbiq nə vaxt tetiklənəcəyini əvvəlcədən bilməyi aradan
    # qaldırır.
    monkeypatch.setattr(QMessageBox, "exec", lambda self: None)


# --------------------------------------------------------------------------- #
# 1. Real kart → real "Təsdiqlə"/"Rədd Et" düymələri
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_approve_on_a_real_card_commits_and_refreshes(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.tasks import TaskReviewController
    from src.presentation.screens.group_f import TasksScreen

    tasks = _Tasks()
    context = _Context(tasks)
    screen = TasksScreen(theme)
    qtbot.addWidget(screen)
    TaskReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    screen.set_tasks("review", [_task_row()])

    _click(screen, "Təsdiqlə")

    assert len(tasks.approvals) == 1
    assert str(tasks.approvals[0]["task_id"]) == TASK_ID
    assert any(s.committed for s in context.sessions)
    assert "tasks" in _Binder.calls, "refresh() ScreenDataBinder-i çağırmalı idi"


@requires_qt
def test_clicking_reject_prompts_for_a_reason_and_commits_it(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    from src.presentation.controllers.tasks import TaskReviewController
    from src.presentation.screens.group_f import TasksScreen

    tasks = _Tasks()
    context = _Context(tasks)
    screen = TasksScreen(theme)
    qtbot.addWidget(screen)
    TaskReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    screen.set_tasks("review", [_task_row()])

    reason = "Foto bulanıqdır, yenidən çəkin"
    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: (reason, True))
    )

    _click(screen, "Rədd Et")

    assert len(tasks.rejections) == 1
    assert tasks.rejections[0]["reason"] == reason
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_a_reject_reason_shorter_than_the_domain_minimum_never_reaches_the_use_case(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Real klik + real (qısaldılmış) modal cavabı — `MIN_REJECTION_REASON_LENGTH`
    REAL sərhəddir."""
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    from src.presentation.controllers.tasks import TaskReviewController
    from src.presentation.screens.group_f import TasksScreen

    tasks = _Tasks()
    context = _Context(tasks)
    screen = TasksScreen(theme)
    qtbot.addWidget(screen)
    TaskReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    screen.set_tasks("review", [_task_row()])

    short_reason = "x" * (MIN_REJECTION_REASON_LENGTH - 1)
    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: (short_reason, True))
    )
    monkeypatch.setattr(QMessageBox, "exec", lambda self: None)  # izah pəncərəsini bağlayır

    _click(screen, "Rədd Et")

    assert tasks.rejections == [], "Domen minimumundan qısa səbəb YAZI YOLUNA GİRMƏMƏLİDİR"


@requires_qt
def test_declining_the_reason_prompt_rejects_nothing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    from src.presentation.controllers.tasks import TaskReviewController
    from src.presentation.screens.group_f import TasksScreen

    tasks = _Tasks()
    context = _Context(tasks)
    screen = TasksScreen(theme)
    qtbot.addWidget(screen)
    TaskReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    screen.set_tasks("review", [_task_row()])

    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("", False)))

    _click(screen, "Rədd Et")

    assert tasks.rejections == []


@requires_qt
def test_approve_and_reject_buttons_do_not_appear_on_non_review_columns(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`reviewable=False` — «Açıq»/«Tamamlandı» sütununda qərar düyməsi YOXDUR."""
    from PySide6.QtWidgets import QPushButton

    from src.presentation.controllers.tasks import TaskReviewController
    from src.presentation.screens.group_f import TasksScreen

    tasks = _Tasks()
    context = _Context(tasks)
    screen = TasksScreen(theme)
    qtbot.addWidget(screen)
    TaskReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    screen.set_tasks("open", [_task_row()])

    texts = [b.text() for b in screen.findChildren(QPushButton)]
    assert "Təsdiqlə" not in texts
    assert "Rədd Et" not in texts


# --------------------------------------------------------------------------- #
# 2. Real "Yeni Tapşırıq" — real dialoq, real sahələr
# --------------------------------------------------------------------------- #


def _patched_new_task_exec(
    monkeypatch: pytest.MonkeyPatch, *, title: str, assignee_id: str
) -> None:
    from PySide6.QtWidgets import QComboBox, QPushButton

    from src.presentation.screens.group_f import NewTaskDialog

    def fake_exec(self: NewTaskDialog) -> int:
        self._title.set_text(title)
        combo = self._assignee.input_widget()
        assert isinstance(combo, QComboBox)
        index = combo.findData(assignee_id)
        assert index >= 0
        combo.setCurrentIndex(index)
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Tapşırıq Ver")
        submit.click()
        return 0

    monkeypatch.setattr(NewTaskDialog, "exec", fake_exec)


@requires_qt
def test_creating_a_task_via_the_real_dialog_commits_and_refreshes(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.tasks import TaskReviewController
    from src.presentation.screens.group_f import TasksScreen

    tasks = _Tasks()
    context = _Context(tasks, employees=[(EMPLOYEE_ID, "Aygün", "Məmmədova")])
    screen = TasksScreen(theme)
    qtbot.addWidget(screen)
    TaskReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _patched_new_task_exec(monkeypatch, title="Vitrini düzəlt", assignee_id=EMPLOYEE_ID)
    _click(screen, "Yeni Tapşırıq")

    assert len(tasks.assignments) == 1
    draft = tasks.assignments[0]["draft"]
    assert draft.title == "Vitrini düzəlt"
    assert str(draft.assignee_id) == EMPLOYEE_ID
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_creating_a_task_with_no_active_employees_does_not_open_a_dialog(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Boş işçi siyahısı REAL haldır (`_read_employees` başlığı) — çökmə YOX, izah VAR."""
    from src.presentation.controllers.tasks import TaskReviewController
    from src.presentation.screens.group_f import TasksScreen

    tasks = _Tasks()
    context = _Context(tasks, employees=[])
    screen = TasksScreen(theme)
    qtbot.addWidget(screen)
    TaskReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Yeni Tapşırıq")  # ÇÖKMƏMƏLİDİR — dialoq açılmamalıdır

    assert tasks.assignments == []


@requires_qt
def test_hostile_and_extreme_text_in_the_real_title_field_does_not_crash(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.tasks import TaskReviewController
    from src.presentation.screens.group_f import TasksScreen

    tasks = _Tasks()
    context = _Context(tasks, employees=[(EMPLOYEE_ID, "Aygün", "Məmmədova")])
    screen = TasksScreen(theme)
    qtbot.addWidget(screen)
    TaskReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    hostile = "'; DROP TABLE tasks; -- 🔥" + "A" * 10_000
    _patched_new_task_exec(monkeypatch, title=hostile, assignee_id=EMPLOYEE_ID)

    _click(screen, "Yeni Tapşırıq")  # ÇÖKMƏMƏLİDİR

    assert len(tasks.assignments) == 1
    assert tasks.assignments[0]["draft"].title == hostile.strip()


# --------------------------------------------------------------------------- #
# 3. Malformed ID və use-case istisnası — çökmür, AÇIQ mesaj göstərir
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_malformed_task_id_from_a_stale_card_does_not_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.tasks import TaskReviewController
    from src.presentation.screens.group_f import TasksScreen

    tasks = _Tasks()
    context = _Context(tasks)
    screen = TasksScreen(theme)
    qtbot.addWidget(screen)
    TaskReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    screen.approved.emit("not-a-uuid")  # ÇÖKMƏMƏLİDİR

    assert tasks.approvals == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_approve_failure_shows_the_domain_message_and_keeps_it_visible(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`_write()`-in xəta qolu `refresh()`-i DƏRHAL çağırmır — mesaj GÖRÜNÜR qalır."""
    from src.presentation.controllers.tasks import TaskReviewController
    from src.presentation.screens.group_f import TasksScreen

    tasks = _Tasks()
    tasks.approve_error = KompasOSError(
        "already approved", user_message="Bu tapşırıq artıq təsdiqlənib."
    )
    context = _Context(tasks)
    screen = TasksScreen(theme)
    qtbot.addWidget(screen)
    TaskReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    screen.set_tasks("review", [_task_row()])

    _click(screen, "Təsdiqlə")  # ÇÖKMƏMƏLİDİR

    assert not any(s.committed for s in context.sessions)
    assert screen.switcher().current_state() == "error"
