"""Paketlənmiş `.exe` rejiminin davranışı (PyInstaller `--onefile --windowed`).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TESTLƏR VACİBDİR
──────────────────────────────────────────────────────────────────────────────
Paketləmə auditində üç qüsur tapıldı və HEÇ BİRİNİ mövcud qapılar tutmurdu,
çünki hamısı yalnız `sys.frozen` doğru olduqda — yəni yalnız real `.exe`
içində — üzə çıxırdı:

1. Arqumentsiz işə salınan `.exe` interfeysi AÇMIRDI: defolt yol özünü-yoxlama
   idi, `--windowed` rejimində konsol olmadığı üçün istifadəçi heç nə görmür,
   proses 1 kodu ilə səssizcə çıxırdı.
2. `Path(__file__).resolve().parents[1]` `--onefile` rejimində bir pillə artıq
   yuxarı qalxır (giriş skripti arxivin KÖKÜNƏ açılır) və `%TEMP%\\database`
   kimi heç vaxt mövcud olmayacaq yol qaytarırdı.
3. Kiosk nəzarətçisi `[sys.executable, "-m", "src.main", ...]` çağırırdı;
   paketlənmiş `.exe` interpretator olmadığı üçün `argparse` "unrecognized
   arguments: -m src.main" verib 2 kodu ilə çıxırdı — nəzarətçi bunu çökmə
   sayıb dərhal restart fırtınası limitinə dəyirdi.

Testlər `sys.frozen`/`sys.executable`-i əvəzləyərək həmin rejimi TAQLİD edir:
real `.exe` qurmadan qərar məntiqi yoxlanılır.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import src.main as main_module
from src.infrastructure.kiosk.watchdog import KioskWatchdog
from src.shared.runtime import bundle_root, deployment_root, is_frozen, relaunch_command

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


@pytest.fixture
def frozen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """`.exe` içində icra rejimini taqlid edir və `.exe`-nin qovluğunu qaytarır."""
    executable = tmp_path / "KompasOS.exe"
    executable.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    yield tmp_path


# --------------------------------------------------------------------------- #
# Rejimin təyini
# --------------------------------------------------------------------------- #


def test_source_execution_is_not_frozen() -> None:
    """Testlər mənbədən işləyir — əks halda bütün digər gözləntilər sürüşür."""
    assert is_frozen() is False
    assert bundle_root() is None


def test_frozen_execution_is_detected(frozen: Path) -> None:
    assert is_frozen() is True


# --------------------------------------------------------------------------- #
# Fayl yolları
# --------------------------------------------------------------------------- #


def test_deployment_root_is_the_repository_root_from_source() -> None:
    """Mənbə rejimində kök repozitoriyadır — `database/` orada axtarılır."""
    assert (deployment_root() / "database" / "schema.sql").exists()


def test_deployment_root_is_next_to_the_executable_when_frozen(frozen: Path) -> None:
    """Paketdə kök `.exe`-nin YANIdır, arxivin müvəqqəti qovluğu DEYİL.

    Qüsur məhz burada idi: `%TEMP%\\database\\schema.sql` yolu çap olunurdu.
    """
    assert deployment_root() == frozen
    assert "Temp" not in str(deployment_root().name)


def test_frozen_self_check_does_not_fail_on_missing_deployment_files(frozen: Path) -> None:
    """`database/` müştəri maşınında yoxdur — bu, nasazlıq sayılmamalıdır.

    Sxem Supabase-i quran tərəf tərəfindən BİR DƏFƏ tətbiq olunur; klient
    tətbiqi `schema.sql`-ı işləmə zamanı ümumiyyətlə oxumur.
    """
    schema = main_module._check_schema_file()
    migrations = main_module._check_migrations()

    assert schema.ok is True
    assert schema.severity == "INFO"
    assert migrations.ok is True
    assert migrations.severity == "INFO"


def test_source_self_check_still_reports_a_missing_schema_as_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Mənbə rejimində faylın yoxluğu natamam repozitoriya deməkdir — ERROR."""
    monkeypatch.setattr(main_module, "deployment_root", lambda: tmp_path)
    monkeypatch.setattr(main_module, "is_frozen", lambda: False)

    result = main_module._check_schema_file()

    assert result.ok is False
    assert result.severity == "ERROR"


def test_dotenv_is_searched_next_to_the_executable(frozen: Path) -> None:
    """`.env` paketə SALINMIR (bölmə 2) — `.exe`-nin yanından oxunur."""
    (frozen / ".env").write_text("KOMPASOS_ENV=PRODUCTION\n", encoding="utf-8")

    result = main_module._check_dotenv(is_production=True)

    assert result is not None
    assert result.name == "dotenv_in_production"


# --------------------------------------------------------------------------- #
# Yenidən işə salma əmri (kiosk nəzarətçisi)
# --------------------------------------------------------------------------- #


def test_relaunch_command_uses_the_module_flag_from_source() -> None:
    assert relaunch_command() == [sys.executable, "-m", "src.main"]


def test_relaunch_command_omits_the_module_flag_when_frozen(frozen: Path) -> None:
    """`.exe` interpretator deyil — `-m src.main` ona arqument kimi çatardı."""
    command = relaunch_command()

    assert command == [str(frozen / "KompasOS.exe")]
    assert "-m" not in command
    assert "src.main" not in command


def test_watchdog_default_command_is_launchable_when_frozen(frozen: Path) -> None:
    """Nəzarətçinin əmri `argparse`-in tanıdığı bayraqlardan ibarət olmalıdır."""
    command = KioskWatchdog().command

    assert command[0] == str(frozen / "KompasOS.exe")
    assert "--gui" in command
    assert "--kiosk" in command
    assert "-m" not in command


# --------------------------------------------------------------------------- #
# Arqumentsiz işə salma → interfeys
# --------------------------------------------------------------------------- #


@pytest.fixture
def quiet_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`main()`-in loglama yan təsirlərini söndürür (test qovluğu çirklənməsin)."""
    monkeypatch.setattr(main_module, "configure_logging", lambda **_: tmp_path)
    monkeypatch.setattr(main_module, "install_global_exception_hook", lambda: None)


@pytest.mark.usefixtures("quiet_main")
def test_frozen_launch_without_arguments_opens_the_gui(
    monkeypatch: pytest.MonkeyPatch, frozen: Path
) -> None:
    """İki dəfə kliklənən `.exe` arqumentsiz gəlir — interfeys AÇILMALIDIR."""
    monkeypatch.setattr(main_module, "is_frozen", lambda: True)
    opened: list[bool] = []
    monkeypatch.setattr(main_module, "_run_gui", lambda _args: opened.append(True) or 0)

    exit_code = main_module.main([])

    assert opened == [True], "Paketlənmiş `.exe` arqumentsiz interfeysi açmalıdır"
    assert exit_code == 0


@pytest.mark.usefixtures("quiet_main")
def test_frozen_launch_with_check_still_runs_the_self_check(
    monkeypatch: pytest.MonkeyPatch, frozen: Path
) -> None:
    """Diaqnostika yolu paketdə də əlçatan qalmalıdır."""
    monkeypatch.setattr(main_module, "is_frozen", lambda: True)
    monkeypatch.setattr(main_module, "_run_gui", lambda _args: pytest.fail("GUI açılmamalıydı"))
    monkeypatch.setattr(main_module, "run_self_check", lambda _c, strict=False: [])

    assert main_module.main(["--check"]) == 0


@pytest.mark.usefixtures("quiet_main")
def test_source_launch_without_arguments_runs_the_self_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mənbə rejimində defolt DƏYİŞMİR — CI məhz bu davranışa arxalanır."""
    monkeypatch.setattr(main_module, "is_frozen", lambda: False)
    monkeypatch.setattr(main_module, "_run_gui", lambda _args: pytest.fail("GUI açılmamalıydı"))
    monkeypatch.setattr(main_module, "run_self_check", lambda _c, strict=False: [])

    assert main_module.main([]) == 0


@pytest.mark.usefixtures("quiet_main")
def test_watchdog_command_is_accepted_by_the_argument_parser(
    monkeypatch: pytest.MonkeyPatch, frozen: Path
) -> None:
    """Nəzarətçinin qurduğu əmr həqiqətən `main()` tərəfindən qəbul edilirmi.

    Bu, "unrecognized arguments" qüsurunun BİRBAŞA reqressiya qapısıdır:
    parser tanımayan bayraq görsə `SystemExit(2)` atardı və nəzarətçi bunu
    sonsuz çökmə dövrü kimi görərdi. Əmr bir mənbədən (`KioskWatchdog`)
    götürülür ki, test onu təkrar yazmasın və ayrıla bilməsin.
    """
    monkeypatch.setattr(main_module, "is_frozen", lambda: True)
    captured: list[argparse.Namespace] = []
    monkeypatch.setattr(main_module, "_run_gui", lambda args: captured.append(args) or 0)

    exit_code = main_module.main(list(KioskWatchdog().command[1:]))

    assert exit_code == 0, "Nəzarətçinin əmri parserdən keçmədi"
    assert captured[0].gui is True
    assert captured[0].kiosk is True
