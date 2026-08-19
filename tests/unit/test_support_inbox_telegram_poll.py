"""`SupportInboxController.poll_telegram` — D3-02 (dövrə 3 audit).

──────────────────────────────────────────────────────────────────────────────
HANSI QÜSURU TUTUR
──────────────────────────────────────────────────────────────────────────────
`poll_telegram()` ƏVVƏL GUI sapında SİNXRON çağırılırdı: `QTimer` (defolt hər
20 san, `TELEGRAM_POLL_INTERVAL_SECONDS`) `TelegramApiClient.get_updates()`-i
işə salırdı, o isə real HTTP sorğusudur (`httpx.Client` taymautu, fallback
15 san). UI-02/D3-01 ilə EYNİ qüsur sinfi — Telegram/internet yavaşlayanda
«Texniki Dəstək» bölməsi bir neçə saniyəliyə donurdu.

Bu fayl aşağıdakıları ölçür (`InlineExecutor` — sap davranışı YOX, MƏNTİQ):

    1. yeni cavablar söhbətlərə yazılır və YALNIZ çatdırılan VARSA `refresh`
       çağırılır;
    2. iki uğursuzluq növü (`poll()` özü / `deliver_telegram_reply`) AYRI-AYRI
       tutulur, HEÇ BİRİ çökmür, HEÇ BİRİ `refresh` çağırmır;
    3. `poller=None`-də heç nə baş vermir.

VƏ (real `QThreadPool` ilə, `test_background_job_funnel.py`-dəki EYNİ üsul):

    4. iş GUI sapından KƏNARDA icra olunur;
    5. əvvəlki dövrə HƏLƏ QAÇIRSA, YENİ dövrə BAŞLADILMIR;
    6. poll dövrəsi əlavə endirməsi (`_on_attachment`) ilə AYNI `self._task`
       sahəsini PAYLAŞMIR (`self._poll_task` ayrıdır).
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Any

import pytest

from src.presentation.background_task import InlineExecutor
from src.presentation.controllers.support_inbox import SupportInboxController
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


class _Reply:
    def __init__(self, *, body: str = "salam", reference: str = "ref-1") -> None:
        self.body = body
        self.reference = reference
        self.reply_to_message_id = 42


class _Poller:
    def __init__(self, *, replies: list[_Reply] | None = None, failure: Exception | None = None):
        self._replies = replies or []
        self._failure = failure
        self.calls = 0
        self.threads: list[int] = []
        self._block: threading.Event | None = None

    def block_on(self, event: threading.Event) -> None:
        self._block = event

    def poll(self) -> list[_Reply]:
        self.calls += 1
        self.threads.append(threading.get_ident())
        if self._block is not None:
            self._block.wait(timeout=5.0)
        if self._failure is not None:
            raise self._failure
        return self._replies


class _SupportInbox:
    def __init__(
        self, *, ticket_ids: list[Any] | None = None, failure: Exception | None = None
    ) -> None:
        # `ticket_ids[i]` — i-nci `deliver_telegram_reply` çağırışının nəticəsi.
        # `None` YOXDUR sayılır (uyğun müraciət tapılmadı).
        self._ticket_ids = ticket_ids
        self._failure = failure
        self.delivered: list[str] = []

    def deliver_telegram_reply(
        self, *, tenant_id: Any, body: str, reference: str, telegram_message_id: int
    ) -> Any:
        if self._failure is not None:
            raise self._failure
        index = len(self.delivered)
        self.delivered.append(reference)
        if self._ticket_ids is None:
            return f"ticket-{index}"
        return self._ticket_ids[index]


class _Session:
    def __init__(self, *, support_inbox: _SupportInbox) -> None:
        self.tenant_id = "tenant"
        self.support_inbox = support_inbox
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(self, *, support_inbox: _SupportInbox) -> None:
        self._support_inbox = support_inbox
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(support_inbox=self._support_inbox)
        self.sessions.append(created)
        yield created


class _Actor:
    id = "actor-1"


class _Screen:
    """`SupportInboxScreen`-in yüngül əvəzi — `run_job`-un `owner=` yoxlaması
    QObject OLMAYAN `owner`-i GÖZLƏNİLƏN halda idarə edir (bax `run_job`
    başlığı), ona görə Qt TƏLƏB OLUNMUR."""


def _controller(context: _Context, *, poller: Any = None) -> SupportInboxController:
    """`InlineExecutor` ilə — sinxron, sap davranışı ölçən testlər ÜÇÜN DEYİL.

    Real sap davranışını ölçən üç test (aşağı) `SupportInboxController`-i
    BİRBAŞA qurur — `executor` ötürmür, ona görə onun ÖZ defoltu (Qt sap
    hovuzu) işə düşür.
    """
    return SupportInboxController(
        context,  # type: ignore[arg-type]
        _Actor(),  # type: ignore[arg-type]
        poller=poller,
        executor=InlineExecutor(),
    )


def _drain_until(qt_app: Any, predicate: Any, *, seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        qt_app.processEvents()


# --------------------------------------------------------------------------- #
# Məntiq (`InlineExecutor` — sinxron, Qt tələb etmir)
# --------------------------------------------------------------------------- #


def test_poll_telegram_delivers_new_replies_and_refreshes() -> None:
    poller = _Poller(replies=[_Reply(reference="a"), _Reply(reference="b")])
    inbox = _SupportInbox()
    context = _Context(support_inbox=inbox)
    controller = _controller(context, poller=poller)
    refreshed: list[Any] = []
    controller.refresh = refreshed.append  # type: ignore[method-assign]
    screen = _Screen()

    controller.poll_telegram(screen)  # type: ignore[arg-type]

    assert inbox.delivered == ["a", "b"]
    assert context.sessions[0].committed is True
    assert refreshed == [screen]


def test_poll_telegram_ignores_a_reply_with_no_matching_ticket() -> None:
    """`deliver_telegram_reply` `None` qaytarsa (uyğun müraciət tapılmadı) sayılmır."""
    poller = _Poller(replies=[_Reply()])
    inbox = _SupportInbox(ticket_ids=[None])
    context = _Context(support_inbox=inbox)
    controller = _controller(context, poller=poller)
    refreshed: list[Any] = []
    controller.refresh = refreshed.append  # type: ignore[method-assign]

    controller.poll_telegram(_Screen())  # type: ignore[arg-type]

    assert refreshed == [], "heç bir cavab HƏQİQƏTƏN çatdırılmayıb, refresh lazım deyil"


def test_poll_telegram_does_nothing_when_there_are_no_replies() -> None:
    poller = _Poller(replies=[])
    context = _Context(support_inbox=_SupportInbox())
    controller = _controller(context, poller=poller)
    refreshed: list[Any] = []
    controller.refresh = refreshed.append  # type: ignore[method-assign]

    controller.poll_telegram(_Screen())  # type: ignore[arg-type]

    assert context.sessions == [], "cavab yoxdursa sessiya BELƏ AÇILMIR"
    assert refreshed == []


def test_poll_telegram_survives_a_poll_failure() -> None:
    """`self._poller.poll()` ÖZÜ çöksə — SÜKUTLA (jurnalda), refresh YOX."""
    poller = _Poller(failure=RuntimeError("Telegram əlçatmazdır"))
    context = _Context(support_inbox=_SupportInbox())
    controller = _controller(context, poller=poller)
    refreshed: list[Any] = []
    controller.refresh = refreshed.append  # type: ignore[method-assign]

    controller.poll_telegram(_Screen())  # type: ignore[arg-type]

    assert context.sessions == []
    assert refreshed == []


def test_poll_telegram_survives_a_delivery_failure() -> None:
    """`deliver_telegram_reply` çöksə — SÜKUTLA (jurnalda), refresh YOX."""
    poller = _Poller(replies=[_Reply()])
    inbox = _SupportInbox(failure=RuntimeError("baza əlçatmazdır"))
    context = _Context(support_inbox=inbox)
    controller = _controller(context, poller=poller)
    refreshed: list[Any] = []
    controller.refresh = refreshed.append  # type: ignore[method-assign]

    controller.poll_telegram(_Screen())  # type: ignore[arg-type]

    assert context.sessions[0].committed is False
    assert refreshed == []


def test_poll_telegram_does_nothing_without_a_configured_poller() -> None:
    context = _Context(support_inbox=_SupportInbox())
    controller = _controller(context, poller=None)

    controller.poll_telegram(_Screen())  # type: ignore[arg-type]

    assert context.sessions == []
    assert controller._poll_task is None


# --------------------------------------------------------------------------- #
# Sap davranışı (real `QThreadPool`, `test_background_job_funnel.py`-dəki üsul)
# --------------------------------------------------------------------------- #


@requires_qt
def test_poll_telegram_runs_off_the_gui_thread(qt_app) -> None:  # type: ignore[no-untyped-def]
    poller = _Poller(replies=[])
    context = _Context(support_inbox=_SupportInbox())
    # `executor` ötürülmür — ÖZ defoltu (Qt sap hovuzu) işə düşür.
    controller = SupportInboxController(context, _Actor(), poller=poller)  # type: ignore[arg-type]

    gui_thread = threading.get_ident()
    controller.poll_telegram(_Screen())  # type: ignore[arg-type]
    _drain_until(qt_app, lambda: not controller._poll_task.is_running)

    assert poller.calls == 1
    assert poller.threads[0] != gui_thread


@requires_qt
def test_poll_telegram_does_not_start_a_second_cycle_while_one_is_running(
    qt_app,
) -> None:  # type: ignore[no-untyped-def]
    block = threading.Event()
    poller = _Poller(replies=[])
    poller.block_on(block)
    context = _Context(support_inbox=_SupportInbox())
    controller = SupportInboxController(context, _Actor(), poller=poller)  # type: ignore[arg-type]

    controller.poll_telegram(_Screen())  # type: ignore[arg-type]
    assert controller._poll_task is not None
    assert controller._poll_task.is_running  # `run()` bunu SİNXRON işarələyir

    controller.poll_telegram(_Screen())  # type: ignore[arg-type]  # İKİNCİ çağırış — kəsilməlidir

    block.set()
    _drain_until(qt_app, lambda: not controller._poll_task.is_running)

    assert poller.calls == 1, "YALNIZ BİR dövrə icra olunmalıdır"


@requires_qt
def test_poll_telegram_uses_a_separate_task_slot_from_attachment_downloads(
    qt_app,
) -> None:  # type: ignore[no-untyped-def]
    """`self._poll_task` VƏ `self._task` bir-birinə mane olmur (bax `__init__`)."""
    poller = _Poller(replies=[])
    context = _Context(support_inbox=_SupportInbox())
    controller = SupportInboxController(context, _Actor(), poller=poller)  # type: ignore[arg-type]

    # `self._task`-ı ƏL İLƏ "işlək" kimi işarələyirik — əlavə endirməsi
    # davam edir kimi simulyasiya edir.
    from src.presentation.background_task import BackgroundTask

    controller._task = BackgroundTask(name="FAKE_ATTACHMENT_DOWNLOAD")

    controller.poll_telegram(_Screen())  # type: ignore[arg-type]
    _drain_until(qt_app, lambda: not controller._poll_task.is_running)

    assert poller.calls == 1, "`self._task`-ın vəziyyəti poll dövrəsinə TƏSİR ETMƏMƏLİDİR"
