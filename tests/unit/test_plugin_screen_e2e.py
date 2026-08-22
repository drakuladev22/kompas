"""`PluginScreen` ↔ `PluginAdminController` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, infra dalğası)
──────────────────────────────────────────────────────────────────────────────
Bu ekranın kontrolleri əvvəllər HEÇ BİR testdə Qt ilə birlikdə sınanmayıb —
`PluginAdminController` yalnız `plugin_management.py`-in domen/tətbiq
testlərində dolayı yoxlanılır. Burada REAL `PluginScreen` + REAL
`PluginAdminController.attach()` qurulur və REAL "Sil" düyməsi, REAL
`ToggleSwitch` kliki, REAL boş-vəziyyət "Plugin Quraşdır" düyməsi sınanır.

`PluginScreen.set_plugins` docstring-i (`group_i.py`) bir keçmiş qüsuru
sənədləşdirir: boş siyahıda `show_empty()` bütün alət zolağını (o cümlədən
yuxarıdakı "Plugin Quraşdır" düyməsini) gizlədirdi və BİRİNCİ plugin heç vaxt
quraşdırıla bilmirdi — `EmptyState`-in öz `primary_clicked`-i məhz bunun üçün
`install_requested`-ə bağlanıb. `test_the_empty_states_own_install_button_
still_opens_the_real_install_flow` bunu REAL kliklə sübut edir.

`PluginAdminController._write`-da `on_retry` naxışı ARTIQ VAR (`ui` sahibi
tərəfindən bu QA dalğası ərzində düzəldilib): uğursuz söndürmə/silmə
`refresh()`-i DƏRHAL çağırmır, əvəzinə `on_retry` düyməsi ilə istifadəçi
təsdiqləyəndə çağırır. `test_a_failed_toggle_shows_a_retry_button_and_does_
not_silently_revert_the_switch` bunu REAL widget üzərində qoruyur.
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from typing import Any, Final

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from src.application.use_cases.plugin_management import InstalledPlugin
from src.infrastructure.plugins.contracts import PluginError, PluginStatus
from src.presentation.controllers.plugin_admin import PluginAdminController
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT: Final = uuid.uuid4()
ACTOR_ID: Final = uuid.uuid4()


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _click(widget: Any, text: str) -> None:
    button = next(b for b in widget.findChildren(QPushButton) if b.text() == text)
    button.click()


class _Actor:
    id = ACTOR_ID


def _plugin(
    *,
    plugin_id: str = "pl-1",
    name: str = "Kassa Genişləndirməsi",
    status: PluginStatus = PluginStatus.APPROVED,
) -> InstalledPlugin:
    return InstalledPlugin(
        plugin_id=plugin_id,
        name=name,
        version="1.2.0",
        publisher="Kompas Trading",
        status=status,
        signature_verified=True,
    )


# --------------------------------------------------------------------------- #
# `PluginManagementUseCase` müqaviləsinin sahtəsi — YERLİ (CLAUDE.md bölmə 6)
# --------------------------------------------------------------------------- #


class _Registry:
    def __init__(self, plugins: list[InstalledPlugin]) -> None:
        self.plugins = list(plugins)
        self.list_error: Exception | None = None
        self.toggle_error: Exception | None = None
        self.remove_error: Exception | None = None
        self.install_error: Exception | None = None
        self.set_enabled_calls: list[tuple[str, bool]] = []
        self.remove_calls: list[str] = []
        self.install_calls: list[Any] = []

    def list_plugins(self, *, tenant_id: Any, actor: Any) -> list[InstalledPlugin]:
        if self.list_error is not None:
            raise self.list_error
        return list(self.plugins)

    def set_enabled(self, *, tenant_id: Any, actor: Any, plugin_id: str, enabled: bool) -> None:
        self.set_enabled_calls.append((plugin_id, enabled))
        if self.toggle_error is not None:
            raise self.toggle_error
        self.plugins = [
            _plugin(
                plugin_id=p.plugin_id,
                name=p.name,
                status=PluginStatus.APPROVED if enabled else PluginStatus.DISABLED,
            )
            if p.plugin_id == plugin_id
            else p
            for p in self.plugins
        ]

    def remove(self, *, tenant_id: Any, actor: Any, plugin_id: str) -> None:
        self.remove_calls.append(plugin_id)
        if self.remove_error is not None:
            raise self.remove_error
        self.plugins = [p for p in self.plugins if p.plugin_id != plugin_id]

    def install(
        self, *, tenant_id: Any, actor: Any, plugin_path: Any, manifest: Any, signature_hex: str
    ) -> Any:
        self.install_calls.append((plugin_path, manifest, signature_hex))
        if self.install_error is not None:
            raise self.install_error
        new = _plugin(plugin_id="pl-new", name=manifest.name, status=PluginStatus.PENDING_APPROVAL)
        self.plugins.append(new)
        return new


class _Session:
    def __init__(self, registry: _Registry) -> None:
        self.tenant_id = TENANT
        self.plugins = registry
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Context:
    def __init__(self, session: _Session) -> None:
        self._session = session
        self.opens = 0

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        self.opens += 1
        yield self._session


def _build(registry: _Registry, theme: Any) -> tuple[Any, _Session]:
    from src.presentation.screens.group_i import PluginScreen

    session = _Session(registry)
    screen = PluginScreen(theme)
    PluginAdminController(_Context(session), _Actor()).attach(screen)  # type: ignore[arg-type]
    return screen, session


def _plugin_cards(screen: Any) -> list[Any]:
    from src.presentation.widgets.primitives import Card

    # `_list_layout`-un SON elementi `addStretch(1)`-dir (bax `PluginScreen.
    # __init__`) — kartlar `insertWidget(count() - 1, ...)` ilə ondan ƏVVƏL
    # yerləşdirilir.
    return [
        w
        for w in (
            screen._list_layout.itemAt(i).widget() for i in range(screen._list_layout.count())
        )
        if isinstance(w, Card)
    ]


# --------------------------------------------------------------------------- #
# 1. Real `ToggleSwitch` kliki — commit edilir, siyahı YENİDƏN oxunur
# --------------------------------------------------------------------------- #


@requires_qt
def test_toggling_a_plugin_via_the_real_switch_commits_and_rereads_the_list(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.widgets.toggle import ToggleSwitch

    registry = _Registry([_plugin(status=PluginStatus.APPROVED)])
    screen, session = _build(registry, theme)
    qtbot.addWidget(screen)

    assert screen._summary.text() == "1 plugin — 1 aktiv"
    toggle = screen.findChild(ToggleSwitch)
    assert toggle is not None and toggle.isChecked()

    qtbot.mouseClick(toggle, Qt.MouseButton.LeftButton)

    assert registry.set_enabled_calls == [("pl-1", False)]
    assert session.commits == 1
    assert screen._summary.text() == "1 plugin — 0 aktiv", "Siyahı REAL olaraq yenidən oxunmalıdır"


# --------------------------------------------------------------------------- #
# 2. Real "Sil" kliki — son plugin silinəndə REAL boş vəziyyət görünür
# --------------------------------------------------------------------------- #


@requires_qt
def test_removing_the_last_plugin_via_the_real_button_shows_the_real_empty_state(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    registry = _Registry([_plugin()])
    screen, session = _build(registry, theme)
    qtbot.addWidget(screen)

    _click(screen, "Sil")

    assert registry.remove_calls == ["pl-1"]
    assert session.commits == 1
    assert screen.switcher().current_state() == "empty"
    assert _plugin_cards(screen) == []


# --------------------------------------------------------------------------- #
# 3. TAPILAN-QÜSUR REQRESSİYASI — boş vəziyyətin ÖZ "Plugin Quraşdır"
#    düyməsi REAL kliklə quraşdırma axınını YENƏ AÇIR
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_empty_states_own_install_button_still_opens_the_real_install_flow(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    """Bax modul başlığı: köhnə qüsur `show_empty()`-in alət zolağını (deməli
    "Plugin Quraşdır" düyməsini) gizlətməsi idi — `EmptyState.primary_clicked`
    məhz bunun üçün ayrıca `install_requested`-ə bağlanıb."""
    from PySide6.QtWidgets import QFileDialog

    registry = _Registry([])  # HEÇ BİR plugin yoxdur — ekran boş vəziyyətdə açılır
    screen, _session = _build(registry, theme)
    qtbot.addWidget(screen)
    assert screen.switcher().current_state() == "empty"

    package = tmp_path / "kassa_ext.py"
    package.write_text("# plugin kodu", encoding="utf-8")
    (tmp_path / "kassa_ext.py.manifest.json").write_text(
        json.dumps(
            {
                "name": "Kassa Genişləndirməsi",
                "version": "1.0.0",
                "publisher": "Kompas Trading",
                "capabilities": ["read_aggregated_metrics"],
                "entry_point": "main.py",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "kassa_ext.py.sig").write_text("deadbeef" * 8, encoding="utf-8")

    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(package), ""))
    )

    # BOŞ VƏZİYYƏTİN ÖZ "Plugin Quraşdır" düyməsinə REAL klik.
    from PySide6.QtWidgets import QLabel

    assert any("Plugin quraşdırılmayıb" in label.text() for label in screen.findChildren(QLabel))
    _click(screen, "Plugin Quraşdır")

    assert len(registry.install_calls) == 1
    assert screen.switcher().current_state() == "content"
    assert screen._summary.text() == "1 plugin — 0 aktiv"  # yeni plugin PENDING_APPROVAL doğulur


# --------------------------------------------------------------------------- #
# 4. Uğursuz açar dəyişimi — REAL "Yenidən Cəhd Et" düyməsi, siyahı SÜKUTLA
#    ƏVƏZ OLUNMUR
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_failed_toggle_shows_a_retry_button_and_does_not_silently_wipe_the_list(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.widgets.toggle import ToggleSwitch

    registry = _Registry([_plugin(), _plugin(plugin_id="pl-2", name="İkinci Plugin")])
    registry.toggle_error = KompasOSError(
        "denied", user_message="Bu plugini söndürmək səlahiyyətiniz yoxdur."
    )
    screen, session = _build(registry, theme)
    qtbot.addWidget(screen)

    toggle = screen.findChildren(ToggleSwitch)[0]
    qtbot.mouseClick(toggle, Qt.MouseButton.LeftButton)  # ÇÖKMƏMƏLİDİR

    assert session.commits == 0
    assert screen.switcher().current_state() == "error"

    # REAL "Yenidən Cəhd Et" kliki `refresh()`-i çağırır — bazadakı HƏQİQİ
    # (dəyişməmiş) vəziyyəti bərpa edir.
    registry.toggle_error = None
    _click(screen, "Yenidən Cəhd Et")

    assert screen.switcher().current_state() == "content"
    assert screen._summary.text() == "2 plugin — 2 aktiv"


# --------------------------------------------------------------------------- #
# 5. Ekstremal giriş — manifestsiz/imzasız/pozulmuş JSON paket ÇÖKMÜR
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_package_without_sidecar_files_shows_a_real_error_without_crashing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QFileDialog

    registry = _Registry([_plugin()])
    screen, _session = _build(registry, theme)
    qtbot.addWidget(screen)

    package = tmp_path / "yalniz_kod.py"
    package.write_text("# heç bir manifest/imza yoxdur", encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(package), ""))
    )

    _click(screen, "Plugin Quraşdır")  # ÇÖKMƏMƏLİDİR

    assert registry.install_calls == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_a_corrupted_manifest_json_shows_a_real_error_without_crashing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QFileDialog

    registry = _Registry([_plugin()])
    screen, _session = _build(registry, theme)
    qtbot.addWidget(screen)

    package = tmp_path / "pozulmus.py"
    package.write_text("# kod", encoding="utf-8")
    (tmp_path / "pozulmus.py.manifest.json").write_text("{ pozulmuş json", encoding="utf-8")
    (tmp_path / "pozulmus.py.sig").write_text("deadbeef", encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(package), ""))
    )

    _click(screen, "Plugin Quraşdır")  # ÇÖKMƏMƏLİDİR

    assert registry.install_calls == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_an_unknown_capability_in_the_manifest_shows_a_real_error_without_crashing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    """Naşir uydurma/köhnəlmiş capability yazsa da — real klik ÇÖKMƏMƏLİDİR."""
    from PySide6.QtWidgets import QFileDialog

    registry = _Registry([_plugin()])
    screen, _session = _build(registry, theme)
    qtbot.addWidget(screen)

    package = tmp_path / "naməlum_capability.py"
    package.write_text("# kod", encoding="utf-8")
    (tmp_path / "naməlum_capability.py.manifest.json").write_text(
        json.dumps(
            {
                "name": "Şübhəli",
                "version": "0.0.1",
                "publisher": "?",
                "capabilities": ["DELETE_EVERYTHING"],
                "entry_point": "main.py",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "naməlum_capability.py.sig").write_text("deadbeef", encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(package), ""))
    )

    _click(screen, "Plugin Quraşdır")  # ÇÖKMƏMƏLİDİR

    assert registry.install_calls == []
    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 6. Siyahı oxunmur — REAL xəta vəziyyəti, ÇÖKMÜR
# --------------------------------------------------------------------------- #


@requires_qt
def test_an_unreadable_plugin_list_shows_a_real_error_state_instead_of_crashing(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    registry = _Registry([])
    registry.list_error = PluginError("db down", user_message="Plugin siyahısı oxuna bilmədi.")
    screen, _session = _build(registry, theme)  # attach() ÇÖKMƏMƏLİDİR
    qtbot.addWidget(screen)

    assert screen.switcher().current_state() == "error"
