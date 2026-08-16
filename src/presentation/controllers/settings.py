"""Ayarlar ekranının YAZI yolu — bildiriş tərcihləri, şifrə və sessiyalar.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU MODUL VAR
──────────────────────────────────────────────────────────────────────────────
Ayarlar ekranında beş idarəedici vardı və `app.py` onlardan YALNIZ birini
(tema seçimini) bağlayırdı. Qalan dördü — «Yadda Saxla», bildiriş açarları,
«Şifrəni Dəyiş» və «Bütün sessiyaları bağla» — siqnal yayır, heç kim
dinləmirdi.

Bildiriş açarları ən aldadıcısı idi: istifadəçi açarı söndürür, «Yadda Saxla»
basır, ekranı yenidən açır və açar YENƏ AÇIQ olur. O, bunu nasazlıq deyil,
öz səhvi sanır və bir daha söndürür.

──────────────────────────────────────────────────────────────────────────────
SESSİYA LƏĞVİ NİYƏ SAYĞACLA BİTİR
──────────────────────────────────────────────────────────────────────────────
Ləğv təhlükəsizlik əməliyyatıdır və audit tələb edir; tətbiqdə isə
`auth_sessions`-a YAZAN tərəf hələ yoxdur (giriş axını token buraxmır). Ona
görə davranış Profil ekranındakı ilə EYNİDİR: aktiv sessiya sayı göstərilir,
sətirlər ləğv EDİLMİR. İki ekranda iki fərqli davranış qoysaydıq, istifadəçi
birində «bağlandı», digərində «bağlanmadı» görər və hansına inanacağını
bilməzdi (bax `controllers/profile.py::_on_close_sessions`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext
    from src.presentation.screens.group_d import SettingsScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)


class SettingsController:
    """«Yadda Saxla», bildiriş açarları və sessiya düyməsini bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: SettingsScreen) -> None:
        screen.saved.connect(lambda payload: self._on_saved(screen, payload))
        screen.sessions_close_requested.connect(lambda: self._on_sessions(screen))
        screen.password_change_requested.connect(lambda: self._on_password(screen))
        self.refresh(screen)

    # ------------------------------- oxuma ----------------------------------- #

    def refresh(self, screen: SettingsScreen) -> None:
        """Saxlanmış bildiriş tərcihlərini ekrana qaytarır."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                prefs = session.preferences.notification_prefs(self._actor.id)
        except KompasOSError as exc:
            _error_log.exception("SETTINGS_LOAD_FAILED", extra={"error": str(exc)})
            return
        screen.set_notification_prefs(prefs)

    # -------------------------------- yazı ----------------------------------- #

    def _on_saved(self, screen: SettingsScreen, payload: dict[str, Any]) -> None:
        """«Yadda Saxla» — bildiriş açarları yazılır.

        TEMA BURADA YAZILMIR: o, `theme_selected` ilə DƏRHAL tətbiq olunur və
        `app.py::_on_theme_selected` onu artıq saxlayır. İkinci dəfə yazsaydıq,
        istifadəçi temanı dəyişib «Yadda Saxla» basmadan ekranı bağladıqda
        iki yol fərqli nəticə verərdi — biri saxlayıb, digəri yox.

        DİL DƏ YAZILMIR: `user_preferences.language` sütununda
        `CHECK (language IN ('az'))` var, yəni yeganə mümkün dəyər onsuz da
        defoltdur (bax spesifikasiya bölmə 9).
        """
        prefs = payload.get("notifications")
        if not isinstance(prefs, dict):
            return
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.preferences.set_notification_prefs(
                    self._actor.id, {str(k): bool(v) for k, v in prefs.items()}
                )
                session.commit()
        except KompasOSError as exc:
            _error_log.exception("SETTINGS_SAVE_FAILED", extra={"error": str(exc)})
            screen.show_error(
                title="Ayarlar yadda saxlanılmadı",
                message=getattr(exc, "user_message", "Yenidən cəhd edin."),
            )
            return
        _inform(screen, "Ayarlar", "Bildiriş tərcihləriniz yadda saxlanıldı.")

    def _on_sessions(self, screen: SettingsScreen) -> None:
        """«Bütün sessiyaları bağla» — Profil ekranı ilə EYNİ davranış."""
        from src.presentation.controllers.profile import _active_session_count  # noqa: PLC0415

        try:
            with self._context.session(user_id=self._actor.id) as session:
                active = _active_session_count(session, self._actor)
        except Exception:
            _error_log.exception("SETTINGS_SESSIONS_FAILED")
            _inform(screen, "Sessiyalar", "Sessiya məlumatı oxuna bilmədi.")
            return

        if active == 0:
            _inform(screen, "Sessiyalar", "Başqa aktiv sessiya yoxdur.")
            return
        _inform(
            screen,
            "Sessiyalar",
            f"{active} aktiv sessiya var. Ləğv etmə hələ aktiv deyil — "
            "giriş axını sessiya tokeni buraxmır.",
        )

    def _on_password(self, screen: SettingsScreen) -> None:
        """«Şifrəni Dəyiş» — şifrə İDARƏÇİ tərəfindən sıfırlanır (SEC-016).

        Öz-özünə dəyişmə axını YOXDUR və bu, təsadüf deyil: spesifikasiya
        e-poçt token axınını qəsdən çıxarıb (mağaza işçilərinin çoxunun
        korporativ e-poçtu yoxdur). İstifadəçiyə düzgün yol göstərilir —
        düymə sükutla heç nə etmir deyil.
        """
        _inform(
            screen,
            "Şifrə",
            "Şifrə İstifadəçilər ekranından administrator tərəfindən "
            "yenilənir («Şifrəni Yenilə»). Rəhbərinizə müraciət edin.",
        )


def _inform(screen: Any, title: str, message: str) -> None:
    from PySide6.QtWidgets import QMessageBox  # noqa: PLC0415

    QMessageBox.information(screen, title, message)


__all__ = ["SettingsController"]
