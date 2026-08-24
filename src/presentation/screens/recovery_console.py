r"""Gizli bərpa konsolu — ekran qatı (RECOVERY-1 Faza 2).

──────────────────────────────────────────────────────────────────────────────
BU EKRAN NƏ ÜÇÜNDÜR
──────────────────────────────────────────────────────────────────────────────
Baza əlçatmaz olanda müştəri SADƏ ekran görür: mesaj + «Yenidən Cəhd Et» +
dəstək ünvanı. Texnik isə `Ctrl+Shift+K` ilə bura düşür və burada nasazlığı
HƏLL ETMƏK üçün lazım olan hər şey var — sahələr, konkret xəta mesajları,
diaqnostika və «Bazanı Avtomatik Qur».

──────────────────────────────────────────────────────────────────────────────
SAHƏLƏR GENİŞDİR — SƏBƏBİ ÖLÇÜDƏDİR
──────────────────────────────────────────────────────────────────────────────
Supabase host adı ~40, `anon` açarı isə 200+ simvoldur. Dar sahədə texnik
yapışdırdığı dəyərin DOĞRU olub-olmadığını gözlə yoxlaya bilmir və səhv
yalnız «bağlantı alınmadı» kimi görünür. Ona görə kart 720px-dir və açar
sahələri tam eni tutur.

──────────────────────────────────────────────────────────────────────────────
EKRAN HEÇ NƏ HESABLAMIR
──────────────────────────────────────────────────────────────────────────────
`CLAUDE.md` §6: ekran yalnız `theme` alır və setter API-si təqdim edir.
Bağlantı testi, diaqnostika və quruluş kontrollerdədir — orada onlar FON
SAPINDA icra olunur, yəni bu ekran uzun əməliyyat boyu donmur.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.presentation.screens.base import Screen
from src.presentation.widgets import metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.forms import FormField
from src.presentation.widgets.primitives import (
    Card,
    body_label,
    muted_label,
    plain_label,
    section_label,
    stretch,
)

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager

#: Kartın eni — uzun açarlar üçün (bax modul başlığı).
CARD_WIDTH: Final = 720

#: Diaqnostika mətninin şrift ölçüsü — sıx, lakin oxunaqlı.
_DIAGNOSTIC_FONT_PX: Final = 11

PROVISION_WARNING: Final = (
    "«Bazanı Avtomatik Qur» YALNIZ KompasOS-un öz cədvəllərini yaradır. "
    "Supabase-in `auth`/`storage` sxemlərinə və sizin öz cədvəllərinizə "
    "TOXUNMUR."
)

ELEVATED_ACCESS_HINT: Final = (
    "Yalnız adi istifadəçinin cədvəl yaratmaq hüququ yoxdursa doldurun. "
    "Dəyər FAYLA YAZILMIR və düymə basılan kimi ekrandan silinir."
)


class RecoveryConsoleScreen(Screen):
    """`Ctrl+Shift+K` ilə açılan texniki konsol.

    Signals:
        test_requested: `dict` — bağlantı sahələri; nəticə `set_status`/
            `set_error` ilə qayıdır.
        save_requested: `dict` — eyni sahələr; `%PROGRAMDATA%`-ya yazılır.
        check_tables_requested: `dict` — çatışan cədvəlləri soruşur.
        provision_requested: `dict` — sahələr + `service_role` + təsdiq sözü.
        open_logs_requested / open_config_requested: Explorer-də qovluq açır.
        closed: Konsol bağlanır (Esc) — arxadakı ekran qayıdır.
    """

    test_requested = Signal(dict)
    save_requested = Signal(dict)
    check_tables_requested = Signal(dict)
    provision_requested = Signal(dict)
    open_logs_requested = Signal()
    open_config_requested = Signal()
    closed = Signal()

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)

        # Konsol uzundur (sahələr + diaqnostika + nəticə) və 800px-lik mağaza
        # ekranında sığmır — sürüşdürmə MƏCBURİDİR, əks halda «Bazanı Qur»
        # düyməsi görünməzdi.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        holder = QWidget()
        outer = QVBoxLayout(holder)
        outer.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        outer.setSpacing(metrics.CARD_SPACING)

        # Doldurma və aralıq `ConnectionSettingsScreen` ilə EYNİDİR: ikisi də
        # girişdən ƏVVƏL açılan kartdır və istifadəçi onlar arasında keçir —
        # fərqli doldurma kartın «tərpənməsi» kimi görünərdi
        # (`test_design_symmetry.py` səpələnməni ölçür).
        #
        # KÖLGƏ YOXDUR (VİZUAL FAZA #1, 4-cü bənd) — SƏBƏB UX-DİR, PERFORMANS
        # DEYİL: `QProgressBar.setValue()` baza quruluşu boyu təkrar-təkrar
        # çağırılır (aşağıda) və ölçüldü ki, İSTƏNİLƏN uşaq yeniləməsi
        # kölgəli kartın TAM yenidən rasterizəsini tətikləyir (hətta məzmun
        # dəyişməyən boş `update()` belə). Kart 916,560 px² sahədə 8.73 ms
        # rasterizə xərci daşıyır — 8.73 ms × 20–50 addım = 175–436 ms sırf
        # kölgəyə gedir. Bu ekranın BÜTÜN işi hamar tərəqqi göstərməkdir —
        # kölgə məhz yeganə geri-bildirimi kəkələdir. Nadir admin əməliyyatı
        # olması bunu dəyişmir: qərar YENƏ DƏ çıxarmaqdır.
        card = Card(padding=40, spacing=metrics.CARD_CONTENT_SPACING, surface="modal")
        card.setFixedWidth(CARD_WIDTH)

        heading = plain_label("Bərpa Konsolu")
        heading_font = heading.font()
        heading_font.setPixelSize(22)
        heading_font.setWeight(QFont.Weight.DemiBold)
        heading.setFont(heading_font)
        card.add(heading)

        card.add(
            body_label(
                "Bu ekran texniki dəstək üçündür. Dəyişikliklər "
                "«Yadda Saxla» basılana qədər tətbiq olunmur.",
                size=13,
            )
        )

        # ---------------------- NASAZLIĞIN SƏBƏBİ (yalnız xətada) ------------ #
        #
        # NİYƏ AYRICA ETİKET, `_status` DEYİL — `_status` KONSOLUN ÖZ
        # əməliyyatlarının nəticəsini daşıyır («Bağlantı uğurludur», «Parol boş
        # qalarsa dəyişmir»). Başlanğıc nasazlığının səbəbi isə konsol
        # AÇILMAMIŞDAN ƏVVƏLKİ faktdır: onu `_status`-a yazsaydıq ilk
        # «Bağlantını Test Et» basılışı səbəbi SİLƏRDİ və texnik nə üçün bura
        # düşdüyünü bir daha görə bilməzdi.
        #
        # NİYƏ GİZLİ BAŞLAYIR — konsol İŞLƏK maşında da açılır (`Root` +
        # `can_switch_db`): orada nasazlıq YOXDUR və boş qırmızı zolaq «nəsə
        # xarabdır» kimi oxunardı. Ona görə etiket YALNIZ səbəb VERİLDİKDƏ
        # görünür (`set_failure_reason`).
        self._failure = muted_label("")
        self._failure.setProperty("variant", "danger-text")
        self._failure.setWordWrap(True)
        # Səbəb mətnində SQLSTATE var — texnik onu dəstək zəngində oxuyur və
        # kopyalayır, yəni seçilə bilməlidir (diaqnostika blokundakı EYNİ qərar).
        self._failure.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self._failure.setVisible(False)
        card.add(self._failure)

        # ------------------------------ sahələr ------------------------------ #
        card.add(section_label("Bağlantı"))
        self._host = FormField(
            "Server ünvanı", placeholder="aws-0-eu-central-1.pooler.supabase.com"
        )
        self._port = FormField("Port", placeholder="5432")
        self._database = FormField("Baza adı", placeholder="postgres")
        self._username = FormField("İstifadəçi adı", placeholder="postgres.abcdefgh")
        self._password = FormField("Parol", password=True)
        self._tenant = FormField("Tenant ID", placeholder="UUID")
        self._supabase_url = FormField("Supabase URL", placeholder="https://<layihə>.supabase.co")
        self._anon_key = FormField("Anon açarı", placeholder="eyJhbGciOi…")
        for field in self._fields():
            card.add(field)

        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(metrics.SPACE_MS)
        self._test = secondary_button("Bağlantını Test Et")
        self._test.clicked.connect(lambda: self.test_requested.emit(self.values()))
        actions_layout.addWidget(self._test)
        self._check = secondary_button("Cədvəlləri Yoxla")
        self._check.clicked.connect(lambda: self.check_tables_requested.emit(self.values()))
        actions_layout.addWidget(self._check)
        actions_layout.addWidget(stretch())
        self._save = action_button("Yadda Saxla")
        self._save.clicked.connect(lambda: self.save_requested.emit(self.values()))
        actions_layout.addWidget(self._save)
        card.add(actions)

        self._status = muted_label("")
        self._status.setWordWrap(True)
        card.add(self._status)

        # --------------------------- avtomatik quruluş ----------------------- #
        card.add(section_label("Avtomatik baza quruluşu"))
        warning = muted_label(PROVISION_WARNING)
        warning.setWordWrap(True)
        card.add(warning)

        # SAHƏNİN ADI DÜRÜSTDÜR: Supabase-in `service_role` açarı PostgREST
        # üçün JWT-dir və birbaşa Postgres bağlantısı onu QƏBUL ETMİR —
        # DDL üçün baza istifadəçisi/parolu lazımdır (bax kontroller).
        self._service_role = FormField(
            "Quruluş üçün elevasiyalı parol (opsional)",
            password=True,
            hint=ELEVATED_ACCESS_HINT,
        )
        card.add(self._service_role)

        # Təsdiq sahəsi YALNIZ məlumatlı bazada görünür — həmişə göstərilsəydi,
        # texnik onu «adi bir xana» kimi doldurmağa alışardı və xəbərdarlıq
        # mənasını itirərdi.
        self._confirmation = FormField("Təsdiq", placeholder="Məlumatlı bazada «QUR» sözünü yazın")
        self._confirmation.setVisible(False)
        card.add(self._confirmation)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setTextVisible(True)
        card.add(self._progress)

        provision_row = QWidget()
        provision_layout = QHBoxLayout(provision_row)
        provision_layout.setContentsMargins(0, 0, 0, 0)
        provision_layout.setSpacing(metrics.SPACE_MS)
        provision_layout.addWidget(stretch())
        self._provision = action_button("Bazanı Avtomatik Qur")
        self._provision.clicked.connect(lambda: self.provision_requested.emit(self.values()))
        provision_layout.addWidget(self._provision)
        card.add(provision_row)

        # ------------------------------ diaqnostika -------------------------- #
        card.add(section_label("Diaqnostika"))
        self._diagnostics = muted_label("")
        self._diagnostics.setWordWrap(True)
        diagnostics_font = self._diagnostics.font()
        diagnostics_font.setPixelSize(_DIAGNOSTIC_FONT_PX)
        self._diagnostics.setFont(diagnostics_font)
        self._diagnostics.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        card.add(self._diagnostics)

        folders = QWidget()
        folders_layout = QHBoxLayout(folders)
        folders_layout.setContentsMargins(0, 0, 0, 0)
        folders_layout.setSpacing(metrics.SPACE_MS)
        self._open_logs = secondary_button("Log Faylını Aç")
        self._open_logs.clicked.connect(self.open_logs_requested)
        folders_layout.addWidget(self._open_logs)
        self._open_config = secondary_button("Config Qovluğunu Aç")
        self._open_config.clicked.connect(self.open_config_requested)
        folders_layout.addWidget(self._open_config)
        folders_layout.addWidget(stretch())
        self._close = secondary_button("Bağla")
        self._close.clicked.connect(self.closed)
        folders_layout.addWidget(self._close)
        card.add(folders)

        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignHCenter)
        scroll.setWidget(holder)
        self.body().addWidget(scroll)

    # ------------------------------- setter API ------------------------------ #

    def _fields(self) -> tuple[FormField, ...]:
        return (
            self._host,
            self._port,
            self._database,
            self._username,
            self._password,
            self._tenant,
            self._supabase_url,
            self._anon_key,
        )

    def values(self) -> dict[str, str]:
        """Sahələrin cari dəyərləri — siqnalla kontrollerə gedir."""
        return {
            "host": self._host.text().strip(),
            "port": self._port.text().strip(),
            "database": self._database.text().strip(),
            "username": self._username.text().strip(),
            "password": self._password.text(),
            "tenant_id": self._tenant.text().strip(),
            "supabase_url": self._supabase_url.text().strip(),
            "anon_key": self._anon_key.text().strip(),
            "service_role": self._service_role.text(),
            "confirmation": self._confirmation.text(),
        }

    def populate(self, settings: dict[str, object]) -> None:
        """Mövcud dəyərləri göstərir — PAROL İSTİSNA.

        Parol yüklənmir: onu ekrana çıxarmaq üçün deşifrələmək lazımdır və o
        vərdiş paylaşılan kompüterdə parolu çiynin üstündən oxunan hala
        gətirərdi (`ConnectionSettingsScreen`-dəki eyni qərar). Boş qalarsa
        mövcud parol saxlanılır.
        """
        self._host.set_text(str(settings.get("host", "")))
        self._port.set_text(str(settings.get("port", "") or ""))
        self._database.set_text(str(settings.get("database", "")))
        self._username.set_text(str(settings.get("username", "")))
        self._tenant.set_text(str(settings.get("tenant_id", "")))
        self._supabase_url.set_text(str(settings.get("supabase_url", "")))
        self._anon_key.set_text(str(settings.get("anon_key", "")))

    def set_diagnostics(self, rows: list[tuple[str, str]]) -> None:
        """Diaqnostika sətirləri — `(etiket, dəyər)` cütləri."""
        self._diagnostics.setText("\n".join(f"{label}: {value}" for label, value in rows))

    def set_failure_reason(self, message: str) -> None:
        """Başlanğıc nasazlığının SƏBƏBİ — BOŞ mətn etiketi gizlədir.

        Boş sətir «səbəb yoxdur» deməkdir: işlək maşında açılan konsol xəta
        zolağı GÖSTƏRMƏMƏLİDİR (bax konstruktordakı izah).
        """
        self._failure.setText(message)
        self._failure.setVisible(bool(message))

    def set_status(self, message: str) -> None:
        """Neytral vəziyyət mətni."""
        self._status.setText(message)

    def set_error(self, message: str) -> None:
        """Xəta mətni — konkret olmalıdır (bax kontroller)."""
        self._status.setText(message)

    def set_busy(self, busy: bool) -> None:
        """Uzun əməliyyat gedərkən düymələr bağlanır."""
        for button in (self._test, self._check, self._save, self._provision):
            button.setEnabled(not busy)

    def require_confirmation(self, required: bool) -> None:
        """Məlumatlı bazada təsdiq sahəsini AÇIR (bax sinif gövdəsi)."""
        self._confirmation.setVisible(required)
        if required:
            self._confirmation.focus_input()

    def set_progress(self, done: int, total: int, label: str = "") -> None:
        """«12/40 …» — quruluş gedişatı."""
        self._progress.setVisible(total > 0)
        self._progress.setMaximum(max(total, 1))
        self._progress.setValue(done)
        self._progress.setFormat(f"{done}/{total} {label}".strip())

    def clear_service_role(self) -> None:
        """`service_role` açarını EKRANDAN da silir.

        Yaddaşdan təmizləmək kifayət DEYİL: açar sahədə qalsaydı, texnik
        ekranı bağlamadan kənara getdikdə növbəti adam onu «göstər» düyməsi
        ilə oxuya bilərdi.
        """
        self._service_role.set_text("")

    def focus_first_field(self) -> None:
        self._host.focus_input()

    def keyPressEvent(self, event: object) -> None:  # noqa: N802 - Qt adlandırması
        """`Esc` konsolu bağlayır — qısayolla açılan ekran qısayolla da gedir."""
        key = getattr(event, "key", lambda: None)()
        if key == Qt.Key.Key_Escape:
            self.closed.emit()
            return
        super().keyPressEvent(event)  # type: ignore[arg-type]


__all__ = [
    "CARD_WIDTH",
    "ELEVATED_ACCESS_HINT",
    "PROVISION_WARNING",
    "RecoveryConsoleScreen",
]
