"""`AttritionRiskScreen` ↔ `AttritionRiskController` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, ikinci beşlik)
──────────────────────────────────────────────────────────────────────────────
`controllers/attrition_risk.py` `tests/` daxilində HEÇ YERDƏ adı çəkilmirdi.
YALNIZ-OXU ekrandır (yazı yolu yoxdur), ona görə burada diqqət ekstremal
OXU məlumatına yönəlir: boş data, sıfır sətir, malformed/uzun dəyərlər —
ekran çökmür ki, "Yenilə" düyməsi real işləyirmi?
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import date
from typing import Any

import pytest

from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()
EMPLOYEE_ID = uuid.uuid4()


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


def _score(
    *,
    employee_id: Any = EMPLOYEE_ID,
    score: float = 62.0,
    is_high_risk: bool = True,
    factors: dict[str, dict[str, object]] | None = None,
) -> Any:
    from src.application.use_cases.attrition_risk import AttritionRiskScoreView

    return AttritionRiskScoreView(
        employee_id=employee_id,
        score=score,
        is_high_risk=is_high_risk,
        factors=factors if factors is not None else {"LATE_STREAK": {"izah": "Ardıcıl gecikmə"}},
        score_date=date(2026, 8, 20),
    )


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _Row(dict):
    pass


class _Connection:
    def __init__(self, employees: dict[str, tuple[str, str, str]]) -> None:
        self._employees = employees

    def execute(self, _sql: str, params: Any = None) -> _Connection:
        self._params = params
        return self

    def fetchall(self) -> list[_Row]:
        if not self._params:
            return []
        requested_ids = {str(eid) for eid in self._params[-1]}
        return [
            _Row(id=eid, first_name=first, last_name=last, store_name=store)
            for eid, (first, last, store) in self._employees.items()
            if eid in requested_ids
        ]


class _Uow:
    def __init__(self, employees: dict[str, tuple[str, str, str]]) -> None:
        self.connection = _Connection(employees)


class _AttritionRisk:
    def __init__(self) -> None:
        self.rows: list[Any] = []
        self.error: KompasOSError | None = None

    def list_for_tenant(self, *, tenant_id: Any, actor: Any) -> list[Any]:
        if self.error is not None:
            raise self.error
        return list(self.rows)


class _Session:
    def __init__(
        self, attrition_risk: _AttritionRisk, employees: dict[str, tuple[str, str, str]]
    ) -> None:
        self.tenant_id = TENANT
        self.attrition_risk = attrition_risk
        self.uow = _Uow(employees)


class _Context:
    def __init__(
        self,
        attrition_risk: _AttritionRisk,
        employees: dict[str, tuple[str, str, str]] | None = None,
    ) -> None:
        self._attrition_risk = attrition_risk
        self._employees = employees or {}

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        yield _Session(self._attrition_risk, self._employees)


class _Actor:
    id = ACTOR_ID


# --------------------------------------------------------------------------- #
# 1. Real "Yenilə" kliki — boş/dolu/xəta halları
# --------------------------------------------------------------------------- #


@requires_qt
def test_attach_populates_the_real_table_from_the_use_case(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.attrition_risk import AttritionRiskController
    from src.presentation.screens.attrition_risk import AttritionRiskScreen

    attrition_risk = _AttritionRisk()
    attrition_risk.rows = [_score()]
    context = _Context(attrition_risk, {str(EMPLOYEE_ID): ("Aygün", "Məmmədova", "Mərkəz")})
    screen = AttritionRiskScreen(theme)
    qtbot.addWidget(screen)

    AttritionRiskController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    assert screen._summary.text() == "1 işçi — 1 yüksək riskdə"


@requires_qt
def test_clicking_refresh_reloads_the_real_list(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.attrition_risk import AttritionRiskController
    from src.presentation.screens.attrition_risk import AttritionRiskScreen

    attrition_risk = _AttritionRisk()
    context = _Context(attrition_risk, {str(EMPLOYEE_ID): ("Aygün", "Məmmədova", "Mərkəz")})
    screen = AttritionRiskScreen(theme)
    qtbot.addWidget(screen)
    AttritionRiskController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    # İlk yükləmə boş idi (ekran "boş" vəziyyətindədir) — sonra data gəlir.
    attrition_risk.rows = [_score(is_high_risk=False)]
    _click(screen, "Yenilə")

    assert screen._summary.text() == "1 işçi — 0 yüksək riskdə"


@requires_qt
def test_zero_rows_shows_the_real_empty_state_not_a_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.attrition_risk import AttritionRiskController
    from src.presentation.screens.attrition_risk import AttritionRiskScreen

    attrition_risk = _AttritionRisk()
    context = _Context(attrition_risk)
    screen = AttritionRiskScreen(theme)
    qtbot.addWidget(screen)

    AttritionRiskController(context, _Actor()).attach(screen)  # type: ignore[arg-type]  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "empty"


@requires_qt
def test_read_failure_shows_an_error_instead_of_a_blank_screen(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.attrition_risk import AttritionRiskController
    from src.presentation.screens.attrition_risk import AttritionRiskScreen

    attrition_risk = _AttritionRisk()
    attrition_risk.error = KompasOSError("db down", user_message="Baza əlaqəsi kəsildi.")
    context = _Context(attrition_risk)
    screen = AttritionRiskScreen(theme)
    qtbot.addWidget(screen)

    AttritionRiskController(context, _Actor()).attach(screen)  # type: ignore[arg-type]  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"


@requires_qt
def test_an_unexpected_exception_falls_back_to_the_generic_message(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.controllers.attrition_risk import AttritionRiskController
    from src.presentation.screens.attrition_risk import AttritionRiskScreen

    attrition_risk = _AttritionRisk()
    attrition_risk.error = RuntimeError("boom")  # type: ignore[assignment]
    context = _Context(attrition_risk)
    screen = AttritionRiskScreen(theme)
    qtbot.addWidget(screen)

    AttritionRiskController(context, _Actor()).attach(screen)  # type: ignore[arg-type]  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 2. Ekstremal/malformed data — REAL cədvəldə çökmür
# --------------------------------------------------------------------------- #


@requires_qt
def test_an_employee_missing_from_the_lookup_falls_back_to_the_raw_id(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """İşçi sətri silinmiş/köçürülmüş ola bilər — `_employee_labels` onu tapmır."""
    from src.presentation.controllers.attrition_risk import AttritionRiskController
    from src.presentation.screens.attrition_risk import AttritionRiskScreen

    attrition_risk = _AttritionRisk()
    attrition_risk.rows = [_score()]
    context = _Context(attrition_risk, employees={})  # BOŞ axtarış cədvəli
    screen = AttritionRiskScreen(theme)
    qtbot.addWidget(screen)

    AttritionRiskController(context, _Actor()).attach(screen)  # type: ignore[arg-type]  # ÇÖKMƏMƏLİDİR

    assert screen._summary.text() == "1 işçi — 1 yüksək riskdə"


@requires_qt
def test_an_extremely_long_factor_explanation_and_emoji_do_not_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`factors_text` sərbəst mətndir — ekran onu MƏZMUNCA yoxlamır, sadəcə göstərir."""
    from src.presentation.controllers.attrition_risk import AttritionRiskController
    from src.presentation.screens.attrition_risk import AttritionRiskScreen

    hostile = "🔥" * 200 + "'; DROP TABLE employees; --" + "A" * 10_000
    attrition_risk = _AttritionRisk()
    attrition_risk.rows = [_score(factors={"LATE_STREAK": {"izah": hostile}})]
    context = _Context(attrition_risk, {str(EMPLOYEE_ID): ("Aygün", "Məmmədova", "Mərkəz")})
    screen = AttritionRiskScreen(theme)
    qtbot.addWidget(screen)

    AttritionRiskController(context, _Actor()).attach(screen)  # type: ignore[arg-type]  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "content"


@requires_qt
def test_the_score_cap_signal_is_excluded_from_the_displayed_factors(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`_SCORE_CAP_SIGNAL` istisna edilir — `_to_row` başlığındakı qayda REAL cədvəldə."""
    from src.presentation.controllers.attrition_risk import AttritionRiskController
    from src.presentation.screens.attrition_risk import AttritionRiskScreen

    attrition_risk = _AttritionRisk()
    attrition_risk.rows = [
        _score(
            factors={
                "SCORE_CAP": {"izah": "Bal 100-də kəsilib"},
                "LATE_STREAK": {"izah": "Ardıcıl gecikmə"},
            }
        )
    ]
    context = _Context(attrition_risk, {str(EMPLOYEE_ID): ("Aygün", "Məmmədova", "Mərkəz")})
    screen = AttritionRiskScreen(theme)
    qtbot.addWidget(screen)

    AttritionRiskController(context, _Actor()).attach(screen)  # type: ignore[arg-type]

    from PySide6.QtWidgets import QLabel

    labels = [label.text() for label in screen.findChildren(QLabel)]
    assert any("Ardıcıl gecikmə" in text for text in labels)
    assert not any("100-də kəsilib" in text for text in labels)


@requires_qt
def test_a_factor_payload_with_no_explanation_key_does_not_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`payload.get("izah")` boşdursa sətir sadəcə keçilir — `KeyError` YOX."""
    from src.presentation.controllers.attrition_risk import AttritionRiskController
    from src.presentation.screens.attrition_risk import AttritionRiskScreen

    attrition_risk = _AttritionRisk()
    attrition_risk.rows = [_score(factors={"MALFORMED": "gözlənilməz sətir dəyəri"})]
    context = _Context(attrition_risk, {str(EMPLOYEE_ID): ("Aygün", "Məmmədova", "Mərkəz")})
    screen = AttritionRiskScreen(theme)
    qtbot.addWidget(screen)

    AttritionRiskController(context, _Actor()).attach(screen)  # type: ignore[arg-type]  # ÇÖKMƏMƏLİDİR

    assert screen.switcher().current_state() == "content"
