"""kompas1.md Faza 2 — icazə kataloquna əlavə edilən 6 yeni flag (#26-30, HR-D).

──────────────────────────────────────────────────────────────────────────────
NİYƏ YENİ GUARD TESTİ YOX, MÖVCUD GUARD-IN TƏSDİQİ VAR
──────────────────────────────────────────────────────────────────────────────
`rbac-flag-engineer` tapşırığının QIRMIZI XƏTTİ: yeni guard YAZILMIR. Bu modul
`PermissionHierarchyGuardUseCase` (Strict Hierarchy + Self-Escalation Guard) və
`PermissionFlag.assert_grantable_to` (Hardlock + Anti-fraud) HEÇ BİR dəyişiklik
olmadan altı yeni flag-i əhatə etdiyini SÜBUT edir.

Bu modul `test_rbac_flag_catalog_extension.py` (miqrasiya 021)-dən BİR
əsaslı yerdə fərqlənir: burada bütün altı flag `hardlock_level = 0` DEYİL —
`can_perform_bulk_operations` (DELEGABLE, səviyyə 3) və `can_configure_
executive_digest` (ROOT_CEO, səviyyə 2) STRUKTUR hardlock daşıyır (miqrasiya
038 başlığı, "Tələ 1"). Ona görə aşağıda flag-lər İKİ qrupa bölünür:
`NONE_HARDLOCK_FLAGS` (yalnız iyerarxiya qərar verir) və elevated-hardlock iki
flag (əlavə struktur məhdudiyyət var, ayrıca test edilir).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest

from src.application.use_cases import (
    CONTROL_PERMISSIONS_FLAG,
    PermissionChangeRequest,
    PermissionHierarchyGuardUseCase,
)
from src.domain.entities import Employee, Position
from src.domain.value_objects import (
    ANTI_FRAUD_FORBIDDEN_ROLES,
    DUAL_CONTROL_APPROVAL_FLAG,
    AuthorizationError,
    HardlockLevel,
    PermissionEffect,
    PermissionFlag,
    RolePriority,
    SystemRole,
    Username,
)
from src.domain.value_objects.identifiers import EmployeeId, PositionId, StoreId, TenantId
from tests.fixtures.fakes import FakeClock, RecordingAudit

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
MIGRATION_FILE: Final = (
    PROJECT_ROOT
    / "database"
    / "migrations"
    / "038_field_reports_and_hr_operations_permission_flags.sql"
)

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)

#: kompas1.md Faza 2 — tapşırığın tam siyahısı.
ALL_NEW_FLAGS: Final[tuple[str, ...]] = (
    "can_conduct_store_audit",
    "can_report_incident",
    "can_manage_leave_balances",
    "can_perform_bulk_operations",
    "can_manage_export_corrections",
    "can_configure_executive_digest",
)

#: `hardlock_level = 0` (NONE) — YALNIZ Strict Hierarchy Guard qərar verir.
NONE_HARDLOCK_FLAGS: Final[tuple[str, ...]] = (
    "can_conduct_store_audit",
    "can_report_incident",
    "can_manage_leave_balances",
    "can_manage_export_corrections",
)

#: İcazə Matrisi qapısı — yalnız bunu daşıyan aktor başqasına icazə verə bilir.
CONTROL_FLAG: Final = PermissionFlag(
    code=CONTROL_PERMISSIONS_FLAG, category="ICAZE", hardlock=HardlockLevel.DELEGABLE
)


def make_employee(role: SystemRole, *, flags: list[PermissionFlag] | None = None) -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=role.value,
        name_az=role.value,
        priority=role.default_priority,
        is_system=True,
        is_camera_type=role.is_camera_type,
    )
    for flag in flags or []:
        position.grant(flag)

    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="T",
        last_name=role.value,
        store_id=STORE,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )


def request_for(
    actor: Employee,
    subject: Employee,
    flag: PermissionFlag,
    effect: PermissionEffect = PermissionEffect.GRANT,
) -> PermissionChangeRequest:
    return PermissionChangeRequest(actor=actor, subject=subject, flag=flag, effect=effect, now=NOW)


@pytest.fixture
def guard() -> PermissionHierarchyGuardUseCase:
    return PermissionHierarchyGuardUseCase(audit=RecordingAudit(), clock=FakeClock(NOW))


# --------------------------------------------------------------------------- #
# Guard təsdiqi — Self-Escalation Guard (bütün altı flag)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("flag_code", ALL_NEW_FLAGS)
def test_self_escalation_guard_blocks_actor_without_the_flag(
    guard: PermissionHierarchyGuardUseCase, flag_code: str
) -> None:
    """Aktor ÖZÜNDƏ olmayan yeni flag-i başqasına verə bilmir.

    CEO aktor kimi seçilib (Root deyil) — Root `_assert_actor_owns_flag`-dan
    azaddır (SEC-006), CEO isə DEYİL, ona görə bu test elevated-hardlock
    flag-lər üçün də mənalıdır (hardlock yoxlamasına ÇATMADAN bloklanır —
    guard sırası: hierarchy → self-escalation → hardlock/anti-fraud).
    """
    flag = PermissionFlag(code=flag_code, category="HR")
    ceo = make_employee(SystemRole.CEO)  # yeni flag YOXDUR
    admin = make_employee(SystemRole.ADMIN)

    with pytest.raises(AuthorizationError, match="aktiv deyil"):
        guard.assert_allowed(request_for(ceo, admin, flag))


@pytest.mark.parametrize("flag_code", NONE_HARDLOCK_FLAGS)
def test_self_escalation_guard_allows_actor_who_owns_the_flag(
    guard: PermissionHierarchyGuardUseCase, flag_code: str
) -> None:
    """MÜSBƏT hal: flag-i daşıyan Root onu aşağı pilləyə ötürə bilir."""
    flag = PermissionFlag(code=flag_code, category="HR")
    root = make_employee(SystemRole.ROOT, flags=[flag])
    hr_admin = make_employee(SystemRole.HR_ADMIN)

    guard.assert_allowed(request_for(root, hr_admin, flag))
    guard.apply(request_for(root, hr_admin, flag))
    assert hr_admin.has_permission(flag_code, now=NOW) is True


# --------------------------------------------------------------------------- #
# Guard təsdiqi — Strict Hierarchy Guard (bütün altı flag)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("flag_code", ALL_NEW_FLAGS)
def test_strict_hierarchy_guard_blocks_equal_tier(
    guard: PermissionHierarchyGuardUseCase, flag_code: str
) -> None:
    """Bərabər pillə bloklanır — CEO başqa CEO-ya yeni flag verə bilmir.

    Hierarchy yoxlaması hardlock-dan ƏVVƏL işlədiyi üçün bu test elevated-
    hardlock flag-lər üçün də keçərlidir (hədəfin hardlock-a uyğun olub-
    olmaması ƏHƏMİYYƏTSİZDİR, bloklama HIERARCHY səbəbi ilə baş verir).
    """
    flag = PermissionFlag(code=flag_code, category="HR")
    ceo_a = make_employee(SystemRole.CEO, flags=[flag])
    ceo_b = make_employee(SystemRole.CEO)

    with pytest.raises(AuthorizationError, match="HIERARCHY"):
        guard.assert_allowed(request_for(ceo_a, ceo_b, flag))


@pytest.mark.parametrize("flag_code", ALL_NEW_FLAGS)
def test_strict_hierarchy_guard_blocks_upward_grant(
    guard: PermissionHierarchyGuardUseCase, flag_code: str
) -> None:
    """Aşağı pillə yuxarıya toxuna bilmir (Admin → CEO)."""
    flag = PermissionFlag(code=flag_code, category="HR")
    admin = make_employee(SystemRole.ADMIN, flags=[CONTROL_FLAG, flag])
    ceo = make_employee(SystemRole.CEO)

    with pytest.raises(AuthorizationError, match="HIERARCHY"):
        guard.assert_allowed(request_for(admin, ceo, flag))


# --------------------------------------------------------------------------- #
# Anti-fraud yoxlaması — siyahı DƏYİŞMƏYİB (CLAUDE.md §5)
# --------------------------------------------------------------------------- #


def test_anti_fraud_forbidden_roles_set_is_unchanged() -> None:
    """Mövcud hardcoded siyahı ({Mağaza_Meneceri, Satıcı}) TOXUNULMAYIB."""
    assert frozenset({SystemRole.STORE_MANAGER, SystemRole.SELLER}) == ANTI_FRAUD_FORBIDDEN_ROLES


#: Bu iki flag-in HƏQİQİ hardlock səviyyəsi (miqrasiya 038) — `HARDLOCK_BY_CODE`
#: xəritəsi olmadan `PermissionFlag(code=..., category="HR")` sükutla
#: `HardlockLevel.NONE` istifadə edərdi və aşağıdakı test YANLIŞ "keçərdi"
#: (hardlock=NONE STORE_MANAGER-ə HEÇ BİR maneə YARATMAZ, testin özü mənasız
#: olardı).
_ELEVATED_HARDLOCK_BY_CODE: Final[dict[str, HardlockLevel]] = {
    "can_perform_bulk_operations": HardlockLevel.DELEGABLE,
    "can_configure_executive_digest": HardlockLevel.ROOT_CEO,
}


@pytest.mark.parametrize("flag_code", ALL_NEW_FLAGS)
def test_new_flags_are_not_in_the_anti_fraud_segregation_list(flag_code: str) -> None:
    """Sual 1: bu flag Mağaza_Meneceri/Satıcı vəzifə ayrılığını POZMUR."""
    assert flag_code not in {
        "can_verify_returns",
        "can_override_return_time",
        "can_issue_fines",
        "can_approve_dual_control_override",
    }
    hardlock = _ELEVATED_HARDLOCK_BY_CODE.get(flag_code, HardlockLevel.NONE)
    flag = PermissionFlag(code=flag_code, category="HR", hardlock=hardlock)
    assert flag.is_anti_fraud is False
    # Mağaza Meneceri bu flag-i öz Position-una ala bilir — istisna atılmır
    # (`can_conduct_store_audit` DEFOLT verilmir, amma fərdi/rol səviyyəsində
    # ALA BİLMƏMƏK ilə "vəzifə ayrılığı görə QADAĞAN olmaq" fərqli şeydir).
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=SystemRole.STORE_MANAGER.value,
        name_az="Mağaza Meneceri",
        priority=RolePriority.OPERATIONAL,
        is_system=True,
    )
    if flag_code in _ELEVATED_HARDLOCK_BY_CODE:
        # Bu ikisi HARDLOCK səbəbindən (anti-fraud səbəbindən YOX) rədd edilir.
        with pytest.raises(AuthorizationError, match="HARDLOCK"):
            position.grant(flag)
    else:
        position.grant(flag)
        assert position.has_flag(flag_code) is True


@pytest.mark.parametrize("flag_code", ALL_NEW_FLAGS)
def test_new_flags_are_not_restricted_to_camera_type_roles(flag_code: str) -> None:
    """Sual 2 (SEC-001): heç biri dual-control təsdiq flag-i DEYİL."""
    assert flag_code != DUAL_CONTROL_APPROVAL_FLAG
    flag = PermissionFlag(code=flag_code, category="HR")
    assert flag.is_camera_only is False


# --------------------------------------------------------------------------- #
# `can_report_incident` — BÜTÜN rollar (Tələ 3)
# --------------------------------------------------------------------------- #


def test_can_report_incident_is_grantable_to_every_system_role() -> None:
    """`hardlock_level = 0` olduğu üçün heç bir rol strukturca kənarlaşmır."""
    flag = PermissionFlag(code="can_report_incident", category="HR")
    for role in SystemRole:
        assert flag.is_grantable_to(role) is True, (
            f"'can_report_incident' '{role.value}' rolunda ola bilməlidir"
        )


def test_can_report_incident_can_be_granted_to_camera_operator_and_seller() -> None:
    """Kamera Nəzarətçisi VƏ Satıcı bu flag-i ala bilir — SEC-001-i POZMUR.

    SEC-001 yalnız `can_approve_dual_control_override`-a aiddir (kamera-tipli
    rol öz override-ını özü təsdiqləyə bilməz); insident BİLDİRMƏK fərqli
    hüquqdur.
    """
    flag = PermissionFlag(code="can_report_incident", category="HR")
    camera_position = Position(
        position_id=PositionId(uuid.uuid4()),
        code="KAMERA_NEZARETCISI",
        name_az="Kamera Nəzarətçisi",
        priority=RolePriority.OPERATIONAL,
        is_system=True,
        is_camera_type=True,
    )
    camera_position.grant(flag)
    assert camera_position.has_flag("can_report_incident") is True

    seller_position = Position(
        position_id=PositionId(uuid.uuid4()),
        code="SATICI",
        name_az="Satıcı",
        priority=RolePriority.STAFF,
        is_system=True,
    )
    seller_position.grant(flag)
    assert seller_position.has_flag("can_report_incident") is True


# --------------------------------------------------------------------------- #
# `can_perform_bulk_operations` — DELEGABLE hardlock (səviyyə 3, Tələ 1)
# --------------------------------------------------------------------------- #


def test_bulk_operations_flag_has_delegable_hardlock() -> None:
    flag = PermissionFlag(
        code="can_perform_bulk_operations", category="HR", hardlock=HardlockLevel.DELEGABLE
    )
    assert flag.is_grantable_to(SystemRole.ROOT) is True
    assert flag.is_grantable_to(SystemRole.CEO) is True
    assert flag.is_grantable_to(SystemRole.ADMIN) is True
    # "YALNIZ Root/CEO/Admin" — qalan dördü STRUKTUR şəkildə kənarda:
    assert flag.is_grantable_to(SystemRole.HR_ADMIN) is False
    assert flag.is_grantable_to(SystemRole.STORE_MANAGER) is False
    assert flag.is_grantable_to(SystemRole.CAMERA_OPERATOR) is False
    assert flag.is_grantable_to(SystemRole.SELLER) is False


def test_bulk_operations_guard_blocks_grant_to_store_manager_even_with_valid_hierarchy(
    guard: PermissionHierarchyGuardUseCase,
) -> None:
    """CEO Mağaza Menecerinə versə belə — HARDLOCK (səviyyə 3) bloklayır.

    Hierarchy (CEO > Mağaza Meneceri) VƏ self-escalation (CEO flag-i daşıyır)
    hər ikisi KEÇİR — yalnız hardlock/anti-fraud addımı bloklayır. Bu, `021`-in
    hardlock=NONE olan altı flag-indən FƏRQLİ, ƏLAVƏ struktur zəmanətdir.
    """
    flag = PermissionFlag(
        code="can_perform_bulk_operations", category="HR", hardlock=HardlockLevel.DELEGABLE
    )
    ceo = make_employee(SystemRole.CEO, flags=[flag])
    manager = make_employee(SystemRole.STORE_MANAGER)

    with pytest.raises(AuthorizationError, match="HARDLOCK"):
        guard.assert_allowed(request_for(ceo, manager, flag))


def test_bulk_operations_guard_allows_grant_to_admin(
    guard: PermissionHierarchyGuardUseCase,
) -> None:
    flag = PermissionFlag(
        code="can_perform_bulk_operations", category="HR", hardlock=HardlockLevel.DELEGABLE
    )
    ceo = make_employee(SystemRole.CEO, flags=[flag])
    admin = make_employee(SystemRole.ADMIN)

    guard.assert_allowed(request_for(ceo, admin, flag))
    guard.apply(request_for(ceo, admin, flag))
    assert admin.has_permission("can_perform_bulk_operations", now=NOW) is True


# --------------------------------------------------------------------------- #
# `can_configure_executive_digest` — ROOT_CEO hardlock (səviyyə 2, Tələ 1)
# --------------------------------------------------------------------------- #


def test_executive_digest_flag_has_root_ceo_hardlock() -> None:
    flag = PermissionFlag(
        code="can_configure_executive_digest", category="HR", hardlock=HardlockLevel.ROOT_CEO
    )
    assert flag.is_grantable_to(SystemRole.ROOT) is True
    assert flag.is_grantable_to(SystemRole.CEO) is True
    # Admin daxil olmaqla QALAN HAMISI kənarda — "Root/CEO" defoltu STRUKTUR:
    assert flag.is_grantable_to(SystemRole.ADMIN) is False
    assert flag.is_grantable_to(SystemRole.HR_ADMIN) is False
    assert flag.is_grantable_to(SystemRole.STORE_MANAGER) is False
    assert flag.is_grantable_to(SystemRole.CAMERA_OPERATOR) is False
    assert flag.is_grantable_to(SystemRole.SELLER) is False


def test_executive_digest_guard_blocks_grant_to_admin(
    guard: PermissionHierarchyGuardUseCase,
) -> None:
    """Root Admin-ə versə belə — HARDLOCK (səviyyə 2) bloklayır.

    Root `_assert_strict_hierarchy`/`_assert_actor_owns_flag`-dan azaddır
    (SEC-006), AMMA `_assert_flag_grantable_to_subject` (hardlock/anti-fraud)
    Root üçün DƏ işləyir — bu test məhz bunu göstərir.
    """
    flag = PermissionFlag(
        code="can_configure_executive_digest", category="HR", hardlock=HardlockLevel.ROOT_CEO
    )
    root = make_employee(SystemRole.ROOT, flags=[flag])
    admin = make_employee(SystemRole.ADMIN)

    with pytest.raises(AuthorizationError, match="HARDLOCK"):
        guard.assert_allowed(request_for(root, admin, flag))


def test_executive_digest_guard_allows_root_to_grant_to_ceo(
    guard: PermissionHierarchyGuardUseCase,
) -> None:
    """Root → CEO: eyni EXECUTIVE pilləsi, amma Root SEC-006 ilə azaddır."""
    flag = PermissionFlag(
        code="can_configure_executive_digest", category="HR", hardlock=HardlockLevel.ROOT_CEO
    )
    root = make_employee(SystemRole.ROOT, flags=[flag])
    ceo = make_employee(SystemRole.CEO)

    guard.assert_allowed(request_for(root, ceo, flag))
    guard.apply(request_for(root, ceo, flag))
    assert ceo.has_permission("can_configure_executive_digest", now=NOW) is True


# --------------------------------------------------------------------------- #
# NONE-hardlock dördlüyü — `021` ilə eyni "yalnız iyerarxiya" sübutu
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("flag_code", NONE_HARDLOCK_FLAGS)
def test_none_hardlock_flags_are_grantable_to_every_role_structurally(flag_code: str) -> None:
    flag = PermissionFlag(code=flag_code, category="HR")
    assert flag.hardlock is HardlockLevel.NONE
    for role in SystemRole:
        assert flag.is_grantable_to(role) is True


# --------------------------------------------------------------------------- #
# Miqrasiya 038 — statik struktur yoxlaması (CLAUDE.md §7, bölmə 5)
# --------------------------------------------------------------------------- #


def _raw_sql() -> str:
    """Faylın TAM mətni (şərhlər DAXİL) — bölmə sərhədləri şərh başlıqlarıdır."""
    return MIGRATION_FILE.read_text(encoding="utf-8")


def _executable_sql() -> str:
    """`--` şərh sətirləri ATILMIŞ mətn — YALNIZ icra olunan SQL."""
    lines = _raw_sql().splitlines()
    return "\n".join(line for line in lines if not re.match(r"^\s*--", line))


def test_migration_file_exists_and_is_readable() -> None:
    assert MIGRATION_FILE.exists(), f"Miqrasiya tapılmadı: {MIGRATION_FILE}"


@pytest.mark.parametrize("flag_code", ALL_NEW_FLAGS)
def test_migration_inserts_every_new_flag_into_the_catalog(flag_code: str) -> None:
    sql = _executable_sql()
    assert f"'{flag_code}'" in sql, f"'{flag_code}' miqrasiya 038-də əlavə edilmir"


def test_migration_does_not_touch_existing_flags() -> None:
    """QIRMIZI XƏTT: mövcud flag-lərdən heç biri silinmir/adı dəyişmir."""
    sql = _executable_sql()
    assert "DELETE FROM permission_flags" not in sql
    assert "UPDATE permission_flags" not in sql
    assert "DROP" not in sql.upper()
    assert "TRUNCATE" not in sql.upper()


def test_migration_flag_inserts_are_idempotent() -> None:
    sql = _executable_sql()
    assert "INSERT INTO permission_flags" in sql
    assert "ON CONFLICT (code) DO NOTHING" in sql


def test_migration_sets_search_path_before_any_insert() -> None:
    sql = _executable_sql()
    preamble = re.search(r"SET\s+search_path\s+TO\s+kompasos\s*,\s*public\s*;", sql)
    assert preamble is not None
    first_insert = re.search(r"\bINSERT\s+INTO\b", sql)
    assert first_insert is not None
    assert preamble.start() < first_insert.start()


def test_migration_documents_its_down_block() -> None:
    text = _raw_sql()
    assert "-- DOWN" in text
    assert re.search(r"^--\s+DELETE FROM permission_flags", text, re.MULTILINE)


def _catalog_row_trailing_flags(sql: str, flag_code: str) -> tuple[str, str, str]:
    """Bir `permission_flags` sətrinin son üç sütununu (hardlock, anti-fraud,
    camera-only) çıxarır — açılış mötərizəsindən sonrakı İLK `rəqəm, BOOL,
    BOOL)` ardıcıllığını tapır. Mətn daxilindəki `(səviyyə 3)` kimi ifadələr
    bunu YANLIŞ tuta bilməz, çünki onların ardından BOOL, BOOL) gəlmir.
    """
    match = re.search(
        rf"\('{flag_code}',.*?(\d),\s*(TRUE|FALSE),\s*(TRUE|FALSE)\)",
        sql,
        re.DOTALL,
    )
    assert match is not None, f"'{flag_code}' üçün kataloq sətri tapılmadı"
    return match.group(1), match.group(2), match.group(3)


def test_migration_sets_hardlock_level_3_for_bulk_operations() -> None:
    sql = _executable_sql()
    hardlock, is_anti_fraud, is_camera_only = _catalog_row_trailing_flags(
        sql, "can_perform_bulk_operations"
    )
    assert hardlock == "3"
    assert is_anti_fraud == "FALSE"
    assert is_camera_only == "FALSE"


def test_migration_sets_hardlock_level_2_for_executive_digest() -> None:
    sql = _executable_sql()
    hardlock, is_anti_fraud, is_camera_only = _catalog_row_trailing_flags(
        sql, "can_configure_executive_digest"
    )
    assert hardlock == "2"
    assert is_anti_fraud == "FALSE"
    assert is_camera_only == "FALSE"


@pytest.mark.parametrize("flag_code", NONE_HARDLOCK_FLAGS)
def test_migration_sets_hardlock_level_0_for_remaining_four_flags(flag_code: str) -> None:
    sql = _executable_sql()
    hardlock, _is_anti_fraud, _is_camera_only = _catalog_row_trailing_flags(sql, flag_code)
    assert hardlock == "0"


def test_root_and_ceo_get_all_six_new_flags() -> None:
    """Mövcud invariant: "Root: bütün flag-lər" / "CEO: Root-un hər şeyi"."""
    sql = _raw_sql()
    root_ceo_block = sql.split("-- 2. DEFOLT SAHİBLİK")[1].split("-- 3. DEFOLT SAHİBLİK")[0]
    assert "'ROOT', 'CEO'" in root_ceo_block
    for flag_code in ALL_NEW_FLAGS:
        assert f"'{flag_code}'" in root_ceo_block, (
            f"'{flag_code}' Root/CEO blokunda yoxdur — mövcud 'hər şeyi görür' invariantı pozulur"
        )


def test_all_seven_roles_get_can_report_incident() -> None:
    sql = _raw_sql()
    block = sql.split("-- 3. DEFOLT SAHİBLİK")[1].split("-- 4. DEFOLT SAHİBLİK")[0]
    for role_code in (
        "ROOT",
        "CEO",
        "ADMIN",
        "HR_ADMIN",
        "MAGAZA_MENECERI",
        "KAMERA_NEZARETCISI",
        "SATICI",
    ):
        assert role_code in block, f"'{role_code}' can_report_incident blokunda yoxdur"


def test_bulk_operations_default_owner_excludes_store_manager_and_operational_roles() -> None:
    """`can_perform_bulk_operations` Mağaza_Meneceri-də (və HR_Admin-də) YOXDUR.

    Bölmə sərhədləri şərh başlığıdır — ona görə `_raw_sql()` (şərhlər
    DAXİL) işlədilir, `_executable_sql()` yox (`_executable_sql()` məhz bu
    başlıqları ATIR, bölünmə boş nəticə verərdi).
    """
    raw = _raw_sql()
    admin_block = raw.split("-- 4. DEFOLT SAHİBLİK — ADMIN")[1].split("-- 5. DEFOLT SAHİBLİK")[0]
    hr_admin_block = raw.split("-- 5. DEFOLT SAHİBLİK — HR_ADMIN")[1].split(
        "-- 6. Mağaza Meneceri"
    )[0]
    assert "can_perform_bulk_operations" in admin_block
    assert "can_perform_bulk_operations" not in hr_admin_block

    executable = _executable_sql()
    assert "WHERE p.code = 'MAGAZA_MENECERI'" not in executable
    assert "WHERE p.code = 'KAMERA_NEZARETCISI'" not in executable
    assert "WHERE p.code = 'SATICI'" not in executable


def test_executive_digest_default_owner_is_only_root_and_ceo() -> None:
    """`can_configure_executive_digest` YALNIZ bölmə 2-də (Root/CEO) görünür."""
    sql = _raw_sql()
    admin_block = sql.split("-- 4. DEFOLT SAHİBLİK — ADMIN")[1].split("-- 5. DEFOLT SAHİBLİK")[0]
    hr_admin_block = sql.split("-- 5. DEFOLT SAHİBLİK — HR_ADMIN")[1].split(
        "-- 6. Mağaza Meneceri"
    )[0]
    assert "can_configure_executive_digest" not in admin_block
    assert "can_configure_executive_digest" not in hr_admin_block
