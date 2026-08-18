"""Yeni işçi `create()` ilə yaranır — `save()` ilə YOX.

──────────────────────────────────────────────────────────────────────────────
QAPININ SƏBƏBİ — NASAZLIQ SAHTƏLƏRDƏ GÖRÜNMÜRDÜ
──────────────────────────────────────────────────────────────────────────────
`PostgresEmployeeRepository.save()` `UPDATE`-dir: olmayan sətir üçün SIFIR
sətir dəyişdirir və heç bir xəta vermir. Yaddaşdakı sahtələrdə isə `save()`
lüğətə yazır, yəni upsert kimi davranır — nəticədə həm İlk Quraşdırma
Sihirbazı, həm də «Yeni İşçi» axını testdə keçir, CANLI BAZADA isə heç nə
yazmırdı. Qüsur yalnız növbəti xarici açar pozuntusunda üzə çıxırdı
(`audit_logs.actor_id` → «Key is not present in table "employees"»).

Ona görə burada ölçülən şey NƏTİCƏ deyil (sahtədə hər iki metod eyni nəticəni
verə bilər), HANSI METODUN çağırıldığıdır. Sahtə `save()` ilə `create()`-i
qəsdən AYRI yazır — istehsalatda da ayrıdırlar.

`create()`-in sirri ilə birlikdə yazması təsadüf deyil: `chk_employee_auth`
hər sətrin ən azı bir autentifikasiya vasitəsi İLƏ YARANMASINI tələb edir,
yəni sətri əvvəl yaradıb sonra şifrə yazmaq MÜMKÜN DEYİL.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from src.application.use_cases.first_run_setup import (
    FirstRunSetupUseCase,
    RootAccountDraft,
    StoreDraft,
)
from src.application.use_cases.user_management import EmployeeDraft, UserManagementUseCase
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import (
    PermissionFlag,
    RolePriority,
    SystemRole,
)
from src.domain.value_objects.credentials import EmailAddress, Username
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    TenantId,
    new_employee_id,
)

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
NOW = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


def _position(code: str, priority: RolePriority) -> Position:
    return Position(
        position_id=PositionId(uuid.uuid4()),
        code=code,
        name_az=code.title(),
        priority=priority,
        is_system=True,
    )


ROOT_POSITION = _position(SystemRole.ROOT.value, RolePriority.ROOT)
# Aktor işçi YARADIR — flag olmadan use case səlahiyyət xətası atır (və bu,
# düzgün davranışdır; test onu yan keçmir, sadəcə ödəyir).
ROOT_POSITION.grant(PermissionFlag(code="can_manage_employees", category="HR"))
# Sihirbaz `CEO` yaradır, `Root` YOX: `Root` təchizatçının (developer)
# pilləsidir və müştəri quraşdırmasından ona yol yoxdur (SEC-024).
CEO_POSITION = _position(SystemRole.CEO.value, RolePriority.EXECUTIVE)
SELLER_POSITION = _position(SystemRole.SELLER.value, RolePriority.STAFF)


class _Employees:
    """`save()` və `create()` AYRI qeyd olunur — fərq testin mövzusudur."""

    def __init__(self, existing: list[Employee] | None = None) -> None:
        self.items: dict[EmployeeId, Employee] = {e.id: e for e in existing or []}
        self.saved: list[Employee] = []
        self.created: list[tuple[Employee, str | None, str | None]] = []

    def get(self, employee_id: EmployeeId) -> Employee | None:
        return self.items.get(employee_id)

    def get_by_username(self, tenant_id: TenantId, username: Any) -> Employee | None:
        return None

    def find_by_pin_candidates(self, tenant_id: TenantId, store_id: Any) -> list[Employee]:
        return []

    def count_active_with_flag(self, tenant_id: TenantId, flag_code: str) -> int:
        return sum(
            1
            for employee in self.items.values()
            if employee.is_active and employee.has_permission(flag_code, now=NOW)
        )

    def count_active_ranked_at_or_above(self, tenant_id: TenantId, priority: Any) -> int:
        """İyerarxiya pilləsinə görə sayğac (SETUP-3) — `<=`, 0 ən yüksəkdir."""
        return sum(
            1
            for employee in self.items.values()
            if employee.is_active and employee.position.priority <= priority
        )

    def save(self, employee: Employee) -> None:
        self.items[employee.id] = employee
        self.saved.append(employee)

    def create(
        self,
        employee: Employee,
        *,
        raw_password: str | None = None,
        raw_pin: str | None = None,
    ) -> None:
        self.items[employee.id] = employee
        self.created.append((employee, raw_password, raw_pin))

    def update_credentials(self, employee_id: EmployeeId, **_: Any) -> None:
        return None


class _Positions:
    def get_by_code(self, tenant_id: TenantId, code: str) -> Position | None:
        return {
            SystemRole.ROOT.value: ROOT_POSITION,
            SystemRole.CEO.value: CEO_POSITION,
            SystemRole.SELLER.value: SELLER_POSITION,
        }.get(code)

    def get(self, position_id: PositionId) -> Position | None:
        return None

    def list_for_tenant(self, tenant_id: TenantId) -> list[Position]:
        return [ROOT_POSITION, CEO_POSITION, SELLER_POSITION]

    def save(self, position: Position) -> None:
        return None


class _Credentials:
    def __init__(self) -> None:
        self.calls: list[EmployeeId] = []

    def set_password(self, employee_id: EmployeeId, **_: Any) -> None:
        self.calls.append(employee_id)

    def set_pin(self, employee_id: EmployeeId, **_: Any) -> None:
        self.calls.append(employee_id)

    def clear_pin_lockout(self, employee_id: EmployeeId) -> None:
        return None


class _Stores:
    def create(self, **_: Any) -> None:
        return None

    def get_id_by_code(self, tenant_id: TenantId, code: str) -> None:
        return None


class _Provisioning:
    def ensure_self_hosted_tenant(self, **_: Any) -> bool:
        return True


class _Audit:
    def __init__(self) -> None:
        self.actions: list[str] = []

    def record(self, **kwargs: Any) -> None:
        self.actions.append(str(kwargs.get("action")))


class _Clock:
    def now(self) -> datetime:
        return NOW


def _root_actor() -> Employee:
    return Employee(
        employee_id=new_employee_id(),
        tenant_id=TENANT,
        position=ROOT_POSITION,
        first_name="Kök",
        last_name="İstifadəçi",
        username=Username.parse("root.actor"),
        has_password=True,
    )


# --------------------------------------------------------------------------- #
# İlk Quraşdırma Sihirbazı
# --------------------------------------------------------------------------- #


def test_wizard_creates_the_executive_row_with_its_secret() -> None:
    employees = _Employees()
    use_case = FirstRunSetupUseCase(
        employees=employees,  # type: ignore[arg-type]
        positions=_Positions(),  # type: ignore[arg-type]
        stores=_Stores(),  # type: ignore[arg-type]
        audit=_Audit(),  # type: ignore[arg-type]
        clock=_Clock(),  # type: ignore[arg-type]
        provisioning=_Provisioning(),  # type: ignore[arg-type]
    )

    use_case.complete(
        tenant_id=TENANT,
        root=RootAccountDraft(
            first_name="Elvin",
            last_name="Məmmədov",
            username=Username.parse("elvin.root"),
            password="UzunVeGucluSifre123",
            recovery_email=EmailAddress.parse("root@kompas.az"),
        ),
        stores=[StoreDraft(code="BAK-001", name="Babək", brand="Yataş")],
        provision_tenant=True,
    )

    assert employees.saved == [], "`save()` yeni sətri YARATMIR — çağırılmamalıdır"
    assert len(employees.created) == 1
    employee, raw_password, _raw_pin = employees.created[0]
    assert raw_password == "UzunVeGucluSifre123"
    # İLK hesab şifrəni ÖZÜ seçir — məcburi dəyişmə YOXDUR (bölmə 2).
    assert employee.must_change_password is False
    # Rol `CEO`-dur: sihirbaz müştəriyə təchizatçı pilləsi vermir (SEC-024).
    assert employee.position.code == SystemRole.CEO.value


# --------------------------------------------------------------------------- #
# «Yeni İşçi» (adi axın + CSV toplu idxalı eyni yolu işlədir)
# --------------------------------------------------------------------------- #


def test_user_management_creates_the_row_with_its_secret() -> None:
    actor = _root_actor()
    employees = _Employees([actor])
    use_case = UserManagementUseCase(
        employees=employees,  # type: ignore[arg-type]
        credentials=_Credentials(),  # type: ignore[arg-type]
        audit=_Audit(),  # type: ignore[arg-type]
        clock=_Clock(),  # type: ignore[arg-type]
    )

    use_case.create_employee(
        tenant_id=TENANT,
        actor=actor,
        employee_id=new_employee_id(),
        draft=EmployeeDraft(
            first_name="Yeni",
            last_name="Satıcı",
            position=SELLER_POSITION,
            username=Username.parse("yeni.satici"),
        ),
        initial_password="MuveqqetiSifre2026",
    )

    assert employees.saved == [], "`save()` yeni sətri YARATMIR — çağırılmamalıdır"
    employee, raw_password, raw_pin = employees.created[0]
    assert raw_password == "MuveqqetiSifre2026"
    assert raw_pin is None
    # Admin şifrəni təyin etdiyi üçün işçi onu DƏYİŞMƏLİDİR (bölmə 2).
    assert employee.must_change_password is True


def test_pin_only_employee_is_created_with_the_pin() -> None:
    """PIN-li işçidə də sətir sirri ilə birlikdə yaranır.

    `chk_employee_auth` `pin_hash`-i də qəbul edir; şifrə YOXDURSA sətir
    yalnız PIN ilə keçərlidir — yəni PIN də YARADILIŞ anında yazılmalıdır.
    """
    actor = _root_actor()
    employees = _Employees([actor])
    use_case = UserManagementUseCase(
        employees=employees,  # type: ignore[arg-type]
        credentials=_Credentials(),  # type: ignore[arg-type]
        audit=_Audit(),  # type: ignore[arg-type]
        clock=_Clock(),  # type: ignore[arg-type]
    )

    use_case.create_employee(
        tenant_id=TENANT,
        actor=actor,
        employee_id=new_employee_id(),
        draft=EmployeeDraft(first_name="Kassir", last_name="İşçi", position=SELLER_POSITION),
        initial_pin="4821",
    )

    employee, raw_password, raw_pin = employees.created[0]
    assert raw_password is None
    assert raw_pin == "4821"
    assert employee.has_pin is True
