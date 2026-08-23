"""`EmployeeHomeScreen`/`ShiftPlanningScreen` ↔ `controllers/open_shift.py` — REAL Qt e2e.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3)
──────────────────────────────────────────────────────────────────────────────
`test_open_shift_controller.py` HƏR İKİ kontrolleri sahtə `_EmployeeScreen`/
`_AdminScreen` siniflərlə ölçür — REAL `EmployeeHomeScreen`, REAL
`ShiftPlanningScreen`, REAL `OpenShiftPostDialog` heç vaxt qurulmur, REAL
"Bu Növbəni Götür"/"Açıq Növbə Elan Et"/"Ləğv Et" düymələri heç vaxt
klikllənmir. Burada hər ikisi FAKTİKİ qurulur.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from src.domain.value_objects.identifiers import OpenShiftPostingId, StoreId, WorkModeId
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()
STORE = StoreId(uuid.uuid4())
WORK_MODE = WorkModeId(uuid.uuid4())
POSTING = OpenShiftPostingId(uuid.uuid4())


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


def _view(*, posting: Any = POSTING, store: Any = STORE, mode: Any = WORK_MODE) -> Any:
    from src.application.use_cases.open_shift_market import OpenShiftView

    return OpenShiftView(
        posting_id=posting,
        store_id=store,
        shift_date=date(2026, 8, 25),
        work_mode_id=mode,
        status="OPEN",
        posted_by=None,
        claimed_by=None,
        created_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
    )


def _work_mode(*, work_mode_id: Any = WORK_MODE, name: str = "Gündüz") -> Any:
    from src.domain.value_objects.catalogs import WorkMode

    return WorkMode(name=name, tenant_id=TENANT, work_mode_id=work_mode_id)


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _Row(dict):
    pass


class _Connection:
    """`_store_choices` (fetchall) VƏ `_store_name` (fetchone) — İKİ FƏRQLİ sorğu."""

    def __init__(self, stores: dict[str, str]) -> None:
        self._stores = stores
        self._last_params: tuple[Any, ...] | None = None

    def execute(self, _sql: str, params: Any = None) -> _Connection:
        self._last_params = params
        return self

    def fetchall(self) -> list[_Row]:
        return [_Row(id=sid, name=name) for sid, name in self._stores.items()]

    def fetchone(self) -> _Row | None:
        if not self._last_params:
            return None
        store_id = str(self._last_params[0])
        name = self._stores.get(store_id)
        return _Row(name=name) if name else None


class _WorkModeRepo:
    def __init__(self, modes: dict[Any, Any]) -> None:
        self._modes = modes

    def get(self, work_mode_id: Any) -> Any:
        return self._modes.get(work_mode_id)


class _EmployeesRepo:
    """DEEP-GAP OP-4 — `_to_claimed_row` işçinin ADINI oxuyur.

    Menecer «kimin növbəsini geri verirəm?» sualının cavabını görməlidir;
    tapılmayan işçi üçün ad BOŞ qalır (yalan ad göstərilmir).
    """

    def __init__(self, name: str = "Aygün Məmmədova") -> None:
        self._name = name

    def get(self, _employee_id: Any) -> Any:
        return SimpleNamespace(full_name=self._name)


class _Uow:
    def __init__(self, stores: dict[str, str], work_modes: dict[Any, Any]) -> None:
        self.connection = _Connection(stores)
        self._work_modes = work_modes
        self.employees = _EmployeesRepo()

    def repository(self, name: str) -> Any:
        if name == "work_modes":
            return _WorkModeRepo(self._work_modes)
        raise NotImplementedError(name)


class _Limits:
    def __init__(self, max_lead_days: int = 3) -> None:
        self.max_lead_days = max_lead_days

    def get_int(self, _tenant_id: Any, _key: str, _fallback: int) -> int:
        return self.max_lead_days


class _WorkModesCatalog:
    def __init__(self, modes: list[Any]) -> None:
        self._modes = modes

    def list_for_selection(self, _tenant_id: Any) -> list[Any]:
        return list(self._modes)


class _OpenShifts:
    def __init__(self) -> None:
        self.employee_rows: list[Any] = []
        self.admin_rows: list[Any] = []
        self.claims: list[dict[str, Any]] = []
        self.claim_error: KompasOSError | None = None
        self.postings: list[dict[str, Any]] = []
        self.post_error: KompasOSError | None = None
        self.cancellations: list[dict[str, Any]] = []
        self.cancel_error: KompasOSError | None = None
        self.admin_list_error: KompasOSError | None = None

    def list_for_employee(self, *, tenant_id: Any, employee: Any) -> list[Any]:
        return list(self.employee_rows)

    def list_claimed_for_employee(self, *, tenant_id: Any, employee: Any) -> list[Any]:
        """DEEP-GAP OP-4 — «Tutduğunuz növbələr» bölməsinin oxu yolu.

        Sahtə BOŞ siyahı qaytarır: bu faylın testləri TUTMA axınını ölçür,
        geri vermə isə ayrıca sınanır. Metodun MÖVCUD olması vacibdir —
        `refresh()` hər çağırışda hər iki siyahını EYNİ sessiyada oxuyur.
        """
        return []

    def claim(self, *, tenant_id: Any, employee: Any, posting_id: Any) -> None:
        if self.claim_error is not None:
            raise self.claim_error
        self.claims.append({"posting_id": posting_id})

    def list_active(self, *, tenant_id: Any, actor: Any) -> list[Any]:
        if self.admin_list_error is not None:
            raise self.admin_list_error
        return list(self.admin_rows)

    def list_claimed_for_store(self, *, tenant_id: Any, actor: Any) -> list[Any]:
        """DEEP-GAP OP-4 — menecerin «Tutulmuş növbələr» siyahısı.

        Bu faylın testləri ELAN VERMƏ/LƏĞV axınını ölçür, ona görə sahtə boş
        siyahı qaytarır; geri vermə `test_open_shift_controller.py`-dədir.
        """
        if self.admin_list_error is not None:
            raise self.admin_list_error
        return []

    def post_open_shift(self, **kwargs: Any) -> None:
        if self.post_error is not None:
            raise self.post_error
        self.postings.append(kwargs)

    def cancel_posting(self, **kwargs: Any) -> None:
        if self.cancel_error is not None:
            raise self.cancel_error
        self.cancellations.append(kwargs)


class _Session:
    def __init__(
        self,
        open_shifts: _OpenShifts,
        stores: dict[str, str],
        work_modes: dict[Any, Any],
        catalog_modes: list[Any],
        limits: _Limits,
    ) -> None:
        self.tenant_id = TENANT
        self.open_shifts = open_shifts
        self.uow = _Uow(stores, work_modes)
        self.limits = limits
        self.work_modes = _WorkModesCatalog(catalog_modes)
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(
        self,
        open_shifts: _OpenShifts,
        *,
        stores: dict[str, str] | None = None,
        work_modes: dict[Any, Any] | None = None,
        catalog_modes: list[Any] | None = None,
        max_lead_days: int = 3,
    ) -> None:
        self._open_shifts = open_shifts
        self._stores = stores or {}
        self._work_modes = work_modes or {}
        self._catalog_modes = catalog_modes or []
        self._limits = _Limits(max_lead_days)
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(
            self._open_shifts, self._stores, self._work_modes, self._catalog_modes, self._limits
        )
        self.sessions.append(created)
        yield created


class _Actor:
    id = ACTOR_ID


# --------------------------------------------------------------------------- #
# 1. İşçi tərəfi — real "Bu Növbəni Götür" kliki
# --------------------------------------------------------------------------- #


@requires_qt
def test_claiming_an_open_shift_via_the_real_button_commits_and_refreshes(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.open_shift import EmployeeOpenShiftController
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen

    open_shifts = _OpenShifts()
    open_shifts.employee_rows = [_view()]
    context = _Context(open_shifts, work_modes={WORK_MODE: _work_mode()})
    screen = EmployeeHomeScreen(
        theme, full_name="Aygün Məmmədova", position_name="Satıcı", store_name="Mərkəz"
    )
    qtbot.addWidget(screen)
    EmployeeOpenShiftController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Bu Növbəni Götür")

    assert len(open_shifts.claims) == 1
    assert str(open_shifts.claims[0]["posting_id"]) == str(POSTING)
    assert any(s.committed for s in context.sessions)
    assert screen._open_shift_hint.text() == "Növbə sizin adınıza yazıldı."


@requires_qt
def test_losing_the_claim_race_shows_the_domain_message_not_a_silent_failure(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`OpenShiftAlreadyClaimedError` sinifli xəta — kiosk PAYLAŞILAN cihazdır, ÇÖKMƏMƏLİDİR."""
    from src.presentation.controllers.open_shift import EmployeeOpenShiftController
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen

    open_shifts = _OpenShifts()
    open_shifts.employee_rows = [_view()]
    open_shifts.claim_error = KompasOSError(
        "already claimed", user_message="Bu növbəni artıq başqası götürüb."
    )
    context = _Context(open_shifts, work_modes={WORK_MODE: _work_mode()})
    screen = EmployeeHomeScreen(
        theme, full_name="Aygün Məmmədova", position_name="Satıcı", store_name="Mərkəz"
    )
    qtbot.addWidget(screen)
    screen.show()  # `isVisible()` göstərilməyən pəncərədə HƏMİŞƏ False qaytarır
    EmployeeOpenShiftController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    _click(screen, "Bu Növbəni Götür")  # ÇÖKMƏMƏLİDİR

    assert screen._open_shift_hint.text() == "Bu növbəni artıq başqası götürüb."
    assert screen._open_shift_hint.isVisible()


@requires_qt
def test_a_malformed_posting_id_from_a_stale_card_does_not_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.open_shift import EmployeeOpenShiftController
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen

    open_shifts = _OpenShifts()
    context = _Context(open_shifts)
    screen = EmployeeHomeScreen(
        theme, full_name="Aygün Məmmədova", position_name="Satıcı", store_name="Mərkəz"
    )
    qtbot.addWidget(screen)
    EmployeeOpenShiftController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    screen.open_shift_claim_requested.emit("not-a-uuid")  # ÇÖKMƏMƏLİDİR

    assert open_shifts.claims == []
    assert screen._open_shift_hint.text() == "Elan identifikatoru düzgün deyil."


# --------------------------------------------------------------------------- #
# 2. Admin tərəfi — real "Açıq Növbə Elan Et" → real dialoq → real klik
# --------------------------------------------------------------------------- #


def _patched_post_dialog_exec(
    monkeypatch: pytest.MonkeyPatch, *, store_id: str, day: str, mode_id: str
) -> None:
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.open_shift import OpenShiftPostDialog

    def fake_exec(self: OpenShiftPostDialog) -> int:
        for combo, value in (
            (self._stores, store_id),
            (self._days, day),
            (self._modes, mode_id),
        ):
            index = combo.findData(value)
            assert index >= 0, f"seçim tapılmadı: {value}"
            combo.setCurrentIndex(index)
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Elan Et")
        submit.click()
        return 0

    monkeypatch.setattr(OpenShiftPostDialog, "exec", fake_exec)


@requires_qt
def test_posting_an_open_shift_via_the_real_dialog_commits_and_refreshes(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.open_shift import ShiftMatrixOpenShiftController
    from src.presentation.screens.group_c import ShiftPlanningScreen

    open_shifts = _OpenShifts()
    mode = _work_mode()
    context = _Context(
        open_shifts,
        stores={str(STORE): "Mərkəz"},
        work_modes={WORK_MODE: mode},
        catalog_modes=[mode],
        max_lead_days=5,
    )
    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)
    ShiftMatrixOpenShiftController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    today = date.today()  # noqa: DTZ011 — `_day_choices` ilə eyni qərar, testdə seçim üçün
    _patched_post_dialog_exec(
        monkeypatch, store_id=str(STORE), day=today.isoformat(), mode_id=str(WORK_MODE)
    )

    _click(screen, "Açıq Növbə Elan Et")

    assert len(open_shifts.postings) == 1
    posted = open_shifts.postings[0]
    assert str(posted["store_id"]) == str(STORE)
    assert str(posted["work_mode_id"]) == str(WORK_MODE)
    assert posted["shift_date"] == today
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_posting_dialog_blocks_submission_when_no_choices_exist(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Mağaza/iş rejimi kataloqu boşdursa combo-lar boş qalır — REAL validasiya."""
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.open_shift import OpenShiftPostDialog

    dialog = OpenShiftPostDialog(
        theme, stores=[], days=[("2026-08-25", "25.08.2026")], work_modes=[]
    )
    qtbot.addWidget(dialog)
    emitted: list[Any] = []
    dialog.submitted.connect(lambda *a: emitted.append(a))

    submit = next(b for b in dialog.findChildren(QPushButton) if b.text() == "Elan Et")
    submit.click()

    assert emitted == []
    assert dialog._hint.text() == "Mağaza, tarix və iş rejimi seçilməlidir."


# --------------------------------------------------------------------------- #
# 3. Admin tərəfi — real "Ləğv Et" (rendered sətir), real səbəb modalı
# --------------------------------------------------------------------------- #


@requires_qt
def test_cancelling_a_posting_via_the_real_row_and_reason_prompt_commits(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    from src.presentation.controllers.open_shift import ShiftMatrixOpenShiftController
    from src.presentation.screens.group_c import ShiftPlanningScreen

    open_shifts = _OpenShifts()
    open_shifts.admin_rows = [_view()]
    context = _Context(
        open_shifts, stores={str(STORE): "Mərkəz"}, work_modes={WORK_MODE: _work_mode()}
    )
    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)
    ShiftMatrixOpenShiftController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("mağaza bağlıdır", True))
    )

    _click(screen, "Ləğv Et")

    assert len(open_shifts.cancellations) == 1
    cancelled = open_shifts.cancellations[0]
    assert str(cancelled["posting_id"]) == str(POSTING)
    assert cancelled["reason"] == "mağaza bağlıdır"
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_declining_the_reason_prompt_cancels_nothing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    from src.presentation.controllers.open_shift import ShiftMatrixOpenShiftController
    from src.presentation.screens.group_c import ShiftPlanningScreen

    open_shifts = _OpenShifts()
    open_shifts.admin_rows = [_view()]
    context = _Context(
        open_shifts, stores={str(STORE): "Mərkəz"}, work_modes={WORK_MODE: _work_mode()}
    )
    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)
    ShiftMatrixOpenShiftController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("", False)))

    _click(screen, "Ləğv Et")

    assert open_shifts.cancellations == []


@requires_qt
def test_cancel_failure_from_a_concurrent_claim_does_not_crash(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """`cancel_posting()` istisna atsa da (elan bu arada tutulub) — ÇÖKMƏMƏLİDİR.

    `_on_cancel`-in `except KompasOSError` qolu da (`announcements.py::
    _on_withdraw` ilə eyni naxışda) `show_error()`-dan DƏRHAL sonra
    `self.refresh(screen)` çağırır. BURADA bu, `announcements.py`-dəki kimi
    xətanı ÜSTÜNDƏN yazmır — çünki `ShiftPlanningScreen.set_open_shift_
    postings()` `show_content()` ÇAĞIRMIR (yalnız kartın öz `set_postings()`-
    inə ötürür), yəni `ContentSwitcher` `show_error()`-un qoyduğu vəziyyətdə
    qalır. Nəticə düzgündür, LAKİN TƏSADÜFİDİR: `refresh()` bu ekranda
    NƏ VAXT SA `show_content()` çağırsaydı (məs. kart da digər bölmələr kimi
    keçid idarə etməyə başlasaydı), eyni "xəta göründü, sonra sükutla
    yoxa çıxdı" nasazlığı BURADA da yaranardı.
    """
    from PySide6.QtWidgets import QInputDialog

    from src.presentation.controllers.open_shift import ShiftMatrixOpenShiftController
    from src.presentation.screens.group_c import ShiftPlanningScreen

    open_shifts = _OpenShifts()
    open_shifts.admin_rows = [_view()]
    open_shifts.cancel_error = KompasOSError(
        "already claimed", user_message="Elan bu arada tutulub."
    )
    context = _Context(
        open_shifts, stores={str(STORE): "Mərkəz"}, work_modes={WORK_MODE: _work_mode()}
    )
    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)
    ShiftMatrixOpenShiftController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("səbəb", True))
    )

    _click(screen, "Ləğv Et")  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"


@requires_qt
def test_admin_list_read_failure_shows_an_error_instead_of_a_blank_screen(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.open_shift import ShiftMatrixOpenShiftController
    from src.presentation.screens.group_c import ShiftPlanningScreen

    open_shifts = _OpenShifts()
    open_shifts.admin_list_error = KompasOSError("db down", user_message="Baza əlaqəsi kəsildi.")
    context = _Context(open_shifts)
    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)

    ShiftMatrixOpenShiftController(context, _Actor()).attach(screen)  # type: ignore[arg-type]  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"
