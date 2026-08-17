"""İcazə Matrisinin yazı yolu — GUARD-lar HƏQİQƏTƏN işə düşürmü.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TESTLƏR MƏCBURİDİR
──────────────────────────────────────────────────────────────────────────────
Bu ekran icazə flag-lərini paylayır: bir checkbox real pul (cərimə yazmaq),
real nəzarət (dual-control) və real məlumat girişi deməkdir. Kontrollerin
qoruyucu qaydaları YAN KEÇMƏSİ heç bir tip xətası vermir — nəticə yalnız
istehsalatda, artıq səlahiyyət verildikdən sonra üzə çıxardı.

Ona görə burada SAXTA use case İŞLƏDİLMİR: `PositionManagementUseCase`-in
ÖZÜ qurulur (saxta olan yalnız repo-lar və audit-dir), yəni:

    * SELF-ESCALATION GUARD  (`_apply_flags`)
    * ANTI-FRAUD vəzifə ayrılığı + hardlock (`PermissionFlag.assert_grantable_to`)
    * `can_manage_positions` qapısı (`_require_permission`)

hamısı testdə REAL kodla icra olunur. Test yalnız NƏTİCƏNİ yoxlayır: yazı
BAŞ TUTMUR və istifadəçi səbəbi GÖRÜR.

Testlər Qt TƏLƏB ETMİR — ekran duck-typing ilə əvəzlənir.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Final

import pytest

from src.application.use_cases.position_management import PositionManagementUseCase
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import (
    HardlockLevel,
    PermissionFlag,
    SystemRole,
)
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import EmployeeId, PositionId, TenantId
from src.presentation.controllers.permission_matrix import PermissionMatrixController

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())
NOW: Final = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)

MANAGE_POSITIONS: Final = PermissionFlag(code="can_manage_positions", category="Sistem")
#: Anti-fraud flag — `Mağaza_Meneceri`/`Satıcı` rollarında OLA BİLMƏZ (bölmə 3).
ISSUE_FINES: Final = PermissionFlag(code="can_issue_fines", category="Cərimə", is_anti_fraud=True)
#: Yalnız `Root` daşıya bilən hardlock flag-i.
ROOT_ONLY_FLAG: Final = PermissionFlag(
    code="can_manage_permissions", category="Sistem", hardlock=HardlockLevel.ROOT_ONLY
)


# --------------------------------------------------------------------------- #
# Saxta mühit — YALNIZ repo/audit; use case REALDIR
# --------------------------------------------------------------------------- #


class _Screen:
    theme = object()

    def __init__(self) -> None:
        self.roles: list[tuple[str, str, int]] = []
        self.matrix: tuple[str, list[Any]] | None = None
        self.errors: list[tuple[str, str]] = []
        self.selected: list[str] = []

    def set_roles(self, roles: list[tuple[str, str, int]]) -> None:
        self.roles = roles

    def set_matrix(self, role_name: str, groups: list[Any]) -> None:
        self.matrix = (role_name, groups)

    def select_role(self, key: str) -> None:
        self.selected.append(key)

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


class _Positions:
    def __init__(self, positions: list[Position]) -> None:
        self.items = {position.id: position for position in positions}
        self.saved: list[Position] = []

    def get(self, position_id: PositionId) -> Position | None:
        return self.items.get(position_id)

    def get_by_code(self, tenant_id: TenantId, code: str) -> Position | None:
        return next((p for p in self.items.values() if p.code == code), None)

    def list_for_tenant(self, tenant_id: TenantId) -> list[Position]:
        return list(self.items.values())

    def save(self, position: Position) -> None:
        self.saved.append(position)


class _Flags:
    def __init__(self, flags: list[PermissionFlag]) -> None:
        self.items = {flag.code: flag for flag in flags}

    def get(self, code: str) -> PermissionFlag | None:
        return self.items.get(code)

    def list_all(self) -> list[PermissionFlag]:
        return list(self.items.values())


class _Audit:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.records.append(kwargs)


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Cursor:
    """`session.uow.connection.execute(...)` müqaviləsinin minimal təkrarı."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _Connection:
    def __init__(self, flags: _Flags) -> None:
        self._flags = flags

    def execute(self, sql: str, params: Any = None) -> _Cursor:
        if "permission_flags" in sql:
            return _Cursor([{"code": code, "name_az": code} for code in self._flags.items])
        # `_employee_counts` sorğusu.
        return _Cursor([])


class _Uow:
    def __init__(self, flags: _Flags) -> None:
        self.connection = _Connection(flags)
        self._flags = flags

    def repository(self, name: str) -> Any:
        assert name == "permission_flags"
        return self._flags


class _Session:
    def __init__(self, use_case: PositionManagementUseCase, flags: _Flags) -> None:
        self.tenant_id = TENANT
        self.positions = use_case
        self.uow = _Uow(flags)
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Context:
    def __init__(self, session: _Session) -> None:
        self._session = session
        self.user_ids: list[Any] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        self.user_ids.append(user_id)
        yield self._session


# --------------------------------------------------------------------------- #
# Qurma köməkçiləri
# --------------------------------------------------------------------------- #


def _position(role: SystemRole, *, flags: list[PermissionFlag] | None = None) -> Position:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=role.value,
        name_az=role.value,
        priority=role.default_priority,
        tenant_id=TENANT,
        is_system=True,
        is_camera_type=role.is_camera_type,
    )
    for flag in flags or []:
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


def _build(
    *,
    actor_flags: list[PermissionFlag],
    target: Position,
    catalog: list[PermissionFlag],
    actor_role: SystemRole = SystemRole.CEO,
) -> tuple[PermissionMatrixController, _Session, _Positions]:
    actor_position = _position(actor_role, flags=actor_flags)
    actor = _employee(actor_position)

    positions = _Positions([actor_position, target])
    flags = _Flags(catalog)
    use_case = PositionManagementUseCase(
        positions=positions,  # type: ignore[arg-type]
        flags=flags,  # type: ignore[arg-type]
        audit=_Audit(),  # type: ignore[arg-type]
        clock=_Clock(),  # type: ignore[arg-type]
    )
    session = _Session(use_case, flags)
    controller = PermissionMatrixController(_Context(session), actor)  # type: ignore[arg-type]
    return (controller, session, positions)


# --------------------------------------------------------------------------- #
# GUARD testləri
# --------------------------------------------------------------------------- #


def test_self_escalation_is_blocked_and_explained() -> None:
    """Aktor ÖZÜNDƏ OLMAYAN flag-i rola verə bilməz (bölmə 3).

    Bu, ən aşkar hücum yoludur: "özümdə olmayan icazəni custom rola qoyum,
    sonra həmin rolu özümə təyin edim". Guard `_apply_flags`-dədir; kontroller
    onu təkrarlamır, yalnız istisnanı GÖSTƏRİR.
    """
    target = _position(SystemRole.HR_ADMIN)
    controller, session, positions = _build(
        # Aktorda `can_issue_fines` YOXDUR.
        actor_flags=[MANAGE_POSITIONS],
        target=target,
        catalog=[MANAGE_POSITIONS, ISSUE_FINES],
    )
    screen = _Screen()
    controller._roles = {target.code: target}

    controller._on_saved(screen, target.code, {"can_issue_fines": True})

    assert positions.saved == [], "Qadağan olunan flag YAZILMAMALIDIR"
    assert session.commits == 0, "Rədd edilmiş əməliyyat commit olunmamalıdır"
    assert screen.errors, "İstifadəçi səbəbi GÖRMƏLİDİR — səssiz udulma yoxdur"
    assert screen.errors[0][0] == "İcazələr yazılmadı"


def test_anti_fraud_separation_is_blocked() -> None:
    """`can_issue_fines` `Mağaza_Meneceri` rolunda ola bilməz (vəzifə ayrılığı).

    Aktorda flag VAR (yəni self-escalation qapısı keçilir) — bloklayan qayda
    məhz anti-fraud ayrılığıdır.
    """
    target = _position(SystemRole.STORE_MANAGER)
    controller, session, positions = _build(
        actor_flags=[MANAGE_POSITIONS, ISSUE_FINES],
        target=target,
        catalog=[MANAGE_POSITIONS, ISSUE_FINES],
    )
    screen = _Screen()
    controller._roles = {target.code: target}

    controller._on_saved(screen, target.code, {"can_issue_fines": True})

    assert positions.saved == []
    assert session.commits == 0
    assert screen.errors[0][0] == "İcazələr yazılmadı"


def test_hardlock_flag_cannot_be_granted_to_a_lower_role() -> None:
    """`ROOT_ONLY` hardlock — flag HR_Admin roluna verilə bilməz (bölmə 3).

    Aktor `Root`-dur, yəni flag ONDA VAR və self-escalation qapısı keçilir.
    Bloklayan yeganə qayda hardlock səviyyəsidir — məhz yoxlamaq istədiyimiz.
    """
    target = _position(SystemRole.HR_ADMIN)
    controller, session, positions = _build(
        actor_role=SystemRole.ROOT,
        actor_flags=[MANAGE_POSITIONS, ROOT_ONLY_FLAG],
        target=target,
        catalog=[MANAGE_POSITIONS, ROOT_ONLY_FLAG],
    )
    screen = _Screen()
    controller._roles = {target.code: target}

    controller._on_saved(screen, target.code, {"can_manage_permissions": True})

    assert positions.saved == []
    assert session.commits == 0
    assert screen.errors[0][0] == "İcazələr yazılmadı"


def test_permitted_change_is_written_and_committed() -> None:
    """İcazəli dəyişiklik BAŞ TUTUR — guard-lar hər şeyi bloklamır."""
    allowed = PermissionFlag(code="can_view_appeals", category="Cərimə")
    target = _position(SystemRole.HR_ADMIN)
    controller, session, positions = _build(
        actor_flags=[MANAGE_POSITIONS, allowed],
        target=target,
        catalog=[MANAGE_POSITIONS, allowed],
    )
    screen = _Screen()
    controller._roles = {target.code: target}

    controller._on_saved(screen, target.code, {"can_view_appeals": True})

    assert positions.saved, "İcazəli dəyişiklik yazılmalıdır"
    assert session.commits == 1
    assert "can_view_appeals" in positions.saved[0].granted_flags


def test_write_session_carries_the_actor_id() -> None:
    """Sessiya `user_id` ilə açılır — DB trigger-i `granted_by`-a bunu görür.

    `enforce_grantor_owns_flag()` qərarını `position_permissions.granted_by`
    sütununa görə verir və sütun `app.user_id`-dən doldurulur
    (`PostgresPositionRepository._sync_flags`). `user_id` ötürülməsəydi yazı
    DB qapısını "seed" kimi yan keçərdi.
    """
    allowed = PermissionFlag(code="can_view_appeals", category="Cərimə")
    target = _position(SystemRole.HR_ADMIN)
    controller, _session, _positions = _build(
        actor_flags=[MANAGE_POSITIONS, allowed],
        target=target,
        catalog=[MANAGE_POSITIONS, allowed],
    )
    context: Any = controller._context
    screen = _Screen()
    controller._roles = {target.code: target}

    controller._on_saved(screen, target.code, {"can_view_appeals": True})

    assert context.user_ids, "Sessiya ümumiyyətlə açılmayıb"
    assert all(user_id is not None for user_id in context.user_ids)


def test_refresh_shows_only_roles_the_actor_may_edit() -> None:
    """Siyahıda YALNIZ aktordan CİDDİ ŞƏKİLDƏ aşağı rollar görünür.

    ────────────────────────────────────────────────────────────────────────
    ƏVVƏL BU TEST ƏKSİNİ QORUYURDU
    ────────────────────────────────────────────────────────────────────────
    Köhnə iddia `[CEO, HR_ADMIN]` idi, yəni CEO ÖZ rolunu da siyahıda
    görürdü. İstifadəçi hesabatı bunun nəticəsini göstərdi: «CEO Root-un
    icazə matrisini dəyişə bilir». Yazma əslində bloklanırdı
    (`assert_may_be_edited_by`), lakin ekran sətri redaktə oluna bilən kimi
    göstərirdi — istifadəçi xanaları işarələyib «Yadda Saxla» basana qədər
    rədd cavabını görmürdü.

    İndi siyahı `Position.may_be_edited_by()`-dən keçir: aktorun ÖZ pilləsi
    (SEC-006 — bərabər pillə bloklanır) və ondan yuxarı olan `Root` sətri
    ümumiyyətlə görünmür. Bu, bölmə 3-ün «GÖRMƏK = SƏLAHİYYƏTİN OLMASI»
    prinsipidir.
    """
    target = _position(SystemRole.HR_ADMIN)
    controller, _session, _positions = _build(
        actor_flags=[MANAGE_POSITIONS],
        target=target,
        catalog=[MANAGE_POSITIONS],
    )
    screen = _Screen()

    controller.refresh(screen)

    codes = [row[0] for row in screen.roles]
    assert codes == [SystemRole.HR_ADMIN.value], "aktor toxuna bilmədiyi rolu görür"
    assert screen.selected == [SystemRole.HR_ADMIN.value]


def test_root_still_sees_every_role() -> None:
    """`Root` bərabər-pillə qaydasından AZADDIR (SEC-006 istisnası).

    Süzgəc onu da tutsaydı, təchizatçı öz rolunu redaktə edə bilməzdi və
    sistem ilk gündən kilidlənərdi.
    """
    target = _position(SystemRole.HR_ADMIN)
    controller, _session, _positions = _build(
        actor_flags=[MANAGE_POSITIONS],
        target=target,
        catalog=[MANAGE_POSITIONS],
        actor_role=SystemRole.ROOT,
    )
    screen = _Screen()

    controller.refresh(screen)

    codes = {row[0] for row in screen.roles}
    assert codes == {SystemRole.ROOT.value, SystemRole.HR_ADMIN.value}
