"""Planlaşdırılmış İcra Xülasəsi — #30, kompas1.md Faza 6.

Bu fayl İKİ şeyi birlikdə saxlayır (`attrition_risk.py`/`behavior_baseline.py`
ilə EYNİ qərar): (1) `configure`/`deactivate`/`list_for_management` — Root
Control Center-in YAZI/OXU yolu, (2) `run()` — planlayıcının gecəlik girişi
(`EXECUTIVE_DIGEST_RUN`, bax `composition.py::_register_scheduled_jobs`).

──────────────────────────────────────────────────────────────────────────────
İKİ HƏQİQƏT MƏNBƏYİ — HANSI DƏYƏR HARADA YAŞAYIR (qərar + əsaslandırma)
──────────────────────────────────────────────────────────────────────────────
Ətraflı izah `domain/value_objects/executive_digest.py` başlığındadır; qısası:

  * `system_limits` = SİYASƏT (metrik kataloqu, yeni sətrin defolt tezliyi,
    həftəlik xülasənin göndərilmə günü) — kirayəçiyə TƏK dəyər, cədvəldə
    sütunu YOXDUR.
  * `executive_digest_config` sətri = FAKTİKİ SEÇİM (kim, nə tezlikdə, hansı
    metriklər) + `last_sent_at` VƏZİYYƏTİ.

Metrik kataloqu daralanda (Root açar çıxararsa) MÖVCUD sətirlərin seçimi
DƏYİŞMİR — `_compute_metrics` naməlum/kataloqdan çıxmış açarı SÜKUTLA ATIR
(loglayaraq), sətri YENİDƏN YAZMIR. Bu, `Feature Toggle`-ın retroaktiv təsir
ETMƏMƏSİ qaydası ilə (CLAUDE.md §5) EYNİ fəlsəfədir.

──────────────────────────────────────────────────────────────────────────────
TƏKRAR GÖNDƏRMƏNİN QARŞISINI NƏ ALIR — İKİ QAT, İKİ FƏRQLİ SUALA CAVAB
──────────────────────────────────────────────────────────────────────────────
Planlayıcı nüvəsi (`job_runner.py`) artıq `app_scheduled_job_runs` cədvəlində
SLOT-başına icarə verir — "bu GÜNÜN yoxlama dövrəsi ARTIQ İCRA OLUNUB?" sualının
cavabıdır və `EXECUTIVE_DIGEST_RUN`-un GÜNDƏ BİR DƏFƏ (bir neçə terminaldan
paralel DEYİL) işə düşməsini zəmanət edir.

BU, KİFAYƏT ETMİR: `JobCadence`-də YALNIZ `DAILY`/`HOURLY` var (`job_runner.py`
başlığı — "ÜÇÜNCÜ VARİANT YOXDUR"), yəni HƏFTƏLİK tezlikli konfiqurasiya üçün
ayrıca "bir dəfə həftədə" slotu YOXDUR. Ona görə `EXECUTIVE_DIGEST_RUN` HƏR GÜN
işə düşür və HƏR sətir üçün "bu KONKRET sətir bu gün DUE-dursa?" sualını ÖZÜ
verir — bu, `executive_digest_config.last_sent_at`-in işidir (bax `_due_window`).

İKİ MEXANİZM BİR-BİRİNİ ƏVƏZ ETMİR, TAMAMLAYIR:
  * `app_scheduled_job_runs` → "planlayıcının BU GÜNKÜ yoxlama dövrəsi
    artıq baş verdi" (kobud, gün-səviyyəli, ÇOX-terminallı mühafizə).
  * `last_sent_at` → "BU sətir üçün son göndəriş nə vaxt idi" (incə,
    sətir-səviyyəli, TƏKRAR-GÖNDƏRMƏNİN həqiqi qapısı).

Planlayıcının zəmanəti **at-least-once**-dır (bax `job_runner.py`: "eyni
tranzaksiyada iş+qeyd mümkün deyil"), yəni `run()` NƏZƏRİ olaraq eyni gün
TƏKRAR çağırıla bilər (icarə itən nadir hal). Handler buna görə İDEMPOTENTDİR:
hər çağırış DB-dən TƏZƏ `last_sent_at` oxuyur və artıq göndərilmiş sətri
YENİDƏN GÖNDƏRMİR — `AnnualLeaveUseCase.run_year_rollover` ilə EYNİ naxış
("haqq TƏYİN edilir, ARTIRILMIR").

──────────────────────────────────────────────────────────────────────────────
BOŞ DÖVR QƏRARI — HEÇ VAXT SÜKUTLA ATLANMIR
──────────────────────────────────────────────────────────────────────────────
Qərar: xülasə HƏMİŞƏ göndərilir, hətta bütün göstəricilər sıfır olsa belə.

Əsaslandırma: icra xülasəsi bir DƏFƏLİK xəbərdarlıq deyil, RİTMİK nəbzdir —
CEO/Root onun "gəldiyini" gözləyir. Sükutla atlansaydı, "bu həftə heç nə
olmayıb" ilə "planlayıcı sınıb, e-poçt getmir" arasındakı fərq ALICI TƏRƏFDƏN
görünməzdi — məhz bu boşluq `FIELD_REPORT_AUDIT_REMINDER`-dən (o, YALNIZ
gecikmiş filial VARSA bildiriş göndərir) fərqləndirən şeydir: audit
xatırlatması KONKRET PROBLEMİ bildirir (yoxdursa bildiriş də yoxdur), icra
xülasəsi isə DÖVRİ HESABATDIR (yoxluq da bir NƏTİCƏDİR — "bu həftə cərimə
sıfır oldu" EYNİ DƏRƏCƏDƏ dəyərli məlumatdır).

──────────────────────────────────────────────────────────────────────────────
ALICI ROLU BOŞ / AKTİV İŞÇİ YOXDUR — ÇÖKMƏ YOX, BROADCAST EHTİYATI
──────────────────────────────────────────────────────────────────────────────
`field_reports._route()` ilə EYNİ İKİ-ADDIMLI naxış: `list_route_recipients`
boş qaytarırsa (rol adı səhv yazılıb, ya da o roldan aktiv işçi yoxdur),
xülasə TENANT-BROADCAST kimi göndərilir (`recipient_id=None`) və auditoriya
süzgəci (`TENANT_NOTIFICATION_AUDIENCE["EXECUTIVE_DIGEST_DELIVERED"]`,
`domain/value_objects/notifications.py`) onu `can_configure_executive_digest`
sahiblərinə daraldır — süzgəcsiz sətir FAIL-OPEN olardı və hər `Satıcı`
şəbəkə-miqyaslı göstəriciləri görərdi.

──────────────────────────────────────────────────────────────────────────────
E-POÇT KANALI ƏLÇATMAZDIR — İKİ QATLI DAVRANIŞ, QƏSDƏN
──────────────────────────────────────────────────────────────────────────────
`is_critical=True` ilə çağrılan `Notifier.notify()` SMTP xətasını ÖZÜ UDUR
(`notifier.py`: "Göndəriş uğursuz olduqda sətir `email_sent = FALSE` qalır və
`EmailFallbackDispatcher` onu arxa fonda təkrarlayır") — yəni MÜVƏQQƏTİ SMTP
kəsintisi `run()`-u İSTİSNA İLƏ ÇÖKDÜRMÜR, in-app bildiriş yerində qalır və
e-poçt arxa fonda YENİDƏN CƏHD OLUNUR. Bu, `FIELD_REPORT_AUDIT_DUE` ilə EYNİ
mövcud davranışdır və DƏYİŞDİRİLMİR.

`JobRunner`-in "e-poçt əlçatmazdırsa iş FAILED yazılır" gözləntisi BUNUNLA
ZİDDİYYƏT TƏŞKİL ETMİR: o, ÜMUMİ qaydadır ("hər hansı gözlənilməz istisna
FAILED yazır, digər işlər davam edir", `job_runner.py::_run_one`) — `run()`
bu faylda HEÇ BİR istisnanı UDMUR (geniş `try/except` YOXDUR), ona görə DB
oxuma/yazma xətası kimi HƏQİQİ infrastruktur nasazlığı SƏRBƏST yuxarı çıxır və
`JobRunner` onu `FAILED` yazıb digər işlərlə davam edir (bax `test_executive_
digest.py::test_run_lets_repository_failures_propagate_for_job_runner`).

──────────────────────────────────────────────────────────────────────────────
1C SƏRHƏDİ
──────────────────────────────────────────────────────────────────────────────
Xam satış rəqəmi BURAYA DAXİL EDİLMİR. Statik `ast` qapısı (Faza 6/9
naxışının təkrarı — bax `multi_store_benchmark.py`/`attrition_risk.py`
başlıqları): bu modulda və `infrastructure.persistence.executive_digest_
repository`-də nə `erp`/`sales` idxalı, nə `SalesDataConnector`/
`OneCSaleRecord` kimi 1C identifikatoru ola bilməz (`tests/unit/
test_executive_digest.py`). Göstəricilər YALNIZ MÖVCUD `multi_store_
benchmark` provayderindən (cərimə/overtime/turnover — HEÇ BİR YENİ hesablama
YAZILMIR, `MultiStoreMetricProvider.metric_values` ÇAĞIRILIR) və `exceptions`
portundan (açıq istisna sayı) qidalanır. Yalnız GECİKƏN CHECK-IN sayı ÜÇÜN
kiçik, BENCHMARK KATALOQUNDA olmayan yeni sorğu var (`DigestFactProvider`,
bax aşağı) — bu da MÖVCUD `attendance_records.is_late` sütununu (`Morning
Check-in`-in artıq yazdığı sahə) SAYIR, YENİ GECİKMƏ MƏNTİQİ QURMUR.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from statistics import fmean
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from src.application.use_cases.multi_store_benchmark import BenchmarkMetric
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.executive_digest import (
    SUPPORTED_FREQUENCIES,
    DigestFrequency,
    DigestMetricKey,
    ExecutiveDigestConfig,
    InvalidDigestConfigError,
)
from src.domain.value_objects.scheduling import DEFAULT_TIMEZONE, require_aware
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date, datetime

    from src.application.use_cases.multi_store_benchmark import MultiStoreMetricProvider
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        Clock,
        ExceptionRepository,
        ExecutiveDigestConfigRepository,
        Notifier,
        SystemLimits,
    )
    from src.domain.value_objects.identifiers import ExecutiveDigestConfigId, TenantId

_app_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Kataloqda olub-olmamasından ASILI OLMAYARAQ, YALNIZ Root/CEO (migrations/038,
#: hardlock səviyyə 2 — `ROOT_CEO`) bu ayarları dəyişə bilər.
CONFIGURE_DIGEST_FLAG: Final[str] = "can_configure_executive_digest"

#: Auditoriyası `domain/value_objects/notifications.py::TENANT_NOTIFICATION_
#: AUDIENCE`-də qeydiyyatdadır — bax modul başlığı "ÇÖKMƏ YOX, BROADCAST".
DIGEST_NOTIFICATION_CATEGORY: Final[str] = "EXECUTIVE_DIGEST_DELIVERED"

#: Bir təqvim HƏFTƏSİ neçə gündür, MİNUS 1 — "bu həftə artıq göndərilib"
#: yoxlamasının TƏRİFİDİR, ROOT PARAMETRİ DEYİL (`job_runner._MIN_HOUR`/
#: `_MAX_HOUR` ilə eyni qərar: saatın 0-23 olması siyasət deyil, tərifdir).
_WEEKLY_DEDUPE_GAP_DAYS: Final[int] = 6

_FALLBACK_METRIC_CATALOG: Final[str] = DEFAULT_LIMITS[
    SystemLimitKey.EXECUTIVE_DIGEST_METRIC_CATALOG
]
_FALLBACK_DEFAULT_FREQUENCY: Final[str] = DEFAULT_LIMITS[
    SystemLimitKey.EXECUTIVE_DIGEST_DEFAULT_FREQUENCY
]
_FALLBACK_WEEKLY_WEEKDAY: Final[int] = int(
    DEFAULT_LIMITS[SystemLimitKey.EXECUTIVE_DIGEST_WEEKLY_WEEKDAY]
)

_ZONE: Final = ZoneInfo(DEFAULT_TIMEZONE)


class ExecutiveDigestPermissionError(KompasOSError):
    """`can_configure_executive_digest` səlahiyyəti yoxdur."""

    user_message = "İcra xülasəsi ayarlarını dəyişmək səlahiyyətiniz yoxdur."


@runtime_checkable
class DigestFactProvider(Protocol):
    """Benchmark kataloqunda OLMAYAN TƏK göstərici — bax modul başlığı.

    `MultiStoreMetricProvider` naxışının EYNİSİ (tətbiq qatının strukturunu
    qaytarmır, sadə `int`), ona görə `ports.py`-da DEYİL, BURADA təyin olunur
    (CLAUDE.md — use case faylının yanında).
    """

    def late_check_in_count(self, tenant_id: TenantId, *, start: date, end: date) -> int:
        """`[start, end)` aralığında `attendance_records.is_late` sayı."""
        ...


@dataclass(frozen=True, slots=True)
class DigestRunReport:
    """`run()` çağırışının nəticəsi — `JobOutcome.detail` mətninin mənbəyi."""

    evaluated: int
    sent: int

    @property
    def not_due(self) -> int:
        return self.evaluated - self.sent


class ExecutiveDigestUseCase:
    """#30 — konfiqurasiya YAZI/OXU yolu + planlayıcı girişi (`run`)."""

    def __init__(
        self,
        *,
        configs: ExecutiveDigestConfigRepository,
        facts: DigestFactProvider,
        benchmark: MultiStoreMetricProvider,
        exceptions: ExceptionRepository,
        limits: SystemLimits,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier,
    ) -> None:
        self._configs = configs
        self._facts = facts
        self._benchmark = benchmark
        self._exceptions = exceptions
        self._limits = limits
        self._audit = audit
        self._clock = clock
        self._notifier = notifier

    # ------------------------------ Root yazı yolu ---------------------------- #

    def list_for_management(
        self, tenant_id: TenantId, actor: Employee
    ) -> list[ExecutiveDigestConfig]:
        """İdarəetmə ekranı — deaktivlər DƏ görünür (yenidən aktivləşdirmək üçün)."""
        self._require(actor, now=self._clock.now())
        return self._configs.list_for_tenant(tenant_id, include_inactive=True)

    def configure(
        self,
        tenant_id: TenantId,
        actor: Employee,
        *,
        recipient_role: str,
        metrics: Sequence[str],
        frequency: str | None = None,
    ) -> ExecutiveDigestConfig:
        """Yeni konfiqurasiya yaradır/mövcudu redaktə edir (UPSERT).

        `frequency=None` — Root açıq tezlik seçməyibsə `system_limits.
        EXECUTIVE_DIGEST_DEFAULT_FREQUENCY` (BR-001-dəki `LEAVE_ALLOWANCE_
        SOURCE` ilə EYNİ "defolt mənbə konfiqurasiya edilir" naxışı) tətbiq
        olunur.
        """
        now = self._clock.now()
        self._require(actor, now=now)

        freq = self._resolve_frequency(tenant_id, frequency)
        catalog = self._metric_catalog(tenant_id)
        chosen = tuple(dict.fromkeys(item.strip().upper() for item in metrics if item.strip()))
        unknown = sorted(item for item in chosen if item not in catalog)
        if unknown:
            raise InvalidDigestConfigError(
                f"Kataloqda olmayan metrik(lər): {', '.join(unknown)}",
                user_message="Seçilən göstəricilərdən bəziləri mövcud deyil.",
                context={"unknown": unknown},
            )

        entry = ExecutiveDigestConfig(
            config_id=None,
            tenant_id=tenant_id,
            recipient_role=recipient_role,
            frequency=freq,
            metrics_included=chosen,
            created_by=actor.id,
        )
        saved = self._configs.save(entry)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="EXECUTIVE_DIGEST_CONFIGURED",
            entity_type="executive_digest_config",
            entity_id=saved.config_id,
            after_state={
                "recipient_role": saved.recipient_role,
                "frequency": saved.frequency.value,
                "metrics_included": list(saved.metrics_included),
            },
        )
        return saved

    def deactivate(
        self, tenant_id: TenantId, actor: Employee, config_id: ExecutiveDigestConfigId
    ) -> None:
        now = self._clock.now()
        self._require(actor, now=now)

        existing = self._configs.get(config_id)
        self._configs.deactivate(tenant_id, config_id, changed_by=actor.id)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="EXECUTIVE_DIGEST_DEACTIVATED",
            entity_type="executive_digest_config",
            entity_id=config_id,
            before_state=None
            if existing is None
            else {"recipient_role": existing.recipient_role, "frequency": existing.frequency.value},
        )

    def _require(self, actor: Employee, *, now: datetime) -> None:
        if not actor.has_permission(CONFIGURE_DIGEST_FLAG, now=now):
            _security_log.warning(
                "EXECUTIVE_DIGEST_PERMISSION_DENIED",
                extra={"actor_id": str(actor.id), "flag": CONFIGURE_DIGEST_FLAG},
            )
            raise ExecutiveDigestPermissionError(
                f"«{CONFIGURE_DIGEST_FLAG}» səlahiyyəti yoxdur",
                context={"actor_id": str(actor.id)},
            )

    def _resolve_frequency(self, tenant_id: TenantId, frequency: str | None) -> DigestFrequency:
        raw = (frequency or self._default_frequency(tenant_id)).strip().upper()
        try:
            freq = DigestFrequency(raw)
        except ValueError as exc:
            raise InvalidDigestConfigError(
                f"'{raw}' tanınmayan tezlikdir",
                user_message="Tezlik gündəlik və ya həftəlik ola bilər.",
            ) from exc
        if freq not in SUPPORTED_FREQUENCIES:
            raise InvalidDigestConfigError(
                f"'{freq.value}' tezliyi planlayıcı tərəfindən HƏLƏ dəstəklənmir "
                "(bax `domain/value_objects/executive_digest.py` başlığı)",
                user_message="Bu tezlik hələ dəstəklənmir.",
            )
        return freq

    # -------------------------------- planlanmış ------------------------------- #

    def run(
        self, *, tenant_id: TenantId, now: datetime, scheduled_for: datetime
    ) -> DigestRunReport:
        """`EXECUTIVE_DIGEST_RUN` (DAILY, LIGHT) planlayıcı girişi.

        `scheduled_for` MAĞAZANIN yerli zonasındadır (`JobRunner._slot_for`
        onu artıq belə hesablayır) — "bu gün" HƏMİN tarixdən götürülür, ikinci
        dəfə zona çevrilməsi APARILMIR.

        Aktoru YOXDUR: bunu düymə yox, planlayıcı çağırır (`notify_overdue_
        audits` ilə eyni forma) — səlahiyyət yoxlaması YOXDUR.
        """
        now = require_aware(now, field="now")
        scheduled_for = require_aware(scheduled_for, field="scheduled_for")
        today = scheduled_for.date()

        weekly_weekday = self._weekly_weekday(tenant_id)
        catalog = self._metric_catalog(tenant_id)
        configs = self._configs.list_for_tenant(tenant_id, include_inactive=False)

        sent = 0
        for config in configs:
            window = _due_window(config, today=today, weekly_weekday=weekly_weekday)
            if window is None:
                continue
            period_start, period_end = window
            lines = self._compute_metrics(
                tenant_id,
                config.metrics_included,
                catalog=catalog,
                start=period_start,
                end=period_end,
            )
            self._deliver(
                tenant_id=tenant_id,
                config=config,
                lines=lines,
                period_start=period_start,
                period_end=period_end,
            )
            # `list_for_tenant`-dən gələn sətrin İD-si HƏMİŞƏ doludur (S101 layihə-üzrə susdurulub).
            assert config.config_id is not None
            self._configs.mark_sent(tenant_id, config.config_id, sent_at=now)
            sent += 1

        report = DigestRunReport(evaluated=len(configs), sent=sent)
        _app_log.info(
            "EXECUTIVE_DIGEST_RUN_COMPLETED",
            extra={"tenant_id": str(tenant_id), "evaluated": report.evaluated, "sent": report.sent},
        )
        return report

    # ------------------------------- köməkçilər -------------------------------- #

    def _deliver(
        self,
        *,
        tenant_id: TenantId,
        config: ExecutiveDigestConfig,
        lines: list[str],
        period_start: date,
        period_end: date,
    ) -> None:
        title = f"{config.frequency.label_az} icra xülasəsi"
        body = "\n".join(
            [f"Dövr: {period_start.isoformat()} — {period_end.isoformat()}", "", *lines]
        )
        recipients = self._configs.list_route_recipients(tenant_id, role_code=config.recipient_role)
        # Boş siyahı → BROADCAST EHTİYATI (bax modul başlığı). `tuple((None,))`
        # ilə eyni forma: hər iki halda DÖVRƏ tam BİR DƏFƏ işləyir.
        targets = tuple(recipients) or (None,)
        for recipient in targets:
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=recipient,
                category=DIGEST_NOTIFICATION_CATEGORY,
                title_az=title,
                body_az=body,
                # MƏCBURİ e-poçt cəhdi — xülasənin BÜTÜN məqsədi mövcud e-poçt
                # fallback kanalını işlətməkdir (bax modul başlığı, "E-POÇT
                # KANALI ƏLÇATMAZDIR").
                is_critical=True,
            )

    def _compute_metrics(
        self,
        tenant_id: TenantId,
        metrics_included: tuple[str, ...],
        *,
        catalog: frozenset[str],
        start: date,
        end: date,
    ) -> list[str]:
        lines: list[str] = []
        for raw_key in metrics_included:
            key = raw_key.strip().upper()
            if key not in catalog:
                # Kataloqdan çıxmış açar — bax modul başlığı "İKİ HƏQİQƏT MƏNBƏYİ".
                _app_log.info("EXECUTIVE_DIGEST_METRIC_DROPPED", extra={"metric": key})
                continue
            try:
                metric = DigestMetricKey(key)
            except ValueError:
                _app_log.warning("EXECUTIVE_DIGEST_METRIC_UNKNOWN", extra={"metric": key})
                continue
            lines.append(f"{metric.label_az}: {self._metric_value(tenant_id, metric, start, end)}")
        return lines

    def _metric_value(
        self, tenant_id: TenantId, metric: DigestMetricKey, start: date, end: date
    ) -> str:
        if metric is DigestMetricKey.FINE_COUNT:
            total = self._network_total(tenant_id, BenchmarkMetric.FINE_COUNT, start, end)
            return str(round(total))
        if metric is DigestMetricKey.OVERTIME_HOURS:
            total = self._network_total(tenant_id, BenchmarkMetric.OVERTIME_HOURS, start, end)
            return f"{total:.1f} saat"
        if metric is DigestMetricKey.TURNOVER_RISK:
            # `0.0` "risk yoxdur" İLƏ "bal hesablanmayıb" arasında FƏRQ QOYMUR
            # (`_network_total` heç bir mağazada dəyər olmadıqda da `0.0`
            # qaytarır) — QƏSDƏN: modul başlığındakı "boş dövr sıfırla
            # göndərilir" qərarı ilə EYNİ məntiq, ayrıca "— (yoxdur)" bayrağı
            # yaratmır.
            total = self._network_total(tenant_id, BenchmarkMetric.TURNOVER_RISK, start, end)
            return f"{total:.1f} bal"
        if metric is DigestMetricKey.OPEN_EXCEPTION_COUNT:
            return str(len(self._exceptions.list_open(tenant_id)))
        # DigestMetricKey.LATE_CHECK_IN_COUNT — YEGANƏ metrik ki, benchmark
        # kataloqunda YOXDUR (bax modul başlığı, `DigestFactProvider`).
        return str(self._facts.late_check_in_count(tenant_id, start=start, end=end))

    def _network_total(
        self, tenant_id: TenantId, metric: BenchmarkMetric, start: date, end: date
    ) -> float:
        """Filial-başına dəyərləri ŞƏBƏKƏ-miqyaslı BİR ədədə endirir.

        Cəm/ortalama seçimi metrikin ÖZÜNÜN tərifidir (`BenchmarkMetric.
        network_aggregation`) — `_multi_store_benchmark._network_value`-nun
        EYNİ məntiqi, LAKİN buradan idxal EDİLMİR: o, modul-daxili (`_` ilə
        başlayan) köməkçidir və iki modul arasında xüsusi asılılıq yaratmaq
        əvəzinə üç sətirlik reduksiya TƏKRARLANIB (`.value` müqayisəsi
        `_NetworkAggregation`-ın ÖZÜNÜ idxal etməkdən qaçır — o, ictimai deyil).
        """
        values = self._benchmark.metric_values(tenant_id, metric, start=start, end=end)
        if not values:
            return 0.0
        numbers = list(values.values())
        if metric.network_aggregation.value == "SUM":
            return sum(numbers)
        return fmean(numbers)

    def _metric_catalog(self, tenant_id: TenantId) -> frozenset[str]:
        raw = self._limits.get_str(
            tenant_id,
            SystemLimitKey.EXECUTIVE_DIGEST_METRIC_CATALOG.value,
            _FALLBACK_METRIC_CATALOG,
        )
        return frozenset(piece.strip().upper() for piece in raw.split(",") if piece.strip())

    def _default_frequency(self, tenant_id: TenantId) -> str:
        return self._limits.get_str(
            tenant_id,
            SystemLimitKey.EXECUTIVE_DIGEST_DEFAULT_FREQUENCY.value,
            _FALLBACK_DEFAULT_FREQUENCY,
        )

    def _weekly_weekday(self, tenant_id: TenantId) -> int:
        raw = self._limits.get_int(
            tenant_id,
            SystemLimitKey.EXECUTIVE_DIGEST_WEEKLY_WEEKDAY.value,
            _FALLBACK_WEEKLY_WEEKDAY,
        )
        # ISO həftə günü 1(Bazar ertəsi)–7(Bazar). Yararsız/hüdud-xarici dəyər
        # ən yaxın hüduda sıxılır — sıfıra bölmə/indeks xətası YARANMASIN.
        return min(7, max(1, raw))


def _due_window(
    config: ExecutiveDigestConfig, *, today: date, weekly_weekday: int
) -> tuple[date, date] | None:
    """Bu KONKRET sətir bu gün DUE-durmu — DUE-dursa `(dövr_başlanğıcı, bugün)`.

    `MONTHLY` (və planlayıcının tanımadığı hər hansı gələcək dəyər) HƏMİŞƏ
    `None` qaytarır — bax `DigestFrequency.is_scheduled` şərhi.
    """
    if config.frequency is DigestFrequency.DAILY:
        if config.last_sent_at is not None and _local_date(config.last_sent_at) >= today:
            return None
        return today - timedelta(days=1), today
    if config.frequency is DigestFrequency.WEEKLY:
        if today.isoweekday() != weekly_weekday:
            return None
        if config.last_sent_at is not None:
            gap = (today - _local_date(config.last_sent_at)).days
            if gap < _WEEKLY_DEDUPE_GAP_DAYS:
                return None
        return today - timedelta(days=7), today
    return None


def _local_date(moment: datetime) -> date:
    """`last_sent_at` UTC-də saxlanılır — `today` İSƏ MAĞAZANIN yerli
    tarixidir (bax `run()`). Müqayisədən ƏVVƏL hər ikisi EYNİ zonaya salınır."""
    return moment.astimezone(_ZONE).date()


__all__ = [
    "CONFIGURE_DIGEST_FLAG",
    "DIGEST_NOTIFICATION_CATEGORY",
    "DigestFactProvider",
    "DigestRunReport",
    "ExecutiveDigestPermissionError",
    "ExecutiveDigestUseCase",
]
