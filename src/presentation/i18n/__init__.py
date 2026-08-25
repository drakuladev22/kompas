"""i18n qatı (bölmə 9) — Faza 4.

translator   — açar → mətn çeviricisi, sərt/yumşaq rejim
catalog_az   — Azərbaycan dili kataloqu (yeganə dil)

`tr` BU PAKETDƏN İXRAC OLUNUR və ekranların yeganə giriş nöqtəsidir: hər
konstruktora tərcüməçi ötürmək yüzlərlə yerdə şablon kod yaradardı
(`translator.py`-dakı «Qlobal nüsxə» bölməsi).
"""

from src.presentation.i18n.catalog_az import CATALOG_AZ
from src.presentation.i18n.translator import (
    DEFAULT_LOCALE,
    TranslationError,
    Translator,
    configure_i18n,
    get_translator,
    reset_i18n,
    tr,
)

__all__ = [
    "CATALOG_AZ",
    "DEFAULT_LOCALE",
    "TranslationError",
    "Translator",
    "configure_i18n",
    "get_translator",
    "reset_i18n",
    "tr",
]
