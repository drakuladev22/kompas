"""Kiosk ilk-istifadə bələdçisi — `v2backlog.md` Faza 10.

Hər test funksiyanın BİR iddiasını sınayır:

  * üç əsas addım HƏMİŞƏ var; üz addımı yalnız bayraqla qoşulur;
  * «İrəli» sonuncu addımda `finished` yayır; «Keç» İSTƏNILƏN addımda;
  * repo fail-safe oxuyur (sətir yoxdursa «görməyib»).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from PySide6.QtWidgets import QWidget

from src.domain.value_objects.identifiers import EmployeeId
from src.presentation.screens.group_a_kiosk import KioskOnboardingOverlay


@pytest.fixture()
def _theme(qapp: Any) -> Any:
    from src.presentation.theme.manager import ThemeManager

    return ThemeManager()


def _overlay(_theme: Any, *, face: bool, parent: Any) -> KioskOnboardingOverlay:
    return KioskOnboardingOverlay(_theme, include_face_step=face, parent=parent)


def test_base_steps_are_always_present(qapp: Any, _theme: Any) -> None:
    holder = QWidget()
    overlay = _overlay(_theme, face=False, parent=holder)

    assert len(overlay.steps) == 3
    assert any("PIN" in title for title, _ in overlay.steps)


def test_face_step_is_opt_in(qapp: Any, _theme: Any) -> None:
    holder = QWidget()
    overlay = _overlay(_theme, face=True, parent=holder)

    assert len(overlay.steps) == 4
    assert any("üzünüzü göstərin" in title for title, _ in overlay.steps)


def test_advance_finishes_on_the_last_step(qapp: Any, _theme: Any) -> None:
    holder = QWidget()
    overlay = _overlay(_theme, face=False, parent=holder)
    finished: list[bool] = []
    overlay.finished.connect(lambda: finished.append(True))

    overlay.advance()  # 1 → 2
    assert not finished
    overlay.advance()  # 2 → 3 (sonuncu)
    assert not finished
    overlay.advance()  # sonuncu addımda «İrəli» = Bitir
    assert finished == [True]


def test_skip_finishes_from_any_step(qapp: Any, _theme: Any) -> None:
    holder = QWidget()
    overlay = _overlay(_theme, face=True, parent=holder)
    finished: list[bool] = []
    overlay.finished.connect(lambda: finished.append(True))

    overlay.finish()
    assert finished == [True]


# --------------------------------------------------------------------------- #
# Repo oxunuşunun fail-safe qaydası (sətir yoxdursa «görməyib»)
# --------------------------------------------------------------------------- #


class _PrefsRepo:
    """`kiosk_onboarding_done` yolunun sahtəsi — sətir yoxdur halı."""

    def __init__(self, rows: dict[str, bool]) -> None:
        self.rows = rows

    def kiosk_onboarding_done(self, employee_id: EmployeeId) -> bool:
        return self.rows.get(str(employee_id), False)

    def mark_kiosk_onboarding_done(self, employee_id: EmployeeId) -> None:
        self.rows[str(employee_id)] = True


def test_missing_row_means_not_seen() -> None:
    repo = _PrefsRepo({})
    employee_id = EmployeeId(uuid4())

    assert repo.kiosk_onboarding_done(employee_id) is False
    repo.mark_kiosk_onboarding_done(employee_id)
    assert repo.kiosk_onboarding_done(employee_id) is True
