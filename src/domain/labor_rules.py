"""Əmək qanunu xəbərdarlıqları (#14, kompasos11.md Faza 6) — SAF QAYDALAR.

──────────────────────────────────────────────────────────────────────────────
BU MODUL BLOKLAMIR — YALNIZ XƏBƏRDARLIQ ÜRƏTİR
──────────────────────────────────────────────────────────────────────────────
kompasos11.md #14 açıq şəkildə deyir: "BLOKLAMIR — sadəcə xəbərdarlıq göstərir.
Son qərar admindədir." Ona görə burada heç bir funksiya istisna ATMIR və heç
bir təyinatı rədd etmir; hamısı `LaborRuleFinding` siyahısı qaytarır. Tətbiq
qatı onları mövcud `ShiftChangeResult.conflicts` kanalına ötürür (bax
`application.use_cases.shift_scheduling` — YENİ xəbərdarlıq mexanizmi
YARADILMIR, mövcud kanal genişlənir).

Bunun praktik səbəbi var: real mağazada "işçi xəstələndi, bu gün başqası
qalmalıdır" halı qanuni istisnadır və sistem onu bloklasaydı, admin növbəni
KompasOS-dan KƏNARDA (kağızda) planlayardı — yəni sistem məlumatsız qalardı.
Xəbərdarlıq isə qərarı məlumatlı edir və audit izində qalır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SAF DOMEN MODULU — I/O YOXDUR
──────────────────────────────────────────────────────────────────────────────
Qaydalar repository, `datetime.now()` və ya limit portu TANIMIR: onlara HAZIR
`PlannedShift` görüntüsü və HAZIR `LaborLimits` verilir. Səbəb — bu qaydalar
üç fərqli çağırış yolundan işlədilir (admin bir günü dəyişir, həftəni
şablonla doldurur, təsdiqlənmiş Shift Swap təqvimə yazılır) və hər yolda
məlumatın necə yığıldığı FƏRQLİDİR. Məlumat yığımı `application` qatındadır
(`labor_compliance.LaborComplianceAdvisor`), qərar isə burada — beləliklə
qayda testləri bazasız və deterministikdir.

──────────────────────────────────────────────────────────────────────────────
GECƏ NÖVBƏSİ (`TimeRange.is_overnight`)
──────────────────────────────────────────────────────────────────────────────
İstirahət hesablaması növbənin BİTMƏ ANINI istifadə edir, bitmə SAATINI yox.
22:00–06:00 növbəsi növbəti gün 06:00-da bitir; sadəcə `end` saatına baxsaydıq
(06:00 < 22:00) istirahət MƏNFİ çıxardı və qayda ya heç işləməz, ya da hər
gecə növbəsində yalançı xəbərdarlıq verərdi. `TimeRange.end_on()` bu sürüşməni
artıq düzgün edir — burada ondan istifadə olunur, təkrar hesablanmır.

──────────────────────────────────────────────────────────────────────────────
HARDCODE ƏDƏD YOXDUR
──────────────────────────────────────────────────────────────────────────────
Dörd hədd də ROOT parametridir (`SystemLimitKey.LABOR_*`, seed:
migrations/025). `LaborLimits.defaults()` yalnız `DEFAULT_LIMITS`-i oxuyur —
bu faylda ədədi sabit YOXDUR.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import TYPE_CHECKING

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.scheduling import DEFAULT_TIMEZONE

if TYPE_CHECKING:
    from collections.abc import Sequence

    from src.domain.value_objects.scheduling import TimeRange

#: Vahid çevirmə sabitləri — biznes limiti DEYİL, ona görə `system_limits`-də
#: yeri yoxdur (CLAUDE.md §5: soft-coded qaydası KONFİQURASİYA EDİLƏ BİLƏN
#: dəyərlərə aiddir, ölçü vahidlərinə yox).
_SECONDS_PER_MINUTE = 60
_MINUTES_PER_HOUR = 60


class LaborRuleKind(str, Enum):
    """Xəbərdarlığın növü — `ScheduleConflict.kind` dəyəri kimi işlədilir.

    `str, Enum` seçimi CLAUDE.md §4 qaydasıdır: `.value` audit `after_state`-inə
    düşür və `StrEnum`-a keçid həmin sətri sükutla dəyişərdi.
    """

    #: İki ardıcıl növbə arasında minimum istirahət pozulub.
    MIN_REST = "LABOR_MIN_REST"
    #: Növbə uzundur — məcburi fasilə planlaşdırılmalıdır.
    MANDATORY_BREAK = "LABOR_MANDATORY_BREAK"
    #: Ardıcıl iş günlərinin sayı həddi keçir.
    MAX_CONSECUTIVE_DAYS = "LABOR_MAX_CONSECUTIVE_DAYS"


@dataclass(frozen=True)
class LaborLimits:
    """#14-ün dörd ROOT parametri, bir dəfə oxunmuş halda.

    SIFIR = QAYDA SUSUR. Bu, qəsdli seçimdir: Root bir qaydanı söndürmək
    istəsə, onu Feature Toggle-a çevirmək əvəzinə həddi 0 qoyur. Əks halda
    "xəbərdarlığı söndür" üçün ayrıca modul açarı lazım olardı və #14
    bütövlükdə söndürülərdi — halbuki müəssisə çox vaxt yalnız BİR qaydanı
    (məs. fasilə) öz iş rejiminə uyğunsuz sayır.

    Mənfi dəyər 0-a yuvarlaqlaşdırılır: Root ekranı `min_value` ilə qoruyur,
    lakin ekranı yan keçən skript mənfi yaza bilər və növbə matrisi bu
    səbəbdən çökməməlidir (bax `PostgresSystemLimits.get_int` fəlsəfəsi).
    """

    min_rest_hours: int
    mandatory_break_minutes: int
    break_required_after_hours: int
    max_consecutive_work_days: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "min_rest_hours", max(0, self.min_rest_hours))
        object.__setattr__(self, "mandatory_break_minutes", max(0, self.mandatory_break_minutes))
        object.__setattr__(
            self, "break_required_after_hours", max(0, self.break_required_after_hours)
        )
        object.__setattr__(
            self, "max_consecutive_work_days", max(0, self.max_consecutive_work_days)
        )

    @classmethod
    def defaults(cls) -> LaborLimits:
        """`DEFAULT_LIMITS` dəyərləri — YALNIZ fallback.

        HƏQİQİ MƏNBƏ `system_limits`-dir (migrations/025 seed edir); bu metod
        limit portu olmayan çağırış yollarında (məs. saf qayda testi) işlədilir.
        """
        return cls(
            min_rest_hours=int(DEFAULT_LIMITS[SystemLimitKey.LABOR_MIN_REST_HOURS]),
            mandatory_break_minutes=int(
                DEFAULT_LIMITS[SystemLimitKey.LABOR_MANDATORY_BREAK_MINUTES]
            ),
            break_required_after_hours=int(
                DEFAULT_LIMITS[SystemLimitKey.LABOR_BREAK_REQUIRED_AFTER_HOURS]
            ),
            max_consecutive_work_days=int(
                DEFAULT_LIMITS[SystemLimitKey.LABOR_MAX_CONSECUTIVE_WORK_DAYS]
            ),
        )


@dataclass(frozen=True)
class PlannedShift:
    """Bir işçinin bir günü — qayda mühərriki üçün MİNİMAL görünüş.

    `ShiftAssignment` birbaşa işlədilmir, çünki qaydalara nə `assignment_id`,
    nə `assigned_by`, nə də `source` lazımdır — lakin onlara `schedule`
    LAZIMDIR və o, `ShiftAssignment`-də YOXDUR (orada yalnız `work_mode_id`
    var). Ayrı görüntü bu iki fərqi bir yerdə həll edir: tətbiq qatı iş
    rejimini kataloqdan oxuyub bura HAZIR TimeRange kimi ötürür.
    """

    shift_date: date
    is_off_day: bool
    #: `WorkMode.schedule`. `None` = sabit saatı olmayan rejim ("Növbəli 2/2")
    #: və ya rejim tapılmadı — saat-əsaslı qaydalar belə gündə SUSUR.
    schedule: TimeRange | None = None

    @property
    def is_working_day(self) -> bool:
        return not self.is_off_day


@dataclass(frozen=True)
class LaborRuleFinding:
    """Bir pozuntu — BLOKLAYICI DEYİL, xəbərdarlıqdır.

    `message_az` hazır cümlədir: mətn qaydanın YANINDA yazılır, çünki hədd
    dəyəri (məs. "12 saat") mesajın içindədir və onu ekranda yenidən qurmaq
    eyni ədədin İKİ yerdə formatlanması demək olardı.
    """

    kind: LaborRuleKind
    shift_date: date
    message_az: str
    #: Qonşu növbənin tarixi — istirahət qaydasında hansı günlə müqayisə
    #: edildiyini göstərir; digər qaydalarda `None`.
    related_date: date | None = None


def evaluate_labor_rules(
    *,
    target: PlannedShift,
    window: Sequence[PlannedShift],
    limits: LaborLimits,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> list[LaborRuleFinding]:
    """`target` gününü üç əmək qanunu qaydasına qarşı yoxlayır.

    Args:
        target: DƏYİŞDİRİLƏN gün. `window` daxilində köhnə variantı olsa belə
            bu üstün tutulur — admin hələ yazılmamış dəyişikliyi də yoxlaya
            bilsin (`apply_assignment` isə artıq yazılmış halı ötürür).
        window: Ətraf günlərin planı (target daxil ola da bilər, olmaya da).
            GENİŞLİYİ ÖNƏMLİDİR: ardıcıl iş günü sayğacı yalnız bu pəncərədə
            görünən günləri saya bilir — çağıran tərəf `max_consecutive_work_days`
            -dən geniş pəncərə verməlidir (bax `LaborComplianceAdvisor`).
        limits: ROOT parametrləri.
        timezone_name: Növbə saatlarının aid olduğu zona. Defolt mağaza
            zonasıdır; `TimeRange.start_on/end_on` tz-aware `datetime` qurur,
            yəni müqayisə heç vaxt naive vaxt üzərində aparılmır.

    Returns:
        Tapılan xəbərdarlıqlar. Boş siyahı = pozuntu görünmür (SÜBUT deyil:
        pəncərədən kənar günlər yoxlanmır).
    """
    plan = {shift.shift_date: shift for shift in window}
    plan[target.shift_date] = target

    findings: list[LaborRuleFinding] = []
    findings.extend(check_min_rest(target, plan, limits, timezone_name=timezone_name))
    findings.extend(check_mandatory_break(target, limits))
    findings.extend(check_consecutive_days(target, plan, limits))
    return findings


# --------------------------------------------------------------------------- #
# 1. Minimum istirahət (iki ardıcıl növbə arasında)
# --------------------------------------------------------------------------- #


def check_min_rest(
    target: PlannedShift,
    plan: dict[date, PlannedShift],
    limits: LaborLimits,
    *,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> list[LaborRuleFinding]:
    """Əvvəlki növbənin bitməsi ilə bu növbənin başlaması arasındakı fasilə.

    İKİ İSTİQAMƏT YOXLANIR — yalnız "əvvəlki növbə" kifayət etmir: admin
    ORTADAKI günü dəyişəndə pozuntu SONRAKI növbə ilə də yarana bilər
    (məs. bu günü gecə növbəsinə çevirmək sabahkı səhər növbəsini pozur).

    ATLANAN HALLAR — və NİYƏ:
      * `target` istirahət günüdür / saatı yoxdur → ölçüləcək an yoxdur.
      * Qonşu iş günü var, amma onun İş Rejimində sabit saat yoxdur →
        QAYDA SUSUR. Uydurma saat götürmək (məs. 09:00) yalançı xəbərdarlıq
        doğurardı və istifadəçi bir müddət sonra bütün xəbərdarlıqlara
        etibar etməyi dayandırardı.
    """
    if limits.min_rest_hours <= 0 or target.is_off_day or target.schedule is None:
        return []

    required = timedelta(hours=limits.min_rest_hours)
    findings: list[LaborRuleFinding] = []

    previous = _nearest_working_day(plan, target.shift_date, step=-1)
    if previous is not None and previous.schedule is not None:
        rest = target.schedule.start_on(
            target.shift_date, timezone_name=timezone_name
        ) - previous.schedule.end_on(previous.shift_date, timezone_name=timezone_name)
        if rest < required:
            findings.append(
                _rest_finding(
                    shift_date=target.shift_date,
                    related_date=previous.shift_date,
                    rest=rest,
                    limits=limits,
                    previous_is_earlier=True,
                )
            )

    following = _nearest_working_day(plan, target.shift_date, step=1)
    if following is not None and following.schedule is not None:
        rest = following.schedule.start_on(
            following.shift_date, timezone_name=timezone_name
        ) - target.schedule.end_on(target.shift_date, timezone_name=timezone_name)
        if rest < required:
            findings.append(
                _rest_finding(
                    shift_date=target.shift_date,
                    related_date=following.shift_date,
                    rest=rest,
                    limits=limits,
                    previous_is_earlier=False,
                )
            )
    return findings


def _rest_finding(
    *,
    shift_date: date,
    related_date: date,
    rest: timedelta,
    limits: LaborLimits,
    previous_is_earlier: bool,
) -> LaborRuleFinding:
    """İstirahət xəbərdarlığının mətnini qurur.

    ÜST-ÜSTƏ DÜŞMƏ AYRICA CÜMLƏDİR: mənfi fasiləni "−2.0 saat istirahət" kimi
    yazmaq oxucunu çaşdırardı; gecə növbəsindən sonra səhər növbəsi məhz belə
    hal yaradır və admin onu dərhal anlamalıdır.
    """
    neighbour = "əvvəlki" if previous_is_earlier else "sonrakı"
    if rest.total_seconds() < 0:
        detail = (
            f"{neighbour} növbə ({related_date.isoformat()}) ilə ÜST-ÜSTƏ DÜŞÜR — "
            f"aralarında istirahət qalmır"
        )
    else:
        detail = (
            f"{neighbour} növbə ({related_date.isoformat()}) ilə arasında yalnız "
            f"{_format_duration(rest)} qalır"
        )
    return LaborRuleFinding(
        kind=LaborRuleKind.MIN_REST,
        shift_date=shift_date,
        related_date=related_date,
        message_az=(
            f"Əmək qanunu xəbərdarlığı: {detail}. Tələb olunan minimum istirahət "
            f"{limits.min_rest_hours} saatdır. Təyinat bloklanmadı — qərar sizindir."
        ),
    )


def _nearest_working_day(
    plan: dict[date, PlannedShift], origin: date, *, step: int
) -> PlannedShift | None:
    """`origin`-dən başlayaraq ən yaxın İŞ gününü tapır (planda mövcud olanlar).

    PLANDA OLMAYAN GÜN AXTARIŞI DAYANDIRIR: "planlaşdırılmamış" gün istirahət
    günü DEYİL (bax `ShiftPlanningUseCase.clear_day` şərhi), lakin onun
    saatları da yoxdur — ondan o tərəfə keçib daha uzaq növbə ilə müqayisə
    etmək "iki ARDICIL növbə" tərifini pozardı.
    """
    cursor = origin + timedelta(days=step)
    while cursor in plan:
        shift = plan[cursor]
        if shift.is_working_day:
            return shift
        cursor += timedelta(days=step)
    return None


# --------------------------------------------------------------------------- #
# 2. Məcburi fasilə
# --------------------------------------------------------------------------- #


def check_mandatory_break(target: PlannedShift, limits: LaborLimits) -> list[LaborRuleFinding]:
    """Uzun növbədə məcburi fasilənin planlaşdırılması xatırladılır.

    NİYƏ İKİ PARAMETR: fasilənin MÜDDƏTİ ("neçə dəqiqə") və onun MƏCBURİ
    OLDUĞU HƏDD ("neçə saatdan uzun növbədə") fərqli suallardır və müəssisələr
    onları müstəqil təyin edir. Tək parametrlə qayda ya hər növbədə işə
    düşərdi (səs-küy), ya da heç vaxt.

    NİYƏ FAKTİKİ FASİLƏ YOXLANMIR: KompasOS-da fasilə PLANDA deyil, icazə
    axınında (`leave_requests`) qeydə alınır — yəni növbə təyin edilən anda
    işçinin sabah fasilə istəyib-istəməyəcəyi hələ MƏLUM DEYİL. Ona görə bu,
    "fasilə verilmədi" ittihamı yox, planlaşdırma xatırlatmasıdır.
    """
    if (
        limits.mandatory_break_minutes <= 0
        or limits.break_required_after_hours <= 0
        or target.is_off_day
        or target.schedule is None
    ):
        return []

    duration = target.schedule.duration
    threshold = timedelta(hours=limits.break_required_after_hours)
    if duration <= threshold:
        return []

    return [
        LaborRuleFinding(
            kind=LaborRuleKind.MANDATORY_BREAK,
            shift_date=target.shift_date,
            message_az=(
                f"Əmək qanunu xəbərdarlığı: növbə {_format_duration(duration)} davam edir "
                f"({target.schedule.format_az()}). {limits.break_required_after_hours} saatdan "
                f"uzun növbədə {limits.mandatory_break_minutes} dəqiqəlik məcburi fasilə "
                f"nəzərdə tutulmalıdır. Təyinat bloklanmadı — qərar sizindir."
            ),
        )
    ]


# --------------------------------------------------------------------------- #
# 3. Maksimum ardıcıl iş günü
# --------------------------------------------------------------------------- #


def check_consecutive_days(
    target: PlannedShift, plan: dict[date, PlannedShift], limits: LaborLimits
) -> list[LaborRuleFinding]:
    """`target`-i ehtiva edən ardıcıl iş günü zəncirinin uzunluğu.

    İSTİRAHƏT GÜNÜ TƏYİN ETMƏK HEÇ VAXT XƏBƏRDARLIQ DOĞURMUR: o, zənciri
    yalnız QISALDA bilər. Ona görə off-day dərhal qaytarır — əks halda admin
    problemi DÜZƏLDƏN əməliyyatda xəbərdarlıq alardı.

    PLANLAŞDIRILMAMIŞ GÜN ZƏNCİRİ KƏSİR: `clear_day` şərhinə görə belə gün
    istirahət günü deyil, lakin İŞ günü də deyil — sayğac yalnız faktiki
    təyin edilmiş iş günlərini sayır.
    """
    if limits.max_consecutive_work_days <= 0 or target.is_off_day:
        return []

    first = target.shift_date
    while True:
        previous = first - timedelta(days=1)
        shift = plan.get(previous)
        if shift is None or not shift.is_working_day:
            break
        first = previous

    last = target.shift_date
    while True:
        following = last + timedelta(days=1)
        shift = plan.get(following)
        if shift is None or not shift.is_working_day:
            break
        last = following

    streak = (last - first).days + 1
    if streak <= limits.max_consecutive_work_days:
        return []

    return [
        LaborRuleFinding(
            kind=LaborRuleKind.MAX_CONSECUTIVE_DAYS,
            shift_date=target.shift_date,
            message_az=(
                f"Əmək qanunu xəbərdarlığı: bu təyinatla işçinin ardıcıl iş günü sayı "
                f"{streak} olur ({first.isoformat()} – {last.isoformat()}). İcazə verilən "
                f"maksimum {limits.max_consecutive_work_days} gündür. Təyinat bloklanmadı — "
                f"qərar sizindir."
            ),
        )
    ]


# --------------------------------------------------------------------------- #
# Formatlama
# --------------------------------------------------------------------------- #


def _format_duration(value: timedelta) -> str:
    """`timedelta` → "10 saat 30 dəqiqə" (Azərbaycan dili, bölmə 9).

    `strftime`/`%H:%M` işlədilmir: 26 saatlıq fərq orada "02:00" kimi
    görünərdi və xəbərdarlıq tam əksini deyərdi.
    """
    total_minutes = int(abs(value).total_seconds()) // _SECONDS_PER_MINUTE
    hours, minutes = divmod(total_minutes, _MINUTES_PER_HOUR)
    if hours and minutes:
        return f"{hours} saat {minutes} dəqiqə"
    if hours:
        return f"{hours} saat"
    return f"{minutes} dəqiqə"


__all__ = [
    "LaborLimits",
    "LaborRuleFinding",
    "LaborRuleKind",
    "PlannedShift",
    "check_consecutive_days",
    "check_mandatory_break",
    "check_min_rest",
    "evaluate_labor_rules",
]
