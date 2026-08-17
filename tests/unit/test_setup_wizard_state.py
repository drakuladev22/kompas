"""Sihirbazın vəziyyəti və form sahələrinin BOŞLUĞU (istifadəçi hesabatı).

──────────────────────────────────────────────────────────────────────────────
ÜÇ QÜSUR — ÜÇÜ DƏ PAKETLƏNMİŞ `.exe`-Nİ İŞLƏDƏRKƏN GÖRÜNDÜ
──────────────────────────────────────────────────────────────────────────────
Heç birini 5076 test göstərmirdi, çünki hamısı Qt widget-lərinin ÖMRÜNÜ və
istifadəçinin GÖRDÜYÜNÜ deyil, məntiqi ölçürdü.

1. «Keç» DÜYMƏSİ ÖLÜ İDİ. O, `_on_next`-ə bağlı idi — yəni «Davam Et»in
   eynisi: validasiyadan keçirdi. Üstəlik `collected()` silinmiş widget-lərdən
   oxuyurdu: `clear_layout()` `deleteLater()` çağırır, Python atributu qalır,
   C++ obyekti ölür və `field.text()` `RuntimeError` atır. İstisna Qt
   slot-unda udulur, ona görə düymə basılırdı və HEÇ NƏ BAŞ VERMİRDİ.

2. FORM SAHƏLƏRİ NÜMUNƏ MƏTNLƏ DOLU GÖRÜNÜRDÜ («Rəşad Məmmədov»,
   «admin@kompas.az»). İstifadəçi onları real dəyər sanır.

3. TASKBAR İKONU GÖRÜNMÜRDÜ — `setWindowIcon()` çağırılsa da, Windows
   Taskbar düymələri **AppUserModelID** üzrə qruplaşdırır.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

_REPO: Final[Path] = Path(__file__).resolve().parents[2]
_SCREENS: Final[Path] = _REPO / "src" / "presentation" / "screens"

#: Nümunə dəyəri əlaməti sayılan naxışlar. Bunlar SAHƏNİ DOLU GÖSTƏRİR.
_EXAMPLE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"[Mm]əsələn", re.IGNORECASE),
    re.compile(r"\bməs\.", re.IGNORECASE),
    # Tarix/versiya nümunələri: «2026-08-01», «01.08.2026».
    re.compile(r"\d{4}-\d{2}(-\d{2})?"),
    re.compile(r"\d{2}\.\d{2}\.\d{4}"),
    # Şəbəkə/host nümunələri.
    re.compile(r"\d{1,3}(\.\d{1,3}){3}"),
    # Hex rəng nümunəsi.
    re.compile(r"#[0-9A-Fa-f]{6}"),
)

_PLACEHOLDER = re.compile(r'(?:placeholder=|setPlaceholderText\(\s*)"((?:[^"\\]|\\.)*)"')


def _placeholders() -> list[tuple[str, str]]:
    """`(fayl, mətn)` — bütün ekranlardakı sabit placeholder-lər."""
    found: list[tuple[str, str]] = []
    for path in sorted(_SCREENS.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for match in _PLACEHOLDER.finditer(path.read_text(encoding="utf-8")):
            if match.group(1):
                found.append((path.name, match.group(1)))
    return found


def test_no_form_field_shows_example_data() -> None:
    """Sahələr BOŞ görünməlidir — nümunə dəyər QALMAMALIDIR.

    Göstəriş mətnləri («Mesaj yazın…», «Vəzifə axtar») QALIR və bu, fərqli
    şeydir: onlar sahəni doldurmur, NƏ ETMƏLİ olduğunu deyir. Silinsəydilər
    axtarış qutusu tamamilə mənasız görünərdi.
    """
    offenders = [
        f"{name}: «{text}»"
        for name, text in _placeholders()
        if any(pattern.search(text) for pattern in _EXAMPLE_PATTERNS)
    ]
    assert not offenders, "Form sahələrində nümunə mətn qalıb:\n  " + "\n  ".join(offenders)


def test_the_setup_wizard_asks_for_nothing_by_example() -> None:
    """Sihirbazın HEÇ BİR sahəsində placeholder olmamalıdır.

    Sihirbaz istifadəçinin gördüyü İLK ekrandır və oradakı «Rəşad Məmmədov»
    nümunəsi məhz bu hesabatın səbəbi oldu.
    """
    source = (_SCREENS / "group_a_entry.py").read_text(encoding="utf-8")
    leftovers = [m.group(1) for m in _PLACEHOLDER.finditer(source) if m.group(1)]
    assert leftovers == [], f"sihirbazda placeholder qalıb: {leftovers}"


def test_the_taskbar_identity_is_set_before_any_window() -> None:
    """Windows Taskbar ikonu üçün AppUserModelID MƏCBURİDİR.

    `setWindowIcon()` PƏNCƏRƏNİN ikonunu verir; Taskbar isə düymələri
    AppUserModelID üzrə qruplaşdırır və kimlik təyin edilməyəndə onu icra
    olunan faylın yolundan çıxarır. `onefile` `.exe`-də həmin yol
    `%TEMP%\\_MEIxxxxx\\` altındadır və HƏR AÇILIŞDA DƏYİŞİR — ona görə
    Windows tətbiqi tanımır və ümumi ikon göstərir.

    Çağırışın YERİ də vacibdir: ilk pəncərədən ƏVVƏL olmalıdır.
    """
    source = (_REPO / "src" / "presentation" / "app.py").read_text(encoding="utf-8")

    assert "SetCurrentProcessExplicitAppUserModelID" in source, "kimlik təyin edilmir"
    assert "APP_USER_MODEL_ID" in source, "kimlik sabiti yoxdur"

    call = source.index("_set_app_user_model_id()\n\n    existing = QApplication.instance()")
    window = source.index("KompasApplication(app,")
    assert call < window, "kimlik ilk pəncərədən SONRA təyin olunur — Windows onu oxumaz"


@requires_qt
def test_answers_survive_widget_destruction(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Addım dəyişəndə yazılan mətn İTMİR — `collected()` onu tapır.

    Bu, qüsurun ÖZ ssenarisidir: birinci addımı doldur, irəli get, sonuncu
    addıma çat və nəticəni topla. Əvvəl bu yolda `RuntimeError` atılırdı.
    """
    from src.presentation.screens.group_a_entry import FirstRunWizard
    from src.presentation.theme.manager import ThemeManager

    screen = FirstRunWizard(ThemeManager())

    screen._full_name.set_text("Aysel Quliyeva")
    screen._email.set_text("aysel@example.az")
    screen._username.set_text("a.quliyeva")
    screen._password.set_text("Parol12345!")
    screen._password_repeat.set_text("Parol12345!")
    screen._on_next()

    assert screen.step_index == 1, "birinci addım keçilmədi"
    screen._store_name.set_text("28 May")
    screen._on_next()

    assert screen.step_index == 2
    payload = screen.collected()
    root = payload["root"]
    assert isinstance(root, dict)
    assert root["first_name"] == "Aysel"
    assert root["last_name"] == "Quliyeva"
    assert root["username"] == "a.quliyeva"
    stores = payload["stores"]
    assert isinstance(stores, list)
    assert stores[0]["name"] == "28 May"


@requires_qt
def test_going_back_restores_what_was_typed(qtbot) -> None:  # type: ignore[no-untyped-def]
    """«Geri» yazılanı GÖSTƏRİR — widget yenidən qurulur, dəyər bərpa olunur."""
    from src.presentation.screens.group_a_entry import FirstRunWizard
    from src.presentation.theme.manager import ThemeManager

    screen = FirstRunWizard(ThemeManager())
    screen._full_name.set_text("Rəşad Məmmədov")
    screen._email.set_text("r@example.az")
    screen._username.set_text("r.m")
    screen._password.set_text("Parol12345!")
    screen._password_repeat.set_text("Parol12345!")
    screen._on_next()
    screen._on_back()

    assert screen.step_index == 0
    assert screen._full_name.text() == "Rəşad Məmmədov", "«Geri» yazılanı sildi"


@requires_qt
def test_skip_advances_without_validation_and_drops_the_step(qtbot) -> None:  # type: ignore[no-untyped-def]
    """«Keç» — validasiya YOX, cavablar SİLİNİR.

    İki şey birlikdə yoxlanılır, çünki qüsur da iki hissəli idi: düymə
    irəliləmirdi VƏ irəliləsəydi yarımçıq dəyəri saxlayardı.
    """
    from src.presentation.screens.group_a_entry import FirstRunWizard
    from src.presentation.theme.manager import ThemeManager

    screen = FirstRunWizard(ThemeManager())
    for field, value in (
        (screen._full_name, "Ad Soyad"),
        (screen._email, "a@b.az"),
        (screen._username, "a.b"),
        (screen._password, "Parol12345!"),
        (screen._password_repeat, "Parol12345!"),
    ):
        field.set_text(value)
    screen._on_next()
    screen._store_name.set_text("Mağaza")
    screen._on_next()

    # Addım 3 (1C server) — yarımçıq doldurulur, sonra KEÇİLİR.
    assert screen.step_index == 2
    screen._server_host.set_text("10.0.0.1:1541")
    screen._on_skip()

    assert screen.step_index == 3, "«Keç» irəliləmədi"
    assert "server" not in screen.collected(), "keçilən addımın dəyəri quraşdırmaya düşdü"
