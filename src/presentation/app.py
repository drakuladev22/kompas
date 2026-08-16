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
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, QTimer
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
    from src.presentation.composition import ApplicationContext
    from src.presentation.controllers.auth import AuthController
    from src.presentation.controllers.fine_entry import FineEntryController
    from src.presentation.controllers.kiosk import KioskController, KioskOutcome
    from src.presentation.controllers.sales_review import SalesReviewController
    from src.presentation.controllers.screen_data import ScreenDataBinder
    from src.presentation.plugin_surface import PluginPage
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen
    from src.presentation.widgets.worker_status import WorkerStatus

_log = get_logger(__name__)

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
        wizard.completed.connect(self._on_setup_completed)
        self._window.set_content(wizard)

    def _on_setup_completed(self, payload: dict[str, object]) -> None:
        """Sihirbaz formu doldurdu — hesab/mağaza yaradılır, sonra giriş.

        Sihirbaz EKRANI özü heç nə yazmır (o, yalnız formadır); yazma
        `FirstRunSetupUseCase`-dədir və o, "tenant boşdurmu?" qapısını
        yenidən yoxlayır — ekranın vəziyyətinə güvənilmir.
        """
        if self._context is None:
            self.show_login()
            return
        try:
            self._context.complete_setup(payload)
        except Exception as exc:
            _log.exception("FIRST_RUN_SETUP_FAILED")
            self.show_fatal_error(getattr(exc, "user_message", "Quraşdırma tamamlana bilmədi."))
            return
        self.show_login()

    # -------------------------------- giriş ---------------------------------- #

    def show_login(self) -> None:
        from src.presentation.screens.group_a_entry import AdminLoginScreen  # noqa: PLC0415

        login = AdminLoginScreen(self._theme)
        login.submitted.connect(self._on_login_submitted)
        self._window.set_content(login)
        self._login = login

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
        self.show_admin(outcome.employee, now=datetime.now(UTC))  # type: ignore[arg-type]

    # ------------------------------- örtük ----------------------------------- #

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

        # İlk açılan ekran — menyuda görünən ilk maddə. Sabit "dashboard"
        # yazmaq olmazdı: icazəsi olmayan istifadəçidə boş ekran qalardı.
        visible = shell.sidebar().entry_keys()
        if visible:
            shell.show_screen(visible[0])

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
            "annual_leave": lambda: AnnualLeaveInboxScreen(theme),
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

        #: Başlıqdakı kontekst mətni (maketdən).
        subtitles = {
            "dashboard": "21 filial · 12 Avqust 2026",
            "live_queue": "Canlı · 2 san əvvəl yeniləndi",
            "daily_roster": "Bellona 28 May · 12 Avqust 2026",
            "fines": "Avqust 2026 · Bellona 28 May",
            "fine_review": "Ayın əvvəli · göndərmə geri qaytarıla bilmir",
            "users": "235 nəfər · 21 filial",
            "bulk_operations": "CSV işçi idxalı · mağaza şablonu",
            "reports": "Avqust 2026 · iki ayrı fayl",
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
            "annual_leave": "İllik haqq · gündaxili icazədən AYRI mexanizm",
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


def run(
    *,
    preview: bool = False,
    kiosk: bool = False,
    theme: ThemeMode = ThemeMode.SYSTEM,
    context: ApplicationContext | None = None,
    startup_error: str = "",
) -> int:
    """GUI-ni işə salır və çıxış kodunu qaytarır.

    Args:
        context: Canlı obyekt qrafı (`main.py` qurur). `None` → önizləmə.
        startup_error: Kontekst qurula bilmədisə istifadəçiyə göstəriləcək
            izah. Boş DEYİLSƏ fatal başlanğıc ekranı açılır (bölmə 8).
    """
    existing = QApplication.instance()
    # `instance()` bazis tip qaytarır; GUI üçün məhz `QApplication` lazımdır.
    app = existing if isinstance(existing, QApplication) else QApplication(sys.argv)
    app.setApplicationName("KompasOS")
    app.setApplicationVersion(__version__)
    # Çərçivəsiz pəncərədə Qt-nin öz "yüksək DPI" miqyaslaması ikon
    # kəskinliyi üçün vacibdir.
    app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    application = KompasApplication(app, preview=preview, theme_preference=theme, context=context)

    if startup_error:
        # Kiosk rejimində belə fatal ekran göstərilir: mağaza işçisi "proqram
        # açılmır" deyib zəng etməkdənsə ekranda əlaqə ünvanını görməlidir.
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
        # KAMERA TUTACAĞI BAĞLANIŞDA BURAXILIR (`facecontrol.md` Faza 3).
        # `OpenCvCameraCapture` cihazı AÇIQ saxlayır (hər doğrulamada bir
        # saniyəlik açılış qiymətini ödəməmək üçün — bax orada). Proses
        # bağlananda onu buraxmasaq, Windows-da sürücü kameranı bir müddət
        # "məşğul" saxlayır və dərhal yenidən başladılan kiosk (watchdog!)
        # öz kamerasını aça bilməzdi.
        app.aboutToQuit.connect(context.close_face_engine)

    _log.info("GUI_STARTED", extra={"preview": preview, "kiosk": kiosk})
    return app.exec()


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
