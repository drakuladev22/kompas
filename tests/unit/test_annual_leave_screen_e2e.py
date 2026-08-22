"""`EmployeeHomeScreen`/`AnnualLeaveInboxScreen` ↔ `controllers/annual_leave.py` — REAL Qt e2e.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, dördüncü beşlik)
──────────────────────────────────────────────────────────────────────────────
`test_annual_leave_screen.py` ekranın ÖZÜNÜ (widget-lər, tondəyişmə) və
kontrolleri AYRI-AYRI, DUCK-TYPED sahtələrlə (`_KioskStub`, `_InboxStub`) sınayır
— REAL `EmployeeHomeScreen`, REAL `AnnualLeaveInboxScreen`, REAL
`AnnualLeaveRequestDialog` heç vaxt eyni prosesdə BİRGƏ qurulmur və "Məzuniyyət
Sorğusu"/"Təsdiqlə"/"Rədd Et" düymələri heç vaxt FAKTİKİ klikllənmir. Burada
kontroller `.attach()` ilə REAL ekrana bağlanır və hər ssenari REAL siqnal
zənciri ilə işə salınır.

Sahtələr BU FAYLDA yerlidir (`tests/fixtures/fakes.py`-a TOXUNULMUR) —
`test_annual_leave.py`/`test_annual_leave_screen.py` ilə eyni qərar: paralel
işləyən başqa ekranların sahtə dəstindən asılı olmamaq.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from src.application.use_cases.annual_leave import AnnualLeaveBalanceView
from src.domain.entities.annual_leave import AnnualLeaveRequest
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import PermissionFlag, RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    TenantId,
    new_annual_leave_request_id,
)
from src.presentation.controllers.annual_leave import SUBMIT_CONFIRMATION
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT: TenantId = TenantId(uuid.uuid4())
NOW = datetime(2026, 8, 12, 9, 42, tzinfo=UTC)


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
# Aktorlar
# --------------------------------------------------------------------------- #


def _employee(
    *, code: str, name_az: str, priority: RolePriority, flags: tuple[str, ...]
) -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=code,
        name_az=name_az,
        priority=priority,
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
        username=Username(f"a.{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )


def _seller() -> Employee:
    return _employee(code="SATICI", name_az="Satıcı", priority=RolePriority.STAFF, flags=())


def _hr_admin() -> Employee:
    return _employee(
        code="HR_ADMIN",
        name_az="HR Admin",
        priority=RolePriority.OPERATIONAL,
        flags=("can_manage_leave_balances",),
    )


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


def _view(
    *,
    year: int = date.today().year,  # noqa: DTZ011 — real dialoqun `_day_choices`-i ilə eyni "bugün"
    available: str = "14",
    total: str = "21",
    carried_over: str = "5",
    expired: bool = False,
) -> AnnualLeaveBalanceView:
    return AnnualLeaveBalanceView(
        year=year,
        entitled_days=Decimal("21.00"),
        carried_over_days=Decimal(carried_over),
        used_days=Decimal("12.00"),
        available_days=Decimal(available),
        total_days=Decimal(total),
        carryover_deadline=date(year + 1, 3, 31),
        carryover_expired=expired,
    )


def _request(employee_id: EmployeeId, *, start: date, end: date) -> AnnualLeaveRequest:
    return AnnualLeaveRequest(
        request_id=new_annual_leave_request_id(),
        tenant_id=TENANT,
        employee_id=employee_id,
        start_date=start,
        end_date=end,
        created_at=NOW,
        emit_created_event=False,
    )


class _UseCase:
    """`AnnualLeaveUseCase` müqaviləsinin REAL siqnal zənciri üçün minimal təkrarı."""

    def __init__(
        self,
        *,
        view: AnnualLeaveBalanceView | None = None,
        pending: list[AnnualLeaveRequest] | None = None,
        balance_error: Exception | None = None,
        inbox_error: Exception | None = None,
        submit_error: Exception | None = None,
        approve_error: Exception | None = None,
        reject_error: Exception | None = None,
    ) -> None:
        self.view = view if view is not None else _view()
        self.pending = list(pending or [])
        self.balance_error = balance_error
        self.inbox_error = inbox_error
        self.submit_error = submit_error
        self.approve_error = approve_error
        self.reject_error = reject_error
        self.balance_calls = 0
        self.inbox_calls = 0
        self.submitted: list[tuple[date, date]] = []
        self.approved: list[Any] = []
        self.rejected: list[tuple[Any, str]] = []

    def my_balance(self, *, tenant_id: Any, employee: Any) -> AnnualLeaveBalanceView:
        self.balance_calls += 1
        if self.balance_error is not None:
            raise self.balance_error
        return self.view

    def pending_inbox(
        self, *, tenant_id: Any, actor: Any, limit: int = 200
    ) -> list[AnnualLeaveRequest]:
        self.inbox_calls += 1
        if self.inbox_error is not None:
            raise self.inbox_error
        return list(self.pending)

    def submit(
        self, *, tenant_id: Any, employee: Any, start_date: date, end_date: date
    ) -> AnnualLeaveRequest:
        if self.submit_error is not None:
            raise self.submit_error
        self.submitted.append((start_date, end_date))
        return _request(employee.id, start=start_date, end=end_date)

    def approve(
        self, *, tenant_id: Any, approver: Any, request_id: Any, employee: Any
    ) -> AnnualLeaveRequest:
        if self.approve_error is not None:
            raise self.approve_error
        if request_id not in {r.id for r in self.pending}:
            # DB-nin şərti `UPDATE`-inin güzgüsü: sorğu artıq qərara bağlanıb —
            # ikinci (sürətli/təkrar) klik burada UDUZUR, ikiqat yazmır.
            raise KompasOSError(
                "artıq qərar verilib", user_message="Bu sorğu artıq qərara bağlanıb."
            )
        self.approved.append(request_id)
        self.pending = [r for r in self.pending if r.id != request_id]
        return _request(employee.id, start=date(2026, 9, 14), end=date(2026, 9, 25))

    def reject(
        self, *, tenant_id: Any, approver: Any, request_id: Any, reason: str
    ) -> AnnualLeaveRequest:
        if self.reject_error is not None:
            raise self.reject_error
        self.rejected.append((request_id, reason))
        removed = [r for r in self.pending if r.id == request_id]
        self.pending = [r for r in self.pending if r.id != request_id]
        return (
            removed[0]
            if removed
            else _request(EmployeeId(uuid.uuid4()), start=date(2026, 9, 14), end=date(2026, 9, 25))
        )


class _EmployeesRepo:
    def __init__(self, employees: dict[EmployeeId, Employee]) -> None:
        self._employees = employees

    def get(self, employee_id: EmployeeId) -> Employee | None:
        return self._employees.get(employee_id)


class _RequestsRepo:
    """`_request_employee()`-in oxuduğu repo — `use_case.pending`-dən AYRI saxlanır.

    Təsdiq/rədd `use_case.pending`-i dəyişsə də, sorğunun sahibini tapmaq üçün
    bu SİYAHI toxunulmaz qalır — real DB-də sətir SİLİNMİR, statusu dəyişir.
    """

    def __init__(self, requests: list[AnnualLeaveRequest]) -> None:
        self._requests = requests

    def get(self, request_id: Any) -> AnnualLeaveRequest | None:
        return next((r for r in self._requests if r.id == request_id), None)


class _Uow:
    def __init__(
        self, employees: dict[EmployeeId, Employee], requests: list[AnnualLeaveRequest]
    ) -> None:
        self.employees = _EmployeesRepo(employees)
        self._requests = _RequestsRepo(requests)

    def repository(self, name: str) -> Any:
        assert name == "annual_leave_requests"
        return self._requests


class _Session:
    def __init__(
        self,
        use_case: _UseCase,
        *,
        employees: dict[EmployeeId, Employee],
        all_requests: list[AnnualLeaveRequest],
    ) -> None:
        self.tenant_id = TENANT
        self.annual_leave = use_case
        self.uow = _Uow(employees, all_requests)
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Context:
    """`ApplicationContext.session()` müqaviləsinin REAL kontroller üçün minimal təkrarı."""

    def __init__(self, use_case: _UseCase, *, employees: dict[EmployeeId, Employee]) -> None:
        self._use_case = use_case
        self._employees = employees
        # `_request_employee()`-in gördüyü sabit siyahı — bax `_RequestsRepo`.
        self._all_requests = list(use_case.pending)
        self.tenant_id = TENANT
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(
            self._use_case, employees=self._employees, all_requests=self._all_requests
        )
        self.sessions.append(created)
        yield created


# --------------------------------------------------------------------------- #
# 1. İşçi tərəfi — real "Məzuniyyət Sorğusu" → real dialoq → real "Sorğu Göndər"
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_the_real_request_button_opens_the_real_dialog_and_submits(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.controllers.annual_leave import EmployeeAnnualLeaveController
    from src.presentation.screens.annual_leave import AnnualLeaveRequestDialog
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen

    seller = _seller()
    use_case = _UseCase()
    context = _Context(use_case, employees={seller.id: seller})
    screen = EmployeeHomeScreen(
        theme, full_name="Aysel Quliyeva", position_name="Satıcı", store_name="Mərkəz"
    )
    qtbot.addWidget(screen)
    screen.show()  # `isVisible()` göstərilməyən pəncərədə HƏMİŞƏ False qaytarır
    EmployeeAnnualLeaveController(context, seller).attach(screen)  # type: ignore[arg-type]

    def fake_exec(self: AnnualLeaveRequestDialog) -> int:
        self._start.setCurrentIndex(0)
        self._end.setCurrentIndex(min(2, self._end.count() - 1))
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Sorğu Göndər")
        submit.click()
        return 0

    monkeypatch.setattr(AnnualLeaveRequestDialog, "exec", fake_exec)

    _click(screen, "Məzuniyyət Sorğusu")

    assert len(use_case.submitted) == 1
    assert any(s.commits for s in context.sessions)
    assert screen._annual_leave_message.text() == SUBMIT_CONFIRMATION
    assert screen._annual_leave_message.isVisible()


@requires_qt
def test_dialog_data_read_failure_shows_a_message_and_never_opens_the_dialog(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Balans forma AÇILMAZDAN ƏVVƏL oxunur — istisna atsa dialoq HEÇ AÇILMIR."""
    from src.presentation.controllers.annual_leave import EmployeeAnnualLeaveController
    from src.presentation.screens.annual_leave import AnnualLeaveRequestDialog
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen

    seller = _seller()
    use_case = _UseCase(balance_error=RuntimeError("baza əlçatmazdır"))
    context = _Context(use_case, employees={seller.id: seller})
    screen = EmployeeHomeScreen(
        theme, full_name="Aysel Quliyeva", position_name="Satıcı", store_name="Mərkəz"
    )
    qtbot.addWidget(screen)
    EmployeeAnnualLeaveController(context, seller).attach(screen)  # type: ignore[arg-type]

    opened: list[int] = []
    monkeypatch.setattr(
        AnnualLeaveRequestDialog, "__init__", lambda self, *a, **k: opened.append(1)
    )

    _click(screen, "Məzuniyyət Sorğusu")  # ÇÖKMƏMƏLİDİR

    assert opened == []
    assert screen._annual_leave_message.text() == "Məzuniyyət forması açılmadı. Yenidən cəhd edin."


@requires_qt
def test_no_selectable_days_shows_a_message_and_skips_the_dialog(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Balans ili artıq keçib — `_day_choices` boşdur, boş dialoq AÇILMIR."""
    from src.presentation.controllers.annual_leave import EmployeeAnnualLeaveController
    from src.presentation.screens.annual_leave import AnnualLeaveRequestDialog
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen

    seller = _seller()
    past_year = date.today().year - 1  # noqa: DTZ011
    use_case = _UseCase(view=_view(year=past_year))
    context = _Context(use_case, employees={seller.id: seller})
    screen = EmployeeHomeScreen(
        theme, full_name="Aysel Quliyeva", position_name="Satıcı", store_name="Mərkəz"
    )
    qtbot.addWidget(screen)
    EmployeeAnnualLeaveController(context, seller).attach(screen)  # type: ignore[arg-type]

    opened: list[int] = []
    monkeypatch.setattr(
        AnnualLeaveRequestDialog, "__init__", lambda self, *a, **k: opened.append(1)
    )

    _click(screen, "Məzuniyyət Sorğusu")

    assert opened == []
    assert screen._annual_leave_message.text() == "Seçilə bilən tarix yoxdur."


@requires_qt
def test_submit_domain_error_via_the_real_dialog_keeps_the_card_alive(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.controllers.annual_leave import EmployeeAnnualLeaveController
    from src.presentation.screens.annual_leave import AnnualLeaveRequestDialog
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen

    seller = _seller()
    error = KompasOSError(
        "balans çatmır",
        user_message="Balansınızda 2 gün qalıb, bu sorğu 12 gün tələb edir.",
    )
    use_case = _UseCase(submit_error=error)
    context = _Context(use_case, employees={seller.id: seller})
    screen = EmployeeHomeScreen(
        theme, full_name="Aysel Quliyeva", position_name="Satıcı", store_name="Mərkəz"
    )
    qtbot.addWidget(screen)
    EmployeeAnnualLeaveController(context, seller).attach(screen)  # type: ignore[arg-type]

    def fake_exec(self: AnnualLeaveRequestDialog) -> int:
        self._start.setCurrentIndex(0)
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Sorğu Göndər")
        submit.click()
        return 0

    monkeypatch.setattr(AnnualLeaveRequestDialog, "exec", fake_exec)

    _click(screen, "Məzuniyyət Sorğusu")  # ÇÖKMƏMƏLİDİR

    assert use_case.submitted == []
    assert screen._annual_leave_message.text() == error.user_message
    # Xətadan sonra da kart YENİDƏN doldurulur — "—" görünmür.
    assert screen._annual_leave_value.text() == "14/21"


# --------------------------------------------------------------------------- #
# 2. HR tərəfi — köməkçilər
# --------------------------------------------------------------------------- #


def _inbox_context(
    use_case: _UseCase, *, owners: dict[EmployeeId, Employee] | None = None
) -> tuple[_Context, Employee]:
    hr = _hr_admin()
    employees = {hr.id: hr, **(owners or {})}
    return _Context(use_case, employees=employees), hr


def _attach_inbox(context: _Context, hr: Employee, theme: Any, *, qtbot: Any) -> Any:
    from src.presentation.controllers.annual_leave import AnnualLeaveInboxController
    from src.presentation.screens.annual_leave import AnnualLeaveInboxScreen

    screen = AnnualLeaveInboxScreen(theme)
    qtbot.addWidget(screen)
    AnnualLeaveInboxController(context, hr).attach(screen)  # type: ignore[arg-type]
    return screen


# --------------------------------------------------------------------------- #
# 2a. Real "Təsdiqlə"
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_the_real_approve_button_commits_and_empties_the_real_table(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    owner = _seller()
    request = _request(owner.id, start=date(2026, 9, 14), end=date(2026, 9, 25))
    use_case = _UseCase(pending=[request])
    context, hr = _inbox_context(use_case, owners={owner.id: owner})
    screen = _attach_inbox(context, hr, theme, qtbot=qtbot)
    assert screen.switcher().current_state() == "content"

    _click(screen, "Təsdiqlə")

    assert use_case.approved == [request.id]
    assert any(s.commits for s in context.sessions)
    assert screen.switcher().current_state() == "empty"


@requires_qt
def test_double_real_approve_before_a_refresh_does_not_process_twice(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Sürətli/təkrar klik: BİRİNCİ qərara bağlanır, İKİNCİ DB-nin şərti
    `UPDATE`-i kimi UDUZUR — ekran ÇÖKMÜR, balans ikiqat yazılmır.
    """
    owner = _seller()
    request = _request(owner.id, start=date(2026, 9, 14), end=date(2026, 9, 25))
    use_case = _UseCase(pending=[request])
    context, hr = _inbox_context(use_case, owners={owner.id: owner})
    screen = _attach_inbox(context, hr, theme, qtbot=qtbot)
    key = str(request.id)

    screen.approve_requested.emit(key)
    screen.approve_requested.emit(key)  # ÇÖKMƏMƏLİDİR

    assert use_case.approved == [request.id], "İkinci klik balansı İKİQAT azaltmamalıdır"


@requires_qt
def test_a_malformed_request_id_from_a_stale_row_does_not_crash_approve(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    owner = _seller()
    request = _request(owner.id, start=date(2026, 9, 14), end=date(2026, 9, 25))
    use_case = _UseCase(pending=[request])
    context, hr = _inbox_context(use_case, owners={owner.id: owner})
    screen = _attach_inbox(context, hr, theme, qtbot=qtbot)

    screen.approve_requested.emit("not-a-uuid")  # ÇÖKMƏMƏLİDİR

    assert use_case.approved == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_approving_a_request_whose_owner_is_missing_reports_instead_of_guessing(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """Sahibi tapılmayan sorğu — use case ÇAĞIRILMIR, real error vəziyyəti görünür."""
    stranger_id = EmployeeId(uuid.uuid4())
    request = _request(stranger_id, start=date(2026, 9, 14), end=date(2026, 9, 25))
    use_case = _UseCase(pending=[request])
    context, hr = _inbox_context(use_case)  # `stranger_id` `employees`-də YOXDUR
    screen = _attach_inbox(context, hr, theme, qtbot=qtbot)

    _click(screen, "Təsdiqlə")

    assert use_case.approved == []
    # Bu qolda `refresh()` ÇAĞIRILMIR (kontrollerin özündə) — banner sükutla
    # üstündən yazılmır, real ekranda GÖRÜNÜR qalır.
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_approve_failure_banner_is_silently_overwritten_by_the_immediate_refresh(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """DÜZƏLDİLDİ (`ui` sahibi) — `announcements.py::_on_withdraw` naxışı KEÇDİ.

    `_on_approve`-un `except KompasOSError` qolu ƏVVƏL `show_error()`-dan
    DƏRHAL sonra `self.refresh(screen)` çağırırdı. Sorğu hələ də `pending`-də
    qaldığı üçün `refresh()` → `set_requests(rows)` qeyri-boş siyahı ilə
    `show_content()` çağırırdı və bu, heç bir render arası olmadan
    `show_error()`-un qoyduğu vəziyyətin ÜSTÜNDƏN yazırdı — HR bu mesajı HEÇ
    VAXT görmürdü.

    İndi `refresh()` çağırışı `on_retry=lambda: self.refresh(screen)`-ə
    köçürülüb (`announcements.py::_on_withdraw` ilə EYNİ naxış): banner
    görünən qalır, yenidən yükləmə isə istifadəçinin öz qərarına buraxılır.
    """
    owner = _seller()
    request = _request(owner.id, start=date(2026, 9, 14), end=date(2026, 9, 25))
    error = KompasOSError(
        "paralel təsdiq", user_message="Balans dəyişdi, siyahını yenidən yoxlayın."
    )
    use_case = _UseCase(pending=[request], approve_error=error)
    context, hr = _inbox_context(use_case, owners={owner.id: owner})
    screen = _attach_inbox(context, hr, theme, qtbot=qtbot)

    _click(screen, "Təsdiqlə")

    assert screen.switcher().current_state() == "error", (
        "HR balans dəyişikliyinin səbəbini görməlidir"
    )


# --------------------------------------------------------------------------- #
# 2b. Real "Rədd Et" — real `QInputDialog` səbəb sorğusu
# --------------------------------------------------------------------------- #


@requires_qt
def test_rejecting_via_the_real_button_and_accepted_reason_prompt_commits(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    owner = _seller()
    request = _request(owner.id, start=date(2026, 9, 14), end=date(2026, 9, 25))
    use_case = _UseCase(pending=[request])
    context, hr = _inbox_context(use_case, owners={owner.id: owner})
    screen = _attach_inbox(context, hr, theme, qtbot=qtbot)

    monkeypatch.setattr(
        QInputDialog,
        "getMultiLineText",
        staticmethod(lambda *a, **k: ("Həmin həftə inventarizasiya var, sonraya keçirin.", True)),
    )

    _click(screen, "Rədd Et")

    assert use_case.rejected == [(request.id, "Həmin həftə inventarizasiya var, sonraya keçirin.")]
    assert any(s.commits for s in context.sessions)
    assert screen.switcher().current_state() == "empty"


@requires_qt
def test_declining_the_real_reject_prompt_writes_nothing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    owner = _seller()
    request = _request(owner.id, start=date(2026, 9, 14), end=date(2026, 9, 25))
    use_case = _UseCase(pending=[request])
    context, hr = _inbox_context(use_case, owners={owner.id: owner})
    screen = _attach_inbox(context, hr, theme, qtbot=qtbot)

    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("", False)))

    _click(screen, "Rədd Et")

    assert use_case.rejected == []
    assert screen.switcher().current_state() == "content", "Sətr sükutla İTMƏMƏLİDİR"


@requires_qt
def test_whitespace_only_reject_reason_is_treated_as_declined(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Boş SAYILAN cavab (yalnız boşluq) yazı yoluna GETMİR (`_ask_reason`)."""
    from PySide6.QtWidgets import QInputDialog

    owner = _seller()
    request = _request(owner.id, start=date(2026, 9, 14), end=date(2026, 9, 25))
    use_case = _UseCase(pending=[request])
    context, hr = _inbox_context(use_case, owners={owner.id: owner})
    screen = _attach_inbox(context, hr, theme, qtbot=qtbot)

    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("   \n\t  ", True))
    )

    _click(screen, "Rədd Et")

    assert use_case.rejected == []


@requires_qt
def test_hostile_and_extreme_length_reject_reason_passes_through_without_crashing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    owner = _seller()
    request = _request(owner.id, start=date(2026, 9, 14), end=date(2026, 9, 25))
    use_case = _UseCase(pending=[request])
    context, hr = _inbox_context(use_case, owners={owner.id: owner})
    screen = _attach_inbox(context, hr, theme, qtbot=qtbot)

    hostile = "'; DROP TABLE annual_leave_requests; -- 🔥" + "A" * 10_000
    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: (hostile, True))
    )

    _click(screen, "Rədd Et")  # ÇÖKMƏMƏLİDİR

    assert use_case.rejected == [(request.id, hostile)]
    assert any(s.commits for s in context.sessions)


@requires_qt
def test_a_malformed_request_id_from_a_stale_row_does_not_crash_reject(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    owner = _seller()
    request = _request(owner.id, start=date(2026, 9, 14), end=date(2026, 9, 25))
    use_case = _UseCase(pending=[request])
    context, hr = _inbox_context(use_case, owners={owner.id: owner})
    screen = _attach_inbox(context, hr, theme, qtbot=qtbot)

    screen.reject_requested.emit("not-a-uuid")  # ÇÖKMƏMƏLİDİR — `QInputDialog` AÇILMAMALIDIR

    assert use_case.rejected == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_reject_failure_banner_is_silently_overwritten_by_the_immediate_refresh(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """DÜZƏLDİLDİ — `_on_reject`-in EYNİ naxışı, bax `test_approve_failure_banner_...`."""
    from PySide6.QtWidgets import QInputDialog

    owner = _seller()
    request = _request(owner.id, start=date(2026, 9, 14), end=date(2026, 9, 25))
    error = KompasOSError(
        "artıq qərar verilib", user_message="Bu sorğu artıq başqası tərəfindən rədd edilib."
    )
    use_case = _UseCase(pending=[request], reject_error=error)
    context, hr = _inbox_context(use_case, owners={owner.id: owner})
    screen = _attach_inbox(context, hr, theme, qtbot=qtbot)

    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("səbəb", True))
    )

    _click(screen, "Rədd Et")

    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 2c. Real "Yenilə" və icazə-bağlı oxu xətası
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_the_real_refresh_button_rereads_the_inbox(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    owner = _seller()
    request = _request(owner.id, start=date(2026, 9, 14), end=date(2026, 9, 25))
    use_case = _UseCase(pending=[request])
    context, hr = _inbox_context(use_case, owners={owner.id: owner})
    screen = _attach_inbox(context, hr, theme, qtbot=qtbot)
    calls_after_attach = use_case.inbox_calls

    _click(screen, "Yenilə")

    assert use_case.inbox_calls == calls_after_attach + 1
    assert screen.switcher().current_state() == "content"


@requires_qt
def test_permission_denied_inbox_read_shows_the_real_error_state(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Flag-siz aktor menyunu keçib ekranı açsa belə — REAL error vəziyyəti göstərilir."""
    error = KompasOSError(
        "can_manage_leave_balances yoxdur",
        user_message="Məzuniyyət sorğusuna qərar vermək səlahiyyətiniz yoxdur.",
    )
    use_case = _UseCase(inbox_error=error)
    context, hr = _inbox_context(use_case)
    screen = _attach_inbox(context, hr, theme, qtbot=qtbot)  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"
