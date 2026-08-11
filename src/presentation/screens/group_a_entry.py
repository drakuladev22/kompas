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

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.forms import FormField
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.logo import CompassLogo
from src.presentation.widgets.primitives import (
    Card,
    Divider,
    body_label,
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


def _field_text(owner: object, attribute: str) -> str:
    """Sehrbaz sahəsinin mətni — sahə hələ qurulmayıbsa boş sətir.

    Sahələr addım açılanda yaradılır (`_apply_step` → `_build_*_fields`), ona
    görə keçilmiş addımın sahəsi ÜMUMİYYƏTLƏ mövcud olmur. `getattr` ilə
    yoxlamaq `hasattr` şəlaləsindən qısa və hər sahə üçün eynidir.
    """
    field = getattr(owner, attribute, None)
    return field.text().strip() if field is not None else ""


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
        self.setStyleSheet(
            f"#SplashScreen {{ background-color: {theme.color('--color-content-bg')}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(30)

        logo = CompassLogo(
            size=96,
            background=theme.color("--color-brand-navy"),
            mark=theme.color("--color-brand-amber"),
        )
        layout.addWidget(logo, alignment=Qt.AlignmentFlag.AlignHCenter)

        wordmark = plain_label("KompasOS")
        wordmark_font = wordmark.font()
        wordmark_font.setPixelSize(34)
        wordmark_font.setWeight(QFont.Weight.DemiBold)
        wordmark.setFont(wordmark_font)
        wordmark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wordmark.setStyleSheet("background: transparent;")
        layout.addWidget(wordmark)

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
    """

    submitted = Signal(str, str)

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setStyleSheet(f"background-color: {theme.color('--color-content-bg')};")

        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = Card(padding=40, spacing=22, shadow=True)
        card.setFixedWidth(LOGIN_CARD_WIDTH)
        card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)

        # ------------------------------ başlıq ------------------------------ #
        heading_box = QWidget()
        heading_layout = QVBoxLayout(heading_box)
        heading_layout.setContentsMargins(0, 0, 0, 0)
        heading_layout.setSpacing(14)
        heading_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

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
        self._username = FormField("İstifadəçi adı", placeholder="r.mammadov")
        card.add(self._username)

        self._password = FormField("Şifrə", password=True)
        card.add(self._password)

        self._submit = action_button("Daxil Ol")
        self._submit.setMinimumHeight(48)
        self._submit.setMaximumHeight(48)
        self._submit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._submit.clicked.connect(self._on_submit)
        card.add(self._submit)

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

    def set_error(self, message: str) -> None:
        """Serverdən gələn xətanı göstərir (yanlış ad/şifrə, bloklanmış hesab).

        Xəta ŞİFRƏ sahəsinin altında göstərilir və hansı sahənin səhv olduğu
        AÇIQLANMIR — "istifadəçi adı yanlışdır" mesajı mövcud hesabları
        sadalamağa (user enumeration) imkan verərdi.
        """
        self._password.set_error(message)

    def set_busy(self, busy: bool) -> None:
        """Sorğu gedərkən düyməni bloklayır — ikiqat göndərmənin qarşısını alır."""
        self._submit.setEnabled(not busy)
        self._submit.setText("Yoxlanılır…" if busy else "Daxil Ol")

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
        layout.setSpacing(14)

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
        text_layout.setSpacing(2)

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

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._index = 0
        self.setStyleSheet(f"background-color: {theme.color('--color-content-bg')};")

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

        note = Card(padding=14, spacing=6)
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
        layout.setSpacing(22)

        self._heading = plain_label()
        heading_font = self._heading.font()
        heading_font.setPixelSize(24)
        heading_font.setWeight(QFont.Weight.DemiBold)
        self._heading.setFont(heading_font)
        layout.addWidget(self._heading)

        self._description = body_label("", size=14)
        self._description.setStyleSheet(f"color: {self._theme.color('--color-text-secondary')};")
        layout.addWidget(self._description)

        self._fields_host = QWidget()
        self._fields_layout = QVBoxLayout(self._fields_host)
        self._fields_layout.setContentsMargins(0, 0, 0, 0)
        self._fields_layout.setSpacing(18)
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
        self._skip.clicked.connect(self._on_next)
        footer_layout.addWidget(self._skip)

        self._next = action_button("Davam Et")
        self._next.clicked.connect(self._on_next)
        footer_layout.addWidget(self._next)

        layout.addWidget(footer)
        return panel

    # ------------------------------ addımlar --------------------------------- #

    def _apply_step(self) -> None:
        """Cari addımın sahələrini qurur və göstəriciləri yeniləyir."""
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

    def _build_admin_fields(self) -> None:
        self._heading.setText("İlk Admin Hesabı")
        self._description.setText(
            "Sistemə tam səlahiyyətli bir hesab yaradın. E-poçt yalnız "
            "qeydiyyat üçündür — sonrakı girişlər istifadəçi adı ilə olur."
        )
        self._full_name = FormField("Ad, Soyad", placeholder="Rəşad Məmmədov")
        self._email = FormField("E-poçt", placeholder="admin@kompas.az")
        self._username = FormField("İstifadəçi adı", placeholder="r.mammadov")
        self._password = FormField("Şifrə", password=True)
        self._password_repeat = FormField("Şifrənin Təkrarı", password=True)
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
        self._store_name = FormField("Mağaza adı", placeholder="28 May")
        self._store_brand = FormField("Brend", placeholder="Bellona")
        self._store_address = FormField("Ünvan", placeholder="Bakı, Nizami küç. 1")
        for field in (self._store_name, self._store_brand, self._store_address):
            self._fields_layout.addWidget(field)

    def _build_server_fields(self) -> None:
        self._heading.setText("1C Server")
        self._description.setText(
            "Satış məlumatları bu serverdən oxunur. İndi keçsəniz, sonradan "
            "«ERP / 1C Serverləri» bölməsindən əlavə edə bilərsiniz."
        )
        self._server_name = FormField("Server adı", placeholder="1C-BAKI-01")
        self._server_host = FormField("Ünvan", placeholder="192.168.1.10:1541")
        self._server_user = FormField("İstifadəçi", placeholder="kompas_sync")
        self._server_password = FormField("Şifrə", password=True)
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
        self._invite_full_name = FormField("Ad, Soyad", placeholder="Aysel Quliyeva")
        self._invite_username = FormField("İstifadəçi adı", placeholder="a.quliyeva")
        self._invite_password = FormField("Müvəqqəti şifrə", password=True)
        self._invite_email = FormField("E-poçt (istəyə görə)", placeholder="hr@kompas.az")
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
        self._index -= 1
        self._apply_step()

    def _on_next(self) -> None:
        if self._index < len(self.STEPS) - 1:
            if not self._validate_current():
                return
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
        first_name, last_name = _split_full_name(_field_text(self, "_full_name"))
        payload: dict[str, object] = {
            "root": {
                "first_name": first_name,
                "last_name": last_name,
                "email": _field_text(self, "_email"),
                "username": _field_text(self, "_username"),
                "password": _field_text(self, "_password"),
            },
            "stores": [],
            "invites": [],
        }

        store_name = _field_text(self, "_store_name")
        if store_name:
            payload["stores"] = [
                {
                    # Kod verilmirsə addan törədilir — `StoreDraft.code`
                    # məcburidir və istifadəçidən ayrıca soruşmaq sihirbazı
                    # uzadardı (spesifikasiya yalnız ad/brend/ünvan deyir).
                    "code": _store_code(store_name),
                    "name": store_name,
                    "brand": _field_text(self, "_store_brand"),
                    "address": _field_text(self, "_store_address"),
                }
            ]

        invite_name = _field_text(self, "_invite_full_name")
        invite_username = _field_text(self, "_invite_username")
        if invite_name and invite_username:
            invite_first, invite_last = _split_full_name(invite_name)
            payload["invites"] = [
                {
                    "first_name": invite_first,
                    "last_name": invite_last,
                    "username": invite_username,
                    "role_code": self.INVITE_ROLE_CODE,
                    "temporary_password": _field_text(self, "_invite_password"),
                    "email": _field_text(self, "_invite_email"),
                }
            ]

        server_host = _field_text(self, "_server_host")
        if server_host:
            payload["server"] = {
                "name": _field_text(self, "_server_name"),
                "host": server_host,
                "username": _field_text(self, "_server_user"),
                "password": _field_text(self, "_server_password"),
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
    """

    #: Tətbiq açılmadıqda müştərinin yeganə çıxış yolu (bölmə 8).
    FALLBACK_CONTACT: Final = "dəstək@kompas.az · +994 12 000 00 00"

    def __init__(
        self,
        theme: ThemeManager,
        *,
        message: str,
        contact: str = FALLBACK_CONTACT,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {theme.color('--color-content-bg')};")

        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = Card(padding=44, spacing=20, surface="modal", shadow=True)
        card.setFixedWidth(560)
        card.body().setAlignment(Qt.AlignmentFlag.AlignHCenter)

        heading = plain_label("KompasOS işə düşə bilmədi")
        heading_font = heading.font()
        heading_font.setPixelSize(24)
        heading_font.setWeight(QFont.Weight.DemiBold)
        heading.setFont(heading_font)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.add(heading)

        detail = body_label(message, size=14)
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail.setMaximumWidth(440)
        detail.setStyleSheet(f"color: {theme.color('--color-text-secondary')};")
        card.body().addWidget(detail, alignment=Qt.AlignmentFlag.AlignHCenter)

        card.add(Divider())

        hint = muted_label("Problem davam edərsə bu ünvanla əlaqə saxlayın:")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.body().addWidget(hint, alignment=Qt.AlignmentFlag.AlignHCenter)

        contact_label = mono_label(contact, size=14)
        contact_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.body().addWidget(contact_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)


__all__ = [
    "LOGIN_CARD_WIDTH",
    "AdminLoginScreen",
    "FatalStartupScreen",
    "FirstRunWizard",
    "SplashScreen",
]
