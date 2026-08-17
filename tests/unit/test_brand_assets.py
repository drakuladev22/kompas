"""Loqo qatı — fayllar, boyama və tema keçidi (logo.md).

──────────────────────────────────────────────────────────────────────────────
NƏYİ QORUYURUQ
──────────────────────────────────────────────────────────────────────────────
Loqo qüsurları SÜKUTLUDUR: şəkil tapılmasa ekran boş qalır, yanlış rənglə
boyansa tünd zolaqda görünməz olur — hər ikisi qurmanı da, testləri də
keçir və yalnız GÖZLƏ baxdıqda üzə çıxır. Ona görə burada üç şey ölçülür:

    1. fayllar mövcuddur və `.ico` onlardan qurulur;
    2. boyama HƏQİQƏTƏN rəngi dəyişir (alfa maskası işləyir);
    3. tema keçidində splash şəkli DƏYİŞİR.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

_REPO_ROOT: Final = Path(__file__).resolve().parents[2]
_LOGO_DIR: Final = _REPO_ROOT / "assets" / "logo"

#: `logo.md` xəritəsindəki runtime faylları (`windows_app.png` YALNIZ referansdır).
_EXPECTED: Final[tuple[str, ...]] = (
    "16.png",
    "16_withoutcontainer.png",
    "32.png",
    "64.png",
    # `.ico`-nun TƏK masteri (bax `scripts/build_icon.py` başlığı).
    "256.png",
    "light.png",
    "dark.png",
    "loading_screen_light.png",
    "loading_screen_dark.png",
)


def test_every_runtime_logo_file_is_present() -> None:
    """Xəritədəki hər fayl `assets/logo/`-dadır."""
    missing = [name for name in _EXPECTED if not (_LOGO_DIR / name).is_file()]
    assert not missing, f"çatışan loqo faylı: {missing}"


def test_the_reference_variants_are_not_shipped() -> None:
    """Referans/variant fayllar `assets/logo/`-ya DÜŞMÜR.

    `windows_app.png` maketdir. `256 negative.png` isə EYNİ işarənin böyük
    nüsxəsi DEYİL — konteyneri kvadratdır (squircle deyil) və fonu daha
    tünddür, yəni ayrı BİR VARİANTDIR. Onu `assets/logo/`-ya köçürmək
    `build_icon.py`-ın «tək master» qaydasını qeyri-müəyyən edərdi: iki
    256-lıq fayl arasında hansının seçildiyi fayl adından asılı qalardı.

    İkisi də `design_reference/`-də QALIR — orada olmaları qüsur deyil,
    dizayn qərarının sübutudur (bax `CLAUDE.md` §0).
    """
    for name in ("windows_app.png", "256 negative.png"):
        assert not (_LOGO_DIR / name).exists(), f"«{name}» runtime qovluğuna düşüb"


def test_the_icon_is_built_from_the_logo_sources() -> None:
    """`.ico` törəmə fayldır və mənbədən yenidən qurula bilir.

    Skript yenidən qurulub ölçüləri müqayisə edilir: `.ico`-nun əl ilə
    dəyişdirilməsi (məs. köhnə loqo ilə) belə tutulur.
    """
    import sys

    from PIL import Image

    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    from build_icon import ICO_SIZES  # yol yuxarıda qurulur

    with Image.open(_REPO_ROOT / "assets" / "kompasos.ico") as icon:
        sizes = sorted(icon.info.get("sizes", []))

    assert sizes == sorted((size, size) for size in ICO_SIZES)


def test_the_large_tier_exists_and_is_not_upscaled() -> None:
    """256 pilləsi VAR və NATİW masterdən gəlir — böyütmə ilə DEYİL.

    ────────────────────────────────────────────────────────────────────────
    BU TEST ƏVVƏL TƏRSİNİ YOXLAYIRDI
    ────────────────────────────────────────────────────────────────────────
    Adı `test_the_missing_large_tier_is_documented` idi və 256-nın YOXLUĞUNU
    qapılayırdı, çünki əldəki ən böyük rastr 64×64 idi — yəni məhdudiyyət
    dizayn qərarı deyil, MƏNBƏ çatışmazlığı idi. `assets/logo/256.png`
    gələndən sonra həmin qapı öz məqsədinin ƏKSİNƏ çevrildi: mövcud pilləni
    QADAĞAN edərdi.

    Yeni qapı iki şeyi birlikdə saxlayır: pillə var VƏ mənbə həqiqətən
    256×256-dır. İkincisi olmasa, dizayn faylı bir gün kiçik ölçüdə ixrac
    edilsə `.ico` sükutla böyütmə ilə qurulardı — yəni reqressiya adı
    dəyişməmiş qapının altından keçərdi.
    """
    import sys

    from PIL import Image

    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    import build_icon  # yol yuxarıda qurulur

    assert 256 in build_icon.ICO_SIZES, "256 pilləsi siyahıdan çıxıb"

    with Image.open(_LOGO_DIR / build_icon.SOURCE_NAME) as master:
        assert master.size == (build_icon.SOURCE_SIZE, build_icon.SOURCE_SIZE), (
            f"master {master.size} — böyütmə ilə qurulan 256 bulanıq olardı"
        )

    with Image.open(_REPO_ROOT / "assets" / "kompasos.ico") as icon:
        assert (256, 256) in icon.info.get("sizes", []), "`.ico`-da 256 pilləsi yoxdur"


@requires_qt
def test_a_missing_asset_returns_none(qt_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Fayl yoxdursa `None` — istisna ATILMIR (tətbiq loqosuz da açılmalıdır)."""
    from src.presentation.widgets import brand_assets

    brand_assets.clear_cache()
    assert brand_assets.logo_path("yoxdur.png") is None
    assert brand_assets.logo_pixmap("yoxdur.png", height=16) is None
    assert brand_assets.tinted_pixmap("yoxdur.png", height=16, color="#FF0000") is None


@requires_qt
def test_tinting_replaces_the_colour_but_keeps_the_shape(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Boyama forma DEYİL, RƏNG dəyişir.

    `16_withoutcontainer.png` tam `#134E4A`-dır və tünd başlıq zolağında
    görünməzdi — testin əsas iddiası budur ki, piksel həqiqətən yeni rəngə
    çevrilir.
    """
    from src.presentation.widgets import brand_assets

    brand_assets.clear_cache()
    plain = brand_assets.logo_pixmap(brand_assets.TITLE_MARK, height=32)
    tinted = brand_assets.tinted_pixmap(brand_assets.TITLE_MARK, height=32, color="#FF0000")
    assert plain is not None
    assert tinted is not None
    assert tinted.size() == plain.size()

    original = plain.toImage()
    painted = tinted.toImage()
    opaque = [
        (x, y)
        for y in range(painted.height())
        for x in range(painted.width())
        if painted.pixelColor(x, y).alpha() > 200
    ]
    assert opaque, "boyanmış şəkildə qeyri-şəffaf piksel yoxdur"

    x, y = opaque[len(opaque) // 2]
    assert painted.pixelColor(x, y).name().upper() == "#FF0000"
    assert original.pixelColor(x, y).name().upper() != "#FF0000"
    # Forma qorunur: alfa maskası eyni qalmalıdır.
    assert original.pixelColor(x, y).alpha() == painted.pixelColor(x, y).alpha()


def test_the_splash_asset_follows_the_theme() -> None:
    """Fayl adı hardcode EDİLMİR — seçim tək yerdədir (logo.md ADDIM 3)."""
    from src.presentation.widgets import brand_assets

    assert brand_assets.splash_asset(dark=True) == brand_assets.SPLASH_DARK
    assert brand_assets.splash_asset(dark=False) == brand_assets.SPLASH_LIGHT


@requires_qt
def test_the_title_bar_shows_the_compass_mark(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """Başlıq zolağında rəngli kvadrat DEYİL, əsl işarə var."""
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode
    from src.presentation.widgets.title_bar import TitleBar

    theme = ThemeManager(preference=ThemeMode.DARK)
    theme.apply(qt_app)
    bar = TitleBar()
    qtbot.addWidget(bar)
    bar.apply_theme(
        control_color="#8394AE",
        hover_color="#C4D0E2",
        close_hover_color="#0B1424",
        brand_mark_color=theme.color("--color-brand-mark"),
    )

    pixmap = bar._logo.pixmap()
    assert not pixmap.isNull()

    image = pixmap.toImage()
    # DƏQİQ BƏRABƏRLİK YOXLANILMIR: Qt piksellə əvvəlcədən-vurulmuş alfa
    # (premultiplied) saxlayır və geri çevirmə ±1 yuvarlaqlaşdırma verir
    # (`#2DD5BF` kimi). Ölçülən şey rəngin DƏYİŞMƏSİDİR, bit-dəqiqlik deyil.
    target = (0x2D, 0xD4, 0xBF)
    off_brand = [
        (x, y)
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 200
        and max(
            abs(image.pixelColor(x, y).red() - target[0]),
            abs(image.pixelColor(x, y).green() - target[1]),
            abs(image.pixelColor(x, y).blue() - target[2]),
        )
        > 2
    ]
    assert not off_brand, f"marka rəngindən kənar piksel: {off_brand[:5]}"


@requires_qt
def test_the_splash_lockup_changes_with_the_theme(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """Tünd və işıqlı lockup FƏRQLİ şəkillərdir (logo.md ADDIM 3)."""
    from src.presentation.screens.group_a_entry import SplashScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    light_theme = ThemeManager(preference=ThemeMode.LIGHT)
    light_theme.apply(qt_app)
    splash = SplashScreen(light_theme, version="0.0.0")
    qtbot.addWidget(splash)

    light = splash._lockup.pixmap()
    assert not light.isNull(), "işıqlı lockup qurulmadı"

    dark_theme = ThemeManager(preference=ThemeMode.DARK)
    splash.apply_theme(dark_theme)
    dark = splash._lockup.pixmap()
    assert not dark.isNull()
    assert dark.toImage() != light.toImage(), "tema dəyişdi, lockup dəyişmədi"
