"""GUI kompozisiya kökü — Faza 4.2.

`main.py --gui` bu modulu çağırır. Burada pəncərə, tema, örtük və ekranlar
bir-birinə bağlanır; heç bir iş məntiqi YOXDUR (o, `application/use_cases`
qatındadır).

──────────────────────────────────────────────────────────────────────────────
AXIN
──────────────────────────────────────────────────────────────────────────────
    Splash → (ilk işə düşmə?) → İlk Quraşdırma Sehrbazı
           → Admin Girişi → Admin Örtüyü (27 ekran)

Kiosk rejimi (`--kiosk`) ayrı bir axındır: PIN klaviaturası → İşçi Ana Ekranı.
İki axın eyni pəncərədə qarışmır, çünki kiosk PC-si paylaşılan cihazdır və
orada admin ekranlarının açılması təhlükəsizlik problemi olardı.
"""

from __future__ import annotations

import sys
from enum import Enum
from typing import TYPE_CHECKING, Final, cast

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QWidget

from src import __version__
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.presentation.plugin_surface import register_plugin_pages
from src.presentation.shell.admin_shell import AdminShell
from src.presentation.shell.kiosk import KioskWindow
from src.presentation.shell.menu import build_default_registry
from src.presentation.shell.window import FramelessWindow
from src.presentation.theme.manager import ThemeManager
from src.presentation.theme.tokens import ThemeMode
from src.presentation.theme.transition import animate_theme_change
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from PySide6.QtGui import QResizeEvent

    from src.domain.entities.employee import Employee
    from src.domain.value_objects.credentials import Username
    from src.domain.value_objects.identifiers import EmployeeId, LeaveTypeId, TenantId
    from src.infrastructure.persistence.mappers import Credentials
    from src.presentation.composition import ApplicationContext, StartupFailureKind
    from src.presentation.controllers.auth import AuthController
    from src.presentation.controllers.devices import DevicePendingController
    from src.presentation.controllers.fine_entry import FineEntryController
    from src.presentation.controllers.kiosk import KioskController, KioskOutcome
    from src.presentation.controllers.sales_review import SalesReviewController
    from src.presentation.controllers.screen_data import ScreenDataBinder
    from src.presentation.plugin_surface import PluginPage
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen
    from src.presentation.widgets.worker_status import WorkerStatus

_log = get_logger(__name__)


def _recovery_may_open(*, actor: Employee | None, configured: bool) -> bool:
    """Bərpa konsolunun qapısı — məntiq kontrollerdədir.

    Ayrıca funksiya ona görə var ki, qərar TƏK yerdən gəlsin: `app.py`
    şərti təkrar yazsaydı, iki qapı bir gün ayrılardı (CLAUDE.md §5).
    """
    from src.presentation.controllers.recovery_console import may_open  # noqa: PLC0415

    return may_open(actor=actor, configured=configured)


#: `SQLSTATE 42P01` — «relation does not exist». Sxem heç tətbiq olunmayıb.
_UNDEFINED_TABLE: Final = "42P01"


class StartupRoute(str, Enum):
    """Splash-dan sonrakı yol — üç halın hər biri fərqli ekrana aparır.

    Sadə `bool` kifayət etmirdi: «sihirbaz lazımdır?» sualının cavabı ÜÇ
    haldır və üçüncüsü (sxem ümumiyyətlə yoxdur) əvvəl `False` kimi
    yuvarlaqlaşdırılırdı — nəticədə istifadəçi giriş ekranında qalırdı.
    """

    LOGIN = "LOGIN"
    SETUP_WIZARD = "SETUP_WIZARD"
    SCHEMA_MISSING = "SCHEMA_MISSING"


#: Splash ekranının minimum görünmə müddəti.
SPLASH_DURATION_MS: Final = 1200

#: Sübut şəkli növbəsinin yoxlanma tezliyi (2 dəqiqə).
#: Cərimə yaradılan anda növbə ONSUZ DA bir dəfə boşaldılır (bax
#: `FineEntryController._issue`) — bu taymer yalnız şəbəkə qayıdanda və ya
#: kvota problemi həll olunanda gözləyən elementləri götürmək üçündür.
#:
#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`EVIDENCE_UPLOAD_POLL_INTERVAL_SECONDS`, seed: migrations/035). Ritm
#: filialın internetindən asılıdır: zəif kanalda seyrək dövrə həm şəbəkəni,
#: həm də DB sessiyalarını qoruyur. Sabit YALNIZ kontekst olmayanda
#: (önizləmə/dizayn rejimi) və ya limit oxunmayanda işə düşür.
FALLBACK_UPLOAD_POLL_INTERVAL_MS: Final = (
    int(DEFAULT_LIMITS[SystemLimitKey.EVIDENCE_UPLOAD_POLL_INTERVAL_SECONDS]) * 1000
)

#: Dövrənin ALT HƏDDİ — migrations/035-dəki `min_value` ilə eyni ədəd.
#: NİYƏ KODDA DA VAR: `QTimer(0)` hər hadisə dövrəsində işə düşər və hər
#: işləməsi bir DB sessiyası açardı — yəni "0" yazmaq interfeysi dondurardı.
#: DB-dəki `min_value` yalnız ROOT ekranından yazılan dəyəri qoruyur; birbaşa
#: SQL ilə düşən dəyər üçün son müdafiə xətti buradadır.
MIN_UPLOAD_POLL_INTERVAL_SECONDS: Final = 10

#: Planlaşdırılmış işlərin yoxlanma tezliyi (15 dəqiqə).
#:
#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`SCHEDULER_POLL_INTERVAL_MINUTES`, seed: migrations/036) və o, adətən
#: `JobRunner.poll_interval()` vasitəsilə oxunur. Bu sabit YALNIZ kontekst
#: olmayanda (önizləmə/dizayn rejimi) və ya limit oxunmayanda işə düşür —
#: dövrənin ritmsiz qalması gecə işlərini tamamilə dayandırardı.
FALLBACK_SCHEDULER_POLL_INTERVAL_MS: Final = (
    int(DEFAULT_LIMITS[SystemLimitKey.SCHEDULER_POLL_INTERVAL_MINUTES]) * 60 * 1000
)

#: Brend ikonu — pəncərə başlığı, Windows Taskbar və Alt-Tab (bölmə 9, 296).
ICON_RELATIVE_PATH: Final = "assets/kompasos.ico"

#: Ay adları — `application/use_cases/reporting.py`-dəki siyahının EYNİSİ.
#:
#: TƏKRAR QƏSDLİDİR: təqdimat qatı hesabat use case-inin PRİVAT sabitini
#: (`_MONTHS_AZ`) idxal etsəydi, başlıq mətni hesabat məntiqindən asılı
#: olardı və həmin sabitin adı dəyişəndə örtük sükutla sınardı. Siyahı
#: TƏQVİM FAKTIdır — dəyişmir.
MONTHS_AZ: Final[tuple[str, ...]] = (
    "Yanvar",
    "Fevral",
    "Mart",
    "Aprel",
    "May",
    "İyun",
    "İyul",
    "Avqust",
    "Sentyabr",
    "Oktyabr",
    "Noyabr",
    "Dekabr",
)


def _format_date_az(moment: datetime) -> str:
    """«17 Avqust 2026» — başlıqdakı tarix."""
    return f"{moment.day} {MONTHS_AZ[moment.month - 1]} {moment.year}"


def _format_month_az(moment: datetime) -> str:
    """«Avqust 2026» — aylıq ekranların dövrü."""
    return f"{MONTHS_AZ[moment.month - 1]} {moment.year}"


def _stores_az(count: int) -> str:
    """«1 filial» / «21 filial» — say HƏMİŞƏ göstərilir.

    Sıfır da yazılır («0 filial»): mağazasız quraşdırma real vəziyyətdir və
    onu gizlətmək istifadəçini «niyə heç nə görünmür?» sualı ilə tək qoyardı.
    """
    return f"{count} filial"


#: Windows Taskbar-ın tətbiqi tanıdığı kimlik.
#:
#: DƏYƏR SABİT QALMALIDIR: istifadəçi tətbiqi Taskbar-a sancanda Windows məhz
#: bu sətri yadda saxlayır. Versiyada dəyişsək, sancılmış nişan «başqa proqram»
#: sayılar və köhnəsi ölü qalar. Ona görə versiya nömrəsi BURAYA yazılmır.
APP_USER_MODEL_ID: Final = "KompasOS.Desktop.1"

#: Uz qatinin modul acari — sondurulubse qeydiyyat TELEB OLUNMUR.
#: `controllers/face_setup.FACE_MODULE` ile eyni deyer olmalidir.
FACE_MODULE_KEY: Final = "CAMERA_VERIFICATION"


def _set_app_user_model_id() -> None:
    r"""Taskbar ikonunu düzəldir — `setWindowIcon` TƏK BAŞINA KİFAYƏT ETMİR.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ İKON GÖRÜNMÜRDÜ
    ──────────────────────────────────────────────────────────────────────────
    `setWindowIcon()` PƏNCƏRƏNİN ikonunu verir (başlıq, Alt-Tab). Taskbar isə
    düymələri **AppUserModelID** üzrə qruplaşdırır və ikonu həmin kimliyə
    bağlı qeyddən götürür. Kimlik AÇIQ təyin edilməyəndə Windows onu İCRA
    OLUNAN FAYLIN yolundan çıxarır — paketlənmiş `onefile` `.exe`-də isə
    faktiki proses `%TEMP%\_MEIxxxxx\` altından işə düşür və həmin yol hər
    açılışda DƏYİŞİR. Nəticədə Windows tətbiqi tanımır və ümumi ikon göstərir.

    Ona görə kimlik BURADA, ilk pəncərə yaranmazdan ƏVVƏL təyin olunur.
    Sonra çağırılsa təsir etmir: Windows kimliyi pəncərə yaradılan anda oxuyur.

    YALNIZ WINDOWS: `shell32` digər platformalarda yoxdur və olmaması nasazlıq
    deyil — Linux/macOS Taskbar-ı `.desktop`/bundle metadatasından oxuyur.
    Uğursuzluq da udulur: ikon problemi tətbiqi dayandırmamalıdır.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes  # noqa: PLC0415

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        _log.warning("APP_USER_MODEL_ID_NOT_SET", exc_info=True)
    else:
        _log.debug("APP_USER_MODEL_ID_SET", extra={"app_id": APP_USER_MODEL_ID})


def _apply_window_icon(app: QApplication) -> None:
    """Tətbiq ikonunu təyin edir — paketlənmiş və mənbə rejimində.

    Əvvəl `setWindowIcon` HEÇ ÇAĞIRILMIRDI: `.ico` yalnız PyInstaller-ə
    verilirdi (`--icon`), yəni `.exe` faylının ÖZÜ düzgün görünürdü, lakin
    işləyən pəncərə, Taskbar və Alt-Tab defolt Qt ikonunu göstərirdi. Bölmə 9
    hər dörd yeri açıq şəkildə sadalayır.

    Fayl tapılmasa səssiz keçilir — ikonun olmaması tətbiqi dayandırmamalıdır.
    """
    from PySide6.QtGui import QIcon  # noqa: PLC0415

    from src.shared.runtime import bundle_root, deployment_root  # noqa: PLC0415

    # İki kök: paketlənmiş rejimdə fayl arxivin İÇİNDƏDİR (`--add-data`),
    # mənbədən işləyəndə isə layihə qovluğundadır.
    roots = [root for root in (bundle_root(), deployment_root()) if root is not None]
    for root in roots:
        path = root / ICON_RELATIVE_PATH
        if path.exists():
            app.setWindowIcon(QIcon(str(path)))
            return
    _log.warning("WINDOW_ICON_MISSING", extra={"roots": [str(root) for root in roots]})


class KompasApplication:
    """Tətbiqin pəncərə və ekran qrafını qurur.

    Args:
        preview: `True` → ekranlar maketdəki nümunə məzmunla doldurulur
            (bax `preview_data.py`). İstehsalatda `False`.
    """

    def __init__(
        self,
        app: QApplication,
        *,
        preview: bool = False,
        theme_preference: ThemeMode = ThemeMode.SYSTEM,
        context: ApplicationContext | None = None,
    ) -> None:
        self._app = app
        self._preview = preview
        _apply_window_icon(app)
        #: Canlı obyekt qrafı (Faza 5/6). `None` -> önizləmə/dizayn rejimi.
        self._context = context
        self._theme = ThemeManager(preference=theme_preference)
        self._theme.apply(app)

        self._registry = build_default_registry()
        self._window = FramelessWindow(title="KompasOS", theme=self._theme)
        # Başlıq zolağındakı tema düyməsi HƏR ekranda işləyir — splash,
        # sihirbaz, giriş və örtük. Əvvəl düymə YALNIZ örtüyün səhifə
        # başlığında idi, yəni girişdən əvvəl temanı dəyişmək mümkün deyildi
        # və istifadəçi «işıqlı/qaranlıq mod işləmir» kimi görürdü.
        self._window.theme_toggle_requested.connect(self.toggle_theme)
        # GİZLİ BƏRPA KONSOLU — `Ctrl+Shift+K` (RECOVERY-1 Faza 2).
        #
        # Qısayol PƏNCƏRƏYƏ bağlanır, ekrana yox: konsol məhz o hallarda
        # lazımdır ki, ekranın özü nasazlıq ekranıdır və hansı ekranın açıq
        # olduğu əvvəlcədən bilinmir. Ekranda HEÇ BİR vizual ipucu yoxdur —
        # düymə, link və ya tooltip qoysaydıq, «gizli» sözünün mənası qalmazdı
        # və mağaza işçisi ora təsadüfən düşərdi.
        self._recovery_shortcut = QShortcut(QKeySequence("Ctrl+Shift+K"), self._window)
        self._recovery_shortcut.activated.connect(self.open_recovery_console)
        #: Konsoldan «Yadda Saxla» sonrası yenidən qurma çağırışı (`run()` verir).
        self._rebuild_context: Callable[[], ApplicationContext] | None = None
        self._shell: AdminShell | None = None
        self._support: QWidget | None = None
        self._notifications: QWidget | None = None
        #: Daxil olmuş istifadəçi — tema saxlanması və ekran doldurulması üçün.
        self._current_employee: Employee | None = None
        #: Real autentifikasiya (Faza 5). `None` → önizləmə/izah rejimi.
        self._auth: AuthController | None = None
        #: Kiosk PIN körpüsü (Faza 5). `None` → önizləmə rejimi.
        self._kiosk_controller: KioskController | None = None
        #: Ekranları canlı məlumatla dolduran körpü — login-dən sonra qurulur.
        self._binder: ScreenDataBinder | None = None
        #: Cərimə formasının yazı yolu — dropdown-ları da bu verir.
        self._fine_entry: FineEntryController | None = None
        #: «Şübhəli Satışlar» növbəsi — işçi açılan siyahısını O verir, ona
        #: görə ekran QURULMAZDAN ƏVVƏL lazımdır (bax `_register_screens`).
        self._sales_review: SalesReviewController | None = None
        #: Sübut şəkillərini arxa planda Drive-a köçürən taymer.
        self._upload_timer: QTimer | None = None
        #: Planlaşdırılmış YÜNGÜL fon işlərini işlədən taymer (Faza 11).
        #: Sübut taymeri ilə YAN-YANA dayanır, onu ƏVƏZ ETMİR: ritmləri ayrı
        #: Root parametrlərindən gəlir (biri şəbəkəyə, digəri gecə işlərinə
        #: kökləndiyi üçün eyni intervalı paylaşa bilməzlər).
        self._scheduler_timer: QTimer | None = None
        #: Plugin-lərin verdiyi səhifələr (audit G-3) — girişdə hesablanır.
        self._plugin_pages: tuple[PluginPage, ...] = ()

    # ------------------------------- pəncərə --------------------------------- #

    def window(self) -> FramelessWindow:
        return self._window

    def theme(self) -> ThemeManager:
        return self._theme

    def start(self) -> None:
        """Splash ilə başlayır və girişə keçir.

        Splash arxasında lisenziya vəziyyəti yoxlanılır (bölmə 8): tenant
        deaktiv edilibsə tətbiq TAM bağlanır və yalnız izahlı
        `LICENSE_INACTIVE` ekranı göstərilir — heç bir modul, o cümlədən PIN
        handshake, işləmir.
        """
        from src.presentation.screens.group_a_entry import SplashScreen  # noqa: PLC0415

        splash = SplashScreen(self._theme, version=__version__)
        splash.finished.connect(self._after_splash)
        self._window.set_content(splash)
        self._window.show()
        splash.finish_after(SPLASH_DURATION_MS)

    def show_loading_splash(self) -> None:
        """Splash-ı DƏRHAL göstərir — kontekst qurulmamışdan ƏVVƏL.

        `start()`-dakı splash-dan fərqi budur ki, burada bitmə taymeri
        QURULMUR: ekran ağır işin (baza hovuzu) nə qədər çəkəcəyini bilmir və
        sabit müddət ya erkən bitər, ya da lazımsız gözlətmə yaradardı.
        Sonrakı axını `_load_context_behind_splash` idarə edir.
        """
        from src.presentation.screens.group_a_entry import SplashScreen  # noqa: PLC0415

        splash = SplashScreen(self._theme, version=__version__)
        self._window.set_content(splash)
        self._window.show()

    def set_context(self, context: ApplicationContext | None) -> None:
        """Kontekst SONRADAN qoşulur (splash arxasında qurulanda).

        Konstruktorda `None` ötürülür, çünki pəncərə kontekstdən ƏVVƏL
        görünməlidir — əks halda baza əlçatmaz olan maşında istifadəçi
        taymaut bitənə qədər boş ekran görürdü.
        """
        self._context = context

    def _after_splash(self) -> None:
        """Splash bitdi — lisenziya qapısı, sonra quraşdırma və ya giriş."""
        if self._context is not None and self._context.license_blocked():
            self.show_license_blocked()
            return
        route = self._startup_route()
        if route is StartupRoute.SCHEMA_MISSING:
            self.show_fatal_error(
                "Baza sxemi tətbiq olunmayıb: cədvəllər tapılmadı. "
                "Quraşdırma sənədindəki `database/schema.sql` addımını icra "
                "edin və ya dəstəklə əlaqə saxlayın."
            )
            return
        if route is StartupRoute.SETUP_WIZARD:
            self.show_setup_wizard()
            return
        self.show_login()

    def _startup_route(self) -> StartupRoute:
        """Splash-dan sonra HANSI ekranın açılacağını BİR sorğu ilə həll edir.

        ──────────────────────────────────────────────────────────────────────
        ÜÇ HAL — ÜÇÜ DƏ FƏRQLİ ADDIM TƏLƏB EDİR
        ──────────────────────────────────────────────────────────────────────
        * **Sxem yoxdur** (`SQLSTATE 42P01`) — sihirbaz da işləyə bilməz, onun
          ilk yazısı elə həmin cədvələ gedir. Əvvəl bu hal ümumi `except`-ə
          düşürdü və istifadəçi GİRİŞ ekranını görürdü: «istifadəçi adı və ya
          şifrə yanlışdır» yazırdı, halbuki səbəb şifrə deyil, quraşdırılmamış
          baza idi.
        * **Admin yoxdur** — BOŞ BAZA. Bu, XƏTA DEYİL, gözlənilən ilk açılışdır
          və sihirbaza aparır.
        * **Admin var** — giriş.

        Sorğu BİR DƏFƏ edilir: iki ayrı yoxlama (əvvəlcə "sxem varmı", sonra
        "admin varmı") eyni sualı iki dəfə verər və aralarındakı anda vəziyyət
        dəyişsə, ekran öz yoxlamasına zidd qərar verərdi.

        SQLSTATE ilə yoxlanılır, mətnlə deyil: psycopg xəta mətnini server
        dilində qaytarır, yəni mətn müqayisəsi lokalizasiyaya bağlı olardı.

        Naməlum xətada GİRİŞ seçilir: sihirbazı SƏHVƏN açmaq mövcud
        quraşdırmanı "boş" göstərər və ilk Root hesabı üzərinə yazmağa
        çalışardı; giriş ekranı isə ən pis halda "giriş alınmadı" deyir və
        geri qaytarıla bilən vəziyyətdir.
        """
        if self._context is None:
            return StartupRoute.LOGIN
        try:
            with self._context.session() as session:
                required = bool(session.setup.is_required(self._context.tenant_id))
        except Exception as exc:
            if getattr(exc, "sqlstate", None) == _UNDEFINED_TABLE:
                _log.error("DATABASE_SCHEMA_MISSING", extra={"sqlstate": _UNDEFINED_TABLE})
                return StartupRoute.SCHEMA_MISSING
            _log.exception("SETUP_CHECK_FAILED")
            return StartupRoute.LOGIN
        return StartupRoute.SETUP_WIZARD if required else StartupRoute.LOGIN

    def show_license_blocked(self) -> None:
        """Bölmə 8: səbəb + borc tarixi + əlaqə vasitəsi AÇIQ göstərilir."""
        from src.presentation.screens.group_e import LicenseInactiveScreen  # noqa: PLC0415

        assert self._context is not None
        headline, detail, contact = self._context.license_screen_text()
        screen = LicenseInactiveScreen(
            self._theme,
            # `headline` səbəbi bir cümlə ilə deyir ("Aylıq ödəniş edilməyib"),
            # `detail` isə tarix/borc kontekstini verir — bölmə 8 hər ikisini
            # AÇIQ tələb edir, ümumi xəta mesajı qadağandır.
            reason=headline or "Lisenziya deaktiv edilib",
            deactivated_at=detail or "—",
            installation_id=str(self._context.tenant_id),
            support_contact=contact or "dəstək@kompas.az",
        )
        self._window.set_content(screen)

    def show_setup_wizard(self) -> None:
        """İlk Quraşdırma Sihirbazı (bölmə 7) — tamamlandıqda girişə keçir."""
        from src.presentation.screens.group_a_entry import FirstRunWizard  # noqa: PLC0415

        wizard = FirstRunWizard(self._theme)
        # Sihirbaza istinad SAXLANMIR — o, `lambda`-nın bağlamasında yaşayır
        # və ekranla birlikdə ölür (`CLAUDE.md` §6 kontroller naxışı).
        wizard.completed.connect(lambda payload: self._on_setup_completed(payload, wizard))
        self._window.set_content(wizard)

    def _on_setup_completed(self, payload: dict[str, object], wizard: QWidget) -> None:
        """Sihirbaz formu doldurdu — hesab/mağaza yaradılır, sonra giriş.

        Sihirbaz EKRANI özü heç nə yazmır (o, yalnız formadır); yazma
        `FirstRunSetupUseCase`-dədir və o, "tenant boşdurmu?" qapısını
        yenidən yoxlayır — ekranın vəziyyətinə güvənilmir.

        ──────────────────────────────────────────────────────────────────────
        DÜZƏLDİLƏ BİLƏN SƏHV FATAL DEYİL
        ──────────────────────────────────────────────────────────────────────
        Əvvəl burada `except Exception` vardı və HƏR uğursuzluq «KompasOS işə
        düşə bilmədi» ekranına aparırdı. Nəticə istehsalatda göründü: zəif
        şifrə yazan istifadəçi proqramın SINDIĞINI düşünürdü — halbuki
        jurnalda sadəcə `WeakSecretError` vardı və düzəliş bir sahədə idi.

        Ayırma İSTİSNA TİPİNƏ görədir, mesaj mətninə görə yox: mətn tərcümə
        və ya redaktə ilə dəyişə bilər, tip isə dəyişməz. Siyahıda olmayan
        hər şey FATAL qalır — «bilinməyəni buraxmaq» prinsipi tərsinədir və
        sükutla yarımçıq quraşdırma yaradardı.
        """
        if self._context is None:
            self.show_login()
            return

        from src.application.use_cases.first_run_setup import (  # noqa: PLC0415
            SetupValidationError,
        )
        from src.domain.value_objects.credentials import (  # noqa: PLC0415
            InvalidEmailError,
            InvalidUsernameError,
        )
        from src.infrastructure.security.hashing import WeakSecretError  # noqa: PLC0415

        #: İstisna tipi → düzəldiləcək sahənin adı (boş = ümumi mesaj).
        correctable: tuple[tuple[type[Exception], str], ...] = (
            (WeakSecretError, "_password"),
            (InvalidUsernameError, "_username"),
            (InvalidEmailError, "_email"),
            (SetupValidationError, ""),
        )

        try:
            self._context.complete_setup(payload)
        except Exception as exc:
            for kind, field in correctable:
                if isinstance(exc, kind):
                    _log.warning(
                        "FIRST_RUN_SETUP_REJECTED",
                        extra={"error_type": type(exc).__name__, "field": field or "—"},
                    )
                    message = getattr(exc, "user_message", "") or str(exc)
                    show_error = getattr(wizard, "show_error", None)
                    if callable(show_error):
                        show_error(message, field=field)
                        return
                    break
            _log.exception("FIRST_RUN_SETUP_FAILED")
            self.show_fatal_error(getattr(exc, "user_message", "Quraşdırma tamamlana bilmədi."))
            return

        # CEO-NUN ÜZ QEYDİYYATI SİHİRBAZIN SONUNDADIR (SEC-025).
        # İşçilər onu İLK GİRİŞDƏ keçir və orada yanlarındakı admin
        # təsdiqləyir; CEO üçün bu mümkün deyil, çünki o an tenant-da ondan
        # başqa admin YOXDUR. Şərti use case özü yoxlayır.
        if self._start_ceo_face_setup(payload):
            return
        self.show_login()

    def _start_ceo_face_setup(self, payload: dict[str, object]) -> bool:
        """Sihirbazdan sonra CEO-nun üz qeydiyyatı ekranını açır.

        Returns:
            `True` — ekran göstərildi; `False` — şərt ödənmir və adi axın
            (giriş ekranı) davam etməlidir.

        UĞURSUZLUQ AXINI DAYANDIRMIR: quraşdırma ARTIQ tamamlanıb və hesab
        yaranıb. Üz qeydiyyatı alınmasa istifadəçi giriş edə bilməlidir —
        əks halda kamerasız maşında quraşdırma dalana düşərdi.
        """
        employee = self._ceo_face_setup_subject(payload)
        if employee is None:
            return False

        from src.presentation.controllers.face_setup import (  # noqa: PLC0415
            FaceSetupController,
        )
        from src.presentation.screens.face_control import (  # noqa: PLC0415
            FaceSetupRequiredScreen,
        )

        assert self._context is not None
        screen = FaceSetupRequiredScreen(
            self._theme, employee_name=employee.full_name, supervised=False
        )
        FaceSetupController(self._context, employee, bootstrap=True).attach(screen)
        screen.skipped.connect(self.show_login)
        self._window.set_content(screen)
        _log.info("CEO_FACE_SETUP_STARTED", extra={"employee_id": str(employee.id)})
        return True

    def _ceo_face_setup_subject(self, payload: dict[str, object]) -> Employee | None:
        """Üz qeydiyyatı LAZIMDIRSA CEO-nu qaytarır, əks halda `None`.

        Aktor SAKİTCƏ autentifikasiya olunur: istifadəçi adı və şifrə formada
        indicə yazılıb, təkrar soruşmaq nə əlavə yoxlama, nə də təhlükəsizlik
        verərdi — yalnız quraşdırmanı uzadardı.

        `is_enrollment_required()` BURADA İŞLƏDİLMİR: o, `Root`/`CEO` pilləsini
        qəsdən istisna sayır (adi ilk-giriş qapısı üçün doğrudur, çünki orada
        NƏZARƏTÇİ tələb olunur). Bootstrap yolu isə məhz həmin pillə üçündür.
        """
        root_raw = payload.get("root")
        if (
            self._context is None
            or self._preview
            or self._auth is None
            or not isinstance(root_raw, dict)
        ):
            return None

        from src.domain.value_objects.credentials import Username  # noqa: PLC0415

        try:
            outcome = self._auth.authenticate(
                Username(str(root_raw.get("username", ""))),
                str(root_raw.get("password", "")),
            )
            employee = getattr(outcome, "employee", None)
            if not isinstance(employee, Employee):
                return None
            with self._context.session() as session:
                enabled = session.toggles.is_enabled(session.tenant_id, FACE_MODULE_KEY)
                profile = session.uow.repository("face_embeddings").get_profile(employee.id)
        except Exception:
            _log.exception("CEO_FACE_SETUP_CHECK_FAILED")
            return None

        if not enabled or (profile is not None and profile.is_enrolled):
            return None
        return employee

    # -------------------------------- giriş ---------------------------------- #

    def show_login(self) -> None:
        from src.presentation.screens.group_a_entry import AdminLoginScreen  # noqa: PLC0415

        login = AdminLoginScreen(self._theme)
        login.submitted.connect(self._on_login_submitted)
        login.face_login_requested.connect(self._on_face_login_requested)
        # DÜYMƏ YALNIZ İŞLƏYƏCƏYİ HALDA GÖRÜNÜR (kioskdakı ilə eyni qayda).
        # Önizləmədə həmişə göstərilir ki, dizayn baxışı ekranın tam formasını
        # görsün — orada kamera və baza onsuz da yoxdur.
        login.set_face_login_available(self._preview or self._face_login_available())
        self._window.set_content(login)
        self._login = login

    def _face_login_available(self) -> bool:
        """«Üzlə daxil ol» düyməsi bu maşında mənalıdırmı."""
        if self._context is None:
            return False

        from src.presentation.controllers.face_login import (  # noqa: PLC0415
            FaceLoginController,
        )

        return FaceLoginController(self._context).available()

    def _on_face_login_requested(self, username: str) -> None:
        """«Üzlə daxil ol» — şifrəsiz giriş (1:1 üz doğrulaması).

        Önizləmədə şifrə yolu ilə EYNİ nümunə ekranı açılır: maket rejimində
        kamera yoxdur, lakin düymənin AXINI göstərilməlidir — əks halda dizayn
        baxışında o, ölü bir düymə kimi görünərdi.
        """
        from datetime import UTC, datetime  # noqa: PLC0415

        if self._context is None:
            if self._preview:
                from src.presentation import preview_data  # noqa: PLC0415

                self.show_admin(preview_data.build_admin(), now=preview_data.PREVIEW_NOW)
                return
            self._login.set_error("Baza bağlantısı qurulmayıb — üzlə giriş mümkün deyil.")
            return

        from src.presentation.controllers.face_login import (  # noqa: PLC0415
            FaceLoginController,
        )

        self._login.set_busy(True)
        try:
            outcome = FaceLoginController(self._context).authenticate(username)
        finally:
            # Düymələr HƏR halda açılır — uğursuzluqdan sonra istifadəçi şifrə
            # yoluna keçə bilməlidir.
            self._login.set_busy(False)

        if outcome.failed or outcome.employee is None:
            self._login.set_error(outcome.message)
            return

        self._login.clear()
        employee = outcome.employee
        # Üz qeydiyyatı qapısı BURADA DA ÇAĞIRILIR, baxmayaraq ki, üzlə girən
        # işçinin profili onsuz da var: qapı «modul açıq + qeydiyyat yoxdur»
        # şərtinə baxır və bu yolda `False` qaytarır. Şərti burada təkrar
        # yazsaydıq, iki mənbə yaranardı.
        if self._show_face_setup_if_required(
            employee, on_continue=lambda: self.show_admin(employee, now=datetime.now(UTC))
        ):
            return
        self.show_admin(employee, now=datetime.now(UTC))

    def set_kiosk_controller(self, controller: KioskController) -> None:
        """Kiosk PIN körpüsünü qoşur (Faza 5)."""
        self._kiosk_controller = controller

    def set_auth_controller(self, controller: AuthController) -> None:
        """Real autentifikasiyanı qoşur (Faza 5).

        Qoşulmayıbsa `--preview` rejimi istənilən dəyəri qəbul edir, adi
        rejim isə səbəbi izah edən mesaj göstərir — səssiz uğursuzluq yox.
        """
        self._auth = controller

    def _on_login_submitted(self, username: str, password: str) -> None:
        """Giriş cəhdi — kontrollerə ötürülür (bax `controllers/auth.py`)."""
        if self._auth is not None:
            self._authenticate(username, password)
            return

        if not self._preview:
            self._login.set_error(
                "Baza bağlantısı qurulmayıb — giriş yoxlanıla bilmir. "
                "Ekranlara baxmaq üçün `--preview` bayrağı ilə açın."
            )
            return

        _log.info("PREVIEW_LOGIN", extra={"username": username})
        from src.presentation import preview_data  # noqa: PLC0415

        self.show_admin(preview_data.build_admin(), now=preview_data.PREVIEW_NOW)

    def _authenticate(self, username: str, password: str) -> None:
        """Real giriş axını.

        Kontroller istisna ATMIR — nəticə həmişə `AuthOutcome`-dur, ona görə
        burada `try/except` yoxdur (bax `controllers/auth.py` başlığı).
        """
        from datetime import UTC, datetime  # noqa: PLC0415

        from src.domain.value_objects.credentials import Username  # noqa: PLC0415

        assert self._auth is not None

        self._login.set_busy(True)
        try:
            outcome = self._auth.authenticate(Username(username), password)
        finally:
            # Düymə HƏR halda açılır — xəta olsa da istifadəçi yenidən
            # cəhd edə bilməlidir.
            self._login.set_busy(False)

        if not outcome.succeeded:
            self._login.set_error(outcome.message)
            return

        if outcome.must_change_password:
            # Bölmə 2: şifrə dəyişdirilməmiş sessiya açılmır.
            self._login.set_error("Şifrəniz dəyişdirilməlidir. Admininizlə əlaqə saxlayın.")
            return

        self._login.clear()
        employee = outcome.employee
        if not isinstance(employee, Employee):  # pragma: no cover - tip qoruyucusu
            self._login.set_error("Giriş nəticəsi oxuna bilmədi.")
            return

        # İLK GİRİŞ ÜZ QEYDİYYATI — örtükdən ƏVVƏL. Sonra göstərsəydik, işçi
        # ekranları bir anlıq görər və qeydiyyat «əlavə pəncərə» kimi oxunardı.
        if self._show_face_setup_if_required(
            employee, on_continue=lambda: self.show_admin(employee, now=datetime.now(UTC))
        ):
            return
        self.show_admin(employee, now=datetime.now(UTC))

    def _show_face_setup_if_required(
        self,
        employee: Employee,
        *,
        on_continue: Callable[[], None],
        host: Callable[[QWidget], None] | None = None,
    ) -> bool:
        """Üz qeydiyyatı tələb olunursa ekranı göstərir.

        Tələb HƏR İKİ giriş qapısında eyni funksiyadan keçir (panel girişi və
        kiosk PIN-i): yalnız birində qoysaydıq, digər qapı sükutla açıq qalar
        və işçi üz qeydiyyatını heç vaxt keçməzdi.

        Args:
            host: Ekranı YERLƏŞDİRƏN funksiya. Defolt əsas pəncərədir; kiosk
                rejimində isə AYRI pəncərə var (`KioskWindow`) və ekranı ora
                qoymaq lazımdır. Parametrsiz yazsaydıq, kioskda qeydiyyat
                ekranı görünməz bir pəncərədə açılardı.

        Returns:
            `True` — ekran göstərildi və çağıran DAYANMALIDIR.
        """
        if self._context is None or self._preview or self._auth is None:
            return False

        from src.presentation.controllers.face_setup import (  # noqa: PLC0415
            FaceSetupController,
            is_enrollment_required,
        )

        try:
            with self._context.session() as session:
                if not is_enrollment_required(session, employee):
                    return False
        except Exception:
            # Yoxlama alınmadısa AXIN DAYANMIR: üz qatı iş dayandıran nasazlığa
            # çevrilməməlidir (səbəb `is_enrollment_required` başlığındadır).
            _log.exception("FACE_SETUP_GATE_FAILED")
            return False

        from src.domain.value_objects.credentials import Username  # noqa: PLC0415
        from src.presentation.screens.face_control import (  # noqa: PLC0415
            FaceSetupRequiredScreen,
        )

        auth = self._auth
        screen = FaceSetupRequiredScreen(self._theme, employee_name=employee.full_name)
        # Kontrollerə istinad SAXLANMIR: o, `lambda`-ların bağlamasında yaşayır
        # və ekranla birlikdə ölür (`CLAUDE.md` §6).
        FaceSetupController(
            self._context,
            employee,
            authenticate=lambda username, password: auth.authenticate(Username(username), password),
        ).attach(screen)
        screen.skipped.connect(on_continue)
        (host or self._window.set_content)(screen)
        _log.info("FACE_SETUP_REQUIRED", extra={"employee_id": str(employee.id)})
        return True

    # ------------------------------- örtük ----------------------------------- #

    def set_rebuild_context(self, factory: Callable[[], ApplicationContext] | None) -> None:
        """Bərpa konsolundan sonra kontekstin yenidən qurulma yolu."""
        self._rebuild_context = factory

    def open_recovery_console(self) -> None:
        """`Ctrl+Shift+K` — qapıdan keçirsə konsolu açır, keçmirsə SUSUR.

        ──────────────────────────────────────────────────────────────────────
        RƏDD MESAJI QƏSDƏN YOXDUR
        ──────────────────────────────────────────────────────────────────────
        «İcazəniz yoxdur» yazsaydıq, bu, elə ipucunun özü olardı: istifadəçi
        həmin qısayolun BİR ŞEY açdığını öyrənərdi. Rədd yalnız
        `security.log`-a düşür (bax `controllers/recovery_console.may_open`).
        """
        from src.infrastructure.config.connection_file import (  # noqa: PLC0415
            find_connection_file,
        )

        configured = self._context is not None or find_connection_file() is not None
        if not _recovery_may_open(actor=self._current_employee, configured=configured):
            return
        self.show_recovery_console()

    def show_recovery_console(self) -> None:
        """Bərpa konsolunu açır (qapı ARTIQ yoxlanılıb)."""
        from src.presentation.controllers.recovery_console import (  # noqa: PLC0415
            RecoveryConsoleController,
        )
        from src.presentation.screens.recovery_console import (  # noqa: PLC0415
            RecoveryConsoleScreen,
        )

        screen = RecoveryConsoleScreen(self._theme)
        controller = RecoveryConsoleController()
        controller.attach(screen)
        # Kontrollerə istinad `lambda`-nın bağlamasında yaşayır (CLAUDE.md §6).
        screen.closed.connect(lambda: self._leave_recovery_console(controller))
        self._window.set_content(screen)
        self._window.show()
        screen.focus_first_field()

    def _leave_recovery_console(self, controller: object) -> None:
        """Konsol bağlandı — normal axına qayıdılır.

        Kontekst varsa (yəni tətbiq işləkdir) sadəcə girişə qayıdırıq; yoxdursa
        `rebuild` ilə YENİDƏN cəhd edilir, çünki texnik məhz bağlantını
        düzəltmək üçün konsola girmişdi.
        """
        _ = controller
        if self._context is None and self._rebuild_context is not None:
            self._attempt_startup(self._rebuild_context)
            return
        self.show_login()

    def logout(self) -> None:
        """Sessiyanı bağlayır və giriş ekranına qayıdır (RECOVERY-1 Faza 1).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ ÖRTÜK DƏ SİLİNİR — TƏKCƏ EKRAN DƏYİŞMİR
        ──────────────────────────────────────────────────────────────────────
        Örtük İSTİFADƏÇİYƏ görə qurulur: menyu maddələri onun icazə
        flag-lərinə, ekranlar isə onun kimliyinə bağlıdır. Yalnız məzmunu
        dəyişsəydik, köhnə örtük yaddaşda qalar və növbəti giriş ikinci nüsxə
        yaradardı — bir müddət sonra eyni siqnal iki dəfə emal olunardı
        (`screen_revisited` iki örtüyə də çatardı).

        Kiosk rejiminə TOXUNULMUR: orada hər əməliyyatdan sonra PIN ekranına
        qayıdış onsuz da var (`group_a_kiosk.py`) və oradakı «Çıxış» ayrı
        axındır.
        """
        _log.info("SESSION_LOGOUT", extra={"had_shell": self._shell is not None})
        self._current_employee = None
        self._shell = None
        self.show_login()

    def show_admin(self, employee: Employee, *, now: datetime) -> None:
        """Admin örtüyünü qurur və bütün ekranları qeydiyyata alır."""
        self._current_employee = employee
        self._apply_stored_theme(employee)
        if self._context is not None:
            from src.presentation.controllers.fine_entry import (  # noqa: PLC0415
                FineEntryController,
            )
            from src.presentation.controllers.sales_review import (  # noqa: PLC0415
                SalesReviewController,
            )
            from src.presentation.controllers.screen_data import (  # noqa: PLC0415
                ScreenDataBinder,
            )

            self._binder = ScreenDataBinder(self._context, employee)
            self._fine_entry = FineEntryController(self._context, employee)
            # Növbə kontrolleri BURADA qurulur, çünki ekranın açılan siyahısı
            # (işçi adları) KONSTRUKTORA lazımdır — ekran qurulandan sonra
            # onu doldurmaq mümkün deyil.
            self._sales_review = SalesReviewController(self._context, employee)
            self._start_upload_timer()
            self._start_scheduler_timer()

        # PLUGIN SƏTHİ (audit G-3) — reyestr HƏR GİRİŞDƏ TƏZƏDƏN qurulur.
        #
        # Səbəb: plugin dəsti iki giriş arasında dəyişə bilər (Root birini
        # təsdiqləyir/söndürür). Eyni reyestrə təkrar yazsaydıq, ikinci giriş
        # "açar təkrarlanır" xətası ilə qarşılaşar və maddə sükutla itərdi.
        # `build_default_registry()`-nin öz sənədləşməsi də məhz bu səbəbdən
        # hər çağırışda təzə obyekt qaytarır.
        self._plugin_pages = self._collect_plugin_pages()
        self._registry = build_default_registry()
        register_plugin_pages(self._registry, self._plugin_pages)

        shell = AdminShell(
            theme=self._theme,
            registry=self._registry,
            employee=employee,
            now=now,
            enabled_modules=self._enabled_modules(),
        )
        shell.theme_toggle_requested.connect(self.toggle_theme)
        shell.logout_requested.connect(self.logout)
        # Panelə QAYIDANDA rəqəmlər yenidən oxunur (bax `_on_screen_revisited`).
        shell.screen_revisited.connect(self._on_screen_revisited)
        # TƏRTİBAT REJİMİ: pəncərə ölçür, örtük paylayır (bax
        # `widgets/responsive.py`). Bağlantı BURADADIR, çünki örtük hər
        # girişdə yenidən qurulur — köhnə örtükdəki bağlantı onunla birlikdə
        # ölür, yenisi isə cari rejimi dərhal alır.
        self._window.layout_mode_changed.connect(shell.apply_layout_mode)
        shell.apply_layout_mode(self._window.layout_mode)
        self._shell = shell
        self._register_screens(shell)

        self._window.set_content(shell)
        self._install_overlays(shell)
        self._refresh_context_subtitles(shell, now=now)
        self._refresh_support_badges(shell)

        # İlk açılan ekran — menyuda görünən ilk maddə. Sabit "dashboard"
        # yazmaq olmazdı: icazəsi olmayan istifadəçidə boş ekran qalardı.
        visible = shell.sidebar().entry_keys()
        if visible:
            shell.show_screen(visible[0])

    #: Ekrana QAYIDANDA məlumatı yenidən oxunan açarlar.
    #:
    #: SİYAHI DARDIR VƏ SƏBƏBİ VAR: hər ekranı hər naviqasiyada yenidən
    #: doldurmaq onlarla sorğunu istifadəçinin hər klikinə bağlayardı, üstəlik
    #: yazı yolu olan ekranlarda (cərimə forması, növbə) doldurulmamış formanı
    #: silərdi. İdarə paneli isə YALNIZ OXUYUR və məhz orada köhnə rəqəm
    #: görünürdü: mağaza/işçi əlavə edildikdən sonra say dəyişmirdi.
    REFRESH_ON_REVISIT: Final[frozenset[str]] = frozenset({"dashboard"})

    def _on_screen_revisited(self, key: str) -> None:
        """Artıq qurulmuş ekrana qayıdış — sayğacları təzələyir."""
        if key not in self.REFRESH_ON_REVISIT or self._binder is None or self._shell is None:
            return
        screen = self._shell.screen_for(key)
        if screen is None:  # pragma: no cover - siqnal yalnız qurulmuş ekran üçün yayılır
            return
        self._binder.populate(key, screen)

    def _refresh_support_badges(self, shell: AdminShell) -> None:
        """Sol paneldəki dəstək sayğaclarını doldurur (CHAT-1 Faza 6).

        SAY YALNIZ `🔴 Açıq` STATUSDUR (tg1.md Faza 6), oxunmamış deyil:
        nişan «məndə iş qalıb» deməkdir. Söhbəti açıb cavab yazmayan Root
        üçün oxunmamış say sıfıra düşərdi — yəni gözdən keçirmək işi
        bitirmiş kimi görünərdi.

        SƏLAHİYYƏTİ OLMAYAN İSTİFADƏÇİDƏ SORĞU DA GETMİR: `actionable_count`
        `can_view` yoxlamasından keçir və sıfır qaytarır, `Sidebar.set_badge`
        isə naməlum açarı sükutla buraxır (maddə onsuz da panelə düşməyib).

        UĞURSUZLUQ SƏSSİZDİR: sayğac köməkçi məlumatdır — onun oxunmaması
        girişi dayandırmamalıdır.
        """
        from src.domain.value_objects.support import SupportChannel  # noqa: PLC0415

        if self._context is None or self._current_employee is None:
            return
        keys = {
            SupportChannel.INTERNAL: "internal_requests",
            SupportChannel.TECHNICAL: "technical_support",
        }
        try:
            with self._context.session(user_id=self._current_employee.id) as session:
                counts = {
                    key: session.support_inbox.actionable_count(
                        tenant_id=session.tenant_id,
                        actor=self._current_employee,
                        channel=channel,
                    )
                    for channel, key in keys.items()
                }
        except Exception:
            _log.exception("SUPPORT_BADGE_REFRESH_FAILED")
            return
        for key, count in counts.items():
            shell.sidebar().set_badge(key, count)

    def _refresh_context_subtitles(self, shell: AdminShell, *, now: datetime) -> None:
        """Başlıqdakı say/tarix mətnlərini CANLI məlumatdan doldurur.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ BU METOD YARANDI
        ──────────────────────────────────────────────────────────────────────
        Kontekst mətnləri maketdən gələn SABİTLƏR idi: «21 filial»,
        «235 nəfər», «12 Avqust 2026». Bir mağazası olan quraşdırmada da ekran
        «21 filial» yazırdı və istifadəçi onu real say sanırdı.

        SAY BAZADAN GƏLİR, ƏL İLƏ TƏYİN EDİLMİR: mağaza əlavə edildikdə rəqəm
        növbəti açılışda özü artır. Ayrıca «filial sayı» parametri
        yaratsaydıq, o, `stores` cədvəli ilə sinxrondan çıxan ikinci həqiqət
        mənbəyi olardı.

        UĞURSUZLUQ SƏSSİZDİR VƏ BOŞ QALIR: sorğu alınmasa mətn yazılmır.
        Yanlış rəqəm göstərməkdənsə heç nə göstərməmək dürüstdür — bu, həmin
        qüsurun ÖZ dərsidir.
        """
        if self._context is None:
            return
        try:
            with self._context.session() as session:
                row = session.uow.connection.execute(
                    """
                    SELECT
                        (SELECT count(*) FROM stores
                          WHERE tenant_id = %s AND is_active)    AS store_count,
                        (SELECT count(*) FROM employees
                          WHERE tenant_id = %s AND is_active)    AS employee_count
                    """,
                    (str(self._context.tenant_id), str(self._context.tenant_id)),
                ).fetchone()
        except Exception:
            _log.exception("SHELL_SUBTITLE_COUNTS_UNAVAILABLE")
            return

        if row is None:
            return
        stores = int(row["store_count"])
        employees = int(row["employee_count"])
        today = _format_date_az(now)

        shell.set_screen_subtitle("dashboard", f"{_stores_az(stores)} · {today}")
        shell.set_screen_subtitle("users", f"{employees} nəfər · {_stores_az(stores)}")
        shell.set_screen_subtitle("daily_roster", today)
        shell.set_screen_subtitle("fines", _format_month_az(now))
        _log.debug(
            "SHELL_SUBTITLES_REFRESHED",
            extra={"store_count": stores, "employee_count": employees},
        )

    def _enabled_modules(self) -> frozenset[str] | None:
        """Root tərəfindən AÇIQ saxlanılan modulların açarları (bölmə 3).

        DYNAMIC UI INTEGRATION: söndürülmüş modulun menyu maddəsi boz DEYİL,
        tamamilə render-dən kəsilir (`NavigationRegistry._is_visible`).

        `None` qaytarmaq "süzgəc tətbiq etmə" deməkdir və QƏSDƏN fail-open-dur:
        toggle mənbəyinə çatmamaq bütün naviqasiyanı boşaltmamalıdır — modulu
        söndürmək AÇIQ əməliyyat olmalıdır, şəbəkə nasazlığının yan təsiri yox
        (eyni istiqamət `PostgresFeatureToggles.is_enabled`-də də seçilib).
        """
        if self._context is None:
            return None
        try:
            with self._context.session() as session:
                return frozenset(session.toggles.enabled_modules(self._context.tenant_id))
        except Exception:
            _log.exception("FEATURE_TOGGLES_LOAD_FAILED")
            return None

    # --------------------------- plugin səthi (G-3) --------------------------- #

    def _collect_plugin_pages(self) -> tuple[PluginPage, ...]:
        """Təsdiqlənmiş plugin-lərin menyu səhifələri.

        MAKET VƏ CANLI YOL EYNİ FUNKSİYADAN KEÇİR (`collect_surface`) — yəni
        beş təhlükəsizlik qapısı (imza, təsdiq, qabiliyyət, icazə flag-i, ad
        məkanı) hər iki rejimdə eynidir. Maket öz "hər şey görünür" yolunu
        qursaydı, qapılardan birinin sınması yalnız istehsalatda üzə çıxardı.

        Oxu uğursuzluğu BOŞ NƏTİCƏ verir, istisna YOX: plugin cədvəlinin
        əlçatmazlığı girişi dayandırmamalıdır (fail-closed istiqamət onsuz da
        qorunur — səth boşdursa plugin heç nə əlavə etmir).
        """
        from src.presentation.plugin_surface import (  # noqa: PLC0415
            PluginRegistrySurface,
            collect_surface,
        )

        if self._preview:
            from src.presentation import preview_data  # noqa: PLC0415

            return collect_surface(preview_data.PLUGIN_SURFACE).pages
        if self._context is None:
            return ()
        try:
            with self._context.session() as session:
                surface = PluginRegistrySurface(
                    session.uow.repository("plugins"), self._context.tenant_id
                ).surface()
        except Exception:
            _log.exception("PLUGIN_PAGES_LOAD_FAILED")
            return ()
        return surface.pages

    def _plugin_page_factory(self, page: PluginPage) -> Callable[[], QWidget]:
        """Plugin səhifəsinin fabrikası.

        `make(...)` BÜKÜCÜSÜ İŞLƏDİLMİR: `preview_screens.populate` və
        `ScreenDataBinder.populate` sabit ekran açarları ilə işləyir və plugin
        açarını tanımadığı üçün hər səhifədə `SCREEN_BINDER_MISSING`
        xəbərdarlığı yazardı — halbuki burada əskik bağlama YOXDUR, məzmunu
        səthin özü verir.

        MƏZMUN ARTIQ PLUGIN-DƏN GƏLİR (audit G-3-ün icra qatı). Əvvəl səhifə
        yalnız manifestdə ELAN olunmuş metadata göstərirdi, çünki `PluginSandbox.
        invoke` `PLUGIN_SANDBOX_TIMEOUT_SECONDS`-ə qədər bloklayır və Qt hadisə
        dövrəsində interfeysi dondururdu. İndi çağırış `BackgroundTask` ilə
        FONDA icra olunur (bax `controllers/plugin_page.py`): səhifə DƏRHAL
        açılır, məzmun isə gələndə yerini tutur.

        FORMA YENƏ HOST-UNDUR: plugin widget ağacı qurmur, yalnız MƏTN verir
        və o mətn zəngin mətn kimi render OLUNMUR (bax `PluginPageScreen`
        başlığı və `plugin_page.py`-dakı "ETİBARSIZ GİRİŞ" bölməsi).

        MAKET REJİMİ İCRA ETMİR: orada nə baza sətri, nə də paket faylı var —
        səhifə metadata + açıq bir izah sətri göstərir. Sətrin ETİKETİ hər iki
        yolda eynidir (`plugin_page.CONTENT_LABEL`), yəni maket öz ad məkanını
        qurmur (CLAUDE.md bölmə 6).
        """

        def build() -> QWidget:
            from src.presentation.controllers.plugin_page import (  # noqa: PLC0415
                CONTENT_LABEL,
                PREVIEW_TEXT,
                attach_plugin_page,
                metadata_rows,
            )
            from src.presentation.screens.group_i import PluginPageScreen  # noqa: PLC0415

            screen = PluginPageScreen(
                self._theme,
                plugin_name=page.plugin_name,
                publisher=page.publisher,
            )
            if self._preview or self._context is None:
                screen.set_rows([*metadata_rows(page), (CONTENT_LABEL, PREVIEW_TEXT)])
                return screen

            attach_plugin_page(screen, page=page, context=self._context)
            return screen

        return build

    def _queue_store_filter_threshold(self) -> int:
        """Növbədəki mağaza süzgəcinin görünmə həddi (audit G-6).

        ROOT-dan oxunur (`CAMERA_QUEUE_STORE_FILTER_THRESHOLD`); oxu mümkün
        deyilsə modul fallback-ı işləyir — `_upload_poll_interval_ms` ilə eyni
        əsaslandırma: verilməli cavab "növbə açılsınmı" deyil, "seçici
        neçədən sonra görünsün" idi.
        """
        from src.presentation.screens.group_b import (  # noqa: PLC0415
            QUEUE_STORE_FILTER_THRESHOLD,
        )

        if self._context is None:
            return QUEUE_STORE_FILTER_THRESHOLD
        try:
            value = self._context.infrastructure_limits().int_of(
                SystemLimitKey.CAMERA_QUEUE_STORE_FILTER_THRESHOLD
            )
        except Exception:
            _log.exception("QUEUE_STORE_FILTER_THRESHOLD_READ_FAILED")
            return QUEUE_STORE_FILTER_THRESHOLD
        return max(1, value)

    def _start_upload_timer(self) -> None:
        """Sübut növbəsini dövri boşaldır (Faza 3.9).

        `EvidenceUploadWorker` özü sap YARATMIR — planlaşdırma çağıranın
        işidir. Burada Qt taymeri seçilib, ayrıca `threading.Thread` yox:
        yükləmə bitdikdən sonra `fines` sətri yenilənir və o iş bazaya
        toxunur; Qt hadisə dövrəsində qalmaq bu yazının interfeyslə eyni
        sırada getməsini təmin edir.

        İNTERVAL ARTIQ ROOT-DANDIR (`EVIDENCE_UPLOAD_POLL_INTERVAL_SECONDS`,
        Faza 10.2): əvvəl sabit 120 000 ms idi və zəif internetli filialda onu
        seyrəkləşdirmək üçün yeni buraxılış lazım gəlirdi. Dəyər BURADA, taymer
        qurularkən bir dəfə oxunur — Qt taymerinin intervalını hər dövrədə
        yenidən soruşmaq üçün ikinci bir taymer lazım olardı; yeni ritm növbəti
        girişdə qüvvəyə minir və bu, fon işi üçün kifayət qədər tezdir.
        """
        if self._context is None or self._upload_timer is not None:
            return
        timer = QTimer(self._window)
        timer.setInterval(self._upload_poll_interval_ms())
        timer.timeout.connect(self._drain_upload_queue)
        timer.start()
        self._upload_timer = timer

    def _upload_poll_interval_ms(self) -> int:
        """Fon dövrəsinin ritmi — ROOT-dan, oxuna bilmirsə fallback.

        Baza əlçatmazlığı BURADA istisna atmır: verilməli cavab "növbə
        boşaldılsınmı" deyil, "hansı ritmlə" idi. Cavabsız qaldıqda sabit ritm
        işləyir və sübut şəkilləri yenə göndərilir (eyni əsaslandırma
        `composition._upload_limit`-dədir).
        """
        if self._context is None:
            return FALLBACK_UPLOAD_POLL_INTERVAL_MS
        try:
            seconds = self._context.infrastructure_limits().int_of(
                SystemLimitKey.EVIDENCE_UPLOAD_POLL_INTERVAL_SECONDS
            )
        except Exception:
            _log.exception("UPLOAD_POLL_INTERVAL_READ_FAILED")
            return FALLBACK_UPLOAD_POLL_INTERVAL_MS
        return max(MIN_UPLOAD_POLL_INTERVAL_SECONDS, seconds) * 1000

    def _drain_upload_queue(self) -> None:
        if self._context is None:
            return
        # `run_evidence_uploads` özü istisna udur və 0 qaytarır — fon işi
        # interfeysi çökdürməməlidir (bax `composition.py`).
        uploaded = self._context.run_evidence_uploads()
        if uploaded:
            _log.info("EVIDENCE_UPLOADED", extra={"count": uploaded})

    # --------------------------- planlaşdırılmış işlər ------------------------ #

    def _start_scheduler_timer(self) -> None:
        """Planlaşdırılmış YÜNGÜL işləri dövri işlədir (Faza 11).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ AYRICA TAYMER — SÜBUT TAYMERİNƏ QOŞULMUR
        ──────────────────────────────────────────────────────────────────────
        İki dövrənin ritmi FƏRQLİ suallara cavab verir: sübut növbəsi filialın
        internetindən (`EVIDENCE_UPLOAD_POLL_INTERVAL_SECONDS`, dəqiqələr),
        planlayıcı isə gecə işlərinin gecikmə dözümündən
        (`SCHEDULER_POLL_INTERVAL_MINUTES`, 15 dəq.) asılıdır. Birinə
        qoşsaydıq, Root iki parametrdən birini dəyişəndə digəri də sükutla
        sürüşərdi. Mövcud `_upload_timer` OLDUĞU KİMİ QALIR.

        `include_heavy=False` — GUI axını `pg_dump` çağıran işi icra ETMİR
        (interfeys dəqiqələrlə donardı). Ağır iş yalnız CLI-dan işləyir:
        `main.py --run-scheduled-jobs` (bax `docs/scheduler_setup.md`).

        İNTERVAL SABİT DEYİL — `JobRunner.poll_interval()`-dan, yəni ROOT
        parametrindən oxunur. Dəyər taymer qurularkən bir dəfə alınır (eyni
        qərar `_start_upload_timer`-dədir: Qt taymerinin intervalını hər
        dövrədə yenidən soruşmaq üçün ikinci taymer lazım olardı; yeni ritm
        növbəti girişdə qüvvəyə minir).
        """
        if self._context is None or self._scheduler_timer is not None:
            return
        timer = QTimer(self._window)
        timer.setInterval(self._scheduler_poll_interval_ms())
        timer.timeout.connect(self._run_scheduled_jobs)
        timer.start()
        self._scheduler_timer = timer

    def _scheduler_poll_interval_ms(self) -> int:
        """Planlayıcı dövrəsinin ritmi — ROOT-dan, oxuna bilmirsə fallback.

        Baza əlçatmazlığı BURADA istisna atmır (eyni əsaslandırma
        `_upload_poll_interval_ms`-dədir): verilməli cavab "işlər icra
        olunsunmu" deyil, "hansı ritmlə" idi. Cavabsız qaldıqda `DEFAULT_LIMITS`
        ritmi işləyir və gecə işləri yenə də icra olunur.
        """
        if self._context is None:
            return FALLBACK_SCHEDULER_POLL_INTERVAL_MS
        try:
            interval = self._context.job_runner().poll_interval(self._context.tenant_id)
        except Exception:
            _log.exception("SCHEDULER_POLL_INTERVAL_READ_FAILED")
            return FALLBACK_SCHEDULER_POLL_INTERVAL_MS
        milliseconds: int = int(interval.total_seconds() * 1000)
        return milliseconds

    def _run_scheduled_jobs(self) -> None:
        """Bir dövrə — YALNIZ yüngül işlər. İstisna GUI-ni çökdürMÜR.

        `composition.run_scheduled_jobs` istisnanı QƏSDƏN udmur (CLI çıxış
        kodu ondan çıxır), ona görə udma məhz BURADADIR — `_drain_upload_queue`
        ilə eyni prinsip: fon işinin nasazlığı pəncərəni bağlamamalıdır, lakin
        jurnalda görünməlidir.
        """
        if self._context is None:
            return
        try:
            report = self._context.run_scheduled_jobs(include_heavy=False)
        except Exception:
            _log.exception("SCHEDULED_JOBS_CYCLE_FAILED")
            return
        if report.executed:
            _log.info(
                "SCHEDULED_JOBS_CYCLE",
                extra={
                    "icra_edilen": report.executed,
                    "ugurlu": report.succeeded,
                    "ugursuz": list(report.failed_jobs),
                },
            )

    def _attach_fine_entry(self, screen: QWidget) -> None:
        """Cərimə formasını use case-ə və sübut növbəsinə bağlayır (bölmə 4)."""
        from src.presentation.screens.group_b import FineEntryScreen  # noqa: PLC0415

        if self._fine_entry is None or not isinstance(screen, FineEntryScreen):
            return
        self._fine_entry.attach(screen)

    def _attach_fine_review(self, screen: QWidget) -> None:
        """«Aylıq Cərimə İcmalı»nı `MonthlyFineReviewUseCase`-ə bağlayır.

        Ekran menyuda `can_publish_fines` ilə qapılıdır, lakin FAKTİKİ qapı
        use case-dədir (`_assert_may_publish`) — menyunun görünməsi əməliyyat
        icazəsi DEYİL (bax `menu.py` başlığı).

        Kontrollerə istinad SAXLANMIR: o, siqnallara bağladığı `lambda`-ların
        bağlamasında yaşayır və ekranla birlikdə ölür (eyni naxış
        `_attach_annual_leave`-dədir).
        """
        from src.presentation.controllers.fine_review import (  # noqa: PLC0415
            MonthlyFineReviewController,
        )
        from src.presentation.screens.fine_review import (  # noqa: PLC0415
            MonthlyFineReviewScreen,
        )

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, MonthlyFineReviewScreen):  # pragma: no cover - tip qoruyucusu
            return
        MonthlyFineReviewController(self._context, self._current_employee).attach(screen)

    def _attach_camera_queue(self, screen: QWidget) -> None:
        """`[Vaxtı Əllə Təyin Et]` — dual-control həddi ROOT limitindən."""
        from src.presentation.controllers.camera_queue import (  # noqa: PLC0415
            CameraQueueController,
        )
        from src.presentation.screens.group_b import OperatorQueueScreen  # noqa: PLC0415

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, OperatorQueueScreen):  # pragma: no cover - tip qoruyucusu
            return
        CameraQueueController(self._context, self._current_employee).attach(screen)

    def _may_contact_support(self) -> bool:
        """`can_contact_support` — defolt CEO/Root/HR_Admin (bölmə 8).

        Önizləmə rejimində HƏMİŞƏ `True`: maket ekranlarının hamısı
        göstərilməlidir və orada real istifadəçi konteksti yoxdur.
        """
        if self._preview:
            return True
        employee = self._current_employee
        if employee is None:
            return False
        from datetime import UTC, datetime  # noqa: PLC0415

        from src.application.use_cases.support_chat import (  # noqa: PLC0415
            CONTACT_SUPPORT_FLAG,
        )

        return bool(employee.has_permission(CONTACT_SUPPORT_FLAG, now=datetime.now(UTC)))

    def _attach_drive_connection(self, screen: QWidget) -> None:
        """Google razılıq axınını ekrana bağlayır (miqrasiya 002).

        Kontrollerə burada istinad SAXLANMIR — o, siqnallara bağladığı
        `lambda`-ların bağlamasında yaşayır və ekranla birlikdə ölür (eyni
        naxış `_attach_root_control`-dadır). Gözləmə taymeri də `screen`-in
        övladıdır, ona görə ekran bağlananda o da dayanır.
        """
        from src.presentation.controllers.drive_connection import (  # noqa: PLC0415
            DriveConnectionController,
        )
        from src.presentation.screens.group_d import (  # noqa: PLC0415
            DriveConnectionScreen,
        )

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, DriveConnectionScreen):  # pragma: no cover - tip qoruyucusu
            return
        DriveConnectionController(self._context, self._current_employee).attach(screen)

    def _attach_catalog_admin(self, key: str, screen: QWidget) -> None:
        """Üç kataloq ekranını öz use case-inə bağlayır (bölmə 4).

        Ekran sinfi ÜÇÜ üçün ORTAQDIR (`group_h.CatalogScreen`), ona görə
        `isinstance` hansı kataloq olduğunu AYIRD EDƏ BİLMİR — açar açıq
        şəkildə ötürülür. Bu, `make(key, ...)`-dəki eyni açardır, yəni maket
        (`preview_screens`) və canlı yol eyni ad məkanını işlədir.

        Kontrollerə istinad SAXLANMIR: o, siqnallara bağladığı `lambda`-ların
        bağlamasında yaşayır və ekranla birlikdə ölür (eyni naxış
        `_attach_root_control`-dadır).
        """
        from src.presentation.controllers.catalog_admin import (  # noqa: PLC0415
            CatalogAdminController,
        )
        from src.presentation.screens.group_h import CatalogScreen  # noqa: PLC0415

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, CatalogScreen):  # pragma: no cover - tip qoruyucusu
            return
        CatalogAdminController(self._context, self._current_employee, key=key).attach(screen)

    def _attach_write_controller(self, key: str, screen: QWidget) -> None:
        """Ekran sinfinə görə YAZI kontrollerini qoşur.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ CƏDVƏL, NİYƏ `elif` ZƏNCİRİ DEYİL
        ──────────────────────────────────────────────────────────────────────
        Faza 5/6-da bağlanan ekranların sayı 12-ni keçdi və `elif` zənciri həm
        oxunmaz, həm də hər yeni ekranda bir az daha uzun olurdu. Cədvəl eyni
        SIRA semantikasını saxlayır (ilk uyğunluq qazanır — alt-siniflər üçün
        vacibdir), lakin yeni sətir əlavə etmək bir sətirlik dəyişiklikdir.

        `key` YALNIZ kataloqlara lazımdır: üç kataloq EYNİ sinifdəndir
        (`group_h.CatalogScreen`) və `isinstance` hansı olduğunu ayırd edə
        bilmir (bax `controllers/catalog_admin.py` başlığı).
        """
        from src.presentation.screens import (  # noqa: PLC0415
            group_b,
            group_c,
            group_d,
            group_f,
            group_g,
            group_h,
            group_i,
        )
        from src.presentation.screens.announcements import (  # noqa: PLC0415
            AnnouncementsScreen,
        )
        from src.presentation.screens.annual_leave import (  # noqa: PLC0415
            AnnualLeaveInboxScreen,
        )
        from src.presentation.screens.attrition_risk import (  # noqa: PLC0415
            AttritionRiskScreen,
        )
        from src.presentation.screens.bulk_operations import (  # noqa: PLC0415
            BulkOperationsScreen,
        )
        from src.presentation.screens.devices import (  # noqa: PLC0415
            DeviceAdminScreen,
        )
        from src.presentation.screens.face_control import (  # noqa: PLC0415
            FaceEnrollmentScreen,
            FaceExemptionScreen,
        )
        from src.presentation.screens.field_reports import (  # noqa: PLC0415
            FieldReportScreen,
        )
        from src.presentation.screens.fine_review import (  # noqa: PLC0415
            MonthlyFineReviewScreen,
        )
        from src.presentation.screens.performance_review import (  # noqa: PLC0415
            PerformanceReviewScreen,
        )
        from src.presentation.screens.support_inbox import (  # noqa: PLC0415
            SupportInboxScreen,
        )
        from src.presentation.screens.sync_conflicts import (  # noqa: PLC0415
            SyncConflictScreen,
        )

        handlers: tuple[tuple[type[QWidget], Callable[[QWidget], None]], ...] = (
            # Ayarlar ekranı tema seçimini örtüyə bağlayır — bu, önizləmə
            # məzmunu deyil, real davranışdır və hər iki rejimdə lazımdır.
            (group_d.SettingsScreen, self._attach_settings),
            # ROOT paneli həm oxuyur, həm yazır (limit, modul açarı, yeni flag).
            (group_d.RootControlScreen, self._attach_root_control),
            (group_d.DriveConnectionScreen, self._attach_drive_connection),
            # Cərimə formasının və növbənin YAZI yolları (sübut yükləməsi,
            # manual vaxt düzəlişi) — hər ikisi ROOT limitlərini işlədir.
            (group_b.FineEntryScreen, self._attach_fine_entry),
            (group_b.OperatorQueueScreen, self._attach_camera_queue),
            # Aylıq Cərimə İcmalı (miqrasiya 003) — HƏM oxuyur, HƏM yazır və
            # nəşrdən sonra siyahını yenidən oxuyur (nəşr olunan cərimə
            # `PENDING_REVIEW`-dan çıxır). Bax `controllers/fine_review.py`.
            (MonthlyFineReviewScreen, self._attach_fine_review),
            (group_h.CatalogScreen, lambda widget: self._attach_catalog_admin(key, widget)),
            (group_h.HelpCenterScreen, self._attach_help_center),
            # kompas1.md Faza 8 — export təcrübəsi. Ekranın DÖVR/LOCK məlumatı
            # `_binders()`-dəki `_reports`-dan gəlməyə DAVAM EDİR; kontroller
            # YALNIZ doğrulama/düzəliş/müqayisə bölməsini bağlayır (`users` və
            # `shift_planning` ilə eyni hibrid naxış).
            (group_h.ReportExportScreen, self._attach_report_export),
            # Faza 5/6 yazı yolları — hər biri öz use case-inə bağlanır.
            (group_c.PermissionMatrixScreen, self._attach_permission_matrix),
            # #7 POS Səlahiyyət Siyasəti (sənədləşdirmə, Faza 4) — "···"
            # menyusunun YALNIZ "POS Səlahiyyəti" bəndini emal edir.
            (group_c.UsersScreen, self._attach_users_pos_threshold),
            # #16 Açıq Növbə Bazarı (Faza 6) — matrisin canlı məlumatı
            # `_binders()`-dən gəlməyə DAVAM EDİR; kontroller YALNIZ açıq
            # elan kartını bağlayır (`users` ekranındakı ilə eyni hibrid
            # naxış — bax `controllers/open_shift.py` başlığı).
            (group_c.ShiftPlanningScreen, self._attach_open_shift_market),
            (group_f.UnassignedSalesScreen, self._attach_sales_review),
            (group_i.PluginScreen, self._attach_plugin_admin),
            (group_i.DashboardBuilderScreen, self._attach_dashboard_builder),
            # #24 Çox-Mağaza Benchmark (Faza 9A) — YALNIZ siqnal bağlaması
            # (dropdown + drill-down); canlı MƏLUMAT `_binders()`-dəki
            # `_dashboard`-dan gəlməyə davam edir (bax metodun başlığı).
            (group_c.DashboardScreen, self._attach_dashboard_benchmark),
            # #9-un GUI tərəfi (kompasos11.md Faza 5) — bax `controllers/exceptions.py`.
            (group_i.ExceptionsScreen, self._attach_exceptions),
            # #19/#20 Ünsiyyət və Performans (kompasos11.md Faza 8) — hər ikisi
            # HƏM oxuyur, HƏM yazır (bax `controllers/announcements.py` və
            # `controllers/performance_review.py` başlıqları).
            (AnnouncementsScreen, self._attach_announcements),
            (PerformanceReviewScreen, self._attach_performance_review),
            # #28 İllik Məzuniyyət Balansı (kompas1.md Faza 4) — təsdiq
            # növbəsi HƏM oxuyur, HƏM yazır və hər qərardan sonra siyahını
            # yenidən oxuyur (bax `controllers/annual_leave.py` başlığı).
            (AnnualLeaveInboxScreen, self._attach_annual_leave),
            # #21 İşdən Çıxma Riski (kompasos11.md Faza 9) — TAMAMİLƏ oxu
            # ekranıdır, lakin baxış audit-ləndiyi üçün ÖZ kontrolleri var
            # (bax `controllers/attrition_risk.py` başlığı).
            (AttritionRiskScreen, self._attach_attrition_risk),
            # Face Control (facecontrol.md Faza 4) — hər ikisi HƏM oxuyur,
            # HƏM yazır: qeydiyyatdan sonra işçinin vəziyyəti dəyişir, istisna
            # verildikdən sonra siyahıya düşür (bax `controllers/
            # face_control.py` başlığı).
            (FaceEnrollmentScreen, self._attach_face_enrollment),
            (FaceExemptionScreen, self._attach_face_exemptions),
            # #29 Toplu Əməliyyatlar (kompas1.md Faza 5) — CSV idxalı + mağaza
            # şablonu HƏR İKİSİ HƏM oxuyur, HƏM yazır (bax `controllers/
            # bulk_operations.py` başlığı).
            (BulkOperationsScreen, self._attach_bulk_operations),
            # #26+#27 Sahə hesabatları (kompas1.md Faza 3) — İKİ menyu açarı,
            # BİR ekran sinfi. `key` ötürülür, çünki `isinstance` «Mağaza
            # Auditi» ilə «İnsident Bildirişi»ni ayırd edə bilmir — üç kataloq
            # ekranındakı (`_attach_catalog_admin`) EYNİ vəziyyət.
            (FieldReportScreen, lambda widget: self._attach_field_reports(key, widget)),
            # G-1 (bölmə 5) — offline konfliktlərin manual həlli. HƏM oxuyur,
            # HƏM yazır və hər qərardan sonra siyahını yenidən oxuyur (bax
            # `controllers/sync_conflicts.py` başlığı).
            (SyncConflictScreen, self._attach_sync_conflicts),
            # DEVICE-1: təsdiq/blok/köçürmə — hər yazıdan sonra siyahı VƏ
            # lisenziya sayğacı yenidən oxunur (bax `controllers/devices.py`).
            (DeviceAdminScreen, self._attach_devices),
            # CHAT-1: hər iki dəstək bölməsi EYNİ sinifdəndir və EYNİ
            # kontrollerə bağlanır — kanal ekranın öz sahəsindədir.
            (SupportInboxScreen, self._attach_support_inbox),
            (group_g.ProfileScreen, self._attach_profile),
            # Faza 3 yekunu: ERP, ehtiyat nüsxə, baza keçidi və diaqnostika.
            # Tapşırıq lövhəsi: «Nəzərdən Keçirilir» sütunundakı təsdiq/rədd
            # düymələri use case-ə bağlanır və hər qərardan sonra lövhə
            # yenidən oxunur (CLAUDE.md bölmə 6).
            (group_f.TasksScreen, self._attach_task_review),
            # Satış Xalları: «Al» və sətir-səviyyəli «Etiraz» use case-ə
            # bağlanır; hər yazıdan sonra balans+tarixçə+kataloq yenidən
            # oxunur (`screen_data._sales_points` başlığındakı vəd).
            (group_f.SalesPointsScreen, self._attach_sales_points),
            (group_d.ErpServersScreen, self._attach_erp_servers),
            # Audit jurnalı YALNIZ OXUYUR, lakin hər süzgəc/səhifə dəyişikliyində
            # YENİDƏN oxuyur — `screen_data`-nın tək çağırışı bunu ödəmir.
            (group_d.AuditScreen, self._attach_audit_log),
            (group_d.BackupScreen, self._attach_backups),
            (group_i.InfrastructureScreen, self._attach_infrastructure),
            (group_d.HealthScreen, self._attach_health),
        )
        for screen_type, handler in handlers:
            if isinstance(screen, screen_type):
                handler(screen)
                return

    def _attach_sales_points(self, screen: QWidget) -> None:
        """Mükafat sorğusu və xal etirazı — `SalesPointsUseCase`-ə bağlayır.

        İki düymə ekranda VARDI, lakin siqnal yükləri use case-in tələb
        etdiyi identifikatorları daşımırdı (`reward_requested` mükafatın
        ADINI yayırdı, `appeal_requested` isə heç nə) — yəni bağlantı texniki
        olaraq mümkün deyildi. İndi hər ikisi identifikator daşıyır.
        """
        from src.presentation.controllers.sales_points import (  # noqa: PLC0415
            SalesPointsController,
        )
        from src.presentation.screens.group_f import SalesPointsScreen  # noqa: PLC0415

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, SalesPointsScreen):  # pragma: no cover - tip qoruyucusu
            return
        SalesPointsController(self._context, self._current_employee).attach(screen)

    def _attach_task_review(self, screen: QWidget) -> None:
        """Tapşırıq təsdiqi/rəddi — `TaskWorkflowUseCase`-ə bağlayır.

        Düymələr ekranda VARDI və siqnal yayırdı, lakin onları dinləyən tərəf
        yox idi: menecer «Təsdiqlə» basırdı, tapşırıq sütunda qalırdı, xəta da
        çıxmırdı. İşçi isə sübutunu göndərib gözləyirdi — və gecikmə
        eskalasiyası onu gecikmiş sayırdı.
        """
        from src.presentation.controllers.tasks import TaskReviewController  # noqa: PLC0415
        from src.presentation.screens.group_f import TasksScreen  # noqa: PLC0415

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, TasksScreen):  # pragma: no cover - tip qoruyucusu
            return
        TaskReviewController(self._context, self._current_employee).attach(screen)

    def _attach_audit_log(self, screen: QWidget) -> None:
        """Audit süzgəclərini və səhifələməsini `AuditQueryUseCase`-ə bağlayır.

        Süzgəc sahələri ekranda ARTIQ vardı və `filters_changed`/`page_changed`
        siqnallarını yayırdı, lakin heç bir kontroller onları dinləmirdi —
        istifadəçi tarix aralığı seçir, «2» səhifəsini basır, cədvəl isə
        dəyişmirdi. Ən pisi: ekran heç bir xəta göstərmirdi, yəni nəticə
        "süzgəcə uyğun yazı budur" kimi oxunurdu.
        """
        from src.presentation.controllers.audit_log import (  # noqa: PLC0415
            AuditLogController,
        )
        from src.presentation.screens.group_d import AuditScreen  # noqa: PLC0415

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, AuditScreen):  # pragma: no cover - tip qoruyucusu
            return
        AuditLogController(self._context, self._current_employee).attach(screen)

    def _attach_settings(self, screen: QWidget) -> None:
        """Ayarlar ekranındakı tema seçimi — hər iki rejimdə qoşulur (bölmə 9)."""
        from src.presentation.screens.group_d import SettingsScreen  # noqa: PLC0415

        if not isinstance(screen, SettingsScreen):  # pragma: no cover - tip qoruyucusu
            return
        screen.select_theme(self._theme.preference.value)
        screen.theme_selected.connect(self._on_theme_selected)

        # Qalan dörd idarəedici (Yadda Saxla, bildiriş açarları, şifrə,
        # sessiyalar) ÖZ kontrollerinə bağlanır: onlar `user_preferences`-ə
        # yazır və ekran açılanda saxlanmış vəziyyət geri oxunur.
        # Tema BURADA qalır, çünki o, yazıdan ƏVVƏL dərhal tətbiq olunur və
        # hər iki rejimdə (önizləmə daxil) işləməlidir.
        if self._preview or self._context is None or self._current_employee is None:
            return
        from src.presentation.controllers.settings import SettingsController  # noqa: PLC0415

        SettingsController(self._context, self._current_employee).attach(screen)

    def _attach_profile(self, screen: QWidget) -> None:
        """Profil ekranını canlı hesab məlumatına bağlayır (bölmə 2, 3).

        `username`/`email` sahələri ekranda QƏSDƏN söndürülüb və kontroller
        onları yazı yoluna BURAXMIR (bax `controllers/profile.py` başlığı).
        """
        from src.presentation.controllers.profile import ProfileController  # noqa: PLC0415
        from src.presentation.screens.group_g import ProfileScreen  # noqa: PLC0415

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, ProfileScreen):  # pragma: no cover - tip qoruyucusu
            return
        ProfileController(self._context, self._current_employee).attach(screen)

    def _attach_plugin_admin(self, screen: QWidget) -> None:
        """Plugin ekranını `PluginManagementUseCase`-ə bağlayır (bölmə 1)."""
        from src.presentation.controllers.plugin_admin import (  # noqa: PLC0415
            PluginAdminController,
        )
        from src.presentation.screens.group_i import PluginScreen  # noqa: PLC0415

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, PluginScreen):  # pragma: no cover - tip qoruyucusu
            return
        PluginAdminController(self._context, self._current_employee).attach(screen)

    def _attach_exceptions(self, screen: QWidget) -> None:
        """ "İstisnalar" ekranını `ExceptionEngineUseCase`-ə bağlayır (#9, Faza 5).

        `PluginScreen`/`DashboardBuilderScreen` ilə EYNİ naxış: ekranın canlı
        yolu `ScreenDataBinder`-də deyil, çünki o həm oxuyur, həm yazır (bax
        `controllers/exceptions.py` başlığı).
        """
        from src.presentation.controllers.exceptions import (  # noqa: PLC0415
            ExceptionsController,
        )
        from src.presentation.screens.group_i import ExceptionsScreen  # noqa: PLC0415

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, ExceptionsScreen):  # pragma: no cover - tip qoruyucusu
            return
        ExceptionsController(self._context, self._current_employee).attach(screen)

    def _attach_announcements(self, screen: QWidget) -> None:
        """ "Elanlar" ekranını `AnnouncementUseCase`-ə bağlayır (#19, Faza 8)."""
        from src.presentation.controllers.announcements import (  # noqa: PLC0415
            AnnouncementsAdminController,
        )
        from src.presentation.screens.announcements import (  # noqa: PLC0415
            AnnouncementsScreen,
        )

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, AnnouncementsScreen):  # pragma: no cover - tip qoruyucusu
            return
        AnnouncementsAdminController(self._context, self._current_employee).attach(screen)

    def _attach_report_export(self, screen: QWidget) -> None:
        """ "Aylıq Hesabatlar" ekranının export təcrübəsini bağlayır (Faza 8).

        Ekran HİBRİDDİR: dövr etiketi və LOCK xülasəsi `ScreenDataBinder.
        _reports`-dan (yalnız oxu), doğrulama/düzəliş/müqayisə isə bu
        kontrollerdən gəlir (bax `controllers/report_export.py` başlığı).
        """
        from src.presentation.controllers.report_export import (  # noqa: PLC0415
            ReportExportController,
        )
        from src.presentation.screens.group_h import ReportExportScreen  # noqa: PLC0415

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, ReportExportScreen):  # pragma: no cover - tip qoruyucusu
            return
        ReportExportController(self._context, self._current_employee).attach(screen)

    def _attach_bulk_operations(self, screen: QWidget) -> None:
        """ "Toplu Əməliyyatlar" ekranını use case-lərə bağlayır (#29, Faza 5)."""
        from src.presentation.controllers.bulk_operations import (  # noqa: PLC0415
            BulkOperationsController,
        )
        from src.presentation.screens.bulk_operations import (  # noqa: PLC0415
            BulkOperationsScreen,
        )

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, BulkOperationsScreen):  # pragma: no cover - tip qoruyucusu
            return
        BulkOperationsController(self._context, self._current_employee).attach(screen)

    def _attach_performance_review(self, screen: QWidget) -> None:
        """ "Performans Qiymətləndirmələri" ekranını use case-ə bağlayır (#20, Faza 8)."""
        from src.presentation.controllers.performance_review import (  # noqa: PLC0415
            PerformanceReviewController,
        )
        from src.presentation.screens.performance_review import (  # noqa: PLC0415
            PerformanceReviewScreen,
        )

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, PerformanceReviewScreen):  # pragma: no cover - tip qoruyucusu
            return
        PerformanceReviewController(self._context, self._current_employee).attach(screen)

    def _attach_annual_leave(self, screen: QWidget) -> None:
        """«Məzuniyyət Sorğuları» ekranını `AnnualLeaveUseCase`-ə bağlayır (#28).

        Ekran `can_manage_leave_balances` ilə qapılıdır (menyu maddəsi), lakin
        FAKTİKİ qapı use case-dədir (`pending_inbox` → `_require_manager`) —
        menyunun görünməsi əməliyyat icazəsi DEYİL (bax `menu.py` başlığı).
        """
        from src.presentation.controllers.annual_leave import (  # noqa: PLC0415
            AnnualLeaveInboxController,
        )
        from src.presentation.screens.annual_leave import (  # noqa: PLC0415
            AnnualLeaveInboxScreen,
        )

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, AnnualLeaveInboxScreen):  # pragma: no cover - tip qoruyucusu
            return
        AnnualLeaveInboxController(self._context, self._current_employee).attach(screen)

    def _attach_support_inbox(self, screen: QWidget) -> None:
        """Dəstək gələnlər qutusunu `SupportInboxUseCase`-ə bağlayır (CHAT-1).

        TELEGRAM SORĞUSU YALNIZ TEXNİKİ BÖLMƏDƏ İŞƏ DÜŞÜR və orada da yalnız
        bot qurulubsa. Səbəb `infrastructure/notifications/telegram.py`
        başlığındadır: `getUpdates` bir yeniliyi TƏK dəfə verir, yəni sorğunu
        birdən çox yerdə aparmaq cavabların bir hissəsini itirərdi.
        """
        from src.presentation.controllers.support_inbox import (  # noqa: PLC0415
            SupportInboxController,
        )
        from src.presentation.screens.support_inbox import (  # noqa: PLC0415
            SupportInboxScreen,
        )

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, SupportInboxScreen):  # pragma: no cover - tip qoruyucusu
            return

        poller = None
        interval_ms = 0
        if screen.channel.notifies_telegram:
            poller, interval_ms = self._build_telegram_poller()
        shell = self._shell
        SupportInboxController(
            self._context,
            self._current_employee,
            poller=poller,
            poll_interval_ms=interval_ms,
            on_counts_changed=(
                (lambda: self._refresh_support_badges(shell)) if shell is not None else None
            ),
        ).attach(screen)

    def _build_telegram_poller(self) -> tuple[object, int]:
        """Telegram sorğu obyektini və intervalını qurur.

        Uğursuzluq EKRANI DAYANDIRMIR: bot qurulmayıbsa və ya ayarlar
        oxunmursa bölmə tam işləyir, sadəcə xarici cavab gəlmir — Telegram
        bu bölmənin ƏLAVƏSİdir, şərti deyil.
        """
        from src.application.root_limits import limit_int  # noqa: PLC0415
        from src.application.use_cases.telegram_config import (  # noqa: PLC0415
            TelegramSettings,
        )
        from src.domain.policies import SystemLimitKey  # noqa: PLC0415
        from src.infrastructure.notifications.telegram import (  # noqa: PLC0415
            TelegramReplyPoller,
        )

        context = self._context
        actor = self._current_employee
        if context is None or actor is None:  # pragma: no cover - çağırış yeri qoruyur
            return None, 0
        try:
            with context.session(user_id=actor.id) as session:
                settings = session.telegram_config.settings_for_gateway(session.tenant_id)
                seconds = limit_int(
                    session.uow.repository("limits"),
                    session.tenant_id,
                    SystemLimitKey.TELEGRAM_POLL_INTERVAL_SECONDS,
                )
        except Exception:
            _log.exception("TELEGRAM_POLLER_SETUP_FAILED")
            return None, 0
        if settings is None:
            return None, 0

        def provider() -> TelegramSettings | None:
            """Ayarlar HƏR sorğuda yenidən oxunur — Root botu dəyişə bilər."""
            try:
                with context.session(user_id=actor.id) as inner:
                    return inner.telegram_config.settings_for_gateway(inner.tenant_id)
            except Exception:
                _log.exception("TELEGRAM_SETTINGS_READ_FAILED")
                return None

        return TelegramReplyPoller(settings_provider=provider), max(1, seconds) * 1000

    def _attach_face_enrollment(self, screen: QWidget) -> None:
        """«Üz Qeydiyyatı» ekranını `FaceEnrollmentUseCase`-ə bağlayır (bənd 1, 2).

        Ekran menyuda `can_manage_employees` ilə qapılıdır, lakin FAKTİKİ qapı
        use case-dədir (`assert_may_enroll` — özünə-qeydiyyat da bloklanır):
        menyunun görünməsi əməliyyat icazəsi DEYİL (bax `menu.py` başlığı).
        """
        from src.presentation.controllers.face_control import (  # noqa: PLC0415
            FaceEnrollmentController,
        )
        from src.presentation.screens.face_control import (  # noqa: PLC0415
            FaceEnrollmentScreen,
        )

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, FaceEnrollmentScreen):  # pragma: no cover - tip qoruyucusu
            return
        FaceEnrollmentController(self._context, self._current_employee).attach(screen)

    def _attach_face_exemptions(self, screen: QWidget) -> None:
        """«Üz Təsdiqi İstisnaları» ekranını use case-ə bağlayır (bənd 14).

        Qapı `can_manage_face_exemptions`-dir (hardlock 2, YALNIZ Root/CEO) və
        o, `FaceControlExemptionUseCase._require_permission`-dadır — OXU da,
        QƏRAR da eyni flag-in arxasındadır.
        """
        from src.presentation.controllers.face_control import (  # noqa: PLC0415
            FaceExemptionController,
        )
        from src.presentation.screens.face_control import (  # noqa: PLC0415
            FaceExemptionScreen,
        )

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, FaceExemptionScreen):  # pragma: no cover - tip qoruyucusu
            return
        FaceExemptionController(self._context, self._current_employee).attach(screen)

    def _attach_attrition_risk(self, screen: QWidget) -> None:
        """ "İşdən Çıxma Riski" ekranını use case-ə bağlayır (#21, Faza 9)."""
        from src.presentation.controllers.attrition_risk import (  # noqa: PLC0415
            AttritionRiskController,
        )
        from src.presentation.screens.attrition_risk import (  # noqa: PLC0415
            AttritionRiskScreen,
        )

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, AttritionRiskScreen):  # pragma: no cover - tip qoruyucusu
            return
        AttritionRiskController(self._context, self._current_employee).attach(screen)

    def _attach_sync_conflicts(self, screen: QWidget) -> None:
        """«Sinxronizasiya Konfliktləri» ekranını use case-ə bağlayır (G-1).

        Ekran menyuda `can_view_employee_reports` ilə qapılıdır, lakin FAKTİKİ
        qapı use case-dədir (`SyncConflictUseCase._require`) — menyunun
        görünməsi əməliyyat icazəsi DEYİL (bax `menu.py` başlığı).
        """
        from src.presentation.controllers.sync_conflicts import (  # noqa: PLC0415
            SyncConflictController,
        )
        from src.presentation.screens.sync_conflicts import (  # noqa: PLC0415
            SyncConflictScreen,
        )

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, SyncConflictScreen):  # pragma: no cover - tip qoruyucusu
            return
        SyncConflictController(self._context, self._current_employee).attach(screen)

    def _attach_devices(self, screen: QWidget) -> None:
        """«Cihazlar» ekranını `DeviceRegistryUseCase`-ə bağlayır (DEVICE-1).

        Menyu `can_manage_devices` ilə qapılıdır, lakin FAKTİKİ qapı use
        case-dədir (`DeviceRegistryUseCase._require`) — menyunun görünməsi
        əməliyyat icazəsi DEYİL (bax `menu.py` başlığı).
        """
        from src.presentation.controllers.devices import (  # noqa: PLC0415
            DeviceAdminController,
        )
        from src.presentation.screens.devices import DeviceAdminScreen  # noqa: PLC0415

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, DeviceAdminScreen):  # pragma: no cover - tip qoruyucusu
            return
        DeviceAdminController(self._context, self._current_employee).attach(screen)

    def _attach_field_reports(self, key: str, screen: QWidget) -> None:
        """Sahə hesabatı formasını `FieldReportUseCase`-ə bağlayır (#26+#27).

        Ekran açarı şablon AİLƏSİNİ seçir (`SCREEN_TEMPLATE_FAMILY`) — şablon
        KODUNU yox. Naməlum açar bağlanmır: yeni ekran əlavə edən adam ailəni
        də qeyd etməlidir, əks halda forma sükutla BOŞ qalardı.
        """
        from src.presentation.controllers.field_reports import (  # noqa: PLC0415
            SCREEN_TEMPLATE_FAMILY,
            FieldReportsController,
        )
        from src.presentation.screens.field_reports import (  # noqa: PLC0415
            FieldReportScreen,
        )

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, FieldReportScreen):  # pragma: no cover - tip qoruyucusu
            return
        family = SCREEN_TEMPLATE_FAMILY.get(key)
        if family is None:  # pragma: no cover - müdafiə xətti
            _log.warning("FIELD_REPORT_SCREEN_FAMILY_MISSING", extra={"screen": key})
            return
        FieldReportsController(
            self._context, self._current_employee, requires_checklist=family
        ).attach(screen)

    def _attach_dashboard_builder(self, screen: QWidget) -> None:
        """Dashboard qurucusunu `DashboardLayoutUseCase`-ə bağlayır (bölmə 6)."""
        from src.presentation.controllers.dashboard_builder import (  # noqa: PLC0415
            DashboardBuilderController,
        )
        from src.presentation.screens.group_i import (  # noqa: PLC0415
            DashboardBuilderScreen,
        )

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, DashboardBuilderScreen):  # pragma: no cover - tip qoruyucusu
            return
        DashboardBuilderController(self._context, self._current_employee).attach(screen)

    def _attach_dashboard_benchmark(self, screen: QWidget) -> None:
        """Reytinq Cədvəlinin dropdown/drill-down siqnallarını bağlayır (#24, Faza 9A).

        AYRI KONTROLLER YARADILMADI: bu widget-lər YALNIZ OXUYUR (bax
        `application.use_cases.multi_store_benchmark` modul başlığı), ona
        görə mövcud `ScreenDataBinder`-in iki metodu (`refresh_dashboard_
        benchmark`, `populate_daily_roster_for_store`) kifayət edir.
        """
        from src.presentation.screens.group_c import DashboardScreen  # noqa: PLC0415

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, DashboardScreen):  # pragma: no cover - tip qoruyucusu
            return
        if self._binder is None:  # pragma: no cover - `show_admin`-lə bərabər qurulur
            return
        screen.ranking_metric_changed.connect(
            lambda metric_key: self._on_ranking_metric_changed(screen, metric_key)
        )
        screen.ranking_row_selected.connect(self._on_ranking_row_selected)

    def _on_ranking_metric_changed(self, screen: QWidget, metric_key: str) -> None:
        """Reytinq dropdown-u dəyişdi — dörd bölmə YENİ metriklə yenilənir."""
        if self._binder is None:  # pragma: no cover - invariant
            return
        self._binder.refresh_dashboard_benchmark(screen, metric_key=metric_key)

    def _on_ranking_row_selected(self, store_id_text: str) -> None:
        """DRILL-DOWN: reytinq sətrinə klik → MÖVCUD "Gündəlik Tabel" ekranı.

        ──────────────────────────────────────────────────────────────────
        NİYƏ QƏRARIN ÖZÜ `perform_ranking_drill_down`-DADIR
        ──────────────────────────────────────────────────────────────────
        `AdminShell.show_screen(key)` YALNIZ açardan asılıdır, parametr
        daşımır (mövcud imza — YENİ naviqasiya qatı YARADILMADI). Reytinq
        cədvəlindəki mağaza isə Root/CEO/Admin/HR_Admin-in ÖZ mağazası
        olmaya bilər (`daily_roster`-in canlı yolu defolt aktorun ÖZ
        `store_id`-sinə bağlıdır, bax `screen_data._daily_roster`), ona görə
        keçiddən SONRA `AdminShell.screen_for()` ilə artıq açılmış instansiya
        götürülür və `populate_daily_roster_for_store` ONU XÜSUSİ olaraq
        kliklənən mağaza ilə doldurur. Bu ÜÇ addım `screen_data.
        perform_ranking_drill_down`-da SAF funksiya kimi yaşayır ki,
        `QApplication` olmadan test oluna bilsin — burada YALNIZ HAZIR
        collaborator-lar ötürülür.
        """
        if self._shell is None or self._binder is None:
            return
        from src.presentation.controllers.screen_data import (  # noqa: PLC0415
            perform_ranking_drill_down,
        )

        succeeded = perform_ranking_drill_down(
            store_id_text,
            show_screen=self._shell.show_screen,
            screen_for=self._shell.screen_for,
            populate=self._binder.populate_daily_roster_for_store,
        )
        if not succeeded:
            _log.warning("BENCHMARK_DRILL_DOWN_FAILED", extra={"value": store_id_text})

    def _attach_sales_review(self, screen: QWidget) -> None:
        """«Şübhəli Satışlar» növbəsini `SalesReviewQueueUseCase`-ə bağlayır."""
        from src.presentation.controllers.sales_review import (  # noqa: PLC0415
            SalesReviewController,
        )
        from src.presentation.screens.group_f import UnassignedSalesScreen  # noqa: PLC0415

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, UnassignedSalesScreen):  # pragma: no cover - tip qoruyucusu
            return
        controller = self._sales_review or SalesReviewController(
            self._context, self._current_employee
        )
        controller.attach(screen)

    def _attach_permission_matrix(self, screen: QWidget) -> None:
        """İcazə Matrisini `PositionManagementUseCase`-ə bağlayır (bölmə 3).

        Bütün qoruyucu qaydalar (Strict Hierarchy, Self-Escalation, hardlock,
        anti-fraud) use case-in İÇİNDƏDİR — kontroller onları təkrarlamır,
        yalnız istisnanı istifadəçiyə izah edir.
        """
        from src.presentation.controllers.permission_matrix import (  # noqa: PLC0415
            PermissionMatrixController,
        )
        from src.presentation.screens.group_c import PermissionMatrixScreen  # noqa: PLC0415

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, PermissionMatrixScreen):  # pragma: no cover - tip qoruyucusu
            return
        PermissionMatrixController(self._context, self._current_employee).attach(screen)

    def _attach_users_pos_threshold(self, screen: QWidget) -> None:
        """`UsersScreen`-in "POS Səlahiyyəti" VƏ "Sənədlər" bəndlərini bağlayır.

        #7 (kompasos11.md Faza 4) və #17 (Faza 7) — HƏR İKİSİ YALNIZ
        sənədləşdirmədir. Bütün qoruyucular (icazə flag-i, Self-Escalation,
        Strict Hierarchy) use case-lərin İÇİNDƏDİR — bax `controllers/
        pos_threshold.py` və `controllers/employee_documents.py` başlıqları.

        İKİ KONTROLLER EYNİ `action_requested` SİQNALINA bağlanır — hər biri
        ÖZ açarını filtrləyir (`POS_THRESHOLD_ACTION_KEY`/
        `EMPLOYEE_DOCUMENT_ACTION_KEY`), yəni bir-birinə mane olmurlar. Metod
        adı DƏYİŞMİR (`_attach_write_controller` cədvəlində `UsersScreen`
        üçün TƏK giriş nöqtəsidir — ilk uyğunluqdan sonra dayanır).
        """
        from src.presentation.controllers.employee_documents import (  # noqa: PLC0415
            UsersEmployeeDocumentController,
        )
        from src.presentation.controllers.pos_threshold import (  # noqa: PLC0415
            UsersPOSThresholdController,
        )
        from src.presentation.screens.group_c import UsersScreen  # noqa: PLC0415

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, UsersScreen):  # pragma: no cover - tip qoruyucusu
            return
        UsersPOSThresholdController(self._context, self._current_employee).attach(screen)
        UsersEmployeeDocumentController(self._context, self._current_employee).attach(screen)

    def _attach_open_shift_market(self, screen: QWidget) -> None:
        """Növbə Planlama ekranının yazı/kataloq kontrollerlərini bağlayır.

        Matrisin İLK doldurulması toxunulmur: o, `ScreenDataBinder.
        _shift_planning`-dən gəlməyə davam edir. Burada ÜÇ kontroller
        qoşulur — hibrid bağlama, `users` ekranı ilə eyni naxış:

          * `ShiftMatrixOpenShiftController` — "Açıq Növbə Bazarı" kartı (#16,
            oxu + yazı).
          * `ShiftMatrixWorkModeController` — toolbar-dakı İş Rejimi seçicisi
            (Faza 7, YALNIZ oxu). Ayrı sinif olmasının səbəbi öz modulunun
            başlığındadır.
          * `ShiftWindowController` — «‹ / ›» ay oxları; matrisi sürüşdürülmüş
            pəncərə ilə YENİDƏN doldurur. Seçicidən ayrı saxlanılır, çünki
            seçicinin "matrisə toxunmur" zəmanəti mənbə mətnindən yoxlanılır.

        METOD ADI DƏYİŞMİR: o, ekran açarı ↔ bağlayıcı xəritəsində qeydə
        alınıb (`tests/unit/test_screen_binding_coverage.py`) və adı
        dəyişdirmək qapını sındırardı — halbuki dəyişən yalnız MƏZMUNdur.
        """
        from src.presentation.controllers.open_shift import (  # noqa: PLC0415
            ShiftMatrixOpenShiftController,
        )
        from src.presentation.controllers.shift_matrix import (  # noqa: PLC0415
            ShiftMatrixWorkModeController,
        )
        from src.presentation.controllers.shift_window import (  # noqa: PLC0415
            ShiftWindowController,
        )
        from src.presentation.screens.group_c import ShiftPlanningScreen  # noqa: PLC0415

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, ShiftPlanningScreen):  # pragma: no cover - tip qoruyucusu
            return
        ShiftMatrixOpenShiftController(self._context, self._current_employee).attach(screen)
        ShiftMatrixWorkModeController(self._context, self._current_employee).attach(screen)
        ShiftWindowController(self._context, self._current_employee).attach(screen)

    def _attach_erp_servers(self, screen: QWidget) -> None:
        """1C server panelini `ErpConnectionWizardUseCase`-ə bağlayır (bölmə 7).

        Kredensiallar nə ekrana, nə jurnala düşür (SEC-013) — audit görünüşü
        domendəki `auditable()`-dədir (bax `controllers/erp_servers.py`).
        """
        from src.presentation.controllers.erp_servers import (  # noqa: PLC0415
            ErpServersController,
        )
        from src.presentation.screens.group_d import ErpServersScreen  # noqa: PLC0415

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, ErpServersScreen):  # pragma: no cover - tip qoruyucusu
            return
        ErpServersController(self._context, self._current_employee).attach(screen)

    def _attach_backups(self, screen: QWidget) -> None:
        """Backup ekranını `BackupAccessUseCase`-ə bağlayır (bölmə 7).

        Bərpa İKİ təsdiq qapısından keçir və heç biri yan keçilmir (bax
        `controllers/backup_admin.py` başlığı).
        """
        from src.presentation.controllers.backup_admin import (  # noqa: PLC0415
            BackupAdminController,
        )
        from src.presentation.screens.group_d import BackupScreen  # noqa: PLC0415

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, BackupScreen):  # pragma: no cover - tip qoruyucusu
            return
        BackupAdminController(self._context, self._current_employee).attach(screen)

    def _attach_infrastructure(self, screen: QWidget) -> None:
        """Baza keçidi panelini `DatabaseSwitchUseCase`-ə bağlayır (bölmə 2)."""
        from src.presentation.controllers.infrastructure import (  # noqa: PLC0415
            InfrastructureController,
        )
        from src.presentation.screens.group_i import (  # noqa: PLC0415
            InfrastructureScreen,
        )

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(screen, InfrastructureScreen):  # pragma: no cover - tip qoruyucusu
            return
        InfrastructureController(self._context, self._current_employee).attach(screen)

    def _attach_health(self, screen: QWidget) -> None:
        """«Yenidən Yoxla» düyməsini canlı oxumaya bağlayır (bölmə 6).

        Sistem Sağlamlığı əsasən OXU ekranıdır və məzmunu `screen_data._health`
        doldurur; burada yalnız yenidən-oxuma tetikləyicisi qoşulur. Ayrıca
        kontroller yaratmaq bir sətirlik yenidən-oxuma üçün lazımsız qat
        olardı (eyni qərar «Yardım Mərkəzi»ndə də verilib).
        """
        from src.presentation.screens.group_d import HealthScreen  # noqa: PLC0415

        if not isinstance(screen, HealthScreen):  # pragma: no cover - tip qoruyucusu
            return

        # G-1: «N sinxronizasiya konflikti həll gözləyir» xəbərdarlığı artıq
        # KOR DALAN deyil. Keçid HƏR İKİ rejimdə bağlanır (maketdə də ekran
        # açılmalıdır) və `AdminShell.show_screen` icazəni ÖZÜ yoxlayır —
        # yəni birbaşa keçid (deep link) qapısı da yerindədir.
        screen.conflicts_requested.connect(self._on_conflicts_requested)

        if self._preview or self._binder is None:
            return
        binder = self._binder
        screen.recheck_requested.connect(lambda: binder.populate("health", screen))

    def _on_conflicts_requested(self) -> None:
        """Sağlamlıq kartındakı keçid — MÖVCUD naviqasiya API-si ilə."""
        if self._shell is None:  # pragma: no cover - örtüklə bərabər qurulur
            return
        self._shell.show_screen("sync_conflicts")

    def _attach_help_center(self, screen: QWidget) -> None:
        """«Dəstəyə yaz» düyməsini MÖVCUD üzən dəstək panelinə bağlayır.

        Yeni bir yazı yolu AÇILMIR: bilet yaratma axını onsuz da
        `SupportChatWidget`-dədir və o, `can_contact_support` yoxlanışından
        keçib qurulur (`_install_overlays`). Düymə həmin paneli açır — iki
        ayrı göndərmə yolu olsaydı, biri düzəldiləndə digəri arxada qalardı.

        Panel qurulmayıbsa (icazə yoxdur) düymə də EKRANDA YOXDUR — ona görə
        burada `None` halı sükutla keçilir, bu, əlçatmaz vəziyyətdir.
        """
        from src.presentation.screens.group_h import HelpCenterScreen  # noqa: PLC0415

        if not isinstance(screen, HelpCenterScreen):  # pragma: no cover - tip qoruyucusu
            return
        screen.support_requested.connect(self._open_support_panel)

    def _open_support_panel(self) -> None:
        support = self._support
        if support is None or not hasattr(support, "open_panel"):
            return
        support.open_panel()
        support.raise_()

    def _attach_root_control(self, screen: QWidget) -> None:
        """ROOT panelini `RootControlUseCase`-ə bağlayır (bölmə 3, bənd 1-4).

        Önizləmə rejimində kontekst yoxdur — maket məzmunu qalır və heç bir
        yazı yolu qoşulmur (`preview_screens` onsuz da nümunə dəyər verib).
        """
        if self._preview or self._context is None or self._current_employee is None:
            return
        from src.presentation.controllers.root_control import (  # noqa: PLC0415
            RootControlController,
        )
        from src.presentation.screens.group_d import RootControlScreen  # noqa: PLC0415

        if not isinstance(screen, RootControlScreen):  # pragma: no cover - tip qoruyucusu
            return
        RootControlController(self._context, self._current_employee).attach(screen)

    def _apply_stored_theme(self, employee: Employee) -> None:
        """Login-də saxlanmış tema tətbiq olunur (bölmə 9)."""
        if self._context is None:
            return
        try:
            with self._context.session() as session:
                stored = session.preferences.theme_for(employee.id)
        except Exception:
            _log.exception("THEME_LOAD_FAILED")
            return
        self.set_theme(ThemeMode(str(stored).lower()))

    def _register_screens(self, shell: AdminShell) -> None:
        """Bütün modul ekranlarını `açar → fabrika` şəklində bağlayır.

        Ekranlar burada QURULMUR — yalnız necə qurulacağı yazılır. Faktiki
        qurulma ilk açılışda baş verir (bax `AdminShell.show_screen`).
        """
        from src.domain.value_objects.support import SupportChannel  # noqa: PLC0415
        from src.presentation.screens import (  # noqa: PLC0415
            group_b,
            group_c,
            group_d,
            group_f,
            group_g,
            group_h,
            group_i,
        )
        from src.presentation.screens.announcements import (  # noqa: PLC0415
            AnnouncementsScreen,
        )
        from src.presentation.screens.annual_leave import (  # noqa: PLC0415
            AnnualLeaveInboxScreen,
        )
        from src.presentation.screens.attrition_risk import (  # noqa: PLC0415
            AttritionRiskScreen,
        )
        from src.presentation.screens.bulk_operations import (  # noqa: PLC0415
            BulkOperationsScreen,
        )
        from src.presentation.screens.devices import DeviceAdminScreen  # noqa: PLC0415
        from src.presentation.screens.face_control import (  # noqa: PLC0415
            FaceEnrollmentScreen,
            FaceExemptionScreen,
        )
        from src.presentation.screens.field_reports import (  # noqa: PLC0415
            FieldReportScreen,
        )
        from src.presentation.screens.fine_review import (  # noqa: PLC0415
            MonthlyFineReviewScreen,
        )
        from src.presentation.screens.performance_review import (  # noqa: PLC0415
            PerformanceReviewScreen,
        )
        from src.presentation.screens.support_inbox import (  # noqa: PLC0415
            SupportInboxScreen,
        )
        from src.presentation.screens.sync_conflicts import (  # noqa: PLC0415
            SyncConflictScreen,
        )

        theme = self._theme

        def make(key: str, factory: Callable[[], QWidget]) -> Callable[[], QWidget]:
            """Fabrikanı önizləmə doldurucusu ilə bükür."""

            def build() -> QWidget:
                screen = factory()
                if self._preview:
                    from src.presentation import preview_screens  # noqa: PLC0415

                    preview_screens.populate(key, screen)
                elif self._binder is not None:
                    # İstehsalat: eyni imza, canlı məlumat (bax `screen_data`).
                    self._binder.populate(key, screen)
                self._attach_write_controller(key, screen)
                return screen

            return build

        # Bəzi ekranlar açılış siyahılarını KONSTRUKTORDA gözləyir (combo-box
        # dəyərləri), ona görə onlar `populate()`-dan əvvəl lazımdır.
        names: list[str] = []
        stores: list[str] = []
        fine_types: list[str] = []
        queue_stores: list[str] = []
        #: «Şübhəli Satışlar» AYRI siyahı işlədir: cərimə siyahısı operatorun
        #: ÖZ filialları ilə məhduddur, satış uyğunlaşması isə şirkət
        #: miqyasındadır (bax `SalesReviewController.employee_names`).
        sales_names: list[str] = []
        #: Mağaza süzgəcinin görünmə həddi (audit G-6) — ROOT parametridir.
        queue_store_threshold = self._queue_store_filter_threshold()
        if self._preview:
            from src.presentation import preview_data  # noqa: PLC0415

            names = list(preview_data.EMPLOYEE_NAMES)
            stores = list(preview_data.STORES)
            fine_types = list(preview_data.FINE_TYPES)
            # MAKETDƏ DÖRD MAĞAZA (əvvəl iki idi): süzgəc yalnız hədddən ÇOX
            # təyinatda qurulur, yəni iki mağaza ilə maket onu heç vaxt
            # göstərməzdi və dizayn nəzərdən keçirilərkən görünməz qalardı.
            queue_stores = list(preview_data.STORES[:4])
            sales_names = names
        else:
            if self._fine_entry is not None:
                # Canlı rejim: dropdown-lar operatorun ÖZ filiallarından qurulur
                # (bax `FineEntryController.options` — fail-safe boş siyahı).
                fine_types, stores, names = self._fine_entry.options()
                queue_stores = stores
            if self._sales_review is not None:
                sales_names = self._sales_review.employee_names()

        factories: dict[str, Callable[[], QWidget]] = {
            "dashboard": lambda: group_c.DashboardScreen(theme),
            "live_queue": lambda: group_b.OperatorQueueScreen(
                theme,
                assigned_stores=queue_stores,
                store_filter_threshold=queue_store_threshold,
            ),
            "daily_roster": lambda: group_c.DailyRosterScreen(theme),
            "shift_planning": lambda: group_c.ShiftPlanningScreen(theme),
            "shift_swaps": lambda: group_c.ShiftSwapScreen(theme),
            "fines": lambda: group_b.FineEntryScreen(
                theme, fine_types=fine_types, stores=stores, employees=names
            ),
            # Aylıq Cərimə İcmalı (miqrasiya 003) — `FineStatus.PUBLISHED`-ə
            # YEGANƏ yol. Ekran öz kontrollerinə bağlıdır (bax
            # `_attach_write_controller` cədvəli).
            "fine_review": lambda: MonthlyFineReviewScreen(theme),
            "fine_appeals": lambda: group_f.FineAppealInboxScreen(theme),
            "tasks": lambda: group_f.TasksScreen(theme),
            "sales_points": lambda: group_f.SalesPointsScreen(theme),
            "unassigned_sales": lambda: group_f.UnassignedSalesScreen(theme, employees=sales_names),
            "users": lambda: group_c.UsersScreen(theme),
            "bulk_operations": lambda: BulkOperationsScreen(theme),
            "permissions": lambda: group_c.PermissionMatrixScreen(theme),
            "erp_servers": lambda: group_d.ErpServersScreen(theme),
            "backups": lambda: group_d.BackupScreen(theme),
            "health": lambda: group_d.HealthScreen(theme),
            "audit": lambda: group_d.AuditScreen(
                theme,
                modules=["Davamiyyət", "Cərimələr", "İcazələr", "Tabel", "ROOT"],
            ),
            "drive_connection": lambda: group_d.DriveConnectionScreen(theme),
            "root_control": lambda: group_d.RootControlScreen(theme),
            "reports": lambda: group_h.ReportExportScreen(theme),
            "work_modes": lambda: group_h.work_modes_screen(theme),
            "fine_types": lambda: group_h.fine_types_screen(theme),
            "leave_types": lambda: group_h.leave_types_screen(theme),
            # «Dəstəyə yaz» düyməsi icazəsi olmayan istifadəçidə QURULMUR
            # (bölmə 8: "bu ikon UI-dan ümumiyyətlə render olunmur") — eyni
            # qapı üzən dəstək ikonuna da tətbiq olunur.
            "help": lambda: group_h.HelpCenterScreen(
                theme, may_contact_support=self._may_contact_support()
            ),
            "infrastructure": lambda: group_i.InfrastructureScreen(theme),
            "plugins": lambda: group_i.PluginScreen(theme),
            "dashboard_builder": lambda: group_i.DashboardBuilderScreen(theme),
            "exceptions": lambda: group_i.ExceptionsScreen(theme),
            # #26+#27 — EYNİ sinif, İKİ açar (bax `_attach_field_reports`).
            "store_audit": lambda: FieldReportScreen(theme),
            "incident_report": lambda: FieldReportScreen(theme),
            "announcements": lambda: AnnouncementsScreen(theme),
            "performance_reviews": lambda: PerformanceReviewScreen(theme),
            "attrition_risk": lambda: AttritionRiskScreen(theme),
            # G-1 (bölmə 5) — «Sistem Sağlamlığı» xəbərdarlığının GEDƏCƏYİ yer.
            "sync_conflicts": lambda: SyncConflictScreen(theme),
            # DEVICE-1: hansı PC hansı filiala aiddir. Ekran HƏM oxuyur,
            # HƏM yazır — ona görə öz kontrolleri var (`_attach_devices`).
            "devices": lambda: DeviceAdminScreen(theme),
            "annual_leave": lambda: AnnualLeaveInboxScreen(theme),
            # CHAT-1: İKİ AÇAR, BİR SİNİF — fərq yalnız `channel` arqumentidir
            # (bax `screens/support_inbox.py` başlığı). `_attach_write_
            # controller` ikisini `isinstance` ilə ayırd edə bilmir, ona görə
            # kontroller kanalı EKRANDAN oxuyur (`screen.channel`), açardan yox.
            "internal_requests": lambda: SupportInboxScreen(theme, channel=SupportChannel.INTERNAL),
            "technical_support": lambda: SupportInboxScreen(
                theme, channel=SupportChannel.TECHNICAL
            ),
            # Face Control (facecontrol.md Faza 4) — hər ikisi ÖZ kontrollerinə
            # bağlıdır (bax `_attach_write_controller` cədvəli).
            "face_enrollment": lambda: FaceEnrollmentScreen(theme),
            "face_exemptions": lambda: FaceExemptionScreen(theme),
            "settings": lambda: group_d.SettingsScreen(theme),
            "profile": lambda: group_g.ProfileScreen(
                theme,
                full_name=shell.header().user_name() or "İstifadəçi",
                role_name="Admin",
                store_name="Baş ofis",
                member_since="2024-cü ildən",
            ),
        }

        #: Başlıqdakı kontekst mətni.
        #:
        #: ────────────────────────────────────────────────────────────────
        #: UYDURMA RƏQƏM YOXDUR — SAY VƏ TARİX CANLI MƏLUMATDANDIR
        #: ────────────────────────────────────────────────────────────────
        #: Əvvəl burada maketdən gələn sabitlər vardı: «21 filial»,
        #: «235 nəfər», «12 Avqust 2026», «Bellona 28 May». İstifadəçi onları
        #: real sayılar sanırdı — bir mağazası olan quraşdırmada belə ekran
        #: «21 filial» yazırdı.
        #:
        #: İndi rəqəm/tarix daşıyan mətnlər BOŞ başlayır və girişdən sonra
        #: `_refresh_context_subtitles()` onları bazadan doldurur. Boş
        #: başlamaq QƏSDLİDİR: doldurula bilməyəndə heç nə göstərilmir —
        #: yanlış rəqəm göstərməkdənsə boşluq dürüstdür.
        subtitles = {
            "dashboard": "",
            "live_queue": "Canlı · 2 san əvvəl yeniləndi",
            "daily_roster": "",
            "fines": "",
            "fine_review": "Ayın əvvəli · göndərmə geri qaytarıla bilmir",
            "users": "",
            "bulk_operations": "CSV işçi idxalı · mağaza şablonu",
            "reports": "İki ayrı fayl",
            "work_modes": "Növbə şablonları",
            "fine_types": "Standart məbləğlər · anti-fraud",
            "leave_types": "Fasilə kateqoriyaları",
            "infrastructure": "Baza keçidi · texniki fasilə",
            "plugins": "Sandbox-da işləyən genişləndirmələr",
            "exceptions": "Davranış anomaliyaları · avtomatik aşkarlanır",
            "store_audit": "Checklist üzrə yoxlama · uğursuz bənd tapşırıq yaradır",
            "incident_report": "Baş vermiş hadisə · kateqoriyaya görə marşrutlanır",
            "announcements": "Bütün mağazalar · bir-tərəfli yayım",
            "performance_reviews": "Dövri qiymətləndirmə · KPI + qeyd",
            "attrition_risk": "Gecəlik hesablanır · yalnız məsləhət xarakterlidir",
            "sync_conflicts": "Offline rejimin izi · hər iki versiya saxlanılır",
            "devices": "Təsdiqlənmiş cihaz lisenziya yeri tutur",
            "annual_leave": "İllik haqq · gündaxili icazədən AYRI mexanizm",
            "internal_requests": "Şirkətin öz növbəsi · Telegram-a GETMİR",
            "technical_support": "Hazırlayıcıya gedir · Telegram sinxronlaşdırılır",
            "face_enrollment": "Nəzarətli proses · foto saxlanmır, yalnız riyazi təmsil",
            "face_exemptions": "PIN-only istisnası · məcburi ikinci təsdiqlə əvəzlənir",
        }

        for key, factory in factories.items():
            shell.register_screen(key, make(key, factory), subtitle=subtitles.get(key, ""))

        # PLUGIN SƏHİFƏLƏRİ SONDA (audit G-3): sabit cədvəl ƏVVƏL qeydiyyatdan
        # keçir, yəni plugin heç bir mövcud açarı üstələyə bilmir —
        # `AdminShell.register_screen` sadəcə lüğətə yazır və sonuncu qalib
        # gələrdi. Ad məkanı (`plugin:`) onsuz da toqquşmanı qeyri-mümkün
        # edir; sıra İKİNCİ qatdır (bax `plugin_surface.py` qapı 4).
        for page in self._plugin_pages:
            if page.key in factories:  # pragma: no cover - ad məkanı bunu qapayır
                continue
            shell.register_screen(
                page.key,
                self._plugin_page_factory(page),
                subtitle=f"Plugin · {page.publisher}",
            )

    # ------------------------------ üst qatlar -------------------------------- #

    def _install_overlays(self, shell: AdminShell) -> None:
        """Dəstək widget-i və bildiriş panelini örtüyün üstünə qoyur.

        DƏSTƏK İKONU İCAZƏYƏ BAĞLIDIR (bölmə 8, sətir 279): «Digər rollar üçün
        bu ikon UI-dan ümumiyyətlə render olunmur». Əvvəl widget ŞƏRTSİZ
        qurulurdu — `can_contact_support` yalnız backend-də (`support_chat.py`)
        yoxlanılırdı, yəni `Satıcı` da hazırlayıcıya yazma imkanını GÖRÜRDÜ.
        Bu, "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" prinsipinin birbaşa pozulmasıdır.

        Widget `setVisible(False)` ilə gizlədilmir — ÜMUMİYYƏTLƏ yaradılmır.
        """
        from src.presentation.screens.group_e import SupportChatWidget  # noqa: PLC0415
        from src.presentation.screens.group_g import NotificationPanel  # noqa: PLC0415

        support = (
            SupportChatWidget(self._theme, parent=shell) if self._may_contact_support() else None
        )
        panel = NotificationPanel(self._theme, parent=shell)
        panel.setVisible(False)

        if self._preview:
            from src.presentation import preview_screens  # noqa: PLC0415

            if support is not None:
                preview_screens.populate("support", support)
            preview_screens.populate("notifications", panel)
            shell.header().set_unread(preview_screens.unread_notification_count())

        self._support = support
        self._notifications = panel

        # Dəstək panelinin CANLI yolu. Əvvəl `message_sent` heç nəyə bağlı
        # DEYİLDİ: istifadəçi mesaj yazır, o, ekranda görünür və heç yerə
        # getmirdi — kəsilmiş yol. Bax `controllers/support_chat.py` başlığı.
        if support is not None:
            self._attach_support_chat(support)

        shell.header().bell_clicked.connect(self._toggle_notifications)
        # SIRA VACİBDİR: canlı bağlama zəng siqnalına `_toggle_notifications`-DAN
        # SONRA qoşulur. Qt birbaşa slotları qoşulma sırası ilə çağırır, yəni
        # kontroller işə düşəndə panelin görünürlüyü ARTIQ dəyişib və o, sorğunu
        # yalnız panel AÇILANDA göndərir. Əks sıra hər bağlanışda da bir sorğu
        # demək olardı — panel isə gün ərzində onlarla dəfə açılıb-bağlanır.
        self._attach_notifications(shell, panel)

        # Örtük ölçüsü dəyişəndə üzən elementlər yenidən yerləşdirilir.
        original_resize = shell.resizeEvent

        def on_resize(event: QResizeEvent) -> None:
            original_resize(event)
            self._reposition_overlays(shell)

        shell.resizeEvent = on_resize  # type: ignore[method-assign]
        QTimer.singleShot(0, lambda: self._reposition_overlays(shell))

    def _attach_support_chat(self, widget: QWidget) -> None:
        """Üzən dəstək panelini `SupportChatUseCase`-ə bağlayır (bölmə 8).

        Önizləmə yolu TOXUNULMAZ qalır: maketdə söhbət `preview_screens`
        tərəfindən doldurulur və heç bir baza sorğusu getmir.
        """
        from src.presentation.controllers.support_chat import (  # noqa: PLC0415
            SupportChatController,
        )
        from src.presentation.screens.group_e import SupportChatWidget  # noqa: PLC0415

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(widget, SupportChatWidget):  # pragma: no cover - tip qoruyucusu
            return
        SupportChatController(self._context, self._current_employee).attach(widget)

    def _attach_notifications(self, shell: AdminShell, panel: QWidget) -> None:
        """Bildiriş panelinin CANLI yazı/oxu yolu (bölmə 7).

        Əvvəl panel YALNIZ önizləmə rejimində doldurulurdu: istehsalatda
        `PostgresNotifier` `notifications` sətrini yazırdı, lakin heç kim onu
        OXUMURDU — nə panel, nə header nişanı. Nəticədə bölmə 7-nin in-app
        kanalı tamamilə ölü idi və e-poçt fallback-ı ilə əvəzlənmişdi.

        Önizləmə yolu TOXUNULMAZ qalır (`preview_screens.populate`) və hər iki
        yol EYNİ açarları işlədir — maket/canlı ad məkanı ayrılığı layihədə
        artıq bir dəfə gizli qüsur yaradıb (bax `shell/menu.py` başlığı).
        """
        from src.presentation.controllers.notifications import (  # noqa: PLC0415
            NotificationsController,
        )
        from src.presentation.screens.group_g import NotificationPanel  # noqa: PLC0415

        if self._preview or self._context is None or self._current_employee is None:
            return
        if not isinstance(panel, NotificationPanel):  # pragma: no cover - tip qoruyucusu
            return
        NotificationsController(self._context, self._current_employee).attach(panel, shell.header())

    def _reposition_overlays(self, shell: AdminShell) -> None:
        if isinstance(self._support, QWidget) and hasattr(self._support, "reposition"):
            self._support.reposition(shell.width(), shell.height())
            self._support.raise_()
        if self._notifications is not None:
            from src.presentation.widgets import metrics  # noqa: PLC0415

            self._notifications.move(
                shell.width() - self._notifications.width() - 26,
                metrics.HEADER_HEIGHT + 10,
            )
            self._notifications.raise_()

    def _toggle_notifications(self) -> None:
        if self._notifications is None or self._shell is None:
            return
        visible = not self._notifications.isVisible()
        self._notifications.setVisible(visible)
        self._shell.header().bell().set_active(visible)
        if visible:
            self._reposition_overlays(self._shell)

    # ---------------------------- fatal başlanğıc ----------------------------- #

    def show_fatal_error(self, message: str) -> None:
        """Tətbiq işə düşə bilmədi — EHTİYAT ƏLAQƏ VASİTƏSİ ilə (bölmə 8).

        Bölmə 8: "hər fatal başlanğıc-xətası ekranında statik e-poçt ünvanı
        göstərilir" — tətbiq açılmırsa müştəri daxili dəstək chat-inə çata
        bilmir və başqa heç bir yolu qalmır.
        """
        from src.presentation.screens.group_a_entry import (  # noqa: PLC0415
            FatalStartupScreen,
        )

        screen = FatalStartupScreen(self._theme, message=message)
        self._window.set_content(screen)
        self._window.show()

    def show_startup_failure(
        self,
        *,
        message: str,
        kind: StartupFailureKind,
        rebuild: Callable[[], ApplicationContext],
    ) -> None:
        """Başlanğıc nasazlığını NÖVÜNƏ uyğun ekranla göstərir (DB-4 Faza 4).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ PROSESİ YENİDƏN BAŞLATMIRIQ
        ──────────────────────────────────────────────────────────────────────
        «Yenidən cəhd et» düyməsi tətbiqi bağlayıb açsaydı, istifadəçi Windows
        UAC/antivirus gecikməsini hər cəhddə yenidən keçərdi və ayarlar
        ekranında yazdıqları itərdi. `rebuild` isə eyni prosesdə `build_context`
        -i yenidən çağırır: uğurda örtük normal axına qoşulur, uğursuzluqda
        YENİ nasazlıq növü ilə eyni ekran qayıdır — yəni parol düzəldikdən sonra
        mesaj «şəbəkə xətası»na dəyişə bilər və istifadəçi irəlilədiyini görür.
        """
        from src.presentation.screens.group_a_entry import (  # noqa: PLC0415
            FatalStartupScreen,
        )

        screen = FatalStartupScreen(
            self._theme,
            message=message,
            retry=True,
        )
        # `lambda` MƏCBURİDİR: PySide6 bağlı metodu ZƏİF saxlayır və ekranla
        # birlikdə yığılan metod siqnalı sükutla kəsərdi (CLAUDE.md §6).
        screen.retry_requested.connect(lambda: self._attempt_startup(rebuild))
        self._window.set_content(screen)
        self._window.show()

    def show_connection_settings(self, rebuild: Callable[[], ApplicationContext]) -> None:
        """«Bağlantı Ayarları» ekranı — girişdən ƏVVƏL açılan yeganə yazı yolu."""
        from src.presentation.controllers.connection_settings import (  # noqa: PLC0415
            ConnectionSettingsController,
        )
        from src.presentation.screens.group_a_entry import (  # noqa: PLC0415
            ConnectionSettingsScreen,
        )

        screen = ConnectionSettingsScreen(self._theme)
        controller = ConnectionSettingsController(
            on_saved=lambda: self._attempt_startup(rebuild),
        )
        controller.attach(screen)
        # İmtina fatal ekrana QAYIDIR, tətbiqi bağlamır: istifadəçi ayarları
        # dəyişmək istəmirsə də əlaqə ünvanını görməlidir (bölmə 8).
        screen.cancelled.connect(lambda: self._attempt_startup(rebuild))
        self._window.set_content(screen)
        self._window.show()

    def _attempt_startup(self, rebuild: Callable[[], ApplicationContext]) -> None:
        """Konteksti yenidən qurmağa cəhd edir; uğurda normal axına keçir."""
        from src.presentation.composition import StartupError  # noqa: PLC0415

        try:
            context = rebuild()
        except StartupError as exc:
            _log.warning("STARTUP_RETRY_FAILED", extra=exc.to_dict())
            self.show_startup_failure(message=exc.user_message, kind=exc.kind, rebuild=rebuild)
            return

        self.adopt_context(context)

    def adopt_context(self, context: ApplicationContext) -> None:
        """Gec qurulmuş konteksti mənimsəyir və örtüyü normal axına salır.

        Kontekst KONSTRUKTORDA verilə bilməzdi: bu yol məhz konstruktor
        anında bazanın əlçatmaz olduğu haldır. Kontroller burada qurulur,
        çünki `_build_auth_controller` konteksti tələb edir.
        """
        self._context = context
        self.set_auth_controller(_build_auth_controller(context))
        _log.info("STARTUP_RECOVERED", extra={"tenant_id": str(context.tenant_id)})
        self.start()

    # -------------------------------- tema ------------------------------------ #

    def _on_theme_selected(self, key: str) -> None:
        """Ayarlar ekranındakı seçim — `user_preferences`-ə YAZILIR (bölmə 9).

        Bölmə 9: "seçim `user_preferences` cədvəlində saxlanılır və növbəti
        login-də tətbiq olunur". Yalnız yaddaşda saxlamaq tətbiq bağlananda
        seçimi itirərdi.
        """
        self.set_theme(ThemeMode(key))
        self._persist_theme(key)

    def _persist_theme(self, key: str) -> None:
        """Tema seçimini yazır — uğursuzluq interfeysi DAYANDIRMIR."""
        if self._context is None or self._current_employee is None:
            return
        try:
            with self._context.session() as session:
                session.preferences.set_theme(self._current_employee.id, key.upper())
                session.commit()
        except Exception:
            _log.exception("THEME_PERSIST_FAILED")

    def toggle_theme(self) -> None:
        """Header-dəki düymə — işıqlı ↔ tünd."""
        target = ThemeMode.DARK if self._theme.mode is ThemeMode.LIGHT else ThemeMode.LIGHT
        self.set_theme(target)

    def set_theme(self, preference: ThemeMode) -> None:
        """Temanı yumşaq keçidlə dəyişir."""

        def apply() -> None:
            self._theme.set_preference(preference, self._app)
            # Pəncərə düymələrinin İKONLARI QSS ilə boyanmır (piksel şəklidir)
            # — onlar temadan sonra ayrıca yenidən çəkilməlidir, əks halda
            # tünd temada işıqlı ikonlar qalırdı.
            self._window.apply_theme(self._theme)
            if self._shell is not None:
                self._shell.apply_theme()

        animate_theme_change(self._window, apply)
        _log.info("THEME_CHANGED", extra={"preference": preference.value})

    # -------------------------------- kiosk ----------------------------------- #

    def _build_employee_home(
        self,
        outcome: KioskOutcome,
        *,
        kiosk: KioskWindow,
        pin_pad: QWidget,
    ) -> QWidget:
        """İşçi Ana Ekranını REAL məlumatla qurur (bölmə 3).

        Statusa uyğun TƏK bir aktiv düymə göstərilir; `🟡` vəziyyətlərində
        düymə YOXDUR, yalnız "Kamera Operatorunun təsdiqini gözləyin" mesajı.
        """
        from src.presentation.screens.group_a_kiosk import (  # noqa: PLC0415
            EmployeeHomeScreen,
        )

        assert outcome.employee is not None
        assert self._kiosk_controller is not None
        employee = outcome.employee
        controller = self._kiosk_controller

        home = EmployeeHomeScreen(
            self._theme,
            full_name=employee.full_name,
            position_name=employee.position.name_az,
            store_name="",
        )

        def refresh(status_outcome: KioskOutcome) -> None:
            if status_outcome.status is not None:
                home.set_status(status_outcome.status)
            # Fasilə sayğacı HƏR əməliyyatdan sonra yenilənir (nahar.md):
            # STEP1 onu artırır, STEP2/STEP3 isə göstəricini dəyişmir — lakin
            # ayrı-ayrı yollar yazsaydıq, biri unudulanda ekran köhnə rəqəmi
            # göstərərdi və işçi "2-ci fasilə" xəbərdarlığını görməzdi.
            home.set_break_options(controller.break_options(employee))

        def show_face_overlay(outcome: KioskOutcome, status: WorkerStatus) -> None:
            """Üz təsdiqi nəticəsini kioskda göstərir (facecontrol.md bənd 3, 5, 6).

            OVERLAY YALNIZ BLOKLAYAN NƏTİCƏDƏ AÇILIR (bax `controllers/
            kiosk.py::BLOCKING_FACE_OUTCOMES`): uğurlu təsdiq gündə onlarla
            dəfə baş verir və hər dəfə bağlanmalı modal kiosk axınına artıq
            bir toxunuş əlavə edərdi.

            HƏRƏKƏT MƏTNİNİ BURADA SEÇMİRİK (bənd 6) — `outcome.face["gesture"]`
            serverdə seçilmiş hərəkətin Azərbaycanca qarşılığıdır.
            """
            from src.presentation.screens.face_control import (  # noqa: PLC0415
                FaceVerificationOverlay,
            )

            overlay = FaceVerificationOverlay(self._theme, parent=home)
            overlay.set_result(outcome.face)

            def retry() -> None:
                # `RETRY` TEXNİKİ haldır (üz görünmədi) və heç bir sayğaca
                # düşmür — yenidən cəhd EYNİ əməliyyatı təkrarlayır.
                overlay.accept()
                on_action(status)

            overlay.retry_requested.connect(retry)
            overlay.open()

        def on_action(status: WorkerStatus) -> None:
            """Statusa uyğun TƏK əməliyyat (bölmə 3).

            Hansı düymənin basıldığını EKRAN deyil, STATUS həll edir — ekranda
            eyni düymə mətni dəyişir və status hər dəfə serverdən oxunur.

            ÜZ QAPISI BURADA ÇAĞIRILMIR: `KioskController`-in üç metodu onu
            ÖZ içində, əməliyyatdan ƏVVƏL icra edir (bax `controllers/
            kiosk.py::_guarded`). Qapını buraya qoysaydıq, o, GUI-nin bir
            budağına bağlanardı və kontrolleri birbaşa çağıran hər yol onu
            atlayardı — yəni Faza 2-nin açıq sənədləşdirdiyi boşluq bağlanmış
            olmazdı.
            """
            outcome: KioskOutcome
            if status is WorkerStatus.NOT_STARTED:
                outcome = controller.start_day(employee)
            elif status is WorkerStatus.VERIFIED:
                # Fasilə növü EKRANDAN gəlir, statusdan yox: `[İcazə İstəyirəm]`
                # eyni düymədir, seçim isə işçinindir. Boş sətir = «Ümumi
                # icazə», yəni bugünkü davranışın eynisi (`leave_type_id=None`).
                outcome = controller.request_leave(
                    employee, leave_type_id=_leave_type_id_or_none(home)
                )
            elif status is WorkerStatus.OUTSIDE:
                outcome = controller.claim_return(employee)
            else:
                return
            refresh(outcome)
            if outcome.requires_face_overlay:
                show_face_overlay(outcome, status)

        home.action_requested.connect(on_action)
        # İLK DOLDURMA: işçi haqqını fasiləni istifadə etməmişdən ƏVVƏL
        # görməlidir ("Nahar fasiləniz: 60 dəqiqə · Bu gün: 0/1").
        home.set_break_options(controller.break_options(employee))
        home.logout_requested.connect(lambda: kiosk.set_content(pin_pad))

        # #16 — "Açıq Növbələr" kartının ÖZ kontrolleri var (CLAUDE.md §6):
        # kart həm oxuyur, həm yazır və hər tutmadan sonra siyahı yenidən
        # oxunmalıdır. `KioskController`-ə əlavə edilmədi, çünki o, GÜNÜN
        # AXINI (giriş/icazə/qayıdış) üçündür — açıq növbə isə gələcək günə
        # aiddir və statusdan asılı deyil.
        #
        # Kontrollerə istinad SAXLANMIR: o, siqnala bağladığı `lambda`-nın
        # bağlamasında yaşayır və ekranla birlikdə ölür.
        if self._context is not None:
            from src.presentation.controllers.open_shift import (  # noqa: PLC0415
                EmployeeOpenShiftController,
            )

            EmployeeOpenShiftController(self._context, employee).attach(home)

            # İşçi Ana Ekranının üç öz-xidmət keçidi (bölmə 3): tapşırıqlar,
            # xallar, «Cərimələrim» → etiraz. Üç düymə də mövcud idi və
            # siqnal yayırdı, lakin onları DİNLƏYƏN tərəf yox idi — işçi
            # basırdı, heç nə olmurdu. Ən ağırı cərimə etirazı idi: hüquq
            # vardı, ona çatan yol yox idi.
            from src.presentation.controllers.kiosk_self_service import (  # noqa: PLC0415
                KioskSelfServiceController,
            )

            KioskSelfServiceController(
                self._context,
                employee,
                kiosk=kiosk,
                theme=self._theme,
            ).attach(home)

            # #19 Elan (Broadcast, kompasos11.md Faza 8) — "Elanlar" kartının
            # ÖZ kontrolleri var, LAKİN bağlayacaq siqnalı YOXDUR (bir-tərəfli,
            # cavab yoxdur — bax `controllers/announcements.py` başlığı).
            # Kontrollerə istinad SAXLANMIR — `EmployeeOpenShiftController` ilə
            # eyni qərar.
            from src.presentation.controllers.announcements import (  # noqa: PLC0415
                EmployeeAnnouncementController,
            )

            EmployeeAnnouncementController(self._context, employee).attach(home)

            # #28 İllik Məzuniyyət (kompas1.md Faza 4) — "İllik Məzuniyyət"
            # kartının ÖZ kontrolleri var: kart həm oxuyur (balans), həm
            # yazır (sorğu) və hər sorğudan sonra balans yenidən oxunur.
            # `KioskController`-ə əlavə EDİLMƏDİ — o, GÜNÜN AXINI üçündür
            # (giriş/gündaxili icazə/qayıdış), illik haqq isə ayrı mexanizmdir
            # (bax `controllers/annual_leave.py` başlığı).
            from src.presentation.controllers.annual_leave import (  # noqa: PLC0415
                EmployeeAnnualLeaveController,
            )

            EmployeeAnnualLeaveController(self._context, employee).attach(home)

        refresh(outcome)
        return home

    def start_kiosk(self) -> KioskWindow:
        """Kiosk axını — PIN klaviaturası ilə başlayır."""
        from src.presentation import preview_data  # noqa: PLC0415
        from src.presentation.screens.group_a_kiosk import (  # noqa: PLC0415
            EmployeeHomeScreen,
            PinPadScreen,
        )

        kiosk = KioskWindow()
        pin_pad = PinPadScreen(
            self._theme,
            store_name="Bellona — 28 May",
            terminal_name="Kiosk Terminal 01",
        )
        pin_pad.set_clock("09:42 · 12 Avqust 2026")

        def show_preview_home() -> None:
            """Dizayn yoxlaması üçün nümunə İşçi Ana Ekranı."""
            home = EmployeeHomeScreen(
                self._theme,
                full_name="Aysel Quliyeva",
                position_name="Satış Məsləhətçisi",
                store_name="Bellona 28 May",
            )
            home.set_tasks(
                [
                    "Vitrin yenilənməsi — bu gün",
                    "Anbar sayımı — sabah",
                    "Müştəri geri-zəngi",
                ]
            )
            home.set_points(1240, monthly_delta=180, to_next_reward=760)
            home.set_fines(
                count=1,
                total_text="25 ₼",
                latest="Gecikmə — 04 Avqust",
                appeal_days_left=3,
            )
            # #16 — maket və canlı yol EYNİ açarları işlədir (`id`, `date`,
            # `work_mode`); bax `controllers/open_shift.py::_to_employee_row`.
            home.set_open_shifts(
                [
                    {
                        "id": "00000000-0000-0000-0000-000000000016",
                        "date": "14.08.2026 · Cüm",
                        "work_mode": "Səhər · 09:00–18:00",
                    }
                ]
            )
            # #19 — maket və canlı yol EYNİ açarları işlədir (`title`,
            # `message`, `scope_text`, `date`); bax
            # `controllers/announcements.py::_to_employee_row`.
            home.set_announcements(
                [
                    {
                        "id": "00000000-0000-0000-0000-000000000019",
                        "title": "Bayram iş qrafiki",
                        "message": (
                            "20-22 Avqust tarixlərində iş saatları 10:00–19:00 olaraq dəyişdirilib."
                        ),
                        "scope_text": "Bütün mağazalar",
                        "date": "12.08.2026 09:00",
                    }
                ]
            )
            # #28 — maket və canlı yol EYNİ açarları işlədir. Burada sözlük
            # ƏL İLƏ yazılmır, `preview_data`-dan gəlir: yeddi açarlı bir
            # sözlüyün iki yerdə təkrarı məhz `menu.py` başlığındakı tarixi
            # qüsurun (ad məkanı sürüşməsi) yaranma yoludur.
            home.set_annual_leave_balance(dict(preview_data.ANNUAL_LEAVE_BALANCE))
            home.logout_requested.connect(lambda: kiosk.set_content(pin_pad))
            kiosk.set_content(home)

        def on_pin(code: str) -> None:
            """PIN daxil edildi — önizləmədə nümunə, əks halda REAL yoxlama."""
            if self._preview:
                show_preview_home()
                return
            if self._kiosk_controller is None:
                # Kontroller yoxdursa PIN yoxlanıla bilməz. Səssiz keçmək
                # işçiyə "sistem məni tanımır" hissi verərdi; açıq mesaj isə
                # onu dərhal menecerə yönləndirir.
                pin_pad.show_message(
                    "Sistem konfiqurasiya edilməyib — administratorla əlaqə saxlayın."
                )
                return

            outcome = self._kiosk_controller.authenticate(code)
            if outcome.failed or outcome.employee is None:
                pin_pad.show_message(outcome.message)
                return

            # İLK GİRİŞ ÜZ QEYDİYYATI — kiosk qapısında da.
            #
            # Mağaza işçisi paneldən yox, MƏHZ buradan girir. Tələbi yalnız
            # panel girişinə qoysaydıq, işçilərin böyük hissəsi üz qeydiyyatını
            # heç vaxt keçməzdi — qapı adı ilə qalardı.
            #
            # PIN-siz «üzlə giriş» yolunda (`on_face_login`) bu yoxlama
            # LAZIM DEYİL: orada işçi onsuz da üzü ilə tanınıb, yəni profili
            # mövcuddur.
            if self._show_face_setup_if_required(
                outcome.employee,
                on_continue=lambda: kiosk.set_content(
                    self._build_employee_home(outcome, kiosk=kiosk, pin_pad=pin_pad)
                ),
                host=kiosk.set_content,
            ):
                return

            home = self._build_employee_home(outcome, kiosk=kiosk, pin_pad=pin_pad)
            kiosk.set_content(home)

        def on_face_login() -> None:
            """«Üzlə daxil ol» — PIN-siz giriş (üz qapısı ilə).

            Önizləmədə eyni nümunə ekranı açılır: maket rejimində kamera və
            baza yoxdur, lakin düymənin AXINI göstərilməlidir — əks halda
            dizayn baxışında o, ölü bir düymə kimi görünərdi.
            """
            if self._preview:
                show_preview_home()
                return
            if self._kiosk_controller is None:
                pin_pad.show_message(
                    "Sistem konfiqurasiya edilməyib — administratorla əlaqə saxlayın."
                )
                return

            outcome = self._kiosk_controller.authenticate_by_face()
            if outcome.failed or outcome.employee is None:
                pin_pad.show_message(outcome.message)
                return

            home = self._build_employee_home(outcome, kiosk=kiosk, pin_pad=pin_pad)
            kiosk.set_content(home)

        pin_pad.submitted.connect(on_pin)
        pin_pad.face_login_requested.connect(on_face_login)
        # DÜYMƏ YALNIZ İŞLƏYƏCƏYİ HALDA GÖRÜNÜR: modul, mağaza əhatəsi və
        # kamera — üçü də hazır olmalıdır. Önizləmədə həmişə göstərilir ki,
        # dizayn baxışı ekranın tam formasını görsün.
        pin_pad.set_face_login_available(
            True
            if self._preview
            else self._kiosk_controller is not None
            and self._kiosk_controller.face_login_available()
        )
        kiosk.set_content(pin_pad)

        def on_exit() -> None:
            kiosk.allow_close()
            kiosk.close()

        kiosk.exit_requested.connect(on_exit)
        kiosk.start()
        self._kiosk = kiosk
        return kiosk


def _load_context_behind_splash(
    app: QApplication,
    application: KompasApplication,
    factory: Callable[[], ApplicationContext],
) -> tuple[ApplicationContext | None, str, StartupFailureKind | None]:
    """Kontekst qurulur — SPLASH GÖRÜNƏRKƏN və GUI sapından KƏNARDA.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ BU LAZIM OLDU
    ──────────────────────────────────────────────────────────────────────────
    `build_context()` baza hovuzunu açır və bağlantı taymautu 15 saniyəyədəkdir.
    Əvvəl o, `main.py`-da PƏNCƏRƏDƏN ƏVVƏL çağırılırdı: server əlçatmazdırsa
    (kabel çıxıb, VPN düşüb, DSN səhvdir) istifadəçi həmin müddət boyu HEÇ NƏ
    görmürdü. Mağaza işçisi üçün bu, «proqram açılmır» deməkdir.

    İki addım BİRLİKDƏ lazımdır və biri digərini əvəz etmir:

        * splash DƏRHAL göstərilir — istifadəçi proqramın işlədiyini görür;
        * iş FON SAPINDA icra olunur — əks halda splash donar və Windows
          pəncərəni «Cavab vermir» kimi işarələyərdi.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ YERLİ `QEventLoop`
    ──────────────────────────────────────────────────────────────────────────
    `run()`-un bütün sonrakı qərarları (cihaz qapısı, kiosk, autentifikasiya)
    kontekstdən ASILIDIR və onlar `app.exec()`-dən ƏVVƏL qurulur. Nəticəni
    siqnalla gözləmək üçün burada müvəqqəti hadisə dövrəsi açılır: pəncərə
    canlı qalır (splash animasiya edir, pəncərə sürüşdürülə bilir), axın isə
    ardıcıl oxunur. Alternativ — bütün `run()`-u callback zəncirinə çevirmək —
    kompozisiya kökünü oxunmaz edərdi.

    Returns:
        `(kontekst, istifadəçi mesajı, nasazlıq növü)`. Uğurda mesaj boşdur.
    """
    from PySide6.QtCore import QEventLoop  # noqa: PLC0415

    from src.presentation.background_task import BackgroundTask  # noqa: PLC0415
    from src.presentation.composition import StartupError  # noqa: PLC0415

    application.show_loading_splash()
    # Splash-ın FAKTİKİ çəkilməsi üçün: `show()` yalnız növbəyə qoyur.
    app.processEvents()

    outcome: dict[str, object] = {}
    loop = QEventLoop()
    task = BackgroundTask(name="STARTUP_CONTEXT")

    def _succeeded(value: object) -> None:
        outcome["context"] = value
        loop.quit()

    def _failed(error: object) -> None:
        outcome["error"] = error
        loop.quit()

    task.succeeded.connect(_succeeded)
    task.failed.connect(_failed)
    task.run(factory)
    loop.exec()

    error = outcome.get("error")
    if error is None:
        return cast("ApplicationContext", outcome.get("context")), "", None

    if isinstance(error, StartupError):
        _log.critical("GUI_STARTUP_ERROR", extra=error.to_dict())
        return None, error.user_message, error.kind

    # GÖZLƏNİLMƏYƏN istisna da BOŞ pəncərəyə çevrilməməlidir: istifadəçi
    # ekranda səbəb və əlaqə ünvanı görməlidir (bölmə 8). Növ `None` qalır —
    # «yenidən cəhd et» təklif etmək burada yanlış olardı, çünki səbəb
    # naməlumdur.
    unexpected = error if isinstance(error, BaseException) else None
    _log.critical("GUI_STARTUP_UNEXPECTED", exc_info=unexpected)
    return None, "KompasOS işə düşə bilmədi. Administratorunuzla əlaqə saxlayın.", None


def run(
    *,
    preview: bool = False,
    kiosk: bool = False,
    theme: ThemeMode = ThemeMode.SYSTEM,
    context: ApplicationContext | None = None,
    startup_error: str = "",
    startup_failure_kind: StartupFailureKind | None = None,
    rebuild_context: Callable[[], ApplicationContext] | None = None,
) -> int:
    """GUI-ni işə salır və çıxış kodunu qaytarır.

    Args:
        context: Canlı obyekt qrafı (`main.py` qurur). `None` → önizləmə.
        startup_error: Kontekst qurula bilmədisə istifadəçiyə göstəriləcək
            izah. Boş DEYİLSƏ fatal başlanğıc ekranı açılır (bölmə 8).
        startup_failure_kind: Nasazlığın növü (DB-4 Faza 4). Verilibsə ekran
            növə uyğun düymələri göstərir; verilməyibsə köhnə davranış qalır —
            yalnız mətn və əlaqə ünvanı.
        rebuild_context: `build_context` çağırışı. «Yenidən cəhd et» və
            ayarlar ekranı ONA bağlıdır; ötürülməzsə düymələr göstərilmir,
            çünki basılanda edəcəkləri heç nə olmazdı.
    """
    # Taskbar kimliyi İLK PƏNCƏRƏDƏN ƏVVƏL təyin olunmalıdır (bax funksiya
    # başlığı) — `QApplication` qurulduqdan sonra da olar, lakin pəncərə
    # yaranmazdan əvvəl. Ən erkən nöqtə burasıdır.
    _set_app_user_model_id()

    existing = QApplication.instance()
    # `instance()` bazis tip qaytarır; GUI üçün məhz `QApplication` lazımdır.
    app = existing if isinstance(existing, QApplication) else QApplication(sys.argv)
    app.setApplicationName("KompasOS")
    app.setApplicationVersion(__version__)
    # Çərçivəsiz pəncərədə Qt-nin öz "yüksək DPI" miqyaslaması ikon
    # kəskinliyi üçün vacibdir.
    app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    application = KompasApplication(app, preview=preview, theme_preference=theme, context=context)

    # KONTEKST BURADA QURULUR, `main.py`-da YOX (SETUP-1 Faza 2).
    #
    # `main.py` onu pəncərədən əvvəl qururdu və baza əlçatmaz olan maşında
    # istifadəçi bağlantı taymautu boyu BOŞ EKRAN görürdü. İndi əvvəlcə splash
    # göstərilir, iş isə fon sapında gedir — bax
    # `_load_context_behind_splash`. Şərt DAR saxlanılır: önizləmə rejimində
    # baza ümumiyyətlə lazım deyil, `startup_error` isə artıq verilibsə
    # yenidən cəhd etmək səhv olardı.
    if context is None and not preview and not startup_error and rebuild_context is not None:
        context, startup_error, startup_failure_kind = _load_context_behind_splash(
            app, application, rebuild_context
        )
        application.set_context(context)

    application.set_rebuild_context(rebuild_context)
    device_gate = _device_gate(application, context) if context is not None else None

    if device_gate is not None:
        # Cihaz təsdiqlənməyib/bloklanıb — tətbiq İŞLƏMİR (DEVICE-1 Faza 2.2).
        # Login ekranı belə açılmır: filialını bilməyən cihazda kim isə giriş
        # edərsə, onun yazdığı cərimə/tabel SƏHV mağazaya düşərdi.
        pass
    elif startup_error:
        # Kiosk rejimində belə fatal ekran göstərilir: mağaza işçisi "proqram
        # açılmır" deyib zəng etməkdənsə ekranda əlaqə ünvanını görməlidir.
        if startup_failure_kind is not None and rebuild_context is not None:
            application.show_startup_failure(
                message=startup_error,
                kind=startup_failure_kind,
                rebuild=rebuild_context,
            )
        else:
            application.show_fatal_error(startup_error)
    elif kiosk:
        if context is not None:
            controller = _build_kiosk_controller(context)
            if controller is not None:
                application.set_kiosk_controller(controller)
        application.start_kiosk()
    else:
        if context is not None:
            application.set_auth_controller(_build_auth_controller(context))
        application.start()

    if context is not None:
        # ──────────────────────────────────────────────────────────────────
        # SERVER VAXTI SİNXRONİZASİYASI (TIME-1)
        # ──────────────────────────────────────────────────────────────────
        # Ekranlar qurulduqdan SONRA başladılır: ilk sorğu sinxrondur (lövbər
        # hazır olmalıdır) və onu pəncərə görünməzdən əvvəl etmək açılışı
        # şəbəkə gecikməsi qədər uzadardı. Vaxt-kritik ilk əməliyyat isə
        # istifadəçinin girişindən sonra baş verir — o vaxta lövbər onsuz da
        # hazırdır.
        context.start_time_sync()
        app.aboutToQuit.connect(context.stop_time_sync)
        _attach_live_clock(app, application, context)
        _apply_tenant_branding(application, context)

        # KAMERA TUTACAĞI BAĞLANIŞDA BURAXILIR (`facecontrol.md` Faza 3).
        # `OpenCvCameraCapture` cihazı AÇIQ saxlayır (hər doğrulamada bir
        # saniyəlik açılış qiymətini ödəməmək üçün — bax orada). Proses
        # bağlananda onu buraxmasaq, Windows-da sürücü kameranı bir müddət
        # "məşğul" saxlayır və dərhal yenidən başladılan kiosk (watchdog!)
        # öz kamerasını aça bilməzdi.
        app.aboutToQuit.connect(context.close_face_engine)

    _log.info("GUI_STARTED", extra={"preview": preview, "kiosk": kiosk})
    return app.exec()


def _has_other_active_device(context: ApplicationContext) -> bool:
    """Kirayəçidə TƏSDİQLƏNMİŞ cihaz varmı — kilidlənmə qoruyucusu üçün.

    Uğursuzluqda `False` qaytarır, yəni qapı AÇIQ qalır. Səbəb eynidir: sayğac
    oxuna bilmirsə, «bloklayaq» qərarı istifadəçini heç kimin aça bilmədiyi
    ekranda saxlayardı — halbuki problem cihazda deyil, sorğudadır.
    """
    try:
        with context.session() as session:
            return session.devices.license_usage(session.tenant_id).active > 0
    except Exception:
        _log.warning("DEVICE_ACTIVE_COUNT_UNAVAILABLE", exc_info=True)
        return False


def _apply_tenant_branding(application: KompasApplication, context: ApplicationContext) -> None:
    """Şirkət adını başlıq zolağına və pəncərə adına yazır (TENANT-1 Faza 2).

    ──────────────────────────────────────────────────────────────────────────
    OXUMAQ ÜÇÜN GİRİŞ GÖZLƏNİLMİR
    ──────────────────────────────────────────────────────────────────────────
    `TenantBrandingUseCase.current()` icazə tələb etmir (bax use case başlığı):
    ad İSTİFADƏÇİ SEÇİLMƏMİŞDƏN ƏVVƏL, giriş ekranında görünməlidir. Girişdən
    sonra tətbiq etsəydik, müştəri öz brendini yalnız içəri girdikdən sonra
    görərdi — halbuki «bu, mənim sistemimdir» siqnalı məhz açılışda lazımdır.

    Uğursuzluq DAYANDIRICI DEYİL: `tenant_branding` cədvəli YENİDİR
    (migrations/064) və miqrasiya tətbiq olunmamış quraşdırmada sorğu xəta
    verər. Həmin halda defolt «KompasOS» qalır — tətbiqin açılmaması
    brendsiz başlıqdan qat-qat pis nəticədir.
    """
    try:
        with context.session() as session:
            branding = session.branding.current(session.tenant_id)
    except Exception:
        _log.warning("TENANT_BRANDING_NOT_APPLIED", exc_info=True)
        return

    title = branding.window_title()
    window = application.window()
    window.setWindowTitle(title)
    title_bar = window.title_bar()
    if title_bar is not None:
        title_bar.set_title(title)


def _device_gate(
    application: KompasApplication, context: ApplicationContext
) -> DevicePendingController | None:
    """Cihaz qeydiyyatı qapısı — təsdiqlənməmiş cihaz işləmir (DEVICE-1).

    ──────────────────────────────────────────────────────────────────────────
    QEYDİYYAT UĞURSUZ OLARSA TƏTBİQ DAYANMIR — VƏ BU, QƏSDƏNDİR
    ──────────────────────────────────────────────────────────────────────────
    `registered_devices` cədvəli YENİDİR (migrations/063). Miqrasiya hələ
    tətbiq olunmamış bir quraşdırmada sorğu xəta verəcək. Həmin halda qapını
    «bağlı» saysaydıq, buraxılışın yayılması BÜTÜN mağazalar üçün kəsintiyə
    çevrilərdi — halbuki qüsur cihazda deyil, miqrasiya sırasındadır.

    Ona görə qapı YALNIZ cavab ALINDIQDA hökm verir: cihaz oxundu və
    `is_operational` deyilsə ekran göstərilir. Oxuna bilmədisə jurnal yazılır
    və tətbiq davam edir (DB-4-ün «graceful failure» prinsipi ilə eyni).

    ──────────────────────────────────────────────────────────────────────────
    İLK QURAŞDIRMA — TENANT SƏTRİ HƏLƏ YOXDUR (paketlənmiş `.exe` tapdı)
    ──────────────────────────────────────────────────────────────────────────
    SEC-021-ə görə boş `KOMPASOS_TENANT_ID` XƏTA DEYİL: kimlik yerli faylda
    YARADILIR və `license_tenants` sətrini İlk Quraşdırma Sihirbazı yazır.
    Yəni ilk açılışda tenant sətri MÖVCUD DEYİL və cihaz qeydiyyatı xarici
    açar pozuntusu ilə dayanır.

    Bu, `.exe`-ni FAKTİKİ işə salmaqla tapıldı — nə lint, nə də 5076 test onu
    göstərmirdi, çünki hamısı tenant-ı hazır fərz edir. `ForeignKeyViolation`
    indi AYRICA tutulur və ERROR deyil, INFO kimi yazılır: bu, gözlənilən ilk
    açılış vəziyyətidir, nasazlıq deyil. Cihaz sihirbaz bitəndən sonrakı
    açılışda qeydiyyatdan keçir.

    ──────────────────────────────────────────────────────────────────────────
    KİLİDLƏNMƏ QORUYUCUSU — İLK CİHAZ BLOKLANMIR
    ──────────────────────────────────────────────────────────────────────────
    Sihirbaz bitəndən sonrakı açılışda tenant artıq var və cihaz
    `PENDING_APPROVAL` yazılır. Qapı onu bloklasaydı, nəticə ÇIXIŞSIZ DÖVRƏ
    olardı: təsdiqi verəcək admin məhz bloklanmış cihazın arxasındadır.

    Ona görə qapı YALNIZ kirayəçidə ƏN AZI BİR aktiv cihaz olduqda bloklayır.
    Aktiv cihaz varsa, təsdiq verə biləcək iş yeri MÖVCUDDUR və yeni cihazın
    gözləməsi mənalıdır. Yoxdursa, birinci cihaz buraxılır — onsuz da hələ
    heç bir məlumat yoxdur və istifadəçi yenə də ad/şifrə ilə giriş etməlidir.

    Bu, DEVICE-1-in qoruma məqsədini zəiflətmir: hücumçu üçün maraqlı olan
    MƏLUMATLI quraşdırmadır və orada aktiv cihaz onsuz da var.

    Returns:
        Gözləmə ekranının kontrolleri — cihaz işləyə bilmirsə; əks halda
        `None` (tətbiq normal açılır).
    """
    import psycopg  # noqa: PLC0415

    from src.presentation.controllers.devices import (  # noqa: PLC0415
        DevicePendingController,
    )
    from src.presentation.screens.devices import DevicePendingScreen  # noqa: PLC0415

    controller = DevicePendingController(context)
    try:
        device = controller.register()
    except psycopg.errors.ForeignKeyViolation:
        # Tenant sətri hələ yoxdur — sihirbaz onu yaradacaq (bax yuxarı).
        _log.info(
            "DEVICE_GATE_DEFERRED",
            extra={"reason": "license_tenants sətri hələ yoxdur — ilk quraşdırma"},
        )
        return None
    except Exception:
        _log.exception("DEVICE_GATE_SKIPPED")
        return None

    if device.is_operational:
        return None

    if not _has_other_active_device(context):
        _log.warning(
            "DEVICE_GATE_OPEN_FIRST_DEVICE",
            extra={
                "short_code": device.short_code,
                "reason": "kirayəçidə aktiv cihaz yoxdur — bloklamaq çıxışsız dövrə olardı",
            },
        )
        return None

    screen = DevicePendingScreen(application.theme())
    screen.set_device(
        short_code=device.short_code,
        machine_name=device.machine_name,
        status=device.status,
    )
    controller.attach(screen)
    application.window().set_content(screen)
    application.window().show()
    _log.warning(
        "DEVICE_NOT_APPROVED",
        extra={"status": device.status.value, "short_code": device.short_code},
    )
    return controller


def _attach_live_clock(
    app: QApplication, application: KompasApplication, context: ApplicationContext
) -> None:
    """Başlıq zolağındakı saatı server vaxtına bağlayır (TIME-1 Faza 2.3).

    Kiosk rejimində başlıq zolağı YOXDUR (`show_title_bar=False`) — o halda
    `title_bar` `None` qaytarır və saat sadəcə qurulmur. Kiosk ekranı onsuz da
    eyni `Clock` portundan oxuyur.

    Taymer bağlanışda dayandırılır: `QTimer` widget-ə bağlıdır və Qt onu onsuz
    da məhv edərdi, lakin `aboutToQuit` anında hələ diri olan taymerin bir dəfə
    də tıqqıldaması artıq bağlanmış bazaya sorğu göndərə bilərdi.
    """
    title_bar = application.window().title_bar()
    if title_bar is None:
        return
    title_bar.set_clock_source(context.clock, status=context.time_integrity_status)
    app.aboutToQuit.connect(title_bar.live_clock.stop)


def _leave_type_id_or_none(home: EmployeeHomeScreen) -> LeaveTypeId | None:
    """İşçi ekranındakı fasilə seçimini `LeaveTypeId`-yə çevirir (nahar.md).

    Boş sətir — «Ümumi icazə» — `None` olur, yəni STEP1 bu günə qədərki
    davranışını saxlayır. Pozuq UUID də `None`-a düşür: ekran onu yalnız
    kontrollerin verdiyi siyahıdan götürür, lakin seçimin mənbəyi gələcəkdə
    dəyişsə, kiosk ÇÖKMƏMƏLİDİR — paylaşılan cihazda bir işçinin səhv seçimi
    bütün mağazanı bloklaya bilməz (`controllers/kiosk.py` başlığı).
    """
    import uuid  # noqa: PLC0415

    from src.domain.value_objects.identifiers import LeaveTypeId as _LeaveTypeId  # noqa: PLC0415

    raw = str(home.selected_break_leave_type_id() or "").strip()
    if not raw:
        return None
    try:
        return _LeaveTypeId(uuid.UUID(raw))
    except ValueError:
        _log.warning("KIOSK_BREAK_SELECTION_INVALID", extra={"value": raw})
        return None


def _build_kiosk_controller(context: ApplicationContext) -> KioskController | None:
    """Kiosk körpüsünü qurur — mağaza identifikatoru mühitdən gəlir.

    Hər kiosk PC-si BİR mağazaya bağlıdır və PIN handshake yalnız həmin
    mağazanın işçiləri arasında axtarış aparır (bax `PinHandshakeUseCase`).
    Mağaza təyin edilməyibsə kontroller QURULMUR: "bütün mağazalarda axtar"
    variantı 235 işçi üçün Argon2 hesablaması demək olardı və üstəlik başqa
    filialın işçisinin bu terminalda giriş etməsinə imkan verərdi.
    """
    import os  # noqa: PLC0415
    import uuid  # noqa: PLC0415

    from src.domain.value_objects.identifiers import StoreId  # noqa: PLC0415
    from src.presentation.controllers.kiosk import KioskController  # noqa: PLC0415

    raw_store = os.environ.get("KOMPASOS_STORE_ID", "").strip()
    if not raw_store:
        _log.error("KIOSK_STORE_NOT_CONFIGURED", extra={"env": "KOMPASOS_STORE_ID"})
        return None
    try:
        store_id = StoreId(uuid.UUID(raw_store))
    except ValueError:
        _log.error("KIOSK_STORE_ID_INVALID", extra={"value": raw_store})
        return None

    return KioskController(context, store_id=store_id)


def _build_auth_controller(context: ApplicationContext) -> AuthController:
    """Giriş kontrollerini canlı obyekt qrafı üzərində qurur.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ USE CASE HƏR CƏHDDƏ YENİDƏN QURULUR
    ──────────────────────────────────────────────────────────────────────────
    `AdminLoginUseCase` üç sessiya-bağlı asılılıq alır: `employees` repo-su,
    `audit` yazıcısı və onların bağlantısı. Kontrolleri bir dəfə qurub
    saxlasaydıq, o, artıq bağlanmış tranzaksiyaya istinad edərdi — giriş
    ekranı isə tətbiqin ən uzun ömürlü ekranıdır (istifadəçi orada dəqiqələrlə
    qala bilər).

    Ona görə `_SessionScopedLogin` hər cəhddə yeni sessiya açır, use case-i
    onun içində qurur və nəticəni qaytarır. Uğursuz cəhdlərin sayğacı
    (`pin_failed_attempts`) da həmin sessiyada yazılır və commit olunur —
    əks halda lockout heç vaxt işləməzdi.
    """
    from src.presentation.controllers.auth import AuthController  # noqa: PLC0415

    bridge = _SessionScopedLogin(context)
    return AuthController(
        login_use_case=bridge,  # type: ignore[arg-type]
        credentials=bridge,
        employees=bridge,
        tenant_id=context.tenant_id,
    )


class _SessionScopedLogin:
    """`AdminLoginUseCase` + `EmployeeLookup` + `CredentialSource` körpüsü.

    Üçü BİR sinifdədir, çünki hər üçü eyni sətri oxuyur; ayrı-ayrı olsaydılar
    bir giriş cəhdi üç ardıcıl tranzaksiya açardı.
    """

    def __init__(self, context: ApplicationContext) -> None:
        self._context = context

    # --- EmployeeLookup ---------------------------------------------------- #

    def get_by_username(self, tenant_id: TenantId, username: Username) -> Employee | None:
        with self._context.session() as session:
            employee: Employee | None = session.uow.employees.get_by_username(tenant_id, username)
            return employee

    # --- CredentialSource -------------------------------------------------- #

    def credentials_for(self, employee_id: EmployeeId) -> Credentials | None:
        with self._context.session() as session:
            credentials: Credentials | None = session.uow.employees.credentials_for(employee_id)
            return credentials

    # --- AdminLoginUseCase.login ------------------------------------------- #

    def login(
        self,
        *,
        tenant_id: TenantId,
        username: Username,
        password: str,
        stored_hash: str | None,
        pepper_version: int = 1,
    ) -> object:
        from src.application.use_cases.authentication import (  # noqa: PLC0415
            AdminLoginUseCase,
        )
        from src.infrastructure.security.hashing import HashingService  # noqa: PLC0415
        from src.infrastructure.timekeeping.clock import SystemClock  # noqa: PLC0415

        with self._context.session() as session:
            use_case = AdminLoginUseCase(
                employees=session.uow.employees,
                # `limits`: şifrə siyasətinin minimum uzunluğu
                # (`PASSWORD_MIN_LENGTH`) ROOT-dandır. Ötürülməsəydi servis
                # fallback ilə işləyər və Root-un yazdığı uzunluq HEÇ VAXT
                # tətbiq olunmazdı.
                hashing=HashingService(limits=self._context.infrastructure_limits()),
                clock=SystemClock(),
                audit=session.uow.audit,
            )
            try:
                result = use_case.login(
                    tenant_id=tenant_id,
                    username=username,
                    password=password,
                    stored_hash=stored_hash,
                    pepper_version=pepper_version,
                )
            except Exception:
                # Uğursuz cəhdin sayğacı da YAZILMALIDIR — onsuz lockout
                # (5 səhv → 15 dəqiqə, bölmə 2) heç vaxt işə düşməzdi.
                session.commit()
                raise
            session.commit()
            return result


__all__ = ["SPLASH_DURATION_MS", "KompasApplication", "run"]
