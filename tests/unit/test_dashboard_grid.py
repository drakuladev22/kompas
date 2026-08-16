"""Panel Qurucusunda ŞƏBƏKƏ yerləşdirməsi (audit G-5).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TESTLƏR VAR
──────────────────────────────────────────────────────────────────────────────
Qurucuda yalnız GÖRÜNÜRLÜK və XƏTTİ SIRA var idi; bölmə 6 isə sətir/sütun və
en (span) təsvir edir. Şəbəkə əlavə edilərkən ƏSAS RİSK yeni funksiya deyil,
KÖHNƏ KONFİQURASİYADIR: `user_preferences.dashboard_layout` sütununda artıq
sadə açar massivləri var və onlar bir buraxılışda "sınmış" görünə bilərdi.

Ona görə burada dörd sual qapılanır:

    1. şəbəkə saxlanılır və geri oxunur;
    2. KÖHNƏ (xətti) konfiqurasiya EYNİ görünüşü verir və saxlanma forması
       da dəyişmir — yəni yan-yol oxucular (SQL, skript) sınmır;
    3. dar pəncərədə şəbəkə tək sütuna yığılır (oxunuş sırası qorunur);
    4. boş xana, örtüşmə və yararsız format ÇÖKMƏ YARATMIR.

Sahtələr BU FAYLDA yerlidir — `tests/fixtures/fakes.py` paylaşılan fayldır.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Final

import pytest

from src.application.use_cases.dashboard_layout import (
    DEFAULT_LAYOUT,
    FALLBACK_GRID_COLUMNS,
    MAX_GRID_COLUMNS,
    PLACEMENT_SEPARATOR,
    WIDGET_CATALOG,
    DashboardLayoutUseCase,
    WidgetPlacement,
    collapse_to_single_column,
    normalize_placements,
    split_entry,
)
from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.position import Position
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.authorization import PermissionEffect, RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import EmployeeId, PositionId, TenantId
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())
NOW: Final = datetime(2026, 8, 12, 9, 42, tzinfo=UTC)
EDIT_FLAG: Final = "can_edit_dashboard_widgets"


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Store:
    def __init__(self, layout: list[str] | None = None) -> None:
        self.layout = layout
        self.saved: list[list[str]] = []

    def load(self, employee_id: Any) -> list[str] | None:
        return self.layout

    def save(self, employee_id: Any, layout: list[str]) -> None:
        self.layout = layout
        self.saved.append(layout)


class _Limits:
    """`LimitReader` sahtəsi — `DASHBOARD_GRID_COLUMNS` mənbəyi."""

    def __init__(self, columns: int | None = None, *, explode: bool = False) -> None:
        self.columns = columns
        self.explode = explode
        self.asked: list[str] = []

    def get_int(self, tenant_id: Any, key: str, default: int) -> int:
        self.asked.append(key)
        if self.explode:
            raise RuntimeError("limit oxunmadı")
        return default if self.columns is None else self.columns


def _employee(*, flags: tuple[str, ...] = (EDIT_FLAG,)) -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        tenant_id=TENANT,
        code="ADMIN",
        name_az="Admin",
        priority=RolePriority.ADMIN,
        is_system=True,
    )
    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
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


def _use_case(store: _Store, *, columns: int | None = 2) -> DashboardLayoutUseCase:
    return DashboardLayoutUseCase(store=store, clock=_Clock(), limits=_Limits(columns))


# =========================================================================== #
# 1. ROOT parametri — beş halqanın kod tərəfi
# =========================================================================== #


def test_the_column_count_comes_from_root_not_from_a_constant() -> None:
    limits = _Limits(3)
    use_case = DashboardLayoutUseCase(store=_Store(), clock=_Clock(), limits=limits)
    view = use_case.view_for(actor=_employee(), tenant_id=TENANT)

    assert view.columns == 3
    assert SystemLimitKey.DASHBOARD_GRID_COLUMNS.value in limits.asked


def test_the_column_count_is_clamped_not_obeyed() -> None:
    """Root 9 yazsa, 1280px pəncərədə kartlar oxunmaz olardı."""
    use_case = DashboardLayoutUseCase(store=_Store(), clock=_Clock(), limits=_Limits(9))
    assert use_case.view_for(actor=_employee(), tenant_id=TENANT).columns == MAX_GRID_COLUMNS

    use_case = DashboardLayoutUseCase(store=_Store(), clock=_Clock(), limits=_Limits(0))
    assert use_case.view_for(actor=_employee(), tenant_id=TENANT).columns == 1


def test_an_unreadable_limit_falls_back_instead_of_breaking_the_panel() -> None:
    use_case = DashboardLayoutUseCase(store=_Store(), clock=_Clock(), limits=_Limits(explode=True))
    assert use_case.view_for(actor=_employee(), tenant_id=TENANT).columns == FALLBACK_GRID_COLUMNS


def test_the_fallback_equals_the_root_default() -> None:
    """Kodda oturan ədəd `DEFAULT_LIMITS` ilə eyni olmalıdır."""
    assert str(FALLBACK_GRID_COLUMNS) == DEFAULT_LIMITS[SystemLimitKey.DASHBOARD_GRID_COLUMNS]


# =========================================================================== #
# 2. GERİYƏ UYĞUNLUQ — köhnə xətti konfiqurasiya İTMİR
# =========================================================================== #


def test_a_legacy_linear_layout_becomes_a_single_column_grid() -> None:
    """Köhnə sətir EYNİ görünüşü verməlidir: hər kart tam enli, sıra ilə."""
    legacy = ["stat_tiles", "leave_gauge", "open_tasks"]
    view = _use_case(_Store(list(legacy))).view_for(actor=_employee(), tenant_id=TENANT)

    placed = {item.key: item for item in view.placements}
    for index, key in enumerate(legacy):
        assert placed[key].row == index
        assert placed[key].column == 0
        assert placed[key].span == view.columns, "Xətti element TAM ENLİ sətir olmalıdır"


def test_a_legacy_layout_keeps_its_visibility_and_order() -> None:
    """Şəbəkə əlavəsi görünürlük/sıra semantikasını DƏYİŞMİR."""
    legacy = ["open_tasks", "stat_tiles"]
    view = _use_case(_Store(list(legacy))).view_for(actor=_employee(), tenant_id=TENANT)

    assert view.order[:2] == ("open_tasks", "stat_tiles")
    assert view.visible == frozenset(legacy)
    assert not view.is_default


def test_saving_a_layout_without_placements_keeps_the_old_storage_format() -> None:
    """Şəbəkə İŞLƏDİLMƏYƏNDƏ bazadakı iz DƏYİŞMİR.

    Bu qapı sırf geriyə uyğunluq üçündür: kodlanmış sətri şərtsiz yazsaydıq,
    şəbəkəyə heç vaxt toxunmamış istifadəçinin sətri də formatını dəyişərdi
    və yan-yol oxucular (SQL sorğusu, miqrasiya skripti) sükutla sınardı.
    """
    store = _Store()
    _use_case(store).save(actor=_employee(), tenant_id=TENANT, layout=["stat_tiles", "leave_gauge"])
    assert store.saved[-1] == ["stat_tiles", "leave_gauge"]
    assert all(PLACEMENT_SEPARATOR not in entry for entry in store.saved[-1])


def test_reset_writes_the_linear_default() -> None:
    """«Defolta qaytar» paketdən çıxan görünüşü bərpa edir — tək sütun."""
    store = _Store(["stat_tiles@0,1,1"])
    _use_case(store).reset(actor=_employee(), tenant_id=TENANT)
    assert all(PLACEMENT_SEPARATOR not in entry for entry in store.saved[-1])
    assert store.saved[-1][0] == DEFAULT_LAYOUT[0]


# =========================================================================== #
# 3. ŞƏBƏKƏ saxlanılır və geri oxunur
# =========================================================================== #


def test_a_grid_layout_survives_a_save_and_reload() -> None:
    store = _Store()
    use_case = _use_case(store)
    use_case.save(
        actor=_employee(),
        tenant_id=TENANT,
        layout=["stat_tiles@0,0,1", "leave_gauge@0,1,1", "open_tasks@1,0,2"],
    )

    assert store.saved[-1] == ["stat_tiles@0,0,1", "leave_gauge@0,1,1", "open_tasks@1,0,2"]

    reloaded = use_case.view_for(actor=_employee(), tenant_id=TENANT).placement_map()
    assert reloaded["stat_tiles"] == (0, 0, 1)
    assert reloaded["leave_gauge"] == (0, 1, 1)
    assert reloaded["open_tasks"] == (1, 0, 2)


def test_encode_and_split_are_inverse() -> None:
    placement = WidgetPlacement(key="stat_tiles", row=2, column=1, span=1)
    assert split_entry(placement.encode()) == ("stat_tiles", (2, 1, 1))


def test_a_plugin_key_with_colons_still_round_trips() -> None:
    """Ayırıcı `@`-dır məhz buna görə (bax `dashboard_layout` başlığı)."""
    key = "plugin:2f1c:widget"
    placement = WidgetPlacement(key=key, row=1, column=0, span=2)
    assert split_entry(placement.encode()) == (key, (1, 0, 2))


# =========================================================================== #
# 4. ÇÖKMƏ YOXDUR — boş xana, örtüşmə, yararsız format
# =========================================================================== #


def test_an_empty_cell_is_legal() -> None:
    """Bir sətirdə tək kart qanunidir — deşik düzəldilmir."""
    placements = normalize_placements([("a", (0, 1, 1)), ("b", (1, 0, 1))], columns=2)
    assert {item.key: (item.row, item.column) for item in placements} == {
        "a": (0, 1),
        "b": (1, 0),
    }


def test_overlapping_placements_are_pushed_to_the_first_free_cell() -> None:
    """İki kart eyni xanaya düşsə, ikincisi növbəti boş yerə keçir."""
    placements = normalize_placements([("a", (0, 0, 1)), ("b", (0, 0, 1))], columns=2)
    cells = {item.key: (item.row, item.column) for item in placements}
    assert cells["a"] == (0, 0)
    assert cells["b"] != cells["a"]
    assert len({item.cells() for item in placements}) == 2


def test_a_span_that_leaves_the_grid_is_clamped() -> None:
    placements = normalize_placements([("a", (0, 1, 5))], columns=2)
    assert placements[0].span == 1, "En sağ kənarı KEÇMƏMƏLİDİR"


def test_a_negative_position_is_clamped() -> None:
    placements = normalize_placements([("a", (-3, -1, 0))], columns=2)
    assert (placements[0].row, placements[0].column, placements[0].span) == (0, 0, 1)


@pytest.mark.parametrize(
    "raw",
    ["stat_tiles@", "stat_tiles@1,2", "stat_tiles@a,b,c", "stat_tiles@1,2,3,4"],
)
def test_an_unreadable_placement_degrades_to_linear(raw: str) -> None:
    """Yararsız format düzülüşü SINDIRMIR — widget öz xəttinə qayıdır."""
    key, placement = split_entry(raw)
    assert key == "stat_tiles"
    assert placement is None


def test_shrinking_the_grid_keeps_every_widget() -> None:
    """Root 3 sütundan 2-yə enəndə üçüncü sütundakı kart İTMİR."""
    store = _Store(["a@0,0,1", "b@0,1,1", "c@0,2,1"])
    entries = [split_entry(item) for item in store.layout or []]
    placements = normalize_placements(entries, columns=2)
    assert {item.key for item in placements} == {"a", "b", "c"}
    assert all(item.column + item.span <= 2 for item in placements)


# =========================================================================== #
# 5. RESPONSİV — dar pəncərədə tək sütun
# =========================================================================== #


def test_collapsing_puts_every_widget_in_one_column() -> None:
    placements = (
        WidgetPlacement(key="a", row=0, column=0, span=1),
        WidgetPlacement(key="b", row=0, column=1, span=1),
        WidgetPlacement(key="c", row=1, column=0, span=2),
    )
    collapsed = collapse_to_single_column(placements)
    assert [item.key for item in collapsed] == ["a", "b", "c"]
    assert all(item.column == 0 and item.span == 1 for item in collapsed)
    assert [item.row for item in collapsed] == [0, 1, 2]


def test_collapsing_preserves_reading_order() -> None:
    """Geniş ekrandakı "soldan sağa, yuxarıdan aşağı" sırası qorunur."""
    placements = (
        WidgetPlacement(key="c", row=2, column=0, span=1),
        WidgetPlacement(key="b", row=0, column=1, span=1),
        WidgetPlacement(key="a", row=0, column=0, span=1),
    )
    assert [item.key for item in collapse_to_single_column(placements)] == ["a", "b", "c"]


def test_collapsing_an_empty_grid_is_not_an_error() -> None:
    assert collapse_to_single_column(()) == ()


# =========================================================================== #
# 6. İKİ SABİTİN PARİTETİ (ekran ↔ tətbiq qatı)
# =========================================================================== #


def test_the_screen_repeats_the_same_separator() -> None:
    """`screens/group_i` tətbiq qatını idxal etmir — sabit təkrarlanır.

    Təkrarlanmanın sükutla ayrılmasının qarşısını məhz bu qapı alır (bax
    `group_i.PLACEMENT_SEPARATOR` şərhi).
    """
    from src.presentation.screens.group_i import (
        PLACEMENT_SEPARATOR as SCREEN_SEPARATOR,
    )

    assert SCREEN_SEPARATOR == PLACEMENT_SEPARATOR


# =========================================================================== #
# 7. EKRAN — Qt tələb edir
# =========================================================================== #


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


_CATALOG: Final = {
    "a": ("Birinci", "izah"),
    "b": ("İkinci", "izah"),
    "c": ("Üçüncü", "izah"),
}


def _builder(theme: Any) -> Any:
    from src.presentation.screens.group_i import DashboardBuilderScreen

    return DashboardBuilderScreen(theme)


@requires_qt
def test_the_old_setter_call_still_works(theme) -> None:  # type: ignore[no-untyped-def]
    """Şəbəkə arqumentləri OPSİONALDIR — köhnə çağırış sınmır."""
    screen = _builder(theme)
    screen.set_widgets(dict(_CATALOG), order=["a", "b", "c"], visible={"a", "b"})

    assert screen.current_layout() == ["a", "b"], "Tək sütunda SADƏ açar qaytarılır"


@requires_qt
def test_a_grid_layout_is_emitted_in_encoded_form(theme) -> None:  # type: ignore[no-untyped-def]
    screen = _builder(theme)
    screen.set_widgets(
        dict(_CATALOG),
        order=["a", "b", "c"],
        visible={"a", "b", "c"},
        placements={"a": (0, 0, 1), "b": (0, 1, 1), "c": (1, 0, 2)},
        columns=2,
    )
    # `a` və `b` YAN-YANA qalır (hər ikisi 0-cı sətir), `c` isə tam enli
    # olduğu üçün növbəti sətrə düşür — axın-paketləmə (bax `_flow_rows`).
    assert screen.current_layout() == ["a@0,0,1", "b@0,1,1", "c@1,0,2"]


@requires_qt
def test_a_side_by_side_pair_survives_a_round_trip(theme) -> None:  # type: ignore[no-untyped-def]
    """REQRESSİYA QAPISI: sətri `enumerate`-dən götürmək cütü parçalayırdı.

    Ekranın yaydığı sətir yenidən `set_widgets`-ə qaytarıldıqda düzülüş
    DƏYİŞMƏMƏLİDİR — əks halda hər saxlama şəbəkəni bir az daha dağıdardı.
    """
    screen = _builder(theme)
    screen.set_widgets(
        dict(_CATALOG),
        order=["a", "b"],
        visible={"a", "b"},
        placements={"a": (0, 0, 1), "b": (0, 1, 1)},
        columns=2,
    )
    first = screen.current_layout()

    parsed = [split_entry(entry) for entry in first]
    normalized = normalize_placements(parsed, columns=2)
    screen.set_widgets(
        dict(_CATALOG),
        order=[item.key for item in normalized],
        visible={item.key for item in normalized},
        placements={item.key: (item.row, item.column, item.span) for item in normalized},
        columns=2,
    )
    assert screen.current_layout() == first


@requires_qt
def test_the_column_selector_is_absent_in_a_single_column_grid(theme) -> None:  # type: ignore[no-untyped-def]
    """Mənasız seçici RENDER OLUNMUR (boz da göstərilmir)."""
    screen = _builder(theme)
    screen.set_widgets(dict(_CATALOG), order=["a"], visible={"a"}, columns=1)
    assert screen._rows[0]._column_box is None

    screen.set_widgets(dict(_CATALOG), order=["a"], visible={"a"}, columns=2)
    assert screen._rows[0]._column_box is not None


@requires_qt
def test_changing_the_column_re_emits_the_layout(theme) -> None:  # type: ignore[no-untyped-def]
    screen = _builder(theme)
    screen.set_widgets(
        dict(_CATALOG),
        order=["a", "b"],
        visible={"a", "b"},
        placements={"a": (0, 0, 2), "b": (1, 0, 2)},
        columns=2,
    )
    emitted: list[list[str]] = []
    screen.layout_changed.connect(emitted.append)

    screen._on_placement_changed("a", 1, 2)

    assert emitted, "Seçici dəyişikliyi yazı yoluna çatmalıdır"
    assert emitted[-1][0] == "a@0,1,1", "En sağ kənarı keçməməli — SIXILIR"


@requires_qt
def test_a_narrow_window_collapses_the_preview(theme) -> None:  # type: ignore[no-untyped-def]
    """Dar pəncərədə şəbəkə tək sütuna yığılır (mövcud `LayoutMode` mexanizmi)."""
    from src.presentation.widgets.responsive import LayoutMode

    screen = _builder(theme)
    screen.set_widgets(
        dict(_CATALOG),
        order=["a", "b"],
        visible={"a", "b"},
        placements={"a": (0, 0, 1), "b": (0, 1, 1)},
        columns=2,
    )
    grid = screen._preview_grid
    assert {grid.getItemPosition(i)[1] for i in range(grid.count())} == {0, 1}

    screen.apply_layout_mode(LayoutMode.COMPACT)
    grid = screen._preview_grid
    assert {grid.getItemPosition(i)[1] for i in range(grid.count())} == {0}
    assert "tək sütuna yığılır" in screen._preview_note.text()


@requires_qt
def test_an_empty_cell_does_not_break_the_preview(theme) -> None:  # type: ignore[no-untyped-def]
    """Sətirdə deşik qanunidir — `QGridLayout` onu sakitcə keçir."""
    screen = _builder(theme)
    screen.set_widgets(
        dict(_CATALOG),
        order=["a", "b"],
        visible={"a", "b"},
        placements={"a": (0, 1, 1), "b": (1, 0, 1)},
        columns=2,
    )
    assert screen._preview_grid.count() == 2
    assert screen.switcher().current_state() == "content"


@requires_qt
def test_hiding_everything_says_so_instead_of_drawing_an_empty_grid(theme) -> None:  # type: ignore[no-untyped-def]
    screen = _builder(theme)
    screen.set_widgets(dict(_CATALOG), order=["a", "b"], visible=set(), columns=2)
    assert screen._preview_grid.count() == 0
    assert "şəbəkə boşdur" in screen._preview_note.text()


@requires_qt
def test_the_preview_path_passes_the_grid_arguments(theme) -> None:  # type: ignore[no-untyped-def]
    """MAKET VƏ CANLI YOL EYNİ AÇARLARI işlədir (CLAUDE.md bölmə 6)."""
    from src.presentation import preview_data, preview_screens

    screen = _builder(theme)
    preview_screens.populate("dashboard_builder", screen)

    assert screen._columns == preview_data.DASHBOARD_GRID_COLUMNS
    assert set(screen._placements) == set(preview_data.DASHBOARD_WIDGETS)
    assert screen._placements["fines"] == (0, 1)


@requires_qt
def test_screen_section_keys_stay_in_step_with_the_widget_catalog() -> None:
    """`DASHBOARD_SECTION_KEYS` ↔ `WIDGET_CATALOG` PARİTETİ (audit G-5).

    Ekran tətbiq qatını İDXAL ETMİR (qat sərhədi), ona görə açar siyahısı
    `screens/group_c.py`-da TƏKRARLANIR. Təkrar isə sükutla ayrıla bilər:
    kataloqa yeni widget əlavə edən adam ekrandakı siyahını unudarsa,
    həmin bölmə Panel Qurucusunda seçilər, lakin panelin özündə HEÇ VAXT
    görünməzdi — nə qurma, nə də tip yoxlayıcısı bunu tutar.

    `open_tasks` QƏSDƏN kənardadır: onun öz bölməsi yoxdur, açıq tapşırıq
    sayı rəqəm kartlarının içindədir (bax `DASHBOARD_SECTION_KEYS` şərhi).
    """
    from src.presentation.screens.group_c import DASHBOARD_SECTION_KEYS

    catalog_keys = [widget.key for widget in WIDGET_CATALOG]

    assert [key for key in DASHBOARD_SECTION_KEYS if key not in catalog_keys] == []
    assert [key for key in catalog_keys if key not in DASHBOARD_SECTION_KEYS] == ["open_tasks"]
