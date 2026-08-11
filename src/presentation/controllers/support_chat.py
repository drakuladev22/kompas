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

from typing import TYPE_CHECKING

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
        self.refresh(widget)

    def refresh(self, widget: SupportChatWidget) -> None:
        """Açıq müraciətin mesajlarını paneldə göstərir.

        Söhbət YALNIZ bir dəfə — qoşulma anında — çəkilir: `SupportChatWidget`
        göndərilən mesajı ÖZÜ dərhal əlavə edir (`_on_send`), ona görə hər
        göndərişdən sonra yenidən çəkmək eyni sətri iki dəfə göstərərdi.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                if not session.support.is_available(tenant_id=session.tenant_id, actor=self._actor):
                    # Modul söndürülüb və ya flag yoxdur — panel onsuz da
                    # qurulmamalı idi (`app.py::_install_overlays`); buraya
                    # düşmək konfiqurasiya dəyişikliyi deməkdir, çökmə yox.
                    return
                threads = session.support.threads(tenant_id=session.tenant_id, actor=self._actor)
                unread = session.support.unread_count(
                    tenant_id=session.tenant_id, actor=self._actor
                )
        except Exception:
            _error_log.exception("SUPPORT_THREAD_LOAD_FAILED")
            return

        open_thread = next((thread for thread in threads if thread.is_open), None)
        if open_thread is not None:
            for message in open_thread.messages:
                widget.add_message(message.body, outgoing=not message.is_from_developer)
        widget.set_unread(bool(unread))

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_sent(self, widget: SupportChatWidget, text: str) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.support.send(tenant_id=session.tenant_id, actor=self._actor, body=text)
                session.commit()
        except KompasOSError as error:
            widget.add_message(f"{FAILURE_PREFIX}{error.user_message}")
        except Exception:
            _error_log.exception("SUPPORT_MESSAGE_FAILED")
            widget.add_message(f"{FAILURE_PREFIX}əlaqə qurulmadı. Yenidən cəhd edin.")

    def _on_opened(self, widget: SupportChatWidget) -> None:
        """Panel açıldı — açıq müraciət oxunmuş işarələnir."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                threads = session.support.threads(tenant_id=session.tenant_id, actor=self._actor)
                open_thread = next((thread for thread in threads if thread.is_open), None)
                if open_thread is None:
                    return
                session.support.mark_read(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    ticket_id=open_thread.ticket_id,
                )
                session.commit()
        except Exception:
            # Nişanın sıfırlanmaması işi dayandırmır — yalnız iz qalır.
            _error_log.exception("SUPPORT_MARK_READ_FAILED")
            return
        widget.set_unread(False)


__all__ = ["FAILURE_PREFIX", "SupportChatController"]
