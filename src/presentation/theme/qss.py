"""Dizayn tokenlərindən Qt Style Sheet (QSS) qurur — Faza 4.1.

──────────────────────────────────────────────────────────────────────────────
NİYƏ ŞABLON, NİYƏ HAZIR .qss FAYLI DEYİL
──────────────────────────────────────────────────────────────────────────────
Qt Style Sheet CSS dəyişənlərini (`var(--color-accent)`) DƏSTƏKLƏMİR. İki
hazır `.qss` faylı (işıqlı/tünd) saxlansaydı, hər rəng iki yerdə təkrarlanar
və biri gec-tez digərindən geri qalardı — üstəlik `check_contrast.py` yalnız
`tokens.py`-ı oxuduğu üçün CI həmin fərqi GÖRMƏZDİ. Ona görə QSS bir dəfə
şablon kimi yazılır və tokenlər icra anında yerinə qoyulur: rəngin yeganə
mənbəyi `tokens.py` olaraq qalır.

──────────────────────────────────────────────────────────────────────────────
`{{--token}}` SİNTAKSİSİ
──────────────────────────────────────────────────────────────────────────────
Şablonda hər token `{{--color-accent}}` şəklində yazılır. Adi `str.format`
istifadə OLUNMUR, çünki QSS-in özündə `{ }` blokları var və onların hamısını
qoşalaşdırmaq şablonu oxunmaz edərdi.

Naməlum token adı SƏSSİZ ötürülmür — `StyleSheetError` atılır. Səhv yazılmış
token QSS-də boş sətir yaradar, Qt isə yararsız qaydanı sükutla ATAR: düymə
sadəcə rəngsiz görünər və səbəbi heç yerdə yazılmaz.
"""

from __future__ import annotations

import re
from typing import Final

from src.shared.exceptions import KompasOSError

#: `{{--token-adı}}` — şablondakı yer tutucular.
_PLACEHOLDER: Final = re.compile(r"\{\{(--[a-z0-9-]+)\}\}")

#: Piksel şəkilçisi tələb edən token prefiksləri (dəyər saf rəqəmdir).
_PX_PREFIXES: Final = (
    "--space-",
    "--radius-",
    "--border-width",
    "--focus-ring-width",
    "--touch-target-min",
    "--font-size-",
)

_HEX_WITH_ALPHA_LENGTH: Final = 8


class StyleSheetError(KompasOSError):
    """QSS şablonunda naməlum və ya yararsız token."""

    user_message = "İnterfeys teması qurula bilmədi."


def _to_qss_value(name: str, raw: str) -> str:
    """Token dəyərini QSS-in anladığı formata çevirir.

    İki çevirmə var:

    1. Ölçü tokenləri `tokens.py`-da saf rəqəmdir (`"8"`) — QSS `8px` gözləyir.
       Rəqəm saxlanılmasının səbəbi odur ki, eyni dəyər Python tərəfdə də
       (`QSpacerItem`, `setFixedHeight`) hesablamada işlədilir və orada `px`
       şəkilçisi maneə olardı.
    2. 8-rəqəmli `#RRGGBBAA` rəngi Qt QSS-də ETİBARSIZDIR — `rgba(...)`-ya
       çevrilir. (Şəffaf örtük rəngi məhz belə yazılıb.)
    """
    if name.startswith(_PX_PREFIXES):
        return f"{raw}px"

    if raw.startswith("#") and len(raw) - 1 == _HEX_WITH_ALPHA_LENGTH:
        red, green, blue, alpha = (int(raw[i : i + 2], 16) for i in (1, 3, 5, 7))
        return f"rgba({red}, {green}, {blue}, {alpha})"

    return raw


def render(template: str, tokens: dict[str, str]) -> str:
    """Şablondakı `{{--token}}` yer tutucularını dəyərlərlə əvəz edir.

    Raises:
        StyleSheetError: Şablonda tokenlər arasında olmayan ad işlədilib.
    """
    unknown: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        value = tokens.get(name)
        if value is None:
            unknown.append(name)
            return ""
        return _to_qss_value(name, value)

    result = _PLACEHOLDER.sub(substitute, template)

    if unknown:
        raise StyleSheetError(
            f"QSS şablonunda naməlum token: {', '.join(sorted(set(unknown)))}",
            context={"unknown_tokens": sorted(set(unknown))},
        )
    return result


# --------------------------------------------------------------------------- #
# Şablon
# --------------------------------------------------------------------------- #
# Variantlar Qt-nin dinamik xüsusiyyət seçiciləri ilə verilir, məsələn:
#
#     button.setProperty("variant", "danger")
#
# Xüsusiyyət widget YARADILDIQDAN SONRA dəyişdirilirsə, Qt üslubu özü yenidən
# hesablamır — `refresh_widget_style()` çağırılmalıdır (aşağıda).

QSS_TEMPLATE: Final = """
/* ===================== ƏSAS ===================== */
/* ──────────────────────────────────────────────────────────────────────────
   NİYƏ BURADA `background-color` YOXDUR
   ──────────────────────────────────────────────────────────────────────────
   Ümumi `QWidget { background-color: … }` qaydası Qt tərəfindən İSTİSNASIZ
   hər widget-ə tətbiq olunur — o cümlədən yalnız yerləşdirmə üçün yaradılan
   boş qablara (`QWidget()` sətir/sütun konteynerləri). Nəticədə həmin qablar
   altındakı səthi ÖRTÜR: kontent sahəsi `--color-content-bg` əvəzinə
   `--color-bg-primary` görünür.

   İşıqlı temada bu nəzərə çarpmır (hər ikisi ağa yaxındır), tünd temada isə
   bütün kontent yanlış tonda qalır. Ona görə fon YALNIZ konkret səthlərə
   verilir (aşağıda), qablar isə şəffaf qalır və altındakı fonu göstərir. */
QWidget {
    color: {{--color-text-primary}};
    font-family: {{--font-family}};
    font-size: {{--font-size-md}};
}

/* Kök səthlər — pəncərə, dialoq və kiosk. */
QDialog,
QWidget#AppWindow,
QWidget#KioskWindow {
    background-color: {{--color-bg-primary}};
}

QWidget:disabled {
    color: {{--color-text-disabled}};
}

/* ===================== MƏTN ===================== */
QLabel[variant="title"] {
    font-size: {{--font-size-xl}};
    font-weight: {{--font-weight-bold}};
}

QLabel[variant="subtitle"] {
    font-size: {{--font-size-lg}};
    font-weight: {{--font-weight-medium}};
}

QLabel[variant="secondary"] {
    color: {{--color-text-secondary}};
    font-size: {{--font-size-sm}};
}

QLabel[variant="success"] { color: {{--color-success}}; }
QLabel[variant="warning"] { color: {{--color-warning}}; }
QLabel[variant="danger"]  { color: {{--color-danger}}; }
QLabel[variant="info"]    { color: {{--color-info}}; }

/* ===================== SƏTHLƏR ===================== */
/* Kart maketdəki dəyərləri işlədir: ağ səth, soyuq-boz sərhəd, 12px künc. */
QFrame[variant="card"] {
    background-color: {{--color-card-bg}};
    border: {{--border-width}} solid {{--color-card-border}};
    border-radius: {{--radius-lg}};
}

/* QEYD: Əvvəllər burada "kartdakı bütün QLabel-lər şəffaf olsun" qaydası var
   idi — ümumi `QWidget { background-color: … }` qaydasını neytrallaşdırmaq
   üçün. Həmin ümumi qayda ARADAN QALDIRILDIQDAN sonra (bax yuxarıdakı izah)
   `QLabel` onsuz da şəffafdır, qayda isə ZİYANLI idi: seçici daha spesifik
   olduğu üçün `QLabel[chip="…"]` nişan fonlarını ƏZİRDİ və status həbləri
   rəngsiz mətn kimi görünürdü. */

QGroupBox {
    background-color: {{--color-bg-surface}};
    border: {{--border-width}} solid {{--color-border-subtle}};
    border-radius: {{--radius-md}};
    margin-top: {{--space-md}};
    padding-top: {{--space-md}};
    font-weight: {{--font-weight-medium}};
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: {{--space-md}};
    padding: 0 {{--space-xs}};
    color: {{--color-text-secondary}};
}

/* ===================== DÜYMƏLƏR ===================== */
QPushButton {
    background-color: {{--color-bg-surface}};
    color: {{--color-text-primary}};
    border: {{--border-width}} solid {{--color-border}};
    border-radius: {{--radius-sm}};
    padding: {{--space-sm}} {{--space-md}};
    min-height: {{--touch-target-min}};
    font-weight: {{--font-weight-medium}};
}

QPushButton:hover  { background-color: {{--color-bg-sunken}}; }
QPushButton:pressed { background-color: {{--color-bg-sunken}}; }

QPushButton:disabled {
    color: {{--color-text-disabled}};
    border-color: {{--color-border-subtle}};
}

QPushButton[variant="primary"] {
    background-color: {{--color-accent}};
    color: {{--color-text-on-accent}};
    border-color: {{--color-accent}};
}

QPushButton[variant="primary"]:hover {
    background-color: {{--color-accent-hover}};
    border-color: {{--color-accent-hover}};
}

QPushButton[variant="primary"]:pressed {
    background-color: {{--color-accent-pressed}};
    border-color: {{--color-accent-pressed}};
}

QPushButton[variant="danger"] {
    background-color: {{--color-danger}};
    color: {{--color-bg-primary}};
    border-color: {{--color-danger}};
}

QPushButton[variant="success"] {
    background-color: {{--color-success}};
    color: {{--color-bg-primary}};
    border-color: {{--color-success}};
}

QPushButton[variant="ghost"] {
    background-color: transparent;
    border-color: transparent;
    color: {{--color-text-secondary}};
}

QPushButton[variant="ghost"]:hover {
    background-color: {{--color-bg-surface}};
    color: {{--color-text-primary}};
}

/* Fokus halqası HƏR İKİ variantda görünür — klaviatura ilə naviqasiya
   (əlçatanlıq) düymənin harada olduğunu göstərməlidir. */
QPushButton:focus,
QLineEdit:focus,
QComboBox:focus,
QCheckBox:focus,
QPlainTextEdit:focus {
    outline: none;
    border: {{--focus-ring-width}} solid {{--color-focus-ring}};
}

/* ===================== GİRİŞ SAHƏLƏRİ ===================== */
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDateEdit, QTimeEdit {
    background-color: {{--color-bg-primary}};
    color: {{--color-text-primary}};
    border: {{--border-width}} solid {{--color-border}};
    border-radius: {{--radius-sm}};
    padding: {{--space-sm}};
    selection-background-color: {{--color-accent}};
    selection-color: {{--color-text-on-accent}};
}

QLineEdit[state="error"], QPlainTextEdit[state="error"] {
    border-color: {{--color-danger}};
}

QLineEdit::placeholder {
    color: {{--color-text-disabled}};
}

QComboBox::drop-down {
    border: none;
    width: {{--space-lg}};
}

QComboBox QAbstractItemView {
    background-color: {{--color-bg-elevated}};
    color: {{--color-text-primary}};
    border: {{--border-width}} solid {{--color-border}};
    selection-background-color: {{--color-accent}};
    selection-color: {{--color-text-on-accent}};
}

/* ===================== CƏDVƏLLƏR ===================== */
QTableWidget, QTableView, QListWidget, QTreeView {
    background-color: {{--color-bg-surface}};
    alternate-background-color: {{--color-bg-sunken}};
    color: {{--color-text-primary}};
    border: {{--border-width}} solid {{--color-border-subtle}};
    border-radius: {{--radius-sm}};
    gridline-color: {{--color-border-subtle}};
}

QTableWidget::item:selected, QListWidget::item:selected, QTreeView::item:selected {
    background-color: {{--color-accent}};
    color: {{--color-text-on-accent}};
}

QHeaderView::section {
    background-color: {{--color-bg-sunken}};
    color: {{--color-text-secondary}};
    border: none;
    border-bottom: {{--border-width}} solid {{--color-border}};
    padding: {{--space-sm}};
    font-weight: {{--font-weight-medium}};
}

/* ===================== PƏNCƏRƏ BAŞLIĞI (CUSTOM TITLE BAR) ===================== */
/* Maket: hündürlük 38px, solda amber loqo kvadratı + "KompasOS", sağda —/□/×.
   Pəncərə çərçivəsiz olduğu üçün bu zolaq Windows-un öz başlığını əvəz edir. */
QWidget#TitleBar {
    background-color: {{--color-titlebar-bg}};
    border-bottom: {{--border-width}} solid {{--color-titlebar-bg}};
}

QWidget#TitleBar QLabel {
    background-color: transparent;
    color: {{--color-titlebar-text}};
    font-size: {{--font-size-sm}};
    font-weight: {{--font-weight-medium}};
}

QWidget#TitleBarLogo {
    background-color: {{--color-brand-amber}};
    border-radius: {{--radius-sm}};
}

/* Pəncərə düymələri: `min-height` sıfırlanır, çünki ümumi QPushButton qaydası
   toxunma hədəfi üçün 44px verir və 38px-lik zolağa sığmazdı. */
QPushButton[variant="window"] {
    background-color: transparent;
    border: none;
    border-radius: 0;
    color: {{--color-titlebar-control}};
    font-size: {{--font-size-sm}};
    font-weight: {{--font-weight-normal}};
    min-height: 0;
    padding: 0;
}

QPushButton[variant="window"]:hover {
    background-color: {{--color-nav-active-bg}};
    color: {{--color-titlebar-text}};
}

QPushButton[variant="window"][action="close"]:hover {
    background-color: {{--color-danger}};
    color: #FFFFFF;
}

/* ===================== NAVİQASİYA (SOL PANEL) ===================== */
QWidget#Sidebar,
QWidget#NavigationSidebar {
    background-color: {{--color-sidebar-bg}};
    border-right: {{--border-width}} solid {{--color-sidebar-border}};
}

/* Bölmə başlığı ("NAVİQASİYA") — böyük hərflər və hərf aralığı QSS-də YOXDUR,
   onlar `widgets/sidebar.py`-da QFont ilə verilir. */
QLabel#SidebarSectionLabel {
    background-color: transparent;
    color: {{--color-text-muted}};
    font-size: {{--font-size-xs}};
    font-weight: {{--font-weight-medium}};
}

QPushButton[variant="nav"] {
    background-color: transparent;
    border: none;
    border-radius: {{--radius-md}};
    color: {{--color-nav-item-text}};
    text-align: left;
    padding: 0 {{--space-md}};
    min-height: 40px;
    max-height: 40px;
    font-weight: {{--font-weight-normal}};
    font-size: {{--font-size-sm}};
}

QPushButton[variant="nav"]:hover {
    background-color: {{--color-neutral-bg}};
    color: {{--color-text-primary}};
}

/* Aktiv maddə maketdə DOLDURULMUŞ sətirdir (sol kənar xətti deyil). */
QPushButton[variant="nav"][active="true"] {
    background-color: {{--color-nav-active-bg}};
    color: {{--color-nav-active-text}};
    font-weight: {{--font-weight-medium}};
}

QPushButton[variant="nav"][active="true"]:hover {
    background-color: {{--color-nav-active-bg}};
}

/* ===================== SƏHİFƏ BAŞLIĞI (HEADER) ===================== */
QWidget#PageHeader {
    background-color: {{--color-header-bg}};
    border-bottom: {{--border-width}} solid {{--color-header-border}};
}

QWidget#PageHeader QLabel { background-color: transparent; }

QLabel#PageTitle {
    color: {{--color-text-primary}};
    font-size: {{--font-size-lg}};
    font-weight: {{--font-weight-medium}};
}

QLabel#PageSubtitle {
    color: {{--color-text-muted}};
    font-size: {{--font-size-sm}};
    font-weight: {{--font-weight-normal}};
}

/* Header-dəki ikon düymələri (tema, zəng) — 34×34, 9px künc. */
QPushButton[variant="icon"] {
    background-color: transparent;
    border: {{--border-width}} solid {{--color-card-border}};
    border-radius: {{--radius-md}};
    min-height: 34px;
    max-height: 34px;
    min-width: 34px;
    max-width: 34px;
    padding: 0;
}

QPushButton[variant="icon"]:hover { background-color: {{--color-neutral-bg}}; }

QPushButton[variant="icon"][active="true"] {
    background-color: {{--color-action-bg}};
    border-color: {{--color-action-bg}};
}

/* ===================== KONTENT SAHƏSİ ===================== */
QWidget#ContentArea,
QWidget#ScreenSurface {
    background-color: {{--color-content-bg}};
}

/* Sürüşdürmə sahələri ŞƏFFAFDIR — adına görə YOX, tipinə görə.
   Əvvəllər qayda `QScrollArea#ContentScroll` idi və yalnız örtükdəki bir
   sahəyə ad verilmişdi; modul daxilindəki digər sahələr (kanban sütunları,
   icazə matrisi, növbə matrisi) qaydadan kənarda qalıb sistem palitrasının
   TÜND fonunu göstərirdi — işıqlı temada ekranın yarısı qara görünürdü.
   Tipə görə seçici yeni sahə əlavə edildikdə də işləyir. */
QScrollArea,
QScrollArea > QWidget,
QScrollArea > QWidget > QWidget {
    background: transparent;
    border: none;
}

/* ===================== ƏSAS HƏRƏKƏT DÜYMƏSİ ===================== */
/* Maketdə əsas düymə işıqlı rejimdə Navy, tünddə Amber-dir — bu, fokus
   halqasının `--color-accent` rəngindən AYRI roldur (bax tokens.py). */
QPushButton[variant="action"] {
    background-color: {{--color-action-bg}};
    color: {{--color-action-text}};
    border: {{--border-width}} solid {{--color-action-bg}};
    border-radius: {{--radius-md}};
    padding: 0 {{--space-lg}};
    min-height: 42px;
    max-height: 42px;
    font-weight: {{--font-weight-medium}};
}

QPushButton[variant="action"]:hover {
    background-color: {{--color-action-hover}};
    border-color: {{--color-action-hover}};
}

QPushButton[variant="action"]:pressed {
    background-color: {{--color-action-pressed}};
    border-color: {{--color-action-pressed}};
}

QPushButton[variant="action"]:disabled {
    background-color: {{--color-neutral-bg}};
    border-color: {{--color-card-border}};
    color: {{--color-text-disabled}};
}

/* İkinci dərəcəli düymə — ağ səth, boz sərhəd (maket: "Keçən aya bax"). */
QPushButton[variant="secondary"] {
    background-color: {{--color-card-bg}};
    color: {{--color-nav-item-text}};
    border: {{--border-width}} solid {{--color-border}};
    border-radius: {{--radius-md}};
    padding: 0 {{--space-lg}};
    min-height: 42px;
    max-height: 42px;
    font-weight: {{--font-weight-normal}};
}

QPushButton[variant="secondary"]:hover { background-color: {{--color-neutral-bg}}; }

/* Seçilmiş segment (Ayarlar → Görünüş) DOLU fon alır — əks halda üç
   düymə eyni görünür və istifadəçi cari temanı təyin edən idarəetmədən
   məhz onu OXUYA BİLMİR. */
QPushButton[variant="secondary"][active="true"] {
    background-color: {{--color-action-bg}};
    color: {{--color-action-text}};
    border-color: {{--color-action-bg}};
    font-weight: {{--font-weight-medium}};
}

/* ===================== YUMŞAQ NİŞANLAR (CHIP) ===================== */
/* Maketdəki status həbləri: yumşaq fon + kalibrlənmiş mətn (bax tokens.py). */
QLabel[chip="success"], QLabel[chip="warning"], QLabel[chip="danger"],
QLabel[chip="info"], QLabel[chip="neutral"] {
    border-radius: {{--radius-md}};
    padding: {{--space-xs}} {{--space-sm}};
    font-size: {{--font-size-sm}};
    font-weight: {{--font-weight-normal}};
}

QLabel[chip="success"] { background-color: {{--color-success-bg}}; color: {{--color-success}}; }
QLabel[chip="warning"] { background-color: {{--color-warning-bg}}; color: {{--color-warning}}; }
QLabel[chip="danger"]  { background-color: {{--color-danger-bg}};  color: {{--color-danger}}; }
QLabel[chip="info"]    { background-color: {{--color-info-bg}};    color: {{--color-info}}; }
QLabel[chip="neutral"] {
    background-color: {{--color-neutral-bg}};
    color: {{--color-text-primary}};
}

/* ===================== FORM SAHƏLƏRİ ===================== */
/* Maket: `height: 46px; border: 1px solid #C9D2E0; border-radius: 9px;
   padding: 0 14px; font-size: 14.5px`. */
QLineEdit[variant="form"],
QComboBox[variant="form"],
QSpinBox[variant="form"],
QDateEdit[variant="form"],
QTimeEdit[variant="form"] {
    background-color: {{--color-card-bg}};
    color: {{--color-text-primary}};
    border: {{--border-width}} solid {{--color-border}};
    border-radius: {{--radius-md}};
    padding: 0 14px;
    font-size: {{--font-size-md}};
}

QLineEdit[variant="form"]:focus,
QComboBox[variant="form"]:focus,
QSpinBox[variant="form"]:focus,
QDateEdit[variant="form"]:focus,
QTimeEdit[variant="form"]:focus {
    border: {{--focus-ring-width}} solid {{--color-focus-ring}};
}

QLineEdit[variant="form"][state="error"],
QComboBox[variant="form"][state="error"] {
    border-color: {{--color-danger}};
}

/* ===================== KÖMƏKÇİ MƏTN ROLLARI ===================== */
QLabel[variant="danger-text"] {
    background-color: transparent;
    color: {{--color-danger}};
    font-size: {{--font-size-sm}};
}

QLabel[variant="muted"] {
    background-color: transparent;
    color: {{--color-text-muted}};
    font-size: {{--font-size-sm}};
}

/* Rəqəm/kod sahələri (saat, xəta kodu, tenant_id) — maketdə IBM Plex Mono. */
QLabel[variant="mono"], QLabel[variant="mono-muted"] {
    background-color: transparent;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: {{--font-size-sm}};
}

QLabel[variant="mono"]       { color: {{--color-text-primary}}; }
QLabel[variant="mono-muted"] { color: {{--color-text-muted}}; }

/* Skeleton (yüklənmə) blokları — maketdə shimmer animasiyası var; QSS
   animasiya dəstəkləmir, ona görə hərəkət `widgets/skeleton.py`-dadır. */
QWidget[variant="skeleton"] {
    background-color: {{--color-skeleton}};
    border-radius: {{--radius-sm}};
}

QWidget[variant="skeleton-alt"] {
    background-color: {{--color-skeleton-alt}};
    border-radius: {{--radius-sm}};
}

/* ===================== AYIRICI ===================== */
QFrame[variant="divider"] {
    background-color: {{--color-divider}};
    border: none;
    max-height: 1px;
    min-height: 1px;
}

QFrame[variant="divider-v"] {
    background-color: {{--color-divider}};
    border: none;
    max-width: 1px;
    min-width: 1px;
}

/* ===================== NİŞANLAR (BADGE) ===================== */
QLabel[badge="success"], QLabel[badge="warning"], QLabel[badge="danger"], QLabel[badge="info"] {
    border-radius: {{--radius-sm}};
    padding: {{--space-xs}} {{--space-sm}};
    font-size: {{--font-size-xs}};
    font-weight: {{--font-weight-medium}};
    color: {{--color-bg-primary}};
}

QLabel[badge="success"] { background-color: {{--color-success}}; }
QLabel[badge="warning"] { background-color: {{--color-warning}}; }
QLabel[badge="danger"]  { background-color: {{--color-danger}}; }
QLabel[badge="info"]    { background-color: {{--color-info}}; }

/* ===================== PIN EKRANI (YÜKSƏK KONTRAST) ===================== */
/* Mağaza işığında oxunmalıdır — ümumi mətn/fon cütü DEYİL, AAA cütü. */
QWidget#PinScreen {
    background-color: {{--color-pin-bg}};
}

QWidget#PinScreen QLabel {
    background-color: transparent;
    color: {{--color-pin-text}};
}

QLineEdit#PinInput {
    background-color: {{--color-pin-bg}};
    color: {{--color-pin-text}};
    border: {{--focus-ring-width}} solid {{--color-pin-text}};
    border-radius: {{--radius-md}};
    font-size: {{--font-size-pin}};
    font-weight: {{--font-weight-bold}};
    padding: {{--space-md}};
}

QPushButton[variant="keypad"] {
    background-color: {{--color-pin-bg}};
    color: {{--color-pin-text}};
    border: {{--focus-ring-width}} solid {{--color-pin-text}};
    border-radius: {{--radius-md}};
    font-size: {{--font-size-lg}};
    font-weight: {{--font-weight-bold}};
    min-height: {{--touch-target-min}};
}

/* ===================== SPLASH ===================== */
QWidget#SplashScreen {
    background-color: {{--color-brand-navy}};
}

QWidget#SplashScreen QLabel {
    background-color: transparent;
    color: {{--color-brand-amber}};
}

/* ===================== DİGƏR ===================== */
QScrollBar:vertical, QScrollBar:horizontal {
    background: transparent;
    border: none;
    width: {{--space-md}};
    height: {{--space-md}};
}

QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: {{--color-border}};
    border-radius: {{--radius-sm}};
    min-height: {{--space-lg}};
    min-width: {{--space-lg}};
}

QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

QToolTip {
    background-color: {{--color-bg-elevated}};
    color: {{--color-text-primary}};
    border: {{--border-width}} solid {{--color-border}};
    padding: {{--space-xs}};
}

QMenu {
    background-color: {{--color-bg-elevated}};
    border: {{--border-width}} solid {{--color-border}};
}

QMenu::item:selected {
    background-color: {{--color-accent}};
    color: {{--color-text-on-accent}};
}

QProgressBar {
    background-color: {{--color-bg-sunken}};
    border: none;
    border-radius: {{--radius-sm}};
    text-align: center;
    color: {{--color-text-primary}};
}

QProgressBar::chunk {
    background-color: {{--color-accent}};
    border-radius: {{--radius-sm}};
}

QCheckBox, QRadioButton {
    spacing: {{--space-sm}};
}

QTabBar::tab {
    background: transparent;
    color: {{--color-text-secondary}};
    padding: {{--space-sm}} {{--space-md}};
    border-bottom: {{--focus-ring-width}} solid transparent;
}

QTabBar::tab:selected {
    color: {{--color-text-primary}};
    border-bottom-color: {{--color-accent}};
}

QStatusBar {
    background-color: {{--color-bg-surface}};
    color: {{--color-text-secondary}};
    border-top: {{--border-width}} solid {{--color-border-subtle}};
}
"""


def build_stylesheet(tokens: dict[str, str]) -> str:
    """Verilmiş tokenlərlə tam QSS mətnini qurur."""
    return render(QSS_TEMPLATE, tokens)


__all__ = ["QSS_TEMPLATE", "StyleSheetError", "build_stylesheet", "render"]
