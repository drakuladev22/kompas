"""Developer Panelinin PySide6 ekranı (bölmə 8, tələb bölmə 6) — Faza 3.11.

Dörd bölmə:

    1. LİSENZİYA   tenant cədvəli (şirkət adı, status-nişanı, qalan gün sayı,
                   son check-in), axtarış və hər sətirdə `[1 Ay Uzat]`.
    2. YAYIM       "Yeni Versiya Yüklə" — fayl seçici (drag-drop), versiya
                   nömrəsi, release notes, "Məcburi Yeniləmədir" və
                   `[Yüklə və Yayımla]`.
    3. ÇÖKMƏLƏR    anonimləşdirilmiş çökmə hesabatları, TEZLİYƏ görə
                   qruplaşdırılmış (bölmə 8).
    4. DƏSTƏK      mərkəzi müraciət inbox-u — müştəri üzrə mövzular və SLA
                   izləməsi (bölmə 8).

3 və 4-cü bölmələr HESABLAMA APARMIR: qruplaşdırma və SLA qərarı
`application/use_cases/developer_console.py`-dədir. Bu ayrılıq həmin
qaydaların Qt olmadan test olunmasına imkan verir — panelin özündə isə
yalnız cədvəl doldurma qalır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ MƏTNLƏR BURADA YAZILMIR
──────────────────────────────────────────────────────────────────────────────
Nişan mətni (`badge_az`), təsdiq sualı (`confirmation_text`, `publish_
confirmation_text`) və "son əlaqə" ifadəsi konsol rejimi ilə PAYLAŞILIR.
GUI-də təkrar yazılsaydı, iki mətn bir gün fərqlənərdi və hansının doğru
olduğu bilinməzdi.

──────────────────────────────────────────────────────────────────────────────
NİYƏ HƏR İKİ ƏMƏLİYYATDA TƏSDİQ MODALI VAR
──────────────────────────────────────────────────────────────────────────────
`[1 Ay Uzat]` PUL alınmasını təsdiqləyən əməliyyatdır və dərhal Supabase-ə
yazılır. Səhv sətirdə bir klik yanlış müştərinin lisenziyasını uzadar, siz
isə bunu yalnız aylar sonra fərq edərsiniz.

`[Yüklə və Yayımla]` daha da geri-dönməzdir: sətir kataloqa düşən kimi BÜTÜN
tenant-lar öz növbəti yoxlamalarında həmin paketi görür (pull modeli). Modal
faylın SHA-256-sını, ölçüsünü və imza vəziyyətini göstərir — yəni "nəyi
yayımlayıram?" sualının cavabı klik anında görünür.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.application.use_cases.developer_console import CrashDashboard, SupportInbox
from src.developer_panel.console import (
    SYNC_NOTE_AZ,
    confirmation_text,
    publish_confirmation_text,
)
from src.domain.value_objects.licensing import LicenseStatus
from src.shared.exceptions import KompasOSError
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from src.infrastructure.licensing.developer_directory import (
        DeveloperTenantDirectory,
        TenantRow,
    )
    from src.infrastructure.updates.publisher import ReleasePublisher

_log = get_logger(__name__)

#: `_run_busy` çağırılan əməliyyatın nəticə tipini olduğu kimi qaytarır.
_T = TypeVar("_T")

COLUMNS = ("Şirkət", "Vəziyyət", "Son əlaqə", "Versiya", "", "")

#: Çökmə panelinin sütunları (bölmə 8 — tezliyə görə qruplaşdırma).
CRASH_COLUMNS = ("Xəta növü", "Təkrar", "Quraşdırma", "Versiya", "Sonuncu")
#: Dəstək inbox-unun sütunları (bölmə 8 — per-tenant threads + SLA).
TICKET_COLUMNS = ("Müştəri", "Mövzu", "İlk cavab", "Həll", "Yaş")

#: Diaqnostika cədvəllərinin hündürlüyü — panel şaquli olaraq şişməsin.
DIAGNOSTIC_TABLE_HEIGHT = 190
#: Göstərilən sətir hədləri. Kəsilmə SƏSSİZ deyil: hər iki bölmənin
#: status sətri "neçəsindən neçəsi göstərilir" sualını cavablandırır.
CRASH_ROW_LIMIT = 12
TICKET_ROW_LIMIT = 12

#: Fayl seçicinin süzgəci — quraşdırıcıdan başqa bir şey yayımlamaq səhvdir.
PACKAGE_FILTER = "Quraşdırıcı (*.exe);;Bütün fayllar (*)"


class PackageDropField(QLineEdit):
    """Fayl yolu sahəsi — Explorer-dən sürüklə-burax dəstəkli.

    Ayrıca sinif olmasının səbəbi: `dragEnterEvent`/`dropEvent` yalnız hadisəni
    QƏBUL EDƏN widget-də işləyir. Bunu pəncərənin özünə qoysaydıq, faylı
    ekranın istənilən yerinə (məsələn tenant cədvəlinin üstünə) buraxmaq da
    "paket seçildi" mənasını verərdi — səhv nəticəyə aparan geniş hədəf.
    """

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 — Qt adı
        if _dropped_path(event) is not None:
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 — Qt adı
        path = _dropped_path(event)
        if path is None:
            event.ignore()
            return
        self.setText(str(path))
        event.acceptProposedAction()


def _dropped_path(event: QDragEnterEvent | QDropEvent) -> Path | None:
    """Sürüklənən TƏK bir yerli fayl (yoxsa `None`)."""
    mime = event.mimeData()
    if not mime.hasUrls():
        return None
    urls = [url for url in mime.urls() if url.isLocalFile()]
    if len(urls) != 1:
        # İki fayl buraxıldıqda hansının nəzərdə tutulduğu bilinmir — səssizcə
        # birincisini götürmək yanlış paketin yayımlanmasına apara bilər.
        return None
    candidate = Path(urls[0].toLocalFile())
    return candidate if candidate.is_file() else None


class DeveloperPanelWindow(QMainWindow):
    """Tenant siyahısı + axtarış + sətir üzrə `[1 Ay Uzat]`."""

    def __init__(
        self,
        directory: DeveloperTenantDirectory,
        *,
        publisher: ReleasePublisher | None = None,
        clock: object = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._directory = directory
        self._publisher = publisher
        self._clock = clock if callable(clock) else (lambda: datetime.now(UTC))
        self._rows: list[TenantRow] = []

        self.setWindowTitle("KompasOS — Developer Paneli (yerli)")
        # Hündürlük yayım bölməsinin varlığından asılıdır; diaqnostika bölmələri
        # isə HƏMİŞƏ var, ona görə hər iki halda əlavə yer ayrılır.
        self.resize(1120, 980 if publisher is not None else 820)

        container = QWidget(self)
        layout = QVBoxLayout(container)

        top = QHBoxLayout()
        self.search_field = QLineEdit(container)
        self.search_field.setPlaceholderText("Şirkət adı və ya e-poçt üzrə axtarış…")
        self.search_field.textChanged.connect(self.reload)
        self.refresh_button = QPushButton("Yenilə", container)
        self.refresh_button.clicked.connect(self.reload)
        top.addWidget(self.search_field, stretch=1)
        top.addWidget(self.refresh_button)
        layout.addLayout(top)

        self.table = QTableWidget(0, len(COLUMNS), container)
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, stretch=1)

        self.status_label = QLabel("", container)
        layout.addWidget(self.status_label)

        # Yayım bölməsi yalnız `publisher` verildikdə QURULUR — mövcud olub
        # deaktiv görünmür (bölmə 3 — "GÖRMƏK = SƏLAHİYYƏTİN OLMASI").
        self.publish_box: QGroupBox | None = None
        if self._publisher is not None:
            self.publish_box = self._build_publish_section(container)
            layout.addWidget(self.publish_box)

        # Çökmə paneli və dəstək inbox-u yan-yana: hər ikisi "nə pisdir?"
        # sualına cavab verir və birlikdə baxılır. Ayrı sətirlərdə olsaydı,
        # panel şaquli olaraq iki dəfə uzanardı və hər ikisini görmək üçün
        # sürüşdürmək lazım gələrdi.
        diagnostics = QHBoxLayout()
        self.crash_box = self._build_crash_section(container)
        self.tickets_box = self._build_tickets_section(container)
        diagnostics.addWidget(self.crash_box, stretch=1)
        diagnostics.addWidget(self.tickets_box, stretch=1)
        layout.addLayout(diagnostics)

        self.setCentralWidget(container)
        self.reload()

    # --------------------------- diaqnostika bölmələri ----------------------- #

    def _build_crash_section(self, parent: QWidget) -> QGroupBox:
        """Anonimləşdirilmiş çökmə paneli — TEZLİYƏ görə qruplaşdırılmış."""
        box = QGroupBox("Çökmə Hesabatları (son 30 gün)", parent)
        inner = QVBoxLayout(box)

        self.crash_table = QTableWidget(0, len(CRASH_COLUMNS), box)
        self.crash_table.setHorizontalHeaderLabels(list(CRASH_COLUMNS))
        self.crash_table.verticalHeader().setVisible(False)
        self.crash_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.crash_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.crash_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.crash_table.setMaximumHeight(DIAGNOSTIC_TABLE_HEIGHT)
        inner.addWidget(self.crash_table)

        self.crash_status = QLabel("", box)
        self.crash_status.setWordWrap(True)
        inner.addWidget(self.crash_status)
        return box

    def _build_tickets_section(self, parent: QWidget) -> QGroupBox:
        """Mərkəzi dəstək inbox-u — SLA vəziyyəti ilə."""
        box = QGroupBox("Dəstək Müraciətləri", parent)
        inner = QVBoxLayout(box)

        self.ticket_table = QTableWidget(0, len(TICKET_COLUMNS), box)
        self.ticket_table.setHorizontalHeaderLabels(list(TICKET_COLUMNS))
        self.ticket_table.verticalHeader().setVisible(False)
        self.ticket_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.ticket_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.ticket_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.ticket_table.setMaximumHeight(DIAGNOSTIC_TABLE_HEIGHT)
        inner.addWidget(self.ticket_table)

        self.ticket_status = QLabel("", box)
        self.ticket_status.setWordWrap(True)
        inner.addWidget(self.ticket_status)
        return box

    def _build_publish_section(self, parent: QWidget) -> QGroupBox:
        """ "Yeni Versiya Yüklə" — fayl, versiya, qeydlər, məcburilik."""
        box = QGroupBox("Yeni Versiya Yüklə", parent)
        form = QFormLayout(box)

        picker = QHBoxLayout()
        self.package_field = PackageDropField(box)
        self.package_field.setPlaceholderText(
            "KompasOS-Setup.exe — faylı bura sürükləyin və ya [Seç…] düyməsini basın"
        )
        self.browse_button = QPushButton("Seç…", box)
        self.browse_button.clicked.connect(self.browse_package)
        picker.addWidget(self.package_field, stretch=1)
        picker.addWidget(self.browse_button)
        form.addRow("Quraşdırıcı:", picker)

        self.version_field = QLineEdit(box)
        self.version_field.setPlaceholderText("1.4.0")
        form.addRow("Versiya nömrəsi:", self.version_field)

        self.notes_field = QPlainTextEdit(box)
        self.notes_field.setPlaceholderText("Bu buraxılışda nə dəyişdi…")
        self.notes_field.setMaximumHeight(90)
        form.addRow("Buraxılış qeydləri:", self.notes_field)

        self.mandatory_checkbox = QCheckBox("Məcburi Yeniləmədir", box)
        self.mandatory_checkbox.setToolTip(
            "İşarələnsə, bu buraxılışdan köhnə bütün quraşdırmalar üçün yenilənmə məcburi sayılır."
        )
        form.addRow("", self.mandatory_checkbox)

        self.publish_button = QPushButton("Yüklə və Yayımla", box)
        self.publish_button.clicked.connect(self.publish)
        form.addRow("", self.publish_button)

        self.publish_status = QLabel("", box)
        self.publish_status.setWordWrap(True)
        form.addRow("", self.publish_status)
        return box

    # ------------------------------- məlumat --------------------------------- #

    def reload(self) -> None:
        """Siyahını Supabase-dən yenidən oxuyur."""
        try:
            self._rows = self._directory.list_tenants(search=self.search_field.text())
        except KompasOSError as exc:
            # Panel hazırlayıcının öz alətidir — xəta gizlədilmir, açıq göstərilir.
            self._rows = []
            self.status_label.setText(f"Xəta: {exc.user_message}")
            _log.error("DEVELOPER_PANEL_LOAD_FAILED", extra={"error": str(exc)})
        else:
            self._fill(self._rows)

        # Diaqnostika bölmələri AYRICA yüklənir: birinin uğursuzluğu digərini
        # və əsas tenant cədvəlini boş qoymamalıdır — panel hazırlayıcının
        # yeganə görmə vasitəsidir və qismən məlumat heç nədən yaxşıdır.
        self.reload_crashes()
        self.reload_tickets()

    def reload_crashes(self) -> None:
        """Çökmələri oxuyur və tezliyə görə qruplaşdırır."""
        try:
            records = self._directory.crash_records()
        except KompasOSError as exc:
            self.crash_table.setRowCount(0)
            self.crash_status.setText(f"Xəta: {exc.user_message}")
            _log.error("DEVELOPER_PANEL_CRASHES_FAILED", extra={"error": str(exc)})
            return

        dashboard = CrashDashboard.from_records(records)
        groups = dashboard.top(CRASH_ROW_LIMIT)
        self.crash_table.setRowCount(len(groups))
        for index, group in enumerate(groups):
            _set_table_cell(
                self.crash_table, index, 0, group.exception_type, bold=group.is_widespread
            )
            _set_table_cell(self.crash_table, index, 1, str(group.occurrences))
            _set_table_cell(
                self.crash_table,
                index,
                2,
                str(group.affected_installations),
                bold=group.is_widespread,
            )
            _set_table_cell(self.crash_table, index, 3, ", ".join(group.app_versions))
            _set_table_cell(self.crash_table, index, 4, _seen_text(group.last_seen, self._clock()))

        widespread = len(dashboard.widespread)
        shown = f"{len(groups)}/{len(dashboard.groups)}" if dashboard.groups else "0"
        self.crash_status.setText(
            f"Cəmi {dashboard.total_crashes} çökmə · {shown} qrup göstərilir · "
            f"bir neçə quraşdırmada təkrarlanan: {widespread}"
        )

    def reload_tickets(self) -> None:
        """Dəstək müraciətlərini oxuyur və SLA vəziyyətini hesablayır."""
        try:
            records = self._directory.support_tickets()
        except KompasOSError as exc:
            self.ticket_table.setRowCount(0)
            self.ticket_status.setText(f"Xəta: {exc.user_message}")
            _log.error("DEVELOPER_PANEL_TICKETS_FAILED", extra={"error": str(exc)})
            return

        inbox = SupportInbox.from_records(records, now=self._clock())
        views = inbox.tickets[:TICKET_ROW_LIMIT]
        self.ticket_table.setRowCount(len(views))
        for index, view in enumerate(views):
            attention = view.needs_attention
            _set_table_cell(self.ticket_table, index, 0, view.record.tenant_name, bold=attention)
            _set_table_cell(self.ticket_table, index, 1, view.record.subject)
            _set_table_cell(self.ticket_table, index, 2, view.response_sla.label_az, bold=attention)
            _set_table_cell(self.ticket_table, index, 3, view.resolution_sla.label_az)
            _set_table_cell(self.ticket_table, index, 4, f"{view.age_hours:.0f} saat")

        self.ticket_status.setText(
            f"Cəmi {len(inbox.tickets)} müraciət · diqqət tələb edən: "
            f"{inbox.attention_count} · ilk cavab gözləyən: "
            f"{len(inbox.awaiting_first_reply)}"
        )

    def _fill(self, rows: Sequence[TenantRow]) -> None:
        now = self._clock()
        self.table.setRowCount(len(rows))
        attention = 0
        for index, row in enumerate(rows):
            needs = row.needs_attention(now)
            attention += int(needs)
            self._set_cell(index, 0, row.tenant_name, highlight=needs)
            self._set_cell(index, 1, row.badge_az(now), highlight=needs)
            self._set_cell(index, 2, _seen_text(row.last_check_in_at, now))
            self._set_cell(index, 3, row.app_version or "—")

            button = QPushButton("1 Ay Uzat", self.table)
            button.clicked.connect(lambda _=False, target=row: self.extend(target))
            self.table.setCellWidget(index, 4, button)

            # Bölmə 8: hər sətirdə TƏK toggle — vəziyyətə görə etiketi dəyişir.
            # İki ayrı düymə (Aktivləşdir + Deaktiv Et) qoyulsaydı, onlardan
            # biri həmişə mənasız olardı və səhv klik riski artardı.
            toggle = QPushButton(_toggle_label(row), self.table)
            toggle.clicked.connect(lambda _=False, target=row: self.toggle_status(target))
            self.table.setCellWidget(index, 5, toggle)

        self.status_label.setText(f"Cəmi: {len(rows)} müştəri · diqqət tələb edən: {attention}")

    def _set_cell(self, row: int, column: int, text: str, *, highlight: bool = False) -> None:
        item = QTableWidgetItem(text)
        if highlight:
            # Rəng deyil, şrift qalınlığı: bölmə 9-dakı dizayn tokenləri
            # (Faza 4) hələ mövcud deyil, sabit rəng isə Dark Mode-da
            # oxunmaz ola bilərdi.
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, column, item)

    # ------------------------------ əməliyyat -------------------------------- #

    def toggle_status(self, row: TenantRow) -> None:
        """`[Aktivləşdir / Deaktiv Et]` — bölmə 8-in vahid kontrol nöqtəsi.

        Söndürmə İKİ mərhələli təsdiq tələb edir, uzatmadan fərqli olaraq:
        uzatma bir müştərinin işini UZADIR, söndürmə isə 21 filialın işini
        DAYANDIRIR. Səbəb sahəsi məcburidir — `LICENSE_INACTIVE` ekranı onu
        müştəriyə göstərir (bölmə 8: ekran "ümumi/qeyri-müəyyən xəta mesajı
        OLMAMALIDIR"), yəni boş səbəb birbaşa müştəri çaşqınlığına çevrilir.
        """
        deactivating = row.status is not LicenseStatus.DEAKTIV
        reason = ""

        if deactivating:
            answer = QMessageBox.warning(
                self,
                "Müştərini deaktiv et",
                f"«{row.tenant_name}» üçün tətbiq TAM BAĞLANACAQ — bütün "
                f"istifadəçilər LICENSE_INACTIVE ekranını görəcək.\n"
                f"Məlumat itmir. Davam edilsin?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer is not QMessageBox.StandardButton.Yes:
                return

            reason, accepted = QInputDialog.getText(
                self, "Deaktivləşdirmə səbəbi", "Səbəb (müştəriyə göstərilir):"
            )
            if not accepted or not reason.strip():
                QMessageBox.information(
                    self, "Ləğv edildi", "Səbəb yazılmadı — heç bir dəyişiklik edilmədi."
                )
                return
        else:
            answer = QMessageBox.question(
                self,
                "Müştərini aktivləşdir",
                f"«{row.tenant_name}» üçün tətbiq dərhal açılacaq. Davam edilsin?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer is not QMessageBox.StandardButton.Yes:
                return

        target = LicenseStatus.DEAKTIV if deactivating else LicenseStatus.AKTIV
        try:
            updated = self._directory.set_status(
                row.tenant_id, target, reason=reason.strip(), now=self._clock()
            )
        except KompasOSError as exc:
            QMessageBox.critical(self, "Əməliyyat alınmadı", exc.user_message)
            _log.error(
                "DEVELOPER_PANEL_STATUS_FAILED",
                extra={"tenant_id": row.tenant_id, "error": str(exc)},
            )
            return

        if updated is None:
            QMessageBox.critical(self, "Tapılmadı", "Müştəri artıq mövcud deyil.")
            return

        QMessageBox.information(
            self,
            "Yeniləndi",
            f"«{updated.tenant_name}» → {updated.status.label_az}.\n{SYNC_NOTE_AZ}",
        )
        self.reload()

    def extend(self, row: TenantRow) -> None:
        """`[1 Ay Uzat]` — təsdiq modalı, sonra Supabase-də yazma."""
        answer = QMessageBox.question(
            self,
            "Lisenziyanı uzat",
            confirmation_text([row]),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return

        try:
            result = self._directory.extend_one_month(row.tenant_id, now=self._clock())
        except KompasOSError as exc:
            QMessageBox.critical(self, "Uzatma alınmadı", exc.user_message)
            _log.error(
                "DEVELOPER_PANEL_EXTEND_FAILED",
                extra={"tenant_id": row.tenant_id, "error": str(exc)},
            )
            return

        suffix = "\nMüştəri yenidən aktivləşdirildi." if result.reactivated else ""
        QMessageBox.information(
            self,
            "Uzadıldı",
            f"«{result.tenant_name}» — yeni bitmə tarixi: "
            f"{result.new_expires_at:%d.%m.%Y}.{suffix}\n\n{SYNC_NOTE_AZ}",
        )
        self.reload()

    # -------------------------------- yayım ---------------------------------- #

    def browse_package(self) -> None:
        """Fayl seçici dialoqu (drag-drop ilə eyni sahəni doldurur)."""
        selected, _ = QFileDialog.getOpenFileName(
            self, "Quraşdırıcını seçin", self.package_field.text(), PACKAGE_FILTER
        )
        if selected:
            self.package_field.setText(selected)

    def publish(self) -> None:
        """`[Yüklə və Yayımla]` — yoxla → təsdiq → Storage + kataloq.

        Yükləmə UI sapında icra olunur (gözləmə kursoru ilə). Bu, adətən pis
        praktikadır, lakin burada şüurlu seçimdir: panel hazırlayıcının öz
        alətidir, əməliyyat ayda bir neçə dəfə olur və ayrı sap + irəliləyiş
        siqnalı qatı bu qazanc üçün əlavə nasazlıq mənbəyi olardı. Ən pis
        nəticə — pəncərənin bir neçə saniyə donmasıdır.
        """
        if self._publisher is None:
            return

        raw_path = self.package_field.text().strip()
        version = self.version_field.text().strip()
        if not raw_path or not version:
            QMessageBox.warning(
                self, "Məlumat çatışmır", "Quraşdırıcı faylı və versiya nömrəsi tələb olunur."
            )
            return

        package = Path(raw_path)
        is_mandatory = self.mandatory_checkbox.isChecked()

        publisher = self._publisher
        inspection = self._run_busy(lambda: publisher.inspect(package))
        if inspection is None:
            return

        answer = QMessageBox.question(
            self,
            "Yeni versiyanı yayımla",
            publish_confirmation_text(version, inspection, is_mandatory=is_mandatory),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return

        result = self._run_busy(
            lambda: publisher.publish(
                package,
                version,
                release_notes=self.notes_field.toPlainText(),
                is_mandatory=is_mandatory,
                inspection=inspection,
            )
        )
        if result is None:
            return

        self.publish_status.setText(
            f"Yayımlandı: {result.version} · {result.storage_path} · {inspection.size_mb} MB"
        )
        QMessageBox.information(
            self,
            "Yayımlandı",
            f"Versiya {result.version} yayımlandı.\n"
            f"Bütün tenant-lar növbəti yoxlamalarında (max 24 saat) onu görəcək.",
        )
        self.package_field.clear()
        self.version_field.clear()
        self.notes_field.clear()
        self.mandatory_checkbox.setChecked(False)

    def _run_busy(self, action: Callable[[], _T]) -> _T | None:
        """Əməliyyatı gözləmə kursoru ilə icra edir; xətanı modalda göstərir.

        `None` = əməliyyat baş tutmadı. Çağıran tərəf bunu yoxlamağa məcburdur
        — belə olmasaydı, uğursuz `inspect()`-dən sonra yayım davam edərdi.
        """
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            return action()
        except KompasOSError as exc:
            QMessageBox.critical(self, "Yayım alınmadı", exc.user_message)
            self.publish_status.setText(f"Xəta: {exc.user_message}")
            _log.error("DEVELOPER_PANEL_PUBLISH_FAILED", extra={"error": str(exc)})
            return None
        finally:
            QApplication.restoreOverrideCursor()


def _toggle_label(row: TenantRow) -> str:
    """Toggle-ın etiketi CARİ vəziyyətin ƏKSİNİ göstərir (bölmə 8).

    `ODENIS_GOZLENILIR` bloklamayan bir vəziyyətdir — tətbiq hələ işləyir,
    ona görə oradakı düymə də "Deaktiv Et" olmalıdır: qrace müddəti bitəndə
    edilən əməliyyat məhz söndürməkdir.
    """
    return "Aktivləşdir" if row.status is LicenseStatus.DEAKTIV else "Deaktiv Et"


def _set_table_cell(
    table: QTableWidget, row: int, column: int, text: str, *, bold: bool = False
) -> None:
    """Yalnız-oxunan hüceyrə. Vurğu RƏNGLƏ deyil, şrift qalınlığı ilə verilir
    (əsas cədvəldəki `_set_cell` ilə eyni səbəb: sabit rəng Dark Mode-da
    oxunmaz ola bilər)."""
    item = QTableWidgetItem(text)
    if bold:
        font = item.font()
        font.setBold(True)
        item.setFont(font)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    table.setItem(row, column, item)


def _seen_text(moment: datetime | None, now: datetime) -> str:
    if moment is None:
        return "heç vaxt"
    days = (now - moment).days
    if days <= 0:
        return "bu gün"
    if days == 1:
        return "dünən"
    return f"{days} gün əvvəl"


def launch(directory: DeveloperTenantDirectory, publisher: ReleasePublisher | None = None) -> int:
    """Paneli müstəqil tətbiq kimi açır."""
    app = QApplication.instance() or QApplication([])
    window = DeveloperPanelWindow(directory, publisher=publisher)
    window.show()
    return int(app.exec())


__all__ = [
    "COLUMNS",
    "PACKAGE_FILTER",
    "DeveloperPanelWindow",
    "PackageDropField",
    "launch",
]
