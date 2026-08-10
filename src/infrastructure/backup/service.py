"""Gecəlik avtomatik ehtiyat nüsxə infrastrukturu (bölmə 7) — Faza 3.13.

Spesifikasiya: *"bütün tenant bazası hər gecə avtomatik yedəklənir
(nöqtə-zamanlı bərpa dəstəyi ilə, minimum 30 günlük saxlama)"*.
Faza 3, bənd 6: *"özünə-xidmət «Bərpa Et» GUI-si Faza 5-də tikilir, amma
faktiki cron/backend məntiqi burada — infrastruktur qatında — yerləşir"*.

──────────────────────────────────────────────────────────────────────────────
İKİ QAT: PLATFORMA PITR + MƏNTİQİ DUMP
──────────────────────────────────────────────────────────────────────────────
Nöqtə-zamanlı bərpanın (PITR) ÖZÜ Supabase-in platforma xüsusiyyətidir və
tətbiq onu kod ilə yarada bilməz — WAL arxivi server tərəfdədir. Bu modul
İKİNCİ qatı verir: gündəlik məntiqi `pg_dump` nüsxəsi.

Niyə ikinci qat lazımdır, əgər PITR varsa:

    * PITR YALNIZ həmin Supabase layihəsi daxilində bərpa edir. Layihənin
      özü silinsə/hesab bağlansa, PITR də gedir.
    * Məntiqi dump PORTATİVDİR — istənilən PostgreSQL-ə bərpa oluna bilir,
      yəni provayder dəyişikliyi mümkün qalır.
    * "Səhvən silindi" halında bütöv bir vaxt nöqtəsinə qayıtmaq əvəzinə
      TƏK CƏDVƏLİ bərpa etmək olur (`pg_restore -t`).

──────────────────────────────────────────────────────────────────────────────
YAZILDI ≠ YEDƏKLƏNDİ
──────────────────────────────────────────────────────────────────────────────
Fayl yaradıldıqdan sonra GERİ OXUNUR və hash-ı yenidən hesablanır. Doluya
yaxın disk, kəsilən şəbəkə diski və ya sükutla uğursuz `pg_dump` "boş, lakin
mövcud" fayl qoya bilər. Yoxlanmamış ehtiyat nüsxə — nüsxə deyil, ümiddir;
onun yararsızlığı məhz lazım olan gün üzə çıxardı.

──────────────────────────────────────────────────────────────────────────────
ŞİFRƏ ƏMR SƏTRİNDƏ OLMUR
──────────────────────────────────────────────────────────────────────────────
`pg_dump` şifrəni `PGPASSWORD` mühit dəyişənindən oxuyur. DSN-i əmr sətrinə
yazmaq onu həmin maşındakı hər prosesə (`ps`, Task Manager) görünən edərdi.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlparse

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from src.domain.value_objects.identifiers import EmployeeId, TenantId
    from src.infrastructure.persistence.connection import Database

_log = get_logger(__name__)
_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

BACKUP_DIR_ENV: Final[str] = "KOMPASOS_BACKUP_DIR"
#: Spesifikasiya "minimum 30 gün" deyir — konfiqurasiya bundan AŞAĞI düşə bilməz.
MIN_RETENTION_DAYS: Final[int] = 30
DEFAULT_RETENTION_DAYS: Final[int] = 30
#: `pg_dump` bu müddətdən uzun çəkərsə dayandırılır (asılıb qalmış proses
#: gecəlik pəncərəni bloklamamalıdır).
DUMP_TIMEOUT_SECONDS: Final[float] = 60 * 60
CHUNK_SIZE: Final[int] = 1024 * 1024

BACKUP_TYPE_NIGHTLY: Final[str] = "NIGHTLY_AUTO"
BACKUP_TYPE_PRE_MIGRATION: Final[str] = "PRE_MIGRATION"
BACKUP_TYPE_MANUAL: Final[str] = "MANUAL"

#: Bərpa əməliyyatı üçün istifadəçinin yazması tələb olunan ifadə.
#: Bölmə 7: *"aydın xəbərdarlıq/təsdiq addımları ilə"*.
RESTORE_CONFIRMATION: Final[str] = "BƏRPA ET"


class BackupError(KompasOSError):
    """Ehtiyat nüsxə əməliyyatı uğursuz oldu."""

    user_message = "Ehtiyat nüsxə əməliyyatı tamamlanmadı."


class BackupToolMissingError(BackupError):
    """`pg_dump`/`pg_restore` tapılmadı.

    SÜKUTLA "sadə SQL ixracı"na keçmirik: yarımçıq formatda saxlanmış və
    bərpa oluna bilməyən fayl, ümumiyyətlə olmayan fayldan PİSDİR — çünki
    ilkini "yedəyim var" deyə yanlış inam yaradır.
    """

    user_message = (
        "Ehtiyat nüsxə aləti (pg_dump) tapılmadı. PostgreSQL client alətlərini "
        "quraşdırın və ya administratorla əlaqə saxlayın."
    )


class BackupVerificationError(BackupError):
    """Yazılan fayl geri oxuna bilmədi və ya boşdur."""

    user_message = "Ehtiyat nüsxə yaradıldı, lakin yoxlanış uğursuz oldu — nüsxə etibarsız sayılır."


@dataclass(frozen=True)
class BackupRecord:
    """Yaradılmış ehtiyat nüsxə."""

    tenant_id: str
    backup_type: str
    storage_ref: str
    size_bytes: int
    checksum: str
    retention_until: date
    created_at: datetime

    @property
    def path(self) -> Path:
        return Path(self.storage_ref)

    def is_expired(self, today: date) -> bool:
        return today > self.retention_until


class NightlyBackupService:
    """`pg_dump` ilə məntiqi nüsxə + yoxlama + saxlama müddəti idarəsi."""

    def __init__(
        self,
        database: Database,
        *,
        dsn: str = "",
        backup_dir: Path | None = None,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        runner: Callable[[Sequence[str], Mapping[str, str]], subprocess.CompletedProcess[str]]
        | None = None,
        clock: Callable[[], datetime] | None = None,
        tool_locator: Callable[[str], str | None] | None = None,
    ) -> None:
        self._database = database
        self._dsn = dsn or os.environ.get("DATABASE_URL", "")
        self._dir = backup_dir or _default_backup_dir()
        # Spesifikasiya "minimum 30 gün" deyir — aşağı dəyər YUXARI qaldırılır,
        # əks halda bir konfiqurasiya səhvi tələbi sükutla pozardı.
        self._retention_days = max(MIN_RETENTION_DAYS, retention_days)
        self._runner = runner
        self._clock = clock or (lambda: datetime.now(UTC))
        self._locate = tool_locator or shutil.which

    @property
    def retention_days(self) -> int:
        return self._retention_days

    @property
    def backup_dir(self) -> Path:
        return self._dir

    # -------------------------------- yaratma -------------------------------- #

    def create(
        self, tenant_id: TenantId, *, backup_type: str = BACKUP_TYPE_NIGHTLY
    ) -> BackupRecord:
        """Nüsxə yaradır, YOXLAYIR və `backup_records`-a yazır.

        Raises:
            BackupToolMissingError: `pg_dump` yoxdur.
            BackupError: dump uğursuz oldu.
            BackupVerificationError: fayl geri oxuna bilmədi.
        """
        tool = self._locate("pg_dump")
        if tool is None:
            raise BackupToolMissingError("pg_dump tapılmadı", context={"tool": "pg_dump"})
        if not self._dsn:
            raise BackupError("DATABASE_URL təyin edilməyib", context={"env": "DATABASE_URL"})

        moment = self._clock()
        target = self._dir / _file_name(tenant_id, backup_type, moment)
        self._dir.mkdir(parents=True, exist_ok=True)

        completed = self._run_dump(tool, target)
        if completed.returncode != 0:
            target.unlink(missing_ok=True)
            raise BackupError(
                f"pg_dump xəta qaytardı (kod {completed.returncode})",
                context={"stderr": (completed.stderr or "")[:500]},
            )

        checksum, size = self._verify(target)
        record = BackupRecord(
            tenant_id=str(tenant_id),
            backup_type=backup_type,
            storage_ref=str(target),
            size_bytes=size,
            checksum=checksum,
            retention_until=(moment + timedelta(days=self._retention_days)).date(),
            created_at=moment,
        )
        self._persist(tenant_id, record)
        _audit_log.info(
            "BACKUP_CREATED",
            extra={
                "tenant_id": str(tenant_id),
                "type": backup_type,
                "size_bytes": size,
                "retention_until": record.retention_until.isoformat(),
            },
        )
        return record

    def _run_dump(self, tool: str, target: Path) -> subprocess.CompletedProcess[str]:
        # `-Fc` — custom format: sıxılmış, seçmə bərpaya (`pg_restore -t`) imkan verir.
        # `--no-owner`/`--no-privileges` — bərpa fərqli rol adı ilə də işləsin.
        command = [
            tool,
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(target),
            _dsn_without_password(self._dsn),
        ]
        environment = {**os.environ, **_password_env(self._dsn)}
        runner = self._runner or self._default_runner
        try:
            return runner(command, environment)
        except subprocess.TimeoutExpired as exc:
            target.unlink(missing_ok=True)
            raise BackupError(
                "pg_dump vaxtında tamamlanmadı", context={"timeout_seconds": DUMP_TIMEOUT_SECONDS}
            ) from exc
        except OSError as exc:
            target.unlink(missing_ok=True)
            raise BackupError("pg_dump icra edilə bilmədi", context={"error": str(exc)}) from exc

    def _default_runner(
        self, command: Sequence[str], environment: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 — alət yolu `shutil.which`-dən, arqumentlər sabitdir
            list(command),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=DUMP_TIMEOUT_SECONDS,
            check=False,
            env=dict(environment),
        )

    def _verify(self, target: Path) -> tuple[str, int]:
        """Faylı GERİ OXUYUR (bax modul başlığı: yazıldı ≠ yedəkləndi)."""
        try:
            size = target.stat().st_size
            digest = hashlib.sha256()
            with target.open("rb") as handle:
                for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
                    digest.update(chunk)
        except OSError as exc:
            target.unlink(missing_ok=True)
            raise BackupVerificationError(
                "Ehtiyat nüsxə geri oxuna bilmədi", context={"error": str(exc)}
            ) from exc

        if size == 0:
            target.unlink(missing_ok=True)
            raise BackupVerificationError("Ehtiyat nüsxə boşdur", context={"file": target.name})
        return digest.hexdigest(), size

    def _persist(self, tenant_id: TenantId, record: BackupRecord) -> None:
        try:
            with self._database.unit_of_work(tenant_id) as uow:
                with uow.connection.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO backup_records
                            (tenant_id, backup_type, storage_ref, size_bytes,
                             checksum, retention_until)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            tenant_id,
                            record.backup_type,
                            record.storage_ref,
                            record.size_bytes,
                            record.checksum,
                            record.retention_until,
                        ),
                    )
                uow.commit()
        except Exception as exc:
            # Fayl YERİNDƏDİR — yalnız qeyd alınmadı. Faylı silmək burada
            # ƏSL nüsxəni məhv etmək olardı; qeyd sonradan bərpa oluna bilər.
            _log.error(
                "BACKUP_RECORD_WRITE_FAILED",
                extra={"file": record.storage_ref, "error": str(exc)},
            )

    # -------------------------------- təmizləmə ------------------------------- #

    def prune(self, tenant_id: TenantId) -> int:
        """Saxlama müddəti bitmiş FAYLLARI silir. Qaytarır: silinən sayı.

        DB sətirlərini `cron_prune_expired_backups()` təmizləyir (schema.sql).
        Fayl sistemi isə SQL-dən görünmür — bu addım olmasa disk dolardı və
        gecəlik nüsxə bir gün sükutla dayanardı.
        """
        today = self._clock().date()
        removed = 0
        for row in self._expired_rows(tenant_id, today):
            path = Path(str(row["storage_ref"]))
            try:
                if path.exists():
                    path.unlink()
                    removed += 1
            except OSError as exc:
                _log.warning("BACKUP_PRUNE_FAILED", extra={"file": str(path), "error": str(exc)})
        if removed:
            _log.info("BACKUP_PRUNED", extra={"removed": removed, "tenant_id": str(tenant_id)})
        return removed

    def _expired_rows(self, tenant_id: TenantId, today: date) -> list[dict[str, Any]]:
        try:
            with self._database.unit_of_work(tenant_id) as uow, uow.connection.cursor() as cur:
                cur.execute(
                    """
                    SELECT storage_ref FROM backup_records
                     WHERE retention_until < %s AND restored_at IS NULL
                    """,
                    (today,),
                )
                return [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            _log.warning("BACKUP_PRUNE_QUERY_FAILED", extra={"error": str(exc)})
            return []

    # --------------------------------- bərpa ---------------------------------- #

    def restore(
        self,
        record: BackupRecord,
        *,
        target_dsn: str,
        confirmation: str,
        actor_id: EmployeeId | None = None,
    ) -> None:
        """Nüsxəni `target_dsn`-ə bərpa edir.

        ────────────────────────────────────────────────────────────────────
        NİYƏ AÇIQ TƏSDİQ İFADƏSİ TƏLƏB OLUNUR
        ────────────────────────────────────────────────────────────────────
        Bərpa MÖVCUD məlumatın üzərinə yazır — səhv çağırış bir günlük
        davamiyyəti, cəriməni və satışı geri qaytarardı. Bölmə 7 "aydın
        xəbərdarlıq/təsdiq addımları" tələb edir; `bool` bayraq isə səhvən
        `True` ötürülə bilər. Yazılmış ifadə təsadüfən yaranmır.

        ────────────────────────────────────────────────────────────────────
        NİYƏ `target_dsn` MƏCBURİ PARAMETRDİR
        ────────────────────────────────────────────────────────────────────
        Defolt olaraq CARİ bazanı götürsəydi, bir sətir kod istehsalat
        bazasının üzərinə yazardı. Hədəfi hər dəfə AÇIQ göstərmək bunu
        şüurlu qərara çevirir.
        """
        if confirmation.strip().upper() != RESTORE_CONFIRMATION:
            raise BackupError(
                "Bərpa təsdiqlənmədi",
                user_message=f"Bərpa üçün «{RESTORE_CONFIRMATION}» yazmalısınız.",
                context={"expected": RESTORE_CONFIRMATION},
            )

        tool = self._locate("pg_restore")
        if tool is None:
            raise BackupToolMissingError("pg_restore tapılmadı", context={"tool": "pg_restore"})

        source = record.path
        if not source.exists():
            raise BackupError("Ehtiyat nüsxə faylı tapılmadı", context={"file": str(source)})

        actual = _sha256_of(source)
        if actual != record.checksum:
            # PRE-FLIGHT CHECKSUM (bölmə 1: "məcburi pre-flight checksum
            # yoxlaması"): zədələnmiş nüsxədən bərpa, bərpa etməməkdən pisdir.
            raise BackupVerificationError(
                "Ehtiyat nüsxənin checksum-u uyğun gəlmir",
                context={"expected": record.checksum, "actual": actual},
            )

        command = [
            tool,
            "--clean",
            "--if-exists",
            "--no-owner",
            "--dbname",
            _dsn_without_password(target_dsn),
            str(source),
        ]
        environment = {**os.environ, **_password_env(target_dsn)}
        _audit_log.critical(
            "BACKUP_RESTORE_STARTED",
            extra={
                "file": source.name,
                "tenant_id": record.tenant_id,
                "actor_id": str(actor_id) if actor_id else None,
            },
        )
        runner = self._runner or self._default_runner
        completed = runner(command, environment)
        if completed.returncode != 0:
            raise BackupError(
                f"pg_restore xəta qaytardı (kod {completed.returncode})",
                context={"stderr": (completed.stderr or "")[:500]},
            )
        _audit_log.critical(
            "BACKUP_RESTORE_COMPLETED",
            extra={"file": source.name, "tenant_id": record.tenant_id},
        )


def _default_backup_dir() -> Path:
    override = os.environ.get(BACKUP_DIR_ENV)
    if override:
        return Path(override)
    base = os.environ.get("PROGRAMDATA") or os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "KompasOS" / "backups"


def _file_name(tenant_id: TenantId, backup_type: str, moment: datetime) -> str:
    stamp = moment.strftime("%Y%m%d-%H%M%S")
    return f"kompasos-{str(tenant_id)[:8]}-{backup_type.lower()}-{stamp}.dump"


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _password_env(dsn: str) -> dict[str, str]:
    """DSN-dəki şifrəni `PGPASSWORD`-ə köçürür (bax modul başlığı)."""
    password = urlparse(dsn).password
    return {"PGPASSWORD": password} if password else {}


def _dsn_without_password(dsn: str) -> str:
    """Şifrəsiz DSN — əmr sətrinə yalnız bu düşür."""
    parsed = urlparse(dsn)
    if not parsed.password:
        return dsn
    netloc = parsed.netloc.replace(f":{parsed.password}@", "@", 1)
    return parsed._replace(netloc=netloc).geturl()


__all__ = [
    "BACKUP_DIR_ENV",
    "BACKUP_TYPE_MANUAL",
    "BACKUP_TYPE_NIGHTLY",
    "BACKUP_TYPE_PRE_MIGRATION",
    "MIN_RETENTION_DAYS",
    "RESTORE_CONFIRMATION",
    "BackupError",
    "BackupRecord",
    "BackupToolMissingError",
    "BackupVerificationError",
    "NightlyBackupService",
]
