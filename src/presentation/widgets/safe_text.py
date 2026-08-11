"""İstifadəçi mətninin Qt tərəfindən HTML kimi şərh olunmasının qarşısı.

──────────────────────────────────────────────────────────────────────────────
PROBLEM: QT-DƏ "DÜZ MƏTN" DEFOLT DEYİL
──────────────────────────────────────────────────────────────────────────────
`QLabel` defolt olaraq `Qt.AutoText` rejimindədir — mətnə baxıb onun zəngin
mətn (HTML) olub-olmadığını ÖZÜ qərara alır. Bazadan gələn ad, cərimə səbəbi
və ya dəstək mesajı `<b>`, `<img src=... >` kimi işarə daşıyırsa, həmin işarə
EKRANDA RENDER OLUNUR: istifadəçi məzmunu interfeysin görünüşünü idarə edir və
`<img>` vasitəsilə lokal fayl yolu sınaqdan keçirilə bilir.

Etiketlər üçün həlli birdəfəlikdir — `setTextFormat(Qt.TextFormat.PlainText)`
(bax `primitives.py`). Lakin TOOLTIP `QWidget` səviyyəsindədir və
`setTextFormat`-a TABE DEYİL: tooltip mətni həmişə eyni avtomatik yoxlamadan
keçir, yəni ayrıca müalicə tələb edir. Bu modul məhz onun üçündür.

──────────────────────────────────────────────────────────────────────────────
NİYƏ QEYD-ŞƏRTSİZ `html.escape` DEYİL
──────────────────────────────────────────────────────────────────────────────
Tooltip düz mətn kimi göstərilirsə, `html.escape` nəticəsi ekrana OLDUĞU KİMİ
düşür: "Əli & Vəli" → "Əli &amp; Vəli". Yəni hər sətri qeyd-şərtsiz escape
etmək təhlükəsizliyi artırır, amma GÖRÜNÜŞÜ dəyişir — bu isə düzəlişin
qadağan etdiyi davranış dəyişikliyidir.

Ona görə iki addım:

    1. Mətndə işarə əlaməti yoxdursa toxunulmur — Qt onu onsuz da düz mətn
       kimi göstərir, nəticə bayt-bayt köhnəsi ilə eynidir.
    2. Əlamət varsa, mətn escape edilib `<html>` içinə salınır. Bu, Qt-ni
       zəngin-mətn rejiminə MƏCBUR edir; həmin rejimdə escape olunmuş işarə
       hərfi mətn kimi görünür (`<b>` istifadəçiyə "<b>" kimi çatır) və heç
       vaxt şərh olunmur.

`Qt.mightBeRichText()` PySide6-da açılmayıb (yalnız C++ tərəfdədir), ona görə
əlamət yoxlaması burada — Qt-nin öz qaydasından DAHA GENİŞ, yəni daha
ehtiyatlı — təkrarlanır.
"""

from __future__ import annotations

import html
from typing import Final

#: Qt-nin zəngin-mətn təyini yalnız bu iki əlamətdən başlayır: birbaşa `<`
#: və ya istifadəçinin əl ilə yazdığı `&lt;` ardıcıllığı. Siyahı QƏSDƏN geniş
#: tutulub — `<` olan hər sətir (məs. "<50 dəq") escape yolundan keçir və
#: zəngin-mətn rejimində eyni görünür.
_RICH_TEXT_MARKERS: Final[tuple[str, ...]] = ("<", "&lt;")


def plain_tooltip(text: str) -> str:
    """Tooltip mətnini işarə şərhindən qoruyur, göründüyü kimi saxlayır.

    Examples:
        >>> plain_tooltip("Rəşad Məmmədov")
        'Rəşad Məmmədov'
        >>> plain_tooltip("<b>Rəşad</b>")
        '<html>&lt;b&gt;Rəşad&lt;/b&gt;</html>'
    """
    if not any(marker in text for marker in _RICH_TEXT_MARKERS):
        return text
    return f"<html>{html.escape(text, quote=True)}</html>"


__all__ = ["plain_tooltip"]
