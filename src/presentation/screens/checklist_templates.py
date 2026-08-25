"""Checklist bənd şablonları — `v2backlog.md` Faza 3.4 + 4.1, Root/HR idarə edir.

`CatalogScreen`/`CatalogEntryDialog` (`group_h.py`) İLƏ EYNİ dizayn dili
(toolbar + `DataTable` + `Card`+`shadow` dialoq) TƏKRAR İSTİFADƏ olunur
(`v2backlog.md` MƏRKƏZİ TƏLƏB #2) — LAKİN ORTAQ EKRAN SİNFİ DEYİL: üç
kataloqdan (İş Rejimi/Cərimə Növü/İcazə Növü) fərqli olaraq bu kataloqun
sətri "ad + bir dəyər" formasına SIĞMIR (`owner_type`/`owner_key`/
`position_no`/`is_blocking`/`photo_required`/`category` — altı sahə), ona
görə `CatalogEntryDialog`-u genişləndirmək əvəzinə YENİ, DAR dialoq yazılıb.

──────────────────────────────────────────────────────────────────────────────
İKİ DƏST, TƏK EKRAN — CHİP FİLTRİ İLƏ AYRILIR
──────────────────────────────────────────────────────────────────────────────
`ChecklistItemTemplateUseCase`-in ÖZÜ "TƏK ad-məkanı deyil, İKİ domenin ORTAQ
infrastrukturudur" deyir (`catalog_management.py` başlığı). Ekran bunu
`ShiftSwapScreen`-in "Gözləyən/Təsdiqlənən/Rədd edilən" `Chip` filtri ilə EYNİ
naxışla göstərir: `owner_type` seçimi SİYAHINI dəyişir, YENİ EKRAN AÇMIR —
iki ayrı ekran sinfi yazmaq eyni cədvəl/dialoq məntiqini iki dəfə təkrarlayardı.

──────────────────────────────────────────────────────────────────────────────
KATEQORİYA SAHƏSİ NİYƏ ŞƏRTLİDİR (`owner_type`-A GÖRƏ)
──────────────────────────────────────────────────────────────────────────────
`migrations/094`: `owner_type = OFFBOARDING` → `category` MƏCBURİDİR (üç
dəyərdən biri), `owner_type = FIELD_REPORT` → `category` MÜTLƏQ NULL (DB
CHECK, `chk_checklist_template_category_by_owner`). Dialoq bu sahəni
FIELD_REPORT seçilibsə ÜMUMİYYƏTLƏ GÖSTƏRMİR (boz/disabled DEYİL) —
"görmək = səlahiyyət" bənd 3-ün EYNİ prinsipi budəfə İCAZƏYƏ yox, DOMEN
VƏZİYYƏTİNƏ tətbiq olunur: mənasız sahəni göstərmək admin-i "bunu doldurmalı
idimmi?" sualı ilə yormazdı.

**QAPI SINIĞI (bu ekranın sənədləşdirdiyi tapıntı)** — `ChecklistItemTemplate.
__post_init__` (`domain/value_objects/catalogs.py`) bu OWNER_TYPE↔CATEGORY
uyğunluğunu YOXLAMIR, YALNIZ DB `CHECK`-i (migrations/094) məcbur edir.
CLAUDE.md bölmə 5-in "hər qayda İKİ yerdə" prinsipi burada BİR yerdədir —
əgər bu dialoqun client-side qadağası YAN keçilsə (məs. gələcəkdə başqa bir
yazı yolu əlavə olunsa), `save()` domen səviyyəsində yox, xam DB
`IntegrityError` ilə uğursuz olardı. Bu fayl (`presentation`) onu DÜZƏLDƏ
BİLMƏZ — `domain`-in işidir, mən yalnız client-side-da yan keçilməsinin
mümkün olmadığını təmin edirəm.

──────────────────────────────────────────────────────────────────────────────
`owner_key` NİYƏ OFFBOARDING-DƏ REDAKTƏ OLUNMUR
──────────────────────────────────────────────────────────────────────────────
`OFFBOARDING_OWNER_KEY` sentinel-i "offboarding-in TƏK kataloqu var" faktının
ifadəsidir (`catalogs.py` başlığı) — dialoq bunu sabit yazır. FIELD_REPORT
isə çox-kataloqlu ola bilər (Faza 4.1, hər hesabat növünün öz checklist-i),
ona görə orada sahə AÇIQ mətn qutusudur.

──────────────────────────────────────────────────────────────────────────────
FIELD_REPORT SƏKMƏSİNDƏ `owner_key` NİYƏ AXTARIŞLA GƏLİR, SİYAHIDAN DEYİL
──────────────────────────────────────────────────────────────────────────────
`ChecklistItemTemplateRepository`-nin (`ports.py`) "bu tenant-da hansı FIELD_
REPORT `owner_key`-ləri mövcuddur?" sualına cavab verən metodu YOXDUR —
`list_for_owner()` HƏMİŞƏ KONKRET `owner_key` tələb edir. Sahibi bunu Faza
4.1-də (gündəlik açılış/bağlanış checklist-i, `v2backlog.md` FAZA 4) əlavə
edəcək, çünki hazırda FIELD_REPORT tərəfini İSTEHLAK edən BİR TƏK yer belə
YOXDUR (bax `catalog_management.py` başlığı). Uydurma bir siyahı (məs. sabit
"İNCIDENT"/"AUDIT" açarları) YAZMAQ ƏVƏZİNƏ admin açarı ƏLLƏ yazıb axtarır —
bu, mövcud olmayan bir kataloqu var kimi göstərməkdənsə DAHA DÜRÜST həlldir.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from src.presentation.screens.base import Screen
from src.presentation.widgets import metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.data_table import Column, DataTable
from src.presentation.widgets.forms import FormField, field_label
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import (
    Card,
    Chip,
    FilterChip,
    muted_label,
    stretch,
    title_label,
)

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager

#: Ekranın filtr çipləri VƏ dialoqun kateqoriya şərtinin açarları — `owner_
#: type` DƏYƏRLƏRİ (`ChecklistOwnerType.value`) İLƏ EYNİDİR (CLAUDE.md §6:
#: canlı/maket açarları uyğunlaşmalıdır).
OWNER_TYPE_OFFBOARDING: Final = "OFFBOARDING"
OWNER_TYPE_FIELD_REPORT: Final = "FIELD_REPORT"
#: `OFFBOARDING_OWNER_KEY` sentinel-inin (`domain/value_objects/catalogs.py`)
#: presentasiya güzgüsü — dialoq DOMEN sabitini idxal etmir (`screens/`
#: `application`/`domain`-i tanımır, CLAUDE.md §3), qiyməti burada TƏKRAR yazır.
OFFBOARDING_OWNER_KEY: Final = "OFFBOARDING"

_OWNER_TYPE_LABELS: Final[dict[str, str]] = {
    OWNER_TYPE_OFFBOARDING: "Offboarding",
    OWNER_TYPE_FIELD_REPORT: "Sahə Hesabatı",
}

_CATEGORY_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    ("EQUIPMENT", "Avadanlıq"),
    ("SETTLEMENT", "Son Haqq-Hesab"),
    ("EXIT_INTERVIEW", "Çıxış Müsahibəsi"),
)
_CATEGORY_LABELS: Final[dict[str, str]] = dict(_CATEGORY_CHOICES)


class ChecklistTemplateScreen(Screen):
    """Checklist bənd şablonları — Root/HR (`can_manage_employees`).

    Signals:
        owner_type_changed: Filtr çipi dəyişdi (`OWNER_TYPE_*`).
        create_requested: `[Yeni Bənd]` — CARİ filtrlə (ekran özü daşıyır).
        edit_requested: `template_id`.
        toggle_requested: `template_id` (aktiv ↔ deaktiv).
    """

    owner_type_changed = Signal(str)
    #: FIELD_REPORT-un `owner_key`-i AXTARIŞLA gəlir (bax modul başlığı,
    #: `owner_key` bölməsi) — açar mətni.
    owner_key_lookup_requested = Signal(str)
    create_requested = Signal()
    edit_requested = Signal(str)
    toggle_requested = Signal(str)

    _COLUMNS: ClassVar[list[Column]] = [
        Column("#", 48, mono=True),
        Column("Kateqoriya", 140),
        Column("Bənd mətni"),
        Column("Bağlayıcı", 100),
        Column("Foto", 80),
        Column("Vəziyyət", 100),
        Column("Əməliyyat", 180),
    ]

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)
        self._owner_type = OWNER_TYPE_OFFBOARDING

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(metrics.SPACE_MS)

        self._filter_chips: dict[str, FilterChip] = {}
        for key, label in _OWNER_TYPE_LABELS.items():
            chip = FilterChip(key, label, "info" if key == self._owner_type else "neutral")
            chip.clicked.connect(self._set_owner_type)
            self._filter_chips[key] = chip
            toolbar_layout.addWidget(chip)

        toolbar_layout.addWidget(stretch())
        self._summary = muted_label("")
        toolbar_layout.addWidget(self._summary)

        create = action_button(
            "Yeni Bənd", icon_name="plus", icon_color=theme.color("--color-action-text")
        )
        create.clicked.connect(self.create_requested)
        toolbar_layout.addWidget(create)
        self.add(toolbar)

        # FIELD_REPORT-un `owner_key` axtarışı — YALNIZ bu dəst seçiləndə
        # görünür (modul başlığı, "FIELD_REPORT SƏKMƏSİNDƏ owner_key").
        self._owner_key_row = QWidget()
        owner_key_outer = QVBoxLayout(self._owner_key_row)
        owner_key_outer.setContentsMargins(0, 0, 0, 0)
        owner_key_outer.setSpacing(4)

        owner_key_layout = QHBoxLayout()
        owner_key_layout.setContentsMargins(0, 0, 0, 0)
        owner_key_layout.setSpacing(metrics.SPACE_MS)
        owner_key_layout.addWidget(field_label("Kataloq açarı (owner_key)"))
        self._owner_key_input = QLineEdit()
        self._owner_key_input.setProperty("variant", "form")
        # NÜMUNƏ DƏYƏR YOX (`test_setup_wizard_state.py::test_no_form_field_
        # shows_example_data`) — placeholder YALNIZ nə gözlənildiyini deyir,
        # doldurulası dəyər TƏKLİF ETMİR. İstifadəçi "məs." sözünü göstəriş
        # yox, hərfi dəyər kimi oxuyub onu daxil edərdi (qapının öz izahı).
        self._owner_key_input.setPlaceholderText("Kataloq açarını yazın")
        owner_key_layout.addWidget(self._owner_key_input, 1)
        lookup = secondary_button("Göstər")
        lookup.clicked.connect(
            lambda: self.owner_key_lookup_requested.emit(self._owner_key_input.text().strip())
        )
        owner_key_layout.addWidget(lookup)
        owner_key_outer.addLayout(owner_key_layout)

        # Nümunə BURADA icazəlidir — sahənin İÇİNDƏ deyil, altındakı köməkçi
        # mətndədir (`test_no_form_field_shows_example_data` yalnız `place
        # holder=`/`setPlaceholderText(...)`-i skan edir).
        owner_key_outer.addWidget(muted_label("məsələn: STORE_AUDIT, DAILY_OPEN", size=12))

        self._owner_key_row.setVisible(False)
        self.add(self._owner_key_row)

        self._table_host = QWidget()
        self._table_layout = QVBoxLayout(self._table_host)
        self._table_layout.setContentsMargins(0, 0, 0, 0)
        self._table_layout.setSpacing(0)
        self.add(self._table_host)

    def _set_owner_type(self, owner_type: str) -> None:
        """`FilterChip.clicked` — `NotificationPanel.set_filter` ilə EYNİ naxış."""
        if owner_type == self._owner_type:
            return
        self._owner_type = owner_type
        for key, chip in self._filter_chips.items():
            chip.set_tone("info" if key == owner_type else "neutral")
        self._owner_key_row.setVisible(owner_type == OWNER_TYPE_FIELD_REPORT)
        if owner_type == OWNER_TYPE_FIELD_REPORT:
            # Axtarış aparılana qədər SİYAHI GÖSTƏRİLMİR — uydurma boş
            # "nəticə" yerinə açıq təlimat (modul başlığı).
            self.show_empty(
                icon_name="checklist",
                title="Kataloq açarını daxil edin",
                message="FIELD_REPORT şablonları üçün əvvəlcə açarı yazıb «Göstər»i basın.",
            )
        self.owner_type_changed.emit(owner_type)

    @property
    def owner_type(self) -> str:
        """Kontrollerin `create_requested`-i EMAL ETMƏK üçün oxuduğu cari filtr."""
        return self._owner_type

    def set_entries(self, rows: list[dict[str, str]]) -> None:
        """Cari `owner_type` üçün bəndləri göstərir.

        Args:
            rows: `id`, `position_no`, `category` (boş ola bilər —
                FIELD_REPORT-da HƏMİŞƏ boşdur), `item_text`, `is_blocking`
                (`"1"`/`"0"`), `photo_required` (`"1"`/`"0"`), `is_active`
                (`"1"`/`"0"`) açarlı sözlüklər. Açarlar `controllers/
                checklist_templates.py::_to_row` ilə EYNİDİR (CLAUDE.md §6).
        """
        clear_layout(self._table_layout)

        if not rows:
            self.show_empty(
                icon_name="checklist",
                title="Bu dəstdə hələ bənd yoxdur",
                message="«Yeni Bənd» ilə ilk checklist bəndini əlavə edin.",
            )
            return

        active_count = sum(1 for row in rows if row.get("is_active", "1") == "1")
        self._summary.setText(
            f"{len(rows)} bənd — {active_count} aktiv, {len(rows) - active_count} deaktiv"
        )

        table = DataTable(self._COLUMNS, self.theme)
        for row in rows:
            table.add_row(self._build_cells(row))
        self._table_layout.addWidget(table)
        self.show_content()

    def table_layout(self) -> QVBoxLayout:
        """Cədvəl qabı — testlər sətir sayını buradan oxuyur."""
        return self._table_layout

    def _build_cells(self, row: dict[str, str]) -> list[QWidget | str]:
        category = row.get("category", "")
        is_blocking = row.get("is_blocking") == "1"
        photo_required = row.get("photo_required") == "1"
        is_active = row.get("is_active", "1") == "1"

        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)

        key = row.get("id", "")
        edit = secondary_button("Redaktə")
        edit.clicked.connect(lambda *_, k=key: self.edit_requested.emit(k))
        actions_layout.addWidget(edit)

        toggle = secondary_button("Deaktiv et" if is_active else "Aktivləşdir")
        toggle.clicked.connect(lambda *_, k=key: self.toggle_requested.emit(k))
        actions_layout.addWidget(toggle)

        return [
            row.get("position_no", ""),
            _CATEGORY_LABELS.get(category, "—"),
            row.get("item_text", ""),
            Chip("Bəli", "warning") if is_blocking else "—",
            Chip("Tələb olunur", "info") if photo_required else "—",
            Chip("Aktiv", "success") if is_active else Chip("Deaktiv", "neutral"),
            actions,
        ]


class ChecklistTemplateDialog(QDialog):
    """Bənd şablonunun yaradılması/redaktəsi.

    Signals:
        submitted: `(owner_key, position_no_text, item_text, is_blocking,
            photo_required, category_or_empty)`.

    Dialoq DOMEN QAYDASINI YOXLAMIR (`CatalogEntryDialog` ilə eyni qərar,
    bax həmin sinfin başlığı) — yalnız BOŞ/yanlış-formatlı sahə tutulur.
    """

    submitted = Signal(str, str, str, bool, bool, str)

    def __init__(
        self,
        theme: ThemeManager,
        *,
        owner_type: str,
        title: str,
        owner_key: str = "",
        position_no: str = "",
        item_text: str = "",
        is_blocking: bool = False,
        photo_required: bool = False,
        category: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._owner_type = owner_type
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING, shadow=True)
        layout.addWidget(card)
        card.add(title_label(title, size=19))
        card.add(muted_label(_OWNER_TYPE_LABELS.get(owner_type, owner_type), size=12))

        self._owner_key = FormField("Kataloq açarı (owner_key)")
        self._owner_key.set_text(
            OFFBOARDING_OWNER_KEY if owner_type == OWNER_TYPE_OFFBOARDING else owner_key
        )
        if owner_type == OWNER_TYPE_OFFBOARDING:
            # Offboarding-in TƏK kataloqu var (modul başlığı) — sahə
            # doldurulub göstərilir, LAKİN redaktə mənasız olardı: dəyişsə
            # sətir "yad" bir owner_key altına düşərdi və `start_checklist()`
            # onu ARTIQ TAPMAZDI.
            self._owner_key.input_widget().setEnabled(False)
        card.add(self._owner_key)

        self._position_no = FormField("Sıra nömrəsi", placeholder="1")
        self._position_no.set_text(position_no)
        card.add(self._position_no)

        self._item_text = FormField("Bənd mətni")
        self._item_text.set_text(item_text)
        card.add(self._item_text)

        self._category_box: QComboBox | None = None
        if owner_type == OWNER_TYPE_OFFBOARDING:
            category_wrap = QWidget()
            category_layout = QVBoxLayout(category_wrap)
            category_layout.setContentsMargins(0, 0, 0, 0)
            category_layout.setSpacing(8)
            category_layout.addWidget(field_label("Kateqoriya"))
            combo = QComboBox()
            combo.setProperty("variant", "form")
            for value, label in _CATEGORY_CHOICES:
                combo.addItem(label, value)
            if category:
                index = combo.findData(category)
                if index >= 0:
                    combo.setCurrentIndex(index)
            category_layout.addWidget(combo)
            card.add(category_wrap)
            self._category_box = combo
        # FIELD_REPORT-da kateqoriya sahəsi ÜMUMİYYƏTLƏ QURULMUR (modul
        # başlığı, "görmək = səlahiyyət" bənd 3-ün domen-vəziyyət tətbiqi).

        self._blocking = QCheckBox("Bağlayıcı bənddir (checklist bunsuz tamamlana bilməz)")
        self._blocking.setChecked(is_blocking)
        card.add(self._blocking)

        self._photo_required = QCheckBox("Foto-sübut tələb olunur")
        self._photo_required.setChecked(photo_required)
        card.add(self._photo_required)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(metrics.SPACE_MS)
        buttons_layout.addWidget(stretch())

        cancel = secondary_button("İmtina")
        cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel)

        save = action_button("Yadda saxla")
        save.clicked.connect(self._on_submit)
        buttons_layout.addWidget(save)
        card.add(buttons)

        save.setDefault(True)
        save.setAutoDefault(True)
        cancel.setAutoDefault(False)

        self._item_text.focus_input()

    def _on_submit(self) -> None:
        owner_key = self._owner_key.text().strip()
        item_text = self._item_text.text().strip()
        position_text = self._position_no.text().strip()

        self._owner_key.clear_error()
        self._item_text.clear_error()
        self._position_no.clear_error()

        valid = True
        if not owner_key:
            self._owner_key.set_error("Kataloq açarı məcburidir")
            valid = False
        if not item_text:
            self._item_text.set_error("Bənd mətni məcburidir")
            valid = False
        if not position_text.isdigit() or int(position_text) < 1:
            self._position_no.set_error("Sıra nömrəsi 1 və ya yuxarı tam ədəd olmalıdır")
            valid = False
        if not valid:
            return

        category = self._category_box.currentData() if self._category_box is not None else ""
        self.submitted.emit(
            owner_key,
            position_text,
            item_text,
            self._blocking.isChecked(),
            self._photo_required.isChecked(),
            category or "",
        )
        self.accept()


__all__ = [
    "OFFBOARDING_OWNER_KEY",
    "OWNER_TYPE_FIELD_REPORT",
    "OWNER_TYPE_OFFBOARDING",
    "ChecklistTemplateDialog",
    "ChecklistTemplateScreen",
]
