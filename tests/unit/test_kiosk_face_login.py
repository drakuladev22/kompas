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
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.domain.value_objects.machine_identity import MachineIdentityHash
from tests.conftest import requires_qt

TENANT = uuid.uuid4()
STORE = uuid.uuid4()
#: SEC-01/SEC-05 (dövrə 3) + DEEP-GAP T1 — ARTIQ İKİ yolda işlədilir: PIN
#: handshake-ində VƏ 1:N `identify_for_login()`-də (terminal throttle-ı hər
#: ikisi üçün EYNİ `(tenant_id, machine_key)` sətridir).
MACHINE_KEY = MachineIdentityHash(digest="a" * 64)

#: Sabit "indi" — sahtə saat. Kilid müqayisələri BU ana nisbətən qurulur.
NOW = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)


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
        #: T1 — bloklanmış terminalda kadr ÇƏKİLMƏMƏLİDİR (fail-fast).
        self.captures = 0

    def is_available(self) -> bool:
        return self._available

    def capture(self, *, count: int = 1, gesture: Any = None) -> list[Any]:
        self.captures += 1
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
        "clock": _Clock(),
        "notifier": object(),
        # T1-dən SONRA `identify_for_login` DƏ bura yazır (ƏSL rədd yollarında),
        # ona görə `object()` ARTIQ KİFAYƏT ETMİR — sahtə `.record` tələb edir.
        "security_events": _SecurityEvents(),
        # T1 — 1:N girişin terminal throttle-ı. MƏCBURİ arqumentdir: sükutla
        # "throttle yoxdur" davranışına qayıtmaq QƏSDƏN mümkün deyil.
        "pin_throttle": _PinThrottle(),
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
        tenant_id=TENANT, store_id=STORE, machine_key=MACHINE_KEY, candidates=[first, second]
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
        tenant_id=TENANT, store_id=STORE, machine_key=MACHINE_KEY, candidates=[first, second]
    )

    assert found is None


def test_identification_refuses_when_nobody_is_close_enough() -> None:
    stranger = _Employee("Kənar şəxs")
    use_case = _use_case({stranger.id: 0.95})

    found = use_case.identify_for_login(
        tenant_id=TENANT, store_id=STORE, machine_key=MACHINE_KEY, candidates=[stranger]
    )

    assert found is None


def test_identification_refuses_when_liveness_fails() -> None:
    """Şəkil/video ilə giriş bağlıdır — canlılıq təsdiqlənməlidir."""
    person = _Employee("Rəşad")
    use_case = _use_case({person.id: 0.05}, live=False)

    found = use_case.identify_for_login(
        tenant_id=TENANT, store_id=STORE, machine_key=MACHINE_KEY, candidates=[person]
    )

    assert found is None


def test_identification_is_off_when_the_module_is_disabled() -> None:
    person = _Employee("Rəşad")
    use_case = _use_case({person.id: 0.05}, toggles=_Toggles(enabled=False))

    found = use_case.identify_for_login(
        tenant_id=TENANT, store_id=STORE, machine_key=MACHINE_KEY, candidates=[person]
    )

    assert found is None


def test_login_button_availability_follows_module_scope_and_camera() -> None:
    use_case = _use_case({})
    assert use_case.login_available(tenant_id=TENANT, store_id=STORE) is True

    without_camera = _use_case({}, camera=_Camera(available=False))
    assert without_camera.login_available(tenant_id=TENANT, store_id=STORE) is False

    without_module = _use_case({}, toggles=_Toggles(enabled=False))
    assert without_module.login_available(tenant_id=TENANT, store_id=STORE) is False


# --------------------------------------------------------------------------- #
# 2b — T1: 1:N girişin terminal throttle-ı
# --------------------------------------------------------------------------- #
#
# NİYƏ BU TESTLƏR VAR
# ───────────────────────────────────────────────────────────────────────────
# «Üzlə daxil ol» yolu nə sayğac artırırdı, nə iz buraxırdı: uğursuz cəhd
# sadəcə `None` qaytarırdı. Yəni kamera qarşısında GECƏ BOYU məhdudiyyətsiz
# sınaq mümkün idi və səhəri gün heç bir jurnalda sətir qalmırdı. Aşağıdakı
# testlər həmin iki boşluğu AYRI-AYRI ölçür — biri keçib digəri qırılsa,
# hansının itdiyi dərhal görünür.


def _throttle(*, locked: bool = False, failed_count: int = 1) -> Any:
    from src.domain.value_objects.pin_throttle import TerminalPinThrottle

    return TerminalPinThrottle(
        tenant_id=TENANT,
        machine_key=MACHINE_KEY,
        store_id=STORE,
        failed_count=failed_count,
        window_started_at=NOW - timedelta(minutes=1),
        locked_until=NOW + timedelta(minutes=15) if locked else None,
        updated_at=NOW,
    )


class _Clock:
    def now(self) -> datetime:
        return NOW


class _SecurityEvents:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.rows.append(kwargs)

    def types(self) -> list[str]:
        return [str(row["event_type"]) for row in self.rows]


class _PinThrottle:
    """`PinThrottleRepository` sahtəsi — sayğacı YADDAŞDA saxlayır.

    `record_failure` DB trigger-inin ARİFMETİKASINI təkrarlamır: bu fayldakı
    testlərin mövzusu hədd deyil, ÇAĞIRILIB-ÇAĞIRILMADIĞIDIR. Kilidin YENİ
    yarandığı hal `locks_on` ilə açıq şəkildə qurulur — yəni test hansı
    davranışı ölçdüyünü gizlətmir.
    """

    def __init__(self, *, existing: Any = None, locks_on: int | None = None) -> None:
        self._existing = existing
        self._locks_on = locks_on
        self.failures = 0
        self.read_count = 0

    def get_for_update(self, _tenant: Any, _machine_key: Any) -> Any:
        self.read_count += 1
        return self._existing

    def record_failure(self, _tenant: Any, _machine_key: Any, *, store_id: Any) -> Any:
        self.failures += 1
        locked = self._locks_on is not None and self.failures >= self._locks_on
        return _throttle(locked=locked, failed_count=self.failures)

    def update_last_seen_store(self, _tenant: Any, _machine_key: Any, *, store_id: Any) -> None:
        return None


class _BrokenPinThrottle:
    def get_for_update(self, _tenant: Any, _machine_key: Any) -> Any:
        raise RuntimeError("bağlantı yoxdur")

    def record_failure(self, _tenant: Any, _machine_key: Any, *, store_id: Any) -> Any:
        raise AssertionError("kilid oxuna bilmədikdə buraya çatılmamalıdır")

    def update_last_seen_store(self, _tenant: Any, _machine_key: Any, *, store_id: Any) -> None:
        return None


def test_unrecognised_face_increments_the_terminal_counter_and_leaves_a_trace() -> None:
    """ƏSL uyğunsuzluq: sayğac artır VƏ `security_events` sətri yaranır.

    İkisi bir arada yoxlanılır, çünki qüsurun ÖZÜ də bir arada idi: «kim cəhd
    etdiyi məlum deyil» qərarı jurnalı da, sürət-limitini də özü ilə aparmışdı.
    """
    throttle = _PinThrottle()
    events = _SecurityEvents()
    stranger = _Employee("Kənar şəxs")
    use_case = _use_case({stranger.id: 0.95}, pin_throttle=throttle, security_events=events)

    found = use_case.identify_for_login(
        tenant_id=TENANT, store_id=STORE, machine_key=MACHINE_KEY, candidates=[stranger]
    )

    assert found is None
    assert throttle.failures == 1
    assert events.types() == ["FACE_LOGIN_FAILED"]
    assert events.rows[0]["details"]["reason"] == "NO_MATCH"


def test_ambiguous_match_also_counts_against_the_terminal() -> None:
    """Marja qapısı LİMİTSİZ sınaq sahəsi olmamalıdır.

    Sayılmasaydı, iki işçiyə eyni dərəcədə oxşayan hər kadr pulsuz cəhd
    olardı — halbuki burada biometrik QƏRAR verilib və giriş RƏDD edilib.
    """
    throttle = _PinThrottle()
    events = _SecurityEvents()
    first, second = _Employee("Rəşad"), _Employee("Rəşid")
    use_case = _use_case(
        {first.id: 0.30, second.id: 0.33}, pin_throttle=throttle, security_events=events
    )

    found = use_case.identify_for_login(
        tenant_id=TENANT, store_id=STORE, machine_key=MACHINE_KEY, candidates=[first, second]
    )

    assert found is None
    assert throttle.failures == 1
    assert events.rows[0]["details"]["reason"] == "AMBIGUOUS"


def test_liveness_failure_does_not_lock_the_terminal() -> None:
    """`verify()`-dakı qərarın EYNİSİ: canlılıq uğursuzluğu sayğaca YAZILMIR.

    Zəif işıqda göz qırpması tutulmayan VİCDANLI işçi bütün mağazanın PIN
    girişini bloklaya bilməz — sayğac `store_pin_throttle`-dır, yəni onun
    kilidi PIN yoluna DA təsir edir.
    """
    throttle = _PinThrottle()
    person = _Employee("Rəşad")
    use_case = _use_case({person.id: 0.05}, live=False, pin_throttle=throttle)

    found = use_case.identify_for_login(
        tenant_id=TENANT, store_id=STORE, machine_key=MACHINE_KEY, candidates=[person]
    )

    assert found is None
    assert throttle.failures == 0


def test_store_without_any_enrolled_face_does_not_lock_the_terminal() -> None:
    """Qeydiyyatsız mağaza KONFİQURASİYA halıdır, hücum siqnalı deyil.

    Sayılsaydı, üz modulu açılan ilk gün hər cəhd uğursuz olardı və terminal
    öz-özünü PIN-siz qoyardı.
    """
    throttle = _PinThrottle()
    person = _Employee("Rəşad")
    use_case = _use_case({}, pin_throttle=throttle)

    found = use_case.identify_for_login(
        tenant_id=TENANT, store_id=STORE, machine_key=MACHINE_KEY, candidates=[person]
    )

    assert found is None
    assert throttle.failures == 0


def test_locked_terminal_is_refused_before_the_camera_is_used() -> None:
    """Fail-fast: bloklanmış terminalda kadr ÇƏKİLMİR.

    Kadr çəkilsəydi hücumçu «kamera işləyir» geribildirişi alardı və N profil
    üzərində məsafə hesablaması hər basışda boşa gedərdi.
    """
    from src.application.use_cases.authentication import TerminalLockedError

    camera = _Camera()
    events = _SecurityEvents()
    person = _Employee("Rəşad")
    use_case = _use_case(
        {person.id: 0.05},
        camera=camera,
        security_events=events,
        pin_throttle=_PinThrottle(existing=_throttle(locked=True)),
    )

    with pytest.raises(TerminalLockedError):
        use_case.identify_for_login(
            tenant_id=TENANT, store_id=STORE, machine_key=MACHINE_KEY, candidates=[person]
        )

    assert camera.captures == 0
    assert events.types() == ["FACE_LOGIN_TERMINAL_LOCKED"]


def test_new_lockout_is_recorded_when_the_threshold_is_crossed() -> None:
    """Həddi KEÇƏN cəhd İKİ sətir buraxır: rədd + yeni kilid."""
    throttle = _PinThrottle(locks_on=1)
    events = _SecurityEvents()
    stranger = _Employee("Kənar şəxs")
    use_case = _use_case({stranger.id: 0.95}, pin_throttle=throttle, security_events=events)

    use_case.identify_for_login(
        tenant_id=TENANT, store_id=STORE, machine_key=MACHINE_KEY, candidates=[stranger]
    )

    assert events.types() == ["FACE_LOGIN_FAILED", "FACE_LOGIN_TERMINAL_LOCKED"]
    assert events.rows[1]["details"]["trigger"] == "NEW_LOCKOUT"
    # HANSI SAYĞACIN kilidlədiyi sətirdən OXUNA bilməlidir — əks halda
    # hadisəni araşdıran adam hansı kanalın bağlandığını tapa bilməz.
    #
    # AF-2-DƏN SONRA AÇAR VƏ DƏYƏR DƏYİŞDİ: əvvəl `shared_counter` idi və
    # HƏMİŞƏ `store_pin_throttle` yazırdı, çünki üz rəddləri PIN girişi ilə
    # ORTAQ sayğaca düşürdü — yəni kameraya bir neçə dəfə baxan kənar şəxs
    # BÜTÜN mağazanın PIN girişini dayandıra bilirdi (xidmətdən imtina).
    # İndi açar `counter`-dır və dəyər HƏQİQƏTİ yazır: `face_throttle` portu
    # bağlanmayıbsa (bu sahtədə bağlanmayıb) köhnə ortaq sayğac, bağlanıbsa
    # ayrı `store_face_throttle`.
    assert events.rows[1]["details"]["counter"] == "store_pin_throttle"


def test_face_login_fails_closed_when_the_throttle_cannot_be_read() -> None:
    """FAIL-CLOSED (SEC-06) — throttle oxuna bilmirsə cəhd RƏDD edilir.

    Fail-open variantı bütün qorumanı sükutla söndürərdi. Qiymət isə burada
    PIN axınındakından da AŞAĞIDIR: işçi PIN-lə davam edir.
    """
    from src.application.use_cases.authentication import TerminalThrottleUnavailableError

    camera = _Camera()
    person = _Employee("Rəşad")
    use_case = _use_case({person.id: 0.05}, camera=camera, pin_throttle=_BrokenPinThrottle())

    with pytest.raises(TerminalThrottleUnavailableError):
        use_case.identify_for_login(
            tenant_id=TENANT, store_id=STORE, machine_key=MACHINE_KEY, candidates=[person]
        )

    assert camera.captures == 0


def test_module_gate_is_checked_before_the_throttle_is_read() -> None:
    """Modul söndürülübsə DB-yə heç bir sorğu getmir.

    Sıra tərsinə olsaydı, üz modulu ÜMUMİYYƏTLƏ açılmamış tenant-da hər ekran
    çəkilişi `SELECT ... FOR UPDATE` doğurardı.
    """
    throttle = _PinThrottle()
    person = _Employee("Rəşad")
    use_case = _use_case({person.id: 0.05}, toggles=_Toggles(enabled=False), pin_throttle=throttle)

    assert (
        use_case.identify_for_login(
            tenant_id=TENANT, store_id=STORE, machine_key=MACHINE_KEY, candidates=[person]
        )
        is None
    )
    assert throttle.read_count == 0


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

    controller = KioskController(  # type: ignore[arg-type]
        _Context(), store_id=STORE, machine_key=MACHINE_KEY
    )
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

    controller = KioskController(  # type: ignore[arg-type]
        _Context(), store_id=STORE, machine_key=MACHINE_KEY
    )
    outcome = controller.authenticate_by_face()

    assert outcome.succeeded is True
    assert outcome.employee is employee


def test_authenticate_by_face_forwards_the_terminal_machine_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """DEEP-GAP T1 — `KioskController.authenticate_by_face` ARTIQ öz
    `machine_key`-ini `identify_for_login()`-ə ÖTÜRÜR.

    ƏVVƏL: çağırış `machine_key` VERMİRDİ (`mypy` `call-arg` xətası ilə
    tutdu — imza MƏCBURİ arqumentdir, `None` fallback-ı YOXDUR, bax
    `FaceVerificationUseCase.__init__` başlığı). Nəticədə terminal
    throttle-ı (`(tenant_id, machine_key)`) 1:N üz girişində HEÇ VAXT
    işə düşməzdi — foto/video ilə limitsiz cəhd mümkün olardı.
    """
    from src.presentation.controllers.kiosk import FaceGate, KioskController

    employee = _Employee("Rəşad")
    received: dict[str, Any] = {}

    class _FaceUseCase:
        def identify_for_login(self, **kwargs: Any) -> Any:
            received.update(kwargs)
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

    controller = KioskController(  # type: ignore[arg-type]
        _Context(), store_id=STORE, machine_key=MACHINE_KEY
    )
    controller.authenticate_by_face()

    assert received["machine_key"] == MACHINE_KEY
    assert received["store_id"] == STORE
    assert received["tenant_id"] == TENANT
    assert received["machine_name"], "Terminal adı ötürülməli idi (bloklanma hadisəsi üçün)"


def test_login_trigger_context_exists_for_the_audit_trail() -> None:
    """Giriş qeydi AYRI `trigger_context` daşıyır (miqrasiya 057).

    `STEP_A` təkrar işlədilsəydi, gün ərzində kiosku beş dəfə açan işçi
    davamiyyət hesabatında beş dəfə «işə başlamış» görünərdi.
    """
    from src.domain.value_objects.face_recognition import FaceTriggerContext

    assert FaceTriggerContext.LOGIN.value == "LOGIN"
    assert FaceTriggerContext.LOGIN is not FaceTriggerContext.STEP_A


# --------------------------------------------------------------------------- #
# AF-2 — ÜZ SAYĞACI PIN SAYĞACINDAN AYRILDI
# --------------------------------------------------------------------------- #
#
# Ortaq sayğac dövründə kameranın qarşısına keçən İSTƏNİLƏN adam — mağazanın
# işçisi olmayan kənar şəxs daxil — sayğacı artırırdı və N rəddən sonra BÜTÜN
# mağazanın PIN girişi kilidlənirdi. 1:N-də cəhd edən şəxs heç bir kimlik
# təqdim etmir, yəni «eyni terminalda eyni adam» fərziyyəsi YOXDUR.


def test_a_wired_face_throttle_never_touches_the_pin_counter() -> None:
    """AF-2-nin BÜTÜN mahiyyəti: üz rəddi PIN girişini DAYANDIRMIR.

    Köhnə davranış məhz ƏKSİNİ edirdi — test ona görə hər iki sahtəni ayrıca
    sayır: üz sayğacı artmalı, PIN sayğacına HEÇ TOXUNULMAMALIDIR.
    """
    face_throttle = _PinThrottle()
    pin_throttle = _PinThrottle()
    stranger = _Employee("Kənar şəxs")
    use_case = _use_case(
        {stranger.id: 0.95},
        pin_throttle=pin_throttle,
        face_throttle=face_throttle,
        security_events=_SecurityEvents(),
    )

    use_case.identify_for_login(
        tenant_id=TENANT, store_id=STORE, machine_key=MACHINE_KEY, candidates=[stranger]
    )

    assert face_throttle.failures == 1, "üz rəddi ÖZ sayğacına yazılmalıdır"
    assert pin_throttle.failures == 0, "PIN sayğacı TOXUNULMAMALIDIR (AF-2)"
    assert pin_throttle.read_count == 0, "kilid yoxlaması da üz sayğacından oxumalıdır"


def test_the_event_row_names_the_counter_that_locked_the_terminal() -> None:
    """Hadisə sətri HANSI sayğacın kilidlədiyini YAZIR — təxmin edilmir (AF-5 prinsipi)."""
    events = _SecurityEvents()
    stranger = _Employee("Kənar şəxs")
    use_case = _use_case(
        {stranger.id: 0.95},
        pin_throttle=_PinThrottle(),
        face_throttle=_PinThrottle(locks_on=1),
        security_events=events,
    )

    use_case.identify_for_login(
        tenant_id=TENANT, store_id=STORE, machine_key=MACHINE_KEY, candidates=[stranger]
    )

    assert events.types() == ["FACE_LOGIN_FAILED", "FACE_LOGIN_TERMINAL_LOCKED"]
    assert events.rows[1]["details"]["counter"] == "store_face_throttle"
