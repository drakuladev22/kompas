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
