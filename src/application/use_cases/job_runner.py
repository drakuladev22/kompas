"""Planlanmış işlərin NÜVƏSİ — qeydiyyat, icarə, icra, nəticə (Faza 11).

KompasOS-da dövri işlərin HAMISININ metodu yazılıb və test edilib (davranış
baz xətti, sənəd bitmə xəbərdarlığı, turnover balı, kadr nümunəsi, gecə
ehtiyat nüsxəsi, köhnəlmiş cərimə təmizliyi, ödəniş xatırlatmaları) — lakin
onları ÇAĞIRAN mexanizm yox idi. `NightlyBackupService` adına baxmayaraq heç
vaxt tətiklənmirdi. Bu modul həmin boşluğu doldurur.

Bu fayl YALNIZ nüvədir: işlərin qeydiyyatı və giriş nöqtələri (CLI, GUI
`QTimer`) ayrıca gəlir. Nüvə heç bir konkret işi TANIMIR.

──────────────────────────────────────────────────────────────────────────────
NİYƏ REYESTR — `if job == ...` ZƏNCİRİ NİYƏ RƏDD EDİLDİ
──────────────────────────────────────────────────────────────────────────────
Bu qərar layihədə ARTIQ qəbul edilib və əsaslandırması `domain/exception_
rules.py` başlığındadır; burada eyni üç səbəb sözbəsöz keçərlidir:

  1. **Planlayıcı audit-kritik koddur.** Onun hər dəyişikliyi ARTIQ işləyən
     bütün gecə işlərini yenidən risk altına salır. `if` zənciri hər yeni
     işdə məhz bu faylın dəyişməsini TƏLƏB EDƏRDİ.
  2. **Asılılıq istiqaməti tərsinə dönərdi.** Zəncir planlayıcını hər işin
     modulundan (və onun bütün use case asılılıqlarından) asılı edərdi;
     nəticədə ehtiyat nüsxə xidmətinin qüsuru planlayıcının testini də
     sındırardı.
  3. **Qismən uğur mümkün olmazdı.** Reyestrdə hər iş AYRI vahiddir və
     birinin çökməsi digərlərini dayandırmır (bax `JobRunner._run_one`).
     Zəncirdə isə bir `elif`-in istisnası bütün gecəni aparardı.

Sıra da eyni səbəbdən qorunur (`dict` sırası): təsadüfi sıra eyni gecənin iki
icrasında `started_at` möhürlərini qarışdırardı və "hansı iş əvvəl işlədi?"
sualı sağlamlıq ekranında cavabsız qalardı.

──────────────────────────────────────────────────────────────────────────────
İCARƏ (LEASE) — 21 MAĞAZA, HƏR BİRİNDƏ BİR NEÇƏ TERMİNAL
──────────────────────────────────────────────────────────────────────────────
Planlayıcı hər terminalda işləyir. Naiv qurulsaydı, HƏR terminal eyni gecə
işini icra edərdi: baz xətti bir neçə dəfə hesablanar, HR eyni sənəd üçün bir
neçə e-poçt alardı.

Müdafiə TƏTBİQ QATINDA DEYİL. Burada heç bir yerdə "əvvəlcə oxu, sonra yaz"
yoxlaması yoxdur — çünki oxu ilə yazı arasındakı pəncərədə hər iki terminal
"qeyd yoxdur" görür və hər ikisi qalib sayılır. Qərarı DB verir:
`ScheduledJobRepository.acquire()` tək atomik `INSERT ... ON CONFLICT DO
NOTHING` (+ şərti `UPDATE`) icra edir və `rowcount` qaytarır (#16 açıq növbə
bazarındakı naxışın eynisi, `open_shift_repository.claim` ilə müqayisə edin).

Tətbiq-səviyyəli kilid (`threading.Lock`) QƏSDƏN İŞLƏDİLMİR: o, yalnız TƏK
proses daxilində işləyir və çox-terminallı quraşdırmada heç nə qorumur.

──────────────────────────────────────────────────────────────────────────────
ÇÖKMÜŞ İNSTANSİYA — İŞ NİYƏ ƏBƏDİ "RUNNING" QALMIR
──────────────────────────────────────────────────────────────────────────────
İcarəni götürən terminal cərəyan kəsilməsindən çöksə, qeyd `RUNNING`
statusunda qalır. Onu təmizləyəcək "canlılıq siqnalı" (heartbeat) YOXDUR və
qəsdən yoxdur: heartbeat üçün fon axını lazımdır, fon axını isə çökmüş
prosesdə onsuz da işləmir — yəni problemi həll etmir, sadəcə köçürür.

Əvəzinə icarənin SON İSTİFADƏ TARİXİ var (`leased_until`). Vaxtı keçmiş
icarəni istənilən instansiya geri götürə bilər (`is_reclaimable`). Beləliklə
çökmə ən pis halda bir icarə müddəti (defolt 30 dəq.) gecikməyə çevrilir,
əbədi dayanmaya yox.

ZƏMANƏT `at-least-once`-DIR, `exactly-once` DEYİL. Səbəb: iş bitdi, lakin
`mark_succeeded` şəbəkə qırılmasına düşdüsə, qeyd `RUNNING` qalır və icarə
bitəndən sonra iş TƏKRAR icra oluna bilər. `exactly-once` iki fazalı commit
tələb edərdi (iş + qeyd EYNİ tranzaksiyada), bu isə `pg_dump` kimi xarici
proses üçün mümkün deyil. Ona görə qeydiyyatdan keçən hər iş İDEMPOTENT
olmalıdır — bu, reyestrin müqaviləsidir.

──────────────────────────────────────────────────────────────────────────────
GECİKMİŞ İCRA (CATCH-UP) — "VAXT KEÇDİ, BURAXAQ" NİYƏ YANLIŞDIR
──────────────────────────────────────────────────────────────────────────────
Bu, server deyil, MASAÜSTÜ tətbiqdir: kompüter gecə söndürülmüş ola bilər.
"03:00 keçib, deməli buraxırıq" davranışı işi ƏBƏDİ icra olunmamış qoyardı.
Ona görə slot hesablanarkən HƏMİŞƏ son keçmiş sərhəd götürülür: 09:12-də
açılan terminal həmin günün 03:00 slotunu görür və qeyd yoxdursa icra edir.

BİR NEÇƏ GÜN GERİ QAYIDILMIR (yalnız SON slot). Səbəb: bu işlər CARİ
vəziyyəti yenidən hesablayır (baz xətti, turnover balı, sənəd bitmə
xəbərdarlığı). İki həftə söndürülmüş terminalda 14 icra eyni nəticəni 14 dəfə
yazardı — faydası sıfır, yükü isə real.

──────────────────────────────────────────────────────────────────────────────
AĞIR / YÜNGÜL AYRIMI — GUI AXINI DONMAMALIDIR
──────────────────────────────────────────────────────────────────────────────
Runner iki yerdən çağırılacaq: CLI-dan və GUI-dakı `QTimer`-dən. `QTimer`
GUI AXININDA işləyir; orada `pg_dump` çağıran iş interfeysi dəqiqələrlə
dondurardı. Ona görə hər iş özünü `JobWeight.HEAVY` və ya `JobWeight.LIGHT`
kimi ELAN ETMƏLİDİR (`ScheduledJob.weight`-in defolt dəyəri YOXDUR — səhv
tərəfə sükutla düşmək mümkün olmasın deyə) və `run_due(include_heavy=...)`
arqumenti də defoltsuzdur: hər iki səhv (donmuş interfeys / heç vaxt
işləməyən ehtiyat nüsxə) SÜKUTLA baş verərdi.

──────────────────────────────────────────────────────────────────────────────
SƏLAHİYYƏT QEYDİ
──────────────────────────────────────────────────────────────────────────────
`run_due` istifadəçi əməliyyatı deyil, sistem işidir; aktoru yoxdur
(`audit.actor_id = None`) və flag yoxlaması YOXDUR. Eyni qərar
`ExceptionEngineUseCase.run`-dadır və səbəbi eynidir: gecə işləyən dövrəyə
süni "istifadəçi" uydurmaq lazım gələrdi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Protocol
from zoneinfo import ZoneInfo

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.job_runs import (
    normalize_job_key,
    trim_error_text,
)
from src.domain.value_objects.scheduling import DEFAULT_TIMEZONE, require_aware
from src.shared.exceptions import KompasOSError
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from src.domain.interfaces.ports import (
        AuditTrail,
        Clock,
        ScheduledJobRepository,
        SystemLimits,
    )
    from src.domain.value_objects.identifiers import TenantId

_log = get_logger(__name__)

#: Sutkanın tərifi — SİYASƏT DEYİL. `SCHEDULER_NIGHTLY_HOUR` Root-dan gəlir,
#: lakin 0–23 diapazonu saatın özünün tərifidir və `system_limits`-ə aid
#: deyil (eyni qərar: `job_runs.MIN_JOB_KEY_LENGTH` DB `CHECK`-in güzgüsüdür).
_MIN_HOUR = 0
_MAX_HOUR = 23


class SchedulerError(KompasOSError):
    """Planlayıcının QURAŞDIRMA səhvi — işə salınma anında çökməlidir."""

    user_message = "Sistem konfiqurasiya xətası. Administratorla əlaqə saxlayın."


class DuplicateJobError(SchedulerError):
    """Eyni açarla ikinci iş qeydiyyatdan keçirilir."""


class JobWeight(str, Enum):
    """İşin GUI axını üçün təhlükəlilik dərəcəsi.

    `HEAVY` = uzun sürən və ya xarici proses çağıran (məs. `pg_dump`).
    `LIGHT` = bir neçə sorğu, saniyələrlə ölçülən.
    """

    LIGHT = "LIGHT"
    HEAVY = "HEAVY"


class JobCadence(str, Enum):
    """İşin slot ritmi — `scheduled_for` dəyərinin necə hesablandığı.

    `DAILY` — gündə bir dəfə, `SCHEDULER_NIGHTLY_HOUR` saatında (gecə işləri).
    `HOURLY` — hər saatın başında (xatırlatma/təmizlik kimi tez-tez işlər).

    ÜÇÜNCÜ VARİANT YOXDUR (məs. "hər 5 dəqiqə"): slot sərhədi TƏQVİM
    sərhədinə oturmalıdır, əks halda `scheduled_for` unikal açarı
    instansiyadan-instansiyaya bir neçə saniyə fərqlənər və eyni iş üçün İKİ
    ayrı sətir yaranardı — yəni icarənin bütün müdafiəsi yıxılardı.
    """

    DAILY = "DAILY"
    HOURLY = "HOURLY"


class JobOutcomeState(str, Enum):
    """Bir işin BU çağırışdakı nəticəsi."""

    #: İcra olundu və uğurla bitdi.
    SUCCEEDED = "SUCCEEDED"
    #: İcra olundu, istisna atdı — qeyd `FAILED` yazıldı, digər işlər davam etdi.
    FAILED = "FAILED"
    #: İcarə alınmadı: başqa instansiya icra edir, slot artıq tamamlanıb, və
    #: ya cəhd tavanı dolub (bax `ScheduledJobRepository.acquire`).
    NOT_ACQUIRED = "NOT_ACQUIRED"
    #: Ağır iş, çağırış isə "yalnız yüngül" rejimindədir (GUI axını).
    SKIPPED_HEAVY = "SKIPPED_HEAVY"
    #: İş reyestrdədir, lakin söndürülüb (`ScheduledJob.enabled = False`).
    DISABLED = "DISABLED"


@dataclass(frozen=True, slots=True)
class JobExecutionContext:
    """İşə ötürülən kontekst — icranın "hansı kirayəçi, hansı slot" cavabı.

    `now` və `scheduled_for` AYRIDIR: gecikmiş icrada birincisi 09:12,
    ikincisi 03:00-dır. İş özü hansını istifadə edəcəyinə qərar verir —
    hesablama pəncərəsi adətən slota, log möhürü isə faktiki ana bağlanır.
    """

    tenant_id: TenantId
    job_key: str
    scheduled_for: datetime
    now: datetime


class ScheduledJobHandler(Protocol):
    """İşin özü — planlayıcının tanıdığı YEGANƏ interfeys.

    Qaytarılan mətn (varsa) qeydin `result_detail` sütununa yazılır: "235
    işçi yeniləndi" kimi bir sətir sağlamlıq ekranında "işlədi, amma nə
    etdi?" sualını cavablandırır. `None` qaytarmaq normaldır.
    """

    def __call__(self, context: JobExecutionContext) -> str | None: ...


@dataclass(frozen=True, slots=True)
class ScheduledJob:
    """Reyestrdəki bir iş.

    `weight` və `cadence` DEFOLTSUZDUR: hər ikisi işin təbiəti haqqında
    qərardır və sükutla "yüngül/gündəlik" sayılan iş səhv tərəfə düşəndə
    nəticə görünməzdir (donmuş interfeys və ya heç vaxt işləməyən iş).
    """

    key: str
    handler: ScheduledJobHandler
    cadence: JobCadence
    weight: JobWeight
    #: Söndürülmüş iş reyestrdə QALIR, lakin icra olunmur. Reyestrdən
    #: ÇIXARMAQ əvəzinə söndürmək qəsdəndir: sağlamlıq ekranı "bu iş var,
    #: amma söndürülüb" ilə "belə iş yoxdur" arasındakı fərqi göstərə bilsin.
    enabled: bool = True

    def __post_init__(self) -> None:
        # Açar KANONİK formada saxlanılır ki, reyestrdəki ad, DB-dəki sətir və
        # log açarı eyni olsun. `frozen` sinifdə yeganə yol budur.
        object.__setattr__(self, "key", normalize_job_key(self.key))

    @property
    def is_heavy(self) -> bool:
        return self.weight is JobWeight.HEAVY


@dataclass(frozen=True, slots=True)
class JobOutcome:
    """Bir işin bir çağırışdakı nəticəsi — hesabatın sətri."""

    job_key: str
    scheduled_for: datetime
    state: JobOutcomeState
    detail: str | None = None
    error_az: str | None = None

    @property
    def was_executed(self) -> bool:
        """İcarə alınıb və iş FAKTİKİ işləyibmi."""
        return self.state in (JobOutcomeState.SUCCEEDED, JobOutcomeState.FAILED)


@dataclass(frozen=True, slots=True)
class SchedulerRunReport:
    """`run_due` çağırışının tam nəticəsi — audit və log bundan çıxır."""

    tenant_id: TenantId
    started_at: datetime
    include_heavy: bool
    outcomes: tuple[JobOutcome, ...] = field(default_factory=tuple)

    @property
    def executed(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.was_executed)

    @property
    def succeeded(self) -> int:
        return sum(1 for o in self.outcomes if o.state is JobOutcomeState.SUCCEEDED)

    @property
    def failed_jobs(self) -> tuple[str, ...]:
        return tuple(o.job_key for o in self.outcomes if o.state is JobOutcomeState.FAILED)

    @property
    def skipped_heavy(self) -> tuple[str, ...]:
        return tuple(o.job_key for o in self.outcomes if o.state is JobOutcomeState.SKIPPED_HEAVY)


class ScheduledJobRegistry:
    """İş açarı → iş uyğunluğu. İstifadə (kompozisiya kökündə, bir dəfə)::

    registry = ScheduledJobRegistry()
    registry.register(ScheduledJob(key="NIGHTLY_BACKUP", ...))
    runner = JobRunner(registry=registry, ...)
    """

    def __init__(self, jobs: tuple[ScheduledJob, ...] = ()) -> None:
        self._jobs: dict[str, ScheduledJob] = {}
        for job in jobs:
            self.register(job)

    # ------------------------------ qeydiyyat -------------------------------- #

    def register(self, job: ScheduledJob) -> str:
        """İşi reyestrə yazır və normallaşdırılmış açarı qaytarır.

        İKİQAT QEYDİYYAT SÜKUTLA UDULMUR: eyni açarla ikinci iş demək,
        birincisinin heç vaxt işləməyəcəyi (və ya sükutla əvəzləndiyi)
        deməkdir. Üstəlik hər ikisi EYNİ `job_key` ilə icarə götürərdi, yəni
        biri digərini "artıq icra olunub" sayıb sükutla atlayardı. Bu,
        quraşdırma qüsurudur və işə salınma anında yüksək səslə çökməlidir,
        gecə saat 3-də sükutla yox (`ExceptionRuleRegistry.register` ilə eyni
        qərar).
        """
        existing = self._jobs.get(job.key)
        if existing is not None:
            raise DuplicateJobError(
                f"'{job.key}' açarı üçün iş artıq qeydiyyatdadır",
                context={"job_key": job.key},
            )
        self._jobs[job.key] = job
        _log.info(
            "SCHEDULED_JOB_REGISTERED",
            extra={"job_key": job.key, "cadence": job.cadence.value, "weight": job.weight.value},
        )
        return job.key

    # -------------------------------- oxuma ---------------------------------- #

    def get(self, job_key: str) -> ScheduledJob | None:
        """Açar üzrə iş; qeydiyyatda yoxdursa `None`."""
        try:
            return self._jobs.get(normalize_job_key(job_key))
        except KompasOSError:
            # Yararsız açar sadəcə "tapılmadı"dır — axtarış istisna atmamalıdır
            # (`ExceptionRuleRegistry.get` ilə eyni qərar).
            return None

    def jobs(self) -> tuple[ScheduledJob, ...]:
        """Qeydiyyat sırasına sadiq siyahı (icra sırası)."""
        return tuple(self._jobs.values())

    def keys(self) -> tuple[str, ...]:
        return tuple(self._jobs)

    @property
    def is_empty(self) -> bool:
        """Boş reyestr NORMAL vəziyyətdir — planlayıcı sadəcə heç nə etmir.

        Bu, xəta deyil: giriş nöqtəsi hələ bağlanmayıb və ya bütün işlər
        söndürülüb ola bilər. Boş reyestrdə çökmək GUI-nin işə düşməsini
        lazımsız yerə bloklayardı.
        """
        return not self._jobs

    def __len__(self) -> int:
        return len(self._jobs)

    def __contains__(self, job_key: object) -> bool:
        return isinstance(job_key, str) and self.get(job_key) is not None

    def __iter__(self) -> Iterator[ScheduledJob]:
        return iter(self.jobs())

    def __repr__(self) -> str:
        return f"ScheduledJobRegistry(jobs={list(self._jobs)})"


class JobRunner:
    """Vaxtı çatmış işləri icarə altında icra edən dövrə.

    İkinci agentin işlətdiyi İCTİMAİ imza::

        runner = JobRunner(
            runs=repository, limits=limits, audit=audit, clock=clock,
            instance_id="TERMINAL-3#4212",
        )
        runner.register(ScheduledJob(
            key="NIGHTLY_BACKUP", handler=lambda ctx: backup.run(ctx.tenant_id),
            cadence=JobCadence.DAILY, weight=JobWeight.HEAVY,
        ))
        report = runner.run_due(tenant_id=tenant, include_heavy=False)   # GUI
        report = runner.run_due(tenant_id=tenant, include_heavy=True)    # CLI
    """

    def __init__(
        self,
        *,
        runs: ScheduledJobRepository,
        limits: SystemLimits,
        audit: AuditTrail,
        clock: Clock,
        instance_id: str,
        registry: ScheduledJobRegistry | None = None,
        timezone_name: str = DEFAULT_TIMEZONE,
    ) -> None:
        """
        Args:
            instance_id: BU terminalın (prosesin) identifikatoru — icarənin
                sahibi. MƏCBURİDİR və defoltu YOXDUR: bütün instansiyalar eyni
                sətri işlətsəydi, "icarə hələ məndədir" yoxlaması hamı üçün
                doğru olardı və çökmüş instansiyanın işini kimin götürdüyü
                sualı cavabsız qalardı. Sabitlik TƏLƏB OLUNMUR — yenidən
                başlayan proses yeni identifikator götürə bilər, köhnə icarə
                onsuz da `leased_until` ilə bitir.
        """
        cleaned = instance_id.strip()
        if not cleaned:
            raise SchedulerError(
                "Planlayıcı instansiya identifikatoru boş ola bilməz",
                context={"instance_id": instance_id},
            )
        self._runs = runs
        self._limits = limits
        self._audit = audit
        self._clock = clock
        self._instance_id = cleaned
        self._registry = registry or ScheduledJobRegistry()
        self._zone = ZoneInfo(timezone_name)

    # ------------------------------ genişlənmə -------------------------------- #

    def register(self, job: ScheduledJob) -> str:
        """İşi planlayıcıya bağlayır — GENİŞLƏNMƏ NÖQTƏSİ.

        İkinci agent (və gələcək hər iş) yalnız bunu çağırır; runner-in kodu
        toxunulmaz qalır.
        """
        return self._registry.register(job)

    @property
    def registered_jobs(self) -> tuple[str, ...]:
        """Qeydiyyatdan keçmiş açarlar — icra sırası ilə."""
        return self._registry.keys()

    @property
    def instance_id(self) -> str:
        """İcarə sahibinin identifikatoru (diaqnostika üçün)."""
        return self._instance_id

    # ------------------------------- parametrlər ------------------------------ #

    def poll_interval(self, tenant_id: TenantId) -> timedelta:
        """GUI/CLI dövrəsinin yoxlama aralığı — ROOT parametri.

        Giriş nöqtəsi `QTimer` intervalını BUNDAN oxumalıdır; sabit ədəd
        yazsaydı, Root paneldəki dəyər ekranda görünər, lakin təsirsiz
        qalardı (`test_root_control_parameter_parity` məhz bu boşluğu
        bağlayır).
        """
        snapshot = self._limits.all_for(tenant_id)
        minutes = self._limit_int(snapshot, SystemLimitKey.SCHEDULER_POLL_INTERVAL_MINUTES)
        # Sıfır/mənfi aralıq dövrəni fasiləsiz işlədərdi — ən azı 1 dəqiqə.
        return timedelta(minutes=max(1, minutes))

    # --------------------------------- icra ----------------------------------- #

    def run_due(
        self,
        *,
        tenant_id: TenantId,
        include_heavy: bool,
        now: datetime | None = None,
    ) -> SchedulerRunReport:
        """Vaxtı çatmış işləri icra edir və hesabat qaytarır.

        Args:
            include_heavy: `False` — YALNIZ yüngül işlər (GUI axını).
                Defoltu YOXDUR (bax modul başlığı: hər iki səhv sükutlu olardı).
            now: Testdə sabitlənən an; verilməzsə `Clock` portundan alınır.
                `datetime.now()` HEÇ YERDƏ çağırılmır — əks halda slot sərhədi
                (03:00) determinstik test edilə bilməzdi.
        """
        started_at = require_aware(now or self._clock.now(), field="now")
        # Limitlər BİR DƏFƏ oxunur: uzun icra ərzində Root dəyəri dəyişsə,
        # eyni dövrənin işləri müxtəlif icarə müddəti ilə işləyərdi
        # (`ExceptionEngineUseCase.run` ilə eyni qərar).
        snapshot = self._limits.all_for(tenant_id)
        nightly_hour = min(
            _MAX_HOUR,
            max(_MIN_HOUR, self._limit_int(snapshot, SystemLimitKey.SCHEDULER_NIGHTLY_HOUR)),
        )
        lease_minutes = max(1, self._limit_int(snapshot, SystemLimitKey.SCHEDULER_LEASE_MINUTES))
        max_attempts = max(1, self._limit_int(snapshot, SystemLimitKey.SCHEDULER_MAX_ATTEMPTS))

        local_now = started_at.astimezone(self._zone)
        outcomes = [
            self._run_one(
                job,
                tenant_id=tenant_id,
                now=started_at,
                scheduled_for=self._slot_for(job.cadence, local_now, nightly_hour=nightly_hour),
                include_heavy=include_heavy,
                lease_minutes=lease_minutes,
                max_attempts=max_attempts,
            )
            for job in self._registry.jobs()
        ]

        report = SchedulerRunReport(
            tenant_id=tenant_id,
            started_at=started_at,
            include_heavy=include_heavy,
            outcomes=tuple(outcomes),
        )
        self._record_audit(report)
        return report

    def _run_one(
        self,
        job: ScheduledJob,
        *,
        tenant_id: TenantId,
        now: datetime,
        scheduled_for: datetime,
        include_heavy: bool,
        lease_minutes: int,
        max_attempts: int,
    ) -> JobOutcome:
        """Tək işi icra edir — istisnası ÖZÜNDƏ QALIR.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ BİR İŞİN ÇÖKMƏSİ DÖVRƏNİ DAYANDIRMIR
        ──────────────────────────────────────────────────────────────────────
        Qüsurlu iş bütün icranı aparsaydı, HƏMİN GECƏ heç bir iş işləməzdi —
        yəni yeni qoşulan tək bir iş bütün fon qatını sükutla söndürərdi.
        Ona görə hər iş təcrid edilir: xəta qeydə (`last_error`) və log-a
        yazılır, digər işlər davam edir (`ExceptionEngineUseCase._run_one`
        ilə eyni qərar və eyni əsaslandırma).

        TƏCRİD YALNIZ `handler`-i əhatə EDİR. `acquire`/`mark_*` çağırışları
        blokun XARİCİNDƏDİR və istisnaları YUXARI ÇIXIR: onların uğursuzluğu
        iş qüsuru deyil, infrastruktur nasazlığıdır (baza əlçatmazdır) —
        həmin halda növbəti işi cəhd etmək də mənasızdır və yalnız eyni
        xətanı təkrarlayardı.
        """
        if not job.enabled:
            return JobOutcome(
                job_key=job.key,
                scheduled_for=scheduled_for,
                state=JobOutcomeState.DISABLED,
                detail="İş söndürülüb",
            )
        if job.is_heavy and not include_heavy:
            # SÜKUTLA ATLANMIR: hesabatda görünür, əks halda "ehtiyat nüsxə
            # niyə işləmir?" sualının izi qalmazdı.
            return JobOutcome(
                job_key=job.key,
                scheduled_for=scheduled_for,
                state=JobOutcomeState.SKIPPED_HEAVY,
                detail="Ağır iş yalnız-yüngül rejimində atlanır",
            )

        acquired = self._runs.acquire(
            tenant_id=tenant_id,
            job_key=job.key,
            scheduled_for=scheduled_for,
            instance_id=self._instance_id,
            now=now,
            leased_until=now + timedelta(minutes=lease_minutes),
            max_attempts=max_attempts,
        )
        if not acquired:
            return JobOutcome(
                job_key=job.key,
                scheduled_for=scheduled_for,
                state=JobOutcomeState.NOT_ACQUIRED,
                detail="İcarə alınmadı (başqa instansiya, tamamlanmış slot və ya cəhd tavanı)",
            )

        try:
            detail = job.handler(
                JobExecutionContext(
                    tenant_id=tenant_id,
                    job_key=job.key,
                    scheduled_for=scheduled_for,
                    now=now,
                )
            )
        # GENİŞ `except` QƏSDƏNDİR: işin hansı istisnanı atacağını planlayıcı
        # bilə bilməz (o, tamamilə kənar koddur) və məhz onu təcrid etmək bu
        # blokun məqsədidir — bax metodun docstring-i.
        except Exception as exc:
            message = trim_error_text(f"{type(exc).__name__}: {exc}")
            _log.error(
                "SCHEDULED_JOB_FAILED",
                extra={"job_key": job.key, "slot": scheduled_for.isoformat(), "error": message},
            )
            self._mark(
                job.key,
                tenant_id=tenant_id,
                scheduled_for=scheduled_for,
                finished_at=self._clock.now(),
                error=message,
            )
            return JobOutcome(
                job_key=job.key,
                scheduled_for=scheduled_for,
                state=JobOutcomeState.FAILED,
                error_az=f"İş icra edilə bilmədi: {message}",
            )

        self._mark(
            job.key,
            tenant_id=tenant_id,
            scheduled_for=scheduled_for,
            finished_at=self._clock.now(),
            result_detail=detail,
        )
        _log.info(
            "SCHEDULED_JOB_SUCCEEDED",
            extra={"job_key": job.key, "slot": scheduled_for.isoformat(), "netice": detail or ""},
        )
        return JobOutcome(
            job_key=job.key,
            scheduled_for=scheduled_for,
            state=JobOutcomeState.SUCCEEDED,
            detail=detail,
        )

    # ------------------------------- köməkçilər ------------------------------- #

    def _mark(
        self,
        job_key: str,
        *,
        tenant_id: TenantId,
        scheduled_for: datetime,
        finished_at: datetime,
        result_detail: str | None = None,
        error: str | None = None,
    ) -> None:
        """Nəticəni yazır və İCARƏNİN İTİRİLMƏSİNİ görünən edir.

        `mark_*` `False` qaytarırsa, icarə artıq bu instansiyada deyil: iş
        `leased_until`-dan uzun çəkib və başqa terminal onu götürüb. Bu,
        sükutla keçilməməlidir — dəyər `SCHEDULER_LEASE_MINUTES`-in çox kiçik
        seçildiyinin YEGANƏ siqnalıdır (bax modul başlığı: at-least-once).
        """
        if error is not None:
            kept = self._runs.mark_failed(
                tenant_id=tenant_id,
                job_key=job_key,
                scheduled_for=scheduled_for,
                instance_id=self._instance_id,
                finished_at=finished_at,
                error=error,
            )
        else:
            kept = self._runs.mark_succeeded(
                tenant_id=tenant_id,
                job_key=job_key,
                scheduled_for=scheduled_for,
                instance_id=self._instance_id,
                finished_at=finished_at,
                result_detail=result_detail,
            )
        if not kept:
            _log.warning(
                "SCHEDULED_JOB_LEASE_LOST",
                extra={
                    "job_key": job_key,
                    "slot": scheduled_for.isoformat(),
                    "instance_id": self._instance_id,
                },
            )

    def _slot_for(self, cadence: JobCadence, local_now: datetime, *, nightly_hour: int) -> datetime:
        """Bu anın aid olduğu SON keçmiş slot (gecikmiş icranın açarı).

        Hesablama MAĞAZANIN yerli zonasındadır (`DEFAULT_TIMEZONE`): "gecə
        saat 3" UTC-də deyil, mağazanın saatında mənalıdır. `replace(hour=...)`
        təhlükəsizdir, çünki Azərbaycan 2016-dan yay/qış saatı tətbiq etmir —
        yerli gün ərzində offset sabitdir. Nəticə tz-aware qalır və DB-də
        `TIMESTAMPTZ` kimi ANİ olaraq saxlanılır, yəni zona sonradan
        dəyişsə də köhnə slotların kimliyi sürüşmür.
        """
        if cadence is JobCadence.HOURLY:
            return local_now.replace(minute=0, second=0, microsecond=0)
        slot = local_now.replace(hour=nightly_hour, minute=0, second=0, microsecond=0)
        if local_now < slot:
            # Sərhəd: TAM 03:00:00-da slot BUGÜNKÜDÜR (`<` müqayisəsi) — yəni
            # iş sərhəd anında dərhal icra oluna bilər. `<=` yazılsaydı,
            # 03:00:00-da işləyən dövrə dünənin slotunu görər və günün işi bir
            # dövrə (15 dəq.) gecikərdi.
            slot -= timedelta(days=1)
        return slot

    def _record_audit(self, report: SchedulerRunReport) -> None:
        """AQREQAT audit sətri — icra BAŞ VERİBSƏ.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ HƏR İŞ ÜÇÜN AYRI SƏTİR YAZILMIR
        ──────────────────────────────────────────────────────────────────────
        Dövrə 15 dəqiqədən bir işləyir və işlərin çoxu "vaxtı çatmayıb"
        cavabını alır. Hər çağırışa sətir yazsaydıq, `audit_logs` gündə
        yüzlərlə mənasız sətirlə dolar və HƏQİQİ insan qərarları (cərimə,
        override, icazə) bu axında itərdi. Naxış `attrition_risk.py`-dakı
        `ATTRITION_SCORES_RECALCULATED` ilə eynidir: 235 işçi üçün 235 sətir
        deyil, BİR aqreqat sətir.

        Heç bir iş icarə ala bilmədisə audit sətri də YOXDUR — yazılası fakt
        baş verməyib.
        """
        if not report.executed:
            return
        self._audit.record(
            tenant_id=report.tenant_id,
            # Aktor YOXDUR: işi insan deyil, planlayıcı başladır.
            actor_id=None,
            action="SCHEDULED_JOBS_EXECUTED",
            entity_type="app_scheduled_job_runs",
            after_state={
                "icra_edilən": report.executed,
                "uğurlu": report.succeeded,
                "uğursuz": list(report.failed_jobs),
                "atlanan_ağır": list(report.skipped_heavy),
                "instansiya": self._instance_id,
                "ağır_daxil": report.include_heavy,
            },
            reason="Planlaşdırılmış fon dövrəsi",
        )
        _log.info(
            "SCHEDULED_JOBS_EXECUTED",
            extra={
                "tenant_id": str(report.tenant_id),
                "icra_edilen": report.executed,
                "ugurlu": report.succeeded,
                "ugursuz": list(report.failed_jobs),
            },
        )

    @staticmethod
    def _limit_int(snapshot: dict[str, str], key: SystemLimitKey) -> int:
        """`system_limits` nüsxəsindən tam ədəd — yararsız dəyər defolta düşür.

        FALLBACK MƏNBƏYİ `DEFAULT_LIMITS`-dir, sinifdəki sabit DEYİL: bu
        modulda planlayıcı ədədi ümumiyyətlə yoxdur (CLAUDE.md §5 — həqiqi
        mənbə `system_limits`, seed: migrations/036).
        """
        fallback = int(DEFAULT_LIMITS[key])
        raw = snapshot.get(key.value)
        if raw is None:
            return fallback
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return fallback


__all__ = [
    "DuplicateJobError",
    "JobCadence",
    "JobExecutionContext",
    "JobOutcome",
    "JobOutcomeState",
    "JobRunner",
    "JobWeight",
    "ScheduledJob",
    "ScheduledJobHandler",
    "ScheduledJobRegistry",
    "SchedulerError",
    "SchedulerRunReport",
]
