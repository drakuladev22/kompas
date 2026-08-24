""" "Toplu Əməliyyatlar" ekranı — #29, kompas1.md Faza 5.

CSV işçi idxalı VƏ mağaza şablonu BİR ekranda, İKİ kartda göstərilir (aşağı
bax "NİYƏ İKİ AYRI MENYU MADDƏSİ YOX"). Backend tam yazılıb
(`application/use_cases/bulk_operations.py`) — bu fayl YALNIZ təqdimat
qatıdır: ekran domen tiplərini (`BulkImportPreview`, `StoreTemplate`, ...)
TANIMIR, yalnız sadə tip (sətir, ədəd, sözlük) qəbul edir və `Signal`larla
kontrollerə (bax `controllers/bulk_operations.py`) ötürür — `fine_entry.py`
başlığındakı eyni qayda: "Ekran domen tiplərini tanımır".

──────────────────────────────────────────────────────────────────────────────
NİYƏ İKİ AYRI MENYU MADDƏSİ YOX
──────────────────────────────────────────────────────────────────────────────
`field_reports.py` iki fərqli menyu açarını (`store_audit`/`incident_report`)
BİR ekran sinfinə bağlayır, çünki backend-də İKİ AYRI şablon KATEQORİYASI var.
Burada isə hər iki funksiya (CSV idxalı, mağaza şablonu) EYNİ TƏK icazə
flag-inə bağlıdır (`can_perform_bulk_operations`, `bulk_operations.py`
başlığı: "HƏR İKİ use case-in ORTAQ qapısıdır") və backend-də də TƏK modul
faylındadır. İki ayrı menyu maddəsi yaratmaq eyni qapının arxasında iki
görünüş yaradardı — istifadəçi "Toplu Əməliyyatlar" menyusuna girəndə hər
ikisini görməyi gözləyir, HR-in gündəlik işi də elə budur: yeni filial
açılanda ƏVVƏLCƏ şablon tətbiq edilir, SONRA həmin filialın işçiləri CSV ilə
yüklənir — iki addım eyni iş axınının hissəsidir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ EKRAN HEÇ VAXT `show_error()` ÇAĞIRMIR (TAM-EKRAN XƏTA VƏZİYYƏTİ YOXDUR)
──────────────────────────────────────────────────────────────────────────────
`Screen.show_error()` bütün `ContentSwitcher`-i xəta vəziyyəti ilə ƏVƏZ EDİR —
tək-məqsədli ekranlarda (`AnnouncementsScreen`, `FieldReportScreen`) bu
düzgündür, çünki oxu uğursuz olanda göstəriləcək başqa məzmun yoxdur. Burada
İSƏ ekran İKİ MÜSTƏQİL bölmədən ibarətdir: şablon siyahısı oxunmasa belə, CSV
idxal forması İŞLƏK qalmalıdır (və əksinə). Ona görə hər bölmənin öz DAXİLİ
mesaj sətri var (`set_import_message`/`set_template_message`) — bax
`FieldReportScreen.set_list_notice` ilə eyni qərar, tətbiq sahəsi genişlənib.

──────────────────────────────────────────────────────────────────────────────
QİSMƏN İDXAL EKRANDA NECƏ GÖRÜNÜR — İKİ ADDIM, GERİ QAYITMAZ SƏTİR YOXDUR
──────────────────────────────────────────────────────────────────────────────
"Önizlə" → sətir-sətir yoxlama (`BULK_IMPORT_PREVIEW_ERROR_LIMIT` ROOT
tavanına qədər göstərilir, aşanı "İdxal Et" düyməsi YALNIZ ən azı bir DÜZGÜN
sətir olduqda aktivləşir. Bu, backend-in "hamısı-ya-heçnə DEYİL" qərarının
(`bulk_operations.py` başlığı) GUI güzgüsüdür: HR əvvəlcə NƏ QƏDƏR sətrin
uğursuz olacağını görür, sonra şüurlu şəkildə təsdiq edir — kor-koranə "İdxal
Et" basıb nəticəni YALNIZ sonda öyrənmir.

──────────────────────────────────────────────────────────────────────────────
MÜVƏQQƏTİ ŞİFRƏ — `BulkImportResultDialog` NİYƏ MODAL DİALOQ, EKRANIN ÖZÜ YOX
──────────────────────────────────────────────────────────────────────────────
`BulkImportReport.created[].temporary_password` BİR DƏFƏLİK qaytarılır (bax
`bulk_operations.py` başlığı) — nə audit-ə, nə `bulk_import_log`-a yazılmır.
Əgər şifrələr BU EKRANIN öz sahəsində (məs. `set_result(...)` ilə) saxlansaydı,
onlar `AdminShell`-in ekran keşində (`app.py::show_screen` ekranı YENİDƏN
QURMUR, saxlayır) NAVİQASİYA arasında da yaddaşda QALARDI — istifadəçi "Toplu
Əməliyyatlar"dan çıxıb geri qayıtsa belə köhnə şifrələr görünərdi. Ona görə
nəticə AYRI, MODAL `QDialog`-dadır (`WA_DeleteOnClose` ilə): `dialog.exec()`
bitəndə Qt obyekti VƏ onun daşıdığı Python siyahısı (parol mətnləri daxil)
DƏRHAL çöp yığılır (bax `controllers/bulk_operations.py::_show_result` —
kontroller də nəticəni HEÇ BİR sahədə saxlamır, yalnız dialoqu qurub bağlayır).
"Hamısını Kopyala" bunun ƏVƏZİDİR: HR 50 şifrəni əl ilə YAZMAQ deyil, BİR
kliklə mübadilə buferinə köçürüb dərhal Excel-ə yapışdıra bilir.

──────────────────────────────────────────────────────────────────────────────
MAĞAZA ŞABLONU — `config_snapshot`-U İSTİFADƏÇİ ƏL İLƏ YAZMIR
──────────────────────────────────────────────────────────────────────────────
`StoreTemplateCaptureDialog`-da sərbəst "ayar" sahəsi YOXDUR — yalnız ad və
mənbə mağaza seçilir. `config_snapshot`-u (mənbə mağazada işlədilən rollar)
KONTROLLER avtomatik OXU sorğusu ilə doldurur (bax `bulk_operations.py`
use case başlığı: "çağıran tərəfin ... TƏQDİM ETDİYİ ayar lüğəti"). Səbəb:
əl ilə yazılan sərbəst mətn (məs. "Kassir, kassir, KASSİR") heç bir təsdiq
keçmir və şablonu istifadəsiz zibilə çevirər — OXU sorğusu isə HƏMİŞƏ mövcud
kataloq adlarını yazır. `StoreTemplateApplyDialog` isə tətbiqdən ƏVVƏL HƏM bu
siyahını, HƏM DƏ "köçürülməyəcək" siyahısını AÇIQ göstərir (`NOT_TRANSFERRED_
TEXT`) — istifadəçi "hər şey köçdü" gözləməsin deyə (bax `bulk_operations.py`
başlığı, "MAĞAZA ŞABLONU").
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QVBoxLayout, QWidget

from src.presentation.screens.base import Screen
from src.presentation.theme.manager import refresh_widget_style
from src.presentation.widgets import metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.data_table import Column, DataTable
from src.presentation.widgets.forms import FormField, field_label
from src.presentation.widgets.primitives import (
    Card,
    Chip,
    Divider,
    body_label,
    mono_label,
    muted_label,
    stretch,
    title_label,
)

if TYPE_CHECKING:
    from src.presentation.theme.manager import ThemeManager

#: Fayl seçicisinin süzgəci — YALNIZ CSV. `group_c.EmployeeDocumentDialog.
#: _pick_file` başlığındakı eyni qeyd: süzgəc QORUMA DEYİL, yalnız istifadəçini
#: yanlış fayl növünə aparmır — həqiqi yoxlama `bulk_operations.py::_parse`-dadır.
CSV_FILE_FILTER: Final = "CSV faylları (*.csv);;Bütün fayllar (*.*)"

#: Tətbiqdən ƏVVƏL göstərilən, DƏYİŞMƏYƏN xəbərdarlıq mətni — bax modul
#: başlığı. Sözbəsöz `bulk_operations.py`-dəki "config_snapshot NƏYİ ETMİR"
#: siyahısının ekran üzü.
NOT_TRANSFERRED_TEXT: Final = (
    "KÖÇÜRÜLMƏYƏCƏK: işçilər (yeni mağaza SIFIR işçi ilə yaranır), cərimə "
    "tarixçəsi və satış/xal tarixçəsi. Rol və iş rejimi kataloqları da "
    "YENİDƏN YARADILMIR — onlar bütün mağazalar üçün onsuz da ortaq "
    "kataloqdur, yeni mağaza onlara birbaşa baxa bilir."
)

_PREVIEW_COLUMNS: Final[list[Column]] = [Column("Sətir", 70, mono=True), Column("Səbəb")]
_TEMPLATE_COLUMNS: Final[list[Column]] = [
    Column("Ad", 170),
    Column("Mənbə mağaza", 170),
    Column("Ayar sayı", 90, mono=True),
    Column("Çəkilmə tarixi", 120, mono=True),
    Column("Vəziyyət", 90),
    Column("Əməliyyat"),
]


class BulkOperationsScreen(Screen):
    """CSV işçi idxalı kartı + mağaza şablonu kartı.

    Signals:
        preview_requested: seçilmiş faylın YEREL yolu — "Önizlə".
        import_requested: seçilmiş faylın YEREL yolu — "İdxal Et" (yalnız
            uğurlu önizləmədən sonra AKTİV olur, bax `set_preview`).
        capture_requested: "Şablon Çıxar" — kontroller mağaza siyahısını
            oxuyub `StoreTemplateCaptureDialog`-u AÇIR.
        apply_requested: şablon ID-si — "Tətbiq Et".
        deactivate_requested: şablon ID-si — "Deaktiv Et".
    """

    preview_requested = Signal(str)
    import_requested = Signal(str)
    capture_requested = Signal()
    apply_requested = Signal(str)
    deactivate_requested = Signal(str)

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)
        self._file_path = ""

        self.add(self._build_import_card())
        self.add(self._build_template_card())

        self.clear_preview()
        self.set_templates([])
        self.show_content()

    # ------------------------------- CSV idxalı -------------------------------- #

    def _build_import_card(self) -> Card:
        # VİZUAL FAZA #1 — KÖLGƏ GERİ ALINDI (4-cü bənd): ölçülmüş repaint
        # bu TAM-ENLİ paneli ölçdü — kölgəli repaint 18.13 ms (60fps
        # büdcəsi 16.67 ms-i AŞIR), kölgəsiz 2.00 ms. Xərc kart SAYINDAN
        # yox, SAHƏDƏN asılıdır — bu, geniş panel, kompakt kart deyil.
        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)
        card.add(title_label("CSV İşçi İdxalı", size=19))
        card.add(
            muted_label(
                "Əvvəlcə fayl seçib ÖNİZLƏYİN — sətir-sətir xəta aşağıda göstərilir. "
                "Xətalı sətirlər ATLANIR, düzgün sətirlər YENƏ DƏ idxal olunur "
                "(qismən idxal qəsdəndir — bir səhv poçt ünvanına görə bütün fayl "
                "rədd edilmir)."
            )
        )
        card.add(Divider())

        file_row = QWidget()
        file_row_layout = QHBoxLayout(file_row)
        file_row_layout.setContentsMargins(0, 0, 0, 0)
        file_row_layout.setSpacing(metrics.SPACE_MS)
        self._file_label = muted_label("Fayl seçilməyib")
        file_row_layout.addWidget(self._file_label, stretch=1)
        pick_button = secondary_button("CSV Faylı Seç")
        pick_button.clicked.connect(self._pick_file)
        file_row_layout.addWidget(pick_button)
        card.add(file_row)

        actions_row = QWidget()
        actions_layout = QHBoxLayout(actions_row)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(metrics.SPACE_MS)
        actions_layout.addWidget(stretch())
        preview_button = secondary_button("Önizlə")
        preview_button.clicked.connect(self._on_preview_clicked)
        actions_layout.addWidget(preview_button)
        self._import_button = action_button("İdxal Et")
        self._import_button.clicked.connect(self._on_import_clicked)
        actions_layout.addWidget(self._import_button)
        card.add(actions_row)

        self._import_message = muted_label("")
        self._import_message.setWordWrap(True)
        card.add(self._import_message)

        card.add(Divider())
        self._preview_summary = muted_label("")
        self._preview_summary.setWordWrap(True)
        card.add(self._preview_summary)

        self._error_table = DataTable(
            _PREVIEW_COLUMNS,
            self.theme,
            footnote="Yalnız ROOT tavanına qədər göstərilir — aqreqat say HƏMİŞƏ tamdır.",
        )
        card.add(self._error_table)

        self._truncated_note = muted_label("")
        self._truncated_note.setWordWrap(True)
        card.add(self._truncated_note)
        return card

    def _pick_file(self) -> None:
        from PySide6.QtWidgets import QFileDialog  # noqa: PLC0415

        path, _selected = QFileDialog.getOpenFileName(
            self, "İşçi siyahısı CSV faylını seçin", "", CSV_FILE_FILTER
        )
        if not path:
            return
        self._file_path = path
        self._file_label.setText(_file_name(path))
        # Fayl DƏYİŞƏNDƏ köhnə önizləmə etibarsızdır — istifadəçi YENİDƏN
        # önizləməli, kor-koranə köhnə nəticəyə görə idxal etməməlidir.
        self.clear_preview(keep_file=True)

    def _on_preview_clicked(self) -> None:
        self.set_import_message("")
        if not self._file_path:
            self.set_import_message("Zəhmət olmasa əvvəlcə CSV faylı seçin.", error=True)
            return
        self.preview_requested.emit(self._file_path)

    def _on_import_clicked(self) -> None:
        if not self._file_path or not self._import_button.isEnabled():
            return
        self.import_requested.emit(self._file_path)

    def set_preview(
        self,
        *,
        total_rows: int,
        valid_count: int,
        error_count: int,
        errors: list[dict[str, str]],
        truncated_extra: int,
    ) -> None:
        """Önizləmə nəticəsi — açarlar `controllers/bulk_operations.py::
        _preview_payload` ilə EYNİDİR (CLAUDE.md §6).

        Args:
            errors: `row`, `message` açarları — HƏR BİRİ ROOT tavanına qədər
                (`BULK_IMPORT_PREVIEW_ERROR_LIMIT`) göstərilən alt-çoxluqdur.
        """
        self.set_import_message("")
        if total_rows == 0:
            self._preview_summary.setText(
                "Fayl 0 sətir daşıyır (yalnız başlıq sətri) — idxal ediləcək heç nə yoxdur."
            )
            self._error_table.clear()
            self._error_table.setVisible(False)
            self._truncated_note.setVisible(False)
            self._import_button.setEnabled(False)
            return

        self._preview_summary.setText(
            f"{total_rows} sətir oxundu — {valid_count} düzgün, {error_count} xətalı."
        )
        self._error_table.clear()
        self._error_table.setVisible(bool(errors))
        for row in errors:
            self._error_table.add_row([mono_label(row.get("row", "")), row.get("message", "")])

        if truncated_extra > 0:
            self._truncated_note.setText(
                f"… və daha {truncated_extra} xəta göstərilmir (ROOT limiti). "
                "Aqreqat say yuxarıda TAMDIR."
            )
            self._truncated_note.setVisible(True)
        else:
            self._truncated_note.setVisible(False)

        self._import_button.setEnabled(valid_count > 0)
        if valid_count == 0:
            self.set_import_message(
                "İdxal ediləcək düzgün sətir yoxdur — bütün sətirlər xəta ilə rədd edildi. "
                "Faylı düzəldib yenidən seçin.",
                error=True,
            )

    def clear_preview(self, *, keep_file: bool = False) -> None:
        """Önizləmə vəziyyətini sıfırlayır.

        `keep_file=True` — yalnız fayl DƏYİŞƏNDƏ (`_pick_file`) işlədilir: yeni
        fayl seçilib, lakin hələ önizlənməyib. `keep_file=False` — uğurlu
        idxaldan SONRA (kontroller çağırır) növbəti yükləmə üçün TAM sıfırlama.
        """
        if not keep_file:
            self._file_path = ""
            self._file_label.setText("Fayl seçilməyib")
        self._preview_summary.setText("")
        self._error_table.clear()
        self._error_table.setVisible(False)
        self._truncated_note.setVisible(False)
        self._import_button.setEnabled(False)
        self.set_import_message("")

    def set_import_message(self, message: str, *, error: bool = False) -> None:
        self._import_message.setText(message)
        self._import_message.setProperty("variant", "danger-text" if error else "muted")
        self._import_message.setVisible(bool(message))
        refresh_widget_style(self._import_message)

    # ----------------------------- mağaza şablonu ------------------------------ #

    def _build_template_card(self) -> Card:
        # VİZUAL FAZA #1 — KÖLGƏ VERİLMİR (4-cü bənd, ölçülmüş): təbii eni
        # 2767px — tipik 1400px pəncərədən GENİŞ, "Mağaza Şablonları"
        # tam-enli paneldir. Ölçülmüş repaint: 10.09 ms (60fps büdcəsinin
        # 60%-i), `_build_import_card`-la EYNİ sinif.
        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(metrics.SPACE_MS)
        header_layout.addWidget(title_label("Mağaza Şablonları", size=19))
        header_layout.addWidget(stretch())
        capture_button = action_button(
            "Şablon Çıxar", icon_name="plus", icon_color=self.theme.color("--color-action-text")
        )
        capture_button.clicked.connect(self.capture_requested)
        header_layout.addWidget(capture_button)
        card.add(header)

        card.add(
            muted_label(
                "Mövcud bir mağazanın rol quruluşunu YENİ filial üçün İSTİNAD "
                "şablonuna çevirir. Mənbə mağazanın özü DƏYİŞMİR — köçürmə TƏK "
                "İSTİQAMƏTLİDİR."
            )
        )
        card.add(Divider())

        self._template_message = muted_label("")
        self._template_message.setWordWrap(True)
        card.add(self._template_message)

        self._template_empty = muted_label("Hələ şablon yaradılmayıb.")
        card.add(self._template_empty)

        self._template_table = DataTable(
            _TEMPLATE_COLUMNS,
            self.theme,
            footnote="Deaktiv şablon SİLİNMİR — soft delete, yalnız yeni tətbiqdə seçilə bilmir.",
        )
        card.add(self._template_table)
        return card

    def set_templates(self, rows: list[dict[str, str]]) -> None:
        """Şablon siyahısı — açarlar `controllers/bulk_operations.py::
        _to_template_rows` ilə EYNİDİR (CLAUDE.md §6).

        Args:
            rows: `id`, `name`, `source_store`, `setting_count`, `captured_at`,
                `status` (`"Aktiv"`/`"Deaktiv"`) açarları.
        """
        self._template_table.clear()
        self._template_empty.setVisible(not rows)
        self._template_table.setVisible(bool(rows))
        for row in rows:
            self._template_table.add_row(self._build_template_cells(row))

    def _build_template_cells(self, row: dict[str, str]) -> list[QWidget | str]:
        template_id = row.get("id", "")
        is_active = row.get("status") == "Aktiv"

        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)
        if is_active:
            apply_button = secondary_button("Tətbiq Et")
            apply_button.clicked.connect(lambda *_, key=template_id: self.apply_requested.emit(key))
            actions_layout.addWidget(apply_button)
            deactivate_button = secondary_button("Deaktiv Et")
            deactivate_button.setProperty("variant", "danger")
            deactivate_button.clicked.connect(
                lambda *_, key=template_id: self.deactivate_requested.emit(key)
            )
            actions_layout.addWidget(deactivate_button)
        else:
            actions_layout.addWidget(muted_label("—"))

        return [
            row.get("name", ""),
            row.get("source_store", "") or "—",
            mono_label(row.get("setting_count", "0")),
            mono_label(row.get("captured_at", "")),
            Chip("Aktiv" if is_active else "Deaktiv", "success" if is_active else "neutral"),
            actions,
        ]

    def set_template_message(self, message: str, *, error: bool = False) -> None:
        self._template_message.setText(message)
        self._template_message.setProperty("variant", "danger-text" if error else "muted")
        self._template_message.setVisible(bool(message))
        refresh_widget_style(self._template_message)


class StoreTemplateCaptureDialog(QDialog):
    """ "Şablon Çıxar" forması — bax modul başlığı ("config_snapshot-u ...").

    Signals:
        submitted: `(name, source_store_id)` — `config_snapshot` BURADA
            QURULMUR, kontroller mənbə mağazanı OXUYARAQ qurur.
    """

    submitted = Signal(str, str)

    def __init__(
        self,
        theme: ThemeManager,
        *,
        stores: list[tuple[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Mağaza Şablonu Çıxar")
        self.setModal(True)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # VİZUAL FAZA #1 — dialoqun BÜTÖV məzmun kartı, BİR dəfə qurulur.
        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING, shadow=True)
        layout.addWidget(card)
        card.add(title_label("Mağaza Şablonu Çıxar", size=19))
        card.add(
            muted_label(
                "Seçilmiş mağazada işlədilən rollar YENİ şablona istinad kimi "
                "yazılır. Mənbə mağazanın cari məlumatı DƏYİŞMİR — bu, YALNIZ oxumadır."
            )
        )
        card.add(Divider())

        self._name = FormField("Şablon adı")
        card.add(self._name)

        self._store_combo = QComboBox()
        for store_id, name in stores:
            self._store_combo.addItem(name, store_id)
        card.add(FormField("Mənbə mağaza", widget=self._store_combo))

        self._error = muted_label("")
        self._error.setProperty("variant", "danger-text")
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        card.add(self._error)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(metrics.SPACE_MS)
        buttons_layout.addWidget(stretch())
        cancel = secondary_button("İmtina")
        cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel)
        submit = action_button("Şablon Yarat")
        submit.clicked.connect(self._on_submit)
        submit.setDefault(True)
        submit.setAutoDefault(True)
        cancel.setAutoDefault(False)
        buttons_layout.addWidget(submit)
        card.add(buttons)

        self._name.focus_input()

    def _on_submit(self) -> None:
        self._name.clear_error()
        self._error.setVisible(False)
        name = self._name.text().strip()
        if not name:
            self._name.set_error("Şablon adı məcburidir")
            return
        source_store_id = str(self._store_combo.currentData() or "")
        if not source_store_id:
            self._error.setText("Mənbə mağaza seçilməlidir — boş siyahıdan şablon çıxarıla bilməz.")
            self._error.setVisible(True)
            return
        self.submitted.emit(name, source_store_id)
        self.accept()


class StoreTemplateApplyDialog(QDialog):
    """ "Tətbiq Et" forması — yeni (boş) mağaza yaradır.

    Signals:
        submitted: `(code, name, brand, address)` — `StoreDraft` sahələri ilə
            EYNİ SIRA (bax `controllers/bulk_operations.py::_submit_apply`).
    """

    submitted = Signal(str, str, str, str)

    def __init__(
        self,
        theme: ThemeManager,
        *,
        template_name: str,
        snapshot_summary: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Şablonu Tətbiq Et")
        self.setModal(True)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # VİZUAL FAZA #1 — dialoqun BÜTÖV məzmun kartı, BİR dəfə qurulur.
        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING, shadow=True)
        layout.addWidget(card)
        card.add(title_label(f"«{template_name}» şablonunu tətbiq et", size=19))

        card.add(field_label("Şablonda İSTİNAD kimi saxlanılan rollar"))
        summary_label = muted_label(snapshot_summary or "—")
        summary_label.setWordWrap(True)
        card.add(summary_label)

        card.add(Divider())
        warning = muted_label(NOT_TRANSFERRED_TEXT)
        warning.setProperty("variant", "danger-text")
        warning.setWordWrap(True)
        card.add(warning)
        card.add(Divider())

        self._code = FormField("Mağaza kodu")
        card.add(self._code)
        self._name = FormField("Mağaza adı")
        card.add(self._name)
        self._brand = FormField("Brend")
        card.add(self._brand)
        self._address = FormField("Ünvan (könüllü)")
        card.add(self._address)

        self._error = muted_label("")
        self._error.setProperty("variant", "danger-text")
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        card.add(self._error)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(metrics.SPACE_MS)
        buttons_layout.addWidget(stretch())
        cancel = secondary_button("İmtina")
        cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel)
        submit = action_button("Yeni Mağaza Yarat")
        submit.clicked.connect(self._on_submit)
        submit.setDefault(True)
        submit.setAutoDefault(True)
        cancel.setAutoDefault(False)
        buttons_layout.addWidget(submit)
        card.add(buttons)

        self._code.focus_input()

    def _on_submit(self) -> None:
        for field in (self._code, self._name, self._brand):
            field.clear_error()
        self._error.setVisible(False)

        code = self._code.text().strip()
        name = self._name.text().strip()
        brand = self._brand.text().strip()
        address = self._address.text().strip()

        if not code:
            self._code.set_error("Mağaza kodu məcburidir")
            return
        if not name:
            self._name.set_error("Mağaza adı məcburidir")
            return
        if not brand:
            self._brand.set_error("Brend adı məcburidir")
            return

        self.submitted.emit(code, name, brand, address)
        self.accept()


class BulkImportResultDialog(QDialog):
    """İdxal nəticəsi — müvəqqəti şifrələr YALNIZ BURADA görünür (bax modul başlığı).

    `WA_DeleteOnClose`: dialoq bağlananda Qt obyekti VƏ onun daşıdığı Python
    siyahısı (`created`, parol mətnləri daxil) DƏRHAL çöp yığılır — heç bir
    sahə, heç bir kontroller atributu bu siyahını SAXLAMIR.
    """

    def __init__(
        self,
        theme: ThemeManager,
        *,
        success_count: int,
        error_count: int,
        errors: list[dict[str, str]],
        truncated_extra: int,
        created: list[dict[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("İdxal Nəticəsi")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # VİZUAL FAZA #1 — dialoqun BÜTÖV məzmun kartı, BİR dəfə qurulur.
        card = Card(padding=metrics.CARD_PADDING, spacing=metrics.CARD_CONTENT_SPACING, shadow=True)
        layout.addWidget(card)
        card.add(title_label("İdxal Nəticəsi", size=19))
        card.add(
            muted_label(f"{success_count} işçi uğurla yaradıldı, {error_count} sətir rədd edildi.")
        )

        if errors:
            card.add(Divider())
            card.add(body_label("Rədd edilən sətirlər", size=13))
            error_table = DataTable(_PREVIEW_COLUMNS, theme)
            for row in errors:
                error_table.add_row([mono_label(row.get("row", "")), row.get("message", "")])
            card.add(error_table)
            if truncated_extra > 0:
                note = muted_label(f"… və daha {truncated_extra} xəta göstərilmir (ROOT limiti).")
                note.setWordWrap(True)
                card.add(note)

        self._created = list(created)
        if self._created:
            card.add(Divider())
            card.add(body_label("Müvəqqəti şifrələr", size=13))
            warning = muted_label(
                "DİQQƏT: bu siyahı YALNIZ İNDİ göstərilir və pəncərə bağlanandan sonra "
                "BİR DAHA GÖSTƏRİLMƏYƏCƏK — heç yerdə (audit, jurnal) saxlanmır. "
                "İndi kopyalayıb HR-ə ötürün."
            )
            warning.setProperty("variant", "danger-text")
            warning.setWordWrap(True)
            card.add(warning)

            password_table = DataTable(
                [Column("İstifadəçi adı", 220), Column("Müvəqqəti şifrə", mono=True)], theme
            )
            for entry in self._created:
                password_table.add_row(
                    [entry.get("username", ""), mono_label(entry.get("temporary_password", ""))]
                )
            card.add(password_table)

            copy_button = secondary_button("Hamısını Kopyala")
            copy_button.clicked.connect(self._copy_all)
            card.add(copy_button)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.addWidget(stretch())
        close_button = action_button("Bağla")
        close_button.clicked.connect(self.accept)
        buttons_layout.addWidget(close_button)
        card.add(buttons)

    def _copy_all(self) -> None:
        """Mübadilə buferinə `istifadəçi adı<TAB>şifrə` sətirləri.

        Excel-ə birbaşa yapışdırıla bilən format — HR 50 şifrəni əl ilə
        yazmır (bax modul başlığı).
        """
        from PySide6.QtGui import QGuiApplication  # noqa: PLC0415

        text = "\n".join(
            f"{entry.get('username', '')}\t{entry.get('temporary_password', '')}"
            for entry in self._created
        )
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)


def _file_name(path: str) -> str:
    """Yolun yalnız fayl adı — tam yol ekranda sətri daşdırır."""
    return path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if path else ""


__all__ = [
    "CSV_FILE_FILTER",
    "NOT_TRANSFERRED_TEXT",
    "BulkImportResultDialog",
    "BulkOperationsScreen",
    "StoreTemplateApplyDialog",
    "StoreTemplateCaptureDialog",
]
