"""`UsersPOSThresholdController` yazı yolu (`controllers/pos_threshold.py`, ARCH-04).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ
──────────────────────────────────────────────────────────────────────────────
Kontroller `omit = ["*/presentation/*"]` istisnası (`pyproject.toml`) SİLİNƏNDƏN
sonra 0% örtüklü çıxdı (dövrə 2/3 audit, ARCH-04) — heç bir test `tests/`
daxilində adını belə çəkmirdi. Fayl POS endirim/ləğv/geri-qaytarma
səlahiyyətini yazır, yəni kassada REAL PUL təsiri olan bir siyasət qeydidir.

Bu, `POSThresholdUseCase`-in ÖZÜNÜ (guard-lar, hesablama) TƏKRAR yoxlamır —
o, `test_pos_threshold.py`-nin işidir. Burada YALNIZ kontrollerin ÖZ
məsuliyyəti ölçülür: use case-in atdığı istisnanı istifadəçiyə DÜZGÜN
tərcümə etmək, `commit()`-in DOĞRU sırada çağırılması/çağırılmaması və
yazıdan SONRA siyahının yenidən oxunması (`ScreenDataBinder`).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, ClassVar

import pytest

from src.presentation.controllers import screen_data as screen_data_module
from src.presentation.controllers.pos_threshold import UsersPOSThresholdController
from src.shared.exceptions import KompasOSError

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
EMPLOYEE = uuid.uuid4()


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _Screen:
    """`show_error` çağırışlarını yığan minimal ekran əvəzi."""

    def __init__(self) -> None:
        self.errors: list[tuple[str, str]] = []

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


class _Threshold:
    """`_show_dialog`-un oxuduğu sahələri daşıyan minimal sənəd əvəzi."""

    def __init__(
        self, *, max_discount_pct: str = "10", can_void: bool = True, can_refund: bool = False
    ) -> None:
        self.max_discount_pct = Decimal(max_discount_pct)
        self.can_void = can_void
        self.can_refund = can_refund
        self.note = "qeyd"
        self.is_active = True


class _PosThreshold:
    """`session.pos_threshold` — `POSThresholdUseCase`-in sahtəsi.

    `failure` təyin edilsə, HƏR üç metod onu atır — kontrollerin
    `KompasOSError`/gözlənilməz istisna arasındakı fərqi DOĞRU yerə
    (screen mesajı) ötürdüyünü ölçmək üçün.
    """

    def __init__(self, *, failure: Exception | None = None, existing: Any = None) -> None:
        self.failure = failure
        self.existing = existing
        self.set_calls: list[dict[str, Any]] = []
        self.revoke_calls: list[dict[str, Any]] = []

    def get_threshold(self, *, tenant_id: Any, actor: Any, employee_id: Any) -> Any:
        if self.failure is not None:
            raise self.failure
        return self.existing

    def set_threshold(self, *, tenant_id: Any, actor: Any, subject: Any, draft: Any) -> Any:
        if self.failure is not None:
            raise self.failure
        self.set_calls.append({"subject": subject, "draft": draft})
        return _Threshold(
            max_discount_pct=str(draft.max_discount_pct),
            can_void=draft.can_void,
            can_refund=draft.can_refund,
        )

    def revoke_threshold(self, *, tenant_id: Any, actor: Any, subject: Any) -> Any:
        if self.failure is not None:
            raise self.failure
        self.revoke_calls.append({"subject": subject})
        return _Threshold()


class _Limits:
    def get_str(self, tenant_id: Any, key: str, default: str) -> str:
        return default


class _Employees:
    def __init__(self, *, known: Any = None) -> None:
        self.known = known

    def get(self, employee_id: Any) -> Any:
        return self.known


class _Row(dict):
    """`session.uow.connection.execute(...).fetchall()`-un tək sətri — ad ilə."""


class _Connection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def execute(self, _sql: str, _params: Any) -> _Connection:
        return self

    def fetchall(self) -> list[_Row]:
        return [_Row(r) for r in self._rows]


class _Uow:
    def __init__(self, *, employees: _Employees, connection: _Connection) -> None:
        self.employees = employees
        self.connection = connection


class _Session:
    def __init__(
        self,
        *,
        pos_threshold: _PosThreshold,
        employees: _Employees,
        rows: list[dict[str, Any]],
    ) -> None:
        self.tenant_id = TENANT
        self.pos_threshold = pos_threshold
        self.limits = _Limits()
        self.uow = _Uow(employees=employees, connection=_Connection(rows))
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    """`ApplicationContext.session()` kontekst menecerinin sahtəsi.

    Real kontekstdə HƏR çağırış YENİ sessiya açır (bölmə 6: "kontroller
    sessiyanı SAXLAMIR") — sahtə də bunu güzgüləyir: hər `with` bloku
    `sessions` siyahısına YENİ element əlavə edir.
    """

    def __init__(self, *, pos_threshold: _PosThreshold, employees: _Employees, rows: Any) -> None:
        self._pos_threshold = pos_threshold
        self._employees = employees
        self._rows = (
            rows
            if rows is not None
            else [{"id": EMPLOYEE, "first_name": "Aysel", "last_name": "Quliyeva"}]
        )
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(
            pos_threshold=self._pos_threshold, employees=self._employees, rows=self._rows
        )
        self.sessions.append(created)
        yield created


class _Actor:
    id = uuid.uuid4()


class _Binder:
    """Sahtə `ScreenDataBinder` — `_refresh()`-in ÇAĞIRILIB-ÇAĞIRILMADIĞINI yığır."""

    populated: ClassVar[list[str]] = []

    def __init__(self, context: Any, actor: Any) -> None:
        pass

    def populate(self, key: str, screen: Any) -> None:
        _Binder.populated.append(key)


@pytest.fixture(autouse=True)
def _binder(monkeypatch: pytest.MonkeyPatch) -> None:
    _Binder.populated = []
    monkeypatch.setattr(screen_data_module, "ScreenDataBinder", _Binder)


def _controller(context: _Context) -> UsersPOSThresholdController:
    return UsersPOSThresholdController(context, _Actor())  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# `_save` — yazı yolu
# --------------------------------------------------------------------------- #


def test_a_successful_save_commits_the_session() -> None:
    """CLAUDE.md §6: unudulmuş `commit()` = sükutlu rollback — burada YOXLANIR."""
    pos = _PosThreshold()
    context = _Context(pos_threshold=pos, employees=_Employees(known=object()), rows=None)
    screen = _Screen()

    _controller(context)._save(
        screen, employee_id=EMPLOYEE, pct="12.5", void=True, refund=False, note="izah"
    )

    assert screen.errors == []
    assert context.sessions[0].committed is True
    assert pos.set_calls[0]["draft"].max_discount_pct == Decimal("12.5")


def test_a_successful_save_refreshes_the_screen() -> None:
    """Kontrollerlərin mövcudluq səbəbidir (bölmə 6): yazıdan sonra siyahı YENİDƏN oxunur."""
    context = _Context(
        pos_threshold=_PosThreshold(), employees=_Employees(known=object()), rows=None
    )

    _controller(context)._save(
        _Screen(), employee_id=EMPLOYEE, pct="5", void=False, refund=False, note=""
    )

    assert _Binder.populated == ["users"]


def test_a_rejected_save_does_not_commit_and_shows_the_domain_message() -> None:
    """Səlahiyyəti/iyerarxiyası uyğun olmayan aktor — `POSThresholdUseCase` `KompasOSError` atır.

    Kontroller bu istisnanı ÖZÜ İCAD ETMİR (bölmə 6 — `permission_matrix.py`
    ilə eyni qərar), YALNIZ `error.user_message`-i göstərir. Burada ölçülən:
    (a) `commit()` ÇAĞIRILMIR (yazı əməliyyatı geri qaytarılmış olur),
    (b) ekranda DOMEN mesajı görünür, texniki trace YOX.
    """
    denial = KompasOSError("hierarchy denied", user_message="Bu işçiyə hədd təyin edə bilməzsiniz.")
    pos = _PosThreshold(failure=denial)
    context = _Context(pos_threshold=pos, employees=_Employees(known=object()), rows=None)
    screen = _Screen()

    _controller(context)._save(
        screen, employee_id=EMPLOYEE, pct="10", void=False, refund=False, note=""
    )

    assert context.sessions[0].committed is False
    assert screen.errors == [("POS həddi yazılmadı", "Bu işçiyə hədd təyin edə bilməzsiniz.")]
    assert _Binder.populated == [], "rədd edilmiş yazıdan sonra siyahı YENİDƏN oxunmamalıdır"


def test_an_unexpected_failure_during_save_shows_a_generic_message_not_a_crash() -> None:
    """Gözlənilməz istisna (məs. bağlantı kəsilməsi) — ekran ÇÖKMÜR, generik mesaj göstərir."""
    pos = _PosThreshold(failure=RuntimeError("bağlantı kəsildi"))
    context = _Context(pos_threshold=pos, employees=_Employees(known=object()), rows=None)
    screen = _Screen()

    _controller(context)._save(
        screen, employee_id=EMPLOYEE, pct="10", void=False, refund=False, note=""
    )

    assert context.sessions[0].committed is False
    assert screen.errors == [("POS həddi yazılmadı", "Dəyişiklik saxlanmadı. Yenidən cəhd edin.")]
    assert _Binder.populated == []


def test_save_rejects_a_non_numeric_percentage_before_touching_the_session() -> None:
    """Format xətası SESSİYA AÇILMADAN tutulur — boş DB gedişi lazımsızdır."""
    context = _Context(
        pos_threshold=_PosThreshold(), employees=_Employees(known=object()), rows=None
    )
    screen = _Screen()

    _controller(context)._save(
        screen, employee_id=EMPLOYEE, pct="on beş", void=False, refund=False, note=""
    )

    assert context.sessions == [], "ədədi olmayan giriş sessiya AÇMAMALIDIR"
    assert len(screen.errors) == 1
    assert screen.errors[0][0] == "Dəyər yanlışdır"


def test_save_reports_a_missing_employee_without_writing() -> None:
    """İşçi araya silinibsə (yarış vəziyyəti) — «tapılmadı» mesajı, yazı CƏHDİ OLMUR."""
    pos = _PosThreshold()
    context = _Context(pos_threshold=pos, employees=_Employees(known=None), rows=None)
    screen = _Screen()

    _controller(context)._save(
        screen, employee_id=EMPLOYEE, pct="10", void=False, refund=False, note=""
    )

    assert context.sessions[0].committed is False
    assert pos.set_calls == []
    assert screen.errors == [
        ("İşçi tapılmadı", "Bu işçi artıq siyahıda deyil. Səhifəni yeniləyin.")
    ]


# --------------------------------------------------------------------------- #
# `_revoke` — geri-alma yolu
# --------------------------------------------------------------------------- #


def test_a_successful_revoke_commits_and_refreshes() -> None:
    pos = _PosThreshold()
    context = _Context(pos_threshold=pos, employees=_Employees(known=object()), rows=None)
    screen = _Screen()

    _controller(context)._revoke(screen, employee_id=EMPLOYEE)

    assert screen.errors == []
    assert context.sessions[0].committed is True
    assert len(pos.revoke_calls) == 1
    assert _Binder.populated == ["users"]


def test_a_rejected_revoke_does_not_commit() -> None:
    denial = KompasOSError(
        "hierarchy denied", user_message="Bu işçinin həddini geri ala bilməzsiniz."
    )
    pos = _PosThreshold(failure=denial)
    context = _Context(pos_threshold=pos, employees=_Employees(known=object()), rows=None)
    screen = _Screen()

    _controller(context)._revoke(screen, employee_id=EMPLOYEE)

    assert context.sessions[0].committed is False
    assert screen.errors == [
        ("POS həddi geri alınmadı", "Bu işçinin həddini geri ala bilməzsiniz.")
    ]
    assert _Binder.populated == []


# --------------------------------------------------------------------------- #
# `_open_dialog` — oxu yolu VƏ xəta halında ekranın vəziyyəti
# --------------------------------------------------------------------------- #


def test_open_dialog_reports_a_missing_employee_and_never_opens_a_dialog() -> None:
    """Boş/silinmiş işçi — susqun boş ekran QADAĞANDIR, AÇIQ mesaj göstərilməlidir."""
    context = _Context(pos_threshold=_PosThreshold(), employees=_Employees(known=object()), rows=[])
    screen = _Screen()
    controller = _controller(context)
    opened: list[Any] = []
    controller._show_dialog = lambda *a, **kw: opened.append((a, kw))  # type: ignore[method-assign]

    controller._open_dialog(screen, "Naməlum Şəxs")

    assert opened == []
    assert screen.errors == [
        ("İşçi tapılmadı", "Bu işçi artıq siyahıda deyil. Səhifəni yeniləyin.")
    ]


def test_open_dialog_surfaces_an_unexpected_failure_instead_of_hanging() -> None:
    """Oxu zamanı gözlənilməz istisna — ekran SUSMUR, aydın mesaj göstərir."""
    pos = _PosThreshold(failure=RuntimeError("baza əlçatmazdır"))
    context = _Context(pos_threshold=pos, employees=_Employees(known=object()), rows=None)
    screen = _Screen()
    controller = _controller(context)
    opened: list[Any] = []
    controller._show_dialog = lambda *a, **kw: opened.append((a, kw))  # type: ignore[method-assign]

    controller._open_dialog(screen, "Aysel Quliyeva")

    assert opened == []
    assert screen.errors == [("POS həddi açıla bilmədi", "Məlumat yüklənmədi. Yenidən cəhd edin.")]


def test_open_dialog_passes_the_existing_record_through_to_the_dialog() -> None:
    """Mövcud sənəd VARSA dialoqa ÖTÜRÜLÜR — həmişə "boş forma" göstərmək səhv olardı.

    `ceiling` `_Limits.get_str()`-in (sistem həddi, sahtədə DEFAULT_LIMITS-ə
    bərabər "100") nəticəsidir — `existing`-in ÖZ sahəsi DEYİL, bu ikisi
    QARIŞDIRILMAMALIDIR (biri fərdi sənəd, digəri qlobal tavan).
    """
    existing = _Threshold(max_discount_pct="20", can_void=True, can_refund=True)
    pos = _PosThreshold(existing=existing)
    context = _Context(pos_threshold=pos, employees=_Employees(known=object()), rows=None)
    screen = _Screen()
    controller = _controller(context)
    calls: list[dict[str, Any]] = []
    controller._show_dialog = lambda scr, **kw: calls.append(kw)  # type: ignore[method-assign]

    controller._open_dialog(screen, "Aysel Quliyeva")

    assert screen.errors == []
    assert calls == [
        {
            "employee_id": EMPLOYEE,
            "full_name": "Aysel Quliyeva",
            "existing": existing,
            "ceiling": "100",
        }
    ]


# --------------------------------------------------------------------------- #
# `_on_action` — yönləndirmə
# --------------------------------------------------------------------------- #


def test_unrelated_actions_are_ignored() -> None:
    """ "···" menyusunun BAŞQA maddələri (`reset_pin` və s.) bu kontrollerdən keçmir."""
    context = _Context(
        pos_threshold=_PosThreshold(), employees=_Employees(known=object()), rows=None
    )
    controller = _controller(context)
    opened: list[str] = []
    controller._open_dialog = lambda screen, name: opened.append(name)  # type: ignore[method-assign]

    controller._on_action(_Screen(), "reset_pin", "Aysel Quliyeva")

    assert opened == []
    assert context.sessions == []
