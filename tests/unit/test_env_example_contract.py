"""`.env.example` yalnız KODUN OXUDUĞU açarları sənədləşdirməlidir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU QAPI VAR
──────────────────────────────────────────────────────────────────────────────
`CLAUDE.md` §8: «quraşdırıcı hansı açarın məcburi olduğunu `.env.example`-dən
öyrənir». Deməli orada yazılan HƏR açar bir vəddir. Oxunmayan açar isə səssiz
yalandır — istifadəçi onu doldurur, heç nə dəyişmir və səbəb heç bir jurnalda
görünmür.

Qapı real hadisədən sonra qoyuldu: fayl `SUPABASE_URL`,
`SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` açarlarını sənədləşdirirdi,
tətbiq isə HƏMİŞƏ `KOMPASOS_` prefiksli adları oxuyurdu. Nəticədə Developer
Paneli üçün `SUPABASE_SERVICE_ROLE_KEY` dolduran adam panelin niyə
açılmadığını tapa bilmirdi. Eyni sinifdən daha iki açar (`KOMPASOS_NTP_*`)
ROOT parametrinə köçmüş, lakin faylda qalmışdı.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.unit

_REPO: Final[Path] = Path(__file__).resolve().parents[2]
_ENV_EXAMPLE: Final[Path] = _REPO / ".env.example"

#: `KEY=` sətirləri (şərh sətirləri `#` ilə başladığı üçün onsuz da düşmür).
_KEY_LINE: Final = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)

#: HƏLƏ QOŞULMAMIŞ, lakin QƏSDƏN saxlanılan açarlar — səbəbi ilə.
#:
#: Bunlar silinmir, çünki dəyər özü DOĞRUDUR və onu oxuyacaq qat gələcəkdə
#: qurulur. Siyahı BAĞLIDIR: yeni ad bura yalnız eyni müzakirədən sonra
#: əlavə olunur, əks halda qapı tədricən mənasını itirər.
_NOT_YET_WIRED: Final[dict[str, str]] = {
    "KOMPASOS_VENDOR_CONTACT": (
        "`SupabaseLicenseGateway(vendor_contact=...)` parametri var, lakin "
        "lisenziya qapısı hələ kompozisiya kökünə bağlanmayıb — dəyəri "
        "ötürəcək çağırış YOXDUR."
    ),
    "KOMPASOS_SUPPORT_EMAIL": (
        "Açılış xətası ekranındakı statik ünvan (bölmə 8) hələ mətndə "
        "sabitdir; mühitdən oxunması lisenziya qapısı ilə eyni işdədir."
    ),
}


def _documented_keys() -> list[str]:
    text = _ENV_EXAMPLE.read_bytes().decode("utf-8")
    return _KEY_LINE.findall(text)


def _source_text() -> str:
    parts: list[str] = []
    for folder in ("src", "scripts"):
        for path in (_REPO / folder).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def test_every_documented_key_is_read_somewhere() -> None:
    """Sənədləşdirilmiş hər açar kodda ADI İLƏ görünməlidir.

    Yoxlama sadədir (mətn axtarışı), çünki açarlar `os.environ.get("...")`
    və ya `Final[str] = "..."` sabiti kimi yazılır — hər iki halda ad mənbədə
    hərfi-hərfinə var. Daha «ağıllı» analiz burada yalnız yalan-mənfi
    gətirərdi.
    """
    source = _source_text()
    orphans = [key for key in _documented_keys() if key not in source and key not in _NOT_YET_WIRED]
    assert not orphans, (
        "`.env.example` heç bir kodun oxumadığı açar sənədləşdirir "
        f"(doldurmaq HEÇ NƏYƏ təsir etmir): {orphans}"
    )


def test_the_waiver_list_stays_honest() -> None:
    """Güzəşt siyahısındakı ad HƏQİQƏTƏN oxunmamalıdır.

    Açar sonradan qoşulanda onu siyahıdan çıxarmaq unudula bilər və güzəşt
    daimi kor nöqtəyə çevrilər. Ona görə güzəştin ÖZÜ də yoxlanılır.
    """
    source = _source_text()
    wired = [key for key in _NOT_YET_WIRED if key in source]
    assert not wired, f"bu açarlar artıq oxunur — `_NOT_YET_WIRED`-dan çıxarın: {wired}"


def test_the_supabase_keys_carry_the_mandatory_prefix() -> None:
    """Prefikssiz `SUPABASE_*` adı GERİ QAYITMAMALIDIR.

    Qüsurun öz ssenarisi: prefikssiz ad mühitdə başqa alətlərin (Supabase
    CLI, digər layihələr) dəyişənləri ilə toqquşur və tətbiq onu onsuz da
    oxumur.
    """
    text = _ENV_EXAMPLE.read_bytes().decode("utf-8")
    offenders = [key for key in _KEY_LINE.findall(text) if key.startswith("SUPABASE_")]
    assert not offenders, (
        f"prefikssiz Supabase açarı geri əlavə olunub: {offenders} — "
        "kod yalnız `KOMPASOS_SUPABASE_*` adlarını oxuyur"
    )
