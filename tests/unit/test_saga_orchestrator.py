"""Saga / Compensating Transaction testləri.

Spesifikasiya bölmə 1-in əsas zəmanəti burada qorunur: audit-kritik zəncir
yarımçıq qalarsa, əməliyyat `PENDING_RECONCILIATION` statusuna keçir və heç
vaxt sükutla itmir.
"""

from __future__ import annotations

import pytest

from src.shared.event_bus import EventBus
from src.shared.exceptions import SagaCompensationError
from src.shared.saga_orchestrator import (
    CompensationOutcome,
    InMemorySagaStateRepository,
    ReconciliationPolicy,
    SagaOrchestrator,
    SagaPendingReconciliationEvent,
    SagaStatus,
    SagaStep,
)

# QEYD: `asyncio` marker-i modul səviyyəsində QOYULMUR — `asyncio_mode = "auto"`
# async testləri özü tutur, sinxron testə (`test_step_validation`) qoyulan
# asyncio marker-i isə pytest-asyncio xəbərdarlığı yaradardı.
pytestmark = pytest.mark.unit


async def test_all_steps_succeed(saga: SagaOrchestrator) -> None:
    trace: list[str] = []

    result = await saga.execute(
        name="HappyPath",
        steps=[
            SagaStep("bir", action=lambda _: trace.append("bir")),
            SagaStep("iki", action=lambda _: trace.append("iki")),
        ],
    )

    assert result.status is SagaStatus.COMPLETED
    assert result.succeeded is True
    assert result.compensation_outcome is CompensationOutcome.NOT_REQUIRED
    assert trace == ["bir", "iki"]


async def test_step_result_available_in_context(saga: SagaOrchestrator) -> None:
    result = await saga.execute(
        name="Context",
        steps=[
            SagaStep("hesabla", action=lambda _: 42),
            SagaStep("istifadə", action=lambda ctx: ctx["hesabla_result"] * 2),
        ],
    )

    assert result.context["istifadə_result"] == 84


async def test_compensation_runs_in_reverse_order(saga: SagaOrchestrator) -> None:
    trace: list[str] = []

    def failing(_: dict[str, object]) -> None:
        raise RuntimeError("üçüncü addım çökdü")

    result = await saga.execute(
        name="LeaveVerification",
        steps=[
            SagaStep(
                "leave_status",
                action=lambda _: trace.append("do:leave"),
                compensation=lambda _: trace.append("undo:leave"),
            ),
            SagaStep(
                "fine_calc",
                action=lambda _: trace.append("do:fine"),
                compensation=lambda _: trace.append("undo:fine"),
            ),
            SagaStep("audit_log", action=failing),
        ],
    )

    assert trace == ["do:leave", "do:fine", "undo:fine", "undo:leave"]
    assert result.failed_step == "audit_log"
    assert result.compensation_outcome is CompensationOutcome.FULLY_COMPENSATED


async def test_any_failure_yields_pending_reconciliation(saga: SagaOrchestrator) -> None:
    """Spesifikasiya-hərfi davranış: kompensasiya uğurlu olsa belə status
    `PENDING_RECONCILIATION` olur (defolt ON_ANY_FAILURE siyasəti)."""

    def boom(_: dict[str, object]) -> None:
        raise ValueError("xəta")

    result = await saga.execute(
        name="AuditCritical",
        steps=[
            SagaStep("a", action=lambda _: None, compensation=lambda _: None),
            SagaStep("b", action=boom),
        ],
    )

    assert result.status is SagaStatus.PENDING_RECONCILIATION
    assert result.compensation_outcome is CompensationOutcome.FULLY_COMPENSATED


async def test_lenient_policy_yields_compensated(saga: SagaOrchestrator) -> None:
    def boom(_: dict[str, object]) -> None:
        raise ValueError("xəta")

    result = await saga.execute(
        name="NonCritical",
        steps=[
            SagaStep("a", action=lambda _: None, compensation=lambda _: None),
            SagaStep("b", action=boom),
        ],
        policy=ReconciliationPolicy.ON_COMPENSATION_FAILURE,
    )

    assert result.status is SagaStatus.COMPENSATED


async def test_failed_compensation_marks_partial(saga: SagaOrchestrator) -> None:
    def bad_compensation(_: dict[str, object]) -> None:
        raise RuntimeError("kompensasiya da çökdü")

    def boom(_: dict[str, object]) -> None:
        raise ValueError("əsas xəta")

    result = await saga.execute(
        name="BadCompensation",
        steps=[
            SagaStep("ok_step", action=lambda _: None, compensation=lambda _: None),
            SagaStep("bad_step", action=lambda _: None, compensation=bad_compensation),
            SagaStep("fail", action=boom),
        ],
        policy=ReconciliationPolicy.ON_COMPENSATION_FAILURE,
    )

    assert result.status is SagaStatus.PENDING_RECONCILIATION
    assert result.compensation_outcome is CompensationOutcome.PARTIALLY_COMPENSATED


async def test_non_compensatable_step_reported(saga: SagaOrchestrator) -> None:
    """Audit log yazısı kimi geri qaytarıla bilməyən addım izlənilir."""

    def boom(_: dict[str, object]) -> None:
        raise ValueError("xəta")

    result = await saga.execute(
        name="Uncompensatable",
        steps=[
            SagaStep("audit_write", action=lambda _: None, compensation=None),
            SagaStep("fail", action=boom),
        ],
    )

    assert "audit_write" in result.uncompensated_steps


async def test_pending_reconciliation_event_published(
    event_bus: EventBus, saga_repository: InMemorySagaStateRepository
) -> None:
    """KRİTİK: bu hadisə e-poçt fallback kanalını tetikləyir (bölmə 7)."""
    captured: list[SagaPendingReconciliationEvent] = []
    event_bus.subscribe(SagaPendingReconciliationEvent, captured.append)
    orchestrator = SagaOrchestrator(event_bus=event_bus, state_repository=saga_repository)

    def boom(_: dict[str, object]) -> None:
        raise RuntimeError("çökdü")

    await orchestrator.execute(name="Critical", steps=[SagaStep("x", action=boom)])

    assert len(captured) == 1
    assert captured[0].saga_name == "Critical"
    assert captured[0].failed_step == "x"


async def test_retry_then_success(saga: SagaOrchestrator) -> None:
    attempts = {"count": 0}

    def flaky(_: dict[str, object]) -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ConnectionError("şəbəkə")
        return "ok"

    result = await saga.execute(
        name="Retry",
        steps=[SagaStep("flaky", action=flaky, retries=3, retry_delay_seconds=0.0)],
    )

    assert result.status is SagaStatus.COMPLETED
    assert attempts["count"] == 3
    assert result.executions[0].attempts == 3


async def test_async_step_supported(saga: SagaOrchestrator) -> None:
    async def async_action(_: dict[str, object]) -> str:
        return "async-ok"

    result = await saga.execute(name="AsyncStep", steps=[SagaStep("a", action=async_action)])

    assert result.context["a_result"] == "async-ok"


async def test_pending_reconciliation_listed_in_repository(
    saga: SagaOrchestrator, saga_repository: InMemorySagaStateRepository
) -> None:
    def boom(_: dict[str, object]) -> None:
        raise RuntimeError("çökdü")

    await saga.execute(name="Listed", steps=[SagaStep("x", action=boom)])

    pending = saga_repository.list_pending_reconciliation()
    assert len(pending) == 1
    assert pending[0].saga_name == "Listed"
    assert saga.pending_reconciliation()[0].saga_name == "Listed"


async def test_raise_for_status(saga: SagaOrchestrator) -> None:
    def boom(_: dict[str, object]) -> None:
        raise RuntimeError("çökdü")

    result = await saga.execute(name="Raise", steps=[SagaStep("x", action=boom)])

    with pytest.raises(SagaCompensationError):
        SagaOrchestrator.raise_for_status(result)


async def test_duplicate_step_names_rejected(saga: SagaOrchestrator) -> None:
    with pytest.raises(ValueError, match="təkrarlanır"):
        await saga.execute(
            name="Dup",
            steps=[
                SagaStep("eyni", action=lambda _: None),
                SagaStep("eyni", action=lambda _: None),
            ],
        )


async def test_empty_step_list_rejected(saga: SagaOrchestrator) -> None:
    with pytest.raises(ValueError, match="ən azı bir addım"):
        await saga.execute(name="Empty", steps=[])


def test_step_validation() -> None:
    with pytest.raises(ValueError, match="boş ola bilməz"):
        SagaStep("   ", action=lambda _: None)
    with pytest.raises(TypeError):
        SagaStep("x", action="not-callable")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="mənfi"):
        SagaStep("x", action=lambda _: None, retries=-1)


async def test_result_serialization(saga: SagaOrchestrator) -> None:
    result = await saga.execute(name="Serialize", steps=[SagaStep("a", action=lambda _: None)])
    payload = result.to_dict()

    assert payload["saga_name"] == "Serialize"
    assert payload["status"] == "COMPLETED"
    assert payload["steps"][0]["name"] == "a"
