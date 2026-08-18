"""Kontroller YAZI YOLLARININ əhatəsiz qalmış hissələri — Faza 5/6 auditi.

──────────────────────────────────────────────────────────────────────────────
NİYƏ MƏHZ KONTROLLERLƏR
──────────────────────────────────────────────────────────────────────────────
Kontroller heç bir iş qaydası daşımır, LAKİN o, qaydanın istifadəçiyə çatan
YEGANƏ yoludur. Buradakı səhv tip xətası vermir və domen testlərini qırmır:
    * `commit()` unudulur  → yazı sükutla rollback olur,
    * istisna udulur       → istifadəçi «heç nə olmadı» görür,
    * ekran yenilənmir     → köhnə sətir yeni məlumat kimi oxunur.

Ölçmə göstərdi ki, `kiosk.py` tamamilə, `camera_queue.py`, `root_control.py`,
`profile.py` və `support_chat.py` isə qismən əhatəsizdir. Aşağıdakı testlər
məhz həmin yolları — xüsusən XƏTA və SƏRHƏD hallarını — bağlayır.

Testlər Qt hadisə dövrəsi TƏLƏB ETMİR: ekranlar duck-typing ilə əvəzlənir;
yalnız modal açan iki yolda `PySide6.QtWidgets` sinfi sahtə ilə əvəz olunur.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

import pytest

from src.application.use_cases.face_control import FaceGateDecision, FaceGateOutcome
from src.application.use_cases.leave_verification import OperationNotPermittedError
from src.domain.entities.attendance_record import CheckInStatus
from src.domain.entities.leave_request import LeaveStatus
from src.domain.policies import FeatureModule, SystemLimitKey
from src.domain.value_objects.authorization import HardlockLevel, PermissionFlag
from src.domain.value_objects.face_recognition import FaceStoreScope
from src.domain.value_objects.identifiers import (
    AttendanceRecordId,
    EmployeeId,
    LeaveRequestId,
    StoreId,
    TenantId,
)
from src.presentation.controllers.camera_queue import CameraQueueController, _combine
from src.presentation.controllers.kiosk import KioskController, KioskOutcome
from src.presentation.controllers.profile import (
    PASSWORD_POLICY_NOTE,
    ProfileController,
    _split_name,
)
from src.presentation.controllers.root_control import (
    MODULE_LABELS,
    RootControlController,
    limit_row,
)
from src.presentation.controllers.support_chat import (
    FAILURE_PREFIX,
    SupportChatController,
)
from src.presentation.widgets.worker_status import WorkerStatus
from src.shared.exceptions import KompasOSError

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())
STORE: Final = StoreId(uuid.uuid4())
NOW: Final = datetime(2026, 8, 10, 14, 10, tzinfo=UTC)


class _DeniedError(KompasOSError):
    user_message = "Bu əməliyyat üçün səlahiyyətiniz yoxdur."


class _Context:
    """`ApplicationContext.session()` müqaviləsinin minimal təkrarı."""

    def __init__(self, session: Any, *, tenant_id: TenantId = TENANT) -> None:
        self._session = session
        self.tenant_id = tenant_id
        self.opened = 0

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        self.opened += 1
        yield self._session


def _actor(employee_id: EmployeeId | None = None) -> Any:
    return type("_Actor", (), {"id": employee_id or EmployeeId(uuid.uuid4())})()


# --------------------------------------------------------------------------- #
# Kiosk körpüsü (`controllers/kiosk.py`)
# --------------------------------------------------------------------------- #


class _KioskLeaveRequests:
    def __init__(self, open_status: LeaveStatus | None = None) -> None:
        self.open_status = open_status

    def find_open_for_employee(self, employee_id: EmployeeId) -> Any:
        if self.open_status is None:
            return None
        return type("_Leave", (), {"status": self.open_status})()


class _KioskAttendance:
    def __init__(self, status: CheckInStatus | None = None) -> None:
        self.status = status

    def get_for_day(self, employee_id: EmployeeId, work_date: date) -> Any:
        if self.status is None:
            return None
        return type("_Record", (), {"status": self.status})()


class _KioskUow:
    def __init__(
        self,
        *,
        leave_status: LeaveStatus | None = None,
        check_in: CheckInStatus | None = None,
    ) -> None:
        self.leave_requests = _KioskLeaveRequests(leave_status)
        self.attendance = _KioskAttendance(check_in)


class _KioskUseCase:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._error = error

    def _run(self, **kwargs: Any) -> None:
        if self._error is not None:
            raise self._error
        self.calls.append(kwargs)

    start_day = _run
    request_leave = _run
    claim_return = _run


class _KioskFaceGate:
    """`FaceVerificationUseCase` müqaviləsinin minimal təkrarı (facecontrol.md).

    DEFOLT `NOT_APPLICABLE`: mövcud kiosk testlərinin sualı üz təsdiqi DEYİL
    (commit, status, istisna udulması) və həmin suallar Face Control-dan ƏVVƏL
    də eyni cavabı verməlidir. `NOT_APPLICABLE` yolu heç nə yazmır və heç nə
    bloklamır — yəni sahtə köhnə davranışın DƏQİQ eynisini modelləşdirir.

    REAL `FaceGateDecision` QAYTARILIR, öz uydurma tipimiz yox: `face_result_row`
    onun sahələrini oxuyur və sahtə tip həmin çevirməni yalançı-yaşıl edərdi.
    """

    def __init__(
        self,
        *,
        outcome: FaceGateOutcome = FaceGateOutcome.NOT_APPLICABLE,
        error: Exception | None = None,
    ) -> None:
        self._outcome = outcome
        self._error = error
        self.calls: list[Any] = []

    def verify(self, *, tenant_id: Any, employee: Any, trigger_context: Any) -> FaceGateDecision:
        self.calls.append(trigger_context)
        if self._error is not None:
            raise self._error
        return FaceGateDecision(
            employee_id=employee.id,
            trigger_context=trigger_context,
            outcome=self._outcome,
            message_az="Üz təsdiqi nəticəsi",
        )


class _KioskSession:
    def __init__(
        self,
        *,
        leave_status: LeaveStatus | None = None,
        check_in: CheckInStatus | None = None,
        morning_error: Exception | None = None,
        leave_error: Exception | None = None,
        face_outcome: FaceGateOutcome = FaceGateOutcome.NOT_APPLICABLE,
        face_error: Exception | None = None,
    ) -> None:
        self.tenant_id = TENANT
        self.uow = _KioskUow(leave_status=leave_status, check_in=check_in)
        self.morning_check_in = _KioskUseCase(error=morning_error)
        self.leave_verification = _KioskUseCase(error=leave_error)
        self.face_verification = _KioskFaceGate(outcome=face_outcome, error=face_error)
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _kiosk(session: _KioskSession) -> tuple[KioskController, _Context]:
    context = _Context(session)
    return KioskController(context, store_id=STORE), context  # type: ignore[arg-type]


def test_kiosk_outcome_failed_is_the_inverse_of_succeeded() -> None:
    assert KioskOutcome(succeeded=False).failed is True
    assert KioskOutcome(succeeded=True).failed is False


def test_start_day_commits_and_returns_the_recomputed_status() -> None:
    """Commit UNUDULARSA giriş sorğusu heç vaxt operatorun növbəsinə düşməz."""
    session = _KioskSession(check_in=CheckInStatus.PENDING_VERIFICATION)
    controller, _ = _kiosk(session)
    employee = _actor()

    outcome = controller.start_day(employee)  # type: ignore[arg-type]

    assert outcome.succeeded is True
    assert outcome.message == "Giriş sorğunuz göndərildi."
    assert outcome.status is WorkerStatus.PENDING_CHECK_IN
    assert session.commits == 1
    assert session.morning_check_in.calls[0]["store_id"] == STORE


def test_leave_request_passes_the_in_store_flag_to_the_use_case() -> None:
    """STEP 1 yalnız `🟢 Mağazada` statusundan işə düşür — şərt AÇIQ ötürülür."""
    session = _KioskSession(leave_status=LeaveStatus.OUTSIDE)
    controller, _ = _kiosk(session)
    employee = _actor()

    outcome = controller.request_leave(employee)  # type: ignore[arg-type]

    assert outcome.succeeded is True
    assert session.leave_verification.calls[0]["employee_is_in_store"] is True
    assert outcome.status is WorkerStatus.OUTSIDE


def test_claim_return_reports_the_pending_return_status() -> None:
    session = _KioskSession(leave_status=LeaveStatus.PENDING_RETURN_VERIFICATION)
    controller, _ = _kiosk(session)

    outcome = controller.claim_return(_actor())  # type: ignore[arg-type]

    assert outcome.succeeded is True
    assert outcome.status is WorkerStatus.PENDING_RETURN
    assert session.commits == 1


def test_a_domain_rule_error_becomes_a_message_not_an_exception() -> None:
    """Kiosk PAYLAŞILAN cihazdır — istisna ekrana çıxsa mağaza bloklanardı."""
    session = _KioskSession(
        leave_error=OperationNotPermittedError("STEP 1 yalnız mağazadan işə düşür")
    )
    controller, _ = _kiosk(session)

    outcome = controller.request_leave(_actor())  # type: ignore[arg-type]

    assert outcome.failed is True
    assert outcome.message, "Səbəb istifadəçiyə GÖSTƏRİLMƏLİDİR"
    assert session.commits == 0


def test_an_unexpected_error_is_reported_as_a_generic_message() -> None:
    """Gözlənilməz xəta texniki detalı SIZDIRMIR, lakin uğursuzluğu gizlətmir."""
    session = _KioskSession(morning_error=RuntimeError("bağlantı qırıldı"))
    controller, _ = _kiosk(session)

    outcome = controller.start_day(_actor())  # type: ignore[arg-type]

    assert outcome.failed is True
    assert outcome.message == "Əməliyyat tamamlanmadı. Yenidən cəhd edin."
    assert "bağlantı" not in outcome.message
    assert session.commits == 0


def test_status_is_read_fresh_on_every_call() -> None:
    """Status KEŞLƏNMİR — operator təsdiqlədikdən sonra düymə dəyişməlidir."""
    session = _KioskSession()
    controller, context = _kiosk(session)
    employee_id = EmployeeId(uuid.uuid4())

    assert controller.status_for(employee_id) is WorkerStatus.NOT_STARTED

    session.uow.attendance.status = CheckInStatus.VERIFIED
    assert controller.status_for(employee_id) is WorkerStatus.VERIFIED
    assert context.opened == 2, "Hər sorğu üçün YENİ sessiya açılmalıdır"


def test_leave_status_outranks_the_attendance_status() -> None:
    """İcazədə olan işçi «Mağazada» görünsəydi operator qayıdışı gözləməzdi."""
    session = _KioskSession(check_in=CheckInStatus.VERIFIED, leave_status=LeaveStatus.OUTSIDE)
    controller, _ = _kiosk(session)

    assert controller.status_for(EmployeeId(uuid.uuid4())) is WorkerStatus.OUTSIDE


class _FailingPinUow:
    """`find_by_pin_candidates` çökür — PIN yolu istisna ATMAMALIDIR."""

    class _Employees:
        def find_by_pin_candidates(self, tenant_id: TenantId, store_id: StoreId) -> list[Any]:
            raise RuntimeError("employees cədvəli əlçatmazdır")

    def __init__(self) -> None:
        self.employees = self._Employees()


class _PinSession:
    def __init__(self) -> None:
        self.tenant_id = TENANT
        self.uow = _FailingPinUow()
        self.limits: Any = None
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def test_a_broken_pin_lookup_never_crashes_the_kiosk_screen() -> None:
    session = _PinSession()
    controller = KioskController(_Context(session), store_id=STORE)  # type: ignore[arg-type]

    outcome = controller.authenticate("1234")

    assert outcome.failed is True
    assert outcome.message == "Sistem xətası. Bir az sonra yenidən cəhd edin."


# --------------------------------------------------------------------------- #
# Kamera növbəsi (`controllers/camera_queue.py`)
# --------------------------------------------------------------------------- #


class _QueueScreen:
    theme: Any = None

    def __init__(self) -> None:
        self.errors: list[tuple[str, str]] = []

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)


class _Connection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.queries: list[str] = []

    def execute(self, sql: str, params: Any = None) -> _Cursor:
        self.queries.append(sql)
        return _Cursor(self.rows)


class _QueueRepo:
    def __init__(self, item: Any = None) -> None:
        self.item = item
        self.requested: list[Any] = []

    def get(self, entity_id: Any) -> Any:
        self.requested.append(entity_id)
        return self.item


class _QueueEmployees:
    def __init__(self, employee: Any = None) -> None:
        self.employee = employee

    def get(self, employee_id: Any) -> Any:
        return self.employee


class _QueueUow:
    def __init__(
        self,
        *,
        leave: Any = None,
        record: Any = None,
        employee: Any = None,
        rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.leave_requests = _QueueRepo(leave)
        self.attendance = _QueueRepo(record)
        self.employees = _QueueEmployees(employee)
        self.connection = _Connection(rows)


class _Limits:
    def __init__(self, value: int) -> None:
        self.value = value

    def get_int(self, tenant_id: TenantId, key: str, default: int) -> int:
        return self.value


class _Recorder:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._error = error

    def __getattr__(self, name: str) -> Any:
        def _call(**kwargs: Any) -> None:
            if self._error is not None:
                raise self._error
            self.calls.append({"method": name, **kwargs})

        return _call


class _QueueSession:
    def __init__(
        self,
        *,
        uow: _QueueUow,
        threshold: int = 30,
        morning_error: Exception | None = None,
    ) -> None:
        self.tenant_id = TENANT
        self.uow = uow
        self.limits = _Limits(threshold)
        self.morning_check_in = _Recorder(error=morning_error)
        self.leave_verification = _Recorder()
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _leave_request() -> Any:
    return type(
        "_Request",
        (),
        {
            "id": LeaveRequestId(uuid.uuid4()),
            "employee_id": EmployeeId(uuid.uuid4()),
            "store_id": STORE,
            "return_claimed_time": NOW,
            "requested_time": NOW - timedelta(minutes=45),
        },
    )()


def _attendance_record() -> Any:
    return type(
        "_Record",
        (),
        {
            "id": AttendanceRecordId(uuid.uuid4()),
            "employee_id": EmployeeId(uuid.uuid4()),
            "work_date": date(2026, 8, 10),
        },
    )()


def test_approving_an_attendance_row_calls_the_morning_check_in_use_case() -> None:
    """Növbə BİRLƏŞMİŞDİR — icazə sorğusu yoxdursa davamiyyət qeydi yoxlanılır."""
    record = _attendance_record()
    session = _QueueSession(uow=_QueueUow(leave=None, record=record))
    controller = CameraQueueController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _QueueScreen()

    controller._on_approve(screen, str(uuid.uuid4()))  # type: ignore[arg-type]

    assert session.morning_check_in.calls[0]["method"] == "verify"
    assert session.morning_check_in.calls[0]["employee_id"] == record.employee_id
    assert session.commits == 1
    assert screen.errors == []


def test_a_leave_row_cannot_be_rejected_and_the_reason_is_explained() -> None:
    """Qayıdış təsdiqində «rədd» anlayışı yoxdur — sükutla keçilmir."""
    session = _QueueSession(uow=_QueueUow(leave=_leave_request()))
    controller = CameraQueueController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _QueueScreen()

    controller._run(  # type: ignore[arg-type]
        screen,
        request_id=str(uuid.uuid4()),
        leave_action=None,
        attendance_action=lambda session, record: None,
        failure_title="Rədd yazılmadı",
    )

    assert screen.errors[0][0] == "Bu sətir rədd edilə bilməz"
    assert session.commits == 0


def test_a_row_that_disappeared_asks_for_a_refresh_instead_of_crashing() -> None:
    """Sərhəd: nə icazə sorğusu, nə davamiyyət qeydi — `KeyError` YOX, mesaj."""
    session = _QueueSession(uow=_QueueUow(leave=None, record=None))
    controller = CameraQueueController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _QueueScreen()

    controller._on_approve(screen, str(uuid.uuid4()))  # type: ignore[arg-type]

    assert screen.errors == [("Sorğu tapılmadı", "Bu sətir artıq emal edilib. Növbəni yeniləyin.")]
    assert session.commits == 0


def test_a_denied_verification_shows_the_domain_reason() -> None:
    session = _QueueSession(
        uow=_QueueUow(leave=None, record=_attendance_record()),
        morning_error=_DeniedError("flag yoxdur"),
    )
    controller = CameraQueueController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _QueueScreen()

    controller._on_approve(screen, str(uuid.uuid4()))  # type: ignore[arg-type]

    assert screen.errors == [("Təsdiq yazılmadı", "Bu əməliyyat üçün səlahiyyətiniz yoxdur.")]
    assert session.commits == 0


def test_an_unexpected_queue_failure_is_reported_without_technical_detail() -> None:
    session = _QueueSession(
        uow=_QueueUow(leave=None, record=_attendance_record()),
        morning_error=RuntimeError("psycopg: bağlantı qırıldı"),
    )
    controller = CameraQueueController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _QueueScreen()

    controller._on_approve(screen, str(uuid.uuid4()))  # type: ignore[arg-type]

    assert screen.errors[0] == (
        "Təsdiq yazılmadı",
        "Əməliyyat tamamlanmadı. Yenidən cəhd edin.",
    )
    assert "psycopg" not in screen.errors[0][1]


def test_a_malformed_request_id_is_handled_as_a_failure_not_a_crash() -> None:
    """`uuid.UUID("abc")` `ValueError` atır — ekran çökməməlidir."""
    session = _QueueSession(uow=_QueueUow())
    controller = CameraQueueController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _QueueScreen()

    controller._on_approve(screen, "bu-uuid-deyil")  # type: ignore[arg-type]

    assert screen.errors[0][0] == "Təsdiq yazılmadı"


def test_the_override_dialog_reads_the_threshold_from_system_limits() -> None:
    """Ekran və use case EYNİ mənbədən oxumalıdır — yoxsa ekran yalan danışar."""
    request = _leave_request()
    employee = type("_E", (), {"full_name": "Aysel Quliyeva"})()
    session = _QueueSession(
        uow=_QueueUow(leave=request, employee=employee, rows=[{"name": "Bakı — Nizami"}]),
        threshold=45,
    )
    controller = CameraQueueController(_Context(session), _actor())  # type: ignore[arg-type]

    details = controller._load(str(uuid.uuid4()))

    assert details is not None
    assert details["threshold_minutes"] == 45
    assert details["employee_name"] == "Aysel Quliyeva"
    assert details["store_name"] == "Bakı — Nizami"
    assert details["reference_time"] == request.return_claimed_time


def test_unknown_employee_and_store_fall_back_to_short_identifiers() -> None:
    """Ad tapılmasa sətir BOŞ qalmır — qısaldılmış ID göstərilir."""
    request = _leave_request()
    session = _QueueSession(uow=_QueueUow(leave=request, employee=None, rows=[]))
    controller = CameraQueueController(_Context(session), _actor())  # type: ignore[arg-type]

    details = controller._load(str(uuid.uuid4()))

    assert details is not None
    assert details["employee_name"] == f"#{str(request.employee_id)[:8]}"
    assert details["store_name"] == f"#{str(STORE)[:8]}"


def test_adjustment_of_an_attendance_row_is_refused_with_a_reason() -> None:
    """Manual vaxt düzəlişi YALNIZ qayıdış təsdiqinə aiddir (modul başlığı)."""
    session = _QueueSession(uow=_QueueUow(leave=None))
    controller = CameraQueueController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _QueueScreen()

    controller._on_adjust(screen, str(uuid.uuid4()))  # type: ignore[arg-type]

    assert screen.errors == [
        (
            "Bu sətir üçün düzəliş yoxdur",
            "Manual vaxt düzəlişi yalnız qayıdış təsdiqinə tətbiq olunur.",
        )
    ]


def test_adjustment_load_failure_is_shown_not_swallowed() -> None:
    session = _QueueSession(uow=_QueueUow())
    controller = CameraQueueController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _QueueScreen()

    controller._on_adjust(screen, "bu-uuid-deyil")  # type: ignore[arg-type]

    assert screen.errors[0][0] == "Düzəliş açıla bilmədi"


def test_a_bad_time_string_never_reaches_the_use_case() -> None:
    """Sərhəd: format SS:DD deyilsə yazı BAŞLAMIR."""
    session = _QueueSession(uow=_QueueUow(leave=_leave_request()))
    controller = CameraQueueController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _QueueScreen()

    controller._submit(  # type: ignore[arg-type]
        screen,
        request_id=str(uuid.uuid4()),
        time_text="25:99",
        reason="Kameradan baxdım",
        reference=NOW,
    )

    assert screen.errors == [("Vaxt oxunmadı", "Vaxt formatı SS:DD olmalıdır.")]
    assert session.leave_verification.calls == []
    assert session.commits == 0


def test_a_valid_override_is_written_and_committed() -> None:
    session = _QueueSession(uow=_QueueUow(leave=_leave_request()))
    controller = CameraQueueController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _QueueScreen()

    controller._submit(  # type: ignore[arg-type]
        screen,
        request_id=str(uuid.uuid4()),
        time_text="13:40",
        reason="Kamera qeydində 13:40 görünür",
        reference=NOW,
    )

    assert session.commits == 1
    call = session.leave_verification.calls[0]
    assert call["method"] == "apply_override"
    assert call["reason"] == "Kamera qeydində 13:40 görünür"
    assert screen.errors == []


def test_override_denial_keeps_the_screen_honest() -> None:
    session = _QueueSession(uow=_QueueUow(leave=_leave_request()))
    session.leave_verification = _Recorder(error=_DeniedError("flag yoxdur"))
    controller = CameraQueueController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _QueueScreen()

    controller._submit(  # type: ignore[arg-type]
        screen,
        request_id=str(uuid.uuid4()),
        time_text="13:40",
        reason="Səbəb",
        reference=NOW,
    )

    assert screen.errors == [("Düzəliş yazılmadı", "Bu əməliyyat üçün səlahiyyətiniz yoxdur.")]
    assert session.commits == 0


def test_the_override_never_moves_the_record_to_another_day() -> None:
    """Düzəliş çox vaxt GERİYƏ olur — «əvvəldirsə sabaha keçir» məntiqi YOXDUR."""
    reference = datetime(2026, 8, 10, 14, 10, tzinfo=UTC)

    combined = _combine(reference, "13:40")

    assert combined is not None
    assert combined.astimezone().date() == reference.astimezone().date()
    assert combined < reference


@pytest.mark.parametrize("text", ["", "  ", "13.40", "25:00", "13:60", "abc"])
def test_unparsable_times_return_none(text: str) -> None:
    assert _combine(NOW, text) is None


def test_a_padded_time_string_is_still_accepted() -> None:
    """Sərhəd: kənar boşluqlar operatorun səhvi deyil, formatın hissəsidir."""
    assert _combine(NOW, "  09:05  ") is not None


# --------------------------------------------------------------------------- #
# ROOT paneli (`controllers/root_control.py`)
# --------------------------------------------------------------------------- #


class _RootScreen:
    def __init__(self) -> None:
        self.limits: list[Any] = []
        #: «Fasilə Parametrləri» bölməsi (nahar.md) — AYRICA saxlanılır,
        #: çünki testlər ümumi siyahının həmin dörd açarı DAŞIMADIĞINI də
        #: yoxlaya bilməlidir (hər açar yalnız bir bölmədə redaktə olunur).
        self.break_limits: list[Any] = []
        self.modules: list[Any] = []
        self.registry: list[Any] = []
        self.errors: list[tuple[str, str]] = []
        self.rejected: list[str] = []
        #: Face Control bölməsi (facecontrol.md bənd 15 + 7/12) — AYRICA
        #: saxlanılır, çünki mağaza əhatəsi `collected()["limits"]` ad
        #: məkanına DÜŞMÜR (ayrı cədvəldir).
        self.face_scope: list[Any] = []
        self.face_tolerance: dict[str, str] = {}
        self.face_rejected: list[str] = []
        #: Brendinq bölməsi (TENANT-1 Faza 2) — `face_scope` ilə eyni
        #: səbəbdən AYRICA: `tenant_branding` `system_limits` sətri DEYİL.
        self.branding: tuple[str, str, str] | None = None
        self.branding_status: str = ""

    def set_limits(self, rows: list[Any]) -> None:
        self.limits = rows

    def set_break_limits(self, rows: list[Any]) -> None:
        self.break_limits = rows

    def set_face_scope(self, rows: list[Any]) -> None:
        self.face_scope = rows

    def set_face_tolerance(self, tolerance: dict[str, str]) -> None:
        self.face_tolerance = tolerance

    def reject_face_scope_change(self, store_id: str) -> None:
        self.face_rejected.append(store_id)

    def set_branding(self, *, company_name: str, accent_color: str, warning: str = "") -> None:
        self.branding = (company_name, accent_color, warning)

    def set_branding_status(self, message: str) -> None:
        self.branding_status = message

    def set_modules(self, rows: list[Any]) -> None:
        self.modules = rows

    def set_registry(self, rows: list[Any]) -> None:
        self.registry = rows

    def reject_module_change(self, module_key: str) -> None:
        self.rejected.append(module_key)

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


class _LimitView:
    """`RootControlUseCase.LimitView`-un sahtəsi.

    İzah/diapazon sahələri DEFOLTLA BOŞDUR: kontroller onları ötürsə də,
    bu testlərin sualı başqadır (yazı yolu, boş dəyər, registry xətası) və
    boş izah `LIMIT_LABELS` ehtiyat yolunu işə salır — yəni sahtə real
    davranışın ən dar variantını modelləşdirir.
    """

    def __init__(
        self,
        key: str,
        value: str,
        *,
        description_az: str = "",
        min_value: str | None = None,
        max_value: str | None = None,
        is_stored: bool = True,
    ) -> None:
        self.key = key
        self.value = value
        self.description_az = description_az
        self.min_value = min_value
        self.max_value = max_value
        self.is_stored = is_stored


class _ModuleView:
    def __init__(self, key: str, *, enabled: bool = True, structural: bool = False) -> None:
        self.module_key = key
        self.is_enabled = enabled
        self.is_structural = structural


class _RootUseCase:
    def __init__(
        self,
        *,
        limits: list[_LimitView] | None = None,
        modules: list[_ModuleView] | None = None,
        flags: list[PermissionFlag] | None = None,
        flags_error: Exception | None = None,
        set_error: Exception | None = None,
    ) -> None:
        self._limits = limits or []
        self._modules = modules or []
        self._flags = flags or []
        self._flags_error = flags_error
        self._set_error = set_error
        self.written: list[tuple[str, str]] = []
        self.toggled: list[dict[str, Any]] = []
        self.created: list[PermissionFlag] = []

    def list_limits(self, *, tenant_id: Any, actor: Any) -> list[_LimitView]:
        return list(self._limits)

    def list_modules(self, *, tenant_id: Any, actor: Any) -> list[_ModuleView]:
        return list(self._modules)

    def list_flags(self, *, actor: Any) -> list[PermissionFlag]:
        if self._flags_error is not None:
            raise self._flags_error
        return list(self._flags)

    def set_limit(self, *, tenant_id: Any, actor: Any, key: Any, value: str) -> Any:
        if self._set_error is not None:
            raise self._set_error
        self.written.append((key.value, value))
        self._limits = [
            _LimitView(key.value, value) if view.key == key.value else view for view in self._limits
        ]
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
        if self._set_error is not None:
            raise self._set_error
        self.toggled.append(
            {"module_key": module_key, "enabled": enabled, "confirmation": confirmation}
        )
        return None

    def create_flag(self, *, tenant_id: Any, actor: Any, flag: PermissionFlag) -> Any:
        if self._set_error is not None:
            raise self._set_error
        self.created.append(flag)
        return flag


class _FaceScopeRepo:
    """`FaceStoreScopeRepository` müqaviləsinin minimal təkrarı (bənd 15)."""

    def __init__(self, active: set[StoreId] | None = None) -> None:
        self._active = active or set()
        self.written: list[tuple[StoreId, bool]] = []

    def active_scope(self, tenant_id: Any) -> FaceStoreScope:
        return FaceStoreScope(store_ids=frozenset(self._active))

    def set_active(
        self, tenant_id: Any, store_id: StoreId, *, active: bool, changed_by: Any
    ) -> None:
        self.written.append((store_id, active))


class _RootConnection:
    """Mağaza siyahısı sorğusu — `face_scope_rows` onu birbaşa oxuyur."""

    def __init__(self, stores: list[dict[str, Any]]) -> None:
        self._stores = stores

    def execute(self, sql: str, params: Any = None) -> Any:
        return type("_Cursor", (), {"fetchall": lambda _self: list(self._stores)})()


class _RootAudit:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.records.append(kwargs)


class _RootUow:
    def __init__(self, stores: list[dict[str, Any]], scope: _FaceScopeRepo) -> None:
        self.connection = _RootConnection(stores)
        self.audit = _RootAudit()
        self._scope = scope

    def repository(self, name: str) -> Any:
        assert name == "face_store_scope"
        return self._scope


class _RootLimits:
    """`SystemLimits` portunun oxu tərəfi — Face Control hədləri üçün."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = values or {}

    def get_str(self, tenant_id: Any, key: str, default: str) -> str:
        return self._values.get(key, default)

    def get_int(self, tenant_id: Any, key: str, default: int) -> int:
        return int(self._values.get(key, default))


class _RootSession:
    def __init__(
        self,
        use_case: _RootUseCase,
        *,
        stores: list[dict[str, Any]] | None = None,
        scope: _FaceScopeRepo | None = None,
        limits: dict[str, str] | None = None,
    ) -> None:
        self.tenant_id = TENANT
        self.root_control = use_case
        self.face_scope = scope or _FaceScopeRepo()
        self.uow = _RootUow(stores or [], self.face_scope)
        self.limits = _RootLimits(limits)
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _root(
    use_case: _RootUseCase,
    *,
    stores: list[dict[str, Any]] | None = None,
    scope: _FaceScopeRepo | None = None,
    limits: dict[str, str] | None = None,
    actor: Any = None,
) -> tuple[RootControlController, _RootSession]:
    session = _RootSession(use_case, stores=stores, scope=scope, limits=limits)
    controller = RootControlController(
        _Context(session),  # type: ignore[arg-type]
        actor or _actor(),
    )
    return controller, session


def test_limit_row_widens_the_range_when_the_stored_value_is_out_of_bounds() -> None:
    """QSpinBox dəyəri KƏSSƏYDİ Root bazadakından fərqli rəqəm görərdi."""
    key, label, value, low, high, suffix = limit_row(
        SystemLimitKey.LATE_TOLERANCE_MINUTES.value, "999"
    )

    assert key == SystemLimitKey.LATE_TOLERANCE_MINUTES.value
    assert label == "Gecikmə tolerantlığı"
    assert (value, low, high, suffix) == (999, 0, 999, "dəq")


def test_limit_row_keeps_a_non_numeric_value_as_text() -> None:
    """«LEAVE_TYPE» və «0.00» ədəd deyil — sahə mətn olaraq qurulur."""
    key, label, value, low, high, _ = limit_row(
        SystemLimitKey.LEAVE_ALLOWANCE_SOURCE.value, "LEAVE_TYPE"
    )

    assert key == SystemLimitKey.LEAVE_ALLOWANCE_SOURCE.value
    assert label == "İcazə güzəştinin mənbəyi"
    assert (value, low, high) == ("LEAVE_TYPE", 0, 0)


def test_an_unknown_limit_key_is_shown_under_its_own_name() -> None:
    """Bazada köhnə sətir qala bilər — GİZLƏTMƏK onu görünməz problem edərdi."""
    assert limit_row("kohne_acar", "5") == ("kohne_acar", "kohne_acar", "5", 0, 0, "")


def test_limit_row_prefers_the_database_description_to_the_curated_table() -> None:
    """Etiketin mənbəyi `system_limits.description_az`-dır (kompas1.md Faza 9).

    ƏL İLƏ YAZILMIŞ CƏDVƏL NİYƏ İKİNCİ SIRADADIR: `LIMIT_LABELS` 17 sətirdir,
    `SystemLimitKey` isə 166 — yəni cədvəl ilk mənbə qalsaydı, hər yeni ROOT
    parametri ekranda TEXNİKİ KODU ilə görünərdi. Baza sətri isə hər
    miqrasiyada məcburi seed edilir (aşağıdakı paritet testi bunu qapıya
    çevirib), ona görə üstündür.
    """
    key, label, value, low, high, suffix = limit_row(
        SystemLimitKey.LATE_TOLERANCE_MINUTES.value,
        "12",
        description_az="Gecikmə tolerantlığı (bazadan)",
        min_value="0",
        max_value="60",
    )

    assert key == SystemLimitKey.LATE_TOLERANCE_MINUTES.value
    assert label == "Gecikmə tolerantlığı (bazadan)"
    # Diapazon da bazadan gəlir — `LIMIT_LABELS` 0–240 deyir, sətir 0–60.
    assert (value, low, high, suffix) == (12, 0, 60, "dəq")


def test_limit_row_ignores_a_decimal_bound_that_no_spin_box_can_show() -> None:
    """`min_value = "0.1"` ədəd deyil — ehtiyat diapazon qalır, sətir çökmür."""
    _, _, value, low, high, _ = limit_row(
        SystemLimitKey.LATE_TOLERANCE_MINUTES.value,
        "30",
        description_az="Gecikmə tolerantlığı",
        min_value="0.1",
        max_value="240",
    )

    assert (value, low, high) == (30, 0, 240)


def test_limit_row_flags_a_limit_that_is_not_stored_in_the_database() -> None:
    """Defoltla tamamlanan sətir GÖRÜNÜR, amma «hələ yazılmayıb» kimi.

    `LimitView.is_stored` mətn yerinə bayraqdır: vəziyyəti `description_az`-a
    yazsaydıq, bütün belə sətirlər ekranda EYNİ adla görünərdi.
    """
    _, label, _, _, _, _ = limit_row(
        SystemLimitKey.LATE_TOLERANCE_MINUTES.value, "30", is_stored=False
    )

    assert label == "Gecikmə tolerantlığı — defolt (bazada yazılmayıb)"


def test_every_feature_module_has_an_azerbaijani_label() -> None:
    """Bölmə 9 — etiketsiz modul ekranda ingiliscə açar kimi görünərdi."""
    missing = [module.value for module in FeatureModule if module not in MODULE_LABELS]

    assert missing == [], f"Etiketi olmayan modul(lar): {missing}"


def test_the_panel_shows_the_reason_instead_of_an_empty_screen() -> None:
    """Boş panel «limit yoxdur» kimi oxunardı — səbəb GÖRÜNMƏLİDİR."""
    use_case = _RootUseCase()
    session = _RootSession(use_case)

    class _Broken(_Context):
        @contextmanager
        def session(self, *, user_id: Any = None) -> Any:
            raise _DeniedError("can_manage_system_limits yoxdur")
            yield  # pragma: no cover

    controller = RootControlController(_Broken(session), _actor())  # type: ignore[arg-type]
    screen = _RootScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.errors == [("Panel açıla bilmədi", "Bu əməliyyat üçün səlahiyyətiniz yoxdur.")]


def test_the_registry_section_stays_empty_without_closing_the_whole_panel() -> None:
    """`can_manage_permissions` yoxdursa YALNIZ registry boş qalır."""
    from src.application.use_cases.root_control import RootControlError

    use_case = _RootUseCase(
        limits=[_LimitView(SystemLimitKey.LATE_TOLERANCE_MINUTES.value, "10")],
        modules=[_ModuleView(FeatureModule.FINE_MODULE.value)],
        flags_error=RootControlError("registry bağlıdır"),
    )
    controller, _ = _root(use_case)
    screen = _RootScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.registry == []
    assert screen.limits, "Limitlər bölməsi AÇIQ qalmalıdır"
    assert screen.modules[0][1] == "Cərimə modulu"
    assert screen.errors == []


def test_hardlocked_flags_are_marked_in_the_registry() -> None:
    use_case = _RootUseCase(
        flags=[
            PermissionFlag(code="can_export_reports", category="SISTEM"),
            PermissionFlag(
                code="can_manage_permissions",
                category="ICAZE",
                hardlock=HardlockLevel.ROOT_ONLY,
            ),
        ]
    )
    controller, _ = _root(use_case)
    screen = _RootScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.registry == [("can_export_reports", False), ("can_manage_permissions", True)]


def test_only_changed_limits_are_written() -> None:
    """Hər klik 12 audit sətri yaratsaydı jurnal real dəyişikliyi gizlədərdi."""
    use_case = _RootUseCase(
        limits=[
            _LimitView(SystemLimitKey.LATE_TOLERANCE_MINUTES.value, "10"),
            _LimitView(SystemLimitKey.PIN_LOCKOUT_MINUTES.value, "15"),
        ]
    )
    controller, session = _root(use_case)
    screen = _RootScreen()

    controller._on_applied(  # type: ignore[arg-type]
        screen,
        {
            "limits": {
                SystemLimitKey.LATE_TOLERANCE_MINUTES.value: "10",
                SystemLimitKey.PIN_LOCKOUT_MINUTES.value: "20",
            }
        },
    )

    assert use_case.written == [(SystemLimitKey.PIN_LOCKOUT_MINUTES.value, "20")]
    assert session.commits == 1


def test_an_unchanged_form_writes_nothing_and_does_not_commit() -> None:
    """Sərhəd: boş `limits` sözlüyü — sessiya belə açılmamalıdır."""
    use_case = _RootUseCase()
    controller, session = _root(use_case)
    screen = _RootScreen()

    controller._on_applied(screen, {"limits": {}})  # type: ignore[arg-type]
    controller._on_applied(screen, None)  # type: ignore[arg-type]

    assert use_case.written == []
    assert session.commits == 0


def test_unknown_and_blank_limit_values_are_skipped_silently() -> None:
    """Naməlum açar və boş dəyər yazılmır, lakin QALAN sətir yazılır."""
    use_case = _RootUseCase(limits=[_LimitView(SystemLimitKey.PIN_LOCKOUT_MINUTES.value, "15")])
    controller, _ = _root(use_case)
    screen = _RootScreen()

    controller._on_applied(  # type: ignore[arg-type]
        screen,
        {
            "limits": {
                "kohne_acar": "7",
                SystemLimitKey.LATE_TOLERANCE_MINUTES.value: "   ",
                SystemLimitKey.PIN_LOCKOUT_MINUTES.value: "20",
            }
        },
    )

    assert use_case.written == [(SystemLimitKey.PIN_LOCKOUT_MINUTES.value, "20")]
    assert screen.errors == []


def test_a_refused_limit_change_is_explained_and_not_committed() -> None:
    use_case = _RootUseCase(
        limits=[_LimitView(SystemLimitKey.PIN_LOCKOUT_MINUTES.value, "15")],
        set_error=_DeniedError("flag yoxdur"),
    )
    controller, session = _root(use_case)
    screen = _RootScreen()

    controller._on_applied(  # type: ignore[arg-type]
        screen, {"limits": {SystemLimitKey.PIN_LOCKOUT_MINUTES.value: "20"}}
    )

    assert screen.errors == [("Limit yazıla bilmədi", "Bu əməliyyat üçün səlahiyyətiniz yoxdur.")]
    assert session.commits == 0


def test_an_unexpected_limit_failure_is_reported_generically() -> None:
    use_case = _RootUseCase(
        limits=[_LimitView(SystemLimitKey.PIN_LOCKOUT_MINUTES.value, "15")],
        set_error=RuntimeError("deadlock"),
    )
    controller, _ = _root(use_case)
    screen = _RootScreen()

    controller._on_applied(  # type: ignore[arg-type]
        screen, {"limits": {SystemLimitKey.PIN_LOCKOUT_MINUTES.value: "20"}}
    )

    assert screen.errors[0] == (
        "Limit yazıla bilmədi",
        "Dəyişiklik saxlanmadı. Yenidən cəhd edin.",
    )


def test_an_empty_confirmation_reaches_the_use_case_as_none() -> None:
    """Boş sətir «təsdiq verildi» sayılmamalıdır — `None` ötürülür."""
    use_case = _RootUseCase()
    controller, session = _root(use_case)
    screen = _RootScreen()

    controller._on_module_toggled(  # type: ignore[arg-type]
        screen, FeatureModule.TASK_ENGINE.value, enabled=False, confirmation=""
    )

    assert use_case.toggled == [
        {
            "module_key": FeatureModule.TASK_ENGINE.value,
            "enabled": False,
            "confirmation": None,
        }
    ]
    assert session.commits == 1


def test_a_refused_toggle_flips_the_switch_back_so_the_screen_never_lies() -> None:
    use_case = _RootUseCase(set_error=_DeniedError("struktur modul"))
    controller, session = _root(use_case)
    screen = _RootScreen()

    controller._on_module_toggled(  # type: ignore[arg-type]
        screen, FeatureModule.CAMERA_VERIFICATION.value, enabled=False, confirmation="ok"
    )

    assert screen.rejected == [FeatureModule.CAMERA_VERIFICATION.value]
    assert screen.errors[0][0] == "Modul dəyişdirilmədi"
    assert session.commits == 0


def test_an_unexpected_toggle_failure_also_flips_the_switch_back() -> None:
    use_case = _RootUseCase(set_error=RuntimeError("şəbəkə"))
    controller, _ = _root(use_case)
    screen = _RootScreen()

    controller._on_module_toggled(  # type: ignore[arg-type]
        screen, FeatureModule.SHIFT_SWAP.value, enabled=True, confirmation=""
    )

    assert screen.rejected == [FeatureModule.SHIFT_SWAP.value]
    assert screen.errors[0][1] == "Dəyişiklik saxlanmadı. Yenidən cəhd edin."


def test_a_new_flag_defaults_to_the_narrowest_hardlock() -> None:
    """Sistem yeni flag-in həssaslığını BİLMİR — ilkin dəyər ən qapalı olur."""
    use_case = _RootUseCase()
    controller, session = _root(use_case)
    screen = _RootScreen()

    controller._on_flag_created(  # type: ignore[arg-type]
        screen, "can_do_new_thing", "SISTEM", hardlock=True
    )

    assert use_case.created[0].hardlock is HardlockLevel.ROOT_ONLY
    assert session.commits == 1


def test_a_flag_without_hardlock_is_created_open() -> None:
    use_case = _RootUseCase()
    controller, _ = _root(use_case)
    screen = _RootScreen()

    controller._on_flag_created(  # type: ignore[arg-type]
        screen, "can_do_open_thing", "SISTEM", hardlock=False
    )

    assert use_case.created[0].hardlock is HardlockLevel.NONE


def test_an_invalid_flag_code_never_reaches_the_database() -> None:
    """`PermissionFlag` kodu özü yoxlayır — səbəb ekranda göstərilir."""
    use_case = _RootUseCase()
    controller, session = _root(use_case)
    screen = _RootScreen()

    controller._on_flag_created(screen, "Səhv Kod!", "SISTEM", hardlock=False)  # type: ignore[arg-type]

    assert use_case.created == []
    assert session.commits == 0
    assert screen.errors[0][0] == "İcazə yaradılmadı"


def test_a_refused_flag_creation_is_explained() -> None:
    use_case = _RootUseCase(set_error=_DeniedError("yalnız Root"))
    controller, session = _root(use_case)
    screen = _RootScreen()

    controller._on_flag_created(  # type: ignore[arg-type]
        screen, "can_do_new_thing", "SISTEM", hardlock=False
    )

    assert screen.errors == [("İcazə yaradılmadı", "Bu əməliyyat üçün səlahiyyətiniz yoxdur.")]
    assert session.commits == 0


# --------------------------------------------------------------------------- #
# Dəstək paneli (`controllers/support_chat.py`)
# --------------------------------------------------------------------------- #


class _ChatWidget:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bool]] = []
        self.unread: bool | None = None

    def add_message(self, text: str, *, outgoing: bool = False) -> None:
        self.messages.append((text, outgoing))

    def set_unread(self, has_unread: bool) -> None:
        self.unread = has_unread

    def selected_channel(self) -> Any:
        from src.domain.value_objects.support import SupportChannel

        return SupportChannel.TECHNICAL

    def is_urgent(self) -> bool:
        return False

    def pending_attachment(self) -> tuple[str, bytes] | None:
        return None


class _Message:
    def __init__(self, body: str, *, from_developer: bool) -> None:
        self.body = body
        self.is_from_developer = from_developer


class _Thread:
    def __init__(self, *, is_open: bool, messages: list[_Message]) -> None:
        self.is_open = is_open
        self.messages = messages
        self.ticket_id = uuid.uuid4()


class _Support:
    def __init__(
        self,
        *,
        available: bool = True,
        threads: list[_Thread] | None = None,
        unread: int = 0,
        load_error: Exception | None = None,
        mark_error: Exception | None = None,
        send_error: Exception | None = None,
    ) -> None:
        self._available = available
        self._threads = threads or []
        self._unread = unread
        self._load_error = load_error
        self._mark_error = mark_error
        self._send_error = send_error
        self.sent: list[str] = []
        self.marked: list[Any] = []

    def is_available(self, *, tenant_id: Any, actor: Any) -> bool:
        return self._available

    def threads(self, *, tenant_id: Any, actor: Any, channel: Any = None) -> list[_Thread]:
        if self._load_error is not None:
            raise self._load_error
        return list(self._threads)

    def unread_count(self, *, tenant_id: Any, actor: Any) -> int:
        # Nişan oxunuşu da EYNİ bağlantıdan keçir — «yükləmə uğursuzdur»
        # ssenarisi hər iki yolu bağlamalıdır, əks halda test yalnız
        # yarısını yoxlayardı.
        if self._load_error is not None:
            raise self._load_error
        return self._unread

    def mark_read(self, *, tenant_id: Any, actor: Any, ticket_id: Any) -> None:
        if self._mark_error is not None:
            raise self._mark_error
        self.marked.append(ticket_id)

    def send(self, *, tenant_id: Any, actor: Any, body: str, subject: str = "") -> Any:
        if self._send_error is not None:
            raise self._send_error
        self.sent.append(body)
        return None


class _ChatSession:
    def __init__(self, support: _Support) -> None:
        self.tenant_id = TENANT
        self.support = support
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _chat(support: _Support) -> tuple[SupportChatController, _ChatSession]:
    session = _ChatSession(support)
    return (
        SupportChatController(_Context(session), _actor()),  # type: ignore[arg-type]
        session,
    )


def test_the_open_thread_is_drawn_with_the_correct_bubble_direction() -> None:
    """Hazırlayıcının cavabı GƏLƏN, istifadəçinin mesajı ÇIXAN baloncuqdur."""
    thread = _Thread(
        is_open=True,
        messages=[
            _Message("Sumqayıt serveri cavab vermir", from_developer=False),
            _Message("Baxırıq, 1 saata cavab verəcəyik", from_developer=True),
        ],
    )
    controller, _ = _chat(_Support(threads=[thread], unread=2))
    widget = _ChatWidget()

    # CHAT-1: söhbət KANAL SEÇİLƏNDƏN sonra çəkilir; nişan isə seçimdən
    # ƏVVƏL, panel açılmamış da qoyulur (bax `controllers/support_chat.py`).
    controller.refresh_badge(widget)  # type: ignore[arg-type]
    controller.open_channel(widget, "TECHNICAL")  # type: ignore[arg-type]

    assert widget.messages == [
        ("Sumqayıt serveri cavab vermir", True),
        ("Baxırıq, 1 saata cavab verəcəyik", False),
    ]
    assert widget.unread is True


def test_a_closed_thread_is_not_drawn() -> None:
    """Sərhəd: yalnız BAĞLI müraciət var — panel boş açılır."""
    closed = _Thread(is_open=False, messages=[_Message("köhnə", from_developer=False)])
    controller, _ = _chat(_Support(threads=[closed]))
    widget = _ChatWidget()

    controller.refresh_badge(widget)  # type: ignore[arg-type]
    controller.open_channel(widget, "TECHNICAL")  # type: ignore[arg-type]

    assert widget.messages == []
    assert widget.unread is False


def test_an_unavailable_support_module_leaves_the_panel_untouched() -> None:
    """Modul söndürülübsə panel çökmür, sadəcə heç nə yazmır."""
    controller, _ = _chat(_Support(available=False, unread=5))
    widget = _ChatWidget()

    controller.refresh_badge(widget)  # type: ignore[arg-type]

    assert widget.messages == []
    assert widget.unread is None, "Əlçatmaz modul nişanı da təyin etməməlidir"


def test_a_failed_thread_load_never_crashes_the_overlay() -> None:
    controller, _ = _chat(_Support(load_error=RuntimeError("bağlantı yoxdur")))
    widget = _ChatWidget()

    controller.refresh_badge(widget)  # type: ignore[arg-type]

    assert widget.messages == []
    assert widget.unread is None


def test_opening_the_panel_marks_the_open_thread_as_read() -> None:
    thread = _Thread(is_open=True, messages=[_Message("salam", from_developer=True)])
    support = _Support(threads=[thread], unread=1)
    controller, session = _chat(support)
    widget = _ChatWidget()

    controller._on_opened(widget)  # type: ignore[arg-type]

    assert support.marked == [thread.ticket_id]
    assert session.commits == 1
    assert widget.unread is False


def test_opening_the_panel_without_an_open_thread_writes_nothing() -> None:
    """Sərhəd: açıq müraciət yoxdursa `mark_read` çağırılmır və commit olmur."""
    support = _Support(threads=[])
    controller, session = _chat(support)
    widget = _ChatWidget()

    controller._on_opened(widget)  # type: ignore[arg-type]

    assert support.marked == []
    assert session.commits == 0
    assert widget.unread is None


def test_a_failed_mark_read_does_not_clear_the_badge() -> None:
    """Nişan YALAN göstərməməlidir: yazılmayıbsa «oxunub» da olmamalıdır."""
    thread = _Thread(is_open=True, messages=[])
    support = _Support(threads=[thread], mark_error=RuntimeError("yazıla bilmədi"))
    controller, session = _chat(support)
    widget = _ChatWidget()

    controller._on_opened(widget)  # type: ignore[arg-type]

    assert widget.unread is None
    assert session.commits == 0


def test_an_unexpected_send_failure_is_shown_inside_the_chat() -> None:
    """Ayrıca xəta sahəsi yoxdur — səbəb söhbətin İÇİNDƏ görünür."""
    controller, session = _chat(_Support(send_error=RuntimeError("SMTP")))
    widget = _ChatWidget()

    controller._on_sent(widget, "Salam")  # type: ignore[arg-type]

    assert widget.messages == [(f"{FAILURE_PREFIX}əlaqə qurulmadı. Yenidən cəhd edin.", False)]
    assert session.commits == 0


# --------------------------------------------------------------------------- #
# Profil (`controllers/profile.py`)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("full_name", "expected"),
    [
        ("", ("", "")),
        ("   ", ("", "")),
        ("Aysel", ("Aysel", "")),
        ("Rəşad Məmmədov", ("Rəşad", "Məmmədov")),
        ("Rəşad Əli Məmmədov", ("Rəşad Əli", "Məmmədov")),
        ("  Rəşad   Məmmədov  ", ("Rəşad", "Məmmədov")),
    ],
)
def test_name_splitting_treats_the_last_word_as_the_surname(
    full_name: str, expected: tuple[str, str]
) -> None:
    """Ata adı ADA daha yaxındır — «Rəşad Əli Məmmədov» → soyad «Məmmədov»."""
    assert _split_name(full_name) == expected


class _FullProfileScreen:
    def __init__(self) -> None:
        self.account: dict[str, str] = {}
        self.role_rows: list[tuple[str, str]] = []
        self.sessions: list[tuple[str, str, str]] = []
        self.errors: list[tuple[str, str]] = []

    def set_account(
        self, *, username: str, email: str, phone: str = "", password_note: str = ""
    ) -> None:
        self.account = {
            "username": username,
            "email": email,
            "phone": phone,
            "password_note": password_note,
        }

    def set_role_info(self, rows: list[tuple[str, str]]) -> None:
        self.role_rows = rows

    def set_sessions(self, sessions: list[tuple[str, str, str]]) -> None:
        self.sessions = sessions

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


class _FlagCatalog:
    def __init__(self, flags: list[PermissionFlag]) -> None:
        self._flags = flags

    def list_all(self) -> list[PermissionFlag]:
        return list(self._flags)


class _RoutedConnection:
    """İki fərqli sorğu, iki fərqli cavab dəsti.

    `profile.py` eyni bağlantıdan HƏM `stores`, HƏM `auth_sessions` oxuyur.
    Tək siyahı qaytaran sahtə ikinci sorğuya birincinin sətirlərini verərdi
    və test yanlış səbəbdən yaşıl (və ya qırmızı) olardı.
    """

    def __init__(
        self, *, store_rows: list[dict[str, Any]], session_rows: list[dict[str, Any]]
    ) -> None:
        self.store_rows = store_rows
        self.session_rows = session_rows

    def execute(self, sql: str, params: Any = None) -> _Cursor:
        if "auth_sessions" in sql:
            return _Cursor(self.session_rows)
        return _Cursor(self.store_rows)


class _ProfileUow:
    def __init__(
        self,
        employee: Any,
        *,
        store_rows: list[dict[str, Any]],
        session_rows: list[dict[str, Any]],
        flags: list[PermissionFlag],
    ) -> None:
        self.employees = _QueueEmployees(employee)
        self.connection = _RoutedConnection(store_rows=store_rows, session_rows=session_rows)
        self._flags = _FlagCatalog(flags)

    def repository(self, name: str) -> Any:
        return self._flags


class _ProfileGate:
    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.checked = 0

    def require_view(self, *, viewer: Any, subject: Any) -> None:
        self.checked += 1
        if self._error is not None:
            raise self._error


class _FullProfileSession:
    def __init__(
        self,
        employee: Any,
        *,
        store_rows: list[dict[str, Any]] | None = None,
        session_rows: list[dict[str, Any]] | None = None,
        flags: list[PermissionFlag] | None = None,
        gate_error: Exception | None = None,
    ) -> None:
        self.tenant_id = TENANT
        self.uow = _ProfileUow(
            employee,
            store_rows=store_rows or [],
            session_rows=session_rows or [],
            flags=flags or [],
        )
        self.employee_profile = _ProfileGate(error=gate_error)
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _profile_employee(*, camera: bool = False) -> Any:
    from src.domain.entities.employee import Employee
    from src.domain.entities.position import Position
    from src.domain.value_objects.authorization import RolePriority
    from src.domain.value_objects.credentials import Username
    from src.domain.value_objects.identifiers import PositionId

    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code="KAMERA_NEZARETCISI" if camera else "HR_ADMIN",
        name_az="Kamera Nəzarətçisi" if camera else "HR Admin",
        priority=RolePriority.OPERATIONAL,
        tenant_id=TENANT,
        is_system=True,
        is_camera_type=camera,
    )
    if not camera:
        position.grant(PermissionFlag(code="can_view_employee_reports", category="HR"))
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        store_id=STORE,
        first_name="Rəşad",
        last_name="Məmmədov",
        username=Username.parse("r.mammadov"),
        has_password=True,
    )


def test_the_profile_screen_never_invents_a_phone_number() -> None:
    """`employees` cədvəlində `phone` sütunu YOXDUR — sahə boş göstərilir."""
    employee = _profile_employee()
    session = _FullProfileSession(employee, store_rows=[{"name": "Bakı — Nizami"}])
    controller = ProfileController(_Context(session), employee)  # type: ignore[arg-type]
    screen = _FullProfileScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.account["phone"] == ""
    assert screen.account["username"] == "r.mammadov"
    assert screen.account["email"] == "—", "E-poçt yoxdursa tire göstərilir"
    assert screen.account["password_note"] == PASSWORD_POLICY_NOTE
    assert session.employee_profile.checked == 1


def test_the_role_card_counts_active_permissions_against_the_catalog() -> None:
    employee = _profile_employee()
    catalog = [
        PermissionFlag(code="can_view_employee_reports", category="HR"),
        PermissionFlag(code="can_manage_backups", category="SISTEM"),
        PermissionFlag(code="can_export_reports", category="SISTEM"),
    ]
    session = _FullProfileSession(employee, store_rows=[{"name": "Bakı — Nizami"}], flags=catalog)
    controller = ProfileController(_Context(session), employee)  # type: ignore[arg-type]
    screen = _FullProfileScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    rows = dict(screen.role_rows)
    assert rows["Vəzifə"] == "HR Admin"
    assert rows["Aktiv icazə"] == "1 / 3"
    assert rows["Fərdi istisna"] == "0"
    assert rows["Təyin edilmiş mağaza"] == "Bakı — Nizami"


def test_more_than_two_stores_are_summarised_not_listed() -> None:
    """Uzun siyahı kartı dağıdardı — «X və daha N» qısaltması istifadə olunur."""
    employee = _profile_employee(camera=True)
    employee.assign_store(StoreId(uuid.uuid4()))
    employee.assign_store(StoreId(uuid.uuid4()))
    session = _FullProfileSession(
        employee, store_rows=[{"name": "Bakı"}, {"name": "Gəncə"}, {"name": "Sumqayıt"}]
    )
    controller = ProfileController(_Context(session), employee)  # type: ignore[arg-type]
    screen = _FullProfileScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert dict(screen.role_rows)["Təyin edilmiş mağaza"] == "Bakı və daha 2"


def test_a_store_that_no_longer_exists_reads_as_unassigned() -> None:
    """Sərhəd: ID var, sətir yoxdur — uydurma ad göstərilmir."""
    employee = _profile_employee()
    session = _FullProfileSession(employee, store_rows=[])
    controller = ProfileController(_Context(session), employee)  # type: ignore[arg-type]
    screen = _FullProfileScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert dict(screen.role_rows)["Təyin edilmiş mağaza"] == "Təyin edilməyib"


def test_session_rows_mark_only_live_sessions_as_active() -> None:
    """Ləğv edilmiş və vaxtı keçmiş sessiya «Bağlanıb» olmalıdır."""
    employee = _profile_employee()
    now = datetime.now(UTC)
    rows = [
        {
            "issued_at": now - timedelta(hours=1),
            "machine_name": "KASSA-01",
            "revoked_at": None,
            "expires_at": now + timedelta(hours=8),
        },
        {
            "issued_at": now - timedelta(days=2),
            "machine_name": None,
            "revoked_at": now - timedelta(days=1),
            "expires_at": now + timedelta(hours=8),
        },
        {
            "issued_at": None,
            "machine_name": "KASSA-02",
            "revoked_at": None,
            "expires_at": now - timedelta(minutes=1),
        },
    ]
    session = _FullProfileSession(
        employee, store_rows=[{"name": "Bakı — Nizami"}], session_rows=rows
    )
    controller = ProfileController(_Context(session), employee)  # type: ignore[arg-type]
    screen = _FullProfileScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    states = [row[2] for row in screen.sessions]
    assert states == ["Aktiv sessiya", "Bağlanıb", "Bağlanıb"]
    assert screen.sessions[1][1] == "Naməlum cihaz"
    assert screen.sessions[2][0] == "—", "Tarixi olmayan sətir tire göstərir"


def test_a_refused_profile_view_shows_the_domain_reason() -> None:
    employee = _profile_employee()
    session = _FullProfileSession(employee, gate_error=_DeniedError("baxış qadağandır"))
    controller = ProfileController(_Context(session), employee)  # type: ignore[arg-type]
    screen = _FullProfileScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.errors == [("Profil açıla bilmədi", "Bu əməliyyat üçün səlahiyyətiniz yoxdur.")]
    assert screen.account == {}


def test_an_unexpected_profile_failure_is_reported_generically() -> None:
    employee = _profile_employee()
    session = _FullProfileSession(employee, gate_error=RuntimeError("psycopg xətası"))
    controller = ProfileController(_Context(session), employee)  # type: ignore[arg-type]
    screen = _FullProfileScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.errors == [
        ("Profil açıla bilmədi", "Hesab məlumatı oxuna bilmədi. Yenidən cəhd edin.")
    ]
