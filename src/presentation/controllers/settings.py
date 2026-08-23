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

from typing import TYPE_CHECKING, Any, Final

from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext
    from src.presentation.screens.group_d import SettingsScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: D3-03 (dövrə 3 audit) — «Şifrə» sahəsinin mətni. Sabit dəyər QƏSDƏNDİR,
#: uydurma "N gün əvvəl" DEYİL: `employees`/`credentials` cədvəlində parolun
#: DƏYİŞDİYİ TARİX saxlanmır (yalnız cari `password_hash` var), yəni real
#: "son dəyişiklik" tarixini yalnız audit jurnalından (`PASSWORD_RESET_BY_
#: ADMIN`) çıxarmaq olardı — o isə `can_view_audit_logs` tələb edir (bax
#: `AuditQueryUseCase._require_access`), Ayarlar ekranı isə FLAG-SIZDIR
#: (özünə-xidmət, `menu.py`). Uydurma ədəd göstərmək «yanlış rəqəm
#: göstərməkdənsə heç nə göstərməmək dürüstdür» qaydasını (bax `screen_data.
#: py`, `base.py` başlıqları) pozardı — DOĞRU, sabit mətn seçilib.
#: Aşağıdakı sətirdəki bastırma EKRAN MƏTNİ üçündür, sirr üçün DEYİL (bandit
#: yalançı müsbəti — dəyişən adında "password" sözü var deyə tetiklənir).
PASSWORD_AGE_TEXT: Final = "Administrator tərəfindən idarə olunur (SEC-016)."  # noqa: S105


class SettingsController:
    """«Yadda Saxla», bildiriş açarları və sessiya düyməsini bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: SettingsScreen) -> None:
        screen.saved.connect(lambda payload: self._on_saved(screen, payload))
        # ──────────────────────────────────────────────────────────────────
        # AÇAR DƏRHAL YAZILIR — «YADDA SAXLA»SIZ İTMİR (DEEP-GAP UX-5)
        # ──────────────────────────────────────────────────────────────────
        # `notification_changed` siqnalı EKRANDA yayılırdı, LAKİN heç bir
        # kontroller onu dinləmirdi: istifadəçi açarı çevirir, ekranı bağlayır
        # və dəyişiklik sükutla itirdi. «Yadda Saxla» düyməsi vardı, amma
        # açarın YANINDA deyil, kartın altında — yəni bağlantı görünmürdü.
        #
        # Sükutla itən dəyişiklik layihənin öz qaydasına ziddir: yarımçıq
        # vəziyyət qalmır (CLAUDE.md §6 — «commit unudularsa rollback olur»).
        # Ona görə açar DƏRHAL yazılır; «Yadda Saxla» isə bütün kartı bir
        # dəfəyə yazan yol kimi QALIR (ikisi eyni metoda gedir, yəni davranış
        # ayrılmır).
        screen.notification_changed.connect(
            lambda key, enabled: self._on_notification_toggled(screen, key, enabled)
        )
        screen.sessions_close_requested.connect(lambda: self._on_sessions(screen))
        screen.password_change_requested.connect(lambda: self._on_password(screen))
        self.refresh(screen)

    # ------------------------------- oxuma ----------------------------------- #

    def refresh(self, screen: SettingsScreen) -> None:
        """Saxlanmış bildiriş tərcihlərini VƏ Təhlükəsizlik kartını ekrana qaytarır.

        ──────────────────────────────────────────────────────────────────────
        TUTUCU `KompasOSError` DEYİL, `Exception`-dır — SƏBƏB
        ──────────────────────────────────────────────────────────────────────
        Bu metod ekran FABRİKASINDAN çağırılır (`app.py::_register_screens`).
        Buradan qaçan istisna `AdminShell.show_screen()`-ə çıxır və menyu
        maddəsi «basılır, heç nə açılmır» halına düşür.

        Dar tutucu məhz bunu buraxırdı: baza qatı hər xətanı `KompasOSError`-ə
        BÜRÜMÜR — hovuz taymautu və bağlantı qırılması `psycopg.OperationalError`
        kimi qalxır. Yəni ötəri şəbəkə problemi bütün «Ayarlar» ekranını
        əlçatmaz edirdi.

        Ekran indi AÇILIR və istifadəçi bölmənin yüklənmədiyini GÖRÜR
        (`set_section_error`) — sükutla defolt dəyər göstərmək daha pis olardı:
        istifadəçi öz tərcihlərini söndürülmüş sanardı.

        ──────────────────────────────────────────────────────────────────────
        D3-03 (dövrə 3 audit) — «TƏHLÜKƏSİZLİK» KARTI ARTIQ DOLDURULUR
        ──────────────────────────────────────────────────────────────────────
        `screen.set_security_info(...)` ƏVVƏL HEÇ ÇAĞIRILMIRDI — kartın iki
        sətri (parol, sessiyalar) istehsalatda HƏMİŞƏ BOŞ qalırdı, maket isə
        dolu göstərirdi (`preview_screens.py::_settings`). Bu, «maket və
        canlı yol EYNİ açarları işlətməlidir» qaydasının (CLAUDE.md §6,
        `menu.py` qüsuru ilə eyni ailə) pozuntusu idi.

        İKİ bölmə AYRI sessiyalarda oxunur (SIRA/KONSİSTENSİYA tələbi yoxdur,
        `support_inbox.py::refresh`-dəki EYNİ-sessiya qaydasından FƏRQLİ) ki,
        BİRİNİN uğursuzluğu DİGƏRİNİ maskalamasın — Qrup G qaydası
        (`base.py`-nin öz başlığı: "yeddi müstəqil bölmədən biri sınanda
        qalanları gizlətmə").
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                prefs = session.preferences.notification_prefs(self._actor.id)
        except Exception as exc:
            _error_log.exception("SETTINGS_LOAD_FAILED", extra={"error": str(exc)})
            screen.set_section_error("Bildiriş tərcihləri")
        else:
            screen.set_notification_prefs(prefs)

        try:
            with self._context.session(user_id=self._actor.id) as session:
                # `_active_session_count` `profile.py`-dandır — `_on_sessions`
                # (aşağı) ARTIQ EYNİ funksiyanı işlədir; SQL-i BURADA TƏKRAR
                # yazmaq iki nüsxənin bir gün ayrılması riski yaradardı.
                from src.presentation.controllers.profile import (  # noqa: PLC0415
                    _active_session_count,
                )

                active = _active_session_count(session, self._actor, now=self._context.clock.now())
        except Exception as exc:
            _error_log.exception("SETTINGS_SECURITY_INFO_FAILED", extra={"error": str(exc)})
            screen.set_section_error("Təhlükəsizlik")
        else:
            screen.set_security_info(
                password_age=PASSWORD_AGE_TEXT, sessions=_sessions_text(active)
            )

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
        except Exception as exc:
            # Tutucu `KompasOSError` DEYİL, `Exception`-dır — SƏBƏB `refresh()`-
            # dəki ilə EYNİDİR (yuxarı, sətir 60-69): psycopg-in çılpaq
            # `OperationalError`-u `KompasOSError` DEYİL, dar tutma isə bu YAZI
            # yolunu («Yadda Saxla») sükutla «basılır, heç nə olmur» halına
            # salırdı. `refresh()` eyni səbəbdən artıq geniş tutur — YAZI yolu
            # geridə qalmışdı.
            _error_log.exception("SETTINGS_SAVE_FAILED", extra={"error": str(exc)})
            screen.show_error(
                title="Ayarlar yadda saxlanılmadı",
                message=getattr(exc, "user_message", "Yenidən cəhd edin."),
            )
            return
        _inform(screen, "Ayarlar", "Bildiriş tərcihləriniz yadda saxlanıldı.")

    def _on_notification_toggled(self, screen: SettingsScreen, key: str, enabled: bool) -> None:
        """Tək açar çevrildi — BÜTÜN dəst yazılır (bax `attach`-dakı izah).

        NİYƏ TƏK AÇAR YOX, BÜTÜN DƏST: `set_notification_prefs` `jsonb`
        sütununu TAM ƏVƏZ EDİR (`DO UPDATE SET notification_prefs =
        EXCLUDED.notification_prefs`). Yalnız çevrilən açarı göndərsəydik,
        qalan iki kanal sütundan SİLİNƏRDİ və növbəti oxunuşda «açar yoxdursa
        kanal açıq qalır» qaydası onları sükutla yenidən açardı — yəni bir
        açarı söndürmək digərini geri qaytarardı.

        Uğurda MODAL AÇILMIR: hər çevrilişdə pəncərə çıxsaydı, üç kanallı
        kartda üç dialoq olardı. UĞURSUZLUQDA isə açar GERİ QAYTARILIR —
        yazılmamış dəyişikliyi ekranda saxlamaq istifadəçiyə yalan deməkdir.
        """
        collected = screen.collected().get("notifications")
        prefs = (
            {str(k): bool(v) for k, v in collected.items()}
            if isinstance(collected, dict)
            else {key: enabled}
        )
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.preferences.set_notification_prefs(self._actor.id, prefs)
                session.commit()
        except Exception as exc:
            # Geniş tutma — səbəb `_on_saved`-dakı ilə EYNİDİR (yuxarı).
            _error_log.exception("SETTINGS_TOGGLE_FAILED", extra={"key": key})
            # `set_notification_prefs` siqnalları BLOKLAYIR — geri qaytarma
            # yeni bir «istifadəçi dəyişdi» hadisəsi yaratmır.
            screen.set_notification_prefs({**prefs, key: not enabled})
            _inform(
                screen,
                "Ayarlar",
                getattr(exc, "user_message", "Dəyişiklik yadda saxlanılmadı."),
            )

    def _on_sessions(self, screen: SettingsScreen) -> None:
        """«Bütün sessiyaları bağla» — sayı göstərir, LƏĞV ETMİR (SEC-5).

        ──────────────────────────────────────────────────────────────────────
        BURADA HƏLƏ LƏĞV YOXDUR — Profil ekranından FƏRQLİ, QƏSDƏN
        ──────────────────────────────────────────────────────────────────────
        `profile.py::_on_close_sessions` indi HƏQİQİ ləğv edir (SEC-5), amma
        YALNIZ DİGƏR sessiyaları — CARİNİ İSTİSNA edir. Bu düymə isə "BÜTÜN
        sessiyaları" bağlayır, yəni CARİ sessiyanı DA — özünü ləğv etmək
        dərhal çıxışa bərabərdir və bu, `_on_close_sessions`-dan tamamilə
        FƏRQLİ bir axındır (ekranın özünün bağlanması, yenidən girişə
        yönləndirmə). SEC-5 iş müqaviləsi bunu əhatə etmirdi, ona görə
        BURADA əlavə edilmədi — "sayı göstər" davranışı QALIR, mətn isə artıq
        YALAN İDDİA ETMİR (əvvəl "giriş axını token buraxmır" deyirdi, amma
        `issue()` indi bağlıdır).
        """
        from src.presentation.controllers.profile import _active_session_count  # noqa: PLC0415

        try:
            with self._context.session(user_id=self._actor.id) as session:
                active = _active_session_count(session, self._actor, now=self._context.clock.now())
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
            f"{active} aktiv sessiya var. Digər sessiyaları bağlamaq üçün "
            "«Profil» ekranındakı «Digər sessiyaları bağla» düyməsini işlədin.",
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


def _sessions_text(active: int) -> str:
    """`set_security_info(sessions=...)`-in mətni — `_on_sessions` ilə EYNİ say mənbəyi."""
    if active == 0:
        return "Aktiv sessiya yoxdur."
    if active == 1:
        return "1 cihazda aktiv sessiyanız var."
    return f"{active} cihazda aktiv sessiyanız var."


__all__ = ["PASSWORD_AGE_TEXT", "SettingsController"]
