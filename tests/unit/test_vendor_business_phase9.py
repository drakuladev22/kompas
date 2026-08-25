"""Vendor-tərəfi biznes funksiyaları — `v2backlog.md` Faza 9.

Hər test funksiyanın BİR iddiasını sınayır:

  9.1 — tam ixrac BÜTÜN `tenant_id`-li cədvəlləri gətirir (dinamik kəşf),
        JSON-a çevirmə tipləri İTİRMİR;
  9.2 — tier yalnız «Əsas»/«Tam» ola bilər; defolt toggle dəsti yalnız
        söndürülən modulları yazır;
  9.3 — legacy CSV yoxlaması DB CHECK-lərini ƏVVƏLCƏDƏN tutur.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

import pytest
from scripts.import_legacy_data import (
    ImportValidationError,
    validate_attendance,
    validate_fines,
)

from src.domain.value_objects.identifiers import TenantId
from src.domain.value_objects.licensing import (
    SERVICE_TIER_ESAS,
    SERVICE_TIER_MODULE_DEFAULTS,
    SERVICE_TIER_TAM,
)
from src.infrastructure.licensing.vendor_maintenance import (
    VendorMaintenanceError,
    apply_tier_toggle_defaults,
    dumps_export,
    export_tenant_json,
    set_service_tier,
)

TENANT = str(uuid.uuid4())


# --------------------------------------------------------------------------- #
# 9.3 — CSV yoxlaması
# --------------------------------------------------------------------------- #


def test_verified_attendance_requires_evidence_columns() -> None:
    """`chk_attendance_verified` CHECK-inin ƏVVƏLCƏDƏN tutulması."""
    with pytest.raises(ImportValidationError, match="verified_at"):
        validate_attendance(
            [{"employee_id": TENANT, "work_date": "2025-01-10", "status": "VERIFIED"}]
        )


def test_valid_attendance_rows_pass() -> None:
    rows = validate_attendance(
        [
            {
                "employee_id": TENANT,
                "work_date": "2025-01-10",
                "status": "pending_verification",
                "late_minutes": "15",
            }
        ]
    )
    assert rows[0]["status"] == "PENDING_VERIFICATION"  # enum dəyərinə normallaşır
    assert rows[0]["late"] == 15
    assert rows[0]["verified_at"] is None


def test_unknown_attendance_status_is_refused() -> None:
    with pytest.raises(ImportValidationError, match="naməlum status"):
        validate_attendance([{"employee_id": TENANT, "work_date": "2025-01-10", "status": "LATE"}])


def test_fine_amount_must_be_non_negative() -> None:
    base = {
        "employee_id": TENANT,
        "store_id": str(uuid.uuid4()),
        "fine_type_code": "GECIKME",
        "fine_date": "2025-01-10",
        "photo_evidence_url": "https://drive.example/x.jpg",
        "issued_by_uuid": str(uuid.uuid4()),
    }
    with pytest.raises(ImportValidationError, match="mənfi"):
        validate_fines([{**base, "amount_azn": "-3"}])

    row = validate_fines([{**base, "amount_azn": "12,50"}])[0]
    assert row["amount"] == Decimal("12.50")  # vergüllü format qəbul olunur
    assert row["status"] == "PUBLISHED"  # defolt


# --------------------------------------------------------------------------- #
# 9.1 — Tam data ixracı
# --------------------------------------------------------------------------- #


class _FakeCursor:
    """`execute → fetchall/fetchone/rowcount` minimal sahtəsi."""

    def __init__(self, results: dict[str, list[dict[str, Any]]]) -> None:
        self._results = results
        self._current: list[dict[str, Any]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: Any) -> None:
        self._current = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        if "information_schema.columns" in sql:
            self._current = [
                {"table_schema": "kompasos", "table_name": "fines"},
                {"table_schema": "kompasos", "table_name": "attendance_records"},
            ]
            return
        for key, rows in self._results.items():
            if f'"{key}"' in sql or f"{key}" in sql:
                self._current = rows
                return
        self._current = []

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._current)

    def fetchone(self) -> dict[str, Any] | None:
        return self._current[0] if self._current else None

    @property
    def rowcount(self) -> int:
        return len(self._current)


class _FakeConn:
    def __init__(self, results: dict[str, list[dict[str, Any]]]) -> None:
        self._results = results

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._results)


def test_export_covers_every_discovered_table() -> None:
    conn = _FakeConn(
        {
            "fines": [
                {"id": uuid.uuid4(), "amount": Decimal("12.50")},
            ],
            "attendance_records": [],
        }
    )
    document = export_tenant_json(conn, TENANT)

    assert set(document["tables"]) == {
        "kompasos.fines",
        "kompasos.attendance_records",  # BOŞ cədvəl də SİYAHIYDADIR
    }
    text = dumps_export(document)
    parsed = json.loads(text)
    # Decimal JSON-un öz tipi DEYİL — str forması itmir.
    assert parsed["tables"]["kompasos.fines"][0]["amount"] == "12.50"


def test_export_with_empty_tenant_is_refused() -> None:
    with pytest.raises(VendorMaintenanceError):
        export_tenant_json(_FakeConn({}), "  ")


# --------------------------------------------------------------------------- #
# 9.2 — Tier idarəsi
# --------------------------------------------------------------------------- #


class _RecordingCursor(_FakeCursor):
    def __init__(self, log: list[tuple[str, Any]]) -> None:
        super().__init__({})
        self.log = log

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.log.append((sql, params))
        # UPDATE ... RETURNING həmişə bir sətir qaytarır (tenant mövcuddur
        # ssenarisi); `set_service_tier`-in `True` yolu buna əsaslanır.
        self._current = [{"ok": True}]

    def fetchone(self) -> dict[str, Any] | None:
        return dict(self._current[0]) if self._current else None

    @property
    def rowcount(self) -> int:
        return 1


class _RecordingConn:
    def __init__(self) -> None:
        self.log: list[tuple[str, Any]] = []
        self.committed = False

    def cursor(self) -> _RecordingCursor:
        return _RecordingCursor(self.log)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass


def test_set_service_tier_validates_the_catalogue() -> None:
    conn = _RecordingConn()
    assert set_service_tier(conn, tenant_id=TENANT, tier=SERVICE_TIER_TAM)
    assert any("service_tier = %s" in sql for sql, _ in conn.log)

    with pytest.raises(VendorMaintenanceError, match="Naməlum"):
        set_service_tier(conn, tenant_id=TENANT, tier="PREMIUM")


def test_tier_defaults_only_write_disabled_modules() -> None:
    """«Tam» heç nə yazmır (fail-safe defolt açıqdır); «Əsas» yalnız qara-siyahını."""
    conn = _RecordingConn()
    written = apply_tier_toggle_defaults(conn, tenant_id=TENANT, tier=SERVICE_TIER_ESAS)

    disabled = SERVICE_TIER_MODULE_DEFAULTS[SERVICE_TIER_ESAS]
    assert written == len(disabled)
    upserts = [params for sql, params in conn.log if "feature_toggles" in sql]
    assert {params[1] for params in upserts} == set(disabled)

    empty_conn = _RecordingConn()
    assert apply_tier_toggle_defaults(empty_conn, tenant_id=TENANT, tier=SERVICE_TIER_TAM) == 0
    assert not empty_conn.log

    with pytest.raises(VendorMaintenanceError):
        apply_tier_toggle_defaults(conn, tenant_id=TENANT, tier="GOLD")


def test_tenant_id_type_still_exists_for_directory_imports() -> None:
    """Səthi qoruma: `TenantId` domen tipli qalır (directory imzalarında)."""
    assert TenantId(TENANT)
