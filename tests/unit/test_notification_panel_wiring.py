"""Bildiriş panelinin CANLI yolu (bölmə 7) — Faza 5/6 bağlantısı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TEST VAR
──────────────────────────────────────────────────────────────────────────────
`PostgresNotifier` istehsalatda REAL `INSERT INTO notifications` edir, lakin
paneli YALNIZ önizləmə rejimi doldururdu (`app.py:_install_overlays`). Yəni
yazılan hər bildiriş istifadəçiyə görünmürdü və header nişanı heç vaxt real
say almırdı — bölmə 7-nin in-app kanalı ölü idi.

Testlər Qt və baza TƏLƏB ETMİR: kontroller yalnız siqnal + setter müqaviləsinə
toxunur, repository isə saxta bağlantı ilə yoxlanılır (eyni naxış
`test_config_repositories.py`-dadır).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.domain.value_objects.identifiers import EmployeeId, TenantId
from src.infrastructure.persistence.notification_repositories import (
    NotificationRow,
    PostgresNotificationRepository,
)
from src.presentation.controllers.notifications import NotificationsController, _to_item

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
ACTOR = EmployeeId(uuid.uuid4())
NOW = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)


def _row(
    *,
    category: str = "FINE_APPEAL_PENDING",
    title: str = "Yeni cərimə etirazı",
    critical: bool = False,
    created_at: datetime = NOW,
    read_at: datetime | None = None,
) -> NotificationRow:
    return NotificationRow(
        id=uuid.uuid4(),
        category=category,
        title_az=title,
        body_az="İcazəsiz çıxış · 40 ₼",
        is_critical=critical,
        created_at=created_at,
        read_at=read_at,
    )


# --------------------------------------------------------------------------- #
# Saxta Qt + saxta sessiya
# --------------------------------------------------------------------------- #


class _Signal:
    """`Signal.connect/emit`-in test əvəzi — QApplication qurulmur."""

    def __init__(self) -> None:
        self._slots: list[Any] = []

    def connect(self, slot: Any) -> None:
        self._slots.append(slot)

    def emit(self, *args: Any) -> None:
        for slot in list(self._slots):
            slot(*args)


class _Panel:
    def __init__(self, *, visible: bool = False) -> None:
        self.notification_clicked = _Signal()
        self.mark_all_read_requested = _Signal()
        self.renders: list[list[dict[str, str]]] = []
        self._visible = visible

    def isVisible(self) -> bool:  # noqa: N802 - Qt adlandırması
        return self._visible

    def set_visible(self, value: bool) -> None:
        self._visible = value

    def set_notifications(self, items: list[dict[str, str]]) -> None:
        self.renders.append(items)


class _Header:
    def __init__(self) -> None:
        self.bell_clicked = _Signal()
        self.unread: list[int] = []

    def set_unread(self, count: int) -> None:
        self.unread.append(count)


class _Repo:
    def __init__(self, rows: list[NotificationRow]) -> None:
        self.rows = rows
        self.read_calls: list[tuple[uuid.UUID, EmployeeId]] = []
        self.all_calls: list[EmployeeId] = []
        self.list_calls = 0

    def list_for_recipient(self, recipient_id: EmployeeId) -> list[NotificationRow]:
        self.list_calls += 1
        assert recipient_id == ACTOR
        return self.rows

    def mark_read(self, notification_id: uuid.UUID, recipient_id: EmployeeId) -> int:
        self.read_calls.append((notification_id, recipient_id))
        return 1

    def mark_all_read(self, recipient_id: EmployeeId) -> int:
        self.all_calls.append(recipient_id)
        return len(self.rows)


class _Session:
    def __init__(self, repo: _Repo) -> None:
        self.notifications = repo
        self.committed = False

    def commit(self) -> None:
        self.committed = True

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _Context:
    def __init__(self, repo: _Repo) -> None:
        self.tenant_id = TENANT
        self.sessions: list[_Session] = []
        self._repo = repo

    def session(self, **_: Any) -> _Session:
        created = _Session(self._repo)
        self.sessions.append(created)
        return created


class _Actor:
    id = ACTOR


def _wire(rows: list[NotificationRow]) -> tuple[_Panel, _Header, _Repo, _Context]:
    repo = _Repo(rows)
    context = _Context(repo)
    panel, header = _Panel(), _Header()
    controller = NotificationsController(context, _Actor())  # type: ignore[arg-type]
    controller.attach(panel, header)  # type: ignore[arg-type]
    return panel, header, repo, context


# --------------------------------------------------------------------------- #
# Qoşulma və sayğac
# --------------------------------------------------------------------------- #


def test_panel_is_filled_and_badge_is_set_on_login() -> None:
    """Zəng nişanı istifadəçi ona TOXUNMADAN əvvəl doğru rəqəmi göstərməlidir."""
    panel, header, repo, _ = _wire([_row(), _row(read_at=NOW), _row()])

    assert repo.list_calls == 1
    assert len(panel.renders[0]) == 3
    assert header.unread == [2], "Oxunmuş sətir sayğaca düşməməlidir"


def test_bell_click_refreshes_only_when_the_panel_opens() -> None:
    """Bağlanış da sorğu göndərsəydi hər açıb-bağlama İKİ sorğu olardı.

    `app.py`-da `_toggle_notifications` zəng siqnalına ƏVVƏL qoşulur, yəni
    kontroller işə düşəndə görünürlük ARTIQ dəyişib. Test məhz həmin sıranı
    modelləyir: əvvəl görünürlük, sonra siqnal.
    """
    panel, header, repo, _ = _wire([_row()])
    after_attach = repo.list_calls

    panel.set_visible(True)
    header.bell_clicked.emit()
    assert repo.list_calls == after_attach + 1

    panel.set_visible(False)
    header.bell_clicked.emit()
    assert repo.list_calls == after_attach + 1, "Bağlanışda sorğu getməməlidir"


# --------------------------------------------------------------------------- #
# Yazı yolu — "oxundu"
# --------------------------------------------------------------------------- #


def test_clicking_a_row_marks_it_read_and_commits() -> None:
    """Commit unudulsa `PostgresUnitOfWork` geri qaytarır — nişan qalardı."""
    row = _row()
    panel, header, repo, context = _wire([row])

    panel.notification_clicked.emit(str(row.id))

    assert repo.read_calls == [(row.id, ACTOR)]
    assert context.sessions[1].committed, "Yazı sessiyası commit edilməlidir"
    assert repo.list_calls == 2, "Yazıdan sonra siyahı yenidən oxunmalıdır"
    assert len(header.unread) == 2


def test_mark_all_read_uses_a_single_write_then_refreshes() -> None:
    panel, _, repo, context = _wire([_row(), _row()])

    panel.mark_all_read_requested.emit()

    assert repo.all_calls == [ACTOR]
    assert context.sessions[1].committed
    assert repo.list_calls == 2


def test_invalid_notification_id_is_logged_not_crashed(monkeypatch: Any) -> None:
    """Yararsız açar örtüyü çökdürməməlidir — panel işləməyə davam edir."""
    from src.presentation.controllers import notifications as module

    recorded: list[str] = []

    class _Log:
        def warning(self, message: str, *, extra: dict[str, Any] | None = None) -> None:
            recorded.append(message)

        def exception(self, message: str, *, extra: dict[str, Any] | None = None) -> None:
            recorded.append(message)

    monkeypatch.setattr(module, "_error_log", _Log())
    panel, _, repo, _ = _wire([_row()])

    panel.notification_clicked.emit("bu-uuid-deyil")

    assert recorded == ["NOTIFICATION_ID_INVALID"]
    assert not repo.read_calls


def test_database_failure_leaves_the_panel_empty_instead_of_crashing(monkeypatch: Any) -> None:
    """Baza əlçatmazdırsa zəng boş qalır, örtük isə açıq (bax modul başlığı)."""
    from src.presentation.controllers import notifications as module

    class _Log:
        def exception(self, message: str, *, extra: dict[str, Any] | None = None) -> None:
            return None

    monkeypatch.setattr(module, "_error_log", _Log())

    class _BrokenContext:
        tenant_id = TENANT

        def session(self, **_: Any) -> Any:
            raise RuntimeError("baza əlçatmazdır")

    panel, header = _Panel(), _Header()
    controller = NotificationsController(_BrokenContext(), _Actor())  # type: ignore[arg-type]
    controller.attach(panel, header)  # type: ignore[arg-type]

    assert panel.renders == [[]]
    assert header.unread == [0]


# --------------------------------------------------------------------------- #
# Sətir → panel formatı (maketlə EYNİ açarlar)
# --------------------------------------------------------------------------- #


def test_item_keys_match_the_preview_contract() -> None:
    """Maket və canlı yol EYNİ açarları işlətməlidir (CLAUDE.md bölmə 6)."""
    from src.presentation import preview_data

    item = _to_item(_row(), now=NOW)
    assert set(item) == set(preview_data.NOTIFICATIONS[0])


def test_unread_flag_uses_the_string_form_the_widget_reads() -> None:
    """`NotificationItem` `notification.get("unread") == "1"` yoxlayır."""
    assert _to_item(_row(), now=NOW)["unread"] == "1"
    assert _to_item(_row(read_at=NOW), now=NOW)["unread"] == "0"


def test_unknown_critical_category_never_looks_informational() -> None:
    """Yeni modul naməlum kateqoriya yazsa da KRİTİK sətir seçilməlidir."""
    unknown = _to_item(_row(category="YENI_MODUL_XEBERDARLIGI", critical=True), now=NOW)
    assert unknown["kind"] == "error"

    quiet = _to_item(_row(category="YENI_MODUL_MELUMATI", critical=False), now=NOW)
    assert quiet["kind"] == "info"


def test_filter_buckets_match_the_three_chips() -> None:
    assert _to_item(_row(category="DUAL_CONTROL_PENDING"), now=NOW)["category"] == "approval"
    assert _to_item(_row(category="PAYMENT_REMINDER"), now=NOW)["category"] == "system"
    # Naməlum kateqoriya GİZLƏNMİR: «Sistem» qovluğuna düşür və «Hamısı»da görünür.
    assert _to_item(_row(category="YENI"), now=NOW)["category"] == "system"


def test_time_text_shortens_todays_rows() -> None:
    today = _to_item(_row(created_at=NOW - timedelta(hours=1)), now=NOW)
    yesterday = _to_item(_row(created_at=NOW - timedelta(days=1)), now=NOW)
    older = _to_item(_row(created_at=NOW - timedelta(days=7)), now=NOW)

    assert ":" in today["time"] and "Dünən" not in today["time"]
    assert yesterday["time"].startswith("Dünən ")
    assert "." in older["time"], "Bir həftəlik sətir tarixsiz göstərilə bilməz"


# --------------------------------------------------------------------------- #
# Repository — auditoriya və tenant şərti
# --------------------------------------------------------------------------- #


class _FakeCursor:
    def __init__(self, rows: list[dict[str, Any]], log: list[tuple[str, tuple[Any, ...]]]) -> None:
        self._rows = rows
        self._log = log
        self.rowcount = len(rows)

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self._log.append((" ".join(sql.split()), params))

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeConnection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.rows, self.executed)


class _TenantContext:
    tenant_id = TENANT


def _repository(rows: list[dict[str, Any]] | None = None) -> tuple[Any, _FakeConnection]:
    conn = _FakeConnection(rows)
    return PostgresNotificationRepository(conn, _TenantContext()), conn  # type: ignore[arg-type]


def test_listing_covers_personal_and_tenant_wide_rows() -> None:
    """`recipient_id IS NULL` sətirləri kəsilsəydi, onlar HEÇ KİMƏ görünməzdi."""
    repo, conn = _repository([])
    repo.list_for_recipient(ACTOR)

    sql, params = conn.executed[-1]
    assert "recipient_id = %s OR recipient_id IS NULL" in sql
    assert "tenant_id = %s" in sql, "RLS-ə ƏLAVƏ açıq tenant şərti olmalıdır"
    assert params[0] == TENANT
    assert params[1] == ACTOR


def test_marking_read_does_not_move_the_first_read_moment() -> None:
    repo, conn = _repository()
    repo.mark_read(uuid.uuid4(), ACTOR)

    sql, _ = conn.executed[-1]
    assert "read_at IS NULL" in sql, "Təkrar klik ilk oxunma vaxtını dəyişməməlidir"
    assert "UPDATE notifications SET read_at = now()" in sql


def test_mark_all_read_is_limited_to_the_visible_audience() -> None:
    repo, conn = _repository()
    repo.mark_all_read(ACTOR)

    sql, params = conn.executed[-1]
    assert "recipient_id = %s OR recipient_id IS NULL" in sql
    assert params == (TENANT, ACTOR)


def test_rows_are_hydrated_with_the_unread_flag() -> None:
    created = NOW - timedelta(minutes=5)
    repo, _ = _repository(
        [
            {
                "id": uuid.uuid4(),
                "category": "DUAL_CONTROL_PENDING",
                "title_az": "İkinci təsdiq gözlənilir",
                "body_az": "37 dəqiqəlik fərq",
                "is_critical": True,
                "created_at": created,
                "read_at": None,
            }
        ]
    )
    rows = repo.list_for_recipient(ACTOR)

    assert len(rows) == 1
    assert rows[0].is_unread
    assert rows[0].is_critical
    assert rows[0].created_at == created
