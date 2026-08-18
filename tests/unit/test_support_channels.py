"""CHAT-1 — iki-kanallı dəstək, status sistemi və Telegram (tg1.md Faza 8).

Spesifikasiyanın 12 test bəndi burada BİRƏ-BİR yoxlanılır. Sıra da onunla
eynidir ki, sənəddəki bəndlə koddakı test arasındakı uyğunluq gözlə tapılsın.

──────────────────────────────────────────────────────────────────────────────
NİYƏ TAM SAHTƏ REPOZİTORİYA
──────────────────────────────────────────────────────────────────────────────
`_Tickets` protokolun HAMISINI (status, taymer, süzgəc, Telegram istinadı)
yaddaşda təkrarlayır. Kiçik `Mock` obyektləri kifayət etmirdi: bu axının
qüsurları məhz VƏZİYYƏT KEÇİDLƏRİNDƏ gizlənir («işçi cavab yazdı, status
qayıtdımı?»), keçid isə yalnız vəziyyət saxlayan sahtədə görünür.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest

from src.application.use_cases.support_chat import (
    InboxFilter,
    SupportAccessError,
    SupportChatUseCase,
    SupportInboxUseCase,
    SupportMessage,
    SupportThread,
    TelegramDelivery,
    TelegramOutgoing,
)
from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import (
    PermissionEffect,
    PermissionFlag,
    SystemRole,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    StoreId,
    SupportMessageId,
    SupportTicketId,
    TenantId,
    new_support_ticket_id,
)
from src.domain.value_objects.support import (
    CONTACT_SUPPORT_FLAG,
    MANAGE_TELEGRAM_FLAG,
    VIEW_INTERNAL_FLAG,
    VIEW_TECHNICAL_FLAG,
    SupportChannel,
    SupportTicketStatus,
)
from src.infrastructure.notifications.telegram import (
    TelegramReply,
    extract_reference,
    format_support_message,
)
from tests.fixtures.fakes import (
    FakeClock,
    FakeFeatureToggles,
    FakeSystemLimits,
    RecordingAudit,
    RecordingNotifier,
)

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())
STORE_A: Final = StoreId(uuid.uuid4())
STORE_B: Final = StoreId(uuid.uuid4())
NOW: Final = datetime(2026, 8, 18, 18, 42, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


@dataclass
class _Row:
    ticket_id: SupportTicketId
    tenant_id: TenantId
    opened_by: EmployeeId
    subject: str
    channel: SupportChannel
    is_urgent: bool
    status: SupportTicketStatus = SupportTicketStatus.OPEN
    created_at: datetime = NOW
    updated_at: datetime = NOW
    resolved_at: datetime | None = None
    waiting_since: datetime | None = None
    reminded_at: datetime | None = None
    staff_read_at: datetime | None = None
    customer_read_at: datetime | None = None
    messages: list[SupportMessage] = field(default_factory=list)


class _Tickets:
    """Protokolun yaddaş nüsxəsi."""

    def __init__(self) -> None:
        self.rows: dict[SupportTicketId, _Row] = {}
        self.profiles: dict[EmployeeId, tuple[str, str, str]] = {}
        self.positions: dict[EmployeeId, str] = {}
        self.stores: dict[EmployeeId, StoreId] = {}
        self._reference = 1000

    # ------------------------------ yazı ---------------------------------- #

    def open_ticket(
        self,
        *,
        ticket_id: SupportTicketId,
        tenant_id: TenantId,
        opened_by: EmployeeId,
        subject: str,
        channel: SupportChannel = SupportChannel.TECHNICAL,
        is_urgent: bool = False,
    ) -> None:
        self.rows[ticket_id] = _Row(
            ticket_id=ticket_id,
            tenant_id=tenant_id,
            opened_by=opened_by,
            subject=subject,
            channel=channel,
            is_urgent=is_urgent,
        )

    def append_message(
        self,
        *,
        message_id: SupportMessageId,
        ticket_id: SupportTicketId,
        sender_id: EmployeeId | None,
        body: str,
        is_from_developer: bool,
        from_telegram: bool = False,
        attachment_name: str = "",
    ) -> None:
        row = self.rows[ticket_id]
        row.messages.append(
            SupportMessage(
                message_id=message_id,
                ticket_id=ticket_id,
                body=body,
                created_at=NOW,
                is_from_developer=is_from_developer,
                sender_id=sender_id,
                from_telegram=from_telegram,
                attachment_name=attachment_name,
            )
        )

    def set_status(
        self, ticket_id: SupportTicketId, *, status: SupportTicketStatus, at: datetime
    ) -> None:
        row = self.rows[ticket_id]
        row.status = status
        row.resolved_at = at if status is SupportTicketStatus.RESOLVED else None
        row.waiting_since = at if status is SupportTicketStatus.WAITING else None
        row.reminded_at = None

    def raise_urgency(self, ticket_id: SupportTicketId) -> None:
        self.rows[ticket_id].is_urgent = True

    def mark_read(self, ticket_id: SupportTicketId, *, up_to: datetime) -> None:
        self.rows[ticket_id].customer_read_at = up_to

    def mark_staff_read(self, ticket_id: SupportTicketId, *, up_to: datetime) -> None:
        self.rows[ticket_id].staff_read_at = up_to

    def mark_reminded(self, ticket_id: SupportTicketId, *, at: datetime) -> None:
        self.rows[ticket_id].reminded_at = at

    # ------------------------------ oxu ------------------------------------ #

    def find_open_ticket(
        self,
        tenant_id: TenantId,
        *,
        channel: SupportChannel = SupportChannel.TECHNICAL,
        opened_by: EmployeeId | None = None,
    ) -> SupportTicketId | None:
        for row in self.rows.values():
            if (
                row.tenant_id == tenant_id
                and row.channel is channel
                and row.status is not SupportTicketStatus.CLOSED
                and (opened_by is None or row.opened_by == opened_by)
            ):
                return row.ticket_id
        return None

    def get_thread(self, ticket_id: SupportTicketId) -> SupportThread | None:
        row = self.rows.get(ticket_id)
        return None if row is None else self._hydrate(row)

    def list_threads(
        self,
        tenant_id: TenantId,
        *,
        limit: int = 20,
        channel: SupportChannel | None = None,
        opened_by: EmployeeId | None = None,
        status: SupportTicketStatus | None = None,
        store_ids: tuple[StoreId, ...] = (),
        position_codes: tuple[str, ...] = (),
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        unread_only: bool = False,
        search: str = "",
        newest_first: bool = True,
    ) -> list[SupportThread]:
        found = [
            self._hydrate(row)
            for row in self._matching(
                tenant_id,
                channel=channel,
                opened_by=opened_by,
                status=status,
                store_ids=store_ids,
                position_codes=position_codes,
                created_from=created_from,
                unread_only=unread_only,
                search=search,
            )
        ]
        found.sort(key=lambda item: item.ticket_status.sort_rank)
        return found[:limit]

    def status_counts(
        self,
        tenant_id: TenantId,
        *,
        channel: SupportChannel,
        store_ids: tuple[StoreId, ...] = (),
        position_codes: tuple[str, ...] = (),
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        unread_only: bool = False,
        search: str = "",
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self._matching(
            tenant_id,
            channel=channel,
            store_ids=store_ids,
            position_codes=position_codes,
            created_from=created_from,
            unread_only=unread_only,
            search=search,
        ):
            counts[row.status.value] = counts.get(row.status.value, 0) + 1
        return counts

    def position_options(self, tenant_id: TenantId) -> list[tuple[str, str]]:
        codes = {
            self.positions.get(row.opened_by, "")
            for row in self.rows.values()
            if row.tenant_id == tenant_id
        }
        return sorted((code, code.title()) for code in codes if code)

    def due_for_auto_close(self, tenant_id: TenantId, *, before: datetime) -> list[SupportTicketId]:
        return [
            row.ticket_id
            for row in self.rows.values()
            if row.tenant_id == tenant_id
            and row.status is SupportTicketStatus.RESOLVED
            and row.resolved_at is not None
            and row.resolved_at <= before
        ]

    def due_for_reminder(
        self, tenant_id: TenantId, *, before: datetime
    ) -> list[tuple[SupportTicketId, EmployeeId | None, str]]:
        return [
            (row.ticket_id, row.opened_by, row.subject)
            for row in self.rows.values()
            if row.tenant_id == tenant_id
            and row.status is SupportTicketStatus.WAITING
            and row.waiting_since is not None
            and row.waiting_since <= before
            and row.reminded_at is None
        ]

    def next_message_reference(self) -> str:
        self._reference += 1
        return f"#msg_{self._reference}"

    def record_telegram_delivery(
        self,
        message_id: SupportMessageId,
        *,
        reference: str,
        telegram_message_id: int | None,
        sent_at: datetime,
    ) -> None:
        # `replace()` — SAHƏ-SAHƏ YENİDƏN QURMA YOX: əl ilə qurulan nüsxə
        # `SupportMessage`-a əlavə olunan hər yeni sahəni (məs. şəkil
        # əlavəsi) SÜKUTLA itirərdi və test onu tapmazdı.
        for row in self.rows.values():
            for index, message in enumerate(row.messages):
                if message.message_id == message_id:
                    row.messages[index] = replace(
                        message, telegram_ref=reference, telegram_sent_at=sent_at
                    )

    def find_ticket_by_reference(
        self, *, reference: str = "", telegram_message_id: int | None = None
    ) -> SupportTicketId | None:
        for row in self.rows.values():
            for message in row.messages:
                if reference and message.telegram_ref == reference:
                    return row.ticket_id
        return None

    def attach_file(self, message_id: SupportMessageId, *, reference: str, filename: str) -> None:
        for row in self.rows.values():
            for index, message in enumerate(row.messages):
                if message.message_id == message_id:
                    row.messages[index] = replace(
                        message, attachment_ref=reference, attachment_name=filename
                    )

    def sender_profile(self, employee_id: EmployeeId) -> tuple[str, str, str]:
        return self.profiles.get(employee_id, ("", "", ""))

    # ---------------------------- köməkçi ---------------------------------- #

    def _matching(
        self,
        tenant_id: TenantId,
        *,
        channel: SupportChannel | None = None,
        opened_by: EmployeeId | None = None,
        status: SupportTicketStatus | None = None,
        store_ids: tuple[StoreId, ...] = (),
        position_codes: tuple[str, ...] = (),
        created_from: datetime | None = None,
        unread_only: bool = False,
        search: str = "",
    ) -> list[_Row]:
        rows = []
        for row in self.rows.values():
            if row.tenant_id != tenant_id:
                continue
            if channel is not None and row.channel is not channel:
                continue
            if opened_by is not None and row.opened_by != opened_by:
                continue
            if status is not None and row.status is not status:
                continue
            if store_ids and self.stores.get(row.opened_by) not in store_ids:
                continue
            if position_codes and self.positions.get(row.opened_by, "") not in position_codes:
                continue
            if created_from is not None and row.updated_at < created_from:
                continue
            if unread_only and not self._unread(row):
                continue
            if search and not self._matches_search(row, search):
                continue
            rows.append(row)
        return rows

    def _matches_search(self, row: _Row, needle: str) -> bool:
        haystack = [row.subject, *(message.body for message in row.messages)]
        name, _position, store = self.profiles.get(row.opened_by, ("", "", ""))
        haystack.extend([name, store])
        return any(needle.lower() in item.lower() for item in haystack)

    def _unread(self, row: _Row) -> bool:
        return any(
            not message.is_from_developer
            and (row.staff_read_at is None or message.created_at > row.staff_read_at)
            for message in row.messages
        )

    def _hydrate(self, row: _Row) -> SupportThread:
        name, position, store = self.profiles.get(row.opened_by, ("", "", ""))
        return SupportThread(
            ticket_id=row.ticket_id,
            subject=row.subject,
            status=row.status.value,
            created_at=row.created_at,
            messages=list(row.messages),
            unread_from_developer=sum(
                1
                for message in row.messages
                if message.is_from_developer
                and (row.customer_read_at is None or message.created_at > row.customer_read_at)
            ),
            channel=row.channel,
            is_urgent=row.is_urgent,
            unread_from_staff=sum(
                1
                for message in row.messages
                if not message.is_from_developer
                and (row.staff_read_at is None or message.created_at > row.staff_read_at)
            ),
            opened_by=row.opened_by,
            sender_name=name,
            sender_position=position,
            sender_position_code=self.positions.get(row.opened_by, ""),
            store_name=store,
            store_id=self.stores.get(row.opened_by),
        )


class _Telegram:
    """Şlüz sahtəsi — göndərilənləri saxlayır."""

    def __init__(self, *, message_id: int | None = 555) -> None:
        self.sent: list[TelegramOutgoing] = []
        self._message_id = message_id

    def send_support_message(self, payload: TelegramOutgoing) -> TelegramDelivery | None:
        self.sent.append(payload)
        return TelegramDelivery(telegram_message_id=self._message_id, sent_at=NOW)


@dataclass
class _Harness:
    tickets: _Tickets
    chat: SupportChatUseCase
    inbox: SupportInboxUseCase
    telegram: _Telegram
    audit: RecordingAudit
    notifier: RecordingNotifier
    clock: FakeClock
    limits: FakeSystemLimits


def _employee(
    role: SystemRole,
    *,
    flags: list[str],
    store_id: StoreId = STORE_A,
    name: str = "Murad",
) -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=role.value,
        name_az=role.value.replace("_", " ").title(),
        priority=role.default_priority,
        is_system=True,
    )
    for code in flags:
        position.grant(PermissionFlag(code=code, category="DESTEK"))
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name=name,
        last_name="Bayramov",
        store_id=store_id,
        has_pin=True,
    )


def _build(*, disabled: set[str] | None = None, limits: dict[str, str] | None = None) -> _Harness:
    tickets = _Tickets()
    telegram = _Telegram()
    audit = RecordingAudit()
    notifier = RecordingNotifier()
    clock = FakeClock(NOW)
    system_limits = FakeSystemLimits(limits)
    toggles = FakeFeatureToggles(disabled)
    chat = SupportChatUseCase(
        tickets=tickets,  # type: ignore[arg-type]
        toggles=toggles,  # type: ignore[arg-type]
        clock=clock,  # type: ignore[arg-type]
        limits=system_limits,  # type: ignore[arg-type]
        telegram=telegram,  # type: ignore[arg-type]
    )
    inbox = SupportInboxUseCase(
        tickets=tickets,  # type: ignore[arg-type]
        toggles=toggles,  # type: ignore[arg-type]
        clock=clock,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        limits=system_limits,  # type: ignore[arg-type]
        telegram=telegram,  # type: ignore[arg-type]
        notifier=notifier,  # type: ignore[arg-type]
    )
    return _Harness(
        tickets=tickets,
        chat=chat,
        inbox=inbox,
        telegram=telegram,
        audit=audit,
        notifier=notifier,
        clock=clock,
        limits=system_limits,
    )


def _seller(harness: _Harness, *, store_id: StoreId = STORE_A) -> Employee:
    actor = _employee(SystemRole.SELLER, flags=[CONTACT_SUPPORT_FLAG], store_id=store_id)
    harness.tickets.profiles[actor.id] = (actor.full_name, "Satıcı", "Yataş Babək")
    harness.tickets.positions[actor.id] = SystemRole.SELLER.value
    harness.tickets.stores[actor.id] = store_id
    return actor


# --------------------------------------------------------------------------- #
# 1. Satıcı widget-i açır → iki kanal seçimi
# --------------------------------------------------------------------------- #


def test_1_a_seller_sees_both_channels_in_the_widget() -> None:
    """Bənd 1: widget hər iki kanalı təklif edir və satıcı hər ikisini yaza bilir."""
    harness = _build()
    actor = _seller(harness)

    assert harness.chat.is_available(tenant_id=TENANT, actor=actor) is True
    # Kanal seçimi widget-in ÖZ vəziyyətidir; backend tərəfdən yoxlanan şey
    # hər iki kanalın həmin flag ilə AÇIQ olmasıdır — ayrıca «daxili yazmaq»
    # icazəsi YOXDUR (bax `value_objects/support.py`).
    for channel in SupportChannel:
        thread = harness.chat.send(
            tenant_id=TENANT, actor=actor, body=f"{channel.value} mesajı", channel=channel
        )
        assert thread.channel is channel


# --------------------------------------------------------------------------- #
# 2. Daxili müraciət → CEO-nun bölməsinə, Telegram-a GETMİR
# --------------------------------------------------------------------------- #


def test_2_an_internal_request_reaches_the_ceo_and_never_telegram() -> None:
    harness = _build()
    actor = _seller(harness)
    ceo = _employee(SystemRole.CEO, flags=[VIEW_INTERNAL_FLAG])

    harness.chat.send(
        tenant_id=TENANT,
        actor=actor,
        body="Növbəm səhv yazılıb",
        channel=SupportChannel.INTERNAL,
    )

    threads = harness.inbox.threads(tenant_id=TENANT, actor=ceo, channel=SupportChannel.INTERNAL)
    assert [thread.subject for thread in threads] == ["Növbəm səhv yazılıb"]
    assert harness.telegram.sent == [], "Daxili müraciət Telegram-a DÜŞMƏMƏLİDİR"


# --------------------------------------------------------------------------- #
# 3. Texniki müraciət → Root-un bölməsinə + Telegram-a
# --------------------------------------------------------------------------- #


def test_3_a_technical_request_reaches_root_and_telegram() -> None:
    harness = _build()
    actor = _seller(harness)
    root = _employee(SystemRole.ROOT, flags=[VIEW_TECHNICAL_FLAG])

    harness.chat.send(
        tenant_id=TENANT,
        actor=actor,
        body="Kiosk PC açılmır, PIN ekranı gəlmir.",
        channel=SupportChannel.TECHNICAL,
    )

    threads = harness.inbox.threads(tenant_id=TENANT, actor=root, channel=SupportChannel.TECHNICAL)
    assert len(threads) == 1
    assert len(harness.telegram.sent) == 1

    payload = harness.telegram.sent[0]
    assert payload.store_name == "Yataş Babək"
    assert payload.sender_position == "Satıcı"
    rendered = format_support_message(payload)
    # Faza 4: filial, ad, VƏZİFƏ və istinad MÜTLƏQ görünür.
    assert "🏪 Yataş Babək" in rendered
    assert "— Satıcı" in rendered
    assert payload.reference in rendered


# --------------------------------------------------------------------------- #
# 4. Proqramdan cavab → işçiyə çatır + Telegram-da görünür
# --------------------------------------------------------------------------- #


def test_4_an_in_app_reply_reaches_the_worker_and_telegram() -> None:
    harness = _build()
    actor = _seller(harness)
    root = _employee(SystemRole.ROOT, flags=[VIEW_TECHNICAL_FLAG])
    thread = harness.chat.send(
        tenant_id=TENANT, actor=actor, body="Proqram donur", channel=SupportChannel.TECHNICAL
    )

    harness.inbox.reply(
        tenant_id=TENANT,
        actor=root,
        channel=SupportChannel.TECHNICAL,
        ticket_id=thread.ticket_id,
        body="Baxırıq, 1 saata cavab verəcəyik",
    )

    worker_view = harness.chat.thread(tenant_id=TENANT, actor=actor, ticket_id=thread.ticket_id)
    assert worker_view.messages[-1].body == "Baxırıq, 1 saata cavab verəcəyik"
    assert worker_view.messages[-1].is_from_developer is True
    assert len(harness.telegram.sent) == 2, "Cavab da Telegram-da görünməlidir"
    assert harness.telegram.sent[-1].is_reply is True


# --------------------------------------------------------------------------- #
# 5. Telegram-dan reply → işçiyə çatır + proqramda görünür
# --------------------------------------------------------------------------- #


def test_5_a_telegram_reply_lands_in_the_thread() -> None:
    harness = _build()
    actor = _seller(harness)
    thread = harness.chat.send(
        tenant_id=TENANT, actor=actor, body="Skaner işləmir", channel=SupportChannel.TECHNICAL
    )
    reference = harness.telegram.sent[0].reference

    delivered = harness.inbox.deliver_telegram_reply(
        tenant_id=TENANT, body="Kabeli çıxarıb taxın", reference=reference
    )

    assert delivered == thread.ticket_id
    worker_view = harness.chat.thread(tenant_id=TENANT, actor=actor, ticket_id=thread.ticket_id)
    assert worker_view.messages[-1].body == "Kabeli çıxarıb taxın"
    assert worker_view.messages[-1].from_telegram is True


def test_5b_a_plain_telegram_message_is_ignored() -> None:
    """Faza 5: reply OLMAYAN mesaj GÖRMƏZDƏN GƏLİNİR."""
    update = {"update_id": 1, "message": {"text": "sabah gəlirəm"}}
    from src.infrastructure.notifications.telegram import _as_reply

    assert _as_reply(update) is None


def test_5c_an_unknown_reference_writes_nothing() -> None:
    """Naməlum istinad TƏSADÜFİ söhbətə yazılmır — mesaj SƏHV işçiyə gedərdi."""
    harness = _build()
    actor = _seller(harness)
    harness.chat.send(
        tenant_id=TENANT, actor=actor, body="Nasazlıq", channel=SupportChannel.TECHNICAL
    )

    assert (
        harness.inbox.deliver_telegram_reply(
            tenant_id=TENANT, body="cavab", reference="#msg_999999"
        )
        is None
    )


def test_5d_the_reference_is_read_from_the_replied_message() -> None:
    reply = TelegramReply(
        body="cavab",
        reference=extract_reference("... #msg_4821"),
        reply_to_message_id=7,
        update_id=9,
    )
    assert reply.reference == "#msg_4821"


# --------------------------------------------------------------------------- #
# 6. CEO: daxili GÖRÜNÜR, texniki və Telegram ayarları GÖRÜNMÜR
# --------------------------------------------------------------------------- #


def test_6_a_ceo_sees_only_the_internal_section() -> None:
    from src.application.use_cases.telegram_config import TelegramConfigUseCase

    harness = _build()
    ceo = _employee(SystemRole.CEO, flags=[VIEW_INTERNAL_FLAG])

    visible = harness.inbox.visible_channels(tenant_id=TENANT, actor=ceo)
    assert visible == [SupportChannel.INTERNAL]

    with pytest.raises(SupportAccessError):
        harness.inbox.threads(tenant_id=TENANT, actor=ceo, channel=SupportChannel.TECHNICAL)

    # Telegram ayarları: flag VERİLSƏ BELƏ CEO görməməlidir (hardlock 1 —
    # qapı `may_manage`-də İKİNCİ nüsxə kimi rol yoxlamasıdır).
    config = TelegramConfigUseCase(
        repository=_ConfigRepo(),  # type: ignore[arg-type]
        audit=harness.audit,  # type: ignore[arg-type]
        clock=harness.clock,  # type: ignore[arg-type]
    )
    ceo_with_flag = _employee(SystemRole.CEO, flags=[VIEW_INTERNAL_FLAG, MANAGE_TELEGRAM_FLAG])
    assert config.may_manage(ceo_with_flag) is False


class _ConfigRepo:
    def load(self, tenant_id: TenantId) -> Any:
        return None

    def describe(self, tenant_id: TenantId) -> Any:
        return None

    def save(self, tenant_id: TenantId, **kwargs: Any) -> None:
        return None

    def set_active(self, tenant_id: TenantId, **kwargs: Any) -> None:
        return None

    def archive(self, tenant_id: TenantId, **kwargs: Any) -> bool:
        return False


# --------------------------------------------------------------------------- #
# 7. Satıcı: yalnız widget, naviqasiyada bölmə YOX
# --------------------------------------------------------------------------- #


def test_7_a_seller_has_no_inbox_section() -> None:
    harness = _build()
    actor = _seller(harness)

    assert harness.chat.is_available(tenant_id=TENANT, actor=actor) is True
    assert harness.inbox.visible_channels(tenant_id=TENANT, actor=actor) == []


# --------------------------------------------------------------------------- #
# 8. Root fərdi override ilə HR_Admin-ə texniki bölməni açır
# --------------------------------------------------------------------------- #


def test_8_an_individual_override_opens_the_technical_section() -> None:
    harness = _build()
    hr = _employee(SystemRole.HR_ADMIN, flags=[VIEW_INTERNAL_FLAG])
    root = _employee(SystemRole.ROOT, flags=[VIEW_TECHNICAL_FLAG])

    assert SupportChannel.TECHNICAL not in harness.inbox.visible_channels(
        tenant_id=TENANT, actor=hr
    )

    hr.apply_override(
        PermissionOverride(
            flag_code=VIEW_TECHNICAL_FLAG,
            effect=PermissionEffect.GRANT,
            granted_by=root.id,
        )
    )

    assert SupportChannel.TECHNICAL in harness.inbox.visible_channels(tenant_id=TENANT, actor=hr)


# --------------------------------------------------------------------------- #
# 9. Status dövrəsi
# --------------------------------------------------------------------------- #


def test_9_the_status_cycle_follows_the_specification() -> None:
    """Bənd 9: Açıq → (oxu, DƏYİŞMİR) → Gözləmədə → işçi yazdı → Açıq."""
    harness = _build()
    actor = _seller(harness)
    root = _employee(SystemRole.ROOT, flags=[VIEW_TECHNICAL_FLAG])
    thread = harness.chat.send(
        tenant_id=TENANT, actor=actor, body="Kassa donur", channel=SupportChannel.TECHNICAL
    )
    assert thread.ticket_status is SupportTicketStatus.OPEN

    # OXUMAQ STATUSU DƏYİŞMİR — yalnız nişanı silir.
    harness.inbox.mark_read(
        tenant_id=TENANT,
        actor=root,
        channel=SupportChannel.TECHNICAL,
        ticket_id=thread.ticket_id,
    )
    after_read = harness.inbox.thread(
        tenant_id=TENANT,
        actor=root,
        channel=SupportChannel.TECHNICAL,
        ticket_id=thread.ticket_id,
    )
    assert after_read.ticket_status is SupportTicketStatus.OPEN
    assert after_read.has_unread is False

    harness.inbox.reply(
        tenant_id=TENANT,
        actor=root,
        channel=SupportChannel.TECHNICAL,
        ticket_id=thread.ticket_id,
        body="Ekranın şəklini göndərin",
    )
    waiting = harness.inbox.set_status(
        tenant_id=TENANT,
        actor=root,
        channel=SupportChannel.TECHNICAL,
        ticket_id=thread.ticket_id,
        status=SupportTicketStatus.WAITING,
    )
    assert waiting.ticket_status is SupportTicketStatus.WAITING

    # İŞÇİ CAVAB YAZDI → AVTOMATİK `OPEN`.
    reopened = harness.chat.send(
        tenant_id=TENANT, actor=actor, body="Şəkil budur", channel=SupportChannel.TECHNICAL
    )
    assert reopened.ticket_status is SupportTicketStatus.OPEN


def test_9b_a_worker_message_reopens_even_a_closed_thread() -> None:
    """Avtomatik keçid 1 «Bağlandı daxil» deyir."""
    harness = _build()
    actor = _seller(harness)
    root = _employee(SystemRole.ROOT, flags=[VIEW_TECHNICAL_FLAG])
    thread = harness.chat.send(
        tenant_id=TENANT, actor=actor, body="Nasazlıq", channel=SupportChannel.TECHNICAL
    )
    harness.inbox.set_status(
        tenant_id=TENANT,
        actor=root,
        channel=SupportChannel.TECHNICAL,
        ticket_id=thread.ticket_id,
        status=SupportTicketStatus.CLOSED,
    )

    # Bağlı söhbət `find_open_ticket`-dən çıxır, yəni YENİ müraciət açılır —
    # işçinin mesajı İTMİR və yeni müraciət `OPEN` statusdadır.
    fresh = harness.chat.send(
        tenant_id=TENANT, actor=actor, body="Yenə təkrarlandı", channel=SupportChannel.TECHNICAL
    )
    assert fresh.ticket_id != thread.ticket_id
    assert fresh.ticket_status is SupportTicketStatus.OPEN


# --------------------------------------------------------------------------- #
# 10. Avtomatik bağlanma
# --------------------------------------------------------------------------- #


def test_10_resolved_tickets_close_after_the_root_period() -> None:
    harness = _build(limits={"SUPPORT_AUTO_CLOSE_DAYS": "3"})
    actor = _seller(harness)
    root = _employee(SystemRole.ROOT, flags=[VIEW_TECHNICAL_FLAG])
    thread = harness.chat.send(
        tenant_id=TENANT, actor=actor, body="Printer", channel=SupportChannel.TECHNICAL
    )
    harness.inbox.set_status(
        tenant_id=TENANT,
        actor=root,
        channel=SupportChannel.TECHNICAL,
        ticket_id=thread.ticket_id,
        status=SupportTicketStatus.RESOLVED,
    )

    # Müddət BİTMƏMİŞ — heç nə bağlanmır.
    early = harness.inbox.run_maintenance(tenant_id=TENANT, now=NOW + timedelta(days=2))
    assert early["closed"] == 0

    late = harness.inbox.run_maintenance(tenant_id=TENANT, now=NOW + timedelta(days=4))
    assert late["closed"] == 1
    assert harness.tickets.rows[thread.ticket_id].status is SupportTicketStatus.CLOSED
    assert "SUPPORT_TICKET_AUTO_CLOSED" in harness.audit.actions()


def test_10b_a_waiting_ticket_reminds_the_worker_once() -> None:
    harness = _build(limits={"SUPPORT_WAITING_REMINDER_DAYS": "2"})
    actor = _seller(harness)
    root = _employee(SystemRole.ROOT, flags=[VIEW_TECHNICAL_FLAG])
    thread = harness.chat.send(
        tenant_id=TENANT, actor=actor, body="Ölçü", channel=SupportChannel.TECHNICAL
    )
    harness.inbox.set_status(
        tenant_id=TENANT,
        actor=root,
        channel=SupportChannel.TECHNICAL,
        ticket_id=thread.ticket_id,
        status=SupportTicketStatus.WAITING,
    )

    first = harness.inbox.run_maintenance(tenant_id=TENANT, now=NOW + timedelta(days=3))
    second = harness.inbox.run_maintenance(tenant_id=TENANT, now=NOW + timedelta(days=4))

    assert first["reminded"] == 1
    assert second["reminded"] == 0, "Xatırlatma TƏKRARLANMAMALIDIR"
    assert len(harness.notifier.messages) == 1


# --------------------------------------------------------------------------- #
# 11. Naviqasiya sayğacı
# --------------------------------------------------------------------------- #


def test_11_the_badge_counts_only_open_tickets() -> None:
    harness = _build()
    actor = _seller(harness)
    root = _employee(SystemRole.ROOT, flags=[VIEW_TECHNICAL_FLAG])
    first = harness.chat.send(
        tenant_id=TENANT, actor=actor, body="Birinci", channel=SupportChannel.TECHNICAL
    )
    assert (
        harness.inbox.actionable_count(
            tenant_id=TENANT, actor=root, channel=SupportChannel.TECHNICAL
        )
        == 1
    )

    for status in (
        SupportTicketStatus.WAITING,
        SupportTicketStatus.RESOLVED,
        SupportTicketStatus.CLOSED,
    ):
        harness.inbox.set_status(
            tenant_id=TENANT,
            actor=root,
            channel=SupportChannel.TECHNICAL,
            ticket_id=first.ticket_id,
            status=status,
        )
        assert (
            harness.inbox.actionable_count(
                tenant_id=TENANT, actor=root, channel=SupportChannel.TECHNICAL
            )
            == 0
        ), f"«{status.label_az}» sayğaca DÜŞMƏMƏLİDİR"


def test_11b_the_badge_is_zero_without_the_flag() -> None:
    harness = _build()
    actor = _seller(harness)
    harness.chat.send(
        tenant_id=TENANT, actor=actor, body="Nasazlıq", channel=SupportChannel.TECHNICAL
    )
    stranger = _employee(SystemRole.STORE_MANAGER, flags=[])

    assert (
        harness.inbox.actionable_count(
            tenant_id=TENANT, actor=stranger, channel=SupportChannel.TECHNICAL
        )
        == 0
    )


# --------------------------------------------------------------------------- #
# 12. Süzgəclər — ayrıca VƏ kombinə
# --------------------------------------------------------------------------- #


def _two_stores(harness: _Harness) -> tuple[Employee, Employee]:
    seller = _seller(harness, store_id=STORE_A)
    manager = _employee(
        SystemRole.STORE_MANAGER, flags=[CONTACT_SUPPORT_FLAG], store_id=STORE_B, name="Elvin"
    )
    harness.tickets.profiles[manager.id] = (manager.full_name, "Mağaza Meneceri", "Yataş Mərkəzi")
    harness.tickets.positions[manager.id] = SystemRole.STORE_MANAGER.value
    harness.tickets.stores[manager.id] = STORE_B
    return seller, manager


def test_12_each_filter_narrows_the_list() -> None:
    harness = _build()
    seller, manager = _two_stores(harness)
    root = _employee(SystemRole.ROOT, flags=[VIEW_TECHNICAL_FLAG])
    harness.chat.send(
        tenant_id=TENANT, actor=seller, body="Satıcı problemi", channel=SupportChannel.TECHNICAL
    )
    harness.chat.send(
        tenant_id=TENANT, actor=manager, body="Menecer problemi", channel=SupportChannel.TECHNICAL
    )

    def names(filters: InboxFilter) -> set[str]:
        return {
            thread.sender_name
            for thread in harness.inbox.threads(
                tenant_id=TENANT, actor=root, channel=SupportChannel.TECHNICAL, filters=filters
            )
        }

    assert names(InboxFilter()) == {seller.full_name, manager.full_name}
    assert names(InboxFilter(store_ids=(STORE_B,))) == {manager.full_name}
    assert names(InboxFilter(position_codes=(SystemRole.SELLER.value,))) == {seller.full_name}
    assert names(InboxFilter(search="Menecer problemi")) == {manager.full_name}
    assert names(InboxFilter(status=SupportTicketStatus.CLOSED)) == set()


def test_12b_filters_combine_instead_of_replacing_each_other() -> None:
    """tg1.md-nin AÇIQ tələbi: filial + vəzifə + status + oxunmamış BİRLİKDƏ."""
    harness = _build()
    seller, manager = _two_stores(harness)
    root = _employee(SystemRole.ROOT, flags=[VIEW_TECHNICAL_FLAG])
    harness.chat.send(
        tenant_id=TENANT, actor=seller, body="Satıcı problemi", channel=SupportChannel.TECHNICAL
    )
    harness.chat.send(
        tenant_id=TENANT, actor=manager, body="Menecer problemi", channel=SupportChannel.TECHNICAL
    )

    combined = InboxFilter(
        status=SupportTicketStatus.OPEN,
        store_ids=(STORE_B,),
        position_codes=(SystemRole.STORE_MANAGER.value,),
        unread_only=True,
        search="problemi",
    )
    threads = harness.inbox.threads(
        tenant_id=TENANT, actor=root, channel=SupportChannel.TECHNICAL, filters=combined
    )
    assert [thread.sender_name for thread in threads] == [manager.full_name]

    # BİR şərti pozan kəsim BOŞ nəticə verir — süzgəclər bir-birini ƏVƏZ
    # ETSƏYDİ, aşağıdakı sorğu yenə bir sətir qaytarardı.
    contradictory = InboxFilter(
        store_ids=(STORE_A,), position_codes=(SystemRole.STORE_MANAGER.value,)
    )
    assert (
        harness.inbox.threads(
            tenant_id=TENANT,
            actor=root,
            channel=SupportChannel.TECHNICAL,
            filters=contradictory,
        )
        == []
    )


def test_12c_status_counts_ignore_the_status_filter_itself() -> None:
    """Zolaqdakı `🔴 Açıq (N)` sayı seçilməmiş bəndlərdə də doğru olmalıdır."""
    harness = _build()
    actor = _seller(harness)
    root = _employee(SystemRole.ROOT, flags=[VIEW_TECHNICAL_FLAG])
    first = harness.chat.send(
        tenant_id=TENANT, actor=actor, body="Birinci", channel=SupportChannel.TECHNICAL
    )
    harness.inbox.set_status(
        tenant_id=TENANT,
        actor=root,
        channel=SupportChannel.TECHNICAL,
        ticket_id=first.ticket_id,
        status=SupportTicketStatus.RESOLVED,
    )

    counts = harness.inbox.status_counts(
        tenant_id=TENANT,
        actor=root,
        channel=SupportChannel.TECHNICAL,
        filters=InboxFilter(status=SupportTicketStatus.OPEN),
    )
    assert counts[SupportTicketStatus.RESOLVED] == 1
    assert counts[SupportTicketStatus.OPEN] == 0


def test_12d_clearing_filters_returns_the_full_list() -> None:
    harness = _build()
    seller, manager = _two_stores(harness)
    root = _employee(SystemRole.ROOT, flags=[VIEW_TECHNICAL_FLAG])
    harness.chat.send(
        tenant_id=TENANT, actor=seller, body="Birinci", channel=SupportChannel.TECHNICAL
    )
    harness.chat.send(
        tenant_id=TENANT, actor=manager, body="İkinci", channel=SupportChannel.TECHNICAL
    )

    empty = InboxFilter()
    assert empty.is_empty is True
    assert (
        len(
            harness.inbox.threads(
                tenant_id=TENANT, actor=root, channel=SupportChannel.TECHNICAL, filters=empty
            )
        )
        == 2
    )
    assert InboxFilter(store_ids=(STORE_A,)).is_empty is False


# --------------------------------------------------------------------------- #
# Əlavə struktur zəmanətləri
# --------------------------------------------------------------------------- #


def test_a_closed_thread_does_not_push_to_telegram_again() -> None:
    """Faza 7.2: bağlanmış söhbət Telegram-a TƏKRAR göndərilmir."""
    harness = _build()
    actor = _seller(harness)
    root = _employee(SystemRole.ROOT, flags=[VIEW_TECHNICAL_FLAG])
    thread = harness.chat.send(
        tenant_id=TENANT, actor=actor, body="Nasazlıq", channel=SupportChannel.TECHNICAL
    )
    harness.inbox.set_status(
        tenant_id=TENANT,
        actor=root,
        channel=SupportChannel.TECHNICAL,
        ticket_id=thread.ticket_id,
        status=SupportTicketStatus.CLOSED,
    )
    sent_before = len(harness.telegram.sent)

    harness.inbox.reply(
        tenant_id=TENANT,
        actor=root,
        channel=SupportChannel.TECHNICAL,
        ticket_id=thread.ticket_id,
        body="Qeyd: arxivə düşdü",
    )

    assert len(harness.telegram.sent) == sent_before


def test_urgent_only_mode_filters_ordinary_messages() -> None:
    """Faza 7.1: `YALNIZ TƏCİLİ` rejimində adi müraciət Telegram-a getmir."""
    harness = _build(limits={"TELEGRAM_NOTIFY_MODE": "YALNIZ TƏCİLİ"})
    actor = _seller(harness)

    harness.chat.send(
        tenant_id=TENANT, actor=actor, body="Adi sual", channel=SupportChannel.TECHNICAL
    )
    assert harness.telegram.sent == []

    harness.chat.send(
        tenant_id=TENANT,
        actor=actor,
        body="MAĞAZA BAĞLIDIR",
        channel=SupportChannel.TECHNICAL,
        urgent=True,
    )
    assert len(harness.telegram.sent) == 1


def test_disabled_mode_keeps_the_message_in_the_app() -> None:
    """`DEAKTİV` mesajı SİLMİR — yalnız Telegram-a göndərmir."""
    harness = _build(limits={"TELEGRAM_NOTIFY_MODE": "DEAKTİV"})
    actor = _seller(harness)
    root = _employee(SystemRole.ROOT, flags=[VIEW_TECHNICAL_FLAG])

    harness.chat.send(
        tenant_id=TENANT, actor=actor, body="Nasazlıq", channel=SupportChannel.TECHNICAL
    )

    assert harness.telegram.sent == []
    assert (
        len(harness.inbox.threads(tenant_id=TENANT, actor=root, channel=SupportChannel.TECHNICAL))
        == 1
    )


def test_a_channel_cannot_be_read_through_the_other_section() -> None:
    """Kanal ayrılığı TƏK sətirlik keçidlə də yan keçilməməlidir."""
    harness = _build()
    actor = _seller(harness)
    ceo = _employee(SystemRole.CEO, flags=[VIEW_INTERNAL_FLAG])
    technical = harness.chat.send(
        tenant_id=TENANT, actor=actor, body="Texniki", channel=SupportChannel.TECHNICAL
    )

    with pytest.raises(SupportAccessError):
        harness.inbox.thread(
            tenant_id=TENANT,
            actor=ceo,
            channel=SupportChannel.INTERNAL,
            ticket_id=technical.ticket_id,
        )


def test_a_worker_cannot_read_another_workers_thread() -> None:
    harness = _build()
    first = _seller(harness)
    second = _employee(
        SystemRole.SELLER, flags=[CONTACT_SUPPORT_FLAG], store_id=STORE_B, name="Aysel"
    )
    thread = harness.chat.send(
        tenant_id=TENANT, actor=first, body="Şəxsi", channel=SupportChannel.INTERNAL
    )

    with pytest.raises(SupportAccessError):
        harness.chat.thread(tenant_id=TENANT, actor=second, ticket_id=thread.ticket_id)


def test_the_module_toggle_closes_both_ends() -> None:
    harness = _build(disabled={"SUPPORT_CHAT"})
    actor = _seller(harness)
    root = _employee(SystemRole.ROOT, flags=[VIEW_TECHNICAL_FLAG])

    assert harness.chat.is_available(tenant_id=TENANT, actor=actor) is False
    assert harness.inbox.visible_channels(tenant_id=TENANT, actor=root) == []
    assert harness.inbox.run_maintenance(tenant_id=TENANT) == {"closed": 0, "reminded": 0}


def test_a_missing_ticket_is_reported_not_guessed() -> None:
    harness = _build()
    root = _employee(SystemRole.ROOT, flags=[VIEW_TECHNICAL_FLAG])

    from src.application.use_cases.support_chat import TicketNotFoundError

    with pytest.raises(TicketNotFoundError):
        harness.inbox.thread(
            tenant_id=TENANT,
            actor=root,
            channel=SupportChannel.TECHNICAL,
            ticket_id=new_support_ticket_id(),
        )


def test_an_attachment_travels_to_telegram_as_bytes() -> None:
    """Faza 4: «Şəkil əlavəsi varsa, Telegram-a da göndərilsin».

    URL DEYİL, BAYTLAR: Drive linki ictimai deyil və Telegram serveri onu
    yükləyə bilməzdi (bax `TelegramOutgoing.attachment` şərhi).
    """
    harness = _build()
    actor = _seller(harness)

    harness.chat.send(
        tenant_id=TENANT,
        actor=actor,
        body="Ekranın şəkli",
        channel=SupportChannel.TECHNICAL,
        attachment=b"fake-png-bytes",
        attachment_name="ekran.png",
    )

    payload = harness.telegram.sent[0]
    assert payload.attachment == b"fake-png-bytes"
    assert payload.attachment_name == "ekran.png"


def test_the_attachment_name_is_visible_before_the_upload_finishes() -> None:
    """Yüklənməmiş şəkil GİZLƏDİLMİR — cavab verən onun mövcudluğunu bilməlidir."""
    harness = _build()
    actor = _seller(harness)
    root = _employee(SystemRole.ROOT, flags=[VIEW_TECHNICAL_FLAG])

    thread = harness.chat.send(
        tenant_id=TENANT,
        actor=actor,
        body="Şəkil əlavə etdim",
        channel=SupportChannel.TECHNICAL,
        attachment=b"bytes",
        attachment_name="ekran.png",
    )
    message = thread.messages[-1]
    assert message.has_attachment is True
    assert message.attachment_ref == "", "İstinad YALNIZ yükləmədən sonra dolur"

    # Fon işçisi yükləməni bitirdi.
    harness.tickets.attach_file(
        message.message_id, reference="GOOGLE_DRIVE:-:file-1", filename="ekran.png"
    )
    refreshed = harness.inbox.thread(
        tenant_id=TENANT,
        actor=root,
        channel=SupportChannel.TECHNICAL,
        ticket_id=thread.ticket_id,
    )
    assert refreshed.messages[-1].attachment_ref == "GOOGLE_DRIVE:-:file-1"


def test_a_storage_reference_survives_the_text_round_trip() -> None:
    """`attachment_ref` mətn sütunudur — geri çevirmə İTKİSİZ olmalıdır."""
    import uuid as _uuid

    from src.domain.value_objects.storage import StorageReference

    original = StorageReference.drive(file_id="1a:2b-cD_e", connection_id=_uuid.UUID(int=7))
    restored = StorageReference.from_cache_key(str(original))

    assert restored.file_id == original.file_id, "İki nöqtəli ID KƏSİLMƏMƏLİDİR"
    assert restored.connection_id == original.connection_id
    assert restored.provider is original.provider
