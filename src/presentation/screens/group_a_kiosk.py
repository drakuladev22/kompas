"""Qrup A — kiosk ekranları: PIN klaviaturası və İşçi Ana Ekranı — Faza 4.2.

Maket: "KompasOS - Qrup A.dc.html", ekranlar 04–05.

Bu iki ekran mağazadakı PAYLAŞILAN kiosk PC-sində işləyir: tam ekran,
çərçivəsiz, toxunma-ilk. Ona görə:

    * düymələr böyükdür (88px — bölmə 9-un 44px minimumundan xeyli yuxarı),
    * PIN ekranı ümumi palitradan DEYİL, AAA kontrastlı `--color-pin-*`
      cütündən istifadə edir (mağaza işığı dəyişkəndir, tez-tez günəş altında),
    * heç bir naviqasiya yoxdur — işçi yalnız öz axınını görür.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.presentation.theme.manager import set_surface_color
from src.presentation.widgets import icons, metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import (
    Card,
    Chip,
    Divider,
    body_label,
    mono_label,
    muted_label,
    plain_label,
    section_label,
    stretch,
    title_label,
)
from src.presentation.widgets.worker_status import WorkerStatus

if TYPE_CHECKING:
    from PySide6.QtGui import QKeyEvent, QPaintEvent

    from src.presentation.theme.manager import ThemeManager
    from src.presentation.widgets.primitives import ChipTone

#: PIN uzunluğu (bölmə 9 — 4 rəqəm).
PIN_LENGTH: Final = 4

#: PIN siyasətinin ekran tərəfi — HƏR İKİSİ FALLBACK-dır, HƏQİQİ MƏNBƏ
#: `system_limits` (`PIN_MAX_FAILED_ATTEMPTS`, `PIN_LOCKOUT_MINUTES`;
#: `schema.sql` §24 seed edir, `authentication.PinHandshakeUseCase` oxuyur).
#:
#: NİYƏ MAKETDƏKİ 3/5 SAXLANILMADI: maket "3 cəhd → 5 dəqiqə" yazırdı,
#: sistemin FAKTİKİ siyasəti isə həmişə 5 cəhd → 15 dəqiqə olub (bölmə 2 və
#: `DEFAULT_LIMITS`). Yəni ekrandakı ədədlər bloklamanın həqiqi həddi ilə
#: ZİDD idi — istifadəçiyə yalan deyən mətn. İndi ədəd tək mənbədən gəlir.
#:
#: NİYƏ EKRAN ÖZÜ OXUMUR: ekranlar yalnız `theme` alır (CLAUDE.md §6) və bazanı
#: TANIMIR; canlı dəyəri çağıran ötürür (`show_lockout(minutes=...)`).
FALLBACK_PIN_MAX_ATTEMPTS: Final = int(DEFAULT_LIMITS[SystemLimitKey.PIN_MAX_FAILED_ATTEMPTS])
FALLBACK_PIN_LOCKOUT_MINUTES: Final = int(DEFAULT_LIMITS[SystemLimitKey.PIN_LOCKOUT_MINUTES])


# --------------------------------------------------------------------------- #
# 04 — PIN Klaviaturası
# --------------------------------------------------------------------------- #


class PinDots(QWidget):
    """Doldurulmuş/boş dairə göstəriciləri — neçə rəqəm daxil edilib.

    Rəqəmin özü GÖSTƏRİLMİR: kiosk mağaza zalındadır və arxadan baxan bir
    nəfər PIN-i oxuya bilərdi.
    """

    def __init__(
        self,
        *,
        color: str,
        length: int = PIN_LENGTH,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._length = length
        self._filled = 0
        self._error = False
        self.setFixedSize(
            length * metrics.PIN_DOT_SIZE + (length - 1) * 22,
            metrics.PIN_DOT_SIZE,
        )

    def set_filled(self, count: int) -> None:
        self._filled = max(0, min(self._length, count))
        self.update()

    def set_error(self, error: bool) -> None:
        self._error = error
        self.update()

    def set_colors(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt adlandırması
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        size = metrics.PIN_DOT_SIZE
        for index in range(self._length):
            x = index * (size + 22)
            rect = (x, 0, size, size)
            if index < self._filled:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self._color)
            else:
                pen = painter.pen()
                pen.setColor(self._color)
                pen.setWidth(2)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(*rect)


class PinPadScreen(QWidget):
    """Tam ekran PIN girişi.

    Signals:
        submitted: 4 rəqəm tamamlandı (`str`).
        face_login_requested: «Üzlə daxil ol» düyməsi.
    """

    submitted = Signal(str)
    #: «Üzlə daxil ol» — PIN-ə ALTERNATİV giriş yolu.
    face_login_requested = Signal()

    #: Klaviatura düzülüşü — maketdəki 3×4 şəbəkə.
    _LAYOUT: Final = (
        ("1", "2", "3"),
        ("4", "5", "6"),
        ("7", "8", "9"),
        ("Təmizlə", "0", "Sil"),
    )

    def __init__(
        self,
        theme: ThemeManager,
        *,
        store_name: str,
        terminal_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._entered = ""
        self._locked = False
        #: Üz doğrulaması gedirmi (`set_busy`). Bloklamadan AYRIDIR.
        self._busy = False

        self.setObjectName("PinScreen")
        text_color = theme.color("--color-pin-text")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 48, 0, 48)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # ------------------------------ başlıq ------------------------------ #
        header = QVBoxLayout()
        header.setSpacing(4)
        header.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # `self._store` (`store` yerinə) — DEEP-GAP U5 test dəstəyi: mağaza
        # adı artıq sabit deyil (`app.py::_kiosk_store_name`), testlər onu
        # `_message`/`_clock` ilə EYNİ naxışla oxuya bilməlidir.
        self._store = title_label(store_name, size=19)
        self._store.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self._store)

        terminal = muted_label(terminal_name)
        terminal.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(terminal)

        self._clock = mono_label("", muted=True)
        self._clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self._clock)
        layout.addLayout(header)

        layout.addSpacing(46)

        prompt = plain_label("PIN kodunuzu daxil edin")
        prompt_font = prompt.font()
        prompt_font.setPixelSize(22)
        prompt_font.setWeight(QFont.Weight.DemiBold)
        prompt.setFont(prompt_font)
        prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(prompt, alignment=Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(26)

        self._dots = PinDots(color=text_color)
        layout.addWidget(self._dots, alignment=Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(14)

        # Xəta sətri HƏMİŞƏ yer tutur (görünməz olsa da) — əks halda mesaj
        # çıxanda bütün klaviatura aşağı sıçrayardı və barmaq səhv düyməyə
        # düşərdi.
        self._message = plain_label(" ")
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_font = self._message.font()
        message_font.setPixelSize(14)
        self._message.setFont(message_font)
        self._message.setFixedHeight(20)
        layout.addWidget(self._message, alignment=Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(26)
        layout.addWidget(self._build_keypad(), alignment=Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(20)
        layout.addWidget(self._build_face_button(), alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)

        footer = muted_label("Problem yaşayırsınızsa mağaza rəhbərinizə müraciət edin.")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(footer, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Klaviatura girişi üçün fokus EKRANIN ÖZÜNDƏDİR: klaviatura
        # düymələri `NoFocus`-dur (basılanda halqa çıxmasın deyə), yəni
        # `keyPressEvent` onlara getmir və ekran onu özü tutmalıdır.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _build_face_button(self) -> QWidget:
        """«Üzlə daxil ol» — PIN-in YANINDA, ONUN ƏVƏZİ DEYİL.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ AŞAĞIDA VƏ NİYƏ İKİNCİ DƏRƏCƏLİ GÖRÜNÜŞDƏ
        ──────────────────────────────────────────────────────────────────────
        Telefon üz-tanıması eyni yerdədir və istifadəçilər bu vərdişi kioska
        gətirir: PIN əsas yoldur, üz isə sürətli alternativdir. Onu əsas düymə
        kimi vurğulasaydıq, kamera işləmədiyi anda (mağazada tez-tez olur)
        ekranın ƏN GÖRÜNƏN elementi işləməyən bir düymə olardı.

        Kamera yoxdursa düymə GİZLƏNİR, sönük qalmır: sönük düymə «niyə
        işləmir?» sualı yaradır və işçi onu təkrar-təkrar basır.
        """
        button = secondary_button("Üzlə daxil ol")
        button.setIcon(icons.icon("face_scan", self._theme.color("--color-pin-text")))
        button.setIconSize(QSize(icons.DEFAULT_SIZE, icons.DEFAULT_SIZE))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumHeight(48)
        button.clicked.connect(self.face_login_requested)
        button.setVisible(False)
        self._face_button = button
        return button

    def set_face_login_available(self, available: bool) -> None:
        """Kamera və üz modulu hazırdırsa düyməni göstərir."""
        self._face_button.setVisible(available)

    def face_button(self) -> QPushButton:
        """Üz girişi düyməsi — kontroller/testlər üçün."""
        return self._face_button

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt adlandırması
        """Fiziki klaviatura və NUMPAD ilə PIN daxil etmə.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ LAZIMDIR
        ──────────────────────────────────────────────────────────────────────
        Kiosk PC-lərinin bir hissəsində toxunma ekranı YOXDUR — orada işçi
        klaviatura ilə işləyir. Ekranda rəqəm düymələri olduğu üçün "onsuz da
        girmək olar" təəssüratı yaranır, halbuki siçansız/toxunmasız terminalda
        PIN-i daxil etməyin heç bir yolu yox idi.

        `text()` YOX, `key()` İŞLƏDİLİR: `Qt.Key_0…Key_9` həm əsas sıranı, həm
        NUMPAD-ı əhatə edir və klaviatura düzülüşündən (AZ/EN/RU) asılı deyil —
        `text()` isə düzülüşə görə dəyişə bilər.
        """
        if self._locked:
            super().keyPressEvent(event)
            return

        key = event.key()
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            self._on_key(str(key - int(Qt.Key.Key_0)))
            event.accept()
            return
        if key == Qt.Key.Key_Backspace:
            self._on_key("Sil")
            event.accept()
            return
        if key in {Qt.Key.Key_Escape, Qt.Key.Key_Delete}:
            self._on_key("Təmizlə")
            event.accept()
            return
        super().keyPressEvent(event)

    def _build_keypad(self) -> QWidget:
        keypad = QWidget()
        grid = QGridLayout(keypad)
        grid.setSpacing(metrics.KEYPAD_SPACING)
        # Düymələrə İSTİNAD saxlanılır: `set_busy` onları müvəqqəti söndürür.
        # `findChildren` ilə axtarsaydıq, üz düyməsi də siyahıya düşərdi və o,
        # ayrıca idarə olunur.
        self._keys: list[QPushButton] = []

        for row_index, row in enumerate(self._LAYOUT):
            for column_index, key in enumerate(row):
                button = QPushButton(key)
                button.setProperty("variant", "keypad")
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                if key.isdigit():
                    button.setFixedSize(metrics.KEYPAD_BUTTON_SIZE, metrics.KEYPAD_BUTTON_SIZE)
                else:
                    # Mətn düymələri ("Təmizlə"/"Sil") rəqəmlərdən ENLİDİR —
                    # kvadrat ölçüdə etiket kəsilirdi ("əmizlə" görünürdü).
                    button.setFixedSize(
                        metrics.KEYPAD_TEXT_BUTTON_WIDTH, metrics.KEYPAD_BUTTON_SIZE
                    )
                    font = button.font()
                    font.setPixelSize(14)
                    button.setFont(font)
                button.clicked.connect(lambda _=False, value=key: self._on_key(value))
                self._keys.append(button)
                grid.addWidget(button, row_index, column_index)

        return keypad

    # ------------------------------- giriş ----------------------------------- #

    def _on_key(self, key: str) -> None:
        if self._locked:
            return

        if key == "Təmizlə":
            self._entered = ""
        elif key == "Sil":
            self._entered = self._entered[:-1]
        elif key.isdigit() and len(self._entered) < PIN_LENGTH:
            self._entered += key
            self.clear_message()

        self._dots.set_filled(len(self._entered))

        if len(self._entered) == PIN_LENGTH:
            self.submitted.emit(self._entered)

    def set_clock(self, text: str) -> None:
        """Saat və tarix — "09:42 · 12 Avqust 2026"."""
        self._clock.setText(text)

    def reset(self) -> None:
        """Girişi təmizləyir (uğurlu təsdiqdən və ya xətadan sonra)."""
        self._entered = ""
        self._dots.set_filled(0)
        self._dots.set_error(False)

    def show_attempt_error(self, remaining: int) -> None:
        """Yanlış PIN — neçə cəhd qaldığını göstərir.

        ──────────────────────────────────────────────────────────────────────
        CANLI AXIN BUNU ÇAĞIRMIR — SƏBƏB STRUKTURDUR
        ──────────────────────────────────────────────────────────────────────
        Kiosk PIN-i ANONİMDİR: `PinHandshakeUseCase.authenticate` uyğun gəlməyən
        PIN üçün `AuthenticationError` atır və HANSI işçinin cəhd etdiyini
        BİLDİRMİR (mağazada 235 nəfər ola bilər; "kimin PIN-i yanlışdır"
        sualının cavabı sızma olardı). "Qalan cəhd sayı" isə işçi-başına
        sayğacdır (`employees.pin_failed_attempts`) — terminal onu bilmədən
        göstərə bilməz.

        Ona görə canlı yol `show_message(GENERIC_PIN_FAILURE)` işlədir
        (`app.start_kiosk::on_pin`). Bu metod maket/e2e yoludur və `remaining`
        DƏYƏRİNİ ÇAĞIRANDAN alır — ekranda ədəd BƏRKİDİLMİR.
        """
        self._message.setText(f"PIN yanlışdır — {remaining} cəhd qaldı")
        self._message.setStyleSheet(f"color: {self._theme.color('--color-danger')};")
        self._dots.set_error(True)
        self.reset()

    def show_message(self, text: str) -> None:
        """Sərbəst xəbərdarlıq mətni (PIN yanlışdır, konfiqurasiya yoxdur, ...).

        `show_attempt_error`-dan fərqi: orada qalan cəhd sayı GÖSTƏRİLİR və
        bu, yalnız PIN səhvində mənalıdır. Sistem xətası halında "3 cəhd
        qaldı" yazmaq işçini yanıldardı — problem onun PIN-ində deyil.
        """
        self._message.setText(text)
        self._message.setStyleSheet(f"color: {self._theme.color('--color-danger')};")
        self._dots.set_error(True)
        self.reset()

    def show_lockout(self, minutes: int = FALLBACK_PIN_LOCKOUT_MINUTES) -> None:
        """Terminal bloklandı — klaviatura söndürülür.

        ──────────────────────────────────────────────────────────────────────
        CANLI AXIN BUNU DA ÇAĞIRMIR — VƏ BU, QƏSDƏNDİR
        ──────────────────────────────────────────────────────────────────────
        Bloklama İŞÇİ-BAŞINADIR (`employees.pin_locked_until`), terminal isə
        PAYLAŞILANdır: bir işçinin bloklanmasına görə klaviaturanı söndürsək,
        həmin mağazanın BÜTÜN növbəsi 15 dəqiqə işə başlaya bilməzdi — yəni
        bir nəfərin səhvi mağaza miqyaslı dayanmaya çevrilərdi. Canlı yol
        `AccountLockedError`-u `show_message()` ilə göstərir: bloklanan işçi
        səbəbi görür, qalanlar isə işləməyə davam edir.

        Metod maket/e2e yolu üçün saxlanılır; `minutes` defoltu ROOT açarından
        gəlir ki, gələcək bir çağıran onu ötürməyi unutsa belə ekrandakı ədəd
        faktiki siyasətlə ZİDD olmasın.
        """
        self._locked = True
        self._message.setText(
            f"Terminal {minutes} dəqiqə bloklandı. Mağaza rəhbərinizə müraciət edin."
        )
        self._message.setStyleSheet(f"color: {self._theme.color('--color-danger')};")
        self.reset()

    def set_busy(self, busy: bool, *, message: str = "Üz yoxlanılır…") -> None:
        """Uzun sürən üz doğrulaması müddətində ekranı «məşğul» göstərir.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ LAZIMDIR (UX-1)
        ──────────────────────────────────────────────────────────────────────
        «Üzlə daxil ol» kamera çəkilişi + 1:N tanıma + 1:1 doğrulama deməkdir
        və bu, saniyələr çəkir. Əvvəl heç bir göstərici yox idi: işçi düyməni
        basırdı, ekran donmuş görünürdü və o, adətən düyməni TƏKRAR basırdı —
        yəni ikinci çəkiliş növbəyə düşürdü. Panel girişində eyni yol ARTIQ
        düzgün qurulmuşdu (`LoginScreen.set_busy`), kiosk yolu unudulmuşdu.

        `_locked`-dan AYRIDIR: bloklama siyasət nəticəsidir və mesajı özü
        yazır, bu isə müvəqqəti gözləmə vəziyyətidir.
        """
        self._busy = busy
        self._face_button.setEnabled(not busy)
        for button in self._keys:
            button.setEnabled(not busy)
        if busy:
            self._message.setText(message)
            self._message.setStyleSheet(f"color: {self._theme.color('--color-text-muted')};")
        else:
            self.clear_message()

    @property
    def is_busy(self) -> bool:
        return self._busy

    def clear_lockout(self) -> None:
        self._locked = False
        self.clear_message()

    def clear_message(self) -> None:
        self._message.setText(" ")
        self._message.setStyleSheet("")
        self._dots.set_error(False)

    @property
    def is_locked(self) -> bool:
        return self._locked


# --------------------------------------------------------------------------- #
# 05 — İşçi Ana Ekranı
# --------------------------------------------------------------------------- #


class EmployeeHomeScreen(QWidget):
    """PIN-dən sonra açılan işçi ekranı — status, tapşırıqlar, xal, cərimələr.

    Signals:
        action_requested: Statusa uyğun TƏK düymə basıldı (`WorkerStatus`).
        photo_change_requested: "Şəkli Dəyiş".
        logout_requested: "Çıxış".
        tasks_requested / rewards_requested / appeal_requested: kart keçidləri.
        open_shift_claim_requested: `[Bu Növbəni Götür]` (#16 — elan id-si).
        annual_leave_request_requested: `[Məzuniyyət Sorğusu]` (#28).

    ──────────────────────────────────────────────────────────────────────────
    "AÇIQ NÖVBƏLƏR" KARTI NİYƏ STATUS DÜYMƏSİNDƏN AYRIDIR
    ──────────────────────────────────────────────────────────────────────────
    Bölmə 3-ün "statusa uyğun TƏK düymə" qaydası İŞ GÜNÜ AXINININA aiddir
    (`[İşə Başladım]` → `[İcazə İstəyirəm]` → `[Mən Qayıtdım]`) — orada
    məqsəd işçini bir addıma yönəltməkdir. Açıq növbə isə həmin axının
    hissəsi DEYİL: o, GƏLƏCƏK bir günə aiddir və işçinin bugünkü statusundan
    asılı deyil. Onu status düyməsinə qatsaydıq, "Mağazadayam" vəziyyətində
    işçi ya icazə istəyə, ya növbə götürə bilərdi — ikisi bir düyməyə
    sığmaz.

    EYNİ ƏSASLANDIRMA "İLLİK MƏZUNİYYƏT" KARTINA DA AİDDİR (#28) və orada bir
    qat da güclüdür: statusdakı `[İcazə İstəyirəm]` STEP1 gündaxili icazədir
    (DƏQİQƏ, `leave_verification.py`), məzuniyyət isə İLLİK haqqdır (GÜN).
    İkisini eyni düyməyə yığmaq iki fərqli mexanizmi bir-birinə qarışdırardı —
    işçi "icazə" sözünü basıb hansı sistemin işə düşdüyünü bilməzdi.
    """

    action_requested = Signal(object)
    photo_change_requested = Signal()
    logout_requested = Signal()
    tasks_requested = Signal()
    rewards_requested = Signal()
    appeal_requested = Signal()
    open_shift_claim_requested = Signal(str)
    annual_leave_request_requested = Signal()

    def __init__(
        self,
        theme: ThemeManager,
        *,
        full_name: str,
        position_name: str,
        store_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._status = WorkerStatus.VERIFIED
        set_surface_color(self, theme.color("--color-content-bg"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 32, 48, 32)
        layout.setSpacing(24)

        layout.addWidget(self._build_header(full_name, position_name, store_name))
        layout.addWidget(self._build_status_card())
        # FASİLƏ KARTI STATUS KARTININ DƏRHAL ALTINDADIR (nahar.md GUI, bənd 2):
        # seçim `[İcazə İstəyirəm]` düyməsindən ƏVVƏL edilir və ikisi arasında
        # başqa kart olsaydı, işçi düyməni basandan sonra "nə seçmişdim?"
        # sualı ilə qalardı. Açıq Növbələr/İllik Məzuniyyət kartlarından
        # FƏRQLİ olaraq bu, günün axınının bir hissəsidir.
        layout.addWidget(self._build_break_card())
        layout.addWidget(self._build_cards_row())
        # #19 Elan (Broadcast, kompasos11.md Faza 8) — kartların ALTINDA, TAM
        # ENLİ: elan sayı dəyişkəndir (0-dan bir neçəyədək) və mətn uzun ola
        # bilər, dörd-sütunlu kartın darlığında kəsilərdi. Genişlənən stretch
        # BURAYA keçib (əvvəl `_build_cards_row`-dadır idi) ki, boş qalan
        # şaquli sahəni bu kart tutsun.
        layout.addWidget(self._build_announcements_card(), 1)

    # ------------------------------- başlıq ---------------------------------- #

    def _build_header(self, full_name: str, position_name: str, store_name: str) -> QWidget:
        from src.presentation.widgets.primitives import Avatar  # noqa: PLC0415

        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self._avatar = Avatar(
            full_name,
            background=self._theme.color("--color-neutral-bg"),
            foreground=self._theme.color("--color-text-primary"),
            size=72,
        )
        layout.addWidget(self._avatar)

        text_box = QWidget()
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)

        greeting = title_label(f"Salam, {full_name}", size=26)
        text_layout.addWidget(greeting)
        text_layout.addWidget(muted_label(f"{position_name} · {store_name}", size=13))
        layout.addWidget(text_box)

        layout.addWidget(stretch())

        photo_button = secondary_button("Şəkli Dəyiş")
        photo_button.clicked.connect(self.photo_change_requested)
        layout.addWidget(photo_button)

        logout_button = secondary_button("Çıxış")
        logout_button.clicked.connect(self.logout_requested)
        layout.addWidget(logout_button)

        return header

    # ---------------------------- status kartı -------------------------------- #

    def _build_status_card(self) -> QWidget:
        card = Card(padding=metrics.CARD_PADDING + 4, spacing=12)

        card.add(section_label("Cari vəziyyət"))

        status_row = QWidget()
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(16)

        from src.presentation.widgets.primitives import StatusDot  # noqa: PLC0415

        self._status_dot = StatusDot(self._theme.color(self._status.color_token), size=14)
        status_layout.addWidget(self._status_dot)

        self._status_label = title_label(self._status.label_az, size=metrics.FONT_KIOSK_TITLE)
        status_layout.addWidget(self._status_label)
        status_layout.addWidget(stretch())

        # Statusa uyğun TƏK düymə (spesifikasiya) — istifadəçi nə edəcəyini
        # seçmir, sistem onu bir addıma yönəldir.
        self._action = action_button(self._status.action_az)
        self._action.setMinimumHeight(56)
        self._action.setMaximumHeight(56)
        action_font = self._action.font()
        action_font.setPixelSize(17)
        self._action.setFont(action_font)
        self._action.clicked.connect(lambda: self.action_requested.emit(self._status))
        status_layout.addWidget(self._action)

        card.add(status_row)
        self._status_hint = body_label(self._status.hint_az, size=13)
        self._status_hint.setStyleSheet(f"color: {self._theme.color('--color-text-secondary')};")
        card.add(self._status_hint)
        return card

    def set_status(self, status: WorkerStatus, *, hint: str = "") -> None:
        """Statusu dəyişir — nöqtə rəngi, ad, izah və düymə birlikdə yenilənir."""
        self._status = status
        self._status_dot.set_color(self._theme.color(status.color_token))
        self._status_label.setText(status.label_az)
        self._status_hint.setText(hint or status.hint_az)
        self._action.setText(status.action_az)
        # "Gözlənilir…" vəziyyətində düymə var, amma basıla bilməz — işçi
        # operatorun təsdiqini gözləyir və təkrar sorğu göndərməməlidir.
        self._action.setEnabled(status.is_actionable)

    # ---------------------------- fasilə seçimi -------------------------------- #

    def _build_break_card(self) -> QWidget:
        """Nahar/Çay seçimi + gündəlik göstərici (nahar.md GUI, bənd 2).

        ──────────────────────────────────────────────────────────────────────
        «ÜMUMİ İCAZƏ» NİYƏ SİYAHIDA QALIR VƏ NİYƏ DEFOLTDUR
        ──────────────────────────────────────────────────────────────────────
        STEP1 bu günə qədər `leave_type_id=None` göndərirdi. Defolt seçimi
        Nahar etsəydik, MÖVCUD davranış sükutla dəyişərdi: bank işinə çıxan
        işçinin sorğusu nahar sayılar, sayğac səhv artar və BR-001 güzəşti
        gözlənilmədən tətbiq olunardı. «Ümumi icazə» = bugünkü davranışın
        eynisi; Nahar/Çay isə İŞÇİNİN AÇIQ seçimidir.

        ──────────────────────────────────────────────────────────────────────
        KART BOŞ SİYAHIDA GİZLƏNİR
        ──────────────────────────────────────────────────────────────────────
        Fasilə növləri hələ seed edilməyibsə (köhnə baza, miqrasiya tətbiq
        olunmayıb) kart ümumiyyətlə görünmür — ekran bugünkü halında qalır.
        Boş açılan siyahı «sistem xarabdır» kimi oxunardı.
        """
        card = Card(padding=metrics.CARD_PADDING, spacing=12)
        card.add(section_label("Fasilə növü"))

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)

        self._break_combo = QComboBox()
        self._break_combo.setProperty("variant", "form")
        self._break_combo.setMinimumWidth(280)
        self._break_combo.currentIndexChanged.connect(self._on_break_changed)
        row_layout.addWidget(self._break_combo)

        self._break_warning = Chip("", "warning")
        self._break_warning.setVisible(False)
        row_layout.addWidget(self._break_warning)
        row_layout.addWidget(stretch())
        card.add(row)

        self._break_detail = body_label("", size=13)
        self._break_detail.setStyleSheet(f"color: {self._theme.color('--color-text-secondary')};")
        card.add(self._break_detail)

        #: Açılan siyahının sırası ilə eyni sıralı seçim məlumatı.
        #: `QComboBox.itemData` əvəzinə ayrıca siyahı saxlanılır, çünki
        #: `currentIndexChanged` siyahı təmizlənərkən də işə düşür və
        #: `itemData(-1)` `None` qaytarardı — sətir isə həmişə lazımdır.
        self._break_options: list[dict[str, str]] = []
        self._break_card = card
        card.setVisible(False)
        return card

    def set_break_options(self, options: list[dict[str, str]]) -> None:
        """`options`: `leave_type_id`, `label`, `detail`, `warning` açarları.

        SEÇİM QORUNUR: siyahı hər STEP1-dən sonra yenidən doldurulur (sayğac
        dəyişib) və işçinin seçimi sıfırlansaydı, ardıcıl iki çay fasiləsi
        üçün seçimi hər dəfə təkrarlamalı olardı.
        """
        previous = self.selected_break_leave_type_id()

        # «Ümumi icazə» HƏMİŞƏ birincidir və siyahıdan gəlmir — o, fasilə
        # deyil, fasilənin YOXLUĞUdur (bax `_build_break_card` başlığı).
        self._break_options = [
            {"leave_type_id": "", "label": "Ümumi icazə", "detail": "", "warning": ""},
            *options,
        ]
        self._break_card.setVisible(bool(options))

        self._break_combo.blockSignals(True)
        self._break_combo.clear()
        self._break_combo.addItems([option["label"] for option in self._break_options])
        index = next(
            (
                position
                for position, option in enumerate(self._break_options)
                if option["leave_type_id"] == previous
            ),
            0,
        )
        self._break_combo.setCurrentIndex(index)
        self._break_combo.blockSignals(False)
        self._apply_break_detail(index)

    def selected_break_leave_type_id(self) -> str:
        """Seçilmiş fasilənin `leave_type_id`-si; «Ümumi icazə» üçün boş sətir."""
        index = self._break_combo.currentIndex()
        if 0 <= index < len(self._break_options):
            return self._break_options[index]["leave_type_id"]
        return ""

    def _on_break_changed(self, index: int) -> None:
        self._apply_break_detail(index)

    def _apply_break_detail(self, index: int) -> None:
        option = self._break_options[index] if 0 <= index < len(self._break_options) else None
        detail = option["detail"] if option else ""
        warning = option["warning"] if option else ""
        self._break_detail.setText(
            detail or "Fasilə seçmədən davam etsəniz sorğu ümumi icazə kimi qeydə alınır."
        )
        self._break_warning.setText(warning)
        self._break_warning.setVisible(bool(warning))

    # ------------------------------- kartlar ---------------------------------- #

    def _build_cards_row(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(metrics.CARD_SPACING)

        layout.addWidget(self._build_tasks_card(), 1)
        layout.addWidget(self._build_points_card(), 1)
        layout.addWidget(self._build_fines_card(), 1)
        layout.addWidget(self._build_open_shifts_card(), 1)
        # #28 İllik Məzuniyyət — kartlar sırasının SONUNDA: soldan sağa
        # "bugün → bu ay → gələcək" ritmi qorunur (tapşırıq/xal/cərimə cari
        # dövrə, açıq növbə yaxın günlərə, məzuniyyət isə bütün ilə aiddir).
        layout.addWidget(self._build_annual_leave_card(), 1)
        return container

    def _build_tasks_card(self) -> Card:
        card = Card(padding=metrics.CARD_PADDING, spacing=12)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.addWidget(title_label("Açıq Tapşırıqlarım", size=metrics.FONT_CARD_TITLE))
        head_layout.addWidget(stretch())
        self._tasks_count = Chip("0", "info")
        head_layout.addWidget(self._tasks_count)
        card.add(head)
        card.add(Divider())

        self._tasks_body = QVBoxLayout()
        self._tasks_body.setSpacing(8)
        holder = QWidget()
        holder.setLayout(self._tasks_body)
        card.add(holder)

        card.body().addStretch(1)
        link = secondary_button("Hamısına bax →")
        link.clicked.connect(self.tasks_requested)
        card.add(link)
        return card

    def set_tasks(self, tasks: list[str]) -> None:
        """Açıq tapşırıqları göstərir."""
        clear_layout(self._tasks_body)

        self._tasks_count.setText(str(len(tasks)))
        for task in tasks:
            self._tasks_body.addWidget(body_label(task, size=13))

    def _build_points_card(self) -> Card:
        card = Card(padding=metrics.CARD_PADDING, spacing=12)
        card.add(title_label("Xal Balansım", size=metrics.FONT_CARD_TITLE))
        card.add(Divider())

        self._points_value = title_label("0", size=32)
        card.add(self._points_value)

        self._points_delta = muted_label("")
        card.add(self._points_delta)

        self._points_hint = body_label("", size=13)
        card.add(self._points_hint)

        card.body().addStretch(1)
        link = secondary_button("Mükafat kataloqu →")
        link.clicked.connect(self.rewards_requested)
        card.add(link)
        return card

    def set_points(self, balance: int, *, monthly_delta: int, to_next_reward: int) -> None:
        # Rəqəm boşluqla ayrılır (1 240) — maketdəki format.
        self._points_value.setText(f"{balance:,}".replace(",", " "))
        sign = "+" if monthly_delta >= 0 else ""
        self._points_delta.setText(f"{sign}{monthly_delta} bu ay")
        self._points_hint.setText(
            f"Növbəti mükafata {to_next_reward} xal qalıb."
            if to_next_reward > 0
            else "Mükafat üçün kifayət qədər xalınız var."
        )

    def _build_fines_card(self) -> Card:
        card = Card(padding=metrics.CARD_PADDING, spacing=12)
        card.add(title_label("Cərimələrim", size=metrics.FONT_CARD_TITLE))
        card.add(Divider())

        self._fines_summary = title_label("—", size=19)
        card.add(self._fines_summary)

        self._fines_detail = body_label("", size=13)
        card.add(self._fines_detail)

        self._fines_deadline = muted_label("")
        card.add(self._fines_deadline)

        card.body().addStretch(1)
        self._appeal_button = secondary_button("Etiraz Et")
        self._appeal_button.clicked.connect(self.appeal_requested)
        card.add(self._appeal_button)
        return card

    def set_fines(
        self,
        *,
        count: int,
        total_text: str,
        latest: str = "",
        appeal_days_left: int | None = None,
    ) -> None:
        self._fines_summary.setText(
            f"{count} bu ay · {total_text}" if count else "Bu ay cərimə yoxdur"
        )
        self._fines_detail.setText(latest)
        self._fines_detail.setVisible(bool(latest))

        if appeal_days_left is None:
            self._fines_deadline.setVisible(False)
            self._appeal_button.setVisible(False)
            return

        self._fines_deadline.setText(f"Etiraz müddəti: {appeal_days_left} gün qalıb")
        self._fines_deadline.setVisible(True)
        self._appeal_button.setVisible(appeal_days_left > 0)

    # --------------------------- açıq növbələr (#16) -------------------------- #

    def _build_open_shifts_card(self) -> Card:
        card = Card(padding=metrics.CARD_PADDING, spacing=12)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.addWidget(title_label("Açıq Növbələr", size=metrics.FONT_CARD_TITLE))
        head_layout.addWidget(stretch())
        self._open_shift_count = Chip("0", "info")
        head_layout.addWidget(self._open_shift_count)
        card.add(head)
        card.add(Divider())

        self._open_shift_body = QVBoxLayout()
        self._open_shift_body.setSpacing(12)
        holder = QWidget()
        holder.setLayout(self._open_shift_body)
        card.add(holder)

        self._open_shift_hint = body_label(
            "Hazırda sizin üçün açıq növbə yoxdur.",
            size=13,
        )
        card.add(self._open_shift_hint)

        card.body().addStretch(1)
        return card

    def set_open_shifts(self, shifts: list[dict[str, str]]) -> None:
        """Açıq növbə elanlarını göstərir (#16).

        Args:
            shifts: `id`, `date`, `work_mode` açarları olan sözlüklər. Açarlar
                maket və canlı yolda EYNİDİR (CLAUDE.md §6).

        Hər sətrin ÖZ düyməsi var: tək bir "götür" düyməsi olsaydı, işçi
        hansı növbəni götürdüyünü seçə bilməzdi.
        """
        clear_layout(self._open_shift_body)
        self._open_shift_count.setText(str(len(shifts)))
        self._open_shift_hint.setVisible(not shifts)

        for shift in shifts:
            self._open_shift_body.addWidget(self._build_open_shift_row(shift))

    def _build_open_shift_row(self, shift: dict[str, str]) -> QWidget:
        row = QWidget()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(body_label(shift["date"], size=13))
        layout.addWidget(muted_label(shift["work_mode"], size=12))

        posting_id = shift["id"]
        take = action_button("Bu Növbəni Götür")
        take.setMinimumHeight(44)  # bölmə 9 — toxunma hədəfinin minimumu
        take.clicked.connect(
            lambda _=False, key=posting_id: self.open_shift_claim_requested.emit(key)
        )
        layout.addWidget(take)
        return row

    def set_open_shift_message(self, message: str) -> None:
        """Tutma cəhdinin nəticəsi — YARIŞI UDUZAN İŞÇİ BUNU GÖRÜR (#16).

        Uduzan sükutla qalmamalıdır: düymə basıldı, siyahı yeniləndi və növbə
        yoxa çıxdı — izahsız bu, "sistem işləmir" kimi qavranılardı. Mətn
        kontrollerdən gəlir (`error.user_message`), ekran onu YENİDƏN
        yazmır — bir mesajın iki mənbəyi olmamalıdır.
        """
        self._open_shift_hint.setText(message or "Hazırda sizin üçün açıq növbə yoxdur.")
        self._open_shift_hint.setVisible(True)

    # ------------------------ illik məzuniyyət (#28) -------------------------- #

    def _build_annual_leave_card(self) -> Card:
        """ "İllik Məzuniyyət" kartı — #28 (kompas1.md Faza 4).

        Struktur "Xal Balansım" kartının ikizidir (böyük rəqəm + izah + tək
        düymə), çünki hər ikisi İŞÇİNİN ÖZ BALANSIDIR və hər ikisi səlahiyyət
        TƏLƏB ETMİR (`AnnualLeaveUseCase.my_balance` / `SalesPointsUseCase.
        balance_for`). Öz haqqını görmək üçün flag istəmək işçini öz
        məlumatından kəsərdi (`menu.py` başlığındakı self-service qaydası).
        """
        card = Card(padding=metrics.CARD_PADDING, spacing=12)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.addWidget(title_label("İllik Məzuniyyət", size=metrics.FONT_CARD_TITLE))
        head_layout.addWidget(stretch())
        self._annual_leave_year = mono_label("", muted=True, size=12)
        head_layout.addWidget(self._annual_leave_year)
        card.add(head)
        card.add(Divider())

        # "14/21" — `available_days`/`total_days`; mətn EKRANDA qurulur, use
        # case yalnız rəqəmləri verir (bax `AnnualLeaveBalanceView` başlığı).
        self._annual_leave_value = title_label("—", size=32)
        card.add(self._annual_leave_value)

        self._annual_leave_caption = muted_label("gün qalıb")
        card.add(self._annual_leave_caption)

        # KÖÇÜRMƏ SƏTRİ HƏMİŞƏ GÖRÜNÜR (bax `set_annual_leave_balance`).
        #
        # TON NİŞANDADIR, MƏTNDƏ DEYİL. `Chip` rəng cütləri (`--color-warning`
        # / `--color-warning-bg`) `scripts/check_contrast.py`-də AA NORMAL mətn
        # həddi ilə ölçülür; eyni rəngi 12px mətn kimi kart fonuna yazsaydıq,
        # tünd temada `--color-danger`/`--color-bg-surface` cütü 4.33:1-ə
        # düşərdi — yəni ən vacib xəbərdarlıq ən pis oxunan sətir olardı.
        self._annual_leave_chip = Chip("", "neutral")
        self._annual_leave_chip.setVisible(False)
        card.add(self._annual_leave_chip)

        self._annual_leave_carryover = body_label("", size=12)
        self._annual_leave_carryover.setStyleSheet(
            f"color: {self._theme.color('--color-text-muted')};"
        )
        card.add(self._annual_leave_carryover)

        card.body().addStretch(1)

        self._annual_leave_message = body_label("", size=12)
        self._annual_leave_message.setVisible(False)
        card.add(self._annual_leave_message)

        request = action_button("Məzuniyyət Sorğusu")
        request.setMinimumHeight(44)  # bölmə 9 — toxunma hədəfinin minimumu
        request.clicked.connect(self.annual_leave_request_requested)
        card.add(request)
        return card

    def set_annual_leave_balance(self, balance: dict[str, str]) -> None:
        """Balans kartını doldurur (#28).

        Args:
            balance: `year`, `available`, `total`, `carried_over`,
                `carryover_deadline`, `carryover_expired` (`"1"`/`"0"`)
                açarları olan sözlük. Açarlar maket (`preview_screens`) və
                canlı yolda (`controllers/annual_leave.py::_to_balance_row`)
                EYNİDİR (CLAUDE.md §6). BOŞ sözlük normal haldır — balans
                qeydi olmayan işçi ekranı ÇÖKDÜRMÜR, "—" görür.

        ──────────────────────────────────────────────────────────────────────
        KÖÇÜRMƏ SON TARİXİ NİYƏ HƏMİŞƏ YAZILIR
        ──────────────────────────────────────────────────────────────────────
        "İstifadə et ya itir" qaydası (`ANNUAL_LEAVE_CARRYOVER_DEADLINE_*`)
        işçinin PULUNU yandırır: keçən ildən köçürülən gün son tarixdən sonra
        balansdan silinir. Bunu bilməyən işçi günü itirir və itkini yalnız
        FAKT olandan sonra görür. Ona görə sətir üç vəziyyətdə də göstərilir:

          * köçürülmüş gün VAR, vaxt keçməyib → `warning` nişanı, gün sayı və
            son tarix birlikdə;
          * köçürülmüş gün VAR, vaxt KEÇİB → `danger` nişanı: rəqəm hələ
            balansda görünə bilər (gecəlik iş növbəti icrada silir), lakin
            işçi ona ARTIQ arxalanmamalıdır;
          * köçürülmüş gün YOX → nişan gizlənir, LAKİN son tarix solğun
            sətirdə qalır, çünki qaydanın ÖZÜ gələn il üçün planlaşdırmaya
            təsir edir və işçi onu ƏVVƏLCƏDƏN bilməlidir.
        """
        year = balance.get("year", "")
        available = balance.get("available", "")
        total = balance.get("total", "")

        self._annual_leave_year.setText(year)
        if available and total:
            self._annual_leave_value.setText(f"{available}/{total}")
            self._annual_leave_caption.setText("gün qalıb")
        else:
            # Balans sətri hələ yoxdur (yeni işçi, oxu xətası) — kart boş
            # qalır, lakin düymə İŞLƏK olur: sorğu göndərmək balansı yaradır.
            self._annual_leave_value.setText("—")
            self._annual_leave_caption.setText("Balans məlumatı yoxdur")

        chip_text, tone = self._carryover_chip(balance)
        self._annual_leave_chip.setText(chip_text)
        self._annual_leave_chip.set_tone(tone)
        self._annual_leave_chip.setVisible(bool(chip_text))
        self._annual_leave_carryover.setText(self._carryover_text(balance))

    def _carryover_chip(self, balance: dict[str, str]) -> tuple[str, ChipTone]:
        carried = balance.get("carried_over", "0")
        if not balance.get("carryover_deadline") or not self._has_carryover(carried):
            return "", "neutral"
        if balance.get("carryover_expired") == "1":
            return "Köçürmə müddəti bitib", "danger"
        return f"{carried} gün köçürülüb", "warning"

    def _carryover_text(self, balance: dict[str, str]) -> str:
        deadline = balance.get("carryover_deadline", "")
        carried = balance.get("carried_over", "0")
        expired = balance.get("carryover_expired") == "1"

        if not deadline:
            return ""
        if self._has_carryover(carried) and expired:
            return f"Köçürülən {carried} günün müddəti bitib ({deadline}) — həmin günlər yanır."
        if self._has_carryover(carried):
            return f"Keçən ildən {carried} gün köçürülüb — {deadline} tarixinədək istifadə edin."
        return f"Köçürülən gün yoxdur. Köçürmə son tarixi: {deadline}."

    @staticmethod
    def _has_carryover(carried: str) -> bool:
        """ "0", "0.0", "0.00" və boş sətir — hamısı "köçürmə yoxdur" deməkdir.

        Rəqəm `Decimal`-dan sətrə çevrilir və format ROOT parametrindən asılı
        olaraq dəyişə bilər; `!= "0"` müqayisəsi "0.00" halında YALANÇI
        xəbərdarlıq verərdi.
        """
        try:
            return float(carried) > 0
        except (TypeError, ValueError):
            return False

    def set_annual_leave_message(self, message: str) -> None:
        """Sorğunun nəticəsi — kioskda İSTİSNA EKRANA ÇIXMIR (#28).

        `set_open_shift_message` ilə eyni qərar: kiosk PAYLAŞILAN cihazdır və
        orada modal xəta pəncərəsi bütün mağazanı bloklaya bilər. Mətn
        kontrollerdən gəlir (`error.user_message`), ekran onu YENİDƏN yazmır.
        """
        self._annual_leave_message.setText(message)
        self._annual_leave_message.setVisible(bool(message))

    # -------------------------------- elanlar (#19) ---------------------------- #

    def _build_announcements_card(self) -> Card:
        """ "Elanlar" kartı — #19 (kompasos11.md Faza 8).

        BİR-TƏRƏFLİDİR: bu kartda "Cavab Yaz" və ya oxşar düymə YOXDUR və
        ƏLAVƏ EDİLMİR — dəstək çatından (`SupportChatWidget`) fərqli olaraq
        elan yalnız OXUNUR (modul başlığındakı "Açıq Növbələr" kartının
        struktur ikizidir, lakin BURADA heç bir `[...]_requested` siqnalı
        yoxdur, çünki işçinin bu kartda edə biləcəyi HEÇ BİR əməliyyat yoxdur).
        """
        card = Card(padding=metrics.CARD_PADDING, spacing=12)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.addWidget(title_label("Elanlar", size=metrics.FONT_CARD_TITLE))
        head_layout.addWidget(stretch())
        self._announcement_count = Chip("0", "info")
        head_layout.addWidget(self._announcement_count)
        card.add(head)
        card.add(Divider())

        self._announcement_body = QVBoxLayout()
        self._announcement_body.setSpacing(12)
        holder = QWidget()
        holder.setLayout(self._announcement_body)
        card.add(holder)

        self._announcement_hint = body_label("Hazırda aktiv elan yoxdur.", size=13)
        card.add(self._announcement_hint)

        card.body().addStretch(1)
        return card

    def set_announcements(self, announcements: list[dict[str, str]]) -> None:
        """Aktiv elanları göstərir (#19).

        Args:
            announcements: `title`, `message`, `scope_text`, `date` açarları
                olan sözlüklər — ən yeni elan ƏVVƏLDƏ. Açarlar maket
                (`preview_screens`) və canlı yolda (`controllers/
                announcements.py`) EYNİDİR (CLAUDE.md §6).
        """
        clear_layout(self._announcement_body)
        self._announcement_count.setText(str(len(announcements)))
        self._announcement_hint.setVisible(not announcements)

        for item in announcements:
            self._announcement_body.addWidget(self._build_announcement_row(item))

    def _build_announcement_row(self, item: dict[str, str]) -> QWidget:
        row = QWidget()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(8)
        head_layout.addWidget(body_label(item.get("title", ""), size=13))
        head_layout.addWidget(stretch())
        scope_text = item.get("scope_text", "")
        if scope_text:
            head_layout.addWidget(mono_label(scope_text, muted=True, size=11))
        layout.addWidget(head)

        # `body_label` (`muted_label` DEYİL): elan mətni sərbəst uzunluqdadır
        # və `muted_label` sətir sarğısı (word wrap) TƏTBİQ ETMİR — uzun elan
        # kartın kənarından kəsilib itərdi.
        message = body_label(item.get("message", ""), size=12)
        message.setStyleSheet(f"color: {self._theme.color('--color-text-secondary')};")
        layout.addWidget(message)
        date_text = item.get("date", "")
        if date_text:
            layout.addWidget(mono_label(date_text, muted=True, size=11))

        return row

    @property
    def status(self) -> WorkerStatus:
        return self._status

    @property
    def theme(self) -> ThemeManager:
        """Tema — dialoq quran kontroller üçün (#28).

        `Screen.theme` ilə EYNİ müqavilə: kontroller `AnnualLeaveRequestDialog`
        yaradarkən temanı ekrandan alır. Kiosk ekranı `Screen`-dən törəmir
        (vəziyyət keçidi və kənar boşluqlar ona lazım deyil), ona görə xassə
        burada ayrıca elan olunur — kontrollerə ikinci bir tema mənbəyi
        ötürsəydik, tema dəyişəndə dialoq köhnə palitrada açılardı.
        """
        return self._theme

    # ------------------------------- test üçün -------------------------------- #
    # `LiveClock.text`-in EYNİ naxışı (`widgets/live_clock.py`): kartların
    # DAXİLİ etiketlərinə birbaşa girmək əvəzinə, testlər bu xassələri oxuyur
    # — DEEP-GAP U5 (üç kartın canlı doldurulması) buna görə yazıldı.

    @property
    def tasks_count_text(self) -> str:
        """«Açıq Tapşırıqlarım» kartındakı say."""
        return self._tasks_count.text()

    @property
    def points_balance_text(self) -> str:
        """«Xal Balansım» kartındakı rəqəm."""
        return self._points_value.text()

    @property
    def fines_summary_text(self) -> str:
        """«Cərimələrim» kartındakı qısa mətn."""
        return self._fines_summary.text()

    @property
    def fines_deadline_text(self) -> str:
        """«Etiraz müddəti: N gün qalıb» sətri (boşdursa görünmür)."""
        return self._fines_deadline.text()


__all__ = [
    "FALLBACK_PIN_LOCKOUT_MINUTES",
    "FALLBACK_PIN_MAX_ATTEMPTS",
    "PIN_LENGTH",
    "EmployeeHomeScreen",
    "PinDots",
    "PinPadScreen",
]
