"""Dark/Light rejimi HƏR ekranda FAKTİKİ işləyirmi.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TESTLƏR VAR
──────────────────────────────────────────────────────────────────────────────
Temanın "işləməsi" iki fərqli şeydir və onları qarışdırmaq asandır:

    1. Palitranın DÜZGÜN olması — `scripts/check_contrast.py` bunu ölçür
       (156 rəng cütü, WCAG AA).
    2. Palitranın EKRANA ÇATMASI — heç bir qapı bunu ölçmürdü.

İkincisi qırıla bilər və qırılmışdı da: `EmployeeHomeScreen` özünə seçicisiz
`background-color` verirdi, Qt həmin elanı bütün uşaqlara yayırdı və kioskun
əsas düyməsi valideynin AÇIQ fonunu götürürdü — ağ mətn açıq fonda, kontrast
1.05:1. Palitra qüsursuz idi; ekrana çatmırdı.

Ona görə burada FAKTİKİ RENDER müqayisə olunur: hər ekran iki temada şəkilə
çevrilir və şəkillər FƏRQLİ olmalıdır. Eyni çıxırsa, ekran temaya tabe deyil —
səbəbi nə olursa olsun (sabit rəng, sızan üslub cədvəli, `WA_StyledBackground`
unudulması).
"""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtCore import Qt

from src.presentation.theme.tokens import ThemeMode
from tests.conftest import requires_qt

pytestmark = [pytest.mark.e2e, pytest.mark.qt]

#: Yalnız `theme` ilə qurula bilən ekranlar — əlavə arqument tələb edənlər
#: aşağıdakı `_EXTRA_ARGS`-dadır.
_SIMPLE_SCREENS: tuple[tuple[str, str], ...] = (
    ("group_c", "DashboardScreen"),
    ("group_c", "PermissionMatrixScreen"),
    ("group_c", "UsersScreen"),
    ("group_c", "ShiftPlanningScreen"),
    ("group_c", "DailyRosterScreen"),
    ("group_c", "ShiftSwapScreen"),
    ("group_d", "BackupScreen"),
    ("group_d", "HealthScreen"),
    ("group_d", "SettingsScreen"),
    ("group_d", "DriveConnectionScreen"),
    ("group_d", "RootControlScreen"),
    ("group_d", "ErpServersScreen"),
    ("group_f", "TasksScreen"),
    ("group_f", "SalesPointsScreen"),
    ("group_f", "FineAppealInboxScreen"),
    ("group_f", "UnassignedSalesScreen"),
    ("group_g", "ProfileScreen"),
    ("group_h", "CatalogScreen"),
    ("group_h", "ReportExportScreen"),
    ("group_h", "HelpCenterScreen"),
    ("group_i", "InfrastructureScreen"),
    ("group_i", "DashboardBuilderScreen"),
    ("group_i", "PluginScreen"),
    ("group_i", "ExceptionsScreen"),
    ("sync_conflicts", "SyncConflictScreen"),
    ("fine_review", "MonthlyFineReviewScreen"),
    ("annual_leave", "AnnualLeaveInboxScreen"),
    ("attrition_risk", "AttritionRiskScreen"),
    ("announcements", "AnnouncementsScreen"),
    ("performance_review", "PerformanceReviewScreen"),
    ("bulk_operations", "BulkOperationsScreen"),
    ("face_control", "FaceEnrollmentScreen"),
    ("face_control", "FaceExemptionScreen"),
)

#: Konstruktoru əlavə arqument tələb edən ekranlar.
_EXTRA_ARGS: dict[str, dict[str, Any]] = {
    "AuditScreen": {"modules": ["Davamiyyət"]},
    "OperatorQueueScreen": {"assigned_stores": ["Bellona 28 May"]},
    "FineAppealScreen": {"reasons": ["Digər"]},
    "EmployeeHomeScreen": {
        "full_name": "Rəşad Məmmədov",
        "position_name": "Satıcı",
        "store_name": "Bellona 28 May",
    },
    "PinPadScreen": {"store_name": "Bellona 28 May", "terminal_name": "Kassa-1"},
    "ProfileScreen": {
        "full_name": "Rəşad Məmmədov",
        "role_name": "Satıcı",
        "store_name": "Bellona 28 May",
        "member_since": "12.03.2024",
    },
    "UnassignedSalesScreen": {"employees": ["Rəşad Məmmədov", "Aysel Quliyeva"]},
}


def _catalog_kwargs() -> dict[str, Any]:
    from src.presentation.widgets.data_table import Column

    return {
        "columns": [Column("Ad"), Column("Vəziyyət", 160)],
        "create_label": "Yeni Növ",
        "empty_title": "Kataloq boşdur",
        "empty_body": "Hələ heç bir növ əlavə edilməyib.",
    }


_WITH_ARGS: tuple[tuple[str, str], ...] = (
    ("group_d", "AuditScreen"),
    ("group_b", "OperatorQueueScreen"),
    ("group_f", "FineAppealScreen"),
    ("group_a_kiosk", "EmployeeHomeScreen"),
    ("group_a_kiosk", "PinPadScreen"),
)

ALL_SCREENS = _SIMPLE_SCREENS + _WITH_ARGS


def _render(qt_app: Any, module: str, name: str, mode: ThemeMode) -> Any:
    from importlib import import_module

    from src.presentation.theme.manager import ThemeManager

    theme = ThemeManager(preference=mode)
    theme.apply(qt_app)

    screen_class = getattr(import_module(f"src.presentation.screens.{module}"), name)
    kwargs = _catalog_kwargs() if name == "CatalogScreen" else _EXTRA_ARGS.get(name, {})
    widget = screen_class(theme, **kwargs)
    widget.resize(1100, 700)
    widget.show()
    qt_app.processEvents()
    image = widget.grab().toImage()
    widget.close()
    return image


@requires_qt
@pytest.mark.parametrize(("module", "name"), ALL_SCREENS, ids=lambda value: value)
def test_screen_renders_differently_in_each_theme(qt_app, module: str, name: str) -> None:  # type: ignore[no-untyped-def]
    """Ekran iki temada EYNİ görünməməlidir.

    Eyni çıxarsa, palitra ekrana çatmır — istifadəçi tünd rejimi seçir, ekran
    isə işıqlı qalır. Bu, bir tokenin səhv olmasından daha pisdir, çünki
    palitra yoxlayıcısı tamamilə yaşıl qalır.
    """
    light = _render(qt_app, module, name, ThemeMode.LIGHT)
    dark = _render(qt_app, module, name, ThemeMode.DARK)

    assert light != dark, (
        f"{name} hər iki temada EYNİ render olunur — tema ekrana çatmır "
        "(sabit rəng? sızan üslub cədvəli? `WA_StyledBackground` unudulub?)"
    )


@requires_qt
@pytest.mark.parametrize(("module", "name"), ALL_SCREENS, ids=lambda value: value)
def test_screen_builds_in_both_themes_without_error(qt_app, module: str, name: str) -> None:  # type: ignore[no-untyped-def]
    """Hər ekran hər iki temada istisna atmadan qurulmalıdır."""
    for mode in (ThemeMode.LIGHT, ThemeMode.DARK):
        image = _render(qt_app, module, name, mode)
        assert not image.isNull(), f"{name} ({mode.value}) boş şəkil verdi"


# --------------------------------------------------------------------------- #
# Oxunaqlıq — mətn və ikon FAKTİKİ olaraq görünürmü
# --------------------------------------------------------------------------- #

#: Render olunmuş şəkildə mətnin fondan ayrılması üçün minimum nisbət.
#:
#: WCAG AA 4.5:1 tələb edir, lakin BURADA ölçülən şey başqadır: bu, tokenlərin
#: nisbəti deyil, PİKSELLƏRİN nisbətidir və antialiasing hər hərfin kənarını
#: fonla qarışdırır, yəni ölçülən dəyər həmişə həqiqi nisbətdən aşağı çıxır.
#: Ona görə hədd aşağı seçilib: burada məqsəd «kifayət qədər kontrastlıdır?»
#: deyil, «ÜMUMİYYƏTLƏ görünürmü?» sualıdır. Token nisbətini
#: `scripts/check_contrast.py` ölçür.
MIN_VISIBLE_RATIO = 1.6

#: «Mürəkkəb» (ink) sayılması üçün minimum PİKSEL SAYI.
#:
#: Faiz payı İŞLƏMİR və bu, ölçmənin ən vacib detalıdır: etiket 1006px enində
#: olur, mətn isə onun cəmi 0.3%-ni tutur. Pay həddi qoysaydıq, mətn pikselləri
#: «səs-küy» sayılıb atılardı və HƏR etiket «görünmür» kimi bayraqlanardı.
#:
#: NİYƏ «BİR RƏNGDƏN N PİKSEL» DEYİL, «CƏMİ N PİKSEL» — ÖLÇÜLMÜŞ SƏBƏB:
#: `appl.md` FAZA 1-dən sonra Inter tətbiqlə birlikdə gəlir (`theme/fonts.py`)
#: və testlər ARTIQ həqiqi qliflərlə render olunur. Əvvəl `offscreen` mühitində
#: şrift yox idi, Qt hər hərfi «tofu» düzbucaqlısı çəkirdi — qalın, TƏK rəngli
#: blok. Həqiqi qlifdə isə 11px-lik «2» rəqəminin bütün mürəkkəbi ~20 pikseldir
#: və antialiasing onu 15-dən çox fərqli çalara yayır: ÖLÇÜLDÜ — ən sıx çalar
#: cəmi 3 piksel. Yəni «bir rəngdən 5 piksel» şərti həqiqi mətni «yoxdur»
#: sayırdı.
#:
#: İndi şərt çalarlar ÜZRƏ TOPLANIR: fondan kifayət qədər fərqlənən pikselin
#: ÜMUMİ sayı bu həddi keçirsə, element görünür. Ağ-üstündə-ağ mətndə belə
#: piksel ÜMUMİYYƏTLƏ olmur, yəni qapı öz işini itirmir.
MIN_INK_PIXELS = 6


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    channels = []
    for raw in rgb:
        value = raw / 255
        channels.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    light, dark = sorted((_relative_luminance(first), _relative_luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _visible_contrast(image: Any) -> float:
    """Fondan ayrılan ƏN kontrastlı «mürəkkəb» nisbəti (bax `MIN_INK_PIXELS`).

    Qaytarılan dəyər belə oxunur: «ən azı `MIN_INK_PIXELS` piksel fondan bu
    nisbətdə (və ya daha çox) fərqlənir». Tək bir piksel nəticəni təyin edə
    bilmir — antialiasing kənarında təsadüfi tünd nöqtə həmişə tapılar —
    lakin nisbət bir rəngin təkrarlanmasından da ASILI DEYİL.
    """
    from collections import Counter

    counter: Counter[tuple[int, int, int]] = Counter()
    width, height = image.width(), image.height()
    # ADDIM 1, ADDIM 2 DEYİL: kiçik nişandakı «0» rəqəmi cəmi bir neçə piksel
    # tutur və hər ikinci pikseli atlasaq, qlif tamamilə sıçrayıb keçilir —
    # nişan «görünmür» kimi bayraqlanardı, halbuki rəqəm yerindədir.
    for y in range(height):
        for x in range(width):
            colour = image.pixelColor(x, y)
            counter[(colour.red(), colour.green(), colour.blue())] += 1

    if not counter:
        return 0.0
    background = counter.most_common(1)[0][0]

    # Çalarlar KONTRASTA görə sıralanır və piksel sayı TOPLANIR: hədd
    # keçiləndə həmin nisbət nəticədir (bax docstring).
    ranked = sorted(
        ((_contrast(background, rgb), count) for rgb, count in counter.items()),
        key=lambda pair: pair[0],
        reverse=True,
    )
    accumulated = 0
    for ratio, count in ranked:
        accumulated += count
        if accumulated >= MIN_INK_PIXELS:
            return ratio
    return 1.0


@requires_qt
@pytest.mark.parametrize(
    ("text_colour", "should_be_visible"),
    [("#FFFFFF", False), ("#4A5568", True)],
    ids=["ağ-üstündə-ağ", "tünd-üstündə-açıq"],
)
def test_the_ink_metric_itself_separates_visible_from_invisible(  # type: ignore[no-untyped-def]
    qt_app, text_colour: str, should_be_visible: bool
) -> None:
    """Ölçünün ÖZÜ yoxlanılır — qapı yalnız düzgün ölçdüyü qədər dəyərlidir.

    `MIN_INK_PIXELS` həddi antialiasing-ə görə yumşaldılıb (bax onun izahı);
    yumşaldılma qapını KORLAMAMALIDIR. Burada eyni kiçik mətn iki dəfə
    çəkilir — biri fonla eyni rəngdə, digəri oxunaqlı — və nəticə ayrılmalıdır.
    Bu test olmasaydı, hədd bir gün «hər şey görünür» deyən dəyərə sürüşə
    bilərdi və heç kim fərq etməzdi.
    """
    from PySide6.QtWidgets import QLabel

    _ = qt_app
    label = QLabel("2")
    label.setFixedSize(22, 22)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet(f"background-color: #FFFFFF; color: {text_colour}; font-size: 11px;")
    label.show()
    qt_app.processEvents()

    ratio = _visible_contrast(label.grab().toImage())
    label.close()

    assert (ratio >= MIN_VISIBLE_RATIO) is should_be_visible, f"ölçülən nisbət: {ratio:.2f}:1"


def _text_widgets(root: Any) -> list[Any]:
    from PySide6.QtWidgets import QLabel, QPushButton

    found = []
    for widget in root.findChildren(QLabel) + root.findChildren(QPushButton):
        if not widget.isVisible() or widget.width() < 8 or widget.height() < 8:
            continue
        has_text = bool(widget.text().strip())
        has_icon = hasattr(widget, "icon") and not widget.icon().isNull()
        if has_text or has_icon:
            found.append(widget)
    return found


@requires_qt
@pytest.mark.parametrize("mode_name", ["LIGHT", "DARK"])
@pytest.mark.parametrize(("module", "name"), ALL_SCREENS, ids=lambda value: value)
def test_no_invisible_text_or_icons(qt_app, module: str, name: str, mode_name: str) -> None:  # type: ignore[no-untyped-def]
    """Mətni/ikonu olan heç bir element fonu ilə birləşməməlidir.

    Bu qapı `check_contrast.py`-ın ölçə BİLMƏDİYİ qüsuru tutur: palitra
    düzgün, lakin element onu almır (sızan üslub cədvəli, sabit rəng, səhv
    valideyn). Kioskun əsas düyməsi məhz belə itmişdi — ağ mətn açıq fonda.
    """
    from importlib import import_module

    from src.presentation.theme.manager import ThemeManager

    mode = ThemeMode.LIGHT if mode_name == "LIGHT" else ThemeMode.DARK
    theme = ThemeManager(preference=mode)
    theme.apply(qt_app)

    screen_class = getattr(import_module(f"src.presentation.screens.{module}"), name)
    kwargs = _catalog_kwargs() if name == "CatalogScreen" else _EXTRA_ARGS.get(name, {})
    widget = screen_class(theme, **kwargs)
    widget.resize(1100, 700)
    widget.show()
    qt_app.processEvents()

    # ÖLÇMƏ EKRANIN ŞƏKLİNDƏN KƏSİLİR + KƏSİLMİŞ ELEMENT ATLANIR.
    #
    # Üç yol sınandı, ikisi səhv nəticə verdi:
    #   * elementin ÖZÜNÜ `grab()` etmək — `QLabel` şəffafdır, Qt boş buferi
    #     qaytarır (ölçüldü: hər iki temada `#1e1e1e`), fon uydurma olur;
    #   * VALİDEYNİ `grab()` etmək — valideyn özü də çox vaxt şəffafdır, yəni
    #     eyni problem bir pillə yuxarı sürüşür;
    #   * EKRANIN şəkli — fon HƏQİQİdir (kompozisiya nəticəsidir), lakin
    #     sürüşmə sahəsində viewport-un altında qalan element şəkildə YOXDUR.
    #
    # Sonuncu yol doğrudur, şərtlə ki, çəkilməyən element ATLANSIN.
    # `visibleRegion()` məhz bunu deyir: kəsilmiş widget üçün boşdur. Bu,
    # «görünmür» (qüsur) ilə «aşağıda qalıb» (normal) arasındakı yeganə
    # etibarlı fərqdir.
    from PySide6.QtCore import QPoint

    root_image = widget.grab().toImage()
    invisible = []
    for child in _text_widgets(widget):
        if child.visibleRegion().isEmpty():
            continue
        origin = child.mapTo(widget, QPoint(0, 0))
        cropped = root_image.copy(origin.x(), origin.y(), child.width(), child.height())
        if cropped.isNull() or cropped.width() < 4:
            continue
        ratio = _visible_contrast(cropped)
        if ratio < MIN_VISIBLE_RATIO:
            label = child.text().strip() or f"<ikon {type(child).__name__}>"
            invisible.append(f"{label!r} ({ratio:.2f}:1)")
    widget.close()

    assert invisible == [], f"{name} ({mode_name}) — görünməyən element: {invisible}"
