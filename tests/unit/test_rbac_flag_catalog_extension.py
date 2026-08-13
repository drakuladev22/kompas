"""Faza 2 (kompasos11.md) — icazə kataloquna əlavə edilən 6 yeni flag.

──────────────────────────────────────────────────────────────────────────────
NİYƏ YENİ GUARD TESTİ YOX, MÖVCUD GUARD-IN TƏSDİQİ VAR
──────────────────────────────────────────────────────────────────────────────
`rbac-flag-engineer` tapşırığının QIRMIZI XƏTTİ: yeni guard YAZILMIR. Bu modul
məhz onu SÜBUT edir — `PermissionHierarchyGuardUseCase` (Strict Hierarchy +
Self-Escalation Guard) və `PermissionFlag.assert_grantable_to` (Hardlock +
Anti-fraud) HEÇ BİR dəyişiklik olmadan altı yeni flag-i də əhatə edir, çünki
hər ikisi `PermissionFlag`-in ÖZÜ üzərində generic işləyir (flag kodunu
`if/elif` zənciri ilə tanımır). Testlər bunu altı flag-in HƏR biri üçün ayrıca
işə salaraq göstərir.

NİYƏ AKTOR HƏR YERDƏ ROOT/CEO/ADMIN-DIR: `can_control_user_permissions`
hardlock səviyyəsi DELEGABLE-dir (yalnız priority ≤ Admin) — yəni HR_Admin,
Mağaza Meneceri və s. HEÇ VAXT bu flag-i daşıya bilmir, deməli
`PermissionHierarchyGuardUseCase` vasitəsilə başqasına icazə VERƏ BİLƏN
aktor da yalnız Root/CEO/Admin ola bilər (bax `schema.sql` §23 şərhi). Testlər
bunu əks etdirir — HR_Admin-i "aktor" kimi sınamaq qeyri-real ssenari olardı.

İkinci hissə DB tərəfini (miqrasiya 021) statik mətn üzərində yoxlayır —
`test_phase1_schema_extension.py` ilə eyni naxış (CLAUDE.md §7: schema.sql
YALNIZ bazis, əlavələr miqrasiyadadır).
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
    PROJECT_ROOT / "database" / "migrations" / "021_rbac_flag_catalog_extension.sql"
)

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)

#: kompasos11.md Faza 2 — tapşırığın tam siyahısı.
NEW_FLAGS: Final[tuple[str, ...]] = (
    "can_manage_pos_thresholds",
    "can_view_exceptions",
    "can_broadcast_announcements",
    "can_conduct_performance_review",
    "can_view_attrition_risk",
    "can_manage_employee_documents",
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
# Guard təsdiqi — Self-Escalation Guard
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("flag_code", NEW_FLAGS)
def test_self_escalation_guard_blocks_actor_without_the_flag(
    guard: PermissionHierarchyGuardUseCase, flag_code: str
) -> None:
    """Aktor ÖZÜNDƏ olmayan yeni flag-i başqasına verə bilmir.

    Yeni guard yazılmayıb: eyni `PermissionHierarchyGuardUseCase.assert_allowed`
    çağırılır, yalnız `flag` parametri altı yeni koddan biridir — bu, guard-ın
    flag-i "tanımadığını", generic işlədiyini göstərir.
    """
    flag = PermissionFlag(code=flag_code, category="HR")
    admin = make_employee(SystemRole.ADMIN, flags=[CONTROL_FLAG])  # yeni flag YOXDUR
    seller = make_employee(SystemRole.SELLER)

    with pytest.raises(AuthorizationError, match="aktiv deyil"):
        guard.assert_allowed(request_for(admin, seller, flag))


@pytest.mark.parametrize("flag_code", NEW_FLAGS)
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
# Guard təsdiqi — Strict Hierarchy Guard
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("flag_code", NEW_FLAGS)
def test_strict_hierarchy_guard_blocks_equal_tier(
    guard: PermissionHierarchyGuardUseCase, flag_code: str
) -> None:
    """Bərabər pillə bloklanır — Admin başqa Admin-ə yeni flag verə bilmir.

    `can_conduct_performance_review` üçün bu, Faza 8-də qurulacaq
    `PerformanceReviewUseCase`-in "menecer YUXARI/BƏRABƏR pilləni
    qiymətləndirə bilməz" tələbinin əsasını təsdiqləyir: eyni `outranks()`
    çağırışı istənilən flag üçün eyni cür işləyir, gələcək ekran özü yenidən
    yoxlama yazmır — mövcud guard-ı çağırır.
    """
    flag = PermissionFlag(code=flag_code, category="HR")
    admin_a = make_employee(SystemRole.ADMIN, flags=[CONTROL_FLAG, flag])
    admin_b = make_employee(SystemRole.ADMIN)

    with pytest.raises(AuthorizationError, match="HIERARCHY"):
        guard.assert_allowed(request_for(admin_a, admin_b, flag))


@pytest.mark.parametrize("flag_code", NEW_FLAGS)
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
# Anti-fraud yoxlaması (agent tərifi, 4 sual)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("flag_code", NEW_FLAGS)
def test_new_flags_are_not_in_the_anti_fraud_segregation_list(flag_code: str) -> None:
    """Sual 1: bu flag Mağaza_Meneceri/Satıcı vəzifə ayrılığını POZMUR.

    Heç biri `can_verify_returns`/`can_override_return_time`/`can_issue_fines`/
    `can_approve_dual_control_override` deyil (CLAUDE.md §5 hardcoded siyahı),
    ona görə `is_anti_fraud=False` düzgündür və Mağaza Meneceri
    `can_conduct_performance_review`-u qanuni daşıya bilir.
    """
    assert flag_code not in {
        "can_verify_returns",
        "can_override_return_time",
        "can_issue_fines",
        "can_approve_dual_control_override",
    }
    flag = PermissionFlag(code=flag_code, category="HR")
    assert flag.is_anti_fraud is False
    # Mağaza Meneceri bu flag-i öz Position-una ala bilir — istisna atılmır.
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=SystemRole.STORE_MANAGER.value,
        name_az="Mağaza Meneceri",
        priority=RolePriority.OPERATIONAL,
        is_system=True,
    )
    position.grant(flag)
    assert position.has_flag(flag_code) is True


@pytest.mark.parametrize("flag_code", NEW_FLAGS)
def test_new_flags_are_not_restricted_to_or_from_camera_type_roles(flag_code: str) -> None:
    """Sual 2 (SEC-001): heç biri dual-control təsdiq flag-i DEYİL.

    SEC-001 yalnız `can_approve_dual_control_override`-a aiddir (bax
    `docs/security_decisions.md`). Kamera-tipli rol bu altı flag-i NƏZƏRİ
    olaraq ala bilər (məs. Root manual override versə) — bu, mövcud
    `can_export_reports`/`can_view_audit_logs` kimi digər qeyri-anti-fraud
    flag-lərlə EYNİ davranışdır, yeni boşluq DEYİL.
    """
    assert flag_code != DUAL_CONTROL_APPROVAL_FLAG
    flag = PermissionFlag(code=flag_code, category="HR")
    camera_position = Position(
        position_id=PositionId(uuid.uuid4()),
        code="KAMERA_NEZARETCISI",
        name_az="Kamera Nəzarətçisi",
        priority=RolePriority.OPERATIONAL,
        is_system=True,
        is_camera_type=True,
    )
    # İstisna ATILMIR — flag anti-fraud/camera-only/excludes-camera-role deyil.
    camera_position.grant(flag)
    assert camera_position.has_flag(flag_code) is True


@pytest.mark.parametrize("flag_code", NEW_FLAGS)
def test_self_escalation_guard_never_lets_actor_grant_flag_to_self(
    guard: PermissionHierarchyGuardUseCase, flag_code: str
) -> None:
    """Sual 3: aktor bu flag-i YALNIZ özündə varsa verə bilir, VƏ ÖZÜNƏ verə bilmir."""
    flag = PermissionFlag(code=flag_code, category="HR")
    root = make_employee(SystemRole.ROOT, flags=[flag])

    with pytest.raises(AuthorizationError, match="SELF-ESCALATION"):
        guard.assert_allowed(request_for(root, root, flag))


@pytest.mark.parametrize("flag_code", NEW_FLAGS)
def test_hardlock_level_is_none_so_hierarchy_guard_is_the_only_gate(flag_code: str) -> None:
    """Sual 4: hardlock=NONE olduğu üçün YALNIZ Strict Hierarchy Guard qərar verir.

    `HardlockLevel.NONE.allows()` HƏR rola `True` qaytarır — yəni bu altı
    flag-in "kimə verilə biləcəyi" sualını TAMAMİLƏ iyerarxiya (yuxarıdakı
    testlər) həll edir, əlavə hardlock məhdudiyyəti YOXDUR.
    """
    flag = PermissionFlag(code=flag_code, category="HR")
    assert flag.hardlock is HardlockLevel.NONE
    for role in SystemRole:
        assert flag.is_grantable_to(role) is True


# --------------------------------------------------------------------------- #
# Miqrasiya 021 — statik struktur yoxlaması (CLAUDE.md §7, bölmə 5)
# --------------------------------------------------------------------------- #


def _raw_sql() -> str:
    """Faylın TAM mətni (şərhlər DAXİL) — bölmə sərhədləri şərh başlıqlarıdır."""
    return MIGRATION_FILE.read_text(encoding="utf-8")


def _executable_sql() -> str:
    """`--` şərh sətirləri ATILMIŞ mətn — YALNIZ icra olunan SQL.

    `test_phase1_schema_extension.py` ilə eyni naxış: DOWN bloku bütünlüklə
    şərh içindədir, ona görə bu funksiya onu da AVTOMATİK çıxarır.
    """
    lines = _raw_sql().splitlines()
    return "\n".join(line for line in lines if not re.match(r"^\s*--", line))


def test_migration_file_exists_and_is_readable() -> None:
    assert MIGRATION_FILE.exists(), f"Miqrasiya tapılmadı: {MIGRATION_FILE}"


@pytest.mark.parametrize("flag_code", NEW_FLAGS)
def test_migration_inserts_every_new_flag_into_the_catalog(flag_code: str) -> None:
    sql = _executable_sql()
    assert f"'{flag_code}'" in sql, f"'{flag_code}' miqrasiya 021-də əlavə edilmir"


def test_migration_does_not_touch_the_existing_36_flags() -> None:
    """QIRMIZI XƏTT: mövcud flag-lərdən heç biri silinmir/adı dəyişmir.

    DOWN bloku bütünlüklə şərh içindədir (aşağıdakı `_executable_sql()`) — ona
    görə sənədləşdirilmiş geri-qaytarma addımları bu yoxlamaya mane olmur.
    """
    sql = _executable_sql()
    assert "DELETE FROM permission_flags" not in sql
    assert "UPDATE permission_flags" not in sql, (
        "Mövcud flag-lərin sətri redaktə OLUNMAMALIDIR — yalnız yeni sətir əlavə edilir."
    )
    assert "DROP" not in sql.upper()
    assert "TRUNCATE" not in sql.upper()


def test_migration_flag_inserts_are_idempotent() -> None:
    sql = _executable_sql()
    assert "INSERT INTO permission_flags" in sql
    assert "ON CONFLICT (code) DO NOTHING" in sql, (
        "Təkrar icrada mövcud sətir üstündən yazılmamalıdır (Root-un redaktəsi qorunmalıdır)."
    )


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


@pytest.mark.parametrize("flag_code", ("can_view_exceptions", "can_manage_employee_documents"))
def test_flags_without_a_spec_default_get_no_operational_role_grant(flag_code: str) -> None:
    """kompasos11.md: bu ikisinin defolt sahibi "—" — heç bir operativ rola verilmir.

    Yalnız Root/CEO (mövcud "hər şeyi görür" invariantı) alır; ADMIN/HR_ADMIN/
    MAGAZA_MENECERI blokunda bu iki koddan biri GÖRÜNMƏMƏLİDİR. Raw mətn
    işlədilir (şərhlər DAXİL) — bölmə sərhədi şərh başlığıdır.
    """
    sql = _raw_sql()
    # `COMMIT;`-dən SONRAKI hissə (DOWN bloku) təmizləmə üçün QƏSDƏN altı
    # flag-in hamısını sadalayır (bax fayl sonu) — operativ-rol blokuna
    # aid DEYİL, ona görə kəsilir.
    operational_block = sql.split("-- 3. DEFOLT SAHİBLİK")[1].split("COMMIT;")[0]
    assert f"'{flag_code}'" not in operational_block, (
        f"'{flag_code}' operativ rol blokunda görünür — kompasos11.md '—' sahibliyini pozur"
    )


def test_root_and_ceo_get_all_six_new_flags() -> None:
    """Mövcud invariant: "Root: bütün flag-lər" / "CEO: Root-un hər şeyi" (schema.sql §23)."""
    sql = _raw_sql()
    root_ceo_block = sql.split("-- 2. DEFOLT SAHİBLİK")[1].split("-- 3. DEFOLT SAHİBLİK")[0]
    assert "'ROOT', 'CEO'" in root_ceo_block
    for flag_code in NEW_FLAGS:
        assert f"'{flag_code}'" in root_ceo_block, (
            f"'{flag_code}' Root/CEO blokunda yoxdur — mövcud 'hər şeyi görür' invariantı pozulur"
        )


def test_store_manager_only_gets_the_performance_review_flag() -> None:
    sql = _raw_sql()
    manager_block = sql.split("Mağaza Meneceri: YALNIZ #20")[1].split("-- Kamera Nəzarətçisi")[0]
    assert "can_conduct_performance_review" in manager_block
    for other in NEW_FLAGS:
        if other == "can_conduct_performance_review":
            continue
        assert other not in manager_block, (
            f"Mağaza Meneceri '{other}' flag-ini almamalıdır (kompasos11.md Faza 2 cədvəli)"
        )


def test_camera_operator_and_seller_get_no_new_default_position_permissions_rows() -> None:
    """Mövcud qayda: Kamera Nəzarətçisi yalnız kamera-əməliyyat, Satıcı heç nə."""
    sql = _executable_sql()
    assert "WHERE p.code = 'SATICI'" not in sql
    assert "WHERE p.code = 'KAMERA_NEZARETCISI'" not in sql
