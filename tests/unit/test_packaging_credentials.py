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

    Siyahı qəsdən dardır: ikon, loqo, şrift, üz modelləri, sxem dəsti. Yeni
    sətir əlavə edən adam bu testi də yeniləməyə məcbur olur — yəni əlavə
    QƏRARA çevrilir.
    """
    block = _datas_block()
    assert "kompasos.ico" in block
    assert "_FACE_MODEL_DATAS" in block
    # Loqo PNG-ləri (logo.md): başlıq zolağı və splash onları RUNTIME-da oxuyur,
    # yəni `.ico` tək başına kifayət etmir.
    assert "'assets/logo'" in block
    # Sxem + miqrasiyalar (RECOVERY-1): «Bazanı Avtomatik Qur» proqramın NƏ
    # quracağını özü ilə daşımasını tələb edir. Bunlar SİRR DEYİL — ona görə
    # yuxarıdakı `_FORBIDDEN` qapısı pozulmur.
    assert "_DATABASE_DATAS" in block
    spec = _spec_text()
    assert "schema.sql" in spec
    assert "'database/migrations'" in spec
    # `vendor/` alt dəsti müştəri paketinə DÜŞMƏMƏLİDİR: o, təchizatçının
    # mərkəzi bazası üçündür (DB-3). Glob KÖK səviyyəni götürür.
    assert "'migrations', '[0-9][0-9][0-9]_*.sql'" in spec
    # Inter şrifti (`appl.md` FAZA 1): interfeys onu TƏLƏB EDİR və Windows-da
    # quraşdırılmış deyil — paketə düşməsə `.exe` ehtiyat şriftlə çıxardı,
    # yəni mənbədən işləyən tətbiq bir cür, müştəri maşınındakı başqa cür
    # görünərdi (loqo PNG-ləri ilə EYNİ tələ). Lisenziya faylı da daxildir:
    # SIL OFL nüsxənin şriftlə birlikdə paylanmasını TƏLƏB edir. Bunlar da
    # SİRR DEYİL, yəni yuxarıdakı `_FORBIDDEN` qapısı pozulmur.
    assert "'assets', 'fonts', '*.ttf'" in spec
    assert "LICENSE-Inter.txt" in spec
    # Hər `datas` elementi ya ikon, ya loqo, ya şrift, ya üz modeli, ya da
    # sxem dəstidir. Rəqəm QƏSDƏN sabitdir: yeni sətir əlavə edən adam bu
    # testi də yeniləməyə məcbur olur, yəni əlavə QƏRARA çevrilir.
    entries = [line.strip() for line in block.splitlines() if line.strip().startswith(("(", "*"))]
    assert len(entries) == 6, f"gözlənilməyən `datas` elementləri: {entries}"


def test_the_test_tree_is_excluded() -> None:
    """`tests` paketə düşmür — hücum səthi və ölçü."""
    text = _spec_text()
    assert "excludes=['pytest', '_pytest', 'tests'," in text


def test_unused_qt_modules_are_excluded() -> None:
    """`QtWebEngine` tək başına ~100 MB-dır və heç yerdə idxal olunmur.

    Kod bazasında YALNIZ `QtWidgets`, `QtCore`, `QtGui`, `QtSvg` işlədilir;
    PyInstaller-in PySide6 hook-u isə tapdığı hər şeyi yığır. Ölçü həm disk,
    həm də AÇILMA vaxtıdır — hər fayl işə düşərkən oxunur.
    """
    text = _spec_text()
    assert "_UNUSED_QT_MODULES" in text
    assert "'PySide6.QtWebEngineCore'," in text
    # İŞLƏDİLƏN dörd modul siyahıda OLMAMALIDIR — biri səhvən əlavə olunsa,
    # paket qurulur, proqram isə müştəri maşınında idxal xətası ilə çökərdi.
    for used in ("'PySide6.QtWidgets'", "'PySide6.QtCore'", "'PySide6.QtGui'", "'PySide6.QtSvg'"):
        assert used not in text, f"{used} işlədilir, çıxarıla bilməz"


def test_the_package_is_built_as_a_directory_not_a_single_file() -> None:
    """`--onefile` hər açılışda 230 MB-ı `%TEMP%`-ə açırdı (5-15 saniyə).

    `exclude_binaries=True` + `COLLECT` — `--onedir` rejiminin spec qarşılığı.
    Bunlardan biri itsə paket sükutla `--onefile`-a qayıdar və yavaşlama
    yalnız müştəri maşınında hiss olunardı.
    """
    text = _spec_text()
    assert "exclude_binaries=True" in text
    assert "coll = COLLECT(" in text


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
