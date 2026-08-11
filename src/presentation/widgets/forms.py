"""Form elementləri — Faza 4.2.

Maketdəki hər giriş sahəsi eyni quruluşdadır: üstdə 13px/500 etiket, altda
46px hündürlüyündə sərhədli qutu (`border-radius: 9px`). Bu modul həmin cütü
bir widget kimi verir ki, 27 ekranda etiket-sahə boşluğu (`gap: 7px`) əl ilə
təkrarlanmasın.

──────────────────────────────────────────────────────────────────────────────
XƏTA MƏTNİ SAHƏNİN ALTINDA, SAHƏNİN İÇİNDƏ DEYİL
──────────────────────────────────────────────────────────────────────────────
Yanlış dəyər bildirişi placeholder-i əvəz etsəydi, istifadəçi yazmağa
başlayanda xəta itərdi və nə səhv etdiyini xatırlamazdı. Ona görə `set_error()`
mətni AYRI sətirdə göstərir və sahənin sərhədini qırmızıya çevirir
(`state="error"` — QSS-də mövcuddur).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.presentation.theme.manager import refresh_widget_style
from src.presentation.widgets.primitives import plain_label

if TYPE_CHECKING:
    from PySide6.QtWidgets import QAbstractSpinBox

#: Maketdəki sahə hündürlüyü.
FIELD_HEIGHT = 46
#: Etiket ilə sahə arası `gap: 7px`.
LABEL_SPACING = 7


def field_label(text: str) -> QLabel:
    """13px/500 sahə etiketi."""
    label = plain_label(text)
    font = label.font()
    font.setPixelSize(13)
    font.setWeight(QFont.Weight.DemiBold)
    label.setFont(font)
    return label


class FormField(QWidget):
    """Etiket + giriş sahəsi + (lazım olduqda) xəta mətni.

    Args:
        widget: Hazır giriş widget-i. `None` → `QLineEdit` yaradılır.
        password: `True` → simvollar gizlədilir.
        hint: Sahənin altındakı daimi izah (xəta mətnindən ayrıdır).
    """

    def __init__(
        self,
        label: str,
        *,
        widget: QLineEdit | QComboBox | QAbstractSpinBox | None = None,
        placeholder: str = "",
        password: bool = False,
        hint: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LABEL_SPACING)

        layout.addWidget(field_label(label))

        if widget is None:
            widget = QLineEdit()
            if placeholder:
                widget.setPlaceholderText(placeholder)
            if password:
                widget.setEchoMode(QLineEdit.EchoMode.Password)

        widget.setProperty("variant", "form")
        widget.setMinimumHeight(FIELD_HEIGHT)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._input = widget
        layout.addWidget(widget)

        self._hint = plain_label(hint)
        hint_font = self._hint.font()
        hint_font.setPixelSize(12)
        self._hint.setFont(hint_font)
        self._hint.setWordWrap(True)
        self._hint.setProperty("variant", "muted")
        self._hint.setVisible(bool(hint))
        layout.addWidget(self._hint)

        self._default_hint = hint

    # ------------------------------- dəyər ---------------------------------- #

    def input_widget(self) -> QLineEdit | QComboBox | QAbstractSpinBox:
        return self._input

    def focus_input(self) -> None:
        """Fokusu ETİKETƏ deyil, GİRİŞ SAHƏSİNƏ verir.

        `FormField` bir qabdır: `field.setFocus()` fokusu qabın özünə verərdi
        və Qt onu ilk uşağa ötürməzdi (qabın `focusPolicy`-si `NoFocus`-dur),
        yəni klaviatura ilə yazmaq mümkün olmazdı. Çağırış nöqtələri
        `input_widget().setFocus()` yazmasın deyə qayda BURADA saxlanılır —
        əks halda hər ekran daxili quruluşu bilməli olardı.
        """
        self._input.setFocus(Qt.FocusReason.OtherFocusReason)

    def text(self) -> str:
        """Sahənin mətni — `QLineEdit` və `QComboBox` üçün işləyir."""
        if isinstance(self._input, QLineEdit):
            return self._input.text()
        if isinstance(self._input, QComboBox):
            return self._input.currentText()
        return ""

    def set_text(self, value: str) -> None:
        if isinstance(self._input, QLineEdit):
            self._input.setText(value)
        elif isinstance(self._input, QComboBox):
            self._input.setCurrentText(value)

    # ------------------------------- xəta ----------------------------------- #

    def set_error(self, message: str) -> None:
        """Sahəni xətalı işarələyir və səbəbi altda göstərir."""
        self._input.setProperty("state", "error")
        refresh_widget_style(self._input)
        self._hint.setProperty("variant", "danger-text")
        self._hint.setText(message)
        self._hint.setVisible(True)
        refresh_widget_style(self._hint)

    def clear_error(self) -> None:
        """Xəta vəziyyətini götürür və daimi izahı bərpa edir."""
        self._input.setProperty("state", "")
        refresh_widget_style(self._input)
        self._hint.setProperty("variant", "muted")
        self._hint.setText(self._default_hint)
        self._hint.setVisible(bool(self._default_hint))
        refresh_widget_style(self._hint)

    @property
    def has_error(self) -> bool:
        # `property()` `Any` qaytarır — müqayisənin nəticəsi açıq `bool`-a
        # çevrilir ki, tip müqaviləsi sızmasın.
        return bool(self._input.property("state") == "error")


__all__ = ["FIELD_HEIGHT", "LABEL_SPACING", "FormField", "field_label"]
