"""Kamera Operatorunun MAĞAZA SÜZGƏCİ (audit G-6).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TESTLƏR VAR
──────────────────────────────────────────────────────────────────────────────
Bölmə 4 operatorun 3-dən çox mağazası olduqda mağaza seçimi tələb edir; ekran
isə yalnız tip süzgəci (giriş/qayıdış) daşıyırdı. Süzgəc əlavə edilərkən ƏSAS
RİSK funksiya deyil, SƏLAHİYYƏT SƏHVİDİR: "hamısı" seçimi asanlıqla "bütün
şəbəkə" mənasına sürüşə bilər.

Ona görə burada beş sual qapılanır:

    1. hədddən AZ təyinatda seçici QURULMUR (mənasız element render olunmur);
    2. hədddən ÇOX təyinatda QURULUR;
    3. siyahıda YALNIZ təyin olunmuş mağazalar var;
    4. təyinat yoxdursa növbə BOŞDUR (fail-safe — süzgəc bunu dəyişmir);
    5. hədd ROOT parametrindən oxunur, kodda oturmur.

Ekran testləri `@requires_qt` ilə işarələnir (`test_sync_conflicts_screen.py`
naxışı); ROOT parametrinin kod tərəfi Qt TƏLƏB ETMİR.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final

import pytest

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_MIGRATION: Final[Path] = (
    _REPO_ROOT / "database" / "migrations" / "054_queue_store_filter_and_dashboard_grid.sql"
)

STORES: Final = [
    "Bellona 28 May",
    "Yataş Xətai",
    "İstikbal Gənclik",
    "Enza Home Gəncə",
]


# =========================================================================== #
# 1. ROOT parametri — BEŞ HALQA
# =========================================================================== #


def test_the_threshold_key_exists_with_a_default() -> None:
    """Halqa 1–2: `SystemLimitKey` + `DEFAULT_LIMITS`."""
    key = SystemLimitKey.CAMERA_QUEUE_STORE_FILTER_THRESHOLD
    assert DEFAULT_LIMITS[key] == "3", "Spesifikasiyanın öz ədədi (3-dən çox)"


def test_the_module_fallback_equals_the_root_default() -> None:
    """Ekrandakı fallback ilə ROOT defoltu AYRILA BİLMƏZ.

    Ayrılsaydı, `system_limits` sətri hələ seed edilməmiş quraşdırmada ekran
    bir ədədlə, ROOT paneli başqası ilə danışardı.
    """
    from src.presentation.screens.group_b import QUEUE_STORE_FILTER_THRESHOLD

    assert (
        str(QUEUE_STORE_FILTER_THRESHOLD)
        == (DEFAULT_LIMITS[SystemLimitKey.CAMERA_QUEUE_STORE_FILTER_THRESHOLD])
    )


def test_the_migration_seeds_both_existing_and_new_tenants() -> None:
    """Halqa 3–4: mövcud kirayəçi `INSERT`-i + yeni kirayəçi trigger-i.

    Açar İKİ dəfə görünməlidir; yalnız birində olsa, ya köhnə quraşdırmalarda
    parametr GUI-dan dəyişdirilə bilməzdi, ya da yeni kirayəçidə sətir heç
    vaxt yaranmazdı.
    """
    blob = _MIGRATION.read_text(encoding="utf-8")
    for key in ("CAMERA_QUEUE_STORE_FILTER_THRESHOLD", "DASHBOARD_GRID_COLUMNS"):
        occurrences = len(re.findall(rf"'{key}'", blob))
        assert occurrences >= 2, (
            f"`{key}` miqrasiyada {occurrences} dəfə görünür — mövcud VƏ yeni "
            "kirayəçi yolları ayrı-ayrılıqda seed edilməlidir."
        )


def test_the_migration_carries_an_azerbaijani_description() -> None:
    """Halqa 5: izahsız sətir ROOT ekranında TEXNİKİ KOD kimi görünür."""
    blob = _MIGRATION.read_text(encoding="utf-8")
    assert "Kamera Operatorunun canlı növbəsində mağaza süzgəcinin" in blob
    assert "widget şəbəkəsinin sütun sayı" in blob


def test_the_app_reads_the_threshold_from_root() -> None:
    """`app.py` ekrana ROOT dəyərini ötürür, sabit ədəd YOX."""
    source = (_REPO_ROOT / "src" / "presentation" / "app.py").read_text(encoding="utf-8")
    assert "SystemLimitKey.CAMERA_QUEUE_STORE_FILTER_THRESHOLD" in source
    assert "store_filter_threshold=queue_store_threshold" in source


# =========================================================================== #
# 2. Ekran — seçicinin MÖVCUDLUĞU
# =========================================================================== #


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _queue(theme: Any, stores: list[str], *, threshold: int = 3) -> Any:
    from src.presentation.screens.group_b import OperatorQueueScreen

    return OperatorQueueScreen(theme, assigned_stores=stores, store_filter_threshold=threshold)


def _entry(store: str, *, kind: str = "Giriş Təsdiqi", request_id: str = "r1") -> Any:
    from src.presentation.screens.group_b import QueueEntry

    return QueueEntry(
        request_id=request_id,
        employee_name="Aysel Quliyeva",
        store_name=store,
        position_name="Satıcı",
        kind=kind,
        timestamp_text="09:42",
        waiting_text="4 dəq",
    )


@requires_qt
@pytest.mark.parametrize("count", [1, 2, 3])
def test_three_or_fewer_stores_get_no_selector(theme, count: int) -> None:  # type: ignore[no-untyped-def]
    """Qısa siyahını süzmək lazım deyil — element ÜMUMİYYƏTLƏ qurulmur."""
    screen = _queue(theme, STORES[:count])
    assert not screen.store_filter_visible


@requires_qt
def test_four_stores_get_a_selector(theme) -> None:  # type: ignore[no-untyped-def]
    screen = _queue(theme, STORES)
    assert screen.store_filter_visible


@requires_qt
def test_the_threshold_is_configurable_not_hardcoded(theme) -> None:  # type: ignore[no-untyped-def]
    """Root həddi 1-ə endirsə, iki mağazalı operator da seçici görür."""
    assert _queue(theme, STORES[:2], threshold=1).store_filter_visible
    assert not _queue(theme, STORES, threshold=10).store_filter_visible


@requires_qt
def test_the_selector_lists_only_assigned_stores(theme) -> None:  # type: ignore[no-untyped-def]
    """SƏLAHİYYƏT GENİŞLƏNMİR: siyahı `assigned_stores`-dan kənara çıxmır."""
    assigned = STORES[:4]
    screen = _queue(theme, assigned)
    box = screen._store_box
    assert box is not None

    listed = [box.itemData(index) for index in range(box.count())]
    from src.presentation.screens.group_b import ALL_STORES

    assert listed[0] == ALL_STORES, "İlk sətir «hamısı» olmalıdır"
    assert listed[1:] == assigned
    assert "Sumqayıt Mərkəz" not in listed


# =========================================================================== #
# 3. Süzgəcin DAVRANIŞI
# =========================================================================== #


@requires_qt
def test_selecting_a_store_narrows_the_queue(theme) -> None:  # type: ignore[no-untyped-def]
    screen = _queue(theme, STORES)
    screen.set_entries(
        [
            _entry(STORES[0], request_id="r1"),
            _entry(STORES[1], request_id="r2"),
            _entry(STORES[0], request_id="r3"),
        ]
    )
    assert screen.visible_rows == 3

    screen.set_store_filter(STORES[0])
    assert screen.visible_rows == 2
    assert screen.active_store == STORES[0]


@requires_qt
def test_all_means_all_assigned_not_the_whole_network(theme) -> None:  # type: ignore[no-untyped-def]
    """«Hamısı» YALNIZ təyin olunmuşları əhatə edir.

    Sətirlər onsuz da `stores_for_operator` ilə süzülür; bu test süzgəcin
    HƏMİN qərara heç nə ƏLAVƏ ETMƏDİYİNİ kilidləyir — «hamısı» seçildikdə
    ekran gələn dəsti olduğu kimi göstərir, genişləndirmir.
    """
    from src.presentation.screens.group_b import ALL_STORES

    screen = _queue(theme, STORES[:4])
    screen.set_entries([_entry(STORES[0], request_id="r1"), _entry(STORES[3], request_id="r2")])
    screen.set_store_filter(ALL_STORES)
    assert screen.visible_rows == 2


@requires_qt
def test_an_unassigned_store_cannot_be_selected(theme) -> None:  # type: ignore[no-untyped-def]
    """Təyinatdan kənar ad sükutla «hamısı»na qayıdır — ekran boş qalmır."""
    from src.presentation.screens.group_b import ALL_STORES

    screen = _queue(theme, STORES)
    screen.set_entries([_entry(STORES[0])])
    screen.set_store_filter("Sumqayıt Mərkəz")

    assert screen.active_store == ALL_STORES
    assert screen.visible_rows == 1


@requires_qt
def test_without_any_assignment_the_queue_stays_empty(theme) -> None:  # type: ignore[no-untyped-def]
    """FAIL-SAFE (bölmə 4): təyinatsız operator HEÇ NƏ görmür.

    Süzgəc bu qərarı dəyişmir — seçici ümumiyyətlə qurulmur və növbə boş
    vəziyyətdə qalır.
    """
    screen = _queue(theme, [])
    screen.set_entries([_entry(STORES[0]), _entry(STORES[1])])

    assert not screen.store_filter_visible
    assert screen.visible_rows == 0
    assert screen.switcher().current_state() == "empty"


@requires_qt
def test_the_kind_filter_still_works_together_with_the_store_filter(theme) -> None:  # type: ignore[no-untyped-def]
    """İki süzgəc VƏ ilə birləşir."""
    screen = _queue(theme, STORES)
    screen.set_entries(
        [
            _entry(STORES[0], kind="Giriş Təsdiqi", request_id="r1"),
            _entry(STORES[0], kind="Qayıdış Təsdiqi", request_id="r2"),
            _entry(STORES[1], kind="Giriş Təsdiqi", request_id="r3"),
        ]
    )
    screen.set_store_filter(STORES[0])
    screen.set_filter("check_in")
    screen.set_entries(list(screen._entries))

    assert screen.visible_rows == 1


@requires_qt
def test_the_choice_survives_a_data_refresh(theme) -> None:  # type: ignore[no-untyped-def]
    """Seçim SESSİYA boyu qalır: yeni məlumat gələndə sıfırlanmır.

    Kontroller hər yazıdan sonra `set_entries`-i yenidən çağırır; seçim
    orada itsəydi, operator hər təsdiqdən sonra süzgəci yenidən qurardı.
    """
    screen = _queue(theme, STORES)
    screen.set_store_filter(STORES[1])
    screen.set_entries([_entry(STORES[0], request_id="r1"), _entry(STORES[1], request_id="r2")])

    assert screen.active_store == STORES[1]
    assert screen.visible_rows == 1


@requires_qt
def test_counts_follow_the_store_filter(theme) -> None:  # type: ignore[no-untyped-def]
    """Çip sayları da daralır — ekran YALAN rəqəm göstərməməlidir."""
    screen = _queue(theme, STORES)
    screen.set_entries(
        [
            _entry(STORES[0], request_id="r1"),
            _entry(STORES[1], request_id="r2"),
            _entry(STORES[1], request_id="r3"),
        ]
    )
    assert "Hamısı · 3" in screen._filter_chips["all"].text()

    screen.set_store_filter(STORES[1])
    assert "Hamısı · 2" in screen._filter_chips["all"].text()


@requires_qt
def test_the_preview_path_exercises_the_selector(theme) -> None:  # type: ignore[no-untyped-def]
    """Maket süzgəci GÖSTƏRMƏLİDİR, əks halda dizayn baxışında görünməz qalar.

    `app.py` maketdə operatora dörd mağaza verir (`STORES[:4]`) — hədddən
    (3) çoxdur.
    """
    from src.presentation import preview_data

    assert len(preview_data.STORES[:4]) > int(
        DEFAULT_LIMITS[SystemLimitKey.CAMERA_QUEUE_STORE_FILTER_THRESHOLD]
    )
    assert _queue(theme, list(preview_data.STORES[:4])).store_filter_visible
