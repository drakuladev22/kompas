"""`FieldReportScreen` ↔ `FieldReportsController` — REAL Qt e2e (#26+#27).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, üçüncü dalğa)
──────────────────────────────────────────────────────────────────────────────
`test_field_report_screen.py` ekranı `set_templates(...)` ilə doldurur və
kontrolleri `_ScreenStub` (duck-typing) ilə ölçür — REAL `FieldReportsController.
attach()`, REAL `QPushButton.click()`, REAL `QRadioButton`, REAL
`QFileDialog`/`QInputDialog` heç vaxt işə düşmür. Burada iki menyu açarının
(`store_audit`/`incident_report`) hər biri REAL öz ekranı + öz kontrolleri ilə
qurulur (`app.py::_attach_field_reports` naxışının EYNİSİ) və hər interaktiv
element (şablon/kateqoriya combo-su, "Bənd Əlavə Et", üç-vəziyyətli radio,
"Şəkil Seç", "Növbəti →", "Təqdim Et", sətir düymələri) REAL kliklə işə salınır.

Sahtələr BU FAYLDA yerlidir — `tests/fixtures/fakes.py`-a TOXUNULMUR (eyni
qərar `test_field_report_screen.py`-də və `test_tasks_screen_e2e.py`-də
verilib).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Final

import pytest

from src.application.use_cases.field_reports import FieldReportSubmission
from src.domain.entities.field_report import FieldReport
from src.domain.value_objects.field_reports import FieldReportCategory, FieldReportTemplate
from src.domain.value_objects.identifiers import StoreId, TenantId, new_field_report_id
from src.presentation.background_task import InlineExecutor
from src.presentation.controllers.field_reports import FieldReportsController
from src.presentation.screens.field_reports import FieldReportScreen
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())
ACTOR_ID: Final = uuid.uuid4()
STORE: Final = StoreId(uuid.uuid4())
NOW: Final = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)

AUDIT_TEMPLATE: Final = FieldReportTemplate(
    code="STORE_AUDIT",
    name_az="Mağaza ziyarəti / audit",
    description_az="Checklist üzrə yoxlama.",
    requires_checklist=True,
)
INCIDENT_TEMPLATE: Final = FieldReportTemplate(
    code="INCIDENT",
    name_az="İnsident bildirişi",
    description_az="Baş vermiş hadisə.",
    requires_checklist=False,
)
AUDIT_CATEGORY: Final = FieldReportCategory(
    code="TEMIZLIK",
    report_type="STORE_AUDIT",
    name_az="Təmizlik və gigiyena",
)
INCIDENT_CATEGORY: Final = FieldReportCategory(
    code="OGURLUQ",
    report_type="INCIDENT",
    name_az="Oğurluq şübhəsi",
    route_to_role="TEHLUKESIZLIK",
)

VALID_DETAIL: Final = "Anbar arxasında qablaşdırma tullantısı yığılıb."


class _DeniedError(KompasOSError):
    user_message = "Bu əməliyyat üçün səlahiyyətiniz yoxdur."


# --------------------------------------------------------------------------- #
# Qt köməkçiləri
# --------------------------------------------------------------------------- #


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


def _radio(widget: Any, text: str) -> Any:
    from PySide6.QtWidgets import QRadioButton

    return next(r for r in widget.findChildren(QRadioButton) if r.text() == text)


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


def _report(detail: str = VALID_DETAIL, *, report_type: str = "STORE_AUDIT") -> FieldReport:
    return FieldReport(
        report_id=new_field_report_id(),
        tenant_id=TENANT,
        report_type=report_type,
        category="TEMIZLIK" if report_type == "STORE_AUDIT" else "OGURLUQ",
        store_id=STORE,
        reported_by=ACTOR_ID,  # type: ignore[arg-type]
        detail=detail,
        created_at=NOW,
        updated_at=NOW,
        emit_created_event=False,
    )


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _Connection:
    def execute(self, _sql: str, _params: Any = None) -> _Cursor:
        return _Cursor([{"id": str(STORE), "name": "Bellona 28 May"}])


class _Uow:
    def __init__(self) -> None:
        self.connection = _Connection()


class _Limits:
    def get_int(self, _tenant_id: Any, _key: str, fallback: int) -> int:
        return fallback


class _UseCase:
    """`FieldReportUseCase` müqaviləsinin minimal təkrarı."""

    def __init__(
        self,
        *,
        templates: list[FieldReportTemplate],
        categories: list[FieldReportCategory],
        reports: list[FieldReport] | None = None,
        list_error: Exception | None = None,
        submit_error: Exception | None = None,
    ) -> None:
        self.templates = templates
        self.categories = categories
        self.reports = list(reports or [])
        self.list_error = list_error
        self.submit_error = submit_error
        self.list_open_calls = 0
        self.submitted: list[Any] = []
        self.closed: list[tuple[Any, Any, str]] = []
        self.started: list[Any] = []

    def list_templates(self, *, tenant_id: Any, actor: Any) -> list[FieldReportTemplate]:
        return list(self.templates)

    def list_categories(
        self, *, tenant_id: Any, actor: Any, report_type: str
    ) -> list[FieldReportCategory]:
        return [c for c in self.categories if c.report_type == report_type]

    def list_open(
        self,
        *,
        tenant_id: Any,
        actor: Any,
        store_ids: Any = None,
        report_type: str | None = None,
    ) -> list[FieldReport]:
        self.list_open_calls += 1
        if self.list_error is not None:
            raise self.list_error
        return [r for r in self.reports if report_type is None or r.report_type == report_type]

    def submit(self, *, tenant_id: Any, actor: Any, draft: Any) -> FieldReportSubmission:
        if self.submit_error is not None:
            raise self.submit_error
        self.submitted.append(draft)
        report = _report(draft.detail, report_type=draft.report_type)
        self.reports.append(report)
        return FieldReportSubmission(report=report, corrective_task_ids=(), routed_role=None)

    def start_progress(self, *, tenant_id: Any, actor: Any, report_id: Any) -> FieldReport:
        self.started.append(report_id)
        return self.reports[0]

    def close(
        self, *, tenant_id: Any, actor: Any, report_id: Any, status: Any, note: str
    ) -> FieldReport:
        self.closed.append((report_id, status, note))
        self.reports = [r for r in self.reports if r.id != report_id]
        return _report()


class _Session:
    def __init__(self, use_case: _UseCase) -> None:
        self.tenant_id = TENANT
        self.uow = _Uow()
        self.limits = _Limits()
        self.field_reports = use_case
        self.commits = 0

    def max_upload_bytes(self) -> int:
        return 5 * 1024 * 1024

    def commit(self) -> None:
        self.commits += 1


class _EvidenceQueue:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []

    def enqueue(self, **kwargs: Any) -> None:
        self.enqueued.append(kwargs)


class _Context:
    """`ApplicationContext.session()` müqaviləsinin minimal təkrarı."""

    def __init__(self, use_case: _UseCase) -> None:
        self._use_case = use_case
        self.tenant_id = TENANT
        self.sessions: list[_Session] = []
        self.evidence = _EvidenceQueue()
        self.upload_runs = 0

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(self._use_case)
        self.sessions.append(created)
        yield created

    def evidence_queue(self) -> _EvidenceQueue:
        return self.evidence

    def run_evidence_uploads(self) -> int:
        self.upload_runs += 1
        return 0


class _Actor:
    id = ACTOR_ID


def _attach(
    use_case: _UseCase, theme: Any, *, qtbot: Any, requires_checklist: bool
) -> tuple[Any, _Context]:
    """Real `FieldReportScreen`-i qurur, REAL kontrolleri bağlayır.

    `app.py::_attach_field_reports`-un EYNİ naxışı: hər menyu açarı ÖZ ekranı
    + ÖZ kontroller nüsxəsi ilə gəlir, `requires_checklist` isə
    `SCREEN_TEMPLATE_FAMILY`-dən çıxır.
    """
    context = _Context(use_case)
    screen = FieldReportScreen(theme)
    qtbot.addWidget(screen)
    FieldReportsController(
        context,  # type: ignore[arg-type]
        _Actor(),  # type: ignore[arg-type]
        requires_checklist=requires_checklist,
        executor=InlineExecutor(),
    ).attach(screen)
    return screen, context


def _audit_use_case(**overrides: Any) -> _UseCase:
    defaults: dict[str, Any] = {
        "templates": [AUDIT_TEMPLATE, INCIDENT_TEMPLATE],
        "categories": [AUDIT_CATEGORY, INCIDENT_CATEGORY],
        "reports": [],
    }
    defaults.update(overrides)
    return _UseCase(**defaults)


# --------------------------------------------------------------------------- #
# 1. İki menyu açarı, İKİ real ekran — ailələr QARIŞMIR
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_audit_and_incident_screens_show_disjoint_templates_and_checklists(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """Eyni kataloqdan İKİ real ekran qurulur — biri checklist göstərir, o biri yox."""
    audit_screen, _audit_ctx = _attach(
        _audit_use_case(), theme, qtbot=qtbot, requires_checklist=True
    )
    incident_screen, _incident_ctx = _attach(
        _audit_use_case(), theme, qtbot=qtbot, requires_checklist=False
    )

    assert audit_screen._template_combo.count() == 1
    assert audit_screen._template_combo.currentData() == "STORE_AUDIT"
    assert audit_screen._checklist_holder.isVisibleTo(audit_screen) is True

    assert incident_screen._template_combo.count() == 1
    assert incident_screen._template_combo.currentData() == "INCIDENT"
    assert incident_screen._checklist_holder.isVisibleTo(incident_screen) is False


# --------------------------------------------------------------------------- #
# 2. Uğurlu axın — REAL combo, REAL "Bənd Əlavə Et", REAL radio, REAL "Təqdim Et"
# --------------------------------------------------------------------------- #


@requires_qt
def test_the_real_widgets_submit_a_complete_audit_report_and_reread_the_list(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    use_case = _audit_use_case()
    screen, context = _attach(use_case, theme, qtbot=qtbot, requires_checklist=True)

    screen._detail.setPlainText(VALID_DETAIL)
    screen._item_text.set_text("Soyuducunun temperaturu")
    _click(screen, "Bənd Əlavə Et")
    _radio(screen, "Keçmədi").click()

    _click(screen, "Təqdim Et")

    assert len(use_case.submitted) == 1
    draft = use_case.submitted[0]
    assert draft.report_type == "STORE_AUDIT"
    assert draft.category == "TEMIZLIK"
    assert draft.checklist[0].item_text == "Soyuducunun temperaturu"
    assert draft.checklist[0].passed is False
    assert any(s.commits for s in context.sessions)
    # Uğurdan sonra forma TƏMİZLƏNİR (REAL widget-lərdə).
    assert screen._detail.toPlainText() == ""
    assert screen.checklist_entries() == ()
    # Yazıdan SONRA siyahı YENİDƏN oxunur: attach() + submit → 2 çağırış.
    assert use_case.list_open_calls == 2


# --------------------------------------------------------------------------- #
# 3. Yarımçıq checklist — REAL "Təqdim Et" sükutla getmir
# --------------------------------------------------------------------------- #


@requires_qt
def test_submitting_without_any_checklist_item_is_rejected_by_the_real_button(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    use_case = _audit_use_case()
    screen, _context = _attach(use_case, theme, qtbot=qtbot, requires_checklist=True)

    screen._detail.setPlainText(VALID_DETAIL)
    _click(screen, "Təqdim Et")  # checklist bəndsiz — audit ŞABLONU bunu tələb edir

    assert use_case.submitted == []
    assert "checklist bəndi tələb edir" in screen._form_message.text()


@requires_qt
def test_a_blank_and_whitespace_only_checklist_item_is_rejected_by_the_real_click(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    use_case = _audit_use_case()
    screen, _context = _attach(use_case, theme, qtbot=qtbot, requires_checklist=True)

    for hostile_blank in ("", "   "):
        screen._item_text.set_text(hostile_blank)
        _click(screen, "Bənd Əlavə Et")

        assert screen._item_text.has_error is True
        assert screen.checklist_entries() == ()


# --------------------------------------------------------------------------- #
# 4. Foto-məcburi bənd — REAL "Növbəti →" və REAL "Təqdim Et" bloklanır
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_photo_required_answered_item_blocks_the_real_next_and_submit_buttons(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    use_case = _audit_use_case()
    screen, _context = _attach(use_case, theme, qtbot=qtbot, requires_checklist=True)

    screen._detail.setPlainText(VALID_DETAIL)
    screen._item_text.set_text("Soyuducunun temperaturu")
    screen._item_photo_required.setChecked(True)
    _click(screen, "Bənd Əlavə Et")
    screen._item_text.set_text("Kassa arxası təmizliyi")
    _click(screen, "Bənd Əlavə Et")

    # İlk bəndə qayıt, cavabla — foto seçilmədən.
    screen._step = 0
    screen._render_step()
    _radio(screen, "Keçmədi").click()

    _click(screen, "Növbəti →")  # ÇÖKMƏMƏLİDİR, İRƏLİ buraxmamalıdır
    assert screen._step == 0
    assert "foto-sübut məcburidir" in screen._checklist_message.text()

    _click(screen, "Təqdim Et")  # eyni qapı təqdimatda da işləməlidir
    assert use_case.submitted == []
    assert "foto-sübut məcburidir" in screen._form_message.text()


# --------------------------------------------------------------------------- #
# 5. Hesabat-səviyyəli foto — REAL "Şəkil Seç" dialoqu, növbəyə yazma, itmiş fayl
# --------------------------------------------------------------------------- #


@requires_qt
def test_picking_a_real_photo_via_the_dialog_enqueues_it_and_triggers_the_upload(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QFileDialog

    use_case = _audit_use_case()
    screen, context = _attach(use_case, theme, qtbot=qtbot, requires_checklist=False)

    photo = tmp_path / "sened.png"
    photo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(photo), ""))
    )

    _click(screen, "Şəkil Seç")  # yalnız BİR belə düymə var (checklist gizlidir)
    assert "sened.png" in screen._photo_label.text()

    screen._detail.setPlainText(VALID_DETAIL)
    _click(screen, "Təqdim Et")

    assert len(use_case.submitted) == 1
    assert len(context.evidence.enqueued) == 1
    assert context.evidence.enqueued[0]["filename"] == "sened.png"
    assert context.upload_runs == 1, "Seçilmiş fayl FON yükləməsini DƏRHAL işə salmalı idi"


@requires_qt
def test_a_photo_file_that_vanishes_before_submit_fails_cleanly_without_a_crash(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    """Seçimlə təqdimat arasında fayl silinir (TOCTOU) — `OSError` sükutla udulmur."""
    from PySide6.QtWidgets import QFileDialog

    use_case = _audit_use_case()
    screen, context = _attach(use_case, theme, qtbot=qtbot, requires_checklist=False)

    photo = tmp_path / "itecek.png"
    photo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(photo), ""))
    )
    _click(screen, "Şəkil Seç")
    photo.unlink()  # TOCTOU: seçildikdən sonra disk üzərindən silinir

    screen._detail.setPlainText(VALID_DETAIL)
    _click(screen, "Təqdim Et")  # ÇÖKMƏMƏLİDİR

    assert use_case.submitted == []
    assert not any(s.commits for s in context.sessions)
    assert context.evidence.enqueued == []
    assert "açıla bilmədi" in screen._form_message.text()


# --------------------------------------------------------------------------- #
# 6. Ekstremal/hostile mətn REAL sahələrdə
# --------------------------------------------------------------------------- #


@requires_qt
def test_hostile_and_extreme_text_in_the_real_detail_and_checklist_fields_does_not_crash(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    use_case = _audit_use_case()
    screen, _context = _attach(use_case, theme, qtbot=qtbot, requires_checklist=True)

    hostile_detail = "'; DROP TABLE field_reports; -- 🔥 " + "A" * 10_000
    hostile_item = "🔥 خط عربي " + "B" * 5_000

    screen._detail.setPlainText(hostile_detail)
    screen._item_text.set_text(hostile_item)
    _click(screen, "Bənd Əlavə Et")
    _radio(screen, "Keçdi").click()

    _click(screen, "Təqdim Et")  # ÇÖKMƏMƏLİDİR

    assert len(use_case.submitted) == 1
    draft = use_case.submitted[0]
    assert draft.checklist[0].item_text == hostile_item
    assert "DROP TABLE" in draft.detail


# --------------------------------------------------------------------------- #
# 7. Sürətli ikiqat klik — real "Təqdim Et" ikinci dəfə YAZMIR
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_rapid_double_click_on_the_real_submit_button_writes_only_one_report(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """Uğurlu birinci klik formu TƏMİZLƏYİR — ikinci klik boş forma ilə qarşılaşır
    və dövr yolu ilə rədd edilir (ayrıca idempotentlik açarı YOXDUR, bax
    `field_reports.py::_on_submit`)."""
    use_case = _audit_use_case()
    screen, context = _attach(use_case, theme, qtbot=qtbot, requires_checklist=False)

    screen._detail.setPlainText(VALID_DETAIL)
    _click(screen, "Təqdim Et")
    _click(screen, "Təqdim Et")

    assert len(use_case.submitted) == 1
    assert sum(s.commits for s in context.sessions) == 1


# --------------------------------------------------------------------------- #
# 8. Repo istisnası — sükutla udulmur, forma silinmir
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_submit_time_authorization_error_shows_the_domain_message_and_keeps_the_form(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    use_case = _audit_use_case(submit_error=_DeniedError("no permission"))
    screen, context = _attach(use_case, theme, qtbot=qtbot, requires_checklist=False)

    screen._detail.setPlainText(VALID_DETAIL)
    _click(screen, "Təqdim Et")  # ÇÖKMƏMƏLİDİR

    assert use_case.submitted == []
    assert not any(s.commits for s in context.sessions)
    assert screen._form_message.text() == _DeniedError.user_message
    # Forma SİLİNMİR — istifadəçi yenidən yazmasın deyə mətn qalır.
    assert screen._detail.toPlainText() == VALID_DETAIL


# --------------------------------------------------------------------------- #
# 9. Real sətir düymələri — "İcraya Götür" / "Həll Edildi" / "Əsassızdır"
# --------------------------------------------------------------------------- #


@requires_qt
def test_clicking_the_real_start_progress_row_button_commits_and_rereads(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    report = _report()
    use_case = _audit_use_case(reports=[report])
    screen, context = _attach(use_case, theme, qtbot=qtbot, requires_checklist=True)

    _click(screen, "İcraya Götür")

    assert [str(x) for x in use_case.started] == [str(report.id)]
    assert any(s.commits for s in context.sessions)


@requires_qt
def test_dismissing_a_report_via_the_real_row_button_requires_a_real_note_prompt(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    report = _report()
    use_case = _audit_use_case(reports=[report])
    screen, context = _attach(use_case, theme, qtbot=qtbot, requires_checklist=True)

    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("Əsassız hesabat", True))
    )

    _click(screen, "Əsassızdır")

    assert len(use_case.closed) == 1
    assert use_case.closed[0][2] == "Əsassız hesabat"
    assert any(s.commits for s in context.sessions)
    # Bağlanmış hesabat açıq siyahıda QALMIR — yenidən oxuma bunu göstərir.
    assert screen.table().row_count == 0


@requires_qt
def test_declining_the_real_close_reason_prompt_writes_nothing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    report = _report()
    use_case = _audit_use_case(reports=[report])
    screen, _context = _attach(use_case, theme, qtbot=qtbot, requires_checklist=True)

    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("", False)))

    _click(screen, "Həll Edildi")

    assert use_case.closed == []
    assert screen.table().row_count == 1  # sətir YOXA ÇIXMIR


# --------------------------------------------------------------------------- #
# 10. Səlahiyyət qapısı: audit flag-i olmayan aktor — real "boş", çökmə YOX
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_seller_style_actor_sees_a_restricted_notice_instead_of_a_crashed_list(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """`list_open` `can_conduct_store_audit` tələb edir — insident formasını
    görən, lakin audit səlahiyyəti olmayan aktorda siyahı BOŞ, forma isə
    İŞLƏK qalmalıdır (bax `controllers/field_reports.py` modul başlığı)."""
    from src.presentation.controllers.field_reports import LIST_RESTRICTED_NOTICE

    use_case = _audit_use_case(list_error=_DeniedError("no audit permission"))
    screen, _context = _attach(use_case, theme, qtbot=qtbot, requires_checklist=False)

    assert screen._list_notice.text() == LIST_RESTRICTED_NOTICE
    assert screen.table().row_count == 0
    # Forma YENƏ İŞLƏYİR — Satıcı insidenti yaza bilir.
    assert screen._template_combo.count() == 1
    from PySide6.QtWidgets import QPushButton

    row_buttons = {"İcraya Götür", "Həll Edildi", "Əsassızdır"}
    texts = {b.text() for b in screen.findChildren(QPushButton)}
    assert row_buttons.isdisjoint(texts), "Boş siyahıda sətir düyməsi RENDER OLUNMAMALIDIR"


# --------------------------------------------------------------------------- #
# 11. Köhnəlmiş sətirdən gələn yanlış ID — REAL siqnal, çökmə YOX
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_malformed_report_id_from_a_stale_row_does_not_crash_either_action(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Ekran yenilənəndən SONRA basılan köhnə sətir düyməsi naməlum İD göndərə
    bilər — kontroller bunu tutmalıdır, `RuntimeError`/`ValueError` YOX."""
    use_case = _audit_use_case()
    screen, _context = _attach(use_case, theme, qtbot=qtbot, requires_checklist=True)

    screen.progress_requested.emit("not-a-uuid")
    screen.close_requested.emit("not-a-uuid", "RESOLVED")

    assert use_case.started == []
    assert use_case.closed == []
    assert "düzgün deyil" in screen._list_notice.text()
