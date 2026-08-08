"""Dependency Injection Container (spesifikasiya bölmə 1).

Məqsəd: domain/application qatları konkret infrastruktur siniflərini deyil,
YALNIZ interfeys (Protocol/ABC) tiplərini tanısın. Konkret implementasiya
kompozisiya kökündə (`bootstrap`) qeydiyyata alınır.

Dəstəklənən ömür (lifetime) modelləri:
    SINGLETON — proses boyu tək nüsxə (məs. `EventBus`, `EncryptionService`)
    SCOPED    — scope daxilində tək nüsxə (məs. bir DB tranzaksiyası/istək)
    TRANSIENT — hər `resolve()` çağırışında yeni nüsxə

Xüsusiyyətlər:
    * Konstruktor tip-annotasiyalarına görə avtomatik auto-wiring.
    * Dövri (circular) asılılıq aşkarlanması — aydın xəta zənciri ilə.
    * Thread-safe; singleton yaradılması double-checked locking ilə.

İstifadə::

    container = DIContainer()
    container.register_instance(EventBus, get_event_bus())
    container.register(IEmployeeRepository, SupabaseEmployeeRepository)
    repo = container.resolve(IEmployeeRepository)
"""

from __future__ import annotations

import inspect
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from enum import Enum
from typing import Any, TypeVar, get_type_hints

from src.shared.exceptions import (
    CircularDependencyError,
    DependencyNotRegisteredError,
    DuplicateRegistrationError,
)
from src.shared.logger import get_logger

_log = get_logger(__name__)

T = TypeVar("T")


class Lifetime(str, Enum):
    """Qeydiyyatın ömür modeli."""

    SINGLETON = "singleton"
    SCOPED = "scoped"
    TRANSIENT = "transient"


class _Registration:
    __slots__ = ("factory", "implementation", "instance", "lifetime", "service_type")

    def __init__(
        self,
        *,
        service_type: type[Any],
        implementation: type[Any] | None,
        factory: Callable[..., Any] | None,
        lifetime: Lifetime,
        instance: Any | None = None,
    ) -> None:
        self.service_type = service_type
        self.implementation = implementation
        self.factory = factory
        self.lifetime = lifetime
        self.instance = instance


class DIContainer:
    """Sadə, tip-təhlükəsiz DI konteyner."""

    def __init__(self, *, parent: DIContainer | None = None) -> None:
        self._registrations: dict[type[Any], _Registration] = {}
        self._singletons: dict[type[Any], Any] = {}
        self._scoped_instances: dict[type[Any], Any] = {}
        self._lock = threading.RLock()
        self._parent = parent
        #: Dövr aşkarlanması thread-lokal olmalıdır (paralel resolve üçün).
        self._resolution_state = threading.local()

    # --------------------------- qeydiyyat -------------------------------- #

    def register(
        self,
        service_type: type[T],
        implementation: type[T] | None = None,
        *,
        lifetime: Lifetime = Lifetime.TRANSIENT,
        override: bool = False,
    ) -> DIContainer:
        """Tip → implementasiya qeydiyyatı.

        Args:
            service_type: Abstraksiya (Protocol/ABC) və ya konkret sinif.
            implementation: Konkret sinif. `None` olduqda `service_type`
                özü implementasiya kimi qəbul olunur.
            lifetime: Ömür modeli.
            override: Mövcud qeydiyyatın üzərinə yazmağa icazə.
        """
        impl = implementation if implementation is not None else service_type
        if not inspect.isclass(impl):
            raise TypeError(f"implementation sinif olmalıdır, alındı: {impl!r}")

        self._guard_duplicate(service_type, override=override)
        with self._lock:
            self._registrations[service_type] = _Registration(
                service_type=service_type,
                implementation=impl,
                factory=None,
                lifetime=lifetime,
            )
        _log.debug(
            "DI_REGISTERED",
            extra={
                "service": service_type.__name__,
                "implementation": impl.__name__,
                "lifetime": lifetime.value,
            },
        )
        return self

    def register_singleton(
        self,
        service_type: type[T],
        implementation: type[T] | None = None,
        *,
        override: bool = False,
    ) -> DIContainer:
        """`Lifetime.SINGLETON` ilə qeydiyyat üçün qısayol."""
        return self.register(
            service_type,
            implementation,
            lifetime=Lifetime.SINGLETON,
            override=override,
        )

    def register_scoped(
        self,
        service_type: type[T],
        implementation: type[T] | None = None,
        *,
        override: bool = False,
    ) -> DIContainer:
        """`Lifetime.SCOPED` ilə qeydiyyat üçün qısayol."""
        return self.register(
            service_type, implementation, lifetime=Lifetime.SCOPED, override=override
        )

    def register_factory(
        self,
        service_type: type[T],
        factory: Callable[..., T],
        *,
        lifetime: Lifetime = Lifetime.TRANSIENT,
        override: bool = False,
    ) -> DIContainer:
        """Fabrik funksiya ilə qeydiyyat.

        Fabrik arqumentsiz və ya tək `DIContainer` arqumenti ilə çağırıla bilər.
        """
        if not callable(factory):
            raise TypeError("factory çağırıla bilən olmalıdır")

        self._guard_duplicate(service_type, override=override)
        with self._lock:
            self._registrations[service_type] = _Registration(
                service_type=service_type,
                implementation=None,
                factory=factory,
                lifetime=lifetime,
            )
        return self

    def register_instance(
        self, service_type: type[T], instance: T, *, override: bool = False
    ) -> DIContainer:
        """Hazır nüsxəni singleton kimi qeydiyyata alır."""
        self._guard_duplicate(service_type, override=override)
        with self._lock:
            self._registrations[service_type] = _Registration(
                service_type=service_type,
                implementation=None,
                factory=None,
                lifetime=Lifetime.SINGLETON,
                instance=instance,
            )
            self._singletons[service_type] = instance
        return self

    def _guard_duplicate(self, service_type: type[Any], *, override: bool) -> None:
        with self._lock:
            if service_type in self._registrations and not override:
                raise DuplicateRegistrationError(
                    f"{service_type.__name__} artıq qeydiyyatdan keçib "
                    f"(üzərinə yazmaq üçün override=True verin)",
                    context={"service": service_type.__name__},
                )

    def is_registered(self, service_type: type[Any]) -> bool:
        with self._lock:
            if service_type in self._registrations:
                return True
        return self._parent.is_registered(service_type) if self._parent else False

    # ----------------------------- həlletmə -------------------------------- #

    def resolve(self, service_type: type[T]) -> T:
        """Tipi həll edir (lazım olsa asılılıqları rekursiv qurur)."""
        stack: list[type[Any]] = getattr(self._resolution_state, "stack", None) or []
        if service_type in stack:
            chain = " → ".join(t.__name__ for t in [*stack, service_type])
            raise CircularDependencyError(
                f"Dövri asılılıq aşkarlandı: {chain}",
                context={"chain": chain},
            )

        self._resolution_state.stack = [*stack, service_type]
        try:
            return self._resolve_internal(service_type)
        finally:
            self._resolution_state.stack = stack

    def _resolve_internal(self, service_type: type[T]) -> T:
        with self._lock:
            registration = self._registrations.get(service_type)

        if registration is None:
            if self._parent is not None:
                return self._parent.resolve(service_type)
            raise DependencyNotRegisteredError(
                f"{getattr(service_type, '__name__', service_type)} "
                f"DI konteynerdə qeydiyyatdan keçməyib",
                context={"service": getattr(service_type, "__name__", str(service_type))},
            )

        if registration.lifetime is Lifetime.SINGLETON:
            with self._lock:
                if service_type in self._singletons:
                    return self._singletons[service_type]  # type: ignore[no-any-return]
            instance = self._create(registration)
            with self._lock:
                # Double-checked: başqa thread bu arada yaratmış ola bilər.
                if service_type not in self._singletons:
                    self._singletons[service_type] = instance
                return self._singletons[service_type]  # type: ignore[no-any-return]

        if registration.lifetime is Lifetime.SCOPED:
            with self._lock:
                if service_type in self._scoped_instances:
                    return self._scoped_instances[service_type]  # type: ignore[no-any-return]
            instance = self._create(registration)
            with self._lock:
                self._scoped_instances.setdefault(service_type, instance)
                return self._scoped_instances[service_type]  # type: ignore[no-any-return]

        return self._create(registration)  # type: ignore[no-any-return]

    def _create(self, registration: _Registration) -> Any:
        if registration.instance is not None:
            return registration.instance

        if registration.factory is not None:
            signature = inspect.signature(registration.factory)
            if len(signature.parameters) == 0:
                return registration.factory()
            return registration.factory(self)

        implementation = registration.implementation
        assert implementation is not None
        return self._auto_wire(implementation)

    def _auto_wire(self, implementation: type[Any]) -> Any:
        """Konstruktor tip-annotasiyalarına görə asılılıqları doldurur."""
        try:
            signature = inspect.signature(implementation.__init__)
        except (TypeError, ValueError):  # pragma: no cover - builtin tiplər
            return implementation()

        try:
            hints = get_type_hints(implementation.__init__)
        except Exception:
            hints = {}

        kwargs: dict[str, Any] = {}
        for name, parameter in signature.parameters.items():
            if name == "self" or parameter.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue

            annotation = hints.get(name, parameter.annotation)
            if annotation is inspect.Parameter.empty:
                if parameter.default is inspect.Parameter.empty:
                    raise DependencyNotRegisteredError(
                        f"{implementation.__name__}.__init__ parametri '{name}' "
                        f"tip annotasiyasına malik deyil — auto-wiring mümkün deyil",
                        context={"implementation": implementation.__name__, "param": name},
                    )
                continue

            if inspect.isclass(annotation) and self.is_registered(annotation):
                kwargs[name] = self.resolve(annotation)
            elif parameter.default is inspect.Parameter.empty:
                raise DependencyNotRegisteredError(
                    f"{implementation.__name__} üçün '{name}: "
                    f"{getattr(annotation, '__name__', annotation)}' asılılığı "
                    f"qeydiyyatdan keçməyib",
                    context={
                        "implementation": implementation.__name__,
                        "param": name,
                        "annotation": str(annotation),
                    },
                )

        return implementation(**kwargs)

    # ------------------------------- scope --------------------------------- #

    def create_scope(self) -> DIContainer:
        """Yeni scope yaradır — `Lifetime.SCOPED` qeydiyyatları izolyasiya olunur."""
        child = DIContainer(parent=self)
        with self._lock:
            child._registrations = dict(self._registrations)
            child._singletons = self._singletons  # singleton-lar paylaşılır
        return child

    @contextmanager
    def scope(self) -> Iterator[DIContainer]:
        """`with container.scope() as scoped:` üçün kontekst meneceri."""
        child = self.create_scope()
        try:
            yield child
        finally:
            child.dispose_scope()

    def dispose_scope(self) -> None:
        """Scope-lu nüsxələri buraxır (varsa `close()`/`dispose()` çağırır)."""
        with self._lock:
            instances = list(self._scoped_instances.values())
            self._scoped_instances.clear()
        for instance in instances:
            for method_name in ("dispose", "close"):
                method = getattr(instance, method_name, None)
                if callable(method):
                    try:
                        method()
                    except Exception:
                        _log.exception(
                            "DI_SCOPE_DISPOSE_FAILED",
                            extra={"instance": type(instance).__name__},
                        )
                    break

    def clear(self) -> None:
        """Bütün qeydiyyat və nüsxələri silir — əsasən testlər üçün."""
        with self._lock:
            self._registrations.clear()
            self._singletons.clear()
            self._scoped_instances.clear()


# --------------------------------------------------------------------------- #
# Qlobal kompozisiya kökü
# --------------------------------------------------------------------------- #

_container_singleton: DIContainer | None = None
_container_lock = threading.Lock()


def get_container() -> DIContainer:
    """Tətbiqin qlobal DI konteynerini qaytarır (lazy, thread-safe)."""
    global _container_singleton
    if _container_singleton is None:
        with _container_lock:
            if _container_singleton is None:
                _container_singleton = DIContainer()
    return _container_singleton


def reset_container() -> None:
    """Qlobal konteyneri sıfırlayır — YALNIZ testlər üçün."""
    global _container_singleton
    with _container_lock:
        _container_singleton = None
