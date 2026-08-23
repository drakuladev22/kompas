"""Aylıq Cərimə İcmalı ekranı — bölmə 4 (miqrasiya 003, Faza 2.7).

`application/use_cases/fine_review.py` axını belə təsvir edir:

    1. Cərimə `PENDING_REVIEW` doğulur — işçi onu GÖRMÜR.
    2. Ayın əvvəlində `can_publish_fines` sahibi 21 filialın həmin ay üçün
       nəşr gözləyən cərimələrini BİR ekranda görür.
    3. Hər sətrə "Saxla" (defolt) / "Sil" qərarı verilir.
    4. TƏK «[Bütün Filiallara Göndər]» düyməsi hamısını bir anda açır.

Use case ARTIQ yazılmışdı, bu ekran isə YOX idi — yəni `FineStatus.PUBLISHED`
-ə yeganə yol heç vaxt çağırılmırdı. Nəticə zəncirvari idi: cərimə nəşr
olunmur → işçi onu görmür → etiraz pəncərəsi açılmır → export şərti
(`EXPORTABLE_STATUSES`) heç vaxt ödənmir, yəni HEÇ BİR cərimə maaşdan
kəsilmir. Bu fayl həmin zəncirin GÖRÜNƏN halqasıdır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ FİLİALA GÖRƏ QRUPLAŞDIRILIR VƏ NİYƏ QRUPLAR YIĞILA BİLİR
──────────────────────────────────────────────────────────────────────────────
21 filialın bir aylıq cəriməsi tək düz siyahıda yüzlərlə sətir deməkdir və
belə ekranda "hansı filialda nə baş verir?" sualının cavabı itir. Qruplar
ALT-CƏMLƏ (say + məbləğ) gəlir, yəni qərar üçün lazım olan mənzərə açmadan
görünür.

Qruplar YIĞILMIŞ vəziyyətdə başlayır: 21 açıq qrup ekranı sürüşdürülməsi
mümkün olmayan uzunluğa çatdırır və icmalın ilk sualı ("ümumi mənzərə
necədir?") məhz başlıqlardan cavab alır. Sətirlər YENƏ DƏ qurulur — gizli
widget-in yalnız tərtibat/çəkilmə xərci düşür, qərar vəziyyəti isə açılıb
bağlananda ORADA qalır (yenidən qurma seçilmiş qərarları itirərdi).

──────────────────────────────────────────────────────────────────────────────
QƏRAR ETİKETLƏRİ EKRANDA YAZILMIR
──────────────────────────────────────────────────────────────────────────────
`ReviewDecision` üzvləri və onların Azərbaycanca adları KƏNARDAN gəlir
(`set_decision_options`, bax `controllers/fine_review.py::decision_options`).
Ekranda təkrar yazsaydıq, enum dəyişəndə maket və canlı yol fərqli mətn
göstərərdi — `menu.py` başlığındakı ad məkanı qüsurunun eyni forması.

SİYAHIDAKI BİRİNCİ variant DEFOLTDUR (`ReviewDecision.KEEP`): use case özü də
qərarı verilməmiş sətri "Saxla" sayır (`publish_batch` docstring-i), yəni
ekranın defoltu ilə use case-in defoltu EYNİ mənbədəndir.

──────────────────────────────────────────────────────────────────────────────
SƏBƏB DİALOQU EKRANDA DEYİL, KONTROLLERDƏDİR
──────────────────────────────────────────────────────────────────────────────
"Sil" qərarı üçün səbəb MƏCBURİDİR (`MIN_DISCARD_REASON_LENGTH`). Ekran
`decision_requested` siqnalını yayır, səbəbi isə kontroller soruşur
(`annual_leave`/`camera_queue` ilə eyni naxış): boş cavab yazı yoluna
ÜMUMİYYƏTLƏ girmir və domen istisnası ilə "cəzalandırma" baş vermir.

──────────────────────────────────────────────────────────────────────────────
NƏŞR GERİ QAYTARILA BİLMİR — ONA GÖRƏ TƏSDİQ MODALI MƏCBURİDİR
──────────────────────────────────────────────────────────────────────────────
Nəşr işçiyə görünmə, 72 saatlıq etiraz pəncərəsi və maaşdan kəsilmə zəncirini
başladır; kütləvi "geri al" YOXDUR (miqrasiya 003: ləğv yalnız fərdi-fərdi
`REVERSED` ilə aparılır). Ona görə `PublishConfirmDialog` neçə cərimənin,
neçə filialın və nə qədər məbləğin göndəriləcəyini AÇIQ yazır və defolt düymə
«İmtina»dır — Enter-ə təsadüfən basmaq 21 filialın cərimələrini açmamalıdır
(`RestoreConfirmDialog` ilə eyni qərar).

Yeni RƏNG CÜTÜ gətirilmir: `Card`, `Chip`, `DataTable`, `danger-text` və
mövcud düymə variantları işlədilir — hamısı `scripts/check_contrast.py`
ölçdüyü cütlərdəndir.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, NamedTuple

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.presentation.screens.base import Screen
from src.presentation.widgets import metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.data_table import Column, DataTable
from src.presentation.widgets.forms import field_label
from src.presentation.widgets.help_hint import HelpButton
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import (
    Card,
    Chip,
    ChipTone,
    Divider,
    body_label,
    muted_label,
    stretch,
    title_label,
)

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager

#: TƏK düymənin mətni — spesifikasiya onu adbaad tələb edir.
PUBLISH_BUTTON_TEXT: Final = "Bütün Filiallara Göndər"

#: Boş vəziyyət: nəşr gözləyən cərimə OLMAMASI müsbət haldır, xəta deyil.
EMPTY_TITLE: Final = "Göndəriləcək cərimə yoxdur"
EMPTY_MESSAGE: Final = (
    "Seçilmiş dövrdə nəşr gözləyən cərimə yoxdur — bütün cərimələr artıq "
    "filiallara göndərilib və ya ləğv edilib."
)

#: Düymənin yanındakı xəbərdarlıq — mətn HƏM burada, HƏM təsdiq modalında
#: görünür ki, istifadəçi nəticəni basmazdan ƏVVƏL də oxusun.
IRREVERSIBLE_NOTE: Final = (
    "Göndərmə geri qaytarıla bilmir: cərimələr həmin an bütün filiallarda "
    "görünür, etiraz pəncərəsi açılır və məbləğ maaş hesablamasına düşür."
)

#: Sübut şəkli nişanının mətnləri — RƏNG TƏK BAŞINA KİFAYƏT ETMİR (rəng
#: korluğu + ekran oxuyucusu), ona görə hər iki hal MƏTNLƏ yazılır.
EVIDENCE_PRESENT_TEXT: Final = "Şəkil var"
EVIDENCE_MISSING_TEXT: Final = "Şəkil yoxdur"

#: Qrupun açılma/yığılma düyməsinin iki vəziyyəti.
_EXPAND_TEXT: Final = "Sətirləri göstər"
_COLLAPSE_TEXT: Final = "Sətirləri gizlət"


class FineReviewRow(NamedTuple):
    """İcmal cədvəlinin bir sətri.

    `fine_id` MƏTNDİR: ekran domen tiplərini tanımır (bax
    `controllers/__init__.py`) — çevirmə kontrollerdədir. Sahələr HƏM maket
    (`preview_data.FINE_REVIEW_GROUPS`), HƏM canlı yol
    (`controllers/fine_review.py::_to_row`) üçün EYNİDİR — CLAUDE.md §6.
    """

    fine_id: str
    employee: str
    fine_type: str
    amount_text: str
    date_text: str
    operator: str
    has_evidence: bool


class FineReviewGroup(NamedTuple):
    """Bir filialın sətirləri + alt-cəmi.

    Alt-cəm EKRANDA HESABLANMIR: məbləğ `Decimal`-dır və onu mətn sətirlərindən
    yenidən toplamaq yuvarlaqlaşdırma fərqi gətirərdi (bax
    `controllers/fine_review.py::_group_rows`).

    `key` FİLİALIN İDENTİFİKATORUDUR, adı yox: toplu qərar siqnalı məhz onu
    daşıyır. Ad UNİKAL DEYİL (`stores` cədvəlində unikallıq `code` üzrədir),
    yəni eyni adlı iki filial olsaydı toplu "hamısını sil" hər ikisinə
    düşərdi — real pul kəsintisində belə səhv yolverilməzdir.
    """

    key: str
    store: str
    count_text: str
    total_text: str
    rows: tuple[FineReviewRow, ...]


class PublishSummary(NamedTuple):
    """Təsdiq modalının göstərdiyi rəqəmlər — çağıran tərəfdən gəlir."""

    period_text: str
    publish_count: int
    discard_count: int
    store_count: int
    amount_text: str


#: Aylıq Cərimə İcmalının kontekstual köməyi (audit G-4).
#:
#: Mətn EKRANIN YANINDA yaşayır, mərkəzi kömək kataloqunda deyil — səbəbi
#: `widgets/help_hint.HelpButton` başlığındadır: "qərarı verilməmiş sətir
#: SAXLA sayılır" qaydası use case ilə ekran arasındakı sükutlu razılaşmadır
#: (bax modul başlığı) və izahı həmin qərarla eyni faylda qalmalıdır.
FINE_REVIEW_HELP_TITLE: Final = "Aylıq Cərimə İcmalı"

FINE_REVIEW_HELP_INTRO: Final = (
    "Bu ekranda seçilmiş ayın nəşr gözləyən cərimələri filial-filial "
    "sadalanır. İşçi onları HƏLƏ görmür — cərimə yalnız göndərmə düyməsindən "
    "sonra görünən olur və o addım geri qaytarıla bilmir."
)

FINE_REVIEW_HELP_STEPS: Final[tuple[str, ...]] = (
    "«İcmal dövrü» siyahısından ayı seçin — orada yalnız nəşr gözləyən "
    "dövrlər olur. Siyahı boşdursa göndəriləcək cərimə yoxdur; bu, xəta "
    "deyil.",
    "Filial başlığındakı «Sətirləri göstər» qrupu açır. Say və məbləğ qrup "
    "bağlı olsa da başlıqda görünür, yəni ümumi mənzərəni hər filialı "
    "açmadan oxumaq olar.",
    "Hər sətrin qərarı defolt olaraq «Saxla»dır: heç nəyə toxunmasanız cərimə "
    "göndəriləcək. «Sil» seçdikdə səbəb soruşulur — belə cərimə işçidən "
    "TUTULMUR, lakin qeyd auditdə qalır və izi silinmir.",
    "Başlıqdakı «Hamısı: …» düymələri həmin filialın bütün sətirlərinə eyni "
    "qərarı verir. Sonra istənilən sətri ayrıca dəyişmək olar — nişanın "
    "yanındakı düymə qərarı «Saxla»ya qaytarır.",
    "«Bütün Filiallara Göndər» TƏK düymədir və təsdiq modalında neçə cərimə, "
    "neçə filial və hansı məbləğin göndəriləcəyi yazılır. Göndərmə GERİ "
    "QAYTARILA BİLMİR: cərimələr həmin an işçilərə görünür, etiraz pəncərəsi "
    "açılır və məbləğ maaş hesablamasına düşür.",
)


class MonthlyFineReviewScreen(Screen):
    """Dövr seçimi + filial qrupları + TƏK «Bütün Filiallara Göndər» düyməsi.

    Signals:
        period_selected: Dövr açılan siyahısı dəyişdi (`YYYY-MM`).
        refresh_requested: `[Yenilə]` — siyahını təzədən oxuyur.
        decision_requested: Sətir qərarı basıldı — `(fine_id, decision_code)`.
            Səbəb BURADA soruşulmur (bax modul başlığı).
        group_decision_requested: Qrupun toplu qərarı — `(store_key, code)`.
        publish_requested: TƏK düymə — sətir qərarlarının siyahısı
            (`fine_id`/`decision`/`reason` açarlı sözlüklər).
    """

    period_selected = Signal(str)
    refresh_requested = Signal()
    decision_requested = Signal(str, str)
    group_decision_requested = Signal(str, str)
    publish_requested = Signal(list)

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)

        #: `code → etiket` — `set_decision_options` doldurur.
        self._option_labels: dict[str, str] = {}
        #: Sıra ilə variant kodları; BİRİNCİSİ defoltdur (bax modul başlığı).
        self._option_codes: list[str] = []
        #: `fine_id → {"decision", "reason"}` — nəşr yükünün mənbəyi.
        self._decisions: dict[str, dict[str, str]] = {}
        #: `fine_id → qərar nişanı` — vəziyyəti sətirdə görünən edir.
        self._decision_chips: dict[str, Chip] = {}
        #: `fine_id → «geri qaytar» düyməsi`. AYRI sözlükdə saxlanılır, Qt
        #: xüsusiyyətində (`setProperty`) YOX: orada widget `QVariant`-a
        #: bükülür və tip yoxlayıcısı üçün `Any`-yə çevrilir — yəni səhv ad
        #: yazılsa sükutla `None` qayıdardı.
        self._revert_buttons: dict[str, QPushButton] = {}
        #: Sətirlərin QURULUŞ sırası — nəşr yükü də bu sıra ilə gedir.
        self._row_order: list[str] = []

        self.add(self._build_toolbar())

        self._notice = muted_label("")
        self._notice.setVisible(False)
        self.add(self._notice)

        self._error = _danger_text("")
        self._error.setVisible(False)
        self.add(self._error)

        self._groups_layout = QVBoxLayout()
        self._groups_layout.setSpacing(16)
        holder = QWidget()
        holder.setLayout(self._groups_layout)
        self.add(holder)

        self.add(self._build_footer())
        self.body().addStretch(1)
        self._sync_publish_button()

    def help_button(self) -> HelpButton:
        """Kontekstual kömək düyməsi — kontroller/testlər üçün."""
        return self._help

    # ------------------------------- alət zolağı ------------------------------ #

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget()
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        # Dar pəncərədə dövr seçimi və düymələr alt-alta düşür.
        self.responsive_row(layout)

        period_box = QWidget()
        period_layout = QVBoxLayout(period_box)
        period_layout.setContentsMargins(0, 0, 0, 0)
        period_layout.setSpacing(8)
        period_layout.addWidget(field_label("İcmal dövrü"))

        self._period = QComboBox()
        self._period.setProperty("variant", "form")
        self._period.currentIndexChanged.connect(self._on_period_changed)
        period_layout.addWidget(self._period)
        layout.addWidget(period_box)

        self._summary = muted_label("")
        layout.addWidget(self._summary)
        layout.addWidget(stretch())

        # Kontekstual kömək (audit G-4) — "qərarı verilməmiş sətir SAXLA
        # sayılır" qaydası ekranda heç yerdə yazılmırdı; istifadəçi isə məhz
        # bunu bilmədən düyməni basanda gözlədiyindən çox cərimə göndərirdi.
        self._help = HelpButton(
            self.theme,
            title=FINE_REVIEW_HELP_TITLE,
            intro=FINE_REVIEW_HELP_INTRO,
            steps=FINE_REVIEW_HELP_STEPS,
        )
        layout.addWidget(self._help)

        refresh = secondary_button("Yenilə")
        refresh.clicked.connect(self.refresh_requested)
        layout.addWidget(refresh)
        return toolbar

    def _build_footer(self) -> QWidget:
        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        card.add(title_label("Nəşr", size=15))
        card.add(muted_label(IRREVERSIBLE_NOTE, size=12))

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)
        row_layout.addWidget(stretch())

        # TƏK DÜYMƏ (spesifikasiya): filial-filial göndərmə yolu ekranda
        # ÜMUMİYYƏTLƏ yoxdur — "bir anda görünür" tələbi məhz bu deməkdir.
        self._publish = action_button(PUBLISH_BUTTON_TEXT)
        self._publish.clicked.connect(self._on_publish)
        row_layout.addWidget(self._publish)
        card.add(row)
        return card

    # -------------------------------- dövrlər --------------------------------- #

    def set_periods(self, periods: list[dict[str, str]], *, selected: str = "") -> None:
        """Nəşr gözləyən dövrləri açılan siyahıya yazır.

        Args:
            periods: `key` (`YYYY-MM`) və `label` ("Avqust 2026") açarlı
                sözlüklər. Sıra çağırandan gəlir — ekran sıralamır.
            selected: Açıq qalacaq dövr. Boşdursa BİRİNCİ element seçilir.

        Siqnal BLOKLANIR: siyahının proqramla doldurulması istifadəçi seçimi
        DEYİL və `period_selected` yaysaydı, kontroller doldurma anında
        yenidən oxu dövrəsinə düşərdi.
        """
        self._period.blockSignals(True)
        self._period.clear()
        for period in periods:
            self._period.addItem(period.get("label", ""), period.get("key", ""))
        if periods:
            index = self._period.findData(selected)
            self._period.setCurrentIndex(index if index >= 0 else 0)
        self._period.blockSignals(False)
        # Dövr yoxdursa seçici görünsə də boşdur — onu gizlətmək "ekran
        # sınıb" təəssüratı yaradardı, ona görə yalnız deaktiv edilmir.
        self._period.setEnabled(bool(periods))

    def selected_period(self) -> str:
        """Hazırda seçilmiş dövr (`YYYY-MM`) — boş ola bilər."""
        data = self._period.currentData()
        return str(data) if data else ""

    def _on_period_changed(self) -> None:
        period = self.selected_period()
        if period:
            self.period_selected.emit(period)

    # ------------------------------- qərar variantları ------------------------ #

    def set_decision_options(self, options: list[dict[str, str]]) -> None:
        """Sətir qərarlarının variantları — `code` və `label` açarları.

        Etiketlər `ReviewDecision`-dan gəlir (bax modul başlığı). Metod
        sətirlərdən ƏVVƏL çağırılmalıdır: sətir düymələri məhz bu siyahıdan
        qurulur.
        """
        self._option_codes = [option.get("code", "") for option in options if option.get("code")]
        self._option_labels = {
            option.get("code", ""): option.get("label", "") for option in options
        }

    def _default_code(self) -> str:
        return self._option_codes[0] if self._option_codes else ""

    # -------------------------------- siyahı ---------------------------------- #

    def set_groups(self, groups: list[FineReviewGroup], *, summary_text: str = "") -> None:
        """Filial qruplarını göstərir və qərar vəziyyətini SIFIRLAYIR.

        Sıfırlama qəsdəndir: siyahı yalnız yenidən oxunanda dəyişir və köhnə
        qərarlar artıq mövcud olmayan cərimələrə aid ola bilər. Onları
        saxlamaq nəşr anında "icmalda olmayan cərimə üçün qərar verildi"
        istisnasına gətirərdi.

        Boş siyahı NORMAL və MÜSBƏT haldır — `show_empty`, `show_error` YOX.
        """
        clear_layout(self._groups_layout)
        self._decisions.clear()
        self._decision_chips.clear()
        self._revert_buttons.clear()
        self._row_order.clear()
        self.show_notice("")
        self.show_form_error("")

        if not groups:
            self._summary.setText("")
            self._sync_publish_button()
            self.show_empty(
                icon_name="check_circle",
                title=EMPTY_TITLE,
                message=EMPTY_MESSAGE,
            )
            return

        self._summary.setText(summary_text)
        default = self._default_code()
        for group in groups:
            for row in group.rows:
                self._row_order.append(row.fine_id)
                self._decisions[row.fine_id] = {"decision": default, "reason": ""}
            self._groups_layout.addWidget(self._build_group(group))

        self._sync_publish_button()
        self.show_content()

    def groups_layout(self) -> QVBoxLayout:
        """Qrup qabı — testlər qrup sayını buradan oxuyur."""
        return self._groups_layout

    def _build_group(self, group: FineReviewGroup) -> Card:
        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(12)
        head_layout.addWidget(title_label(group.store, size=15))
        head_layout.addWidget(muted_label(f"{group.count_text} · {group.total_text}"))
        head_layout.addWidget(stretch())

        # TOPLU SÜRƏTLƏNDİRİCİ: 21 filial × onlarla sətri əl ilə keçmək
        # praktikada mümkün deyil. Düymələr HƏR variant üçün qurulur, yəni
        # enum genişlənsə siyahı özü genişlənir.
        for code in self._option_codes:
            button = secondary_button(f"Hamısı: {self._option_labels.get(code, code)}")
            if code != self._default_code():
                button.setProperty("variant", "danger")
            button.clicked.connect(
                lambda *_, key=group.key, value=code: self.group_decision_requested.emit(key, value)
            )
            head_layout.addWidget(button)

        toggle = secondary_button(_EXPAND_TEXT)
        head_layout.addWidget(toggle)
        card.add(head)

        table = DataTable(_COLUMNS, self.theme)
        for row in group.rows:
            table.add_row(self._build_cells(row))
        # Bax modul başlığı: qruplar YIĞILMIŞ başlayır.
        table.setVisible(False)
        toggle.clicked.connect(lambda *_, widget=table, button=toggle: _toggle(widget, button))
        card.add(table)
        return card

    def _build_cells(self, row: FineReviewRow) -> list[QWidget | str]:
        evidence: QWidget = (
            Chip(EVIDENCE_PRESENT_TEXT, "info")
            if row.has_evidence
            else muted_label(EVIDENCE_MISSING_TEXT, size=12)
        )

        decision = QWidget()
        decision_layout = QHBoxLayout(decision)
        decision_layout.setContentsMargins(0, 0, 0, 0)
        decision_layout.setSpacing(8)

        chip = Chip(self._option_labels.get(self._default_code(), ""), "neutral")
        self._decision_chips[row.fine_id] = chip
        decision_layout.addWidget(chip)

        for code in self._option_codes:
            if code == self._default_code():
                # Defolt variantın düyməsi YALNIZ qərar dəyişdirilmiş sətirdə
                # mənalıdır — hər sətirdə "Saxla" düyməsi göstərmək gözü
                # doldurar və heç bir yeni imkan verməzdi. Geri qayıtma yolu
                # `set_decision` ilə açılır (aşağıdakı `_sync_row`).
                continue
            button = secondary_button(self._option_labels.get(code, code))
            button.setProperty("variant", "danger")
            button.clicked.connect(
                lambda *_, fine_id=row.fine_id, value=code: self.decision_requested.emit(
                    fine_id, value
                )
            )
            decision_layout.addWidget(button)

        revert = secondary_button(self._option_labels.get(self._default_code(), ""))
        revert.setVisible(False)
        revert.clicked.connect(
            lambda *_, fine_id=row.fine_id: self.decision_requested.emit(
                fine_id, self._default_code()
            )
        )
        decision_layout.addWidget(revert)
        self._revert_buttons[row.fine_id] = revert

        return [
            row.employee,
            row.fine_type,
            row.amount_text,
            row.date_text,
            row.operator,
            evidence,
            decision,
        ]

    # -------------------------------- qərarlar -------------------------------- #

    def set_decision(self, fine_id: str, *, decision: str, reason: str = "") -> None:
        """Bir sətrin qərarını yazır və nişanı yeniləyir.

        Kontroller çağırır — səbəb dialoqu ondadır (bax modul başlığı).
        Naməlum `fine_id` SÜKUTLA keçilir: siyahı bu arada yenidən oxunmuş
        ola bilər və köhnə siqnalın ekranı çökdürməsi yolverilməzdir.
        """
        if fine_id not in self._decisions:
            return
        self._decisions[fine_id] = {"decision": decision, "reason": reason}
        self._sync_row(fine_id)

    def decisions(self) -> list[dict[str, str]]:
        """Nəşr yükü — sətirlərin QURULUŞ sırası ilə.

        Qərarı verilməmiş sətir də siyahıdadır və defolt kodu daşıyır: use
        case onu onsuz da "Saxla" sayardı, lakin açıq yazmaq nəşr yükünü
        auditdə oxunaqlı edir.
        """
        return [
            {
                "fine_id": fine_id,
                "decision": self._decisions[fine_id]["decision"],
                "reason": self._decisions[fine_id]["reason"],
            }
            for fine_id in self._row_order
        ]

    def _sync_row(self, fine_id: str) -> None:
        chip = self._decision_chips.get(fine_id)
        if chip is None:  # pragma: no cover - sətir və nişan birlikdə qurulur
            return
        code = self._decisions[fine_id]["decision"]
        is_default = code == self._default_code()
        chip.setText(self._option_labels.get(code, code))
        tone: ChipTone = "neutral" if is_default else "danger"
        chip.set_tone(tone)
        # Səbəb nişanın izahındadır: sətirdə göstərmək cədvəli oxunmaz
        # uzunluqda genişləndirərdi, lakin mətn əlçatan qalmalıdır.
        chip.setToolTip(self._decisions[fine_id]["reason"])

        revert = self._revert_buttons.get(fine_id)
        if revert is not None:
            revert.setVisible(not is_default)

    def _sync_publish_button(self) -> None:
        """Sətir yoxdursa düymə basıla bilmir — boş dəst istisna atardı."""
        self._publish.setEnabled(bool(self._row_order))

    def _on_publish(self) -> None:
        if not self._row_order:  # pragma: no cover - düymə onsuz da bağlıdır
            return
        self.show_form_error("")
        self.publish_requested.emit(self.decisions())

    def publish_button(self) -> QPushButton:
        """TƏK nəşr düyməsi — testlər vəziyyəti buradan oxuyur."""
        return self._publish

    # ------------------------------- mesajlar --------------------------------- #

    def show_notice(self, message: str) -> None:
        """Sakit ton: "42 cərimə göndərildi" kimi nəticə mesajları."""
        self._notice.setText(message)
        self._notice.setVisible(bool(message))

    def show_form_error(self, message: str) -> None:
        """Xəta sətri — domen `user_message`-i, xam istisna mətni YOX."""
        self._error.setText(message)
        self._error.setVisible(bool(message))


class PublishConfirmDialog(QDialog):
    """«Bütün Filiallara Göndər» üçün ciddi təsdiq modalı.

    Signals:
        confirmed: İstifadəçi rəqəmləri görüb təsdiqlədi.

    Rəqəmlər BURADA HESABLANMIR — `PublishSummary` ilə gəlir (bax
    `controllers/fine_review.py::_summary_for`). Modalın ikinci dəfə
    hesablaması iki mənbə yaradar və biri digərindən yayınsaydı, istifadəçi
    təsdiqlədiyi ilə fərqli bir dəsti göndərmiş olardı.
    """

    confirmed = Signal()

    def __init__(
        self,
        theme: ThemeManager,
        *,
        summary: PublishSummary,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("Cərimələri göndər")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        layout.addWidget(card)

        card.add(title_label("Cərimələr bütün filiallara göndərilsin?", size=19))
        card.add(
            body_label(
                f"Dövr: {summary.period_text}. "
                f"{summary.publish_count} cərimə {summary.store_count} filialda "
                f"işçilərə açılacaq — ümumi məbləğ {summary.amount_text}.",
                size=13,
            )
        )
        if summary.discard_count:
            # Silinənlər AYRI cümlədədir: onlar pul kəsintisi YARATMIR, lakin
            # qeyd kimi qalır (`REVERSED`) və istifadəçi ikisini qarışdırmamalıdır.
            card.add(
                body_label(
                    f"{summary.discard_count} cərimə silinəcək — qeyd auditdə qalır, "
                    "lakin işçidən tutulmayacaq.",
                    size=13,
                )
            )
        card.add(Divider())
        card.add(_danger_text(IRREVERSIBLE_NOTE))

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)
        buttons_layout.addWidget(stretch())

        cancel = secondary_button("İmtina")
        cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel)

        self._confirm = action_button(PUBLISH_BUTTON_TEXT)
        self._confirm.clicked.connect(self._on_confirm)
        buttons_layout.addWidget(self._confirm)
        card.add(buttons)

        # DEFOLT DÜYMƏ İMTİNADIR — `RestoreConfirmDialog` ilə eyni qərar və
        # eyni səbəb: nəşrin geri dönüşü yoxdur, ona görə Enter-ə təsadüfən
        # basmaq ən pis halda modalı bağlamalıdır.
        cancel.setDefault(True)
        cancel.setAutoDefault(False)
        self._confirm.setDefault(False)
        self._confirm.setAutoDefault(False)

        QWidget.setTabOrder(cancel, self._confirm)

    def _on_confirm(self) -> None:
        self.confirmed.emit()
        self.accept()

    def confirm_button(self) -> QPushButton:
        """Təsdiq düyməsi — testlər üçün."""
        return self._confirm


#: Cədvəl sütunları — `ClassVar` deyil, MODUL səviyyəsində: qrup kartlarının
#: hər biri öz `DataTable`-ını qurur və siyahını heç biri dəyişmir.
_COLUMNS: Final[list[Column]] = [
    Column("İşçi"),
    Column("Cərimə növü"),
    Column("Məbləğ", 110, mono=True),
    Column("Tarix", 120, mono=True),
    Column("Qeydə alan", 170),
    Column("Sübut", 130),
    Column("Qərar", 260),
]


def _toggle(table: DataTable, button: QPushButton) -> None:
    """Qrupu açır/yığır — sətirlər YENİDƏN QURULMUR (bax modul başlığı)."""
    visible = not table.isVisible()
    table.setVisible(visible)
    button.setText(_COLLAPSE_TEXT if visible else _EXPAND_TEXT)


def _danger_text(text: str) -> QLabel:
    """Təhlükə tonlu izah — mövcud `danger-text` variantı (yeni rəng YOX)."""
    label = body_label(text, size=12)
    label.setProperty("variant", "danger-text")
    return label


__all__ = [
    "EMPTY_MESSAGE",
    "EMPTY_TITLE",
    "EVIDENCE_MISSING_TEXT",
    "EVIDENCE_PRESENT_TEXT",
    "FINE_REVIEW_HELP_INTRO",
    "FINE_REVIEW_HELP_STEPS",
    "FINE_REVIEW_HELP_TITLE",
    "IRREVERSIBLE_NOTE",
    "PUBLISH_BUTTON_TEXT",
    "FineReviewGroup",
    "FineReviewRow",
    "MonthlyFineReviewScreen",
    "PublishConfirmDialog",
    "PublishSummary",
]
