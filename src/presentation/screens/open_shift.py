"""Açıq Növbə Bazarının admin widget-ləri (#16, kompasos11.md Faza 6).

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI FAYL, NİYƏ `group_c.py`-nin İÇİNDƏ DEYİL
──────────────────────────────────────────────────────────────────────────────
Bu iki widget YALNIZ Növbə Planlama ekranında işlədilir, lakin onun maketinə
aid DEYİL: açıq bazar Faza 6 ilə gələn ƏLAVƏDİR və mövcud "işçi × gün"
matrisinin qurulmasına toxunmur. Onları ayrı modulda saxlamaq həmin sərhədi
görünən edir — `ShiftPlanningScreen` yalnız kartı yerləşdirir və iki siqnalı
ötürür; matrisin öz kodu (`set_matrix`, `LEGEND`, şablonlar) dəyişmir.

──────────────────────────────────────────────────────────────────────────────
TARİX SEÇİMİ NİYƏ `QComboBox`-DİR, `QDateEdit` DEYİL
──────────────────────────────────────────────────────────────────────────────
İki səbəb:

  1. ROOT PARAMETRİ EKRANDA GÖRÜNÜR. Elan ən çox `OPEN_SHIFT_MAX_LEAD_DAYS`
     gün irəli üçün verilə bilər. Təqvim vidjeti admini istənilən tarixi
     seçməyə buraxar, sonra use case onu rədd edərdi — yəni səhvi ancaq
     düyməni basandan sonra öyrənərdi. Siyahı ancaq İCAZƏLİ günləri göstərir.
  2. DİZAYN SİSTEMİ. `qss.py` `QComboBox[variant="form"]` üçün kontrast
     yoxlanılmış rəng cütü saxlayır; `QDateEdit` üçün belə qayda YOXDUR və
     onu əlavə etmək `scripts/check_contrast.py`-a yeni cüt gətirərdi.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from src.presentation.i18n import tr
from src.presentation.widgets import metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.forms import field_label
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import (
    Card,
    Divider,
    body_label,
    muted_label,
    section_label,
    stretch,
    title_label,
)

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager


class OpenShiftMarketCard(QWidget):
    """Növbə Planlama ekranındakı "Açıq Növbə Bazarı" bölməsi.

    Signals:
        post_requested: `[Açıq Növbə Elan Et]` basıldı.
        cancel_requested: Sətrin `[Ləğv Et]` düyməsi (elan identifikatoru).
        release_requested: Tutulmuş sətrin `[Geri Ver]` düyməsi (OP-4).
    """

    post_requested = Signal()
    cancel_requested = Signal(str)
    #: DEEP-GAP OP-4 — tutulmuş elanı bazara qaytarır (elan id-si).
    release_requested = Signal(str)

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # VİZUAL FAZA #1 — KÖLGƏ VERİLMİR (4-cü bənd, ölçülmüş): 1,881,900 px²
        # sahə, ölçülmüş repaint: 13.91 ms (60fps büdcəsinin 83%-i) — siyahının
        # ən bahalısı. `OpenShiftMarketCard` tam-enli bazar panelidir.
        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        layout.addWidget(card)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(metrics.SPACE_MS)
        head_layout.addWidget(title_label("Açıq Növbə Bazarı", size=15))
        head_layout.addWidget(stretch())

        post = action_button("Açıq Növbə Elan Et")
        post.clicked.connect(self.post_requested)
        head_layout.addWidget(post)
        card.add(head)

        card.add(
            muted_label(
                "Elan edilmiş növbəni uyğun işçilər öz İşçi Ana Ekranından "
                "götürür — TƏSDİQ MƏRHƏLƏSİ YOXDUR, ilk götürən qazanır. "
                "Bu, Növbə Dəyişmə Sorğusundan ayrı axındır.",
                size=12,
            )
        )
        card.add(Divider())

        self._rows_layout = QVBoxLayout()
        self._rows_layout.setSpacing(8)
        holder = QWidget()
        holder.setLayout(self._rows_layout)
        card.add(holder)

        self._empty = muted_label("Hazırda açıq elan yoxdur.")
        card.add(self._empty)

        # ──────────────────────────────────────────────────────────────────
        # «TUTULMUŞ NÖVBƏLƏR» — MENECERİN GERİ YOLU (DEEP-GAP OP-4)
        # ──────────────────────────────────────────────────────────────────
        # `release_claim()` İKİ aktora icazə verir: növbəni tutan işçi VƏ
        # `can_manage_shifts` sahibi. İkinci qol yalnız kiosk ekranına
        # bağlansaydı ÇAĞIRILA BİLMƏZDİ — işçi işə çıxmayanda (xəstəxana,
        # telefonu söndürülüb) slotu menecer açmalıdır.
        #
        # Bölmə YALNIZ sətir olduqda görünür: tutulmuş növbəsi olmayan
        # mağazada boş başlıq «burada nəsə olmalıydı» sualı yaradardı.
        self._claimed_section = QWidget()
        claimed_layout = QVBoxLayout(self._claimed_section)
        claimed_layout.setContentsMargins(0, 0, 0, 0)
        claimed_layout.setSpacing(8)
        claimed_layout.addWidget(Divider())
        claimed_layout.addWidget(section_label("Tutulmuş növbələr"))
        self._claimed_rows_layout = QVBoxLayout()
        self._claimed_rows_layout.setSpacing(8)
        claimed_holder = QWidget()
        claimed_holder.setLayout(self._claimed_rows_layout)
        claimed_layout.addWidget(claimed_holder)
        self._claimed_section.setVisible(False)
        card.add(self._claimed_section)

    def set_postings(self, rows: list[dict[str, str]]) -> None:
        """Açıq elanları göstərir.

        Args:
            rows: `id`, `date`, `work_mode`, `store` açarları olan sözlüklər.
                Açarlar HƏM maket (`preview_screens`), HƏM canlı yol
                (`controllers/open_shift.py`) üçün EYNİDİR — CLAUDE.md §6.
        """
        clear_layout(self._rows_layout)
        self._empty.setVisible(not rows)

        for row in rows:
            self._rows_layout.addWidget(self._build_row(row))

    def set_claimed(self, rows: list[dict[str, str]]) -> None:
        """Tutulmuş, hələ baş verməmiş növbələr (DEEP-GAP OP-4).

        Args:
            rows: `id`, `date`, `work_mode`, `store`, `employee` açarları.
                İlk dördü açıq elanlarla EYNİDİR; `employee` YALNIZ burada var,
                çünki menecer «kimin növbəsini geri verirəm?» sualının cavabını
                GÖRMƏLİDİR — açıq elanda isə sahib YOXDUR.
        """
        clear_layout(self._claimed_rows_layout)
        self._claimed_section.setVisible(bool(rows))
        for row in rows:
            self._claimed_rows_layout.addWidget(self._build_claimed_row(row))

    def _build_claimed_row(self, row: dict[str, str]) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(metrics.SPACE_MS)

        layout.addWidget(body_label(row["date"], size=13, wrap=False))
        layout.addWidget(
            muted_label(f"{row['work_mode']} · {row['store']} · {row.get('employee', '')}", size=12)
        )
        layout.addWidget(stretch())

        posting_id = row["id"]
        # «Ləğv Et»DƏN FƏRQLİ: bu, elanı YOX ETMİR, onu bazara QAYTARIR —
        # ona görə `danger` variantı VERİLMİR (rəng nəticəni bildirir).
        release = secondary_button("Geri Ver")
        release.clicked.connect(lambda _=False, key=posting_id: self.release_requested.emit(key))
        layout.addWidget(release)
        return container

    def _build_row(self, row: dict[str, str]) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(metrics.SPACE_MS)

        layout.addWidget(body_label(row["date"], size=13, wrap=False))
        layout.addWidget(muted_label(f"{row['work_mode']} · {row['store']}", size=12))
        layout.addWidget(stretch())

        posting_id = row["id"]
        cancel = secondary_button(tr("common.cancel"))
        cancel.setProperty("variant", "danger")
        cancel.clicked.connect(lambda _=False, key=posting_id: self.cancel_requested.emit(key))
        layout.addWidget(cancel)
        return container


class OpenShiftPostDialog(QDialog):
    """`[Açıq Növbə Elan Et]` forması — mağaza, tarix və iş rejimi.

    Signals:
        submitted: (mağaza id, tarix ISO formatında, iş rejimi id).

    Dialoq HEÇ NƏ YOXLAMIR: mövcudluq, tarix hüdudu və slot təkrarı
    `OpenShiftMarketUseCase`-dədir. Burada yalnız BOŞ seçim bloklanır —
    onsuz siqnal mənasız boş sətirlə gedərdi.
    """

    submitted = Signal(str, str, str)

    def __init__(
        self,
        theme: ThemeManager,
        *,
        stores: list[tuple[str, str]],
        days: list[tuple[str, str]],
        work_modes: list[tuple[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("Açıq Növbə Elan Et")
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # VİZUAL FAZA #1 — dialoqun BÜTÖV məzmun kartı, BİR dəfə qurulur.
        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING, shadow=True)
        layout.addWidget(card)
        card.add(title_label("Açıq Növbə Elan Et", size=19))
        card.add(
            muted_label(
                "Elan dərhal işçilərin ekranında görünür və ilk götürən onu "
                "qazanır. Təsdiq mərhələsi yoxdur.",
                size=12,
            )
        )
        card.add(Divider())

        self._stores = self._build_combo(card, "Mağaza", stores)
        self._days = self._build_combo(card, "Tarix", days)
        self._modes = self._build_combo(card, "İş rejimi (növbə şablonu)", work_modes)

        self._hint = muted_label("")
        card.add(self._hint)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(metrics.SPACE_MS)
        buttons_layout.addWidget(stretch())

        cancel = secondary_button(tr("common.decline"))
        cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel)

        submit = action_button("Elan Et")
        submit.clicked.connect(self._on_submit)
        buttons_layout.addWidget(submit)
        card.add(buttons)

        submit.setDefault(True)
        submit.setAutoDefault(True)
        cancel.setAutoDefault(False)

        # Fokus sırası vizual sıra ilə: mağaza → tarix → rejim → düymələr.
        QWidget.setTabOrder(self._stores, self._days)
        QWidget.setTabOrder(self._days, self._modes)
        QWidget.setTabOrder(self._modes, cancel)
        QWidget.setTabOrder(cancel, submit)

    def _build_combo(self, card: Card, label: str, items: list[tuple[str, str]]) -> QComboBox:
        box = QWidget()
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(8)
        box_layout.addWidget(field_label(label))

        combo = QComboBox()
        combo.setProperty("variant", "form")
        for key, text in items:
            # Dəyər `userData`-dadır: göstərilən mətn Azərbaycan dilindədir və
            # identifikatoru mətndən geri çıxarmaq mümkün olmamalıdır.
            combo.addItem(text, key)
        box_layout.addWidget(combo)

        card.add(box)
        return combo

    def _on_submit(self) -> None:
        store_id = self._stores.currentData()
        day = self._days.currentData()
        mode_id = self._modes.currentData()
        if not store_id or not day or not mode_id:
            # Boş siyahı real haldır: kataloqda aktiv iş rejimi olmaya bilər.
            # Sükutla bağlanmaq admini "düymə işləmir" nəticəsinə gətirərdi.
            self._hint.setText("Mağaza, tarix və iş rejimi seçilməlidir.")
            return
        self.submitted.emit(str(store_id), str(day), str(mode_id))
        self.accept()


__all__ = ["OpenShiftMarketCard", "OpenShiftPostDialog"]
