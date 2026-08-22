"""DEEP-GAP U5 (əlavə) — PIN ekranının mağaza adı və saatı SABİT DEYİL.

──────────────────────────────────────────────────────────────────────────────
HANSI QÜSURU TUTUR
──────────────────────────────────────────────────────────────────────────────
`app.py::start_kiosk` `PinPadScreen(store_name="Bellona — 28 May", ...)` və
`pin_pad.set_clock("09:42 · 12 Avqust 2026")` ilə TAM SABİT mətn göstərirdi —
taymer yox idi, `_build_kiosk_controller`-in artıq bildiyi `store_id` heç
yerdə oxunmurdu. Kiosk PIN ekranı hər işçinin gündə 3-4 dəfə gördüyü BİRİNCİ
ekrandır və üzərində sistemin ən əsas iddiası — VAXT — dayanır (bütün
cərimə/gecikmə mexanizmi server-lövbərli vaxta əsaslanır, TIME-1).

Bu fayl `KompasApplication.start_kiosk()`-u REAL `context` ilə çağırır və
PIN ekranının HƏQİQİ widget mətnini (`pin_pad._store`, `pin_pad._clock`)
yoxlayır — `test_kiosk_setup_visibility.py`-dəki EYNİ naxışla (`pin_pad.
_message.text()`-ə birbaşa giriş).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

STORE_ID = uuid.uuid4()
STORE_NAME = "Bellona — 28 May"
#: `to_baku`-nun sabit UTC+4 sürüşməsi ilə asanlıqla yoxlanan an.
MOMENT = datetime(2026, 8, 17, 5, 30, tzinfo=UTC)


class _Row(dict):  # type: ignore[type-arg]
    pass


class _Cursor:
    def __init__(self, row: Any) -> None:
        self._row = row

    def fetchone(self) -> Any:
        return self._row


class _Connection:
    """`camera_queue._store_name`-in gözlədiyi XAM SQL interfeysi."""

    def __init__(self, *, row: Any) -> None:
        self._row = row
        self.calls: list[Any] = []

    def execute(self, query: str, params: Any) -> _Cursor:
        self.calls.append((query, params))
        return _Cursor(self._row)


class _Uow:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection


class _Session:
    def __init__(self, connection: _Connection) -> None:
        self.tenant_id = uuid.uuid4()
        self.uow = _Uow(connection)


class _Clock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class _Status:
    def __init__(self, *, approximate: bool) -> None:
        self.is_approximate = approximate


class _Context:
    """`KompasApplication._context`-in `_kiosk_store_name`/`_start_pin_pad_clock`
    üçün gözlədiyi minimal səth."""

    def __init__(
        self,
        *,
        row: Any,
        moment: datetime = MOMENT,
        approximate: bool = False,
        session_fails: bool = False,
    ) -> None:
        self._connection = _Connection(row=row)
        self.clock = _Clock(moment)
        self._approximate = approximate
        self._session_fails = session_fails

    def time_integrity_status(self) -> _Status:
        return _Status(approximate=self._approximate)

    @contextmanager
    def session(self, *, user_id: Any = None):  # type: ignore[no-untyped-def]
        if self._session_fails:
            raise RuntimeError("baza əlçatan deyil")
        yield _Session(self._connection)


def _build_controller(context: Any) -> Any:
    from src.domain.value_objects.identifiers import StoreId
    from src.domain.value_objects.machine_identity import MachineIdentityHash
    from src.presentation.controllers.kiosk import KioskController

    return KioskController(
        context,
        store_id=StoreId(STORE_ID),
        machine_key=MachineIdentityHash(digest="a" * 64),
    )


@requires_qt
def test_start_kiosk_shows_the_terminals_actual_store_name_and_a_ticking_clock(  # type: ignore[no-untyped-def]
    qt_app,
) -> None:
    """ƏVVƏL: "Bellona — 28 May" SABİT sətir idi — İNDİ: `store_id`-dən oxunur."""
    from src.presentation.app import KompasApplication
    from src.presentation.controllers.kiosk import KioskController  # noqa: F401
    from src.presentation.screens.group_a_kiosk import PinPadScreen
    from src.presentation.theme.tokens import ThemeMode

    context = _Context(row=_Row(name=STORE_NAME))
    application = KompasApplication(
        qt_app, preview=False, theme_preference=ThemeMode.LIGHT, context=context
    )
    application.set_kiosk_controller(_build_controller(context))

    kiosk = application.start_kiosk()
    pin_pad = kiosk.findChild(PinPadScreen)

    assert pin_pad is not None
    assert pin_pad._store.text() == STORE_NAME  # type: ignore[attr-defined]
    # `to_baku(2026-08-17 05:30 UTC)` == `2026-08-17 09:30` (Bakı UTC+4).
    assert pin_pad._clock.text() == "09:30 · 17 Avqust 2026"  # type: ignore[attr-defined]


@requires_qt
def test_start_kiosk_marks_the_clock_when_time_is_approximate(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Vaxt server ilə TƏSDİQLƏNMƏYİBSƏ saat `~` işarəsi daşıyır (TIME-1)."""
    from src.presentation.app import KompasApplication
    from src.presentation.screens.group_a_kiosk import PinPadScreen
    from src.presentation.theme.tokens import ThemeMode
    from src.presentation.widgets.live_clock import APPROXIMATE_MARK

    context = _Context(row=_Row(name=STORE_NAME), approximate=True)
    application = KompasApplication(
        qt_app, preview=False, theme_preference=ThemeMode.LIGHT, context=context
    )
    application.set_kiosk_controller(_build_controller(context))

    kiosk = application.start_kiosk()
    pin_pad = kiosk.findChild(PinPadScreen)

    assert pin_pad is not None
    assert pin_pad._clock.text().startswith(APPROXIMATE_MARK)  # type: ignore[attr-defined]


@requires_qt
def test_start_kiosk_falls_back_to_a_generic_store_name_when_the_lookup_fails(  # type: ignore[no-untyped-def]
    qt_app,
) -> None:
    """Mağaza adı sorğusu sınırsa kiosk ÇÖKMÜR — generic ad göstərilir."""
    from src.presentation.app import KompasApplication
    from src.presentation.screens.group_a_kiosk import PinPadScreen
    from src.presentation.theme.tokens import ThemeMode

    context = _Context(row=_Row(name=STORE_NAME), session_fails=True)
    application = KompasApplication(
        qt_app, preview=False, theme_preference=ThemeMode.LIGHT, context=context
    )
    application.set_kiosk_controller(_build_controller(context))

    kiosk = application.start_kiosk()
    pin_pad = kiosk.findChild(PinPadScreen)

    assert pin_pad is not None
    assert pin_pad._store.text() == "KompasOS Kiosk"  # type: ignore[attr-defined]
    # Saat İSƏ ayrı yoldur (mağaza sorğusundan asılı deyil) — çökmür.
    assert pin_pad._clock.text() != ""  # type: ignore[attr-defined]


@requires_qt
def test_start_kiosk_without_a_context_shows_no_live_clock(qt_app) -> None:  # type: ignore[no-untyped-def]
    """`context is None` (nəzəri hal) — taymer QURULMUR, kiosk yenə açılır.

    `LiveClock`-un "mənbəsiz taymer başlamır" qaydası ilə eynidir: yanlış
    saat göstərməkdənsə heç nə göstərməmək doğrudur.
    """
    from src.presentation.app import KompasApplication
    from src.presentation.screens.group_a_kiosk import PinPadScreen
    from src.presentation.theme.tokens import ThemeMode

    application = KompasApplication(
        qt_app, preview=False, theme_preference=ThemeMode.LIGHT, context=None
    )

    kiosk = application.start_kiosk()
    pin_pad = kiosk.findChild(PinPadScreen)

    assert pin_pad is not None
    assert pin_pad._store.text() == "KompasOS Kiosk"  # type: ignore[attr-defined]
    assert pin_pad._clock.text() == ""  # type: ignore[attr-defined]


@requires_qt
def test_start_kiosk_keeps_the_clock_readable_when_the_source_breaks(qt_app) -> None:  # type: ignore[no-untyped-def]
    """`clock.now()` istisna atırsa saat DONMUŞ (köhnə) mətnini SAXLAYIR.

    Boşaltmaq PIN ekranında "saat sındı" YOX, sadəcə boş sətir kimi
    oxunardı — işçi fərqinə varmazdı (bax `_start_pin_pad_clock` şərhi).
    """
    from src.presentation.app import KompasApplication
    from src.presentation.screens.group_a_kiosk import PinPadScreen
    from src.presentation.theme.tokens import ThemeMode

    class _BrokenClock:
        def now(self) -> datetime:
            raise RuntimeError("server ilə əlaqə yoxdur")

    context = _Context(row=_Row(name=STORE_NAME))
    context.clock = _BrokenClock()  # type: ignore[assignment]
    application = KompasApplication(
        qt_app, preview=False, theme_preference=ThemeMode.LIGHT, context=context
    )
    application.set_kiosk_controller(_build_controller(context))

    kiosk = application.start_kiosk()
    pin_pad = kiosk.findChild(PinPadScreen)

    assert pin_pad is not None
    # İLK tik uğursuz olub — başlanğıc dəyər (boş) qalır, ÇÖKMÜR.
    assert pin_pad._clock.text() == ""  # type: ignore[attr-defined]
