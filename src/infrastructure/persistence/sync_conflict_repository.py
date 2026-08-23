"""`sync_conflicts` repository-si (bölmə 5) — Faza 5.

Konflikt sətirlərini `infrastructure/offline/sync.py` YAZIR; bu modul onları
HR-ın həll ekranı üçün OXUYUR, bağlayır və seçilmiş versiyanı HƏDƏF cədvələ
TƏTBİQ EDİR.

Sətir HEÇ VAXT silinmir — `resolved_at` doldurulur. Bölmə 5-in "hər iki
versiya saxlanılır" tələbi həllə də şamil olunur: hansı versiyanın niyə
seçildiyi sonradan sual oluna bilər.

──────────────────────────────────────────────────────────────────────────────
NİYƏ HƏDƏF YAZISI DA BU FAYLDADIR
──────────────────────────────────────────────────────────────────────────────
`apply_local_version()` `fines`/`leave_requests`/`attendance_records` kimi
YAD cədvəllərə yazır, halbuki repository adı `sync_conflicts`-dir. Alternativ
— hər hədəf cədvəlin öz repository-sinə ayrıca metod əlavə etmək — RƏDD
EDİLDİ: konfliktin `local_version`-u aqreqat DEYİL, xam `JSONB` sütun dəstidir
(offline bufer payload-u) və onu `Fine`/`LeaveRequest` entity-sinə çevirmək
mümkün deyil — payload QİSMİ olur, entity isə tam invariant tələb edir.
Yarımçıq entity qurub yadda saxlamaq isə konfliktdə OLMAYAN sahələri də
üzərinə yazardı.

Yazı `sync_conflicts`-in bağlandığı EYNİ bağlantıdan gedir — bu, atomikliyin
mənbəyidir (bax `use_cases/sync_conflicts.py` başlığı).

──────────────────────────────────────────────────────────────────────────────
CƏDVƏL/SÜTUN ADLARI SQL-Ə NECƏ DÜŞÜR
──────────────────────────────────────────────────────────────────────────────
`table_name` və `local_version` açarları son nəticədə MAĞAZA PC-sinin bufer
faylından gəlir. `offline/sync.py`-dakı EYNİ iki qatlı qorunma tətbiq olunur:

    1. Cədvəl adı `SYNCABLE_TABLES` ağ siyahısında olmalıdır.
    2. Sütun adları `information_schema`-dan (parametrləşdirilmiş sorğu)
       təsdiqlənir və `psycopg.sql.Identifier` ilə sitatlanır.

Tanınmayan sütun SÜKUTLA ATILMIR — istisna verilir, çünki atılan sütun
"tətbiq etdim" deyib məlumatın bir hissəsini itirmək olardı.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from psycopg import sql

from src.application.use_cases.sync_conflicts import (
    ConflictItem,
    ConflictResolutionError,
    Resolution,
)
from src.infrastructure.offline.sync import SYNCABLE_TABLES, cast_placeholder, table_columns
from src.infrastructure.persistence.repositories import _BaseRepository
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from src.domain.value_objects.identifiers import EmployeeId, TenantId

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

#: Hədəf sətirdə HEÇ VAXT üzərinə yazılmayan sütunlar.
#:
#: `id` sətrin kimliyidir, `tenant_id` isə kirayəçi izolyasiyasıdır (RLS-in
#: dayaq nöqtəsi). Bufer payload-unda bunlar dəyişmiş olsa belə tətbiq
#: edilməməlidir: `id`-ni dəyişmək başqa sətri əvəz etmək, `tenant_id`-ni
#: dəyişmək isə qeydi BAŞQA ŞİRKƏTƏ köçürmək olardı.
_IMMUTABLE_TARGET_COLUMNS = frozenset({"id", "tenant_id"})


class PostgresSyncConflictRepository(_BaseRepository):
    """`sync_conflicts` — açıq konfliktlər və onların həlli."""

    _SELECT = """
        SELECT id, table_name, record_id, local_version, remote_version, detected_at
        FROM sync_conflicts
    """

    def list_open(self, tenant_id: TenantId, *, limit: int) -> list[ConflictItem]:
        rows = self._fetch_all(
            f"""{self._SELECT}
            WHERE tenant_id = %s AND resolved_at IS NULL
            ORDER BY detected_at
            LIMIT %s
            """,
            (tenant_id, limit),
        )
        return [_row_to_item(row) for row in rows]

    def get(self, conflict_id: object) -> ConflictItem | None:
        row = self._fetch_one(
            f"{self._SELECT} WHERE id = %s AND tenant_id = %s",
            (conflict_id, self._tenant),
        )
        return _row_to_item(row) if row else None

    def open_count(self, tenant_id: TenantId) -> int:
        row = self._fetch_one(
            """
            SELECT count(*) AS total FROM sync_conflicts
             WHERE tenant_id = %s AND resolved_at IS NULL
            """,
            (tenant_id,),
        )
        return int(row["total"]) if row else 0

    def purge_resolved(self, *, cutoff: datetime) -> int:
        """HƏLL EDİLMİŞ və köhnəlmiş konflikt sətirlərini silir (SAAS-6).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ LAZIMDIR
        ──────────────────────────────────────────────────────────────────────
        `sync_conflicts` yalnız BÖYÜYÜRDÜ: həll `resolved_at`-i doldurur, sətri
        SİLMİR. Hər sətrin içində `local_version` + `remote_version` JSON-ları
        var — yəni cədvəl həm yer yeyir, həm də köhnə PII-ni (ad, məbləğ)
        müddətsiz saxlayır. `OfflineBuffer.purge_synced()` və
        `FaceVerificationLogRepository.purge_older_than()` ilə eyni qərar.

        ──────────────────────────────────────────────────────────────────────
        AUDİT İZİ İTMİR
        ──────────────────────────────────────────────────────────────────────
        Həll qərarı `audit_logs`-a AYRICA yazılır (`SYNC_CONFLICT_RESOLVED` —
        `use_cases/sync_conflicts.py`) və orada hər İKİ versiya
        `before_state`-də saxlanılır. Yəni silinən sətir izin NÜSXƏSİDİR,
        özü deyil. `audit_logs`-a bu metod TOXUNMUR (hüquqi iz).

        AÇIQ (`resolved_at IS NULL`) konflikt HEÇ VAXT silinmir — nə qədər
        köhnə olsa da o, HR_Admin-in gözləyən işidir.

        Args:
            cutoff: bu andan ƏVVƏL həll edilmiş sətirlər silinir. Saxlama
                müddəti ÇAĞIRANDAN gəlir (planlayıcı) — repository siyasət
                oxumur (`purge_older_than` ilə eyni imza qərarı).
        """
        return self._execute(
            """
            DELETE FROM sync_conflicts
             WHERE tenant_id = %s
               AND resolved_at IS NOT NULL
               AND resolved_at < %s
            """,
            (self._tenant, cutoff),
        )

    def resolve(
        self,
        conflict_id: object,
        *,
        resolution: Resolution,
        resolved_by: EmployeeId,
        resolved_at: datetime,
        note: str,
    ) -> bool:
        """Konflikti bağlayır — `local_version`/`remote_version` TOXUNULMUR.

        `resolved_at IS NULL` şərti idempotentlik verir: iki HR eyni anda
        eyni konflikti həll etsə, ikincisi heç nə dəyişmir və birincinin
        qərarı qalır (son yazan qazanmır).

        Returns:
            `True` — bu çağırış konflikti SAHİBLƏNDİ; `False` — artıq bağlı
            idi. Əvvəl `None` qaytarılırdı və nəticə sükutla itirdi: çağıran
            "bağladım" zənn edib auditə öz qərarını yazırdı, cədvəldə isə
            başqasının qərarı dururdu. İndi çağıran hədəfə TOXUNMADAN dayanır.
        """
        return (
            self._execute(
                """
            UPDATE sync_conflicts
               SET resolution      = %s,
                   resolved_by     = %s,
                   resolved_at     = %s,
                   resolution_note = %s
             WHERE id = %s AND tenant_id = %s AND resolved_at IS NULL
            """,
                (resolution.value, resolved_by, resolved_at, note, conflict_id, self._tenant),
            )
            > 0
        )

    def apply_local_version(
        self,
        *,
        table_name: str,
        record_id: object,
        local_version: Mapping[str, Any],
    ) -> int:
        """Yerli (offline) versiyanı hədəf sətrə yazır (bax modul başlığı).

        Yalnız `KEPT_LOCAL` üçün çağırılır: konflikt anında hədəfdə UZAQ
        versiya durur, ona görə `KEPT_REMOTE` heç nə yazmır.

        `updated_at` ƏLLƏ TƏYİN EDİLMİR — hər üç hədəf cədvəldə
        `set_updated_at()` BEFORE UPDATE trigger-i var (`schema.sql` §7/§10/§11)
        və o, payload-dakı köhnə dəyəri onsuz da əvəz edir. İkinci yerdə
        təyin etmək "hansı doğrudur" sualı yaradardı.

        Returns:
            Yazılan sətir sayı (0 və ya 1). `0` çağıranda XƏTAYA çevrilir.

        Raises:
            ConflictResolutionError: cədvəl ağ siyahıda deyilsə və ya
                payload-da tanınmayan sütun varsa.
        """
        if table_name not in SYNCABLE_TABLES:
            # Ağ siyahıdan kənar ad `sync_conflicts` sətrinin əl ilə
            # dəyişdirilməsi əlamətidir, sadə səhv deyil.
            raise ConflictResolutionError(
                f"Cədvəl konflikt həllinə icazəli deyil: {table_name}",
                user_message="Bu cədvəl üçün avtomatik tətbiq dəstəklənmir.",
                context={"table": table_name},
            )

        columns = table_columns(self._conn, table_name)
        unknown = set(local_version) - set(columns)
        if unknown:
            raise ConflictResolutionError(
                f"Tanınmayan sütun(lar): {sorted(unknown)}",
                user_message="Yerli versiyada bu cədvələ aid olmayan sahə var.",
                context={"table": table_name, "columns": sorted(unknown)},
            )

        names = sorted(set(local_version) - _IMMUTABLE_TARGET_COLUMNS)
        if not names:
            # Yazılası sütun qalmadı. `0` qaytarılır ki, çağıran tranzaksiyanı
            # geri qaytarsın: "tətbiq etdim" deyib heç nə yazmamaq məhz
            # düzəldilən qüsurun təkrarı olardı.
            _audit_log.error(
                "SYNC_CONFLICT_APPLY_EMPTY",
                extra={"table": table_name, "record_id": str(record_id)},
            )
            return 0

        assignments = [
            sql.SQL("{} = {}").format(sql.Identifier(name), cast_placeholder(columns[name]))
            for name in names
        ]
        statement = sql.SQL(
            "UPDATE {table} SET {assignments} WHERE id = %s AND tenant_id = %s"
        ).format(
            table=sql.Identifier(table_name),
            assignments=sql.SQL(", ").join(assignments),
        )
        # `tenant_id` şərti RLS-ə ƏLAVƏ ikinci qatdır (`_BaseRepository` naxışı):
        # RLS söndürülmüş bir bağlantı belə başqa kirayəçinin sətrinə çata bilməz.
        values = [local_version[name] for name in names]
        with self._conn.cursor() as cur:
            cur.execute(statement, [*values, record_id, self._tenant])
            written = cur.rowcount
        _audit_log.info(
            "SYNC_CONFLICT_LOCAL_VERSION_APPLIED",
            extra={
                "table": table_name,
                "record_id": str(record_id),
                "columns": names,
                "rows": written,
            },
        )
        return int(written)


def _row_to_item(row: dict[str, Any]) -> ConflictItem:
    return ConflictItem(
        conflict_id=row["id"],
        table_name=row["table_name"],
        record_id=row["record_id"],
        local_version=_as_dict(row["local_version"]),
        remote_version=_as_dict(row["remote_version"]),
        detected_at=row["detected_at"],
    )


def _as_dict(raw: Any) -> dict[str, Any]:
    """`JSONB` sütununu sözlüyə çevirir (sürücü artıq obyekt qaytara bilər)."""
    value = json.loads(raw) if isinstance(raw, str) else raw
    return dict(value) if isinstance(value, dict) else {}


__all__ = ["PostgresSyncConflictRepository"]
