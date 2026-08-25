"""«Nə Yeni?» ekranının kontrolleri — `v2backlog.md` Faza 8.2.

Ekran HƏM oxuyur HƏM yazır (Root nəşr edir) — ona görə ÖZ kontrolleri var
(`attrition_risk` ilə eyni qərar): hər yazıdan sonra siyahı yenidən oxunur və
bu dövrə `populate()`-ın tək çağırışından uzun yaşayır. Kontroller sessiyanı
SAXLAMIR — hər əməliyyat üçün yenisini açır və commit edir (panel saatlarla
açıq qala bilər; uzun-ömürlü tranzaksiya kilid saxlayardı).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.application.use_cases.whats_new import (
    PUBLISH_WHATS_NEW_FLAG,
    WhatsNewEntry,
    WhatsNewPermissionError,
)
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext
    from src.presentation.screens.whats_new import WhatsNewScreen

_log = get_logger(__name__, channel=LogChannel.AUDIT)
_error_log = get_logger(__name__)


class WhatsNewController:
    """Versiya-qeydlərinin oxu/yazı dövrəsi."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: WhatsNewScreen) -> None:
        screen.refresh_requested.connect(lambda: self.refresh(screen))
        screen.publish_requested.connect(
            lambda version, title, body: self._on_publish(screen, version, title, body)
        )
        screen.deactivate_requested.connect(lambda entry_id: self._on_deactivate(screen, entry_id))
        self.refresh(screen)

    def refresh(self, screen: WhatsNewScreen) -> None:
        """Siyahını yenidən oxuyur; nəşr formasının görünməsi flag-dan asılıdır.

        `getattr` QORUMASI MÜDAFİƏDİR: test sahtələri bu portu daşımaya bilər —
        boş siyahı risk siyahısını pozmamalıdır.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                port = getattr(session, "whats_new", None)
                if port is None:
                    entries: list[WhatsNewEntry] = []
                    can_publish = False
                else:
                    try:
                        entries = port.list_entries(tenant_id=session.tenant_id, actor=self._actor)
                    except WhatsNewPermissionError:
                        # VIEW flag-i yoxdur — ekran onsuz da menyu ilə açılmaz;
                        # burada sükutlu boş siyahı kifayətdir.
                        return
                    can_publish = self._actor.has_permission(
                        PUBLISH_WHATS_NEW_FLAG, now=self._context.clock.now()
                    )
        except KompasOSError as error:
            screen.show_error(title="Jurnal açılmadı", message=error.user_message)
            return

        screen.set_publish_visible(can_publish)
        screen.set_entries([_to_row(entry) for entry in entries])

    # ------------------------------ yazı -------------------------------------- #

    def _on_publish(self, screen: WhatsNewScreen, version: str, title: str, body: str) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.whats_new.publish(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    version_label=version,
                    title_az=title,
                    body_az=body,
                )
                session.commit()
        except KompasOSError as error:
            screen.set_publish_message(error.user_message)
            return
        except Exception:
            _error_log.exception("WHATS_NEW_PUBLISH_FAILED")
            screen.set_publish_message("Qeyd yazılmadı. Yenidən cəhd edin.")
            return
        self.refresh(screen)
        screen.set_publish_message(f"«{title}» nəşr olundu.")

    def _on_deactivate(self, screen: WhatsNewScreen, entry_id: str) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.whats_new.deactivate(
                    tenant_id=session.tenant_id, actor=self._actor, entry_id=entry_id
                )
                session.commit()
        except KompasOSError as error:
            screen.set_publish_message(error.user_message)
            return
        except Exception:
            _error_log.exception("WHATS_NEW_DEACTIVATE_FAILED")
            screen.set_publish_message("Söndürmə yazılmadı. Yenidən cəhd edin.")
            return
        self.refresh(screen)


def _to_row(entry: WhatsNewEntry) -> dict[str, str]:
    """`WhatsNewEntry` → `set_entries` açarları (maket ilə EYNİ)."""
    return {
        "entry_id": entry.entry_id,
        "version": entry.version_label,
        "title": entry.title_az,
        "body": entry.body_az,
        "date": entry.created_at.strftime("%d.%m.%Y"),
        "is_active": "1" if entry.is_active else "0",
    }


__all__ = ["WhatsNewController"]
