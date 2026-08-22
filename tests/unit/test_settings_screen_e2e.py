"""`SettingsScreen` ↔ `SettingsController` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, üçüncü beşlik — istifadəçi ekranları)
──────────────────────────────────────────────────────────────────────────────
`test_settings_controller.py` `SettingsController`-i `_FakeScreen` sinif
sahtəsi ilə ölçür — REAL `SettingsScreen`, REAL bildiriş açarları (`ToggleSwitch`)
və REAL "Yadda Saxla"/"Şifrəni Dəyiş"/"Hamısını Bağla" düymələri heç vaxt
qurulmur. Burada onların HAMISI real klikllə sınanır.

Xüsusilə "Şifrəni Dəyiş" və "Hamısını Bağla" — ikisi də `_inform()` vasitəsilə
STATİK `QMessageBox.information(...)` çağırır (bax `controllers/settings.py`).
Bu çağırış heç bir mövcud testdə YOXDUR: `test_settings_controller.py`-nin son
qeydi (fayl sonu) məhz bunu izah edir — "screen PARAMETRİ REAL QWidget olmalıdır"
deyə əlavə Qt-asılı test YARADILMAYIB. Bu fayl həmin boşluğu dolduran YERDİR.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _click(widget: Any, text: str) -> None:
    from PySide6.QtWidgets import QPushButton

    button = next(b for b in widget.findChildren(QPushButton) if b.text() == text)
    button.click()


@pytest.fixture(autouse=True)
def _messages(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """`QMessageBox.information(...)` HƏR "Yadda Saxla" uğurunda da çağırılır
    (`_inform`, `controllers/settings.py`) — real modal `exec()`-i BAĞLAMASA
    test sapı əbədi asılardı (`test_tasks_screen_e2e.py`-dəki eyni naxış)."""
    from PySide6.QtWidgets import QMessageBox

    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda parent, title, message, *a, **k: captured.append((title, message))),
    )
    return captured


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _Preferences:
    def __init__(
        self,
        *,
        prefs: dict[str, bool] | None = None,
        load_failure: Exception | None = None,
        save_failure: Exception | None = None,
    ) -> None:
        self._prefs = prefs or {
            "pending_requests": True,
            "server_alerts": True,
            "daily_digest": True,
        }
        self.load_failure = load_failure
        self.save_failure = save_failure
        self.saved: dict[str, bool] | None = None

    def notification_prefs(self, _employee_id: Any) -> dict[str, bool]:
        if self.load_failure is not None:
            raise self.load_failure
        return dict(self._prefs)

    def set_notification_prefs(self, _employee_id: Any, prefs: dict[str, bool]) -> None:
        if self.save_failure is not None:
            raise self.save_failure
        self.saved = prefs


class _Row:
    def __init__(self, *, revoked_at: Any, expires_at: Any) -> None:
        self.revoked_at = revoked_at
        self.expires_at = expires_at


class _AuthSessionsRepo:
    def __init__(self, rows: list[_Row] | None = None) -> None:
        self._rows = rows or []

    def list_recent_for_user(self, _tenant_id: Any, _employee_id: Any) -> list[_Row]:
        return list(self._rows)


class _Uow:
    def __init__(self, auth_sessions: _AuthSessionsRepo) -> None:
        self._auth_sessions = auth_sessions

    def repository(self, name: str) -> Any:
        assert name == "auth_sessions"
        return self._auth_sessions


class _Session:
    def __init__(self, preferences: _Preferences, auth_sessions: _AuthSessionsRepo) -> None:
        self.tenant_id = TENANT
        self.preferences = preferences
        self.uow = _Uow(auth_sessions)
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Clock:
    def now(self) -> Any:
        from datetime import UTC, datetime

        return datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


class _Context:
    def __init__(
        self, preferences: _Preferences, *, auth_sessions: _AuthSessionsRepo | None = None
    ) -> None:
        self._preferences = preferences
        self._auth_sessions = auth_sessions or _AuthSessionsRepo()
        self.clock = _Clock()
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(self._preferences, self._auth_sessions)
        self.sessions.append(created)
        yield created


class _Actor:
    id = ACTOR_ID


def _attach(context: Any, theme: Any, *, qtbot: Any) -> Any:
    from src.presentation.controllers.settings import SettingsController
    from src.presentation.screens.group_d import SettingsScreen

    screen = SettingsScreen(theme)
    qtbot.addWidget(screen)
    SettingsController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    return screen


# --------------------------------------------------------------------------- #
# 1. Real "Yadda Saxla" — real ToggleSwitch klikləri yazı yoluna çatır
# --------------------------------------------------------------------------- #


@requires_qt
def test_toggling_a_real_switch_and_saving_writes_the_new_state(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    preferences = _Preferences()
    context = _Context(preferences)
    screen = _attach(context, theme, qtbot=qtbot)

    # Konstruktordan sonra `refresh()` REAL sorğunu icra edib toggle-ları
    # doldurub — indi istifadəçi "Server xəbərdarlıqları" açarını REAL
    # klikllə söndürür.
    toggle = screen._notification_toggles["server_alerts"]
    toggle.setChecked(False)

    _click(screen, "Yadda Saxla")

    assert preferences.saved is not None
    assert preferences.saved["server_alerts"] is False
    assert preferences.saved["pending_requests"] is True  # digər açar TOXUNULMAYIB
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_save_failure_from_a_non_kompasos_exception_is_visible_not_swallowed(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """UI-2 nəzarəti REAL widget ilə: `psycopg`-in çılpaq xətası real ekranda görünür."""

    class _OperationalError(Exception):
        pass

    preferences = _Preferences(save_failure=_OperationalError("connection lost"))
    context = _Context(preferences)
    screen = _attach(context, theme, qtbot=qtbot)

    _click(screen, "Yadda Saxla")  # ÇÖKMƏMƏLİDİR

    assert preferences.saved is None
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_a_load_failure_shows_the_section_error_banner_on_a_real_screen(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`refresh()`-in geniş tutucusu — real ekranda banner GÖRÜNÜR."""

    class _OperationalError(Exception):
        pass

    preferences = _Preferences(load_failure=_OperationalError("pool exhausted"))
    context = _Context(preferences)
    screen = _attach(context, theme, qtbot=qtbot)

    assert "Bildiriş tərcihləri" in screen.section_errors()
    # D3-03 — Təhlükəsizlik bölməsi AYRI sessiyada oxunur, bu bölmənin
    # uğursuzluğu ONU maskalamamalıdır (Qrup G qaydası).
    assert screen._sessions_label.text() == "Aktiv sessiya yoxdur."


# --------------------------------------------------------------------------- #
# 2. Real "Şifrəni Dəyiş" / "Hamısını Bağla" — statik `QMessageBox.information`
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_change_password_shows_the_real_informational_dialog(
    qtbot, theme, _messages: list[tuple[str, str]]
) -> None:  # type: ignore[no-untyped-def]
    context = _Context(_Preferences())
    screen = _attach(context, theme, qtbot=qtbot)

    _click(screen, "Şifrəni Dəyiş")

    assert len(_messages) == 1
    title, message = _messages[0]
    assert title == "Şifrə"
    assert "administrator" in message.lower()


@requires_qt
def test_clicking_close_all_sessions_with_none_active_says_so(
    qtbot, theme, _messages: list[tuple[str, str]]
) -> None:  # type: ignore[no-untyped-def]
    context = _Context(_Preferences())
    screen = _attach(context, theme, qtbot=qtbot)

    _click(screen, "Hamısını Bağla")

    assert _messages[-1] == ("Sessiyalar", "Başqa aktiv sessiya yoxdur.")


@requires_qt
def test_clicking_close_all_sessions_with_active_ones_reports_the_count_and_redirects(
    qtbot, theme, _messages: list[tuple[str, str]]
) -> None:  # type: ignore[no-untyped-def]
    """SEC-5: bu düymə LƏĞV ETMİR — istifadəçini «Profil»ə yönləndirir (bax modul başlığı)."""
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    rows = [_Row(revoked_at=None, expires_at=now + timedelta(hours=8))]
    context = _Context(_Preferences(), auth_sessions=_AuthSessionsRepo(rows))
    screen = _attach(context, theme, qtbot=qtbot)

    _click(screen, "Hamısını Bağla")

    title, message = _messages[-1]
    assert title == "Sessiyalar"
    assert "1 aktiv sessiya var" in message
    assert "Profil" in message  # düzgün yola yönləndirir, ləğv İDDİA ETMİR


# --------------------------------------------------------------------------- #
# 3. Real tema düymələri — ekstremal/toxunulmamış hal ÇÖKMƏMƏLİDİR
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_a_theme_button_does_not_crash_even_though_no_controller_listens(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """`SettingsController.attach()` `theme_selected`-i BAĞLAMIR (bax modul başlığı,
    tema `app.py::_on_theme_selected`-də dərhal tətbiq olunur) — real klik yenə
    ÇÖKMƏMƏLİDİR, sadəcə kontroller tərəfindən eşidilmir."""
    context = _Context(_Preferences())
    screen = _attach(context, theme, qtbot=qtbot)

    screen.select_theme("dark")  # real metod — siqnal yayılır, heç kim udmasa da OK

    assert screen._theme_buttons["dark"].isChecked()
