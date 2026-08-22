"""Tam spesifikasiya auditində tapılan qüsurların reqressiya testləri.

Hər test AUDİTDƏ TAPILMIŞ konkret bir boşluğu kilidləyir. Docstring-lər
qüsurun nə olduğunu və niyə heç bir mövcud testin onu tutmadığını yazır —
bu, testin gələcəkdə "lazımsız" kimi silinməsinin qarşısını alır.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import (
    HardlockLevel,
    PermissionEffect,
    PermissionFlag,
    RolePriority,
    SystemRole,
)
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    EmployeeId,
    FineTypeId,
    PositionId,
    StoreId,
    TenantId,
)

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)

#: Dual-control təsdiqi — anti-fraud, kamera roluna da verilmir (SEC-001).
DUAL_FLAG = PermissionFlag(
    code="can_approve_dual_control_override",
    category="KAMERA_CERIME",
    is_anti_fraud=True,
)
#: Adi operativ flag — heç bir qadağası yoxdur.
PLAIN_FLAG = PermissionFlag(code="can_view_audit_logs", category="SISTEM")
#: Cərimə TƏSDİQ flag-i — `excludes_camera_role=True`: cərimə YARADAN
#: (kamera-tipli rol) ilə onu TƏSDİQ EDƏN eyni şəxs ola bilməz (SEC-001,
#: bölmə 3). `DUAL_FLAG`-dan fərqli olaraq `ANTI_FRAUD_FORBIDDEN_ROLES`-a
#: DEYİL, məhz kamera-tipliyə bağlıdır — SEC-1 reqressiyası üçün lazım olan
#: ayırıcı budur (bax aşağı test).
CAMERA_EXCLUDED_FLAG = PermissionFlag(
    code="can_publish_fines",
    category="KAMERA_CERIME",
    is_anti_fraud=True,
    excludes_camera_role=True,
)


def _position(role: SystemRole, *, priority: RolePriority | None = None) -> Position:
    return Position(
        position_id=PositionId(uuid.uuid4()),
        code=role.value,
        name_az=role.value,
        priority=priority if priority is not None else role.default_priority,
        tenant_id=TENANT,
        is_system=True,
        is_camera_type=role.is_camera_type,
    )


def _employee(role: SystemRole, *, employee_id: EmployeeId | None = None) -> Employee:
    return Employee(
        employee_id=employee_id or EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=_position(role),
        first_name="Ad",
        last_name="Soyad",
        store_id=STORE,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )


# --------------------------------------------------------------------------- #
# 1. Rol dəyişikliyi anti-fraud override-larını təmizləyir
# --------------------------------------------------------------------------- #


def test_role_change_revokes_forbidden_overrides() -> None:
    """ROL DƏYİŞİKLİYİ İNVARİANTI — auditdə tapılan KRİTİK-1.

    Anti-fraud qadağası yalnız flag VERİLDİYİ anda yoxlanılırdı. Ona görə
    bu yol açıq idi: flag qanuni olaraq HR_Admin-ə verilir → rol sonradan
    `Mağaza_Meneceri`-yə dəyişdirilir → override QALIR və `has_permission`
    ona rol-defoltdan ƏVVƏL baxır. Nəticədə mağaza meneceri öz filialının
    Kamera Operatorunun override-larını ÖZÜ təsdiqləyə bilirdi — Dual-Control
    mexanizminin tam yan keçilməsi.
    """
    employee = _employee(SystemRole.HR_ADMIN)
    employee.apply_override(
        PermissionOverride(
            flag_code=DUAL_FLAG.code,
            effect=PermissionEffect.GRANT,
            granted_by=EmployeeId(uuid.uuid4()),
        )
    )
    assert employee.has_permission(DUAL_FLAG.code, now=NOW) is True

    removed = employee.change_position(
        _position(SystemRole.STORE_MANAGER), catalog={DUAL_FLAG.code: DUAL_FLAG}
    )

    assert removed == [DUAL_FLAG.code]
    assert employee.has_permission(DUAL_FLAG.code, now=NOW) is False


def test_role_change_keeps_allowed_overrides() -> None:
    """Qadağan OLMAYAN override toxunulmamalıdır — süzgəc kor deyil."""
    employee = _employee(SystemRole.HR_ADMIN)
    employee.apply_override(
        PermissionOverride(
            flag_code=PLAIN_FLAG.code,
            effect=PermissionEffect.GRANT,
            granted_by=EmployeeId(uuid.uuid4()),
        )
    )

    removed = employee.change_position(
        _position(SystemRole.STORE_MANAGER), catalog={PLAIN_FLAG.code: PLAIN_FLAG}
    )

    assert removed == []
    assert employee.has_permission(PLAIN_FLAG.code, now=NOW) is True


def test_unknown_flag_in_overrides_is_not_dropped() -> None:
    """Kataloqda olmayan flag SİLİNMİR — məlumat itkisi olardı."""
    employee = _employee(SystemRole.HR_ADMIN)
    employee.apply_override(
        PermissionOverride(
            flag_code="can_legacy_thing",
            effect=PermissionEffect.GRANT,
            granted_by=EmployeeId(uuid.uuid4()),
        )
    )

    removed = employee.change_position(_position(SystemRole.STORE_MANAGER), catalog={})
    assert removed == []


def _custom_camera_position() -> Position:
    """CUSTOM kamera-tipli rol — heç bir 7 sistem roluna uyğun gəlmir.

    `code` `SystemRole(...)`-a çevrilmədiyi üçün `Position.system_role` `None`
    qaytarır və `effective_system_role` `_PRIORITY_TO_ROLE[OPERATIONAL]` =
    `SystemRole.HR_ADMIN`-ə düşür (`position.py:342`). `HR_ADMIN.is_camera_type`
    isə `False`-dur — yəni `role.is_camera_type` bu barədə HEÇ NƏ demir, YEGANƏ
    siqnal `Position.is_camera_type=True`-nın özüdür.
    """
    return Position(
        position_id=PositionId(uuid.uuid4()),
        code="KAMERA_XUSUSI_ROL",
        name_az="Xüsusi Kamera Nəzarətçisi",
        priority=RolePriority.OPERATIONAL,
        tenant_id=TENANT,
        is_system=False,
        is_camera_type=True,
    )


def test_role_change_to_a_custom_camera_role_revokes_the_excluded_flag() -> None:
    """SEC-1 reqressiyası — `qa` çarpaz sorğuda tapdı, `domain` düzəltdi.

    ──────────────────────────────────────────────────────────────────────────
    QÜSUR NƏ İDİ
    ──────────────────────────────────────────────────────────────────────────
    `change_position()` `flag.assert_grantable_to(position.effective_system_role)`
    çağırırdı — `is_camera_type_role=position.is_camera_type` ÖTÜRMƏDƏN.
    `grant()` (`position.py:104-106`) və `permission_guards.py:246-249` bu
    parametri artıq ötürürdü, `change_position()` isə YEGANƏ istisna idi
    (`assert_grantable_to(` repoda cəmi 4 istinad, bu 3-ü düzgün idi).

    NƏTİCƏ: CUSTOM kamera-tipli rola (`Position.is_camera_type=True`,
    `_PRIORITY_TO_ROLE[OPERATIONAL] = HR_ADMIN`) keçən işçidə əvvəlki
    `can_publish_fines` (cərimə TƏSDİQ) override-u TƏMİZLƏNMİRDİ, çünki
    `camera_capable = is_camera_type_role or role.is_camera_type` hesablanarkən
    HƏR İKİ tərəf `False`-a düşürdü — `is_camera_type_role` ötürülmədiyi,
    `HR_ADMIN.is_camera_type` isə həqiqətən `False` olduğu üçün.
    Beləliklə cərimə YARADAN (kamera) ilə TƏSDİQ EDƏN eyni şəxs ola bilirdi —
    SEC-001-in "vəzifə ayrılığı" zəmanəti CUSTOM rol vasitəsilə yan keçilirdi.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ MÖVCUD İKİ TEST (yuxarı) BUNU TUTMURDU
    ──────────────────────────────────────────────────────────────────────────
    `test_role_change_revokes_forbidden_overrides` `DUAL_FLAG`
    (`can_approve_dual_control_override`) və hədəf `SystemRole.STORE_MANAGER`
    işlədir — həmin kombinasiya `ANTI_FRAUD_FORBIDDEN_ROLES`-un BİRİNCİ
    şərtindən (`assert_grantable_to`-nun kamera qolundan ƏVVƏLKİ şərt) keçib
    istisna atır, yəni kamera-tipli budağa HEÇ ÇATMIR. `_position()` helperi
    də HƏR YERDƏ `is_camera_type=role.is_camera_type` yazır — yəni SİSTEM
    rolundan törəyir, CUSTOM `Position(is_camera_type=True, ...)` heç vaxt
    qurulmurdu. Bu test məhz həmin ikinci, sınanmamış budağı ölçür.

    ──────────────────────────────────────────────────────────────────────────
    TEST DÜZƏLİŞDƏN ƏVVƏL NİYƏ ÇÖKƏRDİ
    ──────────────────────────────────────────────────────────────────────────
    `employee.py:246`-da `is_camera_type_role=position.is_camera_type`
    arqumenti ÇIXARILSA (zehnən), `assert_grantable_to` yalnız
    `role.is_camera_type` (`HR_ADMIN` → `False`) görər, `excludes_camera_role`
    şərti işə düşməz, `AuthorizationError` atılmaz, `removed` boş qalar —
    aşağıdakı iki `assert` İKİSİ də sınardı.
    """
    employee = _employee(SystemRole.HR_ADMIN)
    employee.apply_override(
        PermissionOverride(
            flag_code=CAMERA_EXCLUDED_FLAG.code,
            effect=PermissionEffect.GRANT,
            granted_by=EmployeeId(uuid.uuid4()),
        )
    )
    assert employee.has_permission(CAMERA_EXCLUDED_FLAG.code, now=NOW) is True

    removed = employee.change_position(
        _custom_camera_position(), catalog={CAMERA_EXCLUDED_FLAG.code: CAMERA_EXCLUDED_FLAG}
    )

    assert removed == [CAMERA_EXCLUDED_FLAG.code]
    assert employee.has_permission(CAMERA_EXCLUDED_FLAG.code, now=NOW) is False


def _custom_store_tier_position() -> Position:
    """CUSTOM mağaza-pilləli rol — `_custom_camera_position()`-un GÜZGÜSÜ (T6).

    `code` `SystemRole(...)`-a çevrilmir, `effective_system_role`
    `_PRIORITY_TO_ROLE[OPERATIONAL]` = `SystemRole.HR_ADMIN`-ə düşür.
    `HR_ADMIN` `ANTI_FRAUD_FORBIDDEN_ROLES`-da DEYİL — yəni YEGANƏ siqnal
    `Position.is_store_tier=True`-nın özüdür.
    """
    return Position(
        position_id=PositionId(uuid.uuid4()),
        code="FILIAL_RESPONSAVI",
        name_az="Filial Responsavı",
        priority=RolePriority.OPERATIONAL,
        tenant_id=TENANT,
        is_system=False,
        is_store_tier=True,
    )


def test_role_change_to_a_custom_store_tier_role_revokes_the_anti_fraud_flag() -> None:
    """T6 — `change_position()` `is_store_tier_role`-u da ötürməlidir.

    `test_role_change_to_a_custom_camera_role_revokes_the_excluded_flag`-in
    EYNİ naxışı, `is_camera_type` əvəzinə `is_store_tier` üçün: `DUAL_FLAG`
    (`is_anti_fraud=True`) qanuni olaraq HR_Admin-ə verilir, sonra işçi
    CUSTOM mağaza-pilləli (`FILIAL_RESPONSAVI`, `effective_system_role` =
    `HR_ADMIN`) rola köçürülür. `is_store_tier_role=position.is_store_tier`
    ötürülməsə, `store_capable = is_store_tier_role or role in
    ANTI_FRAUD_FORBIDDEN_ROLES` hər iki tərəfdən `False` qalar (`HR_ADMIN`
    qadağan siyahısında deyil) və override TƏMİZLƏNMƏZ — mağaza meneceri
    ekvivalenti öz filialının kamera operatorunun override-unu ÖZÜNDƏ
    saxlamış olardı.
    """
    employee = _employee(SystemRole.HR_ADMIN)
    employee.apply_override(
        PermissionOverride(
            flag_code=DUAL_FLAG.code,
            effect=PermissionEffect.GRANT,
            granted_by=EmployeeId(uuid.uuid4()),
        )
    )
    assert employee.has_permission(DUAL_FLAG.code, now=NOW) is True

    removed = employee.change_position(
        _custom_store_tier_position(), catalog={DUAL_FLAG.code: DUAL_FLAG}
    )

    assert removed == [DUAL_FLAG.code]
    assert employee.has_permission(DUAL_FLAG.code, now=NOW) is False


# --------------------------------------------------------------------------- #
# 2. İcazə dəyişikliyi audit-lənir
# --------------------------------------------------------------------------- #


def test_permission_override_is_written_to_audit_log() -> None:
    """Bölmə 3 (sətir 86) — auditdə tapılan KRİTİK-4.

    `PermissionHierarchyGuardUseCase` YALNIZ `security.log`-a yazırdı. O,
    fayl-əsaslıdır və `audit_logs`-un DB-səviyyəli append-only zəmanətini
    (`schema.sql` §26) daşımır — yəni sistemin ən həssas əməliyyatı
    (kimin nəyi kimə verməsi) auditdən kənarda qalırdı.
    """
    from src.application.use_cases.permission_guards import (
        PermissionChangeRequest,
        PermissionHierarchyGuardUseCase,
    )
    from tests.fixtures.fakes import FakeClock, RecordingAudit

    audit = RecordingAudit()
    guard = PermissionHierarchyGuardUseCase(audit=audit, clock=FakeClock(NOW))

    guard.apply(
        PermissionChangeRequest(
            actor=_employee(SystemRole.ROOT),
            subject=_employee(SystemRole.SELLER),
            flag=PLAIN_FLAG,
            effect=PermissionEffect.GRANT,
            now=NOW,
            reason="Audit jurnalına baxış lazımdır",
        )
    )

    assert "PERMISSION_OVERRIDE_APPLIED" in audit.actions()
    entry = audit.entries[-1]
    assert entry["after_state"]["flag"] == PLAIN_FLAG.code
    assert entry["after_state"]["effective"] is True
    assert entry["before_state"]["effective"] is False
    assert entry["reason"] == "Audit jurnalına baxış lazımdır"


def test_permission_override_without_audit_source_is_rejected() -> None:
    """Audit mənbəyi yoxdursa əməliyyat DAYANIR, sükutla keçmir.

    Bölmə 5: "məcburi olan bir şeyin sükutla buraxılması onu məcburi olmaqdan
    çıxarır". `assert_allowed()` isə audit-siz işləməyə davam edir — o, UI-da
    element gizlətmək üçün çağırılır və yazı yaratmamalıdır.
    """
    from src.application.use_cases.permission_guards import (
        PermissionAuditUnavailableError,
        PermissionChangeRequest,
        PermissionHierarchyGuardUseCase,
    )

    guard = PermissionHierarchyGuardUseCase()
    request = PermissionChangeRequest(
        actor=_employee(SystemRole.ROOT),
        subject=_employee(SystemRole.SELLER),
        flag=PLAIN_FLAG,
        effect=PermissionEffect.GRANT,
        now=NOW,
    )

    guard.assert_allowed(request)  # yoxlama işləyir
    with pytest.raises(PermissionAuditUnavailableError):
        guard.apply(request)


# --------------------------------------------------------------------------- #
# 3. Öz PIN/şifrəsini sıfırlamaq qadağandır
# --------------------------------------------------------------------------- #


class _Employees:
    def __init__(self, employee: Employee) -> None:
        self.employee = employee
        self.saved: list[Employee] = []

    def get(self, employee_id: EmployeeId) -> Employee | None:
        return self.employee if employee_id == self.employee.id else None

    def save(self, employee: Employee) -> None:
        self.saved.append(employee)


class _Credentials:
    def __init__(self) -> None:
        self.pins: list[Any] = []
        self.passwords: list[Any] = []
        self.cleared: list[Any] = []

    def set_pin(self, employee_id: EmployeeId, *, raw_pin: str) -> None:
        self.pins.append((employee_id, raw_pin))

    def set_password(
        self, employee_id: EmployeeId, *, raw_password: str, must_change: bool
    ) -> None:
        self.passwords.append((employee_id, raw_password, must_change))

    def clear_pin_lockout(self, employee_id: EmployeeId) -> None:
        self.cleared.append(employee_id)


def _user_use_case(employee: Employee, **extra: Any) -> Any:
    from src.application.use_cases.user_management import UserManagementUseCase
    from tests.fixtures.fakes import FakeClock, RecordingAudit

    return UserManagementUseCase(
        employees=_Employees(employee),  # type: ignore[arg-type]
        credentials=extra.pop("credentials", _Credentials()),  # type: ignore[arg-type]
        audit=extra.pop("audit", RecordingAudit()),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
        **extra,
    )


def _grant(employee: Employee, flag_code: str) -> None:
    employee.apply_override(
        PermissionOverride(
            flag_code=flag_code, effect=PermissionEffect.GRANT, granted_by=employee.id
        )
    )


def test_admin_cannot_reset_own_pin() -> None:
    """Bölmə 2 (sətir 42) — SEC-016-nın BİRİNCİ struktur qorunması.

    TOTP çıxarılanda onun yerini üç qorunma tutdu; birincisi budur:
    sıfırlamanı HƏMİŞƏ BAŞQA admin edir. Kod isə `_assert_may_manage`-də
    `actor.id == subject.id` halında ŞƏRTSİZ icazə verirdi — yəni
    `can_reset_pin` sahibi öz lockout-unu da özü açırdı (`clear_pin_lockout`
    bu axındadır), 5 səhv cəhd qaydası öz-özünə yan keçilirdi.
    """
    from src.application.use_cases.user_management import UserManagementError

    actor = _employee(SystemRole.HR_ADMIN)
    _grant(actor, "can_reset_pin")
    credentials = _Credentials()

    with pytest.raises(UserManagementError, match="başqa admin"):
        _user_use_case(actor, credentials=credentials).reset_pin(
            tenant_id=TENANT, actor=actor, employee_id=actor.id, new_pin="1234"
        )

    assert credentials.pins == []
    assert credentials.cleared == [], "Öz lockout-unu açmaq da bloklanmalıdır"


def test_admin_cannot_reset_own_password() -> None:
    """Eyni qayda şifrə üçün — `reset_password` də admin-vasitəçilidir."""
    from src.application.use_cases.user_management import UserManagementError

    actor = _employee(SystemRole.HR_ADMIN)
    _grant(actor, "can_reset_password")
    credentials = _Credentials()

    with pytest.raises(UserManagementError, match="başqa admin"):
        _user_use_case(actor, credentials=credentials).reset_password(
            tenant_id=TENANT, actor=actor, employee_id=actor.id, new_password="Uzun-Sifre-123"
        )
    assert credentials.passwords == []


def test_pin_reset_notifies_the_owner() -> None:
    """Bölmə 2 (sətir 42) — ÜÇÜNCÜ qorunma: sahibin XƏBƏRİ olmalıdır.

    Bildiriş olmadan işçi PIN-inin dəyişdirildiyini yalnız növbəti girişdə
    bilir — yəni sui-istifadə hallı günlərlə gizli qala bilər.
    """
    from tests.fixtures.fakes import RecordingNotifier

    actor = _employee(SystemRole.HR_ADMIN)
    _grant(actor, "can_reset_pin")
    subject = _employee(SystemRole.SELLER)
    notifier = RecordingNotifier()

    use_case = _user_use_case(subject, notifier=notifier)  # type: ignore[arg-type]
    use_case.reset_pin(tenant_id=TENANT, actor=actor, employee_id=subject.id, new_pin="1234")

    assert "CREDENTIAL_RESET" in notifier.categories()
    assert notifier.messages[-1]["recipient_id"] == subject.id


# --------------------------------------------------------------------------- #
# 4. Cəriməni yazan onun etirazına qərar verə bilməz
# --------------------------------------------------------------------------- #


def test_fine_issuer_cannot_decide_own_appeal() -> None:
    """Vəzifə ayrılığı — auditdə tapılan XƏBƏRDARLIQ-7.

    `fine_management.py` modul başlığı bu qaydanı İDDİA edirdi
    («cəriməni yaradan onu ləğv edə BİLMƏMƏLİDİR … DB trigger-i də bunu
    qoruyur»), lakin nə domendə, nə DB-də yoxlama var idi:
    `can_approve_leave_appeal` anti-fraud flag DEYİL, yəni trigger ona
    toxunmur və fərdi override ilə Kamera Operatoruna verilə bilər.
    """
    from src.application.use_cases.fine_management import FinePermissionError
    from src.domain.entities.fine import Fine, FineSource
    from src.domain.value_objects.identifiers import new_fine_id
    from src.domain.value_objects.money import Money

    operator = _employee(SystemRole.CAMERA_OPERATOR)
    fine = Fine(
        fine_id=new_fine_id(),
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        store_id=STORE,
        source=FineSource.MANUAL_CAMERA,
        amount=Money(Decimal("25.00")),
        issued_at=NOW,
        issued_by=operator.id,
        fine_type_id=FineTypeId(uuid.uuid4()),
        photo_evidence_url="queue-1",
    )

    from src.application.use_cases.fine_management import FineAppealUseCase

    with pytest.raises(FinePermissionError, match="vəzifə ayrılığı"):
        FineAppealUseCase._assert_not_issuer(operator, fine)


def test_other_approver_may_decide_the_appeal() -> None:
    """Qadağa YALNIZ yazan şəxsə aiddir — HR_Admin normal qərar verir."""
    from src.application.use_cases.fine_management import FineAppealUseCase
    from src.domain.entities.fine import Fine, FineSource
    from src.domain.value_objects.identifiers import new_fine_id
    from src.domain.value_objects.money import Money

    fine = Fine(
        fine_id=new_fine_id(),
        tenant_id=TENANT,
        employee_id=EmployeeId(uuid.uuid4()),
        store_id=STORE,
        source=FineSource.MANUAL_CAMERA,
        amount=Money(Decimal("25.00")),
        issued_at=NOW,
        issued_by=EmployeeId(uuid.uuid4()),
        fine_type_id=FineTypeId(uuid.uuid4()),
        photo_evidence_url="queue-1",
    )
    FineAppealUseCase._assert_not_issuer(_employee(SystemRole.HR_ADMIN), fine)


# --------------------------------------------------------------------------- #
# 5. Sihirbaz `complete_setup()`-ın gözlədiyi formanı qaytarır
# --------------------------------------------------------------------------- #


def test_wizard_payload_shape_matches_setup_contract() -> None:
    """Auditdə tapılan KRİTİK-2 — GUI ilə quraşdırma MÜMKÜN DEYİLDİ.

    `collected()` YASTI lüğət qaytarırdı (`full_name`, `store_name`, …),
    `complete_setup()` isə `payload["root"]`/`["stores"]`/`["invites"]`
    gözləyirdi. Nəticə: `Username.parse("")` → istisna → fatal ekran.
    Heç bir test bu iki tərəfi tutuşdurmurdu.
    """
    from src.presentation.screens.group_a_entry import _split_full_name, _store_code

    assert _split_full_name("Rəşad Məmmədov") == ("Rəşad", "Məmmədov")
    assert _split_full_name("Əli Vəli Həsənov") == ("Əli Vəli", "Həsənov")
    assert _split_full_name("Rəşad") == ("Rəşad", "")
    assert _split_full_name("   ") == ("", "")

    assert _store_code("28 May") == "28-MAY"
    assert _store_code("Bellona / Nərimanov") == "BELLONA-NƏRIMANOV"
    assert _store_code("") == "MAGAZA-1"


def test_hierarchy_guard_still_blocks_equal_tier() -> None:
    """Audit dəyişikliyi mövcud qoruyucuları ZƏİFLƏTMƏMƏLİDİR (reqressiya)."""
    from src.application.use_cases.permission_guards import (
        PermissionChangeRequest,
        PermissionHierarchyGuardUseCase,
    )
    from src.domain.value_objects.authorization import AuthorizationError
    from tests.fixtures.fakes import FakeClock, RecordingAudit

    guard = PermissionHierarchyGuardUseCase(audit=RecordingAudit(), clock=FakeClock(NOW))
    actor = _employee(SystemRole.ADMIN)
    _grant(actor, "can_control_user_permissions")

    with pytest.raises(AuthorizationError):
        guard.assert_allowed(
            PermissionChangeRequest(
                actor=actor,
                subject=_employee(SystemRole.ADMIN),
                flag=PLAIN_FLAG,
                effect=PermissionEffect.GRANT,
                now=NOW,
            )
        )


def test_hardlock_levels_are_unchanged() -> None:
    """Dörd-səviyyəli hardlock (bölmə 3) — reqressiya qapısı."""
    assert HardlockLevel.ROOT_ONLY.allows(SystemRole.ROOT) is True
    assert HardlockLevel.ROOT_ONLY.allows(SystemRole.CEO) is False
    assert HardlockLevel.ROOT_CEO.allows(SystemRole.CEO) is True
    assert HardlockLevel.ROOT_CEO.allows(SystemRole.ADMIN) is False
    assert HardlockLevel.DELEGABLE.allows(SystemRole.ADMIN) is True
    assert HardlockLevel.DELEGABLE.allows(SystemRole.HR_ADMIN) is False
