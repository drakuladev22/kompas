"""Yerləşdirmə (layout) köməkçiləri — Faza 4.2.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA FUNKSİYA
──────────────────────────────────────────────────────────────────────────────
Bir siyahını yeniləmək üçün Qt-də əvvəlcə köhnə widget-ləri təmizləmək
lazımdır və bunun doğru forması göründüyündən uzundur:

    * `takeAt(0)` `QLayoutItem | None` qaytarır — boş layout-da `None` gəlir;
    * `item.widget()` də `None` ola bilər (aralıq/spacer elementləri üçün);
    * `removeWidget` KİFAYƏT DEYİL — widget valideynsiz qalır və yaddaşda
      asılı qalaraq siqnal almağa davam edir; `deleteLater()` lazımdır.

Bu üç detal 20-dən çox yerdə təkrarlanırdı. Bir yerdə saxlamaq həm təkrarı,
həm də "bir yerdə unudulmuş `deleteLater`" riskini aradan qaldırır.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QLayout


def clear_layout(layout: QLayout, *, keep_last: int = 0) -> None:
    """Layout-dakı widget-ləri silir.

    Args:
        layout: Təmizlənəcək yerləşdirmə.
        keep_last: Sondan neçə element saxlanılsın. Adətən `1` — sonda
            `addStretch()` ilə qoyulmuş boşluğu qorumaq üçün (o, silinsə
            məzmun mərkəzə sürüşərdi).
    """
    while layout.count() > keep_last:
        item = layout.takeAt(0)
        if item is None:
            return
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


def detach_layout(layout: QLayout) -> None:
    """Widget-ləri layout-dan ÇIXARIR, lakin SİLMİR.

    `clear_layout()`-dan fərqi budur ki, widget yaşamağa davam edir və
    sonradan yenidən əlavə oluna bilər. Kiosk axınında məhz belədir: PIN
    klaviaturası ↔ İşçi Ana Ekranı arasında keçid zamanı hər dəfə yeni
    klaviatura qurmaq həm israfdır, həm də daxil edilmiş vəziyyəti (blok
    sayğacı) itirərdi.
    """
    while layout.count():
        item = layout.takeAt(0)
        if item is None:
            return
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
