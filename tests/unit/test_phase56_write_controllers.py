"""Faza 5/6 yazı kontrollerləri — profil, plugin, dashboard qurucusu, satış növbəsi.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TESTLƏR
──────────────────────────────────────────────────────────────────────────────
Hər dördü HƏM oxuyur, HƏM yazır və hər yazıdan sonra siyahını yenidən oxuyur.
Bu dövrədəki səhv (commit unudulması, yanlış use case metodu, siyahının
yenilənməməsi) heç bir tip xətası vermir — istifadəçi yalnız "dəyişiklik
itdi" deyəndə üzə çıxır.

Testlər Qt TƏLƏB ETMİR: ekranlar duck-typing ilə əvəzlənir.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Final

import pytest

from src.domain.value_objects.identifiers import EmployeeId, TenantId
from src.domain.value_objects.money import Money
from src.presentation.controllers.dashboard_builder import DashboardBuilderController
from src.presentation.controllers.plugin_admin import PluginAdminController
from src.presentation.controllers.profile import PASSWORD_POLICY_NOTE, ProfileController
from src.presentation.controllers.sales_review import SINGLE_REASON, SalesReviewController
from src.shared.exceptions import KompasOSError

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())


class _DeniedError(KompasOSError):
    user_message = "Bu əməliyyat üçün səlahiyyətiniz yoxdur."


def _actor() -> Any:
    return type("_Actor", (), {"id": EmployeeId(uuid.uuid4())})()


class _Context:
    """`ApplicationContext.session()` müqaviləsinin minimal təkrarı."""

    def __init__(self, session: Any) -> None:
        self._session = session
        self.opened = 0

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        self.opened += 1
        yield self._session


# --------------------------------------------------------------------------- #
# Dashboard qurucusu
# --------------------------------------------------------------------------- #


class _BuilderScreen:
    def __init__(self) -> None:
        self.widgets: list[tuple[dict[str, Any], list[str], set[str]]] = []
        self.errors: list[tuple[str, str]] = []

    def set_widgets(
        self, catalog: dict[str, tuple[str, str]], *, order: list[str], visible: set[str]
    ) -> None:
        self.widgets.append((dict(catalog), list(order), set(visible)))

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


class _View:
    def __init__(self, keys: tuple[str, ...]) -> None:
        self.order = keys
        self.visible = frozenset(keys)

    def catalog_map(self) -> dict[str, tuple[str, str]]:
        return {key: (key.title(), "izah") for key in self.order}


class _LayoutUseCase:
    def __init__(self, *, save_error: Exception | None = None) -> None:
        self.saved: list[list[str]] = []
        self.resets = 0
        self.save_error = save_error

    def view_for(self, *, actor: Any, tenant_id: Any) -> _View:
        return _View(("attendance", "fines"))

    def save(self, *, actor: Any, tenant_id: Any, layout: list[str]) -> _View:
        if self.save_error is not None:
            raise self.save_error
        self.saved.append(list(layout))
        return _View(tuple(layout))

    def reset(self, *, actor: Any, tenant_id: Any) -> _View:
        self.resets += 1
        return _View(("attendance", "fines"))


class _LayoutSession:
    def __init__(self, use_case: _LayoutUseCase) -> None:
        self.tenant_id = TENANT
        self.dashboard_layout = use_case
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def test_layout_change_is_saved_committed_and_re_read() -> None:
    """Yazıdan SONRA siyahı yenidən oxunur — use case açar süzgəci tətbiq edir."""
    use_case = _LayoutUseCase()
    session = _LayoutSession(use_case)
    controller = DashboardBuilderController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _BuilderScreen()

    controller._on_layout_changed(screen, ["fines", "attendance"])  # type: ignore[arg-type]

    assert use_case.saved == [["fines", "attendance"]]
    assert session.commits == 1
    assert screen.widgets, "Yazıdan sonra ekran yenidən doldurulmalıdır"


def test_layout_save_denial_is_explained_not_swallowed() -> None:
    """`can_edit_dashboard_widgets` yoxdursa səbəb GÖRÜNÜR."""
    use_case = _LayoutUseCase(save_error=_DeniedError("flag yoxdur"))
    session = _LayoutSession(use_case)
    controller = DashboardBuilderController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _BuilderScreen()

    controller._on_layout_changed(screen, ["fines"])  # type: ignore[arg-type]

    assert session.commits == 0
    assert screen.errors == [("Düzülüş saxlanmadı", "Bu əməliyyat üçün səlahiyyətiniz yoxdur.")]


def test_reset_uses_the_use_case_not_a_local_default() -> None:
    """Defolt düzülüş use case-dədir — kontroller onu TƏKRAR TƏYİN ETMİR."""
    use_case = _LayoutUseCase()
    session = _LayoutSession(use_case)
    controller = DashboardBuilderController(_Context(session), _actor())  # type: ignore[arg-type]

    controller._on_reset(_BuilderScreen())  # type: ignore[arg-type]

    assert use_case.resets == 1
    assert use_case.saved == []


# --------------------------------------------------------------------------- #
# Plugin idarəetməsi
# --------------------------------------------------------------------------- #


class _PluginScreen:
    def __init__(self) -> None:
        self.rows: list[dict[str, str]] = []
        self.errors: list[tuple[str, str]] = []

    def set_plugins(self, plugins: list[dict[str, str]]) -> None:
        self.rows = plugins

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


class _PluginUseCase:
    def __init__(self, plugins: list[Any], *, toggle_error: Exception | None = None) -> None:
        self.plugins = plugins
        self.toggle_error = toggle_error
        self.toggled: list[tuple[str, bool]] = []
        self.removed: list[str] = []

    def list_plugins(self, *, tenant_id: Any, actor: Any) -> list[Any]:
        return list(self.plugins)

    def set_enabled(self, *, tenant_id: Any, actor: Any, plugin_id: str, enabled: bool) -> Any:
        if self.toggle_error is not None:
            raise self.toggle_error
        self.toggled.append((plugin_id, enabled))
        return None

    def remove(self, *, tenant_id: Any, actor: Any, plugin_id: str) -> None:
        self.removed.append(plugin_id)


class _PluginSession:
    def __init__(self, use_case: _PluginUseCase) -> None:
        self.tenant_id = TENANT
        self.plugins = use_case
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _installed(**overrides: Any) -> Any:
    from src.application.use_cases.plugin_management import InstalledPlugin
    from src.infrastructure.plugins.contracts import PluginStatus

    defaults: dict[str, Any] = {
        "plugin_id": "pl-1",
        "name": "Anbar Hesabatı",
        "version": "1.2.0",
        "publisher": "Kompas Studio",
        "status": PluginStatus.APPROVED,
        "signature_verified": True,
    }
    defaults.update(overrides)
    return InstalledPlugin(**defaults)


def test_plugin_rows_use_the_screen_key_namespace() -> None:
    """Sətir açarları maket yolu (`preview_data.PLUGINS`) ilə EYNİ olmalıdır."""
    session = _PluginSession(_PluginUseCase([_installed()]))
    controller = PluginAdminController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _PluginScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert set(screen.rows[0]) == {"id", "name", "version", "publisher", "enabled", "signature"}
    assert screen.rows[0]["signature"] == "valid"
    assert screen.rows[0]["enabled"] == "1"


def test_rejected_toggle_refreshes_so_the_screen_does_not_lie() -> None:
    """İmzasız plugin aktivləşdirilə bilməz — açar geri qayıtmalıdır."""
    use_case = _PluginUseCase([_installed()], toggle_error=_DeniedError("imza yoxdur"))
    session = _PluginSession(use_case)
    controller = PluginAdminController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _PluginScreen()

    controller._on_toggle(screen, "pl-1", enabled=True)  # type: ignore[arg-type]

    assert use_case.toggled == []
    assert session.commits == 0
    assert screen.errors[0][0] == "Plugin dəyişdirilmədi"
    # Rədd edildikdən SONRA siyahı yenidən oxunub — ekrandakı açar bazadakı
    # vəziyyəti göstərir.
    assert screen.rows, "Rədd edilmiş dəyişiklikdən sonra siyahı yenilənməlidir"


# --------------------------------------------------------------------------- #
# Şübhəli satış növbəsi
# --------------------------------------------------------------------------- #


class _SalesScreen:
    def __init__(self) -> None:
        self.sales: list[dict[str, str]] = []
        self.total = ""
        self.errors: list[tuple[str, str]] = []

    def set_sales(self, sales: list[dict[str, str]], *, total_amount: str) -> None:
        self.sales = sales
        self.total = total_amount

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


class _QueueUseCase:
    def __init__(self, items: list[Any]) -> None:
        self.items = items
        self.reassigned: list[tuple[Any, Any, str]] = []
        self.confirmed: list[Any] = []

    def queue(self, *, tenant_id: Any, actor: Any) -> list[Any]:
        return list(self.items)

    def reassign(
        self, *, tenant_id: Any, actor: Any, transaction_id: Any, employee_id: Any, reason: str
    ) -> Any:
        self.reassigned.append((transaction_id, employee_id, reason))
        return None

    def confirm(self, *, tenant_id: Any, actor: Any, transaction_id: Any) -> Any:
        self.confirmed.append(transaction_id)
        return None


class _SalesSession:
    def __init__(self, use_case: _QueueUseCase) -> None:
        self.tenant_id = TENANT
        self.sales_review = use_case
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _queue_item(*, suggested: Any = None, name: str = "") -> Any:
    from datetime import UTC, datetime

    from src.application.use_cases.sales_review_queue import ReviewQueueItem
    from src.domain.value_objects.erp import MatchConfidence
    from src.domain.value_objects.identifiers import SalesTransactionId

    return ReviewQueueItem(
        transaction_id=SalesTransactionId(uuid.uuid4()),
        server_name="1C — Bakı",
        one_c_seller_id="S-1",
        one_c_seller_name=name or None,
        one_c_store_code="BAKI-01",
        one_c_document_id="4471",
        gross_amount=Money(Decimal("1240.00")),
        transaction_date=datetime(2026, 8, 12, 14, 22, tzinfo=UTC),
        confidence=(
            MatchConfidence.LOW_CONFIDENCE_MATCH if suggested else MatchConfidence.UNASSIGNED
        ),
        match_reason=None,
        suggested_employee_id=suggested,
        suggested_employee_name=name,
    )


def test_assignment_to_a_different_employee_transfers_points() -> None:
    """Təklifdən FƏRQLİ işçi seçilibsə `reassign()` çağırılır (xal köçür)."""
    suggested = EmployeeId(uuid.uuid4())
    chosen = EmployeeId(uuid.uuid4())
    item = _queue_item(suggested=suggested, name="A. Quliyeva")
    use_case = _QueueUseCase([item])
    session = _SalesSession(use_case)
    controller = SalesReviewController(_Context(session), _actor())  # type: ignore[arg-type]
    controller._items = {"4471": item}
    controller._employees = {"K. Vəliyev": chosen}
    screen = _SalesScreen()

    controller._on_assign(screen, "4471", "K. Vəliyev")  # type: ignore[arg-type]

    assert use_case.confirmed == []
    assert use_case.reassigned == [(item.transaction_id, chosen, SINGLE_REASON)]
    assert session.commits == 1


def test_assignment_to_the_suggested_employee_only_confirms() -> None:
    """Seçim 1C təklifi ilə EYNİDİRSƏ xal TOXUNULMUR — yalnız təsdiq."""
    suggested = EmployeeId(uuid.uuid4())
    item = _queue_item(suggested=suggested, name="A. Quliyeva")
    use_case = _QueueUseCase([item])
    session = _SalesSession(use_case)
    controller = SalesReviewController(_Context(session), _actor())  # type: ignore[arg-type]
    controller._items = {"4471": item}
    controller._employees = {"A. Quliyeva": suggested}
    screen = _SalesScreen()

    controller._on_assign(screen, "4471", "A. Quliyeva")  # type: ignore[arg-type]

    assert use_case.reassigned == []
    assert use_case.confirmed == [item.transaction_id]


def test_stale_receipt_is_refused_instead_of_guessing() -> None:
    """Naməlum çek SÜKUTLA keçilmir — səhv sətrə təyinat real pula təsir edir."""
    use_case = _QueueUseCase([])
    session = _SalesSession(use_case)
    controller = SalesReviewController(_Context(session), _actor())  # type: ignore[arg-type]
    screen = _SalesScreen()

    controller._on_assign(screen, "9999", "A. Quliyeva")  # type: ignore[arg-type]

    assert use_case.reassigned == []
    assert use_case.confirmed == []
    assert session.commits == 0
    assert screen.errors[0][0] == "Siyahı köhnəlib"


# --------------------------------------------------------------------------- #
# Profil
# --------------------------------------------------------------------------- #


class _ProfileScreen:
    def __init__(self) -> None:
        self.account: dict[str, str] = {}
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


class _Users:
    def __init__(self) -> None:
        self.updates: list[Any] = []

    def update_employee(self, *, tenant_id: Any, actor: Any, employee_id: Any, draft: Any) -> Any:
        self.updates.append(draft)
        return None


class _Employees:
    def __init__(self, employee: Any) -> None:
        self._employee = employee

    def get(self, employee_id: Any) -> Any:
        return self._employee


class _ProfileUow:
    def __init__(self, employee: Any) -> None:
        self.employees = _Employees(employee)


class _ProfileSession:
    def __init__(self, employee: Any, users: _Users) -> None:
        self.tenant_id = TENANT
        self.users = users
        self.uow = _ProfileUow(employee)
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _profile_employee() -> Any:
    from src.domain.entities.employee import Employee
    from src.domain.entities.position import Position
    from src.domain.value_objects.authorization import RolePriority
    from src.domain.value_objects.credentials import Username
    from src.domain.value_objects.identifiers import PositionId

    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code="HR_ADMIN",
        name_az="HR Admin",
        priority=RolePriority.OPERATIONAL,
        tenant_id=TENANT,
        is_system=True,
    )
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Rəşad",
        last_name="Məmmədov",
        username=Username.parse("r.mammadov"),
        has_password=True,
    )


def test_profile_save_writes_only_the_name() -> None:
    """`username`/`email` yazı yoluna DÜŞMÜR (bax modul başlığı)."""
    employee = _profile_employee()
    users = _Users()
    session = _ProfileSession(employee, users)
    controller = ProfileController(_Context(session), employee)  # type: ignore[arg-type]
    screen = _ProfileScreen()

    controller._on_saved(  # type: ignore[arg-type]
        screen,
        {"full_name": "Rəşad Əli Məmmədov", "phone": "+994 50 000 00 00", "username": "hacker"},
    )

    assert len(users.updates) == 1
    draft = users.updates[0]
    assert draft.first_name == "Rəşad Əli"
    assert draft.last_name == "Məmmədov"
    # İstifadəçi adı ekranın göndərdiyi dəyərdən DEYİL, mövcud hesabdan gəlir.
    assert str(draft.username) == "r.mammadov"
    assert session.commits == 1


def test_profile_save_refuses_an_empty_name() -> None:
    employee = _profile_employee()
    users = _Users()
    session = _ProfileSession(employee, users)
    controller = ProfileController(_Context(session), employee)  # type: ignore[arg-type]
    screen = _ProfileScreen()

    controller._on_saved(screen, {"full_name": "   "})  # type: ignore[arg-type]

    assert users.updates == []
    assert screen.errors[0][0] == "Ad boş ola bilməz"


def test_password_policy_note_points_at_the_existing_flow() -> None:
    """Yeni şifrə axını İCAD EDİLMİR — mövcud admin-vasitəçili yol izah olunur."""
    assert "administrator" in PASSWORD_POLICY_NOTE.lower()
