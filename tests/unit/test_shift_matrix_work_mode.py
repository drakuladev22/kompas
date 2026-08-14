"""Shift Matrix-in İŞ REJİMİ seçicisi — kompas1.md Faza 7, bənd 4.

Testlər İKİ təbəqəni ayrıca yoxlayır (`test_exception_screen.py` naxışı):

    * ekranın ÖZÜ (dropdown, siqnal, nişan) — Qt TƏLƏB EDİR;
    * kontroller (kataloqun oxunması, nasazlıqda çökməmə) — Qt TƏLƏB ETMİR,
      duck-typing sahtə ekranı ilə işləyir.

──────────────────────────────────────────────────────────────────────────────
ƏN VACİB TEST BURADA `test_apply_assignment_was_only_extended_never_rewritten`
──────────────────────────────────────────────────────────────────────────────
Faza 6/7 intizamı: `ShiftPlanningUseCase.apply_assignment` TOXUNULMAZDIR.
Dropdown ona bir sətir belə əlavə etmir və onu ÇAĞIRMIR — seçici yalnız
«hansı şablon seçilib» sualının cavabını verir.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Any, Final

import pytest

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.catalogs import WorkMode
from src.domain.value_objects.identifiers import EmployeeId, TenantId, WorkModeId
from src.domain.value_objects.scheduling import TimeRange
from src.presentation.controllers.shift_matrix import ShiftMatrixWorkModeController
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())
MORNING_ID: Final = WorkModeId(uuid.uuid4())
LONG_ID: Final = WorkModeId(uuid.uuid4())
NIGHT_ID: Final = WorkModeId(uuid.uuid4())
FREE_ID: Final = WorkModeId(uuid.uuid4())


def _actor() -> Any:
    return type("_Actor", (), {"id": EmployeeId(uuid.uuid4())})()


def _mode(
    name: str, schedule: TimeRange | None, mode_id: WorkModeId, *, is_active: bool = True
) -> WorkMode:
    return WorkMode(
        name=name,
        tenant_id=TENANT,
        work_mode_id=mode_id,
        schedule=schedule,
        is_active=is_active,
        deactivated_at=None if is_active else datetime(2026, 1, 1, tzinfo=UTC),
    )


_MODES: Final = [
    _mode("Səhər", TimeRange(start=time(9, 0), end=time(18, 0)), MORNING_ID),
    _mode("Uzun", TimeRange(start=time(8, 0), end=time(20, 0)), LONG_ID),
    _mode("Gecə", TimeRange(start=time(22, 0), end=time(6, 0)), NIGHT_ID),
    _mode("Növbəli 2/2", None, FREE_ID),
]


# --------------------------------------------------------------------------- #
# Ekran (Qt)
# --------------------------------------------------------------------------- #


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


@requires_qt
def test_the_matrix_toolbar_offers_a_work_mode_dropdown(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Faza 7-nin YEGANƏ boşluğu: statik etiket → seçici."""
    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)

    screen.set_work_modes([(str(MORNING_ID), "Səhər · 09:00–18:00")])

    assert screen.selected_work_mode_id() == str(MORNING_ID)


@requires_qt
def test_selecting_a_mode_emits_its_identifier_not_its_label(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Təyinetmə yolu ADLA deyil, `work_mode_id` ilə işləyir."""
    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)
    emitted: list[str] = []
    screen.work_mode_selected.connect(emitted.append)

    screen.set_work_modes([(str(MORNING_ID), "Səhər"), (str(NIGHT_ID), "Gecə")])
    emitted.clear()

    assert screen.select_work_mode(str(NIGHT_ID)) is True

    assert emitted == [str(NIGHT_ID)]
    assert screen.selected_work_mode_id() == str(NIGHT_ID)


@requires_qt
def test_selecting_a_mode_that_left_the_catalog_is_refused(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Sükutla BAŞQA rejimə düşmək növbəni yanlış saatla təyin etdirərdi."""
    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)
    screen.set_work_modes([(str(MORNING_ID), "Səhər"), (str(NIGHT_ID), "Gecə")])

    assert screen.select_work_mode(str(uuid.uuid4())) is False
    assert screen.selected_work_mode_id() == str(MORNING_ID)


@requires_qt
def test_populating_the_dropdown_emits_exactly_once(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """`addItem` hər dəfə siqnal doğurur — doldurma zamanı onlar bloklanır."""
    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)
    emitted: list[str] = []
    screen.work_mode_selected.connect(emitted.append)

    screen.set_work_modes([(str(MORNING_ID), "A"), (str(LONG_ID), "B"), (str(NIGHT_ID), "C")])

    assert emitted == [str(MORNING_ID)]


@requires_qt
def test_an_empty_catalog_leaves_the_selection_empty_without_crashing(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)
    emitted: list[str] = []
    screen.work_mode_selected.connect(emitted.append)

    screen.set_work_modes([])

    assert screen.selected_work_mode_id() == ""
    assert emitted == []


@requires_qt
def test_set_month_still_works_and_does_not_touch_the_dropdown(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """MÖVCUD imza dəyişməyib — maket yolu olduğu kimi işləyir."""
    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)
    screen.set_work_modes([(str(MORNING_ID), "Səhər")])

    screen.set_month("Avqust 2026", stores=["Bellona 28 May"], mode="5/2")

    assert screen.selected_work_mode_id() == str(MORNING_ID)


@requires_qt
def test_the_preview_path_fills_the_dropdown_too(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Boş dropdown maketdə «funksiya işləmir» kimi oxunardı (CLAUDE.md §6)."""
    from src.presentation import preview_screens
    from src.presentation.screens.group_c import ShiftPlanningScreen

    screen = ShiftPlanningScreen(theme)
    qtbot.addWidget(screen)

    preview_screens.populate("shift_planning", screen)

    assert screen.selected_work_mode_id() != ""


# --------------------------------------------------------------------------- #
# Kontroller (Qt tələb etmir)
# --------------------------------------------------------------------------- #


class _WorkModeCatalog:
    def __init__(self, modes: list[WorkMode], *, error: Exception | None = None) -> None:
        self._modes = modes
        self._error = error
        self.calls = 0

    def list_for_selection(self, tenant_id: TenantId) -> list[WorkMode]:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return list(self._modes)


class _Limits:
    def __init__(self, daily_norm: str | None = None) -> None:
        self._daily_norm = daily_norm

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
        if key == SystemLimitKey.OVERTIME_DAILY_NORM_HOURS.value and self._daily_norm is not None:
            return self._daily_norm
        return default


class _Session:
    def __init__(self, catalog: _WorkModeCatalog, limits: _Limits) -> None:
        self.tenant_id = TENANT
        self.work_modes = catalog
        self.limits = limits


class _Context:
    def __init__(self, session: _Session) -> None:
        self._session = session

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        yield self._session


class _Screen:
    """Duck-typing ekran — `ShiftPlanningScreen`-in yalnız işlənən hissəsi."""

    def __init__(self) -> None:
        self.modes: list[tuple[str, str]] | None = None
        self.norm_label = ""
        self.errors: list[tuple[str, str]] = []
        self.work_mode_selected = _Signal()

    def set_work_modes(self, modes: list[tuple[str, str]]) -> None:
        self.modes = modes

    def set_work_mode_norm(self, text: str) -> None:
        self.norm_label = text

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


class _Signal:
    def __init__(self) -> None:
        self._slots: list[Any] = []

    def connect(self, slot: Any) -> None:
        self._slots.append(slot)

    def emit(self, value: str) -> None:
        for slot in self._slots:
            slot(value)


def _controller(
    modes: list[WorkMode] | None = None,
    *,
    error: Exception | None = None,
    daily_norm: str | None = None,
) -> tuple[ShiftMatrixWorkModeController, _Screen, _WorkModeCatalog]:
    catalog = _WorkModeCatalog(_MODES if modes is None else modes, error=error)
    context = _Context(_Session(catalog, _Limits(daily_norm)))
    return (
        ShiftMatrixWorkModeController(context, _actor()),  # type: ignore[arg-type]
        _Screen(),
        catalog,
    )


def test_the_controller_fills_the_dropdown_from_the_live_catalog() -> None:
    controller, screen, catalog = _controller()

    controller.attach(screen)  # type: ignore[arg-type]

    assert catalog.calls == 1
    assert screen.modes is not None
    assert [mode_id for mode_id, _ in screen.modes] == [
        str(MORNING_ID),
        str(LONG_ID),
        str(NIGHT_ID),
        str(FREE_ID),
    ]
    assert "09:00–18:00" in screen.modes[0][1]


def test_the_norm_label_shows_the_derived_daily_hours() -> None:
    """Norma saat kataloqda SÜTUN deyil — `bitmə − başlanğıc`-dan çıxır."""
    controller, screen, _ = _controller()
    controller.attach(screen)  # type: ignore[arg-type]

    controller._on_selected(screen, str(MORNING_ID))  # type: ignore[arg-type]

    assert "norma 8.00 saat/gün" in screen.norm_label


def test_a_schedule_longer_than_the_legal_norm_says_so_out_loud() -> None:
    """12 saatlıq növbədə istifadəçi «saatlarım hara getdi?» sualı ilə qalmamalıdır."""
    controller, screen, _ = _controller()
    controller.attach(screen)  # type: ignore[arg-type]

    controller._on_selected(screen, str(LONG_ID))  # type: ignore[arg-type]

    assert "norma 8.00 saat/gün" in screen.norm_label
    assert "aşım jurnalında" in screen.norm_label


def test_an_overnight_mode_reports_its_full_duration() -> None:
    """22:00–06:00 → 8 saat; sadə çıxma MƏNFİ verərdi."""
    controller, screen, _ = _controller()
    controller.attach(screen)  # type: ignore[arg-type]

    controller._on_selected(screen, str(NIGHT_ID))  # type: ignore[arg-type]

    assert "norma 8.00 saat/gün" in screen.norm_label
    assert "aşım jurnalında" not in screen.norm_label


def test_a_mode_without_fixed_hours_is_labelled_as_a_free_shift() -> None:
    controller, screen, _ = _controller()
    controller.attach(screen)  # type: ignore[arg-type]

    controller._on_selected(screen, str(FREE_ID))  # type: ignore[arg-type]

    assert "sərbəst növbə" in screen.norm_label


def test_the_daily_norm_comes_from_root_and_not_from_a_second_key() -> None:
    """Root normanı 10-a qaldırsa, nişan da 10 göstərməlidir."""
    controller, screen, _ = _controller(daily_norm="10.00")
    controller.attach(screen)  # type: ignore[arg-type]

    controller._on_selected(screen, str(LONG_ID))  # type: ignore[arg-type]

    assert "norma 10.00 saat/gün" in screen.norm_label


def test_a_broken_root_value_falls_back_to_the_shared_default() -> None:
    controller, screen, _ = _controller(daily_norm="səkkiz")
    controller.attach(screen)  # type: ignore[arg-type]

    controller._on_selected(screen, str(MORNING_ID))  # type: ignore[arg-type]

    expected = Decimal(DEFAULT_LIMITS[SystemLimitKey.OVERTIME_DAILY_NORM_HOURS])
    assert f"norma {expected} saat/gün" in screen.norm_label


def test_the_selection_signal_is_wired_on_attach() -> None:
    controller, screen, _ = _controller()
    controller.attach(screen)  # type: ignore[arg-type]

    screen.work_mode_selected.emit(str(NIGHT_ID))

    assert "22:00–06:00" in screen.norm_label


def test_an_unknown_identifier_does_not_crash_the_toolbar() -> None:
    controller, screen, _ = _controller()
    controller.attach(screen)  # type: ignore[arg-type]

    screen.work_mode_selected.emit(str(uuid.uuid4()))

    assert screen.norm_label == "İş Rejimi: seçilməyib"


def test_a_catalog_failure_leaves_the_matrix_usable() -> None:
    """Növbə planlaması iş rejimi siyahısından daha vacibdir."""

    class _DeniedError(KompasOSError):
        user_message = "İş rejimlərini görmək səlahiyyətiniz yoxdur."

    controller, screen, _ = _controller(error=_DeniedError("qadağan"))
    controller.attach(screen)  # type: ignore[arg-type]

    assert screen.modes == []
    assert screen.norm_label == "İş Rejimi: seçilməyib"
    assert screen.errors and screen.errors[0][1] == "İş rejimlərini görmək səlahiyyətiniz yoxdur."


def test_an_unexpected_failure_is_swallowed_into_an_empty_dropdown() -> None:
    controller, screen, _ = _controller(error=RuntimeError("bağlantı qopdu"))
    controller.attach(screen)  # type: ignore[arg-type]

    assert screen.modes == []
    assert screen.errors == []


def test_a_mode_without_an_identifier_is_skipped() -> None:
    """Yaddaşdakı, hələ saxlanılmamış sətir dropdown-a düşməməlidir."""
    unsaved = WorkMode(name="Qaralama", tenant_id=TENANT, work_mode_id=None)
    controller, screen, _ = _controller([unsaved])
    controller.attach(screen)  # type: ignore[arg-type]

    assert screen.modes == []


def test_the_dropdown_reads_the_selection_list_not_the_management_list() -> None:
    """Soft delete: deaktiv rejim YENİ təyinatda görünməməlidir.

    Süzgəc BURADA təkrarlanmır — `list_for_selection()` onu ARTIQ edir
    (`catalog_management.py`). Bu test məhz həmin metodun çağırıldığını
    bağlayır; `list_for_management()` çağırılsaydı, deaktiv şablon dropdown-a
    düşərdi və keçmişdə oxunmaq üçün saxlanılan sətir yeni növbəyə təyin
    edilə bilərdi.
    """
    controller, screen, catalog = _controller()
    controller.attach(screen)  # type: ignore[arg-type]

    assert catalog.calls == 1
    assert not hasattr(catalog, "list_for_management")
    assert not _mode("Köhnə", None, FREE_ID, is_active=False).selectable


# --------------------------------------------------------------------------- #
# İNTİZAM QAPISI — `apply_assignment` toxunulmazdır
# --------------------------------------------------------------------------- #


def test_the_work_mode_selector_never_calls_the_shift_write_path() -> None:
    """Dropdown təyinetmə məntiqini YENİDƏN YAZMIR — onu ÇAĞIRMIR da.

    Mənbə mətnini oxuyuruq, çünki alternativ (davranış testi) yalnız
    ÇAĞIRILMADIĞINI göstərərdi; burada isə qorunan şey QƏRAR-dır: iş rejimi
    seçicisi Shift Matrix-in yazma nöqtəsindən TAMAMİLƏ ayrıdır.

    Şərhlərdəki adlar SAYILMIR (modul başlığı `apply_assignment`-a istinad
    EDİR və etməlidir) — yalnız ÇAĞIRIŞ forması axtarılır.
    """
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "presentation"
        / "controllers"
        / "shift_matrix.py"
    ).read_text(encoding="utf-8")

    for call in ("apply_assignment(", "assign_work_day(", "save_assignment(", "shift_planning"):
        assert call not in source, f"İş rejimi seçicisi növbə yazma yoluna toxunur: {call}"
