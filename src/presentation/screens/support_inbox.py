"""Dəstək gələnlər qutusu — BİR şablon, İKİ bölmə (CHAT-1 Faza 6).

──────────────────────────────────────────────────────────────────────────────
NİYƏ TƏK SİNİF
──────────────────────────────────────────────────────────────────────────────
«Daxili Müraciətlər» və «Texniki Dəstək» eyni işi görür: sol paneldə söhbət
siyahısı, sağda seçilmiş söhbət, aşağıda cavab sahəsi. Fərq YALNIZ iki
yerdədir — başlıq və Telegram sinxronluq göstəricisi. İki ayrı ekran
yazsaydıq, hər düzəliş (məs. status süzgəcinin davranışı) iki yerdə
təkrarlanmalı olardı və biri sükutla geridə qalardı.

Fərq KONSTRUKTOR ARQUMENTİdir (`channel`), miras deyil: alt-sinif yalnız iki
sətri dəyişmək üçün bütün quruluşu miras alardı və `isinstance` yoxlamaları
yaranardı.

──────────────────────────────────────────────────────────────────────────────
STATUS SÜZGƏCİ VƏ OXUNMAMIŞ — İKİ AYRI ANLAYIŞ
──────────────────────────────────────────────────────────────────────────────
Status «kim hərəkət etməlidir» sualına cavab verir və AÇIQ əməliyyatla
dəyişir. Oxunmamış isə yalnız görünüşdür (qalın şrift) və söhbət açılan kimi
itir — statusa TOXUNMUR. Ona görə «yalnız oxunmamışlar» ayrıca açardır,
status zolağının bəndi deyil: ikisini birləşdirmək «oxudum, deməli işlədim»
yanlışını qaydaya çevirərdi.

──────────────────────────────────────────────────────────────────────────────
SÜZGƏCLƏR ÜST-ÜSTƏ DÜŞÜR
──────────────────────────────────────────────────────────────────────────────
Beş süzgəc (status, filial, vəzifə, tarix, axtarış) + «yalnız oxunmamışlar»
BİRLİKDƏ tətbiq olunur və hər dəyişiklikdə TƏK siqnal yayılır
(`filters_changed`). Ayrı-ayrı siqnallar yaysaydıq, kontroller hansı
süzgəcin dəyişdiyini izləməli olardı — halbuki sorğu onsuz da hamısını
birlikdə istəyir.

──────────────────────────────────────────────────────────────────────────────
EKRAN MƏLUMAT OXUMUR
──────────────────────────────────────────────────────────────────────────────
Bütün sətirlər setter API-si ilə gəlir (`set_threads`, `set_thread`,
`set_status_counts`) və hər əməliyyat SİQNAL yayır. Kontroller sessiyanı
açır, use case-i çağırır və nəticəni geri verir — ekran nə repository, nə də
sessiya tanıyır.

──────────────────────────────────────────────────────────────────────────────
TELEGRAM GÖSTƏRİCİSİ NİYƏ MESAJIN ALTINDADIR
──────────────────────────────────────────────────────────────────────────────
Faza 6: «bu mesaj Telegram-a getdi/getmədi». Göstərici SÖHBƏTİN başlığında
olsaydı, bir mesajın getdiyi, digərinin getmədiyi hal (internet kəsilib
qayıdıb) ifadə oluna bilməzdi — halbuki məhz o hal izah tələb edir.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.domain.value_objects.support import SupportChannel, SupportTicketStatus
from src.presentation.screens.base import Screen
from src.presentation.screens.group_e import ChatBubble
from src.presentation.theme.manager import refresh_widget_style
from src.presentation.widgets import metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.multi_select import MultiSelectCombo
from src.presentation.widgets.primitives import (
    Card,
    Chip,
    Divider,
    body_label,
    muted_label,
    plain_label,
    section_label,
    stretch,
    title_label,
)

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager

#: Status zolağındakı «Hamısı» bəndinin açarı — status DEYİL, ona görə
#: `SupportTicketStatus`-a əlavə edilmir (o, DB dəyərlərinin güzgüsüdür).
STATUS_ALL: Final = "ALL"

#: Filial/vəzifə süzgəclərinin boş vəziyyət mətni.
ALL_STORES: Final = "Bütün filiallar"
ALL_POSITIONS: Final = "Bütün vəzifələr"

#: Tarix aralığı bəndləri — dəyər kontrollerə SÖZ kimi gedir və orada
#: tarixə çevrilir (ekran `Clock` portunu tanımır — CLAUDE.md §4: domen
#: kodunun `datetime.now()` çağırmaması qaydasının təqdimat tərəfi).
RANGE_ALL: Final = "Bütün vaxtlar"
RANGE_TODAY: Final = "Bu gün"
RANGE_WEEK: Final = "Bu həftə"
RANGE_MONTH: Final = "Bu ay"
#: «Xüsusi aralıq» — İKİ tarix sahəsi YALNIZ bu seçimdə görünür.
#:
#: Həmişə göstərsəydik, süzgəc zolağı iki əlavə elementlə dolar və ən çox
#: işlənən üç bənd («bu gün/həftə/ay») onların arasında itərdi.
RANGE_CUSTOM: Final = "Xüsusi aralıq"

SORT_NEWEST: Final = "Ən yeni əvvəl"
SORT_OLDEST: Final = "Ən köhnə əvvəl"

EMPTY_LIST_MESSAGE: Final = "Bu süzgəcə uyğun müraciət yoxdur."
EMPTY_THREAD_MESSAGE: Final = "Sol paneldən söhbət seçin."

#: Böyüdülmüş şəklin maksimum kənarı — 1280×800 minimum ekranda sığır.
ATTACHMENT_PREVIEW_MAX: Final = 900

#: Telegram sinxronluq mətnləri (yalnız texniki bölmədə).
TELEGRAM_SENT: Final = "Telegram: göndərildi"
TELEGRAM_PENDING: Final = "Telegram: göndərilmədi"
TELEGRAM_INBOUND: Final = "Telegram-dan cavab"

#: Status düymələrinin sırası — soldan sağa iş axını ilə eynidir.
_STATUS_ACTIONS: Final[tuple[tuple[SupportTicketStatus, str], ...]] = (
    (SupportTicketStatus.WAITING, "Gözləmədəyə Keç"),
    (SupportTicketStatus.RESOLVED, "Həll Olundu"),
    (SupportTicketStatus.CLOSED, "Bağla"),
    (SupportTicketStatus.OPEN, "Yenidən Aç"),
)


class SupportInboxScreen(Screen):
    """Dəstək söhbətlərinin idarə ekranı.

    Signals:
        thread_selected: Seçilmiş müraciətin ID-si (mətn).
        reply_requested: `dict` (`ticket_id`, `body`).
        status_change_requested: `dict` (`ticket_id`, `status`).
        filters_changed: `dict` — bütün süzgəclər BİRLİKDƏ.
        refresh_requested: Siyahını təzədən oxu.
    """

    thread_selected = Signal(str)
    reply_requested = Signal(dict)
    status_change_requested = Signal(dict)
    filters_changed = Signal(dict)
    refresh_requested = Signal()
    #: Şəklə klik — `dict` (`reference`, `name`).
    #:
    #: EKRAN FAYLI ÖZÜ ÇƏKMİR: Drive-dan endirmə şəbəkə əməliyyatıdır və GUI
    #: sapını dondurardı. Ekran yalnız istəyi yayır; kontroller onu fon
    #: sapında icra edib `show_attachment()` ilə geri verir.
    attachment_requested = Signal(dict)

    def __init__(
        self,
        theme: ThemeManager,
        *,
        channel: SupportChannel = SupportChannel.TECHNICAL,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(theme, parent=parent)
        self._channel = channel
        self._selected_id = ""
        self._thread_status = SupportTicketStatus.OPEN
        # DEFOLT `🔴 Açıq` (tg1.md): panel açılanda «mənim işim» görünməlidir.
        self._status_choice: str = SupportTicketStatus.OPEN.value
        self._status_buttons: dict[str, QPushButton] = {}
        self._counts: dict[SupportTicketStatus, int] = dict.fromkeys(SupportTicketStatus, 0)

        # ────────────────────────────────────────────────────────────────
        # LAYOUT BAZADAN GƏLİR — İKİNCİSİNİ QURMAQ EKRANI BOŞALDIR (LAYOUT-1)
        # ────────────────────────────────────────────────────────────────
        # `Screen.__init__` `self` üzərində ARTIQ `QVBoxLayout` qurur. İkinci
        # `QVBoxLayout(self)` Qt tərəfindən QURULMUR — konsola «which already
        # has a layout» xəbərdarlığı yazılır və həmin layout-a əlavə edilən
        # BÜTÜN vidjetlər valideynsiz qalır. Nəticə: ekran istisnasız qurulur,
        # lakin TAM BOŞ görünür — yəni ən pis nasazlıq növü, çünki nə log, nə
        # də xəta mesajı var.
        #
        # `body()` bazanın məzmun layout-udur; kənar boşluğu da baza verir
        # (`CONTENT_PADDING_H/V`), ona görə burada ayrıca margin TƏYİN
        # EDİLMİR — əks halda bu ekran qalan 38 ekrandan fərqli doldurma ilə
        # görünərdi.
        layout = self.body()

        header = QHBoxLayout()
        header.addWidget(title_label(channel.section_title_az))
        header.addWidget(stretch())
        refresh = secondary_button("Yenilə")
        refresh.clicked.connect(self.refresh_requested)
        header.addWidget(refresh)
        layout.addLayout(header)

        layout.addWidget(self._build_filter_card())

        split = QHBoxLayout()
        split.setSpacing(metrics.CARD_SPACING)
        split.addWidget(self._build_list_panel())
        split.addWidget(self._build_thread_panel(), 1)
        layout.addLayout(split, 1)

        self._message = muted_label("")
        self._message.setWordWrap(True)
        self._message.setVisible(False)
        layout.addWidget(self._message)

    # ------------------------------- süzgəclər ------------------------------- #

    def _build_filter_card(self) -> Card:
        """Status zolağı + kombinə süzgəclər + aktiv «chip»-lər."""
        card = Card(padding=16, spacing=metrics.CARD_CONTENT_SPACING)

        status_row = QWidget()
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)
        for key, label in self._status_choices():
            button = secondary_button(label)
            # SEÇİLMİŞ SEGMENT NAXIŞI (`qss.py`: `[variant="secondary"]
            # [active="true"]`) — Ayarlar → Görünüş zolağı ilə EYNİ. Öz
            # `:checked` qaydamızı yazsaydıq, eyni məna iki fərqli görünüşlə
            # ifadə olunar və kontrast qapısına yeni rəng cütü əlavə olardı.
            button.setProperty("active", "false")
            button.clicked.connect(lambda _=False, value=key: self._on_status_filter(value))
            status_layout.addWidget(button)
            self._status_buttons[key] = button
        status_layout.addWidget(stretch())
        card.add(status_row)

        controls = QWidget()
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(8)

        self._store_filter = MultiSelectCombo(ALL_STORES)
        self._store_filter.selection_changed.connect(lambda _: self._emit_filters())
        controls_layout.addWidget(self._store_filter)

        self._position_filter = MultiSelectCombo(ALL_POSITIONS)
        self._position_filter.selection_changed.connect(lambda _: self._emit_filters())
        controls_layout.addWidget(self._position_filter)

        self._range_filter = QComboBox()
        self._range_filter.addItems([RANGE_ALL, RANGE_TODAY, RANGE_WEEK, RANGE_MONTH, RANGE_CUSTOM])
        self._range_filter.currentIndexChanged.connect(lambda _: self._on_range_changed())
        controls_layout.addWidget(self._range_filter)

        self._range_from = QDateEdit()
        self._range_from.setCalendarPopup(True)
        self._range_from.setDisplayFormat("dd.MM.yyyy")
        self._range_from.setVisible(False)
        self._range_from.dateChanged.connect(lambda _: self._emit_filters())
        controls_layout.addWidget(self._range_from)

        self._range_to = QDateEdit()
        self._range_to.setCalendarPopup(True)
        self._range_to.setDisplayFormat("dd.MM.yyyy")
        self._range_to.setVisible(False)
        self._range_to.dateChanged.connect(lambda _: self._emit_filters())
        controls_layout.addWidget(self._range_to)

        self._sort = QComboBox()
        self._sort.addItems([SORT_NEWEST, SORT_OLDEST])
        self._sort.currentIndexChanged.connect(lambda _: self._emit_filters())
        controls_layout.addWidget(self._sort)

        self._unread_only = QCheckBox("Yalnız oxunmamışlar")
        self._unread_only.toggled.connect(lambda _: self._emit_filters())
        controls_layout.addWidget(self._unread_only)

        self._search = QLineEdit()
        self._search.setPlaceholderText("İşçi adı və ya mesaj mətni…")
        self._search.setProperty("variant", "form")
        # `returnPressed` — HƏR HƏRFDƏ sorğu göndərmirik: axtarış mesaj
        # mətninə də baxır və hər simvolda tam skan israfdır.
        self._search.returnPressed.connect(self._emit_filters)
        controls_layout.addWidget(self._search, 1)
        card.add(controls)

        chips_row = QWidget()
        chips_layout = QHBoxLayout(chips_row)
        chips_layout.setContentsMargins(0, 0, 0, 0)
        chips_layout.setSpacing(8)
        self._chips = chips_layout
        chips_layout.addStretch(1)
        self._clear_button = secondary_button("Filtrləri Təmizlə")
        self._clear_button.clicked.connect(self.clear_filters)
        chips_layout.addWidget(self._clear_button)
        card.add(chips_row)

        self._sync_status_buttons()
        return card

    def _status_choices(self) -> tuple[tuple[str, str], ...]:
        return (
            (STATUS_ALL, "Hamısı"),
            *((status.value, f"{status.dot} {status.label_az}") for status in SupportTicketStatus),
        )

    # ------------------------------- quruluş --------------------------------- #

    def _build_list_panel(self) -> QWidget:
        card = Card()
        card.setFixedWidth(metrics.SUPPORT_INBOX_LIST_WIDTH)
        body = card.body()
        body.setSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        host = QWidget()
        self._rows = QVBoxLayout(host)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(8)
        self._rows.addStretch(1)
        scroll.setWidget(host)
        body.addWidget(scroll, 1)

        self._list_empty = muted_label(EMPTY_LIST_MESSAGE)
        self._list_empty.setWordWrap(True)
        body.addWidget(self._list_empty)
        return card

    def _build_thread_panel(self) -> QWidget:
        card = Card()
        body = card.body()
        body.setSpacing(12)

        head = QHBoxLayout()
        self._subject = section_label("")
        head.addWidget(self._subject)
        head.addWidget(stretch())
        self._status_chip = Chip("", tone="info")
        self._status_chip.setVisible(False)
        head.addWidget(self._status_chip)
        body.addLayout(head)

        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)
        actions_layout.addWidget(stretch())
        self._status_actions: dict[SupportTicketStatus, QPushButton] = {}
        for status, label in _STATUS_ACTIONS:
            button = secondary_button(label)
            button.clicked.connect(lambda _=False, value=status: self._on_status_action(value))
            button.setVisible(False)
            actions_layout.addWidget(button)
            self._status_actions[status] = button
        body.addWidget(actions)

        self._sender = muted_label("")
        body.addWidget(self._sender)
        body.addWidget(Divider())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        host = QWidget()
        self._messages = QVBoxLayout(host)
        self._messages.setContentsMargins(4, 4, 4, 4)
        self._messages.setSpacing(12)
        self._messages.addStretch(1)
        scroll.setWidget(host)
        body.addWidget(scroll, 1)

        self._thread_empty = muted_label(EMPTY_THREAD_MESSAGE)
        body.addWidget(self._thread_empty)

        composer = QHBoxLayout()
        self._reply = QLineEdit()
        self._reply.setPlaceholderText("Cavab yazın…")
        self._reply.setProperty("variant", "form")
        self._reply.setMinimumHeight(40)
        self._reply.returnPressed.connect(self._on_reply)
        composer.addWidget(self._reply, 1)
        self._send = action_button("Göndər")
        self._send.clicked.connect(self._on_reply)
        composer.addWidget(self._send)
        body.addLayout(composer)
        self._set_composer_enabled(False)
        return card

    # ------------------------------ setter API ------------------------------- #

    def set_stores(self, stores: list[tuple[str, str]]) -> None:
        """`(store_id, ad)` cütləri — filial süzgəci üçün."""
        self._store_filter.set_options(stores)

    def set_positions(self, positions: list[tuple[str, str]]) -> None:
        """`(code, ad)` cütləri — vəzifə süzgəci üçün."""
        self._position_filter.set_options(positions)

    def set_status_counts(self, counts: dict[SupportTicketStatus, int]) -> None:
        """Status zolağındakı saylar.

        `Hamısı` bəndində say GÖSTƏRİLMİR: o, cəmi olardı və istifadəçiyə
        heç bir qərar verdirmir — zolağın məqsədi «hansında neçə iş var»
        müqayisəsidir.
        """
        self._counts = dict(counts)
        self._sync_status_buttons()

    def set_threads(self, threads: list[dict[str, Any]]) -> None:
        """Sol paneldəki söhbət siyahısı."""
        clear_layout(self._rows, keep_last=1)
        for thread in threads:
            self._rows.insertWidget(self._rows.count() - 1, self._build_row(thread))
        self._list_empty.setVisible(not threads)

    def set_thread(self, thread: dict[str, Any] | None) -> None:
        """Sağ paneldəki söhbət. `None` → boş vəziyyət."""
        clear_layout(self._messages, keep_last=1)
        if thread is None:
            self._selected_id = ""
            self._subject.setText("")
            self._sender.setText("")
            self._status_chip.setVisible(False)
            for button in self._status_actions.values():
                button.setVisible(False)
            self._thread_empty.setVisible(True)
            self._set_composer_enabled(False)
            return

        self._selected_id = str(thread.get("ticket_id", ""))
        self._thread_status = SupportTicketStatus.parse(str(thread.get("status", "OPEN")))
        self._subject.setText(str(thread.get("subject", "")))
        self._sender.setText(self._sender_line(thread))
        self._status_chip.setText(f"{self._thread_status.dot} {self._thread_status.label_az}")
        self._status_chip.setVisible(True)
        self._sync_status_actions()
        self._thread_empty.setVisible(False)

        for message in thread.get("messages") or []:
            self._append_message(message)
        # BAĞLI SÖHBƏTƏ CAVAB YAZILMIR: əvvəlcə «Yenidən Aç» basılmalıdır.
        # Yazı sahəsini açıq saxlasaydıq, cavab bağlı söhbətə düşər və
        # Telegram-a getməzdi (Faza 7.2) — yəni mesaj sükutla itərdi.
        self._set_composer_enabled(self._thread_status.is_open)

    def set_message(self, text: str, *, error: bool = False) -> None:
        """Ekranın altındakı sistem sətri."""
        self._message.setText(text)
        self._message.setVisible(bool(text))
        colour = "--color-danger" if error else "--color-text-muted"
        self._message.setStyleSheet(f"color: {self._theme.color(colour)};")

    # -------------------------------- oxuma ---------------------------------- #

    def selected_ticket_id(self) -> str:
        return self._selected_id

    def filters(self) -> dict[str, Any]:
        """Bütün süzgəclər BİR sözlükdə — kontroller onları birlikdə ötürür."""
        return {
            "status": "" if self._status_choice == STATUS_ALL else self._status_choice,
            "store_ids": self._store_filter.selected_values(),
            "position_codes": self._position_filter.selected_values(),
            "range": self._range_filter.currentText(),
            # Tarixlər ISO SƏTİRDİR, `QDate` deyil: kontroller Qt tiplərini
            # tanımamalıdır — o, tətbiq qatına `datetime` ötürür və Qt-dən
            # asılı olsaydı, sınaqda pəncərəsiz işləyə bilməzdi.
            "custom_from": self._range_from.date().toString("yyyy-MM-dd"),
            "custom_to": self._range_to.date().toString("yyyy-MM-dd"),
            "unread_only": self._unread_only.isChecked(),
            "search": self._search.text().strip(),
            "newest_first": self._sort.currentText() == SORT_NEWEST,
        }

    def active_filter_labels(self) -> list[str]:
        """Aktiv süzgəclərin «chip» mətnləri — testlər və ekran üçün."""
        labels: list[str] = []
        if self._status_choice != STATUS_ALL:
            status = SupportTicketStatus.parse(self._status_choice)
            labels.append(f"{status.dot} {status.label_az}")
        stores = self._store_filter.selected_values()
        if stores:
            labels.append(f"{len(stores)} filial")
        positions = self._position_filter.selected_values()
        if positions:
            labels.append(f"{len(positions)} vəzifə")
        if self._range_filter.currentText() != RANGE_ALL:
            labels.append(self._range_filter.currentText())
        if self._unread_only.isChecked():
            labels.append("Yalnız oxunmamışlar")
        if self._search.text().strip():
            labels.append(f"«{self._search.text().strip()}»")
        return labels

    @property
    def channel(self) -> SupportChannel:
        return self._channel

    # ------------------------------ əməliyyat -------------------------------- #

    def clear_filters(self) -> None:
        """`[Filtrləri Təmizlə]` — HAMISI sıfırlanır, TƏK sorğu göndərilir.

        Status da sıfırlanır («Hamısı»): istifadəçi «təmizlə» deyəndə
        defolt seçimin qalmasını gözləmir — o, hər şeyi görmək istəyir.
        """
        self._status_choice = STATUS_ALL
        for combo in (self._store_filter, self._position_filter):
            combo.blockSignals(True)
            combo.clear_selection()
            combo.blockSignals(False)
        self._range_filter.blockSignals(True)
        self._range_filter.setCurrentIndex(0)
        self._range_filter.blockSignals(False)
        self._range_from.setVisible(False)
        self._range_to.setVisible(False)
        self._sort.blockSignals(True)
        self._sort.setCurrentIndex(0)
        self._sort.blockSignals(False)
        self._unread_only.blockSignals(True)
        self._unread_only.setChecked(False)
        self._unread_only.blockSignals(False)
        self._search.clear()
        self._sync_status_buttons()
        self._emit_filters()

    # ------------------------------- köməkçi --------------------------------- #

    def _build_row(self, thread: dict[str, Any]) -> QWidget:
        ticket_id = str(thread.get("ticket_id", ""))
        status = SupportTicketStatus.parse(str(thread.get("status", "OPEN")))
        unread = bool(thread.get("unread"))

        row = secondary_button("")
        row.setMinimumHeight(metrics.SUPPORT_ROW_HEIGHT)
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        inner = QVBoxLayout(row)
        inner.setContentsMargins(12, 8, 12, 8)
        inner.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(muted_label(status.dot))
        name = body_label(str(thread.get("sender_name") or "—"), size=12, wrap=False)
        if unread:
            # OXUNMAMIŞ = QALIN ŞRİFT (Gmail naxışı, tg1.md): status DEYİL,
            # yalnız görünüş. Ayrıca nişan qoysaydıq, sətirdə iki fərqli
            # dairə (status nöqtəsi + oxunmamış nöqtəsi) olardı və oxucu
            # onları qarışdırardı.
            font = name.font()
            font.setWeight(QFont.Weight.DemiBold)
            name.setFont(font)
        top.addWidget(name)
        if thread.get("is_urgent"):
            top.addWidget(Chip("Təcili", tone="danger"))
        top.addWidget(stretch())
        top.addWidget(muted_label(str(thread.get("time") or "")))
        inner.addLayout(top)

        inner.addWidget(muted_label(self._sender_line(thread)))
        preview = muted_label(str(thread.get("preview") or ""))
        preview.setWordWrap(False)
        inner.addWidget(preview)

        row.clicked.connect(lambda _=False, key=ticket_id: self._on_row_clicked(key))
        return row

    def _sender_line(self, thread: dict[str, Any]) -> str:
        """«Mağaza · Vəzifə» — boş hissələr TAM ÇIXARILIR.

        «— · —» sətri məlumat vermir; silinmiş mağaza/işçi halında sətir
        sadəcə qısalır.
        """
        parts = [
            str(thread.get("store_name") or "").strip(),
            str(thread.get("sender_position") or "").strip(),
        ]
        return " · ".join(part for part in parts if part)

    def _append_message(self, message: dict[str, Any]) -> None:
        outgoing = bool(message.get("outgoing"))
        bubble = ChatBubble(str(message.get("body", "")), self._theme, outgoing=outgoing)
        self._messages.insertWidget(self._messages.count() - 1, bubble)
        self._append_attachment(message, outgoing=outgoing)
        note = self._telegram_note(message)
        if note:
            label = muted_label(note)
            label.setAlignment(
                Qt.AlignmentFlag.AlignRight if outgoing else Qt.AlignmentFlag.AlignLeft
            )
            self._messages.insertWidget(self._messages.count() - 1, label)

    def _append_attachment(self, message: dict[str, Any], *, outgoing: bool) -> None:
        """Şəkil əlavəsi — klik edilə bilən sətir.

        ──────────────────────────────────────────────────────────────────────
        YÜKLƏNMƏMİŞ ŞƏKİL GİZLƏDİLMİR
        ──────────────────────────────────────────────────────────────────────
        `attachment_ref` boşdursa fayl hələ lokal növbədədir (internet
        yoxdur). Sətri gizlətsəydik, cavab verən adam işçinin şəkil
        göndərdiyini BİLMƏZDİ və «şəkil göndər» deyə təkrar soruşardı.
        Ona görə ad göstərilir, klik isə söndürülür.
        """
        name = str(message.get("attachment_name") or "")
        if not name:
            return
        reference = str(message.get("attachment_ref") or "")
        button = secondary_button(f"📎 {name}" if reference else f"📎 {name} (yüklənir…)")
        button.setEnabled(bool(reference))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if reference:
            button.clicked.connect(
                lambda _=False, ref=reference, label=name: self.attachment_requested.emit(
                    {"reference": ref, "name": label}
                )
            )
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        if outgoing:
            row_layout.addWidget(stretch())
        row_layout.addWidget(button)
        if not outgoing:
            row_layout.addWidget(stretch())
        self._messages.insertWidget(self._messages.count() - 1, row)

    def show_attachment(self, name: str, content: bytes) -> None:
        """Şəkli tam ölçüdə açır (Faza 6: «klik → böyüt»).

        DİALOQ EKRANIN ÖZÜNDƏ QURULUR, ayrıca fayl yazılmır: şəkil yalnız
        baxış üçündür və diskə yazmaq həm icazə problemi (Program Files
        yazıla bilmir), həm də təmizlənməyən müvəqqəti fayl yaradardı.
        """
        pixmap = QPixmap()
        if not pixmap.loadFromData(content):
            self.set_message("Şəkil açıla bilmədi — fayl zədəli ola bilər.", error=True)
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(name)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        label = plain_label()
        # Böyük şəkil ekrandan TAŞMIR: 900px eni 1280×800 minimum ekranda
        # kənarlarla birlikdə sığır (`metrics` sabitləri pəncərə ölçüsündən
        # gəlir, bu isə dialoq həddidir).
        label.setPixmap(
            pixmap.scaled(
                ATTACHMENT_PREVIEW_MAX,
                ATTACHMENT_PREVIEW_MAX,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        layout.addWidget(label)
        close = secondary_button("Bağla")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def _telegram_note(self, message: dict[str, Any]) -> str:
        """Sinxronluq sətri — YALNIZ Telegram-a çıxan kanalda.

        Daxili kanalda bu sətir HƏMİŞƏ «göndərilmədi» olardı və istifadəçi
        onu nasazlıq sanardı; halbuki daxili müraciətin Telegram-a getməməsi
        QAYDAdır (`SupportChannel.notifies_telegram`).
        """
        if not self._channel.notifies_telegram:
            return ""
        if message.get("from_telegram"):
            return TELEGRAM_INBOUND
        sent_at = str(message.get("telegram_sent_at") or "")
        return f"{TELEGRAM_SENT} {sent_at}".strip() if sent_at else TELEGRAM_PENDING

    def _sync_status_buttons(self) -> None:
        for key, button in self._status_buttons.items():
            selected = key == self._status_choice
            button.setProperty("active", "true" if selected else "false")
            refresh_widget_style(button)
            label = dict(self._status_choices())[key]
            if key != STATUS_ALL:
                count = self._counts.get(SupportTicketStatus.parse(key), 0)
                label = f"{label} ({count})"
            button.setText(label)

    def _sync_status_actions(self) -> None:
        """Cari statusun ÖZ düyməsi gizlədilir.

        «Bağlandı» söhbətdə `[Bağla]` düyməsini göstərmək istifadəçiyə heç
        nə etməyən bir düymə verərdi — və o, basıb nəticə gözləyərdi.
        """
        for status, button in self._status_actions.items():
            button.setVisible(status is not self._thread_status)

    def _set_composer_enabled(self, enabled: bool) -> None:
        self._reply.setEnabled(enabled)
        self._send.setEnabled(enabled)

    def _on_row_clicked(self, ticket_id: str) -> None:
        self._selected_id = ticket_id
        self.thread_selected.emit(ticket_id)

    def _on_reply(self) -> None:
        text = self._reply.text().strip()
        if not text or not self._selected_id:
            return
        self._reply.clear()
        self.reply_requested.emit({"ticket_id": self._selected_id, "body": text})

    def _on_status_action(self, status: SupportTicketStatus) -> None:
        if not self._selected_id:
            return
        self.status_change_requested.emit({"ticket_id": self._selected_id, "status": status.value})

    def _on_status_filter(self, value: str) -> None:
        self._status_choice = value
        self._sync_status_buttons()
        self._emit_filters()

    def _on_range_changed(self) -> None:
        """«Xüsusi aralıq» seçiləndə iki tarix sahəsi açılır."""
        custom = self._range_filter.currentText() == RANGE_CUSTOM
        self._range_from.setVisible(custom)
        self._range_to.setVisible(custom)
        self._emit_filters()

    def _emit_filters(self) -> None:
        self._refresh_chips()
        self.filters_changed.emit(self.filters())

    def _refresh_chips(self) -> None:
        """Aktiv süzgəclər zolağın üstündə görünür.

        Süzgəclərin özləri açılan siyahılardır və YIĞILMIŞ vəziyyətdə nə
        seçildiyi görünmür. «Chip»-lər olmasaydı, istifadəçi boş siyahıya
        baxıb məlumatın itdiyini düşünərdi.
        """
        while self._chips.count() > 2:  # noqa: PLR2004 — stretch + təmizlə düyməsi
            item = self._chips.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        labels = self.active_filter_labels()
        for index, label in enumerate(labels):
            self._chips.insertWidget(index, Chip(label, tone="info"))
        self._clear_button.setEnabled(bool(labels))


__all__ = [
    "ALL_POSITIONS",
    "ALL_STORES",
    "EMPTY_LIST_MESSAGE",
    "EMPTY_THREAD_MESSAGE",
    "RANGE_ALL",
    "RANGE_CUSTOM",
    "RANGE_MONTH",
    "RANGE_TODAY",
    "RANGE_WEEK",
    "SORT_NEWEST",
    "SORT_OLDEST",
    "STATUS_ALL",
    "TELEGRAM_INBOUND",
    "TELEGRAM_PENDING",
    "TELEGRAM_SENT",
    "SupportInboxScreen",
]
