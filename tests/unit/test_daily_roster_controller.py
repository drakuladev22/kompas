"""`DailyRosterController` yazı yolu (`controllers/daily_roster.py`).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ
──────────────────────────────────────────────────────────────────────────────
Kontroller ÜMUMİYYƏTLƏ yox idi: `DailyRosterScreen` `[Tabeli Təsdiqlə]` və
`[Qaralama Saxla]` düymələrini çəkirdi, siqnal yayırdı, `DailyAttendanceSheet
UseCase.confirm()` isə tam işlək idi — lakin ekran `app.py::_dispatch_attach`
cədvəlində yox idi. Mağaza meneceri düyməni basırdı, heç nə olmurdu.

Ölçülən YALNIZ kontrollerin öz məsuliyyətidir: təsdiq modalından İMTİNA
halında HEÇ NƏ yazılmaması, `manager_note()`-un imza ilə birlikdə getməsi,
`sheet_date`-in EKRANDA hesablanmaması (gecə yarısı sürüşməsi) və yazıdan
sonra tabelin yenidən oxunması. Use case-in ÖZÜ (`FILL_ATTENDANCE_FLAG`,
uyğunsuzluq bildirişi, `overtime_log`) `test_daily_attendance.py`-nin işidir.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, ClassVar

import pytest

from src.presentation.controllers import daily_roster as daily_roster_module
from src.presentation.controllers import screen_data as screen_data_module
from src.presentation.controllers.daily_roster import DailyRosterController
from src.shared.exceptions import KompasOSError

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
STORE = uuid.uuid4()


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
    def __init__(self, *, note: str = "Gecikmə səbəbi izah olundu.") -> None:
        self.approve_requested = _Signal()
        self.draft_saved = _Signal()
        self._note = note
        self.errors: list[tuple[str, str]] = []
        self.retries: list[Any] = []

    def manager_note(self) -> str:
        return self._note

    def show_error(self, *, title: str, message: str, on_retry: Any = None, **_: Any) -> None:
        self.errors.append((title, message))
        self.retries.append(on_retry)


class _DailyAttendance:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.confirmations: list[dict[str, Any]] = []
        self.drafts: list[dict[str, Any]] = []

    def confirm(self, **kwargs: Any) -> Any:
        if self.failure is not None:
            raise self.failure
        self.confirmations.append(kwargs)
        return object()

    def save_draft_note(self, **kwargs: Any) -> Any:
        if self.failure is not None:
            raise self.failure
        self.drafts.append(kwargs)
        return object()


class _Session:
    def __init__(self, *, attendance: _DailyAttendance) -> None:
        self.tenant_id = TENANT
        self.daily_attendance = attendance
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(self, *, attendance: _DailyAttendance) -> None:
        self._attendance = attendance
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(attendance=self._attendance)
        self.sessions.append(created)
        yield created


class _Actor:
    def __init__(self, *, store_id: Any = STORE) -> None:
        self.id = uuid.uuid4()
        self.store_id = store_id


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
        daily_roster_module,
        "_inform",
        lambda _screen, title, message: shown.append((title, message)),
    )
    monkeypatch.setattr(daily_roster_module, "_confirm", lambda _screen, _question: True)
    return shown


def _build(
    *, failure: Exception | None = None, store_id: Any = STORE, note: str = "Qeyd"
) -> tuple[Any, _Screen, _Context, _DailyAttendance]:
    attendance = _DailyAttendance(failure=failure)
    context = _Context(attendance=attendance)
    controller = DailyRosterController(context, _Actor(store_id=store_id))  # type: ignore[arg-type]
    screen = _Screen(note=note)
    controller.attach(screen)  # type: ignore[arg-type]
    return controller, screen, context, attendance


# --------------------------------------------------------------------------- #
# Təsdiq
# --------------------------------------------------------------------------- #


def test_confirm_writes_commits_and_rereads() -> None:
    """Qüsurun ÖZÜ: bu siqnalı heç kim dinləmirdi."""
    _, screen, context, attendance = _build(note="Kassa növbəsi dəyişdirildi.")

    screen.approve_requested.emit()

    assert len(attendance.confirmations) == 1
    assert attendance.confirmations[0]["store_id"] == STORE
    assert attendance.confirmations[0]["manager_note"] == "Kassa növbəsi dəyişdirildi."
    assert context.sessions[0].committed is True
    assert _Binder.populated == ["daily_roster"]


def test_confirm_never_computes_the_sheet_date_in_the_screen_layer() -> None:
    """`sheet_date` ÖTÜRÜLMÜR — defolt `Clock`-un günüdür (gecə yarısı sürüşməsi)."""
    _, screen, _, attendance = _build()

    screen.approve_requested.emit()

    assert "sheet_date" not in attendance.confirmations[0]


def test_declining_the_modal_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """İmza GERİ QAYTARILA BİLMİR — imtina halında sessiya belə açılmır."""
    monkeypatch.setattr(daily_roster_module, "_confirm", lambda _screen, _question: False)
    _, screen, context, attendance = _build()

    screen.approve_requested.emit()

    assert context.sessions == []
    assert attendance.confirmations == []
    assert _Binder.populated == []


def test_an_actor_without_a_store_is_told_why(_isolate: list[tuple[str, str]]) -> None:
    """Oxu yolu boş siyahı göstərir — yazı yolu SƏBƏBİ deməlidir."""
    _, screen, context, _ = _build(store_id=None)

    screen.approve_requested.emit()

    assert context.sessions == []
    assert _isolate[0][1] == daily_roster_module.NO_STORE_MESSAGE


# --------------------------------------------------------------------------- #
# Qaralama
# --------------------------------------------------------------------------- #


def test_draft_saves_the_note_without_confirming(monkeypatch: pytest.MonkeyPatch) -> None:
    """Qaralama geri qaytarıla biləndir — TƏSDİQ MODALI YOXDUR."""
    asked: list[str] = []
    monkeypatch.setattr(
        daily_roster_module, "_confirm", lambda _s, question: asked.append(question) or True
    )
    _, screen, context, attendance = _build()

    screen.draft_saved.emit("Səhər növbəsi 30 dəqiqə gecikdi.")

    assert asked == []
    assert attendance.confirmations == []
    assert attendance.drafts[0]["note"] == "Səhər növbəsi 30 dəqiqə gecikdi."
    assert context.sessions[0].committed is True
    assert _Binder.populated == ["daily_roster"]


def test_draft_without_a_store_is_told_why(_isolate: list[tuple[str, str]]) -> None:
    _, screen, context, attendance = _build(store_id=None)

    screen.draft_saved.emit("qeyd")

    assert context.sessions == []
    assert attendance.drafts == []
    assert _isolate[0][0] == "Qaralama saxlanmadı"


# --------------------------------------------------------------------------- #
# Uğursuzluq
# --------------------------------------------------------------------------- #


def test_a_failed_confirm_keeps_the_sheet_on_screen(_isolate: list[tuple[str, str]]) -> None:
    """Uğursuz imza sətirləri etibarsız etmir — modal, `show_error` DEYİL."""
    _, screen, context, attendance = _build(failure=KompasOSError("səlahiyyət yoxdur"))

    screen.approve_requested.emit()

    assert attendance.confirmations == []
    assert context.sessions[0].committed is False
    assert _Binder.populated == []
    assert screen.errors == []
    assert len(_isolate) == 1


def test_a_read_failure_offers_a_working_retry() -> None:
    """UI-R4-01: oxu xətasında düymə HƏQİQƏTƏN bağlıdır."""
    controller, screen, _, _ = _build()
    _Binder.failure = KompasOSError("baza əlçatmazdır")

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.errors[0][0] == "Tabel oxuna bilmədi"
    assert callable(screen.retries[0])
