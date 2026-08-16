"""Təqdimat qatındakı SQL-in SXEMƏ uyğunluğu — statik qapı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU QAPI VAR — `ft.name` HADİSƏSİ
──────────────────────────────────────────────────────────────────────────────
`controllers/screen_data.py`-dakı «Cərimələr» sorğusu `ft.name` sütununu
oxuyurdu; `fine_types` cədvəlində isə belə sütun YOXDUR — yalnız `name_az`
(`schema.sql` §fine_types). Sorğu `UndefinedColumn` ilə düşürdü, `populate()`
onu `except Exception` ilə tuturdu, `error.log`-a yazırdı və ekran BOŞ qalırdı.
İstifadəçi üçün "cərimə yoxdur" ilə "sorğu düşdü" eyni göründüyü üçün heç kim
şikayət etmədi və qüsur AYLARLA yaşadı.

Test dəsti bunu tutmurdu, çünki heç bir test bazaya bağlanmır: sorğular yalnız
mətn kimi mövcuddur və Python onların düzgünlüyünü YOXLAMIR. Bu qapı həmin
boşluğu bağlayır — sorğu MƏTNİNDƏKİ `alias.sütun` istinadları `schema.sql` +
`migrations/*.sql` faylından qurulan FAKTİKİ sxemlə tutuşdurulur. Baza tələb
olunmur.

──────────────────────────────────────────────────────────────────────────────
NİYƏ HƏR SORĞU YOXLANMIR — YALANÇI-POZİTİV QAPINI ÖLDÜRÜR
──────────────────────────────────────────────────────────────────────────────
Bu, SQL parseri DEYİL və olmağa çalışmır. Əmin olmadığı konstruksiyanı
ATLAYIR və atladığını SAYIR (`test_gate_reports_its_own_coverage`), çünki
yalançı-pozitiv verən qapı bir həftə sonra söndürülür — söndürülmüş qapı isə
heç bir qapıdan pisdir. Atlanan hallar:

* CTE-lər (`WITH x AS (...)`) və alt-sorğular ÖZ ad məkanını qurur;
* `FROM (SELECT ...) t` və `LATERAL` — törəmə cədvəlin sütunları burada
  hesablanmır;
* funksiya nəticələri (`generate_series`, `unnest`);
* `EXCLUDED.` (UPSERT) və `NEW.`/`OLD.` (trigger) cədvəl DEYİL;
* `SELECT ... FROM t` daxilində KVALİFİKASİYASIZ sütun adları — bir neçə
  cədvəl olduqda hansına aid olduğu mətnə görə bilinmir;
* sütun siyahısı statik oxunmayan görünüşlər (`CREATE VIEW ... WITH ...`).

Yəni qapı "hər şeyi yoxladım" iddiasında deyil; o, MƏHZ `ft.name` sinfini —
mövcud cədvəlin OLMAYAN sütununa kvalifikasiyalı istinadı — tutur.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from difflib import get_close_matches
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.unit

ROOT: Final = Path(__file__).resolve().parents[2]
CONTROLLERS_DIR: Final = ROOT / "src/presentation/controllers"
SCHEMA_SQL: Final = ROOT / "database/schema.sql"
MIGRATIONS_DIR: Final = ROOT / "database/migrations"

#: Cədvəl/görünüş adı → sütun dəsti. `None` = məzmun statik oxuna bilmədi;
#: belə relyasiyaya edilən istinad YOXLANMIR, ATLANIR.
Schema = dict[str, frozenset[str] | None]

# --------------------------------------------------------------------------- #
# 1. Sxem: `CREATE TABLE`, `ALTER TABLE`, `CREATE VIEW`
# --------------------------------------------------------------------------- #

#: Sxem ifadələri — HAMISI BİR regex-də, çünki SIRA ƏHƏMİYYƏTLİDİR: `schema.sql`
#: və miqrasiyalar ardıcıl tətbiq olunur (CLAUDE.md bölmə 7), yəni sonrakı
#: `ALTER TABLE ... DROP COLUMN` əvvəlki sütunu SİLİR. Ayrı-ayrı keçidlər bu
#: ardıcıllığı itirər və silinmiş sütunu "mövcuddur" kimi göstərərdi.
_DDL: Final = re.compile(
    r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<table>[a-z_][a-z0-9_]*)\s*\("
    r"|\bALTER\s+TABLE\s+(?:ONLY\s+)?(?:IF\s+EXISTS\s+)?(?P<alter>[a-z_][a-z0-9_]*)"
    r"(?P<alter_body>[^;]*);"
    r"|\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:MATERIALIZED\s+)?VIEW\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?(?P<view>[a-z_][a-z0-9_]*)\s+AS\b"
    r"|\bDROP\s+(?:TABLE|VIEW|MATERIALIZED\s+VIEW)\s+(?:IF\s+EXISTS\s+)?"
    r"(?P<dropped>[a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)

_ADD_COLUMN: Final = re.compile(
    r"\bADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)", re.IGNORECASE
)
_DROP_COLUMN: Final = re.compile(
    r"\bDROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?([a-z_][a-z0-9_]*)", re.IGNORECASE
)
_RENAME_COLUMN: Final = re.compile(
    r"\bRENAME\s+COLUMN\s+([a-z_][a-z0-9_]*)\s+TO\s+([a-z_][a-z0-9_]*)", re.IGNORECASE
)

#: `CREATE TABLE` gövdəsində SÜTUN OLMAYAN bəndlər.
_TABLE_CONSTRAINT_WORDS: Final = frozenset(
    {"primary", "unique", "check", "constraint", "foreign", "exclude", "like"}
)


def _strip_sql_comments(text: str) -> str:
    """`--` və `/* */` şərhlərini silir.

    Şərh silmək MƏCBURİDİR, çünki hər miqrasiya sonunda ŞƏRHLƏ yazılmış DOWN
    bloku saxlayır (CLAUDE.md bölmə 7) və orada `DROP COLUMN` sətirləri var —
    onları tətbiq etsək sxem GERİ qaytarılmış kimi görünərdi.
    """
    without_block = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", " ", without_block)


def _balanced_body(text: str, open_index: int) -> str:
    """`(`-dan başlayan mötərizənin İÇİ — uyğun bağlanışa qədər."""
    depth = 0
    for index in range(open_index, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return text[open_index + 1 : index]
    return ""


def _split_top_level(text: str) -> list[str]:
    """Yalnız 0-cı dərinlikdəki vergüllərə görə bölür."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def _table_columns(body: str) -> set[str]:
    columns: set[str] = set()
    for item in _split_top_level(body):
        words = item.split()
        if not words:
            continue
        first = words[0].strip('"').lower()
        if first in _TABLE_CONSTRAINT_WORDS:
            continue
        if re.fullmatch(r"[a-z_][a-z0-9_]*", first):
            columns.add(first)
    return columns


def _statement_tail(text: str, start: int) -> str:
    """`start`-dan 0-cı dərinlikdəki `;`-ə qədər olan hissə."""
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == ";" and depth == 0:
            return text[start:index]
    return text[start:]


def _view_columns(body: str) -> frozenset[str] | None:
    """Görünüşün sütun adları — statik oxunmursa `None` (istinad ATLANIR)."""
    text = re.sub(r"\s+", " ", body).strip()
    lowered = text.lower()
    if not lowered.startswith("select"):
        # `CREATE VIEW ... AS WITH ...` və sair — parse edilmir.
        return None
    text = text[len("select") :].strip()
    text = re.sub(r"^distinct\s+on\s*\([^)]*\)", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"^(distinct|all)\b", "", text, flags=re.IGNORECASE).strip()

    select_list = _before_top_level_keyword(text, "from")
    if select_list is None:
        return None

    columns: set[str] = set()
    for item in _split_top_level(select_list):
        # `*` və `s.*` sütun adlarını gizlədir. `count(*)` İSƏ gizlətmir —
        # ona görə yoxlama BƏNDİN ÖZÜNƏ baxır, mətnin içindəki ulduza yox.
        if re.fullmatch(r"\*|[a-z_][a-z0-9_]*\.\*", item, re.IGNORECASE):
            return None
        alias = re.search(r"\bas\s+\"?([a-z_][a-z0-9_]*)\"?\s*$", item, re.IGNORECASE)
        if alias is not None:
            columns.add(alias.group(1).lower())
            continue
        plain = re.fullmatch(r"[a-z_][a-z0-9_]*(?:\.([a-z_][a-z0-9_]*))?", item, re.IGNORECASE)
        if plain is None:
            # Adsız ifadə (`count(*)`) — sütunun adı statik bilinmir.
            return None
        columns.add((plain.group(1) or item).lower())
    return frozenset(columns)


def _before_top_level_keyword(text: str, keyword: str) -> str | None:
    """`keyword` sözünə qədər olan hissə — YALNIZ 0-cı dərinlikdə axtarılır."""
    depth = 0
    pattern = re.compile(rf"\b{keyword}\b", re.IGNORECASE)
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 0 and pattern.match(text, index):
            return text[:index]
    return None


def load_schema() -> Schema:
    """`schema.sql` + miqrasiyalar → cədvəl/görünüş → sütun dəsti.

    Miqrasiyalar NÖMRƏ SIRASI ilə tətbiq olunur — `psql` də faylları ada görə
    icra edir və sxem sonuncu vəziyyəti əks etdirməlidir.
    """
    schema: Schema = {}
    sources = [SCHEMA_SQL, *sorted(MIGRATIONS_DIR.glob("*.sql"))]
    for path in sources:
        text = _strip_sql_comments(path.read_text(encoding="utf-8"))
        for match in _DDL.finditer(text):
            if match.group("table"):
                name = match.group("table").lower()
                body = _balanced_body(text, match.end() - 1)
                existing = schema.get(name) or frozenset()
                schema[name] = frozenset(existing | _table_columns(body))
            elif match.group("alter"):
                _apply_alter(schema, match.group("alter").lower(), match.group("alter_body"))
            elif match.group("view"):
                name = match.group("view").lower()
                schema[name] = _view_columns(_statement_tail(text, match.end()))
            elif match.group("dropped"):
                schema.pop(match.group("dropped").lower(), None)
    return schema


def _apply_alter(schema: Schema, table: str, body: str) -> None:
    columns = schema.get(table)
    if columns is None:
        # Naməlum cədvələ `ALTER` — sxemdə yoxdursa (məs. lisenziya bazası
        # üçün ayrıca fayl) sütun dəsti də qurulmur.
        return
    updated = set(columns)
    updated |= {match.group(1).lower() for match in _ADD_COLUMN.finditer(body)}
    updated -= {match.group(1).lower() for match in _DROP_COLUMN.finditer(body)}
    for match in _RENAME_COLUMN.finditer(body):
        updated.discard(match.group(1).lower())
        updated.add(match.group(2).lower())
    schema[table] = frozenset(updated)


# --------------------------------------------------------------------------- #
# 2. Sorğu təhlili
# --------------------------------------------------------------------------- #

#: Cədvəl DEYİL: UPSERT-in `EXCLUDED`-i, trigger-in `NEW`/`OLD`-u, sxem
#: prefiksləri.
_NON_TABLE_PREFIXES: Final = frozenset(
    {"excluded", "new", "old", "public", "pg_catalog", "information_schema"}
)

#: Bu konstruksiyalar görünəndə BÜTÜN sorğu atlanır — törəmə cədvəlin və
#: funksiya nəticəsinin sütunları mətnə görə bilinmir.
_UNPARSEABLE_MARKERS: Final = ("lateral", "generate_series", "unnest(", " from (", " join (")

#: `FROM`/`JOIN`-dən sonra gələn və ALIAS OLA BİLMƏYƏN sözlər.
_NOT_AN_ALIAS: Final = frozenset(
    {
        "where","group","order","limit","offset","having","on","using","join","left","right",
        "inner","outer","full","cross","natural","union","except","intersect","returning",
        "set","values","window","fetch","for","lateral","as","and","or","not","tablesample",
    }
)  # fmt: skip

_RELATION_REF: Final = re.compile(
    r"\b(?:from|join|into|update)\s+(?!\()([a-z_][a-z0-9_]*)(?![.(])"
    r"(?:\s+(?:as\s+)?([a-z_][a-z0-9_]*))?"
)
_QUALIFIED_REF: Final = re.compile(r"\b([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)\b")
_CTE_NAME: Final = re.compile(r"\b([a-z_][a-z0-9_]*)\s+as\s+(?:(?:not\s+)?materialized\s+)?\(")
_IS_SQL: Final = re.compile(r"^\s*(with|select|insert|update|delete)\b", re.IGNORECASE)


@dataclass
class QueryReport:
    """Bir sorğunun nəticəsi — nə yoxlandı, nə atlandı, nə pozuldu."""

    checked: int = 0
    skipped: int = 0
    problems: list[str] = field(default_factory=list)
    skip_reason: str | None = None


def _normalise(sql: str) -> str:
    """Şərhlər və sətir literalları çıxarılır, boşluq yığılır, kiçildilir.

    Sətir literalları MƏCBURİ çıxarılır: `to_char(x, 'DD.MM.YYYY')` içindəki
    nöqtə `alias.sütun` naxışına oxşayır və qapı olmayan bir sütundan şikayət
    edərdi — yəni ilk yalançı-pozitiv məhz burada doğulardı.
    """
    text = re.sub(r"--[^\n]*", " ", sql)
    text = re.sub(r"'(?:[^']|'')*'", " '' ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def analyse_query(sql: str, schema: Schema) -> QueryReport:
    """Bir SQL mətnindəki `alias.sütun` istinadlarını sxemlə tutuşdurur."""
    report = QueryReport()
    text = _normalise(sql)
    padded = f" {text} "

    for marker in _UNPARSEABLE_MARKERS:
        if marker in padded:
            report.skip_reason = f"parse edilmir: «{marker.strip()}»"
            return report

    relations = {match.group(1) for match in _RELATION_REF.finditer(text)}
    if not relations:
        report.skip_reason = "cədvələ istinad yoxdur"
        return report

    cte_names = {match.group(1) for match in _CTE_NAME.finditer(text)}
    aliases = _alias_map(text, cte_names)

    for match in _QUALIFIED_REF.finditer(text):
        prefix, column = match.group(1), match.group(2)
        if prefix in _NON_TABLE_PREFIXES or prefix in cte_names:
            report.skipped += 1
            continue
        if prefix not in aliases:
            # Naməlum prefiks: törəmə cədvəl, funksiya nəticəsi və ya bizim
            # tanımadığımız konstruksiya. SUSMAQ seçilir — burada "xəta" demək
            # qapını yalançı-pozitivlə doldurardı.
            report.skipped += 1
            continue
        table = aliases[prefix]
        columns = schema.get(table)
        if table not in schema:
            report.problems.append(
                f"`{table}` adlı cədvəl/görünüş sxemdə YOXDUR (istinad: {prefix}.{column})"
            )
            continue
        if columns is None:
            report.skipped += 1
            continue
        report.checked += 1
        if column not in columns:
            report.problems.append(_missing_column_message(table, prefix, column, columns))
    return report


def _alias_map(text: str, cte_names: set[str]) -> dict[str, str]:
    """`alias → cədvəl` xəritəsi (`fine_types ft` → `ft` = `fine_types`).

    CTE adına bağlanan alias xəritəyə DÜŞMÜR — onun sütunları bu qapının
    bilmədiyi bir `SELECT`-dən gəlir və hər istinadı atlanmalıdır.
    """
    aliases: dict[str, str] = {}
    for match in _RELATION_REF.finditer(text):
        relation, alias = match.group(1), match.group(2)
        if relation in cte_names:
            continue
        aliases[relation] = relation
        if alias and alias not in _NOT_AN_ALIAS:
            aliases[alias] = relation
    return aliases


def _missing_column_message(table: str, prefix: str, column: str, columns: frozenset[str]) -> str:
    """Mesaj YAXIN adı təklif edir — `name` → `name_az` (əsl hadisə)."""
    close = get_close_matches(column, sorted(columns), n=1, cutoff=0.5)
    hint = f" — bəlkə `{close[0]}`?" if close else ""
    return (
        f"`{table}` cədvəlində `{column}` sütunu YOXDUR (istinad: {prefix}.{column}){hint} "
        f"| mövcud sütunlar: {', '.join(sorted(columns))}"
    )


# --------------------------------------------------------------------------- #
# 3. Python fayllarından SQL çıxarmaq
# --------------------------------------------------------------------------- #


@dataclass
class FileScan:
    """Bir faylın nəticəsi."""

    queries: int = 0
    checked_refs: int = 0
    skipped_refs: int = 0
    skipped_queries: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def scan_python_file(path: Path, schema: Schema) -> FileScan:
    """Fayldakı SQL sətir literallarını tapır və hər birini təhlil edir."""
    scan = FileScan()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            # DİNAMİK SQL (`f"... {clauses}"`): fraqment natamamdır, sxemə görə
            # yoxlamaq mümkün deyil. Sayılır ki, "hamısını yoxladım" illüziyası
            # yaranmasın (bax modul başlığı).
            joined = "".join(part.value for part in node.values if isinstance(part, ast.Constant))
            if _IS_SQL.match(joined):
                scan.queries += 1
                scan.skipped_queries.append(f"{path.name}:{node.lineno} — dinamik (f-string)")
            continue
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if not _IS_SQL.match(node.value):
            continue
        scan.queries += 1
        report = analyse_query(node.value, schema)
        if report.skip_reason is not None:
            scan.skipped_queries.append(f"{path.name}:{node.lineno} — {report.skip_reason}")
        scan.checked_refs += report.checked
        scan.skipped_refs += report.skipped
        scan.problems.extend(
            f"{path.name}:{node.lineno} → {problem}" for problem in report.problems
        )
    return scan


def scan_directory(directory: Path, schema: Schema) -> FileScan:
    total = FileScan()
    for path in sorted(directory.glob("*.py")):
        scan = scan_python_file(path, schema)
        total.queries += scan.queries
        total.checked_refs += scan.checked_refs
        total.skipped_refs += scan.skipped_refs
        total.skipped_queries.extend(scan.skipped_queries)
        total.problems.extend(scan.problems)
    return total


# --------------------------------------------------------------------------- #
# Testlər
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def schema() -> Schema:
    return load_schema()


def test_schema_loader_reads_the_real_definitions(schema: Schema) -> None:
    """Yükləyicinin ÖZÜ yoxlanılır — boş sxem qapını YALANDAN yaşıl edərdi.

    Heç bir cədvəl oxumayan yükləyici bütün istinadları "atlanıb" sayardı və
    qapı əbədi yaşıl qalardı. Ona görə burada MƏHZ `ft.name` hadisəsinin
    faktları təsbit olunur: `fine_types`-də `name_az` VAR, `name` YOXDUR.
    """
    assert len(schema) > 60, "sxem yükləyicisi cədvəlləri tapmadı"

    fine_types = schema["fine_types"]
    assert fine_types is not None
    assert "name_az" in fine_types
    assert "name" not in fine_types, "əsl hadisənin şərti dəyişib — qapı mənasız olardı"

    # Miqrasiya ilə ƏLAVƏ olunan sütun (schema.sql-də YOXDUR, bax bölmə 7).
    fines = schema["fines"]
    assert fines is not None
    assert "evidence_drive_file_id" in fines, "miqrasiyalar tətbiq olunmayıb"

    # Miqrasiya ilə SİLİNƏN sütun geri gəlməməlidir (001: TOTP çıxarılıb).
    employees = schema["employees"]
    assert employees is not None
    assert "totp_enabled" not in employees, "DROP COLUMN nəzərə alınmayıb"
    assert "username" in employees

    # Görünüşün sütunları `CREATE VIEW`-un `SELECT` siyahısından gəlir.
    health_view = schema["v_erp_server_health"]
    assert health_view is not None
    assert {"server_name", "health", "sync_delay_seconds"} <= health_view


def test_presentation_sql_matches_the_schema(schema: Schema) -> None:
    """QAPI: kontrollerlərdəki hər `alias.sütun` sxemdə mövcud olmalıdır."""
    scan = scan_directory(CONTROLLERS_DIR, schema)
    assert not scan.problems, "Sxemə uyğun olmayan SQL istinadı:\n" + "\n".join(scan.problems)


def test_gate_catches_a_broken_column_reference(schema: Schema) -> None:
    """SÜBUT: qapı süni `ft.name` sınığını TUTUR və yaxın adı təklif edir.

    Bu test olmadan yaşıl qapı heç nə ifadə etməzdi — o, "yoxlanacaq bir şey
    tapmadım" halında da yaşıl olardı.
    """
    broken = """
        SELECT f.amount, COALESCE(ft.name, '—') AS type_name
          FROM fines f
          LEFT JOIN fine_types ft ON ft.id = f.fine_type_id
         WHERE f.tenant_id = %s
    """
    report = analyse_query(broken, schema)

    assert report.skip_reason is None, "sorğu atlanmamalıdır — yoxlanmalıdır"
    assert len(report.problems) == 1
    assert "`fine_types` cədvəlində `name` sütunu YOXDUR" in report.problems[0]
    assert "bəlkə `name_az`?" in report.problems[0], "yaxın ad təklif edilmir"

    # Düzəldilmiş forma TƏMİZDİR — qapı düzgün sorğudan şikayət etmir.
    fixed = broken.replace("ft.name,", "ft.name_az,")
    assert analyse_query(fixed, schema).problems == []


def test_gate_catches_a_missing_relation(schema: Schema) -> None:
    """Olmayan CƏDVƏLƏ istinad da tutulur (səhv yazılmış cədvəl adı)."""
    report = analyse_query("SELECT ft.name_az FROM fine_typez ft WHERE ft.id = %s", schema)
    assert any("sxemdə YOXDUR" in problem for problem in report.problems)


@pytest.mark.parametrize(
    ("sql", "expectation"),
    [
        # CTE öz ad məkanını qurur — `t.total` yoxlanmır.
        ("WITH totals AS (SELECT 1 AS total) SELECT t.total FROM totals t", "təmiz"),
        # UPSERT-in `EXCLUDED`-i cədvəl deyil.
        (
            "INSERT INTO stores (id, name) VALUES (%s, %s) "
            "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
            "təmiz",
        ),
        # Törəmə cədvəl (alt-sorğu) — bütün sorğu atlanır.
        ("SELECT x.total FROM (SELECT count(*) AS total FROM fines) x", "atlanır"),
        # Funksiya nəticəsi — atlanır.
        ("SELECT g.day FROM generate_series(1, 5) AS g(day)", "atlanır"),
        # Sətir literalındakı nöqtə sütun istinadı deyil.
        ("SELECT to_char(f.fine_date, 'DD.MM.YYYY') FROM fines f", "təmiz"),
        # `EXTRACT(... FROM f.sütun)` cədvəl istinadı deyil.
        ("SELECT EXTRACT(YEAR FROM f.fine_date) FROM fines f", "təmiz"),
    ],
)
def test_gate_does_not_produce_false_positives(sql: str, expectation: str, schema: Schema) -> None:
    """Realizm: bu konstruksiyalar qapını YALANÇI-POZİTİV etməməlidir."""
    report = analyse_query(sql, schema)
    assert report.problems == [], f"yalançı-pozitiv: {report.problems}"
    if expectation == "atlanır":
        assert report.skip_reason is not None


def test_gate_reports_its_own_coverage(schema: Schema) -> None:
    """Qapı NEÇƏ sorğunu yoxladığını və neçəsini atladığını AÇIQ deyir.

    «Hamısını yoxladım» illüziyası qapının özündən təhlükəlidir: sonrakı
    müəllif ona güvənib əl ilə yoxlamanı buraxar. Ona görə rəqəmlər həm
    çap olunur (`pytest -rP` və ya `-s` ilə görünür), həm də minimum hədd kimi
    TƏSBİT edilir — parser sınıb heç nə yoxlamamağa başlasa, bu test qırılır.
    Çap olunan mətn TUTULMUR (`capsys` çağırılmır), əks halda öz hesabatımızı
    özümüz udardıq.
    """
    scan = scan_directory(CONTROLLERS_DIR, schema)
    summary = (
        f"SQL qapısı: {scan.queries} sorğu tapıldı, "
        f"{scan.queries - len(scan.skipped_queries)}-i təhlil edildi, "
        f"{len(scan.skipped_queries)}-i atlandı; "
        f"{scan.checked_refs} sütun istinadı yoxlandı, {scan.skipped_refs} istinad atlandı."
    )
    print(summary)
    for skipped in scan.skipped_queries:
        print(f"  atlandı → {skipped}")

    assert scan.queries >= 40, summary
    assert scan.checked_refs >= 100, summary
    # Atlananların payı yarıdan az olmalıdır — əks halda qapı "yoxlayıram"
    # deyib faktiki olaraq susardı.
    assert len(scan.skipped_queries) * 2 < scan.queries, summary
