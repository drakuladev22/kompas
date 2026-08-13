"""Norma üstü iş saatlarının izlənməsi (#15, kompasos11.md Faza 6).

Mövcud davamiyyət hesablamasına ƏLAVƏDİR — onu ƏVƏZ ETMİR. `Daily
AttendanceSheetUseCase` (tabelin açılması, müqayisəsi, təsdiqi) və
`MonthlyReportUseCase` (norma/faktiki GÜN sayı) OLDUĞU KİMİ qalır; bu modul
yalnız onların toxunmadığı sualı cavablandırır: "həmin gün neçə SAAT işlənib
və bu, normadan çoxdurmu?".

──────────────────────────────────────────────────────────────────────────────
NİYƏ YAZMA ANI TABELİN TƏSDİQİDİR
──────────────────────────────────────────────────────────────────────────────
Aşım gün ərzində də hesablana bilərdi (məs. hər check-in-dən sonra), lakin
təsdiqdən əvvəlki rəqəm HƏLƏ MÜBAHİSƏLİDİR: menecer sətri nəzərdən keçirir,
"PIN işləmirdi, şifahi təsdiq" kimi kontekst yazır, uyğunsuzluqlar HR-a
gedir. Təsdiqə qədər dəyişən rəqəmi jurnala yazmaq iki zərər verərdi:

    1. HR eyni gün üçün bir neçə dəfə "norma aşıldı" bildirişi alardı və
       kanal səs-küyə çevrilərdi;
    2. `overtime_log` sətri əmək saatı İDDİASIDIR — imzalanmamış tabeldən
       çıxan rəqəm mübahisədə sübut kimi işlədilə bilməz.

`DailyAttendanceSheet.confirm()` isə dəqiq həmin anı işarələyir: menecer
imzaladı, sətirlər donduruldu (təsdiqlənmiş tabel yenidən doldurulmur).

──────────────────────────────────────────────────────────────────────────────
GÜNDƏLİK VƏ HƏFTƏLİK NORMA BİR SƏTİRDƏ NECƏ BİRLƏŞİR
──────────────────────────────────────────────────────────────────────────────
`overtime_log` cədvəlində bir işçi-gün üçün BİR sətir var (DDL UNIQUE) — yəni
"həftəlik aşım" üçün ayrıca sətir yeri YOXDUR və olmamalıdır (əks halda eyni
saat iki sətirdə görünüb hesabatda İKİQAT sayılardı). Ona görə həftəlik norma
GÜNƏ PAYLANIR::

    gündəlik_aşım  = maks(0, faktiki − gündəlik_norma)
    həftəlik_aşım  = maks(0, həftənin_cəmi − həftəlik_norma)
    həftəlik_pay   = maks(0, həftəlik_aşım − həftənin_artıq_yazılmış_aşımı)
    sətrin_aşımı   = maks(gündəlik_aşım, həftəlik_pay)

`maks` (cəm YOX) qəsdəndir: 10 saatlıq günün 2 saatı ARTIQ gündəlik aşım kimi
yazılıb, onu həftəlik payla toplasaydıq eyni saat iki dəfə sayılardı.
"Artıq yazılmış aşım" isə həftənin DİGƏR sətirlərindən oxunur, ona görə
günlərin təsdiq SIRASI nəticəni pozmur: qalıq payı həmişə SONUNCU təsdiqlənən
gün daşıyır və həftənin cəmi düz çıxır.

Həftə ISO konvensiyasındadır (Bazar ertəsi–Bazar) — migrations/019 həftə günü
nömrələnməsini məhz bu şəkildə kilidləyir ("dörd fərqli nömrələmə arasında
sükutla seçim etmək klassik bir-gün-sürüşmə qüsurudur").

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI BİLDİRİŞ MEXANİZMİ YOXDUR
──────────────────────────────────────────────────────────────────────────────
Aşım xəbəri MÖVCUD `Notifier` portundan keçir (`is_critical=True` → bölmə 7-nin
e-poçt ehtiyat kanalı). Yeni kanal yazmaq həmin fallback-ı (SMTP konfiqurasiyası,
kritiklik yüksəltmə qaydası, auditoriya süzgəci) sıfırdan təkrarlamaq demək
olardı — və təkrarlanan nüsxə mütləq bir gün orijinaldan geri qalır.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Final

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.overtime import OvertimeEntry, OvertimeSource, to_hours
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        Clock,
        Notifier,
        OvertimeLogRepository,
        SystemLimits,
        WorkedHoursProvider,
    )
    from src.domain.value_objects.identifiers import StoreId, TenantId
    from src.domain.value_objects.overtime import WorkedSpan

_log = get_logger(__name__)
_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

#: Aşım hesabatını görən tərəf — tabel uyğunsuzluğu ilə EYNİ auditoriya
#: (`daily_attendance.VIEW_REPORTS_FLAG`): hər ikisi işçinin iş vaxtı barədə
#: fərdi məlumatdır və `Satıcı` onu görməməlidir.
VIEW_REPORTS_FLAG: Final = "can_view_employee_reports"

#: `notifications.category` dəyəri. Auditoriyası
#: `value_objects/notifications.TENANT_NOTIFICATION_AUDIENCE`-dədir — sətir
#: `recipient_id IS NULL` ilə yazılır (konkret HR işçisi məlum deyil) və
#: süzgəcsiz qalsaydı bütün işçilərə görünərdi.
OVERTIME_NOTIFY_CATEGORY: Final = "OVERTIME_NORM_EXCEEDED"

#: Fallback dəyərlər — bax `policies.py`-dakı `SystemLimitKey.OVERTIME_*`
#: şərhləri. HƏQİQİ MƏNBƏ `system_limits`-dir (migrations/026 seed edir);
#: bu sabitlər YALNIZ sətir hələ seed edilməyibsə işə düşür.
_FALLBACK_DAILY_NORM: Final = Decimal(DEFAULT_LIMITS[SystemLimitKey.OVERTIME_DAILY_NORM_HOURS])
_FALLBACK_WEEKLY_NORM: Final = Decimal(DEFAULT_LIMITS[SystemLimitKey.OVERTIME_WEEKLY_NORM_HOURS])
_FALLBACK_NOTIFY_THRESHOLD: Final = Decimal(
    DEFAULT_LIMITS[SystemLimitKey.OVERTIME_NOTIFY_THRESHOLD_HOURS]
)

_ZERO: Final = Decimal("0.00")


class OvertimePermissionError(KompasOSError):
    """Aşım jurnalına baxmaq səlahiyyəti yoxdur."""

    user_message = "Norma üstü iş saatlarına baxmaq səlahiyyətiniz yoxdur."


@dataclass(frozen=True)
class OvertimeDayReport:
    """Bir mağazanın bir gününə aid hesablamanın yekunu.

    Çağırana QAYTARILIR (yalnız loga yazılmır), çünki tabel təsdiqini edən
    ekran "bu təsdiq nə yaratdı?" sualına cavab verə bilməlidir — sükutla
    yazılan yan-təsir sonradan izah edilməsi ən çətin davranışdır.
    """

    tenant_id: TenantId
    store_id: StoreId
    work_date: date
    daily_norm_hours: Decimal
    weekly_norm_hours: Decimal
    entries: list[OvertimeEntry]
    notified: bool = False

    @property
    def exceeded_entries(self) -> list[OvertimeEntry]:
        return [entry for entry in self.entries if entry.has_overtime]

    @property
    def total_over_norm(self) -> Decimal:
        return to_hours(sum((entry.hours_over_norm for entry in self.entries), start=_ZERO))


class OvertimeTrackingUseCase:
    """Təsdiqlənmiş tabeldən norma üstü saatları çıxarır və jurnala yazır."""

    def __init__(
        self,
        *,
        overtime_log: OvertimeLogRepository,
        worked_hours: WorkedHoursProvider,
        limits: SystemLimits,
        notifier: Notifier,
        clock: Clock,
    ) -> None:
        self._overtime_log = overtime_log
        self._worked_hours = worked_hours
        self._limits = limits
        self._notifier = notifier
        self._clock = clock

    # ------------------------------- hesablama -------------------------------- #

    def record_for_day(
        self, *, tenant_id: TenantId, store_id: StoreId, work_date: date
    ) -> OvertimeDayReport:
        """Bir mağazanın bir günü üçün aşımı hesablayır və UPSERT edir.

        İDEMPOTENTDİR: təkrar çağırış eyni nəticəni verir, çünki (a) yazı
        `ON CONFLICT (tenant_id, employee_id, work_date)` ilə üstündən yazır,
        (b) həftəlik pay hesablanarkən HƏMİN GÜNÜN öz sətri kənarda saxlanılır
        — əks halda ikinci icra öz nəticəsini "artıq yazılmış aşım" sayıb payı
        səhvən sıfıra endirərdi.

        Səlahiyyət yoxlaması BURADA YOXDUR: metod tabel təsdiqinin (artıq
        `can_fill_daily_attendance` tələb edən əməliyyatın) davamıdır və
        planlaşdırılmış yenidən-hesablamadan da çağırıla bilir. İnsan girişi
        olan yol `overtime_for_period()`-dur və orada yoxlama VAR.
        """
        daily_norm = self._limit_hours(
            tenant_id, SystemLimitKey.OVERTIME_DAILY_NORM_HOURS, _FALLBACK_DAILY_NORM
        )
        weekly_norm = self._limit_hours(
            tenant_id, SystemLimitKey.OVERTIME_WEEKLY_NORM_HOURS, _FALLBACK_WEEKLY_NORM
        )
        threshold = self._limit_hours(
            tenant_id,
            SystemLimitKey.OVERTIME_NOTIFY_THRESHOLD_HOURS,
            _FALLBACK_NOTIFY_THRESHOLD,
        )

        week_start, week_end = iso_week_bounds(work_date)
        entries: list[OvertimeEntry] = []

        for span in self._worked_hours.spans_for(store_id, work_date):
            # Ölçülə bilməyən gün (növbə təyinatı və ya təsdiqlənmiş giriş
            # yoxdur) jurnala DÜŞMÜR — bax `WorkedSpan.is_measurable`.
            if not span.is_measurable:
                continue

            actual = span.worked_hours
            hours_over = self._hours_over_norm(
                tenant_id=tenant_id,
                span=span,
                actual=actual,
                daily_norm=daily_norm,
                weekly_norm=weekly_norm,
                week_start=week_start,
                week_end=week_end,
            )
            entry = OvertimeEntry(
                tenant_id=tenant_id,
                employee_id=span.employee_id,
                work_date=work_date,
                # Dondurulan norma GÜNDƏLİK normadır (DDL: "həmin gün üçün
                # qüvvədə olan norma"). Həftəlik norma sətrin ÖZÜNÜN ölçüsü
                # deyil, aşımın PAYLANMA qaydasıdır — ona görə `norm_hours`-a
                # yazılmır, yalnız `hours_over_norm`-a təsir edir.
                norm_hours=daily_norm,
                actual_hours=actual,
                hours_over_norm=hours_over,
                source=OvertimeSource.AUTO_ATTENDANCE,
            )
            self._overtime_log.save(entry)
            entries.append(entry)

        report = OvertimeDayReport(
            tenant_id=tenant_id,
            store_id=store_id,
            work_date=work_date,
            daily_norm_hours=daily_norm,
            weekly_norm_hours=weekly_norm,
            entries=entries,
        )
        _log.info(
            "OVERTIME_CALCULATED",
            extra={
                "magaza": str(store_id),
                "is_gunu": work_date.isoformat(),
                "yazilan_setir": len(entries),
                "asim_olan": len(report.exceeded_entries),
                "cemi_asim_saat": str(report.total_over_norm),
            },
        )
        # `replace`: hesabat DƏYİŞMƏZ (frozen) tipdir və bildiriş nəticəsi
        # yalnız göndərişdən sonra bilinir — sahəni mutasiya etmək əvəzinə
        # tək sahəsi yenilənmiş nüsxə qaytarılır.
        return replace(report, notified=self._notify_if_needed(report, threshold=threshold))

    # -------------------------------- oxu ------------------------------------ #

    def overtime_for_period(
        self, *, tenant_id: TenantId, actor: Employee, start: date, end: date
    ) -> list[OvertimeEntry]:
        """Dövr üzrə aşım sətirləri — HR hesabatı üçün (yalnız oxu).

        Səlahiyyət yoxlaması sükutla boş siyahı QAYTARMIR, açıq istisna atır:
        istifadəçi düyməni basıb və "aşım yoxdur" ilə "sizə göstərilmir"
        arasındakı fərq onun üçün həlledicidir.
        """
        now = self._clock.now()
        if not actor.has_permission(VIEW_REPORTS_FLAG, now=now):
            _audit_log.warning(
                "OVERTIME_VIEW_DENIED",
                extra={"aktor": str(actor.id), "flag": VIEW_REPORTS_FLAG},
            )
            raise OvertimePermissionError(
                f"«{VIEW_REPORTS_FLAG}» səlahiyyəti yoxdur",
                context={"actor_id": str(actor.id)},
            )
        if end < start:
            start, end = end, start
        return self._overtime_log.list_for_period(tenant_id, start=start, end=end)

    # ------------------------------ köməkçilər -------------------------------- #

    def _hours_over_norm(
        self,
        *,
        tenant_id: TenantId,
        span: WorkedSpan,
        actual: Decimal,
        daily_norm: Decimal,
        weekly_norm: Decimal,
        week_start: date,
        week_end: date,
    ) -> Decimal:
        """Modul başlığındakı dörd sətirlik düsturun tətbiqi."""
        daily_over = max(_ZERO, actual - daily_norm)

        # HƏMİN GÜNÜN öz sətri kənarda saxlanılır — bax `record_for_day`
        # idempotentlik izahı.
        other_days = [
            entry
            for entry in self._overtime_log.list_for_employee_period(
                tenant_id, span.employee_id, start=week_start, end=week_end
            )
            if entry.work_date != span.work_date
        ]
        week_actual = sum((entry.actual_hours for entry in other_days), start=actual)
        already_attributed = sum((entry.hours_over_norm for entry in other_days), start=Decimal(0))

        week_over = max(_ZERO, week_actual - weekly_norm)
        weekly_share = max(_ZERO, week_over - already_attributed)
        return to_hours(max(daily_over, weekly_share))

    def _notify_if_needed(self, report: OvertimeDayReport, *, threshold: Decimal) -> bool:
        """Hədddən böyük aşım varsa HR_Admin-ə BİR bildiriş göndərir.

        İşçi başına ayrıca bildiriş QƏSDƏN göndərilmir: 21 filialın hər birində
        onlarla işçi var və "hər sətir bir mesaj" qaydası kanalı bir gündə
        yararsız edərdi. Sətirlərin özü jurnaldadır və hesabatdan oxunur.
        """
        # `has_overtime` şərti həddin 0 qoyulduğu halı da düzgün saxlayır:
        # o zaman HƏR faktiki aşım bildirilir, lakin 0.00 sətirlər (yenidən
        # hesablamadan sonra aşımı qalmayanlar) yenə də kənarda qalır.
        exceeded = [
            entry
            for entry in report.entries
            if entry.has_overtime and entry.hours_over_norm >= threshold
        ]
        if not exceeded:
            return False

        total = to_hours(sum((entry.hours_over_norm for entry in exceeded), start=_ZERO))
        self._notifier.notify(
            tenant_id=report.tenant_id,
            # Konkret HR işçisi məlum deyil — sətir "bunu edə bilən adam
            # görsün" deməkdir (bax `notifications.py` auditoriya cədvəli).
            recipient_id=None,
            category=OVERTIME_NOTIFY_CATEGORY,
            title_az="Norma üstü iş saatı aşkarlandı",
            body_az=(
                f"{report.work_date.isoformat()} tarixli təsdiqlənmiş tabeldə "
                f"{len(exceeded)} işçidə norma üstü iş saatı var (cəmi "
                f"{total} saat). Qüvvədə olan norma: gündə "
                f"{report.daily_norm_hours} saat, həftədə "
                f"{report.weekly_norm_hours} saat. Əmək vaxtı uçotunun "
                f"yoxlanılması tələb oluna bilər."
            ),
            # Bölmə 7-nin e-poçt ehtiyat kanalı: aşım əmək qanunvericiliyi
            # riskidir və tətbiqi günlərlə açmayan HR üçün tətbiq-daxili
            # sətir kifayət etmir. Səs-küy riskini `threshold` bağlayır.
            is_critical=True,
        )
        _audit_log.info(
            "OVERTIME_NOTIFIED",
            extra={
                "magaza": str(report.store_id),
                "is_gunu": report.work_date.isoformat(),
                "isci_sayi": len(exceeded),
                "cemi_asim_saat": str(total),
            },
        )
        return True

    def _limit_hours(self, tenant_id: TenantId, key: SystemLimitKey, fallback: Decimal) -> Decimal:
        """`system_limits`-dən saat dəyəri oxuyur (yararsız mətn → fallback).

        Root-un yazı səhvi (boş sətir, vergüllü format, mənfi ədəd) tabelin
        TƏSDİQİNİ çökdürməməlidir — menecerin imzası aşım hesablamasından
        daha vacibdir. `BehaviorAnomalyRule._parse_float` ilə eyni fəlsəfə.
        """
        raw = self._limits.get_str(tenant_id, key.value, str(fallback))
        try:
            value = Decimal(str(raw).strip().replace(",", "."))
        except (InvalidOperation, ValueError, AttributeError):
            return fallback
        if value < 0:
            return fallback
        return value


def iso_week_bounds(day: date) -> tuple[date, date]:
    """Günün daxil olduğu ISO həftəsi: (Bazar ertəsi, Bazar).

    `date.weekday()` (0 = Bazar ertəsi) işlədilir — migrations/019 həftə günü
    konvensiyasını ISO kimi kilidləyir və `EXTRACT(DOW)` (0 = Bazar) qəsdən
    işlədilmir. Həftə sərhədində (Bazar → Bazar ertəsi) yeni həftə BAŞLAYIR,
    yəni bazar günü işlənən saat növbəti həftənin normasına daxil olmur.
    """
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


__all__ = [
    "OVERTIME_NOTIFY_CATEGORY",
    "VIEW_REPORTS_FLAG",
    "OvertimeDayReport",
    "OvertimePermissionError",
    "OvertimeTrackingUseCase",
    "iso_week_bounds",
]
