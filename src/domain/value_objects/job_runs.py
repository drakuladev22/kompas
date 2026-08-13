"""Planlaşdırılmış işin İCRA QEYDİ — planlayıcının domen dili (Faza 11).

Bu modul yalnız DƏYƏRLƏRİ təyin edir: bir işin bir slotu üçün qeyd hansı
vəziyyətdə ola bilər (`JobRunStatus`), qeydin özü nədən ibarətdir
(`ScheduledJobRun`) və iş açarı hansı formada yazılır (`normalize_job_key`).
İcra məntiqi tətbiq qatındadır (`application.use_cases.job_runner`), yazı isə
infrastrukturdadır (`persistence.scheduled_job_repository`).

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA MODUL — NİYƏ `scheduling.py`-A ƏLAVƏ EDİLMƏDİ
──────────────────────────────────────────────────────────────────────────────
`scheduling.py` İŞÇİNİN vaxtı haqqındadır (iş rejimi, gecikmə, yerli
gecəyarı). Buradakı tiplər isə SİSTEMİN öz fon işləri haqqındadır və
tamamilə fərqli oxucu kütləsi var. İkisini bir fayla yığmaq "növbə" sözünün
iki mənasını (işçi növbəsi / iş növbəsi) eyni ad məkanında qarışdırardı —
layihədə məhz bu cür ad toqquşması bir dəfə qüsura çevrilib (bax
`menu.py` başlığı).

──────────────────────────────────────────────────────────────────────────────
İCARƏNİN SƏRHƏDİ: `leased_until <= now` = İCARƏ BİTİB
──────────────────────────────────────────────────────────────────────────────
Sərhəd anında (`now == leased_until`) icarə BİTMİŞ sayılır, yəni işi başqa
instansiya götürə bilər. Alternativ (`<`) o demək olardı ki, saniyənin
mikro-hissəsində iki instansiya eyni işi "diri icarə" ilə görür.

Bu qərar İKİ yerdə eyni olmalıdır: burada (`is_lease_expired`) və SQL-də
(`... AND leased_until <= %s`, bax `scheduled_job_repository.acquire`).
Birini dəyişən DİGƏRİNİ də dəyişməlidir — əks halda kod "icarə bitib"
deyərkən DB "hələ bitməyib" deyəcək və götürmə sükutla uğursuz olacaq.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Final

from src.domain.value_objects.identifiers import TenantId
from src.domain.value_objects.scheduling import require_aware
from src.shared.exceptions import KompasOSError

#: `app_scheduled_job_runs.job_key` üçün minimum uzunluq — DB `CHECK`-inin
#: güzgüsü (`char_length(trim(job_key)) >= 3`). Bu, biznes həddi DEYİL, sxem
#: məhdudiyyətidir; ona görə `system_limits`-ə aid deyil (eyni qərar:
#: `exception_signals.MIN_SOURCE_CODE_LENGTH`).
MIN_JOB_KEY_LENGTH: Final = 3

#: `last_error` sütununa yazılan mətnin tavanı. Uzun `traceback` sətri qeydi
#: oxunmaz edir və heç bir diaqnostika dəyəri vermir — səbəb həmişə ilk
#: sətirlərdədir. Sxem məhdudiyyəti deyil, ona görə kəsmə burada edilir.
MAX_ERROR_TEXT_LENGTH: Final = 2000


class InvalidJobRunError(KompasOSError):
    """İcra qeydi və ya iş açarı yararsızdır — PROQRAMÇI səhvidir.

    Sükutla düzəldilmir: yararsız açar demək, işin heç vaxt icra
    olunmayacağı (və ya başqa işin qeydinə yazılacağı) deməkdir.
    """

    user_message = "Daxili planlayıcı xətası. Administratorla əlaqə saxlayın."


def normalize_job_key(job_key: str) -> str:
    """İş açarını DB formatına gətirir: kənar boşluqsuz, BÖYÜK hərflərlə.

    Normallaşdırma BURADA edilir ki, `"nightly_backup"` yazan qeydiyyat
    `CHECK` pozuntusu ilə YAZI ANINDA (gecə saat 3-də) deyil, qeydiyyat
    anında — yəni tətbiqin işə düşməsində — aydın mesaj alsın. Naxış
    `ExceptionRuleRegistry._normalize` ilə eynidir.
    """
    code = (job_key or "").strip().upper()
    if len(code) < MIN_JOB_KEY_LENGTH:
        raise InvalidJobRunError(
            f"İş açarı minimum {MIN_JOB_KEY_LENGTH} simvol olmalıdır",
            context={"job_key": job_key},
        )
    return code


def trim_error_text(text: str) -> str:
    """Xəta mətnini `MAX_ERROR_TEXT_LENGTH` həddinə qədər kəsir.

    Kəsilmə SƏSSİZ DEYİL — sonuna `…` qoyulur ki, oxuyan mətnin tam
    olmadığını görsün (ekranlardakı sətir kəsmə qərarı ilə eyni).
    """
    clean = text.strip()
    if len(clean) <= MAX_ERROR_TEXT_LENGTH:
        return clean
    return clean[: MAX_ERROR_TEXT_LENGTH - 1] + "…"


class JobRunStatus(str, Enum):
    """`app_scheduled_job_runs.status` — DB `CHECK` siyahısı ilə EYNİ.

    `PENDING` QƏSDƏN YOXDUR: sətir yalnız icarə ANINDA yaranır, yəni "hələ
    başlamamış" qeyd mümkün deyil. Belə status olsaydı, planlayıcının bütün
    gələcək slotlarını əvvəlcədən yazan ayrıca mexanizm lazım olardı — və
    həmin mexanizm özü də növbəti planlaşdırılmış iş olardı (dövrə).
    """

    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ScheduledJobRun:
    """Bir işin BİR slotu üçün icra qeydi (`UNIQUE (tenant_id, job_key, scheduled_for)`).

    `scheduled_for` — icranın AİD OLDUĞU an (məs. 03:00), `started_at` isə
    FAKTİKİ başlanğıc (məs. kompüter 09:12-də açılıbsa, 09:12). İkisinin
    ayrılması qəsdəndir: gecikmiş icranın (catch-up) faktı yalnız bu fərqdən
    görünür və "gecə işi niyə səhər 9-da işlədi?" sualı cavablana bilir.
    """

    tenant_id: TenantId
    job_key: str
    scheduled_for: datetime
    status: JobRunStatus
    leased_by: str
    leased_until: datetime
    started_at: datetime
    attempts: int
    finished_at: datetime | None = None
    last_error: str | None = None
    result_detail: str | None = None

    def __post_init__(self) -> None:
        # Boş `leased_by` "icarəsiz icarə" deməkdir: qeyd var, sahibi yoxdur.
        # Belə sətir çökmüş instansiyanın icarəsini geri götürməyi mümkünsüz
        # edərdi (kimin adına yazılıb sualının cavabı olmazdı).
        if not self.leased_by.strip():
            raise InvalidJobRunError(
                "İcarə sahibinin identifikatoru boş ola bilməz",
                context={"job_key": self.job_key},
            )
        # Cəhd sayı 1-dən başlayır: qeyd ilk icarə ilə YARANIR, yəni "sıfır
        # cəhdlik" sətir məntiqən mümkün deyil. 0/mənfi dəyər cəhd tavanının
        # (`SCHEDULER_MAX_ATTEMPTS`) hesabını pozardı.
        if self.attempts < 1:
            raise InvalidJobRunError(
                "Cəhd sayı ən azı 1 olmalıdır",
                context={"job_key": self.job_key, "attempts": self.attempts},
            )
        require_aware(self.scheduled_for, field="scheduled_for")
        require_aware(self.leased_until, field="leased_until")
        require_aware(self.started_at, field="started_at")
        if self.finished_at is not None:
            require_aware(self.finished_at, field="finished_at")
        # Terminal statusun bitmə anı OLMALIDIR — DB-dəki `chk_job_run_finished`
        # məhdudiyyətinin kod tərəfi (struktur zəmanət iki yerdə yaşayır).
        if self.status is not JobRunStatus.RUNNING and self.finished_at is None:
            raise InvalidJobRunError(
                "Tamamlanmış icranın bitmə anı olmalıdır",
                context={"job_key": self.job_key, "status": self.status.value},
            )

    @property
    def is_terminal(self) -> bool:
        """İcra bitibmi (uğurlu və ya uğursuz)."""
        return self.status is not JobRunStatus.RUNNING

    def is_lease_expired(self, now: datetime) -> bool:
        """İcarə müddəti bitibmi — SƏRHƏD DAXİLDİR (`leased_until <= now`).

        Bax modul başlığı: eyni müqayisə SQL-də də `<=` ilə yazılır.
        """
        require_aware(now, field="now")
        return self.leased_until <= now

    def is_reclaimable(self, now: datetime, *, max_attempts: int) -> bool:
        """Qeyd yenidən götürülə bilərmi — `acquire` SQL şərtinin GÜZGÜSÜ.

        Yalnız İKİ hal: (a) `FAILED` — təkrar cəhd, (b) `RUNNING`, lakin
        icarəsi bitib — İCRAÇI ÇÖKÜB. `SUCCEEDED` heç vaxt qaytarılmır:
        idempotentlik zəmanətinin özü budur.

        Cəhd tavanı hər iki halda tətbiq olunur. Səbəb: tətbiqi ÖLDÜRƏN iş
        (məs. yaddaşı bitirən `pg_dump`) hər dəfə `RUNNING` qalıb icarəsi
        bitəcək və tavan olmasaydı, terminal sonsuz döngəyə düşərdi.
        """
        if self.status is JobRunStatus.SUCCEEDED:
            return False
        if self.attempts >= max_attempts:
            return False
        if self.status is JobRunStatus.FAILED:
            return True
        return self.is_lease_expired(now)


__all__ = [
    "MAX_ERROR_TEXT_LENGTH",
    "MIN_JOB_KEY_LENGTH",
    "InvalidJobRunError",
    "JobRunStatus",
    "ScheduledJobRun",
    "normalize_job_key",
    "trim_error_text",
]
