"""Platforma cədvəlləri — `plugins` və `backup_records` (Faza 5/6 GUI bağlantısı).

`PluginManagementUseCase` və `BackupAccessUseCase` yazılıb, lakin onların
portlarının (`PluginRegistry`, `BackupCatalog`) Postgres tərəfi yox idi —
ona görə hər iki use case `composition.py`-da QURULA BİLMİRDİ və ekranlar
canlı məlumat almırdı. Bu modul həmin boşluğu bağlayır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI MODUL
──────────────────────────────────────────────────────────────────────────────
`catalog_repositories.py` iş kataloqlarını (rejim/cərimə növü/tapşırıq/xal),
`config_repositories.py` isə konfiqurasiyanı (limit/toggle/flag) saxlayır.
Plugin və ehtiyat nüsxə heç birinə aid deyil: onlar TƏTBİQİN ÖZÜNÜN
platforma vəziyyətidir (yüklənən kod, alınan nüsxə) və ömrü tenant-ın iş
məlumatından asılı deyil. Mövcud iki modula qatsaydıq, hər ikisinin
məsuliyyəti bulanardı.

──────────────────────────────────────────────────────────────────────────────
PLUGIN NİYƏ FİZİKİ SİLİNİR, KATALOQ İSƏ YOX
──────────────────────────────────────────────────────────────────────────────
`catalogs.py`-dakı soft delete qaydası BURADA TƏTBİQ OLUNMUR və bu, qəsdəndir:
kataloq sətri keçmiş cərimənin SƏBƏBİDİR (mübahisədə sübut lazımdır), plugin
isə sadəcə bir kod parçasıdır və heç bir tarixi qeydə istinad etmir. Onu
"deaktiv" halda saxlamaq söndürülmüş kodu diskdə qoymaq olardı — bax
`plugin_management.PluginManagementUseCase.remove` şərhi.

──────────────────────────────────────────────────────────────────────────────
`APPROVED` STATUSU İKİ SÜTUN TƏLƏB EDİR
──────────────────────────────────────────────────────────────────────────────
`schema.sql` §17: `chk_plugin_approved` — `status = 'APPROVED'` yalnız
`signature_verified` DOĞRU və `approved_by` DOLU olduqda mümkündür. Ona görə
`set_status()` təsdiq halında `approved_by`/`approved_at` sütunlarını da
yazır; əks halda DB `CHECK` pozuntusu ilə cavab verər və istifadəçi səbəbi
anlaşılmaz xəta kimi görərdi.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from src.application.use_cases.plugin_management import InstalledPlugin
from src.infrastructure.backup.service import BackupRecord
from src.infrastructure.persistence.repositories import _BaseRepository
from src.infrastructure.plugins.contracts import PluginStatus
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.value_objects.identifiers import TenantId
    from src.infrastructure.plugins.contracts import PluginManifest

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)


class PostgresPluginRegistry(_BaseRepository):
    """`plugins` cədvəli — `PluginRegistry` portunun tətbiqi."""

    _SELECT = """
        SELECT id, name, version, publisher, status, signature_verified
        FROM plugins
    """

    def list_all(self, tenant_id: TenantId) -> list[InstalledPlugin]:
        rows = self._fetch_all(
            self._SELECT + " WHERE tenant_id = %s ORDER BY name, version",
            (tenant_id,),
        )
        return [self._hydrate(row) for row in rows]

    def get(self, plugin_id: str) -> InstalledPlugin | None:
        # `tenant_id` şərti də qoyulur (RLS-ə ƏLAVƏ ikinci qat) — başqa
        # tenant-ın plugin ID-si təxmin edilsə belə sətir qaytarılmamalıdır.
        row = self._fetch_one(
            self._SELECT + " WHERE id = %s AND tenant_id = %s",
            (plugin_id, self._tenant),
        )
        return self._hydrate(row) if row else None

    def install(
        self,
        tenant_id: TenantId,
        *,
        manifest: PluginManifest,
        digest: str,
        installed_by: object,
    ) -> str:
        """Paketi `PENDING_APPROVAL` vəziyyətində yazır və ID-sini qaytarır.

        `signature_verified = TRUE` yazılır, çünki bu metod YALNIZ imza
        yoxlanışından sonra çağırılır (`PluginManagementUseCase.install`
        `verify()`-ı ön şərt kimi icra edir). Sütunu `FALSE` qoymaq həmin
        yoxlamanın nəticəsini itirərdi və plugin heç vaxt aktivləşə bilməzdi.

        Eyni ad+versiya təkrar quraşdırıldıqda sətir ƏVƏZLƏNİR: `UNIQUE
        (tenant_id, name, version)` var və "artıq mövcuddur" xətası vermək
        istifadəçini paketi əl ilə silməyə məcbur edərdi. Status isə yenidən
        `PENDING_APPROVAL`-a qayıdır — yeni bayt axını yeni təsdiq deməkdir.
        """
        row = self._fetch_one(
            """
            INSERT INTO plugins
                (tenant_id, name, version, publisher, signature,
                 signature_verified, status, manifest)
            VALUES (%s, %s, %s, %s, %s, TRUE, 'PENDING_APPROVAL', %s)
            ON CONFLICT (tenant_id, name, version)
            DO UPDATE SET publisher          = EXCLUDED.publisher,
                          signature          = EXCLUDED.signature,
                          signature_verified = TRUE,
                          status             = 'PENDING_APPROVAL',
                          approved_by        = NULL,
                          approved_at        = NULL,
                          manifest           = EXCLUDED.manifest
            RETURNING id
            """,
            (
                tenant_id,
                manifest.name,
                manifest.version,
                manifest.publisher,
                digest,
                json.dumps(manifest.to_dict(), ensure_ascii=False),
            ),
        )
        if row is None:  # pragma: no cover — `RETURNING` həmişə sətir verir
            raise RuntimeError("Plugin sətri yaradıla bilmədi")
        plugin_id = str(row["id"])
        _security_log.warning(
            "PLUGIN_ROW_WRITTEN",
            extra={
                "plugin_id": plugin_id,
                "name": manifest.name,
                "version": manifest.version,
                "installed_by": str(installed_by),
            },
        )
        return plugin_id

    def set_status(self, plugin_id: str, status: PluginStatus, *, changed_by: object) -> None:
        approved = status is PluginStatus.APPROVED
        self._execute(
            """
            UPDATE plugins
               SET status      = %s,
                   approved_by = CASE WHEN %s THEN %s::uuid ELSE approved_by END,
                   approved_at = CASE WHEN %s THEN now() ELSE approved_at END
             WHERE id = %s AND tenant_id = %s
            """,
            (status.value, approved, changed_by, approved, plugin_id, self._tenant),
        )
        _log.info(
            "PLUGIN_STATUS_CHANGED",
            extra={"plugin_id": plugin_id, "status": status.value},
        )

    def remove(self, plugin_id: str) -> None:
        self._execute(
            "DELETE FROM plugins WHERE id = %s AND tenant_id = %s",
            (plugin_id, self._tenant),
        )

    @staticmethod
    def _hydrate(row: dict[str, Any]) -> InstalledPlugin:
        return InstalledPlugin(
            plugin_id=str(row["id"]),
            name=str(row["name"]),
            version=str(row["version"]),
            # `publisher` NULL ola bilər (sxem onu məcburi etmir) — ekranda
            # boş xana "naşir yoxdur"u gizlədərdi, halbuki bu, imza
            # yoxlamasının ən vacib sahəsidir.
            publisher=str(row["publisher"] or "Naməlum naşir"),
            status=PluginStatus(str(row["status"])),
            signature_verified=bool(row["signature_verified"]),
        )


class PostgresBackupCatalog(_BaseRepository):
    """`backup_records` — `BackupCatalog` portunun tətbiqi (yalnız OXU).

    YAZI tərəfi burada YOXDUR və bu, qəsdəndir: nüsxə sətrini
    `NightlyBackupService._persist()` yazır, çünki sətir yalnız `pg_dump`
    UĞURLA bitib fayl geri oxunduqdan sonra mənalıdır. İkinci yazı yolu
    açsaydıq, "qeydi var, faylı yox" bərpa nöqtəsi yarana bilərdi.
    """

    def list_available(self, tenant_id: TenantId, *, limit: int = 60) -> list[BackupRecord]:
        """Ən yenidən köhnəyə — ekran ilk sətri "Bu gün" kimi göstərir.

        Müddəti keçmiş sətirlər DƏ qaytarılır: `RestorePoint.is_expired`
        onları ekranda işarələyir. Onları süzsək, istifadəçi "nüsxə yoxdur"
        görər və saxlama müddətinin bitdiyini heç vaxt bilməzdi.
        """
        rows = self._fetch_all(
            """
            SELECT tenant_id, backup_type, storage_ref, size_bytes, checksum,
                   retention_until, created_at
              FROM backup_records
             WHERE tenant_id = %s
             ORDER BY created_at DESC
             LIMIT %s
            """,
            (tenant_id, limit),
        )
        return [self._hydrate(row) for row in rows]

    @staticmethod
    def _hydrate(row: dict[str, Any]) -> BackupRecord:
        return BackupRecord(
            tenant_id=str(row["tenant_id"]),
            backup_type=str(row["backup_type"]),
            storage_ref=str(row["storage_ref"]),
            # `size_bytes` NULL ola bilər (sxemdə NOT NULL deyil) — `0`
            # "ölçü naməlum" deməkdir və `RestorePoint.size_mb` onu 0.0 kimi
            # göstərir; `None` isə hesablamanı `TypeError` ilə çökdürərdi.
            size_bytes=int(row["size_bytes"] or 0),
            checksum=str(row["checksum"]),
            retention_until=row["retention_until"],
            created_at=row["created_at"],
        )


__all__ = ["PostgresBackupCatalog", "PostgresPluginRegistry"]
