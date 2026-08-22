"""`FineEntryScreen` ↔ `controllers/fine_entry.py` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, üçüncü beşlik)
──────────────────────────────────────────────────────────────────────────────
`controllers/fine_entry.py` `tests/` daxilində HEÇ YERDƏ adı çəkilmirdi. Real
sübut sahəsi (`PhotoDropZone.set_file`), real dropdown-lar və real "Cəriməni
Qeyd Et" düyməsi ilə tam axın sınanır.

──────────────────────────────────────────────────────────────────────────────
DÜZƏLDİLDİ — `idempotency_key` İNDİ HƏR GÖNDƏRİŞDƏ ÖTÜRÜLÜR
──────────────────────────────────────────────────────────────────────────────
İlkin tapıntı: `ManualFineUseCase.issue()` (`fine_management.py:228-260`)
`idempotency_key` parametrini dəstəkləyirdi, LAKİN `controllers/
fine_entry.py::_issue()` onu ÖTÜRMÜRDÜ. `ui` bunu düzəltdi:
`FineEntryController._idempotency_key_for_submission()` `sales_points.py::
_redemption_id_for` ilə EYNİ naxışı tətbiq edir (`monotonic()` pəncərəsi,
`DUPLICATE_SUBMISSION_WINDOW_SECONDS`) — pəncərə daxilində iki klik EYNİ
açar daşıyır, DB-nin unikal indeksi (miqrasiya 074) ONU TUTUR. Aşağıdakı
`test_a_rapid_double_click_reuses_the_same_idempotency_key_within_the_window`
YENİ davranışı REAL kliklə ölçür — `monotonic()` testdə idarə olunur, real
gözləmə YOXDUR.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any

import pytest

from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()
STORE_ID = uuid.uuid4()
FINE_TYPE_ID = uuid.uuid4()
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


def _fine_type(*, name: str = "Gecikmə", fine_type_id: Any = FINE_TYPE_ID) -> Any:
    from decimal import Decimal

    from src.domain.value_objects.catalogs import FineType
    from src.domain.value_objects.money import Money

    return FineType(
        name=name,
        tenant_id=TENANT,
        fine_type_id=fine_type_id,
        standard_amount=Money(Decimal("25")),
    )


class _Row(dict):
    pass


class _Connection:
    def __init__(self, stores: dict[str, str], employees: dict[str, tuple[str, str]]) -> None:
        self._stores = stores
        self._employees = employees
        self._last_sql = ""

    def execute(self, sql: str, _params: Any = None) -> _Connection:
        self._last_sql = sql
        return self

    def fetchall(self) -> list[_Row]:
        if "FROM stores" in self._last_sql:
            return [_Row(id=sid, name=name) for sid, name in self._stores.items()]
        if "FROM employees" in self._last_sql:
            return [
                _Row(id=eid, first_name=first, last_name=last)
                for eid, (first, last) in self._employees.items()
            ]
        return []  # pragma: no cover - naməlum sorğu


class _Uow:
    def __init__(self, stores: dict[str, str], employees: dict[str, tuple[str, str]]) -> None:
        self.connection = _Connection(stores, employees)
        self.fines_marked_pending: list[Any] = []
        self._fines_repo = self

    @property
    def fines(self) -> Any:
        return self

    def mark_evidence_pending(self, fine_id: Any) -> None:
        self.fines_marked_pending.append(fine_id)

    def repository(self, key: str) -> Any:
        """`screen_data._fines` kamera operatorunun ÖZ filiallarını soruşur.

        Sahtədə bu metod YOX İDİ və `AttributeError` `populate()`-in geniş
        `except`-inə düşürdü: ekran boş qalırdı, test isə YAŞIL — çünki heç
        biri `SCREEN_BIND_FAILED` yazılmadığını yoxlamırdı. Boş siyahı burada
        DOĞRU sahtədir: bu faylın mövzusu cərimə FORMASIDIR, əhatə süzgəci
        deyil (o, `test_camera_queue_screen_e2e.py`-də ayrıca sınanır).
        """
        if key == "camera_assignments":
            return _CameraAssignments()
        raise AssertionError(f"Gözlənilməyən repo açarı: {key}")


class _CameraAssignments:
    def stores_for_operator(self, operator_id: Any) -> list[Any]:
        return []


class _ManualFines:
    def __init__(self, *, fine_types: list[Any], allowed_stores: list[Any]) -> None:
        self._fine_types = fine_types
        self._allowed_stores = allowed_stores
        self.issued: list[dict[str, Any]] = []
        self.issue_error: KompasOSError | None = None

    def selectable_fine_types(self, _tenant_id: Any) -> list[Any]:
        return list(self._fine_types)

    def allowed_stores(self, _operator: Any) -> list[Any]:
        return list(self._allowed_stores)

    def issue(self, **kwargs: Any) -> Any:
        if self.issue_error is not None:
            raise self.issue_error
        self.issued.append(kwargs)
        return type("_Fine", (), {"id": kwargs.get("fine_id")})()


class _EvidenceQueue:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []
        self.error: KompasOSError | None = None
        self._counter = 0

    def enqueue(self, **kwargs: Any) -> str:
        if self.error is not None:
            raise self.error
        self._counter += 1
        self.enqueued.append(kwargs)
        return f"queue-entry-{self._counter}"


class _Session:
    def __init__(
        self,
        manual_fines: _ManualFines,
        stores: dict[str, str],
        employees: dict[str, tuple[str, str]],
    ) -> None:
        self.tenant_id = TENANT
        self.manual_fines = manual_fines
        self.uow = _Uow(stores, employees)
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(
        self,
        *,
        fine_types: list[Any] | None = None,
        stores: dict[str, str] | None = None,
        employees: dict[str, tuple[str, str]] | None = None,
        allowed_stores: list[Any] | None = None,
    ) -> None:
        self._stores = stores if stores is not None else {str(STORE_ID): "Mərkəz"}
        self._employees = (
            employees if employees is not None else {str(EMPLOYEE_ID): ("Aygün", "Məmmədova")}
        )
        allowed = allowed_stores if allowed_stores is not None else [STORE_ID]
        self.manual_fines = _ManualFines(
            fine_types=fine_types if fine_types is not None else [_fine_type()],
            allowed_stores=allowed,
        )
        self.tenant_id = TENANT
        self.evidence = _EvidenceQueue()
        self.upload_runs = 0
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(self.manual_fines, self._stores, self._employees)
        self.sessions.append(created)
        yield created

    def evidence_queue(self) -> _EvidenceQueue:
        return self.evidence

    def run_evidence_uploads(self) -> int:
        self.upload_runs += 1
        return 0


class _Actor:
    id = ACTOR_ID


def _build(theme: Any, qtbot: Any, context: Any, *, executor: Any = None) -> tuple[Any, Any]:
    from src.presentation.controllers.fine_entry import FineEntryController
    from src.presentation.screens.group_b import FineEntryScreen

    controller = FineEntryController(context, _Actor(), executor=executor)
    fine_types, stores, employees = controller.options()
    screen = FineEntryScreen(theme, fine_types=fine_types, stores=stores, employees=employees)
    qtbot.addWidget(screen)
    controller.attach(screen)
    return screen, controller


def _fill_valid_form(screen: Any, tmp_path: Any) -> None:
    screen._type.set_text("Gecikmə")
    screen._store.set_text("Mərkəz")
    screen._employee.set_text("Aygün Məmmədova")
    photo = tmp_path / "subut.jpg"
    photo.write_bytes(b"\xff\xd8\xff fake jpeg")
    screen._photo.set_file(str(photo))


# --------------------------------------------------------------------------- #
# 1. Real forma — uğurlu göndəriş, sübut növbəyə düşür
# --------------------------------------------------------------------------- #


@requires_qt
def test_submitting_the_real_form_issues_the_fine_and_enqueues_the_photo(
    qtbot, theme, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.background_task import InlineExecutor

    context = _Context()
    screen, _controller = _build(theme, qtbot, context, executor=InlineExecutor())
    _fill_valid_form(screen, tmp_path)

    _click(screen, "Cəriməni Qeyd Et")

    assert len(context.manual_fines.issued) == 1
    issued = context.manual_fines.issued[0]
    assert str(issued["employee_id"]) == str(EMPLOYEE_ID)
    assert str(issued["store_id"]) == str(STORE_ID)
    assert any(s.committed for s in context.sessions)
    assert len(context.evidence.enqueued) == 1
    assert context.evidence.enqueued[0]["filename"] == "subut.jpg"
    assert context.upload_runs == 1


# --------------------------------------------------------------------------- #
# 1b. DEEP-GAP U1 — göndərişdən sonra forma TƏMİZLƏNİR, uğur mesajı görünür
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_successful_submission_clears_the_photo_and_shows_a_confirmation(
    qtbot, theme, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    """DEEP-GAP U1 — köhnə şəkil NÖVBƏTİ işçiyə keçmir.

    ƏVVƏL: uğurlu göndərişdən sonra `_photo` YERİNDƏ QALIRDI — operator
    yalnız dropdown-ları dəyişəndə yeni cərimə ƏVVƏLKİ işçinin sübut
    şəkli ilə yaranırdı. İndi `PhotoDropZone.clear()` MÜTLƏQ çağırılır və
    operator görünən bir təsdiq mesajı alır (kor-koranə təkrar klikin
    qarşısı da bununla alınır).
    """
    from src.presentation.background_task import InlineExecutor

    context = _Context()
    screen, _controller = _build(theme, qtbot, context, executor=InlineExecutor())
    _fill_valid_form(screen, tmp_path)
    assert screen._photo.file_path  # ilkin vəziyyət: şəkil seçilib

    _click(screen, "Cəriməni Qeyd Et")

    assert screen._photo.file_path == "", "Sübut şəkli göndərişdən sonra TƏMİZLƏNMƏLİ idi"
    # `isVisibleTo(screen)`, `isVisible()` YOX: sonuncu YALNIZ pəncərə HƏQİQƏTƏN
    # göstəriləndə `True` olur, offscreen testdə isə valideyn zənciri heç vaxt
    # render olunmur — yəni `isVisible()` widget düzgün qurulsa da `False`
    # qaytarır və testi YALANDAN qırardı. `isVisibleTo()` məhz «valideyn
    # göstərilsəydi görünərdimi?» sualına cavab verir.
    assert screen._success_message.isVisibleTo(screen)
    assert "Aygün Məmmədova" in screen._success_message.text()
    assert "25" in screen._success_message.text()


@requires_qt
def test_a_second_submission_without_reselecting_a_photo_is_rejected(
    qtbot, theme, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    """Formanın özü ARTIQ bilir foto məcburidir — təmizlənmə bunu SİLMİR.

    Uğurlu göndərişdən sonra operator YENİ foto seçmədən ikinci dəfə
    "Cəriməni Qeyd Et" bassa, mövcud "Foto sübutu məcburidir" qapısı
    yenidən işə düşməlidir — köhnə foto sükutla YENİDƏN işlədilməməlidir.
    """
    from src.presentation.background_task import InlineExecutor

    context = _Context()
    screen, _controller = _build(theme, qtbot, context, executor=InlineExecutor())
    _fill_valid_form(screen, tmp_path)

    _click(screen, "Cəriməni Qeyd Et")
    assert len(context.manual_fines.issued) == 1

    _click(screen, "Cəriməni Qeyd Et")  # foto YENİDƏN seçilməyib

    assert len(context.manual_fines.issued) == 1, "İkinci göndəriş yazılmamalı idi"
    assert screen._photo_error.isVisibleTo(screen)  # bax yuxarıdakı `isVisibleTo` qeydi
    assert not screen._success_message.isVisibleTo(screen), (
        "Köhnə uğur mesajı yeni cəhddə TƏMİZLƏNMƏLİ idi"
    )


@requires_qt
def test_submitting_without_a_photo_shows_the_real_validation_message(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    context = _Context()
    screen, _controller = _build(theme, qtbot, context)
    screen.show()  # `isVisible()` göstərilməyən pəncərədə HƏMİŞƏ False qaytarır

    screen._type.set_text("Gecikmə")
    screen._store.set_text("Mərkəz")
    screen._employee.set_text("Aygün Məmmədova")
    # Foto SEÇİLMƏYİB.

    _click(screen, "Cəriməni Qeyd Et")

    assert context.manual_fines.issued == []
    assert screen._photo_error.isVisibleTo(screen)  # bax yuxarıdakı `isVisibleTo` qeydi
    assert screen._photo_error.text() == "Foto sübutu məcburidir"


@requires_qt
def test_no_assigned_stores_shows_the_real_no_stores_message(qtbot, theme, tmp_path: Any) -> None:  # type: ignore[no-untyped-def]
    """Təyinatsız operator (bölmə 4 fail-safe) — real klik AÇIQ mesaj göstərir."""

    context = _Context(allowed_stores=[])
    screen, _controller = _build(theme, qtbot, context)
    _fill_valid_form(screen, tmp_path)

    _click(screen, "Cəriməni Qeyd Et")  # ÇÖKMƏMƏLİDİR

    assert context.manual_fines.issued == []
    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 2. TAPILAN QÜSUR — sürətli ikiqat klik
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_rapid_double_click_reuses_the_same_idempotency_key_within_the_window(
    qtbot, theme, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Pəncərə daxilində EYNİ açar, pəncərə bitəndən sonra YENİ açar.

    `FineEntryController._idempotency_key_for_submission()` `sales_points.py::
    _redemption_id_for` ilə EYNİ naxışdır. `monotonic()` bu testdə İDARƏ
    OLUNUR — real gözləmə YOXDUR, ona görə test sürətli və sabitdir.

    DEEP-GAP U1: uğurlu göndərişdən sonra `clear_photo()` çağırılır (bax
    `FineEntryController._issue`), ona görə hər klikdən ƏVVƏL foto YENİDƏN
    seçilir — dropdown-lar (növ/mağaza/işçi/tarix) toxunulmaz qalır, çünki
    `clear_photo()` YALNIZ fotonu təmizləyir. Bu, «operator eyni niyyətlə
    qısa aralıqla iki dəfə TAM formanı göndərir» ssenarisini modelləşdirir —
    məhz bu halda idempotency açarının EYNİ qalması vacibdir.
    """
    from src.presentation.controllers import fine_entry as fine_entry_module

    clock = {"t": 0.0}
    monkeypatch.setattr(fine_entry_module, "monotonic", lambda: clock["t"])

    context = _Context()
    screen, _controller = _build(theme, qtbot, context)
    _fill_valid_form(screen, tmp_path)

    _click(screen, "Cəriməni Qeyd Et")
    clock["t"] = 2.0  # pəncərə daxilində (DUPLICATE_SUBMISSION_WINDOW_SECONDS = 10)
    _fill_valid_form(screen, tmp_path)  # foto U1-lə TƏMİZLƏNİB, yenidən seçilir
    _click(screen, "Cəriməni Qeyd Et")

    assert len(context.manual_fines.issued) == 2
    first_key = context.manual_fines.issued[0]["idempotency_key"]
    second_key = context.manual_fines.issued[1]["idempotency_key"]
    assert first_key == second_key, "Pəncərə daxilində EYNİ idempotency_key ötürülməli idi"
    assert first_key is not None

    clock["t"] = 15.0  # pəncərə bitib
    _fill_valid_form(screen, tmp_path)
    _click(screen, "Cəriməni Qeyd Et")

    third_key = context.manual_fines.issued[2]["idempotency_key"]
    assert third_key != first_key, (
        "Pəncərə bitəndən sonra YENİ açar yaranmalı idi — əks halda TAMAMİLƏ "
        "AYRI sonrakı cərimə köhnə açarla DB-nin unikal indeksinə toqquşardı"
    )


# --------------------------------------------------------------------------- #
# 3. Ekstremal/naməlum seçim, use-case istisnası — çökmür
# --------------------------------------------------------------------------- #


@requires_qt
def test_an_empty_fine_type_catalog_disables_selection_and_writes_nothing(
    qtbot, theme, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    """Boş kataloq (`selectable_fine_types` boş qayıdır) — combo BOŞ qurulur.

    `_type` combo-su REDAKTƏ OLUNMUR (`_combo()` `setEditable(True)`
    çağırmır), yəni istifadəçi siyahıda OLMAYAN mətn seçə BİLMİR — bu,
    quruluşca müsbət tapıntıdır (bug deyil). Burada ölçülən: boş kataloqla
    açılan formanın real kliki ÇÖKMƏMƏLİDİR və heç nə yazılmamalıdır.
    """
    context = _Context(fine_types=[])
    screen, _controller = _build(theme, qtbot, context)
    screen._store.set_text("Mərkəz")
    screen._employee.set_text("Aygün Məmmədova")
    photo = tmp_path / "subut.jpg"
    photo.write_bytes(b"\xff\xd8\xff fake jpeg")
    screen._photo.set_file(str(photo))

    _click(screen, "Cəriməni Qeyd Et")  # ÇÖKMƏMƏLİDİR

    assert context.manual_fines.issued == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_issue_failure_shows_the_domain_message_and_does_not_commit(
    qtbot, theme, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    """`_require_store_scope` rəddi (operator bu mağazaya təyin edilməyib) — real klik."""
    context = _Context()
    context.manual_fines.issue_error = KompasOSError(
        "store scope denied", user_message="Bu mağaza sizin nəzarətinizdə deyil."
    )
    screen, _controller = _build(theme, qtbot, context)
    _fill_valid_form(screen, tmp_path)

    _click(screen, "Cəriməni Qeyd Et")  # ÇÖKMƏMƏLİDİR

    assert not any(s.committed for s in context.sessions)
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_an_unreadable_photo_shows_a_real_error_and_writes_nothing(
    qtbot, theme, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    """Fayl seçilib, lakin diskdən oxuna bilmir (qovluq seçimi ilə simulyasiya)."""
    context = _Context()
    screen, _controller = _build(theme, qtbot, context)

    screen._type.set_text("Gecikmə")
    screen._store.set_text("Mərkəz")
    screen._employee.set_text("Aygün Məmmədova")
    unreadable_dir = tmp_path / "qovluq"
    unreadable_dir.mkdir()
    screen._photo.set_file(str(unreadable_dir))

    _click(screen, "Cəriməni Qeyd Et")  # ÇÖKMƏMƏLİDİR

    assert context.manual_fines.issued == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_hostile_and_extreme_employee_selection_does_not_crash(qtbot, theme, tmp_path: Any) -> None:  # type: ignore[no-untyped-def]
    """Ekstremal/SQL-bənzər ad seçim siyahısında olsa belə çökmə yaratmır."""
    hostile_name = "'; DROP TABLE fines; -- 🔥"
    context = _Context(employees={str(EMPLOYEE_ID): (hostile_name, "Məmmədova")})
    screen, _controller = _build(theme, qtbot, context)
    _fill_valid_form(screen, tmp_path)
    screen._employee.set_text(f"{hostile_name} Məmmədova")

    _click(screen, "Cəriməni Qeyd Et")  # ÇÖKMƏMƏLİDİR

    assert len(context.manual_fines.issued) == 1
    assert str(context.manual_fines.issued[0]["employee_id"]) == str(EMPLOYEE_ID)
