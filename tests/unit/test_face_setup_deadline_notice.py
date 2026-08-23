"""DEEP-GAP UX-7 — «Sonra» möhləti EKRANDA görünür.

──────────────────────────────────────────────────────────────────────────────
QÜSUR NƏ İDİ
──────────────────────────────────────────────────────────────────────────────
İlk girişdə üz qeydiyyatı ekranı çıxırdı, işçi «Sonra» basırdı və ertəsi gün
EYNİ pəncərə yenidən açılırdı — hər gün. Tələb nə tətbiq olunurdu, nə də ləğv
edilirdi: işçi pəncərəni bağlamağı ÖYRƏNİRDİ, yəni qapı öz məqsədini itirirdi.

İNDİ: `FACE_ENROLLMENT_GRACE_DAYS` Root açarı möhləti təyin edir, möhlət
bitəndə `OverdueFaceEnrollmentRule` menecerin «İstisnalar» siyahısına sətir
yazır. Bu testlər EKRAN tərəfini kilidləyir — işçi «nə vaxta qədər» sualının
cavabını GÖRÜR.

MƏTN EKRANDA HESABLANMIR: `FaceEnrollmentUseCase.enrollment_grace()` onu hazır
verir. Testlər məhz bunu da yoxlayır — ekran öz nüsxəsini qurmur.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
HIRE_DATE = date(2026, 8, 1)


class _Grace:
    """`FaceEnrollmentGrace`-in əvəzedicisi — ekran YALNIZ üç sahəni oxuyur."""

    def __init__(self, *, deadline: date | None, days_left: int) -> None:
        self.deadline = deadline
        self.days_left = days_left
        self.grace_days = 7

    @property
    def is_overdue(self) -> bool:
        return self.deadline is not None and self.days_left < 0

    def label_az(self) -> str:
        if self.deadline is None:
            return "Üz qeydiyyatı gözlənilir"
        if self.days_left < 0:
            return f"Üz qeydiyyatı {abs(self.days_left)} gün gecikib"
        return f"Üz qeydiyyatına {self.days_left} gün qalıb"


class _Enrollment:
    def __init__(self, grace: _Grace | None, *, failure: Exception | None = None) -> None:
        self._grace = grace
        self._failure = failure
        self.calls: list[Any] = []

    def enrollment_grace(self, *, tenant_id: Any, hire_date: Any) -> _Grace:
        if self._failure is not None:
            raise self._failure
        self.calls.append(hire_date)
        assert self._grace is not None
        return self._grace


class _Session:
    def __init__(self, enrollment: _Enrollment) -> None:
        self.tenant_id = TENANT
        self.face_enrollment = enrollment


class _Context:
    def __init__(self, enrollment: _Enrollment) -> None:
        self._enrollment = enrollment

    @contextmanager
    def session(self, *, user_id: Any = None):  # type: ignore[no-untyped-def]
        yield _Session(self._enrollment)


class _Position:
    name_az = "Satıcı"


class _Subject:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.full_name = "Aygün Məmmədova"
        self.hire_date = HIRE_DATE
        self.position = _Position()


def _screen(qt_app: Any) -> Any:
    from src.presentation.screens.face_control import FaceSetupRequiredScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    theme = ThemeManager(preference=ThemeMode.LIGHT)
    theme.apply(qt_app)
    return FaceSetupRequiredScreen(theme, employee_name="Aygün Məmmədova")


def _attach(screen: Any, enrollment: _Enrollment) -> None:
    from src.presentation.controllers.face_setup import FaceSetupController

    FaceSetupController(_Context(enrollment), _Subject()).attach(screen)  # type: ignore[arg-type]


@requires_qt
def test_the_remaining_days_are_shown_to_the_employee(qt_app) -> None:  # type: ignore[no-untyped-def]
    screen = _screen(qt_app)
    enrollment = _Enrollment(_Grace(deadline=date(2026, 8, 8), days_left=3))

    _attach(screen, enrollment)

    assert screen._deadline.isVisible() or not screen.isVisible()
    assert screen._deadline.text() == "Üz qeydiyyatına 3 gün qalıb"
    # Hesablama USE CASE-dədir: kontroller yalnız işə başlama tarixini ötürür.
    assert enrollment.calls == [HIRE_DATE]


@requires_qt
def test_an_overdue_deadline_is_marked_but_not_accusatory(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Gecikmə XƏBƏRDARLIQ rəngindədir, `--color-danger` DEYİL.

    Qeydiyyat self-service deyil — işçi onu özü apara bilmir, yəni gecikmənin
    səbəbi çox vaxt adminin vaxtıdır. Qırmızı «sən səhv etdin» deməkdir.
    """
    screen = _screen(qt_app)

    _attach(screen, _Enrollment(_Grace(deadline=date(2026, 8, 8), days_left=-5)))

    assert screen._deadline.text() == "Üz qeydiyyatı 5 gün gecikib"
    style = screen._deadline.styleSheet()
    assert screen.theme.color("--color-warning") in style
    assert screen.theme.color("--color-danger") not in style


@requires_qt
def test_an_unknown_hire_date_shows_no_deadline_at_all(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Uydurma son tarix göstərmək yanlış rəqəm göstərməyin eynisidir."""
    screen = _screen(qt_app)

    _attach(screen, _Enrollment(_Grace(deadline=None, days_left=0)))

    assert screen._deadline.text() == ""
    assert screen._deadline.isVisible() is False


@requires_qt
def test_a_failing_read_does_not_block_the_enrollment_screen(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Möhlət KÖMƏKÇİ məlumatdır — oxunmaması qapını bağlamamalıdır."""
    screen = _screen(qt_app)

    _attach(screen, _Enrollment(None, failure=RuntimeError("connection lost")))

    assert screen._deadline.text() == ""
    # Ekranın ÖZÜ işlək qalır: «Təsdiqlə və Çək» düyməsi yerindədir.
    assert screen._enroll.isEnabled() is True


@requires_qt
def test_the_screen_does_not_compute_the_deadline_itself(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Ekran mətni HAZIR alır — eyni qayda iki yerdə yaşamamalıdır.

    Qayda `OverdueFaceEnrollmentRule`-da da var; ekran öz nüsxəsini qursaydı,
    Root `FACE_ENROLLMENT_GRACE_DAYS` dəyərini dəyişəndə biri yenilənər,
    digəri köhnə qalardı (`menu.py` başlığındakı ikili-ad-məkanı qüsuru).
    """
    from pathlib import Path

    source = Path("src/presentation/screens/face_control.py").read_text(encoding="utf-8")
    body = source[source.index("def set_deadline_notice") :]
    body = body[: body.index("\n    def ", 1)]

    assert "timedelta" not in body
    assert "FACE_ENROLLMENT_GRACE_DAYS" not in body
    assert str(datetime(2026, 1, 1, tzinfo=UTC).year) not in body
