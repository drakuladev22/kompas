"""Yeni yalnız-oxu bağlamaları: Dashboard, Yardım Mərkəzi, Satış Xalları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AÇAR PARİTETİ AYRICA YOXLANILIR
──────────────────────────────────────────────────────────────────────────────
`_help` mövzuları MODUL AÇARLARINA görə süzür. Əgər burada öz ad məkanımızı
qursaydıq (məs. `"fines"`, halbuki `feature_toggles` cədvəli `"FINE_MODULE"`
saxlayır), süzgəc HƏMİŞƏ boş nəticə verərdi — maketdə isə bu görünməzdi,
çünki maket süzgəc tətbiq etmir. Layihədə məhz bu qüsur olub (bax
`shell/menu.py` başlığı), ona görə paritet testlə bağlanır.

Testlər Qt TƏLƏB ETMİR: ekranlar duck-typing ilə əvəzlənir.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, Final

import pytest

from src.domain.policies import FeatureModule
from src.domain.value_objects.identifiers import EmployeeId, TenantId
from src.presentation.controllers.screen_data import (
    HELP_TOPIC_MODULES,
    ScreenDataBinder,
    _sync_delay_text,
)
from src.presentation.screens.group_h import HELP_TOPICS

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())


# --------------------------------------------------------------------------- #
# Yardım Mərkəzi
# --------------------------------------------------------------------------- #


def test_help_topic_keys_match_the_screen_catalog() -> None:
    """Cədvəldəki mövzu açarları `HELP_TOPICS` ilə EYNİ olmalıdır.

    Fərq olsaydı, adı dəyişmiş mövzu sükutla süzgəcdən düşərdi (heç bir
    modula bağlı olmadığı üçün) və istifadəçi onu heç vaxt görməzdi.
    """
    assert set(HELP_TOPIC_MODULES) == {topic[0] for topic in HELP_TOPICS}


def test_help_topic_modules_use_the_feature_toggle_namespace() -> None:
    """Dəyərlər `FeatureModule` açarlarıdır — toggle cədvəli ilə eyni."""
    known = {module.value for module in FeatureModule}
    for topic, module_key in HELP_TOPIC_MODULES.items():
        assert module_key is None or module_key in known, f"«{topic}» naməlum modul açarı işlədir"


class _Toggles:
    def __init__(self, enabled: set[str], *, fail: bool = False) -> None:
        self._enabled = enabled
        self._fail = fail

    def enabled_modules(self, tenant_id: TenantId) -> set[str]:
        if self._fail:
            raise RuntimeError("toggle mənbəyi əlçatmazdır")
        return set(self._enabled)


class _HelpScreen:
    def __init__(self) -> None:
        self.topics: Any = "toxunulmayıb"

    def set_visible_topics(self, keys: frozenset[str] | None) -> None:
        self.topics = keys


class _Session:
    def __init__(self, toggles: _Toggles) -> None:
        self.tenant_id = TENANT
        self.toggles = toggles


class _Context:
    def __init__(self, session: _Session) -> None:
        self._session = session

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        yield self._session


def _binder(session: _Session) -> ScreenDataBinder:
    actor = type("_Actor", (), {"id": EmployeeId(uuid.uuid4())})()
    return ScreenDataBinder(_Context(session), actor)  # type: ignore[arg-type]


def test_help_hides_topics_of_disabled_modules() -> None:
    """Söndürülmüş modulun təlimatı GÖSTƏRİLMİR (bölmə 3, DYNAMIC UI)."""
    session = _Session(_Toggles({FeatureModule.SALES_POINTS.value}))
    screen = _HelpScreen()

    _binder(session).populate("help", screen)  # type: ignore[arg-type]

    # `erp` modula bağlı deyil (quraşdırma addımıdır), `points` isə açıqdır.
    assert screen.topics == frozenset({"erp", "points"})


def test_help_falls_back_to_all_topics_when_toggles_are_unreadable() -> None:
    """Toggle oxunmasa yardım GİZLƏNMİR — fail-open (bax `_help` docstring)."""
    session = _Session(_Toggles(set(), fail=True))
    screen = _HelpScreen()

    _binder(session).populate("help", screen)  # type: ignore[arg-type]

    assert screen.topics is None


# --------------------------------------------------------------------------- #
# Dashboard köməkçiləri
# --------------------------------------------------------------------------- #


def test_never_synced_server_is_not_shown_as_zero_delay() -> None:
    """`None` gecikmə "0 san" ilə qarışdırılmır — biri ideal, digəri problem."""
    assert _sync_delay_text(None) == "sinxronlaşmayıb"
    assert _sync_delay_text(0) == "0 san"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(45, "45 san"), (600, "10 dəq"), (7200, "2 saat")],
)
def test_sync_delay_uses_readable_units(seconds: int, expected: str) -> None:
    assert _sync_delay_text(seconds) == expected
