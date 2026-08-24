"""Üz qeydiyyatı UI sapını BLOKLAMIR (SETUP-1 Faza 3).

──────────────────────────────────────────────────────────────────────────────
NƏYİ QORUYUR
──────────────────────────────────────────────────────────────────────────────
Üz qeydiyyatı üç ağır addımdan ibarətdir: kamera kadrı çəkir, `dlib` hər kadr
üçün 128-ölçülü kodlaşdırma hesablayır, sonra baza yazısı gedir. Ölçmə deyil,
tərif: bu, saniyələrlə çəkən CPU işidir.

GUI sapında icra olunsaydı, Windows pəncərəni «Cavab vermir» kimi işarələyər,
operator isə proqramı bağlamağa çalışardı — məhz üz məlumatı yazılarkən.

Ölçülən şey İŞİN NƏTİCƏSİ deyil (onu `test_face_control.py` ölçür), məhz
İCRA YERİdir: iş GUI sapından KƏNARDA getməlidir və nəticə siqnalla geri
qayıtmalıdır.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


class _Screen:
    """`FaceEnrollmentScreen` əvəzinə minimal qəbuledici."""

    def __init__(self) -> None:
        self.results: list[dict[str, str]] = []
        self.frames: list[list[dict[str, str]]] = []
        self.busy: list[bool] = []

    def set_result(self, row: dict[str, str]) -> None:
        self.results.append(row)

    def set_frames(self, rows: list[dict[str, str]]) -> None:
        self.frames.append(rows)

    def set_busy(self, busy: bool) -> None:  # pragma: no cover - hamısı istifadə olunmur
        self.busy.append(busy)


def _drain(qt_app: Any, delivered: list[Any], *, seconds: float = 5.0) -> None:
    """Nəticə gələnə qədər hadisə dövrəsini işlədir.

    Fon işi TƏRİFƏ GÖRƏ dərhal bitmir və nəticə Qt siqnalı ilə əsas sapa
    POSTLANIR — hadisə dövrəsi işləmədən o siqnal heç vaxt çatmazdı. Sabit
    `sleep` əvəzinə şərtə görə gözləmək testi maşın sürətindən asılı etmir.
    """
    deadline = time.monotonic() + seconds
    while not delivered and time.monotonic() < deadline:
        qt_app.processEvents()


@requires_qt
def test_the_enrollment_work_leaves_the_gui_thread(qt_app) -> None:  # type: ignore[no-untyped-def]
    """`dlib` kodlaşdırması GUI sapında qalsaydı pəncərə donardı."""
    from PySide6.QtCore import QThread

    from src.presentation.controllers.face_control import run_enrollment_job

    gui_thread = QThread.currentThread()
    seen: dict[str, Any] = {}

    def job() -> object:
        seen["thread"] = QThread.currentThread()
        return "hazırdır"

    delivered: list[object] = []
    task = run_enrollment_job(qt_app, job, on_success=delivered.append, on_failure=delivered.append)
    _drain(qt_app, delivered)

    assert task is not None
    assert seen["thread"] is not gui_thread, "üz emalı GUI sapında icra olundu"
    assert delivered == ["hazırdır"]


@requires_qt
def test_a_failure_is_delivered_not_swallowed(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Fon sapındakı istisna İTMƏMƏLİDİR — operator səbəbi görməlidir."""
    from src.presentation.controllers.face_control import run_enrollment_job

    def job() -> object:
        raise RuntimeError("kamera açılmadı")

    failures: list[object] = []
    task = run_enrollment_job(qt_app, job, on_success=lambda _: None, on_failure=failures.append)
    _drain(qt_app, failures)

    assert task is not None
    assert failures and "kamera açılmadı" in str(failures[0])


# --------------------------------------------------------------------------- #
# PERF-6 #7 — kamera aparat probu (`refresh()`) GUI sapını BLOKLAMIR
# --------------------------------------------------------------------------- #
#
# Prob ƏVVƏL açıq DB sessiyasının İÇİNDƏ, GUI sapında sinxron çağırılırdı
# (bax `face_control.py::FaceEnrollmentController.refresh` başlığı) —
# yuxarıdakı ikisi YALNIZ yazı yolunu (`run_enrollment_job`) ölçür, probu YOX.
# Gələcək bir dəyişiklik probu yenidən sessiyanın içinə salsa, bu test onu
# ya `refresh()`-in özü bloklamasından (aşağıda taymautla), ya da sapın GUI
# sapı ilə eyni olmasından tutmalıdır.


class _Cursor:
    def fetchall(self) -> list[Any]:
        return []


class _Connection:
    def execute(self, _sql: str, _params: Any = ()) -> _Cursor:
        return _Cursor()


class _Uow:
    def __init__(self) -> None:
        self.connection = _Connection()


class _Limits:
    def get_int(self, _tenant_id: Any, _key: str, default: int) -> int:
        return default


class _EnrollmentSession:
    """`_enrollment_rows`/`_limit_int`-in oxuduğu minimal müqavilə."""

    def __init__(self, tenant_id: Any) -> None:
        self.tenant_id = tenant_id
        self.limits = _Limits()
        self.uow = _Uow()


class _ProbeContext:
    """`ApplicationContext.session()`/`face_engine()` müqaviləsinin minimalı."""

    def __init__(self, camera: Any, *, tenant_id: Any) -> None:
        self._camera = camera
        self._tenant_id = tenant_id

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        yield _EnrollmentSession(self._tenant_id)

    def face_engine(self) -> tuple[Any, Any]:
        return self._camera, self._camera


@requires_qt
def test_the_camera_probe_leaves_the_gui_thread(qt_app) -> None:  # type: ignore[no-untyped-def]
    """`camera.is_available()` GUI sapında qalsaydı ekran donardı (PERF-6 #7)."""
    import threading
    import uuid

    from PySide6.QtCore import QThread

    from src.domain.entities.employee import Employee
    from src.domain.entities.position import Position
    from src.domain.value_objects.authorization import RolePriority
    from src.domain.value_objects.credentials import Username
    from src.domain.value_objects.identifiers import EmployeeId, PositionId, TenantId
    from src.presentation.controllers.face_control import FaceEnrollmentController

    gui_thread = QThread.currentThread()
    seen: dict[str, Any] = {}
    block = threading.Event()

    class _Camera:
        def is_available(self) -> bool:
            seen["thread"] = QThread.currentThread()
            block.wait(timeout=5.0)
            return True

    class _Screen:
        def __init__(self) -> None:
            self.cameras: list[dict[str, str]] = []

        def set_employees(self, _rows: Any) -> None:
            return None

        def set_camera(self, camera: dict[str, str]) -> None:
            self.cameras.append(camera)

    tenant = TenantId(uuid.uuid4())
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code="HR_ADMIN",
        name_az="HR Admin",
        priority=RolePriority.OPERATIONAL,
        tenant_id=tenant,
        is_system=True,
    )
    actor = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=tenant,
        position=position,
        first_name="Aysel",
        last_name="Quliyeva",
        username=Username("a.quliyeva"),
        has_password=True,
    )

    context = _ProbeContext(_Camera(), tenant_id=tenant)
    controller = FaceEnrollmentController(context, actor)  # type: ignore[arg-type]
    screen = _Screen()

    started_at = time.monotonic()
    controller.refresh(screen)  # type: ignore[arg-type]
    elapsed = time.monotonic() - started_at

    # `refresh()` ÖZÜ dərhal qayıtmalıdır — sinxron olsaydı bura `block.set()`
    # çağırılana qədər (5 saniyə) çatmazdı.
    assert elapsed < 1.0, "`refresh()` GUI sapını blokladı — PERF-6 #7 geri qayıtdı"
    assert screen.cameras[-1]["available"] == "0", "prob bitənə qədər TƏHLÜKƏSİZ defolt qalmalıdır"

    delivered: list[Any] = []
    controller._camera_task.succeeded.connect(delivered.append)  # type: ignore[union-attr]
    block.set()
    _drain(qt_app, delivered)

    assert seen.get("thread") is not gui_thread, "kamera probu GUI sapında icra olundu"
    assert screen.cameras[-1]["available"] == "1"
