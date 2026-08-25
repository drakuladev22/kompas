"""i18n mexanizmi — Faza 4.1 (bölmə 9, Faza 4.1 "ÇATIŞMAZLIQ DÜZƏLİŞİ").

──────────────────────────────────────────────────────────────────────────────
NİYƏ TƏK DİL, AMMA YENƏ DƏ ÇƏRÇİVƏ
──────────────────────────────────────────────────────────────────────────────
Spesifikasiya bu məsələdə qəsdən dəqiqdir: ilk buraxılışın YEGANƏ interfeys
dili Azərbaycan dilidir — bütün mətn, düymə, xəbərdarlıq və status yazıları
Azərbaycan dilində olmalıdır; `en`/`ru` tərcüməsi bu layihənin ƏHATƏSİNDƏ
DEYİL. `user_preferences.language` sütunundakı `CHECK (language IN ('az'))`
məhz bunu qoruyur.

Onda çərçivə niyə lazımdır? Çünki mətnləri widget kodunun içinə səpələmək
gələcəkdə dil əlavə etməyi TAM YENİDƏN YAZMA işinə çevirir. Bütün mətnlərin
bir kataloqdan keçməsi indi heç nəyə başa gəlmir, sonra isə yeni dil sadəcə
yeni kataloq faylı deməkdir.

DİL SEÇİCİSİ ARTIQ VAR — `v2backlog.md` Faza 8.1 onu ROOT İdarə Mərkəzinə
əlavə etdi (`SystemLimitKey.UI_LANGUAGE`). Bu, yuxarıdakı mülahizəni
DƏYİŞMİR: siyahı `AVAILABLE_UI_LANGUAGES`-dən doldurulur və orada hazırda
YALNIZ `az` var, yəni seçici bu gün tək elementlidir. Seçicinin indidən
mövcud olması qəsdlidir — ikinci dil əlavə olunanda dəyişəcək yeganə yer
kataloq faylı olur, ekran yox.

──────────────────────────────────────────────────────────────────────────────
ÇATIŞMAYAN AÇAR: SƏRT (dev/CI) vs YUMŞAQ (istehsalat)
──────────────────────────────────────────────────────────────────────────────
Səhv yazılmış açar iki cür pis nəticə verə bilər: (a) kassada işçi
`fine.appeal.title` kimi texniki sətir görür, (b) tətbiq çökür. İkisi də
qəbuledilməzdir, lakin fərqli mühitlərdə:

    DEV/TEST/CI   `TranslationError` atılır — səhv buraxılışa çatmır.
    PRODUCTION    xəta jurnala yazılır, ekranda açarın özü görünür. Çökmə
                  bir mətn qüsuruna görə bütün növbəni dayandırardı.

Rejim `KOMPASOS_ENV` ilə seçilir — layihənin qalanı ilə eyni dəyişən.
"""

from __future__ import annotations

import os
from typing import Final

from src.shared.exceptions import KompasOSError
from src.shared.logger import get_logger

_log = get_logger(__name__)

#: İlk buraxılışın yeganə dili. `user_preferences.language` ilə eyni dəyər.
DEFAULT_LOCALE: Final = "az"

#: Bu mühitlərdə çatışmayan açar ÇÖKMƏ deyil, jurnal qeydi yaradır.
_LENIENT_ENVS: Final = frozenset({"PRODUCTION", "STAGING"})


class TranslationError(KompasOSError):
    """Kataloqda olmayan açar və ya çatışmayan parametr."""

    user_message = "İnterfeys mətni tapılmadı."


def _strict_by_default() -> bool:
    return os.environ.get("KOMPASOS_ENV", "PRODUCTION").upper() not in _LENIENT_ENVS


class Translator:
    """Açar → Azərbaycan mətni çevirici.

    Args:
        catalog: Açar/mətn sözlüyü.
        locale: Kataloqun dili — hazırda yalnız `az`.
        strict: `True` olduqda çatışmayan açar/parametr istisna atır.
            `None` verilsə mühitə görə təyin olunur (yuxarıdakı izah).
    """

    def __init__(
        self,
        catalog: dict[str, str],
        *,
        locale: str = DEFAULT_LOCALE,
        strict: bool | None = None,
    ) -> None:
        self._catalog = dict(catalog)
        self._locale = locale
        self._strict = _strict_by_default() if strict is None else strict

    @property
    def locale(self) -> str:
        return self._locale

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(self._catalog)

    def has(self, key: str) -> bool:
        return key in self._catalog

    def __call__(self, key: str, /, **params: object) -> str:
        """`tr("login.title")` və ya `tr("fine.amount", manat=12)`."""
        return self.text(key, **params)

    def text(self, key: str, /, **params: object) -> str:
        """Açarın mətnini qaytarır, `{parametr}` yer tutucularını doldurur."""
        template = self._catalog.get(key)
        if template is None:
            return self._missing(key)

        if not params:
            return template

        try:
            return template.format(**params)
        except (KeyError, IndexError) as exc:
            message = f"'{key}' mətninin parametri çatışmır: {exc}"
            if self._strict:
                raise TranslationError(message, context={"key": key}) from exc
            _log.error("I18N_PARAM_MISSING", extra={"key": key, "detail": str(exc)})
            return template

    def _missing(self, key: str) -> str:
        message = f"Kataloqda '{key}' açarı yoxdur ({self._locale})"
        if self._strict:
            raise TranslationError(message, context={"key": key, "locale": self._locale})
        _log.error("I18N_KEY_MISSING", extra={"key": key, "locale": self._locale})
        return key


# --------------------------------------------------------------------------- #
# Qlobal nüsxə
# --------------------------------------------------------------------------- #
# Widget-lər `tr(...)` funksiyasını birbaşa idxal edir — hər konstruktora
# tərcüməçi ötürmək yüzlərlə yerdə şablon kod yaradardı. Dil işə düşmə anında
# bir dəfə təyin olunur və sonra dəyişmir (yalnız bir dil var).

_translator: Translator | None = None


def configure_i18n(
    catalog: dict[str, str] | None = None,
    *,
    locale: str = DEFAULT_LOCALE,
    strict: bool | None = None,
) -> Translator:
    """Qlobal tərcüməçini qurur (kompozisiya kökündən çağırılır)."""
    global _translator

    if catalog is None:
        from src.presentation.i18n.catalog_az import CATALOG_AZ  # noqa: PLC0415

        catalog = CATALOG_AZ

    _translator = Translator(catalog, locale=locale, strict=strict)
    _log.info("I18N_CONFIGURED", extra={"locale": locale, "key_count": len(catalog)})
    return _translator


def get_translator() -> Translator:
    """Qlobal tərcüməçi — qurulmayıbsa defolt kataloqla özü qurulur."""
    if _translator is None:
        return configure_i18n()
    return _translator


def reset_i18n() -> None:
    """Qlobal nüsxəni sıfırlayır — testlər üçün."""
    global _translator
    _translator = None


def tr(key: str, /, **params: object) -> str:
    """Qısa forma — widget kodunda işlədilən yeganə giriş nöqtəsi."""
    return get_translator().text(key, **params)


__all__ = [
    "DEFAULT_LOCALE",
    "TranslationError",
    "Translator",
    "configure_i18n",
    "get_translator",
    "reset_i18n",
    "tr",
]
