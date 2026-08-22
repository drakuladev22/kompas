"""`DailyRosterScreen` ↔ `DailyRosterController` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, dördüncü beşlik)
──────────────────────────────────────────────────────────────────────────────
`test_daily_roster_controller.py` sahtə `_Screen` sinifi ilə ölçür (siqnal +
metod cütü) — REAL `DailyRosterScreen`, REAL `[Tabeli Təsdiqlə]`/
`[Qaralama Saxla]` düymələri, REAL qeyd sahəsi (`QPlainTextEdit`) heç vaxt
qurulmur. Burada hər ikisi FAKTİKİ qurulur və REAL klikllənir — naxış
`test_open_shift_screen_e2e.py`/`test_tasks_screen_e2e.py` ilə eynidir.

`refresh()` `ScreenDataBinder`-dən keçir (`controllers/daily_roster.py::
refresh` başlığı). Onu REAL DB olmadan ölçmək üçün `fake_binder` fixture-u
ilə `screen_data_module.ScreenDataBinder` sahtələnir (`test_tasks_screen_e2e.
py`-dəki qərarla eyni) — YALNIZ bir test bundan İSTİSNADIR, aşağıya bax.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
STORE = uuid.uuid4()


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


def _set_note(screen: Any, text: str) -> None:
    """`DailyRosterScreen._note` xüsusidir (getter yalnız `manager_note()`) —
    real vidjeti tip üzrə tapıb REAL mətn yazırıq (setPlainText, `.value=` yox)."""
    from PySide6.QtWidgets import QPlainTextEdit

    note_field = screen.findChildren(QPlainTextEdit)[0]
    note_field.setPlainText(text)


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _DailyAttendance:
    """`session.daily_attendance` — YALNIZ yazı metodları (`confirm`,
    `save_draft_note`); `refresh()` bu fayldakı ƏKSƏR testlərdə `fake_binder`
    ilə əvəzləndiyi üçün `open_sheet` BURADA lazım deyil (real oxu yolu üçün
    ayrıca `_BrokenAttendance` var, aşağıdakı bölmə 3-ə bax)."""

    def __init__(
        self,
        *,
        confirm_failure: Exception | None = None,
        confirm_fail_from_call: int = 1,
        draft_failure: Exception | None = None,
    ) -> None:
        self.confirm_failure = confirm_failure
        self.confirm_fail_from_call = confirm_fail_from_call
        self.draft_failure = draft_failure
        self.confirmations: list[dict[str, Any]] = []
        self.drafts: list[dict[str, Any]] = []

    def confirm(self, **kwargs: Any) -> Any:
        attempt = len(self.confirmations) + 1
        if self.confirm_failure is not None and attempt >= self.confirm_fail_from_call:
            raise self.confirm_failure
        self.confirmations.append(kwargs)
        return object()

    def save_draft_note(self, **kwargs: Any) -> Any:
        if self.draft_failure is not None:
            raise self.draft_failure
        self.drafts.append(kwargs)
        return object()


class _Session:
    def __init__(self, attendance: _DailyAttendance) -> None:
        self.tenant_id = TENANT
        self.daily_attendance = attendance
        self.uow = SimpleNamespace(employees=SimpleNamespace(get=lambda _eid: None))
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(self, attendance: _DailyAttendance) -> None:
        self._attendance = attendance
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(self._attendance)
        self.sessions.append(created)
        yield created


class _Actor:
    def __init__(self, *, store_id: Any = STORE) -> None:
        self.id = uuid.uuid4()
        self.store_id = store_id


class _FakeBinder:
    """`screen_data.ScreenDataBinder`-in yerini tutur — `refresh()`-in ÇAĞIRDIĞINI
    ölçmək kifayətdir, real sorğu qatını (`_daily_roster`) BURADA yenidən
    qurmağa ehtiyac yoxdur (`test_tasks_screen_e2e.py`-dəki qərarla eyni)."""

    calls: ClassVar[list[str]] = []

    def __init__(self, context: Any, actor: Any) -> None:
        pass

    def populate(self, key: str, _screen: Any, **_kwargs: Any) -> None:
        _FakeBinder.calls.append(key)


@pytest.fixture(autouse=True)
def _capture_message_boxes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """`_inform()` REAL `QMessageBox.exec()` çağırır — modal event loop testi
    ƏBƏDİ BLOKLAYARDI. `question()` (təsdiq modalı) BURADA TOXUNULMUR — hər
    test onu Yes/No ilə ayrıca patch edir, çünki cavab testdən-testə dəyişir."""
    from PySide6.QtWidgets import QMessageBox

    shown: list[tuple[str, str]] = []

    def fake_exec(self: Any) -> None:
        shown.append((self.windowTitle(), self.text()))

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    return shown


@pytest.fixture
def fake_binder(monkeypatch: pytest.MonkeyPatch) -> type[_FakeBinder]:
    from src.presentation.controllers import screen_data as screen_data_module

    _FakeBinder.calls = []
    monkeypatch.setattr(screen_data_module, "ScreenDataBinder", _FakeBinder)
    return _FakeBinder


# --------------------------------------------------------------------------- #
# 1. Qaralama Saxla — real klik, real qeyd sahəsi
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_qaralama_saxla_saves_the_real_note_and_refreshes(
    qtbot, theme, fake_binder
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.daily_roster import DailyRosterController
    from src.presentation.screens.group_c import DailyRosterScreen

    attendance = _DailyAttendance()
    context = _Context(attendance)
    screen = DailyRosterScreen(theme)
    qtbot.addWidget(screen)
    _set_note(screen, "Kassa növbəsi dəyişdirildi.")
    DailyRosterController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Qaralama Saxla")

    assert len(attendance.drafts) == 1
    assert attendance.drafts[0]["note"] == "Kassa növbəsi dəyişdirildi."
    assert attendance.drafts[0]["store_id"] == STORE
    assert context.sessions[0].committed is True
    assert fake_binder.calls == ["daily_roster"], "refresh() ScreenDataBinder-i çağırmalı idi"


@requires_qt
def test_qaralama_saxla_never_opens_the_real_confirmation_modal(
    qtbot, theme, fake_binder, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Modul başlığının iddiası: qaralama GERİ QAYTARILA BİLƏNDİR, modal YOXDUR."""
    from PySide6.QtWidgets import QMessageBox

    from src.presentation.controllers.daily_roster import DailyRosterController
    from src.presentation.screens.group_c import DailyRosterScreen

    def _fail_if_called(*_a: Any, **_k: Any) -> Any:
        pytest.fail("Qaralama Saxla təsdiq modalı açmamalıdır")

    monkeypatch.setattr(QMessageBox, "question", staticmethod(_fail_if_called))

    attendance = _DailyAttendance()
    context = _Context(attendance)
    screen = DailyRosterScreen(theme)
    qtbot.addWidget(screen)
    _set_note(screen, "qeyd")
    DailyRosterController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Qaralama Saxla")

    assert len(attendance.drafts) == 1


@requires_qt
def test_hostile_and_extreme_text_in_the_real_note_field_does_not_crash(
    qtbot, theme, fake_binder
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.daily_roster import DailyRosterController
    from src.presentation.screens.group_c import DailyRosterScreen

    attendance = _DailyAttendance()
    context = _Context(attendance)
    screen = DailyRosterScreen(theme)
    qtbot.addWidget(screen)
    hostile = "'; DROP TABLE daily_attendance_sheets; -- 🔥" + "A" * 10_000
    _set_note(screen, hostile)
    DailyRosterController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Qaralama Saxla")  # ÇÖKMƏMƏLİDİR

    assert len(attendance.drafts) == 1
    assert attendance.drafts[0]["note"] == hostile


@requires_qt
def test_qaralama_saxla_with_whitespace_only_note_still_writes_the_raw_text(
    qtbot, theme, fake_binder
) -> None:  # type: ignore[no-untyped-def]
    """Kontroller/ekran QATI heç bir `strip()`/minimum uzunluq YOXLAMASI etmir —
    boş görünən qeyd domenə OLDUĞU KİMİ ötürülür. Domendəki minimum-uzunluq
    qaydası (əgər varsa) BURADA ÖLÇÜLMÜR (`tests/unit/test_daily_attendance.py`-nin
    işidir); bu test YALNIZ ekran qatının süzgəcsiz ötürdüyünü sənədləşdirir."""
    from src.presentation.controllers.daily_roster import DailyRosterController
    from src.presentation.screens.group_c import DailyRosterScreen

    attendance = _DailyAttendance()
    context = _Context(attendance)
    screen = DailyRosterScreen(theme)
    qtbot.addWidget(screen)
    _set_note(screen, "    ")
    DailyRosterController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Qaralama Saxla")  # ÇÖKMƏMƏLİDİR

    assert attendance.drafts[0]["note"] == "    "


@requires_qt
def test_qaralama_saxla_with_no_store_shows_a_real_warning_and_writes_nothing(
    qtbot, theme, fake_binder, _capture_message_boxes: list[tuple[str, str]]
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.daily_roster import (
        NO_STORE_MESSAGE,
        DailyRosterController,
    )
    from src.presentation.screens.group_c import DailyRosterScreen

    attendance = _DailyAttendance()
    context = _Context(attendance)
    screen = DailyRosterScreen(theme)
    qtbot.addWidget(screen)
    DailyRosterController(context, _Actor(store_id=None)).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Qaralama Saxla")

    assert attendance.drafts == []
    assert context.sessions == []
    assert _capture_message_boxes[-1] == ("Qaralama saxlanmadı", NO_STORE_MESSAGE)


@requires_qt
def test_draft_write_failure_shows_the_real_domain_message_and_keeps_the_sheet(
    qtbot, theme, fake_binder, _capture_message_boxes: list[tuple[str, str]]
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.daily_roster import DailyRosterController
    from src.presentation.screens.group_c import DailyRosterScreen

    attendance = _DailyAttendance(
        draft_failure=KompasOSError("db down", user_message="Baza əlaqəsi kəsildi.")
    )
    context = _Context(attendance)
    screen = DailyRosterScreen(theme)
    qtbot.addWidget(screen)
    _set_note(screen, "qeyd")
    DailyRosterController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Qaralama Saxla")  # ÇÖKMƏMƏLİDİR

    assert attendance.drafts == []
    assert context.sessions[0].committed is False
    assert _capture_message_boxes[-1] == ("Qaralama saxlanmadı", "Baza əlaqəsi kəsildi.")
    assert fake_binder.calls == [], "uğursuz yazıdan sonra refresh() ÇAĞIRILMAMALIDIR"


# --------------------------------------------------------------------------- #
# 2. Tabeli Təsdiqlə — real klik, real təsdiq modalı
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_tabeli_tesdiqle_asks_a_real_confirmation_then_commits(
    qtbot, theme, fake_binder, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    from src.presentation.controllers.daily_roster import DailyRosterController
    from src.presentation.screens.group_c import DailyRosterScreen

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    attendance = _DailyAttendance()
    context = _Context(attendance)
    screen = DailyRosterScreen(theme)
    qtbot.addWidget(screen)
    _set_note(screen, "Gecikmə səbəbi izah olundu.")
    DailyRosterController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Tabeli Təsdiqlə")

    assert len(attendance.confirmations) == 1
    assert attendance.confirmations[0]["store_id"] == STORE
    assert attendance.confirmations[0]["manager_note"] == "Gecikmə səbəbi izah olundu."
    assert "sheet_date" not in attendance.confirmations[0]
    assert context.sessions[0].committed is True
    assert fake_binder.calls == ["daily_roster"]


@requires_qt
def test_declining_the_real_confirmation_modal_writes_nothing(
    qtbot, theme, fake_binder, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    from src.presentation.controllers.daily_roster import DailyRosterController
    from src.presentation.screens.group_c import DailyRosterScreen

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )
    attendance = _DailyAttendance()
    context = _Context(attendance)
    screen = DailyRosterScreen(theme)
    qtbot.addWidget(screen)
    DailyRosterController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Tabeli Təsdiqlə")

    assert attendance.confirmations == []
    assert context.sessions == []
    assert fake_binder.calls == [], "imtinadan sonra refresh() ÇAĞIRILMAMALIDIR"


@requires_qt
def test_tabeli_tesdiqle_with_no_store_never_opens_the_confirmation_modal(
    qtbot,
    theme,
    fake_binder,
    monkeypatch: pytest.MonkeyPatch,
    _capture_message_boxes: list[tuple[str, str]],
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    from src.presentation.controllers.daily_roster import (
        NO_STORE_MESSAGE,
        DailyRosterController,
    )
    from src.presentation.screens.group_c import DailyRosterScreen

    def _fail_if_called(*_a: Any, **_k: Any) -> Any:
        pytest.fail("mağazası olmayan aktor üçün təsdiq modalı AÇILMAMALIDIR")

    monkeypatch.setattr(QMessageBox, "question", staticmethod(_fail_if_called))
    attendance = _DailyAttendance()
    context = _Context(attendance)
    screen = DailyRosterScreen(theme)
    qtbot.addWidget(screen)
    DailyRosterController(context, _Actor(store_id=None)).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Tabeli Təsdiqlə")

    assert attendance.confirmations == []
    assert context.sessions == []
    assert _capture_message_boxes[-1] == ("Tabel təsdiqlənmədi", NO_STORE_MESSAGE)


@requires_qt
def test_a_second_confirm_after_the_sheet_is_already_signed_is_rejected_not_crashed(
    qtbot,
    theme,
    fake_binder,
    monkeypatch: pytest.MonkeyPatch,
    _capture_message_boxes: list[tuple[str, str]],
) -> None:  # type: ignore[no-untyped-def]
    """`_require_open` domen qoruması (`controllers/daily_roster.py` başlığı):
    ikinci imza cəhdi İKİNCİ dəfə uğur qazanmamalıdır. UI qatı düyməni
    yazıdan sonra DEAKTİV ETMİR (bax aşağıdakı tapıntı) — qorunma YALNIZ
    domen səviyyəsindədir və bu test məhz onu doğrulayır: ikinci klik
    çökmür, AÇIQ mesaj göstərir, sessiya `commit()` olunmur."""
    from PySide6.QtWidgets import QMessageBox

    from src.presentation.controllers.daily_roster import DailyRosterController
    from src.presentation.screens.group_c import DailyRosterScreen

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    attendance = _DailyAttendance(
        confirm_failure=KompasOSError(
            "sheet already confirmed", user_message="Tabel artıq imzalanıb."
        ),
        confirm_fail_from_call=2,
    )
    context = _Context(attendance)
    screen = DailyRosterScreen(theme)
    qtbot.addWidget(screen)
    DailyRosterController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Tabeli Təsdiqlə")
    _click(screen, "Tabeli Təsdiqlə")  # ÇÖKMƏMƏLİDİR

    assert len(attendance.confirmations) == 1, "ikinci cəhd sətri İKİNCİ dəfə yazmamalıdır"
    assert context.sessions[0].committed is True
    assert context.sessions[1].committed is False
    assert _capture_message_boxes[-1] == ("Tabel təsdiqlənmədi", "Tabel artıq imzalanıb.")


@requires_qt
def test_a_domain_permission_rejection_on_confirm_shows_a_clear_message_not_a_crash(
    qtbot,
    theme,
    fake_binder,
    monkeypatch: pytest.MonkeyPatch,
    _capture_message_boxes: list[tuple[str, str]],
) -> None:  # type: ignore[no-untyped-def]
    """`FILL_ATTENDANCE_FLAG` yoxlaması `DailyAttendanceSheetUseCase.confirm()`-
    dədir (`use_cases/daily_attendance.py:273`), EKRANDA DEYİL — `[Tabeli
    Təsdiqlə]` düyməsi flag-i olmayan aktor üçün DƏ render olunur (bax
    tapıntı #2, aşağı). Klik nəticəsi isə fail-closed-dur: domen
    `SheetPermissionError` atır, kontroller onu tutub AÇIQ mesaj göstərir —
    ÇÖKMÜR, sükutla uğur da göstərmir."""
    from PySide6.QtWidgets import QMessageBox

    from src.presentation.controllers.daily_roster import DailyRosterController
    from src.presentation.screens.group_c import DailyRosterScreen

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    attendance = _DailyAttendance(
        confirm_failure=KompasOSError(
            "«can_fill_daily_attendance» səlahiyyəti yoxdur",
            user_message="Bu tabelə giriş səlahiyyətiniz yoxdur.",
        ),
        confirm_fail_from_call=1,
    )
    context = _Context(attendance)
    screen = DailyRosterScreen(theme)
    qtbot.addWidget(screen)
    DailyRosterController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Tabeli Təsdiqlə")  # ÇÖKMƏMƏLİDİR

    assert attendance.confirmations == []
    assert context.sessions[0].committed is False
    assert _capture_message_boxes[-1] == (
        "Tabel təsdiqlənmədi",
        "Bu tabelə giriş səlahiyyətiniz yoxdur.",
    )


# --------------------------------------------------------------------------- #
# 3. `refresh()` REAL `ScreenDataBinder`-lə — QA-FULL tapıntısı, DÜZƏLDİLDİ
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_real_read_failure_now_reaches_the_real_retry_screen(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """DÜZƏLİŞDƏN SONRA (bax `screen_data.py::populate` başlığı, `reraise`
    parametri): `DailyRosterController.refresh()` indi `populate(...,
    reraise=True)` çağırır və REAL `ScreenDataBinder.populate()` `Kompas
    OSError`-u ARTIQ udmur, yenidən atır. Əvvəl bu fayldakı eyni test
    ("ölü kod" tapıntısı) `switcher().current_state() == "content"` +
    bölmə-banner gözləyirdi; İNDİ TƏRSİNƏ — ekran `"error"` vəziyyətinə
    keçir və `on_retry` funksional işləyir. Bu test heç bir sahtə
    `ScreenDataBinder` olmadan (REAL sinif) bunu sübut edir."""
    from src.presentation.controllers.daily_roster import DailyRosterController
    from src.presentation.screens.group_c import DailyRosterScreen

    class _BrokenAttendance:
        def __init__(self) -> None:
            self.calls = 0

        def open_sheet(self, **_kwargs: Any) -> Any:
            self.calls += 1
            raise KompasOSError("query failed", user_message="Baza əlaqəsi kəsildi.")

    class _Session:
        tenant_id = TENANT

        def __init__(self, attendance: _BrokenAttendance) -> None:
            self.daily_attendance = attendance
            self.uow = SimpleNamespace(employees=SimpleNamespace(get=lambda _eid: None))

        def commit(self) -> None:
            pass

    class _Context:
        def __init__(self, attendance: _BrokenAttendance) -> None:
            self._attendance = attendance

        @contextmanager
        def session(self, *, user_id: Any = None) -> Any:
            yield _Session(self._attendance)

    screen = DailyRosterScreen(theme)
    qtbot.addWidget(screen)
    attendance = _BrokenAttendance()
    controller = DailyRosterController(_Context(attendance), _Actor())  # type: ignore[arg-type]

    controller.refresh(screen)  # type: ignore[arg-type]  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error", (
        "REAL oxu xətası indi 'error' vəziyyətinə keçməlidir — reraise=True fix-i"
    )
    assert screen.section_errors() == (), "tam-ekran xəta göstərilirsə bölmə banneri LAZIM DEYİL"

    # `on_retry` HƏQİQƏTƏN işlək düymədir — real klik `refresh()`-i TƏKRAR çağırır.
    from PySide6.QtWidgets import QPushButton

    retry = next(b for b in screen.findChildren(QPushButton) if b.text() == "Yenidən Cəhd Et")
    retry.click()

    assert attendance.calls == 2, "'Yenidən Cəhd Et' real retry funksiyasını çağırmalıdır"
    assert screen.switcher().current_state() == "error"
