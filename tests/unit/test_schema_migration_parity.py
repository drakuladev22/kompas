"""`schema.sql` ↔ miqrasiya paritesi — eyni obyekt İKİ yerdə EYNİ olmalıdır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU QAPI VAR
──────────────────────────────────────────────────────────────────────────────
DB-1 konsolidasiya auditi belə bir qüsur tapdı: `enforce_anti_fraud_segregation()`
miqrasiya 013-də prioritet-əsaslı qadağa ilə gücləndirilmiş, 048-də həddi
yenilənmiş, lakin `schema.sql`-dəki nüsxə HEÇ VAXT yenilənməmişdi.

Nəticə sükutlu idi və yalnız quraşdırma YOLUNDAN asılı görünürdü:

  * tam miqrasiya zənciri tətbiq olunmuş baza → GÜCLÜ qapı (düzgün);
  * `schema.sql` ilə təmiz quraşdırma       → ZƏİF qapı — "satıcı-pilləli"
    custom rol bütün anti-fraud flag-lərini DB səviyyəsində qəbul edərdi.

Domen qatı hər iki halda bloklayırdı, yəni müdafiənin İKİNCİ qatı bir yolda
YOX idi. CLAUDE.md §5 məhz bunu qadağan edir: «Hər qayda İKİ yerdə var —
domendə və DB trigger-ində. Birini dəyişəndə DİGƏRİ də dəyişməlidir.»

Heç bir mövcud test bunu tuta bilmirdi, çünki `database/tests/test_guards.sql`
FAKTİKİ bazaya qarşı işləyir — yəni miqrasiyalar tətbiq olunduqdan SONRAKI
vəziyyəti ölçür və `schema.sql`-in öz mətnini heç vaxt görmür.

──────────────────────────────────────────────────────────────────────────────
NƏ ÖLÇÜLÜR
──────────────────────────────────────────────────────────────────────────────
Hər obyekt (funksiya / indeks / cədvəl) HƏM `schema.sql`-də, HƏM də ən azı bir
miqrasiyada təyin olunubsa, `schema.sql`-dəki tərif SONUNCU miqrasiyanınkı ilə
üst-üstə düşməlidir. Fərq qəsdlidirsə `INTENTIONAL_DIVERGENCE`-ə SƏBƏBİ İLƏ
yazılır — yəni fərq görünməz qalmır, qərara çevrilir.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT: Final = Path(__file__).resolve().parents[2]
_SCHEMA: Final = _REPO_ROOT / "database" / "schema.sql"
_MIGRATIONS: Final = _REPO_ROOT / "database" / "migrations"

#: Fərqi QƏSDLİ olan obyektlər: ad → səbəb.
#:
#: Siyahıya əlavə etmək bir QƏRARDIR: "bu iki tərif fərqlidir və bu, düzgündür".
#: Səbəb yazılmasa qapı mənasını itirər — növbəti oxucu fərqin unudulmuş, yoxsa
#: seçilmiş olduğunu bilməzdi.
INTENTIONAL_DIVERGENCE: Final[dict[str, str]] = {
    "idx_notifications_email_pending": (
        "007 indeksi `email_attempts` + `email_next_attempt_at` sütunları ilə "
        "yenidən qurur, həmin sütunları isə ELƏ 007 əlavə edir. Bazis sxem "
        "onları ehtiva etmir, yəni tərif orada dəyişə BİLMƏZ — fərq qatlanma "
        "nizamının nəticəsidir."
    ),
}

#: Yalnız bu ad növləri müqayisə olunur. `CREATE TABLE` da daxildir, çünki
#: `monthly_fine_review_batches` hər iki yerdə tam təriflə mövcuddur.
_FUNCTION = re.compile(
    r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+([a-z_][a-z0-9_]*)\s*\(.*?\$\$\s*LANGUAGE\s+plpgsql\s*;",
    re.IGNORECASE | re.DOTALL,
)
_INDEX = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)\s+(ON\s+.*?);",
    re.IGNORECASE | re.DOTALL,
)
_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)\s*\((.*?)\n\);",
    re.IGNORECASE | re.DOTALL,
)


def _strip_comments(sql: str) -> str:
    """`--` şərhlərini atır — şərh fərqi davranış fərqi DEYİL."""
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _normalise(sql: str) -> str:
    """Boşluq/sətir fərqlərini silir; mətn və böyük-kiçik hərf QALIR.

    Xəta mesajları qəsdən saxlanılır: iki qapı eyni qaydanı fərqli mesajla
    ifadə edirsə, istifadəçi hansı qatın işə düşdüyünü bilməlidir.
    """
    return " ".join(_strip_comments(sql).split())


def _collect(pattern: re.Pattern[str], text: str, *, group: int = 0) -> dict[str, str]:
    found: dict[str, str] = {}
    for match in pattern.finditer(text):
        name = match.group(1).lower()
        body = match.group(group) if group else match.group(0)
        found[name] = _normalise(body)
    return found


def _definitions(text: str) -> dict[str, str]:
    return {
        **_collect(_FUNCTION, text),
        **_collect(_INDEX, text, group=2),
        **_collect(_TABLE, text, group=2),
    }


def _pairs() -> list[tuple[str, str, str, str]]:
    """(ad, schema.sql tərifi, sonuncu miqrasiya adı, onun tərifi)."""
    schema = _definitions(_SCHEMA.read_text(encoding="utf-8", errors="replace"))

    latest: dict[str, tuple[str, str]] = {}
    for path in sorted(_MIGRATIONS.glob("*.sql")):
        for name, body in _definitions(path.read_text(encoding="utf-8", errors="replace")).items():
            latest[name] = (path.name, body)

    return [
        (name, schema[name], latest[name][0], latest[name][1])
        for name in sorted(schema)
        if name in latest
    ]


def test_shared_objects_are_defined_identically() -> None:
    """İki yerdə təyin olunan hər obyekt EYNİ olmalıdır (və ya siyahıda)."""
    drifted = [
        (name, source)
        for name, schema_body, source, migration_body in _pairs()
        if schema_body != migration_body and name not in INTENTIONAL_DIVERGENCE
    ]

    assert not drifted, (
        "`schema.sql` ilə miqrasiya arasında fərq: "
        + ", ".join(f"{name} (sonuncu: {source})" for name, source in drifted)
        + ". Bazis sxem son versiyaya gətirilməli, VƏ YA fərq "
        "`INTENTIONAL_DIVERGENCE`-ə səbəbi ilə yazılmalıdır."
    )


def test_the_anti_fraud_guard_carries_the_priority_rule() -> None:
    """Ən kritik hal AYRICA kilidlənir — ümumi qapı ondan asılı qalmasın.

    Yuxarıdakı test bütün obyektlərə baxır və gələcəkdə kimsə pozuntunu
    `INTENTIONAL_DIVERGENCE`-ə yazaraq susdura bilər. Bu qayda isə
    struktur zəmanətdir (CLAUDE.md §5): prioritet-əsaslı qadağa hər iki
    tərifdə OLMALIDIR — istisnası yoxdur.
    """
    schema = _SCHEMA.read_text(encoding="utf-8", errors="replace")
    match = _FUNCTION.search(schema)
    bodies = {m.group(1).lower(): m.group(0) for m in _FUNCTION.finditer(schema)}
    assert match is not None, "schema.sql-də heç bir plpgsql funksiyası tapılmadı"

    guard = bodies.get("enforce_anti_fraud_segregation")
    assert guard is not None, "`enforce_anti_fraud_segregation()` schema.sql-dən itib"
    assert "v_priority" in guard, (
        "anti-fraud qapısı prioritet qaydasını daşımır — custom 'satıcı-pilləli' "
        "rol DB səviyyəsində anti-fraud flag-i ala bilər (bax modul başlığı)"
    )
    assert ">= 4" in guard, "prioritet həddi 048-dəki dəyərlə (4) uyğun gəlmir"


def test_the_divergence_registry_is_not_stale() -> None:
    """Siyahıdakı ad artıq fərqli deyilsə, sətir SİLİNMƏLİDİR.

    Köhnəlmiş istisna qapının ən sakit uğursuzluq formasıdır: ad orada qalır,
    fərq isə real deyil — yəni növbəti həqiqi fərq həmin adla gəlsə, sükutla
    keçər.
    """
    actually_different = {
        name
        for name, schema_body, _source, migration_body in _pairs()
        if schema_body != migration_body
    }
    stale = sorted(set(INTENTIONAL_DIVERGENCE) - actually_different)
    assert not stale, f"`INTENTIONAL_DIVERGENCE`-dəki bu adlar artıq fərqlənmir: {stale}"
