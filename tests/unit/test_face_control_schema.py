"""`facecontrol.md` Faza 1 — Face Control sxem qatının (miqrasiya 047) qapıları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TEST STATİK MƏTN ÜZƏRİNDƏ İŞLƏYİR
──────────────────────────────────────────────────────────────────────────────
Cədvəl, indeks, trigger və RLS siyasəti YALNIZ canlı PostgreSQL-də icra olunur;
vahid testlərdə sahtə repo-lar var. Sintaksisi CI-ın `db-schema` job-u yoxlayır
(sxem + miqrasiyalar İKİ dəfə tətbiq olunur). Burada verilən sual başqadır:
"qayda mənbədə HƏLƏ DƏ varmı?" — və cavab mətndən oxunur.
`test_phase1_field_ops_schema.py` (037) eyni naxışı işlədir; köməkçi funksiyalar
QƏSDƏN köçürülüb, idxal edilmir: bir test faylının digərindən asılı olması bir
modulun adının dəyişməsini iki qapının birdən çökməsinə çevirərdi.

──────────────────────────────────────────────────────────────────────────────
NƏ QORUNUR — VƏ NİYƏ MƏHZ BUNLAR
──────────────────────────────────────────────────────────────────────────────
Face Control BİOMETRİK məlumatla işləyir, ona görə adi sxem qapılarından
(çox-kirayəçilik, sənədləşmə, idempotentlik, tz-aware) əlavə DÖRD qayda var və
onların hər biri bir sətirlik səhvlə sükutla pozula bilər:

  1. FOTO SAXLANMIR — heç bir sütun kadr/şəkil saxlamır.
  2. VEKTOR AÇIQ MƏTN DEYİL — sütun şərhi şifrələməni AÇIQ yazmalıdır, əks
     halda növbəti mühəndis onu adi mətn kimi doldurar.
  3. JURNALDA VEKTOR YOXDUR — əks halda hər cəhd ikinci biometrik nüsxə
     yaradar və deaktivasiyada silmə qaydası mənasız olar.
  4. ARXİVDƏ DƏ SİLİNİR — `PURGED` statusu ilə vektorun `NULL` olması `CHECK`
     ilə bağlanır; "silindi" deyib saxlamaq mümkün olmamalıdır.

Beşinci qrup MISMATCH sayğacının PIN sayğacından AYRI qalmasıdır — bu, bənd
3-ün ən vacib davranış qərarıdır və sxem səviyyəsində iki ayrı sütunla ifadə
olunur.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR: Final = PROJECT_ROOT / "database" / "migrations"
MIGRATION: Final = MIGRATIONS_DIR / "047_face_control_schema.sql"

#: Bu miqrasiyanın YARATDIĞI cədvəllər.
NEW_TABLES: Final = (
    "face_embedding_history",
    "face_verification_log",
    "face_control_exemptions",
    "face_control_store_scope",
)

#: `employees`-ə ƏLAVƏ olunan sütunlar (mövcud sütunlara toxunulmur).
NEW_EMPLOYEE_COLUMNS: Final = (
    "face_embedding",
    "face_enrolled_at",
    "face_mismatch_attempts",
    "face_locked_until",
)

#: `facecontrol.md`-nin ON ROOT parametri: doqquzu "ROOT PARAMETRİ" işarəsi
#: ilə açıq sadalanır, onuncusu (`FACE_ENROLLMENT_FRAME_COUNT`) isə sənədin
#: MƏRKƏZİ TƏLƏBİNDƏN doğur — "tapılıb bura əlavə edilməyən, amma sənin
#: gördüyün istənilən başqa konfiqurasiya edilə bilən ədəd/həddi/say" da
#: `system_limits`-ə yazılmalıdır. Kadr sayı (bənd 11) məhz belə bir ədəddir.
FACE_LIMIT_KEYS: Final = (
    SystemLimitKey.FACE_ENROLLMENT_MIN_QUALITY,
    SystemLimitKey.FACE_ENROLLMENT_FRAME_COUNT,
    SystemLimitKey.FACE_MISMATCH_LOCKOUT_THRESHOLD,
    SystemLimitKey.FACE_LIVENESS_ACTIONS,
    SystemLimitKey.FACE_MATCH_TOLERANCE,
    SystemLimitKey.FACE_LOW_CONFIDENCE_TOLERANCE,
    SystemLimitKey.FACE_REENROLLMENT_REMINDER_MONTHS,
    SystemLimitKey.FACE_EXEMPTION_MAX_DAYS,
    SystemLimitKey.FACE_VERIFICATION_LOG_RETENTION_MONTHS,
    SystemLimitKey.FACE_VERIFICATION_MAX_SECONDS,
)

_LINE_COMMENT_RE: Final = re.compile(r"--[^\n]*")
_STRING_LITERAL_RE: Final = re.compile(r"'(?:[^']|'')*'", re.DOTALL)

_TABLE_LEVEL_KEYWORDS: Final = frozenset(
    {"CONSTRAINT", "UNIQUE", "PRIMARY", "FOREIGN", "CHECK", "EXCLUDE", "LIKE"}
)


def _raw_sql() -> str:
    """Faylın TAM mətni — DOWN bloku və başlıq şərhləri DAXİL."""
    return MIGRATION.read_text(encoding="utf-8")


def _executable_sql() -> str:
    """`--` şərhlərini atır — DOWN bloku YALNIZ şərhdədir."""
    return _LINE_COMMENT_RE.sub("", _raw_sql())


def _masked_string_literals(sql: str) -> str:
    """Sətir sabitlərinin İÇİNİ boşluqla əvəzləyir, UZUNLUĞU saxlayır."""
    return _STRING_LITERAL_RE.sub(lambda m: "'" + " " * (len(m.group(0)) - 2) + "'", sql)


def _table_body(table: str) -> str:
    """`CREATE TABLE IF NOT EXISTS <table> ( ... )` gövdəsini qaytarır."""
    raw = _executable_sql()
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


def _columns(table: str) -> list[str]:
    """Cədvəlin sütun adları (cədvəl səviyyəli məhdudiyyətlər kənarda)."""
    body = _masked_string_literals(_table_body(table))
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


# --------------------------------------------------------------------------- #
# 1. Nömrələmə, preambula, DOWN
# --------------------------------------------------------------------------- #


def test_the_migration_continues_the_existing_sequence() -> None:
    """047 boşluqsuz ardıcıllığı davam etdirir və 046-ya TOXUNMUR.

    `psql` faylları ADA görə sıralayır; buraxılmış nömrə tətbiq sırasını
    şübhəli edər və "hansı miqrasiya çatışmır?" sualını insan yaddaşına buraxardı.
    """
    numbers = sorted(int(path.name[:3]) for path in MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    assert numbers == list(range(1, max(numbers) + 1)), (
        "Miqrasiya nömrələrində boşluq və ya təkrar var."
    )
    assert 47 in numbers, "047 miqrasiyası tapılmadı"
    assert MIGRATION.exists(), f"Gözlənilən fayl yoxdur: {MIGRATION.name}"
    assert (MIGRATIONS_DIR / "046_position_flag_hierarchy_guard.sql").exists(), (
        "046 başqa iş üçün istifadə olunub və yerində qalmalıdır."
    )


def test_the_migration_sets_the_search_path_before_any_object() -> None:
    """Preambula İLK obyekt istinadından əvvəl gəlir (son 6 miqrasiyada unudulmuşdu)."""
    sql = _executable_sql()
    preamble = re.search(r"SET\s+search_path\s+TO\s+kompasos\s*,\s*public\s*;", sql)
    assert preamble is not None, "`SET search_path` preambulası yoxdur"
    first_object = re.search(r"\b(ALTER\s+TABLE|CREATE\s+TABLE|INSERT\s+INTO)\b", sql, re.I)
    assert first_object is not None
    assert preamble.start() < first_object.start()


def test_the_migration_documents_its_down_block_with_a_loss_warning() -> None:
    """DOWN bloku + İTKİ xəbərdarlığı şərh içində sənədləşdirilir (CLAUDE.md §7).

    Xəbərdarlıq burada adi nəzakət deyil: foto saxlanmadığı üçün üz vektoru
    HEÇ BİR yerdən yenidən hesablana bilməz — geri qaytarma hər işçinin
    fiziki olaraq yenidən qeydiyyatdan keçməsi deməkdir.
    """
    text = _raw_sql()
    assert "-- DOWN" in text, "DOWN başlığı yoxdur"
    assert re.search(r"^--\s+DROP TABLE IF EXISTS", text, re.MULTILINE), (
        "DOWN bloku geri qaytarma addımlarını göstərmir"
    )
    assert "İTKİ XƏBƏRDARLIĞI" in text, (
        "DOWN bloku bərpa edilə bilməyən biometrik itkini xəbərdar etmir."
    )


# --------------------------------------------------------------------------- #
# 2. QIRMIZI XƏTT — heç nə silinmir/dəyişdirilmir
# --------------------------------------------------------------------------- #


def test_the_migration_never_destroys_or_reshapes_existing_objects() -> None:
    """İcra olunan SQL-də dağıdıcı DDL OLMAMALIDIR.

    `DROP TRIGGER` / `DROP POLICY` istisnadır: onlar idempotentlik naxışının
    hissəsidir (dərhal ardınca yenidən yaradılır) və məlumat silmir.
    """
    sql = _executable_sql()
    forbidden = {
        "DROP TABLE": r"\bDROP\s+TABLE\b",
        "DROP COLUMN": r"\bDROP\s+COLUMN\b",
        "RENAME": r"\bRENAME\b",
        "ALTER COLUMN ... TYPE": r"\bALTER\s+COLUMN\b[^;]*\bTYPE\b",
        "DROP CONSTRAINT": r"\bDROP\s+CONSTRAINT\b",
        "TRUNCATE": r"\bTRUNCATE\b",
        "DELETE FROM": r"\bDELETE\s+FROM\b",
        "UPDATE": r"\bUPDATE\s+\w+\s+SET\b",
    }
    for label, pattern in forbidden.items():
        assert not re.search(pattern, sql, re.IGNORECASE), (
            f"İcra olunan SQL-də `{label}` var — Faza 1 YALNIZ əlavə etməlidir."
        )


def test_alter_table_only_touches_employees_and_the_new_tables() -> None:
    """`ALTER TABLE` yalnız `employees`-ə (ADD COLUMN) və yeni cədvəllərə dəyir."""
    sql = _executable_sql()
    targets = {
        match.group(1) for match in re.finditer(r"ALTER\s+TABLE\s+([\w%]+)", sql, re.IGNORECASE)
    }
    allowed = {*NEW_TABLES, "employees", "%I"}
    assert targets <= allowed, f"Gözlənilməyən `ALTER TABLE` hədəfi: {sorted(targets - allowed)}"


def test_employees_is_only_extended_with_add_column_if_not_exists() -> None:
    """`employees` üzərində YALNIZ idempotent sütun əlavəsi olmalıdır."""
    sql = re.sub(r"\s+", " ", _executable_sql())
    statement = re.search(r"ALTER TABLE employees ADD COLUMN[^;]*;", sql, re.IGNORECASE)
    assert statement is not None, "`employees` sütun əlavəsi tapılmadı"
    for column in NEW_EMPLOYEE_COLUMNS:
        assert f"ADD COLUMN IF NOT EXISTS {column}" in statement.group(0), (
            f"`employees.{column}` idempotent şəkildə əlavə edilmir — ikinci icra çökər."
        )


# --------------------------------------------------------------------------- #
# 3. Biometrik məlumatın dörd qaydası
# --------------------------------------------------------------------------- #


def test_no_column_anywhere_stores_a_photo_or_a_frame() -> None:
    """FOTO SAXLANMIR — nə `BYTEA`, nə şəkil/kadr yolu sütunu.

    `BYTEA` axtarışı qəsdən bütün fayl üzrədir: bir yerdə görünsə belə,
    "vektoru xam saxlayaq" qərarı sükutla geri qayıdıb deməkdir.
    """
    sql = _executable_sql()
    assert not re.search(r"\bBYTEA\b", sql, re.IGNORECASE), (
        "`BYTEA` sütunu var — biometrik xam məlumat saxlanır ola bilər."
    )
    for table in NEW_TABLES:
        for column in _columns(table):
            assert not re.search(r"photo|image|frame|snapshot", column, re.IGNORECASE), (
                f"`{table}.{column}` kadr/şəkil saxlayan sütuna oxşayır — foto SAXLANMIR."
            )


@pytest.mark.parametrize(
    ("table", "column"),
    [("employees", "face_embedding"), ("face_embedding_history", "face_embedding")],
)
def test_every_embedding_column_documents_that_it_is_encrypted(table: str, column: str) -> None:
    """Şifrələmə sütun şərhində AÇIQ yazılmalıdır.

    Sxem sənədi olmadan növbəti mühəndis sütunu adi mətn kimi doldurar və
    heç bir test bunu tutmaz — çünki tip eynidir (`TEXT`).
    """
    sql = _executable_sql()
    comment = re.search(
        rf"COMMENT\s+ON\s+COLUMN\s+{table}\.{column}\s+IS\s+(.*?);", sql, re.DOTALL | re.IGNORECASE
    )
    assert comment is not None, f"`{table}.{column}` üçün `COMMENT ON COLUMN` yoxdur"
    assert "ŞİFRƏLƏNMİŞ" in comment.group(1), (
        f"`{table}.{column}` şərhi şifrələməni yazmır — sütun adi mətn kimi doldurula bilər."
    )


def test_the_live_embedding_column_explains_the_multi_frame_average() -> None:
    """Bənd 11: dəyər TƏK kadrdan deyil, kadrların RİYAZİ ORTASINDAN gəlir.

    Bu, Faza 2/3 üçün struktur göstərişdir: sütun bir kadrın embedding-i ilə
    doldurulsa, sxem formal olaraq düzgün, sistem isə keyfiyyətcə zəif olardı.
    """
    sql = _executable_sql()
    comment = re.search(
        r"COMMENT\s+ON\s+COLUMN\s+employees\.face_embedding\s+IS\s+(.*?);", sql, re.DOTALL
    )
    assert comment is not None
    assert "RİYAZİ ORTASIDIR" in comment.group(1), (
        "`employees.face_embedding` şərhi çox-kadr ortalamasını (bənd 11) izah etmir."
    )


def test_the_verification_log_never_stores_an_embedding() -> None:
    """Jurnalda vektor OLMAMALIDIR — əks halda ikinci biometrik nüsxə yaranardı."""
    columns = _columns("face_verification_log")
    assert "face_embedding" not in columns
    assert not [c for c in columns if "embedding" in c or "vector" in c], (
        "`face_verification_log` vektor saxlayır — bənd 8-in silmə qaydası mənasız olardı."
    )
    assert "confidence_score" in columns, "Bənd 12 — nəticə binar deyil, bal saxlanılmalıdır."


def test_the_archive_cannot_claim_a_purge_while_keeping_the_vector() -> None:
    """`PURGED` statusu vektorun `NULL` olmasını MƏCBUR edir (bənd 8 + bənd 2).

    Yalnız `employees.face_embedding`-i təmizləmək kifayət etməzdi: arxiv
    köhnə vektorları saxlayır və biometrik məlumat orada yaşamağa davam edərdi.
    """
    body = re.sub(r"\s+", " ", _table_body("face_embedding_history"))
    assert "CHECK ((status = 'PURGED') = (face_embedding IS NULL))" in body, (
        "Arxivdə `PURGED` statusu vektorun silinməsinə bağlanmayıb."
    )
    assert "'REPLACED'" in body, "Bənd 2 — köhnə vektor `REPLACED` statusu ilə arxivlənməlidir."


# --------------------------------------------------------------------------- #
# 4. MISMATCH sayğacı — PIN-dən TAM AYRI (bənd 3)
# --------------------------------------------------------------------------- #


def test_the_mismatch_counter_follows_the_existing_pin_lockout_pattern() -> None:
    """Sayğac `employees` sütunudur — mövcud PIN naxışının eynisi.

    `schema.sql` §7 PIN sayğacını ayrıca kredensial cədvəlində DEYİL,
    `employees.pin_failed_attempts`/`pin_locked_until` sütunlarında saxlayır.
    Ayrıca cədvəl hər kiosk əməliyyatına bir JOIN əlavə edərdi.
    """
    schema = (PROJECT_ROOT / "database" / "schema.sql").read_text(encoding="utf-8")
    assert "pin_failed_attempts" in schema and "pin_locked_until" in schema, (
        "Mövcud PIN naxışı tapılmadı — bu qapının fərziyyəsi yoxa çıxır."
    )
    sql = re.sub(r"\s+", " ", _executable_sql())
    assert "ADD COLUMN IF NOT EXISTS face_mismatch_attempts SMALLINT NOT NULL DEFAULT 0" in sql
    assert "ADD COLUMN IF NOT EXISTS face_locked_until TIMESTAMPTZ" in sql


def test_the_mismatch_counter_is_a_separate_column_from_the_pin_counter() -> None:
    """PIN sayğacına TOXUNULMUR — iki sayğac ayrı sütunlarda yaşayır.

    Bənd 3: `NO_FACE_DETECTED` PIN-lockout sayğacına DAXİL EDİLMİR. Sütunları
    birləşdirsəydik, işıqsız dəhlizdə duran vicdanlı işçi üç cəhddən sonra
    kilidlənərdi — sistem "təhlükəsiz" görünüb faktiki olaraq işi dayandırardı.

    SƏTİR SABİTLƏRİ MASKALANIR: `COMMENT ON COLUMN` mətnləri icra olunan
    SQL-in bir hissəsidir və PIN sütunlarının ADINI izah məqsədilə çəkir.
    Maskalamasaq, sənədləşməni yaxşılaşdırmaq bu qapını qırardı — yəni qapı
    yaxşı şərh yazmağı cəzalandırardı.
    """
    sql = _masked_string_literals(_executable_sql())
    assert "pin_failed_attempts" not in sql, "Mövcud PIN sayğacına toxunulur!"
    assert "pin_locked_until" not in sql, "Mövcud PIN kilid sütununa toxunulur!"


def test_the_log_records_which_failure_mode_occurred() -> None:
    """İki uğursuzluq rejimi sxem səviyyəsində AYRI dəyərlərdir."""
    body = re.sub(r"\s+", " ", _table_body("face_verification_log"))
    match = re.search(r"result\s+IN\s*\(([^)]*)\)", body)
    assert match is not None, "`result` üçün CHECK siyahısı tapılmadı"
    assert {v.strip().strip("'") for v in match.group(1).split(",")} == {
        "SUCCESS",
        "NO_FACE_DETECTED",
        "MISMATCH",
    }


def test_the_trigger_context_reuses_the_existing_step_vocabulary() -> None:
    """`STEP_A`/`STEP_1`/`STEP_2` mövcud `_verified_now(operation=...)` sözlüyüdür.

    Yeni ad məkanı qurmaq `menu.py` başlığındakı qüsurun eynisi olardı: iki
    siyahı bir müddət üst-üstə düşər, sonra sükutla ayrılardı.
    """
    body = re.sub(r"\s+", " ", _table_body("face_verification_log"))
    match = re.search(r"trigger_context\s+IN\s*\(([^)]*)\)", body)
    assert match is not None, "`trigger_context` üçün CHECK siyahısı tapılmadı"
    assert {v.strip().strip("'") for v in match.group(1).split(",")} == {
        "STEP_A",
        "STEP_1",
        "STEP_2",
    }
    for source_name in ("morning_check_in.py", "leave_verification.py"):
        source = (PROJECT_ROOT / "src" / "application" / "use_cases" / source_name).read_text(
            encoding="utf-8"
        )
        assert 'operation="STEP' in source, (
            f"{source_name} artıq `STEP_*` sözlüyünü işlətmir — CHECK siyahısı ondan qopub."
        )


# --------------------------------------------------------------------------- #
# 5. İstisna (exemption) yolunun sərt qorumaları — bənd 14
# --------------------------------------------------------------------------- #


def test_an_exemption_must_carry_a_reason_and_an_expiry() -> None:
    """İstisna özü bir aldatma yoluna çevrilə bilər — ona görə iki sütun MƏCBURİDİR."""
    body = re.sub(r"\s+", " ", _table_body("face_control_exemptions"))
    assert "expires_at TIMESTAMPTZ NOT NULL" in body, (
        "`expires_at` `NULL` ola bilir — «müvəqqəti» istisna sükutla əbədi qalardı."
    )
    assert re.search(r"reason\s+TEXT\s+NOT\s+NULL\s+CHECK\s*\(\s*char_length", body), (
        "`reason` boş və ya absurd ola bilir — sənədləşməmiş boşluq müdafiə olunmur."
    )
    assert "CHECK (expires_at > granted_at)" in body, (
        "Sıfır/mənfi ömürlü istisna ekranda «aktiv» görünüb heç vaxt işləməzdi."
    )


def test_only_one_active_exemption_may_exist_per_employee() -> None:
    """Qismən unikal indeks: keçmiş sətirlər qalır, ikinci AKTİV sətir yaranmır."""
    sql = _executable_sql()
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ux_face_exemption_active" in sql
    assert re.search(
        r"ux_face_exemption_active\s+ON\s+face_control_exemptions\s*\(\s*tenant_id\s*,\s*"
        r"employee_id\s*\)\s*WHERE\s+status\s*=\s*'ACTIVE'",
        re.sub(r"\s+", " ", sql),
    ), "Aktiv istisna unikallığı qismən indekslə ifadə olunmayıb."


def test_the_exemption_status_list_is_exactly_the_specified_three() -> None:
    body = re.sub(r"\s+", " ", _table_body("face_control_exemptions"))
    match = re.search(
        r"status\s+TEXT\s+NOT\s+NULL\s+DEFAULT\s+'ACTIVE'\s+CHECK\s*\(\s*status"
        r"\s+IN\s*\(([^)]*)\)",
        body,
    )
    assert match is not None, "`status` üçün CHECK siyahısı tapılmadı"
    assert {v.strip().strip("'") for v in match.group(1).split(",")} == {
        "ACTIVE",
        "EXPIRED",
        "REVOKED",
    }


# --------------------------------------------------------------------------- #
# 6. İcazə flag-i — hardlock səviyyə 2 (bənd 14)
# --------------------------------------------------------------------------- #


def test_the_exemption_flag_is_locked_to_root_and_ceo() -> None:
    """`can_manage_employees` KİFAYƏT ETMİR — onun hardlock səviyyəsi 0-dır.

    Səviyyə 2 (`HardlockLevel.ROOT_CEO`) mövcud `enforce_permission_hardlock()`
    trigger-i və domen tərəfi (`PermissionFlag.assert_grantable_to`) tərəfindən
    AVTOMATİK tətbiq olunur — yeni guard yazılmır.
    """
    sql = re.sub(r"\s+", " ", _executable_sql())
    assert "'can_manage_face_exemptions'" in sql, "Flag kataloqa əlavə edilmir"
    assert "ON CONFLICT (code) DO NOTHING" in sql, (
        "Təkrar icrada Root-un redaktəsi üstündən yazılardı."
    )
    insert = re.search(
        r"INSERT INTO permission_flags.*?ON CONFLICT \(code\) DO NOTHING", sql, re.DOTALL
    )
    assert insert is not None
    assert re.search(r"2,\s*FALSE,\s*FALSE\)", insert.group(0)), (
        "Flag `hardlock_level = 2` ilə elan olunmur — HR-səviyyəli admin-ə həvalə edilə bilərdi."
    )


def test_the_exemption_flag_is_granted_to_root_and_ceo_only() -> None:
    """Defolt sahiblik YALNIZ Root/CEO — heç bir operativ rola sətir yazılmır."""
    sql = re.sub(r"\s+", " ", _executable_sql())
    grant = re.search(r"INSERT INTO position_permissions.*?ON CONFLICT DO NOTHING", sql, re.DOTALL)
    assert grant is not None, "Rol təyinatı tapılmadı"
    assert "WHERE p.code IN ('ROOT', 'CEO')" in grant.group(0)
    for role in ("HR_ADMIN", "ADMIN", "MAGAZA_MENECERI", "KAMERA_NEZARETCISI", "SATICI"):
        assert f"'{role}'" not in grant.group(0), (
            f"`{role}` roluna istisna səlahiyyəti verilir — bənd 14 «YALNIZ Root/CEO» deyir."
        )


# --------------------------------------------------------------------------- #
# 7. İstisna motoru — mövcud kataloqa seed (bənd 16)
# --------------------------------------------------------------------------- #


def test_face_mismatch_is_seeded_into_the_existing_exception_source_catalog() -> None:
    """Motorun KODU dəyişmir — yeni mənbə bir `INSERT`-dir (migrations/018 qərarı)."""
    sql = re.sub(r"\s+", " ", _executable_sql())
    assert "INSERT INTO exception_sources" in sql, "Yeni mənbə kataloqa yazılmır"
    assert "'FACE_MISMATCH'" in sql
    assert "'CRITICAL'" in sql, (
        "MISMATCH ən güclü fırıldaqçılıq siqnalıdır — ciddiyyəti `CRITICAL` olmalıdır."
    )
    assert not re.search(r"CREATE\s+TABLE[^;]*\bexception", sql, re.IGNORECASE), (
        "İstisna motoru üçün yeni cədvəl yaradılır — mövcud motor əvəz olunmamalıdır."
    )


# --------------------------------------------------------------------------- #
# 8. Çox-kirayəçilik, sənədləşmə, idempotentlik, tz-aware
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("table", NEW_TABLES)
def test_every_new_table_is_created_idempotently(table: str) -> None:
    sql = _executable_sql()
    assert re.search(rf"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+{table}\b", sql, re.IGNORECASE), (
        f"`{table}` `IF NOT EXISTS` olmadan yaradılır — ikinci icra çökər."
    )


@pytest.mark.parametrize("table", NEW_TABLES)
def test_every_new_table_carries_a_tenant_id(table: str) -> None:
    assert "tenant_id" in _columns(table), (
        f"`{table}` cədvəlində `tenant_id` yoxdur — izolyasiya mümkün deyil."
    )


@pytest.mark.parametrize("table", NEW_TABLES)
def test_every_new_table_enables_row_level_security(table: str) -> None:
    """RLS fail-closed (SEC-008) — biometrik cədvəldə bu, adi izolyasiyadan vacibdir."""
    sql = _executable_sql()
    direct = re.search(
        rf"ALTER\s+TABLE\s+{table}\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY", sql, re.IGNORECASE
    )
    in_loop = re.search(rf"'{table}'", sql) and "ENABLE ROW LEVEL SECURITY" in sql.upper()
    assert direct or in_loop, f"`{table}` üçün RLS işə salınmır."


@pytest.mark.parametrize("table", NEW_TABLES)
def test_every_new_table_gets_a_tenant_isolation_policy(table: str) -> None:
    sql = _executable_sql()
    direct = re.search(rf"CREATE\s+POLICY\s+tenant_isolation\s+ON\s+{table}\b", sql, re.IGNORECASE)
    in_loop = re.search(rf"'{table}'", sql) and "CREATE POLICY tenant_isolation ON %I" in sql
    assert direct or in_loop, f"`{table}` üçün `tenant_isolation` siyasəti yoxdur."
    assert "current_tenant_id()" in sql


@pytest.mark.parametrize("table", NEW_TABLES)
def test_every_new_table_is_documented(table: str) -> None:
    sql = _executable_sql()
    assert re.search(rf"COMMENT\s+ON\s+TABLE\s+{table}\s+IS", sql, re.IGNORECASE), (
        f"`{table}` üçün `COMMENT ON TABLE` yoxdur."
    )


@pytest.mark.parametrize("table", NEW_TABLES)
def test_every_new_column_is_documented(table: str) -> None:
    """Sənədsiz sütun bir il sonra "bu nə idi?" sualına çevrilir."""
    sql = _executable_sql()
    missing = [
        column
        for column in _columns(table)
        if not re.search(rf"COMMENT\s+ON\s+COLUMN\s+{table}\.{column}\s+IS", sql, re.IGNORECASE)
    ]
    assert not missing, f"`{table}` sütunları sənədsizdir: {missing}"


@pytest.mark.parametrize("column", NEW_EMPLOYEE_COLUMNS)
def test_every_new_employee_column_is_documented(column: str) -> None:
    sql = _executable_sql()
    assert re.search(rf"COMMENT\s+ON\s+COLUMN\s+employees\.{column}\s+IS", sql, re.IGNORECASE), (
        f"`employees.{column}` sənədsizdir."
    )


def test_all_time_columns_are_timezone_aware() -> None:
    """Naiv `TIMESTAMP` QADAĞANDIR (CLAUDE.md §4 — tz-aware qaydası)."""
    sql = _executable_sql()
    assert not re.search(r"\bTIMESTAMP\b(?!\s*TZ)", sql, re.IGNORECASE), (
        "Qurşaqsız `TIMESTAMP` var — yay/qış saatı keçidində səssiz sürüşmə verər."
    )


def test_indexes_are_created_idempotently() -> None:
    sql = _executable_sql()
    non_idempotent = [
        match.group(0)
        for match in re.finditer(r"CREATE\s+(UNIQUE\s+)?INDEX\s+(?!IF\s+NOT\s+EXISTS)\S+", sql)
    ]
    assert not non_idempotent, f"İdempotent olmayan indeks: {non_idempotent}"


def test_every_updated_at_column_has_a_trigger() -> None:
    """`updated_at` trigger olmadan ƏL İLƏ yenilənməli olardı — və unudulardı."""
    sql = _executable_sql()
    for table in NEW_TABLES:
        if "updated_at" not in _columns(table):
            continue
        assert re.search(rf"CREATE\s+TRIGGER\s+\w+\s+BEFORE\s+UPDATE\s+ON\s+{table}\b", sql), (
            f"`{table}.updated_at` üçün trigger bağlanmayıb."
        )


# --------------------------------------------------------------------------- #
# 9. GRANT / REVOKE — `ALTER DEFAULT PRIVILEGES` `DELETE`-i avtomatik verir
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "table", ("face_embedding_history", "face_control_exemptions", "face_control_store_scope")
)
def test_evidence_tables_deny_delete_to_the_application_role(table: str) -> None:
    """Açıq `REVOKE` MƏCBURİDİR (migrations/018-in izahı).

    `schema.sql` §28 `ALTER DEFAULT PRIVILEGES` ilə hər YENİ cədvələ `DELETE`
    verir — dar `GRANT` tək başına heç nə məhdudlaşdırmır.
    """
    sql = re.sub(r"\s+", " ", _executable_sql()).replace("' '", "")
    revoke = re.search(r"REVOKE DELETE ON ([^']*?) FROM", sql)
    assert revoke is not None, "Heç bir `REVOKE DELETE` yoxdur"
    assert table in revoke.group(1), f"`{table}` üçün `DELETE` geri alınmır."


def test_the_verification_log_may_be_pruned_but_never_edited() -> None:
    """Qəsdli asimmetriya: bənd 17 silməni TƏLƏB edir, redaktə isə saxtakarlıqdır.

    Jurnal sətri FAKTdır — `UPDATE` icazəsi kiməsə MISMATCH-i sonradan
    SUCCESS-ə çevirmək imkanı verərdi. Saxlama müddəti təmizləməsi isə
    spesifikasiyanın açıq tələbidir və həmin gecəlik iş bu rolla işləyir.
    """
    sql = re.sub(r"\s+", " ", _executable_sql()).replace("' '", "")
    assert "GRANT SELECT, INSERT, DELETE ON face_verification_log" in sql, (
        "Saxlama müddəti təmizləməsi (bənd 17) üçün `DELETE` verilməyib."
    )
    assert "REVOKE UPDATE ON face_verification_log" in sql, (
        "Jurnal sətri redaktə edilə bilir — MISMATCH sonradan SUCCESS-ə çevrilə bilərdi."
    )


# --------------------------------------------------------------------------- #
# 10. Doqquz ROOT parametri — zəncirin hər halqası
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("key", FACE_LIMIT_KEYS, ids=lambda k: k.value)
def test_every_face_parameter_has_a_default(key: SystemLimitKey) -> None:
    """Defoltsuz açar ROOT ekranını `KeyError` ilə çökdürür."""
    assert key in DEFAULT_LIMITS, f"`{key.value}` üçün `DEFAULT_LIMITS` sətri yoxdur"


@pytest.mark.parametrize("key", FACE_LIMIT_KEYS, ids=lambda k: k.value)
def test_every_face_parameter_is_seeded_for_old_and_new_tenants(key: SystemLimitKey) -> None:
    """Mövcud kirayəçilər `INSERT`-lə, yenilər trigger-lə — hər ikisi lazımdır.

    Yalnız birini yazsaydıq, ya köhnə bazada sətir yaranmazdı (Root GUI-dan
    dəyişə bilməzdi), ya da yeni kirayəçi parametrsiz qalardı.
    """
    sql = _executable_sql()
    assert sql.count(f"'{key.value}'") >= 2, (
        f"«{key.value}» ya mövcud, ya da yeni kirayəçilər üçün seed edilməyib"
    )


def test_the_new_tenant_trigger_does_not_touch_seed_tenant_defaults() -> None:
    """`seed_tenant_defaults()` `schema.sql` §24-dədir və TƏK mənbədir.

    Sətir sabitləri maskalanır: funksiyanın `COMMENT`-i ona QƏSDƏN istinad
    edir («toxunulmadan qalır») və bu, pozuntu deyil, sənədləşmədir.
    """
    sql = _masked_string_literals(_executable_sql())
    assert "seed_face_control_limits_for_new_tenant" in sql
    assert "trg_seed_face_control_limits" in sql
    assert "seed_tenant_defaults" not in sql, (
        "`seed_tenant_defaults()` dəyişdirilir — `schema.sql` tək mənbə olmaqdan çıxar."
    )


@pytest.mark.parametrize("key", FACE_LIMIT_KEYS, ids=lambda k: k.value)
def test_every_face_parameter_is_idempotently_seeded(key: SystemLimitKey) -> None:
    """`ON CONFLICT DO NOTHING` — Root-un dəyişdirdiyi dəyər üstündən yazılmır."""
    sql = _executable_sql()
    assert sql.count("ON CONFLICT (tenant_id, limit_key) DO NOTHING") >= 2, (
        "Seed sətirləri təkrar icrada Root-un dəyərini üstündən yazardı."
    )


def test_the_numeric_defaults_sit_inside_their_declared_range() -> None:
    """Defolt öz `min_value`/`max_value` aralığından kənarda ola bilməz.

    Belə sətir ROOT ekranında ilk açılışda «yanlış dəyər» kimi görünər və
    Root heç nə dəyişməmiş formanı saxlaya bilməzdi.
    """
    sql = re.sub(r"\s+", " ", _executable_sql())
    for key in FACE_LIMIT_KEYS:
        row = re.search(
            rf"\('{key.value}',\s*'([^']*)',\s*'(INTEGER|DECIMAL|TEXT)',\s*"
            rf"(NULL|'[^']*'),\s*(NULL|'[^']*')",
            sql,
        )
        assert row is not None, f"`{key.value}` seed sətri tapılmadı"
        value, value_type, minimum, maximum = row.groups()
        assert value == DEFAULT_LIMITS[key], (
            f"`{key.value}`: SQL defoltu ({value}) `DEFAULT_LIMITS` ({DEFAULT_LIMITS[key]}) "
            "ilə üst-üstə düşmür — kod və baza fərqli cavab verərdi."
        )
        if value_type == "TEXT":
            assert minimum == "NULL" and maximum == "NULL", (
                f"`{key.value}` kataloq dəyəridir — ədədi diapazon mənasızdır."
            )
            continue
        assert float(minimum.strip("'")) <= float(value) <= float(maximum.strip("'")), (
            f"`{key.value}` defoltu öz diapazonundan kənardadır."
        )


def test_the_low_confidence_band_is_not_inverted_by_default() -> None:
    """Aşağı-etibar həddi bənzərlik həddindən BÖYÜK olsaydı, zolaq tərsinə dönərdi.

    İki AYRI `system_limits` sətri olduğu üçün bunu `CHECK` ilə ifadə etmək
    mümkün deyil — ən azı DEFOLT vəziyyətin doğru olması qapı ilə saxlanılır.
    """
    low = float(DEFAULT_LIMITS[SystemLimitKey.FACE_LOW_CONFIDENCE_TOLERANCE])
    match = float(DEFAULT_LIMITS[SystemLimitKey.FACE_MATCH_TOLERANCE])
    assert low < match, "Defolt halda «aşağı-etibarlı» zolaq mövcud deyil — bənd 12 işləməzdi."


def test_the_match_tolerance_default_is_the_documented_library_value() -> None:
    """0.60 `face_recognition` (Dlib) sənədləşməsindəki defolt `tolerance`-dır.

    Ədəd QƏSDƏN "yaxşılaşdırılmır": kitabxananın öz tövsiyəsindən sapmaq üçün
    ölçmə lazımdır, ölçmə isə pilot mağazada olacaq (facecontrol.md, THRESHOLD
    bölməsi).
    """
    assert DEFAULT_LIMITS[SystemLimitKey.FACE_MATCH_TOLERANCE] == "0.60"


def test_the_lockout_threshold_is_independent_from_the_pin_threshold() -> None:
    """Bənd 4: üz həddi PIN həddindən AYRI açardır və daha aşağı ola bilər."""
    face = int(DEFAULT_LIMITS[SystemLimitKey.FACE_MISMATCH_LOCKOUT_THRESHOLD])
    pin = int(DEFAULT_LIMITS[SystemLimitKey.PIN_MAX_FAILED_ATTEMPTS])
    assert (
        SystemLimitKey.FACE_MISMATCH_LOCKOUT_THRESHOLD is not SystemLimitKey.PIN_MAX_FAILED_ATTEMPTS
    )
    assert face <= pin, (
        "Üz uyğunsuzluğu PIN səhvindən daha güclü siqnaldır — həddi ondan yuxarı olmamalıdır."
    )


def test_no_new_lockout_duration_parameter_was_invented() -> None:
    """Bənd 4: lockout MEXANİZMİ təkrar yazılmır — `PIN_LOCKOUT_MINUTES` çağırılır.

    Yeni müddət açarı yaratmaq iki paralel kilid mexanizmi demək olardı və
    "hansı müddət tətbiq olundu?" sualı auditdə cavabsız qalardı.
    """
    invented = [key.value for key in SystemLimitKey if key.value.startswith("FACE_LOCKOUT")]
    assert not invented, f"Yeni kilid müddəti açarı yaradılıb: {invented}"


def test_the_store_scope_is_a_child_table_not_a_comma_list() -> None:
    """Bənd 15 — mağaza siyahısı FK-lı uşaq cədvəldir (`announcement_targets` naxışı).

    Vergüllü `system_limits` sətri FK verə bilməzdi: bir simvol səhv yazılsa,
    Face Control həmin mağazada SÜKUTLA sönərdi (fail-open) və heç bir qapı
    bunu tutmazdı.
    """
    body = re.sub(r"\s+", " ", _table_body("face_control_store_scope"))
    assert "store_id UUID NOT NULL REFERENCES stores(id)" in body, (
        "Mağaza əhatəsi real `FOREIGN KEY` ilə bağlanmır."
    )
    assert "UNIQUE (tenant_id, store_id)" in body
    scope_keys = [
        key.value for key in SystemLimitKey if "FACE" in key.value and "STORE" in key.value
    ]
    assert not scope_keys, f"Mağaza siyahısı `system_limits`-ə də yazılıb: {scope_keys}"


def test_the_global_feature_toggle_mechanism_is_untouched() -> None:
    """Qlobal toggle cədvəlinə TOXUNULMUR — bu cədvəl onun üstündə süzgəcdir.

    Sətir sabitləri maskalanır: cədvəl şərhi qlobal mexanizmin adını qəsdən
    çəkir ki, oxuyan onların münasibətini bilsin.
    """
    sql = _masked_string_literals(_executable_sql())
    assert "feature_toggles" not in sql, (
        "`feature_toggles` cədvəlinə toxunulur — bənd 15 qlobal mexanizmi qorumağı tələb edir."
    )
