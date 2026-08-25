"""Deployment təhlükəsizliyi — `v2backlog.md` Faza 11.

11.1 — canary: `app_version_tenant_targets`-də sətri olan tenant KANALINI
       deyil, HƏDƏFİ görür; sətir yoxdursa davranış DƏYİŞMİR.
11.2 — geri-qaytarma: eyni yol köhnə versiyanı da hədəfləyir; «normala
       qaytar» hədəfi silir (çıxış qapısı).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from src.domain.value_objects.updates import UpdateUnavailableError, Version
from src.infrastructure.licensing.vendor_maintenance import (
    VendorMaintenanceError,
    clear_version_target,
    find_version_id,
    set_version_target,
)
from src.infrastructure.updates.catalog import SupabaseReleaseCatalog

TENANT = "11111111-1111-1111-1111-111111111111"


# --------------------------------------------------------------------------- #
# Sahtə bağlantı — `_fetch` yalnız `unit_of_work().connection.cursor()` istifadə edir
# --------------------------------------------------------------------------- #


class _FakeCursor:
    def __init__(self, plan: dict[str, list[dict[str, Any]]]) -> None:
        self._plan = plan
        self._rows: list[dict[str, Any]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        if "app_version_tenant_targets" in sql:
            self._rows = self._plan.get("target", [])
            return
        if "app_versions" in sql and "channel" in sql:
            self._rows = self._plan.get("latest", [])
            return
        raise UpdateUnavailableError("naməlum cədvəl", user_message="yoxdur")

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    @property
    def rowcount(self) -> int:
        return len(self._rows)


class _FakeUow:
    def __init__(self, cursor: _FakeCursor) -> None:
        self.connection = type("_Conn", (), {"cursor": lambda *_: cursor})()

    @staticmethod
    def commit() -> None:
        pass


class _FakeDatabase:
    """`unit_of_work(tenant_id)` kontekst-menecerini təqlid edir."""

    def __init__(self, plan: dict[str, list[dict[str, Any]]]) -> None:
        self.cursor = _FakeCursor(plan)

    @contextmanager
    def unit_of_work(self, tenant_id: str):  # type: ignore[no-untyped-def]
        yield _FakeUow(self.cursor)


def _row(version: str) -> dict[str, Any]:
    return {
        "version_number": version,
        "channel": "STABLE",
        "storage_path": f"stable/KompasOS-{version}.exe",
        "sha256_hash": "a" * 64,
        "size_bytes": 1024,
        "is_mandatory": False,
        "mandatory_below": None,
        "release_notes": "",
        "release_date": datetime(2026, 8, 1, tzinfo=UTC),
        "published_at": datetime(2026, 8, 1, tzinfo=UTC),
    }


def _catalog(plan: dict[str, list[dict[str, Any]]]) -> SupabaseReleaseCatalog:
    from src.infrastructure.persistence.connection_types import Database  # noqa: F401

    catalog = SupabaseReleaseCatalog.__new__(SupabaseReleaseCatalog)
    object.__setattr__(catalog, "_database", _FakeDatabase(plan))
    object.__setattr__(
        catalog,
        "_limits",
        type("_L", (), {"int_of": staticmethod(lambda _k: 20)})(),
    )
    return catalog


def test_targeted_release_beats_the_channel() -> None:
    catalog = _catalog({"target": [_row("1.3.9")], "latest": [_row("1.4.0")]})

    info = catalog.latest(TENANT)

    assert info is not None
    assert info.version == Version.parse("1.3.9")  # canary/rollback hədəfi ÜSTÜNDƏDİR


def test_without_a_target_the_channel_flow_is_untouched() -> None:
    catalog = _catalog({"target": [], "latest": [_row("1.4.0")]})

    info = catalog.latest(TENANT)

    assert info is not None and info.version == Version.parse("1.4.0")


def test_invalid_target_row_falls_back_to_channel() -> None:
    bad = _row("1.3.9")
    bad["sha256_hash"] = "qisa"  # yararsız hash → ReleaseInfo rədd edir
    catalog = _catalog({"target": [bad], "latest": [_row("1.4.0")]})

    info = catalog.latest(TENANT)

    assert info is not None and info.version == Version.parse("1.4.0")


# --------------------------------------------------------------------------- #
# Vendor yazı yolu
# --------------------------------------------------------------------------- #


class _RecordingCursor(_FakeCursor):
    def __init__(self, log: list[tuple[str, Any]], *, returning: bool = True) -> None:
        super().__init__({})
        self.log = log
        self._returning = returning

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.log.append((sql.strip(), params))
        self._rows = [{"id": "ok"}] if self._returning else []

    def fetchone(self) -> dict[str, Any] | None:
        return dict(self._rows[0]) if self._rows else None

    @property
    def rowcount(self) -> int:
        return 1 if self._returning else 0


class _RecordingConn:
    def __init__(self, *, returning: bool = True) -> None:
        self.log: list[tuple[str, Any]] = []
        self._returning = returning

    def cursor(self) -> _RecordingCursor:
        return _RecordingCursor(self.log, returning=self._returning)


def test_short_reason_is_refused_before_any_write() -> None:
    conn = _RecordingConn()
    with pytest.raises(VendorMaintenanceError, match="çox qısadır"):
        set_version_target(conn, tenant_id=TENANT, version_id="v1", reason="can")
    assert not conn.log


def test_set_target_upserts_and_clear_removes() -> None:
    conn = _RecordingConn()
    assert set_version_target(conn, tenant_id=TENANT, version_id="v1", reason="Canary yayımı")
    assert any("ON CONFLICT (tenant_id)" in sql for sql, _ in conn.log)

    assert clear_version_target(conn, tenant_id=TENANT)


def test_find_version_id_ignores_blank_input() -> None:
    conn = _RecordingConn()
    assert find_version_id(conn, version_number="   ") is None
    assert not conn.log  # boş giriş üçün sorğu belə GEDMİR
