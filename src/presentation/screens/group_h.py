"""Qrup H — kataloqlar, hesabat ixracı və Yardım Mərkəzi — Faza 5/6.

Bu qrup maketdə AYRICA fayl kimi verilməyib: spesifikasiyanın bölmə 4 və
6-sında adbaad tələb olunan, lakin Qrup A–G maketlərinə düşməmiş ekranlardır.
Ona görə burada mövcud dizayn dilinin (Card, DataTable, Chip, PageHeader)
qaydaları TƏKRAR İSTİFADƏ olunur — yeni vizual naxış icad edilmir.

    31  İş Rejimləri Kataloqu      (`can_manage_work_modes`,  bölmə 4)
    32  Cərimə Növləri Kataloqu    (`can_manage_fine_types`,  bölmə 4)
    33  İcazə Növləri Kataloqu     (`can_manage_leave_types`, bölmə 4)
    34  Aylıq Hesabat İxracı       (`can_export_reports`,     bölmə 6)
    35  Yardım Mərkəzi             (səlahiyyət tələb olunmur, 5-ci faza)

──────────────────────────────────────────────────────────────────────────────
ÜÇ KATALOQ, BİR EKRAN SİNFİ
──────────────────────────────────────────────────────────────────────────────
`CatalogScreen` üçü üçün ortaqdır və sütunları konstruktorda alır. Üç ayrı
sinif yazmaq eyni cədvəl/boş-vəziyyət/düymə məntiqini üç dəfə təkrarlayardı;
fərqləri isə yalnız sütun adları və "yeni sətir" düyməsinin mətnidir.

──────────────────────────────────────────────────────────────────────────────
DEAKTİV SƏTİR NİYƏ SİLİNMİR, SOLĞUN GÖSTƏRİLİR
──────────────────────────────────────────────────────────────────────────────
Kataloqda "soft delete" var (bax `domain/value_objects/catalogs.py`). İdarəetmə
ekranı deaktiv sətirləri DƏ göstərir — nişanla — çünki Root onları yenidən
aktivləşdirə bilməlidir. Onları gizlətsək, "silinmiş" növ geri qaytarıla
bilməz görünərdi.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.presentation.i18n.text import az_upper
from src.presentation.screens.base import Screen, section_header
from src.presentation.theme.manager import refresh_widget_style
from src.presentation.widgets import icons, metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.data_table import Column, DataTable
from src.presentation.widgets.forms import FormField, field_label
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import (
    Card,
    Chip,
    Divider,
    body_label,
    muted_label,
    plain_label,
    stretch,
    title_label,
)
from src.presentation.widgets.safe_text import plain_tooltip

if TYPE_CHECKING:
    from PySide6.QtGui import QMouseEvent

    from src.presentation.theme.manager import ThemeManager


# --------------------------------------------------------------------------- #
# 31–33 — Kataloq ekranları
# --------------------------------------------------------------------------- #


class CatalogScreen(Screen):
    """İş Rejimləri / Cərimə Növləri / İcazə Növləri üçün ortaq ekran.

    Sətir `dict` kimi verilir: ekran domen tipini TANIMIR, yalnız hazır
    mətnləri göstərir. Beləliklə eyni ekran üç fərqli kataloqa xidmət edir və
    Qt qatı domen dəyişikliklərindən təsirlənmir.

    Signals:
        create_requested: "Yeni ..." düyməsi.
        edit_requested: Sətir açarı.
        toggle_requested: Sətir açarı (aktiv ↔ deaktiv).
    """

    create_requested = Signal()
    edit_requested = Signal(str)
    toggle_requested = Signal(str)

    def __init__(
        self,
        theme: ThemeManager,
        *,
        columns: list[Column],
        create_label: str,
        empty_title: str,
        empty_body: str,
        footnote: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(theme, parent=parent)
        self._columns = columns
        self._empty_title = empty_title
        self._empty_body = empty_body
        self._footnote = footnote
        self._rows: list[dict[str, str]] = []

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(10)
        self._summary = muted_label("")
        toolbar_layout.addWidget(self._summary)
        toolbar_layout.addWidget(stretch())

        create = action_button(
            create_label,
            icon_name="plus",
            icon_color=theme.color("--color-action-text"),
        )
        create.clicked.connect(self.create_requested)
        toolbar_layout.addWidget(create)
        self.add(toolbar)

        self._table_host = QWidget()
        self._table_layout = QVBoxLayout(self._table_host)
        self._table_layout.setContentsMargins(0, 0, 0, 0)
        self._table_layout.setSpacing(0)
        self.add(self._table_host)

    def set_entries(self, rows: list[dict[str, str]]) -> None:
        """Sətirləri yenidən çəkir.

        Args:
            rows: Hər sətir üçün: `key`, `cells` (`|` ilə ayrılmış), və
                `is_active` (`"1"`/`"0"`).
        """
        self._rows = rows
        clear_layout(self._table_layout)

        if not rows:
            self.show_empty(icon_name="list", title=self._empty_title, message=self._empty_body)
            return

        active_count = sum(1 for row in rows if row.get("is_active", "1") == "1")
        self._summary.setText(
            f"{len(rows)} sətir — {active_count} aktiv, {len(rows) - active_count} deaktiv"
        )

        table = DataTable(self._columns, self.theme, footnote=self._footnote)
        for row in rows:
            table.add_row(self._build_cells(row))
        self._table_layout.addWidget(table)
        self.show_content()

    def _build_cells(self, row: dict[str, str]) -> list[QWidget | str]:
        """Bir sətrin hüceyrələri — sonuncu sütun həmişə əməliyyat düymələridir."""
        cells: list[QWidget | str] = list(row.get("cells", "").split("|"))

        is_active = row.get("is_active", "1") == "1"
        status = Chip("Aktiv" if is_active else "Deaktiv", "success" if is_active else "neutral")
        cells.append(status)

        key = row.get("key", "")
        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)

        edit = secondary_button("Redaktə")
        edit.clicked.connect(lambda *_, k=key: self.edit_requested.emit(k))
        actions_layout.addWidget(edit)

        # Deaktiv sətir üçün düymə "Aktivləşdir" olur — eyni əməliyyat, əks
        # istiqamət. İki ayrı düymə göstərmək mənasız olardı, çünki biri
        # həmişə söndürülmüş qalardı.
        toggle = secondary_button("Deaktiv et" if is_active else "Aktivləşdir")
        toggle.clicked.connect(lambda *_, k=key: self.toggle_requested.emit(k))
        actions_layout.addWidget(toggle)
        cells.append(actions)

        return cells


class CatalogEntryDialog(QDialog):
    """Kataloq sətrinin yaradılması/redaktəsi — ad + bir dəyər sahəsi.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ ÜÇ AYRI DİALOQ DEYİL
    ──────────────────────────────────────────────────────────────────────────
    `CatalogScreen` üçü üçün ortaqdır (bax modul başlığı) və eyni səbəb burada
    da qüvvədədir: üç kataloqun fərqi YALNIZ ikinci sahənin etiketi və
    izahıdır («Saat aralığı» / «Standart məbləğ» / «Tövsiyə olunan müddət»).
    Üç dialoq eyni validasiya və düymə məntiqini üç dəfə təkrarlayardı.

    ──────────────────────────────────────────────────────────────────────────
    DİALOQ DOMEN QAYDASINI YOXLAMIR
    ──────────────────────────────────────────────────────────────────────────
    Burada yalnız BOŞ sahə tutulur. Formatın (məs. «09:00–18:00») və hədlərin
    (`MAX_LEAVE_DURATION_MINUTES`) doğruluğunu `catalogs.py` value object-ləri
    yoxlayır və mesajları Azərbaycancadır. Qaydanı burada TƏKRARLASAYDIQ, iki
    nüsxə yaranardı və biri dəyişəndə digəri arxada qalardı.

    Signals:
        submitted: (ad, dəyər mətni).
    """

    submitted = Signal(str, str)

    def __init__(
        self,
        theme: ThemeManager,
        *,
        title: str,
        value_label: str,
        value_hint: str = "",
        name: str = "",
        value: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = Card(padding=26, spacing=18)
        layout.addWidget(card)
        card.add(title_label(title, size=19))
        card.add(Divider())

        self._name = FormField("Ad", placeholder="Məsələn: Nahar Fasiləsi")
        self._name.set_text(name)
        card.add(self._name)

        self._value_label = value_label
        self._value = FormField(value_label, hint=value_hint)
        self._value.set_text(value)
        card.add(self._value)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)
        buttons_layout.addWidget(stretch())

        cancel = secondary_button("İmtina")
        cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel)

        save = action_button("Yadda saxla")
        save.clicked.connect(self._on_submit)
        buttons_layout.addWidget(save)
        card.add(buttons)

        # ──────────────────────────────────────────────────────────────────
        # ENTER NƏYİ İŞƏ SALIR — AÇIQ QƏRAR
        # ──────────────────────────────────────────────────────────────────
        # Defolt düymə TƏYİN EDİLMƏSƏYDİ, Qt onu ÖZÜ seçərdi: dialoqdakı ilk
        # `QPushButton` (burada «İmtina») avtomatik defolt olur və Enter işi
        # ləğv edərdi. Bu dialoq DAĞIDICI DEYİL — kataloq sətri yaradır və
        # səhv nəticə asanlıqla geri alınır — ona görə Enter TƏSDİQ edir,
        # yəni ad/dəyər yazan istifadəçi əlini klaviaturadan ayırmır.
        # (Dağıdıcı dialoqlarda qərar TƏRSDİR — bax `group_d.py`/`group_i.py`.)
        save.setDefault(True)
        save.setAutoDefault(True)
        cancel.setAutoDefault(False)

        # Fokus sırası vizual sıra ilə: ad → dəyər → imtina → yadda saxla.
        QWidget.setTabOrder(self._name.input_widget(), self._value.input_widget())
        QWidget.setTabOrder(self._value.input_widget(), cancel)
        QWidget.setTabOrder(cancel, save)

        # İlkin fokus ilk MƏNTİQİ sahədədir — redaktə halında da «Ad»-dır,
        # çünki dəyişdirilməsi ən çox ehtimal olunan sahə odur.
        self._name.focus_input()

    def _on_submit(self) -> None:
        name = self._name.text().strip()
        value = self._value.text().strip()

        # Hər iki sahə AYRICA işarələnir: yalnız birincini göstərsək,
        # istifadəçi onu düzəldib yenidən rədd cavabı alardı.
        self._name.clear_error()
        self._value.clear_error()
        if not name:
            self._name.set_error("Ad məcburidir")
        if not value:
            self._value.set_error(f"«{self._value_label}» məcburidir")
        if not name or not value:
            return

        self.submitted.emit(name, value)
        self.accept()


def work_modes_screen(theme: ThemeManager, *, parent: QWidget | None = None) -> CatalogScreen:
    """İş Rejimləri Kataloqu (bölmə 4, `can_manage_work_modes`)."""
    return CatalogScreen(
        theme,
        columns=[
            Column("Rejim adı"),
            Column("Saat aralığı", 180, mono=True),
            Column("Vəziyyət", 110),
            Column("Əməliyyat", metrics.CATALOG_ACTION_COLUMN_WIDTH),
        ],
        create_label="Yeni İş Rejimi",
        empty_title="İş rejimi təyin edilməyib",
        empty_body=(
            "Növbə matrisində işçiyə rejim təyin etmək üçün əvvəlcə "
            "şablon yaradın — məsələn «08:00–17:00»."
        ),
        footnote=(
            "İşçinin Morning Check-in təsdiqi rejimin başlanğıc saatından "
            "gecdirsə, Gündəlik Tabeldə «Gecikib» kimi işarələnir — bu, "
            "ayrıca cərimə YARATMIR."
        ),
        parent=parent,
    )


def fine_types_screen(theme: ThemeManager, *, parent: QWidget | None = None) -> CatalogScreen:
    """Cərimə Növləri Kataloqu (bölmə 4, `can_manage_fine_types`)."""
    return CatalogScreen(
        theme,
        columns=[
            Column("Cərimə növü"),
            Column("Standart məbləğ", 170),
            Column("Vəziyyət", 110),
            Column("Əməliyyat", metrics.CATALOG_ACTION_COLUMN_WIDTH),
        ],
        create_label="Yeni Cərimə Növü",
        empty_title="Cərimə növü təyin edilməyib",
        empty_body=(
            "Kamera Operatoru yalnız buradakı növlərdən seçə bilər. "
            "Siyahı boş olduqda manual cərimə yazıla bilmir."
        ),
        footnote=(
            "ANTİ-FRAUD: operator sərbəst məbləğ təyin edə bilmir — yalnız "
            "burada təsdiqlənmiş növü və onun standart qiymətini seçir. "
            "Deaktiv edilən növ tarixi qeydlərdə OLDUĞU KİMİ qalır."
        ),
        parent=parent,
    )


def leave_types_screen(theme: ThemeManager, *, parent: QWidget | None = None) -> CatalogScreen:
    """İcazə Növləri Kataloqu (bölmə 4, `can_manage_leave_types`)."""
    return CatalogScreen(
        theme,
        columns=[
            Column("İcazə növü"),
            Column("Tövsiyə olunan müddət", 190),
            Column("Vəziyyət", 110),
            Column("Əməliyyat", metrics.CATALOG_ACTION_COLUMN_WIDTH),
        ],
        create_label="Yeni İcazə Növü",
        empty_title="İcazə növü təyin edilməyib",
        empty_body=(
            "İşçi «İcazə İstəyirəm» addımında bu siyahıdan seçir — "
            "məsələn «Nahar Fasiləsi», «Siqaret Fasiləsi»."
        ),
        footnote=(
            "Növ seçimi yalnız kateqoriyalaşdırma/hesabat üçündür və gecikmə düsturunu DƏYİŞMİR."
        ),
        parent=parent,
    )


# --------------------------------------------------------------------------- #
# 34 — Aylıq Hesabat İxracı
# --------------------------------------------------------------------------- #

#: İki hesabatın ekrandakı təsviri — bölmə 6-dakı ayrılığı GÖRÜNƏN edir.
_REPORT_CARDS: Final[tuple[tuple[str, str, str, str], ...]] = (
    (
        "attendance",
        "Aylıq Davamiyyət Hesabatı",
        "Yalnız FİKS MAAŞ üçün — iş günləri, off-day-lər və icazəsiz qayıblar. "
        "Cərimə məlumatı bu faylda YOXDUR.",
        "file",
    ),
    (
        "bonus_penalty",
        "Premiya və Cərimə Hesabatı",
        "Cərimələr əsas maaşdan DEYİL, aylıq PREMİYADAN kəsilir. "
        "Etiraz pəncərəsi açıq olan və ləğv edilmiş cərimələr daxil edilmir.",
        "fine",
    ),
)


#: Pre-export doğrulama cədvəlinin sütunları (kompas1.md Faza 8, bənd A).
_FINDING_COLUMNS: Final[list[Column]] = [
    Column("Qayda", 190),
    Column("Kim / Hara", 190),
    Column("Nə aşkarlandı"),
]

#: Dövr-üzrə müqayisə cədvəli (bənd F).
_COMPARISON_COLUMNS: Final[list[Column]] = [
    Column("Göstərici", 210),
    Column("Cari dövr", 110, mono=True),
    Column("Keçən dövr", 110, mono=True),
    Column("Fərq", 110, mono=True),
    Column("Vəziyyət"),
]

#: Manual düzəliş jurnalı (bənd D).
_CORRECTION_COLUMNS: Final[list[Column]] = [
    Column("İşçi", 170),
    Column("Tarix", 110, mono=True),
    Column("Dəyişiklik", 230),
    Column("Səbəb"),
]


class ReportExportScreen(Screen):
    """İki AYRI Excel faylının ixracı + export-öncəsi doğrulama.

    Bölmə 6 (`can_export_reports`) + kompas1.md Faza 8 (A, D, E, F, G).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ YENİ EKRAN DEYİL, BU EKRANIN GENİŞLƏNMƏSİ
    ──────────────────────────────────────────────────────────────────────────
    Doğrulama, müqayisə və düzəliş export-un ADDIMLARIDIR, ayrı iş deyil.
    Ayrı ekranda yaşasaydılar, HR əvvəlcə bir ekranda yoxlayıb sonra digərində
    export edərdi — və iki ekran arasında dövr/rol seçimi sükutla fərqlənə
    bilərdi (məhz `menu.py` başlığındakı "ad məkanı uyğunsuzluğu" qüsurunun
    formasıdır). Burada seçim BİRDİR: yuxarıdakı dövr və rol filtri həm
    doğrulamaya, həm yaranan fayla tətbiq olunur.

    ──────────────────────────────────────────────────────────────────────────
    İKİ ADDIM: «Doğrula və Hazırla» → «Təsdiqlə və Export Et»
    ──────────────────────────────────────────────────────────────────────────
    Hesabat kartındakı düymə artıq faylı YAZMIR — `preflight_requested`
    siqnalını verir. Fayl YALNIZ aşağıdakı təsdiq düyməsi ilə yaranır
    (`export_requested`). Səbəb bölmə 6-nın hüquqi tələbindən doğur: fayl
    mühasibatlığa gedən sənəddir və HR onu şübhəli sətirləri GÖRMƏDƏN
    çıxarmamalıdır.

    XƏBƏRDARLIQ BLOKLAMIR: təsdiq düyməsi tapıntı olsa da AKTİV qalır (bax
    `set_validation_findings`).

    ──────────────────────────────────────────────────────────────────────────
    TARİX ARALIĞI: `[Tam Ay]` DEFOLTDUR, `[Xüsusi Aralıq]` ONUN ÜSTÜNƏ QURULUR
    ──────────────────────────────────────────────────────────────────────────
    Faza 7 `ReportRange`-i use case səviyyəsində açdı, GUI isə hələ cari ayı
    sabit işlədirdi. İndi rejim seçicisi var və DEFOLT `[Tam Ay]`-dır: həmin
    rejimdə tarix sahələri GİZLİDİR, yəni ekranın görünüşü və davranışı
    Faza 8-in ilk buraxılışı ilə eynidir (`ReportRange.for_month` → `YYYY-MM`
    açarı, `fines.exported_period` sətirlərinin mənası dəyişmir).

    NİYƏ AVTOMATİK TƏTBİQ YOX, «Aralığı Tətbiq Et» DÜYMƏSİ: tarix sahəsinə
    yazarkən hər simvol yarımçıq tarix doğurur (`2026-0`) və hər dəyişiklikdə
    doğrulamanı yenidən işlətmək 21 filialın aqreqasiyasını onlarla dəfə
    çağırardı. Düymə niyyəti AÇIQ bildirir.

    Signals:
        preflight_requested: Hesabat açarı — doğrulamanı işə salır.
        export_requested: Hesabat açarı — HR təsdiqlədi, fayl yazılsın.
        period_changed: `YYYY-MM`.
        role_filter_changed: Seçilmiş rol kodu (boş = bütün rollar).
        range_changed: (başlanğıc, bitmə) ISO mətnləri; İKİSİ DƏ BOŞ = `[Tam Ay]`.
        correction_requested: «Düzəliş Et» — kontroller dialoqu açır.
    """

    preflight_requested = Signal(str)
    export_requested = Signal(str)
    period_changed = Signal(str)
    role_filter_changed = Signal(str)
    range_changed = Signal(str, str)
    correction_requested = Signal()

    #: Rejim seçicisinin dəyərləri. `""` (tam ay) DEFOLTDUR və `selected_range()`
    #: onu boş cütlə ifadə edir — kontroller «boş = tam ay» qaydasını bir yerdə
    #: oxuyur, iki fərqli bayraq daşımır.
    RANGE_MODE_FULL_MONTH: Final = ""
    RANGE_MODE_CUSTOM: Final = "CUSTOM"

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)
        self._period_label = title_label("", size=15)
        self._lock_note = muted_label("")
        #: Hansı hesabat üçün doğrulama işlədilib — təsdiq düyməsi məhz onu
        #: export edir. Boş qaldıqda təsdiq HEÇ NƏ etmir (bax `_on_confirm`).
        self._active_report = ""
        #: Ekranda görünən cari rəqəmlər (bax `set_row_values`).
        self._row_values: dict[str, dict[str, str]] = {}

        self.add(
            section_header(
                "Aylıq Hesabatlar",
                "İki fayl ayrı məqsədə xidmət edir və qarışdırılmamalıdır.",
            )
        )

        period_card = Card()
        period_body = period_card.body()
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)
        row_layout.addWidget(muted_label("Hesabat dövrü"))
        row_layout.addWidget(self._period_label)
        row_layout.addWidget(self._build_range_mode())
        row_layout.addWidget(stretch())
        row_layout.addWidget(muted_label("Rol filtri"))
        row_layout.addWidget(self._build_role_filter())
        period_body.addWidget(row)
        period_body.addWidget(self._build_custom_range_row())
        self._range_message = muted_label("")
        self._range_message.setWordWrap(True)
        self._range_message.setVisible(False)
        period_body.addWidget(self._range_message)
        period_body.addWidget(self._lock_note)
        self.add(period_card)

        cards = QWidget()
        cards_layout = QHBoxLayout(cards)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(metrics.CARD_SPACING)
        for key, title, description, icon_name in _REPORT_CARDS:
            cards_layout.addWidget(self._build_card(key, title, description, icon_name), 1)
        self.add(cards)

        self.add(self._build_preflight_card())

        # Artıq hündürlüyü SONA yığır. Onsuz Qt boşluğu yuxarıdakı elementlər
        # arasında bölüşdürür və başlıq ilə mətn arasında böyük, izahsız
        # aralıq yaranır (kartlar da lazımsız uzanır).
        self.body().addStretch(1)

    # ------------------------------ qurulma ---------------------------------- #

    def _build_range_mode(self) -> QComboBox:
        """`[Tam Ay]` / `[Xüsusi Aralıq]` seçicisi (kompas1.md Faza 7, bənd 1).

        İki `FilterChip` əvəzinə `QComboBox` seçildi: yanındakı rol filtri
        onsuz da combo-dur və iki qonşu seçim eyni idarəetmə forması ilə
        göstərilməlidir — fərqli forma istifadəçiyə fərqli təbiətli seçim
        olduğu təəssüratı verərdi, halbuki hər ikisi eyni sualı cavablandırır:
        «hansı kəsik export ediləcək?».
        """
        combo = QComboBox()
        combo.addItem("Tam ay", self.RANGE_MODE_FULL_MONTH)
        combo.addItem("Xüsusi aralıq", self.RANGE_MODE_CUSTOM)
        combo.currentIndexChanged.connect(self._on_range_mode_changed)
        self._range_mode = combo
        return combo

    def _build_custom_range_row(self) -> QWidget:
        """Başlanğıc/bitmə tarixləri + «Aralığı Tətbiq Et».

        Sətir `[Tam Ay]` rejimində GİZLİDİR (söndürülmüş deyil): söndürülmüş
        sahələr istifadəçiyə heç vaxt işlətməyəcəyi iki boş qutu göstərərdi və
        defolt görünüş Faza 8-in ilk buraxılışından fərqlənərdi.
        """
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self._range_start = FormField(
            "Başlanğıc", placeholder="2026-08-01", hint="İL-AY-GÜN formatında."
        )
        self._range_end = FormField("Bitmə", placeholder="2026-08-15")
        layout.addWidget(self._range_start, 1)
        layout.addWidget(self._range_end, 1)

        apply_button = secondary_button("Aralığı Tətbiq Et")
        apply_button.setToolTip(
            plain_tooltip(
                "Aralıq tətbiq olunanda doğrulama, dövr-müqayisəsi və qeydlər yenidən yüklənir."
            )
        )
        apply_button.clicked.connect(self._on_range_applied)
        layout.addWidget(apply_button)

        self._custom_range_row = container
        container.setVisible(False)
        return container

    def _build_role_filter(self) -> QComboBox:
        """Rol/vəzifə süzgəci (bənd G) — siyahı KATALOQDAN gəlir.

        Burada YALNIZ «Bütün rollar» sətri var; qalan sətirlər
        `set_role_options()` ilə əlavə olunur. Sabit rol adları YAZILMIR: rol
        kataloqu Root panelindən genişlənə bilər (`positions`) və ekranda
        yazılmış siyahı həmin an köhnəlmiş olardı.
        """
        combo = QComboBox()
        combo.addItem("Bütün rollar", "")
        combo.currentIndexChanged.connect(self._on_role_changed)
        self._role_filter = combo
        return combo

    def _build_card(self, key: str, title: str, description: str, icon_name: str) -> QWidget:
        card = Card()
        body = card.body()

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(10)

        glyph = plain_label()
        glyph.setFixedSize(32, 32)
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glyph.setPixmap(icons.render(icon_name, self.theme.color("--color-action-bg"), size=16))
        glyph.setStyleSheet(
            f"background-color: {self.theme.color('--color-neutral-bg')}; border-radius: 10px;"
        )
        head_layout.addWidget(glyph)
        head_layout.addWidget(title_label(title, size=15))
        head_layout.addWidget(stretch())
        body.addWidget(head)

        explanation = muted_label(description)
        explanation.setWordWrap(True)
        body.addWidget(explanation)
        body.addWidget(Divider())

        button = action_button(
            "Doğrula və Hazırla",
            icon_name="download",
            icon_color=self.theme.color("--color-action-text"),
        )
        button.setToolTip(
            plain_tooltip(
                "Fayl HƏLƏ yaranmır: şübhəli sətirlər və keçən dövrlə fərq aşağıda göstərilir."
            )
        )
        button.clicked.connect(lambda *_, k=key: self._on_preflight(k))
        body.addWidget(button)
        return card

    def _build_preflight_card(self) -> Card:
        """Doğrulama + müqayisə + düzəliş bölməsi — BİR kartda.

        Üç ayrı kart əvəzinə bir kart: üçü də EYNİ seçimə (dövr + rol) aiddir
        və HR onları ardıcıl oxuyur — şübhəli sətir → keçən dövrlə fərq →
        edilmiş düzəlişlər → təsdiq. Ayrı kartlar bu ardıcıllığı vizual olaraq
        pozardı.
        """
        card = Card(padding=22, spacing=14)
        card.add(title_label("Export-öncəsi Doğrulama", size=17))
        card.add(
            muted_label(
                "Fayl yaranmazdan ƏVVƏL şübhəli sətirlər burada göstərilir. "
                "Bu, XƏBƏRDARLIQDIR — export bloklanmır, son qərar sizindir."
            )
        )
        card.add(Divider())

        self._preflight_message = muted_label("")
        self._preflight_message.setWordWrap(True)
        card.add(self._preflight_message)

        self._finding_table = DataTable(
            _FINDING_COLUMNS,
            self.theme,
            footnote="Xəbərdarlıq export-u BLOKLAMIR — sətirlər fayla daxil olur.",
        )
        card.add(self._finding_table)

        card.add(Divider())
        card.add(title_label("Keçən eyni-uzunluqda dövrlə müqayisə", size=15))
        self._comparison_caption = muted_label("")
        self._comparison_caption.setWordWrap(True)
        card.add(self._comparison_caption)
        self._comparison_table = DataTable(_COMPARISON_COLUMNS, self.theme)
        card.add(self._comparison_table)

        self._corrections_card = QWidget()
        corrections_layout = QVBoxLayout(self._corrections_card)
        corrections_layout.setContentsMargins(0, 0, 0, 0)
        corrections_layout.setSpacing(12)
        corrections_layout.addWidget(Divider())

        corrections_head = QWidget()
        head_layout = QHBoxLayout(corrections_head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(10)
        head_layout.addWidget(title_label("Manual düzəlişlər", size=15))
        head_layout.addWidget(stretch())
        self._correction_button = secondary_button("Düzəliş Et")
        self._correction_button.setToolTip(
            plain_tooltip(
                "Düzəliş mənbə qeydini DƏYİŞMİR — export anında tətbiq olunan "
                "ayrıca audit sətridir."
            )
        )
        self._correction_button.clicked.connect(self.correction_requested)
        head_layout.addWidget(self._correction_button)
        corrections_layout.addWidget(corrections_head)

        self._correction_table = DataTable(
            _CORRECTION_COLUMNS,
            self.theme,
            footnote="Düzəliş sətri SİLİNMİR və REDAKTƏ EDİLMİR — yenisi əlavə olunur.",
        )
        corrections_layout.addWidget(self._correction_table)
        card.add(self._corrections_card)
        # GÖRMƏK = SƏLAHİYYƏTİN OLMASI: flag yoxdursa bölmə söndürülmür,
        # TAMAMİLƏ gizlədilir (bax `set_correction_access`). Defolt GİZLİDİR —
        # kontroller icazəni təsdiqləyənə qədər görünməməlidir (fail-closed).
        self._corrections_card.setVisible(False)

        card.add(Divider())
        confirm_row = QWidget()
        confirm_layout = QHBoxLayout(confirm_row)
        confirm_layout.setContentsMargins(0, 0, 0, 0)
        confirm_layout.setSpacing(12)
        confirm_layout.addWidget(stretch())
        self._confirm_button = action_button(
            "Təsdiqlə və Export Et",
            icon_name="download",
            icon_color=self.theme.color("--color-action-text"),
        )
        self._confirm_button.clicked.connect(self._on_confirm)
        confirm_layout.addWidget(self._confirm_button)
        card.add(confirm_row)

        self._preflight_card = card
        # Doğrulama işlədilməyincə bölmə boşdur — göstərilsəydi, HR boş
        # cədvəlləri "problem yoxdur" kimi oxuyardı, halbuki yoxlama HEÇ
        # APARILMAYIB.
        card.setVisible(False)
        return card

    # ------------------------------ siqnal körpüləri -------------------------- #

    def _on_role_changed(self, index: int) -> None:
        code = self._role_filter.itemData(index)
        self.role_filter_changed.emit("" if code is None else str(code))

    def _on_range_mode_changed(self, index: int) -> None:
        """Rejim dəyişdi — tarix sətri göstərilir/gizlədilir.

        `[Tam Ay]`-a QAYIDIŞ dərhal siqnal verir (boş cütlə), çünki orada
        tətbiq ediləcək əlavə məlumat yoxdur — istifadəçidən ikinci klik
        tələb etmək mənasız olardı. `[Xüsusi Aralıq]`-a keçid isə siqnal
        VERMİR: sahələr hələ boşdur və dərhal xəta göstərmək düzgün deyil.
        """
        custom = self._range_mode.itemData(index) == self.RANGE_MODE_CUSTOM
        self._custom_range_row.setVisible(custom)
        self.set_range_message("")
        if not custom:
            self._range_start.clear_error()
            self._range_end.clear_error()
            self.range_changed.emit("", "")

    def _on_range_applied(self) -> None:
        """«Aralığı Tətbiq Et» — YALNIZ boşluq yoxlanılır.

        Tarixin FORMATI və uzunluq həddi (`REPORT_RANGE_MAX_DAYS`) burada
        yoxlanmır: birincisi `date.fromisoformat`, ikincisi
        `MonthlyReportUseCase.resolve_range` işidir və hər ikisinin mesajı
        Azərbaycancadır. Qaydanı ekranda təkrarlasaydıq, ROOT həddi
        dəyişəndə iki nüsxədən biri arxada qalardı.
        """
        start = self._range_start.text().strip()
        end = self._range_end.text().strip()
        self._range_start.clear_error()
        self._range_end.clear_error()
        if not start:
            self._range_start.set_error("Başlanğıc tarixi məcburidir")
        if not end:
            self._range_end.set_error("Bitmə tarixi məcburidir")
        if not start or not end:
            return
        self.range_changed.emit(start, end)

    def _on_preflight(self, key: str) -> None:
        self._active_report = key
        self.preflight_requested.emit(key)

    def _on_confirm(self) -> None:
        if not self._active_report:
            # Doğrulama işlədilməyibsə təsdiqləyəcək bir şey yoxdur. Sükutla
            # geri qayıtmaq düzgündür: düymə onsuz da yalnız doğrulamadan sonra
            # görünən kartdadır, bu, yalnız proqram-səviyyəli çağırışa qarşı
            # qoruyucudur.
            return
        self.export_requested.emit(self._active_report)

    # ------------------------------ setter API -------------------------------- #

    def set_period(self, label: str) -> None:
        self._period_label.setText(label)

    def set_lock_summary(
        self,
        deferred_fines: int,
        *,
        already_exported: int = 0,
        overlap_notice: str = "",
    ) -> None:
        """LOCK vəziyyəti — İKİ AYRI səbəb, İKİ AYRI cümlə.

        Bölmə 6: "Export ekranında hər sətir üçün «etiraz pəncərəsi vəziyyəti»
        (bağlı/açıq) aydın göstərilir". Sıfır olduqda da mətn göstərilir —
        istifadəçi "heç bir cərimə gözləmir" cavabını görməlidir, boşluğu yox.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ İKİ SAYĞAC BİRLƏŞDİRİLMİR
        ──────────────────────────────────────────────────────────────────────
        Cərimə fayldan İKİ tamamilə fərqli səbəbə görə çıxa bilər:
          * 72 saatlıq etiraz pəncərəsi HƏLƏ AÇIQ — cərimə GƏLƏCƏK dövrdə
            yenidən qiymətləndiriləcək (müvəqqəti);
          * ARTIQ başqa bir dövrdə tutulub — bir daha HEÇ VAXT tutulmayacaq
            (üst-üstə düşən aralıq, Faza 7).
        Tək rəqəmdə birləşdirilsəydi, HR "bu pul nə vaxt tutulacaq?" sualına
        cavab ala bilməzdi. `overlap_notice` mətni ekranda QURULMUR —
        `BonusPenaltySelection.overlap_notice_az()`-dan gəlir, çünki eyni
        cümlə audit sətrində də lazımdır.
        """
        if deferred_fines:
            lines = [
                f"{deferred_fines} cərimənin 72 saatlıq etiraz pəncərəsi hələ AÇIQDIR — "
                f"bu dövrün Premiya və Cərimə faylına daxil edilməyəcək, "
                f"növbəti dövrdə yenidən qiymətləndiriləcək."
            ]
        else:
            lines = ["Bütün cərimələrin etiraz pəncərəsi BAĞLIDIR — təxirə salınan qeyd yoxdur."]
        if already_exported:
            lines.append(
                overlap_notice
                or (
                    f"{already_exported} cərimə bu aralığa düşür, lakin artıq əvvəlki "
                    f"dövr(lər)də tutulub — təkrar tutulmur."
                )
            )
        self._lock_note.setText(" ".join(lines))
        self.show_content()

    def set_range_selection(self, *, custom: bool, start: str = "", end: str = "") -> None:
        """Rejim + tarix sahələrini proqram yolu ilə qurur.

        Siqnal MÜVƏQQƏTİ SUSDURULUR (`set_role_options` ilə eyni səbəb):
        `setCurrentIndex` `currentIndexChanged`-i doğurur və kontroller ilk
        qurulma anında yenidən-oxu dövrəsinə düşərdi.
        """
        blocked = self._range_mode.blockSignals(True)
        try:
            mode = self.RANGE_MODE_CUSTOM if custom else self.RANGE_MODE_FULL_MONTH
            index = self._range_mode.findData(mode)
            self._range_mode.setCurrentIndex(max(index, 0))
        finally:
            self._range_mode.blockSignals(blocked)
        self._custom_range_row.setVisible(custom)
        self._range_start.set_text(start)
        self._range_end.set_text(end)
        self._range_start.clear_error()
        self._range_end.clear_error()

    def selected_range(self) -> tuple[str, str]:
        """(başlanğıc, bitmə) ISO mətnləri; İKİSİ DƏ BOŞ = `[Tam Ay]`.

        Mətn qaytarılır, `date` YOX: ekran domen/tətbiq tiplərini TANIMIR
        (`fine_entry.py` başlığındakı qayda) və format səhvinin mesajı
        kontrollerdə, istifadəçi dilində qurulur.
        """
        if self._range_mode.currentData() != self.RANGE_MODE_CUSTOM:
            return ("", "")
        return (self._range_start.text().strip(), self._range_end.text().strip())

    def set_range_message(self, message: str, *, error: bool = False) -> None:
        """Aralıq seçicisinin YANINDA göstərilən mesaj.

        Aralıq xətası (format, çox uzun aralıq) QƏSDƏN doğrulama kartında
        deyil, BURADA göstərilir: düzəliş məhz bu iki sahədədir və mesajı
        ekranın aşağısına yazmaq istifadəçini səhvin yerindən uzaqlaşdırardı.
        """
        self._range_message.setText(message)
        self._range_message.setProperty("variant", "danger-text" if error else "muted")
        self._range_message.setVisible(bool(message))
        refresh_widget_style(self._range_message)

    def set_role_options(self, options: list[dict[str, str]], *, selected: str = "") -> None:
        """Rol filtri seçimləri (bənd G) — açarlar `code` və `name`.

        Siyahı yenilənərkən siqnal MÜVƏQQƏTİ SUSDURULUR: `addItem()` hər
        çağırışda `currentIndexChanged` doğurur və kontroller doldurmanın
        ortasında yarımçıq seçimlə yenidən oxumağa başlayardı (sonsuz dövrə
        riski).
        """
        blocked = self._role_filter.blockSignals(True)
        try:
            self._role_filter.clear()
            self._role_filter.addItem("Bütün rollar", "")
            for option in options:
                self._role_filter.addItem(option.get("name", ""), option.get("code", ""))
            index = self._role_filter.findData(selected)
            self._role_filter.setCurrentIndex(max(index, 0))
        finally:
            self._role_filter.blockSignals(blocked)

    def selected_role(self) -> str:
        """Hazırda seçilmiş rol kodu (boş = bütün rollar)."""
        data = self._role_filter.currentData()
        return "" if data is None else str(data)

    def active_report(self) -> str:
        """Doğrulaması işlədilmiş hesabat açarı (boş = hələ seçilməyib)."""
        return self._active_report

    def set_row_values(self, values: dict[str, dict[str, str]]) -> None:
        """Ekranda GÖRÜNƏN cari rəqəmlər — düzəliş dialoqunun «köhnə dəyəri».

        Açar quruluşu: `{işçi ID mətni: {sahə kodu: dəyər}}`. Ekran bu sözlüyü
        HEÇ YERDƏ göstərmir — o, yalnız audit sualının ("istifadəçi NƏYİ gördü
        və nəyə dəyişdi?") cavabıdır. Bazadan oxumaq həmin cavabı təhrif
        edərdi: başqa bir HR bu arada düzəliş yazmış ola bilər.
        """
        self._row_values = {employee_id: dict(fields) for employee_id, fields in values.items()}

    def current_value(self, employee_id: object, field: str) -> str | None:
        """`set_row_values()` ilə verilmiş cari dəyər (tapılmasa `None`)."""
        return self._row_values.get(str(employee_id), {}).get(field)

    def set_validation_findings(self, rows: list[dict[str, str]]) -> None:
        """Şübhəli sətirlər (bənd A) — açarlar `rule`, `subject`, `detail`.

        Tapıntı olmadıqda cədvəl GİZLƏNİR və müsbət mətn göstərilir: boş cədvəl
        "yoxlama aparılmadı" kimi də oxuna bilər, açıq cümlə isə yox.

        Təsdiq düyməsi BURADA SÖNDÜRÜLMÜR — bloklama YOXDUR (bax sinif başlığı).
        """
        self._preflight_card.setVisible(True)
        self._finding_table.clear()
        self._finding_table.setVisible(bool(rows))
        for row in rows:
            self._finding_table.add_row(
                [
                    Chip(row.get("rule", ""), "danger"),
                    row.get("subject", ""),
                    row.get("detail", ""),
                ]
            )
        if rows:
            self.set_preflight_message(
                f"{len(rows)} şübhəli sətir tapıldı — yoxlayın. "
                f"Export BLOKLANMIR: nəzərdən keçirdikdən sonra təsdiqləyə bilərsiniz.",
                error=True,
            )
        else:
            self.set_preflight_message("Şübhəli sətir tapılmadı — export üçün hazırdır.")
        self.show_content()

    def set_period_comparison(self, rows: list[dict[str, str]], *, caption: str = "") -> None:
        """Dövr-üzrə müqayisə (bənd F) — açarlar `metric`, `current`,
        `previous`, `delta`, `significant` (`"1"` = ROOT həddini aşır).

        Keçən dövr məlumatı olmadıqda (`rows` boş) cədvəl gizlənir və izah
        göstərilir — sıfırlarla dolu cədvəl "keçən dövr sıfır idi" kimi oxunar,
        halbuki doğru cavab "bilinmir"dir.
        """
        self._comparison_caption.setText(
            caption or "Keçən dövr üçün məlumat yoxdur — müqayisə göstərilmir."
        )
        self._comparison_table.clear()
        self._comparison_table.setVisible(bool(rows))
        for row in rows:
            significant = row.get("significant") == "1"
            self._comparison_table.add_row(
                [
                    row.get("metric", ""),
                    row.get("current", ""),
                    row.get("previous", ""),
                    row.get("delta", ""),
                    Chip("Əhəmiyyətli fərq", "danger") if significant else Chip("Sabit", "neutral"),
                ]
            )

    def set_corrections(self, rows: list[dict[str, str]]) -> None:
        """Manual düzəliş jurnalı (bənd D) — açarlar `employee`, `date`,
        `change`, `reason`."""
        self._correction_table.clear()
        self._correction_table.setVisible(bool(rows))
        for row in rows:
            self._correction_table.add_row(
                [
                    row.get("employee", ""),
                    row.get("date", ""),
                    row.get("change", ""),
                    row.get("reason", ""),
                ]
            )

    def set_correction_access(self, *, allowed: bool) -> None:
        """`can_manage_export_corrections` yoxdursa bölmə GİZLƏNİR.

        Söndürülmüş düymə DEYİL, gizlədilmiş bölmə: layihənin "GÖRMƏK =
        SƏLAHİYYƏTİN OLMASI" prinsipi (`menu.py` başlığı). Söndürülmüş düymə
        istifadəçiyə mövcud olmayan bir imkanı vəd edər və "niyə basıla
        bilmir?" sualı ilə dəstəyə müraciət doğurardı.
        """
        self._corrections_card.setVisible(allowed)

    def set_preflight_message(self, message: str, *, error: bool = False) -> None:
        self._preflight_message.setText(message)
        self._preflight_message.setProperty("variant", "danger-text" if error else "muted")
        self._preflight_message.setVisible(bool(message))
        refresh_widget_style(self._preflight_message)

    def show_preflight_section(self) -> None:
        """Doğrulama bölməsini görünən edir (kontroller xəta mesajı göstərəndə).

        `set_validation_findings` onsuz da görünür edir; bu metod isə oxu
        UĞURSUZ olduqda lazımdır — mesaj gizli kartda qalsaydı, istifadəçi
        düyməni basıb HEÇ BİR cavab görməzdi.
        """
        self._preflight_card.setVisible(True)
        self.show_content()


class ExportCorrectionDialog(QDialog):
    """Manual export düzəlişi (kompas1.md Faza 8, bənd D).

    Naxış `group_c.PosThresholdDialog` / `EmployeeDocumentDialog`-dandır:
    kart-daxilində forma, sağda «İmtina» + təsdiq düyməsi, `QPlainTextEdit`
    səbəb sahəsi.

    ──────────────────────────────────────────────────────────────────────────
    SƏBƏB SAHƏSİ NİYƏ BURADA DA YOXLANILIR
    ──────────────────────────────────────────────────────────────────────────
    HƏQİQİ qapı use case-dədir (`ExportPreflightUseCase.record_correction` →
    `EXPORT_CORRECTION_REASON_MIN_LENGTH`) və DB-də CHECK kimi TƏKRARLANIR.
    Buradakı üçüncü yoxlama onları ƏVƏZ ETMİR — YALNIZ dərhal, sətir-altı
    xəbərdarlıq verir: minimum uzunluq ROOT-dan gəlir və dialoqa arqument kimi
    ötürülür, ekranda SABİT YAZILMIR (hardcode qadağandır).

    ──────────────────────────────────────────────────────────────────────────
    KÖHNƏ DƏYƏR NİYƏ REDAKTƏ EDİLƏ BİLMİR
    ──────────────────────────────────────────────────────────────────────────
    «Köhnə dəyər» sahəsi YALNIZ-OXUdur: o, sistemin hazırkı rəqəmidir və
    istifadəçinin onu yazması auditi mənasız edərdi ("nədən dəyişdi?" sualına
    istifadəçinin öz cavabı). Dəyər kontrollerdən, cari export sətrindən gəlir.

    Signals:
        submitted: (işçi ID, tarix `YYYY-MM-DD`, sahə kodu, yeni dəyər, səbəb).
    """

    submitted = Signal(str, str, str, str, str)

    def __init__(
        self,
        theme: ThemeManager,
        *,
        employees: list[tuple[str, str]],
        fields: list[tuple[str, str]],
        default_date: str,
        reason_min_length: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._reason_min_length = reason_min_length
        self.setWindowTitle("Export Düzəlişi")
        self.setModal(True)
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = Card(padding=26, spacing=18)
        layout.addWidget(card)
        card.add(title_label("Export Düzəlişi", size=19))
        card.add(
            muted_label(
                "Düzəliş mənbə qeydini (kamera təsdiqli davamiyyət) DƏYİŞMİR — "
                "export anında tətbiq olunan ayrıca audit sətri yaradır.",
                size=12,
            )
        )
        card.add(Divider())

        self._employee = QComboBox()
        for employee_id, name in employees:
            self._employee.addItem(name, employee_id)
        card.add(field_label("İşçi"))
        card.add(self._employee)

        self._field = QComboBox()
        for code, label in fields:
            self._field.addItem(label, code)
        card.add(field_label("Düzəldilən sütun"))
        card.add(self._field)

        self._date = FormField(
            "Tarix",
            placeholder="2026-08-13",
            hint="Düzəlişin aid olduğu təqvim günü (İL-AY-GÜN).",
        )
        self._date.set_text(default_date)
        card.add(self._date)

        self._value = FormField(
            "Yeni dəyər",
            hint="Ədədi sütunlar üçün tam say; «Qeyd» sütunu üçün sərbəst mətn.",
        )
        card.add(self._value)

        reason_box = QWidget()
        reason_layout = QVBoxLayout(reason_box)
        reason_layout.setContentsMargins(0, 0, 0, 0)
        reason_layout.setSpacing(7)
        reason_layout.addWidget(field_label("Səbəb (MƏCBURİ)"))
        self._reason = QPlainTextEdit()
        self._reason.setPlaceholderText(
            f"Düzəliş NİYƏ edilir? Ən azı {reason_min_length} simvol — "
            f"səbəbsiz düzəliş auditdə dəyərsizdir."
        )
        self._reason.setFixedHeight(84)
        reason_layout.addWidget(self._reason)
        self._reason_error = muted_label("")
        self._reason_error.setWordWrap(True)
        self._reason_error.setVisible(False)
        reason_layout.addWidget(self._reason_error)
        card.add(reason_box)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)
        buttons_layout.addWidget(stretch())

        cancel = secondary_button("İmtina")
        cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel)

        save = action_button("Düzəlişi Yaz")
        save.clicked.connect(self._on_submit)
        buttons_layout.addWidget(save)
        card.add(buttons)

        # ENTER QƏSDƏN TƏSDİQ ETMİR: bu dialoq AUDİT sətri yaradır və sətir
        # SİLİNMİR/REDAKTƏ EDİLMİR (migrations/037). Səbəb sahəsində Enter
        # onsuz da yeni sətir deməkdir; `setDefault(False)` isə təsadüfi
        # təsdiqin qarşısını alır (dağıdıcı dialoqlarda `group_d.py`-dəki
        # eyni qərar).
        save.setDefault(False)
        save.setAutoDefault(False)
        cancel.setAutoDefault(False)

        QWidget.setTabOrder(self._employee, self._field)
        QWidget.setTabOrder(self._field, self._date.input_widget())
        QWidget.setTabOrder(self._date.input_widget(), self._value.input_widget())
        QWidget.setTabOrder(self._value.input_widget(), self._reason)
        QWidget.setTabOrder(self._reason, cancel)
        QWidget.setTabOrder(cancel, save)

        self._value.focus_input()

    def _on_submit(self) -> None:
        """Boş sahə + tarix formatı + səbəb uzunluğu — HAMISI birlikdə.

        Sahələr AYRICA işarələnir: yalnız birincini göstərsək, istifadəçi onu
        düzəldib yenidən rədd cavabı alardı (`CatalogEntryDialog._on_submit`
        ilə eyni qərar).
        """
        from datetime import date  # noqa: PLC0415 — yalnız format yoxlaması üçün

        self._date.clear_error()
        self._value.clear_error()
        self._reason_error.setVisible(False)

        raw_date = self._date.text().strip()
        value = self._value.text().strip()
        reason = self._reason.toPlainText().strip()

        valid = True
        if not raw_date:
            self._date.set_error("Tarix məcburidir")
            valid = False
        else:
            try:
                date.fromisoformat(raw_date)
            except ValueError:
                self._date.set_error("Tarix formatı: İL-AY-GÜN (məs. 2026-08-13)")
                valid = False
        if not value:
            self._value.set_error("Yeni dəyər məcburidir")
            valid = False
        if len(reason) < self._reason_min_length:
            self._reason_error.setText(
                f"Səbəb ən azı {self._reason_min_length} simvol olmalıdır — "
                f"indi {len(reason)} simvoldur."
            )
            self._reason_error.setProperty("variant", "danger-text")
            self._reason_error.setVisible(True)
            refresh_widget_style(self._reason_error)
            valid = False
        if not valid:
            return

        employee_id = self._employee.currentData()
        field_code = self._field.currentData()
        self.submitted.emit(
            "" if employee_id is None else str(employee_id),
            raw_date,
            "" if field_code is None else str(field_code),
            value,
            reason,
        )
        self.accept()


# --------------------------------------------------------------------------- #
# 35 — Yardım Mərkəzi
# --------------------------------------------------------------------------- #

#: Yardım məqalələri — modul açarı → (başlıq, addımlar).
#: Mətnlər BURADADIR, ayrıca fayl deyil: onlar interfeys mətnidir və ekranla
#: birlikdə dəyişir; ayrı JSON-a çıxarılsaydı, sinxronsuzluq riski yaranardı.
HELP_TOPICS: Final[tuple[tuple[str, str, tuple[str, ...]], ...]] = (
    (
        "leave",
        "İcazə və qayıdış təsdiqi",
        (
            "İşçi «İcazə İstəyirəm» düyməsi ilə icazə növünü seçir — vaxt "
            "möhürü NTP serverinə qarşı yoxlanılır.",
            "Qayıdanda «Mən Qayıtdım» basılır və sorğu Kamera Operatorunun Canlı Növbəsinə düşür.",
            "Operator kameraya baxıb təsdiqləyir; gecikmə varsa cərimə "
            "avtomatik hesablanır (Total = Requested + 2 × Delay).",
            "Təsdiq gecikirsə sorğu avtomatik eskalasiya olunur — HR_Admin "
            "və ya CEO əl ilə təsdiq edə bilər.",
        ),
    ),
    (
        "fines",
        "Cərimələr və etiraz",
        (
            "Cərimə əvvəlcə «İcmal gözləyir» vəziyyətində yaranır — işçi onu hələ GÖRMÜR.",
            "Ayın əvvəlində səlahiyyətli şəxs bütün filialların cərimələrini "
            "bir cədvəldə nəzərdən keçirir və tək düymə ilə nəşr edir.",
            "Nəşrdən sonra işçinin 72 saatlıq etiraz hüququ başlayır.",
            "Etiraz pəncərəsi bağlanana qədər cərimə heç bir hesabata "
            "DÜŞMÜR — bu, hüquqi tələbdir.",
        ),
    ),
    (
        "shifts",
        "Növbə planlaması və dəyişmə",
        (
            "İş Rejimləri kataloqunda şablon yaradılır (məs. «08:00–17:00»).",
            "Növbə Matrisində işçiyə həmin şablon təyin edilir.",
            "İşçi növbə dəyişmə sorğusu göndərə bilər; təsdiq "
            "`can_approve_shift_swap` sahibindədir.",
            "Gündəlik Tabel HR planı ilə faktiki davamiyyəti müqayisə edir.",
        ),
    ),
    (
        "erp",
        "1C / ERP bağlantısı",
        (
            "Hər server ayrıca əlavə olunur və «Bağlantını Test Et» ilə "
            "yoxlanılır — test uğursuz olarsa konfiqurasiya YAZILMIR.",
            "Mağazalar serverlərə ayrıca xəritələnir.",
            "Uyğunlaşdırıla bilməyən satışlar «Şübhəli Satışlar» növbəsinə "
            "düşür və əl ilə həll olunur.",
        ),
    ),
    (
        "points",
        "Satış xalları və mükafatlar",
        (
            "Xallar 1C-dən sinxronlaşdırılan satışlara görə avtomatik verilir.",
            "Səhv hesablanmış xala 72 saat ərzində etiraz göndərmək olar.",
            "Xallar hər 6 ayda (1 Yanvar və 1 İyul) sıfırlanır — "
            "14 gün əvvəldən xəbərdarlıq gedir.",
            "Mükafat kataloqundan seçim edərək xalı istifadə etmək olar.",
        ),
    ),
    (
        "support",
        "Problem yaşayırsınızsa",
        (
            "Sağ-alt küncdəki dəstək düyməsi ilə birbaşa müraciət göndərin.",
            "«Sistem Sağlamlığı» ekranı bağlantı, sinxronizasiya və saat "
            "fərqi problemlərini özü aşkarlayır və düzəliş ekranına yönləndirir.",
            "Tətbiq açılmırsa, mağaza PC-sindəki nəzarətçi onu avtomatik "
            "yenidən başladır — bir neçə saniyə gözləyin.",
        ),
    ),
)


class TopicChip(Chip):
    """Kliklənə bilən mövzu nişanı.

    `Chip` sadə `QLabel`-dir; kliki dəstəkləmək üçün ayrıca siqnal lazımdır.
    `LinkLabel` istifadə edilmədi, çünki nişan forması (yumşaq fon + yumru
    kənar) burada məhz filtr çubuğunun vizual dilidir.

    Signals:
        clicked: Mövzu açarı.
    """

    clicked = Signal(str)

    def __init__(self, key: str, text: str, *, parent: QWidget | None = None) -> None:
        super().__init__(text, "neutral", parent=parent)
        self.key = key
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 — Qt adı
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)
        super().mouseReleaseEvent(event)


class HelpTopicCard(Card):
    """Bir yardım mövzusu — nömrələnmiş addımlarla."""

    def __init__(
        self,
        title: str,
        steps: tuple[str, ...],
        theme: ThemeManager,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)
        body = self.body()
        body.addWidget(title_label(title, size=15))
        body.addWidget(Divider())

        for index, step in enumerate(steps, start=1):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(10)

            number = plain_label(str(index))
            number.setFixedSize(22, 22)
            number.setAlignment(Qt.AlignmentFlag.AlignCenter)
            number.setStyleSheet(
                f"background-color: {theme.color('--color-neutral-bg')};"
                f"color: {theme.color('--color-text-secondary')};"
                f"border-radius: 11px; font-size: 11px;"
            )
            row_layout.addWidget(number, alignment=Qt.AlignmentFlag.AlignTop)

            text = body_label(step)
            text.setWordWrap(True)
            row_layout.addWidget(text, 1)
            body.addWidget(row)


class HelpCenterScreen(Screen):
    """Kontekstli yardım və təlimatlar (5-ci faza, bənd 3).

    Səlahiyyət TƏLƏB OLUNMUR: yardım mətnini gizlətmək dəstək yükünü artırar,
    azaltmaz. Mövzular isə istifadəçinin GÖRDÜYÜ modullara görə süzülə bilər
    (`set_visible_topics`) — görmədiyi bir modulun təlimatı ona kömək etməz.

    Signals:
        topic_selected: Mövzu açarı.
        support_requested: "Dəstəyə yaz".
    """

    topic_selected = Signal(str)
    support_requested = Signal()

    def __init__(
        self,
        theme: ThemeManager,
        *,
        may_contact_support: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(theme, parent=parent)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)
        header_layout.addWidget(
            section_header(
                "Yardım Mərkəzi",
                "Ən çox verilən sualların addım-addım cavabı.",
            ),
            1,
        )
        # «GÖRMƏK = SƏLAHİYYƏTİN OLMASI» (bölmə 8, sətir 279): `can_contact_support`
        # olmayan istifadəçidə düymə NƏ SÖNDÜRÜLÜR, NƏ GİZLƏDİLİR — ümumiyyətlə
        # QURULMUR. Eyni qayda üzən dəstək ikonuna da tətbiq olunur
        # (`app.py::_install_overlays`) və iki yerin AYRILMASI qüsur olardı:
        # ikonu kəsib düyməni saxlasaydıq, icazəsiz istifadəçi yenə "dəstəyə
        # yaza bilirəm" nəticəsinə gələrdi.
        #
        # Defolt `True`-dur ki, önizləmə/dizayn rejimi (real istifadəçi konteksti
        # olmayan yol) bütün ekranı göstərə bilsin — `app.py` canlı rejimdə
        # dəyəri açıq şəkildə ötürür.
        if may_contact_support:
            contact = secondary_button("Dəstəyə yaz")
            contact.clicked.connect(self.support_requested)
            header_layout.addWidget(contact, alignment=Qt.AlignmentFlag.AlignTop)
        self.add(header)

        self._chip_row = QWidget()
        self._chip_layout = QHBoxLayout(self._chip_row)
        self._chip_layout.setContentsMargins(0, 0, 0, 0)
        self._chip_layout.setSpacing(8)
        self.add(self._chip_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        host = QWidget()
        self._topics_layout = QVBoxLayout(host)
        self._topics_layout.setContentsMargins(0, 0, 0, 0)
        self._topics_layout.setSpacing(metrics.CARD_SPACING)
        self._topics_layout.addStretch(1)
        scroll.setWidget(host)
        self.add(scroll)

        self.set_visible_topics(None)

    def set_visible_topics(self, keys: frozenset[str] | None) -> None:
        """Mövzuları süzür.

        Args:
            keys: Göstəriləcək mövzu açarları. `None` → HAMISI (defolt).
                Boş çoxluq da icazəlidir və "heç nə yoxdur" vəziyyətini
                göstərir — bu, səhv deyil, yeni quraşdırılmış sistemin
                normal halıdır.
        """
        clear_layout(self._chip_layout)
        clear_layout(self._topics_layout, keep_last=1)

        topics = [topic for topic in HELP_TOPICS if keys is None or topic[0] in keys]
        if not topics:
            self.show_empty(
                icon_name="help",
                title="Yardım mövzusu yoxdur",
                message="Sizin görə bildiyiniz modullar üçün hələ təlimat əlavə edilməyib.",
            )
            return

        for key, title, _steps in topics:
            chip = TopicChip(key, az_upper(title.split()[0]))
            # Tooltip `setTextFormat`-a tabe deyil: nişanın mətni `Chip`-də
            # düz mətndir, tooltip isə ayrıca süzülməlidir. Mövzu başlıqları
            # hazırda sabitdir, lakin siyahı plagin/DB mənbəyinə açıqdır.
            chip.setToolTip(plain_tooltip(title))
            chip.clicked.connect(self.topic_selected)
            self._chip_layout.addWidget(chip)
        self._chip_layout.addWidget(stretch())

        for _key, title, steps in topics:
            card = HelpTopicCard(title, steps, self.theme)
            self._topics_layout.insertWidget(self._topics_layout.count() - 1, card)

        self.show_content()


__all__ = [
    "HELP_TOPICS",
    "CatalogEntryDialog",
    "CatalogScreen",
    "ExportCorrectionDialog",
    "HelpCenterScreen",
    "HelpTopicCard",
    "ReportExportScreen",
    "TopicChip",
    "fine_types_screen",
    "leave_types_screen",
    "work_modes_screen",
]
