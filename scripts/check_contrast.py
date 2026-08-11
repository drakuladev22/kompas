#!/usr/bin/env python3
"""WCAG AA rəng kontrastı yoxlayıcısı (spesifikasiya bölmə 9).

QAYDA (spesifikasiyadan):
    "CI pipeline-a … avtomatik rəng kontrastı/əlçatanlıq (accessibility)
    yoxlaması daxil edilir; WCAG AA tələbinə cavab verməyən rəng cütü build-i
    uğursuz edir."
    "minimum 4.5:1 mətn üçün, 3:1 iri qrafik elementlər üçün"

İSTİFADƏ:
    python scripts/check_contrast.py                      # tokenləri avtomatik tap
    python scripts/check_contrast.py --tokens path.json   # JSON-dan oxu
    python scripts/check_contrast.py --pair "#0B1D3A" "#F5A623"

TOKEN MƏNBƏYİ:
    1. `src/presentation/theme/tokens.py` — `LIGHT_THEME` və `DARK_THEME`
       lüğətləri (Faza 4-də yaranır);
    2. və ya `--tokens` ilə verilən JSON: {"light": {...}, "dark": {...}}.

Tokenlər hələ yoxdursa (Faza 1-3), skript 0 çıxış kodu ilə "atlandı" bildirir —
CI erkən fazalarda qırmızı olmur.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOKENS_MODULE = PROJECT_ROOT / "src" / "presentation" / "theme" / "tokens.py"

AA_NORMAL_TEXT = 4.5
AA_LARGE_TEXT = 3.0
AAA_NORMAL_TEXT = 7.0

# --- Hex rəng formatı ---
HEX_SHORT_LENGTH = 3  # #RGB
HEX_FULL_LENGTH = 6  # #RRGGBB
HEX_WITH_ALPHA_LENGTH = 8  # #RRGGBBAA

# --- WCAG 2.1 sRGB → xətti çevirmə həddi ---
SRGB_LINEAR_THRESHOLD = 0.03928

#: Yoxlanılan cütlər: (ön plan tokeni, fon tokeni, minimum nisbət, təsvir)
REQUIRED_PAIRS: list[tuple[str, str, float, str]] = [
    ("--color-text-primary", "--color-bg-primary", AA_NORMAL_TEXT, "Əsas mətn"),
    ("--color-text-secondary", "--color-bg-primary", AA_NORMAL_TEXT, "İkinci dərəcəli mətn"),
    ("--color-text-primary", "--color-bg-surface", AA_NORMAL_TEXT, "Kart üzərində mətn"),
    ("--color-text-on-accent", "--color-accent", AA_NORMAL_TEXT, "Vurğu düyməsində mətn"),
    ("--color-accent", "--color-bg-primary", AA_LARGE_TEXT, "Vurğu (qrafik element)"),
    ("--color-success", "--color-bg-primary", AA_LARGE_TEXT, "Uğur göstəricisi"),
    ("--color-warning", "--color-bg-primary", AA_LARGE_TEXT, "Xəbərdarlıq göstəricisi"),
    ("--color-danger", "--color-bg-primary", AA_LARGE_TEXT, "Xəta göstəricisi"),
    ("--color-border", "--color-bg-primary", AA_LARGE_TEXT, "Sərhəd/ayırıcı"),
    # --- örtük (shell) və nişanlar — Faza 4.2, dizayn maketlərindən ---
    # Maket bu cütlərin bir neçəsində AA-dan aşağı qalırdı; `tokens.py`-dakı
    # "DİZAYN MAKETİ İLƏ FƏRQLƏR" bölməsi hansı dəyərin niyə dəyişdiyini yazır.
    # Cütlər burada qapıya salınır ki, gələcək bir "kiçik rəng düzəlişi"
    # həmin kalibrlənməni səssizcə geri qaytarmasın.
    ("--color-text-primary", "--color-card-bg", AA_NORMAL_TEXT, "Kart üzərində əsas mətn"),
    ("--color-text-muted", "--color-card-bg", AA_NORMAL_TEXT, "Kartda solğun mətn"),
    ("--color-nav-item-text", "--color-sidebar-bg", AA_NORMAL_TEXT, "Naviqasiya maddəsi"),
    ("--color-nav-active-text", "--color-nav-active-bg", AA_NORMAL_TEXT, "Aktiv naviqasiya"),
    ("--color-nav-item-icon", "--color-sidebar-bg", AA_LARGE_TEXT, "Naviqasiya ikonu"),
    ("--color-titlebar-text", "--color-titlebar-bg", AA_NORMAL_TEXT, "Başlıq zolağı mətni"),
    ("--color-titlebar-control", "--color-titlebar-bg", AA_LARGE_TEXT, "Pəncərə düymələri"),
    ("--color-success", "--color-success-bg", AA_NORMAL_TEXT, "Uğur nişanı"),
    ("--color-warning", "--color-warning-bg", AA_NORMAL_TEXT, "Xəbərdarlıq nişanı"),
    ("--color-danger", "--color-danger-bg", AA_NORMAL_TEXT, "Xəta nişanı"),
    ("--color-info", "--color-info-bg", AA_NORMAL_TEXT, "Məlumat nişanı"),
    ("--color-text-primary", "--color-neutral-bg", AA_NORMAL_TEXT, "Neytral nişan"),
    ("--color-action-text", "--color-action-bg", AA_NORMAL_TEXT, "Əsas hərəkət düyməsi"),
    ("--color-action-bg", "--color-card-bg", AA_LARGE_TEXT, "Hərəkət düyməsi / kart"),
    ("--color-chart-bar", "--color-card-bg", AA_LARGE_TEXT, "Qrafik sütunu"),
    # ----------------------------------------------------------------------- #
    # QSS-DƏKİ FAKTİKİ İSTİFADƏ — əlçatanlıq auditindən sonra
    # ----------------------------------------------------------------------- #
    # NİYƏ BU BÖLMƏ VAR: yuxarıdakı cütlər tokenləri "nominal" rolda yoxlayır
    # (mətn / əsas fon). `theme/qss.py` isə eyni tokenləri BAŞQA fonların
    # üzərində də işlədir — `:disabled`, `:hover`, `::placeholder`, sərhəd və
    # nişan qaydalarında. Həmin kombinasiyalar heç yerdə hesablanmırdı, ona
    # görə dörd AA pozuntusu (placeholder 3.09:1, bağla-hover 3.34:1, ikon
    # sərhədi 1.30:1, deaktiv mətn 2.70:1) qapıdan sükutla keçmişdi.
    #
    # QAYDA: `qss.py`-a yeni rəng CÜTÜ (ön plan + fon eyni qaydada) yazan
    # hər kəs onu bura da əlavə edir. Cüt burada yoxdursa, o, YOXLANMIR.
    # --- placeholder (aktiv sahə → tam AA) ---
    ("--color-text-placeholder", "--color-bg-primary", AA_NORMAL_TEXT, "Placeholder (adi sahə)"),
    ("--color-text-placeholder", "--color-card-bg", AA_NORMAL_TEXT, "Placeholder (form sahəsi)"),
    # --- dolu semantik səthlərdə mətn: nişan (badge), danger/success düymə,
    #     pəncərənin "bağla" düyməsinin hover halı ---
    ("--color-bg-primary", "--color-danger", AA_NORMAL_TEXT, "Nişan/bağla — xəta"),
    ("--color-bg-primary", "--color-success", AA_NORMAL_TEXT, "Nişan mətni — uğur"),
    ("--color-bg-primary", "--color-warning", AA_NORMAL_TEXT, "Nişan mətni — xəbərdarlıq"),
    ("--color-bg-primary", "--color-info", AA_NORMAL_TEXT, "Nişan mətni — məlumat"),
    # --- fonsuz idarəetmə elementinin sərhədi (WCAG 1.4.11) ---
    ("--color-border-strong", "--color-header-bg", AA_LARGE_TEXT, "İkon düyməsi sərhədi"),
    ("--color-border-strong", "--color-card-bg", AA_LARGE_TEXT, "İkon sərhədi (kart)"),
    # --- deaktiv mətn: WCAG rəsmən istisna edir, layihə 3:1 tələb edir ---
    ("--color-text-disabled", "--color-bg-primary", AA_LARGE_TEXT, "Deaktiv mətn"),
    ("--color-text-disabled", "--color-bg-surface", AA_LARGE_TEXT, "Deaktiv düymə mətni"),
    ("--color-text-disabled", "--color-neutral-bg", AA_LARGE_TEXT, "Deaktiv hərəkət düyməsi"),
    ("--color-text-disabled", "--color-card-bg", AA_LARGE_TEXT, "Deaktiv mətn (kart)"),
    ("--color-text-disabled", "--color-bg-elevated", AA_LARGE_TEXT, "Deaktiv mətn (yüksək)"),
    ("--color-text-disabled", "--color-bg-sunken", AA_LARGE_TEXT, "Deaktiv mətn (çökük)"),
    ("--color-text-disabled", "--color-content-bg", AA_LARGE_TEXT, "Deaktiv mətn (kontent)"),
    # --- fokus halqası hər dayandığı səthin üzərində görünməlidir ---
    ("--color-focus-ring", "--color-bg-primary", AA_LARGE_TEXT, "Fokus halqası (əsas fon)"),
    ("--color-focus-ring", "--color-card-bg", AA_LARGE_TEXT, "Fokus halqası (kart)"),
    ("--color-focus-ring", "--color-header-bg", AA_LARGE_TEXT, "Fokus halqası (header)"),
    ("--color-focus-ring", "--color-sidebar-bg", AA_LARGE_TEXT, "Fokus halqası (sol panel)"),
    ("--color-focus-ring", "--color-content-bg", AA_LARGE_TEXT, "Fokus halqası (kontent)"),
    ("--color-focus-ring", "--color-neutral-bg", AA_LARGE_TEXT, "Fokus halqası (neytral)"),
    ("--color-focus-ring", "--color-nav-active-bg", AA_LARGE_TEXT, "Fokus halqası (aktiv nav)"),
    ("--color-focus-ring", "--color-pin-bg", AA_LARGE_TEXT, "Fokus halqası (PIN)"),
    # --- hover / pressed halları da MƏTN daşıyır ---
    ("--color-text-on-accent", "--color-accent-hover", AA_NORMAL_TEXT, "Vurğu düyməsi (hover)"),
    ("--color-text-on-accent", "--color-accent-pressed", AA_NORMAL_TEXT, "Vurğu düyməsi (basılı)"),
    ("--color-action-text", "--color-action-hover", AA_NORMAL_TEXT, "Hərəkət düyməsi (hover)"),
    ("--color-action-text", "--color-action-pressed", AA_NORMAL_TEXT, "Hərəkət (basılı)"),
    ("--color-text-primary", "--color-bg-sunken", AA_NORMAL_TEXT, "Düymə (hover fonu)"),
    ("--color-titlebar-text", "--color-nav-active-bg", AA_NORMAL_TEXT, "Pəncərə düyməsi (hover)"),
    ("--color-nav-item-text", "--color-neutral-bg", AA_NORMAL_TEXT, "Nav maddəsi (hover)"),
    ("--color-nav-item-text", "--color-card-bg", AA_NORMAL_TEXT, "İkinci dərəcəli düymə"),
    # --- eyni mətn rolunun DİGƏR səthləri (auditdə tapılan boşluq) ---
    ("--color-text-primary", "--color-bg-elevated", AA_NORMAL_TEXT, "Menyu/tooltip mətni"),
    ("--color-text-secondary", "--color-card-bg", AA_NORMAL_TEXT, "İkinci dərəcəli (kart)"),
    ("--color-text-secondary", "--color-bg-sunken", AA_NORMAL_TEXT, "Cədvəl başlığı"),
    ("--color-text-muted", "--color-content-bg", AA_NORMAL_TEXT, "Solğun mətn (kontent)"),
    ("--color-text-muted", "--color-bg-surface", AA_NORMAL_TEXT, "Solğun mətn (səth)"),
    ("--color-text-muted", "--color-neutral-bg", AA_NORMAL_TEXT, "Solğun mətn (neytral sətir)"),
    ("--color-text-muted", "--color-bg-sunken", AA_NORMAL_TEXT, "Solğun mətn (çökük)"),
    ("--color-text-muted", "--color-header-bg", AA_NORMAL_TEXT, "Alt başlıq (header)"),
    ("--color-text-muted", "--color-sidebar-bg", AA_NORMAL_TEXT, "Bölmə etiketi"),
]

#: PIN Handshake ekranı fərqli işıqlandırmada istifadə olunur — bölmə 9 orada
#: "əlavə yüksək-kontrast variant" tələb edir.
HIGH_CONTRAST_PAIRS: list[tuple[str, str, float, str]] = [
    ("--color-pin-text", "--color-pin-bg", AAA_NORMAL_TEXT, "PIN ekranı (AAA)"),
]


# --------------------------------------------------------------------------- #
# Rəng hesablamaları (WCAG 2.1)
# --------------------------------------------------------------------------- #


def parse_hex(color: str) -> tuple[int, int, int]:
    """`#RGB` / `#RRGGBB` / `#RRGGBBAA` formatını RGB-yə çevirir."""
    value = color.strip().lstrip("#")
    if len(value) == HEX_SHORT_LENGTH:
        value = "".join(ch * 2 for ch in value)
    if len(value) == HEX_WITH_ALPHA_LENGTH:
        value = value[:HEX_FULL_LENGTH]  # alfa kanalı kontrastda nəzərə alınmır
    if len(value) != HEX_FULL_LENGTH:
        raise ValueError(f"Yararsız rəng formatı: {color!r}")
    try:
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    except ValueError as exc:
        raise ValueError(f"Yararsız rəng formatı: {color!r}") from exc


def _channel_luminance(channel: int) -> float:
    srgb = channel / 255.0
    if srgb <= SRGB_LINEAR_THRESHOLD:
        return srgb / 12.92
    return ((srgb + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    """WCAG 2.1 nisbi parlaqlıq (0.0 = qara, 1.0 = ağ)."""
    red, green, blue = parse_hex(color)
    return (
        0.2126 * _channel_luminance(red)
        + 0.7152 * _channel_luminance(green)
        + 0.0722 * _channel_luminance(blue)
    )


def contrast_ratio(foreground: str, background: str) -> float:
    """İki rəng arasında WCAG kontrast nisbəti (1.0 – 21.0)."""
    lighter = max(relative_luminance(foreground), relative_luminance(background))
    darker = min(relative_luminance(foreground), relative_luminance(background))
    return (lighter + 0.05) / (darker + 0.05)


# --------------------------------------------------------------------------- #
# Yoxlama
# --------------------------------------------------------------------------- #


@dataclass
class Finding:
    theme: str
    description: str
    foreground_token: str
    background_token: str
    foreground: str
    background: str
    ratio: float
    required: float

    @property
    def passed(self) -> bool:
        return self.ratio >= self.required

    def format(self) -> str:
        mark = "PASS" if self.passed else "FAIL"
        return (
            f"[{mark}] {self.theme:<5} {self.description:<28} "
            f"{self.foreground_token} ({self.foreground}) / "
            f"{self.background_token} ({self.background}) = "
            f"{self.ratio:.2f}:1 (tələb: {self.required}:1)"
        )


def check_theme(
    theme_name: str,
    tokens: dict[str, str],
    pairs: list[tuple[str, str, float, str]],
    *,
    strict_missing: bool = False,
) -> tuple[list[Finding], list[str]]:
    """Bir temanı yoxlayır. `(nəticələr, çatışmayan tokenlər)` qaytarır."""
    findings: list[Finding] = []
    missing: list[str] = []

    for fg_token, bg_token, required, description in pairs:
        foreground = tokens.get(fg_token)
        background = tokens.get(bg_token)
        if foreground is None or background is None:
            for token, value in ((fg_token, foreground), (bg_token, background)):
                if value is None and token not in missing:
                    missing.append(token)
            continue

        findings.append(
            Finding(
                theme=theme_name,
                description=description,
                foreground_token=fg_token,
                background_token=bg_token,
                foreground=foreground,
                background=background,
                ratio=contrast_ratio(foreground, background),
                required=required,
            )
        )

    if strict_missing and missing:
        raise ValueError(f"{theme_name}: çatışmayan tokenlər: {', '.join(missing)}")

    return findings, missing


def load_tokens(explicit: Path | None) -> dict[str, dict[str, str]] | None:
    """Tokenləri JSON fayldan və ya `tokens.py` modulundan oxuyur."""
    if explicit is not None:
        data: dict[str, Any] = json.loads(explicit.read_text(encoding="utf-8"))
        return {name: {k: str(v) for k, v in palette.items()} for name, palette in data.items()}

    if not TOKENS_MODULE.exists():
        return None

    import importlib.util

    spec = importlib.util.spec_from_file_location("kompasos_tokens", TOKENS_MODULE)
    if spec is None or spec.loader is None:  # pragma: no cover - praktikada olmur
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return {
        "light": dict(getattr(module, "LIGHT_THEME", {})),
        "dark": dict(getattr(module, "DARK_THEME", {})),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WCAG AA kontrast yoxlaması")
    parser.add_argument("--tokens", type=Path, help="dizayn tokenlərinin JSON faylı")
    parser.add_argument("--pair", nargs=2, metavar=("FG", "BG"), help="tək cütü yoxla və çıx")
    parser.add_argument(
        "--include-high-contrast",
        action="store_true",
        help="PIN ekranı üçün AAA yoxlamasını da apar",
    )
    args = parser.parse_args(argv)

    if args.pair:
        ratio = contrast_ratio(args.pair[0], args.pair[1])
        verdict = "AA keçir" if ratio >= AA_NORMAL_TEXT else "AA KEÇMİR"
        sys.stdout.write(f"{args.pair[0]} / {args.pair[1]} = {ratio:.2f}:1 — {verdict}\n")
        return 0 if ratio >= AA_NORMAL_TEXT else 1

    themes = load_tokens(args.tokens)
    if themes is None:
        sys.stdout.write(
            "::notice::Dizayn tokenləri hələ yoxdur "
            f"({TOKENS_MODULE.relative_to(PROJECT_ROOT)}) — "
            "kontrast yoxlaması Faza 4-də aktivləşir, atlandı.\n"
        )
        return 0

    pairs = list(REQUIRED_PAIRS)
    if args.include_high_contrast:
        pairs += HIGH_CONTRAST_PAIRS

    all_findings: list[Finding] = []
    all_missing: dict[str, list[str]] = {}

    for theme_name, tokens in themes.items():
        if not tokens:
            sys.stdout.write(f"::warning::'{theme_name}' teması boşdur\n")
            continue
        findings, missing = check_theme(theme_name, tokens, pairs)
        all_findings.extend(findings)
        if missing:
            all_missing[theme_name] = missing

    for finding in all_findings:
        sys.stdout.write(finding.format() + "\n")

    for theme_name, missing in all_missing.items():
        sys.stdout.write(
            f"::error::'{theme_name}' temasında çatışmayan tokenlər: {', '.join(missing)}\n"
        )

    failures = [f for f in all_findings if not f.passed]
    for finding in failures:
        sys.stdout.write(
            f"::error::WCAG AA pozuntusu — {finding.theme}/{finding.description}: "
            f"{finding.ratio:.2f}:1 < {finding.required}:1\n"
        )

    if failures or all_missing:
        sys.stdout.write(
            f"\nUĞURSUZ: {len(failures)} kontrast pozuntusu, "
            f"{sum(len(m) for m in all_missing.values())} çatışmayan token\n"
        )
        return 1

    sys.stdout.write(f"\nUĞURLU: {len(all_findings)} rəng cütü WCAG AA-ya uyğundur\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
