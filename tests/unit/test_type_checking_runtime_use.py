"""`TYPE_CHECKING` adının İCRA ZAMANI işlədilməsi — reqressiya qapısı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU QAPI VAR — İSTEHSALATDA ÇÖKMƏ YARATDI
──────────────────────────────────────────────────────────────────────────────
`app.py` `Employee`-ni YALNIZ `if TYPE_CHECKING:` altında idxal edir, lakin
`_authenticate()` içində `isinstance(employee, Employee)` yazırdı. İcra zamanı
belə bir ad YOXDUR:

    File "src\\presentation\\app.py", line 878, in _authenticate
    NameError: name 'Employee' is not defined

Nəticə istifadəçi üçün belə görünürdü: giriş məlumatları DÜZGÜNDÜR, jurnalda
`LOGIN_SUCCESS` var — sonra ekran «Yoxlanılır…» deyib YENİDƏN giriş ekranına
qayıdır. Yəni sistem işləyir, istifadəçi isə heç vaxt daxil ola bilmir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ NƏ MYPY, NƏ DƏ TESTLƏR TUTDU
──────────────────────────────────────────────────────────────────────────────
* **mypy görmür**: onun üçün idxal MÖVCUDDUR — o, məhz `TYPE_CHECKING`
  blokunu oxuyur. Tip yoxlaması baxımından kod tam düzgündür.
* **`from __future__ import annotations` yanıldır**: bütün annotasiyalar sətir
  kimi qalır, yəni `def f(x: Employee)` heç vaxt problem yaratmır. Təhlükə
  YALNIZ HƏQİQİ icra istifadəsindədir (`isinstance`, `issubclass`).
* **örtük aldadıcı idi**: həmin sətir `# pragma: no cover - tip qoruyucusu`
  ilə işarələnmişdi — «icra olunmaz» fərziyyəsi ilə. Halbuki o, HƏR girişdə
  icra olunurdu.

Ona görə qayda maşınla yoxlanılır: `isinstance`/`issubclass` arqumenti kimi
işlədilən ad ya modul səviyyəsində, ya da HƏMİN FUNKSİYANIN İÇİNDƏ idxal
olunmalıdır (`# noqa: PLC0415` naxışı — bax `theme/manager.py::detect`).
"""

from __future__ import annotations

import ast
import pathlib
from typing import Final

import pytest

pytestmark = pytest.mark.unit

_SRC: Final = pathlib.Path(__file__).resolve().parents[2] / "src"

#: İkinci arqumenti İCRA ZAMANI tələb edən çağırışlar.
_RUNTIME_CALLS: Final[frozenset[str]] = frozenset({"isinstance", "issubclass"})


def _type_checking_names(tree: ast.Module) -> set[str]:
    """`if TYPE_CHECKING:` blokunda idxal olunan adlar."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        guarded = (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
            isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
        )
        if not guarded:
            continue
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.ImportFrom | ast.Import):
                for alias in stmt.names:
                    names.add(alias.asname or alias.name.split(".")[-1])
    return names


def _module_level_names(tree: ast.Module) -> set[str]:
    """`TYPE_CHECKING`-dən KƏNARDA, modul səviyyəsində idxal olunan adlar."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom | ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[-1])
    return names


def _locally_imported(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Funksiyanın İÇİNDƏ idxal olunan adlar — bunlar icra zamanı MÖVCUDDUR."""
    names: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.ImportFrom | ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[-1])
    return names


def _offenders(path: pathlib.Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    if "TYPE_CHECKING" not in source:
        return []
    tree = ast.parse(source)
    guarded = _type_checking_names(tree) - _module_level_names(tree)
    if not guarded:
        return []

    found: list[str] = []
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        safe = _locally_imported(function)
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Name) or func.id not in _RUNTIME_CALLS:
                continue
            for argument in node.args[1:]:
                for sub in ast.walk(argument):
                    if isinstance(sub, ast.Name) and sub.id in guarded and sub.id not in safe:
                        found.append(
                            f"{path.relative_to(_SRC.parent)}:{node.lineno} "
                            f"{func.id}(..., {sub.id}) — `{sub.id}` yalnız TYPE_CHECKING-dədir"
                        )
    return found


def test_no_type_checking_name_is_used_at_runtime() -> None:
    """`isinstance`/`issubclass` arqumenti icra zamanı MÖVCUD olmalıdır.

    Düzəliş iki formadan biridir: adı modul səviyyəsində idxal et, VƏ YA
    funksiyanın içində lokal idxal yaz (`# noqa: PLC0415`) — layihədə ikinci
    naxış üstünlük təşkil edir, çünki açılış idxallarını yüngül saxlayır.
    """
    offenders: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        offenders.extend(_offenders(path))

    assert offenders == [], (
        "Bu adlar icra zamanı MÖVCUD DEYİL və `NameError` verəcək "
        "(mypy bunu GÖRMÜR — onun üçün idxal var):\n  " + "\n  ".join(offenders)
    )
