"""ÖLÜ QORUYUCULAR — şərhin vəd etdiyi, kodun isə etmədiyi yoxlamalar.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL VAR
──────────────────────────────────────────────────────────────────────────────
Layihədə təkrarlanan bir qüsur növü var: qoruma YAZILIR, şərhdə İZAH edilir,
lakin heç vaxt İCRA olunmur (`DOM-R2-01` — `Fine.reverse()`-dəki mənfi məbləğ
yoxlaması `is_positive` budağının içində qalmışdı, yəni ölü idi). Buradakı
testlər həmin növün ÜÇ nüsxəsini kilidləyir:

* `tasks.py` — `MIN_REJECT_REASON = 10` təyin edilmişdi, dialoqun mətnində
  görünürdü, lakin HEÇ NƏ onu yoxlamırdı;
* `camera_queue.py` — «minimum 10 simvol» mətndə hərfi yazılmışdı, nə idxal
  vardı, nə yoxlama;
* `sales_points.py` — `redemption_id` «ikiqat klikdən qoruyur» deyirdi, halbuki
  `uuid4()` KLİKİN İÇİNDƏ çağırılırdı, yəni hər klik yeni id verirdi.

Hər üçündə istifadəçi zərəri eynidir: mətn/klik itir və ya təkrarlanır.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, ClassVar

import pytest

from src.domain.entities.appeal import MIN_DECISION_NOTE_LENGTH
from src.domain.entities.attendance_record import MIN_REJECT_REASON_LENGTH
from src.domain.entities.task import MIN_REJECTION_REASON_LENGTH
from src.presentation.controllers import screen_data as screen_data_module
from src.presentation.controllers import tasks as tasks_module
from src.presentation.controllers.sales_points import SalesPointsController
from src.presentation.controllers.tasks import TaskReviewController

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
TASK = uuid.uuid4()
REWARD = uuid.uuid4()


# --------------------------------------------------------------------------- #
# Ortaq sahtələr
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
        # `attach` bunu da bağlayır («Yeni Tapşırıq» dialoqu) — sahtə ekranda
        # olmasaydı, bağlama `AttributeError` ilə çökərdi.
        self.create_requested = _Signal()
        self.reward_requested = _Signal()
        self.appeal_requested = _Signal()
        self.errors: list[tuple[str, str]] = []

    def show_error(self, *, title: str, message: str, on_retry: Any = None, **_: Any) -> None:
        self.errors.append((title, message))


class _Tasks:
    def __init__(self) -> None:
        self.rejections: list[dict[str, Any]] = []

    def approve(self, **kwargs: Any) -> Any:
        return object()

    def reject(self, **kwargs: Any) -> Any:
        self.rejections.append(kwargs)
        return object()


class _SalesPoints:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def request_reward(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        return object()

    def open_dispute(self, **kwargs: Any) -> Any:
        return object()


class _Session:
    def __init__(self, *, tasks: _Tasks, sales_points: _SalesPoints) -> None:
        self.tenant_id = TENANT
        self.tasks = tasks
        self.sales_points = sales_points
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(self) -> None:
        self.tasks = _Tasks()
        self.sales_points = _SalesPoints()
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(tasks=self.tasks, sales_points=self.sales_points)
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


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    _Binder.populated = []
    monkeypatch.setattr(screen_data_module, "ScreenDataBinder", _Binder)
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        tasks_module, "_inform", lambda _s, title, message: shown.append((title, message))
    )
    return shown


def _answer(monkeypatch: pytest.MonkeyPatch, text: str, *, accepted: bool = True) -> None:
    """`QInputDialog.getMultiLineText` cavabını sahtələyir — Qt qalxmır."""

    class _Dialog:
        @staticmethod
        def getMultiLineText(*_args: Any, **_kwargs: Any) -> tuple[str, bool]:  # noqa: N802
            return text, accepted

    monkeypatch.setitem(
        __import__("sys").modules,
        "PySide6.QtWidgets",
        type("_Stub", (), {"QInputDialog": _Dialog, "QMessageBox": _MessageBox})(),
    )


class _MessageBox:
    """`QMessageBox` əvəzi — `camera_queue` xəbərdarlığını yığır."""

    shown: ClassVar[list[str]] = []

    class Icon:
        Warning = 0

    def __init__(self, _parent: Any = None) -> None:
        self._text = ""

    def setIcon(self, _icon: Any) -> None:  # noqa: N802
        return None

    def setWindowTitle(self, _title: str) -> None:  # noqa: N802
        return None

    def setText(self, text: str) -> None:  # noqa: N802
        self._text = text

    def exec(self) -> None:
        _MessageBox.shown.append(self._text)


# --------------------------------------------------------------------------- #
# TASK-01 — tapşırığın rədd səbəbi
# --------------------------------------------------------------------------- #


def test_task_reject_reason_shorter_than_the_domain_minimum_never_reaches_the_use_case(
    monkeypatch: pytest.MonkeyPatch, _isolate: list[tuple[str, str]]
) -> None:
    """Qısa səbəb sessiya AÇMADAN qaytarılır — əks halda yazılan mətn itirdi."""
    context = _Context()
    screen = _Screen()
    TaskReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    _answer(monkeypatch, "qısa")

    screen.rejected.emit(str(TASK))

    assert context.sessions == []
    assert context.tasks.rejections == []
    assert len(_isolate) == 1


def test_task_reject_reason_at_the_domain_minimum_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _Context()
    screen = _Screen()
    TaskReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    _answer(monkeypatch, "x" * MIN_REJECTION_REASON_LENGTH)

    screen.rejected.emit(str(TASK))

    assert len(context.tasks.rejections) == 1
    assert context.sessions[0].committed is True


def test_task_screen_mirror_equals_the_domain_constant() -> None:
    """Rəqəm İKİ yerdə YAZILMIR — ekran domendəki dəyəri idxal edir."""
    assert tasks_module.MIN_REJECT_REASON is MIN_REJECTION_REASON_LENGTH


def test_task_cancelled_dialog_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _Context()
    screen = _Screen()
    TaskReviewController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    _answer(monkeypatch, "kifayət qədər uzun səbəb", accepted=False)

    screen.rejected.emit(str(TASK))

    assert context.sessions == []


# --------------------------------------------------------------------------- #
# CAM-01 — kamera növbəsində rədd səbəbi
# --------------------------------------------------------------------------- #


def test_camera_queue_reason_dialog_uses_the_domain_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qısa səbəb `None` qaytarır — yəni yazı yolu heç başlamır."""
    from src.presentation.controllers.camera_queue import CameraQueueController

    _MessageBox.shown = []
    _answer(monkeypatch, "az")

    assert CameraQueueController._ask_reason(_Screen()) is None  # type: ignore[arg-type]
    assert _MessageBox.shown != []
    assert str(MIN_REJECT_REASON_LENGTH) in _MessageBox.shown[0]


def test_camera_queue_reason_at_the_boundary_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.presentation.controllers.camera_queue import CameraQueueController

    _MessageBox.shown = []
    reason = "x" * MIN_REJECT_REASON_LENGTH
    _answer(monkeypatch, reason)

    assert CameraQueueController._ask_reason(_Screen()) == reason  # type: ignore[arg-type]
    assert _MessageBox.shown == []


# --------------------------------------------------------------------------- #
# SP-01 — mükafat sorğusunun ikiqat kliki
# --------------------------------------------------------------------------- #


def test_double_click_reuses_the_same_redemption_id() -> None:
    """İki klik = BİR sətir. `ON CONFLICT (id)` yalnız EYNİ id ilə qoruyur."""
    context = _Context()
    screen = _Screen()
    SalesPointsController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    screen.reward_requested.emit(str(REWARD))
    screen.reward_requested.emit(str(REWARD))

    ids = [call["redemption_id"] for call in context.sales_points.requests]
    assert len(ids) == 2
    assert ids[0] == ids[1]


def test_a_different_reward_gets_its_own_redemption_id() -> None:
    """Ayrı mükafat AYRI sətirdir — pəncərə mükafat-başınadır."""
    context = _Context()
    screen = _Screen()
    SalesPointsController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    other = uuid.uuid4()

    screen.reward_requested.emit(str(REWARD))
    screen.reward_requested.emit(str(other))

    ids = [call["redemption_id"] for call in context.sales_points.requests]
    assert ids[0] != ids[1]


def test_a_click_after_the_window_starts_a_new_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pəncərə bitəndən sonra klik HƏQİQİ ikinci sorğudur — id yenilənir."""
    from src.presentation.controllers import sales_points as sales_points_module

    context = _Context()
    screen = _Screen()
    SalesPointsController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    ticks = iter([0.0, 999.0])
    monkeypatch.setattr(sales_points_module, "monotonic", lambda: next(ticks))

    screen.reward_requested.emit(str(REWARD))
    screen.reward_requested.emit(str(REWARD))

    ids = [call["redemption_id"] for call in context.sales_points.requests]
    assert ids[0] != ids[1]


# --------------------------------------------------------------------------- #
# UI-R4-01 — «Yenidən Cəhd Et» düyməsi
# --------------------------------------------------------------------------- #


def test_the_appeal_note_minimum_is_shared_with_the_domain() -> None:
    """Kontroller mesajı domendəki həddi TƏKRARLAMIR, ONDAN qurur."""
    from src.presentation.controllers.fine_appeals import SHORT_NOTE_MESSAGE

    assert str(MIN_DECISION_NOTE_LENGTH) in SHORT_NOTE_MESSAGE
