"""Kiosk girişi — numpad, «Üzlə daxil ol» və girişin ÖZÜNDƏ üz qapısı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TESTLƏR VAR
──────────────────────────────────────────────────────────────────────────────
Üç ayrı tələb var və üçü də anti-fraud zəncirinə toxunur:

    1. NUMPAD — toxunma ekranı olmayan kiosk PC-də PIN-i daxil etməyin heç bir
       yolu yox idi. Ekranda rəqəm düymələri göründüyü üçün qüsur «yoxdur»
       kimi görünürdü.
    2. ÜZLƏ GİRİŞ — PIN-ə alternativ yol. Ən həssas giriş üsuludur, ona görə
       tanıma (1:N) TƏK BAŞINA kifayət etmir: doğrulama (1:1) da işləməlidir,
       çünki bütün audit izi ondadır.
    3. GİRİŞİN ÖZÜNDƏ ÜZ QAPISI — ən vacibi. Əvvəl qapı yalnız ƏMƏLİYYATDA
       idi: PIN-i başqasına verən işçinin adından ekran AÇILIRDI və həmin adam
       tapşırıqları, xal balansını, cərimə tarixçəsini GÖRÜRDÜ. Sızma «İşə
       Başladım» basılmadan da baş verirdi.

Sahtələr BU FAYLDA yerlidir.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any

import pytest

from tests.conftest import requires_qt

TENANT = uuid.uuid4()
STORE = uuid.uuid4()


# --------------------------------------------------------------------------- #
# 1 — PIN ekranı: numpad və üz düyməsi
# --------------------------------------------------------------------------- #


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.DARK)
    manager.apply(qt_app)
    return manager


def _pin_pad(theme: Any) -> Any:
    from src.presentation.screens.group_a_kiosk import PinPadScreen

    return PinPadScreen(theme, store_name="Bellona 28 May", terminal_name="Kassa-1")


def _press(widget: Any, key: Any) -> None:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    QApplication.sendEvent(
        widget, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    )


@requires_qt
def test_pin_can_be_typed_on_the_numeric_keypad(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    screen = _pin_pad(theme)
    qtbot.addWidget(screen)
    submitted: list[str] = []
    screen.submitted.connect(submitted.append)

    for key in (Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3, Qt.Key.Key_4):
        _press(screen, key)

    assert submitted == ["1234"]


@requires_qt
def test_backspace_deletes_and_escape_clears(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    screen = _pin_pad(theme)
    qtbot.addWidget(screen)
    submitted: list[str] = []
    screen.submitted.connect(submitted.append)

    for key in (Qt.Key.Key_1, Qt.Key.Key_2):
        _press(screen, key)
    _press(screen, Qt.Key.Key_Backspace)
    _press(screen, Qt.Key.Key_Escape)
    for key in (Qt.Key.Key_9, Qt.Key.Key_9, Qt.Key.Key_9, Qt.Key.Key_9):
        _press(screen, key)

    # Silmə və təmizləmə işləməsəydi, PIN «12» ilə başlayardı.
    assert submitted == ["9999"]


@requires_qt
def test_keyboard_input_is_ignored_while_locked(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Bloklanmış ekranda klaviatura da bloklanmalıdır.

    Əks halda numpad bloklamanı YAN KEÇƏRDİ — yəni yeni giriş yolu köhnə
    təhlükəsizlik qaydasını sükutla zəiflədərdi.
    """
    from PySide6.QtCore import Qt

    screen = _pin_pad(theme)
    qtbot.addWidget(screen)
    submitted: list[str] = []
    screen.submitted.connect(submitted.append)
    screen.show_lockout(15)

    for key in (Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3, Qt.Key.Key_4):
        _press(screen, key)

    assert submitted == []


@requires_qt
def test_face_button_is_hidden_until_declared_available(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Kamera/modul yoxdursa düymə GÖRÜNMÜR — sönük qalmır.

    Sönük düymə «niyə işləmir?» sualı yaradır və işçi onu təkrar basır.
    """
    screen = _pin_pad(theme)
    qtbot.addWidget(screen)
    screen.show()

    assert screen.face_button().isVisible() is False
    screen.set_face_login_available(True)
    assert screen.face_button().isVisible() is True


@requires_qt
def test_face_button_emits_its_signal(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    screen = _pin_pad(theme)
    qtbot.addWidget(screen)
    screen.set_face_login_available(True)
    seen: list[int] = []
    screen.face_login_requested.connect(lambda: seen.append(1))

    screen.face_button().click()

    assert seen == [1]


# --------------------------------------------------------------------------- #
# 2 — 1:N tanıma qaydaları
# --------------------------------------------------------------------------- #


class _Scope:
    def covers(self, _store: Any) -> bool:
        return True


class _StoreScope:
    def active_scope(self, _tenant: Any) -> Any:
        return _Scope()


class _Toggles:
    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = enabled

    def is_enabled(self, _tenant: Any, _module: str) -> bool:
        return self._enabled


class _Camera:
    def __init__(self, *, available: bool = True, frames: int = 1) -> None:
        self._available = available
        self._frames = frames

    def is_available(self) -> bool:
        return self._available

    def capture(self, *, count: int = 1, gesture: Any = None) -> list[Any]:
        return [object()] * self._frames


class _Sample:
    def __init__(self, *, live: bool = True) -> None:
        self.has_face = True
        self.liveness_confirmed = live
        self.embedding = object()


class _Matcher:
    """Məsafələri ÖNCƏDƏN verilmiş cədvəldən qaytarır."""

    def __init__(self, distances: list[float], *, live: bool = True) -> None:
        self._distances = list(distances)
        self._live = live

    def extract(self, _frame: Any, *, gesture: Any = None) -> Any:
        return _Sample(live=self._live)

    def distance(self, profile: Any, _candidate: Any) -> float:
        return float(profile)


class _Profiles:
    def __init__(self, distances: dict[Any, float]) -> None:
        self._distances = distances

    def get_profile(self, employee_id: Any) -> Any:
        value = self._distances.get(employee_id)
        if value is None:
            return None

        class _Profile:
            embedding = value

        return _Profile()


class _Employee:
    def __init__(self, name: str) -> None:
        self.id = uuid.uuid4()
        self.full_name = name


def _use_case(distances: dict[Any, float], *, live: bool = True, **overrides: Any) -> Any:
    from src.application.use_cases.face_control import FaceVerificationUseCase

    kwargs: dict[str, Any] = {
        "profiles": _Profiles(distances),
        "verification_log": object(),
        "exemptions": object(),
        "store_scope": _StoreScope(),
        "camera": _Camera(),
        "matcher": _Matcher([], live=live),
        "limits": _Limits(),
        "toggles": _Toggles(),
        "audit": object(),
        "clock": object(),
        "notifier": object(),
    }
    kwargs.update(overrides)
    return FaceVerificationUseCase(**kwargs)


class _Limits:
    """`SystemLimits` portunun sahtəsi — hər açar üçün DEFOLTU qaytarır.

    Dəyərləri burada BƏRKİTMİRİK: testin mövzusu hədd deyil, TANIMA QAYDASIDIR
    (marja, canlılıq, modul). Defolt qaytarmaq həmin qaydaları real ROOT
    dəyərləri ilə yoxlayır.
    """

    def get_int(self, _tenant: Any, _key: str, default: int) -> int:
        return default

    def get_decimal(self, _tenant: Any, _key: str, default: Any) -> Any:
        return default

    def get_str(self, _tenant: Any, _key: str, default: str) -> str:
        return default

    def get_bool(self, _tenant: Any, _key: str, default: bool) -> bool:
        return default


def test_identification_picks_the_closest_enrolled_face() -> None:
    first, second = _Employee("Rəşad"), _Employee("Aysel")
    use_case = _use_case({first.id: 0.10, second.id: 0.60})

    found = use_case.identify_for_login(
        tenant_id=TENANT, store_id=STORE, candidates=[first, second]
    )

    assert found is first


def test_identification_refuses_when_two_faces_are_too_close() -> None:
    """1:N-in ƏSAS riski budur — bənzər iki üzdən biri sükutla seçilməməlidir.

    Nəticə «başqasının adından giriş» olardı, yəni sistemin bütün audit izi
    yanlış adama yazılardı.
    """
    first, second = _Employee("Rəşad"), _Employee("Rəşid")
    use_case = _use_case({first.id: 0.30, second.id: 0.33})

    found = use_case.identify_for_login(
        tenant_id=TENANT, store_id=STORE, candidates=[first, second]
    )

    assert found is None


def test_identification_refuses_when_nobody_is_close_enough() -> None:
    stranger = _Employee("Kənar şəxs")
    use_case = _use_case({stranger.id: 0.95})

    found = use_case.identify_for_login(tenant_id=TENANT, store_id=STORE, candidates=[stranger])

    assert found is None


def test_identification_refuses_when_liveness_fails() -> None:
    """Şəkil/video ilə giriş bağlıdır — canlılıq təsdiqlənməlidir."""
    person = _Employee("Rəşad")
    use_case = _use_case({person.id: 0.05}, live=False)

    found = use_case.identify_for_login(tenant_id=TENANT, store_id=STORE, candidates=[person])

    assert found is None


def test_identification_is_off_when_the_module_is_disabled() -> None:
    person = _Employee("Rəşad")
    use_case = _use_case({person.id: 0.05}, toggles=_Toggles(enabled=False))

    found = use_case.identify_for_login(tenant_id=TENANT, store_id=STORE, candidates=[person])

    assert found is None


def test_login_button_availability_follows_module_scope_and_camera() -> None:
    use_case = _use_case({})
    assert use_case.login_available(tenant_id=TENANT, store_id=STORE) is True

    without_camera = _use_case({}, camera=_Camera(available=False))
    assert without_camera.login_available(tenant_id=TENANT, store_id=STORE) is False

    without_module = _use_case({}, toggles=_Toggles(enabled=False))
    assert without_module.login_available(tenant_id=TENANT, store_id=STORE) is False


# --------------------------------------------------------------------------- #
# 3 — Girişin ÖZÜNDƏ üz qapısı
# --------------------------------------------------------------------------- #


class _GateSession:
    def __init__(self) -> None:
        self.committed = 0

    def commit(self) -> None:
        self.committed += 1


class _GateContext:
    def __init__(self) -> None:
        self.tenant_id = TENANT
        self._session = _GateSession()

    @contextmanager
    def session(self, *, user_id: Any = None):  # type: ignore[no-untyped-def]
        yield self._session


def test_face_login_is_blocked_when_the_gate_refuses(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Tanınma UĞURLU olsa belə, doğrulama rədd edirsə ekran AÇILMIR.

    Tələbin özü budur: «pinkod başqası tərəfindən açılsa face control ilə
    doğrulansın; başqa insandırsa açılmasın». Burada ən pis ssenari
    yoxlanılır — tanıma adamı SƏHVƏN doğru saysa da, 1:1 doğrulama son sözü
    deyir.
    """
    from src.presentation.controllers.kiosk import FaceGate, KioskController

    employee = _Employee("Rəşad")

    class _FaceUseCase:
        def identify_for_login(self, **_kwargs: Any) -> Any:
            return employee

    class _Uow:
        class employees:  # noqa: N801 - sahtə ad məkanı
            @staticmethod
            def find_by_pin_candidates(_tenant: Any, _store: Any) -> list[Any]:
                return [employee]

    class _Session:
        def __init__(self) -> None:
            self.uow = _Uow()
            self.face_verification = _FaceUseCase()

        def commit(self) -> None:
            return None

    class _Context:
        tenant_id = TENANT

        @contextmanager
        def session(self, *, user_id: Any = None):  # type: ignore[no-untyped-def]
            yield _Session()

    monkeypatch.setattr(
        KioskController,
        "_status_for",
        lambda self, session, employee_id: None,
    )
    monkeypatch.setattr(
        KioskController,
        "_face_gate",
        lambda self, emp, ctx: FaceGate(
            allowed=False, message="Üz uyğun gəlmədi.", face={"outcome": "MISMATCH"}
        ),
    )

    controller = KioskController(_Context(), store_id=STORE)  # type: ignore[arg-type]
    outcome = controller.authenticate_by_face()

    assert outcome.succeeded is False
    assert outcome.employee is None
    assert outcome.face["outcome"] == "MISMATCH"


def test_face_login_opens_only_after_the_gate_allows(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.kiosk import FaceGate, KioskController

    employee = _Employee("Rəşad")

    class _FaceUseCase:
        def identify_for_login(self, **_kwargs: Any) -> Any:
            return employee

    class _Uow:
        class employees:  # noqa: N801 - sahtə ad məkanı
            @staticmethod
            def find_by_pin_candidates(_tenant: Any, _store: Any) -> list[Any]:
                return [employee]

    class _Session:
        def __init__(self) -> None:
            self.uow = _Uow()
            self.face_verification = _FaceUseCase()

        def commit(self) -> None:
            return None

    class _Context:
        tenant_id = TENANT

        @contextmanager
        def session(self, *, user_id: Any = None):  # type: ignore[no-untyped-def]
            yield _Session()

    monkeypatch.setattr(KioskController, "_status_for", lambda self, s, e: None)
    monkeypatch.setattr(
        KioskController,
        "_face_gate",
        lambda self, emp, ctx: FaceGate(allowed=True, message="", face={"outcome": "MATCH"}),
    )

    controller = KioskController(_Context(), store_id=STORE)  # type: ignore[arg-type]
    outcome = controller.authenticate_by_face()

    assert outcome.succeeded is True
    assert outcome.employee is employee


def test_login_trigger_context_exists_for_the_audit_trail() -> None:
    """Giriş qeydi AYRI `trigger_context` daşıyır (miqrasiya 057).

    `STEP_A` təkrar işlədilsəydi, gün ərzində kiosku beş dəfə açan işçi
    davamiyyət hesabatında beş dəfə «işə başlamış» görünərdi.
    """
    from src.domain.value_objects.face_recognition import FaceTriggerContext

    assert FaceTriggerContext.LOGIN.value == "LOGIN"
    assert FaceTriggerContext.LOGIN is not FaceTriggerContext.STEP_A
