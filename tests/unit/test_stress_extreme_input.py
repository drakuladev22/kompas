"""QA-FULL FAZA 6 — Ekstremal/zərərli mətn sınaqları (real Qt e2e).

──────────────────────────────────────────────────────────────────────────────
DÜZƏLDİLDİ — SIFIR-EN BOŞLUQ (`\\u200b`) "MƏNALI MƏTN" HƏDDİNİ ARTIQ YAN KEÇMİR
──────────────────────────────────────────────────────────────────────────────
İlkin tapıntı: `fine_appeals.py::_decide`, `shift_swaps.py::_ask_reason` və
domendəki `OpenShiftPosting.cancel()`/`FineAppeal._require_note`/
`ShiftSwapRequest.reject`/`AnnualLeaveRequest` (dörd ayrı yer) eyni
normalizasiyanı işlədirdi:

    cleaned = " ".join(note.split())
    if len(cleaned) < MIN_DECISION_..._LENGTH: rədd et

Python-un `str.split()`/`str.isspace()` YALNIZ `\\s` kateqoriyasını (adi
boşluq, tab, sətir sonu) boşluq sayır — Unicode "Format" kateqoriyasındakı
görünməz simvollar (SIFIR-EN BOŞLUQ `U+200B`, SIFIR-EN BİRLƏŞDİRİCİ `U+200C`,
SÖZ BİRLƏŞDİRİCİSİ `U+2060` və s.) bura DAXİL DEYİLDİ. Nəticə: 10 ədəd
`\\u200b`-dən ibarət — insan gözünə TAMAMİLƏ BOŞ görünən — mətn `len(cleaned)
>= 10` şərtini KEÇİRDİ və "mənalı izah" kimi qəbul edilirdi. Bu, kosmetik
deyildi: `fine_appeals.py` başlığı deyir — "işçi cərimənin niyə qüvvədə
qaldığını (və ya ləğv edildiyini) məhz bu mətndən öyrənir".

DÜZƏLİŞ (`domain` sahibi, `src/shared/text.py::normalise_decision_text`):
normalizasiya BİR yerə çıxarıldı — Unicode "Cf" (Format) kateqoriyasını
`str.split()`-dən ƏVVƏL təmizləyir. `domain` bunu ÖZ sahəsində (16 domain
entity + 8 use_case faylı) tətbiq etdi; `shift_swaps.py::_ask_reason`-un
KONTROLLER səviyyəsindəki AYRI kopiyasını isə `ui` `normalise_decision_text`
idxalı ilə əvəz etdi (`fine_appeals.py::_decide` artıq domen üzərindən
keçdiyi üçün ayrı kopiyaya malik deyildi). Hər iki test aşağıda YENİDƏN
İŞLƏDİLİB — `xfail` markerləri SİLİNİB, indi YAŞILDIR.
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()
EMPLOYEE_ID = uuid.uuid4()
FINE_ID = uuid.uuid4()
APPEAL_ID = uuid.uuid4()
REQUEST_ID = uuid.uuid4()

#: 10 ədəd sıfır-en boşluq — `MIN_DECISION_NOTE_LENGTH`/`_REASON_LENGTH`
#: (hər ikisi 10) sərhədinə TAM UYĞUNDUR, lakin insan gözünə BOŞDUR.
ZERO_WIDTH_ONLY = "\u200b" * 10

#: Ekran/log qatını sındırmağa çalışan format-simvolları — Python-un `%`
#: operatoru VƏ `str.format()` `{}`-i xüsusi mənalandırır; burada bunlar
#: adi MƏTN kimi keçməlidir, format ARQUMENTİ kimi YOX.
FORMAT_HOSTILE = "Sübut %s yoxdur, {employee} kodu %(x)d, {0}, 100% itki."

RTL_MIXED = "الدليل غير كافٍ — sübut yoxdur — עדות אינה מספקת 🔥"

NULL_BYTE_NAME = "Aygün\x00Məmmədova"


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


def _mute_modal(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from PySide6.QtWidgets import QMessageBox

    shown: list[str] = []

    def _fake_exec(self: Any) -> int:
        shown.append(self.text())
        return 0

    monkeypatch.setattr(QMessageBox, "exec", _fake_exec)
    return shown


# --------------------------------------------------------------------------- #
# Ortaq sahtələr — `fine_appeals`
# --------------------------------------------------------------------------- #


class _FaEmployees:
    def get(self, _employee_id: Any) -> Any:
        return type("E", (), {"full_name": "Aygün Məmmədova"})()


class _FaConnection:
    def __init__(self) -> None:
        self._last_sql = ""

    def execute(self, sql: str, _params: Any = None) -> _FaConnection:
        self._last_sql = sql
        return self

    def fetchone(self) -> Any:
        if "fine_types" in self._last_sql:
            return {"name": "Kassa Kəsiri"}
        if "FROM fines" in self._last_sql:
            return {"amount": "25.00"}
        return None  # pragma: no cover


class _FaUow:
    def __init__(self) -> None:
        self.employees = _FaEmployees()
        self.connection = _FaConnection()


class _FaLimits:
    def get_int(self, _tenant_id: Any, _key: str, default: int) -> int:
        return default


def _appeal() -> Any:
    from src.domain.entities.appeal import FineAppeal

    return FineAppeal(
        appeal_id=APPEAL_ID,  # type: ignore[arg-type]
        tenant_id=TENANT,  # type: ignore[arg-type]
        fine_id=FINE_ID,  # type: ignore[arg-type]
        employee_id=EMPLOYEE_ID,  # type: ignore[arg-type]
        reason="Kamerada mən görünmürəm.",
        created_at=datetime(2026, 8, 18, 9, 0, tzinfo=UTC),
        emit_created_event=False,
    )


class _FineAppeals:
    """Real `FineAppeal.approve()` üzərindən — normalizasiya DOMENDƏ baş verir."""

    def __init__(self, appeals: list[Any]) -> None:
        self._by_id = {a.id: a for a in appeals}
        self.approvals: list[dict[str, Any]] = []

    def inbox(self, *, tenant_id: Any, actor: Any) -> list[Any]:
        """`controller.refresh()` HƏR çağırışda bunu tələb edir."""
        return [a for a in self._by_id.values() if not a.status.is_decided]

    def approve(
        self, *, tenant_id: Any, actor: Any, appeal_id: Any, note: str, new_amount: Any = None
    ) -> Any:
        appeal = self._by_id[appeal_id]
        appeal.approve(
            decided_by=actor.id,
            decided_at=datetime(2026, 8, 21, 9, 0, tzinfo=UTC),
            note=note,
            new_amount=new_amount,
        )
        self.approvals.append({"appeal_id": appeal_id, "note": note})
        return appeal


class _FaSession:
    def __init__(self, appeals: _FineAppeals) -> None:
        self.tenant_id = TENANT
        self.fine_appeals = appeals
        self.limits = _FaLimits()
        self.uow = _FaUow()
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _FaContext:
    def __init__(self, appeals: _FineAppeals) -> None:
        self._appeals = appeals
        self.sessions: list[_FaSession] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _FaSession(self._appeals)
        self.sessions.append(created)
        yield created


class _Actor:
    id = ACTOR_ID


def _build_appeal_screen(theme: Any, qtbot: Any, context: _FaContext) -> tuple[Any, Any]:
    from src.presentation.controllers.fine_appeals import FineAppealInboxController
    from src.presentation.screens.group_f import FineAppealInboxScreen

    screen = FineAppealInboxScreen(theme)
    qtbot.addWidget(screen)
    controller = FineAppealInboxController(context, _Actor())  # type: ignore[arg-type]
    controller.attach(screen)
    return screen, controller


def _reason_box(screen: Any) -> Any:
    from PySide6.QtWidgets import QPlainTextEdit

    return screen.findChildren(QPlainTextEdit)[0]


# --------------------------------------------------------------------------- #
# 1. TAPILAN QÜSUR — sıfır-en boşluq "mənalı mətn" kimi qəbul edilir
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_zero_width_space_only_note_bypasses_the_meaningful_content_length_gate(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    shown = _mute_modal(monkeypatch)
    appeals = _FineAppeals([_appeal()])
    context = _FaContext(appeals)
    screen, controller = _build_appeal_screen(theme, qtbot, context)
    controller.refresh(screen)

    _reason_box(screen).setPlainText(ZERO_WIDTH_ONLY)
    _click(screen, "Qəbul Et")  # ÇÖKMƏMƏLİDİR

    assert appeals.approvals == [], "insan gözünə BOŞ görünən mətn qərar səbəbi kimi YAZILMAMALIDIR"
    assert shown, "qısa-mətn xəbərdarlığı göstərilməli idi"


@requires_qt
def test_a_zero_width_space_only_reject_reason_bypasses_the_meaningful_content_length_gate(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    from src.presentation.controllers import screen_data as screen_data_module
    from src.presentation.controllers.shift_swaps import ShiftSwapController
    from src.presentation.screens.group_c import ShiftSwapScreen

    class _Binder:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        def populate(self, _key: str, screen: Any) -> None:
            screen.set_counts({"pending": 0})
            screen.set_requests([])

    monkeypatch.setattr(screen_data_module, "ScreenDataBinder", _Binder)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: None)
    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: (ZERO_WIDTH_ONLY, True))
    )

    class _Swaps:
        def __init__(self) -> None:
            self.rejections: list[dict[str, Any]] = []

        def reject(self, *, tenant_id: Any, approver: Any, request_id: Any, reason: str) -> None:
            self.rejections.append({"request_id": request_id, "reason": reason})

    class _Session:
        def __init__(self, swaps: _Swaps) -> None:
            self.tenant_id = TENANT
            self.shift_swaps = swaps
            self.committed = False

        def commit(self) -> None:
            self.committed = True

    class _Context:
        def __init__(self, swaps: _Swaps) -> None:
            self._swaps = swaps

        @contextmanager
        def session(self, *, user_id: Any = None) -> Any:
            yield _Session(self._swaps)

    swaps = _Swaps()
    context = _Context(swaps)
    screen = ShiftSwapScreen(theme)
    qtbot.addWidget(screen)
    screen.show()
    ShiftSwapController(context, _Actor()).attach(screen)  # type: ignore[arg-type]
    screen.set_requests(
        [
            {
                "id": str(REQUEST_ID),
                "from_name": "Aygün Məmmədova",
                "to_name": "25.08.2026",
                "shift": "25.08.2026",
                "store": "Mərkəz",
                "status": "Gözləyir",
                "note": "Ailə tədbiri",
            }
        ]
    )

    from PySide6.QtCore import Qt

    card = next(c for c in screen._rows if c.key == str(REQUEST_ID))
    qtbot.mouseClick(card, Qt.MouseButton.LeftButton)
    _click(screen, "Rədd Et")  # ÇÖKMƏMƏLİDİR

    assert swaps.rejections == [], "insan gözünə BOŞ görünən mətn rədd səbəbi kimi YAZILMAMALIDIR"


# --------------------------------------------------------------------------- #
# 2. Real boşluq (adi space/tab/newline) DÜZGÜN rədd edilir — ƏKS SÜBUT
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_reason_of_only_ordinary_whitespace_including_tabs_and_newlines_is_correctly_rejected(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Yuxarıdakı qüsurun ƏKSİ — ADİ boşluq/tab/sətirsonu DÜZGÜN işləyir.

    Fərq yalnız Unicode "Format" kateqoriyasındadır (bax fayl başlığı) —
    bu test göstərir ki, normalizasiyanın ÖZÜ səhv YAZILMAYIB, sadəcə
    Unicode-un görünməz alt-çoxluğunu NƏZƏRƏ ALMIR.
    """
    shown = _mute_modal(monkeypatch)
    appeals = _FineAppeals([_appeal()])
    context = _FaContext(appeals)
    screen, controller = _build_appeal_screen(theme, qtbot, context)
    controller.refresh(screen)

    _reason_box(screen).setPlainText("   \n\t\t  \n   ")
    _click(screen, "Qəbul Et")  # ÇÖKMƏMƏLİDİR

    assert appeals.approvals == []
    assert shown


# --------------------------------------------------------------------------- #
# 2b. QANUNİ mətn ZƏDƏLƏNMİR — Azərbaycan hərfləri, rəqəm, durğu, emoji
# --------------------------------------------------------------------------- #


def test_normalise_decision_text_preserves_legitimate_content_while_stripping_only_cf_chars() -> (
    None
):
    """`normalise_decision_text` YALNIZ Unicode "Cf" (Format) kateqoriyasını
    atır — bu, ZWSP/ZWNJ/ZWJ/BOM/soft-hyphen/yön işarələri kimi HEÇ VAXT
    mənalı məzmun daşımayan, görünməz simvollardır (fayl başlığı). Digər
    bütün kateqoriyalar (hərf, rəqəm, durğu, simvol/emoji) toxunulmaz qalır —
    əks halda qapı "boş mətni tutur" əvəzinə "qanuni mətni korlayır" olardı,
    bu da eyni dərəcədə YARARSIZ bir düzəliş olardı.
    """
    from src.shared.text import normalise_decision_text

    # Azərbaycan əlifbasının latın hərflərində olmayan hərfləri (ə, ö, ü, ğ,
    # ş, ç, ı) VƏ durğu/rəqəmi ehtiva edən həqiqi HR qərar mətni.
    az_text = "Kamerada aydın görünür, işçi 3 dəqiqə gecikib — sübut kifayətdir (95%)."
    assert normalise_decision_text(az_text) == az_text

    # Emoji "Symbol, Other" (So) kateqoriyasındadır, Cf DEYİL — saxlanmalıdır.
    with_emoji = "Sübut kifayət etmir ❌ yenidən baxılacaq 🔥"
    assert normalise_decision_text(with_emoji) == with_emoji

    # Görünməz simvol MƏTNİN ORTASINA salınıb — yalnız o atılır, ətrafdakı
    # qanuni sözlər YARIMÇIQ qalmadan bir-birinə bitişmir, çünki addım (1)
    # yalnız Cf simvolunu silir, ətrafdakı boşluq toxunulmaz qalır.
    az_with_zwsp = "Kamerada aydın görünür\u200b, sübut kifayət edir."
    assert normalise_decision_text(az_with_zwsp) == "Kamerada aydın görünür, sübut kifayət edir."

    # Qarışıq kiril/ərəb mətn — Cf-dən BAŞQA heç bir skript xüsusi
    # rəftar görmür, çünki `unicodedata.category` yalnız Cf-i hədəf alır.
    cyrillic = "Доказательство недостаточно, отклонено."
    assert normalise_decision_text(cyrillic) == cyrillic


# --------------------------------------------------------------------------- #
# 3. Nəhəng mətn (50 000 simvol) — kəsilmə/çökmə yoxdur
# --------------------------------------------------------------------------- #


@requires_qt
def test_a_fifty_thousand_character_note_is_written_in_full_without_crashing_or_truncation(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """Heç bir maks-uzunluq yoxlaması YOXDUR (kontrollerdə də, domendə də) —
    bu test onu SÜBUT EDİR: giriş nə qədər böyükdürsə, o QƏDƏR yazılır.
    Performans qapısı YOXDUR (`QA-FULL Faza 5` işidir), burada YALNIZ
    çökmə/kəsilmə yoxlanılır."""
    huge = "Kamerada aydın görünür, sübut kifayət etmir. " * 1200  # ~54 000 simvol
    assert len(huge) > 50_000

    appeals = _FineAppeals([_appeal()])
    context = _FaContext(appeals)
    screen, controller = _build_appeal_screen(theme, qtbot, context)
    controller.refresh(screen)

    started = time.perf_counter()
    _reason_box(screen).setPlainText(huge)
    _click(screen, "Qəbul Et")  # ÇÖKMƏMƏLİDİR
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert len(appeals.approvals) == 1
    assert appeals.approvals[0]["note"] == " ".join(huge.split())
    assert elapsed_ms < 5000, f"50k simvollu göndəriş {elapsed_ms:.0f} ms çəkdi — dondurma şübhəsi"


# --------------------------------------------------------------------------- #
# 4. Sıfır bayt (`\\x00`) işçi adında — dropdown VƏ yazı yolu çökmür
# --------------------------------------------------------------------------- #


class _FeRow(dict):
    pass


class _FeConnection:
    def __init__(self, stores: dict[str, str], employees: dict[str, tuple[str, str]]) -> None:
        self._stores = stores
        self._employees = employees
        self._last_sql = ""

    def execute(self, sql: str, _params: Any = None) -> _FeConnection:
        self._last_sql = sql
        return self

    def fetchall(self) -> list[_FeRow]:
        if "FROM stores" in self._last_sql:
            return [_FeRow(id=sid, name=name) for sid, name in self._stores.items()]
        if "FROM employees" in self._last_sql:
            return [
                _FeRow(id=eid, first_name=first, last_name=last)
                for eid, (first, last) in self._employees.items()
            ]
        return []  # pragma: no cover


class _FeUow:
    def __init__(self, stores: dict[str, str], employees: dict[str, tuple[str, str]]) -> None:
        self.connection = _FeConnection(stores, employees)

    @property
    def fines(self) -> Any:
        return self

    def mark_evidence_pending(self, _fine_id: Any) -> None:
        return None


class _ManualFines:
    def __init__(self, *, fine_types: list[Any], allowed_stores: list[Any]) -> None:
        self._fine_types = fine_types
        self._allowed_stores = allowed_stores
        self.issued: list[dict[str, Any]] = []

    def selectable_fine_types(self, _tenant_id: Any) -> list[Any]:
        return list(self._fine_types)

    def allowed_stores(self, _operator: Any) -> list[Any]:
        return list(self._allowed_stores)

    def issue(self, **kwargs: Any) -> Any:
        self.issued.append(kwargs)
        return type("_Fine", (), {"id": kwargs.get("fine_id")})()


class _FeSession:
    def __init__(
        self,
        manual_fines: _ManualFines,
        stores: dict[str, str],
        employees: dict[str, tuple[str, str]],
    ) -> None:
        self.tenant_id = TENANT
        self.manual_fines = manual_fines
        self.uow = _FeUow(stores, employees)
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _FeContext:
    def __init__(self, *, employees: dict[str, tuple[str, str]]) -> None:
        self._stores = {str(uuid.uuid4()): "Mərkəz"}
        self.store_id = next(iter(self._stores))
        self._employees = employees
        self.manual_fines = _ManualFines(
            fine_types=[_fine_type()], allowed_stores=[uuid.UUID(self.store_id)]
        )
        self.tenant_id = TENANT
        self.evidence = _FeEvidenceQueue()
        self.upload_runs = 0
        self.sessions: list[_FeSession] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _FeSession(self.manual_fines, self._stores, self._employees)
        self.sessions.append(created)
        yield created

    def evidence_queue(self) -> _FeEvidenceQueue:
        return self.evidence

    def run_evidence_uploads(self) -> int:
        self.upload_runs += 1
        return 0


class _FeEvidenceQueue:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []
        self._counter = 0

    def enqueue(self, **kwargs: Any) -> str:
        self._counter += 1
        self.enqueued.append(kwargs)
        return f"queue-entry-{self._counter}"


def _fine_type() -> Any:
    from decimal import Decimal

    from src.domain.value_objects.catalogs import FineType
    from src.domain.value_objects.money import Money

    return FineType(
        name="Gecikmə",
        tenant_id=TENANT,
        fine_type_id=uuid.uuid4(),
        standard_amount=Money(Decimal("25")),
    )


@requires_qt
def test_a_null_byte_embedded_in_the_employee_name_does_not_crash_the_dropdown_or_write_path(
    qtbot, theme, tmp_path: Any
) -> None:  # type: ignore[no-untyped-def]
    """Postgres NUL bayt (`\\x00`) qəbul ETMİR (`psycopg`-in özü atır), lakin
    o, `infra`-nın DB sərhədidir — bura YALNIZ UI/kontroller qatının real
    fayl seçimi + kliklə ÇÖKMƏDİYİNİ sınayır."""
    from src.presentation.background_task import InlineExecutor
    from src.presentation.controllers.fine_entry import FineEntryController
    from src.presentation.screens.group_b import FineEntryScreen

    employee_id = uuid.uuid4()
    context = _FeContext(employees={str(employee_id): (NULL_BYTE_NAME, "Məmmədova")})
    controller = FineEntryController(context, _Actor(), executor=InlineExecutor())
    fine_types, stores, employees = controller.options()
    screen = FineEntryScreen(theme, fine_types=fine_types, stores=stores, employees=employees)
    qtbot.addWidget(screen)
    controller.attach(screen)

    screen._type.set_text("Gecikmə")
    screen._store.set_text("Mərkəz")
    screen._employee.set_text(f"{NULL_BYTE_NAME} Məmmədova")
    photo = tmp_path / "subut.jpg"
    photo.write_bytes(b"\xff\xd8\xff fake jpeg")
    screen._photo.set_file(str(photo))

    _click(screen, "Cəriməni Qeyd Et")  # ÇÖKMƏMƏLİDİR

    assert len(context.manual_fines.issued) == 1
    assert str(context.manual_fines.issued[0]["employee_id"]) == str(employee_id)


# --------------------------------------------------------------------------- #
# 5. RTL/qarışıq dil — çökmür
# --------------------------------------------------------------------------- #


@requires_qt
def test_rtl_and_mixed_script_note_is_normalised_and_committed_without_crashing(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    _mute_modal(monkeypatch)
    appeals = _FineAppeals([_appeal()])
    context = _FaContext(appeals)
    screen, controller = _build_appeal_screen(theme, qtbot, context)
    controller.refresh(screen)

    _reason_box(screen).setPlainText(RTL_MIXED)
    _click(screen, "Qəbul Et")  # ÇÖKMƏMƏLİDİR

    assert len(appeals.approvals) == 1
    assert appeals.approvals[0]["note"] == " ".join(RTL_MIXED.split())


# --------------------------------------------------------------------------- #
# 6. Format-simvolları (`%s`, `{}`, `%(x)d`) — log/mətn sınmır
# --------------------------------------------------------------------------- #


@requires_qt
def test_format_string_specifiers_in_the_note_pass_through_as_literal_text(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """`%s`/`{}`/`%(x)d` mətn kimi YAZILMALIDIR — heç bir yerdə format
    ARQUMENTİ kimi ŞƏRH OLUNMAMALIDIR (Python-un `%`/`.format()` çağırışları
    bu mətni QƏBUL ETMİR, sadəcə saxlayır)."""
    _mute_modal(monkeypatch)
    appeals = _FineAppeals([_appeal()])
    context = _FaContext(appeals)
    screen, controller = _build_appeal_screen(theme, qtbot, context)
    controller.refresh(screen)

    _reason_box(screen).setPlainText(FORMAT_HOSTILE)
    _click(screen, "Qəbul Et")  # ÇÖKMƏMƏLİDİR (məs. `KeyError`/`ValueError` format xətası)

    assert len(appeals.approvals) == 1
    assert appeals.approvals[0]["note"] == " ".join(FORMAT_HOSTILE.split())


@requires_qt
def test_format_string_specifiers_in_a_malformed_appeal_id_do_not_crash_the_error_log(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """`_error_log.exception(..., extra={"appeal_id": str(appeal_id_text)})`
    (`fine_appeals.py::_decide`) — `appeal_id_text` birbaşa istifadəçi
    girişindən (köhnəlmiş siqnal payload-ı) gələ bilər; `%s`/`{}` burada
    logger-in daxili formatlaşdırmasını SINDIRMAMALIDIR."""
    shown = _mute_modal(monkeypatch)
    appeals = _FineAppeals([_appeal()])
    context = _FaContext(appeals)
    screen, controller = _build_appeal_screen(theme, qtbot, context)
    controller.refresh(screen)

    hostile_id = "%s-{0}-%(x)d-" + "not-a-uuid"
    screen.accepted.emit(hostile_id, "Sübut kifayət etmir, ləğv edilir.")  # ÇÖKMƏMƏLİDİR

    assert appeals.approvals == []
    assert shown
