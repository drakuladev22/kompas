"""Qrup G — bildiriş mərkəzi və profil — Faza 4.2.

Maket: "KompasOS - Qrup G.dc.html", ekranlar 28–30.

    28  Boş / Yüklənmə / Xəta vəziyyətləri → `widgets/states.py` + `screens/base.py`
    29  Bildiriş Mərkəzi (header zəngindən açılan panel)
    30  Profil

28-ci ekran burada TƏKRAR OLUNMUR: o, ayrıca ekran deyil, bütün modullar üçün
ümumi qaydadır və `ContentSwitcher` şəklində artıq mexanizmə çevrilib (bax
`screens/base.py`). Onu buraya da köçürmək eyni davranışın iki mənbəsi
demək olardı.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.presentation.screens.base import Screen
from src.presentation.theme.manager import enable_styled_background, set_surface_color
from src.presentation.widgets import icons, metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.forms import FormField
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import (
    Avatar,
    Card,
    Chip,
    Divider,
    FilterChip,
    LinkLabel,
    StatusDot,
    body_label,
    is_activation_key,
    mono_label,
    muted_label,
    plain_label,
    section_label,
    stretch,
    title_label,
)

if TYPE_CHECKING:
    from PySide6.QtGui import QKeyEvent, QMouseEvent, QShowEvent

    from src.presentation.theme.manager import ThemeManager


# --------------------------------------------------------------------------- #
# 29 — Bildiriş Mərkəzi
# --------------------------------------------------------------------------- #

#: Bildiriş növü → (ikon, fon tokeni, ikon tokeni).
_NOTIFICATION_KINDS: Final[dict[str, tuple[str, str, str]]] = {
    "error": ("server_off", "--color-danger-bg", "--color-danger"),
    "warning": ("clock", "--color-warning-bg", "--color-warning"),
    "info": ("fine", "--color-info-bg", "--color-info"),
    "success": ("check", "--color-success-bg", "--color-success"),
    "system": ("database", "--color-neutral-bg", "--color-text-primary"),
}


class NotificationItem(QWidget):
    """Bir bildiriş sətri.

    Signals:
        clicked: `notification_id`.
    """

    clicked = Signal(str)

    def __init__(
        self,
        notification: dict[str, str],
        theme: ThemeManager,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._id = notification.get("id", "")
        unread = notification.get("unread") == "1"
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Sətir klik edilə bilir → klaviatura ilə də çatılmalıdır. Fokus
        # halqası QSS-dədir (`QWidget[variant="list-row"]:focus`), sərhədin
        # faktiki çəkilməsi üçün `WA_StyledBackground` lazımdır.
        self.setProperty("variant", "list-row")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        enable_styled_background(self)

        # Oxunmamış sətir bir ton fərqli fonda göstərilir və yanında amber
        # nöqtə olur. HƏR İKİSİ RƏNGDİR — yəni rəngi ayırd etməyən istifadəçi
        # üçün fərq yoxdur. Ona görə vəziyyət əlçatan ADA da yazılır: ekran
        # oxuyucusu sətri "… — oxunmamış" kimi elan edir. Vizual dizayn
        # dəyişmir, məlumat isə ikinci kanaldan da keçir.
        if unread:
            set_surface_color(self, theme.color("--color-neutral-bg"))
        title_text = notification.get("title", "")
        self.setAccessibleName(f"{title_text} — oxunmamış" if unread else title_text)
        self.setAccessibleDescription(notification.get("body", ""))

        layout = QHBoxLayout(self)
        # 20/14 əvəzinə 18/12 — fərq QSS-dəki 2px şəffaf fokus sərhədidir,
        # cəmi dəyişmir (bax `widgets/data_table.py`-dakı eyni naxış).
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(12)

        kind = notification.get("kind", "system")
        icon_name, background_token, icon_token = _NOTIFICATION_KINDS.get(
            kind, _NOTIFICATION_KINDS["system"]
        )

        glyph = plain_label()
        glyph.setFixedSize(30, 30)
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glyph.setPixmap(icons.render(icon_name, theme.color(icon_token), size=15, stroke_width=1.6))
        glyph.setStyleSheet(
            f"background-color: {theme.color(background_token)}; border-radius: 9px;"
        )
        layout.addWidget(glyph, alignment=Qt.AlignmentFlag.AlignTop)

        text_box = QWidget()
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        text_layout.addWidget(title_label(title_text, size=13))
        body = notification.get("body", "")
        if body:
            text_layout.addWidget(muted_label(body))
        text_layout.addWidget(mono_label(notification.get("time", ""), muted=True, size=11))
        layout.addWidget(text_box, 1)

        if unread:
            dot = StatusDot(theme.color("--color-brand-amber"))
            dot.setToolTip("Oxunmamış")
            dot.setAccessibleName("Oxunmamış")
            layout.addWidget(dot, alignment=Qt.AlignmentFlag.AlignTop)

    def _activate(self) -> None:
        # Siçan və klaviatura tək yoldan keçir — bax `primitives.FilterChip`.
        self.clicked.emit(self._id)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt adlandırması
        if event.button() is Qt.MouseButton.LeftButton:
            self._activate()
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt adlandırması
        if is_activation_key(event):
            self._activate()
            event.accept()
            return
        super().keyPressEvent(event)


class NotificationPanel(Card):
    """Header zəngindən açılan bildiriş paneli (420px).

    Signals:
        notification_clicked: `notification_id`.
        mark_all_read_requested: "Hamısını oxunmuş et".
        see_all_requested: "Bütün bildirişlərə bax".
        filter_changed: "all" / "approval" / "system".
    """

    notification_clicked = Signal(str)
    mark_all_read_requested = Signal()
    see_all_requested = Signal()
    filter_changed = Signal(str)

    _FILTERS: Final = (
        ("all", "Hamısı"),
        ("approval", "Təsdiq"),
        ("system", "Sistem"),
    )

    #: Maketdəki maksimum hündürlük.
    MAX_HEIGHT: Final = 620

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(padding=0, spacing=0, shadow=True, parent=parent)
        self._theme = theme
        self._active_filter = "all"
        self.setFixedWidth(metrics.NOTIFICATION_PANEL_WIDTH)
        self.setMaximumHeight(self.MAX_HEIGHT)

        # ------------------------------ başlıq ------------------------------ #
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 18, 20, 18)
        header_layout.setSpacing(12)
        header_layout.addWidget(title_label("Bildirişlər", size=15))

        self._unread_chip = Chip("", "warning")
        self._unread_chip.setVisible(False)
        header_layout.addWidget(self._unread_chip)
        header_layout.addWidget(stretch())

        mark_all = LinkLabel("Hamısını oxunmuş et")
        mark_all.clicked.connect(self.mark_all_read_requested)
        header_layout.addWidget(mark_all)
        self.add(header)

        # ------------------------------ süzgəc ------------------------------ #
        filters = QWidget()
        filters_layout = QHBoxLayout(filters)
        filters_layout.setContentsMargins(20, 12, 20, 12)
        filters_layout.setSpacing(8)
        self._filter_chips: dict[str, FilterChip] = {}
        for key, label in self._FILTERS:
            chip = FilterChip(key, label, "neutral")
            chip.clicked.connect(self.set_filter)
            self._filter_chips[key] = chip
            filters_layout.addWidget(chip)
        filters_layout.addStretch(1)
        self.add(filters)
        self.add(Divider())

        # ------------------------------ siyahı ------------------------------ #
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._list_host = QWidget()
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch(1)
        self._scroll.setWidget(self._list_host)
        self.body().addWidget(self._scroll, 1)

        self.add(Divider())

        # ------------------------------- altlıq ----------------------------- #
        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(20, 14, 20, 14)
        footer_layout.setSpacing(12)

        see_all = LinkLabel("Bütün bildirişlərə bax")
        see_all.clicked.connect(self.see_all_requested)
        footer_layout.addWidget(see_all)
        footer_layout.addWidget(stretch())
        footer_layout.addWidget(muted_label("30 gün saxlanılır"))
        self.add(footer)

        #: Sonuncu doldurulmuş dəst — süzgəc dəyişəndə yenidən süzülür.
        #: `set_filter` aşağıda çağırıldığı üçün BU SƏTİR ondan əvvəl olmalıdır.
        self._notifications: list[dict[str, str]] = []

        self.set_filter("all")

    # ------------------------------- məzmun ---------------------------------- #

    def set_notifications(self, notifications: list[dict[str, str]]) -> None:
        # DƏST ƏVVƏLCƏ SAXLANILIR: əvvəllər bu sətir metodun SONUNDA idi və
        # "görünən bildiriş yoxdur" halında `return` ona çatmırdı — yəni boş
        # nəticə verən bir süzgəcdən sonra keş köhnə qalır, «Hamısı»na qayıdış
        # isə əvvəlki dəsti göstərərdi.
        self._notifications = list(notifications)
        clear_layout(self._list_layout, keep_last=1)

        unread = sum(1 for n in notifications if n.get("unread") == "1")
        self._unread_chip.setText(f"{unread} yeni")
        self._unread_chip.setVisible(unread > 0)

        visible = [n for n in notifications if self._matches(n)]

        if not visible:
            empty = muted_label("Bildiriş yoxdur.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setContentsMargins(20, 40, 20, 40)
            self._list_layout.insertWidget(0, empty)
            return

        for index, notification in enumerate(visible):
            if index:
                self._list_layout.insertWidget(self._list_layout.count() - 1, Divider())
            item = NotificationItem(notification, self._theme)
            item.clicked.connect(self.notification_clicked)
            self._list_layout.insertWidget(self._list_layout.count() - 1, item)

    def _matches(self, notification: dict[str, str]) -> bool:
        if self._active_filter == "all":
            return True
        return notification.get("category", "system") == self._active_filter

    def set_filter(self, key: str) -> None:
        """Süzgəci dəyişir və SİYAHINI yenidən qurur.

        Çipin rəngini dəyişib siyahını olduğu kimi saxlamaq ən aldadıcı
        formadır: istifadəçi «Cərimə» çipini seçir, ekranda isə sistem
        bildirişləri qalır — o, bunu süzgəcin nəticəsi sayır və "cərimə
        bildirişi yoxdur" qənaətinə gəlir. `filter_changed` siqnalını heç bir
        kontroller dinləmirdi, yəni süzgəc heç bir yerdə tətbiq olunmurdu.
        """
        self._active_filter = key
        for chip_key, chip in self._filter_chips.items():
            chip.set_tone("info" if chip_key == key else "neutral")
        self.set_notifications(list(self._notifications))
        self.filter_changed.emit(key)

    @property
    def active_filter(self) -> str:
        return self._active_filter


# --------------------------------------------------------------------------- #
# 30 — Profil
# --------------------------------------------------------------------------- #


class ProfileScreen(Screen):
    """Şəxsi məlumat, sessiya tarixçəsi, rol/səlahiyyət və təhlükəsizlik.

    Signals:
        saved: Dəyişdirilə bilən sahələr.
        photo_change_requested / password_change_requested: düymələr.
        close_other_sessions_requested: "Digər sessiyaları bağla".

    ──────────────────────────────────────────────────────────────────────
    İSTİFADƏÇİ ADI VƏ E-POÇT NİYƏ SÖNÜLÜDÜR
    ──────────────────────────────────────────────────────────────────────
    Hər ikisi identifikasiya vasitəsidir: istifadəçi adı giriş açarıdır,
    e-poçt isə hesabın bərpa kanalı. İstifadəçinin özünə dəyişməyə icazə
    versək, ələ keçirilmiş sessiya hesabı tamamilə ötürə bilərdi.

    Sahələr GİZLƏDİLMİR, söndürülür — istifadəçi öz dəyərini görməlidir
    (dəstəyə müraciət edərkən lazım olur); maket də bunu altdakı qeydlə
    izah edir.
    """

    saved = Signal(dict)
    photo_change_requested = Signal()
    password_change_requested = Signal()
    close_other_sessions_requested = Signal()

    def __init__(
        self,
        theme: ThemeManager,
        *,
        full_name: str,
        role_name: str,
        store_name: str,
        member_since: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(theme, parent=parent)

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(12)
        toolbar_layout.addWidget(stretch())
        cancel = secondary_button("Ləğv Et")
        # DÜYMƏ ƏVVƏL HEÇ NƏYƏ BAĞLI DEYİLDİ: istifadəçi adını səhv yazıb
        # «Ləğv Et» basırdı, sahələr olduğu kimi qalırdı və o, dəyişikliyin
        # ATILDIĞINI sanırdı — sonra «Yadda Saxla» basanda SƏHV ad yazılırdı.
        # Ləğv YALNIZ EKRAN əməliyyatıdır (bazaya heç nə getməmişdi), ona görə
        # kontroller lazım deyil: sahələr son YÜKLƏNMİŞ dəyərlərə qayıdır.
        cancel.clicked.connect(self.revert_edits)
        toolbar_layout.addWidget(cancel)
        save = action_button("Yadda Saxla")
        save.clicked.connect(lambda: self.saved.emit(self.collected()))
        toolbar_layout.addWidget(save)
        self.add(toolbar)

        self.add(self._build_identity(full_name, role_name, store_name, member_since))

        columns = QWidget()
        columns_layout = QHBoxLayout(columns)
        columns_layout.setContentsMargins(0, 0, 0, 0)
        columns_layout.setSpacing(metrics.CARD_SPACING)
        # Dar pəncərədə iki sütun bir-birinin altına düşür — bax
        # `screens/base.py::responsive_row`.
        self.responsive_row(columns_layout)
        columns_layout.addWidget(self._build_personal(full_name), 1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(metrics.CARD_SPACING)
        right_layout.addWidget(self._build_role_card())
        right_layout.addWidget(self._build_sessions_card())
        right_layout.addWidget(self._build_security_card())
        # facecontrol.md bənd 13 — «Üz qeydiyyatı» kartı TƏHLÜKƏSİZLİK
        # bölməsindən dərhal sonra durur: hər ikisi hesabın kimliyini qoruyan
        # mexanizmdir (biri «bilirsən», digəri «kimsən») və eyni ritmdə
        # baxılır.
        right_layout.addWidget(self._build_face_card())
        right_layout.addStretch(1)
        columns_layout.addWidget(right, 1)

        self.add(columns)
        # #20 Performans Qiymətləndirməsi (kompasos11.md Faza 8) — TAM ENLİ:
        # notlar uzun ola bilər, iki sütunlu kartda hər sətir kəsilərdi.
        self.add(self._build_performance_card())
        self.body().addStretch(1)

        # Zəncir bütün kartlar qurulduqdan SONRA verilir. Sıra REDAKTƏ EDİLƏ
        # BİLƏN sahələrdən keçir və söndürülmüş «İstifadəçi adı» / «E-poçt»
        # sahələrini ATLAYIR — Qt onları onsuz da keçir, lakin zənciri açıq
        # yazmaq sıranı vizual sıraya bağlayır (ad → telefon → yadda saxla).
        QWidget.setTabOrder(self._full_name.input_widget(), self._phone.input_widget())
        QWidget.setTabOrder(self._phone.input_widget(), cancel)
        QWidget.setTabOrder(cancel, save)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt adlandırması
        """Fokus ilk REDAKTƏ EDİLƏ BİLƏN sahəyə («Ad, Soyad») qoyulur.

        Yuxarıdakı alət zolağındakı «Yadda Saxla» vizual olaraq birincidir,
        lakin məntiqi ilk addım DEYİL: forma doldurulmamış saxlamaq mənasızdır.
        Fokusun sahədə başlaması siçansız istifadəçiyə düymələri geri
        keçməyə (Shift+Tab) məcbur etmir.
        """
        super().showEvent(event)
        self._full_name.focus_input()

    def _build_identity(
        self, full_name: str, role_name: str, store_name: str, member_since: str
    ) -> Card:
        card = Card(padding=metrics.CARD_PADDING, spacing=0)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self._avatar = Avatar(
            full_name,
            background=self.theme.color("--color-neutral-bg"),
            foreground=self.theme.color("--color-text-primary"),
            size=72,
        )
        layout.addWidget(self._avatar)

        text_box = QWidget()
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        text_layout.addWidget(title_label(full_name, size=22))
        text_layout.addWidget(muted_label(f"{role_name} · {store_name} · {member_since}", size=13))
        layout.addWidget(text_box)
        layout.addWidget(stretch())

        change = secondary_button("Şəkli Dəyiş")
        change.clicked.connect(self.photo_change_requested)
        layout.addWidget(change)

        card.add(row)
        return card

    def _build_personal(self, full_name: str) -> Card:
        card = Card(padding=metrics.CARD_PADDING, spacing=16)
        # Maketdə kart bölmə başlığı 15px başlıq DEYİL — 12px böyük hərfli
        # mono etiketdir (`letter-spacing: 0.1em`, solğun rəng).
        card.add(section_label("Şəxsi məlumat"))

        self._full_name = FormField("Ad, Soyad")
        self._full_name.set_text(full_name)
        #: «Ləğv Et»-in qaytaracağı dəyərlər — son YÜKLƏNMİŞ vəziyyət.
        self._loaded = {"full_name": full_name, "phone": ""}
        card.add(self._full_name)

        self._username = FormField("İstifadəçi adı")
        self._username.input_widget().setEnabled(False)
        card.add(self._username)

        self._phone = FormField("Telefon")
        card.add(self._phone)

        self._email = FormField("E-poçt (qeydiyyat)")
        self._email.input_widget().setEnabled(False)
        card.add(self._email)

        card.add(muted_label("İstifadəçi adı və e-poçt yalnız Admin tərəfindən dəyişdirilir."))
        return card

    def _build_role_card(self) -> Card:
        card = Card(padding=metrics.CARD_PADDING, spacing=12)
        card.add(title_label("Rol və səlahiyyət", size=15))
        self._role_rows = QVBoxLayout()
        self._role_rows.setSpacing(12)
        holder = QWidget()
        holder.setLayout(self._role_rows)
        card.add(holder)
        return card

    def _build_sessions_card(self) -> Card:
        card = Card(padding=metrics.CARD_PADDING, spacing=12)
        card.add(section_label("Son giriş tarixçəsi"))
        self._session_rows = QVBoxLayout()
        self._session_rows.setSpacing(12)
        holder = QWidget()
        holder.setLayout(self._session_rows)
        card.add(holder)
        return card

    def _build_security_card(self) -> Card:
        card = Card(padding=metrics.CARD_PADDING, spacing=12)
        card.add(title_label("Təhlükəsizlik", size=15))

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)

        change = secondary_button("Şifrəni Dəyiş")
        change.clicked.connect(self.password_change_requested)
        buttons_layout.addWidget(change)

        close_sessions = secondary_button("Digər sessiyaları bağla")
        close_sessions.clicked.connect(self.close_other_sessions_requested)
        buttons_layout.addWidget(close_sessions)
        buttons_layout.addStretch(1)
        card.add(buttons)

        self._password_note = muted_label("")
        card.add(self._password_note)
        return card

    # ------------------------- üz qeydiyyatı (bənd 13) ------------------------ #

    def _build_face_card(self) -> Card:
        """«Üz qeydiyyatı» — DÖVRİ YENİLƏMƏ TÖVSİYƏSİ, bloklama YOX.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ BURADA MƏCBURİYYƏT YOXDUR
        ──────────────────────────────────────────────────────────────────────
        `facecontrol.md` bənd 13 açıq deyir: «Bu, MƏCBURİ BLOKLAMA YARATMIR,
        yalnız admin üçün görünən tövsiyədir». İnsan üzü zamanla dəyişir
        (saqqal, eynək, çəki) və köhnə vektor tanınma dəqiqliyini AZALDIR —
        lakin işçini işə buraxmamaq üçün əsas deyil (`MonthlyLeaveUsage` ilə
        eyni fəlsəfə: xəbərdarlıq göstərilir, iş davam edir).

        Ona görə burada nə düymə, nə qadağa var — yalnız vəziyyət və tarix.
        Yeniləmə isə NƏZARƏTLİ prosesdir və AYRI ekrandadır («Üz Qeydiyyatı»,
        `can_manage_employees`): işçi öz üzünü özü yeniləyə bilməz (bənd 1).
        """
        card = Card(padding=metrics.CARD_PADDING, spacing=12)
        card.add(section_label("Üz qeydiyyatı"))

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self._face_chip = Chip("Qeydiyyatsız", "neutral")
        layout.addWidget(self._face_chip)
        self._face_enrolled_at = mono_label("")
        layout.addWidget(self._face_enrolled_at)
        layout.addWidget(stretch())
        card.add(row)

        self._face_note = body_label("", size=12)
        card.add(self._face_note)
        return card

    def set_face_enrollment(self, enrollment: dict[str, str]) -> None:
        """Üz qeydiyyatının vəziyyəti (bənd 13).

        Args:
            enrollment: `state` (`NEW` / `ENROLLED` / `STALE`), `enrolled_at`,
                `reminder_months` açarları. Açarlar HƏM maket
                (`preview_data.FACE_PROFILE_ENROLLMENT`), HƏM canlı yol
                (`controllers/profile.py::_face_enrollment_row`) üçün EYNİDİR
                (CLAUDE.md §6). `state` dəyərləri `controllers/face_control.py::
                enrollment_state` ilə eynidir — ekran öz ad məkanını qurmur.

        BOŞ SÖZLÜK NORMAL HALDIR: Face Control modulu söndürülübsə və ya
        məlumat oxuna bilmirsə kart neytral vəziyyətdə qalır və heç bir
        xəbərdarlıq göstərmir — yalançı xəbərdarlıq həqiqi olanı dəyərsizləşdirir.
        """
        state = enrollment.get("state", "")
        enrolled_at = enrollment.get("enrolled_at", "")
        months = enrollment.get("reminder_months", "")

        if state == "STALE":
            self._face_chip.setText("Köhnəlib")
            self._face_chip.set_tone("warning")
            self._face_note.setText(
                f"Üz qeydiyyatı köhnəlib, yenilənməsi tövsiyə olunur ({months} aydan "
                f"köhnədir). Bu, girişinizi BLOKLAMIR — yeniləmə «Üz Qeydiyyatı» "
                f"ekranından administrator tərəfindən aparılır."
            )
        elif state == "ENROLLED":
            self._face_chip.setText("Qeydiyyatlı")
            self._face_chip.set_tone("success")
            self._face_note.setText(
                f"Qeydiyyat qüvvədədir. Tövsiyə olunan yeniləmə intervalı: {months} ay."
            )
        elif state == "NEW":
            self._face_chip.setText("Qeydiyyatsız")
            self._face_chip.set_tone("neutral")
            self._face_note.setText(
                "Üz qeydiyyatı aparılmayıb. Qeydiyyatı administrator aparır — "
                "işçi bunu özü edə bilmir."
            )
        else:
            self._face_chip.setText("Məlumat yoxdur")
            self._face_chip.set_tone("neutral")
            self._face_note.setText("")

        self._face_enrolled_at.setText(enrolled_at or "—")

    # ------------------------ performans tarixçəsi (#20) ---------------------- #

    def _build_performance_card(self) -> Card:
        """ "Performans Tarixçəm" — #20 (kompasos11.md Faza 8).

        SƏLAHİYYƏT/DÜYMƏ YOXDUR: bu, TAMAMİLƏ OXU kartıdır (qiymətləndirməni
        yalnız `can_conduct_performance_review` sahibi ayrıca ekrandan yazır,
        bax `screens/performance_review.py`). Cavab/etiraz sahəsi YOXDUR —
        performans qiyməti dəstək çatı deyil, birtərəfli qeyddir.
        """
        card = Card(padding=metrics.CARD_PADDING, spacing=12)
        card.add(section_label("Performans Tarixçəm"))

        self._performance_rows = QVBoxLayout()
        self._performance_rows.setSpacing(16)
        holder = QWidget()
        holder.setLayout(self._performance_rows)
        card.add(holder)

        self._performance_empty = muted_label("Hələ heç bir qiymətləndirmə yazılmayıb.")
        card.add(self._performance_empty)
        return card

    def set_performance_history(self, rows: list[dict[str, str]]) -> None:
        """Qiymətləndirmə tarixçəsini göstərir (#20).

        Args:
            rows: `period`, `overall_score`, `reviewer`, `notes`, `ratings_text`
                açarları olan sözlüklər — ən yeni dövr ƏVVƏLDƏ. Açarlar maket
                (`preview_screens._profile`) və canlı yolda (`controllers/
                profile.py`) EYNİDİR (CLAUDE.md §6).
        """
        clear_layout(self._performance_rows)
        self._performance_empty.setVisible(not rows)

        for row in rows:
            self._performance_rows.addWidget(self._build_performance_row(row))

    def _build_performance_row(self, row: dict[str, str]) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(12)
        head_layout.addWidget(title_label(row.get("period", ""), size=14))
        head_layout.addWidget(stretch())
        score_text = row.get("overall_score", "")
        if score_text:
            head_layout.addWidget(Chip(f"{score_text} xal", "info"))
        layout.addWidget(head)

        reviewer = row.get("reviewer", "")
        if reviewer:
            layout.addWidget(muted_label(f"Qiymətləndirən: {reviewer}", size=12))

        ratings_text = row.get("ratings_text", "")
        if ratings_text:
            layout.addWidget(body_label(ratings_text, size=12))

        notes = row.get("notes", "")
        if notes:
            layout.addWidget(body_label(notes, size=12))

        return container

    # ------------------------------- doldurma -------------------------------- #

    def set_account(
        self,
        *,
        username: str,
        email: str,
        phone: str = "",
        password_note: str = "",
    ) -> None:
        self._username.set_text(username)
        self._email.set_text(email)
        self._phone.set_text(phone)
        self._password_note.setText(password_note)
        # Yükləmə vəziyyəti YENİLƏNİR: «Ləğv Et» ekranın İLK açılışına deyil,
        # SON oxunmuş məlumata qaytarmalıdır (yazıdan sonra kontroller
        # `refresh()` çağırır və dəyərlər dəyişir).
        self._loaded["phone"] = phone
        self.show_content()

    def set_role_info(self, rows: list[tuple[str, str]]) -> None:
        self._fill(self._role_rows, rows)

    def set_sessions(self, sessions: list[tuple[str, str, str]]) -> None:
        """`sessions`: (vaxt, cihaz, vəziyyət)."""
        clear_layout(self._session_rows)

        for time_text, device, state in sessions:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)
            layout.addWidget(mono_label(time_text))
            layout.addWidget(body_label(device, size=13, wrap=False))
            layout.addWidget(stretch())
            active = state == "Aktiv sessiya"
            layout.addWidget(Chip(state, "success" if active else "neutral"))
            self._session_rows.addWidget(row)

    def _fill(self, layout: QVBoxLayout, rows: list[tuple[str, str]]) -> None:
        clear_layout(layout)

        for name, value in rows:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(12)
            row_layout.addWidget(muted_label(name))
            row_layout.addWidget(stretch())
            row_layout.addWidget(body_label(value, size=13, wrap=False))
            layout.addWidget(row)

    def set_identity(self, full_name: str) -> None:
        """Ad sahəsini yeniləyir — `set_account` ilə eyni «yüklənmiş» qeydə düşür."""
        self._full_name.set_text(full_name)
        self._loaded["full_name"] = full_name

    def revert_edits(self) -> None:
        """«Ləğv Et» — sahələr son yüklənmiş dəyərlərə qayıdır.

        Bazaya HEÇ NƏ göndərilmir, çünki hələ göndərilməmişdi: bu ekranda
        «Yadda Saxla» basılmayıbsa yazı da baş verməyib. Ona görə ləğv
        kontroller tələb etmir — ekranın öz vəziyyətinin bərpasıdır.
        """
        self._full_name.set_text(self._loaded["full_name"])
        self._phone.set_text(self._loaded["phone"])

    def collected(self) -> dict[str, str]:
        """Yalnız DƏYİŞDİRİLƏ BİLƏN sahələr qaytarılır."""
        return {
            "full_name": self._full_name.text(),
            "phone": self._phone.text(),
        }


__all__ = ["NotificationItem", "NotificationPanel", "ProfileScreen"]
