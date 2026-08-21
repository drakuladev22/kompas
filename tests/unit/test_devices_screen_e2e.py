"""`DeviceAdminScreen`/`DevicePendingScreen` ↔ `controllers/devices.py` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3)
──────────────────────────────────────────────────────────────────────────────
`test_device_admin_screen.py` YALNIZ `DeviceAdminScreen`-in ÖZÜNÜ (aparat izi
qapısı) ölçür — heç bir `DeviceAdminController` bağlamır. `test_device_pending_
controller.py` isə TAM ƏKSİNƏ — kontrolleri sahtə `_Screen` siniflə ölçür, heç
vaxt REAL `DevicePendingScreen` qurmur. Yəni «Təsdiqlə»/«Blokla»/«Köçür»
düymələrinin REAL kliki heç yerdə kontrollerə çatmır. Burada hər ikisi
(ekran + kontroller) FAKTİKİ qurulur və REAL widget qarşılıqlı təsiri ilə
sınanır.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any

import pytest

from src.domain.value_objects.devices import DeviceStatus, DeviceType
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()
STORE_A = str(uuid.uuid4())
STORE_B = str(uuid.uuid4())
DEVICE_ACTIVE = str(uuid.uuid4())
DEVICE_BLOCKED = str(uuid.uuid4())
DEVICE_PENDING = str(uuid.uuid4())


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
# `DeviceAdminScreen` sahtələri
# --------------------------------------------------------------------------- #


class _Row(dict):
    pass


class _Connection:
    def __init__(self, stores: list[tuple[str, str]]) -> None:
        self._stores = stores

    def execute(self, _sql: str, _params: Any = None) -> _Connection:
        return self

    def fetchall(self) -> list[_Row]:
        return [_Row(id=sid, name=name) for sid, name in self._stores]


class _Uow:
    def __init__(self, stores: list[tuple[str, str]]) -> None:
        self.connection = _Connection(stores)


class _Usage:
    def describe(self) -> str:
        return "3 / 10 cihaz istifadə olunur"


class _RegisteredDevice:
    """`RegisteredDevice`-in yerini tutur — kontroller yalnız bu atributları oxuyur."""

    def __init__(
        self,
        *,
        device_id: str,
        status: DeviceStatus,
        device_type: DeviceType = DeviceType.ADMIN_PC,
        store_id: str | None = None,
        pending_fingerprint: str | None = None,
        short_code: str = "AB12CD",
        machine_name: str = "KASSA-1",
    ) -> None:
        self.id = device_id
        self.status = status
        self.device_type = device_type
        self.store_id = store_id
        self.pending_fingerprint = pending_fingerprint
        self.short_code = short_code
        self.machine_name = machine_name
        self.device_name = machine_name
        self.last_seen_at = None


class _Devices:
    def __init__(self) -> None:
        self.rows: list[_RegisteredDevice] = []
        self.list_error: KompasOSError | None = None
        self.approvals: list[dict[str, Any]] = []
        self.blocks: list[dict[str, Any]] = []
        self.reactivations: list[Any] = []
        self.reassignments: list[dict[str, Any]] = []
        self.accepted_fingerprints: list[Any] = []
        self.register_result: Any = None
        self.register_error: BaseException | None = None

    def list_all(self, *, tenant_id: Any, actor: Any) -> list[_RegisteredDevice]:
        if self.list_error is not None:
            raise self.list_error
        return list(self.rows)

    def license_usage(self, _tenant_id: Any) -> _Usage:
        return _Usage()

    def approve(self, **kwargs: Any) -> None:
        self.approvals.append(kwargs)

    def block(self, **kwargs: Any) -> None:
        self.blocks.append(kwargs)

    def reactivate(self, **kwargs: Any) -> None:
        self.reactivations.append(kwargs)

    def reassign_store(self, **kwargs: Any) -> None:
        self.reassignments.append(kwargs)

    def accept_fingerprint(self, **kwargs: Any) -> None:
        self.accepted_fingerprints.append(kwargs)

    def register_self(self, **kwargs: Any) -> Any:
        if self.register_error is not None:
            raise self.register_error
        return self.register_result


class _Session:
    def __init__(self, devices: _Devices, stores: list[tuple[str, str]]) -> None:
        self.tenant_id = TENANT
        self.devices = devices
        self.uow = _Uow(stores)
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(self, devices: _Devices, stores: list[tuple[str, str]] | None = None) -> None:
        self._devices = devices
        self._stores = stores or []
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(self._devices, self._stores)
        self.sessions.append(created)
        yield created


class _Actor:
    id = ACTOR_ID


# --------------------------------------------------------------------------- #
# 1. Admin: Təsdiq forması → real klik → approve() + commit + yenidən oxuma
# --------------------------------------------------------------------------- #


@requires_qt
def test_approving_a_pending_device_via_the_real_inline_form_commits(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.devices import DeviceAdminController
    from src.presentation.screens.devices import DeviceAdminScreen

    devices = _Devices()
    devices.rows = [
        _RegisteredDevice(device_id=DEVICE_PENDING, status=DeviceStatus.PENDING_APPROVAL)
    ]
    context = _Context(devices, [(STORE_A, "Mərkəz")])
    screen = DeviceAdminScreen(theme)
    qtbot.addWidget(screen)
    DeviceAdminController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    from PySide6.QtWidgets import QLineEdit

    name_input = next(w for w in screen.findChildren(QLineEdit))
    name_input.setText("KASSA-YENİ")
    _click(screen, "Təsdiqlə")

    assert len(devices.approvals) == 1
    approval = devices.approvals[0]
    assert str(approval["device_id"]) == DEVICE_PENDING
    assert str(approval["store_id"]) == STORE_A
    assert approval["device_name"] == "KASSA-YENİ"
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_approve_without_a_store_choice_is_rejected_before_reaching_the_use_case(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """Mağaza siyahısı boşdursa `store_box.currentData()` `None` qaytarır."""
    from src.presentation.controllers.devices import DeviceAdminController
    from src.presentation.screens.devices import DeviceAdminScreen

    devices = _Devices()
    devices.rows = [
        _RegisteredDevice(device_id=DEVICE_PENDING, status=DeviceStatus.PENDING_APPROVAL)
    ]
    context = _Context(devices, [])  # HEÇ BİR mağaza yoxdur
    screen = DeviceAdminScreen(theme)
    qtbot.addWidget(screen)
    DeviceAdminController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Təsdiqlə")  # ÇÖKMƏMƏLİDİR

    assert devices.approvals == []
    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 2. Admin: aktiv cihaz sətri — Blokla / Köçür / (uyğunsuzluqda) İzi Qəbul Et
# --------------------------------------------------------------------------- #


@requires_qt
def test_blocking_an_active_device_via_the_real_row_button_commits(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.devices import DeviceAdminController
    from src.presentation.screens.devices import DeviceAdminScreen

    devices = _Devices()
    devices.rows = [
        _RegisteredDevice(device_id=DEVICE_ACTIVE, status=DeviceStatus.ACTIVE, store_id=STORE_A)
    ]
    context = _Context(devices, [(STORE_A, "Mərkəz")])
    screen = DeviceAdminScreen(theme)
    qtbot.addWidget(screen)
    DeviceAdminController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Blokla")

    assert len(devices.blocks) == 1
    assert str(devices.blocks[0]["device_id"]) == DEVICE_ACTIVE
    assert devices.blocks[0]["reason"] == "Administrator tərəfindən bloklandı"
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_reassigning_the_store_via_the_real_combo_and_button_commits(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.devices import DeviceAdminController
    from src.presentation.screens.devices import DeviceAdminScreen

    devices = _Devices()
    devices.rows = [
        _RegisteredDevice(device_id=DEVICE_ACTIVE, status=DeviceStatus.ACTIVE, store_id=STORE_A)
    ]
    context = _Context(devices, [(STORE_A, "Mərkəz"), (STORE_B, "28 May")])
    screen = DeviceAdminScreen(theme)
    qtbot.addWidget(screen)
    DeviceAdminController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    from PySide6.QtWidgets import QComboBox

    combo = next(c for c in screen.findChildren(QComboBox) if c.findData(STORE_B) >= 0)
    combo.setCurrentIndex(combo.findData(STORE_B))
    _click(screen, "Köçür")

    assert len(devices.reassignments) == 1
    assert str(devices.reassignments[0]["store_id"]) == STORE_B
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_reactivating_a_blocked_device_via_the_real_button_commits(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.devices import DeviceAdminController
    from src.presentation.screens.devices import DeviceAdminScreen

    devices = _Devices()
    devices.rows = [_RegisteredDevice(device_id=DEVICE_BLOCKED, status=DeviceStatus.BLOCKED)]
    context = _Context(devices, [])
    screen = DeviceAdminScreen(theme)
    qtbot.addWidget(screen)
    DeviceAdminController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Bərpa Et")

    assert len(devices.reactivations) == 1
    assert str(devices.reactivations[0]["device_id"]) == DEVICE_BLOCKED
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_accepting_a_pending_fingerprint_via_the_real_button_commits(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Düymə YALNIZ uyğunsuzluq görülmüş sətirdə çıxır (`test_device_admin_screen.py`
    onu screen-level ölçür) — burada REAL kontrollerlə UCADAN UCA doğrulanır."""
    from src.presentation.controllers.devices import DeviceAdminController
    from src.presentation.screens.devices import DeviceAdminScreen

    devices = _Devices()
    devices.rows = [
        _RegisteredDevice(
            device_id=DEVICE_ACTIVE,
            status=DeviceStatus.ACTIVE,
            store_id=STORE_A,
            pending_fingerprint="deadbeef" * 8,
        )
    ]
    context = _Context(devices, [(STORE_A, "Mərkəz")])
    screen = DeviceAdminScreen(theme)
    qtbot.addWidget(screen)
    DeviceAdminController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "İzi Qəbul Et")

    assert len(devices.accepted_fingerprints) == 1
    assert str(devices.accepted_fingerprints[0]["device_id"]) == DEVICE_ACTIVE
    assert any(s.committed for s in context.sessions)


# --------------------------------------------------------------------------- #
# 3. Admin: oxu xətası, yazı xətası — çökmür, AÇIQ mesaj göstərir
# --------------------------------------------------------------------------- #


@requires_qt
def test_list_read_failure_shows_an_error_instead_of_a_blank_screen(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.devices import DeviceAdminController
    from src.presentation.screens.devices import DeviceAdminScreen

    devices = _Devices()
    devices.list_error = KompasOSError("db down", user_message="Baza əlaqəsi kəsildi.")
    context = _Context(devices, [])
    screen = DeviceAdminScreen(theme)
    qtbot.addWidget(screen)

    DeviceAdminController(context, _Actor()).attach(screen)  # type: ignore[arg-type]  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"


@requires_qt
def test_block_failure_from_a_concurrent_change_shows_the_domain_message(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Başqa admin artıq bloklayıbsa da — real klik AÇIQ mesaj göstərməlidir, çökməməlidir."""
    from src.presentation.controllers.devices import DeviceAdminController
    from src.presentation.screens.devices import DeviceAdminScreen

    devices = _Devices()
    devices.rows = [
        _RegisteredDevice(device_id=DEVICE_ACTIVE, status=DeviceStatus.ACTIVE, store_id=STORE_A)
    ]
    context = _Context(devices, [(STORE_A, "Mərkəz")])
    screen = DeviceAdminScreen(theme)
    qtbot.addWidget(screen)
    DeviceAdminController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    def _fails(**_: Any) -> None:
        raise KompasOSError("stale", user_message="Bu cihaz artıq başqası tərəfindən bloklanıb.")

    devices.block = _fails  # type: ignore[method-assign]

    _click(screen, "Blokla")  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 4. `DevicePendingScreen` — real «Yenidən Yoxla» kliki, `InlineExecutor`
# --------------------------------------------------------------------------- #


@requires_qt
def test_recheck_button_registers_and_shows_the_device_code(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Real düymə kliki → FON işi (`InlineExecutor`) → real kod REAL label-də görünür."""
    from src.infrastructure.config import device_identity as device_identity_module
    from src.presentation.background_task import InlineExecutor
    from src.presentation.controllers.devices import DevicePendingController
    from src.presentation.screens.devices import DevicePendingScreen

    monkeypatch.setattr(device_identity_module, "load_device_id", lambda path=None: None)
    monkeypatch.setattr(device_identity_module, "collect_fingerprint", _fingerprint)
    saved: list[Any] = []
    monkeypatch.setattr(
        device_identity_module,
        "save_device_id",
        lambda device_id, path=None: saved.append(device_id),
    )

    devices = _Devices()
    devices.register_result = _RegistrationOutcome(
        is_new=True,
        device=_RegisteredDevice(
            device_id=DEVICE_PENDING,
            status=DeviceStatus.PENDING_APPROVAL,
            short_code="QWERTY",
            machine_name="TEST-PC",
        ),
    )
    context = _Context(devices, [])
    screen = DevicePendingScreen(theme)
    qtbot.addWidget(screen)
    DevicePendingController(context, executor=InlineExecutor()).attach(screen)  # type: ignore[arg-type]
    # `attach()` ÖZÜ ilk yoxlamanı işə salır (bax modul başlığı) — casus BUNDAN
    # SONRA qoyulur ki, yalnız DÜYMƏ KLİKİNİN açdığı iş ölçülsün.
    busy_calls: list[bool] = []
    original_set_busy = screen.set_busy
    screen.set_busy = lambda busy: (busy_calls.append(busy), original_set_busy(busy))[1]  # type: ignore[method-assign]

    _click(screen, "Yenidən Yoxla")

    assert screen._code.text() == "QWERTY"
    # `attach()` özü DƏ bir dəfə qeydiyyat aparır (ilk yoxlama) — kliklə
    # birlikdə cəmi İKİ yazı olur, hər ikisi eyni cihaz id-sinədir.
    assert saved == [DEVICE_PENDING, DEVICE_PENDING]
    assert busy_calls == [True, False], "`InlineExecutor` sinxrondur — busy dərhal bağlanmalıdır"
    assert screen._recheck.isEnabled()


def _fingerprint() -> Any:
    return _FakeFingerprint()


@requires_qt
def test_a_domain_rejection_during_registration_shows_its_own_message(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.infrastructure.config import device_identity as device_identity_module
    from src.presentation.background_task import InlineExecutor
    from src.presentation.controllers.devices import DevicePendingController
    from src.presentation.screens.devices import DevicePendingScreen

    monkeypatch.setattr(device_identity_module, "load_device_id", lambda path=None: None)
    monkeypatch.setattr(device_identity_module, "collect_fingerprint", _fingerprint)

    devices = _Devices()
    devices.register_error = KompasOSError(
        "license exhausted", user_message="Lisenziya limiti dolub."
    )
    context = _Context(devices, [])
    screen = DevicePendingScreen(theme)
    qtbot.addWidget(screen)
    DevicePendingController(context, executor=InlineExecutor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Yenidən Yoxla")  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"
    # Xəta sonrası düymə YENİDƏN aktivləşməlidir — əks halda admin ƏBƏDİ
    # "Yoxlanılır…" görər və heç vaxt yenidən cəhd edə bilməz.
    assert screen._recheck.isEnabled()
    assert screen._recheck.text() == "Yenidən Yoxla"


@requires_qt
def test_an_unexpected_exception_during_registration_falls_back_to_the_generic_message(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """`collect_fingerprint()` gözlənilməz istisna atsa da — ÇÖKMƏMƏLİDİR, generik mesaj."""
    from src.infrastructure.config import device_identity as device_identity_module
    from src.presentation.background_task import InlineExecutor
    from src.presentation.controllers.devices import REGISTER_FAILED, DevicePendingController
    from src.presentation.screens.devices import DevicePendingScreen

    monkeypatch.setattr(device_identity_module, "load_device_id", lambda path=None: None)

    def _boom() -> Any:
        raise RuntimeError("PowerShell timeout")

    monkeypatch.setattr(device_identity_module, "collect_fingerprint", _boom)

    devices = _Devices()
    context = _Context(devices, [])
    screen = DevicePendingScreen(theme)
    qtbot.addWidget(screen)

    errors: list[tuple[str, str]] = []
    original_show_error = screen.show_error

    def _spy(*, title: str, message: str, **kwargs: Any) -> Any:
        errors.append((title, message))
        return original_show_error(title=title, message=message, **kwargs)

    screen.show_error = _spy  # type: ignore[method-assign]

    DevicePendingController(context, executor=InlineExecutor()).attach(screen)  # type: ignore[arg-type]  # ÇÖKMƏMƏLİDİR (attach() özü ilk yoxlamanı işə salır)

    assert errors and errors[-1][1] == REGISTER_FAILED


class _FakeFingerprint:
    value = "a" * 32


class _RegistrationOutcome:
    def __init__(self, *, is_new: bool, device: _RegisteredDevice) -> None:
        self.is_new = is_new
        self.device = device
