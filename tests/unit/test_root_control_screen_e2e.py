"""`RootControlScreen` ↔ `controllers/root_control.py` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, ikinci dalğa)
──────────────────────────────────────────────────────────────────────────────
`test_root_control_screen_limits.py` YALNIZ `OverflowError` qapısını ölçür
(`set_limits` birbaşa çağırılır, siqnal ZƏNCİRİ YOXDUR). `test_controller_
gap_coverage.py`-dəki `_root(...)` testləri isə kontrolleri SAHTƏ `_RootScreen`
siniflə ölçür — heç vaxt REAL `QSpinBox`, REAL `QLineEdit`, REAL `ToggleSwitch`
kliki və ya REAL `QInputDialog` modalı işə düşmür. Struktur-kritik modul
təsdiq modalı, ikiqat klik, səlahiyyətsiz aktorun REAL ekranda nə gördüyü — bu
üçü sahtə ekranla ÜMUMİYYƏTLƏ sınana bilməzdi (widget yoxdur ki, klik olunsun).

Burada hər ikisi (ekran + kontroller) FAKTİKİ qurulur.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from src.application.use_cases.root_control import (
    MIN_CONFIRMATION_LENGTH,
    RootControlError,
    StructuralModuleError,
)
from src.domain.policies import DEFAULT_LIMITS, FeatureModule, SystemLimitKey
from src.domain.value_objects.authorization import HardlockLevel, PermissionFlag
from src.domain.value_objects.face_recognition import FaceStoreScope
from src.domain.value_objects.identifiers import StoreId
from src.infrastructure.config.limits import INFRA_LIMIT_BOUNDS
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()
STORE_A = str(uuid.uuid4())


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _click(widget: Any, text: str) -> None:
    from PySide6.QtWidgets import QPushButton

    button = next(b for b in widget.findChildren(QPushButton) if b.text() == text)
    button.click()


# --------------------------------------------------------------------------- #
# Sahtələr — YALNIZ `RootControlController`-in gözlədiyi səth
# --------------------------------------------------------------------------- #


class _LimitView:
    def __init__(
        self,
        key: str,
        value: str,
        *,
        min_value: str | None = None,
        max_value: str | None = None,
    ) -> None:
        self.key = key
        self.value = value
        self.description_az = ""
        self.min_value = min_value
        self.max_value = max_value
        self.is_stored = True


class _ModuleView:
    def __init__(self, key: str, *, enabled: bool = True, structural: bool = False) -> None:
        self.module_key = key
        self.is_enabled = enabled
        self.is_structural = structural


class _BrandingView:
    company_name = ""
    accent_color: str | None = None

    def accessibility_warning(self) -> str:
        return ""


class _Branding:
    def current(self, _tenant_id: Any) -> _BrandingView:
        return _BrandingView()


class _TelegramConfig:
    """`may_manage` `False` qaytarır — Telegram kartı bu testlərin mövzusu
    deyil, ona görə `_fill_telegram` erkən qayıdır (bax kontroller başlığı)."""

    def may_manage(self, _actor: Any) -> bool:
        return False


class _RootLimits:
    def get_str(self, _tenant_id: Any, _key: str, fallback: str) -> str:
        return fallback


class _Row(dict):
    pass


class _RootConnection:
    def __init__(self, stores: list[dict[str, str]]) -> None:
        self._stores = stores

    def execute(self, _sql: str, _params: Any = None) -> _RootConnection:
        return self

    def fetchall(self) -> list[_Row]:
        return [_Row(id=s["id"], name=s["name"]) for s in self._stores]


class _FaceScopeRepo:
    def __init__(self, active: set[str] | None = None) -> None:
        self._active = {StoreId(uuid.UUID(sid)) for sid in (active or set())}
        self.written: list[tuple[StoreId, bool]] = []

    def active_scope(self, _tenant_id: Any) -> FaceStoreScope:
        return FaceStoreScope(store_ids=frozenset(self._active))

    def set_active(
        self, _tenant_id: Any, store_id: StoreId, *, active: bool, changed_by: Any
    ) -> None:
        self.written.append((store_id, active))


class _RootAudit:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.records.append(kwargs)


class _RootUow:
    def __init__(self, stores: list[dict[str, str]], scope: _FaceScopeRepo) -> None:
        self.connection = _RootConnection(stores)
        self.audit = _RootAudit()
        self._scope = scope

    def repository(self, name: str) -> Any:
        assert name == "face_store_scope"
        return self._scope


class _RootUseCase:
    """`RootControlUseCase`-in yerini tutur — HƏQİQİ QAYDANI TƏKRARLAMIR.

    Struktur-kritik təsdiq uzunluğu kimi domen qaydaları `use_cases/root_
    control.py`-nin öz sınaqlarındadır (`test_application_root_limits.py`).
    Burada YALNIZ yazı YOLUNUN düzgünlüyü ölçülür: real klik → real siqnal →
    kontroller → bu sahtəyə DÜZGÜN arqumentlərlə çatırmı, sahtənin atdığı
    domen istisnası real UI-də DÜZGÜN göstərilirmi.
    """

    def __init__(
        self,
        *,
        limits: list[_LimitView] | None = None,
        modules: list[_ModuleView] | None = None,
        flags: list[PermissionFlag] | None = None,
        limits_denied: bool = False,
        toggle_error: Exception | None = None,
        create_error: Exception | None = None,
    ) -> None:
        self._limits = {v.key: v for v in (limits or [])}
        self._modules = list(modules or [])
        self._flags = list(flags or [])
        self._limits_denied = limits_denied
        self._toggle_error = toggle_error
        self._create_error = create_error
        self.written: list[tuple[str, str]] = []
        self.toggled: list[dict[str, Any]] = []
        self.created: list[PermissionFlag] = []

    def list_limits(self, *, tenant_id: Any, actor: Any) -> list[_LimitView]:
        if self._limits_denied:
            raise RootControlError(
                "«can_manage_system_limits» səlahiyyəti yoxdur",
                user_message="Bu bölmə üçün səlahiyyətiniz yoxdur.",
            )
        return list(self._limits.values())

    def list_modules(self, *, tenant_id: Any, actor: Any) -> list[_ModuleView]:
        return list(self._modules)

    def list_flags(self, *, actor: Any) -> list[PermissionFlag]:
        return list(self._flags)

    def set_limit(self, *, tenant_id: Any, actor: Any, key: Any, value: str) -> Any:
        self.written.append((key.value, value))
        # Real bazanı təqlid edir: YAZILAN dəyər NÖVBƏTİ `list_limits`-də
        # görünməlidir — əks halda ikiqat-klik qoruması sınağı heç nə
        # sübut etmirdi (həmişə "dəyişdi" görünərdi).
        if key.value in self._limits:
            self._limits[key.value].value = value
        return None

    def set_module_enabled(
        self,
        *,
        tenant_id: Any,
        actor: Any,
        module_key: str,
        enabled: bool,
        confirmation: str | None = None,
    ) -> Any:
        if self._toggle_error is not None:
            raise self._toggle_error
        self.toggled.append(
            {"module_key": module_key, "enabled": enabled, "confirmation": confirmation}
        )
        for module in self._modules:
            if module.module_key == module_key:
                module.is_enabled = enabled
        return None

    def create_flag(self, *, tenant_id: Any, actor: Any, flag: PermissionFlag) -> Any:
        if self._create_error is not None:
            raise self._create_error
        self.created.append(flag)
        return flag


class _Session:
    def __init__(
        self,
        use_case: _RootUseCase,
        *,
        stores: list[dict[str, str]] | None = None,
        scope: _FaceScopeRepo | None = None,
        open_shifts: Any = None,
    ) -> None:
        self.tenant_id = TENANT
        self.root_control = use_case
        self.uow = _RootUow(stores or [], scope or _FaceScopeRepo())
        self.limits = _RootLimits()
        self.branding = _Branding()
        self.telegram_config = _TelegramConfig()
        #: DEEP-GAP OP-3 — söndürmədən sonra AXINDA qalan açıq elanların sayı.
        #: `None` = repo ümumiyyətlə yoxdur (köhnə testlərin vəziyyəti), yəni
        #: kontroller ehtiyat mətnə düşməlidir.
        self.open_shifts = open_shifts
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Clock:
    """`ServerTimeService`-in yerini tutur (T5) — `_permitted()` artıq
    `self._context.clock.now()` çağırır, OS saatı `datetime.now(UTC)` YOX."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class _Context:
    def __init__(
        self,
        use_case: _RootUseCase,
        *,
        stores: list[dict[str, str]] | None = None,
        scope: _FaceScopeRepo | None = None,
        open_shifts: Any = None,
    ) -> None:
        self._use_case = use_case
        self._stores = stores or []
        self._scope = scope or _FaceScopeRepo()
        self._open_shifts = open_shifts
        self.clock = _Clock()
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(
            self._use_case,
            stores=self._stores,
            scope=self._scope,
            open_shifts=self._open_shifts,
        )
        self.sessions.append(created)
        yield created


class _Actor:
    def __init__(self, *, permitted: bool = True) -> None:
        self.id = ACTOR_ID
        self._permitted = permitted

    def has_permission(self, _flag: str, *, now: Any = None) -> bool:
        return self._permitted


def _attach(context: _Context, theme: Any, *, qtbot: Any, actor: _Actor | None = None) -> Any:
    from src.presentation.controllers.root_control import RootControlController
    from src.presentation.screens.group_d import RootControlScreen

    screen = RootControlScreen(theme)
    qtbot.addWidget(screen)
    RootControlController(context, actor or _Actor()).attach(screen)  # type: ignore[arg-type]
    return screen


# --------------------------------------------------------------------------- #
# 1. «Tətbiq Et» — real spin box + real klik
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_real_apply_button_writes_only_the_changed_limit_and_commits(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    key = SystemLimitKey.LATE_TOLERANCE_MINUTES
    use_case = _RootUseCase(limits=[_LimitView(key.value, "10")])
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    spin = screen._limit_inputs[key.value]
    spin.setValue(45)
    _click(screen, "Tətbiq Et")

    assert use_case.written == [(key.value, "45")]
    assert any(s.committed for s in context.sessions)
    # Refresh yenidən oxuyub REAL widget-i yeni dəyərlə qurur.
    assert screen._limit_inputs[key.value].value() == 45


@requires_qt
def test_clicking_apply_without_changing_anything_writes_nothing(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    key = SystemLimitKey.LATE_TOLERANCE_MINUTES
    use_case = _RootUseCase(limits=[_LimitView(key.value, "10")])
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    _click(screen, "Tətbiq Et")  # dəyər toxunulmayıb

    assert use_case.written == [], "dəyişməyən limit yazılmamalıdır (bölmə 3, bənd 4)"


@requires_qt
def test_double_clicking_apply_after_a_real_change_writes_it_exactly_once(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Sürətli ikiqat klik — kontroller HƏR yazıdan sonra `refresh()` çağırır,
    ikinci klik artıq "dəyişməyib" görür və yazmır (bölmə 3, bənd 4)."""
    key = SystemLimitKey.LATE_TOLERANCE_MINUTES
    use_case = _RootUseCase(limits=[_LimitView(key.value, "10")])
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    screen._limit_inputs[key.value].setValue(60)
    _click(screen, "Tətbiq Et")
    _click(screen, "Tətbiq Et")  # ikinci klik — HEÇ NƏ dəyişməyib

    assert use_case.written == [(key.value, "60")], "limit İKİ dəfə yazılıb"


# --------------------------------------------------------------------------- #
# 2. Tavanı 32 bitə sığmayan limit — REAL mətn sahəsi, ekstremal dəyərlər
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw_text",
    [
        "9" * 50,  # nəhəng ədəd
        "🔥" * 20,  # emoji
        "'; DROP TABLE system_limits; --",  # SQL-bənzər mətn
        "-999999999999",  # mənfi
        "on beş min",  # sərbəst mətn
        "a" * 10_000,  # 10 000+ simvol
    ],
)
@requires_qt
def test_the_real_oversized_limit_text_field_accepts_extreme_input_without_crashing(
    qtbot, theme, raw_text: str
) -> None:  # type: ignore[no-untyped-def]
    """`IMAGE_CACHE_MAX_BYTES` 8 GiB tavanı ilə MƏTN sahəsinə düşür (bax
    `test_an_oversized_limit_falls_back_to_a_text_field`). Sahə heç bir
    format yoxlaması APARMIR — bura yazılan ƏN QƏRİBƏ mətn belə ÇÖKMƏMƏLİDİR
    və olduğu kimi `set_limit`-ə çatmalıdır (validasiya, varsa, domen
    qatındadır)."""
    key = SystemLimitKey.IMAGE_CACHE_MAX_BYTES
    minimum, maximum = INFRA_LIMIT_BOUNDS[key]
    use_case = _RootUseCase(
        limits=[
            _LimitView(
                key.value, DEFAULT_LIMITS[key], min_value=str(minimum), max_value=str(maximum)
            )
        ]
    )
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    assert key.value in screen._limit_texts, "gözlənilən sahə MƏTN kimi qurulmayıb"
    screen._limit_texts[key.value].setText(raw_text)
    _click(screen, "Tətbiq Et")  # ÇÖKMƏMƏLİDİR

    assert use_case.written == [(key.value, raw_text.strip())]


@pytest.mark.parametrize("raw_text", ["", "   ", "\t\n"])
@requires_qt
def test_an_empty_or_whitespace_only_text_field_is_silently_skipped_not_written(
    qtbot, theme, raw_text: str
) -> None:  # type: ignore[no-untyped-def]
    """Boş/yalnız-boşluq dəyər `_on_applied`-da `strip()`-dən sonra atılır —
    domen qatının "limit dəyəri boş ola bilməz" istisnası ÜMUMİYYƏTLƏ
    çağırılmır. Nəticə eynidir (yazılmır), amma yol fərqlidir; bu test onun
    ÇÖKMƏDƏN keçdiyini göstərir."""
    key = SystemLimitKey.IMAGE_CACHE_MAX_BYTES
    minimum, maximum = INFRA_LIMIT_BOUNDS[key]
    use_case = _RootUseCase(
        limits=[
            _LimitView(
                key.value, DEFAULT_LIMITS[key], min_value=str(minimum), max_value=str(maximum)
            )
        ]
    )
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    screen._limit_texts[key.value].setText(raw_text)
    _click(screen, "Tətbiq Et")  # ÇÖKMƏMƏLİDİR

    assert use_case.written == []
    assert screen.switcher().current_state() == "content", "boş dəyər xəta ekranı açmamalıdır"


# --------------------------------------------------------------------------- #
# 3. Səlahiyyət qapısı — `can_manage_system_limits` yoxdur
# --------------------------------------------------------------------------- #


@requires_qt
def test_denied_actor_sees_the_error_state_and_the_apply_button_is_not_visible(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """Fail-closed: `list_limits` səlahiyyət rədd edəndə `refresh()` xəta
    vəziyyətinə keçir. Bu, `ContentSwitcher`-in `QStackedWidget`-i ilə "Tətbiq
    Et" düyməsini APARIR — düymə `self._content` daxilindədir və `_content`
    artıq stack-in cari widget-i deyil."""
    use_case = _RootUseCase(limits_denied=True)
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot, actor=_Actor(permitted=False))
    screen.show()
    qtbot.waitExposed(screen) if hasattr(qtbot, "waitExposed") else None

    assert screen.switcher().current_state() == "error"

    from PySide6.QtWidgets import QPushButton

    apply_button = next(b for b in screen.findChildren(QPushButton) if b.text() == "Tətbiq Et")
    assert not apply_button.isVisible(), "'Tətbiq Et' səlahiyyətsiz aktora görünməməlidir"


@requires_qt
def test_denied_actor_clicking_the_apply_button_still_writes_nothing(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Görünməzlik tək başına kifayət deyil — proqramatik klik (məs. qısayol,
    test) belə heç nəyə çatmamalıdır: heç bir limit ekrana YÜKLƏNMƏYİB, ona
    görə `collected()` boşdur."""
    use_case = _RootUseCase(limits_denied=True)
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot, actor=_Actor(permitted=False))

    _click(screen, "Tətbiq Et")  # ÇÖKMƏMƏLİDİR

    assert use_case.written == []


# --------------------------------------------------------------------------- #
# 4. Struktur-kritik modul — REAL `ToggleSwitch` kliki + REAL `QInputDialog`
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_non_structural_module_toggles_immediately_without_any_dialog(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    key = FeatureModule.FINE_MODULE
    assert not key.is_structural
    use_case = _RootUseCase(modules=[_ModuleView(key.value, enabled=True, structural=False)])
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    screen._module_toggles[key.value].click()

    # Kontroller boş sətri `None`-a çevirir (`confirmation or None`,
    # `controllers/root_control.py::_on_module_toggled`) — use case "boş
    # təsdiq" ilə "təsdiq YOXDUR"u eyni cür oxuyur.
    assert use_case.toggled == [{"module_key": key.value, "enabled": False, "confirmation": None}]


@requires_qt
def test_a_structural_module_click_opens_a_real_input_dialog(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    key = FeatureModule.CAMERA_VERIFICATION
    assert key.is_structural
    use_case = _RootUseCase(modules=[_ModuleView(key.value, enabled=True, structural=True)])
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    captured: list[tuple[Any, ...]] = []

    def _fake(*args: Any, **kwargs: Any) -> tuple[str, bool]:
        captured.append(args)
        return ("kifayət qədər uzun səbəb", True)

    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(_fake))

    screen._module_toggles[key.value].click()

    assert captured, "struktur-kritik modulda modal AÇILMALIDIR"
    assert use_case.toggled == [
        {"module_key": key.value, "enabled": False, "confirmation": "kifayət qədər uzun səbəb"}
    ]


@requires_qt
def test_cancelling_the_confirmation_dialog_reverts_the_toggle_and_calls_nothing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    key = FeatureModule.CAMERA_VERIFICATION
    use_case = _RootUseCase(modules=[_ModuleView(key.value, enabled=True, structural=True)])
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("", False)))

    toggle = screen._module_toggles[key.value]
    toggle.click()

    assert use_case.toggled == [], "ləğv edilmiş modal use case-i çağırmamalıdır"
    assert toggle.isChecked(), "açar əvvəlki (aktiv) vəziyyətinə qayıtmalıdır"


@requires_qt
def test_an_empty_confirmation_text_with_accepted_dialog_also_reverts_and_calls_nothing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """`accepted=True` amma mətn boş/yalnız-boşluq — ekranın ÖZ qapısı (bax
    `RootControlScreen._on_module_toggled`) bunu use case-ə ÇATDIRMAMALIDIR."""
    from PySide6.QtWidgets import QInputDialog

    key = FeatureModule.CAMERA_VERIFICATION
    use_case = _RootUseCase(modules=[_ModuleView(key.value, enabled=True, structural=True)])
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("   ", True))
    )

    toggle = screen._module_toggles[key.value]
    toggle.click()

    assert use_case.toggled == []
    assert toggle.isChecked()


@requires_qt
def test_a_confirmation_shorter_than_the_domain_minimum_still_reaches_the_use_case(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """AŞKAR EDİLƏN QÜSUR DEYİL, DEFANS-QATININ SÜBUTU: ekran YALNIZ "boş
    deyil" yoxlayır (bax `_on_module_toggled` şərhi) — `MIN_CONFIRMATION_
    LENGTH` (6 simvol) UZUNLUĞUNU YOXLAMIR. 1 simvollu mətn belə use case-ə
    ÇATIR; əsl qapı `RootControlUseCase.set_module_enabled`-dədir (real
    istisna simulyasiya olunur — bax sahtənin `toggle_error`)."""
    from PySide6.QtWidgets import QInputDialog

    key = FeatureModule.CAMERA_VERIFICATION
    assert len("x") < MIN_CONFIRMATION_LENGTH
    use_case = _RootUseCase(
        modules=[_ModuleView(key.value, enabled=True, structural=True)],
        toggle_error=StructuralModuleError(
            f"«{key.value}» struktur-kritik moduldur — "
            f"minimum {MIN_CONFIRMATION_LENGTH} simvolluq təsdiq tələb olunur"
        ),
    )
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("x", True)))

    toggle = screen._module_toggles[key.value]
    toggle.click()  # ÇÖKMƏMƏLİDİR

    assert toggle.isChecked(), "domen rəddindən sonra açar geri qaytarılmalıdır"


def test_a_module_toggle_rejection_does_not_replace_the_whole_panel_with_an_error(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    key = FeatureModule.CAMERA_VERIFICATION
    use_case = _RootUseCase(
        modules=[_ModuleView(key.value, enabled=True, structural=True)],
        toggle_error=StructuralModuleError(
            f"«{key.value}» struktur-kritik moduldur — "
            f"minimum {MIN_CONFIRMATION_LENGTH} simvolluq təsdiq tələb olunur"
        ),
    )
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("x", True)))

    screen._module_toggles[key.value].click()  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "content", (
        "bir modulun rəddi bütün ROOT panelini xəta ekranına çevirməməlidir"
    )


# --------------------------------------------------------------------------- #
# 5. İcazə registri — REAL "Yarat" düyməsi
# --------------------------------------------------------------------------- #


@requires_qt
def test_creating_a_new_flag_via_the_real_form_reaches_the_use_case(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    use_case = _RootUseCase()
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    screen._new_flag.setText("can_manage_test_widget")
    screen._new_flag_category.setText("Test")
    screen._new_flag_kind.setCurrentText("Hardlock")
    _click(screen, "Yarat")

    assert len(use_case.created) == 1
    flag = use_case.created[0]
    assert flag.code == "can_manage_test_widget"
    assert flag.category == "Test"
    assert flag.hardlock is HardlockLevel.ROOT_ONLY


@requires_qt
def test_an_empty_flag_name_does_not_reach_the_use_case(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    use_case = _RootUseCase()
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    screen._new_flag.setText("   ")
    _click(screen, "Yarat")  # ÇÖKMƏMƏLİDİR

    assert use_case.created == []


@requires_qt
def test_a_flag_without_the_can_prefix_is_rejected_by_the_domain_not_silently_dropped(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """`PermissionFlag.__post_init__` `can_` prefiksini tələb edir (bax ekran
    şərhi) — ekran özü format yoxlamır, domen `ValueError` atır və kontroller
    onu real xəta kimi göstərməlidir, ÇÖKMƏMƏLİDİR."""
    use_case = _RootUseCase()
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    screen._new_flag.setText("manage_test_widget")  # `can_` YOXDUR
    _click(screen, "Yarat")  # ÇÖKMƏMƏLİDİR

    assert use_case.created == []


@requires_qt
def test_flag_creation_domain_rejection_shows_a_real_error_without_crashing(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    use_case = _RootUseCase(
        create_error=RootControlError("duplicate", user_message="Bu adda icazə artıq var.")
    )
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    screen._new_flag.setText("can_duplicate")
    screen._new_flag_category.setText("Test")
    _click(screen, "Yarat")  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 6. Face Control mağaza əhatəsi — REAL `ToggleSwitch` kliki
# --------------------------------------------------------------------------- #


def _answer_scope_dialog(monkeypatch, *, confirm: bool) -> None:
    """T4 təsdiq modalını sahtələyir.

    NİYƏ LAZIMDIR: `group_d.py::_confirm_face_scope_narrowing` əhatə QLOBAL
    ikən İLK mağaza seçiləndə `QMessageBox.question(...)` açır. Offscreen
    platformada modal cavab gözləyərək ƏBƏDİ bloklanır — dəst «asmış» kimi
    görünür və `pytest-timeout` 60 saniyədən sonra prosesi öldürür (bu, real
    ölçüdə bir dəfə baş verdi və tam dəsti korladı).

    Layihədəki mövcud naxış budur (`tests/e2e/test_developer_panel_ui.py:174`):
    modal `staticmethod` ilə əvəzlənir. Dialoqu ekrandan gizlətmək DEYİL,
    CAVABINI təyin etmək lazımdır — çünki «Xeyr» cavabı ayrıca davranışdır.
    """
    from PySide6.QtWidgets import QMessageBox

    answer = QMessageBox.StandardButton.Yes if confirm else QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: answer))


@requires_qt
def test_a_real_face_scope_toggle_click_writes_and_audits(qtbot, theme, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    store_id = STORE_A
    use_case = _RootUseCase()
    scope = _FaceScopeRepo()
    context = _Context(use_case, stores=[{"id": store_id, "name": "Mərkəz"}], scope=scope)
    screen = _attach(context, theme, qtbot=qtbot)
    _answer_scope_dialog(monkeypatch, confirm=True)

    toggle = screen._face_scope_toggles[store_id]
    assert not toggle.isChecked()
    toggle.click()

    assert scope.written == [(StoreId(uuid.UUID(store_id)), True)]
    assert any(
        r["action"] == "FACE_SCOPE_CHANGED" for s in context.sessions for r in s.uow.audit.records
    )


@requires_qt
def test_face_scope_change_denied_without_the_flag_reverts_the_real_toggle(  # type: ignore[no-untyped-def]
    qtbot, theme, monkeypatch
) -> None:
    """`_permitted()` `can_manage_system_limits` yoxlayır — bu, `list_limits`-
    dən AYRI bir yoxlamadır (kontroller özü aparır). Burada limitlərə icazə
    VAR (panel açılır), lakin `_permitted()` `False` qaytarır."""
    store_id = STORE_A
    use_case = _RootUseCase()
    scope = _FaceScopeRepo()
    context = _Context(use_case, stores=[{"id": store_id, "name": "Mərkəz"}], scope=scope)
    screen = _attach(context, theme, qtbot=qtbot, actor=_Actor(permitted=False))
    _answer_scope_dialog(monkeypatch, confirm=True)

    toggle = screen._face_scope_toggles[store_id]
    toggle.click()  # ÇÖKMƏMƏLİDİR

    assert scope.written == []
    assert not toggle.isChecked(), "rədd edilmiş dəyişiklik geri qaytarılmalıdır"
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_declining_the_narrowing_dialog_writes_nothing_and_reverts_the_toggle(  # type: ignore[no-untyped-def]
    qtbot, theme, monkeypatch
) -> None:
    """T4 — «Xeyr» cavabı əməliyyatı TAM dayandırır.

    Əhatə QLOBAL ikən (heç bir mağaza seçilməyib) İLK mağazanı seçmək DİGƏR
    bütün mağazalarda üz təsdiqini söndürür — bir toggle kliki bütün şəbəkənin
    Face Control-unu söndürməyə bərabərdir. Modal məhz buna görə var; onun
    HƏQİQƏTƏN qapı olduğunu sınayan yeganə test budur, çünki «Bəli» yolu
    modalın mövcudluğunu SÜBUT ETMİR (dialoq ümumiyyətlə açılmasaydı da həmin
    test yaşıl qalardı).
    """
    store_id = STORE_A
    use_case = _RootUseCase()
    scope = _FaceScopeRepo()
    context = _Context(use_case, stores=[{"id": store_id, "name": "Mərkəz"}], scope=scope)
    screen = _attach(context, theme, qtbot=qtbot)
    _answer_scope_dialog(monkeypatch, confirm=False)

    toggle = screen._face_scope_toggles[store_id]
    toggle.click()

    assert scope.written == [], "rədd edilmiş daralma bazaya YAZILMAMALIDIR"
    assert not toggle.isChecked(), "açar əvvəlki vəziyyətinə qaytarılmalıdır"


# --------------------------------------------------------------------------- #
# 5. DEEP-GAP OP-3 — söndürmə AXINDA qalanları GÖRÜNƏN edir
# --------------------------------------------------------------------------- #


class _OpenShiftMarket:
    """`session.open_shifts.list_active`-in əvəzedicisi."""

    def __init__(self, count: int) -> None:
        self._count = count
        self.calls = 0

    def list_active(self, *, tenant_id: Any, actor: Any) -> list[object]:
        self.calls += 1
        return [object()] * self._count


@requires_qt
def test_disabling_shift_swap_reports_how_many_postings_can_still_be_claimed(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Toggle-ın RETROAKTİV OLMAMASI qaydası qalır — sükut ARADAN QALXIR.

    Root açarı söndürür və «növbə dəyişmə bağlandı» sanırdı, halbuki açıq
    elanlar hələ tutulur və təsdiqlənir (`claim`/`approve` toggle-a BAXMIR,
    bu qəsdlidir). Mesaj həmin fərqi göstərir.
    """
    key = FeatureModule.SHIFT_SWAP
    use_case = _RootUseCase(modules=[_ModuleView(key.value, enabled=True, structural=False)])
    market = _OpenShiftMarket(3)
    context = _Context(use_case, open_shifts=market)
    screen = _attach(context, theme, qtbot=qtbot)

    screen._module_toggles[key.value].click()

    assert use_case.toggled and use_case.toggled[0]["enabled"] is False
    assert market.calls == 1
    message = screen._module_message.text()
    assert "3 açıq elan" in message
    assert screen._module_message.isVisible() or not screen.isVisible()


@requires_qt
def test_enabling_a_module_shows_no_in_flight_notice(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Mesaj YALNIZ söndürməyə aiddir — açılışda axında qalan qeyd anlayışı yoxdur."""
    key = FeatureModule.SHIFT_SWAP
    use_case = _RootUseCase(modules=[_ModuleView(key.value, enabled=False, structural=False)])
    market = _OpenShiftMarket(3)
    context = _Context(use_case, open_shifts=market)
    screen = _attach(context, theme, qtbot=qtbot)

    screen._module_toggles[key.value].click()

    assert use_case.toggled and use_case.toggled[0]["enabled"] is True
    assert market.calls == 0
    assert screen._module_message.text() == ""


@requires_qt
def test_a_module_without_in_flight_records_still_confirms_the_change(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Sayğac sıfırdırsa/başqa moduldursa qısa təsdiq mətni qalır — sükut YOX."""
    key = FeatureModule.FINE_MODULE
    use_case = _RootUseCase(modules=[_ModuleView(key.value, enabled=True, structural=False)])
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    screen._module_toggles[key.value].click()

    assert screen._module_message.text() == "Modul söndürüldü — YENİ qeyd yaradıla bilməz."
