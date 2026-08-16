"""Özünə-host edilən ilk quraşdırma tenant sətrini ÖZÜ yaradır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU QAPI VAR
──────────────────────────────────────────────────────────────────────────────
Bütün cədvəllərdə `tenant_id` sütunu `license_tenants(tenant_id)`-ə xarici
açarla bağlıdır. Sətir yoxdursa sihirbaz ilk mağazanı belə yarada bilmir —
yəni "boş bazada ilk açılış" ssenarisi FK pozuntusu ilə bitərdi. Sxemin özü
bunu gözləyirdi (`seed_tenant_defaults()` şərhi), sadəcə çağıran tərəf yox idi.

SIRA DA ÖLÇÜLÜR: tenant sətri ROLLARDAN əvvəl yaradılmalıdır, çünki rollar
həmin sətrə bağlı `seed_tenant_defaults()` çağırışından gəlir.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from src.application.use_cases.first_run_setup import (
    FirstRunSetupUseCase,
    RootAccountDraft,
    SetupValidationError,
    StoreDraft,
)
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import RolePriority, SystemRole
from src.domain.value_objects.credentials import EmailAddress, Username
from src.domain.value_objects.identifiers import PositionId, TenantId

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _Provisioning:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def ensure_self_hosted_tenant(
        self, *, tenant_id: TenantId, name: str, contact_email: str
    ) -> bool:
        self.calls.append((name, contact_email))
        return True


class _Positions:
    """Rollar YALNIZ provizyondan SONRA görünür — sıranı bu sinif ölçür."""

    def __init__(self, provisioning: _Provisioning) -> None:
        self._provisioning = provisioning
        self._root = Position(
            position_id=PositionId(uuid.uuid4()),
            code=SystemRole.ROOT.value,
            name_az="Root",
            priority=RolePriority.EXECUTIVE,
            is_system=True,
        )

    def get_by_code(self, tenant_id: TenantId, code: str) -> Position | None:
        if not self._provisioning.calls:
            return None
        return self._root if code == SystemRole.ROOT.value else None


class _Employees:
    def __init__(self) -> None:
        self.saved: list[Any] = []
        self.passwords: list[str | None] = []

    def count_active_with_flag(self, tenant_id: TenantId, flag: str) -> int:
        return 0

    def save(self, employee: Any) -> None:
        self.saved.append(employee)

    def create(
        self, employee: Any, *, raw_password: str | None = None, raw_pin: str | None = None
    ) -> None:
        self.saved.append(employee)
        self.passwords.append(raw_password)


class _Stores:
    def __init__(self) -> None:
        self.created: list[str] = []

    def create(self, *, store_id: Any, tenant_id: TenantId, code: str, **_: Any) -> None:
        self.created.append(code)

    def get_id_by_code(self, tenant_id: TenantId, code: str) -> None:
        return None


class _Audit:
    def __init__(self) -> None:
        self.records: list[str] = []

    def record(self, **kwargs: Any) -> None:
        self.records.append(str(kwargs.get("action")))


class _Clock:
    def now(self) -> Any:
        from datetime import UTC, datetime

        return datetime.now(UTC)


def _use_case() -> tuple[FirstRunSetupUseCase, _Provisioning, _Stores, _Employees]:
    provisioning = _Provisioning()
    stores = _Stores()
    employees = _Employees()
    use_case = FirstRunSetupUseCase(
        employees=employees,  # type: ignore[arg-type]
        positions=_Positions(provisioning),  # type: ignore[arg-type]
        stores=stores,  # type: ignore[arg-type]
        audit=_Audit(),  # type: ignore[arg-type]
        clock=_Clock(),  # type: ignore[arg-type]
        provisioning=provisioning,  # type: ignore[arg-type]
    )
    return use_case, provisioning, stores, employees


def _root(*, email: str | None = "root@kompas.az") -> RootAccountDraft:
    return RootAccountDraft(
        first_name="Elvin",
        last_name="Məmmədov",
        username=Username.parse("elvin.root"),
        password="Kompas!2026",
        recovery_email=EmailAddress.parse(email) if email else None,
    )


_STORES = [StoreDraft(code="BAK-001", name="Babək filialı", brand="Yataş", address="Bakı")]


# --------------------------------------------------------------------------- #
# Testlər
# --------------------------------------------------------------------------- #


def test_self_hosted_setup_creates_the_tenant_row_first() -> None:
    """Tenant sətri ROLLARDAN ƏVVƏL yaradılır — əks halda rol tapılmazdı."""
    use_case, provisioning, stores, _employees = _use_case()

    outcome = use_case.complete(
        tenant_id=TENANT, root=_root(), stores=_STORES, provision_tenant=True
    )

    assert provisioning.calls == [("Yataş", "root@kompas.az")]
    assert stores.created == ["BAK-001"]
    assert outcome.root_employee_id is not None


def test_licensed_setup_never_creates_a_tenant_row() -> None:
    """Lisenziyalı quraşdırmada sətri TƏCHİZATÇI yaradır.

    Tətbiq onu özü yaratsaydı, «AKTIV» statuslu tenant qurmaq üçün sadəcə
    sihirbazı açmaq kifayət edərdi — yəni lisenziya qapısı yan keçilərdi.
    """
    use_case, provisioning, _stores, _employees = _use_case()
    # Rollar onsuz da mövcuddur (təchizatçı seed edib).
    provisioning.calls.append(("əvvəlcədən", "mövcuddur"))

    use_case.complete(tenant_id=TENANT, root=_root(), stores=_STORES)

    assert provisioning.calls == [("əvvəlcədən", "mövcuddur")], "port çağırılmamalıdır"


def test_self_hosted_setup_requires_a_contact_email() -> None:
    """E-poçtsuz tenant sətri YARADILMIR — bərpa kanalı olmadan qalardı."""
    use_case, provisioning, stores, employees = _use_case()

    with pytest.raises(SetupValidationError):
        use_case.complete(
            tenant_id=TENANT, root=_root(email=None), stores=_STORES, provision_tenant=True
        )

    assert provisioning.calls == []
    assert stores.created == [], "yarımçıq quraşdırma qalmamalıdır"
    assert employees.saved == []


def test_missing_provisioning_port_fails_loudly() -> None:
    """Port qoşulmayıbsa açıq xəta olur — FK pozuntusu ilə çökmür."""
    use_case = FirstRunSetupUseCase(
        employees=_Employees(),  # type: ignore[arg-type]
        positions=_Positions(_Provisioning()),  # type: ignore[arg-type]
        stores=_Stores(),  # type: ignore[arg-type]
        audit=_Audit(),  # type: ignore[arg-type]
        clock=_Clock(),  # type: ignore[arg-type]
    )

    with pytest.raises(SetupValidationError):
        use_case.complete(tenant_id=TENANT, root=_root(), stores=_STORES, provision_tenant=True)


def test_tenant_name_falls_back_to_the_store_name() -> None:
    """Brend boşdursa ad mağazanın adından götürülür — sətir adsız qalmır.

    Köməkçi BİRBAŞA çağırılır, sihirbaz axını ilə yox: `_require_text` brendi
    onsuz da məcburi edir, yəni bu hal ekrandan KEÇƏ BİLMİR. Ehtiyat yol yenə
    də ölçülür, çünki `_tenant_name` gələcəkdə başqa çağırandan da (məs. toplu
    idxal) istifadə oluna bilər.
    """
    from src.application.use_cases.first_run_setup import _tenant_name

    assert _tenant_name([StoreDraft(code="BAK-002", name="Nizami filialı", brand=" ")]) == (
        "Nizami filialı"
    )
    assert _tenant_name([]) == "KompasOS quraşdırması"
