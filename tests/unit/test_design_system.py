"""Dizayn sistemi — tokenlər, QSS və ikonlar — Faza 4.2.

Bu testlər PySide6-SIZ işləyən hissələri yoxlayır (token bütövlüyü, QSS
şablonu, statusun xəritələnməsi). Widget davranışı `tests/e2e`-dədir, çünki
orada `QApplication` lazımdır.
"""

from __future__ import annotations

import pytest

from src.presentation.theme.qss import QSS_TEMPLATE, StyleSheetError, build_stylesheet, render
from src.presentation.theme.tokens import (
    DARK_THEME,
    LIGHT_THEME,
    METRICS,
    TYPOGRAPHY,
    ThemeMode,
    theme_tokens,
)

# --------------------------------------------------------------------------- #
# Tokenlər
# --------------------------------------------------------------------------- #


def test_themes_have_identical_keys() -> None:
    """Bir temada unudulan token digərində boş QSS sətri yaradar."""
    assert set(LIGHT_THEME) == set(DARK_THEME)


def test_every_colour_token_is_a_hex_string() -> None:
    """`check_contrast.py` yalnız hex gözləyir — hesablanmış dəyər onu qırar."""
    for theme in (LIGHT_THEME, DARK_THEME):
        for name, value in theme.items():
            assert value.startswith("#"), f"{name} hex deyil: {value!r}"
            assert len(value) in {4, 7, 9}, f"{name} yararsız hex: {value!r}"


def test_theme_tokens_includes_metrics_and_typography() -> None:
    tokens = theme_tokens(ThemeMode.LIGHT)
    assert set(METRICS) <= set(tokens)
    assert set(TYPOGRAPHY) <= set(tokens)
    assert set(LIGHT_THEME) <= set(tokens)


def test_system_mode_is_rejected() -> None:
    """`SYSTEM` palitra deyil — əvvəlcə həll olunmalıdır."""
    with pytest.raises(ValueError, match="SYSTEM"):
        theme_tokens(ThemeMode.SYSTEM)


@pytest.mark.parametrize(
    "token",
    [
        "--color-titlebar-bg",
        # Pəncərə düymələrinin hover səthi — əvvəl `--color-nav-active-bg`
        # işlənirdi və işıqlı temada zolağın fonu ilə eyni Navy idi (hover
        # görünmürdü). Bax `tests/unit/test_window_chrome.py`.
        "--color-titlebar-control-hover",
        "--color-sidebar-bg",
        "--color-nav-active-bg",
        "--color-content-bg",
        "--color-card-bg",
        "--color-action-bg",
        "--color-text-muted",
        "--color-success-bg",
    ],
)
def test_shell_tokens_present_in_both_themes(token: str) -> None:
    """Maketdən gələn örtük tokenləri hər iki temada olmalıdır."""
    assert token in LIGHT_THEME
    assert token in DARK_THEME


def test_action_colour_differs_between_themes() -> None:
    """Maket: işıqlı rejimdə Navy, tünddə Amber — eyni olsalar səhv olardı."""
    assert LIGHT_THEME["--color-action-bg"] != DARK_THEME["--color-action-bg"]


# --------------------------------------------------------------------------- #
# QSS
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("mode", [ThemeMode.LIGHT, ThemeMode.DARK])
def test_stylesheet_builds_for_both_themes(mode: ThemeMode) -> None:
    stylesheet = build_stylesheet(theme_tokens(mode))
    assert stylesheet
    assert "{{" not in stylesheet, "Yerinə qoyulmamış token qalıb"


def test_unknown_token_raises() -> None:
    """Səhv yazılmış token SƏSSİZ keçməməlidir."""
    with pytest.raises(StyleSheetError, match="--color-yoxdur"):
        render("QWidget { color: {{--color-yoxdur}}; }", theme_tokens(ThemeMode.LIGHT))


def test_size_tokens_get_px_suffix() -> None:
    result = render("a { padding: {{--space-md}}; }", theme_tokens(ThemeMode.LIGHT))
    assert "16px" in result


def test_alpha_hex_becomes_rgba() -> None:
    """Qt QSS 8-rəqəmli hex-i anlamır."""
    result = render("a { background: {{--color-overlay}}; }", theme_tokens(ThemeMode.DARK))
    assert result.strip().startswith("a { background: rgba(")


def test_template_references_only_known_tokens() -> None:
    """Şablonda mövcud olmayan token qalmasın — hər iki tema ilə yoxlanılır."""
    for mode in (ThemeMode.LIGHT, ThemeMode.DARK):
        render(QSS_TEMPLATE, theme_tokens(mode))


# --------------------------------------------------------------------------- #
# Əlçatanlıq — QSS mətni səviyyəsində yoxlanan qaydalar
# --------------------------------------------------------------------------- #


def _without_comments(template: str) -> str:
    """`/* … */` bloklarını çıxarır.

    Şərhlərdə rəng kodları QƏSDƏN yazılır — məhz hansı dəyərin niyə rədd
    edildiyini izah etmək üçün (`#DCE2EC` = 1.30:1). Onları hardcode saymaq
    izahatı yazmağı cəzalandırardı, halbuki layihənin üslub qaydası əksini
    tələb edir.
    """
    import re

    return re.sub(r"/\*.*?\*/", "", template, flags=re.DOTALL)


def _rule_body(selector: str) -> str:
    """Verilmiş seçicinin elan blokunu qaytarır.

    Sadə `split("}")` İŞLƏMİR: şablondakı `{{--token}}` yer tutucuları da
    qıvrım mötərizə ehtiva edir və blok onların ortasından kəsilərdi. Ona görə
    əvvəlcə yer tutucular neytrallaşdırılır.
    """
    import re

    neutral = re.sub(r"\{\{(--[a-z0-9-]+)\}\}", r"<\1>", QSS_TEMPLATE)
    start = neutral.index(f"{selector} {{") + len(selector) + 2
    return neutral[start : neutral.index("}", start)]


def test_no_hardcoded_colour_in_template() -> None:
    """Şablonda `#RRGGBB` yazılmır — rəngin yeganə mənbəyi `tokens.py`-dır.

    Auditdə tapılmış qüsur: `variant="window"][action="close"]:hover` içində
    `color: #FFFFFF` HARDCODE edilmişdi. İşıqlı temada bu görünmürdü (fon onsuz
    da tünd qırmızıdır), tünd temada isə xəta rəngi açıq mərcandır və ağ simvol
    orada cəmi 3.34:1 verirdi. Hardcode edilmiş dəyər tərifə görə temaya görə
    dəyişmir, yəni kontrast qapısı onu HEÇ VAXT görə bilməzdi.

    Qayda `tokens.py` modul başlığında yazılıb; burada MAŞINLA yoxlanılır.
    """
    import re

    hardcoded = re.findall(r"#[0-9A-Fa-f]{3,8}\b", _without_comments(QSS_TEMPLATE))

    assert hardcoded == [], (
        "QSS şablonunda hardcode rəng var — `tokens.py`-a token əlavə edin: "
        f"{sorted(set(hardcoded))}"
    )


def test_placeholder_uses_its_own_token() -> None:
    """Placeholder deaktiv mətn tokenini işlətməməlidir.

    Placeholder AKTİV sahənin içindədir: WCAG-in "inactive component"
    istisnası ona şamil olunmur və tam 4.5:1 tələb olunur. Deaktiv mətn
    tokeni isə (qəsdən) daha solğundur.
    """
    rule = _rule_body("QLineEdit::placeholder")

    assert "<--color-text-placeholder>" in rule
    assert "--color-text-disabled" not in rule


def test_icon_button_border_uses_the_strong_token() -> None:
    """Fonsuz ikon düyməsinin sərhədi kart sərhədi ola bilməz (1.30:1)."""
    rule = _rule_body('QPushButton[variant="icon"]')

    assert "<--color-border-strong>" in rule
    assert "--color-card-border" not in rule


#: Fokus halqası olmadan qalmış variantlar (auditin 5-ci tapıntısı) + `nav`.
#:
#: `nav` auditin siyahısında YOX idi, lakin eyni qüsurdan əziyyət çəkirdi:
#: onun bloku da `border: none` yazır və ümumi `QPushButton:focus` qaydasından
#: SONRA gəlir. Siyahıya əlavə edilməsi düzəlişi eyni sinif qüsurun HAMISINA
#: şamil edir.
_FOCUSABLE_VARIANTS = ["window", "nav", "icon", "action", "secondary", "keypad"]

#: Variantın fokus qaydasını tapan selektor. Demək olar ki hamısı `:focus`
#: psevdo-sinfidir — İSTİSNA `window`-dur: orada halqa `[keyfocus="true"]`
#: dinamik xüsusiyyətinə bağlıdır, çünki Qt pəncərə açılanda fokusu başlıq
#: zolağının «kiçilt» düyməsinə verir və `:focus` hər açılışda görünən ağ
#: kvadrat çəkirdi (bax `qss.py` və `buttons.py::focusInEvent`).
#:
#: Testin ÖLÇDÜYÜ ŞEY DƏYİŞMİR: qaydanın variantın əsas blokundan SONRA
#: gəlməsi. Yalnız qaydanın adı fərqlidir.
_FOCUS_SELECTOR = {"window": '[keyfocus="true"]'}


@pytest.mark.parametrize("variant", _FOCUSABLE_VARIANTS)
def test_variant_focus_rule_comes_after_its_base_rule(variant: str) -> None:
    """`:focus` qaydası variantın ƏSAS blokundan SONRA gəlməlidir.

    Qt QSS CSS2 spesifikliyini işlədir və BƏRABƏRLİKDƏ sonuncu qayda qalib
    gəlir: `QPushButton[variant="action"]` (bir atribut) ilə
    `QPushButton:focus` (bir psevdo-sinif) eyni spesifiklikdədir. Ona görə
    ümumi fokus qaydası variant bloklarından ƏVVƏL yazıldıqda onların
    `border` elanı tərəfindən sükutla əzilirdi.

    Bu test SIRAYA baxır, çünki qüsurun səbəbi məhz sıra idi: qayda mövcud
    idi, sadəcə qüvvəyə minmirdi. Faktiki render `tests/e2e`-də yoxlanılır.
    """
    base = QSS_TEMPLATE.index(f'QPushButton[variant="{variant}"] {{')
    selector = _FOCUS_SELECTOR.get(variant, ":focus")
    focus = QSS_TEMPLATE.index(f'QPushButton[variant="{variant}"]{selector}')

    assert focus > base, (
        f"`{variant}` variantının fokus qaydası əsas blokdan ƏVVƏL gəlir — "
        "Qt onu variantın `border` elanı ilə əzəcək"
    )


def test_generic_focus_rule_never_disables_the_outline() -> None:
    """`outline: none` yalnız ONU ƏVƏZ EDƏN sərhədlə birlikdə ola bilər."""
    for block in QSS_TEMPLATE.split("}"):
        if "outline: none" in block:
            assert "border:" in block, (
                "Fokus konturu söndürülür, əvəzinə isə sərhəd verilmir — "
                f"klaviatura göstəricisi itir:\n{block}"
            )


@pytest.mark.parametrize(
    "token",
    ["--color-text-placeholder", "--color-border-strong"],
)
def test_new_accessibility_tokens_exist_in_both_themes(token: str) -> None:
    """Yeni token bir temada unudulsa, orada QSS sətri boş qalar."""
    assert token in LIGHT_THEME
    assert token in DARK_THEME


def test_every_icon_button_call_site_passes_an_accessible_name() -> None:
    """Yalnız-ikon düymə hər çağırış yerində AÇIQ ad almalıdır.

    Fabrika `accessible_name` boş olduqda `tooltip`-ə düşür — adsız qalmaqdansa
    təxmini ad yaxşıdır. Lakin bu ehtiyat yol QAYDA deyil: tooltip qısa
    göstərişdir ("Yuxarı"), ekran oxuyucusu isə düyməni kontekstsiz oxuyur və
    on sətir boyu eyni "Yuxarı" səslənməsi heç nə demir.

    Ona görə yoxlama MƏNBƏ MƏTNİNDƏDİR: yeni çağırış yeri əlavə edən adam adı
    unudarsa, qüsur ekran oxuyucusu ilə sınaqda yox, burada üzə çıxır.
    """
    import ast
    from pathlib import Path

    presentation = Path(__file__).resolve().parents[2] / "src" / "presentation"
    missing: list[str] = []

    for path in presentation.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "icon_button"
                and not any(keyword.arg == "accessible_name" for keyword in node.keywords)
            ):
                missing.append(f"{path.name}:{node.lineno}")

    assert missing == [], f"`accessible_name` verilməyən icon_button çağırışları: {missing}"


def test_brand_colours_were_not_touched_by_the_accessibility_pass() -> None:
    """QIRMIZI XƏTT: brend rəngləri əlçatanlıq düzəlişindən sonra da eynidir.

    Bütün kontrast düzəlişləri TONU deyil, İŞIQLIĞI dəyişməklə aparılıb.
    Brend tokenləri isə heç bir istiqamətdə tərpənməməlidir — onlar loqo və
    splash üçündür və tanınma dəyəri məhz dəyişməzlikdədir.
    """
    from src.presentation.theme.tokens import BRAND_AMBER, BRAND_NAVY

    assert BRAND_NAVY == "#0B1D3A"
    assert BRAND_AMBER == "#F5A623"
    for theme in (LIGHT_THEME, DARK_THEME):
        assert theme["--color-brand-navy"] == BRAND_NAVY
        assert theme["--color-brand-amber"] == BRAND_AMBER


# --------------------------------------------------------------------------- #
# İşçi statusu
# --------------------------------------------------------------------------- #


def test_worker_status_maps_from_domain_enums() -> None:
    """Maketdəki beş vəziyyət domen enum-larından düzgün alınmalıdır."""
    from src.domain.entities.attendance_record import CheckInStatus
    from src.presentation.widgets.worker_status import WorkerStatus

    assert WorkerStatus.from_domain(CheckInStatus.NOT_STARTED) is WorkerStatus.NOT_STARTED
    assert (
        WorkerStatus.from_domain(CheckInStatus.PENDING_VERIFICATION)
        is WorkerStatus.PENDING_CHECK_IN
    )
    assert WorkerStatus.from_domain(CheckInStatus.VERIFIED) is WorkerStatus.VERIFIED


def test_leave_status_overrides_check_in() -> None:
    """İcazədə olan işçi "Mağazada" görünməməlidir — operator onu gözləyir."""
    from src.domain.entities.attendance_record import CheckInStatus
    from src.domain.entities.leave_request import LeaveStatus
    from src.presentation.widgets.worker_status import WorkerStatus

    assert (
        WorkerStatus.from_domain(CheckInStatus.VERIFIED, LeaveStatus.OUTSIDE)
        is WorkerStatus.OUTSIDE
    )
    assert (
        WorkerStatus.from_domain(CheckInStatus.VERIFIED, LeaveStatus.PENDING_RETURN_VERIFICATION)
        is WorkerStatus.PENDING_RETURN
    )


def test_pending_states_are_not_actionable() -> None:
    """Təsdiq gözləyən işçi təkrar sorğu göndərə bilməməlidir."""
    from src.presentation.widgets.worker_status import WorkerStatus

    assert not WorkerStatus.PENDING_CHECK_IN.is_actionable
    assert not WorkerStatus.PENDING_RETURN.is_actionable
    assert WorkerStatus.NOT_STARTED.is_actionable


def test_every_status_has_azerbaijani_text() -> None:
    """Bölmə 9: interfeysdə İngiliscə placeholder qalmamalıdır."""
    from src.presentation.widgets.worker_status import WorkerStatus

    for status in WorkerStatus:
        assert status.label_az.strip()
        assert status.hint_az.strip()
        assert status.action_az.strip()
        assert status.color_token.startswith("--color-")


# --------------------------------------------------------------------------- #
# İkonlar
# --------------------------------------------------------------------------- #


def test_icon_set_is_not_empty() -> None:
    from src.presentation.widgets import icons

    assert len(icons.available()) >= 30


def test_unknown_icon_raises() -> None:
    from src.presentation.widgets.icons import IconNotFoundError, _document

    with pytest.raises(IconNotFoundError, match="yoxdur"):
        _document("belə-ikon-yoxdur", "#000000", 1.5)


def test_icon_document_embeds_colour() -> None:
    """Rəng SVG-yə yazılmalıdır — əks halda ikon həmişə qara görünərdi."""
    from src.presentation.widgets.icons import _document

    document = _document("bell", "#F5A623", 1.5).decode()
    assert 'stroke="#F5A623"' in document
    assert 'viewBox="0 0 16 16"' in document


# --------------------------------------------------------------------------- #
# Tipoqrafiya — QSS-in `setFont()`-u əzməsinə qarşı qoruma
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("size", [13, 15, 17, 22, 26, 34])
def test_heading_size_is_not_overridden_by_qss(qt_app, size: int) -> None:  # type: ignore[no-untyped-def]
    """Maketin başlıq şkalası (13–34px) QSS tərəfindən yastılanmamalıdır.

    Qt-də QSS xüsusiyyəti proqram vasitəsilə verilmiş `QFont`-u ÜSTƏLƏYİR.
    Ona görə ümumi `QWidget { font-size }` və ya `#PageTitle { font-size }`
    qaydası bütün başlıqları bir ölçüyə salırdı — 73 çağırış nöqtəsi maketdən
    fərqli görünürdü və `size` parametri səssizcə təsirsiz qalırdı.
    """
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.widgets.primitives import title_label

    ThemeManager(preference=ThemeMode.LIGHT).apply(qt_app)
    label = title_label("Nümunə", size=size)
    label.ensurePolished()

    assert label.font().pixelSize() == size


def _system_has_a_fixed_pitch_font() -> bool:
    """Sistemdə ÜMUMİYYƏTLƏ sabit enli şrift varmı.

    Bəzi başsız mühitlərdə (`QT_QPA_PLATFORM=offscreen`, fontconfig-siz
    konteyner) Qt-nin şrift bazası TAM BOŞ olur — `QFontDatabase.families()`
    sıfır element qaytarır. Belə mühitdə "mono sabit enlidirmi" sualının
    cavabı bizim kodumuzdan asılı deyil: seçiləcək şrift yoxdur.
    """
    from PySide6.QtGui import QFontDatabase

    return any(QFontDatabase.isFixedPitch(name) for name in QFontDatabase.families())


def test_mono_role_resolves_to_a_fixed_pitch_font(qt_app) -> None:  # type: ignore[no-untyped-def]
    """`mono` rolu ƏSLİNDƏ sabit enli şriftlə render olunmalıdır.

    Ad `tokens.py`-dakı `--font-family-mono`-dan gəlir; siyahının ilk üzvü
    (IBM Plex Mono) quraşdırılmaya bilər, ona görə burada konkret ad DEYİL,
    şriftin sabit enli olması yoxlanılır — maketin rəqəm sütunlarını şaquli
    düzən xassə məhz budur.

    Test bir müddət CI-da qırılırdı: QSS-ə ailə SİYAHISI yazılırdı, Qt isə
    onun yalnız BİRİNCİ adını götürür (CSS fallback zənciri QSS-də yoxdur).
    Həll `resolve_mono_family`-dədir — indi QSS-ə tək, mövcud ad yazılır.
    """
    from PySide6.QtGui import QFontInfo

    from src.presentation.theme.manager import ThemeManager
    from src.presentation.widgets.primitives import mono_label

    if not _system_has_a_fixed_pitch_font():
        pytest.skip("Mühitdə heç bir sabit enli şrift yoxdur — yoxlanacaq bir şey yoxdur")

    ThemeManager(preference=ThemeMode.LIGHT).apply(qt_app)
    label = mono_label("12.08 09:58")
    label.ensurePolished()

    assert QFontInfo(label.font()).fixedPitch()


def test_mono_family_resolution_prefers_an_installed_name(qt_app) -> None:  # type: ignore[no-untyped-def]
    """`resolve_mono_family` QSS-ə MÖVCUD ad yazmalıdır, siyahı yox.

    Bu, yuxarıdakı testin səbəb tərəfidir: nəticə (sabit enli render) mühitdən
    asılıdır, seçim məntiqi isə asılı DEYİL və hər yerdə yoxlanıla bilər.
    """
    from PySide6.QtGui import QFontDatabase

    from src.presentation.theme.manager import resolve_mono_family

    resolved = resolve_mono_family('"Yoxdur Bir", "Yoxdur İki", monospace')
    assert "," not in resolved, "QSS-ə siyahı yazılmamalıdır — Qt yalnız ilkini götürür"

    available = set(QFontDatabase.families())
    if available:
        name = resolved.strip('"')
        assert name == "monospace" or name in available, (
            f"Seçilmiş şrift sistemdə yoxdur: {resolved}"
        )


def test_table_footnote_wraps_instead_of_widening_the_screen(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Uzun qeyd sətri sarılmalıdır, ekranı genişləndirməməlidir.

    Ekranlar bir `QStackedWidget`-i paylaşır və yığın uşaqlarının ƏN GENİŞİNİ
    götürür. Sarılmayan qeyd sətri ona görə YALNIZ öz ekranını deyil, BÜTÜN
    ekranları kəsir — üfüqi sürüşdürmə zolağı hər yerdə peyda olur.
    """
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.widgets.data_table import Column, DataTable

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)

    long_note = (
        "ANTİ-FRAUD: operator sərbəst məbləğ təyin edə bilmir — yalnız burada "
        "təsdiqlənmiş növü və onun standart qiymətini seçir. Deaktiv edilən növ "
        "tarixi qeydlərdə OLDUĞU KİMİ qalır."
    )
    table = DataTable([Column("Ad"), Column("Dəyər", 120)], theme, footnote=long_note)
    table.ensurePolished()

    from PySide6.QtWidgets import QLabel

    notes = [child for child in table.findChildren(QLabel) if child.text().startswith("ANTİ-FRAUD")]
    assert notes, "qeyd sətri tapılmadı"
    assert notes[0].wordWrap(), "qeyd sətri sarılmır — ekran genişlənəcək"
