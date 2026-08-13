"""Faza 1 sxem genişlənməsinin (miqrasiya 018–020) struktur qapıları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TEST STATİK MƏTN ÜZƏRİNDƏ İŞLƏYİR
──────────────────────────────────────────────────────────────────────────────
Cədvəl, indeks, trigger və RLS siyasəti YALNIZ canlı PostgreSQL-də icra olunur;
vahid testlərdə isə sahtə repo-lar var. Sintaksisi CI-ın `db-schema` job-u
yoxlayır (sxem + miqrasiyalar İKİ dəfə tətbiq olunur). Burada verilən sual
başqadır: "qayda mənbədə HƏLƏ DƏ varmı?" — və cavab mətndən oxunur.
`tests/unit/test_db_guard_parity.py` və `test_race_condition_guards.py` eyni
naxışı işlədir.

NƏ QORUNUR
──────────────────────────────────────────────────────────────────────────────
1. QIRMIZI XƏTT — miqrasiyalar heç nə SİLMİR: icra olunan SQL-də `DROP TABLE`,
   `DROP COLUMN`, `RENAME`, `ALTER COLUMN ... TYPE` yoxdur. Bu qayda insan
   yaddaşına buraxılsa, növbəti "kiçik düzəliş" mövcud cədvəli sükutla
   dəyişdirə bilər.
2. ÇOX-KİRAYƏÇİLİK — hər yeni cədvəldə `tenant_id` + RLS + `tenant_isolation`
   siyasəti. Biri unudulsa, tətbiq rolu BAŞQA kirayəçinin sətrini oxuya bilər
   (SEC-008 fail-closed zəmanəti).
3. SƏNƏDLƏŞMƏ — hər cədvəl və HƏR sütun `COMMENT` daşıyır. Layihənin üslub
   qaydası budur: qərarın NİYƏ-si mənbədə yazılır.
4. TZ QAYDASI — bütün vaxt sütunları `TIMESTAMPTZ`. Naiv `TIMESTAMP` yay/qış
   saatı keçidində bir saatlıq səssiz sürüşmə verir.
5. İDEMPOTENTLİK — `IF NOT EXISTS` cütləri (CI iki dəfə tətbiq edir).
6. #16 "İLK BASAN QAZANIR" — DB qatının mövcudluğu (qismən unikal indeks +
   status keçid trigger-i).
7. #9 GENİŞLƏNƏ BİLƏN MƏNBƏ — `exceptions.source` sərt `CHECK` siyahısı DEYİL.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR: Final = PROJECT_ROOT / "database" / "migrations"

POS_MIGRATION: Final = MIGRATIONS_DIR / "018_pos_policy_and_exception_engine.sql"
SHIFT_MIGRATION: Final = MIGRATIONS_DIR / "019_shift_intelligence_tables.sql"
HR_MIGRATION: Final = MIGRATIONS_DIR / "020_hr_lifecycle_tables.sql"

#: Yeni cədvəl → onu yaradan miqrasiya. `exception_sources` və
#: `announcement_targets` spesifikasiyada AYRICA sadalanmır: birincisi #9-un
#: "genişlənə bilən mənbə" tələbinin, ikincisi #19-un `STORE_LIST` əhatəsinin
#: struktur cavabıdır (əsaslandırma miqrasiya başlıqlarındadır).
NEW_TABLES: Final[dict[str, Path]] = {
    "pos_permission_thresholds": POS_MIGRATION,
    "employee_behavior_baseline": POS_MIGRATION,
    "exception_sources": POS_MIGRATION,
    "exceptions": POS_MIGRATION,
    "staffing_pattern_suggestions": SHIFT_MIGRATION,
    "overtime_log": SHIFT_MIGRATION,
    "open_shift_postings": SHIFT_MIGRATION,
    "employee_documents": HR_MIGRATION,
    "announcements": HR_MIGRATION,
    "announcement_targets": HR_MIGRATION,
    "performance_reviews": HR_MIGRATION,
    "attrition_risk_scores": HR_MIGRATION,
}

#: Soft delete qaydasına tabe olan cədvəllər — burada fiziki `DELETE` yoxdur,
#: çünki sətir keçmiş qərarın SÜBUTUDUR (`catalogs.py` başlığı).
SOFT_DELETE_TABLES: Final = (
    "pos_permission_thresholds",
    "exception_sources",
    "employee_documents",
    "announcements",
)

MIGRATION_FILES: Final = (POS_MIGRATION, SHIFT_MIGRATION, HR_MIGRATION)

_LINE_COMMENT_RE: Final = re.compile(r"--[^\n]*")
_STRING_LITERAL_RE: Final = re.compile(r"'(?:[^']|'')*'", re.DOTALL)

#: Sətir başlayan sütun tərifi DEYİL, cədvəl səviyyəli məhdudiyyət olan açarlar.
_TABLE_LEVEL_KEYWORDS: Final = frozenset(
    {"CONSTRAINT", "UNIQUE", "PRIMARY", "FOREIGN", "CHECK", "EXCLUDE", "LIKE"}
)


def _executable_sql(path: Path) -> str:
    """`--` şərhlərini atır — DOWN bloku YALNIZ şərhdədir.

    Şərhlər saxlanılsaydı, "faylda `DROP TABLE` yoxdur" yoxlaması məhz
    sənədləşdirilmiş DOWN blokunu tapıb yalançı xəbərdarlıq verərdi.
    """
    return _LINE_COMMENT_RE.sub("", path.read_text(encoding="utf-8"))


def _masked_string_literals(sql: str) -> str:
    """Sətir sabitlərinin İÇİNİ boşluqla əvəzləyir, UZUNLUĞU saxlayır.

    Mötərizə sayan gövdə çıxarıcısı üçün lazımdır: `CHECK (period ~ '...(...)')`
    kimi ifadələrdə mötərizə MƏTNİN içindədir və struktur mötərizəsi deyil.
    Uzunluq saxlanılır ki, tapılan sərhədlər ORİJİNAL mətnə də tətbiq oluna
    bilsin — testlərin bir hissəsi məhz sabitlərin özünü (`'CLAIMED'`) yoxlayır.
    """
    return _STRING_LITERAL_RE.sub(lambda m: "'" + " " * (len(m.group(0)) - 2) + "'", sql)


def _concatenated_literals(sql: str) -> str:
    """Boşluqları yığır və QONŞU sətir sabitlərini birləşdirir.

    PostgreSQL sətir sonunda kəsilmiş literalları avtomatik birləşdirir
    (`'GRANT ... ON a, ' 'b TO %I'`). Bunu nəzərə almasaq, iki sətrə bölünmüş
    `GRANT`/`REVOKE` siyahısının SONUNCU cədvəli testdən gizli qalar.
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
    # Sabitlər maskalanır: `DEFAULT 'a, b'` kimi dəyər sütun sərhədi kimi
    # oxunmamalıdır.
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
        first = words[0]
        if first.upper() in _TABLE_LEVEL_KEYWORDS:
            continue
        names.append(first)
    return names


# --------------------------------------------------------------------------- #
# Nömrələmə və mövcudluq
# --------------------------------------------------------------------------- #


def test_the_new_migrations_continue_the_existing_sequence() -> None:
    """018–020 mövcud ən böyük nömrədən (017) SONRA gəlir.

    `{18, 19, 20} <= set(numbers)` (dəqiq "son üç" YOX) qəsdən seçilib: Faza 2
    (`021_rbac_flag_catalog_extension.sql`) və sonrakı fazalar ardıcıllığı
    davam etdirir — sərt "son üç" şərti hər yeni miqrasiyada bu testi
    yenidən sındırardı, halbuki əsl sual dəyişməyib: "boşluq/təkrar varmı?"
    """
    numbers = sorted(int(path.name[:3]) for path in MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    assert numbers == list(range(1, max(numbers) + 1)), (
        "Miqrasiya nömrələrində boşluq və ya təkrar var — `psql` sıralaması "
        "faylları ada görə düzür, boşluq isə tətbiq sırasını şübhəli edir."
    )
    assert {18, 19, 20} <= set(numbers)


@pytest.mark.parametrize("path", MIGRATION_FILES, ids=lambda p: p.name)
def test_each_migration_documents_its_down_block(path: Path) -> None:
    """DOWN bloku şərh içində sənədləşdirilir (CLAUDE.md §7)."""
    text = path.read_text(encoding="utf-8")
    assert "-- DOWN" in text, f"{path.name}: DOWN başlığı yoxdur"
    assert re.search(r"^--\s+DROP TABLE IF EXISTS", text, re.MULTILINE), (
        f"{path.name}: DOWN bloku geri qaytarma addımlarını göstərmir"
    )


# --------------------------------------------------------------------------- #
# QIRMIZI XƏTT — heç nə silinmir, dəyişdirilmir
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", MIGRATION_FILES, ids=lambda p: p.name)
def test_migrations_never_destroy_or_reshape_existing_objects(path: Path) -> None:
    """İcra olunan SQL-də dağıdıcı DDL OLMAMALIDIR.

    `DROP TRIGGER` / `DROP POLICY` istisnadır: onlar İDEMPOTENTLİK naxışının
    hissəsidir (dərhal ardınca yenidən yaradılır) və mövcud məlumatı silmir.
    """
    sql = _executable_sql(path)
    forbidden = {
        "DROP TABLE": r"\bDROP\s+TABLE\b",
        "DROP COLUMN": r"\bDROP\s+COLUMN\b",
        "RENAME": r"\bRENAME\b",
        "ALTER COLUMN ... TYPE": r"\bALTER\s+COLUMN\b[^;]*\bTYPE\b",
        "DROP CONSTRAINT": r"\bDROP\s+CONSTRAINT\b",
        "TRUNCATE": r"\bTRUNCATE\b",
    }
    for label, pattern in forbidden.items():
        assert not re.search(pattern, sql, re.IGNORECASE), (
            f"{path.name}: icra olunan SQL-də `{label}` var — Faza 1 YALNIZ "
            "əlavə etməlidir (kompasos11.md QIRMIZI XƏTT)."
        )


@pytest.mark.parametrize("path", MIGRATION_FILES, ids=lambda p: p.name)
def test_alter_table_only_targets_the_new_tables(path: Path) -> None:
    """`ALTER TABLE` yalnız BU miqrasiyanın yaratdığı cədvələ toxunur.

    `%I` — RLS döngəsindəki `format()` şablonudur; faktiki adlar həmin
    döngənin massivindədir və `test_every_new_table_enables_row_level_security`
    onları ayrıca yoxlayır.
    """
    sql = _executable_sql(path)
    targets = {
        match.group(1) for match in re.finditer(r"ALTER\s+TABLE\s+([\w%]+)", sql, re.IGNORECASE)
    }
    allowed = {name for name, source in NEW_TABLES.items() if source == path} | {"%I"}
    assert targets <= allowed, (
        f"{path.name}: MÖVCUD cədvələ `ALTER TABLE` tətbiq olunur: {sorted(targets - allowed)}"
    )


# --------------------------------------------------------------------------- #
# Çox-kirayəçilik: tenant_id + RLS + siyasət
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("table", NEW_TABLES)
def test_every_new_table_is_created_idempotently(table: str) -> None:
    """CI hər miqrasiyanı İKİ dəfə tətbiq edir."""
    sql = _executable_sql(NEW_TABLES[table])
    assert re.search(rf"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+{table}\b", sql, re.IGNORECASE), (
        f"`{table}` `IF NOT EXISTS` olmadan yaradılır — ikinci icra çökər."
    )


@pytest.mark.parametrize("table", NEW_TABLES)
def test_every_new_table_carries_a_tenant_id(table: str) -> None:
    """Kirayəçi açarı OLMAYAN cədvəl RLS ilə izolyasiya edilə bilmir."""
    assert "tenant_id" in _columns(NEW_TABLES[table], table), (
        f"`{table}` cədvəlində `tenant_id` yoxdur — çox-kirayəçi izolyasiyası mümkün deyil."
    )


@pytest.mark.parametrize("table", NEW_TABLES)
def test_every_new_table_enables_row_level_security(table: str) -> None:
    """RLS açıq şəkildə İŞƏ SALINIR (fail-closed, SEC-008).

    Cədvəl ya birbaşa `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` ilə, ya da
    `format()` döngəsinin massivində adı çəkilməklə əhatə olunur.
    """
    sql = _executable_sql(NEW_TABLES[table])
    direct = re.search(
        rf"ALTER\s+TABLE\s+{table}\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY", sql, re.IGNORECASE
    )
    in_loop = re.search(rf"'{table}'", sql) and "ENABLE ROW LEVEL SECURITY" in sql.upper()
    assert direct or in_loop, (
        f"`{table}` üçün RLS işə salınmır — tətbiq rolu başqa kirayəçinin sətrini oxuya bilər."
    )


@pytest.mark.parametrize("table", NEW_TABLES)
def test_every_new_table_gets_a_tenant_isolation_policy(table: str) -> None:
    """RLS siyasətsiz açılsaydı, cədvəl HEÇ KİMƏ görünməzdi (səssiz nasazlıq)."""
    sql = _executable_sql(NEW_TABLES[table])
    direct = re.search(rf"CREATE\s+POLICY\s+tenant_isolation\s+ON\s+{table}\b", sql, re.IGNORECASE)
    in_loop = re.search(rf"'{table}'", sql) and "CREATE POLICY tenant_isolation ON %I" in sql
    assert direct or in_loop, f"`{table}` üçün `tenant_isolation` siyasəti yoxdur."
    assert "current_tenant_id()" in sql


def test_the_system_wide_source_catalog_is_readable_by_every_tenant() -> None:
    """`exception_sources` — `positions` naxışı: `tenant_id IS NULL` = sistem sətri."""
    sql = _executable_sql(POS_MIGRATION)
    policy = re.search(
        r"CREATE\s+POLICY\s+tenant_isolation\s+ON\s+exception_sources(.*?);", sql, re.DOTALL
    )
    assert policy is not None
    body = re.sub(r"\s+", " ", policy.group(1))
    assert "tenant_id = current_tenant_id() OR tenant_id IS NULL" in body, (
        "Sistem mənbələri (tenant_id IS NULL) heç bir kirayəçiyə görünməzdi."
    )
    assert "WITH CHECK (tenant_id = current_tenant_id())" in body, (
        "Kirayəçi öz sətrini SİSTEM sətri kimi yaza bilərdi."
    )


# --------------------------------------------------------------------------- #
# Sənədləşmə və tz-aware qaydası
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("table", NEW_TABLES)
def test_every_new_table_is_documented(table: str) -> None:
    sql = _executable_sql(NEW_TABLES[table])
    assert re.search(rf"COMMENT\s+ON\s+TABLE\s+{table}\s+IS", sql, re.IGNORECASE), (
        f"`{table}` üçün `COMMENT ON TABLE` yoxdur."
    )


@pytest.mark.parametrize("table", NEW_TABLES)
def test_every_new_column_is_documented(table: str) -> None:
    """Sənədsiz sütun bir il sonra "bu nə idi?" sualına çevrilir."""
    path = NEW_TABLES[table]
    sql = _executable_sql(path)
    missing = [
        column
        for column in _columns(path, table)
        if not re.search(rf"COMMENT\s+ON\s+COLUMN\s+{table}\.{column}\s+IS", sql, re.IGNORECASE)
    ]
    assert not missing, f"`{table}` sütunları sənədsizdir: {missing}"


@pytest.mark.parametrize("path", MIGRATION_FILES, ids=lambda p: p.name)
def test_all_time_columns_are_timezone_aware(path: Path) -> None:
    """Naiv `TIMESTAMP` QADAĞANDIR (CLAUDE.md §4 — tz-aware qaydası)."""
    sql = _executable_sql(path)
    assert not re.search(r"\bTIMESTAMP\b(?!\s*TZ)", sql, re.IGNORECASE), (
        f"{path.name}: qurşaqsız `TIMESTAMP` sütunu var — yay/qış saatı "
        "keçidində bir saatlıq səssiz sürüşmə verər."
    )


@pytest.mark.parametrize("path", MIGRATION_FILES, ids=lambda p: p.name)
def test_indexes_are_created_idempotently(path: Path) -> None:
    sql = _executable_sql(path)
    non_idempotent = [
        match.group(0)
        for match in re.finditer(r"CREATE\s+(UNIQUE\s+)?INDEX\s+(?!IF\s+NOT\s+EXISTS)\S+", sql)
    ]
    assert not non_idempotent, f"{path.name}: idempotent olmayan indeks: {non_idempotent}"


# --------------------------------------------------------------------------- #
# #16 — "ilk basan qazanır" DB qatı
# --------------------------------------------------------------------------- #


def test_open_shift_posting_has_a_partial_unique_claim_guard() -> None:
    """Qismən unikal indeks yalnız TUTULMUŞ elanları əhatə edir.

    Şərt olmasaydı, ləğv edilmiş və ya açıq elanlar da indeksə düşər və işçinin
    həmin günə növbəti seçimini ƏBƏDİ bloklayardı — `migrations/015`-dəki
    `REVERSED` dərsinin eynisi.
    """
    sql = re.sub(r"\s+", " ", _executable_sql(SHIFT_MIGRATION))
    anchor = "CREATE UNIQUE INDEX IF NOT EXISTS uq_open_shift_one_claim_per_employee_day"
    assert anchor in sql, "İşçi-gün üzrə tutma qapağı yoxdur"
    predicate = sql.split(anchor, 1)[1].split(";", 1)[0]
    assert "WHERE status = 'CLAIMED'" in predicate
    assert "claimed_by" in predicate

    slot_anchor = "CREATE UNIQUE INDEX IF NOT EXISTS uq_open_shift_one_open_per_slot"
    assert slot_anchor in sql, "Eyni slot üçün iki açıq elan bloklanmır"
    assert "WHERE status = 'OPEN'" in sql.split(slot_anchor, 1)[1].split(";", 1)[0]


def test_open_shift_posting_status_transition_is_enforced_by_a_trigger() -> None:
    """Tətbiq qatı `WHERE status = 'OPEN'` şərtini unutsa da qalib qorunur."""
    sql = _executable_sql(SHIFT_MIGRATION)
    assert "CREATE OR REPLACE FUNCTION enforce_open_shift_claim_transition()" in sql
    assert re.search(
        r"CREATE\s+TRIGGER\s+trg_open_shift_claim_transition\s+BEFORE\s+UPDATE\s+ON\s+"
        r"open_shift_postings",
        sql,
        re.IGNORECASE,
    ), "Status keçid trigger-i bağlanmayıb"

    body = sql.split("enforce_open_shift_claim_transition() RETURNS TRIGGER", 1)[1]
    body = body.split("LANGUAGE plpgsql", 1)[0]
    assert "OLD.status <> 'OPEN'" in body, "OPEN olmayan sətirdən keçid bloklanmır"
    assert "NEW.claimed_by IS DISTINCT FROM OLD.claimed_by" in body, (
        "Tutulmuş elanın sahibi üstündən yazıla bilər — 'ilk basan qazanır' pozulur."
    )


def test_claimed_posting_cannot_exist_without_an_owner() -> None:
    """`CLAIMED` statusu `claimed_by` + `claimed_at` OLMADAN mümkün deyil."""
    body = re.sub(r"\s+", " ", _table_body(SHIFT_MIGRATION, "open_shift_postings"))
    assert "CONSTRAINT chk_open_shift_claim" in body
    assert "status = 'CLAIMED' AND claimed_by IS NOT NULL AND claimed_at IS NOT NULL" in body


# --------------------------------------------------------------------------- #
# #9 — genişlənə bilən mənbə dizaynı
# --------------------------------------------------------------------------- #


def test_exception_source_is_a_catalog_reference_not_a_frozen_list() -> None:
    """Yeni mənbə DDL tələb ETMƏMƏLİDİR (kompasos11.md struktur qərarı B)."""
    body = re.sub(r"\s+", " ", _table_body(POS_MIGRATION, "exceptions"))
    assert "source TEXT NOT NULL REFERENCES exception_sources(code)" in body, (
        "`exceptions.source` kataloqa istinad etmir."
    )
    assert not re.search(r"CHECK\s*\(\s*source\s+IN", body, re.IGNORECASE), (
        "`source` üzərində sərt CHECK siyahısı var — hər yeni mənbə miqrasiya tələb edərdi."
    )
    assert "ON DELETE NO ACTION" in body, (
        "Mənbə kataloqu istisna sətirləri qalarkən silinə bilməməlidir."
    )


def test_the_only_seeded_source_in_this_batch_is_the_behavior_anomaly() -> None:
    """Bu partiyada yeganə mənbə #8-in davranış anomaliyasıdır."""
    sql = _executable_sql(POS_MIGRATION)
    inserts = re.findall(r"INSERT\s+INTO\s+exception_sources.*?;", sql, re.DOTALL)
    assert len(inserts) == 1
    assert "'BEHAVIOR_ANOMALY'" in inserts[0]
    assert "ON CONFLICT (code) DO NOTHING" in inserts[0], (
        "Təkrar icra müştərinin redaktə etdiyi mətni üstündən yazardı."
    )


def test_exception_findings_are_deduplicated_regardless_of_status() -> None:
    """Rədd edilmiş tapıntı növbəti gecə YENİDƏN yaranmamalıdır."""
    sql = re.sub(r"\s+", " ", _executable_sql(POS_MIGRATION))
    anchor = "CREATE UNIQUE INDEX IF NOT EXISTS uq_exceptions_dedupe"
    assert anchor in sql
    predicate = sql.split(anchor, 1)[1].split(";", 1)[0]
    assert "dedupe_key IS NOT NULL" in predicate
    assert "status" not in predicate, (
        "Şərtə status əlavə edilsə, DISMISSED tapıntı təkrar açılar və "
        "'bir dəfə rədd etdim' qərarı mənasını itirər."
    )


# --------------------------------------------------------------------------- #
# Soft delete qaydası
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("table", SOFT_DELETE_TABLES)
def test_catalog_like_tables_use_soft_delete(table: str) -> None:
    """Fiziki `DELETE` keçmiş qərarın sübutunu məhv edərdi."""
    columns = _columns(NEW_TABLES[table], table)
    assert "is_active" in columns, f"`{table}` soft delete bayrağı daşımır."
    assert "deactivated_at" in columns, f"`{table}` söndürülmə anını saxlamır."


@pytest.mark.parametrize("table", [*SOFT_DELETE_TABLES, "exceptions", "performance_reviews"])
def test_evidence_tables_do_not_grant_delete_to_the_application_role(table: str) -> None:
    """Tətbiq rolu sübut sətrini SİLƏ BİLMƏMƏLİDİR.

    `GRANT ... DELETE` verilsəydi, soft delete qaydası yalnız kod nəzakəti
    olardı: ekranı yan keçən bir skript sətri fiziki silə bilərdi.

    ⚠️ DAR `GRANT` KİFAYƏT ETMİR. `schema.sql` §28 belə bitir:

        ALTER DEFAULT PRIVILEGES IN SCHEMA kompasos
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO kompasos_app;

    Yəni SONRADAN yaradılan hər cədvəl `DELETE`-i AVTOMATİK alır. Ona görə bu
    test yalnız "GRANT-da DELETE yoxdur"u yox, AÇIQ `REVOKE`-un mövcudluğunu
    da tələb edir — `audit_logs` / `permission_flags` ilə eyni naxış.
    """
    sql = _concatenated_literals(_executable_sql(NEW_TABLES[table]))
    delete_grants = re.findall(r"GRANT SELECT, INSERT, UPDATE, DELETE ON ([^']+)", sql)
    for grant in delete_grants:
        assert table not in grant, f"`{table}` üçün DELETE səlahiyyəti verilib."

    revokes = re.findall(r"REVOKE DELETE ON ([^']+)", sql)
    assert any(table in revoke for revoke in revokes), (
        f"`{table}` üçün açıq `REVOKE DELETE` yoxdur — `ALTER DEFAULT PRIVILEGES` "
        "(schema.sql §28) silmə hüququnu sükutla geri qaytarardı."
    )


def test_employee_documents_expose_the_shift_matrix_blocking_signal() -> None:
    """Faza 7 inteqrasiyası sxem tərəfindən DƏSTƏKLƏNİR."""
    columns = _columns(HR_MIGRATION, "employee_documents")
    assert "is_blocking" in columns
    assert "expiry_date" in columns
    sql = _executable_sql(HR_MIGRATION)
    assert "idx_employee_documents_blocking" in sql, (
        "Shift Matrix hər təyinetmədə bu sorğunu işlədir — indekssiz qalması "
        "bütün matrisi yavaşladar."
    )


def test_explainability_is_a_database_level_guarantee() -> None:
    """#21 — izah edilə bilməyən bal HR qərarını əsaslandıra bilməz."""
    body = re.sub(r"\s+", " ", _table_body(HR_MIGRATION, "attrition_risk_scores"))
    assert "factors_json JSONB NOT NULL" in body
    assert "factors_json <> '{}'::jsonb" in body, (
        "Boş `factors_json` qəbul edilsə, qara-qutu bal yazıla bilərdi."
    )
    assert "risk_band" not in body, (
        "Bant saxlanılmamalıdır: həddi Root dəyişəndə köhnə sətirlər köhnə təsnifatla qalar."
    )


def test_performance_ratings_stay_configuration_driven() -> None:
    """#20 — KPI siyahısı Faza 8-də konfiqurasiya ediləcək."""
    body = re.sub(r"\s+", " ", _table_body(HR_MIGRATION, "performance_reviews"))
    assert "ratings_json JSONB NOT NULL" in body
    assert "jsonb_typeof(ratings_json) = 'object'" in body
    assert "chk_review_not_self" in body, "Öz-özünü qiymətləndirmə bloklanmır."


def test_announcement_targets_cannot_drift_to_another_tenant() -> None:
    """Denormalizasiya edilmiş `tenant_id` birləşmiş FK ilə bağlanır."""
    body = re.sub(r"\s+", " ", _table_body(HR_MIGRATION, "announcement_targets"))
    assert (
        "FOREIGN KEY (tenant_id, announcement_id) REFERENCES announcements (tenant_id, id)" in body
    ), "Uşaq sətir başqa kirayəçinin elanına bağlana bilər."
    sql = _executable_sql(HR_MIGRATION)
    assert "enforce_announcement_target_scope" in sql, (
        "`scope = ALL` elana mağaza hədəfi yazılması bloklanmır."
    )
