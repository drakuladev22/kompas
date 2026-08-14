"""ROL-FLAG yolunda Strict Hierarchy Guard + mütləq `ROOT_ONLY` qoruması.

──────────────────────────────────────────────────────────────────────────────
BU TESTLƏR HANSI QÜSURU TUTUR
──────────────────────────────────────────────────────────────────────────────
Anti-fraud auditi `set_role_flags()`-də üç qapı tapdı — `can_manage_positions`,
Self-Escalation Guard və hardlock/anti-fraud — və HEÇ BİRİ aktorun pilləsini
hədəf ROLUN pilləsi ilə müqayisə etmirdi. `Position.revoke()` isə sadəcə
`discard()` idi.

Nəticə praktikada belə oxunurdu: `can_manage_positions` sahibi (defolt `Root`
VƏ `CEO`) `Root` rolundan `can_manage_system_limits` flag-ini ÇIXARA bilərdi.
Bu, adi səlahiyyət pozuntusu deyil — geri qaytarmaq üçün lazım olan flag məhz
çıxarılan flag olduğuna görə əməliyyat GERİ DÖNMƏZDİR.

Aşağıdakı testlər hər iki qatı ayrıca yoxlayır (use case VƏ entity), çünki
düzəliş yalnız birində olsaydı ekranı yan keçən kod digərindən keçərdi. Sonuncu
bölmə isə qaydanın DB yarısını — miqrasiya 046-dakı trigger-i — mətndən
təsdiqləyir (naxış: `test_db_guard_parity.py`).

MÜSBƏT HALLAR QƏSDƏN VAR: qorumanın "hər şeyi bloklamaq" olmadığını sübut edən
test olmasa, düzəliş sadəcə funksiyanı söndürməkdən fərqlənməzdi.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest

from src.application.use_cases.position_management import (
    PositionManagementUseCase,
)
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import (
    AuthorizationError,
    HardlockLevel,
    PermissionFlag,
    RolePriority,
    SystemRole,
)
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import EmployeeId, PositionId, TenantId
from src.shared.logger import LogChannel
from tests.fixtures.fakes import FakeClock, RecordingAudit

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())
NOW: Final = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA_FILE: Final = PROJECT_ROOT / "database" / "schema.sql"
MIGRATIONS_DIR: Final = PROJECT_ROOT / "database" / "migrations"
MIGRATION_046: Final = "046_position_flag_hierarchy_guard.sql"

HIERARCHY_FUNCTION: Final = "enforce_position_flag_hierarchy"
POSITION_TABLE: Final = "position_permissions"

# --------------------------------------------------------------------------- #
# Kataloq — hardlock səviyyələri `permission_flags` cədvəlindəki dəyərlərdir
# --------------------------------------------------------------------------- #

MANAGE_POSITIONS: Final = PermissionFlag(
    code="can_manage_positions", category="Sistem", hardlock=HardlockLevel.ROOT_CEO
)
#: `hardlock_level = 1` — dörd `ROOT_ONLY` flag-indən biri (schema.sql §22).
SYSTEM_LIMITS: Final = PermissionFlag(
    code="can_manage_system_limits", category="Sistem", hardlock=HardlockLevel.ROOT_ONLY
)
EXPORT: Final = PermissionFlag(code="can_export_reports", category="Hesabat")

CATALOG: Final = {
    MANAGE_POSITIONS.code: MANAGE_POSITIONS,
    SYSTEM_LIMITS.code: SYSTEM_LIMITS,
    EXPORT.code: EXPORT,
}


# --------------------------------------------------------------------------- #
# Sahtələr — YALNIZ repo-lar; use case REALDIR
# --------------------------------------------------------------------------- #


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
        self.items[position.id] = position
        self.saved.append(position)


class _Flags:
    def get(self, code: str) -> PermissionFlag | None:
        return CATALOG.get(code)

    def list_all(self) -> list[PermissionFlag]:
        return list(CATALOG.values())

    def create(self, flag: PermissionFlag, *, created_by: EmployeeId) -> None:
        CATALOG[flag.code] = flag


def _position(
    code: str,
    priority: RolePriority,
    *,
    flags: tuple[PermissionFlag, ...] = (),
    is_system: bool = True,
) -> Position:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=code,
        name_az=code.title(),
        priority=priority,
        tenant_id=TENANT,
        is_system=is_system,
    )
    for flag in flags:
        position.grant(flag)
    return position


def _employee(position: Position) -> Employee:
    """Aktoru rolun MÜSTƏQİL nüsxəsi ilə qurur.

    İstehsalatda aktor və redaktə olunan rol AYRI sorğularla oxunur, yəni iki
    fərqli obyektdir (`mappers.position_from_row` hər dəfə yenisini qurur).
    Testdə eyni nüsxəni paylaşsaydıq, `set_role_flags`-in "əvvəlcə hamısını
    geri al" addımı aktorun ÖZ səlahiyyətini də silərdi və test istehsalatda
    mövcud olmayan vəziyyəti yoxlayardı — `Root` öz rolunu redaktə edən kimi
    "səlahiyyətin yoxdur" xətası alardıq.
    """
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=_clone(position),
        first_name="T",
        last_name=position.code,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )


def _clone(position: Position) -> Position:
    clone = Position(
        position_id=position.id,
        code=position.code,
        name_az=position.name_az,
        priority=position.priority,
        tenant_id=position.tenant_id,
        is_system=position.is_system,
        is_camera_type=position.is_camera_type,
    )
    for code in sorted(position.granted_flags):
        clone.grant(CATALOG[code])
    return clone


def _use_case(positions: _Positions) -> tuple[PositionManagementUseCase, RecordingAudit]:
    audit = RecordingAudit()
    use_case = PositionManagementUseCase(
        positions=positions,  # type: ignore[arg-type]
        flags=_Flags(),  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=FakeClock(NOW),  # type: ignore[arg-type]
    )
    return use_case, audit


def _root_role() -> Position:
    """`Root` rolu — sistemin ən həssas flag-ini məhz o daşıyır."""
    return _position(
        SystemRole.ROOT.value,
        RolePriority.EXECUTIVE,
        flags=(MANAGE_POSITIONS, SYSTEM_LIMITS),
    )


def _ceo_role() -> Position:
    return _position(SystemRole.CEO.value, RolePriority.EXECUTIVE, flags=(MANAGE_POSITIONS,))


# --------------------------------------------------------------------------- #
# 1. TƏTBİQ QATI — CEO `Root` rolunun flag dəstinə toxuna bilməz
# --------------------------------------------------------------------------- #


def test_ceo_cannot_strip_a_root_only_flag_from_the_root_role() -> None:
    """AUDİTİN ƏSAS SSENARİSİ: CEO `Root`-dan `can_manage_system_limits`-i alır.

    `set_role_flags` flag dəstini TAM əvəzləyir: göndərilməyən hər flag geri
    alınır. Yəni hücum "boş dəst göndər" qədər sadədir və heç bir qadağan
    olunmuş flag VERİLMİR — məhz buna görə köhnə üç qapının heç biri işə
    düşmürdü.
    """
    root_role = _root_role()
    ceo_role = _ceo_role()
    positions = _Positions([root_role, ceo_role])
    use_case, audit = _use_case(positions)

    with pytest.raises(AuthorizationError, match="STRICT HIERARCHY GUARD"):
        use_case.set_role_flags(
            tenant_id=TENANT,
            actor=_employee(ceo_role),
            position_id=root_role.id,
            flag_codes=(),
        )

    assert root_role.has_flag(SYSTEM_LIMITS.code), "Flag rolda QALMALIDIR"
    assert positions.saved == [], "Rədd edilmiş əməliyyat yazılmamalıdır"
    assert audit.actions() == [], "Baş tutmayan dəyişiklik audit-ə düşməməlidir"


def test_ceo_cannot_edit_a_role_at_its_own_level() -> None:
    """SEC-006: bərabər pillə DƏ bloklanır — yalnız `Root` istisnadır.

    Bir CEO digər EXECUTIVE pilləli rolun səlahiyyətlərini sükutla dəyişə
    bilsəydi, "eyni pillədəki istifadəçilərin icazələrinə HEÇ VAXT müdaxilə
    edə bilməz" qaydası (bölmə 3) rol yolundan yan keçilərdi.
    """
    peer_role = _position("BÖLGƏ_RƏHBƏRİ", RolePriority.EXECUTIVE, flags=(EXPORT,), is_system=False)
    ceo_role = _ceo_role()
    ceo_role.grant(EXPORT)
    positions = _Positions([peer_role, ceo_role])
    use_case, audit = _use_case(positions)

    with pytest.raises(AuthorizationError, match="STRICT HIERARCHY GUARD"):
        use_case.set_role_flags(
            tenant_id=TENANT,
            actor=_employee(ceo_role),
            position_id=peer_role.id,
            flag_codes=(EXPORT.code,),
        )

    assert positions.saved == []
    assert audit.actions() == []


def test_priority_zero_custom_role_does_not_inherit_the_root_exemption() -> None:
    """SEC-006 istisnası KODA bağlıdır, prioritetə yox.

    Əks halda qadağa bir addımla yan keçilərdi: "özümə prioritet 0-lı custom
    rol yaradım, sonra `Root` roluna toxunum". `effective_system_role` məhz
    buna görə yalnız kodu `ROOT` olanı `ROOT` sayır.
    """
    fake_root = _position("KÖLGƏ_ROOT", RolePriority.EXECUTIVE, is_system=False)
    fake_root.grant(MANAGE_POSITIONS)
    root_role = _root_role()
    positions = _Positions([fake_root, root_role])
    use_case, _audit = _use_case(positions)

    with pytest.raises(AuthorizationError, match="STRICT HIERARCHY GUARD"):
        use_case.set_role_flags(
            tenant_id=TENANT,
            actor=_employee(fake_root),
            position_id=root_role.id,
            flag_codes=(),
        )

    assert root_role.has_flag(SYSTEM_LIMITS.code)


# --------------------------------------------------------------------------- #
# 2. ENTITY QATI — `Position.revoke()` özü də bağlıdır
# --------------------------------------------------------------------------- #


def test_direct_revoke_from_a_higher_role_is_refused() -> None:
    """Use case yan keçilsə belə entity qapını bağlı saxlayır.

    Qayda İKİ yerdədir (CLAUDE.md §5) və bu test məhz ikinci yeri yoxlayır:
    `revoke()` əvvəllər sadəcə `discard()` idi.
    """
    root_role = _root_role()
    ceo_role = _ceo_role()

    with pytest.raises(AuthorizationError, match="STRICT HIERARCHY GUARD"):
        root_role.revoke(SYSTEM_LIMITS, actor_position=ceo_role)

    assert root_role.has_flag(SYSTEM_LIMITS.code)


def test_revoke_without_an_actor_is_fail_closed() -> None:
    """`actor_position` defoltu "qorumasız keç" DEYİL.

    Parametr sonradan əlavə olunub; unudulmuş bir çağırış nöqtəsi sükutla köhnə
    davranışa qayıtsaydı, düzəliş heç nə dəyişməzdi.
    """
    root_role = _root_role()

    with pytest.raises(AuthorizationError, match="AKTOR KONTEKSTİ YOXDUR"):
        root_role.revoke(SYSTEM_LIMITS)

    assert root_role.has_flag(SYSTEM_LIMITS.code)


def test_root_only_flag_cannot_be_touched_by_a_non_root_actor() -> None:
    """MÜTLƏQ YOXLAMA: iyerarxiya keçsə BELƏ `ROOT_ONLY` flag CEO-ya bağlıdır.

    Hədəf rol (`HR_Admin`) CEO-dan ciddi şəkildə aşağıdadır, yəni Strict
    Hierarchy Guard bu yazını BURAXARDI. `ROOT_ONLY` yoxlaması ondan AYRIDIR
    və məhz buna görə ayrıca test edilir.
    """
    hr_role = _position(SystemRole.HR_ADMIN.value, RolePriority.OPERATIONAL)
    ceo_role = _ceo_role()

    with pytest.raises(AuthorizationError, match="YALNIZ Root toxuna bilər"):
        hr_role.assert_root_only_flag_allowed(SYSTEM_LIMITS, actor_position=ceo_role)


def test_root_only_flag_cannot_be_granted_to_another_role_even_by_root() -> None:
    """`ROOT_ONLY` flag YALNIZ `Root` rolunda yaşayır — `Root` özü də köçürə bilmir."""
    hr_role = _position(SystemRole.HR_ADMIN.value, RolePriority.OPERATIONAL)
    root_role = _root_role()
    positions = _Positions([hr_role, root_role])
    use_case, audit = _use_case(positions)

    with pytest.raises(AuthorizationError, match="yalnız Root rolunda ola bilər"):
        use_case.set_role_flags(
            tenant_id=TENANT,
            actor=_employee(root_role),
            position_id=hr_role.id,
            flag_codes=(SYSTEM_LIMITS.code,),
        )

    assert not hr_role.has_flag(SYSTEM_LIMITS.code)
    assert positions.saved == []
    assert audit.actions() == []


def test_root_touching_a_root_only_flag_leaves_a_security_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Root özü etsə belə iz qalır — insidentdə ilk soruşulan sual budur."""
    root_role = _root_role()
    positions = _Positions([root_role])
    use_case, audit = _use_case(positions)

    with caplog.at_level(logging.WARNING, logger=LogChannel.SECURITY.logger_name):
        use_case.set_role_flags(
            tenant_id=TENANT,
            actor=_employee(root_role),
            position_id=root_role.id,
            flag_codes=(MANAGE_POSITIONS.code, SYSTEM_LIMITS.code),
        )

    assert "ROOT_ONLY_FLAG_TOUCHED" in caplog.text
    assert "POSITION_FLAGS_UPDATED" in audit.actions()


# --------------------------------------------------------------------------- #
# 3. REGRESSİYA OLMADIĞININ SÜBUTU — qanuni axın SINMAMALIDIR
# --------------------------------------------------------------------------- #


def test_ceo_can_still_edit_a_strictly_lower_role() -> None:
    """CİDDİ ŞƏKİLDƏ aşağı pillə — həm vermək, həm geri almaq İŞLƏYİR.

    Guard-ın "hər şeyi bloklamadığını" göstərən test. Geri alma yolu ayrıca
    vacibdir: `set_role_flags` əvvəlcə BÜTÜN flag-ləri `revoke()` edir, yəni
    yeni yoxlama səhv qurulsaydı ADİ redaktə də çökərdi.
    """
    hr_role = _position(SystemRole.HR_ADMIN.value, RolePriority.OPERATIONAL, flags=(EXPORT,))
    ceo_role = _ceo_role()
    ceo_role.grant(EXPORT)
    positions = _Positions([hr_role, ceo_role])
    use_case, audit = _use_case(positions)
    actor = _employee(ceo_role)

    # (a) Mövcud flag GERİ ALINIR.
    stripped = use_case.set_role_flags(
        tenant_id=TENANT, actor=actor, position_id=hr_role.id, flag_codes=()
    )
    assert stripped.granted_flags == frozenset()

    # (b) Yenidən VERİLİR.
    restored = use_case.set_role_flags(
        tenant_id=TENANT, actor=actor, position_id=hr_role.id, flag_codes=(EXPORT.code,)
    )
    assert restored.granted_flags == frozenset({EXPORT.code})

    assert len(positions.saved) == 2
    assert audit.actions() == ["POSITION_FLAGS_UPDATED", "POSITION_FLAGS_UPDATED"]


def test_root_can_still_edit_its_own_role() -> None:
    """SEC-006 Root istisnası qalır — əks halda sistem ilk gündən kilidlənərdi."""
    root_role = _root_role()
    positions = _Positions([root_role])
    use_case, _audit = _use_case(positions)

    updated = use_case.set_role_flags(
        tenant_id=TENANT,
        actor=_employee(root_role),
        position_id=root_role.id,
        flag_codes=(MANAGE_POSITIONS.code, SYSTEM_LIMITS.code),
    )

    assert updated.granted_flags == frozenset({MANAGE_POSITIONS.code, SYSTEM_LIMITS.code})


def test_root_can_still_drop_a_root_only_flag_from_its_own_role() -> None:
    """`Root` öz rolundan `ROOT_ONLY` flag-i çıxara bilər — qadağa AKTORA görədir."""
    root_role = _root_role()
    positions = _Positions([root_role])
    use_case, _audit = _use_case(positions)

    updated = use_case.set_role_flags(
        tenant_id=TENANT,
        actor=_employee(root_role),
        position_id=root_role.id,
        flag_codes=(MANAGE_POSITIONS.code,),
    )

    assert not updated.has_flag(SYSTEM_LIMITS.code)


# --------------------------------------------------------------------------- #
# 4. QAYDANIN DB YARISI (naxış: `test_db_guard_parity.py`)
# --------------------------------------------------------------------------- #

_FUNCTION_RE: Final = re.compile(
    r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+(?P<name>\w+)\s*\(\s*\)"
    r".*?\$\$(?P<body>.*?)\$\$\s*LANGUAGE\s+plpgsql",
    re.DOTALL | re.IGNORECASE,
)

_TRIGGER_RE: Final = re.compile(
    r"CREATE\s+TRIGGER\s+\w+\s+(?P<timing>BEFORE|AFTER)\s+(?P<events>[\w\s]+?)"
    r"\s+ON\s+(?P<table>\w+)\s+FOR\s+EACH\s+ROW\s+EXECUTE\s+FUNCTION\s+(?P<func>\w+)\s*\(\s*\)",
    re.DOTALL | re.IGNORECASE,
)

_LINE_COMMENT_RE: Final = re.compile(r"--[^\n]*")


def _sql_sources() -> list[tuple[str, str]]:
    """(fayl adı, ŞƏRHSİZ məzmun) — DOWN bloku şərh içindədir və sayılmamalıdır."""
    paths = [SCHEMA_FILE, *sorted(MIGRATIONS_DIR.glob("*.sql"))]
    return [
        (path.name, _LINE_COMMENT_RE.sub("", path.read_text(encoding="utf-8"))) for path in paths
    ]


def _function_body(name: str) -> str:
    bodies: dict[str, str] = {}
    for _file_name, sql in _sql_sources():
        for match in _FUNCTION_RE.finditer(sql):
            bodies[match.group("name").lower()] = match.group("body")
    if name not in bodies:
        pytest.fail(
            f"'{name}' funksiyası nə `schema.sql`-də, nə də miqrasiyalarda tapılmadı — "
            f"struktur zəmanətin DB yarısı silinib (CLAUDE.md §5)"
        )
    return bodies[name]


def _trigger_bindings() -> set[tuple[str, str, str]]:
    """(cədvəl, funksiya, hadisələr) — bütün SQL mənbələri üzrə."""
    bindings: set[tuple[str, str, str]] = set()
    for _file_name, sql in _sql_sources():
        for match in _TRIGGER_RE.finditer(sql):
            bindings.add(
                (
                    match.group("table").lower(),
                    match.group("func").lower(),
                    " ".join(match.group("events").split()).upper(),
                )
            )
    return bindings


def test_migration_046_exists_and_carries_the_search_path_preamble() -> None:
    """Qapı testi: fayl yoxdursa aşağıdakılar yanlış olaraq "keçərdi"."""
    path = MIGRATIONS_DIR / MIGRATION_046
    assert path.exists(), f"Miqrasiya tapılmadı: {path}"
    assert "SET search_path TO kompasos, public;" in path.read_text(encoding="utf-8")


def test_hierarchy_trigger_is_bound_to_the_position_permissions_table() -> None:
    """`enforce_hierarchy_guard()` YALNIZ override cədvəlindədir — rol yolu ayrıca bağlanır."""
    tables = {table for table, func, _events in _trigger_bindings() if func == HIERARCHY_FUNCTION}
    assert POSITION_TABLE in tables, (
        "`position_permissions` üzərində iyerarxiya trigger-i yoxdur — "
        "ekranı yan keçən SQL qaydadan azad qalır"
    )


def test_hierarchy_trigger_also_covers_the_delete_path() -> None:
    """GERİ ALMA DB-də `DELETE`-dir (`_sync_flags`), yəni trigger onu tutmalıdır.

    Yalnız `INSERT OR UPDATE` bağlansaydı, qorunan tərəf VERMƏK olardı, hücum
    isə məhz ALMAQ yolundan keçir.
    """
    events = {
        found_events
        for _table, func, found_events in _trigger_bindings()
        if func == HIERARCHY_FUNCTION
    }
    assert any("DELETE" in item for item in events), (
        "Trigger `DELETE` hadisəsini əhatə etmir — flag-in geri alınması qorumasız qalır"
    )


def test_db_body_mirrors_the_domain_semantics() -> None:
    """SQL gövdəsi domenlə EYNİ qərarları verməlidir (CLAUDE.md §5)."""
    body = _function_body(HIERARCHY_FUNCTION)

    assert "v_actor_code = 'ROOT'" in body, "SEC-006 Root istisnası itib"
    assert "v_target_priority <= v_actor_priority" in body, (
        "Bərabər pillə yenidən buraxılır — `<` deyil, `<=` olmalıdır (SEC-006)"
    )
    assert "app.user_id" in body, "DELETE yolunda aktor mənbəyi itib"
    assert "hardlock_level" in body, "ROOT_ONLY qərarı kataloqdan oxunmur"
    assert "v_target_code <> 'ROOT'" in body, "ROOT_ONLY flag başqa rola köçürülə bilər"


def test_db_side_reads_the_hardlock_level_instead_of_a_literal_flag_list() -> None:
    """Sərt siyahı ÜÇÜNCÜ mənbə yaradardı (CLAUDE.md §5) — qadağandır.

    Root Permission Registry-dən yeni `ROOT_ONLY` flag əlavə etdikdə literal
    siyahı arxada qalar və yeni flag sükutla qorumasız buraxılardı.
    """
    body = _function_body(HIERARCHY_FUNCTION)

    for literal in ("can_manage_permissions", "can_manage_system_limits"):
        assert literal not in body, (
            f"Trigger gövdəsində sabit flag adı ('{literal}') var — qərar "
            f"`permission_flags.hardlock_level` üzərində qurulmalıdır"
        )


def test_domain_half_of_the_rule_is_still_wired() -> None:
    """DB tərəfi domenin ƏVƏZİ deyil, TAMAMLAYICISIDIR.

    Domen yarısı silinsə ("trigger onsuz da tutur" mülahizəsi ilə), istifadəçi
    izahlı istisna əvəzinə `psycopg` xətası görərdi — CLAUDE.md §6-dakı naxış
    pozulardı.
    """
    source = Path(PositionManagementUseCase.__module__.replace(".", "/") + ".py")
    text = (PROJECT_ROOT / source).read_text(encoding="utf-8")

    assert "assert_may_be_edited_by" in text, "Use case iyerarxiya yoxlamasını çağırmır"
    assert "assert_root_only_flag_allowed" in text, "Use case ROOT_ONLY yoxlamasını çağırmır"

    entity: Any = Position
    assert hasattr(entity, "assert_may_be_edited_by")
    assert hasattr(entity, "assert_root_only_flag_allowed")
