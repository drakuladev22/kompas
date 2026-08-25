"""`TYPE_CHECKING` altında idxal olunan adın İCRA zamanı çağırılması (v2backlog Faza 15).

──────────────────────────────────────────────────────────────────────────────
BU QAPI NİYƏ VAR — İKİ FUNKSİYA MƏHZ BELƏ SÜKUTLA SINDI
──────────────────────────────────────────────────────────────────────────────
`composition.py` idxalları İKİ yerə bölür: `if TYPE_CHECKING:` bloku (yalnız
tip annotasiyaları üçün — açılış sürətinə görə, bax modul başlığı) və sessiya
qrafını quran metodun İÇİNDƏKİ icra-idxalları. Yeni use case əlavə edən adam
birincisini yazır (çünki `dataclass` sahəsinin tipi ONA görə lazımdır), ikinci
siyahı isə 170 sətirlik əlifba sırasıdır və gözdən qaçır.

Nəticə sükutludur: `mypy` YAŞIL qalır (tip mövcuddur), `ruff` YAŞIL qalır
(idxal işlədilib), fayl idxal olunur (modul səviyyəsində heç nə çağırılmır) —
qüsur yalnız sessiya qrafı FAKTİKİ qurulanda `NameError` kimi partlayır.
Məhz bu, `CampaignPeriodsUseCase` (Faza 6.4) və `WhatsNewUseCase` (Faza 8.2)
ilə baş verdi: hər ikisi `TYPE_CHECKING` altında idi, hər ikisi
`_build_use_cases()` içində çağırılırdı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `mypy` BUNU TUTMUR
──────────────────────────────────────────────────────────────────────────────
`mypy` TYPE_CHECKING blokunu HƏMİŞƏ doğru sayır — onun üçün ad mövcuddur.
Ayrılıq məhz orasındadır ki, icra zamanı həmin blok İŞLƏMİR. Yəni bu qüsur
statik yoxlayıcının kor nöqtəsindədir və yalnız AST səviyyəsində, «hansı ad
harada mövcuddur» sualı ilə tutula bilər.

──────────────────────────────────────────────────────────────────────────────
YALNIZ ÇAĞIRIŞ (`Call`) YOXLANILIR
──────────────────────────────────────────────────────────────────────────────
`Foo | None` annotasiyası, `cast(Foo, x)`-in birinci arqumenti və sətir-tipli
annotasiyalar TYPE_CHECKING adını icra etmir — onlar qanunidir. Partlayan
YEGANƏ istifadə `Foo(...)` formasıdır, ona görə test yalnız onu axtarır və
səhv-müsbət vermir.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

_SRC: Final[Path] = Path(__file__).resolve().parents[2] / "src"


def _names_bound_at_runtime(tree: ast.Module) -> set[str]:
    """Modulun icra zamanı FAKTİKİ tanıdığı adlar (idxal + təyin edilmiş)."""
    bound: set[str] = set()

    def visit(node: ast.AST, *, inside_type_checking: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.If) and "TYPE_CHECKING" in ast.unparse(child.test):
                # `else:` budağı icra olunur — oradakı idxal HƏQİQİDİR.
                for fallback in child.orelse:
                    visit(fallback, inside_type_checking=False)
                continue
            if isinstance(child, ast.Import | ast.ImportFrom) and not inside_type_checking:
                bound.update((alias.asname or alias.name).split(".")[0] for alias in child.names)
            elif isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                bound.add(child.name)
            elif isinstance(child, ast.Assign):
                bound.update(t.id for t in child.targets if isinstance(t, ast.Name))
            visit(child, inside_type_checking=inside_type_checking)

    visit(tree, inside_type_checking=False)
    return bound


def _names_imported_only_for_typing(tree: ast.Module) -> set[str]:
    """`if TYPE_CHECKING:` blokunda idxal olunan adlar."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
            for inner in node.body:
                for candidate in ast.walk(inner):
                    if isinstance(candidate, ast.Import | ast.ImportFrom):
                        names.update(
                            (alias.asname or alias.name).split(".")[0] for alias in candidate.names
                        )
    return names


def _called_names(tree: ast.Module) -> set[str]:
    """`Foo(...)` şəklində çağırılan sadə adlar."""
    return {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def test_no_module_calls_a_name_it_only_imported_for_type_checking() -> None:
    """`src/` boyu heç bir modul yalnız-tip adını icra zamanı çağırmır."""
    offenders: dict[str, list[str]] = {}
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        typing_only = _names_imported_only_for_typing(tree) - _names_bound_at_runtime(tree)
        called = sorted(typing_only & _called_names(tree))
        if called:
            offenders[str(path.relative_to(_SRC.parent))] = called

    assert not offenders, (
        "Bu adlar YALNIZ `TYPE_CHECKING` altında idxal olunub, lakin icra "
        "zamanı çağırılır — `mypy` yaşıl qalacaq, tətbiq isə həmin sətrə "
        f"çatanda `NameError` verəcək: {offenders}"
    )
