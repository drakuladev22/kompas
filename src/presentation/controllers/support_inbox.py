"""«Daxili Müraciətlər» və «Texniki Dəstək» bölmələrinin canlı yolu (CHAT-1).

──────────────────────────────────────────────────────────────────────────────
BİR KONTROLLER, İKİ BÖLMƏ
──────────────────────────────────────────────────────────────────────────────
Ekran kimi kontroller də TƏKdir və kanalı ekrandan oxuyur
(`screen.channel`). İki ayrı kontroller yazsaydıq, «cavab yaz» axını iki
yerdə təkrarlanardı və Telegram itələməsi yalnız birində olardı.

──────────────────────────────────────────────────────────────────────────────
SESSİYA SAXLANMIR
──────────────────────────────────────────────────────────────────────────────
Bölmə saatlarla açıq qala bilər; hər əməliyyat üçün yeni sessiya açılır və
commit edilir (eyni səbəb `controllers/notifications.py`-dadır: uzun-ömürlü
tranzaksiya bu müddət boyu kilid saxlayardı).

──────────────────────────────────────────────────────────────────────────────
TELEGRAM SORĞUSU BURADADIR, ÖRTÜKDƏ YOX
──────────────────────────────────────────────────────────────────────────────
`getUpdates` bir yeniliyi YALNIZ BİR dəfə verir (bax
`infrastructure/notifications/telegram.py` başlığı). Sorğunu örtükdə
(hər istifadəçidə) işə salsaydıq, cavab hansı maşının növbəsinə düşdüsə
orada görünərdi. Ona görə taymer YALNIZ texniki bölmə açıq olanda işləyir —
o bölmə isə `can_view_technical_support` ilə qorunur.

Taymer ekranla birlikdə ölür: `QTimer` valideyni ekrandır.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QTimer

from src.application.use_cases.support_chat import InboxFilter
from src.domain.value_objects.identifiers import StoreId, SupportTicketId
from src.domain.value_objects.support import SupportTicketStatus
from src.presentation.screens.support_inbox import (
    RANGE_CUSTOM,
    RANGE_MONTH,
    RANGE_TODAY,
    RANGE_WEEK,
)
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.application.use_cases.support_chat import SupportThread
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext
    from src.presentation.screens.support_inbox import SupportInboxScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

GENERIC_ERROR = "Əməliyyat tamamlanmadı. Yenidən cəhd edin."

#: Naməlum ID formatında gələn sətir — istifadəçiyə görünən cavab.
#:
#: Ekran ID-ni ÖZÜ verir (siyahıdan), yəni bura yalnız proqram xətası və ya
#: köhnəlmiş siyahı gətirə bilər. Sükutla buraxmaq «düyməni basdım, heç nə
#: olmadı» vəziyyəti yaradardı.
UNKNOWN_TICKET = "Müraciət tapılmadı — siyahını yeniləyin."


class SupportInboxController:
    """Gələnlər qutusunu `SupportInboxUseCase`-ə bağlayır."""

    def __init__(
        self,
        context: ApplicationContext,
        actor: Employee,
        *,
        poller: Any = None,
        poll_interval_ms: int = 0,
        executor: Any = None,
        on_counts_changed: Any = None,
    ) -> None:
        # `poller` İSTƏYƏ BAĞLIDIR: Telegram qurulmayıbsa (müştərilərin çoxu)
        # bölmə tam işləyir, sadəcə xarici cavab gəlmir.
        self._context = context
        self._actor = actor
        self._poller = poller
        self._poll_interval_ms = poll_interval_ms
        self._timer: QTimer | None = None
        # `executor` YALNIZ TEST ÜÇÜNDÜR (`InlineExecutor`): fon işi olmadan
        # dialoqun açılmasını yoxlamaq mümkün olmazdı.
        self._executor = executor
        # Fon işinə istinad SAXLANILIR — `run_job` başlığındakı təhlükə:
        # istinadsız `BackgroundTask` zibil yığanı tərəfindən siqnal
        # çatmamış silinə bilər.
        self._task: Any = None
        # Naviqasiya sayğacı YALNIZ girişdə doldurulsaydı, cavab yazıb
        # statusu dəyişdikdən sonra sol paneldəki rəqəm KÖHNƏ qalardı və
        # istifadəçi «hələ də 3 iş var» sanardı. Geri çağırış hər oxunuşdan
        # sonra onu yeniləyir.
        self._on_counts_changed = on_counts_changed

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: SupportInboxScreen) -> None:
        screen.thread_selected.connect(lambda key: self._open_thread(screen, key))
        screen.reply_requested.connect(lambda payload: self._on_reply(screen, payload))
        screen.status_change_requested.connect(lambda payload: self._on_status(screen, payload))
        screen.filters_changed.connect(lambda _: self.refresh(screen))
        screen.refresh_requested.connect(lambda: self.refresh(screen))
        screen.attachment_requested.connect(lambda payload: self._on_attachment(screen, payload))
        self._load_options(screen)
        self.refresh(screen)
        self._start_polling(screen)

    def _start_polling(self, screen: SupportInboxScreen) -> None:
        """Telegram cavablarını dövri yoxlayır — YALNIZ texniki bölmədə."""
        if self._poller is None or not screen.channel.notifies_telegram:
            return
        if self._poll_interval_ms <= 0:
            return
        timer = QTimer(screen)
        timer.setInterval(self._poll_interval_ms)
        timer.timeout.connect(lambda: self.poll_telegram(screen))
        timer.start()
        self._timer = timer

    # -------------------------------- oxuma ---------------------------------- #

    def refresh(self, screen: SupportInboxScreen) -> None:
        """Siyahını, sayları və seçilmiş söhbəti yenidən oxuyur.

        SAYLAR SİYAHI İLƏ EYNİ SESSİYADADIR: ayrı sessiyada oxusaydıq,
        aradakı yeni mesaj `🔴 Açıq (12)` yazan zolaqla 11 sətirlik siyahını
        eyni anda göstərə bilərdi.
        """
        applied = self._filters_of(screen)
        try:
            with self._context.session(user_id=self._actor.id) as session:
                threads = session.support_inbox.threads(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    channel=screen.channel,
                    filters=applied,
                )
                counts = session.support_inbox.status_counts(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    channel=screen.channel,
                    filters=applied,
                )
        except KompasOSError as error:
            screen.set_message(error.user_message, error=True)
            return
        except Exception:
            _error_log.exception("SUPPORT_INBOX_LOAD_FAILED")
            screen.set_message(GENERIC_ERROR, error=True)
            return

        screen.set_status_counts(counts)
        screen.set_threads([_row(thread) for thread in threads])
        selected = screen.selected_ticket_id()
        current = next((t for t in threads if str(t.ticket_id) == selected), None)
        # SEÇİM İTİRİLMİR: süzgəc dəyişəndə seçilmiş söhbət siyahıdan çıxa
        # bilər — o halda sağ panel boşalır, çünki göstərilən söhbətin
        # siyahıda görünməməsi istifadəçini çaşdırardı.
        screen.set_thread(_detail(current) if current is not None else None)
        screen.set_message("")
        if self._on_counts_changed is not None:
            try:
                self._on_counts_changed()
            except Exception:
                # Sayğacın yenilənməməsi bölməni dayandırmır — yalnız iz qalır.
                _error_log.exception("SUPPORT_BADGE_CALLBACK_FAILED")

    def _filters_of(self, screen: SupportInboxScreen) -> InboxFilter:
        """Ekranın xam sözlüyünü tətbiq qatının strukturuna çevirir.

        TARİX BURADA HESABLANIR, EKRANDA YOX: ekran `datetime.now()`
        çağırmır (CLAUDE.md §4 qaydasının təqdimat tərəfi) — o, yalnız
        «Bu həftə» sözünü verir, sərhədi kontroller qoyur.
        """
        raw = screen.filters()
        status_value = str(raw.get("status") or "")
        return InboxFilter(
            status=SupportTicketStatus.parse(status_value) if status_value else None,
            store_ids=tuple(
                store for store in (_store_id(item) for item in raw.get("store_ids", [])) if store
            ),
            position_codes=tuple(str(code) for code in raw.get("position_codes", [])),
            created_from=_range_start(
                str(raw.get("range") or ""), custom=str(raw.get("custom_from") or "")
            ),
            created_to=_range_end(
                str(raw.get("range") or ""), custom=str(raw.get("custom_to") or "")
            ),
            unread_only=bool(raw.get("unread_only")),
            search=str(raw.get("search") or ""),
            newest_first=bool(raw.get("newest_first", True)),
        )

    def _open_thread(self, screen: SupportInboxScreen, ticket_id: str) -> None:
        parsed = _ticket_id(ticket_id)
        if parsed is None:
            screen.set_message(UNKNOWN_TICKET, error=True)
            return
        try:
            with self._context.session(user_id=self._actor.id) as session:
                thread = session.support_inbox.thread(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    channel=screen.channel,
                    ticket_id=parsed,
                )
                # Açılış = oxundu. Nişan yalnız burada sıfırlanır, siyahı
                # yüklənəndə YOX: siyahını açmaq mesajı oxumaq demək deyil.
                session.support_inbox.mark_read(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    channel=screen.channel,
                    ticket_id=parsed,
                )
                session.commit()
        except KompasOSError as error:
            screen.set_message(error.user_message, error=True)
            return
        except Exception:
            _error_log.exception("SUPPORT_THREAD_OPEN_FAILED")
            screen.set_message(GENERIC_ERROR, error=True)
            return
        screen.set_thread(_detail(thread))
        screen.set_message("")

    def _load_options(self, screen: SupportInboxScreen) -> None:
        """Filial və vəzifə süzgəclərinin siyahıları.

        Uğursuzluq EKRANI DAYANDIRMIR: süzgəclər boş qalır, söhbətlər isə
        normal görünür — onlar köməkçi vasitədir, məzmun deyil.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                # `session.uow.connection` — layihənin mövcud naxışı
                # (`controllers/devices.py::_store_options` eyni sorğunu edir).
                rows = session.uow.connection.execute(
                    "SELECT id, name FROM stores WHERE tenant_id = %s AND is_active ORDER BY name",
                    (str(session.tenant_id),),
                ).fetchall()
                positions = session.support_inbox.position_options(
                    tenant_id=session.tenant_id, actor=self._actor
                )
        except Exception:
            _error_log.exception("SUPPORT_INBOX_OPTIONS_FAILED")
            return
        screen.set_stores([(str(row["id"]), str(row["name"])) for row in rows])
        screen.set_positions(list(positions))

    # -------------------------------- yazı ----------------------------------- #

    def _on_reply(self, screen: SupportInboxScreen, payload: dict[str, Any]) -> None:
        parsed = _ticket_id(str(payload.get("ticket_id", "")))
        body = str(payload.get("body", ""))
        if parsed is None:
            screen.set_message(UNKNOWN_TICKET, error=True)
            return
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.support_inbox.reply(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    channel=screen.channel,
                    ticket_id=parsed,
                    body=body,
                )
                session.commit()
        except KompasOSError as error:
            screen.set_message(error.user_message, error=True)
            return
        except Exception:
            _error_log.exception("SUPPORT_REPLY_FAILED")
            screen.set_message(GENERIC_ERROR, error=True)
            return
        self._open_thread(screen, str(parsed))
        self.refresh(screen)

    def _on_status(self, screen: SupportInboxScreen, payload: dict[str, Any]) -> None:
        parsed = _ticket_id(str(payload.get("ticket_id", "")))
        if parsed is None:
            screen.set_message(UNKNOWN_TICKET, error=True)
            return
        status = SupportTicketStatus.parse(str(payload.get("status") or ""))
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.support_inbox.set_status(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    channel=screen.channel,
                    ticket_id=parsed,
                    status=status,
                )
                session.commit()
        except KompasOSError as error:
            screen.set_message(error.user_message, error=True)
            return
        except Exception:
            _error_log.exception("SUPPORT_STATUS_FAILED")
            screen.set_message(GENERIC_ERROR, error=True)
            return
        # YALNIZ `refresh`: söhbət yenidən oxunmur, çünki status dəyişikliyi
        # onu cari süzgəcdən ÇIXARA bilər (məs. `🔴 Açıq` süzgəcində «Həll
        # Olundu» basıldı). Əvvəlcə açıb sonra siyahıdan silmək paneli bir
        # anlıq göstərib söndürərdi — `refresh` düzgün son vəziyyəti verir.
        self.refresh(screen)

    def _on_attachment(self, screen: SupportInboxScreen, payload: dict[str, Any]) -> None:
        """Şəkli Drive-dan FON SAPINDA endirir və dialoqda göstərir.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ FON SAPI
        ──────────────────────────────────────────────────────────────────────
        Endirmə şəbəkə əməliyyatıdır (bir neçə MB) və GUI sapında icra
        olunsaydı, pəncərə həmin müddət ərzində «cavab vermir» görünərdi.
        Dialoq isə YALNIZ GUI sapında açıla bilər — ona görə iş bölünür:
        baytlar fonda gəlir, `show_attachment` geri çağırışda göstərir
        (eyni naxış `controllers/report_export.py`-dədir).
        """
        from src.presentation.background_task import run_job  # noqa: PLC0415

        reference = str(payload.get("reference") or "")
        name = str(payload.get("name") or "")
        if not reference:
            return
        screen.set_message("Şəkil yüklənir…")
        self._task = run_job(
            lambda: self._download_attachment(reference),
            on_success=lambda content: self._attachment_ready(screen, name, content),
            on_failure=lambda _error: screen.set_message(
                "Şəkil yüklənmədi — Drive bağlantısını yoxlayın.", error=True
            ),
            owner=screen,
            name="SUPPORT_ATTACHMENT_DOWNLOAD",
            executor=self._executor,
        )

    def _download_attachment(self, reference: str) -> bytes:
        """Drive-dan baytları gətirir — FON SAPINDA icra olunur."""
        from src.domain.value_objects.storage import StorageReference  # noqa: PLC0415

        providers = self._context.drive_providers(max_upload_bytes=self._max_upload_bytes())
        if providers is None:
            raise RuntimeError("Drive bağlantısı qurulmayıb")
        parsed = StorageReference.from_cache_key(reference)
        return bytes(providers.active().get_image_bytes(parsed))

    def _max_upload_bytes(self) -> int:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                return int(session.max_upload_bytes())
        except Exception:
            _error_log.exception("SUPPORT_ATTACHMENT_LIMIT_FAILED")
            return 5 * 1024 * 1024

    def _attachment_ready(self, screen: SupportInboxScreen, name: str, content: Any) -> None:
        screen.set_message("")
        screen.show_attachment(name, bytes(content))

    # ----------------------------- Telegram → proqram ------------------------ #

    def poll_telegram(self, screen: SupportInboxScreen) -> int:
        """Telegram-dan gələn cavabları söhbətlərə yazır. Nəticə: sayı.

        Uğursuzluq SÜKUTLA buraxılır: bu, istifadəçinin başlatdığı əməliyyat
        deyil, arxa fondakı dövrədir və hər taymer tetiklənməsində xəta
        sətri göstərmək bölməni oxunmaz edərdi. Səbəb jurnaldadır.
        """
        if self._poller is None:
            return 0
        try:
            replies = self._poller.poll()
        except Exception:
            _error_log.exception("TELEGRAM_POLL_FAILED")
            return 0
        if not replies:
            return 0

        delivered = 0
        try:
            with self._context.session(user_id=self._actor.id) as session:
                for reply in replies:
                    ticket_id = session.support_inbox.deliver_telegram_reply(
                        tenant_id=session.tenant_id,
                        body=reply.body,
                        reference=reply.reference,
                        telegram_message_id=reply.reply_to_message_id,
                    )
                    if ticket_id is not None:
                        delivered += 1
                session.commit()
        except Exception:
            _error_log.exception("TELEGRAM_REPLY_DELIVERY_FAILED")
            return 0
        if delivered:
            self.refresh(screen)
        return delivered


def _row(thread: SupportThread) -> dict[str, Any]:
    """Sol paneldəki bir sətir."""
    last = thread.last_message
    return {
        "ticket_id": str(thread.ticket_id),
        "sender_name": thread.sender_name,
        "sender_position": thread.sender_position,
        "store_name": thread.store_name,
        "preview": last.body if last is not None else thread.subject,
        "time": last.created_at.strftime("%d.%m %H:%M") if last is not None else "",
        "unread": thread.has_unread,
        "status": thread.ticket_status.value,
        "is_urgent": thread.is_urgent,
    }


def _range_start(label: str, *, custom: str = "") -> datetime | None:
    """«Bu gün / Bu həftə / Bu ay / Xüsusi» → başlanğıc anı. Naməlum söz → `None`.

    HƏFTƏ BAZAR ERTƏSİNDƏN başlayır (`weekday()` 0 = bazar ertəsi):
    Azərbaycanda iş həftəsinin başlanğıcı budur və «bu həftə» süzgəci məhz
    iş həftəsini nəzərdə tutur.
    """
    if label == RANGE_CUSTOM:
        return _parse_date(custom)
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    if label == RANGE_TODAY:
        return midnight
    if label == RANGE_WEEK:
        return midnight - timedelta(days=midnight.weekday())
    if label == RANGE_MONTH:
        return midnight.replace(day=1)
    return None


def _range_end(label: str, *, custom: str = "") -> datetime | None:
    """Yuxarı sərhəd — YALNIZ «Xüsusi aralıq»da.

    Hazır bəndlərin («bu gün», «bu həftə») yuxarı sərhədi İNDİdir və onu
    açıq yazmaq lazımsızdır: gələcək tarixli müraciət mövcud deyil.

    SEÇİLƏN GÜN TAM DAXİLDİR: sərhəd həmin günün 23:59:59-udur, gecə
    yarısı deyil — əks halda «1-dən 5-ə» seçimi 5-ci gün yazılan müraciəti
    sükutla kənarda qoyardı.
    """
    if label != RANGE_CUSTOM:
        return None
    parsed = _parse_date(custom)
    return None if parsed is None else parsed + timedelta(days=1) - timedelta(seconds=1)


def _parse_date(raw: str) -> datetime | None:
    """`YYYY-MM-DD` → gecə yarısı (UTC). Yararsız sətir → `None`."""
    try:
        return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def _detail(thread: SupportThread) -> dict[str, Any]:
    """Sağ paneldəki tam söhbət.

    `outgoing=is_from_developer` — bu ekranda CAVABLAYAN tərəf «biz»ik,
    yəni işçinin mesajı GƏLƏN, cavab isə ÇIXAN balondur. İşçinin öz
    panelində (`SupportChatWidget`) bu, tam TƏRSİdir və məhz ona görə
    çevirmə ekranda deyil, hər kontrollerdə ayrıca yazılır.
    """
    return {
        "ticket_id": str(thread.ticket_id),
        "subject": thread.subject,
        "sender_name": thread.sender_name,
        "sender_position": thread.sender_position,
        "store_name": thread.store_name,
        "status": thread.ticket_status.value,
        "is_urgent": thread.is_urgent,
        "messages": [
            {
                "body": message.body,
                "outgoing": message.is_from_developer,
                "telegram_sent_at": (
                    message.telegram_sent_at.strftime("%H:%M")
                    if message.telegram_sent_at is not None
                    else ""
                ),
                "from_telegram": message.from_telegram,
                "attachment_ref": message.attachment_ref,
                "attachment_name": message.attachment_name,
            }
            for message in thread.messages
        ],
    }


def _ticket_id(raw: str) -> SupportTicketId | None:
    """Mətn ID-ni tiplənmiş İD-yə çevirir; yararsızdırsa `None`."""
    try:
        return SupportTicketId(uuid.UUID(raw))
    except (ValueError, AttributeError, TypeError):
        return None


def _store_id(raw: str) -> StoreId | None:
    if not raw:
        return None
    try:
        return StoreId(uuid.UUID(raw))
    except (ValueError, AttributeError, TypeError):
        return None


__all__ = ["GENERIC_ERROR", "UNKNOWN_TICKET", "SupportInboxController"]
