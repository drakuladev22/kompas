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
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.presentation.i18n.text import az_upper
from src.presentation.screens.base import Screen, section_header
from src.presentation.widgets import icons, metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.data_table import Column, DataTable
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import (
    Card,
    Chip,
    Divider,
    body_label,
    muted_label,
    stretch,
    title_label,
)

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


def work_modes_screen(theme: ThemeManager, *, parent: QWidget | None = None) -> CatalogScreen:
    """İş Rejimləri Kataloqu (bölmə 4, `can_manage_work_modes`)."""
    return CatalogScreen(
        theme,
        columns=[
            Column("Rejim adı"),
            Column("Saat aralığı", 180, mono=True),
            Column("Status", 110),
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
            Column("Status", 110),
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
            Column("Status", 110),
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


class ReportExportScreen(Screen):
    """İki AYRI Excel faylının ixracı (bölmə 6, `can_export_reports`).

    Signals:
        export_requested: Hesabat açarı (`attendance` / `bonus_penalty`).
        period_changed: `YYYY-MM`.
    """

    export_requested = Signal(str)
    period_changed = Signal(str)

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)
        self._period_label = title_label("", size=15)
        self._lock_note = muted_label("")

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
        row_layout.addWidget(stretch())
        period_body.addWidget(row)
        period_body.addWidget(self._lock_note)
        self.add(period_card)

        cards = QWidget()
        cards_layout = QHBoxLayout(cards)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(metrics.CARD_SPACING)
        for key, title, description, icon_name in _REPORT_CARDS:
            cards_layout.addWidget(self._build_card(key, title, description, icon_name), 1)
        self.add(cards)

        # Artıq hündürlüyü SONA yığır. Onsuz Qt boşluğu yuxarıdakı üç element
        # arasında bölüşdürür və başlıq ilə mətn arasında böyük, izahsız
        # aralıq yaranır (kartlar da lazımsız uzanır).
        self.body().addStretch(1)

    def _build_card(self, key: str, title: str, description: str, icon_name: str) -> QWidget:
        card = Card()
        body = card.body()

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(10)

        glyph = QLabel()
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
            "Excel-ə ixrac et",
            icon_name="download",
            icon_color=self.theme.color("--color-action-text"),
        )
        button.clicked.connect(lambda *_, k=key: self.export_requested.emit(k))
        body.addWidget(button)
        return card

    def set_period(self, label: str) -> None:
        self._period_label.setText(label)

    def set_lock_summary(self, deferred_fines: int) -> None:
        """Etiraz pəncərəsinə görə TƏXİRƏ salınan cərimələri göstərir.

        Bölmə 6: "Export ekranında hər sətir üçün «etiraz pəncərəsi vəziyyəti»
        (bağlı/açıq) aydın göstərilir". Sıfır olduqda da mətn göstərilir —
        istifadəçi "heç bir cərimə gözləmir" cavabını görməlidir, boşluğu yox.
        """
        if deferred_fines:
            self._lock_note.setText(
                f"{deferred_fines} cərimənin 72 saatlıq etiraz pəncərəsi hələ AÇIQDIR — "
                f"bu ayın Premiya və Cərimə faylına daxil edilməyəcək, "
                f"növbəti dövrdə yenidən qiymətləndiriləcək."
            )
        else:
            self._lock_note.setText(
                "Bütün cərimələrin etiraz pəncərəsi BAĞLIDIR — təxirə salınan qeyd yoxdur."
            )
        self.show_content()


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

            number = QLabel(str(index))
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

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
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
            chip.setToolTip(title)
            chip.clicked.connect(self.topic_selected)
            self._chip_layout.addWidget(chip)
        self._chip_layout.addWidget(stretch())

        for _key, title, steps in topics:
            card = HelpTopicCard(title, steps, self.theme)
            self._topics_layout.insertWidget(self._topics_layout.count() - 1, card)

        self.show_content()


__all__ = [
    "HELP_TOPICS",
    "CatalogScreen",
    "HelpCenterScreen",
    "HelpTopicCard",
    "ReportExportScreen",
    "TopicChip",
    "fine_types_screen",
    "leave_types_screen",
    "work_modes_screen",
]
