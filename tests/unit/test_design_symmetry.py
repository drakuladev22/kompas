"""Dizayn simmetriyası qapısı — səpələnmə ARTA BİLMƏZ.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU QAPI VAR
──────────────────────────────────────────────────────────────────────────────
`scripts/check_symmetry.py` ölçür, bu fayl isə QAPILAYIR. İkisi ayrıdır, çünki
skript inkişaf zamanı əl ilə oxunur (hansı ekranda hansı ölçü səpələnib), qapı
isə hər commit-də avtomatik işləyir və yalnız BİR suala cavab verir: vəziyyət
pisləşdimi?

Qapı olmadan audit bir dəfəlik hesabat olardı: rəqəm bu gün ölçülər, sabah
yeni ekran öz `padding=23`-ünü gətirər və heç kim bilməzdi. Kod bazasında bunun
dəqiq nümunəsi var — `.design-sync/NOTES.md`-dəki kontrast sayı iki dəfə
köhnəlmişdi, çünki onu yalnız sənəd saxlayırdı.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from check_symmetry import (  # noqa: E402 - yol yuxarıda qurulur
    GRID,
    MAX_DISTINCT,
    MAX_OFF_GRID,
    ROLES,
    TYPOGRAPHY_ROLES,
    _is_invalid,
    scan,
)


def _totals() -> tuple[int, int]:
    """Qapı ölçmə qaydasını TƏKRARLAMIR — skriptin `_is_invalid`-ini çağırır.

    Əvvəl burada sadəcə `value % GRID` yazılmışdı və qapı şrift ölçülərini də
    4px şəbəkəsinə salırdı. Halbuki tipoqrafiya ŞKALA-ya (11/13/15/19/22/26/28)
    tabedir — 13px şəbəkədən kənardır, lakin tamamilə düzgündür. İki yerdə iki
    fərqli qayda saxlamaq məhz bu yalan xəbərdarlığı doğurmuşdu; indi qayda
    TƏK yerdədir (`scripts/check_symmetry.py`).
    """
    found = scan()
    distinct = 0
    off_grid = 0
    for role in ROLES:
        values = found.get(role, {})
        distinct += len(values)
        typographic = role in TYPOGRAPHY_ROLES
        off_grid += sum(1 for value in values if _is_invalid(value, typographic=typographic))
    return distinct, off_grid


def test_design_scatter_does_not_grow() -> None:
    """Fərqli ölçü dəyərlərinin sayı tavanı keçməməlidir.

    Keçirsə, kimsə mövcud `metrics.py` sabitini işlətmək əvəzinə yeni bir
    ad-hoc ədəd yazıb — həmin ekran qonşularından bir-iki piksel sürüşəcək və
    fərq yalnız ekranlar yan-yana görüldükdə hiss olunacaq.
    """
    distinct, _off_grid = _totals()
    assert distinct <= MAX_DISTINCT, (
        f"ölçü səpələnməsi artıb: {distinct} > {MAX_DISTINCT}. Yeni ədədi "
        "`widgets/metrics.py`-dakı mövcud sabitə bağlayın."
    )


def test_off_grid_values_do_not_grow() -> None:
    """4px şəbəkəsindən kənar dəyərlərin sayı tavanı keçməməlidir."""
    _distinct, off_grid = _totals()
    assert off_grid <= MAX_OFF_GRID, (
        f"şəbəkədən kənar dəyər artıb: {off_grid} > {MAX_OFF_GRID}. "
        f"Ölçünü {GRID}px-in qatına yuvarlaqlaşdırın."
    )


def test_the_ceiling_is_not_left_behind() -> None:
    """Tavan faktiki vəziyyətdən ÇOX YUXARIDA qalmamalıdır.

    Redizayn səpələnməni azaldır; tavan isə köhnə rəqəmdə qalsaydı, qapı
    yavaş-yavaş mənasızlaşardı — aralıq böyüdükcə yeni ad-hoc ölçülər
    «tavanın altında» sərbəst yığıla bilərdi. 10 vahidlik pəncərə redizaynın
    bir addımına icazə verir, yığılmağa isə yox.
    """
    distinct, off_grid = _totals()
    assert MAX_DISTINCT - distinct <= 10, (
        f"tavan köhnəlib: faktiki {distinct}, tavan {MAX_DISTINCT} — "
        "`scripts/check_symmetry.py`-da MAX_DISTINCT-i yeniləyin"
    )
    assert MAX_OFF_GRID - off_grid <= 10, (
        f"tavan köhnəlib: faktiki {off_grid}, tavan {MAX_OFF_GRID} — "
        "`scripts/check_symmetry.py`-da MAX_OFF_GRID-i yeniləyin"
    )
