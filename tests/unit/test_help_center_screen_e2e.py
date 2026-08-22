"""`HelpCenterScreen` — REAL Qt e2e sınaqları (kontrollersiz ekran).

──────────────────────────────────────────────────────────────────────────────
NİYƏ KONTROLLER YOXDUR, TEST YENƏ DƏ LAZIMDIR
──────────────────────────────────────────────────────────────────────────────
`controllers/` altında `help_center.py` YOXDUR: `support_requested` siqnalı
birbaşa `app.py::_open_support_panel`-ə bağlanır (bax `app.py:3109`),
`topic_selected` isə heç kimə bağlı deyil (izahat: "kontroller lazım olsa
qoşula bilər", bax `HelpCenterScreen._on_topic` şərhi). Yəni bu ekranın bütün
davranışı EKRANIN ÖZÜNDƏDİR — məhz buna görə `test_signal_wiring_gate.py`
kimi «siqnal bağlıdırmı?» yoxlaması bura İŞLƏMİR: bağlı olmayan siqnal
QƏSDƏNDİR. Əsl sual budur: real "Dəstəyə yaz" düyməsi `may_contact_support`
qapısına REAL tabedirmi, real çip REAL karta sürüşdürürmü, boş süzgəc REAL
boş-vəziyyət göstərirmi.
"""

from __future__ import annotations

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


# --------------------------------------------------------------------------- #
# 1. «GÖRMƏK = SƏLAHİYYƏTİN OLMASI» — bölmə 8, sətir 279
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_contact_support_button_is_not_built_at_all_without_the_flag(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`may_contact_support=False` — düymə SÖNDÜRÜLMÜR, ÜMUMİYYƏTLƏ QURULMUR."""
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_h import HelpCenterScreen

    screen = HelpCenterScreen(theme, may_contact_support=False)
    qtbot.addWidget(screen)

    texts = [b.text() for b in screen.findChildren(QPushButton)]
    assert "Dəstəyə yaz" not in texts


@requires_qt
def test_the_contact_support_button_is_real_and_clickable_with_the_flag(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_h import HelpCenterScreen

    screen = HelpCenterScreen(theme, may_contact_support=True)
    qtbot.addWidget(screen)

    received: list[str] = []
    screen.support_requested.connect(lambda: received.append("clicked"))

    button = next(b for b in screen.findChildren(QPushButton) if b.text() == "Dəstəyə yaz")
    button.click()

    assert received == ["clicked"]


# --------------------------------------------------------------------------- #
# 2. Mövzu çipi → real kart sürüşdürməsi + boş süzgəc
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_a_topic_chip_scrolls_to_its_real_card_and_emits(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    from src.presentation.screens.group_h import HelpCenterScreen, TopicChip

    screen = HelpCenterScreen(theme)
    qtbot.addWidget(screen)
    screen.show()

    received: list[str] = []
    screen.topic_selected.connect(received.append)

    assert "fines" in screen._topic_cards  # sanity: kart REAL qurulub
    chip = next(c for c in screen.findChildren(TopicChip) if c.key == "fines")
    qtbot.mouseClick(chip, Qt.MouseButton.LeftButton)  # REAL siçan kliki, çağırış YOX

    assert received == ["fines"]


@requires_qt
def test_filtering_to_an_empty_set_shows_the_real_empty_state_not_a_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Yeni quraşdırılmış sistemdə heç bir mövzu görünə bilməz — bu, XƏTA DEYİL
    (bax `set_visible_topics` şərhi).

    QA-FULL Faza 3 tapıntısı: bu iddia (`_topic_cards == {}`) əvvəlcə QIRMIZI
    idi — boş süzgəc yolunda `_topic_cards.clear()` çağırılmırdı, dict silinmiş
    (`deleteLater()`) `HelpTopicCard` widget-lərinə köhnəlmiş istinad
    saxlayırdı. `ui-fixes` `set_visible_topics`-i düzəltdi (bax onun şərhi) —
    test İNDİ real düzəlişi qoruyur."""
    from src.presentation.screens.group_h import HelpCenterScreen

    screen = HelpCenterScreen(theme)
    qtbot.addWidget(screen)

    screen.set_visible_topics(frozenset())  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "empty"
    assert screen._topic_cards == {}


@requires_qt
def test_filtering_to_a_subset_hides_the_rest_and_none_is_shown_by_a_stale_chip(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_h import HELP_TOPICS, HelpCenterScreen

    screen = HelpCenterScreen(theme)
    qtbot.addWidget(screen)

    screen.set_visible_topics(frozenset({"leave"}))

    assert set(screen._topic_cards) == {"leave"}
    assert screen.switcher().current_state() == "content"
    # digər mövzuların çipi ekranda QALMAMALIDIR — köhnə çipə klik "leave"dən
    # başqa açar EMİT ETMƏMƏLİDİR (çünki o çip artıq YOXDUR).
    remaining_titles = {title for key, title, _ in HELP_TOPICS if key != "leave"}
    button_texts = {b.text() for b in screen.findChildren(QPushButton)}
    assert not (remaining_titles & button_texts)


@requires_qt
def test_switching_from_empty_back_to_all_topics_restores_real_content(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Boş → dolu keçid REAL vəziyyət keçidi olmalıdır, «sükutlu boş» qalmamalıdır."""
    from src.presentation.screens.group_h import HELP_TOPICS, HelpCenterScreen

    screen = HelpCenterScreen(theme)
    qtbot.addWidget(screen)
    screen.set_visible_topics(frozenset())
    assert screen.switcher().current_state() == "empty"

    screen.set_visible_topics(None)  # `None` = HAMISI

    assert screen.switcher().current_state() == "content"
    assert set(screen._topic_cards) == {key for key, _, _ in HELP_TOPICS}
