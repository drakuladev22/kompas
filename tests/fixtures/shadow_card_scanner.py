"""`shadow=True` çağırış yerlərini AST ilə çıxaran ORTAQ skaner (vizual iş).

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA MODUL — `ui_screen_scanner.py` İLƏ EYNİ ƏSASLANDIRMA
──────────────────────────────────────────────────────────────────────────────
`test_shadow_card_width_gate.py` (baseline ilə MÜQAYİSƏ edir) və
`tests/tools/refresh_shadow_card_baseline.py` (baseline-ı YENİDƏN YAZIR) EYNİ
ölçmə məntiqini işlətməlidir. Ölçmə BİR yerdə yazılıb, hər iki tərəfindən
İDXAL olunur.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AD DEYİL, (fayl, sinif, metod, sıra) AÇARI
──────────────────────────────────────────────────────────────────────────────
`shadow=True` çağırışı bir sətir kodudur, sətir NÖMRƏSİ isə vizual işin bu
mərhələsində DAİM sürüşür (hər redaktə, hər yeni şərh sətri) — sətirlə açarlaşan
baseline HƏR redaktədə yalançı-müsbət verərdi. `(fayl, sinif, metod)` üçlüyü
DAHA sabitdir, LAKİN tək başına kifayət etmir: `DashboardScreen.__init__`
kimi bir metod BİRDƏN ARTIQ kart qura bilər (bax `group_c.py`). Ona görə
DÖRDÜNCÜ element — HƏMİN üçlük daxilindəki SIRA NÖMRƏSİ (0-dan) — əlavə
olunur. Bu açar YALNIZ fayl/sinif/metod adı dəyişəndə VƏ YA çağırışların
NİSBİ SIRASI dəyişəndə (nadir, real struktur dəyişikliyi) sürüşür — sadə
sətir sürüşməsindən TAM İMMUNDUR.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

#: `(fayl_adı, sinif_adı, metod_adı, həmin_metoddakı_sıra)`.
ShadowCardKey = tuple[str, str, str, int]


class ShadowCardSite(NamedTuple):
    """Bir `shadow=True` çağırışının DİAQNOSTİK məlumatı (mesajlar üçün)."""

    lineno: int


def _is_shadow_true_keyword(node: ast.Call) -> bool:
    return any(
        keyword.arg == "shadow"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for keyword in node.keywords
    )


def scan_shadow_card_sites(screens_dir: Path) -> dict[ShadowCardKey, ShadowCardSite]:
    """`screens_dir`-dəki HƏR `.py` faylında `shadow=True` çağırışlarını tapır.

    Yalnız SİNİF METODLARININ (funksiya DEYİL, modul-səviyyəli də DEYİL)
    daxilindəki çağırışlar sayılır — bütün mövcud `shadow=True` istifadələri
    (`Card(shadow=True)` VƏ `super().__init__(..., shadow=True, ...)`)
    sinif metodu daxilindədir, bax `git grep 'shadow=True' src/presentation`.
    """
    result: dict[ShadowCardKey, ShadowCardSite] = {}
    for path in sorted(screens_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            for func in ast.walk(cls):
                if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                occurrence = 0
                for node in ast.walk(func):
                    if isinstance(node, ast.Call) and _is_shadow_true_keyword(node):
                        key = (path.name, cls.name, func.name, occurrence)
                        result[key] = ShadowCardSite(lineno=node.lineno)
                        occurrence += 1
    return result


__all__ = ["ShadowCardKey", "ShadowCardSite", "scan_shadow_card_sites"]
