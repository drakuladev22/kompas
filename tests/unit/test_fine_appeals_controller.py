"""`FineAppealInboxController` yazı yolu (`controllers/fine_appeals.py`).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ
──────────────────────────────────────────────────────────────────────────────
Kontroller ÜMUMİYYƏTLƏ yox idi: ekran `accepted`/`rejected` yayırdı, use case
`approve`/`reject` tam işlək idi, `app.py::_dispatch_attach` cədvəlində isə bu
ekran heç vaxt olmamışdı. HR_Admin qərarın səbəbini yazır, «Qəbul Et» basır və
HEÇ NƏ olmurdu — etiraz REAL PUL kəsintisinə qarşı olduğu üçün bu, sükutla
itən bir maddi qərardır.

Burada use case-in ÖZÜ (72 saatlıq pəncərə, `Fine.reverse`, audit) TƏKRAR
yoxlanmır — o, `test_use_cases.py`/`test_entities.py`-nin işidir. Ölçülən
YALNIZ kontrollerin öz məsuliyyətidir: qısa səbəbi sessiya AÇMADAN qaytarmaq,
səbəbi domenlə EYNİ qaydada normallaşdırmaq, `commit()`-i doğru sırada
çağırmaq və yazıdan SONRA siyahını yenidən oxumaq.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, ClassVar

import pytest

from src.domain.entities.appeal import MIN_DECISION_NOTE_LENGTH
from src.presentation.controllers import fine_appeals as fine_appeals_module
from src.presentation.controllers import screen_data as screen_data_module
from src.presentation.controllers.fine_appeals import FineAppealInboxController
from src.shared.exceptions import KompasOSError

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
APPEAL = uuid.uuid4()


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _Signal:
    """`Signal.connect(...)` + `emit(...)` — Qt olmadan."""

    def __init__(self) -> None:
        self._slots: list[Any] = []

    def connect(self, slot: Any) -> None:
        self._slots.append(slot)

    def emit(self, *args: Any) -> None:
        for slot in self._slots:
            slot(*args)

    @property
    def connected(self) -> bool:
        return bool(self._slots)


class _Screen:
    """Minimal `FineAppealInboxScreen` əvəzi."""

    def __init__(self) -> None:
        self.accepted = _Signal()
        self.rejected = _Signal()
        self.errors: list[tuple[str, str]] = []
        self.retries: list[Any] = []

    def show_error(self, *, title: str, message: str, on_retry: Any = None, **_: Any) -> None:
        self.errors.append((title, message))
        self.retries.append(on_retry)


class _FineAppeals:
    """`session.fine_appeals` — `FineAppealUseCase` sahtəsi."""

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
    def __init__(self, *, appeals: _FineAppeals) -> None:
        self.tenant_id = TENANT
        self.fine_appeals = appeals
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    """Hər `with` YENİ sessiya açır — bölmə 6: «kontroller sessiyanı SAXLAMIR»."""

    def __init__(self, *, appeals: _FineAppeals) -> None:
        self._appeals = appeals
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(appeals=self._appeals)
        self.sessions.append(created)
        yield created


class _Actor:
    id = uuid.uuid4()


class _Binder:
    """Sahtə `ScreenDataBinder` — `refresh()` çağırılıbmı."""

    populated: ClassVar[list[str]] = []
    failure: ClassVar[Exception | None] = None

    def __init__(self, context: Any, actor: Any) -> None:
        pass

    def populate(self, key: str, _screen: Any) -> None:
        if _Binder.failure is not None:
            raise _Binder.failure
        _Binder.populated.append(key)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Binder-i və modalı sahtələ — Qt bu testlərdə qalxmır."""
    _Binder.populated = []
    _Binder.failure = None
    monkeypatch.setattr(screen_data_module, "ScreenDataBinder", _Binder)
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        fine_appeals_module,
        "_inform",
        lambda _screen, title, message: shown.append((title, message)),
    )
    return shown


def _build(*, failure: Exception | None = None) -> tuple[Any, _Screen, _Context, _FineAppeals]:
    appeals = _FineAppeals(failure=failure)
    context = _Context(appeals=appeals)
    controller = FineAppealInboxController(context, _Actor())  # type: ignore[arg-type]
    screen = _Screen()
    controller.attach(screen)  # type: ignore[arg-type]
    return controller, screen, context, appeals


LONG_NOTE = "Sübut kifayət etmir, cərimə qüvvədə qalır."


# --------------------------------------------------------------------------- #
# Bağlantı
# --------------------------------------------------------------------------- #


def test_attach_connects_both_decision_signals() -> None:
    """Qüsurun ÖZÜ: heç bir kontroller bu iki siqnalı dinləmirdi."""
    _, screen, _, _ = _build()

    assert screen.accepted.connected
    assert screen.rejected.connected


def test_attach_does_not_read_the_inbox_twice() -> None:
    """«fine_appeals» `_binders()`-dədir — `attach` ikinci oxu ETMİR (PERF-1/2/3)."""
    _build()

    assert _Binder.populated == []


# --------------------------------------------------------------------------- #
# Qəbul / rədd
# --------------------------------------------------------------------------- #


def test_accept_writes_commits_and_rereads() -> None:
    _, screen, context, appeals = _build()

    screen.accepted.emit(str(APPEAL), LONG_NOTE)

    assert len(appeals.approvals) == 1
    assert appeals.approvals[0]["appeal_id"] == APPEAL
    assert appeals.approvals[0]["note"] == LONG_NOTE
    assert context.sessions[0].committed is True
    assert _Binder.populated == ["fine_appeals"]


def test_reject_writes_commits_and_rereads() -> None:
    _, screen, context, appeals = _build()

    screen.rejected.emit(str(APPEAL), LONG_NOTE)

    assert len(appeals.rejections) == 1
    assert appeals.rejections[0]["appeal_id"] == APPEAL
    assert context.sessions[0].committed is True
    assert _Binder.populated == ["fine_appeals"]


def test_accept_never_invents_a_partial_amount() -> None:
    """Ekranda məbləğ sahəsi yoxdur — `new_amount` ÖTÜRÜLMÜR (tam ləğv)."""
    _, screen, _, appeals = _build()

    screen.accepted.emit(str(APPEAL), LONG_NOTE)

    assert "new_amount" not in appeals.approvals[0]


# --------------------------------------------------------------------------- #
# Səbəbin doğrulanması
# --------------------------------------------------------------------------- #


def test_short_note_never_opens_a_session(_isolate: list[tuple[str, str]]) -> None:
    """Qısa səbəb yazı yoluna ÜMUMİYYƏTLƏ girmir — kart və mətn yerində qalır."""
    _, screen, context, appeals = _build()

    screen.accepted.emit(str(APPEAL), "qısa")

    assert context.sessions == []
    assert appeals.approvals == []
    assert _Binder.populated == []
    assert len(_isolate) == 1


def test_whitespace_only_note_is_rejected(_isolate: list[tuple[str, str]]) -> None:
    _, screen, context, _ = _build()

    screen.rejected.emit(str(APPEAL), "        \n   ")

    assert context.sessions == []
    assert len(_isolate) == 1


def test_note_is_normalised_exactly_like_the_domain() -> None:
    """Domen `" ".join(note.split())` edir — ekran DAHA SƏRT saymamalıdır.

    «a» × 10 ARALARINDA boşluqla domendə 19 simvoldur, sadə `strip()` ilə isə
    ekran onu 28 sayardı; əks halda (ekran sərt) istifadəçi domenin qəbul
    etdiyi mətnə görə rədd cavabı alardı.
    """
    _, screen, _, appeals = _build()
    padded = "   Sübut   şəkli    aydın    deyil   "

    screen.accepted.emit(str(APPEAL), padded)

    assert appeals.approvals[0]["note"] == "Sübut şəkli aydın deyil"


def test_the_boundary_length_is_accepted() -> None:
    """Tam `MIN_DECISION_NOTE_LENGTH` uzunluq KEÇİR — sərhəd domenlə eynidir."""
    _, screen, _, appeals = _build()

    screen.accepted.emit(str(APPEAL), "x" * MIN_DECISION_NOTE_LENGTH)

    assert len(appeals.approvals) == 1


def test_one_character_below_the_boundary_is_refused(_isolate: list[Any]) -> None:
    _, screen, context, _ = _build()

    screen.accepted.emit(str(APPEAL), "x" * (MIN_DECISION_NOTE_LENGTH - 1))

    assert context.sessions == []
    assert len(_isolate) == 1


# --------------------------------------------------------------------------- #
# Yararsız identifikator və uğursuz yazı
# --------------------------------------------------------------------------- #


def test_unusable_appeal_id_is_reported_not_crashed(_isolate: list[Any]) -> None:
    """QA-13 naxışı: `UUID("")` `ValueError` atır — susqun çökmə YOX."""
    _, screen, context, _ = _build()

    screen.accepted.emit("", LONG_NOTE)

    assert context.sessions == []
    assert len(_isolate) == 1
    assert _isolate[0][1] == fine_appeals_module.UNKNOWN_APPEAL_MESSAGE


def test_use_case_failure_keeps_the_list_and_skips_the_reread(
    _isolate: list[Any],
) -> None:
    """Uğursuz yazı siyahını SİLMİR — modal, `show_error` deyil."""
    failure = KompasOSError("icazə yoxdur")
    _, screen, context, appeals = _build(failure=failure)

    screen.accepted.emit(str(APPEAL), LONG_NOTE)

    assert appeals.approvals == []
    assert context.sessions[0].committed is False
    assert _Binder.populated == []
    assert screen.errors == []
    assert len(_isolate) == 1


def test_read_failure_shows_a_working_retry_button() -> None:
    """UI-R4-01: oxu xətasında «Yenidən Cəhd Et» HƏQİQƏTƏN bağlıdır."""
    controller, screen, _, _ = _build()
    _Binder.failure = KompasOSError("baza əlçatmazdır")

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.errors[0][0] == "Etirazlar oxuna bilmədi"
    assert callable(screen.retries[0])
