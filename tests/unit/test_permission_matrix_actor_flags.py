"""İcazə matrisində AKTORDA OLMAYAN flag deaktiv göstərilir (audit tapıntısı D-3).

──────────────────────────────────────────────────────────────────────────────
BU TƏHLÜKƏSİZLİK BOŞLUĞU DEYİL — GÖRÜNTÜ QÜSURUDUR, LAKİN NƏTİCƏSİ REALDIR
──────────────────────────────────────────────────────────────────────────────
Backend qapısı (`PositionManagementUseCase._apply_flags` → Self-Escalation
Guard) yerindədir və aktorun ÖZÜNDƏ olmayan flag-i rola verməsini rədd edir.
Problem yalnız zamanlamada idi: admin xananı işarələyir, "Yadda Saxla" basır,
BÜTÜN seçim geri qaytarılır və hansı xananın günahkar olduğu bəlli olmur.

Düzəliş qaydanı ekrana KÖÇÜRMÜR — kontroller aktorun effektiv flag dəstini
onsuz da bilir və həmin məlumatı matris sətrinin beşinci sahəsi kimi ötürür.
Testlər hər iki qatı yoxlayır: məlumatın DOĞRU hazırlandığını (Qt-siz) və
ekranın onu DOĞRU göstərdiyini (Qt).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest

from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import (
    HardlockLevel,
    PermissionEffect,
    PermissionFlag,
    RolePriority,
    SystemRole,
)
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import EmployeeId, PositionId, TenantId
from src.presentation import preview_data
from src.presentation.controllers.permission_matrix import _flag_groups
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())

OWNED: Final = PermissionFlag(code="can_view_appeals", category="Cərimə")
NOT_OWNED: Final = PermissionFlag(code="can_manage_fine_types", category="Cərimə")
HARDLOCKED: Final = PermissionFlag(
    code="can_manage_backups", category="Sistem", hardlock=HardlockLevel.ROOT_CEO
)


# --------------------------------------------------------------------------- #
# Sahtə sessiya — `_flag_groups` yalnız kataloq + etiket sorğusu işlədir
# --------------------------------------------------------------------------- #


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)


class _Connection:
    def __init__(self, catalog: list[PermissionFlag]) -> None:
        self._catalog = catalog

    def execute(self, sql: str, params: Any = None) -> _Cursor:
        if "permission_flags" in sql:
            return _Cursor([{"code": flag.code, "name_az": flag.code} for flag in self._catalog])
        return _Cursor([])


class _FlagRepo:
    def __init__(self, catalog: list[PermissionFlag]) -> None:
        self._catalog = catalog

    def list_all(self) -> list[PermissionFlag]:
        return list(self._catalog)


class _Uow:
    def __init__(self, catalog: list[PermissionFlag]) -> None:
        self.connection = _Connection(catalog)
        self._flags = _FlagRepo(catalog)

    def repository(self, name: str) -> Any:
        assert name == "permission_flags"
        return self._flags


class _Session:
    def __init__(self, catalog: list[PermissionFlag]) -> None:
        self.tenant_id = TENANT
        self.uow = _Uow(catalog)


def _position(code: str, priority: RolePriority, *flags: PermissionFlag) -> Position:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=code,
        name_az=code.title(),
        priority=priority,
        tenant_id=TENANT,
        is_system=True,
    )
    for flag in flags:
        position.grant(flag)
    return position


def _employee(position: Position) -> Employee:
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="T",
        last_name=position.code,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )


def _rows(groups: Any) -> dict[str, tuple[Any, ...]]:
    return {item[0]: item for _category, items in groups for item in items}


# --------------------------------------------------------------------------- #
# 1. Məlumat qatı — kontroller aktorun sahibliyini ötürür
# --------------------------------------------------------------------------- #


def test_flag_the_actor_does_not_hold_is_marked_unavailable() -> None:
    """Beşinci sahə: `True` = aktorda var, `False` = verə bilməz."""
    catalog = [OWNED, NOT_OWNED, HARDLOCKED]
    session = _Session(catalog)
    target = _position(SystemRole.HR_ADMIN.value, RolePriority.OPERATIONAL)
    actor = _employee(_position(SystemRole.CEO.value, RolePriority.EXECUTIVE, OWNED))

    rows = _rows(_flag_groups(session, target, actor=actor))  # type: ignore[arg-type]

    assert rows[OWNED.code][4] is True, "Aktorda olan flag AKTİV qalmalıdır"
    assert rows[NOT_OWNED.code][4] is False, (
        "Aktorda OLMAYAN flag deaktiv işarələnməlidir — əks halda admin rədd "
        "ediləcəyini yalnız 'Yadda Saxla'-dan sonra bilər"
    )


def test_an_expired_override_does_not_count_as_ownership() -> None:
    """Sahiblik EFFEKTİVDİR — `Employee.has_permission` ilə eyni cavab.

    Vaxtı keçmiş override sahiblik vermir; ekran fərqli qərar versəydi, admin
    artıq işləməyən icazəni paylaya biləcəyini sanardı.
    """
    catalog = [NOT_OWNED]
    session = _Session(catalog)
    target = _position(SystemRole.HR_ADMIN.value, RolePriority.OPERATIONAL)
    actor = _employee(_position(SystemRole.CEO.value, RolePriority.EXECUTIVE))
    actor.apply_override(
        PermissionOverride(
            flag_code=NOT_OWNED.code,
            effect=PermissionEffect.GRANT,
            granted_by=actor.id,
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )

    rows = _rows(_flag_groups(session, target, actor=actor))  # type: ignore[arg-type]

    assert rows[NOT_OWNED.code][4] is False


def test_without_an_actor_no_extra_cell_is_disabled() -> None:
    """Aktor konteksti olmayan çağırış (maket/test) matrisi bağlamamalıdır.

    Bu, təhlükəsizlik güzəşti deyil: sahə yalnız GÖRÜNTÜNÜ idarə edir, yazını
    isə use case rədd edir.
    """
    session = _Session([OWNED, NOT_OWNED])
    target = _position(SystemRole.HR_ADMIN.value, RolePriority.OPERATIONAL)

    rows = _rows(_flag_groups(session, target))  # type: ignore[arg-type]

    assert all(row[4] is True for row in rows.values())


def test_the_mockup_rows_carry_the_same_five_fields_as_the_live_path() -> None:
    """CLAUDE.md §6: maket və canlı yol EYNİ açarları işlətməlidir.

    Maket dörd sahəli sətirdə qalsaydı, ekran maketdə `ValueError` verərdi və
    uyğunsuzluq yalnız GUI açılanda üzə çıxardı.
    """
    for _category, items in preview_data.PERMISSION_GROUPS:
        for item in items:
            assert len(item) == 5, f"Maket sətri beş sahəli deyil: {item}"
            assert isinstance(item[4], bool)

    flat = _rows(preview_data.PERMISSION_GROUPS)
    assert flat["can_issue_fines"][4] is False, (
        "Maket 'aktorda olmayan icazə' vəziyyətini ən azı bir sətirdə göstərməlidir"
    )


# --------------------------------------------------------------------------- #
# 2. Ekran qatı — Qt tələb edir
# --------------------------------------------------------------------------- #


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


@requires_qt
def test_unavailable_cell_is_disabled_with_its_own_tooltip(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Hardlock ilə "sizdə yoxdur" AYRI izah verir — səbəblər fərqlidir."""
    from src.presentation.screens.group_c import PermissionMatrixScreen

    screen = PermissionMatrixScreen(theme)
    qtbot.addWidget(screen)

    screen.set_matrix(
        "HR_Admin",
        [
            (
                "Cərimə",
                [
                    (OWNED.code, "Etirazlara baxmaq", True, False, True),
                    (NOT_OWNED.code, "Cərimə tarifləri", False, False, False),
                    (HARDLOCKED.code, "Ehtiyat nüsxə", False, True, True),
                ],
            )
        ],
    )

    boxes = screen._checkboxes
    assert boxes[OWNED.code].isEnabled() is True
    assert boxes[NOT_OWNED.code].isEnabled() is False
    assert boxes[NOT_OWNED.code].toolTip() == "Bu icazə sizdə yoxdur — başqasına verə bilməzsiniz"
    # Hardlock izahı DƏYİŞMİR: "heç kim dəyişə bilməz" ilə "sən verə bilməzsən"
    # eyni şey deyil və admin ikisini qarışdırmamalıdır.
    assert boxes[HARDLOCKED.code].isEnabled() is False
    assert "Hardlock" in boxes[HARDLOCKED.code].toolTip()


@requires_qt
def test_disabled_cells_are_still_sent_to_the_use_case(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Deaktiv xana MATRİSDƏN DÜŞMÜR — `set_role_flags` dəsti TAM əvəzləyir.

    Xana `collected()`-dən çıxsaydı, rolun mövcud icazəsi ilk yadda saxlamada
    SÜKUTLA silinərdi — deaktiv etmək "yox saymaq" demək deyil.
    """
    from src.presentation.screens.group_c import PermissionMatrixScreen

    screen = PermissionMatrixScreen(theme)
    qtbot.addWidget(screen)

    screen.set_matrix(
        "HR_Admin",
        [
            (
                "Cərimə",
                [
                    (OWNED.code, "Etirazlara baxmaq", True, False, True),
                    # Aktorda yoxdur, LAKİN rolda VAR — göndərilməli və qalmalıdır.
                    (NOT_OWNED.code, "Cərimə tarifləri", True, False, False),
                ],
            )
        ],
    )

    collected = screen.collected()
    assert collected == {OWNED.code: True, NOT_OWNED.code: True}


@requires_qt
def test_the_preview_path_fills_the_matrix_screen(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Maket yolu ekranı SINDIRMADAN doldurur (beş sahəli sətirlə)."""
    from src.presentation.preview_screens import populate
    from src.presentation.screens.group_c import PermissionMatrixScreen

    screen = PermissionMatrixScreen(theme)
    qtbot.addWidget(screen)

    populate("permissions", screen)

    assert screen._checkboxes["can_issue_fines"].isEnabled() is False
    assert screen._checkboxes["can_view_leave"].isEnabled() is True
