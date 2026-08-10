"""Audit Jurnalı baxışı (spesifikasiya bölmə 8, Faza 6.3) — `can_view_audit_logs`.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI USE CASE, SADƏ REPO ÇAĞIRIŞI DEYİL
──────────────────────────────────────────────────────────────────────────────
Audit jurnalı sistemin ƏN HƏSSAS oxunuşudur: orada manual override səbəbləri,
icazə dəyişiklikləri, cərimə qərarları — yəni bütün "kim nə etdi" izi var.
Ekranın birbaşa repo çağırması o deməkdir ki, səlahiyyət yoxlaması UI-da
qalır və başqa bir çağırış nöqtəsi (məs. plugin, hesabat) onu yan keçə bilər.

──────────────────────────────────────────────────────────────────────────────
BAXIŞIN ÖZÜ DƏ AUDİT-LƏNİR
──────────────────────────────────────────────────────────────────────────────
`AUDIT_LOG_VIEWED` sətri yazılır. Bu, ilk baxışda artıq görünür ("jurnala
baxmaq da jurnala düşür?"), amma məhz belə olmalıdır: audit izinə çıxışı olan
şəxs həm də ən çox məlumat toplaya bilən şəxsdir və onun nə vaxt, hansı
süzgəclə baxdığı sonradan sual oluna bilər. Sətir YÜNGÜLDÜR — nəticələr yox,
yalnız süzgəc parametrləri yazılır.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import AuditTrail, Clock
    from src.domain.value_objects.identifiers import EmployeeId, TenantId

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

VIEW_AUDIT_FLAG = "can_view_audit_logs"

#: Bir səhifədə maksimum sətir — 21 filialın bir ayı 100k+ sətir ola bilər.
MAX_PAGE_SIZE = 500
DEFAULT_PAGE_SIZE = 100


class AuditAccessError(KompasOSError):
    """Audit jurnalına baxmaq səlahiyyəti yoxdur."""

    user_message = "Audit jurnalına baxmaq səlahiyyətiniz yoxdur."


@dataclass(frozen=True)
class AuditEntry:
    """Bir audit sətri — ekranın göstərdiyi forma."""

    entry_id: object
    occurred_at: datetime
    actor_id: EmployeeId | None
    actor_name: str
    action: str
    entity_type: str
    entity_id: str | None
    reason: str | None
    before_state: dict[str, Any] | None
    after_state: dict[str, Any] | None
    machine_name: str | None
    app_version: str | None

    @property
    def has_state_diff(self) -> bool:
        """Sətrin "detalları aç" düyməsi göstərilməlidirmi."""
        return bool(self.before_state or self.after_state)


@dataclass(frozen=True)
class AuditFilter:
    """Ekranın süzgəc vəziyyəti.

    Hamısı istəyə bağlıdır; heç biri verilməyibsə son `limit` sətir qaytarılır.
    """

    action: str | None = None
    entity_type: str | None = None
    actor_id: EmployeeId | None = None
    since: datetime | None = None
    until: datetime | None = None
    search: str = ""
    limit: int = DEFAULT_PAGE_SIZE
    offset: int = 0

    def normalized(self) -> AuditFilter:
        """Həddi aşan `limit` sükutla kəsilir — ekranın donmasının qarşısını alır."""
        limit = max(1, min(self.limit, MAX_PAGE_SIZE))
        if limit == self.limit and self.offset >= 0:
            return self
        return AuditFilter(
            action=self.action,
            entity_type=self.entity_type,
            actor_id=self.actor_id,
            since=self.since,
            until=self.until,
            search=self.search,
            limit=limit,
            offset=max(0, self.offset),
        )

    def to_audit_state(self) -> dict[str, object]:
        return {
            "action": self.action,
            "entity_type": self.entity_type,
            "actor_id": str(self.actor_id) if self.actor_id else None,
            "since": self.since.isoformat() if self.since else None,
            "until": self.until.isoformat() if self.until else None,
            "search": self.search or None,
            "limit": self.limit,
            "offset": self.offset,
        }


@dataclass(frozen=True)
class AuditPage:
    """Səhifələnmiş nəticə."""

    entries: list[AuditEntry]
    total: int
    filters: AuditFilter

    @property
    def has_more(self) -> bool:
        return self.filters.offset + len(self.entries) < self.total


@runtime_checkable
class AuditLogReader(Protocol):
    """`audit_logs` oxuma portu.

    `AuditTrail` (yazma) ilə AYRI saxlanılır: yazma hər use case-də lazımdır,
    oxuma isə YALNIZ bir ekranda. Bir protokolda birləşdirmək 11 use case-i
    heç vaxt işlətməyəcəkləri metodlara məcbur edərdi.
    """

    def query(self, tenant_id: TenantId, filters: AuditFilter) -> list[AuditEntry]: ...

    def count(self, tenant_id: TenantId, filters: AuditFilter) -> int: ...

    def distinct_actions(self, tenant_id: TenantId) -> list[str]:
        """Süzgəc dropdown-unu doldurmaq üçün."""
        ...


class AuditQueryUseCase:
    """Audit Log Viewer-in arxa tərəfi."""

    def __init__(
        self,
        *,
        reader: AuditLogReader,
        audit: AuditTrail,
        clock: Clock,
    ) -> None:
        self._reader = reader
        self._audit = audit
        self._clock = clock

    def search(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        filters: AuditFilter | None = None,
    ) -> AuditPage:
        """Süzülmüş audit səhifəsi qaytarır."""
        self._require_access(actor)
        applied = (filters or AuditFilter()).normalized()

        entries = self._reader.query(tenant_id, applied)
        total = self._reader.count(tenant_id, applied)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="AUDIT_LOG_VIEWED",
            entity_type="audit_logs",
            entity_id=None,
            after_state={**applied.to_audit_state(), "result_count": len(entries)},
        )
        return AuditPage(entries=entries, total=total, filters=applied)

    def available_actions(self, *, tenant_id: TenantId, actor: Employee) -> list[str]:
        """Süzgəc dropdown-u — baxış hüququ eynidir."""
        self._require_access(actor)
        return self._reader.distinct_actions(tenant_id)

    def _require_access(self, actor: Employee) -> None:
        if not actor.has_permission(VIEW_AUDIT_FLAG, now=self._clock.now()):
            _security_log.warning(
                "AUDIT_ACCESS_DENIED",
                extra={"actor_id": str(actor.id), "flag": VIEW_AUDIT_FLAG},
            )
            raise AuditAccessError(
                f"«{VIEW_AUDIT_FLAG}» səlahiyyəti yoxdur",
                context={"actor_id": str(actor.id)},
            )


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "VIEW_AUDIT_FLAG",
    "AuditAccessError",
    "AuditEntry",
    "AuditFilter",
    "AuditLogReader",
    "AuditPage",
    "AuditQueryUseCase",
]
