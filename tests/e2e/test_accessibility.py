"""Klaviatura əlçatanlığı və fokus göstəricisi — WCAG AA davranış testləri.

Bu fayl əlçatanlıq auditinin DAVRANIŞ tapıntılarını qapıya salır; RƏNG
tapıntıları `scripts/check_contrast.py` və `tests/unit/test_design_system.py`
tərəfindən yoxlanılır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BURADA REAL WIDGET QURULUR (VƏ NİYƏ QSS MƏTNİ KİFAYƏT DEYİL)
──────────────────────────────────────────────────────────────────────────────
Auditin ən vacib tapıntısı belə idi: fokus halqası QSS-də MÖVCUD idi, lakin
qüvvəyə minmirdi — Qt-nin kaskad qaydası onu variant bloklarının `border`
elanı ilə əzirdi. Yəni "qayda şablonda varmı" sualı DOĞRU cavab verirdi,
istifadəçi isə heç nə görmürdü.

Ona görə burada faktiki RENDER müqayisə edilir: widget fokussuz və fokuslu
halda `grab()` ilə şəkilə çevrilir və iki şəkil BƏRABƏR OLMAMALIDIR. Bu,
QSS-in necə yazıldığından asılı olmayan yeganə yoxlamadır — sabah kimsə
qaydanı başqa üsulla versə (məsələn `QProxyStyle` ilə), test yenə düzgün
qərar verər.

Yoxlamanın həssaslığı təsdiqlənib: fokus bloku şablondan çıxarıldıqda hər beş
variant üçün iki şəkil eyni çıxır (yəni test qüsuru TUTUR), blok yerində
olduqda isə hər beşi üçün fərqlidir.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from src.presentation.theme.tokens import ThemeMode
from tests.conftest import requires_qt

if TYPE_CHECKING:
    from PySide6.QtWidgets import QPushButton, QWidget

pytestmark = [pytest.mark.e2e, pytest.mark.qt]


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _themed(app: Any, mode: ThemeMode) -> Any:
    """Tətbiqə temanı tətbiq edib `ThemeManager`-i qaytarır."""
    from src.presentation.theme.manager import ThemeManager

    manager = ThemeManager(preference=mode)
    manager.apply(app)
    return manager


def _shown(app: Any, widget: QWidget) -> QWidget:
    """Widget-i göstərir və pəncərəni AKTİV edir.

    Aktivlik məcburidir: qeyri-aktiv pəncərədə `setFocus()` yalnız "gələcək
    fokus" qeyd edir, `hasFocus()` isə `False` qalır — yəni `:focus`
    psevdo-sinifi heç vaxt işə düşməzdi və test səhvən yaşıl olardı.
    """
    widget.show()
    widget.activateWindow()
    app.processEvents()
    return widget


def _renders_differently_when_focused(app: Any, widget: QWidget) -> bool:
    """Widget KLAVİATURA fokusu alanda VİZUAL olaraq dəyişirmi.

    Fokus səbəbi QƏSDƏN `Tab`-dır, defolt (`Other`) deyil: halqa klaviatura ilə
    gəzən istifadəçi üçündür və pəncərə düymələri onu məhz həmin səbəbə
    bağlayır (bax `widgets/buttons.py::focusInEvent` — açılışdakı avtomatik
    fokus hər dəfə görünən ağ kvadrat çəkirdi). Digər variantlar səbəbə
    baxmır, yəni yoxlama onlar üçün eyni qalır.
    """
    from PySide6.QtCore import Qt

    widget.clearFocus()
    app.processEvents()
    unfocused = widget.grab().toImage()

    widget.setFocus(Qt.FocusReason.TabFocusReason)
    app.processEvents()
    assert widget.hasFocus(), "widget fokus qəbul etmir — `focusPolicy` yoxlayın"
    focused = widget.grab().toImage()

    return unfocused != focused


def _press(widget: QWidget, key: Any) -> None:
    """Klaviatura hadisəsini birbaşa widget-ə göndərir."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    QApplication.sendEvent(
        widget, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    )


# --------------------------------------------------------------------------- #
# Tapıntı 5 — fokus halqası QSS kaskadı ilə əzilirdi
# --------------------------------------------------------------------------- #


@requires_qt
@pytest.mark.parametrize("mode", [ThemeMode.LIGHT, ThemeMode.DARK])
@pytest.mark.parametrize("variant", ["action", "secondary", "icon", "nav", "window"])
def test_every_button_variant_shows_a_focus_indicator(
    qt_app, mode: ThemeMode, variant: str
) -> None:  # type: ignore[no-untyped-def]
    """Hər düymə variantı fokus alanda GÖRÜNƏN fərq göstərməlidir.

    Düzəlişdən əvvəl beşi də heç nə göstərmirdi: ümumi `QPushButton:focus`
    qaydası şablonda variant bloklarından ƏVVƏL dayanırdı və Qt bərabər
    spesifiklikdə sonuncu qaydanı seçdiyi üçün `border: none` / variant
    sərhədi qalib gəlirdi.
    """
    from PySide6.QtWidgets import QHBoxLayout, QWidget

    from src.presentation.widgets.buttons import (
        NavButton,
        WindowButton,
        action_button,
        icon_button,
        secondary_button,
    )

    theme = _themed(qt_app, mode)
    factories = {
        "action": lambda: action_button("Yadda saxla"),
        "secondary": lambda: secondary_button("Ləğv et"),
        "icon": lambda: icon_button(
            "bell",
            theme.color("--color-text-secondary"),
            tooltip="Bildirişlər",
            accessible_name="Bildirişlər",
        ),
        "nav": lambda: NavButton(
            "dashboard",
            "İdarə paneli",
            icon_name="bell",
            idle_color=theme.color("--color-nav-item-icon"),
            active_color=theme.color("--color-brand-amber"),
        ),
        "window": lambda: WindowButton("close"),
    }

    host = QWidget()
    layout = QHBoxLayout(host)
    button = factories[variant]()
    layout.addWidget(button)
    _shown(qt_app, host)

    assert _renders_differently_when_focused(qt_app, button), (
        f"`variant={variant}` fokus alanda vizual fərq göstərmir — "
        "QSS kaskadında `:focus` qaydası variant blokundan sonra gəlirmi?"
    )


@requires_qt
def test_window_buttons_are_reachable_by_keyboard(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Çərçivəsiz pəncərədə —/□/× klaviatura ilə əlçatan olmalıdır.

    Pəncərənin öz çərçivəsi yoxdur, yəni Windows-un sistem menyusu (Alt+Boşluq)
    da yoxdur: bu üç düymə pəncərəni idarə etməyin yeganə yoludur. `NoFocus`
    ilə onlar siçansız istifadəçi üçün TAMAMİLƏ əlçatmaz idi.

    `TabFocus` qəsdən seçilib (`StrongFocus` deyil): siçanla klikləyəndə fokus
    halqası çıxmır, yəni mövcud vizual davranış dəyişmir.
    """
    from PySide6.QtCore import Qt

    from src.presentation.widgets.title_bar import TitleBar

    _themed(qt_app, ThemeMode.DARK)
    bar = TitleBar()
    _shown(qt_app, bar)

    buttons = [bar._minimize, bar._maximize, bar._close]
    for button in buttons:
        assert button.focusPolicy() is Qt.FocusPolicy.TabFocus
        assert button.accessibleName().strip(), "pəncərə düyməsi adsızdır"


@requires_qt
@pytest.mark.parametrize("mode", [ThemeMode.LIGHT, ThemeMode.DARK])
@pytest.mark.parametrize(
    "element",
    ["FilterChip", "LinkLabel", "ClickableCard", "TableRow", "NotificationItem"],
)
def test_clickable_non_button_elements_show_a_focus_indicator(  # type: ignore[no-untyped-def]
    qt_app, mode: ThemeMode, element: str
) -> None:
    """Etiket/kart/sətir şəklindəki hərəkətlər də fokus göstərməlidir.

    Bunlar `QPushButton` deyil, ona görə Qt onlara heç bir defolt fokus
    görünüşü vermir — halqa tamamilə QSS-dən gəlir.
    """
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from src.presentation.screens.group_g import NotificationItem
    from src.presentation.widgets.data_table import Column, TableRow
    from src.presentation.widgets.primitives import ClickableCard, FilterChip, LinkLabel

    theme = _themed(qt_app, mode)
    factories = {
        "FilterChip": lambda: FilterChip("hamisi", "Hamısı"),
        "LinkLabel": lambda: LinkLabel("Bütün bildirişlərə bax"),
        "ClickableCard": lambda: ClickableCard("novbe-1"),
        "TableRow": lambda: TableRow([Column("Ad")], ["Rəşad Məmmədov"], theme),
        "NotificationItem": lambda: NotificationItem(
            {"id": "n-1", "title": "Növbə dəyişdi", "unread": "0"}, theme
        ),
    }

    host = QWidget()
    layout = QVBoxLayout(host)
    widget = factories[element]()
    layout.addWidget(widget)
    _shown(qt_app, host)

    assert _renders_differently_when_focused(qt_app, widget), (
        f"`{element}` fokus alanda görünmür — QSS-də `:focus` qaydası varmı?"
    )


@requires_qt
def test_focus_border_does_not_change_chip_geometry(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Fokus üçün ayrılmış ŞƏFFAF sərhəd nişanın ölçüsünü dəyişməməlidir.

    Sərhəd yalnız `:focus` halında əlavə edilsəydi, Qt widget-in ölçü hesabına
    2px əlavə edərdi və nişan fokus alanda "sıçrayardı". Ona görə yer
    əvvəlcədən ayrılır, doldurma isə eyni qədər azaldılır: `2px + 3px = 5px`
    və `2px + 10px = 12px`.

    Bu test həmin hesabı qoruyur: kimsə doldurmanı "sadələşdirsə", nişan
    ölçüsü sükutla böyüyərdi.

    (DESIGN.MD REDİZAYNI: hesab əvvəllər `2+2=4` / `2+6=8` idi və hər iki
    nəticə `--space-xs`/`--space-sm` tokenlərinə düşürdü. Yeni həb formasında
    doldurma `3px 10px`-dir, cəm isə 5/12 — şkalada qarşılığı olmadığı üçün
    hərfi yazılır. İNVARİANT DƏYİŞMƏYİB: yoxlanan şey rəqəmlər deyil,
    «fokus ölçünü dəyişmir» qaydasıdır.)
    """
    from src.presentation.theme.qss import QSS_TEMPLATE, render
    from src.presentation.theme.tokens import theme_tokens
    from src.presentation.widgets.primitives import Chip

    tokens = theme_tokens(ThemeMode.LIGHT)
    # İKİ MÜSTƏQİL ƏVƏZLƏMƏ, bir uzun blok deyil: qaydanın içinə şərh əlavə
    # etmək (redizayn zamanı məhz belə oldu) bitişik bloku uyğunsuz edir və
    # test "qayda dəyişib" deyib dayanırdı, halbuki YOXLADIĞI invariant
    # toxunulmamışdı. Ayrı-ayrı sətirlər şərhə həssas deyil.
    without_focus_room = QSS_TEMPLATE.replace(
        "    border: {{--focus-ring-width}} solid transparent;\n    /* DESIGN.MD REDİZAYNI:",
        "    /* DESIGN.MD REDİZAYNI:",
    ).replace("    padding: 3px 10px;", "    padding: 5px 12px;")
    assert without_focus_room != QSS_TEMPLATE, "nişan qaydası dəyişib — testi yeniləyin"

    qt_app.setStyleSheet(render(without_focus_room, tokens))
    maket = Chip("Aktiv", "success")
    maket.ensurePolished()
    expected = maket.sizeHint()

    qt_app.setStyleSheet(render(QSS_TEMPLATE, tokens))
    actual_chip = Chip("Aktiv", "success")
    actual_chip.ensurePolished()

    # `qt_app` sessiya boyu paylaşılır — üslub cədvəli olduğu kimi qaytarılır,
    # əks halda bu test özündən sonrakıların mühitini dəyişərdi.
    _themed(qt_app, ThemeMode.LIGHT)

    assert actual_chip.sizeHint() == expected


# --------------------------------------------------------------------------- #
# Tapıntı 4 — klik edilə bilən elementlər klaviatura ilə çatılmırdı
# --------------------------------------------------------------------------- #


@requires_qt
@pytest.mark.parametrize("key_name", ["Key_Return", "Key_Enter", "Key_Space"])
def test_filter_chip_activates_with_keyboard(qt_app, key_name: str) -> None:  # type: ignore[no-untyped-def]
    """Süzgəc nişanı Enter/Space ilə də klik sayılmalıdır."""
    from PySide6.QtCore import Qt

    from src.presentation.widgets.primitives import FilterChip

    _themed(qt_app, ThemeMode.LIGHT)
    chip = FilterChip("hamisi", "Hamısı")
    _shown(qt_app, chip)

    received: list[str] = []
    chip.clicked.connect(received.append)
    _press(chip, getattr(Qt.Key, key_name))

    assert received == ["hamisi"]
    assert chip.focusPolicy() is Qt.FocusPolicy.StrongFocus


@requires_qt
def test_link_label_activates_with_keyboard_and_has_a_name(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Mətn-hərəkət klaviatura ilə işə düşməli və adı olmalıdır."""
    from PySide6.QtCore import Qt

    from src.presentation.widgets.primitives import LinkLabel

    _themed(qt_app, ThemeMode.LIGHT)
    link = LinkLabel("Hamısını oxunmuş et")
    _shown(qt_app, link)

    received: list[bool] = []
    link.clicked.connect(lambda: received.append(True))
    _press(link, Qt.Key.Key_Return)

    assert received == [True]
    assert link.accessibleName() == "Hamısını oxunmuş et"


@requires_qt
def test_clickable_card_and_table_row_activate_with_keyboard(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Klik edilə bilən kart və cədvəl sətri — siçansız da açılmalıdır."""
    from PySide6.QtCore import Qt

    from src.presentation.widgets.data_table import Column, TableRow
    from src.presentation.widgets.primitives import ClickableCard

    theme = _themed(qt_app, ThemeMode.LIGHT)

    card = ClickableCard("nov-1")
    _shown(qt_app, card)
    card_clicks: list[str] = []
    card.clicked.connect(card_clicks.append)
    _press(card, Qt.Key.Key_Space)

    row = TableRow([Column("Ad")], ["Rəşad Məmmədov"], theme)
    _shown(qt_app, row)
    row_clicks: list[bool] = []
    row.clicked.connect(lambda: row_clicks.append(True))
    _press(row, Qt.Key.Key_Return)

    assert card_clicks == ["nov-1"]
    assert row_clicks == [True]


@requires_qt
def test_notification_row_carries_unread_state_in_its_name(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Oxunmamış vəziyyət YALNIZ rənglə göstərilməməlidir.

    Maketdə fərq iki şeydir: bir ton fərqli fon və amber nöqtə — hər ikisi
    RƏNGDİR. Rəngi ayırd etməyən istifadəçi üçün oxunmuş və oxunmamış sətir
    eynidir, ona görə vəziyyət əlçatan ada da yazılır.
    """
    from PySide6.QtCore import Qt

    from src.presentation.screens.group_g import NotificationItem

    theme = _themed(qt_app, ThemeMode.LIGHT)
    unread = NotificationItem(
        {"id": "n-1", "title": "Yeni cərimə", "body": "Gecikmə", "unread": "1"}, theme
    )
    read = NotificationItem({"id": "n-2", "title": "Növbə dəyişdi", "unread": "0"}, theme)
    _shown(qt_app, unread)

    clicks: list[str] = []
    unread.clicked.connect(clicks.append)
    _press(unread, Qt.Key.Key_Return)

    assert "oxunmamış" in unread.accessibleName()
    assert "oxunmamış" not in read.accessibleName()
    assert clicks == ["n-1"]


@requires_qt
def test_photo_drop_zone_is_keyboard_operable(qt_app, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    """Foto sübutu MƏCBURİDİR — deməli siçansız da seçilə bilməlidir.

    Sahə yalnız `mousePressEvent`-ə bağlı qalsaydı, bir əlçatanlıq qüsuru
    bütöv cərimə axınını klaviatura istifadəçisi üçün bağlayardı.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFileDialog

    from src.presentation.screens.group_b import PhotoDropZone

    theme = _themed(qt_app, ThemeMode.LIGHT)
    zone = PhotoDropZone(theme)
    _shown(qt_app, zone)

    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("C:/subut.png", ""))
    )
    chosen: list[str] = []
    zone.file_selected.connect(chosen.append)
    _press(zone, Qt.Key.Key_Return)

    assert chosen == ["C:/subut.png"]
    assert zone.accessibleName().strip()


# --------------------------------------------------------------------------- #
# Tapıntı 6 — yalnız-ikon düymələrin əlçatan adı yox idi
# --------------------------------------------------------------------------- #


@requires_qt
def test_icon_buttons_have_accessible_names(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Mətnsiz düymə `accessibleName()` olmadan "adsız düymə" kimi elan olunur.

    Qt zənciri: `accessibleName()` → boşdursa `text()`. `toolTip()` bu
    zəncirdə YOXDUR, ona görə tooltip-in mövcudluğu heç nəyi həll etmirdi.
    """
    from src.presentation.widgets.buttons import icon_button

    _themed(qt_app, ThemeMode.LIGHT)
    button = icon_button(
        "bell",
        "#666666",
        tooltip="Bildirişlər",
        accessible_name="Bildirişlər",
        accessible_description="Oxunmamış bildirişləri açır",
    )

    assert button.text() == "", "fabrika mətnsiz düymə qaytarır — ad tələb olunur"
    assert button.accessibleName() == "Bildirişlər"
    assert button.accessibleDescription() == "Oxunmamış bildirişləri açır"


@requires_qt
def test_page_header_icon_buttons_are_named(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Header-dəki TƏKRAR işlədilən ikon düymələri adsız qalmamalıdır.

    Zəng düyməsinin adı SAYI da daşıyır: nişan ayrıca üzən `QLabel`-dir və
    Qt onu düymə ilə əlaqələndirmir — yalnız-vizual qalsaydı, oxunmamış
    bildirişin varlığı ekran oxuyucusundan gizli olardı.
    """
    from src.presentation.widgets.page_header import PageHeader

    theme = _themed(qt_app, ThemeMode.LIGHT)
    header = PageHeader(
        icon_color=theme.color("--color-nav-item-icon"),
        avatar_bg=theme.color("--color-neutral-bg"),
        avatar_fg=theme.color("--color-text-primary"),
        badge_bg=theme.color("--color-brand-amber"),
        badge_fg=theme.color("--color-brand-navy"),
        surface_color=theme.color("--color-header-bg"),
        dark_mode=False,
    )
    _shown(qt_app, header)

    # TEMA DÜYMƏSİ ARTIQ HEADER-DƏ DEYİL — o, başlıq zolağına köçdü
    # (`widgets/title_bar.py`) və onun adı `test_window_chrome`-da yoxlanılır.
    # Dublikatın silinməsi `navbar.md` PROBLEM 2 bənd 1-in tələbidir; qapı
    # onun GERİ QAYITMAMASINI da yoxlayır, çünki iki düymə sağ blokun
    # simmetriyasını pozurdu.
    assert not hasattr(header, "_theme_button"), (
        "tema düyməsi header-ə geri qayıdıb — o, başlıq zolağındadır"
    )

    bell_button: QPushButton = header._bell._button
    assert bell_button.accessibleName() == "Bildirişlər"

    header.set_unread(5)
    assert "5" in bell_button.accessibleName()


@requires_qt
def test_nav_button_keeps_its_name_when_collapsed(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Daraldılmış sol paneldə mətn silinir — ad qalmalıdır."""
    from src.presentation.widgets.buttons import NavButton

    theme = _themed(qt_app, ThemeMode.LIGHT)
    button = NavButton(
        "fines",
        "Cərimələr",
        icon_name="fine",
        idle_color=theme.color("--color-nav-item-icon"),
        active_color=theme.color("--color-brand-amber"),
    )
    button.set_compact(True)

    assert button.text() == ""
    assert button.accessibleName() == "Cərimələr"


@requires_qt
def test_nav_button_shows_full_title_in_tooltip(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Kəsilən başlıq siçanla da oxunmalıdır.

    Sol panel sabit enlidir; «Ehtiyat Nüsxə və Bərpa» ən uzun maddədir və Qt
    onu «…» ilə kəsir. Tooltip olmasa, tam ad YALNIZ ekran oxuyucusundan
    əlçatan olardı — gözlə oxuyan istifadəçi üçün maddə anlaşılmaz qalırdı.
    """
    from src.presentation.widgets.buttons import NavButton

    theme = _themed(qt_app, ThemeMode.LIGHT)
    button = NavButton(
        "backups",
        "Ehtiyat Nüsxə və Bərpa",
        icon_name="database",
        idle_color=theme.color("--color-nav-item-icon"),
        active_color=theme.color("--color-brand-amber"),
    )

    assert button.toolTip() == "Ehtiyat Nüsxə və Bərpa"


@requires_qt
def test_nav_button_survives_collapse_and_expand(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Panel yığılıb açıldıqda başlıq GERİ QAYITMALIDIR.

    Qüsur tarixi: `set_compact()` mətni `toolTip()`-dən bərpa edir, tooltip
    isə heç yerdə qurulmurdu. Nəticədə ilk yığılmadan sonra `toolTip()` boş
    olur, açılışda `setText("" or "")` işləyir və BÜTÜN maddələr adsız
    qalırdı — yalnız ikonlar. Konstruktorda tooltip qurulduqdan sonra dövrə
    bağlanır; bu test onun təkrar-təkrar işlədiyini təsbit edir.
    """
    from src.presentation.widgets.buttons import NavButton

    theme = _themed(qt_app, ThemeMode.LIGHT)
    button = NavButton(
        "fines",
        "Cərimələr",
        icon_name="fine",
        idle_color=theme.color("--color-nav-item-icon"),
        active_color=theme.color("--color-brand-amber"),
    )

    for _cycle in range(3):
        button.set_compact(True)
        assert button.text() == ""
        assert button.toolTip() == "Cərimələr", "yığılmış halda mətn itdi"

        button.set_compact(False)
        assert button.text() == "Cərimələr", "açılışda başlıq geri qayıtmadı"
        assert button.toolTip() == "Cərimələr"


# --------------------------------------------------------------------------- #
# Tapıntı 8/9 — modal dialoqlarda Enter və ilkin fokus
# --------------------------------------------------------------------------- #


def _default_buttons(dialog: QWidget) -> list[str]:
    """Dialoqdakı defolt düymələrin mətnləri."""
    from PySide6.QtWidgets import QPushButton

    return [button.text() for button in dialog.findChildren(QPushButton) if button.isDefault()]


@requires_qt
@pytest.mark.parametrize(
    ("builder", "expected_default", "focus_attribute"),
    [
        ("catalog", "Yadda saxla", "_name"),
        ("role", "Yarat", "_name"),
        ("migration", "İmtina", "_input"),
        ("restore", "İmtina", "_confirm_input"),
    ],
)
def test_modal_default_button_and_initial_focus(  # type: ignore[no-untyped-def]
    qt_app, builder: str, expected_default: str, focus_attribute: str
) -> None:
    """Enter-in nəticəsi AÇIQ təyin edilməli, fokus ilk məntiqi sahədə olmalıdır.

    ⚠ DAĞIDICI dialoqlarda (`migration`, `restore`) defolt düymə TƏSDİQ DEYİL,
    İMTİNA-dır: Enter-ə təsadüfən basmaq bazanı köçürməməli və ya bərpa
    etməməlidir. Təyin edilməsəydi, Qt ilk `QPushButton`-u («İmtina») onsuz da
    defolt sayardı — lakin bu, TƏSADÜFİ nəticə olardı: düymələrin sırası
    dəyişən kimi Enter təsdiqə keçərdi. Ona görə qərar açıq yazılır.
    """
    from src.domain.value_objects.infrastructure import DatabaseTarget
    from src.presentation.screens.group_c import RoleCreateDialog
    from src.presentation.screens.group_d import RestoreConfirmDialog
    from src.presentation.screens.group_h import CatalogEntryDialog
    from src.presentation.screens.group_i import MigrationConfirmDialog

    theme = _themed(qt_app, ThemeMode.LIGHT)
    builders = {
        "catalog": lambda: CatalogEntryDialog(
            theme, title="Yeni fasilə növü", value_label="Standart müddət"
        ),
        "role": lambda: RoleCreateDialog(theme),
        "migration": lambda: MigrationConfirmDialog(
            theme,
            destination=DatabaseTarget.PRIVATE_SERVER,
            summary="12 cədvəl köçürüləcək",
            warnings=[],
        ),
        "restore": lambda: RestoreConfirmDialog(theme, backup_date="09.08.2026"),
    }

    dialog = builders[builder]()
    _shown(qt_app, dialog)

    assert _default_buttons(dialog) == [expected_default]

    expected_focus = getattr(dialog, focus_attribute).input_widget()
    assert dialog.focusWidget() is expected_focus, (
        "modal açılanda fokus ilk MƏNTİQİ sahədə olmalıdır"
    )


@requires_qt
def test_destructive_modals_do_not_auto_default_the_confirm_button(qt_app) -> None:  # type: ignore[no-untyped-def]
    """`autoDefault` dağıdıcı düymələrdə söndürülməlidir.

    Qt `autoDefault` düyməsi FOKUS ALDIQDA onu müvəqqəti defolt edir. Yalnız
    `setDefault(False)` yazmaq buna görə kifayət deyil: istifadəçi Tab ilə
    «Bərpa Et»-ə çatan kimi Enter yenidən bərpanı işə salardı və qoruma
    sükutla itərdi.
    """
    from src.presentation.screens.group_d import RestoreConfirmDialog

    theme = _themed(qt_app, ThemeMode.LIGHT)
    dialog = RestoreConfirmDialog(theme, backup_date="09.08.2026")
    _shown(qt_app, dialog)

    confirm = dialog._confirm
    assert not confirm.isDefault()
    assert not confirm.autoDefault()


# --------------------------------------------------------------------------- #
# Tapıntı 9 — əsas formalarda ilkin fokus və tab sırası
# --------------------------------------------------------------------------- #


@requires_qt
def test_login_screen_focuses_the_username_and_orders_tabs(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Giriş ekranı açılan kimi istifadəçi adı sahəsi fokusda olmalıdır.

    Fokus `showEvent`-dədir, konstruktorda deyil: ekran örtükdəki yığının bir
    səhifəsidir və konstruktor işlədikdə hələ görünmür — Qt isə gizli widget
    üçün fokus tələbini saxlamır.
    """
    from src.presentation.screens.group_a_entry import AdminLoginScreen

    theme = _themed(qt_app, ThemeMode.LIGHT)
    screen = AdminLoginScreen(theme)
    _shown(qt_app, screen)

    username = screen._username.input_widget()
    password = screen._password.input_widget()
    submit = screen._submit

    assert screen.focusWidget() is username
    assert username.nextInFocusChain() is not None

    # Tab zənciri: ad → şifrə → «Daxil Ol».
    username.setFocus()
    screen.focusNextChild()
    assert screen.focusWidget() is password
    screen.focusNextChild()
    assert screen.focusWidget() is submit
