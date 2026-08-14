"""Norma iş günü / norma saat hesablaması — SAF DOMEN QAYDASI (kompas1.md Faza 7).

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA MODUL — VƏ NİYƏ DOMENDƏ
──────────────────────────────────────────────────────────────────────────────
Bu modulun qaytardığı rəqəm birbaşa PULA çevrilir: FAYL 1 (Aylıq Davamiyyət
Hesabatı) fiks maaşın hesablandığı sənəddir və «norma iş günü» sütunu səhv
olarsa işçinin maaşı azalır. Ona görə hesablama nə SQL-də, nə ekranda, nə də
Excel yazıcısında yaşamır — burada, bazasız və deterministik test oluna bilən
saf funksiyada yaşayır (`labor_rules.py` ilə eyni fəlsəfə).

Modul I/O TANIMIR: repository, `Clock`, `datetime.now()` yoxdur. Ona HAZIR
`PlannedDay` görüntüsü verilir. Səbəb `labor_rules.py`-dakı ilə eynidir —
məlumatın necə yığıldığı çağırış yoluna görə dəyişir (tam ay, xüsusi aralıq,
tək işçi), qərar isə hər üç yolda EYNİ olmalıdır.

──────────────────────────────────────────────────────────────────────────────
«NORMA İŞ GÜNÜ» TƏRİFİ — MÖVCUD TƏRİFDƏN DƏYİŞMİR
──────────────────────────────────────────────────────────────────────────────
`report_repositories.py` başlığında seçilmiş tərif SAXLANILIR: **seçilmiş
aralıqda Shift Matrix-də iş günü kimi planlaşdırılmış günlərin sayı**. Sabit
aylıq norma (məs. "22 gün") YOXDUR və qəsdən yoxdur — mağazalar həftənin 7
günü işləyir, növbə qrafiki fərdidir.

Bu modul həmin tərifi İKİ İSTİQAMƏTDƏ genişləndirir:
  1. Aralıq ixtiyari ola bilər (tam ay ARTIQ xüsusi haldır).
  2. Gün sayına ƏLAVƏ olaraq norma SAAT-ı da hesablanır — hər günün öz İş
     Rejimindən (`TimeRange.duration`), yəni işçidən işçiyə fərqli.

──────────────────────────────────────────────────────────────────────────────
İŞ REJİMİ NORMASI ⟷ `OVERTIME_DAILY_NORM_HOURS` — ZİDDİYYƏT QƏRARI
──────────────────────────────────────────────────────────────────────────────
İki mənbə var və onların SÜKUTLA fərqlənməsi ən pis haldır:

  * İş Rejimi (`work_modes.start_time`/`end_time`) — «bu işçiyə həmin gün NƏ
    QƏDƏR PLANLAŞDIRILIB». FƏRDİdir, gündən-günə dəyişə bilər.
  * `OVERTIME_DAILY_NORM_HOURS` (ROOT parametri, defolt 8) — «gündəlik HÜQUQİ
    norma»; `overtime_tracking.py` aşımı MƏHZ ondan hesablayır.

QƏRAR: **plan mənbəyi İş Rejimidir, TAVAN isə hüquqi normadır.** Yəni gündəlik
norma saat = `min(iş_rejimi_müddəti, OVERTIME_DAILY_NORM_HOURS)`.

NİYƏ TAVAN VAR (ALTERNATİVİN RƏDDİ): 12 saatlıq növbə planlaşdırılıbsa və biz
onu olduğu kimi «norma» saysaydıq, həmin 12 saatın 4-ü İKİ DƏFƏ ödənilərdi —
bir dəfə fiks maaşın norması kimi (FAYL 1), bir dəfə də `overtime_log`-dakı
aşım kimi (`overtime_tracking.py` onu 8-dən yuxarı hissə sayır). Tavan qoymaqla
aşım hissəsinin YEGANƏ sahibi overtime moduludur; bu modul yalnız norma
hissəsini bildirir.

Sıxılma SÜKUTLA baş vermir: `WorkNorm.capped_days` neçə günün tavana dəydiyini
sayır və `scheduled_hours` sıxılmadan ƏVVƏLKİ plan saatını saxlayır — fərq
istənilən anda göstərilə bilir.

Sabit saatı OLMAYAN iş rejimi (`WorkMode.schedule is None` — "Növbəli 2/2",
"Sərbəst növbə") üçün gündəlik norma hüquqi normanın ÖZÜDÜR: uydurma saat
seçmək əvəzinə iki mənbədən qalanı işlədilir və `unscheduled_plan_days` ilə
görünür.

──────────────────────────────────────────────────────────────────────────────
GECƏ NÖVBƏSİ VƏ AY/İL SƏRHƏDİ
──────────────────────────────────────────────────────────────────────────────
`TimeRange.duration` gecə növbəsini (22:00–06:00) artıq düzgün ölçür — burada
saat arifmetikası TƏKRARLANMIR, `duration` ÇAĞIRILIR.

Növbə HƏMİŞƏ BAŞLADIĞI günə yazılır (`shift_assignments.shift_date`). 31 dekabr
22:00–06:00 növbəsi tam 8 saatı ilə DEKABR aralığına düşür və yanvara SIZMIR.
Alternativ (saatları iki günə bölmək) rədd edildi: Shift Matrix-in özü günü
tək sətir kimi saxlayır, bölünmə isə iki hesabatın cəmini ayın sərhədində
uyğunsuz edərdi.

──────────────────────────────────────────────────────────────────────────────
PRO-RATA — ƏL DÜZƏLİŞİ TƏLƏB ETMİR
──────────────────────────────────────────────────────────────────────────────
İşçi aralığın ortasında işə düşübsə (və ya çıxıbsa), aralığın ONA AİD OLMAYAN
hissəsi normadan avtomatik çıxarılır: hesablama yalnız aralığın məşğulluq
pəncərəsi ilə KƏSİŞMƏSİNƏ baxır. Plan sətri həmin kəsişmədən kənarda qalsa
belə (HR işə qəbul tarixini sonradan düzəldib) sayılmır — qoruyucu qəsdəndir,
çünki plan cədvəli ilə kadr sənədi arasındakı uyğunsuzluq işçinin xeyrinə
deyil, ZİYANINA da işləyə bilər.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Final

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.shared.exceptions import KompasOSError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from src.domain.value_objects.scheduling import TimeRange

#: Saat çevrilməsinin dəqiqliyi — AZN hesablamaları ilə eyni (iki onluq).
_HOURS_QUANTUM: Final = Decimal("0.01")
#: Pro-rata əmsalının dəqiqliyi. Dörd onluq: 1 günlük fərq 400 günlük aralıqda
#: belə görünən qalır (0.0025), yəni əmsal yuvarlaqlaşma ilə 1.0000-a çevrilib
#: «tam dövr» kimi oxunmur.
_RATIO_QUANTUM: Final = Decimal("0.0001")
_ZERO: Final = Decimal("0.00")
_MINUTES_PER_HOUR: Final = Decimal("60")

#: FALLBACK — HƏQİQİ MƏNBƏ `system_limits.OVERTIME_DAILY_NORM_HOURS`
#: (seed: migrations/026). Burada ədəd YAZILMIR, `DEFAULT_LIMITS`-dən oxunur:
#: `overtime_tracking._FALLBACK_DAILY_NORM` ilə EYNİ sətirdir, yəni iki modul
#: heç vaxt fərqli defoltla işləyə bilməz.
FALLBACK_LEGAL_DAILY_NORM_HOURS: Final[Decimal] = Decimal(
    DEFAULT_LIMITS[SystemLimitKey.OVERTIME_DAILY_NORM_HOURS]
)


class WorkNormError(KompasOSError):
    """Norma hesablana bilmədi — aralıq və ya məşğulluq pəncərəsi ziddiyyətlidir."""

    user_message = "Norma hesablanmadı — seçilmiş tarix aralığı düzgün deyil."


@dataclass(frozen=True)
class PlannedDay:
    """Shift Matrix-in BİR günü, hesablama üçün lazım olan hissəsi.

    `schedule` `None` ola bilər: sabit saatı olmayan iş rejimi (`WorkMode.
    schedule is None`) və ya rejimi təyin edilməmiş iş günü. Hər iki halda
    gündəlik norma hüquqi normadan götürülür (modul başlığına bax).
    """

    day: date
    is_off_day: bool
    schedule: TimeRange | None = None


@dataclass(frozen=True)
class EmploymentWindow:
    """İşçinin məşğulluq pəncərəsi — pro-rata-nın YEGANƏ girişi.

    Hər iki ucu `None` ola bilər və bu, «hədd yoxdur» deməkdir: `started_on`
    boşdursa işçi aralığın əvvəlindən, `ended_on` boşdursa aralığın sonunadək
    işləyib sayılır. Boş dəyəri «işləməyib» kimi oxumaq mövcud kadr
    məlumatının natamamlığına görə işçinin normasını sıfırlayardı — yəni
    məlumat qüsuru maaş kəsintisinə çevrilərdi.
    """

    started_on: date | None = None
    ended_on: date | None = None

    def __post_init__(self) -> None:
        if (
            self.started_on is not None
            and self.ended_on is not None
            and self.ended_on < self.started_on
        ):
            raise WorkNormError(
                "Məşğulluq pəncərəsinin bitmə tarixi başlanğıcdan əvvəl ola bilməz",
                context={"started_on": str(self.started_on), "ended_on": str(self.ended_on)},
            )

    def covers(self, day: date) -> bool:
        """Həmin gün işçiyə aiddirmi."""
        if self.started_on is not None and day < self.started_on:
            return False
        return not (self.ended_on is not None and day > self.ended_on)

    def clamp(self, start: date, end: date) -> tuple[date, date] | None:
        """Aralığın məşğulluq pəncərəsi ilə kəsişməsi; kəsişmə yoxdursa `None`."""
        lower = start if self.started_on is None else max(start, self.started_on)
        upper = end if self.ended_on is None else min(end, self.ended_on)
        if lower > upper:
            return None
        return lower, upper


@dataclass(frozen=True)
class WorkNorm:
    """Bir işçinin bir aralıq üzrə norması — FAYL 1-in rəqəm mənbəyi."""

    #: Aralığın TAM təqvim günü sayı (hər iki uc daxil).
    range_days: int
    #: Aralığın işçinin məşğulluq pəncərəsi ilə kəsişən təqvim günü sayı.
    covered_days: int
    #: Planlaşdırılmış İŞ günləri (istirahət günləri xaric).
    norm_work_days: int
    #: Hüquqi tavanla sıxılmış norma saat cəmi — hesabata BU düşür.
    norm_work_hours: Decimal
    #: Sıxılmadan ƏVVƏLKİ plan saatı — fərq aşım modulunun payıdır.
    scheduled_hours: Decimal
    #: Neçə günün iş rejimi hüquqi normadan uzun olub (tavana dəyib).
    capped_days: int
    #: Sabit saatı olmayan (rejimsiz) planlı iş günü sayı.
    unscheduled_plan_days: int
    #: Planlaşdırılmış istirahət günləri.
    off_days: int

    @property
    def pro_rata_ratio(self) -> Decimal:
        """Aralığın işçiyə AİD hissəsi (0.0000–1.0000).

        SIFIRA BÖLMƏ YOXDUR: `range_days` konstruksiyaya görə ən azı 1-dir
        (bir günlük aralıqda da başlanğıc = bitmə daxildir), lakin qoruyucu
        yenə saxlanılır — bu sinif gələcəkdə başqa yoldan da qurula bilər.
        """
        if self.range_days <= 0:
            return _ZERO
        return (Decimal(self.covered_days) / Decimal(self.range_days)).quantize(
            _RATIO_QUANTUM, rounding=ROUND_HALF_UP
        )

    @property
    def is_prorated(self) -> bool:
        """İşçi aralığın yalnız BİR HİSSƏSİNDƏ işləyibmi."""
        return self.covered_days < self.range_days

    @property
    def average_norm_hours_per_day(self) -> Decimal:
        """Bir norma iş gününə düşən orta saat.

        SIFIR İŞ GÜNÜ OLAN İŞÇİ: `norm_work_days == 0` halında `0.00`
        qaytarılır — bölmə HEÇ VAXT icra olunmur. Bu, tez-tez rast gəlinən
        haldır (uzunmüddətli məzuniyyət, yeni açılan filial) və istisna atmaq
        bütün hesabatı bir işçiyə görə çökdürərdi.
        """
        if self.norm_work_days <= 0:
            return _ZERO
        return (self.norm_work_hours / Decimal(self.norm_work_days)).quantize(
            _HOURS_QUANTUM, rounding=ROUND_HALF_UP
        )


@dataclass(frozen=True)
class WorkNormRequest:
    """`calculate_work_norm` girişi — arqument sayını cilovlamaq üçün.

    Ayrı struktur qəsdəndir: hesablama beş müstəqil giriş alır və onları
    mövqeli arqument kimi ötürmək (tarix, tarix, siyahı, pəncərə, Decimal)
    yerini dəyişdirməklə SÜKUTLA səhv nəticə verə bilərdi.
    """

    start: date
    end: date
    plan: tuple[PlannedDay, ...] = ()
    employment: EmploymentWindow = field(default_factory=EmploymentWindow)
    #: `system_limits.OVERTIME_DAILY_NORM_HOURS` dəyəri (tətbiq qatı oxuyur).
    legal_daily_norm_hours: Decimal = FALLBACK_LEGAL_DAILY_NORM_HOURS

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise WorkNormError(
                "Aralığın bitmə tarixi başlanğıcdan əvvəl ola bilməz",
                user_message="Bitmə tarixi başlanğıc tarixindən əvvəl ola bilməz.",
                context={"start": str(self.start), "end": str(self.end)},
            )


def calculate_work_norm(request: WorkNormRequest) -> WorkNorm:
    """Aralıq + Shift Matrix planı → norma gün/saat (pro-rata AVTOMATİK).

    Düstur bir cümlə ilə: **norma = aralığın işçinin məşğulluq pəncərəsi ilə
    kəsişməsində Shift Matrix-də iş günü kimi planlaşdırılmış günlərin sayı;
    norma saat isə həmin günlərin `min(iş_rejimi_müddəti, hüquqi_gündəlik_
    norma)` cəmidir.**
    """
    span = request.end - request.start
    range_days = span.days + 1

    covered = request.employment.clamp(request.start, request.end)
    covered_days = 0 if covered is None else (covered[1] - covered[0]).days + 1

    cap = _usable_cap(request.legal_daily_norm_hours)

    norm_days = 0
    off_days = 0
    capped_days = 0
    unscheduled = 0
    norm_hours = _ZERO
    scheduled_hours = _ZERO

    for entry in _relevant_days(request):
        if entry.is_off_day:
            off_days += 1
            continue
        norm_days += 1
        if entry.schedule is None:
            # Sabit saatı olmayan rejim — hüquqi norma tətbiq olunur (başlıq).
            unscheduled += 1
            planned = cap
        else:
            planned = _hours(entry.schedule.duration)
            if planned > cap:
                capped_days += 1
        scheduled_hours += planned
        norm_hours += daily_norm_hours(entry.schedule, legal_daily_norm_hours=cap)

    return WorkNorm(
        range_days=range_days,
        covered_days=covered_days,
        norm_work_days=norm_days,
        norm_work_hours=norm_hours.quantize(_HOURS_QUANTUM, rounding=ROUND_HALF_UP),
        scheduled_hours=scheduled_hours.quantize(_HOURS_QUANTUM, rounding=ROUND_HALF_UP),
        capped_days=capped_days,
        unscheduled_plan_days=unscheduled,
        off_days=off_days,
    )


def daily_norm_hours(
    schedule: TimeRange | None,
    *,
    legal_daily_norm_hours: Decimal = FALLBACK_LEGAL_DAILY_NORM_HOURS,
) -> Decimal:
    """BİR günün norma saatı — `min(iş_rejimi_müddəti, hüquqi_norma)`.

    PUBLIC FUNKSİYA QƏSDƏNDİR: eyni rəqəm həm hesabatda (cəmin tərkib hissəsi
    kimi), həm də Shift Matrix-in iş rejimi seçicisində («9:00–18:00 → 8.00
    saat/gün») göstərilir. İki yerdə ayrıca hesablansaydı, GUI-də görünən
    rəqəmlə hesabatdakı rəqəm sükutla fərqlənə bilərdi — bu modulun bütün
    məqsədi məhz həmin fərqi qadağan etməkdir.

    Gecə növbəsi (`22:00–06:00`) `TimeRange.duration` vasitəsilə düzgün
    ölçülür; burada saat arifmetikası TƏKRARLANMIR.
    """
    cap = _usable_cap(legal_daily_norm_hours)
    if schedule is None:
        return cap
    return min(_hours(schedule.duration), cap)


def calendar_days(start: date, end: date) -> list[date]:
    """`[start, end]` aralığındakı bütün təqvim günləri (hər iki uc daxil)."""
    if end < start:
        return []
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _relevant_days(request: WorkNormRequest) -> Iterable[PlannedDay]:
    """Aralıqda VƏ məşğulluq pəncərəsində olan plan sətirləri, günə görə TƏK.

    TƏKRARIN AradaN QALDIRILMASI: `shift_assignments`-də `(employee_id,
    shift_date)` unikaldır, lakin bu funksiya siyahını repository-dən DEYİL,
    ixtiyari çağırandan alır (test, toplu idxal, birləşdirilmiş görüntü).
    Təkrar sətir norma gününü İKİ dəfə saydırardı — yəni işçiyə çatmayan
    saatı «planlaşdırılmış» göstərərdi.
    """
    unique: dict[date, PlannedDay] = {}
    for entry in request.plan:
        if entry.day < request.start or entry.day > request.end:
            continue
        if not request.employment.covers(entry.day):
            continue
        unique[entry.day] = entry
    return [unique[day] for day in sorted(unique)]


def _usable_cap(raw: Decimal) -> Decimal:
    """Hüquqi gündəlik norma — mənasız dəyər fallback-a düşür.

    ROOT ekranı `min_value` ilə qoruyur, lakin ekranı yan keçən skript `0` və
    ya mənfi yaza bilər. O halda HƏR günün norması sıfır olardı və bütün
    şəbəkənin davamiyyət hesabatı sükutla boşalardı — `catalogs._leave_
    duration_ceiling` ilə eyni qərar.
    """
    if raw <= _ZERO:
        return FALLBACK_LEGAL_DAILY_NORM_HOURS
    return raw


def _hours(duration: timedelta) -> Decimal:
    """`timedelta` → saat (iki onluq).

    `TimeRange.duration` gecə növbəsini ARTIQ düzgün ölçür (22:00–06:00 → 8
    saat) — burada saat arifmetikası təkrarlanmır.
    """
    minutes = Decimal(int(duration.total_seconds())) / Decimal("60")
    return (minutes / _MINUTES_PER_HOUR).quantize(_HOURS_QUANTUM, rounding=ROUND_HALF_UP)


__all__ = [
    "FALLBACK_LEGAL_DAILY_NORM_HOURS",
    "EmploymentWindow",
    "PlannedDay",
    "WorkNorm",
    "WorkNormError",
    "WorkNormRequest",
    "calculate_work_norm",
    "calendar_days",
    "daily_norm_hours",
]
