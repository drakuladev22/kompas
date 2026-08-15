"""Face Control-un EKRAN qatı — `facecontrol.md` Faza 4.

Testlər DÖRD təbəqəni ayrıca yoxlayır:

    * MENYU qapıları — «GÖRMƏK = SƏLAHİYYƏTİN OLMASI» (Qt tələb ETMİR);
    * KİOSK ÜZ QAPISI — mənbə mətnini AST ilə oxuyan struktur qapısı + davranış;
    * KONTROLLERLƏR — maket/canlı açar pariteti, yazıdan sonra yenidən oxuma,
      `user_message` sızması (Qt tələb ETMİR);
    * EKRANLARIN ÖZÜ — `qtbot` + `qt_app`, HƏM dark, HƏM light rejimdə.

Sahtələr BU FAYLDA yerlidir — `tests/fixtures/fakes.py`-a TOXUNULMUR (eyni
qərar `test_annual_leave_screen.py`-də də verilib: paralel işlər həmin ortaq
faylı dəyişə bilər).

──────────────────────────────────────────────────────────────────────────────
ƏN VACİB TEST HANSIDIR
──────────────────────────────────────────────────────────────────────────────
`test_kiosk_operations_never_bypass_the_face_gate`. `use_cases/face_control.py`
başlığı öz qərarının zəif nöqtəsini açıq yazıb: üz təsdiqi `start_day`/
`request_leave`/`claim_return` metodlarının İÇİNDƏ deyil, ona görə həmin
metodları birbaşa çağıran hər yol onu atlaya bilər. Boşluğu bağlayan qat kiosk
kontrolleridir və o, YALNIZ öz strukturunu qoruduğu müddətdə işləyir. Həmin
struktur DAVRANIŞ testi ilə tutulmur (sahtə use case istənilən nəticəni qaytara
bilər), ona görə burada mənbə mətni oxunur — naxış
`test_root_control_parameter_parity`-dəndir.
"""

from __future__ import annotations

import ast
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest

from src.application.use_cases.face_control import (
    FaceEnrollmentResult,
    FaceExemptionView,
    FaceGateDecision,
    FaceGateOutcome,
)
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.authorization import PermissionFlag, RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.face_recognition import (
    FaceEnrollmentFrameOutcome,
    FaceExemption,
    FaceTriggerContext,
    LivenessGesture,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    TenantId,
    new_face_exemption_id,
)
from src.presentation import preview_data
from src.presentation.controllers.face_control import (
    CAMERA_READY,
    CAMERA_UNAVAILABLE,
    FaceEnrollmentController,
    FaceExemptionController,
    _enrollment_rows,
    _exemption_limits,
    _exemption_row,
    _frame_row,
    _result_row,
    enrollment_state,
)
from src.presentation.controllers.kiosk import (
    FACE_GATE_UNAVAILABLE,
    KioskController,
    face_result_row,
)
from src.presentation.shell.menu import DEFAULT_ENTRIES, build_default_registry
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())
NOW: Final = datetime(2026, 8, 15, 9, 42, tzinfo=UTC)
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_KIOSK_SOURCE: Final[Path] = _REPO_ROOT / "src" / "presentation" / "controllers" / "kiosk.py"


class _DeniedError(KompasOSError):
    """`FaceControlPermissionError` müqaviləsinin yerli əvəzi."""

    user_message = "Bu əməliyyat üçün səlahiyyətiniz yoxdur."


# --------------------------------------------------------------------------- #
# Aktorlar
# --------------------------------------------------------------------------- #


def _employee(*, code: str, name_az: str, flags: tuple[str, ...]) -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=code,
        name_az=name_az,
        priority=RolePriority.OPERATIONAL,
        tenant_id=TENANT,
        is_system=True,
    )
    for flag in flags:
        position.grant(PermissionFlag(code=flag, category="test"))
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Aysel",
        last_name="Quliyeva",
        username=Username("a.quliyeva"),
        has_password=True,
    )


def _seller() -> Employee:
    return _employee(code="SATICI", name_az="Satıcı", flags=())


def _hr_admin() -> Employee:
    return _employee(code="HR_ADMIN", name_az="HR Admin", flags=("can_manage_employees",))


def _root() -> Employee:
    return _employee(
        code="ROOT",
        name_az="Root",
        flags=("can_manage_employees", "can_manage_face_exemptions"),
    )


# --------------------------------------------------------------------------- #
# Menyu — «GÖRMƏK = SƏLAHİYYƏTİN OLMASI»
# --------------------------------------------------------------------------- #


def test_enrollment_entry_is_gated_by_the_employee_management_flag() -> None:
    """Bənd 1: qeydiyyat YALNIZ `can_manage_employees` sahibindədir."""
    entry = next(e for e in DEFAULT_ENTRIES if e.key == "face_enrollment")
    assert entry.required_flag == "can_manage_employees"
    # Feature Toggle YOXDUR: modul söndürülsə də yeni işçini qabaqcadan
    # qeydiyyata almaq qanunidir (bax `menu.py` şərhi).
    assert entry.feature_module is None


def test_exemption_entry_requires_the_dedicated_hardlocked_flag() -> None:
    """Bənd 14: `can_manage_employees` KİFAYƏT ETMİR."""
    entry = next(e for e in DEFAULT_ENTRIES if e.key == "face_exemptions")
    assert entry.required_flag == "can_manage_face_exemptions"


def test_an_hr_admin_never_sees_the_exemption_screen() -> None:
    """İstisna ekranı HR-səviyyəli admin üçün RENDER OLUNMUR (boz deyil, YOX)."""
    registry = build_default_registry()
    hr_admin = _hr_admin()

    assert registry.is_visible("face_enrollment", hr_admin, now=NOW) is True
    assert registry.is_visible("face_exemptions", hr_admin, now=NOW) is False
    assert registry.is_visible("face_exemptions", _root(), now=NOW) is True


def test_a_seller_sees_neither_face_control_screen() -> None:
    """İşçi öz üzünü özü qeydiyyata sala biləcəyi yolu GÖRMÜR (bənd 1)."""
    registry = build_default_registry()
    seller = _seller()

    assert registry.is_visible("face_enrollment", seller, now=NOW) is False
    assert registry.is_visible("face_exemptions", seller, now=NOW) is False


# --------------------------------------------------------------------------- #
# KİOSK ÜZ QAPISI — struktur qapısı (mənbə mətnini oxuyur)
# --------------------------------------------------------------------------- #


def _kiosk_class() -> ast.ClassDef:
    tree = ast.parse(_KIOSK_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "KioskController":
            return node
    pytest.fail("`kiosk.py`-da `KioskController` tapılmadı")


def _method(name: str) -> ast.FunctionDef:
    for item in _kiosk_class().body:
        if isinstance(item, ast.FunctionDef) and item.name == name:
            return item
    pytest.fail(f"`KioskController.{name}` tapılmadı")


def _self_calls(node: ast.AST) -> list[str]:
    """Metodun gövdəsindəki BÜTÜN `self.X(...)` çağırışları (sıra ilə)."""
    calls: list[tuple[int, str]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "self"
        ):
            calls.append((child.lineno, func.attr))
    return [name for _, name in sorted(calls)]


@pytest.mark.parametrize("method", ["start_day", "request_leave", "claim_return"])
def test_kiosk_operations_never_bypass_the_face_gate(method: str) -> None:
    """STEP A/1/2 `_operation`-u BİRBAŞA çağıra bilməz (facecontrol.md Faza 4).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ MƏNBƏ MƏTNİ, NİYƏ DAVRANIŞ TESTİ YOX
    ──────────────────────────────────────────────────────────────────────────
    Davranış testi sahtə use case ilə işləyir və sahtə istənilən nəticəni
    qaytara bilər — yəni «qapı çağırıldımı?» sualına yalnız o metodun HAZIRKI
    kodu üçün cavab verir. Sual isə STRUKTURA aiddir: dördüncü əməliyyat
    yazan adam `_operation`-u birbaşa çağırsa, bütün davranış testləri yaşıl
    qalar və üz qatı həmin axında SÜKUTLA yan keçilər.

    Naxış `test_root_control_parameter_parity`-dəndir (orada
    `Path(...).read_text()` ilə struktur qərarı qorunur).
    """
    calls = _self_calls(_method(method))

    assert "_guarded" in calls, (
        f"`KioskController.{method}` artıq `_guarded`-i çağırmır — üz qapısı "
        "atlanır (facecontrol.md bənd 3)."
    )
    assert "_operation" not in calls, (
        f"`KioskController.{method}` `_operation`-u BİRBAŞA çağırır — bu, üz "
        "qapısını yan keçir. Əməliyyat `_guarded`-dən keçməlidir."
    )


def test_the_guard_runs_the_face_gate_before_the_operation() -> None:
    """SIRA: əvvəlcə üz, sonra əməliyyat — tərsi jurnalı mənasız edərdi."""
    calls = _self_calls(_method("_guarded"))

    assert "_face_gate" in calls, "`_guarded` üz qapısını çağırmır"
    assert "_operation" in calls, "`_guarded` əməliyyatı çağırmır"
    assert calls.index("_face_gate") < calls.index("_operation"), (
        "Üz qapısı əməliyyatdan SONRA çağırılır — MISMATCH halında sorğu artıq yaradılmış olardı."
    )


def test_the_face_gate_calls_the_verification_use_case() -> None:
    """Qapı MÖVCUD use case-i çağırır, ikinci mexanizm yazmır."""
    source = _KIOSK_SOURCE.read_text(encoding="utf-8")

    assert "session.face_verification.verify(" in source, (
        "`_face_gate` artıq `FaceVerificationUseCase.verify`-i çağırmır — "
        "üz qapısı boş qabığa çevrilib."
    )


# --------------------------------------------------------------------------- #
# Kiosk sahtələri
# --------------------------------------------------------------------------- #


class _KioskUseCase:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def _run(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)

    start_day = _run
    request_leave = _run
    claim_return = _run


class _KioskAttendance:
    def get_for_day(self, employee_id: Any, work_date: Any) -> Any:
        return None


class _KioskLeaves:
    def find_open_for_employee(self, employee_id: Any) -> Any:
        return None


class _KioskUow:
    def __init__(self) -> None:
        self.attendance = _KioskAttendance()
        self.leave_requests = _KioskLeaves()


class _FaceGateStub:
    def __init__(
        self,
        *,
        outcome: FaceGateOutcome = FaceGateOutcome.ALLOWED,
        error: Exception | None = None,
        gesture: LivenessGesture | None = LivenessGesture.BLINK,
        confidence: float | None = 88.0,
    ) -> None:
        self._outcome = outcome
        self._error = error
        self._gesture = gesture
        self._confidence = confidence
        self.contexts: list[FaceTriggerContext] = []

    def verify(
        self, *, tenant_id: Any, employee: Any, trigger_context: FaceTriggerContext
    ) -> FaceGateDecision:
        self.contexts.append(trigger_context)
        if self._error is not None:
            raise self._error
        return FaceGateDecision(
            employee_id=employee.id,
            trigger_context=trigger_context,
            outcome=self._outcome,
            message_az="Üz nəticəsi",
            liveness_action=self._gesture,
            confidence_score=self._confidence,
        )


class _KioskSession:
    def __init__(self, gate: _FaceGateStub) -> None:
        self.tenant_id = TENANT
        self.uow = _KioskUow()
        self.morning_check_in = _KioskUseCase()
        self.leave_verification = _KioskUseCase()
        self.face_verification = gate
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Context:
    """`ApplicationContext.session()` müqaviləsinin minimal təkrarı."""

    def __init__(self, session: Any) -> None:
        self._session = session
        self.tenant_id = TENANT
        self.opened = 0

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        self.opened += 1
        yield self._session


def _kiosk(gate: _FaceGateStub) -> tuple[KioskController, _KioskSession]:
    from src.domain.value_objects.identifiers import StoreId

    session = _KioskSession(gate)
    controller = KioskController(_Context(session), store_id=StoreId(uuid.uuid4()))  # type: ignore[arg-type]
    return controller, session


# --------------------------------------------------------------------------- #
# Kiosk üz qapısı — davranış
# --------------------------------------------------------------------------- #


def test_a_mismatch_stops_the_operation_before_it_is_created() -> None:
    """`BLOCKED` — STEP A ÜMUMİYYƏTLƏ çağırılmır."""
    gate = _FaceGateStub(outcome=FaceGateOutcome.BLOCKED)
    controller, session = _kiosk(gate)

    outcome = controller.start_day(_seller())

    assert outcome.failed is True
    assert session.morning_check_in.calls == [], "Üz uyğun gəlmədikdə əməliyyat yaradılmamalıdır"
    assert gate.contexts == [FaceTriggerContext.STEP_A]
    assert outcome.face["outcome"] == "BLOCKED"
    assert outcome.requires_face_overlay is True


def test_no_face_detected_offers_a_retry_without_running_the_operation() -> None:
    """`RETRY` TEXNİKİ haldır — sayğac artmır, yenidən cəhd təklif olunur."""
    gate = _FaceGateStub(outcome=FaceGateOutcome.RETRY, confidence=None)
    controller, session = _kiosk(gate)

    outcome = controller.claim_return(_seller())

    assert outcome.failed is True
    assert session.leave_verification.calls == []
    assert gate.contexts == [FaceTriggerContext.STEP_2]
    assert outcome.face["retry"] == "1"
    assert outcome.face["confidence"] == "", "Müqayisə aparılmayıbsa bal GÖSTƏRİLMİR"


def test_an_exempt_employee_is_routed_to_dual_control_not_waved_through() -> None:
    """Bənd 14: istisna «buraxın» demir — MƏCBURİ ikinci təsdiq."""
    gate = _FaceGateStub(outcome=FaceGateOutcome.DUAL_CONTROL_REQUIRED, gesture=None)
    controller, session = _kiosk(gate)

    outcome = controller.request_leave(_seller())

    assert outcome.failed is True
    assert session.leave_verification.calls == []
    assert outcome.requires_face_overlay is True
    assert outcome.face["retry"] == "0"


def test_a_broken_face_gate_fails_closed() -> None:
    """Bənd 5: nasazlıq SÜKUTLA «yalnız PIN» rejimi YARATMIR."""
    gate = _FaceGateStub(error=RuntimeError("kamera sürücüsü çökdü"))
    controller, session = _kiosk(gate)

    outcome = controller.start_day(_seller())

    assert outcome.failed is True
    assert outcome.message == FACE_GATE_UNAVAILABLE
    assert "sürücü" not in outcome.message, "Texniki detal işçiyə SIZMIR"
    assert session.morning_check_in.calls == []
    assert outcome.face["outcome"] == "MANUAL_APPROVAL_REQUIRED"


def test_a_domain_error_in_the_gate_reaches_the_worker_as_user_message() -> None:
    gate = _FaceGateStub(error=_DeniedError("daxili kontekst: flag yoxdur"))
    controller, _ = _kiosk(gate)

    outcome = controller.start_day(_seller())

    assert outcome.message == _DeniedError.user_message
    assert "daxili kontekst" not in outcome.message


def test_an_allowed_face_lets_the_operation_run_and_commits_the_log() -> None:
    """Uğurlu təsdiq: jurnal sətri VƏ əməliyyat — İKİ ayrı commit."""
    gate = _FaceGateStub(outcome=FaceGateOutcome.ALLOWED)
    controller, session = _kiosk(gate)

    outcome = controller.start_day(_seller())

    assert outcome.succeeded is True
    assert len(session.morning_check_in.calls) == 1
    assert session.commits == 2, "Qapı jurnalı və əməliyyat AYRI sessiyalarda commit edilir"
    assert outcome.requires_face_overlay is False, "Uğurlu təsdiqdə modal AÇILMIR"


def test_a_store_outside_the_pilot_scope_pays_no_extra_transaction() -> None:
    """`NOT_APPLICABLE` heç nə yazmır — boş commit də olmur (bənd 15)."""
    gate = _FaceGateStub(outcome=FaceGateOutcome.NOT_APPLICABLE, gesture=None, confidence=None)
    controller, session = _kiosk(gate)

    outcome = controller.start_day(_seller())

    assert outcome.succeeded is True
    assert session.commits == 1, "Yalnız əməliyyatın öz commit-i olmalıdır"
    assert outcome.requires_face_overlay is False


def test_the_gesture_text_comes_from_the_decision_not_from_the_screen() -> None:
    """Bənd 6: hərəkəti EKRAN SEÇMİR, serverdən gələni GÖSTƏRİR."""
    decision = FaceGateDecision(
        employee_id=EmployeeId(uuid.uuid4()),
        trigger_context=FaceTriggerContext.STEP_A,
        outcome=FaceGateOutcome.RETRY,
        message_az="Üz aşkarlanmadı.",
        liveness_action=LivenessGesture.HEAD_TURN,
    )

    row = face_result_row(decision)

    assert row["gesture"] == LivenessGesture.HEAD_TURN.prompt_az
    assert row["retry"] == "1"


def test_preview_and_live_paths_share_the_same_overlay_keys() -> None:
    """Maket və canlı yol EYNİ açarları işlədir (CLAUDE.md §6)."""
    decision = FaceGateDecision(
        employee_id=EmployeeId(uuid.uuid4()),
        trigger_context=FaceTriggerContext.STEP_A,
        outcome=FaceGateOutcome.ALLOWED,
        message_az="Üz təsdiqləndi.",
        liveness_action=LivenessGesture.SMILE,
        confidence_score=88.4,
    )

    assert set(face_result_row(decision)) == set(preview_data.FACE_VERIFICATION_RESULT)


# --------------------------------------------------------------------------- #
# Qeydiyyat kontrolleri
# --------------------------------------------------------------------------- #


class _Row(dict):  # type: ignore[type-arg]
    """`dict`-ə əsaslanan sətir — `row["sütun"]` müqaviləsi ilə eynidir."""


class _Cursor:
    def __init__(self, rows: list[_Row]) -> None:
        self._rows = rows

    def fetchall(self) -> list[_Row]:
        return self._rows

    def fetchone(self) -> _Row | None:
        return self._rows[0] if self._rows else None


class _Connection:
    def __init__(self, rows: list[_Row]) -> None:
        self._rows = rows
        self.queries: list[str] = []

    def execute(self, sql: str, params: Any = ()) -> _Cursor:
        self.queries.append(" ".join(sql.split()))
        return _Cursor(self._rows)


class _Employees:
    def __init__(self, employees: dict[EmployeeId, Employee]) -> None:
        self._employees = employees

    def get(self, employee_id: EmployeeId) -> Employee | None:
        return self._employees.get(employee_id)


class _Uow:
    def __init__(self, rows: list[_Row], employees: dict[EmployeeId, Employee]) -> None:
        self.connection = _Connection(rows)
        self.employees = _Employees(employees)


class _Limits:
    def get_int(self, tenant_id: Any, key: str, default: int) -> int:
        return default

    def get_str(self, tenant_id: Any, key: str, default: str) -> str:
        return default


class _EnrollmentUseCase:
    def __init__(self, *, result: FaceEnrollmentResult, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def enroll(self, **kwargs: Any) -> FaceEnrollmentResult:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._result


class _ReEnrollmentUseCase:
    def __init__(self, *, result: FaceEnrollmentResult) -> None:
        self._result = result
        self.calls: list[dict[str, Any]] = []

    def re_enroll(self, **kwargs: Any) -> FaceEnrollmentResult:
        self.calls.append(kwargs)
        return self._result


class _ExemptionUseCase:
    def __init__(
        self,
        *,
        active: list[FaceExemptionView] | None = None,
        list_error: Exception | None = None,
        grant_error: Exception | None = None,
    ) -> None:
        self._active = active or []
        self._list_error = list_error
        self._grant_error = grant_error
        self.granted: list[dict[str, Any]] = []
        self.revoked: list[dict[str, Any]] = []
        self.list_calls = 0

    def list_active(self, *, tenant_id: Any, actor: Any) -> list[FaceExemptionView]:
        self.list_calls += 1
        if self._list_error is not None:
            raise self._list_error
        return list(self._active)

    def grant(self, **kwargs: Any) -> Any:
        if self._grant_error is not None:
            raise self._grant_error
        self.granted.append(kwargs)
        return None

    def revoke(self, **kwargs: Any) -> Any:
        self.revoked.append(kwargs)
        return None


class _FaceSession:
    def __init__(
        self,
        *,
        rows: list[_Row] | None = None,
        employees: dict[EmployeeId, Employee] | None = None,
        enrollment: _EnrollmentUseCase | None = None,
        re_enrollment: _ReEnrollmentUseCase | None = None,
        exemptions: _ExemptionUseCase | None = None,
    ) -> None:
        self.tenant_id = TENANT
        self.uow = _Uow(rows or [], employees or {})
        self.limits = _Limits()
        self.face_enrollment = enrollment
        self.face_re_enrollment = re_enrollment
        self.face_exemptions = exemptions
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _FaceContext(_Context):
    def __init__(self, session: Any, *, camera_available: bool = True) -> None:
        super().__init__(session)
        self._camera_available = camera_available

    def face_engine(self) -> tuple[Any, Any]:
        camera = type("_Camera", (), {"is_available": lambda _self: self._camera_available})()
        return camera, camera


class _EnrollmentScreen:
    """`FaceEnrollmentScreen` setter API-sinin sahtəsi."""

    def __init__(self, *, mode: str = "ENROLL", reason: str = "") -> None:
        self.employees: list[list[dict[str, str]]] = []
        self.cameras: list[dict[str, str]] = []
        self.results: list[dict[str, str]] = []
        self.frames: list[list[dict[str, str]]] = []
        self.errors: list[tuple[str, str]] = []
        self._mode = mode
        self._reason = reason

    def set_employees(self, rows: list[dict[str, str]]) -> None:
        self.employees.append(rows)

    def set_camera(self, camera: dict[str, str]) -> None:
        self.cameras.append(camera)

    def set_result(self, result: dict[str, str]) -> None:
        self.results.append(result)

    def set_frames(self, rows: list[dict[str, str]]) -> None:
        self.frames.append(rows)

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))

    def mode(self) -> str:
        return self._mode

    def reason_text(self) -> str:
        return self._reason


class _ExemptionScreen:
    """`FaceExemptionScreen` setter API-sinin sahtəsi."""

    def __init__(self) -> None:
        self.limits: list[dict[str, str]] = []
        self.employees: list[list[dict[str, str]]] = []
        self.exemptions: list[list[dict[str, str]]] = []
        self.errors: list[tuple[str, str]] = []

    def set_limits(self, limits: dict[str, str]) -> None:
        self.limits.append(limits)

    def set_employees(self, rows: list[dict[str, str]]) -> None:
        self.employees.append(rows)

    def set_exemptions(self, rows: list[dict[str, str]]) -> None:
        self.exemptions.append(rows)

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


def _accepted_result(employee_id: EmployeeId) -> FaceEnrollmentResult:
    return FaceEnrollmentResult(
        employee_id=employee_id,
        accepted=True,
        message_az="Üz qeydiyyatı tamamlandı — 4/5 kadrın ortası istinad kimi saxlanıldı.",
        frames=(
            FaceEnrollmentFrameOutcome(index=1, accepted=True, quality=0.82),
            FaceEnrollmentFrameOutcome(
                index=2, accepted=False, quality=0.31, reason_az="Kadr çox qaranlıqdır"
            ),
        ),
        enrolled_at=NOW,
    )


def _rejected_result(employee_id: EmployeeId) -> FaceEnrollmentResult:
    return FaceEnrollmentResult(
        employee_id=employee_id,
        accepted=False,
        message_az="Heç bir kadr keyfiyyət həddini keçmədi.",
        frames=(
            FaceEnrollmentFrameOutcome(
                index=1, accepted=False, quality=0.12, reason_az="Kadr çox qaranlıqdır"
            ),
        ),
    )


def test_enrollment_commits_only_when_the_frames_pass() -> None:
    """Rədd edilmiş cəhd COMMIT EDİLMİR — arxiv sətri izsiz qalmalıdır."""
    subject = EmployeeId(uuid.uuid4())
    actor = _hr_admin()

    accepted = _EnrollmentUseCase(result=_accepted_result(subject))
    session = _FaceSession(enrollment=accepted)
    controller = FaceEnrollmentController(_FaceContext(session), actor)  # type: ignore[arg-type]
    screen = _EnrollmentScreen()
    controller._on_capture(screen, str(subject))  # type: ignore[arg-type]
    assert session.commits == 1
    assert screen.results[-1]["accepted"] == "1"

    rejected = _EnrollmentUseCase(result=_rejected_result(subject))
    session = _FaceSession(enrollment=rejected)
    controller = FaceEnrollmentController(_FaceContext(session), actor)  # type: ignore[arg-type]
    screen = _EnrollmentScreen()
    controller._on_capture(screen, str(subject))  # type: ignore[arg-type]
    assert session.commits == 0
    assert screen.results[-1]["accepted"] == "0"


def test_the_frame_reasons_reach_the_screen_one_by_one() -> None:
    """«uğursuz» deyil, SƏBƏB: operatorun növbəti addımı ondan asılıdır."""
    subject = EmployeeId(uuid.uuid4())
    session = _FaceSession(enrollment=_EnrollmentUseCase(result=_accepted_result(subject)))
    controller = FaceEnrollmentController(_FaceContext(session), _hr_admin())  # type: ignore[arg-type]
    screen = _EnrollmentScreen()

    controller._on_capture(screen, str(subject))  # type: ignore[arg-type]

    rows = screen.frames[-1]
    assert [row["accepted"] for row in rows] == ["1", "0"]
    assert rows[1]["reason"] == "Kadr çox qaranlıqdır"
    assert rows[1]["quality"] == "0.31"


def test_the_screen_is_refreshed_before_the_result_is_written() -> None:
    """SIRA: `refresh()` seçim siqnalını işə salır və nəticəni silərdi."""
    subject = EmployeeId(uuid.uuid4())
    session = _FaceSession(enrollment=_EnrollmentUseCase(result=_accepted_result(subject)))
    controller = FaceEnrollmentController(_FaceContext(session), _hr_admin())  # type: ignore[arg-type]
    screen = _EnrollmentScreen()

    controller._on_capture(screen, str(subject))  # type: ignore[arg-type]

    assert screen.employees, "Yazıdan sonra siyahı yenidən oxunmalıdır"
    assert screen.results, "Nəticə siyahıdan SONRA yazılmalıdır"


def test_a_domain_error_reaches_the_operator_as_user_message() -> None:
    subject = EmployeeId(uuid.uuid4())
    session = _FaceSession(
        enrollment=_EnrollmentUseCase(
            result=_accepted_result(subject),
            error=_DeniedError("öz üzünüzü özünüz qeydiyyata sala bilməzsiniz"),
        )
    )
    controller = FaceEnrollmentController(_FaceContext(session), _hr_admin())  # type: ignore[arg-type]
    screen = _EnrollmentScreen()

    controller._on_capture(screen, str(subject))  # type: ignore[arg-type]

    assert screen.results[-1]["message"] == _DeniedError.user_message
    assert session.commits == 0


def test_a_malformed_employee_id_never_opens_a_session() -> None:
    session = _FaceSession(
        enrollment=_EnrollmentUseCase(result=_accepted_result(EmployeeId(uuid.uuid4())))
    )
    context = _FaceContext(session)
    controller = FaceEnrollmentController(context, _hr_admin())  # type: ignore[arg-type]
    screen = _EnrollmentScreen()

    controller._on_capture(screen, "işçi-yox")  # type: ignore[arg-type]

    assert context.opened == 0
    assert screen.results[-1]["accepted"] == "0"


def test_an_unavailable_camera_is_explained_not_hidden() -> None:
    """Bənd 5 fəlsəfəsi: nasazlıq AÇIQ deyilir, düymələr sönür."""
    session = _FaceSession(
        enrollment=_EnrollmentUseCase(result=_accepted_result(EmployeeId(uuid.uuid4())))
    )
    controller = FaceEnrollmentController(
        _FaceContext(session, camera_available=False),  # type: ignore[arg-type]
        _hr_admin(),
    )
    screen = _EnrollmentScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.cameras[-1]["available"] == "0"
    assert screen.cameras[-1]["message"] == CAMERA_UNAVAILABLE
    assert "yoxlayın" in screen.cameras[-1]["message"], "İstifadəçi NƏ ETMƏLİ olduğunu bilməlidir"


def test_the_frame_count_comes_from_the_root_parameter() -> None:
    session = _FaceSession(
        enrollment=_EnrollmentUseCase(result=_accepted_result(EmployeeId(uuid.uuid4())))
    )
    controller = FaceEnrollmentController(_FaceContext(session), _hr_admin())  # type: ignore[arg-type]
    screen = _EnrollmentScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.cameras[-1]["frame_count"] == str(
        DEFAULT_LIMITS[SystemLimitKey.FACE_ENROLLMENT_FRAME_COUNT]
    )
    assert screen.cameras[-1]["message"] == CAMERA_READY


def test_retake_repeats_the_re_enrollment_when_the_screen_is_in_that_mode() -> None:
    """`[Yenidən Çək]` REJİMƏ görə davranır, ayrı yaddaş saxlamır."""
    subject = EmployeeId(uuid.uuid4())
    re_enrollment = _ReEnrollmentUseCase(result=_accepted_result(subject))
    session = _FaceSession(
        enrollment=_EnrollmentUseCase(result=_accepted_result(subject)),
        re_enrollment=re_enrollment,
    )
    controller = FaceEnrollmentController(_FaceContext(session), _hr_admin())  # type: ignore[arg-type]
    screen = _EnrollmentScreen(mode="RE_ENROLL", reason="Eynək dəyişib, üz tanınmır")

    controller._on_retake(screen, str(subject))  # type: ignore[arg-type]

    assert len(re_enrollment.calls) == 1
    assert re_enrollment.calls[0]["reason"] == "Eynək dəyişib, üz tanınmır"


def test_the_actor_never_appears_in_their_own_enrollment_list() -> None:
    """Özünə-qeydiyyat SEÇİMİ ekranda MÖVCUD OLMUR (bənd 1)."""
    actor = _hr_admin()
    session = _FaceSession(rows=[])
    _enrollment_rows(session, actor)  # type: ignore[arg-type]

    query = session.uow.connection.queries[-1]
    assert "e.id <> %s" in query, "Aktorun öz sətri sorğudan çıxarılmır"


@pytest.mark.parametrize(
    ("enrolled_at", "expected"),
    [
        (None, "NEW"),
        (NOW - timedelta(days=30), "ENROLLED"),
        (NOW - timedelta(days=800), "STALE"),
    ],
)
def test_enrollment_state_matches_the_reminder_interval(
    enrolled_at: datetime | None, expected: str
) -> None:
    """Bənd 13 — «köhnəlib» sərhədi `add_months` ilə hesablanır."""
    assert enrollment_state(enrolled_at, now=NOW, reminder_months=12) == expected


def test_a_zero_reminder_interval_never_marks_an_enrollment_as_stale() -> None:
    """Root intervalı 0 yazsa xatırlatma SÖNÜR — yalançı xəbərdarlıq olmur."""
    assert enrollment_state(NOW - timedelta(days=3000), now=NOW, reminder_months=0) == "ENROLLED"


def test_preview_and_live_paths_share_the_same_enrollment_keys() -> None:
    session = _FaceSession(
        rows=[
            _Row(
                {
                    "id": uuid.uuid4(),
                    "first_name": "Aysel",
                    "last_name": "Quliyeva",
                    "face_enrolled_at": None,
                    "store_name": "Bellona 28 May",
                }
            )
        ]
    )

    rows = _enrollment_rows(session, _hr_admin())  # type: ignore[arg-type]

    assert set(rows[0]) == set(preview_data.FACE_ENROLLMENT_EMPLOYEES[0])
    assert rows[0]["state"] == "NEW"


def test_preview_and_live_paths_share_the_same_result_and_frame_keys() -> None:
    result = _accepted_result(EmployeeId(uuid.uuid4()))

    assert set(_result_row(result)) == set(preview_data.FACE_ENROLLMENT_RESULT)
    assert set(_frame_row(result.frames[0])) == set(preview_data.FACE_ENROLLMENT_FRAMES[0])


# --------------------------------------------------------------------------- #
# İstisna kontrolleri
# --------------------------------------------------------------------------- #


def _exemption(employee_id: EmployeeId, granted_by: EmployeeId) -> FaceExemption:
    return FaceExemption(
        exemption_id=new_face_exemption_id(),
        tenant_id=TENANT,
        employee_id=employee_id,
        granted_by=granted_by,
        reason="Üz cərrahiyyəsindən sonra sağalma dövrü",
        granted_at=NOW,
        expires_at=NOW + timedelta(days=56),
    )


def test_preview_and_live_paths_share_the_same_exemption_keys() -> None:
    owner = _seller()
    root = _root()
    view = FaceExemptionView(exemption=_exemption(owner.id, root.id), days_remaining=56)
    session = _FaceSession(employees={owner.id: owner, root.id: root})

    row = _exemption_row(session, view)  # type: ignore[arg-type]

    assert set(row) == set(preview_data.FACE_EXEMPTIONS[0])
    assert row["employee"] == owner.full_name
    assert row["granted_by"] == root.full_name


def test_the_exemption_limits_come_from_root_and_the_schema() -> None:
    session = _FaceSession()

    limits = _exemption_limits(session)  # type: ignore[arg-type]

    assert set(limits) == set(preview_data.FACE_EXEMPTION_LIMITS)
    assert limits["max_days"] == str(DEFAULT_LIMITS[SystemLimitKey.FACE_EXEMPTION_MAX_DAYS])
    assert limits["min_reason_length"] == "10"


def test_granting_an_exemption_commits_and_rereads_the_list() -> None:
    owner = _seller()
    root = _root()
    use_case = _ExemptionUseCase()
    session = _FaceSession(exemptions=use_case, employees={owner.id: owner, root.id: root})
    controller = FaceExemptionController(_FaceContext(session), root)  # type: ignore[arg-type]
    screen = _ExemptionScreen()

    controller._on_grant(screen, str(owner.id), "Tibbi səbəb — həkim arayışı", 30)  # type: ignore[arg-type]

    assert len(use_case.granted) == 1
    assert session.commits == 1
    assert use_case.list_calls == 1, "Yazıdan sonra siyahı təzədən oxunmalıdır"


def test_a_permission_error_explains_itself_instead_of_showing_an_empty_table() -> None:
    """Boş cədvəl «istisna yoxdur» kimi oxunardı — bu, yanlış təəssüratdır."""
    use_case = _ExemptionUseCase(list_error=_DeniedError("hardlock 2 tələb olunur"))
    session = _FaceSession(exemptions=use_case)
    controller = FaceExemptionController(_FaceContext(session), _root())  # type: ignore[arg-type]
    screen = _ExemptionScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.errors == [("İstisnalar oxunmadı", _DeniedError.user_message)]
    assert screen.exemptions == []


def test_revoking_without_a_reason_never_reaches_the_use_case(monkeypatch: Any) -> None:
    """Ləğv İNSAN qərarıdır — boş cavab yazı yoluna GETMİR."""
    from src.presentation.controllers import face_control as module

    root = _root()
    use_case = _ExemptionUseCase()
    session = _FaceSession(exemptions=use_case)
    controller = FaceExemptionController(_FaceContext(session), root)  # type: ignore[arg-type]
    screen = _ExemptionScreen()
    exemption_id = str(new_face_exemption_id())

    monkeypatch.setattr(
        module.FaceExemptionController, "_ask_reason", staticmethod(lambda *_: None)
    )
    controller._on_revoke(screen, exemption_id)  # type: ignore[arg-type]
    assert use_case.revoked == []
    assert session.commits == 0

    monkeypatch.setattr(
        module.FaceExemptionController,
        "_ask_reason",
        staticmethod(lambda *_: "Sağalma dövrü bitdi, üz tanınır"),
    )
    controller._on_revoke(screen, exemption_id)  # type: ignore[arg-type]

    assert len(use_case.revoked) == 1
    assert session.commits == 1


def test_a_malformed_exemption_id_never_opens_a_session() -> None:
    use_case = _ExemptionUseCase()
    session = _FaceSession(exemptions=use_case)
    context = _FaceContext(session)
    controller = FaceExemptionController(context, _root())  # type: ignore[arg-type]
    screen = _ExemptionScreen()

    controller._on_revoke(screen, "istisna-yox")  # type: ignore[arg-type]

    assert context.opened == 0
    assert screen.errors[-1][0] == "İstisna ləğv edilmədi"


# --------------------------------------------------------------------------- #
# EKRANLARIN ÖZÜ — Qt tələb edir, HƏR İKİ REJİMDƏ
# --------------------------------------------------------------------------- #


@pytest.fixture(params=["light", "dark"])
def theme(request, qt_app):  # type: ignore[no-untyped-def]
    """Hər ekran testi HƏM işıqlı, HƏM tünd rejimdə icra olunur.

    Rəng birbaşa yazılmadığı üçün (hamısı `theme.color(...)` tokenidir) fərq
    yalnız kalibrləmədədir — lakin `set_tone`/`setStyleSheet` yollarının hər
    iki palitrada çökmədiyini yalnız faktiki icra göstərir.
    """
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(
        preference=ThemeMode.LIGHT if request.param == "light" else ThemeMode.DARK
    )
    manager.apply(qt_app)
    return manager


@requires_qt
def test_the_enrollment_screen_switches_to_re_enrollment_mode(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Qeydiyyatı olan işçi seçiləndə səbəb sahəsi və arxiv xəbərdarlığı açılır."""
    from src.presentation.screens.face_control import FaceEnrollmentScreen

    screen = FaceEnrollmentScreen(theme)
    qtbot.addWidget(screen)

    screen.set_camera(dict(preview_data.FACE_ENROLLMENT_CAMERA))
    screen.set_employees([dict(row) for row in preview_data.FACE_ENROLLMENT_EMPLOYEES])

    screen._subject.setCurrentIndex(0)  # `NEW`
    assert screen.mode() == "ENROLL"
    assert screen._capture.isVisibleTo(screen) is True
    assert screen._re_enroll_box.isVisibleTo(screen) is False

    screen._subject.setCurrentIndex(1)  # `ENROLLED`
    assert screen.mode() == "RE_ENROLL"
    assert screen._save.isVisibleTo(screen) is True
    assert screen._re_enroll_box.isVisibleTo(screen) is True
    assert "arxivlənir" in screen._archive_warning.text()


@requires_qt
def test_a_stale_enrollment_is_marked_on_the_enrollment_screen(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Bənd 13 — «Köhnəlib» nişanı admin üçün GÖRÜNÜR, girişi bloklamır."""
    from src.presentation.screens.face_control import FaceEnrollmentScreen

    screen = FaceEnrollmentScreen(theme)
    qtbot.addWidget(screen)
    screen.set_camera(dict(preview_data.FACE_ENROLLMENT_CAMERA))
    screen.set_employees([dict(row) for row in preview_data.FACE_ENROLLMENT_EMPLOYEES])

    screen._subject.setCurrentIndex(2)  # `STALE`

    assert screen._state_chip.text() == "Köhnəlib"
    assert screen._state_chip.property("chip") == "warning"


@requires_qt
def test_re_enrollment_without_a_reason_emits_nothing(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Boş səbəb domen istisnasına DEYİL, ekran mesajına çevrilir."""
    from src.presentation.screens.face_control import FaceEnrollmentScreen

    screen = FaceEnrollmentScreen(theme)
    qtbot.addWidget(screen)
    screen.set_camera(dict(preview_data.FACE_ENROLLMENT_CAMERA))
    screen.set_employees([dict(row) for row in preview_data.FACE_ENROLLMENT_EMPLOYEES])
    screen._subject.setCurrentIndex(1)

    emitted: list[tuple[str, str]] = []
    screen.re_enroll_requested.connect(lambda key, reason: emitted.append((key, reason)))
    screen._on_save()

    assert emitted == []
    assert "səbəb" in screen._result.text().lower()


@requires_qt
def test_the_retake_button_appears_only_after_a_rejected_attempt(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.face_control import FaceEnrollmentScreen

    screen = FaceEnrollmentScreen(theme)
    qtbot.addWidget(screen)
    screen.set_camera(dict(preview_data.FACE_ENROLLMENT_CAMERA))
    screen.set_employees([dict(row) for row in preview_data.FACE_ENROLLMENT_EMPLOYEES])
    assert screen._retake.isVisibleTo(screen) is False

    screen.set_result({"accepted": "0", "message": "Kadrlar keçmədi", "frames_total": "5"})
    assert screen._retake.isVisibleTo(screen) is True

    screen.set_result(dict(preview_data.FACE_ENROLLMENT_RESULT))
    assert screen._retake.isVisibleTo(screen) is False


@requires_qt
def test_an_empty_employee_list_shows_the_empty_state_not_an_error(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.face_control import FaceEnrollmentScreen

    screen = FaceEnrollmentScreen(theme)
    qtbot.addWidget(screen)

    screen.set_employees([])

    assert screen.switcher().current_state() == "empty"


@requires_qt
def test_the_frame_table_renders_every_outcome(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.face_control import FaceEnrollmentScreen

    screen = FaceEnrollmentScreen(theme)
    qtbot.addWidget(screen)

    screen.set_frames([dict(row) for row in preview_data.FACE_ENROLLMENT_FRAMES])

    assert screen.frames_layout().count() == 1
    assert screen._frames_empty.isVisibleTo(screen) is False


@requires_qt
def test_the_exemption_screen_blocks_a_short_reason(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Sxem `CHECK`-i 10 simvol tələb edir — yararsız sorğu YOLA ÇIXMIR."""
    from src.presentation.screens.face_control import FaceExemptionScreen

    screen = FaceExemptionScreen(theme)
    qtbot.addWidget(screen)
    screen.set_limits(dict(preview_data.FACE_EXEMPTION_LIMITS))
    screen.set_employees([dict(row) for row in preview_data.FACE_EXEMPTION_EMPLOYEES])

    emitted: list[tuple[str, str, int]] = []
    screen.grant_requested.connect(lambda key, reason, days: emitted.append((key, reason, days)))

    screen._reason.setText("qısa")
    screen._on_grant()
    assert emitted == []
    assert "10 simvol" in screen._hint.text()

    screen._reason.setText("Tibbi səbəb — həkim arayışı təqdim edilib")
    screen._on_grant()
    assert len(emitted) == 1
    assert emitted[0][2] >= 1


@requires_qt
def test_the_exemption_days_ceiling_comes_from_root(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.face_control import FaceExemptionScreen

    screen = FaceExemptionScreen(theme)
    qtbot.addWidget(screen)

    screen.set_limits({"max_days": "45", "min_reason_length": "10"})

    assert screen._days.maximum() == 45
    assert "45 gün" in screen._hint.text()


@requires_qt
def test_the_exemption_screen_states_the_compensating_control(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """MƏTN MƏCBURİDİR: istisna «sadəcə üz yoxlamasını söndürmək» deyil."""
    from PySide6.QtWidgets import QLabel

    from src.presentation.screens.face_control import FaceExemptionScreen

    screen = FaceExemptionScreen(theme)
    qtbot.addWidget(screen)

    texts = " ".join(label.text() for label in screen.findChildren(QLabel))
    assert "ikinci təsdiq" in texts
    assert "MÜVƏQQƏTİDİR" in texts


@requires_qt
def test_the_exemption_table_renders_the_preview_rows(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.face_control import FaceExemptionScreen

    screen = FaceExemptionScreen(theme)
    qtbot.addWidget(screen)

    screen.set_exemptions([dict(row) for row in preview_data.FACE_EXEMPTIONS])
    assert screen.table_layout().count() == 1

    revoked: list[str] = []
    screen.revoke_requested.connect(revoked.append)
    screen.revoke_requested.emit(preview_data.FACE_EXEMPTIONS[0]["id"])
    assert revoked == [preview_data.FACE_EXEMPTIONS[0]["id"]]

    screen.set_exemptions([])
    assert screen.table_layout().count() == 0
    assert screen._table_empty.isVisibleTo(screen) is True


@requires_qt
@pytest.mark.parametrize("result", preview_data.FACE_VERIFICATION_RESULTS)
def test_the_overlay_shows_a_distinct_text_for_every_outcome(qtbot, theme, result) -> None:  # type: ignore[no-untyped-def]
    """Bənd 3: üç nəticə, ÜÇ FƏRQLİ mətn."""
    from src.presentation.screens.face_control import OUTCOME_TITLES, FaceVerificationOverlay

    overlay = FaceVerificationOverlay(theme)
    qtbot.addWidget(overlay)

    overlay.set_result(dict(result))

    assert overlay.title_text() == OUTCOME_TITLES[result["outcome"]][0]
    assert overlay.message_text() == result["message"]
    assert overlay.retry_visible() is (result["retry"] == "1")


@requires_qt
def test_the_overlay_only_displays_the_gesture_it_was_given(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Bənd 6: ekranın öz hərəkət siyahısı YOXDUR."""
    from src.presentation.screens import face_control
    from src.presentation.screens.face_control import FaceVerificationOverlay

    overlay = FaceVerificationOverlay(theme)
    qtbot.addWidget(overlay)

    overlay.set_result(
        {
            "outcome": "RETRY",
            "message": "Üz aşkarlanmadı.",
            "gesture": LivenessGesture.SMILE.prompt_az,
            "confidence": "",
            "retry": "1",
        }
    )

    assert overlay.gesture_text() == LivenessGesture.SMILE.prompt_az

    # STRUKTUR QAPISI: ekran nə təsadüfi seçim aparır, nə də hərəkət
    # kataloqunu idxal edir — hər ikisi serverdədir (bənd 6).
    source = Path(face_control.__file__).read_text(encoding="utf-8")
    assert "import secrets" not in source, "Ekran hərəkəti ÖZÜ seçir — seçim serverdə olmalıdır"
    assert "import random" not in source, "Ekranda proqnozlaşdırıla bilən seçim yaranıb"
    assert "from src.domain.value_objects.face_recognition import" not in source, (
        "Ekran hərəkət kataloqunu idxal edir — göstərişi o, SEÇMƏMƏLİDİR."
    )


@requires_qt
def test_an_unknown_outcome_is_reported_not_swallowed(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.face_control import (
        FALLBACK_OUTCOME_TITLE,
        FaceVerificationOverlay,
    )

    overlay = FaceVerificationOverlay(theme)
    qtbot.addWidget(overlay)

    overlay.set_result({"outcome": "GELECEK_NETICE", "message": "?", "retry": "0"})

    assert overlay.title_text() == FALLBACK_OUTCOME_TITLE[0]


@requires_qt
def test_the_overlay_uses_the_high_contrast_pin_palette(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Kiosk toxunma-ilkdir: AAA cüt + 88px düymə (yeni rəng cütü YOX)."""
    from src.presentation.screens.face_control import FaceVerificationOverlay
    from src.presentation.widgets import metrics

    overlay = FaceVerificationOverlay(theme)
    qtbot.addWidget(overlay)

    assert overlay.objectName() == "PinScreen"
    assert overlay._retry.property("variant") == "keypad"
    assert overlay._close.minimumHeight() == metrics.KEYPAD_BUTTON_SIZE


# --------------------------------------------------------------------------- #
# ROOT paneli — mağaza əhatəsi + tərs hədd
# --------------------------------------------------------------------------- #


@requires_qt
def test_an_empty_face_scope_is_explained_as_global_not_disabled(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Bənd 15: boş seçim «söndürülüb» DEYİL, qlobal toggle-a tabedir."""
    from src.presentation.screens.group_d import RootControlScreen

    screen = RootControlScreen(theme)
    qtbot.addWidget(screen)

    screen.set_face_scope([{"id": str(uuid.uuid4()), "name": "Bellona 28 May", "active": "0"}])
    assert "qlobal" in screen._face_scope_summary.text().lower()

    screen.set_face_scope([{"id": str(uuid.uuid4()), "name": "Bellona 28 May", "active": "1"}])
    assert "YALNIZ" in screen._face_scope_summary.text()


@requires_qt
def test_toggling_a_store_emits_the_scope_signal(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_d import RootControlScreen

    store_id = str(uuid.uuid4())
    screen = RootControlScreen(theme)
    qtbot.addWidget(screen)
    screen.set_face_scope([{"id": store_id, "name": "Bellona 28 May", "active": "0"}])

    seen: list[tuple[str, bool]] = []
    screen.face_scope_changed.connect(lambda key, active: seen.append((key, active)))
    screen._face_scope_toggles[store_id].setChecked(True)

    assert seen == [(store_id, True)]

    # Rədd edilmiş yazı açarı GERİ qaytarır — ekran YALAN göstərməməlidir.
    screen.reject_face_scope_change(store_id)
    assert screen._face_scope_toggles[store_id].isChecked() is False


@requires_qt
def test_the_face_scope_never_enters_the_limit_namespace(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Mağaza əhatəsi `system_limits` sətri DEYİL — `collected()`-ə düşməməlidir."""
    from src.domain.policies import SystemLimitKey
    from src.presentation.screens.group_d import RootControlScreen

    store_id = str(uuid.uuid4())
    screen = RootControlScreen(theme)
    qtbot.addWidget(screen)
    screen.set_face_scope([{"id": store_id, "name": "Bellona 28 May", "active": "1"}])

    collected = screen.collected()
    known = {key.value for key in SystemLimitKey}
    assert set(collected["limits"]) <= known  # type: ignore[arg-type]
    assert store_id not in collected["limits"]  # type: ignore[operator]


@requires_qt
def test_an_inverted_tolerance_pair_is_shown_as_a_warning(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Bənd 7 + 12: tərs cüt SÜKUTLA keçmir — Root faktiki davranışı görməlidir."""
    from src.presentation.screens.group_d import RootControlScreen

    screen = RootControlScreen(theme)
    qtbot.addWidget(screen)

    screen.set_face_tolerance(dict(preview_data.FACE_TOLERANCE))
    assert screen._face_tolerance_warning.isVisibleTo(screen) is False

    screen.set_face_tolerance(
        {"match": "0.60", "low_confidence": "0.90", "inverted": "1", "band_enabled": "0"}
    )
    assert screen._face_tolerance_warning.isVisibleTo(screen) is True
    assert "FAIL-CLOSED" in screen._face_tolerance_warning.text()


def test_the_root_controller_reads_the_inverted_flag_from_the_domain() -> None:
    """Domen məntiqi TƏKRARLANMIR — `FaceToleranceBand.resolve` çağırılır."""
    source = (_REPO_ROOT / "src" / "presentation" / "controllers" / "root_control.py").read_text(
        encoding="utf-8"
    )

    assert "FaceToleranceBand.resolve(" in source, (
        "ROOT kontrolleri tərs-hədd qərarını ÖZÜ hesablayır — domen qaydasının "
        "ikinci nüsxəsi yaranıb."
    )


# --------------------------------------------------------------------------- #
# Kamera Dashboard — konseptual sərhəd + aşağı-etibar nişanı
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_operator_queue_states_the_boundary_between_identity_and_presence(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Operator SƏHV GÜVƏN hissi yaşamamalıdır (konseptual sərhəd)."""
    from PySide6.QtWidgets import QLabel

    from src.presentation.screens.group_b import OperatorQueueScreen

    screen = OperatorQueueScreen(theme, assigned_stores=["Bellona 28 May"])
    qtbot.addWidget(screen)

    texts = " ".join(label.text() for label in screen.findChildren(QLabel))
    assert "KİMDİR" in texts
    assert "FİZİKİ" in texts
    assert "ƏVƏZ ETMİR" in texts


@requires_qt
def test_a_low_confidence_row_carries_a_chip(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Bənd 12 — nişan MÖVCUD `Chip` naxışı ilə, sətri BLOKLAMADAN."""
    from src.presentation.screens.group_b import OperatorQueueScreen, QueueEntry
    from src.presentation.widgets.primitives import Chip

    screen = OperatorQueueScreen(theme, assigned_stores=["Bellona 28 May"])
    qtbot.addWidget(screen)

    screen.set_entries(
        [
            QueueEntry(
                request_id="q1",
                employee_name="Aysel Quliyeva",
                store_name="Bellona 28 May",
                position_name="Satış",
                kind="Giriş Təsdiqi",
                timestamp_text="09:42",
                waiting_text="1 dəq",
            ),
            QueueEntry(
                request_id="q2",
                employee_name="Murad Əliyev",
                store_name="Bellona 28 May",
                position_name="Anbar",
                kind="Qayıdış Təsdiqi",
                timestamp_text="11:58",
                waiting_text="3 dəq",
                is_low_confidence=True,
            ),
        ]
    )

    chips = [chip.text() for row in screen._rows for chip in row.findChildren(Chip)]
    assert chips.count("aşağı-etibarlı üz təsdiqi") == 1, "Nişan YALNIZ işarələnmiş sətirdədir"
    assert screen.visible_rows == 2, "Nişan sətri BLOKLAMIR"


# --------------------------------------------------------------------------- #
# Profil kartı (bənd 13)
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_profile_card_recommends_without_blocking(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_g import ProfileScreen

    screen = ProfileScreen(
        theme,
        full_name="Aysel Quliyeva",
        role_name="HR Admin",
        store_name="Baş ofis",
        member_since="2024-cü ildən",
    )
    qtbot.addWidget(screen)

    screen.set_face_enrollment(dict(preview_data.FACE_PROFILE_ENROLLMENT))
    assert screen._face_chip.text() == "Köhnəlib"
    assert screen._face_chip.property("chip") == "warning"
    assert "BLOKLAMIR" in screen._face_note.text()

    screen.set_face_enrollment(
        {"state": "ENROLLED", "enrolled_at": "01.08.2026", "reminder_months": "12"}
    )
    assert screen._face_chip.property("chip") == "success"

    # Boş sözlük YALANÇI xəbərdarlıq doğurmur.
    screen.set_face_enrollment({})
    assert screen._face_note.text() == ""
