"""Cihaz idarəetməsi və gözləmə ekranları (DEVICE-1, Faza 2.2 + Faza 4).

──────────────────────────────────────────────────────────────────────────────
İKİ EKRAN, BİR FAYL — NİYƏ
──────────────────────────────────────────────────────────────────────────────
`DevicePendingScreen` (cihaz özü görür) və `DeviceAdminScreen` (admin görür)
EYNİ axının iki ucudur: birinin göstərdiyi qısa kod digərinin axtardığı
açardır. Ayrı fayllara bölsəydik, kodun formatı və mətn dili iki yerdə
saxlanılardı və biri dəyişəndə digəri sükutla köhnələrdi — layihədə
`menu.py` başlığında sənədləşdirilmiş «ad məkanı ayrılması» qüsurunun eyni
forması.

──────────────────────────────────────────────────────────────────────────────
GÖZLƏMƏ EKRANI KOD-MƏRKƏZLİDİR
──────────────────────────────────────────────────────────────────────────────
Ekranın YEGANƏ vəzifəsi: mağaza işçisi telefonla admin-ə bir kod desin. Ona
görə kod ekranın mərkəzində, ən böyük şriftlə və hərflər arası boşluqla
yazılır — qalan hər şey (izah, maşın adı) ondan kiçikdir. Tam UUID
GÖSTƏRİLMİR: 36 simvollu sətri telefonla söyləmək praktiki olaraq mümkün
deyil və səhv eşidilən bir simvol admini BAŞQA cihazı təsdiqləməyə aparardı.

──────────────────────────────────────────────────────────────────────────────
«YENİLƏ» DÜYMƏSİ VAR, AVTOMATİK POLLING YOXDUR
──────────────────────────────────────────────────────────────────────────────
Cihaz təsdiq gözləyərkən bazaya hər saniyə sorğu göndərmək mənasızdır: təsdiq
insan əməliyyatıdır və dəqiqələrlə ölçülür. Üstəlik təsdiqlənməmiş cihaz
lisenziyasız vəziyyətdədir — onun fasiləsiz sorğu göndərməsi «qeydiyyatsız
cihaz serveri yükləyir» deməkdir. İşçi admin ilə telefonda danışdıqdan sonra
düyməni basır; bu, gözləntiyə uyğundur.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from src.domain.value_objects.devices import DeviceStatus, DeviceType
from src.presentation.screens.base import Screen
from src.presentation.widgets import metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.data_table import Column, DataTable
from src.presentation.widgets.forms import field_label
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import (
    Card,
    Chip,
    ChipTone,
    body_label,
    muted_label,
    plain_label,
    section_label,
    stretch,
    title_label,
)

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager

# --------------------------------------------------------------------------- #
# Mətnlər — İKİ ekran arasında paylaşılır (bax modul başlığı)
# --------------------------------------------------------------------------- #

PENDING_TITLE: Final = "Bu cihaz hələ təsdiqlənməyib"
PENDING_INTRO: Final = (
    "Proqramın işləməsi üçün bu kompüter administrator tərəfindən təsdiqlənməli "
    "və bir filiala təyin edilməlidir."
)
PENDING_INSTRUCTION: Final = "Administratorunuza zəng edin və aşağıdakı kodu bildirin:"
PENDING_AFTER: Final = (
    "Təsdiqdən sonra «Yenidən Yoxla» düyməsini basın. Kod bu kompüterə aiddir və dəyişmir."
)

BLOCKED_TITLE: Final = "Bu cihaz bloklanıb"
BLOCKED_INTRO: Final = (
    "Kompüter administrator tərəfindən bloklanıb və ya uzun müddət istifadə "
    "olunmadığı üçün avtomatik sıradan çıxarılıb."
)

ADMIN_EMPTY_TITLE: Final = "Qeydiyyatdan keçmiş cihaz yoxdur"
ADMIN_EMPTY_MESSAGE: Final = (
    "Hər kompüter ilk açılışda özünü qeydiyyata salır və burada görünür. "
    "Siyahı boşdursa, heç bir kompüter hələ bu bazaya qoşulmayıb."
)

#: Cihaz tiplərinin Azərbaycanca adları (bölmə 9: yeganə interfeys dili).
#: Enum dəyərlərinin ÖZÜ identifikatordur və tərcümə OLUNMUR — bax
#: `sync_conflicts.py` başlığındakı eyni qərar.
DEVICE_TYPE_LABELS: Final[dict[DeviceType, str]] = {
    DeviceType.KIOSK: "Kiosk (işçi girişi)",
    DeviceType.ADMIN_PC: "İdarə kompüteri",
    DeviceType.CAMERA_OPERATOR: "Kamera operatoru",
}

STATUS_LABELS: Final[dict[DeviceStatus, str]] = {
    DeviceStatus.PENDING_APPROVAL: "Təsdiq gözləyir",
    DeviceStatus.ACTIVE: "Aktiv",
    DeviceStatus.BLOCKED: "Bloklanıb",
}

#: Status → `Chip` tonu. Gözləyən sətir NEYTRAL tonda qalır, xəbərdarlıq
#: tonunda YOX: təsdiq gözləmək normal iş axınıdır, nasazlıq deyil — sarı
#: rəng adminə hər yeni cihazı problem kimi göstərərdi.
STATUS_TONES: Final[dict[DeviceStatus, ChipTone]] = {
    DeviceStatus.PENDING_APPROVAL: "info",
    DeviceStatus.ACTIVE: "success",
    DeviceStatus.BLOCKED: "danger",
}

#: Qısa kodun ekrandakı ölçüsü — telefonla oxumaq üçün qəsdən böyükdür.
_CODE_FONT_PX: Final = 44
_CODE_LETTER_SPACING: Final = 6.0


def _tone_of(raw: object) -> ChipTone:
    """Status dəyəri → `Chip` tonu; tanınmayan dəyər neytral qalır."""
    try:
        return STATUS_TONES[DeviceStatus(str(raw))]
    except ValueError:
        return "neutral"


def status_label(status: DeviceStatus) -> str:
    """Status → istifadəçi mətni. İki ekran da bunu işlədir."""
    return STATUS_LABELS.get(status, status.value)


def device_type_label(device_type: DeviceType) -> str:
    return DEVICE_TYPE_LABELS.get(device_type, device_type.value)


class DevicePendingScreen(Screen):
    """Təsdiq gözləyən (və ya bloklanmış) cihazın gördüyü tam-ekran mane.

    Signals:
        recheck_requested: «Yenidən Yoxla» — vəziyyəti təzədən oxuyur.
    """

    recheck_requested = Signal()

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.setSpacing(0)
        layout.addStretch(1)

        card = Card()
        body = card.body()
        body.setSpacing(metrics.CARD_SPACING)

        self._title = title_label(PENDING_TITLE)
        body.addWidget(self._title)

        self._intro = body_label(PENDING_INTRO)
        body.addWidget(self._intro)

        self._instruction = body_label(PENDING_INSTRUCTION)
        body.addWidget(self._instruction)

        # Kod monoaralıqlı DEYİL, adi şriftlə böyük yazılır: monoaralıqlı
        # şrift «texniki dəyər» siqnalı verir, halbuki bu kod məhz İNSANIN
        # oxuyub səsləndirməsi üçündür. Hərf aralığı isə məcburidir —
        # bitişik simvollar telefonla diktə edilərkən qarışır.
        self._code = plain_label("")
        self._code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        code_font = self._code.font()
        code_font.setPixelSize(_CODE_FONT_PX)
        code_font.setWeight(QFont.Weight.Bold)
        code_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, _CODE_LETTER_SPACING)
        self._code.setFont(code_font)
        body.addWidget(self._code)

        self._machine = muted_label("")
        body.addWidget(self._machine)

        self._after = muted_label(PENDING_AFTER)
        self._after.setWordWrap(True)
        body.addWidget(self._after)

        actions = QHBoxLayout()
        actions.addWidget(stretch())
        self._recheck = action_button("Yenidən Yoxla")
        self._recheck.clicked.connect(self.recheck_requested)
        actions.addWidget(self._recheck)
        body.addLayout(actions)

        layout.addWidget(card)
        layout.addStretch(1)

    # ------------------------------- setter API ------------------------------ #

    def set_device(self, *, short_code: str, machine_name: str, status: DeviceStatus) -> None:
        """Ekranı cihazın vəziyyətinə görə qurur."""
        blocked = status is DeviceStatus.BLOCKED
        self._title.setText(BLOCKED_TITLE if blocked else PENDING_TITLE)
        self._intro.setText(BLOCKED_INTRO if blocked else PENDING_INTRO)
        # Bloklanmış cihazda kod GÖSTƏRİLMİR: kod «məni təsdiqlə» çağırışıdır,
        # bloklanmış cihaz isə təsdiq gözləmir — onu göstərmək istifadəçini
        # nəticəsiz zəngə göndərərdi.
        self._instruction.setVisible(not blocked)
        self._code.setVisible(not blocked)
        self._code.setText(short_code if not blocked else "")
        self._after.setVisible(not blocked)
        self._machine.setText(f"Kompüter: {machine_name}" if machine_name else "")

    def set_busy(self, busy: bool) -> None:
        """Yoxlama gedərkən düyməni deaktiv edir — ikiqat sorğu olmasın."""
        self._recheck.setEnabled(not busy)
        self._recheck.setText("Yoxlanılır…" if busy else "Yenidən Yoxla")


class DeviceAdminScreen(Screen):
    """«Cihazlar» — təsdiq növbəsi, siyahı və lisenziya sayğacı.

    Signals:
        approve_requested: `dict` (`device_id`, `store_id`, `device_name`,
            `device_type`).
        block_requested: `device_id`.
        reactivate_requested: `device_id`.
        reassign_requested: `dict` (`device_id`, `store_id`).
        refresh_requested: siyahını təzədən oxu.
    """

    approve_requested = Signal(dict)
    block_requested = Signal(str)
    reactivate_requested = Signal(str)
    reassign_requested = Signal(dict)
    refresh_requested = Signal()

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)
        self._stores: list[tuple[str, str]] = []
        self._selected_id = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(metrics.CARD_SPACING)

        header = QHBoxLayout()
        header.addWidget(title_label("Cihazlar"))
        header.addWidget(stretch())
        # Lisenziya sayğacı BAŞLIQDA, cədvəlin altında deyil: admin yeni cihaz
        # təsdiqləməzdən ƏVVƏL yer olub-olmadığını bilməlidir, sonra deyil.
        self._usage = Chip("", tone="info")
        header.addWidget(self._usage)
        refresh = secondary_button("Yenilə")
        refresh.clicked.connect(self.refresh_requested)
        header.addWidget(refresh)
        layout.addLayout(header)

        # --- Təsdiq növbəsi (diqqət çəkən bölmə) ---------------------------
        self._pending_card = Card()
        pending_body = self._pending_card.body()
        pending_body.setSpacing(12)
        self._pending_heading = section_label("Təsdiq gözləyənlər")
        pending_body.addWidget(self._pending_heading)
        self._pending_rows = QVBoxLayout()
        self._pending_rows.setSpacing(12)
        pending_body.addLayout(self._pending_rows)
        layout.addWidget(self._pending_card)

        # --- Tam siyahı -----------------------------------------------------
        self._table = DataTable(
            [
                Column("Cihaz"),
                Column("Filial", 200),
                Column("Tip", 170),
                Column("Vəziyyət", 140),
                Column("Son görünmə", 150, mono=True),
                Column("Əməliyyat", 260),
            ],
            theme,
        )
        layout.addWidget(self._table)

        self._empty = muted_label(ADMIN_EMPTY_MESSAGE)
        self._empty.setWordWrap(True)
        self._empty.setVisible(False)
        layout.addWidget(self._empty)

    # ------------------------------- setter API ------------------------------ #

    def set_stores(self, stores: list[tuple[str, str]]) -> None:
        """`(store_id, ad)` cütləri — təsdiq sətrindəki seçim üçün."""
        self._stores = list(stores)

    def set_usage(self, text: str) -> None:
        """«12 / 25 cihaz istifadə olunur»."""
        self._usage.setText(text)

    def set_pending(self, devices: list[dict[str, object]]) -> None:
        """Təsdiq gözləyən cihazlar — hər biri öz təsdiq forması ilə."""
        clear_layout(self._pending_rows)
        if not devices:
            # Bölmə tamamilə GİZLƏNİR, boş qalmır: «0 gözləyən» yazısı hər
            # açılışda yer tutar və gözü heç nəyə yönəltməzdi.
            self._pending_card.setVisible(False)
            return
        self._pending_card.setVisible(True)
        self._pending_heading.setText(f"Təsdiq gözləyənlər ({len(devices)})")
        for device in devices:
            self._pending_rows.addWidget(self._build_pending_row(device))

    def set_devices(self, devices: list[dict[str, object]]) -> None:
        """Tam siyahı."""
        self._table.clear()
        for device in devices:
            status = device.get("status")
            # `Chip` tonu `Literal`-dir; sözlükdən gələn sətri birbaşa
            # ötürmək tip zəmanətini itirərdi — açar KATALOQDAN həll olunur.
            chip = Chip(
                str(device.get("status_label", "")),
                tone=_tone_of(device.get("status")),
            )
            self._table.add_row(
                [
                    str(device.get("name", "")),
                    str(device.get("store", "—")),
                    str(device.get("type", "")),
                    chip,
                    str(device.get("last_seen", "—")),
                    self._build_actions(device),
                ],
                # Bloklanmış sətir vurğulanır: admin siyahıya baxanda «niyə
                # bu mağaza işləmir?» sualının cavabı gözə dəyməlidir.
                highlighted=status == DeviceStatus.BLOCKED.value,
            )
        self._empty.setVisible(not devices)
        self._table.setVisible(bool(devices))

    # -------------------------------- daxili --------------------------------- #

    def _build_actions(self, device: dict[str, object]) -> QWidget:
        """Sətir əməliyyatları — VƏZİYYƏTƏ görə fərqlidir.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ HƏR SƏTİRDƏ EYNİ DÜYMƏ DƏSTİ DEYİL
        ──────────────────────────────────────────────────────────────────────
        Bloklanmış cihazı «Blokla» etmək, aktiv cihazı «Bərpa Et» etmək
        mənasızdır — düymə basılar, use case `InvalidStateTransitionError`
        atar və istifadəçi izah edilməyən xəta görər. Vəziyyətə uyğun olmayan
        əməliyyatı DEAKTİV etmək əvəzinə GÖSTƏRMƏMƏK seçildi: deaktiv düymə
        «niyə basılmır?» sualı yaradır, olmayan düymə isə yaratmır.

        Təsdiq gözləyən sətirdə düymə YOXDUR: onun forması yuxarıdaki
        «Təsdiq gözləyənlər» kartındadır və orada filial/ad seçimi ilə
        birlikdə gəlir. İki yerdə iki fərqli təsdiq yolu olsaydı, biri
        filialsız təsdiq imkanı açardı.
        """
        device_id = str(device.get("id", ""))
        status = str(device.get("status", ""))
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        if status == DeviceStatus.ACTIVE.value:
            store_box = QComboBox()
            for store_id, store_name in self._stores:
                store_box.addItem(store_name, store_id)
            # Cari filial seçili gəlir ki, «dəyişdir» düyməsi təsadüfən
            # BİRİNCİ mağazaya köçürməsin.
            current = str(device.get("store_id", ""))
            index = store_box.findData(current)
            if index >= 0:
                store_box.setCurrentIndex(index)
            layout.addWidget(store_box, 1)

            move = secondary_button("Köçür")
            move.clicked.connect(
                lambda: self.reassign_requested.emit(
                    {"device_id": device_id, "store_id": store_box.currentData()}
                )
            )
            layout.addWidget(move)

            block = secondary_button("Blokla")
            block.clicked.connect(lambda: self.block_requested.emit(device_id))
            layout.addWidget(block)
        elif status == DeviceStatus.BLOCKED.value:
            restore = action_button("Bərpa Et")
            restore.clicked.connect(lambda: self.reactivate_requested.emit(device_id))
            layout.addWidget(restore)
            layout.addWidget(stretch())
        else:
            layout.addWidget(muted_label("Yuxarıdaki formada təsdiqlənir"))

        return holder

    def _build_pending_row(self, device: dict[str, object]) -> QWidget:
        """Bir gözləyən cihaz + onun təsdiq forması.

        Forma sətrin İÇİNDƏDİR, ayrı dialoqda deyil: admin telefonda danışa-
        danışa ad yazır və filial seçir — dialoq açmaq həmin axını kəsərdi.
        """
        device_id = str(device.get("id", ""))
        row = QWidget()
        outer = QVBoxLayout(row)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        heading = QHBoxLayout()
        heading.setSpacing(12)
        code = plain_label(str(device.get("short_code", "")))
        code.setProperty("variant", "mono")
        heading.addWidget(code)
        heading.addWidget(muted_label(str(device.get("machine_name", ""))))
        heading.addWidget(stretch())
        outer.addLayout(heading)

        form = QHBoxLayout()
        form.setSpacing(12)

        form.addWidget(field_label("Ad"))
        name_input = QLineEdit()
        name_input.setPlaceholderText("məs. Yataş Babək — Kassa 1")
        name_input.setText(str(device.get("machine_name", "")))
        form.addWidget(name_input, 2)

        form.addWidget(field_label("Filial"))
        store_box = QComboBox()
        for store_id, store_name in self._stores:
            store_box.addItem(store_name, store_id)
        form.addWidget(store_box, 2)

        form.addWidget(field_label("Tip"))
        type_box = QComboBox()
        for device_type, label in DEVICE_TYPE_LABELS.items():
            type_box.addItem(label, device_type.value)
        form.addWidget(type_box, 2)

        approve = action_button("Təsdiqlə")
        approve.clicked.connect(
            lambda: self.approve_requested.emit(
                {
                    "device_id": device_id,
                    "store_id": store_box.currentData(),
                    "device_name": name_input.text(),
                    "device_type": type_box.currentData(),
                }
            )
        )
        form.addWidget(approve)

        block = secondary_button("Blokla")
        block.clicked.connect(lambda: self.block_requested.emit(device_id))
        form.addWidget(block)

        outer.addLayout(form)
        return row


__all__ = [
    "ADMIN_EMPTY_MESSAGE",
    "ADMIN_EMPTY_TITLE",
    "BLOCKED_INTRO",
    "BLOCKED_TITLE",
    "DEVICE_TYPE_LABELS",
    "PENDING_AFTER",
    "PENDING_INSTRUCTION",
    "PENDING_INTRO",
    "PENDING_TITLE",
    "STATUS_LABELS",
    "STATUS_TONES",
    "DeviceAdminScreen",
    "DevicePendingScreen",
    "device_type_label",
    "status_label",
]
