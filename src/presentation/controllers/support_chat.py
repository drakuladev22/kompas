"""Üzən dəstək panelinin CANLI yolu — `SupportChatUseCase` (bölmə 8).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU KONTROLLER İNDİ YAZILIR
──────────────────────────────────────────────────────────────────────────────
`SupportChatWidget` maketdən bəri mövcud idi və `message_sent` siqnalını
yayırdı, LAKİN canlı rejimdə həmin siqnal HEÇ NƏYƏ bağlı deyildi: istifadəçi
mesaj yazır, göndər düyməsini basır, mesaj ekranda görünür — və heç yerə
getmir. «Yardım Mərkəzi»-nin `[Dəstəyə yaz]` düyməsi məhz bu paneli açdığına
görə boşluq daha da görünən olurdu: kəsilmiş yolun sonunda dayanan düymə
«GÖRMƏK = SƏLAHİYYƏTİN OLMASI» prinsipinin əks tərəfidir — görünən element
İŞLƏMƏLİDİR.

──────────────────────────────────────────────────────────────────────────────
YENİ USE CASE YARADILMIR
──────────────────────────────────────────────────────────────────────────────
`SupportChatUseCase` artıq `Session`-dadır (`session.support`) və bütün
qaydaları daşıyır: modul yoxlaması, `can_contact_support`, mesaj uzunluğu,
"hər mesaj üçün yeni müraciət YARADILMIR" qaydası. Burada yalnız tərcümə var.

──────────────────────────────────────────────────────────────────────────────
SESSİYA SAXLANMIR
──────────────────────────────────────────────────────────────────────────────
Panel örtük boyu yaşayır və gün ərzində onlarla dəfə açılır; hər əməliyyat
üçün yeni sessiya açılır və commit edilir (eyni səbəb `notifications.py`-da
izah olunub).

──────────────────────────────────────────────────────────────────────────────
XƏTA SÖHBƏTİN İÇİNDƏ GÖSTƏRİLİR
──────────────────────────────────────────────────────────────────────────────
Widget-də ayrıca xəta sahəsi YOXDUR. Modal açmaq isə burada yanlış olardı:
istifadəçi kiçik, diskret panelə (bölmə 8: "kiçik, nəzakətli") yazır və
qarşısına tam ekran dialoq çıxması həmin diskretliyi pozardı. Ona görə səbəb
söhbətin içində, AÇIQ işarələnmiş sistem sətri kimi göstərilir — mesajın
GETMƏDİYİ istifadəçidən gizlədilmir.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.domain.value_objects.support import SupportChannel
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext
    from src.presentation.screens.group_e import SupportChatWidget

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Göndərilə bilməyən mesajın qarşısındakı işarə. Mətn `add_message()` ilə
#: GƏLƏN (incoming) baloncuq kimi göstərilir, çünki bu, hazırlayıcıdan deyil,
#: SİSTEMDƏN gələn cavabdır — çıxan baloncuq onu istifadəçinin öz mesajı kimi
#: göstərərdi və "göndərildi" təəssüratı yaradardı.
FAILURE_PREFIX = "⚠ Göndərilmədi — "


class SupportChatController:
    """Üzən dəstək panelini `SupportChatUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, widget: SupportChatWidget) -> None:
        widget.message_sent.connect(lambda text: self._on_sent(widget, text))
        # Panel AÇILANDA oxunmuş sayılır (bölmə 8: nişan "kiçik, nəzakətli"
        # olmalıdır və açıldıqdan sonra qalması mənasızdır).
        widget.opened.connect(lambda: self._on_opened(widget))
        # Söhbət YALNIZ kanal seçiləndən sonra çəkilir (Faza 1): seçimdən
        # əvvəl hansı tarixçənin göstəriləcəyi bilinmir.
        widget.channel_selected.connect(lambda value: self.open_channel(widget, value))
        self.refresh_badge(widget)

    def refresh_badge(self, widget: SupportChatWidget) -> None:
        """Yalnız oxunmamış nişanını yeniləyir — söhbət ÇƏKİLMİR.

        Panel açılmamışdan əvvəl hansı kanalın tarixçəsinin göstəriləcəyi
        məlum deyil (Faza 1), nişan isə HƏR İKİ kanalın cəmini göstərməlidir:
        işçi cavabın hansı kanaldan gəldiyini bilmədən də «cavab var»
        işarəsini görməlidir.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                if not session.support.is_available(tenant_id=session.tenant_id, actor=self._actor):
                    # Modul söndürülüb və ya flag yoxdur — panel onsuz da
                    # qurulmamalı idi (`app.py::_install_overlays`); buraya
                    # düşmək konfiqurasiya dəyişikliyi deməkdir, çökmə yox.
                    return
                unread = session.support.unread_count(
                    tenant_id=session.tenant_id, actor=self._actor
                )
        except Exception:
            _error_log.exception("SUPPORT_THREAD_LOAD_FAILED")
            return
        widget.set_unread(bool(unread))

    def open_channel(self, widget: SupportChatWidget, raw_channel: str) -> None:
        """Seçilmiş kanalın açıq söhbətini paneldə göstərir.

        Söhbət YALNIZ burada — seçim anında — çəkilir: `SupportChatWidget`
        göndərilən mesajı ÖZÜ dərhal əlavə edir (`_on_send`), ona görə hər
        göndərişdən sonra yenidən çəkmək eyni sətri iki dəfə göstərərdi.
        """
        try:
            channel = SupportChannel.parse(raw_channel)
        except ValueError:
            _error_log.exception("SUPPORT_CHANNEL_UNKNOWN")
            return
        try:
            with self._context.session(user_id=self._actor.id) as session:
                threads = session.support.threads(
                    tenant_id=session.tenant_id, actor=self._actor, channel=channel
                )
        except Exception:
            _error_log.exception("SUPPORT_THREAD_LOAD_FAILED")
            return

        open_thread = next((thread for thread in threads if thread.is_open), None)
        if open_thread is None:
            return
        for message in open_thread.messages:
            widget.add_message(message.body, outgoing=not message.is_from_developer)

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_sent(self, widget: SupportChatWidget, text: str) -> None:
        channel = widget.selected_channel()
        if channel is None:
            # Widget bunu onsuz da bloklayır; burada təkrar yoxlama var,
            # çünki kontroller siqnala bağlıdır və siqnal başqa yerdən də
            # yayıla bilər (məs. test və ya gələcək qısayol).
            widget.add_message(f"{FAILURE_PREFIX}əvvəlcə kanal seçin.")
            return
        attachment = widget.pending_attachment()
        try:
            with self._context.session(user_id=self._actor.id) as session:
                thread = session.support.send(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    body=text,
                    channel=channel,
                    urgent=widget.is_urgent(),
                    attachment=attachment[1] if attachment else None,
                    attachment_name=attachment[0] if attachment else "",
                )
                session.commit()
            if attachment is not None:
                self._queue_attachment(thread, filename=attachment[0], content=attachment[1])
        except KompasOSError as error:
            widget.add_message(f"{FAILURE_PREFIX}{error.user_message}")
        except Exception:
            _error_log.exception("SUPPORT_MESSAGE_FAILED")
            widget.add_message(f"{FAILURE_PREFIX}əlaqə qurulmadı. Yenidən cəhd edin.")

    def _queue_attachment(self, thread: Any, *, filename: str, content: bytes) -> None:
        """Şəkli MÖVCUD sübut növbəsinə qoyur (`upload_queue.py`).

        ──────────────────────────────────────────────────────────────────────
        SIRA: ƏVVƏLCƏ MESAJ, SONRA NÖVBƏ
        ──────────────────────────────────────────────────────────────────────
        `fine_entry.py`-dəkinin TƏRSİdir və səbəbi var: orada şəkil sübutdur
        və şəkilsiz cərimə yaradılmamalıdır. Burada isə MƏTN əsasdır — şəkil
        onun əlavəsidir. Növbəni əvvəl doldursaydıq və mesaj yazısı çöksəydi,
        Drive-da sahibsiz fayl qalardı.

        UĞURSUZLUQ MESAJI GERİ QAYTARMIR: mətn artıq göndərilib və oxunur.
        İşçi yalnız şəklin getmədiyini bilir — bu, «heç nə getmədi»dən
        yaxşıdır.
        """
        message = thread.last_message
        if message is None:  # pragma: no cover - `send()` mesajı əlavə edir
            return
        from src.infrastructure.storage.upload_queue import UploadOwnerType  # noqa: PLC0415

        store_id = getattr(self._actor, "store_id", None)
        if store_id is None:
            _error_log.warning("SUPPORT_ATTACHMENT_NO_STORE")
            return
        try:
            self._context.evidence_queue().enqueue(
                tenant_id=str(self._context.tenant_id),
                owner_type=UploadOwnerType.SUPPORT_MESSAGE,
                owner_id=str(message.message_id),
                store_id=store_id,
                filename=filename,
                content=content,
                taken_at=message.created_at,
            )
        except Exception:
            _error_log.exception("SUPPORT_ATTACHMENT_QUEUE_FAILED")

    def _on_opened(self, widget: SupportChatWidget) -> None:
        """Panel açıldı — açıq müraciətlər oxunmuş işarələnir.

        HƏR İKİ kanal işarələnir, seçilmiş kanal deyil: nişan onsuz da
        ikisinin cəmidir və yalnız birini oxunmuş saymaq nişanı panel
        bağlandıqdan sonra yenidən yandırardı.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                threads = session.support.threads(tenant_id=session.tenant_id, actor=self._actor)
                open_threads = [thread for thread in threads if thread.is_open]
                if not open_threads:
                    return
                for thread in open_threads:
                    session.support.mark_read(
                        tenant_id=session.tenant_id,
                        actor=self._actor,
                        ticket_id=thread.ticket_id,
                    )
                session.commit()
        except Exception:
            # Nişanın sıfırlanmaması işi dayandırmır — yalnız iz qalır.
            _error_log.exception("SUPPORT_MARK_READ_FAILED")
            return
        widget.set_unread(False)


__all__ = ["FAILURE_PREFIX", "SupportChatController"]
