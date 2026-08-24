"""FETCH/APPLY üç-mərhələli naxışın SAP SƏRHƏDİ (PERF-6 Faza B/C/D).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TEST VACİBDİR
──────────────────────────────────────────────────────────────────────────────
`screen_data.py`-dəki doldurucular üç mərhələyə bölünüb:

    <binder>_inputs(screen)          → ƏSAS SAP: YALNIZ Qt OXUYUR
    <binder>_fetch(session, params)  → FON SAPI: YALNIZ DB, Qt-yə TOXUNMUR
    <binder>_apply(screen, data)     → ƏSAS SAP: YALNIZ Qt, DB-yə TOXUNMUR

Bölünmənin BÜTÜN mənası budur ki, ağır `fetch` mərhələsi fon sapına
köçürülə bilsin (`ScreenDataBinder.populate()` başlığı) və GUI donmasın.
Qayda pozulanda nəticə SÜKUTLA baş verir, kod-nəzərdən-keçirmə isə onu
HƏMİŞƏ tutmur:

    * `*_fetch` içində qalan bir `screen.set_*()` çağırışı FON SAPINDAN Qt
      widget-inə toxunar. Qt widget-ləri sap-təhlükəsiz DEYİL
      (`background_task.py` başlığı) — nəticə sınmış render, təsadüfi
      çökmə və ya heç nə ola bilər, üstəlik ÇOX VAXT inkişaf maşınında
      REPRODUKSİYA OLUNMUR (sap vaxtlamasından asılıdır). Yəni bu qüsur
      məhz istehsalatda, ən pis anda üzə çıxır.
    * `*_apply` içində qalan bir `session`/`self._context` istifadəsi əks
      istiqamətdə eyni zərəri verir: DB sorğusu YENİDƏN əsas sapda gedər
      və bütün PERF-6 düzəlişini SÜKUTLA geri qaytarar — heç bir mövcud
      test bunu tutmur, çünki nəticə (ekranda düzgün məlumat) DƏYİŞMİR,
      yalnız HANSI SAPDA əldə edildiyi dəyişir.

Test `screen_data.py`-ı İCRA ETMİR, YALNIZ AST ilə oxuyur (Qt/DB tələb
etmir) — naxış `test_screen_data_binding.py`-dəki üsulun eynidir.

Bu fayl `test_screen_data_binding.py`-dən AYRIDIR: o, doldurucunun ekranın
REAL setter imzası ilə uyğunluğunu yoxlayır (setter ADI/ARQUMENTLƏRİ), bu isə
HANSI SAPDA nə işlədiyini — fərqli qaydalar, fərqli qüsur növü.

Ad siyahısı QƏSDƏN YOXDUR: metodlar `*_fetch`/`*_apply` SUFFIKSİNƏ görə
avtomatik tapılır. FAZA C/D-də daha çox doldurucu eyni naxışa keçəcək —
sabit siyahı olsaydı, yeni metod əlavə olunanda test onu SÜKUTLA nəzərdən
qaçırardı və qoruma öz mənasını itirərdi (bax `test_binder_calls_match_
screen_setter_signatures`-in eyni səbəbli `DELEGATED_BINDERS`-i).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.unit

SCREEN_DATA: Final = (
    Path(__file__).resolve().parents[2] / "src/presentation/controllers/screen_data.py"
)


def _tree() -> ast.Module:
    return ast.parse(SCREEN_DATA.read_text(encoding="utf-8"))


def _methods_ending_with(suffix: str) -> list[ast.FunctionDef]:
    """Adı `suffix` ilə bitən HƏR metod — sinifdən asılı olmayaraq.

    Sabit ad siyahısı YOXDUR (bax modul başlığı) — yalnız suffiks uyğunluğu.
    """
    return [
        node
        for node in ast.walk(_tree())
        if isinstance(node, ast.FunctionDef) and node.name.endswith(suffix)
    ]


def _arg_names(node: ast.FunctionDef) -> set[str]:
    args = node.args
    return (
        {
            arg.arg
            for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)
            if arg.arg not in {"self", "cls"}
        }
        | ({args.vararg.arg} if args.vararg else set())
        | ({args.kwarg.arg} if args.kwarg else set())
    )


def _screen_attribute_refs(node: ast.FunctionDef) -> list[str]:
    """`screen.<nə isə>` formasında olan HƏR atribut istinadı.

    Yalnız ÇAĞIRIŞLAR yox — `screen.x` oxunuşu da fon sapından Qt widget-inə
    TOXUNMAQDIR (setter çağırmasa belə, `getattr` özü Qt-ni sorğulayır).
    """
    return [
        f"screen.{child.attr}"
        for child in ast.walk(node)
        if isinstance(child, ast.Attribute)
        and isinstance(child.value, ast.Name)
        and child.value.id == "screen"
    ]


def _uses_name(node: ast.FunctionDef, name: str) -> bool:
    return any(isinstance(child, ast.Name) and child.id == name for child in ast.walk(node))


def _uses_self_context(node: ast.FunctionDef) -> bool:
    return any(
        isinstance(child, ast.Attribute)
        and child.attr == "_context"
        and isinstance(child.value, ast.Name)
        and child.value.id == "self"
        for child in ast.walk(node)
    )


def test_fetch_methods_never_touch_the_screen() -> None:
    """`*_fetch` FON SAPINA köçürülür — Qt widget-inə TOXUNA BİLMƏZ.

    Nə imzada `screen` arqumenti, nə gövdədə `screen.<...>` istinadı ola
    bilər. `assert fetch_methods` — heç bir metod tapılmasa test «0 yoxladım,
    hamısı keçdi» deyə YAŞIL qalmamalıdır (bax modul başlığı: adlar
    dəyişsə/köçsə bu, ən yayılmış səssiz ölüm formasıdır).
    """
    fetch_methods = _methods_ending_with("_fetch")
    assert fetch_methods, (
        "`*_fetch` adında HEÇ BİR metod tapılmadı — ad naxışı dəyişibmi? "
        "(bu boş nəticə testin özünü mənasız edər)"
    )

    failures: list[str] = []
    for node in fetch_methods:
        if "screen" in _arg_names(node):
            failures.append(
                f"`{node.name}` imzasında `screen` arqumenti var — fon sapına lazım deyil"
            )
        refs = _screen_attribute_refs(node)
        if refs:
            failures.append(
                f"`{node.name}` FON SAPINDAN Qt-yə toxunur: {', '.join(sorted(set(refs)))}"
            )

    assert not failures, "\n".join(failures)


def test_apply_methods_never_touch_the_database() -> None:
    """`*_apply` ƏSAS SAPDA işləyir — `session`/`self._context` İŞLƏNMƏMƏLİDİR.

    Geri istiqamətdəki eyni qapı: DB sorğusu bura sızsaydı, GUI sapı
    yenidən bloklanardı və PERF-6 düzəlişi sükutla geri qayıdardı.
    """
    apply_methods = _methods_ending_with("_apply")
    assert apply_methods, (
        "`*_apply` adında HEÇ BİR metod tapılmadı — ad naxışı dəyişibmi? "
        "(bu boş nəticə testin özünü mənasız edər)"
    )

    failures: list[str] = []
    for node in apply_methods:
        if "session" in _arg_names(node):
            failures.append(
                f"`{node.name}` imzasında `session` arqumenti var — əsas sapa lazım deyil"
            )
        elif _uses_name(node, "session"):
            failures.append(
                f"`{node.name}` ƏSAS SAPDA `session` işlədir — DB oxusu `fetch`-ə aiddir"
            )
        if _uses_self_context(node):
            failures.append(
                f"`{node.name}` ƏSAS SAPDA `self._context` işlədir — sessiya açmaq `fetch`-ə aiddir"
            )

    assert not failures, "\n".join(failures)
