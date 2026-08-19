"""`ShiftSwapController` yazı yolu (`controllers/shift_swaps.py`).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ
──────────────────────────────────────────────────────────────────────────────
Kontroller ÜMUMİYYƏTLƏ yox idi və qüsur `test_signal_wiring_gate.py`-dan da
SÜKUTLA keçirdi: qapı siqnalı ADINA görə axtarır, `approved`/`rejected` isə
`TasksScreen`-də DƏ var — tapşırıq lövhəsinin bağlantısı bu ekranı da
«bağlanıb» göstərirdi. Ona görə burada ölçülən yalnız kontroller deyil, həm də
qapının bu kor nöqtəsinin bağlandığıdır (`test_signal_wiring_gate.py`-dakı
sinif-agah yoxlama).

Use case-in ÖZÜ (`_require_approver`, matrisin yenilənməsi, bildiriş)
`test_shift_scheduling.py`-nin işidir.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, ClassVar

import pytest

from src.domain.entities.shift import MIN_DECISION_REASON_LENGTH
from src.presentation.controllers import screen_data as screen_data_module
from src.presentation.controllers import shift_swaps as shift_swaps_module
from src.presentation.controllers.shift_swaps import ShiftSwapController
from src.shared.exceptions import KompasOSError

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
REQUEST = uuid.uuid4()


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
        self.errors: list[tuple[str, str]] = []
        self.retries: list[Any] = []

    def show_error(self, *, title: str, message: str, on_retry: Any = None, **_: Any) -> None:
        self.errors.append((title, message))
        self.retries.append(on_retry)


class _Swaps:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.approvals: list[dict[str, Any]] = []
        self.rejections: list[dict[str, Any]] = []

    def approve(self, **kwargs: Any) -> Any:
        if self.failure is not None:
            raise self.failure
        self.approvals.append(kwargs)
        return object()

    def reject(self, **kwargs: Any) -> Any:
        if self.failure is not None:
            raise self.failure
        self.rejections.append(kwargs)
        return object()


class _Session:
    def __init__(self, *, swaps: _Swaps) -> None:
        self.tenant_id = TENANT
        self.shift_swaps = swaps
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(self, *, swaps: _Swaps) -> None:
        self._swaps = swaps
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(swaps=self._swaps)
        self.sessions.append(created)
        yield created


class _Actor:
    id = uuid.uuid4()


class _Binder:
    populated: ClassVar[list[str]] = []
    failure: ClassVar[Exception | None] = None

    def __init__(self, context: Any, actor: Any) -> None:
        pass

    def populate(self, key: str, _screen: Any) -> None:
        if _Binder.failure is not None:
            raise _Binder.failure
        _Binder.populated.append(key)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    _Binder.populated = []
    _Binder.failure = None
    monkeypatch.setattr(screen_data_module, "ScreenDataBinder", _Binder)
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        shift_swaps_module,
        "_inform",
        lambda _screen, title, message: shown.append((title, message)),
    )
    return shown


def _answer(monkeypatch: pytest.MonkeyPatch, text: str, *, accepted: bool = True) -> None:
    monkeypatch.setattr(
        ShiftSwapController, "_ask_reason", staticmethod(lambda _s: text if accepted else None)
    )


def _build(*, failure: Exception | None = None) -> tuple[Any, _Screen, _Context, _Swaps]:
    swaps = _Swaps(failure=failure)
    context = _Context(swaps=swaps)
    controller = ShiftSwapController(context, _Actor())  # type: ignore[arg-type]
    screen = _Screen()
    controller.attach(screen)  # type: ignore[arg-type]
    return controller, screen, context, swaps


LONG_REASON = "Həmin gün mağazada tək kassir qalır."


def test_approve_writes_commits_and_rereads() -> None:
    """Qüsurun ÖZÜ: bu siqnalı heç kim dinləmirdi."""
    _, screen, context, swaps = _build()

    screen.approved.emit(str(REQUEST))

    assert swaps.approvals[0]["request_id"] == REQUEST
    assert context.sessions[0].committed is True
    assert _Binder.populated == ["shift_swaps"]


def test_reject_carries_the_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    _, screen, context, swaps = _build()
    _answer(monkeypatch, LONG_REASON)

    screen.rejected.emit(str(REQUEST))

    assert swaps.rejections[0]["reason"] == LONG_REASON
    assert context.sessions[0].committed is True


def test_a_cancelled_reason_dialog_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _, screen, context, swaps = _build()
    _answer(monkeypatch, "", accepted=False)

    screen.rejected.emit(str(REQUEST))

    assert context.sessions == []
    assert swaps.rejections == []


def test_a_short_reason_never_opens_a_session(_isolate: list[tuple[str, str]]) -> None:
    """`_ask_reason`-un ÖZÜ ölçülür — dialoq qısa mətni geri qaytarmır."""
    controller, screen, _, _ = _build()

    class _Dialog:
        @staticmethod
        def getMultiLineText(*_a: Any, **_k: Any) -> tuple[str, bool]:  # noqa: N802
            return "az", True

    import sys

    stub = type("_Stub", (), {"QInputDialog": _Dialog, "QMessageBox": object})()
    original = sys.modules.get("PySide6.QtWidgets")
    sys.modules["PySide6.QtWidgets"] = stub  # type: ignore[assignment]
    try:
        assert controller._ask_reason(screen) is None  # type: ignore[arg-type]
    finally:
        if original is not None:
            sys.modules["PySide6.QtWidgets"] = original
    assert _isolate[0][1] == shift_swaps_module.SHORT_REASON


def test_the_reason_minimum_comes_from_the_domain() -> None:
    """Rəqəm İKİ yerdə yazılmır — mesaj domendəki həddən qurulur."""
    assert str(MIN_DECISION_REASON_LENGTH) in shift_swaps_module.SHORT_REASON
    assert str(MIN_DECISION_REASON_LENGTH) in shift_swaps_module.REJECT_PROMPT


def test_an_unusable_request_id_is_reported(_isolate: list[tuple[str, str]]) -> None:
    _, screen, context, _ = _build()

    screen.approved.emit("")

    assert context.sessions == []
    assert _isolate[0][1] == shift_swaps_module.UNKNOWN_REQUEST_MESSAGE


def test_a_failed_decision_keeps_the_list(_isolate: list[tuple[str, str]]) -> None:
    _, screen, context, swaps = _build(failure=KompasOSError("səlahiyyət yoxdur"))

    screen.approved.emit(str(REQUEST))

    assert swaps.approvals == []
    assert context.sessions[0].committed is False
    assert _Binder.populated == []
    assert screen.errors == []
    assert len(_isolate) == 1


def test_a_read_failure_offers_a_working_retry() -> None:
    controller, screen, _, _ = _build()
    _Binder.failure = KompasOSError("baza əlçatmazdır")

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.errors[0][0] == "Sorğular oxuna bilmədi"
    assert callable(screen.retries[0])
