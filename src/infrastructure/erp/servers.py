"""1C server reyestri, konfiqurasiya backup-ı və rollback — Faza 3.10.

`ErpServerRegistry` portunun (bax `domain/interfaces/ports.py`) tətbiqi.

Spesifikasiya bölmə 7: *"CEO/Root istədiyi qədər 1C server əlavə edə, redaktə
edə, silə (deaktiv edə) bilər ... hər server üçün əvvəlki işlək konfiqurasiya
avtomatik backup kimi saxlanılır və bir kliklə geri qaytarıla bilər ... bütün
əlavə/dəyişiklik/silmə əməliyyatları `audit_logs`-da qeyd olunur."*

──────────────────────────────────────────────────────────────────────────────
BACKUP NƏ VAXT YARADILIR — VƏ NİYƏ HƏR DƏYİŞİKLİKDƏ YOX
──────────────────────────────────────────────────────────────────────────────
Backup YALNIZ üzərinə yazılacaq konfiqurasiya İŞLƏK olduqda `was_verified`
ilə saxlanılır. Səbəb: admin səhv IP yazıb yadda saxlayır, sonra bir də səhv
yazır. Hər dəyişikliyi doğrulanmış backup saysaydıq, "geri qaytar" düyməsi
İKİNCİ səhv konfiqurasiyanı bərpa edərdi — yəni ən çox lazım olduğu anda işə
yaramazdı.

──────────────────────────────────────────────────────────────────────────────
ŞİFRƏ HEÇ VAXT AÇIQ SAXLANILMIR
──────────────────────────────────────────────────────────────────────────────
`password_encrypted` AES-256-GCM ilə şifrələnir və AAD kontekstinə server
ID-si bağlanır (SEC-002 modeli): şifrəli dəyər başqa server sətrinə
köçürülsə deşifrə OLUNMUR. Backup-ın bütöv JSON-u da eyni qayda ilə, öz
backup ID-sinə bağlanaraq şifrələnir.

Siyahı sorğusu (`_SELECT`) şifrə sütununu QƏSDƏN oxumur — sirri təsadüfən
yaddaşa gətirməmək üçün; o, yalnız `credentials_for()` ilə açıq şəkildə
istənildikdə oxunur və hər belə çağırış `security.log`-a düşür.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from src.application.use_cases.erp_connection import StoreServerLink
from src.domain.value_objects.erp import (
    ErpError,
    ErpServer,
    ErpServerDraft,
    ErpServerStatus,
    OneCDocumentMapping,
    SyncCursor,
)
from src.domain.value_objects.identifiers import ErpServerId, StoreId, TenantId
from src.infrastructure.erp.one_c_connector import OneCServerConfig
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.value_objects.identifiers import EmployeeId
    from src.infrastructure.persistence.connection import Database
    from src.infrastructure.security.encryption import EncryptionService

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)
_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)


class ErpServerNotFoundError(ErpError):
    """Göstərilən server qeydi yoxdur."""

    user_message = "Server qeydi tapılmadı — siyahını yeniləyin."


class NoVerifiedBackupError(ErpError):
    """Geri qaytarılacaq işlək konfiqurasiya yoxdur."""

    user_message = (
        "Bu server üçün saxlanmış işlək konfiqurasiya yoxdur — geri qaytarmaq mümkün deyil."
    )


@dataclass(frozen=True)
class ConfigBackup:
    """`erp_server_config_backups` sətri (məzmun DEŞİFRƏ EDİLMƏMİŞ)."""

    id: UUID
    server_id: UUID
    backed_up_at: datetime
    was_verified: bool
    backed_up_by: UUID | None = None


class ErpServerRepository:
    """`erp_servers` + `erp_server_config_backups` üzərində əməliyyatlar."""

    _SELECT = """
        SELECT id, tenant_id, server_name, host, port, username, infobase,
               status, use_https, document_mapping_json, sync_interval_seconds,
               last_successful_sync, last_sync_started_at, last_error,
               last_error_at, consecutive_failures, sync_cursor_at,
               sync_cursor_document_ids
          FROM erp_servers
    """

    def __init__(
        self, database: Database, tenant_id: TenantId, encryption: EncryptionService
    ) -> None:
        self._database = database
        self._tenant_id = tenant_id
        # Şifrələmə konstruktora bağlanır ki, yuxarı qatlar (use case, sync
        # worker) onu heç vaxt ötürməsin — sirr infrastrukturda qalır.
        self._encryption = encryption

    # ------------------------------- oxuma ----------------------------------- #

    def list_all(self) -> list[ErpServer]:
        rows = self._fetch_all(self._SELECT + " ORDER BY server_name")
        return [_row_to_server(row) for row in rows]

    def get(self, server_id: ErpServerId) -> ErpServer | None:
        rows = self._fetch_all(self._SELECT + " WHERE id = %s", (server_id,))
        return _row_to_server(rows[0]) if rows else None

    def require(self, server_id: ErpServerId) -> ErpServer:
        server = self.get(server_id)
        if server is None:
            raise ErpServerNotFoundError(
                "ERP server qeydi tapılmadı", context={"server_id": str(server_id)}
            )
        return server

    def syncable(self) -> list[ErpServer]:
        """Sinxronizasiya dövrünə daxil olan serverlər.

        `ERROR` statusu DA daxildir: bir şəbəkə kəsintisi serveri həmişəlik
        növbədən çıxarsaydı, admin problem düzəldikdən sonra da əl ilə
        yenidən aktivləşdirməli olardı (bax `ErpServerStatus.is_syncable`).
        """
        rows = self._fetch_all(self._SELECT + " WHERE status <> 'INACTIVE' ORDER BY server_name")
        return [_row_to_server(row) for row in rows]

    def credentials_for(self, server_id: ErpServerId) -> OneCServerConfig:
        """Şifrəni deşifrə edib hazır bağlantı konfiqurasiyası qurur."""
        server = self.require(server_id)
        rows = self._fetch_all(
            "SELECT password_encrypted FROM erp_servers WHERE id = %s", (server_id,)
        )
        if not rows:  # pragma: no cover - `require` onsuz da yoxladı
            raise ErpServerNotFoundError(
                "ERP server qeydi tapılmadı", context={"server_id": str(server_id)}
            )
        _security_log.info("ERP_CREDENTIALS_ACCESSED", extra={"server_id": str(server_id)})
        password = self._encryption.decrypt(
            rows[0]["password_encrypted"], context=f"erp_server:{server_id}"
        )
        return OneCServerConfig(
            host=server.host,
            port=server.port,
            username=server.username,
            password=password,
            infobase=server.infobase,
            use_https=server.use_https,
            mapping=server.mapping,
        )

    # ------------------------------- yazma ----------------------------------- #

    def create(
        self,
        draft: ErpServerDraft,
        *,
        created_by: EmployeeId | None = None,
        activate: bool = True,
    ) -> ErpServer:
        """Yeni server qeydi yaradır (yalnız test uğurlu olduqdan sonra çağırılır)."""
        new_id = uuid4()
        status = ErpServerStatus.ACTIVE if activate else ErpServerStatus.INACTIVE
        encrypted = self._encryption.encrypt(draft.password, context=f"erp_server:{new_id}")

        with self._database.unit_of_work(self._tenant_id, user_id=created_by) as uow:
            with uow.connection.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO erp_servers
                        (id, tenant_id, server_name, host, port, username,
                         password_encrypted, infobase, use_https,
                         document_mapping_json, status, sync_interval_seconds,
                         created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        new_id,
                        self._tenant_id,
                        draft.server_name,
                        draft.host,
                        draft.port,
                        draft.username,
                        encrypted,
                        draft.infobase,
                        draft.use_https,
                        json.dumps(draft.mapping.as_dict()),
                        status.value,
                        draft.sync_interval_seconds,
                        created_by,
                    ),
                )
            self._write_audit(
                uow.connection,
                actor_id=created_by,
                action="ERP_SERVER_CREATED",
                entity_id=new_id,
                after_state=draft.auditable(),
            )
            uow.commit()

        _audit_log.info(
            "ERP_SERVER_CREATED",
            extra={
                "server_id": str(new_id),
                "server_name": draft.server_name,
                "host": draft.host,
                "actor_id": str(created_by) if created_by else None,
            },
        )
        return self.require(ErpServerId(new_id))

    def update(
        self,
        server_id: ErpServerId,
        draft: ErpServerDraft,
        *,
        updated_by: EmployeeId | None = None,
        backup_previous: bool = True,
    ) -> ErpServer:
        """Konfiqurasiyanı əvəz edir; əvvəlkini (işləkdirsə) backup-a yazır."""
        existing = self.require(server_id)
        encrypted = self._encryption.encrypt(draft.password, context=f"erp_server:{server_id}")

        with self._database.unit_of_work(self._tenant_id, user_id=updated_by) as uow:
            if backup_previous:
                self._store_backup(
                    uow.connection,
                    server_id=server_id,
                    backed_up_by=updated_by,
                    was_verified=existing.has_verified_config,
                )
            with uow.connection.cursor() as cur:
                cur.execute(
                    """
                    UPDATE erp_servers
                       SET server_name = %s, host = %s, port = %s, username = %s,
                           password_encrypted = %s, infobase = %s, use_https = %s,
                           document_mapping_json = %s, sync_interval_seconds = %s
                     WHERE id = %s
                    """,
                    (
                        draft.server_name,
                        draft.host,
                        draft.port,
                        draft.username,
                        encrypted,
                        draft.infobase,
                        draft.use_https,
                        json.dumps(draft.mapping.as_dict()),
                        draft.sync_interval_seconds,
                        server_id,
                    ),
                )
            self._write_audit(
                uow.connection,
                actor_id=updated_by,
                action="ERP_SERVER_UPDATED",
                entity_id=server_id,
                before_state=existing.auditable(),
                after_state=draft.auditable(),
            )
            uow.commit()

        _audit_log.info(
            "ERP_SERVER_UPDATED",
            extra={
                "server_id": str(server_id),
                "actor_id": str(updated_by) if updated_by else None,
            },
        )
        return self.require(server_id)

    def set_status(
        self,
        server_id: ErpServerId,
        status: ErpServerStatus,
        *,
        changed_by: EmployeeId | None = None,
        reason: str | None = None,
    ) -> None:
        """Aktivləşdirir/deaktiv edir. Sətir SİLİNMİR (bölmə 7: "deaktiv edə").

        Fiziki silmə `sales_transactions.server_id` xarici açarını qırardı —
        yəni keçmiş satış tarixçəsi də itərdi.
        """
        existing = self.require(server_id)
        with self._database.unit_of_work(self._tenant_id, user_id=changed_by) as uow:
            with uow.connection.cursor() as cur:
                cur.execute(
                    "UPDATE erp_servers SET status = %s WHERE id = %s",
                    (status.value, server_id),
                )
            self._write_audit(
                uow.connection,
                actor_id=changed_by,
                action="ERP_SERVER_STATUS_CHANGED",
                entity_id=server_id,
                before_state={"status": existing.status.value},
                after_state={"status": status.value},
                reason=reason,
            )
            uow.commit()
        _audit_log.info(
            "ERP_SERVER_STATUS_CHANGED",
            extra={
                "server_id": str(server_id),
                "from": existing.status.value,
                "to": status.value,
                "actor_id": str(changed_by) if changed_by else None,
            },
        )

    # ---------------------------- sync vəziyyəti ------------------------------ #

    def mark_sync_started(self, server_id: ErpServerId, *, now: datetime | None = None) -> None:
        moment = now or datetime.now(UTC)
        self._execute(
            "UPDATE erp_servers SET last_sync_started_at = %s WHERE id = %s",
            (moment, server_id),
        )

    def record_success(
        self, server_id: ErpServerId, cursor: SyncCursor, *, now: datetime | None = None
    ) -> None:
        """Uğurlu dövr: kursor irəliləyir, xəta sayğacı sıfırlanır."""
        moment = now or datetime.now(UTC)
        self._execute(
            """
            UPDATE erp_servers
               SET last_successful_sync = %s,
                   sync_cursor_at = %s,
                   sync_cursor_document_ids = %s,
                   consecutive_failures = 0,
                   last_error = NULL,
                   last_error_at = NULL,
                   status = CASE WHEN status = 'ERROR' THEN 'ACTIVE' ELSE status END
             WHERE id = %s
            """,
            (moment, cursor.last_document_at, sorted(cursor.boundary_document_ids), server_id),
        )

    def record_failure(
        self, server_id: ErpServerId, message: str, *, now: datetime | None = None
    ) -> None:
        """Uğursuz dövr: sayğac artır, status `ERROR` olur.

        Kursor TOXUNULMUR — növbəti cəhd eyni yerdən davam edir.
        """
        moment = now or datetime.now(UTC)
        self._execute(
            """
            UPDATE erp_servers
               SET last_error = %s,
                   last_error_at = %s,
                   consecutive_failures = consecutive_failures + 1,
                   status = CASE WHEN status = 'ACTIVE' THEN 'ERROR' ELSE status END
             WHERE id = %s
            """,
            (message[:500], moment, server_id),
        )

    # ------------------------------- backup ---------------------------------- #

    def latest_verified_backup(self, server_id: ErpServerId) -> ConfigBackup | None:
        rows = self._fetch_all(
            """
            SELECT id, server_id, backed_up_at, was_verified, backed_up_by
              FROM erp_server_config_backups
             WHERE server_id = %s AND was_verified
             ORDER BY backed_up_at DESC
             LIMIT 1
            """,
            (server_id,),
        )
        if not rows:
            return None
        row = rows[0]
        return ConfigBackup(
            id=row["id"],
            server_id=row["server_id"],
            backed_up_at=row["backed_up_at"],
            was_verified=row["was_verified"],
            backed_up_by=row.get("backed_up_by"),
        )

    def rollback(self, server_id: ErpServerId, *, actor_id: EmployeeId | None = None) -> ErpServer:
        """ "Bir kliklə geri qaytar" (bölmə 7) — sonuncu İŞLƏK konfiqurasiya."""
        backup = self.latest_verified_backup(server_id)
        if backup is None:
            raise NoVerifiedBackupError(
                "Bu server üçün doğrulanmış konfiqurasiya backup-ı yoxdur",
                context={"server_id": str(server_id)},
            )
        existing = self.require(server_id)
        draft = _draft_from_payload(self._read_backup_payload(backup.id))
        restored = self.update(
            server_id,
            draft,
            updated_by=actor_id,
            # Bərpa zamanı üzərinə yazılan konfiqurasiya POZUQ olduğu üçün
            # onu backup saxlamaq mənasızdır.
            backup_previous=False,
        )
        _security_log.warning(
            "ERP_SERVER_ROLLED_BACK",
            extra={
                "server_id": str(server_id),
                "backup_id": str(backup.id),
                "backed_up_at": backup.backed_up_at.isoformat(),
                "replaced_host": existing.host,
                "actor_id": str(actor_id) if actor_id else None,
            },
        )
        return restored

    def _store_backup(
        self,
        connection: Any,
        *,
        server_id: ErpServerId,
        backed_up_by: EmployeeId | None,
        was_verified: bool,
    ) -> UUID:
        """Cari konfiqurasiyanı bütöv şəkildə şifrələyib saxlayır."""
        config = self.credentials_for(server_id)
        server = self.require(server_id)
        backup_id = uuid4()
        payload = {
            "server_name": server.server_name,
            "host": config.host,
            "port": config.port,
            "username": config.username,
            "password": config.password,
            "infobase": config.infobase,
            "use_https": config.use_https,
            "sync_interval_seconds": server.sync_interval_seconds,
            "mapping": config.mapping.as_dict(),
        }
        encrypted = self._encryption.encrypt(
            json.dumps(payload, ensure_ascii=False), context=f"erp_backup:{backup_id}"
        )
        with connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO erp_server_config_backups
                    (id, server_id, config_json_encrypted, backed_up_by, was_verified)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (backup_id, server_id, encrypted, backed_up_by, was_verified),
            )
        return backup_id

    def _read_backup_payload(self, backup_id: UUID) -> dict[str, Any]:
        rows = self._fetch_all(
            "SELECT config_json_encrypted FROM erp_server_config_backups WHERE id = %s",
            (backup_id,),
        )
        if not rows:  # pragma: no cover - invariant
            raise NoVerifiedBackupError(
                "Backup sətri tapılmadı", context={"backup_id": str(backup_id)}
            )
        _security_log.info("ERP_BACKUP_DECRYPTED", extra={"backup_id": str(backup_id)})
        raw = self._encryption.decrypt(
            rows[0]["config_json_encrypted"], context=f"erp_backup:{backup_id}"
        )
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):  # pragma: no cover - invariant
            raise ErpError("Backup məzmunu yararsızdır", context={"backup_id": str(backup_id)})
        return parsed

    # ------------------------------ köməkçilər -------------------------------- #

    def _write_audit(
        self,
        connection: Any,
        *,
        actor_id: EmployeeId | None,
        action: str,
        entity_id: UUID,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> None:
        with connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_logs
                    (tenant_id, actor_id, action, entity_type, entity_id,
                     before_state, after_state, reason)
                VALUES (%s, %s, %s, 'erp_server', %s, %s, %s, %s)
                """,
                (
                    self._tenant_id,
                    actor_id,
                    action,
                    entity_id,
                    json.dumps(before_state, ensure_ascii=False) if before_state else None,
                    json.dumps(after_state, ensure_ascii=False) if after_state else None,
                    reason,
                ),
            )

    def _fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._database.unit_of_work(self._tenant_id) as uow, uow.connection.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def _execute(self, sql: str, params: tuple[Any, ...]) -> None:
        with self._database.unit_of_work(self._tenant_id) as uow:
            with uow.connection.cursor() as cur:
                cur.execute(sql, params)
            uow.commit()


# --------------------------------------------------------------------------- #
# Sətir ↔ obyekt
# --------------------------------------------------------------------------- #


def _row_to_server(row: dict[str, Any]) -> ErpServer:
    return ErpServer(
        id=ErpServerId(row["id"]),
        tenant_id=TenantId(row["tenant_id"]),
        server_name=row["server_name"],
        host=row["host"],
        port=row["port"],
        username=row["username"],
        infobase=row.get("infobase") or "",
        status=ErpServerStatus(row["status"]),
        use_https=bool(row.get("use_https")),
        mapping=OneCDocumentMapping.from_dict(row.get("document_mapping_json")),
        sync_interval_seconds=row.get("sync_interval_seconds") or 300,
        last_successful_sync=row.get("last_successful_sync"),
        last_sync_started_at=row.get("last_sync_started_at"),
        last_error=row.get("last_error"),
        last_error_at=row.get("last_error_at"),
        consecutive_failures=row.get("consecutive_failures") or 0,
        cursor=SyncCursor(
            last_document_at=row.get("sync_cursor_at"),
            boundary_document_ids=frozenset(row.get("sync_cursor_document_ids") or ()),
        ),
    )


def _draft_from_payload(payload: dict[str, Any]) -> ErpServerDraft:
    return ErpServerDraft(
        server_name=str(payload["server_name"]),
        host=str(payload["host"]),
        port=int(payload["port"]),
        username=str(payload["username"]),
        password=str(payload["password"]),
        infobase=str(payload.get("infobase", "")),
        use_https=bool(payload.get("use_https", False)),
        mapping=OneCDocumentMapping.from_dict(payload.get("mapping")),
        sync_interval_seconds=int(payload.get("sync_interval_seconds", 300)),
    )


class PostgresStoreServerMappingRepository:
    """`store_server_mapping` — mağaza ↔ 1C server bağlantısı (bölmə 7).

    `ErpServerRepository`-dən AYRIDIR: o, serverin ÖZ konfiqurasiyasını
    (şifrə, backup, rollback) idarə edir; bu isə sadəcə iki ID-ni və bir 1C
    kodunu birləşdirən əlaqə cədvəlidir. Birləşdirmək server repo-suna
    tamamilə başqa məsuliyyət əlavə edərdi.
    """

    def __init__(self, database: Database, tenant_id: TenantId) -> None:
        self._database = database
        self._tenant_id = tenant_id

    def list_all(self) -> list[StoreServerLink]:
        rows = self._fetch(
            """
            SELECT m.store_id, m.server_id, m.one_c_store_code,
                   COALESCE(s.name, '—')          AS store_name,
                   COALESCE(e.server_name, '—')   AS server_name
            FROM store_server_mapping m
            JOIN stores s      ON s.id = m.store_id
            JOIN erp_servers e ON e.id = m.server_id
            WHERE s.tenant_id = %s
            ORDER BY e.server_name, s.name
            """,
            (self._tenant_id,),
        )
        return [
            StoreServerLink(
                store_id=row["store_id"],
                store_name=row["store_name"],
                server_id=row["server_id"],
                server_name=row["server_name"],
                one_c_store_code=row["one_c_store_code"],
            )
            for row in rows
        ]

    def upsert(self, *, store_id: StoreId, server_id: ErpServerId, one_c_store_code: str) -> None:
        self._execute(
            """
            INSERT INTO store_server_mapping (store_id, server_id, one_c_store_code)
            VALUES (%s, %s, %s)
            ON CONFLICT (store_id, server_id)
            DO UPDATE SET one_c_store_code = EXCLUDED.one_c_store_code
            """,
            (store_id, server_id, one_c_store_code),
        )

    def delete(self, *, store_id: StoreId, server_id: ErpServerId) -> None:
        self._execute(
            "DELETE FROM store_server_mapping WHERE store_id = %s AND server_id = %s",
            (store_id, server_id),
        )

    def _fetch(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._database.unit_of_work(self._tenant_id) as uow, uow.connection.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def _execute(self, sql: str, params: tuple[Any, ...]) -> None:
        with self._database.unit_of_work(self._tenant_id) as uow:
            with uow.connection.cursor() as cur:
                cur.execute(sql, params)
            uow.commit()


__all__ = [
    "ConfigBackup",
    "ErpServerNotFoundError",
    "ErpServerRepository",
    "NoVerifiedBackupError",
    "PostgresStoreServerMappingRepository",
]
