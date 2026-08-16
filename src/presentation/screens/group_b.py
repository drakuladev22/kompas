"""Qrup B — kamera operatoru və anti-fraud — Faza 4.2.

Maket: "KompasOS - Qrup B.dc.html", ekranlar 06–08.

──────────────────────────────────────────────────────────────────────────────
BU EKRANLARDA VİDEO YOXDUR — QƏSDƏN
──────────────────────────────────────────────────────────────────────────────
Maketin öz izahı: "Bu ekranların heç birində video görüntü yoxdur — operator
fiziki görüntünü ayrıca iVMS proqramında izləyir. KompasOS yalnız təsdiq
axınını idarə edir."

Ona görə növbə kartında xatırladıcı sətir var ("Fiziki görüntünü iVMS
proqramında yoxlayın") — operator təsdiqi ekrandakı məlumata görə yox, öz
gördüyünə görə verməlidir. Bu sətri silmək anti-fraud axınının mənasını
itirərdi.

──────────────────────────────────────────────────────────────────────────────
MAĞAZA ƏHATƏSİ (SCOPE)
──────────────────────────────────────────────────────────────────────────────
Operator 21 filialın hamısını deyil, yalnız ona təyin edilmiş 2–3 mağazanı
görür. Ekran bunu həm göstərir (sol paneldəki "Təyinatım" kartı), həm də
altdakı qeyddə izah edir — əks halda operator "növbə boşdur" deyib digər
mağazaların sorğularını gözlədiyini sanardı.
"""

from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QSizePolicy,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from src.presentation.screens.base import Screen
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.data_table import Column, DataTable
from src.presentation.widgets.forms import FormField, field_label
from src.presentation.widgets.primitives import (
    Avatar,
    Card,
    Chip,
    ChipTone,
    Divider,
    FilterChip,
    body_label,
    is_activation_key,
    mono_label,
    muted_label,
    plain_label,
    stretch,
    title_label,
)

if TYPE_CHECKING:
    from PySide6.QtGui import (
        QDragEnterEvent,
        QDropEvent,
        QKeyEvent,
        QMouseEvent,
        QShowEvent,
    )

    from src.presentation.theme.manager import ThemeManager

#: Bu fərqdən BÖYÜK düzəliş ikinci təsdiq (Dual-Control) tələb edir.
#:
#: Bu, `system_limits.DUAL_CONTROL_THRESHOLD_MINUTES`-in FALLBACK-ıdır, tək
#: həqiqət mənbəyi DEYİL. Həddi tətbiq edən yer `leave_verification.py`-dır və
#: o, dəyəri Root panelindən oxuyur; dialoq isə yalnız XƏBƏRDARLIQ göstərir.
#: İkisi ayrılsaydı (Root 45 yazır, dialoq 30 deyir) operator ekranda gördüyü
#: ilə sistemin tətbiq etdiyi arasında uyğunsuzluq yaşayardı — ona görə
#: `threshold_minutes` konstruktorda ötürülür.
DUAL_CONTROL_THRESHOLD_MINUTES: Final = 30

#: Mağaza süzgəci bu SAYDAN ÇOX təyinatı olan operatorda görünür (audit G-6).
#:
#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits.CAMERA_QUEUE_STORE_FILTER_
#: THRESHOLD` (seed: migrations/058) və dəyər konstruktora ötürülür
#: (`app.py::_register_screens`). `DUAL_CONTROL_THRESHOLD_MINUTES` ilə eyni
#: naxış: ekran ROOT-u ÖZÜ oxumur, ona verilən ədədi işlədir.
QUEUE_STORE_FILTER_THRESHOLD: Final = 3

#: «Hamısı» seçiminin daxili açarı. Boş sətir SEÇİLMƏDİ: mağaza adı da boş ola
#: bilər (məlumat qüsuru) və o zaman "hamısı" ilə "adsız mağaza" eyni dəyərə
#: düşərdi. `*` isə heç bir mağaza adında olmayan işarədir.
ALL_STORES: Final = "*"


# --------------------------------------------------------------------------- #
# 06 — Canlı Təsdiq Növbəsi
# --------------------------------------------------------------------------- #


class QueueEntry:
    """Növbədəki bir sorğu — ekranın gözlədiyi məlumat forması."""

    __slots__ = (
        "employee_name",
        "is_late",
        "is_low_confidence",
        "kind",
        "position_name",
        "request_id",
        "store_name",
        "timestamp_text",
        "waiting_text",
    )

    def __init__(
        self,
        *,
        request_id: str,
        employee_name: str,
        store_name: str,
        position_name: str,
        kind: str,
        timestamp_text: str,
        waiting_text: str,
        is_late: bool = False,
        is_low_confidence: bool = False,
    ) -> None:
        self.request_id = request_id
        self.employee_name = employee_name
        self.store_name = store_name
        self.position_name = position_name
        #: "Giriş Təsdiqi" və ya "Qayıdış Təsdiqi".
        self.kind = kind
        self.timestamp_text = timestamp_text
        self.waiting_text = waiting_text
        #: `True` → gözləmə mətni xəbərdarlıq rəngində göstərilir.
        self.is_late = is_late
        #: Üz təsdiqi AŞAĞI-ETİBAR zolağında keçdi (facecontrol.md bənd 12).
        #:
        #: DEFOLT `False` VƏ BU, QƏSDƏNDİR: sahə mövcud çağırış nöqtələrinin
        #: heç birini dəyişmir (`screen_data._live_queue`, `preview_screens`,
        #: e2e testi). Nişan yalnız AÇIQ şəkildə `True` ötürüləndə görünür —
        #: əks halda operator hər sətirdə bir xəbərdarlıq görüb ona məhəl
        #: qoymamağa öyrəşərdi.
        self.is_low_confidence = is_low_confidence


class QueueRow(Card):
    """Növbə sətri — işçi, tip nişanı, vaxt və üç hərəkət düyməsi.

    Signals:
        approve_requested / reject_requested / adjust_requested: `request_id`.
    """

    approve_requested = Signal(str)
    reject_requested = Signal(str)
    adjust_requested = Signal(str)

    def __init__(
        self,
        entry: QueueEntry,
        theme: ThemeManager,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(padding=16, spacing=0, parent=parent)
        self._entry = entry

        line = QWidget()
        layout = QHBoxLayout(line)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(18)

        layout.addWidget(
            Avatar(
                entry.employee_name,
                background=theme.color("--color-neutral-bg"),
                foreground=theme.color("--color-text-primary"),
                size=46,
            )
        )

        identity = QWidget()
        identity_layout = QVBoxLayout(identity)
        identity_layout.setContentsMargins(0, 0, 0, 0)
        identity_layout.setSpacing(4)
        name = title_label(entry.employee_name, size=14)
        identity_layout.addWidget(name)
        identity_layout.addWidget(muted_label(f"{entry.store_name} · {entry.position_name}"))
        layout.addWidget(identity)

        # Tip nişanı — giriş/qayıdış fərqi bir baxışda görünməlidir.
        tone: ChipTone = "info" if entry.kind.startswith("Giriş") else "neutral"
        layout.addWidget(Chip(entry.kind, tone))

        # AŞAĞI-ETİBARLI ÜZ TƏSDİQİ (facecontrol.md bənd 12) — MÖVCUD `Chip`
        # naxışı, yeni rəng cütü YOX.
        #
        # NİŞAN SƏTRİ BLOKLAMIR: bal aşağı-etibar zolağındadırsa əməliyyat
        # DAVAM EDİB (`FaceGateOutcome.ALLOWED_LOW_CONFIDENCE`) və növbədə
        # normal sətir kimi durur. Nişanın yeganə məqsədi operatorun iVMS
        # yoxlamasını YÖNLƏNDİRMƏKDİR — «bu sətrə bir az diqqətlə bax».
        # `danger` tonu QƏSDƏN SEÇİLMƏDİ: qırmızı «fırıldaq aşkarlandı»
        # deməkdir, halbuki aşağı etibar çox vaxt işıqdan və ya bucaqdandır.
        if entry.is_low_confidence:
            layout.addWidget(Chip("aşağı-etibarlı üz təsdiqi", "warning"))

        time_box = QWidget()
        time_layout = QVBoxLayout(time_box)
        time_layout.setContentsMargins(0, 0, 0, 0)
        time_layout.setSpacing(4)
        time_layout.addWidget(mono_label(entry.timestamp_text))
        waiting = muted_label(entry.waiting_text)
        if entry.is_late:
            waiting.setStyleSheet(f"color: {theme.color('--color-warning')};")
        time_layout.addWidget(waiting)
        layout.addWidget(time_box)

        layout.addWidget(stretch())

        adjust = secondary_button("Vaxtı Düzəlt")
        adjust.clicked.connect(lambda: self.adjust_requested.emit(entry.request_id))
        layout.addWidget(adjust)

        reject = secondary_button("Rədd Et")
        reject.clicked.connect(lambda: self.reject_requested.emit(entry.request_id))
        layout.addWidget(reject)

        approve = action_button("Təsdiqlə")
        approve.clicked.connect(lambda: self.approve_requested.emit(entry.request_id))
        layout.addWidget(approve)

        self.add(line)

    @property
    def entry(self) -> QueueEntry:
        return self._entry


class OperatorQueueScreen(Screen):
    """Birləşmiş canlı təsdiq növbəsi (giriş + qayıdış).

    Signals:
        approve_requested / reject_requested / adjust_requested: `request_id`.
        filter_changed: Seçilmiş süzgəc ("all" / "check_in" / "return").
        store_filter_changed: Seçilmiş mağaza (`ALL_STORES` = hamısı).

    ──────────────────────────────────────────────────────────────────────────
    MAĞAZA SÜZGƏCİ NƏ EDİR VƏ NƏ ETMİR (audit G-6)
    ──────────────────────────────────────────────────────────────────────────
    EDİR: operatorun ARTIQ gördüyü sətirləri bir filiala daraldır — üç-dörd
    mağazanın sorğusu bir siyahıda qarışanda "hansı mağazanın növbəsi
    uzanıb?" sualı görünməz qalır.

    ETMİR: səlahiyyət GENİŞLƏNDİRMİR. Siyahıdakı mağazalar `assigned_stores`
    dəstindən gəlir və o, `CameraAssignmentRepository.stores_for_operator`
    nəticəsidir; «Hamısı» seçimi də MƏHZ həmin dəsti əhatə edir, "bütün
    şəbəkə"ni yox. Təyinatı olmayan operator boş növbə görür (fail-safe,
    bölmə 4) və süzgəc bu qərara heç nə əlavə etmir.

    SEÇİM SESSİYA BOYU YADDA QALIR, DİSKDƏ YOX: ekran örtük tərəfindən
    keşlənir (`AdminShell._screens`), yəni operator başqa ekrana keçib
    qayıdanda seçimi yerindədir. `user_preferences`-ə YAZILMIR — mağaza
    təyinatı dəyişə bilər və növbəti girişdə artıq mövcud olmayan filialın
    süzgəci ilə açılan növbə "boş" görünərdi, səbəbi isə heç yerdə yazılmazdı.
    """

    approve_requested = Signal(str)
    reject_requested = Signal(str)
    adjust_requested = Signal(str)
    filter_changed = Signal(str)
    store_filter_changed = Signal(str)

    _FILTERS: Final = (
        ("all", "Hamısı"),
        ("check_in", "Giriş Təsdiqi"),
        ("return", "Qayıdış Təsdiqi"),
    )

    def __init__(
        self,
        theme: ThemeManager,
        *,
        assigned_stores: list[str],
        store_filter_threshold: int = QUEUE_STORE_FILTER_THRESHOLD,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(theme, parent=parent)
        self._assigned_stores = assigned_stores
        self._active_filter = "all"
        self._active_store = ALL_STORES
        self._rows: list[QueueRow] = []
        #: Sonuncu doldurulmuş dəst — süzgəc dəyişəndə yenidən süzülür.
        self._entries: list[QueueEntry] = []

        # --- süzgəc çipləri --- #
        self._filter_bar = QWidget()
        filter_layout = QHBoxLayout(self._filter_bar)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(8)
        self._filter_chips: dict[str, FilterChip] = {}
        for key, label in self._FILTERS:
            chip = FilterChip(key, label, "neutral")
            chip.clicked.connect(self.set_filter)
            self._filter_chips[key] = chip
            filter_layout.addWidget(chip)
        filter_layout.addStretch(1)

        # --- mağaza seçicisi (audit G-6) --- #
        #
        # HƏDDƏN AZ TƏYİNATDA ÜMUMİYYƏTLƏ QURULMUR (`setVisible(False)` və ya
        # `setEnabled(False)` DEYİL): iki-üç mağazalı operator üçün seçici
        # heç nə etmir və yalnız üst paneli doldurardı. Layihənin ümumi
        # qaydası mənasız/icazəsiz elementi RENDER ETMƏMƏKDİR.
        self._store_box: QComboBox | None = None
        if len(assigned_stores) > max(1, store_filter_threshold):
            self._store_box = QComboBox()
            self._store_box.addItem(f"Bütün mağazalarım ({len(assigned_stores)})", ALL_STORES)
            for store in assigned_stores:
                self._store_box.addItem(store, store)
            self._store_box.setAccessibleName("Mağaza süzgəci — yalnız sizə təyin edilmişlər")
            self._store_box.setToolTip("Yalnız sizə təyin edilmiş mağazalar")
            self._store_box.currentIndexChanged.connect(self._on_store_selected)
            filter_layout.addWidget(field_label("Mağaza"))
            filter_layout.addWidget(self._store_box)

        self.add(self._filter_bar)

        # --- iVMS xatırladıcısı — bax modul başlığı --- #
        reminder = Card(padding=12, spacing=0)
        reminder_line = QWidget()
        reminder_layout = QHBoxLayout(reminder_line)
        reminder_layout.setContentsMargins(0, 0, 0, 0)
        reminder_layout.setSpacing(10)
        from src.presentation.widgets import icons  # noqa: PLC0415

        glyph = plain_label()
        glyph.setPixmap(icons.render("shield", theme.color("--color-info"), size=18))
        reminder_layout.addWidget(glyph)
        reminder_layout.addWidget(
            body_label("Fiziki görüntünü iVMS proqramında yoxlayın", size=13, wrap=False)
        )
        reminder_layout.addStretch(1)
        reminder.add(reminder_line)

        # --- ÜZ TƏSDİQİ ↔ OPERATOR SƏRHƏDİ (facecontrol.md, konseptual sərhəd)
        #
        # BU MƏTN MƏCBURİDİR VƏ SƏBƏBİ TƏHLÜKƏSİZLİKDİR. Face Control
        # kioskda avtomatik işləyir və operator onun mövcudluğunu bilirsə,
        # təbii nəticə belə olur: «sistem üzü yoxlayıb, deməli mən sürətlə
        # təsdiqləyə bilərəm». Bu, yanlış güvən hissidir — iki sistem İKİ
        # FƏRQLİ suala cavab verir:
        #
        #     Face Control → «kioskda duran şəxs KİMDİR» (identity)
        #     Operator/iVMS → «bu şəxs FİZİKİ olaraq orada idi, davranışı
        #                      normaldırmı» (presence/context)
        #
        # Üz təsdiqi STEP B/C təsdiqini NƏ ƏVƏZ EDİR, NƏ DƏ AVTOMATLAŞDIRIR.
        # Mətn olmasaydı, sərhəd yalnız sənəddə qalar və operator onu heç vaxt
        # oxumazdı.
        reminder.add(Divider())
        reminder.add(
            body_label(
                "Üz təsdiqi «kioskda duran şəxs KİMDİR» sualına cavab verir. Siz isə "
                "«bu şəxs FİZİKİ olaraq orada idi və davranışı normaldırmı» sualına "
                "cavab verirsiniz — bu, AYRI sualdır.",
                size=13,
            )
        )
        reminder.add(
            muted_label(
                "Üz təsdiqi sizin təsdiqinizi ƏVƏZ ETMİR və avtomatlaşdırmır. Hər iki "
                "yoxlama paralel işləyir; «aşağı-etibarlı üz təsdiqi» nişanı olan sətrə "
                "xüsusilə diqqətlə baxın."
            )
        )
        self.add(reminder)

        # --- sətirlər --- #
        self._rows_host = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(12)
        self.add(self._rows_host)

        self.body().addStretch(1)

        self._scope_note = muted_label(
            f"Yalnız sizə təyin edilmiş {len(assigned_stores)} mağazanın sorğuları "
            "görünür. Təyinat dəyişikliyi üçün Admin ilə əlaqə saxlayın."
        )
        self._scope_note.setWordWrap(True)
        self.add(self._scope_note)

        self.set_filter("all")

    # ------------------------------- məzmun ---------------------------------- #

    def set_entries(self, entries: list[QueueEntry]) -> None:
        """Növbəni yeniləyir.

        Boş təyinat (operatora heç bir mağaza verilməyib) AYRI haldır və
        "növbə boşdur" ilə qarışdırılmamalıdır — birincidə problem
        konfiqurasiyadadır, ikincisi normal iş vəziyyətidir.

        SƏTİRLƏR KEŞLƏNİR (audit G-6): mağaza süzgəci dəyişəndə eyni dəst
        yenidən süzülür və baza sorğusu göndərilmir (bax `set_store_filter`).
        """
        self._entries = list(entries)
        for row in self._rows:
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()

        self._update_filter_counts(entries)

        if not self._assigned_stores:
            self.show_empty(
                icon_name="shield",
                title="Sizə mağaza təyin edilməyib",
                message=(
                    "Təsdiq növbəsini görmək üçün ən azı bir mağazaya təyinat "
                    "lazımdır. Admin ilə əlaqə saxlayın."
                ),
            )
            return

        visible = [e for e in entries if self._matches(e)]
        if not visible:
            self.show_empty(
                icon_name="check_circle",
                title="Gözləyən sorğu yoxdur",
                message=(
                    "Bütün giriş və qayıdış sorğuları təsdiqlənib. Yeni sorğu "
                    "gəldikdə burada dərhal görünəcək."
                ),
            )
            return

        for entry in visible:
            row = QueueRow(entry, self.theme)
            row.approve_requested.connect(self.approve_requested)
            row.reject_requested.connect(self.reject_requested)
            row.adjust_requested.connect(self.adjust_requested)
            self._rows_layout.addWidget(row)
            self._rows.append(row)

        self.show_content()

    def _matches(self, entry: QueueEntry) -> bool:
        # MAĞAZA SÜZGƏCİ ƏVVƏL: tip süzgəci ilə VƏ ilə birləşir — operator
        # "yalnız bu filialın giriş təsdiqləri" kəsişməsini istəyə bilər.
        if not self._in_store_scope(entry):
            return False
        if self._active_filter == "all":
            return True
        if self._active_filter == "check_in":
            return entry.kind.startswith("Giriş")
        return entry.kind.startswith("Qayıdış")

    def _update_filter_counts(self, entries: list[QueueEntry]) -> None:
        """Çip saylarını yeniləyir — SAYLAR MAĞAZA SÜZGƏCİNƏ TABEDİR.

        Süzgəc «Bellona 28 May»-dədirsə, "Giriş Təsdiqi · 12" yazmaq yanlış
        olardı: operator ekranda üç sətir görüb 12 rəqəmini oxuyar və hansının
        doğru olduğunu bilməzdi.
        """
        scoped = [entry for entry in entries if self._in_store_scope(entry)]
        totals = {
            "all": len(scoped),
            "check_in": sum(1 for e in scoped if e.kind.startswith("Giriş")),
            "return": sum(1 for e in scoped if e.kind.startswith("Qayıdış")),
        }
        for key, label in self._FILTERS:
            self._filter_chips[key].setText(f"{label} · {totals[key]}")

    def _in_store_scope(self, entry: QueueEntry) -> bool:
        """Sətir seçilmiş mağazaya aiddirmi (`ALL_STORES` → hamısı)."""
        if self._active_store == ALL_STORES:
            return True
        return entry.store_name == self._active_store

    def set_filter(self, key: str) -> None:
        """Süzgəci dəyişir; aktiv çip dolu fon alır."""
        self._active_filter = key
        for chip_key, chip in self._filter_chips.items():
            chip.set_tone("info" if chip_key == key else "neutral")
        self.filter_changed.emit(key)

    def _on_store_selected(self) -> None:
        if self._store_box is None:  # pragma: no cover - tip qoruyucusu
            return
        self.set_store_filter(str(self._store_box.currentData()))

    def set_store_filter(self, store: str) -> None:
        """Mağaza süzgəcini dəyişir.

        TƏYİNATDAN KƏNAR AD RƏDD EDİLİR: süzgəc yalnız GÖRÜNÜŞÜ daraldır,
        yəni siyahıda olmayan mağazanı seçmək cəhdi sükutla «hamısı»na
        qayıtmalıdır — əks halda ekran heç vaxt dolmayan bir vəziyyətdə
        qalardı və səbəbi görünməzdi.
        """
        if store != ALL_STORES and store not in self._assigned_stores:
            store = ALL_STORES
        self._active_store = store
        # KEŞLƏNMİŞ SƏTİRLƏR YENİDƏN SÜZÜLÜR, BAZAYA GEDİLMİR: süzgəc
        # GÖRÜNÜŞ əməliyyatıdır və məlumat artıq ekrandadır. Yeni sorğu
        # göndərmək eyni nəticəni gecikməylə verər, üstəlik operator hər
        # seçimdə növbənin "yenidən yüklənməsini" görərdi.
        self.set_entries(list(self._entries))
        self.store_filter_changed.emit(store)

    @property
    def active_filter(self) -> str:
        return self._active_filter

    @property
    def active_store(self) -> str:
        """Seçilmiş mağaza (`ALL_STORES` = təyin edilmişlərin hamısı)."""
        return self._active_store

    @property
    def store_filter_visible(self) -> bool:
        """Mağaza seçicisi QURULUBMU (görünürlük deyil, MÖVCUDLUQ)."""
        return self._store_box is not None

    @property
    def visible_rows(self) -> int:
        return len(self._rows)


# --------------------------------------------------------------------------- #
# 07 — Manual Vaxt Düzəlişi
# --------------------------------------------------------------------------- #


class ManualTimeOverrideDialog(QDialog):
    """Vaxtı əl ilə düzəltmə modalı.

    Signals:
        submitted: (düzəldilmiş vaxt mətni, səbəb).

    Səbəb MƏCBURİDİR və audit jurnalına yazılır — modal bunu açıq şəkildə
    yazır ("Səbəb audit jurnalına yazılır və silinmir"), çünki operator
    düzəlişin izlənildiyini BİLMƏLİDİR; anti-fraud dəyəri məhz buradadır.
    """

    submitted = Signal(str, str)

    def __init__(
        self,
        theme: ThemeManager,
        *,
        employee_name: str,
        store_name: str,
        kind: str,
        system_time: str,
        threshold_minutes: int = DUAL_CONTROL_THRESHOLD_MINUTES,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._system_time = system_time
        # 0/mənfi dəyər "hər düzəliş ikinci təsdiq tələb edir" demək olardı;
        # səhv konfiqurasiya iş axınını dayandırmamalıdır (fail-open).
        self._threshold_minutes = (
            threshold_minutes if threshold_minutes > 0 else DUAL_CONTROL_THRESHOLD_MINUTES
        )
        self.setWindowTitle("Vaxtı Manual Düzəlt")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = Card(padding=28, spacing=20)
        layout.addWidget(card)

        # ------------------------------ başlıq ------------------------------ #
        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(10)

        head_text = QWidget()
        head_text_layout = QVBoxLayout(head_text)
        head_text_layout.setContentsMargins(0, 0, 0, 0)
        head_text_layout.setSpacing(4)
        head_text_layout.addWidget(title_label("Vaxtı Manual Düzəlt", size=20))
        head_text_layout.addWidget(muted_label(f"{employee_name} · {store_name} · {kind}"))
        head_layout.addWidget(head_text)
        head_layout.addWidget(stretch())

        close = secondary_button("×")
        close.setFixedWidth(42)
        close.clicked.connect(self.reject)
        head_layout.addWidget(close)
        card.add(head)
        card.add(Divider())

        # ------------------------------ vaxtlar ----------------------------- #
        times = QWidget()
        times_layout = QHBoxLayout(times)
        times_layout.setContentsMargins(0, 0, 0, 0)
        times_layout.setSpacing(24)

        system_box = QWidget()
        system_layout = QVBoxLayout(system_box)
        system_layout.setContentsMargins(0, 0, 0, 0)
        system_layout.setSpacing(7)
        system_layout.addWidget(field_label("Sistem qeydi"))
        system_value = mono_label(system_time, size=18)
        system_layout.addWidget(system_value)
        times_layout.addWidget(system_box)

        self._time_edit = QTimeEdit()
        self._time_edit.setDisplayFormat("HH:mm")
        from PySide6.QtCore import QTime  # noqa: PLC0415

        parsed = QTime.fromString(system_time, "HH:mm")
        if parsed.isValid():
            self._time_edit.setTime(parsed)
        self._time_edit.timeChanged.connect(self._on_time_changed)
        corrected = FormField("Düzəldilmiş vaxt", widget=self._time_edit)
        times_layout.addWidget(corrected, 1)

        card.add(times)

        # ------------------------------ səbəb ------------------------------- #
        reason_box = QWidget()
        reason_layout = QVBoxLayout(reason_box)
        reason_layout.setContentsMargins(0, 0, 0, 0)
        reason_layout.setSpacing(7)
        reason_layout.addWidget(field_label("Səbəb *"))

        self._reason = QPlainTextEdit()
        self._reason.setPlaceholderText("Nə üçün düzəliş edilir? Hadisəni qısa və konkret yazın.")
        self._reason.setFixedHeight(96)
        self._reason.textChanged.connect(self._on_reason_changed)
        reason_layout.addWidget(self._reason)

        self._reason_error = plain_label()
        self._reason_error.setProperty("variant", "danger-text")
        self._reason_error.setVisible(False)
        reason_layout.addWidget(self._reason_error)

        reason_layout.addWidget(muted_label("Səbəb audit jurnalına yazılır və silinmir."))
        card.add(reason_box)

        # -------------------------- dual-control ---------------------------- #
        self._dual_control = Card(padding=14, spacing=6)
        self._dual_control.add(title_label("Cüt Nəzarətli Təsdiq Tələb Olunacaq", size=14))
        self._dual_control_detail = body_label("", size=13)
        self._dual_control.add(self._dual_control_detail)
        self._dual_control.setVisible(False)
        card.add(self._dual_control)

        # ------------------------------ düymələr ---------------------------- #
        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)
        buttons_layout.addWidget(stretch())

        cancel = secondary_button("İmtina")
        cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel)

        self._submit = action_button("Təsdiqə Göndər")
        self._submit.clicked.connect(self._on_submit)
        buttons_layout.addWidget(self._submit)
        card.add(buttons)

        # ──────────────────────────────────────────────────────────────────
        # ENTER TƏSDİQ ETMİR — İMTİNA EDİR
        # ──────────────────────────────────────────────────────────────────
        # Bu modal anti-fraud nöqtəsidir: vaxtın əl ilə düzəldilməsi audit
        # jurnalına yazılır və hədd aşılarsa Dual-Control tələb edir. Səbəb
        # sahəsi `QPlainTextEdit`-dir, yəni orada Enter YENİ SƏTİR yazır —
        # istifadəçi mətn yazarkən Enter-in formanı göndərməsini gözləmir.
        # Defolt təsdiq düyməsi bu gözləntini pozardı və izlənilən bir
        # əməliyyat təsadüfən başladılardı.
        cancel.setDefault(True)
        cancel.setAutoDefault(False)
        self._submit.setDefault(False)
        self._submit.setAutoDefault(False)

        # Fokus sırası: vaxt → səbəb → imtina → göndər.
        QWidget.setTabOrder(self._time_edit, self._reason)
        QWidget.setTabOrder(self._reason, cancel)
        QWidget.setTabOrder(cancel, self._submit)

        # İlkin fokus DÜZƏLDİLƏCƏK VAXTDADIR — modalın bütün mövcudluq səbəbi
        # odur; səbəb sahəsi ondan sonra gəlir.
        self._time_edit.setFocus(Qt.FocusReason.OtherFocusReason)

    # ------------------------------- məntiq ---------------------------------- #

    def difference_minutes(self) -> int:
        """Sistem qeydi ilə düzəldilmiş vaxt arasındakı fərq (mütləq dəqiqə)."""
        from PySide6.QtCore import QTime  # noqa: PLC0415

        original = QTime.fromString(self._system_time, "HH:mm")
        if not original.isValid():
            return 0
        return abs(original.secsTo(self._time_edit.time())) // 60

    def _on_time_changed(self) -> None:
        difference = self.difference_minutes()
        requires = difference > self._threshold_minutes
        self._dual_control.setVisible(requires)
        if requires:
            self._dual_control_detail.setText(
                f"Fərq {difference} dəqiqədir "
                f"({self._threshold_minutes} dəqiqədən çox). Düzəliş "
                "ikinci səlahiyyətli şəxs təsdiqləyənə qədər gözləmədə qalacaq."
            )

    def _on_reason_changed(self) -> None:
        if self._reason.toPlainText().strip():
            self._reason_error.setVisible(False)

    def _on_submit(self) -> None:
        reason = self._reason.toPlainText().strip()
        if not reason:
            self._reason_error.setText("Səbəb məcburidir")
            self._reason_error.setVisible(True)
            return
        self.submitted.emit(self._time_edit.time().toString("HH:mm"), reason)
        self.accept()

    @property
    def requires_dual_control(self) -> bool:
        return self.difference_minutes() > self._threshold_minutes


# --------------------------------------------------------------------------- #
# 08 — Cərimələr: Manual Qeydiyyat
# --------------------------------------------------------------------------- #


class PhotoDropZone(Card):
    """Foto sübutu sahəsi — sürüklə-burax və ya seç.

    Signals:
        file_selected: Seçilmiş faylın yolu.

    Foto MƏCBURİDİR (spesifikasiya): sübut olmadan qeyd edilən cərimə
    etiraz zamanı müdafiə oluna bilməzdi.
    """

    file_selected = Signal(str)

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(padding=22, spacing=8, parent=parent)
        self._theme = theme
        self._path = ""
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(120)
        # ──────────────────────────────────────────────────────────────────
        # NİYƏ BU SAHƏ MÜTLƏQ KLAVİATURA İLƏ İŞLƏMƏLİDİR
        # ──────────────────────────────────────────────────────────────────
        # Foto sübutu MƏCBURİDİR (bax sinif başlığı): şəkil olmadan cərimə
        # yazıla bilmir. Sahə yalnız `mousePressEvent`-ə bağlı qalsaydı,
        # siçansız istifadəçi cərimə axınını SONA QƏDƏR apara bilməzdi —
        # yəni bir əlçatanlıq qüsuru bütöv bir iş prosesini bağlayardı.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Foto sübutu seç")
        self.setAccessibleDescription(
            "Şəkli bura sürükləyin və ya Enter ilə fayl seçimini açın (PNG/JPG)"
        )

        from src.presentation.widgets import icons  # noqa: PLC0415

        self._glyph = plain_label()
        self._glyph.setPixmap(icons.render("image", theme.color("--color-text-muted"), size=26))
        self._glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.add(self._glyph)

        self._title = body_label("Şəkil əlavə et", size=14)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.add(self._title)

        self._hint = muted_label("sürüklə və ya seç · PNG/JPG")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.add(self._hint)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - Qt adlandırması
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 - Qt adlandırması
        urls = event.mimeData().urls()
        if urls:
            self.set_file(urls[0].toLocalFile())
            event.acceptProposedAction()

    def _activate(self) -> None:
        """Fayl seçimini açır — siçan və klaviatura üçün ORTAQ yol."""
        from PySide6.QtWidgets import QFileDialog  # noqa: PLC0415

        path, _ = QFileDialog.getOpenFileName(
            self, "Foto sübutu seçin", "", "Şəkillər (*.png *.jpg *.jpeg)"
        )
        if path:
            self.set_file(path)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        self._activate()
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt adlandırması
        if is_activation_key(event):
            self._activate()
            event.accept()
            return
        super().keyPressEvent(event)

    def set_file(self, path: str) -> None:
        from pathlib import Path  # noqa: PLC0415

        self._path = path
        self._title.setText(Path(path).name)
        self._hint.setText("Dəyişmək üçün klikləyin")
        self.file_selected.emit(path)

    @property
    def file_path(self) -> str:
        return self._path

    def clear(self) -> None:
        self._path = ""
        self._title.setText("Şəkil əlavə et")
        self._hint.setText("sürüklə və ya seç · PNG/JPG")


class FineEntryScreen(Screen):
    """Manual cərimə qeydiyyatı + bu ayın cərimələri siyahısı.

    Signals:
        submitted: Forma məlumatı (`dict`).
    """

    submitted = Signal(dict)

    #: Status → nişan tonu (maketdəki rənglərlə eyni).
    _STATUS_TONES: Final[dict[str, ChipTone]] = {
        "Təsdiqlənib": "success",
        "Etiraz edilib": "warning",
        "Ləğv edilib": "neutral",
        "Gözləyir": "info",
    }

    def __init__(
        self,
        theme: ThemeManager,
        *,
        fine_types: list[str],
        stores: list[str],
        employees: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(theme, parent=parent)

        columns = [
            Column("İşçi", 220),
            Column("Növ", 180),
            Column("Tarix", 110, mono=True),
            Column("Məbləğ", 110),
            Column("Vəziyyət"),
        ]

        self.add(self._build_form(fine_types, stores, employees))
        self.add(title_label("Bu ayın cərimələri", size=16))
        self._summary = muted_label("")
        self.add(self._summary)

        self._table = DataTable(
            columns,
            theme,
            footnote=(
                "Cərimə qeyd edildikdən sonra işçiyə bildiriş gedir və 3 gün "
                "ərzində etiraz edə bilər."
            ),
        )
        self.add(self._table)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt adlandırması
        """Ekran açılanda fokus formanın ilk sahəsinə («Cərimə Növü») qoyulur.

        Səbəb `AdminLoginScreen.showEvent`-də izah olunub: ekran örtükdəki
        yığının bir səhifəsidir və konstruktor işlədikdə hələ görünmür.
        Fokusun forma ilə başlaması operatorun ilk hərəkətini — növ seçmək —
        siçansız da mümkün edir; qiymət sahəsi məhz həmin seçimdən dolur.
        """
        super().showEvent(event)
        self._type.focus_input()

    # -------------------------------- forma ---------------------------------- #

    def _build_form(self, fine_types: list[str], stores: list[str], employees: list[str]) -> Card:
        card = Card(padding=22, spacing=18)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.addWidget(title_label("Yeni Cərimə", size=16))
        head_layout.addWidget(stretch())
        card.add(head)
        card.add(Divider())

        grid = QWidget()
        grid_layout = QHBoxLayout(grid)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(18)

        self._type = FormField("Cərimə Növü", widget=self._combo(fine_types))
        grid_layout.addWidget(self._type, 1)

        self._store = FormField(
            "Mağaza",
            widget=self._combo(stores),
            hint="Yalnız sizə təyin edilmiş mağazalar",
        )
        grid_layout.addWidget(self._store, 1)

        self._employee = FormField("İşçi", widget=self._combo(employees))
        grid_layout.addWidget(self._employee, 1)
        card.add(grid)

        second = QWidget()
        second_layout = QHBoxLayout(second)
        second_layout.setContentsMargins(0, 0, 0, 0)
        second_layout.setSpacing(18)

        date_edit = QDateEdit()
        date_edit.setDisplayFormat("dd.MM.yyyy")
        date_edit.setCalendarPopup(True)
        from PySide6.QtCore import QDate  # noqa: PLC0415

        date_edit.setDate(QDate.currentDate())
        self._date = FormField("Tarix", widget=date_edit)
        second_layout.addWidget(self._date, 1)

        # Qiymət cərimə növündən gəlir və ƏL İLƏ DƏYİŞDİRİLMİR — əks halda
        # eyni pozuntuya görə fərqli məbləğlər yazıla bilərdi.
        self._price = FormField("Qiymət", widget=self._readonly_field("—"))
        self._price.input_widget().setEnabled(False)
        second_layout.addWidget(self._price, 1)
        second_layout.addWidget(stretch(), 1)
        card.add(second)

        photo_box = QWidget()
        photo_layout = QVBoxLayout(photo_box)
        photo_layout.setContentsMargins(0, 0, 0, 0)
        photo_layout.setSpacing(7)
        photo_layout.addWidget(field_label("Foto Sübutu *"))
        self._photo = PhotoDropZone(self.theme)
        photo_layout.addWidget(self._photo)
        self._photo_error = plain_label()
        self._photo_error.setProperty("variant", "danger-text")
        self._photo_error.setVisible(False)
        photo_layout.addWidget(self._photo_error)
        card.add(photo_box)

        submit_row = QWidget()
        submit_layout = QHBoxLayout(submit_row)
        submit_layout.setContentsMargins(0, 0, 0, 0)
        submit_layout.addWidget(stretch())
        self._submit = action_button(
            "Cəriməni Qeyd Et", icon_name="plus", icon_color=self.theme.color("--color-action-text")
        )
        self._submit.clicked.connect(self._on_submit)
        submit_layout.addWidget(self._submit)
        card.add(submit_row)

        # Zəncir bütün sahələr yarandıqdan SONRA qurulur (bax
        # `group_a_entry.AdminLoginScreen`): Qt `setTabOrder`-i yalnız MÖVCUD
        # widget cütünə tətbiq edir və sonradan yaradılan hər şeyi zəncirin
        # sonuna atır. Sıra maketdəki oxu istiqamətini təkrarlayır:
        # növ → mağaza → işçi → tarix → foto → qeyd et.
        # «Qiymət» sıradan KƏNARDADIR — o, deaktivdir və dəyəri növdən gəlir.
        chain: tuple[QWidget, ...] = (
            self._type.input_widget(),
            self._store.input_widget(),
            self._employee.input_widget(),
            self._date.input_widget(),
            self._photo,
            self._submit,
        )
        for previous, following in pairwise(chain):
            QWidget.setTabOrder(previous, following)

        return card

    @staticmethod
    def _combo(values: list[str]) -> QComboBox:
        combo = QComboBox()
        combo.addItems(values)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return combo

    @staticmethod
    def _readonly_field(text: str) -> QLineEdit:
        field = QLineEdit(text)
        field.setReadOnly(True)
        return field

    def set_price(self, text: str) -> None:
        """Cərimə növü seçildikdə avtomatik doldurulur ("25 ₼ · avtomatik")."""
        self._price.set_text(text)

    def _on_submit(self) -> None:
        if not self._photo.file_path:
            self._photo_error.setText("Foto sübutu məcburidir")
            self._photo_error.setVisible(True)
            return
        self._photo_error.setVisible(False)

        self.submitted.emit(
            {
                "fine_type": self._type.text(),
                "store": self._store.text(),
                "employee": self._employee.text(),
                "date": self._date.text(),
                "photo_path": self._photo.file_path,
            }
        )

    # -------------------------------- siyahı --------------------------------- #

    def set_fines(
        self,
        fines: list[dict[str, str]],
        *,
        period_text: str,
        total_text: str,
    ) -> None:
        """Bu ayın cərimələrini göstərir."""
        self._summary.setText(f"{period_text} · {len(fines)} qeyd · {total_text}")
        self._table.clear()

        for fine in fines:
            status = fine.get("status", "Gözləyir")
            self._table.add_row(
                [
                    fine.get("employee", ""),
                    fine.get("type", ""),
                    mono_label(fine.get("date", "")),
                    mono_label(fine.get("amount", "")),
                    Chip(status, self._STATUS_TONES.get(status, "neutral")),
                ]
            )
        self.show_content()

    def table(self) -> DataTable:
        return self._table


__all__ = [
    "DUAL_CONTROL_THRESHOLD_MINUTES",
    "FineEntryScreen",
    "ManualTimeOverrideDialog",
    "OperatorQueueScreen",
    "PhotoDropZone",
    "QueueEntry",
    "QueueRow",
]
