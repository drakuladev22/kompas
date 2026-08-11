"""İngiliscə sızmanın reqressiya qapısı — Faza 8 (lokalizasiya).

Bölmə 9 yeganə interfeys dilini Azərbaycan dili kimi təyin edir. Buna
baxmayaraq maketdən köçürülən mətnlərdə İngiliscə sözlər qaldı və onlar
İKİ yolla gizləndi:

  1. Cədvəl sütun başlıqları (`Column("Status")`) — ekran açılmadan görünmür,
     ona görə heç bir mövcud test onlara toxunmurdu.
  2. Menyu maddələri (`title_az="Dashboard"`) — `test_menu_registry.py` yalnız
     `key`, `order`, `icon` və `required_flag` sahələrini yoxlayırdı; başlıq
     mətni heç kim tərəfindən yoxlanılmırdı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ MƏTN YOXLAMASI, TƏRCÜMƏ FAYLI DEYİL
──────────────────────────────────────────────────────────────────────────────
`i18n/catalog_az.py` mövcuddur, lakin `Translator` hazırda heç yerdə
çağırılmır — ekranlar mətni BİRBAŞA yazır. Yəni kataloqu təmiz saxlamaq tək
başına kifayət deyil; sızma canlı kodda baş verir. Ona görə qapı mənbə kodun
ÖZÜNÜ oxuyur və `Column(...)`/`MenuEntry(...)` başlıqlarını statik süzür.

Statik AST oxunuşu qəsdən seçilib: ekranı qurmaq üçün `QApplication` lazımdır
və `QT_QPA_PLATFORM=offscreen` olmayan mühitdə test tamamilə keçilməli olardı
(bax `CLAUDE.md` bölmə 2 — monospace şrift qeydi). Statik yoxlama isə hər
mühitdə işləyir.

──────────────────────────────────────────────────────────────────────────────
SİYAHI NİYƏ QAPALIDIR
──────────────────────────────────────────────────────────────────────────────
"İngiliscə söz varmı" sualına ümumi cavab vermək mümkün deyil: `KompasOS`,
`ERP`, `1C`, `PIN`, `Drive`, `Tenant`, `Plugin` qəsdən tərcümə OLUNMUR
(məhsul/domen adlarıdır, `kompasos.md` boyu belə işlənir). Ona görə qapı
YALNIZ artıq bir dəfə sızmış və Azərbaycanca qarşılığı qərara alınmış
sözləri bloklayır — yeni söz əlavə etmək şüurlu qərar tələb etsin.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

import pytest

from src.presentation.i18n.catalog_az import CATALOG_AZ
from src.presentation.shell.menu import DEFAULT_ENTRIES

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
SCREENS_DIR: Final = PROJECT_ROOT / "src" / "presentation" / "screens"
SCHEMA_FILE: Final = PROJECT_ROOT / "database" / "schema.sql"
SEED_MIGRATION: Final = PROJECT_ROOT / "database" / "migrations" / "017_i18n_seed_labels.sql"

#: `schema.sql`-in seed bölmələrinin sərhədləri (§21 → §26).
#: Yalnız bu aralıq süzülür: ondan yuxarıda `CREATE TABLE`/trigger gövdələri
#: var və orada `status`, `override` sözləri SÜTUN ADIDIR, tərcümə obyekti yox.
SEED_REGION_START: Final = "21. SEED: 7 DEFOLT ROL"
SEED_REGION_END: Final = "26. AUDIT LOG DƏYİŞMƏZLİYİ"

#: Tərcümə edilmiş və bir daha görünməməli olan sözlər.
#:
#: Hər biri üçün seçilmiş qarşılıq:
#:   Dashboard     → «İdarə Paneli» (mürəkkəb adlarda qısa forma «Panel»)
#:   Backup        → «Ehtiyat Nüsxə»
#:   Status        → «Vəziyyət»
#:   Override      → «İstisna» (icazə) / «vaxt düzəlişi» (manual vaxt)
#:   Dual-Control  → «Cüt Nəzarət»
#:   Control Center→ «İdarə Mərkəzi»
FORBIDDEN_WORDS: Final[tuple[str, ...]] = (
    "Dashboard",
    "Backup",
    "Status",
    "Override",
    "Dual-Control",
    "Dual Control",
    "Control Center",
)

#: Söz sərhədi ilə, böyük-kiçik hərfə həssas OLMADAN.
#: `\b` işlədilir ki, «Statusu» kimi Azərbaycan şəkilçili forma da tutulsun —
#: belə forma da sızmadır, sadəcə daha yaxşı gizlənir.
_FORBIDDEN_RE: Final = re.compile(
    "|".join(rf"\b{re.escape(word)}" for word in FORBIDDEN_WORDS),
    re.IGNORECASE,
)


#: Tək tokenli ad — identifikator şübhəsi (`DASHBOARD_BUILDER`,
#: `can_view_dashboard_builder`, `nav.dashboard`). Bunlar TƏRCÜMƏ OLUNMUR:
#: `FeatureModule`/`SystemLimitKey` dəyərləri və flag kodları ilə hərfi
#: uyğunluqda qalmalıdırlar, əks halda tətbiq bazadakı sətri tapa bilməz.
_IDENTIFIER_RE: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def _leak(text: str) -> str | None:
    """Qadağan olunmuş sözü qaytarır, yoxdursa `None`."""
    found = _FORBIDDEN_RE.search(text)
    return found.group(0) if found else None


def _column_titles() -> list[tuple[str, int, str]]:
    """Bütün ekran fayllarındakı `Column("...")` başlıqları.

    Yalnız BİRİNCİ mövqe arqumenti oxunur: `Column.__init__` imzasında
    `title` odur (`data_table.py`). `width`/`mono` ədəd və bayraqdır, mətn
    deyil.
    """
    titles: list[tuple[str, int, str]] = []
    for path in sorted(SCREENS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name != "Column" or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                titles.append((path.name, first.lineno, first.value))
    return titles


def test_column_titles_are_discoverable() -> None:
    """Qapı: AST axtarışı pozulsa, aşağıdakı test yanlış olaraq "keçər"."""
    titles = _column_titles()
    assert len(titles) > 50, f"Sütun başlıqları tapılmadı (yalnız {len(titles)} ədəd)"
    assert any(title == "Vəziyyət" for _f, _l, title in titles), (
        "«Vəziyyət» sütunu tapılmadı — axtarış səhv yerə baxır"
    )


def test_table_column_titles_have_no_english_leak() -> None:
    """Cədvəl sütun başlıqları Azərbaycan dilində olmalıdır."""
    leaks = [
        f"{file}:{line} «{title}» → «{word}»"
        for file, line, title in _column_titles()
        if (word := _leak(title)) is not None
    ]
    assert not leaks, "Sütun başlığında İngiliscə söz qaldı:\n" + "\n".join(leaks)


@pytest.mark.parametrize(
    "entry",
    DEFAULT_ENTRIES,
    ids=lambda entry: entry.key,  # type: ignore[misc]
)
def test_menu_titles_have_no_english_leak(entry) -> None:  # type: ignore[no-untyped-def]
    """Menyu başlığı istifadəçinin GÖRDÜYÜ ilk mətndir — sızma burada ən bahalıdır."""
    word = _leak(entry.title_az)
    assert word is None, (
        f"'{entry.key}' maddəsinin başlığında İngiliscə söz var: «{entry.title_az}» → «{word}»"
    )


def test_catalog_values_have_no_english_leak() -> None:
    """Kataloq hazırda işlədilmir, lakin qoşulanda sızmanı GERİ gətirməməlidir.

    Açarlar (`nav.dashboard`, `backup.now`) QƏSDƏN yoxlanılmır — onlar kod
    identifikatorudur və İngiliscə qalır (bax `CLAUDE.md` bölmə 4).
    """
    leaks = [
        f"{key} = «{value}» → «{word}»"
        for key, value in CATALOG_AZ.items()
        if (word := _leak(value)) is not None
    ]
    assert not leaks, "Kataloq dəyərində İngiliscə söz qaldı:\n" + "\n".join(leaks)


def test_terminology_is_consistent_between_menu_and_catalog() -> None:
    """Eyni ekran iki adla çağırılmamalıdır (menyu ↔ kataloq).

    Qüsurun tarixi: `menu.py` "ROOT Mərkəzi", `catalog_az.py` isə
    "ROOT Control Center" yazırdı. Kataloq bağlananda istifadəçi eyni
    ekranı iki fərqli adla görəcəkdi.
    """
    mismatches = [
        f"{entry.key}: menyu «{entry.title_az}» ↔ kataloq «{CATALOG_AZ[key]}»"
        for entry in DEFAULT_ENTRIES
        if (key := f"nav.{entry.key}") in CATALOG_AZ and CATALOG_AZ[key] != entry.title_az
    ]
    assert not mismatches, "Menyu və kataloq başlıqları fərqlidir:\n" + "\n".join(mismatches)


# --------------------------------------------------------------------------- #
# BAZA SEED ETİKETLƏRİ — mətnin İKİNCİ mənbəyi
# --------------------------------------------------------------------------- #
# Etiketlərin bir hissəsi kodda DEYİL, bazadadır: `permission_matrix.py:299`
# icazə adlarını `permission_flags.name_az`-dan oxuyur (tərcüməni ekranda
# təkrarlamamaq üçün — bax həmin faylın başlığı). Yəni Python tərəfini
# təmizləmək kifayət etmir; qapı SQL seed mətnini də tutmalıdır.
#
# Miqrasiya 017 mövcud quraşdırmaları düzəldir, `schema.sql` isə TƏMİZ
# quraşdırmanı. İkisi ayrılsaydı, yeni müştəri köhnə (İngiliscə) mətni alardı
# və qüsur yalnız istehsalatda görünərdi.

_LINE_COMMENT_RE: Final = re.compile(r"--[^\n]*")

#: SQL sətir literalı (`''` ilə qaçırılmış apostrof daxil).
_SQL_LITERAL_RE: Final = re.compile(r"'((?:[^']|'')*)'")

#: `SET name_az = '...'` və çoxsətirli `SET`-in vergüldən sonrakı davamı.
_SET_LABEL_RE: Final = re.compile(
    r"(?:SET|,)\s+(?:name_az|description_az|description)\s*=\s*'((?:[^']|'')*)'"
)

#: `WHERE name_az = '...'` / `AND description_az = '...'` — KÖHNƏ dəyər.
_WHERE_LABEL_RE: Final = re.compile(
    r"(?:WHERE|AND)\s+(?:name_az|description_az|description)\s*=\s*'((?:[^']|'')*)'"
)


def _strip_sql_comments(sql: str) -> str:
    """`--` şərhlərini atır.

    MƏCBURİDİR: miqrasiya sonunda ŞƏRHƏ ALINMIŞ DOWN bloku var (CLAUDE.md
    bölmə 7) və orada KÖHNƏ mətnlər yazılıdır. Şərhlər atılmasa, DOWN
    blokundakı köhnə dəyərlər «yeni dəyər» kimi oxunar və test tərsinə
    işləyərdi. Eyni yanaşma `test_db_guard_parity.py`-dədir.

    Sətir literalının içindəki `--` ardıcıllığı bu fayllarda YOXDUR (tire
    kimi `—` işlədilir), ona görə tam SQL parser-i əsassız mürəkkəblikdir.
    """
    return _LINE_COMMENT_RE.sub("", sql)


def _seed_literals() -> list[tuple[int, str]]:
    """`schema.sql`-in seed bölmələrindəki insan-oxunaqlı sətirlər."""
    lines = SCHEMA_FILE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines, 1) if SEED_REGION_START in line)
    end = next(i for i, line in enumerate(lines, 1) if SEED_REGION_END in line)

    found: list[tuple[int, str]] = []
    for number in range(start, end):
        for match in _SQL_LITERAL_RE.finditer(lines[number - 1]):
            value = match.group(1)
            if not value or _IDENTIFIER_RE.match(value):
                continue
            found.append((number, value))
    return found


def test_seed_region_is_discoverable() -> None:
    """Qapı: sərhəd markerləri dəyişsə, aşağıdakı testlər boş dəst üzərində "keçər"."""
    assert SCHEMA_FILE.exists(), f"schema.sql tapılmadı: {SCHEMA_FILE}"
    assert SEED_MIGRATION.exists(), f"017 miqrasiyası tapılmadı: {SEED_MIGRATION}"
    literals = _seed_literals()
    assert len(literals) > 40, f"Seed sətirləri tapılmadı (yalnız {len(literals)} ədəd)"
    assert any(value == "Ehtiyat nüsxə/bərpa" for _line, value in literals), (
        "Yenilənmiş seed etiketi tapılmadı — axtarış səhv aralığa baxır"
    )


def test_schema_seed_labels_have_no_english_leak() -> None:
    """`schema.sql` seed etiketləri — TƏMİZ quraşdırmanın gördüyü mətn."""
    leaks = [
        f"schema.sql:{line} «{value}» → «{word}»"
        for line, value in _seed_literals()
        if (word := _leak(value)) is not None
    ]
    assert not leaks, "Seed etiketində İngiliscə söz qaldı:\n" + "\n".join(leaks)


def test_migration_017_writes_the_same_text_as_schema() -> None:
    """MİQRASİYA ↔ SXEM PARİTETİ — yeni dəyərlər eyni olmalıdır.

    Mövcud baza `017`-dən, təzə baza isə `schema.sql`-dən mətn alır. İkisi
    ayrılsaydı, eyni versiyada işləyən iki quraşdırma fərqli etiket göstərərdi
    və fərqi heç bir test görməzdi.
    """
    migration = _strip_sql_comments(SEED_MIGRATION.read_text(encoding="utf-8"))
    schema = SCHEMA_FILE.read_text(encoding="utf-8")

    new_values = _SET_LABEL_RE.findall(migration)
    assert len(new_values) >= 10, f"Miqrasiyada `SET` etiketi tapılmadı ({len(new_values)} ədəd)"

    missing = [value for value in new_values if f"'{value}'" not in schema]
    assert not missing, (
        "017-nin yazdığı mətn `schema.sql`-də YOXDUR — təzə quraşdırma köhnə "
        "mətni alacaq:\n" + "\n".join(missing)
    )


def test_migration_017_old_values_are_gone_from_schema() -> None:
    """Sxem HƏQİQƏTƏN yenilənib — köhnə mətn seed-də qalmamalıdır.

    Bu, əvvəlki testin əks tərəfidir: `SET` dəyəri sxemdə tapıla bilər,
    lakin köhnə sətir də yanında qalmış olsa (məsələn ikinci bir seed
    bloku), miqrasiya bir hissəni əldən verərdi.
    """
    migration = _strip_sql_comments(SEED_MIGRATION.read_text(encoding="utf-8"))
    schema = SCHEMA_FILE.read_text(encoding="utf-8")

    old_values = _WHERE_LABEL_RE.findall(migration)
    assert len(old_values) >= 10, f"Miqrasiyada `WHERE` etiketi tapılmadı ({len(old_values)} ədəd)"

    stale = [value for value in old_values if f"'{value}'" in schema]
    assert not stale, (
        "Köhnə etiket hələ də `schema.sql`-dədir — 017 onu yalnız BAZADA "
        "düzəldir, təzə quraşdırma isə yenidən gətirər:\n" + "\n".join(stale)
    )


def test_migration_017_does_not_touch_identifier_columns() -> None:
    """Yalnız insan-oxunaqlı sütunlar yenilənir (qırmızı xətt).

    `code`, `flag_code`, `limit_key`, `module_key`, `category` bazada
    `FeatureModule` / `SystemLimitKey` / `menu.py` bağlantıları ilə hərfi
    uyğunluqdadır — tərcümə edilsəydi tətbiq sətri TAPA BİLMƏZDİ.
    """
    migration = _strip_sql_comments(SEED_MIGRATION.read_text(encoding="utf-8"))
    forbidden_targets = ("code", "flag_code", "limit_key", "module_key", "category")

    written = re.findall(r"(?:SET|,)\s+([a-z_]+)\s*=", migration)
    illegal = sorted({column for column in written if column in forbidden_targets})
    assert not illegal, f"017 identifikator sütununu yazır: {illegal}"

    assert "ALTER TABLE" not in migration.upper(), "017 struktur dəyişikliyi etməməlidir"
    assert "DROP " not in migration.upper(), "017 heç nə silməməlidir"


# --------------------------------------------------------------------------- #
# İSTİFADƏÇİYƏ ÇATAN ARQUMENTLƏR — üçüncü sızma yolu
# --------------------------------------------------------------------------- #
# Sütun başlıqları və menyu adları ekranın SƏTHİDİR. İstifadəçi mətni bir də
# DƏRİNDƏN gəlir: `KompasOSError.user_message`, `_require_status(hint=...)`,
# `Notifier.notify(title_az=..., body_az=...)`. Bunlar yalnız xəta anında
# görünür, yəni maketdə də, adi klikləmədə də gözə dəymir — məhz ona görə
# `leave_request.py:209`-dakı «statusunda» sözü auditdən keçib qalmışdı.
#
# `KompasOSError`-un BİRİNCİ (mövqe) arqumenti QƏSDƏN yoxlanılmır: o,
# developer/log mesajıdır (bax `shared/exceptions.py` — `self.message`),
# istifadəçi isə `user_message`-i görür. Onu tərcümə etmək `pytest.raises(
# match=...)` qapılarını sındırardı və heç bir istifadəçi faydası verməzdi.

SRC_DIR: Final = PROJECT_ROOT / "src"

#: İstifadəçiyə ÇATAN adlandırılmış arqumentlər.
USER_FACING_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "user_message",
        "hint",
        "title_az",
        "body_az",
        "empty_title",
        "empty_body",
        "footnote",
        "placeholder",
        "tooltip",
        "accessible_name",
        "create_label",
        "label",
    }
)


def _string_parts(node: ast.expr) -> list[ast.Constant]:
    """Sətir literalları — f-sətir və `+`/bitişik birləşmə daxil.

    Mətn tez-tez parçalanır (`"..." "..."` və ya f-sətir). Yalnız `Constant`
    axtarsaq, iki sətrə bölünmüş sızma görünməz qalardı.
    """
    if isinstance(node, ast.Constant):
        return [node] if isinstance(node.value, str) else []
    if isinstance(node, ast.JoinedStr):
        return [v for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
    if isinstance(node, ast.BinOp):
        return _string_parts(node.left) + _string_parts(node.right)
    return []


def _user_facing_strings() -> list[tuple[str, int, str, str]]:
    """`(fayl, sətir, arqument, mətn)` — istifadəçiyə çatan bütün literallar."""
    found: list[tuple[str, int, str, str]] = []
    for path in sorted(SRC_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        name = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg in USER_FACING_KEYWORDS:
                        found += [
                            (name, part.lineno, keyword.arg, part.value)
                            for part in _string_parts(keyword.value)
                        ]
            elif isinstance(node, ast.Assign):
                # sinif səviyyəli `user_message = "..."`
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in USER_FACING_KEYWORDS:
                        found += [
                            (name, part.lineno, target.id, part.value)
                            for part in _string_parts(node.value)
                        ]
    return found


def test_user_facing_strings_are_discoverable() -> None:
    """Qapı: AST axtarışı pozulsa, aşağıdakı test boş dəst üzərində "keçər"."""
    strings = _user_facing_strings()
    assert len(strings) > 100, f"İstifadəçi mətni tapılmadı (yalnız {len(strings)} ədəd)"
    assert any(arg == "user_message" for _f, _l, arg, _v in strings), (
        "`user_message` heç yerdə tapılmadı — axtarış səhv işləyir"
    )


def test_user_facing_messages_have_no_english_leak() -> None:
    """Xəta və bildiriş mətnləri də Azərbaycan dilində olmalıdır."""
    leaks = [
        f"{file}:{line} {arg}= «{value}» → «{word}»"
        for file, line, arg, value in _user_facing_strings()
        if (word := _leak(value)) is not None
    ]
    assert not leaks, "İstifadəçi mesajında İngiliscə söz qaldı:\n" + "\n".join(leaks)
