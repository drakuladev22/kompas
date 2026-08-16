"""Koddakı `migrations/NNN` istinadları HƏQİQİ faylı göstərməlidir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU QAPI VAR
──────────────────────────────────────────────────────────────────────────────
Miqrasiyalar bir dəfə YENİDƏN NÖMRƏLƏNDİ (057–060 → 053–056, nömrə boşluğunu
bağlamaq üçün). Fayllar düzgün adlandı, lakin koddakı şərh istinadları köhnə
nömrədə qaldı. Nəticə xüsusilə aldadıcı idi: həmin nömrələr SONRADAN BAŞQA
miqrasiyalara verildi, yəni istinad "sınıq" deyil, **YANLIŞ** oldu —
`DASHBOARD_GRID_COLUMNS`-un mənbəyini axtaran adam 058-i açır və orada bildiriş
tərcihlərini görürdü.

Sadəcə «fayl mövcuddurmu» yoxlaması bunu TUTA BİLMƏZDİ (058 mövcuddur). Ona
görə qapı MƏZMUNA baxır.

──────────────────────────────────────────────────────────────────────────────
DƏQİQLİK QAYDASI — YALANÇI XƏBƏRDARLIQ VERMİRİK
──────────────────────────────────────────────────────────────────────────────
İstinadın yanındakı ad YALNIZ o halda yoxlanılır ki, o, SQL korpusunda
ÜMUMİYYƏTLƏ mövcud olsun. Səbəb: `APP_LIMIT_BOUNDS`, `HARDLOCK_BY_CODE` kimi
adlar PYTHON sabitidir və miqrasiyada heç vaxt keçmir — onları "yanlış istinad"
saymaq qapını səs-küyə çevirərdi.

Yəni tutulan hal dəqiqdir: **ad SQL-də var, amma GÖSTƏRİLƏN faylda yox** —
deməli nömrə səhvdir və qapı düzgün faylı da göstərir.

İdentifikatoru olmayan sərbəst istinad (məs. «bax migrations/037») yoxlanmır:
onun doğruluğunu maşın müəyyən edə bilməz, "keçdi" kimi göstərmək isə qapını
yalançı edərdi.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT: Final = Path(__file__).resolve().parents[2]
_MIGRATIONS: Final = _REPO_ROOT / "database" / "migrations"
_SCANNED: Final = ("src", "tests")

#: `migrations/054` və ya «miqrasiya 054» — hər ikisi kodda işlənir.
_REFERENCE: Final = re.compile(r"migrations?/(\d{3})|miqrasiya\s+(\d{3})")

#: İdentifikator BACKTICK içində olmalıdır — layihə konvensiyası budur.
#: Backtick tələb edilməsəydi, şərhlərdəki BÖYÜK hərfli Azərbaycan vurğu
#: sözləri (`YOXLAMA`, `PLANLAYICISI`) identifikator sanılardı. Alt-xətt
#: tələbi eyni səbəbdəndir: limit açarları HƏMİŞƏ `SNAKE_CASE`-dir.
_IDENTIFIER: Final = re.compile(r"`([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)`|`([a-z_]+\.[a-z_]+)`")

#: Fayl adı `cədvəl.sütun` naxışına oxşayır (`test_x.py`) — SQL obyekti deyil.
_NOT_SQL_SUFFIX: Final = (".py", ".md", ".sql", ".toml", ".json")


@cache
def _migration_files() -> tuple[tuple[str, str], ...]:
    return tuple(
        (path.name, path.read_text(encoding="utf-8", errors="replace"))
        for path in sorted(_MIGRATIONS.glob("*.sql"))
    )


def _files_containing(name: str) -> set[str]:
    return {filename for filename, text in _migration_files() if name in text}


def _file_for(number: str) -> str | None:
    matches = [filename for filename, _text in _migration_files() if filename.startswith(number)]
    return matches[0] if matches else None


def _claims() -> list[tuple[str, int, str, str, str]]:
    """(fayl, sətir, nömrə, identifikator, sətrin özü)."""
    claims: list[tuple[str, int, str, str, str]] = []
    for root in _SCANNED:
        for path in sorted((_REPO_ROOT / root).rglob("*.py")):
            if "__pycache__" in path.parts or path.name == Path(__file__).name:
                continue
            relative = str(path.relative_to(_REPO_ROOT))
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                reference = _REFERENCE.search(line)
                if reference is None:
                    continue
                number = reference.group(1) or reference.group(2)
                for match in _IDENTIFIER.finditer(line):
                    name = match.group(1) or match.group(2)
                    if name and not name.endswith(_NOT_SQL_SUFFIX):
                        claims.append((relative, lineno, number, name, line.strip()))
    return claims


def test_every_referenced_migration_file_exists() -> None:
    """`migrations/NNN` göstərilirsə həmin fayl OLMALIDIR."""
    missing = [
        f"{path}:{lineno} → migrations/{number}"
        for path, lineno, number, _name, _line in _claims()
        if _file_for(number) is None
    ]
    assert not missing, "mövcud olmayan miqrasiyaya istinad: " + ", ".join(missing)


def test_referenced_migrations_actually_contain_the_named_identifier() -> None:
    """Ad SQL-də varsa, GÖSTƏRİLƏN miqrasiyada da olmalıdır.

    Nömrələmə düzəlişindən sonra qalan altı yanlış istinadı məhz bu yoxlama
    tutdu: fayl mövcud idi, məzmun isə tamamilə başqa mövzu idi.
    """
    wrong: list[str] = []
    for path, lineno, number, name, line in _claims():
        target = _file_for(number)
        if target is None:
            continue  # yuxarıdakı test ayrıca hesabat verir
        holders = _files_containing(name)
        if not holders:
            continue  # Python-tərəfi ad — SQL iddiası deyil
        if target not in holders:
            wrong.append(
                f"{path}:{lineno} — `{name}` {target}-də yoxdur, "
                f"əslində burada: {', '.join(sorted(holders))} (sətir: {line[:60]})"
            )

    assert not wrong, "istinad edilən miqrasiya səhvdir:\n  " + "\n  ".join(wrong)


def test_the_gate_actually_checks_something() -> None:
    """Qapı boş işləməməlidir — yoxlana bilən iddia sayı sıfır ola bilməz.

    Regex bir gün sınsa (məs. şərh üslubu dəyişsə), yuxarıdakı iki test SÜKUTLA
    keçərdi: sıfır iddia = sıfır uğursuzluq. Bu yoxlama həmin sakit sınmanı
    tutur.
    """
    verifiable = [claim for claim in _claims() if _files_containing(claim[3])]
    assert len(verifiable) >= 10, (
        f"yalnız {len(verifiable)} yoxlana bilən istinad tapıldı — "
        "`_IDENTIFIER`/`_REFERENCE` naxışı sınıb ola bilər"
    )
