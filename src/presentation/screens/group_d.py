"""Qrup D — ERP, infrastruktur, ayarlar və ROOT — Faza 4.2.

Maket: "KompasOS - Qrup D.dc.html", ekranlar 15–20.

    15  ERP / 1C Çox-Server Paneli
    16  Ehtiyat Nüsxə / Bərpa
    17  Sistem Sağlamlığı (Diaqnostika)
    18  Audit Jurnalı
    19  Ayarlar
    20  ROOT İdarə Mərkəzi
"""

from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.presentation.screens.base import Screen
from src.presentation.widgets import metrics
from src.presentation.widgets.buttons import action_button, secondary_button
from src.presentation.widgets.charts import Meter
from src.presentation.widgets.data_table import Column, DataTable
from src.presentation.widgets.forms import FormField
from src.presentation.widgets.layout_utils import clear_layout
from src.presentation.widgets.primitives import (
    Card,
    Chip,
    ChipTone,
    Divider,
    StatusDot,
    body_label,
    mono_label,
    muted_label,
    plain_label,
    stretch,
    title_label,
)
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
    card = Card(padding=18, spacing=10)

    head = QWidget()
    head_layout = QHBoxLayout(head)
    head_layout.setContentsMargins(0, 0, 0, 0)
    head_layout.setSpacing(8)
    head_layout.addWidget(StatusDot(theme.color(tone)))
    head_layout.addWidget(muted_label(title, size=13))
    head_layout.addWidget(stretch())
    card.add(head)

    card.add(title_label(value, size=24))
    card.add(muted_label(caption))
    card.body().addStretch(1)
    return card


# --------------------------------------------------------------------------- #
# 15 — ERP / 1C Çox-Server Paneli
# --------------------------------------------------------------------------- #


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

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(12)
        self._summary = muted_label("")
        toolbar_layout.addWidget(self._summary)
        toolbar_layout.addWidget(stretch())

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
                Column("Server", 200),
                Column("Ünvan", 200, mono=True),
                Column("Mağaza", 140),
                Column("Sinxron", 120, mono=True),
                Column("Vəziyyət"),
            ],
            theme,
        )
        self._table.row_selected.connect(self._on_row)
        self.add(self._table)

        bottom = QWidget()
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(metrics.CARD_SPACING)

        self._mapping = Card(padding=18, spacing=10)
        self._mapping.add(title_label("Mağaza — Server xəritələmə", size=14))
        self._mapping_rows = QVBoxLayout()
        self._mapping_rows.setSpacing(8)
        mapping_holder = QWidget()
        mapping_holder.setLayout(self._mapping_rows)
        self._mapping.add(mapping_holder)
        self._mapping_note = muted_label("")
        self._mapping.add(self._mapping_note)
        bottom_layout.addWidget(self._mapping, 1)

        self._sync = Card(padding=18, spacing=10)
        self._sync.add(title_label("Son sinxronizasiya", size=14))
        self._sync_rows = QVBoxLayout()
        self._sync_rows.setSpacing(8)
        sync_holder = QWidget()
        sync_holder.setLayout(self._sync_rows)
        self._sync.add(sync_holder)
        bottom_layout.addWidget(self._sync, 1)
        self.add(bottom)

        self._server_names: list[str] = []

    def set_servers(self, servers: list[dict[str, str]], *, mapped_stores: int) -> None:
        self._summary.setText(f"{len(servers)} server · {mapped_stores} mağaza xəritələnib")
        self._table.clear()
        self._server_names = [server["name"] for server in servers]

        for server in servers:
            status = server.get("status", "Aktiv")
            self._table.add_row(
                [
                    mono_label(server["name"]),
                    mono_label(server.get("address", ""), muted=True),
                    server.get("stores", ""),
                    mono_label(server.get("latency", "—")),
                    Chip(status, self._STATUS_TONES.get(status, "neutral")),
                ]
            )
        self.show_content()

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
            layout.setSpacing(10)
            layout.addWidget(StatusDot(self.theme.color(tones.get(tone, "--color-success"))))
            layout.addWidget(body_label(name, size=13, wrap=False))
            layout.addWidget(stretch())
            layout.addWidget(mono_label(value))
            self._sync_rows.addWidget(row)


class ServerConnectionWizard(QDialog):
    """ "Yeni Server" sihirbazı — bağlantı testi ilə.

    Signals:
        test_requested: Doldurulmuş sahələr.
        saved: Doldurulmuş sahələr.

    Test NƏTİCƏSİ olmadan yadda saxlamağa icazə verilir, lakin xəbərdarlıq
    göstərilir — offline quraşdırmada (server hələ qoşulmayıb) admin serveri
    əvvəlcədən əlavə edə bilməlidir.
    """

    test_requested = Signal(dict)
    saved = Signal(dict)

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("Yeni 1C Serveri")
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        card = Card(padding=26, spacing=18)
        layout.addWidget(card)

        card.add(title_label("Yeni 1C Serveri", size=20))
        card.add(muted_label("Bağlantı məlumatlarını daxil edin və yoxlayın."))
        card.add(Divider())

        self._name = FormField("Server adı", placeholder="1C-BAKI-03")
        self._host = FormField("Ünvan", placeholder="10.20.1.16:1541")
        self._database = FormField("Baza", placeholder="kompas_prod")
        self._username = FormField("İstifadəçi", placeholder="kompas_sync")
        self._password = FormField("Şifrə", password=True)
        for field in (self._name, self._host, self._database, self._username, self._password):
            card.add(field)

        self._result = plain_label()
        self._result.setVisible(False)
        self._result.setWordWrap(True)
        card.add(self._result)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)

        test = secondary_button("Bağlantını Yoxla")
        test.clicked.connect(lambda: self.test_requested.emit(self.collected()))
        buttons_layout.addWidget(test)
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
        for button in (test, cancel):
            button.setAutoDefault(False)

        # Fokus sırası vizual sıra ilə: beş sahə → yoxla → imtina → saxla.
        fields = (self._name, self._host, self._database, self._username, self._password)
        for previous, following in pairwise(fields):
            QWidget.setTabOrder(previous.input_widget(), following.input_widget())
        QWidget.setTabOrder(self._password.input_widget(), test)
        QWidget.setTabOrder(test, cancel)
        QWidget.setTabOrder(cancel, save)

        self._name.focus_input()

    def collected(self) -> dict[str, str]:
        return {
            "name": self._name.text(),
            "host": self._host.text(),
            "database": self._database.text(),
            "username": self._username.text(),
            "password": self._password.text(),
        }

    def set_test_result(self, *, ok: bool, message: str) -> None:
        token = "--color-success" if ok else "--color-danger"
        self._result.setText(message)
        self._result.setStyleSheet(f"color: {self._theme.color(token)};")
        self._result.setVisible(True)

    def _on_save(self) -> None:
        self._name.clear_error()
        if not self._name.text().strip():
            self._name.set_error("Server adı məcburidir")
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

        self._storage = Card(padding=18, spacing=10)
        self._storage.add(title_label("Saxlama", size=14))
        self._storage_value = title_label("—", size=20)
        self._storage.add(self._storage_value)
        self._storage_meter = Meter(theme)
        self._storage.add(self._storage_meter)
        self._storage_caption = muted_label("")
        self._storage.add(self._storage_caption)
        bottom_layout.addWidget(self._storage, 1)

        schedule = Card(padding=18, spacing=12)
        schedule.add(title_label("Cədvəl", size=14))

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

        card = Card(padding=26, spacing=16)
        layout.addWidget(card)

        card.add(title_label("Bu nöqtəyə bərpa edilsin?", size=20))
        card.add(
            body_label(
                f"{backup_date} tarixli ehtiyat nüsxə bərpa olunacaq. Bu tarixdən "
                "SONRAKI bütün məlumatlar — davamiyyət qeydləri, cərimələr, "
                "tapşırıqlar — İTİRİLƏCƏK.",
                size=14,
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
    """

    recheck_requested = Signal()

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)

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

        self._latency = Card(padding=18, spacing=10)
        self._latency.add(title_label("1C sinxron gecikməsi — server üzrə", size=14))
        self._latency_rows = QVBoxLayout()
        self._latency_rows.setSpacing(8)
        latency_holder = QWidget()
        latency_holder.setLayout(self._latency_rows)
        self._latency.add(latency_holder)
        self.add(self._latency)

        self._alerts = Card(padding=18, spacing=10)
        self._alerts.add(title_label("Aktiv xəbərdarlıqlar", size=14))
        self._alerts_rows = QVBoxLayout()
        self._alerts_rows.setSpacing(10)
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
            layout.setSpacing(10)
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
            layout.setSpacing(10)
            layout.addWidget(StatusDot(self.theme.color(tones.get(tone, "--color-warning"))))
            layout.addWidget(body_label(text, size=13), 1)
            layout.addWidget(mono_label(time_text, muted=True))
            self._alerts_rows.addWidget(row)


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
        self._range.setPlaceholderText("01.08.2026 — 12.08.2026")
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
        self._pagination_layout.setSpacing(6)
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
            button.setFixedWidth(46)
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
    language_selected = Signal(str)
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
        card = Card(padding=20, spacing=14)
        card.add(title_label("Görünüş", size=15))

        options = QWidget()
        options_layout = QHBoxLayout(options)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(10)

        for key, label in self._THEME_OPTIONS:
            button = secondary_button(label)
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, k=key: self.select_theme(k))
            options_layout.addWidget(button)
            self._theme_buttons[key] = button
        options_layout.addStretch(1)
        card.add(options)

        card.add(Divider())
        self._language = QComboBox()
        self._language.setProperty("variant", "form")
        self._language.addItems(["Azərbaycan dili"])
        self._language.currentTextChanged.connect(self.language_selected)
        card.add(FormField("İnterfeys dili", widget=self._language))
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
        card = Card(padding=20, spacing=14)
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
            text_layout.setSpacing(2)
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

    def _build_security(self) -> Card:
        card = Card(padding=20, spacing=14)
        card.add(title_label("Təhlükəsizlik", size=15))

        password_row = QWidget()
        password_layout = QHBoxLayout(password_row)
        password_layout.setContentsMargins(0, 0, 0, 0)
        password_text = QWidget()
        password_text_layout = QVBoxLayout(password_text)
        password_text_layout.setContentsMargins(0, 0, 0, 0)
        password_text_layout.setSpacing(2)
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
        lock_text_layout.setSpacing(2)
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
        sessions_text_layout.setSpacing(2)
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
            "language": self._language.currentText(),
            "notifications": {
                key: toggle.isChecked() for key, toggle in self._notification_toggles.items()
            },
            "lock_timeout": self._lock_timeout.currentText(),
        }


# --------------------------------------------------------------------------- #
# 20 — ROOT İdarə Mərkəzi
# --------------------------------------------------------------------------- #


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
        status_layout.setSpacing(10)
        self._status_dot = StatusDot(theme.color("--color-text-muted"))
        status_layout.addWidget(self._status_dot)
        self._account = body_label("Hesab qoşulmayıb", size=14, wrap=False)
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
        actions_layout.setSpacing(10)
        actions_layout.addWidget(stretch())
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
        self._pending = Card(padding=20, spacing=10)
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
            layout.setSpacing(10)
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

    def __init__(self, theme: ThemeManager, *, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent=parent)
        self._limit_inputs: dict[str, QSpinBox] = {}
        self._limit_texts: dict[str, QLineEdit] = {}
        self._break_inputs: dict[str, QSpinBox] = {}
        self._module_toggles: dict[str, ToggleSwitch] = {}
        self._structural: set[str] = set()

        banner = Card(padding=14, spacing=6)
        banner_row = QWidget()
        banner_layout = QHBoxLayout(banner_row)
        banner_layout.setContentsMargins(0, 0, 0, 0)
        banner_layout.setSpacing(10)
        banner_layout.addWidget(Chip("ROOT rejimi", "danger"))
        banner_layout.addWidget(body_label("Bütün əməliyyatlar audit jurnalına yazılır.", size=13))
        banner_layout.addWidget(stretch())
        apply_button = action_button("Tətbiq Et")
        apply_button.clicked.connect(lambda: self.applied.emit(self.collected()))
        banner_layout.addWidget(apply_button)
        banner.add(banner_row)
        self.add(banner)

        self._limits = Card(padding=20, spacing=14)
        self._limits.add(title_label("Dinamik limitlər", size=15))
        self._limits_rows = QVBoxLayout()
        self._limits_rows.setSpacing(12)
        limits_holder = QWidget()
        limits_holder.setLayout(self._limits_rows)
        self._limits.add(limits_holder)
        self.add(self._limits)

        self.add(self._build_break_card())

        self._modules = Card(padding=20, spacing=14)
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
        card = Card(padding=20, spacing=14)
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

    def _build_registry(self) -> Card:
        card = Card(padding=20, spacing=14)
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
        create_layout.setSpacing(10)

        # Yer tutucu `can_` ilə başlayır, çünki `PermissionFlag` bu prefiksi
        # TƏLƏB EDİR (bax `authorization.PermissionFlag.__post_init__`).
        # Əvvəlki "module.action_name" nümunəsi yaradılan kimi rədd edilirdi.
        self._new_flag = QLineEdit()
        self._new_flag.setPlaceholderText("can_module_action")
        self._new_flag.setProperty("variant", "form")
        create_layout.addWidget(self._new_flag, 1)

        # Kateqoriya `PermissionFlag`-in məcburi sahəsidir və icazə matrisində
        # qruplaşdırma açarıdır — onsuz yeni flag matrisdə yersiz qalardı.
        self._new_flag_category = QLineEdit()
        self._new_flag_category.setPlaceholderText("Kateqoriya")
        self._new_flag_category.setProperty("variant", "form")
        self._new_flag_category.setFixedWidth(170)
        create_layout.addWidget(self._new_flag_category)

        self._new_flag_kind = QComboBox()
        self._new_flag_kind.setProperty("variant", "form")
        self._new_flag_kind.addItems(["Standart", "Hardlock"])
        self._new_flag_kind.setFixedWidth(150)
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

        if isinstance(value, int):
            spin = QSpinBox()
            spin.setProperty("variant", "form")
            spin.setRange(minimum, maximum)
            spin.setValue(value)
            spin.setSuffix(f" {suffix}")
            spin.setFixedWidth(160)
            numbers[key] = spin
            layout.addWidget(spin)
        else:
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
            layout.setSpacing(10)
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
