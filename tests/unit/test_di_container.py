"""DI Container testləri."""

from __future__ import annotations

import pytest

from src.shared.di_container import DIContainer, Lifetime, get_container, reset_container
from src.shared.exceptions import (
    CircularDependencyError,
    DependencyNotRegisteredError,
    DuplicateRegistrationError,
)

pytestmark = pytest.mark.unit


class Repository:
    def __init__(self) -> None:
        self.calls = 0


class Service:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository


class UseCase:
    def __init__(self, service: Service) -> None:
        self.service = service


class Disposable:
    def __init__(self) -> None:
        self.closed = False

    def dispose(self) -> None:
        self.closed = True


def test_transient_creates_new_instance(container: DIContainer) -> None:
    container.register(Repository)
    assert container.resolve(Repository) is not container.resolve(Repository)


def test_singleton_returns_same_instance(container: DIContainer) -> None:
    container.register_singleton(Repository)
    assert container.resolve(Repository) is container.resolve(Repository)


def test_register_instance(container: DIContainer) -> None:
    instance = Repository()
    container.register_instance(Repository, instance)
    assert container.resolve(Repository) is instance


def test_auto_wiring_resolves_dependency_graph(container: DIContainer) -> None:
    container.register_singleton(Repository)
    container.register(Service)
    container.register(UseCase)

    use_case = container.resolve(UseCase)

    assert isinstance(use_case.service, Service)
    assert isinstance(use_case.service.repository, Repository)


def test_missing_dependency_raises(container: DIContainer) -> None:
    container.register(Service)  # Repository qeydiyyatdan keçməyib
    with pytest.raises(DependencyNotRegisteredError):
        container.resolve(Service)


def test_unregistered_type_raises(container: DIContainer) -> None:
    with pytest.raises(DependencyNotRegisteredError):
        container.resolve(Repository)


def test_circular_dependency_detected(container: DIContainer) -> None:
    class A:
        def __init__(self, b: B) -> None:
            self.b = b

    class B:
        def __init__(self, a: A) -> None:
            self.a = a

    # get_type_hints üçün adlar modul səviyyəsində görünməlidir
    globals()["A"], globals()["B"] = A, B
    container.register(A)
    container.register(B)

    with pytest.raises(CircularDependencyError) as exc_info:
        container.resolve(A)

    assert "→" in str(exc_info.value)


def test_duplicate_registration_blocked(container: DIContainer) -> None:
    container.register(Repository)
    with pytest.raises(DuplicateRegistrationError):
        container.register(Repository)

    container.register(Repository, override=True)  # override ilə olar


def test_factory_registration(container: DIContainer) -> None:
    def make_repository() -> Repository:
        return Repository()

    container.register_factory(Repository, make_repository, lifetime=Lifetime.SINGLETON)
    assert container.resolve(Repository) is container.resolve(Repository)


def test_factory_receives_container(container: DIContainer) -> None:
    container.register_singleton(Repository)
    container.register_factory(Service, lambda c: Service(c.resolve(Repository)))

    service = container.resolve(Service)
    assert isinstance(service.repository, Repository)


def test_scoped_lifetime_isolated_per_scope(container: DIContainer) -> None:
    container.register_scoped(Repository)

    with container.scope() as scope_one:
        first = scope_one.resolve(Repository)
        assert scope_one.resolve(Repository) is first

    with container.scope() as scope_two:
        second = scope_two.resolve(Repository)

    assert first is not second


def test_scope_disposes_instances(container: DIContainer) -> None:
    container.register_scoped(Disposable)

    with container.scope() as scope:
        instance = scope.resolve(Disposable)
        assert instance.closed is False

    assert instance.closed is True


def test_default_parameter_is_not_required(container: DIContainer) -> None:
    class WithDefault:
        def __init__(self, timeout: int = 45) -> None:
            self.timeout = timeout

    container.register(WithDefault)
    assert container.resolve(WithDefault).timeout == 45


def test_is_registered(container: DIContainer) -> None:
    assert container.is_registered(Repository) is False
    container.register(Repository)
    assert container.is_registered(Repository) is True


def test_get_container_is_singleton() -> None:
    reset_container()
    assert get_container() is get_container()
    reset_container()
