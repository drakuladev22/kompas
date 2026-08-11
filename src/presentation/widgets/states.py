"""Boş / yüklənmə / xəta vəziyyətləri — Qrup G — Faza 4.2.

Maketin Qrup G sənədi bu üç vəziyyət üçün VAHİD qayda qoyur:

    "Hər modulun boş, yüklənmə və xəta vəziyyəti eyni qaydaya tabedir: nə baş
     verdiyini bir cümlə ilə izah et, sonra bir aydın hərəkət təklif et."

Ona görə hər modul öz "məlumat yoxdur" ekranını ayrıca qurmur — buradakı üç
sinif işlədilir və mətnlər arqument kimi verilir. Bu, 27 ekranda eyni
davranışı təmin edir və bir modulun "sadəcə boş cədvəl" göstərməsinin
qarşısını alır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `ThemeManager` ARQUMENTDİR
──────────────────────────────────────────────────────────────────────────────
Bu siniflər `primitives`-dən fərqli olaraq BİR NEÇƏ tokeni birlikdə işlədir
(ikon çərçivəsinin fonu, sərhədi, ikon rəngi, mətn rəngləri). Hər birini ayrı
arqument kimi ötürmək çağırış yerini oxunmaz edərdi. `ThemeManager` isə
`QApplication` olmadan da işləyir (bax `manager.resolve_mode`), yəni testdə
başsız (headless) qurmaq mümkündür.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.presentation.widgets import icons, metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.primitives import (
    Card,
    Divider,
    Skeleton,
    body_label,
    muted_label,
    plain_label,
    stretch,
)

if TYPE_CHECKING:
    from PySide6.QtGui import QHideEvent, QShowEvent

    from src.presentation.theme.manager import ThemeManager

#: Vəziyyətin tonu — ikon çərçivəsinin rəngini müəyyən edir.
StateTone = Literal["neutral", "danger", "warning", "accent"]

#: Ton → (fon tokeni, sərhəd tokeni, ikon tokeni).
_TONE_TOKENS: dict[StateTone, tuple[str, str, str]] = {
    "neutral": ("--color-card-bg", "--color-card-border", "--color-text-muted"),
    "danger": ("--color-danger-bg", "--color-danger", "--color-danger"),
    "warning": ("--color-warning-bg", "--color-warning", "--color-warning"),
    "accent": ("--color-accent-subtle", "--color-brand-amber", "--color-brand-amber"),
}


class StateIconBox(QWidget):
    """76×76 yumşaq künclü ikon çərçivəsi — maketdəki `border-radius: 22px`.

    Qt-də bu formanı QSS ilə vermək olar, lakin rəng tondan asılı olaraq
    dəyişdiyi üçün şablona beş ayrı seçici lazım olardı. Bir widget-in
    `styleSheet`-ini birbaşa yazmaq burada daha az koddur və token adları
    yenə `ThemeManager`-dən gəlir.
    """

    def __init__(
        self,
        icon_name: str,
        theme: ThemeManager,
        *,
        tone: StateTone = "neutral",
        box_size: int = metrics.STATE_ICON_BOX,
        icon_size: int = metrics.STATE_ICON_SIZE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        background_token, border_token, icon_token = _TONE_TOKENS[tone]

        self.setFixedSize(box_size, box_size)
        self.setStyleSheet(
            f"background-color: {theme.color(background_token)};"
            f"border: 1px solid {theme.color(border_token)};"
            f"border-radius: {metrics.STATE_ICON_BOX_RADIUS}px;"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        glyph = plain_label()
        glyph.setPixmap(
            icons.render(
                icon_name,
                theme.color(icon_token),
                size=icon_size,
                stroke_width=1.2,
            )
        )
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glyph.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(glyph)


class EmptyState(QWidget):
    """ "Məlumat yoxdur" vəziyyəti — ikon, başlıq, izah və bir aydın hərəkət.

    Signals:
        primary_clicked: Əsas düymə.
        secondary_clicked: İkinci düymə (varsa).
    """

    primary_clicked = Signal()
    secondary_clicked = Signal()

    def __init__(
        self,
        theme: ThemeManager,
        *,
        icon_name: str,
        title: str,
        message: str,
        primary_text: str = "",
        primary_icon: str | None = None,
        secondary_text: str = "",
        tone: StateTone = "neutral",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        inner = QVBoxLayout()
        inner.setSpacing(20)
        inner.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        icon_box = StateIconBox(icon_name, theme, tone=tone)
        inner.addWidget(icon_box, alignment=Qt.AlignmentFlag.AlignHCenter)

        heading = plain_label(title)
        heading_font = heading.font()
        heading_font.setPixelSize(metrics.FONT_STATE_TITLE)
        heading_font.setWeight(QFont.Weight.DemiBold)
        heading.setFont(heading_font)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(heading)

        description = body_label(message, size=14)
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description.setMaximumWidth(metrics.STATE_TEXT_MAX_WIDTH)
        description.setStyleSheet(f"color: {theme.color('--color-text-secondary')};")
        inner.addWidget(description, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._extra = QVBoxLayout()
        self._extra.setSpacing(12)
        inner.addLayout(self._extra)

        if primary_text or secondary_text:
            buttons = QHBoxLayout()
            buttons.setSpacing(12)
            buttons.setAlignment(Qt.AlignmentFlag.AlignHCenter)

            if primary_text:
                primary = action_button(
                    primary_text,
                    icon_name=primary_icon,
                    icon_color=theme.color("--color-action-text"),
                )
                primary.clicked.connect(self.primary_clicked)
                buttons.addWidget(primary)

            if secondary_text:
                secondary = secondary_button(secondary_text)
                secondary.clicked.connect(self.secondary_clicked)
                buttons.addWidget(secondary)

            inner.addLayout(buttons)

        self._footer = muted_label("")
        self._footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._footer.setVisible(False)
        inner.addWidget(self._footer, alignment=Qt.AlignmentFlag.AlignHCenter)

        outer.addLayout(inner)

    def set_footnote(self, text: str) -> None:
        """Altdakı kiçik qeyd — "Avtomatik yenidən cəhd 30 saniyədən bir edilir."."""
        self._footer.setText(text)
        self._footer.setVisible(bool(text))

    def add_detail_rows(self, rows: list[tuple[str, str]], *, mono_values: bool = True) -> None:
        """Açar/dəyər cədvəli — xəta kodu, son uğurlu yenilənmə və s.

        Maketdə bu, ikinci sərhədli qutudur və hər sətir "ad ... dəyər"
        formasındadır (dəyər sağa dayanır).
        """
        if not rows:
            return

        card = Card(padding=14, spacing=8)
        card.setMaximumWidth(metrics.STATE_TEXT_MAX_WIDTH + 120)

        for index, (name, value) in enumerate(rows):
            line = QWidget()
            line_layout = QHBoxLayout(line)
            line_layout.setContentsMargins(0, 0, 0, 0)
            line_layout.setSpacing(10)

            key_label = muted_label(name)
            line_layout.addWidget(key_label)
            line_layout.addWidget(stretch())

            value_label = plain_label(value)
            value_font = value_label.font()
            value_font.setPixelSize(metrics.FONT_CAPTION)
            if mono_values:
                value_label.setProperty("variant", "mono")
            value_label.setFont(value_font)
            line_layout.addWidget(value_label)

            card.add(line)
            if index < len(rows) - 1:
                card.add(Divider())

        self._extra.addWidget(card, alignment=Qt.AlignmentFlag.AlignHCenter)


class ErrorState(EmptyState):
    """Xəta vəziyyəti — `EmptyState`-in qırmızı tonlu variantı.

    Ayrı sinif kimi saxlanılır ki, çağırış yerində niyyət görünsün və ton
    təsadüfən "neutral" qalmasın.
    """

    def __init__(
        self,
        theme: ThemeManager,
        *,
        title: str,
        message: str,
        icon_name: str = "server_off",
        primary_text: str = "Yenidən Cəhd Et",
        primary_icon: str | None = "refresh",
        secondary_text: str = "",
        details: list[tuple[str, str]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            theme,
            icon_name=icon_name,
            title=title,
            message=message,
            primary_text=primary_text,
            primary_icon=primary_icon,
            secondary_text=secondary_text,
            tone="danger",
            parent=parent,
        )
        if details:
            self.add_detail_rows(details)


class LoadingState(QWidget):
    """Skeleton siyahısı — maketdəki pilləli shimmer sətirləri.

    Spesifik detal (maketdən): skeleton YALNIZ 400 ms-dən sonra görünür.
    Daha qısa yükləmələrdə heç nə göstərilmir, çünki bir anlıq görünüb yox
    olan boz bloklar "sayrışma" effekti yaradır və yükləmənin özündən daha
    çox nəzərə çarpır. Gecikməni ekran idarə edir (`QTimer`); bu widget
    sadəcə görüntünü verir.
    """

    def __init__(
        self,
        *,
        rows: int = 4,
        show_filters: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._blocks: list[Skeleton] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        if show_filters:
            filters = QHBoxLayout()
            filters.setSpacing(10)
            for index, width in enumerate((110, 150, 170)):
                block = Skeleton(width, 32, delay_ms=index * 100)
                self._blocks.append(block)
                filters.addWidget(block)
            filters.addStretch(1)
            layout.addLayout(filters)

        for row_index in range(rows):
            layout.addWidget(self._build_row(row_index))

        layout.addStretch(1)

    def _build_row(self, row_index: int) -> QWidget:
        """Bir siyahı sətri — dairəvi avatar + iki mətn zolağı + düymələr.

        Maketdə hər növbəti sətir bir qədər şəffafdır (`opacity: 0.85 → 0.5`),
        yəni siyahı aşağı doğru "solur". Bu, gözü yuxarıdakı məzmuna yönəldir.
        """
        delay = row_index * 100
        card = Card(padding=16, spacing=0)

        line = QHBoxLayout()
        line.setSpacing(18)

        avatar = Skeleton(46, 46, delay_ms=delay)
        self._blocks.append(avatar)
        line.addWidget(avatar)

        texts = QVBoxLayout()
        texts.setSpacing(8)
        for width, height, alt in ((180, 14, False), (130, 12, True)):
            block = Skeleton(width, height, alt=alt, delay_ms=delay + 150)
            self._blocks.append(block)
            texts.addWidget(block)
        line.addLayout(texts)

        line.addStretch(1)

        for index, width in enumerate((110, 96, 120)):
            block = Skeleton(width, 38, alt=index < 2, delay_ms=delay + index * 100)  # noqa: PLR2004
            self._blocks.append(block)
            line.addWidget(block)

        container = QWidget()
        container.setLayout(line)
        card.add(container)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return card

    def start(self) -> None:
        """Bütün blokların animasiyasını işə salır."""
        for block in self._blocks:
            block.start()

    def stop(self) -> None:
        for block in self._blocks:
            block.stop()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt adlandırması
        super().showEvent(event)
        self.start()

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802 - Qt adlandırması
        # Görünməyən animasiya CPU yeyir — kiosk PC-ləri zəifdir.
        self.stop()
        super().hideEvent(event)


__all__ = [
    "EmptyState",
    "ErrorState",
    "LoadingState",
    "StateIconBox",
    "StateTone",
]
