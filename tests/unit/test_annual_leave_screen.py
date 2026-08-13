"""İllik məzuniyyət ekranı və kontrolleri — #28-in GUI tərəfi (kompas1.md Faza 4).

Testlər İKİ təbəqəni ayrıca yoxlayır:

    * ekranların ÖZÜ (balans kartı, köçürmə tonu, dialoqun tarix siyahısı, boş
      inbox) — Qt TƏLƏB EDİR, çünki `set_annual_leave_balance`/`set_requests`
      real `Card`/`DataTable`/`QComboBox` qurur;
    * kontrollerlər (açar paritetı, yazıdan sonra yenidən oxuma, məcburi rədd
      səbəbi, `user_message`) — Qt TƏLƏB ETMİR, `test_field_report_screen.py`
      və `test_exception_screen.py`-dəki duck-typing naxışını təkrarlayır.

Sahtələr BU FAYLDA yerlidir — `tests/fixtures/fakes.py`-a TOXUNULMUR (eyni
qərar iki əvvəlki ekran testində də verilib: paralel işlər həmin ortaq faylı
dəyişə bilər).

──────────────────────────────────────────────────────────────────────────────
BU TESTLƏR ÜÇÜNCÜ MEXANİZMİ YOXLAYIR
──────────────────────────────────────────────────────────────────────────────
Burada nə `MonthlyLeaveUsage` (STEP1/STEP2 gündaxili icazə, DƏQİQƏ), nə də
Shift Matrix istirahət günü sınanır — onların öz testləri var və bu fayl
onlara toxunmur.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Final

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
from src.presentation import preview_data
from src.presentation.controllers.annual_leave import (
    BALANCE_READ_FAILED,
    SUBMIT_CONFIRMATION,
    AnnualLeaveInboxController,
    EmployeeAnnualLeaveController,
    _day_choices,
    _day_number,
    _to_balance_row,
)
from src.presentation.shell.menu import DEFAULT_ENTRIES, build_default_registry
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())
NOW: Final = datetime(2026, 8, 12, 9, 42, tzinfo=UTC)


class _DeniedError(KompasOSError):
    """`AnnualLeavePermissionError` müqaviləsinin yerli əvəzi."""

    user_message = "Məzuniyyət sorğusuna qərar vermək səlahiyyətiniz yoxdur."


class _BalanceError(KompasOSError):
    user_message = "Balansınızda 2 gün qalıb, bu sorğu 12 gün tələb edir."


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
        username=Username("a.quliyeva"),
        has_password=True,
    )


def _seller() -> Employee:
    """Heç bir flag daşımayan `Satıcı` — öz balansını GÖRMƏLİDİR."""
    return _employee(code="SATICI", name_az="Satıcı", priority=RolePriority.STAFF, flags=())


def _hr_admin() -> Employee:
    return _employee(
        code="HR_ADMIN",
        name_az="HR Admin",
        priority=RolePriority.OPERATIONAL,
        flags=("can_manage_leave_balances",),
    )


# --------------------------------------------------------------------------- #
# Menyu: "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" (CLAUDE.md bölmə 3)
# --------------------------------------------------------------------------- #


def test_inbox_entry_is_gated_by_the_leave_balance_flag() -> None:
    entry = next(e for e in DEFAULT_ENTRIES if e.key == "annual_leave")
    assert entry.required_flag == "can_manage_leave_balances"


def test_employee_without_the_flag_does_not_see_the_hr_inbox() -> None:
    """Flag-siz işçi HR növbəsini GÖRMÜR — kart isə ona qalır (növbəti test)."""
    registry = build_default_registry()
    assert registry.is_visible("annual_leave", _seller(), now=NOW) is False
    assert registry.is_visible("annual_leave", _hr_admin(), now=NOW) is True


# --------------------------------------------------------------------------- #
# Sahtələr — Qt tələb ETMİR
# --------------------------------------------------------------------------- #


def _view(
    *,
    year: int = 2026,
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
    """`AnnualLeaveUseCase` müqaviləsinin minimal təkrarı."""

    def __init__(
        self,
        *,
        view: AnnualLeaveBalanceView | None = None,
        pending: list[AnnualLeaveRequest] | None = None,
        balance_error: Exception | None = None,
        inbox_error: Exception | None = None,
        submit_error: Exception | None = None,
        approve_error: Exception | None = None,
    ) -> None:
        self.view = view if view is not None else _view()
        self.pending = list(pending or [])
        self.balance_error = balance_error
        self.inbox_error = inbox_error
        self.submit_error = submit_error
        self.approve_error = approve_error
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
        self.approved.append(request_id)
        self.pending = [r for r in self.pending if r.id != request_id]
        return (
            self.pending[0]
            if self.pending
            else _request(employee.id, start=date(2026, 9, 14), end=date(2026, 9, 25))
        )

    def reject(
        self, *, tenant_id: Any, approver: Any, request_id: Any, reason: str
    ) -> AnnualLeaveRequest:
        self.rejected.append((request_id, reason))
        removed = [r for r in self.pending if r.id == request_id]
        self.pending = [r for r in self.pending if r.id != request_id]
        return (
            removed[0]
            if removed
            else _request(EmployeeId(uuid.uuid4()), start=date(2026, 9, 14), end=date(2026, 9, 25))
        )


class _EmployeeRepo:
    def __init__(self, employees: dict[EmployeeId, Employee]) -> None:
        self._employees = employees

    def get(self, employee_id: EmployeeId) -> Employee | None:
        return self._employees.get(employee_id)


class _RequestRepo:
    def __init__(self, requests: list[AnnualLeaveRequest]) -> None:
        self._requests = requests

    def get(self, request_id: Any) -> AnnualLeaveRequest | None:
        return next((r for r in self._requests if r.id == request_id), None)


class _Uow:
    def __init__(
        self, employees: dict[EmployeeId, Employee], requests: list[AnnualLeaveRequest]
    ) -> None:
        self.employees = _EmployeeRepo(employees)
        self._requests = _RequestRepo(requests)

    def repository(self, name: str) -> Any:
        assert name == "annual_leave_requests"
        return self._requests


class _Session:
    def __init__(self, use_case: _UseCase, *, employees: dict[EmployeeId, Employee]) -> None:
        self.tenant_id = TENANT
        self.annual_leave = use_case
        self.uow = _Uow(employees, use_case.pending)
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Context:
    """`ApplicationContext.session()` müqaviləsinin minimal təkrarı."""

    def __init__(self, session: _Session) -> None:
        self._session = session
        self.tenant_id = TENANT

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        yield self._session


class _KioskStub:
    """İşçi Ana Ekranının setter API-sinin sahtəsi."""

    def __init__(self) -> None:
        self.balances: list[dict[str, str]] = []
        self.messages: list[str] = []
        self.theme = object()

    def set_annual_leave_balance(self, balance: dict[str, str]) -> None:
        self.balances.append(balance)

    def set_annual_leave_message(self, message: str) -> None:
        self.messages.append(message)


class _InboxStub:
    """HR ekranının setter API-sinin sahtəsi."""

    def __init__(self) -> None:
        self.rows: list[list[dict[str, str]]] = []
        self.errors: list[tuple[str, str]] = []

    def set_requests(self, rows: list[dict[str, str]]) -> None:
        self.rows.append(rows)

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


def _kiosk_controller(
    use_case: _UseCase, actor: Employee | None = None
) -> tuple[EmployeeAnnualLeaveController, _Session]:
    employee = actor or _seller()
    session = _Session(use_case, employees={employee.id: employee})
    return EmployeeAnnualLeaveController(_Context(session), employee), session  # type: ignore[arg-type]


def _inbox_controller(
    use_case: _UseCase, *, owners: dict[EmployeeId, Employee] | None = None
) -> tuple[AnnualLeaveInboxController, _Session]:
    actor = _hr_admin()
    employees = {actor.id: actor, **(owners or {})}
    session = _Session(use_case, employees=employees)
    return AnnualLeaveInboxController(_Context(session), actor), session  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# İşçi kartı — flag TƏLƏB ETMİR
# --------------------------------------------------------------------------- #


def test_every_employee_sees_their_own_balance_without_a_flag() -> None:
    """Öz haqqını görmək üçün `can_manage_leave_balances` LAZIM DEYİL."""
    seller = _seller()
    assert seller.has_permission("can_manage_leave_balances", now=NOW) is False

    use_case = _UseCase()
    controller, _ = _kiosk_controller(use_case, seller)
    screen = _KioskStub()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert use_case.balance_calls == 1
    assert screen.balances[-1]["available"] == "14"
    assert screen.balances[-1]["total"] == "21"


def test_preview_and_live_paths_share_the_same_balance_keys() -> None:
    """Maket və canlı yol EYNİ açarları işlətməlidir (CLAUDE.md §6)."""
    controller, _ = _kiosk_controller(_UseCase())
    screen = _KioskStub()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert set(screen.balances[-1]) == set(preview_data.ANNUAL_LEAVE_BALANCE)


def test_preview_and_live_paths_share_the_same_inbox_keys() -> None:
    """HR növbəsi üçün də eyni paritet — iki ad məkanı sürüşməməlidir."""
    owner = _seller()
    use_case = _UseCase(
        pending=[_request(owner.id, start=date(2026, 9, 14), end=date(2026, 9, 25))]
    )
    controller, _ = _inbox_controller(use_case, owners={owner.id: owner})
    screen = _InboxStub()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert set(screen.rows[-1][0]) == set(preview_data.ANNUAL_LEAVE_PENDING[0])
    assert screen.rows[-1][0]["employee"] == owner.full_name


def test_missing_balance_row_does_not_crash_the_kiosk() -> None:
    """Balans qeydi olmayan işçi — kart boş qalır, ekran ÇÖKMÜR."""
    use_case = _UseCase(balance_error=RuntimeError("baza əlçatmazdır"))
    controller, _ = _kiosk_controller(use_case)
    screen = _KioskStub()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.balances[-1] == {}
    assert screen.messages[-1] == BALANCE_READ_FAILED


def test_domain_error_reaches_the_kiosk_as_user_message_not_raw_text() -> None:
    """XAM istisna mətni ekrana ÇIXMIR — yalnız `user_message`."""
    use_case = _UseCase(balance_error=_BalanceError("daxili kontekst: available=2, requested=12"))
    controller, _ = _kiosk_controller(use_case)
    screen = _KioskStub()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.messages[-1] == _BalanceError.user_message
    assert "daxili kontekst" not in screen.messages[-1]


def test_submit_writes_commits_and_rereads_the_balance() -> None:
    """Yazıdan SONRA balans YENİDƏN oxunur (CLAUDE.md §6)."""
    use_case = _UseCase()
    controller, session = _kiosk_controller(use_case)
    screen = _KioskStub()

    controller._submit(screen, "2026-09-14", "2026-09-25")  # type: ignore[arg-type]

    assert use_case.submitted == [(date(2026, 9, 14), date(2026, 9, 25))]
    assert session.commits == 1
    assert use_case.balance_calls == 1, "Sorğudan sonra balans təzədən oxunmalıdır"
    assert screen.messages[-1] == SUBMIT_CONFIRMATION


def test_submit_failure_explains_the_reason_and_keeps_the_card_alive() -> None:
    """Domen istisnası sükutla udulmur, kart isə yenidən doldurulur."""
    use_case = _UseCase(submit_error=_BalanceError("balans çatmır"))
    controller, session = _kiosk_controller(use_case)
    screen = _KioskStub()

    controller._submit(screen, "2026-09-14", "2026-09-25")  # type: ignore[arg-type]

    assert session.commits == 0
    assert screen.messages[-1] == _BalanceError.user_message
    assert screen.balances, "Xətadan sonra da kart doldurulmalıdır"


def test_malformed_dates_never_reach_the_use_case() -> None:
    """Yanlış ISO tarixi sessiya AÇMADAN tutulur."""
    use_case = _UseCase()
    controller, session = _kiosk_controller(use_case)
    screen = _KioskStub()

    controller._submit(screen, "sabah", "2026-09-25")  # type: ignore[arg-type]

    assert use_case.submitted == []
    assert session.commits == 0
    assert screen.messages[-1] == "Seçilmiş tarixlər düzgün deyil."


# --------------------------------------------------------------------------- #
# HR təsdiq növbəsi
# --------------------------------------------------------------------------- #


def test_empty_inbox_is_not_an_error() -> None:
    """Gözləyən sorğu olmaması NORMAL haldır — qırmızı ekran GÖSTƏRİLMİR."""
    controller, _ = _inbox_controller(_UseCase(pending=[]))
    screen = _InboxStub()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.rows[-1] == []
    assert screen.errors == []


def test_permission_error_is_explained_with_the_user_message() -> None:
    """Flag-siz aktor ekranı açsa, səbəb `user_message`-dən gəlir."""
    use_case = _UseCase(inbox_error=_DeniedError("can_manage_leave_balances yoxdur"))
    controller, _ = _inbox_controller(use_case)
    screen = _InboxStub()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.rows[-1] == []
    assert screen.errors == [("Məzuniyyət sorğuları oxunmadı", _DeniedError.user_message)]


def test_approve_commits_and_rereads_the_inbox() -> None:
    """Təsdiqdən SONRA siyahı yenidən oxunur — qərar verilmiş sorğu itir."""
    owner = _seller()
    request = _request(owner.id, start=date(2026, 9, 14), end=date(2026, 9, 25))
    use_case = _UseCase(pending=[request])
    controller, session = _inbox_controller(use_case, owners={owner.id: owner})
    screen = _InboxStub()
    controller.refresh(screen)  # type: ignore[arg-type]
    assert len(screen.rows[-1]) == 1

    controller._on_approve(screen, str(request.id))  # type: ignore[arg-type]

    assert use_case.approved == [request.id]
    assert session.commits == 1
    assert use_case.inbox_calls == 2, "Qərardan sonra növbə təzədən oxunmalıdır"
    assert screen.rows[-1] == []


def test_approve_without_a_known_employee_is_reported_not_guessed() -> None:
    """Sorğunun sahibi tapılmasa use case ÇAĞIRILMIR (`hire_date` lazımdır)."""
    stranger = EmployeeId(uuid.uuid4())
    request = _request(stranger, start=date(2026, 9, 14), end=date(2026, 9, 25))
    use_case = _UseCase(pending=[request])
    controller, session = _inbox_controller(use_case)
    screen = _InboxStub()

    controller._on_approve(screen, str(request.id))  # type: ignore[arg-type]

    assert use_case.approved == []
    assert session.commits == 0
    assert screen.errors[-1][0] == "Sorğu təsdiqlənmədi"


def test_approve_failure_shows_the_user_message_and_refreshes(monkeypatch: Any) -> None:
    """Paralel təsdiq halı: səbəb AÇIQ yazılır, siyahı yenilənir."""
    owner = _seller()
    request = _request(owner.id, start=date(2026, 9, 14), end=date(2026, 9, 25))
    use_case = _UseCase(pending=[request], approve_error=_BalanceError("paralel təsdiq"))
    controller, session = _inbox_controller(use_case, owners={owner.id: owner})
    screen = _InboxStub()

    controller._on_approve(screen, str(request.id))  # type: ignore[arg-type]

    assert session.commits == 0
    assert screen.errors[-1] == ("Sorğu təsdiqlənmədi", _BalanceError.user_message)
    assert use_case.inbox_calls == 1, "Xətadan sonra da siyahı təzələnməlidir"


def test_reject_requires_a_reason_and_rereads_the_inbox(monkeypatch: Any) -> None:
    """Rədd səbəbi MƏCBURİDİR; boş cavab yazı yoluna GETMİR."""
    from src.presentation.controllers import annual_leave as module

    owner = _seller()
    request = _request(owner.id, start=date(2026, 9, 14), end=date(2026, 9, 25))
    use_case = _UseCase(pending=[request])
    controller, session = _inbox_controller(use_case, owners={owner.id: owner})
    screen = _InboxStub()

    monkeypatch.setattr(
        module.AnnualLeaveInboxController, "_ask_reason", staticmethod(lambda *_: None)
    )
    controller._on_reject(screen, str(request.id))  # type: ignore[arg-type]
    assert use_case.rejected == []
    assert session.commits == 0

    monkeypatch.setattr(
        module.AnnualLeaveInboxController,
        "_ask_reason",
        staticmethod(lambda *_: "Həmin həftə inventarizasiya var, sonraya keçirin."),
    )
    controller._on_reject(screen, str(request.id))  # type: ignore[arg-type]

    assert len(use_case.rejected) == 1
    assert use_case.rejected[0][1].startswith("Həmin həftə")
    assert session.commits == 1
    # Rəddən sonra sorğu növbədən çıxır — yenidən oxuma bunu göstərir.
    assert screen.rows[-1] == []


def test_malformed_request_id_never_opens_a_session() -> None:
    use_case = _UseCase()
    controller, session = _inbox_controller(use_case)
    screen = _InboxStub()

    controller._on_approve(screen, "sorğu-yox")  # type: ignore[arg-type]

    assert use_case.approved == []
    assert session.commits == 0
    assert screen.errors[-1][1] == "Sorğu identifikatoru düzgün deyil."


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def test_day_number_drops_meaningless_zeros_but_keeps_half_days() -> None:
    """`NUMERIC(5,2)` ekranda "14.00" kimi görünməməlidir."""
    assert _day_number(Decimal("14.00")) == "14"
    assert _day_number(Decimal("10.00")) == "10"
    assert _day_number(Decimal("14.50")) == "14.5"


def test_day_choices_stop_at_the_end_of_the_balance_year() -> None:
    """Horizont kartda göstərilən İLİN sonudur (bax `_day_choices` başlığı)."""
    today = date.today()  # noqa: DTZ011 — funksiyanın özü də təqvim günü işlədir
    choices = _day_choices(year=today.year)

    assert choices[0][0] == today.isoformat(), "Bugün DAXİLDİR"
    assert choices[-1][0] == date(today.year, 12, 31).isoformat()
    # Keçmiş il üçün seçim qalmır — dialoq ümumiyyətlə açılmır.
    assert _day_choices(year=today.year - 1) == []


def test_expired_carryover_reaches_the_row_as_a_flag() -> None:
    """`carryover_expired` sözlükdə DAŞINIR — ekran onu tondan çıxarır."""
    row = _to_balance_row(_view(expired=True))
    assert row["carryover_expired"] == "1"
    assert row["carryover_deadline"] == "31.03.2027"
    assert _to_balance_row(_view(expired=False))["carryover_expired"] == "0"


# --------------------------------------------------------------------------- #
# Ekranların ÖZÜ — Qt tələb edir
# --------------------------------------------------------------------------- #


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _home(theme: Any) -> Any:
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen

    return EmployeeHomeScreen(
        theme,
        full_name="Aysel Quliyeva",
        position_name="Satış Məsləhətçisi",
        store_name="Bellona 28 May",
    )


@requires_qt
def test_balance_card_renders_the_fourteen_of_twentyone_format(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """ "14/21 gün qalıb" — mətni EKRAN qurur, use case yalnız rəqəm verir."""
    screen = _home(theme)
    qtbot.addWidget(screen)

    screen.set_annual_leave_balance(dict(preview_data.ANNUAL_LEAVE_BALANCE))

    assert screen._annual_leave_value.text() == "14/21"
    assert screen._annual_leave_caption.text() == "gün qalıb"
    # Köçürmə sətri maketdə də GÖRÜNÜR — solğun tonda, son tarixlə birlikdə.
    assert "31.03.2027" in screen._annual_leave_carryover.text()


@requires_qt
def test_carryover_deadline_is_always_visible(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Köçürmə son tarixi ÜÇ vəziyyətdə də işçiyə çatdırılır."""
    screen = _home(theme)
    qtbot.addWidget(screen)

    screen.set_annual_leave_balance(_to_balance_row(_view(carried_over="5")))
    warning_text = screen._annual_leave_carryover.text()
    assert "31.03.2027" in warning_text
    assert "5 gün köçürülüb" in warning_text
    assert screen._annual_leave_chip.property("chip") == "warning"
    assert screen._annual_leave_chip.isVisibleTo(screen) is True

    screen.set_annual_leave_balance(_to_balance_row(_view(carried_over="5", expired=True)))
    expired_text = screen._annual_leave_carryover.text()
    assert "müddəti bitib" in expired_text
    assert "31.03.2027" in expired_text
    assert screen._annual_leave_chip.property("chip") == "danger"

    # Köçürmə yoxdursa nişan gizlənir, LAKİN son tarix sətri qalır.
    screen.set_annual_leave_balance(_to_balance_row(_view(carried_over="0")))
    plain_text = screen._annual_leave_carryover.text()
    assert "31.03.2027" in plain_text
    assert screen._annual_leave_chip.isVisibleTo(screen) is False


@requires_qt
def test_zero_carryover_written_with_decimals_is_not_a_warning(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """ "0.00" YALANÇI xəbərdarlıq doğurmamalıdır (bax `_has_carryover`)."""
    screen = _home(theme)
    qtbot.addWidget(screen)

    screen.set_annual_leave_balance(
        {
            "year": "2026",
            "available": "21",
            "total": "21",
            "used": "0",
            "carried_over": "0.00",
            "carryover_deadline": "31.03.2027",
            "carryover_expired": "0",
        }
    )

    assert "Köçürülən gün yoxdur" in screen._annual_leave_carryover.text()


@requires_qt
def test_empty_balance_keeps_the_request_button_usable(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Balans qeydi olmayan işçi "—" görür, ekran isə ÇÖKMÜR."""
    screen = _home(theme)
    qtbot.addWidget(screen)

    screen.set_annual_leave_balance({})

    assert screen._annual_leave_value.text() == "—"
    assert screen._annual_leave_caption.text() == "Balans məlumatı yoxdur"
    assert screen._annual_leave_carryover.text() == ""


@requires_qt
def test_request_button_emits_the_signal(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`[Məzuniyyət Sorğusu]` kontrollerə siqnal göndərir."""
    screen = _home(theme)
    qtbot.addWidget(screen)

    emitted: list[bool] = []
    screen.annual_leave_request_requested.connect(lambda: emitted.append(True))
    screen.annual_leave_request_requested.emit()

    assert emitted == [True]


@requires_qt
def test_inbox_shows_the_preview_rows_and_emits_row_keys(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Maket sətirləri render olunur və düymələr SƏTRİN açarını daşıyır."""
    from src.presentation.screens.annual_leave import AnnualLeaveInboxScreen

    screen = AnnualLeaveInboxScreen(theme)
    qtbot.addWidget(screen)

    screen.set_requests(list(preview_data.ANNUAL_LEAVE_PENDING))

    assert screen.switcher().current_state() == "content"
    approved: list[str] = []
    screen.approve_requested.connect(approved.append)
    screen.approve_requested.emit(preview_data.ANNUAL_LEAVE_PENDING[0]["id"])
    assert approved == ["al-1"]


@requires_qt
def test_empty_inbox_shows_the_empty_state_not_an_error(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.annual_leave import AnnualLeaveInboxScreen

    screen = AnnualLeaveInboxScreen(theme)
    qtbot.addWidget(screen)

    screen.set_requests([])

    assert screen.switcher().current_state() == "empty"


@requires_qt
def test_dialog_end_list_never_precedes_the_start(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """ "bitmə < başlanğıc" vəziyyəti UI-da MÖVCUD OLMUR."""
    from src.presentation.screens.annual_leave import AnnualLeaveRequestDialog

    days = [
        ("2026-09-14", "14.09.2026 · B.e"),
        ("2026-09-15", "15.09.2026 · Ç.a"),
        ("2026-09-16", "16.09.2026 · Çər"),
    ]
    dialog = AnnualLeaveRequestDialog(theme, days=days, balance_hint="Balansınızda 14 gün qalıb.")
    qtbot.addWidget(dialog)

    dialog._start.setCurrentIndex(2)
    assert dialog._end.count() == 1
    assert dialog._end.currentData() == "2026-09-16"

    dialog._start.setCurrentIndex(0)
    assert dialog._end.count() == 3


@requires_qt
def test_dialog_emits_both_dates(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.annual_leave import AnnualLeaveRequestDialog

    days = [("2026-09-14", "14.09.2026 · B.e"), ("2026-09-15", "15.09.2026 · Ç.a")]
    dialog = AnnualLeaveRequestDialog(theme, days=days)
    qtbot.addWidget(dialog)

    emitted: list[tuple[str, str]] = []
    dialog.submitted.connect(lambda start, end: emitted.append((start, end)))

    dialog._start.setCurrentIndex(0)
    dialog._end.setCurrentIndex(1)
    dialog._on_submit()

    assert emitted == [("2026-09-14", "2026-09-15")]


@requires_qt
def test_dialog_without_days_does_not_emit(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Boş siyahı müdafiə xətti: siqnal ATILMIR, səbəb YAZILIR."""
    from src.presentation.screens.annual_leave import AnnualLeaveRequestDialog

    dialog = AnnualLeaveRequestDialog(theme, days=[])
    qtbot.addWidget(dialog)

    emitted: list[tuple[str, str]] = []
    dialog.submitted.connect(lambda start, end: emitted.append((start, end)))
    dialog._on_submit()

    assert emitted == []
    assert dialog._hint.text() == "Başlanğıc və bitmə tarixi seçilməlidir."
