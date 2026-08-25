"""Break-glass fövqəladə giriş ekranı — `v2backlog.md` Faza 5.4.

`transfer_requests.py` İLƏ EYNİ NAXIŞ (bax həmin faylın başlığı): ekran
yalnız `theme` alır, məlumat İKİ yoldan gəlir — maket (`preview_screens`) və
canlı yol (`controllers/break_glass.py`); ikisi EYNİ açarları işlədir
(CLAUDE.md §6).

Yeni QSS/rəng YOXDUR — `Card`, `DataTable`, `QComboBox[variant="form"]`,
`QLineEdit[variant="form"]`, `action_button`/`secondary_button` TƏKRAR
İSTİFADƏ olunur (`v2backlog.md` MƏRKƏZİ TƏLƏB #2).

──────────────────────────────────────────────────────────────────────────────
DÖRD BÖLMƏ, DÖRD AUDITORİYA — HAMISI BİR EKRANDA
──────────────────────────────────────────────────────────────────────────────
Ehtiyat-admin HEÇ BİR flag daşımadığı üçün ayrıca «ehtiyat-adminlar ekranı»
qurmaq olmazdı — onun gördüyü bölmələr REYESTR üzvlüyündən asılıdır və bu,
menyu səviyyəsində deyil, EKRAN səviyyəsində həll olunur:

* **Vəziyyət kartı** — hər kəs görür (görmək = səlahiyyət deyil: burada heç
  bir başqasının məlumatı YOXDUR, yalnız ÖZ reyestr vəziyyəti);
* **Sorğu forması** — yalnız AKTİV ehtiyat-admin görür;
* **Təsdiq növbəsi + aktiv səlahiyyətlər** — `can_approve_break_glass`
  daşıyanlar VƏ ya ehtiyat-adminlər (use case-in `_require_approver` qapısı);
* **Reyestr** — yalnız Root (`can_manage_break_glass`).

Bölmənin GİZLƏDİLMƏSİ boz/deaktiv ETMƏK DEYİL — kompasos-ui bənd 3: işləməyən
element ümumiyyətlə render olunmur. Kontroller hər bölmə üçün ayrıca
görünürlük bayrağı göndərir (`set_*_visible`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from src.domain.entities.break_glass import MIN_BREAK_GLASS_REASON_LENGTH
from src.presentation.screens.base import Screen, section_header
from src.presentation.widgets import metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.data_table import Column, DataTable
from src.presentation.widgets.forms import field_label
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import (
    Card,
    Divider,
    body_label,
    muted_label,
    stretch,
    title_label,
)

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager


class BreakGlassScreen(Screen):
    """Fövqəladə giriş — sorğu / təsdiq / reyestr, auditoriyaya görə bölməli.

    Signals:
        request_requested: `[Fövqəladə Giriş İstə]` (səbəb).
        approve_requested: Növbə sətrinin `[Təsdiqlə]` düyməsi (sorğu id).
        reject_requested: Növbə sətrinin `[Rədd Et]` düyməsi (sorğu id).
        revoke_grant_requested: Aktiv səlahiyyətin `[Dayandır]` düyməsi (id).
        designate_requested: Reyestrdəki `[Təyin Et]` düyməsi (işçi id).
        trustee_revoke_requested: Reyestr sətrinin `[Ləğv Et]` düyməsi (işçi id).
        refresh_requested: `[Yenilə]`.
    """

    request_requested = Signal(str)
    approve_requested = Signal(str)
    reject_requested = Signal(str)
    revoke_grant_requested = Signal(str)
    designate_requested = Signal(str)
    trustee_revoke_requested = Signal(str)
    refresh_requested = Signal()

    _PENDING_COLUMNS: ClassVar[list[Column]] = [
        Column("İstəyən"),
        Column("Səbəb"),
        Column("Soruşulub", 150, mono=True),
        Column("Pəncərə bitir", 150, mono=True),
        Column("Əməliyyat", 210),
    ]

    _ACTIVE_COLUMNS: ClassVar[list[Column]] = [
        Column("İşçi"),
        Column("Təsdiq edən"),
        Column("Başladı", 150, mono=True),
        Column("Bitir", 150, mono=True),
        Column("Əməliyyat", 130),
    ]

    _TRUSTEE_COLUMNS: ClassVar[list[Column]] = [
        Column("Ehtiyat-admin"),
        Column("Təyin edən"),
        Column("Təyin tarixi", 160, mono=True),
        Column("Əməliyyat", 130),
    ]

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)

        # ------------------------------ alət zolağı -------------------------- #
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(metrics.SPACE_MS)
        self._summary = muted_label("")
        toolbar_layout.addWidget(self._summary)
        toolbar_layout.addWidget(stretch())
        refresh = secondary_button("Yenilə")
        refresh.clicked.connect(self.refresh_requested)
        toolbar_layout.addWidget(refresh)
        self.add(toolbar)

        # ------------------------------ vəziyyət kartı ----------------------- #
        status_card = Card(
            padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING, shadow=True
        )
        # 19 = kart titulluğunun şkaladakı yeri — 17 şkaladan kənar idi
        # (`test_design_symmetry.py::test_off_grid_values_do_not_grow`).
        status_card.add(title_label("Fövqəladə Giriş (break-glass)", size=19))
        status_card.add(
            muted_label(
                "Root əlçatmaz olanda, ƏVVƏLCƏDƏN təyin edilmiş ehtiyat-admin "
                "ikinci-etibarlı şəxsin təsdiqi ilə vaxt-məhdud səlahiyyət alır. "
                "Hər addım audit jurnalına yazılır."
            )
        )
        self._identity_line = body_label("")
        status_card.add(self._identity_line)
        status_card.add(Divider())

        request_box = QWidget()
        request_layout = QVBoxLayout(request_box)
        request_layout.setContentsMargins(0, 0, 0, 0)
        request_layout.setSpacing(8)
        request_layout.addWidget(field_label("Səbəb — audit sənədidir, ətraflı yazın"))
        self._reason = QLineEdit()
        self._reason.setProperty("variant", "form")
        # GÖSTƏRİŞ, NÜMUNƏ DEYİL (bax `attrition_risk.py`-dakı eyni düzəliş).
        # Burada əlavə səbəb var: mətn AUDİT sənədidir və hazır nümunə
        # istifadəçini onu olduğu kimi göndərməyə sövq edərdi — audit sətri
        # isə HƏQİQİ səbəbi saxlamalıdır.
        self._reason.setPlaceholderText("Fövqəladə girişin səbəbini ətraflı yazın")
        request_layout.addWidget(self._reason)

        request_row = QWidget()
        request_row_layout = QHBoxLayout(request_row)
        request_row_layout.setContentsMargins(0, 0, 0, 0)
        request_row_layout.setSpacing(metrics.SPACE_MS)
        request_row_layout.addWidget(stretch())
        submit = action_button("Fövqəladə Giriş İstə")
        submit.clicked.connect(self._on_submit)
        request_row_layout.addWidget(submit)
        request_layout.addWidget(request_row)
        status_card.add(request_box)

        self._request_box = request_box
        self.add(status_card)

        # ------------------------------ təsdiq növbəsi ----------------------- #
        pending_section = QWidget()
        pending_layout = QVBoxLayout(pending_section)
        pending_layout.setContentsMargins(0, 0, 0, 0)
        pending_layout.setSpacing(metrics.CARD_CONTENT_SPACING)
        pending_layout.addWidget(
            section_header(
                "Təsdiq Gözləyən Sorğular",
                "İkinci-etibarlı şəxs qərar verir — özünü təsdiq qadağandır.",
            )
        )
        self._pending_host = QWidget()
        self._pending_layout = QVBoxLayout(self._pending_host)
        self._pending_layout.setContentsMargins(0, 0, 0, 0)
        self._pending_layout.setSpacing(0)
        pending_layout.addWidget(self._pending_host)
        self._pending_section = pending_section
        self.add(pending_section)

        # --------------------------- aktiv səlahiyyətlər --------------------- #
        active_section = QWidget()
        active_layout = QVBoxLayout(active_section)
        active_layout.setContentsMargins(0, 0, 0, 0)
        active_layout.setSpacing(metrics.CARD_CONTENT_SPACING)
        active_layout.addWidget(
            section_header(
                "Qüvvədə Olan Səlahiyyətlər",
                "Verilmiş təsdiqin hələ də qüvvədə olub-olmadığı buradan oxunur.",
            )
        )
        self._active_host = QWidget()
        self._active_layout = QVBoxLayout(self._active_host)
        self._active_layout.setContentsMargins(0, 0, 0, 0)
        self._active_layout.setSpacing(0)
        active_layout.addWidget(self._active_host)
        self._active_section = active_section
        self.add(active_section)

        # ------------------------------ reyestr ------------------------------ #
        registry_section = QWidget()
        registry_layout = QVBoxLayout(registry_section)
        registry_layout.setContentsMargins(0, 0, 0, 0)
        registry_layout.setSpacing(metrics.CARD_CONTENT_SPACING)
        registry_layout.addWidget(
            section_header(
                "Ehtiyat-Adminlər Reyestri",
                "Böhran anında ƏLAVƏ ETMƏK MÜMKÜN DEYİL — təyinat yalnız əvvəlcədən.",
            )
        )

        designate_row = QWidget()
        designate_layout = QHBoxLayout(designate_row)
        designate_layout.setContentsMargins(0, 0, 0, 0)
        designate_layout.setSpacing(metrics.SPACE_MS)
        self._employee_choice = QComboBox()
        self._employee_choice.setProperty("variant", "form")
        designate_layout.addWidget(self._employee_choice, 1)
        designate = action_button("Təyin Et")
        designate.clicked.connect(self._on_designate)
        designate_layout.addWidget(designate)
        registry_layout.addWidget(designate_row)

        self._trustee_host = QWidget()
        self._trustee_layout = QVBoxLayout(self._trustee_host)
        self._trustee_layout.setContentsMargins(0, 0, 0, 0)
        self._trustee_layout.setSpacing(0)
        registry_layout.addWidget(self._trustee_host)
        self._registry_section = registry_section
        self.add(registry_section)

    # ------------------------------ məlumat yolu ----------------------------- #

    def set_summary(self, text: str) -> None:
        """Alət zolağındakı qısa mesaj — əməliyyat nəticələri BURADA yaşayır."""
        self._summary.setText(text)

    def set_my_status(self, is_trustee: bool, grant_row: dict[str, str] | None) -> None:
        """Vəziyyət kartının şəxsi sətri.

        Açarlar maket (`preview_screens._break_glass`) ilə EYNİDİR:
        `status`, `reason`, `expires`.
        """
        if grant_row is not None:
            status = {
                "PENDING_APPROVAL": "Sorğunuz təsdiq gözləyir",
                "ACTIVE": "Fövqəladə səlahiyyətiniz QÜVVƏDƏDİR",
            }.get(grant_row.get("status", ""), grant_row.get("status", ""))
            expires = grant_row.get("expires", "")
            tail = f" · Bitmə: {expires}" if expires else ""
            reason = grant_row.get("reason", "")
            detail = f"Səbəb: {reason}" if reason else ""
            self._identity_line.setText(f"{status}{tail}. {detail}".strip())
            return
        if is_trustee:
            self._identity_line.setText(
                "Siz ehtiyat-admindirsiniz. Fövqəladə halda aşağıdan sorğu göndərin — "
                "ikinci-etibarlı şəxs təsdiqləyənə qədər səlahiyyət qüvvəyə minmir."
            )
        else:
            self._identity_line.setText(
                "Siz ehtiyat-admin deyilsiniz. Təyinatı yalnız Root, əvvəlcədən edir."
            )

    def set_request_form_visible(self, visible: bool) -> None:
        """Sorğu forması YALNIZ aktiv ehtiyat-admindirsinizsə render olunur."""
        self._request_box.setVisible(visible)

    def set_pending_visible(self, visible: bool) -> None:
        self._pending_section.setVisible(visible)

    def set_pending(self, rows: list[dict[str, str]]) -> None:
        """Açarlar `controllers/break_glass.py::_to_inbox_row` ilə EYNİDİR:
        `id`, `requester`, `reason`, `requested`, `window_end`."""
        clear_layout(self._pending_layout)
        if not rows:
            self._pending_layout.addWidget(muted_label("Təsdiq gözləyən sorğu yoxdur."))
            return
        table = DataTable(self._PENDING_COLUMNS, self.theme)
        for row in rows:
            table.add_row(self._pending_cells(row))
        self._pending_layout.addWidget(table)

    def set_active_visible(self, visible: bool) -> None:
        self._active_section.setVisible(visible)

    def set_active(self, rows: list[dict[str, str]]) -> None:
        """Açarlar `_to_active_row` ilə EYNİDİR: `id`, `employee`, `approver`,
        `started`, `expires`, `revokable` ("1"/"0")."""
        clear_layout(self._active_layout)
        if not rows:
            self._active_layout.addWidget(muted_label("Qüvvədə fövqəladə səlahiyyət yoxdur."))
            return
        table = DataTable(self._ACTIVE_COLUMNS, self.theme)
        for row in rows:
            table.add_row(self._active_cells(row))
        self._active_layout.addWidget(table)

    def set_registry(
        self,
        rows: list[dict[str, str]],
        *,
        can_manage: bool,
        employees: list[tuple[str, str]] | None = None,
    ) -> None:
        """Reyestr bölməsi — yalnız Root üçün tam; `can_manage=False` gizlədir.

        Args:
            rows: `_to_trustee_row` açarları: `employee_id`, `name`,
                `designated_by`, `designated_at`, `revokable`.
            employees: `(id, ad)` — təyinat siyahısı; yalnız `can_manage=True`
                ikəndir, çünki siyahı bütün aktiv işçiləri daşıyır.
        """
        self._registry_section.setVisible(can_manage)
        if not can_manage:
            return
        self._employee_choice.clear()
        for employee_id, name in employees or []:
            self._employee_choice.addItem(name, employee_id)

        clear_layout(self._trustee_layout)
        if not rows:
            self._trustee_layout.addWidget(
                muted_label("Reyestr boşdur — fövqəladə giriş heç kim üçün mümkün deyil.")
            )
            return
        table = DataTable(self._TRUSTEE_COLUMNS, self.theme)
        for row in rows:
            table.add_row(self._trustee_cells(row))
        self._trustee_layout.addWidget(table)

    # ------------------------------ düymə yolları ---------------------------- #

    def _on_submit(self) -> None:
        reason = self._reason.text().strip()
        # Səbəb həddi DOMENDƏN gälir (`MIN_BREAK_GLASS_REASON_LENGTH`) —
        # burada ikinci ədəd yazsaq, domen dəyişəndə ekran köhnə qaydada
        # qalardı (dialoq yalnız erkən rədd edir, faktiki qapı use case-dədir).
        if len(reason) < MIN_BREAK_GLASS_REASON_LENGTH:
            self.set_summary(
                f"Səbəb ən azı {MIN_BREAK_GLASS_REASON_LENGTH} simvol olmalıdır — "
                "bu, audit sənədidir."
            )
            return
        self.request_requested.emit(reason)
        self._reason.clear()

    def _on_designate(self) -> None:
        employee_id = self._employee_choice.currentData()
        if not employee_id:
            self.set_summary("Təyin ediləcək işçi seçilməyib.")
            return
        self.designate_requested.emit(str(employee_id))

    def _pending_cells(self, row: dict[str, str]) -> list[QWidget | str]:
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
            row.get("requester", ""),
            row.get("reason", ""),
            row.get("requested", ""),
            row.get("window_end", ""),
            actions,
        ]

    def _active_cells(self, row: dict[str, str]) -> list[QWidget | str]:
        cells: list[QWidget | str] = [
            row.get("employee", ""),
            row.get("approver", ""),
            row.get("started", ""),
            row.get("expires", ""),
        ]
        if row.get("revokable") == "1":
            stop = secondary_button("Dayandır")
            stop.setProperty("variant", "danger")
            key = row.get("id", "")
            stop.clicked.connect(lambda *_, k=key: self.revoke_grant_requested.emit(k))
            cells.append(stop)
        else:
            cells.append("")
        return cells

    def _trustee_cells(self, row: dict[str, str]) -> list[QWidget | str]:
        cells: list[QWidget | str] = [
            row.get("name", ""),
            row.get("designated_by", ""),
            row.get("designated_at", ""),
        ]
        if row.get("revokable") == "1":
            revoke = secondary_button("Ləğv Et")
            revoke.setProperty("variant", "danger")
            key = row.get("employee_id", "")
            revoke.clicked.connect(lambda *_, k=key: self.trustee_revoke_requested.emit(k))
            cells.append(revoke)
        else:
            cells.append("")
        return cells


__all__ = ["BreakGlassScreen"]
