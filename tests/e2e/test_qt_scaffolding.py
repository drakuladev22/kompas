"""pytest-qt karkasının smoke testi (spesifikasiya bölmə 1).

Faza 1-də hələ GUI yoxdur. Bu fayl karkasın işlək olduğunu təsdiqləyir və
Faza 4-də doldurulacaq E2E ssenarilərinin yerini rəsmiləşdirir:

    * PIN handshake → Camera Operator təsdiqi/override → cərimə hesablanması → sync
    * Dual-control eskalasiyası (30+ dəqiqəlik override)
    * Offline → online konflikt həlli

PySide6 quraşdırılmayıbsa testlər `skip` olunur — CI erkən fazalarda qırmızı olmur.
"""

from __future__ import annotations

import pytest

from tests.conftest import requires_qt

pytestmark = [pytest.mark.e2e, pytest.mark.qt]


@requires_qt
def test_qapp_fixture_available(qt_app) -> None:  # type: ignore[no-untyped-def]
    """`pytest-qt` işləyir və QApplication yaradıla bilir."""
    assert qt_app is not None


@requires_qt
def test_widget_can_be_shown(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Widget yaradılıb göstərilə bilir (offscreen platformada da)."""
    from PySide6.QtWidgets import QLabel

    label = QLabel("KompasOS")
    qtbot.addWidget(label)
    label.show()

    assert label.text() == "KompasOS"


@pytest.mark.skip(
    reason="Faza 5 — repository/use-case qoşulmayıb. İnterfeys tərəfi hazırdır: "
    "bax tests/e2e/test_antifraud_flow_e2e.py"
)
def test_pin_handshake_to_fine_calculation_e2e() -> None:
    """PLACEHOLDER: STEP 1 → STEP 2 → STEP 3 → cərimə → sync tam axını.

    Faza 4.2-də TAMAMLANAN hissə (`test_antifraud_flow_e2e.py`):
        * PIN daxil edilməsi və 4 rəqəmdən sonra göndərilməsi,
        * səhv PIN / lockout davranışı,
        * PIN → İşçi Ana Ekranı keçidi,
        * cərimə formasının foto sübutu olmadan göndərilməməsi.

    Burada QALAN hissə: cərimənin faktiki hesablanması və 1C sinxronizasiyası
    — hər ikisi repository qatını tələb edir.
    """


@pytest.mark.skip(
    reason="Faza 5 — ikinci təsdiqin SAXLANMASI repository tələb edir. "
    "Eskalasiya şərti Faza 4.2-də yoxlanılır: tests/e2e/test_antifraud_flow_e2e.py"
)
def test_dual_control_escalation_e2e() -> None:
    """PLACEHOLDER: 30+ dəqiqəlik manual override → HR_Admin/CEO ikinci təsdiqi.

    Faza 4.2-də TAMAMLANAN hissə: 30 dəqiqə həddinin hesablanması, modalın
    "Dual-Control tələb olunacaq" xəbərdarlığı və məcburi səbəb sahəsi
    (`test_antifraud_flow_e2e.py`).

    Burada QALAN hissə: ikinci səlahiyyətli şəxsin təsdiqi və gözləmə
    vəziyyətinin bazada saxlanması.
    """


@pytest.mark.skip(reason="Faza 3/4-də implementasiya olunur — offline buffer yoxdur")
def test_offline_to_online_conflict_resolution_e2e() -> None:
    """PLACEHOLDER: offline yazı → online sync → CONFLICT → HR manual həlli."""
