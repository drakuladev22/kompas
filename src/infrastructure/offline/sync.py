"""Offline buferin Supabase-ə köçürülməsi və konflikt aşkarlanması — Faza 3.5.

Spesifikasiya bölmə 5: *"Konflikt həlli: audit-kritik cədvəllər
(leave_requests, fines, audit_logs) üçün last-write-wins qəbul edilmir.
Konflikt aşkarlandıqda hər iki versiya saxlanılır, `CONFLICT` statusu ilə
HR_Admin-ə manual həll üçün göndərilir."*

──────────────────────────────────────────────────────────────────────────────
KONFLİKT NECƏ AŞKARLANIR
──────────────────────────────────────────────────────────────────────────────
Hər buferlənmiş yazı özü ilə `base_version` daşıyır — offline düşməzdən əvvəl
oxunan sətrin `updated_at`-ı. Sinxronizasiya anında uzaq sətrin `updated_at`-ı
yenidən oxunur:

    uzaq == base   → heç kim toxunmayıb            → tətbiq et
    uzaq >  base   → kimsə dəyişib (divergensiya)  → cədvəl növündən asılı
    sətir yoxdur   → yeni qeyd                     → tətbiq et

Divergensiyada:
    audit-kritik cədvəl → CONFLICT (hər iki versiya saxlanılır, HR_Admin həll edir)
    digər cədvəl        → last-write-wins (yerli yazı tətbiq olunur, qeydə alınır)

──────────────────────────────────────────────────────────────────────────────
TƏHLÜKƏSİZLİK: CƏDVƏL/SÜTUN ADLARI SQL-Ə NECƏ DÜŞÜR
──────────────────────────────────────────────────────────────────────────────
`table_name` bufer faylından gəlir — yəni MAĞAZA PC-sinin diskindən. Onu
birbaşa SQL-ə yapışdırmaq inyeksiya olardı. İki səviyyəli qorunma:

    1. Cədvəl adı `SYNCABLE_TABLES` ağ siyahısında olmalıdır.
    2. Sütun adları `information_schema`-dan oxunur (parametrləşdirilmiş
       sorğu ilə) və `psycopg.sql.Identifier` ilə sitatlanır.

Payload-da tanınmayan sütun varsa yazı SÜKUTLA ötürülmür — xəta verilir.
Sükutla atmaq "sinxronlaşdı" deyib məlumatı itirmək demək olardı.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from psycopg import sql

from src.domain.policies import SystemLimitKey
from src.infrastructure.config.limits import InfrastructureLimits, fallback_int
from src.infrastructure.offline.buffer import BufferedWrite, OfflineBuffer
from src.infrastructure.persistence.connection import SCHEMA
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from psycopg import Connection

    from src.infrastructure.persistence.connection import Database

_log = get_logger(__name__)
_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

#: Offline buferdən yazıla bilən cədvəllər (ağ siyahı — bax modul başlığı).
SYNCABLE_TABLES: Final[frozenset[str]] = frozenset(
    {"attendance_records", "leave_requests", "fines", "audit_logs"}
)

#: Divergensiya yoxlaması üçün versiya sütunu. `audit_logs` append-only-dir
#: (UPDATE trigger tərəfindən bloklanır), ona görə versiyası yoxdur.
VERSION_COLUMN: Final[dict[str, str | None]] = {
    "attendance_records": "updated_at",
    "leave_requests": "updated_at",
    "fines": "updated_at",
    "audit_logs": None,
}

#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits` (`OFFLINE_SYNC_BATCH_SIZE`,
#: seed: migrations/032). Bir dövrdə neçə yazı tətbiq olunur: offline
#: qaldıqdan sonra bufer minlərlə sətir saxlaya bilər və paketin ölçüsü
#: "nə qədər tez bərpa olsun" ilə "istifadəçi əməliyyatları nə qədər
#: gözləsin" arasındakı tarazlıqdır — o isə mağazanın kanalından asılıdır.
FALLBACK_BATCH_SIZE: Final[int] = fallback_int(SystemLimitKey.OFFLINE_SYNC_BATCH_SIZE)


class SyncError(Exception):
    """Bir yazının tətbiqi uğursuz oldu (növbədə qalır, təkrar cəhd olunur)."""


def cast_placeholder(column_type: tuple[str, str]) -> sql.Composable:
    """`%s::tip` — JSON-dan gələn hər dəyər SƏTİRDİR.

    Payload bufer faylında JSON kimi saxlanılır, yəni `date`, `timestamptz`,
    `uuid`, `numeric` və enum dəyərləri geri oxunanda `str` olur. Açıq cast
    olmasa PostgreSQL "column is of type date but expression is of type text"
    deyə imtina edərdi.

    NİYƏ MODUL SƏVİYYƏSİNDƏ, `OfflineSyncService`-in DAXİLİNDƏ DEYİL: eyni
    JSON→sütun cast qaydası İKİNCİ giriş nöqtəsindən də lazım oldu —
    `PostgresSyncConflictRepository.apply_local_version()` HR-ın seçdiyi yerli
    versiyanı eyni `JSONB` formatından hədəf sətrə yazır. Qaydanı orada təkrar
    yazmaq RƏDD EDİLDİ: massiv istisnası (`_` prefiksi) kimi incəliklər bir
    nüsxədə düzəlib digərində qalardı və nasazlıq yalnız istehsalatda,
    konkret sütun tipində üzə çıxardı.
    """
    udt_schema, udt_name = column_type
    if udt_name.startswith("_"):  # massiv tipi — cast tətbiq edilmir
        return sql.Placeholder()
    return sql.SQL("{}::{}").format(sql.Placeholder(), sql.Identifier(udt_schema, udt_name))


def table_columns(conn: Connection[dict[str, Any]], table_name: str) -> dict[str, tuple[str, str]]:
    """Cədvəlin real sütunları və tipləri — sxem dəyişikliyi ilə sinxron qalır.

    Cədvəl/sütun adları bufer faylından, yəni MAĞAZA PC-sinin diskindən gəlir
    (bax modul başlığı) — onları SQL-ə yapışdırmadan ƏVVƏL bazanın ÖZÜNDƏN
    təsdiqləmək inyeksiyaya qarşı ikinci qatdır. Sorğu parametrləşdirilib.

    Returns:
        `{sütun_adı: (udt_schema, udt_name)}`. Tip `cast_placeholder()`-də
        açıq cast üçün lazımdır.

    Raises:
        SyncError: cədvəl bu sxemdə mövcud deyilsə.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, udt_schema, udt_name
              FROM information_schema.columns
             WHERE table_schema = %s AND table_name = %s
            """,
            (SCHEMA, table_name),
        )
        columns = {
            str(row["column_name"]): (str(row["udt_schema"]), str(row["udt_name"]))
            for row in cur.fetchall()
        }
    if not columns:
        raise SyncError(f"Cədvəl tapılmadı: {table_name}")
    return columns


@dataclass
class SyncReport:
    """Bir `run_once()` çağırışının nəticəsi — health monitor və testlər üçün."""

    attempted: int = 0
    synced: int = 0
    conflicts: int = 0
    failed: int = 0
    skipped_offline: bool = False
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        if self.skipped_offline:
            return "SyncReport(offline — cəhd edilmədi)"
        return (
            f"SyncReport(cəhd={self.attempted}, sinxron={self.synced}, "
            f"konflikt={self.conflicts}, uğursuz={self.failed})"
        )


class OfflineSyncService:
    """Buferi boşaldan servis. Sap yaratmır — planlaşdırma çağıranın işidir."""

    def __init__(
        self,
        *,
        buffer: OfflineBuffer,
        database: Database,
        is_online: Callable[[], bool] | None = None,
        batch_size: int | None = None,
        limits: InfrastructureLimits | None = None,
    ) -> None:
        """
        Args:
            batch_size: AÇIQ üstünlük — verilərsə ROOT dəyəri OXUNMUR.
            limits: `system_limits`-ə açılan pəncərə; verilməzsə fallback.
        """
        self._buffer = buffer
        self._database = database
        self._is_online = is_online or database.health_check
        self._explicit_batch_size = batch_size
        self._limits = limits or InfrastructureLimits()
        self._column_cache: dict[str, dict[str, tuple[str, str]]] = {}

    def _batch_size(self) -> int:
        """Paket ölçüsü — HƏR DÖVRDƏ oxunur.

        Servis uzun ömürlüdür və bərpa dövrü saatlarla çəkə bilər; admin
        yükü azaltmaq üçün paketi ORTADA kiçiltmək istəyə bilər.
        """
        if self._explicit_batch_size is not None:
            return self._explicit_batch_size
        return self._limits.int_of(SystemLimitKey.OFFLINE_SYNC_BATCH_SIZE)

    def run_once(self, *, now: datetime | None = None) -> SyncReport:
        """Hazır olan yazıları tətbiq etməyə cəhd edir."""
        moment = now or datetime.now(UTC)
        report = SyncReport()

        if not self._is_online():
            report.skipped_offline = True
            _log.debug("OFFLINE_SYNC_SKIPPED", extra={"reason": "bağlantı yoxdur"})
            return report

        for write in self._buffer.pending(now=moment, limit=self._batch_size()):
            report.attempted += 1
            try:
                outcome = self._apply(write, now=moment)
            except Exception as exc:  # bir yazının nasazlığı növbəni dayandırmasın
                report.failed += 1
                report.errors.append(f"{write.table_name}/{write.record_id}: {exc}")
                self._buffer.mark_failed(write.id, str(exc), now=moment)
                continue

            if outcome == "CONFLICT":
                report.conflicts += 1
            else:
                report.synced += 1

        if report.attempted:
            _log.info(
                "OFFLINE_SYNC_RUN",
                extra={
                    "attempted": report.attempted,
                    "synced": report.synced,
                    "conflicts": report.conflicts,
                    "failed": report.failed,
                },
            )
        return report

    # ------------------------------ bir yazı --------------------------------- #

    def _apply(self, write: BufferedWrite, *, now: datetime) -> str:
        if write.table_name not in SYNCABLE_TABLES:
            # Ağ siyahıda olmayan cədvəl — bu, bufer faylının dəyişdirilməsi
            # əlamətidir, sadə səhv deyil.
            raise SyncError(f"Cədvəl sinxronizasiyaya icazəli deyil: {write.table_name}")

        from uuid import UUID  # noqa: PLC0415

        from src.domain.value_objects.identifiers import TenantId  # noqa: PLC0415

        tenant_id = TenantId(UUID(write.tenant_id))
        with self._database.unit_of_work(tenant_id) as uow:
            conn = uow.connection
            remote = self._read_remote(conn, write)

            if remote is not None and self._is_diverged(write, remote):
                if write.is_audit_critical:
                    self._record_conflict(conn, write, remote, now=now)
                    uow.commit()
                    self._buffer.mark_conflict(write.id, remote_version=remote, now=now)
                    return "CONFLICT"
                _audit_log.warning(
                    "OFFLINE_SYNC_LAST_WRITE_WINS",
                    extra={
                        "table": write.table_name,
                        "record_id": write.record_id,
                        "reason": "audit-kritik olmayan cədvəl",
                    },
                )

            self._upsert(conn, write)
            uow.commit()

        self._buffer.mark_synced(write.id, now=now)
        return "SYNCED"

    def _read_remote(
        self, conn: Connection[dict[str, Any]], write: BufferedWrite
    ) -> dict[str, Any] | None:
        columns = self._columns(conn, write.table_name)
        query = sql.SQL("SELECT * FROM {} WHERE id = %s").format(sql.Identifier(write.table_name))
        with conn.cursor() as cur:
            cur.execute(query, (write.record_id,))
            row = cur.fetchone()
        if row is None:
            return None
        return {key: value for key, value in row.items() if key in columns}

    @staticmethod
    def _is_diverged(write: BufferedWrite, remote: dict[str, Any]) -> bool:
        version_column = VERSION_COLUMN.get(write.table_name)
        if version_column is None:
            # `audit_logs`: sətir artıq varsa təkrar tətbiqdir (idempotent),
            # divergensiya deyil.
            return False
        if write.base_version is None:
            # Yerli yeni qeyd, uzaqda isə eyni `id` ilə sətir var → divergensiya.
            return True
        remote_version = remote.get(version_column)
        if not isinstance(remote_version, datetime):
            return False
        return remote_version > write.base_version

    def _upsert(self, conn: Connection[dict[str, Any]], write: BufferedWrite) -> None:
        columns = self._columns(conn, write.table_name)
        unknown = set(write.payload) - set(columns)
        if unknown:
            # Sükutla atmaq "sinxronlaşdı" deyib məlumatı itirmək olardı.
            raise SyncError(f"Tanınmayan sütun(lar): {sorted(unknown)}")

        payload = dict(write.payload)
        payload["id"] = write.record_id
        names = sorted(payload)
        values = [payload[name] for name in names]

        identifiers = [sql.Identifier(name) for name in names]
        placeholders = [self._placeholder(columns[name]) for name in names]
        assignments = [
            sql.SQL("{0} = EXCLUDED.{0}").format(sql.Identifier(name))
            for name in names
            if name != "id"
        ]
        if assignments:
            statement = sql.SQL(
                "INSERT INTO {table} ({columns}) VALUES ({values}) "
                "ON CONFLICT (id) DO UPDATE SET {assignments}"
            ).format(
                table=sql.Identifier(write.table_name),
                columns=sql.SQL(", ").join(identifiers),
                values=sql.SQL(", ").join(placeholders),
                assignments=sql.SQL(", ").join(assignments),
            )
        else:  # yalnız `id` — praktikada olmur, lakin SQL sintaksisi pozulmasın
            statement = sql.SQL(
                "INSERT INTO {table} ({columns}) VALUES ({values}) ON CONFLICT (id) DO NOTHING"
            ).format(
                table=sql.Identifier(write.table_name),
                columns=sql.SQL(", ").join(identifiers),
                values=sql.SQL(", ").join(placeholders),
            )
        with conn.cursor() as cur:
            cur.execute(statement, values)

    @staticmethod
    def _placeholder(column_type: tuple[str, str]) -> sql.Composable:
        """Modul səviyyəli `cast_placeholder()`-ə keçid — bax onun docstring-i.

        Metod SAXLANILIR (silinmir): daxili çağırış nöqtələri və onları yoxlayan
        testlər bu adı işlədir, funksiyanın ÖZÜ isə artıq modul səviyyəsindədir
        ki, `sync_conflict_repository` də eyni cast qaydasını TƏKRAR YAZMADAN
        işlədə bilsin (iki nüsxə olsaydı, biri düzələndə digəri arxada qalardı).
        """
        return cast_placeholder(column_type)

    def _record_conflict(
        self,
        conn: Connection[dict[str, Any]],
        write: BufferedWrite,
        remote: dict[str, Any],
        *,
        now: datetime,
    ) -> None:
        """`sync_conflicts` cədvəlinə hər iki versiyanı yazır (bölmə 5)."""
        from json import dumps  # noqa: PLC0415

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sync_conflicts
                    (tenant_id, table_name, record_id, local_version, remote_version, detected_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    write.tenant_id,
                    write.table_name,
                    write.record_id,
                    dumps(write.payload, ensure_ascii=False, default=str),
                    dumps(remote, ensure_ascii=False, default=str),
                    now,
                ),
            )
        _audit_log.critical(
            "SYNC_CONFLICT_RECORDED",
            extra={
                "table": write.table_name,
                "record_id": write.record_id,
                "action": "HR_Admin manual həll etməlidir",
            },
        )

    def _columns(
        self, conn: Connection[dict[str, Any]], table_name: str
    ) -> dict[str, tuple[str, str]]:
        """`table_columns()` üzərinə PROSES-ÖMÜRLÜ keş.

        Keş burada qalır, ortaq funksiyada YOX: servis uzun ömürlüdür və bir
        bərpa dövründə minlərlə yazı eyni cədvələ dəyir. Konflikt həlli isə
        istifadəçi tempində, sessiya-ömürlü repository üzərindən gedir — orada
        keş faydasızdır, sxem dəyişikliyini isə gec görərdi.
        """
        cached = self._column_cache.get(table_name)
        if cached is not None:
            return cached
        columns = table_columns(conn, table_name)
        self._column_cache[table_name] = columns
        return columns


__all__ = [
    "SYNCABLE_TABLES",
    "OfflineSyncService",
    "SyncError",
    "SyncReport",
    "cast_placeholder",
    "table_columns",
]
