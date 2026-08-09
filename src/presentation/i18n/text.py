"""Azərbaycan dilinə uyğun mətn çevirmələri — Faza 4.2.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `str.upper()` KİFAYƏT ETMİR
──────────────────────────────────────────────────────────────────────────────
Azərbaycan əlifbasında `i` hərfinin böyüyü NÖQTƏLİ `İ`-dir, `I` isə AYRI bir
hərfdir (onun kiçiyi nöqtəsiz `ı`). Python-un standart `str.upper()` metodu
Unicode-un defolt qaydasını tətbiq edir və `i` → `I` çevirir, yəni nöqtəni
İTİRİR:

    "Naviqasiya".upper()  →  "NAVIQASIYA"   (düzgünü: NAVİQASİYA)
    "İşçi".upper()        →  "İŞÇI"         (düzgünü: İŞÇİ)

Nəticə bütün cədvəl başlıqlarında və sol paneldəki bölmə etiketində görünür.
Azərbaycan dilli məhsulda bu, orfoqrafiya səhvidir.

Python `str.upper()`-ə lokal (locale) vermir, ona görə çevirmə əl ilə edilir:
əvvəlcə `i` → `İ` əvəz olunur, sonra qalanı adi qaydada böyüdülür (`ı` → `I`
onsuz da düzgün işləyir).
"""

from __future__ import annotations


def az_upper(text: str) -> str:
    """Mətni Azərbaycan qaydası ilə böyük hərflərə çevirir.

    Examples:
        >>> az_upper("Naviqasiya")
        'NAVİQASİYA'
        >>> az_upper("İşçi")
        'İŞÇİ'
        >>> az_upper("ıxmaq")
        'IXMAQ'
    """
    # Sıra VACİBDİR: `i` əvvəlcə `İ`-yə çevrilir, əks halda `upper()` onu
    # nöqtəsiz `I` edərdi və məlumat itərdi.
    return text.replace("i", "İ").upper()


__all__ = ["az_upper"]
