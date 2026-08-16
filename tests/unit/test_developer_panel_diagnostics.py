"""Developer Panelinin çökmə/dəstək bölmələri — konsol və GUI — Faza 6.

Panel `service_role` bağlantısı tələb edir, ona görə `DeveloperTenantDirectory`
saxta obyektlə əvəz olunur. Yoxlanılan şey SQL deyil, PANELİN QƏRARIDIR:
nə göstərilir, hansı sıra ilə, xəta halında nə olur.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.application.use_cases.developer_console import (
    FIRST_RESPONSE_SLA_HOURS,
    CrashDashboard,
    CrashRecord,
    SupportInbox,
    TicketRecord,
)
from src.developer_panel.console import (
    render_crash_dashboard,
    render_support_inbox,
    run_console,
)
from src.shared.exceptions import KompasOSError

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


class _DirectoryUnavailableError(KompasOSError):
    user_message = "Baza əlçatmazdır."


class _FakeDirectory:
    """`DeveloperTenantDirectory`-nin panel üçün lazım olan hissəsi."""

    def __init__(
        self,
        *,
        crashes: list[CrashRecord] | None = None,
        tickets: list[TicketRecord] | None = None,
        fail: str = "",
    ) -> None:
        self._crashes = crashes or []
        self._tickets = tickets or []
        self._fail = fail

    def list_tenants(self, *, search: str = "") -> list[Any]:
        return []

    def crash_records(self, *, days: int = 30, limit: int = 2000) -> list[CrashRecord]:
        if self._fail == "crashes":
            raise _DirectoryUnavailableError("çökmə sorğusu alınmadı")
        return self._crashes

    def support_tickets(self, *, limit: int = 200) -> list[TicketRecord]:
        if self._fail == "tickets":
            raise _DirectoryUnavailableError("müraciət sorğusu alınmadı")
        return self._tickets


def _crash(*, fingerprint: str, tenant: str, exception_type: str = "ValueError") -> CrashRecord:
    return CrashRecord(
        fingerprint=fingerprint,
        exception_type=exception_type,
        app_version="1.4.0",
        anonymous_tenant_ref=tenant,
        occurred_at=NOW,
    )


def _ticket(*, ticket_id: str, tenant: str, hours_ago: int) -> TicketRecord:
    return TicketRecord(
        ticket_id=ticket_id,
        tenant_name=tenant,
        subject="1C sinxronizasiyası dayanıb",
        status="OPEN",
        created_at=NOW - timedelta(hours=hours_ago),
    )


# --------------------------------------------------------------------------- #
# Konsol çıxışı
# --------------------------------------------------------------------------- #


def test_empty_crash_dashboard_says_so_instead_of_printing_a_bare_header() -> None:
    assert render_crash_dashboard(CrashDashboard.from_records([])) == "Çökmə hesabatı yoxdur."


def test_widespread_crash_is_marked_and_listed_first() -> None:
    dashboard = CrashDashboard.from_records(
        [_crash(fingerprint="local", tenant="t1", exception_type="OSError")] * 30
        + [_crash(fingerprint="wide", tenant=f"t{i}", exception_type="KeyError") for i in range(4)]
    )

    output = render_crash_dashboard(dashboard)
    lines = output.splitlines()

    assert lines[2].startswith("KeyError")
    assert lines[2].rstrip().endswith("!")
    assert "OSError" in lines[3]
    assert not lines[3].rstrip().endswith("!")


def test_crash_summary_reports_how_many_groups_are_shown() -> None:
    """Kəsilmə SƏSSİZ olmamalıdır."""
    dashboard = CrashDashboard.from_records(
        [_crash(fingerprint=f"f{i}", tenant=f"t{i}") for i in range(20)]
    )
    output = render_crash_dashboard(dashboard, limit=5)
    assert "20 qrup" in output
    assert "5 göstərilir" in output


def test_empty_inbox_says_so() -> None:
    assert render_support_inbox(SupportInbox.from_records([], now=NOW)) == (
        "Dəstək müraciəti yoxdur."
    )


def test_breached_ticket_is_marked_and_listed_first() -> None:
    inbox = SupportInbox.from_records(
        [
            _ticket(ticket_id="fresh", tenant="Yataş", hours_ago=1),
            _ticket(ticket_id="late", tenant="Bellona", hours_ago=FIRST_RESPONSE_SLA_HOURS + 5),
        ],
        now=NOW,
    )

    lines = render_support_inbox(inbox).splitlines()

    assert lines[2].startswith("Bellona")
    assert lines[2].rstrip().endswith("!")
    assert "diqqət tələb edən: 1" in lines[-1]


def test_inbox_summary_counts_tickets_awaiting_a_first_reply() -> None:
    inbox = SupportInbox.from_records(
        [_ticket(ticket_id=f"t{i}", tenant="Bellona", hours_ago=1) for i in range(3)], now=NOW
    )
    assert "ilk cavab gözləyən: 3" in render_support_inbox(inbox)


# --------------------------------------------------------------------------- #
# `run_console` marşrutlaşdırması
# --------------------------------------------------------------------------- #


def test_crashes_flag_routes_to_the_crash_dashboard() -> None:
    directory = _FakeDirectory(crashes=[_crash(fingerprint="x", tenant="t1")])
    code, output = run_console(directory, show_crashes=True, now=NOW)  # type: ignore[arg-type]

    assert code == 0
    assert "XƏTA NÖVÜ" in output


def test_tickets_flag_routes_to_the_inbox() -> None:
    directory = _FakeDirectory(tickets=[_ticket(ticket_id="a", tenant="Bellona", hours_ago=1)])
    code, output = run_console(directory, show_tickets=True, now=NOW)  # type: ignore[arg-type]

    assert code == 0
    assert "MÜŞTƏRİ" in output


def test_crashes_flag_wins_over_the_default_tenant_table() -> None:
    """Görünüş seçimi açıqdır — istifadəçi nə istədiyini yazıb."""
    directory = _FakeDirectory(crashes=[_crash(fingerprint="x", tenant="t1")])
    _, output = run_console(directory, show_crashes=True, now=NOW)  # type: ignore[arg-type]
    assert "ŞİRKƏT" not in output


def test_without_flags_the_tenant_table_is_still_the_default() -> None:
    code, output = run_console(_FakeDirectory(), now=NOW)  # type: ignore[arg-type]
    assert code == 0
    assert output == "Heç bir müştəri qeydi tapılmadı."


# --------------------------------------------------------------------------- #
# REQRESSİYA: CLI bayraqları `run_console`-a FAKTİKİ olaraq çatır
#
# `run_console` `show_crashes`/`show_tickets`-i həmişə qəbul edirdi və
# `_render_view` onlara görə budaqlanırdı — LAKİN `main._run_developer_panel`
# onları ÖTÜRMÜRDÜ. Nəticə sükutla yanlış idi: `--developer-mode --crashes`
# adi müştəri cədvəlini göstərirdi və istifadəçi səhv məlumata baxdığını
# bilmirdi. Yuxarıdakı marşrutlaşdırma testləri bunu tuta bilmirdi, çünki
# onlar `run_console`-u BİRBAŞA çağırır — boşluq isə çağıran tərəfdə idi.
# --------------------------------------------------------------------------- #


def _developer_cli(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> dict[str, Any]:
    """`main(argv)`-i saxta panel qatı ilə işlədir və `run_console` arqumentlərini qaytarır.

    ARQUMENT SİYAHISI ƏL İLƏ QURULMUR: əsl `argparse` parser-i işə düşür, yəni
    test bayraq adının dəyişməsini də tutur. Loglama və global istisna qarmağı
    əvəzlənir — vahid test qlobal vəziyyəti dəyişməməlidir.
    """
    import src.main as main_module
    from src.developer_panel import console as console_module
    from src.infrastructure.licensing import developer_directory as directory_module
    from src.infrastructure.persistence import connection_types

    captured: dict[str, Any] = {}

    def _fake_run_console(directory: Any, **kwargs: Any) -> tuple[int, str]:
        captured.update(kwargs)
        return 0, "saxta çıxış"

    monkeypatch.setattr(console_module, "run_console", _fake_run_console)
    monkeypatch.setattr(directory_module, "developer_mode_enabled", lambda: True)
    monkeypatch.setattr(
        directory_module, "DeveloperTenantDirectory", lambda database: _FakeDirectory()
    )
    # SEAM `connection_types`-dədir: `_run_developer_panel` bağlantını
    # `TenantDatabase` kimi qurur (DB-4 Faza 1) — `Database`-i əvəzləmək
    # artıq HEÇ NƏYİ tutmur və test real bazaya qoşulmağa çalışardı.
    monkeypatch.setattr(connection_types, "TenantDatabase", object)
    monkeypatch.setattr(main_module, "_build_release_publisher", lambda database: None)
    monkeypatch.setattr(main_module, "configure_logging", lambda **kwargs: "logs")
    monkeypatch.setattr(main_module, "install_global_exception_hook", lambda: None)

    assert main_module.main(argv) == 0
    return captured


def test_crashes_flag_reaches_run_console(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured = _developer_cli(monkeypatch, ["--developer-mode", "--crashes"])

    assert captured["show_crashes"] is True
    assert captured["show_tickets"] is False
    capsys.readouterr()


def test_tickets_flag_reaches_run_console(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured = _developer_cli(monkeypatch, ["--developer-mode", "--tickets"])

    assert captured["show_tickets"] is True
    assert captured["show_crashes"] is False
    capsys.readouterr()


def test_default_developer_view_asks_for_neither_diagnostic(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Bayraqsız çağırışda hər ikisi `False` olmalıdır — cədvəl görünüşü."""
    captured = _developer_cli(monkeypatch, ["--developer-mode"])

    assert captured["show_crashes"] is False
    assert captured["show_tickets"] is False
    capsys.readouterr()


# --------------------------------------------------------------------------- #
# GUI bölmələri
# --------------------------------------------------------------------------- #

pytest.importorskip("PySide6", reason="Qt olmadan panel ekranı qurula bilməz")


@pytest.fixture
def panel(qtbot):  # type: ignore[no-untyped-def]
    """Paneli saxta məlumat qatı ilə qurur."""
    from src.developer_panel.ui import DeveloperPanelWindow

    def _build(directory: _FakeDirectory) -> Any:
        window = DeveloperPanelWindow(directory, clock=lambda: NOW)  # type: ignore[arg-type]
        qtbot.addWidget(window)
        return window

    return _build


def test_panel_shows_crash_groups(panel) -> None:  # type: ignore[no-untyped-def]
    window = panel(
        _FakeDirectory(
            crashes=[_crash(fingerprint="wide", tenant=f"t{i}") for i in range(4)],
            tickets=[],
        )
    )

    assert window.crash_table.rowCount() == 1
    assert window.crash_table.item(0, 0).text() == "ValueError"
    assert window.crash_table.item(0, 1).text() == "4"
    assert "4 çökmə" in window.crash_status.text()


def test_panel_marks_widespread_crashes_in_bold(panel) -> None:  # type: ignore[no-untyped-def]
    """Vurğu rənglə deyil, şrift qalınlığı ilə — Dark Mode-da da oxunur."""
    window = panel(
        _FakeDirectory(crashes=[_crash(fingerprint="wide", tenant=f"t{i}") for i in range(3)])
    )
    assert window.crash_table.item(0, 0).font().bold()


def test_panel_shows_tickets_with_sla_labels(panel) -> None:  # type: ignore[no-untyped-def]
    window = panel(
        _FakeDirectory(
            tickets=[
                _ticket(ticket_id="a", tenant="Bellona", hours_ago=FIRST_RESPONSE_SLA_HOURS + 2)
            ]
        )
    )

    assert window.ticket_table.rowCount() == 1
    assert window.ticket_table.item(0, 0).text() == "Bellona"
    assert window.ticket_table.item(0, 2).text() == "SLA pozulub"
    assert "diqqət tələb edən: 1" in window.ticket_status.text()


def test_a_failing_crash_query_does_not_empty_the_ticket_section(panel) -> None:
    """Bir bölmənin xətası digərini kor qoymamalıdır."""
    window = panel(
        _FakeDirectory(
            tickets=[_ticket(ticket_id="a", tenant="Bellona", hours_ago=1)],
            fail="crashes",
        )
    )

    assert window.crash_table.rowCount() == 0
    assert "Baza əlçatmazdır" in window.crash_status.text()
    assert window.ticket_table.rowCount() == 1


def test_a_failing_ticket_query_is_shown_not_swallowed(panel) -> None:
    """Panel hazırlayıcının öz alətidir — xəta gizlədilmir."""
    window = panel(_FakeDirectory(fail="tickets"))
    assert "Baza əlçatmazdır" in window.ticket_status.text()


def test_empty_data_renders_empty_tables_without_crashing(panel) -> None:
    window = panel(_FakeDirectory())
    assert window.crash_table.rowCount() == 0
    assert window.ticket_table.rowCount() == 0
