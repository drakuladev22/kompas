"""Saga / Compensating Transaction orkestratoru (spesifikasiya bölmə 1).

QAYDA (spesifikasiyadan):
    "`LeaveVerificationUseCase` kimi çox-aqreqatlı əməliyyatlar (leave status +
    fine hesablama + audit log) bir Saga orkestratoru altında icra olunmalıdır.
    Əgər zəncirin hər hansı addımı uğursuz olarsa, artıq commit olunmuş addımlar
    üçün compensating action işə düşməli və bütün əməliyyat
    `PENDING_RECONCILIATION` statusuna keçməlidir. Audit-kritik məlumat heç vaxt
    yarımçıq vəziyyətdə qalmır."

Bu modul həmin qaydanı hərfi mənada tətbiq edir:

    * Addımlar ardıcıl icra olunur; hər uğurlu addım "commit olunmuş" sayılır.
    * İstənilən addım uğursuz olduqda kompensasiyalar TƏRS sırada işə düşür.
    * Nəticə statusu — defolt `ReconciliationPolicy.ON_ANY_FAILURE` siyasəti ilə —
      kompensasiya uğurlu olsa belə `PENDING_RECONCILIATION` olur, çünki
      audit-kritik zəncirin yarımçıq qalması insan nəzarətini tələb edir.
      Kompensasiyanın FAKTİKİ nəticəsi ayrıca `compensation_outcome` sahəsində
      saxlanılır ki, reconciliation növbəsində prioritet vermək mümkün olsun.
    * `PENDING_RECONCILIATION` statusu `SagaPendingReconciliationEvent` hadisəsi
      ilə Event Bus-a yayımlanır — Faza 3-dəki e-poçt fallback servisi bu
      hadisəyə abunə olur (bax bölmə 7: "heç vaxt sükutla qeyd olunmamalıdır").

İstifadə::

    saga = SagaOrchestrator(event_bus=bus)
    result = await saga.execute(
        name="LeaveVerification",
        steps=[
            SagaStep("update_leave_status", action=..., compensation=...),
            SagaStep("calculate_fine", action=..., compensation=...),
            SagaStep("write_audit_log", action=..., compensation=None),
        ],
        context={"leave_request_id": 42},
    )
    if result.status is SagaStatus.COMPLETED:
        ...
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable  # noqa: UP035

from src.shared.event_bus import DomainEvent, EventBus
from src.shared.exceptions import SagaCompensationError
from src.shared.logger import LogChannel, get_logger

_log = get_logger(__name__)
_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)
_error_log = get_logger(__name__, channel=LogChannel.ERROR)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


# --------------------------------------------------------------------------- #
# Statuslar
# --------------------------------------------------------------------------- #


class SagaStatus(str, Enum):
    """Saga instansiyasının vəziyyəti (DB-dəki `saga_instances.status` ilə eyni)."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    PENDING_RECONCILIATION = "PENDING_RECONCILIATION"
    FAILED = "FAILED"


class CompensationOutcome(str, Enum):
    """Kompensasiya mərhələsinin faktiki nəticəsi (reconciliation prioriteti üçün)."""

    NOT_REQUIRED = "NOT_REQUIRED"
    FULLY_COMPENSATED = "FULLY_COMPENSATED"
    PARTIALLY_COMPENSATED = "PARTIALLY_COMPENSATED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"


class ReconciliationPolicy(str, Enum):
    """`PENDING_RECONCILIATION` statusunun nə vaxt təyin olunacağı.

    ON_ANY_FAILURE:
        Spesifikasiyanın hərfi tələbi — hər hansı addım uğursuz olduqda,
        kompensasiya uğurlu olsa belə status `PENDING_RECONCILIATION` olur.
        Audit-kritik sagalar (icazə/cərimə/audit zənciri) üçün DEFOLT budur.
    ON_COMPENSATION_FAILURE:
        Yalnız kompensasiyanın özü uğursuz olduqda. Audit-kritik OLMAYAN
        köməkçi sagalar (məs. bildiriş göndərmə zənciri) üçün istifadə oluna
        bilər ki, reconciliation növbəsi lazımsız yüklənməsin.
    """

    ON_ANY_FAILURE = "ON_ANY_FAILURE"
    ON_COMPENSATION_FAILURE = "ON_COMPENSATION_FAILURE"


# --------------------------------------------------------------------------- #
# Hadisələr
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class SagaStartedEvent(DomainEvent):
    saga_id: uuid.UUID
    saga_name: str
    step_count: int


@dataclass(frozen=True, kw_only=True)
class SagaCompletedEvent(DomainEvent):
    saga_id: uuid.UUID
    saga_name: str
    duration_ms: float


@dataclass(frozen=True, kw_only=True)
class SagaCompensatedEvent(DomainEvent):
    saga_id: uuid.UUID
    saga_name: str
    failed_step: str
    outcome: CompensationOutcome


@dataclass(frozen=True, kw_only=True)
class SagaPendingReconciliationEvent(DomainEvent):
    """KRİTİK: bu hadisə mütləq e-poçt fallback kanalına düşməlidir (bölmə 7)."""

    saga_id: uuid.UUID
    saga_name: str
    failed_step: str
    error_message: str
    compensation_outcome: CompensationOutcome
    uncompensated_steps: tuple[str, ...]


# --------------------------------------------------------------------------- #
# Addım tərifi
# --------------------------------------------------------------------------- #

SagaContext = dict[str, Any]
StepCallable = Callable[[SagaContext], Any] | Callable[[SagaContext], Awaitable[Any]]


@dataclass(frozen=True)
class SagaStep:
    """Saga zəncirinin bir addımı.

    Attributes:
        name: Addımın unikal, log-a düşən adı.
        action: `context` qəbul edən sync və ya async callable. Qaytardığı dəyər
            `context[f"{name}_result"]` altında saxlanılır.
        compensation: Addımın təsirini geri qaytaran callable. `None` olduqda
            addım "kompensasiya edilə bilməyən" sayılır (məs. audit log yazısı
            heç vaxt silinmir — bax bölmə 4 "orijinal qeyd heç vaxt silinmir").
        retries: Uğursuzluq halında əlavə cəhd sayı (0 = cəhd yoxdur).
        retry_delay_seconds: Cəhdlər arası gözləmə.
        idempotency_key: Təkrar icra qorunması üçün açar (Faza 3 repo-su istifadə edir).
    """

    name: str
    action: StepCallable
    compensation: StepCallable | None = None
    retries: int = 0
    retry_delay_seconds: float = 0.5
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("SagaStep.name boş ola bilməz")
        if not callable(self.action):
            raise TypeError(f"SagaStep '{self.name}': action çağırıla bilən olmalıdır")
        if self.compensation is not None and not callable(self.compensation):
            raise TypeError(f"SagaStep '{self.name}': compensation çağırıla bilən olmalıdır")
        if self.retries < 0:
            raise ValueError(f"SagaStep '{self.name}': retries mənfi ola bilməz")

    @property
    def is_compensatable(self) -> bool:
        return self.compensation is not None


@dataclass
class StepExecution:
    """Bir addımın icra qeydi (audit izi üçün)."""

    step_name: str
    started_at: datetime
    finished_at: datetime | None = None
    succeeded: bool = False
    attempts: int = 0
    error: str | None = None
    compensated: bool = False
    compensation_error: str | None = None


@dataclass
class SagaResult:
    """Saganın yekun nəticəsi."""

    saga_id: uuid.UUID
    saga_name: str
    status: SagaStatus
    compensation_outcome: CompensationOutcome
    context: SagaContext
    executions: list[StepExecution]
    started_at: datetime
    finished_at: datetime
    failed_step: str | None = None
    error: Exception | None = None
    correlation_id: uuid.UUID | None = None

    @property
    def succeeded(self) -> bool:
        return self.status is SagaStatus.COMPLETED

    @property
    def duration_ms(self) -> float:
        return (self.finished_at - self.started_at).total_seconds() * 1000

    @property
    def uncompensated_steps(self) -> tuple[str, ...]:
        """Uğurla icra olunmuş, lakin geri qaytarıla BİLMƏMİŞ addımlar."""
        return tuple(
            execution.step_name
            for execution in self.executions
            if execution.succeeded and not execution.compensated
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "saga_id": str(self.saga_id),
            "saga_name": self.saga_name,
            "status": self.status.value,
            "compensation_outcome": self.compensation_outcome.value,
            "failed_step": self.failed_step,
            "error": str(self.error) if self.error else None,
            "duration_ms": round(self.duration_ms, 2),
            "correlation_id": str(self.correlation_id) if self.correlation_id else None,
            "steps": [
                {
                    "name": execution.step_name,
                    "succeeded": execution.succeeded,
                    "attempts": execution.attempts,
                    "compensated": execution.compensated,
                    "error": execution.error,
                    "compensation_error": execution.compensation_error,
                }
                for execution in self.executions
            ],
        }


# --------------------------------------------------------------------------- #
# Vəziyyət saxlama (Postgres reposu `saga_instances` cədvəli üzərində qurulur)
# --------------------------------------------------------------------------- #


@runtime_checkable
class SagaStateRepository(Protocol):
    """Saga vəziyyətinin davamlı saxlanması üçün port.

    `saga_instances` cədvəli (`schema.sql`) üzərində implementasiya olunur —
    bu, tətbiq saga ortasında çökərsə (crash), yenidən başlayanda yarımçıq
    sagaların aşkarlanmasını mümkün edir.

    QEYD (D6 audit tapıntısı, dövrə 2): «Faza 3-də edilir» ifadəsi ARTIQ
    KEÇƏRSİZ İDDİA idi — cədvəl mövcud olsa da, `composition.py` bu portu
    HEÇ VAXT bağlamırdı, `SagaOrchestrator()` sıfır arqumentlə qurulur və
    `state_repository or InMemorySagaStateRepository()` fallback-ı işə düşürdü
    (aşağıda). Nəticə: hər `session()` çağırışı TƏZƏ, boş yaddaş-daxili dict
    alırdı — `PENDING_RECONCILIATION` qeydləri sessiya bağlananda GEDİRDİ.
    Postgres implementasiyası indi YAZILIR (infra) və `composition.py`-a
    bağlanacaq (ui); `InMemorySagaStateRepository` bundan sonra YALNIZ
    test/fallback məqsədlidir — davamlı backend yoxdursa belə, orkestrator
    partlamamalıdır (bax `_persist()`-in niyə istisnanı UDMASININ əsaslandırması).
    """

    def save(self, result: SagaResult) -> None: ...

    def list_pending_reconciliation(self) -> list[SagaResult]: ...


class InMemorySagaStateRepository:
    """Faza 1 üçün yaddaşda saxlayan sadə implementasiya."""

    def __init__(self) -> None:
        self._store: dict[uuid.UUID, SagaResult] = {}

    def save(self, result: SagaResult) -> None:
        self._store[result.saga_id] = result

    def list_pending_reconciliation(self) -> list[SagaResult]:
        return [
            result
            for result in self._store.values()
            if result.status is SagaStatus.PENDING_RECONCILIATION
        ]

    def get(self, saga_id: uuid.UUID) -> SagaResult | None:
        return self._store.get(saga_id)


# --------------------------------------------------------------------------- #
# Orkestrator
# --------------------------------------------------------------------------- #


class SagaOrchestrator:
    """Compensating-transaction orkestratoru."""

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        state_repository: SagaStateRepository | None = None,
        default_policy: ReconciliationPolicy = ReconciliationPolicy.ON_ANY_FAILURE,
        policy_resolver: Callable[[str], ReconciliationPolicy] | None = None,
    ) -> None:
        """
        Args:
            policy_resolver: Saga adına görə siyasət təyin edən funksiya.
                `src.shared.saga_policies.policy_for` bura verilir (kompozisiya
                kökündə, `main.build_container`). Dövri idxaldan qaçmaq üçün
                orkestrator reyestri BİRBAŞA idxal etmir. Verilmədikdə
                `default_policy` (ən sərt) tətbiq olunur.
        """
        self._event_bus = event_bus
        self._state_repository = state_repository or InMemorySagaStateRepository()
        self._default_policy = default_policy
        self._policy_resolver = policy_resolver

    # ------------------------------ icra ---------------------------------- #

    async def execute(
        self,
        *,
        name: str,
        steps: list[SagaStep],
        context: SagaContext | None = None,
        correlation_id: uuid.UUID | None = None,
        tenant_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
        policy: ReconciliationPolicy | None = None,
    ) -> SagaResult:
        """Saga zəncirini icra edir və nəticəni qaytarır.

        Bu metod ISTISNA ATMIR — bütün nəticələr `SagaResult.status` üzərindən
        bildirilir ki, çağıran tərəf yarımçıq vəziyyəti səhvən "uğur" kimi
        qəbul etməsin.
        """
        if not steps:
            raise ValueError("Saga ən azı bir addımdan ibarət olmalıdır")

        seen: set[str] = set()
        for step in steps:
            if step.name in seen:
                raise ValueError(f"Saga addım adı təkrarlanır: '{step.name}'")
            seen.add(step.name)

        # Prioritet: açıq arqument → reyestr → ən sərt defolt.
        if policy is not None:
            effective_policy = policy
        elif self._policy_resolver is not None:
            effective_policy = self._policy_resolver(name)
        else:
            effective_policy = self._default_policy
        saga_id = uuid.uuid4()
        correlation_id = correlation_id or saga_id
        started_at = _utc_now()
        working_context: SagaContext = dict(context or {})
        working_context.setdefault("saga_id", saga_id)
        working_context.setdefault("correlation_id", correlation_id)

        executions: list[StepExecution] = []
        completed_steps: list[SagaStep] = []

        _audit_log.info(
            "SAGA_STARTED",
            extra={
                "saga_id": str(saga_id),
                "saga_name": name,
                "correlation_id": str(correlation_id),
                "step_count": len(steps),
            },
        )
        await self._emit(
            SagaStartedEvent(
                saga_id=saga_id,
                saga_name=name,
                step_count=len(steps),
                correlation_id=correlation_id,
                tenant_id=tenant_id,
                actor_id=actor_id,
            )
        )

        for step in steps:
            execution = StepExecution(step_name=step.name, started_at=_utc_now())
            executions.append(execution)
            try:
                value = await self._run_with_retries(step, working_context, execution)
            except Exception as exc:
                execution.finished_at = _utc_now()
                execution.error = f"{type(exc).__name__}: {exc}"
                _error_log.exception(
                    "SAGA_STEP_FAILED",
                    extra={
                        "saga_id": str(saga_id),
                        "saga_name": name,
                        "step": step.name,
                        "attempts": execution.attempts,
                    },
                )
                return await self._compensate_and_finalize(
                    saga_id=saga_id,
                    name=name,
                    steps_to_compensate=completed_steps,
                    executions=executions,
                    context=working_context,
                    started_at=started_at,
                    failed_step=step.name,
                    error=exc,
                    correlation_id=correlation_id,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    policy=effective_policy,
                )

            execution.finished_at = _utc_now()
            execution.succeeded = True
            working_context[f"{step.name}_result"] = value
            completed_steps.append(step)
            _log.debug(
                "SAGA_STEP_OK",
                extra={"saga_id": str(saga_id), "step": step.name},
            )

        finished_at = _utc_now()
        result = SagaResult(
            saga_id=saga_id,
            saga_name=name,
            status=SagaStatus.COMPLETED,
            compensation_outcome=CompensationOutcome.NOT_REQUIRED,
            context=working_context,
            executions=executions,
            started_at=started_at,
            finished_at=finished_at,
            correlation_id=correlation_id,
        )
        self._persist(result)
        _audit_log.info("SAGA_COMPLETED", extra=result.to_dict())
        await self._emit(
            SagaCompletedEvent(
                saga_id=saga_id,
                saga_name=name,
                duration_ms=result.duration_ms,
                correlation_id=correlation_id,
                tenant_id=tenant_id,
                actor_id=actor_id,
            )
        )
        return result

    async def _run_with_retries(
        self, step: SagaStep, context: SagaContext, execution: StepExecution
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(step.retries + 1):
            execution.attempts = attempt + 1
            try:
                return await self._invoke(step.action, context)
            except Exception as exc:
                last_error = exc
                if attempt < step.retries:
                    _log.warning(
                        "SAGA_STEP_RETRY",
                        extra={
                            "step": step.name,
                            "attempt": execution.attempts,
                            "error": str(exc),
                        },
                    )
                    await asyncio.sleep(step.retry_delay_seconds)
        assert last_error is not None
        raise last_error

    # -------------------------- kompensasiya ------------------------------- #

    async def _compensate_and_finalize(
        self,
        *,
        saga_id: uuid.UUID,
        name: str,
        steps_to_compensate: list[SagaStep],
        executions: list[StepExecution],
        context: SagaContext,
        started_at: datetime,
        failed_step: str,
        error: Exception,
        correlation_id: uuid.UUID,
        tenant_id: uuid.UUID | None,
        actor_id: uuid.UUID | None,
        policy: ReconciliationPolicy,
    ) -> SagaResult:
        """Kompensasiyaları TƏRS sırada icra edir və yekun statusu təyin edir."""
        executions_by_name = {execution.step_name: execution for execution in executions}
        compensation_failed = False
        compensated_count = 0
        compensatable_count = 0

        for step in reversed(steps_to_compensate):
            execution = executions_by_name[step.name]
            if step.compensation is None:
                # Qəsdən kompensasiya edilməyən addım (məs. audit yazısı).
                _log.info(
                    "SAGA_STEP_NOT_COMPENSATABLE",
                    extra={"saga_id": str(saga_id), "step": step.name},
                )
                continue

            compensatable_count += 1
            try:
                await self._invoke(step.compensation, context)
                execution.compensated = True
                compensated_count += 1
                _audit_log.info(
                    "SAGA_STEP_COMPENSATED",
                    extra={"saga_id": str(saga_id), "step": step.name},
                )
            except Exception as exc:
                compensation_failed = True
                execution.compensation_error = f"{type(exc).__name__}: {exc}"
                _error_log.exception(
                    "SAGA_COMPENSATION_FAILED",
                    extra={"saga_id": str(saga_id), "step": step.name},
                )

        if compensatable_count == 0:
            outcome = CompensationOutcome.NOT_REQUIRED
        elif compensation_failed:
            outcome = (
                CompensationOutcome.COMPENSATION_FAILED
                if compensated_count == 0
                else CompensationOutcome.PARTIALLY_COMPENSATED
            )
        else:
            outcome = CompensationOutcome.FULLY_COMPENSATED

        if policy is ReconciliationPolicy.ON_ANY_FAILURE or outcome in (
            CompensationOutcome.COMPENSATION_FAILED,
            CompensationOutcome.PARTIALLY_COMPENSATED,
        ):
            status = SagaStatus.PENDING_RECONCILIATION
        else:
            status = SagaStatus.COMPENSATED

        finished_at = _utc_now()
        result = SagaResult(
            saga_id=saga_id,
            saga_name=name,
            status=status,
            compensation_outcome=outcome,
            context=context,
            executions=executions,
            started_at=started_at,
            finished_at=finished_at,
            failed_step=failed_step,
            error=error,
            correlation_id=correlation_id,
        )
        self._persist(result)

        if status is SagaStatus.PENDING_RECONCILIATION:
            _audit_log.critical("SAGA_PENDING_RECONCILIATION", extra=result.to_dict())
            await self._emit(
                SagaPendingReconciliationEvent(
                    saga_id=saga_id,
                    saga_name=name,
                    failed_step=failed_step,
                    error_message=f"{type(error).__name__}: {error}",
                    compensation_outcome=outcome,
                    uncompensated_steps=result.uncompensated_steps,
                    correlation_id=correlation_id,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                )
            )
        else:
            _audit_log.warning("SAGA_COMPENSATED", extra=result.to_dict())
            await self._emit(
                SagaCompensatedEvent(
                    saga_id=saga_id,
                    saga_name=name,
                    failed_step=failed_step,
                    outcome=outcome,
                    correlation_id=correlation_id,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                )
            )

        return result

    # ------------------------------ köməkçi -------------------------------- #

    @staticmethod
    async def _invoke(func: StepCallable, context: SagaContext) -> Any:
        """Sync və ya async callable-ı vahid şəkildə çağırır."""
        if inspect.iscoroutinefunction(func):
            return await func(context)
        result = func(context)
        if inspect.isawaitable(result):
            return await result
        return result

    async def _emit(self, event: DomainEvent) -> None:
        if self._event_bus is None:
            return
        try:
            await self._event_bus.publish(event)
        except Exception:
            _error_log.exception("SAGA_EVENT_PUBLISH_FAILED", extra={"event": event.event_name})

    def _persist(self, result: SagaResult) -> None:
        """Saga nəticəsini davamlı yaddaşa yazır — İSTİSNA UDULUR, ƏMƏLİYYAT
        GERİ QAYTARILMIR.

        ──────────────────────────────────────────────────────────────────────
        QƏRAR (dövrə 2 debatı, D6): NİYƏ BU, `AuditTrail.record()` (CLAUDE.md
        §5, "audit istisna udmur") QAYDASINA TABE DEYİL
        ──────────────────────────────────────────────────────────────────────
        DB audit sətri saga-nın ÖZ ADDIMIDIR (`step_write_audit` və s.) —
        uğursuz olsa bütün zəncir kompensasiyaya düşür, çünki o, ƏMƏLİYYATIN
        QANUNİ NƏTİCƏSİDİR. `_persist()` isə saga ARTIQ öz yekun statusuna
        (`COMPLETED`/`COMPENSATED`/`PENDING_RECONCILIATION`) çatdıqdan SONRA
        çağırılır — yazdığı sətir ƏMƏLİYYATIN NƏTİCƏSİ DEYİL, orkestratorun
        ÖZ NƏZARƏT jurnalıdır (crash-bərpa + HR/Root uzlaşma ekranı üçün).

        İstisnanı ötürsəydik: artıq COMMIT olunmuş (audit sətri DAXİL) bir
        leave-verification/fine əməliyyatı YALNIZ bu İKİNCİ DƏRƏCƏLİ yazı
        uğursuz olduğu üçün tam geri qaytarılardı — real, artıq audit-lənmiş
        bir əməliyyatı DB nasazlığı anında itirmək, uzlaşma qeydini
        itirməkdən DAHA PİSDİR. Ona görə istisna BURADA udulur — `_emit()`
        ilə EYNİ naxış (yuxarıda), fərqli səbəblə: orada hadisə telemetriyadır,
        burada isə "artıq baş vermiş" bir NƏTİCƏNİN qeydidir.

        BUNUNLA BELƏ `PENDING_RECONCILIATION` OPERATORUN YEGANƏ İZİ ola bilər
        (D6: `saga_instances` reposu bağlanmayanda `InMemorySagaStateRepository`
        sessiya bitəndə itir) — ona görə MƏHZ bu statusda uğursuzluq `critical`
        səviyyəsində loglanır ki, "həm saga, həm onun qeydi" ikiqat itkisi
        monitorinqdə İTMƏSİN. `execute()` bu statusda HƏR HALDA ayrıca
        `_audit_log.critical("SAGA_PENDING_RECONCILIATION", ...)` yazır (bax
        yuxarı) — bu metodun uğursuzluğundan ASILI OLMAYAN, ayrı fayl-kanalı izi.
        """
        try:
            self._state_repository.save(result)
        except Exception:
            if result.status is SagaStatus.PENDING_RECONCILIATION:
                _error_log.critical(
                    "SAGA_STATE_PERSIST_FAILED_FOR_PENDING_RECONCILIATION",
                    extra={"saga_id": str(result.saga_id), "saga_name": result.saga_name},
                    exc_info=True,
                )
            else:
                _error_log.exception(
                    "SAGA_STATE_PERSIST_FAILED", extra={"saga_id": str(result.saga_id)}
                )

    # --------------------------- reconciliation ---------------------------- #

    def pending_reconciliation(self) -> list[SagaResult]:
        """İnsan müdaxiləsi gözləyən sagaların siyahısı (HR/Root ekranı üçün)."""
        return self._state_repository.list_pending_reconciliation()

    @staticmethod
    def raise_for_status(result: SagaResult) -> None:
        """Çağıran tərəf istisna semantikası istəyirsə istifadə edir."""
        if result.status is SagaStatus.PENDING_RECONCILIATION:
            raise SagaCompensationError(
                f"Saga '{result.saga_name}' PENDING_RECONCILIATION statusundadır "
                f"(uğursuz addım: {result.failed_step})",
                context=result.to_dict(),
            )
