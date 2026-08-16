"""Sinxronizasiya konfliktləri ekranı və kontrolleri — G-1 (bölmə 5).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TESTLƏR VAR
──────────────────────────────────────────────────────────────────────────────
`SyncConflictUseCase` və `sync_conflicts` repository-si ARTIQ yazılmışdı,
«Sistem Sağlamlığı» ekranı isə «N sinxronizasiya konflikti həll gözləyir»
xəbərdarlığını göstərirdi — lakin GEDƏCƏK YER yox idi. Yəni istifadəçiyə
həll edə bilmədiyi problem göstərilirdi. Bu fayl həmin dalanın bir daha
açılmamasını qoruyur:

    * menyu maddəsi FAKTİKİ flag-ə bağlıdır (təxmin edilmiş ada yox);
    * qərar `resolve()`-a DOĞRU arqumentlərlə gedir;
    * hər qərardan sonra siyahı YENİDƏN oxunur (paralel HR halı);
    * "artıq həll olunub" xəta deyil, SAKİT məlumatdır;
    * səbəb boş ikən düymələr DEAKTİVDİR (qərar geri alına bilmir).

Testlər iki təbəqəni ayırır: kontroller (Qt TƏLƏB ETMİR, duck-typing) və
ekranın ÖZÜ (`@requires_qt`) — `test_annual_leave_screen.py` naxışı.

Sahtələr BU FAYLDA yerlidir: `tests/fixtures/fakes.py`-a toxunulmur, çünki
paralel işlər həmin ortaq faylı dəyişə bilər (eyni qərar əvvəlki üç ekran
testində də verilib).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Final

import pytest

from src.application.use_cases.sync_conflicts import (
    MIN_NOTE_LENGTH,
    RESOLVE_CONFLICT_FLAG,
    ConflictItem,
    ConflictNotFoundError,
    ConflictResolutionError,
    Resolution,
)
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import PermissionFlag, RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import EmployeeId, PositionId, TenantId
from src.presentation import preview_data
from src.presentation.controllers.sync_conflicts import (
    ALREADY_RESOLVED_NOTICE,
    LIST_READ_FAILED,
    MAX_VALUE_CHARS,
    RESOLVE_FAILED,
    TABLE_LABELS_AZ,
    SyncConflictController,
    _format_value,
    _to_field_rows,
    _to_list_row,
    resolution_options,
)
from src.presentation.shell.menu import DEFAULT_ENTRIES, build_default_registry
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())
NOW: Final = datetime(2026, 8, 12, 9, 42, tzinfo=UTC)


class _DeniedError(ConflictResolutionError):
    """`SyncConflictUseCase._require`-in atdığı istisnanın yerli əvəzi."""

    user_message = "Sinxronizasiya konfliktlərini həll etmək səlahiyyətiniz yoxdur."


class _ShortNoteError(ConflictResolutionError):
    user_message = "Qərarınızın səbəbini yazın."


# --------------------------------------------------------------------------- #
# Aktorlar
# --------------------------------------------------------------------------- #


def _employee(*, code: str, name_az: str, flags: tuple[str, ...]) -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=code,
        name_az=name_az,
        priority=RolePriority.OPERATIONAL,
        tenant_id=TENANT,
        is_system=True,
    )
    for flag in flags:
        position.grant(PermissionFlag(code=flag, category="test"))
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Aysel",
        last_name="Quliyeva",
        username=Username("a.quliyeva"),
        has_password=True,
    )


def _seller() -> Employee:
    """Heç bir flag daşımayan `Satıcı` — maddəni GÖRMƏMƏLİDİR."""
    return _employee(code="SATICI", name_az="Satıcı", flags=())


def _hr_admin() -> Employee:
    return _employee(code="HR_ADMIN", name_az="HR Admin", flags=(RESOLVE_CONFLICT_FLAG,))


# --------------------------------------------------------------------------- #
# 1–2. Menyu: "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" (bölmə 3)
# --------------------------------------------------------------------------- #


def test_menu_entry_is_gated_by_the_use_case_flag() -> None:
    """Menyu maddəsi use case-in FAKTİKİ flag-inə bağlıdır, təxminə yox.

    İkisi ayrılsaydı, maddə görünər, ekran isə "səlahiyyətiniz yoxdur"
    deyərdi — yəni `menu.py` başlığındakı ad-uyğunsuzluğu qüsurunun eyni
    forması.
    """
    entry = next(e for e in DEFAULT_ENTRIES if e.key == "sync_conflicts")
    assert entry.required_flag == RESOLVE_CONFLICT_FLAG
    # Toggle YOXDUR: offline sinxronizasiya iş-prosesi modulu deyil.
    assert entry.feature_module is None


def test_employee_without_the_flag_does_not_see_the_entry() -> None:
    """Flag-siz istifadəçidə maddə RENDER OLUNMUR (boz deyil, YOX)."""
    registry = build_default_registry()
    assert registry.is_visible("sync_conflicts", _seller(), now=NOW) is False
    assert registry.is_visible("sync_conflicts", _hr_admin(), now=NOW) is True


# --------------------------------------------------------------------------- #
# Sahtələr — Qt tələb ETMİR
# --------------------------------------------------------------------------- #


def _item(
    *,
    key: str = "sc-1",
    table: str = "fines",
    local: dict[str, Any] | None = None,
    remote: dict[str, Any] | None = None,
) -> ConflictItem:
    return ConflictItem(
        conflict_id=key,
        table_name=table,
        record_id="4f2a9c11-0000-0000-0000-000000000000",
        local_version=local if local is not None else {"amount": "45.00", "status": "PENDING"},
        remote_version=remote if remote is not None else {"amount": "30.00", "status": "PENDING"},
        detected_at=NOW,
    )


class _UseCase:
    """`SyncConflictUseCase` müqaviləsinin minimal təkrarı."""

    def __init__(
        self,
        *,
        items: list[ConflictItem] | None = None,
        inbox_error: Exception | None = None,
        resolve_error: Exception | None = None,
    ) -> None:
        self.items = list(items or [])
        self.inbox_error = inbox_error
        self.resolve_error = resolve_error
        self.inbox_calls = 0
        self.resolved: list[dict[str, Any]] = []

    def inbox(self, *, tenant_id: Any, actor: Any) -> list[ConflictItem]:
        self.inbox_calls += 1
        if self.inbox_error is not None:
            raise self.inbox_error
        return list(self.items)

    def resolve(
        self,
        *,
        tenant_id: Any,
        actor: Any,
        conflict_id: Any,
        resolution: Resolution,
        note: str,
    ) -> ConflictItem:
        if self.resolve_error is not None:
            raise self.resolve_error
        self.resolved.append(
            {
                "tenant_id": tenant_id,
                "actor": actor,
                "conflict_id": conflict_id,
                "resolution": resolution,
                "note": note,
            }
        )
        removed = [item for item in self.items if item.conflict_id == conflict_id]
        self.items = [item for item in self.items if item.conflict_id != conflict_id]
        return removed[0] if removed else _item()


class _Session:
    def __init__(self, use_case: _UseCase) -> None:
        self.tenant_id = TENANT
        self.sync_conflicts = use_case
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Context:
    """`ApplicationContext.session()` müqaviləsinin minimal təkrarı."""

    def __init__(self, session: _Session) -> None:
        self._session = session
        self.tenant_id = TENANT
        self.opened = 0

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        self.opened += 1
        yield self._session


class _ScreenStub:
    """Ekranın setter API-sinin sahtəsi — Qt olmadan."""

    def __init__(self) -> None:
        self.rows: list[list[dict[str, str]]] = []
        self.comparisons: list[tuple[dict[str, str], list[dict[str, str]]]] = []
        self.errors: list[tuple[str, str]] = []
        self.form_errors: list[str] = []
        self.notices: list[str] = []
        self.resolutions: list[list[dict[str, str]]] = []
        self.min_lengths: list[int] = []

    def set_conflicts(self, rows: list[dict[str, str]]) -> None:
        self.rows.append(rows)

    def set_comparison(self, detail: dict[str, str], fields: list[dict[str, str]]) -> None:
        self.comparisons.append((detail, fields))

    def set_resolutions(self, options: list[dict[str, str]]) -> None:
        self.resolutions.append(options)

    def set_note_min_length(self, value: int) -> None:
        self.min_lengths.append(value)

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))

    def show_form_error(self, message: str) -> None:
        self.form_errors.append(message)

    def show_notice(self, message: str) -> None:
        self.notices.append(message)


def _controller(use_case: _UseCase) -> tuple[SyncConflictController, _Session, _Context]:
    session = _Session(use_case)
    context = _Context(session)
    return SyncConflictController(context, _hr_admin()), session, context  # type: ignore[arg-type]


def _payload(
    conflict_id: str = "sc-1", *, note: str = "Mağazadakı vaxt doğrudur."
) -> dict[str, str]:
    return {"id": conflict_id, "resolution": Resolution.KEPT_LOCAL.value, "note": note}


# --------------------------------------------------------------------------- #
# 3–4. Yazı yolu
# --------------------------------------------------------------------------- #


def test_resolve_passes_the_exact_use_case_arguments() -> None:
    """Qərar `resolve()`-a DOMEN tipləri ilə gedir (sətir kodu ilə YOX)."""
    use_case = _UseCase(items=[_item()])
    controller, session, _ = _controller(use_case)
    screen = _ScreenStub()
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_resolve(screen, _payload())  # type: ignore[arg-type]

    assert len(use_case.resolved) == 1
    call = use_case.resolved[0]
    assert call["conflict_id"] == "sc-1"
    assert call["resolution"] is Resolution.KEPT_LOCAL
    assert call["note"] == "Mağazadakı vaxt doğrudur."
    assert call["tenant_id"] == TENANT
    assert session.commits == 1, "commit UNUDULSA yazı rollback olardı"


def test_resolve_rereads_the_inbox_afterwards() -> None:
    """Həll edilmiş konflikt siyahıdan ÇIXIR — yenidən oxuma bunu göstərir."""
    use_case = _UseCase(items=[_item(key="sc-1"), _item(key="sc-2", table="attendance_records")])
    controller, _, _ = _controller(use_case)
    screen = _ScreenStub()
    controller.refresh(screen)  # type: ignore[arg-type]
    assert len(screen.rows[-1]) == 2

    controller._on_resolve(screen, _payload("sc-1"))  # type: ignore[arg-type]

    assert use_case.inbox_calls == 2, "Qərardan sonra siyahı təzədən oxunmalıdır"
    assert [row["id"] for row in screen.rows[-1]] == ["sc-2"]


def test_last_resolution_empties_the_list_and_silences_the_health_alert() -> None:
    """Sonuncu konflikt bağlananda siyahı BOŞALIR.

    «Sistem Sağlamlığı» xəbərdarlığı EYNİ repo-dan (`open_count`) oxunur, ona
    görə boş siyahı avtomatik olaraq sönmüş xəbərdarlıq deməkdir — əlavə iş
    tələb olunmur (bax `screen_data._open_conflicts`).
    """
    use_case = _UseCase(items=[_item()])
    controller, _, _ = _controller(use_case)
    screen = _ScreenStub()
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_resolve(screen, _payload())  # type: ignore[arg-type]

    assert screen.rows[-1] == []
    assert use_case.items == []
    assert screen.comparisons[-1] == ({}, [])


def test_unknown_resolution_code_never_reaches_the_use_case() -> None:
    use_case = _UseCase(items=[_item()])
    controller, session, _ = _controller(use_case)
    screen = _ScreenStub()
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_resolve(screen, {"id": "sc-1", "resolution": "HAMISI", "note": "səbəb"})  # type: ignore[arg-type]

    assert use_case.resolved == []
    assert session.commits == 0
    assert screen.form_errors[-1] == "Qərar variantı tanınmadı."


# --------------------------------------------------------------------------- #
# 5. Paralel həll — SAKİT ton, çökmə YOX
# --------------------------------------------------------------------------- #


def test_conflict_not_found_is_explained_calmly_and_refreshes() -> None:
    """Başqası artıq həll edib — bu, XƏTA deyil, məlumatdır."""
    use_case = _UseCase(items=[_item()], resolve_error=ConflictNotFoundError("tapılmadı"))
    controller, session, _ = _controller(use_case)
    screen = _ScreenStub()
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_resolve(screen, _payload())  # type: ignore[arg-type]

    assert screen.notices[-1] == ALREADY_RESOLVED_NOTICE
    assert screen.errors == [], "Qorxudan qırmızı ekran GÖSTƏRİLMİR"
    assert session.commits == 0
    assert use_case.inbox_calls == 2, "Siyahı yenilənməlidir"


def test_stale_row_is_reported_without_touching_the_use_case() -> None:
    """Siyahıda olmayan sətir üçün sessiya AÇILMIR — yenidən oxuma kifayətdir."""
    use_case = _UseCase(items=[_item()])
    controller, session, context = _controller(use_case)
    screen = _ScreenStub()
    controller.refresh(screen)  # type: ignore[arg-type]
    opened_before = context.opened

    controller._on_resolve(screen, _payload("sc-yoxdur"))  # type: ignore[arg-type]

    assert use_case.resolved == []
    assert session.commits == 0
    assert screen.notices[-1] == ALREADY_RESOLVED_NOTICE
    # Yalnız `refresh()`-in sessiyası açılır, `resolve()` üçün yenisi YOX.
    assert context.opened == opened_before + 1


def test_domain_error_reaches_the_screen_as_user_message_not_raw_text() -> None:
    """XAM istisna mətni ekrana ÇIXMIR — yalnız `user_message`."""
    use_case = _UseCase(items=[_item()], resolve_error=_ShortNoteError("daxili kontekst: length=2"))
    controller, session, _ = _controller(use_case)
    screen = _ScreenStub()
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_resolve(screen, _payload(note="ok"))  # type: ignore[arg-type]

    assert screen.form_errors[-1] == _ShortNoteError.user_message
    assert "daxili kontekst" not in screen.form_errors[-1]
    assert session.commits == 0
    # Siyahı YENİLƏNMİR: heç nə dəyişməyib və yenidən oxuma HR-ın yazdığı
    # qeydi silərdi (bax `_on_resolve` şərhi).
    assert use_case.inbox_calls == 1


def test_unexpected_failure_does_not_crash_the_screen() -> None:
    use_case = _UseCase(items=[_item()], resolve_error=RuntimeError("baza əlçatmazdır"))
    controller, session, _ = _controller(use_case)
    screen = _ScreenStub()
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_resolve(screen, _payload())  # type: ignore[arg-type]

    assert screen.form_errors[-1] == RESOLVE_FAILED
    assert session.commits == 0


# --------------------------------------------------------------------------- #
# 6. Oxu yolu və boş siyahı
# --------------------------------------------------------------------------- #


def test_empty_inbox_is_not_an_error() -> None:
    """Konflikt olmaması NORMAL və MÜSBƏT haldır — qırmızı ekran YOX."""
    controller, _, _ = _controller(_UseCase(items=[]))
    screen = _ScreenStub()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.rows[-1] == []
    assert screen.errors == []
    assert screen.comparisons[-1] == ({}, [])


def test_permission_error_is_explained_with_the_user_message() -> None:
    """Flag-siz aktor ekranı açsa (deep link), səbəb AÇIQ yazılır."""
    use_case = _UseCase(inbox_error=_DeniedError("flag yoxdur"))
    controller, _, _ = _controller(use_case)
    screen = _ScreenStub()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.rows[-1] == []
    assert screen.errors == [("Konfliktlər oxunmadı", _DeniedError.user_message)]


def test_unreadable_list_does_not_crash() -> None:
    use_case = _UseCase(inbox_error=RuntimeError("baza əlçatmazdır"))
    controller, _, _ = _controller(use_case)
    screen = _ScreenStub()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.errors == [("Konfliktlər oxunmadı", LIST_READ_FAILED)]


def test_first_conflict_is_selected_automatically() -> None:
    """HR ekranı açan kimi müqayisəni görür — boş panelə baxmır."""
    use_case = _UseCase(items=[_item(key="sc-1"), _item(key="sc-2")])
    controller, _, _ = _controller(use_case)
    screen = _ScreenStub()

    controller.refresh(screen)  # type: ignore[arg-type]

    detail, fields = screen.comparisons[-1]
    assert detail["id"] == "sc-1"
    assert fields, "Müqayisə sətirləri boş qalmamalıdır"


# --------------------------------------------------------------------------- #
# 9. Kontroller SESSİYA SAXLAMIR
# --------------------------------------------------------------------------- #


def test_controller_opens_a_new_session_for_every_operation() -> None:
    """Panel saatlarla açıq qala bilər — uzun tranzaksiya kilid saxlayardı."""
    use_case = _UseCase(items=[_item(key="sc-1"), _item(key="sc-2")])
    controller, _, context = _controller(use_case)
    screen = _ScreenStub()

    controller.refresh(screen)  # type: ignore[arg-type]
    assert context.opened == 1

    controller._on_resolve(screen, _payload("sc-1"))  # type: ignore[arg-type]
    # `resolve` üçün bir sessiya + ondan sonrakı `refresh()` üçün bir sessiya.
    assert context.opened == 3

    stored = [value for value in vars(controller).values() if isinstance(value, _Session)]
    assert stored == [], "Kontroller sessiyaya istinad SAXLAMAMALIDIR"


def test_selecting_a_conflict_does_not_open_a_session() -> None:
    """Müqayisə paneli SON oxunuşdan qurulur — hər klikdə sorğu getmir."""
    use_case = _UseCase(items=[_item(key="sc-1"), _item(key="sc-2")])
    controller, _, context = _controller(use_case)
    screen = _ScreenStub()
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_selected(screen, "sc-2")  # type: ignore[arg-type]

    assert context.opened == 1
    assert screen.comparisons[-1][0]["id"] == "sc-2"


# --------------------------------------------------------------------------- #
# Maket ↔ canlı açar paritetı (CLAUDE.md §6)
# --------------------------------------------------------------------------- #


def test_preview_and_live_paths_share_the_same_row_keys() -> None:
    use_case = _UseCase(items=[_item()])
    controller, _, _ = _controller(use_case)
    screen = _ScreenStub()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert set(screen.rows[-1][0]) == set(preview_data.SYNC_CONFLICTS[0])


def test_preview_and_live_paths_share_the_same_field_keys() -> None:
    use_case = _UseCase(items=[_item()])
    controller, _, _ = _controller(use_case)
    screen = _ScreenStub()

    controller.refresh(screen)  # type: ignore[arg-type]

    _detail, fields = screen.comparisons[-1]
    assert set(fields[0]) == set(preview_data.SYNC_CONFLICT_FIELDS[0])


def test_detail_and_row_use_one_dictionary() -> None:
    """Başlıq və sətir EYNİ sözlükdür — biri dəyişəndə digəri arxada qalmasın."""
    item = _item()
    assert _to_list_row(item).keys() == set(preview_data.SYNC_CONFLICTS[0])


# --------------------------------------------------------------------------- #
# Çeviricilər
# --------------------------------------------------------------------------- #


def test_resolution_options_come_from_the_enum_not_from_the_screen() -> None:
    """Etiketlər `Resolution.label_az`-dır — ekran onları UYDURMUR."""
    options = resolution_options()
    assert [option["code"] for option in options] == [item.value for item in Resolution]
    assert [option["label"] for option in options] == [item.label_az for item in Resolution]
    merged = next(option for option in options if option["code"] == Resolution.MERGED.value)
    assert "əl ilə" in merged["hint"], "MERGED-in NƏ demək olduğu açıq yazılmalıdır"


def test_differing_fields_are_listed_first_and_marked() -> None:
    """Göz dərhal fərqə düşməlidir — sıra kontrollerdə verilir."""
    item = _item(
        local={"status": "PENDING", "amount": "45.00", "note": "eyni"},
        remote={"status": "PUBLISHED", "amount": "45.00", "note": "eyni"},
    )
    rows = _to_field_rows(item)

    assert [row["field"] for row in rows] == ["status", "amount", "note"]
    assert rows[0]["differs"] == "1"
    assert [row["differs"] for row in rows[1:]] == ["0", "0"]
    assert rows[0]["local"] == "PENDING"
    assert rows[0]["remote"] == "PUBLISHED"


def test_missing_field_on_one_side_is_shown_as_an_explicit_gap() -> None:
    """Bir tərəfdə OLMAYAN sahə də fərqdir — "(boş)" onu görünən edir."""
    item = _item(local={"reason": "gecikmə"}, remote={})
    rows = _to_field_rows(item)

    assert rows[0]["local"] == "gecikmə"
    assert rows[0]["remote"] == "(boş)"
    assert rows[0]["differs"] == "1"


def test_long_values_are_truncated_for_display_only() -> None:
    """Kəsilmə GÖRÜNTÜYƏ aiddir — fərq TAM dəyər üzərində hesablanır."""
    long_text = "a" * (MAX_VALUE_CHARS + 40)
    assert _format_value(long_text).endswith("…")
    assert len(_format_value(long_text)) == MAX_VALUE_CHARS + 1
    # Fərq hesablanması dəyişmir: iki fərqli uzun mətn yenə FƏRQLİ sayılır.
    item = _item(local={"note": long_text}, remote={"note": long_text + "b"})
    assert _to_field_rows(item)[0]["differs"] == "1"


def test_audit_critical_tables_are_flagged_for_the_screen() -> None:
    """Bölmə 5-in üç cədvəli sətirdə işarələnir, dördüncüsü YOX."""
    assert _to_list_row(_item(table="fines"))["audit_critical"] == "1"
    assert _to_list_row(_item(table="leave_requests"))["audit_critical"] == "1"
    assert _to_list_row(_item(table="audit_logs"))["audit_critical"] == "1"
    assert _to_list_row(_item(table="attendance_records"))["audit_critical"] == "0"


def test_unknown_table_keeps_its_raw_name() -> None:
    """Naməlum cədvəl "naməlum" yazılmır — xam ad ən azı dəqiqdir."""
    assert _to_list_row(_item(table="pos_receipts"))["table_label"] == "pos_receipts"
    assert _to_list_row(_item(table="fines"))["table_label"] == TABLE_LABELS_AZ["fines"]


# --------------------------------------------------------------------------- #
# Ekranın ÖZÜ — Qt tələb edir
# --------------------------------------------------------------------------- #


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _screen(theme: Any) -> Any:
    from src.presentation.screens.sync_conflicts import SyncConflictScreen

    screen = SyncConflictScreen(theme)
    screen.set_resolutions(resolution_options())
    screen.set_note_min_length(MIN_NOTE_LENGTH)
    return screen


def _labels(widget: Any) -> list[str]:
    from PySide6.QtWidgets import QLabel

    return [label.text() for label in widget.findChildren(QLabel)]


def _chip_tones(widget: Any) -> list[str]:
    from PySide6.QtWidgets import QLabel

    return [
        str(label.property("chip"))
        for label in widget.findChildren(QLabel)
        if label.property("chip")
    ]


def _rows(screen: Any) -> list[Any]:
    layout = screen.list_layout()
    return [layout.itemAt(index).widget() for index in range(layout.count())]


@requires_qt
def test_empty_state_is_positive_not_an_empty_table(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Konflikt yoxdursa MÜSBƏT mesaj göstərilir, boş cədvəl yox."""
    from src.presentation.screens.sync_conflicts import EMPTY_TITLE

    screen = _screen(theme)
    qtbot.addWidget(screen)

    screen.set_conflicts([])

    assert screen.switcher().current_state() == "empty"
    assert EMPTY_TITLE in _labels(screen.switcher())


@requires_qt
def test_audit_critical_row_is_visibly_different(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Nişan + AÇIQ MƏTN: rəng tək başına kifayət etmir (rəng-korluğu)."""
    from src.presentation.screens.sync_conflicts import AUDIT_CRITICAL_NOTE

    screen = _screen(theme)
    qtbot.addWidget(screen)

    screen.set_conflicts([dict(row) for row in preview_data.SYNC_CONFLICTS])

    critical, ordinary = _rows(screen)
    assert AUDIT_CRITICAL_NOTE in _labels(critical)
    assert "danger" in _chip_tones(critical)
    assert AUDIT_CRITICAL_NOTE not in _labels(ordinary)
    assert "danger" not in _chip_tones(ordinary)


@requires_qt
def test_differing_fields_are_highlighted_and_identical_ones_are_muted(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Fərqli sahə «Fərqli» nişanı ilə, eyni sahə solğun mətnlə göstərilir."""
    screen = _screen(theme)
    qtbot.addWidget(screen)

    screen.set_conflicts([dict(row) for row in preview_data.SYNC_CONFLICTS])
    screen.set_comparison(
        dict(preview_data.SYNC_CONFLICTS[0]),
        [dict(row) for row in preview_data.SYNC_CONFLICT_FIELDS],
    )

    layout = screen.field_layout()
    assert layout.count() == len(preview_data.SYNC_CONFLICT_FIELDS)
    first = layout.itemAt(0).widget()
    last = layout.itemAt(layout.count() - 1).widget()
    assert "warning" in _chip_tones(first), "Fərqli sahə nişanlanmalıdır"
    assert _chip_tones(last) == [], "Eyni sahədə nişan olmamalıdır"
    assert "eyni" in _labels(last)


@requires_qt
def test_decision_buttons_stay_disabled_until_a_reason_is_written(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Səbəb MƏCBURİDİR və qərar geri alına bilmir — düymə əvvəlcədən bağlıdır."""
    screen = _screen(theme)
    qtbot.addWidget(screen)

    screen.set_conflicts([dict(row) for row in preview_data.SYNC_CONFLICTS])
    screen.set_comparison(dict(preview_data.SYNC_CONFLICTS[0]), [])

    buttons = screen.decision_buttons()
    assert len(buttons) == len(Resolution)
    assert all(not button.isEnabled() for button in buttons)

    # Minimumdan qısa qeyd DƏ kifayət etmir.
    screen._note.setPlainText("a" * (MIN_NOTE_LENGTH - 1))
    assert all(not button.isEnabled() for button in screen.decision_buttons())

    screen._note.setPlainText("Mağazadakı vaxt doğrudur.")
    assert all(button.isEnabled() for button in screen.decision_buttons())

    # YALNIZ boşluqdan ibarət qeyd boş sayılır (use case də belə təmizləyir).
    screen._note.setPlainText("      ")
    assert all(not button.isEnabled() for button in screen.decision_buttons())


@requires_qt
def test_decision_emits_the_cleaned_payload(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Siqnal `id`/`resolution`/`note` daşıyır; artıq boşluqlar təmizlənir."""
    screen = _screen(theme)
    qtbot.addWidget(screen)

    screen.set_conflicts([dict(row) for row in preview_data.SYNC_CONFLICTS])
    screen.set_comparison(dict(preview_data.SYNC_CONFLICTS[0]), [])

    emitted: list[dict[str, str]] = []
    screen.resolve_requested.connect(emitted.append)

    screen._note.setPlainText("Mağazadakı   vaxt  doğrudur.")
    screen.decision_buttons()[0].click()

    assert emitted == [
        {
            "id": "sc-1",
            "resolution": Resolution.KEPT_LOCAL.value,
            "note": "Mağazadakı vaxt doğrudur.",
        }
    ]


@requires_qt
def test_switching_conflicts_clears_the_reason(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Bir qeyd üçün yazılmış izah digərinin audit sətrinə DÜŞMƏMƏLİDİR."""
    screen = _screen(theme)
    qtbot.addWidget(screen)

    screen.set_conflicts([dict(row) for row in preview_data.SYNC_CONFLICTS])
    screen.set_comparison(dict(preview_data.SYNC_CONFLICTS[0]), [])
    screen._note.setPlainText("Cərimə üçün yazılmış səbəb.")

    screen.set_comparison(dict(preview_data.SYNC_CONFLICTS[1]), [])

    assert screen._note.toPlainText() == ""
    assert all(not button.isEnabled() for button in screen.decision_buttons())


@requires_qt
def test_selecting_a_row_emits_the_conflict_id(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    screen = _screen(theme)
    qtbot.addWidget(screen)

    selected: list[str] = []
    screen.conflict_selected.connect(selected.append)
    screen.set_conflicts([dict(row) for row in preview_data.SYNC_CONFLICTS])
    _rows(screen)[1]._activate()

    assert selected == ["sc-2"]


@requires_qt
def test_notice_and_error_are_separate_channels(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Sakit məlumat (`show_notice`) xəta sətri ilə eyni yerə yazılmır."""
    screen = _screen(theme)
    qtbot.addWidget(screen)

    screen.show_notice(ALREADY_RESOLVED_NOTICE)
    screen.show_form_error("Qərar variantı tanınmadı.")

    assert screen._notice.text() == ALREADY_RESOLVED_NOTICE
    assert screen._error.text() == "Qərar variantı tanınmadı."
    assert screen._error.property("variant") == "danger-text"


# --------------------------------------------------------------------------- #
# «Sistem Sağlamlığı» → ekran keçidi (dalanın bağlanması)
# --------------------------------------------------------------------------- #


@requires_qt
def test_health_link_is_not_built_without_conflicts(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Keçid `setEnabled(False)` ilə boz qalmır — ÜMUMİYYƏTLƏ qurulmur."""
    from src.presentation.screens.group_d import HealthScreen

    screen = HealthScreen(theme)
    qtbot.addWidget(screen)

    screen.set_conflict_action(0)
    assert screen._conflict_link is None

    screen.set_conflict_action(3)
    assert screen._conflict_link is not None
    assert "3" in screen._conflict_link.text()

    # Sonuncu konflikt həll olunanda keçid də yox olur.
    screen.set_conflict_action(0)
    assert screen._conflict_link is None


@requires_qt
def test_health_link_emits_the_navigation_signal(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_d import HealthScreen

    screen = HealthScreen(theme)
    qtbot.addWidget(screen)
    screen.set_conflict_action(2)

    emitted: list[bool] = []
    screen.conflicts_requested.connect(lambda: emitted.append(True))
    assert screen._conflict_link is not None
    screen._conflict_link._activate()

    assert emitted == [True]
