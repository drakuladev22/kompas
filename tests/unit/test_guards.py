"""Guard use case-lərinin və NavigationRegistry-nin testləri (Faza 2.4, 2.8)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.application.use_cases import (
    CONTROL_PERMISSIONS_FLAG,
    DualControlDeadlockGuardUseCase,
    PermissionChangeRequest,
    PermissionHierarchyGuardUseCase,
)
from src.domain.entities import Employee, PermissionOverride, Position
from src.domain.policies import (
    LeaveAllowancePolicy,
    LeaveAllowanceSource,
    SystemLimitKey,
)
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
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    StoreId,
    TenantId,
)
from src.presentation.navigation import (
    MenuEntry,
    NavigationConfigError,
    NavigationRegistry,
)
from tests.fixtures.fakes import FakeClock, RecordingAudit

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)

CONTROL_FLAG = PermissionFlag(
    code=CONTROL_PERMISSIONS_FLAG, category="ICAZE", hardlock=HardlockLevel.DELEGABLE
)
EXPORT_FLAG = PermissionFlag(code="can_export_reports", category="SISTEM")
ROOT_ONLY_FLAG = PermissionFlag(
    code="can_manage_permissions", category="ICAZE", hardlock=HardlockLevel.ROOT_ONLY
)
CAMERA_FLAG = PermissionFlag(
    code="can_issue_fines",
    category="KAMERA_CERIME",
    is_anti_fraud=True,
    is_camera_only=True,
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
    flag: PermissionFlag = EXPORT_FLAG,
    effect: PermissionEffect = PermissionEffect.GRANT,
) -> PermissionChangeRequest:
    return PermissionChangeRequest(actor=actor, subject=subject, flag=flag, effect=effect, now=NOW)


@pytest.fixture
def guard() -> PermissionHierarchyGuardUseCase:
    """Audit ilə qurulmuş qoruyucu.

    `apply()` artıq audit mənbəyi TƏLƏB EDİR (bölmə 3, sətir 86: hər icazə
    dəyişikliyi `audit_logs`-a düşməlidir). Audit-siz qurulmuş qoruyucu
    `assert_allowed()` üçün hələ də yararlıdır — o, UI-da element gizlətmək
    üçün çağırılır və yazı yaratmamalıdır.
    """
    return PermissionHierarchyGuardUseCase(audit=RecordingAudit(), clock=FakeClock(NOW))


# --------------------------------------------------------------------------- #
# Strict Hierarchy Guard
# --------------------------------------------------------------------------- #


def test_admin_can_grant_to_lower_tier(guard: PermissionHierarchyGuardUseCase) -> None:
    admin = make_employee(SystemRole.ADMIN, flags=[CONTROL_FLAG, EXPORT_FLAG])
    seller = make_employee(SystemRole.SELLER)

    guard.assert_allowed(request_for(admin, seller))
    guard.apply(request_for(admin, seller))

    assert seller.has_permission(EXPORT_FLAG.code, now=NOW) is True


def test_admin_cannot_touch_equal_tier(guard: PermissionHierarchyGuardUseCase) -> None:
    actor = make_employee(SystemRole.ADMIN, flags=[CONTROL_FLAG, EXPORT_FLAG])
    other_admin = make_employee(SystemRole.ADMIN)

    with pytest.raises(AuthorizationError, match="HIERARCHY"):
        guard.assert_allowed(request_for(actor, other_admin))


def test_admin_cannot_touch_higher_tier(guard: PermissionHierarchyGuardUseCase) -> None:
    admin = make_employee(SystemRole.ADMIN, flags=[CONTROL_FLAG, EXPORT_FLAG])
    ceo = make_employee(SystemRole.CEO)

    with pytest.raises(AuthorizationError, match="HIERARCHY"):
        guard.assert_allowed(request_for(admin, ceo))


def test_ceo_cannot_touch_other_ceo(guard: PermissionHierarchyGuardUseCase) -> None:
    """SEC-006: bərabər pillə bloklanır, CEO da istisna deyil."""
    ceo_a = make_employee(SystemRole.CEO, flags=[EXPORT_FLAG])
    ceo_b = make_employee(SystemRole.CEO)

    with pytest.raises(AuthorizationError, match="HIERARCHY"):
        guard.assert_allowed(request_for(ceo_a, ceo_b))


def test_root_is_exempt_from_equal_tier_rule(
    guard: PermissionHierarchyGuardUseCase,
) -> None:
    """SEC-006: əks halda tenant-ın ilk Root-u heç kimə icazə verə bilməzdi."""
    root = make_employee(SystemRole.ROOT)
    ceo = make_employee(SystemRole.CEO)

    guard.assert_allowed(request_for(root, ceo))


# --------------------------------------------------------------------------- #
# Self-Escalation Guard
# --------------------------------------------------------------------------- #


def test_cannot_edit_own_permissions(guard: PermissionHierarchyGuardUseCase) -> None:
    admin = make_employee(SystemRole.ADMIN, flags=[CONTROL_FLAG, EXPORT_FLAG])

    with pytest.raises(AuthorizationError, match="SELF-ESCALATION"):
        guard.assert_allowed(request_for(admin, admin))


def test_root_cannot_edit_own_permissions_either(
    guard: PermissionHierarchyGuardUseCase,
) -> None:
    """Root üçün də özünə toxunmaq qadağandır — yalnız bərabər-pillə istisnadır."""
    root = make_employee(SystemRole.ROOT)

    with pytest.raises(AuthorizationError, match="SELF-ESCALATION"):
        guard.assert_allowed(request_for(root, root))


def test_cannot_grant_flag_actor_does_not_have(
    guard: PermissionHierarchyGuardUseCase,
) -> None:
    admin = make_employee(SystemRole.ADMIN, flags=[CONTROL_FLAG])  # EXPORT yoxdur
    seller = make_employee(SystemRole.SELLER)

    with pytest.raises(AuthorizationError, match="aktiv deyil"):
        guard.assert_allowed(request_for(admin, seller))


def test_deny_does_not_require_owning_flag(
    guard: PermissionHierarchyGuardUseCase,
) -> None:
    """İcazəni GERİ ALMAQ səlahiyyət artırması deyil."""
    admin = make_employee(SystemRole.ADMIN, flags=[CONTROL_FLAG])
    seller = make_employee(SystemRole.SELLER)

    guard.assert_allowed(request_for(admin, seller, effect=PermissionEffect.DENY))


def test_root_can_grant_flag_it_does_not_hold(
    guard: PermissionHierarchyGuardUseCase,
) -> None:
    """Root icazə kataloqunun sahibidir — özündə olmayan flag-i də paylaya bilir."""
    root = make_employee(SystemRole.ROOT)
    seller = make_employee(SystemRole.SELLER)

    guard.assert_allowed(request_for(root, seller))


# --------------------------------------------------------------------------- #
# DB PARİTETİ (migration 014) — hər biri `test_guards.sql`-dəki bir testin cütü
# --------------------------------------------------------------------------- #


def test_cannot_deny_own_permissions_either(
    guard: PermissionHierarchyGuardUseCase,
) -> None:
    """Özünə toxunma EFFEKTDƏN ASILI DEYİL (DB cütü: `test_guards.sql` TEST 20).

    DB trigger-i əvvəl yalnız `effect = 'GRANT'` halını bloklayırdı; domen isə
    hər ikisini. Bu test domen tərəfini KİLİDLƏYİR ki, iki qatı "eyniləşdirmək"
    adı ilə səhv istiqamətdə — yəni domeni zəiflədərək — uzlaşdırmaq cəhdi
    dərhal tutulsun.
    """
    admin = make_employee(SystemRole.ADMIN, flags=[CONTROL_FLAG, EXPORT_FLAG])

    with pytest.raises(AuthorizationError, match="SELF-ESCALATION"):
        guard.assert_allowed(request_for(admin, admin, effect=PermissionEffect.DENY))


def test_deny_override_on_actor_removes_ownership(
    guard: PermissionHierarchyGuardUseCase,
) -> None:
    """`DENY` override rol-defoltu ÜSTƏLƏYİR (DB cütü: TEST 21).

    Aktorun rolunda flag var, lakin fərdi `DENY` onu söndürüb — həmin flag
    ARTIQ ötürülə bilməz. Sahibliyin iki qatlı hesablanması `has_permission()`
    ilə eyni sıradadır; DB trigger-i də məhz bu ardıcıllığı təkrarlayır.
    """
    admin = make_employee(SystemRole.ADMIN, flags=[CONTROL_FLAG, EXPORT_FLAG])
    admin.apply_override(
        PermissionOverride(
            flag_code=EXPORT_FLAG.code,
            effect=PermissionEffect.DENY,
            granted_by=EmployeeId(uuid.uuid4()),
        )
    )
    seller = make_employee(SystemRole.SELLER)

    with pytest.raises(AuthorizationError, match="aktiv deyil"):
        guard.assert_allowed(request_for(admin, seller))


def test_expired_override_does_not_count_as_ownership(
    guard: PermissionHierarchyGuardUseCase,
) -> None:
    """Vaxtı keçmiş override sahiblik VERMİR (DB cütü: TEST 22).

    Müvəqqəti səlahiyyət bitdikdən sonra onu başqasına ötürmək, müddət
    məhdudiyyətini bir addımla mənasız edərdi — verilən yeni sətrin öz
    `expires_at`-ı olmaya bilər.
    """
    admin = make_employee(SystemRole.ADMIN, flags=[CONTROL_FLAG])
    admin.apply_override(
        PermissionOverride(
            flag_code=EXPORT_FLAG.code,
            effect=PermissionEffect.GRANT,
            granted_by=EmployeeId(uuid.uuid4()),
            expires_at=NOW - timedelta(hours=1),
        )
    )
    seller = make_employee(SystemRole.SELLER)

    with pytest.raises(AuthorizationError, match="aktiv deyil"):
        guard.assert_allowed(request_for(admin, seller))


def test_active_override_is_enough_to_pass_the_flag_on(
    guard: PermissionHierarchyGuardUseCase,
) -> None:
    """MÜSBƏT HAL: override ilə alınmış flag ötürülə bilir (DB cütü: TEST 19).

    Sahiblik yalnız rol-defoltdan ibarət olsaydı, fərdi override praktikada
    "yarım icazə" olardı — ekranda görünür, lakin həvalə edilə bilmir.
    """
    admin = make_employee(SystemRole.ADMIN, flags=[CONTROL_FLAG])
    admin.apply_override(
        PermissionOverride(
            flag_code=EXPORT_FLAG.code,
            effect=PermissionEffect.GRANT,
            granted_by=EmployeeId(uuid.uuid4()),
            expires_at=NOW + timedelta(hours=1),
        )
    )
    seller = make_employee(SystemRole.SELLER)

    guard.assert_allowed(request_for(admin, seller))


# --------------------------------------------------------------------------- #
# Control flag & hardlock & anti-fraud
# --------------------------------------------------------------------------- #


def test_actor_without_control_flag_denied(
    guard: PermissionHierarchyGuardUseCase,
) -> None:
    hr = make_employee(SystemRole.HR_ADMIN, flags=[EXPORT_FLAG])  # CONTROL yoxdur
    seller = make_employee(SystemRole.SELLER)

    with pytest.raises(AuthorizationError, match="olmadan"):
        guard.assert_allowed(request_for(hr, seller))


def test_hardlocked_flag_cannot_be_granted(
    guard: PermissionHierarchyGuardUseCase,
) -> None:
    root = make_employee(SystemRole.ROOT)
    admin = make_employee(SystemRole.ADMIN)

    with pytest.raises(AuthorizationError):
        guard.assert_allowed(request_for(root, admin, flag=ROOT_ONLY_FLAG))


def test_anti_fraud_flag_cannot_reach_store_manager(
    guard: PermissionHierarchyGuardUseCase,
) -> None:
    """Bölmə 3: kamera flag-i override yolu ilə də Store Manager-ə keçməməlidir."""
    root = make_employee(SystemRole.ROOT)
    manager = make_employee(SystemRole.STORE_MANAGER)

    with pytest.raises(AuthorizationError):
        guard.assert_allowed(request_for(root, manager, flag=CAMERA_FLAG))


def test_dual_control_flag_cannot_reach_camera_operator(
    guard: PermissionHierarchyGuardUseCase,
) -> None:
    root = make_employee(SystemRole.ROOT)
    operator = make_employee(SystemRole.CAMERA_OPERATOR)
    flag = PermissionFlag(
        code=DUAL_CONTROL_APPROVAL_FLAG, category="KAMERA_CERIME", is_anti_fraud=True
    )

    with pytest.raises(AuthorizationError):
        guard.assert_allowed(request_for(root, operator, flag=flag))


def test_is_allowed_never_raises(guard: PermissionHierarchyGuardUseCase) -> None:
    admin = make_employee(SystemRole.ADMIN, flags=[CONTROL_FLAG, EXPORT_FLAG])
    assert guard.is_allowed(request_for(admin, admin)) is False
    assert guard.is_allowed(request_for(admin, make_employee(SystemRole.SELLER))) is True


# --------------------------------------------------------------------------- #
# Dual-Control Deadlock Guard
# --------------------------------------------------------------------------- #


class FakeEmployeeRepo:
    def __init__(self, count: int) -> None:
        self._count = count

    def count_active_with_flag(self, tenant_id: TenantId, flag_code: str) -> int:
        return self._count


class RecordingNotifier:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    def notify(self, **kwargs: object) -> None:
        self.messages.append(kwargs)


def test_deadlock_guard_healthy_when_approver_exists() -> None:
    guard = DualControlDeadlockGuardUseCase(FakeEmployeeRepo(2))  # type: ignore[arg-type]
    result = guard.check(TENANT)

    assert result.is_healthy is True
    assert result.is_deadlocked is False


def test_deadlock_guard_warns_when_no_approver() -> None:
    notifier = RecordingNotifier()
    guard = DualControlDeadlockGuardUseCase(FakeEmployeeRepo(0), notifier)  # type: ignore[arg-type]

    result = guard.check(TENANT)

    assert result.is_deadlocked is True
    assert result.warning_az is not None
    assert len(notifier.messages) == 1
    assert notifier.messages[0]["is_critical"] is True


def test_deadlock_guard_detects_last_approver_removal() -> None:
    """Sonuncu təsdiqçi silinərkən xəbərdarlıq verilməlidir."""
    guard = DualControlDeadlockGuardUseCase(FakeEmployeeRepo(1))  # type: ignore[arg-type]

    assert guard.check_before_change(TENANT, removing_approver=False).is_healthy is True
    result = guard.check_before_change(TENANT, removing_approver=True)
    assert result.is_deadlocked is True
    assert result.approver_count == 0


def test_deadlock_guard_ok_when_two_approvers_and_one_removed() -> None:
    guard = DualControlDeadlockGuardUseCase(FakeEmployeeRepo(2))  # type: ignore[arg-type]
    assert guard.check_before_change(TENANT, removing_approver=True).is_healthy is True


# --------------------------------------------------------------------------- #
# BR-001 — güzəşt siyasəti
# --------------------------------------------------------------------------- #


def test_allowance_defaults_to_leave_type() -> None:
    policy = LeaveAllowancePolicy()
    assert policy.source is LeaveAllowanceSource.LEAVE_TYPE
    assert policy.resolve(leave_type_minutes=60) == 60
    assert policy.resolve(leave_type_minutes=None) == 0


def test_allowance_fixed_source() -> None:
    policy = LeaveAllowancePolicy(source=LeaveAllowanceSource.FIXED, fixed_minutes=30)
    assert policy.resolve(leave_type_minutes=60) == 30


def test_allowance_none_source_is_strictest() -> None:
    policy = LeaveAllowancePolicy(source=LeaveAllowanceSource.NONE)
    assert policy.resolve(leave_type_minutes=60) == 0


def test_allowance_policy_from_limits() -> None:
    policy = LeaveAllowancePolicy.from_limits(
        {
            SystemLimitKey.LEAVE_ALLOWANCE_SOURCE.value: "FIXED",
            SystemLimitKey.LEAVE_ALLOWANCE_FIXED_MINUTES.value: "45",
        }
    )
    assert policy.source is LeaveAllowanceSource.FIXED
    assert policy.fixed_minutes == 45


def test_allowance_policy_falls_back_on_bad_config() -> None:
    """Yararsız konfiqurasiya sistemi çökdürməməlidir — defolta qayıdır."""
    policy = LeaveAllowancePolicy.from_limits(
        {
            SystemLimitKey.LEAVE_ALLOWANCE_SOURCE.value: "QARIŞIQ",
            SystemLimitKey.LEAVE_ALLOWANCE_FIXED_MINUTES.value: "abc",
        }
    )
    assert policy.source is LeaveAllowanceSource.LEAVE_TYPE
    assert policy.fixed_minutes == 0


# --------------------------------------------------------------------------- #
# NavigationRegistry — "GÖRMƏK = SƏLAHİYYƏTİN OLMASI"
# --------------------------------------------------------------------------- #


@pytest.fixture
def registry() -> NavigationRegistry:
    reg = NavigationRegistry()
    reg.register_all(
        [
            MenuEntry(key="settings", title_az="Ayarlar", order=900),
            MenuEntry(
                key="fines",
                title_az="Cərimələr",
                required_flag="can_issue_fines",
                feature_module="FINE_MODULE",
                order=20,
            ),
            MenuEntry(
                key="fines_new",
                title_az="Yeni Cərimə",
                required_flag="can_issue_fines",
                feature_module="FINE_MODULE",
                parent_key="fines",
                order=21,
            ),
            MenuEntry(
                key="permissions",
                title_az="İcazə Matrisi",
                required_flag=CONTROL_PERMISSIONS_FLAG,
                order=10,
            ),
        ]
    )
    return reg


def test_menu_hides_entries_without_permission(registry: NavigationRegistry) -> None:
    """Element BOZ göstərilmir — ümumiyyətlə qaytarılmır (bölmə 3)."""
    seller = make_employee(SystemRole.SELLER)
    keys = [e.key for e in registry.visible_for(seller, now=NOW)]

    assert keys == ["settings"]
    assert "fines" not in keys
    assert "permissions" not in keys


def test_menu_shows_permitted_entries(registry: NavigationRegistry) -> None:
    operator = make_employee(SystemRole.CAMERA_OPERATOR, flags=[CAMERA_FLAG])
    keys = [e.key for e in registry.visible_for(operator, now=NOW)]

    assert "fines" in keys
    assert "fines_new" in keys
    assert "permissions" not in keys


def test_disabled_feature_module_hides_entry(registry: NavigationRegistry) -> None:
    """İKİ şərt eyni vaxtda: icazə VAR, amma modul söndürülüb → görünmür."""
    operator = make_employee(SystemRole.CAMERA_OPERATOR, flags=[CAMERA_FLAG])

    keys = [
        e.key
        for e in registry.visible_for(operator, now=NOW, enabled_modules=frozenset({"TASK_ENGINE"}))
    ]

    assert "fines" not in keys
    assert "settings" in keys  # feature_module=None → toggle-dan asılı deyil


def test_child_hidden_when_parent_hidden() -> None:
    reg = NavigationRegistry()
    reg.register_all(
        [
            MenuEntry(key="parent", title_az="Valideyn", required_flag="can_x"),
            MenuEntry(key="child", title_az="Alt", parent_key="parent"),
        ]
    )
    seller = make_employee(SystemRole.SELLER)

    assert reg.visible_for(seller, now=NOW) == ()


def test_is_visible_guards_deep_links(registry: NavigationRegistry) -> None:
    """Menyunun gizlədilməsi kifayət deyil — birbaşa keçid də bloklanmalıdır."""
    seller = make_employee(SystemRole.SELLER)
    operator = make_employee(SystemRole.CAMERA_OPERATOR, flags=[CAMERA_FLAG])

    assert registry.is_visible("fines", seller, now=NOW) is False
    assert registry.is_visible("fines", operator, now=NOW) is True
    assert registry.is_visible("naməlum_ekran", operator, now=NOW) is False


def test_child_deep_link_blocked_when_parent_blocked(
    registry: NavigationRegistry,
) -> None:
    operator = make_employee(SystemRole.CAMERA_OPERATOR, flags=[CAMERA_FLAG])
    assert registry.is_visible("fines_new", operator, now=NOW, enabled_modules=frozenset()) is False


def test_duplicate_menu_key_rejected() -> None:
    reg = NavigationRegistry()
    reg.register(MenuEntry(key="a", title_az="A"))
    with pytest.raises(NavigationConfigError, match="təkrarlanır"):
        reg.register(MenuEntry(key="a", title_az="A2"))


def test_menu_entry_requires_title() -> None:
    with pytest.raises(NavigationConfigError):
        MenuEntry(key="a", title_az="   ")


def test_entries_are_ordered(registry: NavigationRegistry) -> None:
    root = make_employee(SystemRole.ROOT, flags=[CONTROL_FLAG])
    keys = [e.key for e in registry.visible_for(root, now=NOW)]
    assert keys == ["permissions", "settings"]


def test_override_grants_menu_visibility(registry: NavigationRegistry) -> None:
    """Fərdi override menyu görünüşünə də təsir edir.

    Subyekt `Admin`-dir: `can_control_user_permissions` hardlock səviyyə 3-dür
    və yalnız priority <= ADMIN olan rollara həvalə edilə bilər (bölmə 3).
    """
    guard = PermissionHierarchyGuardUseCase(audit=RecordingAudit(), clock=FakeClock(NOW))
    root = make_employee(SystemRole.ROOT)
    admin = make_employee(SystemRole.ADMIN)

    assert registry.is_visible("permissions", admin, now=NOW) is False

    guard.apply(request_for(root, admin, flag=CONTROL_FLAG))
    assert registry.is_visible("permissions", admin, now=NOW) is True


def test_control_flag_cannot_be_delegated_below_admin(
    guard: PermissionHierarchyGuardUseCase,
) -> None:
    """Hardlock səviyyə 3: HR_Admin bu flag-i ala bilməz (bölmə 3)."""
    root = make_employee(SystemRole.ROOT)
    hr = make_employee(SystemRole.HR_ADMIN)

    with pytest.raises(AuthorizationError, match="HARDLOCK"):
        guard.assert_allowed(request_for(root, hr, flag=CONTROL_FLAG))


def test_priority_enum_used_by_guard() -> None:
    assert RolePriority.ADMIN.outranks(RolePriority.OPERATIONAL) is True
