"""Kontekstual «?» kömək düyməsi və onun modalı (audit G-4).

──────────────────────────────────────────────────────────────────────────────
BU MODUL NİYƏ VAR
──────────────────────────────────────────────────────────────────────────────
Spesifikasiya kontekstual köməyi MƏCBURİ sayır, lakin layihədə yalnız MƏRKƏZİ
«Yardım Mərkəzi» ekranı (35) var idi: istifadəçi ERP və ya İnfrastruktur
ekranında ilişəndə menyudan çıxıb ayrı bir ekrana keçməli, orada mövzu tapmalı
və sonra geri qayıtmalı olurdu. Ən çox köməyə ehtiyac duyulan an məhz
istifadəçinin ekranı TƏRK ETMƏK istəmədiyi andır.

Bu modul həmin boşluğu bağlayır: hər ekran öz başlığının yanına bir «?»
düyməsi qoyur, düymə isə eyni Yardım Mərkəzi tonunda — sadə, jarqonsuz,
addım-addım — kiçik bir modal açır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `screens/group_h.HelpTopicCard` İDXAL EDİLMİR
──────────────────────────────────────────────────────────────────────────────
Nömrələnmiş addım kartı orada ARTIQ var, lakin qat istiqaməti birdir:
`screens/` → `widgets/`. Əks istiqamətdə idxal (`widgets/` → `screens/`)
dairəvi asılılıq yaradardı — `group_h` özü `widgets/`-dən onlarla element
alır. Ona görə addım sətri burada YENİDƏN qurulur; vizual dil qəsdən eynidir
(dairəvi nömrə + gövdə mətni), yəni istifadəçi iki fərqli "kömək görünüşü"
öyrənmir.

──────────────────────────────────────────────────────────────────────────────
KLAVİATURA VƏ EKRAN OXUYUCUSU
──────────────────────────────────────────────────────────────────────────────
Düymə YALNIZ-İKONDUR, yəni `text()` boşdur və Qt-nin əlçatan-ad zənciri
(`accessibleName()` → `text()`) tooltip-ə BAXMIR (bax `buttons.icon_button`
başlığı). Ona görə ad AÇIQ verilir və ekranın adını daşıyır: «Kömək — ERP
Serverləri». `QPushButton` defolt olaraq `StrongFocus` daşıyır, yəni düymə
Tab ilə fokuslanır və Boşluq/Enter ilə açılır — siçansız istifadəçi köməyə
eyni yolla çatır.

Modalın mətni SEÇİLƏ BİLƏN qalır (`TextSelectableByMouse`): istifadəçi
addımı dəstək müraciətinə köçürə bilməlidir — mətni yalnız oxumaq üçün
kilidləmək onu yenidən yazmağa məcbur edərdi.

──────────────────────────────────────────────────────────────────────────────
RƏNG
──────────────────────────────────────────────────────────────────────────────
YENİ RƏNG CÜTÜ YARADILMIR. İkon `--color-text-muted`, modal isə mövcud `Card`
səthidir — hər ikisi `tokens.py`-da onsuz da kalibrlənmiş cütlərdir. Kömək
elementi üçün ayrıca vurğu rəngi seçmək kontrast qapısına yeni cüt əlavə
edərdi və heç bir üstünlük verməzdi.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.presentation.widgets import icons, metrics
from src.presentation.widgets.buttons import secondary_button
from src.presentation.widgets.primitives import (
    Card,
    Divider,
    body_label,
    plain_label,
    stretch,
    title_label,
)
from src.presentation.widgets.safe_text import plain_tooltip

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager

#: Düymənin tooltip mətni — hər ekranda EYNİDİR ki, ikonun mənası
#: öyrənildikdən sonra hər yerdə tanınsın.
HELP_TOOLTIP: Final = "Bu ekran haqqında kömək"

#: Modalın bağlama düyməsi.
HELP_CLOSE_TEXT: Final = "Bağla"

#: Modalın minimum eni — addımlar bir-iki sözdən sonra sətir dəyişməsin.
_DIALOG_MIN_WIDTH: Final = 520

#: Nömrə dairəsinin ölçüsü (`group_h.HelpTopicCard` ilə eyni).
_STEP_BADGE_SIZE: Final = 22


class HelpDialog(QDialog):
    """Bir ekranın kontekstual köməyi — giriş cümləsi + nömrələnmiş addımlar.

    Modal MODAL-DIR (`setModal(True)`): kömək oxunarkən arxadakı ekranla
    işləmək məcburiyyəti yoxdur və modal olmayan pəncərə ekranların arxasında
    itə bilərdi. Escape onu bağlayır (`QDialog`-un öz davranışı) — ayrıca
    qısayol elan etmək lazım deyil.
    """

    def __init__(
        self,
        theme: ThemeManager,
        *,
        title: str,
        intro: str,
        steps: tuple[str, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle(f"Kömək — {title}")
        self.setModal(True)
        self.setMinimumWidth(_DIALOG_MIN_WIDTH)
        self.setAccessibleName(f"Kömək — {title}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        card = Card(padding=metrics.CARD_PADDING, spacing=12)
        layout.addWidget(card)

        card.add(title_label(title, size=19))
        intro_label = body_label(intro, size=13)
        intro_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card.add(intro_label)
        card.add(Divider())

        for index, step in enumerate(steps, start=1):
            card.add(self._step_row(index, step))

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.addWidget(stretch())
        close = secondary_button(HELP_CLOSE_TEXT)
        close.clicked.connect(self.accept)
        buttons_layout.addWidget(close)
        card.add(buttons)

        # Fokus BAĞLA düyməsindədir: modal açılan kimi Enter onu bağlayır,
        # yəni klaviatura istifadəçisi köməyi oxuyub bir düymə ilə işinə
        # qayıdır.
        close.setFocus(Qt.FocusReason.OtherFocusReason)

    def _step_row(self, index: int, text: str) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)

        number = plain_label(str(index))
        number.setFixedSize(_STEP_BADGE_SIZE, _STEP_BADGE_SIZE)
        number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        number.setStyleSheet(
            f"background-color: {self._theme.color('--color-neutral-bg')};"
            f"color: {self._theme.color('--color-text-secondary')};"
            f"border-radius: {_STEP_BADGE_SIZE // 2}px; font-size: 11px;"
        )
        row_layout.addWidget(number, alignment=Qt.AlignmentFlag.AlignTop)

        body = body_label(text, size=13)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row_layout.addWidget(body, 1)
        return row


class HelpButton(QPushButton):
    """Ekran başlığının yanındakı «?» düyməsi.

    `buttons.icon_button()` FABRİKASI İŞLƏDİLMİR, çünki o, hazır nüsxə
    qaytarır və alt sinif üçün istifadə oluna bilmir. Konfiqurasiya isə
    HƏRFƏN eynidir (`variant=icon`, `HEADER_ICON_BUTTON` ölçüsü, `icons.icon`)
    — ikisinin sükutla ayrılmasının qarşısını `tests/unit/
    test_contextual_help.py`-dakı paritet qapısı alır.

    Mətnlər konstruktora ötürülür, modul səviyyəsində SAXLANILMIR: hər ekranın
    köməyi həmin ekranın YANINDA yaşamalıdır — ayrı bir kataloqda saxlansaydı,
    ekran dəyişəndə mətn arxada qalardı (eyni əsaslandırma `group_h.
    HELP_TOPICS` şərhindədir).
    """

    def __init__(
        self,
        theme: ThemeManager,
        *,
        title: str,
        intro: str,
        steps: tuple[str, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._title = title
        self._intro = intro
        self._steps = steps

        self.setProperty("variant", "icon")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIcon(icons.icon("help", theme.color("--color-text-muted")))
        self.setIconSize(QSize(icons.DEFAULT_SIZE, icons.DEFAULT_SIZE))
        self.setFixedSize(metrics.HEADER_ICON_BUTTON, metrics.HEADER_ICON_BUTTON)
        self.setToolTip(plain_tooltip(HELP_TOOLTIP))
        self.setAccessibleName(f"Kömək — {title}")
        self.setAccessibleDescription(intro)
        self.clicked.connect(self.open_help)

    def open_help(self) -> HelpDialog:
        """Modalı qurur və göstərir; nüsxəni QAYTARIR (testlər üçün).

        `exec()` DEYİL, `show()`: `exec()` öz hadisə dövrəsini işə salır və
        çağıran kodu bloklayır — testdə isə bu, sonsuz gözləmə demək olardı.
        Modal davranış onsuz da `setModal(True)` ilə təmin olunur.

        Valideyn PƏNCƏRƏDİR (`window()`), düymə DEYİL: modal düymənin
        üstündə deyil, ekranın MƏRKƏZİNDƏ açılmalıdır və düymə ekran
        dəyişəndə məhv olsa, modal onunla birlikdə ölməlidir — hər iki
        tələbi pəncərə valideynliyi ödəyir.
        """
        dialog = HelpDialog(
            self._theme,
            title=self._title,
            intro=self._intro,
            steps=self._steps,
            parent=self.window(),
        )
        dialog.show()
        return dialog


__all__ = [
    "HELP_CLOSE_TEXT",
    "HELP_TOOLTIP",
    "HelpButton",
    "HelpDialog",
]
