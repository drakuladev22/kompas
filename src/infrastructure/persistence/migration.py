"""Baza keçidinin infrastruktur tərəfi (bölmə 2).

    PostgresMigrationEventLog  — `db_migration_events` jurnalı
    SessionReadOnlyController  — aktiv sessiyaların yalnız-oxu rejimi
    BufferDrainAdapter         — `OfflineBuffer`-i porta uyğunlaşdırır
    PgDumpMigrator             — faktiki köçürmə + barmaq izi

──────────────────────────────────────────────────────────────────────────────
BARMAQ İZİ NECƏ HESABLANIR
──────────────────────────────────────────────────────────────────────────────
Hər tenant-a aid cədvəlin sətir sayı + `md5` aqreqatı birləşdirilib bir
`sha256`-ya çevrilir. Tam `pg_dump` müqayisəsi seçilmədi, çünki dump-da
sıralama, sıxılma və zaman möhürləri fərqlənə bilər — eyni məlumat üçün
FƏRQLİ bayt axını verib yalançı uğursuzluq yaradardı.

Sıralama AÇIQ şəkildə `ORDER BY` ilə sabitlənir: `md5(string_agg(...))`
sətirlərin gəliş sırasından asılıdır və onsuz eyni baza iki dəfə fərqli
barmaq izi verərdi.

──────────────────────────────────────────────────────────────────────────────
YALNIZ-OXU REJİMİ NİYƏ TƏTBİQ SƏVİYYƏSİNDƏDİR
──────────────────────────────────────────────────────────────────────────────
`ALTER DATABASE ... SET default_transaction_read_only` bütün bazaya təsir
edir və miqrasiyanın ÖZÜNÜ də bloklayardı. Ona görə bayraq `system_limits`
cədvəlində saxlanılır və tətbiq onu hər yazı əməliyyatından əvvəl oxuyur —
miqrasiya prosesi isə bu yoxlamadan kənardır.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from src.domain.value_objects.infrastructure import (
    DatabaseTarget,
    MigrationError,
    MigrationStatus,
)
from src.infrastructure.persistence.dsn import dsn_without_password, password_env
from src.infrastructure.persistence.repositories import _BaseRepository
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from src.domain.value_objects.identifiers import EmployeeId, TenantId
    from src.domain.value_objects.infrastructure import ChecksumPair
    from src.infrastructure.offline.buffer import OfflineBuffer

_log = get_logger(__name__)
_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Yalnız-oxu bayrağının `system_limits`-dəki açarı.
READ_ONLY_LIMIT_KEY: Final[str] = "MAINTENANCE_READ_ONLY"

#: Barmaq izinə daxil edilən cədvəllər. Siyahı AÇIQ yazılır: `information_schema`
#: üzərindən avtomatik toplasaydıq, müvəqqəti/köməkçi cədvəllər də daxil olar və
#: eyni məlumat üçün fərqli nəticə çıxardı.
CHECKSUM_TABLES: Final[tuple[str, ...]] = (
    "employees",
    "positions",
    "stores",
    "leave_requests",
    "attendance_records",
    "fines",
    "fine_appeals",
    "tasks",
    "shift_assignments",
    "points_ledger",
    "sales_transactions",
    "audit_logs",
)


class SessionReadOnlyController(_BaseRepository):
    """Aktiv sessiyaları yalnız-oxu rejiminə keçirir (modul başlığına bax)."""

    def enter_read_only(self, tenant_id: TenantId, *, reason: str) -> None:
        self._execute(
            """
            INSERT INTO system_limits (tenant_id, limit_key, limit_value)
            VALUES (%s, %s, %s)
            ON CONFLICT (tenant_id, limit_key)
            DO UPDATE SET limit_value = EXCLUDED.limit_value, changed_at = now()
            """,
            (tenant_id, READ_ONLY_LIMIT_KEY, reason),
        )
        _log.warning("MAINTENANCE_READ_ONLY_ON", extra={"tenant_id": str(tenant_id)})

    def leave_read_only(self, tenant_id: TenantId) -> None:
        self._execute(
            "DELETE FROM system_limits WHERE tenant_id = %s AND limit_key = %s",
            (tenant_id, READ_ONLY_LIMIT_KEY),
        )
        _log.info("MAINTENANCE_READ_ONLY_OFF", extra={"tenant_id": str(tenant_id)})

    def is_read_only(self, tenant_id: TenantId) -> bool:
        row = self._fetch_one(
            "SELECT 1 FROM system_limits WHERE tenant_id = %s AND limit_key = %s",
            (tenant_id, READ_ONLY_LIMIT_KEY),
        )
        return row is not None


class BufferDrainAdapter:
    """`OfflineBuffer`-i `OfflineBufferDrain` portuna uyğunlaşdırır.

    ──────────────────────────────────────────────────────────────────────────
    `tenant_id` ARTIQ İSTİFADƏ OLUNUR (D2 izolyasiya auditi)
    ──────────────────────────────────────────────────────────────────────────
    Əvvəl bu arqument QƏBUL EDİLİR, LAKİN İSTİFADƏ EDİLMİRDİ — «bir mağaza
    PC-si = bir tenant» fərziyyəsi ilə. Fərziyyə maşın tenant DƏYİŞDİRİLƏRƏK
    yenidən quraşdırılanda (və ya köhnə bufer faylı silinmədikdə) POZULUR:
    SQLite faylı DATA QOVLUĞUNA bağlıdır, kirayəçiyə YOX. Nəticədə ekrandakı
    «gözləyən yazı» sayğacı köhnə kirayəçinin heç vaxt boşalmayacaq
    sətirlərini də göstərirdi. Eyni qərar `EvidenceUploadQueue`-nun
    `tenant_id` konstruktor arqumentində verilmişdi.
    """

    def __init__(
        self,
        buffer: OfflineBuffer,
        *,
        sync_runner: Callable[[], int] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._buffer = buffer
        #: Sinxronizasiyanı işə salan funksiya. `None` → yalnız sayğac oxunur
        #: (bufer öz planlayıcısı ilə boşalır).
        self._sync_runner = sync_runner
        #: Vaxt mənbəyi — `pending()` geri-çəkilmə cədvəlini vaxta görə süzür,
        #: ona görə testdə sabitlənə bilməlidir.
        self._now = now or (lambda: datetime.now(UTC))

    @property
    def buffer(self) -> OfflineBuffer:
        """Sarılmış bufer — Faza 5.1 nəzarətçisi onun YAŞINI ölçür.

        AÇIQ ƏLÇATANLIQ QƏSDLİDİR: `OfflineBacklogMonitor` `pending_count()`
        ilə kifayətlənə bilməz (say həddi yaş həddini GÖRMÜR, bax
        `offline/backlog.py`), lakin adapteri həmin metodlarla şişirtmək
        `OfflineBufferDrain` portunu ONA aid olmayan sorğularla doldurardı —
        port baza KEÇİDİ üçündür, sağlamlıq nəzarəti üçün yox.
        """
        return self._buffer

    def pending_count(self, tenant_id: TenantId) -> int:
        return len(self._buffer.pending(now=self._now(), tenant_id=str(tenant_id)))

    def flush(self, tenant_id: TenantId) -> int:
        """Növbəni boşaltmağa cəhd edir və QALAN sətir sayını qaytarır."""
        if self._sync_runner is not None:
            try:
                self._sync_runner()
            except Exception as exc:
                _error_log.error("BUFFER_FLUSH_FAILED", extra={"error": str(exc)})
        return self.pending_count(tenant_id)


class PgDumpMigrator:
    """`pg_dump`/`pg_restore` əsaslı köçürmə.

    DSN-lər KONSTRUKTORDA verilir — bu sinif credential oxumur və onları
    log-a yazmır (`--dbname` arqumenti `subprocess`-ə siyahı kimi ötürülür,
    qabıqdan keçmir).

    ──────────────────────────────────────────────────────────────────────────
    ŞİFRƏ ƏMR SƏTRİNƏ DÜŞMÜR
    ──────────────────────────────────────────────────────────────────────────
    Qabıqdan keçməmək KİFAYƏT DEYİL: arqument siyahısının özü prosesin əmr
    sətridir və eyni maşındakı hər proses onu oxuya bilir (`ps`, Process
    Explorer). Ona görə DSN `dsn_without_password()` ilə bölünür, şifrə isə
    `PGPASSWORD` mühit dəyişəni ilə ötürülür — gecəlik ehtiyat nüsxə
    xidmətindəki EYNİ mexanizm (`persistence/dsn.py`).
    """

    def __init__(
        self,
        *,
        dsn_by_target: dict[DatabaseTarget, str],
        checksum_reader: Callable[[str, str], Any] | None = None,
        runner: Callable[[Sequence[str]], int] | None = None,
        on_switch: Callable[[DatabaseTarget], None] | None = None,
    ) -> None:
        self._dsn = dsn_by_target
        self._checksum_reader = checksum_reader
        #: Kənardan verilən icraçı (test/xüsusi mühit). İmzası DƏYİŞMİR —
        #: ona yalnız şifrəsiz əmr sətri gedir, mühit dəyişəni isə daxili
        #: icraçının işidir (bax `_invoke`).
        self._external_runner = runner
        self._runner = runner or self._run
        self._on_switch = on_switch
        self._active: DatabaseTarget | None = None

    # ------------------------------ barmaq izi ------------------------------- #

    def checksum(self, target: DatabaseTarget) -> str:
        """Bazanın sabit barmaq izi (modul başlığına bax)."""
        if self._checksum_reader is None:
            raise MigrationError(
                "Barmaq izi oxuyucusu konfiqurasiya edilməyib",
                user_message="Baza yoxlaması aparıla bilmədi.",
            )

        digest = hashlib.sha256()
        for table in CHECKSUM_TABLES:
            # `to_jsonb` sütun sırasından asılı olmayan sabit təsvir verir;
            # `ORDER BY` isə sətir sırasını sabitləyir (başlıqdakı izah).
            value = self._checksum_reader(
                self._require_dsn(target),
                f"SELECT count(*)::text || ':' || "  # noqa: S608 — cədvəl adı sabit siyahıdandır
                f"coalesce(md5(string_agg(t.row_text, '' ORDER BY t.row_text)), '') "
                f"FROM (SELECT to_jsonb(x)::text AS row_text FROM {table} x) t",
            )
            digest.update(f"{table}={value}\n".encode())
        return digest.hexdigest()

    # -------------------------------- köçürmə -------------------------------- #

    def copy(self, *, source: DatabaseTarget, destination: DatabaseTarget) -> None:
        """`pg_dump | pg_restore` — məlumatı hədəfə köçürür.

        Arqumentlərə ŞİFRƏSİZ DSN gedir; şifrə `_invoke` içində mühit
        dəyişəninə keçir (bax sinif başlığı). Əmrlərin özü, sırası və xəta
        mesajları dəyişməyib.
        """
        source_dsn = self._require_dsn(source)
        destination_dsn = self._require_dsn(destination)

        code = self._invoke(
            [
                "pg_dump",
                "--dbname",
                dsn_without_password(source_dsn),
                "--format",
                "custom",
                "--no-owner",
                "--no-privileges",
                "--file",
                "-",
            ],
            dsn=source_dsn,
        )
        if code != 0:
            raise MigrationError(
                f"`pg_dump` {code} kodu ilə dayandı",
                user_message="Məlumatın oxunması alınmadı.",
            )

        code = self._invoke(
            [
                "pg_restore",
                "--dbname",
                dsn_without_password(destination_dsn),
                "--clean",
                "--if-exists",
                "-",
            ],
            dsn=destination_dsn,
        )
        if code != 0:
            raise MigrationError(
                f"`pg_restore` {code} kodu ilə dayandı",
                user_message="Məlumatın yazılması alınmadı.",
            )

    def switch_active(self, target: DatabaseTarget) -> None:
        self._active = target
        if self._on_switch is not None:
            self._on_switch(target)
        _log.warning("ACTIVE_DATABASE_SWITCHED", extra={"target": target.value})

    def rollback(self, *, to: DatabaseTarget, reason: str) -> None:
        """Aktiv bazanı geri qaytarır.

        Hədəfdəki YARIMÇIQ məlumat SİLİNMİR: onu silmək üçün növbəti cəhd
        onsuz da `--clean` ilə başlayır, silmə cəhdi isə bu ən həssas anda
        ikinci bir uğursuzluq mənbəyi olardı.
        """
        self.switch_active(to)
        _error_log.warning("DATABASE_ROLLED_BACK", extra={"target": to.value, "reason": reason})

    @property
    def active(self) -> DatabaseTarget | None:
        return self._active

    def _require_dsn(self, target: DatabaseTarget) -> str:
        dsn = self._dsn.get(target)
        if not dsn:
            raise MigrationError(
                f"«{target.label_az}» üçün bağlantı ünvanı təyin edilməyib",
                user_message=f"{target.label_az} bağlantısı konfiqurasiya edilməyib.",
                context={"target": target.value},
            )
        return dsn

    def _invoke(self, command: Sequence[str], *, dsn: str) -> int:
        """Əmri icra edir; şifrəni əmr sətrindən AYIRIB mühitə ötürür.

        Kənardan `runner` verilibsə o, köhnə imzası ilə (yalnız əmr siyahısı)
        çağırılır — ona onsuz da şifrəsiz sətir gedir və test qoşquları
        dəyişməli olmur. Mühit dəyişəni yalnız daxili icraçıya lazımdır.
        """
        if self._external_runner is None:
            return self._run(command, {**os.environ, **password_env(dsn)})
        return self._runner(command)

    @staticmethod
    def _run(command: Sequence[str], environment: Mapping[str, str] | None = None) -> int:
        # `shell=False` (defolt): arqumentlər qabıqdan keçmir. Şifrə isə
        # arqument DEYİL — `environment` içindəki `PGPASSWORD`-dədir.
        completed = subprocess.run(  # noqa: S603
            command,
            check=False,
            capture_output=True,
            env=dict(environment) if environment is not None else None,
        )
        if completed.returncode != 0:
            _error_log.error(
                "MIGRATION_COMMAND_FAILED",
                extra={"command": command[0], "code": completed.returncode},
            )
        return completed.returncode


class PostgresMigrationEventLog(_BaseRepository):
    """`db_migration_events` — keçid tarixçəsi (bölmə 2)."""

    def start(
        self,
        *,
        tenant_id: TenantId,
        initiated_by: EmployeeId,
        source: DatabaseTarget,
        destination: DatabaseTarget,
        window_start: datetime,
    ) -> str:
        row = self._fetch_one(
            """
            INSERT INTO db_migration_events
                (tenant_id, initiated_by, source_target, destination_target,
                 maintenance_window_start, status)
            VALUES (%s, %s, %s, %s, %s, 'IN_PROGRESS')
            RETURNING id
            """,
            (tenant_id, initiated_by, source.value, destination.value, window_start),
        )
        if row is None:  # pragma: no cover — `RETURNING` həmişə sətir verir
            raise MigrationError("Keçid hadisəsi yaradıla bilmədi")
        return str(row["id"])

    def finish(
        self,
        event_id: str,
        *,
        status: MigrationStatus,
        checksums: ChecksumPair | None = None,
        buffer_flushed: bool = False,
        rolled_back: bool = False,
        rollback_reason: str | None = None,
        window_end: datetime | None = None,
    ) -> None:
        self._execute(
            """
            UPDATE db_migration_events
               SET status                   = %s,
                   preflight_checksum       = %s,
                   postflight_checksum      = %s,
                   checksum_matched         = %s,
                   pending_buffer_flushed   = %s,
                   rolled_back              = %s,
                   rollback_reason          = %s,
                   maintenance_window_end   = %s
             WHERE id = %s
            """,
            (
                status.value,
                checksums.preflight if checksums else None,
                checksums.postflight if checksums else None,
                checksums.matched if checksums else None,
                buffer_flushed,
                rolled_back,
                rollback_reason,
                window_end,
                event_id,
            ),
        )

    def history(self, tenant_id: TenantId, *, limit: int = 20) -> list[dict[str, Any]]:
        return self._fetch_all(
            """
            SELECT id, source_target, destination_target, status,
                   checksum_matched, rolled_back, rollback_reason,
                   maintenance_window_start, maintenance_window_end, created_at
              FROM db_migration_events
             WHERE tenant_id = %s
             ORDER BY created_at DESC
             LIMIT %s
            """,
            (tenant_id, limit),
        )


def read_scalar(dsn: str, sql: str) -> str:
    """`PgDumpMigrator(checksum_reader=...)` üçün hazır oxuyucu.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ AYRICA BAĞLANTI
    ──────────────────────────────────────────────────────────────────────────
    Barmaq izi HƏR İKİ bazadan oxunur — mənbədən və HƏDƏFDƏN. Hədəf isə
    tətbiqin cari `Database` pool-unda YOXDUR (ona hələ keçilməyib), ona görə
    burada DSN-ə birbaşa qoşulmaqdan başqa yol yoxdur. Bağlantı sorğudan
    sonra dərhal bağlanır: keçid saatlarla açıq qalan panel deyil, bir dəfəlik
    texniki pəncərədir.

    Şifrə DSN-in İÇİNDƏDİR və heç bir yerə yazılmır (`psycopg` onu əmr sətrinə
    çıxarmır) — bu, `PgDumpMigrator._invoke`-dakı `PGPASSWORD` mexanizmindən
    fərqlidir, çünki orada xarici PROSES işə düşür, burada isə kitabxana.
    """
    import psycopg  # noqa: PLC0415

    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()
    # Boş nəticə "cədvəl boşdur" deməkdir və barmaq izinə boş sətir kimi
    # daxil olur — istisna atmaq keçidi konfiqurasiya səhvi kimi göstərərdi.
    return "" if row is None else str(row[0])


__all__ = [
    "CHECKSUM_TABLES",
    "READ_ONLY_LIMIT_KEY",
    "BufferDrainAdapter",
    "PgDumpMigrator",
    "PostgresMigrationEventLog",
    "SessionReadOnlyController",
    "read_scalar",
]
