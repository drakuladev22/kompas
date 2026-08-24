"""Canlı doldurucuların ekran setter imzaları ilə uyğunluğu.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TEST VACİBDİR
──────────────────────────────────────────────────────────────────────────────
`ScreenDataBinder.populate()` hər doldurucunu `try/except Exception` içində
çağırır — bir ekranın problemi bütün örtüyü çökdürməsin deyə. Nəticə: səhv
imza ilə çağırış (`TypeError`) və ya səhv sözlük açarı (`KeyError`) SÜKUTLA
udulur, ekran isə boş qalır. İstifadəçi "məlumat yoxdur" görür, jurnalda isə
səbəb `error.log`-dadır — yəni qüsur aylarla gizli qala bilər.

Layihədə məhz bu baş verib: `set_matrix(rows)` iki arqument gözləyirdi,
`set_entries(...)` `result_text` tələb edirdi, `set_users` isə `full_name`
açarını oxuyurdu — dördü də canlı rejimdə boş ekran verirdi, heç bir test
qırılmırdı.

`screen: Any` annotasiyası mypy-ı da kor edir, ona görə statik yoxlama da
tutmurdu. Bu test həmin boşluğu bağlayır: hər doldurucunun çağırdığı setter
ADI və ARQUMENTLƏRİ real ekran sinfinin imzası ilə tutuşdurulur.

Testlər Qt tələb ETMİR: `inspect.signature` ilə işləyir, widget qurulmur.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any, Final

import pytest

pytestmark = pytest.mark.unit

BINDER_MODULE: Final = Path(__file__).resolve().parents[2] / "src/presentation/controllers"
SCREEN_DATA: Final = BINDER_MODULE / "screen_data.py"

#: Doldurucu adı → ekran sinfi. `app.py`-dakı `factories` ilə eyni cütlərdir.
BINDER_SCREENS: Final[dict[str, tuple[str, str]]] = {
    "_dashboard": ("group_c", "DashboardScreen"),
    "_live_queue": ("group_b", "OperatorQueueScreen"),
    "_fines": ("group_b", "FineEntryScreen"),
    "_shift_planning": ("group_c", "ShiftPlanningScreen"),
    "_shift_swaps": ("group_c", "ShiftSwapScreen"),
    "_daily_roster": ("group_c", "DailyRosterScreen"),
    "_fine_appeals": ("group_f", "FineAppealInboxScreen"),
    "_tasks": ("group_f", "TasksScreen"),
    "_sales_points": ("group_f", "SalesPointsScreen"),
    "_users": ("group_c", "UsersScreen"),
    "_audit": ("group_d", "AuditScreen"),
    "_reports": ("group_h", "ReportExportScreen"),
    "_help": ("group_h", "HelpCenterScreen"),
    "_health": ("group_d", "HealthScreen"),
}

#: Setter çağırışlarını KÖMƏKÇİ metodlara paylayan doldurucular.
#:
#: Dashboard beş müstəqil bölmədən ibarətdir (rəqəm kartları, qrafik, ölçən,
#: liderlər, serverlər) və hamısını bir funksiyada yazmaq 150 sətirlik blok
#: yaradardı. Bölünmə imza yoxlamasını POZMAMALIDIR, ona görə köməkçilər
#: burada AÇIQ sadalanır — yenisi əlavə olunub bura yazılmasa, onun setter
#: çağırışı statik yoxlamadan kənarda qalar.
DELEGATED_BINDERS: Final[dict[str, tuple[str, ...]]] = {
    "_dashboard": (
        "_dashboard_summary_apply",
        "_dashboard_fines_apply",
        "_dashboard_leave_apply",
        "_dashboard_leaders_apply",
        "_dashboard_health_apply",
        "_dashboard_network_apply",
        # `_dashboard_benchmark` ÖZÜ heç bir setter çağırmır — icazə
        # yoxlamasından sonra dörd setteri (`set_ranking_table`, `set_store_
        # vs_network`, `set_metric_trend`, `set_outliers`) çağıran BU
        # metoda delegə edir (`refresh_dashboard_benchmark` da EYNİsini
        # paylaşır). DOĞRU AD BUDUR — QƏSDƏN QIRMIZI qalır:
        # `_dashboard_benchmark_apply`-ın `screen.set_store_vs_network(**
        # data.comparison)` çağırışı `test_screen_data_forbids_kwargs_
        # unpacking_calls`-ı pozur (`screen_data.py:1193`, TƏK kök səbəb).
        # Köhnə/səhv addan (`_populate_benchmark_sections`) İSTİFADƏ ETMİRİK
        # — o, qırmızını YANLIŞ səbəblə («funksiya tapılmadı») göstərərdi.
        "_dashboard_benchmark_apply",
        "_dashboard_break_overuse_apply",
    ),
    # #13 — tarixi nümunə kartı Növbə Matrisinin İKİNCİ, müstəqil bölməsidir
    # (matris + məsləhət). Ayrı köməkçi olması onun heç nə təyin etmədiyini
    # struktur olaraq göstərir; imza yoxlaması isə burada elan edildiyi üçün
    # onu da əhatə edir.
    "_shift_planning": ("_render_shift_matrix_apply", "_shift_staffing_pattern_apply"),
    "_fines": ("_fines_apply",),
    "_help": ("_help_apply",),
    "_shift_swaps": ("_shift_swaps_apply",),
    "_fine_appeals": ("_fine_appeals_apply",),
    "_tasks": ("_tasks_apply",),
    "_sales_points": ("_sales_points_apply",),
    "_reports": ("_reports_apply",),
    "_audit": ("_audit_apply",),
    "_live_queue": ("_live_queue_apply",),
    "_users": ("_users_apply",),
    "_health": ("_health_apply",),
    "_daily_roster": ("_daily_roster_apply",),
}


def _screen_class(module_name: str, class_name: str) -> type:
    import importlib

    module = importlib.import_module(f"src.presentation.screens.{module_name}")
    return getattr(module, class_name)  # type: ignore[no-any-return]


def _setter_calls_by_source(binder_name: str) -> dict[str, list[ast.Call]]:
    """Doldurucunun (və elan edilmiş köməkçilərinin) `screen.<setter>(…)` çağırışları.

    Nəticə AD ÜZRƏ ayrıdır (`binder_name` özü + hər `DELEGATED_BINDERS` girişi
    üçün AYRI siyahı) — `test_every_delegate_contributes_a_setter_call`-a
    lazımdır: yekun (bütün adları birləşdirilmiş) siyahının boş OLMAMASI
    kifayət etmir, çünki bir delegat SIFIR çağırış versə, digərlərinin
    çağırışları onu SÜKUTLA örtür (bax modul başlığı — `_dashboard_benchmark`
    məhz bu vəziyyətdə tapıldı).
    """
    wanted = {binder_name, *DELEGATED_BINDERS.get(binder_name, ())}
    tree = ast.parse(SCREEN_DATA.read_text(encoding="utf-8"))
    by_source: dict[str, list[ast.Call]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in wanted:
            continue
        by_source[node.name] = [
            call
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "screen"
        ]
    missing = wanted - by_source.keys()
    if missing:
        pytest.fail(f"`screen_data.py`-da tapılmadı: {sorted(missing)}")
    return by_source


def _setter_calls(binder_name: str) -> list[ast.Call]:
    """`_setter_calls_by_source`-un YEKUN (bütün mənbələr birləşdirilmiş) forması."""
    return [call for calls in _setter_calls_by_source(binder_name).values() for call in calls]


def test_every_registered_binder_is_covered_here() -> None:
    """Yeni doldurucu əlavə olunanda bu test də yenilənməlidir.

    Qapı budur: `_binders()`-dəki açar bu faylda yoxdursa, həmin ekran statik
    yoxlamadan kənarda qalır və köhnə qüsur yenidən mümkün olur.
    """
    tree = ast.parse(SCREEN_DATA.read_text(encoding="utf-8"))
    registered: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_binders":
            registered = {
                value.attr
                for value in ast.walk(node)
                if isinstance(value, ast.Attribute) and value.attr.startswith("_")
            }
            break

    # Köməkçilər `_binders()`-də QEYDİYYATDA DEYİL — onlar bir doldurucunun
    # daxili bölünməsidir və ayrıca ekran açarına bağlanmır.
    registered -= {name for names in DELEGATED_BINDERS.values() for name in names}

    assert registered, "`_binders()` tapılmadı"
    difference = registered ^ set(BINDER_SCREENS)
    assert not difference, (
        f"`_binders()` ilə cədvəl fərqlənir: {sorted(difference)} — "
        f"yeni doldurucu əlavə edildikdə `BINDER_SCREENS` də yenilənməlidir"
    )


@pytest.mark.parametrize("binder_name", sorted(BINDER_SCREENS))
def test_binder_calls_match_screen_setter_signatures(binder_name: str) -> None:
    """Hər `screen.<setter>(…)` çağırışı real imzaya bağlana bilməlidir.

    `Signature.bind` arqument sayını, açar-arqumentlərin adını və MƏCBURİ
    parametrlərin verilməsini yoxlayır — yəni `TypeError`-u icradan ƏVVƏL
    tutur. Dəyərlərin özü `object()` ilə əvəzlənir, çünki burada yoxlanan
    məzmun deyil, MÜQAVİLƏDİR.
    """
    module_name, class_name = BINDER_SCREENS[binder_name]
    screen_class = _screen_class(module_name, class_name)

    calls = _setter_calls(binder_name)
    assert calls, f"`{binder_name}` heç bir setter çağırmır — doldurucu ölüdür"

    for call in calls:
        setter_name = call.func.attr  # type: ignore[union-attr]
        setter = getattr(screen_class, setter_name, None)
        assert setter is not None, (
            f"{class_name}.{setter_name}() YOXDUR — `{binder_name}` onu çağırır"
        )

        signature = inspect.signature(setter)
        positional: list[Any] = [None, *[object() for _ in call.args]]
        keywords = {keyword.arg: object() for keyword in call.keywords if keyword.arg is not None}
        try:
            signature.bind(*positional, **keywords)
        except TypeError as error:
            pytest.fail(
                f"{class_name}.{setter_name}{signature} — `{binder_name}` yanlış çağırır: {error}"
            )


@pytest.mark.parametrize("binder_name", sorted(BINDER_SCREENS))
def test_every_delegate_contributes_a_setter_call(binder_name: str) -> None:
    """`DELEGATED_BINDERS`-də AÇIQ elan edilmiş HƏR ad ƏN AZI BİR çağırış verməlidir.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `test_binder_calls_match_screen_setter_signatures` BUNU TUTMUR
    ──────────────────────────────────────────────────────────────────────────
    O test yalnız YEKUN (bütün delegatlar birləşdirilmiş) siyahının boş
    OLMAMASINI tələb edir. Bir delegat adı KÖHNƏLSƏ (funksiya adı dəyişib
    və ya başqa yerə köçübsə) — `missing` yoxlaması `screen_data.py`-da HEÇ
    BİR funksiya bu adı daşımadıqda tutur, LAKİN funksiya HƏLƏ MÖVCUDDURSA,
    sadəcə artıq `screen.set_*` ÇAĞIRMIRSA (məs. daha da dərin bir köməkçiyə
    delegə edibsə) — bu SÜKUTLA keçir, çünki digər delegatların çağırışları
    yekun siyahını onsuz da boş qoymur.

    Məhz bu formada tapıldı: `_dashboard_benchmark` DELEGATED_BINDERS-də idi,
    LAKİN özü heç bir setter çağırmırdı (`_populate_benchmark_sections`-a
    delegə edirdi) — test digər yeddi bölmənin çağırışları sayəsində YAŞIL
    qalırdı və dörd setterin (`set_ranking_table`, `set_store_vs_network`,
    `set_metric_trend`, `set_outliers`) İMZASI heç vaxt yoxlanılmırdı.

    Əsas binder-in (`binder_name`) ÖZÜNÜN sıfır çağırış verməsi NORMALDIR —
    bu, doldurucunun bütün işini köməkçilərə həvalə etdiyi (delegasiya) hal
    üçün gözlənilir. Yoxlama YALNIZ `DELEGATED_BINDERS`-də AÇIQ sadalanmış
    adlara aiddir.
    """
    by_source = _setter_calls_by_source(binder_name)
    for delegate_name in DELEGATED_BINDERS.get(binder_name, ()):
        assert by_source.get(delegate_name), (
            f"`DELEGATED_BINDERS['{binder_name}']` içindəki `{delegate_name}` heç bir "
            f"setter çağırmır — ad köhnəlib, ya da funksiya başqa (daha dərin) "
            f"bir köməkçiyə delegə edir"
        )


def test_screen_data_forbids_kwargs_unpacking_calls() -> None:
    """`screen.<setter>(**mapping)` QADAĞANDIR — açıq açar-arqumentlər tələb olunur.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ
    ──────────────────────────────────────────────────────────────────────────
    `**` açılışı imza yoxlamasını YAN KEÇİR: nə bu fayldakı AST testi
    (`ast.keyword.arg` belə çağırışlarda HƏMİŞƏ `None`-dur, real açar adları
    YALNIZ İCRA ZAMANI, dict-in məzmunu ilə məlumdur), nə mypy (`dict[str,
    Any]` açılışının açarlarını setter imzası ilə tutuşdurmur) bunu tuta
    bilir. Uyğunsuzluğun nəticəsi udulan `TypeError` və BOŞ ekrandır —
    `_audit_apply`-ın öz şərhi məhz bu qüsur sinfini izah edir (səhv açar
    `TypeError` atırdı, `populate()` onu udurdu, cədvəl canlı rejimdə
    HƏMİŞƏ boş qalırdı).

    ──────────────────────────────────────────────────────────────────────────
    YAZILDIĞI GÜN QIRMIZI İDİ — İNDİ HƏLL OLUNUB
    ──────────────────────────────────────────────────────────────────────────
    Yazılanda `screen_data.py`-də bütün faylda YEGANƏ pozuntu `_dashboard_
    benchmark_apply`-dakı `screen.set_store_vs_network(**data.comparison)`
    idi. `ui-speed` sətri açıq açar-arqumentlərə keçirdi VƏ `_DashboardBench
    markData.comparison`-ı `dict[str, Any] | None`-dan `_BenchmarkComparison
    | None` (frozen dataclass) etdi — indi mypy sahə adlarını, bu test isə
    setter imzasını yoxlayır. `test_binder_calls_match_screen_setter_
    signatures`-dəki müvəqqəti `**` güzəşti bu səbəbdən SİLİNİB (geri
    qaytarılmamalıdır — o, məhz bu testin YEGANƏ, dəqiq siqnal olması üçün
    var idi).

    Qəsdən `xfail` İŞLƏDİLMƏDİ: xfail bu qadağanı GÖRÜNMƏZ edərdi — qırmızı
    sətir problemi dəqiq bildirən SİQNAL idi, indi isə testin ÖZÜ qaydanın
    gələcəkdə sükutla pozulmasının qarşısını alır.
    """
    tree = ast.parse(SCREEN_DATA.read_text(encoding="utf-8"))
    violations: list[str] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "screen"
            and any(keyword.arg is None for keyword in node.keywords)
        ):
            continue
        violations.append(
            f"{SCREEN_DATA.name}:{node.lineno} — screen.{node.func.attr}(**...) qadağandır: "
            f"`**` açılışı imza yoxlamasını yan keçir (nə bu AST testi, nə mypy açarların "
            f"setter imzasına uyğunluğunu yoxlaya bilir; uyğunsuzluğun nəticəsi udulan "
            f"`TypeError` və BOŞ ekrandır — bax `_audit_apply` şərhi). Açıq açar-"
            f"arqumentlərə keçirin."
        )

    assert not violations, "\n".join(violations)


# --------------------------------------------------------------------------- #
# Boş vəziyyət
# --------------------------------------------------------------------------- #


def test_screen_state_wrappers_are_not_kwargs_typed() -> None:
    """`Screen.show_empty/show_error` TAM imzalı olmalıdır, `**kwargs` yox.

    `**kwargs: object` + `# type: ignore` mypy-ı kor edirdi və üç ekran
    `message=` əvəzinə `body=` göndərirdi — boş siyahı ilə `TypeError`.
    Boş siyahı isə ilk quraşdırmada NORMAL haldır.
    """
    from src.presentation.screens.base import Screen

    for method_name in ("show_empty", "show_error"):
        signature = inspect.signature(getattr(Screen, method_name))
        kinds = {parameter.kind for parameter in signature.parameters.values()}
        assert inspect.Parameter.VAR_KEYWORD not in kinds, (
            f"Screen.{method_name} yenidən `**kwargs` qəbul edir — "
            f"çağırış yerləri statik yoxlanılmayacaq"
        )
        assert "title" in signature.parameters
        assert "message" in signature.parameters
