"""Toplu Əməliyyatlar (#29, kompas1.md Faza 5) — CSV işçi idxalı + mağaza şablonu.

──────────────────────────────────────────────────────────────────────────────
NƏ YOXLANILIR — VƏ NİYƏ MƏHZ BU
──────────────────────────────────────────────────────────────────────────────
  A. QIRMIZI XƏTT — iyerarxiyanı pozan sətir `create_employee()`-in ÖZ
     `AuthorizationError`-u ilə RƏDD EDİLİR; bu modul heç bir hierarxiya
     yoxlamasını TƏKRARLAMIR (bax `bulk_operations.py` başlığı).
  B. FLAG-SİZ AKTOR — `can_perform_bulk_operations` yoxdursa açıq istisna,
     həm önizləmə, həm idxal üçün.
  C. QİSMƏN İDXAL — 3 uğurlu + 2 uğursuz sətir → 3 işçi yaranır, hesabat
     dəqiq 2 xəta göstərir.
  D. CSV RİSKLƏRİ — boş fayl, yalnız-başlıq fayl, BOM-lu UTF-8, `;`/`,`
     ayırıcı, Windows sətir sonu, fayl-daxili dublikat, mövcud toqquşma,
     sütun sırası, əskik məcburi sütun, çox böyük fayl, şifrə sütunu.
  E. AUDİT İSTİSNA UDMUR — yekun `bulk_log.finish()`/`audit.record()`
     uğursuz olsa, İSTİSNA YUXARI ÖTÜRÜLÜR (udulmur), lakin ARTIQ YARADILMIŞ
     işçilər TOXUNULMUR (hər sətir öz tranzaksiyasında, bax modul başlığı).
  F. MAĞAZA ŞABLONU — mənbə mağaza DƏYİŞMİR, `config_snapshot` boş ola
     bilməz, tətbiq `StoreWriter.create()` vasitəsilə YENİ mağaza yaradır.

Sahtələr BURADA, YERLİ təyin olunub (`tests/fixtures/fakes.py`-a əlavə
edilmir) — `test_annual_leave.py`/`test_field_reports.py` ilə eyni
əsaslandırma: bu fayl paralel işləyən başqa fazaların sahtə dəstindən asılı
olmamalıdır.

`EmployeeRowCreator` sahtəsi YOXDUR — testlər ONUN ƏVƏZİNƏ REAL
`UserManagementUseCase.create_employee`-i (fakes-lə qurulmuş) işlədir, çünki
QIRMIZI XƏTT məhz bunun sətir-sətir ÇAĞIRILDIĞINI sübut etməlidir (bax A).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import pytest

from src.application.use_cases.bulk_operations import (
    BULK_OPERATIONS_FLAG,
    IMPORT_TYPE_EMPLOYEES,
    IMPORT_TYPE_STORE_TEMPLATE,
    REQUIRED_COLUMNS,
    BulkEmployeeImportUseCase,
    BulkImportFileError,
    BulkOperationsPermissionError,
    StoreTemplateNotFoundError,
    StoreTemplateUseCase,
    StoreTemplateValidationError,
)
from src.application.use_cases.first_run_setup import StoreDraft
from src.application.use_cases.user_management import EmployeeDraft, UserManagementUseCase
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.authorization import (
    AuthorizationError,
    HardlockLevel,
    PermissionFlag,
    RolePriority,
)
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    EmployeeId,
    PositionId,
    StoreId,
    StoreTemplateId,
    TenantId,
)
from src.domain.value_objects.store_templates import StoreTemplate

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
STORE = StoreId(uuid.uuid4())
NOW = datetime(2026, 8, 13, 9, 0, tzinfo=UTC)

#: `hardlock=DELEGABLE` — `migrations/038` ilə EYNİ: Root/CEO/Admin.
BULK_FLAG = PermissionFlag(
    code=BULK_OPERATIONS_FLAG, category="HR", hardlock=HardlockLevel.DELEGABLE
)
MANAGE_EMPLOYEES_FLAG = PermissionFlag(code="can_manage_employees", category="HR")


# --------------------------------------------------------------------------- #
# Yerli sahtələr
# --------------------------------------------------------------------------- #


@dataclass
class FakeClock:
    moment: datetime = NOW

    def now(self) -> datetime:
        return self.moment


class FakeLimits:
    """`SystemLimits` — verilməyən açar üçün `DEFAULT_LIMITS`-i qaytarır."""

    def __init__(self, overrides: dict[str, str] | None = None) -> None:
        self._values = {key.value: value for key, value in DEFAULT_LIMITS.items()}
        self._values.update(overrides or {})

    def set(self, key: SystemLimitKey, value: str) -> None:
        self._values[key.value] = value

    def get_int(self, tenant_id: TenantId, key: str, default: int) -> int:
        try:
            return int(self._values.get(key, str(default)))
        except (TypeError, ValueError):
            return default

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
        return self._values.get(key, default)

    def all_for(self, tenant_id: TenantId) -> dict[str, str]:
        return dict(self._values)


class RecordingAudit:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        #: `AuditTrail.record()`-un UĞURSUZLUĞUNU simulyasiya edir (CLAUDE.md
        #: §5: "audit yazısı istisna udmur" — bax test E).
        self.failure: Exception | None = None

    def record(self, **kwargs: Any) -> None:
        if self.failure is not None:
            raise self.failure
        self.entries.append(kwargs)

    def actions(self) -> list[str]:
        return [str(e["action"]) for e in self.entries]


class FakeEmployees:
    def __init__(self, employees: list[Employee] | None = None) -> None:
        self.items: dict[EmployeeId, Employee] = {e.id: e for e in employees or []}

    def get(self, employee_id: EmployeeId) -> Employee | None:
        return self.items.get(employee_id)

    def get_by_username(self, tenant_id: TenantId, username: Username) -> Employee | None:
        for employee in self.items.values():
            if (
                employee.tenant_id == tenant_id
                and employee.username is not None
                and str(employee.username) == str(username)
            ):
                return employee
        return None

    def save(self, employee: Employee) -> None:
        self.items[employee.id] = employee

    def count_active_with_flag(self, tenant_id: TenantId, flag_code: str) -> int:
        return sum(
            1
            for e in self.items.values()
            if e.tenant_id == tenant_id and e.is_active and e.has_permission(flag_code, now=NOW)
        )


class FakeCredentials:
    def __init__(self) -> None:
        self.passwords: dict[EmployeeId, str] = {}

    def set_password(
        self, employee_id: EmployeeId, *, raw_password: str, must_change: bool
    ) -> None:
        self.passwords[employee_id] = raw_password

    def set_pin(self, employee_id: EmployeeId, *, raw_pin: str) -> None:  # pragma: no cover
        pass

    def clear_pin_lockout(self, employee_id: EmployeeId) -> None:  # pragma: no cover
        pass


class FakePositions:
    def __init__(self, positions: list[Position]) -> None:
        self.by_code: dict[str, Position] = {p.code: p for p in positions}

    def get(self, position_id: PositionId) -> Position | None:
        for position in self.by_code.values():
            if position.id == position_id:
                return position
        return None

    def get_by_code(self, tenant_id: TenantId, code: str) -> Position | None:
        return self.by_code.get(code)

    def list_for_tenant(self, tenant_id: TenantId) -> list[Position]:
        return list(self.by_code.values())

    def save(self, position: Position) -> None:  # pragma: no cover
        self.by_code[position.code] = position


class FakeStores:
    """`StoreWriter` — `create()` + `get_id_by_code()`.

    `created` siyahısı MƏNBƏ MAĞAZANIN DƏYİŞMƏDİYİNİ sübut etmək üçündür:
    sinifdə "update" metodu ÜMUMİYYƏTLƏ YOXDUR — struktur olaraq mövcud bir
    mağaza sətrinə toxunmaq MÜMKÜN DEYİL.
    """

    def __init__(self) -> None:
        self.by_code: dict[str, StoreId] = {}
        self.created: list[dict[str, Any]] = []

    def create(
        self,
        *,
        store_id: StoreId,
        tenant_id: TenantId,
        code: str,
        name: str,
        brand: str,
        address: str,
    ) -> None:
        self.created.append(
            {
                "store_id": store_id,
                "tenant_id": tenant_id,
                "code": code,
                "name": name,
                "brand": brand,
                "address": address,
            }
        )
        self.by_code[code] = store_id

    def get_id_by_code(self, tenant_id: TenantId, code: str) -> StoreId | None:
        return self.by_code.get(code)

    def register(self, code: str, store_id: StoreId) -> None:
        """Test qurğusu — mövcud mağaza kodunu ƏVVƏLCƏDƏN qeyd edir."""
        self.by_code[code] = store_id


class FakeBulkLog:
    def __init__(self) -> None:
        self.started: list[dict[str, Any]] = []
        self.finished: list[dict[str, Any]] = []
        #: `finish()`-in UĞURSUZLUĞUNU simulyasiya edir (bax test E).
        self.finish_failure: Exception | None = None

    def start(self, **kwargs: Any) -> None:
        self.started.append(kwargs)

    def finish(self, **kwargs: Any) -> None:
        if self.finish_failure is not None:
            raise self.finish_failure
        self.finished.append(kwargs)

    def list_recent(self, tenant_id: TenantId, *, limit: int = 50) -> list[dict[str, object]]:
        return []


class FakeTemplates:
    def __init__(self) -> None:
        self.items: dict[StoreTemplateId, StoreTemplate] = {}

    def get(self, template_id: StoreTemplateId) -> StoreTemplate | None:
        return self.items.get(template_id)

    def list_for_tenant(
        self, tenant_id: TenantId, *, include_inactive: bool = False
    ) -> list[StoreTemplate]:
        return [t for t in self.items.values() if include_inactive or t.is_active]

    def save(self, tenant_id: TenantId, entry: StoreTemplate) -> None:
        assert entry.store_template_id is not None
        self.items[entry.store_template_id] = entry

    def deactivate(
        self, tenant_id: TenantId, template_id: StoreTemplateId, *, changed_by: EmployeeId
    ) -> None:
        existing = self.items[template_id]
        self.items[template_id] = replace(existing, is_active=False, deactivated_at=NOW)


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _position(
    code: str, priority: RolePriority, *, flags: tuple[PermissionFlag, ...] = ()
) -> Position:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=code,
        name_az=code.title(),
        priority=priority,
        is_system=True,
    )
    for flag in flags:
        position.grant(flag)
    return position


def _employee(position: Position, *, username: str, store_id: StoreId | None = None) -> Employee:
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Test",
        last_name="Actor",
        store_id=store_id,
        username=Username.parse(username),
        has_password=True,
    )


#: BULK + MANAGE_EMPLOYEES hər ikisi olan ADMIN aktoru — spesifikasiyanın
#: "YALNIZ Root/CEO/Admin" tələbinin ən aşağı pilləsi (DELEGABLE hardlock).
ADMIN_POSITION = _position("ADMIN", RolePriority.ADMIN, flags=(BULK_FLAG, MANAGE_EMPLOYEES_FLAG))
#: `can_manage_employees` VAR, `can_perform_bulk_operations` YOXDUR.
HR_ADMIN_NO_BULK_POSITION = _position(
    "HR_ADMIN", RolePriority.OPERATIONAL, flags=(MANAGE_EMPLOYEES_FLAG,)
)
SELLER_POSITION = _position("SATICI", RolePriority.STAFF)
ROOT_POSITION = _position("ROOT", RolePriority.ROOT)


def _csv_bytes(
    rows: list[dict[str, str]],
    *,
    columns: tuple[str, ...] = (*REQUIRED_COLUMNS, "store_code", "notification_email"),
    delimiter: str = ",",
    newline: str = "\n",
    bom: bool = False,
) -> bytes:
    lines = [delimiter.join(columns)]
    lines.extend(delimiter.join(row.get(col, "") for col in columns) for row in rows)
    text = newline.join(lines) + newline
    data = text.encode("utf-8")
    return (b"\xef\xbb\xbf" + data) if bom else data


@dataclass
class Harness:
    use_case: BulkEmployeeImportUseCase
    employees: FakeEmployees
    positions: FakePositions
    stores: FakeStores
    bulk_log: FakeBulkLog
    audit: RecordingAudit
    clock: FakeClock
    limits: FakeLimits
    users: UserManagementUseCase
    created_employees: list[EmployeeId] = field(default_factory=list)


def _build(
    *, positions: list[Position] | None = None, limits: dict[str, str] | None = None
) -> Harness:
    employees = FakeEmployees()
    credentials = FakeCredentials()
    audit = RecordingAudit()
    clock = FakeClock()
    fake_limits = FakeLimits(limits)
    users = UserManagementUseCase(
        employees=employees, credentials=credentials, audit=audit, clock=clock
    )

    def _create_row(
        *,
        tenant_id: TenantId,
        actor: Employee,
        employee_id: EmployeeId,
        draft: Any,
        initial_password: str,
    ) -> Employee:
        return users.create_employee(
            tenant_id=tenant_id,
            actor=actor,
            employee_id=employee_id,
            draft=draft,
            initial_password=initial_password,
        )

    position_list = positions or [ADMIN_POSITION, SELLER_POSITION, ROOT_POSITION]
    fake_positions = FakePositions(position_list)
    fake_stores = FakeStores()
    bulk_log = FakeBulkLog()

    from src.infrastructure.security.hashing import HashingService

    use_case = BulkEmployeeImportUseCase(
        employees=employees,
        positions=fake_positions,
        stores=fake_stores,
        create_employee_row=_create_row,
        hashing=HashingService(),
        bulk_log=bulk_log,
        audit=audit,
        clock=clock,
        limits=fake_limits,
    )
    return Harness(
        use_case=use_case,
        employees=employees,
        positions=fake_positions,
        stores=fake_stores,
        bulk_log=bulk_log,
        audit=audit,
        clock=clock,
        limits=fake_limits,
        users=users,
    )


# --------------------------------------------------------------------------- #
# B. Flag-siz aktor
# --------------------------------------------------------------------------- #


def test_actor_without_flag_cannot_preview() -> None:
    h = _build()
    actor = _employee(HR_ADMIN_NO_BULK_POSITION, username="hr1")
    with pytest.raises(BulkOperationsPermissionError):
        h.use_case.preview_csv(tenant_id=TENANT, actor=actor, csv_bytes=b"first_name\n")


def test_actor_without_flag_cannot_import() -> None:
    h = _build()
    actor = _employee(HR_ADMIN_NO_BULK_POSITION, username="hr2")
    with pytest.raises(BulkOperationsPermissionError):
        h.use_case.import_employees(
            tenant_id=TENANT, actor=actor, csv_bytes=b"first_name\n", file_ref=None
        )


# --------------------------------------------------------------------------- #
# D. CSV riskləri
# --------------------------------------------------------------------------- #


def test_empty_file_rejected() -> None:
    h = _build()
    actor = _employee(ADMIN_POSITION, username="admin_a")
    with pytest.raises(BulkImportFileError):
        h.use_case.preview_csv(tenant_id=TENANT, actor=actor, csv_bytes=b"")


def test_header_only_file_is_a_valid_empty_result() -> None:
    h = _build()
    actor = _employee(ADMIN_POSITION, username="admin_b")
    csv_bytes = _csv_bytes([])
    preview = h.use_case.preview_csv(tenant_id=TENANT, actor=actor, csv_bytes=csv_bytes)
    assert preview.total_data_rows == 0
    assert preview.valid_rows == ()
    assert preview.errors == ()

    report = h.use_case.import_employees(
        tenant_id=TENANT, actor=actor, csv_bytes=csv_bytes, file_ref=None
    )
    assert report.row_count == 0
    assert report.success_count == 0
    assert report.error_count == 0
    assert h.bulk_log.started[0]["row_count"] == 0
    assert h.bulk_log.finished[0]["success_count"] == 0


def test_bom_prefixed_utf8_is_decoded() -> None:
    h = _build()
    actor = _employee(ADMIN_POSITION, username="admin_c")
    csv_bytes = _csv_bytes(
        [
            {
                "first_name": "Aysel",
                "last_name": "Quliyeva",
                "position_code": "SATICI",
                "username": "aysel01",
            }
        ],
        bom=True,
    )
    preview = h.use_case.preview_csv(tenant_id=TENANT, actor=actor, csv_bytes=csv_bytes)
    assert preview.total_data_rows == 1
    assert len(preview.valid_rows) == 1


def test_semicolon_delimiter_is_detected() -> None:
    h = _build()
    actor = _employee(ADMIN_POSITION, username="admin_d")
    csv_bytes = _csv_bytes(
        [
            {
                "first_name": "Kamran",
                "last_name": "Aliyev",
                "position_code": "SATICI",
                "username": "kamran01",
            }
        ],
        delimiter=";",
    )
    preview = h.use_case.preview_csv(tenant_id=TENANT, actor=actor, csv_bytes=csv_bytes)
    assert preview.total_data_rows == 1
    assert len(preview.valid_rows) == 1
    assert preview.valid_rows[0].draft.first_name == "Kamran"


def test_windows_line_endings_are_handled() -> None:
    h = _build()
    actor = _employee(ADMIN_POSITION, username="admin_e")
    csv_bytes = _csv_bytes(
        [
            {
                "first_name": "Nigar",
                "last_name": "Hasanova",
                "position_code": "SATICI",
                "username": "nigar01",
            }
        ],
        newline="\r\n",
    )
    preview = h.use_case.preview_csv(tenant_id=TENANT, actor=actor, csv_bytes=csv_bytes)
    assert preview.total_data_rows == 1
    assert len(preview.valid_rows) == 1


def test_duplicate_username_within_file_is_rejected() -> None:
    h = _build()
    actor = _employee(ADMIN_POSITION, username="admin_f")
    csv_bytes = _csv_bytes(
        [
            {
                "first_name": "Ali",
                "last_name": "Ismayilov",
                "position_code": "SATICI",
                "username": "ali01",
            },
            {
                "first_name": "Ali2",
                "last_name": "Ismayilov2",
                "position_code": "SATICI",
                "username": "ALI01",
            },  # CITEXT — eyni sayılır
        ]
    )
    preview = h.use_case.preview_csv(tenant_id=TENANT, actor=actor, csv_bytes=csv_bytes)
    assert len(preview.valid_rows) == 1
    assert len(preview.errors) == 1
    assert preview.errors[0].row_number == 3  # başlıq=1, 1-ci sətir=2, 2-ci=3
    assert "dublikat" in preview.errors[0].message.lower()


def test_existing_employee_username_collision_is_rejected() -> None:
    existing = _employee(SELLER_POSITION, username="mevcud01")
    h = _build()
    h.employees.save(existing)
    actor = _employee(ADMIN_POSITION, username="admin_g")
    csv_bytes = _csv_bytes(
        [
            {
                "first_name": "Yeni",
                "last_name": "Isci",
                "position_code": "SATICI",
                "username": "mevcud01",
            }
        ]
    )
    preview = h.use_case.preview_csv(tenant_id=TENANT, actor=actor, csv_bytes=csv_bytes)
    assert not preview.valid_rows
    assert len(preview.errors) == 1
    assert "mövcuddur" in preview.errors[0].message.lower()


def test_column_reordering_does_not_matter() -> None:
    h = _build()
    actor = _employee(ADMIN_POSITION, username="admin_h")
    csv_bytes = _csv_bytes(
        [
            {
                "first_name": "Tural",
                "last_name": "Nabiyev",
                "position_code": "SATICI",
                "username": "tural01",
            }
        ],
        columns=("username", "position_code", "last_name", "first_name"),
    )
    preview = h.use_case.preview_csv(tenant_id=TENANT, actor=actor, csv_bytes=csv_bytes)
    assert len(preview.valid_rows) == 1
    assert preview.valid_rows[0].draft.first_name == "Tural"


def test_missing_required_column_rejects_whole_file() -> None:
    h = _build()
    actor = _employee(ADMIN_POSITION, username="admin_i")
    csv_bytes = _csv_bytes(
        [{"first_name": "X", "last_name": "Y", "username": "xy01"}],
        columns=("first_name", "last_name", "username"),  # `position_code` əskikdir
    )
    with pytest.raises(BulkImportFileError):
        h.use_case.preview_csv(tenant_id=TENANT, actor=actor, csv_bytes=csv_bytes)


@pytest.mark.parametrize("column", ["password", "pin", "temp_password", "PIN_CODE"])
def test_password_or_pin_column_rejects_whole_file(column: str) -> None:
    h = _build()
    actor = _employee(ADMIN_POSITION, username="admin_j")
    csv_bytes = _csv_bytes(
        [
            {
                "first_name": "X",
                "last_name": "Y",
                "position_code": "SATICI",
                "username": "xy02",
                column: "12345",
            }
        ],
        columns=(*REQUIRED_COLUMNS, column),
    )
    with pytest.raises(BulkImportFileError, match=r"şifrə|PIN"):
        h.use_case.preview_csv(tenant_id=TENANT, actor=actor, csv_bytes=csv_bytes)


def test_file_exceeding_max_rows_is_rejected() -> None:
    h = _build(limits={SystemLimitKey.BULK_IMPORT_MAX_ROWS.value: "2"})
    actor = _employee(ADMIN_POSITION, username="admin_k")
    rows = [
        {"first_name": f"A{i}", "last_name": "B", "position_code": "SATICI", "username": f"user{i}"}
        for i in range(3)
    ]
    csv_bytes = _csv_bytes(rows)
    with pytest.raises(BulkImportFileError, match="tavan"):
        h.use_case.preview_csv(tenant_id=TENANT, actor=actor, csv_bytes=csv_bytes)
    # Heç bir sətir emal edilməyib — fayl SƏVİYYƏSİNDƏ rədd olunub.
    assert not h.employees.items


# --------------------------------------------------------------------------- #
# A. QIRMIZI XƏTT — iyerarxiya
# --------------------------------------------------------------------------- #


def test_hierarchy_violation_rejects_row_via_create_employee_guard() -> None:
    """Admin özündən yüksək (ROOT) rol təyin edə bilməz — `create_employee`-in ÖZ qapısı."""
    h = _build()
    actor = _employee(ADMIN_POSITION, username="admin_l")
    csv_bytes = _csv_bytes(
        [
            {
                "first_name": "Sahibkar",
                "last_name": "Boss",
                "position_code": "ROOT",
                "username": "boss01",
            }
        ]
    )
    report = h.use_case.import_employees(
        tenant_id=TENANT, actor=actor, csv_bytes=csv_bytes, file_ref=None
    )
    assert report.success_count == 0
    assert report.error_count == 1
    assert report.row_count == 1
    assert not h.employees.items  # heç bir işçi yaranmayıb
    # `AuthorizationError.user_message`-in ÖZÜ sətir mesajında görünür.
    assert report.errors[0].row_number == 2


def test_create_employee_guard_actually_fires_directly() -> None:
    """Eyni ssenari BİRBAŞA `create_employee()` çağırışında — QIRMIZI XƏTT-in sübutu."""
    h = _build()
    actor = _employee(ADMIN_POSITION, username="admin_m")
    with pytest.raises(AuthorizationError):
        h.users.create_employee(
            tenant_id=TENANT,
            actor=actor,
            employee_id=EmployeeId(uuid.uuid4()),
            draft=EmployeeDraft(first_name="X", last_name="Y", position=ROOT_POSITION),
            initial_password="Str0ng!Passw0rd",
        )


# --------------------------------------------------------------------------- #
# C. Qismən idxal
# --------------------------------------------------------------------------- #


def test_partial_import_three_success_two_errors() -> None:
    h = _build()
    actor = _employee(ADMIN_POSITION, username="admin_n")
    rows = [
        {"first_name": "Aygun", "last_name": "V", "position_code": "SATICI", "username": "aygun1"},
        {"first_name": "Vusal", "last_name": "V", "position_code": "SATICI", "username": "vusal1"},
        {"first_name": "Elvin", "last_name": "V", "position_code": "SATICI", "username": "elvin1"},
        # Uğursuz #1 — naməlum rol.
        {"first_name": "Bad", "last_name": "Role", "position_code": "NAMELUM", "username": "bad1"},
        # Uğursuz #2 — boş məcburi sahə (last_name boşdur).
        {"first_name": "Bad2", "last_name": "", "position_code": "SATICI", "username": "bad2"},
    ]
    csv_bytes = _csv_bytes(rows)
    report = h.use_case.import_employees(
        tenant_id=TENANT, actor=actor, csv_bytes=csv_bytes, file_ref="işçilər.csv"
    )
    assert report.row_count == 5
    assert report.success_count == 3
    assert report.error_count == 2
    assert len(h.employees.items) == 3
    created_usernames = {str(e.username) for e in h.employees.items.values()}
    assert created_usernames == {"aygun1", "vusal1", "elvin1"}
    # Uğurlu sətirlərin hər biri MÜVƏQQƏTİ ŞİFRƏ ilə qaytarılır.
    assert len(report.created) == 3
    assert all(c.temporary_password for c in report.created)
    # `bulk_import_log` rəqəmləri tam uzlaşır.
    assert h.bulk_log.started[0]["row_count"] == 5
    assert h.bulk_log.started[0]["import_type"] == IMPORT_TYPE_EMPLOYEES
    assert h.bulk_log.finished[0]["success_count"] == 3
    assert h.bulk_log.finished[0]["error_count"] == 2
    assert h.bulk_log.finished[0]["error_summary"] is not None
    # ƏMƏLİYYAT səviyyəli AQREQAT audit sətri — 5 YOX, BİR sətir.
    aggregate = [e for e in h.audit.entries if e["action"] == "BULK_EMPLOYEE_IMPORT_COMPLETED"]
    assert len(aggregate) == 1
    assert aggregate[0]["after_state"]["success_count"] == 3
    # HƏR uğurlu işçinin FƏRDİ `EMPLOYEE_CREATED` audit sətri DƏ var
    # (`create_employee()`-in daxili yazısı) — 3 ədəd.
    individual = [e for e in h.audit.entries if e["action"] == "EMPLOYEE_CREATED"]
    assert len(individual) == 3


def test_temporary_passwords_are_never_written_to_audit_or_log() -> None:
    h = _build()
    actor = _employee(ADMIN_POSITION, username="admin_o")
    csv_bytes = _csv_bytes(
        [
            {
                "first_name": "Sirli",
                "last_name": "Sifre",
                "position_code": "SATICI",
                "username": "sirli01",
            }
        ]
    )
    report = h.use_case.import_employees(
        tenant_id=TENANT, actor=actor, csv_bytes=csv_bytes, file_ref=None
    )
    password = report.created[0].temporary_password
    assert password not in repr(h.audit.entries)
    assert password not in repr(h.bulk_log.started)
    assert password not in repr(h.bulk_log.finished)


# --------------------------------------------------------------------------- #
# E. Audit istisna udmur / yarımçıq idxal
# --------------------------------------------------------------------------- #


def test_bulk_log_finish_failure_propagates_but_keeps_created_rows() -> None:
    h = _build()
    h.bulk_log.finish_failure = RuntimeError("DB bağlantısı qırıldı")
    actor = _employee(ADMIN_POSITION, username="admin_p")
    csv_bytes = _csv_bytes(
        [
            {
                "first_name": "Sağlam",
                "last_name": "Qeyd",
                "position_code": "SATICI",
                "username": "saglam01",
            }
        ]
    )
    with pytest.raises(RuntimeError, match="bağlantısı"):
        h.use_case.import_employees(
            tenant_id=TENANT, actor=actor, csv_bytes=csv_bytes, file_ref=None
        )
    # Sətir ARTIQ ÖZ tranzaksiyasında yaradılıb — yekun jurnal yazısının
    # uğursuzluğu ONU geri qaytarmır.
    assert len(h.employees.items) == 1
    # `bulk_import_log.start()` isə artıq yazılıb (əməliyyatın əvvəlində) —
    # `finished_at = NULL` qalır (bu sahtədə: `finished` siyahısı boşdur).
    assert len(h.bulk_log.started) == 1
    assert not h.bulk_log.finished


def test_aggregate_audit_failure_propagates_but_keeps_created_rows() -> None:
    h = _build()
    actor = _employee(ADMIN_POSITION, username="admin_q")
    csv_bytes = _csv_bytes(
        [
            {
                "first_name": "Toxunulmaz",
                "last_name": "Qeyd",
                "position_code": "SATICI",
                "username": "toxunulmaz01",
            }
        ]
    )

    # Uğurlu sətir ÜÇÜN audit sərbəst yazsın, YALNIZ İKİNCİ (aqreqat) çağırış
    # uğursuz olsun — `RecordingAudit.failure` HƏR çağırışı əngəlləyər, ona
    # görə burada YEKUN sətirdən DƏRHAL ƏVVƏL simulyasiya edilir.
    real_record = h.audit.record
    calls: list[str] = []

    def _flaky_record(**kwargs: Any) -> None:
        calls.append(str(kwargs["action"]))
        if kwargs["action"] == "BULK_EMPLOYEE_IMPORT_COMPLETED":
            raise RuntimeError("audit yazısı uğursuz oldu")
        real_record(**kwargs)

    h.audit.record = _flaky_record  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="audit yazısı"):
        h.use_case.import_employees(
            tenant_id=TENANT, actor=actor, csv_bytes=csv_bytes, file_ref=None
        )
    assert len(h.employees.items) == 1
    assert "EMPLOYEE_CREATED" in calls
    assert "BULK_EMPLOYEE_IMPORT_COMPLETED" in calls
    # `bulk_log.finish()` İSƏ ÇAĞIRILIB (audit-dən ƏVVƏL) — lakin bu iki
    # yazı EYNİ tranzaksiyada olmalı olduğu üçün (bax modul başlığı),
    # REAL DB-də audit uğursuzluğu `finish()`-in commit-ini DƏ geri
    # qaytarardı. Bu sahtədə hər ikisi ayrı obyektdir, ona görə YALNIZ
    # sıralanışı təsdiqləyirik.
    assert h.bulk_log.finished


# --------------------------------------------------------------------------- #
# F. Mağaza şablonu
# --------------------------------------------------------------------------- #


def _template_harness() -> tuple[
    StoreTemplateUseCase, FakeStores, FakeBulkLog, RecordingAudit, FakeTemplates
]:
    templates = FakeTemplates()
    stores = FakeStores()
    bulk_log = FakeBulkLog()
    audit = RecordingAudit()
    clock = FakeClock()
    use_case = StoreTemplateUseCase(
        templates=templates, stores=stores, bulk_log=bulk_log, audit=audit, clock=clock
    )
    return use_case, stores, bulk_log, audit, templates


def test_capture_does_not_mutate_source_store() -> None:
    use_case, stores, _bulk_log, _audit, _templates = _template_harness()
    actor = _employee(ADMIN_POSITION, username="admin_r")
    source_id = StoreId(uuid.uuid4())
    stores.register("SRC-01", source_id)

    template = use_case.capture(
        tenant_id=TENANT,
        actor=actor,
        name="Bayraqdar Mağaza Şablonu",
        source_store_id=source_id,
        config_snapshot={"work_modes": ["08:00-17:00"], "position_roster": {"SATICI": 4}},
    )

    assert template.based_on_store_id == source_id
    # `FakeStores`-un `create()`-dən BAŞQA yazma metodu YOXDUR — struktur
    # olaraq mənbə mağazaya TOXUNULA BİLMƏZ. Bu, onu SÜBUT edir:
    assert stores.created == []


def test_capture_rejects_empty_snapshot() -> None:
    use_case, _stores, _bulk_log, _audit, _templates = _template_harness()
    actor = _employee(ADMIN_POSITION, username="admin_s")
    with pytest.raises(StoreTemplateValidationError):
        use_case.capture(
            tenant_id=TENANT, actor=actor, name="Boş", source_store_id=None, config_snapshot={}
        )


def test_capture_requires_flag() -> None:
    use_case, _stores, _bulk_log, _audit, _templates = _template_harness()
    actor = _employee(HR_ADMIN_NO_BULK_POSITION, username="hr3")
    with pytest.raises(BulkOperationsPermissionError):
        use_case.capture(
            tenant_id=TENANT,
            actor=actor,
            name="Şablon",
            source_store_id=None,
            config_snapshot={"a": 1},
        )


def test_apply_creates_new_store_and_does_not_touch_source() -> None:
    use_case, stores, bulk_log, audit, _templates = _template_harness()
    actor = _employee(ADMIN_POSITION, username="admin_t")
    source_id = StoreId(uuid.uuid4())
    stores.register("SRC-02", source_id)

    template = use_case.capture(
        tenant_id=TENANT,
        actor=actor,
        name="Flaqman Şablonu",
        source_store_id=source_id,
        config_snapshot={"position_roster": {"SATICI": 3, "MAGAZA_MENECERI": 1}},
    )

    result = use_case.apply(
        tenant_id=TENANT,
        actor=actor,
        template_id=template.store_template_id,  # type: ignore[arg-type]
        new_store=StoreDraft(code="NEW-01", name="Yeni Filial", brand="Bellona"),
    )

    assert len(stores.created) == 1
    assert stores.created[0]["code"] == "NEW-01"
    assert result.new_store_id == stores.created[0]["store_id"]
    assert result.template_name == "Flaqman Şablonu"
    # Mənbə mağaza (SRC-02) HƏLƏ DƏ yalnız `register()` ilə qeydə alınıb —
    # `create()` YALNIZ yeni mağaza üçün çağırılıb.
    assert all(row["code"] != "SRC-02" for row in stores.created)

    assert bulk_log.started[0]["import_type"] == IMPORT_TYPE_STORE_TEMPLATE
    assert bulk_log.started[0]["row_count"] == 1
    assert bulk_log.finished[0]["success_count"] == 1
    applied = [e for e in audit.entries if e["action"] == "STORE_TEMPLATE_APPLIED"]
    assert len(applied) == 1
    assert applied[0]["after_state"]["new_store_code"] == "NEW-01"


def test_apply_unknown_template_raises() -> None:
    use_case, _stores, _bulk_log, _audit, _templates = _template_harness()
    actor = _employee(ADMIN_POSITION, username="admin_u")
    with pytest.raises(StoreTemplateNotFoundError):
        use_case.apply(
            tenant_id=TENANT,
            actor=actor,
            template_id=StoreTemplateId(uuid.uuid4()),
            new_store=StoreDraft(code="X", name="X", brand="X"),
        )


def test_deactivate_hides_template_from_default_listing() -> None:
    use_case, _stores, _bulk_log, _audit, _templates = _template_harness()
    actor = _employee(ADMIN_POSITION, username="admin_v")
    template = use_case.capture(
        tenant_id=TENANT,
        actor=actor,
        name="Silinəcək Şablon",
        source_store_id=None,
        config_snapshot={"a": 1},
    )
    assert template.store_template_id is not None

    active_before = use_case.list_templates(tenant_id=TENANT, actor=actor)
    assert any(t.store_template_id == template.store_template_id for t in active_before)

    use_case.deactivate(tenant_id=TENANT, actor=actor, template_id=template.store_template_id)

    active_after = use_case.list_templates(tenant_id=TENANT, actor=actor)
    assert all(t.store_template_id != template.store_template_id for t in active_after)

    all_including_inactive = use_case.list_templates(
        tenant_id=TENANT, actor=actor, include_inactive=True
    )
    match = next(
        t for t in all_including_inactive if t.store_template_id == template.store_template_id
    )
    assert match.is_active is False
    assert match.deactivated_at is not None


def test_captured_at_is_stamped_into_snapshot() -> None:
    use_case, _stores, _bulk_log, _audit, _templates = _template_harness()
    actor = _employee(ADMIN_POSITION, username="admin_w")
    template = use_case.capture(
        tenant_id=TENANT,
        actor=actor,
        name="Zaman Möhürü",
        source_store_id=None,
        config_snapshot={"work_modes": ["09:00-18:00"]},
    )
    assert "captured_at" in template.config_snapshot
    assert template.config_snapshot["work_modes"] == ["09:00-18:00"]


def test_store_template_does_not_migrate_employees_or_fine_history() -> None:
    """`config_snapshot` YALNIZ çağıranın verdiyi ayarları saxlayır.

    Bu test "hər şey köçdü" gözləntisinin YANLIŞ olduğunu sübut edir: işçi
    siyahısı və ya cərimə tarixçəsi üçün BURADA HEÇ BİR PORT/ARQUMENT YOXDUR
    — `capture()` imzasına baxmaq kifayətdir (`employees=`/`fines=`
    parametri yoxdur), ona görə struktur olaraq köçürülə BİLMƏZLƏR.
    """
    import inspect

    from src.application.use_cases.bulk_operations import StoreTemplateUseCase as _Cls

    signature = inspect.signature(_Cls.capture)
    assert "employees" not in signature.parameters
    assert "fines" not in signature.parameters
