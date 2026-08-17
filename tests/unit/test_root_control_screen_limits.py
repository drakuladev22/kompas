"""ROOT İdarə Mərkəzi hər limiti göstərə bilməlidir — biri belə paneli aparmır.

──────────────────────────────────────────────────────────────────────────────
QÜSUR: PANEL «BOŞ» GÖRÜNÜRDÜ
──────────────────────────────────────────────────────────────────────────────
İstifadəçi hesabatı: «root idarə mərkəzində heç bir şey görsənmir».

Səbəb bir sətirdə idi:

    OverflowError: QSpinBox.setRange(16777216, 8589934592)

`IMAGE_CACHE_MAX_BYTES` tavanı 8 GiB-dir (migrations/032), `QSpinBox` isə
`int32` ilə işləyir (maks. 2 147 483 647). İstisna `RootControlController.
_fill`-i ORTADA dayandırırdı: limitlərin bir hissəsi qurulur, sonra fasilə
parametrləri, modul açarları, icazə registri və brendinq bölmələri
ÜMUMİYYƏTLƏ qurulmurdu. `refresh()` istisnanı tutub «Panel açıla bilmədi»
yazırdı, yəni əsl səbəb — bir limitin tavanı — heç yerdə görünmürdü.

──────────────────────────────────────────────────────────────────────────────
QAPI NƏ QORUYUR
──────────────────────────────────────────────────────────────────────────────
Yeni limit açarı gətirən adam tavanı sərbəst seçir və `system_limits` üçün
8 GiB tamamilə normal dəyərdir. Ona görə qapı «tavan kiçik olsun» demir —
EKRANIN hər tavanı daşıya bilməsini tələb edir.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

import pytest

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.infrastructure.config.limits import INFRA_LIMIT_BOUNDS
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

#: `QSpinBox`-un tip hüdudu — ekrandakı sabitlə eyni olmalıdır.
_INT32_MAX: Final = 2_147_483_647


def _every_limit_row() -> list[tuple[str, str, int | str, int, int, str]]:
    """HƏR açar üçün ekranın gözlədiyi sətir — hüdudları ilə birlikdə.

    Siyahı əl ilə seçilmir: `DEFAULT_LIMITS`-in hamısı gəzilir, yəni sabah
    əlavə olunan açar da avtomatik qapıdan keçir.
    """
    from src.presentation.controllers.root_control import limit_row

    rows = []
    for key, value in DEFAULT_LIMITS.items():
        bounds = INFRA_LIMIT_BOUNDS.get(key)
        minimum = str(bounds[0]) if bounds else None
        maximum = str(bounds[1]) if bounds else None
        rows.append(limit_row(key.value, value, min_value=minimum, max_value=maximum))
    return rows


def test_at_least_one_limit_really_exceeds_the_spin_box_range() -> None:
    """Qapının ÖZÜ yoxlanılır: sınaq halı həqiqətən mövcuddur.

    Bu bənd olmasaydı, `IMAGE_CACHE_MAX_BYTES` bir gün kiçildiləndə aşağıdakı
    test «keçdi» deyərdi, halbuki heç nə ölçməmiş olardı.
    """
    oversized = [
        key for key, (_, maximum) in INFRA_LIMIT_BOUNDS.items() if maximum > Decimal(_INT32_MAX)
    ]
    assert oversized, "32 bitə sığmayan limit qalmayıb — qapı boşa işləyir"


@requires_qt
def test_every_limit_can_be_rendered(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """Bütün limitlər BİR ANDA ekrana verilir — istisna atılmamalıdır."""
    from src.presentation.screens.group_d import RootControlScreen
    from src.presentation.theme.manager import ThemeManager

    screen = RootControlScreen(ThemeManager())
    qtbot.addWidget(screen)

    screen.set_limits(_every_limit_row())

    rendered = set(screen._limit_inputs) | set(screen._limit_texts)
    missing = {key.value for key in DEFAULT_LIMITS} - rendered
    assert not missing, f"bu limitlər ekranda YOXDUR: {sorted(missing)}"


@requires_qt
def test_an_oversized_limit_falls_back_to_a_text_field(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """32 bitə sığmayan limit MƏTN sahəsi kimi göstərilir, atılmır.

    Vacib olan «spin yox, sətir» deyil — dəyərin YENƏ redaktə oluna bilməsi
    və `collected()`-ə düşməsidir. Sahə ümumiyyətlə göstərilməsəydi, Root
    həmin limiti panel vasitəsilə heç vaxt dəyişə bilməzdi.
    """
    from src.presentation.controllers.root_control import limit_row
    from src.presentation.screens.group_d import RootControlScreen
    from src.presentation.theme.manager import ThemeManager

    key = SystemLimitKey.IMAGE_CACHE_MAX_BYTES
    minimum, maximum = INFRA_LIMIT_BOUNDS[key]

    screen = RootControlScreen(ThemeManager())
    qtbot.addWidget(screen)
    screen.set_limits(
        [limit_row(key.value, DEFAULT_LIMITS[key], min_value=str(minimum), max_value=str(maximum))]
    )

    assert key.value not in screen._limit_inputs, "8 GiB tavanı spin-ə verilib"
    assert key.value in screen._limit_texts, "limit ümumiyyətlə göstərilmir"
    assert screen._limit_texts[key.value].text() == DEFAULT_LIMITS[key]
    assert key.value in screen.collected()["limits"]  # type: ignore[operator]


@requires_qt
def test_a_normal_limit_still_uses_a_spin_box(qtbot, qt_app) -> None:  # type: ignore[no-untyped-def]
    """Düzəliş adi limitləri MƏTNƏ çevirməməlidir — yoxsa panel geriləyər."""
    from src.presentation.controllers.root_control import limit_row
    from src.presentation.screens.group_d import RootControlScreen
    from src.presentation.theme.manager import ThemeManager

    key = SystemLimitKey.PASSWORD_MIN_LENGTH
    minimum, maximum = INFRA_LIMIT_BOUNDS[key]

    screen = RootControlScreen(ThemeManager())
    qtbot.addWidget(screen)
    screen.set_limits(
        [limit_row(key.value, DEFAULT_LIMITS[key], min_value=str(minimum), max_value=str(maximum))]
    )

    assert key.value in screen._limit_inputs
    assert screen._limit_inputs[key.value].value() == int(DEFAULT_LIMITS[key])
