"""Plugin interfeys səthi — səhifə və widget qeydiyyatı (audit G-3).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TESTLƏR VAR
──────────────────────────────────────────────────────────────────────────────
`PluginCapability.REGISTER_PAGE` və `RENDER_WIDGET` Faza 2-dən bəri ELAN
edilirdi, lakin `shell/menu.py`-dakı `DEFAULT_ENTRIES` və `dashboard_layout.
WIDGET_CATALOG` sabit `tuple` olduğu üçün heç bir plugin nə səhifə, nə widget
əlavə edə bilmirdi — qabiliyyət sənəddə var, icrada yox idi.

Səthin açılması TƏHLÜKƏSİZLİK səthini də açır, ona görə burada beş qapının
HƏR BİRİ ayrıca yoxlanılır:

    1. imza + təsdiq       — `PENDING_APPROVAL`/imzasız plugin səth VERMİR;
    2. qabiliyyət          — manifestdə elan olunmayan səth YARANMIR;
    3. icazə flag-i        — flagsız plugin RƏDD edilir ("GÖRMƏK = SƏLAHİYYƏT");
    4. ad toqquşması       — plugin MÖVCUD maddəni ƏVƏZ EDƏ BİLMİR;
    5. izolyasiya          — bir plugin-in istisnası UI-ni çökdürmür.

Sahtələr BU FAYLDA yerlidir (`tests/fixtures/fakes.py`-a toxunulmur) — paralel
işlərin ortaq faylı dəyişməsi riski, `test_sync_conflicts_screen.py`-dəki eyni
qərar.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Final

import pytest

from src.application.use_cases.dashboard_layout import (
    WIDGET_CATALOG,
    DashboardWidget,
    build_widget_catalog,
)
from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import PermissionEffect, RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import EmployeeId, PositionId, TenantId
from src.infrastructure.plugins.contracts import (
    PluginCapability,
    PluginManifest,
    PluginStatus,
)
from src.presentation import preview_data
from src.presentation.navigation import MenuEntry
from src.presentation.plugin_surface import (
    PLUGIN_KEY_PREFIX,
    PLUGIN_MENU_ORDER_BASE,
    ApprovedPlugin,
    PluginRegistrySurface,
    collect_surface,
    plugin_page_key,
    plugin_widget_key,
    register_plugin_pages,
)
from src.presentation.shell.menu import DEFAULT_ENTRIES, build_default_registry
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())
NOW: Final = datetime(2026, 8, 12, 9, 42, tzinfo=UTC)
FLAG: Final = "can_view_employee_reports"


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _employee(*, flags: tuple[str, ...]) -> Employee:
    """Verilmiş flag-ləri daşıyan operativ-pilləli işçi.

    Naxış `test_remaining_gaps.py`-dən götürülüb: flag-lər `apply_override`
    ilə verilir, çünki `Position` konstruktoru flag qəbul etmir və vəzifə
    kataloqu ilə fərdi güzəşt AYRI mexanizmlərdir.
    """
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        tenant_id=TENANT,
        code="KAMERA_NEZARETCISI",
        name_az="Kamera Nəzarətçisi",
        priority=RolePriority.OPERATIONAL,
        is_system=True,
    )
    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Test",
        last_name="İstifadəçi",
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


def _manifest(
    *,
    name: str = "Anbar Hesabatı",
    capabilities: frozenset[PluginCapability] = frozenset({PluginCapability.REGISTER_PAGE}),
    flags: frozenset[str] = frozenset({FLAG}),
) -> PluginManifest:
    return PluginManifest(
        name=name,
        version="1.0.0",
        publisher="Kompas Studio",
        capabilities=capabilities,
        entry_point="main.py",
        description_az="Nümunə plugin.",
        required_flags=flags,
    )


def _plugin(
    *,
    plugin_id: str = "pl-1",
    status: PluginStatus = PluginStatus.APPROVED,
    verified: bool = True,
    manifest: PluginManifest | None = None,
) -> ApprovedPlugin:
    resolved = manifest or _manifest()
    return ApprovedPlugin(
        plugin_id=plugin_id,
        name=resolved.name,
        publisher=resolved.publisher,
        status=status,
        signature_verified=verified,
        manifest=resolved,
    )


# =========================================================================== #
# 1. Səth QURULUR — qabiliyyət artıq ölü deyil
# =========================================================================== #


def test_an_approved_plugin_page_reaches_the_menu() -> None:
    """Əsas iddia: təsdiqlənmiş plugin menyuda GÖRÜNÜR."""
    surface = collect_surface([_plugin()])
    registry = build_default_registry()
    before = len(registry.all_entries)

    assert register_plugin_pages(registry, surface.pages) == 1
    assert len(registry.all_entries) == before + 1

    entry = registry.get(plugin_page_key("pl-1"))
    assert entry is not None
    assert entry.title_az == "Anbar Hesabatı"
    assert registry.is_visible(entry.key, _employee(flags=(FLAG,)), now=NOW)


def test_a_plugin_widget_extends_the_dashboard_catalog() -> None:
    """`WIDGET_CATALOG` artıq DİNAMİK genişlənə bilir."""
    surface = collect_surface(
        [
            _plugin(
                manifest=_manifest(
                    capabilities=frozenset(
                        {PluginCapability.REGISTER_PAGE, PluginCapability.RENDER_WIDGET}
                    )
                )
            )
        ]
    )
    assert len(surface.widgets) == 1

    catalog = build_widget_catalog(surface.widgets)
    assert len(catalog) == len(WIDGET_CATALOG) + 1
    added = next(widget for widget in catalog if widget.key == plugin_widget_key("pl-1"))
    assert added.required_flag == FLAG, "Widget də flag TƏLƏB ETMƏLİDİR"


def test_plugin_entries_never_outrank_core_menu_items() -> None:
    """Plugin maddəsi əsas maddələri yuxarı-aşağı SÜRÜŞDÜRMÜR."""
    surface = collect_surface([_plugin()])
    registry = build_default_registry()
    register_plugin_pages(registry, surface.pages)

    core_max = max(entry.order for entry in DEFAULT_ENTRIES)
    plugin_entry = registry.get(plugin_page_key("pl-1"))
    assert plugin_entry is not None
    assert plugin_entry.order >= PLUGIN_MENU_ORDER_BASE > core_max


# =========================================================================== #
# 2. QAPI 1 — imza və təsdiq
# =========================================================================== #


@pytest.mark.parametrize(
    ("status", "verified", "reason"),
    [
        (PluginStatus.PENDING_APPROVAL, True, "Root hələ təsdiqləməyib"),
        (PluginStatus.DISABLED, True, "Root söndürüb"),
        (PluginStatus.REJECTED, True, "Root rədd edib"),
        (PluginStatus.APPROVED, False, "imza doğrulanmayıb"),
    ],
)
def test_only_approved_and_signed_plugins_produce_a_surface(
    status: PluginStatus, verified: bool, reason: str
) -> None:
    """Təsdiqsiz/imzasız plugin menyuya GİRMİR."""
    surface = collect_surface([_plugin(status=status, verified=verified)])
    assert surface.pages == (), reason
    assert surface.widgets == (), reason


def test_the_preview_surface_applies_the_same_gates_as_the_live_path() -> None:
    """MAKET VƏ CANLI YOL EYNİ FUNKSİYADAN keçir (CLAUDE.md bölmə 6).

    `preview_data.PLUGIN_SURFACE` üç sətir daşıyır — biri təsdiqli, biri
    söndürülmüş, biri imzasız/flagsız. Maket öz "hər şey görünür" yolunu
    qursaydı, qapılardan birinin sınması yalnız istehsalatda üzə çıxardı.
    """
    surface = collect_surface(preview_data.PLUGIN_SURFACE)
    assert [page.plugin_id for page in surface.pages] == ["pl-1"]
    assert [widget.key for widget in surface.widgets] == [plugin_widget_key("pl-1")]


# =========================================================================== #
# 3. QAPI 2/3 — qabiliyyət və icazə flag-i
# =========================================================================== #


def test_a_plugin_without_the_capability_gets_no_page() -> None:
    surface = collect_surface(
        [_plugin(manifest=_manifest(capabilities=frozenset({PluginCapability.REPORT_TRANSFORM})))]
    )
    assert surface.pages == ()
    assert surface.widgets == ()


def test_a_plugin_without_a_permission_flag_is_rejected() -> None:
    """Flagsız səhifə HƏR istifadəçiyə render olunardı — bölmə 3-ün pozulması."""
    surface = collect_surface([_plugin(manifest=_manifest(flags=frozenset()))])
    assert surface.pages == (), "Flagsız plugin səhifəsi RƏDD edilməlidir"


def test_every_declared_flag_is_required_not_just_the_first() -> None:
    """İki flag elan edilibsə, birini daşıyan istifadəçi maddəni GÖRMÜR."""
    surface = collect_surface(
        [_plugin(manifest=_manifest(flags=frozenset({FLAG, "can_export_reports"})))]
    )
    registry = build_default_registry()
    register_plugin_pages(registry, surface.pages)
    key = plugin_page_key("pl-1")

    partial = _employee(flags=(FLAG,))
    complete = _employee(flags=(FLAG, "can_export_reports"))

    assert not registry.is_visible(key, partial, now=NOW)
    assert registry.is_visible(key, complete, now=NOW)


def test_a_user_without_the_flag_does_not_see_the_plugin_page() -> None:
    """ "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" — maddə boz DEYİL, ÜMUMİYYƏTLƏ yoxdur."""
    surface = collect_surface([_plugin()])
    registry = build_default_registry()
    register_plugin_pages(registry, surface.pages)

    visible = registry.visible_for(_employee(flags=()), now=NOW)
    assert plugin_page_key("pl-1") not in {entry.key for entry in visible}


# =========================================================================== #
# 4. QAPI 4 — ad toqquşmasında PLUGIN UDUZUR
# =========================================================================== #


def test_plugin_keys_live_in_their_own_namespace() -> None:
    """Heç bir əsas açar `plugin:` ilə başlamır — toqquşma sxem səviyyəsində yoxdur."""
    assert not any(entry.key.startswith(PLUGIN_KEY_PREFIX) for entry in DEFAULT_ENTRIES)
    assert plugin_page_key("x").startswith(PLUGIN_KEY_PREFIX)


def test_a_taken_key_keeps_the_core_entry() -> None:
    """Açar artıq varsa PLUGIN maddəsi atılır, əsas maddə QALIR.

    Ssenari süni qurulur (ad məkanı bunu onsuz da qapayır), çünki ikinci qat
    məhz "birinci qat sınsa nə olur?" sualına cavab verməlidir.
    """
    registry = build_default_registry()
    hijacked = plugin_page_key("pl-1")
    registry.register(MenuEntry(key=hijacked, title_az="Əsl ekran", required_flag=None, order=5))

    assert register_plugin_pages(registry, collect_surface([_plugin()]).pages) == 0
    entry = registry.get(hijacked)
    assert entry is not None
    assert entry.title_az == "Əsl ekran", "Plugin əsas maddəni ƏVƏZ ETMƏMƏLİDİR"


def test_a_plugin_widget_cannot_replace_a_core_widget() -> None:
    """Kataloq toqquşmasında da əsas sətir qalır."""
    intruder = DashboardWidget(
        key="stat_tiles",
        title_az="Saxta rəqəm kartları",
        description_az="Zərərli plugin",
        required_flag=FLAG,
    )
    catalog = build_widget_catalog([intruder])
    assert len(catalog) == len(WIDGET_CATALOG)
    original = next(widget for widget in catalog if widget.key == "stat_tiles")
    assert original.title_az == "Rəqəm kartları"


# =========================================================================== #
# 5. QAPI 5 — izolyasiya
# =========================================================================== #


class _ExplodingPlugin:
    """Manifest oxunanda istisna atan sətir — korlanmış məlumatın modeli."""

    plugin_id = "pl-bad"
    name = "Zəhərli"
    publisher = "Naməlum"
    status = PluginStatus.APPROVED
    signature_verified = True

    @property
    def manifest(self) -> PluginManifest:
        raise RuntimeError("manifest oxunmadı")


def test_one_broken_plugin_does_not_remove_the_others() -> None:
    """Bir sətrin nasazlığı qalan plugin-ləri və əsas UI-ni çökdürmür."""
    records: list[Any] = [_ExplodingPlugin(), _plugin(plugin_id="pl-2")]
    surface = collect_surface(records)
    assert [page.plugin_id for page in surface.pages] == ["pl-2"]


def test_a_failing_registration_does_not_stop_the_shell() -> None:
    """Reyestr istisna atsa da qeydiyyat dövrü DAVAM edir."""

    class _AngryRegistry:
        def __init__(self) -> None:
            self.calls = 0

        def get(self, key: str) -> None:
            return None

        def register(self, entry: MenuEntry) -> None:
            self.calls += 1
            raise RuntimeError("reyestr sındı")

    registry = _AngryRegistry()
    pages = collect_surface([_plugin(plugin_id="a"), _plugin(plugin_id="b")]).pages
    assert register_plugin_pages(registry, pages) == 0  # type: ignore[arg-type]
    assert registry.calls == 2, "İkinci plugin də cəhd edilməlidir"


def test_an_unavailable_plugin_table_yields_an_empty_surface() -> None:
    """Baza əlçatmazlığı naviqasiyanı DAYANDIRMIR — səth sadəcə boşdur."""

    class _DeadRegistry:
        def list_all(self, tenant_id: Any) -> list[Any]:
            raise RuntimeError("bağlantı yoxdur")

    provider = PluginRegistrySurface(_DeadRegistry(), TENANT)  # type: ignore[arg-type]
    assert provider.surface().pages == ()
    assert provider.dashboard_widgets() == ()


def test_rows_without_a_manifest_are_skipped() -> None:
    """Manifesti oxunmayan sətir səth VERMİR (fail-closed)."""

    class _Row:
        plugin_id = "pl-9"
        name = "Manifestsiz"
        publisher = "Kompas Studio"
        status = PluginStatus.APPROVED
        signature_verified = True
        manifest = None

    class _Registry:
        def list_all(self, tenant_id: Any) -> list[Any]:
            return [_Row()]

    provider = PluginRegistrySurface(_Registry(), TENANT)  # type: ignore[arg-type]
    assert provider.surface().pages == ()


# =========================================================================== #
# 6. Determinizm — eyni quraşdırma eyni menyunu verir
# =========================================================================== #


@requires_qt
def test_the_plugin_page_screen_renders_host_controlled_rows(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Səhifə plugin-in ADINI və NAŞİRİNİ göstərməlidir.

    Mənbə kartı olmasaydı, plugin səhifəsi tətbiqin ÖZ ekranı kimi görünərdi
    və "bu rəqəm haradandır?" sualının cavabı yox olardı (bax
    `screens/group_i.PluginPageScreen` başlığı).
    """
    from src.presentation.screens.group_i import PluginPageScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)

    screen = PluginPageScreen(theme, plugin_name="Anbar Hesabatı", publisher="Kompas Studio")
    screen.set_rows([("Qabiliyyətlər", "register_page")])
    assert screen.switcher().current_state() == "content"

    # Boş məzmun XƏTA DEYİL — istifadəçi səbəbi görməlidir.
    screen.set_rows([])
    assert screen.switcher().current_state() == "empty"


def test_surface_order_is_deterministic() -> None:
    """Sıra (naşir, ad, id) üzrədir — maddə hər açılışda eyni yerdədir."""
    first = collect_surface(
        [
            _plugin(plugin_id="b", manifest=_manifest(name="Beta")),
            _plugin(plugin_id="a", manifest=_manifest(name="Alfa")),
        ]
    )
    second = collect_surface(
        [
            _plugin(plugin_id="a", manifest=_manifest(name="Alfa")),
            _plugin(plugin_id="b", manifest=_manifest(name="Beta")),
        ]
    )
    assert [page.title_az for page in first.pages] == ["Alfa", "Beta"]
    assert [page.key for page in first.pages] == [page.key for page in second.pages]
