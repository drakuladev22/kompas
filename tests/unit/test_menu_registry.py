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


def test_permission_matrix_is_gated_by_the_flag_its_use_case_actually_requires() -> None:
    """İcazə Matrisi `can_manage_positions` tələb etməlidir — EKRANIN QAPISI İLƏ EYNİ.

    `can_manage_permissions` YALNIZ `Root`-a hardlock-dur (bölmə 3) və yeni
    FLAG yaratmaq üçündür — Permission Registry-də yaşayır, bu ekran deyil.

    QAPI ƏVVƏL `can_control_user_permissions` İDİ VƏ BU, ÖLÜ BƏND YARADIRDI
    (QA-FULL Faza 3, canlı sınaq): ekran `PositionManagementUseCase`-ə
    bağlıdır və o, `can_manage_positions` tələb edir (hardlock 2, Root/CEO).
    Yalnız menyu flag-i olan `Admin` bəndi görürdü, klik isə HƏR dəfə boş
    xəta ilə bitirdi. «GÖRMƏK = SƏLAHİYYƏTİN OLMASI» qaydası menyu tərəfinin
    düzəldilməsini tələb edir; use case-in hardlock-u struktur zəmanətdir və
    ekranın xatirinə zəiflədilmir (bax `menu.py`-dəki tam əsaslandırma).

    BU TEST MƏHZ HƏMİN İKİ QAPININ EYNİLİYİNİ QORUYUR — ayrılan an ölü bənd
    geri qayıdır.
    """
    from src.application.use_cases.position_management import MANAGE_POSITIONS_FLAG

    entry = next(e for e in DEFAULT_ENTRIES if e.key == "permissions")
    assert entry.required_flag == MANAGE_POSITIONS_FLAG


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


#: Səlahiyyət tələb ETMƏYƏN maddələr — hər biri üçün səbəb yazılıb.
#: Siyahı testin ÖZÜNDƏ saxlanılır ki, bir maddənin flag-i təsadüfən
#: silinəndə test onu tutsun (`menu.py`-dan oxusaydıq, yoxlama özünü
#: təsdiqləyən tavtologiyaya çevrilərdi).
_FLAGLESS_KEYS: Final[dict[str, str]] = {
    "dashboard": "Hər kəsə öz səlahiyyəti çərçivəsində görünür",
    "help": "Yardım mərkəzi — məlumat səthi",
    "settings": "Yalnız şəxsi tənzimləmələr (tema, bildiriş)",
    "profile": "Öz profili",
    "sales_points": "Öz xal balansı — self-service (bölmə 6, İşçi Ana Ekranı)",
}


@pytest.mark.parametrize("key", sorted(_FLAGLESS_KEYS), ids=sorted(_FLAGLESS_KEYS))
def test_self_service_entries_are_not_gated_by_a_flag(key: str) -> None:
    """Öz məlumatını görmək səlahiyyət tələb etmir.

    `sales_points` bu siyahıya sonradan əlavə edildi: ekran işçinin ÖZ
    balansıdır (`screen_data._sales_points` yalnız `actor.id` ilə işləyir),
    lakin maddə `can_manage_sales_points` tələb edirdi — bölmə 3-də MENECER
    səlahiyyəti kimi tərif olunan flag. Nəticədə heç bir flag daşımayan adi
    `Satıcı` öz xal balansını GÖRƏ BİLMİRDİ.
    """
    entry = next(e for e in DEFAULT_ENTRIES if e.key == key)
    assert entry.required_flag is None, (
        f"'{key}' maddəsi self-service-dir ({_FLAGLESS_KEYS[key]}) — "
        f"flag qapısı istifadəçini öz məlumatından kəsir"
    )


def test_manager_side_of_sales_points_keeps_its_flag() -> None:
    """`can_manage_sales_points` menyudan TAM çıxarılmır.

    «Şübhəli Satışlar» növbəsi (`sales_review_queue.py`) məhz bu flag ilə
    qorunur — self-service düzəlişi menecer qapısını zəiflətməməlidir.
    """
    entry = next(e for e in DEFAULT_ENTRIES if e.key == "unassigned_sales")
    assert entry.required_flag == "can_manage_sales_points"


def test_dashboard_builder_requires_a_permission() -> None:
    """Bölmə 6: "Yalnız bu modula icazəsi olan rollara görünür".

    Bayraqsız maddə HƏR istifadəçiyə render olunur və bu, bölmə 3-dəki
    "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" prinsipini birbaşa pozur.
    """
    entry = next(e for e in DEFAULT_ENTRIES if e.key == "dashboard_builder")
    assert entry.required_flag == "can_view_dashboard_builder"
