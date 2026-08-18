"""«Bağlantı Ayarları» ekranının Diaqnostika bölməsi (SETUP-1 Faza 2).

──────────────────────────────────────────────────────────────────────────────
NƏYİ QORUYUR
──────────────────────────────────────────────────────────────────────────────
Bu ekran məhz baza əlçatmaz olanda açılır — yəni quraşdırıcı orada dayanıb və
«proqram hansı faylı oxuyur?» sualını verir. `Setup.exe` ilə paylanan
quraşdırmada cavab AŞKAR DEYİL: `.exe` `Program Files`-dadır, konfiqurasiya
isə `ProgramData`-da; ikisi ayrı yerdədir və heç bir ekranda yazılmırdı.

Nəticə praktik idi: quraşdırıcı config faylını `.exe`-nin yanına qoyur, proqram
onu ProgramData-da axtarır və heç kim səhvi görmür. Ona görə üç yol EKRANDA
yazılır — konfiqurasiya, log, yerli məlumat.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


@pytest.fixture
def shared_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Bütün yollar testin müvəqqəti qovluğuna bağlanır."""
    from src.infrastructure.config.connection_file import CONNECTION_FILE_ENV

    root = tmp_path / "ProgramData"
    root.mkdir()
    monkeypatch.setenv("PROGRAMDATA", str(root))
    monkeypatch.setenv("XDG_DATA_HOME", str(root))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.delenv(CONNECTION_FILE_ENV, raising=False)
    monkeypatch.delenv("KOMPASOS_LOG_DIR", raising=False)
    monkeypatch.delenv("KOMPASOS_SQLITE_PATH", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    return root


def test_the_diagnostic_rows_name_all_three_locations(shared_paths: Path) -> None:
    """Üç yol da göstərilir — biri çatışmasa sual yenə cavabsız qalardı."""
    from src.presentation.controllers.connection_settings import diagnostic_paths

    labels = [label for label, _ in diagnostic_paths()]

    assert labels == ["Konfiqurasiya faylı", "Log qovluğu", "Yerli məlumat"]


def test_a_missing_config_shows_where_it_will_be_written(shared_paths: Path) -> None:
    """«Tapılmadı» tək başına faydasızdır — quraşdırıcıya YER lazımdır."""
    from src.presentation.controllers.connection_settings import diagnostic_paths

    value = dict(diagnostic_paths())["Konfiqurasiya faylı"]

    assert "tapılmadı" in value.lower()
    assert str(shared_paths / "KompasOS" / "connection.json") in value


def test_an_existing_config_shows_the_file_actually_used(shared_paths: Path) -> None:
    """İki nüsxə olan maşında hansının işlədiyi EKRANDA görünməlidir."""
    from src.presentation.controllers.connection_settings import diagnostic_paths

    target = shared_paths / "KompasOS" / "connection.json"
    target.parent.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")

    value = dict(diagnostic_paths())["Konfiqurasiya faylı"]

    assert value == str(target)


def test_the_log_and_data_rows_point_at_program_data(shared_paths: Path) -> None:
    """`Program Files`-a yazmaq mümkün deyil — yollar ProgramData olmalıdır."""
    from src.presentation.controllers.connection_settings import diagnostic_paths

    rows = dict(diagnostic_paths())

    assert rows["Log qovluğu"] == str(shared_paths / "KompasOS" / "logs")
    assert rows["Yerli məlumat"] == str(shared_paths / "KompasOS" / "data")


@requires_qt
def test_the_screen_renders_every_diagnostic_row(qtbot, shared_paths: Path) -> None:  # type: ignore[no-untyped-def]
    """Setter API-si (CLAUDE.md §6): ekran yolları ÖZÜ hesablamır, göstərir."""
    from src.presentation.screens.group_a_entry import ConnectionSettingsScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    screen = ConnectionSettingsScreen(ThemeManager(preference=ThemeMode.LIGHT))
    qtbot.addWidget(screen)

    screen.set_diagnostics([("Log qovluğu", "C:\\ProgramData\\KompasOS\\logs")])

    assert "C:\\ProgramData\\KompasOS\\logs" in screen._diagnostics.text()
    assert "Log qovluğu" in screen._diagnostics.text()
