"""`Session` ↔ use case ↔ repo bağlantısının reqressiya qapısı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TEST VAR
──────────────────────────────────────────────────────────────────────────────
On use case ARTIQ yazılmışdı (kataloqlar, backup, plugin, dashboard düzülüşü,
baza keçidi, şübhəli satış növbəsi, profil, ERP sihirbazı), lakin
`composition.py`-dakı `Session`-a qoşulmamışdı — yəni onları çağıracaq BİR
YOL DA yox idi. Belə boşluq heç bir tip xətası vermir və heç bir test qırmır:
o, yalnız istifadəçi boş ekran görəndə üzə çıxır.

Qapı iki tərəflidir:

1. `Session` sahələri və `_build_session`-dakı açar-arqumentlər EYNİ dəst
   olmalıdır (sahə əlavə edib qurmağı unutmaq `TypeError` verər, lakin yalnız
   REAL baza ilə — bu testdə isə dərhal).
2. Use case-in tələb etdiyi hər repo `PostgresUnitOfWork._build_repositories()`
   -də qeydiyyatdan keçməlidir. `uow.repository("plugins")` yoxdursa nəticə
   işlək zamanı `KeyError`-dur.

Testlər BAZA TƏLƏB ETMİR: `composition.py` və `connection.py` `ast` ilə
oxunur.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

from src.presentation.composition import Session

pytestmark = pytest.mark.unit

_SRC: Final = Path(__file__).resolve().parents[2] / "src"
COMPOSITION: Final = _SRC / "presentation/composition.py"
CONNECTION: Final = _SRC / "infrastructure/persistence/connection.py"

#: FAZA 5/6-da bağlanan use case-lər — `Session` sahə adları.
#:
#: Siyahı AÇIQ yazılır ki, biri sükutla SİLİNSƏ test qırılsın: sahəni silmək
#: ekranı yenidən boş qoyardı və bu, tam olaraq bağladığımız qüsurdur.
NEWLY_WIRED: Final[frozenset[str]] = frozenset(
    {
        "work_modes",
        "fine_types",
        "leave_types",
        "backups",
        "plugins",
        "dashboard_layout",
        "db_switch",
        "sales_review",
        "employee_profile",
        "erp_connections",
    }
)

#: `_build_repositories()`-də olmalı olan yeni açarlar.
NEW_REPOSITORY_KEYS: Final[frozenset[str]] = frozenset(
    {"plugins", "backup_records", "read_only", "migration_events"}
)


def _build_session_keywords() -> set[str]:
    """`_build_session` daxilindəki `return Session(...)` açar-arqumentləri."""
    tree = ast.parse(COMPOSITION.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_build_session":
            continue
        for call in ast.walk(node):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "Session"
            ):
                return {kw.arg for kw in call.keywords if kw.arg is not None}
    pytest.fail("`_build_session` içində `Session(...)` çağırışı tapılmadı")


def _repository_keys() -> set[str]:
    """`_build_repositories()`-dəki sözlük açarları."""
    tree = ast.parse(CONNECTION.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_build_repositories":
            continue
        return {
            key.value
            for mapping in ast.walk(node)
            if isinstance(mapping, ast.Dict)
            for key in mapping.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
    pytest.fail("`_build_repositories` tapılmadı")


def test_every_session_field_is_actually_constructed() -> None:
    """Sahə əlavə edib qurmağı unutmaq BURADA tutulur, istehsalatda yox."""
    fields = set(Session.__dataclass_fields__)
    keywords = _build_session_keywords()

    missing = fields - keywords
    assert not missing, f"`Session` sahələri qurulmur: {sorted(missing)}"


def test_the_newly_wired_use_cases_are_present() -> None:
    """Faza 5/6 bağlantısı geri alınmayıb."""
    fields = set(Session.__dataclass_fields__)
    assert fields >= NEWLY_WIRED, f"Bağlantı itib: {sorted(NEWLY_WIRED - fields)}"


def test_new_repositories_are_registered_in_the_unit_of_work() -> None:
    """`uow.repository("plugins")` işlək zamanı `KeyError` verməməlidir."""
    keys = _repository_keys()
    missing = NEW_REPOSITORY_KEYS - keys
    assert not missing, f"`_build_repositories()`-də yoxdur: {sorted(missing)}"


def test_repository_names_used_in_composition_all_exist() -> None:
    """`repo("...")` sətirlərinin HAMISI qeydiyyatdan keçmiş açar olmalıdır.

    Səhv yazılmış ad (`"backups"` ↔ `"backup_records"`) mypy-dan keçir və
    yalnız həmin ekran açılanda çökür — yəni ən gec anda.
    """
    tree = ast.parse(COMPOSITION.read_text(encoding="utf-8"))
    used = {
        call.args[0].value
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "repo"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    }
    unknown = used - _repository_keys()
    assert not unknown, f"`_build_repositories()`-də olmayan repo adları: {sorted(unknown)}"
