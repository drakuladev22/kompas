"""Elan (Broadcast) YAZI yolu — #19, kompasos11.md Faza 8.

İki kontroller, iki ekran, BİR use case:

    `EmployeeAnnouncementController` → İşçi Ana Ekranı (kiosk): YALNIZ oxuyur,
                                       heç bir yazı siqnalı YOXDUR (bir-tərəfli).
    `AnnouncementsAdminController`   → "Elanlar" ekranı (admin): yayımlayır,
                                       geri çəkir, siyahını göstərir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ ÖZ KONTROLLERİ VAR (CLAUDE.md §6)
──────────────────────────────────────────────────────────────────────────────
Admin ekranı HƏM oxuyur, HƏM yazır və hər yazıdan sonra siyahı YENİDƏN
oxunmalıdır — geri çəkilmiş elan "Aktiv" nişanı ilə qalsaydı, admin onu
ikinci dəfə geri çəkməyə çalışardı. Bu dövrə `populate()`-ın tək
çağırışından uzun yaşayır, ona görə `screen_data.py` bağlaması yararsızdır
(`controllers/exceptions.py` ilə eyni qərar).

SESSİYA SAXLANILMIR: hər əməliyyat üçün yeni sessiya açılır və commit edilir
(`controllers/open_shift.py` ilə eyni naxış — panel saatlarla açıq qala bilər).

──────────────────────────────────────────────────────────────────────────────
KİOSKDA İSTİSNA EKRANA ÇIXMIR
──────────────────────────────────────────────────────────────────────────────
`controllers/kiosk.py` başlığındakı qayda burada da keçərlidir: kiosk PC-si
PAYLAŞILAN cihazdır və orada istisna ilə çökən ekran bütün mağazanı
bloklayardı. `EmployeeAnnouncementController` bütün nəticəni sükutla udur —
kart sadəcə boş qalır (`OpenShiftMarketUseCase.list_for_employee` ilə eyni
fail-soft qərar).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from src.domain.entities.announcement import AnnouncementDraft, AnnouncementScope
from src.domain.value_objects.identifiers import AnnouncementId, StoreId
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.application.use_cases.announcements import AnnouncementView
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.announcements import AnnouncementsScreen
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: `AnnouncementScope` üzrə Azərbaycanca etiket — ekranların İKİSİ də bu
#: sözlüyü işlədir (CLAUDE.md §6: maket/canlı EYNİ açar).
_SCOPE_TEXT: dict[str, str] = {
    AnnouncementScope.ALL.value: "Bütün mağazalar",
    AnnouncementScope.STORE_LIST.value: "Seçilmiş mağazalar",
}


class EmployeeAnnouncementController:
    """İşçi Ana Ekranının "Elanlar" kartı — YALNIZ OXU, siqnal YOXDUR."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: EmployeeHomeScreen) -> None:
        """Bağlayacaq siqnal yoxdur (bir-tərəfli) — yalnız ilk dəfə doldurur."""
        self.refresh(screen)

    def refresh(self, screen: EmployeeHomeScreen) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                views = session.announcements.list_for_employee(
                    tenant_id=session.tenant_id, employee=self._actor
                )
                rows = [_to_employee_row(view) for view in views]
        except Exception:
            # Kioskda kart oxunmaması ekranı SINDIRMAMALIDIR: işçinin əsas
            # axını (giriş/icazə/qayıdış) elandan asılı deyil.
            _error_log.exception("ANNOUNCEMENT_LIST_FAILED")
            screen.set_announcements([])
            return

        screen.set_announcements(rows)


class AnnouncementsAdminController:
    """ "Elanlar" ekranındakı yayımlama/geri çəkmə axını (admin)."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: AnnouncementsScreen) -> None:
        screen.create_requested.connect(lambda: self._on_create(screen))
        screen.withdraw_requested.connect(
            lambda announcement_id: self._on_withdraw(screen, announcement_id)
        )
        self.refresh(screen)

    def refresh(self, screen: AnnouncementsScreen) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                views = session.announcements.list_recent(
                    tenant_id=session.tenant_id, actor=self._actor
                )
                rows = [_to_admin_row(view) for view in views]
        except KompasOSError as error:
            screen.set_announcements([])
            screen.show_error(title="Elanlar oxunmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception("ANNOUNCEMENT_ADMIN_LIST_FAILED")
            screen.set_announcements([])
            return

        screen.set_announcements(rows)

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_create(self, screen: AnnouncementsScreen) -> None:
        """`[Yeni Elan]` — dialoq açılır, mağaza siyahısı sessiyadan gəlir."""
        from src.presentation.screens.announcements import (  # noqa: PLC0415
            AnnouncementComposeDialog,
        )

        try:
            with self._context.session(user_id=self._actor.id) as session:
                stores = _store_choices(session)
        except Exception:
            _error_log.exception("ANNOUNCEMENT_DIALOG_DATA_FAILED")
            screen.show_error(
                title="Elan forması açılmadı",
                message="Mağaza siyahısı oxunmadı. Yenidən cəhd edin.",
            )
            return

        dialog = AnnouncementComposeDialog(screen.theme, stores=stores, parent=screen)
        dialog.submitted.connect(
            lambda title, message, scope, store_ids: self._submit(
                screen, title, message, scope, store_ids
            )
        )
        dialog.exec()

    def _submit(
        self,
        screen: AnnouncementsScreen,
        title: str,
        message: str,
        scope: str,
        store_ids: list[str],
    ) -> None:
        try:
            parsed_scope = AnnouncementScope(scope)
            parsed_stores = frozenset(StoreId(uuid.UUID(sid)) for sid in store_ids)
        except ValueError:
            screen.show_error(title="Elan yayımlanmadı", message="Seçilmiş dəyərlər düzgün deyil.")
            return

        draft = AnnouncementDraft(
            title_az=title, message=message, scope=parsed_scope, store_ids=parsed_stores
        )
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.announcements.broadcast(
                    tenant_id=session.tenant_id, actor=self._actor, draft=draft
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="Elan yayımlanmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception("ANNOUNCEMENT_BROADCAST_FAILED")
            screen.show_error(
                title="Elan yayımlanmadı", message="Elan yazılmadı. Yenidən cəhd edin."
            )
            return

        self.refresh(screen)

    def _on_withdraw(self, screen: AnnouncementsScreen, announcement_id: str) -> None:
        try:
            parsed_id = AnnouncementId(uuid.UUID(announcement_id))
        except ValueError:
            screen.show_error(
                title="Elan geri çəkilmədi", message="Elan identifikatoru düzgün deyil."
            )
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.announcements.withdraw(
                    tenant_id=session.tenant_id, actor=self._actor, announcement_id=parsed_id
                )
                session.commit()
        except KompasOSError as error:
            # Elan bu arada başqası tərəfindən geri çəkilibsə də bura düşür —
            # admin AÇIQ cavab alır. `refresh()` BURADAN ÇAĞIRILMIR: o,
            # `set_announcements()` → `show_content()` zənciri ilə
            # `ContentSwitcher`-i sinxron şəkildə "content" vəziyyətinə
            # qaytarır və heç bir render arası olmadan bu xəta banner-inin
            # ÜSTÜNDƏN yazır — admin mesajı HEÇ VAXT görmür (QA-FULL FAZA 3,
            # `announcements.py::_submit` ilə eyni qərar). Yenidən yükləmə
            # `on_retry` ilə istifadəçinin öz qərarına buraxılır.
            screen.show_error(
                title="Elan geri çəkilmədi",
                message=error.user_message,
                on_retry=lambda: self.refresh(screen),
            )
            return
        except Exception:
            _error_log.exception(
                "ANNOUNCEMENT_WITHDRAW_FAILED", extra={"announcement_id": announcement_id}
            )
            screen.show_error(
                title="Elan geri çəkilmədi", message="Dəyişiklik yazılmadı. Yenidən cəhd edin."
            )
            return

        self.refresh(screen)


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _to_employee_row(view: AnnouncementView) -> dict[str, str]:
    """`AnnouncementView` → İşçi Ana Ekranının FAKTİKİ gözlədiyi açarlar."""
    return {
        "id": str(view.announcement_id),
        "title": view.title_az,
        "message": view.message,
        "scope_text": _SCOPE_TEXT.get(view.scope, view.scope),
        "date": _day_label(view),
    }


def _to_admin_row(view: AnnouncementView) -> dict[str, str]:
    """`AnnouncementView` → "Elanlar" ekranının FAKTİKİ gözlədiyi açarlar."""
    return {
        "id": str(view.announcement_id),
        "title": view.title_az,
        "scope_text": _SCOPE_TEXT.get(view.scope, view.scope),
        "date": _day_label(view),
        "is_active": "1" if view.is_active else "0",
    }


def _day_label(view: AnnouncementView) -> str:
    return view.created_at.astimezone().strftime("%d.%m.%Y %H:%M")


def _store_choices(session: Session) -> list[tuple[str, str]]:
    """Aktiv mağazalar — `tenant_id` şərti İKİNCİ TƏCRİD QATIDIR (CLAUDE.md §6)."""
    rows = session.uow.connection.execute(
        "SELECT id, name FROM stores WHERE tenant_id = %s AND is_active ORDER BY name",
        (session.tenant_id,),
    ).fetchall()
    return [(str(row["id"]), str(row["name"])) for row in rows]


__all__ = ["AnnouncementsAdminController", "EmployeeAnnouncementController"]
