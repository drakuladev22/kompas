"""Dizayn sistemi — tokenlər, QSS və ikonlar — Faza 4.2.

Bu testlər PySide6-SIZ işləyən hissələri yoxlayır (token bütövlüyü, QSS
şablonu, statusun xəritələnməsi). Widget davranışı `tests/e2e`-dədir, çünki
orada `QApplication` lazımdır.
"""

from __future__ import annotations

import pytest

from src.presentation.theme.qss import QSS_TEMPLATE, StyleSheetError, build_stylesheet, render
from src.presentation.theme.tokens import (
    DARK_THEME,
    LIGHT_THEME,
    METRICS,
    TYPOGRAPHY,
    ThemeMode,
    theme_tokens,
)

# --------------------------------------------------------------------------- #
# Tokenlər
# --------------------------------------------------------------------------- #


def test_themes_have_identical_keys() -> None:
    """Bir temada unudulan token digərində boş QSS sətri yaradar."""
    assert set(LIGHT_THEME) == set(DARK_THEME)


def test_every_colour_token_is_a_hex_string() -> None:
    """`check_contrast.py` yalnız hex gözləyir — hesablanmış dəyər onu qırar."""
    for theme in (LIGHT_THEME, DARK_THEME):
        for name, value in theme.items():
            assert value.startswith("#"), f"{name} hex deyil: {value!r}"
            assert len(value) in {4, 7, 9}, f"{name} yararsız hex: {value!r}"


def test_theme_tokens_includes_metrics_and_typography() -> None:
    tokens = theme_tokens(ThemeMode.LIGHT)
    assert set(METRICS) <= set(tokens)
    assert set(TYPOGRAPHY) <= set(tokens)
    assert set(LIGHT_THEME) <= set(tokens)


def test_system_mode_is_rejected() -> None:
    """`SYSTEM` palitra deyil — əvvəlcə həll olunmalıdır."""
    with pytest.raises(ValueError, match="SYSTEM"):
        theme_tokens(ThemeMode.SYSTEM)


@pytest.mark.parametrize(
    "token",
    [
        "--color-titlebar-bg",
        "--color-sidebar-bg",
        "--color-nav-active-bg",
        "--color-content-bg",
        "--color-card-bg",
        "--color-action-bg",
        "--color-text-muted",
        "--color-success-bg",
    ],
)
def test_shell_tokens_present_in_both_themes(token: str) -> None:
    """Maketdən gələn örtük tokenləri hər iki temada olmalıdır."""
    assert token in LIGHT_THEME
    assert token in DARK_THEME


def test_action_colour_differs_between_themes() -> None:
    """Maket: işıqlı rejimdə Navy, tünddə Amber — eyni olsalar səhv olardı."""
    assert LIGHT_THEME["--color-action-bg"] != DARK_THEME["--color-action-bg"]


# --------------------------------------------------------------------------- #
# QSS
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("mode", [ThemeMode.LIGHT, ThemeMode.DARK])
def test_stylesheet_builds_for_both_themes(mode: ThemeMode) -> None:
    stylesheet = build_stylesheet(theme_tokens(mode))
    assert stylesheet
    assert "{{" not in stylesheet, "Yerinə qoyulmamış token qalıb"


def test_unknown_token_raises() -> None:
    """Səhv yazılmış token SƏSSİZ keçməməlidir."""
    with pytest.raises(StyleSheetError, match="--color-yoxdur"):
        render("QWidget { color: {{--color-yoxdur}}; }", theme_tokens(ThemeMode.LIGHT))


def test_size_tokens_get_px_suffix() -> None:
    result = render("a { padding: {{--space-md}}; }", theme_tokens(ThemeMode.LIGHT))
    assert "16px" in result


def test_alpha_hex_becomes_rgba() -> None:
    """Qt QSS 8-rəqəmli hex-i anlamır."""
    result = render("a { background: {{--color-overlay}}; }", theme_tokens(ThemeMode.DARK))
    assert result.strip().startswith("a { background: rgba(")


def test_template_references_only_known_tokens() -> None:
    """Şablonda mövcud olmayan token qalmasın — hər iki tema ilə yoxlanılır."""
    for mode in (ThemeMode.LIGHT, ThemeMode.DARK):
        render(QSS_TEMPLATE, theme_tokens(mode))


# --------------------------------------------------------------------------- #
# İşçi statusu
# --------------------------------------------------------------------------- #


def test_worker_status_maps_from_domain_enums() -> None:
    """Maketdəki beş vəziyyət domen enum-larından düzgün alınmalıdır."""
    from src.domain.entities.attendance_record import CheckInStatus
    from src.presentation.widgets.worker_status import WorkerStatus

    assert WorkerStatus.from_domain(CheckInStatus.NOT_STARTED) is WorkerStatus.NOT_STARTED
    assert (
        WorkerStatus.from_domain(CheckInStatus.PENDING_VERIFICATION)
        is WorkerStatus.PENDING_CHECK_IN
    )
    assert WorkerStatus.from_domain(CheckInStatus.VERIFIED) is WorkerStatus.VERIFIED


def test_leave_status_overrides_check_in() -> None:
    """İcazədə olan işçi "Mağazada" görünməməlidir — operator onu gözləyir."""
    from src.domain.entities.attendance_record import CheckInStatus
    from src.domain.entities.leave_request import LeaveStatus
    from src.presentation.widgets.worker_status import WorkerStatus

    assert (
        WorkerStatus.from_domain(CheckInStatus.VERIFIED, LeaveStatus.OUTSIDE)
        is WorkerStatus.OUTSIDE
    )
    assert (
        WorkerStatus.from_domain(CheckInStatus.VERIFIED, LeaveStatus.PENDING_RETURN_VERIFICATION)
        is WorkerStatus.PENDING_RETURN
    )


def test_pending_states_are_not_actionable() -> None:
    """Təsdiq gözləyən işçi təkrar sorğu göndərə bilməməlidir."""
    from src.presentation.widgets.worker_status import WorkerStatus

    assert not WorkerStatus.PENDING_CHECK_IN.is_actionable
    assert not WorkerStatus.PENDING_RETURN.is_actionable
    assert WorkerStatus.NOT_STARTED.is_actionable


def test_every_status_has_azerbaijani_text() -> None:
    """Bölmə 9: interfeysdə İngiliscə placeholder qalmamalıdır."""
    from src.presentation.widgets.worker_status import WorkerStatus

    for status in WorkerStatus:
        assert status.label_az.strip()
        assert status.hint_az.strip()
        assert status.action_az.strip()
        assert status.color_token.startswith("--color-")


# --------------------------------------------------------------------------- #
# İkonlar
# --------------------------------------------------------------------------- #


def test_icon_set_is_not_empty() -> None:
    from src.presentation.widgets import icons

    assert len(icons.available()) >= 30


def test_unknown_icon_raises() -> None:
    from src.presentation.widgets.icons import IconNotFoundError, _document

    with pytest.raises(IconNotFoundError, match="yoxdur"):
        _document("belə-ikon-yoxdur", "#000000", 1.5)


def test_icon_document_embeds_colour() -> None:
    """Rəng SVG-yə yazılmalıdır — əks halda ikon həmişə qara görünərdi."""
    from src.presentation.widgets.icons import _document

    document = _document("bell", "#F5A623", 1.5).decode()
    assert 'stroke="#F5A623"' in document
    assert 'viewBox="0 0 16 16"' in document
