"""Offline sinxronizasiya konfliktlərinin manual həlli (bölmə 5) — Faza 5.

    "Konflikt aşkarlandıqda hər iki versiya saxlanılır, `CONFLICT` statusu ilə
     HR_Admin-ə MANUAL HƏLL üçün göndərilir." (bölmə 5)

`infrastructure/offline/sync.py` konflikti AŞKARLAYIR və `sync_conflicts`-ə
yazır. Bu modul həmin sətirlərin insan tərəfindən həll edilməsini idarə edir —
onsuz cədvəl sonsuza qədər böyüyər və "manual həll" heç vaxt baş verməzdi.

──────────────────────────────────────────────────────────────────────────────
ÜÇ HƏLL VARİANTI, HEÇ BİRİ SİLMİR
──────────────────────────────────────────────────────────────────────────────
    KEPT_LOCAL   — mağazadakı (offline) versiya doğrudur
    KEPT_REMOTE  — buluddakı versiya doğrudur
    MERGED       — HR hər ikisindən götürüb yeni dəyər qurdu

Hər üç halda `local_version` və `remote_version` sütunları TOXUNULMAZ qalır.
Bölmə 5 audit-kritik cədvəllər üçün last-write-wins-i qadağan edir; həll
qərarı da həmin audit izinin bir hissəsidir və geri baxıla bilməlidir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `can_approve_leave_appeal` DEYİL, `can_view_employee_reports`
──────────────────────────────────────────────────────────────────────────────
Konflikt cədvəlləri (leave_requests, fines, audit_logs) HR-ın gündəlik iş
sahəsidir və bölmə 5 həlli açıq şəkildə `HR_Admin`-ə verir. Kataloqda "sync
konflikti" üçün ayrıca flag YOXDUR; ən yaxın mövcud qapı HR-ın işçi
qeydlərinə baxış hüququdur. Yeni flag yaratmaq `can_manage_permissions`
tələb edərdi (yalnız Root) və kataloqu bir ekran üçün şişirdərdi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from src.application.root_limits import fallback_int, limit_int
from src.domain.policies import SystemLimitKey
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import AuditTrail, Clock, SystemLimits
    from src.domain.value_objects.identifiers import EmployeeId, TenantId

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

RESOLVE_CONFLICT_FLAG = "can_view_employee_reports"

MIN_NOTE_LENGTH = 5

#: İnbox-un bir oxunuşda gətirdiyi konflikt sayı.
#:
#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`SystemLimitKey.SYNC_CONFLICT_PAGE_SIZE`, seed: migrations/034). Uzun
#: offline dövrdən sonra konflikt sayı sıçrayır və HR bir dəfəyə neçəsini
#: görmək istədiyi quraşdırmadan-quraşdırmaya fərqlənir.
DEFAULT_INBOX_PAGE_SIZE = fallback_int(SystemLimitKey.SYNC_CONFLICT_PAGE_SIZE)


class ConflictResolutionError(KompasOSError):
    """Konflikt həlli icra edilə bilmədi."""

    user_message = "Konflikt həll edilə bilmədi."


class ConflictNotFoundError(ConflictResolutionError):
    user_message = "Konflikt qeydi tapılmadı."


class Resolution(str, Enum):
    """`sync_conflicts.resolution` — DB `CHECK` ilə EYNİ dəyərlər."""

    KEPT_LOCAL = "KEPT_LOCAL"
    KEPT_REMOTE = "KEPT_REMOTE"
    MERGED = "MERGED"

    @property
    def label_az(self) -> str:
        return _RESOLUTION_LABELS[self]


_RESOLUTION_LABELS: dict[Resolution, str] = {
    Resolution.KEPT_LOCAL: "Mağazadakı versiya saxlanıldı",
    Resolution.KEPT_REMOTE: "Buluddakı versiya saxlanıldı",
    Resolution.MERGED: "Hər iki versiyadan birləşdirildi",
}


@dataclass(frozen=True)
class ConflictItem:
    """Həll gözləyən bir konflikt — ekranın yan-yana göstərdiyi iki versiya."""

    conflict_id: object
    table_name: str
    record_id: object
    local_version: dict[str, Any]
    remote_version: dict[str, Any]
    detected_at: datetime

    def differing_fields(self) -> list[str]:
        """Yalnız FƏRQLİ sahələr — ekran onları vurğulayır.

        Bütün sahələri göstərmək 30 sütunlu bir cərimə sətrində fərqi
        gözdən itirərdi; HR məhz fərqə baxıb qərar verir.
        """
        keys = set(self.local_version) | set(self.remote_version)
        return sorted(
            key for key in keys if self.local_version.get(key) != self.remote_version.get(key)
        )

    @property
    def is_audit_critical(self) -> bool:
        """Bölmə 5-də adı çəkilən cədvəllər — ekranda xəbərdarlıq nişanı."""
        return self.table_name in AUDIT_CRITICAL_TABLES


#: Bölmə 5: "audit-kritik cədvəllər (leave_requests, fines, audit_logs)".
AUDIT_CRITICAL_TABLES = frozenset({"leave_requests", "fines", "audit_logs"})


@runtime_checkable
class SyncConflictRepository(Protocol):
    """`sync_conflicts` cədvəli."""

    def list_open(
        self, tenant_id: TenantId, *, limit: int = DEFAULT_INBOX_PAGE_SIZE
    ) -> list[ConflictItem]: ...

    def get(self, conflict_id: object) -> ConflictItem | None: ...

    def open_count(self, tenant_id: TenantId) -> int: ...

    def resolve(
        self,
        conflict_id: object,
        *,
        resolution: Resolution,
        resolved_by: EmployeeId,
        resolved_at: datetime,
        note: str,
    ) -> None: ...


class SyncConflictUseCase:
    """HR-ın konflikt həlli inbox-u."""

    def __init__(
        self,
        *,
        repository: SyncConflictRepository,
        audit: AuditTrail,
        clock: Clock,
        limits: SystemLimits | None = None,
    ) -> None:
        # `limits` İSTƏYƏ BAĞLIDIR: `None` halında səhifə ölçüsü
        # `DEFAULT_INBOX_PAGE_SIZE` fallback-ıdır — davranış köçürmədən
        # ƏVVƏLKİ ilə HƏRFƏN eynidir.
        self._repository = repository
        self._audit = audit
        self._clock = clock
        self._limits = limits

    def inbox(self, *, tenant_id: TenantId, actor: Employee) -> list[ConflictItem]:
        """Həll gözləyən konfliktlər — audit-kritik olanlar əvvəldə."""
        self._require(actor)
        items = self._repository.list_open(
            tenant_id,
            limit=limit_int(self._limits, tenant_id, SystemLimitKey.SYNC_CONFLICT_PAGE_SIZE),
        )
        return sorted(items, key=lambda item: (not item.is_audit_critical, item.detected_at))

    def open_count(self, *, tenant_id: TenantId, actor: Employee) -> int:
        """Menyu nişanı üçün sayğac."""
        self._require(actor)
        return self._repository.open_count(tenant_id)

    def resolve(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        conflict_id: object,
        resolution: Resolution,
        note: str,
    ) -> ConflictItem:
        """Konflikti bağlayır — hər iki versiya cədvəldə QALIR."""
        self._require(actor)
        cleaned = " ".join(note.split())
        if len(cleaned) < MIN_NOTE_LENGTH:
            raise ConflictResolutionError(
                f"Həll qeydi minimum {MIN_NOTE_LENGTH} simvol olmalıdır",
                user_message="Qərarınızın səbəbini yazın.",
                context={"length": len(cleaned)},
            )

        item = self._repository.get(conflict_id)
        if item is None:
            raise ConflictNotFoundError(
                "Konflikt qeydi tapılmadı", context={"conflict_id": str(conflict_id)}
            )

        now = self._clock.now()
        self._repository.resolve(
            conflict_id,
            resolution=resolution,
            resolved_by=actor.id,
            resolved_at=now,
            note=cleaned,
        )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="SYNC_CONFLICT_RESOLVED",
            entity_type=item.table_name,
            entity_id=item.record_id,
            before_state={"local": item.local_version, "remote": item.remote_version},
            after_state={"resolution": resolution.value},
            reason=cleaned,
        )
        return item

    def _require(self, actor: Employee) -> None:
        if not actor.has_permission(RESOLVE_CONFLICT_FLAG, now=self._clock.now()):
            _audit_log.warning(
                "SYNC_CONFLICT_ACCESS_DENIED",
                extra={"actor_id": str(actor.id), "flag": RESOLVE_CONFLICT_FLAG},
            )
            raise ConflictResolutionError(
                f"«{RESOLVE_CONFLICT_FLAG}» səlahiyyəti yoxdur",
                user_message="Sinxronizasiya konfliktlərini həll etmək səlahiyyətiniz yoxdur.",
                context={"actor_id": str(actor.id)},
            )


__all__ = [
    "AUDIT_CRITICAL_TABLES",
    "DEFAULT_INBOX_PAGE_SIZE",
    "RESOLVE_CONFLICT_FLAG",
    "ConflictItem",
    "ConflictNotFoundError",
    "ConflictResolutionError",
    "Resolution",
    "SyncConflictRepository",
    "SyncConflictUseCase",
]
