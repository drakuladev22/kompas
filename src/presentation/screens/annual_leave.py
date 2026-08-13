"""İllik məzuniyyət ekranları — #28, kompas1.md Faza 4.

İki widget, İKİ AYRI auditoriya:

    `AnnualLeaveRequestDialog` → İŞÇİ (kiosk): tarix seçir, sorğu göndərir.
    `AnnualLeaveInboxScreen`   → HR (`can_manage_leave_balances`): təsdiq növbəsi.

Maketdə (Qrup A–I) AYRICA fayl kimi verilməyib — `announcements.py`,
`performance_review.py`, `attrition_risk.py` və `field_reports.py` ilə eyni
vəziyyət: Faza 4-ün YENİ funksiyasıdır və mövcud dizayn dilini (`Card`,
`DataTable`, `Chip`, `QComboBox[variant="form"]`) TƏKRAR İSTİFADƏ edir. Yeni
rəng sabiti YOXDUR — `scripts/check_contrast.py` ölçdüyü 130 cütdən kənara
çıxan heç bir cüt gətirilmir.

──────────────────────────────────────────────────────────────────────────────
BU ÜÇÜNCÜ MEXANİZMDİR — İKİSİ İLƏ QARIŞDIRILMIR
──────────────────────────────────────────────────────────────────────────────
KompasOS-da "istirahət" sözünün ÜÇ ayrı mənası var və hər birinin ÖZ ekranı:

  * STEP1/STEP2 gündaxili icazə (DƏQİQƏ) — İşçi Ana Ekranındakı statusa uyğun
    TƏK düymə (`[İcazə İstəyirəm]`) və «Canlı Növbə» ekranı;
  * Shift Matrix istirahət günü (PLAN) — «Növbə Planlama» matrisi;
  * İLLİK MƏZUNİYYƏT (GÜN, haqq) — BU FAYL.

Ona görə burada nə `MonthlyLeaveUsage` (240 dəq.), nə də növbə matrisi
göstərilmir: bir ekranda iki fərqli "qalan vaxt" rəqəmi işçini yanıldardı.

──────────────────────────────────────────────────────────────────────────────
TARİX SEÇİMİ NİYƏ `QComboBox`-DİR, `QDateEdit`/`QCalendarWidget` DEYİL
──────────────────────────────────────────────────────────────────────────────
`open_shift.OpenShiftPostDialog`-dakı qərarın eynisi və eyni iki səbəbdən:

  1. SİYAHI YALNIZ İCAZƏLİ GÜNÜ GÖSTƏRİR. `AnnualLeaveUseCase.submit` keçmiş
     tarixi rədd edir, `_charge_year` isə sorğunu BAŞLANĞIC ilinin balansından
     çıxır. Təqvim vidjeti işçini istənilən günə buraxar, sonra use case onu
     rədd edərdi — səhv yalnız düymə basıldıqdan sonra görünərdi.
  2. DİZAYN SİSTEMİ. `qss.py` `QComboBox[variant="form"]` üçün kontrast
     yoxlanılmış rəng cütü saxlayır; `QCalendarWidget` üçün belə qayda YOXDUR
     və onu əlavə etmək kontrast yoxlayıcısına yeni cüt gətirərdi.

BİTMƏ SİYAHISI BAŞLANĞICA GÖRƏ YENİDƏN QURULUR: "bitmə < başlanğıc" vəziyyəti
UI-da ÜMUMİYYƏTLƏ mövcud olmur. `AnnualLeaveRequest.__init__` həmin qaydanı
onsuz da qoruyur — dialoq onu TƏKRARLAMIR, sadəcə ifadə edilə bilməz edir.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from src.presentation.screens.base import Screen
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.data_table import Column, DataTable
from src.presentation.widgets.forms import field_label
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import (
    Card,
    Divider,
    muted_label,
    stretch,
    title_label,
)

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager


class AnnualLeaveInboxScreen(Screen):
    """HR-ın illik məzuniyyət təsdiq növbəsi — `can_manage_leave_balances`.

    Signals:
        approve_requested: Sətrin `[Təsdiqlə]` düyməsi (sorğu identifikatoru).
        reject_requested: Sətrin `[Rədd Et]` düyməsi (sorğu identifikatoru).
        refresh_requested: `[Yenilə]` — siyahını təzədən oxuyur.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ SƏBƏB SAHƏSİ CƏDVƏLDƏ DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Rədd səbəbi MƏCBURİDİR (`AnnualLeaveRequest.reject`), lakin sətrin içində
    mətn qutusu olsaydı, HR onu doldurmadan `[Rədd Et]`-i basar və domen
    istisnası ilə qarşılaşardı. Səbəb `QInputDialog` ilə soruşulur
    (`controllers/camera_queue.py::_ask_reason` naxışı): boş cavab yazı yoluna
    ÜMUMİYYƏTLƏ göndərilmir.
    """

    approve_requested = Signal(str)
    reject_requested = Signal(str)
    refresh_requested = Signal()

    #: `ClassVar` — `Column` siyahısı nüsxələr arasında PAYLAŞILA bilər
    #: (heç bir nüsxə onu dəyişmir); bax `announcements.AnnouncementsScreen`.
    _COLUMNS: ClassVar[list[Column]] = [
        Column("İşçi"),
        Column("Tarixlər", 210, mono=True),
        Column("Müddət", 130),
        Column("Göndərilib", 150, mono=True),
        Column("Əməliyyat", 210),
    ]

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(10)
        self._summary = muted_label("")
        toolbar_layout.addWidget(self._summary)
        toolbar_layout.addWidget(stretch())

        refresh = secondary_button("Yenilə")
        refresh.clicked.connect(self.refresh_requested)
        toolbar_layout.addWidget(refresh)
        self.add(toolbar)

        self._table_host = QWidget()
        self._table_layout = QVBoxLayout(self._table_host)
        self._table_layout.setContentsMargins(0, 0, 0, 0)
        self._table_layout.setSpacing(0)
        self.add(self._table_host)

    def set_requests(self, rows: list[dict[str, str]]) -> None:
        """Təsdiq gözləyən sorğuları göstərir.

        Args:
            rows: `id`, `employee`, `range_text`, `days_text`, `submitted`
                açarları olan sözlüklər. Açarlar HƏM maket
                (`preview_screens._annual_leave`), HƏM canlı yol
                (`controllers/annual_leave.py::_to_inbox_row`) üçün EYNİDİR —
                CLAUDE.md §6.

        Boş siyahı NORMAL haldır (gözləyən sorğu yoxdur) və xəta DEYİL —
        `show_empty` göstərilir, `show_error` YOX.
        """
        clear_layout(self._table_layout)

        if not rows:
            self.show_empty(
                icon_name="calendar",
                title="Təsdiq gözləyən məzuniyyət sorğusu yoxdur",
                message="İşçi Ana Ekranından göndərilən illik məzuniyyət sorğuları burada görünür.",
            )
            return

        self._summary.setText(f"{len(rows)} sorğu təsdiq gözləyir")

        table = DataTable(self._COLUMNS, self.theme)
        for row in rows:
            table.add_row(self._build_cells(row))
        self._table_layout.addWidget(table)
        self.show_content()

    def table_layout(self) -> QVBoxLayout:
        """Cədvəl qabı — testlər sətir sayını buradan oxuyur."""
        return self._table_layout

    def _build_cells(self, row: dict[str, str]) -> list[QWidget | str]:
        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)

        key = row.get("id", "")
        approve = action_button("Təsdiqlə")
        approve.clicked.connect(lambda *_, k=key: self.approve_requested.emit(k))
        actions_layout.addWidget(approve)

        reject = secondary_button("Rədd Et")
        reject.setProperty("variant", "danger")
        reject.clicked.connect(lambda *_, k=key: self.reject_requested.emit(k))
        actions_layout.addWidget(reject)

        return [
            row.get("employee", ""),
            row.get("range_text", ""),
            row.get("days_text", ""),
            row.get("submitted", ""),
            actions,
        ]


class AnnualLeaveRequestDialog(QDialog):
    """İşçinin `[Məzuniyyət Sorğusu]` forması — başlanğıc və bitmə tarixi.

    Signals:
        submitted: `(start_iso, end_iso)` — ISO formatında iki təqvim günü.

    Dialoq BALANSI YOXLAMIR: kifayət edən gün, üst-üstə düşən məzuniyyət və
    keçmiş tarix qaydaları `AnnualLeaveUseCase.submit`-dədir. Burada yalnız
    BOŞ seçim bloklanır — onsuz siqnal mənasız boş sətirlə gedərdi
    (`open_shift.OpenShiftPostDialog._on_submit` ilə eyni sərhəd).
    """

    submitted = Signal(str, str)

    def __init__(
        self,
        theme: ThemeManager,
        *,
        days: list[tuple[str, str]],
        balance_hint: str = "",
        parent: QWidget | None = None,
    ) -> None:
        """
        Args:
            days: `(ISO tarix, göstərilən mətn)` cütləri — YALNIZ seçilə bilən
                günlər (bugündən cari balans ilinin sonunadək; bax
                `controllers/annual_leave.py::_day_choices`).
            balance_hint: "Balansınızda 14 gün qalıb." — rəqəm ekranda
                HESABLANMIR, çağırandan gəlir.
        """
        super().__init__(parent)
        self._theme = theme
        self._days = list(days)
        self.setWindowTitle("Məzuniyyət Sorğusu")
        self.setModal(True)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = Card(padding=26, spacing=16)
        layout.addWidget(card)
        card.add(title_label("İllik Məzuniyyət Sorğusu", size=19))
        card.add(
            muted_label(
                "Sorğu təsdiq gözləyir — balansınızdan gün YALNIZ təsdiqdən sonra çıxılır.",
                size=12,
            )
        )
        if balance_hint:
            card.add(muted_label(balance_hint, size=12))
        card.add(Divider())

        self._start = self._build_combo(card, "Başlanğıc tarixi", self._days)
        self._end = self._build_combo(card, "Bitmə tarixi", self._days)
        # Bitmə siyahısı başlanğıcdan ASILIDIR — bax modul başlığı.
        self._start.currentIndexChanged.connect(self._sync_end_choices)
        self._sync_end_choices()

        self._hint = muted_label("")
        card.add(self._hint)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)
        buttons_layout.addWidget(stretch())

        cancel = secondary_button("İmtina")
        cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel)

        submit = action_button("Sorğu Göndər")
        submit.clicked.connect(self._on_submit)
        buttons_layout.addWidget(submit)
        card.add(buttons)

        submit.setDefault(True)
        submit.setAutoDefault(True)
        cancel.setAutoDefault(False)

        # Fokus sırası vizual sıra ilə: başlanğıc → bitmə → düymələr.
        QWidget.setTabOrder(self._start, self._end)
        QWidget.setTabOrder(self._end, cancel)
        QWidget.setTabOrder(cancel, submit)

    def _build_combo(self, card: Card, label: str, items: list[tuple[str, str]]) -> QComboBox:
        box = QWidget()
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(7)
        box_layout.addWidget(field_label(label))

        combo = QComboBox()
        combo.setProperty("variant", "form")
        for key, text in items:
            # Dəyər `userData`-dadır: göstərilən mətn Azərbaycan dilindədir və
            # ISO tarixi mətndən geri çıxarmaq mümkün olmamalıdır.
            combo.addItem(text, key)
        box_layout.addWidget(combo)

        card.add(box)
        return combo

    def _sync_end_choices(self) -> None:
        """Bitmə siyahısını seçilmiş başlanğıcdan SONRAKI günlərlə doldurur.

        Mövcud seçim hələ də etibarlıdırsa SAXLANILIR — əks halda işçi
        başlanğıcı bir gün irəli sürüşdürəndə bitmə tarixi sükutla sıfırlanar
        və o, bunu yalnız sorğunu göndərdikdən sonra görərdi.
        """
        start_index = self._start.currentIndex()
        if start_index < 0:
            return

        previous = self._end.currentData()
        self._end.blockSignals(True)
        self._end.clear()
        for key, text in self._days[start_index:]:
            self._end.addItem(text, key)
        restored = self._end.findData(previous)
        self._end.setCurrentIndex(restored if restored >= 0 else 0)
        self._end.blockSignals(False)

    def _on_submit(self) -> None:
        start = self._start.currentData()
        end = self._end.currentData()
        if not start or not end:
            # Boş siyahı müdafiə xəttidir: sükutla bağlanmaq işçiyə "düymə
            # işləmir" hissi verərdi.
            self._hint.setText("Başlanğıc və bitmə tarixi seçilməlidir.")
            return
        self.submitted.emit(str(start), str(end))
        self.accept()


__all__ = ["AnnualLeaveInboxScreen", "AnnualLeaveRequestDialog"]
