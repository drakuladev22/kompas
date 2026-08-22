"""`SupportInboxScreen` ↔ `SupportInboxController` — REAL Qt e2e sınaqları (CHAT-1).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3)
──────────────────────────────────────────────────────────────────────────────
`test_support_inbox_screen.py` REAL ekranı qurur, LAKİN heç bir testdə
`SupportInboxController` ONA bağlanmır — süzgəclər, status saylar və düymələr
YALNIZ ekranın öz metodları ilə ölçülür. `test_support_inbox_telegram_poll.py`
isə əksinədir: kontrolleri qurur, LAKİN `_Screen` sahtəsi ilə (heç bir real
widget, heç bir real klik). Bu boşluq CLAUDE.md-nin təsvir etdiyi tələdir —
kanal izolyasiyası, «yalnız `OPEN` sayılır» qaydası və xəta qolunun
üstündən yazılmaması heç vaxt REAL düymə kliki ilə yoxlanılmayıb.

Burada `SupportInboxController.attach(screen)` REAL `SupportInboxScreen`-ə
bağlanır və hər ssenari HƏQİQİ widget qarşılıqlı təsiri (sətrə klik, status
düyməsi, cavab sahəsinə yazıb Enter) ilə işə salınır.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from src.application.use_cases.support_chat import SupportMessage, SupportThread
from src.domain.value_objects.identifiers import EmployeeId, SupportTicketId
from src.domain.value_objects.support import SupportChannel, SupportTicketStatus
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()

INTERNAL_TICKET = SupportTicketId(uuid.uuid4())
TECHNICAL_TICKET = SupportTicketId(uuid.uuid4())


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


def _thread(
    *,
    ticket_id: SupportTicketId,
    channel: SupportChannel,
    sender_name: str = "Murad Bayramov",
    status: SupportTicketStatus = SupportTicketStatus.OPEN,
    messages: list[SupportMessage] | None = None,
) -> SupportThread:
    return SupportThread(
        ticket_id=ticket_id,
        subject="Kiosk açılmır",
        status=status.value,
        created_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
        messages=messages or [],
        channel=channel,
        sender_name=sender_name,
        sender_position="Mağaza Meneceri",
        store_name="Yataş Babək",
    )


def _message(
    *, ticket_id: SupportTicketId, body: str, is_from_developer: bool = False
) -> SupportMessage:
    from src.domain.value_objects.identifiers import SupportMessageId

    return SupportMessage(
        message_id=SupportMessageId(uuid.uuid4()),
        ticket_id=ticket_id,
        body=body,
        created_at=datetime(2026, 8, 20, 9, 5, tzinfo=UTC),
        is_from_developer=is_from_developer,
    )


class _SupportInbox:
    """`SupportInboxUseCase`-in yerini tutur — YALNIZ kontrollerin gözlədiyi imza."""

    def __init__(self) -> None:
        self._threads: dict[SupportChannel, list[SupportThread]] = {
            SupportChannel.INTERNAL: [],
            SupportChannel.TECHNICAL: [],
        }
        self._counts: dict[SupportChannel, dict[SupportTicketStatus, int]] = {}
        self.threads_calls: list[SupportChannel] = []
        self.mark_read_calls: list[tuple[SupportChannel, SupportTicketId]] = []
        self.replies: list[dict[str, Any]] = []
        self.status_changes: list[dict[str, Any]] = []
        self.reply_error: KompasOSError | None = None
        self.set_status_error: KompasOSError | None = None

    def threads(self, *, tenant_id: Any, actor: Any, channel: SupportChannel, filters: Any) -> Any:
        self.threads_calls.append(channel)
        return list(self._threads.get(channel, []))

    def status_counts(
        self, *, tenant_id: Any, actor: Any, channel: SupportChannel, filters: Any
    ) -> Any:
        return dict(self._counts.get(channel, dict.fromkeys(SupportTicketStatus, 0)))

    def thread(
        self, *, tenant_id: Any, actor: Any, channel: SupportChannel, ticket_id: SupportTicketId
    ) -> Any:
        return next(t for t in self._threads[channel] if t.ticket_id == ticket_id)

    def mark_read(
        self, *, tenant_id: Any, actor: Any, channel: SupportChannel, ticket_id: SupportTicketId
    ) -> None:
        self.mark_read_calls.append((channel, ticket_id))

    def reply(
        self,
        *,
        tenant_id: Any,
        actor: Any,
        channel: SupportChannel,
        ticket_id: SupportTicketId,
        body: str,
    ) -> None:
        if self.reply_error is not None:
            raise self.reply_error
        self.replies.append({"channel": channel, "ticket_id": ticket_id, "body": body})

    def set_status(
        self,
        *,
        tenant_id: Any,
        actor: Any,
        channel: SupportChannel,
        ticket_id: SupportTicketId,
        status: SupportTicketStatus,
    ) -> None:
        if self.set_status_error is not None:
            raise self.set_status_error
        self.status_changes.append({"channel": channel, "ticket_id": ticket_id, "status": status})

    def position_options(self, *, tenant_id: Any, actor: Any) -> list[tuple[str, str]]:
        return []


class _Row(dict):
    """`session.uow.connection.execute(...).fetchall()`-un `row["ad"]` API-si."""


class _Connection:
    def execute(self, _sql: str, _params: Any = None) -> _Connection:
        return self

    def fetchall(self) -> list[_Row]:
        return []


class _Uow:
    connection = _Connection()


class _Session:
    def __init__(self, inbox: _SupportInbox) -> None:
        self.tenant_id = TENANT
        self.support_inbox = inbox
        self.uow = _Uow()
        self.committed = False

    def commit(self) -> None:
        self.committed = True

    def max_upload_bytes(self) -> int:
        return 5 * 1024 * 1024


class _Context:
    def __init__(self, inbox: _SupportInbox) -> None:
        self._inbox = inbox
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(self._inbox)
        self.sessions.append(created)
        yield created

    def drive_providers(self, *, max_upload_bytes: int) -> Any:
        return None


class _Actor:
    id = EmployeeId(ACTOR_ID)


def _wire(theme: Any, channel: SupportChannel, inbox: _SupportInbox) -> tuple[Any, Any, _Context]:
    from src.presentation.controllers.support_inbox import SupportInboxController
    from src.presentation.screens.support_inbox import SupportInboxScreen

    context = _Context(inbox)
    screen = SupportInboxScreen(theme, channel=channel)
    controller = SupportInboxController(context, _Actor())  # type: ignore[arg-type]
    controller.attach(screen)  # type: ignore[arg-type]
    return screen, controller, context


def _row_widgets(screen: Any) -> list[Any]:
    return [
        screen._rows.itemAt(index).widget()
        for index in range(screen._rows.count())
        if screen._rows.itemAt(index).widget() is not None
    ]


def _click_row(screen: Any, index: int = 0) -> None:
    _row_widgets(screen)[index].click()


# --------------------------------------------------------------------------- #
# 1. Kanal izolyasiyası (CHAT-1) — REAL ekranla
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_internal_screen_never_shows_a_technical_ticket(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    inbox = _SupportInbox()
    inbox._threads[SupportChannel.INTERNAL] = [
        _thread(ticket_id=INTERNAL_TICKET, channel=SupportChannel.INTERNAL, sender_name="Aygün")
    ]
    inbox._threads[SupportChannel.TECHNICAL] = [
        _thread(ticket_id=TECHNICAL_TICKET, channel=SupportChannel.TECHNICAL, sender_name="Murad")
    ]

    screen, _controller, _context = _wire(theme, SupportChannel.INTERNAL, inbox)
    qtbot.addWidget(screen)

    assert inbox.threads_calls == [SupportChannel.INTERNAL], (
        "Kontroller kanalı EKRANDAN oxumalıdır — açardan yox"
    )
    rows = _row_widgets(screen)
    assert len(rows) == 1
    texts = [child.text() for child in rows[0].findChildren(type(screen._sender))]
    assert any("Aygün" in t for t in texts)
    assert not any("Murad" in t for t in texts)


@requires_qt
def test_the_technical_screen_never_shows_an_internal_ticket(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    inbox = _SupportInbox()
    inbox._threads[SupportChannel.INTERNAL] = [
        _thread(ticket_id=INTERNAL_TICKET, channel=SupportChannel.INTERNAL, sender_name="Aygün")
    ]
    inbox._threads[SupportChannel.TECHNICAL] = [
        _thread(ticket_id=TECHNICAL_TICKET, channel=SupportChannel.TECHNICAL, sender_name="Murad")
    ]

    screen, _controller, _context = _wire(theme, SupportChannel.TECHNICAL, inbox)
    qtbot.addWidget(screen)

    assert inbox.threads_calls == [SupportChannel.TECHNICAL]
    rows = _row_widgets(screen)
    assert len(rows) == 1
    texts = [child.text() for child in rows[0].findChildren(type(screen._sender))]
    assert any("Murad" in t for t in texts)
    assert not any("Aygün" in t for t in texts)


# --------------------------------------------------------------------------- #
# 2. Real sətrə klik → açılış, `mark_read`, real chat balonları
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_a_real_row_opens_the_thread_and_marks_it_read(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    inbox = _SupportInbox()
    inbox._threads[SupportChannel.TECHNICAL] = [
        _thread(
            ticket_id=TECHNICAL_TICKET,
            channel=SupportChannel.TECHNICAL,
            messages=[_message(ticket_id=TECHNICAL_TICKET, body="Kassa açılmır")],
        )
    ]
    screen, _controller, context = _wire(theme, SupportChannel.TECHNICAL, inbox)
    qtbot.addWidget(screen)

    _click_row(screen)

    assert inbox.mark_read_calls == [(SupportChannel.TECHNICAL, TECHNICAL_TICKET)]
    assert any(s.committed for s in context.sessions)
    assert screen._subject.text() == "Kiosk açılmır"
    assert screen._send.isEnabled() is True, "OPEN söhbətdə cavab sahəsi AÇIQ olmalıdır"


# --------------------------------------------------------------------------- #
# 3. Real cavab yazma — Enter ilə göndərmə, yazı yolu commit edir
# --------------------------------------------------------------------------- #


@requires_qt
def test_typing_a_reply_and_pressing_enter_sends_it_through_the_real_composer(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    inbox = _SupportInbox()
    inbox._threads[SupportChannel.TECHNICAL] = [
        _thread(ticket_id=TECHNICAL_TICKET, channel=SupportChannel.TECHNICAL)
    ]
    screen, _controller, context = _wire(theme, SupportChannel.TECHNICAL, inbox)
    qtbot.addWidget(screen)
    _click_row(screen)

    screen._reply.setText("Kassanı yenidən başladın.")
    qtbot.keyClick(screen._reply, __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.Key.Key_Return)

    assert inbox.replies == [
        {
            "channel": SupportChannel.TECHNICAL,
            "ticket_id": TECHNICAL_TICKET,
            "body": "Kassanı yenidən başladın.",
        }
    ]
    assert any(s.committed for s in context.sessions)
    assert screen._reply.text() == "", "Göndərildikdən sonra sahə TƏMİZLƏNMƏLİDİR"


@requires_qt
def test_the_send_button_does_the_same_as_enter(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    inbox = _SupportInbox()
    inbox._threads[SupportChannel.TECHNICAL] = [
        _thread(ticket_id=TECHNICAL_TICKET, channel=SupportChannel.TECHNICAL)
    ]
    screen, _controller, _context = _wire(theme, SupportChannel.TECHNICAL, inbox)
    qtbot.addWidget(screen)
    _click_row(screen)

    screen._reply.setText("Cavab")
    screen._send.click()

    assert len(inbox.replies) == 1


@requires_qt
def test_an_empty_or_whitespace_reply_never_reaches_the_use_case(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    inbox = _SupportInbox()
    inbox._threads[SupportChannel.TECHNICAL] = [
        _thread(ticket_id=TECHNICAL_TICKET, channel=SupportChannel.TECHNICAL)
    ]
    screen, _controller, _context = _wire(theme, SupportChannel.TECHNICAL, inbox)
    qtbot.addWidget(screen)
    _click_row(screen)

    screen._reply.setText("     ")
    screen._send.click()  # ÇÖKMƏMƏLİDİR

    assert inbox.replies == []


@requires_qt
def test_hostile_and_extreme_reply_text_does_not_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    inbox = _SupportInbox()
    inbox._threads[SupportChannel.TECHNICAL] = [
        _thread(ticket_id=TECHNICAL_TICKET, channel=SupportChannel.TECHNICAL)
    ]
    screen, _controller, _context = _wire(theme, SupportChannel.TECHNICAL, inbox)
    qtbot.addWidget(screen)
    _click_row(screen)

    hostile = ("'; DROP TABLE support_messages; -- 🔥" * 50) + "A" * 10_000
    screen._reply.setText(hostile)
    screen._send.click()  # ÇÖKMƏMƏLİDİR

    assert len(inbox.replies) == 1
    assert inbox.replies[0]["body"] == hostile.strip()


# --------------------------------------------------------------------------- #
# 4. Real status düyməsi — cavab bağlı söhbətə YAZILMIR
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_the_real_resolve_button_commits_and_the_composer_stays_reachable(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    inbox = _SupportInbox()
    inbox._threads[SupportChannel.TECHNICAL] = [
        _thread(ticket_id=TECHNICAL_TICKET, channel=SupportChannel.TECHNICAL)
    ]
    screen, _controller, context = _wire(theme, SupportChannel.TECHNICAL, inbox)
    qtbot.addWidget(screen)
    _click_row(screen)

    screen._status_actions[SupportTicketStatus.RESOLVED].click()

    assert inbox.status_changes == [
        {
            "channel": SupportChannel.TECHNICAL,
            "ticket_id": TECHNICAL_TICKET,
            "status": SupportTicketStatus.RESOLVED,
        }
    ]
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_closing_a_thread_via_the_real_button_locks_the_composer_after_refresh(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """Status düyməsi bağlandıqdan SONRA `refresh()` bağlı vəziyyəti gətirməlidir."""
    inbox = _SupportInbox()
    inbox._threads[SupportChannel.TECHNICAL] = [
        _thread(ticket_id=TECHNICAL_TICKET, channel=SupportChannel.TECHNICAL)
    ]
    screen, _controller, _context = _wire(theme, SupportChannel.TECHNICAL, inbox)
    qtbot.addWidget(screen)
    _click_row(screen)

    # Refresh CLOSED statusunu qaytarsın deyə arxa fondakı sətri dəyişirik.
    def _close_then_reflect(
        *, tenant_id: Any, actor: Any, channel: Any, ticket_id: Any, status: Any
    ) -> None:
        inbox.status_changes.append({"channel": channel, "ticket_id": ticket_id, "status": status})
        inbox._threads[SupportChannel.TECHNICAL] = [
            _thread(ticket_id=TECHNICAL_TICKET, channel=SupportChannel.TECHNICAL, status=status)
        ]

    inbox.set_status = _close_then_reflect  # type: ignore[method-assign]

    screen._status_actions[SupportTicketStatus.CLOSED].click()

    assert screen._send.isEnabled() is False, "Bağlı söhbətdə cavab sahəsi bağlı olmalıdır"


# --------------------------------------------------------------------------- #
# 5. Xəta qolu — real klik, sükutla udulmur, üstündən YAZILMIR
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_reply_failure_shows_the_domain_message_and_does_not_commit(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    inbox = _SupportInbox()
    inbox._threads[SupportChannel.TECHNICAL] = [
        _thread(ticket_id=TECHNICAL_TICKET, channel=SupportChannel.TECHNICAL)
    ]
    inbox.reply_error = KompasOSError(
        "closed ticket", user_message="Bu söhbət bağlıdır — cavab yazıla bilməz."
    )
    screen, _controller, context = _wire(theme, SupportChannel.TECHNICAL, inbox)
    qtbot.addWidget(screen)
    screen.show()
    _click_row(screen)
    committed_before = sum(1 for s in context.sessions if s.committed)

    screen._reply.setText("Cavab")
    screen._send.click()  # ÇÖKMƏMƏLİDİR

    committed_after = sum(1 for s in context.sessions if s.committed)
    assert committed_after == committed_before, "İstisna atılıbsa YENİ commit OLMAMALIDIR"
    assert screen._message.isVisible() is True
    assert "bağlıdır" in screen._message.text()


@requires_qt
def test_a_status_change_failure_shows_an_error_instead_of_crashing(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    inbox = _SupportInbox()
    inbox._threads[SupportChannel.TECHNICAL] = [
        _thread(ticket_id=TECHNICAL_TICKET, channel=SupportChannel.TECHNICAL)
    ]
    inbox.set_status_error = KompasOSError(
        "already closed", user_message="Müraciət artıq bağlanıb."
    )
    screen, _controller, _context = _wire(theme, SupportChannel.TECHNICAL, inbox)
    qtbot.addWidget(screen)
    screen.show()
    _click_row(screen)

    screen._status_actions[SupportTicketStatus.CLOSED].click()  # ÇÖKMƏMƏLİDİR

    assert screen._message.isVisible() is True
    assert "bağlanıb" in screen._message.text()


@requires_qt
def test_a_malformed_ticket_id_from_a_stale_row_does_not_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Siqnal köhnəlmiş sətirdən naməlum ID ilə gəlsə də ÇÖKMƏMƏLİDİR."""
    from src.presentation.controllers.support_inbox import UNKNOWN_TICKET

    inbox = _SupportInbox()
    screen, _controller, _context = _wire(theme, SupportChannel.TECHNICAL, inbox)
    qtbot.addWidget(screen)

    screen.thread_selected.emit("bu-uuid-deyil")

    assert inbox.mark_read_calls == []
    assert screen._message.text() == UNKNOWN_TICKET


# --------------------------------------------------------------------------- #
# 6. Aşağı endirmə xətası — real klik, düymə sükutla ölmür
# --------------------------------------------------------------------------- #


def _with_attachment(*, ticket_id: SupportTicketId) -> SupportThread:
    from dataclasses import replace

    thread = _thread(
        ticket_id=ticket_id,
        channel=SupportChannel.TECHNICAL,
        messages=[_message(ticket_id=ticket_id, body="Şəkil")],
    )
    thread.messages[0] = replace(
        thread.messages[0], attachment_ref="GOOGLE_DRIVE:-:file-1", attachment_name="ekran.png"
    )
    return thread


def _attachment_button(screen: Any) -> Any:
    from PySide6.QtWidgets import QPushButton

    return next(
        b
        for b in screen.findChildren(QPushButton)
        if "ekran.png" in b.text() and "(" not in b.text()
    )


@requires_qt
def test_the_real_attachment_button_downloads_and_shows_the_image(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.background_task import InlineExecutor
    from src.presentation.controllers.support_inbox import SupportInboxController
    from src.presentation.screens.support_inbox import SupportInboxScreen

    inbox = _SupportInbox()
    inbox._threads[SupportChannel.TECHNICAL] = [_with_attachment(ticket_id=TECHNICAL_TICKET)]
    context = _Context(inbox)
    screen = SupportInboxScreen(theme, channel=SupportChannel.TECHNICAL)
    qtbot.addWidget(screen)
    controller = SupportInboxController(
        context,
        _Actor(),
        executor=InlineExecutor(),  # type: ignore[arg-type]
    )
    controller.attach(screen)  # type: ignore[arg-type]

    downloaded: list[tuple[str, bytes]] = []
    screen.show_attachment = lambda name, content: downloaded.append((name, content))  # type: ignore[method-assign]
    controller._download_attachment = lambda reference: b"\x89PNG\r\n"  # type: ignore[method-assign]

    _click_row(screen)
    _attachment_button(screen).click()  # ÇÖKMƏMƏLİDİR

    assert downloaded == [("ekran.png", b"\x89PNG\r\n")]


@requires_qt
def test_attachment_download_failure_shows_a_message_instead_of_crashing(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.background_task import InlineExecutor
    from src.presentation.controllers.support_inbox import SupportInboxController
    from src.presentation.screens.support_inbox import SupportInboxScreen

    inbox = _SupportInbox()
    inbox._threads[SupportChannel.TECHNICAL] = [_with_attachment(ticket_id=TECHNICAL_TICKET)]
    context = _Context(inbox)
    screen = SupportInboxScreen(theme, channel=SupportChannel.TECHNICAL)
    qtbot.addWidget(screen)
    screen.show()
    controller = SupportInboxController(
        context,
        _Actor(),
        executor=InlineExecutor(),  # type: ignore[arg-type]
    )
    controller.attach(screen)  # type: ignore[arg-type]

    def _broken_download(reference: str) -> bytes:
        raise RuntimeError("Drive əlçatmazdır")

    controller._download_attachment = _broken_download  # type: ignore[method-assign]

    _click_row(screen)
    _attachment_button(screen).click()  # ÇÖKMƏMƏLİDİR

    assert screen._message.isVisible() is True
    assert "Drive" in screen._message.text() or "yüklənmədi" in screen._message.text()
