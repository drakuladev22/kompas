"""`OperatorQueueScreen` ↔ `controllers/camera_queue.py` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, üçüncü beşlik)
──────────────────────────────────────────────────────────────────────────────
`controllers/camera_queue.py` `tests/` daxilində HEÇ YERDƏ adı çəkilmirdi.
Bura ANTI-FRAUD (SEC-001, CLAUDE.md §5) qapısının GUI tərəfidir — real
"Təsdiqlə"/"Rədd Et"/"Vaxtı Düzəlt" düymələri klikllənir.

──────────────────────────────────────────────────────────────────────────────
TAPILAN QÜSUR — "GÖRMƏK = SƏLAHİYYƏT" POZUNTUSU (aşağıda `test_the_adjust_
button_is_shown_to_every_operator_...` sübut edir)
──────────────────────────────────────────────────────────────────────────────
`QueueRow` (`screens/group_b.py`) "Vaxtı Düzəlt" düyməsini HƏR sətirdə
QEYDSİZ-ŞƏRTSİZ qurur — ekranın konstruktoru aktor/flag məlumatı ÜMUMİYYƏTLƏ
QƏBUL ETMİR. `can_verify_returns` (ekrana giriş üçün, menyu qapısı) VƏ
`can_override_return_time` (manual vaxt düzəlişi üçün) AYRI, MÜSTƏQİL
flag-lərdir (`leave_verification.py:387-398`) — operator birincini daşıyıb
İKİNCİSİNƏ malik olmaya bilər. Belə operator düyməni görür, formanı doldurur,
"Təsdiqə Göndər" basır və YALNIZ O ZAMAN `AuthorizationError` alır — bu,
`kompasos-ui` skill-inin qadağan etdiyi tam nümunədir: "əgər element görünür
və yalnız klikdən sonra rədd edilirsə, bu QÜSURDUR".
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()
STORE_ID = uuid.uuid4()
EMPLOYEE_ID = uuid.uuid4()
LEAVE_REQUEST_ID = uuid.uuid4()
ATTENDANCE_ID = uuid.uuid4()


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


class _Employee:
    def __init__(self, name: str = "Aygün Məmmədova") -> None:
        self.full_name = name


class _LeaveRequest:
    def __init__(
        self,
        *,
        request_id: Any = LEAVE_REQUEST_ID,
        employee_id: Any = EMPLOYEE_ID,
        store_id: Any = STORE_ID,
    ) -> None:
        self.id = request_id
        self.employee_id = employee_id
        self.store_id = store_id
        self.return_claimed_time = datetime(2026, 8, 20, 13, 40, tzinfo=UTC)
        self.requested_time = datetime(2026, 8, 20, 13, 45, tzinfo=UTC)


class _AttendanceRecord:
    def __init__(self, *, record_id: Any = ATTENDANCE_ID) -> None:
        self.id = record_id
        self.employee_id = EMPLOYEE_ID
        self.store_id = STORE_ID
        self.work_date = datetime(2026, 8, 20, tzinfo=UTC).date()
        self.requested_at = datetime(2026, 8, 20, 8, 5, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _Row(dict):
    pass


class _Connection:
    def __init__(self, stores: dict[str, str]) -> None:
        self._stores = stores
        self._last_params: tuple[Any, ...] | None = None

    def execute(self, _sql: str, params: Any = None) -> _Connection:
        self._last_params = params
        return self

    def fetchone(self) -> _Row | None:
        if not self._last_params:
            return None
        store_id = str(self._last_params[0])
        name = self._stores.get(store_id)
        return _Row(name=name) if name else None


class _LeaveRequestsRepo:
    def __init__(self, requests: dict[Any, _LeaveRequest]) -> None:
        self._requests = requests

    def get(self, request_id: Any) -> _LeaveRequest | None:
        return self._requests.get(request_id)


class _AttendanceRepo:
    def __init__(self, records: dict[Any, _AttendanceRecord]) -> None:
        self._records = records

    def get(self, record_id: Any) -> _AttendanceRecord | None:
        return self._records.get(record_id)


class _EmployeesRepo:
    def __init__(self, employee: _Employee) -> None:
        self._employee = employee

    def get(self, _employee_id: Any) -> _Employee:
        return self._employee


class _Uow:
    def __init__(
        self,
        *,
        stores: dict[str, str],
        leave_requests: dict[Any, _LeaveRequest],
        attendance: dict[Any, _AttendanceRecord],
        employee: _Employee,
    ) -> None:
        self.connection = _Connection(stores)
        self.leave_requests = _LeaveRequestsRepo(leave_requests)
        self.attendance = _AttendanceRepo(attendance)
        self.employees = _EmployeesRepo(employee)


class _LeaveVerification:
    def __init__(self) -> None:
        self.verify_return_calls: list[dict[str, Any]] = []
        self.override_calls: list[dict[str, Any]] = []
        self.verify_return_error: KompasOSError | None = None
        self.override_error: KompasOSError | None = None

    async def verify_return(self, **kwargs: Any) -> None:
        if self.verify_return_error is not None:
            raise self.verify_return_error
        self.verify_return_calls.append(kwargs)

    def apply_override(self, **kwargs: Any) -> None:
        if self.override_error is not None:
            raise self.override_error
        self.override_calls.append(kwargs)


class _MorningCheckIn:
    def __init__(self) -> None:
        self.verifications: list[dict[str, Any]] = []
        self.rejections: list[dict[str, Any]] = []
        self.verify_error: KompasOSError | None = None
        self.reject_error: KompasOSError | None = None

    def verify(self, **kwargs: Any) -> None:
        if self.verify_error is not None:
            raise self.verify_error
        self.verifications.append(kwargs)

    def reject(self, **kwargs: Any) -> None:
        if self.reject_error is not None:
            raise self.reject_error
        self.rejections.append(kwargs)


class _Limits:
    def get_int(self, _tenant_id: Any, _key: str, fallback: int) -> int:
        return 30


class _Session:
    def __init__(
        self,
        *,
        stores: dict[str, str],
        leave_requests: dict[Any, _LeaveRequest],
        attendance: dict[Any, _AttendanceRecord],
        employee: _Employee,
        leave_verification: _LeaveVerification,
        morning_check_in: _MorningCheckIn,
    ) -> None:
        self.tenant_id = TENANT
        self.uow = _Uow(
            stores=stores, leave_requests=leave_requests, attendance=attendance, employee=employee
        )
        self.leave_verification = leave_verification
        self.morning_check_in = morning_check_in
        self.limits = _Limits()
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(
        self,
        *,
        stores: dict[str, str] | None = None,
        leave_requests: dict[Any, _LeaveRequest] | None = None,
        attendance: dict[Any, _AttendanceRecord] | None = None,
        employee: _Employee | None = None,
    ) -> None:
        self._stores = stores or {str(STORE_ID): "Mərkəz"}
        self._leave_requests = leave_requests or {}
        self._attendance = attendance or {}
        self._employee = employee or _Employee()
        self.leave_verification = _LeaveVerification()
        self.morning_check_in = _MorningCheckIn()
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(
            stores=self._stores,
            leave_requests=self._leave_requests,
            attendance=self._attendance,
            employee=self._employee,
            leave_verification=self.leave_verification,
            morning_check_in=self.morning_check_in,
        )
        self.sessions.append(created)
        yield created


class _Actor:
    id = ACTOR_ID


def _build_screen(
    theme: Any,
    qtbot: Any,
    *,
    assigned_stores: list[str] | None = None,
    may_override_return_time: bool = False,
) -> Any:
    """`may_override_return_time` FAIL-CLOSED defoltludur (`group_b.py`-dəki
    qərarın güzgüsü) — çağıran tərəf icazəni AÇIQ ötürməlidir, əks halda
    gələcək testlər səhvən permissiv qurula bilər."""
    from src.presentation.screens.group_b import OperatorQueueScreen

    screen = OperatorQueueScreen(
        theme,
        assigned_stores=assigned_stores or ["Mərkəz"],
        may_override_return_time=may_override_return_time,
    )
    qtbot.addWidget(screen)
    return screen


def _return_entry() -> Any:
    from src.presentation.screens.group_b import QueueEntry

    return QueueEntry(
        request_id=str(LEAVE_REQUEST_ID),
        employee_name="Aygün Məmmədova",
        store_name="Mərkəz",
        position_name="Satıcı",
        kind="Qayıdış Təsdiqi",
        timestamp_text="13:45",
        waiting_text="5 dəq",
    )


def _check_in_entry() -> Any:
    from src.presentation.screens.group_b import QueueEntry

    return QueueEntry(
        request_id=str(ATTENDANCE_ID),
        employee_name="Aygün Məmmədova",
        store_name="Mərkəz",
        position_name="Satıcı",
        kind="Giriş Təsdiqi",
        timestamp_text="08:05",
        waiting_text="10 dəq",
    )


# --------------------------------------------------------------------------- #
# 1. "GÖRMƏK = SƏLAHİYYƏT" — DÜZƏLDİLİB: "Vaxtı Düzəlt" İNDİ İCAZƏYƏ TABEDİR
# --------------------------------------------------------------------------- #
#
# `ui` `group_b.py`-ni düzəltdi: `OperatorQueueScreen`/`QueueRow` indi
# `may_override_return_time: bool` qəbul edir (fail-closed defolt, `False`)
# və `can_override_return_time`-ı olmayan operatorda düymə ÜMUMİYYƏTLƏ
# QURULMUR (boz DEYİL). Aşağıdakı İKİ test yeni davranışı REAL kliklə sınayır.


@requires_qt
def test_the_adjust_button_is_absent_without_the_override_permission(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Fail-closed defolt: icazə AÇIQ ötürülməyibsə düymə YOXDUR (görmək = səlahiyyət)."""
    from PySide6.QtWidgets import QPushButton

    screen = _build_screen(theme, qtbot, may_override_return_time=False)
    screen.set_entries([_return_entry()])

    texts = [b.text() for b in screen.findChildren(QPushButton)]
    assert "Vaxtı Düzəlt" not in texts


@requires_qt
def test_the_adjust_button_appears_when_the_operator_has_the_override_permission(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """`may_override_return_time=True` ötürüləndə düymə REAL görünür."""
    from PySide6.QtWidgets import QPushButton

    screen = _build_screen(theme, qtbot, may_override_return_time=True)
    screen.set_entries([_return_entry()])

    texts = [b.text() for b in screen.findChildren(QPushButton)]
    assert "Vaxtı Düzəlt" in texts


# --------------------------------------------------------------------------- #
# 2. Real "Təsdiqlə"/"Rədd Et" — qayıdış VƏ giriş mənbəyi
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_approve_on_a_return_row_commits_and_refreshes(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers import screen_data as screen_data_module
    from src.presentation.controllers.camera_queue import CameraQueueController

    populated: list[str] = []
    monkeypatch.setattr(
        screen_data_module,
        "ScreenDataBinder",
        type(
            "_Binder",
            (),
            {"__init__": lambda self, *a: None, "populate": lambda self, k, s: populated.append(k)},
        ),
    )

    context = _Context(leave_requests={LEAVE_REQUEST_ID: _LeaveRequest()})
    screen = _build_screen(theme, qtbot)
    screen.set_entries([_return_entry()])
    CameraQueueController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Təsdiqlə")

    assert len(context.leave_verification.verify_return_calls) == 1
    assert context.leave_verification.verify_return_calls[0]["request_id"] == LEAVE_REQUEST_ID
    assert any(s.committed for s in context.sessions)
    assert "live_queue" in populated


@requires_qt
def test_clicking_approve_on_a_check_in_row_commits(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers import screen_data as screen_data_module
    from src.presentation.controllers.camera_queue import CameraQueueController

    monkeypatch.setattr(
        screen_data_module,
        "ScreenDataBinder",
        type(
            "_Binder", (), {"__init__": lambda self, *a: None, "populate": lambda self, k, s: None}
        ),
    )

    context = _Context(attendance={ATTENDANCE_ID: _AttendanceRecord()})
    screen = _build_screen(theme, qtbot)
    screen.set_entries([_check_in_entry()])
    CameraQueueController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Təsdiqlə")

    assert len(context.morning_check_in.verifications) == 1
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_rejecting_a_check_in_prompts_for_a_reason_and_commits(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    from src.presentation.controllers import screen_data as screen_data_module
    from src.presentation.controllers.camera_queue import CameraQueueController

    monkeypatch.setattr(
        screen_data_module,
        "ScreenDataBinder",
        type(
            "_Binder", (), {"__init__": lambda self, *a: None, "populate": lambda self, k, s: None}
        ),
    )
    monkeypatch.setattr(
        QInputDialog,
        "getMultiLineText",
        staticmethod(lambda *a, **k: ("Foto bulanıqdır, yenidən çəkin", True)),
    )

    context = _Context(attendance={ATTENDANCE_ID: _AttendanceRecord()})
    screen = _build_screen(theme, qtbot)
    screen.set_entries([_check_in_entry()])
    CameraQueueController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Rədd Et")

    assert len(context.morning_check_in.rejections) == 1
    assert context.morning_check_in.rejections[0]["reason"] == "Foto bulanıqdır, yenidən çəkin"


@requires_qt
def test_a_reject_reason_shorter_than_the_domain_minimum_never_reaches_the_use_case(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    from src.presentation.controllers import screen_data as screen_data_module
    from src.presentation.controllers.camera_queue import CameraQueueController

    monkeypatch.setattr(
        screen_data_module,
        "ScreenDataBinder",
        type(
            "_Binder", (), {"__init__": lambda self, *a: None, "populate": lambda self, k, s: None}
        ),
    )
    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("x", True)))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: None)

    context = _Context(attendance={ATTENDANCE_ID: _AttendanceRecord()})
    screen = _build_screen(theme, qtbot)
    screen.set_entries([_check_in_entry()])
    CameraQueueController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Rədd Et")  # ÇÖKMƏMƏLİDİR

    assert context.morning_check_in.rejections == []


@requires_qt
def test_rejecting_a_return_row_shows_the_no_reject_message_and_writes_nothing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Qayıdış təsdiqində "rədd" anlayışı YOXDUR (modul başlığı) — real klik AÇIQ mesaj verir.

    Səbəb HƏMİŞƏ ƏVVƏLCƏ soruşulur (`_on_reject` → `_ask_reason`), mənbə
    yalnız SONRA `_run()`-da müəyyən edilir — real modalı monkeypatch etmək
    LAZIMDIR, əks halda test sapı bloklanar.
    """
    from PySide6.QtWidgets import QInputDialog

    from src.presentation.controllers.camera_queue import CameraQueueController

    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("real səbəb budur", True))
    )

    context = _Context(leave_requests={LEAVE_REQUEST_ID: _LeaveRequest()})
    screen = _build_screen(theme, qtbot)
    screen.set_entries([_return_entry()])
    CameraQueueController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Rədd Et")  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"
    assert context.leave_verification.verify_return_calls == []


# --------------------------------------------------------------------------- #
# 3. Real "Vaxtı Düzəlt" — dual-control xəbərdarlığı, real submit
# --------------------------------------------------------------------------- #


@requires_qt
def test_adjusting_time_via_the_real_dialog_commits(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.controllers.camera_queue import CameraQueueController
    from src.presentation.screens.group_b import ManualTimeOverrideDialog

    context = _Context(leave_requests={LEAVE_REQUEST_ID: _LeaveRequest()})
    screen = _build_screen(theme, qtbot, may_override_return_time=True)
    screen.set_entries([_return_entry()])
    CameraQueueController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    def fake_exec(self: ManualTimeOverrideDialog) -> int:
        self._reason.setPlainText("İşçi əslində 13:40-da qayıtmışdı")
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Təsdiqə Göndər")
        submit.click()
        return 0

    monkeypatch.setattr(ManualTimeOverrideDialog, "exec", fake_exec)

    _click(screen, "Vaxtı Düzəlt")

    assert len(context.leave_verification.override_calls) == 1
    assert context.leave_verification.override_calls[0]["reason"] == (
        "İşçi əslində 13:40-da qayıtmışdı"
    )
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_the_reason_field_is_required_by_the_real_dialog_before_any_write(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.controllers.camera_queue import CameraQueueController
    from src.presentation.screens.group_b import ManualTimeOverrideDialog

    context = _Context(leave_requests={LEAVE_REQUEST_ID: _LeaveRequest()})
    screen = _build_screen(theme, qtbot, may_override_return_time=True)
    screen.set_entries([_return_entry()])
    CameraQueueController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    def fake_exec(self: ManualTimeOverrideDialog) -> int:
        self.show()  # `isVisible()` göstərilməyən pəncərədə HƏMİŞƏ False qaytarır
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Təsdiqə Göndər")
        submit.click()  # səbəb BOŞ
        assert self._reason_error.isVisible()
        return self.reject()

    monkeypatch.setattr(ManualTimeOverrideDialog, "exec", fake_exec)

    _click(screen, "Vaxtı Düzəlt")

    assert context.leave_verification.override_calls == []


@requires_qt
def test_a_large_time_difference_shows_the_real_dual_control_warning(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """SEC-001-in eyni ruhu: böyük fərq İKİNCİ təsdiq tələb edir, REAL widget-də görünür."""
    from src.presentation.screens.group_b import ManualTimeOverrideDialog

    dialog = ManualTimeOverrideDialog(
        theme,
        employee_name="Aygün Məmmədova",
        store_name="Mərkəz",
        kind="Qayıdış Təsdiqi",
        system_time="13:45",
        threshold_minutes=30,
    )
    qtbot.addWidget(dialog)
    dialog.show()  # `isVisible()` göstərilməyən pəncərədə HƏMİŞƏ False qaytarır

    from PySide6.QtCore import QTime

    dialog._time_edit.setTime(QTime(14, 30))  # 45 dəqiqə fərq — 30 həddini keçir

    assert dialog.requires_dual_control
    assert dialog._dual_control.isVisible()


# --------------------------------------------------------------------------- #
# 4. Malformed ID, oxu-yazı istisnası — çökmür
# --------------------------------------------------------------------------- #


@requires_qt
def test_an_unknown_request_id_shows_a_clear_message_not_a_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Sətir artıq emal edilib (paralel operator basıb) — real klik AÇIQ mesaj verir."""
    from src.presentation.controllers.camera_queue import CameraQueueController

    context = _Context()  # heç bir sorğu/qeyd YOXDUR
    screen = _build_screen(theme, qtbot)
    screen.set_entries([_return_entry()])
    CameraQueueController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Təsdiqlə")  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"


@requires_qt
def test_verify_return_failure_shows_the_domain_message_and_does_not_commit(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Anti-fraud rəddi (`FinePermissionError`/SEC-001) — real klik AÇIQ mesaj göstərir."""
    from src.presentation.controllers.camera_queue import CameraQueueController

    context = _Context(leave_requests={LEAVE_REQUEST_ID: _LeaveRequest()})
    context.leave_verification.verify_return_error = KompasOSError(
        "camera role cannot dual-control",
        user_message="Kamera operatoru cüt-nəzarətli təsdiqi daşıya bilməz.",
    )
    screen = _build_screen(theme, qtbot)
    screen.set_entries([_return_entry()])
    CameraQueueController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Təsdiqlə")  # ÇÖKMƏMƏLİDİR

    assert not any(s.committed for s in context.sessions)
    assert screen.switcher().current_state() == "error"
