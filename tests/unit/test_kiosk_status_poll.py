"""DEEP-GAP UX-2 — kioskda «təsdiq gözlənilir» vəziyyəti ÖZÜ yenilənir.

──────────────────────────────────────────────────────────────────────────────
QÜSUR NƏ İDİ
──────────────────────────────────────────────────────────────────────────────
İşçi [İşə Başladım] basır, status 🟡 `PENDING_CHECK_IN` olur. Operator BAŞQA
maşında təsdiqləyir — kiosk ekranı isə DƏYİŞMİR, çünki `refresh()` yalnız
İŞÇİNİN öz əməliyyatından sonra çağırılırdı. İşçinin yeganə yolu çıxıb
yenidən PIN + üz qapısından keçmək idi.

Aşağıdakı testlər `app.py::_start_kiosk_status_poll`-un İKİ müqaviləsini
kilidləyir:

1. 🟡 vəziyyətdə sorğu GEDİR və status dəyişəndə ekran yenilənir;
2. yaşıl/mavi (`is_actionable`) vəziyyətdə sorğu ÜMUMİYYƏTLƏ getmir —
   40 terminal × 8 saat davamlı sorğu demək olardı.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.presentation.widgets.worker_status import WorkerStatus
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit


class _FakeHome:
    """`EmployeeHomeScreen`-in əvəzedicisi — taymerin SAHİBİ olacaq qədər Qt.

    `QTimer(home)` real `QObject` tələb edir, ona görə `QWidget`-dən törəyir;
    qalan hər şey (`set_status`) yalnız çağırışı yazır.
    """

    def __init__(self) -> None:
        self.statuses: list[WorkerStatus] = []

    def set_status(self, status: WorkerStatus, *, hint: str = "") -> None:
        self.statuses.append(status)


class _FakeController:
    def __init__(self, statuses: list[WorkerStatus]) -> None:
        self._statuses = statuses
        self.calls = 0

    def status_for(self, employee_id: Any) -> WorkerStatus:
        self.calls += 1
        return self._statuses[min(self.calls - 1, len(self._statuses) - 1)]


class _FakeEmployee:
    id = "employee-1"


def _application(qt_app: Any) -> Any:
    from src.presentation.app import KompasApplication
    from src.presentation.theme.tokens import ThemeMode

    return KompasApplication(qt_app, preview=False, theme_preference=ThemeMode.LIGHT, context=None)


def _stop_timers(owner: Any) -> None:
    """Testdən SONRA taymer DAYANDIRILIR — sızma başqa testi qırır.

    Taymerin intervalı 30 saniyədir və tam dəst ~38 dəqiqə işləyir: widget
    canlı qalsa, tıqqıltı SONRAKI testin ortasında baş verir və (uğursuz
    yolda) jurnala sətir yazır. `test_logger.py` isə jurnalda MƏHZ BİR sətir
    gözləyir — yəni sızma orada qırmızı verir və səbəbi bu faylda olur.
    Qt widget-i `deleteLater()` ilə silinsə də taymer hadisə dövrəsi işləyənə
    qədər yaşayır, ona görə AÇIQ `stop()` çağırılır.
    """
    from PySide6.QtCore import QTimer

    for timer in owner.findChildren(QTimer):
        timer.stop()


def _home(qt_app: Any) -> Any:
    from PySide6.QtWidgets import QWidget

    class _Home(QWidget, _FakeHome):  # type: ignore[misc]
        def __init__(self) -> None:
            QWidget.__init__(self)
            _FakeHome.__init__(self)

    return _Home()


@requires_qt
def test_a_pending_status_is_polled_and_the_screen_follows(qt_app) -> None:  # type: ignore[no-untyped-def]
    """🟡 → operator təsdiqləyir → ekran ÖZÜ 🟢 olur."""
    application = _application(qt_app)
    home = _home(qt_app)
    controller = _FakeController([WorkerStatus.VERIFIED])
    last_status = [WorkerStatus.PENDING_CHECK_IN]

    application._start_kiosk_status_poll(home, controller, _FakeEmployee(), last_status)
    # Taymerin ÖZ intervalını gözləmirik (30 san.) — dövrənin GÖVDƏSİ
    # birbaşa işə salınır. Ölçülən şey ritm deyil, DAVRANIŞdır.
    from PySide6.QtCore import QTimer

    timer = home.findChild(QTimer)
    assert timer is not None
    timer.timeout.emit()

    assert controller.calls == 1
    assert home.statuses == [WorkerStatus.VERIFIED]
    assert last_status[-1] is WorkerStatus.VERIFIED
    _stop_timers(home)


@requires_qt
def test_an_actionable_status_never_touches_the_database(qt_app) -> None:  # type: ignore[no-untyped-def]
    """🟢 «Mağazada» vəziyyətində növbəti dəyişikliyi İŞÇİNİN ÖZÜ edir.

    Sorğu göndərmək boş dayanan 40 terminaldan davamlı yük demək olardı.
    """
    from PySide6.QtCore import QTimer

    application = _application(qt_app)
    home = _home(qt_app)
    controller = _FakeController([WorkerStatus.OUTSIDE])
    last_status = [WorkerStatus.VERIFIED]

    application._start_kiosk_status_poll(home, controller, _FakeEmployee(), last_status)
    home.findChild(QTimer).timeout.emit()

    assert controller.calls == 0
    assert home.statuses == []
    _stop_timers(home)


@requires_qt
def test_an_unchanged_status_does_not_redraw_the_screen(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Operator hələ təsdiqləməyibsə ekran TOXUNULMUR — yanıb-sönmə olmaz."""
    from PySide6.QtCore import QTimer

    application = _application(qt_app)
    home = _home(qt_app)
    controller = _FakeController([WorkerStatus.PENDING_CHECK_IN])
    last_status = [WorkerStatus.PENDING_CHECK_IN]

    application._start_kiosk_status_poll(home, controller, _FakeEmployee(), last_status)
    home.findChild(QTimer).timeout.emit()

    assert controller.calls == 1
    assert home.statuses == []
    _stop_timers(home)


@requires_qt
def test_a_failing_query_keeps_the_timer_alive(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Ötəri şəbəkə xətası dövrəni DAYANDIRMIR — növbəti tıqqıltı cəhd edir."""
    from PySide6.QtCore import QTimer

    application = _application(qt_app)
    home = _home(qt_app)

    class _Broken(_FakeController):
        def status_for(self, employee_id: Any) -> WorkerStatus:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("connection lost")
            return WorkerStatus.VERIFIED

    controller = _Broken([WorkerStatus.VERIFIED])
    last_status = [WorkerStatus.PENDING_CHECK_IN]

    application._start_kiosk_status_poll(home, controller, _FakeEmployee(), last_status)
    timer = home.findChild(QTimer)
    timer.timeout.emit()
    assert home.statuses == []

    timer.timeout.emit()
    assert home.statuses == [WorkerStatus.VERIFIED]
    _stop_timers(home)
