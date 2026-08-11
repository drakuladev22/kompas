"""Domen ↔ DB trigger PARİTETİ — Self-Escalation Guard (CLAUDE.md §5).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TEST STATİK MƏTN ÜZƏRİNDƏ İŞLƏYİR
──────────────────────────────────────────────────────────────────────────────
Trigger-lər yalnız canlı PostgreSQL-də icra olunur; vahid testlərdə isə fake
repo-lar var, yəni `database/tests/test_guards.sql` YALNIZ CI-dakı `db-schema`
job-unda işləyir. Aradakı boşluq real qüsura çevrilmişdi: iki struktur qayda
domendə mövcud, DB tərəfində isə YOX idi və heç bir test bunu görmürdü, çünki
"testlər yaşıldır" — sadəcə həmin qatı heç kim yoxlamırdı.

Bu modul məhz o boşluğu bağlayır: SQL mənbələrini oxuyur və qaydanın DB
tərəfində HƏLƏ DƏ mövcud olduğunu təsdiqləyir. Sintaksisi icra etmir (bunu CI
edir) — sual "qayda İKİ yerdədirmi", cavab isə mətndən oxunur.

Yoxlanan iki tapıntı (anti-fraud auditi):
    1. `_assert_actor_owns_flag` (aktor özündə olmayan flag-i verə bilməz) —
       DB-də qarşılığı yox idi → `enforce_grantor_owns_flag()` (migration 014).
    2. `_assert_not_self` effektdən asılı deyil, DB isə yalnız `GRANT`-ı
       bloklayırdı → `enforce_self_escalation_guard()` genişləndirildi.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Final

import pytest

from src.application.use_cases.permission_guards import PermissionHierarchyGuardUseCase

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA_FILE: Final = PROJECT_ROOT / "database" / "schema.sql"
MIGRATIONS_DIR: Final = PROJECT_ROOT / "database" / "migrations"

OWNS_FLAG_FUNCTION: Final = "enforce_grantor_owns_flag"
SELF_GUARD_FUNCTION: Final = "enforce_self_escalation_guard"

OVERRIDE_TABLE: Final = "user_permission_overrides"
POSITION_TABLE: Final = "position_permissions"

#: `CREATE OR REPLACE FUNCTION ad() ... $$ gövdə $$ LANGUAGE plpgsql`
_FUNCTION_RE: Final = re.compile(
    r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+(?P<name>\w+)\s*\(\s*\)"
    r".*?\$\$(?P<body>.*?)\$\$\s*LANGUAGE\s+plpgsql",
    re.DOTALL | re.IGNORECASE,
)

#: `CREATE TRIGGER ad ... ON cədvəl ... EXECUTE FUNCTION funksiya()`
_TRIGGER_RE: Final = re.compile(
    r"CREATE\s+TRIGGER\s+\w+\s+(?P<timing>BEFORE|AFTER)\s+(?P<events>[\w\s]+?)"
    r"\s+ON\s+(?P<table>\w+)\s+FOR\s+EACH\s+ROW\s+EXECUTE\s+FUNCTION\s+(?P<func>\w+)\s*\(\s*\)",
    re.DOTALL | re.IGNORECASE,
)

_LINE_COMMENT_RE: Final = re.compile(r"--[^\n]*")


def _strip_comments(sql: str) -> str:
    """`--` şərhlərini atır.

    ŞƏRHLƏRİN ATILMASI MƏCBURİDİR: miqrasiya faylları sonunda ŞƏRHƏ ALINMIŞ
    DOWN bloku saxlayır (CLAUDE.md §7) və orada funksiyanın KÖHNƏ (dar)
    variantı yazılıdır. Şərhlər atılmasa, "sonuncu tərif" kimi məhz DOWN
    blokundakı köhnə gövdə tapılar və test yanlış nəticə verərdi.

    Sadə yanaşma sətir literalının içindəki `--` ardıcıllığını da kəsərdi;
    bu SQL fayllarında belə literal YOXDUR (tire kimi `—` işlədilir), ona görə
    tam SQL parser-i gətirmək əsassız mürəkkəblik olardı.
    """
    return _LINE_COMMENT_RE.sub("", sql)


def _sql_sources() -> list[tuple[str, str]]:
    """(fayl adı, şərhsiz məzmun) — TƏTBİQ SIRASI ilə: schema.sql, sonra 001…NNN."""
    paths = [SCHEMA_FILE, *sorted(MIGRATIONS_DIR.glob("*.sql"))]
    return [(path.name, _strip_comments(path.read_text(encoding="utf-8"))) for path in paths]


def _effective_functions() -> dict[str, str]:
    """Hər funksiyanın SONUNCU (yəni qüvvədə olan) gövdəsi.

    `CREATE OR REPLACE` semantikası budur: sonrakı fayl əvvəlkini üstələyir.
    """
    bodies: dict[str, str] = {}
    for _name, sql in _sql_sources():
        for match in _FUNCTION_RE.finditer(sql):
            bodies[match.group("name").lower()] = match.group("body")
    return bodies


def _trigger_bindings() -> set[tuple[str, str]]:
    """(cədvəl, funksiya) cütləri — bütün fayllar üzrə."""
    bindings: set[tuple[str, str]] = set()
    for _name, sql in _sql_sources():
        for match in _TRIGGER_RE.finditer(sql):
            bindings.add((match.group("table").lower(), match.group("func").lower()))
    return bindings


def _require_function(function_name: str) -> str:
    """Qüvvədə olan gövdə — funksiya ümumiyyətlə yoxdursa AYDIN mesajla dayanır."""
    bodies = _effective_functions()
    if function_name not in bodies:
        pytest.fail(
            f"'{function_name}' funksiyası nə `schema.sql`-də, nə də miqrasiyalarda "
            f"tapılmadı — struktur zəmanətin DB yarısı silinib (CLAUDE.md §5)"
        )
    return bodies[function_name]


def _normalise(body: str) -> str:
    """Müqayisə üçün: boşluqlar tək aralığa yığılır."""
    return " ".join(body.split())


def _function_in(file_name: str, function_name: str) -> str:
    """Konkret faylda təyin olunmuş funksiya gövdəsi."""
    for name, sql in _sql_sources():
        if name != file_name:
            continue
        for match in _FUNCTION_RE.finditer(sql):
            if match.group("name").lower() == function_name:
                return match.group("body")
    pytest.fail(f"'{function_name}' funksiyası '{file_name}' faylında tapılmadı")


# --------------------------------------------------------------------------- #
# Qapı: mənbələr oxunmasa aşağıdakı testlər yanlış olaraq "keçər"
# --------------------------------------------------------------------------- #


def test_sql_sources_are_readable() -> None:
    assert SCHEMA_FILE.exists(), f"schema.sql tapılmadı: {SCHEMA_FILE}"
    assert MIGRATIONS_DIR.exists(), f"Miqrasiya qovluğu tapılmadı: {MIGRATIONS_DIR}"
    assert _effective_functions(), "SQL mənbələrində heç bir plpgsql funksiyası tapılmadı"


# --------------------------------------------------------------------------- #
# TAPINTI 2 — özünə toxunma effektdən asılı olmamalıdır
# --------------------------------------------------------------------------- #


def test_self_escalation_guard_exists_on_the_override_table() -> None:
    assert (OVERRIDE_TABLE, SELF_GUARD_FUNCTION) in _trigger_bindings(), (
        "Self-Escalation Guard trigger-i `user_permission_overrides`-dan qopub"
    )


def test_self_escalation_guard_blocks_both_effects() -> None:
    """DB `GRANT` VƏ `DENY` — hər ikisini bloklamalıdır.

    Domen `_assert_not_self` effektə ÜMUMİYYƏTLƏ baxmır. DB-də isə
    `AND NEW.effect = 'GRANT'` şərti var idi: aktor özünə `DENY` sətri yaza
    bilirdi. `UNIQUE (user_id, flag_code)` səbəbindən həmin sətir sonrakı
    `UPDATE` üçün "tutulmuş yer" olurdu və `granted_by` aktorun özü qalırdı —
    yəni audit izində icazəni kimin dəyişdiyi cavabsız qalırdı.
    """
    body = _require_function(SELF_GUARD_FUNCTION)

    assert "NEW.granted_by = NEW.user_id" in body, (
        "Özünə toxunma yoxlaması gövdədən çıxıb — Self-Escalation Guard işləmir"
    )
    assert "= 'GRANT'" not in body, (
        "Self-Escalation Guard yenidən `effect = 'GRANT'` şərtinə bağlanıb — "
        "domen (`_assert_not_self`) isə hər iki effekti bloklayır (CLAUDE.md §5)"
    )


# --------------------------------------------------------------------------- #
# TAPINTI 1 — səlahiyyət verən həmin flag-ə sahib olmalıdır
# --------------------------------------------------------------------------- #


def test_grantor_ownership_trigger_covers_both_write_paths() -> None:
    """Fərdi override VƏ rol-defolt — hər iki yazı yolu bağlı olmalıdır.

    Yalnız override tərəfi bağlansaydı, qadağa bir addımla yan keçilərdi:
    "özümdə olmayan flag-i custom rola qoyum, sonra o rolu hədəfə təyin edim"
    (bax `position_management._apply_flags` — domen məhz buna görə İKİ yerdə
    eyni yoxlamanı aparır).
    """
    bindings = _trigger_bindings()
    assert (OVERRIDE_TABLE, OWNS_FLAG_FUNCTION) in bindings, (
        "`user_permission_overrides` üzərində sahiblik trigger-i yoxdur"
    )
    assert (POSITION_TABLE, OWNS_FLAG_FUNCTION) in bindings, (
        "`position_permissions` üzərində sahiblik trigger-i yoxdur"
    )


def test_grantor_ownership_mirrors_the_domain_semantics() -> None:
    """SQL gövdəsi `_assert_actor_owns_flag` + `has_permission` ilə eyni olmalıdır."""
    body = _require_function(OWNS_FLAG_FUNCTION)

    # Geri alma yoxlanılmır — icazəni GERİ ALMAQ səlahiyyət artırması deyil.
    assert "NEW.effect <> 'GRANT'" in body, "Override tərəfində DENY istisnası itib"
    assert "NOT NEW.granted" in body, "Rol tərəfində `granted = FALSE` istisnası itib"

    # Root istisnası — domendə `effective_system_role is SystemRole.ROOT`,
    # yəni MƏHZ `ROOT` kodu (prioritet 0-lı custom rol CEO semantikasına düşür).
    assert "v_actor_code = 'ROOT'" in body, "Root istisnası itib — kamera rolu quraşdırıla bilməz"

    # Sahiblik İKİ qatın birləşməsidir və vaxtı keçmiş override sayılmır.
    assert OVERRIDE_TABLE in body, "Fərdi override qatı hesablamadan çıxıb"
    assert POSITION_TABLE in body, "Rol-defolt qatı hesablamadan çıxıb"
    assert "expires_at" in body, "Vaxtı keçmiş override hələ də sahiblik sayılır"


def test_seed_and_bootstrap_path_stays_open() -> None:
    """`granted_by IS NULL` (sistem seed-i) AÇIQ qalmalıdır.

    §23 (rol → flag defolt təyinatı), §24 (`seed_tenant_defaults`) və §25 (DEV
    tenant) `position_permissions` sətirlərini "verən" olmadan yazır — o anda
    hələ heç bir işçi mövcud deyil. İstisna itsəydi tenant ümumiyyətlə qurula
    bilməzdi: ilk Root-un rolu da flag-lərini məhz seed-dən alır.
    """
    body = _require_function(OWNS_FLAG_FUNCTION)

    assert "v_actor := NEW.granted_by" in body
    assert "v_actor IS NULL" in body, (
        "Sistem seed-i üçün `granted_by IS NULL` istisnası itib — "
        "yeni tenant quraşdırması trigger-ə ilişəcək"
    )


def test_identical_row_rewrite_is_not_treated_as_a_new_grant() -> None:
    """Dəyişməyən sətrin təkrar yazılışı bloklanmamalıdır.

    `EmployeeRepository._sync_overrides()` və `PositionRepository._sync_flags()`
    HƏR yazılışda bütün sətirləri yenidən UPSERT edir. Bu qaydanın nəticəsi isə
    ÜÇÜNCÜ şəxsin — səlahiyyəti verənin — SONRAKI vəziyyətindən asılıdır. İstisna
    olmasaydı belə zəncir yaranardı: Admin qanuni şəkildə flag verir → Admin-in
    həmin flag-i geri alınır → artıq həmin işçinin adını redaktə etmək belə
    mümkün olmur. Domen də mövcud sətrin təkrar yazılışını yoxlamır, ona görə
    istisna İKİ qatı ayırmır, əksinə eyniləşdirir.
    """
    body = _require_function(OWNS_FLAG_FUNCTION)

    assert "IS NOT DISTINCT FROM NEW.granted_by" in body, (
        "İdempotent təkrar yazılış istisnası itib — mövcud override sətri olan "
        "işçinin adi redaktəsi trigger-ə ilişəcək"
    )


@pytest.mark.parametrize("function_name", [OWNS_FLAG_FUNCTION, SELF_GUARD_FUNCTION])
def test_schema_and_migration_definitions_are_identical(function_name: str) -> None:
    """`schema.sql` (tək başına quraşdırma) ilə miqrasiya EYNİ qaydanı verməlidir.

    CLAUDE.md §7: `schema.sql` təkbaşına tam quraşdırmadır, miqrasiyalar isə
    onun üstünə qatlanır. İki tərif ayrılsaydı, təzə quraşdırılan baza ilə
    yenilənmiş baza FƏRQLİ təhlükəsizlik qaydaları ilə işləyərdi — və bu fərq
    yalnız insidentdə üzə çıxardı.
    """
    schema_body = _function_in("schema.sql", function_name)
    migration_body = _function_in("014_self_escalation_db_parity.sql", function_name)

    assert _normalise(schema_body) == _normalise(migration_body), (
        f"'{function_name}' schema.sql və migration 014-də FƏRQLİ yazılıb"
    )


# --------------------------------------------------------------------------- #
# Paritetin DOMEN tərəfi — biri silinsə, cüt qırılır
# --------------------------------------------------------------------------- #


def test_domain_half_of_the_rule_is_still_wired() -> None:
    """DB tərəfi domenin ƏVƏZİ deyil, TAMAMLAYICISIDIR.

    Bu test qəsdən `assert_allowed`-un mənbəyinə baxır: qaydanın domen yarısı
    silinsə (məs. "trigger onsuz da tutur" mülahizəsi ilə), GUI istifadəçiyə
    izahlı istisna əvəzinə `psycopg` xətası göstərərdi — CLAUDE.md §6-dakı
    "səlahiyyət yoxlaması açıq istisna atır" naxışı pozulardı.
    """
    source = inspect.getsource(PermissionHierarchyGuardUseCase.assert_allowed)

    assert "_assert_not_self" in source, "Domen tərəfi: özünə toxunma yoxlaması çağırılmır"
    assert "_assert_actor_owns_flag" in source, "Domen tərəfi: flag sahibliyi yoxlanılmır"
