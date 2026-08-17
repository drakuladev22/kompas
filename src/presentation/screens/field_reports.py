"""Sahə hesabatı forması — #26 Mağaza Auditi + #27 İnsident Bildirişi (kompas1.md Faza 3).

──────────────────────────────────────────────────────────────────────────────
BİR EKRAN SİNFİ, İKİ MENYU AÇARI — NİYƏ İKİ AYRI EKRAN YAZILMADI
──────────────────────────────────────────────────────────────────────────────
Tətbiq qatı bu iki formanı VAHİD nüvə kimi qurub (`use_cases/field_reports.py`
"Struktur Qərar A"): fərq şablonun ADINDA yox, `FieldReportTemplate.
requires_checklist` XASSƏSİNDƏDİR. Ekran həmin qərarı GÜZGÜLƏYİR — burada
`if template_code == "STORE_AUDIT"` zənciri YOXDUR:

    * checklist bölməsinin görünməsi  → seçilmiş şablonun `requires_checklist`
    * formanın başlığı və izahı       → kataloqun `name_az`/`description_az`
    * hansı şablonlar siyahıdadır     → use case ONSUZ DA səlahiyyətə görə
                                        süzür (`list_templates`)

Nəticədə üçüncü şablon (məs. "Təchizat yoxlaması") kataloqa bir `INSERT` ilə
əlavə olunur və BU FAYL DƏYİŞMİR. Presedent layihədə var: üç kataloq ekranı da
(`group_h.CatalogScreen`) tək sinifdir və yalnız açarla fərqlənir
(`controllers/catalog_admin.py` başlığı).

──────────────────────────────────────────────────────────────────────────────
NİYƏ KİOSK EKRANI DEYİL, ADMİN ÖRTÜYÜNÜN İÇİNDƏ MOBİL-DOSTU FORMA
──────────────────────────────────────────────────────────────────────────────
`group_a_kiosk.py` PAYLAŞILAN mağaza PC-si üçündür: tam ekran, naviqasiyasız,
88px toxunma hədəfləri. Bu forma isə ŞƏXSİ sessiyada doldurulur (hesabat
`reported_by` ilə şəxsə yazılır və marşrutlanır), ona görə örtüyün içindədir.
"Mobil-dostu"luq iki qərarla təmin olunur:

    1. TƏK SÜTUN — sahələr yan-yana düzülmür, dar pəncərədə də sıra qorunur;
       forma kartının maksimum eni məhduddur (`FORM_MAX_WIDTH`), çünki 1400px
       enində uzanan giriş sahəsi oxunmur.
    2. ADDIM-ADDIM CHECKLIST — 40 bəndlik audit bir siyahıda göstərilsəydi,
       telefon ekranında istifadəçi hansı bəndə cavab verdiyini itirərdi.
       Eyni qərarı `migrations/037` də yazıb (`position_no` sütununun izahı:
       "checklist addım-addım naviqasiya ilə göstərilir").

──────────────────────────────────────────────────────────────────────────────
ÜÇÜNCÜ VƏZİYYƏT (`passed IS NULL`) UI-DA NECƏ İFADƏ OLUNUR
──────────────────────────────────────────────────────────────────────────────
Bənd ÜÇ vəziyyətlidir (keçdi / keçmədi / yoxlanılmadı) və `QCheckBox` bunu
ifadə EDƏ BİLMİR: iki-vəziyyətli qutuda "işarələnməmiş" həm "yoxlanılmadı",
həm də "keçmədi" deməkdir — halbuki domendə bu ikisi TAMAM FƏRQLİDİR
(`is_blocking_failure` YALNIZ `passed is False` halında düzəliş tapşırığı
yaradır, `None` yaratmır). `QCheckBox.setTristate()` də uyğun deyil: onun üçüncü
vəziyyəti (`PartiallyChecked`) vizual olaraq "qismən" deməkdir və istifadəçi onu
"yarım keçdi" kimi oxuyar.

Ona görə hər bənddə ÜÇ radio düymə var və defolt seçim «Yoxlanılmadı»dır —
yəni cavabsız bənd təsadüfən "keçdi" sayılmır.

──────────────────────────────────────────────────────────────────────────────
FOTO MƏCBURİ OLAN BƏND — İSTİFADƏÇİ XƏTAYA QƏDƏR APARILMIR
──────────────────────────────────────────────────────────────────────────────
Domen qaydası onsuz da rədd edir (`FieldReportChecklistItem._apply_answer`),
lakin rədd TƏQDİMAT anında baş verərdi — yəni istifadəçi 30 bəndi doldurub
sonda xəta alardı. Ekran həmin qaydanı ƏVVƏLCƏDƏN tətbiq edir: foto tələb edən
bənd cavablanıbsa və şəkil seçilməyibsə, NƏ növbəti addıma keçmək, NƏ də
təqdim etmək olur; səbəb elə həmin bəndin yanında yazılır.

Cavab MODELDƏ SAXLANILIR (radio geri qaytarılmır): auditor əvvəlcə "keçmədi"
işarələyib sonra şəkil çəkə bilər — seçimi onun barmağı altından geri almaq
səbəbi gizlədər və işi ikiqat artırardı.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, ClassVar, Final

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QPlainTextEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from src.domain.value_objects.field_reports import FieldReportStatus
from src.presentation.screens.base import Screen
from src.presentation.widgets.buttons import action_button, secondary_button
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
    stretch,
    title_label,
)

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager

#: Forma sütununun maksimum eni. Vizual ölçüdür, iş qaydası DEYİL — ona görə
#: `system_limits`-də yeri yoxdur (`forms.FIELD_HEIGHT` ilə eyni kateqoriya).
FORM_MAX_WIDTH: Final = 640

#: Fayl seçicisinin süzgəci — YALNIZ şəkil.
#:
#: SEC-018: `allowed_extensions_for("FIELD_REPORT")` sahə hesabatı üçün PDF
#: BURAXMIR (işçi sənədindən fərqli olaraq). Süzgəcin özü QORUMA DEYİL —
#: istifadəçi "Bütün fayllar"a keçə bilər və Qt məzmuna baxmır; həqiqi qapı
#: `validate_evidence_payload`-dadır. Süzgəc yalnız istifadəçini boş yerə
#: yanlış fayla aparmamaq üçündür (`group_c.EmployeeDocumentDialog._pick_file`
#: ilə eyni qərar, əks istiqamətdə: orada PDF ƏLAVƏ edilir, burada ÇIXARILIR).
PHOTO_FILE_FILTER: Final = "Şəkillər (*.png *.jpg *.jpeg *.webp)"


@dataclass(frozen=True)
class ChecklistEntry:
    """Formanın topladığı BİR checklist bəndi — hələ domen draft-ı DEYİL.

    `ChecklistItemDraft`-ın (domen) təkrarı deyil, GUI güzgüsüdür: burada
    `photo_ref` YOX, `photo_path` var — ekran YEREL disk yolunu tanıyır,
    Drive istinadını isə YALNIZ kontroller/növbə bilir (`controllers/
    field_reports.py` başlığı). Ekranın domen tipini doldurması onu
    infrastruktur sırasından (spool → Drive) asılı edərdi.
    """

    item_text: str
    is_blocking: bool = False
    photo_required: bool = False
    #: Üç vəziyyət — `None` = hələ yoxlanılmadı (bax modul başlığı).
    passed: bool | None = None
    #: Seçilmiş şəklin YEREL yolu; `""` = seçilməyib.
    photo_path: str = ""
    note: str = ""


@dataclass(frozen=True)
class FieldReportFormValues:
    """Təqdimat siqnalının yükü — ekranın kontrollerə verdiyi HƏR ŞEY.

    Sözlük əvəzinə dataclass: `fine_entry` naxışında (`Signal(object)` + `dict`)
    açar səhvi yalnız icra zamanı üzə çıxır. Burada sahə adı mypy-ın
    yoxladığı müqavilədir və kontroller `values.detail` yazanda səhv ad
    dərhal görünür.
    """

    template_code: str
    category_code: str
    store_id: str
    detail: str
    photo_paths: tuple[str, ...] = ()
    checklist: tuple[ChecklistEntry, ...] = ()


class FieldReportScreen(Screen):
    """Sahə hesabatı forması + həmin şablonun açıq hesabatları.

    Signals:
        submit_requested: `FieldReportFormValues` — «Təqdim Et».
        progress_requested: `report_id` — «İcraya Götür».
        close_requested: `(report_id, FieldReportStatus.value)` — «Həll Edildi»
            / «Əsassızdır». Bağlanma qeydi MƏCBURİDİR və kontrollerdə
            soruşulur (`controllers/exceptions.py`-dəki eyni naxış).
    """

    submit_requested = Signal(object)
    progress_requested = Signal(str)
    close_requested = Signal(str, str)

    #: Status kodu → nişan tonu. `FieldReportStatus` SƏRT enum-dur (yeni dəyər
    #: buraxılış tələb edir), ona görə burada sabit lüğət saxlanıla bilər —
    #: şablon/kateqoriya lüğəti isə saxlanıla BİLMƏZ (onlar kataloqdur).
    _STATUS_TONES: ClassVar[dict[str, ChipTone]] = {
        FieldReportStatus.SUBMITTED.value: "info",
        FieldReportStatus.IN_PROGRESS.value: "warning",
        FieldReportStatus.RESOLVED.value: "success",
        FieldReportStatus.DISMISSED.value: "neutral",
    }

    _COLUMNS: ClassVar[list[Column]] = [
        Column("Şablon", 140),
        Column("Kateqoriya", 140),
        Column("Mağaza", 130),
        Column("Təfərrüat", 220),
        Column("Bal", 70),
        Column("Vəziyyət", 110),
        Column("Tarix", 130, mono=True),
        Column("Əməliyyat"),
    ]

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)

        self._templates: list[dict[str, str]] = []
        self._categories: list[dict[str, str]] = []
        self._items: list[ChecklistEntry] = []
        self._photo_paths: list[str] = []
        #: ROOT parametrləri — dəyər `set_*` ilə CANLI oxunur, burada sabit YOX.
        self._photo_limit = 0
        self._detail_min_length = 0
        self._step = 0
        #: Radio-nun proqram yolu ilə qurulması `select_answer`-i işə salmasın.
        self._suspend_answer = False

        # SIRA VACİBDİR: checklist qabı ƏVVƏLCƏ qurulur, çünki forma kartındakı
        # şablon seçicisi ona istinad edən siqnala bağlanır — tərsi olsaydı,
        # konstruktor gedişində atılan bir siqnal `AttributeError` verərdi.
        self._checklist_holder = _narrow(self._build_checklist_card())
        self._checklist_holder.setVisible(False)

        self.add(_narrow(self._build_form_card()))
        self.add(self._checklist_holder)
        self.add(_narrow(self._build_actions_card()))
        self.add(self._build_list_card())

        self._render_step()
        self.show_content()

    # ------------------------------- quruluş --------------------------------- #

    def _build_form_card(self) -> Card:
        card = Card(padding=20, spacing=12)

        self._form_title = title_label("Sahə hesabatı", size=19)
        card.add(self._form_title)
        self._form_description = muted_label("")
        self._form_description.setWordWrap(True)
        card.add(self._form_description)
        card.add(Divider())

        self._template_combo = self._build_combo(card, "Hesabat şablonu")
        self._template_combo.currentIndexChanged.connect(lambda _index: self._on_template_changed())
        self._category_combo = self._build_combo(card, "Kateqoriya")
        self._store_combo = self._build_combo(card, "Mağaza")

        card.add(field_label("Nə müşahidə etdiniz?"))
        self._detail = QPlainTextEdit()
        self._detail.setProperty("variant", "form")
        self._detail.setMinimumHeight(112)
        self._detail.setPlaceholderText("Tapıntını və ya hadisəni öz sözlərinizlə yazın…")
        card.add(self._detail)
        self._detail_hint = muted_label("")
        self._detail_hint.setWordWrap(True)
        card.add(self._detail_hint)

        card.add(Divider())
        card.add(field_label("Foto-sübut (könüllü)"))
        self._photo_label = muted_label("Şəkil seçilməyib")
        self._photo_label.setWordWrap(True)

        photo_row = QWidget()
        photo_layout = QHBoxLayout(photo_row)
        photo_layout.setContentsMargins(0, 0, 0, 0)
        photo_layout.setSpacing(12)
        photo_layout.addWidget(self._photo_label, stretch=1)
        pick = secondary_button("Şəkil Seç")
        pick.clicked.connect(self.pick_photos)
        photo_layout.addWidget(pick)
        drop = secondary_button("Təmizlə")
        drop.clicked.connect(self.clear_photos)
        photo_layout.addWidget(drop)
        card.add(photo_row)
        return card

    def _build_checklist_card(self) -> Card:
        card = Card(padding=20, spacing=12)
        card.add(title_label("Checklist", size=15))
        card.add(
            muted_label(
                "Bəndlər bir-bir göstərilir. Hər bənd üç cavabdan birini alır: "
                "keçdi / keçmədi / yoxlanılmadı. Uğursuz BLOKLAYICI bənd "
                "təqdimatdan sonra Tapşırıq Mühərrikində avtomatik düzəliş "
                "tapşırığı yaradır — cavabsız bənd YARATMIR.",
                size=12,
            )
        )
        card.add(Divider())

        self._item_text = FormField("Bənd mətni")
        card.add(self._item_text)
        self._item_blocking = QCheckBox("Bloklayıcı bənddir (uğursuzluq düzəliş tapşırığı yaradır)")
        card.add(self._item_blocking)
        self._item_photo_required = QCheckBox("Bu bənd üçün foto-sübut məcburidir")
        card.add(self._item_photo_required)

        add_row = QWidget()
        add_layout = QHBoxLayout(add_row)
        add_layout.setContentsMargins(0, 0, 0, 0)
        add_layout.setSpacing(12)
        add_layout.addWidget(stretch())
        add_button = action_button(
            "Bənd Əlavə Et",
            icon_name="plus",
            icon_color=self.theme.color("--color-action-text"),
        )
        add_button.clicked.connect(self.add_checklist_item)
        add_layout.addWidget(add_button)
        card.add(add_row)

        card.add(Divider())

        nav_row = QWidget()
        nav_layout = QHBoxLayout(nav_row)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(12)
        self._previous_button = secondary_button("← Əvvəlki")
        self._previous_button.clicked.connect(self.go_previous)
        nav_layout.addWidget(self._previous_button)
        self._step_label = mono_label("0 / 0")
        nav_layout.addWidget(self._step_label)
        nav_layout.addWidget(stretch())
        self._next_button = secondary_button("Növbəti →")
        self._next_button.clicked.connect(self.go_next)
        nav_layout.addWidget(self._next_button)
        card.add(nav_row)

        self._step_host = QWidget()
        self._step_layout = QVBoxLayout(self._step_host)
        self._step_layout.setContentsMargins(0, 0, 0, 0)
        self._step_layout.setSpacing(12)
        card.add(self._step_host)

        self._checklist_message = muted_label("")
        self._checklist_message.setWordWrap(True)
        self._checklist_message.setVisible(False)
        card.add(self._checklist_message)
        return card

    def _build_actions_card(self) -> Card:
        card = Card(padding=20, spacing=12)

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(stretch())
        reset = secondary_button("Formanı Təmizlə")
        reset.clicked.connect(self.clear_form)
        layout.addWidget(reset)
        submit = action_button("Təqdim Et")
        submit.clicked.connect(self._on_submit)
        submit.setDefault(True)
        submit.setAutoDefault(True)
        reset.setAutoDefault(False)
        layout.addWidget(submit)
        card.add(row)

        self._form_message = muted_label("")
        self._form_message.setWordWrap(True)
        self._form_message.setVisible(False)
        card.add(self._form_message)
        return card

    def _build_list_card(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(title_label("Açıq hesabatlar", size=15))
        self._list_notice = muted_label("")
        self._list_notice.setWordWrap(True)
        self._list_notice.setVisible(False)
        layout.addWidget(self._list_notice)

        self._list_empty = muted_label("Açıq hesabat yoxdur.")
        layout.addWidget(self._list_empty)

        self._table = DataTable(
            self._COLUMNS,
            self.theme,
            footnote=(
                "Bağlanmış hesabat silinmir — rədd qərarı da audit jurnalına düşür. "
                "«Bal» yalnız CAVABLANMIŞ bəndlərdən hesablanır."
            ),
        )
        self._table.setVisible(False)
        layout.addWidget(self._table)
        return holder

    def _build_combo(self, card: Card, label: str) -> QComboBox:
        card.add(field_label(label))
        combo = QComboBox()
        combo.setProperty("variant", "form")
        combo.setMinimumHeight(48)
        card.add(combo)
        return combo

    # -------------------------------- setter API ------------------------------ #

    def set_templates(self, templates: list[dict[str, str]]) -> None:
        """Aktorun YAZA BİLDİYİ şablonlar (use case onsuz da süzür).

        Args:
            templates: `code`, `name`, `description`, `requires_checklist`
                (`"1"`/`"0"`) açarları. Açarlar maket (`preview_screens.
                _field_report`) və canlı yol (`controllers/field_reports.py::
                _template_row`) üçün EYNİDİR — CLAUDE.md §6.
        """
        self._templates = list(templates)
        # Siqnal MÜVƏQQƏTİ bağlanır: `clear()` + hər `addItem()`
        # `currentIndexChanged` atır, yəni siyahı qurulduqca `_on_template_
        # changed` yarımçıq vəziyyətdə dəfələrlə işləyərdi.
        self._template_combo.blockSignals(True)
        self._template_combo.clear()
        for template in self._templates:
            self._template_combo.addItem(template.get("name", ""), template.get("code", ""))
        self._template_combo.blockSignals(False)
        self._on_template_changed()

    def set_categories(self, categories: list[dict[str, str]]) -> None:
        """BÜTÜN şablonların kateqoriyaları — süzgəc ekranda işləyir.

        Şablon dəyişəndə yeni sorğu GÖNDƏRİLMİR: kateqoriya kataloqu kiçikdir
        (mağaza başına deyil, kirayəçi başına) və hər seçimdə baza sorğusu
        açmaq forma doldurulan müddətdə onlarla lazımsız gediş-gəliş demək
        olardı.

        Args:
            categories: `code`, `template`, `name`, `route_text` açarları.
        """
        self._categories = list(categories)
        self._apply_categories()

    def set_stores(self, stores: list[tuple[str, str]]) -> None:
        """(mağaza id, ad) — `open_shift.OpenShiftPostDialog` ilə eyni forma."""
        self._store_combo.clear()
        for store_id, name in stores:
            self._store_combo.addItem(name, store_id)

    def set_photo_limit(self, max_photos: int) -> None:
        """`system_limits.FIELD_REPORT_MAX_PHOTOS` — ekranda GÖRÜNÜR.

        Sabit ədəd YOXDUR: dəyər kontrollerdən (ROOT parametrindən) gəlir,
        `open_shift.py`-dəki `OPEN_SHIFT_MAX_LEAD_DAYS` ilə eyni qərar.
        """
        self._photo_limit = max(0, max_photos)
        self._refresh_photo_label()

    def set_detail_min_length(self, min_length: int) -> None:
        """`system_limits.FIELD_REPORT_MIN_DETAIL_LENGTH` (sxem döşəməsi ilə)."""
        self._detail_min_length = max(0, min_length)
        hint = ""
        if self._detail_min_length:
            hint = (
                f"Ən azı {self._detail_min_length} simvol — bu mətn düzəliş "
                f"tapşırığının izahına düşür."
            )
        self._detail_hint.setText(hint)

    def set_open_reports(self, rows: list[dict[str, str]]) -> None:
        """Açıq hesabatlar.

        `show_empty()` QƏSDƏN İŞLƏDİLMİR: o, bütün məzmunu vəziyyət ekranı ilə
        ƏVƏZ EDƏRDİ və istifadəçi FORMANI görməzdi — halbuki boş siyahı məhz
        yeni hesabat yazmaq üçün ən tipik andır (`Screen.show_empty` yalnız
        oxu-ekranları üçün nəzərdə tutulub).

        Args:
            rows: `id`, `type_name`, `category_name`, `store`, `detail`,
                `status`, `status_text`, `score_text`, `date` açarları.
        """
        self._table.clear()
        self._list_empty.setVisible(not rows)
        self._table.setVisible(bool(rows))
        for row in rows:
            self._table.add_row(self._build_report_cells(row))
        self.show_content()

    def set_list_notice(self, message: str) -> None:
        """Siyahının üstündəki izah/xəta sətri (boş sətir = gizlət)."""
        self._list_notice.setText(message)
        self._list_notice.setVisible(bool(message))

    def set_form_message(self, message: str, *, error: bool = False) -> None:
        """Formanın altındakı nəticə sətri.

        `show_error()` DEYİL: o, məzmunu əvəz edir və istifadəçinin YAZDIĞI
        mətni ekrandan silərdi. Təqdimat xətası formanın YANINDA qalmalıdır.
        """
        self._form_message.setText(message)
        self._form_message.setProperty("variant", "danger-text" if error else "muted")
        self._form_message.setVisible(bool(message))
        _restyle(self._form_message)

    def clear_form(self) -> None:
        """Uğurlu təqdimatdan sonra formu boşaldır — kontroller çağırır."""
        self._detail.setPlainText("")
        self._items = []
        self._photo_paths = []
        self._step = 0
        self._item_text.set_text("")
        self._item_blocking.setChecked(False)
        self._item_photo_required.setChecked(False)
        self._refresh_photo_label()
        self._set_checklist_message("")
        self._render_step()

    # ------------------------------- oxuma API -------------------------------- #

    def checklist_entries(self) -> tuple[ChecklistEntry, ...]:
        """Cari checklist vəziyyəti — testlər və kontroller üçün."""
        return tuple(self._items)

    def selected_template(self) -> dict[str, str]:
        """Seçilmiş şablonun kataloq sətri; seçim yoxdursa boş sözlük."""
        code = str(self._template_combo.currentData() or "")
        for template in self._templates:
            if template.get("code") == code:
                return template
        return {}

    def requires_checklist(self) -> bool:
        """Seçilmiş şablon checklist tələb edirmi (KATALOQDAN, `if` ilə yox)."""
        return self.selected_template().get("requires_checklist") == "1"

    def table(self) -> DataTable:
        return self._table

    # ------------------------------- checklist -------------------------------- #

    def add_checklist_item(self) -> bool:
        """«Bənd Əlavə Et» — mətn boşdursa əlavə etmir və səbəbi göstərir."""
        self._item_text.clear_error()
        text = self._item_text.text().strip()
        if not text:
            self._item_text.set_error("Bənd mətni məcburidir")
            return False

        self._items.append(
            ChecklistEntry(
                item_text=text,
                is_blocking=self._item_blocking.isChecked(),
                photo_required=self._item_photo_required.isChecked(),
            )
        )
        self._item_text.set_text("")
        self._item_blocking.setChecked(False)
        self._item_photo_required.setChecked(False)
        # Yeni bənd DƏRHAL göstərilir: əks halda istifadəçi bəndin əlavə
        # olunduğunu yalnız sayğacdan bilərdi.
        self._step = len(self._items) - 1
        self._set_checklist_message("")
        self._render_step()
        return True

    def select_answer(self, passed: bool | None) -> None:
        """Cari bəndin cavabı — üç vəziyyətdən biri (bax modul başlığı)."""
        if self._suspend_answer or not self._items:
            return
        entry = replace(self._items[self._step], passed=passed)
        self._items[self._step] = entry
        # Foto boşluğu DƏRHAL göstərilir (bloklama isə naviqasiyadadır).
        self._set_checklist_message(_photo_gap(entry))

    def go_next(self) -> bool:
        """Növbəti bənd. Foto boşluğu varsa İRƏLİ BURAXMIR (modul başlığı)."""
        if not self._items:
            return False
        gap = _photo_gap(self._items[self._step])
        if gap:
            self._set_checklist_message(gap)
            return False
        if self._step + 1 >= len(self._items):
            self._set_checklist_message("Bu, sonuncu bənddir.")
            return False
        self._step += 1
        self._set_checklist_message("")
        self._render_step()
        return True

    def go_previous(self) -> bool:
        """Əvvəlki bənd — GERİ dönüş foto qaydasına TABE DEYİL.

        Geriyə hərəkəti bloklamaq istifadəçini foto tapmadan qapalı qoyardı:
        əvvəlki bəndi düzəltmək yolu bağlanardı, halbuki səhv məhz orada ola
        bilər.
        """
        if not self._items or self._step == 0:
            return False
        self._step -= 1
        self._set_checklist_message("")
        self._render_step()
        return True

    def pick_item_photo(self) -> None:
        """Cari checklist bəndi üçün şəkil seçir."""
        if not self._items:
            return
        path = self._ask_photo()
        if not path:
            return
        self._items[self._step] = replace(self._items[self._step], photo_path=path)
        self._set_checklist_message("")
        self._render_step()

    def _render_step(self) -> None:
        """Cari bəndin kartını yenidən qurur.

        HƏR DƏFƏ YENİDƏN QURULUR (widget-lər saxlanılmır): bəndlərin sayı
        dəyişkəndir və hər bəndin öz radio qrupu, qeydi, şəkli var. Yaddaşda
        40 kart saxlamaq əvəzinə tək kart yenidən çəkilir — `ContentSwitcher`
        vəziyyət widget-lərində də eyni qərar verilib.
        """
        clear_layout(self._step_layout)
        total = len(self._items)
        self._step = min(self._step, max(total - 1, 0))
        self._step_label.setText(f"{self._step + 1 if total else 0} / {total}")
        self._previous_button.setEnabled(total > 1 and self._step > 0)
        self._next_button.setEnabled(total > 1 and self._step < total - 1)

        if not total:
            self._step_layout.addWidget(
                muted_label("Hələ bənd əlavə edilməyib — yuxarıdakı sahədən başlayın.")
            )
            return

        entry = self._items[self._step]
        panel = Card(surface="panel", padding=16, spacing=12)
        panel.add(body_label(f"{self._step + 1}. {entry.item_text}", size=15))

        chips = QWidget()
        chips_layout = QHBoxLayout(chips)
        chips_layout.setContentsMargins(0, 0, 0, 0)
        chips_layout.setSpacing(8)
        if entry.is_blocking:
            chips_layout.addWidget(Chip("Bloklayıcı", "warning"))
        if entry.photo_required:
            chips_layout.addWidget(Chip("Foto məcburi", "info"))
        chips_layout.addWidget(stretch())
        panel.add(chips)

        panel.add(self._build_answer_row(entry))

        panel.add(field_label("Qeyd (düzəliş tapşırığının mətninə düşür)"))
        note = QPlainTextEdit()
        note.setProperty("variant", "form")
        note.setMinimumHeight(72)
        note.setPlainText(entry.note)
        note.textChanged.connect(lambda: self._on_note_changed(note.toPlainText()))
        panel.add(note)

        photo_row = QWidget()
        photo_layout = QHBoxLayout(photo_row)
        photo_layout.setContentsMargins(0, 0, 0, 0)
        photo_layout.setSpacing(12)
        photo_layout.addWidget(
            muted_label(_file_name(entry.photo_path) or "Şəkil seçilməyib"), stretch=1
        )
        pick = secondary_button("Şəkil Seç")
        pick.clicked.connect(self.pick_item_photo)
        photo_layout.addWidget(pick)
        panel.add(photo_row)

        self._step_layout.addWidget(panel)

    def _build_answer_row(self, entry: ChecklistEntry) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        passed = QRadioButton("Keçdi")
        failed = QRadioButton("Keçmədi")
        unchecked = QRadioButton("Yoxlanılmadı")

        group = QButtonGroup(row)
        for button in (passed, failed, unchecked):
            group.addButton(button)
            layout.addWidget(button)
        layout.addWidget(stretch())

        # Proqram yolu ilə qurulan seçim `select_answer`-i İŞƏ SALMAMALIDIR:
        # əks halda kart hər yenidən çəkiləndə cavab "yenidən seçilmiş" sayılar
        # və foto mesajı özbaşına görünərdi.
        self._suspend_answer = True
        if entry.passed is True:
            passed.setChecked(True)
        elif entry.passed is False:
            failed.setChecked(True)
        else:
            unchecked.setChecked(True)
        self._suspend_answer = False

        passed.toggled.connect(lambda checked: self._on_answer_toggled(True, checked=checked))
        failed.toggled.connect(lambda checked: self._on_answer_toggled(False, checked=checked))
        unchecked.toggled.connect(lambda checked: self._on_answer_toggled(None, checked=checked))
        return row

    def _on_answer_toggled(self, passed: bool | None, *, checked: bool) -> None:
        """`toggled` HƏM seçiləndə, HƏM seçim itəndə gəlir — yalnız birincisi."""
        if checked:
            self.select_answer(passed)

    def _on_note_changed(self, text: str) -> None:
        if not self._items:
            return
        self._items[self._step] = replace(self._items[self._step], note=text)

    def _set_checklist_message(self, message: str) -> None:
        self._checklist_message.setText(message)
        self._checklist_message.setProperty("variant", "danger-text" if message else "muted")
        self._checklist_message.setVisible(bool(message))
        _restyle(self._checklist_message)

    # -------------------------------- foto ------------------------------------ #

    def pick_photos(self) -> None:
        """Hesabat səviyyəsindəki şəkillər — limit ROOT parametrindən."""
        path = self._ask_photo()
        if not path:
            return
        if self._photo_limit and len(self._photo_paths) >= self._photo_limit:
            self.set_form_message(
                f"Bir hesabata ən çoxu {self._photo_limit} şəkil əlavə edilə bilər.",
                error=True,
            )
            return
        if path not in self._photo_paths:
            self._photo_paths.append(path)
        self._refresh_photo_label()

    def clear_photos(self) -> None:
        self._photo_paths = []
        self._refresh_photo_label()

    def _ask_photo(self) -> str:
        from PySide6.QtWidgets import QFileDialog  # noqa: PLC0415

        path, _selected = QFileDialog.getOpenFileName(
            self, "Foto-sübut seçin", "", PHOTO_FILE_FILTER
        )
        return str(path or "")

    def _refresh_photo_label(self) -> None:
        if not self._photo_paths:
            suffix = f" (ən çoxu {self._photo_limit})" if self._photo_limit else ""
            self._photo_label.setText(f"Şəkil seçilməyib{suffix}")
            return
        names = ", ".join(_file_name(path) for path in self._photo_paths)
        self._photo_label.setText(f"{len(self._photo_paths)} şəkil: {names}")

    # ------------------------------- şablon axını ------------------------------ #

    def _on_template_changed(self) -> None:
        template = self.selected_template()
        self._form_title.setText(template.get("name") or "Sahə hesabatı")
        self._form_description.setText(template.get("description", ""))
        # Checklist bölməsinin görünməsi KATALOQDAN çıxır (modul başlığı).
        self._checklist_holder.setVisible(self.requires_checklist())
        self._apply_categories()

    def _apply_categories(self) -> None:
        code = str(self._template_combo.currentData() or "")
        self._category_combo.clear()
        for category in self._categories:
            if category.get("template") != code:
                continue
            label = category.get("name", "")
            route = category.get("route_text", "")
            # Marşrut ADI seçimin YANINDA göstərilir: bildirişin kimə gedəcəyi
            # təqdimatdan ƏVVƏL bilinməlidir (#27 marşrutlaması kataloqdadır).
            self._category_combo.addItem(f"{label} · {route}" if route else label, category["code"])

    # ------------------------------- təqdimat --------------------------------- #

    def _on_submit(self) -> None:
        self.set_form_message("")
        template_code = str(self._template_combo.currentData() or "")
        category_code = str(self._category_combo.currentData() or "")
        store_id = str(self._store_combo.currentData() or "")
        detail = self._detail.toPlainText().strip()

        if not template_code or not category_code:
            self.set_form_message("Hesabat şablonu və kateqoriya seçilməlidir.", error=True)
            return
        if not store_id:
            self.set_form_message("Mağaza seçilməlidir.", error=True)
            return
        if len(detail) < max(1, self._detail_min_length):
            self.set_form_message(
                f"Təsvir ən azı {max(1, self._detail_min_length)} simvol olmalıdır.", error=True
            )
            return
        if self.requires_checklist() and not self._items:
            self.set_form_message("Bu forma ən azı bir checklist bəndi tələb edir.", error=True)
            return
        if self._photo_limit and len(self._photo_paths) > self._photo_limit:
            self.set_form_message(
                f"Bir hesabata ən çoxu {self._photo_limit} şəkil əlavə edilə bilər.", error=True
            )
            return

        for index, entry in enumerate(self._items):
            gap = _photo_gap(entry)
            if gap:
                # İstifadəçi PROBLEMLİ bəndə aparılır — mətn onsuz da bəndin
                # adını daşıyır, lakin 30 bəndlik auditdə onu axtarmaq lazım
                # gəlməməlidir.
                self._step = index
                self._render_step()
                self._set_checklist_message(gap)
                self.set_form_message(gap, error=True)
                return

        self.submit_requested.emit(
            FieldReportFormValues(
                template_code=template_code,
                category_code=category_code,
                store_id=store_id,
                detail=detail,
                photo_paths=tuple(self._photo_paths),
                checklist=tuple(self._items),
            )
        )

    # -------------------------------- siyahı ---------------------------------- #

    def _build_report_cells(self, row: dict[str, str]) -> list[QWidget | str]:
        report_id = row.get("id", "")
        status = row.get("status", "")

        detail = muted_label(row.get("detail", ""))
        detail.setWordWrap(True)

        return [
            row.get("type_name", ""),
            row.get("category_name", ""),
            row.get("store", ""),
            detail,
            mono_label(row.get("score_text", "")),
            Chip(
                row.get("status_text", "") or status,
                self._STATUS_TONES.get(status, "neutral"),
            ),
            mono_label(row.get("date", "")),
            self._build_report_actions(report_id, status),
        ]

    def _build_report_actions(self, report_id: str, status: str) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        if status == FieldReportStatus.SUBMITTED.value:
            start = secondary_button("İcraya Götür")
            start.clicked.connect(lambda: self.progress_requested.emit(report_id))
            layout.addWidget(start)

        resolve = secondary_button("Həll Edildi")
        resolve.clicked.connect(
            lambda: self.close_requested.emit(report_id, FieldReportStatus.RESOLVED.value)
        )
        layout.addWidget(resolve)

        dismiss = secondary_button("Əsassızdır")
        dismiss.setProperty("variant", "danger")
        dismiss.clicked.connect(
            lambda: self.close_requested.emit(report_id, FieldReportStatus.DISMISSED.value)
        )
        layout.addWidget(dismiss)
        return container


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _photo_gap(entry: ChecklistEntry) -> str:
    """Foto məcburi olan CAVABLANMIŞ bənddə şəkil çatışmırsa — səbəb mətni.

    Şərt domendəki `_apply_answer` ilə HƏRFİ-HƏRFİNƏ eynidir (`photo_required
    and photo_ref is None`), yalnız `photo_ref` əvəzinə yerel yol yoxlanılır.
    Cavabsız bənd (`passed is None`) boşluq SAYILMIR — domen də onu rədd etmir.
    """
    if entry.photo_required and entry.passed is not None and not entry.photo_path:
        return f"«{entry.item_text}» bəndi üçün foto-sübut məcburidir — şəkil əlavə edin."
    return ""


def _file_name(path: str) -> str:
    """Yolun yalnız fayl adı — tam yol ekranda sətri daşdırır."""
    return path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if path else ""


def _narrow(widget: QWidget) -> QWidget:
    """Widget-i `FORM_MAX_WIDTH` ilə məhdudlaşdırıb mərkəzə alır (mobil-dostu)."""
    widget.setMaximumWidth(FORM_MAX_WIDTH)
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addWidget(stretch())
    layout.addWidget(widget)
    layout.addWidget(stretch())
    return holder


def _restyle(widget: QWidget) -> None:
    """Dinamik `variant` dəyişikliyindən sonra QSS-i yenidən hesablatdırır.

    Qt xüsusiyyət dəyişəndə üslubu ÖZÜ yeniləmir (`Chip.set_tone` ilə eyni
    səbəb) — bu addım olmasa xəta mətni köhnə rəngdə qalardı.
    """
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


__all__ = [
    "FORM_MAX_WIDTH",
    "PHOTO_FILE_FILTER",
    "ChecklistEntry",
    "FieldReportFormValues",
    "FieldReportScreen",
]
