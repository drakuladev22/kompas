"""`UsersScreen`/`PosThresholdDialog` ↔ `controllers/pos_threshold.py` — REAL Qt e2e.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, ikinci beşlik)
──────────────────────────────────────────────────────────────────────────────
`controllers/pos_threshold.py` `tests/` daxilində HEÇ YERDƏ adı çəkilmirdi
(3 yazı yolu: `set_threshold`, `revoke_threshold` + hər əməliyyatdan ƏVVƏLKİ
oxu — hamısı `.commit()` çağırır). Burada REAL `UsersScreen`-in "···" menyusu,
REAL `PosThresholdDialog` və REAL "Yadda Saxla"/"Geri Al" düymələri sınanır.

HƏDD DƏYƏRİ: `PosThresholdDialog._on_submit()` YALNIZ boş sahəni yoxlayır —
`Decimal` çevrilməsi (və mənfi/sıfır/kəsr/nəhəng/mətn ayırd etməsi) TAMAMİLƏ
`controllers/pos_threshold.py::_save`-dədir. Aşağıda hər ssenari REAL "Yadda
Saxla" kliki ilə, dialoqun ÖZ mətn sahəsinə real yazılaraq sınanır.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, ClassVar

import pytest

from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()
EMPLOYEE_ID = uuid.uuid4()
FULL_NAME = "Aygün Məmmədova"


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _user_row(full_name: str = FULL_NAME) -> dict[str, str]:
    return {"full_name": full_name, "username": "aygun.m", "role": "Satıcı", "store": "Mərkəz"}


def _trigger_menu_action(screen: Any, label: str) -> None:
    from PySide6.QtWidgets import QPushButton

    ellipsis = next(b for b in screen.findChildren(QPushButton) if b.text() == "···")
    menu = ellipsis.menu()
    action = next(a for a in menu.actions() if a.text() == label)
    action.trigger()


class _FakeThreshold:
    def __init__(
        self,
        *,
        max_discount_pct: Decimal = Decimal("10"),
        can_void: bool = False,
        can_refund: bool = False,
        note: str | None = "",
        is_active: bool = True,
    ) -> None:
        self.max_discount_pct = max_discount_pct
        self.can_void = can_void
        self.can_refund = can_refund
        self.note = note
        self.is_active = is_active


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _Row(dict):
    pass


class _Connection:
    def __init__(self, employees: list[tuple[str, str, str]]) -> None:
        self._employees = employees

    def execute(self, _sql: str, _params: Any = None) -> _Connection:
        return self

    def fetchall(self) -> list[_Row]:
        return [
            _Row(id=eid, first_name=first, last_name=last) for eid, first, last in self._employees
        ]


class _Subject:
    """`session.uow.employees.get(...)`-in qaytardığı obyekt — `_save`/`_revoke` yalnız keçirir."""


class _EmployeesRepo:
    def __init__(self, subject: Any) -> None:
        self._subject = subject

    def get(self, _employee_id: Any) -> Any:
        return self._subject


class _Uow:
    def __init__(self, employees: list[tuple[str, str, str]], subject: Any) -> None:
        self.connection = _Connection(employees)
        self.employees = _EmployeesRepo(subject)


class _PosThreshold:
    def __init__(self) -> None:
        self.existing: Any = None
        self.sets: list[dict[str, Any]] = []
        self.revokes: list[dict[str, Any]] = []
        self.set_error: KompasOSError | None = None
        self.revoke_error: KompasOSError | None = None

    def get_threshold(self, *, tenant_id: Any, actor: Any, employee_id: Any) -> Any:
        return self.existing

    def set_threshold(self, *, tenant_id: Any, actor: Any, subject: Any, draft: Any) -> None:
        if self.set_error is not None:
            raise self.set_error
        self.sets.append({"subject": subject, "draft": draft})

    def revoke_threshold(self, *, tenant_id: Any, actor: Any, subject: Any) -> None:
        if self.revoke_error is not None:
            raise self.revoke_error
        self.revokes.append({"subject": subject})


class _Limits:
    def get_str(self, _tenant_id: Any, _key: str, fallback: str) -> str:
        return "50"


class _Session:
    def __init__(
        self,
        pos_threshold: _PosThreshold,
        employees: list[tuple[str, str, str]],
        subject: Any,
    ) -> None:
        self.tenant_id = TENANT
        self.pos_threshold = pos_threshold
        self.limits = _Limits()
        self.uow = _Uow(employees, subject)
        self.committed = False

    def commit(self) -> None:
        self.committed = True


_UNSET: Any = object()


class _Context:
    def __init__(
        self,
        pos_threshold: _PosThreshold,
        *,
        employees: list[tuple[str, str, str]] | None = None,
        subject: Any = _UNSET,
    ) -> None:
        self._pos_threshold = pos_threshold
        self._employees = (
            employees if employees is not None else [(str(EMPLOYEE_ID), "Aygün", "Məmmədova")]
        )
        # `subject=None` QƏSDƏN dəstəklənir (`_save`/`_revoke`-in "işçi silinib"
        # qolunu sınamaq üçün) — ona görə defolt `None` YOX, ayrıca sentineldir.
        self._subject = _Subject() if subject is _UNSET else subject
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(self._pos_threshold, self._employees, self._subject)
        self.sessions.append(created)
        yield created


class _Actor:
    id = ACTOR_ID


class _Binder:
    populated: ClassVar[list[str]] = []

    def __init__(self, context: Any, actor: Any) -> None:
        pass

    def populate(self, key: str, _screen: Any) -> None:
        _Binder.populated.append(key)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.presentation.controllers import screen_data as screen_data_module

    _Binder.populated = []
    monkeypatch.setattr(screen_data_module, "ScreenDataBinder", _Binder)


def _attach(context: Any, theme: Any, *, qtbot: Any) -> Any:
    from src.presentation.controllers.pos_threshold import UsersPOSThresholdController
    from src.presentation.screens.group_c import UsersScreen

    screen = UsersScreen(theme)
    qtbot.addWidget(screen)
    screen.set_users([_user_row()])
    UsersPOSThresholdController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    return screen


def _patched_dialog_exec(monkeypatch: pytest.MonkeyPatch, *, pct_text: str) -> None:
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_c import PosThresholdDialog

    def fake_exec(self: PosThresholdDialog) -> int:
        self._pct.set_text(pct_text)
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Yadda Saxla")
        submit.click()
        return 0

    monkeypatch.setattr(PosThresholdDialog, "exec", fake_exec)


# --------------------------------------------------------------------------- #
# 1. Real "···" → "POS Səlahiyyəti" → real dialoq
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_real_menu_action_opens_the_dialog_prefilled_with_the_existing_value(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_c import PosThresholdDialog

    pos_threshold = _PosThreshold()
    pos_threshold.existing = _FakeThreshold(max_discount_pct=Decimal("22.5"), can_void=True)
    context = _Context(pos_threshold)
    screen = _attach(context, theme, qtbot=qtbot)

    captured: list[PosThresholdDialog] = []
    original_init = PosThresholdDialog.__init__

    def _spy_init(self: PosThresholdDialog, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        captured.append(self)

    monkeypatch.setattr(PosThresholdDialog, "__init__", _spy_init)
    monkeypatch.setattr(PosThresholdDialog, "exec", lambda self: 0)

    _trigger_menu_action(screen, "POS Səlahiyyəti")

    assert len(captured) == 1
    dialog = captured[0]
    assert dialog._pct.text() == "22.5"
    assert dialog._void.isChecked()
    assert "Geri Al" in [b.text() for b in dialog.findChildren(QPushButton)]


@requires_qt
def test_no_existing_threshold_hides_the_revoke_button(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_c import PosThresholdDialog

    context = _Context(_PosThreshold())
    screen = _attach(context, theme, qtbot=qtbot)

    captured: list[PosThresholdDialog] = []
    original_init = PosThresholdDialog.__init__

    def _spy_init(self: PosThresholdDialog, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        captured.append(self)

    monkeypatch.setattr(PosThresholdDialog, "__init__", _spy_init)
    monkeypatch.setattr(PosThresholdDialog, "exec", lambda self: 0)

    _trigger_menu_action(screen, "POS Səlahiyyəti")

    assert "Geri Al" not in [b.text() for b in captured[0].findChildren(QPushButton)]


@requires_qt
def test_an_employee_not_found_shows_an_error_and_does_not_open_the_dialog(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    context = _Context(_PosThreshold(), employees=[])
    screen = _attach(context, theme, qtbot=qtbot)

    _trigger_menu_action(screen, "POS Səlahiyyəti")  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 2. Hədd dəyəri — real "Yadda Saxla" ilə mənfi/sıfır/kəsr/nəhəng/mətn/boş
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_valid_decimal_via_the_real_field_commits_and_refreshes(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    pos_threshold = _PosThreshold()
    context = _Context(pos_threshold)
    screen = _attach(context, theme, qtbot=qtbot)

    _patched_dialog_exec(monkeypatch, pct_text="15.5")
    _trigger_menu_action(screen, "POS Səlahiyyəti")

    assert len(pos_threshold.sets) == 1
    assert pos_threshold.sets[0]["draft"].max_discount_pct == Decimal("15.5")
    assert any(s.committed for s in context.sessions)
    assert "users" in _Binder.populated


@requires_qt
def test_a_comma_decimal_separator_is_accepted(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Azərbaycan istifadəçisi onluq ayırıcı kimi vergül yaza bilər."""
    pos_threshold = _PosThreshold()
    context = _Context(pos_threshold)
    screen = _attach(context, theme, qtbot=qtbot)

    _patched_dialog_exec(monkeypatch, pct_text="15,5")
    _trigger_menu_action(screen, "POS Səlahiyyəti")

    assert pos_threshold.sets[0]["draft"].max_discount_pct == Decimal("15.5")


@requires_qt
def test_a_negative_value_is_not_blocked_by_the_ui_and_reaches_the_use_case(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Mənfi ədəd HƏDD YOXLAMASI DEYİL — UI Decimal kimi parçalayır, sərhədi domen qoyur."""
    pos_threshold = _PosThreshold()
    context = _Context(pos_threshold)
    screen = _attach(context, theme, qtbot=qtbot)

    _patched_dialog_exec(monkeypatch, pct_text="-5")
    _trigger_menu_action(screen, "POS Səlahiyyəti")  # ÇÖKMƏMƏLİDİR

    assert len(pos_threshold.sets) == 1
    assert pos_threshold.sets[0]["draft"].max_discount_pct == Decimal("-5")


@requires_qt
def test_zero_is_a_valid_decimal_and_reaches_the_use_case(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    pos_threshold = _PosThreshold()
    context = _Context(pos_threshold)
    screen = _attach(context, theme, qtbot=qtbot)

    _patched_dialog_exec(monkeypatch, pct_text="0")
    _trigger_menu_action(screen, "POS Səlahiyyəti")

    assert pos_threshold.sets[0]["draft"].max_discount_pct == Decimal("0")


@requires_qt
def test_an_enormous_value_does_not_crash_the_decimal_parser(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    pos_threshold = _PosThreshold()
    context = _Context(pos_threshold)
    screen = _attach(context, theme, qtbot=qtbot)

    huge = "9" * 50
    _patched_dialog_exec(monkeypatch, pct_text=huge)
    _trigger_menu_action(screen, "POS Səlahiyyəti")  # ÇÖKMƏMƏLİDİR

    assert pos_threshold.sets[0]["draft"].max_discount_pct == Decimal(huge)


@requires_qt
def test_non_numeric_text_is_rejected_with_a_real_error_and_writes_nothing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    pos_threshold = _PosThreshold()
    context = _Context(pos_threshold)
    screen = _attach(context, theme, qtbot=qtbot)

    _patched_dialog_exec(monkeypatch, pct_text="on beş faiz")
    _trigger_menu_action(screen, "POS Səlahiyyəti")  # ÇÖKMƏMƏLİDİR

    assert pos_threshold.sets == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_sql_like_text_is_rejected_as_a_bad_decimal_not_executed(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    pos_threshold = _PosThreshold()
    context = _Context(pos_threshold)
    screen = _attach(context, theme, qtbot=qtbot)

    _patched_dialog_exec(monkeypatch, pct_text="1; DROP TABLE pos_permission_thresholds; --")
    _trigger_menu_action(screen, "POS Səlahiyyəti")  # ÇÖKMƏMƏLİDİR

    assert pos_threshold.sets == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_an_empty_field_is_rejected_by_the_real_dialog_before_any_write(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_c import PosThresholdDialog

    pos_threshold = _PosThreshold()
    context = _Context(pos_threshold)
    screen = _attach(context, theme, qtbot=qtbot)

    def fake_exec(self: PosThresholdDialog) -> int:
        self._pct.set_text("")
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Yadda Saxla")
        submit.click()
        assert self._pct.has_error
        return self.reject()

    monkeypatch.setattr(PosThresholdDialog, "exec", fake_exec)

    _trigger_menu_action(screen, "POS Səlahiyyəti")

    assert pos_threshold.sets == []


# --------------------------------------------------------------------------- #
# 3. Real "Geri Al" — real klik, use-case istisnası
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_revoke_on_the_real_button_commits_and_refreshes(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_c import PosThresholdDialog

    pos_threshold = _PosThreshold()
    pos_threshold.existing = _FakeThreshold()
    context = _Context(pos_threshold)
    screen = _attach(context, theme, qtbot=qtbot)

    def fake_exec(self: PosThresholdDialog) -> int:
        revoke = next(b for b in self.findChildren(QPushButton) if b.text() == "Geri Al")
        revoke.click()
        return 0

    monkeypatch.setattr(PosThresholdDialog, "exec", fake_exec)

    _trigger_menu_action(screen, "POS Səlahiyyəti")

    assert len(pos_threshold.revokes) == 1
    assert any(s.committed for s in context.sessions)
    assert "users" in _Binder.populated


@requires_qt
def test_set_threshold_failure_shows_the_domain_message_and_does_not_commit(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Self-Escalation Guard / Strict Hierarchy Guard rəddi — real klik AÇIQ mesaj göstərir."""
    pos_threshold = _PosThreshold()
    pos_threshold.set_error = KompasOSError(
        "self escalation", user_message="Özünüzə səlahiyyət verə bilməzsiniz."
    )
    context = _Context(pos_threshold)
    screen = _attach(context, theme, qtbot=qtbot)

    _patched_dialog_exec(monkeypatch, pct_text="15")
    _trigger_menu_action(screen, "POS Səlahiyyəti")  # ÇÖKMƏMƏLİDİR

    # `_open_dialog()`-un ÖZ oxu sessiyası ayrıca commit edir (yazı DEYİL) —
    # əsl yoxlama budur ki, heç bir hədd YAZILMAYIB.
    assert pos_threshold.sets == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_the_subject_disappearing_between_open_and_save_shows_a_real_error(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """İşçi dialoq AÇIQ ikən deaktiv edilib/silinib —
    `session.uow.employees.get` `None` qaytarır."""
    pos_threshold = _PosThreshold()
    context = _Context(pos_threshold, subject=None)
    screen = _attach(context, theme, qtbot=qtbot)

    _patched_dialog_exec(monkeypatch, pct_text="15")
    _trigger_menu_action(screen, "POS Səlahiyyəti")  # ÇÖKMƏMƏLİDİR

    assert pos_threshold.sets == []
    assert screen.switcher().current_state() == "error"
