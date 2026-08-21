"""`DashboardScreen` ↔ `controllers/screen_data.py::_dashboard` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, üçüncü beşlik)
──────────────────────────────────────────────────────────────────────────────
`dashboard` menyu açarı FLAG-SİZDİR — hər autentifikasiya olunmuş istifadəçi
görür. Səkkiz bölmənin ALTISI aqreqat sayğacdır (heç bir icazə yoxlaması
yoxdur — bu, QƏSDƏNDİR, çünki onlar hesab sayı/məbləği kimi ÜMUMİLƏŞDİRİLMİŞ
rəqəmlərdir). İKİSİ isə (`_dashboard_break_overuse`, `_dashboard_benchmark`)
AD-BAAD işçi məlumatı göstərir və ÖZ flag-lərini tələb edir
(`can_view_employee_reports`, `can_export_reports`) — "GÖRMƏK = SƏLAHİYYƏT"
BURADA REAL yoxlanılır: flag-siz aktor bu iki bölməni GÖRMƏLİDİRMİ?

Digər maddələr: ekstremal/malformed data (uzun mağaza adı, sıfır sətir) real
`BarChart`/`RankList`/kartlarda çökmə yaratmır ki? Bölmə-təcridi (bir sorğu
sınsa qalanları düzgün qalır) real widget-lə YOXLANILIR.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import pytest

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


class _Row(dict):
    pass


class _Connection:
    """SQL-i FİNGERPRİNT-ə görə yönləndirən sahtə — hər `_dashboard_*` bölməsi üçün."""

    def __init__(
        self,
        *,
        employee_count: int = 12,
        store_count: int = 3,
        fines_rows: list[_Row] | None = None,
        leaders_rows: list[_Row] | None = None,
        health_rows: list[_Row] | None = None,
        break_names: list[_Row] | None = None,
    ) -> None:
        self._employee_count = employee_count
        self._store_count = store_count
        self._fines_rows = fines_rows if fines_rows is not None else []
        self._leaders_rows = leaders_rows if leaders_rows is not None else []
        self._health_rows = health_rows if health_rows is not None else []
        self._break_names = break_names if break_names is not None else []
        self._last_sql = ""

    def execute(self, sql: str, _params: Any = None) -> _Connection:
        self._last_sql = sql
        return self

    def fetchone(self) -> _Row | None:
        sql = self._last_sql
        if "employee_count" in sql:
            return _Row(employee_count=self._employee_count, store_count=self._store_count)
        if "in_store" in sql:
            return _Row(
                in_store=4,
                planned=6,
                pending_entry=1,
                pending_return=0,
                oldest_entry=None,
                oldest_return=None,
                open_tasks=2,
                overdue_tasks=1,
            )
        if "used_minutes" in sql:
            return _Row(used_minutes=120, active_employees=self._employee_count)
        return None  # pragma: no cover

    def fetchall(self) -> list[_Row]:
        sql = self._last_sql
        if "SUM(f.amount)" in sql:
            return self._fines_rows
        if "points_ledger" in sql:
            return self._leaders_rows
        if "v_erp_server_health" in sql:
            return self._health_rows
        if "id, first_name, last_name" in sql:
            return self._break_names
        return []  # pragma: no cover


class _Limits:
    def get_int(self, _tenant_id: Any, _key: str, fallback: int) -> int:
        return fallback


class _BreakUsage:
    def __init__(self, employee_id: Any, warning: str) -> None:
        self.employee_id = employee_id
        self.allowance = type("_Allowance", (), {"warning_az": lambda self: warning})()


class _LeaveVerification:
    def __init__(self, usages: list[_BreakUsage] | None = None) -> None:
        self._usages = usages if usages is not None else []

    def break_overuse_for_day(self, *, tenant_id: Any, on_date: Any) -> list[_BreakUsage]:
        return list(self._usages)


class _MultiStoreBenchmark:
    """Minimal sahtə — YALNIZ bölmələrin GÖRÜNMƏ keçidini sınamaq üçün kifayətdir."""

    def ranking(self, **_kwargs: Any) -> list[Any]:
        return []

    def trend(self, **_kwargs: Any) -> list[Any]:
        return []

    def outliers(self, **_kwargs: Any) -> Any:
        return type("_Outliers", (), {"summary_text_az": "", "outliers": []})()

    def store_vs_network(
        self, **_kwargs: Any
    ) -> Any:  # pragma: no cover - boş `ranking`-də çağırılmır
        raise AssertionError("rows boşdursa çağırılmamalıdır")


class _Uow:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection


class _Session:
    def __init__(
        self,
        connection: _Connection,
        *,
        leave_verification: _LeaveVerification,
        multi_store_benchmark: _MultiStoreBenchmark,
        broken_section: str | None = None,
    ) -> None:
        self.tenant_id = TENANT
        self._connection = connection
        self._broken_section = broken_section
        self.uow = _Uow(_BrokenConnection(connection, broken_section))
        self.limits = _Limits()
        self.leave_verification = leave_verification
        self.multi_store_benchmark = multi_store_benchmark


class _BrokenConnection:
    """Verilmiş fingerprint-li sorğunu QƏSDƏN sındırır — bölmə-təcridini sınamaq üçün."""

    def __init__(self, real: _Connection, broken_fingerprint: str | None) -> None:
        self._real = real
        self._broken = broken_fingerprint

    def execute(self, sql: str, params: Any = None) -> Any:
        if self._broken is not None and self._broken in sql:
            raise RuntimeError("simulated query failure")
        return self._real.execute(sql, params)


class _Context:
    def __init__(
        self,
        *,
        connection: _Connection | None = None,
        leave_verification: _LeaveVerification | None = None,
        multi_store_benchmark: _MultiStoreBenchmark | None = None,
        broken_section: str | None = None,
    ) -> None:
        self._connection = connection if connection is not None else _Connection()
        self._leave_verification = leave_verification or _LeaveVerification()
        self._multi_store_benchmark = multi_store_benchmark or _MultiStoreBenchmark()
        self._broken_section = broken_section

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        yield _Session(
            self._connection,
            leave_verification=self._leave_verification,
            multi_store_benchmark=self._multi_store_benchmark,
            broken_section=self._broken_section,
        )


class _Actor:
    def __init__(self, flags: frozenset[str] = frozenset()) -> None:
        self.id = ACTOR_ID
        self._flags = flags

    def has_permission(self, flag: str, *, now: datetime) -> bool:
        return flag in self._flags


def _build_screen(theme: Any, qtbot: Any) -> Any:
    from src.presentation.screens.group_c import DashboardScreen

    screen = DashboardScreen(theme)
    qtbot.addWidget(screen)
    return screen


def _populate(context: Any, actor: Any, screen: Any) -> Any:
    from src.presentation.controllers.screen_data import ScreenDataBinder

    binder = ScreenDataBinder(context, actor)
    binder.populate("dashboard", screen)
    return binder


# --------------------------------------------------------------------------- #
# 1. Aqreqat bölmələr — real widget doldurulur, ekstremal data çökmə yaratmır
# --------------------------------------------------------------------------- #


@requires_qt
def test_network_size_populates_the_real_stat_tiles(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    context = _Context(connection=_Connection(employee_count=235, store_count=21))
    screen = _build_screen(theme, qtbot)

    _populate(context, _Actor(), screen)

    assert screen._employees._value.text() == "235"
    assert screen._stores._value.text() == "21"


@requires_qt
def test_zero_stores_and_employees_does_not_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Tək-mağazalı/yeni quraşdırma — sıfır sətir REAL ekranı çökdürməməlidir."""
    context = _Context(connection=_Connection(employee_count=0, store_count=0))
    screen = _build_screen(theme, qtbot)

    _populate(context, _Actor(), screen)  # ÇÖKMƏMƏLİDİR

    assert screen._employees._value.text() == "0"


@requires_qt
def test_an_extremely_long_store_name_and_huge_amount_do_not_crash_the_chart(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    hostile_name = "Mərkəz — 🔥" * 40 + "'; DROP TABLE fines; --"
    connection = _Connection(fines_rows=[_Row(store_name=hostile_name, total=999_999_999)])
    context = _Context(connection=connection)
    screen = _build_screen(theme, qtbot)

    _populate(context, _Actor(), screen)  # ÇÖKMƏMƏLİDİR


# --------------------------------------------------------------------------- #
# 2. "GÖRMƏK = SƏLAHİYYƏT" — flag-siz aktor iki AD-BAAD bölməni GÖRMÜR
# --------------------------------------------------------------------------- #


@requires_qt
def test_break_overuse_card_stays_hidden_without_the_reports_flag(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Real sətirlər MÖVCUDDUR (server-də), lakin flag-siz aktor onları GÖRMƏMƏLİDİR."""
    usages = [_BreakUsage(EMPLOYEE_ID, "2-ci nahar fasiləsi (limit: 1)")]
    connection = _Connection(
        break_names=[_Row(id=EMPLOYEE_ID, first_name="Aygün", last_name="Məmmədova")]
    )
    context = _Context(connection=connection, leave_verification=_LeaveVerification(usages))
    screen = _build_screen(theme, qtbot)
    screen.show()

    _populate(context, _Actor(), screen)  # flag-SİZ aktor

    assert not screen._break_card.isVisible(), "Flag-siz aktor ad-baad xəbərdarlıq GÖRMƏMƏLİDİR"


@requires_qt
def test_break_overuse_card_becomes_visible_with_the_reports_flag(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.application.use_cases.employee_profile import VIEW_EMPLOYEE_REPORTS_FLAG

    usages = [_BreakUsage(EMPLOYEE_ID, "2-ci nahar fasiləsi (limit: 1)")]
    connection = _Connection(
        break_names=[_Row(id=EMPLOYEE_ID, first_name="Aygün", last_name="Məmmədova")]
    )
    context = _Context(connection=connection, leave_verification=_LeaveVerification(usages))
    screen = _build_screen(theme, qtbot)
    screen.show()

    _populate(context, _Actor(frozenset({VIEW_EMPLOYEE_REPORTS_FLAG})), screen)

    assert screen._break_card.isVisible()
    from PySide6.QtWidgets import QLabel

    assert any(
        "Aygün Məmmədova" in label.text() for label in screen._break_card.findChildren(QLabel)
    )


@requires_qt
def test_benchmark_sections_stay_hidden_without_the_export_flag(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    context = _Context()
    screen = _build_screen(theme, qtbot)
    screen.show()

    _populate(context, _Actor(), screen)  # flag-SİZ aktor

    assert not screen._ranking_card.isVisible()
    assert not screen._trend_card.isVisible()
    assert not screen._outlier_card.isVisible()
    assert not screen._store_vs_network_card.isVisible()


@requires_qt
def test_benchmark_sections_become_visible_with_the_export_flag(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.application.use_cases.multi_store_benchmark import VIEW_BENCHMARK_FLAG

    context = _Context()
    screen = _build_screen(theme, qtbot)
    screen.show()

    _populate(context, _Actor(frozenset({VIEW_BENCHMARK_FLAG})), screen)

    assert screen._ranking_card.isVisible()
    assert screen._trend_card.isVisible()
    assert screen._outlier_card.isVisible()


@requires_qt
def test_an_unknown_ranking_metric_from_a_stale_dropdown_does_not_crash(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.application.use_cases.multi_store_benchmark import VIEW_BENCHMARK_FLAG
    from src.presentation.controllers.screen_data import ScreenDataBinder

    context = _Context()
    screen = _build_screen(theme, qtbot)
    binder = ScreenDataBinder(context, _Actor(frozenset({VIEW_BENCHMARK_FLAG})))

    binder.refresh_dashboard_benchmark(screen, metric_key="NOT_A_REAL_METRIC")  # ÇÖKMƏMƏLİDİR

    assert screen.section_errors() == ("Mağaza reytinqi",)


# --------------------------------------------------------------------------- #
# 3. Bölmə-təcridi — bir sorğu sınsa qalanları düzgün qalır
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_broken_network_query_does_not_prevent_other_sections_from_loading(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    connection = _Connection(fines_rows=[_Row(store_name="Mərkəz", total=150)])
    context = _Context(connection=connection, broken_section="employee_count")
    screen = _build_screen(theme, qtbot)

    _populate(context, _Actor(), screen)  # ÇÖKMƏMƏLİDİR

    assert "Şəbəkənin ölçüsü" in screen.section_errors()
    # Cərimə bölməsi SINMAYIB — qalan altı bölmə öz işini davam etdirir.
    assert "Filial üzrə cərimələr" not in screen.section_errors()
