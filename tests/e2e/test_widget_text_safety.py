"""Etiket və tooltip mətninin HTML kimi şərh olunmadığının yoxlanması.

Təhlükəsizlik auditinin 1-ci tapıntısı: `QLabel` defolt `Qt.AutoText`
rejimindədir, yəni bazadan gələn "Rəşad <b>MMC</b>" sətri ekranda QALIN
şriftlə görünürdü — istifadəçi məzmunu interfeysin görünüşünü idarə edirdi.
`<img src=...>` isə lokal fayl yollarını sınaqdan keçirməyə imkan verirdi.

Testlər REAL widget qurur (offscreen), çünki `textFormat()` yalnız qurulmuş
`QLabel`-də oxuna bilir. Ekranların hamısı mətni məhz bu fabrikalardan alır
(bax `widgets/primitives.py`), ona görə bir yerdəki yoxlama 20+ sink-i əhatə
edir.
"""

from __future__ import annotations

import pytest

from tests.conftest import requires_qt

pytestmark = [pytest.mark.e2e, pytest.mark.qt]

#: Hücum yükü — hər fabrikaya EYNİ sətir verilir.
ATTACK = "<b>Rəşad</b><img src=x onerror=1>"


@requires_qt
@pytest.mark.parametrize(
    "factory_name",
    ["title_label", "muted_label", "mono_label", "section_label", "body_label"],
)
def test_text_factories_render_markup_literally(qt_app, factory_name: str) -> None:  # type: ignore[no-untyped-def]
    """İşarə RENDER OLUNMUR — mətn olduğu kimi saxlanılır."""
    from PySide6.QtCore import Qt

    from src.presentation.widgets import primitives

    label = getattr(primitives, factory_name)(ATTACK)

    assert label.textFormat() is Qt.TextFormat.PlainText
    # Davranış dəyişmir: mətnin özü itmir və ya kəsilmir (`section_label`
    # onu yalnız böyük hərfə çevirir).
    assert "Rəşad" in label.text() or "RƏŞAD" in label.text()
    assert "<b>" in label.text().lower(), (
        "mətn sükutla təmizlənməməlidir — yalnız şərh olunmamalıdır"
    )


@requires_qt
def test_plain_label_is_plain_text_with_and_without_parent(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Rolsuz etiketlərin ortaq fabriki — birbaşa `QLabel(...)` əvəzi."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget

    from src.presentation.widgets.primitives import plain_label

    host = QWidget()
    orphan = plain_label(ATTACK)
    child = plain_label("Mətn", host)

    assert orphan.textFormat() is Qt.TextFormat.PlainText
    assert child.textFormat() is Qt.TextFormat.PlainText
    # Valideyn və mətn `QLabel(...)`-dəki kimi ötürülür — davranış eynidir.
    assert child.parent() is host
    assert child.text() == "Mətn"
    assert orphan.text() == ATTACK


@requires_qt
def test_chip_and_link_labels_are_plain_text(qt_app) -> None:  # type: ignore[no-untyped-def]
    """`Chip`/`FilterChip`/`LinkLabel` də `QLabel` törəmələridir."""
    from PySide6.QtCore import Qt

    from src.presentation.widgets.primitives import Chip, FilterChip, LinkLabel

    assert Chip(ATTACK).textFormat() is Qt.TextFormat.PlainText
    assert FilterChip("key", ATTACK).textFormat() is Qt.TextFormat.PlainText
    assert LinkLabel(ATTACK).textFormat() is Qt.TextFormat.PlainText


@requires_qt
def test_avatar_tooltip_does_not_carry_live_markup(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Tooltip `setTextFormat`-a tabe deyil — ad ayrıca süzülür."""
    from src.presentation.widgets.primitives import Avatar

    avatar = Avatar("Rəşad Məmmədov", background="#123456", foreground="#FFFFFF")
    avatar.set_name(ATTACK)

    tooltip = avatar.toolTip()
    assert "<b>" not in tooltip
    assert "<img" not in tooltip
    assert "&lt;b&gt;" in tooltip, "mətn itməməlidir, yalnız zərərsizləşməlidir"


@requires_qt
def test_ordinary_name_keeps_its_tooltip_unchanged(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Adi ad üçün tooltip bayt-bayt köhnəsi ilə eynidir."""
    from src.presentation.widgets.primitives import Avatar

    avatar = Avatar("Rəşad Məmmədov", background="#123456", foreground="#FFFFFF")
    avatar.set_name("Günel Əliyeva")

    assert avatar.toolTip() == "Günel Əliyeva"
    assert avatar._initials == "GƏ"
