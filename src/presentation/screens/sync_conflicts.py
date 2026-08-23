"""Sinxronizasiya konfliktlərinin həlli ekranı — bölmə 5 (offline rejim).

Bölmə 5 konflikti belə tərif edir:

    "Konflikt aşkarlandıqda hər iki versiya saxlanılır, `CONFLICT` statusu ilə
     HR_Admin-ə MANUAL HƏLL üçün göndərilir."

`application/use_cases/sync_conflicts.py` həmin manual həlli ARTIQ idarə edir
və «Sistem Sağlamlığı» ekranı «N sinxronizasiya konflikti həll gözləyir»
xəbərdarlığını göstərir — lakin GEDƏCƏK YER yox idi. Yəni sistem problemi
elan edir, sonra istifadəçini kor dalana salırdı. Bu ekran həmin dalanı
bağlayır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ YAN-YANA MÜQAYİSƏ, NİYƏ «SON YAZAN QAZANIR» DEYİL
──────────────────────────────────────────────────────────────────────────────
Konflikt cədvəlləri (`attendance_records`, `leave_requests`, `fines`,
`audit_logs`) davamiyyət saatı və REAL PUL kəsintisi daşıyır. Avtomatik
seçim (last-write-wins) bölmə 5-də məhz bu cədvəllər üçün QADAĞANDIR: hansı
versiyanın doğru olduğunu yalnız insan bilir — məsələn mağazadakı operator
işçinin faktiki qayıdış vaxtını görüb, bulud isə köhnə plan dəyərini saxlayır.

Ona görə ekranın mərkəzi bir cədvəl deyil, İKİ SÜTUNLU müqayisədir: FƏRQLİ
sahələr vurğulanır, eyni qalanlar sönük göstərilir. `differing_fields()`
onsuz da yalnız fərqi qaytarır; eyni sahələri də göstəririk, çünki
"başqa nəyə toxunur?" sualı qərarın bir hissəsidir — lakin gözü fərqə
yönəltmək üçün onlar solğun qalır.

──────────────────────────────────────────────────────────────────────────────
AUDİT-KRİTİK KONFLİKT: RƏNG KİFAYƏT ETMİR, MƏTN DƏ LAZIMDIR
──────────────────────────────────────────────────────────────────────────────
`ConflictItem.is_audit_critical` bölmə 5-də adı çəkilən cədvəlləri işarələyir.
Belə sətir HƏM nişanla (`Chip`, `danger` tonu), HƏM DƏ açıq cümlə ilə
göstərilir. Yalnız ikon/rəng işlətmək iki səbəbdən yetərsizdir: rəng-korluğu
olan istifadəçi tonu ayırd etmir, ekran oxuyucusu isə rəngi ümumiyyətlə
oxumur. Cümlə ekranda BİR yerdə saxlanılır (`AUDIT_CRITICAL_NOTE`) — sətirdə
və müqayisə panelində eyni mətn görünsün deyə.

──────────────────────────────────────────────────────────────────────────────
QƏRAR GERİ QAYTARILA BİLMİR — ONA GÖRƏ SƏBƏB MƏCBURİDİR
──────────────────────────────────────────────────────────────────────────────
`PostgresSyncConflictRepository.resolve` `WHERE ... AND resolved_at IS NULL`
şərti ilə yazır: bir dəfə bağlanmış konflikt İKİNCİ dəfə həll edilə bilmir
(paralel iki HR halında birincinin qərarı qalır). Yəni bu ekrandakı düymə
geri alına bilməyən qərardır və `SyncConflictUseCase.resolve` səbəb mətnini
MƏCBURİ edir (`MIN_NOTE_LENGTH`). Düymələr səbəb yazılana qədər DEAKTİVDİR —
domen istisnası ilə "cəzalandırmaq" əvəzinə vəziyyət ifadə edilə bilməz olur
(`annual_leave.AnnualLeaveRequestDialog` ilə eyni sərhəd qərarı).

──────────────────────────────────────────────────────────────────────────────
QƏRAR ETİKETLƏRİ VƏ MİNİMUM UZUNLUQ EKRANDA YAZILMIR
──────────────────────────────────────────────────────────────────────────────
`Resolution.label_az` və `MIN_NOTE_LENGTH` tətbiq qatındadır; ekran onları
`set_resolutions()` / `set_note_min_length()` ilə KƏNARDAN alır. Ekranda
təkrar yazsaydıq, enum dəyişəndə maket və canlı yol fərqli mətn göstərərdi —
`menu.py` başlığındakı ad məkanı qüsurunun eyni forması.

SAHƏ ADLARI TƏRCÜMƏ OLUNMUR: `local_version`/`remote_version` sözlüklərinin
açarları baza SÜTUN adlarıdır (`status`, `amount`, `updated_at`), yəni
identifikatordur — `menu.py` açarları və `FeatureModule` dəyərləri ilə eyni
kateqoriya. Onlar monoaralıqlı yazılır ki, texniki ad olduqları görünsün.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.presentation.screens.base import Screen
from src.presentation.widgets import metrics
from src.presentation.widgets.buttons import secondary_button
from src.presentation.widgets.forms import field_label
from src.presentation.widgets.help_hint import HelpButton
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import (
    Card,
    Chip,
    ClickableCard,
    Divider,
    body_label,
    mono_label,
    muted_label,
    section_label,
    stretch,
    title_label,
)

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager

#: Audit-kritik konfliktin AÇIQ izahı — nişanın yanında MƏTN kimi görünür.
#: Bir yerdə saxlanılır: siyahı sətri və müqayisə paneli eyni cümləni yazır.
AUDIT_CRITICAL_NOTE: Final = (
    "Audit-kritik cədvəl: bu qeyd davamiyyət saatına və ya real pul "
    "kəsintisinə toxunur. Qərar geri qaytarıla bilmir — seçimi yazmadan "
    "əvvəl hər iki versiyanı diqqətlə tutuşdurun."
)

#: Boş vəziyyət — konflikt OLMAMASI normal və MÜSBƏT haldır, xəta deyil.
EMPTY_TITLE: Final = "Həll gözləyən konflikt yoxdur"
EMPTY_MESSAGE: Final = (
    "Offline rejimdə eyni qeyd iki yerdə fərqli dəyişdirildikdə burada "
    "görünür. Hazırda bütün versiyalar uyğundur."
)

#: Müqayisə sətrinin sabit sütun enləri (maketdəki cədvəl ritmi).
_MARKER_WIDTH: Final = 92
_FIELD_WIDTH: Final = 190

#: Konflikt ekranının kontekstual köməyi (audit G-4).
#:
#: Mətn EKRANIN YANINDA yaşayır, mərkəzi kömək kataloqunda deyil — səbəbi
#: `widgets/help_hint.HelpButton` başlığındadır: qərarın BİR DƏFƏLİK olması
#: `resolve`-un `WHERE ... resolved_at IS NULL` şərtindən doğur (bax modul
#: başlığı) və izah həmin qərarla eyni faylda saxlanılmalıdır.
SYNC_CONFLICT_HELP_TITLE: Final = "Sinxronizasiya Konfliktləri"

SYNC_CONFLICT_HELP_INTRO: Final = (
    "Offline rejimdə eyni qeyd iki yerdə fərqli dəyişdirildikdə hər iki "
    "versiya saxlanılır və burada həll gözləyir. Qərar BİR DƏFƏ verilir — "
    "bağlanmış konflikt yenidən açıla bilmir."
)

SYNC_CONFLICT_HELP_STEPS: Final[tuple[str, ...]] = (
    "Soldakı siyahıdan konflikti seçin. «Audit-kritik» nişanlı sətirlər "
    "davamiyyət saatına və ya real pul kəsintisinə toxunur; sıranı sistem "
    "verir və belə qeydlər həmişə yuxarıda olur.",
    "Sağda «Mağazadakı versiya» ilə «Buluddakı versiya» yan-yana durur. "
    "Fərqli sahələr qalın yazılır və «Fərqli» nişanı alır; eyni qalanlar "
    "sönük göstərilir — onlar da göz önündədir, çünki qərarın başqa nəyə "
    "toxunduğu qərarın bir hissəsidir.",
    "«Qərarın səbəbi» sahəsini doldurun. Mətn məcburidir və audit jurnalına "
    "olduğu kimi düşür; yazılana qədər qərar düymələri basıla bilmir. Başqa "
    "konfliktə keçdikdə sahə təmizlənir ki, bir qeydin izahı digərinin "
    "jurnalına düşməsin.",
    "Qərar düymələrindən birini seçin. Heç biri «tövsiyə olunan» deyil — "
    "doğru versiyanı yalnız qeydə baxan insan bilir. Seçim konflikti bağlayır, "
    "lakin hər iki versiya cədvəldə QALIR: heç nə silinmir.",
    "Verilmiş qərar GERİ QAYTARILA BİLMİR və konflikt ikinci dəfə həll "
    "edilmir. Bu arada başqası onu bağlayıbsa sakit tonlu məlumat görünür — "
    "«Yenilə» siyahını təzədən oxuyur.",
)


class SyncConflictScreen(Screen):
    """Konflikt siyahısı + LOKAL ↔ UZAQ müqayisəsi + qərar paneli.

    Signals:
        conflict_selected: Siyahıdan bir konflikt seçildi (`conflict_id`).
        resolve_requested: Qərar düyməsi — `dict` (`id`, `resolution`, `note`).
        refresh_requested: `[Yenilə]` — siyahını təzədən oxuyur.
    """

    conflict_selected = Signal(str)
    resolve_requested = Signal(dict)
    refresh_requested = Signal()

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)
        self._note_min_length = 0
        self._selected_id = ""
        self._decision_buttons: list[QPushButton] = []
        #: `conflict_id → «Seçildi» nişanı` — seçim göstəricisi.
        self._selection_chips: dict[str, Chip] = {}

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(12)
        self._summary = muted_label("")
        toolbar_layout.addWidget(self._summary)
        toolbar_layout.addWidget(stretch())

        # Kontekstual kömək (audit G-4) — qərarın BİR DƏFƏLİK olduğu qərar
        # kartında yazılıb, lakin səbəbin niyə məcburi olduğu və sönük
        # sətirlərin nə üçün göstərildiyi yalnız burada izah olunur.
        self._help = HelpButton(
            theme,
            title=SYNC_CONFLICT_HELP_TITLE,
            intro=SYNC_CONFLICT_HELP_INTRO,
            steps=SYNC_CONFLICT_HELP_STEPS,
        )
        toolbar_layout.addWidget(self._help)

        refresh = secondary_button("Yenilə")
        refresh.clicked.connect(self.refresh_requested)
        toolbar_layout.addWidget(refresh)
        self.add(toolbar)

        columns = QWidget()
        columns_layout = QHBoxLayout(columns)
        columns_layout.setContentsMargins(0, 0, 0, 0)
        # Kartlar arası aralıq — bax `performance_review.py`-dakı eyni sətir.
        columns_layout.setSpacing(metrics.CARD_SPACING)
        # Dar pəncərədə siyahı və müqayisə alt-alta düşür (bax
        # `screens/base.py::responsive_row`).
        self.responsive_row(columns_layout)
        columns_layout.addWidget(self._build_list_card(), 1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(16)
        right_layout.addWidget(self._build_comparison_card())
        right_layout.addWidget(self._build_decision_card())
        right_layout.addStretch(1)
        columns_layout.addWidget(right, 2)

        self.add(columns)
        self.body().addStretch(1)

    def help_button(self) -> HelpButton:
        """Kontekstual kömək düyməsi — kontroller/testlər üçün."""
        return self._help

    # ------------------------------- siyahı ----------------------------------- #

    def _build_list_card(self) -> Card:
        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        card.add(title_label("Həll gözləyən konfliktlər", size=15))
        card.add(
            muted_label(
                "Audit-kritik qeydlər siyahının başındadır — sıranı use case verir.",
                size=12,
            )
        )
        card.add(Divider())

        self._list_rows = QVBoxLayout()
        self._list_rows.setSpacing(12)
        holder = QWidget()
        holder.setLayout(self._list_rows)
        card.add(holder)

        card.body().addStretch(1)
        return card

    def _build_list_row(self, row: dict[str, str]) -> QWidget:
        key = row.get("id", "")
        card = ClickableCard(key, padding=16, spacing=8)
        card.clicked.connect(self.conflict_selected)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(8)
        head_layout.addWidget(_strong_label(row.get("table_label", ""), size=14))
        head_layout.addWidget(stretch())
        chip = Chip("Seçildi", "info")
        chip.setVisible(False)
        head_layout.addWidget(chip)
        card.add(head)
        self._selection_chips[key] = chip

        card.add(mono_label(row.get("record_label", ""), muted=True))
        card.add(
            muted_label(
                f"{row.get('detected', '')} · {row.get('diff_count', '')}",
                size=12,
            )
        )

        if row.get("audit_critical") == "1":
            card.add(Chip("Audit-kritik", "danger"))
            card.add(_danger_text(AUDIT_CRITICAL_NOTE))

        return card

    def set_conflicts(self, rows: list[dict[str, str]]) -> None:
        """Həll gözləyən konfliktləri göstərir.

        Args:
            rows: `id`, `table_label`, `record_label`, `detected`,
                `diff_count`, `audit_critical` açarları. Açarlar HƏM maket
                (`preview_screens._sync_conflicts`), HƏM canlı yol
                (`controllers/sync_conflicts.py::_to_list_row`) üçün EYNİDİR —
                CLAUDE.md §6.

        Boş siyahı NORMAL və MÜSBƏT haldır: `show_empty` göstərilir,
        `show_error` YOX (`annual_leave.AnnualLeaveInboxScreen` ilə eyni qərar).
        """
        clear_layout(self._list_rows)
        self._selection_chips.clear()

        if not rows:
            self._summary.setText("")
            self.set_comparison({}, [])
            self.show_empty(
                icon_name="check_circle",
                title=EMPTY_TITLE,
                message=EMPTY_MESSAGE,
            )
            return

        self._summary.setText(f"{len(rows)} konflikt həll gözləyir")
        for row in rows:
            self._list_rows.addWidget(self._build_list_row(row))
        self.show_content()

    def list_layout(self) -> QVBoxLayout:
        """Siyahı qabı — testlər sətir sayını buradan oxuyur."""
        return self._list_rows

    # ------------------------------ müqayisə ---------------------------------- #

    def _build_comparison_card(self) -> Card:
        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        self._detail_title = title_label("Konflikt seçilməyib", size=15)
        card.add(self._detail_title)
        self._detail_meta = mono_label("", muted=True)
        card.add(self._detail_meta)

        self._detail_warning = _danger_text("")
        self._detail_warning.setVisible(False)
        card.add(self._detail_warning)

        card.add(Divider())

        self._comparison_header = self._build_comparison_header()
        self._comparison_header.setVisible(False)
        card.add(self._comparison_header)

        self._field_rows = QVBoxLayout()
        self._field_rows.setSpacing(8)
        holder = QWidget()
        holder.setLayout(self._field_rows)
        card.add(holder)

        self._comparison_empty = muted_label("Müqayisə üçün soldan bir konflikt seçin.")
        card.add(self._comparison_empty)
        return card

    @staticmethod
    def _build_comparison_header() -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        marker = section_label("Fərq")
        marker.setFixedWidth(_MARKER_WIDTH)
        layout.addWidget(marker)

        name = section_label("Sahə")
        name.setFixedWidth(_FIELD_WIDTH)
        layout.addWidget(name)

        # İki versiya BƏRABƏR enlidir: yan-yana müqayisədə bir tərəfi geniş
        # vermək gözü həmin sütuna yönəldərdi, halbuki qərar simmetrikdir.
        layout.addWidget(section_label("Mağazadakı versiya (lokal)"), 1)
        layout.addWidget(section_label("Buluddakı versiya (uzaq)"), 1)
        return header

    def _build_field_row(self, row: dict[str, str]) -> QWidget:
        differs = row.get("differs") == "1"

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        marker: QWidget = Chip("Fərqli", "warning") if differs else muted_label("eyni", size=12)
        marker.setFixedWidth(_MARKER_WIDTH)
        layout.addWidget(marker)

        name = _value_label(row.get("field", ""), differs=differs)
        name.setFixedWidth(_FIELD_WIDTH)
        layout.addWidget(name)

        layout.addWidget(_value_label(row.get("local", ""), differs=differs), 1)
        layout.addWidget(_value_label(row.get("remote", ""), differs=differs), 1)
        return container

    def set_comparison(self, detail: dict[str, str], fields: list[dict[str, str]]) -> None:
        """Seçilmiş konfliktin iki versiyasını yan-yana göstərir.

        Args:
            detail: `id`, `table_label`, `record_label`, `detected`,
                `diff_count`, `audit_critical`. Boş sözlük → seçim yoxdur.
            fields: `field`, `local`, `remote`, `differs` açarları. Sıra
                kontrollerdən gəlir (fərqli sahələr əvvəldə) — ekran
                sıralamır, çünki "nə fərqlidir" qərarı `differing_fields()`
                metodundadır.
        """
        previous = self._selected_id
        self._selected_id = detail.get("id", "")

        for key, chip in self._selection_chips.items():
            chip.setVisible(key == self._selected_id)

        # BAŞQA konfliktə keçdikdə səbəb sahəsi TƏMİZLƏNİR: bir qeyd üçün
        # yazılmış izah digərinin audit sətrinə düşsəydi, jurnal yalan
        # danışardı — həm də bu, düzəldilə bilməyən yazıdır.
        if self._selected_id != previous:
            self._note.clear()
            self.show_form_error("")
            self.show_notice("")

        clear_layout(self._field_rows)
        self._detail_title.setText(detail.get("table_label", "") or "Konflikt seçilməyib")
        self._detail_meta.setText(
            " · ".join(
                part
                for part in (
                    detail.get("record_label", ""),
                    detail.get("detected", ""),
                    detail.get("diff_count", ""),
                )
                if part
            )
        )

        critical = detail.get("audit_critical") == "1"
        self._detail_warning.setText(AUDIT_CRITICAL_NOTE if critical else "")
        self._detail_warning.setVisible(critical)

        self._comparison_header.setVisible(bool(fields))
        self._comparison_empty.setVisible(not fields)
        for row in fields:
            self._field_rows.addWidget(self._build_field_row(row))

        self._sync_button_state()

    def field_layout(self) -> QVBoxLayout:
        """Müqayisə sətirlərinin qabı — testlər üçün."""
        return self._field_rows

    # -------------------------------- qərar ----------------------------------- #

    def _build_decision_card(self) -> Card:
        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        card.add(section_label("Qərar"))
        card.add(
            muted_label(
                "Hər iki versiya cədvəldə QALIR — qərar konflikti bağlayır və "
                "audit jurnalına düşür. Bir dəfə bağlanmış konflikt yenidən "
                "həll edilə bilmir.",
                size=12,
            )
        )

        card.add(field_label("Qərarın səbəbi"))
        self._note = QPlainTextEdit()
        self._note.setProperty("variant", "form")
        self._note.setMinimumHeight(84)
        self._note.setPlaceholderText("Hansı versiyanı niyə seçdiyinizi yazın…")
        self._note.textChanged.connect(self._sync_button_state)
        card.add(self._note)

        self._note_hint = muted_label("", size=12)
        card.add(self._note_hint)

        self._error = _danger_text("")
        self._error.setVisible(False)
        card.add(self._error)

        # Sakit ton: "başqası artıq həll edib" xəta DEYİL, məlumatdır.
        self._notice = muted_label("", size=12)
        self._notice.setVisible(False)
        card.add(self._notice)

        self._decisions = QVBoxLayout()
        self._decisions.setSpacing(12)
        holder = QWidget()
        holder.setLayout(self._decisions)
        card.add(holder)
        return card

    def set_resolutions(self, options: list[dict[str, str]]) -> None:
        """Qərar variantları — `code`, `label`, `hint` açarları.

        Etiketlər `Resolution.label_az`-dan gəlir (bax modul başlığı); `hint`
        boş ola bilər və yalnız izah tələb edən variantda doldurulur.
        """
        clear_layout(self._decisions)
        self._decision_buttons.clear()

        for option in options:
            self._decisions.addWidget(self._build_decision(option))
        self._sync_button_state()

    def _build_decision(self, option: dict[str, str]) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        code = option.get("code", "")
        # ÜÇÜ DƏ `secondary`: heç bir variant "tövsiyə olunan" deyil və
        # birini `action` etmək gözü ona yönəldərdi — halbuki doğru cavabı
        # yalnız qeydə baxan insan bilir.
        button = secondary_button(option.get("label", ""))
        button.setEnabled(False)
        button.clicked.connect(lambda *_, value=code: self._on_resolve(value))
        self._decision_buttons.append(button)
        layout.addWidget(button)

        hint = option.get("hint", "")
        if hint:
            layout.addWidget(muted_label(hint, size=12))
        return container

    def set_note_min_length(self, value: int) -> None:
        """Səbəbin minimum uzunluğu — `MIN_NOTE_LENGTH` (tətbiq qatından)."""
        self._note_min_length = max(0, value)
        self._note_hint.setText(
            f"Səbəb məcburidir — ən azı {self._note_min_length} simvol. "
            "Mətn audit jurnalına olduğu kimi düşür."
        )
        self._sync_button_state()

    def _cleaned_note(self) -> str:
        """Use case-in `resolve()`-də etdiyi EYNİ təmizləmə — `src/shared/
        text.py::normalise_decision_text` (artıq boşluqlar VƏ görünməz
        Unicode Cf simvolları, məs. sıfır-en boşluq)."""
        from src.shared.text import normalise_decision_text  # noqa: PLC0415

        return normalise_decision_text(self._note.toPlainText())

    def _required_length(self) -> int:
        """Ən azı BİR simvol: `set_note_min_length` çağırılmasa da boş qeyd keçməsin."""
        return max(1, self._note_min_length)

    def _sync_button_state(self) -> None:
        enabled = bool(self._selected_id) and len(self._cleaned_note()) >= self._required_length()
        for button in self._decision_buttons:
            button.setEnabled(enabled)

    def _on_resolve(self, code: str) -> None:
        if not self._selected_id:
            self.show_form_error("Əvvəlcə soldan bir konflikt seçin.")
            return
        note = self._cleaned_note()
        if len(note) < self._required_length():
            self.show_form_error(f"Səbəb ən azı {self._required_length()} simvol olmalıdır.")
            return

        self.show_form_error("")
        self.show_notice("")
        self.resolve_requested.emit({"id": self._selected_id, "resolution": code, "note": note})

    def decision_buttons(self) -> list[QPushButton]:
        """Qərar düymələri — testlər deaktiv vəziyyəti buradan yoxlayır."""
        return list(self._decision_buttons)

    # ------------------------------- mesajlar --------------------------------- #

    def show_form_error(self, message: str) -> None:
        """Qərar panelindəki xəta sətri (domen `user_message`-i)."""
        self._error.setText(message)
        self._error.setVisible(bool(message))

    def show_notice(self, message: str) -> None:
        """Sakit tonlu məlumat — "bu konflikt artıq həll olunub" kimi hallar."""
        self._notice.setText(message)
        self._notice.setVisible(bool(message))


# --------------------------------------------------------------------------- #
# Etiket köməkçiləri
# --------------------------------------------------------------------------- #


def _strong_label(text: str, *, size: int = 13) -> QLabel:
    """Qalın gövdə mətni — siyahı sətrinin başlığı."""
    label = body_label(text, size=size, wrap=False)
    font = label.font()
    font.setWeight(QFont.Weight.DemiBold)
    label.setFont(font)
    return label


def _danger_text(text: str) -> QLabel:
    """Təhlükə tonlu izah sətri — mövcud `danger-text` variantı (yeni rəng YOX)."""
    label = body_label(text, size=12)
    label.setProperty("variant", "danger-text")
    return label


def _value_label(text: str, *, differs: bool) -> QLabel:
    """Müqayisə xanası: fərqli sahə QALIN, eyni sahə SÖNÜK.

    Hər ikisi monoaralıqlıdır — dəyərlər baza sütunlarıdır və iki sütunu
    gözlə tutuşdurmaq sabit-enli şriftdə mümkün olur (bax `mono_label`
    başlığı). Vurğu üçün YENİ RƏNG işlədilmir: `mono` ↔ `mono-muted` cütü
    onsuz da kontrast yoxlayıcısından keçib.
    """
    label = mono_label(text, muted=not differs, size=13)
    if differs:
        font = label.font()
        font.setWeight(QFont.Weight.DemiBold)
        label.setFont(font)
    return label


__all__ = [
    "AUDIT_CRITICAL_NOTE",
    "EMPTY_MESSAGE",
    "EMPTY_TITLE",
    "SYNC_CONFLICT_HELP_INTRO",
    "SYNC_CONFLICT_HELP_STEPS",
    "SYNC_CONFLICT_HELP_TITLE",
    "SyncConflictScreen",
]
