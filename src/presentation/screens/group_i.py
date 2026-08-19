"""Qrup İ — infrastruktur, panel qurucusu və plugin idarəetməsi — Faza 5/6.

    36  [İnfrastruktur Və Baza Ayarları]  (`can_switch_db`,      bölmə 2)
    37  Panel Qurucusu                    (səlahiyyət tələb etmir, bölmə 6)
    38  Plugin İdarəetməsi                (`can_manage_plugins`, bölmə 1)
    39  İstisnalar                        (`can_view_exceptions`, kompasos11.md
                                            Faza 5, #9-un GUI tərəfi)

──────────────────────────────────────────────────────────────────────────────
39-CU EKRANIN MAKETİ NİYƏ YOXDUR
──────────────────────────────────────────────────────────────────────────────
"İstisnalar" ekranı kompasos11.md-nin YENİ tələbidir (#9) — Qrup A–H-in HTML
maketlərində yoxdur. 36–38 də eyni səbəbdən buradadır (bax bu faylın adı:
"Faza 5/6", maket-referanslı qruplardan fərqli olaraq). Yeni "maketsiz" ekranı
buraya qoşmaq mövcud naxışı təkrarlayır, süni beşinci qrup yaratmır.

──────────────────────────────────────────────────────────────────────────────
BAZA KEÇİDİ EKRANI NİYƏ "SEHRBAZ" DEYİL
──────────────────────────────────────────────────────────────────────────────
ERP bağlantısı çox addımlı sehrbazdır, çünki orada İSTİFADƏÇİ məlumat daxil
edir. Baza keçidində isə istifadəçi yalnız BİR qərar verir ("hara?") — qalan
yeddi addımı sistem özü icra edir. Sehrbaz forması burada saxta seçim
təəssüratı yaradardı; əvəzinə tək təsdiq + gedişat siyahısı göstərilir.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.domain.value_objects.infrastructure import (
    ALL_PHASES,
    DatabaseTarget,
    MigrationPhase,
)
from src.presentation.screens.base import Screen, section_header
from src.presentation.widgets import icons, metrics
from src.presentation.widgets.buttons import action_button, icon_button, secondary_button
from src.presentation.widgets.data_table import Column, DataTable
from src.presentation.widgets.forms import FormField, field_label
from src.presentation.widgets.help_hint import HelpButton
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import (
    Card,
    Chip,
    ChipTone,
    Divider,
    body_label,
    mono_label,
    muted_label,
    plain_label,
    stretch,
    title_label,
)
from src.presentation.widgets.responsive import LayoutMode
from src.presentation.widgets.toggle import ToggleSwitch

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager


#: Şəbəkə yerləşdirməsinin kodlanma ayırıcısı (audit G-5).
#:
#: TƏK MƏNBƏ `application.use_cases.dashboard_layout.PLACEMENT_SEPARATOR`-dədir
#: və dəyər BURADA TƏKRARLANIR, idxal edilmir: `screens/` paketindəki heç bir
#: ekran tətbiq qatını idxal etmir (qat sərhədi ekranları saf saxlayır) və bu
#: fayl həmin qaydanı pozan birinci olmamalıdır. Təkrarlanma sükutla
#: ayrılmasın deyə `tests/unit/test_dashboard_grid.py` iki sabitin eyniliyini
#: QAPI kimi yoxlayır.
PLACEMENT_SEPARATOR: Final = "@"


# --------------------------------------------------------------------------- #
# 36 — İnfrastruktur Və Baza Ayarları
# --------------------------------------------------------------------------- #


class PhaseRow(QWidget):
    """Keçidin bir addımı — gözləyir / icra olunur / tamamlandı / uğursuz."""

    STATES: Final = ("pending", "running", "done", "failed")

    def __init__(
        self, phase: MigrationPhase, theme: ThemeManager, *, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._phase = phase

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(12)

        self._marker = plain_label()
        self._marker.setFixedSize(22, 22)
        self._marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._marker)

        label = body_label(f"{phase.order + 1}. {phase.label_az}")
        label.setWordWrap(True)
        layout.addWidget(label, 1)

        self._chip = Chip("Gözləyir", "neutral")
        layout.addWidget(self._chip)

        self.set_state("pending")

    def set_state(self, state: str) -> None:
        """Vəziyyəti dəyişir.

        Nişan HƏM ikon, HƏM mətnlə verilir — yalnız rəngə güvənmək rəng
        ayırd edə bilməyən istifadəçi üçün məlumatı itirərdi (bölmə 9).
        """
        icon_name, token, chip_text, tone = {
            "pending": ("clock", "--color-text-muted", "Gözləyir", "neutral"),
            "running": ("refresh", "--color-info", "İcra olunur", "info"),
            "done": ("check_circle", "--color-success", "Tamamlandı", "success"),
            "failed": ("close", "--color-danger", "Uğursuz", "danger"),
        }[state]

        self._marker.setPixmap(
            icons.render(icon_name, self._theme.color(token), size=14, stroke_width=1.8)
        )
        self._chip.setText(chip_text)
        self._chip.set_tone(tone)  # type: ignore[arg-type]


#: İnfrastruktur ekranının kontekstual köməyi (audit G-4).
#:
#: Mətn EKRANIN YANINDA yaşayır, mərkəzi kömək kataloqunda deyil — səbəbi
#: `widgets/help_hint.HelpButton` başlığındadır: «düymə keçidi başlatmır,
#: əvvəlcə ön yoxlama gedir» qərarı `MigrationConfirmDialog` ilə eyni faylda
#: saxlanılmalıdır ki, təsdiq axını dəyişəndə izah də onunla birlikdə
#: yenilənsin.
INFRASTRUCTURE_HELP_TITLE: Final = "İnfrastruktur Və Baza Ayarları"

INFRASTRUCTURE_HELP_INTRO: Final = (
    "Bu ekran sistemin Cloud ilə Şəxsi Server bazası arasında keçidini idarə "
    "edir. Keçid ərzində bütün sessiyalar yalnız-oxu rejimində olur — yəni bu, "
    "planlaşdırılmış texniki fasilədir, adi ayar deyil."
)

INFRASTRUCTURE_HELP_STEPS: Final[tuple[str, ...]] = (
    "«Aktiv baza» hazırda hansı bazanın işlədiyini göstərir. Düymənin adı "
    "həmişə HƏDƏFİ yazır: «Şəxsi Server-ə keç» yazısı sistemin indi Cloud-da "
    "olması deməkdir.",
    "Düyməni basmaq keçidi BAŞLATMIR — əvvəlcə ön yoxlama işə düşür və "
    "nəticəsi təsdiq modalında göstərilir. Sinxronlaşmamış yazı varsa "
    "xəbərdarlıq orada, yəni keçiddən ƏVVƏL görünür.",
    "Təsdiq üçün hədəf bazanın adı ƏL İLƏ yazılır. Bu, süni maneə deyil: "
    "refleks kliki dayandırır. Modalda Enter düyməsi «İmtina»ya bağlıdır — "
    "səhvən basmaq heç nə başlatmır.",
    "«Keçid addımları» siyahısı gedişatı canlı göstərir. Aktiv baza YALNIZ "
    "bütün addımlar tamamlananda dəyişir; uğursuz addım keçidi dayandırır və "
    "jurnalda «Geri qaytarıldı» yaxud «Uğursuz» kimi qeyd olunur.",
    "«Keçid tarixçəsi» hər cəhdi barmaq izi ilə saxlayır və sətirləri "
    "SİLİNMİR — hansı məlumatın hansı bazadan gəldiyini sonradan yalnız bu "
    "jurnal sübut edir.",
)


class InfrastructureScreen(Screen):
    """Cloud ↔ Şəxsi Server keçidi + texniki fasilə gedişatı (bölmə 2).

    Signals:
        switch_requested: Hədəf baza (`CLOUD` / `PRIVATE_SERVER`).
        history_requested: Jurnalın yenilənməsi.
    """

    switch_requested = Signal(str)
    history_requested = Signal()

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)
        self._phase_rows: dict[MigrationPhase, PhaseRow] = {}
        self._active = DatabaseTarget.CLOUD

        self.add(
            section_header(
                "İnfrastruktur Və Baza Ayarları",
                "Keçid yalnız texniki fasilə rejimində icra olunur.",
            )
        )

        # ------------------------------ aktiv baza --------------------------- #
        target_card = Card()
        body = target_card.body()

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)
        row_layout.addWidget(muted_label("Aktiv baza"))
        self._active_label = title_label("", size=15)
        row_layout.addWidget(self._active_label)
        row_layout.addWidget(stretch())

        # Kontekstual kömək (audit G-4) — düymənin keçidi DƏRHAL başlatmadığı
        # (əvvəlcə ön yoxlama + təsdiq) ekranda heç yerdə yazılmırdı, halbuki
        # bu, istifadəçinin basmazdan ƏVVƏL bilməli olduğu şeydir.
        self._help = HelpButton(
            theme,
            title=INFRASTRUCTURE_HELP_TITLE,
            intro=INFRASTRUCTURE_HELP_INTRO,
            steps=INFRASTRUCTURE_HELP_STEPS,
        )
        row_layout.addWidget(self._help)

        self._switch_button = action_button(
            "Digər bazaya keç",
            icon_name="database",
            icon_color=theme.color("--color-action-text"),
        )
        self._switch_button.clicked.connect(
            lambda: self.switch_requested.emit(self._active.opposite().value)
        )
        row_layout.addWidget(self._switch_button)
        body.addWidget(row)

        self._warning_label = muted_label("")
        self._warning_label.setWordWrap(True)
        body.addWidget(self._warning_label)
        self.add(target_card)

        # ------------------------------ gedişat ------------------------------ #
        phases_card = Card()
        phases_body = phases_card.body()
        phases_body.addWidget(title_label("Keçid addımları", size=15))
        phases_body.addWidget(Divider())
        for phase in ALL_PHASES:
            widget = PhaseRow(phase, theme)
            self._phase_rows[phase] = widget
            phases_body.addWidget(widget)
        self.add(phases_card)

        # ------------------------------ jurnal ------------------------------- #
        #
        # «YENİLƏ» DÜYMƏSİ NİYƏ BURADA
        # ─────────────────────────────────────────────────────────────────────
        # `history_requested` siqnalı elan olunmuşdu və `controllers/
        # infrastructure.py` onu ARTIQ dinləyirdi (`refresh`-ə bağlı), lakin
        # ekranda onu yayacaq HEÇ BİR element yox idi — yəni bağlantının bir
        # ucu boşda qalmışdı və tarixçə yalnız ekran açılanda oxunurdu. Baza
        # keçidi isə DƏQİQƏLƏRLƏ sürən əməliyyatdır: istifadəçi nəticəni
        # görmək üçün ekranı tərk edib qayıtmalı olurdu.
        #
        # Düymə kartın BAŞLIQ sətrindədir (design.md dizayn dili, qərar 3:
        # «kart başlığı öz əməliyyatını daşıyır») — cədvəlin altına qoysaydıq,
        # uzun jurnalda ekranın dibində qalardı.
        history_header = QWidget()
        history_header_layout = QHBoxLayout(history_header)
        history_header_layout.setContentsMargins(0, 0, 0, 0)
        history_header_layout.setSpacing(12)
        history_header_layout.addWidget(title_label("Keçid tarixçəsi", size=15))
        history_header_layout.addWidget(stretch())
        self._history_refresh = secondary_button("Yenilə")
        self._history_refresh.clicked.connect(self.history_requested)
        history_header_layout.addWidget(self._history_refresh)
        self.add(history_header)

        self._history_host = QWidget()
        self._history_layout = QVBoxLayout(self._history_host)
        self._history_layout.setContentsMargins(0, 0, 0, 0)
        self._history_layout.setSpacing(0)
        self.add(self._history_host)

        self.set_active_target(DatabaseTarget.CLOUD)

    def help_button(self) -> HelpButton:
        """Kontekstual kömək düyməsi — kontroller/testlər üçün."""
        return self._help

    # -------------------------------- API ------------------------------------ #

    def set_active_target(self, target: DatabaseTarget) -> None:
        self._active = target
        self._active_label.setText(target.label_az)
        self._switch_button.setText(f"{target.opposite().label_az}-ə keç")

    def set_warnings(self, warnings: list[str]) -> None:
        """Ön yoxlama xəbərdarlıqları — boşdursa "hazırdır" yazılır.

        Boş sətir buraxmaq istifadəçidə "yoxlama aparılmadı?" sualı yaradardı.
        """
        self._warning_label.setText(
            "\n".join(f"• {text}" for text in warnings)
            if warnings
            else "Ön yoxlama təmizdir — sinxronlaşmamış yazı yoxdur."
        )

    def set_phase_state(self, phase: MigrationPhase, state: str) -> None:
        self._phase_rows[phase].set_state(state)

    def reset_phases(self) -> None:
        for widget in self._phase_rows.values():
            widget.set_state("pending")

    def set_history(self, rows: list[dict[str, str]]) -> None:
        """Keçid tarixçəsi (`db_migration_events`)."""
        clear_layout(self._history_layout)
        if not rows:
            self._history_layout.addWidget(muted_label("Hələ heç bir baza keçidi olmayıb."))
            self.show_content()
            return

        table = DataTable(
            [
                Column("Tarix", 160, mono=True),
                Column("İstiqamət"),
                # Barmaq izi bir HASH-dır — maketin identifikator qaydası.
                Column("Barmaq izi", 170, mono=True),
                Column("Nəticə", 150),
            ],
            self.theme,
            footnote="Hər keçid `db_migration_events` cədvəlinə yazılır və silinmir.",
        )
        for entry in rows:
            table.add_row(
                [
                    entry.get("date", ""),
                    entry.get("direction", ""),
                    entry.get("checksum", ""),
                    Chip(entry.get("status", ""), entry.get("tone", "neutral")),  # type: ignore[arg-type]
                ]
            )
        self._history_layout.addWidget(table)
        self.show_content()


class MigrationConfirmDialog(QDialog):
    """Baza keçidinin təsdiq modalı — «ciddi təsdiq» addımı (bölmə 2).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ HƏDƏFİN ADI ƏL İLƏ YAZILIR
    ──────────────────────────────────────────────────────────────────────────
    Keçid bütün tenant-ı yalnız-oxu rejiminə salır, məlumatı köçürür və aktiv
    bazanı dəyişir. `MigrationPlan` docstring-i açıq deyir: "Panel bu planı
    istifadəçiyə GÖSTƏRİR və yalnız təsdiqdən sonra icra başlayır". Sadə
    "Bəli" düyməsi refleks kliklə basıla bilər; hədəfin adını yazmaq isə
    istifadəçini plana BAXMAĞA məcbur edir.

    Eyni naxış `RestoreConfirmDialog`-dadır (bərpa üçün nüsxə tarixi yazılır)
    — iki dağıdıcı əməliyyat üçün iki fərqli təsdiq üslubu istifadəçini
    çaşdırardı.

    Signals:
        confirmed: Təsdiqlənmiş hədəf bazanın açarı (`DatabaseTarget.value`).
    """

    confirmed = Signal(str)

    def __init__(
        self,
        theme: ThemeManager,
        *,
        destination: DatabaseTarget,
        summary: str,
        warnings: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._destination = destination
        self.setWindowTitle("Baza keçidini təsdiq et")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        card = Card(padding=24, spacing=16)
        layout.addWidget(card)

        card.add(title_label("Baza keçidi başlasın?", size=19))
        card.add(body_label(summary, size=13))
        card.add(Divider())

        # Ön yoxlama xəbərdarlıqları TƏSDİQDƏN ƏVVƏL göstərilir: onları
        # keçiddən sonra göstərmək məlumatı gec çatdırmaq olardı.
        if warnings:
            card.add(title_label("Ön yoxlama", size=15))
            for text in warnings:
                card.add(body_label(f"• {text}", size=13))
        else:
            card.add(muted_label("Ön yoxlama təmizdir."))

        self._input = FormField(
            "Təsdiq üçün hədəf bazanın adını yazın",
            placeholder=destination.label_az,
            hint="Keçid ərzində bütün sessiyalar YALNIZ-OXU rejimində olacaq.",
        )
        card.add(self._input)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)
        buttons_layout.addWidget(stretch())

        cancel = secondary_button("İmtina")
        cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel)

        confirm = action_button("Keçidi Başlat")
        confirm.clicked.connect(self._on_confirm)
        buttons_layout.addWidget(confirm)
        card.add(buttons)

        # ──────────────────────────────────────────────────────────────────
        # DEFOLT DÜYMƏ TƏSDİQ DEYİL, İMTİNADIR — QƏSDƏN
        # ──────────────────────────────────────────────────────────────────
        # Bu dialoq bütün tenant-ı yalnız-oxu rejiminə salıb məlumatı köçürür.
        # Sinif başlığı deyir: "Sadə «Bəli» düyməsi refleks kliklə basıla
        # bilər" — eyni risk KLAVİATURADA daha böyükdür, çünki Enter ekranda
        # baxmadan da basılır (əvvəlki dialoqun Enter-i "yapışıb" qala bilər).
        #
        # Ona görə Enter-in nəticəsi İMTİNA-dır: səhvən basmaq heç nə itirmir,
        # yalnız modalı bağlayır. Keçid isə şüurlu bir hərəkət tələb edir —
        # hədəf bazanın adını yazmaq və düyməni açıq şəkildə basmaq.
        # Eyni qərar `RestoreConfirmDialog`-dadır (`group_d.py`).
        #
        # `autoDefault` HƏR İKİ düymədə söndürülür: əks halda fokus təsdiq
        # düyməsinə düşən kimi Qt onu müvəqqəti defolt edərdi və yuxarıdakı
        # qoruma sükutla itərdi.
        cancel.setDefault(True)
        cancel.setAutoDefault(False)
        confirm.setDefault(False)
        confirm.setAutoDefault(False)

        # Fokus sırası: təsdiq sahəsi → imtina → keçidi başlat.
        QWidget.setTabOrder(self._input.input_widget(), cancel)
        QWidget.setTabOrder(cancel, confirm)

        # İlkin fokus təsdiq sahəsindədir — düymədə DEYİL: istifadəçinin
        # atmalı olduğu ilk addım adı yazmaqdır.
        self._input.focus_input()

    def _on_confirm(self) -> None:
        self._input.clear_error()
        if self._input.text().strip() != self._destination.label_az:
            self._input.set_error("Ad hədəf bazanın adı ilə üst-üstə düşmür")
            return
        self.confirmed.emit(self._destination.value)
        self.accept()


# --------------------------------------------------------------------------- #
# 37 — Panel Qurucusu
# --------------------------------------------------------------------------- #


class WidgetRow(QWidget):
    """Panel qurucusunda bir widget sətri — göstər/gizlət + sıralama + şəbəkə.

    Signals:
        toggled: `(widget_key, görünürmü)`.
        moved: `(widget_key, istiqamət)` — `-1` yuxarı, `+1` aşağı.
        placement_changed: `(widget_key, sütun, en)` — şəbəkə seçicisi (G-5).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ SÜRÜKLƏ-BURAX DEYİL, SEÇİCİ (audit G-5)
    ──────────────────────────────────────────────────────────────────────────
    Şəbəkə yerləşdirməsi üçün iki forma var idi:

      * SÜRÜKLƏ-BURAX — göz üçün ən aydın, LAKİN klaviatura ilə əlçatan
        deyil. Onu əlçatan etmək üçün onsuz da paralel bir klaviatura yolu
        (fokus + ox düymələri + elan mətnləri) yazılmalı olurdu, yəni iki
        mexanizm bir işi görərdi.
      * SEÇİCİ (`QComboBox`) — Qt-nin öz əlçatanlıq dəstəyi ilə gəlir: Tab
        ilə fokuslanır, ox düymələri ilə dəyişir, ekran oxuyucusu adı və
        dəyəri elan edir. Sətir/sütun/en ANLAYIŞI da açıq şəkildə görünür.

    İkincisi seçildi. SƏTİR nömrəsi ayrıca seçici DEYİL — o, mövcud
    yuxarı/aşağı düymələri ilə idarə olunur (sıra = sətir), yəni istifadəçi
    bir anlayışı iki yerdə öyrənmir.
    """

    toggled = Signal(str, bool)
    moved = Signal(str, int)
    placement_changed = Signal(str, int, int)

    def __init__(
        self,
        key: str,
        title: str,
        description: str,
        *,
        visible: bool,
        theme: ThemeManager,
        columns: int = 1,
        column: int = 0,
        span: int = 1,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.key = key

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(12)

        text_box = QWidget()
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        text_layout.addWidget(title_label(title, size=15))
        caption = muted_label(description)
        caption.setWordWrap(True)
        text_layout.addWidget(caption)
        layout.addWidget(text_box, 1)

        # Əlçatan ad SƏTRİN ADINI da daşıyır ("Yuxarı" tək başına mənasızdır:
        # ekran oxuyucusu düymələri kontekstsiz, bir-bir elan edir və on sətir
        # boyu eyni "Yuxarı" səslənərdi — hansı widget-in tərpəndiyi bilinməz).
        icon_color = theme.color("--color-text-secondary")
        up = icon_button(
            "arrow_up",
            icon_color,
            tooltip="Yuxarı",
            accessible_name=f"{title} — bir sətir yuxarı köçür",
        )
        up.clicked.connect(lambda: self.moved.emit(self.key, -1))
        layout.addWidget(up)

        down = icon_button(
            "arrow_down",
            icon_color,
            tooltip="Aşağı",
            accessible_name=f"{title} — bir sətir aşağı köçür",
        )
        down.clicked.connect(lambda: self.moved.emit(self.key, 1))
        layout.addWidget(down)

        # --- şəbəkə seçiciləri (G-5) --- #
        #
        # TƏK SÜTUNLU ŞƏBƏKƏDƏ ÜMUMİYYƏTLƏ QURULMUR: `columns == 1` olduqda
        # "hansı sütun?" sualının bir cavabı var və seçici yalnız sətri
        # doldurardı. `setEnabled(False)` ilə boz saxlamaq da seçilmədi —
        # layihənin ümumi qaydası mənasız elementi RENDER ETMƏMƏKDİR.
        self._column_box: QComboBox | None = None
        self._span_box: QComboBox | None = None
        if columns > 1:
            self._column_box = self._build_selector(
                [(str(index + 1), index) for index in range(columns)],
                current=max(0, min(columns - 1, column)),
                accessible_name=f"{title} — sütun",
                tooltip="Sütun",
            )
            layout.addWidget(field_label("Sütun"))
            layout.addWidget(self._column_box)

            self._span_box = self._build_selector(
                [(str(width), width) for width in range(1, columns + 1)],
                current=max(1, min(columns, span)),
                accessible_name=f"{title} — neçə sütun tutsun",
                tooltip="En (sütun sayı)",
            )
            layout.addWidget(field_label("En"))
            layout.addWidget(self._span_box)

            self._column_box.currentIndexChanged.connect(self._emit_placement)
            self._span_box.currentIndexChanged.connect(self._emit_placement)

        # Vəziyyət KONSTRUKTORDA verilir, `setChecked()` ilə yox: sonuncu
        # animasiya başladır və hadisə dövrü işləməyənə qədər açar hələ də
        # köhnə vəziyyəti çəkir (ekran ilk dəfə boyananda yanlış görünürdü).
        self._toggle = ToggleSwitch(theme, checked=visible)
        self._toggle.setAccessibleName(f"{title} — paneldə göstər")
        self._toggle.toggled.connect(lambda state: self.toggled.emit(self.key, state))
        layout.addWidget(self._toggle)

        # Sıra vizual sıra ilə üst-üstə düşür: mətn → yuxarı → aşağı →
        # sütun → en → açar.
        QWidget.setTabOrder(up, down)
        previous: QWidget = down
        for box in (self._column_box, self._span_box):
            if box is not None:
                QWidget.setTabOrder(previous, box)
                previous = box
        QWidget.setTabOrder(previous, self._toggle)

    @staticmethod
    def _build_selector(
        options: list[tuple[str, int]],
        *,
        current: int,
        accessible_name: str,
        tooltip: str,
    ) -> QComboBox:
        """Rəqəm seçicisi — dəyər `userData`-da saxlanılır, MƏTNDƏ yox.

        Mətndən oxumaq (`int(box.currentText())`) lokallaşdırma və "1-dən
        başlayan göstərmə / 0-dan başlayan indeks" fərqi ilə sınardı.
        """
        box = QComboBox()
        for label, value in options:
            box.addItem(label, value)
        box.setCurrentIndex(next((i for i, (_, v) in enumerate(options) if v == current), 0))
        box.setAccessibleName(accessible_name)
        box.setToolTip(tooltip)
        return box

    def _emit_placement(self) -> None:
        if self._column_box is None or self._span_box is None:  # pragma: no cover
            return
        self.placement_changed.emit(
            self.key,
            int(self._column_box.currentData()),
            int(self._span_box.currentData()),
        )

    def set_visible_state(self, visible: bool) -> None:
        self._toggle.setChecked(visible)


#: Panel Qurucusunun kontekstual köməyi (audit G-4).
#:
#: Mətn EKRANIN YANINDA yaşayır, mərkəzi kömək kataloqunda deyil — səbəbi
#: `widgets/help_hint.HelpButton` başlığındadır: sətrin AYRICA seçilməməsi
#: (axın-paketləmə, bax `_flow_rows`) qeyri-aşkar qərardır və izahı həmin
#: alqoritmlə eyni faylda qalmalıdır.
BUILDER_HELP_TITLE: Final = "Panel Qurucusu"

BUILDER_HELP_INTRO: Final = (
    "Bu ekranda İdarə Panelində hansı bölmələrin görünəcəyi, hansı sırada və "
    "şəbəkənin harasında duracağı təyin edilir. Hər dəyişiklik dərhal yadda "
    "saxlanılır — ayrıca «saxla» düyməsi yoxdur."
)

BUILDER_HELP_STEPS: Final[tuple[str, ...]] = (
    "Sətrin sonundakı açar bölməni panelə çıxarır və ya oradan yığışdırır. "
    "Gizlətmək heç bir məlumatı silmir — yalnız kartı görünüşdən çıxarır və "
    "istənilən vaxt geri qaytarılır.",
    "Yuxarı və aşağı ox düymələri bölmənin sırasını dəyişir. Sıra həm "
    "panelin oxunuş ardıcıllığını, həm də kartın şəbəkədə hansı sətrə "
    "düşəcəyini müəyyən edir.",
    "«Sütun» kartın haradan başlayacağını, «En» isə neçə sütun tutacağını "
    "seçir. Sətir ayrıca seçilmir: kart cari sətirdə yer varsa yan-yana "
    "qalır, yer qalmayıbsa özü aşağı düşür.",
    "«Şəbəkə önizləməsi» seçimin nəticəsini dərhal göstərir. Pəncərə "
    "daraldıqda şəbəkə tək sütuna yığılır — bu, qurduğunuz düzülüşü SİLMİR, "
    "yalnız həmin ölçüdə necə göstərildiyini dəyişir.",
    "«Defolta qaytar» görünürlüyü, sıranı və şəbəkə yerləşdirməsini eyni anda "
    "sistem defoltuna endirir. Bu addım GERİ QAYTARILA BİLMİR: əvvəlki "
    "düzülüş saxlanılmır və əl ilə yenidən qurulmalıdır.",
)


class DashboardBuilderScreen(Screen):
    """İdarə Panelinin konfiqurasiya ekranı (bölmə 6).

    Signals:
        layout_changed: Yeni düzülüş (görünən widget açarları, SIRA ilə).
        reset_requested: Defolt düzülüşə qayıt.
    """

    layout_changed = Signal(list)
    reset_requested = Signal()

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)
        self._rows: list[WidgetRow] = []
        self._order: list[str] = []
        self._visible: set[str] = set()
        self._catalog: dict[str, tuple[str, str]] = {}
        #: `açar → (sütun, en)`. SƏTİR burada YOXDUR: o, `self._order`
        #: sırasından hesablanır (bax `WidgetRow` başlığı — bir anlayış bir
        #: yerdə idarə olunur).
        self._placements: dict[str, tuple[int, int]] = {}
        self._columns = 1

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(
            section_header(
                "Panel Qurucusu",
                "Hansı bölmələrin görünəcəyini, sırasını və şəbəkədəki yerini təyin edin.",
            ),
            1,
        )

        # Kontekstual kömək (audit G-4) — «Defolta qaytar»-ın geri
        # qaytarılmaması və sətrin niyə seçilmədiyi (axın-paketləmə) ekranda
        # görünmürdü; hər ikisi burada izah olunur. Yuxarıya bərabərləşdirilir,
        # çünki qonşu düymə də başlığın ilk sətri ilə eyni xətdə durur.
        self._help = HelpButton(
            theme,
            title=BUILDER_HELP_TITLE,
            intro=BUILDER_HELP_INTRO,
            steps=BUILDER_HELP_STEPS,
        )
        header_layout.addWidget(self._help, alignment=Qt.AlignmentFlag.AlignTop)

        reset = secondary_button("Defolta qaytar")
        reset.clicked.connect(self.reset_requested)
        header_layout.addWidget(reset, alignment=Qt.AlignmentFlag.AlignTop)
        self.add(header)

        self._card = Card()
        self._list_layout = self._card.body()
        self.add(self._card)

        # --- şəbəkə önizləməsi (G-5) --- #
        # Seçicilər ədədlə işləyir; önizləmə həmin ədədlərin NƏ DEMƏK
        # olduğunu göstərir. Onsuz istifadəçi "sütun 2, en 1" yazıb nəticəni
        # yalnız İdarə Panelini açandan sonra görərdi.
        self._preview_card = Card()
        self._preview_card.add(title_label("Şəbəkə önizləməsi", size=15))
        self._preview_host = QWidget()
        self._preview_grid = QGridLayout(self._preview_host)
        self._preview_grid.setContentsMargins(0, 0, 0, 0)
        self._preview_grid.setSpacing(8)
        self._preview_card.add(self._preview_host)
        self._preview_note = muted_label("")
        self._preview_note.setWordWrap(True)
        self._preview_card.add(self._preview_note)
        self.add(self._preview_card)

        self._summary = muted_label("")
        self._summary.setWordWrap(True)
        self.add(self._summary)

        # Artıq hündürlük SONA — onsuz Qt boşluğu başlıq ilə kart arasında
        # bölüşdürür və izahsız aralıq yaranır (bax `group_h` eyni düzəliş).
        self.body().addStretch(1)

    def help_button(self) -> HelpButton:
        """Kontekstual kömək düyməsi — kontroller/testlər üçün."""
        return self._help

    def set_widgets(
        self,
        catalog: dict[str, tuple[str, str]],
        *,
        order: list[str],
        visible: set[str],
        placements: dict[str, tuple[int, int, int]] | None = None,
        columns: int = 1,
    ) -> None:
        """Kataloqu və cari düzülüşü göstərir.

        Args:
            catalog: `açar → (başlıq, izah)`.
            order: Göstərilmə sırası (kataloqda olmayan açarlar buraxılır).
            visible: Görünən açarlar.
            placements: `açar → (sətir, sütun, en)` (audit G-5). `None` →
                şəbəkə YOXDUR, davranış əvvəlki kimi XƏTTİDİR.
            columns: Şəbəkənin sütun sayı (ROOT: `DASHBOARD_GRID_COLUMNS`).

        İKİ SON ARQUMENT OPSİONALDIR VƏ BU, QƏSDƏNDİR: maket yolu
        (`preview_screens._dashboard_builder`), canlı yol
        (`controllers/dashboard_builder.py`) və mövcud testlər imzanı
        DƏYİŞMƏDƏN çağırmağa davam edir.
        """
        self._catalog = catalog
        self._columns = max(1, columns)
        self._order = [key for key in order if key in catalog]
        # Kataloqda olub sırada olmayan widget SONA əlavə olunur: yeni
        # modul əlavə edildikdə istifadəçinin köhnə düzülüşü onu gizlətməməli,
        # sadəcə sonuncu yerə qoymalıdır.
        self._order += [key for key in catalog if key not in self._order]
        self._visible = {key for key in visible if key in catalog}

        given = placements or {}
        # YERLƏŞDİRMƏSİ OLMAYAN AÇAR TAM ENLİ SƏTİR ALIR — `dashboard_layout.
        # normalize_placements`-dəki eyni geriyə-uyğunluq qaydası (köhnə xətti
        # konfiqurasiya EYNİ görünüşü verməlidir).
        self._placements = {}
        for key in self._order:
            _, column, span = given.get(key, (0, 0, self._columns))
            column = max(0, min(self._columns - 1, column))
            span = max(1, min(self._columns - column, span))
            self._placements[key] = (column, span)
        self._render()

    def _render(self) -> None:
        clear_layout(self._list_layout)
        self._rows = []

        for index, key in enumerate(self._order):
            title, description = self._catalog[key]
            column, span = self._placements.get(key, (0, self._columns))
            row = WidgetRow(
                key,
                title,
                description,
                visible=key in self._visible,
                theme=self.theme,
                columns=self._columns,
                column=column,
                span=span,
            )
            row.toggled.connect(self._on_toggled)
            row.moved.connect(self._on_moved)
            row.placement_changed.connect(self._on_placement_changed)
            self._rows.append(row)
            self._list_layout.addWidget(row)
            if index < len(self._order) - 1:
                self._list_layout.addWidget(Divider())

        self._update_summary()
        self._render_preview()
        self.show_content()

    # ---------------------------- şəbəkə önizləməsi -------------------------- #

    def _render_preview(self) -> None:
        """Görünən kartları şəbəkədə çəkir.

        DAR PƏNCƏRƏDƏ TƏK SÜTUN: rejim `Screen.apply_layout_mode`-dan gəlir
        (mərkəzi mexanizm, `widgets/responsive.py`) — burada yalnız TƏTBİQ
        olunur, en yenidən ÖLÇÜLMÜR.
        """
        clear_layout(self._preview_grid)
        compact = self.layout_mode is LayoutMode.COMPACT
        columns = 1 if compact else self._columns

        placed = [key for key in self._order if key in self._visible]
        if not placed:
            self._preview_note.setText("Görünən bölmə yoxdur — şəbəkə boşdur.")
            return

        if compact:
            for row_index, key in enumerate(placed):
                self._preview_grid.addWidget(self._preview_tile(key), row_index, 0, 1, 1)
        else:
            for key, row_index in self._flow_rows(placed).items():
                column, span = self._placements.get(key, (0, columns))
                self._preview_grid.addWidget(
                    self._preview_tile(key), row_index, column, 1, max(1, span)
                )

        self._preview_note.setText(
            "Dar pəncərədə şəbəkə tək sütuna yığılır — kartların oxunuş sırası dəyişmir."
            if compact
            else f"{columns} sütunlu şəbəkə. Hər sətir üçün sütun və en seçin."
        )

    def _flow_rows(self, keys: list[str]) -> dict[str, int]:
        """Sıradan SƏTİR nömrələrini hesablayır (axın-paketləmə).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ SƏTİR AYRICA SEÇİCİ DEYİL
        ──────────────────────────────────────────────────────────────────────
        Üç ayrı seçici (sətir + sütun + en) istifadəçidən üç ədədi UZLAŞDIRMAĞI
        tələb edərdi: "sətir 2, sütun 1" yazsa və 2-ci sətirdə heç nə olmasa,
        şəbəkədə izahsız boşluq yaranardı. Axın modeli isə tanışdır — mətn
        redaktorunda söz sətrə sığmayanda özü aşağı düşür:

            Sıra yuxarıdan aşağı gəzilir; hər kart SEÇDİYİ sütundan başlayır.
            Cari sətirdə yer varsa ORADA qalır (yan-yana), yoxdursa növbəti
            sətrə keçir.

        Nəticə: iki tam-enli kart avtomatik alt-alta, iki yarım-enli kart
        avtomatik yan-yana düşür — istifadəçi yalnız "bu kart nə qədər yer
        tutsun?" sualına cavab verir.
        """
        rows: dict[str, int] = {}
        row = 0
        occupied: set[int] = set()
        for key in keys:
            column, span = self._placements.get(key, (0, self._columns))
            column = max(0, min(self._columns - 1, column))
            span = max(1, min(self._columns - column, span))
            cells = set(range(column, column + span))
            if occupied & cells:
                row += 1
                occupied = set()
            occupied |= cells
            rows[key] = row
        return rows

    def _preview_tile(self, key: str) -> QWidget:
        title = self._catalog.get(key, (key, ""))[0]
        chip = Chip(title, "info" if key in self._visible else "neutral")
        chip.setAccessibleName(f"{title} — şəbəkədəki yeri")
        return chip

    def apply_layout_mode(self, mode: LayoutMode) -> None:
        """Rejim dəyişdi — önizləmə yenidən çəkilir.

        SEÇİCİLƏR TOXUNULMUR: istifadəçinin qurduğu şəbəkə GENİŞ ekran
        üçündür və pəncərəni daraltmaq onu SİLMƏMƏLİDİR — yalnız göstərilməsi
        dəyişir.
        """
        super().apply_layout_mode(mode)
        self._render_preview()

    # -------------------------------- hadisələr ------------------------------ #

    def _update_summary(self) -> None:
        self._summary.setText(
            f"{len(self._visible)}/{len(self._order)} bölmə göstərilir. "
            f"Dəyişiklik dərhal yadda saxlanılır."
        )

    def _on_toggled(self, key: str, visible: bool) -> None:
        if visible:
            self._visible.add(key)
        else:
            self._visible.discard(key)
        self._emit()
        self._update_summary()
        self._render_preview()

    def _on_moved(self, key: str, direction: int) -> None:
        """Sətri bir addım yuxarı/aşağı sürüşdürür.

        Sərhəddən kənara çıxma SƏSSİZCƏ nəzərə alınmır — ilk sətirdə "yuxarı"
        basmaq xəta deyil, sadəcə effektsizdir.
        """
        if key not in self._order:
            return
        index = self._order.index(key)
        target = index + direction
        if not 0 <= target < len(self._order):
            return
        self._order[index], self._order[target] = self._order[target], self._order[index]
        self._render()
        self._emit()

    def _on_placement_changed(self, key: str, column: int, span: int) -> None:
        """Sütun/en seçicisi dəyişdi.

        `span` SIXILIR: sütun 2-də en 2 seçmək 3-cü sütuna daşardı və şəbəkə
        özü-özünə örtüşərdi. Səhv seçim XƏTA GÖSTƏRMİR — sadəcə mümkün olan
        ən böyük enə enir (istifadəçi nəticəni önizləmədə dərhal görür).
        """
        if key not in self._placements:
            return
        column = max(0, min(self._columns - 1, column))
        span = max(1, min(self._columns - column, span))
        self._placements[key] = (column, span)
        self._emit()
        self._render_preview()

    def _emit(self) -> None:
        """Düzülüşü KODLANMIŞ formada yayır (bax `dashboard_layout` başlığı).

        Siqnalın tipi (`Signal(list)`) və kontrollerin kodu DƏYİŞMİR — yalnız
        sətirlərin məzmunu zənginləşir. Şəbəkə yoxdursa (`columns == 1`) sadə
        açar göndərilir, yəni köhnə davranış hərfən qorunur.
        """
        self.layout_changed.emit(self.current_layout())

    def current_layout(self) -> list[str]:
        """Görünən widget-lər — SIRA ilə (şəbəkə varsa kodlanmış).

        SƏTİR `_flow_rows` ilə hesablanır, sıradan BİRBAŞA götürülmür: sadə
        `enumerate` yan-yana duran iki kartı iki ayrı sətrə göndərərdi və
        istifadəçinin qurduğu şəbəkə hər saxlamada dağılardı.
        """
        visible_keys = [key for key in self._order if key in self._visible]
        if self._columns <= 1:
            return visible_keys
        rows = self._flow_rows(visible_keys)
        encoded: list[str] = []
        for key in visible_keys:
            column, span = self._placements[key]
            span = max(1, min(self._columns - column, span))
            encoded.append(f"{key}{PLACEMENT_SEPARATOR}{rows[key]},{column},{span}")
        return encoded


# --------------------------------------------------------------------------- #
# 38 — Plugin İdarəetməsi
# --------------------------------------------------------------------------- #


class PluginScreen(Screen):
    """Quraşdırılmış plugin-lərin siyahısı (bölmə 1, `can_manage_plugins`).

    Signals:
        install_requested: "Plugin Quraşdır".
        toggle_requested: `(plugin_id, aktivləşdirilsinmi)`.
        remove_requested: `plugin_id`.
    """

    install_requested = Signal()
    toggle_requested = Signal(str, bool)
    remove_requested = Signal(str)

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        self._summary = muted_label("")
        toolbar_layout.addWidget(self._summary)
        toolbar_layout.addWidget(stretch())
        install = action_button(
            "Plugin Quraşdır",
            icon_name="plus",
            icon_color=theme.color("--color-action-text"),
        )
        install.clicked.connect(self.install_requested)
        toolbar_layout.addWidget(install)
        self.add(toolbar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        host = QWidget()
        self._list_layout = QVBoxLayout(host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(metrics.CARD_SPACING)
        self._list_layout.addStretch(1)
        scroll.setWidget(host)
        self.add(scroll)

    def set_plugins(self, plugins: list[dict[str, str]]) -> None:
        """Plugin siyahısını göstərir.

        Args:
            plugins: `id`, `name`, `version`, `publisher`, `enabled` (`"1"`/`"0"`),
                `signature` (`valid` / `invalid` / `unsigned`).
        """
        clear_layout(self._list_layout, keep_last=1)

        if not plugins:
            # ────────────────────────────────────────────────────────────────
            # BOŞ VƏZİYYƏTDƏ DÜYMƏ BURADA OLMALIDIR — ALƏT ZOLAĞI GİZLƏNİR
            # ────────────────────────────────────────────────────────────────
            # `show_empty()` `ContentSwitcher`-i BOŞ vəziyyətə keçirir və bu,
            # bütün məzmun widget-ini — o cümlədən yuxarıdakı «Plugin Quraşdır»
            # düyməsini daşıyan alət zolağını — gizlədir. Nəticə dövrə idi:
            # plugin YOXDURSA quraşdırma düyməsi də yoxdur, yəni BİRİNCİ
            # plugin heç vaxt quraşdırıla bilməzdi.
            #
            # `EmptyState`-in öz əsas düyməsi məhz bunun üçündür: boş ekran
            # istifadəçini dalana yox, NÖVBƏTİ ADDIMA aparmalıdır.
            empty = self.show_empty(
                icon_name="grid",
                title="Plugin quraşdırılmayıb",
                message=(
                    "Plugin-lər ayrıca prosesdə, məhdud API səthi ilə işləyir və "
                    "yalnız imzalanmış paketlər qəbul edilir."
                ),
                primary_text="Plugin Quraşdır",
                primary_icon="plus",
            )
            # Hər çağırışda YENİ `EmptyState` qurulur (bax
            # `ContentSwitcher.show_empty`), ona görə təkrar bağlanma riski
            # yoxdur — köhnəsi siqnalı ilə birlikdə məhv olur.
            empty.primary_clicked.connect(self.install_requested)
            return

        enabled = sum(1 for plugin in plugins if plugin.get("enabled") == "1")
        self._summary.setText(f"{len(plugins)} plugin — {enabled} aktiv")

        for plugin in plugins:
            self._list_layout.insertWidget(self._list_layout.count() - 1, self._build_card(plugin))
        self.show_content()

    def _build_card(self, plugin: dict[str, str]) -> QWidget:
        card = Card()
        body = card.body()

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(12)
        head_layout.addWidget(title_label(plugin.get("name", ""), size=15))
        head_layout.addWidget(Chip(f"v{plugin.get('version', '?')}", "neutral"))

        # İMZA VƏZİYYƏTİ ƏN GÖRÜNƏN NİŞANDIR: imzasız plugin ayrıca prosesdə
        # işləsə belə, mənbəyi naməlumdur — istifadəçi bunu quraşdırma
        # qərarından ƏVVƏL görməlidir (bölmə 1, sandbox qaydası).
        signature = plugin.get("signature", "unsigned")
        head_layout.addWidget(
            Chip(
                {
                    "valid": "İmza doğrulandı",
                    "invalid": "İMZA YANLIŞDIR",
                    "unsigned": "İMZASIZ",
                }.get(signature, "İMZASIZ"),
                "success" if signature == "valid" else "danger",
            )
        )
        head_layout.addWidget(stretch())

        enabled = plugin.get("enabled") == "1"
        toggle = ToggleSwitch(self.theme, checked=enabled)
        plugin_id = plugin.get("id", "")
        toggle.toggled.connect(lambda state, pid=plugin_id: self.toggle_requested.emit(pid, state))
        head_layout.addWidget(toggle)
        body.addWidget(head)

        publisher = muted_label(f"Naşir: {plugin.get('publisher', 'naməlum')}")
        publisher.setWordWrap(True)
        body.addWidget(publisher)
        body.addWidget(Divider())

        remove = secondary_button("Sil")
        remove.clicked.connect(lambda *_, pid=plugin_id: self.remove_requested.emit(pid))
        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.addWidget(stretch())
        footer_layout.addWidget(remove)
        body.addWidget(footer)
        return card


# --------------------------------------------------------------------------- #
# 38b — Plugin səhifəsi (audit G-3)
# --------------------------------------------------------------------------- #


class PluginPageScreen(Screen):
    """Plugin-in menyuya əlavə etdiyi səhifə (`PluginCapability.REGISTER_PAGE`).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ QURULUŞU HOST TƏYİN EDİR, PLUGIN YALNIZ MƏTN VERİR
    ──────────────────────────────────────────────────────────────────────────
    Plugin-in widget ağacı qurmasına icazə vermək (məs. QML/HTML yükləmək)
    sandbox-un bütün mənasını itirərdi: ayrı prosesdə işləyən kod host-un
    pəncərəsinə birbaşa element yerləşdirə bilməzdi, ona görə də ya kod host
    prosesinə keçməli, ya da host ixtiyari işarələmə şərh etməli olardı. Hər
    ikisi yeni hücum səthidir.

    Ona görə forma BURADA sabitdir — başlıq, mənbə kartı və ad/dəyər sətirləri
    — plugin isə yalnız MƏTN doldurur. Ən pis halda istifadəçi yanlış mətn
    görər; kod icra oluna bilməz.

    ──────────────────────────────────────────────────────────────────────────
    MƏNBƏ KARTI NİYƏ MƏCBURİDİR
    ──────────────────────────────────────────────────────────────────────────
    İstifadəçi bu səhifənin KİM tərəfindən verildiyini bilməlidir. Naşir adı
    olmasaydı, plugin səhifəsi tətbiqin öz ekranı kimi görünərdi və "bu rəqəm
    haradandır?" sualının cavabı yox olardı.
    """

    def __init__(
        self,
        theme: ThemeManager,
        *,
        plugin_name: str,
        publisher: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(theme, parent=parent)

        source = Card(padding=16, spacing=12)
        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(12)
        head_layout.addWidget(title_label(plugin_name, size=15))
        head_layout.addWidget(Chip("Plugin", "info"))
        head_layout.addWidget(stretch())
        source.add(head)
        source.add(muted_label(f"Naşir: {publisher}"))
        source.add(
            body_label(
                "Bu bölmə plugin tərəfindən təqdim olunur. Plugin ayrıca prosesdə "
                "işləyir, baza bağlantısını və sirrləri GÖRMÜR və yalnız icazə "
                "verilmiş API səthini çağıra bilir.",
                size=13,
            )
        )
        self.add(source)

        self._rows_card = Card()
        self._rows_layout = self._rows_card.body()
        self.add(self._rows_card)

        self.body().addStretch(1)

    def set_rows(self, rows: list[tuple[str, str]]) -> None:
        """Ad/dəyər sətirlərini göstərir.

        Boş siyahı XƏTA DEYİL: plugin heç nə qaytarmaya bilər və bu, normal
        haldır — istifadəçi səbəbi görməlidir, boş ağ ekran yox.
        """
        clear_layout(self._rows_layout)
        if not rows:
            self.show_empty(
                icon_name="grid",
                title="Plugin məzmun qaytarmadı",
                message=(
                    "Bu səhifə plugin tərəfindən doldurulur. Hazırda göstəriləcək "
                    "məlumat yoxdur — plugin-i Plugin İdarəetməsi ekranından yoxlayın."
                ),
            )
            return

        for index, (label, value) in enumerate(rows):
            line = QWidget()
            line_layout = QHBoxLayout(line)
            line_layout.setContentsMargins(0, 6, 0, 6)
            line_layout.setSpacing(12)
            line_layout.addWidget(muted_label(label))
            line_layout.addWidget(stretch())
            line_layout.addWidget(body_label(value, size=13, wrap=False))
            self._rows_layout.addWidget(line)
            if index < len(rows) - 1:
                self._rows_layout.addWidget(Divider())

        self.show_content()


# --------------------------------------------------------------------------- #
# 39 — İstisnalar (Vahid İstisna Motoru, #9 — kompasos11.md Faza 5)
# --------------------------------------------------------------------------- #


class ExceptionsScreen(Screen):
    """Açıq davranış-anomaliyası siqnallarının jurnalı (`can_view_exceptions`).

    ──────────────────────────────────────────────────────────────────────────
    MƏNBƏ-BADGE NİYƏ SƏRT ZƏNCİR DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Motor rule-registry ilə qurulub (bax `exception_engine.py` başlığı) — YENİ
    mənbə YALNIZ `registry.register(...)` ilə qoşulur, motorun kodu
    TOXUNULMUR. Ekran eyni prinsipi təkrarlayır: nişanın MƏTNİ hər sətirdə
    `ExceptionView.source_name_az`-dan (bazadan) gəlir, `if source == "..."`
    zənciri YOXDUR. Ton isə QƏSDƏN sabitdir ("info") — mənbəyə görə rəngləmək
    hər yeni mənbə üçün BURAYA da toxunmağı tələb edərdi, halbuki motor məhz
    bunun qarşısını almaq üçün qurulub. Ciddiyyət nişanı (aşağıda) fərqlidir:
    `ExceptionSeverity` SƏRT siyahıdır (bax `exception_signals.py` başlığı),
    ona görə onun rəng lüğəti kodda saxlanıla bilər.

    Signals:
        reviewed_requested: `exception_id` — "[Nəzərdən Keçirildi]" (qeyd
            könüllüdür, dialoq açılmır).
        dismissed_requested: `exception_id` — "[Rədd Et]" (səbəb kontrollerdə
            soruşulur, çünki domen qaydası onu MƏCBURİ edir — bax
            `ExceptionRecord.dismiss`).
    """

    reviewed_requested = Signal(str)
    dismissed_requested = Signal(str)

    #: Ciddiyyət kodu → nişan tonu. `ExceptionSeverity` SƏRT enum-dur (yeni
    #: dəyər buraxılış tələb edir), ona görə burada sabit lüğət YAZILA bilər —
    #: mənbə lüğəti ilə eyni azadlıq YOXDUR (bax sinif başlığı).
    _SEVERITY_TONES: Final[dict[str, ChipTone]] = {
        "LOW": "neutral",
        "MEDIUM": "info",
        "HIGH": "warning",
        "CRITICAL": "danger",
    }

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)

        self._table = DataTable(
            [
                Column("Mənbə", 160),
                Column("İşçi", 160),
                Column("Mağaza", 140),
                Column("Təfərrüat", 240),
                Column("Ciddiyyət", 100),
                Column("Tarix", 140, mono=True),
                Column("Əməliyyat"),
            ],
            theme,
            footnote=("Bağlanmış istisna yenidən açılmır — rədd qərarı da audit jurnalına düşür."),
        )
        self.add(self._table)

    def set_exceptions(self, rows: list[dict[str, str]]) -> None:
        """Açıq istisnaları göstərir.

        Args:
            rows: `id`, `source`, `source_name`, `employee`, `store`,
                `detail`, `severity`, `severity_text`, `date` açarları —
                canlı yol (`controllers/exceptions.py`) və maket yolu
                (`preview_screens._exceptions`) EYNİ dəsti göndərir.
        """
        self._table.clear()
        if not rows:
            self.show_empty(
                icon_name="shield",
                title="Açıq istisna yoxdur",
                message="Bütün davranış siqnalları nəzərdən keçirilib.",
            )
            return

        for row in rows:
            exception_id = row.get("id", "")
            severity = row.get("severity", "")

            detail = muted_label(row.get("detail", ""))
            # SÖZƏ GÖRƏ SARILMA: təfərrüat mətni sabit enli xanadadır (240px),
            # sarılmayan uzun mətn `DataTable` sütununu genişləndirər və
            # nəticə bütün ekranlara sızardı (bax `DataTable` başlığı).
            detail.setWordWrap(True)

            self._table.add_row(
                [
                    # Naməlum/gələcək mənbə də mətnini BAZADAN alır — sərt
                    # `if` zənciri yoxdur (bax sinif başlığı).
                    Chip(row.get("source_name", "") or row.get("source", ""), "info"),
                    row.get("employee", ""),
                    row.get("store", ""),
                    detail,
                    Chip(
                        row.get("severity_text", "") or severity,
                        self._SEVERITY_TONES.get(severity, "neutral"),
                    ),
                    mono_label(row.get("date", "")),
                    self._build_actions(exception_id),
                ]
            )
        self.show_content()

    def _build_actions(self, exception_id: str) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        review = secondary_button("Nəzərdən Keçirildi")
        review.clicked.connect(lambda: self.reviewed_requested.emit(exception_id))
        layout.addWidget(review)

        # "Rədd Et" `danger` variantını alır — `PosThresholdDialog`-dakı
        # "Geri Al" ilə EYNİ naxış (`secondary_button` + üstündən `variant`
        # dəyişikliyi), yeni kontrast cütü yaratmır.
        dismiss = secondary_button("Rədd Et")
        dismiss.setProperty("variant", "danger")
        dismiss.clicked.connect(lambda: self.dismissed_requested.emit(exception_id))
        layout.addWidget(dismiss)

        return container

    def table(self) -> DataTable:
        return self._table


__all__ = [
    "DashboardBuilderScreen",
    "ExceptionsScreen",
    "InfrastructureScreen",
    "MigrationConfirmDialog",
    "PhaseRow",
    "PluginScreen",
    "WidgetRow",
]
