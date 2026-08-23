"""DEEP-GAP UX-8 — drill-down-dan GERİ yol.

──────────────────────────────────────────────────────────────────────────────
QÜSUR NƏ İDİ
──────────────────────────────────────────────────────────────────────────────
Menecer İdarə Panelində reytinq sətrinə klikləyir və özünü BAŞQA mağazanın
Gündəlik Tabelində tapır. Başlıqda yalnız «Gündəlik Tabel» yazırdı, yəni
istifadəçi HARA düşdüyünü bilmirdi; sol paneldən qayıdanda isə ekran HƏMİN
başqa mağazanın məlumatı ilə dolu qalırdı, çünki ekranlar açara görə keşlənir
(`REFRESH_ON_REVISIT` yalnız `dashboard`-ı əhatə edir).

Testlər İKİ müqaviləni kilidləyir:

1. drill-down başlığın altındakı kontekst sətrini kliklənən mağaza ilə yazır;
2. sol paneldən qayıdış ekranı İSTİFADƏÇİNİN ÖZ mağazasına qaytarır və köhnə
   kontekst mətnini bərpa edir — İKİNCİ qayıdışda isə heç nə etmir (ekran
   artıq normal vəziyyətdədir, ona görə əlavə sorğu getmir).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from src.presentation.controllers.screen_data import DAILY_ROSTER_SCREEN_KEY
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

STORE_ID = str(uuid.uuid4())


class _FakeShell:
    def __init__(self) -> None:
        self.subtitles: dict[str, str] = {DAILY_ROSTER_SCREEN_KEY: "Bu gün · 12 nəfər"}
        self.roster = object()

    def show_screen(self, key: str) -> bool:
        return True

    def screen_for(self, key: str) -> Any:
        return self.roster if key == DAILY_ROSTER_SCREEN_KEY else None

    def screen_subtitle(self, key: str) -> str:
        return self.subtitles.get(key, "")

    def set_screen_subtitle(self, key: str, subtitle: str) -> None:
        self.subtitles[key] = subtitle


class _FakeBinder:
    def __init__(self) -> None:
        self.drilled: list[Any] = []
        self.populated: list[str] = []

    def populate_daily_roster_for_store(self, store_id: Any, screen: Any) -> None:
        self.drilled.append(store_id)

    def populate(self, key: str, screen: Any) -> None:
        self.populated.append(key)


def _application(
    qt_app: Any, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, _FakeShell, _FakeBinder]:
    from src.presentation.app import KompasApplication
    from src.presentation.theme.tokens import ThemeMode

    application = KompasApplication(
        qt_app, preview=False, theme_preference=ThemeMode.LIGHT, context=None
    )
    shell, binder = _FakeShell(), _FakeBinder()
    application._shell = shell
    application._binder = binder
    # Mağaza adı XAM SQL ilə oxunur — bu testin predmeti naviqasiyadır, baza
    # deyil, ona görə ad birbaşa verilir (metodun ÖZ ehtiyat yolu ayrıca
    # sənədləşib: ad tapılmasa «Seçilmiş mağaza» yazılır).
    monkeypatch.setattr(application, "_drill_store_name", lambda _text: "Bellona 28 May")
    return application, shell, binder


@requires_qt
def test_drill_down_names_the_store_in_the_page_context(qt_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    application, shell, binder = _application(qt_app, monkeypatch)

    application._on_ranking_row_selected(STORE_ID)

    assert binder.drilled and str(binder.drilled[0]) == STORE_ID
    assert shell.subtitles[DAILY_ROSTER_SCREEN_KEY] == "Bellona 28 May · İdarə Panelindən"


@requires_qt
def test_returning_from_the_sidebar_resets_the_store_and_the_context(qt_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Sol paneldən qayıdış ekranı İSTİFADƏÇİNİN ÖZ mağazasına qaytarır."""
    application, shell, binder = _application(qt_app, monkeypatch)
    application._on_ranking_row_selected(STORE_ID)

    application._on_screen_revisited(DAILY_ROSTER_SCREEN_KEY)

    assert binder.populated == [DAILY_ROSTER_SCREEN_KEY]
    assert shell.subtitles[DAILY_ROSTER_SCREEN_KEY] == "Bu gün · 12 nəfər"


@requires_qt
def test_a_second_return_does_not_query_again(qt_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Drill-down izi bir dəfə silinir — ekran artıq normal vəziyyətdədir.

    Əks halda hər qayıdış bir sorğu açardı, halbuki `REFRESH_ON_REVISIT`
    siyahısının bütün mənası məhz bunun qarşısını almaqdır.
    """
    application, _shell, binder = _application(qt_app, monkeypatch)
    application._on_ranking_row_selected(STORE_ID)
    application._on_screen_revisited(DAILY_ROSTER_SCREEN_KEY)

    application._on_screen_revisited(DAILY_ROSTER_SCREEN_KEY)

    assert binder.populated == [DAILY_ROSTER_SCREEN_KEY]


@requires_qt
def test_a_roster_visit_without_a_drill_down_is_untouched(qt_app, monkeypatch) -> None:
    """Drill-down olmadan qayıdış HEÇ NƏ etmir — köhnə davranış qorunur."""
    application, shell, binder = _application(qt_app, monkeypatch)

    application._on_screen_revisited(DAILY_ROSTER_SCREEN_KEY)

    assert binder.populated == []
    assert shell.subtitles[DAILY_ROSTER_SCREEN_KEY] == "Bu gün · 12 nəfər"
