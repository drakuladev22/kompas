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


# --------------------------------------------------------------------------- #
# Spesifikasiya uyğunluğu — icazə qapıları (bölmə 3 və 6)
# --------------------------------------------------------------------------- #


def test_permission_matrix_is_gated_by_the_delegable_flag() -> None:
    """İcazə Matrisi `can_control_user_permissions` tələb etməlidir.

    `can_manage_permissions` YALNIZ `Root`-a hardlock-dur (bölmə 3) və yeni
    FLAG yaratmaq üçündür — Permission Registry-də yaşayır. Matris ekranı isə
    mövcud flag-ləri paylayır; bölmə 3 açıq deyir ki, `Admin` onu görür. Səhv
    qapı ilə `Admin` VƏ `CEO` ekranı heç vaxt aça bilmirdi, yəni səlahiyyətin
    həvalə edilməsi — `Admin` rolunun bütün mövcudluq səbəbi — işləmirdi.
    """
    entry = next(e for e in DEFAULT_ENTRIES if e.key == "permissions")
    assert entry.required_flag == "can_control_user_permissions"


def test_feature_module_keys_match_the_toggle_namespace() -> None:
    """Menyudakı `feature_module` dəyəri `feature_toggles` açarı OLMALIDIR.

    Bu, `required_flag` yoxlamasının toggle-lar üçün eynisidir və eyni səbəbə
    görə lazımdır: uyğunsuz ad heç bir xəta vermir. `AdminShell`-ə ötürülən
    `enabled_modules` dəsti `FeatureModule` dəyərlərini saxlayır; menyu ayrı
    ad məkanı işlətsəydi (`"fines"` ↔ `"FINE_MODULE"`) `entry.feature_module
    not in modules` HƏMİŞƏ doğru olardı və Root modulu söndürsə belə maddə
    görünməyə davam edərdi — yəni bölmə 3-dəki DYNAMIC UI INTEGRATION sükutla
    işləməzdi. Layihədə məhz bu qüsur var idi.
    """
    from src.domain.policies import FeatureModule

    known = {module.value for module in FeatureModule}
    for entry in DEFAULT_ENTRIES:
        if entry.feature_module is None:
            continue
        assert entry.feature_module in known, (
            f"'{entry.key}' maddəsi `FeatureModule`-da olmayan "
            f"'{entry.feature_module}' modul açarına istinad edir — "
            f"toggle bu maddəni heç vaxt gizlədə bilməyəcək"
        )


def test_toggle_backed_modules_are_actually_used_by_the_menu() -> None:
    """Söndürüləndə görünən nəticəsi olan modullar menyuda təmsil olunmalıdır.

    `DUAL_CONTROL` və `SUPPORT_CHAT` istisna edilib: onlar öz menyu maddəsi
    olmayan, iş axınının İÇİNDƏ yaşayan qatlardır (əlavə təsdiq addımı və
    üst paneldəki dəstək paneli), ona görə naviqasiyadan kəsilə bilməzlər.
    """
    from src.domain.policies import FeatureModule

    embedded = {FeatureModule.DUAL_CONTROL.value, FeatureModule.SUPPORT_CHAT.value}
    used = {entry.feature_module for entry in DEFAULT_ENTRIES if entry.feature_module}
    missing = {module.value for module in FeatureModule} - embedded - used
    assert not missing, f"Bu modulların menyu təmsilçisi yoxdur: {sorted(missing)}"


def test_dashboard_builder_requires_a_permission() -> None:
    """Bölmə 6: "Yalnız bu modula icazəsi olan rollara görünür".

    Bayraqsız maddə HƏR istifadəçiyə render olunur və bu, bölmə 3-dəki
    "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" prinsipini birbaşa pozur.
    """
    entry = next(e for e in DEFAULT_ENTRIES if e.key == "dashboard_builder")
    assert entry.required_flag == "can_view_dashboard_builder"
