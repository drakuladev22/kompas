"""Panel girişindəki «Üzlə daxil ol» — düymə, kontroller və qapıları.

İstifadəçi tələbi: «kiosk ekranında qeyd etdiyim facecontrol buttonu username
password ekranında da olmalıdır».

──────────────────────────────────────────────────────────────────────────────
ƏN VACİB TEST HANSIDIR
──────────────────────────────────────────────────────────────────────────────
`test_not_applicable_never_grants_a_panel_login`.

Kioskda üz qapısı PIN-dən SONRA işləyir — yəni İKİNCİ amildir və modul
söndürüldükdə (`NOT_APPLICABLE`) axının «yalnız PIN» rejiminə düşməsi
DOĞRUDUR. Panel girişində isə üz TƏK amildir: eyni yumşalma buraya
köçürülsəydi, modulu bağlı kirayəçidə istifadəçi adını yazıb düyməni basmaq
panelə girmək üçün kifayət edərdi — yəni şifrə sükutla ləğv olardı.

Bu fərq bir sətirlik şərtdə yaşayır (`GRANTING_OUTCOMES`), ona görə həm sətrin
özü, həm də onun davranışı ayrıca qapıdadır.

Sahtələr BU FAYLDA yerlidir — `tests/fixtures/fakes.py`-a toxunulmur (eyni
qərar `test_face_control_screen.py`-də verilib).
"""

from __future__ import annotations

import uuid
from typing import Any, Final

import pytest

from src.application.use_cases.face_control import FaceGateDecision, FaceGateOutcome
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.face_recognition import FaceTriggerContext
from src.domain.value_objects.identifiers import EmployeeId, PositionId, TenantId
from src.presentation.controllers.face_login import (
    GRANTING_OUTCOMES,
    FaceLoginController,
)
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())


# --------------------------------------------------------------------------- #
# Yerli sahtələr
# --------------------------------------------------------------------------- #


def _employee(*, code: str = "HR_ADMIN", must_change_password: bool = False) -> Employee:
    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=Position(
            position_id=PositionId(uuid.uuid4()),
            code=code,
            name_az=code,
            priority=RolePriority.OPERATIONAL,
            tenant_id=TENANT,
            is_system=True,
        ),
        first_name="Aygün",
        last_name="Əliyeva",
        username=Username("a.eliyeva"),
        has_password=True,
    )
    employee.must_change_password = must_change_password
    return employee


class _Employees:
    def __init__(self, employee: Employee | None) -> None:
        self._employee = employee
        self.asked: list[str] = []

    def get_by_username(self, tenant_id: TenantId, username: Username) -> Employee | None:
        self.asked.append(str(username))
        if self._employee is None:
            return None
        return self._employee if str(username) == str(self._employee.username) else None


class _Audit:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.entries.append(kwargs)


class _Verification:
    """`FaceVerificationUseCase` sahtəsi — YALNIZ `verify`."""

    def __init__(self, outcome: FaceGateOutcome, *, error: Exception | None = None) -> None:
        self._outcome = outcome
        self._error = error
        self.calls: list[FaceTriggerContext] = []

    def verify(
        self, *, tenant_id: TenantId, employee: Employee, trigger_context: FaceTriggerContext
    ) -> FaceGateDecision:
        self.calls.append(trigger_context)
        if self._error is not None:
            raise self._error
        return FaceGateDecision(
            employee_id=employee.id,
            trigger_context=trigger_context,
            outcome=self._outcome,
            message_az="sahtə nəticə",
        )


class _Uow:
    def __init__(self, employees: _Employees, audit: _Audit) -> None:
        self.employees = employees
        self.audit = audit


class _Toggles:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.asked: list[str] = []

    def is_enabled(self, tenant_id: TenantId, module_key: str) -> bool:
        self.asked.append(module_key)
        return self.enabled


class _Session:
    def __init__(self, context: _Context) -> None:
        self._context = context
        self.tenant_id = TENANT
        self.uow = _Uow(context.employees, context.audit)
        self.toggles = context.toggles
        self.face_verification = context.verification

    def commit(self) -> None:
        self._context.commits += 1

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _Context:
    """`ApplicationContext` sahtəsi — yalnız `session()` və sayğaclar."""

    def __init__(
        self,
        *,
        employee: Employee | None,
        outcome: FaceGateOutcome = FaceGateOutcome.ALLOWED,
        error: Exception | None = None,
        module_enabled: bool = True,
    ) -> None:
        self.tenant_id = TENANT
        self.employees = _Employees(employee)
        self.audit = _Audit()
        self.toggles = _Toggles(module_enabled)
        self.verification = _Verification(outcome, error=error)
        self.commits = 0
        self.user_ids: list[EmployeeId | None] = []

    def session(self, *, user_id: EmployeeId | None = None) -> _Session:
        self.user_ids.append(user_id)
        return _Session(self)


def _controller(context: _Context) -> FaceLoginController:
    return FaceLoginController(context)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Qapı — hansı nəticə giriş verir
# --------------------------------------------------------------------------- #


def test_not_applicable_never_grants_a_panel_login() -> None:
    """Modul söndürülübsə üzlə giriş VERİLMİR (bax fayl başlığı).

    Kioskdakı `allows_operation` xassəsi `NOT_APPLICABLE` üçün `True`-dur —
    ona görə burada həmin xassə İŞLƏDİLMİR və ayrıca siyahı var. Bu test o
    siyahının kiosk məntiqinə «sadələşdirilməsinin» qarşısını alır.
    """
    assert FaceGateOutcome.NOT_APPLICABLE not in GRANTING_OUTCOMES
    assert FaceGateOutcome.NOT_APPLICABLE.allows_operation is True

    context = _Context(employee=_employee(), outcome=FaceGateOutcome.NOT_APPLICABLE)
    outcome = _controller(context).authenticate("a.eliyeva")

    assert outcome.failed
    assert "Şifrənizlə" in outcome.message
    assert context.audit.entries == []
    # Heç nə yazılmayıb — boş tranzaksiya commit EDİLMİR.
    assert context.commits == 0


def test_only_the_two_allowing_outcomes_open_the_panel() -> None:
    """Siyahı DƏQİQ iki nəticədən ibarətdir.

    `ALLOWED_LOW_CONFIDENCE` içəridədir, çünki o, rədd deyil — bal aşağı-etibar
    zolağındadır və qeyd yalnız Kamera Operatoru üçün nişanlanır (bənd 12).
    """
    assert (
        frozenset({FaceGateOutcome.ALLOWED, FaceGateOutcome.ALLOWED_LOW_CONFIDENCE})
        == GRANTING_OUTCOMES
    )

    for outcome_value in FaceGateOutcome:
        context = _Context(employee=_employee(), outcome=outcome_value)
        result = _controller(context).authenticate("a.eliyeva")
        assert result.succeeded is (outcome_value in GRANTING_OUTCOMES), outcome_value.value


def test_a_successful_face_login_is_audited_as_a_login() -> None:
    """Audit hərəkəti `ADMIN_LOGIN`-dir, üsul isə `FACE`.

    Ayrı hərəkət adı seçsəydik, «kim nə vaxt girdi?» hesabatı üzlə girişləri
    GÖRMƏZDİ — yəni ən həssas yol ən az izi buraxardı.
    """
    context = _Context(employee=_employee())

    outcome = _controller(context).authenticate("a.eliyeva")

    assert outcome.succeeded
    assert len(context.audit.entries) == 1
    entry = context.audit.entries[0]
    assert entry["action"] == "ADMIN_LOGIN"
    assert entry["after_state"]["method"] == "FACE"
    assert context.commits == 1
    assert context.verification.calls == [FaceTriggerContext.LOGIN]


def test_the_verification_runs_under_the_subjects_own_session() -> None:
    """Sessiya işçinin `user_id`-si ilə açılır — RLS və audit aktoru üçün."""
    employee = _employee()
    context = _Context(employee=employee)

    _controller(context).authenticate("a.eliyeva")

    assert employee.id in context.user_ids


# --------------------------------------------------------------------------- #
# Şifrə yolunun qapıları TƏKRARLANIR
# --------------------------------------------------------------------------- #


def test_a_forced_password_change_cannot_be_skipped_with_a_face() -> None:
    """`must_change_password` üzlə YAN KEÇİLMİR.

    Keçilsəydi, şifrəsi sıfırlanmış hesab onu heç vaxt dəyişməzdi: dəyişdirmə
    məhz şifrə yolundadır.
    """
    context = _Context(employee=_employee(must_change_password=True))

    outcome = _controller(context).authenticate("a.eliyeva")

    assert outcome.failed
    assert outcome.must_change_password
    # Kamera ÜMUMİYYƏTLƏ işə düşmür — qapı ondan ƏVVƏLdir.
    assert context.verification.calls == []


def test_a_domain_login_ban_still_applies() -> None:
    """`assert_admin_login_allowed()` üz yolunda da işləyir."""
    employee = _employee()
    context = _Context(employee=employee)

    def _refuse() -> None:
        raise KompasOSError("qadağan", user_message="Bu hesabla panelə giriş qadağandır.")

    employee.assert_admin_login_allowed = _refuse  # type: ignore[method-assign]

    outcome = _controller(context).authenticate("a.eliyeva")

    assert outcome.failed
    assert outcome.message == "Bu hesabla panelə giriş qadağandır."
    assert context.verification.calls == []


def test_an_unknown_username_gives_the_generic_message() -> None:
    """Hesabın mövcudluğu AÇIQLANMIR — hesab sadalamanın qarşısı alınır."""
    context = _Context(employee=None)

    outcome = _controller(context).authenticate("yoxdur")

    assert outcome.failed
    assert outcome.message == "Üzlə giriş alınmadı. Şifrənizlə daxil olun."
    assert context.verification.calls == []


def test_an_empty_username_is_a_form_error_not_a_security_message() -> None:
    """Boş sahə istifadəçi səhvidir — ümumi mesaj onu nasazlıq kimi göstərərdi."""
    context = _Context(employee=_employee())

    outcome = _controller(context).authenticate("   ")

    assert outcome.failed
    assert "istifadəçi adınızı" in outcome.message
    assert context.employees.asked == []


def test_an_unexpected_failure_fails_closed() -> None:
    """Nasazlıq «buraxaq»a çevrilmir — istifadəçi şifrə yoluna qaytarılır."""
    context = _Context(employee=_employee(), error=RuntimeError("kamera öldü"))

    outcome = _controller(context).authenticate("a.eliyeva")

    assert outcome.failed
    assert "Şifrənizlə" in outcome.message
    assert context.audit.entries == []


# --------------------------------------------------------------------------- #
# Düymənin görünmə şərti
# --------------------------------------------------------------------------- #


def test_the_button_hides_when_the_module_is_off() -> None:
    """Modul bağlıdırsa düymə göstərilmir — işləməyən düymə nasazlıq kimi oxunur."""
    context = _Context(employee=_employee(), module_enabled=False)

    assert _controller(context).available() is False


def test_availability_never_opens_the_camera_device() -> None:
    """Kamera cihazı AÇILMIR — yalnız kitabxana + modul soruşulur.

    `is_available()` çağırsaydıq (kioskun etdiyi kimi), hər idarəçinin
    veb-kamerası proqram açıq olduğu müddətcə tutulu qalardı. Səbəb
    `FaceLoginController.available` başlığındadır; bu test onu qoruyur.
    """
    import ast
    import inspect
    import textwrap

    # DOCSTRING KƏNARDA QALIR: o, məhz `is_available()`-in NİYƏ çağırılmadığını
    # izah edir. Xam mətndə axtarsaydıq, test öz izahına ilişərdi.
    function = ast.parse(textwrap.dedent(inspect.getsource(FaceLoginController.available))).body[0]
    assert isinstance(function, ast.FunctionDef)
    statements = function.body
    if isinstance(statements[0], ast.Expr) and isinstance(statements[0].value, ast.Constant):
        statements = statements[1:]
    code = "\n".join(ast.unparse(node) for node in statements)

    assert "camera_available()" in code
    assert "is_available()" not in code


# --------------------------------------------------------------------------- #
# Ekran — Qt tələb edir
# --------------------------------------------------------------------------- #


@pytest.fixture(params=["light", "dark"])
def theme(request, qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(
        preference=ThemeMode.LIGHT if request.param == "light" else ThemeMode.DARK
    )
    manager.apply(qt_app)
    return manager


@requires_qt
def test_the_face_button_is_hidden_until_it_is_known_to_work(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Defolt GİZLİDİR — sönük düymə «niyə işləmir?» sualı yaradır."""
    from src.presentation.screens.group_a_entry import AdminLoginScreen

    screen = AdminLoginScreen(theme)
    qtbot.addWidget(screen)

    assert screen.face_button().isVisibleTo(screen) is False
    screen.set_face_login_available(True)
    assert screen.face_button().isVisibleTo(screen) is True


@requires_qt
def test_the_face_button_sends_only_the_username(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Şifrə sahəsi OXUNMUR — üz onu əvəz edir, ona əlavə olunmur."""
    from src.presentation.screens.group_a_entry import AdminLoginScreen

    screen = AdminLoginScreen(theme)
    qtbot.addWidget(screen)
    screen.set_face_login_available(True)

    sent: list[str] = []
    screen.face_login_requested.connect(sent.append)

    screen._username.set_text("  a.eliyeva  ")
    screen._password.set_text("şifrə-yazılıb")
    screen.face_button().click()

    assert sent == ["a.eliyeva"]


@requires_qt
def test_an_empty_username_marks_the_username_field(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Xəta ŞİFRƏ sahəsində deyil — əskik olan məhz istifadəçi adıdır."""
    from src.presentation.screens.group_a_entry import AdminLoginScreen

    screen = AdminLoginScreen(theme)
    qtbot.addWidget(screen)
    screen.set_face_login_available(True)

    sent: list[str] = []
    screen.face_login_requested.connect(sent.append)
    screen.face_button().click()

    assert sent == []
    assert screen._username.has_error is True
    assert screen._password.has_error is False


@requires_qt
def test_busy_blocks_both_login_paths(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Kamera çəkilişi gedərkən şifrə ilə İKİNCİ axın başlaya bilməz."""
    from src.presentation.screens.group_a_entry import AdminLoginScreen

    screen = AdminLoginScreen(theme)
    qtbot.addWidget(screen)

    screen.set_busy(True)
    assert screen._submit.isEnabled() is False
    assert screen.face_button().isEnabled() is False

    screen.set_busy(False)
    assert screen._submit.isEnabled() is True
    assert screen.face_button().isEnabled() is True
