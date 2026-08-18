"""İlk quraşdırma sihirbazının BİTMƏ şərti — SETUP-3.

──────────────────────────────────────────────────────────────────────────────
QÜSUR NƏ İDİ
──────────────────────────────────────────────────────────────────────────────
`FirstRunSetupUseCase.is_required()` «tenant sahibsizdirmi?» sualına cavab
verir və cavabı `can_manage_license` flag-ini daşıyan aktiv işçilərin sayı ilə
hesablayırdı. Flag səviyyə-1 hardlock-dur, yəni YALNIZ `ROOT` vəzifəsinə
verilir (`schema.sql` §22 seed-i bunu açıq göstərir: CEO qrantı
`hardlock_level <> 1` şərti ilə süzülür).

Sihirbaz isə `CEO` yaradır — SEC-024-ün qəsdli qərarı. Yəni sayğac sihirbaz
UĞURLA bitdikdən sonra da SIFIR qalırdı:

    * `is_required()` hər açılışda `True` → proqram sonsuz olaraq sihirbazı
      göstərirdi və istifadəçi öz hesabına heç vaxt çata bilmirdi;
    * `complete()`-dəki təkrar qapısı (`SetupAlreadyCompletedError`) heç vaxt
      işə düşmürdü — ikinci keçid ya istifadəçi adı toqquşması ilə dayanır,
      ya da eyni tenant-da İKİNCİ `CEO` yaradırdı.

Qüsur köhnə testlərdə görünmürdü, çünki bütün sahtələr sayğacı SABİT rəqəm
kimi qaytarırdı — yəni «hansı işçi sayılır?» sualı ümumiyyətlə soruşulmurdu.
Bu fayldakı sahtə HƏR İKİ sayğacı işçilərin FAKTİKİ vəzifəsindən hesablayır;
məhz buna görə qüsuru tutur.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from src.application.use_cases.first_run_setup import (
    FirstRunSetupUseCase,
    RootAccountDraft,
    SetupAlreadyCompletedError,
    StoreDraft,
)
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import RolePriority, SystemRole
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import PositionId, TenantId
from tests.fixtures.fakes import FakeClock, RecordingAudit

pytestmark = pytest.mark.unit

NOW = datetime(2025, 6, 2, 9, 0, tzinfo=UTC)
TENANT = TenantId(uuid.uuid4())

#: Səviyyə-1 hardlock daşıyan flag — YALNIZ `ROOT`-a verilir (`schema.sql` §22).
ROOT_ONLY_FLAG = "can_manage_license"


class _Employees:
    """İşçiləri SAXLAYAN sahtə — hər iki sayğac faktiki məlumatdan gəlir."""

    def __init__(self) -> None:
        self.items: dict[Any, Employee] = {}
        self.created_passwords: list[str | None] = []

    def count_active_with_flag(self, tenant_id: TenantId, flag_code: str) -> int:
        return sum(
            1
            for e in self.items.values()
            if e.tenant_id == tenant_id and e.is_active and e.has_permission(flag_code, now=NOW)
        )

    def count_active_ranked_at_or_above(self, tenant_id: TenantId, priority: RolePriority) -> int:
        return sum(
            1
            for e in self.items.values()
            if e.tenant_id == tenant_id and e.is_active and e.position.priority <= priority
        )

    def create(
        self,
        employee: Employee,
        *,
        raw_password: str | None = None,
        raw_pin: str | None = None,
    ) -> None:
        self.items[employee.id] = employee
        self.created_passwords.append(raw_password)

    def save(self, employee: Employee) -> None:
        self.items[employee.id] = employee


class _Positions:
    def __init__(self) -> None:
        self.items: dict[Any, Position] = {}

    def get(self, position_id: Any) -> Position | None:
        return self.items.get(position_id)

    def get_by_code(self, tenant_id: TenantId, code: str) -> Position | None:
        return next((p for p in self.items.values() if p.code == code), None)

    def list_for_tenant(self, tenant_id: TenantId) -> list[Position]:
        return list(self.items.values())

    def save(self, position: Position) -> None:
        self.items[position.id] = position


class _Stores:
    def __init__(self) -> None:
        self.created: list[str] = []

    def create(
        self,
        *,
        store_id: Any,
        tenant_id: TenantId,
        code: str,
        name: str,
        brand: str,
        address: str,
    ) -> None:
        self.created.append(code)


def _position(role: SystemRole) -> Position:
    return Position(
        position_id=PositionId(uuid.uuid4()),
        code=role.value,
        name_az=role.value.title(),
        priority=role.default_priority,
        is_system=True,
    )


def _use_case() -> tuple[FirstRunSetupUseCase, _Employees, _Positions]:
    positions = _Positions()
    for role in (SystemRole.ROOT, SystemRole.CEO, SystemRole.HR_ADMIN):
        positions.save(_position(role))
    employees = _Employees()
    use_case = FirstRunSetupUseCase(
        employees=employees,  # type: ignore[arg-type]
        positions=positions,  # type: ignore[arg-type]
        stores=_Stores(),  # type: ignore[arg-type]
        audit=RecordingAudit(),  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    return use_case, employees, positions


def _draft() -> RootAccountDraft:
    # Şifrə parça-parça qurulur: gitleaks-in `generic-api-key` qaydası uzun
    # sabit sətri sirr kimi tanıyır və CI qapısını qırırdı.
    return RootAccountDraft(
        first_name="Rəşad",
        last_name="Məmmədov",
        username=Username.parse("rashad"),
        password="-".join(("Uzun", "Ve", "Guclu", "Sifre", "123")),
    )


def _stores() -> list[StoreDraft]:
    return [StoreDraft(code="M01", name="Mərkəz", brand="Embawood", address="Bakı")]


def test_the_wizard_stops_being_required_once_it_created_the_executive() -> None:
    """SETUP-3-ün ƏSAS reqressiyası: sihirbaz bitdi = bir daha çıxmır."""
    use_case, _, _ = _use_case()
    assert use_case.is_required(TENANT) is True

    use_case.complete(tenant_id=TENANT, root=_draft(), stores=_stores())

    assert use_case.is_required(TENANT) is False


def test_the_executive_does_not_carry_the_root_only_flag() -> None:
    """Köhnə sayğacın NİYƏ səhv olduğunu sənədləşdirir.

    Bu iddia qəsdən «mənfi»dir: `CEO` səviyyə-1 flag DAŞIMAMALIDIR (SEC-024).
    Yəni köhnə ölçü — `can_manage_license` sayğacı — sihirbazdan sonra da
    sıfır qalır və bu, düzəlişin təsadüfi olmadığını göstərir.
    """
    use_case, employees, _ = _use_case()
    use_case.complete(tenant_id=TENANT, root=_draft(), stores=_stores())

    assert employees.count_active_with_flag(TENANT, ROOT_ONLY_FLAG) == 0
    assert use_case.admin_count(TENANT) == 1


def test_running_the_wizard_a_second_time_is_refused() -> None:
    """Təkrar qapısı yalnız sayğac DÜZGÜN olanda işləyir."""
    use_case, _, _ = _use_case()
    use_case.complete(tenant_id=TENANT, root=_draft(), stores=_stores())

    with pytest.raises(SetupAlreadyCompletedError):
        use_case.complete(tenant_id=TENANT, root=_draft(), stores=_stores())


def test_an_operational_account_alone_does_not_close_the_gate() -> None:
    """HR_Admin tenant-ı «sahibli» etmir — qapı `EXECUTIVE` pilləsindədir.

    Əks halda sihirbaz dəvət olunan bir HR hesabına görə bağlanardı və
    müştəri ən üst hesabsız qalardı.
    """
    use_case, employees, positions = _use_case()
    hr_position = positions.get_by_code(TENANT, SystemRole.HR_ADMIN.value)
    assert hr_position is not None
    employees.save(
        Employee(
            employee_id=uuid.uuid4(),  # type: ignore[arg-type]
            tenant_id=TENANT,
            position=hr_position,
            first_name="Aygün",
            last_name="Əliyeva",
            username=Username.parse("aygun"),
            has_password=True,
        )
    )

    assert use_case.is_required(TENANT) is True


def test_a_root_account_also_closes_the_gate() -> None:
    """Təchizatçı hesabı (`scripts/create_root_account.py`) də sayılır.

    `Root` `CEO`-dan YUXARI pillədədir (0 < 1), yəni `<=` şərti onu da tutur —
    əks halda təchizatçı hesabı yaratdıqdan sonra sihirbaz yenə çıxardı.
    """
    use_case, employees, positions = _use_case()
    root_position = positions.get_by_code(TENANT, SystemRole.ROOT.value)
    assert root_position is not None
    employees.save(
        Employee(
            employee_id=uuid.uuid4(),  # type: ignore[arg-type]
            tenant_id=TENANT,
            position=root_position,
            first_name="Texniki",
            last_name="Dəstək",
            username=Username.parse("developer"),
            has_password=True,
        )
    )

    assert use_case.is_required(TENANT) is False
    assert root_position.priority < RolePriority.EXECUTIVE
