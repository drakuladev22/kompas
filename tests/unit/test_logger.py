"""Struktur JSON loglama testləri (spesifikasiya bölmə 2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.shared.logger import (
    LogChannel,
    configure_logging,
    get_logger,
    redact,
)

pytestmark = pytest.mark.unit


def _read_lines(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def test_all_four_channels_created(_isolated_logs: Path) -> None:
    for channel in LogChannel:
        get_logger("test", channel=channel).info("qeyd")

    files = {path.name for path in _isolated_logs.iterdir()}
    assert files == {"audit.log", "security.log", "error.log", "app.log"}


def test_log_line_is_valid_json(_isolated_logs: Path) -> None:
    get_logger("test").info("SYNC_OK", extra={"server_id": 3, "rows": 120})

    records = _read_lines(_isolated_logs / "app.log")
    assert len(records) == 1
    record = records[0]
    assert record["message"] == "SYNC_OK"
    assert record["level"] == "INFO"
    assert record["channel"] == "app"
    assert record["context"]["server_id"] == 3  # type: ignore[index]
    assert "timestamp" in record


def test_channels_do_not_leak(_isolated_logs: Path) -> None:
    """Audit yazısı `app.log`-a düşməməlidir (propagate=False)."""
    get_logger("test", channel=LogChannel.AUDIT).info("MANUAL_TIME_OVERRIDE")

    assert len(_read_lines(_isolated_logs / "audit.log")) == 1
    assert _read_lines(_isolated_logs / "app.log") == []


def test_sensitive_fields_are_redacted(_isolated_logs: Path) -> None:
    get_logger("test", channel=LogChannel.SECURITY).warning(
        "LOGIN_ATTEMPT",
        extra={
            "email": "user@example.com",
            "password": "SuperGizli123",
            "pin": "4821",
            "totp_secret": "JBSWY3DP",
            "nested": {"api_key": "abc123", "safe": "ok"},
        },
    )

    raw = (_isolated_logs / "security.log").read_text(encoding="utf-8")
    assert "SuperGizli123" not in raw
    assert "4821" not in raw
    assert "JBSWY3DP" not in raw
    assert "abc123" not in raw
    assert "user@example.com" in raw  # e-poçt maskalanmır (audit üçün lazımdır)
    assert "ok" in raw


def test_exception_is_serialized(_isolated_logs: Path) -> None:
    log = get_logger("test", channel=LogChannel.ERROR)
    try:
        raise ValueError("qəsdən xəta")
    except ValueError:
        log.exception("STEP_FAILED")

    record = _read_lines(_isolated_logs / "error.log")[0]
    exception = record["exception"]
    assert exception["type"] == "ValueError"  # type: ignore[index]
    assert "qəsdən xəta" in exception["message"]  # type: ignore[index]
    assert "Traceback" in exception["stacktrace"]  # type: ignore[index]


def test_redact_helper() -> None:
    payload = {
        "password_hash": "x",
        "items": [{"token": "y"}, {"name": "z"}],
        "count": 3,
    }
    result = redact(payload)

    assert result["password_hash"] == "***REDACTED***"
    assert result["items"][0]["token"] == "***REDACTED***"
    assert result["items"][1]["name"] == "z"
    assert result["count"] == 3


@pytest.mark.parametrize(
    "reserved", ["message", "module", "name", "args", "lineno", "levelname", "msg"]
)
def test_reserved_extra_keys_do_not_crash(_isolated_logs: Path, reserved: str) -> None:
    """REQRESSİYA: `extra={"message": ...}` bütün tətbiqi çökdürürdü.

    `logging` qorunan sahə adının üzərinə yazılmasına icazə vermir və `KeyError`
    atır. Loglama heç vaxt tətbiqi dayandırmamalıdır — açar `ctx_` prefiksi ilə
    təhlükəsiz adlandırılır və məlumat itmir.
    """
    get_logger("test").info("EVENT", extra={reserved: "dəyər", "safe": "ok"})

    records = _read_lines(_isolated_logs / "app.log")
    assert len(records) == 1
    context = records[0]["context"]
    assert context[f"ctx_{reserved}"] == "dəyər"  # type: ignore[index]
    assert context["safe"] == "ok"  # type: ignore[index]
    assert records[0]["message"] == "EVENT"  # əsl mesaj toxunulmaz qalır


def test_app_version_can_be_updated_with_force(tmp_path: Path) -> None:
    """REQRESSİYA: lazy konfiqurasiya səbəbindən app_version həmişə 0.0.0 qalırdı."""
    log_dir = tmp_path / "versioned"
    configure_logging(log_dir=log_dir, console=False, force=True, app_version="9.9.9")
    get_logger("test").info("VERSION_CHECK")

    records = _read_lines(log_dir / "app.log")
    assert records[0]["app_version"] == "9.9.9"


def test_configure_logging_is_idempotent(tmp_path: Path) -> None:
    first = configure_logging(log_dir=tmp_path / "a", console=False, force=True)
    second = configure_logging(log_dir=tmp_path / "b", console=False)

    assert first == tmp_path / "a"
    assert second == tmp_path / "b"  # force olmadan yenidən qurulmur
    get_logger("test").info("qeyd")
    assert (tmp_path / "a" / "app.log").exists()


def test_an_unusable_log_directory_falls_back_instead_of_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AÇILIŞ ÇÖKMƏSİ (dövrə 5) — indi GERİ ÇƏKİLMƏ ilə əvəzlənib.

    ──────────────────────────────────────────────────────────────────────────
    NƏ QIRIQ İDİ
    ──────────────────────────────────────────────────────────────────────────
    `configure_logging` `target_dir.mkdir(...)`-i qoruyucusuz çağırırdı və
    `main()` onu HƏM `install_global_exception_hook()`-dan, HƏM əsas
    `try/except`-dən ƏVVƏL işlədir. Yəni `%PROGRAMDATA%\\KompasOS\\logs`
    yaradıla bilməyəndə (icazə siyasəti, antivirus, ya eyni addan FAYL) xam
    `OSError` yüksəlirdi: paketlənmiş `--windowed` `.exe`-də NƏ pəncərə, NƏ
    mesaj, NƏ `error.log` sətri — proses sadəcə yox olurdu.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ ÇÖKMƏ YOX, GERİ ÇƏKİLMƏ SEÇİLDİ
    ──────────────────────────────────────────────────────────────────────────
    Mağaza kassası log qovluğuna görə İŞƏ DÜŞMƏMƏLİDİR — növbə başlayır,
    kassir işləməlidir. Üstəlik «təmiz çıxış kodu» `--windowed` rejimdə
    istifadəçiyə heç nə göstərmir (`stderr` görünmür), yəni o da praktikada
    səssiz yoxa çıxmadır.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `tempfile.gettempdir()` MOCK-LANIR (TESTİN İZOLYASİYASI)
    ──────────────────────────────────────────────────────────────────────────
    Mock-lanmasa geri çəkilmə HƏQİQİ `%TEMP%\\KompasOS\\logs`-a yazır. Bu
    qovluq test sessiyaları arasında TƏMİZLƏNMİR (`RotatingFileHandler`
    mövcud faylın üzərinə YAZMIR, ƏLAVƏ edir) — nəticədə real inkişaf
    maşınında/CI agentində sahiblənilməyən artefakt yığılır VƏ testlər arası
    sızma yaranır («son sətri götür» kimi fərdi düzəlişlər simptomu müalicə
    edir, mənbəni yox). `tmp_path`-a bağlı SAXTA `%TEMP%` hər testi TAM
    izolyasiya edir və `next(...)`/`[-1]` kimi «hansı köhnə sətri seçək»
    sualını ümumiyyətlə YARATMIR.
    """
    fake_temp = tmp_path / "faketemp"
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(fake_temp))
    blocker = tmp_path / "blocker"
    blocker.write_text("bura qovluq deyil, fayldır", encoding="utf-8")
    unwritable_log_dir = blocker / "logs"  # ana element FAYLDIR — mkdir uğursuz olur

    used = configure_logging(log_dir=unwritable_log_dir, console=False, force=True)

    assert used != unwritable_log_dir
    assert used.is_dir()
    assert used == fake_temp / "KompasOS" / "logs"


def test_the_fallback_is_written_to_the_log_so_it_can_be_traced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Geri çəkilmə SÜKUTLA olmur — «loglar niyə boşdur?» sualı cavablanmalıdır.

    `tempfile.gettempdir()` YUXARIDAKI testin şərhindəki səbəblə mock-lanır:
    izolyasiya olmadan `error.log` başqa testlərin/sessiyaların köhnə
    `LOG_DIR_FALLBACK` sətirlərini daşıyır və test YANLIŞ (özününkü olmayan)
    qeydi yoxlaya bilər.
    """
    fake_temp = tmp_path / "faketemp"
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(fake_temp))
    blocker = tmp_path / "blocker"
    blocker.write_text("fayl", encoding="utf-8")
    requested = blocker / "logs"

    used = configure_logging(log_dir=requested, console=False, force=True)
    error_log = used / "error.log"

    assert error_log.exists()
    # SƏTİR JSON-dur — mətn axtarışı yol ayırıcılarının qoşa qaçışına görə
    # yanıldıcıdır (`\` → `\\`). Ona görə sətir PARSE olunur və sahələr
    # ADLA yoxlanılır.
    records = _read_lines(error_log)
    fallback_records = [r for r in records if r["message"] == "LOG_DIR_FALLBACK"]
    # İzolyasiya sayəsində DƏQİQ BİR sətir gözlənilir — "hansını götürək?"
    # sualı (birinci/sonuncu) burada ümumiyyətlə yaranmır.
    assert len(fallback_records) == 1
    entry = fallback_records[0]

    # Həm İSTƏNİLƏN, həm İŞLƏDİLƏN yol yazılır — səbəb izlənə bilsin.
    assert Path(entry["context"]["requested"]) == requested  # type: ignore[index]
    assert Path(entry["context"]["used"]) == used  # type: ignore[index]
    assert entry["context"]["error"]  # type: ignore[index]


def test_main_starts_normally_when_only_the_preferred_log_dir_is_broken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sınıq log qovluğu açılışı DAYANDIRMIR — `EXIT_STARTUP_ERROR` qaytarılmır."""
    from src.main import EXIT_STARTUP_ERROR, main

    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path / "faketemp"))
    blocker = tmp_path / "blocker"
    blocker.write_text("bura qovluq deyil, fayldır", encoding="utf-8")

    code = main(["--check", "--log-dir", str(blocker / "logs")])

    assert code != EXIT_STARTUP_ERROR


def test_main_exits_cleanly_when_even_the_fallback_is_unusable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HƏR İKİ qovluq alınmasa: təmiz çıxış kodu, XAM istisna YOX.

    Bu, düzəlişin ÖZÜNÜN yeni səssiz ölüm yaratmadığını kilidləyir: son hal
    `LogSetupError` (bir `KompasOSError` törəməsi) atır və `main()`-in
    `except (OSError, KompasOSError)` budağı onu tutur.
    """
    from src.main import EXIT_STARTUP_ERROR, main

    blocker = tmp_path / "blocker"
    blocker.write_text("fayl", encoding="utf-8")
    # `%TEMP%` DƏ sınıq olsun — geri çəkilmə yolu da bağlanır.
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(blocker))

    code = main(["--check", "--log-dir", str(blocker / "logs")])

    assert code == EXIT_STARTUP_ERROR


# --------------------------------------------------------------------------- #
# Konsol kanalının kodlaşdırması (paketlənmiş `.exe`-də repro edilib)
# --------------------------------------------------------------------------- #


def test_console_handler_switches_a_cp1252_stream_to_utf8() -> None:
    """Yönləndirilmiş çıxış `cp1252`-dirsə axın UTF-8-ə keçirilir.

    QÜSUR PAKETLƏNMİŞ `.exe`-DƏ TAPILDI: `KompasOS.exe --check` çıxışı hər
    log sətrində `UnicodeEncodeError: 'charmap' codec can't encode character
    'ı'` verirdi — Windows-da boru/yönləndirmə `cp1252`-dir, layihənin isə
    HƏR sətri Azərbaycan hərfi daşıyır. Mesaj fayla düşürdü (fayl handler-i
    `utf-8`), lakin stderr «Logging error» ilə dolurdu.
    """
    import io

    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")

    resolved = _console_stream_with(stream)

    assert resolved is stream
    assert stream.encoding.lower().replace("-", "") == "utf8"


def test_console_handler_is_skipped_when_there_is_no_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--windowed` paketdə `sys.stdout` `None`-dur — handler QURULMUR.

    `StreamHandler(None)` sükutla `sys.stderr`-ə keçir, o da `None` ola bilər;
    onda HƏR log sətri istisna verərdi. Fayl kanalı onsuz da yazır, ona görə
    düzgün davranış konsol handler-ini ÜMUMİYYƏTLƏ qurmamaqdır.
    """
    import logging as std_logging

    from src.shared.logger import LogChannel, configure_logging

    monkeypatch.setattr("src.shared.logger.sys.stdout", None)
    configure_logging(log_dir=tmp_path / "logs", console=True, force=True)

    logger = std_logging.getLogger(LogChannel.APP.logger_name)
    streams = [h for h in logger.handlers if type(h) is std_logging.StreamHandler]
    assert streams == []


def _console_stream_with(stream: object) -> object:
    """`_console_stream()`-i verilmiş axınla çağırır (monkeypatch köməkçisi)."""
    import src.shared.logger as logger_module

    original = logger_module.sys.stdout
    logger_module.sys.stdout = stream  # type: ignore[assignment]
    try:
        return logger_module._console_stream()
    finally:
        logger_module.sys.stdout = original
