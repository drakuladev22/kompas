"""`security_events` üçün FAIL-SOFT yazıcı (SEC-7 audit tapıntısı).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU, `AuditTrail`-DAN (CLAUDE.md §5, "audit istisna udmur") FƏRQLİ DAVRANIR
──────────────────────────────────────────────────────────────────────────────
`security_events` ÜÇÜNCÜ kanaldır — `audit_logs` (DB, istisna udmur) və
`security.log` (fayl, HƏMİŞƏ yazır) onsuz da mövcuddur. Bu kanalın yazısı
uğursuz olsa əməliyyatı geri qaytarmaq (məs. `LOGIN_FAILED` yazıla bilmədiyi
üçün GİRİŞİN ÖZÜNÜ dayandırmaq) xidmətdən imtina (DoS) yaradardı — hücumçu
bazanı yükləyib bütün istifadəçilərin girişini bloklaya bilərdi. Ona görə
BU sinif istisnanı UDUR, LAKİN SÜKUTLA YOX: uğursuzluq `security.log`-a
`critical` səviyyəsində, tam iz (`exc_info`) ilə yazılır ki, monitorinqdə
görünməz qalmasın. Naxış `SagaOrchestrator._persist()`/`_emit()` ilə EYNİDİR
(`saga_orchestrator.py`) — orkestratorun öz nəzarət jurnalı da eyni səbəbdən
əməliyyatı geri qaytarmır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ İSTEHSALATDA YALNIZ BU SINIF BAĞLANMALIDIR, XAM REPO YOX
──────────────────────────────────────────────────────────────────────────────
`SecurityEventRepository`-nin xam (Postgres) implementasiyası öz uğursuzluğunu
UDMUR — bu, İSTƏNİLƏN irəli-doğru istifadəçi üçün TƏBİİDİR: repo sadəcə
DB-yə yazır, siyasət qərarı (udulsunmu?) onun işi deyil. Fail-soft qərarı
BURADA, kompozisiya səviyyəsində alınır ki, gələcəkdə kimsə xam repo-nu
BİRBAŞA bir use case-ə bağlasa, səhv AŞKAR görünsün (bütün `record()`
çağırışları istisna ATAR) — sükutla "yarım işləyən" bir sistem yaranmaz.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.interfaces.ports import SecurityEventRepository
    from src.domain.value_objects.identifiers import EmployeeId, TenantId

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)


class FailSoftSecurityEventRecorder:
    """`SecurityEventRepository`-ni sarır — yazı uğursuzluğu İSTİSNA ATMIR.

    Strukturca `SecurityEventRepository`-nin ÖZÜNƏ uyğundur (eyni `record()`
    imzası) — istənilən use case bu sinfi bilavasitə `SecurityEventRepository`
    kimi qəbul edə bilər (structural typing, `Protocol`).
    """

    def __init__(self, repository: SecurityEventRepository) -> None:
        self._repository = repository

    def record(
        self,
        *,
        tenant_id: TenantId,
        event_type: str,
        employee_id: EmployeeId | None = None,
        username_attempt: str | None = None,
        ip_address: str | None = None,
        machine_name: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        try:
            self._repository.record(
                tenant_id=tenant_id,
                event_type=event_type,
                employee_id=employee_id,
                username_attempt=username_attempt,
                ip_address=ip_address,
                machine_name=machine_name,
                details=details,
            )
        except Exception:
            _security_log.critical(
                "SECURITY_EVENT_PERSIST_FAILED",
                extra={
                    "event_type": event_type,
                    "tenant_id": str(tenant_id),
                    "employee_id": str(employee_id) if employee_id is not None else None,
                },
                exc_info=True,
            )


__all__ = ["FailSoftSecurityEventRecorder"]
