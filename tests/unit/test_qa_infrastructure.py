"""QA-FULL ölçmə infrastrukturunun ÖZ testləri.

──────────────────────────────────────────────────────────────────────────────
NİYƏ ALƏTİN ÖZÜ TEST OLUNUR
──────────────────────────────────────────────────────────────────────────────
Bu fazanın bütün nəticələri — «donma var/yoxdur», «N+1 var/yoxdur», «yaddaş
sızır/sızmır» — bu alətlərin ÇIXIŞINA söykənəcək. Alət səhv ölçürsə, hesabat
da səhv olar və bunu heç nə göstərməz: yaşıl nəticə həm «problem yoxdur»,
həm də «alət işləmir» deməkdir. Ona görə hər ölçünün HƏM müsbət, HƏM mənfi
halı yoxlanılır — yalnız «aşkarlayır» deyil, «yalançı həyəcan vermir» də.
"""

from __future__ import annotations

import enum
import time
from typing import Any

import pytest

from tests.fixtures.qa_harness import (
    StatementRecorder,
    Timings,
    grows_monotonically,
    memory_growth,
)

pytestmark = pytest.mark.unit

requires_qt = pytest.mark.qt


# --------------------------------------------------------------------------- #
# 1 — Donma aşkarlanması
# --------------------------------------------------------------------------- #


def test_the_threshold_falls_back_when_the_environment_value_is_broken() -> None:
    """Səhv diaqnostika açarı tətbiqi işə salmamaq üçün səbəb DEYİL."""
    from src.presentation.stall_monitor import (
        DEFAULT_STALL_THRESHOLD_MS,
        STALL_ENV_KEY,
        stall_threshold_ms,
    )

    assert stall_threshold_ms({}) == DEFAULT_STALL_THRESHOLD_MS
    assert stall_threshold_ms({STALL_ENV_KEY: "abc"}) == DEFAULT_STALL_THRESHOLD_MS
    assert stall_threshold_ms({STALL_ENV_KEY: "0"}) == DEFAULT_STALL_THRESHOLD_MS
    assert stall_threshold_ms({STALL_ENV_KEY: "-5"}) == DEFAULT_STALL_THRESHOLD_MS
    assert stall_threshold_ms({STALL_ENV_KEY: " 250 "}) == 250


@requires_qt
def test_a_late_timer_is_measured_as_a_stall(qt_app: Any) -> None:
    """Saat SÜNİDİR — ölçü məntiqinin özü yoxlanılır, sürət yox.

    Real gözləmə ilə yoxlamaq testi mühitdən asılı edərdi (yüklü CI-da hər
    taymer gecikir). Burada saat verilir, yəni «7.3 saniyə gecikmiş taymer»
    ssenarisi DƏQİQ təkrarlanır.
    """
    from src.presentation.stall_monitor import StallMonitor

    ticks = iter([0.0, 0.5, 7.8, 8.3])
    monitor = StallMonitor(threshold_ms=1000, interval_ms=500, clock=lambda: next(ticks))
    seen: list[int] = []
    monitor.stalled.connect(seen.append)

    monitor._tick()  # 0.0 → 0.5: gecikmə yoxdur
    monitor._tick()  # 0.5 → 7.8: 7300 ms, gözlənilən 500 → donma 6800 ms
    monitor._tick()  # 7.8 → 8.3: yenidən normal

    assert seen == [6800], "donma ölçüsü gözlənilən gecikmə deyil"
    assert monitor.count == 1
    assert monitor.worst_ms == 6800


@requires_qt
def test_a_real_blocking_call_is_detected(qt_app: Any) -> None:
    """SÜNİ SAAT YOX — əsas sap HƏQİQƏTƏN bloklanır və monitor onu tutur.

    Yuxarıdakı test məntiqi yoxlayır, bu isə MEXANİZMİ: `QTimer`-in həqiqətən
    hadisə dövrəsindən asılı olduğunu və blokdan sonra gecikmiş işə
    düşdüyünü. İkisindən yalnız biri olsaydı, alət «işləyir» görünüb real
    donmanı buraxa bilərdi.

    Hədd 150 ms-dir və blok 700 ms — aralıq QƏSDƏN genişdir ki, yüklü
    maşında test qeyri-sabit olmasın.
    """
    from PySide6.QtCore import QTimer

    from src.presentation.stall_monitor import StallMonitor

    monitor = StallMonitor(threshold_ms=150, interval_ms=50)
    seen: list[int] = []
    monitor.stalled.connect(seen.append)
    monitor.start()

    # Bloku hadisə dövrəsinin İÇİNDƏN çağırırıq — real donmanın forması budur.
    QTimer.singleShot(0, lambda: time.sleep(0.7))
    QTimer.singleShot(900, qt_app.quit)
    qt_app.exec()
    monitor.stop()

    assert seen, "700 ms-lik real blok aşkarlanmadı — mexanizm işləmir"
    assert max(seen) >= 400, f"ölçülən gecikmə həqiqətdən çox kiçikdir: {seen}"


@requires_qt
def test_a_responsive_event_loop_reports_nothing(qt_app: Any) -> None:
    """YALANÇI HƏYƏCAN QAPISI: bloksuz dövrədə heç nə yazılmır.

    Bu olmasaydı monitor hər açılışda jurnalı doldurar və `MAIN_THREAD_STALL`
    yazısı mənasını itirərdi — «hər zaman var» olan xəbərdarlıq yoxdur
    deməkdir.
    """
    from PySide6.QtCore import QTimer

    from src.presentation.stall_monitor import StallMonitor

    monitor = StallMonitor(threshold_ms=150, interval_ms=50)
    seen: list[int] = []
    monitor.stalled.connect(seen.append)
    monitor.start()

    QTimer.singleShot(600, qt_app.quit)
    qt_app.exec()
    monitor.stop()

    assert seen == [], f"bloksuz dövrədə donma bildirildi: {seen}"


# --------------------------------------------------------------------------- #
# 2 — Sorğu sayğacı (N+1)
# --------------------------------------------------------------------------- #


def test_the_recorder_normalises_whitespace_so_the_same_query_matches() -> None:
    """Çoxsətirli SQL bir sətrə yığılır — əks halda N+1 naxışı görünməzdi."""
    recorder = StatementRecorder()
    recorder.execute("SELECT *\n  FROM   employees\n WHERE id = %s", (1,))
    recorder.execute("SELECT * FROM employees WHERE id = %s", (2,))

    assert recorder.statements[0] == recorder.statements[1]
    assert recorder.count == 2


def test_repeated_queries_are_reported_as_an_n_plus_one_signature() -> None:
    """Eyni SQL dövrədə üç dəfə = N+1 imzası; parametr fərqi ƏHƏMİYYƏTSİZDİR."""
    recorder = StatementRecorder()
    for employee_id in range(4):
        recorder.execute("SELECT name FROM employees WHERE id = %s", (employee_id,))
    recorder.execute("SELECT count(*) FROM stores")

    repeated = recorder.repeated(minimum=3)
    assert list(repeated.values()) == [4]
    assert "employees" in next(iter(repeated))
    assert recorder.repeated(minimum=5) == {}, "hədd nəzərə alınmır"


def test_the_budget_names_the_statements_it_rejected() -> None:
    """Büdcə pozulanda mesaj SORĞULARI göstərir — yalnız rəqəm faydasızdır."""
    recorder = StatementRecorder()

    with pytest.raises(AssertionError) as excinfo, recorder.budget(1, label="ekran açılışı"):
        recorder.execute("SELECT 1")
        recorder.execute("SELECT 2")

    message = str(excinfo.value)
    assert "ekran açılışı" in message
    assert "2 sorğu" in message
    assert "SELECT 2" in message


def test_the_budget_passes_when_the_limit_is_respected() -> None:
    recorder = StatementRecorder()
    with recorder.budget(2):
        recorder.execute("SELECT 1")
        recorder.execute("SELECT 2")
    assert recorder.count == 2


# --------------------------------------------------------------------------- #
# 3 — Vaxt
# --------------------------------------------------------------------------- #


def test_timings_rank_the_slowest_operation_first() -> None:
    """Sıralama ƏN SÜRƏTLİ nümunəyə görədir (bax `Timings.best` şərhi)."""
    timings = Timings()
    timings.samples["sürətli"] = [1.0, 9.0]
    timings.samples["yavaş"] = [50.0, 55.0]
    timings.samples["orta"] = [10.0]

    assert [label for label, _ in timings.slowest()] == ["yavaş", "orta", "sürətli"]
    assert timings.best("sürətli") == 1.0
    assert "yavaş" in timings.table(limit=1)
    assert "orta" not in timings.table(limit=1)


def test_measure_records_even_when_the_block_raises() -> None:
    """İSTİSNA YOLU DA ÖLÇÜLÜR — ən yavaş əməliyyat çox vaxt uğursuz olandır."""
    timings = Timings()
    with pytest.raises(ValueError, match="sınaq"), timings.measure("uğursuz"):
        raise ValueError("sınaq")

    assert "uğursuz" in timings.samples


def test_call_returns_the_value_of_the_action() -> None:
    timings = Timings()
    assert timings.call("iş", lambda: 42) == 42
    assert timings.samples["iş"]


# --------------------------------------------------------------------------- #
# 4 — Yaddaş
# --------------------------------------------------------------------------- #


def test_a_leaking_action_grows_monotonically() -> None:
    """Sızma SİMULYASİYASI: siyahı böyüməyə davam edir."""
    leaked: list[bytes] = []

    def _leak() -> None:
        leaked.append(b"x" * 200_000)

    readings = memory_growth(_leak, cycles=6)
    assert grows_monotonically(readings), f"sızma aşkarlanmadı: {readings}"


def test_a_clean_action_does_not_report_a_leak() -> None:
    """YALANÇI HƏYƏCAN QAPISI: müvəqqəti obyekt sızma sayılmır."""

    def _clean() -> None:
        _ = [b"x" * 200_000]

    readings = memory_growth(_clean, cycles=6)
    assert not grows_monotonically(readings), f"təmiz iş sızma kimi göstərildi: {readings}"


def test_a_short_series_is_never_called_a_leak() -> None:
    """İki ölçü sızma haqqında heç nə demir — naxış üçün üç lazımdır."""
    assert not grows_monotonically([1, 1_000_000])


# --------------------------------------------------------------------------- #
# 5 — Tutulmamış istisna İSTİFADƏÇİYƏ deyilir
# --------------------------------------------------------------------------- #


def test_the_crash_notice_is_shown_once_not_on_every_repeat() -> None:
    """Təkrarlanan qüsur onlarla dialoq açsaydı, bildiriş özü nasazlıq olardı."""
    from src.presentation.app import KompasApplication

    application = object.__new__(KompasApplication)
    application._crash_notified = False
    shown: list[str] = []

    class _Box:
        # Həqiqi `QMessageBox.Icon` enum-u sinif ATRİBUTUDUR və çağıran ona
        # sinif üzərindən müraciət edir — sahtədə də elə olmalıdır.
        Icon = enum.Enum("Icon", ["Warning"])

        def __init__(self, _parent: object) -> None:
            self.text = ""

        def setIcon(self, _icon: object) -> None: ...  # noqa: N802

        def setWindowTitle(self, _title: str) -> None: ...  # noqa: N802

        def setText(self, text: str) -> None:  # noqa: N802
            self.text = text

        def setDetailedText(self, _text: str) -> None: ...  # noqa: N802

        def exec(self) -> None:
            shown.append(self.text)

    from PySide6 import QtWidgets

    original = QtWidgets.QMessageBox
    QtWidgets.QMessageBox = _Box  # type: ignore[misc, assignment]
    try:
        application._window = None
        for _ in range(3):
            application.notify_unhandled_error(NameError, NameError("Employee"))
    finally:
        QtWidgets.QMessageBox = original  # type: ignore[misc]

    assert len(shown) == 1, "hər təkrarda dialoq açıldı"
    # Mətn TEXNİKİ DEYİL: istifadəçi `NameError` sözündən heç nə anlamır.
    assert "NameError" not in shown[0]
    assert "dəstəyə müraciət" in shown[0]
