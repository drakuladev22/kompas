"""«Bağlantı Ayarları» ekranının YAZI yolu (DB-4 Faza 4).

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA KONTROLLER — EKRAN ÖZÜ YAZA BİLƏRDİMİ
──────────────────────────────────────────────────────────────────────────────
Ekran yalnız sahələri toplayır. Yazı yolu isə İKİ addımlıdır — əvvəlcə sınaq
bağlantısı, yalnız uğurlu olduqda diskə yazı — və hər iki addım şəbəkəyə/fayl
sisteminə toxunur. CLAUDE.md §6: «həm oxuyub həm yazan ekranın ÖZ kontrolleri
olur», çünki hər yazıdan sonra vəziyyət yenidən oxunmalıdır.

──────────────────────────────────────────────────────────────────────────────
BURADA SESSİYA YOXDUR VƏ BU, İSTİSNA DEYİL
──────────────────────────────────────────────────────────────────────────────
Digər kontrollerlər hər əməliyyat üçün `context.session()` açır. Bu kontroller
AÇA BİLMƏZ: o, məhz baza bağlantısı QURULA BİLMƏDİYİ üçün işə düşür. Yazdığı
yer bazadan kənardadır (`%PROGRAMDATA%\\KompasOS\\connection.json`), audit
sətri də yazıla bilməz — audit cədvəli həmin əlçatmaz bazadadır. Ona görə iz
`security.log`-a düşür (aşağıya bax); bu, audit qaydasının pozulması deyil,
onun tətbiq oluna bilmədiyi yeganə nöqtədir və ona görə açıq loglanır.

──────────────────────────────────────────────────────────────────────────────
SINAQ NİYƏ MƏCBURİDİR
──────────────────────────────────────────────────────────────────────────────
Yoxlamadan yazsaydıq, yanlış dəyər faylda qalar və tətbiq növbəti açılışda
yenə eyni fatal ekrana düşərdi — istifadəçi isə artıq «düzəltdim» sanardı.
Yanlış konfiqurasiyanı diskə YAZMAMAQ onu sonradan geri qaytarmaqdan ucuzdur.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.presentation.controllers.ui_feedback import flush_ui
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.presentation.screens.group_a_entry import ConnectionSettingsScreen

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)


def diagnostic_paths() -> list[tuple[str, str]]:
    """Ekranda göstərilən üç yol — `(etiket, dəyər)` cütləri.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ EKRANDA YAZILIR
    ──────────────────────────────────────────────────────────────────────────
    Bu ekran məhz baza əlçatmaz olanda açılır, yəni quraşdırıcı burada dayanıb.
    `Setup.exe` ilə paylanan quraşdırmada `.exe` `Program Files`-da, konfiqurasiya
    isə `ProgramData`-dadır — ikisi AYRI yerdədir və heç bir ekranda yazılmırdı.
    Nəticədə tipik səhv (config faylını `.exe`-nin yanına qoymaq) görünməz
    qalırdı: proqram onu başqa qovluqda axtarır, quraşdırıcı isə faylın orada
    olduğuna əmindir.

    Konfiqurasiya sətri iki fərqli sual cavablandırır: fayl VARSA hansı nüsxə
    işlədilir (üç yer axtarılır — `connection_search_paths`), YOXDURSA yazı
    hara düşəcək. «Tapılmadı» tək başına quraşdırıcıya heç nə vermir.
    """
    from src.infrastructure.config.connection_file import (  # noqa: PLC0415
        connection_file_path,
        find_connection_file,
    )
    from src.shared.data_paths import default_data_dir, default_log_dir  # noqa: PLC0415

    found = find_connection_file()
    config = str(found) if found else f"tapılmadı — yazılacaq yer: {connection_file_path()}"
    return [
        ("Konfiqurasiya faylı", config),
        ("Log qovluğu", str(default_log_dir())),
        ("Yerli məlumat", str(default_data_dir())),
    ]


class ConnectionSettingsController:
    """Ekranı `connection.json` faylına bağlayır.

    Kontrollerə İSTİNAD SAXLANILMIR (CLAUDE.md §6): o, siqnallara bağladığı
    `lambda`-ların bağlamasında yaşayır və ekranla birlikdə ölür.
    """

    def __init__(self, *, on_saved: Callable[[], None]) -> None:
        self._on_saved = on_saved

    # ------------------------------ bağlanma ---------------------------------- #

    def attach(self, screen: ConnectionSettingsScreen) -> None:
        """Siqnalları bağlayır və mövcud dəyərləri göstərir."""
        screen.submitted.connect(lambda payload: self._on_submit(screen, payload))
        screen.set_diagnostics(diagnostic_paths())
        self._populate(screen)

    def _populate(self, screen: ConnectionSettingsScreen) -> None:
        """Mövcud faylı oxuyur — YOXDURSA və ya SINIQDIRSA ekran boş açılır.

        Sınıq fayl BURADA xəta vermir: istifadəçi məhz onu əvəz etmək üçün bu
        ekrandadır. Səbəb isə status sətrində deyilir ki, «niyə sahələr boşdur?»
        sualı cavabsız qalmasın.
        """
        from src.infrastructure.config.connection_file import (  # noqa: PLC0415
            ConnectionFileError,
            load_settings,
        )

        try:
            settings = load_settings()
        except ConnectionFileError as exc:
            screen.set_error(exc.user_message)
            return

        if settings is None:
            screen.set_status("Bağlantı hələ konfiqurasiya edilməyib.")
            return

        screen.populate(
            {
                "host": settings.host,
                "port": settings.port,
                "database": settings.database,
                "username": settings.username,
            }
        )
        screen.set_status("Mövcud ayarlar göstərilir. Parol boş qalarsa dəyişmir.")

    # ------------------------------- yazı yolu -------------------------------- #

    def _on_submit(self, screen: ConnectionSettingsScreen, payload: dict[str, Any]) -> None:
        from src.infrastructure.config.connection_file import (  # noqa: PLC0415
            ConnectionSettings,
            save_settings,
        )

        password = str(payload.get("password", ""))
        if not password:
            # BOŞ PAROL = «DƏYİŞMƏ», silmə DEYİL. Ekran parolu heç vaxt
            # göstərmir (bax ekranın başlığı), ona görə boş sahəni «parolu
            # sil» kimi oxumaq istifadəçinin işlək ayarını sükutla pozardı.
            password = self._existing_password()
            if not password:
                screen.set_error("Parolu daxil edin — saxlanmış parol tapılmadı.")
                return

        settings = ConnectionSettings(
            host=str(payload["host"]),
            port=int(payload["port"]),
            database=str(payload["database"]),
            username=str(payload["username"]),
            password=password,
            sslmode=str(payload.get("sslmode", "require")),
        )

        screen.set_busy(True)
        screen.set_status("Bağlantı yoxlanılır…")
        # ──────────────────────────────────────────────────────────────────
        # SINAQ ƏSAS SAPDA APARILIR — NİYƏ İŞÇİ SAP DEYİL
        # ──────────────────────────────────────────────────────────────────
        # `probe_dsn` ən çox 10 saniyə bloklayır. İşçi sap Qt siqnal
        # körpüsü, ləğvetmə və ekran ölümündən sonra gələn cavab hallarını
        # tələb edərdi — bunların hamısı bir dəfəlik, ön-plan, istifadəçi
        # gözlədiyi əməliyyat üçün artıq mürəkkəblikdir (örtük hələ
        # qurulmayıb, arxa fonda dayandırılası iş yoxdur).
        # `processEvents` isə MƏCBURİDİR: onsuz «Yoxlanılır…» yazısı bloklama
        # bitənə qədər çəkilmir və istifadəçi düymənin işlədiyini görmür.
        flush_ui()
        try:
            if not self._probe(screen, settings.dsn()):
                return
            save_settings(settings)
        except KompasOSError as exc:
            # `ConnectionFileError` DEYİL, ÜMUMİ `KompasOSError`: yazı yolu
            # şifrələmə açarına da toxunur (`EncryptionKeyError`) və dar
            # tutucu onu buraxırdı. Qt isə siqnal işləyicisindən çıxan
            # istisnanı yalnız stderr-ə yazır — istifadəçi düyməni basıb
            # HEÇ NƏ görmürdü (SETUP-2).
            screen.set_error(exc.user_message)
            return
        except Exception:
            _log.exception("CONNECTION_SETTINGS_SAVE_FAILED")
            screen.set_error("Ayarlar saxlanmadı. Yenidən cəhd edin.")
            return
        finally:
            screen.set_busy(False)

        # Parol LOG-A DÜŞMÜR: yalnız hansı serverə keçildiyi qeyd olunur.
        _security_log.warning(
            "CONNECTION_SETTINGS_CHANGED",
            extra={
                "host": settings.host,
                "database": settings.database,
                "username": settings.username,
                "note": "audit cədvəli əlçatmaz idi — iz yalnız buradadır",
            },
        )
        screen.set_status("Ayarlar yadda saxlanıldı. Tətbiq yenidən qoşulur…")
        self._on_saved()

    def _probe(self, screen: ConnectionSettingsScreen, dsn: str) -> bool:
        """Sınaq bağlantısı — uğursuzluqda SƏBƏBİ ekrana yazır.

        Mesaj `classify_connection_failure`-dən gəlir, yəni fatal başlanğıc
        ekranı ilə EYNİ mətndir. İki yerdə iki fərqli izah yazsaydıq, eyni
        nasazlıq istifadəçiyə iki müxtəlif səbəb kimi görünərdi.
        """
        from src.infrastructure.persistence.connection import probe_dsn  # noqa: PLC0415
        from src.presentation.composition import classify_connection_failure  # noqa: PLC0415

        try:
            probe_dsn(dsn)
        except Exception as exc:  # səbəb təsnif olunub istifadəçiyə göstərilir
            failure = classify_connection_failure(exc)
            _log.warning("CONNECTION_PROBE_FAILED", extra=failure.to_dict())
            screen.set_error(failure.user_message)
            return False
        return True

    @staticmethod
    def _existing_password() -> str:
        """Saxlanmış parolu qaytarır (yoxdursa/açılmırsa boş sətir)."""
        from src.infrastructure.config.connection_file import (  # noqa: PLC0415
            ConnectionFileError,
            load_settings,
        )

        try:
            current = load_settings()
        except ConnectionFileError:
            return ""
        return current.password if current is not None else ""


__all__ = ["ConnectionSettingsController"]
