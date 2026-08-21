"""`PluginPageScreen` ↔ `controllers/plugin_page.py::attach_plugin_page` — REAL Qt e2e.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, ikinci beşlik)
──────────────────────────────────────────────────────────────────────────────
`plugin_page.py` `tests/` daxilində HEÇ YERDƏ adı çəkilmirdi. Bu modul FON
SAPINDA işləyir (`BackgroundTask`) və nəticəsi `succeeded`/`failed` siqnalları
ilə REAL `PluginPageScreen`-i yeniləyir. Burada `InlineExecutor` istifadə
olunur ki, fon işi test sapında SİNXRON icra olunsun (CLAUDE.md bölmə 6 —
"qeyri-sabit test heç bir testdən pisdir"). `PluginSandbox` monkeypatch
edilir — real alt-proses işə salınmır.

XÜSUSİLƏ SINANIR: taymaut, plugin istisna atması, zibil/nəhəng cavab
(`content_rows` MAX_CONTENT_ROWS/MAX_LABEL_CHARS/MAX_VALUE_CHARS həddi),
plugin silinib/söndürülübsə (beş qapının YENİDƏN yoxlanması) — ekran heç
birində donmur/çökmür.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

from src.infrastructure.plugins.contracts import (
    PluginCapability,
    PluginError,
    PluginManifest,
    PluginStatus,
    PluginTimeoutError,
)
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

PLUGIN_ID = "plugin-42"


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _manifest(**overrides: Any) -> PluginManifest:
    defaults: dict[str, Any] = {
        "name": "Satış İdmanı",
        "version": "1.0.0",
        "publisher": "ACME",
        "capabilities": frozenset({PluginCapability.REGISTER_PAGE}),
        "entry_point": "main.py",
        "required_flags": frozenset({"can_view_plugin_pages"}),
    }
    defaults.update(overrides)
    return PluginManifest(**defaults)


def _page(**overrides: Any) -> Any:
    from src.presentation.plugin_surface import PluginPage, plugin_page_key

    defaults: dict[str, Any] = {
        "plugin_id": PLUGIN_ID,
        "plugin_name": "Satış İdmanı",
        "publisher": "ACME",
        "key": plugin_page_key(PLUGIN_ID),
        "title_az": "Satış İdmanı",
        "required_flags": frozenset({"can_view_plugin_pages"}),
        "capabilities": frozenset({PluginCapability.REGISTER_PAGE.value}),
    }
    defaults.update(overrides)
    return PluginPage(**defaults)


class _Record:
    def __init__(
        self,
        *,
        manifest: PluginManifest | None,
        package_path: str = "C:/plugins/acme",
        status: PluginStatus = PluginStatus.APPROVED,
        signature_verified: bool = True,
    ) -> None:
        self.plugin_id = PLUGIN_ID
        self.name = "Satış İdmanı"
        self.publisher = "ACME"
        self.manifest = manifest
        self.package_path = package_path
        self.status = status
        self.signature_verified = signature_verified


class _PluginsRepo:
    def __init__(self, record: _Record | None) -> None:
        self._record = record

    def get(self, _plugin_id: str) -> _Record | None:
        return self._record


class _Uow:
    def __init__(self, record: _Record | None) -> None:
        self._record = record

    def repository(self, name: str) -> Any:
        if name == "plugins":
            return _PluginsRepo(self._record)
        raise NotImplementedError(name)


class _Session:
    def __init__(self, record: _Record | None) -> None:
        self.uow = _Uow(record)


class _InfrastructureLimits:
    def float_of(self, _key: Any) -> float:
        return 5.0


class _Context:
    def __init__(self, record: _Record | None) -> None:
        self._record = record

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        yield _Session(self._record)

    def infrastructure_limits(self) -> _InfrastructureLimits:
        return _InfrastructureLimits()


class _FakeSandbox:
    """`PluginSandbox`-un yerini tutur — real alt-proses İŞLƏMİR."""

    behavior: Any = None  # test-lər arası paylaşılan callable — `monkeypatch` təyin edir

    def __init__(self, *, manifest: Any, plugin_path: Any, policy: Any) -> None:
        self.manifest = manifest
        self.plugin_path = plugin_path
        self.policy = policy

    def invoke(self, request: Any) -> Any:
        return type(self).behavior(request)


@pytest.fixture(autouse=True)
def _patch_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.infrastructure.plugins import sandbox as sandbox_module

    monkeypatch.setattr(sandbox_module, "PluginSandbox", _FakeSandbox)


def _attach(screen: Any, *, context: Any, page: Any) -> None:
    from src.presentation.background_task import InlineExecutor
    from src.presentation.controllers.plugin_page import attach_plugin_page

    attach_plugin_page(screen, page=page, context=context, executor=InlineExecutor())


def _row_texts(screen: Any) -> list[str]:
    from PySide6.QtWidgets import QLabel

    return [label.text() for label in screen.findChildren(QLabel)]


# --------------------------------------------------------------------------- #
# 1. Uğurlu cavab — real ekranda REAL sətirlər
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_successful_response_renders_metadata_and_content_rows(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.infrastructure.plugins.contracts import PluginResponse
    from src.presentation.screens.group_i import PluginPageScreen

    _FakeSandbox.behavior = lambda _request: PluginResponse(
        ok=True, data={"Bu ayın satışı": "12 450 AZN"}
    )
    record = _Record(manifest=_manifest())
    context = _Context(record)
    screen = PluginPageScreen(theme, plugin_name="Satış İdmanı", publisher="ACME")
    qtbot.addWidget(screen)

    _attach(screen, context=context, page=_page())  # ÇÖKMƏMƏLİDİR, DONMAMALIDIR

    texts = _row_texts(screen)
    assert any("12 450 AZN" in text for text in texts)
    assert screen.section_errors() == ()


@requires_qt
def test_an_empty_response_shows_the_empty_text_not_a_blank_screen(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.infrastructure.plugins.contracts import PluginResponse
    from src.presentation.controllers.plugin_page import EMPTY_TEXT
    from src.presentation.screens.group_i import PluginPageScreen

    _FakeSandbox.behavior = lambda _request: PluginResponse(ok=True, data=None)
    context = _Context(_Record(manifest=_manifest()))
    screen = PluginPageScreen(theme, plugin_name="Satış İdmanı", publisher="ACME")
    qtbot.addWidget(screen)

    _attach(screen, context=context, page=_page())

    assert EMPTY_TEXT in _row_texts(screen)


# --------------------------------------------------------------------------- #
# 2. Taymaut, plugin istisnası, gözlənilməz istisna — DONMUR, ÇÖKMÜR
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_timeout_shows_the_configured_seconds_and_a_section_error(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_i import PluginPageScreen

    def _timeout(_request: Any) -> Any:
        raise PluginTimeoutError("timed out")

    _FakeSandbox.behavior = _timeout
    context = _Context(_Record(manifest=_manifest()))
    screen = PluginPageScreen(theme, plugin_name="Satış İdmanı", publisher="ACME")
    qtbot.addWidget(screen)

    _attach(screen, context=context, page=_page())  # ÇÖKMƏMƏLİDİR

    texts = _row_texts(screen)
    assert any("5 saniyə" in text for text in texts)
    assert screen.section_errors() == ("Plugin məzmunu",)


@requires_qt
def test_a_plugin_error_shows_its_own_user_message(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_i import PluginPageScreen

    def _fail(_request: Any) -> Any:
        raise PluginError("interpreter missing", user_message="Plugin interpretatoru tapılmadı.")

    _FakeSandbox.behavior = _fail
    context = _Context(_Record(manifest=_manifest()))
    screen = PluginPageScreen(theme, plugin_name="Satış İdmanı", publisher="ACME")
    qtbot.addWidget(screen)

    _attach(screen, context=context, page=_page())  # ÇÖKMƏMƏLİDİR

    assert "Plugin interpretatoru tapılmadı." in _row_texts(screen)


@requires_qt
def test_an_unwrapped_exception_from_the_sandbox_falls_back_to_the_generic_message(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """`sandbox.invoke()` HƏR HALDA `PluginError` atmaya bilər (proqramlaşdırma
    xətası, `TypeError` və s.) — `_show_failure`-in `isinstance` qolu bunu tutur."""
    from src.presentation.screens.group_i import PluginPageScreen

    def _boom(_request: Any) -> Any:
        raise TypeError("gözlənilməz daxili xəta")

    _FakeSandbox.behavior = _boom
    context = _Context(_Record(manifest=_manifest()))
    screen = PluginPageScreen(theme, plugin_name="Satış İdmanı", publisher="ACME")
    qtbot.addWidget(screen)

    _attach(screen, context=context, page=_page())  # ÇÖKMƏMƏLİDİR

    texts = _row_texts(screen)
    assert any("məzmunu alınmadı" in text for text in texts)
    assert screen.section_errors() == ("Plugin məzmunu",)


@requires_qt
def test_a_not_ok_response_shows_the_publisher_facing_message(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Sandbox "uğursuz" işarələyib (yararsız JSON) — texniki mətn İSTİFADƏÇİYƏ getmir."""
    from src.infrastructure.plugins.contracts import PluginResponse
    from src.presentation.screens.group_i import PluginPageScreen

    _FakeSandbox.behavior = lambda _request: PluginResponse(ok=False, error="stack trace ...")
    context = _Context(_Record(manifest=_manifest()))
    screen = PluginPageScreen(theme, plugin_name="Satış İdmanı", publisher="ACME")
    qtbot.addWidget(screen)

    _attach(screen, context=context, page=_page())  # ÇÖKMƏMƏLİDİR

    texts = _row_texts(screen)
    assert not any("stack trace" in text for text in texts)
    assert any("Naşirin təqdim etdiyi" in text for text in texts)


# --------------------------------------------------------------------------- #
# 3. Zibil/nəhəng cavab — `content_rows()` HƏDDİ REAL ekranda
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_huge_response_is_truncated_to_forty_rows_with_a_visible_notice(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.infrastructure.plugins.contracts import PluginResponse
    from src.presentation.screens.group_i import PluginPageScreen

    data = {f"sahə-{i:03d}": str(i) for i in range(100)}
    _FakeSandbox.behavior = lambda _request: PluginResponse(ok=True, data=data)
    context = _Context(_Record(manifest=_manifest()))
    screen = PluginPageScreen(theme, plugin_name="Satış İdmanı", publisher="ACME")
    qtbot.addWidget(screen)

    _attach(screen, context=context, page=_page())  # ÇÖKMƏMƏLİDİR, DONMAMALIDIR

    texts = _row_texts(screen)
    assert any("ilk 40 sahəsi" in text for text in texts)
    assert any("60 daha" in text for text in texts)


@requires_qt
def test_an_extremely_long_value_and_control_characters_do_not_break_the_row(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`_as_text` sətir sonlarını boşluğa çevirir, uzunluğu kəsir — SQL-bənzər mətn də daxil."""
    from src.infrastructure.plugins.contracts import PluginResponse
    from src.presentation.screens.group_i import PluginPageScreen

    hostile_value = "'; DROP TABLE plugins; --\n\n" + "🔥" * 50 + "A" * 10_000
    _FakeSandbox.behavior = lambda _request: PluginResponse(ok=True, data={"nəticə": hostile_value})
    context = _Context(_Record(manifest=_manifest()))
    screen = PluginPageScreen(theme, plugin_name="Satış İdmanı", publisher="ACME")
    qtbot.addWidget(screen)

    _attach(screen, context=context, page=_page())  # ÇÖKMƏMƏLİDİR

    texts = _row_texts(screen)
    matched = [text for text in texts if text.startswith("'; DROP TABLE")]
    assert len(matched) == 1
    assert len(matched[0]) <= 400
    assert matched[0].endswith("…")
    assert "\n" not in matched[0]


# --------------------------------------------------------------------------- #
# 4. Beş qapı yenidən yoxlanır — plugin bu arada söndürülüb/silinib
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_disabled_plugin_is_denied_even_though_the_menu_still_shows_the_page(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """Panel saatlarla açıq qala bilər — Root plugin-i bu müddətdə söndürə bilər (modul başlığı)."""
    from src.presentation.screens.group_i import PluginPageScreen

    _FakeSandbox.behavior = lambda _request: pytest.fail("sandbox ÇAĞIRILMAMALI idi")
    record = _Record(manifest=_manifest(), status=PluginStatus.DISABLED)
    context = _Context(record)
    screen = PluginPageScreen(theme, plugin_name="Satış İdmanı", publisher="ACME")
    qtbot.addWidget(screen)

    _attach(screen, context=context, page=_page())  # ÇÖKMƏMƏLİDİR

    assert any("aktiv deyil" in text for text in _row_texts(screen))


@requires_qt
def test_a_deleted_plugin_record_shows_a_reinstall_message(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_i import PluginPageScreen

    _FakeSandbox.behavior = lambda _request: pytest.fail("sandbox ÇAĞIRILMAMALI idi")
    context = _Context(None)  # sətir bazada YOXDUR
    screen = PluginPageScreen(theme, plugin_name="Satış İdmanı", publisher="ACME")
    qtbot.addWidget(screen)

    _attach(screen, context=context, page=_page())  # ÇÖKMƏMƏLİDİR

    assert any("quraşdırılmayıb" in text for text in _row_texts(screen))


@requires_qt
def test_a_missing_package_path_fails_closed(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_i import PluginPageScreen

    _FakeSandbox.behavior = lambda _request: pytest.fail("sandbox ÇAĞIRILMAMALI idi")
    record = _Record(manifest=_manifest(), package_path="   ")
    context = _Context(record)
    screen = PluginPageScreen(theme, plugin_name="Satış İdmanı", publisher="ACME")
    qtbot.addWidget(screen)

    _attach(screen, context=context, page=_page())  # ÇÖKMƏMƏLİDİR

    assert any("yenidən quraşdırın" in text for text in _row_texts(screen))
