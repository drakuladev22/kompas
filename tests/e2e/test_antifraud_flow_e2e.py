"""Anti-fraud axınının interfeys tərəfi — Faza 4.2.

`test_qt_scaffolding.py`-dakı Faza 4 yer tutucularının təqdimat qatına aid
hissəsi burada gerçəkləşdirilir:

    * PIN handshake → İşçi Ana Ekranı (kiosk axını)
    * Dual-Control eskalasiyası — 30+ dəqiqəlik manual override

──────────────────────────────────────────────────────────────────────────────
ƏHATƏ SƏRHƏDİ
──────────────────────────────────────────────────────────────────────────────
Bu testlər İNTERFEYS qaydalarını yoxlayır: hansı ekran açılır, hansı
xəbərdarlıq görünür, hansı düymə bloklanır. Cərimənin FAKTİKİ hesablanması və
1C sinxronizasiyası Faza 5-də (repository + use-case qoşulduqda) əlavə olunur
— o vaxta qədər həmin addımlar `test_qt_scaffolding.py`-da yer tutucu olaraq
qalır.
"""

from __future__ import annotations

import pytest

from tests.conftest import requires_qt

pytestmark = [pytest.mark.e2e, pytest.mark.qt]


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


# --------------------------------------------------------------------------- #
# PIN handshake (STEP 1)
# --------------------------------------------------------------------------- #


@requires_qt
def test_pin_entry_emits_code_after_four_digits(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_a_kiosk import PIN_LENGTH, PinPadScreen

    screen = PinPadScreen(theme, store_name="Bellona — 28 May", terminal_name="Kiosk Terminal 01")
    qtbot.addWidget(screen)

    with qtbot.waitSignal(screen.submitted, timeout=1000) as blocker:
        for digit in "1234":
            screen._on_key(digit)

    assert blocker.args == ["1234"]
    assert PIN_LENGTH == 4


@requires_qt
def test_pin_is_not_submitted_before_completion(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Natamam PIN göndərilməməlidir — hər rəqəm sorğu yaratsaydı, kilidlənmə
    sayğacı dərhal dolardı."""
    from src.presentation.screens.group_a_kiosk import PinPadScreen

    screen = PinPadScreen(theme, store_name="Bellona", terminal_name="Kiosk-01")
    qtbot.addWidget(screen)

    received: list[str] = []
    screen.submitted.connect(received.append)

    for digit in "123":
        screen._on_key(digit)

    assert received == []


@requires_qt
def test_wrong_pin_shows_remaining_attempts(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_a_kiosk import PinPadScreen

    screen = PinPadScreen(theme, store_name="Bellona", terminal_name="Kiosk-01")
    qtbot.addWidget(screen)

    screen.show_attempt_error(remaining=2)
    assert not screen.is_locked, "Cəhd qalıbsa terminal bloklanmamalıdır"


@requires_qt
def test_lockout_disables_the_keypad(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Bloklanmış terminalda rəqəm basmaq heç nə etməməlidir."""
    from src.presentation.screens.group_a_kiosk import PinPadScreen

    screen = PinPadScreen(theme, store_name="Bellona", terminal_name="Kiosk-01")
    qtbot.addWidget(screen)

    received: list[str] = []
    screen.submitted.connect(received.append)

    screen.show_lockout()
    assert screen.is_locked
    for digit in "1234":
        screen._on_key(digit)

    assert received == [], "Blok zamanı PIN göndərilməməlidir"

    screen.clear_lockout()
    assert not screen.is_locked


@requires_qt
def test_kiosk_routes_from_pin_to_employee_home(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """STEP 1 → İşçi Ana Ekranı: kiosk pəncərəsi məzmunu dəyişir."""
    from src.presentation.app import KompasApplication
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen, PinPadScreen
    from src.presentation.theme.tokens import ThemeMode

    application = KompasApplication(qt_app, preview=True, theme_preference=ThemeMode.LIGHT)
    kiosk = application.start_kiosk()
    qtbot.addWidget(kiosk)

    pin_pad = kiosk.findChild(PinPadScreen)
    assert pin_pad is not None
    assert kiosk.findChild(EmployeeHomeScreen) is None

    for digit in "1234":
        pin_pad._on_key(digit)

    assert kiosk.findChild(EmployeeHomeScreen) is not None


@requires_qt
def test_employee_home_shows_single_action_per_status(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Spesifikasiya: statusa uyğun TƏK düymə."""
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen
    from src.presentation.widgets.worker_status import WorkerStatus

    screen = EmployeeHomeScreen(
        theme,
        full_name="Aysel Quliyeva",
        position_name="Satış Məsləhətçisi",
        store_name="Bellona 28 May",
    )
    qtbot.addWidget(screen)

    screen.set_status(WorkerStatus.NOT_STARTED)
    assert screen.status is WorkerStatus.NOT_STARTED

    # Təsdiq gözlənilən vəziyyətdə düymə basıla BİLMƏMƏLİDİR.
    screen.set_status(WorkerStatus.PENDING_CHECK_IN)
    assert not screen._action.isEnabled()

    screen.set_status(WorkerStatus.OUTSIDE)
    assert screen._action.isEnabled()


# --------------------------------------------------------------------------- #
# Dual-Control eskalasiyası (STEP 2)
# --------------------------------------------------------------------------- #


@requires_qt
def test_small_time_override_does_not_require_dual_control(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QTime

    from src.presentation.screens.group_b import ManualTimeOverrideDialog

    dialog = ManualTimeOverrideDialog(
        theme,
        employee_name="Aysel Quliyeva",
        store_name="Bellona 28 May",
        kind="Giriş Təsdiqi",
        system_time="09:42",
    )
    qtbot.addWidget(dialog)

    dialog._time_edit.setTime(QTime(9, 30))
    assert dialog.difference_minutes() == 12
    assert not dialog.requires_dual_control


@requires_qt
def test_large_time_override_escalates_to_dual_control(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Maketdəki ssenari: 09:42 → 09:05 = 37 dəqiqə (30-dan çox)."""
    from PySide6.QtCore import QTime

    from src.presentation.screens.group_b import (
        DUAL_CONTROL_THRESHOLD_MINUTES,
        ManualTimeOverrideDialog,
    )

    dialog = ManualTimeOverrideDialog(
        theme,
        employee_name="Aysel Quliyeva",
        store_name="Bellona 28 May",
        kind="Giriş Təsdiqi",
        system_time="09:42",
    )
    qtbot.addWidget(dialog)

    dialog._time_edit.setTime(QTime(9, 5))

    assert dialog.difference_minutes() == 37
    assert dialog.difference_minutes() > DUAL_CONTROL_THRESHOLD_MINUTES
    assert dialog.requires_dual_control


@requires_qt
def test_override_requires_a_reason(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Səbəb audit jurnalına yazılır — boş göndərilə bilməz."""
    from src.presentation.screens.group_b import ManualTimeOverrideDialog

    dialog = ManualTimeOverrideDialog(
        theme,
        employee_name="Aysel Quliyeva",
        store_name="Bellona 28 May",
        kind="Giriş Təsdiqi",
        system_time="09:42",
    )
    qtbot.addWidget(dialog)

    received: list[tuple[str, str]] = []
    dialog.submitted.connect(lambda time_text, reason: received.append((time_text, reason)))

    dialog._on_submit()
    assert received == [], "Səbəbsiz düzəliş göndərilməməlidir"

    dialog._reason.setPlainText("Kiosk terminalı işə düşməmişdi.")
    dialog._on_submit()
    assert len(received) == 1
    assert received[0][1] == "Kiosk terminalı işə düşməmişdi."


# --------------------------------------------------------------------------- #
# Cərimə qeydiyyatı (STEP 3-ün interfeys şərti)
# --------------------------------------------------------------------------- #


@requires_qt
def test_fine_cannot_be_recorded_without_photo_evidence(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Foto sübutu MƏCBURİDİR — sübutsuz cərimə etirazda müdafiə oluna bilməz."""
    from src.presentation.screens.group_b import FineEntryScreen

    screen = FineEntryScreen(
        theme,
        fine_types=["Gecikmə"],
        stores=["Bellona 28 May"],
        employees=["Nigar Səfərova"],
    )
    qtbot.addWidget(screen)

    submitted: list[dict[str, str]] = []
    screen.submitted.connect(submitted.append)

    screen._on_submit()
    assert submitted == []

    screen._photo.set_file("C:/tmp/subut.png")
    screen._on_submit()
    assert len(submitted) == 1
    assert submitted[0]["photo_path"].endswith("subut.png")
