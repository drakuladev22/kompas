"""Repository QƏRARLARI — tərcih, konflikt, dəstək, plugin, nüsxə kataloqu.

──────────────────────────────────────────────────────────────────────────────
BAZA LAZIM DEYİL
──────────────────────────────────────────────────────────────────────────────
`tests/unit/test_config_repositories.py`-dakı naxış təkrarlanır: bağlantı
sahtə obyektlə əvəz olunur və yalnız QƏRARLAR yoxlanılır — sətir yoxdursa nə
qaytarılır, `NULL` sütun necə oxunur, hansı şərt idempotentlik verir, hansı
sütun UPSERT-də yenilənir. SQL-in faktiki icrası `tests/integration`-dadır və
`DATABASE_URL` olmadan atlanır.

Bu repository-lər ölçmədə **0% əhatə** ilə görünürdü: onların yeganə testi
inteqrasiya qatındadır, yəni bu maşında heç vaxt işləmir. Aşağıdakı testlər
məhz Python tərəfindəki qərarları (fallback, çevirmə, sayğac) bağlayır.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pytest

from src.application.use_cases.user_management import CredentialWriter
from src.domain.entities.appeal import AppealStatus, FineAppeal
from src.domain.entities.attendance_sheet import (
    AutoAttendanceStatus,
    DailyAttendanceSheet,
    SheetLine,
)
from src.domain.entities.exception_record import ExceptionRecord
from src.domain.entities.shift import ShiftSwapRequest
from src.domain.value_objects.exception_signals import ExceptionSeverity
from src.domain.value_objects.identifiers import (
    AppealId,
    EmployeeId,
    ExceptionId,
    FineId,
    ShiftSwapRequestId,
    SupportMessageId,
    SupportTicketId,
    TenantId,
    new_daily_sheet_id,
)
from src.domain.value_objects.money import Money
from src.domain.value_objects.scheduling import DEFAULT_TIMEZONE, TimeRange
from src.infrastructure.persistence.exception_repositories import (
    PostgresExceptionRepository,
    PostgresExceptionSourceCatalog,
)
from src.infrastructure.persistence.platform_repositories import (
    PostgresBackupCatalog,
    PostgresPluginRegistry,
)
from src.infrastructure.persistence.preferences import (
    DEFAULT_LANGUAGE,
    DEFAULT_THEME,
    PostgresUserPreferences,
)
from src.infrastructure.persistence.report_repositories import (
    PostgresReportFactProvider,
    _as_decimal,
)
from src.infrastructure.persistence.repositories import PostgresEmployeeRepository
from src.infrastructure.persistence.support_repositories import (
    PostgresSupportTicketRepository,
)
from src.infrastructure.persistence.sync_conflict_repository import (
    PostgresSyncConflictRepository,
)
from src.infrastructure.persistence.workflow_repositories import (
    PostgresAttendanceFactProvider,
    PostgresDailyAttendanceSheetRepository,
    PostgresFineAppealRepository,
    PostgresShiftSwapRepository,
)
from src.infrastructure.plugins.contracts import (
    PluginCapability,
    PluginManifest,
    PluginStatus,
)

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
ACTOR = EmployeeId(uuid.uuid4())
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Saxta bağlantı — sorğuya görə fərqli cavab
# --------------------------------------------------------------------------- #


class _FakeCursor:
    def __init__(self, plan: list[tuple[str, list[dict[str, Any]]]], log: list[Any]) -> None:
        self._plan = plan
        self._log = log
        self._rows: list[dict[str, Any]] = []
        self.rowcount = 0

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        flat = " ".join(sql.split())
        self._log.append((flat, params))
        self._rows = []
        for needle, rows in self._plan:
            if needle in flat:
                self._rows = rows
                break
        self.rowcount = len(self._rows)

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)


class _FakeConnection:
    """Sorğu mətnindəki AÇAR SÖZƏ görə sətir dəsti seçən bağlantı.

    Tək siyahı qaytaran sahtə `_hydrate()` kimi İKİ sorğu edən metodlarda
    yanlış nəticə verərdi (mesaj sorğusuna ticket sətirləri qayıdardı) — ona
    görə plan cədvəli işlədilir.
    """

    def __init__(self, plan: list[tuple[str, list[dict[str, Any]]]] | None = None) -> None:
        self.plan = plan or []
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.plan, self.executed)


class _Context:
    def __init__(self, tenant_id: TenantId = TENANT) -> None:
        self.tenant_id = tenant_id


def _build(
    repo_cls: type, plan: list[tuple[str, list[dict[str, Any]]]] | None = None
) -> tuple[Any, _FakeConnection]:
    conn = _FakeConnection(plan)
    return repo_cls(conn, _Context()), conn


def _sql(conn: _FakeConnection) -> str:
    return conn.executed[-1][0]


# --------------------------------------------------------------------------- #
# İstifadəçi tərcihləri (`preferences.py`)
# --------------------------------------------------------------------------- #


def test_a_user_who_never_opened_settings_gets_the_system_theme() -> None:
    """Sətrin olmaması NORMAL haldır — hər login-də boş sətir yaradılmır."""
    repo, _ = _build(PostgresUserPreferences, [("SELECT theme", [])])

    assert repo.theme_for(ACTOR) == DEFAULT_THEME == "SYSTEM"


def test_a_stored_theme_is_returned_verbatim() -> None:
    repo, _ = _build(PostgresUserPreferences, [("SELECT theme", [{"theme": "DARK"}])])

    assert repo.theme_for(ACTOR) == "DARK"


def test_an_unknown_stored_theme_falls_back_instead_of_breaking_the_shell() -> None:
    """Yararsız konfiqurasiya örtüyü çökdürməməlidir — defolta qayıdılır."""
    repo, _ = _build(PostgresUserPreferences, [("SELECT theme", [{"theme": "NEON"}])])

    assert repo.theme_for(ACTOR) == DEFAULT_THEME


@pytest.mark.parametrize("raw", ["", "  ", "neon", "system light"])
def test_writing_an_invalid_theme_is_refused(raw: str) -> None:
    """Sərhəd: boş və naməlum dəyər bazaya ÇATMIR."""
    repo, conn = _build(PostgresUserPreferences)

    with pytest.raises(ValueError, match="Naməlum tema"):
        repo.set_theme(ACTOR, raw)
    assert conn.executed == []


def test_theme_is_normalised_and_written_as_an_upsert() -> None:
    """Təkrar seçim ikinci sətir yaratmamalıdır."""
    repo, conn = _build(PostgresUserPreferences)

    repo.set_theme(ACTOR, "  dark  ")

    sql, params = conn.executed[-1]
    assert "INSERT INTO user_preferences" in sql
    assert "ON CONFLICT (user_id) DO UPDATE" in sql
    assert params == (ACTOR, "DARK")


def test_language_falls_back_to_azerbaijani() -> None:
    """Bölmə 9: yeganə interfeys dili — sətir yoxdursa da `az`."""
    repo, _ = _build(PostgresUserPreferences, [("SELECT language", [])])

    assert repo.language_for(ACTOR) == DEFAULT_LANGUAGE == "az"


def test_never_configured_layout_is_none_not_an_empty_list() -> None:
    """«Heç nə qurmamışam» ilə «hər şeyi gizlətdim» FƏRQLİDİR (miqrasiya 011)."""
    repo, _ = _build(PostgresUserPreferences, [("SELECT dashboard_layout", [])])
    assert repo.load(ACTOR) is None

    repo, _ = _build(
        PostgresUserPreferences,
        [("SELECT dashboard_layout", [{"dashboard_layout": None}])],
    )
    assert repo.load(ACTOR) is None


def test_an_explicitly_empty_layout_is_preserved() -> None:
    repo, _ = _build(
        PostgresUserPreferences, [("SELECT dashboard_layout", [{"dashboard_layout": []}])]
    )

    assert repo.load(ACTOR) == []


def test_a_layout_stored_as_a_json_string_is_still_readable() -> None:
    """Köhnə yazı mətn ola bilər — bir dəfəlik format fərqi ekranı sındırmır."""
    repo, _ = _build(
        PostgresUserPreferences,
        [("SELECT dashboard_layout", [{"dashboard_layout": '["fines", "tasks"]'}])],
    )

    assert repo.load(ACTOR) == ["fines", "tasks"]


def test_a_corrupt_layout_value_reads_as_an_empty_list() -> None:
    """Sərhəd: siyahı olmayan JSON — ekran boş açılır, çökmür."""
    repo, _ = _build(
        PostgresUserPreferences,
        [("SELECT dashboard_layout", [{"dashboard_layout": '{"a": 1}'}])],
    )

    assert repo.load(ACTOR) == []


def test_saving_a_layout_replaces_it_completely() -> None:
    repo, conn = _build(PostgresUserPreferences)

    repo.save(ACTOR, ["fines", "attendance"])

    sql, params = conn.executed[-1]
    assert "ON CONFLICT (user_id) DO UPDATE" in sql
    assert json.loads(params[1]) == ["fines", "attendance"]


# --------------------------------------------------------------------------- #
# Sinxronizasiya konfliktləri (`sync_conflict_repository.py`)
# --------------------------------------------------------------------------- #


def _conflict_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": uuid.uuid4(),
        "table_name": "fines",
        "record_id": uuid.uuid4(),
        "local_version": {"amount": "25.00"},
        "remote_version": {"amount": "50.00"},
        "detected_at": NOW,
    }
    row.update(overrides)
    return row


def test_open_conflicts_are_ordered_and_limited_by_the_query() -> None:
    rows = [_conflict_row(), _conflict_row(table_name="tasks")]
    repo, conn = _build(PostgresSyncConflictRepository, [("FROM sync_conflicts", rows)])

    items = repo.list_open(TENANT, limit=25)

    assert [item.table_name for item in items] == ["fines", "tasks"]
    sql, params = conn.executed[-1]
    assert "resolved_at IS NULL" in sql
    assert "ORDER BY detected_at" in sql
    assert params == (TENANT, 25)


def test_a_jsonb_column_delivered_as_text_is_still_parsed() -> None:
    """Sürücü `jsonb`-i mətn kimi qaytara bilər — sahə müqayisəsi pozulmamalıdır."""
    row = _conflict_row(
        local_version=json.dumps({"amount": "25.00"}),
        remote_version=json.dumps({"amount": "50.00"}),
    )
    repo, _ = _build(PostgresSyncConflictRepository, [("FROM sync_conflicts", [row])])

    item = repo.get(row["id"])

    assert item is not None
    assert item.differing_fields() == ["amount"]


def test_a_non_object_version_column_reads_as_an_empty_dict() -> None:
    """Sərhəd: `NULL`/massiv — ekran çökmür, sadəcə fərq göstərmir."""
    row = _conflict_row(local_version=None, remote_version="[1, 2]")
    repo, _ = _build(PostgresSyncConflictRepository, [("FROM sync_conflicts", [row])])

    item = repo.get(row["id"])

    assert item is not None
    assert item.local_version == {}
    assert item.remote_version == {}


def test_a_missing_conflict_returns_none() -> None:
    repo, _ = _build(PostgresSyncConflictRepository, [("FROM sync_conflicts", [])])

    assert repo.get(uuid.uuid4()) is None


def test_the_open_counter_is_zero_when_the_table_is_empty() -> None:
    repo, _ = _build(PostgresSyncConflictRepository, [("count(*)", [])])

    assert repo.open_count(TENANT) == 0


def test_the_open_counter_reads_the_aggregate() -> None:
    repo, _ = _build(PostgresSyncConflictRepository, [("count(*)", [{"total": 7}])])

    assert repo.open_count(TENANT) == 7


def test_resolving_is_idempotent_by_the_resolved_at_guard() -> None:
    """İki HR eyni anda həll etsə İKİNCİSİ heç nə dəyişməməlidir."""
    from src.application.use_cases.sync_conflicts import Resolution

    repo, conn = _build(PostgresSyncConflictRepository)
    conflict_id = uuid.uuid4()

    repo.resolve(
        conflict_id,
        resolution=Resolution.MERGED,
        resolved_by=ACTOR,
        resolved_at=NOW,
        note="Hər ikisindən götürüldü",
    )

    sql, params = conn.executed[-1]
    assert "UPDATE sync_conflicts" in sql
    assert "resolved_at IS NULL" in sql, "İdempotentlik şərti olmadan son yazan qazanardı"
    assert "local_version" not in sql, "Versiya sütunlarına TOXUNULMUR (bölmə 5)"
    assert params[0] == "MERGED"
    assert params[1] == ACTOR


# --------------------------------------------------------------------------- #
# Dəstək müraciətləri (`support_repositories.py`)
# --------------------------------------------------------------------------- #


def _ticket_row(ticket_id: SupportTicketId, *, last_read: datetime | None) -> dict[str, Any]:
    return {
        "id": ticket_id,
        "subject": "Server cavab vermir",
        "status": "WAITING_CUSTOMER",
        "created_at": NOW,
        "customer_last_read_at": last_read,
    }


def _message_row(*, from_developer: bool, created_at: datetime) -> dict[str, Any]:
    return {
        "id": SupportMessageId(uuid.uuid4()),
        "ticket_id": SupportTicketId(uuid.uuid4()),
        "sender_id": None if from_developer else ACTOR,
        "body": "mesaj",
        "is_from_developer": from_developer,
        "created_at": created_at,
    }


def test_no_open_ticket_returns_none_instead_of_raising() -> None:
    repo, conn = _build(PostgresSupportTicketRepository, [("FROM support_tickets", [])])

    assert repo.find_open_ticket(TENANT) is None
    assert "status <> 'CLOSED'" in _sql(conn), "WAITING_CUSTOMER də açıq sayılır"


def test_the_unread_counter_only_counts_developer_messages_after_the_last_read() -> None:
    """Nişan istifadəçinin ÖZ mesajlarını saymamalıdır."""
    ticket_id = SupportTicketId(uuid.uuid4())
    last_read = NOW
    plan = [
        (
            "FROM support_messages",
            [
                _message_row(from_developer=True, created_at=last_read - timedelta(hours=1)),
                _message_row(from_developer=True, created_at=last_read + timedelta(minutes=5)),
                _message_row(from_developer=False, created_at=last_read + timedelta(minutes=9)),
            ],
        ),
        ("FROM support_tickets", [_ticket_row(ticket_id, last_read=last_read)]),
    ]
    repo, _ = _build(PostgresSupportTicketRepository, plan)

    thread = repo.get_thread(ticket_id)

    assert thread is not None
    assert thread.unread_from_developer == 1
    assert thread.is_open is True
    assert len(thread.messages) == 3


def test_a_never_read_thread_counts_every_developer_message() -> None:
    """Sərhəd: `customer_last_read_at IS NULL` — hamısı oxunmamışdır."""
    ticket_id = SupportTicketId(uuid.uuid4())
    plan = [
        (
            "FROM support_messages",
            [
                _message_row(from_developer=True, created_at=NOW),
                _message_row(from_developer=True, created_at=NOW + timedelta(minutes=1)),
            ],
        ),
        ("FROM support_tickets", [_ticket_row(ticket_id, last_read=None)]),
    ]
    repo, _ = _build(PostgresSupportTicketRepository, plan)

    thread = repo.get_thread(ticket_id)

    assert thread is not None
    assert thread.unread_from_developer == 2


def test_a_missing_thread_returns_none() -> None:
    repo, _ = _build(PostgresSupportTicketRepository, [("FROM support_tickets", [])])

    assert repo.get_thread(SupportTicketId(uuid.uuid4())) is None


def test_appending_a_message_also_touches_the_ticket_row() -> None:
    """Yeni cavab siyahının BAŞINA qalxmalıdır — `updated_at` trigger-i UPDATE istəyir."""
    repo, conn = _build(PostgresSupportTicketRepository)
    ticket_id = SupportTicketId(uuid.uuid4())

    repo.append_message(
        message_id=SupportMessageId(uuid.uuid4()),
        ticket_id=ticket_id,
        sender_id=ACTOR,
        body="Salam",
        is_from_developer=False,
    )

    assert "INSERT INTO support_messages" in conn.executed[0][0]
    assert "UPDATE support_tickets SET status = status" in conn.executed[1][0]
    assert conn.executed[1][1] == (ticket_id,)


def test_marking_read_is_scoped_to_the_tenant() -> None:
    """RLS-ə ƏLAVƏ ikinci qat — `tenant_id` şərti sorğuda AÇIQ olmalıdır."""
    repo, conn = _build(PostgresSupportTicketRepository)
    ticket_id = SupportTicketId(uuid.uuid4())

    repo.mark_read(ticket_id, up_to=NOW)

    sql, params = conn.executed[-1]
    assert "tenant_id = %s" in sql
    assert params == (NOW, ticket_id, TENANT)


# --------------------------------------------------------------------------- #
# Plugin reyestri və nüsxə kataloqu (`platform_repositories.py`)
# --------------------------------------------------------------------------- #


def _plugin_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": uuid.uuid4(),
        "name": "kompas-erp-bridge",
        "version": "1.2.0",
        "publisher": "KompasOS",
        "status": "PENDING_APPROVAL",
        "signature_verified": True,
    }
    row.update(overrides)
    return row


def test_a_plugin_without_a_publisher_is_labelled_not_left_blank() -> None:
    """Naşir imza yoxlamasının ƏN vacib sahəsidir — boş xana onu gizlədərdi."""
    repo, _ = _build(PostgresPluginRegistry, [("FROM plugins", [_plugin_row(publisher=None)])])

    plugins = repo.list_all(TENANT)

    assert plugins[0].publisher == "Naməlum naşir"
    assert plugins[0].status is PluginStatus.PENDING_APPROVAL


def test_a_plugin_lookup_is_scoped_to_the_tenant() -> None:
    row = _plugin_row()
    repo, conn = _build(PostgresPluginRegistry, [("FROM plugins", [row])])

    plugin = repo.get(str(row["id"]))

    assert plugin is not None
    assert plugin.plugin_id == str(row["id"])
    sql, params = conn.executed[-1]
    assert "AND tenant_id = %s" in sql
    assert params[1] == TENANT


def test_a_missing_plugin_returns_none() -> None:
    repo, _ = _build(PostgresPluginRegistry, [("FROM plugins", [])])

    assert repo.get(str(uuid.uuid4())) is None


def test_reinstalling_the_same_version_resets_the_approval() -> None:
    """Yeni bayt axını YENİ təsdiq deməkdir — `approved_by` sıfırlanır."""
    plugin_id = uuid.uuid4()
    repo, conn = _build(PostgresPluginRegistry, [("INSERT INTO plugins", [{"id": plugin_id}])])
    manifest = PluginManifest(
        name="kompas-erp-bridge",
        version="1.2.0",
        publisher="KompasOS",
        capabilities=frozenset({PluginCapability.READ_AGGREGATED_METRICS}),
        entry_point="bridge:main",
    )

    returned = repo.install(TENANT, manifest=manifest, digest="sha256:aa", installed_by=ACTOR)

    sql, params = conn.executed[-1]
    assert returned == str(plugin_id)
    assert "ON CONFLICT (tenant_id, name, version)" in sql
    assert "approved_by = NULL" in sql
    assert "status = 'PENDING_APPROVAL'" in sql
    assert json.loads(params[5])["name"] == "kompas-erp-bridge"


def test_approval_fills_the_two_columns_the_db_check_requires() -> None:
    """`chk_plugin_approved`: `APPROVED` yalnız `approved_by` dolu olduqda."""
    repo, conn = _build(PostgresPluginRegistry)

    repo.set_status("pl-1", PluginStatus.APPROVED, changed_by=ACTOR)

    sql, params = conn.executed[-1]
    assert "approved_by = CASE WHEN %s THEN %s::uuid" in sql
    assert params[1] is True and params[3] is True
    assert params[2] == ACTOR


def test_a_non_approval_status_leaves_the_approver_columns_untouched() -> None:
    repo, conn = _build(PostgresPluginRegistry)

    repo.set_status("pl-1", PluginStatus.DISABLED, changed_by=ACTOR)

    params = conn.executed[-1][1]
    assert params[0] == "DISABLED"
    assert params[1] is False and params[3] is False


def test_removing_a_plugin_deletes_the_row_physically() -> None:
    """Kataloq soft-delete qaydası burada TƏTBİQ OLUNMUR (modul başlığı)."""
    repo, conn = _build(PostgresPluginRegistry)

    repo.remove("pl-1")

    sql, params = conn.executed[-1]
    assert sql.startswith("DELETE FROM plugins")
    assert params == ("pl-1", TENANT)


def _backup_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "tenant_id": TENANT,
        "backup_type": "NIGHTLY",
        "storage_ref": "/nusxeler/2026-08-10.dump",
        "size_bytes": 5 * 1024 * 1024,
        "checksum": "sha256:abc",
        "retention_until": date(2026, 9, 10),
        "created_at": NOW,
    }
    row.update(overrides)
    return row


def test_a_backup_without_a_size_reads_as_zero_not_none() -> None:
    """Sərhəd: `NULL` ölçü — `RestorePoint.size_mb` `TypeError` ilə çökməməlidir."""
    plan = [("FROM backup_records", [_backup_row(size_bytes=None)])]
    repo, _ = _build(PostgresBackupCatalog, plan)

    records = repo.list_available(TENANT)

    assert records[0].size_bytes == 0


def test_expired_backups_are_still_listed() -> None:
    """Süzsək istifadəçi «nüsxə yoxdur» görər və müddətin bitdiyini bilməzdi."""
    repo, conn = _build(
        PostgresBackupCatalog,
        [("FROM backup_records", [_backup_row(retention_until=date(2026, 1, 1))])],
    )

    records = repo.list_available(TENANT, limit=5)

    assert records[0].is_expired(date(2026, 8, 10)) is True
    sql, params = conn.executed[-1]
    assert "ORDER BY created_at DESC" in sql
    assert params == (TENANT, 5)


def test_an_empty_catalog_returns_an_empty_list() -> None:
    repo, _ = _build(PostgresBackupCatalog, [("FROM backup_records", [])])

    assert repo.list_available(TENANT) == []


def test_the_store_scope_of_a_repository_comes_from_the_tenant_context() -> None:
    """Kontekst dəyişəndə sorğu şərti də dəyişməlidir — sabit qalmamalıdır."""
    other = TenantId(uuid.uuid4())
    conn = _FakeConnection()
    repo = PostgresSupportTicketRepository(conn, _Context(other))  # type: ignore[arg-type]

    repo.mark_read(SupportTicketId(uuid.uuid4()), up_to=NOW)

    assert conn.executed[-1][1][2] == other, "Şərt `TENANT`-a deyil, KONTEKSTƏ bağlıdır"


# --------------------------------------------------------------------------- #
# İş axını repository-ləri (`workflow_repositories.py`)
# --------------------------------------------------------------------------- #


def _swap_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "tenant_id": TENANT,
        "employee_id": ACTOR,
        "store_id": uuid.uuid4(),
        "target_date": date(2026, 8, 15),
        "requested_mode_id": None,
        "reason": "Ailə vəziyyəti",
        "status": "PENDING_APPROVAL",
        "manager_note": None,
        "manager_id": None,
        "decided_by": None,
        "decision_reason": None,
        "decided_at": None,
        "created_at": NOW,
    }
    row.update(overrides)
    return row


def test_a_restored_swap_request_emits_no_domain_event() -> None:
    """Bərpa edilən aqreqat hadisə YAYMAMALIDIR (CLAUDE.md §3).

    Əks halda hər siyahı açılışı `ShiftSwapRequested` hadisələri yayardı və
    eyni bildiriş hər ekran yenilənməsində təkrarlanardı.
    """
    row = _swap_row()
    repo, _ = _build(PostgresShiftSwapRepository, [("FROM shift_swap_requests", [row])])

    request = repo.get(row["id"])

    assert request is not None
    assert request.has_pending_events is False, "Repo-dan gələn aqreqat hadisə toplamamalıdır"
    assert request.store_id == row["store_id"], "`store_id` JOIN-dən gəlir"


def test_the_pending_swap_filter_adds_the_store_clause_only_when_asked() -> None:
    """Dinamik `WHERE` YALNIZ sabit sətir siyahısından qurulur (CLAUDE.md §4)."""
    repo, conn = _build(PostgresShiftSwapRepository, [("FROM shift_swap_requests", [])])

    repo.list_pending(TENANT)
    without_store = conn.executed[-1]
    store_id = uuid.uuid4()
    repo.list_pending(TENANT, store_id=store_id)
    with_store = conn.executed[-1]

    assert "e.store_id = %s" not in without_store[0]
    assert without_store[1] == (TENANT,)
    assert "e.store_id = %s" in with_store[0]
    assert with_store[1] == (TENANT, store_id)


def test_saving_a_swap_request_updates_only_the_decision_columns() -> None:
    """`ON CONFLICT` sorğunun İLKİN məzmununu (səbəb, tarix) geri yazmamalıdır."""
    repo, conn = _build(PostgresShiftSwapRepository)
    request = ShiftSwapRequest(
        request_id=ShiftSwapRequestId(uuid.uuid4()),
        tenant_id=TENANT,
        employee_id=ACTOR,
        target_date=date(2026, 8, 15),
        reason="Ailə vəziyyəti",
        created_at=NOW,
        emit_created_event=False,
    )

    repo.save(request)

    sql, params = conn.executed[-1]
    assert "ON CONFLICT (id) DO UPDATE" in sql
    assert "status = EXCLUDED.status" in sql
    assert "reason = EXCLUDED.reason" not in sql, "İlkin səbəb TOXUNULMAZ qalır"
    assert params[0] == request.id
    assert params[6] == "PENDING_APPROVAL"


def _appeal_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "tenant_id": TENANT,
        "fine_id": uuid.uuid4(),
        "employee_id": ACTOR,
        "reason": "Kamera qeydi səhvdir",
        "status": "PENDING",
        "decided_by": None,
        "decision_note": None,
        "decided_at": None,
        "new_amount": None,
        "created_at": NOW,
    }
    row.update(overrides)
    return row


def test_a_restored_appeal_emits_no_domain_event() -> None:
    row = _appeal_row()
    repo, _ = _build(PostgresFineAppealRepository, [("FROM fine_appeals", [row])])

    appeal = repo.get(row["id"])

    assert appeal is not None
    assert appeal.has_pending_events is False


def test_a_null_reduced_amount_stays_none_instead_of_becoming_zero() -> None:
    """Sərhəd: `NULL` = «məbləğ dəyişmədi», `0.00` = «tam ləğv» — eyni deyil."""
    repo, _ = _build(PostgresFineAppealRepository, [("FROM fine_appeals", [_appeal_row()])])

    appeal = repo.get_for_fine(uuid.uuid4())

    assert appeal is not None
    assert appeal.new_amount is None


def test_a_reduced_amount_is_wrapped_in_money() -> None:
    row = _appeal_row(status="APPROVED", new_amount=Decimal("25.00"), decided_at=NOW)
    repo, _ = _build(PostgresFineAppealRepository, [("FROM fine_appeals", [row])])

    appeal = repo.get(row["id"])

    assert appeal is not None
    assert appeal.new_amount == Money(Decimal("25.00"))


def test_missing_appeals_read_as_none_and_empty_lists() -> None:
    repo, _ = _build(PostgresFineAppealRepository, [("FROM fine_appeals", [])])

    assert repo.get(uuid.uuid4()) is None
    assert repo.get_for_fine(uuid.uuid4()) is None
    assert repo.list_pending(TENANT) == []
    assert repo.list_for_employee(ACTOR) == []


def test_saving_an_appeal_sends_a_plain_decimal_not_a_money_object() -> None:
    """SQL-ə `Money` getsəydi sürücü onu serialize edə bilməzdi."""
    repo, conn = _build(PostgresFineAppealRepository)
    appeal = FineAppeal(
        appeal_id=AppealId(uuid.uuid4()),
        tenant_id=TENANT,
        fine_id=FineId(uuid.uuid4()),
        employee_id=ACTOR,
        reason="Səbəb mətni",
        created_at=NOW,
        status=AppealStatus.APPROVED,
        new_amount=Money(Decimal("25.00")),
        emit_created_event=False,
    )

    repo.save(appeal)

    params = conn.executed[-1][1]
    assert params[9] == Decimal("25.00")
    assert not isinstance(params[9], Money)


def test_a_sheet_is_rewritten_line_by_line_after_a_delete() -> None:
    """Sətirlər TAM əvəzlənir — qismən yeniləmə köhnə sətri buraxardı."""
    stored_id = uuid.uuid4()
    repo, conn = _build(
        PostgresDailyAttendanceSheetRepository,
        [("SELECT id FROM daily_attendance_sheets", [{"id": stored_id}])],
    )
    store_id = uuid.uuid4()
    sheet = DailyAttendanceSheet(
        sheet_id=new_daily_sheet_id(),
        tenant_id=TENANT,
        store_id=store_id,  # type: ignore[arg-type]
        sheet_date=date(2026, 8, 10),
        lines=[SheetLine(employee_id=ACTOR, auto_status=AutoAttendanceStatus.VERIFIED)],
    )

    repo.save(sheet)

    statements = [item[0] for item in conn.executed]
    assert "INSERT INTO daily_attendance_sheets" in statements[0]
    assert "DELETE FROM daily_attendance_sheet_lines" in statements[2]
    assert conn.executed[2][1] == (stored_id,), "Sətirlər FAKTİKİ id ilə yazılır"
    assert "INSERT INTO daily_attendance_sheet_lines" in statements[3]
    assert conn.executed[3][1][0] == stored_id


def test_a_sheet_read_back_carries_its_lines_and_manager_note() -> None:
    sheet_id = uuid.uuid4()
    store_id = uuid.uuid4()
    plan = [
        (
            "FROM daily_attendance_sheet_lines",
            [
                {
                    "employee_id": ACTOR,
                    "auto_status": "LATE",
                    "planned_off": False,
                    "manager_note": "PIN işləmirdi",
                }
            ],
        ),
        (
            "FROM daily_attendance_sheets",
            [
                {
                    "id": sheet_id,
                    "tenant_id": TENANT,
                    "store_id": store_id,
                    "sheet_date": date(2026, 8, 10),
                    "is_confirmed": True,
                    "confirmed_by": ACTOR,
                    "confirmed_at": NOW,
                    "manager_note": "Gün problemsiz keçdi",
                }
            ],
        ),
    ]
    repo, _ = _build(PostgresDailyAttendanceSheetRepository, plan)

    sheet = repo.get_for_day(store_id, date(2026, 8, 10))

    assert sheet is not None
    assert sheet.is_confirmed is True
    assert sheet.manager_note == "Gün problemsiz keçdi"
    assert sheet.lines[0].auto_status is AutoAttendanceStatus.LATE
    assert sheet.lines[0].manager_note == "PIN işləmirdi"


def test_a_missing_sheet_returns_none() -> None:
    repo, _ = _build(PostgresDailyAttendanceSheetRepository, [("FROM daily_attendance_sheets", [])])

    assert repo.get_for_day(uuid.uuid4(), date(2026, 8, 10)) is None
    assert repo.list_unconfirmed(TENANT, up_to=date(2026, 8, 10)) == []


def test_a_past_day_is_reported_as_over_so_absences_become_visible() -> None:
    """Bölmə 3: gün bitməyibsə «qayıb» yazılmır — sərhəd bugünkü tarixdir."""
    row = {
        "employee_id": ACTOR,
        "planned_off": False,
        "check_in_status": None,
        "is_late": False,
        "late_minutes": None,
        "is_outside": False,
    }
    repo, _ = _build(PostgresAttendanceFactProvider, [("FROM employees", [row])])
    today = datetime.now(UTC).date()

    past = repo.facts_for(uuid.uuid4(), today - timedelta(days=1))
    current = repo.facts_for(uuid.uuid4(), today)

    assert past[0].day_is_over is True
    assert current[0].day_is_over is False
    assert past[0].late_minutes == 0, "`NULL` dəqiqə sıfıra çevrilməlidir"


def test_check_in_status_is_translated_into_two_independent_flags() -> None:
    rows = [
        {
            "employee_id": ACTOR,
            "planned_off": False,
            "check_in_status": "VERIFIED",
            "is_late": True,
            "late_minutes": 12,
            "is_outside": False,
        },
        {
            "employee_id": ACTOR,
            "planned_off": True,
            "check_in_status": "PENDING_VERIFICATION",
            "is_late": False,
            "late_minutes": 0,
            "is_outside": True,
        },
    ]
    repo, _ = _build(PostgresAttendanceFactProvider, [("FROM employees", rows)])

    facts = repo.facts_for(uuid.uuid4(), date(2026, 8, 10))

    assert (facts[0].has_verified_check_in, facts[0].is_pending_verification) == (True, False)
    assert facts[0].is_late is True
    assert facts[0].late_minutes == 12
    assert (facts[1].has_verified_check_in, facts[1].is_pending_verification) == (False, True)
    assert facts[1].is_currently_outside is True
    assert facts[1].planned_off is True


# --------------------------------------------------------------------------- #
# Hesabat faktları (`report_repositories.py`)
# --------------------------------------------------------------------------- #


def test_an_employee_with_no_records_still_appears_with_zeroes() -> None:
    """İşçi siyahısı ƏSASDIR — sayğacı olmayan işçi sətirdən DÜŞMÜR."""
    row = {
        "employee_id": ACTOR,
        "full_name": "Aysel Quliyeva",
        "store_name": "—",
        "position_name": "—",
        "norm_work_days": 0,
        "off_days": 0,
        "actual_worked_days": 0,
        "unauthorized_absences": 0,
    }
    repo, conn = _build(PostgresReportFactProvider, [("FROM employees", [row])])

    facts = repo.attendance_facts(TENANT, start=date(2026, 8, 1), end=date(2026, 8, 31))

    assert facts[0].actual_worked_days == 0
    assert facts[0].store_name == "—"
    assert conn.executed[-1][1][-1] is None, "Süzgəc yoxdursa `NULL` ötürülür"


def test_the_store_filter_is_passed_twice_for_the_null_check() -> None:
    """`(%s::uuid IS NULL OR e.store_id = %s::uuid)` — hər iki yerə eyni dəyər."""
    store_id = uuid.uuid4()
    repo, conn = _build(PostgresReportFactProvider, [("FROM employees", [])])

    repo.attendance_facts(TENANT, start=date(2026, 8, 1), end=date(2026, 8, 31), store_id=store_id)

    params = conn.executed[-1][1]
    assert params[-1] == store_id
    assert params[-2] == store_id


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, "0.00"), (0, "0"), (1240, "1240"), ("980.50", "980.50")],
)
def test_a_sum_of_any_driver_type_becomes_a_decimal(raw: Any, expected: str) -> None:
    """`sum()` `None`/`int`/`Decimal` qaytara bilər — üçü də normallaşdırılır."""
    assert _as_decimal(raw) == Decimal(expected)


def test_sales_facts_wrap_the_gross_amount_in_money() -> None:
    row = {
        "employee_id": ACTOR,
        "full_name": "Kamran Vəliyev",
        "store_name": "Bakı",
        "gross_sales": None,
        "earned_points": 0,
    }
    repo, _ = _build(PostgresReportFactProvider, [("FROM employees", [row])])

    facts = repo.sales_facts(TENANT, start=date(2026, 8, 1), end=date(2026, 8, 31))

    assert facts[0].gross_sales == Money(Decimal("0.00"))
    assert facts[0].earned_points == 0


def test_reversed_points_are_excluded_by_the_query_itself() -> None:
    """Uğurlu xal etirazı premiyaya getməməlidir — şərt SORĞUDA olmalıdır."""
    repo, conn = _build(PostgresReportFactProvider, [("FROM employees", [])])

    repo.sales_facts(TENANT, start=date(2026, 8, 1), end=date(2026, 8, 31))

    assert "pl.status = 'ACTIVE'" in conn.executed[-1][0]


# --------------------------------------------------------------------------- #
# Plan faktları — Faza 7 (dinamik norma + pro-rata mənbəyi)
# --------------------------------------------------------------------------- #


def _plan_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "employee_id": ACTOR,
        "hire_date": None,
        "is_active": True,
        "ended_on": None,
        "shift_date": date(2026, 8, 3),
        "is_off_day": False,
        "start_time": time(9, 0),
        "end_time": time(18, 0),
    }
    row.update(overrides)
    return row


def test_plan_rows_are_grouped_per_employee_with_their_schedules() -> None:
    rows = [
        _plan_row(shift_date=date(2026, 8, 3)),
        _plan_row(shift_date=date(2026, 8, 4), is_off_day=True, start_time=None, end_time=None),
    ]
    repo, _ = _build(PostgresReportFactProvider, [("FROM employees", rows)])

    facts = repo.plan_facts(TENANT, start=date(2026, 8, 1), end=date(2026, 8, 31))

    assert len(facts) == 1
    assert len(facts[0].planned_days) == 2
    assert facts[0].planned_days[0].schedule == TimeRange(start=time(9, 0), end=time(18, 0))
    assert facts[0].planned_days[1].is_off_day is True
    assert facts[0].planned_days[1].schedule is None


def test_an_employee_without_any_plan_row_still_yields_an_empty_plan() -> None:
    """`LEFT JOIN` — planı olmayan işçi siyahıdan DÜŞMÜR (norma 0 siqnalı)."""
    repo, _ = _build(PostgresReportFactProvider, [("FROM employees", [_plan_row(shift_date=None)])])

    facts = repo.plan_facts(TENANT, start=date(2026, 8, 1), end=date(2026, 8, 31))

    assert facts[0].planned_days == ()
    assert facts[0].employment.started_on is None


def test_an_active_employee_never_gets_an_employment_end_date() -> None:
    """Köhnə `deactivated_at` qalığı aktiv işçini öz normasından məhrum etməməlidir."""
    rows = [_plan_row(is_active=True, ended_on=date(2026, 8, 10), hire_date=date(2026, 8, 5))]
    repo, _ = _build(PostgresReportFactProvider, [("FROM employees", rows)])

    window = repo.plan_facts(TENANT, start=date(2026, 8, 1), end=date(2026, 8, 31))[0].employment

    assert window.started_on == date(2026, 8, 5)
    assert window.ended_on is None


def test_a_deactivated_employee_carries_its_last_day() -> None:
    rows = [_plan_row(is_active=False, ended_on=date(2026, 8, 10))]
    repo, _ = _build(PostgresReportFactProvider, [("FROM employees", rows)])

    window = repo.plan_facts(TENANT, start=date(2026, 8, 1), end=date(2026, 8, 31))[0].employment

    assert window.ended_on == date(2026, 8, 10)


def test_the_plan_query_reads_deactivation_in_the_store_timezone() -> None:
    """UTC-də gecə çıxan işçinin son iş günü BİR GÜN sürüşməməlidir."""
    repo, conn = _build(PostgresReportFactProvider, [("FROM employees", [])])

    repo.plan_facts(TENANT, start=date(2026, 8, 1), end=date(2026, 8, 31))

    sql, params = conn.executed[-1]
    assert "AT TIME ZONE COALESCE(s.timezone, %s)" in sql
    assert params[0] == DEFAULT_TIMEZONE


def test_the_plan_query_does_not_filter_out_deactivated_work_modes() -> None:
    """Soft delete: keçmiş növbənin rejimi «naməlum»a çevrilməməlidir."""
    repo, conn = _build(PostgresReportFactProvider, [("FROM employees", [])])

    repo.plan_facts(TENANT, start=date(2026, 8, 1), end=date(2026, 8, 31))

    sql = conn.executed[-1][0]
    assert "LEFT JOIN work_modes wm ON wm.id = sa.work_mode_id" in sql
    assert "wm.is_active" not in sql


def test_a_degenerate_work_mode_becomes_an_unscheduled_day() -> None:
    """Başlanğıc = bitmə: `TimeRange` qəbul etmir — hesabat çökmür, `None` olur."""
    rows = [_plan_row(start_time=time(9, 0), end_time=time(9, 0))]
    repo, _ = _build(PostgresReportFactProvider, [("FROM employees", rows)])

    facts = repo.plan_facts(TENANT, start=date(2026, 8, 1), end=date(2026, 8, 31))

    assert facts[0].planned_days[0].schedule is None


def test_the_plan_query_passes_the_store_filter_twice() -> None:
    store_id = uuid.uuid4()
    repo, conn = _build(PostgresReportFactProvider, [("FROM employees", [])])

    repo.plan_facts(TENANT, start=date(2026, 8, 1), end=date(2026, 8, 31), store_id=store_id)

    params = conn.executed[-1][1]
    assert params[-1] == store_id
    assert params[-2] == store_id


# --------------------------------------------------------------------------- #
# Vahid İstisna Jurnalı (`exception_repositories.py`)
# --------------------------------------------------------------------------- #


def _exception_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "tenant_id": TENANT,
        "source": "BEHAVIOR_ANOMALY",
        "employee_id": ACTOR,
        "store_id": uuid.uuid4(),
        "detail": "Check-in vaxtı baz xəttindən kənarlaşıb",
        "context_json": {"kenarlasma": 42},
        "severity": "MEDIUM",
        "status": "OPEN",
        "dedupe_key": "BEHAVIOR_ANOMALY:2026-08-10",
        "reviewed_by": None,
        "reviewed_at": None,
        "review_note": None,
        "created_at": NOW,
    }
    row.update(overrides)
    return row


def test_an_exception_row_is_restored_without_emitting_an_event() -> None:
    """Repo-dan bərpa hadisə YAYSAYDI, hər oxu "yeni anomaliya" bildirişi olardı."""
    repo, _ = _build(PostgresExceptionRepository, [("FROM exceptions", [_exception_row()])])

    record = repo.get(ExceptionId(uuid.uuid4()))

    assert record is not None
    assert not record.has_pending_events
    assert record.severity is ExceptionSeverity.MEDIUM
    assert record.context["kenarlasma"] == 42


def test_a_jsonb_column_stored_as_text_is_still_readable() -> None:
    """Sürücü `jsonb`-i obyekt qaytarır, köhnə yazı sətir ola bilər — hər ikisi."""
    repo, _ = _build(
        PostgresExceptionRepository,
        [("FROM exceptions", [_exception_row(context_json='{"a": 1}')])],
    )

    record = repo.get(ExceptionId(uuid.uuid4()))

    assert record is not None
    assert record.context == {"a": 1}


@pytest.mark.parametrize("raw", [None, "[]", "salam", 7])
def test_a_broken_context_column_becomes_an_empty_dict(raw: Any) -> None:
    """Yararsız `context_json` ekranı çökdürməməlidir — sətir yenə göstərilir."""
    repo, _ = _build(
        PostgresExceptionRepository,
        [("FROM exceptions", [_exception_row(context_json=raw)])],
    )

    record = repo.get(ExceptionId(uuid.uuid4()))

    assert record is not None
    assert record.context == {}


def test_the_dedupe_lookup_does_not_filter_by_status() -> None:
    """Rədd edilmiş tapıntı da "artıq mövcuddur" sayılmalıdır."""
    repo, conn = _build(PostgresExceptionRepository, [("FROM exceptions", [])])

    repo.find_by_dedupe(TENANT, source="BEHAVIOR_ANOMALY", dedupe_key="K-1")

    sql, params = conn.executed[-1]
    assert "status" not in sql.split("WHERE")[-1]
    assert params == (TENANT, "BEHAVIOR_ANOMALY", "K-1")


def test_an_empty_store_scope_never_reaches_the_database() -> None:
    """FAIL-SAFE: "heç bir mağazaya çıxış yoxdur" halında sorğu göndərilmir."""
    repo, conn = _build(PostgresExceptionRepository, [("FROM exceptions", [])])

    assert repo.list_open(TENANT, store_ids=[]) == []
    assert conn.executed == []


def test_the_open_queue_filters_by_tenant_status_and_store() -> None:
    store_id = uuid.uuid4()
    repo, conn = _build(PostgresExceptionRepository, [("FROM exceptions", [])])

    repo.list_open(TENANT, store_ids=[store_id], limit=25)  # type: ignore[list-item]

    sql, params = conn.executed[-1]
    assert "tenant_id = %s" in sql
    assert "status = 'OPEN'" in sql
    assert "store_id = ANY(%s)" in sql
    assert params == (TENANT, [store_id], 25)


def test_the_upsert_never_rewrites_the_detection_facts() -> None:
    """`detail`/`created_at` dəyişsəydi, qərar verənin gördüyü mətn itərdi."""
    record = ExceptionRecord(
        exception_id=ExceptionId(uuid.uuid4()),
        tenant_id=TENANT,
        source="BEHAVIOR_ANOMALY",
        employee_id=ACTOR,
        store_id=uuid.uuid4(),  # type: ignore[arg-type]
        detail="Check-in vaxtı baz xəttindən kənarlaşıb",
        created_at=NOW,
        context={"kenarlasma": 42},
        emit_created_event=False,
    )
    repo, conn = _build(PostgresExceptionRepository)

    repo.save(record)

    sql, params = conn.executed[-1]
    updated = sql.split("DO UPDATE")[-1]
    assert "status" in updated
    assert "review_note" in updated
    assert "detail" not in updated
    assert "created_at" not in updated
    assert json.loads(params[6]) == {"kenarlasma": 42}


def test_system_sources_are_visible_to_every_tenant() -> None:
    """`tenant_id IS NULL` şərti olmasa `BEHAVIOR_ANOMALY` heç kimə görünməzdi."""
    repo, conn = _build(
        PostgresExceptionSourceCatalog,
        [
            (
                "FROM exception_sources",
                [
                    {
                        "code": "BEHAVIOR_ANOMALY",
                        "name_az": "Davranış anomaliyası",
                        "description_az": None,
                        "default_severity": "HIGH",
                        "is_active": True,
                    }
                ],
            )
        ],
    )

    source = repo.get(TENANT, " behavior_anomaly ")

    sql, params = conn.executed[-1]
    assert "tenant_id IS NULL" in sql
    assert params == ("BEHAVIOR_ANOMALY", TENANT)
    assert source is not None
    assert source.default_severity is ExceptionSeverity.HIGH


def test_the_catalog_hides_deactivated_sources_by_default() -> None:
    repo, conn = _build(PostgresExceptionSourceCatalog, [("FROM exception_sources", [])])

    repo.list_all(TENANT)
    active_only = conn.executed[-1][0]
    repo.list_all(TENANT, include_inactive=True)
    everything = conn.executed[-1][0]

    assert "is_active" in active_only
    assert "is_active" not in everything.split("WHERE")[-1]


def test_an_unknown_severity_in_the_catalog_falls_back() -> None:
    """Root sətri əl ilə redaktə etsə, ekran çökmür — MEDIUM göstərilir."""
    repo, _ = _build(
        PostgresExceptionSourceCatalog,
        [
            (
                "FROM exception_sources",
                [
                    {
                        "code": "BEHAVIOR_ANOMALY",
                        "name_az": "Davranış anomaliyası",
                        "description_az": "İzah",
                        "default_severity": "ÇOX_PİS",
                        "is_active": False,
                    }
                ],
            )
        ],
    )

    (source,) = repo.list_all(TENANT, include_inactive=True)

    assert source.default_severity is ExceptionSeverity.MEDIUM
    assert source.is_active is False


# --------------------------------------------------------------------------- #
# `CredentialWriter` — protokolun TƏTBİQİ ümumiyyətlə yox idi
#
# `composition.py` `credentials=uow.employees` ötürür, yəni protokolu məhz
# `PostgresEmployeeRepository` ödəməlidir. Metodlar isə YAZILMAMIŞDI:
# `uow.employees` `Any` qaytardığı üçün nə mypy, nə də hər hansı test bunu
# görmürdü və `[Şifrəni Yenilə]` düyməsi istehsalatda `AttributeError` ilə
# çökürdü. Aşağıdakı testlər "metod var" ilə kifayətlənmir — SAXLANMIŞ heşin
# verilən xam sirri DOĞRULADIĞINI yoxlayır.
# --------------------------------------------------------------------------- #

#: Protokolun tələb etdiyi metodlar — SİYAHI ƏL İLƏ YAZILMIR, protokolun
#: özündən çıxarılır ki, ora yeni metod əlavə olunanda test onu tutsun.
_CREDENTIAL_WRITER_METHODS = sorted(
    name
    for name, value in vars(CredentialWriter).items()
    if callable(value) and not name.startswith("_")
)


@pytest.fixture
def _pepper(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEC-005 pepper-i — heşləmə onsuz qurula bilməz."""
    monkeypatch.setenv("KOMPASOS_HASH_PEPPER", "a" * 64)


def _credential_params(conn: _FakeConnection) -> tuple[Any, ...]:
    """`update_credentials()` UPDATE-inin parametrləri: (pin, password, pepper, …)."""
    for sql, params in conn.executed:
        if "COALESCE(%s, password_hash)" in sql:
            return params
    raise AssertionError("Sirr UPDATE-i ümumiyyətlə icra olunmadı")


def test_the_employee_repository_satisfies_the_credential_writer_protocol() -> None:
    """Kompozisiya kökü onu bu protokol kimi ötürür — metodlar MÖVCUD olmalıdır."""
    repo, _ = _build(PostgresEmployeeRepository)

    missing = [
        name for name in _CREDENTIAL_WRITER_METHODS if not callable(getattr(repo, name, None))
    ]

    assert _CREDENTIAL_WRITER_METHODS, "Protokoldan metod siyahısı çıxarılmadı — qapı kordur"
    assert missing == [], f"`CredentialWriter` metodları yoxdur: {missing}"


@pytest.mark.usefixtures("_pepper")
def test_set_password_stores_a_hash_that_verifies_the_raw_password() -> None:
    """Saxlanan heş verilən şifrəni doğrulamalıdır — «yazıldı» kifayət deyil."""
    from src.infrastructure.security.hashing import HashingService

    repo, conn = _build(PostgresEmployeeRepository)

    repo.set_password(ACTOR, raw_password="Güclü-Şifrə-2026!", must_change=True)

    params = _credential_params(conn)
    assert params[0] is None, "PIN heşinə TOXUNULMAMALIDIR (`COALESCE` davranışı)"
    assert HashingService().verify_password(params[1], "Güclü-Şifrə-2026!") is True
    # `pepper_version` də yazılır: yazılmasaydı yeni heş köhnə versiya ilə
    # yoxlanar və doğru şifrə də rədd edilərdi (SEC-005).
    assert params[2] == HashingService().current_pepper_version


@pytest.mark.usefixtures("_pepper")
def test_set_password_also_writes_the_must_change_flag() -> None:
    """Admin təyin etdiyi şifrə ilk girişdə MƏCBURİ dəyişdirilməlidir (bölmə 2)."""
    repo, conn = _build(PostgresEmployeeRepository)

    repo.set_password(ACTOR, raw_password="Güclü-Şifrə-2026!", must_change=True)

    sql, params = conn.executed[-1]
    assert "must_change_password" in sql
    assert params[0] is True
    assert "tenant_id = %s" in sql, "Kirayəçi şərti RLS-ə ƏLAVƏ ikinci qatdır"


@pytest.mark.usefixtures("_pepper")
def test_set_pin_binds_the_hash_to_the_employee_id() -> None:
    """PIN heşi `employee_id`-yə bağlıdır (SEC-005) — başqa işçidə uyğun gəlməməlidir."""
    from src.infrastructure.security.hashing import HashingService

    repo, conn = _build(PostgresEmployeeRepository)
    other = EmployeeId(uuid.uuid4())

    repo.set_pin(ACTOR, raw_pin="4821")

    params = _credential_params(conn)
    assert params[1] is None, "Şifrə heşinə TOXUNULMAMALIDIR"
    hashing = HashingService()
    assert hashing.verify_pin(params[0], "4821", employee_id=str(ACTOR)) is True
    assert hashing.verify_pin(params[0], "4821", employee_id=str(other)) is False


def test_clear_pin_lockout_resets_both_counter_and_deadline() -> None:
    """Yeni PIN tək başına kifayət etmir — bloklanmış işçi yenə gözləməli olardı."""
    repo, conn = _build(PostgresEmployeeRepository)

    repo.clear_pin_lockout(ACTOR)

    sql, params = conn.executed[-1]
    assert "pin_failed_attempts = 0" in sql
    assert "pin_locked_until = NULL" in sql
    assert params == (ACTOR, TENANT)
