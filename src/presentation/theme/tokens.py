"""KompasOS Dizayn Sistemi — rəng və ölçü tokenləri (bölmə 9) — Faza 4.1.

Bu modul dizayn sisteminin YEGANƏ həqiqət mənbəyidir. Heç bir komponent
kodunda rəng hardcode olunmur (bölmə 9) — widget-lər tokenləri `qss.py`
vasitəsilə alır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ FAYL `scripts/check_contrast.py` TƏRƏFİNDƏN OXUNUR
──────────────────────────────────────────────────────────────────────────────
CI addımı (bölmə 1 və 9) bu faylı idxal edib `LIGHT_THEME` və `DARK_THEME`
sözlüklərini oxuyur, sonra WCAG AA nisbətlərini hesablayır. Bu səbəbdən:

    * hər iki sözlük EYNİ açar dəstinə malik olmalıdır (aşağıda yoxlanılır),
    * dəyərlər sadə `#RRGGBB` sətirləri olmalıdır — hesablanmış ifadə,
      funksiya çağırışı və ya asılılıq OLMAMALIDIR (skript modulu izolyasiya
      olunmuş şəkildə `exec` edir və PySide6 quraşdırılmamış ola bilər).

Buna görə modul PySide6-dan ASILI DEYİL və heç nə idxal etmir.

──────────────────────────────────────────────────────────────────────────────
BREND AMBERİ İLƏ İNTERAKTİV VURĞU NİYƏ AYRI TOKENLƏRDİR (VACİB QƏRAR)
──────────────────────────────────────────────────────────────────────────────
Bölmə 9 iki tələbi eyni anda qoyur: (a) Amber `#F5A623` brend tanınması üçün
hər iki rejimdə DƏYİŞMƏZ qalsın, (b) hər rəng cütü WCAG AA-dan keçsin.
Bunlar işıqlı rejimdə BİR-BİRİNİ İSTİSNA EDİR:

    #F5A623 ağ fonda = 2.03:1   → iri qrafik element üçün lazım olan 3:1-i
                                   belə keçmir (bax `test_brand_amber_on_
                                   white_fails_normal_text`).

Ona görə iki AYRI rol tanınır:

    `--color-brand-amber`  Loqo, splash, iri dekorativ elementlər. HƏR İKİ
                           rejimdə eynidir — brend tanınması burada qorunur.
                           Kontrast məcburiyyəti YOXDUR, çünki üzərində mətn
                           yerləşmir; yalnız TÜND fonda işlədilir.
    `--color-accent`       Düymə, fokus halqası, aktiv menyu — yəni üzərində
                           MƏTN olan və klikləənən hər şey. Fona görə AYRICA
                           kalibrlənir (bölmə 9: "hər fonla kontrast nisbəti
                           ayrıca kalibrlənir"): işıqlı rejimdə dərin amber
                           `#9A5F00`, tünd rejimdə brend amberinin özü.

Alternativ — hər iki rejimdə `#F5A623` saxlayıb üzərinə tünd mətn qoymaq —
işıqlı rejimdə amber düyməni ağ fondan ayırd edilməz edərdi (2.03:1), yəni
düymənin harada bitdiyi görünməzdi. Rəngi kalibrləmək brendi qorumağın yeganə
yoludur; brend rəngi loqoda toxunulmaz qalır.

──────────────────────────────────────────────────────────────────────────────
PIN EKRANI ÜÇÜN AYRICA TOKENLƏR
──────────────────────────────────────────────────────────────────────────────
PIN Handshake ekranı mağazada — dəyişkən işıqlandırmada, tez-tez günəş
altında — istifadə olunur (bölmə 9). Ona görə həmin ekran ümumi mətn/fon
cütündən DEYİL, AAA (7:1) həddini keçən öz `--color-pin-*` cütündən istifadə
edir və CI onu `--include-high-contrast` ilə ayrıca yoxlayır.

──────────────────────────────────────────────────────────────────────────────
DİZAYN MAKETİ İLƏ FƏRQLƏR (`--color-*-bg`, `--color-text-muted`)
──────────────────────────────────────────────────────────────────────────────
Örtük (shell) tokenləri Claude Design maketlərindən (Qrup A–G) götürülüb.
İKİ yerdə maketin dəyəri QƏSDƏN dəyişdirilib, çünki maket WCAG AA-dan keçmir
və bu layihədə kontrast CI qapısıdır (`scripts/check_contrast.py`):

    nişan mətni   maket `#17845A` / `#E4F4EC` = 4.08:1  → AA-dan AŞAĞI
                  bizdə `--color-success` `#1E7A46`     = 4.66:1  ✓

    solğun mətn   maket `#93A0B5` / ağ = 2.65:1         → AA-dan AŞAĞI
                  bizdə `--color-text-muted` `#64738D`  = 4.80:1  ✓

Maketin YUMŞAQ FONLARI (`--color-*-bg`) olduğu kimi saxlanılır — dəyişən
yalnız onların ÜZƏRİNDƏKİ mətndir. Beləliklə görünüş maketlə eyni qalır,
oxunaqlıq isə tələb olunan həddi keçir. Eyni prinsip yuxarıdakı brend amberi
qərarı ilə üst-üstə düşür: rəngi kalibrləmək dizaynı qorumağın yoludur.

İkon rəngi (`--color-nav-item-icon`) maketdəki kimi qalır — o, mətn deyil,
"iri qrafik element"dir və 3:1 həddindən keçir (`#7B8AA3` / ağ = 3.53:1).
"""

from __future__ import annotations

from enum import Enum
from typing import Final

# --------------------------------------------------------------------------- #
# Brend sabitləri
# --------------------------------------------------------------------------- #

#: Deep Navy — brendin əsas rəngi (bölmə 9).
BRAND_NAVY: Final = "#0B1D3A"

#: Amber — brendin vurğu rəngi. YALNIZ loqo/dekorativ elementlərdə dəyişməz
#: işlədilir; interaktiv vurğu üçün `--color-accent`-ə bax (yuxarıdakı izah).
BRAND_AMBER: Final = "#F5A623"


class ThemeMode(str, Enum):
    """İstifadəçinin Ayarlar ekranındakı seçimi (`user_preferences.theme`).

    `SYSTEM` saxlanılan bir DƏYƏRDİR, tema deyil — işə düşmə anında OS-in
    seçiminə görə `LIGHT` və ya `DARK`-a həll olunur (bax `resolve_mode`).
    """

    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


# --------------------------------------------------------------------------- #
# İŞIQLI TEMA
# --------------------------------------------------------------------------- #

LIGHT_THEME: Final[dict[str, str]] = {
    # --- fonlar ---
    "--color-bg-primary": "#FFFFFF",
    "--color-bg-surface": "#F2F4F8",
    "--color-bg-elevated": "#FFFFFF",
    "--color-bg-sunken": "#E6EAF2",
    # --- mətn ---
    "--color-text-primary": BRAND_NAVY,
    "--color-text-secondary": "#4A5568",
    "--color-text-disabled": "#8A93A6",
    "--color-text-on-accent": "#FFFFFF",
    # --- vurğu (interaktiv) ---
    "--color-accent": "#9A5F00",
    "--color-accent-hover": "#824F00",
    "--color-accent-pressed": "#6B4100",
    "--color-accent-subtle": "#FDF3E0",
    # --- brend (dekorativ, kontrast məcburiyyəti yoxdur) ---
    "--color-brand-navy": BRAND_NAVY,
    "--color-brand-amber": BRAND_AMBER,
    # --- semantik ---
    "--color-success": "#1E7A46",
    "--color-warning": "#A15C00",
    "--color-danger": "#B3261E",
    "--color-info": "#1B5E9E",
    # --- struktur ---
    "--color-border": "#8A93A6",
    "--color-border-subtle": "#D5DAE4",
    "--color-focus-ring": "#9A5F00",
    "--color-overlay": "#0B1D3A99",
    # --- PIN ekranı (AAA) ---
    "--color-pin-bg": "#FFFFFF",
    "--color-pin-text": BRAND_NAVY,
    # --- örtük (shell) quruluşu — bax "DİZAYN MAKETİ" qeydi aşağıda ---
    "--color-titlebar-bg": BRAND_NAVY,
    "--color-titlebar-text": "#DCE4F0",
    "--color-titlebar-control": "#A9B6CB",
    "--color-sidebar-bg": "#FFFFFF",
    "--color-sidebar-border": "#DCE2EC",
    "--color-nav-item-text": "#33405C",
    "--color-nav-item-icon": "#7B8AA3",
    "--color-nav-active-bg": BRAND_NAVY,
    "--color-nav-active-text": "#FFFFFF",
    # --- əsas hərəkət düyməsi (maketdə: işıqlıda Navy, tünddə Amber) ---
    "--color-action-bg": BRAND_NAVY,
    "--color-action-text": "#FFFFFF",
    "--color-chart-bar": BRAND_NAVY,
    "--color-action-hover": "#16305C",
    "--color-action-pressed": "#071426",
    "--color-header-bg": "#FFFFFF",
    "--color-header-border": "#DCE2EC",
    "--color-content-bg": "#F4F6FA",
    "--color-card-bg": "#FFFFFF",
    "--color-card-border": "#DCE2EC",
    "--color-divider": "#EDF0F6",
    "--color-text-muted": "#64738D",
    "--color-skeleton": "#E5EAF2",
    "--color-skeleton-alt": "#EDF0F6",
    # --- yumşaq nişan (chip) fonları ---
    "--color-success-bg": "#E4F4EC",
    "--color-warning-bg": "#FDF1DC",
    "--color-danger-bg": "#FDF1F1",
    "--color-info-bg": "#E8F2FB",
    "--color-neutral-bg": "#EDF0F6",
}


# --------------------------------------------------------------------------- #
# TÜND TEMA
# --------------------------------------------------------------------------- #
# Tərs kontrast məntiqi (bölmə 9): Deep Navy burada MƏTN deyil, FON olur.
# Semantik rənglər "neon" görünməmək üçün doymuşluğu azaldılmış variantlardır
# — məs. uğur rəngi `#4ADE80` deyil `#3FBF6E` (9.63:1 əvəzinə 7.10:1, hələ də
# AAA), çünki tünd fonda parlaq yaşıl gözü yorur və "xəbərdarlıq" kimi oxunur.

DARK_THEME: Final[dict[str, str]] = {
    # --- fonlar ---
    "--color-bg-primary": BRAND_NAVY,
    "--color-bg-surface": "#12294D",
    "--color-bg-elevated": "#17325C",
    "--color-bg-sunken": "#071426",
    # --- mətn ---
    "--color-text-primary": "#F2F4F8",
    "--color-text-secondary": "#A8B4CC",
    "--color-text-disabled": "#6B7B99",
    "--color-text-on-accent": BRAND_NAVY,
    # --- vurğu (interaktiv) — tünd fonda brend amberinin ÖZÜ işləyir ---
    "--color-accent": BRAND_AMBER,
    "--color-accent-hover": "#FFB944",
    "--color-accent-pressed": "#D98E14",
    "--color-accent-subtle": "#2A2412",
    # --- brend ---
    "--color-brand-navy": BRAND_NAVY,
    "--color-brand-amber": BRAND_AMBER,
    # --- semantik ---
    "--color-success": "#3FBF6E",
    "--color-warning": "#F0B429",
    "--color-danger": "#EF5A5A",
    "--color-info": "#6BA6E8",
    # --- struktur ---
    "--color-border": "#5E76A0",
    "--color-border-subtle": "#2A3F63",
    "--color-focus-ring": BRAND_AMBER,
    "--color-overlay": "#000000AA",
    # --- PIN ekranı (AAA) ---
    "--color-pin-bg": "#071426",
    "--color-pin-text": "#F2F4F8",
    # --- örtük (shell) quruluşu ---
    "--color-titlebar-bg": "#0B1424",
    "--color-titlebar-text": "#C4D0E2",
    "--color-titlebar-control": "#8394AE",
    "--color-sidebar-bg": "#0F1B30",
    "--color-sidebar-border": "#22314D",
    "--color-nav-item-text": "#C4D0E2",
    "--color-nav-item-icon": "#8394AE",
    "--color-nav-active-bg": "#142443",
    "--color-nav-active-text": "#E8EDF5",
    # --- əsas hərəkət düyməsi ---
    "--color-action-bg": BRAND_AMBER,
    "--color-action-text": BRAND_NAVY,
    "--color-chart-bar": "#55719F",
    "--color-action-hover": "#FFB944",
    "--color-action-pressed": "#D98E14",
    "--color-header-bg": "#0B1424",
    "--color-header-border": "#22314D",
    "--color-content-bg": "#070E1C",
    "--color-card-bg": "#0F1B30",
    "--color-card-border": "#22314D",
    "--color-divider": "#1B2B47",
    "--color-text-muted": "#93A3BC",
    "--color-skeleton": "#152744",
    "--color-skeleton-alt": "#101E36",
    # --- yumşaq nişan (chip) fonları ---
    "--color-success-bg": "#123527",
    "--color-warning-bg": "#3A2E12",
    "--color-danger-bg": "#3A1D1F",
    "--color-info-bg": "#12293F",
    "--color-neutral-bg": "#142443",
}


# --------------------------------------------------------------------------- #
# Ölçü/tipoqrafiya tokenləri — temadan ASILI DEYİL
# --------------------------------------------------------------------------- #
# Rəngdən ayrı saxlanılır, çünki kontrast skripti yalnız rəngləri gözləyir və
# burada bir "8px" dəyəri onu qırardı.

METRICS: Final[dict[str, str]] = {
    "--space-xs": "4",
    "--space-sm": "8",
    "--space-md": "16",
    "--space-lg": "24",
    "--space-xl": "32",
    "--radius-sm": "4",
    "--radius-md": "8",
    "--radius-lg": "12",
    "--border-width": "1",
    "--focus-ring-width": "2",
    # Kassa PC-lərində toxunma ekranı ola bilər — minimum hədəf ölçüsü.
    "--touch-target-min": "44",
}

TYPOGRAPHY: Final[dict[str, str]] = {
    "--font-family": "Segoe UI, Inter, Arial, sans-serif",
    "--font-size-xs": "11",
    "--font-size-sm": "13",
    "--font-size-md": "15",
    "--font-size-lg": "19",
    "--font-size-xl": "26",
    # PIN ekranı uzaqdan və tələsik oxunur — ayrıca, daha iri ölçü.
    "--font-size-pin": "40",
    "--font-weight-normal": "400",
    "--font-weight-medium": "600",
    "--font-weight-bold": "700",
}


THEMES: Final[dict[ThemeMode, dict[str, str]]] = {
    ThemeMode.LIGHT: LIGHT_THEME,
    ThemeMode.DARK: DARK_THEME,
}


# --------------------------------------------------------------------------- #
# Bütövlük yoxlaması
# --------------------------------------------------------------------------- #


def _assert_themes_are_parallel() -> None:
    """Hər iki temada EYNİ açarların olmasını təmin edir.

    Bir temada unudulan token həmin rejimdə QSS-də boş sətir yaradar və
    widget rəngsiz qalar — bu, yalnız istifadəçi temanı dəyişdirdikdə üzə
    çıxan, testdə görünməyən bir qüsurdur. İdxal anında tutmaq ucuzdur.
    """
    light, dark = set(LIGHT_THEME), set(DARK_THEME)
    if light != dark:
        only_light = sorted(light - dark)
        only_dark = sorted(dark - light)
        raise ValueError(
            "Tema tokenləri uyğun gəlmir — "
            f"yalnız işıqlıda: {only_light}; yalnız tünddə: {only_dark}"
        )


_assert_themes_are_parallel()


def theme_tokens(mode: ThemeMode) -> dict[str, str]:
    """Verilmiş rejimin BÜTÜN tokenlərini (rəng + ölçü + tipoqrafiya) qaytarır.

    Args:
        mode: `LIGHT` və ya `DARK`. `SYSTEM` burada QƏBUL EDİLMİR — o, əvvəlcə
            `resolve_mode` ilə həll olunmalıdır, əks halda "sistem teması"
            adlı mövcud olmayan bir palitra axtarılardı.

    Raises:
        ValueError: `SYSTEM` verildikdə.
    """
    if mode is ThemeMode.SYSTEM:
        raise ValueError("`SYSTEM` rejimi əvvəlcə `resolve_mode` ilə həll olunmalıdır")
    return {**THEMES[mode], **METRICS, **TYPOGRAPHY}


__all__ = [
    "BRAND_AMBER",
    "BRAND_NAVY",
    "DARK_THEME",
    "LIGHT_THEME",
    "METRICS",
    "THEMES",
    "TYPOGRAPHY",
    "ThemeMode",
    "theme_tokens",
]
