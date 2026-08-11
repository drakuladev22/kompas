"""Kataloq ekranlarının YAZI yolu — `controllers/catalog_admin.py`.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TESTLƏR
──────────────────────────────────────────────────────────────────────────────
Kontroller üç kataloq üçün ORTAQDIR və fərqlər `_ADAPTERS` cədvəlindədir. Bir
adapterdəki səhv (məs. `fine_types` üçün `work_modes` use case-inin
göstərilməsi) heç bir tip xətası vermir — nəticə yalnız istifadəçi ekranda
yanlış siyahı görəndə üzə çıxardı.

Testlər Qt TƏLƏB ETMİR: ekran duck-typing ilə əvəzlənir (kontroller ekrandan
yalnız `set_entries`, `show_error` və `theme` istifadə edir), sessiya isə
sadə saxta obyektdir.

SOFT DELETE qapısı ayrıca yoxlanılır: `toggle` aktiv sətirdə `deactivate()`,
DEAKTİV sətirdə isə `save(is_active=True)` çağırmalıdır. Əgər ikinci hal
`deactivate()`-ə düşsəydi, «Aktivləşdir» düyməsi heç nə etməzdi və deaktiv
sətir birdəfəlik ölü qalardı (`delete()` YOXDUR — bax `catalogs.py`).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from src.domain.value_objects.catalogs import FineType, LeaveType, WorkMode
from src.domain.value_objects.identifiers import (
    EmployeeId,
    FineTypeId,
    LeaveTypeId,
    TenantId,
    WorkModeId,
)
from src.domain.value_objects.money import Money
from src.domain.value_objects.scheduling import TimeRange
from src.presentation.controllers.catalog_admin import (
    CATALOG_KEYS,
    CatalogAdminController,
    CatalogInputError,
    _parse_amount,
    _parse_minutes,
    _parse_schedule,
)
from src.shared.exceptions import KompasOSError

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Saxta mühit
# --------------------------------------------------------------------------- #


class _Screen:
    """`CatalogScreen` əvəzi — kontrollerin toxunduğu ÜÇ üzv."""

    theme = object()

    def __init__(self) -> None:
        self.rows: list[dict[str, str]] = []
        self.errors: list[tuple[str, str]] = []

    def set_entries(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


class _CatalogUseCase:
    """Üç kataloq use case-inin ortaq saxtası — çağırışları qeyd edir."""

    def __init__(self, entries: list[Any]) -> None:
        self.entries = entries
        self.saved: list[Any] = []
        self.deactivated: list[Any] = []
        self.error: Exception | None = None

    def list_for_management(self, tenant_id: TenantId, actor: Any) -> list[Any]:
        if self.error is not None:
            raise self.error
        return list(self.entries)

    def save(self, tenant_id: TenantId, actor: Any, entry: Any) -> None:
        self.saved.append(entry)

    def deactivate(self, tenant_id: TenantId, actor: Any, entry_id: Any) -> None:
        self.deactivated.append(entry_id)


class _Session:
    def __init__(self, use_case: _CatalogUseCase) -> None:
        self.tenant_id = TENANT
        self.work_modes = use_case
        self.fine_types = use_case
        self.leave_types = use_case
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Context:
    """`ApplicationContext.session()` müqaviləsinin minimal təkrarı."""

    def __init__(self, session: _Session) -> None:
        self._session = session
        self.opened = 0

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        self.opened += 1
        yield self._session


def _actor() -> Any:
    return type("_Actor", (), {"id": EmployeeId(uuid.uuid4())})()


def _controller(key: str, use_case: _CatalogUseCase) -> tuple[CatalogAdminController, _Context]:
    context = _Context(_Session(use_case))
    return (CatalogAdminController(context, _actor(), key=key), context)  # type: ignore[arg-type]


def _work_mode(*, active: bool = True) -> WorkMode:
    from datetime import time

    return WorkMode(
        name="Səhər növbəsi",
        tenant_id=TENANT,
        is_active=active,
        deactivated_at=None if active else NOW,
        work_mode_id=WorkModeId(uuid.uuid4()),
        schedule=TimeRange(time(9, 0), time(18, 0)),
    )


def _fine_type(*, active: bool = True) -> FineType:
    return FineType(
        name="Formaya uyğun geyinməmək",
        tenant_id=TENANT,
        is_active=active,
        deactivated_at=None if active else NOW,
        fine_type_id=FineTypeId(uuid.uuid4()),
        standard_amount=Money(Decimal("25.00")),
    )


def _leave_type(*, active: bool = True) -> LeaveType:
    return LeaveType(
        name="Nahar fasiləsi",
        tenant_id=TENANT,
        is_active=active,
        deactivated_at=None if active else NOW,
        leave_type_id=LeaveTypeId(uuid.uuid4()),
        default_duration_minutes=60,
    )


# --------------------------------------------------------------------------- #
# Oxu yolu
# --------------------------------------------------------------------------- #


def test_all_three_catalog_keys_have_an_adapter() -> None:
    """Açar `app.py::factories` ilə eyni olmalıdır — maket/canlı ad məkanı."""
    for key in CATALOG_KEYS:
        controller, _ = _controller(key, _CatalogUseCase([]))
        assert controller is not None


@pytest.mark.parametrize(
    ("key", "entry", "expected_cells"),
    [
        ("work_modes", _work_mode(), "Səhər növbəsi|09:00–18:00"),
        ("fine_types", _fine_type(), "Formaya uyğun geyinməmək|25.00 ₼"),
        ("leave_types", _leave_type(), "Nahar fasiləsi|1 saat"),
    ],
)
def test_refresh_renders_domain_rows_into_screen_cells(
    key: str, entry: Any, expected_cells: str
) -> None:
    """Sətir ekranın gözlədiyi `key`/`cells`/`is_active` formasına çevrilir."""
    use_case = _CatalogUseCase([entry])
    controller, _ = _controller(key, use_case)
    screen = _Screen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert len(screen.rows) == 1
    assert screen.rows[0]["cells"] == expected_cells
    assert screen.rows[0]["is_active"] == "1"
    assert screen.errors == []


def test_refresh_shows_the_reason_when_permission_is_missing() -> None:
    """Səlahiyyət yoxdursa cədvəl BOŞ deyil, SƏBƏBLƏ göstərilir."""

    class _DeniedError(KompasOSError):
        user_message = "Bu kataloqu dəyişdirmək səlahiyyətiniz yoxdur."

    use_case = _CatalogUseCase([])
    use_case.error = _DeniedError("flag yoxdur")
    controller, _ = _controller("fine_types", use_case)
    screen = _Screen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.rows == []
    assert screen.errors == [
        ("Kataloq açıla bilmədi", "Bu kataloqu dəyişdirmək səlahiyyətiniz yoxdur.")
    ]


# --------------------------------------------------------------------------- #
# Soft delete (bax modul başlığı)
# --------------------------------------------------------------------------- #


def test_toggle_deactivates_an_active_entry() -> None:
    entry = _fine_type(active=True)
    use_case = _CatalogUseCase([entry])
    controller, context = _controller("fine_types", use_case)
    screen = _Screen()
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_toggle(screen, screen.rows[0]["key"])  # type: ignore[arg-type]

    assert use_case.deactivated == [entry.fine_type_id]
    assert use_case.saved == []
    # Hər əməliyyat ÖZ sessiyasındadır: ilk oxu, yazı, sonra yenidən oxu.
    assert context.opened == 3


def test_toggle_reactivates_a_deactivated_entry_via_save() -> None:
    """Deaktiv sətir `save(is_active=True)` ilə dirilir — `delete()` YOXDUR."""
    entry = _fine_type(active=False)
    use_case = _CatalogUseCase([entry])
    controller, _ = _controller("fine_types", use_case)
    screen = _Screen()
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_toggle(screen, screen.rows[0]["key"])  # type: ignore[arg-type]

    assert use_case.deactivated == []
    assert len(use_case.saved) == 1
    revived = use_case.saved[0]
    assert revived.is_active is True
    assert revived.deactivated_at is None
    # Kimlik QORUNUR: yeni sətir yaradılmır, mövcud sətir yenidən yazılır.
    assert revived.fine_type_id == entry.fine_type_id


def test_edit_keeps_the_current_active_state() -> None:
    """«Redaktə» sətri DİRİLTMİR — aktivləşdirmə ayrı düymədir."""
    entry = _leave_type(active=False)
    use_case = _CatalogUseCase([entry])
    controller, _ = _controller("leave_types", use_case)
    screen = _Screen()
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._save(screen, existing=entry, name="Nahar fasiləsi", value="45")  # type: ignore[arg-type]

    saved = use_case.saved[0]
    assert saved.is_active is False
    assert saved.default_duration_minutes == 45
    assert saved.deactivated_at is not None


def test_missing_row_key_refreshes_instead_of_failing() -> None:
    """Siyahı köhnəlibsə istifadəçi səbəbi görür və siyahı yenilənir."""
    use_case = _CatalogUseCase([_work_mode()])
    controller, _ = _controller("work_modes", use_case)
    screen = _Screen()
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_toggle(screen, "naməlum-açar")  # type: ignore[arg-type]

    assert use_case.deactivated == []
    assert screen.errors[0][0] == "Sətir tapılmadı"


# --------------------------------------------------------------------------- #
# Dəyər çevirmələri
# --------------------------------------------------------------------------- #


def test_schedule_accepts_both_dash_characters() -> None:
    """Ekranda uzun tire göstərilir, klaviaturada qısa yazılır — ikisi də keçir."""
    assert _parse_schedule("09:00-18:00") == _parse_schedule("09:00–18:00")


def test_schedule_free_shift_has_no_time_range() -> None:
    """«Növbəli 2/2» kimi rejimlərdə sabit saat yoxdur (bax `WorkMode`)."""
    assert _parse_schedule("sərbəst") is None


def test_invalid_values_raise_a_user_readable_error() -> None:
    for parser, raw in ((_parse_schedule, "09:00"), (_parse_amount, "abc"), (_parse_minutes, "x")):
        with pytest.raises(CatalogInputError) as error:
            parser(raw)  # type: ignore[operator]
        assert error.value.user_message


def test_amount_accepts_the_format_the_screen_itself_shows() -> None:
    """Cədvəldə «25 ₼» yazılır — həmin mətn geri yazıla bilməlidir."""
    assert _parse_amount("25,50 ₼") == Decimal("25.50")
