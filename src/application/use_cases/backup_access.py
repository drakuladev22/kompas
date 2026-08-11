"""Özünə-xidmət ehtiyat nüsxə/bərpa qapısı — `can_manage_backups` (bölmə 3, 7) — Faza 5.1.

    "`[İnfrastruktur Və Baza Ayarları]` panelində müştəri ÖZÜ, hazırlayıcının
     köməyi olmadan, aydın xəbərdarlıq/təsdiq addımları ilə «Əvvəlki tarixə
     Bərpa Et» funksiyasından istifadə edə bilər." (bölmə 7)

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI QAT
──────────────────────────────────────────────────────────────────────────────
`NightlyBackupService` (Faza 3) `pg_dump`/`pg_restore` işlədən İNFRASTRUKTUR
qatıdır — o, gecə planlayıcısı tərəfindən İNSAN AKTORU OLMADAN da çağırılır,
ona görə orada səlahiyyət yoxlaması YOXDUR və olmamalıdır.

Lakin GUI-dən gələn "Bərpa Et" düyməsi insan qərarıdır və `can_manage_backups`
tələb edir. Yoxlamanı servisə əlavə etsək, planlayıcı üçün süni "sistem
aktoru" uydurmalı olardıq. Bu use case həmin qapını infrastrukturun ÜSTÜNDƏ
qurur — servis toxunulmaz qalır.

──────────────────────────────────────────────────────────────────────────────
TƏSDİQ İFADƏSİ NİYƏ BURADA DA KEÇİR
──────────────────────────────────────────────────────────────────────────────
`restore()` `confirmation`-ı olduğu kimi servisə ötürür və onu ÖZÜ yoxlamır.
İki yerdə yoxlamaq eyni qaydanın iki nüsxəsini yaradardı; servisdəki yoxlama
isə son qapıdır və hər çağırış yolunda işləyir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import AuditTrail, Clock
    from src.domain.value_objects.identifiers import EmployeeId, TenantId
    from src.infrastructure.backup.service import BackupRecord

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

MANAGE_BACKUPS_FLAG = "can_manage_backups"


class BackupAccessError(KompasOSError):
    """Ehtiyat nüsxə/bərpa əməliyyatı üçün səlahiyyət yoxdur."""

    user_message = "Ehtiyat nüsxə və bərpa əməliyyatları üçün səlahiyyətiniz yoxdur."


@runtime_checkable
class BackupCatalog(Protocol):
    """Yaradılmış nüsxələrin siyahısı (`backup_records`)."""

    def list_available(self, tenant_id: TenantId, *, limit: int = 60) -> list[BackupRecord]: ...


@runtime_checkable
class BackupOperations(Protocol):
    """`NightlyBackupService`-in bu qatın işlətdiyi hissəsi."""

    def create(self, tenant_id: TenantId, *, backup_type: str = ...) -> BackupRecord: ...

    def restore(
        self,
        record: BackupRecord,
        *,
        target_dsn: str,
        confirmation: str,
        # `object | None` DEYİL, `EmployeeId | None`: `Protocol` structural
        # typing-dir və parametr tipləri KONTRAVARIANTDIR — porta `object`
        # yazsaydıq, `NightlyBackupService.restore(actor_id: EmployeeId | None)`
        # daha DAR olduğu üçün porta uyğun sayılmazdı və `composition.py`-da
        # bağlantı mypy-dan keçməzdi. Dəyər onsuz da həmişə `actor.id`-dir.
        actor_id: EmployeeId | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class RestorePoint:
    """Ekranda göstərilən bərpa nöqtəsi."""

    record: BackupRecord
    label_az: str
    is_expired: bool

    @property
    def size_mb(self) -> float:
        return round(self.record.size_bytes / (1024 * 1024), 1)


class BackupAccessUseCase:
    """«Ehtiyat Nüsxə və Bərpa» ekranının səlahiyyət qapısı."""

    def __init__(
        self,
        *,
        catalog: BackupCatalog,
        operations: BackupOperations,
        audit: AuditTrail,
        clock: Clock,
    ) -> None:
        self._catalog = catalog
        self._operations = operations
        self._audit = audit
        self._clock = clock

    def restore_points(self, *, tenant_id: TenantId, actor: Employee) -> list[RestorePoint]:
        """Mövcud bərpa nöqtələri — ən yenidən köhnəyə."""
        self._require(actor)
        today = self._clock.now().date()
        return [
            RestorePoint(
                record=record,
                label_az=_label_for(record.created_at.date(), today),
                is_expired=record.is_expired(today),
            )
            for record in self._catalog.list_available(tenant_id)
        ]

    def create_now(self, *, tenant_id: TenantId, actor: Employee) -> BackupRecord:
        """`[İndi Nüsxə Yarat]` — planlaşdırılmış gecə nüsxəsindən ƏLAVƏ.

        Riskli əməliyyatdan (məs. baza keçidi) ƏVVƏL əl ilə nüsxə götürmək
        üçün lazımdır — gecəni gözləmək o anda mənasızdır.
        """
        self._require(actor)
        record = self._operations.create(tenant_id, backup_type="MANUAL")
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="BACKUP_CREATED_MANUALLY",
            entity_type="backup_records",
            entity_id=None,
            after_state={
                "storage_ref": record.storage_ref,
                "size_bytes": record.size_bytes,
                "checksum": record.checksum,
            },
        )
        return record

    def restore(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        record: BackupRecord,
        target_dsn: str,
        confirmation: str,
    ) -> None:
        """`[Əvvəlki tarixə Bərpa Et]` — yazılı təsdiq servisdə yoxlanılır.

        Audit sətri əməliyyatdan ƏVVƏL yazılır: bərpa uğursuz olsa belə
        "kim bu düyməni basdı" sualı cavablanmalıdır — uğursuz bərpa cəhdi
        özü də araşdırılası hadisədir.
        """
        self._require(actor)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="BACKUP_RESTORE_REQUESTED",
            entity_type="backup_records",
            entity_id=None,
            before_state={"target_dsn_masked": _mask_dsn(target_dsn)},
            after_state={
                "storage_ref": record.storage_ref,
                "created_at": record.created_at.isoformat(),
            },
        )
        self._operations.restore(
            record,
            target_dsn=target_dsn,
            confirmation=confirmation,
            actor_id=actor.id,
        )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="BACKUP_RESTORE_COMPLETED",
            entity_type="backup_records",
            entity_id=None,
            after_state={"storage_ref": record.storage_ref},
        )

    def _require(self, actor: Employee) -> None:
        if not actor.has_permission(MANAGE_BACKUPS_FLAG, now=self._clock.now()):
            _security_log.warning(
                "BACKUP_ACCESS_DENIED",
                extra={"actor_id": str(actor.id), "flag": MANAGE_BACKUPS_FLAG},
            )
            raise BackupAccessError(
                f"«{MANAGE_BACKUPS_FLAG}» səlahiyyəti yoxdur",
                context={"actor_id": str(actor.id)},
            )


def _label_for(created_on: date, today: date) -> str:
    """İnsan-oxunaqlı etiket: "Bu gün", "Dünən", yoxsa tarix."""
    delta = (today - created_on).days
    if delta <= 0:
        return "Bu gün"
    if delta == 1:
        return "Dünən"
    return f"{created_on:%d.%m.%Y} ({delta} gün əvvəl)"


def _mask_dsn(dsn: str) -> str:
    """DSN-i audit üçün təhlükəsiz formaya salır — şifrə ASLA yazılmır."""
    if "@" not in dsn:
        return dsn
    _, _, tail = dsn.partition("@")
    return f"***@{tail}"


__all__ = [
    "MANAGE_BACKUPS_FLAG",
    "BackupAccessError",
    "BackupAccessUseCase",
    "BackupCatalog",
    "BackupOperations",
    "RestorePoint",
]
