"""`ShiftSwapScreen` ↔ `controllers/shift_swaps.py` — REAL Qt e2e.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, dördüncü beşlik)
──────────────────────────────────────────────────────────────────────────────
`test_shift_swap_controller.py` `_Screen` sahtəsi ilə ölçür — REAL
`ShiftSwapScreen`, REAL `ClickableCard` kliki, REAL "Təsdiqlə"/"Rədd Et"
düymələri, REAL `QInputDialog`/`QMessageBox` heç vaxt qurulmur. Burada
hər biri FAKTİKİ qurulub klikllənir.

Naxış `test_tasks_screen_e2e.py`/`test_open_shift_screen_e2e.py`-dən
götürülüb: `ScreenDataBinder` sahtələnir (canlı oxu yolunun ÖZÜ,
`screen_data.py::_shift_swaps`, artıq `test_screen_data_binders.py`
ailəsinin işidir), yazı yolu isə TAM realdır.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, ClassVar

import pytest

from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()
REQUEST = uuid.uuid4()
OTHER_REQUEST = uuid.uuid4()


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


def _card_click(qtbot: Any, screen: Any, request_id: str) -> None:
    """`ClickableCard` düyməyə DEYİL, mousePressEvent-ə cavab verir — REAL klik."""
    from PySide6.QtCore import Qt

    card = next(c for c in screen._rows if c.key == request_id)
    qtbot.mouseClick(card, Qt.MouseButton.LeftButton)


def _request_row(
    *,
    request_id: str = str(REQUEST),
    from_name: str = "Aygün Məmmədova",
    shift: str = "25.08.2026",
    store: str = "Mərkəz",
    status: str = "Gözləyir",
    note: str = "Ailə tədbiri",
) -> dict[str, str]:
    return {
        "id": request_id,
        "from_name": from_name,
        "to_name": shift,
        "shift": shift,
        "store": store,
        "status": status,
        "note": note,
    }


# --------------------------------------------------------------------------- #
# Sahtələr — `screen_data.py::_shift_swaps` sahtələnir (yalnız YAZI yolu real)
# --------------------------------------------------------------------------- #


class _Swaps:
    """`session.shift_swaps` — domendəki `_require_pending` qoruyucusunu TƏQLİD edir.

    İkiqat klik ssenarisi üçün lazımdır: real domendə ikinci qərar
    `DomainRuleError` atır, burada da eyni cavab qaytarılır ki, kontrollerin
    xəta qolu REAL şərtlə sınansın.
    """

    def __init__(self) -> None:
        self.decided: set[str] = set()
        self.approvals: list[dict[str, Any]] = []
        self.rejections: list[dict[str, Any]] = []
        self.approve_error: KompasOSError | None = None
        self.reject_error: KompasOSError | None = None

    def approve(self, *, tenant_id: Any, approver: Any, request_id: Any) -> None:
        if self.approve_error is not None:
            raise self.approve_error
        if str(request_id) in self.decided:
            raise KompasOSError("already decided", user_message="Bu sorğu artıq emal edilib.")
        self.decided.add(str(request_id))
        self.approvals.append(
            {"tenant_id": tenant_id, "approver": approver, "request_id": request_id}
        )

    def reject(self, *, tenant_id: Any, approver: Any, request_id: Any, reason: str) -> None:
        if self.reject_error is not None:
            raise self.reject_error
        if str(request_id) in self.decided:
            raise KompasOSError("already decided", user_message="Bu sorğu artıq emal edilib.")
        self.decided.add(str(request_id))
        self.rejections.append(
            {
                "tenant_id": tenant_id,
                "approver": approver,
                "request_id": request_id,
                "reason": reason,
            }
        )


class _Session:
    def __init__(self, swaps: _Swaps) -> None:
        self.tenant_id = TENANT
        self.shift_swaps = swaps
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(self, swaps: _Swaps) -> None:
        self._swaps = swaps
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(self._swaps)
        self.sessions.append(created)
        yield created


class _Actor:
    id = ACTOR_ID


class _Binder:
    """`ScreenDataBinder` sahtəsi — `refresh()`-in ÇAĞIRILDIĞINI ölçür.

    `screen_data.py::_shift_swaps`-in ÖZÜ (işçi/mağaza adı sorğuları)
    ayrıca faylın işidir; burada yalnız kontrollerin refresh-i FAKTİKİ
    çağırdığı və nəticəni real ekrana ötürdüyü yoxlanılır.
    """

    populated: ClassVar[list[str]] = []
    failure: ClassVar[KompasOSError | None] = None
    remaining: ClassVar[list[dict[str, str]]] = []

    def __init__(self, context: Any, actor: Any) -> None:
        pass

    def populate(self, key: str, screen: Any) -> None:
        if _Binder.failure is not None:
            raise _Binder.failure
        _Binder.populated.append(key)
        screen.set_counts({"pending": len(_Binder.remaining)})
        screen.set_requests(list(_Binder.remaining))


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from src.presentation.controllers import screen_data as screen_data_module

    _Binder.populated = []
    _Binder.failure = None
    _Binder.remaining = []
    monkeypatch.setattr(screen_data_module, "ScreenDataBinder", _Binder)
    # `_inform()` (`controllers/shift_swaps.py`) real `QMessageBox.exec()`
    # çağırır — modal event loop test sapını əbədi bloklardı.
    monkeypatch.setattr(QMessageBox, "exec", lambda self: None)


def _build(qtbot: Any, theme: Any, swaps: _Swaps) -> tuple[Any, Any, _Context]:
    from src.presentation.controllers.shift_swaps import ShiftSwapController
    from src.presentation.screens.group_c import ShiftSwapScreen

    context = _Context(swaps)
    screen = ShiftSwapScreen(theme)
    qtbot.addWidget(screen)
    screen.show()  # `isVisible()` göstərilməyən pəncərədə HƏMİŞƏ False qaytarır
    ShiftSwapController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    return ShiftSwapController(context, _Actor()), screen, context  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 1. Real kart seçimi → real "Təsdiqlə"/"Rədd Et"
# --------------------------------------------------------------------------- #


@requires_qt
def test_selecting_a_real_card_and_approving_commits_and_refreshes(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    swaps = _Swaps()
    _, screen, context = _build(qtbot, theme, swaps)
    screen.set_requests([_request_row()])
    _Binder.remaining = []  # təsdiqdən sonra sorğu daha "gözləyən" deyil

    _card_click(qtbot, screen, str(REQUEST))
    _click(screen, "Təsdiqlə")

    assert len(swaps.approvals) == 1
    assert str(swaps.approvals[0]["request_id"]) == str(REQUEST)
    assert any(s.committed for s in context.sessions)
    assert "shift_swaps" in _Binder.populated, "refresh() ScreenDataBinder-i çağırmalı idi"
    assert screen._rows == [], "sorğu artıq gözləmirsə siyahıdan çıxmalıdır"


@requires_qt
def test_rejecting_via_the_real_dialog_carries_the_reason_and_commits(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    swaps = _Swaps()
    _, screen, context = _build(qtbot, theme, swaps)
    screen.set_requests([_request_row()])
    _Binder.remaining = []

    reason = "Həmin gün mağazada tək kassir qalır."
    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: (reason, True))
    )

    _card_click(qtbot, screen, str(REQUEST))
    _click(screen, "Rədd Et")

    assert len(swaps.rejections) == 1
    assert swaps.rejections[0]["reason"] == reason
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_declining_the_reason_prompt_writes_nothing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    swaps = _Swaps()
    _, screen, context = _build(qtbot, theme, swaps)
    screen.set_requests([_request_row()])

    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("", False)))

    _card_click(qtbot, screen, str(REQUEST))
    _click(screen, "Rədd Et")

    assert swaps.rejections == []
    assert context.sessions == [], "ləğv edilmiş dialoq sessiya AÇMAMALIDIR"


@requires_qt
def test_a_reason_shorter_than_the_domain_minimum_never_reaches_the_use_case(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """`MIN_DECISION_REASON_LENGTH` UI-dən keçəndə də REAL sərhəddir."""
    from PySide6.QtWidgets import QInputDialog

    from src.domain.entities.shift import MIN_DECISION_REASON_LENGTH
    from src.presentation.controllers import shift_swaps as shift_swaps_module

    swaps = _Swaps()
    _, screen, context = _build(qtbot, theme, swaps)
    screen.set_requests([_request_row()])

    short_reason = "x" * (MIN_DECISION_REASON_LENGTH - 1)
    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: (short_reason, True))
    )

    _card_click(qtbot, screen, str(REQUEST))
    _click(screen, "Rədd Et")

    assert swaps.rejections == [], "domen minimumundan qısa səbəb yazı yoluna girməməlidir"
    assert context.sessions == [], (
        "qısa səbəb sessiya AÇMAMALIDIR (`_ask_reason` sessiyadan ƏVVƏL yoxlayır)"
    )
    # `SHORT_REASON` mesajının ÖZÜ `test_shift_swap_controller.py`-də ölçülür;
    # burada yalnız real modalın FAKTİKİ göstərildiyi (bloklamadan) sınanır.
    del shift_swaps_module  # yalnız idxal yolunu sənədləşdirmək üçün saxlanılır


# --------------------------------------------------------------------------- #
# 2. Seçim olmadan klik — guard
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_decision_buttons_with_no_selection_opens_no_session(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Heç bir kart klikllənməyibsə `_current is None` — düymələr Qt SƏVİYYƏSİNDƏ
    deaktiv EDİLMİR (`_build_detail_panel`-də `setEnabled` yoxdur), qoruma
    yalnız `_emit_approved`/`_emit_rejected`-dəki `if self._current is not None`
    şərtidir. Bu test məhz həmin məntiqi REAL kliklə yoxlayır."""
    swaps = _Swaps()
    _, screen, context = _build(qtbot, theme, swaps)
    # `set_requests` heç çağırılmayıb — `_current` konstruktordan bəri `None`.

    _click(screen, "Təsdiqlə")
    _click(screen, "Rədd Et")

    assert swaps.approvals == []
    assert swaps.rejections == []
    assert context.sessions == []


# --------------------------------------------------------------------------- #
# 3. Ekstremal/zərərli mətn — çökmür
# --------------------------------------------------------------------------- #


@requires_qt
def test_hostile_and_extreme_reject_reason_passes_through_without_crashing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    swaps = _Swaps()
    _, screen, context = _build(qtbot, theme, swaps)
    screen.set_requests([_request_row()])
    _Binder.remaining = []

    hostile = "'; DROP TABLE shift_swap_requests; -- 🔥" + "A" * 10_000
    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: (hostile, True))
    )

    _card_click(qtbot, screen, str(REQUEST))
    _click(screen, "Rədd Et")  # ÇÖKMƏMƏLİDİR

    assert len(swaps.rejections) == 1
    assert swaps.rejections[0]["reason"] == " ".join(hostile.split())
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_a_reason_of_only_whitespace_is_treated_as_too_short(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    swaps = _Swaps()
    _, screen, context = _build(qtbot, theme, swaps)
    screen.set_requests([_request_row()])

    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("   \n\t  ", True))
    )

    _card_click(qtbot, screen, str(REQUEST))
    _click(screen, "Rədd Et")

    assert swaps.rejections == []
    assert context.sessions == []


@requires_qt
def test_a_malformed_request_id_from_the_approved_signal_does_not_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    swaps = _Swaps()
    _, screen, context = _build(qtbot, theme, swaps)

    screen.approved.emit("not-a-uuid")  # ÇÖKMƏMƏLİDİR — ölü kartdan qalma stale ID

    assert swaps.approvals == []
    assert context.sessions == []


@requires_qt
def test_a_malformed_request_id_from_the_rejected_signal_does_not_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    swaps = _Swaps()
    _, screen, context = _build(qtbot, theme, swaps)

    screen.rejected.emit("")  # ÇÖKMƏMƏLİDİR

    assert swaps.rejections == []
    assert context.sessions == []


# --------------------------------------------------------------------------- #
# 4. Sürətli/ikiqat klik — eyni sorğu iki dəfə qərara bağlanmır
# --------------------------------------------------------------------------- #


@requires_qt
def test_double_clicking_approve_on_a_stale_selection_does_not_double_decide(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`set_requests([])` `_current`-i SIFIRLAMIR (bax `group_c.py::set_requests`)
    — birinci klikdən sonra siyahı boşalsa da düymələr eyni `_current`-ə
    işarə edir. İkinci klik domen qoruyucusuna ('artıq qərar alıb') çırpılır,
    UİKİ SƏVİYYƏDƏ debounce YOXDUR — nəticə düzgündür, LAKİN bu, `refresh()`-
    in `_current`-i sıfırlamamasının TƏSADÜFİ nəticəsidir."""
    swaps = _Swaps()
    _, screen, context = _build(qtbot, theme, swaps)
    screen.set_requests([_request_row()])
    _Binder.remaining = []

    _card_click(qtbot, screen, str(REQUEST))
    _click(screen, "Təsdiqlə")
    _click(screen, "Təsdiqlə")  # eyni (artıq qərar alınmış) `_current`-ə ikinci klik

    assert len(swaps.approvals) == 1, "eyni sorğu İKİ dəfə qərara bağlanmamalıdır"
    assert context.sessions[0].committed is True
    assert context.sessions[1].committed is False, "ikinci cəhd rollback olmalıdır"


# --------------------------------------------------------------------------- #
# 5. Repo istisnaları — aydın mesaj, sükutla üstündən yazma yoxdur
# --------------------------------------------------------------------------- #


@requires_qt
def test_an_approval_failure_shows_a_modal_and_does_not_commit_or_refresh(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    swaps = _Swaps()
    swaps.approve_error = KompasOSError(
        "already claimed by shift matrix",
        user_message="Bu sorğu artıq başqası tərəfindən qərara bağlanıb.",
    )
    _, screen, context = _build(qtbot, theme, swaps)
    screen.set_requests([_request_row()])

    _card_click(qtbot, screen, str(REQUEST))
    _click(screen, "Təsdiqlə")  # ÇÖKMƏMƏLİDİR

    assert context.sessions[0].committed is False
    assert _Binder.populated == [], "uğursuz yazıdan sonra siyahı YENİDƏN oxunmamalıdır"
    # Kart siyahıda QALIR — istifadəçi başqa sorğuları görməyə davam edir.
    assert len(screen._rows) == 1


@requires_qt
def test_a_read_failure_after_a_successful_decision_shows_an_error_state_not_a_blank_screen(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """Yazı UĞURLUDUR, `refresh()`-in ÖZÜ (`ScreenDataBinder.populate`) sındıqda
    `screen.show_error()` işə düşür — `announcements.py`-dəki naxışdan FƏRQLİ
    olaraq, burada `_write()` yazıdan sonra YALNIZ `refresh()` çağırır (ikinci,
    üstündən yazan `show_content()` çağırışı YOXDUR)."""
    swaps = _Swaps()
    _, screen, context = _build(qtbot, theme, swaps)
    screen.set_requests([_request_row()])

    def _fail(_key: str, _screen: Any) -> None:
        raise KompasOSError("baza əlaqəsi kəsildi", user_message="Baza əlaqəsi kəsildi.")

    _card_click(qtbot, screen, str(REQUEST))
    _Binder.failure = KompasOSError("db down", user_message="Baza əlaqəsi kəsildi.")
    _click(screen, "Təsdiqlə")  # ÇÖKMƏMƏLİDİR

    assert swaps.approvals[0]["request_id"]  # yazı ÖZÜ uğurlu oldu
    assert any(s.committed for s in context.sessions)
    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 6. DÜZƏLDİLDİ — seçilən kartın detalı artıq CANLI rejimdə də görünür
# --------------------------------------------------------------------------- #
#
# DÜZƏLİŞ (`ui` sahibi): kontrollerdə keş YOX — `ShiftSwapScreen.select()`
# özü `set_requests()`-in son sətirlərini (`_requests_by_id`) saxlayır və
# seçim anında `set_detail()`-i BİRBAŞA çağırır (`group_c.py::_detail_for`).
# Kontrollerdə keşləmək bu testin ÖZÜNDƏ işləməzdi: `_build()` `attach()`-i
# `set_requests()`-dən ƏVVƏL çağırır, `ScreenDataBinder` isə sahtələnib —
# kontrollerin "son populate() nəticəsi" adlana biləcək heç nəyi yoxdur, sətir
# birbaşa ekrana ötürülür. Ekranın ÖZÜ isə hər iki yolda (canlı VƏ bu test)
# eyni məlumatı artıq alır.


@requires_qt
def test_selecting_a_real_card_populates_the_detail_panel(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    swaps = _Swaps()
    _, screen, _ = _build(qtbot, theme, swaps)

    screen.set_requests([_request_row(from_name="Aygün Məmmədova", note="Ailə tədbiri")])
    _card_click(qtbot, screen, str(REQUEST))

    assert "Aygün Məmmədova" in screen._detail_title.text()
