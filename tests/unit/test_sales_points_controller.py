"""`SalesPointsController` yazı yolu (`controllers/sales_points.py`) — DÖVRƏ 5 audit.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ
──────────────────────────────────────────────────────────────────────────────
`sales_points.py` `tests/` daxilində adı belə çəkilmirdi (CLAUDE.md bölmə 2 —
«10 kontroller LİTERAL 0%»). `_on_reward`/`_on_appeal` `UUID(reward_id)`/
`UUID(entry_id)` çağırırdı, lakin `_write()`-in qoruyucusu YALNIZ
`except KompasOSError`-dır — `UUID()`-in atdığı `ValueError` ORADAN KEÇMİR.
Normal axında bu identifikator ekranın ÖZ sətrindən gəlir (həmişə etibarlıdır),
lakin köhnəlmiş sətir/UI uyğunsuzluğunda bu, ÇÖKMƏ demək idi. Bu fayl HƏM
həmin qapını, HƏM də normal (etibarlı ID) axını ölçür.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from src.presentation.controllers.sales_points import SalesPointsController

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR = uuid.uuid4()


class _SalesPoints:
    def __init__(self) -> None:
        self.rewards: list[dict[str, Any]] = []
        self.disputes: list[dict[str, Any]] = []

    def request_reward(self, **kwargs: Any) -> None:
        self.rewards.append(kwargs)

    def open_dispute(self, **kwargs: Any) -> None:
        self.disputes.append(kwargs)


class _Session:
    def __init__(self, sales_points: _SalesPoints) -> None:
        self.tenant_id = TENANT
        self.sales_points = sales_points
        self.committed = False

    def commit(self) -> None:
        self.committed = True

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _Context:
    def __init__(self, sales_points: _SalesPoints) -> None:
        self._sales_points = sales_points
        self.sessions: list[_Session] = []

    def session(self, **_: Any) -> _Session:
        created = _Session(self._sales_points)
        self.sessions.append(created)
        return created


class _Actor:
    id = ACTOR


class _Screen:
    def __init__(self) -> None:
        self.errors: list[tuple[str, str]] = []

    def show_error(self, *, title: str, message: str, **_: Any) -> None:
        self.errors.append((title, message))


def _controller(sales_points: _SalesPoints) -> tuple[SalesPointsController, _Context]:
    context = _Context(sales_points)
    controller = SalesPointsController(context, _Actor())  # type: ignore[arg-type]
    controller.refresh = lambda screen: None  # type: ignore[method-assign]
    return controller, context


def test_malformed_reward_id_is_reported_not_crashed() -> None:
    """`UUID("kod-deyil")` `_write`-in `except KompasOSError` qoruyucusundan KEÇMƏMƏLİDİR."""
    sales_points = _SalesPoints()
    controller, context = _controller(sales_points)
    screen = _Screen()

    controller._on_reward(screen, "kod-deyil")

    assert screen.errors == [
        ("Mükafat sorğusu göndərilmədi", "Mükafat identifikatoru düzgün deyil. Səhifəni yeniləyin.")
    ]
    assert not sales_points.rewards, "yararsız ID ilə use case ÇAĞIRILMAMALIDIR"
    assert context.sessions == []


def test_malformed_entry_id_is_reported_not_crashed() -> None:
    sales_points = _SalesPoints()
    controller, context = _controller(sales_points)
    screen = _Screen()

    controller._on_appeal(screen, "")

    assert screen.errors == [
        ("Etiraz göndərilmədi", "Xal sətrinin identifikatoru düzgün deyil. Səhifəni yeniləyin.")
    ]
    assert not sales_points.disputes
    assert context.sessions == []


def test_valid_reward_id_requests_and_commits() -> None:
    sales_points = _SalesPoints()
    controller, context = _controller(sales_points)
    screen = _Screen()
    reward_id = uuid.uuid4()

    controller._on_reward(screen, str(reward_id))

    assert len(sales_points.rewards) == 1
    assert sales_points.rewards[0]["reward_id"] == reward_id
    assert context.sessions[0].committed
    assert screen.errors == []


def test_valid_entry_id_opens_a_dispute_with_the_supplied_reason(monkeypatch: Any) -> None:
    sales_points = _SalesPoints()
    controller, context = _controller(sales_points)
    controller._ask_reason = lambda screen: "Yanlış hesablanıb"  # type: ignore[method-assign]
    screen = _Screen()
    entry_id = uuid.uuid4()

    controller._on_appeal(screen, str(entry_id))

    assert len(sales_points.disputes) == 1
    assert sales_points.disputes[0]["entry_id"] == entry_id
    assert sales_points.disputes[0]["reason"] == "Yanlış hesablanıb"
    assert context.sessions[0].committed
