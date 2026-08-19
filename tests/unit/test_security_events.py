"""`FailSoftSecurityEventRecorder` testləri (SEC-7, `shared/security_events.py`).

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA FAYL
──────────────────────────────────────────────────────────────────────────────
`tests/fixtures/fakes.py::RecordingSecurityEvents` (SEC-7 şərhi) qəsdən
`failure` sahəsi DAŞIMIR və özü açıq yazır: fail-soft davranışı ölçmək
lazım olsa, bunu xam sahtə yox, `FailSoftSecurityEventRecorder`-in ÖZÜ
ölçməlidir — istehsalatda da xam implementasiya birbaşa use case-ə
verilmir, YALNIZ bu sarğı verilir. Bu fayl məhz həmin boşluğu bağlayır:
`security_events.py` əvvəllər HEÇ BİR test tərəfindən çağırılmırdı (fail-soft
budağı, sətir 63-74, coverage-də tamamilə ağ idi).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from src.domain.value_objects.identifiers import EmployeeId, TenantId
from src.shared.security_events import FailSoftSecurityEventRecorder

pytestmark = pytest.mark.unit


def _read_lines(path: Path) -> list[dict[str, object]]:
    import json

    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


class _RawRepository:
    """`SecurityEventRepository`-in xam (sınmayan VƏ ya sınan) sahtəsi."""

    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        if self.failure is not None:
            raise self.failure


def test_a_healthy_write_is_forwarded_unchanged() -> None:
    """Uğurlu hal: sarğı sadəcə ÖTÜRÜR, heç nə udmur, heç nə əlavə etmir."""
    raw = _RawRepository()
    tenant = TenantId(uuid.uuid4())
    employee = EmployeeId(uuid.uuid4())
    recorder = FailSoftSecurityEventRecorder(raw)

    recorder.record(
        tenant_id=tenant,
        event_type="LOGIN_SUCCEEDED",
        employee_id=employee,
        details={"machine": "kassa-1"},
    )

    assert raw.calls == [
        {
            "tenant_id": tenant,
            "event_type": "LOGIN_SUCCEEDED",
            "employee_id": employee,
            "username_attempt": None,
            "ip_address": None,
            "machine_name": None,
            "details": {"machine": "kassa-1"},
        }
    ]


def test_a_failed_write_does_not_raise() -> None:
    """FAIL-SOFT: DB yazısı çöksə belə, çağıran (giriş axını) İSTİSNA ALMIR.

    Modul başlığının izah etdiyi səbəb: geri qaytarma girişin özünü
    dayandırardı — bu, `security_events` cədvəlini yükləməklə DoS yaradardı.
    """
    raw = _RawRepository(failure=RuntimeError("DB əlçatmazdır"))
    recorder = FailSoftSecurityEventRecorder(raw)

    recorder.record(tenant_id=TenantId(uuid.uuid4()), event_type="LOGIN_FAILED")

    # İstisna yuxarı ötürülmədi (əks halda yuxarıdakı sətir testi ÇÖKDÜRƏRDİ) —
    # AMMA cəhdin özü xam repo-ya çatdı, sükutla "hara isə itmədi".
    assert raw.calls and raw.calls[0]["event_type"] == "LOGIN_FAILED"

    # İstisna yuxarı ötürülmədi — çağırış sadəcə qayıtdı.


def test_a_failed_write_is_still_visible_in_the_security_log(
    _isolated_logs: Path,
) -> None:
    """Sükutla udulmur — `security.log`-a CRITICAL səviyyəsində, tam izlə düşür."""
    raw = _RawRepository(failure=RuntimeError("bağlantı kəsildi"))
    recorder = FailSoftSecurityEventRecorder(raw)
    tenant = TenantId(uuid.uuid4())
    employee = EmployeeId(uuid.uuid4())

    recorder.record(tenant_id=tenant, event_type="PERMISSION_CHANGE_DENIED", employee_id=employee)

    records = _read_lines(_isolated_logs / "security.log")
    matching = [r for r in records if r["message"] == "SECURITY_EVENT_PERSIST_FAILED"]
    assert len(matching) == 1
    entry = matching[0]
    assert entry["level"] == "CRITICAL"
    assert entry["context"]["event_type"] == "PERMISSION_CHANGE_DENIED"  # type: ignore[index]
    assert entry["context"]["tenant_id"] == str(tenant)  # type: ignore[index]
    assert entry["context"]["employee_id"] == str(employee)  # type: ignore[index]
    # `exc_info=True` — orijinal istisnanın izi qeyddə görünməlidir.
    assert entry["exception"]["type"] == "RuntimeError"  # type: ignore[index]
    assert "bağlantı kəsildi" in entry["exception"]["message"]  # type: ignore[index]


def test_a_successful_write_leaves_no_critical_trace(_isolated_logs: Path) -> None:
    """Əks-sınaq: uğurlu yazı `security.log`-a HEÇ NƏ əlavə etmir — səs-küy yoxdur."""
    raw = _RawRepository()
    recorder = FailSoftSecurityEventRecorder(raw)

    recorder.record(tenant_id=TenantId(uuid.uuid4()), event_type="LOGIN_SUCCEEDED")

    assert _read_lines(_isolated_logs / "security.log") == []


def test_employee_id_is_optional_and_logged_as_none_when_absent(
    _isolated_logs: Path,
) -> None:
    """Anonim uğursuz giriş (`employee_id=None`) — CLAUDE.md §5 PIN anonimliyi ilə uyğun."""
    raw = _RawRepository(failure=ValueError("naməlum xəta"))
    recorder = FailSoftSecurityEventRecorder(raw)

    recorder.record(tenant_id=TenantId(uuid.uuid4()), event_type="LOGIN_FAILED", employee_id=None)

    records = _read_lines(_isolated_logs / "security.log")
    assert records[0]["context"]["employee_id"] is None  # type: ignore[index]
