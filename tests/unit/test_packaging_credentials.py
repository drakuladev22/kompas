"""Paketə credentials düşmür (DB-4 Faza 3).

──────────────────────────────────────────────────────────────────────────────
NİYƏ MAŞINLA YOXLANILIR
──────────────────────────────────────────────────────────────────────────────
«`.env` paketə salınmır» ifadəsi spec faylının şərhində var. Şərh isə sükutla
köhnəlir: kimsə bir gün `datas`-a bir sətir əlavə edər, şərh yerində qalar və
fərq YALNIZ paketin içində — yəni müştəriyə göndərildikdən sonra — görünər.

Bu qapı `.spec` faylının MƏTNİNİ oxuyur, yəni build tələb etmir və hər `pytest`
dəstində işləyir.

──────────────────────────────────────────────────────────────────────────────
NƏ ÖLÇÜLMÜR
──────────────────────────────────────────────────────────────────────────────
Faktiki `.exe`-nin içindəkilər ölçülmür (build lazımdır). Ölçülən şey NİYYƏTDİR:
spec nə paketləməyi söyləyir. Build-in özü CI-nın işidir.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT: Final = Path(__file__).resolve().parents[2]
_SPEC: Final = _REPO_ROOT / "src" / "KompasOS.spec"

#: Paketə DÜŞMƏMƏLİ olan fayl/ad nümunələri.
_FORBIDDEN: Final[tuple[str, ...]] = (
    ".env",
    "connection.json",
    "installation.json",
    "kompasos.key",
    "service_role",
    "DATABASE_URL",
    "KOMPASOS_VENDOR_DSN",
)


def _spec_text() -> str:
    return _SPEC.read_text(encoding="utf-8", errors="replace")


def _datas_block() -> str:
    """`Analysis(...)` daxilindəki `datas=[...]` bloku.

    Axtarış `a = Analysis(`-dən BAŞLAYIR: spec-in başlığında `--add-data`
    ekvivalentini izah edən ŞƏRH də `datas=[` sətrini daşıyır və sadə
    `index("datas=[")` məhz onu tapırdı — yəni test şərhi yoxlayırdı, kodu yox.
    """
    text = _spec_text()
    start = text.index("datas=[", text.index("a = Analysis("))
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "[":
            depth += 1
        elif text[index] == "]":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise AssertionError("`datas=[...]` bloku bağlanmır")


def test_no_credential_file_is_bundled() -> None:
    """`datas` yalnız ikon və üz modellərini daşıyır."""
    block = _datas_block()
    for name in _FORBIDDEN:
        assert name not in block, f"`datas` credentials daşıyır: {name}"


def test_the_spec_contains_no_hardcoded_dsn() -> None:
    """Spec-in HEÇ BİR yerində DSN sətri olmamalıdır.

    Şərhlərdə `postgresql://` nümunəsi belə yazılmır: kopyalanan nümunə bir
    gün real dəyərlə əvəzlənə bilər və heç bir baxış onu tutmaz.
    """
    assert not re.search(r"postgres(?:ql)?://", _spec_text())


def test_the_datas_block_only_carries_known_assets() -> None:
    """Yeni `datas` sətri DİQQƏTDƏN yayınmamalıdır.

    Siyahı qəsdən dardır: ikon + üz modelləri. Yeni sətir əlavə edən adam bu
    testi də yeniləməyə məcbur olur — yəni əlavə QƏRARA çevrilir.
    """
    block = _datas_block()
    assert "kompasos.ico" in block
    assert "_FACE_MODEL_DATAS" in block
    # Loqo PNG-ləri (logo.md): başlıq zolağı və splash onları RUNTIME-da oxuyur,
    # yəni `.ico` tək başına kifayət etmir.
    assert "'assets/logo'" in block
    # Hər `datas` elementi ya ikon, ya loqo dəsti, ya da üz modelləridir.
    entries = [line.strip() for line in block.splitlines() if line.strip().startswith(("(", "*"))]
    assert len(entries) == 3, f"gözlənilməyən `datas` elementləri: {entries}"
    assert entries[2].startswith("*_FACE_MODEL_DATAS")


def test_the_test_tree_is_excluded() -> None:
    """`tests` paketə düşmür — hücum səthi və ölçü."""
    text = _spec_text()
    assert "excludes=['pytest', '_pytest', 'tests']" in text


def test_the_bootstrap_script_is_not_bundled() -> None:
    """Vendor hesabı yaradan skript `.exe`-də olmamalıdır (DB-3 Faza 4)."""
    text = _spec_text()
    assert "create_vendor_account" not in text
    # `a.scripts` PyInstaller-in ÖZ atributudur (giriş nöqtəsinin bayt-kodu) —
    # `scripts/` qovluğu ilə əlaqəsi yoxdur. Ona görə yoxlama YOL formasına
    # baxır, sadə söz axtarışına yox.
    assert "'scripts'" not in text
    assert "scripts/" not in text.replace("\\", "/")


def test_the_entry_point_is_the_only_script() -> None:
    """`Analysis` yalnız `main.py`-ı giriş nöqtəsi kimi alır."""
    text = _spec_text()
    analysis = text[text.index("a = Analysis(") : text.index("pyz = PYZ(")]
    scripts = re.findall(r"os\.path\.join\(SPECPATH,\s*'([^']+)'\)", analysis)
    assert scripts and scripts[0] == "main.py"
