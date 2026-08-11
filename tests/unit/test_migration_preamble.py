"""Hər SQL faylının `search_path` preambulasını daşıdığını təsbit edir.

NİYƏ BU TEST VAR — Bütün cədvəllər `kompasos` sxemindədir, `public`-də deyil.
`psql -f fayl.sql` HƏR fayl üçün YENİ sessiya açır, ona görə bir faylda
qoyulan `SET search_path` növbəti fayla KEÇMİR. Preambulanı unudan fayl
defolt `search_path` (`"$user", public`) ilə işləyir və içindəki hər cədvəl
istinadı `relation "..." does not exist` xətası verir.

Bu, nəzəri risk deyil: `010`, `011`, `013` faylları məhz bu sətri itirmişdi
və CI-ın `DB sxemi` job-u miqrasiya döngəsinin ORTASINDA — `010`-da —
çökürdü. Nəticədə `011`–`017` HEÇ VAXT icra olunmurdu, yəni onların
sintaksisi və məntiqi real bazada yoxlanmamış qalırdı.

NİYƏ QRIPP DEYİL, TEST — Preambula insan yazısıdır və hər yeni miqrasiyada
təkrarlanır; təkrarlanan şeyi unutmaq qaçılmazdır. Kod baxışı bunu tutmur,
çünki faylın QALAN hissəsi tamamilə düzgün görünür. Yeganə etibarlı qapı
maşın yoxlamasıdır.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_MIGRATIONS_DIR: Final[Path] = _REPO_ROOT / "database" / "migrations"
_SQL_TEST_DIR: Final[Path] = _REPO_ROOT / "database" / "tests"

#: Sxem adı `schema.sql`-də təyin olunur; preambula ona İSTİNAD etməlidir.
_EXPECTED: Final[re.Pattern[str]] = re.compile(
    r"^\s*SET\s+search_path\s+TO\s+kompasos\s*,\s*public\s*;", re.MULTILINE
)

#: `--` ilə başlayan şərh sətri: DOWN bloku məhz belə saxlanılır, ona görə
#: şərh içindəki `SET search_path` FAKTİKİ preambula sayılmamalıdır.
_COMMENT_LINE: Final[re.Pattern[str]] = re.compile(r"^\s*--")


def _executable_sql(path: Path) -> str:
    """Şərh sətirlərini ataraq YALNIZ icra olunan SQL-i qaytarır."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not _COMMENT_LINE.match(line))


def _migration_files() -> list[Path]:
    return sorted(_MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))


def test_migrations_dir_is_discoverable() -> None:
    """Marker qapısı — boş dəst üzərində testlərin "keçməsi"nin qarşısını alır."""
    files = _migration_files()
    assert len(files) >= 17, f"Miqrasiya faylları tapılmadı: {_MIGRATIONS_DIR}"


@pytest.mark.parametrize("path", _migration_files(), ids=lambda p: p.name)
def test_every_migration_sets_the_search_path(path: Path) -> None:
    """Hər miqrasiya `kompasos` sxemini açıq şəkildə seçməlidir."""
    assert _EXPECTED.search(_executable_sql(path)), (
        f"{path.name} `SET search_path TO kompasos, public;` sətrini daşımır — "
        "bu fayl defolt sxemlə işləyəcək və hər cədvəl istinadı çökəcək."
    )


@pytest.mark.parametrize("path", _migration_files(), ids=lambda p: p.name)
def test_search_path_comes_before_the_first_table_reference(path: Path) -> None:
    """Preambula İLK cədvəl istinadından ƏVVƏL gəlməlidir.

    Sətrin faylda mövcud olması kifayət deyil: sonda dursa, ondan əvvəlki
    `ALTER TABLE`/`UPDATE` yenə defolt sxemdə axtarar.
    """
    sql = _executable_sql(path)
    preamble = _EXPECTED.search(sql)
    assert preamble is not None  # yuxarıdakı test onsuz da tutur

    first_reference = re.search(
        r"\b(ALTER\s+TABLE|UPDATE|INSERT\s+INTO|CREATE\s+(UNIQUE\s+)?INDEX)\b",
        sql,
        re.IGNORECASE,
    )
    if first_reference is None:
        pytest.skip("Bu miqrasiya cədvələ birbaşa istinad etmir")

    assert preamble.start() < first_reference.start(), (
        f"{path.name}: `SET search_path` ilk cədvəl istinadından SONRA gəlir — "
        "ondan əvvəlki ifadələr defolt sxemdə axtaracaq."
    )


def test_sql_guard_suite_also_sets_the_search_path() -> None:
    """`test_guards.sql` də ayrıca `psql` sessiyasında işləyir."""
    guards = _SQL_TEST_DIR / "test_guards.sql"
    assert guards.exists(), f"Guard test faylı tapılmadı: {guards}"
    assert _EXPECTED.search(_executable_sql(guards)), (
        "test_guards.sql `SET search_path` daşımır — CI-da hər cədvəl çökər."
    )


def test_schema_file_declares_the_schema_itself() -> None:
    """`schema.sql` sxemi həm YARADIR, həm seçir — miqrasiyalar buna güvənir."""
    schema = _REPO_ROOT / "database" / "schema.sql"
    sql = _executable_sql(schema)
    assert re.search(r"CREATE\s+SCHEMA\s+IF\s+NOT\s+EXISTS\s+kompasos", sql, re.I), (
        "schema.sql `kompasos` sxemini yaratmır — preambula mənasız olardı."
    )
    assert _EXPECTED.search(sql), "schema.sql `SET search_path` daşımır."
