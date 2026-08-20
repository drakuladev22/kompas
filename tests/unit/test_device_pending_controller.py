"""`DevicePendingController` — qeydiyyat FON SAPINDA (DÖVRƏ 5 audit tapıntısı).

──────────────────────────────────────────────────────────────────────────────
NƏ YOXLANILIR
──────────────────────────────────────────────────────────────────────────────
`register()` `device_identity.collect_fingerprint()` çağırır və o, Windows-da
PowerShell alt-prosesi işə salıb `HARDWARE_PROBE_TIMEOUT_SECONDS` (8 san.)
qədər gözləyə bilər (`device_identity.py`). Əvvəl bu, «Yenidən Yoxla»
düyməsinin `clicked` slotunda BİRBAŞA, GUI sapında çağırılırdı — düymə
`set_busy(True)` ilə deaktiv olurdu, lakin bütün pəncərə iş bitənə qədər
CAVAB VERMİRDİ.

Burada `register()`-in ÖZÜ (aparat izi, fayl I/O) sınanmır — bu,
`test_device_identity.py`/`test_device_registry.py`-nin işidir. Yalnız
KONTROLLERİN naxışı ölçülür: iş `InlineExecutor` ilə sinxron tetiklənir
(hadisə dövrü olmadan), lakin `run_job` körpüsündən keçir — yəni əsl icrada
eyni kod yolu Qt hovuzunda FON SAPINDA işləyəcək.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.domain.value_objects.devices import DeviceStatus
from src.presentation.background_task import InlineExecutor
from src.presentation.controllers.devices import REGISTER_FAILED, DevicePendingController
from src.shared.exceptions import KompasOSError

pytestmark = pytest.mark.unit


class _Device:
    def __init__(self, *, status: DeviceStatus = DeviceStatus.PENDING_APPROVAL) -> None:
        self.short_code = "AB12CD"
        self.machine_name = "KASSA-3"
        self.status = status


class _Screen:
    def __init__(self) -> None:
        self.busy_history: list[bool] = []
        self.devices: list[dict[str, Any]] = []
        self.errors: list[tuple[str, str]] = []

    def set_busy(self, busy: bool) -> None:
        self.busy_history.append(busy)

    def set_device(self, *, short_code: str, machine_name: str, status: DeviceStatus) -> None:
        self.devices.append(
            {"short_code": short_code, "machine_name": machine_name, "status": status}
        )

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


def _controller(monkeypatch: pytest.MonkeyPatch, *, register: Any) -> DevicePendingController:
    # `InlineExecutor`: bu testlər MƏNTİQİ ölçür, sapı yox — nəticə dərhal,
    # hadisə dövrü gözləmədən qayıdır (bax `background_task.py`).
    controller = DevicePendingController(object(), executor=InlineExecutor())  # type: ignore[arg-type]
    monkeypatch.setattr(controller, "register", register)
    return controller


def test_successful_recheck_updates_the_screen_and_clears_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = _Device()
    controller = _controller(monkeypatch, register=lambda: device)
    screen = _Screen()

    controller.refresh(screen)

    # `set_busy(True)` iş BAŞLAMADAN, `set_busy(False)` nəticə GƏLƏNDƏ — ikisi
    # arasında düymə "Yoxlanılır…" göstərməli idi (bax `DevicePendingScreen`).
    assert screen.busy_history == [True, False]
    assert screen.devices == [
        {"short_code": "AB12CD", "machine_name": "KASSA-3", "status": DeviceStatus.PENDING_APPROVAL}
    ]
    assert screen.errors == []


def test_domain_failure_shows_the_domain_message_not_a_blank_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _DeniedError(KompasOSError):
        user_message = "Baza ilə əlaqə qurulmadı."

    def _boom() -> Any:
        raise _DeniedError("no db")

    controller = _controller(monkeypatch, register=_boom)
    screen = _Screen()

    controller.refresh(screen)

    assert screen.busy_history == [True, False]
    assert screen.errors == [("Qeydiyyat alınmadı", "Baza ilə əlaqə qurulmadı.")]
    assert screen.devices == []


def test_unexpected_failure_falls_back_to_the_generic_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> Any:
        raise RuntimeError("powershell əlçatmazdır")

    controller = _controller(monkeypatch, register=_boom)
    screen = _Screen()

    controller.refresh(screen)

    assert screen.busy_history == [True, False]
    assert screen.errors == [("Qeydiyyat alınmadı", REGISTER_FAILED)]


def test_recheck_button_wiring_triggers_a_fresh_probe() -> None:
    """`recheck_requested` siqnalı FAKTİKİ bağlanmalıdır (`test_dead_signal_wiring.py` başlığı)."""

    class _Signal:
        def __init__(self) -> None:
            self.slot: Any = None

        def connect(self, slot: Any) -> None:
            self.slot = slot

    class _AttachScreen(_Screen):
        def __init__(self) -> None:
            super().__init__()
            self.recheck_requested = _Signal()

    calls = {"count": 0}

    def _register() -> _Device:
        calls["count"] += 1
        return _Device()

    controller = DevicePendingController(object(), executor=InlineExecutor())  # type: ignore[arg-type]
    controller.register = _register  # type: ignore[method-assign]
    screen = _AttachScreen()

    controller.attach(screen)  # `attach()` özü BİR dəfə çağırır.
    assert calls["count"] == 1
    assert screen.recheck_requested.slot is not None

    screen.recheck_requested.slot()  # düymə basılışını simulyasiya edir
    assert calls["count"] == 2
