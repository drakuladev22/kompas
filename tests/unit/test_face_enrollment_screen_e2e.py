"""`FaceEnrollmentScreen` ↔ `FaceEnrollmentController` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, üçüncü dalğa)
──────────────────────────────────────────────────────────────────────────────
`test_face_control_screen.py` ekranı VƏ kontrolleri ayrı-ayrı ölçür:
`_EnrollmentScreen` sahtəsi kontrollerin `set_result`/`set_camera`/`set_frames`
çağırışlarını YALNIZ siyahıya yazır, heç bir REAL widget qurmur; ekran
testləri isə (`test_the_enrollment_screen_switches_to_re_enrollment_mode` və s.)
heç vaxt `FaceEnrollmentController.attach()` çağırmır. Yəni `[Çək]` /
`[Yadda Saxla]` / `[Yenidən Çək]` düymələrinin REAL kliki heç yerdə
kontrollerə çatmır — biometrik qeydiyyat kimi həssas bir sahədə bu boşluq
xüsusilə bahalıdır. Burada hər ikisi (ekran + kontroller) FAKTİKİ qurulur.

Kameraya və şəbəkəyə ÇIXILMIR: `ApplicationContext.face_engine()` və
`FaceEnrollmentUseCase` tam sahtə ilə əvəz olunur — yalnız GUI ↔ kontroller
sərhədi ölçülür (`background_task.py` naxışı, `test_devices_screen_e2e.py`
ilə eyni fəlsəfə).

Sahtələr BU FAYLDA yerlidir (`tests/fixtures/fakes.py`-a TOXUNULMUR) — paralel
işləyən agentlər həmin ortaq faylı dəyişə bilər.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from src.application.use_cases.face_control import FaceEnrollmentResult
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import PermissionFlag, RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.face_recognition import FaceEnrollmentFrameOutcome
from src.domain.value_objects.identifiers import EmployeeId, PositionId, TenantId
from src.presentation.background_task import InlineExecutor
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
NOW = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)


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


def _hr_admin() -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code="HR_ADMIN",
        name_az="HR Admin",
        priority=RolePriority.OPERATIONAL,
        tenant_id=TENANT,
        is_system=True,
    )
    position.grant(PermissionFlag(code="can_manage_employees", category="test"))
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Aysel",
        last_name="Quliyeva",
        username=Username("a.quliyeva"),
        has_password=True,
    )


# --------------------------------------------------------------------------- #
# Sahtələr — YALNIZ kontrollerin faktiki oxuduğu atributlar
# --------------------------------------------------------------------------- #


class _Row(dict):  # type: ignore[type-arg]
    """`row["sütun"]` müqaviləsi ilə uyğun gələn sətir."""


class _Cursor:
    def __init__(self, rows: list[_Row]) -> None:
        self._rows = rows

    def fetchall(self) -> list[_Row]:
        return self._rows


class _Connection:
    def __init__(self, rows: list[_Row]) -> None:
        self._rows = rows

    def execute(self, _sql: str, _params: Any = ()) -> _Cursor:
        return _Cursor(self._rows)


class _Uow:
    def __init__(self, rows: list[_Row]) -> None:
        self.connection = _Connection(rows)


class _Limits:
    def get_int(self, _tenant_id: Any, _key: str, default: int) -> int:
        return default

    def get_str(self, _tenant_id: Any, _key: str, default: str) -> str:
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


class _Session:
    def __init__(
        self,
        *,
        rows: list[_Row],
        enrollment: _EnrollmentUseCase | None = None,
        re_enrollment: _ReEnrollmentUseCase | None = None,
    ) -> None:
        self.tenant_id = TENANT
        self.uow = _Uow(rows)
        self.limits = _Limits()
        self.face_enrollment = enrollment
        self.face_re_enrollment = re_enrollment
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Context:
    """`ApplicationContext` müqaviləsinin minimal təkrarı — HƏR ÇAĞIRIŞ YENİ sessiya."""

    def __init__(
        self, session_factory: Callable[[], _Session], *, camera_available: bool = True
    ) -> None:
        self._session_factory = session_factory
        self._camera_available = camera_available
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = self._session_factory()
        self.sessions.append(created)
        yield created

    def face_engine(self) -> tuple[Any, Any]:
        camera = type("_Camera", (), {"is_available": lambda _self: self._camera_available})()
        return camera, camera


class _DeferredExecutor:
    """`InlineExecutor`-dan FƏRQLİ olaraq işi DƏRHAL yerinə yetirmir.

    «Birinci klikin işi hələ QAÇIR» vəziyyətini deterministik şəkildə
    simulyasiya edir: real `QThreadPool` ilə eyni ssenarini sınamaq
    (sürətli ikiqat klik) sap vaxtlamasından asılı olub qeyri-sabit test
    yaradardı. Burada iş `flush()` çağırılana qədər NÖVBƏDƏ qalır — iki
    klik arasında ekranın buraxdığı boşluq AÇIQ görünür.
    """

    def __init__(self) -> None:
        self.pending: list[Callable[[], None]] = []

    @property
    def runs_inline(self) -> bool:
        # Sinxron BAĞLANTI növü tələb olunur ki, `flush()` içindəki `emit`
        # hadisə dövrəsi gözləmədən dərhal `_deliver`-ə çatsın.
        return True

    def submit(self, job: Callable[[], None]) -> None:
        self.pending.append(job)

    def flush(self) -> None:
        jobs, self.pending = self.pending, []
        for job in jobs:
            job()


def _employee_row(employee_id: EmployeeId, *, enrolled_at: datetime | None = None) -> _Row:
    return _Row(
        id=employee_id,
        first_name="Murad",
        last_name="Əliyev",
        face_enrolled_at=enrolled_at,
        store_name="Bellona 28 May",
    )


def _accepted_result(employee_id: EmployeeId) -> FaceEnrollmentResult:
    return FaceEnrollmentResult(
        employee_id=employee_id,
        accepted=True,
        message_az="Üz qeydiyyatı tamamlandı.",
        frames=(
            FaceEnrollmentFrameOutcome(index=1, accepted=True, quality=0.81),
            FaceEnrollmentFrameOutcome(
                index=2, accepted=False, quality=0.22, reason_az="Kadrda üz aşkarlanmadı"
            ),
            FaceEnrollmentFrameOutcome(
                index=3, accepted=False, quality=0.30, reason_az="Kadr çox qaranlıqdır"
            ),
        ),
        enrolled_at=NOW,
    )


# --------------------------------------------------------------------------- #
# 1. Real klik → kamera işi → commit → REAL cədvəldə FƏRQLİ səbəblər
# --------------------------------------------------------------------------- #


@requires_qt
def test_capturing_via_the_real_button_commits_and_renders_distinct_frame_reasons(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.face_control import FaceEnrollmentController
    from src.presentation.screens.face_control import FaceEnrollmentScreen

    subject = EmployeeId(uuid.uuid4())
    use_case = _EnrollmentUseCase(result=_accepted_result(subject))
    context = _Context(lambda: _Session(rows=[_employee_row(subject)], enrollment=use_case))
    screen = FaceEnrollmentScreen(theme)
    qtbot.addWidget(screen)
    FaceEnrollmentController(context, _hr_admin(), executor=InlineExecutor()).attach(screen)

    screen._subject.setCurrentIndex(0)
    _click(screen, "Çək")

    assert len(use_case.calls) == 1
    assert any(s.commits == 1 for s in context.sessions), "Qəbul edilən cəhd COMMIT edilməlidir"

    from PySide6.QtWidgets import QLabel

    table = screen.frames_layout().itemAt(0).widget()
    texts = " ".join(label.text() for label in table.findChildren(QLabel))
    # Hər rədd edilən kadrın SƏBƏBİ FƏRQLİDİR — «uğursuz» deyil, konkret mətn
    # (bənd 1 fəlsəfəsi, `_frame_row` şərhi).
    assert "Kadrda üz aşkarlanmadı" in texts
    assert "Kadr çox qaranlıqdır" in texts


# --------------------------------------------------------------------------- #
# 2. Kamera əlçatmazdır — düymə DEAKTİVDİR, klik ÇÖKMƏMƏLİDİR
# --------------------------------------------------------------------------- #


@requires_qt
def test_capture_is_a_no_op_when_the_camera_is_unavailable(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.face_control import (
        CAMERA_UNAVAILABLE,
        FaceEnrollmentController,
    )
    from src.presentation.screens.face_control import FaceEnrollmentScreen

    subject = EmployeeId(uuid.uuid4())
    use_case = _EnrollmentUseCase(result=_accepted_result(subject))
    context = _Context(
        lambda: _Session(rows=[_employee_row(subject)], enrollment=use_case),
        camera_available=False,
    )
    screen = FaceEnrollmentScreen(theme)
    qtbot.addWidget(screen)
    FaceEnrollmentController(context, _hr_admin(), executor=InlineExecutor()).attach(screen)

    screen._subject.setCurrentIndex(0)
    assert screen._capture.isEnabled() is False, "Kamera əlçatmazkən düymə basıla bilməməlidir"

    _click(screen, "Çək")  # deaktiv düymə — Qt `click()` heç nə etmir, ÇÖKMƏMƏLİDİR

    assert use_case.calls == [], "Deaktiv düymə barədə klik use case-ə çatmamalıdır"
    assert screen._camera_state.text() == CAMERA_UNAVAILABLE


# --------------------------------------------------------------------------- #
# 3. Boş səbəblə [Yadda Saxla] — real klik, domen istisnasına ÇATMIR
# --------------------------------------------------------------------------- #


@requires_qt
def test_saving_a_re_enrollment_without_a_reason_never_reaches_the_use_case(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.face_control import FaceEnrollmentController
    from src.presentation.screens.face_control import FaceEnrollmentScreen

    subject = EmployeeId(uuid.uuid4())
    re_use_case = _ReEnrollmentUseCase(result=_accepted_result(subject))
    rows = [_employee_row(subject, enrolled_at=NOW)]
    context = _Context(lambda: _Session(rows=rows, re_enrollment=re_use_case))
    screen = FaceEnrollmentScreen(theme)
    qtbot.addWidget(screen)
    FaceEnrollmentController(context, _hr_admin(), executor=InlineExecutor()).attach(screen)

    screen._subject.setCurrentIndex(0)
    assert screen.mode() == "RE_ENROLL"

    _click(screen, "Yadda Saxla")  # boş sahə ilə — ÇÖKMƏMƏLİDİR

    assert re_use_case.calls == []
    assert "səbəb" in screen._result.text().lower()


# --------------------------------------------------------------------------- #
# 4. Domen rədd cavabı — real klik, mesaj göstərilir, ÇÖKMÜR, commit YOXDUR
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_domain_rejection_during_capture_shows_the_message_without_crashing(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.face_control import FaceEnrollmentController
    from src.presentation.screens.face_control import FaceEnrollmentScreen

    subject = EmployeeId(uuid.uuid4())
    denial = KompasOSError(
        "self enroll", user_message="Öz üzünüzü özünüz qeydiyyata sala bilməzsiniz."
    )
    use_case = _EnrollmentUseCase(result=_accepted_result(subject), error=denial)
    context = _Context(lambda: _Session(rows=[_employee_row(subject)], enrollment=use_case))
    screen = FaceEnrollmentScreen(theme)
    qtbot.addWidget(screen)
    FaceEnrollmentController(context, _hr_admin(), executor=InlineExecutor()).attach(screen)

    screen._subject.setCurrentIndex(0)
    _click(screen, "Çək")  # ÇÖKMƏMƏLİDİR

    assert screen._result.text() == denial.user_message
    assert all(s.commits == 0 for s in context.sessions), "Rədd edilən cəhd COMMIT edilməməlidir"


# --------------------------------------------------------------------------- #
# 5. DÜZƏLDİLDİ — fon işinin Qt valideyni artıq VAR (`ui` sahibi)
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_background_task_is_parented_to_the_screen_like_the_device_pattern(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.face_control import FaceEnrollmentController
    from src.presentation.screens.face_control import FaceEnrollmentScreen

    subject = EmployeeId(uuid.uuid4())
    use_case = _EnrollmentUseCase(result=_accepted_result(subject))
    context = _Context(lambda: _Session(rows=[_employee_row(subject)], enrollment=use_case))
    screen = FaceEnrollmentScreen(theme)
    qtbot.addWidget(screen)
    controller = FaceEnrollmentController(context, _hr_admin(), executor=InlineExecutor())
    controller.attach(screen)

    screen._subject.setCurrentIndex(0)
    _click(screen, "Çək")

    assert controller._task is not None
    assert controller._task.parent() is screen


# --------------------------------------------------------------------------- #
# 6. DÜZƏLDİLDİ — sürətli ikiqat klikə qarşı `is_running` qapısı əlavə edildi
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_second_click_while_the_first_capture_is_still_running_is_rejected(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.face_control import FaceEnrollmentController
    from src.presentation.screens.face_control import FaceEnrollmentScreen

    subject = EmployeeId(uuid.uuid4())
    use_case = _EnrollmentUseCase(result=_accepted_result(subject))
    executor = _DeferredExecutor()
    context = _Context(lambda: _Session(rows=[_employee_row(subject)], enrollment=use_case))
    screen = FaceEnrollmentScreen(theme)
    qtbot.addWidget(screen)
    FaceEnrollmentController(context, _hr_admin(), executor=executor).attach(screen)
    screen._subject.setCurrentIndex(0)

    _click(screen, "Çək")  # BİRİNCİ klik — iş hələ QAÇIR (`_DeferredExecutor`)
    _click(screen, "Çək")  # İKİNCİ klik — birinci HƏLƏ BİTMƏYİB, düymə hələ aktivdir
    executor.flush()

    assert len(use_case.calls) == 1, "İki sürətli klik İKİ paralel `enroll()` çağırışı yaratdı"
