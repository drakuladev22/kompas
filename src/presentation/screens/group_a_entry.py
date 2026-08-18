"""Qrup A — giriş axını: Splash, İlk Quraşdırma, Admin Girişi — Faza 4.2.

Maket: "KompasOS - Qrup A.dc.html", ekranlar 01–03.

──────────────────────────────────────────────────────────────────────────────
GİRİŞ NİYƏ İSTİFADƏÇİ ADI + ŞİFRƏDİR (E-POÇT VƏ 2FA DEYİL)
──────────────────────────────────────────────────────────────────────────────
Maketin özündə yazılıb: "istifadəçi adı + şifrə · özünə-xidmət bərpa yoxdur".
Bu, `SEC-016` dəyişikliyi ilə eynidir (bax həmin commit) — TOTP/2FA çıxarılıb.
E-poçt yalnız İLK QURAŞDIRMADA soruşulur və hesabın bərpa kanalıdır, giriş
vasitəsi deyil; sehrbazın özündə də belə izah olunur.

Şifrə bərpası QƏSDƏN yoxdur: mağaza işçilərinin çoxunun korporativ e-poçtu
yoxdur, ona görə "linki e-poçtuna göndər" axını real deyil. Şifrəni yalnız
Admin yeniləyir (`can_reset_password`).
"""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.presentation.theme.manager import set_surface_color
from src.presentation.theme.tokens import ThemeMode
from src.presentation.widgets import brand_assets, icons
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.forms import FormField
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.logo import CompassLogo
from src.presentation.widgets.primitives import (
    Card,
    Divider,
    body_label,
    image_label,
    mono_label,
    muted_label,
    plain_label,
    stretch,
)

if TYPE_CHECKING:
    from PySide6.QtGui import QShowEvent

    from src.presentation.theme.manager import ThemeManager

#: Maketdəki giriş kartının eni.
LOGIN_CARD_WIDTH: Final = 420
#: Sehrbazın sol addım paneli.
WIZARD_STEP_PANEL_WIDTH: Final = 300


# `_field_text()` SİLİNDİ — ŞƏRHİ YANLIŞ İDİ VƏ QÜSURU GİZLƏDİRDİ
#
# O, belə yazırdı: «keçilmiş addımın sahəsi ÜMUMİYYƏTLƏ mövcud olmur, ona görə
# `getattr` ilə yoxlamaq kifayətdir». Bu, doğru deyildi: `clear_layout()`
# `deleteLater()` çağırır, yəni C++ obyekti ölür, PYTHON ATRİBUTU İSƏ QALIR.
# `getattr(...) is not None` yoxlaması ondan keçir və `field.text()`
# `RuntimeError` atır. İstisna Qt slot-unda udulduğu üçün düymə basılır,
# heç nə baş vermir — «Keç» və «Davam Et» məhz belə ölmüşdü.
#
# İndi dəyərlər `SetupWizardScreen._answers` sözlüyündədir və `_answer()`
# metodu ilə oxunur; həmin sözlük widget-lərdən uzun yaşayır.


def _split_full_name(full_name: str) -> tuple[str, str]:
    """«Ad Soyad» → (`first_name`, `last_name`).

    Domen ayrı sahələr saxlayır, sihirbaz isə TƏK sahə soruşur (maketdə belədir
    və iki sahə soruşmaq ilk təəssüratı ağırlaşdırardı). Bir sözlük ad
    verilərsə soyad boş qalır — `RootAccountDraft` bunu qəbul edir və istifadəçi
    sonradan profilindən düzəldə bilər.
    """
    parts = full_name.split()
    if not parts:
        return ("", "")
    if len(parts) == 1:
        return (parts[0], "")
    return (" ".join(parts[:-1]), parts[-1])


def _store_code(name: str) -> str:
    """Mağaza adından qısa kod törədir («28 May» → `28-MAY`).

    Spesifikasiya (bölmə 7) sihirbazda yalnız ad/brend/ünvan soruşur, `StoreDraft`
    isə `code` tələb edir. Kodu istifadəçidən ayrıca soruşmaq ilk quraşdırmanı
    uzadardı; törədilən kod sonradan «Mağazalar» ekranından dəyişdirilə bilər.
    """
    cleaned = "".join(char if char.isalnum() else "-" for char in name.upper())
    collapsed = "-".join(part for part in cleaned.split("-") if part)
    return collapsed[:32] or "MAGAZA-1"


# --------------------------------------------------------------------------- #
# 01 — Splash
# --------------------------------------------------------------------------- #


class SplashScreen(QWidget):
    """Tam ekran açılış — loqo, ad, yüklənmə göstəricisi, versiya.

    Signals:
        finished: Yükləmə tamamlandı.
    """

    finished = Signal()

    def __init__(
        self,
        theme: ThemeManager,
        *,
        version: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setObjectName("SplashScreen")
        # Fon `--color-content-bg` DEYİL: lockup şəkli öz konteyner fonu ilə
        # gəlir və iki rəng fərqləndikdə konteyner ekranda ayrıca düzbucaqlı
        # kimi görünür. `--color-splash-bg` məhz şəkildən oxunmuş dəyərdir
        # (bax `tokens.py` — token izahı və onu şəkillə tutuşduran test).
        self.setStyleSheet(
            f"#SplashScreen {{ background-color: {theme.color('--color-splash-bg')}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(32)

        # ------------------------------------------------------------------
        # LOCKUP — TEMAYA GÖRƏ HAZIR ŞƏKİL, ÇƏKİLƏN LOQO DEYİL (logo.md)
        # ------------------------------------------------------------------
        # `loading_screen_light/dark.png` pərgar İLƏ "KompasOS" mətnini BİR
        # kompozisiyada daşıyır — hərflərin işarəyə nisbəti, boşluq və optik
        # mərkəz dizaynda həll olunub. Onu Qt-də iki ayrı elementlə (çəkilən
        # loqo + etiket) təkrar qurmaq həmin nisbətləri təxmin etmək olardı.
        #
        # Tema seçimi `ThemeManager`-in HƏLL OLUNMUŞ rejimindən gəlir
        # (`SYSTEM` → işıqlı/tünd) — fayl adı heç bir yerdə hardcode edilmir
        # (logo.md ADDIM 3).
        self._lockup = image_label()
        self._fallback_logo: CompassLogo | None = None

        if not self._apply_lockup():
            # Şəkil tapılmadı — köhnə çəkilən loqo QALIR (paket qüsuru splash-i
            # boş qoymamalıdır). İki elementin İKİSİ də əlavə olunmur: yalnız
            # işləyən yol görünür.
            self._fallback_logo = CompassLogo(
                size=96,
                background=theme.color("--color-brand-navy"),
                mark=theme.color("--color-brand-amber"),
            )
            layout.addWidget(self._fallback_logo, alignment=Qt.AlignmentFlag.AlignHCenter)

            wordmark = plain_label("KompasOS")
            wordmark_font = wordmark.font()
            wordmark_font.setPixelSize(34)
            wordmark_font.setWeight(QFont.Weight.DemiBold)
            wordmark.setFont(wordmark_font)
            wordmark.setAlignment(Qt.AlignmentFlag.AlignCenter)
            wordmark.setStyleSheet("background: transparent;")
            layout.addWidget(wordmark)
        else:
            layout.addWidget(self._lockup, alignment=Qt.AlignmentFlag.AlignHCenter)

        tagline = muted_label("Mağaza İdarəetmə Platforması", size=15)
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(tagline)

        # Maketdə bu, sağa doğru sürüşən dar zolaqdır (`@keyframes kload`).
        # Qt-də eyni effekt "qeyri-müəyyən" (`range 0,0`) progress bar-dır.
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        self._progress.setFixedSize(220, 4)
        layout.addWidget(self._progress, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._status = muted_label("Modullar yüklənir…")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status)

        # Maketdə splash-dakı versiya mono-dur (`v2.4.0`).
        version_label = mono_label(f"v{version}", muted=True)
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_label)

    #: Lockup-un ekrandakı hündürlüyü. Mənbə 1066×388-dir, yəni nisbət ~2.75:1
    #: — 132px hündürlük ≈ 363px en verir və köhnə 96px loqo + 34px başlıqdan
    #: ibarət blokun tutduğu şaquli yerlə eyni sıradadır (splash-in tarazlığı
    #: dəyişmir).
    LOCKUP_HEIGHT: Final = 132

    def _apply_lockup(self) -> bool:
        """Cari temaya uyğun lockup şəklini qoyur; fayl yoxdursa `False`."""
        pixmap = brand_assets.logo_pixmap(
            brand_assets.splash_asset(dark=self._theme.mode is ThemeMode.DARK),
            height=self.LOCKUP_HEIGHT,
        )
        if pixmap is None:
            return False
        self._lockup.setPixmap(pixmap)
        return True

    def apply_theme(self, theme: ThemeManager) -> None:
        """Tema keçidində FON və lockup birlikdə dəyişir (logo.md ADDIM 3).

        Splash qısa ömürlüdür, lakin `--theme` bayrağı ilə açılan önizləmə və
        dizayn yoxlaması onu hər iki rejimdə göstərir — şəkil fonla birlikdə
        dəyişməsəydi, tünd lockup işıqlı fonun üzərində qalardı.
        """
        self._theme = theme
        self.setStyleSheet(
            f"#SplashScreen {{ background-color: {theme.color('--color-splash-bg')}; }}"
        )
        if self._fallback_logo is not None:
            self._fallback_logo.set_colors(
                background=theme.color("--color-brand-navy"),
                mark=theme.color("--color-brand-amber"),
            )
            return
        self._apply_lockup()

    def set_status(self, text: str) -> None:
        """Yüklənən mərhələni göstərir ("Baza bağlantısı yoxlanılır…")."""
        self._status.setText(text)

    def finish_after(self, milliseconds: int) -> None:
        """Verilmiş müddətdən sonra `finished` yayır.

        Splash minimum bir müddət görünməlidir — modullar sürətlə yüklənəndə
        ekranın "sayrışması" (bir anlıq görünüb yox olması) pis görünür.
        """
        QTimer.singleShot(milliseconds, self.finished.emit)


# --------------------------------------------------------------------------- #
# 03 — Admin Girişi
# --------------------------------------------------------------------------- #


class AdminLoginScreen(QWidget):
    """Kart formalı giriş ekranı.

    Signals:
        submitted: (istifadəçi adı, şifrə).
        face_login_requested: «Üzlə daxil ol» — YALNIZ istifadəçi adı daşıyır.

    ──────────────────────────────────────────────────────────────────────────
    ÜZ DÜYMƏSİ NİYƏ İSTİFADƏÇİ ADINI DAŞIYIR
    ──────────────────────────────────────────────────────────────────────────
    Kioskda düymə heç nə daşımır: orada 1:N tanıma var və sual «bu kimdir?»
    olur. Panel maşınının mağazası yoxdur, yəni 1:N axtarış bütün şəbəkə üzrə
    gedərdi — ona görə burada 1:1 doğrulama seçilib və hesab istifadəçi adından
    tapılır (səbəb `controllers/face_login.py` başlığındadır).

    Şifrə sahəsi göndərilMİR və bu qəsdəndir: üz şifrəni ƏVƏZ EDİR, ona ƏLAVƏ
    OLUNMUR — əks halda düymənin heç bir mənası qalmazdı.
    """

    submitted = Signal(str, str)
    face_login_requested = Signal(str)

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        set_surface_color(self, theme.color("--color-content-bg"))

        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = Card(padding=40, spacing=20, shadow=True)
        card.setFixedWidth(LOGIN_CARD_WIDTH)
        card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)

        # ------------------------------ başlıq ------------------------------ #
        heading_box = QWidget()
        heading_layout = QVBoxLayout(heading_box)
        heading_layout.setContentsMargins(0, 0, 0, 0)
        heading_layout.setSpacing(16)
        heading_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # Rozet (konteynerli işarə) — `64.png`. Başlıq zolağındakı işarədən
        # FƏRQLİ fayldır və qəsdən: kart açıq səthdədir, yəni işarənin öz
        # konteyneri onu fondan ayırır. Boyanmır — rozetin daxili kontrastı
        # (tünd konteyner + açıq teal işarə) hər iki temada işləyir.
        rosette = brand_assets.logo_pixmap(brand_assets.APP_MARK, height=52)
        if rosette is not None:
            heading_layout.addWidget(image_label(rosette), alignment=Qt.AlignmentFlag.AlignHCenter)
        else:
            # Fayl yoxdursa çəkilən loqo QALIR — giriş ekranı loqosuz açılmır.
            heading_layout.addWidget(
                CompassLogo(
                    size=52,
                    background=theme.color("--color-brand-navy"),
                    mark=theme.color("--color-brand-amber"),
                ),
                alignment=Qt.AlignmentFlag.AlignHCenter,
            )

        heading = plain_label("Hesabınıza Daxil Olun")
        heading_font = heading.font()
        heading_font.setPixelSize(22)
        heading_font.setWeight(QFont.Weight.DemiBold)
        heading.setFont(heading_font)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading_layout.addWidget(heading)
        card.add(heading_box)

        # ------------------------------ sahələr ----------------------------- #
        self._username = FormField("İstifadəçi adı")
        card.add(self._username)

        self._password = FormField("Şifrə", password=True)
        card.add(self._password)

        self._submit = action_button("Daxil Ol")
        self._submit.setMinimumHeight(48)
        self._submit.setMaximumHeight(48)
        self._submit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._submit.clicked.connect(self._on_submit)
        card.add(self._submit)

        card.add(self._build_face_button())

        card.add(Divider())

        # Özünə-xidmət bərpa YOXDUR — səbəbi modul başlığında izah olunub.
        footer = body_label("Şifrənizi unutmusunuz?\nAdmininizlə əlaqə saxlayın.", size=13)
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet(f"color: {theme.color('--color-text-secondary')};")
        card.add(footer)

        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)

        # Enter ilə göndərmə — masaüstü konvensiyası.
        for field in (self._username, self._password):
            widget = field.input_widget()
            if isinstance(widget, QLineEdit):
                widget.returnPressed.connect(self._on_submit)

        # ──────────────────────────────────────────────────────────────────
        # FOKUS ZƏNCİRİ EKRANIN QURULMASININ SONUNDADIR
        # ──────────────────────────────────────────────────────────────────
        # `setTabOrder` iki MÖVCUD widget arasında əlaqə qurur; hər hansı biri
        # sonradan yaradılsaydı, Qt onu zəncirin sonuna ATARDI və sıra vizual
        # sıradan ayrılardı. Ona görə zəncir bütün widget-lər yarandıqdan
        # SONRA, bir yerdə qurulur.
        QWidget.setTabOrder(self._username.input_widget(), self._password.input_widget())
        QWidget.setTabOrder(self._password.input_widget(), self._submit)
        QWidget.setTabOrder(self._submit, self._face)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt adlandırması
        """Ekran görünəndə fokus istifadəçi adı sahəsinə qoyulur.

        Fokus KONSTRUKTORDA verilmir: giriş ekranı örtükdəki `QStackedWidget`
        -in bir səhifəsidir və konstruktor işlədikdə hələ görünmür — Qt fokus
        tələbini gizli widget üçün saxlamır. Sistem bloklanmadan sonra ekrana
        QAYIDANDA da fokus yenidən ilk sahədə olmalıdır, ona görə `showEvent`
        (bir dəfəlik bayraq deyil) düzgün yerdir.
        """
        super().showEvent(event)
        self._username.focus_input()

    def _on_submit(self) -> None:
        username = self._username.text().strip()
        password = self._password.text()

        self._username.clear_error()
        self._password.clear_error()

        if not username:
            self._username.set_error("İstifadəçi adını daxil edin")
            return
        if not password:
            self._password.set_error("Şifrəni daxil edin")
            return

        self.submitted.emit(username, password)

    # ------------------------------ üzlə giriş ------------------------------- #

    def _build_face_button(self) -> QPushButton:
        """«Üzlə daxil ol» — ŞİFRƏNİN YANINDA, ONUN ƏVƏZİ DEYİL.

        Kioskdakı düymə ilə eyni görünüş və eyni davranış qaydası
        (`PinPadScreen._build_face_button`): ikinci dərəcəli üslub, çünki
        şifrə əsas yoldur; kamera və ya modul yoxdursa düymə SÖNÜK QALMIR,
        GİZLƏNİR — sönük düymə «niyə işləmir?» sualı yaradır və istifadəçi onu
        təkrar-təkrar basır.
        """
        button = secondary_button("Üzlə daxil ol")
        button.setIcon(icons.icon("face_scan", self._theme.color("--color-text-secondary")))
        button.setIconSize(QSize(icons.DEFAULT_SIZE, icons.DEFAULT_SIZE))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumHeight(48)
        button.setMaximumHeight(48)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.clicked.connect(self._on_face_login)
        button.setVisible(False)
        self._face = button
        return button

    def _on_face_login(self) -> None:
        """Yalnız istifadəçi adı göndərilir — şifrə sahəsi OXUNMUR.

        Boş sahə xətası ŞİFRƏ sahəsində deyil, İSTİFADƏÇİ ADI sahəsində
        göstərilir: burada əskik olan məhz odur və göz onu dərhal tapmalıdır.
        """
        username = self._username.text().strip()
        self._username.clear_error()
        self._password.clear_error()

        if not username:
            self._username.set_error("Üzlə giriş üçün istifadəçi adınızı yazın")
            return

        self.face_login_requested.emit(username)

    def set_face_login_available(self, available: bool) -> None:
        """Modul və kamera kitabxanası hazırdırsa düyməni göstərir."""
        self._face.setVisible(available)

    def face_button(self) -> QPushButton:
        """Üz girişi düyməsi — kontroller/testlər üçün."""
        return self._face

    def set_error(self, message: str) -> None:
        """Serverdən gələn xətanı göstərir (yanlış ad/şifrə, bloklanmış hesab).

        Xəta ŞİFRƏ sahəsinin altında göstərilir və hansı sahənin səhv olduğu
        AÇIQLANMIR — "istifadəçi adı yanlışdır" mesajı mövcud hesabları
        sadalamağa (user enumeration) imkan verərdi.
        """
        self._password.set_error(message)

    def set_busy(self, busy: bool) -> None:
        """Sorğu gedərkən düymələri bloklayır — ikiqat göndərmənin qarşısını alır.

        ÜZ DÜYMƏSİ DƏ BLOKLANIR: kamera çəkilişi bir neçə saniyə çəkir və o
        müddətdə şifrə ilə ikinci cəhd açıq qalsaydı, iki paralel giriş axını
        yaranardı — ikisi də uğurlu olsa, hansı örtüyün qalacağı təsadüfdən
        asılı olardı.
        """
        self._submit.setEnabled(not busy)
        self._submit.setText("Yoxlanılır…" if busy else "Daxil Ol")
        self._face.setEnabled(not busy)

    def clear(self) -> None:
        self._username.set_text("")
        self._password.set_text("")
        self._username.clear_error()
        self._password.clear_error()


# --------------------------------------------------------------------------- #
# 02 — İlk Quraşdırma Sehrbazı
# --------------------------------------------------------------------------- #


class _WizardStep(QWidget):
    """Sol paneldəki bir addım göstəricisi (nömrə + ad + izah)."""

    def __init__(
        self,
        number: int,
        title: str,
        subtitle: str,
        theme: ThemeManager,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._number = number

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self._badge = plain_label(str(number))
        self._badge.setFixedSize(28, 28)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge_font = self._badge.font()
        badge_font.setPixelSize(13)
        badge_font.setWeight(QFont.Weight.DemiBold)
        self._badge.setFont(badge_font)
        layout.addWidget(self._badge)

        text_box = QWidget()
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)

        self._title = plain_label(title)
        title_font = self._title.font()
        title_font.setPixelSize(14)
        title_font.setWeight(QFont.Weight.DemiBold)
        self._title.setFont(title_font)
        text_layout.addWidget(self._title)
        text_layout.addWidget(muted_label(subtitle))

        layout.addWidget(text_box)
        layout.addWidget(stretch())

        self.set_state("upcoming")

    def set_state(self, state: str) -> None:
        """`done` / `current` / `upcoming` — nömrə dairəsinin görünüşü."""
        theme = self._theme
        if state == "current":
            background = theme.color("--color-action-bg")
            foreground = theme.color("--color-action-text")
        elif state == "done":
            background = theme.color("--color-success")
            foreground = theme.color("--color-card-bg")
        else:
            background = theme.color("--color-neutral-bg")
            foreground = theme.color("--color-text-muted")

        self._badge.setText("✓" if state == "done" else str(self._number))
        self._badge.setStyleSheet(
            f"background-color: {background}; color: {foreground};border-radius: 14px;"
        )


class FirstRunWizard(QWidget):
    """İlk quraşdırma — 4 addım: Admin → Mağaza → 1C server → HR dəvəti.

    Signals:
        completed: Bütün addımlar doldurulub (`dict` şəklində məlumat).
        cancelled: İstifadəçi imtina etdi.

    ──────────────────────────────────────────────────────────────────────
    `collected()` NİYƏ YUVALANMIŞ QAYTARIR
    ──────────────────────────────────────────────────────────────────────
    `ApplicationContext.complete_setup()` `payload["root"]`, `["stores"]`,
    `["invites"]` gözləyir. Sihirbaz əvvəl YASTI lüğət qaytarırdı
    (`{"full_name": ..., "store_name": ...}`), ona görə `root_raw` boş
    çıxır və `Username.parse("")` istisna atırdı — yəni GUI ilə yeni
    quraşdırma FAKTİKİ OLARAQ MÜMKÜN DEYİLDİ və səhv fatal ekran kimi
    görünürdü. İki tərəfin formasını burada birləşdiririk, çünki domen
    tiplərini (`Username`, `EmailAddress`) tanıyan yer kompozisiya köküdür,
    ekran deyil (bax `controllers/__init__.py`).
    """

    completed = Signal(dict)
    cancelled = Signal()

    #: Maketdəki addım tərifləri.
    STEPS: Final = (
        ("İlk Admin Hesabı", "E-poçt, istifadəçi adı, şifrə"),
        ("İlk Mağaza", "Ad, brend, ünvan"),
        ("1C Server", "İstəyə görə keçilə bilər"),
        ("HR_Admin Dəvəti", "İstəyə görə keçilə bilər"),
    )

    #: Dəvət olunan hesabın rolu — spesifikasiya (bölmə 7) HR_Admin deyir.
    INVITE_ROLE_CODE: Final = "HR_ADMIN"

    #: Bu indeksdən başlayaraq addımlar keçilə bilər (1C server, HR dəvəti).
    FIRST_OPTIONAL_STEP: Final = 2

    #: Addım → həmin addımın sahə açarları.
    #:
    #: TƏK MƏNBƏ: `collected()`, `_capture_current()` və «Keç» hər üçü bunu
    #: oxuyur. Siyahı üç yerdə saxlansaydı, yeni sahə birində unudular və
    #: nəticə sükutlu olardı — məsələn «Keç» onu təmizləməz, yarımçıq dəyər
    #: quraşdırmaya düşərdi.
    STEP_FIELDS: Final[tuple[tuple[str, ...], ...]] = (
        ("_full_name", "_email", "_username", "_password", "_password_repeat"),
        ("_store_name", "_store_brand", "_store_address"),
        ("_server_name", "_server_host", "_server_user", "_server_password"),
        ("_invite_full_name", "_invite_username", "_invite_password", "_invite_email"),
    )

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._index = 0
        # ──────────────────────────────────────────────────────────────────
        # VƏZİYYƏT WIDGET-LƏRDƏN UZUN YAŞAYIR
        # ──────────────────────────────────────────────────────────────────
        # Hər addım açılanda `_apply_step()` `clear_layout()` çağırır, o isə
        # `widget.deleteLater()` edir — yəni ƏVVƏLKİ addımın `FormField`
        # obyektləri SİLİNİR. Python atributu (`self._full_name`) qalır,
        # arxasındaki C++ obyekti isə yox: `field.text()` `RuntimeError`
        # atır. Qt slot-un içindəki istisna udulur, ona görə düymə basılır və
        # HEÇ NƏ BAŞ VERMİR — «Keç» və «Davam Et» məhz belə ölmüşdü.
        #
        # Ona görə mətnlər addım dəyişməzdən ƏVVƏL bura köçürülür və
        # `collected()` YALNIZ buradan oxuyur.
        self._answers: dict[str, str] = {}
        set_surface_color(self, theme.color("--color-content-bg"))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_step_panel())
        layout.addWidget(self._build_form_panel(), 1)

        self._apply_step()

    # ------------------------------ sol panel -------------------------------- #

    def _build_step_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(WIZARD_STEP_PANEL_WIDTH)
        panel.setStyleSheet(
            f"background-color: {self._theme.color('--color-sidebar-bg')};"
            f"border-right: 1px solid {self._theme.color('--color-sidebar-border')};"
        )

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(28, 32, 28, 32)
        layout.setSpacing(24)

        from src.presentation.widgets.primitives import section_label  # noqa: PLC0415

        layout.addWidget(section_label("Quraşdırma"))

        self._steps: list[_WizardStep] = []
        for number, (title, subtitle) in enumerate(self.STEPS, start=1):
            step = _WizardStep(number, title, subtitle, self._theme)
            self._steps.append(step)
            layout.addWidget(step)

        layout.addStretch(1)

        note = Card(padding=16, spacing=8)
        note.add(
            body_label(
                "Bu hesab sistemin ilk Admin-i olacaq. Sonradan yalnız Admin "
                "yeni istifadəçi yarada bilər.",
                size=12,
            )
        )
        layout.addWidget(note)

        return panel

    # ------------------------------ sağ panel -------------------------------- #

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(48, 40, 48, 32)
        layout.setSpacing(24)

        self._heading = plain_label()
        heading_font = self._heading.font()
        heading_font.setPixelSize(24)
        heading_font.setWeight(QFont.Weight.DemiBold)
        self._heading.setFont(heading_font)
        layout.addWidget(self._heading)

        self._description = body_label("", size=13)
        self._description.setStyleSheet(f"color: {self._theme.color('--color-text-secondary')};")
        layout.addWidget(self._description)

        # ------------------------------------------------------------------
        # QURAŞDIRMANIN RƏDD CAVABI BURADA GÖRÜNÜR — «İŞƏ DÜŞƏ BİLMƏDİ» YOX
        # ------------------------------------------------------------------
        # Əvvəl `complete_setup()` istənilən istisnada tətbiqi FATAL ekrana
        # aparırdı. Halbuki səbəblərin bir qismi istifadəçinin DÜZƏLDƏ
        # BİLƏCƏYİ şeydir (zəif şifrə, yararsız istifadəçi adı/e-poçt) —
        # onları «proqram işə düşə bilmədi» kimi göstərmək istifadəçini
        # çıxışı olmayan ekranda qoyurdu.
        #
        # Rəng cütü `--color-danger` / `--color-danger-bg`-dir, çünki
        # `--color-danger` KONTENT fonunda yalnız İRİ mətn üçün kifayət edir
        # (`check_contrast.py` sətir 57). Öz fonu ilə isə adi mətn üçün də
        # keçir və yeni cüt əlavə etmək lazım gəlmir.
        self._error = body_label("", size=13)
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        self._error.setStyleSheet(
            f"background-color: {self._theme.color('--color-danger-bg')};"
            f"color: {self._theme.color('--color-danger')};"
            "border-radius: 12px; padding: 12px 14px;"
        )
        layout.addWidget(self._error)

        self._fields_host = QWidget()
        self._fields_layout = QVBoxLayout(self._fields_host)
        self._fields_layout.setContentsMargins(0, 0, 0, 0)
        self._fields_layout.setSpacing(16)
        layout.addWidget(self._fields_host)

        layout.addStretch(1)
        layout.addWidget(Divider())

        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(12)

        self._progress_label = muted_label("")
        footer_layout.addWidget(self._progress_label)
        footer_layout.addWidget(stretch())

        self._back = secondary_button("Geri")
        self._back.clicked.connect(self._on_back)
        footer_layout.addWidget(self._back)

        self._skip = secondary_button("Keç")
        self._skip.clicked.connect(self._on_skip)
        footer_layout.addWidget(self._skip)

        self._next = action_button("Davam Et")
        self._next.clicked.connect(self._on_next)
        footer_layout.addWidget(self._next)

        layout.addWidget(footer)
        return panel

    # ------------------------------ addımlar --------------------------------- #

    def show_error(self, message: str, *, field: str = "") -> None:
        """Quraşdırma rədd edildi — sihirbaz AÇIQ qalır, mesaj göstərilir.

        ────────────────────────────────────────────────────────────────────
        NİYƏ BİRİNCİ ADDIMA QAYIDIR
        ────────────────────────────────────────────────────────────────────
        `complete_setup()`-ın rədd etdiyi sahələr — istifadəçi adı, e-poçt,
        şifrə — HAMISI birinci addımdadır. Mağaza addımını sihirbaz özü
        yoxlayır (`_validate_current`), yəni ora çatan səhv qalmır.
        İstifadəçini olduğu yerdə saxlasaydıq, o, düzəltməli olduğu sahəyə
        çatmaq üçün üç dəfə «Geri» basmalı olardı.

        Args:
            message: İstifadəçiyə göstərilən izah.
            field: Səhvin AİD OLDUĞU sahə (`_password`, `_username`,
                `_email`). Boşdursa yalnız ümumi mesaj göstərilir. Ad
                ÇAĞIRANDAN gəlir, mesaj mətnindən çıxarılmır: mətnə baxıb
                təxmin etmək dil dəyişəndə sükutla sınardı.
        """
        self._index = 0
        self._apply_step()  # sahələr yenidən qurulur, `_answers` bərpa olunur

        self._error.setText(message)
        self._error.setVisible(True)

        target = getattr(self, field, None) if field else None
        if target is not None:
            target.set_error(message)

    def _apply_step(self) -> None:
        """Cari addımın sahələrini qurur və göstəriciləri yeniləyir."""
        # Xəta mesajı YALNIZ göstərildiyi addımda qalır: istifadəçi irəli/geri
        # keçəndə köhnə mesaj ekranda ilişib qalsaydı, düzəldilmiş sahə hələ
        # də səhv görünərdi.
        self._error.setVisible(False)

        for position, step in enumerate(self._steps):
            if position < self._index:
                step.set_state("done")
            elif position == self._index:
                step.set_state("current")
            else:
                step.set_state("upcoming")

        clear_layout(self._fields_layout)

        builder = (
            self._build_admin_fields,
            self._build_store_fields,
            self._build_server_fields,
            self._build_invite_fields,
        )[self._index]
        builder()

        self._progress_label.setText(f"Addım {self._index + 1} / {len(self.STEPS)}")
        self._back.setEnabled(self._index > 0)
        # 1C server və HR dəvəti addımları keçilə bilər — hər ikisi
        # spesifikasiyada "istəyə görə"dir (bölmə 7, sətir 223).
        self._skip.setVisible(self._index >= self.FIRST_OPTIONAL_STEP)
        self._next.setText("Tamamla" if self._index == len(self.STEPS) - 1 else "Davam Et")

    def _field(self, key: str, label: str, *, password: bool = False) -> FormField:
        """Sahəni qurur və ƏVVƏL yazılmış dəyəri BƏRPA edir.

        Bərpa olmadan «Geri» düyməsi istifadəçinin yazdığını silərdi: widget
        yenidən yaradılır, köhnəsi isə artıq məhv edilib.

        `placeholder` QƏSDƏN VERİLMİR — bax sinif docstring-i.
        """
        field = FormField(label, password=password)
        field.set_text(self._answers.get(key, ""))
        return field

    def _answer(self, key: str) -> str:
        """Toplanmış cavab — sahə heç açılmayıbsa boş sətir."""
        return self._answers.get(key, "")

    def _capture_current(self) -> None:
        """Cari addımın mətnlərini `_answers`-ə köçürür və atributları boşaldır.

        Atributun `None`-a qoyulması MƏCBURİDİR: silinmiş widget-ə istinad
        qalsaydı, sonrakı hər oxunuş `RuntimeError` riski daşıyardı və o,
        Qt slot-unda sükutla udulardı.
        """
        for key in self.STEP_FIELDS[self._index]:
            field = getattr(self, key, None)
            if field is None:
                continue
            with suppress(RuntimeError):
                self._answers[key] = field.text().strip()
            setattr(self, key, None)

    def _discard_current(self) -> None:
        """«Keç» — bu addımın cavabları SİLİNİR.

        Keçilmiş addım quraşdırmaya DÜŞMƏMƏLİDİR. Yalnız validasiyanı yan
        keçsəydik, yarımçıq yazılmış server/dəvət məlumatı sükutla yazılardı.
        """
        for key in self.STEP_FIELDS[self._index]:
            self._answers.pop(key, None)
            setattr(self, key, None)

    def _build_admin_fields(self) -> None:
        self._heading.setText("İlk Admin Hesabı")
        self._description.setText(
            "Sistemə tam səlahiyyətli bir hesab yaradın. E-poçt yalnız "
            "qeydiyyat üçündür — sonrakı girişlər istifadəçi adı ilə olur."
        )
        self._full_name = self._field("_full_name", "Ad, Soyad")
        self._email = self._field("_email", "E-poçt")
        self._username = self._field("_username", "İstifadəçi adı")
        self._password = self._field("_password", "Şifrə", password=True)
        self._password_repeat = self._field("_password_repeat", "Şifrənin Təkrarı", password=True)
        for field in (
            self._full_name,
            self._email,
            self._username,
            self._password,
            self._password_repeat,
        ):
            self._fields_layout.addWidget(field)

    def _build_store_fields(self) -> None:
        self._heading.setText("İlk Mağaza")
        self._description.setText(
            "Ən azı bir mağaza tələb olunur — işçilər və növbələr mağazaya bağlanır."
        )
        self._store_name = self._field("_store_name", "Mağaza adı")
        self._store_brand = self._field("_store_brand", "Brend")
        self._store_address = self._field("_store_address", "Ünvan")
        for field in (self._store_name, self._store_brand, self._store_address):
            self._fields_layout.addWidget(field)

    def _build_server_fields(self) -> None:
        self._heading.setText("1C Server")
        self._description.setText(
            "Satış məlumatları bu serverdən oxunur. İndi keçsəniz, sonradan "
            "«ERP / 1C Serverləri» bölməsindən əlavə edə bilərsiniz."
        )
        self._server_name = self._field("_server_name", "Server adı")
        self._server_host = self._field("_server_host", "Ünvan")
        self._server_user = self._field("_server_user", "İstifadəçi")
        self._server_password = self._field("_server_password", "Şifrə", password=True)
        for field in (
            self._server_name,
            self._server_host,
            self._server_user,
            self._server_password,
        ):
            self._fields_layout.addWidget(field)

    def _build_invite_fields(self) -> None:
        """Addım 4 — HR_Admin dəvəti (bölmə 7, sətir 223).

        Müvəqqəti şifrə ilk girişdə məcburi dəyişdirilir — e-poçt token
        axını YOXDUR (SEC-016, bölmə 2). E-poçt sahəsi yalnız BİLDİRİŞ
        üçündür, giriş identifikatoru istifadəçi adıdır.
        """
        self._heading.setText("HR_Admin Dəvəti")
        self._description.setText(
            "İkinci admin-səviyyəli hesab yaradın. Tək hesab qalıb bloklanmasın "
            "deyə bu tövsiyə olunur — indi keçsəniz, sonradan «İstifadəçilər» "
            "bölməsindən əlavə edə bilərsiniz."
        )
        self._invite_full_name = self._field("_invite_full_name", "Ad, Soyad")
        self._invite_username = self._field("_invite_username", "İstifadəçi adı")
        self._invite_password = self._field("_invite_password", "Müvəqqəti şifrə", password=True)
        self._invite_email = self._field("_invite_email", "E-poçt (istəyə görə)")
        for field in (
            self._invite_full_name,
            self._invite_username,
            self._invite_password,
            self._invite_email,
        ):
            self._fields_layout.addWidget(field)

    # ------------------------------ naviqasiya ------------------------------- #

    def _on_back(self) -> None:
        if self._index == 0:
            self.cancelled.emit()
            return
        self._capture_current()
        self._index -= 1
        self._apply_step()

    def _on_next(self) -> None:
        """«Davam Et» — validasiya, tutma, sonra irəliləmə.

        TUTMA İNDEKS DƏYİŞMƏZDƏN ƏVVƏLDİR: `_capture_current()`
        `self._index`-ə baxır, ona görə artırmadan sonra çağırılsaydı NÖVBƏTİ
        addımın (hələ qurulmamış) sahələrini oxumağa çalışardı.
        """
        if not self._validate_current():
            return
        self._capture_current()
        if self._index < len(self.STEPS) - 1:
            self._index += 1
            self._apply_step()
            return
        self.completed.emit(self.collected())

    def _on_skip(self) -> None:
        """«Keç» — validasiya YOX, cavablar SİLİNİR.

        Əvvəl bu düymə `_on_next`-ə bağlı idi, yəni «Davam Et»in eynisi idi:
        validasiyadan keçirdi və keçilən addımın yarımçıq dəyərlərini
        saxlayırdı. «Keç» sözü hər iki davranışın əksini vəd edir.
        """
        self._discard_current()
        if self._index < len(self.STEPS) - 1:
            self._index += 1
            self._apply_step()
            return
        self.completed.emit(self.collected())

    def _validate_current(self) -> bool:
        """Cari addımın məcburi sahələrini yoxlayır."""
        if self._index == 0:
            required = (
                (self._full_name, "Ad və soyadı daxil edin"),
                (self._email, "E-poçt ünvanını daxil edin"),
                (self._username, "İstifadəçi adını daxil edin"),
                (self._password, "Şifrəni daxil edin"),
            )
            valid = True
            for field, message in required:
                field.clear_error()
                if not field.text().strip():
                    field.set_error(message)
                    valid = False
            if valid and self._password.text() != self._password_repeat.text():
                self._password_repeat.set_error("Şifrələr uyğun gəlmir")
                valid = False
            return valid

        if self._index == 1:
            self._store_name.clear_error()
            if not self._store_name.text().strip():
                self._store_name.set_error("Mağaza adını daxil edin")
                return False
        return True

    def collected(self) -> dict[str, object]:
        """Sihirbazın nəticəsi — `complete_setup()`-ın gözlədiyi FORMADA.

        Bax sinif docstring-i: yastı lüğət qaytarmaq quraşdırmanı tamamilə
        sındırırdı. Burada yalnız FORMA çevrilir; domen tiplərinə çevirmə
        (`Username.parse`, `EmailAddress.parse`) və validasiya kompozisiya
        kökündədir — ekran domen tiplərini tanımır.
        """
        first_name, last_name = _split_full_name(self._answer("_full_name"))
        payload: dict[str, object] = {
            "root": {
                "first_name": first_name,
                "last_name": last_name,
                "email": self._answer("_email"),
                "username": self._answer("_username"),
                "password": self._answer("_password"),
            },
            "stores": [],
            "invites": [],
        }

        store_name = self._answer("_store_name")
        if store_name:
            payload["stores"] = [
                {
                    # Kod verilmirsə addan törədilir — `StoreDraft.code`
                    # məcburidir və istifadəçidən ayrıca soruşmaq sihirbazı
                    # uzadardı (spesifikasiya yalnız ad/brend/ünvan deyir).
                    "code": _store_code(store_name),
                    "name": store_name,
                    "brand": self._answer("_store_brand"),
                    "address": self._answer("_store_address"),
                }
            ]

        invite_name = self._answer("_invite_full_name")
        invite_username = self._answer("_invite_username")
        if invite_name and invite_username:
            invite_first, invite_last = _split_full_name(invite_name)
            payload["invites"] = [
                {
                    "first_name": invite_first,
                    "last_name": invite_last,
                    "username": invite_username,
                    "role_code": self.INVITE_ROLE_CODE,
                    "temporary_password": self._answer("_invite_password"),
                    "email": self._answer("_invite_email"),
                }
            ]

        server_host = self._answer("_server_host")
        if server_host:
            payload["server"] = {
                "name": self._answer("_server_name"),
                "host": server_host,
                "username": self._answer("_server_user"),
                "password": self._answer("_server_password"),
            }
        return payload

    @property
    def step_index(self) -> int:
        return self._index


# --------------------------------------------------------------------------- #
# 04 — Fatal başlanğıc xətası (bölmə 8, EHTİYAT DƏSTƏK KANALI)
# --------------------------------------------------------------------------- #


class FatalStartupScreen(QWidget):
    """Tətbiq ümumiyyətlə işə düşə bilmədi.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ AYRICA EKRAN, MODAL DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Modal arxasında işlək bir pəncərə olmalıdır; burada isə heç nə yoxdur —
    baza bağlantısı və ya konfiqurasiya yoxdur, yəni menyu, örtük, ekranlar
    qurula bilmir. Boş pəncərə üzərində modal göstərmək istifadəçini "arxada
    nəsə var" gözləntisinə salardı.

    ──────────────────────────────────────────────────────────────────────────
    ƏLAQƏ ÜNVANI NİYƏ STATİKDİR
    ──────────────────────────────────────────────────────────────────────────
    Bölmə 8: "hər fatal başlanğıc-xətası ekranında STATİK e-poçt ünvanı
    göstərilir". Ünvanı bazadan oxumaq mənasız olardı — məhz baza əlçatmaz
    olduğu üçün bu ekran görünür. Ona görə mətn koddadır.

    ──────────────────────────────────────────────────────────────────────────
    DÜYMƏLƏR İSTƏYƏ BAĞLIDIR VƏ DEFOLT YOXDUR (DB-4 Faza 4)
    ──────────────────────────────────────────────────────────────────────────
    Ekran əvvəl yalnız mətn göstərirdi. `retry=True` təkrar cəhd düyməsi
    əlavə edir — server müvəqqəti əlçatmaz olanda bu, mənalı yeganə
    hərəkətdir. Defolt `False`-dur: səhv nasazlıqda təkrar cəhd təklif etmək
    istifadəçini nəticəsiz döngəyə salardı, yəni düymənin OLMAMASI da qərardır.

    ──────────────────────────────────────────────────────────────────────────
    «BAĞLANTI AYARLARI» DÜYMƏSİ ARTIQ YOXDUR (RECOVERY-1 Faza 2)
    ──────────────────────────────────────────────────────────────────────────
    Əvvəl konfiqurasiya nasazlığında ekran ikinci düymə göstərirdi. Nəticə:
    mağaza işçisi problemi ÖZÜ «düzəltməyə» çalışır və İŞLƏK konfiqurasiyanı
    poza bilirdi — sonra dəstək həm nasazlığı, həm də ona əlavə olunmuş
    dəyişikliyi araşdırmalı qalırdı.

    Müştərinin gördüyü ekran indi QƏSDƏN kasıbdır: mesaj + «Yenidən Cəhd Et» +
    dəstək ünvanı. Eyni imkan TEXNİKDƏDİR: `Ctrl+Shift+K` → Bərpa Konsolu
    (qapı `controllers/recovery_console.may_open`-dadır). Nasazlığın NÖVÜ
    ötürülməkdə davam edir (DB-4 Faza 4) — `app.py` ona görə qərar verir.

    Signals:
        retry_requested: «Yenidən cəhd et» basıldı.
    """

    #: Tətbiq açılmadıqda müştərinin yeganə çıxış yolu (bölmə 8).
    FALLBACK_CONTACT: Final = "dəstək@kompas.az · +994 12 000 00 00"

    retry_requested = Signal()

    def __init__(
        self,
        theme: ThemeManager,
        *,
        message: str,
        contact: str = FALLBACK_CONTACT,
        retry: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        set_surface_color(self, theme.color("--color-content-bg"))

        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = Card(padding=40, spacing=20, surface="modal", shadow=True)
        card.setFixedWidth(560)
        card.body().setAlignment(Qt.AlignmentFlag.AlignHCenter)

        heading = plain_label("KompasOS işə düşə bilmədi")
        heading_font = heading.font()
        heading_font.setPixelSize(24)
        heading_font.setWeight(QFont.Weight.DemiBold)
        heading.setFont(heading_font)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.add(heading)

        detail = body_label(message, size=13)
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail.setMaximumWidth(440)
        detail.setStyleSheet(f"color: {theme.color('--color-text-secondary')};")
        card.body().addWidget(detail, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._retry_button: QPushButton | None = None
        if retry:
            actions = QWidget()
            actions_layout = QHBoxLayout(actions)
            actions_layout.setContentsMargins(0, 0, 0, 0)
            actions_layout.setSpacing(12)
            actions_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

            if retry:
                self._retry_button = action_button("Yenidən Cəhd Et")
                self._retry_button.setMinimumHeight(44)
                self._retry_button.clicked.connect(self.retry_requested.emit)
                actions_layout.addWidget(self._retry_button)

            card.add(actions)

        card.add(Divider())

        hint = muted_label("Problem davam edərsə bu ünvanla əlaqə saxlayın:")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.body().addWidget(hint, alignment=Qt.AlignmentFlag.AlignHCenter)

        contact_label = mono_label(contact, size=13)
        contact_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.body().addWidget(contact_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)


# --------------------------------------------------------------------------- #
# 05 — Bağlantı Ayarları (DB-4 Faza 4)
# --------------------------------------------------------------------------- #


class ConnectionSettingsScreen(QWidget):
    """Baza bağlantı məlumatlarını daxil etmə ekranı — GİRİŞDƏN ƏVVƏL.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ BU EKRAN SİHİRBAZIN İÇİNDƏ DEYİL
    ──────────────────────────────────────────────────────────────────────────
    İlk Quraşdırma Sihirbazı Root hesabını BAZAYA yazır — yəni işləmək üçün
    bağlantı ARTIQ lazımdır. DSN-i onun içində soruşmaq sihirbazı özündən əvvəl
    işləməyə məcbur edərdi (bax `infrastructure/config/connection_file.py`).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ GİRİŞ TƏLƏB OLUNMUR
    ──────────────────────────────────────────────────────────────────────────
    «Görmək = səlahiyyətin olması» qaydası BAZADAKI məlumata aiddir; burada isə
    heç bir baza məlumatı göstərilmir və göstərilə də bilməz — ekran məhz baza
    əlçatmaz olduğu üçün açılır. Səlahiyyəti bazadan yoxlamaq üçün bazaya
    qoşulmaq lazımdır, qoşulmaq üçünsə bu ekran. Qoruma FİZİKİDİR: fayl
    `%PROGRAMDATA%`-dədir və ora yazmaq administrator hüququ tələb edir.

    ──────────────────────────────────────────────────────────────────────────
    PAROL SAHƏSİ BOŞ AÇILIR
    ──────────────────────────────────────────────────────────────────────────
    Mövcud host/istifadəçi doldurulur ki, istifadəçi «hansı serverə baxır?»
    sualını cavablasın. Parol isə YÜKLƏNMİR: onu ekrana çıxarmaq üçün əvvəlcə
    deşifrələmək lazımdır və o vərdiş paylaşılan mağaza kompüterində parolu
    çiynin üstündən oxunan hala gətirərdi. Boş qalarsa mövcud parol saxlanılır.

    Signals:
        submitted: `dict` — host, port, database, username, password, sslmode.
        cancelled: istifadəçi imtina etdi.
    """

    submitted = Signal(dict)
    cancelled = Signal()

    #: Kartın eni giriş kartından (420) GENİŞDİR — DSN sahələri uzundur
    #: (Supabase host adı ~40 simvol) və dar kartda mətn kəsilirdi.
    #:
    #: Dəyər `FatalStartupScreen` ilə EYNİDİR və bu, təsadüf deyil: istifadəçi
    #: iki ekran arasında irəli-geri keçir, fərqli en isə kartın hər keçiddə
    #: «sıçraması» kimi görünərdi. 560 həm də layihənin mövcud forma enidir
    #: (səkkiz ekranda `setMinimumWidth(560)`) — yeni ad-hoc ölçü yaratmaq
    #: dizayn səpələnməsi qapısını da pozardı (`test_design_symmetry.py`).
    CARD_WIDTH: Final = 560

    #: TCP portunun yuxarı həddi — protokol faktıdır, Root parametri deyil.
    MAX_PORT: Final = 65535

    def __init__(
        self,
        theme: ThemeManager,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        set_surface_color(self, theme.color("--color-content-bg"))

        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Doldurma və aralıq qonşu giriş ekranları ilə EYNİDİR (`AdminLoginScreen`,
        # `FatalStartupScreen`): istifadəçi bu üç ekran arasında keçir və ad-hoc
        # 36px kartın hər keçiddə bir neçə piksel «tərpənməsi» kimi görünərdi.
        card = Card(padding=40, spacing=16, surface="modal", shadow=True)
        card.setFixedWidth(self.CARD_WIDTH)

        heading = plain_label("Bağlantı Ayarları")
        heading_font = heading.font()
        heading_font.setPixelSize(22)
        heading_font.setWeight(QFont.Weight.DemiBold)
        heading.setFont(heading_font)
        card.add(heading)

        intro = body_label(
            "Server məlumatlarını daxil edin. Yadda saxlamazdan əvvəl bağlantı "
            "yoxlanılır — yalnız işləyən ayarlar saxlanılır.",
            size=13,
        )
        intro.setStyleSheet(f"color: {theme.color('--color-text-secondary')};")
        card.add(intro)

        self._host = FormField("Server ünvanı")
        self._port = FormField("Port")
        self._database = FormField("Baza adı")
        self._username = FormField("İstifadəçi adı")
        self._password = FormField("Parol", password=True)
        for field in (self._host, self._port, self._database, self._username, self._password):
            card.add(field)

        self._status = muted_label("")
        self._status.setWordWrap(True)
        card.add(self._status)

        # DİAQNOSTİKA — bax `controllers/connection_settings.diagnostic_paths`.
        # Kart mətninin ən kiçik və ən solğun hissəsidir: o, formanı DOLDURAN
        # istifadəçiyə lazım deyil, yalnız «proqram hansı faylı oxuyur?»
        # sualını verən quraşdırıcıya lazımdır. Vurğulu göstərsəydik, hər
        # açılışda diqqəti forma sahələrindən yayındırardı.
        self._diagnostics = muted_label("")
        self._diagnostics.setWordWrap(True)
        diagnostics_font = self._diagnostics.font()
        diagnostics_font.setPixelSize(11)
        self._diagnostics.setFont(diagnostics_font)
        self._diagnostics.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        card.add(self._diagnostics)

        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(12)

        self._cancel = secondary_button("İmtina")
        self._cancel.setMinimumHeight(44)
        self._cancel.clicked.connect(self.cancelled.emit)
        actions_layout.addWidget(self._cancel)

        actions_layout.addWidget(stretch())

        self._submit = action_button("Yoxla və Yadda Saxla")
        self._submit.setMinimumHeight(44)
        self._submit.clicked.connect(self._on_submit)
        actions_layout.addWidget(self._submit)

        card.add(actions)
        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)

        for field in (self._host, self._port, self._database, self._username, self._password):
            widget = field.input_widget()
            if isinstance(widget, QLineEdit):
                widget.returnPressed.connect(self._on_submit)

    # ------------------------------ setter API -------------------------------- #

    def set_diagnostics(self, rows: list[tuple[str, str]]) -> None:
        """Proqramın FAKTİKİ işlətdiyi yolları göstərir.

        Ekran yolları ÖZÜ hesablamır (CLAUDE.md §6): o, yalnız `theme` alır və
        setter API-si təqdim edir. Hesablama `connection_settings` kontrollerin-
        dədir, çünki yollar mühit dəyişənlərindən və fayl sistemindən asılıdır.
        """
        self._diagnostics.setText("\n".join(f"{label}: {value}" for label, value in rows))

    def populate(self, settings: dict[str, object]) -> None:
        """Mövcud dəyərləri göstərir (parol İSTİSNA — bax sinif başlığı)."""
        self._host.set_text(str(settings.get("host", "")))
        self._port.set_text(str(settings.get("port", "") or ""))
        self._database.set_text(str(settings.get("database", "")))
        self._username.set_text(str(settings.get("username", "")))

    def set_error(self, message: str) -> None:
        self._status.setText(message)
        self._status.setStyleSheet(f"color: {self._theme.color('--color-danger')};")

    def set_status(self, message: str) -> None:
        self._status.setText(message)
        self._status.setStyleSheet(f"color: {self._theme.color('--color-text-secondary')};")

    def set_busy(self, busy: bool) -> None:
        """Sınaq gedərkən düymə bloklanır — ikiqat sorğu şəbəkəni gözlədir."""
        self._submit.setEnabled(not busy)
        self._submit.setText("Yoxlanılır…" if busy else "Yoxla və Yadda Saxla")

    # -------------------------------- daxili ---------------------------------- #

    def _on_submit(self) -> None:
        for field in (self._host, self._port, self._database, self._username):
            field.clear_error()

        host = self._host.text().strip()
        database = self._database.text().strip() or "postgres"
        username = self._username.text().strip()
        raw_port = self._port.text().strip() or "5432"

        if not host:
            self._host.set_error("Server ünvanını daxil edin")
            return
        if not username:
            self._username.set_error("İstifadəçi adını daxil edin")
            return
        if not raw_port.isdigit() or not 1 <= int(raw_port) <= self.MAX_PORT:
            # PORT EKRANDA YOXLANILIR: yanlış port `psycopg`-də "host tapılmadı"
            # kimi görünür və istifadəçi səhvi ünvanda axtarardı.
            self._port.set_error("Port 1–65535 aralığında rəqəm olmalıdır")
            return

        self.submitted.emit(
            {
                "host": host,
                "port": int(raw_port),
                "database": database,
                "username": username,
                "password": self._password.text(),
                "sslmode": "require",
            }
        )


__all__ = [
    "LOGIN_CARD_WIDTH",
    "AdminLoginScreen",
    "ConnectionSettingsScreen",
    "FatalStartupScreen",
    "FirstRunWizard",
    "SplashScreen",
]
