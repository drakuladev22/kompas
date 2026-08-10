"""Developer Panelinin PySide6 ekranı — Faza 3.11 (spesifikasiya bölmə 8).

Panel hazırlayıcının YERLİ alətidir: internetə host olunmur, `service_role`
açarı ilə birbaşa Supabase-ə qoşulur. Testlər bazasız işləyir — `FakeDirectory`
və `FakePublisher` eyni səthi təqdim edir.

İki ən vacib test:

    test_tesdiq_redd_edilende_hec_ne_deyismir       `[1 Ay Uzat]` PUL alınmasını
                                                    təsdiqləyir — modal ləğv
                                                    edildikdə yazma OLMAMALIDIR.
    test_yayim_tesdiq_redd_edilende_yuklenmir       `[Yüklə və Yayımla]` daha da
                                                    geri-dönməzdir: sətir düşən
                                                    kimi BÜTÜN tenant-lar görür.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from src.domain.value_objects.licensing import LicenseStatus, extend_by_month
from src.domain.value_objects.updates import ReleaseChannel, Version
from src.infrastructure.licensing.developer_directory import ExtensionResult, TenantRow
from src.infrastructure.updates.publisher import (
    PackageInspection,
    PublishError,
    PublishResult,
)
from tests.conftest import requires_qt

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.e2e, pytest.mark.qt]

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def make_row(
    name: str,
    *,
    tenant_id: str,
    status: LicenseStatus = LicenseStatus.AKTIV,
    days: int = 20,
    last_seen_days: int = 0,
) -> TenantRow:
    return TenantRow(
        tenant_id=tenant_id,
        tenant_name=name,
        status=status,
        expires_at=NOW + timedelta(days=days),
        last_check_in_at=NOW - timedelta(days=last_seen_days),
        company_contact_email=f"{name.lower()}@example.az",
        app_version="1.0.0",
    )


class FakeDirectory:
    def __init__(self, rows: list[TenantRow]) -> None:
        self._rows = rows
        self.extended: list[str] = []

    def list_tenants(self, *, search: str = "") -> list[TenantRow]:
        if not search:
            return list(self._rows)
        needle = search.casefold()
        return [row for row in self._rows if needle in row.tenant_name.casefold()]

    def get(self, tenant_id: str) -> TenantRow | None:
        return next((row for row in self._rows if row.tenant_id == tenant_id), None)

    def extend_one_month(self, tenant_id: str, *, now: datetime | None = None) -> ExtensionResult:
        current = self.get(tenant_id)
        assert current is not None
        self.extended.append(tenant_id)
        return ExtensionResult(
            tenant_id=tenant_id,
            tenant_name=current.tenant_name,
            old_expires_at=current.expires_at,
            new_expires_at=extend_by_month(current.expires_at, now=now or NOW),
            reactivated=current.status is not LicenseStatus.AKTIV,
        )

    # Diaqnostika bölmələri (Faza 6) — bu fayl lisenziya/yayım axınlarını
    # yoxlayır, ona görə burada BOŞ qaytarılır. Həmin bölmələrin öz
    # davranışı `tests/unit/test_developer_panel_diagnostics.py`-dədir.
    def crash_records(self, *, days: int = 30, limit: int = 2000) -> list[Any]:
        return []

    def support_tickets(self, *, limit: int = 200) -> list[Any]:
        return []


@pytest.fixture
def directory() -> FakeDirectory:
    return FakeDirectory(
        [
            make_row("Bellona Baku", tenant_id="t-1"),
            make_row("Yatas Crescent", tenant_id="t-2", days=-3),
            make_row("Enza Home", tenant_id="t-3", status=LicenseStatus.DEAKTIV),
        ]
    )


@pytest.fixture
def window(qtbot: Any, directory: FakeDirectory) -> Iterator[Any]:
    from src.developer_panel.ui import DeveloperPanelWindow

    widget = DeveloperPanelWindow(directory, clock=lambda: NOW)  # type: ignore[arg-type]
    qtbot.addWidget(widget)
    yield widget


@requires_qt
def test_cedvel_butun_musterileri_gosterir(window: Any) -> None:
    assert window.table.rowCount() == 3
    assert window.table.item(0, 0).text() == "Bellona Baku"


@requires_qt
def test_qalan_gun_nisanda_gorunur(window: Any) -> None:
    assert window.table.item(0, 1).text() == "20 gün qalıb"


@requires_qt
def test_bitmis_ve_deaktiv_setirler_vurgulanir(window: Any) -> None:
    """Diqqət tələb edən sətirlər qalın şriftlə seçilir."""
    assert not window.table.item(0, 0).font().bold()  # sağlam
    assert window.table.item(1, 0).font().bold()  # müddəti bitib
    assert window.table.item(2, 0).font().bold()  # deaktiv


@requires_qt
def test_axtaris_siyahini_suzur(window: Any) -> None:
    window.search_field.setText("enza")

    assert window.table.rowCount() == 1
    assert window.table.item(0, 0).text() == "Enza Home"


@requires_qt
def test_tesdiq_redd_edilende_hec_ne_deyismir(
    window: Any,
    directory: FakeDirectory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Modal ləğv edilirsə Supabase-ə yazma OLMAMALIDIR."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )

    window.extend(directory.list_tenants()[0])

    assert directory.extended == []


@requires_qt
def test_tesdiqden_sonra_uzatma_icra_olunur(
    window: Any,
    directory: FakeDirectory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))

    window.extend(directory.list_tenants()[0])

    assert directory.extended == ["t-1"]


@requires_qt
def test_setirde_uzatma_duymesi_var(window: Any) -> None:
    button = window.table.cellWidget(0, 4)

    assert button is not None
    assert button.text() == "1 Ay Uzat"


# --------------------------------------------------------------------------- #
# "Yeni Versiya Yüklə" bölməsi
# --------------------------------------------------------------------------- #

DIGEST = "a" * 64


class FakePublisher:
    """`ReleasePublisher` əvəzi — şəbəkə və baza olmadan eyni səth."""

    def __init__(self, *, signed: bool = True, fail: bool = False) -> None:
        self.signed = signed
        self.fail = fail
        self.published: list[tuple[str, str, bool]] = []

    def inspect(self, package: Path) -> PackageInspection:
        return PackageInspection(
            path=package,
            sha256=DIGEST,
            size_bytes=42 * 1024 * 1024,
            is_signed=self.signed,
            publisher_subject="O=Kompas MMC" if self.signed else "",
            signature_error="" if self.signed else "imza yoxdur",
        )

    def publish(
        self,
        package: Path,
        version: str,
        *,
        release_notes: str = "",
        is_mandatory: bool = False,
        inspection: PackageInspection | None = None,
        **_: Any,
    ) -> PublishResult:
        if self.fail:
            raise PublishError("yükləmə alınmadı")
        self.published.append((version, release_notes, is_mandatory))
        return PublishResult(
            version=Version.parse(version),
            channel=ReleaseChannel.STABLE,
            storage_path=f"{version}/KompasOS-Setup.exe",
            sha256=DIGEST,
            size_bytes=42 * 1024 * 1024,
            is_mandatory=is_mandatory,
            published_at=NOW,
        )


@pytest.fixture
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
def publish_window(
    qtbot: Any, directory: FakeDirectory, publisher: FakePublisher, tmp_path: Path
) -> Iterator[Any]:
    from src.developer_panel.ui import DeveloperPanelWindow

    widget = DeveloperPanelWindow(
        directory,  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    qtbot.addWidget(widget)
    package = tmp_path / "KompasOS-Setup.exe"
    package.write_bytes(b"MZ-fake")
    widget._test_package = package  # type: ignore[attr-defined]
    yield widget


def _accept(monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))


@requires_qt
def test_publisher_verilmeyende_bolme_umumiyyetle_yoxdur(window: Any) -> None:
    """ "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" — bölmə boz deyil, MÖVCUD deyil."""
    assert window.publish_box is None


@requires_qt
def test_yayim_bolmesinin_saheleri_var(publish_window: Any) -> None:
    assert publish_window.publish_box is not None
    assert publish_window.publish_box.title() == "Yeni Versiya Yüklə"
    assert publish_window.publish_button.text() == "Yüklə və Yayımla"
    assert publish_window.mandatory_checkbox.text() == "Məcburi Yeniləmədir"


@requires_qt
def test_fayl_veya_versiya_bos_olduqda_yayim_baslamir(
    publish_window: Any, publisher: FakePublisher, monkeypatch: pytest.MonkeyPatch
) -> None:
    _accept(monkeypatch)
    publish_window.version_field.setText("1.4.0")  # fayl seçilməyib

    publish_window.publish()

    assert publisher.published == []


@requires_qt
def test_yayim_tesdiq_redd_edilende_yuklenmir(
    publish_window: Any, publisher: FakePublisher, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )
    publish_window.package_field.setText(str(publish_window._test_package))
    publish_window.version_field.setText("1.4.0")

    publish_window.publish()

    assert publisher.published == []


@requires_qt
def test_tesdiqden_sonra_yayim_icra_olunur(
    publish_window: Any, publisher: FakePublisher, monkeypatch: pytest.MonkeyPatch
) -> None:
    _accept(monkeypatch)
    publish_window.package_field.setText(str(publish_window._test_package))
    publish_window.version_field.setText("1.4.0")
    publish_window.notes_field.setPlainText("Cərimə hesablaması düzəldildi")
    publish_window.mandatory_checkbox.setChecked(True)

    publish_window.publish()

    assert publisher.published == [("1.4.0", "Cərimə hesablaması düzəldildi", True)]


@requires_qt
def test_ugurlu_yayimdan_sonra_saheler_temizlenir(
    publish_window: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Növbəti buraxılış təsadüfən köhnə qeydlərlə yayımlanmasın."""
    _accept(monkeypatch)
    publish_window.package_field.setText(str(publish_window._test_package))
    publish_window.version_field.setText("1.4.0")
    publish_window.mandatory_checkbox.setChecked(True)

    publish_window.publish()

    assert publish_window.version_field.text() == ""
    assert publish_window.package_field.text() == ""
    assert publish_window.mandatory_checkbox.isChecked() is False


@requires_qt
def test_yayim_xetasi_saheleri_temizlemir(
    qtbot: Any, directory: FakeDirectory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uğursuz cəhddən sonra hazırlayıcı hər şeyi yenidən yazmamalıdır."""
    from src.developer_panel.ui import DeveloperPanelWindow

    package = tmp_path / "KompasOS-Setup.exe"
    package.write_bytes(b"MZ-fake")
    widget = DeveloperPanelWindow(
        directory,  # type: ignore[arg-type]
        publisher=FakePublisher(fail=True),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    qtbot.addWidget(widget)
    _accept(monkeypatch)
    widget.package_field.setText(str(package))
    widget.version_field.setText("1.4.0")

    widget.publish()

    assert widget.version_field.text() == "1.4.0"


@requires_qt
def test_faylin_suruklenmesi_sahani_doldurur(publish_window: Any, tmp_path: Path) -> None:
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent

    dropped = tmp_path / "KompasOS-Setup.exe"
    dropped.write_bytes(b"MZ")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(dropped))])
    event = QDropEvent(
        QPointF(0, 0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    publish_window.package_field.dropEvent(event)

    assert publish_window.package_field.text() == str(dropped)


@requires_qt
def test_iki_fayl_suruklendikde_hec_biri_secilmir(publish_window: Any, tmp_path: Path) -> None:
    """Hansının nəzərdə tutulduğu bilinmir — səhv paket yayımlanmasın."""
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent

    first = tmp_path / "a.exe"
    second = tmp_path / "b.exe"
    first.write_bytes(b"MZ")
    second.write_bytes(b"MZ")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(first)), QUrl.fromLocalFile(str(second))])
    event = QDropEvent(
        QPointF(0, 0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    publish_window.package_field.dropEvent(event)

    assert publish_window.package_field.text() == ""
