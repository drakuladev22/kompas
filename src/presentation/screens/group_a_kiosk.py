"""Qrup A — kiosk ekranları: PIN klaviaturası və İşçi Ana Ekranı — Faza 4.2.

Maket: "KompasOS - Qrup A.dc.html", ekranlar 04–05.

Bu iki ekran mağazadakı PAYLAŞILAN kiosk PC-sində işləyir: tam ekran,
çərçivəsiz, toxunma-ilk. Ona görə:

    * düymələr böyükdür (88px — bölmə 9-un 44px minimumundan xeyli yuxarı),
    * PIN ekranı ümumi palitradan DEYİL, AAA kontrastlı `--color-pin-*`
      cütündən istifadə edir (mağaza işığı dəyişkəndir, tez-tez günəş altında),
    * heç bir naviqasiya yoxdur — işçi yalnız öz axınını görür.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.presentation.widgets import metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import (
    Card,
    Divider,
    body_label,
    mono_label,
    muted_label,
    stretch,
    title_label,
)
from src.presentation.widgets.worker_status import WorkerStatus

if TYPE_CHECKING:
    from PySide6.QtGui import QPaintEvent

    from src.presentation.theme.manager import ThemeManager

#: PIN uzunluğu (bölmə 9 — 4 rəqəm).
PIN_LENGTH: Final = 4
#: Maketdəki xəbərdarlıq: 3 səhv cəhddən sonra 5 dəqiqə blok.
MAX_ATTEMPTS: Final = 3
LOCKOUT_MINUTES: Final = 5


# --------------------------------------------------------------------------- #
# 04 — PIN Klaviaturası
# --------------------------------------------------------------------------- #


class PinDots(QWidget):
    """Doldurulmuş/boş dairə göstəriciləri — neçə rəqəm daxil edilib.

    Rəqəmin özü GÖSTƏRİLMİR: kiosk mağaza zalındadır və arxadan baxan bir
    nəfər PIN-i oxuya bilərdi.
    """

    def __init__(
        self,
        *,
        color: str,
        length: int = PIN_LENGTH,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._length = length
        self._filled = 0
        self._error = False
        self.setFixedSize(
            length * metrics.PIN_DOT_SIZE + (length - 1) * 22,
            metrics.PIN_DOT_SIZE,
        )

    def set_filled(self, count: int) -> None:
        self._filled = max(0, min(self._length, count))
        self.update()

    def set_error(self, error: bool) -> None:
        self._error = error
        self.update()

    def set_colors(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt adlandırması
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        size = metrics.PIN_DOT_SIZE
        for index in range(self._length):
            x = index * (size + 22)
            rect = (x, 0, size, size)
            if index < self._filled:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self._color)
            else:
                pen = painter.pen()
                pen.setColor(self._color)
                pen.setWidth(2)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(*rect)


class PinPadScreen(QWidget):
    """Tam ekran PIN girişi.

    Signals:
        submitted: 4 rəqəm tamamlandı (`str`).
    """

    submitted = Signal(str)

    #: Klaviatura düzülüşü — maketdəki 3×4 şəbəkə.
    _LAYOUT: Final = (
        ("1", "2", "3"),
        ("4", "5", "6"),
        ("7", "8", "9"),
        ("Təmizlə", "0", "Sil"),
    )

    def __init__(
        self,
        theme: ThemeManager,
        *,
        store_name: str,
        terminal_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._entered = ""
        self._locked = False

        self.setObjectName("PinScreen")
        text_color = theme.color("--color-pin-text")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 48, 0, 48)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # ------------------------------ başlıq ------------------------------ #
        header = QVBoxLayout()
        header.setSpacing(4)
        header.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        store = title_label(store_name, size=20)
        store.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(store)

        terminal = muted_label(terminal_name)
        terminal.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(terminal)

        self._clock = mono_label("", muted=True)
        self._clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self._clock)
        layout.addLayout(header)

        layout.addSpacing(46)

        prompt = QLabel("PIN kodunuzu daxil edin")
        prompt_font = prompt.font()
        prompt_font.setPixelSize(22)
        prompt_font.setWeight(QFont.Weight.DemiBold)
        prompt.setFont(prompt_font)
        prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(prompt, alignment=Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(26)

        self._dots = PinDots(color=text_color)
        layout.addWidget(self._dots, alignment=Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(14)

        # Xəta sətri HƏMİŞƏ yer tutur (görünməz olsa da) — əks halda mesaj
        # çıxanda bütün klaviatura aşağı sıçrayardı və barmaq səhv düyməyə
        # düşərdi.
        self._message = QLabel(" ")
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_font = self._message.font()
        message_font.setPixelSize(14)
        self._message.setFont(message_font)
        self._message.setFixedHeight(20)
        layout.addWidget(self._message, alignment=Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(26)
        layout.addWidget(self._build_keypad(), alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)

        footer = muted_label("Problem yaşayırsınızsa mağaza rəhbərinizə müraciət edin.")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(footer, alignment=Qt.AlignmentFlag.AlignHCenter)

    def _build_keypad(self) -> QWidget:
        keypad = QWidget()
        grid = QGridLayout(keypad)
        grid.setSpacing(metrics.KEYPAD_SPACING)

        for row_index, row in enumerate(self._LAYOUT):
            for column_index, key in enumerate(row):
                button = QPushButton(key)
                button.setProperty("variant", "keypad")
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                if key.isdigit():
                    button.setFixedSize(metrics.KEYPAD_BUTTON_SIZE, metrics.KEYPAD_BUTTON_SIZE)
                else:
                    # Mətn düymələri ("Təmizlə"/"Sil") rəqəmlərdən ENLİDİR —
                    # kvadrat ölçüdə etiket kəsilirdi ("əmizlə" görünürdü).
                    button.setFixedSize(
                        metrics.KEYPAD_TEXT_BUTTON_WIDTH, metrics.KEYPAD_BUTTON_SIZE
                    )
                    font = button.font()
                    font.setPixelSize(14)
                    button.setFont(font)
                button.clicked.connect(lambda _=False, value=key: self._on_key(value))
                grid.addWidget(button, row_index, column_index)

        return keypad

    # ------------------------------- giriş ----------------------------------- #

    def _on_key(self, key: str) -> None:
        if self._locked:
            return

        if key == "Təmizlə":
            self._entered = ""
        elif key == "Sil":
            self._entered = self._entered[:-1]
        elif key.isdigit() and len(self._entered) < PIN_LENGTH:
            self._entered += key
            self.clear_message()

        self._dots.set_filled(len(self._entered))

        if len(self._entered) == PIN_LENGTH:
            self.submitted.emit(self._entered)

    def set_clock(self, text: str) -> None:
        """Saat və tarix — "09:42 · 12 Avqust 2026"."""
        self._clock.setText(text)

    def reset(self) -> None:
        """Girişi təmizləyir (uğurlu təsdiqdən və ya xətadan sonra)."""
        self._entered = ""
        self._dots.set_filled(0)
        self._dots.set_error(False)

    def show_attempt_error(self, remaining: int) -> None:
        """Yanlış PIN — neçə cəhd qaldığını göstərir."""
        self._message.setText(f"PIN yanlışdır — {remaining} cəhd qaldı")
        self._message.setStyleSheet(f"color: {self._theme.color('--color-danger')};")
        self._dots.set_error(True)
        self.reset()

    def show_message(self, text: str) -> None:
        """Sərbəst xəbərdarlıq mətni (PIN yanlışdır, konfiqurasiya yoxdur, ...).

        `show_attempt_error`-dan fərqi: orada qalan cəhd sayı GÖSTƏRİLİR və
        bu, yalnız PIN səhvində mənalıdır. Sistem xətası halında "3 cəhd
        qaldı" yazmaq işçini yanıldardı — problem onun PIN-ində deyil.
        """
        self._message.setText(text)
        self._message.setStyleSheet(f"color: {self._theme.color('--color-danger')};")
        self._dots.set_error(True)
        self.reset()

    def show_lockout(self, minutes: int = LOCKOUT_MINUTES) -> None:
        """Terminal bloklandı — klaviatura söndürülür."""
        self._locked = True
        self._message.setText(
            f"Terminal {minutes} dəqiqə bloklandı. Mağaza rəhbərinizə müraciət edin."
        )
        self._message.setStyleSheet(f"color: {self._theme.color('--color-danger')};")
        self.reset()

    def clear_lockout(self) -> None:
        self._locked = False
        self.clear_message()

    def clear_message(self) -> None:
        self._message.setText(" ")
        self._message.setStyleSheet("")
        self._dots.set_error(False)

    @property
    def is_locked(self) -> bool:
        return self._locked


# --------------------------------------------------------------------------- #
# 05 — İşçi Ana Ekranı
# --------------------------------------------------------------------------- #


class EmployeeHomeScreen(QWidget):
    """PIN-dən sonra açılan işçi ekranı — status, tapşırıqlar, xal, cərimələr.

    Signals:
        action_requested: Statusa uyğun TƏK düymə basıldı (`WorkerStatus`).
        photo_change_requested: "Şəkli Dəyiş".
        logout_requested: "Çıxış".
        tasks_requested / rewards_requested / appeal_requested: kart keçidləri.
    """

    action_requested = Signal(object)
    photo_change_requested = Signal()
    logout_requested = Signal()
    tasks_requested = Signal()
    rewards_requested = Signal()
    appeal_requested = Signal()

    def __init__(
        self,
        theme: ThemeManager,
        *,
        full_name: str,
        position_name: str,
        store_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._status = WorkerStatus.VERIFIED
        self.setStyleSheet(f"background-color: {theme.color('--color-content-bg')};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(46, 34, 46, 34)
        layout.setSpacing(26)

        layout.addWidget(self._build_header(full_name, position_name, store_name))
        layout.addWidget(self._build_status_card())
        layout.addWidget(self._build_cards_row(), 1)

    # ------------------------------- başlıq ---------------------------------- #

    def _build_header(self, full_name: str, position_name: str, store_name: str) -> QWidget:
        from src.presentation.widgets.primitives import Avatar  # noqa: PLC0415

        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        self._avatar = Avatar(
            full_name,
            background=self._theme.color("--color-neutral-bg"),
            foreground=self._theme.color("--color-text-primary"),
            size=72,
        )
        layout.addWidget(self._avatar)

        text_box = QWidget()
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)

        greeting = title_label(f"Salam, {full_name}", size=26)
        text_layout.addWidget(greeting)
        text_layout.addWidget(muted_label(f"{position_name} · {store_name}", size=14))
        layout.addWidget(text_box)

        layout.addWidget(stretch())

        photo_button = secondary_button("Şəkli Dəyiş")
        photo_button.clicked.connect(self.photo_change_requested)
        layout.addWidget(photo_button)

        logout_button = secondary_button("Çıxış")
        logout_button.clicked.connect(self.logout_requested)
        layout.addWidget(logout_button)

        return header

    # ---------------------------- status kartı -------------------------------- #

    def _build_status_card(self) -> QWidget:
        card = Card(padding=26, spacing=14)

        card.add(muted_label("Cari status"))

        status_row = QWidget()
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(14)

        from src.presentation.widgets.primitives import StatusDot  # noqa: PLC0415

        self._status_dot = StatusDot(self._theme.color(self._status.color_token), size=14)
        status_layout.addWidget(self._status_dot)

        self._status_label = title_label(self._status.label_az, size=24)
        status_layout.addWidget(self._status_label)
        status_layout.addWidget(stretch())

        # Statusa uyğun TƏK düymə (spesifikasiya) — istifadəçi nə edəcəyini
        # seçmir, sistem onu bir addıma yönəldir.
        self._action = action_button(self._status.action_az)
        self._action.setMinimumHeight(54)
        self._action.setMaximumHeight(54)
        action_font = self._action.font()
        action_font.setPixelSize(17)
        self._action.setFont(action_font)
        self._action.clicked.connect(lambda: self.action_requested.emit(self._status))
        status_layout.addWidget(self._action)

        card.add(status_row)
        self._status_hint = body_label(self._status.hint_az, size=14)
        self._status_hint.setStyleSheet(f"color: {self._theme.color('--color-text-secondary')};")
        card.add(self._status_hint)
        return card

    def set_status(self, status: WorkerStatus, *, hint: str = "") -> None:
        """Statusu dəyişir — nöqtə rəngi, ad, izah və düymə birlikdə yenilənir."""
        self._status = status
        self._status_dot.set_color(self._theme.color(status.color_token))
        self._status_label.setText(status.label_az)
        self._status_hint.setText(hint or status.hint_az)
        self._action.setText(status.action_az)
        # "Gözlənilir…" vəziyyətində düymə var, amma basıla bilməz — işçi
        # operatorun təsdiqini gözləyir və təkrar sorğu göndərməməlidir.
        self._action.setEnabled(status.is_actionable)

    # ------------------------------- kartlar ---------------------------------- #

    def _build_cards_row(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(metrics.CARD_SPACING)

        layout.addWidget(self._build_tasks_card(), 1)
        layout.addWidget(self._build_points_card(), 1)
        layout.addWidget(self._build_fines_card(), 1)
        return container

    def _build_tasks_card(self) -> Card:
        card = Card(padding=22, spacing=12)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.addWidget(title_label("Açıq Tapşırıqlarım", size=16))
        head_layout.addWidget(stretch())
        self._tasks_count = title_label("0", size=16)
        head_layout.addWidget(self._tasks_count)
        card.add(head)
        card.add(Divider())

        self._tasks_body = QVBoxLayout()
        self._tasks_body.setSpacing(8)
        holder = QWidget()
        holder.setLayout(self._tasks_body)
        card.add(holder)

        card.body().addStretch(1)
        link = secondary_button("Hamısına bax →")
        link.clicked.connect(self.tasks_requested)
        card.add(link)
        return card

    def set_tasks(self, tasks: list[str]) -> None:
        """Açıq tapşırıqları göstərir."""
        clear_layout(self._tasks_body)

        self._tasks_count.setText(str(len(tasks)))
        for task in tasks:
            self._tasks_body.addWidget(body_label(task, size=13))

    def _build_points_card(self) -> Card:
        card = Card(padding=22, spacing=12)
        card.add(title_label("Xal Balansım", size=16))
        card.add(Divider())

        self._points_value = title_label("0", size=32)
        card.add(self._points_value)

        self._points_delta = muted_label("")
        card.add(self._points_delta)

        self._points_hint = body_label("", size=13)
        card.add(self._points_hint)

        card.body().addStretch(1)
        link = secondary_button("Mükafat kataloqu →")
        link.clicked.connect(self.rewards_requested)
        card.add(link)
        return card

    def set_points(self, balance: int, *, monthly_delta: int, to_next_reward: int) -> None:
        # Rəqəm boşluqla ayrılır (1 240) — maketdəki format.
        self._points_value.setText(f"{balance:,}".replace(",", " "))
        sign = "+" if monthly_delta >= 0 else ""
        self._points_delta.setText(f"{sign}{monthly_delta} bu ay")
        self._points_hint.setText(
            f"Növbəti mükafata {to_next_reward} xal qalıb."
            if to_next_reward > 0
            else "Mükafat üçün kifayət qədər xalınız var."
        )

    def _build_fines_card(self) -> Card:
        card = Card(padding=22, spacing=12)
        card.add(title_label("Cərimələrim", size=16))
        card.add(Divider())

        self._fines_summary = title_label("—", size=18)
        card.add(self._fines_summary)

        self._fines_detail = body_label("", size=13)
        card.add(self._fines_detail)

        self._fines_deadline = muted_label("")
        card.add(self._fines_deadline)

        card.body().addStretch(1)
        self._appeal_button = secondary_button("Etiraz Et")
        self._appeal_button.clicked.connect(self.appeal_requested)
        card.add(self._appeal_button)
        return card

    def set_fines(
        self,
        *,
        count: int,
        total_text: str,
        latest: str = "",
        appeal_days_left: int | None = None,
    ) -> None:
        self._fines_summary.setText(
            f"{count} bu ay · {total_text}" if count else "Bu ay cərimə yoxdur"
        )
        self._fines_detail.setText(latest)
        self._fines_detail.setVisible(bool(latest))

        if appeal_days_left is None:
            self._fines_deadline.setVisible(False)
            self._appeal_button.setVisible(False)
            return

        self._fines_deadline.setText(f"Etiraz müddəti: {appeal_days_left} gün qalıb")
        self._fines_deadline.setVisible(True)
        self._appeal_button.setVisible(appeal_days_left > 0)

    @property
    def status(self) -> WorkerStatus:
        return self._status


__all__ = [
    "LOCKOUT_MINUTES",
    "MAX_ATTEMPTS",
    "PIN_LENGTH",
    "EmployeeHomeScreen",
    "PinDots",
    "PinPadScreen",
]
