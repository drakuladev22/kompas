"""Qrup D — ERP, infrastruktur, ayarlar və ROOT — Faza 4.2.

Maket: "KompasOS - Qrup D.dc.html", ekranlar 15–20.

    15  ERP / 1C Çox-Server Paneli
    16  Ehtiyat Nüsxə / Bərpa
    17  Sistem Sağlamlığı (Diaqnostika)
    18  Audit Jurnalı
    19  Ayarlar
    20  ROOT İdarə Mərkəzi

──────────────────────────────────────────────────────────────────────────────
NİYƏ SİHİRBAZ DOMEN ENUM-UNU BİRBAŞA İDXAL EDİR (1c.md GUI fazası)
──────────────────────────────────────────────────────────────────────────────
`ServerConnectionWizard` `ConnectorType`/`ConnectorConfig` idxal edir — bu,
`group_c`/`group_f`/`group_i`-də artıq işlənən naxışdır. Səbəb: kartların
BÜTÜN mətnləri (`label_az`, `card_description_az`, `address_label_az`,
`latency_meaning_az`) domendə saxlanılır və eyni mətn HƏM sihirbazda, HƏM
siyahı nişanında, HƏM də sağlamlıq diaqnozunda görünür. Ekran öz nüsxəsini
yazsaydı, üç yerdə üç fərqli ifadə yaranardı və istifadəçi "bunlar eyni
şeydirmi?" sualı ilə qalardı (bax `ConnectorType` docstring-i).

`ErpServersScreen`-in ÖZÜ isə domendən ASILI DEYİL: siyahı sətirləri sadə
sözlüklərdir və mətnləri kontroller (canlı) yaxud `preview_data` (maket)
verir — hər ikisi EYNİ açarları işlədir (CLAUDE.md bölmə 6).
"""

from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING, Any, Final

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.domain.value_objects.erp import (
    MIN_SYNC_INTERVAL_SECONDS,
    ConnectorConfig,
    ConnectorType,
    ErpPlatformError,
)
from src.presentation.screens.base import Screen
from src.presentation.theme.manager import refresh_widget_style
from src.presentation.widgets import icons, metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.charts import Meter
from src.presentation.widgets.data_table import Column, DataTable
from src.presentation.widgets.forms import FormField, field_label
from src.presentation.widgets.help_hint import HelpButton
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import (
    Card,
    Chip,
    ChipTone,
    ClickableCard,
    Divider,
    LinkLabel,
    StatusDot,
    body_label,
    mono_label,
    muted_label,
    plain_label,
    stretch,
    title_label,
)
from src.presentation.widgets.safe_text import plain_tooltip
from src.presentation.widgets.toggle import ToggleSwitch

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager


def _metric_card(
    theme: ThemeManager,
    title: str,
    value: str,
    caption: str,
    tone: str,
) -> Card:
    """Diaqnostika kartı — rəng-kodlaşdırılmış status nöqtəsi ilə."""
    card = Card(padding=20, spacing=12)

    head = QWidget()
    head_layout = QHBoxLayout(head)
    head_layout.setContentsMargins(0, 0, 0, 0)
    head_layout.setSpacing(8)
    head_layout.addWidget(StatusDot(theme.color(tone)))
    head_layout.addWidget(muted_label(title, size=13))
    head_layout.addWidget(stretch())
    card.add(head)

    card.add(title_label(value, size=26))
    card.add(muted_label(caption))
    card.body().addStretch(1)
    return card


# --------------------------------------------------------------------------- #
# 15 — ERP / 1C Çox-Server Paneli
# --------------------------------------------------------------------------- #


#: ERP panelinin kontekstual köməyi (audit G-4).
#:
#: Mətn EKRANIN YANINDA yaşayır, mərkəzi kömək kataloqunda deyil — səbəbi
#: `widgets/help_hint.HelpButton` başlığındadır: «Sinxron» sütununun növ-növ
#: dəyişən mənası və «Hamısını Yoxla» düyməsinin FAKTİKİ etdiyi iş bu faylda
#: izah olunur, izahın ikinci nüsxəsi ayrı kataloqda saxlansaydı sükutla
#: arxada qalardı.
ERP_HELP_TITLE: Final = "ERP Serverləri"

ERP_HELP_INTRO: Final = (
    "Bu ekranda 1C serverləri, hansı mağazanın hansı serverə bağlandığı və "
    "son sinxronizasiyanın nəticəsi göstərilir. Siyahının özü heç nə "
    "dəyişmir — yazı yalnız sihirbaz vasitəsilə aparılır."
)

ERP_HELP_STEPS: Final[tuple[str, ...]] = (
    "Cədvəldəki sətrə klikləyin — həmin serverin sihirbazı REDAKTƏ rejimində "
    "açılır. Növ, ünvan, baza və dövr formaya yüklənir; şifrə sahəsi isə "
    "təhlükəsizlik üçün boş gəlir və yenidən yazılmalıdır.",
    "«Sinxron» sütunu hər növdə BAŞQA şeyi ölçür: HTTP-də şəbəkə cavabını, "
    "COM-da obyektin qurulmasını, fayl mübadiləsində qovluğun oxunmasını. "
    "Cədvəlin altındakı izah hansı rəqəmin nə demək olduğunu yazır — "
    "rəqəmləri müxtəlif növlər arasında tutuşdurmaq yanıldıcıdır.",
    "«Hamısını Yoxla» serverlərə yeni sorğu GÖNDƏRMİR — sinxronizasiya "
    "xidmətinin real nəticələrini yenidən oxuyur. Yəni bu düymə heç nəyi "
    "dəyişmir və istənilən vaxt təhlükəsiz basıla bilər.",
    "«Yeni Server» sihirbazı açır: növ seçilir, ünvan və giriş məlumatları "
    "yazılır, bağlantı yadda saxlanmazdan ƏVVƏL sınaqdan keçirilir — testdən "
    "keçməyən konfiqurasiya yazılmır.",
    "«Mağaza — Server xəritələmə» hansı filialın hansı serverdən oxuyacağını "
    "göstərir. Xəritələnməmiş mağazanın məlumatı 1C-yə ÜMUMİYYƏTLƏ getmir, "
    "ona görə siyahıdakı boşluq diqqətdən qaçmamalıdır.",
)


class ErpServersScreen(Screen):
    """1C serverləri, mağaza xəritələməsi və son sinxronizasiya.

    Signals:
        test_all_requested / create_requested: alət düymələri.
        server_selected: Server adı.
    """

    test_all_requested = Signal()
    create_requested = Signal()
    server_selected = Signal(str)

    _STATUS_TONES: Final[dict[str, ChipTone]] = {
        "Aktiv": "success",
        "Gecikmə yüksəkdir": "warning",
        "Bağlantı yoxdur": "danger",
    }

    #: Bağlantı növü nişanının tonu (1c.md UX tələbi 4).
    #:
    #: ──────────────────────────────────────────────────────────────────────
    #: NİYƏ MÖVCUD TONLAR, NİYƏ YENİ RƏNGLƏR DEYİL
    #: ──────────────────────────────────────────────────────────────────────
    #: Üç yeni rəng üç yeni cüt deməkdir və hər biri HƏR İKİ temada AA-dan
    #: keçməlidir. Mövcud nişan tonları (`tokens.py`) məhz bunun üçün artıq
    #: kalibrlənib — yeni ton əlavə etmək eyni işi ikinci dəfə görmək və
    #: sürüşmə riski yaratmaq olardı.
    #:
    #: TON SEÇİMİ TƏSADÜFİ DEYİL: fayl mübadiləsi real-vaxt DEYİL
    #: (`ConnectorType.is_real_time`) və nişanın "xəbərdarlıq" tonu məhz bu
    #: qeyd-şərti daşıyır. Rəng TƏK əlamət deyil — nişanın İÇİNDƏ növün adı
    #: yazılır (`label_az`), yəni rəngi ayırd etməyən istifadəçi mətni oxuyur.
    #: Açar naməlum gəlirsə nişan GİZLƏNMİR, neytral tonda göstərilir.
    _TYPE_TONES: Final[dict[str, ChipTone]] = {
        "HTTP/OData": "info",
        "COM": "neutral",
        "Fayl": "warning",
    }

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(12)
        self._summary = muted_label("")
        toolbar_layout.addWidget(self._summary)
        toolbar_layout.addWidget(stretch())

        # Kontekstual kömək (audit G-4) — «Sinxron» sütununun mənası cədvəlin
        # altında bir sətirdə yazılır, «Hamısını Yoxla»-nın nə etdiyi isə
        # heç yerdə görünmürdü; hər ikisi burada tam izah olunur.
        self._help = HelpButton(
            theme,
            title=ERP_HELP_TITLE,
            intro=ERP_HELP_INTRO,
            steps=ERP_HELP_STEPS,
        )
        toolbar_layout.addWidget(self._help)

        test_all = secondary_button("Hamısını Yoxla")
        test_all.clicked.connect(self.test_all_requested)
        toolbar_layout.addWidget(test_all)

        create = action_button(
            "Yeni Server",
            icon_name="plus",
            icon_color=theme.color("--color-action-text"),
        )
        create.clicked.connect(self.create_requested)
        toolbar_layout.addWidget(create)
        self.add(toolbar)

        self._table = DataTable(
            [
                Column("Server", 180),
                Column("Növ", 110),
                Column("Ünvan", 190, mono=True),
                Column("Mağaza", 130),
                Column("Sinxron", 110, mono=True),
                Column("Vəziyyət"),
            ],
            theme,
        )
        self._table.row_selected.connect(self._on_row)
        self.add(self._table)

        # «Sinxron» sütununun rəqəmi hər növdə BAŞQA şeyi ölçür (şəbəkə cavabı /
        # COM obyektinin qurulması / qovluğun oxunması). Rəqəmi izahsız
        # buraxsaydıq, fayl serverindəki "45 ms" şəbəkə gecikməsi kimi oxunardı
        # — yəni cədvəl YANILDIRARDI. Açıqlama cədvəlin altında bir dəfə, sətir
        # tooltip-ində isə hər sətir üçün ayrıca verilir.
        self._latency_legend = muted_label("")
        self._latency_legend.setWordWrap(True)
        self._latency_legend.setVisible(False)
        self.add(self._latency_legend)

        bottom = QWidget()
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(metrics.CARD_SPACING)

        self._mapping = Card(padding=20, spacing=12)
        self._mapping.add(title_label("Mağaza — Server xəritələmə", size=15))
        self._mapping_rows = QVBoxLayout()
        self._mapping_rows.setSpacing(8)
        mapping_holder = QWidget()
        mapping_holder.setLayout(self._mapping_rows)
        self._mapping.add(mapping_holder)
        self._mapping_note = muted_label("")
        self._mapping.add(self._mapping_note)
        bottom_layout.addWidget(self._mapping, 1)

        self._sync = Card(padding=20, spacing=12)
        self._sync.add(title_label("Son sinxronizasiya", size=15))
        self._sync_rows = QVBoxLayout()
        self._sync_rows.setSpacing(8)
        sync_holder = QWidget()
        sync_holder.setLayout(self._sync_rows)
        self._sync.add(sync_holder)
        bottom_layout.addWidget(self._sync, 1)
        self.add(bottom)

        self._server_names: list[str] = []

    def help_button(self) -> HelpButton:
        """Kontekstual kömək düyməsi — kontroller/testlər üçün."""
        return self._help

    def set_servers(self, servers: list[dict[str, str]], *, mapped_stores: int) -> None:
        """Server siyahısı.

        Sətir açarları (maket və canlı yolda EYNİDİR): `name`, `type`,
        `address`, `stores`, `latency`, `latency_meaning`, `status`.
        `type`/`latency_meaning` boş gələ bilər — o zaman nişan və izah
        sadəcə göstərilmir, sətir isə itmir.
        """
        self._summary.setText(f"{len(servers)} server · {mapped_stores} mağaza xəritələnib")
        self._table.clear()
        self._server_names = [server["name"] for server in servers]

        for server in servers:
            status = server.get("status", "Aktiv")
            kind = server.get("type", "")
            latency = mono_label(server.get("latency", "—"))
            meaning = server.get("latency_meaning", "")
            if meaning:
                latency.setToolTip(plain_tooltip(meaning))
            self._table.add_row(
                [
                    mono_label(server["name"]),
                    Chip(kind, self._TYPE_TONES.get(kind, "neutral")) if kind else plain_label(""),
                    mono_label(server.get("address", ""), muted=True),
                    server.get("stores", ""),
                    latency,
                    Chip(status, self._STATUS_TONES.get(status, "neutral")),
                ]
            )
        self._set_latency_legend(servers)
        self.show_content()

    def _set_latency_legend(self, servers: list[dict[str, str]]) -> None:
        """«Sinxron» sütununun mənasını növ-növ izah edir.

        Mətn DOMENDƏN gəlir (`ConnectorType.latency_meaning_az`) və sətirlərlə
        birlikdə ötürülür — ekran öz nüsxəsini qursaydı, domendəki izah
        dəyişəndə cədvəldəki açıqlama arxada qalardı. Yalnız siyahıda FAKTİKİ
        mövcud olan növlər sadalanır: istifadəçinin işlətmədiyi bir növün
        izahı yalnız səs-küy olardı.
        """
        seen: dict[str, str] = {}
        for server in servers:
            kind, meaning = server.get("type", ""), server.get("latency_meaning", "")
            if kind and meaning and kind not in seen:
                seen[kind] = meaning
        if not seen:
            self._latency_legend.setVisible(False)
            self._latency_legend.setText("")
            return
        # Mətn ÇEVRİLMİR (nə kiçik, nə böyük hərfə): domendən gələn izahda
        # akronim var («COM obyektinin qurulma müddəti») və `lower()` onu
        # «com» kimi göstərərdi — yəni domen mətnini korlayardı.
        parts = "; ".join(f"{kind} — {meaning}" for kind, meaning in seen.items())
        self._latency_legend.setText(f"«Sinxron» sütunu: {parts}.")
        self._latency_legend.setVisible(True)

    def _on_row(self, index: int) -> None:
        if 0 <= index < len(self._server_names):
            self.server_selected.emit(self._server_names[index])

    def set_mapping(self, mapping: list[tuple[str, str]], *, note: str) -> None:
        clear_layout(self._mapping_rows)

        for store, server in mapping:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(body_label(store, size=13, wrap=False))
            layout.addWidget(stretch())
            layout.addWidget(mono_label(server))
            self._mapping_rows.addWidget(row)

        self._mapping_note.setText(note)

    def set_last_sync(self, entries: list[tuple[str, str, str]]) -> None:
        """`entries`: (ad, vaxt/nəticə, ton)."""
        clear_layout(self._sync_rows)

        tones = {"success": "--color-success", "danger": "--color-danger"}
        for name, value, tone in entries:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)
            layout.addWidget(StatusDot(self.theme.color(tones.get(tone, "--color-success"))))
            layout.addWidget(body_label(name, size=13, wrap=False))
            layout.addWidget(stretch())
            layout.addWidget(mono_label(value))
            self._sync_rows.addWidget(row)


#: Növ kartının ikonu (1c.md UX tələbi 1: "hər biri öz minimal line-ikonu ilə").
_CONNECTOR_ICONS: Final[dict[ConnectorType, str]] = {
    ConnectorType.HTTP: "cloud",
    ConnectorType.COM: "desktop",
    ConnectorType.FILE_EXCHANGE: "folder_file",
}

#: Sahələrin yumşaq keçidi (1c.md UX tələbi 2). 160 ms — tema keçidinin
#: 260 ms-indən qısadır, çünki burada dəyişən şey bütün pəncərə deyil, bir
#: blokdur; daha uzunu formanı "ləng" göstərərdi.
_FIELD_FADE_MS: Final = 160


class _ConnectorCard(ClickableCard):
    """Bağlantı növü seçimi — ikon + ad + izah (1c.md UX tələbi 1).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ DROPDOWN DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Spesifikasiya bunu açıq tələb edir: seçimi edən adam çox vaxt qeyri-texniki
    olur (CEO) və "HTTP/OData ▾" sətri ona heç nə demir. Kart forması üç seçimi
    EYNİ ANDA, izahı ilə birlikdə göstərir — müqayisə üçün heç nə açmaq lazım
    gəlmir.

    ──────────────────────────────────────────────────────────────────────────
    ƏLÇATMAZ KART GİZLƏDİLMİR
    ──────────────────────────────────────────────────────────────────────────
    COM yalnız Windows-da işləyir. Kartı gizlətsəydik, istifadəçi "niyə iki
    seçim var, sənəddə isə üç yazılıb?" sualı ilə tək qalardı. Ona görə kart
    QALIR, klik qəbul etmir və SƏBƏB mətnlə yazılır. Bu, "görmək = səlahiyyətin
    olması" qaydası ilə ziddiyyət təşkil ETMİR: orada söhbət İCAZƏDƏN gedir
    (icazəsiz maddə ümumiyyətlə qurulmur), burada isə platformanın texniki
    məhdudiyyətindən — həmin məhdudiyyət izah olunmalıdır.
    """

    def __init__(
        self,
        connector_type: ConnectorType,
        theme: ThemeManager,
        *,
        available: bool = True,
        unavailable_reason: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(connector_type.value, padding=16, spacing=8, parent=parent)
        self.connector_type = connector_type
        self._available = available
        self._theme = theme
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(12)

        glyph = plain_label()
        glyph.setPixmap(
            icons.render(
                _CONNECTOR_ICONS[connector_type],
                theme.color("--color-text-primary" if available else "--color-text-muted"),
                size=20,
                stroke_width=1.3,
            )
        )
        head_layout.addWidget(glyph)
        head_layout.addWidget(title_label(connector_type.label_az, size=15))
        head_layout.addWidget(stretch())
        self.add(head)

        description = muted_label(connector_type.card_description_az)
        description.setWordWrap(True)
        self.add(description)

        # SEÇİMİN İKİNCİ SİQNALI (rəng-korluğu üçün). Amber çərçivə tək
        # əlamət olsaydı, deuteranopiya ilə seçilmiş kart seçilməmişdən
        # fərqlənməzdi — burada isə İŞARƏ + MƏTN də görünür.
        self._mark = QWidget()
        mark_layout = QHBoxLayout(self._mark)
        mark_layout.setContentsMargins(0, 0, 0, 0)
        mark_layout.setSpacing(8)
        check = plain_label()
        check.setPixmap(
            icons.render("check", theme.color("--color-accent"), size=14, stroke_width=1.8)
        )
        mark_layout.addWidget(check)
        mark_layout.addWidget(muted_label("Seçildi"))
        mark_layout.addStretch(1)
        self._mark.setVisible(False)
        self.add(self._mark)

        if not available:
            self.setProperty("unavailable", "true")
            self.setCursor(Qt.CursorShape.ArrowCursor)
            # Klaviatura ilə də seçilə bilməməlidir — fokus alan, lakin heç
            # nə etməyən element ekran oxuyucusunda "ölü" düymə kimi qalır.
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            reason = muted_label(unavailable_reason)
            reason.setWordWrap(True)
            self.add(reason)
            self.setToolTip(plain_tooltip(unavailable_reason))

    @property
    def is_available(self) -> bool:
        return self._available

    def set_selected(self, selected: bool) -> None:
        """Seçilmiş görünüşü tətbiq edir (çərçivə + fon + işarə)."""
        self.setProperty("selected", "true" if selected else "false")
        self._mark.setVisible(selected)
        refresh_widget_style(self)

    def _activate(self) -> None:
        # Əlçatmaz kart siqnal YAYMIR: klik "heç nə baş vermədi" kimi
        # görünərdi, halbuki səbəb kartın öz mətnindədir.
        if self._available:
            super()._activate()


class _TestSpinner(QLabel):
    """Fırlanan «yenilə» ikonu — bağlantı testi gedərkən (1c.md UX tələbi 3).

    NİYƏ PİKSMAP FIRLADILIR, NİYƏ HAZIR WIDGET YOXDUR: Qt-də qeyri-müəyyən
    gedişat göstəricisi `QProgressBar`-dır və o, formada bir zolaq yeri tutur;
    burada isə lazım olan şey düymənin YANINDA, mətnlə eyni sətirdə duran
    kiçik bir hərəkətdir. Bir `QTimer` + bir `QTransform` bunun ən ucuz yoludur
    və dayandırıldıqda heç bir resurs saxlamır.

    Taymer `stop()` ilə HƏR HALDA dayandırılır (uğur, uğursuzluq, pəncərənin
    bağlanması) — dayandırılmayan taymer modal bağlandıqdan sonra da hər 90
    ms-də bir kadr çəkməyə davam edərdi.
    """

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self._frame = icons.render("refresh", theme.color("--color-text-muted"), size=14)
        self._angle = 0
        self.setFixedSize(20, 20)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setPixmap(self._frame)
        self.setVisible(False)
        self._timer = QTimer(self)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._advance)

    def start(self) -> None:
        self.setVisible(True)
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.setVisible(False)

    def _advance(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.setPixmap(
            self._frame.transformed(
                QTransform().rotate(self._angle), Qt.TransformationMode.SmoothTransformation
            )
        )


class ServerConnectionWizard(QDialog):
    """ "Yeni Server" sihirbazı — bağlantı növü seçimi + bağlantı testi.

    Signals:
        test_requested: Doldurulmuş sahələr.
        saved: Doldurulmuş sahələr.

    Test NƏTİCƏSİ olmadan yadda saxlamağa icazə verilir, lakin xəbərdarlıq
    göstərilir — offline quraşdırmada (server hələ qoşulmayıb) admin serveri
    əvvəlcədən əlavə edə bilməlidir.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ HƏR NÖVÜN ÖZ SAHƏ PANELİ VAR (1c.md UX tələbi 2)
    ──────────────────────────────────────────────────────────────────────────
    "Bir tipdən digərinə keçilib geri qayıdılsa, əvvəl yazılmış dəyərlər
    YADDAŞDA qalır." Tək bir «Ünvan» sahəsini üç növ arasında paylaşsaydıq,
    HTTP üçün yazılmış `10.20.1.16:1541` fayl növünə keçəndə qovluq yolu kimi
    görünərdi — yəni dəyər "qalmazdı", ÇEVRİLƏRDİ. Ona görə hər növün öz
    paneli, öz sahələri var: yaddaş widget-lərin özündədir və heç bir əlavə
    sinxronizasiya tələb etmir.

    Növə XAS parametrlər (`connector_config`) isə `ConnectorConfig`-də
    saxlanılır və `with_values(...)` ilə üzərinə yazılır — beləliklə redaktədə
    yüklənmiş, lakin formada göstərilməyən qabaqcıl açarlar (məs. COM sorğu
    sahələrinin adları) İTMİR.
    """

    test_requested = Signal(dict)
    saved = Signal(dict)

    def __init__(
        self,
        theme: ThemeManager,
        *,
        parent: QWidget | None = None,
        system_name: str | None = None,
    ) -> None:
        """Sihirbazı qurur.

        Args:
            theme: Rəng tokenlərinin mənbəyi (ekran rəng HARDCODE ETMİR).
            parent: Modalın valideyni.
            system_name: `platform.system()` əvəzedicisi — COM kartının
                əlçatanlığını testdə qlobal yamaqsız yoxlamaq üçün
                (`OneCComConnector`-un `system_name` parametri ilə eyni naxış).
        """
        super().__init__(parent)
        self._theme = theme
        self._system_name = system_name
        self.setWindowTitle("Yeni 1C Serveri")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        card = Card(padding=24, spacing=16)
        layout.addWidget(card)

        self._heading = title_label("Yeni 1C Serveri", size=19)
        card.add(self._heading)
        card.add(
            muted_label(
                "Əvvəlcə bağlantı növünü seçin, sonra həmin növün tələb etdiyi "
                "məlumatları doldurub yoxlayın."
            )
        )
        card.add(Divider())

        # --- 1-ci addım: növ kartları ---------------------------------------- #
        self._cards: dict[ConnectorType, _ConnectorCard] = {}
        card.add(self._build_type_cards())

        # Redaktədə növ dəyişdirildikdə görünən xəbərdarlıq (aşağıda izah).
        # SOLĞUN DEYİL, XƏBƏRDARLIQ TONUNDA: mətn nəticəsi geri qaytarıla
        # bilməyən bir dəyişikliyi elan edir — solğun rəng onu "əlavə qeyd"
        # kimi göstərib gözdən qaçırardı.
        self._type_notice = body_label("", size=13)
        self._type_notice.setProperty("variant", "warning")
        self._type_notice.setVisible(False)
        card.add(self._type_notice)

        # --- ortaq sahələr ---------------------------------------------------- #
        self._name = FormField("Server adı")
        card.add(self._name)

        # --- 2-ci addım: növə xas sahələr (yumşaq keçidlə) -------------------- #
        self._stack = QStackedWidget()
        self._panels: dict[ConnectorType, QWidget] = {}
        self._address: dict[ConnectorType, FormField] = {}
        self._config_inputs: dict[ConnectorType, dict[str, FormField]] = {}
        self._config_memory: dict[ConnectorType, ConnectorConfig] = {
            connector_type: ConnectorConfig() for connector_type in ConnectorType
        }
        self._build_http_panel()
        self._build_com_panel()
        self._build_file_panel()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self._stack)
        scroll.setMinimumHeight(240)
        card.add(scroll)

        # Sahələrin görünüşü ANİ dəyişmir — bax `_show_panel`.
        self._fade_effect = QGraphicsOpacityEffect(self._stack)
        self._fade_effect.setOpacity(1.0)
        self._stack.setGraphicsEffect(self._fade_effect)
        self._fade = QPropertyAnimation(self._fade_effect, b"opacity", self)
        self._fade.setDuration(_FIELD_FADE_MS)
        self._fade.setEasingCurve(QEasingCurve.Type.InOutCubic)

        # --- sinxronizasiya dövrü (növdən ASILI OLMAYAN ortaq parametr) ------ #
        #
        # `0` = "tipin defoltu": `ErpServerDraft.sync_interval_seconds=None`
        # verildikdə domen həmin defoltu tətbiq edir (fayl mübadiləsi üçün ROOT
        # limitindən). Boş buraxıla bilən `QSpinBox` yoxdur, ona görə xüsusi
        # dəyər mətni işlədilir — istifadəçi "nə yazmalıyam?" sualı ilə
        # qalmasın deyə.
        self._interval = QSpinBox()
        self._interval.setProperty("variant", "form")
        self._interval.setRange(0, 86400)
        self._interval.setSingleStep(30)
        self._interval.setSuffix(" san")
        self._interval.setSpecialValueText("Bağlantı növünün defoltu")
        card.add(
            FormField(
                "Sinxronizasiya dövrü",
                widget=self._interval,
                hint=(
                    f"Ən azı {MIN_SYNC_INTERVAL_SECONDS} saniyə. "
                    "Boş buraxsanız növün öz defolt dövrü tətbiq olunur."
                ),
            )
        )

        # --- test nəticəsi ---------------------------------------------------- #
        self._result_row = QWidget()
        result_layout = QHBoxLayout(self._result_row)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(8)
        self._spinner = _TestSpinner(theme)
        result_layout.addWidget(self._spinner)
        self._result_icon = plain_label()
        self._result_icon.setVisible(False)
        result_layout.addWidget(self._result_icon)
        self._result = plain_label()
        self._result.setWordWrap(True)
        result_layout.addWidget(self._result, 1)
        self._result_row.setVisible(False)
        card.add(self._result_row)

        # Texniki səbəb AYRI sətirdədir — bax `set_test_result`.
        self._result_detail = mono_label("", muted=True)
        self._result_detail.setWordWrap(True)
        self._result_detail.setVisible(False)
        card.add(self._result_detail)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)

        self._test_button = secondary_button("Bağlantını Yoxla")
        self._test_button.clicked.connect(lambda: self.test_requested.emit(self.collected()))
        buttons_layout.addWidget(self._test_button)
        buttons_layout.addWidget(stretch())

        cancel = secondary_button("İmtina")
        cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel)

        save = action_button("Yadda Saxla")
        save.clicked.connect(self._on_save)
        buttons_layout.addWidget(save)
        card.add(buttons)

        # Enter «Yadda Saxla»-nı işə salır: server QEYDƏ ALINIR, heç nə
        # silinmir və səhv qeyd redaktə edilə bilir. Açıq təyin olmasaydı
        # Qt ilk düyməni («Bağlantını Yoxla») defolt sayardı və Enter
        # gözlənilmədən şəbəkə sorğusu başladardı.
        save.setDefault(True)
        save.setAutoDefault(True)
        for button in (self._test_button, cancel):
            button.setAutoDefault(False)

        # Fokus sırası vizual sıra ilə: kartlar → ad → aktiv panelin sahələri →
        # dövr → yoxla → imtina → saxla.
        self._tail_buttons = (self._test_button, cancel, save)
        self._selected_type = ConnectorType.HTTP
        self._loaded_type: ConnectorType | None = None
        self._apply_selection(ConnectorType.HTTP, animate=False)

        self._name.focus_input()

    # ------------------------------ quruluş ---------------------------------- #

    def _build_type_cards(self) -> QWidget:
        """Üç növ yan-yana. Windows olmayan mühitdə COM izahla əlçatmazdır.

        `platform.system()` işlədilir, `sys.platform` YOX — səbəb
        `com_connector.py` başlığındadır: mypy konfiqurasiyası `platform =
        "win32"` ilə işləyir və `sys.platform` yoxlaması qeyri-Windows budağı
        "çatılmaz kod" kimi göstərərdi.
        """
        import platform  # noqa: PLC0415

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)

        windows = (self._system_name or platform.system()) == "Windows"
        for connector_type in ConnectorType:
            available = windows or not connector_type.requires_windows
            card = _ConnectorCard(
                connector_type,
                self._theme,
                available=available,
                # Səbəb mətni DOMENDƏNDİR (`ErpPlatformError.user_message`) —
                # eyni cümlə konnektorun özü işə düşməyəndə də göstərilir.
                unavailable_reason=ErpPlatformError.user_message,
            )
            card.clicked.connect(self._on_card_clicked)
            self._cards[connector_type] = card
            row_layout.addWidget(card, 1)
        return row

    def _build_http_panel(self) -> None:
        """HTTP/OData — sahələr Faza 4.2-dəki forma ilə EYNİDİR.

        `self._host` / `self._database` / `self._username` / `self._password`
        adları QƏSDƏN saxlanılıb: mövcud sihirbazın forması dəyişmir, yalnız
        onun ətrafına növ seçimi əlavə olunur (1c.md QIRMIZI XƏTT).
        """
        panel, layout = self._new_panel()
        self._host = FormField(ConnectorType.HTTP.address_label_az)
        self._database = FormField("Baza (infobase)")
        self._username = FormField("İstifadəçi")
        self._password = FormField("Şifrə", password=True)
        for field in (self._host, self._database, self._username, self._password):
            layout.addWidget(field)
        layout.addStretch(1)
        self._address[ConnectorType.HTTP] = self._host
        self._register_panel(ConnectorType.HTTP, panel)

    def _build_com_panel(self) -> None:
        """COM — server/qovluq, baza (Ref), istifadəçi, şifrə + sorğu parametrləri.

        Sorğu SAHƏ ADLARI (`id_field`, `date_field`, …) formada YOXDUR: onların
        dil-əsaslı defoltları standart 1C konfiqurasiyalarını onsuz da tutur və
        yeddi əlavə sahə bu ekranı qeyri-texniki istifadəçi üçün oxunmaz edərdi.
        Redaktədə yüklənmiş belə açarlar İTMİR — `ConnectorConfig.with_values`
        yalnız formadakı açarları üzərinə yazır (bax sinif başlığı).
        """
        panel, layout = self._new_panel()
        address = FormField(ConnectorType.COM.address_label_az)
        self._com_infobase = FormField("Baza adı (Ref)")
        self._com_username = FormField("İstifadəçi")
        self._com_password = FormField("Şifrə", password=True)
        for field in (address, self._com_infobase, self._com_username, self._com_password):
            layout.addWidget(field)

        file_mode = QComboBox()
        file_mode.setProperty("variant", "form")
        file_mode.addItems(["Klient-server (Srvr=)", "Fayl bazası (File=)"])
        language = QComboBox()
        language.setProperty("variant", "form")
        language.addItems(["RU", "EN"])
        query_source = FormField("Sənəd növü")
        layout.addWidget(FormField("Baza rejimi", widget=file_mode))
        layout.addWidget(
            FormField(
                "Sorğu dili",
                widget=language,
                hint="1C sorğusunun dili — baza konfiqurasiyası ilə eyni olmalıdır.",
            )
        )
        layout.addWidget(query_source)
        layout.addStretch(1)

        self._address[ConnectorType.COM] = address
        self._com_file_mode = file_mode
        self._com_language = language
        self._config_inputs[ConnectorType.COM] = {"query_source": query_source}
        self._register_panel(ConnectorType.COM, panel)

    def _build_file_panel(self) -> None:
        """Fayl mübadiləsi — qovluq, format və gözlənilən sütun adları.

        Sütun adları BURADA olmalıdır: konnektorun ən çox rast gəlinən xətası
        "faylda gözlənilən sütun(lar) yoxdur" mesajıdır və o, düzəlişin məhz
        sihirbazda edilməsini deyir. Sahələri gizlətsəydik, istifadəçi mesajı
        oxuyub heç nə edə bilməzdi.
        """
        panel, layout = self._new_panel()
        address = FormField(
            ConnectorType.FILE_EXCHANGE.address_label_az,
        )
        layout.addWidget(address)

        file_format = QComboBox()
        file_format.setProperty("variant", "form")
        file_format.addItems(["CSV", "XML"])
        layout.addWidget(FormField("Fayl formatı", widget=file_format))

        text_fields: dict[str, FormField] = {
            "file_pattern": FormField("Fayl şablonu"),
            "encoding": FormField("Kodlaşdırma"),
            "delimiter": FormField("Ayırıcı (CSV)"),
            "record_tag": FormField("Sənəd elementi (XML)"),
            "date_format": FormField("Tarix şablonu"),
            "document_id_column": FormField("Sənəd ID sütunu"),
            "date_column": FormField("Tarix sütunu"),
            "seller_column": FormField("Satıcı sütunu"),
            "store_column": FormField("Mağaza sütunu"),
            "amount_column": FormField("Məbləğ sütunu"),
            "seller_name_column": FormField("Satıcı adı sütunu"),
        }
        for field in text_fields.values():
            layout.addWidget(field)
        layout.addStretch(1)

        self._address[ConnectorType.FILE_EXCHANGE] = address
        self._file_format = file_format
        self._config_inputs[ConnectorType.FILE_EXCHANGE] = text_fields
        self._register_panel(ConnectorType.FILE_EXCHANGE, panel)

    @staticmethod
    def _new_panel() -> tuple[QWidget, QVBoxLayout]:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        return panel, layout

    def _register_panel(self, connector_type: ConnectorType, panel: QWidget) -> None:
        self._panels[connector_type] = panel
        self._stack.addWidget(panel)

    # ------------------------------ seçim ------------------------------------ #

    def _on_card_clicked(self, key: str) -> None:
        self._apply_selection(ConnectorType.parse(key), animate=True)

    def _apply_selection(self, connector_type: ConnectorType, *, animate: bool) -> None:
        """Kart seçimi → sahələr, fokus sırası və (redaktədə) xəbərdarlıq."""
        previous = self._selected_type
        if previous is not connector_type:
            # DƏYƏR YADDAŞI: paneldən çıxarkən növün konfiqurasiyası saxlanılır
            # (bax sinif başlığı). Sahələrin özü panellə birlikdə yaşayır.
            self._config_memory[previous] = self._config_memory[previous].with_values(
                **self._read_config_values(previous)
            )
        self._selected_type = connector_type
        for card_type, card in self._cards.items():
            card.set_selected(card_type is connector_type)
        self._show_panel(connector_type, animate=animate)
        self._update_type_notice()
        self._apply_tab_order(connector_type)

    def _show_panel(self, connector_type: ConnectorType, *, animate: bool) -> None:
        """Panelin dəyişməsi — sərt sıçrayış YOX (1c.md UX tələbi 2).

        Animasiya ƏVVƏLCƏ dayandırılır: istifadəçi kartlar arasında sürətlə
        gəzərsə, iki keçid üst-üstə düşüb paneli yarı-şəffaf qoyardı.
        """
        self._fade.stop()
        self._stack.setCurrentWidget(self._panels[connector_type])
        if not animate:
            self._fade_effect.setOpacity(1.0)
            return
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()

    def _update_type_notice(self) -> None:
        """Redaktədə növ dəyişdirildikdə görünən xəbərdarlıq.

        Köhnə növün konfiqurasiyası SİLİNMİR — sətir yenidən yazılanda əvvəlki
        konfiqurasiya `erp_server_config_backups`-a düşür (bax
        `ErpServerRepository.update`). Lakin o, artıq İŞLƏMİR və istifadəçi
        bunu yadda saxlamazdan ƏVVƏL bilməlidir.
        """
        loaded = self._loaded_type
        if loaded is None or loaded is self._selected_type:
            self._type_notice.setVisible(False)
            self._type_notice.setText("")
            return
        self._type_notice.setText(
            f"Bağlantı növü «{loaded.label_az}» → «{self._selected_type.label_az}» "
            "dəyişdirilir. Köhnə növün parametrləri ehtiyat nüsxədə qalır, "
            "lakin bu serverdə artıq işləməyəcək."
        )
        self._type_notice.setVisible(True)

    def _apply_tab_order(self, connector_type: ConnectorType) -> None:
        """Fokus sırası GÖRÜNƏN sıra ilə üst-üstə düşməlidir.

        Panel dəyişəndə sıra da dəyişir: gizli panelin sahələri Tab-la
        keçilməməlidir, əks halda fokus ekranda görünməyən bir sahədə "itərdi".
        """
        widgets: list[QWidget] = [card for card in self._cards.values() if card.is_available]
        widgets.append(self._name.input_widget())
        widgets.extend(field.input_widget() for field in self._panel_fields(connector_type))
        widgets.append(self._interval)
        widgets.extend(self._tail_buttons)
        for previous, following in pairwise(widgets):
            QWidget.setTabOrder(previous, following)

    def _panel_fields(self, connector_type: ConnectorType) -> list[FormField]:
        fields = [self._address[connector_type]]
        if connector_type is ConnectorType.HTTP:
            fields += [self._database, self._username, self._password]
        elif connector_type is ConnectorType.COM:
            fields += [self._com_infobase, self._com_username, self._com_password]
        fields += list(self._config_inputs.get(connector_type, {}).values())
        return fields

    # ------------------------------ dəyərlər --------------------------------- #

    def selected_type(self) -> str:
        """Seçilmiş bağlantı növünün açarı (`ConnectorType.value`)."""
        return self._selected_type.value

    def _read_config_values(self, connector_type: ConnectorType) -> dict[str, Any]:
        """Formadakı növə xas parametrlər — `connector_config` sözlüyü.

        Boş sahə də ötürülür: istifadəçinin TƏMİZLƏDİYİ dəyər saxlanmalı olsa,
        `with_values` onu üzərinə yazmalıdır. Boş sətir konnektor tərəfində
        onsuz da "defoltu işlət" deməkdir (`ConnectorConfig.text`).
        """
        values: dict[str, Any] = {
            key: field.text().strip()
            for key, field in self._config_inputs.get(connector_type, {}).items()
        }
        if connector_type is ConnectorType.COM:
            values["file_mode"] = self._com_file_mode.currentIndex() == 1
            values["query_language"] = self._com_language.currentText()
        elif connector_type is ConnectorType.FILE_EXCHANGE:
            values["file_format"] = self._file_format.currentText()
        return values

    def collected(self) -> dict[str, Any]:
        """Formanın hazırkı vəziyyəti — `load()`-un tərsi.

        `host`/`database`/`username`/`password` açarları Faza 4.2-dən BƏRİ
        eynidir; `connector_type`, `sync_interval` və `config` ƏLAVƏ olunub,
        yəni köhnə HTTP yolu dəyişmədən işləyir.
        """
        connector_type = self._selected_type
        infobase, username, password = "", "", ""
        if connector_type is ConnectorType.HTTP:
            infobase = self._database.text()
            username, password = self._username.text(), self._password.text()
        elif connector_type is ConnectorType.COM:
            infobase = self._com_infobase.text()
            username, password = self._com_username.text(), self._com_password.text()

        config = self._config_memory[connector_type].with_values(
            **self._read_config_values(connector_type)
        )
        interval = self._interval.value()
        return {
            "name": self._name.text(),
            "connector_type": connector_type.value,
            "host": self._address[connector_type].text(),
            "database": infobase,
            "username": username,
            "password": password,
            "sync_interval": str(interval) if interval else "",
            "config": config.as_dict(),
        }

    def load(self, payload: dict[str, Any]) -> None:
        """Mövcud serveri formaya yükləyir (redaktə axını).

        ŞİFRƏ QƏSDƏN GƏLMİR: o, `erp_servers`-də şifrələnib və oxu-modelində
        ümumiyyətlə yoxdur (SEC-013, bax `controllers/erp_servers.py` başlığı).
        Sözlükdə `password` olsa belə istifadə edilmir — sahə boş açılır və
        istifadəçi onu yenidən yazır.
        """
        connector_type = ConnectorType.parse(str(payload.get("connector_type", "")))
        self._loaded_type = connector_type
        self.setWindowTitle("1C Serverinin Redaktəsi")
        self._heading.setText("1C Serverinin Redaktəsi")

        self._name.set_text(str(payload.get("name", "")))
        self._address[connector_type].set_text(str(payload.get("host", "")))
        infobase = str(payload.get("database", ""))
        username = str(payload.get("username", ""))
        if connector_type is ConnectorType.HTTP:
            self._database.set_text(infobase)
            self._username.set_text(username)
        elif connector_type is ConnectorType.COM:
            self._com_infobase.set_text(infobase)
            self._com_username.set_text(username)

        raw_interval = str(payload.get("sync_interval", "")).strip()
        self._interval.setValue(int(raw_interval) if raw_interval.isdigit() else 0)

        config = ConnectorConfig.from_dict(payload.get("config") or {})
        self._config_memory[connector_type] = config
        self._write_config_values(connector_type, config)
        self._apply_selection(connector_type, animate=False)

    def _write_config_values(self, connector_type: ConnectorType, config: ConnectorConfig) -> None:
        """Saxlanmış konfiqurasiyanı formadakı sahələrə yazır."""
        for key, field in self._config_inputs.get(connector_type, {}).items():
            field.set_text(config.text(key))
        if connector_type is ConnectorType.COM:
            self._com_file_mode.setCurrentIndex(1 if config.flag("file_mode") else 0)
            self._com_language.setCurrentText(config.text("query_language", "RU").upper())
        elif connector_type is ConnectorType.FILE_EXCHANGE:
            self._file_format.setCurrentText(config.text("file_format", "CSV").upper())

    # ------------------------------ test nəticəsi ---------------------------- #

    def set_busy(self, busy: bool) -> None:
        """Test gedərkən: düymə deaktiv + FIRLANAN spinner + «Yoxlanılır…».

        ──────────────────────────────────────────────────────────────────────
        `processEvents` YAMAĞI ÇIXARILDI — ARTIQ LAZIM DEYİL
        ──────────────────────────────────────────────────────────────────────
        Əvvəl burada açıq `QApplication.processEvents(ExcludeUserInputEvents)`
        çağırılırdı, çünki bağlantı testi SİNXRON idi: metod qayıtdıqdan
        dərhal sonra hadisə dövrü bloklanırdı və Qt "deaktiv düymə +
        Yoxlanılır…" halını ÇƏKMƏYƏ macal tapmırdı; spinner isə ümumiyyətlə
        fırlanmırdı (taymer bloklanmış dövrdə işə düşmür).

        Test indi fon işçisinə keçib (`presentation/background_task.py`), yəni
        hadisə dövrü test müddətində SƏRBƏSTDİR: pəncərə özü boyanır, spinner
        FAKTİKİ fırlanır (1c.md UX tələbi 3) və istifadəçi sihirbazı bağlaya,
        sahələri dəyişə bilir. `processEvents` isə indi zərərlidir: o, hadisə
        emalını emalın İÇİNDƏN başladır (yenidən-giriş) və bu yolla siqnal
        emalının ortasında ikinci bir slot işə düşə bilər.

        İkiqat işə salma qorumasının mənbəyi də dəyişib: əvvəl
        `ExcludeUserInputEvents` bayrağı idi, indi isə DEAKTİV düymə +
        kontrollerin `BackgroundTask.is_running` yoxlamasıdır.
        """
        self._test_button.setEnabled(not busy)
        self._test_button.setText("Yoxlanılır…" if busy else "Bağlantını Yoxla")
        self._result_icon.setVisible(False)
        self._result_detail.setVisible(False)
        if not busy:
            self._spinner.stop()
            return

        self._result.setText("Yoxlanılır…")
        self._result.setStyleSheet(f"color: {self._theme.color('--color-text-muted')};")
        self._result_row.setVisible(True)
        self._spinner.start()

    def set_test_result(self, *, ok: bool, message: str, detail: str = "") -> None:
        """Nəticə: yaşıl check + mətn, yaxud qırmızı X + KONKRET səbəb.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ `detail` ARTIQ EKRANDA GÖSTƏRİLİR
        ──────────────────────────────────────────────────────────────────────
        Əvvəl texniki səbəb yalnız `app.log`-a yazılırdı. Üç konnektorlu
        dünyada bu, yetərli deyil: fayl mübadiləsində `detail` faylda TAPILAN
        sütunların siyahısıdır, naməlum COM xətasında isə xam `HRESULT` —
        yəni nasazlığı axtaran adamın yeganə ipucu. Onları gizlətmək
        "generic xəta" yasağını (1c.md UX tələbi 3) faktiki olaraq pozardı.

        SIZMA RİSKİ: mətn yalnız `can_manage_erp_servers` daşıyan istifadəçiyə
        və məhz onun ÖZÜNÜN yazdığı parametrlərə aiddir — şifrə isə `detail`-ə
        heç vaxt düşmür (konnektorlar onu istisna mətninə qoymur).
        """
        self._spinner.stop()
        self._test_button.setEnabled(True)
        self._test_button.setText("Bağlantını Yoxla")

        token = "--color-success" if ok else "--color-danger"
        self._result_icon.setPixmap(
            icons.render(
                "check_circle" if ok else "close",
                self._theme.color(token),
                size=16,
                stroke_width=1.8,
            )
        )
        self._result_icon.setVisible(True)
        # Mətn OLDUĞU KİMİ göstərilir — ümumiləşdirilmir, kəsilmir.
        self._result.setText(message)
        self._result.setStyleSheet(f"color: {self._theme.color(token)};")
        self._result_row.setVisible(True)

        self._result_detail.setText(detail)
        self._result_detail.setVisible(bool(detail))

    # ------------------------------ yadda saxlama ---------------------------- #

    def _on_save(self) -> None:
        self._name.clear_error()
        if not self._name.text().strip():
            self._name.set_error("Server adı məcburidir")
            return
        address = self._address[self._selected_type]
        address.clear_error()
        if not address.text().strip():
            address.set_error(f"{self._selected_type.address_label_az} məcburidir")
            return
        self.saved.emit(self.collected())
        self.accept()


# --------------------------------------------------------------------------- #
# 16 — Ehtiyat Nüsxə / Bərpa
# --------------------------------------------------------------------------- #


class BackupScreen(Screen):
    """Ehtiyat nüsxə siyahısı, saxlama həcmi və cədvəl.

    Signals:
        backup_now_requested: «İndi Ehtiyat Nüsxə Al».
        restore_requested: Ehtiyat nüsxə tarixi.
    """

    backup_now_requested = Signal()
    restore_requested = Signal(str)

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(12)
        self._schedule_label = muted_label("")
        toolbar_layout.addWidget(self._schedule_label)
        toolbar_layout.addWidget(stretch())
        now = action_button("İndi Ehtiyat Nüsxə Al")
        now.clicked.connect(self.backup_now_requested)
        toolbar_layout.addWidget(now)
        self.add(toolbar)

        self._table = DataTable(
            [
                Column("Tarix", 200, mono=True),
                Column("Ölçü", 120),
                Column("Növ", 180),
                Column("Vəziyyət", 240),
                Column("Bərpa"),
            ],
            theme,
            footnote="Son 30 günün ehtiyat nüsxələri saxlanılır, sonra avtomatik silinir.",
        )
        self.add(self._table)

        bottom = QWidget()
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(metrics.CARD_SPACING)

        self._storage = Card(padding=20, spacing=12)
        self._storage.add(title_label("Saxlama", size=15))
        self._storage_value = title_label("—", size=19)
        self._storage.add(self._storage_value)
        self._storage_meter = Meter(theme)
        self._storage.add(self._storage_meter)
        self._storage_caption = muted_label("")
        self._storage.add(self._storage_caption)
        bottom_layout.addWidget(self._storage, 1)

        schedule = Card(padding=20, spacing=12)
        schedule.add(title_label("Cədvəl", size=15))

        auto_row = QWidget()
        auto_layout = QHBoxLayout(auto_row)
        auto_layout.setContentsMargins(0, 0, 0, 0)
        auto_layout.addWidget(body_label("Avtomatik ehtiyat nüsxə", size=13, wrap=False))
        auto_layout.addWidget(stretch())
        self._auto_toggle = ToggleSwitch(theme, checked=True)
        auto_layout.addWidget(self._auto_toggle)
        schedule.add(auto_row)

        self._time_combo = QComboBox()
        self._time_combo.setProperty("variant", "form")
        self._time_combo.addItems(["00:00", "01:00", "02:00", "03:00", "04:00"])
        self._time_combo.setCurrentText("02:00")
        schedule.add(FormField("Vaxt", widget=self._time_combo))

        self._retention = QSpinBox()
        self._retention.setProperty("variant", "form")
        self._retention.setRange(7, 365)
        self._retention.setValue(30)
        self._retention.setSuffix(" gün")
        schedule.add(FormField("Saxlama müddəti", widget=self._retention))
        bottom_layout.addWidget(schedule, 1)
        self.add(bottom)

    def set_schedule_label(self, text: str) -> None:
        self._schedule_label.setText(text)

    def set_backups(self, backups: list[dict[str, str]]) -> None:
        self._table.clear()
        for backup in backups:
            succeeded = backup.get("ok", "1") == "1"

            if succeeded:
                restore = secondary_button("Bu Nöqtəyə Bərpa Et")
                restore.clicked.connect(
                    lambda _=False, date=backup["date"]: self.restore_requested.emit(date)
                )
                action: QWidget = restore
            else:
                # Uğursuz ehtiyat nüsxədən bərpa MÜMKÜN DEYİL — düymə göstərmək
                # istifadəçini yanıldardı.
                action = plain_label("—")

            self._table.add_row(
                [
                    mono_label(backup["date"]),
                    backup.get("size", "—"),
                    backup.get("kind", ""),
                    Chip(
                        backup.get("status", ""),
                        "success" if succeeded else "danger",
                    ),
                    action,
                ]
            )
        self.show_content()

    def set_storage(self, used_gb: float, total_gb: float, *, count: int) -> None:
        self._storage_value.setText(f"{used_gb:g} GB / {total_gb:g} GB")
        self._storage_meter.set_ratio(used_gb / total_gb if total_gb else 0)
        self._storage_caption.setText(f"{count} ehtiyat nüsxə saxlanılır")

    def table(self) -> DataTable:
        return self._table


class RestoreConfirmDialog(QDialog):
    """Bərpa təsdiqi — "ciddi təsdiq-modalı" (spesifikasiya).

    Bərpa MÖVCUD məlumatı əvəz edir, yəni geri dönüşü yoxdur. Ona görə
    istifadəçidən ehtiyat nüsxə tarixini ƏL İLƏ yazmaq tələb olunur — "Bəli"
    düyməsinə refleks olaraq basmağın qarşısını alır.
    """

    confirmed = Signal(str)

    def __init__(
        self,
        theme: ThemeManager,
        *,
        backup_date: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._backup_date = backup_date
        self.setWindowTitle("Bərpanı təsdiq et")
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        card = Card(padding=24, spacing=16)
        layout.addWidget(card)

        card.add(title_label("Bu nöqtəyə bərpa edilsin?", size=19))
        card.add(
            body_label(
                f"{backup_date} tarixli ehtiyat nüsxə bərpa olunacaq. Bu tarixdən "
                "SONRAKI bütün məlumatlar — davamiyyət qeydləri, cərimələr, "
                "tapşırıqlar — İTİRİLƏCƏK.",
                size=13,
            )
        )

        self._confirm_input = FormField(
            "Təsdiq üçün ehtiyat nüsxə tarixini yazın",
            placeholder=backup_date,
        )
        card.add(self._confirm_input)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)
        buttons_layout.addWidget(stretch())

        cancel = secondary_button("İmtina")
        cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel)

        self._confirm = action_button("Bərpa Et")
        self._confirm.clicked.connect(self._on_confirm)
        buttons_layout.addWidget(self._confirm)
        card.add(buttons)

        # DEFOLT DÜYMƏ İMTİNADIR — bərpa MÖVCUD məlumatı əvəz edir və geri
        # dönüşü yoxdur (bax sinif başlığı). Enter-ə təsadüfən basmaq bazanı
        # BƏRPA ETMƏMƏLİDİR; ən pis halda modal bağlanır və istifadəçi onu
        # yenidən açır. Eyni qərar `MigrationConfirmDialog`-dadır.
        # `autoDefault` söndürülür ki, fokus «Bərpa Et»-ə düşdükdə Qt onu
        # müvəqqəti defolt etməsin.
        cancel.setDefault(True)
        cancel.setAutoDefault(False)
        self._confirm.setDefault(False)
        self._confirm.setAutoDefault(False)

        QWidget.setTabOrder(self._confirm_input.input_widget(), cancel)
        QWidget.setTabOrder(cancel, self._confirm)

        # İlkin fokus tarix sahəsindədir — axının ilk məntiqi addımı budur.
        self._confirm_input.focus_input()

    def _on_confirm(self) -> None:
        self._confirm_input.clear_error()
        if self._confirm_input.text().strip() != self._backup_date:
            self._confirm_input.set_error("Tarix ehtiyat nüsxə tarixi ilə üst-üstə düşmür")
            return
        self.confirmed.emit(self._backup_date)
        self.accept()


# --------------------------------------------------------------------------- #
# 17 — Sistem Sağlamlığı
# --------------------------------------------------------------------------- #


class HealthScreen(Screen):
    """Diaqnostika — DB ping, disk, NTP sapması, 1C gecikməsi, xəbərdarlıqlar.

    Signals:
        recheck_requested: "Yenidən Yoxla".
        conflicts_requested: Xəbərdarlıq kartındakı «… konflikti həll et»
            keçidi — «Sinxronizasiya Konfliktləri» ekranını açır (bax
            `set_conflict_action`).
    """

    recheck_requested = Signal()
    conflicts_requested = Signal()

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)
        #: Keçid LAZIM OLANA QƏDƏR QURULMUR — bax `set_conflict_action`.
        self._conflict_link: LinkLabel | None = None

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        self._last_check = muted_label("")
        toolbar_layout.addWidget(self._last_check)
        toolbar_layout.addWidget(stretch())
        recheck = secondary_button("Yenidən Yoxla")
        recheck.clicked.connect(self.recheck_requested)
        toolbar_layout.addWidget(recheck)
        self.add(toolbar)

        self._metrics_host = QWidget()
        self._metrics_layout = QHBoxLayout(self._metrics_host)
        self._metrics_layout.setContentsMargins(0, 0, 0, 0)
        self._metrics_layout.setSpacing(metrics.CARD_SPACING)
        self.add(self._metrics_host)

        self._latency = Card(padding=20, spacing=12)
        self._latency.add(title_label("1C sinxron gecikməsi — server üzrə", size=15))
        self._latency_rows = QVBoxLayout()
        self._latency_rows.setSpacing(8)
        latency_holder = QWidget()
        latency_holder.setLayout(self._latency_rows)
        self._latency.add(latency_holder)
        self.add(self._latency)

        self._alerts = Card(padding=20, spacing=12)
        self._alerts.add(title_label("Aktiv xəbərdarlıqlar", size=15))
        self._alerts_rows = QVBoxLayout()
        self._alerts_rows.setSpacing(12)
        alerts_holder = QWidget()
        alerts_holder.setLayout(self._alerts_rows)
        self._alerts.add(alerts_holder)
        self.add(self._alerts)

        self.body().addStretch(1)

    def set_last_check(self, text: str) -> None:
        self._last_check.setText(text)

    def set_metrics(self, items: list[tuple[str, str, str, str]]) -> None:
        """`items`: (ad, dəyər, izah, ton)."""
        clear_layout(self._metrics_layout)

        tones = {
            "success": "--color-success",
            "warning": "--color-warning",
            "danger": "--color-danger",
        }
        for name, value, caption, tone in items:
            self._metrics_layout.addWidget(
                _metric_card(self.theme, name, value, caption, tones.get(tone, "--color-success")),
                1,
            )
        self.show_content()

    def set_latencies(self, entries: list[tuple[str, str, str]]) -> None:
        clear_layout(self._latency_rows)

        tones = {
            "success": "--color-success",
            "warning": "--color-warning",
            "danger": "--color-danger",
        }
        for name, value, tone in entries:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)
            layout.addWidget(StatusDot(self.theme.color(tones.get(tone, "--color-success"))))
            layout.addWidget(mono_label(name))
            layout.addWidget(stretch())
            layout.addWidget(mono_label(value))
            self._latency_rows.addWidget(row)

    def set_alerts(self, alerts: list[tuple[str, str, str]]) -> None:
        """`alerts`: (mətn, vaxt, ton)."""
        clear_layout(self._alerts_rows)

        if not alerts:
            self._alerts_rows.addWidget(muted_label("Aktiv xəbərdarlıq yoxdur."))
            return

        tones = {"warning": "--color-warning", "danger": "--color-danger"}
        for text, time_text, tone in alerts:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)
            layout.addWidget(StatusDot(self.theme.color(tones.get(tone, "--color-warning"))))
            layout.addWidget(body_label(text, size=13), 1)
            layout.addWidget(mono_label(time_text, muted=True))
            self._alerts_rows.addWidget(row)

    def set_conflict_action(self, count: int) -> None:
        """Konflikt xəbərdarlığının GEDƏCƏYİ yeri kartın altına əlavə edir.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ AYRICA SETTER, NİYƏ `set_alerts` İÇİNDƏ DEYİL
        ──────────────────────────────────────────────────────────────────────
        `set_alerts` sətri `(mətn, vaxt, ton)` üçlüyü kimi alır və orada
        "bu sətir kliklənəndir" məlumatı üçün yer yoxdur. İmzanı dəyişmək
        maket və canlı yolun HƏR İKİSİNİ (`preview_screens._health`,
        `screen_data._health`) və mövcud testləri qırardı — halbuki əlavə
        edilən şey bir keçiddir.

        ──────────────────────────────────────────────────────────────────────
        WIDGET İCAZƏSİZ İSTİFADƏÇİDƏ QURULMUR
        ──────────────────────────────────────────────────────────────────────
        «GÖRMƏK = SƏLAHİYYƏTİN OLMASI» (bölmə 3): keçid `sync_conflicts`
        ekranına aparır və o, `can_view_employee_reports` tələb edir. Çağıran
        tərəf (`screen_data._health`) həmin flag-i yoxlayır və flag yoxdursa
        bu metodu ÇAĞIRMIR — nəticədə `LinkLabel` ümumiyyətlə YARADILMIR,
        `setEnabled(False)` ilə boz qalmır.

        `count == 0` halında mövcud keçid SİLİNİR: sonuncu konflikt həll
        olunanda xəbərdarlıq da, keçid də eyni anda yox olmalıdır.
        """
        if count <= 0:
            if self._conflict_link is not None:
                self._conflict_link.deleteLater()
                self._conflict_link = None
            return

        if self._conflict_link is None:
            link = LinkLabel("")
            link.clicked.connect(self.conflicts_requested)
            self._alerts.add(link)
            self._conflict_link = link

        text = f"{count} sinxronizasiya konfliktini həll et"
        self._conflict_link.setText(text)
        self._conflict_link.setAccessibleName(text)


# --------------------------------------------------------------------------- #
# 18 — Audit Jurnalı
# --------------------------------------------------------------------------- #


class AuditScreen(Screen):
    """Süzgəclənə bilən, DƏYİŞDİRİLƏ BİLMƏYƏN audit jurnalı.

    Signals:
        export_requested: "Excel-ə İxrac Et".
        filters_changed: Süzgəc dəyərləri.
        page_changed: Səhifə nömrəsi.
    """

    export_requested = Signal()
    filters_changed = Signal(dict)
    page_changed = Signal(int)

    def __init__(
        self,
        theme: ThemeManager,
        *,
        modules: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(theme, parent=parent)

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(12)
        self._total = muted_label("")
        toolbar_layout.addWidget(self._total)
        toolbar_layout.addWidget(stretch())
        export = secondary_button("Excel-ə İxrac Et")
        export.clicked.connect(self.export_requested)
        toolbar_layout.addWidget(export)
        self.add(toolbar)

        filters = Card(padding=16, spacing=12)
        filters_row = QWidget()
        filters_layout = QHBoxLayout(filters_row)
        filters_layout.setContentsMargins(0, 0, 0, 0)
        filters_layout.setSpacing(12)

        self._search = QLineEdit()
        self._search.setPlaceholderText("İstifadəçi və ya əməliyyat")
        self._search.setProperty("variant", "form")
        self._search.textChanged.connect(self._emit_filters)
        filters_layout.addWidget(self._search, 2)

        self._range = QLineEdit()
        # GÖSTƏRİŞDİR, NÜMUNƏ DEYİL. Əvvəlki mətn («01.08.2026 — 12.08.2026»)
        # qutunu DOLU göstərirdi; bu isə yalnız qutunun NƏ olduğunu deyir.
        # Etiketsiz buraxıla bilməzdi: yanındakı axtarış qutusunun göstərişi
        # var və filtr sırasında adsız qalan tək qutu «nə üçündür?» sualını
        # doğurur — sətir etiketi yoxdur, qutunun özü etiketdir.
        self._range.setPlaceholderText("Tarix aralığı")
        self._range.setProperty("variant", "form")
        filters_layout.addWidget(self._range, 1)

        self._module = QComboBox()
        self._module.setProperty("variant", "form")
        self._module.addItem("Modul: Hamısı")
        self._module.addItems(modules)
        self._module.currentTextChanged.connect(self._emit_filters)
        filters_layout.addWidget(self._module, 1)

        self._critical_only = ToggleSwitch(theme)
        self._critical_only.toggled.connect(self._emit_filters)
        critical_box = QWidget()
        critical_layout = QHBoxLayout(critical_box)
        critical_layout.setContentsMargins(0, 0, 0, 0)
        critical_layout.setSpacing(8)
        critical_layout.addWidget(body_label("Kritik əməliyyatlar", size=13, wrap=False))
        critical_layout.addWidget(self._critical_only)
        filters_layout.addWidget(critical_box)

        filters.add(filters_row)
        self.add(filters)

        self._result_count = muted_label("")
        self.add(self._result_count)

        self._table = DataTable(
            [
                Column("Vaxt", 140, mono=True),
                Column("İstifadəçi", 180),
                Column("Əməliyyat", 240),
                Column("Modul", 150),
                Column("Detal"),
            ],
            theme,
            footnote="Audit yazıları dəyişdirilə və silinə bilməz.",
        )
        self.add(self._table)

        self._pagination = QWidget()
        self._pagination_layout = QHBoxLayout(self._pagination)
        self._pagination_layout.setContentsMargins(0, 0, 0, 0)
        self._pagination_layout.setSpacing(8)
        self.add(self._pagination)

    def _emit_filters(self) -> None:
        self.filters_changed.emit(
            {
                "search": self._search.text(),
                "range": self._range.text(),
                "module": self._module.currentText(),
                "critical_only": self._critical_only.isChecked(),
            }
        )

    def set_total(self, text: str) -> None:
        self._total.setText(text)

    def set_entries(self, entries: list[dict[str, str]], *, result_text: str) -> None:
        self._result_count.setText(result_text)
        self._table.clear()

        if not entries:
            self.show_empty(
                icon_name="file",
                title="Uyğun yazı tapılmadı",
                message="Süzgəc şərtlərini genişləndirin və ya tarix aralığını dəyişin.",
            )
            return

        for entry in entries:
            self._table.add_row(
                [
                    mono_label(entry.get("time", "")),
                    entry.get("user", ""),
                    entry.get("action", ""),
                    entry.get("module", ""),
                    muted_label(entry.get("detail", "")),
                ]
            )
        self.show_content()

    def set_pagination(self, current: int, total: int) -> None:
        clear_layout(self._pagination_layout)

        self._pagination_layout.addStretch(1)

        def add_button(text: str, page: int, *, enabled: bool = True) -> None:
            button = secondary_button(text)
            # Dar düymə: geniş yan doldurma 46px-lik enə sığmır (bax QSS).
            button.setProperty("compact", "true")
            button.setFixedWidth(48)
            button.setEnabled(enabled)
            button.clicked.connect(lambda _=False, p=page: self.page_changed.emit(p))
            self._pagination_layout.addWidget(button)

        add_button("‹", max(1, current - 1), enabled=current > 1)
        # Yalnız yaxın səhifələr göstərilir — 18 səhifəlik jurnalda hamısını
        # sıralamaq alət panelini doldurardı.
        for page in range(max(1, current - 1), min(total, current + 1) + 1):
            add_button(str(page), page)
        if total > current + 1:
            self._pagination_layout.addWidget(muted_label("…"))
            add_button(str(total), total)
        add_button("›", min(total, current + 1), enabled=current < total)

        self._pagination_layout.addStretch(1)

    def table(self) -> DataTable:
        return self._table


# --------------------------------------------------------------------------- #
# 19 — Ayarlar
# --------------------------------------------------------------------------- #


class SettingsScreen(Screen):
    """Görünüş, dil, bildirişlər və təhlükəsizlik.

    Signals:
        theme_selected: "light" / "dark" / "system".
        language_selected: Dil kodu.
        notification_changed: (açar, aktiv).
        password_change_requested / sessions_close_requested: düymələr.
        saved: Bütün dəyərlər.
    """

    theme_selected = Signal(str)
    notification_changed = Signal(str, bool)
    password_change_requested = Signal()
    sessions_close_requested = Signal()
    saved = Signal(dict)

    _THEME_OPTIONS: Final = (
        ("light", "İşıqlı"),
        ("dark", "Qaranlıq"),
        ("system", "Sistemə uyğun"),
    )

    _NOTIFICATIONS: Final = (
        (
            "pending_requests",
            "Təsdiq gözləyən sorğular",
            "Növbəyə yeni sorğu düşdükdə səsli bildiriş",
        ),
        (
            "server_alerts",
            "Server xəbərdarlıqları",
            "1C bağlantısı kəsildikdə masaüstü bildirişi",
        ),
        (
            "daily_digest",
            "Gündəlik xülasə e-poçtu",
            "Hər gün 19:00-da davamiyyət hesabatı",
        ),
    )

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)
        self._theme_buttons: dict[str, QPushButton] = {}
        self._notification_toggles: dict[str, ToggleSwitch] = {}

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.addWidget(stretch())
        save = action_button("Yadda Saxla")
        save.clicked.connect(lambda: self.saved.emit(self.collected()))
        toolbar_layout.addWidget(save)
        self.add(toolbar)

        self.add(self._build_appearance())
        self.add(self._build_notifications())
        self.add(self._build_security())
        self.body().addStretch(1)

    def _build_appearance(self) -> Card:
        card = Card(padding=20, spacing=12)
        card.add(title_label("Görünüş", size=15))

        options = QWidget()
        options_layout = QHBoxLayout(options)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(12)

        for key, label in self._THEME_OPTIONS:
            button = secondary_button(label)
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, k=key: self.select_theme(k))
            options_layout.addWidget(button)
            self._theme_buttons[key] = button
        options_layout.addStretch(1)
        card.add(options)

        card.add(Divider())
        # DİL SEÇİCİSİ DEYİL, GÖSTƏRİCİDİR.
        #
        # Spesifikasiya (bölmə 9) açıq yazır: «dil seçimi hazırda göstərilmir,
        # çünki yalnız bir dil var». Bazada da qayda eynidir —
        # `user_preferences.language` sütununda `CHECK (language IN ('az'))`.
        #
        # Əvvəl burada TƏK bəndli açılan siyahı vardı: istifadəçi onu açır,
        # bir seçim görür, bağlayır — yəni idarəedici görünüşü daşıyan, lakin
        # heç nə seçdirməyən bir element. `language_selected` siqnalı da elə
        # buna görə heç vaxt işə düşmürdü. Sətir QALIR (istifadəçi cari dili
        # görməlidir), idarəedici isə göstəriciyə çevrilib.
        # `FormField` YALNIZ redaktə edilə bilən idarəediciləri qəbul edir
        # (tip imzası ilə qorunur) — göstərici sətri əl ilə qurulur.
        language_row = QWidget()
        language_layout = QHBoxLayout(language_row)
        language_layout.setContentsMargins(0, 0, 0, 0)
        language_layout.setSpacing(12)
        language_layout.addWidget(field_label("İnterfeys dili"))
        language_layout.addWidget(stretch())
        self._language = body_label("Azərbaycan dili", size=13, wrap=False)
        language_layout.addWidget(self._language)
        card.add(language_row)
        return card

    def select_theme(self, key: str) -> None:
        for option, button in self._theme_buttons.items():
            button.setProperty("active", "true" if option == key else "false")
            button.setChecked(option == key)
            style = button.style()
            style.unpolish(button)
            style.polish(button)
        self.theme_selected.emit(key)

    def _build_notifications(self) -> Card:
        card = Card(padding=20, spacing=12)
        card.add(title_label("Bildirişlər", size=15))

        for index, (key, title, description) in enumerate(self._NOTIFICATIONS):
            if index:
                card.add(Divider())
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)

            text_box = QWidget()
            text_layout = QVBoxLayout(text_box)
            text_layout.setContentsMargins(0, 0, 0, 0)
            text_layout.setSpacing(4)
            text_layout.addWidget(body_label(title, size=13, wrap=False))
            text_layout.addWidget(muted_label(description))
            layout.addWidget(text_box)
            layout.addWidget(stretch())

            toggle = ToggleSwitch(self.theme, checked=True)
            toggle.toggled.connect(
                lambda checked, k=key: self.notification_changed.emit(k, checked)
            )
            self._notification_toggles[key] = toggle
            layout.addWidget(toggle)
            card.add(row)
        return card

    def set_notification_prefs(self, prefs: dict[str, bool]) -> None:
        """Saxlanmış açar vəziyyətlərini ekrana qaytarır (miqrasiya 058).

        AÇAR YOXDURSA KANAL AÇIQ QALIR: sətri olmayan istifadəçi bugünkü
        davranışı görməlidir — əks qayda miqrasiya anında hamının bildirişini
        sükutla kəsərdi. Eyni əsaslandırma repo-dadır.

        Siqnal bloklanır: `setChecked` `toggled`-i işə salır və o, yükləmə
        anında «istifadəçi dəyişdi» kimi oxunardı — nəticədə ekran açılan kimi
        yazı əməliyyatı baş verərdi.
        """
        for key, toggle in self._notification_toggles.items():
            toggle.blockSignals(True)
            toggle.setChecked(prefs.get(key, True))
            toggle.blockSignals(False)

    def _build_security(self) -> Card:
        card = Card(padding=20, spacing=12)
        card.add(title_label("Təhlükəsizlik", size=15))

        password_row = QWidget()
        password_layout = QHBoxLayout(password_row)
        password_layout.setContentsMargins(0, 0, 0, 0)
        password_text = QWidget()
        password_text_layout = QVBoxLayout(password_text)
        password_text_layout.setContentsMargins(0, 0, 0, 0)
        password_text_layout.setSpacing(4)
        password_text_layout.addWidget(body_label("Şifrə", size=13, wrap=False))
        self._password_age = muted_label("")
        password_text_layout.addWidget(self._password_age)
        password_layout.addWidget(password_text)
        password_layout.addWidget(stretch())
        change = secondary_button("Şifrəni Dəyiş")
        change.clicked.connect(self.password_change_requested)
        password_layout.addWidget(change)
        card.add(password_row)
        card.add(Divider())

        lock_row = QWidget()
        lock_layout = QHBoxLayout(lock_row)
        lock_layout.setContentsMargins(0, 0, 0, 0)
        lock_text = QWidget()
        lock_text_layout = QVBoxLayout(lock_text)
        lock_text_layout.setContentsMargins(0, 0, 0, 0)
        lock_text_layout.setSpacing(4)
        lock_text_layout.addWidget(body_label("Avtomatik kilid", size=13, wrap=False))
        lock_text_layout.addWidget(muted_label("Hərəkətsizlik zamanı proqram kilidlənir"))
        lock_layout.addWidget(lock_text)
        lock_layout.addWidget(stretch())
        self._lock_timeout = QComboBox()
        self._lock_timeout.setProperty("variant", "form")
        self._lock_timeout.addItems(["5 dəq", "10 dəq", "15 dəq", "30 dəq"])
        self._lock_timeout.setCurrentText("15 dəq")
        self._lock_timeout.setFixedWidth(140)
        lock_layout.addWidget(self._lock_timeout)
        card.add(lock_row)
        card.add(Divider())

        sessions_row = QWidget()
        sessions_layout = QHBoxLayout(sessions_row)
        sessions_layout.setContentsMargins(0, 0, 0, 0)
        sessions_text = QWidget()
        sessions_text_layout = QVBoxLayout(sessions_text)
        sessions_text_layout.setContentsMargins(0, 0, 0, 0)
        sessions_text_layout.setSpacing(4)
        sessions_text_layout.addWidget(body_label("Aktiv sessiyalar", size=13, wrap=False))
        self._sessions_label = muted_label("")
        sessions_text_layout.addWidget(self._sessions_label)
        sessions_layout.addWidget(sessions_text)
        sessions_layout.addWidget(stretch())
        close_all = secondary_button("Hamısını Bağla")
        close_all.clicked.connect(self.sessions_close_requested)
        sessions_layout.addWidget(close_all)
        card.add(sessions_row)
        return card

    def set_security_info(self, *, password_age: str, sessions: str) -> None:
        self._password_age.setText(password_age)
        self._sessions_label.setText(sessions)
        self.show_content()

    def set_notification(self, key: str, enabled: bool) -> None:
        toggle = self._notification_toggles.get(key)
        if toggle is not None:
            toggle.setChecked(enabled)

    def collected(self) -> dict[str, object]:
        active_theme = next(
            (key for key, button in self._theme_buttons.items() if button.isChecked()),
            "system",
        )
        return {
            "theme": active_theme,
            # Dil DƏYİŞDİRİLƏ BİLMİR (bax `_build_appearance`) — payload-da
            # yenə göndərilir ki, çağıran tərəf tam vəziyyəti görsün.
            "language": self._language.text(),
            "notifications": {
                key: toggle.isChecked() for key, toggle in self._notification_toggles.items()
            },
            "lock_timeout": self._lock_timeout.currentText(),
        }


# --------------------------------------------------------------------------- #
# 20 — ROOT İdarə Mərkəzi
# --------------------------------------------------------------------------- #


#: Drive bağlantısı ekranının kontekstual köməyi (audit G-4).
#:
#: Mətn EKRANIN YANINDA yaşayır, mərkəzi kömək kataloqunda deyil — səbəbi
#: `widgets/help_hint.HelpButton` başlığındadır: hesabın dəyişdirilməsi
#: keçmiş SÜBUTLARIN harada qaldığına təsir edir və bu xəbərdarlıq sinif
#: başlığı ilə bir yerdə redaktə olunmalıdır.
DRIVE_HELP_TITLE: Final = "Drive Bağlantısı"

DRIVE_HELP_INTRO: Final = (
    "Cərimə sübut şəkilləri Google Drive hesabında saxlanılır. Bu ekran "
    "hansı hesabın işlədildiyini göstərir və onu dəyişməyə imkan verir. "
    "Diqqət: hesabı dəyişmək keçmiş sübutların yerini dəyişmir."
)

DRIVE_HELP_STEPS: Final[tuple[str, ...]] = (
    "«Google Hesabı Qoş» sistem brauzerində razılıq səhifəsi açır. Brauzer "
    "açılmasa (kiosk və ya terminal quraşdırması), ekranda görünən ünvanı "
    "seçib başqa cihazda açmaq kifayətdir — bağlantı yenə tamamlanır.",
    "Razılıq verilənə qədər ekran gözləyir. «Ləğv Et» axını dayandırır və "
    "heç bir hesab yazılmır; yarımçıq qalmış razılıq sistemdə iz buraxmır.",
    "Hesab qoşulduqdan sonra düymə «Hesabı Dəyiş»ə çevrilir. Yeni hesab "
    "köhnəsini ARXİVLƏYİR: keçmiş cərimə şəkilləri köhnə hesabda qalır və "
    "oradan göstərilməyə davam edir. Köhnə hesabı Google tərəfdən silmək "
    "həmin sübutları GERİ QAYTARILMAZ şəkildə itirər.",
    "Kvota sətri hesabda qalan yeri göstərir. Yer bitəndə şəkil yüklənmir — "
    "cərimə yenə də normal yaranır, şəkil isə lokal növbədə gözləyir və yer "
    "açılan kimi göndərilir. Yəni xəbərdarlıq gecikdirilə bilər, amma "
    "nəzərdən qaçırılmamalıdır.",
    "«Bağlantı tarixçəsi» hansı hesabın nə vaxt işlədildiyini saxlayır və "
    "sətirləri silinmir: mübahisəli cərimənin şəklinin hansı hesabda "
    "olduğunu yalnız bu jurnal göstərir.",
)


class DriveConnectionScreen(Screen):
    """Cərimə sübut şəkilləri üçün Google Drive hesabı (miqrasiya 002).

    Signals:
        connect_requested: `[Google hesabı qoşun]`.
        cancel_requested: Gözləyən razılıq axını ləğv edilir.

    ──────────────────────────────────────────────────────────────────────
    NİYƏ ÜNVAN MƏTN KİMİ DƏ GÖSTƏRİLİR
    ──────────────────────────────────────────────────────────────────────
    Razılıq ünvanı sistem brauzerində açılır, lakin kiosk/terminal
    quraşdırmalarında `webbrowser.open()` heç nə etməyə bilər. Ünvan ekranda
    seçilə bilən mətn kimi qalırsa, administrator onu başqa cihazda aça bilər
    — brauzerin açılmaması bağlantını qeyri-mümkün etməməlidir.

    ──────────────────────────────────────────────────────────────────────
    NİYƏ HESAB DƏYİŞMƏK XƏBƏRDARLIQ TƏLƏB EDİR
    ──────────────────────────────────────────────────────────────────────
    Yeni hesab qoşulduqda köhnəsi ARXİVLƏNİR, silinmir: köhnə şəkillər hələ
    də köhnə hesabdadır və oradan oxunur. Administrator bunu qoşmazdan ƏVVƏL
    bilməlidir, çünki köhnə hesabı bağlamaq keçmiş sübutları itirər.
    """

    connect_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)

        self._status_card = Card(padding=20, spacing=12)
        self._status_card.add(title_label("Aktiv hesab", size=15))

        status_row = QWidget()
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(12)
        self._status_dot = StatusDot(theme.color("--color-text-muted"))
        status_layout.addWidget(self._status_dot)
        self._account = body_label("Hesab qoşulmayıb", size=13, wrap=False)
        status_layout.addWidget(self._account)
        status_layout.addWidget(stretch())
        self._status_chip = Chip("Qoşulmayıb", "neutral")
        status_layout.addWidget(self._status_chip)
        self._status_card.add(status_row)

        self._quota = muted_label("Kvota məlumatı yoxdur")
        self._status_card.add(self._quota)
        self._status_card.add(Divider())
        self._status_card.add(
            muted_label(
                "Yeni hesab qoşulduqda köhnəsi arxivlənir. Keçmiş cərimə şəkilləri "
                "köhnə hesabda qalır və oradan göstərilməyə davam edir — köhnə "
                "hesabı silməyin."
            )
        )

        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(12)
        actions_layout.addWidget(stretch())

        # Kontekstual kömək (audit G-4) — kartdakı qeyd yalnız arxivlənməni
        # yazır; razılıq axınının brauzersiz tamamlanması və kvota bitəndə nə
        # baş verdiyi burada izah olunur.
        self._help = HelpButton(
            theme,
            title=DRIVE_HELP_TITLE,
            intro=DRIVE_HELP_INTRO,
            steps=DRIVE_HELP_STEPS,
        )
        actions_layout.addWidget(self._help)

        self._cancel = secondary_button("Ləğv Et")
        self._cancel.clicked.connect(self.cancel_requested)
        self._cancel.setVisible(False)
        actions_layout.addWidget(self._cancel)
        self._connect = action_button("Google Hesabı Qoş")
        self._connect.clicked.connect(self.connect_requested)
        actions_layout.addWidget(self._connect)
        self._status_card.add(actions)
        self.add(self._status_card)

        # Razılıq gedərkən görünən kart — ünvan + gözləmə mətni.
        self._pending = Card(padding=20, spacing=12)
        self._pending.add(title_label("Brauzerdə razılıq gözlənilir", size=15))
        self._pending.add(
            muted_label(
                "Açılan səhifədə Google hesabınızı seçin və KompasOS-a icazə verin. "
                "Səhifə açılmadısa aşağıdakı ünvanı brauzerə köçürün."
            )
        )
        self._auth_url = QLineEdit()
        self._auth_url.setReadOnly(True)
        self._auth_url.setProperty("variant", "form")
        self._pending.add(self._auth_url)
        self._pending.setVisible(False)
        self.add(self._pending)

        self._history = Card(padding=20, spacing=12)
        self._history.add(title_label("Bağlantı tarixçəsi", size=15))
        self._history_rows = QVBoxLayout()
        self._history_rows.setSpacing(8)
        holder = QWidget()
        holder.setLayout(self._history_rows)
        self._history.add(holder)
        self.add(self._history)
        self.body().addStretch(1)

    def help_button(self) -> HelpButton:
        """Kontekstual kömək düyməsi — kontroller/testlər üçün."""
        return self._help

    # ------------------------------- doldurma -------------------------------- #

    def set_active(
        self,
        *,
        account: str | None,
        status_text: str,
        tone: ChipTone,
        quota_text: str,
    ) -> None:
        """Aktiv bağlantı. `account=None` → "qoşulmayıb" vəziyyəti."""
        self._account.setText(account or "Hesab qoşulmayıb")
        self._status_chip.setText(status_text)
        self._status_chip.set_tone(tone)
        self._quota.setText(quota_text)
        self._connect.setText("Hesabı Dəyiş" if account else "Google Hesabı Qoş")
        self.show_content()

    def set_history(self, rows: list[tuple[str, str, str]]) -> None:
        """`rows`: (hesab, status, tarix)."""
        clear_layout(self._history_rows)
        for account, status, when in rows:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)
            layout.addWidget(body_label(account, size=13, wrap=False))
            layout.addWidget(stretch())
            layout.addWidget(mono_label(when))
            layout.addWidget(Chip(status, "success" if status == "Aktiv" else "neutral"))
            self._history_rows.addWidget(row)

    def show_pending(self, auth_url: str) -> None:
        """Razılıq gözləmə vəziyyəti — düymə bloklanır, ünvan göstərilir."""
        self._auth_url.setText(auth_url)
        self._pending.setVisible(True)
        self._connect.setEnabled(False)
        self._cancel.setVisible(True)

    def clear_pending(self) -> None:
        self._pending.setVisible(False)
        self._auth_url.clear()
        self._connect.setEnabled(True)
        self._cancel.setVisible(False)


#: ROOT İdarə Mərkəzinin kontekstual köməyi (audit G-4).
#:
#: Mətn EKRANIN YANINDA yaşayır, mərkəzi kömək kataloqunda deyil — səbəbi
#: `widgets/help_hint.HelpButton` başlığındadır: bu ekranın hər bölməsi ayrı
#: bir YAZI hədəfinə gedir (limit sətri ↔ modul açarı ↔ mağaza əhatəsi ↔
#: flag registri) və hansının «Tətbiq Et» gözlədiyi yalnız burada, kodun
#: yanında dəqiq saxlanıla bilər.
ROOT_HELP_TITLE: Final = "ROOT İdarə Mərkəzi"

ROOT_HELP_INTRO: Final = (
    "Bu ekran sistemin limitlərini, modul açarlarını və icazə registrini "
    "idarə edir. Dəyişikliklər bütün mağazalara aiddir və hər biri audit "
    "jurnalına yazılır."
)

ROOT_HELP_STEPS: Final[tuple[str, ...]] = (
    "«Dinamik limitlər» — taymautlar, hədlər və dərəcələr. Dəyər «Tətbiq Et» "
    "basılana qədər yazılmır; yazıldıqdan sonra isə YALNIZ yeni əməliyyatlara "
    "tətbiq olunur — keçmiş qeydlər yenidən hesablanmır.",
    "«Fasilə Parametrləri» nahar və çay fasiləsinin müddətini və gündəlik say "
    "həddini saxlayır. Müddət yalnız işçi ekranındakı göstəricidir: gecikmə "
    "və cərimə düsturuna TƏSİR ETMİR, hədd aşılanda əməliyyat bloklanmır, "
    "yalnız xəbərdarlıq göstərilir.",
    "«Face Control» bölməsində açılan mağaza üz təsdiqini DƏRHAL alır — bu "
    "bölmə «Tətbiq Et» gözləmir. Heç bir mağaza seçilməyibsə modul qlobal "
    "açara tabe olur, yəni boş siyahı «söndürülüb» demək deyil.",
    "«Modul açarları» — söndürmə YALNIZ yeni qeydlərin yaranmasını dayandırır; "
    "mövcud qeydlər axınını tamamlayır, silinmir və hesabatlardan çıxmır. "
    "Struktur-kritik modulda səbəb yazmaq məcburidir və mətn audit jurnalına "
    "olduğu kimi düşür.",
    "«İcazə registri» yeni icazə flag-i yaradır; ad «can_» ilə başlamalıdır, "
    "kateqoriya isə onun İcazə Matrisində hansı qrupda görünəcəyini təyin "
    "edir. Bu ekranda flag-i silmək yolu YOXDUR — səhv yazılmış ad matrisdə "
    "qalır.",
    "«Tətbiq Et» limitləri və modul açarlarını bir anda göndərir. Bölmələrin "
    "öz «Yadda Saxla» düyməsi eyni yazı yolundan keçir, sadəcə yalnız həmin "
    "bölmənin sahələrini daşıyır — nəticə fərqli olmur.",
)


#: `QSpinBox` 32-bitdir — daha böyük hədd `OverflowError` atır.
#:
#: ──────────────────────────────────────────────────────────────────────────
#: BU SABİT ROOT PARAMETRİ DEYİL — Qt-nin TİP HÜDUDUDUR
#: ──────────────────────────────────────────────────────────────────────────
#: `IMAGE_CACHE_MAX_BYTES` tavanı 8 GiB-dir (`8589934592`, migrations/032) və
#: `QSpinBox.setRange()` onu qəbul EDƏ BİLMİR. Nəticə sadəcə çirkin görünüş
#: deyildi: istisna `RootControlController._fill`-i ORTADA dayandırırdı, ona
#: görə ROOT İdarə Mərkəzində limitlərin bir hissəsi görünür, fasilə
#: parametrləri, modul açarları, icazə registri və brendinq bölmələri isə
#: ÜMUMİYYƏTLƏ qurulmurdu — panel «boş» görünürdü.
INT32_MAX: Final = 2_147_483_647


class RootControlScreen(Screen):
    """Dinamik limitlər, modul açarları və icazə registri.

    Signals:
        applied: Bütün dəyişikliklər.
        module_toggled: (modul açarı, aktiv, yazılı təsdiq mətni).
        flag_created: (flag kodu, kateqoriya, hardlock).

    ──────────────────────────────────────────────────────────────────────
    STRUKTUR-KRİTİK MODULLAR
    ──────────────────────────────────────────────────────────────────────
    Bəzi modulları söndürmək məlumat itkisinə səbəb olmur, lakin iş axınını
    dayandırır (məs. Kamera Təsdiqi söndürülərsə STEP1-3 və Morning
    Check-in axınları yeni instansiya yarada bilmir). Bölmə 3 belə modul
    üçün "sadə bir-kliklik toggle" QADAĞAN edir: əlavə xəbərdarlıq modalı
    VƏ yazılı təsdiq sahəsi tələb olunur.

    Ona görə `module_toggled` üçüncü arqument kimi TƏSDİQ MƏTNİNİ daşıyır
    (struktur olmayan modullarda boş sətir). Mətnin UZUNLUĞU burada
    yoxlanılmır — o qayda `RootControlUseCase.set_module_enabled`-dədir və
    ekranı yan keçən hər yol üçün də işləyir. Burada yalnız "boş mətnlə
    davam etmə" yoxlanılır ki, istifadəçi səhvən Enter basmasın.
    """

    applied = Signal(dict)
    module_toggled = Signal(str, bool, str)
    flag_created = Signal(str, str, bool)
    #: Face Control mağaza əhatəsi (facecontrol.md bənd 15) — (store_id, aktiv).
    #:
    #: NİYƏ `applied` SÖZLÜYÜNƏ QOŞULMADI: `collected()["limits"]` yalnız
    #: `SystemLimitKey` dəyərlərini daşıyır və `test_root_control_uses_the_
    #: shared_key_namespace` məhz bunu yoxlayır. Mağaza əhatəsi isə
    #: `system_limits` sətri DEYİL — o, ayrıca `face_control_store_scope`
    #: cədvəlidir (soft delete ilə). Onu limit ad məkanına salmaq iki fərqli
    #: yazı hədəfini bir sözlükdə qarışdırmaq olardı.
    face_scope_changed = Signal(str, bool)
    #: Şirkət kimliyi (TENANT-1 Faza 2) — `dict` (`company_name`,
    #: `accent_color`, `clear_accent`).
    #:
    #: NİYƏ `applied` SÖZLÜYÜNƏ QOŞULMADI: `collected()["limits"]` yalnız
    #: `SystemLimitKey` dəyərlərini daşıyır və `test_root_control_uses_the_
    #: shared_key_namespace` məhz bunu yoxlayır. Brendinq isə `system_limits`
    #: sətri DEYİL — ayrıca `tenant_branding` cədvəlidir (migrations/064).
    #: `face_scope_changed` ilə eyni qərar.
    branding_changed = Signal(dict)
    #: Telegram bot konfiqurasiyası (CHAT-1 Faza 3) — `dict` (`bot_token`,
    #: `chat_id`).
    #:
    #: `applied` SÖZLÜYÜNƏ QOŞULMADI — `face_scope_changed` və
    #: `branding_changed` ilə eyni səbəb: `collected()["limits"]` yalnız
    #: `SystemLimitKey` dəyərlərini daşıyır, Telegram ayarları isə ayrıca
    #: `telegram_config` cədvəlidir (migrations/068). Üstəlik burada SİRR var:
    #: token-i ümumi «Tətbiq Et» sözlüyünə qatmaq onu hər tətbiq
    #: əməliyyatında ötürərdi.
    telegram_saved = Signal(dict)
    #: Aktiv/Deaktiv keçidi — token TOXUNULMUR (bax use case).
    telegram_active_changed = Signal(bool)
    telegram_test_requested = Signal()

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)
        self._limit_inputs: dict[str, QSpinBox] = {}
        self._limit_texts: dict[str, QLineEdit] = {}
        self._break_inputs: dict[str, QSpinBox] = {}
        self._module_toggles: dict[str, ToggleSwitch] = {}
        self._structural: set[str] = set()
        self._face_scope_toggles: dict[str, ToggleSwitch] = {}

        banner = Card(padding=16, spacing=8)
        banner_row = QWidget()
        banner_layout = QHBoxLayout(banner_row)
        banner_layout.setContentsMargins(0, 0, 0, 0)
        banner_layout.setSpacing(12)
        banner_layout.addWidget(Chip("ROOT rejimi", "danger"))
        banner_layout.addWidget(body_label("Bütün əməliyyatlar audit jurnalına yazılır.", size=13))
        banner_layout.addWidget(stretch())

        # Kontekstual kömək (audit G-4) — ekranın bölmələri FƏRQLİ yazı
        # hədəflərinə gedir (limit sətri, modul açarı, mağaza əhatəsi, flag
        # registri) və hansının «Tətbiq Et» gözlədiyi ekranda görünmürdü.
        self._help = HelpButton(
            theme,
            title=ROOT_HELP_TITLE,
            intro=ROOT_HELP_INTRO,
            steps=ROOT_HELP_STEPS,
        )
        banner_layout.addWidget(self._help)

        apply_button = action_button("Tətbiq Et")
        apply_button.clicked.connect(lambda: self.applied.emit(self.collected()))
        banner_layout.addWidget(apply_button)
        banner.add(banner_row)
        self.add(banner)

        self._limits = Card(padding=20, spacing=12)
        self._limits.add(title_label("Dinamik limitlər", size=15))
        self._limits_rows = QVBoxLayout()
        self._limits_rows.setSpacing(12)
        limits_holder = QWidget()
        limits_holder.setLayout(self._limits_rows)
        self._limits.add(limits_holder)
        self.add(self._limits)

        self.add(self._build_break_card())
        self.add(self._build_face_card())
        self.add(self._build_branding_card())
        self.add(self._build_telegram_card())

        self._modules = Card(padding=20, spacing=12)
        self._modules.add(title_label("Modul açarları", size=15))
        self._modules_rows = QVBoxLayout()
        self._modules_rows.setSpacing(12)
        modules_holder = QWidget()
        modules_holder.setLayout(self._modules_rows)
        self._modules.add(modules_holder)
        self._modules.add(
            muted_label("Struktur-kritik modulları söndürərkən əlavə təsdiq tələb olunur.")
        )
        self.add(self._modules)

        self.add(self._build_registry())
        self.body().addStretch(1)

    def help_button(self) -> HelpButton:
        """Kontekstual kömək düyməsi — kontroller/testlər üçün."""
        return self._help

    def _build_break_card(self) -> Card:
        """«Fasilə Parametrləri» — Nahar/Çay (nahar.md GUI, bənd 1).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ AYRICA BÖLMƏ, «DİNAMİK LİMİTLƏR» SİYAHISINDA DEYİL
        ──────────────────────────────────────────────────────────────────────
        Texniki cəhətdən bu dörd açar da adi `system_limits` sətridir və
        yuxarıdakı siyahıda AVTOMATİK görünərdi. Lakin nahar.md onları
        adbaad ayrıca ekran bölməsi kimi tələb edir və səbəb praktikdir:
        166 limitlik siyahıda «nahar neçə dəqiqədir?» sualının cavabını
        tapmaq üçün Root sürüşdürüb axtarmalı olardı.

        HƏR AÇAR YALNIZ BİR YERDƏ REDAKTƏ OLUNUR: kontroller bu dörd sətri
        yuxarıdakı siyahıdan ÇIXARIB bura yönəldir (bax
        `controllers/root_control._fill`). İki yerdə göstərsəydik, iki
        müxtəlif dəyər yazıb «Tətbiq Et» basmaq mümkün olardı və hansının
        qazandığı düymələrin sırasından asılı qalardı.
        """
        card = Card(padding=20, spacing=12)
        card.add(title_label("Fasilə Parametrləri", size=15))
        card.add(
            muted_label(
                "Nahar və Çay fasilələri ümumi «İcazə Növləri» kataloqundan AYRIDIR — "
                "onları yalnız Root dəyişə bilər."
            )
        )

        self._break_rows = QVBoxLayout()
        self._break_rows.setSpacing(12)
        holder = QWidget()
        holder.setLayout(self._break_rows)
        card.add(holder)

        card.add(Divider())
        card.add(
            muted_label(
                "Müddət yalnız işçi ekranındakı məlumat göstəricisidir — gecikmə/cərimə "
                "düsturuna TƏSİR ETMİR. Gündəlik say həddi aşılanda əməliyyat "
                "BLOKLANMIR, yalnız xəbərdarlıq göstərilir."
            )
        )

        save_row = QWidget()
        save_layout = QHBoxLayout(save_row)
        save_layout.setContentsMargins(0, 0, 0, 0)
        save_layout.addWidget(stretch())
        save = action_button("Yadda Saxla")
        # Yalnız BU bölmənin sahələri göndərilir. Ümumi «Tətbiq Et» də onları
        # daşıyır (`collected()`), yəni Root hansı düyməni basdığından asılı
        # olmayaraq eyni nəticəni alır — sadəcə bu düymə daha yaxındır.
        save.clicked.connect(lambda: self.applied.emit({"limits": self._collected_breaks()}))
        save_layout.addWidget(save)
        card.add(save_row)
        return card

    def _collected_breaks(self) -> dict[str, int | str]:
        return {key: spin.value() for key, spin in self._break_inputs.items()}

    # ---------------------- Telegram bildirişləri (CHAT-1) ------------------- #

    def _build_telegram_card(self) -> Card:
        """«Telegram Bildirişləri» — bot token, chat ID, aktivlik, test.

        ──────────────────────────────────────────────────────────────────────
        TOKEN SAHƏSİ BOŞ BAŞLAYIR VƏ CARİ DƏYƏRİ GÖSTƏRMİR
        ──────────────────────────────────────────────────────────────────────
        Yanındakı etiket yalnız MASKANI göstərir (`••••1234`). Sahəni cari
        token ilə doldurmaq onu ekran-paylaşımında və skrinşotda ifşa edərdi,
        halbuki Root-un ona baxmağa ehtiyacı yoxdur — o, ya botu DƏYİŞİR,
        ya da toxunmur.

        Nəticə: boş sahə «dəyişmə» deməkdir; `[Botu Dəyiş]` isə yeni token
        TƏLƏB EDİR (use case 40 simvoldan qısasını rədd edir).

        ──────────────────────────────────────────────────────────────────────
        AKTİVLİK AÇARI «TƏTBİQ ET» GÖZLƏMİR
        ──────────────────────────────────────────────────────────────────────
        `face_scope_changed` ilə eyni qərar: aç/bağla xarakterli seçim toplu
        tətbiq addımından sonra göstərilsəydi, Root botun FAKTİKİ vəziyyətini
        ekranda görməzdi.
        """
        card = Card(padding=20, spacing=12)
        card.add(title_label("Telegram Bildirişləri", size=15))
        card.add(
            muted_label(
                "YALNIZ «Texniki Dəstək» mesajları Telegram-a düşür. «Daxili Müraciət» "
                "şirkətin öz növbəsindədir və kənara ÇIXMIR."
            )
        )

        self._telegram_state = muted_label("Bot qurulmayıb.")
        card.add(self._telegram_state)
        card.add(Divider())

        self._telegram_token = QLineEdit()
        self._telegram_token.setPlaceholderText("Yeni bot token (dəyişmirsinizsə boş buraxın)")
        self._telegram_token.setProperty("variant", "form")
        # Token yazılarkən də görünmür: Root onu adətən yanında adam olan
        # kompüterdə yapışdırır.
        self._telegram_token.setEchoMode(QLineEdit.EchoMode.Password)
        card.add(field_label("Bot Token"))
        card.add(self._telegram_token)

        self._telegram_chat = QLineEdit()
        self._telegram_chat.setPlaceholderText("Qrupun və ya kanalın chat ID-si")
        self._telegram_chat.setProperty("variant", "form")
        card.add(field_label("Chat ID"))
        card.add(self._telegram_chat)

        active_row = QWidget()
        active_layout = QHBoxLayout(active_row)
        active_layout.setContentsMargins(0, 0, 0, 0)
        active_layout.setSpacing(12)
        active_layout.addWidget(plain_label("Aktiv"))
        active_layout.addWidget(stretch())
        self._telegram_active = ToggleSwitch(self._theme)
        self._telegram_active.toggled.connect(self.telegram_active_changed)
        active_layout.addWidget(self._telegram_active)
        card.add(active_row)

        buttons = QWidget()
        button_layout = QHBoxLayout(buttons)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(12)
        button_layout.addWidget(stretch())
        self._telegram_test_button = secondary_button("Test Mesajı Göndər")
        self._telegram_test_button.clicked.connect(self.telegram_test_requested)
        button_layout.addWidget(self._telegram_test_button)
        replace = action_button("Botu Dəyiş")
        replace.clicked.connect(self._on_telegram_save)
        button_layout.addWidget(replace)
        card.add(buttons)

        self._telegram_message = muted_label("")
        self._telegram_message.setWordWrap(True)
        card.add(self._telegram_message)
        return card

    def _on_telegram_save(self) -> None:
        self.telegram_saved.emit(
            {
                "bot_token": self._telegram_token.text().strip(),
                "chat_id": self._telegram_chat.text().strip(),
            }
        )

    def set_telegram(self, config: dict[str, object]) -> None:
        """Cari konfiqurasiyanı göstərir (token MASKALANMIŞ).

        Token sahəsi TƏMİZLƏNİR: yazılmış yeni token uğurla saxlandıqdan
        sonra ekranda qalsaydı, növbəti «Botu Dəyiş» onu təkrar göndərərdi.
        """
        masked = str(config.get("masked_token") or "")
        chat_id = str(config.get("chat_id") or "")
        is_active = bool(config.get("is_active"))
        updated = str(config.get("updated_at") or "")
        by = str(config.get("updated_by_name") or "")

        if masked:
            suffix = f" · son dəyişiklik: {updated} {by}".rstrip() if updated or by else ""
            self._telegram_state.setText(f"Bot: {masked} · Chat: {chat_id or '—'}{suffix}")
        else:
            self._telegram_state.setText("Bot qurulmayıb.")
        self._telegram_token.clear()
        self._telegram_chat.setText(chat_id)
        self._telegram_active.blockSignals(True)
        self._telegram_active.setChecked(is_active)
        self._telegram_active.blockSignals(False)

    def set_telegram_message(self, text: str, *, error: bool = False) -> None:
        self._telegram_message.setText(text)
        colour = "--color-danger" if error else "--color-text-muted"
        self._telegram_message.setStyleSheet(f"color: {self._theme.color(colour)};")

    def set_telegram_busy(self, busy: bool) -> None:
        """«Test Mesajı Göndər» fonda qaçarkən düymə söndürülür (UX-1/UI-4).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ BU SETER LAZIM OLDU
        ──────────────────────────────────────────────────────────────────────
        Test Telegram-a HƏQİQİ şəbəkə sorğusudur (`TELEGRAM_REQUEST_TIMEOUT_
        SECONDS`, defolt 15 san, Root 120 san-a qədər böyüdə bilər) və
        kontroller onu artıq `background_task.run_job` ilə fon sapında icra
        edir (bax `controllers/root_control.py::_on_telegram_test`). Düymə
        özü isə əvvəl HEÇ SÖNDÜRÜLMÜRDÜ — iş fona keçəndən sonra bu, artıq
        donma yaratmır, lakin təkrar kliklə iki paralel Telegram sorğusu
        göndərmək mümkün qalırdı. `ErpServersScreen`-dəki `set_busy` ilə eyni
        naxış: deaktivlik GÖRÜNƏN qatdır, kontrollerdəki `BackgroundTask.
        is_running` isə klaviatura qısayolunu da tutur.
        """
        self._telegram_test_button.setEnabled(not busy)
        self._telegram_test_button.setText("Göndərilir…" if busy else "Test Mesajı Göndər")

    def telegram_inputs(self) -> dict[str, object]:
        """Sahələrin cari məzmunu — testlər və kontroller üçün."""
        return {
            "bot_token": self._telegram_token.text().strip(),
            "chat_id": self._telegram_chat.text().strip(),
            "is_active": self._telegram_active.isChecked(),
        }

    # ------------------------ Face Control (bənd 15, 7 + 12) ----------------- #

    def _build_face_card(self) -> Card:
        """«Face Control» bölməsi — mağaza əhatəsi + tərs-hədd xəbərdarlığı.

        ──────────────────────────────────────────────────────────────────────
        NAXIŞ «FASİLƏ PARAMETRLƏRİ»-DƏNDİR (bax `_build_break_card`)
        ──────────────────────────────────────────────────────────────────────
        Eyni fayl, eyni sinif, eyni quruluş: başlıq → izah → dinamik sətirlər
        qabı → `Divider` → izah → bölmənin öz düyməsi. Səbəb də eynidir —
        166 limitlik siyahıda «Face Control hansı mağazalarda işləyir?»
        sualının cavabını sürüşdürüb axtarmaq lazım gələrdi.

        FƏRQ BİR YERDƏDİR: fasilə parametrləri `system_limits` sətirləridir və
        `applied` sözlüyü ilə birlikdə gedir; mağaza əhatəsi isə AYRI cədvəldir
        (`face_control_store_scope`, soft delete ilə) və hər açar dərhal öz
        siqnalını yayır — `[Tətbiq Et]` gözləmir. Səbəb: seçim aç/bağla
        xarakterlidir və toplu «tətbiq» addımı Root-a hansı mağazanın FAKTİKİ
        vəziyyətdə olduğunu göstərməzdi.

        ──────────────────────────────────────────────────────────────────────
        «BOŞ = QLOBAL» MƏTNİ MƏCBURİDİR
        ──────────────────────────────────────────────────────────────────────
        Heç bir mağaza seçilməyəndə Face Control QLOBAL toggle-a tabe olur
        (`FaceStoreScope.is_global`) — yəni İŞLƏYİR. İzah olmasaydı, boş sahə
        «söndürülüb» kimi oxunardı və Root pilot yayımını tərsinə anlayardı.
        """
        card = Card(padding=20, spacing=12)
        card.add(title_label("Face Control", size=15))
        card.add(
            muted_label(
                "Üz təsdiqi PIN-i ƏVƏZ ETMİR — ona əlavə olunan qatdır. Aşağıdakı "
                "seçim yalnız modulun HANSI mağazalarda tətbiq olunduğunu müəyyən edir."
            )
        )

        card.add(Divider())
        card.add(plain_label("Face Control aktiv olan mağazalar"))
        card.add(
            muted_label(
                "HEÇ BİR mağaza seçilməyibsə (defolt) modul QLOBAL Feature Toggle-a "
                "tabe olur — yəni indiki davranış dəyişmir. Seçim edilibsə, üz təsdiqi "
                "YALNIZ seçilmiş mağazalarda tətbiq olunur (pilot-mərhələli yayım)."
            )
        )

        self._face_scope_rows = QVBoxLayout()
        self._face_scope_rows.setSpacing(12)
        scope_holder = QWidget()
        scope_holder.setLayout(self._face_scope_rows)
        card.add(scope_holder)

        self._face_scope_summary = muted_label("")
        card.add(self._face_scope_summary)

        card.add(Divider())
        card.add(plain_label("Uyğunluq həddi"))
        self._face_tolerance = body_label("", size=13)
        card.add(self._face_tolerance)
        # TƏRS-HƏDD XƏBƏRDARLIĞI (facecontrol.md bənd 7 + 12) — bax
        # `set_face_tolerance`.
        self._face_tolerance_warning = body_label("", size=13)
        self._face_tolerance_warning.setVisible(False)
        card.add(self._face_tolerance_warning)
        return card

    def _build_branding_card(self) -> Card:
        """«Şirkət kimliyi» bölməsi — ad və vurğu rəngi (TENANT-1 Faza 2).

        ──────────────────────────────────────────────────────────────────────
        LOQO BURADA YÜKLƏNMİR — VƏ BU, QƏSDƏNDİR
        ──────────────────────────────────────────────────────────────────────
        Loqo fayl seçici dialoqu tələb edir; həmin dialoq isə Root panelinin
        BÜTÜN digər sahələri kimi «yaz və Tətbiq Et» ritmindən kənara düşür
        (fayl seçimi dərhal nəticə verir, toplu tətbiq gözləmir). Onu bu kartın
        içinə salmaq iki fərqli qarşılıqlı təsir modelini bir bölmədə
        qarışdırmaq olardı.

        Ad və rəng isə mətn sahələridir və mövcud ritmə tam uyğundur. Loqo
        `TenantBrandingUseCase.update(logo_png=...)` ilə onsuz da dəyişdirilə
        bilir — burada YALNIZ ekran yolu yoxdur, imkan yox deyil.

        ──────────────────────────────────────────────────────────────────────
        XƏBƏRDARLIQ SAHƏSİ HƏMİŞƏ VAR, LAKİN ADƏTƏN GİZLİDİR
        ──────────────────────────────────────────────────────────────────────
        Uyğun olmayan rəng RƏDD EDİLMİR (bax `value_objects/branding.py`) —
        istifadəçi onu saxlaya bilər, lakin nəticəni bilməlidir. Mətn use
        case-dən gəlir; ekran onu YAZMIR, yalnız göstərir.
        """
        card = Card(padding=20, spacing=12)
        card.add(title_label("Şirkət kimliyi", size=15))
        card.add(
            muted_label(
                "Bu ayarlar YALNIZ görünüşə təsir edir. Funksionallıq, təhlükəsizlik "
                "qaydaları və icazə matrisi HEÇ BİR müştəri üçün dəyişmir."
            )
        )

        card.add(Divider())
        card.add(plain_label("Şirkət adı"))
        card.add(
            muted_label(
                "Başlıq zolağında «KompasOS — <ad>» kimi görünür. Boş buraxılsa "
                "yalnız «KompasOS» qalır."
            )
        )
        self._branding_name = QLineEdit()
        card.add(self._branding_name)

        card.add(Divider())
        card.add(plain_label("Vurğu rəngi"))
        card.add(muted_label("`#RRGGBB` formatında. Boş buraxılsa defolt Amber işlədilir."))
        self._branding_accent = QLineEdit()
        card.add(self._branding_accent)

        self._branding_warning = body_label("", size=13)
        self._branding_warning.setVisible(False)
        card.add(self._branding_warning)

        # Uğur mesajı XƏBƏRDARLIQDAN AYRI sətirdədir: ikisini bir etiketdə
        # birləşdirsəydik, «yadda saxlanıldı» mətni oxunaqlılıq
        # xəbərdarlığının üzərini yazar və istifadəçi problemi görməzdi.
        self._branding_status = muted_label("")
        self._branding_status.setVisible(False)
        card.add(self._branding_status)

        apply_button = action_button("Şirkət kimliyini yadda saxla")
        apply_button.clicked.connect(self._on_branding_apply)
        card.add(apply_button)
        return card

    def _on_branding_apply(self) -> None:
        accent = self._branding_accent.text().strip()
        self.branding_changed.emit(
            {
                "company_name": self._branding_name.text(),
                "accent_color": accent or None,
                # Boş sahə «sil» deməkdir — `None` isə use case-də «dəyişmə»
                # mənasını daşıyır (bax `TenantBrandingUseCase.update`).
                "clear_accent": not accent,
            }
        )

    def set_branding(self, *, company_name: str, accent_color: str, warning: str = "") -> None:
        """Cari brendinqi göstərir; `warning` boşdursa xəbərdarlıq gizlənir."""
        self._branding_name.setText(company_name)
        self._branding_accent.setText(accent_color)
        self._branding_warning.setText(warning)
        self._branding_warning.setVisible(bool(warning))

    def set_branding_status(self, message: str) -> None:
        """Yazıdan sonrakı sakit məlumat sətri (boş = gizli)."""
        self._branding_status.setText(message)
        self._branding_status.setVisible(bool(message))

    def set_face_scope(self, stores: list[dict[str, str]]) -> None:
        """Face Control-un mağaza əhatəsi (bənd 15).

        Args:
            stores: `id`, `name`, `active` ("1"/"0") açarları olan sözlüklər.
                Açarlar HƏM maket (`preview_screens._root_control`), HƏM canlı
                yol (`controllers/root_control.py::_face_scope_rows`) üçün
                EYNİDİR — CLAUDE.md §6.

        Boş siyahı MAĞAZA OLMAMASI deməkdir (yeni quraşdırma) və «qlobal
        rejim» ilə QARIŞDIRILMIR: qlobal rejim seçilmiş mağaza olmamasıdır,
        bu isə ümumiyyətlə mağaza olmamasıdır.
        """
        clear_layout(self._face_scope_rows)
        self._face_scope_toggles.clear()

        for store in stores:
            key = store.get("id", "")
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)
            layout.addWidget(body_label(store.get("name", ""), size=13, wrap=False))
            layout.addWidget(stretch())

            toggle = ToggleSwitch(self.theme, checked=store.get("active") == "1")
            toggle.toggled.connect(
                lambda checked, k=key: self.face_scope_changed.emit(k, bool(checked))
            )
            self._face_scope_toggles[key] = toggle
            layout.addWidget(toggle)
            self._face_scope_rows.addWidget(row)

        selected = sum(1 for store in stores if store.get("active") == "1")
        if not stores:
            self._face_scope_summary.setText("Mağaza siyahısı boşdur.")
        elif selected == 0:
            self._face_scope_summary.setText(
                "Seçim yoxdur — Face Control qlobal Feature Toggle-a tabedir (indiki davranış)."
            )
        else:
            self._face_scope_summary.setText(
                f"{selected} mağaza seçilib — üz təsdiqi YALNIZ orada tətbiq olunur."
            )

    def reject_face_scope_change(self, store_id: str) -> None:
        """Yazı rədd edildi — açar geri qaytarılır (siqnal təkrar yayılmadan).

        `reject_module_change` ilə eyni qərar: ekran YALAN göstərməməlidir.
        Fərq odur ki, burada əvvəlki vəziyyət açarın CARİ vəziyyətinin
        əksidir — istifadəçi onu indicə dəyişib.
        """
        toggle = self._face_scope_toggles.get(store_id)
        if toggle is None:
            return
        toggle.blockSignals(True)
        toggle.setChecked(not toggle.isChecked())
        toggle.blockSignals(False)

    def set_face_tolerance(self, tolerance: dict[str, str]) -> None:
        """Bənzərlik + aşağı-etibar həddi və TƏRS CÜT xəbərdarlığı.

        Args:
            tolerance: `match`, `low_confidence`, `inverted` ("1"/"0"),
                `band_enabled` ("1"/"0") açarları.

        ──────────────────────────────────────────────────────────────────────
        DOMEN MƏNTİQİ BURADA TƏKRARLANMIR
        ──────────────────────────────────────────────────────────────────────
        `FACE_LOW_CONFIDENCE_TOLERANCE > FACE_MATCH_TOLERANCE` cütünün nə
        demək olduğunu `FaceToleranceBand.resolve` həll edir və o, FAIL-CLOSED
        davranır: zolaq söndürülür, qəbul sərhədi İKİSİNDƏN SƏRTİNƏ enir.
        Ekran həmin hesablamanı APARMIR — `inverted` bayrağı ona HAZIR gəlir
        (`is_inverted`) və burada yalnız GÖSTƏRİLİR.

        Xəbərdarlıq niyə lazımdır: Root ekranda «yumşaltdım» zənn edə bilər,
        sistem isə sərtləşmiş halda işləyir. Konfiqurasiya ilə davranış
        arasındakı gizli fərq ən pis nasazlıq formasıdır (bax
        `FaceToleranceBand` başlığı) — ona görə o, GİZLİ QALMAMALIDIR.
        """
        match = tolerance.get("match", "—")
        low = tolerance.get("low_confidence", "—")
        band_enabled = tolerance.get("band_enabled") == "1"
        self._face_tolerance.setText(
            f"Bənzərlik həddi: {match} · aşağı-etibar həddi: {low}. "
            + (
                "Aralıqdakı nəticələr «aşağı-etibarlı təsdiq» kimi nişanlanır."
                if band_enabled
                else "Aşağı-etibar zolağı işləmir — nəticələr yalnız keçdi/keçmədi olur."
            )
        )

        inverted = tolerance.get("inverted") == "1"
        self._face_tolerance_warning.setVisible(inverted)
        if inverted:
            self._face_tolerance_warning.setText(
                f"DİQQƏT: aşağı-etibar həddi ({low}) bənzərlik həddindən ({match}) "
                f"BÖYÜKDÜR. Bu cüt mənasızdır — sistem onu FAIL-CLOSED emal edir: "
                f"aşağı-etibar zolağı söndürülür və qəbul sərhədi ikisindən SƏRTİNƏ "
                f"endirilir. Yəni tətbiq olunan hədd ekranda yazdığınız deyil."
            )
            self._face_tolerance_warning.setStyleSheet(
                f"color: {self.theme.color('--color-danger')};"
            )

    def _build_registry(self) -> Card:
        card = Card(padding=20, spacing=12)
        card.add(title_label("İcazə registri", size=15))

        self._registry_rows = QVBoxLayout()
        self._registry_rows.setSpacing(8)
        holder = QWidget()
        holder.setLayout(self._registry_rows)
        card.add(holder)
        card.add(Divider())

        create_row = QWidget()
        create_layout = QHBoxLayout(create_row)
        create_layout.setContentsMargins(0, 0, 0, 0)
        create_layout.setSpacing(12)

        # Göstəriş `can_` prefiksini ADLANDIRIR, çünki `PermissionFlag` onu
        # TƏLƏB EDİR (bax `authorization.PermissionFlag.__post_init__`) —
        # prefiksiz yazılan açar yaradılan kimi rədd edilirdi. Bu, nümunə
        # dəyər deyil: qaydanın özüdür və qutunu dolu göstərmir. Etiketsiz
        # buraxıla bilməzdi — yanındakı «Kateqoriya» qutusunun göstərişi var.
        self._new_flag = QLineEdit()
        self._new_flag.setPlaceholderText("İcazə açarı — `can_` ilə başlamalıdır")
        self._new_flag.setProperty("variant", "form")
        create_layout.addWidget(self._new_flag, 1)

        # Kateqoriya `PermissionFlag`-in məcburi sahəsidir və icazə matrisində
        # qruplaşdırma açarıdır — onsuz yeni flag matrisdə yersiz qalardı.
        self._new_flag_category = QLineEdit()
        self._new_flag_category.setPlaceholderText("Kateqoriya")
        self._new_flag_category.setProperty("variant", "form")
        self._new_flag_category.setFixedWidth(168)
        create_layout.addWidget(self._new_flag_category)

        self._new_flag_kind = QComboBox()
        self._new_flag_kind.setProperty("variant", "form")
        self._new_flag_kind.addItems(["Standart", "Hardlock"])
        self._new_flag_kind.setFixedWidth(152)
        create_layout.addWidget(self._new_flag_kind)

        create = secondary_button("Yarat")
        create.clicked.connect(self._on_create_flag)
        create_layout.addWidget(create)
        card.add(create_row)
        return card

    def _on_create_flag(self) -> None:
        name = self._new_flag.text().strip()
        if not name:
            return
        category = self._new_flag_category.text().strip() or "Ümumi"
        self.flag_created.emit(name, category, self._new_flag_kind.currentText() == "Hardlock")
        self._new_flag.clear()
        self._new_flag_category.clear()

    # ------------------------------- doldurma -------------------------------- #

    def set_limits(self, limits: list[tuple[str, str, int | str, int, int, str]]) -> None:
        """`limits`: (açar, etiket, dəyər, min, max, şəkilçi).

        Dəyər ƏDƏD deyilsə (`LEAVE_ALLOWANCE_SOURCE` = "LEAVE_TYPE",
        `DELAY_FINE_RATE_PER_MINUTE` = "0.00") sətir sahəsi qurulur. Səbəb:
        bölmə 3 "hər şey Root-dan idarə olunmalıdır" deyir, ona görə ədədə
        sığmayan limiti ekrandan ÇIXARMAQ olmaz — çıxarsaydıq, o limit yalnız
        birbaşa SQL ilə dəyişdirilə bilərdi, yəni faktiki olaraq hardcode
        sayılardı. `min`/`max`/`şəkilçi` mətn sahəsində nəzərə alınmır.
        """
        clear_layout(self._limits_rows)
        self._limit_inputs.clear()
        self._limit_texts.clear()

        for entry in limits:
            self._limits_rows.addWidget(self._limit_row_widget(entry, numbers=self._limit_inputs))
        self.show_content()

    def set_break_limits(self, limits: list[tuple[str, str, int | str, int, int, str]]) -> None:
        """«Fasilə Parametrləri» bölməsi — `set_limits` ilə EYNİ sətir formatı.

        Format qəsdən eynidir: kontroller iki siyahını bir mənbədən
        (`RootControlUseCase.list_limits`) qurur və yalnız BÖLÜR. Ayrı format
        seçsəydik, `description_az`/`min_value`/`max_value` zənciri ikinci
        dəfə yazılmalı olardı və biri düzəldiləndə digəri arxada qalardı
        (`test_root_control_parameter_parity` məhz bu naxışı qoruyur).
        """
        clear_layout(self._break_rows)
        self._break_inputs.clear()

        for entry in limits:
            self._break_rows.addWidget(self._limit_row_widget(entry, numbers=self._break_inputs))

    def _limit_row_widget(
        self,
        entry: tuple[str, str, int | str, int, int, str],
        *,
        numbers: dict[str, QSpinBox],
    ) -> QWidget:
        """Bir limit sətri — ədəd üçün spin, mətn üçün sətir sahəsi.

        `numbers` HANSI lüğətə yazılacağını təyin edir: eyni widget qurucusu
        həm ümumi siyahıya, həm də fasilə bölməsinə xidmət edir. Mətn sahələri
        HƏMİŞƏ `_limit_texts`-ə düşür, çünki fasilə parametrlərinin dördü də
        ədəddir və oraya mətn sətri düşsəydi, bu, sxem xətası olardı — onu
        gizlətmək əvəzinə ümumi kanalda göstərmək daha dürüstdür.
        """
        key, label, value, minimum, maximum, suffix = entry
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(body_label(label, size=13, wrap=False))
        layout.addWidget(stretch())

        # ƏDƏD OLMAQ KİFAYƏT DEYİL — 32 BİTƏ SIĞMALIDIR
        #
        # `QSpinBox` `int32` ilə işləyir və `IMAGE_CACHE_MAX_BYTES` tavanı
        # (8 GiB) ona sığmır. Əvvəl bu, `OverflowError` idi və bütün paneli
        # aparırdı (bax `INT32_MAX` şərhi). İndi belə limit MƏTN sahəsi kimi
        # göstərilir: dəyər yenə redaktə olunur, yenə eyni `set_limit` yolundan
        # keçir və hüdudlar yenə tətbiq qatında yoxlanılır — itən yeganə şey
        # spin oxlarıdır.
        fits_in_spin_box = isinstance(value, int) and abs(minimum) <= INT32_MAX
        fits_in_spin_box = fits_in_spin_box and abs(maximum) <= INT32_MAX
        if fits_in_spin_box:
            spin = QSpinBox()
            spin.setProperty("variant", "form")
            spin.setRange(minimum, maximum)
            spin.setValue(int(value))
            spin.setSuffix(f" {suffix}")
            spin.setFixedWidth(160)
            numbers[key] = spin
            layout.addWidget(spin)
        else:
            value = str(value)
            field = QLineEdit(value)
            field.setProperty("variant", "form")
            field.setFixedWidth(160)
            self._limit_texts[key] = field
            layout.addWidget(field)
        return row

    def set_modules(self, modules: list[tuple[str, str, bool, bool]]) -> None:
        """`modules`: (açar, etiket, aktiv, struktur-kritik)."""
        clear_layout(self._modules_rows)
        self._module_toggles.clear()
        self._structural.clear()

        for key, label, enabled, structural in modules:
            if structural:
                self._structural.add(key)

            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)
            layout.addWidget(body_label(label, size=13, wrap=False))
            if structural:
                layout.addWidget(Chip("struktur-kritik", "warning"))
            layout.addWidget(stretch())

            toggle = ToggleSwitch(self.theme, checked=enabled)
            toggle.toggled.connect(lambda checked, k=key: self._on_module_toggled(k, checked))
            self._module_toggles[key] = toggle
            layout.addWidget(toggle)
            self._modules_rows.addWidget(row)

    def _on_module_toggled(self, key: str, enabled: bool) -> None:
        confirmation = ""
        if not enabled and key in self._structural:
            # Bölmə 3: struktur-kritik modul üçün bir-kliklik toggle KİFAYƏT
            # DEYİL. `getMultiLineText` bir modalda hər ikisini verir —
            # xəbərdarlıq mətni və yazılı təsdiq sahəsi.
            from PySide6.QtWidgets import QInputDialog  # noqa: PLC0415

            confirmation, accepted = QInputDialog.getMultiLineText(
                self,
                "Struktur-kritik modul söndürülür",
                f"«{key}» modulu STEP1-3 və Morning Check-in axınlarının struktur\n"
                "əsasıdır. Söndürüldükdən sonra YENİ instansiya yaradıla bilməyəcək;\n"
                "mövcud və tarixi qeydlər toxunulmaz qalır.\n\n"
                "Davam etmək üçün səbəbi yazın (audit jurnalına düşür):",
            )
            if not accepted or not confirmation.strip():
                self._restore_toggle(key)
                return
            confirmation = confirmation.strip()
        self.module_toggled.emit(key, enabled, confirmation)

    def _restore_toggle(self, key: str) -> None:
        """Açarı əvvəlki vəziyyətinə qaytarır — siqnal təkrar işə düşmədən.

        `reject_module_change()` ilə eyni kod: təsdiq verilmədikdə də,
        use case əməliyyatı rədd etdikdə də ekran YALAN göstərməməlidir.
        """
        toggle = self._module_toggles.get(key)
        if toggle is None:
            return
        toggle.blockSignals(True)
        toggle.setChecked(True)
        toggle.blockSignals(False)

    def reject_module_change(self, key: str) -> None:
        """Use case dəyişikliyi rədd etdi — açar geri qaytarılır."""
        self._restore_toggle(key)

    def set_registry(self, flags: list[tuple[str, bool]]) -> None:
        clear_layout(self._registry_rows)

        for name, hardlock in flags:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)
            layout.addWidget(mono_label(name))
            layout.addWidget(stretch())
            layout.addWidget(
                Chip("hardlock" if hardlock else "standart", "danger" if hardlock else "neutral")
            )
            self._registry_rows.addWidget(row)

    def collected(self) -> dict[str, object]:
        limits: dict[str, int | str] = {
            key: spin.value() for key, spin in self._limit_inputs.items()
        }
        # Fasilə bölməsi də ÜMUMİ «Tətbiq Et»-ə daxildir: Root iki ayrı düymə
        # basmağa məcbur qalmamalıdır. Öz «Yadda Saxla» düyməsi isə yalnız bu
        # dördünü göndərir — hər ikisi eyni `set_limit` yolundan keçir.
        limits.update(self._collected_breaks())
        limits.update({key: field.text().strip() for key, field in self._limit_texts.items()})
        return {
            "limits": limits,
            "modules": {key: toggle.isChecked() for key, toggle in self._module_toggles.items()},
        }


__all__ = [
    "AuditScreen",
    "BackupScreen",
    "DriveConnectionScreen",
    "ErpServersScreen",
    "HealthScreen",
    "RestoreConfirmDialog",
    "RootControlScreen",
    "ServerConnectionWizard",
    "SettingsScreen",
]
