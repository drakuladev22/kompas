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
4. Yerli SQLite faylları CARİ QOVLUĞA nisbi yazılırdı (`./data/*.db`). `.exe`
   Start menyusundan `C:\\Windows\\System32`, kiosk nəzarətçisindən isə
   `C:\\Program Files\\KompasOS` qovluğu ilə açılır — hər ikisi standart
   istifadəçi üçün yazıla bilmir və ilk sübut şəkli/ilk offline yazı
   `unable to open database file` ilə itirdi.
5. Plugin sandbox-u alt-prosesi `sys.executable` ilə açırdı; paketdə bu,
   `KompasOS.exe`-dir və `-I -S plugin.py` ona adi arqument kimi çatır.

Testlər `sys.frozen`/`sys.executable`-i əvəzləyərək həmin rejimi TAQLİD edir:
real `.exe` qurmadan qərar məntiqi yoxlanılır. 4-cü qüsur üçün üstəlik CARİ
QOVLUQ dəyişdirilir — yolun ondan asılı OLMADIĞINI sübut etmək üçün.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

import src.infrastructure.offline.buffer as buffer_module
import src.infrastructure.persistence.migration as migration_module
import src.infrastructure.plugins.sandbox as sandbox_module
import src.infrastructure.security.encryption as encryption_module
import src.main as main_module
import src.presentation.composition as composition_module
from src.infrastructure.kiosk.watchdog import KioskWatchdog
from src.infrastructure.plugins import (
    PluginCapability,
    PluginError,
    PluginManifest,
    PluginRequest,
    PluginSandbox,
)
from src.shared.data_paths import resolve_data_file
from src.shared.runtime import (
    PLUGIN_PYTHON_ENV,
    bundle_root,
    deployment_root,
    is_frozen,
    plugin_interpreter,
    relaunch_command,
)

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


# --------------------------------------------------------------------------- #
# Yerli SQLite yolları (offline bufer + sübut növbəsi)
# --------------------------------------------------------------------------- #


@pytest.fixture
def user_data_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """İstifadəçi məlumat qovluğunu testin müvəqqəti qovluğuna yönləndirir.

    Hər iki dəyişən (Windows `LOCALAPPDATA` və POSIX `XDG_DATA_HOME`) EYNİ
    kökə baxır ki, gözlənilən nəticə işlədiyimiz OS-dən asılı olmasın.
    Mövcud `KOMPASOS_*` açarları silinir — testin nəticəsi geliştiricinin
    `.env` faylından asılı OLMAMALIDIR.
    """
    root = tmp_path / "AppData" / "Local"
    root.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(root))
    monkeypatch.setenv("XDG_DATA_HOME", str(root))
    monkeypatch.delenv("KOMPASOS_SQLITE_PATH", raising=False)
    monkeypatch.delenv("KOMPASOS_EVIDENCE_QUEUE_PATH", raising=False)
    return root / "KompasOS" / "data"


def _workdir(tmp_path: Path, name: str) -> Path:
    """Yazıla bilməyən sistem qovluğunun rolunu oynayan boş qovluq."""
    path = tmp_path / name
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.usefixtures("user_data_root")
def test_configured_sqlite_path_is_used_exactly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """MÖVCUD DAVRANIŞ: mühit dəyişəni təyin olunubsa yol DƏYİŞMİR."""
    target = tmp_path / "xüsusi" / "buffer.db"
    monkeypatch.setenv("KOMPASOS_SQLITE_PATH", str(target))

    assert resolve_data_file("KOMPASOS_SQLITE_PATH", "offline_buffer.db") == target


@pytest.mark.usefixtures("user_data_root")
def test_configured_evidence_queue_path_is_used_exactly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "xüsusi" / "növbə.db"
    monkeypatch.setenv("KOMPASOS_EVIDENCE_QUEUE_PATH", str(target))

    assert resolve_data_file("KOMPASOS_EVIDENCE_QUEUE_PATH", "evidence_uploads.db") == target


def test_blank_environment_variable_counts_as_unset(
    monkeypatch: pytest.MonkeyPatch, user_data_root: Path
) -> None:
    """`.env` faylında boş sətir adi haldır — o, yolu boşluğa çevirməməlidir."""
    monkeypatch.setenv("KOMPASOS_SQLITE_PATH", "   ")

    assert resolve_data_file("KOMPASOS_SQLITE_PATH", "offline_buffer.db") == (
        user_data_root / "offline_buffer.db"
    )


def test_default_path_does_not_depend_on_the_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, user_data_root: Path
) -> None:
    """QÜSURUN BİRBAŞA QAPISI: CWD dəyişir, yol DƏYİŞMİR.

    Köhnə davranışda `Path("./data/offline_buffer.db")` iki fərqli CWD-də iki
    fərqli (və yazıla bilməyən) yol verirdi.
    """
    system32 = _workdir(tmp_path, "System32")
    program_files = _workdir(tmp_path, "Program Files/KompasOS")

    monkeypatch.chdir(system32)
    from_system32 = resolve_data_file("KOMPASOS_SQLITE_PATH", "offline_buffer.db")
    monkeypatch.chdir(program_files)
    from_program_files = resolve_data_file("KOMPASOS_SQLITE_PATH", "offline_buffer.db")

    assert from_system32 == from_program_files == user_data_root / "offline_buffer.db"
    assert from_system32.is_absolute()
    assert str(system32) not in str(from_system32)
    assert str(program_files) not in str(from_program_files)


def test_existing_legacy_file_is_reused_and_never_moved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, user_data_root: Path
) -> None:
    """GERİYƏ UYĞUNLUQ: köhnə `./data/*.db` varsa göndərilməmiş yazı itmir.

    Köçürmə QƏSDƏN edilmir (bax `shared/data_paths.py` başlığı): fayl yerində
    qalır, məzmunu toxunulmaz olur və yeni qovluqda ikinci nüsxə yaranmır.
    """
    installation = _workdir(tmp_path, "köhnə-quraşdırma")
    legacy = installation / "data" / "offline_buffer.db"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"SQLite format 3\x00")
    monkeypatch.chdir(installation)

    resolved = resolve_data_file("KOMPASOS_SQLITE_PATH", "offline_buffer.db")

    assert resolved == Path("data") / "offline_buffer.db"
    assert resolved.resolve() == legacy.resolve()
    assert legacy.read_bytes() == b"SQLite format 3\x00", "Köhnə fayl toxunulmaz qalmalıdır"
    assert not (user_data_root / "offline_buffer.db").exists()


def test_offline_buffer_default_lands_in_the_user_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, user_data_root: Path
) -> None:
    """Kompozisiya kökü həqiqətən yeni yolu ötürürmü (bağlantı yoxlanışı)."""
    captured: list[Path] = []

    class _FakeBuffer:
        def __init__(self, path: Path, *, encryption: object) -> None:
            captured.append(path)

    class _FakeEncryption:
        """Şifrələmə açarı testin mövzusu deyil — konstruktoru sadəcə boş qalır."""

    monkeypatch.setattr(buffer_module, "OfflineBuffer", _FakeBuffer)
    monkeypatch.setattr(encryption_module, "EncryptionService", _FakeEncryption)
    monkeypatch.setattr(migration_module, "BufferDrainAdapter", lambda buffer: buffer)
    monkeypatch.chdir(_workdir(tmp_path, "System32"))

    composition_module._LazyBufferDrain()._ensure()

    assert captured == [user_data_root / "offline_buffer.db"]


class _UnreachableDatabase:
    """Sessiya AÇILMAYAN saxta baza — sübut növbəsi ondan asılı olmamalıdır."""

    def unit_of_work(self, *_args: object, **_kwargs: object) -> object:
        raise RuntimeError("baza əlçatmazdır")


def test_evidence_queue_is_created_in_the_user_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, user_data_root: Path
) -> None:
    """İLK SÜBUT ŞƏKLİ ANI: fayl həqiqətən yaradıla bilirmi.

    Test SQLite faylını REAL yaradır, çünki qüsur məhz yazma anında üzə
    çıxırdı — yolun sətir kimi düzgün olması kifayət deyil.
    """
    workdir = _workdir(tmp_path, "System32")
    monkeypatch.chdir(workdir)
    context = composition_module.ApplicationContext(
        database=_UnreachableDatabase(),  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),  # type: ignore[arg-type]
    )

    queue: Any = context.evidence_queue()
    try:
        assert (user_data_root / "evidence_uploads.db").is_file()
        assert not (workdir / "data").exists(), "Cari qovluğa heç nə yazılmamalıdır"
    finally:
        queue.close()


def test_evidence_queue_honours_the_environment_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, user_data_root: Path
) -> None:
    """MÖVCUD DAVRANIŞ: açar təyin olunubsa növbə məhz orada qurulur."""
    target = tmp_path / "növbə" / "uploads.db"
    monkeypatch.setenv("KOMPASOS_EVIDENCE_QUEUE_PATH", str(target))
    context = composition_module.ApplicationContext(
        database=_UnreachableDatabase(),  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),  # type: ignore[arg-type]
    )

    queue: Any = context.evidence_queue()
    try:
        assert target.is_file()
        assert not (user_data_root / "evidence_uploads.db").exists()
    finally:
        queue.close()


# --------------------------------------------------------------------------- #
# Plugin sandbox-unun interpretatoru
# --------------------------------------------------------------------------- #


def _interpreter_names() -> tuple[str, ...]:
    return ("python.exe",) if sys.platform == "win32" else ("python3", "python")


@pytest.fixture
def no_configured_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    """`KOMPASOS_PLUGIN_PYTHON` təyin olunmamış hal (defolt axtarış yolu)."""
    monkeypatch.delenv(PLUGIN_PYTHON_ENV, raising=False)


def _sandbox(plugin_path: Path) -> PluginSandbox:
    manifest = PluginManifest(
        name="test-plugin",
        version="1.0.0",
        publisher="KompasOS Rəsmi",
        capabilities=frozenset({PluginCapability.REPORT_TRANSFORM}),
        entry_point="main.py",
    )
    return PluginSandbox(manifest=manifest, plugin_path=plugin_path)


@pytest.mark.usefixtures("no_configured_interpreter")
def test_sandbox_command_is_unchanged_from_source(tmp_path: Path) -> None:
    """Mənbə rejimində əmr HƏRFƏN köhnəsi ilə eynidir — reqressiya qapısı."""
    plugin = tmp_path / "main.py"
    plugin.write_text("print('{}')\n", encoding="utf-8")

    assert _sandbox(plugin)._command() == [sys.executable, "-I", "-S", str(plugin)]


@pytest.mark.usefixtures("no_configured_interpreter")
def test_frozen_sandbox_never_uses_the_executable(frozen: Path, tmp_path: Path) -> None:
    """`.exe` interpretator deyil — o, əmrin başına DÜŞMƏMƏLİDİR."""
    bundled = frozen / "python" / _interpreter_names()[0]
    bundled.parent.mkdir()
    bundled.write_bytes(b"")
    plugin = tmp_path / "main.py"
    plugin.write_text("print('{}')\n", encoding="utf-8")

    command = _sandbox(plugin)._command()

    assert command[0] == str(bundled)
    assert command[0] != str(frozen / "KompasOS.exe")
    assert command[1:3] == ["-I", "-S"], "İzolyasiya bayraqları qalmalıdır"


def test_frozen_sandbox_prefers_the_configured_interpreter(
    monkeypatch: pytest.MonkeyPatch, frozen: Path, tmp_path: Path
) -> None:
    """Quraşdırıcının açıq göstərdiyi interpretator axtarışdan üstündür."""
    chosen = tmp_path / "Python313" / _interpreter_names()[0]
    chosen.parent.mkdir()
    chosen.write_bytes(b"")
    monkeypatch.setenv(PLUGIN_PYTHON_ENV, str(chosen))
    plugin = tmp_path / "main.py"
    plugin.write_text("print('{}')\n", encoding="utf-8")

    assert _sandbox(plugin)._command()[0] == str(chosen)


@pytest.mark.usefixtures("frozen", "no_configured_interpreter")
def test_frozen_sandbox_refuses_when_no_interpreter_is_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """İnterpretator yoxdursa alt-proses ÜMUMİYYƏTLƏ açılmır.

    Köhnə davranışda `KompasOS.exe -I -S plugin.py` işə düşürdü: ya `argparse`
    2 kodu ilə çıxırdı, ya da tətbiqin ikinci nüsxəsi açılırdı. İkisi də
    istifadəçiyə "plugin xəta ilə bitdi (kod 2)" kimi görünürdü.
    """
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        sandbox_module.subprocess, "run", lambda *_a, **_k: pytest.fail("Alt-proses açılmamalıydı")
    )
    plugin = tmp_path / "main.py"
    plugin.write_text("print('{}')\n", encoding="utf-8")

    with pytest.raises(PluginError, match="interpretator"):
        _sandbox(plugin).invoke(
            PluginRequest(capability=PluginCapability.REPORT_TRANSFORM, payload={})
        )


@pytest.mark.usefixtures("no_configured_interpreter")
def test_plugin_interpreter_from_source_is_the_running_python() -> None:
    assert plugin_interpreter() == sys.executable


@pytest.mark.usefixtures("frozen", "no_configured_interpreter")
def test_plugin_interpreter_is_none_when_the_package_has_no_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tapılmayan interpretator SÜKUTLA `sys.executable`-a çevrilməməlidir."""
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    assert plugin_interpreter() is None


@pytest.mark.usefixtures("frozen", "no_configured_interpreter")
def test_windows_store_stub_is_not_accepted_as_interpreter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`WindowsApps\\python.exe` Store yönləndiricisidir — 9009 ilə çıxır."""
    stub = "C:\\Users\\kassir\\AppData\\Local\\Microsoft\\WindowsApps\\python.exe"
    monkeypatch.setattr(shutil, "which", lambda _name: stub)

    assert plugin_interpreter() is None


@pytest.mark.usefixtures("frozen", "no_configured_interpreter")
def test_system_python_is_accepted_when_the_package_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Paketin yanında interpretator yoxdursa sistemdəki işlədilir."""
    system_python = "C:\\Python313\\python.exe"
    monkeypatch.setattr(shutil, "which", lambda _name: system_python)

    assert plugin_interpreter() == system_python
