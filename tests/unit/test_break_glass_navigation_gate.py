"""Fövqəladə giriş menyu marşrutu — `v2backlog.md` Faza 5.4.

Ehtiyat-admin HEÇ BİR flag daşımır; maddənin görünürlüyü zəng edənin ötürdüyü
`alternate_admission` ilə açılır (`navigation.NavigationRegistry`). Bu qapı
üç sualı cavablandırır:

1. Flag daşıyanlar (Root/CEO) köhnə yolla görür — davranış DƏYİŞMƏDİ;
2. Callable YALNIZ öz maddəsinə təsir edir — başqa flag-qapılı maddələr
   callable ilə AÇILMIR;
3. Feature Toggle söndürülmüş modulu heç vaxt bərpa ETMİR — callable
   toggle yoxlamasından YÜKSƏKDİR və ona çatmır.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.application.use_cases.break_glass import APPROVE_BREAK_GLASS_FLAG
from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import PermissionEffect, RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import EmployeeId, TenantId
from src.presentation.navigation import MenuEntry, NavigationRegistry
from src.presentation.shell.menu import DEFAULT_ENTRIES

NOW = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)
TENANT = TenantId(uuid.uuid4())


def _employee(*, flags: tuple[str, ...] = ()) -> Employee:
    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=Position(
            position_id=uuid.uuid4(),  # type: ignore[arg-type]
            code="ADMIN",
            name_az="Admin",
            priority=RolePriority.ADMIN,
            tenant_id=TENANT,
            is_system=True,
        ),
        first_name="Ad",
        last_name="Soyad",
        username=Username(f"u.{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )
    for flag in flags:
        employee.apply_override(
            PermissionOverride(
                flag_code=flag, effect=PermissionEffect.GRANT, granted_by=employee.id
            )
        )
    return employee


def _registry() -> NavigationRegistry:
    registry = NavigationRegistry()
    registry.register_all(list(DEFAULT_ENTRIES))
    return registry


def _admit_only_break_glass(entry: MenuEntry) -> bool:
    return bool(entry.key == "break_glass")


def test_the_entry_is_gated_by_the_approver_flag() -> None:
    entry = next(e for e in DEFAULT_ENTRIES if e.key == "break_glass")
    assert entry.required_flag == APPROVE_BREAK_GLASS_FLAG


def test_flag_holder_sees_the_entry_without_admission() -> None:
    """Köhnə yol DƏYİŞMƏDİ — callable olmadan da Root/CEO maddəni görür."""
    registry = _registry()
    holder = _employee(flags=(APPROVE_BREAK_GLASS_FLAG,))
    keys = [entry.key for entry in registry.visible_for(holder, now=NOW)]
    assert "break_glass" in keys


def test_the_trustee_is_admitted_through_the_alternate_gate() -> None:
    """Flagı OLMAYAN ehtiyat-admin callable ilə daxil olur — mexanizmin ÖZÜ."""
    registry = _registry()
    trustee = _employee()

    assert "break_glass" not in [entry.key for entry in registry.visible_for(trustee, now=NOW)]
    admitted = [
        entry.key
        for entry in registry.visible_for(
            trustee, now=NOW, alternate_admission=_admit_only_break_glass
        )
    ]
    assert "break_glass" in admitted
    # Deep-link qoruması EYNİ qapıdan keçir — sidebar klikinə bərabərdir.
    assert registry.is_visible(
        "break_glass", trustee, now=NOW, alternate_admission=_admit_only_break_glass
    )


def test_the_admission_never_opens_other_flagged_entries() -> None:
    """Callable «break_glass»-dan KƏNAR heç bir maddəyə açar vermir."""
    registry = _registry()
    stranger = _employee()
    before = {e.key for e in registry.visible_for(stranger, now=NOW)}
    after = {
        e.key: None
        for e in registry.visible_for(
            stranger, now=NOW, alternate_admission=_admit_only_break_glass
        )
    }
    assert set(after) - before == {"break_glass"}
    assert registry.is_visible("audit", stranger, now=NOW) is False
    assert (
        registry.is_visible("audit", stranger, now=NOW, alternate_admission=_admit_only_break_glass)
        is False
    )


def test_a_disabled_module_stays_hidden_despite_admission() -> None:
    """Toggle yoxlaması callable-dan YÜKSƏKDİR — sınmadıqda belə saxlanmalı.

    `break_glass` toggle-SİZ maddədir (infrastruktur qapısı), ona görə bu test
    toggle-LI QONŞUSU üzərində qurulur: `live_queue` maddəsi həm flag, həm
    toggle (`MODULE_CAMERA`) daşıyır. Callable HƏR KƏSİ buraxan olsa belə,
    boş modul dəstində maddə GİZLİ QALMALIDIR — yoxlama sırası
    («modul → flag → admission») burada kilidlənir.
    """
    entry = next(e for e in DEFAULT_ENTRIES if e.key == "break_glass")
    # Maddəni toggle-SİZ saxlamaq STRUKTUR qərarıdır (bax `menu.py` başlığı):
    # «Root əlçatmaz olanda işləyən yol»u modul açarı ilə söndürmək olmazdı.
    assert entry.feature_module is None

    def admit_everything(candidate: MenuEntry) -> bool:
        return True

    registry = _registry()
    stranger = _employee()
    visible = {
        e.key: None
        for e in registry.visible_for(
            stranger,
            now=NOW,
            enabled_modules=frozenset(),
            alternate_admission=admit_everything,
        )
    }
    # Boş modul dəsti = bütün toggle-LI maddələr gizlidir; callable onları
    # BƏRPA ETMİR. Yalnız toggle-siz maddə callable-in öz seçimi ilə görünür.
    assert "live_queue" not in visible
    assert "break_glass" in visible


def test_orders_around_the_infrastructure_cluster_are_unique() -> None:
    orders = sorted(e.order for e in DEFAULT_ENTRIES)
    assert len(orders) == len(set(orders))
    entry = next(e for e in DEFAULT_ENTRIES if e.key == "break_glass")
    assert 167 < entry.order < 170
