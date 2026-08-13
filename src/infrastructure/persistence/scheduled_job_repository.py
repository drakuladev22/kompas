"""Planlanmış işin icarə/nəticə saxlaması — `app_scheduled_job_runs` (Faza 11).

QAYDA (bölmə 2): 100% parameterləşdirilmiş SQL. RLS-Ə ƏLAVƏ İKİNCİ QAT: hər
sorğuda açıq `tenant_id` şərti var (layihənin bütün repo-larında eyni naxış).

──────────────────────────────────────────────────────────────────────────────
YARIŞ QAPAĞI BU FAYLDA YAŞAYIR
──────────────────────────────────────────────────────────────────────────────
`acquire()` NƏ `SELECT`-lə başlayır, NƏ də UPSERT edir. O, İKİ addımdan
ibarətdir və hər ikisi ATOMİKDİR:

    1) INSERT ... ON CONFLICT (tenant_id, job_key, scheduled_for) DO NOTHING
       → `rowcount == 1` isə icarə BU instansiyanındır. İki terminal eyni anda
         gələndə PostgreSQL unikal indeksi yalnız birini keçirir; ikincisi 0
         sətir yazır və heç bir istisna almır.

    2) (yalnız 1-ci 0 qaytardısa) ŞƏRTLİ UPDATE:
       WHERE ... AND attempts < %s
         AND (status = 'FAILED' OR (status = 'RUNNING' AND leased_until <= %s))
       → `rowcount == 1` isə icarə GERİ GÖTÜRÜLDÜ (çökmüş instansiya və ya
         uğursuz cəhd). Şərt SORĞUNUN İÇİNDƏDİR: onu Python-da yoxlamaq oxu
         ilə yazı arasında pəncərə qoyardı və iki terminal eyni işi
         "bərpa edərdi" (`open_shift_repository.claim` ilə eyni qərar).

`SUCCEEDED` sətir heç bir şərtə uymur — yəni tamamlanmış slot bir daha
götürülə bilmir. Bu, idempotentlik zəmanətinin ÖZÜDÜR və üçüncü qat
DB trigger-idir (`migrations/036`: `SUCCEEDED` statusundan çıxış qadağandır).

──────────────────────────────────────────────────────────────────────────────
NİYƏ `PostgresUnitOfWork`-Ə QOŞULMUR — HƏR METOD ÖZ TRANZAKSİYASINDADIR
──────────────────────────────────────────────────────────────────────────────
Digər repo-lar `_BaseRepository`-dən miras alır və çağıranın tranzaksiyasında
işləyir. Burada bu, MÜDAFİƏNİ SÖNDÜRƏRDİ:

  * icarə çağıranın tranzaksiyasında qalsaydı, digər terminal onu YALNIZ iş
    bitəndən sonra görərdi — yəni "icarə var" faktı icra müddətində gizli
    qalar və hər iki terminal işi paralel başlayardı;
  * ağır iş (`pg_dump`) dəqiqələrlə çəkir; həmin müddət boyu açıq tranzaksiya
    saxlamaq CLAUDE.md §6-nın açıq qadağasıdır (uzun-ömürlü tranzaksiya kilid
    saxlayır).

Naxış `PostgresNotifier` ilə eynidir: `Database` alır, hər əməliyyat üçün
qısa `unit_of_work` açır və DƏRHAL commit edir.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.domain.value_objects.identifiers import TenantId
from src.domain.value_objects.job_runs import (
    JobRunStatus,
    ScheduledJobRun,
    normalize_job_key,
    trim_error_text,
)
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from src.infrastructure.persistence.connection import Database

_log = get_logger(__name__)

_SELECT = """
    SELECT tenant_id, job_key, scheduled_for, status, leased_by, leased_until,
           started_at, finished_at, attempts, last_error, result_detail
      FROM app_scheduled_job_runs
"""


class PostgresScheduledJobRepository:
    """`ScheduledJobRepository` portunun tətbiqi."""

    def __init__(self, database: Database) -> None:
        self._database = database

    # -------------------------------- icarə ----------------------------------- #

    def acquire(
        self,
        *,
        tenant_id: TenantId,
        job_key: str,
        scheduled_for: datetime,
        instance_id: str,
        now: datetime,
        leased_until: datetime,
        max_attempts: int,
    ) -> bool:
        """İcarəni atomik götürür — bax modul başlığı (iki addım, hər ikisi DB-də)."""
        key = normalize_job_key(job_key)
        with self._database.unit_of_work(tenant_id) as uow:
            with uow.connection.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO app_scheduled_job_runs
                        (tenant_id, job_key, scheduled_for, status, leased_by,
                         leased_until, started_at, attempts)
                    VALUES (%s, %s, %s, 'RUNNING', %s, %s, %s, 1)
                    ON CONFLICT (tenant_id, job_key, scheduled_for) DO NOTHING
                    """,
                    (tenant_id, key, scheduled_for, instance_id, leased_until, now),
                )
                inserted = cur.rowcount
                if inserted == 1:
                    uow.commit()
                    return True

                # İkinci addım: mövcud sətir GERİ GÖTÜRÜLƏ bilərmi?
                # `finished_at = NULL` MƏCBURİDİR — `chk_job_run_finished`
                # məhdudiyyəti `RUNNING` sətirdə bitmə anı olmasına icazə
                # vermir (yarımçıq "həm işləyir, həm bitib" sətri yaranmasın).
                cur.execute(
                    """
                    UPDATE app_scheduled_job_runs
                       SET status       = 'RUNNING',
                           leased_by    = %s,
                           leased_until = %s,
                           started_at   = %s,
                           finished_at  = NULL,
                           attempts     = attempts + 1
                     WHERE tenant_id = %s
                       AND job_key = %s
                       AND scheduled_for = %s
                       AND attempts < %s
                       AND (
                             status = 'FAILED'
                          OR (status = 'RUNNING' AND leased_until <= %s)
                           )
                    """,
                    (
                        instance_id,
                        leased_until,
                        now,
                        tenant_id,
                        key,
                        scheduled_for,
                        max_attempts,
                        # SƏRHƏD: `<=` — icarə bitmə anında ARTIQ bitmiş sayılır
                        # (`ScheduledJobRun.is_lease_expired` ilə eyni operator;
                        # birini dəyişən digərini də dəyişməlidir).
                        now,
                    ),
                )
                reclaimed = cur.rowcount
            uow.commit()
        if reclaimed == 1:
            _log.warning(
                "SCHEDULED_JOB_LEASE_RECLAIMED",
                extra={"job_key": key, "slot": scheduled_for.isoformat(), "sahib": instance_id},
            )
        return reclaimed == 1

    # -------------------------------- nəticə ---------------------------------- #

    def mark_succeeded(
        self,
        *,
        tenant_id: TenantId,
        job_key: str,
        scheduled_for: datetime,
        instance_id: str,
        finished_at: datetime,
        result_detail: str | None = None,
    ) -> bool:
        """Uğurlu bitiş. `leased_by` şərti icarə sahibliyini yoxlayır."""
        return (
            self._finish(
                tenant_id=tenant_id,
                job_key=job_key,
                scheduled_for=scheduled_for,
                instance_id=instance_id,
                finished_at=finished_at,
                status=JobRunStatus.SUCCEEDED,
                # Uğur köhnə xətanı SİLİR: sətir "sonuncu vəziyyət"i göstərir və
                # keçən cəhdin mesajı qalsaydı, ekran uğurlu işi qırmızı
                # göstərərdi. Cəhd sayğacı (`attempts`) tarixçəni saxlayır.
                last_error=None,
                result_detail=result_detail,
            )
            == 1
        )

    def mark_failed(
        self,
        *,
        tenant_id: TenantId,
        job_key: str,
        scheduled_for: datetime,
        instance_id: str,
        finished_at: datetime,
        error: str,
    ) -> bool:
        """Uğursuzluq + səbəb. Səbəb BOŞ OLA BİLMƏZ (`chk_job_run_error`)."""
        message = trim_error_text(error) or "Naməlum xəta"
        return (
            self._finish(
                tenant_id=tenant_id,
                job_key=job_key,
                scheduled_for=scheduled_for,
                instance_id=instance_id,
                finished_at=finished_at,
                status=JobRunStatus.FAILED,
                last_error=message,
                result_detail=None,
            )
            == 1
        )

    def _finish(
        self,
        *,
        tenant_id: TenantId,
        job_key: str,
        scheduled_for: datetime,
        instance_id: str,
        finished_at: datetime,
        status: JobRunStatus,
        last_error: str | None,
        result_detail: str | None,
    ) -> int:
        """Hər iki bitiş yolunun ortaq ŞƏRTLİ `UPDATE`-i.

        Şərtdə həm `leased_by`, həm `status = 'RUNNING'` var: icarəsi
        bitmiş və başqasına keçmiş iş öz nəticəsini YENİ sahibin üstünə
        yaza bilməz (uduzan tərəf `False` alır və planlayıcı xəbərdarlıq
        yazır — bax `JobRunner._mark`).
        """
        key = normalize_job_key(job_key)
        with self._database.unit_of_work(tenant_id) as uow:
            with uow.connection.cursor() as cur:
                cur.execute(
                    """
                    UPDATE app_scheduled_job_runs
                       SET status        = %s,
                           finished_at   = %s,
                           last_error    = %s,
                           result_detail = %s
                     WHERE tenant_id = %s
                       AND job_key = %s
                       AND scheduled_for = %s
                       AND leased_by = %s
                       AND status = 'RUNNING'
                    """,
                    (
                        status.value,
                        finished_at,
                        last_error,
                        result_detail,
                        tenant_id,
                        key,
                        scheduled_for,
                        instance_id,
                    ),
                )
                affected = cur.rowcount
            uow.commit()
        return affected

    # --------------------------------- oxu ------------------------------------ #

    def get(
        self, *, tenant_id: TenantId, job_key: str, scheduled_for: datetime
    ) -> ScheduledJobRun | None:
        """Bir slotun qeydi — sağlamlıq/diaqnostika yolu (icra yolunda YOX)."""
        key = normalize_job_key(job_key)
        with self._database.unit_of_work(tenant_id) as uow, uow.connection.cursor() as cur:
            cur.execute(
                f"{_SELECT} WHERE tenant_id = %s AND job_key = %s AND scheduled_for = %s",
                (tenant_id, key, scheduled_for),
            )
            row = cur.fetchone()
        return None if row is None else _row_to_run(row)


def _row_to_run(row: dict[str, Any]) -> ScheduledJobRun:
    return ScheduledJobRun(
        tenant_id=TenantId(row["tenant_id"]),
        job_key=str(row["job_key"]),
        scheduled_for=row["scheduled_for"],
        status=JobRunStatus(row["status"]),
        leased_by=str(row["leased_by"]),
        leased_until=row["leased_until"],
        started_at=row["started_at"],
        attempts=int(row["attempts"]),
        finished_at=row["finished_at"],
        # `NULL` sütunlar sətirdə boş mətnə ÇEVRİLMİR: "xəta yoxdur" ilə "xəta
        # boş sətirdir" fərqi diaqnostikada mənalıdır.
        last_error=None if row["last_error"] is None else str(row["last_error"]),
        result_detail=None if row["result_detail"] is None else str(row["result_detail"]),
    )


__all__ = ["PostgresScheduledJobRepository"]
