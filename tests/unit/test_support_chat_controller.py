"""Üzən dəstək panelinin canlı yolu — `controllers/support_chat.py`.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TESTLƏR
──────────────────────────────────────────────────────────────────────────────
`SupportChatWidget.message_sent` əvvəl canlı rejimdə HEÇ NƏYƏ bağlı deyildi:
mesaj ekranda görünürdü, `support_tickets`-ə isə heç nə yazılmırdı. Belə
"kəsilmiş yol" heç bir test qırmır — o, yalnız müştəri cavab gözləyib
almayanda üzə çıxır.

İki qapı qoyulur: mesajın use case-ə ÇATMASI və uğursuzluğun GİZLƏNMƏMƏSİ.
Testlər Qt TƏLƏB ETMİR — widget duck-typing ilə əvəzlənir.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, Final

import pytest

from src.domain.value_objects.identifiers import EmployeeId, TenantId
from src.domain.value_objects.support import SupportChannel
from src.presentation.controllers.support_chat import (
    FAILURE_PREFIX,
    SupportChatController,
)
from src.shared.exceptions import KompasOSError

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())


class _Widget:
    """`SupportChatWidget` əvəzi — kontrollerin toxunduğu metodlar."""

    def __init__(self, *, channel: SupportChannel | None = SupportChannel.TECHNICAL) -> None:
        self.messages: list[tuple[str, bool]] = []
        self.unread: bool | None = None
        self.channel = channel
        self.urgent = False

    def add_message(self, text: str, *, outgoing: bool = False) -> None:
        self.messages.append((text, outgoing))

    def set_unread(self, has_unread: bool) -> None:
        self.unread = has_unread

    def selected_channel(self) -> SupportChannel | None:
        return self.channel

    def is_urgent(self) -> bool:
        return self.urgent

    def pending_attachment(self) -> tuple[str, bytes] | None:
        return None


class _SupportUseCase:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.sent: list[str] = []
        self.channels: list[SupportChannel] = []
        self.error = error

    def is_available(self, *, tenant_id: TenantId, actor: Any) -> bool:
        return True

    def threads(
        self, *, tenant_id: TenantId, actor: Any, channel: SupportChannel | None = None
    ) -> list[Any]:
        return []

    def unread_count(self, *, tenant_id: TenantId, actor: Any) -> int:
        return 0

    def send(
        self,
        *,
        tenant_id: TenantId,
        actor: Any,
        body: str,
        channel: SupportChannel = SupportChannel.TECHNICAL,
        subject: str = "",
        urgent: bool = False,
        attachment: bytes | None = None,
        attachment_name: str = "",
    ) -> Any:
        if self.error is not None:
            raise self.error
        self.sent.append(body)
        self.channels.append(channel)
        return None


class _Session:
    def __init__(self, support: _SupportUseCase) -> None:
        self.tenant_id = TENANT
        self.support = support
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Context:
    def __init__(self, session: _Session) -> None:
        self._session = session

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        yield self._session


def _controller(support: _SupportUseCase) -> tuple[SupportChatController, _Session]:
    session = _Session(support)
    actor = type("_Actor", (), {"id": EmployeeId(uuid.uuid4())})()
    return (SupportChatController(_Context(session), actor), session)  # type: ignore[arg-type]


def test_message_reaches_the_use_case_and_is_committed() -> None:
    """Commit UNUDULARSA yazı rollback olardı — bilet heç vaxt yaranmazdı."""
    support = _SupportUseCase()
    controller, session = _controller(support)
    widget = _Widget()

    controller._on_sent(widget, "Sumqayıt serveri 4 saatdır cavab vermir.")

    assert support.sent == ["Sumqayıt serveri 4 saatdır cavab vermir."]
    assert session.commits == 1
    # Uğurlu göndərişdə ƏLAVƏ baloncuq YOXDUR: widget istifadəçinin mesajını
    # onsuz da özü əlavə edib (bax `SupportChatWidget._on_send`).
    assert widget.messages == []


def test_failed_message_is_not_silently_swallowed() -> None:
    """Mesajın GETMƏDİYİ istifadəçidən gizlədilmir."""

    class _ClosedError(KompasOSError):
        user_message = "Dəstək chat-i hazırda aktiv deyil."

    support = _SupportUseCase(error=_ClosedError("modul deaktiv"))
    controller, session = _controller(support)
    widget = _Widget()

    controller._on_sent(widget, "Salam")

    assert session.commits == 0
    assert widget.messages == [(f"{FAILURE_PREFIX}Dəstək chat-i hazırda aktiv deyil.", False)]
