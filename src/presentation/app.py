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
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from src import __version__
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
    from src.domain.value_objects.identifiers import EmployeeId, TenantId
    from src.infrastructure.persistence.mappers import Credentials
    from src.presentation.composition import ApplicationContext
    from src.presentation.controllers.auth import AuthController
    from src.presentation.controllers.fine_entry import FineEntryController
    from src.presentation.controllers.kiosk import KioskController, KioskOutcome
    from src.presentation.controllers.screen_data import ScreenDataBinder
    from src.presentation.widgets.worker_status import WorkerStatus

_log = get_logger(__name__)

#: Splash ekranının minimum görünmə müddəti.
SPLASH_DURATION_MS: Final = 1200

#: Sübut şəkli növbəsinin yoxlanma tezliyi (2 dəqiqə).
#: Cərimə yaradılan anda növbə ONSUZ DA bir dəfə boşaldılır (bax
#: `FineEntryController._issue`) — bu taymer yalnız şəbəkə qayıdanda və ya
#: kvota problemi həll olunanda gözləyən elementləri götürmək üçündür.
UPLOAD_POLL_INTERVAL_MS: Final = 120_000

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
        self._window = FramelessWindow(title="KompasOS")
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
        #: Sübut şəkillərini arxa planda Drive-a köçürən taymer.
        self._upload_timer: QTimer | None = None

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
        if self._setup_required():
            self.show_setup_wizard()
            return
        self.show_login()

    def _setup_required(self) -> bool:
        """Tenant-da admin hesabı yoxdursa İlk Quraşdırma Sihirbazı açılır.

        Xəta halında `False`: sihirbazı SƏHVƏN açmaq mövcud quraşdırmanı
        "boş" göstərərdi; giriş ekranını açmaq isə ən pis halda "giriş
        alınmadı" mesajı verir və geri qaytarıla bilən vəziyyətdir.
        """
        if self._context is None:
            return False
        try:
            with self._context.session() as session:
                return bool(session.setup.is_required(self._context.tenant_id))
        except Exception:
            _log.exception("SETUP_CHECK_FAILED")
            return False

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
            from src.presentation.controllers.screen_data import (  # noqa: PLC0415
                ScreenDataBinder,
            )

            self._binder = ScreenDataBinder(self._context, employee)
            self._fine_entry = FineEntryController(self._context, employee)
            self._start_upload_timer()
        shell = AdminShell(
            theme=self._theme,
            registry=self._registry,
            employee=employee,
            now=now,
            enabled_modules=self._enabled_modules(),
        )
        shell.theme_toggle_requested.connect(self.toggle_theme)
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

    def _start_upload_timer(self) -> None:
        """Sübut növbəsini dövri boşaldır (Faza 3.9).

        `EvidenceUploadWorker` özü sap YARATMIR — planlaşdırma çağıranın
        işidir. Burada Qt taymeri seçilib, ayrıca `threading.Thread` yox:
        yükləmə bitdikdən sonra `fines` sətri yenilənir və o iş bazaya
        toxunur; Qt hadisə dövrəsində qalmaq bu yazının interfeyslə eyni
        sırada getməsini təmin edir.

        Interval yükləmə HƏDDİ deyil, sadəcə fon dövrəsidir — ona görə
        `system_limits`-də açarı yoxdur (bölmə 3 onu sadalamır).
        """
        if self._context is None or self._upload_timer is not None:
            return
        timer = QTimer(self._window)
        timer.setInterval(UPLOAD_POLL_INTERVAL_MS)
        timer.timeout.connect(self._drain_upload_queue)
        timer.start()
        self._upload_timer = timer

    def _drain_upload_queue(self) -> None:
        if self._context is None:
            return
        # `run_evidence_uploads` özü istisna udur və 0 qaytarır — fon işi
        # interfeysi çökdürməməlidir (bax `composition.py`).
        uploaded = self._context.run_evidence_uploads()
        if uploaded:
            _log.info("EVIDENCE_UPLOADED", extra={"count": uploaded})

    def _attach_fine_entry(self, screen: QWidget) -> None:
        """Cərimə formasını use case-ə və sübut növbəsinə bağlayır (bölmə 4)."""
        from src.presentation.screens.group_b import FineEntryScreen  # noqa: PLC0415

        if self._fine_entry is None or not isinstance(screen, FineEntryScreen):
            return
        self._fine_entry.attach(screen)

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
                # Ayarlar ekranı tema seçimini örtüyə bağlayır — bu, önizləmə
                # məzmunu deyil, real davranışdır və hər iki rejimdə lazımdır.
                if isinstance(screen, group_d.SettingsScreen):
                    screen.select_theme(self._theme.preference.value)
                    screen.theme_selected.connect(self._on_theme_selected)
                # ROOT paneli TƏK ekrandır ki, həm oxuyur, həm yazır (limit,
                # modul açarı, yeni flag) — ona görə `_binder` yerinə öz
                # kontrolleri var (bax `controllers/root_control.py`).
                elif isinstance(screen, group_d.RootControlScreen):
                    self._attach_root_control(screen)
                elif isinstance(screen, group_d.DriveConnectionScreen):
                    self._attach_drive_connection(screen)
                # Cərimə formasının və növbənin YAZI yolları (sübut yükləməsi,
                # manual vaxt düzəlişi) — hər ikisi ROOT limitlərini işlədir.
                elif isinstance(screen, group_b.FineEntryScreen):
                    self._attach_fine_entry(screen)
                elif isinstance(screen, group_b.OperatorQueueScreen):
                    self._attach_camera_queue(screen)
                return screen

            return build

        # Bəzi ekranlar açılış siyahılarını KONSTRUKTORDA gözləyir (combo-box
        # dəyərləri), ona görə onlar `populate()`-dan əvvəl lazımdır.
        names: list[str] = []
        stores: list[str] = []
        fine_types: list[str] = []
        queue_stores: list[str] = []
        if self._preview:
            from src.presentation import preview_data  # noqa: PLC0415

            names = list(preview_data.EMPLOYEE_NAMES)
            stores = list(preview_data.STORES)
            fine_types = list(preview_data.FINE_TYPES)
            queue_stores = list(preview_data.STORES[:2])
        elif self._fine_entry is not None:
            # Canlı rejim: dropdown-lar operatorun ÖZ filiallarından qurulur
            # (bax `FineEntryController.options` — fail-safe boş siyahı).
            fine_types, stores, names = self._fine_entry.options()
            queue_stores = stores

        factories: dict[str, Callable[[], QWidget]] = {
            "dashboard": lambda: group_c.DashboardScreen(theme),
            "live_queue": lambda: group_b.OperatorQueueScreen(theme, assigned_stores=queue_stores),
            "daily_roster": lambda: group_c.DailyRosterScreen(theme),
            "shift_planning": lambda: group_c.ShiftPlanningScreen(theme),
            "shift_swaps": lambda: group_c.ShiftSwapScreen(theme),
            "fines": lambda: group_b.FineEntryScreen(
                theme, fine_types=fine_types, stores=stores, employees=names
            ),
            "fine_appeals": lambda: group_f.FineAppealInboxScreen(theme),
            "tasks": lambda: group_f.TasksScreen(theme),
            "sales_points": lambda: group_f.SalesPointsScreen(theme),
            "unassigned_sales": lambda: group_f.UnassignedSalesScreen(theme, employees=names),
            "users": lambda: group_c.UsersScreen(theme),
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
            "help": lambda: group_h.HelpCenterScreen(theme),
            "infrastructure": lambda: group_i.InfrastructureScreen(theme),
            "plugins": lambda: group_i.PluginScreen(theme),
            "dashboard_builder": lambda: group_i.DashboardBuilderScreen(theme),
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
            "users": "235 nəfər · 21 filial",
            "reports": "Avqust 2026 · iki ayrı fayl",
            "work_modes": "Növbə şablonları",
            "fine_types": "Standart məbləğlər · anti-fraud",
            "leave_types": "Fasilə kateqoriyaları",
            "infrastructure": "Baza keçidi · texniki fasilə",
            "plugins": "Sandbox-da işləyən genişləndirmələr",
        }

        for key, factory in factories.items():
            shell.register_screen(key, make(key, factory), subtitle=subtitles.get(key, ""))

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

        shell.header().bell_clicked.connect(self._toggle_notifications)

        # Örtük ölçüsü dəyişəndə üzən elementlər yenidən yerləşdirilir.
        original_resize = shell.resizeEvent

        def on_resize(event: QResizeEvent) -> None:
            original_resize(event)
            self._reposition_overlays(shell)

        shell.resizeEvent = on_resize  # type: ignore[method-assign]
        QTimer.singleShot(0, lambda: self._reposition_overlays(shell))

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

        def on_action(status: WorkerStatus) -> None:
            """Statusa uyğun TƏK əməliyyat (bölmə 3).

            Hansı düymənin basıldığını EKRAN deyil, STATUS həll edir — ekranda
            eyni düymə mətni dəyişir və status hər dəfə serverdən oxunur.
            """
            if status is WorkerStatus.NOT_STARTED:
                refresh(controller.start_day(employee))
            elif status is WorkerStatus.VERIFIED:
                refresh(controller.request_leave(employee))
            elif status is WorkerStatus.OUTSIDE:
                refresh(controller.claim_return(employee))

        home.action_requested.connect(on_action)
        home.logout_requested.connect(lambda: kiosk.set_content(pin_pad))
        refresh(outcome)
        return home

    def start_kiosk(self) -> KioskWindow:
        """Kiosk axını — PIN klaviaturası ilə başlayır."""
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

        pin_pad.submitted.connect(on_pin)
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

    _log.info("GUI_STARTED", extra={"preview": preview, "kiosk": kiosk})
    return app.exec()


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
                hashing=HashingService(),
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
