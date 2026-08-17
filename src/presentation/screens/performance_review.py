"""Performans Qiymətləndirməsi forması — #20, kompasos11.md Faza 8.

Maketdə AYRICA fayl kimi verilməyib (Qrup A–I-də yoxdur) — bu, Faza 8-in
`can_conduct_performance_review` sahibi üçün YENİ funksiyadır. Mövcud dizayn
dilini (`Card`, `FormField`, `Divider`, `Chip`) TƏKRAR İSTİFADƏ edir.

──────────────────────────────────────────────────────────────────────────────
KPI SİYAHISI EKRANDA HARDCODE EDİLMİR
──────────────────────────────────────────────────────────────────────────────
`set_kpi_catalog()` konstruktorda YOX, DOLDURMA zamanı çağırılır — çünki
göstərici siyahısı Root-un `system_limits.PERFORMANCE_REVIEW_KPI_CATALOG`
parametridir (`kompasos11.md` Faza 8-in açıq tələbi: "KPI siyahısı da
konfiqurasiya edilə bilən olmalıdır"). Ekran KPI kodlarının MƏNASINI
tanımır — yalnız `(kod, etiket)` cütlərini göstərir.

──────────────────────────────────────────────────────────────────────────────
BAL ŞKALASI (1–5) NİYƏ BURADA SABİTDİR
──────────────────────────────────────────────────────────────────────────────
`entities/performance_review.py::KPI_SCORE_MIN/MAX` başlığındakı EYNİ
əsaslandırma: bu, ROOT parametri deyil, ölçü vahididir (dəyişsə köhnə
`overall_score` sətirləri geriyə dönük mənasız olardı). Ekran bunu təkrar
YAZMIR, sadəcə sabit 1-5 seçimini göstərir.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.presentation.screens.base import Screen
from src.presentation.widgets.buttons import action_button
from src.presentation.widgets.forms import FormField, field_label
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import (
    Card,
    Chip,
    Divider,
    body_label,
    muted_label,
    section_label,
    stretch,
    title_label,
)

if TYPE_CHECKING:
    from PySide6.QtGui import QShowEvent

    from src.presentation.theme.manager import ThemeManager

#: Likert şkalası — modul başlığındakı izah: struktur sabit, ROOT parametri DEYİL.
_SCORE_CHOICES: tuple[int, ...] = (1, 2, 3, 4, 5)


class PerformanceReviewScreen(Screen):
    """Qiymətləndirmə forması + seçilmiş işçinin keçmiş dövrləri.

    Signals:
        employee_selected: İşçi dropdown-u dəyişdi (`employee_id`) — kontroller
            keçmiş dövrləri VƏ dövr sahəsinin defolt dəyərini yenidən oxuyur.
        submit_requested: "Yadda Saxla" — `dict` (`employee_id`, `period`,
            `ratings`, `notes`).
    """

    employee_selected = Signal(str)
    submit_requested = Signal(dict)

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)
        self._kpi_inputs: dict[str, QComboBox] = {}

        columns = QWidget()
        columns_layout = QHBoxLayout(columns)
        columns_layout.setContentsMargins(0, 0, 0, 0)
        columns_layout.setSpacing(20)
        # Dar pəncərədə forma və tarixçə alt-alta düşür (bax
        # `screens/base.py::responsive_row`).
        self.responsive_row(columns_layout)
        columns_layout.addWidget(self._build_form_card(), 1)
        columns_layout.addWidget(self._build_history_card(), 1)
        self.add(columns)
        self.body().addStretch(1)

    # ------------------------------- forma kartı ------------------------------ #

    def _build_form_card(self) -> Card:
        card = Card(padding=20, spacing=12)
        card.add(title_label("Yeni Qiymətləndirmə", size=19))
        card.add(Divider())

        self._employee = FormField("İşçi", widget=QComboBox())
        employee_combo = self._employee.input_widget()
        assert isinstance(employee_combo, QComboBox)
        employee_combo.currentIndexChanged.connect(self._on_employee_changed)
        card.add(self._employee)

        self._period = FormField("Dövr", hint="Format: YYYY, YYYY-MM və ya YYYY-Qn")
        card.add(self._period)

        card.add(field_label("Göstəricilər (KPI)"))
        self._kpi_host = QWidget()
        self._kpi_layout = QVBoxLayout(self._kpi_host)
        self._kpi_layout.setContentsMargins(0, 0, 0, 0)
        self._kpi_layout.setSpacing(12)
        card.add(self._kpi_host)

        card.add(field_label("Qeyd"))
        self._notes = QPlainTextEdit()
        self._notes.setProperty("variant", "form")
        self._notes.setMinimumHeight(88)
        self._notes.setPlaceholderText("Sərbəst rəy (könüllü)…")
        card.add(self._notes)

        self._error = muted_label("")
        self._error.setProperty("variant", "danger-text")
        self._error.setVisible(False)
        card.add(self._error)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.addWidget(stretch())
        save = action_button("Yadda Saxla")
        save.clicked.connect(self._on_submit)
        buttons_layout.addWidget(save)
        card.add(buttons)

        return card

    def _build_history_card(self) -> Card:
        card = Card(padding=20, spacing=12)
        card.add(section_label("Keçmiş Dövrlər"))
        card.add(Divider())

        self._history_rows = QVBoxLayout()
        self._history_rows.setSpacing(16)
        holder = QWidget()
        holder.setLayout(self._history_rows)
        card.add(holder)

        self._history_empty = muted_label("Bu işçi üçün qeydiyyatlı qiymətləndirmə yoxdur.")
        card.add(self._history_empty)

        card.body().addStretch(1)
        return card

    # ------------------------------- doldurma --------------------------------- #

    def set_employees(self, employees: list[tuple[str, str]]) -> None:
        """`(id, ad)` cütləri — dropdown ilk elementlə açılır."""
        combo = self._employee.input_widget()
        assert isinstance(combo, QComboBox)
        combo.blockSignals(True)
        combo.clear()
        for employee_id, name in employees:
            combo.addItem(name, employee_id)
        combo.blockSignals(False)
        if employees:
            self._on_employee_changed(0)

    def set_kpi_catalog(self, kpis: list[tuple[str, str]]) -> None:
        """`(kod, etiket)` cütləri — Root-un CARİ kataloqu (modul başlığı)."""
        clear_layout(self._kpi_layout)
        self._kpi_inputs.clear()
        for code, label in kpis:
            self._kpi_layout.addWidget(self._build_kpi_row(code, label))

    def _build_kpi_row(self, code: str, label: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(body_label(label, size=13), 1)

        combo = QComboBox()
        combo.setProperty("variant", "form")
        combo.setFixedWidth(72)
        for score in _SCORE_CHOICES:
            combo.addItem(str(score), score)
        # Orta bal ilkin dəyər kimi seçilir — boş buraxılmış KPI görünüşü
        # istifadəçiyə "hələ qiymətləndirilməyib" təəssüratı verməsin deyə.
        combo.setCurrentIndex(len(_SCORE_CHOICES) // 2)
        layout.addWidget(combo)

        self._kpi_inputs[code] = combo
        return row

    def set_period(self, period: str) -> None:
        """Formanın DEFOLT dövr sətri — `PerformanceReviewUseCase.default_period`-dan."""
        self._period.set_text(period)

    def set_history(self, rows: list[dict[str, str]]) -> None:
        """Seçilmiş işçinin keçmiş dövrləri.

        Args:
            rows: `period`, `overall_score`, `reviewer`, `notes` açarları —
                açarlar `group_g.ProfileScreen.set_performance_history` ilə
                EYNİDİR (CLAUDE.md §6 — iki ekran eyni `PerformanceReviewView`
                mənbəyindən qidalanır).
        """
        clear_layout(self._history_rows)
        self._history_empty.setVisible(not rows)
        for row in rows:
            self._history_rows.addWidget(self._build_history_row(row))

    def _build_history_row(self, row: dict[str, str]) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.addWidget(body_label(row.get("period", ""), size=13))
        head_layout.addWidget(stretch())
        score_text = row.get("overall_score", "")
        if score_text:
            head_layout.addWidget(Chip(f"{score_text} xal", "info"))
        layout.addWidget(head)

        reviewer = row.get("reviewer", "")
        if reviewer:
            layout.addWidget(muted_label(f"Qiymətləndirən: {reviewer}", size=12))

        notes = row.get("notes", "")
        if notes:
            layout.addWidget(body_label(notes, size=12))

        return container

    def show_form_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(bool(message))

    # ------------------------------- siqnal körpüləri -------------------------- #

    def _on_employee_changed(self, index: int) -> None:
        combo = self._employee.input_widget()
        assert isinstance(combo, QComboBox)
        employee_id = combo.itemData(index)
        if employee_id:
            self.employee_selected.emit(str(employee_id))

    def _on_submit(self) -> None:
        combo = self._employee.input_widget()
        assert isinstance(combo, QComboBox)
        employee_id = combo.currentData()
        period = self._period.text().strip()

        self.show_form_error("")
        self._period.clear_error()
        if not employee_id:
            self.show_form_error("İşçi seçin.")
            return
        if not period:
            self._period.set_error("Dövr məcburidir")
            return

        ratings = {code: field.currentData() for code, field in self._kpi_inputs.items()}
        self.submit_requested.emit(
            {
                "employee_id": str(employee_id),
                "period": period,
                "ratings": ratings,
                "notes": self._notes.toPlainText().strip(),
            }
        )

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt adlandırması
        super().showEvent(event)
        self._employee.focus_input()


__all__ = ["PerformanceReviewScreen"]
