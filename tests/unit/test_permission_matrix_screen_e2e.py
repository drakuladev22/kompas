"""`PermissionMatrixScreen` ↔ `controllers/permission_matrix.py` — REAL Qt e2e.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, ikinci dalğa)
──────────────────────────────────────────────────────────────────────────────
`test_permission_matrix_controller.py` GUARD-ların REAL kodla işlədiyini
sübut edir, lakin ekranı duck-typing ilə əvəz edir — checkbox HEÇ VAXT real
siçan kliki almır. `test_permission_matrix_actor_flags.py` Qt tələb edir,
lakin `screen.set_matrix(...)`-i BİRBAŞA çağırır, `controller.attach()`
üzərindən DEYİL. Bu fayl HƏR İKİSİNİ birləşdirir: `PermissionMatrixScreen`
real qurulur, `PermissionMatrixController` ona `.attach()` olunur, `Position
ManagementUseCase`-in ÖZÜ (saxta olan yalnız repo/audit/uow) işlədilir və
qutucuqlar/düymələr REAL `.click()` ilə basılır.

──────────────────────────────────────────────────────────────────────────────
TAPILAN QÜSUR — DEAKTİV (LAKİN İŞARƏLİ) XANA "YADDA SAXLA"-NI KOR EDİR
──────────────────────────────────────────────────────────────────────────────
`_flag_groups` sənədləşdirdiyi kimi, aktorda OLMAYAN bir flag rolda ARTIQ
granted-dırsa, checkbox `checked=True, enabled=False` göstərilir (D3) —
admin onu TOXUNA BİLMİR. Lakin `PermissionMatrixScreen.collected()`
"hardlock olanlar DA daxil, dəyişməz vəziyyətdə" bütün xanaları qaytarır və
`_on_saved` bunların hamısını `set_role_flags`-ə göndərir. `set_role_flags`
ƏVVƏLCƏ BÜTÜN mövcud flag-ləri geri alır, SONRA tam dəsti yenidən `_apply_
flags` ilə verir (`position_management.py:296`) — YENİDƏN VERMƏ addımı hər
kod üçün Self-Escalation Guard-ı işlədir, TOXUNULUB-TOXUNULMADIĞINDAN ASILI
OLMADAN. Nəticə: admin HEÇ TOXUNMADIĞI, artıq mövcud olan bir flag üzündən
TAMAMİLƏ ƏLAQƏSİZ, İCAZƏLİ bir dəyişikliyi belə saxlaya bilmir — bax
`test_saving_an_unrelated_change_is_blocked_by_an_untouched_flag_the_actor_
does_not_own` (xfail, DOĞRU gözlənilən davranışı yazır). Tapıntı `domain`-ə
göndərilib (`src/application/use_cases/position_management.py` onun
sahəsidir).

──────────────────────────────────────────────────────────────────────────────
İKİNCİ TAPINTI — MENYU QAPISI VƏ YAZI QAPISI FƏRQLİ FLAG İŞLƏDİR
──────────────────────────────────────────────────────────────────────────────
`shell/menu.py`-də "İcazə Matrisi" bəndi `required_flag="can_control_user_
permissions"` ilə göstərilir/gizlədilir, lakin `PositionManagementUseCase.
_require_permission()` (ekranın FAKTİKİ yazı qapısı, `list_roles`/`set_role_
flags`/`create_role`-un HAMISINDA) `can_manage_positions`-ı yoxlayır — İKİ
AYRI flag. Aktorda birincisi olub ikincisi olmasa, menyu bəndi görünür, lakin
ekran açılan kimi `list_roles` `AuthorizationError` atır və `refresh()` boş
xəta ekranı göstərir (bax `test_without_can_manage_positions_the_screen_
shows_a_clear_error_instead_of_a_blank_matrix`) — çökmə yoxdur, lakin bu, ölü
menyu bəndi sinfindən bir naxışdır (bax `git log` — "dörd ölü menyu bəndi").
Tapıntı `domain`-ə göndərilib.
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
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())
NOW: Final = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)

#: Yazı qapısı — `PositionManagementUseCase._require_permission`.
MANAGE_POSITIONS: Final = PermissionFlag(code="can_manage_positions", category="Sistem")
#: Adi, riskssiz flag — CEO-nun ÖZÜNDƏ ola bilər.
OWNED: Final = PermissionFlag(code="can_view_appeals", category="Cərimə")
#: Adi flag, LAKİN aktorda YOXDUR — HR_Admin-ə hələ verilməmiş.
NOT_OWNED_PLAIN: Final = PermissionFlag(code="can_view_leave", category="İcazə")
#: Anti-fraud flag — `Mağaza_Meneceri`/`Satıcı`-da OLA BİLMƏZ (bölmə 3).
ISSUE_FINES: Final = PermissionFlag(code="can_issue_fines", category="Cərimə", is_anti_fraud=True)
#: `Root` üçün hardlock — heç kimə (Root-dan başqa) verilə bilməz.
ROOT_ONLY_FLAG: Final = PermissionFlag(
    code="can_manage_backups", category="Sistem", hardlock=HardlockLevel.ROOT_ONLY
)


# --------------------------------------------------------------------------- #
# Sahtə mühit — YALNIZ repo/audit/uow; use case VƏ ekran REALDIR
# --------------------------------------------------------------------------- #


class _PositionsRepo:
    def __init__(self, positions: list[Position]) -> None:
        self.items: dict[Any, Position] = {p.id: p for p in positions}
        self.saved: list[Position] = []
        self.save_error: Exception | None = None

    def _fresh(self, position: Position) -> Position:
        """DB-dən YENİDƏN oxunmuş kimi TƏZƏ instansiya qaytarır.

        Real repo hər sessiyada SQL-dən YENİ `Position` qurur. Bu fake əvəzinə
        eyni obyekti qaytarsaydı, use case-in `revoke()`+`grant()` ilə etdiyi
        in-memory mutasiya `save()` UĞURSUZ olsa BELƏ sonrakı `refresh()`-ə
        SIZARDI — yəni uğursuz yazı DB-də əks olunmadığı halda ekranda əks
        olunmuş kimi görünərdi (bax `test_a_generic_repository_failure_on_
        save_shows_a_clear_message_and_recovers`).
        """
        clone = Position(
            position_id=position.id,
            code=position.code,
            name_az=position.name_az,
            priority=position.priority,
            tenant_id=position.tenant_id,
            is_system=position.is_system,
            is_camera_type=position.is_camera_type,
            is_active=position.is_active,
        )
        clone._granted_flags = set(position.granted_flags)
        return clone

    def get(self, position_id: PositionId) -> Position | None:
        base = self.items.get(position_id)
        return self._fresh(base) if base is not None else None

    def get_by_code(self, tenant_id: TenantId, code: str) -> Position | None:
        base = next((p for p in self.items.values() if p.code == code), None)
        return self._fresh(base) if base is not None else None

    def list_for_tenant(self, tenant_id: TenantId) -> list[Position]:
        return [self._fresh(p) for p in self.items.values()]

    def save(self, position: Position) -> None:
        if self.save_error is not None:
            raise self.save_error
        self.saved.append(position)
        self.items[position.id] = self._fresh(position)


class _FlagsRepo:
    def __init__(self, flags: list[PermissionFlag]) -> None:
        self.items = {f.code: f for f in flags}

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
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _Connection:
    """`_flag_labels` VƏ `_employee_counts` eyni `execute(...)`-dan keçir."""

    def __init__(self, flags: _FlagsRepo) -> None:
        self._flags = flags

    def execute(self, sql: str, params: Any = None) -> _Cursor:
        if "permission_flags" in sql:
            return _Cursor([{"code": code, "name_az": code} for code in self._flags.items])
        return _Cursor([])  # `_employee_counts` — bu testlərdə əhəmiyyətsiz.


class _Uow:
    def __init__(self, flags: _FlagsRepo) -> None:
        self.connection = _Connection(flags)
        self._flags = flags

    def repository(self, name: str) -> Any:
        assert name == "permission_flags"
        return self._flags


class _Session:
    def __init__(self, use_case: PositionManagementUseCase, flags: _FlagsRepo) -> None:
        self.tenant_id = TENANT
        self.positions = use_case
        self.uow = _Uow(flags)
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Context:
    def __init__(self, session: _Session) -> None:
        self._session = session
        #: hər `with context.session(...)` çağırışının `user_id`-si — YENİ
        #: sessiya naxışının (bölmə 6) real işlədiyini yoxlamaq üçün.
        self.session_calls: list[Any] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        self.session_calls.append(user_id)
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
) -> tuple[Any, _Context, _PositionsRepo]:
    """`(controller, context, positions_repo)` — REAL use case, saxta repo."""
    actor_position = _position(actor_role, flags=actor_flags)
    actor = _employee(actor_position)

    positions = _PositionsRepo([actor_position, target])
    flags = _FlagsRepo(catalog)
    use_case = PositionManagementUseCase(
        positions=positions,  # type: ignore[arg-type]
        flags=flags,  # type: ignore[arg-type]
        audit=_Audit(),  # type: ignore[arg-type]
        clock=_Clock(),  # type: ignore[arg-type]
    )
    session = _Session(use_case, flags)
    context = _Context(session)
    controller = PermissionMatrixController(context, actor)  # type: ignore[arg-type]
    return controller, context, positions


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _select_role(screen: Any, code: str) -> None:
    """Rol düyməsinə REAL klik — `select_role(...)`-un birbaşa çağırışı DEYİL."""
    screen._role_buttons[code].click()


# --------------------------------------------------------------------------- #
# 1. Rol seçimi — real klik matrisi doldurur
# --------------------------------------------------------------------------- #


def _press_retry(screen: Any) -> None:
    """Xəta banner-indəki «Yenidən Cəhd Et» düyməsini HƏQİQƏTƏN basır.

    Siqnalı birbaşa yaymaq kifayət etməzdi: UI-R4-01-ə görə `on_retry`
    verilməyəndə düymə ÜMUMİYYƏTLƏ çəkilmir (bax `ContentSwitcher.show_error`
    docstring-i). Yəni düymənin MÖVCUDLUĞU testin əsl iddiasıdır — banner
    yenilənməni istifadəçiyə buraxırsa, o yenilənməni başlatmaq YOLU da
    olmalıdır.
    """
    from PySide6.QtWidgets import QPushButton

    state = screen.switcher()._stack.currentWidget()
    button = state.findChild(QPushButton)
    assert button is not None, "Xəta banner-i «Yenidən Cəhd Et» düyməsi olmadan ölü dalandır"
    button.click()


@requires_qt
def test_selecting_a_role_via_a_real_click_loads_its_matrix(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_c import PermissionMatrixScreen

    target = _position(SystemRole.HR_ADMIN, flags=[OWNED])
    controller, context, _positions = _build(
        actor_flags=[MANAGE_POSITIONS, OWNED],
        target=target,
        catalog=[MANAGE_POSITIONS, OWNED, NOT_OWNED_PLAIN],
    )
    screen = PermissionMatrixScreen(theme)
    qtbot.addWidget(screen)

    controller.attach(screen)  # `refresh()` onsuz da ilk rolu seçir.

    assert target.code in screen._role_buttons
    assert OWNED.code in screen._checkboxes
    assert screen._checkboxes[OWNED.code].isChecked() is True
    assert screen._checkboxes[NOT_OWNED_PLAIN.code].isChecked() is False

    # İkinci real klik — eyni rolun üstünə yenidən basmaq sındırmamalıdır.
    _select_role(screen, target.code)
    assert screen._matrix_title.text().startswith(target.name_az)
    # Hər `role_selected` YENİ sessiya açır (bölmə 6).
    assert len(context.session_calls) >= 2
    assert all(user_id is not None for user_id in context.session_calls)


# --------------------------------------------------------------------------- #
# 2. Aktorda OLMAYAN, LAKİN artıq granted flag — real klik ONU AÇMIR
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_flag_the_actor_does_not_own_cannot_be_checked_via_a_real_click(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """D3 qorunmasının REAL siçan kliki qarşısında da tutduğunu sübut edir."""
    from src.presentation.screens.group_c import PermissionMatrixScreen

    # Rol NOT_OWNED_PLAIN-i ARTIQ daşıyır, amma bunu verən başqa admin idi —
    # cari aktorda bu flag YOXDUR.
    target = _position(SystemRole.HR_ADMIN, flags=[NOT_OWNED_PLAIN])
    controller, _context, _positions = _build(
        actor_flags=[MANAGE_POSITIONS],  # NOT_OWNED_PLAIN aktorda YOXDUR.
        target=target,
        catalog=[MANAGE_POSITIONS, NOT_OWNED_PLAIN],
    )
    screen = PermissionMatrixScreen(theme)
    qtbot.addWidget(screen)
    controller.attach(screen)

    box = screen._checkboxes[NOT_OWNED_PLAIN.code]
    assert box.isChecked() is True, "Rolda mövcud olan flag aktiv göstərilməlidir"
    assert box.isEnabled() is False, "Aktorda olmayan flag basıla bilməməlidir (D3)"
    assert box.toolTip() == "Bu icazə sizdə yoxdur — başqasına verə bilməzsiniz"

    box.click()  # REAL klik — Qt deaktiv widget-i sükutla İMTİNA edir.

    assert box.isChecked() is True, "Deaktiv xana klikdən sonra da DƏYİŞMƏMƏLİDİR"


# --------------------------------------------------------------------------- #
# 3. Anti-fraud/hardlock ilə bloklanan flag — real klik ONU AÇMIR
# --------------------------------------------------------------------------- #


@requires_qt
def test_an_anti_fraud_flag_is_locked_and_cannot_be_checked_via_a_real_click(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`can_issue_fines` `Mağaza_Meneceri`-də ola bilməz — qıfıl, aktordan ASILI DEYİL."""
    from src.presentation.screens.group_c import PermissionMatrixScreen

    target = _position(SystemRole.STORE_MANAGER)  # ISSUE_FINES HƏLƏ granted DEYİL.
    controller, _context, _positions = _build(
        actor_flags=[MANAGE_POSITIONS, ISSUE_FINES],  # Aktorda VAR — self-escalation səbəb deyil.
        target=target,
        catalog=[MANAGE_POSITIONS, ISSUE_FINES],
    )
    screen = PermissionMatrixScreen(theme)
    qtbot.addWidget(screen)
    controller.attach(screen)

    box = screen._checkboxes[ISSUE_FINES.code]
    assert box.isChecked() is False
    assert box.isEnabled() is False, "Anti-fraud qadağası aktorun sahibliyindən ASILI DEYİL"
    assert "Hardlock" in box.toolTip() or "ayrılığı" in box.toolTip()

    box.click()

    assert box.isChecked() is False, "Qıfıllı xana klikdən sonra da BAĞLI qalmalıdır"


# --------------------------------------------------------------------------- #
# 4. TAPILAN QÜSUR — toxunulmamış, artıq mövcud flag ƏLAQƏSİZ dəyişikliyi bloklayır
# --------------------------------------------------------------------------- #


@requires_qt
def test_saving_an_unrelated_change_is_blocked_by_an_untouched_flag_the_actor_does_not_own(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """DOĞRU gözlənilən davranış: toxunulmayan xana YENİDƏN yoxlanılmamalıdır.

    Ssenari: HR_Admin rolunda ARTIQ `NOT_OWNED_PLAIN` var (aktorda yoxdur,
    disabled-checked göstərilir, D3). Admin bunu heç toxunmadan, sadəcə
    ayrıca, öz sahib olduğu `OWNED` flag-ini əlavə etmək istəyir. Bu, tam
    icazəli, zərərsiz bir dəyişiklikdir və UĞURLA saxlanmalıdır — Self-
    Escalation Guard yalnız FAKTİKİ YENİ verilən flag-lərə tətbiq olunmalıdır,
    dəyişməyən mövcud flag-lərə YOX.
    """
    from src.presentation.screens.group_c import PermissionMatrixScreen

    target = _position(SystemRole.HR_ADMIN, flags=[NOT_OWNED_PLAIN])
    controller, context, positions = _build(
        actor_flags=[MANAGE_POSITIONS, OWNED],  # NOT_OWNED_PLAIN aktorda YOXDUR.
        target=target,
        catalog=[MANAGE_POSITIONS, OWNED, NOT_OWNED_PLAIN],
    )
    screen = PermissionMatrixScreen(theme)
    qtbot.addWidget(screen)
    controller.attach(screen)

    # Admin YALNIZ öz sahib olduğu, indiyə qədər granted OLMAYAN OWNED-i
    # işarələyir — NOT_OWNED_PLAIN-ə HEÇ TOXUNMUR.
    screen._checkboxes[OWNED.code].click()
    screen._save.click()

    assert context.session_calls, "Yazı sessiyası açılmalıdır"
    saved_target = next(p for p in positions.saved if p.id == target.id)
    assert OWNED.code in saved_target.granted_flags, "İcazəli əlavə YAZILMALIDIR"
    assert NOT_OWNED_PLAIN.code in saved_target.granted_flags, (
        "Toxunulmayan mövcud flag QORUNMALIDIR"
    )


# --------------------------------------------------------------------------- #
# 5. Bütün xanalar unchecked halda saxla — hamısı geri alınır
# --------------------------------------------------------------------------- #


@requires_qt
def test_saving_with_every_box_unchecked_revokes_everything_and_commits(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    target = _position(SystemRole.HR_ADMIN, flags=[OWNED])
    controller, context, positions = _build(
        actor_flags=[MANAGE_POSITIONS, OWNED],
        target=target,
        catalog=[MANAGE_POSITIONS, OWNED],
    )
    from src.presentation.screens.group_c import PermissionMatrixScreen

    screen = PermissionMatrixScreen(theme)
    qtbot.addWidget(screen)
    controller.attach(screen)

    box = screen._checkboxes[OWNED.code]
    assert box.isChecked() is True
    box.click()  # REAL klik — söndürür.
    assert box.isChecked() is False

    screen._save.click()

    saved_target = next(p for p in positions.saved if p.id == target.id)
    assert saved_target.granted_flags == set()
    assert context._session.commits >= 1


# --------------------------------------------------------------------------- #
# 6. Sürətli ikiqat klik — dublikat yazı yoxdur, çökmə yoxdur
# --------------------------------------------------------------------------- #


@requires_qt
def test_double_clicking_save_quickly_does_not_crash_or_duplicate_the_change(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """İkinci klik EYNİ nəticəni yenidən yazır (idempotent) — çökmür, təkrarlanmır."""
    target = _position(SystemRole.HR_ADMIN)
    controller, context, positions = _build(
        actor_flags=[MANAGE_POSITIONS, OWNED],
        target=target,
        catalog=[MANAGE_POSITIONS, OWNED],
    )
    from src.presentation.screens.group_c import PermissionMatrixScreen

    screen = PermissionMatrixScreen(theme)
    qtbot.addWidget(screen)
    controller.attach(screen)

    screen._checkboxes[OWNED.code].click()
    screen._save.click()
    screen._save.click()  # sürətli ikinci klik — heç bir gözləmə YOXDUR.

    assert len(positions.saved) == 2, "İki klik = iki yazı, LAKİN nəticə eynidir"
    assert all(p.granted_flags == {OWNED.code} for p in positions.saved)
    assert context._session.commits == 2


# --------------------------------------------------------------------------- #
# 7. Repo istisna atanda — AYDIN mesaj, banner sükutla üstündən yazılmır
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_generic_repository_failure_on_save_shows_a_clear_message_and_recovers(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    target = _position(SystemRole.HR_ADMIN)
    controller, context, positions = _build(
        actor_flags=[MANAGE_POSITIONS, OWNED],
        target=target,
        catalog=[MANAGE_POSITIONS, OWNED],
    )
    from src.presentation.screens.group_c import PermissionMatrixScreen

    screen = PermissionMatrixScreen(theme)
    qtbot.addWidget(screen)
    controller.attach(screen)

    positions.save_error = RuntimeError("DB bağlantısı kəsildi")
    screen._checkboxes[OWNED.code].click()
    screen._save.click()

    # ƏVVƏLKİ İDDİA TƏRSİNƏ ÇEVRİLDİ (QA-FULL FAZA 3 davamı). Burada əvvəl
    # «banner ekranı 'error' vəziyyətində DAYANDIRMAMALIDIR» yazılmışdı və test
    # məhz qüsuru kilidləyirdi: `_on_saved` istisnadan sonra DƏRHAL `refresh()`
    # çağırırdı, `select_role()` → `set_matrix()` → `show_content()` zənciri isə
    # banner-in ÜSTÜNDƏN yazırdı. Nəticədə admin yazı xətasını HEÇ VAXT
    # görmürdü — xanalar səbəbsiz geri qayıdırdı və bu, «proqram dəyişikliyimi
    # özbaşına ləğv etdi» kimi oxunurdu. «Matrisi itirmiş sanar» narahatlığı
    # isə yerində qalmır: banner-də İŞLƏYƏN «Yenidən Cəhd Et» düyməsi var.
    assert screen.switcher().current_state() == "error", (
        "Yazı xətası GÖRÜNMƏLİDİR — yenilənmə onu udmamalıdır"
    )
    assert context._session.commits == 0, "Uğursuz yazı commit OLUNMAMALIDIR"

    _press_retry(screen)

    assert screen.switcher().current_state() == "content"
    # `refresh()` yenidən oxuduqda flag DƏYİŞMƏMİŞ qalır — YALAN göstərilmir.
    assert screen._checkboxes[OWNED.code].isChecked() is False


# --------------------------------------------------------------------------- #
# 8. "+ Yeni Vəzifə" — real klik, real dialoq, real yaratma
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_create_role_button_and_dialog_are_really_wired(qtbot, theme, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`role_create_requested` ÖLÜ BƏND DEYİL — real klik real rol yaradır."""
    from PySide6.QtWidgets import QDialog

    from src.presentation.screens import group_c as group_c_module
    from src.presentation.screens.group_c import PermissionMatrixScreen

    target = _position(SystemRole.HR_ADMIN)
    controller, _context, positions = _build(
        actor_flags=[MANAGE_POSITIONS],
        target=target,
        catalog=[MANAGE_POSITIONS],
    )
    screen = PermissionMatrixScreen(theme)
    qtbot.addWidget(screen)
    controller.attach(screen)

    # Dialoq `.exec()` modal göz gözləyər — testdə avtomatik doldurub Yarat
    # basırıq, dialoq real qalır.
    def _auto_submit(self: Any) -> int:
        self._name.set_text("Anbar Nəzarətçisi")
        self._on_submit()
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(group_c_module.RoleCreateDialog, "exec", _auto_submit)

    create_button = next(
        b for b in screen.findChildren(type(screen._save)) if b.text() == "+ Yeni Vəzifə"
    )
    create_button.click()

    assert positions.saved, "'+ Yeni Vəzifə' rol yaratmalıdır — ÖLÜ bənd deyil"
    created = positions.saved[-1]
    assert created.name_az == "Anbar Nəzarətçisi"
    assert created.granted_flags == set(), (
        "Yeni rol İCAZƏSİZ doğulmalıdır (ən qapalı ilkin vəziyyət)"
    )
    # Yaradıldıqdan sonra DƏRHAL seçilir (`self._active = position.code`).
    assert created.code in screen._role_buttons


# --------------------------------------------------------------------------- #
# 9. "Ləğv Et" — real klik seçimi bazadakı vəziyyətə qaytarır
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_cancel_reverts_unsaved_checkbox_changes(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    target = _position(SystemRole.HR_ADMIN, flags=[OWNED])
    controller, _context, _positions = _build(
        actor_flags=[MANAGE_POSITIONS, OWNED],
        target=target,
        catalog=[MANAGE_POSITIONS, OWNED],
    )
    from src.presentation.screens.group_c import PermissionMatrixScreen

    screen = PermissionMatrixScreen(theme)
    qtbot.addWidget(screen)
    controller.attach(screen)

    box = screen._checkboxes[OWNED.code]
    assert box.isChecked() is True
    box.click()
    assert screen.collected()[OWNED.code] is False, "Yadda saxlanmamış dəyişiklik lokal qalmalıdır"

    screen._cancel.click()  # REAL klik — `role_selected` təkrar yayılır.

    assert screen._checkboxes[OWNED.code].isChecked() is True, (
        "Ləğv Et bazadakı vəziyyəti bərpa etməlidir"
    )


# --------------------------------------------------------------------------- #
# 10. `can_manage_positions` YOXDUR — boş matris DEYİL, aydın xəta (fail-closed)
# --------------------------------------------------------------------------- #


@requires_qt
def test_without_can_manage_positions_the_screen_shows_a_clear_error_instead_of_a_blank_matrix(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """Yazı qapısının FAKTİKİ tələb etdiyi flag `can_manage_positions`-dır.

    `shell/menu.py`-dəki naviqasiya qapısı isə `can_control_user_permissions`
    yoxlayır (bax modul başlığı, İKİNCİ TAPINTI). Aktorda YALNIZ menyu
    flag-i olsaydı, menyu bəndi görünərdi, lakin ekran DƏRHAL bura düşərdi —
    çökmə yoxdur, amma dead-end menyu bəndi naxışıdır.
    """
    target = _position(SystemRole.HR_ADMIN)
    controller, _context, _positions = _build(
        actor_flags=[],  # `can_manage_positions` YOXDUR.
        target=target,
        catalog=[MANAGE_POSITIONS],
    )
    from src.presentation.screens.group_c import PermissionMatrixScreen

    screen = PermissionMatrixScreen(theme)
    qtbot.addWidget(screen)

    controller.attach(screen)

    assert screen.switcher().current_state() == "error"
    assert screen._role_buttons == {}, (
        "Boş, lakin YALAN vəziyyət YOXDUR — heç bir rol düyməsi çəkilmir"
    )
