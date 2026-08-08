"""Saga reconciliation siyasət reyestrinin testləri (qərar SEC-003)."""

from __future__ import annotations

import pytest

from src.shared import saga_policies
from src.shared.saga_orchestrator import (
    ReconciliationPolicy,
    SagaOrchestrator,
    SagaStatus,
    SagaStep,
)

pytestmark = pytest.mark.unit


def test_registry_is_consistent() -> None:
    saga_policies.assert_registry_is_consistent()


def test_audit_critical_sagas_use_strictest_policy() -> None:
    for name in saga_policies.AUDIT_CRITICAL_SAGAS:
        assert saga_policies.policy_for(name) is ReconciliationPolicy.ON_ANY_FAILURE


def test_best_effort_sagas_use_lenient_policy() -> None:
    for name in saga_policies.BEST_EFFORT_SAGAS:
        assert saga_policies.policy_for(name) is ReconciliationPolicy.ON_COMPENSATION_FAILURE


def test_unknown_saga_defaults_to_strictest() -> None:
    """Fail-safe: reyestrə yazmağı unudan developer "yumşaq" rejimə düşməməlidir."""
    assert (
        saga_policies.policy_for("BrandNewUnregisteredSaga") is ReconciliationPolicy.ON_ANY_FAILURE
    )


def test_money_and_attendance_sagas_are_audit_critical() -> None:
    """Spesifikasiyanın maliyyə/davamiyyət zəncirləri sərt siyasətdə olmalıdır."""
    for name in (
        saga_policies.SAGA_LEAVE_VERIFICATION,
        saga_policies.SAGA_MANUAL_FINE_ISSUE,
        saga_policies.SAGA_MANUAL_TIME_OVERRIDE,
        saga_policies.SAGA_PERMISSION_CHANGE,
        saga_policies.SAGA_PAYROLL_EXPORT,
    ):
        assert name in saga_policies.AUDIT_CRITICAL_SAGAS


def test_inconsistent_registry_is_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        saga_policies, "BEST_EFFORT_SAGAS", frozenset({saga_policies.SAGA_LEAVE_VERIFICATION})
    )
    with pytest.raises(ValueError, match="ziddiyyətli"):
        saga_policies.assert_registry_is_consistent()


# --------------------------------------------------------------------------- #
# Orkestratora qoşulma
# --------------------------------------------------------------------------- #


async def test_resolver_applies_registry_policy(saga_repository) -> None:
    orchestrator = SagaOrchestrator(
        state_repository=saga_repository, policy_resolver=saga_policies.policy_for
    )

    def boom(_: dict[str, object]) -> None:
        raise RuntimeError("çökdü")

    audit_critical = await orchestrator.execute(
        name=saga_policies.SAGA_LEAVE_VERIFICATION,
        steps=[
            SagaStep("a", action=lambda _: None, compensation=lambda _: None),
            SagaStep("b", action=boom),
        ],
    )
    best_effort = await orchestrator.execute(
        name=saga_policies.SAGA_NOTIFICATION_DISPATCH,
        steps=[
            SagaStep("a", action=lambda _: None, compensation=lambda _: None),
            SagaStep("b", action=boom),
        ],
    )

    assert audit_critical.status is SagaStatus.PENDING_RECONCILIATION
    assert best_effort.status is SagaStatus.COMPENSATED


async def test_explicit_policy_overrides_registry(saga_repository) -> None:
    orchestrator = SagaOrchestrator(
        state_repository=saga_repository, policy_resolver=saga_policies.policy_for
    )

    def boom(_: dict[str, object]) -> None:
        raise RuntimeError("çökdü")

    result = await orchestrator.execute(
        name=saga_policies.SAGA_LEAVE_VERIFICATION,
        steps=[
            SagaStep("a", action=lambda _: None, compensation=lambda _: None),
            SagaStep("b", action=boom),
        ],
        policy=ReconciliationPolicy.ON_COMPENSATION_FAILURE,
    )

    assert result.status is SagaStatus.COMPENSATED


async def test_no_resolver_falls_back_to_strictest(saga_repository) -> None:
    orchestrator = SagaOrchestrator(state_repository=saga_repository)

    def boom(_: dict[str, object]) -> None:
        raise RuntimeError("çökdü")

    result = await orchestrator.execute(
        name=saga_policies.SAGA_NOTIFICATION_DISPATCH,
        steps=[
            SagaStep("a", action=lambda _: None, compensation=lambda _: None),
            SagaStep("b", action=boom),
        ],
    )

    assert result.status is SagaStatus.PENDING_RECONCILIATION
