"""Konfiqurasiya repository-lərinin qərarları — Faza 5.

BAZA LAZIM DEYİL: bağlantı saxta obyektlə əvəz olunur və yalnız QƏRARLAR
yoxlanılır — sətir yoxdursa nə olur, fail-safe hansı istiqamətdədir, hansı
əməliyyat təsdiq tələb edir. Faktiki SQL-in düzgünlüyü `tests/integration`
qatındadır (DATABASE_URL olmadan atlanır).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from src.domain.value_objects.authorization import HardlockLevel
from src.domain.value_objects.catalogs import MAX_LEAVE_DURATION_MINUTES
from src.domain.value_objects.identifiers import EmployeeId, StoreId, TenantId
from src.infrastructure.persistence.config_repositories import (
    PostgresCameraAssignmentRepository,
    PostgresFeatureToggles,
    PostgresLeaveTypeRepository,
    PostgresPermissionFlagRepository,
    PostgresShiftRepository,
    PostgresSystemLimits,
)

TENANT = TenantId(uuid.uuid4())
ACTOR = EmployeeId(uuid.uuid4())


# --------------------------------------------------------------------------- #
# Saxta bağlantı
# --------------------------------------------------------------------------- #


class _FakeCursor:
    def __init__(self, rows: list[dict[str, Any]], log: list[tuple[str, tuple[Any, ...]]]) -> None:
        self._rows = rows
        self._log = log
        self.rowcount = len(rows)

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self._log.append((" ".join(sql.split()), params))

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeConnection:
    """Hər sorğuya EYNİ sətirləri qaytaran bağlantı."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.rows, self.executed)


class _Context:
    def __init__(self, tenant_id: TenantId) -> None:
        self.tenant_id = tenant_id


def _build(repo_cls: type, rows: list[dict[str, Any]] | None = None) -> tuple[Any, _FakeConnection]:
    conn = _FakeConnection(rows)
    return repo_cls(conn, _Context(TENANT)), conn


# --------------------------------------------------------------------------- #
# SystemLimits — defolt davranışı
# --------------------------------------------------------------------------- #


def test_missing_limit_falls_back_to_default() -> None:
    repo, _ = _build(PostgresSystemLimits, rows=[])
    assert repo.get_int(TENANT, "approval_wait", 10) == 10


def test_stored_limit_is_used() -> None:
    repo, _ = _build(PostgresSystemLimits, rows=[{"limit_value": "45"}])
    assert repo.get_int(TENANT, "approval_wait", 10) == 45


def test_non_numeric_limit_falls_back_instead_of_crashing() -> None:
    """Yararsız konfiqurasiya bütün axını dayandırmamalıdır."""
    repo, _ = _build(PostgresSystemLimits, rows=[{"limit_value": "otuz"}])
    assert repo.get_int(TENANT, "approval_wait", 10) == 10


def test_set_value_records_who_changed_it() -> None:
    """ROOT əməliyyatı "kim dəyişdi" sualını cavablandırmalıdır."""
    repo, conn = _build(PostgresSystemLimits)
    repo.set_value(TENANT, "dual_control", "30", changed_by=ACTOR)

    sql, params = conn.executed[-1]
    assert "INSERT INTO system_limits" in sql
    assert "ON CONFLICT" in sql, "Təkrar yazma UPSERT olmalıdır"
    assert ACTOR in params


# --------------------------------------------------------------------------- #
# FeatureToggles — defolt AÇIQ, struktur təsdiqi
# --------------------------------------------------------------------------- #


def test_unknown_module_is_enabled_by_default() -> None:
    """Sətir yoxdursa modul AÇIQ sayılır — söndürmək açıq əməliyyat olmalıdır."""
    repo, _ = _build(PostgresFeatureToggles, rows=[])
    assert repo.is_enabled(TENANT, "tasks") is True


def test_disabled_module_is_reported_as_disabled() -> None:
    repo, _ = _build(PostgresFeatureToggles, rows=[{"is_enabled": False}])
    assert repo.is_enabled(TENANT, "tasks") is False


def test_structural_module_cannot_be_disabled_without_confirmation() -> None:
    """Modal-ı yan keçən yol da eyni qaydaya tabedir."""
    repo, _ = _build(PostgresFeatureToggles, rows=[{"is_structural": True}])

    with pytest.raises(ValueError, match="struktur-kritik"):
        repo.set_enabled(TENANT, "fines", enabled=False, changed_by=ACTOR)


def test_structural_module_disables_with_confirmation() -> None:
    repo, conn = _build(PostgresFeatureToggles, rows=[{"is_structural": True}])

    repo.set_enabled(TENANT, "fines", enabled=False, changed_by=ACTOR, confirmation="Razıyam")

    sql, params = conn.executed[-1]
    assert "INSERT INTO feature_toggles" in sql
    assert "Razıyam" in params


def test_enabling_never_requires_confirmation() -> None:
    """Təsdiq YALNIZ söndürmə üçündür — açmaq zərərsizdir."""
    repo, conn = _build(PostgresFeatureToggles, rows=[{"is_structural": True}])
    repo.set_enabled(TENANT, "fines", enabled=True, changed_by=ACTOR)
    assert conn.executed, "Açma əməliyyatı yerinə yetirilməlidir"


# --------------------------------------------------------------------------- #
# ShiftRepository — fail-safe istiqaməti
# --------------------------------------------------------------------------- #


def test_missing_shift_is_treated_as_a_working_day() -> None:
    """Plan yoxdursa iş günü sayılır.

    Əks halda planlaşdırılmamış işçi üçün gecikmə heç vaxt hesablanmaz və
    cərimə sistemi səssizcə söndürülərdi.
    """
    from datetime import date

    repo, _ = _build(PostgresShiftRepository, rows=[])
    assert repo.is_off_day(ACTOR, date(2026, 8, 12)) is False


def test_off_day_is_reported() -> None:
    from datetime import date

    repo, _ = _build(PostgresShiftRepository, rows=[{"is_off_day": True}])
    assert repo.is_off_day(ACTOR, date(2026, 8, 12)) is True


def test_scheduled_start_is_none_without_a_plan() -> None:
    from datetime import date

    repo, _ = _build(PostgresShiftRepository, rows=[])
    assert repo.scheduled_start(ACTOR, date(2026, 8, 12)) is None


# --------------------------------------------------------------------------- #
# CameraAssignment — fail-safe BOŞ
# --------------------------------------------------------------------------- #


def test_operator_without_assignment_sees_nothing() -> None:
    """Bölmə 4: defolt "hər şeyi göstər" DEYİL."""
    repo, _ = _build(PostgresCameraAssignmentRepository, rows=[])
    assert repo.stores_for_operator(ACTOR) == []


def test_assigned_stores_are_returned() -> None:
    store = StoreId(uuid.uuid4())
    repo, _ = _build(PostgresCameraAssignmentRepository, rows=[{"store_id": store}])
    assert repo.stores_for_operator(ACTOR) == [store]


def test_assignment_is_idempotent() -> None:
    """Təkrar təyinat xəta verməməlidir — eyni əməliyyat iki dəfə edilə bilər."""
    repo, conn = _build(PostgresCameraAssignmentRepository)
    repo.assign(ACTOR, StoreId(uuid.uuid4()), assigned_by=ACTOR)
    sql, _ = conn.executed[-1]
    assert "ON CONFLICT" in sql and "DO NOTHING" in sql


# --------------------------------------------------------------------------- #
# PermissionFlagRepository
# --------------------------------------------------------------------------- #


def test_flag_row_maps_to_domain_object() -> None:
    repo, _ = _build(
        PostgresPermissionFlagRepository,
        rows=[
            {
                "code": "can_issue_fines",
                "category": "KAMERA_CERIME",
                "hardlock_level": 1,
                "is_anti_fraud": True,
                "is_camera_only": True,
                "excludes_camera_role": False,
            }
        ],
    )

    flag = repo.get("can_issue_fines")

    assert flag is not None
    assert flag.code == "can_issue_fines"
    assert flag.hardlock is HardlockLevel.ROOT_ONLY
    assert flag.is_anti_fraud
    assert flag.is_camera_only


def test_duplicate_flag_creation_is_not_silently_swallowed() -> None:
    """`ON CONFLICT DO NOTHING` OLMAMALIDIR — Root səhvən yaratdığını sanardı."""
    from src.domain.value_objects.authorization import PermissionFlag

    repo, conn = _build(PostgresPermissionFlagRepository)
    repo.create(PermissionFlag(code="can_test_flag", category="TEST"), created_by=ACTOR)

    sql, _ = conn.executed[-1]
    assert "INSERT INTO permission_flags" in sql
    assert "ON CONFLICT" not in sql


# --------------------------------------------------------------------------- #
# İcazə növünün ROOT tavanı (Faza 10.2, üçüncü dalğa)
# --------------------------------------------------------------------------- #
#
# NİYƏ OXU YOLU DA TAVANI BİLMƏLİDİR: `LeaveType` tavanı `__post_init__`-də
# yoxlayır və obyekt həm YAZI anında, həm də bazadan BƏRPA edilərkən qurulur.
# Root tavanı qaldırıb 900 dəqiqəlik növ yaratsaydı, növbəti oxu modul
# fallback-ı (720) ilə həmin sətri RƏDD edərdi — yəni kataloq ekranı öz
# yazdığı sətri geri oxuya bilməzdi. Aşağıdakı testlər bu halqanı bağlayır.


class _RoutedCursor:
    """SQL-in ilk açar sözünə görə fərqli sətir dəsti qaytaran kursor."""

    def __init__(self, routes: dict[str, list[dict[str, Any]]], log: list[str]) -> None:
        self._routes = routes
        self._log = log
        self._rows: list[dict[str, Any]] = []
        self.rowcount = 0

    def __enter__(self) -> _RoutedCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        flat = " ".join(sql.split())
        self._log.append(flat)
        table = "system_limits" if "system_limits" in flat else "leave_types"
        self._rows = self._routes.get(table, [])

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _RoutedConnection:
    def __init__(self, routes: dict[str, list[dict[str, Any]]]) -> None:
        self.routes = routes
        self.executed: list[str] = []

    def cursor(self) -> _RoutedCursor:
        return _RoutedCursor(self.routes, self.executed)


def _leave_type_rows(*minutes: int) -> list[dict[str, Any]]:
    return [
        {
            "id": uuid.uuid4(),
            "tenant_id": TENANT,
            "name_az": f"Növ {index}",
            "default_duration_minutes": value,
            "is_active": True,
        }
        for index, value in enumerate(minutes)
    ]


def test_leave_type_read_path_uses_the_root_ceiling() -> None:
    """Root tavanı 1200-dürsə, 900 dəqiqəlik sətir OXUNA bilməlidir."""
    conn = _RoutedConnection(
        {
            "system_limits": [{"limit_value": "1200"}],
            "leave_types": _leave_type_rows(900),
        }
    )
    repo = PostgresLeaveTypeRepository(conn, _Context(TENANT))  # type: ignore[arg-type]

    entries = repo.list_all(TENANT, include_inactive=True)

    assert [entry.default_duration_minutes for entry in entries] == [900]


def test_leave_type_read_path_falls_back_when_the_limit_row_is_missing() -> None:
    """Limit sətri yoxdursa modul fallback-ı işləyir — davranış köhnə ilə eyni."""
    conn = _RoutedConnection(
        {"system_limits": [], "leave_types": _leave_type_rows(MAX_LEAVE_DURATION_MINUTES)}
    )
    repo = PostgresLeaveTypeRepository(conn, _Context(TENANT))  # type: ignore[arg-type]

    assert repo.max_duration_minutes(TENANT) == MAX_LEAVE_DURATION_MINUTES
    assert len(repo.list_all(TENANT)) == 1


def test_leave_type_ceiling_is_read_once_per_query_not_per_row() -> None:
    """Onlarla sətirlik kataloq üçün limit sorğusu BİR dəfə getməlidir."""
    conn = _RoutedConnection(
        {
            "system_limits": [{"limit_value": "1200"}],
            "leave_types": _leave_type_rows(30, 45, 60, 900),
        }
    )
    repo = PostgresLeaveTypeRepository(conn, _Context(TENANT))  # type: ignore[arg-type]

    repo.list_all(TENANT)

    limit_queries = [sql for sql in conn.executed if "system_limits" in sql]
    assert len(limit_queries) == 1
