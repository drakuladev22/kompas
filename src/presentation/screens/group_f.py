"""Qrup F — tapşırıq, satış xalları və etirazlar — Faza 4.2.

Maket: "KompasOS - Qrup F.dc.html", ekranlar 24–27.

    24  Task & Workflow Paneli (kanban)
    25  Satış Xalları və Mükafatlar
    26  Cərimə Etirazı — işçi tərəfi (+ HR tərəfi, aşağıda)
    27  "Təyin Olunmamış / Şübhəli Satışlar" növbəsi

──────────────────────────────────────────────────────────────────────────────
26-cı EKRANIN HR TƏRƏFİ
──────────────────────────────────────────────────────────────────────────────
Maket bu ekranın YALNIZ işçi tərəfini çəkib. Spesifikasiya isə hər iki tərəfi
tələb edir ("işçi tərəfi … və HR_Admin tərəfi, Qəbul/Rədd + səbəb"). Ona görə
`FineAppealInboxScreen` maketdəki vizual dili (eyni kart, eyni nişanlar)
istifadə edərək HR görünüşünü verir — yeni bir üslub icad etmədən.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.presentation.screens.base import Screen
from src.presentation.widgets import icons, metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.charts import Meter
from src.presentation.widgets.data_table import Column, DataTable
from src.presentation.widgets.forms import FormField, field_label
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import (
    Card,
    Chip,
    ChipTone,
    Divider,
    body_label,
    mono_label,
    muted_label,
    plain_label,
    stretch,
    title_label,
)

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager


# --------------------------------------------------------------------------- #
# 24 — Task & Workflow Paneli
# --------------------------------------------------------------------------- #


class TaskCard(Card):
    """Kanban kartı.

    Signals:
        approved / rejected: `task_id` — yalnız "Nəzərdən Keçirilir" sütununda.
    """

    approved = Signal(str)
    rejected = Signal(str)

    def __init__(
        self,
        task: dict[str, str],
        theme: ThemeManager,
        *,
        reviewable: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(padding=16, spacing=8, parent=parent)
        task_id = task.get("id", "")

        self.add(title_label(task.get("title", ""), size=14))

        description = task.get("description", "")
        if description:
            self.add(muted_label(description))

        if task.get("evidence"):
            # Sübut şəkli — kiçik önizləmə nişanı (faktiki şəkil sonradan
            # `QPixmap` ilə əvəz olunur; burada yer tutucu göstərilir).
            evidence = QWidget()
            evidence_layout = QHBoxLayout(evidence)
            evidence_layout.setContentsMargins(0, 0, 0, 0)
            evidence_layout.setSpacing(8)
            glyph = plain_label()
            glyph.setPixmap(icons.render("image", theme.color("--color-text-muted"), size=15))
            evidence_layout.addWidget(glyph)
            evidence_layout.addWidget(muted_label(task["evidence"]))
            evidence_layout.addStretch(1)
            self.add(evidence)

        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(8)
        footer_layout.addWidget(muted_label(task.get("assignee", "")))
        footer_layout.addWidget(stretch())
        footer_layout.addWidget(mono_label(task.get("due", ""), muted=True))
        self.add(footer)

        status = task.get("status_text", "")
        if status:
            tone: ChipTone = "success" if "Təsdiq" in status else "danger"
            self.add(Chip(status, tone))

        if reviewable:
            self.add(Divider())
            actions = QWidget()
            actions_layout = QHBoxLayout(actions)
            actions_layout.setContentsMargins(0, 0, 0, 0)
            actions_layout.setSpacing(8)

            reject = secondary_button("Rədd Et")
            reject.clicked.connect(lambda: self.rejected.emit(task_id))
            actions_layout.addWidget(reject)

            approve = action_button("Təsdiqlə")
            approve.clicked.connect(lambda: self.approved.emit(task_id))
            actions_layout.addWidget(approve)
            self.add(actions)


class TasksScreen(Screen):
    """Kanban: Açıq / Nəzərdən Keçirilir / Tamamlandı.

    Signals:
        create_requested: "Yeni Tapşırıq".
        approved / rejected: `task_id`.
    """

    create_requested = Signal()
    approved = Signal(str)
    rejected = Signal(str)

    COLUMNS: Final = (
        ("open", "Açıq"),
        ("review", "Nəzərdən Keçirilir"),
        ("done", "Tamamlandı"),
    )

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)
        self._column_layouts: dict[str, QVBoxLayout] = {}
        self._column_counts: dict[str, QLabel] = {}

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        self._summary = muted_label("")
        toolbar_layout.addWidget(self._summary)
        toolbar_layout.addWidget(stretch())
        create = action_button(
            "Yeni Tapşırıq",
            icon_name="plus",
            icon_color=theme.color("--color-action-text"),
        )
        create.clicked.connect(self.create_requested)
        toolbar_layout.addWidget(create)
        self.add(toolbar)

        board = QWidget()
        board_layout = QHBoxLayout(board)
        board_layout.setContentsMargins(0, 0, 0, 0)
        board_layout.setSpacing(metrics.CARD_SPACING)

        for key, title in self.COLUMNS:
            board_layout.addWidget(self._build_column(key, title), 1)
        self.add(board)

    def _build_column(self, key: str, title: str) -> QWidget:
        column = QWidget()
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(12)
        head_layout.addWidget(title_label(title, size=15))
        count = Chip("0", "neutral")
        self._column_counts[key] = count
        head_layout.addWidget(count)
        head_layout.addWidget(stretch())
        layout.addWidget(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        host = QWidget()
        cards_layout = QVBoxLayout(host)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(12)
        cards_layout.addStretch(1)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)

        self._column_layouts[key] = cards_layout
        return column

    def set_summary(self, text: str) -> None:
        self._summary.setText(text)

    def set_tasks(self, column: str, tasks: list[dict[str, str]]) -> None:
        layout = self._column_layouts[column]
        clear_layout(layout, keep_last=1)

        self._column_counts[column].setText(str(len(tasks)))

        for task in tasks:
            card = TaskCard(task, self.theme, reviewable=column == "review")
            card.approved.connect(self.approved)
            card.rejected.connect(self.rejected)
            layout.insertWidget(layout.count() - 1, card)
        self.show_content()


# --------------------------------------------------------------------------- #
# 25 — Satış Xalları və Mükafatlar
# --------------------------------------------------------------------------- #


class SalesPointsScreen(Screen):
    """Xal balansı, tarixçə və mükafat kataloqu.

    Signals:
        appeal_requested: Etiraz edilən xal sətrinin `entry_id`-si.
        reward_requested: Mükafatın `reward_id`-si.
    """

    appeal_requested = Signal(str)
    reward_requested = Signal(str)

    _HISTORY_TONES: Final[dict[str, ChipTone]] = {
        "Təsdiqli": "success",
        "Gözləyir": "warning",
        "Geri alınıb": "danger",
    }

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)

        # ------------------------------ balans ------------------------------ #
        summary = QWidget()
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(metrics.CARD_SPACING)

        self._balance = Card(padding=20, spacing=8)
        self._balance.add(muted_label("Cari balans"))
        self._balance_value = title_label("0", size=32)
        self._balance.add(self._balance_value)
        self._balance_delta = muted_label("")
        self._balance.add(self._balance_delta)
        summary_layout.addWidget(self._balance, 1)

        self._next_reward = Card(padding=20, spacing=12)
        self._next_reward.add(muted_label("Növbəti mükafat"))
        self._next_reward_value = title_label("—", size=22)
        self._next_reward.add(self._next_reward_value)
        self._reward_meter = Meter(theme)
        self._next_reward.add(self._reward_meter)
        summary_layout.addWidget(self._next_reward, 1)

        self._rank = Card(padding=20, spacing=8)
        self._rank.add(muted_label("Filial reytinqi"))
        self._rank_value = title_label("—", size=22)
        self._rank.add(self._rank_value)
        self._rank.body().addStretch(1)
        summary_layout.addWidget(self._rank, 1)
        self.add(summary)

        # ----------------------------- tarixçə ------------------------------ #
        history_head = QWidget()
        history_head_layout = QHBoxLayout(history_head)
        history_head_layout.setContentsMargins(0, 0, 0, 0)
        history_head_layout.setSpacing(12)
        history_head_layout.addWidget(title_label("Xal tarixçəsi", size=15))
        self._history_period = muted_label("")
        history_head_layout.addWidget(self._history_period)
        history_head_layout.addWidget(stretch())
        self.add(history_head)

        self._history = DataTable(
            [
                Column("Tarix", 110, mono=True),
                Column("Səbəb"),
                Column("Vəziyyət", 160),
                Column("Xal", 100),
                # Etiraz sütunu — sətir-səviyyəli düymə (bax `set_history`).
                Column("Etiraz", 120),
            ],
            theme,
        )
        self.add(self._history)

        # ETİRAZ DÜYMƏSİ SƏTİRDƏDİR, EKRANDA DEYİL.
        #
        # Əvvəl ekranın altında TƏK bir «Etiraz Et» düyməsi vardı və o,
        # arqumentsiz siqnal yayırdı — yəni «hansı xal sətrinə etiraz?» sualı
        # cavabsız qalırdı. `SalesPointsUseCase.open_dispute` isə məhz
        # `entry_id` tələb edir, ona görə düymə heç vaxt bağlana bilməzdi.
        # Sətir-səviyyəli düymə həm sualı həll edir, həm də 72 saatlıq
        # pəncərəni sətir-sətir göstərməyə imkan verir.
        self.add(
            muted_label(
                "Xalın düzgün hesablanmadığını düşünürsünüzsə həmin sətirdəki "
                "«Etiraz» düyməsini basın (72 saat ərzində)."
            )
        )

        # ---------------------------- mükafatlar ---------------------------- #
        self.add(title_label("Mükafat kataloqu", size=15))
        self._catalog = QWidget()
        self._catalog_layout = QHBoxLayout(self._catalog)
        self._catalog_layout.setContentsMargins(0, 0, 0, 0)
        self._catalog_layout.setSpacing(metrics.CARD_SPACING)
        self.add(self._catalog)
        self.body().addStretch(1)

    def set_balance(
        self,
        balance: int,
        *,
        monthly_delta: int,
        to_next_reward: int,
        next_reward_cost: int,
        rank_text: str,
    ) -> None:
        self._balance_value.setText(f"{balance:,}".replace(",", " "))
        sign = "+" if monthly_delta >= 0 else ""
        self._balance_delta.setText(f"Bu ay {sign}{monthly_delta} xal")
        self._next_reward_value.setText(f"{to_next_reward} xal qalıb")
        self._reward_meter.set_ratio(balance / next_reward_cost if next_reward_cost else 0.0)
        self._rank_value.setText(rank_text)
        self.show_content()

    def set_history(self, entries: list[dict[str, str]], *, period: str) -> None:
        self._history_period.setText(period)
        self._history.clear()

        for entry in entries:
            status = entry.get("status", "")
            points = entry.get("points", "")
            points_label = mono_label(points)
            # Mənfi xal qırmızı, müsbət yaşıl — işarə ilə BİRLİKDƏ, yəni
            # rəng tək daşıyıcı deyil.
            token = (
                "--color-danger"
                if points.startswith("−") or points.startswith("-")
                else "--color-success"
            )
            points_label.setStyleSheet(f"color: {self.theme.color(token)};")

            # Etiraz YALNIZ pəncərəsi açıq sətirdə mümkündür; `can_appeal`
            # açarını oxu yolu hesablayır (72 saatlıq qayda domendədir və
            # ekran onu TƏKRAR HESABLAMIR — iki mənbə sükutla ayrılardı).
            entry_id = entry.get("entry_id", "")
            if entry.get("can_appeal") == "1" and entry_id:
                action: Any = secondary_button("Etiraz")
                action.setProperty("compact", "true")
                action.clicked.connect(
                    lambda _=False, key=entry_id: self.appeal_requested.emit(key)
                )
            else:
                action = muted_label("—")

            self._history.add_row(
                [
                    mono_label(entry.get("date", "")),
                    entry.get("reason", ""),
                    Chip(status, self._HISTORY_TONES.get(status, "neutral")),
                    points_label,
                    action,
                ]
            )

    def set_catalog(self, rewards: list[dict[str, str]], *, balance: int) -> None:
        """`rewards`: name, cost (int mətn olaraq)."""
        clear_layout(self._catalog_layout)

        for reward in rewards:
            cost = int(reward["cost"])
            card = Card(padding=20, spacing=12)

            thumbnail = plain_label()
            thumbnail.setFixedHeight(72)
            thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumbnail.setPixmap(
                icons.render("star", self.theme.color("--color-brand-amber"), size=30)
            )
            thumbnail.setStyleSheet(
                f"background-color: {self.theme.color('--color-neutral-bg')};border-radius: 10px;"
            )
            card.add(thumbnail)

            card.add(title_label(reward["name"], size=15))
            card.add(muted_label(f"{cost} xal"))

            affordable = balance >= cost
            if affordable:
                button = action_button("Al")
                reward_id = reward.get("id", "")
                button.clicked.connect(
                    lambda _=False, key=reward_id: self.reward_requested.emit(key)
                )
            else:
                # "Çatmır" düyməsi söndürülür — basılabilən görünüb heç nə
                # etməyən düymə istifadəçini çaşdırardı.
                button = action_button("Çatmır")
                button.setEnabled(False)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            card.add(button)

            self._catalog_layout.addWidget(card, 1)
        self._catalog_layout.addStretch(1)


# --------------------------------------------------------------------------- #
# 26 — Cərimə Etirazı (işçi tərəfi)
# --------------------------------------------------------------------------- #


class FineAppealScreen(Screen):
    """İşçinin cərimə tarixçəsi + yeni etiraz forması.

    Signals:
        appeal_started: `fine_id`.
        appeal_submitted: Forma məlumatı.
    """

    appeal_started = Signal(str)
    appeal_submitted = Signal(dict)

    _TONES: Final[dict[str, ChipTone]] = {
        "Etiraz baxılır": "warning",
        "Ləğv edilib": "success",
        "Təsdiqlənib": "neutral",
    }

    def __init__(
        self,
        theme: ThemeManager,
        *,
        reasons: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(theme, parent=parent)

        summary = QWidget()
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(metrics.CARD_SPACING)

        self._month_total = Card(padding=20, spacing=8)
        self._month_total.add(muted_label("Bu ay"))
        self._month_total_value = title_label("—", size=26)
        self._month_total.add(self._month_total_value)
        summary_layout.addWidget(self._month_total, 1)

        self._open_appeals = Card(padding=20, spacing=8)
        self._open_appeals.add(muted_label("Açıq etiraz"))
        self._open_appeals_value = title_label("0", size=26)
        self._open_appeals.add(self._open_appeals_value)
        summary_layout.addWidget(self._open_appeals, 1)
        summary_layout.addWidget(stretch(), 2)
        self.add(summary)

        self.add(title_label("Cərimə tarixçəm", size=15))

        self._history_layout = QVBoxLayout()
        self._history_layout.setSpacing(12)
        history_host = QWidget()
        history_host.setLayout(self._history_layout)
        self.add(history_host)

        self.add(muted_label("Etiraz müddəti cərimə yazıldıqdan sonra 3 gündür."))

        self.add(self._build_form(reasons))
        self.body().addStretch(1)

    def _build_form(self, reasons: list[str]) -> Card:
        card = Card(padding=20, spacing=16)
        self._form_card = card

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(12)
        head_layout.addWidget(title_label("Yeni etiraz", size=15))
        self._form_subject = muted_label("")
        head_layout.addWidget(self._form_subject)
        head_layout.addWidget(stretch())
        card.add(head)
        card.add(Divider())

        self._reason = QComboBox()
        self._reason.setProperty("variant", "form")
        self._reason.addItems(reasons)
        card.add(FormField("Etiraz səbəbi", widget=self._reason))

        explanation_box = QWidget()
        explanation_layout = QVBoxLayout(explanation_box)
        explanation_layout.setContentsMargins(0, 0, 0, 0)
        explanation_layout.setSpacing(8)
        explanation_layout.addWidget(field_label("İzah"))
        self._explanation = QPlainTextEdit()
        self._explanation.setPlaceholderText("Nə baş verdiyini qısa izah edin.")
        self._explanation.setFixedHeight(96)
        explanation_layout.addWidget(self._explanation)
        self._explanation_error = plain_label()
        self._explanation_error.setProperty("variant", "danger-text")
        self._explanation_error.setVisible(False)
        explanation_layout.addWidget(self._explanation_error)
        card.add(explanation_box)

        from src.presentation.screens.group_b import PhotoDropZone  # noqa: PLC0415

        document_box = QWidget()
        document_layout = QVBoxLayout(document_box)
        document_layout.setContentsMargins(0, 0, 0, 0)
        document_layout.setSpacing(8)
        document_layout.addWidget(field_label("Sənəd (istəyə görə)"))
        self._document = PhotoDropZone(self.theme)
        document_layout.addWidget(self._document)
        card.add(document_box)

        submit_row = QWidget()
        submit_layout = QHBoxLayout(submit_row)
        submit_layout.setContentsMargins(0, 0, 0, 0)
        submit_layout.addWidget(stretch())
        submit = action_button("Etirazı Göndər")
        submit.clicked.connect(self._on_submit)
        submit_layout.addWidget(submit)
        card.add(submit_row)

        card.setVisible(False)
        return card

    def set_summary(self, *, month_total: str, open_appeals: int) -> None:
        self._month_total_value.setText(month_total)
        self._open_appeals_value.setText(str(open_appeals))
        self.show_content()

    def set_history(self, fines: list[dict[str, str]]) -> None:
        clear_layout(self._history_layout)

        for fine in fines:
            card = Card(padding=16, spacing=8)
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)

            text_box = QWidget()
            text_layout = QVBoxLayout(text_box)
            text_layout.setContentsMargins(0, 0, 0, 0)
            text_layout.setSpacing(4)
            text_layout.addWidget(title_label(fine.get("type", ""), size=14))
            text_layout.addWidget(muted_label(fine.get("meta", "")))
            layout.addWidget(text_box)
            layout.addWidget(stretch())

            layout.addWidget(mono_label(fine.get("amount", "")))

            status = fine.get("status", "")
            if status:
                layout.addWidget(Chip(status, self._TONES.get(status, "neutral")))

            if fine.get("appealable") == "1":
                button = secondary_button("Etiraz Et")
                # Mətn dövrə DAXİLİNDƏ hesablanır: `lambda` yalnız hazır
                # sətri tutur, beləliklə hər düymə öz cəriməsinə bağlanır.
                subject = (
                    f"{fine.get('type', '')} — {fine.get('meta', '')} · {fine.get('amount', '')}"
                )
                fine_id = fine.get("id", "")
                button.clicked.connect(
                    lambda _=False, fid=fine_id, text=subject: self.start_appeal(fid, text)
                )
                layout.addWidget(button)

            card.add(row)
            self._history_layout.addWidget(card)

    def start_appeal(self, fine_id: str, subject: str) -> None:
        """Etiraz formasını açır və hansı cərimə üçün olduğunu göstərir."""
        self._current_fine = fine_id
        self._form_subject.setText(subject)
        self._form_card.setVisible(True)
        self.appeal_started.emit(fine_id)

    def _on_submit(self) -> None:
        explanation = self._explanation.toPlainText().strip()
        if not explanation:
            self._explanation_error.setText("İzah məcburidir")
            self._explanation_error.setVisible(True)
            return
        self._explanation_error.setVisible(False)

        self.appeal_submitted.emit(
            {
                "fine_id": getattr(self, "_current_fine", ""),
                "reason": self._reason.currentText(),
                "explanation": explanation,
                "document": self._document.file_path,
            }
        )
        self._form_card.setVisible(False)
        self._explanation.clear()
        self._document.clear()


class FineAppealInboxScreen(Screen):
    """HR_Admin tərəfi — gələn etirazlar, Qəbul/Rədd + səbəb.

    Signals:
        accepted / rejected: (`appeal_id`, səbəb).
    """

    accepted = Signal(str, str)
    rejected = Signal(str, str)

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)
        self._layout_host = QVBoxLayout()
        self._layout_host.setSpacing(12)
        host = QWidget()
        host.setLayout(self._layout_host)
        self.add(host)
        self.body().addStretch(1)

    def set_appeals(self, appeals: list[dict[str, str]]) -> None:
        clear_layout(self._layout_host)

        if not appeals:
            self.show_empty(
                icon_name="check_circle",
                title="Gözləyən etiraz yoxdur",
                message="Bütün etirazlar cavablandırılıb.",
            )
            return

        for appeal in appeals:
            card = Card(padding=20, spacing=12)

            head = QWidget()
            head_layout = QHBoxLayout(head)
            head_layout.setContentsMargins(0, 0, 0, 0)
            head_layout.setSpacing(12)
            head_layout.addWidget(title_label(appeal.get("employee", ""), size=15))
            head_layout.addWidget(Chip(appeal.get("fine_type", ""), "neutral"))
            head_layout.addWidget(stretch())
            head_layout.addWidget(mono_label(appeal.get("amount", "")))
            card.add(head)

            card.add(muted_label(appeal.get("meta", "")))
            card.add(body_label(appeal.get("explanation", ""), size=13))

            if appeal.get("document"):
                card.add(muted_label(f"Sənəd: {appeal['document']}"))

            card.add(Divider())

            reason = QPlainTextEdit()
            reason.setPlaceholderText("Qərarın səbəbi (işçiyə göndərilir)")
            reason.setFixedHeight(64)
            card.add(reason)

            actions = QWidget()
            actions_layout = QHBoxLayout(actions)
            actions_layout.setContentsMargins(0, 0, 0, 0)
            actions_layout.setSpacing(12)
            actions_layout.addWidget(stretch())

            appeal_id = appeal.get("id", "")
            reject = secondary_button("Rədd Et")
            reject.clicked.connect(
                lambda _=False, aid=appeal_id, box=reason: self.rejected.emit(
                    aid, box.toPlainText()
                )
            )
            actions_layout.addWidget(reject)

            accept = action_button("Qəbul Et")
            accept.clicked.connect(
                lambda _=False, aid=appeal_id, box=reason: self.accepted.emit(
                    aid, box.toPlainText()
                )
            )
            actions_layout.addWidget(accept)
            card.add(actions)

            self._layout_host.addWidget(card)
        self.show_content()


# --------------------------------------------------------------------------- #
# 27 — Şübhəli / Təyin Olunmamış Satışlar
# --------------------------------------------------------------------------- #


class UnassignedSalesScreen(Screen):
    """1C-dən gələn, işçiyə bağlanmayan satışlar.

    Signals:
        rematch_requested: "Yenidən Uyğunlaşdır".
        assigned: (çek nömrəsi, işçi adı).
        bulk_assign_requested: Seçilmiş sətirlər.
    """

    rematch_requested = Signal()
    assigned = Signal(str, str)
    bulk_assign_requested = Signal(list)

    #: Bu faizdən aşağı uyğunluq "zəif" sayılır və xəbərdarlıq tonunda göstərilir.
    #:
    #: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits.
    #: ERP_MATCH_LOW_CONFIDENCE_PERCENT` (seed: migrations/035). Canlı dəyəri
    #: kontroller `set_low_confidence_threshold()` ilə ötürür; ekran bazanı
    #: TANIMIR (CLAUDE.md §6: ekran yalnız `theme` alır və setter təqdim edir),
    #: ona görə sabit maket/önizləmə yolu üçün yerində qalır.
    FALLBACK_LOW_CONFIDENCE_PERCENT: Final = int(
        DEFAULT_LIMITS[SystemLimitKey.ERP_MATCH_LOW_CONFIDENCE_PERCENT]
    )

    def __init__(
        self,
        theme: ThemeManager,
        *,
        employees: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(theme, parent=parent)
        self._employees = employees
        self._combos: dict[str, QComboBox] = {}
        #: Qüvvədə olan hədd — kontroller canlı dəyəri yazana qədər fallback.
        self._low_confidence_percent = self.FALLBACK_LOW_CONFIDENCE_PERCENT

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.addWidget(muted_label("1C-dən gələn, işçiyə bağlanmayan satışlar"))
        toolbar_layout.addWidget(stretch())
        rematch = secondary_button("Yenidən Uyğunlaşdır")
        rematch.clicked.connect(self.rematch_requested)
        toolbar_layout.addWidget(rematch)
        self.add(toolbar)

        # Xal hesablanmasının DAYANDIĞINI açıq yazmaq vacibdir — əks halda
        # işçilər "xalım gəlmir" deyə dəstəyə müraciət edərdi.
        self._banner = Card(padding=16, spacing=8)
        self._banner_text = body_label("", size=13)
        self._banner.add(self._banner_text)
        self.add(self._banner)

        self._table = DataTable(
            [
                Column("Çek", 100, mono=True),
                Column("Tarix", 150, mono=True),
                Column("Məbləğ", 120),
                Column("1C təklifi", 180),
                Column("Uyğunluq", 120),
                Column("İşçi təyin et"),
            ],
            theme,
            footnote=(
                "Təyinat audit jurnalına yazılır və işçinin xal balansına dərhal təsir edir."
            ),
        )
        self.add(self._table)

        bulk_row = QWidget()
        bulk_layout = QHBoxLayout(bulk_row)
        bulk_layout.setContentsMargins(0, 0, 0, 0)
        bulk_layout.addWidget(stretch())
        bulk = action_button("Seçilmişləri Toplu Təyin Et")
        bulk.clicked.connect(lambda: self.bulk_assign_requested.emit(self.selections()))
        bulk_layout.addWidget(bulk)
        self.add(bulk_row)

    def set_low_confidence_threshold(self, percent: int) -> None:
        """Xəbərdarlıq rənginin həddini ROOT dəyəri ilə əvəzləyir.

        `set_sales`-dan ƏVVƏL çağırılmalıdır (kontroller bunu edir): sətirlər
        artıq çəkilibsə rəng yenidən hesablanmır — cədvəl hər doldurmada
        onsuz da sıfırdan qurulur, ona görə ikinci bir yenidən-boyama yolu
        əlavə etmək lazımsız mürəkkəblik olardı.
        """
        self._low_confidence_percent = percent

    def set_sales(self, sales: list[dict[str, str]], *, total_amount: str) -> None:
        self._banner_text.setText(
            f"{len(sales)} satış işçiyə təyin edilməyib — xal hesablanması bu "
            f"sətirlər təyin olunana qədər dayandırılıb. Cəmi {total_amount}."
        )
        self._table.clear()
        self._combos.clear()

        if not sales:
            self.show_empty(
                icon_name="check_circle",
                title="Təyin olunmamış satış yoxdur",
                message="Bütün 1C satışları işçilərə bağlanıb.",
            )
            return

        for sale in sales:
            receipt = sale["receipt"]
            confidence = int(sale.get("confidence", "0"))

            confidence_label = mono_label(f"{confidence}%")
            if confidence < self._low_confidence_percent:
                confidence_label.setStyleSheet(f"color: {self.theme.color('--color-warning')};")

            combo = QComboBox()
            combo.setProperty("variant", "form")
            combo.addItem("İşçi seç")
            combo.addItems(self._employees)
            suggestion = sale.get("suggestion", "")
            if suggestion and suggestion in self._employees:
                combo.setCurrentText(suggestion)
            self._combos[receipt] = combo

            assign = secondary_button("Təyin Et")
            assign.clicked.connect(lambda _=False, r=receipt: self._on_assign(r))

            action_cell = QWidget()
            action_layout = QHBoxLayout(action_cell)
            action_layout.setContentsMargins(0, 0, 0, 0)
            action_layout.setSpacing(8)
            action_layout.addWidget(combo, 1)
            action_layout.addWidget(assign)

            self._table.add_row(
                [
                    mono_label(receipt),
                    mono_label(sale.get("date", "")),
                    mono_label(sale.get("amount", "")),
                    suggestion or muted_label("təklif yoxdur"),
                    confidence_label,
                    action_cell,
                ]
            )
        self.show_content()

    def _on_assign(self, receipt: str) -> None:
        combo = self._combos.get(receipt)
        if combo is None or combo.currentIndex() == 0:
            return
        self.assigned.emit(receipt, combo.currentText())

    def selections(self) -> list[tuple[str, str]]:
        """Seçilmiş (çek, işçi) cütləri — "İşçi seç" qalanlar buraxılır."""
        return [
            (receipt, combo.currentText())
            for receipt, combo in self._combos.items()
            if combo.currentIndex() > 0
        ]

    def table(self) -> DataTable:
        return self._table


__all__ = [
    "FineAppealInboxScreen",
    "FineAppealScreen",
    "SalesPointsScreen",
    "TaskCard",
    "TasksScreen",
    "UnassignedSalesScreen",
]
