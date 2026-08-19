"""Bot dəyişdirilməsi SÖNDÜRÜLMÜŞ inteqrasiyanı geri qaytarmır — TG-1.

──────────────────────────────────────────────────────────────────────────────
QÜSUR NƏ İDİ
──────────────────────────────────────────────────────────────────────────────
`TelegramConfigUseCase.save()` `is_active` parametrini `True` defoltu ilə
alırdı, ROOT panelinin «Botu Dəyiş» yolu isə onu ÜMUMİYYƏTLƏ ötürmür
(`controllers/root_control._on_telegram_saved` yalnız token və chat ID
göndərir).

Nəticə sükutlu idi: Root inteqrasiyanı QƏSDƏN söndürür
(`set_active(False)`), bir müddət sonra botu dəyişir — və inteqrasiya
ÖZ-ÖZÜNƏ yenidən aktivləşir. İstifadəçi bunu yalnız Telegram kanalına mesaj
düşəndə görür, yəni səhvin nəticəsi kanaldan KƏNARDA (müştərinin qrupunda)
üzə çıxır.

Bir ayarın dəyişməsi BAŞQA ayarı geri qaytarmamalıdır — defolt indi
«vəziyyətə toxunma»dır.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import RolePriority, SystemRole
from src.domain.value_objects.identifiers import EmployeeId, PositionId, TenantId

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
TENANT = TenantId(uuid.uuid4())
TOKEN = "1234567890:AAH" + "x" * 32


@dataclass
class _StoredSettings:
    bot_token: str
    chat_id: str
    is_active: bool

    @property
    def is_usable(self) -> bool:
        return bool(self.bot_token and self.chat_id and self.is_active)


class _Repo:
    """Yalnız `is_active`-in necə yazıldığını izləyir."""

    def __init__(self, stored: _StoredSettings | None) -> None:
        self.stored = stored
        self.saved_active: list[bool] = []

    def load(self, tenant_id: TenantId) -> _StoredSettings | None:
        return self.stored

    def describe(self, tenant_id: TenantId) -> Any:
        return None

    def save(self, tenant_id: TenantId, **kwargs: Any) -> None:
        self.saved_active.append(bool(kwargs["is_active"]))

    def set_active(self, tenant_id: TenantId, **kwargs: Any) -> None:
        return None

    def archive(self, tenant_id: TenantId, **kwargs: Any) -> bool:
        return False


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Audit:
    def record(self, **_kwargs: Any) -> None:
        return None


def _root() -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=SystemRole.ROOT.value,
        name_az="Root",
        priority=RolePriority.ROOT,
        is_system=True,
    )
    # Səlahiyyət qapısı testdə `_require` ilə əvəzlənir (aşağıya bax): burada
    # ölçülən şey icazə DEYİL, `is_active` defoltudur. Flag-i əl ilə qurmaq
    # `Position.grant()`-in bütün hardlock zəncirini işə salardı və test
    # predmetdən uzaqlaşardı.
    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Texniki",
        last_name="Dəstək",
        has_pin=True,
    )
    return employee


def _use_case(repo: _Repo) -> Any:
    from src.application.use_cases.telegram_config import TelegramConfigUseCase

    return TelegramConfigUseCase(
        repository=repo,  # type: ignore[arg-type]
        audit=_Audit(),  # type: ignore[arg-type]
        clock=_Clock(),  # type: ignore[arg-type]
    )


def _save(use_case: Any, actor: Employee, **extra: Any) -> None:
    use_case.save(
        tenant_id=TENANT,
        actor=actor,
        bot_token=TOKEN,
        chat_id="-1001234567890",
        **extra,
    )


def test_changing_the_bot_keeps_a_deactivated_integration_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QÜSURUN ÖZÜ: söndürülmüş inteqrasiya bot dəyişəndə AÇILMAMALIDIR."""
    repo = _Repo(_StoredSettings(bot_token="köhnə", chat_id="-100", is_active=False))
    use_case = _use_case(repo)
    actor = _root()
    monkeypatch.setattr(type(use_case), "_require", lambda _self, _actor: None)

    _save(use_case, actor)

    assert repo.saved_active == [False]


def test_changing_the_bot_keeps_an_active_integration_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Əks istiqamət: aktiv inteqrasiya da olduğu kimi qalır."""
    repo = _Repo(_StoredSettings(bot_token="köhnə", chat_id="-100", is_active=True))
    use_case = _use_case(repo)
    actor = _root()
    monkeypatch.setattr(type(use_case), "_require", lambda _self, _actor: None)

    _save(use_case, actor)

    assert repo.saved_active == [True]


def test_the_first_configuration_starts_active(monkeypatch: pytest.MonkeyPatch) -> None:
    """Saxlanmış sətir YOXDURSA `True` — bot qurmaq onu işlətmək niyyətidir."""
    repo = _Repo(None)
    use_case = _use_case(repo)
    actor = _root()
    monkeypatch.setattr(type(use_case), "_require", lambda _self, _actor: None)

    _save(use_case, actor)

    assert repo.saved_active == [True]


def test_an_explicit_value_is_still_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Açıq `False` ötürülərsə hörmət edilir — `set_active()` yolu dəyişmir."""
    repo = _Repo(_StoredSettings(bot_token="köhnə", chat_id="-100", is_active=True))
    use_case = _use_case(repo)
    actor = _root()
    monkeypatch.setattr(type(use_case), "_require", lambda _self, _actor: None)

    _save(use_case, actor, is_active=False)

    assert repo.saved_active == [False]
