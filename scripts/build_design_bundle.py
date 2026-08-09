#!/usr/bin/env python3
"""`ds-bundle/` qovluğunu qurur — Claude Design üçün token və ikon ixracı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU SKRİPT VAR
──────────────────────────────────────────────────────────────────────────────
`design-sync` skilli JS dizayn sistemlərini gözləyir: `dist/` → esbuild →
`_ds_bundle.js`. KompasOS isə PySide6 tətbiqidir — Qt widget-lərini brauzerdə
render olunan React paketinə çevirmək mümkün deyil.

Lakin dizayn sisteminin RƏNG, TİPOQRAFİYA və İKON qatı platformadan asılı
deyil. Bu skript onları `tokens.py` / `metrics.py` / `icons.py`-dan oxuyub
Claude Design-ın anladığı CSS formatına çevirir. Nəticədə orada qurulan hər
yeni maket avtomatik KompasOS brendində çıxır.

──────────────────────────────────────────────────────────────────────────────
MƏNBƏ OXUNMASI: NİYƏ İKİ FƏRQLİ ÜSUL
──────────────────────────────────────────────────────────────────────────────
`tokens.py` və `metrics.py` QƏSDƏN asılılıqsızdır (bax `tokens.py` başlığı —
`check_contrast.py` da onları izolyasiya ilə `exec` edir), ona görə burada da
`exec` işlədilir.

`icons.py` isə PySide6-dan asılıdır. Onu `exec` etmək bu skripti Qt-siz
mühitdə (CI konteyneri) işləməz edərdi, ona görə `_BODIES` lüğəti `ast` ilə
STATİK oxunur — icra olunmadan.

İSTİFADƏ:
    python scripts/build_design_bundle.py            # ds-bundle/ qurur
    python scripts/build_design_bundle.py --check    # yalnız yoxlayır
"""

from __future__ import annotations

import argparse
import ast
import shutil
import sys
from pathlib import Path
from typing import Any, Final

PROJECT_ROOT: Final = Path(__file__).resolve().parents[1]
THEME_DIR: Final = PROJECT_ROOT / "src" / "presentation" / "theme"
WIDGETS_DIR: Final = PROJECT_ROOT / "src" / "presentation" / "widgets"
OUT_DIR: Final = PROJECT_ROOT / "ds-bundle"

#: Ölçü tokenləri saf rəqəmdir (`"8"`) — CSS `px` gözləyir.
_PX_PREFIXES: Final = (
    "--space-",
    "--radius-",
    "--border-width",
    "--focus-ring-width",
    "--touch-target-min",
    "--font-size-",
)


# --------------------------------------------------------------------------- #
# Mənbələrin oxunması
# --------------------------------------------------------------------------- #


def _exec_module(path: Path) -> dict[str, Any]:
    """Asılılıqsız modulu izolyasiya ilə icra edir və namespace qaytarır."""
    namespace: dict[str, Any] = {"__name__": path.stem, "__file__": str(path)}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)  # noqa: S102
    return namespace


def _static_dict(path: Path, name: str) -> dict[str, str]:
    """Modulu İCRA ETMƏDƏN sabit lüğət literalını oxuyur."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        targets = [node.target] if isinstance(node, ast.AnnAssign) else getattr(node, "targets", [])
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                value = node.value
                if not isinstance(value, ast.Dict):
                    break
                return {
                    ast.literal_eval(key): ast.literal_eval(val)
                    for key, val in zip(value.keys, value.values, strict=True)
                    if key is not None
                }
    raise SystemExit(f"'{name}' lüğəti tapılmadı: {path}")


# --------------------------------------------------------------------------- #
# CSS qurulması
# --------------------------------------------------------------------------- #


def _css_value(name: str, raw: str) -> str:
    return f"{raw}px" if name.startswith(_PX_PREFIXES) else raw


def _declarations(tokens: dict[str, str], indent: str = "  ") -> str:
    return "\n".join(
        f"{indent}{name}: {_css_value(name, value)};" for name, value in tokens.items()
    )


def _header(title: str) -> str:
    return (
        "/* ─────────────────────────────────────────────────────────────────\n"
        f"   {title}\n"
        "   AVTOMATİK YARADILIB — əl ilə redaktə etməyin.\n"
        "   Mənbə: src/presentation/theme/tokens.py\n"
        "   Yenidən qurmaq: python scripts/build_design_bundle.py\n"
        "   ───────────────────────────────────────────────────────────────── */\n\n"
    )


def build_colour_files(light: dict[str, str], dark: dict[str, str]) -> dict[str, str]:
    """İşıqlı və tünd palitralar — ayrı fayllarda.

    Tünd palitra İKİ yolla tətbiq olunur: açıq seçim (`[data-theme="dark"]`)
    və sistem seçimi (`prefers-color-scheme`). İkincisi `[data-theme="light"]`
    ilə qorunur — əks halda istifadəçinin AÇIQ "işıqlı" seçimi OS-in tünd
    rejimi tərəfindən ləğv olunardı.
    """
    light_css = (
        _header("KompasOS — işıqlı tema rəngləri") + ":root {\n" + _declarations(light) + "\n}\n"
    )

    dark_css = (
        _header("KompasOS — tünd tema rəngləri")
        + ':root[data-theme="dark"] {\n'
        + _declarations(dark)
        + "\n}\n\n"
        + "@media (prefers-color-scheme: dark) {\n"
        + '  :root:not([data-theme="light"]) {\n'
        + _declarations(dark, indent="    ")
        + "\n  }\n}\n"
    )
    return {"colors-light.css": light_css, "colors-dark.css": dark_css}


def build_scale_file(typography: dict[str, str], metrics_tokens: dict[str, str]) -> str:
    """Tipoqrafiya və ölçü şkalası — temadan ASILI DEYİL."""
    return (
        _header("KompasOS — tipoqrafiya və ölçü şkalası")
        + ":root {\n"
        + _declarations(typography)
        + "\n\n"
        + _declarations(metrics_tokens)
        + "\n}\n"
    )


def build_layout_file(layout: dict[str, int]) -> str:
    """Maketdən götürülmüş örtük ölçüləri (`metrics.py`)."""
    lines = "\n".join(
        f"  --layout-{name.lower().replace('_', '-')}: {value}px;" for name, value in layout.items()
    )
    return (
        "/* ─────────────────────────────────────────────────────────────────\n"
        "   KompasOS — örtük (shell) ölçüləri\n"
        "   AVTOMATİK YARADILIB. Mənbə: src/presentation/widgets/metrics.py\n"
        "   ───────────────────────────────────────────────────────────────── */\n\n"
        ":root {\n" + lines + "\n}\n"
    )


def build_styles_entry(token_files: list[str]) -> str:
    """`styles.css` — dizaynlara YALNIZ bunun `@import` bağlaması çatır.

    Ona görə hər token faylı buradan idxal olunmalıdır; buraxılan fayl
    render olunan dizayna ÜMUMİYYƏTLƏ çatmır.
    """
    imports = "\n".join(f'@import "./tokens/{name}";' for name in token_files)
    return (
        "/* ─────────────────────────────────────────────────────────────────\n"
        "   KompasOS Dizayn Sistemi — giriş nöqtəsi\n"
        "   Dizaynlara yalnız bu faylın tranzitiv @import bağlaması çatır.\n"
        "   ───────────────────────────────────────────────────────────────── */\n\n"
        + imports
        + "\n"
    )


# --------------------------------------------------------------------------- #
# İkonlar
# --------------------------------------------------------------------------- #


def build_icons_page(bodies: dict[str, str]) -> str:
    """İkon kataloqu — kopyalana bilən SVG mənbəyi ilə.

    `stroke="currentColor"` işlədilir: beləliklə ikon yerləşdiyi mətnin
    rəngini alır və ayrıca rəng tokeni tələb etmir.
    """
    lines = [
        "# KompasOS ikon dəsti",
        "",
        f'{len(bodies)} xətt-əsaslı ikon. Hamısı `viewBox="0 0 16 16"`, doldurulmamış',
        '(`fill="none"`), `stroke-width` 1.5 və yumru uclarla çəkilir.',
        "",
        "## İstifadə",
        "",
        "Rəng `currentColor`-dan gəlir — ikonu valideyn elementin `color`-u ilə",
        "idarə edin, ayrıca rəng verməyin:",
        "",
        "```html",
        '<span style="color: var(--color-brand-amber)">',
        '  <svg width="16" height="16" viewBox="0 0 16 16" fill="none"',
        '       stroke="currentColor" stroke-width="1.5"',
        '       stroke-linecap="round" stroke-linejoin="round">',
        '    <path d="M8 3v10M3 8h10"/>',
        "  </svg>",
        "</span>",
        "```",
        "",
        "## Dəst",
        "",
    ]

    for name in sorted(bodies):
        body = bodies[name]
        lines += [
            f"### `{name}`",
            "",
            "```html",
            '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor"',
            '     stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">',
            f"  {body}",
            "</svg>",
            "```",
            "",
        ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# README
# --------------------------------------------------------------------------- #


def build_readme(counts: dict[str, int], icon_names: list[str]) -> str:
    """Konvensiya başlığı + avtomatik indeks.

    Başlıq (`.design-sync/conventions.md`) İNSAN tərəfindən yazılır və burada
    yalnız ƏVVƏLƏ əlavə olunur — bu fayl dizayn agentinin sistem promptuna
    daxil edilir, ona görə məzmunu qurma anında birləşdirilməlidir.
    """
    header_path = PROJECT_ROOT / ".design-sync" / "conventions.md"
    header = header_path.read_text(encoding="utf-8").rstrip() if header_path.exists() else ""

    body = [
        "",
        "",
        "---",
        "",
        "## Bu paketdə nə var",
        "",
        f"- `styles.css` — giriş nöqtəsi ({len(icon_names)} ikon ayrıca sənəddədir)",
        f"- `tokens/colors-light.css` — {counts['colour_tokens']} rəng, `:root`",
        f"- `tokens/colors-dark.css` — həmin {counts['colour_tokens']} rəng, "
        '`[data-theme="dark"]` və `prefers-color-scheme`',
        f"- `tokens/scale.css` — {counts['typography_tokens']} tipoqrafiya + "
        f"{counts['metric_tokens']} ölçü tokeni",
        f"- `tokens/layout.css` — {counts['layout_tokens']} örtük ölçüsü (maketdən)",
        f"- `guidelines/icons.md` — {counts['icons']} xətt-ikon, SVG mənbəyi ilə",
        "",
        "## Mənbə",
        "",
        "Tokenlər KompasOS reposundan avtomatik ixrac olunur:",
        "",
        "| Fayl | Mənbə |",
        "|---|---|",
        "| `tokens/colors-*.css` | `src/presentation/theme/tokens.py` |",
        "| `tokens/scale.css` | `src/presentation/theme/tokens.py` |",
        "| `tokens/layout.css` | `src/presentation/widgets/metrics.py` |",
        "| `guidelines/icons.md` | `src/presentation/widgets/icons.py` |",
        "",
        "Yenidən qurmaq: `python scripts/build_design_bundle.py`",
        "",
        "## Kontrast",
        "",
        "Bütün rəng cütləri WCAG AA qapısından keçir "
        "(`python scripts/check_contrast.py --include-high-contrast`). "
        "Token dəyişdirən hər dəyişiklik həmin yoxlamadan keçməlidir.",
        "",
    ]
    return header + "\n".join(body)


# --------------------------------------------------------------------------- #
# Qurulma
# --------------------------------------------------------------------------- #


def build() -> dict[str, int]:
    tokens_ns = _exec_module(THEME_DIR / "tokens.py")
    metrics_ns = _exec_module(WIDGETS_DIR / "metrics.py")
    icon_bodies = _static_dict(WIDGETS_DIR / "icons.py", "_BODIES")

    light: dict[str, str] = tokens_ns["LIGHT_THEME"]
    dark: dict[str, str] = tokens_ns["DARK_THEME"]
    typography: dict[str, str] = tokens_ns["TYPOGRAPHY"]
    metrics_tokens: dict[str, str] = tokens_ns["METRICS"]

    layout = {
        name: value
        for name, value in metrics_ns.items()
        if name.isupper() and isinstance(value, int) and not name.startswith("_")
    }

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    (OUT_DIR / "tokens").mkdir(parents=True)
    (OUT_DIR / "guidelines").mkdir(parents=True)

    files = build_colour_files(light, dark)
    files["scale.css"] = build_scale_file(typography, metrics_tokens)
    files["layout.css"] = build_layout_file(layout)

    for name, content in files.items():
        (OUT_DIR / "tokens" / name).write_text(content, encoding="utf-8")

    # SIRA VACİBDİR: işıqlı palitra `:root`-a yazır, tünd palitra isə onu
    # `[data-theme="dark"]` ilə üstələyir. Əlifba sırası (`colors-dark` əvvəl)
    # spesifiklik sayəsində yenə işləyərdi, lakin oxuyan adam üçün yanıldıcıdır.
    order = ["colors-light.css", "colors-dark.css", "scale.css", "layout.css"]
    missing = set(files) - set(order)
    if missing:
        raise SystemExit(f"`order` siyahısına əlavə edilməyən token faylı: {sorted(missing)}")
    (OUT_DIR / "styles.css").write_text(build_styles_entry(order), encoding="utf-8")
    (OUT_DIR / "guidelines" / "icons.md").write_text(
        build_icons_page(icon_bodies), encoding="utf-8"
    )

    counts = {
        "colour_tokens": len(light),
        "typography_tokens": len(typography),
        "metric_tokens": len(metrics_tokens),
        "layout_tokens": len(layout),
        "icons": len(icon_bodies),
    }
    (OUT_DIR / "README.md").write_text(build_readme(counts, sorted(icon_bodies)), encoding="utf-8")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Claude Design bundle qurucusu")
    parser.add_argument("--check", action="store_true", help="yalnız mənbələri yoxla")
    args = parser.parse_args(argv)

    if args.check:
        _exec_module(THEME_DIR / "tokens.py")
        _static_dict(WIDGETS_DIR / "icons.py", "_BODIES")
        sys.stdout.write("Mənbələr oxuna bilir.\n")
        return 0

    counts = build()
    sys.stdout.write(
        f"ds-bundle/ quruldu — {counts['colour_tokens']} rəng, "
        f"{counts['typography_tokens']} tipoqrafiya, "
        f"{counts['metric_tokens']} ölçü, {counts['layout_tokens']} örtük, "
        f"{counts['icons']} ikon.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
