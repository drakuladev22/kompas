"""`kompas1.md` Faza 1 sxem genişlənməsinin (miqrasiya 037) struktur qapıları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TEST STATİK MƏTN ÜZƏRİNDƏ İŞLƏYİR
──────────────────────────────────────────────────────────────────────────────
Cədvəl, indeks, trigger və RLS siyasəti YALNIZ canlı PostgreSQL-də icra olunur;
vahid testlərdə isə sahtə repo-lar var. Sintaksisi CI-ın `db-schema` job-u
yoxlayır (sxem + miqrasiyalar İKİ dəfə tətbiq olunur). Burada verilən sual
başqadır: "qayda mənbədə HƏLƏ DƏ varmı?" — və cavab mətndən oxunur.
`test_phase1_schema_extension.py` (018–020) eyni naxışı işlədir; köməkçi
funksiyalar QƏSDƏN köçürülüb, idxal edilmir: test faylının başqa test faylından
asılı olması bir modulun adının dəyişməsini iki qapının birdən çökməsinə
çevirərdi.

NƏ QORUNUR
──────────────────────────────────────────────────────────────────────────────
1. QIRMIZI XƏTT — miqrasiya heç nə silmir/dəyişdirmir (`DROP TABLE`,
   `DROP COLUMN`, `ALTER COLUMN ... TYPE`, `TRUNCATE` yoxdur).
2. `work_modes` TƏKRAR YARADILMIR — o, `schema.sql` §11-dədir. Təkrar yazılsa
   `CREATE TABLE IF NOT EXISTS` sükutla heç nə etməz və iki fərqli "həqiqət"
   yaranardı; `daily_norm_hours` da əlavə edilmir (norma `migrations/019`
   naxışı ilə canlı hesablanır, `overtime_log`-da dondurulur).
3. ÇOX-KİRAYƏÇİLİK — hər yeni cədvəldə `tenant_id` + RLS + `tenant_isolation`.
4. SƏNƏDLƏŞMƏ — hər cədvəl və HƏR sütun `COMMENT` daşıyır.
5. TZ QAYDASI — bütün vaxt sütunları `TIMESTAMPTZ`.
6. İDEMPOTENTLİK — `IF NOT EXISTS` (CI hər miqrasiyanı iki dəfə tətbiq edir).
7. GENİŞLƏNƏ BİLƏN ŞABLON/KATEQORİYA — `field_reports.type` və `.category`
   sərt `CHECK` siyahısı DEYİL, kataloqa FK-dır (018 `exceptions.source` qərarı).
8. #28 ÜST-ÜSTƏ DÜŞMƏ QAPAĞI — `EXCLUDE USING gist` DB qatındadır.
9. AUDİT SƏTİRLƏRİ — `REVOKE DELETE` (və düzəlişlərdə `REVOKE UPDATE`) var.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR: Final = PROJECT_ROOT / "database" / "migrations"
SCHEMA_FILE: Final = PROJECT_ROOT / "database" / "schema.sql"

MIGRATION: Final = MIGRATIONS_DIR / "037_field_reports_and_hr_operations.sql"

#: Bu miqrasiyanın yaratdığı cədvəllər. `field_report_types` və
#: `field_report_categories` spesifikasiyada ayrıca sadalanmır: onlar `type` və
#: `category` üçün "sərt siyahı yerinə kataloq" tələbinin struktur cavabıdır
#: (əsaslandırma miqrasiya başlığındadır).
NEW_TABLES: Final = (
    "field_report_types",
    "field_report_categories",
    "field_reports",
    "field_report_checklist_items",
    "annual_leave_balances",
    "annual_leave_requests",
    "bulk_import_log",
    "store_templates",
    "executive_digest_config",
    "export_manual_corrections",
)

#: Kataloq xarakterli cədvəllər — fiziki `DELETE` yoxdur (`catalogs.py` qaydası).
SOFT_DELETE_TABLES: Final = (
    "field_report_types",
    "field_report_categories",
    "store_templates",
    "executive_digest_config",
)

#: Sətri sübut/audit olan cədvəllər — tətbiq rolu onları SİLƏ BİLMƏMƏLİDİR.
NO_DELETE_TABLES: Final = (*SOFT_DELETE_TABLES, *NEW_TABLES)

_LINE_COMMENT_RE: Final = re.compile(r"--[^\n]*")
_STRING_LITERAL_RE: Final = re.compile(r"'(?:[^']|'')*'", re.DOTALL)

_TABLE_LEVEL_KEYWORDS: Final = frozenset(
    {"CONSTRAINT", "UNIQUE", "PRIMARY", "FOREIGN", "CHECK", "EXCLUDE", "LIKE"}
)


def _executable_sql(path: Path) -> str:
    """`--` şərhlərini atır — DOWN bloku YALNIZ şərhdədir."""
    return _LINE_COMMENT_RE.sub("", path.read_text(encoding="utf-8"))


def _masked_string_literals(sql: str) -> str:
    """Sətir sabitlərinin İÇİNİ boşluqla əvəzləyir, UZUNLUĞU saxlayır."""
    return _STRING_LITERAL_RE.sub(lambda m: "'" + " " * (len(m.group(0)) - 2) + "'", sql)


def _concatenated_literals(sql: str) -> str:
    """Boşluqları yığır və QONŞU sətir sabitlərini birləşdirir.

    PostgreSQL sətir sonunda kəsilmiş literalları avtomatik birləşdirir
    (`'GRANT ... ON a, ' 'b TO %I'`); bunu nəzərə almasaq iki sətrə bölünmüş
    `GRANT`/`REVOKE` siyahısının sonuncu cədvəli testdən gizli qalar.
    """
    return re.sub(r"\s+", " ", sql).replace("' '", "")


def _table_body(path: Path, table: str) -> str:
    """`CREATE TABLE IF NOT EXISTS <table> ( ... )` gövdəsini qaytarır."""
    raw = _executable_sql(path)
    sql = _masked_string_literals(raw)
    anchor = re.search(rf"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+{table}\s*\(", sql, re.IGNORECASE)
    assert anchor is not None, f"`{table}` üçün idempotent CREATE ifadəsi tapılmadı"

    depth = 1
    start = anchor.end()
    for index in range(start, len(sql)):
        if sql[index] == "(":
            depth += 1
        elif sql[index] == ")":
            depth -= 1
            if depth == 0:
                return raw[start:index]
    pytest.fail(f"`{table}` tərifinin bağlayıcı mötərizəsi tapılmadı")


def _columns(path: Path, table: str) -> list[str]:
    """Cədvəlin sütun adları (cədvəl səviyyəli məhdudiyyətlər kənarda)."""
    body = _masked_string_literals(_table_body(path, table))
    fragments: list[str] = []
    depth = 0
    current = ""
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            fragments.append(current)
            current = ""
            continue
        current += char
    fragments.append(current)

    names: list[str] = []
    for fragment in fragments:
        words = fragment.split()
        if not words:
            continue
        if words[0].upper() in _TABLE_LEVEL_KEYWORDS:
            continue
        names.append(words[0])
    return names


def _normalized(path: Path) -> str:
    return re.sub(r"\s+", " ", _executable_sql(path))


# --------------------------------------------------------------------------- #
# Nömrələmə, mövcudluq, DOWN
# --------------------------------------------------------------------------- #


def test_the_migration_continues_the_existing_sequence() -> None:
    """037 boşluqsuz ardıcıllığı davam etdirir.

    `psql` faylları ADA görə sıralayır; buraxılmış nömrə tətbiq sırasını
    şübhəli edər və "hansı miqrasiya çatışmır?" sualını insan yaddaşına buraxardı.
    """
    numbers = sorted(int(path.name[:3]) for path in MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    assert numbers == list(range(1, max(numbers) + 1)), (
        "Miqrasiya nömrələrində boşluq və ya təkrar var."
    )
    assert 37 in numbers, "037 miqrasiyası tapılmadı"
    assert MIGRATION.exists(), f"Gözlənilən fayl yoxdur: {MIGRATION.name}"


def test_the_migration_documents_its_down_block() -> None:
    """DOWN bloku şərh içində sənədləşdirilir (CLAUDE.md §7)."""
    text = MIGRATION.read_text(encoding="utf-8")
    assert "-- DOWN" in text, "DOWN başlığı yoxdur"
    assert re.search(r"^--\s+DROP TABLE IF EXISTS", text, re.MULTILINE), (
        "DOWN bloku geri qaytarma addımlarını göstərmir"
    )


def test_the_migration_sets_the_search_path_before_any_object() -> None:
    """Preambula İLK obyekt istinadından əvvəl gəlir (`test_migration_preamble` naxışı)."""
    sql = _executable_sql(MIGRATION)
    preamble = re.search(r"SET\s+search_path\s+TO\s+kompasos\s*,\s*public\s*;", sql)
    assert preamble is not None, "`SET search_path` preambulası yoxdur"
    first_object = re.search(r"\bCREATE\s+(TABLE|EXTENSION|INDEX)\b", sql, re.IGNORECASE)
    assert first_object is not None
    assert preamble.start() < first_object.start()


# --------------------------------------------------------------------------- #
# QIRMIZI XƏTT
# --------------------------------------------------------------------------- #


def test_the_migration_never_destroys_or_reshapes_existing_objects() -> None:
    """İcra olunan SQL-də dağıdıcı DDL OLMAMALIDIR.

    `DROP TRIGGER` / `DROP POLICY` istisnadır: onlar idempotentlik naxışının
    hissəsidir (dərhal ardınca yenidən yaradılır) və məlumat silmir.
    """
    sql = _executable_sql(MIGRATION)
    forbidden = {
        "DROP TABLE": r"\bDROP\s+TABLE\b",
        "DROP COLUMN": r"\bDROP\s+COLUMN\b",
        "RENAME": r"\bRENAME\b",
        "ALTER COLUMN ... TYPE": r"\bALTER\s+COLUMN\b[^;]*\bTYPE\b",
        "DROP CONSTRAINT": r"\bDROP\s+CONSTRAINT\b",
        "TRUNCATE": r"\bTRUNCATE\b",
        "DELETE FROM": r"\bDELETE\s+FROM\b",
    }
    for label, pattern in forbidden.items():
        assert not re.search(pattern, sql, re.IGNORECASE), (
            f"İcra olunan SQL-də `{label}` var — Faza 1 YALNIZ əlavə etməlidir."
        )


def test_alter_table_only_targets_the_new_tables() -> None:
    """`ALTER TABLE` yalnız BU miqrasiyanın yaratdığı cədvələ toxunur."""
    sql = _executable_sql(MIGRATION)
    targets = {
        match.group(1) for match in re.finditer(r"ALTER\s+TABLE\s+([\w%]+)", sql, re.IGNORECASE)
    }
    assert targets <= {*NEW_TABLES, "%I"}, (
        f"MÖVCUD cədvələ `ALTER TABLE` tətbiq olunur: {sorted(targets - set(NEW_TABLES))}"
    )


def test_only_the_two_catalogs_receive_seed_rows() -> None:
    """`INSERT` yalnız yeni kataloqlara gedir — mövcud cədvələ sətir yazılmır."""
    sql = _executable_sql(MIGRATION)
    targets = {
        match.group(1).lower()
        for match in re.finditer(r"INSERT\s+INTO\s+(\w+)", sql, re.IGNORECASE)
    }
    assert targets == {"field_report_types", "field_report_categories"}, (
        f"Gözlənilməyən INSERT hədəfi: {sorted(targets)}"
    )
    assert sql.count("ON CONFLICT (code) DO NOTHING") == 2, (
        "Seed sətirləri təkrar icrada müştərinin redaktəsini üstündən yazardı."
    )


# --------------------------------------------------------------------------- #
# `work_modes` — MÜTLƏQ TOXUNULMAZ
# --------------------------------------------------------------------------- #


def test_work_modes_already_exists_in_the_base_schema() -> None:
    """Marker: cədvəl `schema.sql`-dədir — aşağıdakı qapının fərziyyəsi budur."""
    schema = _executable_sql(SCHEMA_FILE)
    assert re.search(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+work_modes\b", schema), (
        "`work_modes` bazis sxemdə tapılmadı — 037-nin onu buraxma səbəbi yoxa çıxır."
    )


def test_the_migration_does_not_recreate_work_modes() -> None:
    """Təkrar yaratma SÜKUTLA heç nə edərdi və iki mənbə yaradardı.

    `CREATE TABLE IF NOT EXISTS work_modes` mövcud cədvəl üzərində heç nə etmir;
    fərqli sütun dəsti gözləyən kod yalnız İSTEHSALATDA çökərdi.
    """
    sql = _executable_sql(MIGRATION)
    assert not re.search(r"CREATE\s+TABLE[^;]*\bwork_modes\b", sql, re.IGNORECASE), (
        "037 `work_modes` cədvəlini təkrar yaradır — `schema.sql` §11 ilə ikilik yaranar."
    )
    assert "daily_norm_hours" not in sql, (
        "`daily_norm_hours` sütunu əlavə edilib — norma `end_time − start_time`-dan "
        "çıxır və `overtime_log`-da dondurulur (migrations/019); sütun ikinci, "
        "sürüşən mənbə yaradardı."
    )


# --------------------------------------------------------------------------- #
# Çox-kirayəçilik, sənədləşmə, idempotentlik
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("table", NEW_TABLES)
def test_every_new_table_is_created_idempotently(table: str) -> None:
    sql = _executable_sql(MIGRATION)
    assert re.search(rf"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+{table}\b", sql, re.IGNORECASE), (
        f"`{table}` `IF NOT EXISTS` olmadan yaradılır — ikinci icra çökər."
    )


@pytest.mark.parametrize("table", NEW_TABLES)
def test_every_new_table_carries_a_tenant_id(table: str) -> None:
    assert "tenant_id" in _columns(MIGRATION, table), (
        f"`{table}` cədvəlində `tenant_id` yoxdur — izolyasiya mümkün deyil."
    )


@pytest.mark.parametrize("table", NEW_TABLES)
def test_every_new_table_enables_row_level_security(table: str) -> None:
    """RLS açıq şəkildə işə salınır (fail-closed, SEC-008)."""
    sql = _executable_sql(MIGRATION)
    direct = re.search(
        rf"ALTER\s+TABLE\s+{table}\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY", sql, re.IGNORECASE
    )
    in_loop = re.search(rf"'{table}'", sql) and "ENABLE ROW LEVEL SECURITY" in sql.upper()
    assert direct or in_loop, f"`{table}` üçün RLS işə salınmır."


@pytest.mark.parametrize("table", NEW_TABLES)
def test_every_new_table_gets_a_tenant_isolation_policy(table: str) -> None:
    sql = _executable_sql(MIGRATION)
    direct = re.search(rf"CREATE\s+POLICY\s+tenant_isolation\s+ON\s+{table}\b", sql, re.IGNORECASE)
    in_loop = re.search(rf"'{table}'", sql) and "CREATE POLICY tenant_isolation ON %I" in sql
    assert direct or in_loop, f"`{table}` üçün `tenant_isolation` siyasəti yoxdur."
    assert "current_tenant_id()" in sql


@pytest.mark.parametrize("table", ["field_report_types", "field_report_categories"])
def test_system_catalog_rows_are_visible_to_every_tenant(table: str) -> None:
    """Kataloqlar `positions` naxışını izləyir: `tenant_id IS NULL` = sistem sətri."""
    sql = _executable_sql(MIGRATION)
    policy = re.search(rf"CREATE\s+POLICY\s+tenant_isolation\s+ON\s+{table}(.*?);", sql, re.DOTALL)
    assert policy is not None
    body = re.sub(r"\s+", " ", policy.group(1))
    assert "tenant_id = current_tenant_id() OR tenant_id IS NULL" in body, (
        "Sistem sətirləri heç bir kirayəçiyə görünməzdi."
    )
    assert "WITH CHECK (tenant_id = current_tenant_id())" in body, (
        "Kirayəçi öz sətrini SİSTEM sətri kimi yaza bilərdi."
    )


@pytest.mark.parametrize("table", NEW_TABLES)
def test_every_new_table_is_documented(table: str) -> None:
    sql = _executable_sql(MIGRATION)
    assert re.search(rf"COMMENT\s+ON\s+TABLE\s+{table}\s+IS", sql, re.IGNORECASE), (
        f"`{table}` üçün `COMMENT ON TABLE` yoxdur."
    )


@pytest.mark.parametrize("table", NEW_TABLES)
def test_every_new_column_is_documented(table: str) -> None:
    """Sənədsiz sütun bir il sonra "bu nə idi?" sualına çevrilir."""
    sql = _executable_sql(MIGRATION)
    missing = [
        column
        for column in _columns(MIGRATION, table)
        if not re.search(rf"COMMENT\s+ON\s+COLUMN\s+{table}\.{column}\s+IS", sql, re.IGNORECASE)
    ]
    assert not missing, f"`{table}` sütunları sənədsizdir: {missing}"


def test_all_time_columns_are_timezone_aware() -> None:
    """Naiv `TIMESTAMP` QADAĞANDIR (CLAUDE.md §4 — tz-aware qaydası)."""
    sql = _executable_sql(MIGRATION)
    assert not re.search(r"\bTIMESTAMP\b(?!\s*TZ)", sql, re.IGNORECASE), (
        "Qurşaqsız `TIMESTAMP` var — yay/qış saatı keçidində səssiz sürüşmə verər."
    )


def test_indexes_are_created_idempotently() -> None:
    sql = _executable_sql(MIGRATION)
    non_idempotent = [
        match.group(0)
        for match in re.finditer(r"CREATE\s+(UNIQUE\s+)?INDEX\s+(?!IF\s+NOT\s+EXISTS)\S+", sql)
    ]
    assert not non_idempotent, f"İdempotent olmayan indeks: {non_idempotent}"


def test_every_updated_at_column_has_a_trigger() -> None:
    """`updated_at` trigger olmadan ƏL İLƏ yenilənməli olardı — və unudulardı."""
    sql = _executable_sql(MIGRATION)
    for table in NEW_TABLES:
        if "updated_at" not in _columns(MIGRATION, table):
            continue
        assert re.search(rf"CREATE\s+TRIGGER\s+\w+\s+BEFORE\s+UPDATE\s+ON\s+{table}\b", sql), (
            f"`{table}.updated_at` üçün trigger bağlanmayıb."
        )


# --------------------------------------------------------------------------- #
# #26 + #27 — genişlənə bilən şablon/kateqoriya dizaynı
# --------------------------------------------------------------------------- #


def test_report_type_and_category_are_catalog_references_not_frozen_lists() -> None:
    """Yeni şablon/kateqoriya DDL tələb ETMƏMƏLİDİR (018 `source` qərarı)."""
    body = re.sub(r"\s+", " ", _table_body(MIGRATION, "field_reports"))
    assert "type TEXT NOT NULL REFERENCES field_report_types(code)" in body, (
        "`field_reports.type` kataloqa istinad etmir."
    )
    assert not re.search(r"CHECK\s*\(\s*type\s+IN", body, re.IGNORECASE), (
        "`type` üzərində sərt CHECK siyahısı var — hər yeni şablon miqrasiya tələb edərdi."
    )
    assert not re.search(r"CHECK\s*\(\s*category\s+IN", body, re.IGNORECASE), (
        "`category` üzərində sərt CHECK siyahısı var."
    )
    assert "ON DELETE NO ACTION" in body, "Kataloq sətri hesabatlar qalarkən silinə bilməməlidir."


def test_category_cannot_drift_to_another_report_type() -> None:
    """Birləşmiş FK: insident kateqoriyası audit hesabatına yazıla bilməz."""
    body = re.sub(r"\s+", " ", _table_body(MIGRATION, "field_reports"))
    assert (
        "FOREIGN KEY (type, category) REFERENCES field_report_categories (report_type, code)"
        in body
    ), "Şablon–kateqoriya uyğunluğu struktur şəkildə qorunmur."
    parent = re.sub(r"\s+", " ", _table_body(MIGRATION, "field_report_categories"))
    assert "UNIQUE (report_type, code)" in parent, (
        "Birləşmiş FK-nın hədəf açarı yoxdur — FK yaradıla bilməzdi."
    )


def test_both_report_templates_and_their_categories_are_seeded() -> None:
    """Faza 3 heç bir DDL yazmadan işə düşməlidir."""
    sql = _executable_sql(MIGRATION)
    for code in ("'STORE_AUDIT'", "'INCIDENT'"):
        assert code in sql, f"{code} şablonu seed edilməyib"
    for code in (
        "AUDIT_TEMIZLIK",
        "AUDIT_VITRIN",
        "AUDIT_TEHLUKESIZLIK",
        "AUDIT_KASSA",
        "INCIDENT_OGURLUQ",
        "INCIDENT_QEZA",
        "INCIDENT_AVADANLIQ",
        "INCIDENT_SIKAYET",
    ):
        assert f"'{code}'" in sql, f"{code} kateqoriyası seed edilməyib"


def test_photo_references_are_a_typed_text_array() -> None:
    """Fayl BAYTI burada saxlanılmır; JSONB element tipini zəmanət verməzdi."""
    body = re.sub(r"\s+", " ", _table_body(MIGRATION, "field_reports"))
    assert "photo_refs TEXT[] NOT NULL DEFAULT '{}'::text[]" in body, (
        "`photo_refs` mətn massivi deyil — element tipi zəmanətsiz qalar."
    )
    assert "NOT ('' = ANY (photo_refs))" in body, (
        "Boş istinad elementi bloklanmır — o, 'şəkil var' kimi görünüb heç nəyə açılmır."
    )
    assert "jsonb" not in body.lower(), "Foto istinadları üçün JSONB seçilib."


# --------------------------------------------------------------------------- #
# #26 — checklist bəndinin üç vəziyyəti
# --------------------------------------------------------------------------- #


def test_checklist_result_is_three_valued() -> None:
    """`passed` NULL qala bilər = "hələ yoxlanılmadı"."""
    body = re.sub(r"\s+", " ", _table_body(MIGRATION, "field_report_checklist_items"))
    assert re.search(r"\bpassed\s+BOOLEAN\s*,", body), (
        "`passed` üç vəziyyətli deyil (NOT NULL və ya başqa tip) — cavabsız bənd "
        "uğursuzdan ayrıla bilməzdi."
    )
    assert "is_checked" not in body, (
        "Ayrı `is_checked` sütunu ziddiyyətli cütə (yoxlanılmayıb + keçdi) imkan verərdi."
    )


def test_the_task_engine_index_uses_the_null_safe_predicate() -> None:
    """`= FALSE` cavabsız bəndi ATLAYIR; düzgün predikat həm də sürətli yoldur."""
    sql = _normalized(MIGRATION)
    anchor = "CREATE INDEX IF NOT EXISTS idx_field_report_items_failed_blocking"
    assert anchor in sql, "Tapşırıq Mühərrikinin indeksi yoxdur"
    predicate = sql.split(anchor, 1)[1].split(";", 1)[0]
    assert "WHERE passed IS FALSE AND is_blocking" in predicate


def test_checklist_items_cannot_drift_to_another_tenant() -> None:
    body = re.sub(r"\s+", " ", _table_body(MIGRATION, "field_report_checklist_items"))
    assert "FOREIGN KEY (tenant_id, report_id) REFERENCES field_reports (tenant_id, id)" in body, (
        "Uşaq sətir başqa kirayəçinin hesabatına bağlana bilər."
    )


# --------------------------------------------------------------------------- #
# #28 — balans və üst-üstə düşmə
# --------------------------------------------------------------------------- #


def test_annual_leave_balance_is_unique_per_employee_and_year() -> None:
    body = re.sub(r"\s+", " ", _table_body(MIGRATION, "annual_leave_balances"))
    assert "UNIQUE (tenant_id, employee_id, year)" in body, (
        "Paralel iki INSERT iki balans yaradar və 'neçə gün qalıb?' sualının iki cavabı olardı."
    )


def test_annual_leave_balance_cannot_go_negative_in_the_database() -> None:
    """Qayda İKİ yerdədir (CLAUDE.md §5) — ekranı yan keçən skript də ona tabedir."""
    body = re.sub(r"\s+", " ", _table_body(MIGRATION, "annual_leave_balances"))
    assert "CONSTRAINT chk_annual_leave_balance_not_negative" in body
    assert "CHECK (used_days <= entitled_days + carried_over_days)" in body


def test_annual_leave_request_dates_are_ordered() -> None:
    body = re.sub(r"\s+", " ", _table_body(MIGRATION, "annual_leave_requests"))
    assert "CHECK (end_date >= start_date)" in body


def test_approved_leave_ranges_cannot_overlap() -> None:
    """Paralel iki təsdiqdə tətbiq qatının oxu-yaz yoxlaması uduzur."""
    body = re.sub(r"\s+", " ", _table_body(MIGRATION, "annual_leave_requests"))
    assert "EXCLUDE USING gist" in body, "Üst-üstə düşmə qapağı yoxdur"
    assert "employee_id WITH =" in body
    assert "daterange(start_date, end_date, '[]') WITH &&" in body, (
        "Aralıq qapalı-qapalı olmalıdır: `[)` yazılsaydı bir sorğunun son günü "
        "digərinin ilk günü ilə üst-üstə düşərdi."
    )
    assert "WHERE (status = 'APPROVED')" in body, (
        "Qapaq qismən olmalıdır — gözləyən/rədd edilmiş sorğular kəsişə bilər."
    )
    assert "CREATE EXTENSION IF NOT EXISTS btree_gist" in _executable_sql(MIGRATION), (
        "`uuid` sütununun `=` operatoru gist indeksində yalnız btree_gist ilə işləyir."
    )


def test_approved_leave_must_declare_the_deducted_days() -> None:
    """Balansla sorğular arasında uzlaşdırma yalnız bu sütunla mümkündür."""
    body = re.sub(r"\s+", " ", _table_body(MIGRATION, "annual_leave_requests"))
    assert "CHECK (status <> 'APPROVED' OR deducted_days IS NOT NULL)" in body


def test_annual_leave_is_kept_separate_from_the_intraday_leave_system() -> None:
    """Ayrılıq QƏSDƏNDİR — mənbədə açıq yazılmalıdır ki, sonradan birləşdirilməsin."""
    text = MIGRATION.read_text(encoding="utf-8")
    assert "leave_requests" in text, "Mövcud gündaxili icazə sistemi ilə fərq izah edilmir"
    assert "Shift Matrix" in text, "Off-day sistemi ilə fərq izah edilmir"
    sql = _executable_sql(MIGRATION)
    assert not re.search(r"\bALTER\s+TABLE\s+leave_requests\b", sql, re.IGNORECASE)


# --------------------------------------------------------------------------- #
# #29 / #30 / HR-D
# --------------------------------------------------------------------------- #


def test_store_template_survives_its_source_store() -> None:
    """Şablonun dəyəri `config_snapshot`-dadır, mənbə mağazada deyil."""
    body = re.sub(r"\s+", " ", _table_body(MIGRATION, "store_templates"))
    assert "based_on_store_id UUID REFERENCES stores(id) ON DELETE SET NULL" in body
    assert "config_snapshot JSONB NOT NULL" in body
    assert "config_snapshot <> '{}'::jsonb" in body, (
        "Boş şablondan yaradılan mağaza heç bir ayar almazdı."
    )


def test_bulk_import_failures_must_carry_a_reason() -> None:
    body = re.sub(r"\s+", " ", _table_body(MIGRATION, "bulk_import_log"))
    assert "CONSTRAINT chk_bulk_import_error_detail" in body
    assert "CONSTRAINT chk_bulk_import_counts" in body
    assert "performed_at" in body, "Vaxt sütunu `_at` şəkilçisi ilə adlanmalıdır"


def test_executive_digest_frequency_is_a_closed_list_but_role_is_not() -> None:
    """Tezlik planlayıcının iş açarına bağlıdır; rol isə kirayəçinin kataloqundandır."""
    body = re.sub(r"\s+", " ", _table_body(MIGRATION, "executive_digest_config"))
    assert "CHECK (frequency IN ('DAILY', 'WEEKLY', 'MONTHLY'))" in body
    assert not re.search(r"CHECK\s*\(\s*recipient_role\s+IN", body, re.IGNORECASE)
    assert "cardinality(metrics_included) >= 1" in body, "Boş metrik siyahısı boş e-poçt deməkdir."
    assert "UNIQUE (tenant_id, recipient_role, frequency)" in body


def test_export_corrections_require_a_real_reason_and_a_real_change() -> None:
    """Səbəbsiz düzəliş auditdə dəyərsizdir; dəyişməyən düzəliş isə səs-küydür."""
    body = re.sub(r"\s+", " ", _table_body(MIGRATION, "export_manual_corrections"))
    assert re.search(r"reason\s+TEXT\s+NOT\s+NULL\s+CHECK\s*\(char_length\(trim\(reason\)\)", body)
    assert "CHECK (old_value IS DISTINCT FROM new_value)" in body
    assert "corrected_by UUID NOT NULL" in body


# --------------------------------------------------------------------------- #
# Soft delete və silmə hüququ
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("table", SOFT_DELETE_TABLES)
def test_catalog_like_tables_use_soft_delete(table: str) -> None:
    """Fiziki `DELETE` keçmiş qərarın sübutunu məhv edərdi."""
    columns = _columns(MIGRATION, table)
    assert "is_active" in columns, f"`{table}` soft delete bayrağı daşımır."
    assert "deactivated_at" in columns, f"`{table}` söndürülmə anını saxlamır."


@pytest.mark.parametrize("table", NO_DELETE_TABLES)
def test_no_new_table_grants_delete_to_the_application_role(table: str) -> None:
    """⚠️ DAR `GRANT` KİFAYƏT ETMİR — `ALTER DEFAULT PRIVILEGES` (schema.sql §28)
    sonradan yaradılan hər cədvələ `DELETE` verir; açıq `REVOKE` məcburidir.
    """
    sql = _concatenated_literals(_executable_sql(MIGRATION))
    for grant in re.findall(r"GRANT SELECT, INSERT, UPDATE, DELETE ON ([^']+)", sql):
        assert table not in grant, f"`{table}` üçün DELETE səlahiyyəti verilib."

    revokes = re.findall(r"REVOKE (?:UPDATE, )?DELETE ON ([^']+)", sql)
    assert any(table in revoke for revoke in revokes), (
        f"`{table}` üçün açıq `REVOKE DELETE` yoxdur."
    )


def test_export_corrections_are_immutable() -> None:
    """Düzəlişin özü düzəldilə bilsəydi, audit izi geri yazıla bilərdi."""
    sql = _concatenated_literals(_executable_sql(MIGRATION))
    assert "REVOKE UPDATE, DELETE ON export_manual_corrections" in sql
    updating_grants = re.findall(r"GRANT SELECT, INSERT, UPDATE ON ([^']+)", sql)
    for grant in updating_grants:
        assert "export_manual_corrections" not in grant, "Dəyişməz audit sətrinə UPDATE verilib."
