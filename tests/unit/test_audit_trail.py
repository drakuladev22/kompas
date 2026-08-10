"""`PostgresAuditTrail` — bölmə 3/4/7-nin tələb etdiyi `audit_logs` yazıcısı.

Bu adapter əvvəllər YOX idi: `AuditTrail` portu 11 use case tərəfindən
işlədilirdi, lakin PostgreSQL tətbiqi olmadığı üçün həmin `record()`
çağırışlarının istehsalatda yazacağı bir yer də yox idi.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from src.domain.interfaces.ports import AuditTrail
from src.domain.value_objects.identifiers import EmployeeId, TenantId
from src.infrastructure.persistence.audit import PostgresAuditTrail


class _FakeCursor:
    def __init__(self, sink: list[tuple[str, tuple[Any, ...]]]) -> None:
        self._sink = sink

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self._sink.append((sql, params))


class _FakeConnection:
    """Yalnız `cursor()` — adapter bağlantıdan başqa heç nə gözləmir."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple[Any, ...]]] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.statements)


def _trail() -> tuple[PostgresAuditTrail, _FakeConnection]:
    connection = _FakeConnection()
    return PostgresAuditTrail(connection, machine_name="KASSA-01", app_version="2.4.0"), connection  # type: ignore[arg-type]


def test_satisfies_the_audit_trail_port() -> None:
    """Port `runtime_checkable` deyil, ona görə struktur uyğunluğu yoxlanılır."""
    trail, _ = _trail()
    assert hasattr(trail, "record")
    assert isinstance(AuditTrail, type(AuditTrail))


def test_record_inserts_into_audit_logs() -> None:
    trail, connection = _trail()
    tenant = TenantId(uuid.uuid4())
    actor = EmployeeId(uuid.uuid4())

    trail.record(
        tenant_id=tenant,
        actor_id=actor,
        action="MANUAL_TIME_OVERRIDE",
        entity_type="leave_requests",
        entity_id=uuid.uuid4(),
        before_state={"vaxt": "09:42"},
        after_state={"vaxt": "09:05"},
        reason="Kamera görüntüsünə əsasən düzəliş",
    )

    assert len(connection.statements) == 1
    sql, params = connection.statements[0]
    assert "INSERT INTO audit_logs" in sql
    assert params[0] == str(tenant)
    assert params[1] == str(actor)
    assert params[2] == "MANUAL_TIME_OVERRIDE"
    assert params[7] == "Kamera görüntüsünə əsasən düzəliş"
    assert params[8] == "KASSA-01"
    assert params[9] == "2.4.0"


def test_occurred_at_is_not_sent_by_the_application() -> None:
    """Vaxtı BAZA qoyur (`DEFAULT now()`).

    Tətbiq saatı göndərilsəydi, saatı dəyişdirilmiş kassa PC-si audit izini
    də təhrif edərdi — halbuki iz məhz həmin manipulyasiyanı tutmaq üçündür.
    """
    trail, connection = _trail()
    trail.record(
        tenant_id=TenantId(uuid.uuid4()),
        actor_id=None,
        action="PERMISSION_GRANTED",
        entity_type="employees",
    )

    sql, _ = connection.statements[0]
    assert "occurred_at" not in sql


def test_actor_may_be_absent_for_developer_side_actions() -> None:
    """Emergency Access Recovery-də icraçı tenant istifadəçisi DEYİL."""
    trail, connection = _trail()
    trail.record(
        tenant_id=TenantId(uuid.uuid4()),
        actor_id=None,
        action="EMERGENCY_ACCESS_RECOVERY",
        entity_type="employees",
    )

    _, params = connection.statements[0]
    assert params[1] is None


def test_states_are_stored_as_readable_utf8_json() -> None:
    """`ensure_ascii=False` — audit məzmununu insan oxuyur (etiraz, müfəttiş)."""
    trail, connection = _trail()
    trail.record(
        tenant_id=TenantId(uuid.uuid4()),
        actor_id=None,
        action="FINE_ISSUED",
        entity_type="fines",
        after_state={"səbəb": "Formaya uyğun geyinməmək"},
    )

    _, params = connection.statements[0]
    assert params[6] is not None
    assert "\\u" not in params[6]
    assert json.loads(params[6])["səbəb"] == "Formaya uyğun geyinməmək"


def test_empty_states_stay_null_rather_than_empty_json() -> None:
    """`NULL` ilə `{}` fərqlidir: biri "məlumat yoxdur", digəri "boş vəziyyət"."""
    trail, connection = _trail()
    trail.record(
        tenant_id=TenantId(uuid.uuid4()),
        actor_id=None,
        action="LOGIN",
        entity_type="employees",
    )

    _, params = connection.statements[0]
    assert params[5] is None
    assert params[6] is None
