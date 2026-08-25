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
/* Şrift AİLƏSİ və ÖLÇÜSÜ burada verilmir — hər ikisi tətbiq səviyyəsindədir
   (`ThemeManager.apply`). Ümumi `QWidget` qaydası onları versəydi, hər
   widget-in `setFont()` ilə istədiyi ölçü əzilərdi və maketin başlıq şkalası
   (13–34px) bir dəyərə yastılanardı — bax həmin metodun izahı. */
QWidget {
    color: {{--color-text-primary}};
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

/* Kartın İÇİNDƏKİ alt-qutu — maketdə `11px` (developer panelindəki
   telemetriya/ticket/crash blokları). Kartdan 1px kiçik künc təsadüfi deyil:
   eyni radius iç-içə iki səthi bir-birinə "yapışdırır" və iyerarxiya itir. */
QFrame[variant="panel"] {
    background-color: {{--color-card-bg}};
    border: {{--border-width}} solid {{--color-card-border}};
    border-radius: {{--radius-panel}};
}

/* Üzən və ya mərkəzi İRİ səth — dəstək paneli, lisenziya kartı (`14px`). */
QFrame[variant="modal"] {
    background-color: {{--color-card-bg}};
    border: {{--border-width}} solid {{--color-card-border}};
    border-radius: {{--radius-modal}};
}

/* SEÇİLMİŞ KART (1C Bağlantı Sihirbazının növ-kartları, 1c.md UX tələbi 1).

   NİYƏ HƏM SƏRHƏD, HƏM FON, HƏM DƏ (kodda) İŞARƏ:
   Spesifikasiya "seçilmiş kart Amber/vurğu rəngi ilə çərçivələnir" deyir, lakin
   RƏNG TƏK SİQNAL OLA BİLMƏZ (WCAG 1.4.1) — deuteranopiya ilə amber sərhəd boz
   sərhəddən seçilmir. Ona görə üç əlamət birlikdə işləyir: sərhəd RƏNGİ dəyişir,
   sərhəd ENİ 1px-dən fokus halqası eninə qalxır və kartın içindəki işarə
   ("✓ Seçildi" nişanı) yalnız seçilmiş kartda görünür (bax `group_d.py`).

   Fon `--color-accent-subtle`-dir: üzərindəki mətn cütləri `check_contrast.py`-a
   ƏLAVƏ EDİLİB (əsas mətn 15.25:1 / 14.03:1, solğun mətn 5.12:1 / 6.04:1). */
QFrame[variant="card"][selected="true"] {
    background-color: {{--color-accent-subtle}};
    border: {{--focus-ring-width}} solid {{--color-accent}};
}

/* ƏLÇATMAZ KART — COM növü Windows-dan kənarda (1c.md UX tələbi 1).
   Kart GİZLƏDİLMİR: yoxluq istifadəçini "niyə yalnız iki seçim var?" sualı ilə
   tək qoyardı. Fon çökür və sərhəd solur; SƏBƏB isə mətnlə yazılır — deaktiv
   görünüş tək başına "niyə?" sualına cavab vermir. */
QFrame[variant="card"][unavailable="true"] {
    background-color: {{--color-bg-sunken}};
    border: {{--border-width}} solid {{--color-border-subtle}};
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
    border-radius: {{--radius-control}};
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

/* DEAKTİV — funksional qüsur düzəlişi (VİZUAL FAZA #0).
   `QPushButton:disabled` (yuxarıda) YALNIZ `color`/`border-color` sıfırlayır,
   `background-color`-a TOXUNMUR — variant seçicisi ONDAN daha SPESİFİK
   olduğu üçün `[variant="primary"]`-in `--color-accent` fonu KASKADDA QALIB
   QALIRDI. Nəticə: deaktiv əsas düymə TAM güclü accent fonu ilə render
   olunurdu, istifadəçi onu klikləmə üçün AKTİV zənn edirdi. `[variant=
   "action"]:disabled` ilə EYNİ cütü işlədir (`--color-text-disabled` /
   `--color-neutral-bg`, `scripts/check_contrast.py`-da ARTIQ TƏSDİQLƏNİB —
   "Deaktiv hərəkət düyməsi", light 3.85:1 / dark 4.48:1) — YENİ cüt YOX. */
QPushButton[variant="primary"]:disabled {
    background-color: {{--color-neutral-bg}};
    border-color: {{--color-card-border}};
    color: {{--color-text-disabled}};
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
   (əlçatanlıq) düymənin harada olduğunu göstərməlidir.

   GİRİŞ SAHƏLƏRİ (`QLineEdit`/`QComboBox`/`QPlainTextEdit`) BURADA YOXDUR —
   VİZUAL FAZA #6 (alt-xətt naxışı, aşağıda) qəsdən çıxarır. Səbəb
   SPESİFİKLİK BƏRABƏRLİYİDİR: bu qayda da, aşağıdakı sahə-spesifik fokus
   qaydası da eyni `Tip:pseudo-sinif` formasındadır (Qt/CSS spesifikliyi
   eynidir), yəni son sözü SƏTIR SIRASI deyir. Bu qayda burada qalsaydı,
   onun `border: 2px solid` (DÖRD tərəfli) tərifi sahə-spesifik `border-
   bottom`-u KEÇƏRDİ və fokusda köhnə DÖRDBUCAQ QUTU geri qayıdardı —
   dizaynın bütün məqsədini sükutla pozardı. */
QPushButton:focus,
QCheckBox:focus {
    outline: none;
    border: {{--focus-ring-width}} solid {{--color-focus-ring}};
}

/* ===================== GİRİŞ SAHƏLƏRİ ===================== */
/* SAHƏ DOLDURULMUŞ SƏTHDİR, AĞ QUTU DEYİL.
   ─────────────────────────────────────────────────────────────────────────
   Əvvəl sahə ağ fonda (`--color-bg-primary`) 3:1 kontrastlı sərhədlə
   çəkilirdi. Kontrast tələbi ödənirdi, LAKİN nəticə sərt idi: parlaq ağ
   daxili sahə ilə tünd çərçivə arasındakı fərq gözə «cizgi» kimi dəyirdi və
   kartın ÖZÜ də ağ olduğu üçün sahə səthdən yalnız həmin cizgi ilə ayrılırdı.

   İndi sahənin İÇİ bir pillə çökür (`--color-bg-surface`): sərhəd eyni
   tokendə qalır (yəni 1.4.11 zəmanəti POZULMUR), lakin daxili işıqlıq
   azaldığı üçün çərçivə «kəsici xətt» kimi deyil, səthin kənarı kimi
   oxunur. Fokusda sahə AĞA qalxır — yəni aktiv sahə səthdən qabağa çıxır
   (macOS/iOS forma naxışı).

   Doldurma 8 → 10/12: mətn kursoru ilə çərçivə arasındakı məsafə əvvəl
   sıxdı; 12px üfüqi doldurma `variant="form"` sahələri ilə də eyni sıraya
   düşür (14 → 12, hər ikisi 4px şəbəkəsində). */
/* `QDateTimeEdit` NİYƏ HƏR YERDƏ `QDateEdit`/`QTimeEdit` İLƏ BİRLİKDƏ (VİZUAL
   FAZA #0b): Qt-də bu, `QDateEdit`/`QTimeEdit`-in AYRI (bacı) sinfidir, heç
   birindən miras ALMIR — `group_f.py`-də quraşdırılanda seçicilər onu
   TANIMIRDI və sahə HƏR İKİ temada Qt-nin DEFOLT (stilsiz) görünüşü ilə
   render olunurdu. Düzəliş YALNIZ ad əlavəsidir, YENİ qayda YOX. */
/* QUTU GEDİR, ALT XƏTT GƏLİR (VİZUAL FAZA #6, istifadəçi qərarı).
   ─────────────────────────────────────────────────────────────────────────
   DÖRD-TƏRƏFLİ QUTU NİYƏ ATILDI: `--color-border` (#86868B) orta-tünd boz
   tondur, çünki 1.4.11-in 3:1 həddini DAŞIMALI idi — sahənin fonu
   (`--color-bg-surface`) isə kartın ağ fonundan cəmi 1.09:1 fərqlənir,
   yəni tünd sərhəd sahənin harada başladığını göstərən YEGANƏ vizual
   siqnal idi. Nəticə: parlaq daxil + tünd DÖRD-tərəfli çərçivə "köhnə
   forma" hissi yaradırdı (macOS/iOS deyil, klassik masaüstü qutusu).

   3:1 İNDİ NECƏ ÖDƏNİR: `--color-border` HƏMİN token olaraq qalır, sadəcə
   YALNIZ alt kənarda çəkilir (`border-bottom`) — rəng, qalınlıq və
   yoxlanılan kontrast nisbəti (`--color-border` / `--color-bg-primary`,
   `scripts/check_contrast.py`-də "Sərhəd/ayırıcı" cütü) DƏYİŞMİR, sadəcə
   HANSI TƏRƏFDƏ çəkildiyi dəyişir. Üst/yan tərəflər indi sərhədsizdir —
   onların fərqləndirməsini `--color-bg-surface` doldurması aparır, forma
   şəklini isə alt xətt təyin edir (doldurulmuş sahə + alt xətt, Material
   naxışı).

   RADİUS BÖLÜNÜR: üst künclər yumşaq qalır, alt künclər 0-dır — əks halda
   alt xətt künclərdə kəsilib "sınıq" görünərdi. */
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDateEdit, QTimeEdit,
QDateTimeEdit {
    background-color: {{--color-bg-surface}};
    color: {{--color-text-primary}};
    border: none;
    border-bottom: {{--border-width}} solid {{--color-border}};
    border-top-left-radius: {{--radius-control}};
    border-top-right-radius: {{--radius-control}};
    border-bottom-left-radius: 0;
    border-bottom-right-radius: 0;
    padding: 10px 12px;
    selection-background-color: {{--color-accent}};
    selection-color: {{--color-text-on-accent}};
}

/* Hover — alt xətt BİR PİLLƏ güclənir. `--color-border-strong` məhz bunun
   üçün qalır: token silinmədi, rolu dəyişdi (əvvəl başlıqdakı ikon
   düyməsinin çərçivəsi idi, indi sahənin hover kənarı). Hər iki halda
   ölçülən şey eynidir — 3:1 kontrastlı idarəetmə kənarı, sadəcə YALNIZ
   alt tərəfdə (`border-color` → `border-bottom-color`). */
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover,
QComboBox:hover, QSpinBox:hover, QDateEdit:hover, QTimeEdit:hover,
QDateTimeEdit:hover {
    border-bottom-color: {{--color-border-strong}};
}

/* Fokus — sahə səthdən QALXIR: fon ağa (yüksəldilmiş səthə) keçir və
   alt xətt qalınlaşıb (1px → 2px) vurğu rənginə keçir. İki siqnal birlikdə
   işləyir, yəni rəngi ayırd edə bilməyən istifadəçi üçün də fokus görünür.

   BÖRDER BURADA AÇIQ YAZILIR, ÜMUMİ FOKUS QAYDASINDAN GÖZLƏNMİR — yuxarıdakı
   `QPushButton:focus, QCheckBox:focus` qaydası bu tipləri artıq ƏHATƏ
   ETMİR (bax həmin qaydanın şərhi); qutunun geri qayıtmaması üçün alt-xətt
   davranışı burada, YALNIZ sahələr üçün təyin olunur.

   PADDİNG-BOTTOM 1PX AZALIR — hündürlük SIÇRAMASIN deyə: 1px → 2px alt
   xətt keçidi `padding-bottom`-u 1px azaltmaqla kompensasiya edilir
   (`data_table.py`-dəki "görünməz sərhəd" naxışının EYNİSİ, fərq ondadır
   ki, orada sərhəd HƏMİŞƏ ayrılır, burada isə YALNIZ fokusda kiçilir —
   nəticə eynidir: ümumi hündürlük dəyişmir). */
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QComboBox:focus, QSpinBox:focus, QDateEdit:focus, QTimeEdit:focus,
QDateTimeEdit:focus {
    background-color: {{--color-bg-elevated}};
    border-bottom: {{--focus-ring-width}} solid {{--color-focus-ring}};
    padding-bottom: 9px;
}

/* Deaktiv sahə — çökük səth, solğun mətn: «yazıla bilməz» rəngdən ƏVVƏL
   FORMADAN oxunur. */
QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled,
QComboBox:disabled, QSpinBox:disabled, QDateEdit:disabled, QTimeEdit:disabled,
QDateTimeEdit:disabled {
    background-color: {{--color-bg-sunken}};
    color: {{--color-text-disabled}};
    border-bottom-color: {{--color-border-subtle}};
}

QLineEdit[state="error"], QPlainTextEdit[state="error"] {
    border-bottom-color: {{--color-danger}};
}

/* Placeholder DEAKTİV mətn DEYİL — sahə aktivdir və istifadəçi ondan nə
   yazacağını öyrənir. WCAG 1.4.3-ün "inactive component" istisnası buna
   TƏTBİQ OLUNMUR, ona görə `--color-text-disabled` (3.09:1 işıqlıda) əvəzinə
   tam 4.5:1 hədəfinə kalibrlənmiş ayrıca token işlədilir. */
QLineEdit::placeholder {
    color: {{--color-text-placeholder}};
}

/* VİZUAL FAZA #6 DÜZƏLİŞİ — `background-color`/`subcontrol-*` ƏLAVƏ OLUNDU.
   ─────────────────────────────────────────────────────────────────────────
   İLKİN YOXLAMA SƏHV İDİ: `border: none` təkbaşına KİFAYƏT ETMİR. Qt-nin
   sənədləşdirilmiş davranışı budur — `::drop-down` alt-kontroluna
   `background-color` AÇIQ təyin edilməyəndə Qt native platform üslubuna
   (Windows-da bu maşında) qayıdır və o, öz çərçivəli/haşiyəli "düymə"
   fonunu çəkir; nəticə sağ tərəfdə şaquli ayırıcı xətt + qutulu ox sahəsi
   kimi görünür — QSS-in `border: none`-u bu native fon çəkilişini
   BLOKLAMIR, çünki NÖVBƏTİ addım (fon) hələ CSS-ə həvalə edilməmişdi.

   Fon `transparent` olanda alt-kontrol artıq QComboBox-un ÖZ doldurulmuş
   fonunu göstərir (heç bir ayrı səth yaratmır) və `subcontrol-origin`/
   `subcontrol-position` açıq yazılanda Qt bu alt-kontrolu TAM CSS-yönümlü
   kimi tanıyır — native fallback YOX olur. Ox NATİV `PE_IndicatorArrowDown`
   ilə qalır (xüsusi ikon TƏYİN OLUNMUR), yəni görünüşü dəyişmir, YALNIZ
   ətrafındakı qutu/xətt itir. */
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    border: none;
    background-color: transparent;
    width: {{--space-lg}};
}

/* İKİNCİ ADDIM YAZILDI, SONRA GERİ ÇIXARILDI — bax aşağıdakı ÜÇÜNCÜ addımın
   şərhi. Burada YALNIZ `[variant="form"]` üçün `::drop-down` TƏKRARI qalır
   (`::down-arrow` YOX): Qt-nin alt-kontrol kaskadı dinamik `[variant]`
   xüsusiyyəti ilə seçilmiş `QComboBox`-a AD-SİZ `::drop-down` qaydasını
   avtomatik VERMİR (ölçülüb: `new_task_dialog`/`fine_entry`-dəki formalı
   seçicilərdə eyni bevel qaldı). Görünüş TƏKRARLANIR, çünki Qt-nin özü
   BURADA miras vermir. */
QComboBox[variant="form"]::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    border: none;
    background-color: transparent;
    width: {{--space-lg}};
}

/* ALTINCI ADDIM — EYNİ ÜÇ MÜALİCƏ `QDateEdit`/`QDateTimeEdit`-in TƏQVİM
   düyməsinə DƏ (`setCalendarPopup(True)` — `group_f.py`-dəki "Son tarix",
   `group_b.py`/`support_inbox.py`-dəki tarix seçiciləri). `QComboBox`-da
   işləyən reseptin EYNİSİ: fon/sərhəd şəffaflaşdırılır, `::drop-down`
   CSS-ə tam həvalə edilir (bax yuxarıdakı `QComboBox::drop-down` şərhi —
   səbəb TƏKRARLANMIR). `QTimeEdit::drop-down` da PROFİLAKTİK əlavə olunur
   (kodda `setCalendarPopup` İŞLƏDİLMİR, lakin `QTimeEdit` `QDateTimeEdit`-
   dən miras alır, subcontrol NƏZƏRİ mövcuddur — gələcək istifadə üçün
   eyni tələyə düşməsin). */
QDateEdit::drop-down, QTimeEdit::drop-down, QDateTimeEdit::drop-down,
QDateEdit[variant="form"]::drop-down, QTimeEdit[variant="form"]::drop-down,
QDateTimeEdit[variant="form"]::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    border: none;
    background-color: transparent;
    width: {{--space-lg}};
}

/* `QSpinBox`/`QDateEdit`/`QTimeEdit`/`QDateTimeEdit`-in `::up-button`/
   `::down-button`-u — `QComboBox::drop-down` ilə EYNİ alt-kontrol
   memarlığı, ona görə EYNİ qaydaya tabedir (bax aşağıdakı ÜÇÜNCÜ addım:
   bevel-i aradan qaldıran əsl amil `padding-right`-dır, bu qayda ONUN
   YANINDA lazımdır ki, düymələrin ÖZÜ də şəffaf/haşiyəsiz qalsın).
   `::up-arrow`/`::down-arrow` BURADA QƏSDƏN YOXDUR — bax ALTINCI addım
   (aşağıda) — indi RUNTIME ikonla birlikdə əlavə olunurlar. */
QSpinBox::up-button, QSpinBox::down-button,
QDateEdit::up-button, QDateEdit::down-button,
QTimeEdit::up-button, QTimeEdit::down-button,
QDateTimeEdit::up-button, QDateTimeEdit::down-button {
    border: none;
    background: transparent;
    width: {{--space-md}};
}

/* ÜÇÜNCÜ DÜZƏLİŞ — HƏQİQİ KÖK SƏBƏB TAPILDI, PİKSEL SƏVİYYƏSİNDƏ
   YOXLANDI (`QWidget.grab()` + piksel oxuma, ZOOM skrinşot deyil — bax
   commit tarixçəsi).
   ─────────────────────────────────────────────────────────────────────────
   Yuxarıdakı iki düzəliş (`background-color: transparent` + açıq
   `::down-arrow`) TƏK BAŞINA kifayət etmirdi, çünki əsl səbəb BAŞQA idi:
   sahənin ÖZ `padding`-i sağda alt-kontrol üçün YER AYIRMIRDI (`padding:
   0 12px` — sol/sağ EYNİ). Qt-nin RƏSMİ "Customizing QComboBox" nümunəsi
   məhz buna görə ASİMMETRİK doldurma işlədir (`padding: 1px 18px 1px 3px`)
   — kifayət qədər sağ boşluq AYRILMAYANDA Qt alt-kontrolu CSS-ə TAM
   HƏVALƏ ETMİR, native "kompleks kontrol" çəkilişinə (bevel daxil) geri
   qayıdır, `::drop-down`-un ÖZ qaydaları TƏK BAŞINA ora TƏSİR ETMİR.
   (DÜZƏLİŞ, DÖRDÜNCÜ addımdan sonra: `::down-arrow`-un TƏSİRSİZ olduğu
   iddiası SƏHV idi — o, OXUN ÖZÜNÜ aparırdı, bevel-i yox. Bax aşağı.)

   Sağ padding YALNIZ alt-kontrolu olan BEŞ tipə (`QComboBox`/`QSpinBox`/
   `QDateEdit`/`QTimeEdit`/`QDateTimeEdit`) əlavə olunur — `QLineEdit`/
   `QPlainTextEdit`/`QTextEdit`-in belə bir alt-kontrolu yoxdur, onlara
   əlavə sağ boşluq lazımsız asimmetriya yaradardı.

   SINAQ: 220px enində, hər iki temada, `grab()`-dan oxunan piksel
   sətirlərində sağ kənarda TƏK BİR fon rəngi qaldı — açıq/tünd xətt,
   bevel İZİ YOXDUR. */
QComboBox, QSpinBox, QDateEdit, QTimeEdit, QDateTimeEdit {
    padding-right: 28px;
}

QComboBox[variant="form"],
QSpinBox[variant="form"],
QDateEdit[variant="form"],
QTimeEdit[variant="form"],
QDateTimeEdit[variant="form"] {
    padding-right: 28px;
}

/* DÖRDÜNCÜ ADDIM — REAL Windows platformasında yoxlandı (`app.platformName()
   == "windows"`, offscreen DEYİL): `padding-right` bevel-i doğrudan da
   apardı, LAKİN ox üçbucağı da GETMİŞDİ — sahə sağda boş fonla bitirdi.
   Səbəb özümüzün İKİNCİ addımdakı `QComboBox::down-arrow` qaydası imiş:
   Qt-nin sənədləşdirilmiş qaydasına görə `::down-arrow`-a HƏR HANSI stil
   verilib, LAKİN `image` təyin edilməyəndə, Qt oxu BOŞ (heç nə) çəkir —
   customizasiya olunmamış vəziyyətdə isə native primitiv (`PE_
   IndicatorArrowDown`) özü çəkilirdi. Yəni `::down-arrow` qaydası bevel-i
   YOX, OXUN ÖZÜNÜ aparırmış — ikisi TƏSADÜFƏN eyni committə düşdüyü üçün
   səbəb-nəticə qarışmışdı.

   Həll (o an üçün): `QComboBox::down-arrow` VƏ `QComboBox[variant="form"]
   ::down-arrow` qaydaları TAMAMİLƏ ÇIXARILDI. `::drop-down` (fon/sərhəd) VƏ
   `padding-right` QALDI — bevel-i onlar apardı, ox isə YENİDƏN nativ yolla
   çəkildi (LAKİN real Windows-da o da GÖRÜNMƏDİ — bax BEŞİNCİ addım). */

/* BEŞİNCİ ADDIM — RUNTIME-DA YARADILAN İKON (Hipotez 3-ün UCUZ variantı,
   statik asset/`.spec`/`infra` koordinasiyası OLMADAN).
   ─────────────────────────────────────────────────────────────────────────
   Real Windows-da (offscreen DEYİL) sınandı: nativ `PE_IndicatorArrowDown`
   HEÇ VAXT görünmədi (DÖRDÜNCÜ addımdan ƏVVƏL DƏ) — ox YOX idi, sadəcə boş
   sahə. CSS-üçbucaq həlli (BEŞİNCİ addımdan ƏVVƏLKİ sınaq, Hipotez 2) DƏ
   uğursuz oldu: Qt bu alt-kontrolda "transparent" sərhədi şəffaf ÇƏKMİR
   (piksel sınağı: 3 rəngli sərhədlə diaqonal keçid GÖRÜNÜR, `transparent`
   ilə isə bütün qutu dolu qalır — sübutla, təxminlə DEYİL).

   Həll: ikon `widgets/icons.py`-dakı `_BODIES["chevron_down"]` SVG
   gövdəsindən RUNTIME-da (`theme/manager.py::resolve_caret_down_icon`)
   `QPixmap` kimi çəkilir və keş qovluğuna (`%PROGRAMDATA%\\KompasOS\
   icon_cache\\`) YAZILIR — heç bir yeni fayl `.spec`-ə DÜŞMÜR, çünki ikonun
   ÖZÜ artıq Python kodunda (SVG mətni) mövcuddur. Sonuncu sətir
   `ThemeManager.stylesheet()`-də HƏR açılış/tema-keçidində YENİDƏN
   hesablanan tam CSS bəyanatıdır (`"image: url(...);"` YA DA boş sətir) —
   bax `resolve_caret_down_icon` VƏ `tokens.py`-dakı placeholder şərhi. Boş
   qalanda bu blok effektiv OLARAQ boşdur, yəni tətbiq DÖRDÜNCÜ addımın
   vəziyyətinə (bevel yox, ox yox) sükutla qayıdır — ÇÖKMÜR.

   `setCalendarPopup(True)` olan `QDateEdit`/`QDateTimeEdit`-də bu, TƏQVİM
   düyməsinin oxudur (ayrıca qayda, aşağıda) — TƏK, tam-hündürlük düymə
   olduğu üçün `center right` DÜZGÜNDÜR (`QComboBox`-la EYNİ həndəsə). */
QComboBox::down-arrow, QComboBox[variant="form"]::down-arrow {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 10px;
    height: 10px;
    {{--icon-caret-down-rule}}
}

/* ALTINCI ADDIM (davamı) — TƏQVİM düyməsinin oxu (`QDateEdit`/
   `QDateTimeEdit`, `::drop-down` — yuxarıdakı ALTINCI addımın davamı).
   `QComboBox::down-arrow` İLƏ EYNİ HƏNDƏSƏ: `::drop-down` TAM hündürlük
   tutur, ona görə `center right`. */
QDateEdit::down-arrow, QDateEdit[variant="form"]::down-arrow,
QDateTimeEdit::down-arrow, QDateTimeEdit[variant="form"]::down-arrow {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 10px;
    height: 10px;
    {{--icon-caret-down-rule}}
}

/* YEDDİNCİ ADDIM — `QSpinBox`/`QTimeEdit`-in ADDIM (stepper) oxları
   (`::up-arrow`/`::down-arrow`, `setCalendarPopup` YOXDUR — İKİ AYRI,
   üst-üstə YIĞILMIŞ düymə, `QComboBox`-un TƏK tam-hündürlük düyməsindən
   FƏRQLİ). Ona görə həndəsə DƏ fərqlidir: `top right`/`bottom right` —
   `center right` yazılsaydı hər iki ox eyni nöqtəyə (widget-in ORTASINA)
   düşərdi, üst/alt düymələrin ÖZ yarısına DEYİL.

   `QDateEdit`/`QDateTimeEdit` bu qrupda YOXDUR: `setCalendarPopup(True)`
   olduqda Qt addım düymələrini GİZLƏDİR (yalnız təqvim düyməsi qalır,
   yuxarıdakı ALTINCI addım) — addım oxu qaydası onlarda heç vaxt işə
   düşmür, əlavə etmək lazımsız seçici olardı.

   `chevron_up` — `icons.py`-dakı `chevron_down`-un ŞAQULİ GÜZGÜSÜ, EYNİ
   runtime-keş mexanizmi (`resolve_caret_up_icon`, `--icon-caret-up-rule`). */
QSpinBox::up-arrow, QSpinBox[variant="form"]::up-arrow,
QTimeEdit::up-arrow, QTimeEdit[variant="form"]::up-arrow {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 10px;
    height: 10px;
    {{--icon-caret-up-rule}}
}

QSpinBox::down-arrow, QSpinBox[variant="form"]::down-arrow,
QTimeEdit::down-arrow, QTimeEdit[variant="form"]::down-arrow {
    subcontrol-origin: padding;
    subcontrol-position: bottom right;
    width: 10px;
    height: 10px;
    {{--icon-caret-down-rule}}
}

QComboBox QAbstractItemView {
    background-color: {{--color-bg-elevated}};
    color: {{--color-text-primary}};
    border: {{--border-width}} solid {{--color-border}};
    selection-background-color: {{--color-accent}};
    selection-color: {{--color-text-on-accent}};
}

/* Açılan menyu (header-dəki hesab menyusu — RECOVERY-1).
   Rənglər AÇILAN SİYAHI ilə EYNİDİR və bu, qəsdəndir: ikisi də «üzən
   səth»dir, fərqli tonda olsaydılar eyni ekranda iki müxtəlif açılan
   element görünərdi. Stilləşdirilməsəydi Qt sistem palitrasını işlədər və
   tünd rejimdə ağ menyu çıxardı. */
QMenu {
    background-color: {{--color-bg-elevated}};
    color: {{--color-text-primary}};
    border: {{--border-width}} solid {{--color-border}};
    border-radius: {{--radius-sm}};
    padding: {{--space-xs}};
}

QMenu::item {
    padding: {{--space-xs}} {{--space-md}};
    border-radius: {{--radius-sm}};
}

QMenu::item:selected {
    background-color: {{--color-accent}};
    color: {{--color-text-on-accent}};
}

QMenu::separator {
    height: {{--border-width}};
    background-color: {{--color-border-subtle}};
    margin: {{--space-xs}} 0;
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

/* Sütun başlığı maketdə böyük hərfli MONO mətndir (`DataTable` özü də belə
   qurur) — Qt-nin öz cədvəl başlığı da eyni görünməlidir, əks halda iki
   cədvəl tipi yan-yana fərqli oxunur. */
QHeaderView::section {
    background-color: {{--color-bg-sunken}};
    color: {{--color-text-secondary}};
    border: none;
    border-bottom: {{--border-width}} solid {{--color-border}};
    padding: {{--space-sm}};
    font-family: {{--font-family-mono}};
    font-size: {{--font-size-xs}};
    font-weight: {{--font-weight-medium}};
}

/* `DataTable`-in ÖZ sətri (`TableRow`) — Qt cədvəli deyil, adi `QWidget`.
   Sətir klik edilə bilir, deməli klaviatura ilə də seçilə bilməlidir; fokus
   halqası üçün yer nişanlarda olduğu kimi əvvəlcədən ayrılır. Sətrin daxili
   kənar boşluğu Python tərəfdə həmin 2px qədər azaldılıb (`data_table.py`),
   ona görə sətir hündürlüyü maketdəki kimi qalır. */
QWidget[variant="table-row"] {
    border: {{--focus-ring-width}} solid transparent;
    border-radius: {{--radius-sm}};
}

/* Bildiriş sətri — eyni naxış (bax `screens/group_g.py`). */
QWidget[variant="list-row"] {
    border: {{--focus-ring-width}} solid transparent;
    border-radius: {{--radius-sm}};
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

/* Maketdə `width/height: 16px; border-radius: 5px`. */
QWidget#TitleBarLogo {
    background-color: {{--color-brand-amber}};
    border-radius: {{--radius-badge}};
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

/* Hover fonu ÖZ tokenindədir. Əvvəl `--color-nav-active-bg` idi və işıqlı
   temada o da `BRAND_NAVY`-dir — yəni başlıq zolağının fonu ilə eyni rəng
   (1.00:1) və hover halı GÖRÜNMÜRDÜ. Bax `tokens.py`, həmin tokenin izahı.

   `color:` qaydası mətn üçündür; ikon `QIcon`-dur və QSS onu boyamır — həmin
   rəngi `WindowButton` özü təkrarlayır (bax `buttons.py`). İki yerdə olması
   qəsdəndir: burada mətn ehtiyatı, orada ikon. */
/* `[hover="true"]` — QSS-in `:hover` psevdo-sinfinə ƏLAVƏ, onu əvəz etmir.
   Snap Layouts rejimində "böyüt" düyməsi qeyri-müştəri sahədir və Qt ora
   siçan hadisəsi göndərmir; `:hover` heç vaxt işə düşmür (bax
   `shell/native_chrome.py`). Dinamik xüsusiyyət həmin boşluğu bağlayır. */
QPushButton[variant="window"]:hover,
QPushButton[variant="window"][hover="true"] {
    background-color: {{--color-titlebar-control-hover}};
    color: {{--color-titlebar-text}};
}

/* Mətn rəngi TOKEN-dəndir, hardcode `#FFFFFF` deyil: tünd temada xəta rəngi
   açıq mərcandır (`#EF5A5A`) və ağ simvol onun üzərində cəmi 3.34:1 verirdi —
   13px simvol üçün AA 4.5:1 tələb edir. `--color-bg-primary` işıqlıda onsuz da
   ağdır (6.54:1 dəyişməz qalır), tünddə isə Navy-yə çevrilir (5.02:1).
   Bu, adi `variant="danger"` düyməsinin ARTIQ işlətdiyi naxışdır. */
QPushButton[variant="window"][action="close"]:hover,
QPushButton[variant="window"][action="close"][hover="true"] {
    background-color: {{--color-danger}};
    color: {{--color-bg-primary}};
}

/* ===================== NAVİQASİYA (SOL PANEL) ===================== */
QWidget#Sidebar,
QWidget#NavigationSidebar {
    background-color: {{--color-sidebar-bg}};
    border-right: {{--border-width}} solid {{--color-sidebar-border}};
}

/* Böyük hərfli bölmə etiketi — həm sol paneldə ("NAVİQASİYA", "SİSTEM"),
   həm də kartların içində ("ŞƏXSİ MƏLUMAT", "BU AYIN XÜLASƏSİ").
   Böyük hərflər və hərf aralığı QSS-də YOXDUR — onlar `primitives.py`-da
   QFont ilə verilir. Şrift ailəsi mono-dur: maketdə bu etiket `IBM Plex
   Mono` ilə yazılır və onu adi mətndən məhz şrift fərqi ayırır. */
/* «NAVİQASİYA» ETİKETİ MONO ŞRİFTDƏN ÇIXARILDI.

   İstifadəçi hesabatı: etiket «NAVIOASIYA» kimi görünürdü. Mətn DOĞRU idi
   (`az_upper("Naviqasiya")` → `NAVİQASİYA`, doctest ilə qorunur) — problem
   RENDERDƏ idi: bu qayda `--font-family-mono` tələb edir, həmin ailə isə bu
   sinif maşınlarda HƏLL OLUNMUR (`CLAUDE.md` §2 qeydi:
   `test_mono_role_resolves_to_a_fixed_pitch_font` məhz buna görə atlanır).
   Qt əvəzedici şrift seçir və o, `İ`-nin nöqtəsini, `Q`-nun quyruğunu itirir.

   Mono şrift `tokens.py` başlığında izah olunan İŞ üçündür: rəqəmləri sütunda
   düzmək (ID, versiya, məbləğ). Bölmə etiketi rəqəm daşımır — sütun
   düzülüşünə ehtiyacı yoxdur, yəni mono onun üçün heç vaxt lazım deyildi.
   İnterfeys şrifti + hərf aralığı (`primitives.section_label`) referans
   maketdəki (`navbar.jpg`) «MAIN MENU» görünüşünü onsuz da verir. */
QLabel#SectionLabel {
    background-color: transparent;
    color: {{--color-text-muted}};
    font-family: {{--font-family}};
    font-size: {{--font-size-xs}};
    font-weight: {{--font-weight-medium}};
}

/* HÜNDÜRLÜK ARTIQ BURADA ƏDƏD DEYİL.

   Əvvəl `min-height: 40px; max-height: 40px` yazılırdı və bu, sükutla
   `metrics.NAV_ITEM_HEIGHT`-i ÜSTƏLƏYİRDİ: Python tərəfdə ölçü dəyişəndə
   panel görünüşdə eyni qalırdı. «Maddələr iç-içədir» şikayətinin bir hissəsi
   məhz bu ikili mənbədən gəlirdi.

   `padding` SOL və SAĞ üçün eynidir — aktiv maddənin fon-bloku mətn+ikonu
   simmetrik əhatə etsin deyə (navbar.md, PROBLEM 1 bənd 3). Şaquli padding
   VERİLMİR: hündürlük onsuz da sabitdir və şaquli padding onu «içəridən»
   sıxaraq mətni yuxarı sürüşdürərdi. */
QPushButton[variant="nav"] {
    background-color: transparent;
    border: none;
    border-radius: {{--radius-control}};
    color: {{--color-nav-item-text}};
    text-align: left;
    padding: 0 {{--space-md}};
    min-height: {{--nav-item-height}};
    max-height: {{--nav-item-height}};
    font-weight: {{--font-weight-normal}};
    font-size: {{--font-size-sm}};
}

/* Daraldılmış panel: ikon mərkəzdə, mətn YOXDUR (navbar.jpg-dəki nazik
   zolaq). Sol padding sıfırlanır — əks halda ikon 64px-lik zolağın sol
   yarısına sıxışır və ikonlar mərkəz oxundan sürüşür. */
QPushButton[variant="nav"][compact="true"] {
    text-align: center;
    padding: 0;
}

QPushButton[variant="nav"]:hover {
    background-color: {{--color-neutral-bg}};
    color: {{--color-text-primary}};
}

/* Aktiv maddə maketdə DOLDURULMUŞ sətirdir — VİZUAL FAZA #3 buna bir sol
   kənar xətti (lövbər) ƏLAVƏ EDİR, doldurmanı ƏVƏZ ETMİR.
   `--color-focus-ring-on-dark` (`#F5A623`) SEÇİLİB, `--color-accent` YOX:
   işıqlı temada `--color-accent` kontrast üçün `#9A5F00`-a tənzimlənir
   (bax `kompasos-ui` skill-i), bu sərhəd isə HƏR İKİ temada `--color-nav-
   active-bg` (`#2E3440`, hər iki palitrada EYNİ) üzərində 3:1 saxlamalıdır
   — `scripts/check_contrast.py`-da bu CÜT ARTIQ VAR ("Fokus halqası (aktiv
   nav)", 6.16:1), YENİ cüt YOX. `padding-left` 16 → 13px (`--space-md` −
   3px sərhəd) ki, mətn sərhəd əlavə olunanda SAĞA SÜRÜŞMƏSİN. */
QPushButton[variant="nav"][active="true"] {
    background-color: {{--color-nav-active-bg}};
    color: {{--color-nav-active-text}};
    font-weight: {{--font-weight-medium}};
    border-left: 3px solid {{--color-focus-ring-on-dark}};
    padding-left: 13px;
}

QPushButton[variant="nav"][active="true"]:hover {
    background-color: {{--color-nav-active-bg}};
}

/* DARALDILMIŞ PANEL (ikon mərkəzdə) — sol xətt BURADA YOXDUR: mətn yoxdur,
   sərhəd ikonu mərkəzdən sürüşdürərdi (bax `[compact="true"]`-nın `text-
   align: center`-i). Dolu fon YENƏ DƏ görünür — kifayət qədər aydın
   siqnaldır, əlavə xətt lazım deyil. */
QPushButton[variant="nav"][compact="true"][active="true"] {
    border-left: none;
    padding-left: 0;
}

/* DEAKTİV — bax `[variant="primary"]:disabled`-in izahı. Fon BURADA
   `--color-neutral-bg` DEYİL: sıravi vəziyyət ARTIQ şəffafdır (bax `[variant
   ="nav"]`), dolu fon əlavə etsək naviqasiya maddəsi qəflətən "qutu" kimi
   görünərdi — sıravi maddələrdən vizual dilə görə fərqlənərdi. YALNIZ mətn
   susdurulur, "flat" görünüş qorunur. */
QPushButton[variant="nav"]:disabled {
    background-color: transparent;
    color: {{--color-text-disabled}};
}

/* ===================== SƏHİFƏ BAŞLIĞI (HEADER) ===================== */
QWidget#PageHeader {
    background-color: {{--color-header-bg}};
    border-bottom: {{--border-width}} solid {{--color-header-border}};
}

QWidget#PageHeader QLabel { background-color: transparent; }

/* ÖLÇÜ BURADA VERİLMİR — QƏSDƏN.
   Maket başlıqları bir ölçüdə deyil: səhifə başlığı 17px, kart başlığı 14–15,
   panel başlığı 16, işçi adı 22, kiosk 28, lisenziya 26. `title_label(size=…)`
   həmin dəyəri `QFont` ilə verir, QSS-dəki `font-size` isə onu ƏZİRDİ və
   bütün başlıqlar 19px çıxırdı (73 çağırış nöqtəsi, 13–34px aralığı).
   Qt-də QSS xüsusiyyəti proqram vasitəsilə verilmiş `QFont`-u üstələyir, ona
   görə ölçünün YEGANƏ mənbəyi çağırış nöqtəsidir. Rəng və çəki isə burada
   qalır: onlar bütün başlıqlar üçün eynidir. */
QLabel#PageTitle {
    color: {{--color-text-primary}};
    font-weight: {{--font-weight-medium}};
}

QLabel#PageSubtitle {
    color: {{--color-text-muted}};
    font-size: {{--font-size-sm}};
    font-weight: {{--font-weight-normal}};
}

/* Header-dəki ikon düymələri (tema, zəng) — 34×34, 9px künc.
   SƏRHƏD `--color-card-border` DEYİL: fon şəffaf olduğu üçün sərhəd düymənin
   harada başlayıb bitdiyini göstərən YEGANƏ vizual əlamətdir və WCAG 1.4.11
   ona 3:1 tələb qoyur. Kart sərhədi bu rolda 1.30:1 (işıqlı) / 1.42:1 (tünd)
   verirdi — kart üçün kifayət, müstəqil idarəetmə elementi üçün yox. */
/* SƏRHƏD RESTİNQ HALINDA YOXDUR — AFFORDANS İKONUN ÖZÜDÜR.
   ─────────────────────────────────────────────────────────────────────────
   Əvvəl düymə 1px `--color-border-strong` çərçivə daşıyırdı və səbəb WCAG
   1.4.11 idi: «düymənin VARLIĞINI göstərən yeganə şey sərhəddir». Bu
   arqument İKONUN RƏNGİNİ nəzərə almırdı — başlıqdakı zəng/kömək ikonları
   `--color-nav-item-text` ilə çəkilir, yəni MƏTN səviyyəsində kontrastdadır
   (işıqlıda 9.4:1, tünddə 11.7:1). Qliflə ifadə olunan idarəetmə elementi
   1.4.11-in tələbini onsuz da ödəyir; çərçivə isə başlıqda dörd ayrı qutu
   yaradırdı və `appl.md` qayda 5 (sərt xətləri azalt) ilə birbaşa ziddiyyət
   təşkil edirdi.

   `transparent` SƏRHƏD SAXLANILIR, `border: none` YOX: sərhədi tamamilə
   silsək, hover/fokus halında 1px əlavə olunanda düymə YERİNDƏN TƏRPƏNİR
   (Qt sərhədi qutu ölçüsünə daxil edir). Şəffaf sərhəd həndəsəni sabit
   saxlayır. */
QPushButton[variant="icon"] {
    background-color: transparent;
    border: {{--border-width}} solid transparent;
    border-radius: {{--radius-pill}};
    min-height: 34px;
    max-height: 34px;
    min-width: 34px;
    max-width: 34px;
    padding: 0;
}

/* Hover və basılma — DOLĞU səth, çərçivə yox (macOS alət zolağı naxışı). */
QPushButton[variant="icon"]:hover { background-color: {{--color-neutral-bg}}; }

QPushButton[variant="icon"]:pressed { background-color: {{--color-bg-sunken}}; }

QPushButton[variant="icon"][active="true"] {
    background-color: {{--color-action-bg}};
    border-color: {{--color-action-bg}};
    border-radius: {{--radius-pill}};
}

/* DEAKTİV — bax `[variant="primary"]:disabled`-in izahı. `color:` BURADA
   YAZILMIR: `QIcon` hazır piksel şəklidir, QSS `color:` ONA TƏSİR ETMİR
   (bax `buttons.py::icon_button` başlığı, "RƏNG NİYƏ QSS-DƏN DEYİL") —
   yazsaq ölü kod olardı. Sıravi ikon düyməsi ARTIQ şəffafdır, ona görə
   `[variant="icon"]:disabled` YALNIZ `[active="true"]` altvariantını
   susdurur: O, DOLU `--color-action-bg` fonu daşıyır (məs. aktiv tema
   düyməsi) və məhz BUNUN üçün "aktiv görünür" riski VAR. */
QPushButton[variant="icon"][active="true"]:disabled {
    background-color: {{--color-neutral-bg}};
    border-color: {{--color-neutral-bg}};
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
    border-radius: {{--radius-control}};
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
    border-radius: {{--radius-control}};
    padding: 0 {{--space-lg}};
    min-height: 42px;
    max-height: 42px;
    font-weight: {{--font-weight-normal}};
}

QPushButton[variant="secondary"]:hover { background-color: {{--color-neutral-bg}}; }

/* DAR düymə (səhifələmə nömrələri, ‹ ›). Adi `secondary` doldurması yan-yana
   24+24px-dir; sabit 46px enli düymədə bu, məzmun sahəsini MƏNFİ edir və Qt
   mətni tamamilə kəsir — səhifə nömrələri boş kvadrat kimi görünürdü.
   Ona görə dar düymə doldurmanı sıfırlayır və eni özü təyin edir. */
QPushButton[variant="secondary"][compact="true"] {
    padding: 0;
}

/* Seçilmiş segment (Ayarlar → Görünüş) DOLU fon alır — əks halda üç
   düymə eyni görünür və istifadəçi cari temanı təyin edən idarəetmədən
   məhz onu OXUYA BİLMİR. */
QPushButton[variant="secondary"][active="true"] {
    background-color: {{--color-action-bg}};
    color: {{--color-action-text}};
    border-color: {{--color-action-bg}};
    font-weight: {{--font-weight-medium}};
}

/* DEAKTİV — bax `[variant="primary"]:disabled`-in izahı, EYNİ cüt. */
QPushButton[variant="secondary"]:disabled {
    background-color: {{--color-neutral-bg}};
    border-color: {{--color-card-border}};
    color: {{--color-text-disabled}};
}

/* ===================== YUMŞAQ NİŞANLAR (CHIP) ===================== */
/* Maketdəki status həbləri: yumşaq fon + kalibrlənmiş mətn (bax tokens.py). */
/* ŞƏFFAF SƏRHƏD NİYƏ HƏMİŞƏ VAR
   `FilterChip` klaviatura ilə fokuslana bilir və fokus halqası sərhədlə
   çəkilir. Sərhəd YALNIZ `:focus` halında əlavə edilsəydi, Qt widget-in ölçü
   hesabına 2px əlavə edərdi və nişan fokus alanda "sıçrayardı" — süzgəc
   zolağındakı bütün sətir yerini dəyişərdi. Ona görə yer ƏVVƏLCƏDƏN ayrılır,
   fokusda isə yalnız rəng dolur.
   Doldurma `4px 8px` əvəzinə `2px 6px`-dir: 2px sərhəd + 2px/6px doldurma =
   maketdəki 4px/8px qutu. Yəni görünüş DƏYİŞMİR. Rəqəmlər `--focus-ring-width`
   (2) ilə bağlıdır — o dəyişsə, bu doldurma da dəyişməlidir. */
QLabel[chip="success"], QLabel[chip="warning"], QLabel[chip="danger"],
QLabel[chip="info"], QLabel[chip="neutral"] {
    border: {{--focus-ring-width}} solid transparent;
    /* DESIGN.MD REDİZAYNI: `--radius-md` (8px) → tam həb. Referansların
       hamısında status nişanı HƏBDİR; 8px radius onu kiçik kartla
       qarışdırırdı və cədvəl sətrində "basıla bilən" görünürdü. */
    border-radius: {{--radius-pill}};
    padding: 3px 10px;
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
/* Forma sahəsi — yuxarıdakı ilə EYNİ dil: doldurulmuş səth, eyni sərhəd,
   eyni künc. Fərq yalnız hündürlük (`forms.FIELD_HEIGHT = 46`) və şrift
   ölçüsündədir, ona görə burada YALNIZ onlar təkrarlanır. */
/* `QDateTimeEdit[variant="form"]` BURADA DA LAZIMDIR (VİZUAL FAZA #0b):
   `FormField(widget=...)` HƏR widget-ə `variant="form"` qoyur
   (`widgets/forms.py`), ona görə `group_f.py`-dəki son-tarix sahəsi (`self.
   _deadline = QDateTimeEdit()`) MƏHZ bu seçici qrupuna düşür — yuxarıdakı
   AD-siz qrup ona ÜMUMİYYƏTLƏ TƏSİR ETMİR. */
/* QUTU → ALT XƏTT (VİZUAL FAZA #6) BURADA DA EYNİ PRİNSİPLƏ TƏTBİQ OLUNUR —
   yuxarıdakı AD-siz qrupun şərhi izahı daşıyır. TƏK FƏRQ: burada `:focus`
   qaydası `padding-bottom` AZALTMIR. Səbəb struktur fərqdir — bu qrupun
   hündürlüyü CSS box-modelindən deyil, Python tərəfdən (`FormField`
   `widget.setMinimumHeight(FIELD_HEIGHT)`, `widgets/forms.py`) gəlir və
   `padding: 0` onsuz da sıfırdır; alt xəttin 1px→2px böyüməsi mövcud
   minimum-hündürlük daxilində udulur, sıçrama YARADA BİLMİR. */
QLineEdit[variant="form"],
QComboBox[variant="form"],
QSpinBox[variant="form"],
QDateEdit[variant="form"],
QTimeEdit[variant="form"],
QDateTimeEdit[variant="form"] {
    background-color: {{--color-bg-surface}};
    color: {{--color-text-primary}};
    border: none;
    border-bottom: {{--border-width}} solid {{--color-border}};
    border-top-left-radius: {{--radius-control}};
    border-top-right-radius: {{--radius-control}};
    border-bottom-left-radius: 0;
    border-bottom-right-radius: 0;
    padding: 0 12px;
    font-size: {{--font-size-md}};
}

QLineEdit[variant="form"]:hover,
QComboBox[variant="form"]:hover,
QSpinBox[variant="form"]:hover,
QDateEdit[variant="form"]:hover,
QTimeEdit[variant="form"]:hover,
QDateTimeEdit[variant="form"]:hover {
    border-bottom-color: {{--color-border-strong}};
}

QLineEdit[variant="form"]:focus,
QComboBox[variant="form"]:focus,
QSpinBox[variant="form"]:focus,
QDateEdit[variant="form"]:focus,
QTimeEdit[variant="form"]:focus,
QDateTimeEdit[variant="form"]:focus {
    background-color: {{--color-bg-elevated}};
    border-bottom: {{--focus-ring-width}} solid {{--color-focus-ring}};
}

QLineEdit[variant="form"][state="error"],
QComboBox[variant="form"][state="error"] {
    border-bottom-color: {{--color-danger}};
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

/* Mətn şəklində hərəkət (`LinkLabel`) — klaviatura ilə fokuslana bilir.
   Rəng BURADA VERİLMİR: link mətni ekrandan-ekrana fərqli rolda görünür
   (kartda solğun, panel başlığında əsas) və çağırış nöqtəsi onu özü seçir.
   Bu qayda yalnız fokus halqasının yerini ayırır — nişanlarda olduğu kimi
   şəffaf sərhəd əvvəlcədən qoyulur ki, fokusda düzülüş sıçramasın. */
QLabel[variant="link"] {
    background-color: transparent;
    border: {{--focus-ring-width}} solid transparent;
    border-radius: {{--radius-sm}};
}

/* Rəqəm/kod sahələri (saat, xəta kodu, tenant_id) — maketdə IBM Plex Mono.
   Şrift adı burada YAZILMIR: mənbə `tokens.py`-dakı `--font-family-mono`-dur
   (bax həmin faylın "MONO ŞRİFT NİYƏ AYRICA TOKENDİR" bölməsi). */
QLabel[variant="mono"], QLabel[variant="mono-muted"] {
    background-color: transparent;
    font-family: {{--font-family-mono}};
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
    border-radius: {{--radius-badge}};
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
/* AÇILIŞ EKRANI — FON TOKENİ İLƏ, MƏTN SOLĞUN (`appl.md` FAZA 3)
   ─────────────────────────────────────────────────────────────────────────
   İKİ SƏHV BURADA İDİ:

   1. FON `--color-brand-navy` yazırdı, halbuki ekranın özü `--color-splash-bg`
      ilə INLINE stil qoyur (`screens/group_a_entry.py`) və inline stil QSS-i
      üstələyir. Yəni bu qayda HEÇ VAXT görünmürdü — iki fərqli fon iki yerdə
      yazılmışdı və biri ölü idi. İndi hər ikisi EYNİ tokendir.

   2. MƏTN brend amberi idi — BÜTÜN etiketlər: alt yazı, vəziyyət mətni,
      versiya. `appl.md` qayda 3 amberin YALNIZ vurğu (aktiv element, əsas
      CTA) üçün işlədilməsini tələb edir; burada isə o, adi köməkçi mətnin
      rəngi idi və ekranın 100%-i markanın rəngində «yanırdı».

   ƏLAVƏ FAKT: kontrast qapısı (`scripts/check_contrast.py`) açılış ekranı
   üçün ARTIQ `--color-text-muted` / `--color-splash-bg` cütünü ölçürdü — yəni
   ölçülən cüt ilə RENDER olunan rəng fərqli idi. İndi ikisi eynidir. */
QWidget#SplashScreen {
    background-color: {{--color-splash-bg}};
}

QWidget#SplashScreen QLabel {
    background-color: transparent;
    color: {{--color-text-muted}};
}

/* Söz nişanı — lockup şəkli tapılmayanda çəkilən EHTİYAT başlıq. Solğun
   deyil: o, ekranın adıdır. Kontrast qapısı bu cütü ARTIQ ölçür
   («Açılış — söz nişanı», `--color-text-primary` / `--color-splash-bg`). */
QWidget#SplashScreen QLabel#SplashWordmark {
    color: {{--color-text-primary}};
}

/* ===================== DİGƏR ===================== */
/* ÜMUMİ QAYDA (bu gün EYNİ tələ ÜÇ ayrı yerdə çıxdı — `QComboBox::drop-
   down`, `QComboBox::down-arrow` və aşağıdakı sol-panel zolağı): Qt-nin
   alt-kontrol (`::…`) sistemi İKİ FƏRQLİ tələ qurur, EYNİ görünüşlə
   ("boş/səhv görünür") üzə çıxsa da:

   1. STİLLƏŞDİRİLMƏMİŞ alt-kontrol NATİV ÜSLUBA qayıdır — valideynin
      `border`/`background` təmizliyi ONA sirayət ETMİR (`::drop-down`-un
      GİRİŞ SAHƏLƏRİ bölməsindəki tarixçəsi: bevel/haşiyə buradan gəldi).
      `::add-line`/`::sub-line`-in aşağıda `height: 0; width: 0;` ilə AÇIQ
      söndürülməsi bunun ÖZÜ nümunədir.

   2. Alt-kontrol STİLLƏŞDİRİLİB, LAKİN `image` YOXDURSA (arrow/ikon
      xarakterli alt-kontrollarda — `::down-arrow`, `::up-arrow`), Qt HEÇ
      NƏ çəkmir — nə native, nə CSS. `QComboBox::down-arrow`-a `border:
      none`/`background: transparent` yazmaq OXUN ÖZÜNÜ YOX ETDİ (GİRİŞ
      SAHƏLƏRİ bölməsi, DÖRDÜNCÜ addım) — çünki bu, 1-ci hala YOX, 2-ci
      hala aiddir.

   Yəni QAYDA TƏK CÜMLƏ DEYİL: "boş yerə YAZ" (1-ci hal üçün) İLƏ "arrow
   xarakterli alt-kontrola TOXUNMA, ya da `image` VER" (2-ci hal üçün)
   ARASINDA FƏRQ VAR — hansının aid olduğunu qarışdırmaq əks nəticə verir.
   Yeni alt-kontrollu widget QSS-ə əlavə edilərkən HƏR `::` seçici üçün
   BU FƏRQİ aydınlaşdırmaq YOXLAMA SİYAHISINA daxil edilməlidir. */
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

/* SOL PANELİN SÜRÜŞDÜRMƏ ZOLAĞI NAZİKDİR — ÜMUMİ ZOLAQDAN (yuxarı, 16px)
   QƏSDƏN FƏRQLƏNİR.
   ─────────────────────────────────────────────────────────────────────────
   16px-lik ÜMUMİ zolaq sol paneldə İKİ yan təsir yaratdı (ölçülüb):
   (a) maddələrin sahəsi 244→228px düşdü, elide olunan maddə sayı 1-dən
   6-ya qalxdı; (b) daraldılmış (64px) rejimdə zolaq ikon sütununu
   mərkəzdən sürüşdürdü. Hər ikisinin kökü EYNİDİR — zolağın ÖZÜ genişdir,
   `sidebar.py`-dəki `#SidebarScroll` (`setObjectName`) buna görə ÖZ,
   nazik üslubunu alır.

   `AsNeeded` siyasəti (`sidebar.py`) YERİNDƏ QALIR — bura `AlwaysOff`
   YAZILMIR: 42 maddəlik ROOT panelində zolağı söndürmək aşağıdakı
   ikonları YENİDƏN çatılmaz edərdi, yəni bu gün düzəldilən funksional
   qüsuru geri qaytarardı. Yalnız EN azaldılır, sürüşdürmə ÖZÜ qalır.

   `--space-sm` (8px) EN üçün, `--color-border-subtle` TUTACAQ üçün —
   ikisi də MÖVCUD tokenlərdir (yenisi əlavə OLUNMUR): ümumi zolağın
   `--space-md`/`--color-border` cütünə paralel, sadəcə bir pillə solğun
   və nazik. */
QScrollArea#SidebarScroll QScrollBar:vertical {
    background: transparent;
    border: none;
    width: {{--space-sm}};
}

QScrollArea#SidebarScroll QScrollBar::handle:vertical {
    background: {{--color-border-subtle}};
    border-radius: {{--radius-sm}};
    min-height: {{--space-lg}};
}

/* KİOSK EKRANININ SÜRÜŞDÜRMƏ ZOLAĞI — `#SidebarScroll` İLƏ EYNİ NAZİK
   ÜSLUB, EYNİ SƏBƏB: toxunma cihazında qalın (16px) ümumi zolaq yer yeyir
   (`group_a_kiosk.py::EmployeeHomeScreen`, `perf-screens`-in kompakt-
   rejim hündürlük tapıntısı — `admin_shell.py:137`-dəki `ContentScroll`
   presedenti tətbiq olunur, kiosk üçün AYRI fəlsəfə İCAD OLUNMUR). YENİ
   token YARADILMIR — `#SidebarScroll` ilə EYNİ cüt (`--space-sm`,
   `--color-border-subtle`) təkrar işlədilir. */
QScrollArea#KioskContentScroll QScrollBar:vertical {
    background: transparent;
    border: none;
    width: {{--space-sm}};
}

QScrollArea#KioskContentScroll QScrollBar::handle:vertical {
    background: {{--color-border-subtle}};
    border-radius: {{--radius-sm}};
    min-height: {{--space-lg}};
}

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

/* ===================== FOKUS GÖSTƏRİCİSİ (BLOK ƏN SONDA) ===================== */
/* ──────────────────────────────────────────────────────────────────────────
   NİYƏ BU BLOK ŞABLONUN ƏN SONUNDADIR — VƏ NİYƏ ONU YUXARI KÖÇÜRMƏK OLMAZ
   ──────────────────────────────────────────────────────────────────────────
   Qt Style Sheet CSS2 spesifiklik qaydasını işlədir və BƏRABƏRLİKDƏ SONUNCU
   qayda qalib gəlir. `QPushButton[variant="action"]` (bir atribut seçicisi) ilə
   `QPushButton:focus` (bir psevdo-sinif) EYNİ spesifiklikdədir — ona görə
   yuxarıdakı ümumi `QPushButton:focus` qaydası özündən SONRA gələn hər variant
   blokunun `border` elanı tərəfindən sükutla əzilirdi.

   Nəticə görünməz bir qüsur idi: `window`, `nav`, `icon`, `action` və
   `secondary` düymələri `Tab` ilə fokuslananda HEÇ BİR vizual fərq
   göstərmirdi. Nə Qt xəbərdarlıq edirdi, nə də kontrast skripti — çünki
   qayda mövcud idi, sadəcə qüvvəyə minmirdi.

   Bu blok həmin variantların hər birini AÇIQ şəkildə təkrar elan edir və
   şablonun sonunda dayanır. `tests/unit/test_design_system.py` sıranı
   qapıya salır: yeni variant bloku bundan SONRA əlavə edilsə, test qırılır.

   ──────────────────────────────────────────────────────────────────────────
   HALQA RƏNGİ HƏR YERDƏ `--color-focus-ring` DEYİL — QƏSDƏN
   ──────────────────────────────────────────────────────────────────────────
   Fokus halqası ALTINDAKI səthlə 3:1 kontrast verməlidir. İki yerdə
   `--color-focus-ring` bunu STRUKTUR olaraq verə bilmir:

     * `action` düyməsi — tünd temada fonu brend amberidir, halqa rəngi də
       amberdir: 1.00:1, yəni halqa TAMAMİLƏ görünməz olardı. Ona görə orada
       düymənin ÖZ mətn rəngi (`--color-action-text`) işlədilir — o cüt onsuz
       da 8.28:1 (tünd) / 16.79:1 (işıqlı) ilə qapıdan keçir.
     * `window` düyməsi — başlıq zolağı hər iki temada Navy-dir; işıqlı temada
       dərin amber halqa orada cəmi 3.21:1 verir (marjinal). Zolağın öz mətn
       rəngi 11.82–13.11:1 verir və onsuz da qapıdadır.

   Qalan variantlarda halqa `--color-focus-ring`-dir və ən pis hal 4.59:1-dir. */

/* HALQA `:focus`-a DEYİL, `[keyfocus="true"]`-ya bağlıdır. Səbəb: Qt pəncərə
   açılanda fokusu fokus-zəncirinin BİRİNCİ elementinə verir və bu, başlıq
   zolağının «kiçilt» düyməsidir — yəni tətbiq hər açılışda həmin düymənin
   ətrafında ağ kvadratla başlayırdı, istifadəçi heç nəyə toxunmadan.
   Xüsusiyyəti `WindowButton.focusInEvent` yalnız KLAVİATURA səbəbi
   (`Tab`/`Backtab`/qısayol) ilə qoyur — halqa onsuz da onun üçündür. */
QPushButton[variant="window"][keyfocus="true"] {
    border: {{--focus-ring-width}} solid {{--color-titlebar-text}};
}

/* BAĞLA düyməsi eyni anda HƏM fokusda, HƏM hover-də ola bilər: klaviatura ilə
   gəzən istifadəçi `Tab`-la ora çatır, sonra siçanı hərəkət etdirir. O halda
   fon `--color-danger`-ə çevrilir və zolağın öz mətn rəngi ilə halqa TÜND
   temada cəmi 2.14:1 verirdi (#C4D0E2 / #EF5A5A) — 3:1 həddindən aşağı, yəni
   fokusun harada olduğu görünmürdü. Halqa da mətn/ikon kimi
   `--color-bg-primary`-yə keçir: həmin cüt onsuz da qapıdadır (6.54:1 işıqlı,
   5.02:1 tünd). */
QPushButton[variant="window"][action="close"]:hover[keyfocus="true"],
QPushButton[variant="window"][action="close"][hover="true"][keyfocus="true"] {
    border: {{--focus-ring-width}} solid {{--color-bg-primary}};
}

QPushButton[variant="nav"]:focus {
    border: {{--focus-ring-width}} solid {{--color-focus-ring}};
}

/* AKTİV HƏB TÜND SƏTHDİR — halqa da ona görə seçilir (bax `tokens.py`,
   `--color-focus-ring-on-dark`). İşıqlı temada ümumi halqa dərin amberdir və
   həmin həbin üzərində 2.39:1 verirdi: fokus faktiki olaraq görünmürdü. */
QPushButton[variant="nav"][active="true"]:focus {
    border: {{--focus-ring-width}} solid {{--color-focus-ring-on-dark}};
}

QPushButton[variant="icon"]:focus,
QPushButton[variant="icon"][active="true"]:focus {
    border: {{--focus-ring-width}} solid {{--color-focus-ring}};
}

/* ŞƏFFAF SƏTHLƏRDƏKİ İKON DÜYMƏLƏRİ SƏRHƏDSİZDİR.

   `variant="icon"` defoltda 1px sərhəd + 8px künc daşıyır. Səbəb `tokens.py`
   başlığındadır: səhifə başlığındaki 34×34 düymənin VARLIĞINI göstərən yeganə
   şey sərhəddir (WCAG 1.4.11).

   Sol panel və başlıq zolağı isə FƏRQLİ kontekstdir — orada düymə öz
   səthinin içindədir və qonşuları da sərhədsizdir (naviqasiya sətirləri,
   pəncərə düymələri). Sərhəd orada elementi «görünən» etmir, əksinə: qutu
   kimi ayırır. İstifadəçi hesabatı bunu belə təsvir etdi — «narıncı
   düzbucaqlı + ağ dairəvi cizgi, dizayn sisteminə heç uyğun deyil».

   Görünürlük ORADA fərqli yolla təmin olunur: hover fonu + panel səthindən
   fərqlənən ikon rəngi. */
#Sidebar QPushButton[variant="icon"],
#TitleBar QPushButton[variant="icon"] {
    /* `border: none` — `variant="window"` düymələri ilə EYNİ qərar.
       Şəffaf 1px sərhəd saxlasaydıq, Qt-nin QSS qutu modelində `min-width`
       MƏZMUN sahəsi olduğu üçün düymə tokendən 2px böyük çıxardı: tema
       düyməsi 48×40, pəncərə düymələri isə 46×38 — yəni «hamısı eyni ölçüdə»
       tələbi (navbar.md PROBLEM 3 bənd 3) pozulardı. Halqa yalnız klaviatura
       fokusunda əlavə olunur (aşağıda), pəncərə düymələrində olduğu kimi. */
    border: none;
    background-color: transparent;
    min-width: {{--window-button-width}};
    max-width: {{--window-button-width}};
    min-height: {{--titlebar-height}};
    max-height: {{--titlebar-height}};
}

/* Sol panelin düyməsi naviqasiya sətrindən KİÇİKDİR — panelin başlığında
   «maddə» kimi oxunmasın deyə (navbar.jpg-də `»` nişanı maddələrdən xırdadır).
   Qayda zolaq qaydasından SONRA gəlir: bərabər spesifiklikdə sonuncu qalib
   gəlir (bax bu faylın sonundaki fokus bloku izahı). */
#Sidebar QPushButton[variant="icon"] {
    min-width: {{--sidebar-toggle-size}};
    max-width: {{--sidebar-toggle-size}};
    min-height: {{--sidebar-toggle-size}};
    max-height: {{--sidebar-toggle-size}};
}

#Sidebar QPushButton[variant="icon"]:hover,
#TitleBar QPushButton[variant="icon"]:hover {
    background-color: {{--color-neutral-bg}};
}

/* BAŞLIQ ZOLAĞINDAKI İKON DÜYMƏSİ İSTİSNADIR.
   Qt pəncərə açılanda fokusu zəncirin BİRİNCİ elementinə verir və başlıq
   zolağı tərtibatın ən üstündədir — yəni yuxarıdakı qayda tətbiq açılan kimi
   heç nəyə toxunmadan işıqlı kvadrat çəkərdi. Halqa `[keyfocus="true"]`-ya
   bağlanır (`KeyFocusRingMixin`), yəni yalnız `Tab`/`Shortcut` fokusunda
   görünür. Pəncərə düymələri (`variant="window"`) ilə EYNİ qərar. */
#TitleBar QPushButton[variant="icon"]:focus {
    border: {{--focus-ring-width}} solid transparent;
}

#TitleBar QPushButton[variant="icon"][keyfocus="true"],
#Sidebar QPushButton[variant="icon"][keyfocus="true"] {
    border: {{--focus-ring-width}} solid {{--color-focus-ring}};
}

/* Sol panelin aç/bağla düyməsi də eyni qaydadadır: o, panelin İLK fokus ala
   bilən elementidir, yəni `:focus` şərtsiz olsaydı hər açılışda halqa
   çəkilərdi. */
#Sidebar QPushButton[variant="icon"]:focus {
    border: {{--focus-ring-width}} solid transparent;
}

QPushButton[variant="action"]:focus {
    border: {{--focus-ring-width}} solid {{--color-action-text}};
}

QPushButton[variant="secondary"]:focus {
    border: {{--focus-ring-width}} solid {{--color-focus-ring}};
}

/* Seçilmiş segment fonu `--color-action-bg`-dir (tünddə amber) — yuxarıdakı
   `action` ilə eyni səbəbdən halqa mətn rəngindədir. */
QPushButton[variant="secondary"][active="true"]:focus {
    border: {{--focus-ring-width}} solid {{--color-action-text}};
}

/* PIN klaviaturası: sərhəd ARTIQ 2px-dir, ona görə fokus ENİ deyil RƏNGİ
   dəyişir — eni artırmaq düymələri sıçradardı, kiosk isə toxunma ekranıdır
   və düzülüş sabit qalmalıdır. */
QPushButton[variant="keypad"]:focus {
    border-color: {{--color-focus-ring}};
}

/* Etiket şəklindəki hərəkətlər — `FilterChip`, `LinkLabel`.
   Yer şəffaf sərhədlə əvvəlcədən ayrılıb, burada yalnız rəng dolur. */
QLabel[chip="success"]:focus, QLabel[chip="warning"]:focus,
QLabel[chip="danger"]:focus, QLabel[chip="info"]:focus,
QLabel[chip="neutral"]:focus, QLabel[variant="link"]:focus {
    border-color: {{--color-focus-ring}};
}

/* Klik edilə bilən kart və siyahı sətirləri. Kartın sərhədi onsuz da 1px-dir,
   ona görə burada EN dəyişmir, yalnız rəng — sətir hündürlüyü sabit qalır. */
QFrame[variant="card"]:focus {
    border-color: {{--color-focus-ring}};
}

QWidget[variant="table-row"]:focus,
QWidget[variant="list-row"]:focus {
    border-color: {{--color-focus-ring}};
}
"""


def build_stylesheet(tokens: dict[str, str]) -> str:
    """Verilmiş tokenlərlə tam QSS mətnini qurur."""
    return render(QSS_TEMPLATE, tokens)


__all__ = ["QSS_TEMPLATE", "StyleSheetError", "build_stylesheet", "render"]
