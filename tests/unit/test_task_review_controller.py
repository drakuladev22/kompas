"""`TaskReviewController` yazı yolu (`controllers/tasks.py`) — DÖVRƏ 5 audit.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ
──────────────────────────────────────────────────────────────────────────────
`tasks.py` `tests/` daxilində adı belə çəkilmirdi (CLAUDE.md bölmə 2 — «10
kontroller LİTERAL 0%»). `_on_approve`/`_on_reject` `TaskId(UUID(task_id))`
çağırırdı, lakin `_write()`-in qoruyucusu YALNIZ `except KompasOSError`-dır —
`UUID()`-in atdığı `ValueError` ORADAN KEÇMİR. Normal axında `task_id` ekranın
ÖZ kartından gəlir (həmişə etibarlıdır), lakin köhnəlmiş kart/UI
uyğunsuzluğunda bu, ÇÖKMƏ demək idi (siqnal slotundan yuxarı qalxan
`ValueError`). Bu fayl HƏM həmin qapını, HƏM də normal (etibarlı ID) axını
ölçür.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from src.presentation.controllers.tasks import TaskReviewController

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR = uuid.uuid4()


class _Tasks:
    def __init__(self) -> None:
        self.approved: list[dict[str, Any]] = []
        self.rejected: list[dict[str, Any]] = []

    def approve(self, **kwargs: Any) -> None:
        self.approved.append(kwargs)

    def reject(self, **kwargs: Any) -> None:
        self.rejected.append(kwargs)


class _Session:
    def __init__(self, tasks: _Tasks) -> None:
        self.tenant_id = TENANT
        self.tasks = tasks
        self.committed = False

    def commit(self) -> None:
        self.committed = True

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _Context:
    def __init__(self, tasks: _Tasks) -> None:
        self._tasks = tasks
        self.sessions: list[_Session] = []

    def session(self, **_: Any) -> _Session:
        created = _Session(self._tasks)
        self.sessions.append(created)
        return created


class _Actor:
    id = ACTOR


class _Screen:
    def __init__(self) -> None:
        self.errors: list[tuple[str, str]] = []
        self.refreshed = 0

    def show_error(self, *, title: str, message: str, **_: Any) -> None:
        self.errors.append((title, message))


def _controller(tasks: _Tasks) -> tuple[TaskReviewController, _Context]:
    context = _Context(tasks)
    controller = TaskReviewController(context, _Actor())  # type: ignore[arg-type]
    return controller, context


def test_malformed_task_id_is_reported_not_crashed_on_approve(monkeypatch: Any) -> None:
    """`UUID("")` `_write`-in `except KompasOSError` qoruyucusundan KEÇMƏMƏLİDİR."""
    tasks = _Tasks()
    controller, context = _controller(tasks)
    controller.refresh = lambda screen: None  # type: ignore[method-assign]
    screen = _Screen()

    controller._on_approve(screen, "kod-deyil")

    assert screen.errors == [
        ("Təsdiq yazılmadı", "Tapşırıq identifikatoru düzgün deyil. Səhifəni yeniləyin.")
    ]
    assert not tasks.approved, "yararsız ID ilə use case ÇAĞIRILMAMALIDIR"
    assert context.sessions == [], "sessiya belə AÇILMAMALIDIR"


def test_malformed_task_id_is_reported_not_crashed_on_reject(monkeypatch: Any) -> None:
    """Rədd yolunda da eyni qapı — səbəb dialoqu BELƏ AÇILMAMALIDIR."""
    tasks = _Tasks()
    controller, context = _controller(tasks)
    controller.refresh = lambda screen: None  # type: ignore[method-assign]
    asked = {"count": 0}

    def _ask_reason(screen: Any) -> str:
        asked["count"] += 1
        return "səbəb"

    controller._ask_reason = _ask_reason  # type: ignore[method-assign]
    screen = _Screen()

    controller._on_reject(screen, "")

    assert screen.errors == [
        ("Rədd yazılmadı", "Tapşırıq identifikatoru düzgün deyil. Səhifəni yeniləyin.")
    ]
    assert not tasks.rejected
    assert asked["count"] == 0, "səbəb sorğusu ID yoxlamasından SONRA gəlməlidir"
    assert context.sessions == []


def test_valid_task_id_approves_and_commits() -> None:
    tasks = _Tasks()
    controller, context = _controller(tasks)
    refreshed: list[Any] = []

    def _refresh(screen: Any) -> None:
        refreshed.append(screen)

    controller.refresh = _refresh  # type: ignore[method-assign]
    screen = _Screen()
    task_id = uuid.uuid4()

    controller._on_approve(screen, str(task_id))

    assert len(tasks.approved) == 1
    assert tasks.approved[0]["task_id"] == task_id
    assert context.sessions[0].committed
    assert screen.errors == []
    assert refreshed == [screen]


def test_valid_task_id_rejects_with_the_supplied_reason() -> None:
    tasks = _Tasks()
    controller, context = _controller(tasks)
    controller.refresh = lambda screen: None  # type: ignore[method-assign]
    controller._ask_reason = lambda screen: "Foto yararsızdır"  # type: ignore[method-assign]
    screen = _Screen()
    task_id = uuid.uuid4()

    controller._on_reject(screen, str(task_id))

    assert len(tasks.rejected) == 1
    assert tasks.rejected[0]["task_id"] == task_id
    assert tasks.rejected[0]["reason"] == "Foto yararsızdır"
    assert context.sessions[0].committed
