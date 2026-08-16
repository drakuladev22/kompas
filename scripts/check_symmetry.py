"""Dizayn simmetriyası auditi — «eyni rol → eyni dəyər» qaydasını ölçür.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU SKRİPT VAR
──────────────────────────────────────────────────────────────────────────────
Bir ekranı tək-tək baxanda hər şey qaydasında görünür: kartın doldurması 22,
qonşu ekranda 26, üçüncüdə 18 — hər biri ayrılıqda "normal"dır. Uyğunsuzluq
YALNIZ ekranlar YAN-YANA qoyulanda üzə çıxır, istifadəçi isə onları məhz
yan-yana görür: menyudan keçid edəndə kartlar "tərpənir", başlıqlar bir-iki
piksel sürüşür və interfeys səbəbi izah edilə bilməyən bir narahatlıq verir.

Gözlə audit 72 sinifdə mümkün deyil. Ona görə ölçü mexanikidir: hər ROL üçün
(kart doldurması, başlıq ölçüsü, aralıq, sətir hündürlüyü) kod bazasında neçə
FƏRQLİ dəyər işlədildiyi sayılır. Simmetrik dizaynda bu say kiçikdir və hər
dəyərin `metrics.py`-da adı var; asimmetrik dizaynda isə ədədlər fayl-fayl
səpələnir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ 4px ŞƏBƏKƏSİ
──────────────────────────────────────────────────────────────────────────────
Şəbəkədən kənar dəyər (məs. 22) təkbaşına görünmür, lakin o, qonşu 24 və 20
ilə birlikdə şaquli ritmi pozur: kartların daxili sətirləri artıq eyni xəttə
düşmür. `design_reference/`-dəki hər referans 4px-in qatlarında işləyir.

İstifadə:
    python scripts/check_symmetry.py            # hesabat
    python scripts/check_symmetry.py --strict   # şəbəkədən kənar dəyər varsa 1
"""

from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path
from typing import Final

_ROOT = Path(__file__).resolve().parents[1]
_TARGETS: Final = (
    _ROOT / "src" / "presentation" / "screens",
    _ROOT / "src" / "presentation" / "widgets",
    _ROOT / "src" / "presentation" / "shell",
)

#: Şəbəkə addımı — `tokens.METRICS["--space-xs"]` ilə eynidir.
GRID: Final = 4

#: Hesabatda hər dəyər üçün göstərilən nümunə yerlərin sayı.
SAMPLE_PLACES: Final = 3

#: TAVAN — bu rəqəmlər YALNIZ AŞAĞI DÜŞMƏLİDİR.
#:
#: ──────────────────────────────────────────────────────────────────────────
#: NİYƏ TAVAN, NİYƏ SIFIR
#: ──────────────────────────────────────────────────────────────────────────
#: Sıfır tələb etmək 40 ekranın hamısını bir anda dəyişməyi tələb edərdi —
#: yəni ya qapı söndürülərdi, ya da nəhəng, yoxlanılması mümkün olmayan bir
#: dəyişiklik edilərdi. Tavan isə iki şeyi eyni anda təmin edir: mövcud
#: vəziyyət SƏNƏDLƏŞİR (rəqəm görünür, unudulmur) və VƏZİYYƏT PİSLƏŞMİR —
#: yeni ekran öz ad-hoc ölçüsünü gətirə bilmir.
#:
#: Hər redizayn addımından sonra bu iki rəqəm azaldılmalıdır. Artırmaq
#: qadağandır: artım o deməkdir ki, dizayn bir addım da səpələnib.
MAX_DISTINCT: Final = 66
MAX_OFF_GRID: Final = 1

#: Rol → həmin rolu daşıyan çağırışlar. Ad `metrics.py`-dakı sabitlə uyğun
#: gəlirsə, dəyər ADLIDIR və səpələnmə sayılmır.
ROLES: Final[dict[str, tuple[str, ...]]] = {
    "kart doldurması": ("Card:padding",),
    "kart aralığı": ("Card:spacing",),
    "tərtibat aralığı": ("setSpacing",),
    "başlıq ölçüsü": ("title_label:size",),
    "gövdə ölçüsü": ("body_label:size", "muted_label:size", "mono_label:size"),
    "sabit en": ("setFixedWidth", "setMinimumWidth"),
    "sabit hündürlük": ("setFixedHeight", "setMinimumHeight", "setMaximumHeight"),
}

#: Tipoqrafiya rolları — bunlar 4px ŞƏBƏKƏSİNƏ TABE DEYİL.
#:
#: Şrift ölçüsü şəbəkə deyil, ŞKALA ilə idarə olunur: `tokens.TYPOGRAPHY`
#: 11/13/15/19/26 pillələrini verir və onların 4-ə bölünməməsi qəsdəndir —
#: mətn ölçüləri həndəsi nisbətlə artır, boşluqlar isə xətti. İkisini eyni
#: qaydaya tabe etmək 13px gövdə mətnini 12 və ya 16-ya sürüşdürərdi, yəni
#: oxunaqlığı dizayn təmizliyinə qurban verərdi.
TYPOGRAPHY_ROLES: Final = frozenset({"başlıq ölçüsü", "gövdə ölçüsü"})

#: İcazə verilən şrift pillələri (`tokens.TYPOGRAPHY` + maketin aralıq
#: dəyərləri: 12 köməkçi mətn, 22 səhifə başlığı, 28 kiosk).
#: 32 = DISPLAY pilləsi: kartdakı hero rəqəm (balans, gün sayı).
#: `design_reference/dashboard.jpg` hero rəqəmi başlıqdan xeyli iri verir —
#: onu 26-ya endirmək rəqəmi qonşu başlıqla eyni çəkiyə salardı.
TYPE_SCALE: Final = frozenset({11, 12, 13, 15, 19, 22, 26, 28, 32})

_CALL_TO_ROLE: Final = {call: role for role, calls in ROLES.items() for call in calls}


class _Scanner(ast.NodeVisitor):
    """Ölçü daşıyan çağırışlardakı SABİT ədədləri toplayır.

    `metrics.X` kimi adlı istinadlar TOPLANMIR — onlar simmetriyanın həlli,
    problemi deyil. Yalnız hərfi ədədlər (`22`, `26`) qeyd olunur.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.hits: list[tuple[str, int, int]] = []  # (çağırış açarı, dəyər, sətir)

    def visit_Call(self, node: ast.Call) -> None:
        name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")

        for keyword in node.keywords:
            key = f"{name}:{keyword.arg}"
            if key in _CALL_TO_ROLE and isinstance(keyword.value, ast.Constant):
                value = keyword.value.value
                if isinstance(value, int) and not isinstance(value, bool):
                    self.hits.append((key, value, keyword.value.lineno))

        if name in _CALL_TO_ROLE:
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, int):
                    self.hits.append((name, arg.value, arg.lineno))

        self.generic_visit(node)


def _is_invalid(value: int, *, typographic: bool) -> bool:
    """Dəyər öz qaydasını pozurmu — şrift üçün ŞKALA, qalanı üçün ŞƏBƏKƏ."""
    if typographic:
        return value not in TYPE_SCALE
    # 1px İSTİSNADIR: ayırıcı xətt və sərhəd. 4px-ə yuvarlaqlaşdırılsa xətt
    # qalın zolağa dönər — yəni qayda öz məqsədinin əksini verərdi.
    if value <= 1:
        return False
    return bool(value % GRID)


def scan() -> dict[str, dict[int, list[str]]]:
    """Rol → {dəyər: [yer, …]}."""
    found: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    for target in _TARGETS:
        for path in sorted(target.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            scanner = _Scanner(path)
            scanner.visit(ast.parse(path.read_text(encoding="utf-8")))
            for key, value, line in scanner.hits:
                role = _CALL_TO_ROLE[key]
                found[role][value].append(f"{path.name}:{line}")
    return found


def main() -> int:
    strict = "--strict" in sys.argv
    found = scan()

    off_grid_total = 0
    scatter_total = 0

    print("DİZAYN SİMMETRİYASI — rol üzrə dəyər səpələnməsi")
    print("=" * 78)
    for role in ROLES:
        values = found.get(role, {})
        if not values:
            continue
        distinct = sorted(values)
        typographic = role in TYPOGRAPHY_ROLES
        off_grid = [value for value in distinct if _is_invalid(value, typographic=typographic)]
        scatter_total += len(distinct)
        off_grid_total += len(off_grid)

        print(f"\n{role.upper()}  —  {len(distinct)} fərqli dəyər")
        for value in distinct:
            places = values[value]
            invalid = _is_invalid(value, typographic=typographic)
            kind = "şkaladan" if typographic else "şəbəkədən"
            mark = f"  ⚠ {kind} kənar" if invalid else ""
            sample = ", ".join(places[:SAMPLE_PLACES])
            more = f" (+{len(places) - SAMPLE_PLACES})" if len(places) > SAMPLE_PLACES else ""
            print(f"   {value:>4}px × {len(places):<3} {sample}{more}{mark}")

    print("\n" + "=" * 78)
    print(
        f"CƏMİ: {scatter_total} fərqli dəyər, bunlardan {off_grid_total}-i 4px şəbəkəsindən kənar"
    )
    print(f"TAVAN: {MAX_DISTINCT} / {MAX_OFF_GRID}")

    if strict and (scatter_total > MAX_DISTINCT or off_grid_total > MAX_OFF_GRID):
        print(
            "\nUĞURSUZ: səpələnmə ARTIB. Yeni ad-hoc ölçü əlavə edilib — "
            "onu `widgets/metrics.py`-dakı mövcud sabitə bağlayın."
        )
        return 1
    if scatter_total < MAX_DISTINCT or off_grid_total < MAX_OFF_GRID:
        print(
            f"\nYAXŞILAŞMA: tavanı yeniləyin → MAX_DISTINCT={scatter_total}, "
            f"MAX_OFF_GRID={off_grid_total}"
        )
    print("\nQeyd: adlı istinadlar (`metrics.X`) sayılmır — onlar həllin özüdür.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
