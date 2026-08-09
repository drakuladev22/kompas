"""Qlobal pytest konfiqurasiyası və fixture-lar.

`pytest-qt` karkası burada qurulur (spesifikasiya bölmə 1: E2E testlər GUI
səviyyəsində, hər PR-da CI-da işə düşməlidir). Faza 1-də hələ GUI yoxdur, ona
görə Qt fixture-ları `qt` marker-i ilə işarələnib və PySide6 quraşdırılmayıbsa
avtomatik `skip` olunur — CI erkən fazalarda qırmızı olmasın.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

# `src` paketinin import edilə bilməsi üçün layihə kökü sys.path-a əlavə olunur.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.infrastructure.security.encryption import (  # noqa: E402
    EncryptionService,
    KeyMaterial,
    generate_key,
)
from src.infrastructure.security.hashing import (  # noqa: E402
    HashingService,
    PepperProvider,
    generate_pepper,
)
from src.shared.di_container import DIContainer, reset_container  # noqa: E402
from src.shared.event_bus import EventBus, reset_event_bus  # noqa: E402
from src.shared.logger import configure_logging  # noqa: E402
from src.shared.saga_orchestrator import (  # noqa: E402
    InMemorySagaStateRepository,
    SagaOrchestrator,
)

# --------------------------------------------------------------------------- #
# Marker qeydiyyatı
# --------------------------------------------------------------------------- #


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "unit: sürətli, izolyasiya olunmuş domen testləri")
    config.addinivalue_line("markers", "integration: DB/şəbəkə tələb edən testlər")
    config.addinivalue_line("markers", "e2e: pytest-qt ilə uçdan-uca GUI ssenariləri")
    config.addinivalue_line("markers", "qt: PySide6 tələb edir (yoxdursa skip)")
    config.addinivalue_line("markers", "slow: uzun sürən testlər")


# --------------------------------------------------------------------------- #
# Ümumi fixture-lar
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _isolated_logs(tmp_path: Path) -> Iterator[Path]:
    """Hər test öz müvəqqəti log qovluğuna yazır — testlər bir-birini çirkləndirmir."""
    log_dir = tmp_path / "logs"
    configure_logging(log_dir=log_dir, console=False, force=True)
    yield log_dir


@pytest.fixture(autouse=True)
def _reset_globals() -> Iterator[None]:
    """Qlobal singleton-ları hər testdən əvvəl/sonra sıfırlayır."""
    reset_event_bus()
    reset_container()
    yield
    reset_event_bus()
    reset_container()


@pytest.fixture
def event_bus() -> EventBus:
    """Təmiz, izolyasiya olunmuş event bus."""
    return EventBus()


@pytest.fixture
def strict_event_bus() -> EventBus:
    """Handler xətalarını udmayan bus — testdə xətanı görünən etmək üçün."""
    return EventBus(raise_on_handler_error=True)


@pytest.fixture
def container() -> DIContainer:
    return DIContainer()


@pytest.fixture
def saga_repository() -> InMemorySagaStateRepository:
    return InMemorySagaStateRepository()


@pytest.fixture
def saga(event_bus: EventBus, saga_repository: InMemorySagaStateRepository) -> SagaOrchestrator:
    return SagaOrchestrator(event_bus=event_bus, state_repository=saga_repository)


@pytest.fixture
def fernet_key() -> str:
    return generate_key()


@pytest.fixture
def encryption_service(fernet_key: str, monkeypatch: pytest.MonkeyPatch) -> EncryptionService:
    """Env-əsaslı açarla qurulmuş şifrələmə servisi."""
    monkeypatch.setenv("KOMPASOS_FERNET_KEY", fernet_key)
    monkeypatch.delenv("KOMPASOS_FERNET_KEY_PREVIOUS", raising=False)
    return EncryptionService()


class StaticKeyProvider:
    """Testlər üçün sabit açar provayderi."""

    name = "static"

    def __init__(self, material: KeyMaterial) -> None:
        self._material = material

    def load(self) -> KeyMaterial:
        return self._material


@pytest.fixture
def static_key_provider_factory() -> type[StaticKeyProvider]:
    return StaticKeyProvider


# --------------------------------------------------------------------------- #
# Hash-ləmə
# --------------------------------------------------------------------------- #

#: Argon2 testdə SÜRƏTLİ parametrlərlə işləyir — istehsalat dəyərləri
#: (t=3, m=64 MiB, p=4) hər hash üçün ~100 ms tələb edir və test dəstini
#: dəqiqələrlə uzadardı. Alqoritm (Argon2id) və məntiq eynidir.
FAST_ARGON2 = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


@pytest.fixture
def pepper() -> str:
    return generate_pepper()


@pytest.fixture
def hashing_service(pepper: str, monkeypatch: pytest.MonkeyPatch) -> HashingService:
    """Pepper konfiqurasiya edilmiş, sürətli parametrli hash servisi."""
    monkeypatch.setenv("KOMPASOS_HASH_PEPPER", pepper)
    return HashingService(**FAST_ARGON2)


@pytest.fixture
def hashing_service_no_pepper(monkeypatch: pytest.MonkeyPatch) -> HashingService:
    """Pepper OLMADAN — deqradasiya rejimini yoxlamaq üçün."""
    monkeypatch.delenv("KOMPASOS_HASH_PEPPER", raising=False)
    return HashingService(pepper_provider=PepperProvider(), **FAST_ARGON2)


# --------------------------------------------------------------------------- #
# pytest-qt karkası (Faza 4-də GUI gələndə aktivləşir)
# --------------------------------------------------------------------------- #


def _pyside6_available() -> bool:
    try:
        import PySide6  # noqa: F401
    except ImportError:
        return False
    return True


PYSIDE6_AVAILABLE = _pyside6_available()

requires_qt = pytest.mark.skipif(
    not PYSIDE6_AVAILABLE,
    reason="PySide6 quraşdırılmayıb — GUI testləri Faza 4-də aktivləşir",
)


@pytest.fixture(scope="session", autouse=True)
def _qt_headless_env() -> None:
    """CI-da (Linux runner) Qt üçün offscreen platform təyin edir."""
    if os.environ.get("CI") and not os.environ.get("QT_QPA_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture
def qt_app(qapp):  # type: ignore[no-untyped-def]
    """`pytest-qt`-nin `qapp` fixture-ı üzərində nazik örtük.

    Faza 4-dən etibarən burada KompasOS Dizayn Sistemi (dark/light tema) tətbiq
    olunacaq ki, E2E testlər real tema ilə işləsin.
    """
    return qapp
