"""Ekran siniflərinin funksional imzasını AST ilə çıxaran ORTAQ skaner (FINAL-UI).

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA MODUL — HƏM TEST, HƏM YENİLƏMƏ ALƏTİ EYNİ FUNKSİYANI ÇAĞIRIR
──────────────────────────────────────────────────────────────────────────────
`test_ui_screen_regression_gate.py` (baseline ilə MÜQAYİSƏ edir) və
`tests/tools/refresh_ui_baseline.py` (baseline-ı YENİDƏN YAZIR) EYNİ ölçmə
məntiqini işlətməlidir — əks halda «test niyə fərqli sayır» sualı hər dəyişən
skan alqoritmi ilə yenidən doğular. Ona görə ölçmə BİR yerdə yazılıb, hər iki
tərəfindən İDXAL olunur (`qa_harness.py`-dəki eyni əsaslandırma).

──────────────────────────────────────────────────────────────────────────────
NİYƏ YALNIZ AST — QT QURULMUR
──────────────────────────────────────────────────────────────────────────────
`.venv`-də PySide6 var, amma bu skan `Signal(...)` elanının, `set_*`/
`populate*` metodunun VƏ `.connect()` çağırışının SİNTAKTİK MÖVCUDLUĞUNU
ölçür — widget-in İCRA zamanı necə davrandığını yox. AST bunu Qt-siz, saniyə
alt sürətdə edir; 99 sinif üçün hər `pytest` çağırışında pəncərə qurmaq
(hətta `offscreen`-də) lazımsız yükdür.

──────────────────────────────────────────────────────────────────────────────
BU SKAN NƏYİ ÖLÇÜR, NƏYİ ÖLÇMÜR
──────────────────────────────────────────────────────────────────────────────
Ölçür: sinif GÖVDƏSİNDƏ birbaşa elan olunan `Signal(...)` ADLARI, sinif
gövdəsindəki `def set_*`/`def populate*` metod ADLARI, və sinif altındakı
İSTƏNİLƏN `.connect(...)` çağırışının SAYI (`ast.walk` — daxili funksiyalar,
lambda-lar daxil, çünki `connect()` çağırışı çox vaxt `_wire()` tipli kömekçi
metodda və ya lambda daxilində olur).

ÖLÇMÜR: bağlantının DOĞRU siqnala/slota getdiyini, `set_*` metodunun DÜZGÜN
parametr aldığını, `.connect()`-in İŞLƏK olduğunu (məs. `self._x.clicked.
connect(...)` — `_x` mövcud olmaya da bilər, sintaktik cəhətdən fərq etməz).
Bu, QƏSDƏNDİR (bax `test_ui_screen_regression_gate.py` başlığı): dəqiqlik
əvəzinə ƏHATƏ seçilib, çünki 424 elementin HƏR birinin DOĞRULUĞUNU statik
yoxlamaq `ui-inventory`-nin tapdığı kimi (147 xam «bağlanmamış» namizəddən
143-ü yalançı-müsbət) əlçatmazdır.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TypedDict


class ScreenClassSignature(TypedDict):
    """Bir ekran sinfinin FUNKSİONAL barmaq izi — `dict`, çünki `refresh_ui_
    baseline.py` bunu birbaşa Python literalı kimi fayla yazır (dataclass
    `repr()`-i formatlaşdırmaq üçün əlavə addım tələb edərdi)."""

    signals: tuple[str, ...]
    setters: tuple[str, ...]
    connect_count: int


#: `(fayl_adı, sinif_adı)` — TƏK sinif adı KİFAYƏT ETMİR: iki fərqli ekran
#: faylı nəzəri olaraq eyni adlı sinif elan edə bilər (məs. iki modulda
#: `_Row` köməkçisi), fayl adı əlavə edilməsə belə toqquşma SÜKUTLA bir-
#: birini əvəz edərdi.
ScreenKey = tuple[str, str]


def _constructor_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def scan_screen_classes(screens_dir: Path) -> dict[ScreenKey, ScreenClassSignature]:
    """`screens_dir`-dəki HƏR `.py` faylının HƏR ÜST-SƏVİYYƏ sinfini skan edir.

    Yalnız ÜST-SƏVİYYƏ (`tree.body`-dəki) siniflər sayılır — daxili
    (nested) siniflər layihədə işlədilmir, `ui-inventory`-nin əsas
    inventarı da eyni əhatəni işlətmişdi (bax `report.md`: 99 sinif).
    """
    result: dict[ScreenKey, ScreenClassSignature] = {}
    for path in sorted(screens_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            signals: list[str] = []
            setters: list[str] = []
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and isinstance(stmt.value, ast.Call)
                    and _constructor_name(stmt.value) == "Signal"
                ):
                    signals.extend(
                        target.id for target in stmt.targets if isinstance(target, ast.Name)
                    )
                if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef) and (
                    stmt.name.startswith("set_") or stmt.name.startswith("populate")
                ):
                    setters.append(stmt.name)
            connect_count = sum(
                1
                for sub in ast.walk(node)
                if isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "connect"
            )
            result[(path.name, node.name)] = ScreenClassSignature(
                signals=tuple(signals), setters=tuple(setters), connect_count=connect_count
            )
    return result


__all__ = ["ScreenClassSignature", "ScreenKey", "scan_screen_classes"]
