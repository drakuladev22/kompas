"""Pəncərə enindən asılı tərtibat rejimi (breakpoint) — Faza 4.2 davamı.

NİYƏ `widgets/`, NİYƏ `shell/`: rejimi HƏM örtük (`shell/admin_shell.py`), HƏM
ekran bazası (`screens/base.py`) oxuyur. Modul `shell/` altında qalsaydı,
`screens/` paketi `shell/__init__.py`-ı — yəni bütün örtük ağacını — idxal
etməyə məcbur olardı. `widgets/` isə təqdimat qatının ƏN AŞAĞI təbəqəsidir və
onu hər kəs sərbəst idxal edir (`metrics.py` ilə eyni səbəb).


`uxui.md` Addım 3:

    "Bunu `resizeEvent`-ə bağlı bir MƏRKƏZİ funksiya ilə et (hər widget öz-özünə
     yoxlamasın, mərkəzi bir «layout mode» siqnalına abunə olsun) — təkrarlanan
     kod yaranmasın."

──────────────────────────────────────────────────────────────────────────────
NİYƏ SİQNAL, NİYƏ HƏR WIDGET-DƏ `resizeEvent`
──────────────────────────────────────────────────────────────────────────────
Qt-də hər widget öz `resizeEvent`-ini ala bilər, yəni sol panel də, hər ekran
da eni özü ölçə bilərdi. Bu yol İKİ sürətli səhv gətirir:

1. **Ölçülən en fərqlidir.** Sol panel özünü 226px görür, ekran isə
   `pəncərə − 226`. Hər biri "1280 həddi" ilə öz enini müqayisə etsəydi,
   həddin mənası widget-dən widget-ə dəyişərdi və rejim keçidləri sıradan
   çıxardı (panel yığılan kimi ekran genişlənir → ekran "geniş" rejimə keçir
   → panel açılır → sonsuz dövrə).

2. **Hədd ədədi çoxalır.** Eyni 1280/700 cütü onlarla faylda təkrarlanardı.

Ona görə ölçən TƏK yer var — üst pəncərə (`FramelessWindow`), və o, nəticəni
bir siqnalla yayır. Ölçən bir, abunə olan çox.

──────────────────────────────────────────────────────────────────────────────
NİYƏ İKİ REJİM, ÜÇ DEYİL
──────────────────────────────────────────────────────────────────────────────
`uxui.md` üçüncü diapazonu (`< 700px`) açıq şəkildə pəncərənin MİNİMUM ölçüsü
ilə bağlamağı tapşırır: "əgər praktiki deyilsə, pəncərənin öz minimum ölçüsünü
bu həddə qoy … əvəzinə mürəkkəb əlavə breakpoint qurma". Yəni 700px-dən aşağı
vəziyyət heç vaxt yaranmır — ona rejim vermək ölü kod olardı.
"""

from __future__ import annotations

from enum import Enum

from src.presentation.widgets import metrics


class LayoutMode(str, Enum):
    """Pəncərə eninə görə tərtibat rejimi.

    `str, Enum` layihə konvensiyasıdır (CLAUDE.md bölmə 4): dəyər log/siqnal
    çıxışında olduğu kimi görünür və `Signal(str)` ilə birbaşa ötürülə bilir.
    """

    #: ≥ 1280px — sol panel tam (ikon + mətn), kartlar yan-yana.
    WIDE = "WIDE"
    #: 700–1280px — sol panel yalnız-ikon, kartlar bir sütunda.
    COMPACT = "COMPACT"


def mode_for_width(width: int) -> LayoutMode:
    """Pəncərə eninə uyğun rejimi qaytarır.

    Hədd DAXİLDİR: tam olaraq 1280px `WIDE`-dır, çünki spesifikasiyanın
    minimum pəncərə ölçüsü məhz 1280-dir və ilk açılışda tətbiq dərhal
    daraldılmış görünsəydi, bu, qüsur kimi oxunardı.
    """
    if width >= metrics.LAYOUT_BREAKPOINT_WIDE:
        return LayoutMode.WIDE
    return LayoutMode.COMPACT


__all__ = ["LayoutMode", "mode_for_width"]
