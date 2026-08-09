"""Naviqasiya reyestrinin bütövlüyü — Faza 4.2.

`shell/menu.py` sənədləşməsində vəd edilən yoxlama məhz budur: hər menyu
maddəsinin `required_flag` dəyəri `database/schema.sql`-dakı icazə reyestrində
MÖVCUD olmalıdır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TEST VACİBDİR
──────────────────────────────────────────────────────────────────────────────
Səhv yazılmış flag adı (`can_manage_shift` ↔ `can_manage_shifts`) heç bir
xəta vermir: `Employee.has_permission()` sadəcə `False` qaytarır və maddə
HƏMİŞƏ gizli qalır. Nəticədə bölmə "yoxa çıxır", səbəbi isə heç bir jurnalda
görünmür. Belə qüsuru yalnız statik uyğunluq yoxlaması tutur.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from src.presentation.shell.menu import DEFAULT_ENTRIES, build_default_registry

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA_FILE: Final = PROJECT_ROOT / "database" / "schema.sql"
MIGRATIONS_DIR: Final = PROJECT_ROOT / "database" / "migrations"

#: `can_...` şəklindəki bütün flag adları.
_FLAG_PATTERN: Final = re.compile(r"\bcan_[a-z0-9_]+\b")


def _schema_flags() -> frozenset[str]:
    """Sxem və miqrasiyalarda adı keçən bütün icazə flag-ləri."""
    sources = [SCHEMA_FILE, *sorted(MIGRATIONS_DIR.glob("*.sql"))]
    found: set[str] = set()
    for path in sources:
        if path.exists():
            found.update(_FLAG_PATTERN.findall(path.read_text(encoding="utf-8")))
    return frozenset(found)


def test_schema_file_is_readable() -> None:
    """Qapı: sxem tapılmasa, aşağıdakı test yanlış olaraq "keçər"."""
    assert SCHEMA_FILE.exists(), f"schema.sql tapılmadı: {SCHEMA_FILE}"
    assert _schema_flags(), "Sxemdə heç bir `can_*` flag-i tapılmadı"


@pytest.mark.parametrize(
    "entry",
    DEFAULT_ENTRIES,
    ids=lambda entry: entry.key,  # type: ignore[misc]
)
def test_required_flag_exists_in_schema(entry) -> None:  # type: ignore[no-untyped-def]
    """Hər maddənin flag-i icazə reyestrində olmalıdır."""
    if entry.required_flag is None:
        pytest.skip("Flag tələb etmir (hər istifadəçi görür)")
    assert entry.required_flag in _schema_flags(), (
        f"'{entry.key}' maddəsi sxemdə olmayan '{entry.required_flag}' "
        f"flag-inə istinad edir — bölmə heç kimə görünməyəcək"
    )


def test_keys_are_unique() -> None:
    """Təkrarlanan açar reyestrdə istisna atır — burada erkən tutulur."""
    keys = [entry.key for entry in DEFAULT_ENTRIES]
    assert len(keys) == len(set(keys)), "Menyu açarları təkrarlanır"


def test_orders_are_unique() -> None:
    """Eyni `order` iki maddəni sabit olmayan sıraya salır."""
    orders = [entry.order for entry in DEFAULT_ENTRIES]
    assert len(orders) == len(set(orders)), "İki maddənin `order` dəyəri eynidir"


def test_every_entry_has_an_icon() -> None:
    """İkonsuz maddə sətri sola sürüşdürər (bax `sidebar.FALLBACK_ICON`)."""
    from src.presentation.widgets import icons

    for entry in DEFAULT_ENTRIES:
        assert entry.icon is not None, f"'{entry.key}' üçün ikon təyin edilməyib"
        assert entry.icon in icons.available(), (
            f"'{entry.key}' maddəsi mövcud olmayan '{entry.icon}' ikonuna istinad edir"
        )


def test_registry_builds_fresh_instances() -> None:
    """Hər çağırış TƏZƏ reyestr qaytarmalıdır (testlər arası sızma olmasın)."""
    first = build_default_registry()
    second = build_default_registry()
    assert first is not second
    assert len(first.all_entries) == len(DEFAULT_ENTRIES)
