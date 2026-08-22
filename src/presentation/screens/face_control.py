"""Face Control (Üz Təsdiqi) ekranları — `facecontrol.md` Faza 4.

ÜÇ WIDGET, ÜÇ AYRI AUDİTORİYA VƏ ÜÇ AYRI SƏLAHİYYƏT:

    `FaceEnrollmentScreen`   → admin (`can_manage_employees`) — bənd 1, 2, 11
    `FaceExemptionScreen`    → YALNIZ Root/CEO (`can_manage_face_exemptions`) — bənd 14
    `FaceVerificationOverlay`→ kioskda duran İŞÇİ — bənd 3, 5, 6, 12

Maketdə (Qrup A–I) yeri yoxdur — `annual_leave.py`, `announcements.py` və
`bulk_operations.py` ilə eyni vəziyyət: Faza 5-dən sonrakı funksiya öz adı ilə
fayl alır və mövcud dizayn dilini (`Card`, `DataTable`, `Chip`,
`QComboBox[variant="form"]`) TƏKRAR İSTİFADƏ edir.

──────────────────────────────────────────────────────────────────────────────
ŞƏKİL EKRANA ÇIXMIR — «CANLI ÖNİZLƏMƏ» NİYƏ VİDEO AXINI DEYİL
──────────────────────────────────────────────────────────────────────────────
`migrations/047`-nin birinci qaydası belədir: kadr DİSKƏ YAZILMIR və ŞƏBƏKƏYƏ
ÇIXMIR; `FaceFrame` yalnız yaddaşda yaşayır və `__repr__`-i maskalanıb.
`CameraCapture` portu (bax `interfaces/ports.py`) məhz buna görə önizləmə
axını TƏQDİM ETMİR — onun yeganə metodu `capture()`-dır və nəticə birbaşa
`FaceMatcher`-ə gedir.

Ona görə bu ekrandakı «canlı önizləmə» sahəsi kameranın VƏZİYYƏTİNİ göstərir
(hazırdır / əlçatmazdır / çəkiliş gedir / neçə kadr keçdi), ŞƏKLİ yox. Qt-də
`QVideoWidget` ilə kadr göstərmək texniki cəhətdən mümkün idi və QƏSDƏN rədd
edildi: o zaman biometrik kadr GUI ağacına düşərdi, yəni ekran görüntüsü,
`grab()` çağırışı və ya çökmə dump-ı onu diskə çıxara bilərdi — qaydanın
bütün mənası itərdi.

«Çəkilmiş kadrlar qalereyası» də YOXDUR (agent qaydası 4): operator kadrın
ÖZÜNÜ deyil, onun TALEYİNİ görür — «2-ci kadr: çox qaranlıq».

──────────────────────────────────────────────────────────────────────────────
ÜÇ DÜYMƏNİN MƏNASI (`[Çək]` / `[Yenidən Çək]` / `[Yadda Saxla]`)
──────────────────────────────────────────────────────────────────────────────
`FaceEnrollmentUseCase.capture_and_store` ATOMİKDİR: kadr çəkilişi, keyfiyyət
süzgəci, orta vektor (bənd 11) və yazı BİR çağırışdadır. «Əvvəlcə çək, sonra
yadda saxla» iki-fazalı variant ciddi nəzərdən keçirildi və rədd edildi —
ikinci faza kadrları YENİDƏN çəkməli olardı, yəni operatorun ekranda gördüyü
keyfiyyət balı SAXLANILAN vektora aid olmazdı (fərqli kadrlar, fərqli işıq).
Bu, ən pis formadır: ekran bir şey göstərir, baza başqa şey saxlayır.

Ona görə düymələr REJİMƏ görə paylanıb:

    `ENROLL`     → `[Çək]`          (ilk qeydiyyat, səbəb tələb olunmur)
    `RE_ENROLL`  → `[Yadda Saxla]`  (səbəb MƏCBURİ, köhnə vektor arxivlənir)
    hər ikisi    → `[Yenidən Çək]`  (yalnız RƏDD edilmiş cəhddən sonra görünür)

──────────────────────────────────────────────────────────────────────────────
YENİ RƏNG CÜTÜ YOXDUR
──────────────────────────────────────────────────────────────────────────────
Overlay `objectName = "PinScreen"` işlədir, yəni AAA kontrastlı
`--color-pin-*` cütünü OLDUĞU KİMİ miras alır (`qss.py` «PIN EKRANI» bloku) və
düymələri `variant="keypad"`-dir — 88px toxunma hədəfi, kalibrlənmiş rəng.
Nəticə mətninin rəngi (`--color-danger`/`--color-success`/`--color-warning`)
`PinPadScreen.show_message` ilə EYNİ naxışdadır və həmin cütlər
`scripts/check_contrast.py`-a əlavə olunub.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
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
    from src.presentation.widgets.primitives import ChipTone

#: Overlay-dəki mətnin ölçüsü — kiosk toxunma-ilkdir və işçi ekrandan bir
#: qol məsafəsində dayanır (`PinPadScreen`-in 22px göstərişi ilə eyni pillə).
OVERLAY_PROMPT_SIZE: Final = 22
OVERLAY_TITLE_SIZE: Final = 26

#: `FaceGateOutcome` dəyəri → (başlıq, rəng tokeni). AÇARLAR USE CASE-DƏNDİR
#: (`application/use_cases/face_control.FaceGateOutcome`), ekran öz ad məkanını
#: QURMUR — `menu.py` başlığındakı tarixi qüsur məhz belə yaranmışdı.
#:
#: MƏTN İSƏ EKRANINDIR: use case-in `message_az`-ı NƏ BAŞ VERDİYİNİ izah edir
#: («Üz uyğun gəlmədi. Əməliyyat dayandırıldı.»), başlıq isə işçinin bir
#: baxışda oxuduğu nəticədir. İkisini birləşdirmək uzun cümləni 26px-də
#: göstərmək demək olardı.
OUTCOME_TITLES: Final[dict[str, tuple[str, str]]] = {
    "ALLOWED": ("Üz təsdiqləndi", "--color-success"),
    "ALLOWED_LOW_CONFIDENCE": ("Üz təsdiqləndi — aşağı etibar", "--color-warning"),
    "RETRY": ("Üz aşkarlanmadı", "--color-warning"),
    "BLOCKED": ("Üz uyğun gəlmədi", "--color-danger"),
    "LOCKED": ("Hesab müvəqqəti bloklandı", "--color-danger"),
    "MANUAL_APPROVAL_REQUIRED": ("Manual təsdiq lazımdır", "--color-warning"),
    "DUAL_CONTROL_REQUIRED": ("İkinci təsdiq lazımdır", "--color-warning"),
    "NOT_APPLICABLE": ("Üz təsdiqi tətbiq olunmur", "--color-info"),
}

#: Naməlum nəticə üçün ehtiyat — SÜKUTLA keçmir (bax `_apply_outcome`).
FALLBACK_OUTCOME_TITLE: Final = ("Nəticə oxunmadı", "--color-danger")

#: Qeydiyyat vəziyyəti → (nişan mətni, ton). Açarlar kontrollerin
#: `enrollment_state()` funksiyası ilə EYNİDİR.
ENROLLMENT_STATE_CHIPS: Final[dict[str, tuple[str, ChipTone]]] = {
    "NEW": ("Qeydiyyatsız", "danger"),
    "ENROLLED": ("Qeydiyyatlı", "success"),
    "STALE": ("Köhnəlib", "warning"),
}


# --------------------------------------------------------------------------- #
# 1–2. Qeydiyyat / yenidən-qeydiyyat ekranı (bənd 1, 2, 11)
# --------------------------------------------------------------------------- #


class FaceEnrollmentScreen(Screen):
    """Nəzarətli üz qeydiyyatı — YALNIZ admin girişində (bənd 1).

    Signals:
        subject_changed: Seçilmiş işçi dəyişdi (`employee_id`).
        capture_requested: `[Çək]` — ilk qeydiyyat (`employee_id`).
        re_enroll_requested: `[Yadda Saxla]` — yenidən-qeydiyyat
            (`employee_id`, `reason`).
        retake_requested: `[Yenidən Çək]` — SON əməliyyatı təkrarlayır
            (`employee_id`).
        refresh_requested: `[Yenilə]`.

    ──────────────────────────────────────────────────────────────────────────
    İŞÇİ BU EKRANI ÖZÜ AÇA BİLMİR — QAPI İKİ YERDƏDİR
    ──────────────────────────────────────────────────────────────────────────
    Menyu maddəsi `can_manage_employees` ilə qapılıdır (`shell/menu.py`), yəni
    flag-i olmayan istifadəçidə maddə RENDER OLUNMUR (boz deyil, YOX). Lakin
    menyunun gizlədilməsi əməliyyat icazəsi DEYİL: faktiki qapı
    `FaceEnrollmentUseCase.assert_may_enroll`-dadır və o, ÖZÜNƏ-qeydiyyatı da
    ayrıca bloklayır — admin öz üzünü öz hesabına bağlaya bilməz.

    Ekran həmin qaydanı TƏKRARLAMIR (domen məntiqi ekrana köçürülmür), lakin
    onu GÖRÜNƏN edir: aktorun öz sətri siyahıda `[siz]` qeydi ilə gəlir və
    kontroller onu seçim siyahısına salmır (bax `controllers/face_control.py`).
    """

    subject_changed = Signal(str)
    capture_requested = Signal(str)
    re_enroll_requested = Signal(str, str)
    retake_requested = Signal(str)
    refresh_requested = Signal()

    #: `ClassVar` — `Column` siyahısı nüsxələr arasında PAYLAŞILA bilər
    #: (heç bir nüsxə onu dəyişmir); bax `annual_leave.AnnualLeaveInboxScreen`.
    _FRAME_COLUMNS: ClassVar[list[Column]] = [
        Column("Kadr", 90, mono=True),
        Column("Nəticə", 150),
        Column("Keyfiyyət", 130, mono=True),
        Column("Səbəb"),
    ]

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)
        self._rows: list[dict[str, str]] = []
        self._mode = "ENROLL"
        self._camera_ready = False

        self.add(self._build_toolbar())
        self.add(self._build_subject_card())
        self.add(self._build_preview_card())
        self.add(self._build_frames_card())
        self.body().addStretch(1)

        # Başlanğıc vəziyyəti: siyahı hələ gəlməyib, düymələr işləmir.
        self._apply_mode()

    # ------------------------------- quruluş --------------------------------- #

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget()
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self._summary = muted_label("")
        layout.addWidget(self._summary)
        layout.addWidget(stretch())

        refresh = secondary_button("Yenilə")
        refresh.clicked.connect(self.refresh_requested)
        layout.addWidget(refresh)
        return toolbar

    def _build_subject_card(self) -> Card:
        card = Card(padding=20, spacing=12)
        card.add(title_label("Üz Qeydiyyatı", size=15))
        card.add(
            muted_label(
                "Qeydiyyat NƏZARƏTLİ prosesdir: işçi FİZİKİ olaraq yanınızda olmalıdır. "
                "Foto SAXLANMIR — yalnız riyazi təmsil şifrələnərək yazılır."
            )
        )
        card.add(Divider())

        selector = QWidget()
        selector_layout = QVBoxLayout(selector)
        selector_layout.setContentsMargins(0, 0, 0, 0)
        selector_layout.setSpacing(8)
        selector_layout.addWidget(field_label("İşçi"))

        self._subject = QComboBox()
        self._subject.setProperty("variant", "form")
        self._subject.currentIndexChanged.connect(self._on_subject_changed)
        selector_layout.addWidget(self._subject)
        card.add(selector)

        state_row = QWidget()
        state_layout = QHBoxLayout(state_row)
        state_layout.setContentsMargins(0, 0, 0, 0)
        state_layout.setSpacing(12)
        self._state_chip = Chip("Qeydiyyatsız", "danger")
        state_layout.addWidget(self._state_chip)
        self._enrolled_at = mono_label("")
        state_layout.addWidget(self._enrolled_at)
        state_layout.addWidget(stretch())
        card.add(state_row)

        # --- yenidən-qeydiyyat bloku (bənd 2) — YALNIZ həmin rejimdə görünür --
        self._re_enroll_box = QWidget()
        re_layout = QVBoxLayout(self._re_enroll_box)
        re_layout.setContentsMargins(0, 0, 0, 0)
        re_layout.setSpacing(8)
        self._archive_warning = body_label("", size=13)
        re_layout.addWidget(self._archive_warning)
        re_layout.addWidget(field_label("Yenidən qeydiyyatın səbəbi"))
        self._reason = QLineEdit()
        self._reason.setProperty("variant", "form")
        re_layout.addWidget(self._reason)
        card.add(self._re_enroll_box)

        return card

    def _build_preview_card(self) -> Card:
        """«Canlı önizləmə» — ŞƏKİL YOX, VƏZİYYƏT (bax modul başlığı)."""
        card = Card(padding=20, spacing=12)
        card.add(title_label("Kamera", size=15))

        self._camera_state = body_label("Kamera vəziyyəti oxunmayıb.", size=13)
        card.add(self._camera_state)

        self._progress = title_label("0/0 kadr", size=19)
        card.add(self._progress)

        self._progress_hint = muted_label(
            "Kadrlar yalnız yaddaşda emal olunur və heç bir yerə yazılmır."
        )
        card.add(self._progress_hint)
        card.add(Divider())

        self._result = body_label("", size=13)
        card.add(self._result)

        buttons = QWidget()
        button_layout = QHBoxLayout(buttons)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(12)
        button_layout.addWidget(stretch())

        self._retake = secondary_button("Yenidən Çək")
        self._retake.clicked.connect(self._on_retake)
        # RƏDD EDİLMİŞ cəhddən ƏVVƏL görünmür — `set_result()` onu açır.
        self._retake.setVisible(False)
        button_layout.addWidget(self._retake)

        self._capture = action_button("Çək")
        self._capture.clicked.connect(self._on_capture)
        button_layout.addWidget(self._capture)

        self._save = action_button("Yadda Saxla")
        self._save.clicked.connect(self._on_save)
        button_layout.addWidget(self._save)

        card.add(buttons)
        return card

    def _build_frames_card(self) -> Card:
        """Kadr-kadr nəticə — «uğursuz» əvəzinə SƏBƏB (bənd 1)."""
        card = Card(padding=20, spacing=12)
        card.add(title_label("Kadrların nəticəsi", size=15))
        card.add(
            muted_label(
                "Rədd edilən kadrın səbəbi göstərilir — işıqlandırma, bucaq və ya "
                "kamera problemi ayırd edilə bilsin."
            )
        )

        self._frames_host = QWidget()
        self._frames_layout = QVBoxLayout(self._frames_host)
        self._frames_layout.setContentsMargins(0, 0, 0, 0)
        self._frames_layout.setSpacing(0)
        card.add(self._frames_host)

        self._frames_empty = muted_label("Hələ kadr çəkilməyib.")
        card.add(self._frames_empty)
        return card

    # ------------------------------- doldurma -------------------------------- #

    def set_employees(self, rows: list[dict[str, str]]) -> None:
        """Qeydiyyat aparıla bilən işçilər.

        Args:
            rows: `id`, `name`, `store`, `state`, `enrolled_at` açarları olan
                sözlüklər. `state` — `NEW` / `ENROLLED` / `STALE`. Açarlar HƏM
                maket (`preview_screens._face_enrollment`), HƏM canlı yol
                (`controllers/face_control.py::_employee_row`) üçün EYNİDİR
                (CLAUDE.md §6).

        Boş siyahı NORMAL haldır (mağazada hələ işçi yoxdur) — `show_empty`
        göstərilir, `show_error` YOX.
        """
        self._rows = list(rows)

        self._subject.blockSignals(True)
        self._subject.clear()
        for row in self._rows:
            label = row.get("name", "")
            store = row.get("store", "")
            self._subject.addItem(f"{label} · {store}" if store else label, row.get("id", ""))
        self._subject.blockSignals(False)

        if not self._rows:
            self.show_empty(
                icon_name="user",
                title="Qeydiyyat üçün işçi yoxdur",
                message=(
                    "Üz qeydiyyatı üçün əvvəlcə «İstifadəçilər» ekranından işçi əlavə edin. "
                    "Öz hesabınız bu siyahıda görünmür — qeydiyyatı ikinci şəxs aparmalıdır."
                ),
            )
            self._summary.setText("")
            self._apply_mode()
            return

        self._summary.setText(f"{len(self._rows)} işçi")
        self._on_subject_changed(self._subject.currentIndex())
        self.show_content()

    def set_camera(self, camera: dict[str, str]) -> None:
        """Kameranın vəziyyəti + ROOT-dan gələn kadr sayı.

        Args:
            camera: `available` ("1"/"0"), `message`, `frame_count` açarları.
                Kadr sayı `FACE_ENROLLMENT_FRAME_COUNT`-dandır və ekranda
                HESABLANMIR — çağırandan gəlir (CLAUDE.md §5).
        """
        self._camera_ready = camera.get("available") == "1"
        self._camera_state.setText(camera.get("message", ""))
        self._camera_state.setStyleSheet(
            "" if self._camera_ready else f"color: {self.theme.color('--color-danger')};"
        )
        total = camera.get("frame_count", "0")
        self._progress.setText(f"0/{total} kadr")
        self._apply_mode()

    def set_result(self, result: dict[str, str]) -> None:
        """Son cəhdin nəticəsi.

        Args:
            result: `accepted` ("1"/"0"), `message`, `frames_total`,
                `frames_accepted` açarları. Mətn use case-dən gəlir
                (`FaceEnrollmentResult.message_az`) — ekran onu YENİDƏN
                yazmır, yalnız rəngləndirir.
        """
        accepted = result.get("accepted") == "1"
        self._result.setText(result.get("message", ""))
        token = "--color-success" if accepted else "--color-danger"
        self._result.setStyleSheet(f"color: {self.theme.color(token)};")
        self._progress.setText(
            f"{result.get('frames_accepted', '0')}/{result.get('frames_total', '0')} kadr"
        )
        # `[Yenidən Çək]` YALNIZ rədd edilmiş cəhddən sonra görünür — uğurdan
        # sonra göstərmək operatoru «bir də çəkim?» sualı ilə baş-başa qoyardı.
        self._retake.setVisible(not accepted)
        if accepted:
            self._reason.clear()

    def set_frames(self, rows: list[dict[str, str]]) -> None:
        """Kadr-kadr nəticə cədvəli.

        Args:
            rows: `index`, `accepted` ("1"/"0"), `quality`, `reason` açarları.
        """
        clear_layout(self._frames_layout)
        self._frames_empty.setVisible(not rows)
        if not rows:
            return

        table = DataTable(self._FRAME_COLUMNS, self.theme)
        for row in rows:
            accepted = row.get("accepted") == "1"
            table.add_row(
                [
                    row.get("index", ""),
                    Chip("Qəbul edildi", "success") if accepted else Chip("Rədd edildi", "danger"),
                    row.get("quality", ""),
                    row.get("reason", ""),
                ]
            )
        self._frames_layout.addWidget(table)

    def frames_layout(self) -> QVBoxLayout:
        """Kadr cədvəlinin qabı — testlər sətir sayını buradan oxuyur."""
        return self._frames_layout

    # ------------------------------- seçim ----------------------------------- #

    def selected_employee_id(self) -> str:
        data = self._subject.currentData()
        return str(data) if data else ""

    def mode(self) -> str:
        """`ENROLL` və ya `RE_ENROLL` — testlər və kontroller üçün."""
        return self._mode

    def reason_text(self) -> str:
        """Yenidən-qeydiyyat səbəbi — `[Yenidən Çək]` onu təkrar işlədir."""
        return self._reason.text().strip()

    def _on_subject_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._rows):
            self._mode = "ENROLL"
            self._apply_mode()
            return

        row = self._rows[index]
        state = row.get("state", "NEW")
        text, tone = ENROLLMENT_STATE_CHIPS.get(state, ENROLLMENT_STATE_CHIPS["NEW"])
        self._state_chip.setText(text)
        self._state_chip.set_tone(tone)

        # BAŞQA İŞÇİYƏ KEÇƏNDƏ ƏVVƏLKİ NƏTİCƏ QALMIR: «2 kadr qaranlıq idi»
        # mesajı yeni işçinin adının altında dayansaydı, operator onu həmin
        # işçiyə aid sayardı.
        self._result.setText("")
        self._retake.setVisible(False)

        enrolled_at = row.get("enrolled_at", "")
        self._enrolled_at.setText(
            f"Qeydiyyat tarixi: {enrolled_at}" if enrolled_at else "Qeydiyyat aparılmayıb"
        )
        self._archive_warning.setText(
            f"Köhnə vektor SİLİNMİR — «REPLACED» statusu ilə arxivlənir "
            f"(cari qeydiyyat: {enrolled_at or '—'}). Dəyişiklik audit jurnalına yazılır."
        )

        self._mode = "RE_ENROLL" if state in ("ENROLLED", "STALE") else "ENROLL"
        self._apply_mode()
        self.subject_changed.emit(row.get("id", ""))

    def _apply_mode(self) -> None:
        """Rejimə görə düymələri və səbəb sahəsini paylayır (bax modul başlığı)."""
        re_enroll = self._mode == "RE_ENROLL"
        has_subject = bool(self.selected_employee_id())
        self._re_enroll_box.setVisible(re_enroll)
        self._capture.setVisible(not re_enroll)
        self._save.setVisible(re_enroll)
        # Kamera əlçatmazdırsa düymə BASILA BİLMİR: use case onsuz da
        # `FaceCameraUnavailableError` atardı, lakin istifadəçiyə səbəbi
        # ƏVVƏLCƏDƏN demək onu boş-boşuna gözlətməkdən yaxşıdır.
        self._capture.setEnabled(self._camera_ready and has_subject)
        self._save.setEnabled(self._camera_ready and has_subject)
        self._retake.setEnabled(self._camera_ready and has_subject)

    # ------------------------------ əməliyyat -------------------------------- #

    def _on_capture(self) -> None:
        employee_id = self.selected_employee_id()
        if not employee_id:
            return
        self.capture_requested.emit(employee_id)

    def _on_save(self) -> None:
        employee_id = self.selected_employee_id()
        if not employee_id:
            return
        reason = self._reason.text().strip()
        if not reason:
            # Səbəb use case-də də MƏCBURİDİR (`FaceReEnrollmentUseCase.
            # re_enroll`), lakin boş sətri oraya göndərmək operatora domen
            # istisnası göstərmək demək olardı — sahə burada tutulur.
            self._result.setText("Yenidən qeydiyyat üçün səbəb yazılmalıdır.")
            self._result.setStyleSheet(f"color: {self.theme.color('--color-danger')};")
            return
        self.re_enroll_requested.emit(employee_id, reason)

    def _on_retake(self) -> None:
        employee_id = self.selected_employee_id()
        if not employee_id:
            return
        self.retake_requested.emit(employee_id)

    def set_busy(self, busy: bool) -> None:
        """Kamera/DB əməliyyatı gedərkən ÜÇ əməliyyat düyməsi BAĞLANIR.

        ──────────────────────────────────────────────────────────────────────
        QA-FULL FAZA 3 tapıntısı — ƏVVƏL BU METOD YOX İDİ
        ──────────────────────────────────────────────────────────────────────
        `[Çək]`/`[Yadda Saxla]`/`[Yenidən Çək]` əməliyyat gedərkən AKTİV
        qalırdı: sürətli ikiqat klik iki paralel `enroll()`/`re_enroll()`
        çağırışı yaradırdı (real kamerada iki ayrı kadr seriyası). Naxış
        `ErpServersScreen.set_busy` ilə EYNİDİR — deaktivlik GÖRÜNƏN qatdır,
        `controllers/face_control.py::FaceEnrollmentController._run`-dakı
        `BackgroundTask.is_running` isə klaviatura qısayolunu da tutur.

        `_apply_mode()`-un hesabladığı "kamera hazırdır + işçi seçilib" şərti
        BURADA TƏKRARLANIR (`not busy and ready`), çünki `set_busy(False)`
        işdən sonra düymələri düzgün vəziyyətə ÖZÜ qaytarmalıdır — uğursuz
        cəhddə (`_fail`) `_apply_mode()` YENİDƏN ÇAĞIRILMIR.

        MƏTN DƏYİŞMİR (digər `set_busy` naxışlarından FƏRQLİ): `[Çək]`
        operator üçün TANIŞ etiket olaraq qalır və `Qt`-nin ÖZÜ deaktiv
        düymədə `.click()`-i sükutla heç nə etmir (`QAbstractButton::click()`)
        — yəni qapı görünüş DƏYİŞMƏDƏN belə işləyir.
        """
        ready = self._camera_ready and bool(self.selected_employee_id())
        self._capture.setEnabled(not busy and ready)
        self._save.setEnabled(not busy and ready)
        self._retake.setEnabled(not busy and ready)


# --------------------------------------------------------------------------- #
# 14. İstisna idarəetməsi — YALNIZ Root/CEO
# --------------------------------------------------------------------------- #


class FaceExemptionScreen(Screen):
    """PIN-only istisnalarının idarəsi (bənd 14) — `can_manage_face_exemptions`.

    Signals:
        grant_requested: `[İstisna Ver]` — (`employee_id`, `reason`, `days`).
        revoke_requested: Sətrin `[Ləğv Et]` düyməsi (`exemption_id`).
        refresh_requested: `[Yenilə]`.

    ──────────────────────────────────────────────────────────────────────────
    `can_manage_employees` KİFAYƏT ETMİR — VƏ BU, EKRANDA DA GÖRÜNÜR
    ──────────────────────────────────────────────────────────────────────────
    İstisna üz qatını SÖNDÜRÜR, yəni özü bir aldatma yoluna çevrilə bilər.
    Flag `hardlock_level = 2` (`HardlockLevel.ROOT_CEO`) ilə elan olunub, yəni
    Root onu HR-səviyyəli admin-ə HƏVALƏ EDƏ BİLMİR. Menyu maddəsi həmin
    flag-lə qapılıdır (`shell/menu.py`) və flag-i olmayan istifadəçidə maddə
    RENDER OLUNMUR.

    ──────────────────────────────────────────────────────────────────────────
    KOMPENSASİYA EDİCİ NƏZARƏT MƏTNİ NİYƏ MƏCBURİDİR
    ──────────────────────────────────────────────────────────────────────────
    İstisna verən Root PIN-only-nin yaratdığı boşluğu ANLAMALIDIR: həmin
    işçinin HƏR giriş/qayıdışı avtomatik dual-control-a düşür. Bu, «bir az
    diqqətli ol» tövsiyəsi deyil, MƏCBURİ ikinci təsdiqdir
    (`FaceVerificationUseCase._dual_control_required`). Mətn olmasaydı, istisna
    «sadəcə üz yoxlamasını söndürmək» kimi oxunardı.
    """

    grant_requested = Signal(str, str, int)
    revoke_requested = Signal(str)
    refresh_requested = Signal()

    _COLUMNS: ClassVar[list[Column]] = [
        Column("İşçi"),
        Column("Səbəb"),
        Column("Bitmə tarixi", 150, mono=True),
        Column("Qalıb", 110, mono=True),
        Column("Verən", 170),
        Column("Əməliyyat", 140),
    ]

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)
        self._min_reason_length = 0

        self.add(self._build_warning())
        self.add(self._build_form())
        self.add(self._build_table())
        self.body().addStretch(1)

    # ------------------------------- quruluş --------------------------------- #

    def _build_warning(self) -> Card:
        card = Card(padding=16, spacing=8)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(Chip("Kompensasiya edici nəzarət", "warning"))
        layout.addWidget(stretch())
        card.add(row)
        card.add(
            body_label(
                "İstisnalı işçinin HƏR giriş və qayıdış təsdiqi avtomatik olaraq MƏCBURİ "
                "ikinci təsdiqə (dual-control) düşür. Bu, PIN-only rejiminin yaratdığı "
                "boşluğu əvəzləyir və söndürülə bilməz.",
                size=13,
            )
        )
        card.add(
            muted_label(
                "İstisna MÜVƏQQƏTİDİR: müddət bitdikdə avtomatik ləğv olunur və "
                "yenidən əsaslandırılmalıdır."
            )
        )
        return card

    def _build_form(self) -> Card:
        card = Card(padding=20, spacing=12)
        card.add(title_label("Yeni istisna", size=15))
        card.add(Divider())

        employee_box = QWidget()
        employee_layout = QVBoxLayout(employee_box)
        employee_layout.setContentsMargins(0, 0, 0, 0)
        employee_layout.setSpacing(8)
        employee_layout.addWidget(field_label("İşçi"))
        self._employee = QComboBox()
        self._employee.setProperty("variant", "form")
        employee_layout.addWidget(self._employee)
        card.add(employee_box)

        reason_box = QWidget()
        reason_layout = QVBoxLayout(reason_box)
        reason_layout.setContentsMargins(0, 0, 0, 0)
        reason_layout.setSpacing(8)
        reason_layout.addWidget(field_label("Səbəb"))
        self._reason = QLineEdit()
        self._reason.setProperty("variant", "form")
        self._reason.setPlaceholderText("Tibbi və ya fiziki səbəbi yazın")
        reason_layout.addWidget(self._reason)
        card.add(reason_box)

        days_box = QWidget()
        days_layout = QVBoxLayout(days_box)
        days_layout.setContentsMargins(0, 0, 0, 0)
        days_layout.setSpacing(8)
        days_layout.addWidget(field_label("Müddət"))
        self._days = QSpinBox()
        self._days.setProperty("variant", "form")
        # Diapazon SET EDİLƏNƏ QƏDƏR 1 gündür: tavan ROOT parametridir
        # (`FACE_EXEMPTION_MAX_DAYS`) və `set_max_days()` ilə gəlir — ekranda
        # sabit ədəd yazsaydıq, Root-un dəyişikliyi burada görünməzdi.
        self._days.setRange(1, 1)
        self._days.setSuffix(" gün")
        self._days.setFixedWidth(160)
        days_layout.addWidget(self._days)
        card.add(days_box)

        self._hint = muted_label("")
        card.add(self._hint)

        buttons = QWidget()
        button_layout = QHBoxLayout(buttons)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(12)
        button_layout.addWidget(stretch())
        grant = action_button("İstisna Ver")
        grant.clicked.connect(self._on_grant)
        button_layout.addWidget(grant)
        card.add(buttons)
        return card

    def _build_table(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)
        header_layout.addWidget(title_label("Aktiv istisnalar", size=15))
        self._summary = muted_label("")
        header_layout.addWidget(self._summary)
        header_layout.addWidget(stretch())
        refresh = secondary_button("Yenilə")
        refresh.clicked.connect(self.refresh_requested)
        header_layout.addWidget(refresh)
        layout.addWidget(header)

        self._table_host = QWidget()
        self._table_layout = QVBoxLayout(self._table_host)
        self._table_layout.setContentsMargins(0, 0, 0, 0)
        self._table_layout.setSpacing(0)
        layout.addWidget(self._table_host)

        self._table_empty = muted_label(
            "Aktiv istisna yoxdur — bütün işçilər üz təsdiqindən keçir."
        )
        layout.addWidget(self._table_empty)
        return host

    # ------------------------------- doldurma -------------------------------- #

    def set_employees(self, rows: list[dict[str, str]]) -> None:
        """İstisna verilə bilən işçilər — `id`, `name` açarları."""
        self._employee.clear()
        for row in rows:
            self._employee.addItem(row.get("name", ""), row.get("id", ""))

    def set_limits(self, limits: dict[str, str]) -> None:
        """ROOT tavanı + sxem məhdudiyyəti.

        Args:
            limits: `max_days` (`FACE_EXEMPTION_MAX_DAYS`) və
                `min_reason_length` (`face_control_exemptions.reason` `CHECK`-i)
                açarları. HƏR İKİSİ ÇAĞIRANDAN gəlir — ekran nə bazanı, nə
                `DEFAULT_LIMITS`-i tanıyır (CLAUDE.md §6).
        """
        max_days = _positive_int(limits.get("max_days"), fallback=1)
        self._days.setRange(1, max_days)
        self._days.setValue(min(self._days.value() or 1, max_days))
        self._min_reason_length = _positive_int(limits.get("min_reason_length"), fallback=0)
        self._hint.setText(
            f"Ən çox {max_days} gün. Səbəb ən azı {self._min_reason_length} simvol olmalıdır — "
            f"sənədləşməmiş istisna auditdə müdafiə oluna bilmir."
        )

    def set_exemptions(self, rows: list[dict[str, str]]) -> None:
        """Aktiv istisnalar.

        Args:
            rows: `id`, `employee`, `reason`, `expires_at`, `days_remaining`,
                `granted_by` açarları. Maket və canlı yolda EYNİDİR
                (CLAUDE.md §6).
        """
        clear_layout(self._table_layout)
        self._table_empty.setVisible(not rows)
        self._summary.setText(f"{len(rows)} aktiv istisna" if rows else "")
        if not rows:
            self.show_content()
            return

        table = DataTable(self._COLUMNS, self.theme)
        for row in rows:
            table.add_row(self._build_cells(row))
        self._table_layout.addWidget(table)
        self.show_content()

    def table_layout(self) -> QVBoxLayout:
        """Cədvəl qabı — testlər sətir sayını buradan oxuyur."""
        return self._table_layout

    def _build_cells(self, row: dict[str, str]) -> list[QWidget | str]:
        actions = QWidget()
        layout = QHBoxLayout(actions)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        key = row.get("id", "")
        revoke = secondary_button("Ləğv Et")
        revoke.setProperty("variant", "danger")
        revoke.clicked.connect(lambda *_, k=key: self.revoke_requested.emit(k))
        layout.addWidget(revoke)

        return [
            row.get("employee", ""),
            row.get("reason", ""),
            row.get("expires_at", ""),
            row.get("days_remaining", ""),
            row.get("granted_by", ""),
            actions,
        ]

    # ------------------------------ əməliyyat -------------------------------- #

    def _on_grant(self) -> None:
        employee_id = self._employee.currentData()
        reason = self._reason.text().strip()
        if not employee_id:
            self._hint.setText("İşçi seçilməlidir.")
            return
        if len(reason) < self._min_reason_length:
            # Qayda bazanın `CHECK`-idir və use case-də də var; burada yalnız
            # yararsız sorğunun YOLA ÇIXMASI bloklanır (bax `annual_leave`
            # dialoqundakı eyni sərhəd).
            self._hint.setText(
                f"Səbəb ən azı {self._min_reason_length} simvol olmalıdır — hazırda {len(reason)}."
            )
            return
        self.grant_requested.emit(str(employee_id), reason, int(self._days.value()))
        self._reason.clear()


# --------------------------------------------------------------------------- #
# 3–6, 12. Kiosk doğrulama overlay-i
# --------------------------------------------------------------------------- #


class FaceVerificationOverlay(QDialog):
    """PIN-dən SONRAKI üz təsdiqi addımı — kiosk üzərində modal.

    Signals:
        retry_requested: `[Yenidən Cəhd Et]` — YALNIZ `RETRY` nəticəsində.
        dismissed: `[Bağla]`.

    ──────────────────────────────────────────────────────────────────────────
    `PinPadScreen` DƏYİŞMİR — BU, ONDAN SONRAKI ADDIMIDIR
    ──────────────────────────────────────────────────────────────────────────
    Klaviatura, nöqtələr, lockout mesajı və `submitted` siqnalı OLDUĞU KİMİ
    qalır. Üz təsdiqi PIN-in içinə yazılmır: `FaceVerificationUseCase.verify`
    PIN uğurlu olduqdan SONRA, STEP A/1/2 əməliyyatından ƏVVƏL işləyir
    (`controllers/kiosk.py`) və bu overlay onun NƏTİCƏSİNİ göstərir.

    ──────────────────────────────────────────────────────────────────────────
    HƏRƏKƏTİ EKRAN SEÇMİR (bənd 6)
    ──────────────────────────────────────────────────────────────────────────
    «Gözlərinizi qırpın» / «Başınızı yavaşca sağa çevirin» / «Gülümsəyin»
    mətnləri BURADA SEÇİLMİR: hərəkət serverdə `secrets.choice` ilə seçilir və
    ekrana `FaceGateDecision.liveness_action.prompt_az` kimi GƏLİR. Ekranda
    seçim olsaydı, təsadüfilik kiosk maşınına köçər və video-təkrar hücumu
    üçün proqnozlaşdırıla bilən olardı.

    Ona görə burada nə `random`, nə hərəkət siyahısı var — yalnız gələn mətnin
    göstərilməsi.

    ──────────────────────────────────────────────────────────────────────────
    KAMERA NASAZLIĞI SƏSSİZ KEÇİD YARATMIR (bənd 5)
    ──────────────────────────────────────────────────────────────────────────
    `MANUAL_APPROVAL_REQUIRED` nəticəsi «heç nə olmadı» kimi göstərilmir: işçi
    NƏ BAŞ VERDİYİNİ (kamera işləmir / qeydiyyat yoxdur) və NƏ ETMƏLİ olduğunu
    (HR_Admin/CEO manual təsdiq verəcək) açıq mətnlə oxuyur.
    """

    retry_requested = Signal()
    dismissed = Signal()

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setObjectName("PinScreen")  # AAA `--color-pin-*` cütü, yeni rəng YOX
        self.setWindowTitle("Üz Təsdiqi")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(0)

        self._title = plain_label("Üz təsdiqi")
        title_font = self._title.font()
        title_font.setPixelSize(OVERLAY_TITLE_SIZE)
        title_font.setWeight(QFont.Weight.Bold)
        self._title.setFont(title_font)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title)

        layout.addSpacing(18)

        self._gesture = plain_label(" ")
        gesture_font = self._gesture.font()
        gesture_font.setPixelSize(OVERLAY_PROMPT_SIZE)
        gesture_font.setWeight(QFont.Weight.DemiBold)
        self._gesture.setFont(gesture_font)
        self._gesture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._gesture.setWordWrap(True)
        layout.addWidget(self._gesture)

        layout.addSpacing(14)

        self._message = plain_label(" ")
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message.setWordWrap(True)
        message_font = self._message.font()
        message_font.setPixelSize(16)
        self._message.setFont(message_font)
        layout.addWidget(self._message)

        layout.addSpacing(10)

        self._confidence = plain_label(" ")
        self._confidence.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._confidence)

        layout.addSpacing(26)

        buttons = QWidget()
        button_layout = QHBoxLayout(buttons)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(metrics.KEYPAD_SPACING)
        button_layout.addStretch(1)

        self._retry = self._touch_button("Yenidən Cəhd Et")
        self._retry.clicked.connect(self._on_retry)
        button_layout.addWidget(self._retry)

        self._close = self._touch_button("Bağla")
        self._close.clicked.connect(self._on_close)
        button_layout.addWidget(self._close)
        button_layout.addStretch(1)
        layout.addWidget(buttons)

        self.show_checking()

    def _touch_button(self, text: str) -> QPushButton:
        """Kiosk düyməsi — `variant="keypad"` (88px, AAA cüt, mövcud QSS)."""
        button = QPushButton(text)
        button.setProperty("variant", "keypad")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setMinimumSize(metrics.KEYPAD_TEXT_BUTTON_WIDTH + 60, metrics.KEYPAD_BUTTON_SIZE)
        font = button.font()
        font.setPixelSize(16)
        button.setFont(font)
        return button

    # ------------------------------- vəziyyət -------------------------------- #

    def show_checking(self) -> None:
        """Doğrulama gedir — nəticə hələ yoxdur."""
        self._title.setText("Üz təsdiqi aparılır")
        self._title.setStyleSheet("")
        self._gesture.setText("Kameraya baxın")
        self._message.setText("Bir neçə saniyə çəkə bilər.")
        self._message.setStyleSheet("")
        self._confidence.setText(" ")
        self._retry.setVisible(False)
        self._close.setVisible(False)

    def set_result(self, result: dict[str, str]) -> None:
        """Doğrulamanın nəticəsi.

        Args:
            result: `outcome` (`FaceGateOutcome` dəyəri), `message`, `gesture`,
                `confidence`, `retry` ("1"/"0") açarları. Maket
                (`preview_screens`) və canlı yol
                (`controllers/kiosk.py::face_result`) EYNİ açarları işlədir
                (CLAUDE.md §6).
        """
        self._apply_outcome(result.get("outcome", ""))
        self._message.setText(result.get("message", ""))
        gesture = result.get("gesture", "")
        self._gesture.setText(gesture or "Kameraya baxın")
        confidence = result.get("confidence", "")
        self._confidence.setText(f"Oxşarlıq: {confidence}" if confidence else " ")
        self._retry.setVisible(result.get("retry") == "1")
        self._close.setVisible(True)

    def _apply_outcome(self, outcome: str) -> None:
        """Nəticə açarını başlığa və rəngə çevirir.

        NAMƏLUM AÇAR SÜKUTLA KEÇMİR: yeni `FaceGateOutcome` dəyəri əlavə
        olunub bu cədvələ yazılmasa, işçi boş başlıq görərdi. Ehtiyat mətn
        («Nəticə oxunmadı») isə açıq şəkildə qüsuru bildirir.
        """
        title, token = OUTCOME_TITLES.get(outcome, FALLBACK_OUTCOME_TITLE)
        self._title.setText(title)
        self._title.setStyleSheet(f"color: {self._theme.color(token)};")
        self._message.setStyleSheet(f"color: {self._theme.color(token)};")

    def title_text(self) -> str:
        """Başlıq mətni — testlər üçün."""
        return self._title.text()

    def gesture_text(self) -> str:
        """Göstərilən liveness göstərişi — testlər üçün."""
        return self._gesture.text()

    def message_text(self) -> str:
        return self._message.text()

    def retry_visible(self) -> bool:
        return bool(self._retry.isVisibleTo(self))

    def _on_retry(self) -> None:
        self.retry_requested.emit()

    def _on_close(self) -> None:
        self.dismissed.emit()
        self.accept()


def _positive_int(raw: str | None, *, fallback: int) -> int:
    """Sözlükdən gələn ədəd — yararsız mətn ekranı çökdürmür.

    Setter-lərə düz mətn gəlir (maket və canlı yol EYNİ sözlük formatındadır),
    ona görə çevirmə burada bir dəfə edilir. `BehaviorAnomalyRule._parse_float`
    ilə eyni fəlsəfə: yararsız dəyər sükutla ehtiyata düşür, ekran isə
    açılmağa davam edir.
    """
    if raw is None:
        return fallback
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return fallback
    return value if value > 0 else fallback


class FaceSetupRequiredScreen(Screen):
    """İLK GİRİŞ — üz qeydiyyatı tələb olunur (nəzarətli proses).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ ADMİN ŞİFRƏSİ SORUŞULUR
    ──────────────────────────────────────────────────────────────────────────
    `facecontrol.md` bənd 1: işçi ÖZ üzünü özü qeydiyyata SALA BİLMƏZ. Səbəb
    `FaceEnrollmentUseCase.assert_may_enroll`-da yazılıb — nəzarətsiz
    qeydiyyatda işçi İSTƏNİLƏN üzü öz hesabına bağlaya bilər (məsələn
    dostunun), sonra həmin adam onun adına giriş edər və üz qatının bütün
    mənası itər.

    Ona görə bu ekran işçinin qarşısında açılır, lakin çəkilişi YANINDAKI
    admin öz hesabı ilə təsdiqləyir. Aktor həmin admindir, subyekt isə işçi —
    yəni `actor.id != subject_id` şərti təbii şəkildə ödənir.

    ──────────────────────────────────────────────────────────────────────────
    «SONRA» DÜYMƏSİ NİYƏ VAR — QAPI OLMAMASI ÜÇÜN DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Kamerası olmayan mağazada bu ekran MƏCBURİ olsaydı, işçi heç vaxt giriş
    edə bilməzdi — yəni üz qatı iş dayandıran nasazlığa çevrilərdi. «Sonra»
    həmin dalanı açır və seçim İZSİZ QALMIR: hər keçid jurnala yazılır və
    ekran NÖVBƏTİ girişdə yenidən çıxır. Daimi istisna isə ayrıca yoldadır
    (`face_exemptions`, yalnız Root/CEO).

    Signals:
        enroll_requested: (admin istifadəçi adı, admin şifrəsi).
        skipped: «Sonra» — giriş davam edir, tələb qalır.
    """

    enroll_requested = Signal(str, str)
    skipped = Signal()

    def __init__(
        self,
        theme: ThemeManager,
        *,
        employee_name: str = "",
        supervised: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        """`supervised=False` — İlk Quraşdırma Sihirbazı (SEC-025).

        Həmin halda admin sahələri GİZLƏNİR: aktor elə istifadəçinin özüdür və
        şifrəni bir neçə saniyə əvvəl yazıb. Onu təkrar soruşmaq nə əlavə
        yoxlama verər, nə də təhlükəsizlik — yalnız qeydiyyatı uzadardı.
        """
        super().__init__(theme, parent=parent)
        self._supervised = supervised

        # ÖLÇÜLƏR GİRİŞ KARTINDAN GÖTÜRÜLÜB (`AdminLoginScreen`: 40/20).
        # Bu ekran giriş axınının davamıdır — istifadəçi onu şifrə kartından
        # DƏRHAL sonra görür. Öz ölçüsünü seçsəydik, iki ardıcıl ekran arasında
        # kartın gövdəsi «tullanardı» və dizayn səpələnməsi bir dəyər artardı
        # (`scripts/check_symmetry.py` tavanı).
        card = Card(padding=40, spacing=20)
        card.add(title_label("Üz qeydiyyatı tələb olunur", size=22))
        self._subject = body_label("", size=15)
        card.add(self._subject)
        card.add(Divider())
        card.add(
            muted_label(
                (
                    "Bu, hesabınızla İLK girişdir. Üz qeydiyyatı nəzarətli "
                    "prosesdir: onu özünüz apara bilməzsiniz — yanınızdakı admin "
                    "öz hesabı ilə təsdiqləməlidir. Şəkil SAXLANILMIR, yalnız "
                    "riyazi təmsil yazılır."
                )
                if supervised
                else (
                    "Sistemdə hələ başqa admin yoxdur, ona görə qeydiyyatı özünüz "
                    "aparırsınız (SEC-025). Bu, YALNIZ ilk hesab üçün mümkündür — "
                    "ikinci admin yarandıqdan sonra hər qeydiyyat təsdiq tələb edir. "
                    "Şəkil SAXLANILMIR, yalnız riyazi təmsil yazılır."
                ),
                size=13,
            )
        )

        self._username = FormField("Admin istifadəçi adı")
        self._username.setVisible(supervised)
        card.add(self._username)
        self._password = FormField("Admin şifrəsi", password=True)
        self._password.setVisible(supervised)
        card.add(self._password)

        self._error = body_label("", size=13)
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        self._error.setStyleSheet(
            f"background-color: {theme.color('--color-danger-bg')};"
            f"color: {theme.color('--color-danger')};"
            "border-radius: 12px; padding: 12px 14px;"
        )
        card.add(self._error)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)

        later = secondary_button("Sonra")
        later.clicked.connect(self.skipped)
        buttons_layout.addWidget(later)
        buttons_layout.addWidget(stretch())

        self._enroll = action_button("Təsdiqlə və Çək")
        self._enroll.clicked.connect(self._on_enroll)
        buttons_layout.addWidget(self._enroll)
        card.add(buttons)

        self.add(card)
        self.body().addStretch(1)
        self.set_employee_name(employee_name)

    # -------------------------------- API ----------------------------------- #

    def set_employee_name(self, name: str) -> None:
        """Kimin üzünün çəkiləcəyi AÇIQ yazılır.

        Admin öz şifrəsini yazır, yəni ekranda «kimin adına» sualı qalmamalıdır
        — səhv işçinin üzünü çəkmək sükutla düzəldilə bilməyən qeyddir
        (yenidən-qeydiyyat AYRI, səbəb tələb edən prosesdir).
        """
        self._subject.setText(f"İşçi: {name}" if name else "")

    def set_busy(self, busy: bool) -> None:
        self._enroll.setEnabled(not busy)
        self._enroll.setText("Çəkilir…" if busy else "Təsdiqlə və Çək")

    def set_error(self, message: str) -> None:
        """Sahə səviyyəsində xəta — `Screen.show_error()` DEYİL.

        Baza sinfin `show_error()`-u bütün məzmunu XƏTA VƏZİYYƏTİ ilə əvəz
        edir (ekran açıla bilmədi halı). Burada isə ekran işləyir, sadəcə
        cəhd rədd olunub: forma yerində qalmalı, yazılanlar itməməlidir.
        Ad da fərqlidir ki, ikisi səhvən qarışmasın (`AdminLoginScreen` ilə
        eyni adlandırma).
        """
        self._error.setText(message)
        self._error.setVisible(True)

    def clear_error(self) -> None:
        self._error.setVisible(False)

    def _on_enroll(self) -> None:
        self.clear_error()
        if not self._supervised:
            # Bootstrap: aktor onsuz da məlumdur, kimlik soruşulmur.
            self.enroll_requested.emit("", "")
            return
        username = self._username.text().strip()
        password = self._password.text()
        if not username or not password:
            self.set_error("Admin istifadəçi adı və şifrəsi tələb olunur.")
            return
        self.enroll_requested.emit(username, password)


__all__ = [
    "ENROLLMENT_STATE_CHIPS",
    "FALLBACK_OUTCOME_TITLE",
    "OUTCOME_TITLES",
    "OVERLAY_PROMPT_SIZE",
    "OVERLAY_TITLE_SIZE",
    "FaceEnrollmentScreen",
    "FaceExemptionScreen",
    "FaceSetupRequiredScreen",
    "FaceVerificationOverlay",
]
