"""Açıq Növbə Bazarının YAZI yolu (`controllers/open_shift.py`, ARCH-04).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ
──────────────────────────────────────────────────────────────────────────────
Fayl `pyproject.toml`-un `omit = ["*/presentation/*"]` istisnası SİLİNƏNDƏN
sonra 0% örtüklü çıxdı (dövrə 2/3 audit, ARCH-04) — `tests/` daxilində adı
HEÇ YERDƏ çəkilmirdi. İKİ kontroller BİR faylda: işçi tərəfi (kiosk, "növbəni
götür") VƏ admin tərəfi (elan/ləğv). `OpenShiftMarketUseCase`-in özü
`test_open_shift_market.py`-də ölçülür — burada YALNIZ kontrollerin öz
məsuliyyəti: `commit()`-in doğru sırada çağırılması, rədd edilmiş yazının
geri qaytarılması, yazıdan SONRA siyahının yenidən oxunması VƏ boş/xəta
halında ekranın göstərdiyi (modul başlığı: "kioskda istisna EKRANA ÇIXMIR").
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from src.application.use_cases.open_shift_market import OpenShiftView
from src.domain.value_objects.identifiers import (
    OpenShiftPostingId,
    StoreId,
    WorkModeId,
)
from src.presentation.controllers.open_shift import (
    EmployeeOpenShiftController,
    ShiftMatrixOpenShiftController,
)
from src.shared.exceptions import KompasOSError

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
STORE = StoreId(uuid.uuid4())
WORK_MODE = WorkModeId(uuid.uuid4())
POSTING = OpenShiftPostingId(uuid.uuid4())
_STORE_ROW_ID = uuid.uuid4()


def _view(*, posting: Any = POSTING, store: Any = STORE, mode: Any = WORK_MODE) -> OpenShiftView:
    return OpenShiftView(
        posting_id=posting,
        store_id=store,
        shift_date=date(2026, 8, 20),
        work_mode_id=mode,
        status="OPEN",
        posted_by=None,
        claimed_by=None,
        created_at=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
    )


# --------------------------------------------------------------------------- #
# Sahtələr — hər ikisi HƏR yazıdan SONRA YENİ sessiya açır (CLAUDE.md §6)
# --------------------------------------------------------------------------- #


class _EmployeeScreen:
    def __init__(self) -> None:
        self.rows: list[dict[str, str]] = []
        #: DEEP-GAP OP-4 — «Tutduğunuz növbələr» bölməsinin sətirləri.
        self.claimed_rows: list[dict[str, str]] = []
        self.messages: list[str] = []

    def set_open_shifts(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows

    def set_claimed_shifts(self, rows: list[dict[str, str]]) -> None:
        self.claimed_rows = rows

    def set_open_shift_message(self, message: str) -> None:
        self.messages.append(message)


class _AdminScreen:
    def __init__(self) -> None:
        self.postings: list[dict[str, str]] = []
        #: DEEP-GAP OP-4 — «Tutulmuş növbələr» bölməsinin sətirləri.
        self.claimed: list[dict[str, str]] = []
        self.errors: list[tuple[str, str]] = []

    def set_open_shift_postings(self, rows: list[dict[str, str]]) -> None:
        self.postings = rows

    def set_claimed_open_shifts(self, rows: list[dict[str, str]]) -> None:
        self.claimed = rows

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


class _OpenShifts:
    """`session.open_shifts` — `OpenShiftMarketUseCase`-in sahtəsi."""

    def __init__(
        self,
        *,
        views: list[OpenShiftView] | None = None,
        claimed_views: list[OpenShiftView] | None = None,
        list_failure: Exception | None = None,
        write_failure: Exception | None = None,
    ) -> None:
        self.views = views if views is not None else [_view()]
        #: DEEP-GAP OP-4 — işçinin TUTDUĞU, hələ baş verməmiş növbələr.
        self.claimed_views = claimed_views or []
        self.list_failure = list_failure
        self.write_failure = write_failure
        self.claims: list[Any] = []
        self.releases: list[dict[str, Any]] = []
        self.posts: list[dict[str, Any]] = []
        self.cancels: list[dict[str, Any]] = []

    def list_for_employee(self, *, tenant_id: Any, employee: Any) -> list[OpenShiftView]:
        if self.list_failure is not None:
            raise self.list_failure
        return self.views

    def list_claimed_for_employee(self, *, tenant_id: Any, employee: Any) -> list[OpenShiftView]:
        """DEEP-GAP OP-4 — «Tutduğunuz növbələr» bölməsinin oxu yolu.

        Defolt BOŞ siyahıdır: mövcud testlər TUTMA axınını ölçür və orada
        işçinin hələ tutduğu növbə yoxdur. Geri vermə testləri `claimed_views`
        ötürür. Oxu uğursuzluğu `list_failure` ilə EYNİ yoldan gedir — hər iki
        siyahı `refresh()`-də EYNİ sessiyadadır, yəni biri çöksə ikincisi də
        oxunmur.
        """
        if self.list_failure is not None:
            raise self.list_failure
        return self.claimed_views

    def release_claim(self, *, tenant_id: Any, actor: Any, posting_id: Any, reason: str) -> None:
        if self.write_failure is not None:
            raise self.write_failure
        self.releases.append({"posting_id": posting_id, "reason": reason})

    def list_active(self, *, tenant_id: Any, actor: Any) -> list[OpenShiftView]:
        if self.list_failure is not None:
            raise self.list_failure
        return self.views

    def list_claimed_for_store(self, *, tenant_id: Any, actor: Any) -> list[OpenShiftView]:
        """DEEP-GAP OP-4 — menecerin «Tutulmuş növbələr» siyahısı.

        `list_active` ilə EYNİ sessiyada oxunur, ona görə uğursuzluq da EYNİ
        `list_failure` açarından gəlir.
        """
        if self.list_failure is not None:
            raise self.list_failure
        return self.claimed_views

    def claim(self, *, tenant_id: Any, employee: Any, posting_id: Any) -> None:
        if self.write_failure is not None:
            raise self.write_failure
        self.claims.append(posting_id)

    def post_open_shift(
        self, *, tenant_id: Any, actor: Any, store_id: Any, shift_date: Any, work_mode_id: Any
    ) -> None:
        if self.write_failure is not None:
            raise self.write_failure
        self.posts.append({"store_id": store_id, "shift_date": shift_date, "mode": work_mode_id})

    def cancel_posting(self, *, tenant_id: Any, actor: Any, posting_id: Any, reason: str) -> None:
        if self.write_failure is not None:
            raise self.write_failure
        self.cancels.append({"posting_id": posting_id, "reason": reason})


class _WorkMode:
    def __init__(self, *, name: str = "Gündüz") -> None:
        self.name = name

    def scheduled_start_label(self) -> str:
        return "09:00"


class _WorkModesRepo:
    def __init__(self, *, mode: _WorkMode | None = None) -> None:
        self._mode = mode

    def get(self, work_mode_id: Any) -> _WorkMode | None:
        return self._mode


class _Row(dict):
    pass


class _Connection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows if rows is not None else [{"id": _STORE_ROW_ID, "name": "Bellona 28 May"}]

    def execute(self, _sql: str, _params: Any) -> _Connection:
        return self

    def fetchall(self) -> list[_Row]:
        return [_Row(r) for r in self._rows]

    def fetchone(self) -> _Row | None:
        return _Row(self._rows[0]) if self._rows else None


class _EmployeesRepo:
    """DEEP-GAP OP-4 — `_to_claimed_row` işçinin ADINI oxuyur.

    Menecer «kimin növbəsini geri verirəm?» sualının cavabını görməlidir;
    tapılmayan işçi üçün ad BOŞ qalır (yalan ad göstərilmir).
    """

    def __init__(self, name: str = "Aygün Məmmədova") -> None:
        self._name = name

    def get(self, _employee_id: Any) -> Any:
        return SimpleNamespace(full_name=self._name)


class _Uow:
    def __init__(self, *, work_mode: _WorkMode | None) -> None:
        self._repos = {"work_modes": _WorkModesRepo(mode=work_mode)}
        self.connection = _Connection()
        self.employees = _EmployeesRepo()

    def repository(self, name: str) -> Any:
        return self._repos[name]


class _Limits:
    def get_int(self, tenant_id: Any, key: str, default: int) -> int:
        return default


class _WorkModeSelection:
    def __init__(self) -> None:
        self.work_mode_id = WORK_MODE
        self.name = "Gündüz"

    def scheduled_start_label(self) -> str:
        return "09:00"


class _WorkModesCatalog:
    def list_for_selection(self, tenant_id: Any) -> list[_WorkModeSelection]:
        return [_WorkModeSelection()]


class _Session:
    def __init__(self, *, open_shifts: _OpenShifts, work_mode: _WorkMode | None) -> None:
        self.tenant_id = TENANT
        self.open_shifts = open_shifts
        self.uow = _Uow(work_mode=work_mode)
        self.limits = _Limits()
        self.work_modes = _WorkModesCatalog()
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(self, *, open_shifts: _OpenShifts, work_mode: _WorkMode | None = None) -> None:
        self._open_shifts = open_shifts
        self._work_mode = work_mode
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(open_shifts=self._open_shifts, work_mode=self._work_mode)
        self.sessions.append(created)
        yield created


class _Actor:
    id = uuid.uuid4()


# --------------------------------------------------------------------------- #
# `EmployeeOpenShiftController.refresh` / `_on_claim`
# --------------------------------------------------------------------------- #


def test_refresh_lists_the_open_shifts_with_their_work_mode_names() -> None:
    context = _Context(open_shifts=_OpenShifts(), work_mode=_WorkMode(name="Axşam"))
    screen = _EmployeeScreen()

    EmployeeOpenShiftController(context, _Actor()).refresh(screen)  # type: ignore[arg-type]

    assert screen.rows == [
        {"id": str(POSTING), "date": "20.08.2026 · C.a", "work_mode": "Axşam · 09:00"}
    ]


def test_refresh_never_crashes_the_kiosk_on_a_read_failure() -> None:
    """Modul başlığı: kioskda istisna EKRANA ÇIXMIR — susqun boş siyahı DEYİL, İZAHLI boş siyahı."""
    context = _Context(open_shifts=_OpenShifts(list_failure=RuntimeError("baza əlçatmazdır")))
    screen = _EmployeeScreen()

    EmployeeOpenShiftController(context, _Actor()).refresh(screen)  # type: ignore[arg-type]

    assert screen.rows == []
    assert screen.messages == ["Açıq növbə siyahısı yüklənmədi."]


def test_a_successful_claim_commits_and_re_reads_the_list() -> None:
    shifts = _OpenShifts()
    context = _Context(open_shifts=shifts, work_mode=_WorkMode())
    screen = _EmployeeScreen()

    EmployeeOpenShiftController(context, _Actor())._on_claim(screen, str(POSTING))  # type: ignore[arg-type]

    assert shifts.claims == [POSTING]
    assert context.sessions[0].committed is True
    # `refresh()` İKİNCİ (YENİ) sessiyada baş verir — CLAUDE.md §6: sessiya SAXLANMIR.
    assert len(context.sessions) == 2
    assert screen.messages[-1] == "Növbə sizin adınıza yazıldı."


def test_losing_the_race_does_not_commit_but_still_refreshes_with_the_domain_message() -> None:
    """Yarışı uduzmaq (`OpenShiftAlreadyClaimedError`) — siyahı YENƏ DƏ yenidən oxunur.

    Kontroller bunu YENİDƏN İCAD ETMİR: `error.user_message` birbaşa göstərilir
    (bax `_on_claim` şərhi), amma `refresh()` mütləq çağırılır — əks halda
    işçi artıq tutulmuş elanı YENƏ ekranında görər və İKİNCİ dəfə basar.
    """
    denial = KompasOSError("already claimed", user_message="Bu növbəni artıq başqası götürüb.")
    shifts = _OpenShifts(write_failure=denial, views=[])
    context = _Context(open_shifts=shifts)
    screen = _EmployeeScreen()

    EmployeeOpenShiftController(context, _Actor())._on_claim(screen, str(POSTING))  # type: ignore[arg-type]

    assert context.sessions[0].committed is False
    assert screen.messages[-1] == "Bu növbəni artıq başqası götürüb."
    assert screen.rows == [], "yenidən oxunan siyahı boşdursa boş göstərilməlidir"


def test_an_unexpected_claim_failure_shows_a_generic_message_and_still_refreshes() -> None:
    shifts = _OpenShifts(write_failure=RuntimeError("bağlantı kəsildi"))
    context = _Context(open_shifts=shifts)
    screen = _EmployeeScreen()

    EmployeeOpenShiftController(context, _Actor())._on_claim(screen, str(POSTING))  # type: ignore[arg-type]

    assert context.sessions[0].committed is False
    assert screen.messages[-1] == "Növbə götürülmədi. Yenidən cəhd edin."


def test_a_malformed_posting_id_never_opens_a_session() -> None:
    context = _Context(open_shifts=_OpenShifts())
    screen = _EmployeeScreen()

    EmployeeOpenShiftController(context, _Actor())._on_claim(screen, "uuid-deyil")  # type: ignore[arg-type]

    assert context.sessions == []
    assert screen.messages == ["Elan identifikatoru düzgün deyil."]


# --------------------------------------------------------------------------- #
# `ShiftMatrixOpenShiftController.refresh`
# --------------------------------------------------------------------------- #


def test_admin_refresh_lists_the_active_postings() -> None:
    context = _Context(open_shifts=_OpenShifts(), work_mode=_WorkMode())
    screen = _AdminScreen()

    ShiftMatrixOpenShiftController(context, _Actor()).refresh(screen)  # type: ignore[arg-type]

    assert screen.postings[0]["id"] == str(POSTING)
    assert screen.errors == []


def test_admin_refresh_shows_the_domain_error_and_empties_the_list() -> None:
    denial = KompasOSError("no permission", user_message="Bu paneli görmək icazəniz yoxdur.")
    context = _Context(open_shifts=_OpenShifts(list_failure=denial))
    screen = _AdminScreen()

    ShiftMatrixOpenShiftController(context, _Actor()).refresh(screen)  # type: ignore[arg-type]

    assert screen.postings == []
    assert screen.errors == [("Açıq növbələr oxunmadı", "Bu paneli görmək icazəniz yoxdur.")]


def test_admin_refresh_on_an_unexpected_failure_shows_an_error_too() -> None:
    """QA-14 (dövrə 3 audit) DÜZƏLDİ: gözlənilməz istisnada da panel SƏBƏBİ göstərir.

    `KompasOSError` budağı ilə MÜQAYİSƏ ET: domen rədd etsə admin AYDIN mesaj
    görür (yuxarıdakı test) — əvvəl baza/şəbəkə kimi gözlənilməz xəta baş
    verəndə admin YALNIZ BOŞ PANEL görürdü, mesaj YOX idi (asimmetriya).
    İndi hər iki qol SİMMETRİKDİR: siyahı boşalır VƏ səbəb göstərilir. Test
    ARTIQ DÜZƏLMİŞ davranışı sənədləşdirir (əvvəlki adı "...silently" idi —
    artıq doğru deyil).
    """
    context = _Context(open_shifts=_OpenShifts(list_failure=RuntimeError("baza əlçatmazdır")))
    screen = _AdminScreen()

    ShiftMatrixOpenShiftController(context, _Actor()).refresh(screen)  # type: ignore[arg-type]

    assert screen.postings == []
    assert screen.errors == [("Açıq növbələr oxunmadı", "Siyahı yüklənmədi. Yenidən cəhd edin.")]


# --------------------------------------------------------------------------- #
# `ShiftMatrixOpenShiftController._submit` — elan yazı yolu
# --------------------------------------------------------------------------- #


def test_a_successful_post_commits_and_refreshes() -> None:
    shifts = _OpenShifts()
    context = _Context(open_shifts=shifts, work_mode=_WorkMode())
    screen = _AdminScreen()

    ShiftMatrixOpenShiftController(context, _Actor())._submit(  # type: ignore[arg-type]
        screen, str(STORE), "2026-08-20", str(WORK_MODE)
    )

    assert shifts.posts == [{"store_id": STORE, "shift_date": date(2026, 8, 20), "mode": WORK_MODE}]
    assert context.sessions[0].committed is True
    assert screen.errors == []
    assert len(context.sessions) == 2, "yazıdan SONRA YENİ sessiyada YENİDƏN oxunmalıdır"


def test_post_rejects_malformed_values_before_opening_a_session() -> None:
    context = _Context(open_shifts=_OpenShifts())
    screen = _AdminScreen()

    ShiftMatrixOpenShiftController(context, _Actor())._submit(  # type: ignore[arg-type]
        screen, "uuid-deyil", "2026-08-20", str(WORK_MODE)
    )

    assert context.sessions == []
    assert screen.errors == [("Elan yaradılmadı", "Seçilmiş dəyərlər düzgün deyil.")]


def test_a_rejected_post_does_not_commit_or_refresh() -> None:
    denial = KompasOSError("hierarchy denied", user_message="Bu mağaza üçün elan verə bilməzsiniz.")
    context = _Context(open_shifts=_OpenShifts(write_failure=denial))
    screen = _AdminScreen()

    ShiftMatrixOpenShiftController(context, _Actor())._submit(  # type: ignore[arg-type]
        screen, str(STORE), "2026-08-20", str(WORK_MODE)
    )

    assert context.sessions[0].committed is False
    assert screen.errors == [("Elan yaradılmadı", "Bu mağaza üçün elan verə bilməzsiniz.")]
    assert len(context.sessions) == 1, "rədd edildikdə siyahı YENİDƏN OXUNMAMALIDIR"


def test_an_unexpected_post_failure_shows_a_generic_message() -> None:
    context = _Context(open_shifts=_OpenShifts(write_failure=RuntimeError("kəsildi")))
    screen = _AdminScreen()

    ShiftMatrixOpenShiftController(context, _Actor())._submit(  # type: ignore[arg-type]
        screen, str(STORE), "2026-08-20", str(WORK_MODE)
    )

    assert context.sessions[0].committed is False
    assert screen.errors == [("Elan yaradılmadı", "Elan yazılmadı. Yenidən cəhd edin.")]


def test_on_post_surfaces_a_dialog_data_failure_without_opening_a_dialog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _Context(open_shifts=_OpenShifts(list_failure=RuntimeError("kəsildi")))
    # `list_failure` `_store_choices`/`_work_mode_choices`-a təsir ETMİR (onlar
    # `open_shifts`-dən keçmir) — session AÇILIŞININ özünü sındırmaq üçün
    # `session` context manager-i yerində istisna atan sahtə işlədilir.
    from src.presentation import controllers

    controller = ShiftMatrixOpenShiftController(context, _Actor())  # type: ignore[arg-type]

    def _boom(*, user_id: Any = None) -> Any:
        raise RuntimeError("baza əlçatmazdır")

    monkeypatch.setattr(context, "session", _boom)
    screen = _AdminScreen()

    controller._on_post(screen)  # type: ignore[arg-type]

    assert screen.errors == [
        (
            "Elan forması açılmadı",
            "Mağaza və iş rejimi siyahısı oxunmadı. Yenidən cəhd edin.",
        )
    ]
    del controllers  # yalnız importun mövcudluğunu göstərmək üçün, işlədilmir


# --------------------------------------------------------------------------- #
# `ShiftMatrixOpenShiftController._on_cancel` — ləğv yazı yolu
# --------------------------------------------------------------------------- #


def _patch_reason(monkeypatch: pytest.MonkeyPatch, *, accepted: bool, text: str) -> None:
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: (text, accepted))
    )


def test_cancel_does_nothing_without_a_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_reason(monkeypatch, accepted=True, text="   ")
    context = _Context(open_shifts=_OpenShifts())

    ShiftMatrixOpenShiftController(context, _Actor())._on_cancel(  # type: ignore[arg-type]
        _AdminScreen(), str(POSTING)
    )

    assert context.sessions == []


def test_a_successful_cancel_commits_and_refreshes(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_reason(monkeypatch, accepted=True, text="mağaza bağlıdır")
    shifts = _OpenShifts()
    context = _Context(open_shifts=shifts, work_mode=_WorkMode())
    screen = _AdminScreen()

    ShiftMatrixOpenShiftController(context, _Actor())._on_cancel(  # type: ignore[arg-type]
        screen, str(POSTING)
    )

    assert shifts.cancels == [{"posting_id": POSTING, "reason": "mağaza bağlıdır"}]
    assert context.sessions[0].committed is True
    assert len(context.sessions) == 2


def test_a_rejected_cancel_still_refreshes_because_the_posting_may_already_be_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_on_cancel`-in ÖZ qərarı `_submit`-dən FƏRQLİDİR: rədd edildikdə DƏ `refresh()` çağırılır.

    Şərh (mənbə): "Elan bu arada tutulubsa da bura düşür — admin AÇIQ cavab
    alır." Yəni ADMIN görməli ki, elan artıq işçi tərəfindən götürülüb.
    """
    denial = KompasOSError("already claimed", user_message="Elan artıq götürülüb.")
    context = _Context(open_shifts=_OpenShifts(write_failure=denial))
    _patch_reason(monkeypatch, accepted=True, text="mağaza bağlıdır")
    screen = _AdminScreen()

    ShiftMatrixOpenShiftController(context, _Actor())._on_cancel(  # type: ignore[arg-type]
        screen, str(POSTING)
    )

    assert context.sessions[0].committed is False
    assert screen.errors == [("Elan ləğv edilmədi", "Elan artıq götürülüb.")]
    assert len(context.sessions) == 2, "rədd edildikdə BELƏ siyahı yenidən oxunmalıdır"


def test_an_unexpected_cancel_failure_shows_a_generic_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_reason(monkeypatch, accepted=True, text="səbəb")
    context = _Context(open_shifts=_OpenShifts(write_failure=RuntimeError("kəsildi")))
    screen = _AdminScreen()

    ShiftMatrixOpenShiftController(context, _Actor())._on_cancel(  # type: ignore[arg-type]
        screen, str(POSTING)
    )

    assert context.sessions[0].committed is False
    assert screen.errors == [("Elan ləğv edilmədi", "Dəyişiklik yazılmadı. Yenidən cəhd edin.")]


def test_cancel_rejects_a_malformed_posting_id_without_asking_for_a_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[bool] = []
    monkeypatch.setattr(
        ShiftMatrixOpenShiftController,
        "_ask_reason",
        staticmethod(lambda screen: asked.append(True)),
    )
    context = _Context(open_shifts=_OpenShifts())
    screen = _AdminScreen()

    ShiftMatrixOpenShiftController(context, _Actor())._on_cancel(  # type: ignore[arg-type]
        screen, "uuid-deyil"
    )

    assert asked == []
    assert context.sessions == []
    assert screen.errors == [("Elan ləğv edilmədi", "Elan identifikatoru düzgün deyil.")]


# --------------------------------------------------------------------------- #
# `_on_post` — dialoq üçün seçim siyahılarının qurulması
# --------------------------------------------------------------------------- #


def test_on_post_loads_choices_and_opens_a_real_dialog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Uğurlu yol: seçimlər DÜZGÜN oxunur VƏ real dialoq qurulur (Qt-siz doğrulama).

    Real `OpenShiftPostDialog` qurulmasının ÖZÜ (siqnal bağlanması, exec())
    bu faylın əhatəsindən kənardır (digər iki kontroller faylı ilə eyni
    sərhəd) — burada YALNIZ dialoqun ALDIĞI seçim siyahılarının DÜZGÜN
    qurulduğu monkeypatch edilmiş konstruktorla ölçülür.
    """
    from src.presentation.screens import open_shift as open_shift_screen_module

    captured: dict[str, Any] = {}

    class _FakeDialog:
        submitted = type("_Signal", (), {"connect": lambda self, slot: None})()

        def __init__(
            self, theme: Any, *, stores: Any, days: Any, work_modes: Any, parent: Any
        ) -> None:
            captured["stores"] = stores
            captured["days"] = days
            captured["work_modes"] = work_modes

        def exec(self) -> None:
            captured["executed"] = True

    monkeypatch.setattr(open_shift_screen_module, "OpenShiftPostDialog", _FakeDialog)
    context = _Context(open_shifts=_OpenShifts(), work_mode=_WorkMode())
    screen = _AdminScreen()
    screen.theme = "theme"  # type: ignore[attr-defined]

    ShiftMatrixOpenShiftController(context, _Actor())._on_post(screen)  # type: ignore[arg-type]

    assert captured["stores"] == [(str(_STORE_ROW_ID), "Bellona 28 May")]
    assert captured["work_modes"] == [(str(WORK_MODE), "Gündüz · 09:00")]
    assert captured["executed"] is True
    assert len(captured["days"]) == 31, "FALLBACK_MAX_LEAD_DAYS=30 → bugün + 30 gün"
    assert captured["days"][0][0] == date.today().isoformat()  # noqa: DTZ011 — `_day_choices` ilə EYNİ qərar


# --------------------------------------------------------------------------- #
# DEEP-GAP OP-4 — `[Geri Ver]`: tutulmuş növbə bazara QAYIDIR
# --------------------------------------------------------------------------- #
#
# `claim()` TERMİNAL idi: işçi növbəni götürüb sonra xəstələnsə, slot təqvimdə
# DOLU görünürdü, faktiki isə boş qalırdı və heç kim onun yenidən
# doldurulmalı olduğunu bilmirdi. Aşağıdakı testlər həm siyahının GÖRÜNDÜYÜNÜ,
# həm də səbəb qaydasının POZULMADIĞINI kilidləyir.


def test_the_claimed_shifts_are_shown_to_the_employee() -> None:
    """Geri vermə düyməsinin ASILDIĞI sətir mövcud olmalıdır."""
    market = _OpenShifts(views=[], claimed_views=[_view()])
    context = _Context(open_shifts=market)
    screen = _EmployeeScreen()

    EmployeeOpenShiftController(context, _Actor()).refresh(screen)  # type: ignore[arg-type]

    assert screen.rows == []
    assert len(screen.claimed_rows) == 1


def test_releasing_a_claim_asks_for_a_reason_and_writes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BİR dialoq, BİR yazı — səbəb domenə OLDUĞU KİMİ ötürülür."""
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(
        QInputDialog,
        "getMultiLineText",
        staticmethod(lambda *a, **k: ("Xəstələndim, həkim arayışı var", True)),
    )
    market = _OpenShifts(views=[], claimed_views=[_view()])
    context = _Context(open_shifts=market)
    screen = _EmployeeScreen()
    controller = EmployeeOpenShiftController(context, _Actor())  # type: ignore[arg-type]

    controller._on_release(screen, str(POSTING))  # type: ignore[arg-type]

    assert len(market.releases) == 1
    assert market.releases[0]["reason"] == "Xəstələndim, həkim arayışı var"
    # YAZI sessiyası commit olunur; SONUNCU sessiya isə `refresh()`-in OXU
    # sessiyasıdır və o, commit ETMİR (kontroller sessiyanı saxlamır — hər
    # əməliyyat üçün yenisini açır, CLAUDE.md §6).
    assert any(session.committed for session in context.sessions)
    assert screen.messages[-1] == "Növbə bazara qaytarıldı."


def test_a_cancelled_reason_dialog_releases_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Səbəb MƏCBURİDİR — ləğv edilən dialoq heç nə yazmır."""
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("", False)))
    market = _OpenShifts(views=[], claimed_views=[_view()])
    context = _Context(open_shifts=market)
    controller = EmployeeOpenShiftController(context, _Actor())  # type: ignore[arg-type]

    controller._on_release(_EmployeeScreen(), str(POSTING))  # type: ignore[arg-type]

    assert market.releases == []
    assert context.sessions == []


def test_a_short_reason_never_reaches_the_use_case(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hədd DOMENDƏNDİR — dialoq onu ekranda TƏKRAR yoxlayır (mətn itmir).

    Naxış `camera_queue._ask_reason`-dandır (DEEP-GAP U9): qısa cavabdan sonra
    dialoq YAZILAN MƏTNLƏ yenidən açılır, operator sıfırdan yazmır. Burada
    ikinci dəfə ləğv edilir — dövrə sonsuz olmamalıdır.
    """
    from PySide6.QtWidgets import QInputDialog

    calls: list[tuple[Any, ...]] = []

    def _multiline(*args: Any, **kwargs: Any) -> tuple[str, bool]:
        calls.append(args)
        return ("qısa", True) if len(calls) == 1 else ("", False)

    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(_multiline))

    # `QMessageBox` SİNFİ əvəzlənir, YALNIZ `exec` deyil: xəbərdarlıq qutusu
    # `QMessageBox(screen)` şəklində qurulur və bu faylın ekran sahtəsi REAL
    # `QWidget` DEYİL (testlər Qt-siz işləyir — bax faylın digər testləri).
    class _Box:
        Icon = type("Icon", (), {"Warning": 0})

        def __init__(self, _parent: Any) -> None:
            pass

        def setIcon(self, _icon: Any) -> None:  # noqa: N802 - Qt adlandırması
            pass

        def setWindowTitle(self, _title: str) -> None:  # noqa: N802 - Qt adlandırması
            pass

        def setText(self, _text: str) -> None:  # noqa: N802 - Qt adlandırması
            pass

        def exec(self) -> None:
            pass

    from PySide6 import QtWidgets

    monkeypatch.setattr(QtWidgets, "QMessageBox", _Box)
    market = _OpenShifts(views=[], claimed_views=[_view()])
    context = _Context(open_shifts=market)
    controller = EmployeeOpenShiftController(context, _Actor())  # type: ignore[arg-type]

    controller._on_release(_EmployeeScreen(), str(POSTING))  # type: ignore[arg-type]

    assert len(calls) == 2, "qısa cavabdan sonra dialoq YENİDƏN açılmalıdır"
    assert market.releases == []


def test_a_rejected_release_shows_the_domain_message_and_does_not_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Paralel ləğv/geri buraxma — işçi SƏBƏBİ görür, kiosk çökmür."""
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(
        QInputDialog,
        "getMultiLineText",
        staticmethod(lambda *a, **k: ("Xəstələndim, həkim arayışı var", True)),
    )
    market = _OpenShifts(
        views=[],
        claimed_views=[_view()],
        write_failure=KompasOSError("not claimed", user_message="Bu növbə tutulmayıb."),
    )
    context = _Context(open_shifts=market)
    screen = _EmployeeScreen()
    controller = EmployeeOpenShiftController(context, _Actor())  # type: ignore[arg-type]

    controller._on_release(screen, str(POSTING))  # type: ignore[arg-type]

    assert market.releases == []
    assert all(not session.committed for session in context.sessions)
    assert screen.messages[-1] == "Bu növbə tutulmayıb."
