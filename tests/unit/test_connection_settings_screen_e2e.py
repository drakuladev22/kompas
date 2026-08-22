"""`ConnectionSettingsScreen` ↔ `ConnectionSettingsController` — REAL Qt e2e.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, üçüncü beşlik — "settings" tapşırığı)
──────────────────────────────────────────────────────────────────────────────
Bu ekranın kontrolleri `tests/` daxilində HEÇ YERDƏ real widget ağacı ilə
sınanmır (yalnız `_probe`/`_on_submit`-in özü, əgər varsa, funksional testlərlə
ölçülmüş ola bilər — burada REAL "Yoxla və Yadda Saxla" düyməsi, REAL sahə
validasiyası (`_on_submit` ekranın ÖZÜNDƏ) və REAL "Parol boş = dəyişmə"
qaydası real klikllə sınanır. Bu ekran GİRİŞDƏN ƏVVƏL açılır (bax sinif
başlığı) — yəni sınaq QAPISI istifadəçinin ilk gördüyü ekranlardan biridir.

`probe_dsn`/`save_settings`/`load_settings` HƏQİQİ şəbəkəyə/fayl sisteminə
toxunur — burada modul-səviyyəli funksiyalar monkeypatch edilir (kontroller
onları `_probe`/`_on_submit`/`_populate`/`_existing_password` daxilindən
funksiya kimi idxal edir, bax `connection_settings.py`).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


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


def _fill(
    screen: Any, *, host: str, port: str, database: str, username: str, password: str
) -> None:
    screen._host.set_text(host)
    screen._port.set_text(port)
    screen._database.set_text(database)
    screen._username.set_text(username)
    screen._password.set_text(password)


def _attach(theme: Any, *, qtbot: Any, on_saved: Any = None) -> Any:
    from src.presentation.controllers.connection_settings import ConnectionSettingsController
    from src.presentation.screens.group_a_entry import ConnectionSettingsScreen

    screen = ConnectionSettingsScreen(theme)
    qtbot.addWidget(screen)
    ConnectionSettingsController(on_saved=on_saved or (lambda: None)).attach(screen)
    return screen


# --------------------------------------------------------------------------- #
# 1. Ekranın ÖZ validasiyası — real klik, real inline xəta
# --------------------------------------------------------------------------- #


@requires_qt
def test_an_empty_host_is_rejected_inline_and_nothing_is_probed(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.infrastructure.persistence import connection as connection_module

    probed: list[str] = []
    monkeypatch.setattr(connection_module, "probe_dsn", probed.append)
    screen = _attach(theme, qtbot=qtbot)
    _fill(screen, host="", port="5432", database="postgres", username="root", password="x")

    _click(screen, "Yoxla və Yadda Saxla")  # ÇÖKMƏMƏLİDİR

    assert screen._host.has_error
    assert probed == []


@requires_qt
def test_a_non_numeric_port_is_rejected_inline(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Port EKRANDA yoxlanılır (bax `_on_submit` şərhi) — `psycopg`-ə heç çatmır."""
    screen = _attach(theme, qtbot=qtbot)
    _fill(
        screen,
        host="db.kompasos.local",
        port="'; DROP TABLE users; --",
        database="postgres",
        username="root",
        password="x",
    )

    _click(screen, "Yoxla və Yadda Saxla")  # ÇÖKMƏMƏLİDİR

    assert screen._port.has_error


@requires_qt
def test_a_port_above_the_valid_range_is_rejected(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    screen = _attach(theme, qtbot=qtbot)
    _fill(
        screen,
        host="db.kompasos.local",
        port="99999",
        database="postgres",
        username="root",
        password="x",
    )

    _click(screen, "Yoxla və Yadda Saxla")  # ÇÖKMƏMƏLİDİR

    assert screen._port.has_error


# --------------------------------------------------------------------------- #
# 2. Real "Yoxla və Yadda Saxla" — sınaq uğursuz olanda YAZILMIR
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_failed_probe_shows_the_classified_reason_and_does_not_save(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.infrastructure.persistence import connection as connection_module
    from src.presentation import composition as composition_module

    def _fail(_dsn: str) -> None:
        raise RuntimeError("connection refused")

    monkeypatch.setattr(connection_module, "probe_dsn", _fail)
    monkeypatch.setattr(
        composition_module,
        "classify_connection_failure",
        lambda exc: type(
            "F", (), {"user_message": "Serverə qoşulmaq mümkün olmadı.", "to_dict": lambda self: {}}
        )(),
    )
    saved: list[str] = []
    monkeypatch.setattr(
        "src.infrastructure.config.connection_file.save_settings", lambda s: saved.append(s.host)
    )

    screen = _attach(theme, qtbot=qtbot)
    _fill(
        screen,
        host="unreachable.kompasos.local",
        port="5432",
        database="postgres",
        username="root",
        password="secret",
    )

    _click(screen, "Yoxla və Yadda Saxla")  # ÇÖKMƏMƏLİDİR

    assert saved == []
    assert screen._status.text() == "Serverə qoşulmaq mümkün olmadı."
    assert screen._status_is_error


@requires_qt
def test_hostile_and_extreme_text_in_the_real_host_field_does_not_crash(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.infrastructure.persistence import connection as connection_module

    probed: list[str] = []

    def _fail(dsn: str) -> None:
        probed.append(dsn)
        raise RuntimeError("connection refused")

    monkeypatch.setattr(connection_module, "probe_dsn", _fail)

    screen = _attach(theme, qtbot=qtbot)
    hostile = "'; DROP TABLE tenants; -- 🔥" + "A" * 5_000
    _fill(screen, host=hostile, port="5432", database="postgres", username="root", password="x")

    _click(screen, "Yoxla və Yadda Saxla")  # ÇÖKMƏMƏLİDİR

    assert len(probed) == 1
    assert hostile in probed[0]  # DSN-in İÇİNDƏ ötürülüb, ayrıca parçalanmayıb


# --------------------------------------------------------------------------- #
# 3. Real uğurlu yol — sınaq keçir, yazılır, geri çağırış işə düşür
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_successful_probe_saves_and_calls_the_on_saved_callback(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.infrastructure.config import connection_file as connection_file_module
    from src.infrastructure.persistence import connection as connection_module

    monkeypatch.setattr(connection_module, "probe_dsn", lambda dsn: None)
    saved: list[Any] = []
    monkeypatch.setattr(connection_file_module, "save_settings", saved.append)

    on_saved_calls: list[str] = []
    screen = _attach(theme, qtbot=qtbot, on_saved=lambda: on_saved_calls.append("called"))
    _fill(
        screen,
        host="db.kompasos.local",
        port="5432",
        database="kompasos",
        username="root",
        password="secret",
    )

    _click(screen, "Yoxla və Yadda Saxla")

    assert len(saved) == 1
    assert saved[0].host == "db.kompasos.local"
    assert saved[0].password == "secret"
    assert on_saved_calls == ["called"]
    assert not screen._status_is_error


@requires_qt
def test_an_empty_password_keeps_the_existing_one_when_available(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Boş parol = «DƏYİŞMƏ», SİLMƏ deyil (bax `_on_submit` şərhi)."""
    from src.infrastructure.config import connection_file as connection_file_module
    from src.infrastructure.persistence import connection as connection_module

    existing = connection_file_module.ConnectionSettings(
        host="old.kompasos.local",
        port=5432,
        database="postgres",
        username="root",
        password="köhnə-parol",
        sslmode="require",
    )
    monkeypatch.setattr(connection_file_module, "load_settings", lambda: existing)
    monkeypatch.setattr(connection_module, "probe_dsn", lambda dsn: None)
    saved: list[Any] = []
    monkeypatch.setattr(connection_file_module, "save_settings", saved.append)

    screen = _attach(theme, qtbot=qtbot)
    _fill(
        screen,
        host="new.kompasos.local",
        port="5432",
        database="postgres",
        username="root",
        password="",
    )

    _click(screen, "Yoxla və Yadda Saxla")

    assert saved[0].password == "köhnə-parol"


@requires_qt
def test_an_empty_password_with_no_existing_one_shows_an_inline_error(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.infrastructure.config import connection_file as connection_file_module

    monkeypatch.setattr(connection_file_module, "load_settings", lambda: None)

    screen = _attach(theme, qtbot=qtbot)
    _fill(
        screen,
        host="db.kompasos.local",
        port="5432",
        database="postgres",
        username="root",
        password="",
    )

    _click(screen, "Yoxla və Yadda Saxla")  # ÇÖKMƏMƏLİDİR

    assert screen._status_is_error
    assert "Parolu daxil edin" in screen._status.text()
