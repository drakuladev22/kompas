"""Faza 6 widget-lərinin MƏLUMAT YOLU — `v2backlog.md` 6.1–6.5.

──────────────────────────────────────────────────────────────────────────────
BU FAYL NİYƏ SONRADAN YAZILDI — «ÖLÇÜLƏN ≠ ÖRTÜLƏN»
──────────────────────────────────────────────────────────────────────────────
Faza 6 beş yeni dashboard widget-i gətirdi. `test_analytics_phase6.py` onların
YALNIZ İKİSİNİ yoxlayırdı: təkrar-üz QAYDASINI (Exception Engine səviyyəsi) və
kampaniya dövrlərinin use case-ini. Ekranı DOLDURAN dörd metod
(`_dashboard_cost_center_fetch`, `_dashboard_operators_fetch`,
`_dashboard_campaign_fetch`, `_dashboard_fairness_fetch`) heç bir testdə
ÇAĞIRILMIRDI — yəni sətirlərin formatı, səlahiyyət qapıları və median
hesablaması yalnız canlı bazada üzə çıxardı.

Bu, CLAUDE.md §2-nin xəbərdarlığının eynisidir: kontroller qatı «test edilib»
görünür, çünki fayl adları tanışdır — ÇAĞIRILAN yollar isə başqadır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SAHTƏ BAĞLANTI, NİYƏ CANLI BAZA DEYİL
──────────────────────────────────────────────────────────────────────────────
Bu metodların RİSKİ SQL-də deyil (onu inteqrasiya testi tutur), PYTHON
tərəfindədir: median seçimi, faiz formatı, `None` gələn sütunlar, səlahiyyət
qapısı. Sahtə bağlantı sorğunu barmaq izinə görə tanıyıb sətir qaytarır —
beləliklə test baza olmadan da HƏMİN məntiqi ölçür.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any

import pytest

from src.presentation.controllers.screen_data import ScreenDataBinder

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()
TODAY = date(2026, 8, 26)
MONTH_START = date(2026, 8, 1)
NEXT_MONTH = date(2026, 9, 1)


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _Connection:
    """Sorğunu BARMAQ İZİNƏ görə tanıyır — SQL mətnini təkrar yazmır.

    Barmaq izi kimi sorğunun ƏSAS cədvəli/sütunu seçilib: tam SQL-i teste
    köçürmək onu sorğunun formatına bağlayardı və hər boşluq dəyişikliyi
    testi qırardı (halbuki davranış eyni qalır).
    """

    def __init__(self, answers: dict[str, list[dict[str, Any]]]) -> None:
        self._answers = answers
        self.seen: list[str] = []

    def execute(self, sql: str, params: Any = None) -> _Result:
        self.seen.append(sql)
        for fingerprint, rows in self._answers.items():
            if fingerprint in sql:
                return _Result(rows)
        return _Result([])


class _Employees:
    def __init__(self, names: dict[uuid.UUID, str]) -> None:
        self._names = names

    def get(self, employee_id: Any) -> Any:
        name = self._names.get(uuid.UUID(str(employee_id)))
        if name is None:
            return None
        return type("_Profile", (), {"full_name": name})()


class _Uow:
    def __init__(self, connection: _Connection, employees: _Employees) -> None:
        self.connection = connection
        self.employees = employees


class _Session:
    def __init__(self, connection: _Connection, employees: _Employees) -> None:
        self.tenant_id = TENANT
        self.uow = _Uow(connection, employees)


class _Context:
    def __init__(self, session: _Session) -> None:
        self._session = session

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        yield self._session


class _Actor:
    def __init__(self, flags: frozenset[str]) -> None:
        self.id = ACTOR_ID
        self._flags = flags

    def has_permission(self, flag: str, *, now: datetime | None = None) -> bool:
        return flag in self._flags


def _binder(
    answers: dict[str, list[dict[str, Any]]],
    *,
    flags: frozenset[str] = frozenset(),
    names: dict[uuid.UUID, str] | None = None,
) -> tuple[ScreenDataBinder, _Session]:
    session = _Session(_Connection(answers), _Employees(names or {}))
    binder = ScreenDataBinder(_Context(session), _Actor(flags))  # type: ignore[arg-type]
    return binder, session


# --------------------------------------------------------------------------- #
# 6.1 — Mağaza üzrə xərc mərkəzi
# --------------------------------------------------------------------------- #


def test_cost_center_reports_overtime_hours_and_the_bonus_total() -> None:
    """Sütunlar SAAT, qeyd isə BONUS XALI daşıyır — ikisi fərqli ölçüdür."""
    binder, session = _binder(
        {
            "overtime_hours": [
                {"store_name": "Bellona 28 May", "overtime_hours": 12.5, "bonus_points": 40},
                {"store_name": "Yataş Xətai", "overtime_hours": 3.25, "bonus_points": 10},
            ]
        },
        flags=frozenset({"can_export_reports"}),
    )

    data = binder._dashboard_cost_center_fetch(
        session,  # type: ignore[arg-type]
        month_start=MONTH_START,
        next_month=NEXT_MONTH,
    )

    assert data is not None
    assert data.bars == [
        ("Bellona 28 May", 12.5, "12.5 saat"),
        ("Yataş Xətai", 3.25, "3.2 saat"),
    ]
    assert "50 bonus xalı" in data.bonus_note
    assert "maaş fondu KompasOS-da izlənmir" in data.bonus_note


def test_cost_center_survives_a_store_without_any_overtime() -> None:
    """Yeni mağazada `overtime_hours` sıfırdır — sətir YENƏ görünməlidir.

    Sıfırlı mağazanı gizlətsəydik, «bu filialın əlavə iş yükü yoxdur» faktı
    ekranda «məlumat yoxdur» kimi oxunardı; ikisi fərqli cavabdır.
    """
    binder, session = _binder(
        {
            "overtime_hours": [
                {"store_name": "Yeni Filial", "overtime_hours": 0.0, "bonus_points": 0}
            ]
        },
        flags=frozenset({"can_export_reports"}),
    )

    data = binder._dashboard_cost_center_fetch(
        session,  # type: ignore[arg-type]
        month_start=MONTH_START,
        next_month=NEXT_MONTH,
    )

    assert data is not None
    assert data.bars == [("Yeni Filial", 0.0, "0.0 saat")]
    assert "0 bonus xalı" in data.bonus_note


# --------------------------------------------------------------------------- #
# 6.2 — Təkrar işçi qeydiyyatı (widget tərəfi)
# --------------------------------------------------------------------------- #


def test_duplicate_widget_is_hidden_without_the_exceptions_flag() -> None:
    """Flag yoxdursa `None` — «boş siyahı» DEYİL.

    Fərq davranışdadır: `None` bölməni GİZLƏDİR, boş siyahı isə «təkrar
    qeydiyyat tapılmadı» yazısını göstərərdi — səlahiyyəti olmayan istifadəçi
    üçün bu, olmayan bir təminat vəd etmək olardı.
    """
    binder, session = _binder({"DUPLICATE_FACE": []})

    assert binder._dashboard_duplicates_fetch(session) is None  # type: ignore[arg-type]


def test_duplicate_widget_resolves_both_names_of_the_pair() -> None:
    """Cütün İKİNCİ adı `context_json`-dan həll olunur (SQL JOIN-i yoxdur)."""
    subject, pair = uuid.uuid4(), uuid.uuid4()
    binder, session = _binder(
        {
            "DUPLICATE_FACE": [
                {
                    "employee_id": subject,
                    "context_json": {"pair_employee_id": str(pair), "distance": 0.21},
                    "created_at": datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
                }
            ]
        },
        flags=frozenset({"can_view_exceptions"}),
        names={subject: "Rəşad Məmmədov", pair: "Elvin Quliyev"},
    )

    data = binder._dashboard_duplicates_fetch(session)  # type: ignore[arg-type]

    assert data is not None
    assert data.rows == [("Rəşad Məmmədov", "Elvin Quliyev", "0.21", "20.08.2026")]


def test_duplicate_widget_does_not_crash_on_a_broken_pair_reference() -> None:
    """`context_json`-dakı yararsız UUID sətri BÜTÜN bölməni sındırmamalıdır."""
    subject = uuid.uuid4()
    binder, session = _binder(
        {
            "DUPLICATE_FACE": [
                {
                    "employee_id": subject,
                    "context_json": {"pair_employee_id": "yararsız", "distance": 0.3},
                    "created_at": datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
                }
            ]
        },
        flags=frozenset({"can_view_exceptions"}),
        names={subject: "Rəşad Məmmədov"},
    )

    data = binder._dashboard_duplicates_fetch(session)  # type: ignore[arg-type]

    assert data is not None
    assert data.rows[0][1] == "—", "Naməlum cüt «—» kimi göstərilməlidir"


# --------------------------------------------------------------------------- #
# 6.3 — Kamera operatorunun performansı
# --------------------------------------------------------------------------- #


def test_operator_performance_is_hidden_from_the_operator_themselves() -> None:
    """Spesifikasiya: «yalnız HR_Admin/CEO görür, operator özü YOX»."""
    binder, session = _binder({"verified_count": []})

    assert (
        binder._dashboard_operators_fetch(
            session,  # type: ignore[arg-type]
            month_start=MONTH_START,
            next_month=NEXT_MONTH,
        )
        is None
    )


def test_operator_performance_formats_minutes_and_late_share() -> None:
    binder, session = _binder(
        {
            "verified_count": [
                {
                    "operator_name": "Nigar Əliyeva",
                    "verified_count": 42,
                    "avg_minutes": 12.6,
                    "late_share": 9.4,
                }
            ]
        },
        flags=frozenset({"can_view_operator_performance"}),
    )

    data = binder._dashboard_operators_fetch(
        session,  # type: ignore[arg-type]
        month_start=MONTH_START,
        next_month=NEXT_MONTH,
    )

    assert data is not None
    assert data.rows == [("Nigar Əliyeva", "42", "13 dəq", "9%")]


def test_operator_performance_reads_the_late_threshold_from_root() -> None:
    """Gecikmə həddi `VERIFICATION_TIMEOUT_MINUTES`-dən gəlir, koddan YOX.

    Sorğuya ötürülən parametr yoxlanılmır (sahtə bağlantı SQL icra etmir) —
    yoxlanılan budur ki, kod HƏMİN açarı bazadan OXUYUR: oxumasaydı Root-un
    dəyişdiyi hədd panelə heç vaxt çatmazdı.
    """
    binder, session = _binder(
        {
            "limit_value": [{"limit_value": "30"}],
            "verified_count": [
                {
                    "operator_name": "Nigar Əliyeva",
                    "verified_count": 5,
                    "avg_minutes": None,
                    "late_share": None,
                }
            ],
        },
        flags=frozenset({"can_view_operator_performance"}),
    )

    data = binder._dashboard_operators_fetch(
        session,  # type: ignore[arg-type]
        month_start=MONTH_START,
        next_month=NEXT_MONTH,
    )

    assert data is not None
    assert data.rows == [("Nigar Əliyeva", "5", "0 dəq", "0%")], "`None` sütunlar sıfıra düşür"
    assert any("system_limits" in sql for sql in session.uow.connection.seen), (
        "Root həddi oxunmayıb — `system_limits` sorğusu ümumiyyətlə getməyib"
    )


# --------------------------------------------------------------------------- #
# 6.4 — Kampaniya təsiri
# --------------------------------------------------------------------------- #


def test_campaign_impact_is_hidden_without_either_viewing_flag() -> None:
    binder, session = _binder({"campaign_periods": []})

    assert binder._dashboard_campaign_fetch(session, today=TODAY) is None  # type: ignore[arg-type]


def test_campaign_impact_shows_the_delta_against_the_preceding_window() -> None:
    """Kampaniya günlərinin ortası ƏVVƏLKİ eyni uzunluqlu pəncərə ilə müqayisə olunur."""
    binder, session = _binder(
        {
            "campaign_periods": [
                {
                    "name": "Avqust Endirimi",
                    "start_date": date(2026, 8, 10),
                    "end_date": date(2026, 8, 20),
                }
            ],
            "avg_count": [{"avg_count": 6.0}],
        },
        flags=frozenset({"can_view_attrition_risk"}),
    )

    data = binder._dashboard_campaign_fetch(session, today=TODAY)  # type: ignore[arg-type]

    assert data is not None
    label, detail = data.rows[0]
    assert label == "Avqust Endirimi (10.08–20.08)"
    assert detail == "＝ 0.0 işçi/gün bazaya görə", "Eyni orta → fərq sıfırdır"


def test_campaign_impact_says_data_is_still_collecting_when_a_window_is_empty() -> None:
    """Boş pəncərə «0 fərq» DEYİL: ölçü hələ mümkün deyil."""
    binder, session = _binder(
        {
            "campaign_periods": [
                {
                    "name": "Yeni Kampaniya",
                    "start_date": date(2026, 8, 25),
                    "end_date": date(2026, 8, 30),
                }
            ],
            "avg_count": [{"avg_count": None}],
        },
        flags=frozenset({"can_manage_campaign_periods"}),
    )

    data = binder._dashboard_campaign_fetch(session, today=TODAY)  # type: ignore[arg-type]

    assert data is not None
    assert data.rows[0][1] == "məlumat toplanır"


# --------------------------------------------------------------------------- #
# 6.5 — İş yükünün ədalətliliyi
# --------------------------------------------------------------------------- #


def test_workload_fairness_ranks_by_distance_from_the_median() -> None:
    """Median ORTADAN fərqi ölçür — bir «çox işləyən» siyahını sürüşdürmür.

    Günlər: 4, 10, 11, 12 → median 10.5. Ən uzaq sətir 4 gündür; ORTA
    (9.25) işlədilsəydi sıralama eyni çıxardı, LAKİN 30 günlük bir işçi
    əlavə olunanda orta bütün komandanı «az işləyən» edərdi.
    """
    binder, session = _binder(
        {
            "day_count": [
                {"full_name": "Ayan Hüseynova", "store_name": "Bellona", "day_count": 4},
                {"full_name": "Elvin Quliyev", "store_name": "Bellona", "day_count": 10},
                {"full_name": "Nigar Əliyeva", "store_name": "Xətai", "day_count": 11},
                {"full_name": "Rəşad Məmmədov", "store_name": "Xətai", "day_count": 12},
            ]
        }
    )

    data = binder._dashboard_fairness_fetch(session, today=TODAY)  # type: ignore[arg-type]

    assert data is not None
    assert data.rows[0][0] == "Ayan Hüseynova", "Mediandan ƏN UZAQ sətir başda olmalıdır"
    assert "10.5" in data.hint or "median" in data.hint.lower()


def test_workload_fairness_returns_an_empty_view_when_no_shift_exists() -> None:
    """Növbə yoxdursa median hesablana bilməz — çökmə YOX, boş görünüş."""
    binder, session = _binder({"day_count": []})

    data = binder._dashboard_fairness_fetch(session, today=TODAY)  # type: ignore[arg-type]

    assert data is not None
    assert data.rows == []
    assert data.hint == ""
