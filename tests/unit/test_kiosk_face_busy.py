"""UX-1 — kiosk «Üzlə daxil ol» düyməsi ekranı DONDURMUR.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL VAR
──────────────────────────────────────────────────────────────────────────────
Kamera çəkilişi + 1:N tanıma + 1:1 doğrulama saniyələr çəkir. Kiosk yolunda
heç bir göstərici yox idi: işçi düyməni basırdı, ekran cavabsız qalırdı və o,
düyməni TƏKRAR basırdı — ikinci çəkiliş növbəyə düşürdü. İlk düzəliş (UX-1)
kioska da panel yolundakı ilə EYNİ naxışı gətirdi (`set_busy` + `flush_ui`) —
lakin sonradan məlum oldu ki, həmin naxışın ÖZÜ yarımçıqdır (aşağıya bax).

İlk bölmə ekranın ÖZ müqavilələrini ölçür: məşğul vəziyyətdə klaviatura və üz
düyməsi söndürülür, iş bitəndə — uğurlu VƏ uğursuz halda — yenidən açılır.

──────────────────────────────────────────────────────────────────────────────
İKİNCİ BÖLMƏ — DÖVRƏ 5 TAPINTISI: «BUSY GÖRÜNTÜSÜ» ≠ FON İŞİ
──────────────────────────────────────────────────────────────────────────────
Yuxarıdakı ilk düzəliş (UX-1) yalnız `set_busy(True)` + `flush_ui()` qoyub
"Yoxlanılır…" görüntüsünü ÇƏKDİRİRDİ — `authenticate_by_face()` ÖZÜ hələ GUI
sapında icra olunurdu, yəni kiosk pəncərəsi bu müddət ərzində HƏQİQƏTƏN
donurdu (Windows üçün "cavab vermir"). Aşağıdakı testlər `app.py::start_kiosk`
daxilindəki `on_face_login` closure-unun `run_job` ilə FON SAPINA köçdüyünü
ölçür — naxış `test_face_login_background.py`-dəki (panel yolu) EYNİSİdir.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


def _pin_pad(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_a_kiosk import PinPadScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)
    return PinPadScreen(theme, store_name="Mağaza 1", terminal_name="Terminal A")


@requires_qt
def test_busy_disables_the_keypad_and_the_face_button(qt_app) -> None:  # type: ignore[no-untyped-def]
    screen = _pin_pad(qt_app)

    screen.set_busy(True)

    assert screen.is_busy is True
    assert screen.face_button().isEnabled() is False
    assert all(not button.isEnabled() for button in screen._keys)


@requires_qt
def test_clearing_busy_restores_every_button(qt_app) -> None:  # type: ignore[no-untyped-def]
    """`finally` bloku bunu HƏR halda çağırır — uğursuzluqdan sonra da."""
    screen = _pin_pad(qt_app)

    screen.set_busy(True)
    screen.set_busy(False)

    assert screen.is_busy is False
    assert screen.face_button().isEnabled() is True
    assert all(button.isEnabled() for button in screen._keys)


@requires_qt
def test_busy_shows_a_neutral_message_not_an_error(qt_app) -> None:  # type: ignore[no-untyped-def]
    """«Yoxlanılır…» xəta DEYİL — nöqtələr qırmızıya boyanmamalıdır."""
    screen = _pin_pad(qt_app)

    screen.set_busy(True)

    assert screen._message.text() == "Üz yoxlanılır…"
    assert screen._dots._error is False


@requires_qt
def test_busy_is_independent_from_the_lockout_state(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Bloklama siyasət nəticəsidir, məşğulluq müvəqqəti gözləmədir."""
    screen = _pin_pad(qt_app)

    screen.set_busy(True)
    screen.set_busy(False)

    assert screen.is_locked is False


# --------------------------------------------------------------------------- #
# `app.py::start_kiosk` — `on_face_login` FON SAPINDA (DÖVRƏ 5)
# --------------------------------------------------------------------------- #


def _drain_until(qt_app: Any, predicate: Any, *, seconds: float = 5.0) -> None:
    """`predicate()` `True` olana qədər hadisə dövrəsini işlədir.

    Bax `test_session_touch_guard.py::_drain_until` / `test_face_login_
    background.py::_drain_until` — eyni əsaslandırma: fon işinin nəticəsi Qt
    siqnalı ilə qayıdır, hadisə dövrəsi işləmədən heç vaxt çatmaz.
    """
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        qt_app.processEvents()


def _kiosk_application(qt_app: Any) -> Any:
    from src.domain.value_objects.identifiers import StoreId
    from src.domain.value_objects.machine_identity import MachineIdentityHash
    from src.presentation.app import KompasApplication
    from src.presentation.controllers.kiosk import KioskController
    from src.presentation.theme.tokens import ThemeMode

    application = KompasApplication(
        qt_app, preview=False, theme_preference=ThemeMode.LIGHT, context=None
    )
    controller = KioskController(  # type: ignore[arg-type]
        None,
        store_id=StoreId(uuid.uuid4()),
        machine_key=MachineIdentityHash(digest="a" * 64),
    )
    application.set_kiosk_controller(controller)
    return application, controller


@requires_qt
def test_kiosk_face_login_does_not_block_the_gui_thread(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Çağırış ÖZÜ dərhal qayıtmalıdır — köhnə (sinxron) versiyada bloklayardı."""
    from src.presentation.controllers.kiosk import KioskOutcome
    from src.presentation.screens.group_a_kiosk import PinPadScreen

    application, controller = _kiosk_application(qt_app)
    block = __import__("threading").Event()

    def _slow_authenticate() -> KioskOutcome:
        block.wait(timeout=5.0)
        return KioskOutcome(succeeded=False, message="test")

    controller.authenticate_by_face = _slow_authenticate  # type: ignore[method-assign]

    kiosk = application.start_kiosk()
    pin_pad = kiosk.findChild(PinPadScreen)
    assert pin_pad is not None

    pin_pad.face_login_requested.emit()

    # ÇAĞIRIŞ ÖZÜ dərhal qayıtdı — iş hələ FON SAPINDA gedir.
    assert application._kiosk_face_task is not None
    assert application._kiosk_face_task.is_running
    assert pin_pad.is_busy is True

    block.set()
    _drain_until(qt_app, lambda: not application._kiosk_face_task.is_running)


@requires_qt
def test_successful_kiosk_face_login_opens_the_employee_home(  # type: ignore[no-untyped-def]
    qt_app, monkeypatch
) -> None:
    from PySide6.QtWidgets import QWidget

    from src.presentation.controllers.kiosk import KioskOutcome
    from src.presentation.screens.group_a_kiosk import PinPadScreen

    application, controller = _kiosk_application(qt_app)
    employee = object()
    outcome = KioskOutcome(succeeded=True, employee=employee)  # type: ignore[arg-type]
    controller.authenticate_by_face = lambda: outcome  # type: ignore[method-assign]

    opened: list[Any] = []

    def _fake_build_employee_home(result: Any, *, kiosk: Any, pin_pad: Any) -> Any:
        opened.append(result)
        return QWidget()

    monkeypatch.setattr(application, "_build_employee_home", _fake_build_employee_home)

    kiosk = application.start_kiosk()
    pin_pad = kiosk.findChild(PinPadScreen)
    assert pin_pad is not None

    pin_pad.face_login_requested.emit()
    _drain_until(qt_app, lambda: not application._kiosk_face_task.is_running)

    assert opened == [outcome]
    assert pin_pad.is_busy is False


@requires_qt
def test_denied_kiosk_face_login_shows_the_message_and_clears_busy(qt_app) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.kiosk import KioskOutcome
    from src.presentation.screens.group_a_kiosk import PinPadScreen

    application, controller = _kiosk_application(qt_app)
    controller.authenticate_by_face = lambda: KioskOutcome(  # type: ignore[method-assign]
        succeeded=False, message="Üzünüz uyğun gəlmədi."
    )

    kiosk = application.start_kiosk()
    pin_pad = kiosk.findChild(PinPadScreen)
    assert pin_pad is not None

    pin_pad.face_login_requested.emit()
    _drain_until(qt_app, lambda: not application._kiosk_face_task.is_running)

    assert pin_pad.is_busy is False
    assert pin_pad._message.text() == "Üzünüz uyğun gəlmədi."  # type: ignore[attr-defined]


@requires_qt
def test_unexpected_kiosk_task_failure_is_logged_not_swallowed(  # type: ignore[no-untyped-def]
    qt_app, monkeypatch
) -> None:
    """`authenticate_by_face()` özü istisna ATMIR, lakin son qoruyucu sınanır."""
    from src.presentation import app as app_module
    from src.presentation.screens.group_a_kiosk import PinPadScreen

    application, controller = _kiosk_application(qt_app)

    def _boom() -> Any:
        raise RuntimeError("kamera əlçatmazdır")

    controller.authenticate_by_face = _boom  # type: ignore[method-assign]
    logged: list[str] = []
    monkeypatch.setattr(app_module._log, "error", lambda key, **_: logged.append(key))

    kiosk = application.start_kiosk()
    pin_pad = kiosk.findChild(PinPadScreen)
    assert pin_pad is not None

    pin_pad.face_login_requested.emit()
    _drain_until(qt_app, lambda: bool(logged))

    assert logged == ["KIOSK_FACE_LOGIN_TASK_FAILED"]
    assert pin_pad.is_busy is False
    assert pin_pad._message.text() == "Üz təsdiqi aparıla bilmədi. PIN ilə daxil olun."  # type: ignore[attr-defined]
