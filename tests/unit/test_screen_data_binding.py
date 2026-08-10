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
    "_live_queue": ("group_b", "OperatorQueueScreen"),
    "_fines": ("group_b", "FineEntryScreen"),
    "_shift_planning": ("group_c", "ShiftPlanningScreen"),
    "_shift_swaps": ("group_c", "ShiftSwapScreen"),
    "_daily_roster": ("group_c", "DailyRosterScreen"),
    "_fine_appeals": ("group_f", "FineAppealInboxScreen"),
    "_tasks": ("group_f", "TasksScreen"),
    "_users": ("group_c", "UsersScreen"),
    "_audit": ("group_d", "AuditScreen"),
    "_reports": ("group_h", "ReportExportScreen"),
}


def _screen_class(module_name: str, class_name: str) -> type:
    import importlib

    module = importlib.import_module(f"src.presentation.screens.{module_name}")
    return getattr(module, class_name)  # type: ignore[no-any-return]


def _setter_calls(binder_name: str) -> list[ast.Call]:
    """Doldurucu gövdəsindəki `screen.<setter>(…)` çağırışları."""
    tree = ast.parse(SCREEN_DATA.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == binder_name:
            return [
                call
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "screen"
            ]
    pytest.fail(f"`{binder_name}` doldurucusu `screen_data.py`-da tapılmadı")


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
