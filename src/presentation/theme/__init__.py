"""KompasOS Dizayn Sistemi — dark/light tokenlər və tema meneceri (bölmə 9).

Üç modul:

    `tokens.py`   Rənglərin YEGANƏ mənbəyi. PySide6-dan asılı deyil, çünki
                  CI-dakı kontrast yoxlayıcısı onu təkbaşına idxal edir.
    `qss.py`      Tokenlərdən Qt Style Sheet qurur (`{{--token}}` şablonu).
    `manager.py`  Seçimi həll edir, tətbiq edir, dəyişikliyi yayır.

`manager` PySide6 idxal etdiyi üçün burada YENİDƏN İXRAC EDİLMİR — əks halda
`tokens`-ı oxumaq istəyən skript də Qt yükləməyə məcbur olardı.
"""

from src.presentation.theme.qss import StyleSheetError, build_stylesheet, render
from src.presentation.theme.tokens import (
    BRAND_AMBER,
    BRAND_NAVY,
    DARK_THEME,
    LIGHT_THEME,
    METRICS,
    THEMES,
    TYPOGRAPHY,
    ThemeMode,
    theme_tokens,
)

__all__ = [
    "BRAND_AMBER",
    "BRAND_NAVY",
    "DARK_THEME",
    "LIGHT_THEME",
    "METRICS",
    "THEMES",
    "TYPOGRAPHY",
    "StyleSheetError",
    "ThemeMode",
    "build_stylesheet",
    "render",
    "theme_tokens",
]
