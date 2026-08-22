"""`DashboardBuilderScreen` ↔ `DashboardBuilderController` — REAL Qt e2e.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, üçüncü beşlik — "dashboard_builder")
──────────────────────────────────────────────────────────────────────────────
`test_phase56_write_controllers.py` `DashboardBuilderController`-i duck-typing
sahtəsi ilə ölçür — REAL `WidgetRow` (aç/gizlət açarı, yuxarı/aşağı düymələri,
sütun/en seçiciləri) heç vaxt qurulmur. Burada onlar REAL kliklə sınanır.

──────────────────────────────────────────────────────────────────────────────
TAPILMIŞ VƏ DÜZƏLDİLMİŞ QÜSUR — `_write()`-in xəta qolu UI-R4-01-i POZURDU
──────────────────────────────────────────────────────────────────────────────
Bu fayl İLK yazıldığı zaman `controllers/dashboard_builder.py::_write()`
xəta qolunda `screen.show_error(title=..., message=...)` çağırırdı —
`on_retry` OLMADAN. `screens/base.py::Screen.show_error` (UI-R4-01) `on_retry`
verilməyəndə "Yenidən Cəhd Et" düyməsini ÜMUMİYYƏTLƏ ÇƏKMİR; layihə-boyu 15+
oxşar kontroller (`plugin_admin.py`, `profile.py`, `tasks.py`, s.) bunu
ötürürdü, `dashboard_builder.py` isə YOX. Nəticə: yazı uğursuz olanda
istifadəçi "Yenidən Cəhd Et"siz tam ekran xətasında qalırdı. `ui-fixes`-ə
bildirildi və O, `on_retry=lambda: self.refresh(screen)` əlavə edərək
DÜZƏLTDİ (bax `dashboard_builder.py::_write` başlığındakı "QA-FULL FAZA 3
tapıntısı" qeydi). Aşağıdakı testlər İNDİ düzəldilmiş, DOĞRU davranışı
yoxlayır — bax 3-cü bölmə.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any

import pytest

from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()


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


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _View:
    def __init__(
        self, order: tuple[str, ...] = ("attendance", "fines"), *, columns: int = 1
    ) -> None:
        self.order = order
        self.visible = frozenset(order)
        self.columns = columns

    def catalog_map(self) -> dict[str, tuple[str, str]]:
        return {key: (key.title(), f"{key} izahı") for key in self.order}

    def placement_map(self) -> dict[str, tuple[int, int, int]]:
        return {key: (row, 0, self.columns) for row, key in enumerate(self.order)}


class _LayoutUseCase:
    def __init__(
        self,
        *,
        view: _View | None = None,
        save_error: Exception | None = None,
        reset_error: Exception | None = None,
    ) -> None:
        self._view = view or _View()
        self.saved: list[list[str]] = []
        self.resets = 0
        self.save_error = save_error
        self.reset_error = reset_error

    def view_for(self, *, actor: Any, tenant_id: Any) -> _View:
        return self._view

    def save(self, *, actor: Any, tenant_id: Any, layout: list[str]) -> _View:
        if self.save_error is not None:
            raise self.save_error
        self.saved.append(list(layout))
        self._view = _View(tuple(layout), columns=self._view.columns)
        return self._view

    def reset(self, *, actor: Any, tenant_id: Any) -> _View:
        if self.reset_error is not None:
            raise self.reset_error
        self.resets += 1
        self._view = _View(("attendance", "fines"), columns=self._view.columns)
        return self._view


class _Session:
    def __init__(self, use_case: _LayoutUseCase) -> None:
        self.tenant_id = TENANT
        self.dashboard_layout = use_case
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(self, use_case: _LayoutUseCase) -> None:
        self._use_case = use_case
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(self._use_case)
        self.sessions.append(created)
        yield created


class _Actor:
    id = ACTOR_ID


def _attach(context: Any, theme: Any, *, qtbot: Any) -> Any:
    from src.presentation.controllers.dashboard_builder import DashboardBuilderController
    from src.presentation.screens.group_i import DashboardBuilderScreen

    screen = DashboardBuilderScreen(theme)
    qtbot.addWidget(screen)
    DashboardBuilderController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    return screen


# --------------------------------------------------------------------------- #
# 1. Real toggle/yuxarı-aşağı — uğurlu yazı
# --------------------------------------------------------------------------- #


@requires_qt
def test_toggling_a_real_switch_off_writes_and_re_reads(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    use_case = _LayoutUseCase()
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    row = next(r for r in screen._rows if r.key == "fines")
    row._toggle.setChecked(False)  # REAL ToggleSwitch klikinin yerini tutur

    assert use_case.saved == [["attendance"]]  # "fines" artıq görünmür
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_moving_the_top_row_up_is_a_silent_no_op_not_a_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Sərhəddən kənar hərəkət XƏTA DEYİL (bax `_on_moved` şərhi) — SƏSSİZ effektsiz."""
    from PySide6.QtWidgets import QPushButton

    use_case = _LayoutUseCase()
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    first_row = screen._rows[0]
    up_button = next(b for b in first_row.findChildren(QPushButton) if b.toolTip() == "Yuxarı")
    up_button.click()  # ÇÖKMƏMƏLİDİR

    assert use_case.saved == []  # sıra dəyişmədi, ona görə yazı da baş vermədi
    assert [row.key for row in screen._rows] == ["attendance", "fines"]


@requires_qt
def test_moving_the_bottom_row_down_reorders_and_writes(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    use_case = _LayoutUseCase()
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    top_row = screen._rows[0]
    down_button = next(b for b in top_row.findChildren(QPushButton) if b.toolTip() == "Aşağı")
    down_button.click()

    assert use_case.saved == [["fines", "attendance"]]
    assert [row.key for row in screen._rows] == ["fines", "attendance"]


@requires_qt
def test_clicking_reset_uses_the_real_button_and_the_use_case_default(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    use_case = _LayoutUseCase()
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    _click(screen, "Defolta qaytar")

    assert use_case.resets == 1
    assert use_case.saved == []  # `reset()` AYRI yoldur, `save()` ÇAĞIRILMIR


# --------------------------------------------------------------------------- #
# 2. Şəbəkə seçiciləri (G-5) — real QComboBox dəyişikliyi
# --------------------------------------------------------------------------- #


@requires_qt
def test_changing_the_real_column_selector_writes_a_placement_encoded_key(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    view = _View(("attendance", "fines"), columns=2)
    use_case = _LayoutUseCase(view=view)
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    row = next(r for r in screen._rows if r.key == "attendance")
    assert row._column_box is not None, "columns > 1 olduqda seçici QURULMALIDIR"
    row._column_box.setCurrentIndex(1)  # sütun 2

    assert use_case.saved, "Seçici dəyişikliyi yazı yoluna çatmalıdır"
    encoded_key = next(k for k in use_case.saved[-1] if k.startswith("attendance"))
    # `PLACEMENT_SEPARATOR` = "@", format `açar@sətir,sütun,en` (bax
    # `current_layout()` şərhi) — sütun 1-ə köçürüldüyü üçün en avtomatik
    # sıxılır (2 sütunlu şəbəkədə 1-ci sütundan başlayan en 1-dən çox ola bilməz).
    assert encoded_key == "attendance@0,1,1"


# --------------------------------------------------------------------------- #
# 3. Yazı uğursuzluğu — `on_retry` REAL düyməni işlək saxlayır (DÜZƏLDİLİB)
# --------------------------------------------------------------------------- #
#
# QA-FULL Faza 3 (bu fayl) bu bölmədə əvvəlcə real bir qüsur tapmışdı:
# `_write()`-in xəta qolu `on_retry` ÖTÜRMÜRDÜ, ona görə UI-R4-01 qaydasınca
# "Yenidən Cəhd Et" düyməsi ÜMUMİYYƏTLƏ ÇƏKİLMİRDİ — istifadəçi tam ekran
# xətasında "ölü dalan"da qalırdı. `ui-fixes` bunu `on_retry=lambda: self.
# refresh(screen)` əlavə edərək DÜZƏLTDİ (bax `dashboard_builder.py::_write`
# başlığı, "QA-FULL FAZA 3 tapıntısı"). Aşağıdakı iki test İNDİ düzəlişdən
# SONRAKI DOĞRU davranışı yoxlayır: düymə VAR, REAL kliklənir və REAL
# yenidən-oxumanı başladır.


@requires_qt
def test_a_save_failure_shows_a_real_working_retry_button(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    use_case = _LayoutUseCase(
        save_error=KompasOSError(
            "flag yoxdur", user_message="Bu əməliyyat üçün səlahiyyətiniz yoxdur."
        )
    )
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    row = next(r for r in screen._rows if r.key == "fines")
    row._toggle.setChecked(False)  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"

    # Növbəti "Yenidən Cəhd Et" kliki UĞURLU `refresh()` başlatmalıdır —
    # xətanı aradan qaldırıb REAL düyməni basırıq.
    use_case.save_error = None
    _click(screen, "Yenidən Cəhd Et")

    assert screen.switcher().current_state() == "content"
    assert [row.key for row in screen._rows] == ["attendance", "fines"]


@requires_qt
def test_a_reset_failure_also_gets_a_real_working_retry_button(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    use_case = _LayoutUseCase(
        reset_error=KompasOSError("flag yoxdur", user_message="Səlahiyyətiniz yoxdur.")
    )
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    _click(screen, "Defolta qaytar")  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"

    use_case.reset_error = None
    _click(screen, "Yenidən Cəhd Et")

    assert screen.switcher().current_state() == "content"


@requires_qt
def test_an_unexpected_non_kompasos_failure_is_reported_generically(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    use_case = _LayoutUseCase(save_error=RuntimeError("connection lost"))
    context = _Context(use_case)
    screen = _attach(context, theme, qtbot=qtbot)

    row = next(r for r in screen._rows if r.key == "fines")
    row._toggle.setChecked(False)  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"
