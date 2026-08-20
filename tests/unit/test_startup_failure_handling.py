"""Başlanğıc nasazlıqları — ÜÇ hal, ÜÇ ayrı davranış (DB-4 Faza 4).

──────────────────────────────────────────────────────────────────────────────
NƏYİ QORUYURUQ
──────────────────────────────────────────────────────────────────────────────
Əvvəl hər başlanğıc nasazlığı eyni fatal ekrana, eyni mətnlə düşürdü. Yəni
«server müvəqqəti əlçatmazdır» ilə «bağlantı ümumiyyətlə konfiqurasiya
edilməyib» istifadəçi üçün eyni görünürdü — birincidə gözləmək, ikincidə isə
ayarları daxil etmək lazımdır və ekran bunu heç cür deməzdi.

Testlər üç halı AYRI-AYRI ölçür:

    1. TENANT bazası əlçatmaz  → izahlı mesaj + «Yenidən Cəhd Et»;
    2. VENDOR/lisenziya əlçatmaz → tətbiq BLOKLANMIR (fail-open);
    3. Credentials yoxdur/yanlışdır → «Bağlantı Ayarları» ekranı.

──────────────────────────────────────────────────────────────────────────────
TƏSNİFAT NİYƏ AYRICA TEST OLUNUR
──────────────────────────────────────────────────────────────────────────────
Səhv təsnifatın qiyməti simmetrik DEYİL: şəbəkə nasazlığını «ayarlar
səhvdir» kimi göstərmək istifadəçini DÜZGÜN dəyərləri dəyişməyə sövq edər və
işləyən konfiqurasiya itər. Ona görə defoltun `DATABASE_UNREACHABLE` olduğu
ayrıca yoxlanılır.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.presentation.composition import (
    StartupError,
    StartupFailureKind,
    classify_connection_failure,
)
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# TƏSNİFAT
# --------------------------------------------------------------------------- #


class _SqlStateError(Exception):
    """`psycopg` istisnalarının `sqlstate` atributunu təqlid edir."""

    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def test_a_missing_configuration_asks_for_settings() -> None:
    """Heç bir mənbə yoxdursa təkrar cəhd MƏNASIZDIR."""
    from src.shared.exceptions import ConfigurationError

    failure = classify_connection_failure(ConfigurationError("mənbə yoxdur"))

    assert failure.kind is StartupFailureKind.CREDENTIALS_MISSING
    assert failure.kind.is_configuration_problem


def test_a_freshly_installed_machine_reaches_the_settings_screen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """SETUP-1 Faza 4: Setup ilə quraşdırılmış, config-siz maşın.

    Bu, müştərinin GÖRDÜYÜ İLK vəziyyətdir: `.exe` `Program Files`-dadır,
    `ProgramData` boşdur, `DATABASE_URL` yoxdur (tətbiq `.env` oxumur).
    Tələb: proqram ÇÖKMƏMƏLİ, aydın şəkildə «Bağlantı Ayarları» ekranına
    yönləndirməlidir — və oradan yazılan fayl `ProgramData`-ya düşməlidir.
    """
    from src.infrastructure.config.connection_file import (
        CONNECTION_FILE_ENV,
        ConnectionSettings,
        save_settings,
    )
    from src.infrastructure.persistence.connection import build_dsn_from_env
    from src.infrastructure.security.encryption import generate_key
    from src.shared.exceptions import ConfigurationError

    # Şifrələmə açarı mühitdən gəlir — DPAPI (Windows API) çağırılmır və test
    # platformadan asılı olmur (`test_connection_file.py`-dakı eyni naxış).
    monkeypatch.setenv("KOMPASOS_FERNET_KEY", generate_key())
    program_data = tmp_path / "ProgramData"
    program_data.mkdir()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv(CONNECTION_FILE_ENV, raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setenv("PROGRAMDATA", str(program_data))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(program_data))
    monkeypatch.setattr(
        "src.infrastructure.config.connection_file.deployment_root",
        lambda: tmp_path / "ProgramFiles",
    )

    with pytest.raises(ConfigurationError) as raised:
        build_dsn_from_env()

    assert classify_connection_failure(raised.value).kind.is_configuration_problem
    assert "Bağlantı Ayarları" in raised.value.user_message

    written = save_settings(
        ConnectionSettings(
            host="db.example",
            port=5432,
            database="postgres",
            username="postgres",
            password="parol",
        )
    )

    assert written == program_data / "KompasOS" / "connection.json"


def test_a_broken_configuration_file_asks_for_settings() -> None:
    """Fayl var, lakin oxunmur — «konfiqurasiya yoxdur»dan FƏRQLİ haldır."""
    from src.infrastructure.config.connection_file import ConnectionFileError

    failure = classify_connection_failure(ConnectionFileError("korlanıb"))

    assert failure.kind is StartupFailureKind.CREDENTIALS_INVALID


@pytest.mark.parametrize("sqlstate", ["28P01", "28000", "3D000"])
def test_authentication_sqlstates_ask_for_settings(sqlstate: str) -> None:
    """Parol/rol/baza adı yanlışdırsa şəbəkəni yoxlamaq kömək etmir."""
    failure = classify_connection_failure(_SqlStateError(sqlstate))

    assert failure.kind is StartupFailureKind.CREDENTIALS_INVALID
    assert failure.context["sqlstate"] == sqlstate


@pytest.mark.parametrize("sqlstate", ["08006", "57P03", ""])
def test_network_failures_stay_retryable(sqlstate: str) -> None:
    """Şəbəkə/server nasazlığı ayarlar ekranına YÖNLƏNDİRMİR."""
    failure = classify_connection_failure(_SqlStateError(sqlstate))

    assert failure.kind is StartupFailureKind.DATABASE_UNREACHABLE
    assert not failure.kind.is_configuration_problem


def test_an_unknown_failure_defaults_to_retry() -> None:
    """Tanınmayan istisna TƏKRAR CƏHD yoluna düşür.

    Defolt istiqamət qəsdən seçilib: təkrar cəhd heç nəyi pozmur, «ayarları
    düzəlt» isə işləyən konfiqurasiyanı pozmağa dəvətdir.
    """
    failure = classify_connection_failure(RuntimeError("naməlum"))

    assert failure.kind is StartupFailureKind.DATABASE_UNREACHABLE
    assert isinstance(failure, StartupError)


def test_the_failure_kind_reaches_the_log() -> None:
    """Dəstək zəngində «hansı ekran göründü?» sualı jurnaldan cavablanmalıdır."""
    failure = classify_connection_failure(_SqlStateError("28P01"))

    assert failure.to_dict()["context"]["failure_kind"] == "CREDENTIALS_INVALID"


# --------------------------------------------------------------------------- #
# HAL 2 — VENDOR/LİSENZİYA ƏLÇATMAZ: TƏTBİQ BLOKLANMIR
# --------------------------------------------------------------------------- #


class _RaisingLicense:
    """Lisenziya bazasına çatmır — hər sorğu istisna atır."""

    def current_state(self) -> Any:
        raise ConnectionError("lisenziya bazası əlçatmaz")


def test_an_unreachable_license_source_does_not_block_the_application() -> None:
    """Yoxlaya bilməmək BLOKLAMA SƏBƏBİ DEYİL (fail-open, bölmə 8).

    Bloklasaydıq, təchizatçının bazasındakı bir nasazlıq BÜTÜN müştərilərin
    mağazalarını eyni anda dayandırardı — yəni mərkəzi nöqtə mərkəzi risqə
    çevrilərdi.
    """
    from src.domain.value_objects.identifiers import TenantId
    from src.presentation.composition import ApplicationContext

    context = ApplicationContext(
        database=None,  # type: ignore[arg-type] — bu yol bazaya toxunmur
        tenant_id=TenantId("00000000-0000-0000-0000-000000000001"),
        license_client=_RaisingLicense(),  # type: ignore[arg-type]
    )

    assert context.license_blocked() is False


def test_an_unverified_license_is_a_warning_not_a_block() -> None:
    """`LICENSE_UNVERIFIED` yalnız xəbərdarlıqdır — offline qrace işləyir."""
    from src.domain.value_objects.licensing import (
        LicenseState,
        Restriction,
        RestrictionKind,
    )

    state = LicenseState(
        snapshot=None,
        restrictions=(
            Restriction(
                kind=RestrictionKind.LICENSE_UNVERIFIED,
                headline_az="Lisenziya yoxlanıla bilmir",
                detail_az="Bazaya çatılmır.",
            ),
        ),
        offline_grace_days_left=9,
    )

    assert state.is_blocked is False
    assert state.has(RestrictionKind.LICENSE_UNVERIFIED)
    assert state.offline_grace_days_left == 9


# --------------------------------------------------------------------------- #
# EKRAN — DÜYMƏLƏR NÖVƏ GÖRƏ GÖRÜNÜR
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_fatal_screen_shows_no_buttons_by_default(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """Köhnə davranış QORUNUR: düymə istənilmədikdə göstərilmir."""
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_a_entry import FatalStartupScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)

    screen = FatalStartupScreen(theme, message="xəta")

    assert not screen.findChildren(QPushButton)


@requires_qt
def test_a_network_failure_offers_only_retry(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """Şəbəkə nasazlığında ayarlar düyməsi GÖSTƏRİLMİR (bax modul başlığı)."""
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_a_entry import FatalStartupScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)

    screen = FatalStartupScreen(theme, message="xəta", retry=True)
    labels = [button.text() for button in screen.findChildren(QPushButton)]

    assert labels == ["Yenidən Cəhd Et"]


@requires_qt
def test_the_customer_screen_shows_nothing_but_retry(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """Görünən ekranda AYARLAR DÜYMƏSİ OLMAMALIDIR (RECOVERY-1 Faza 2).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ DÜYMƏ ÇIXARILDI
    ──────────────────────────────────────────────────────────────────────────
    Əvvəl konfiqurasiya nasazlığında ekran «Bağlantı Ayarları» təklif edirdi.
    Nəticə: mağaza işçisi problemi ÖZÜ «düzəltməyə» çalışır və İŞLƏK
    konfiqurasiyanı poza bilir — sonra həm nasazlıq, həm də səbəbi dəyişmiş
    olur, dəstək isə ikisini birdən araşdırmalı qalır.

    İndi eyni imkan TEXNİKİN əlindədir: `Ctrl+Shift+K` → Bərpa Konsolu
    (`controllers/recovery_console.may_open` qapısı ilə).
    """
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_a_entry import FatalStartupScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)

    screen = FatalStartupScreen(theme, message="xəta", retry=True)
    labels = [button.text() for button in screen.findChildren(QPushButton)]

    assert "Bağlantı Ayarları" not in labels
    assert labels == ["Yenidən Cəhd Et"]


@requires_qt
def test_the_retry_button_emits_its_signal(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_a_entry import FatalStartupScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)

    screen = FatalStartupScreen(theme, message="xəta", retry=True)
    fired: list[bool] = []
    screen.retry_requested.connect(lambda: fired.append(True))

    screen._retry_button.click()

    assert fired == [True]


# --------------------------------------------------------------------------- #
# BAĞLANTI AYARLARI EKRANI
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_settings_screen_rejects_an_empty_host(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_a_entry import ConnectionSettingsScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)

    screen = ConnectionSettingsScreen(theme)
    payloads: list[dict[str, object]] = []
    screen.submitted.connect(payloads.append)

    screen._on_submit()

    assert payloads == []


@requires_qt
def test_the_settings_screen_rejects_an_invalid_port(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """Yanlış port `psycopg`-də «host tapılmadı» kimi görünür — ekranda tutulur."""
    from src.presentation.screens.group_a_entry import ConnectionSettingsScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)

    screen = ConnectionSettingsScreen(theme)
    screen.populate({"host": "db.example.com", "username": "postgres", "database": "postgres"})
    screen._port.set_text("99999")
    payloads: list[dict[str, object]] = []
    screen.submitted.connect(payloads.append)

    screen._on_submit()

    assert payloads == []


@requires_qt
def test_a_valid_form_emits_the_payload(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_a_entry import ConnectionSettingsScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)

    screen = ConnectionSettingsScreen(theme)
    screen.populate({"host": "db.example.com", "username": "postgres", "database": "kompas"})
    screen._password.set_text("gizli")
    payloads: list[dict[str, object]] = []
    screen.submitted.connect(payloads.append)

    screen._on_submit()

    assert len(payloads) == 1
    assert payloads[0]["host"] == "db.example.com"
    assert payloads[0]["port"] == 5432  # boş sahə → defolt
    assert payloads[0]["password"] == "gizli"


# --------------------------------------------------------------------------- #
# KONTROLLER — YOXLAMADAN ÖNCƏ YAZI YOXDUR
# --------------------------------------------------------------------------- #


@pytest.fixture
def _isolated_connection_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from src.infrastructure.config.connection_file import CONNECTION_FILE_ENV
    from src.infrastructure.security.encryption import generate_key

    target = tmp_path / "connection.json"
    monkeypatch.setenv(CONNECTION_FILE_ENV, str(target))
    monkeypatch.setenv("KOMPASOS_FERNET_KEY", generate_key())
    return target


@requires_qt
def test_a_failed_probe_writes_nothing(  # type: ignore[no-untyped-def]
    qtbot, qt_app, _isolated_connection_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Yanlış ayarlar DİSKƏ DÜŞMÜR — testin ƏSAS iddiası budur.

    Yazsaydıq, tətbiq növbəti açılışda yenə eyni fatal ekrana düşərdi və
    istifadəçi artıq «düzəltdim» sanardı.
    """
    from src.infrastructure.persistence import connection as connection_module
    from src.presentation.controllers.connection_settings import ConnectionSettingsController
    from src.presentation.screens.group_a_entry import ConnectionSettingsScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)

    def _fail(dsn: str, *, timeout: int = 10) -> None:
        raise _SqlStateError("28P01")

    monkeypatch.setattr(connection_module, "probe_dsn", _fail)

    saved: list[bool] = []
    screen = ConnectionSettingsScreen(theme)
    ConnectionSettingsController(on_saved=lambda: saved.append(True)).attach(screen)
    screen.populate({"host": "db.example.com", "username": "postgres", "database": "kompas"})
    screen._password.set_text("səhv")

    screen._on_submit()

    assert not _isolated_connection_file.exists()
    assert saved == []


@requires_qt
def test_a_successful_probe_writes_the_file(  # type: ignore[no-untyped-def]
    qtbot, qt_app, _isolated_connection_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.infrastructure.config.connection_file import load_settings
    from src.infrastructure.persistence import connection as connection_module
    from src.presentation.controllers.connection_settings import ConnectionSettingsController
    from src.presentation.screens.group_a_entry import ConnectionSettingsScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)

    monkeypatch.setattr(connection_module, "probe_dsn", lambda dsn, **kwargs: None)

    saved: list[bool] = []
    screen = ConnectionSettingsScreen(theme)
    ConnectionSettingsController(on_saved=lambda: saved.append(True)).attach(screen)
    screen.populate({"host": "db.example.com", "username": "postgres", "database": "kompas"})
    screen._password.set_text("düzgün")

    screen._on_submit()

    assert saved == [True]
    stored = load_settings(_isolated_connection_file)
    assert stored is not None
    assert stored.host == "db.example.com"
    assert stored.password == "düzgün"
    # Parol XAM mətndə YOXDUR (`connection_file.py` zəmanəti burada da ölçülür).
    assert "düzgün" not in _isolated_connection_file.read_text(encoding="utf-8")


@requires_qt
def test_an_empty_password_keeps_the_stored_one(  # type: ignore[no-untyped-def]
    qtbot, qt_app, _isolated_connection_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Boş parol «dəyişmə» deməkdir, «sil» YOX (bax kontrollerin şərhi)."""
    from src.infrastructure.config.connection_file import (
        ConnectionSettings,
        load_settings,
        save_settings,
    )
    from src.infrastructure.persistence import connection as connection_module
    from src.presentation.controllers.connection_settings import ConnectionSettingsController
    from src.presentation.screens.group_a_entry import ConnectionSettingsScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)

    save_settings(
        ConnectionSettings(
            host="köhnə.example.com",
            port=5432,
            database="kompas",
            username="postgres",
            password="köhnə-parol",
        ),
        _isolated_connection_file,
    )
    monkeypatch.setattr(connection_module, "probe_dsn", lambda dsn, **kwargs: None)

    screen = ConnectionSettingsScreen(theme)
    ConnectionSettingsController(on_saved=lambda: None).attach(screen)
    screen._host.set_text("yeni.example.com")

    screen._on_submit()

    stored = load_settings(_isolated_connection_file)
    assert stored is not None
    assert stored.host == "yeni.example.com"
    assert stored.password == "köhnə-parol"


# --------------------------------------------------------------------------- #
# BAĞLANTI — «QURULDU, LAKİN HEÇ KİM ÇAĞIRMIR» SİNFİNDƏN QORUNMA
# --------------------------------------------------------------------------- #
# DB-4 Faza 1-də tam işlək bir modul yazıldı və heç bir istehsalat kodu onu
# idxal etmədi — qüsuru nə lint, nə mypy, nə də test tapdı. Aşağıdakı iki test
# həmin sinfi bu fazada təkrarlanmaqdan saxlayır: ekranın düymələri var, lakin
# `main` növü ötürməsə, istifadəçi onları HEÇ VAXT görməz.


def test_main_does_not_open_the_database_before_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`main._run_gui` bazaya TOXUNMUR — kontekst splash arxasında qurulur.

    ──────────────────────────────────────────────────────────────────────────
    MÜQAVİLƏ NİYƏ KÖÇDÜ
    ──────────────────────────────────────────────────────────────────────────
    Əvvəl `_run_gui` `build_context()`-i ÖZÜ çağırır, `StartupError`-u tutur
    və nəticəni `run()`-a ötürürdü. Nəticə: server əlçatmaz olan maşında
    bağlantı taymautu (15 saniyəyədək) PƏNCƏRƏDƏN ƏVVƏL gedirdi və istifadəçi
    boş ekran görürdü (SETUP-1).

    İndi məsuliyyət `run()`-dadır: splash dərhal göstərilir, kontekst isə fon
    sapında qurulur. Nasazlığın mətni və NÖVÜ itmir — onu
    `test_startup_splash_loading.py` ölçür. Burada ölçülən şey budur ki,
    `_run_gui` bazaya ÜMUMİYYƏTLƏ toxunmur.
    """
    import argparse

    import src.main as main_module
    from src.presentation import app as app_module
    from src.presentation import composition as composition_module

    captured: dict[str, Any] = {}
    opened: list[str] = []

    def _must_not_run(**kwargs: Any) -> Any:  # pragma: no cover - çağırılmamalıdır
        opened.append("build_context")
        raise AssertionError("`_run_gui` bazanı pəncərədən əvvəl açdı")

    def _fake_run(**kwargs: Any) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(composition_module, "build_context", _must_not_run)
    monkeypatch.setattr(app_module, "run", _fake_run)

    args = argparse.Namespace(preview=False, kiosk=False, theme="light")
    assert main_module._run_gui(args) == 0

    assert opened == [], "kontekst hələ də pəncərədən əvvəl qurulur"
    assert captured["context"] is None
    assert captured["startup_error"] == ""
    assert captured["startup_failure_kind"] is None
    # «Yenidən cəhd et» və Bağlantı Ayarları ekranı BUNA bağlıdır — ötürülməsə
    # düymələr ümumiyyətlə göstərilmir (bax `run()` docstring-i).
    assert callable(captured["rebuild_context"])


def test_preview_mode_offers_no_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--preview` bazasız işləyir — «yenidən cəhd et» orada mənasızdır."""
    import argparse

    import src.main as main_module
    from src.presentation import app as app_module

    captured: dict[str, Any] = {}
    monkeypatch.setattr(app_module, "run", lambda **kwargs: captured.update(kwargs) or 0)

    args = argparse.Namespace(preview=True, kiosk=False, theme="light")
    main_module._run_gui(args)

    assert captured["rebuild_context"] is None
    assert captured["startup_failure_kind"] is None


@requires_qt
def test_a_successful_retry_adopts_the_context(qtbot, qt_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Uğurlu təkrar cəhd örtüyü NORMAL axına salır — proses yenidən açılmır."""
    from src.presentation.app import KompasApplication
    from src.presentation.background_task import InlineExecutor
    from src.presentation.theme.tokens import ThemeMode

    application = KompasApplication(qt_app, preview=True, theme_preference=ThemeMode.LIGHT)
    # AÇILIŞ CƏHDİ FON SAPINDADIR (donma düzəlişi) — testdə hadisə dövrəsi
    # gözlənilməsin deyə layihənin `InlineExecutor` naxışı verilir: `run_job`
    # qayıtdıqda nəticə ARTIQ çatdırılmışdır. Sap davranışı ayrıca
    # `test_background_task.py`-da ölçülür; burada ölçülən EKRAN SEÇİMİDİR.
    application._executor = InlineExecutor()
    started: list[bool] = []
    monkeypatch.setattr(application, "start", lambda: started.append(True))
    monkeypatch.setattr("src.presentation.app._build_auth_controller", lambda context: object())

    class _Context:
        tenant_id = "00000000-0000-0000-0000-000000000001"

    application.show_startup_failure(
        message="baza əlçatmazdır",
        kind=StartupFailureKind.DATABASE_UNREACHABLE,
        rebuild=_Context,  # type: ignore[arg-type]
    )
    application._attempt_startup(_Context)  # type: ignore[arg-type]

    assert started == [True]


@requires_qt
def test_a_failed_retry_shows_the_new_reason(qtbot, qt_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """İkinci cəhd BAŞQA səbəblə uğursuz olarsa, ekran YENİ mesajı göstərir.

    Mesaj dəyişmirsə istifadəçi irəlilədiyini görmür — parolu düzəldib şəbəkə
    xətasına düşmək «heç nə dəyişmədi» kimi oxunardı.
    """
    from PySide6.QtWidgets import QPushButton

    from src.presentation.app import KompasApplication
    from src.presentation.background_task import InlineExecutor
    from src.presentation.theme.tokens import ThemeMode

    application = KompasApplication(qt_app, preview=True, theme_preference=ThemeMode.LIGHT)
    # AÇILIŞ CƏHDİ FON SAPINDADIR (donma düzəlişi) — testdə hadisə dövrəsi
    # gözlənilməsin deyə layihənin `InlineExecutor` naxışı verilir: `run_job`
    # qayıtdıqda nəticə ARTIQ çatdırılmışdır. Sap davranışı ayrıca
    # `test_background_task.py`-da ölçülür; burada ölçülən EKRAN SEÇİMİDİR.
    application._executor = InlineExecutor()

    def _rebuild() -> Any:
        raise StartupError(
            "şəbəkə",
            user_message="Bazaya qoşulmaq mümkün olmadı.",
            kind=StartupFailureKind.DATABASE_UNREACHABLE,
        )

    application._attempt_startup(_rebuild)

    labels = [button.text() for button in application._window.findChildren(QPushButton)]
    # Pəncərənin ÖZ düymələri (minimize/maximize/close) mətnsizdir —
    # `text()` boş sətir qaytarır və filtrdən keçmir.
    labels = [label for label in labels if label]
    # Konfiqurasiya problemi DEYİL → ayarlar düyməsi göstərilmir.
    assert labels == ["Yenidən Cəhd Et"]
