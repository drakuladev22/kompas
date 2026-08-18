"""Dəstək gələnlər qutusunun EKRAN davranışı (tg1.md Faza 6).

──────────────────────────────────────────────────────────────────────────────
NƏYİ QORUYUR
──────────────────────────────────────────────────────────────────────────────
Domen tərəfi `test_support_channels.py`-dədir; burada YALNIZ ekranın öz
qərarları ölçülür və hər biri spesifikasiyanın açıq bəndidir:

    1. Süzgəclər BİR-BİRİNİ ƏVƏZ ETMİR — hamısı tək sözlükdə çıxır;
    2. Status zolağı saylarla göstərilir və defolt seçim `🔴 Açıq`-dir;
    3. «Filtrləri Təmizlə» HAMISINI sıfırlayır;
    4. Cari statusun öz düyməsi gizlənir (basılsa heç nə etməzdi);
    5. Bağlı söhbətdə yazı sahəsi bağlıdır — cavab sükutla itməməlidir;
    6. Telegram göstəricisi YALNIZ texniki bölmədə görünür;
    7. Yüklənməmiş şəkil GİZLƏDİLMİR, yalnız kliki söndürülür.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.domain.value_objects.support import SupportChannel, SupportTicketStatus
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _screen(theme: Any, channel: SupportChannel = SupportChannel.TECHNICAL) -> Any:
    from src.presentation.screens.support_inbox import SupportInboxScreen

    return SupportInboxScreen(theme, channel=channel)


def _thread(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ticket_id": "11111111-1111-1111-1111-111111111111",
        "subject": "Kiosk açılmır",
        "sender_name": "Murad Bayramov",
        "sender_position": "Mağaza Meneceri",
        "store_name": "Yataş Babək",
        "status": SupportTicketStatus.OPEN.value,
        "is_urgent": False,
        "messages": [],
    }
    payload.update(overrides)
    return payload


@requires_qt
def test_the_default_status_filter_is_open(theme: Any) -> None:
    """tg1.md: «Defolt seçim: 🔴 Açıq» — panel açılanda «mənim işim» görünür."""
    screen = _screen(theme)

    assert screen.filters()["status"] == SupportTicketStatus.OPEN.value


@requires_qt
def test_every_filter_travels_in_one_dictionary(theme: Any) -> None:
    """Süzgəclər ÜST-ÜSTƏ düşür — hamısı eyni sözlükdə çıxmalıdır."""
    screen = _screen(theme)

    keys = set(screen.filters())

    assert keys == {
        "status",
        "store_ids",
        "position_codes",
        "range",
        "custom_from",
        "custom_to",
        "unread_only",
        "search",
        "newest_first",
    }


@requires_qt
def test_status_counts_are_rendered_on_the_bar(theme: Any) -> None:
    from src.presentation.screens.support_inbox import STATUS_ALL

    screen = _screen(theme)
    screen.set_status_counts(
        {
            SupportTicketStatus.OPEN: 12,
            SupportTicketStatus.WAITING: 3,
            SupportTicketStatus.RESOLVED: 0,
            SupportTicketStatus.CLOSED: 41,
        }
    )

    labels = {key: button.text() for key, button in screen._status_buttons.items()}
    assert "(12)" in labels[SupportTicketStatus.OPEN.value]
    assert "(41)" in labels[SupportTicketStatus.CLOSED.value]
    # «Hamısı» bəndində say GÖSTƏRİLMİR — o, cəm olardı və müqayisəyə
    # kömək etməzdi (bax `set_status_counts` şərhi).
    assert "(" not in labels[STATUS_ALL]


@requires_qt
def test_clearing_the_filters_resets_every_control(theme: Any) -> None:
    from src.presentation.screens.support_inbox import RANGE_ALL, STATUS_ALL

    screen = _screen(theme)
    screen.set_stores([("s1", "Yataş Babək")])
    screen._search.setText("Murad")
    screen._unread_only.setChecked(True)
    screen._range_filter.setCurrentIndex(1)

    emitted: list[dict[str, Any]] = []
    screen.filters_changed.connect(emitted.append)
    screen.clear_filters()

    filters = screen.filters()
    assert filters["status"] == ""
    assert filters["search"] == ""
    assert filters["unread_only"] is False
    assert screen._range_filter.currentText() == RANGE_ALL
    assert screen._status_choice == STATUS_ALL
    # TƏK siqnal: hər kontrol ayrıca yaysaydı, «təmizlə» beş sorğu göndərərdi.
    assert len(emitted) == 1


@requires_qt
def test_active_filters_are_shown_as_chips(theme: Any) -> None:
    """Yığılmış açılan siyahıda seçim görünmür — «chip»-lər onu göstərir."""
    screen = _screen(theme)
    screen.set_stores([("s1", "Yataş Babək"), ("s2", "Yataş Mərkəzi")])
    screen._search.setText("kassa")
    screen._unread_only.setChecked(True)

    labels = screen.active_filter_labels()

    assert any("Açıq" in label for label in labels)
    assert "Yalnız oxunmamışlar" in labels
    assert any("kassa" in label for label in labels)


@requires_qt
def test_the_current_status_button_is_hidden(theme: Any) -> None:
    """«Bağlandı» söhbətdə `[Bağla]` düyməsi heç nə etməzdi."""
    screen = _screen(theme)
    screen.set_thread(_thread(status=SupportTicketStatus.CLOSED.value))

    # `isHidden()` — `isVisible()` DEYİL: ekran göstərilməyibsə Qt bütün
    # uşaqları «görünməyən» sayır və test həmişə keçərdi. `isHidden()` isə
    # yalnız AÇIQ `setVisible(False)` çağırışını əks etdirir.
    hidden = {status: button.isHidden() for status, button in screen._status_actions.items()}
    assert hidden[SupportTicketStatus.CLOSED] is True
    assert hidden[SupportTicketStatus.OPEN] is False


@requires_qt
def test_a_closed_thread_blocks_the_composer(theme: Any) -> None:
    """Bağlı söhbətə yazılan cavab Telegram-a getmir — sükutla itərdi."""
    screen = _screen(theme)

    screen.set_thread(_thread(status=SupportTicketStatus.CLOSED.value))
    assert screen._send.isEnabled() is False

    screen.set_thread(_thread(status=SupportTicketStatus.RESOLVED.value))
    assert screen._send.isEnabled() is True, "«Həll olundu» hələ AÇIQdır"


@requires_qt
def test_the_telegram_indicator_is_technical_only(theme: Any) -> None:
    from src.presentation.screens.support_inbox import TELEGRAM_PENDING

    message = {"body": "salam", "outgoing": False, "telegram_sent_at": ""}

    technical = _screen(theme, SupportChannel.TECHNICAL)
    assert technical._telegram_note(message) == TELEGRAM_PENDING

    internal = _screen(theme, SupportChannel.INTERNAL)
    # Daxili kanalda göstərici HƏMİŞƏ «göndərilmədi» olardı və istifadəçi
    # onu nasazlıq sanardı — halbuki bu, QAYDAdır.
    assert internal._telegram_note(message) == ""


@requires_qt
def test_a_pending_attachment_is_shown_but_not_clickable(theme: Any) -> None:
    """Yüklənməyi gözləyən şəkil GİZLƏDİLMİR — cavab verən onu bilməlidir."""
    screen = _screen(theme)
    screen.set_thread(
        _thread(
            messages=[
                {
                    "body": "Şəkil əlavə etdim",
                    "outgoing": False,
                    "attachment_name": "ekran.png",
                    "attachment_ref": "",
                }
            ]
        )
    )

    buttons = [
        screen._messages.itemAt(index).widget()
        for index in range(screen._messages.count())
        if screen._messages.itemAt(index).widget() is not None
    ]
    texts = [
        child.text()
        for widget in buttons
        for child in widget.findChildren(type(screen._send))
        if child.text()
    ]
    assert any("ekran.png" in text for text in texts)
    assert any("yüklənir" in text for text in texts)


@requires_qt
def test_a_stored_attachment_emits_the_request(theme: Any) -> None:
    screen = _screen(theme)
    screen.set_thread(
        _thread(
            messages=[
                {
                    "body": "Şəkil",
                    "outgoing": False,
                    "attachment_name": "ekran.png",
                    "attachment_ref": "GOOGLE_DRIVE:-:file-1",
                }
            ]
        )
    )
    seen: list[dict[str, Any]] = []
    screen.attachment_requested.connect(seen.append)

    for index in range(screen._messages.count()):
        widget = screen._messages.itemAt(index).widget()
        if widget is None:
            continue
        for child in widget.findChildren(type(screen._send)):
            if "ekran.png" in child.text():
                child.click()

    assert seen == [{"reference": "GOOGLE_DRIVE:-:file-1", "name": "ekran.png"}]


@requires_qt
def test_unread_rows_are_bold(theme: Any) -> None:
    """Gmail naxışı: oxunmamış QALIN, amma bu, STATUS DEYİL."""
    from PySide6.QtGui import QFont

    screen = _screen(theme)
    screen.set_threads([_thread(unread=True), _thread(unread=False)])

    rows = [
        screen._rows.itemAt(index).widget()
        for index in range(screen._rows.count())
        if screen._rows.itemAt(index).widget() is not None
    ]
    weights = [
        child.font().weight()
        for row in rows
        for child in row.findChildren(type(screen._sender))
        if "Murad" in child.text()
    ]
    assert QFont.Weight.DemiBold in weights
    assert QFont.Weight.Normal in weights


@requires_qt
def test_the_multi_select_summarises_its_choice(qt_app: Any) -> None:
    from PySide6.QtCore import Qt

    from src.presentation.widgets.multi_select import MultiSelectCombo

    combo = MultiSelectCombo("Bütün filiallar")
    combo.set_options([("a", "Yataş Babək"), ("b", "Yataş Mərkəzi")])
    line_edit = combo.lineEdit()
    assert line_edit is not None
    assert line_edit.text() == "Bütün filiallar"

    combo._model.item(0).setCheckState(Qt.CheckState.Checked)
    assert combo.selected_values() == ["a"]
    assert line_edit.text() == "Yataş Babək"

    combo._model.item(1).setCheckState(Qt.CheckState.Checked)
    assert line_edit.text() == "2 seçim"

    # Seçim siyahı YENİLƏNƏNDƏ də qalır — əks halda hər yeniləmə
    # istifadəçinin kəsimini silərdi.
    combo.set_options([("a", "Yataş Babək"), ("b", "Yataş Mərkəzi"), ("c", "Yeni")])
    assert set(combo.selected_values()) == {"a", "b"}


@requires_qt
def test_clearing_the_multi_select_emits_once(qt_app: Any) -> None:
    from PySide6.QtCore import Qt

    from src.presentation.widgets.multi_select import MultiSelectCombo

    combo = MultiSelectCombo("Bütün vəzifələr")
    combo.set_options([("a", "Satıcı"), ("b", "Menecer")])
    combo._model.item(0).setCheckState(Qt.CheckState.Checked)
    combo._model.item(1).setCheckState(Qt.CheckState.Checked)

    emitted: list[list[str]] = []
    combo.selection_changed.connect(emitted.append)
    combo.clear_selection()

    assert emitted == [[]]
    assert combo.selected_values() == []


@requires_qt
def test_the_custom_date_fields_appear_only_when_chosen(theme: Any) -> None:
    """İki tarix sahəsi həmişə görünsəydi, üç adi bənd onların arasında itərdi."""
    from src.presentation.screens.support_inbox import RANGE_CUSTOM

    screen = _screen(theme)
    assert screen._range_from.isHidden() is True

    screen._range_filter.setCurrentText(RANGE_CUSTOM)
    assert screen._range_from.isHidden() is False
    assert screen._range_to.isHidden() is False

    screen.clear_filters()
    assert screen._range_from.isHidden() is True


@requires_qt
def test_a_custom_range_includes_the_final_day(theme: Any) -> None:
    """«1-dən 5-ə» seçimi 5-ci gün yazılanı KƏNARDA QOYMAMALIDIR."""
    from src.presentation.controllers.support_inbox import _range_end, _range_start
    from src.presentation.screens.support_inbox import RANGE_CUSTOM

    start = _range_start(RANGE_CUSTOM, custom="2026-08-01")
    end = _range_end(RANGE_CUSTOM, custom="2026-08-05")

    assert start is not None
    assert end is not None
    assert start.day == 1
    assert (end.day, end.hour, end.minute) == (5, 23, 59)


@requires_qt
def test_a_broken_custom_date_is_ignored_not_crashed(theme: Any) -> None:
    from src.presentation.controllers.support_inbox import _range_start
    from src.presentation.screens.support_inbox import RANGE_CUSTOM

    assert _range_start(RANGE_CUSTOM, custom="tarix deyil") is None
