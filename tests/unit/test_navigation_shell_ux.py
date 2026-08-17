"""Sol naviqasiya: aralıq, aç/bağla düyməsi, responsivlik və başlıq mətni.

──────────────────────────────────────────────────────────────────────────────
DÖRD İSTİFADƏÇİ HESABATI, DÖRD QAPI
──────────────────────────────────────────────────────────────────────────────
    «naviqasiya sistemi çox iç-içədir»          → ölçülər
    «açılıb bağlanan navigation olmalıdır»       → düymə + siqnal
    «bağlananda/açılanda responsivlik düz olmalıdır» → əl ilə seçim yaddaşı
    «idarə panelində 21 filial yazılmağını istəmirəm» → say bazadan gəlir
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from src.presentation.widgets import metrics
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

_REPO: Final[Path] = Path(__file__).resolve().parents[2]


def test_the_navigation_has_room_to_breathe() -> None:
    """Sətir hündürlüyü və aralıq «iç-içə» görünməyəcək qədər olmalıdır.

    Ədədlər DƏYİŞƏ BİLƏR — qapı konkret 44/8 rəqəmini qorumur, MİNİMUMU
    qoruyur. Kimsə maketə qayıtmaq üçün onları 40/4-ə endirsə, hesabatın
    səbəbi geri qayıdar və bu, sükutla baş verməməlidir.
    """
    assert metrics.NAV_ITEM_HEIGHT >= 44, "naviqasiya sətri yenidən sıxılıb"
    assert metrics.SIDEBAR_ITEM_SPACING >= 8, "sətirlər arası boşluq yenidən daralıb"
    assert metrics.SIDEBAR_WIDTH >= 240, "uzun başlıqlar üçün en kifayət etmir"
    # Daraldılmış en TOXUNMAMALIDIR: o, yalnız-ikon rejimin ölçüsüdür və
    # böyüsəydi «daralt» əməliyyatı mənasını itirərdi.
    assert metrics.SIDEBAR_COLLAPSED_WIDTH < metrics.SIDEBAR_WIDTH // 2


@requires_qt
def test_the_sidebar_can_be_collapsed_and_reopened(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """Düymə paneli daraldır, ikinci klik geri açır və vəziyyəti YAYIR."""
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.widgets.sidebar import Sidebar

    theme = ThemeManager()
    bar = Sidebar(
        idle_icon_color=theme.color("--color-nav-item-icon"),
        active_icon_color=theme.color("--color-brand-amber"),
    )
    qtbot.addWidget(bar)

    states: list[bool] = []
    bar.collapse_toggled.connect(states.append)

    assert bar.is_collapsed is False
    assert bar.width() == metrics.SIDEBAR_WIDTH

    bar.toggle_button().click()
    assert bar.is_collapsed is True
    assert bar.width() == metrics.SIDEBAR_COLLAPSED_WIDTH

    bar.toggle_button().click()
    assert bar.is_collapsed is False
    assert bar.width() == metrics.SIDEBAR_WIDTH

    assert states == [True, False], "vəziyyət yayılmır — örtük seçimi yadda saxlaya bilməz"


@requires_qt
def test_a_manual_choice_survives_a_window_resize(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """Əl ilə açılan panel pəncərə kiçiləndə ÖZ-ÖZÜNƏ bağlanmır.

    Bu, «responsivlik düz olmalıdır» hesabatının nüvəsidir: əvvəl daralma
    YALNIZ pəncərə enindən asılı idi, yəni istifadəçinin qərarı hər ölçü
    dəyişikliyində silinirdi.
    """
    from datetime import UTC, datetime

    from src.presentation import preview_data
    from src.presentation.shell.admin_shell import AdminShell
    from src.presentation.shell.menu import build_default_registry
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.widgets.responsive import LayoutMode

    theme = ThemeManager()
    shell = AdminShell(
        theme=theme,
        registry=build_default_registry(),
        employee=preview_data.build_admin(),
        now=datetime(2026, 8, 17, 9, 0, tzinfo=UTC),
    )
    qtbot.addWidget(shell)

    sidebar = shell.sidebar()
    assert sidebar.is_collapsed is False

    # Dar pəncərə → avtomatik daralma (seçim hələ yoxdur).
    shell.apply_layout_mode(LayoutMode.COMPACT)
    assert sidebar.is_collapsed is True

    # İstifadəçi ƏL İLƏ açır...
    sidebar.toggle_button().click()
    assert sidebar.is_collapsed is False

    # ...və pəncərə yenidən dar rejimə düşsə belə AÇIQ qalır.
    shell.apply_layout_mode(LayoutMode.WIDE)
    shell.apply_layout_mode(LayoutMode.COMPACT)
    assert sidebar.is_collapsed is False, "əl ilə verilən qərar sükutla ləğv olundu"


def test_no_screen_subtitle_carries_an_invented_number() -> None:
    """Başlıq mətnlərində uydurma say/tarix QALMAMALIDIR.

    «21 filial», «235 nəfər», «12 Avqust 2026» maketdən gələn sabitlər idi və
    bir mağazalı quraşdırmada da göstərilirdi. İndi bu mətnlər boş başlayır və
    girişdən sonra bazadan doldurulur.
    """
    source = (_REPO / "src" / "presentation" / "app.py").read_text(encoding="utf-8")
    block = source[source.index("subtitles = {") : source.index("for key, factory in factories")]

    values = re.findall(r':\s*"([^"]*)"', block)
    offenders = [
        text
        for text in values
        if re.search(r"\d+\s*(filial|nəfər)", text) or re.search(r"\d{1,2}\s+[A-ZİƏÖÜÇŞĞ]", text)
    ]
    assert not offenders, f"başlıqda uydurma say/tarix qalıb: {offenders}"


def test_the_counts_come_from_the_database() -> None:
    """Say `stores`/`employees` cədvəllərindən oxunur, parametrdən YOX.

    Ayrıca «filial sayı» parametri olsaydı, o, `stores` cədvəli ilə sinxrondan
    çıxan ikinci həqiqət mənbəyi olardı — mağaza əlavə edilir, rəqəm qalır.
    """
    source = (_REPO / "src" / "presentation" / "app.py").read_text(encoding="utf-8")
    assert "_refresh_context_subtitles" in source, "canlı doldurma yolu yoxdur"
    assert "FROM stores" in source and "FROM employees" in source
    assert "SHELL_SUBTITLE_COUNTS_UNAVAILABLE" in source, (
        "sorğu uğursuzluğu sükutla ötürülür — jurnal yazısı olmalıdır"
    )


# --------------------------------------------------------------------------- #
# İdarə panelindəki «neçə işçi, neçə filial»
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_dashboard_shows_the_network_size(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """İdarə panelində işçi və filial sayı kart kimi görünür."""
    from src.presentation.screens import group_c
    from src.presentation.theme.manager import ThemeManager

    screen = group_c.DashboardScreen(ThemeManager())
    qtbot.addWidget(screen)

    screen.set_network_size(employees=7, stores=2)

    assert screen._employees._value.text() == "7"
    assert screen._stores._value.text() == "2"


@requires_qt
def test_the_counts_grow_when_something_is_created(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """Yeni mağaza/işçi yarandıqda rəqəm ARTIR — sabit deyil.

    Ekran öz-özünə sorğu vermir; qapı «say YENİDƏN yazıla bilir» faktını
    qoruyur. Onu bir dəfə qurulub donan kartla (məs. konstruktorda sabit
    mətn) əvəz etmək istəyən adam burada dayanır.
    """
    from src.presentation.screens import group_c
    from src.presentation.theme.manager import ThemeManager

    screen = group_c.DashboardScreen(ThemeManager())
    qtbot.addWidget(screen)

    screen.set_network_size(employees=1, stores=1)
    screen.set_network_size(employees=2, stores=3)

    assert screen._employees._value.text() == "2"
    assert screen._stores._value.text() == "3"


@requires_qt
def test_returning_to_the_dashboard_reloads_it(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """Artıq qurulmuş panelə qayıdış AYRICA siqnal yayır.

    Ekranlar bir dəfə qurulur və məlumatı qurulma anında doldurulur. Siqnal
    olmasaydı, mağaza əlavə edib panelə qayıdan istifadəçi köhnə rəqəmi
    görərdi — «yaratdıqca artmalıdır» gözləntisi məhz burada pozulurdu.

    `screen_changed` bu iş üçün yaramır: o, İLK qurulmada da yayılır.
    """
    from datetime import UTC, datetime

    from src.presentation import preview_data
    from src.presentation.screens.base import Screen
    from src.presentation.shell.admin_shell import AdminShell
    from src.presentation.shell.menu import build_default_registry
    from src.presentation.theme.manager import ThemeManager

    theme = ThemeManager()
    shell = AdminShell(
        theme=theme,
        registry=build_default_registry(),
        employee=preview_data.build_admin(),
        now=datetime(2026, 8, 17, 9, 0, tzinfo=UTC),
    )
    qtbot.addWidget(shell)

    keys = shell.sidebar().entry_keys()
    first, second = keys[0], keys[1]
    shell.register_screen(first, lambda: Screen(theme))
    shell.register_screen(second, lambda: Screen(theme))

    revisits: list[str] = []
    shell.screen_revisited.connect(revisits.append)

    shell.show_screen(first)
    assert revisits == [], "ilk qurulmada təzələmə siqnalı yayılmamalıdır"

    shell.show_screen(second)
    shell.show_screen(first)
    assert revisits == [first], "qayıdışda təzələmə siqnalı yayılmır"


def test_only_read_only_screens_are_reloaded_on_revisit() -> None:
    """Təzələmə siyahısı DAR olmalıdır.

    Hər ekranı hər naviqasiyada yenidən doldurmaq onlarla sorğunu istifadəçinin
    hər klikinə bağlayardı və yazı yolu olan ekranlarda (cərimə forması, növbə)
    doldurulmamış formanı silərdi.
    """
    from src.presentation.app import KompasApplication

    assert set(KompasApplication.REFRESH_ON_REVISIT) == {"dashboard"}


# --------------------------------------------------------------------------- #
# `navbar.md` + `navbar.jpg` — vizual düzülüş qapıları
# --------------------------------------------------------------------------- #


def test_the_row_height_is_not_hardcoded_in_the_stylesheet() -> None:
    """Sətir hündürlüyü İKİ yerdə OLMAMALIDIR.

    Qüsurun ÖZ ssenarisi: `qss.py` `min-height: 40px; max-height: 40px`
    yazırdı və bu, `metrics.NAV_ITEM_HEIGHT`-i sükutla üstələyirdi — Python
    tərəfdə ölçü dəyişəndə panel GÖRÜNÜŞDƏ eyni qalırdı. «Maddələr
    iç-içədir» hesabatının bir hissəsi məhz bu ikili mənbədən gəlirdi.
    """
    from src.presentation.theme import tokens

    source = (_REPO / "src" / "presentation" / "theme" / "qss.py").read_text(encoding="utf-8")
    nav_block = source[source.index('QPushButton[variant="nav"] {') :]
    # `index("}")` YARAMIR: token sintaksisi `{{--ad}}` ilə yazılır, yəni ilk
    # `}` elə tokenin içindədir. Blok SƏTİR BAŞINDAKI `}` ilə bitir.
    nav_block = nav_block[: nav_block.index("\n}")]

    assert "{{--nav-item-height}}" in nav_block, "hündürlük tokendən gəlmir"
    assert not re.search(r"min-height:\s*\d", nav_block), "QSS-də ədəd qalıb"

    # Token və metrik EYNİ dəyər olmalıdır — biri QSS-ə, digəri layout-a gedir.
    assert tokens.METRICS["--nav-item-height"] == str(metrics.NAV_ITEM_HEIGHT)
    assert tokens.METRICS["--nav-icon-gap"] == str(metrics.NAV_ITEM_ICON_SPACING)


def test_the_section_label_does_not_use_the_mono_family() -> None:
    """«NAVİQASİYA» etiketi mono şriftdə OLMAMALIDIR.

    İstifadəçi onu «NAVIOASIYA» kimi görürdü. Mətn doğru idi (`az_upper`
    doctest ilə qorunur) — problem renderdə: mono ailə bu sinif maşınlarda
    həll olunmur (`CLAUDE.md` §2) və əvəzedici şrift `İ`-nin nöqtəsini,
    `Q`-nun quyruğunu itirir.
    """
    source = (_REPO / "src" / "presentation" / "theme" / "qss.py").read_text(encoding="utf-8")
    block = source[source.index("QLabel#SectionLabel {") :]
    block = block[: block.index(chr(10) + "}")]  # bax yuxarıdaki `}}` izahı
    assert "{{--font-family-mono}}" not in block, "bölmə etiketi yenidən mono şriftdədir"
    assert "{{--font-family}}" in block


def test_the_uppercase_helper_keeps_azerbaijani_letters() -> None:
    """Mətnin ÖZÜ doğrudur — qapı bunu da təsdiqləyir."""
    from src.presentation.i18n.text import az_upper

    assert az_upper("Naviqasiya") == "NAVİQASİYA"


@requires_qt
def test_the_section_label_lines_up_with_the_icons(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """Etiket və ikonlar DƏQİQ eyni şaquli xətdən başlayır.

    Əvvəl etiketin sol kənarı 12px, naviqasiya sətrinin ikonu isə 12+16=28px
    idi — panelin sol kənarında iki fərqli xətt görünürdü (navbar.md PROBLEM 1
    bənd 4).
    """
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.widgets.sidebar import Sidebar

    theme = ThemeManager()
    theme.apply(qt_app)
    bar = Sidebar(
        idle_icon_color=theme.color("--color-nav-item-icon"),
        active_icon_color=theme.color("--color-brand-amber"),
    )
    qtbot.addWidget(bar)
    # Geometry YALNIZ göstərildikdən sonra hesablanır — `show()` olmadan bütün
    # koordinatlar sıfırdır və ölçmə mənasız olardı.
    bar.show()
    qt_app.processEvents()

    label_left = bar._section.mapTo(bar, bar._section.rect().topLeft()).x()
    expected = metrics.SIDEBAR_PADDING_H + metrics.NAV_ITEM_TEXT_INDENT
    assert label_left == expected, (
        f"etiket {label_left}px-dən başlayır, ikonlar isə {expected}px-dən"
    )


@requires_qt
def test_the_collapsed_rail_centres_its_icons(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """Daraldılmış zolaqda mətn TAM gizlənir, ikon MƏRKƏZDƏ olur.

    `navbar.jpg`-də nazik zolaqda ikonlar dəqiq mərkəzdədir. Sol padding
    qalsaydı, 64px-lik zolaqda ikon sol yarıya sıxışardı və «kəsilmiş mətn»
    təsiri yaranardı (navbar.md PROBLEM 1 bənd 7).
    """
    from src.domain.value_objects.authorization import PermissionFlag
    from src.presentation.navigation import MenuEntry
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.widgets.sidebar import Sidebar

    theme = ThemeManager()
    theme.apply(qt_app)
    bar = Sidebar(
        idle_icon_color=theme.color("--color-nav-item-icon"),
        active_icon_color=theme.color("--color-brand-amber"),
    )
    qtbot.addWidget(bar)
    bar.set_entries([MenuEntry(key="dashboard", title_az="İdarə Paneli", icon="dashboard")])
    button = bar._buttons["dashboard"]

    assert button.property("compact") == "false"
    assert button.text() == "İdarə Paneli"

    bar.set_collapsed(True)
    assert button.property("compact") == "true", "QSS mərkəzləmə şərti qoyulmur"
    assert button.text() == "", "daraldılmış rejimdə mətn qalıb"
    # Ad ekran oxuyucusu üçün İTMİR (mövcud zəmanət).
    assert button.accessibleName().strip()

    assert PermissionFlag is not None


@requires_qt
def test_the_title_bar_buttons_share_one_size_and_centre(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """Dörd düymə (tema, kiçilt, böyüt, bağla) EYNİ ölçü və mərkəzdə.

    Tema düyməsi əvvəl 34×34 idi və tam hündürlüklü düzbucaqlıların yanında
    «dairə» kimi oxunurdu (navbar.md PROBLEM 3 bənd 3).
    """
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.widgets.title_bar import TitleBar

    theme = ThemeManager()
    theme.apply(qt_app)
    bar = TitleBar()
    qtbot.addWidget(bar)
    bar.show()
    qt_app.processEvents()

    buttons = (bar.theme_button(), *bar.buttons())
    sizes = {(b.width(), b.height()) for b in buttons}
    assert len(sizes) == 1, f"düymələr fərqli ölçüdədir: {sizes}"

    centres = {b.mapTo(bar, b.rect().center()).y() for b in buttons}
    assert len(centres) == 1, f"şaquli mərkəzlər fərqlidir: {centres}"


def test_icon_buttons_on_bare_surfaces_have_no_border() -> None:
    """Sol panel və başlıq zolağındaki ikon düyməsi SƏRHƏDSİZDİR.

    İstifadəçi hesabatı: «narıncı düzbucaqlı + ağ dairəvi cizgi, dizayn
    sisteminə heç uyğun deyil». Baza `variant="icon"` qaydası 1px sərhəd +
    8px künc daşıyır — səhifə başlığında doğrudur (orada düymənin varlığını
    göstərən yeganə şey sərhəddir), bu iki səthdə isə qutu kimi ayırır.
    """
    source = (_REPO / "src" / "presentation" / "theme" / "qss.py").read_text(encoding="utf-8")
    marker = '#Sidebar QPushButton[variant="icon"],\n#TitleBar QPushButton[variant="icon"] {'
    assert marker in source, "sərhədsiz qayda yoxdur"
    block = source[source.index(marker) :]
    block = block[: block.index(chr(10) + "}")]  # bax `}}` izahı
    assert "border: none" in block
