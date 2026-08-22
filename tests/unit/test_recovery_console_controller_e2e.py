r"""`RecoveryConsoleScreen` ↔ `RecoveryConsoleController` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3)
──────────────────────────────────────────────────────────────────────────────
`test_recovery_console.py` YALNIZ təmiz funksiyaları (`describe_failure`,
`may_open`) ölçür — `RecoveryConsoleController.attach(screen)` heç vaxt REAL
`RecoveryConsoleScreen`-ə bağlanmır, «Bağlantını Test Et», «Yadda Saxla»,
«Bazanı Avtomatik Qur» düymələri heç vaxt REAL klik almır. Bu, məhz bu
konsolun SON ÇARƏ olduğu üçün ən bahalı boşluqdur: baza açılmayanda
quraşdırıcının əlindəki YEGANƏ alət elə bu ekrandır.

`_run()` defolt icraçı ilə (`QtPoolExecutor`, HƏQİQİ sap hovuzu) işləyir —
`RecoveryConsoleController` `executor=` parametrini QƏBUL ETMİR (fərqli olaraq
`SupportInboxController`-dən), ona görə burada network/DB funksiyaları
`monkeypatch` ilə əvəzlənir, sap isə REAL qalır və `qtbot.waitUntil` ilə
gözlənilir.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.presentation.composition import StartupFailureKind
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _screen(theme: Any) -> Any:
    from src.presentation.screens.recovery_console import RecoveryConsoleScreen

    return RecoveryConsoleScreen(theme)


def _wire(theme: Any, *, authenticated: bool = True) -> tuple[Any, Any]:
    from src.presentation.controllers.recovery_console import RecoveryConsoleController

    screen = _screen(theme)
    controller = RecoveryConsoleController(authenticated=authenticated)
    controller.attach(screen)
    return screen, controller


def _fill_connection_fields(screen: Any) -> None:
    screen._host.set_text("db.example.com")
    screen._port.set_text("5432")
    screen._database.set_text("postgres")
    screen._username.set_text("root_user")
    screen._password.set_text("gizli-parol")


def _no_saved_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """`refresh()` (attach zamanı çağırılır) diskə ÇATMASIN — real fayl yoxdur."""
    monkeypatch.setattr("src.infrastructure.config.connection_file.load_settings", lambda: None)


@requires_qt
def test_attach_populates_the_real_fields_from_saved_settings_but_never_the_password(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.infrastructure.config.connection_file import ConnectionSettings

    saved = ConnectionSettings(
        host="prod.supabase.co",
        port=6543,
        database="postgres",
        username="postgres.abcd",
        password="çox-gizli",
    )
    monkeypatch.setattr("src.infrastructure.config.connection_file.load_settings", lambda: saved)

    screen, _controller = _wire(theme)
    qtbot.addWidget(screen)

    assert screen._host.text() == "prod.supabase.co"
    assert screen._port.text() == "6543"
    assert screen._username.text() == "postgres.abcd"
    assert screen._password.text() == "", "Parol EKRANA HEÇ VAXT yüklənməməlidir"


# --------------------------------------------------------------------------- #
# QAYDA B — avtentifikasiyasız rejim, real klik, ŞƏBƏKƏYƏ ÇIXMIR
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_real_test_button_is_blocked_without_a_password_in_bypass_mode(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.recovery_console import (
        _UNAUTHENTICATED_NETWORK_BLOCKED,
    )

    _no_saved_settings(monkeypatch)
    called: list[str] = []
    monkeypatch.setattr(
        "src.infrastructure.persistence.connection.probe_dsn",
        lambda dsn, **_: called.append(dsn),
    )
    screen, controller = _wire(theme, authenticated=False)
    qtbot.addWidget(screen)
    _fill_connection_fields(screen)
    screen._password.set_text("")

    screen._test.click()  # ÇÖKMƏMƏLİDİR, ŞƏBƏKƏYƏ ÇIXMAMALIDIR

    assert called == [], "Bypass rejimində boş parolla ŞƏBƏKƏYƏ ÇIXILMAMALIDIR"
    assert controller._task is None, "Heç bir fon işi başladılmamalıdır"
    assert screen._status.text() == _UNAUTHENTICATED_NETWORK_BLOCKED


@requires_qt
def test_the_real_save_button_is_blocked_without_a_password_in_bypass_mode(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.recovery_console import _UNAUTHENTICATED_SAVE_BLOCKED

    _no_saved_settings(monkeypatch)
    called: list[Any] = []
    monkeypatch.setattr(
        "src.infrastructure.config.connection_file.save_settings",
        lambda settings, path=None: called.append(settings),
    )
    screen, controller = _wire(theme, authenticated=False)
    qtbot.addWidget(screen)
    _fill_connection_fields(screen)
    screen._password.set_text("")

    screen._save.click()  # ÇÖKMƏMƏLİDİR, DİSKƏ YAZMAMALIDIR

    assert called == [], "Bypass rejimində boş parol DİSKƏ YAZILMAMALIDIR"
    assert controller._task is None
    assert screen._status.text() == _UNAUTHENTICATED_SAVE_BLOCKED


@requires_qt
def test_the_real_check_tables_button_is_blocked_in_bypass_mode(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.recovery_console import (
        _UNAUTHENTICATED_NETWORK_BLOCKED,
    )

    _no_saved_settings(monkeypatch)
    screen, controller = _wire(theme, authenticated=False)
    qtbot.addWidget(screen)
    _fill_connection_fields(screen)
    screen._password.set_text("")

    screen._check.click()  # ÇÖKMƏMƏLİDİR

    assert controller._task is None
    assert screen._status.text() == _UNAUTHENTICATED_NETWORK_BLOCKED


@requires_qt
def test_the_real_provision_button_is_blocked_in_bypass_mode_without_elevated_password(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.recovery_console import (
        _UNAUTHENTICATED_NETWORK_BLOCKED,
    )

    _no_saved_settings(monkeypatch)
    screen, controller = _wire(theme, authenticated=False)
    qtbot.addWidget(screen)
    _fill_connection_fields(screen)
    screen._password.set_text("")
    screen._service_role.set_text("")

    screen._provision.click()  # ÇÖKMƏMƏLİDİR

    assert controller._task is None
    assert screen._status.text() == _UNAUTHENTICATED_NETWORK_BLOCKED


@requires_qt
def test_bypass_mode_still_allows_an_elevated_provision_password(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """`elevated` (service_role) sahəsi DİSKDƏN bərpa olunmur — bypass QAYDASINI pozmur."""
    _no_saved_settings(monkeypatch)
    screen, controller = _wire(theme, authenticated=False)
    qtbot.addWidget(screen)
    _fill_connection_fields(screen)
    screen._password.set_text("")
    screen._service_role.set_text("əl-ilə-yazılan-elevasiyalı-parol")

    screen._provision.click()  # BLOKLANMAMALIDIR — elevated sahə doldurulub

    qtbot.waitUntil(lambda: controller._task is not None, timeout=2000)


# --------------------------------------------------------------------------- #
# Real fon işi — REAL sap hovuzu, `qtbot.waitUntil` ilə gözlənilir
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_real_test_button_reports_a_successful_probe(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    _no_saved_settings(monkeypatch)
    seen_dsn: list[str] = []
    monkeypatch.setattr(
        "src.infrastructure.persistence.connection.probe_dsn",
        lambda dsn, **_: seen_dsn.append(dsn),
    )
    screen, controller = _wire(theme)
    qtbot.addWidget(screen)
    _fill_connection_fields(screen)

    screen._test.click()

    qtbot.waitUntil(
        lambda: controller._task is not None and not controller._task.is_running, timeout=5000
    )
    assert len(seen_dsn) == 1
    assert "db.example.com" in seen_dsn[0]
    assert "UĞURLUDUR" in screen._status.text()


@requires_qt
def test_the_real_test_button_reports_a_concrete_failure_not_a_generic_one(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    class _SqlStateError(Exception):
        def __init__(self) -> None:
            super().__init__("password authentication failed")
            self.sqlstate = "28P01"

    def _broken_probe(dsn: str, **_: Any) -> None:
        raise _SqlStateError()

    _no_saved_settings(monkeypatch)
    monkeypatch.setattr("src.infrastructure.persistence.connection.probe_dsn", _broken_probe)
    screen, controller = _wire(theme)
    qtbot.addWidget(screen)
    _fill_connection_fields(screen)

    screen._test.click()  # ÇÖKMƏMƏLİDİR

    qtbot.waitUntil(
        lambda: controller._task is not None and not controller._task.is_running, timeout=5000
    )
    assert "28P01" in screen._status.text()
    assert "parol" in screen._status.text().lower() or "açar" in screen._status.text().lower()


@requires_qt
def test_the_real_save_button_writes_through_the_real_widget_values(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    _no_saved_settings(monkeypatch)
    saved: list[Any] = []

    def _fake_save(settings: Any, path: Any = None) -> str:
        saved.append(settings)
        return "yaddaş-yolu"

    monkeypatch.setattr("src.infrastructure.config.connection_file.save_settings", _fake_save)
    screen, controller = _wire(theme)
    qtbot.addWidget(screen)
    _fill_connection_fields(screen)

    screen._save.click()

    qtbot.waitUntil(
        lambda: controller._task is not None and not controller._task.is_running, timeout=5000
    )
    assert len(saved) == 1
    assert saved[0].host == "db.example.com"
    assert saved[0].username == "root_user"
    assert saved[0].password == "gizli-parol"


@requires_qt
def test_the_real_provision_button_asks_for_confirmation_on_populated_database(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Real klik → real fon iş → real `_confirmation` sahəsi görünür olur."""

    class _State:
        requires_confirmation = True
        populated_tables = (("employees", 12),)

        def accepts(self, confirmation: str) -> bool:
            return confirmation.strip().upper() == "QUR"

    monkeypatch.setattr("psycopg.connect", lambda *a, **k: _FakeConnCtx())
    monkeypatch.setattr(
        "src.infrastructure.persistence.provisioning.inspect_database", lambda cur: _State()
    )
    _no_saved_settings(monkeypatch)
    screen, controller = _wire(theme)
    qtbot.addWidget(screen)
    screen.show()
    _fill_connection_fields(screen)
    screen._service_role.set_text("elevasiyalı-parol")

    screen._provision.click()

    qtbot.waitUntil(
        lambda: controller._task is not None and not controller._task.is_running, timeout=5000
    )
    assert screen._confirmation.isVisible() is True
    assert "DİQQƏT" in screen._status.text()
    # Elevasiyalı açar EKRANDAN dərhal silinir (nəticə gözlənilərkən belə).
    assert screen._service_role.text() == ""


class _FakeCursor:
    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeConnCtx:
    def __enter__(self) -> _FakeConnCtx:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return _FakeCursor()


# --------------------------------------------------------------------------- #
# `Esc` və «Bağla» — real qısayol, real klik
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_real_escape_key_closes_the_console(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    _no_saved_settings(monkeypatch)
    screen, _controller = _wire(theme)
    qtbot.addWidget(screen)
    closed: list[bool] = []
    screen.closed.connect(lambda: closed.append(True))

    qtbot.keyClick(screen, Qt.Key.Key_Escape)

    assert closed == [True]


@requires_qt
def test_the_real_close_button_closes_the_console(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    _no_saved_settings(monkeypatch)
    screen, _controller = _wire(theme)
    qtbot.addWidget(screen)
    closed: list[bool] = []
    screen.closed.connect(lambda: closed.append(True))

    screen._close.click()

    assert closed == [True]


# --------------------------------------------------------------------------- #
# Giriş qapısı — `may_open`, real aktor modeli
# --------------------------------------------------------------------------- #


class _Position:
    def __init__(self, role: Any) -> None:
        self.effective_system_role = role
        self.code = str(getattr(role, "value", role))


class _Actor:
    def __init__(self, *, flags: set[str], role: Any) -> None:
        self._flags = flags
        self.position = _Position(role)
        self.id = "aktor"

    def has_permission(self, flag: str, *, now: Any = None) -> bool:
        return flag in self._flags


def test_a_root_without_the_flag_is_denied_even_though_the_role_matches() -> None:
    """Rol KİFAYƏT ETMİR — `can_switch_db` flag-i AYRICA tələb olunur."""
    from src.domain.value_objects.authorization import SystemRole
    from src.presentation.controllers.recovery_console import may_open

    actor = _Actor(flags=set(), role=SystemRole.ROOT)

    assert may_open(actor=actor, configured=True) is False


def test_a_ceo_with_the_flag_is_still_denied_by_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """`can_switch_db` `HardlockLevel.ROOT_ONLY` daşıyır — CEO belə çatmır."""
    from src.domain.value_objects.authorization import SystemRole
    from src.presentation.controllers.recovery_console import SWITCH_DB_FLAG, may_open

    actor = _Actor(flags={SWITCH_DB_FLAG}, role=SystemRole.CEO)

    assert may_open(actor=actor, configured=True) is False


def test_a_credentials_invalid_failure_does_not_bypass_the_gate() -> None:
    """Baza İŞLƏKDİR, saxlanmış parol səhvdir — toyuq-yumurta arqumenti KEÇƏRSİZDİR."""
    from src.presentation.controllers.recovery_console import may_open

    assert (
        may_open(
            actor=None,
            configured=True,
            startup_failure_kind=StartupFailureKind.CREDENTIALS_INVALID,
        )
        is False
    )
