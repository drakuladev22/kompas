"""Çökmə paneli və dəstək inbox-unun sıralama/SLA qərarları — Faza 6.

Bu oxu-modellərin bütün dəyəri PRİORİTETLƏŞDİRMƏDƏDİR: hansı çökmə əvvəl
göstərilir, hansı müraciət diqqət tələb edir. Testlər məhz həmin sıranı
qoruyur.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.application.use_cases.developer_console import (
    FIRST_RESPONSE_SLA_HOURS,
    RESOLUTION_SLA_HOURS,
    CrashDashboard,
    CrashRecord,
    SlaState,
    SupportInbox,
    TicketRecord,
    group_crashes,
)

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _crash(
    *,
    fingerprint: str,
    tenant: str,
    version: str = "1.4.0",
    minutes_ago: int = 0,
    exception_type: str = "ValueError",
) -> CrashRecord:
    return CrashRecord(
        fingerprint=fingerprint,
        exception_type=exception_type,
        app_version=version,
        anonymous_tenant_ref=tenant,
        occurred_at=NOW - timedelta(minutes=minutes_ago),
    )


# --------------------------------------------------------------------------- #
# Çökmə qruplaşdırması
# --------------------------------------------------------------------------- #


def test_crashes_are_grouped_by_fingerprint() -> None:
    groups = group_crashes(
        [
            _crash(fingerprint="abc", tenant="t1"),
            _crash(fingerprint="abc", tenant="t1", minutes_ago=5),
            _crash(fingerprint="def", tenant="t2"),
        ]
    )
    assert {group.fingerprint for group in groups} == {"abc", "def"}
    assert next(g for g in groups if g.fingerprint == "abc").occurrences == 2


def test_installation_count_beats_raw_repetition() -> None:
    """20 mağazada 3 dəfə çökən kod xətası bir mağazadakı 500 təkrarı üstələyir."""
    local_noise = [_crash(fingerprint="local", tenant="t1") for _ in range(50)]
    widespread = [_crash(fingerprint="wide", tenant=f"t{i}") for i in range(5)]

    groups = group_crashes(local_noise + widespread)

    assert groups[0].fingerprint == "wide"
    assert groups[0].affected_installations == 5
    assert groups[1].occurrences == 50


def test_single_installation_crash_is_not_widespread() -> None:
    groups = group_crashes([_crash(fingerprint="x", tenant="t1") for _ in range(20)])
    assert not groups[0].is_widespread


def test_widespread_needs_several_installations() -> None:
    groups = group_crashes([_crash(fingerprint="x", tenant=f"t{i}") for i in range(3)])
    assert groups[0].is_widespread


def test_regression_is_detected_when_only_one_version_is_affected() -> None:
    groups = group_crashes(
        [
            _crash(fingerprint="x", tenant="t1", version="1.5.0"),
            _crash(fingerprint="x", tenant="t2", version="1.5.0"),
        ]
    )
    assert groups[0].is_regression
    assert groups[0].app_versions == ("1.5.0",)


def test_long_standing_crash_is_not_a_regression() -> None:
    groups = group_crashes(
        [
            _crash(fingerprint="x", tenant="t1", version="1.4.0"),
            _crash(fingerprint="x", tenant="t2", version="1.5.0"),
        ]
    )
    assert not groups[0].is_regression


def test_first_and_last_seen_span_the_group() -> None:
    groups = group_crashes(
        [
            _crash(fingerprint="x", tenant="t1", minutes_ago=100),
            _crash(fingerprint="x", tenant="t1", minutes_ago=10),
        ]
    )
    assert groups[0].first_seen == NOW - timedelta(minutes=100)
    assert groups[0].last_seen == NOW - timedelta(minutes=10)


def test_dashboard_totals_and_widespread_filter() -> None:
    dashboard = CrashDashboard.from_records(
        [_crash(fingerprint="wide", tenant=f"t{i}") for i in range(4)]
        + [_crash(fingerprint="local", tenant="t9")]
    )

    assert dashboard.total_crashes == 5
    assert [group.fingerprint for group in dashboard.widespread] == ["wide"]
    assert len(dashboard.top(1)) == 1


def test_empty_dashboard_is_not_an_error() -> None:
    dashboard = CrashDashboard.from_records([])
    assert dashboard.total_crashes == 0
    assert dashboard.top() == []


def test_group_summary_is_azerbaijani() -> None:
    groups = group_crashes([_crash(fingerprint="x", tenant="t1", exception_type="KeyError")])
    assert "KeyError" in groups[0].summary_az
    assert "quraşdırmada" in groups[0].summary_az


# --------------------------------------------------------------------------- #
# Dəstək inbox-u və SLA
# --------------------------------------------------------------------------- #


def _ticket(
    *,
    ticket_id: str = "T-1",
    tenant: str = "Bellona",
    hours_ago: int = 1,
    first_response_hours: int | None = None,
    closed_hours: int | None = None,
    status: str = "OPEN",
) -> TicketRecord:
    created = NOW - timedelta(hours=hours_ago)
    return TicketRecord(
        ticket_id=ticket_id,
        tenant_name=tenant,
        subject="1C sinxronizasiyası dayanıb",
        status=status,
        created_at=created,
        first_response_at=(
            None
            if first_response_hours is None
            else created + timedelta(hours=first_response_hours)
        ),
        closed_at=(None if closed_hours is None else created + timedelta(hours=closed_hours)),
    )


def test_fresh_ticket_is_on_track() -> None:
    inbox = SupportInbox.from_records([_ticket(hours_ago=1)], now=NOW)
    assert inbox.tickets[0].response_sla is SlaState.ON_TRACK
    assert not inbox.tickets[0].needs_attention


def test_ticket_in_the_last_quarter_of_the_window_is_at_risk() -> None:
    """Xəbərdarlıq POZULMADAN ƏVVƏL gəlməlidir — sonra artıq gecdir."""
    inbox = SupportInbox.from_records(
        [_ticket(hours_ago=int(FIRST_RESPONSE_SLA_HOURS * 0.8))], now=NOW
    )
    assert inbox.tickets[0].response_sla is SlaState.AT_RISK
    assert inbox.tickets[0].needs_attention


def test_unanswered_ticket_past_the_window_is_breached() -> None:
    inbox = SupportInbox.from_records([_ticket(hours_ago=FIRST_RESPONSE_SLA_HOURS + 1)], now=NOW)
    assert inbox.tickets[0].response_sla is SlaState.BREACHED


def test_answered_within_the_window_is_met() -> None:
    inbox = SupportInbox.from_records(
        [_ticket(hours_ago=50, first_response_hours=2, closed_hours=5, status="CLOSED")],
        now=NOW,
    )
    view = inbox.tickets[0]
    assert view.response_sla is SlaState.MET
    assert view.resolution_sla is SlaState.MET
    assert not view.needs_attention


def test_a_closed_ticket_keeps_its_verdict_as_time_passes() -> None:
    """Keçmiş nəticə `now` irəlilədikcə dəyişməməlidir."""
    record = _ticket(hours_ago=10, first_response_hours=1, closed_hours=2, status="CLOSED")
    early = SupportInbox.from_records([record], now=NOW)
    late = SupportInbox.from_records([record], now=NOW + timedelta(days=30))
    assert early.tickets[0].response_sla is late.tickets[0].response_sla


def test_slow_reply_after_the_deadline_is_still_a_breach() -> None:
    inbox = SupportInbox.from_records(
        [_ticket(hours_ago=100, first_response_hours=FIRST_RESPONSE_SLA_HOURS + 5)],
        now=NOW,
    )
    assert inbox.tickets[0].response_sla is SlaState.BREACHED


def test_resolution_sla_is_tracked_separately_from_the_reply() -> None:
    """Sürətli cavab + gec həll «yaxşı xidmət» kimi görünməməlidir."""
    inbox = SupportInbox.from_records(
        [_ticket(hours_ago=RESOLUTION_SLA_HOURS + 10, first_response_hours=1)], now=NOW
    )
    view = inbox.tickets[0]
    assert view.response_sla is SlaState.MET
    assert view.resolution_sla is SlaState.BREACHED


def test_attention_needed_tickets_come_first() -> None:
    """SLA-sı pozulmuş müraciət siyahının ortasında gizlənə bilməz."""
    inbox = SupportInbox.from_records(
        [
            _ticket(ticket_id="fresh", hours_ago=1),
            _ticket(ticket_id="breached", hours_ago=FIRST_RESPONSE_SLA_HOURS + 5),
        ],
        now=NOW,
    )
    assert inbox.tickets[0].record.ticket_id == "breached"
    assert inbox.attention_count == 1


def test_awaiting_first_reply_excludes_closed_tickets() -> None:
    inbox = SupportInbox.from_records(
        [
            _ticket(ticket_id="open", hours_ago=2),
            _ticket(ticket_id="closed", hours_ago=2, closed_hours=1, status="CLOSED"),
        ],
        now=NOW,
    )
    assert [view.record.ticket_id for view in inbox.awaiting_first_reply] == ["open"]


def test_threads_can_be_filtered_per_tenant() -> None:
    inbox = SupportInbox.from_records(
        [
            _ticket(ticket_id="a", tenant="Bellona"),
            _ticket(ticket_id="b", tenant="Yataş"),
            _ticket(ticket_id="c", tenant="Bellona"),
        ],
        now=NOW,
    )
    assert {view.record.ticket_id for view in inbox.for_tenant("Bellona")} == {"a", "c"}
    assert inbox.tenants() == ["Bellona", "Yataş"]


def test_age_uses_the_closing_moment_for_finished_tickets() -> None:
    """Bağlanmış müraciətin yaşı sonradan ŞİŞMİR."""
    inbox = SupportInbox.from_records(
        [_ticket(hours_ago=100, first_response_hours=1, closed_hours=4, status="CLOSED")],
        now=NOW,
    )
    assert inbox.tickets[0].age_hours == 4


def test_an_open_ticket_keeps_counting() -> None:
    """Cavabsız müraciət inboxda «0 saat» görünə bilməz — sütun məhz onun üçündür."""
    inbox = SupportInbox.from_records([_ticket(hours_ago=30)], now=NOW)
    assert inbox.tickets[0].age_hours == 30


def test_an_answered_but_unresolved_ticket_also_keeps_counting() -> None:
    inbox = SupportInbox.from_records([_ticket(hours_ago=48, first_response_hours=1)], now=NOW)
    assert inbox.tickets[0].age_hours == 48


def test_sla_labels_are_azerbaijani() -> None:
    assert SlaState.BREACHED.label_az == "SLA pozulub"
    assert SlaState.ON_TRACK.label_az == "Vaxtında"


# --------------------------------------------------------------------------- #
# Təcili giriş bərpası — giriş şərtləri (bölmə 2)
# --------------------------------------------------------------------------- #


class _RecoveryDirectory:
    """`get()` üçün minimal ikiqat — yalnız tanınan tenant qaytarır."""

    def __init__(self, known: str = "t-1") -> None:
        self._known = known

    def get(self, tenant_id: str) -> object | None:
        return object() if tenant_id == self._known else None


def test_recovery_requires_a_username() -> None:
    from src.developer_panel.console import _recovery_problem

    problem = _recovery_problem(
        _RecoveryDirectory(),  # type: ignore[arg-type]
        "t-1",
        "",
        "TICKET-42",
        "info@musteri.az",
    )
    assert problem is not None
    assert "İstifadəçi adı" in problem


def test_recovery_rejects_unknown_tenant() -> None:
    from src.developer_panel.console import _recovery_problem

    problem = _recovery_problem(
        _RecoveryDirectory(),  # type: ignore[arg-type]
        "yoxdur",
        "r.mammadov",
        "TICKET-42",
        "info@musteri.az",
    )
    assert problem is not None
    assert "tapılmadı" in problem


def test_recovery_reference_is_mandatory() -> None:
    """Kimlik təsdiqinin izi olmadan prosedur audit-də izsiz qalardı."""
    from src.developer_panel.console import _recovery_problem

    problem = _recovery_problem(
        _RecoveryDirectory(),  # type: ignore[arg-type]
        "t-1",
        "r.mammadov",
        "   ",
        "info@musteri.az",
    )
    assert problem is not None
    assert "recovery-reference" in problem


def test_recovery_contact_is_mandatory() -> None:
    """Əlaqə təsdiqi prosedurun ƏSAS qapısıdır (bax `authentication.py`)."""
    from src.developer_panel.console import _recovery_problem

    problem = _recovery_problem(
        _RecoveryDirectory(),  # type: ignore[arg-type]
        "t-1",
        "r.mammadov",
        "TICKET-42",
        "",
    )
    assert problem is not None
    assert "recovery-contact" in problem


def test_recovery_accepts_a_complete_request() -> None:
    from src.developer_panel.console import _recovery_problem

    assert (
        _recovery_problem(
            _RecoveryDirectory(),  # type: ignore[arg-type]
            "t-1",
            "r.mammadov",
            "TICKET-42",
            "info@musteri.az",
        )
        is None
    )
