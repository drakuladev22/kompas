"""`bulk_import_log` + `store_templates` (#29, kompas1.md Faza 5, migrations/037).

İKİ CƏDVƏL, BİR FAYL: hər ikisi EYNİ funksiya sahəsinin (Toplu Əməliyyatlar)
törəməsidir və heç biri başqa heç bir modulda İSTİFADƏ OLUNMUR — ayrı fayllara
bölmək yalnız iki kiçik sinfi iki fayla parçalayardı, oxunaqlılıq qazandırmadan
(`bulk_operations.py`-in özü də iki use case-i EYNİ səbəbdən bir modulda saxlayır).

`bulk_import_log`-da `DELETE` HEÇ VAXT işlədilmir: `migrations/037` cədvələ
açıq `REVOKE DELETE` qoyub (audit qeydidir) — bu fayl da həmin qaydaya
tabedir, DB-nin özü onsuz da bunu məcbur edir.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from psycopg import errors as pg_errors

from src.domain.value_objects.catalogs import InvalidCatalogEntryError
from src.domain.value_objects.store_templates import StoreTemplate
from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.value_objects.identifiers import (
        BulkImportLogId,
        EmployeeId,
        StoreTemplateId,
        TenantId,
    )


class PostgresBulkImportLogRepository(_BaseRepository):
    """`bulk_import_log` — bax `BulkImportLogRepository` port başlığı.

    İKİ-FAZALI YAZI (`start()` + `finish()`) burada TƏK sətrin İKİ ayrı `UPDATE`
    ilə doldurulması kimi görünür — bu, TƏSADÜFİ DEYİL: `application/use_cases/
    bulk_operations.py` başlığındakı tranzaksiya sərhədi qərarının DB tərəfidir.
    """

    def start(
        self,
        *,
        log_id: BulkImportLogId,
        tenant_id: TenantId,
        import_type: str,
        performed_by: EmployeeId,
        file_ref: str | None,
        row_count: int,
        performed_at: datetime,
    ) -> None:
        self._execute(
            """
            INSERT INTO bulk_import_log
                (id, tenant_id, import_type, performed_by, file_ref, row_count, performed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (log_id, tenant_id, import_type, performed_by, file_ref, row_count, performed_at),
        )

    def finish(
        self,
        *,
        log_id: BulkImportLogId,
        success_count: int,
        error_count: int,
        error_summary: str | None,
        finished_at: datetime,
    ) -> None:
        self._execute(
            """
            UPDATE bulk_import_log
               SET success_count = %s,
                   error_count   = %s,
                   error_summary = %s,
                   finished_at   = %s
             WHERE id = %s AND tenant_id = %s
            """,
            (success_count, error_count, error_summary, finished_at, log_id, self._tenant),
        )

    def list_recent(self, tenant_id: TenantId, *, limit: int = 50) -> list[dict[str, object]]:
        # `max(1, ...)`: `LIMIT 0` PostgreSQL-də "heç nə" demədir, sıfır
        # sətirlik cavab isə "əməliyyat tarixçəsi yoxdur" ilə qarışa bilər.
        rows = self._fetch_all(
            """
            SELECT id, import_type, performed_by, file_ref, row_count, success_count,
                   error_count, error_summary, performed_at, finished_at
              FROM bulk_import_log
             WHERE tenant_id = %s
             ORDER BY performed_at DESC
             LIMIT %s
            """,
            (tenant_id, max(1, limit)),
        )
        return [dict(row) for row in rows]


class PostgresStoreTemplateRepository(_BaseRepository):
    """`store_templates` — bax `StoreTemplateRepository` port başlığı."""

    _SELECT = """
        SELECT id, tenant_id, name, based_on_store_id, config_snapshot,
               created_by, is_active, deactivated_at
          FROM store_templates
    """

    def get(self, template_id: StoreTemplateId) -> StoreTemplate | None:
        row = self._fetch_one(
            self._SELECT + " WHERE id = %s AND tenant_id = %s", (template_id, self._tenant)
        )
        return self._hydrate(row) if row else None

    def list_for_tenant(
        self, tenant_id: TenantId, *, include_inactive: bool = False
    ) -> list[StoreTemplate]:
        sql = self._SELECT + " WHERE tenant_id = %s"
        if not include_inactive:
            sql += " AND is_active"
        rows = self._fetch_all(sql + " ORDER BY name", (tenant_id,))
        return [self._hydrate(row) for row in rows]

    def save(self, tenant_id: TenantId, entry: StoreTemplate) -> None:
        """YALNIZ YARADIR — bax port başlığı ("config_snapshot DƏYİŞMİR").

        `UniqueViolation` TUTULUR: `UNIQUE (tenant_id, name)` pozuntusu xam DB
        mətni kimi çatsaydı, Root "eyni adlı şablon niyə yaranmadı?" sualına
        cavab tapa bilməzdi (`annual_leave_repository.save()` ilə eyni naxış).
        """
        try:
            self._execute(
                """
                INSERT INTO store_templates
                    (id, tenant_id, name, based_on_store_id, config_snapshot,
                     created_by, is_active)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
                """,
                (
                    entry.store_template_id,
                    tenant_id,
                    entry.name,
                    entry.based_on_store_id,
                    json.dumps(dict(entry.config_snapshot)),
                    entry.created_by,
                    entry.is_active,
                ),
            )
        except pg_errors.UniqueViolation as error:
            raise InvalidCatalogEntryError(
                f"Bu adla şablon artıq mövcuddur: {entry.name}",
                user_message=f"«{entry.name}» adlı şablon artıq mövcuddur — fərqli ad seçin.",
                context={"name": entry.name},
            ) from error

    def deactivate(
        self, tenant_id: TenantId, template_id: StoreTemplateId, *, changed_by: EmployeeId
    ) -> None:
        # `changed_by` SQL-də İSTİFADƏ OLUNMUR — cədvəldə "kim söndürdü" sütunu
        # yoxdur (`store_templates`-in nə `updated_by`, nə `deactivated_by`-ı
        # var, migrations/037). Struktur cavab AUDİT SƏTRİNDƏDİR (tətbiq qatı,
        # `WorkModeRepository.deactivate` ilə EYNİ qərar).
        self._execute(
            """
            UPDATE store_templates
               SET is_active = FALSE, deactivated_at = now()
             WHERE id = %s AND tenant_id = %s AND is_active
            """,
            (template_id, tenant_id),
        )

    def _hydrate(self, row: dict[str, Any]) -> StoreTemplate:
        return StoreTemplate(
            name=row["name"],
            tenant_id=row["tenant_id"],
            is_active=row["is_active"],
            deactivated_at=row["deactivated_at"],
            store_template_id=row["id"],
            based_on_store_id=row["based_on_store_id"],
            config_snapshot=_as_snapshot(row["config_snapshot"]),
            created_by=row["created_by"],
        )


def _as_snapshot(raw: Any) -> dict[str, object]:
    """`JSONB` sütununu `dict`-ə çevirir — sürücü artıq obyekt qaytara bilər.

    `preferences.py::_as_key_list` ilə eyni müdafiə: format fərqi (sətir/obyekt)
    bir dəfəlik sürücü davranışına bağlı ola bilər, ekranı sındırmamalıdır.
    """
    value = json.loads(raw) if isinstance(raw, str) else raw
    return dict(value) if isinstance(value, dict) else {}


__all__ = [
    "PostgresBulkImportLogRepository",
    "PostgresStoreTemplateRepository",
]
