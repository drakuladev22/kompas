"""İllik məzuniyyət haqqının hesablanması (#28) — SAF QAYDA MODULU.

──────────────────────────────────────────────────────────────────────────────
BU MODUL ÜÇ MEXANİZMDƏN HANSINA AİDDİR
──────────────────────────────────────────────────────────────────────────────
KompasOS-da "icazə/istirahət" sözü ÜÇ AYRI şeyi bildirir və bu fayl YALNIZ
üçüncüsünə aiddir:

    1. GÜNDAXİLİ İCAZƏ (STEP1/STEP2) — saatlıq, iş günü ərzində çıxış;
       vahidi DƏQİQƏ, nəticəsi cərimə. `leave_verification.py`,
       `morning_check_in.py`, `MonthlyLeaveUsage` (240 dəq.), `LeaveTypeCatalog`.
    2. SHIFT MATRIX OFF-DAY — növbə cədvəlindəki istirahət günü; vahidi PLAN,
       nəticəsi "bu gün işləmir". `shift_scheduling.py`.
    3. İLLİK MƏZUNİYYƏT (BU MODUL) — uzun-müddətli illik haqq; vahidi GÜN,
       nəticəsi balansdan çıxma.

Bunları BİRLƏŞDİRMƏK cazibədardır ("hamısı işə gəlməməkdir"), lakin yanlışdır:
birincinin aylıq tavanı var və cərimə doğurur, ikincisi PLANDIR (haqq deyil),
üçüncüsü isə İL boyu yığılan və pul dəyəri daşıyan haqqdır. Vahid model
qurulsaydı, 60 dəqiqəlik nahar fasiləsi illik məzuniyyət balansından gün
çıxarardı.

Bu modul ikinci mexanizmi YALNIZ OXUYUR (hansı gün istirahətdir?) və heç vaxt
DƏYİŞDİRMİR; birinciyə isə ümumiyyətlə toxunmur.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SAF DOMEN MODULU — I/O YOXDUR
──────────────────────────────────────────────────────────────────────────────
`attrition_rules.py` / `labor_rules.py` ilə EYNİ bölgü: bu fayl repository,
`Clock` və `SystemLimits` TANIMIR — ona artıq oxunmuş `AnnualLeavePolicy` və
düz arqumentlər verilir. Məlumat yığımı (`system_limits` oxusu, Shift Matrix
sorğusu) tətbiq qatındadır (`application/use_cases/annual_leave.py`), yəni
hesablama testləri bazasız və deterministikdir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `Decimal`, NİYƏ `float` DEYİL
──────────────────────────────────────────────────────────────────────────────
`annual_leave_balances.entitled_days` sxemdə `NUMERIC(5,2)`-dir və miqrasiya
şərhi səbəbi yazır: yarım-gün məzuniyyət real HR praktikasıdır, ikilik kəsr
isə 0.1-i dəqiq saxlamır və balans illər boyu sürüşərdi. Hesablama qatı
DB ilə eyni tipdə işləməlidir — əks halda yuvarlaqlaşdırma fərqi məhz
`CHECK (used_days <= entitled_days + carried_over_days)` sərhədində üzə
çıxardı.

──────────────────────────────────────────────────────────────────────────────
YUVARLAQLAŞDIRMA QƏRARI
──────────────────────────────────────────────────────────────────────────────
Bütün nəticələr iki onluğa `ROUND_HALF_UP` ilə yuvarlaqlaşdırılır. `ROUND_DOWN`
seçilsəydi, hər proporsional hesablama işçinin ZİYANINA kəsilərdi (21 × 200/365
= 11.5068 → 11.50) və bu, sistematik bir qərəz olardı; `ROUND_HALF_UP` isə
neytraldır və `NUMERIC(5,2)` sütununa itkisiz oturur.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Final

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey

#: Gün sütunlarının onluq dəqiqliyi — `NUMERIC(5,2)` ilə eyni (migrations/037).
DAY_QUANTUM: Final[Decimal] = Decimal("0.01")

_ZERO: Final[Decimal] = Decimal("0")


def quantize_days(value: Decimal) -> Decimal:
    """Gün dəyərini `NUMERIC(5,2)` dəqiqliyinə gətirir (bax modul başlığı)."""
    return value.quantize(DAY_QUANTUM, rounding=ROUND_HALF_UP)


class AccrualPeriod(str, Enum):
    """`ANNUAL_LEAVE_ACCRUAL_PERIOD` — haqqın hansı ritmlə qazanıldığı.

    `ANNUAL` DİGƏR İKİSİNDƏN STRUKTUR OLARAQ FƏRQLİDİR: orada haqq ilin
    ƏVVƏLİNDƏ tam verilir (yalnız işə qəbul tarixinə görə proporsional
    kəsilir), `MONTHLY`/`QUARTERLY`-də isə TAMAMLANMIŞ dövr başına toplanır.
    Fərq süni deyil — "front-loaded" model İşçi Ana Ekranındakı "14/21 gün
    qalıb" kartının mənasını verir; toplanan modeldə həmin kart yanvarda
    "0/1.75" göstərərdi və işçi yay məzuniyyətini planlaya bilməzdi.

    DÖRDÜNCÜ VARİANT (məs. "HƏFTƏLİK") QƏSDƏN YOXDUR: dövr sərhədi TƏQVİM
    sərhədinə oturmalıdır ki, "neçə dövr tamamlanıb?" sualının cavabı
    terminaldan-terminala dəyişməsin (`JobCadence` ilə eyni əsaslandırma).
    """

    ANNUAL = "ANNUAL"
    QUARTERLY = "QUARTERLY"
    MONTHLY = "MONTHLY"

    @property
    def periods_per_year(self) -> int:
        if self is AccrualPeriod.MONTHLY:
            return 12
        if self is AccrualPeriod.QUARTERLY:
            return 4
        return 1

    @property
    def is_front_loaded(self) -> bool:
        """Haqq ilin əvvəlində TAM verilirmi (bax sinif şərhi)."""
        return self is AccrualPeriod.ANNUAL

    @classmethod
    def from_value(cls, raw: str) -> AccrualPeriod:
        """Naməlum/səhv dəyər → `ANNUAL`.

        İSTİSNA ATILMIR: Root sətrində yazı səhvi olsa, işçinin balansı
        ÜMUMİYYƏTLƏ hesablana bilməzdi və ekran boş qalardı. Ən geniş yayılmış
        və ən səxavətli variant təhlükəsiz defoltdur.
        """
        try:
            return cls(raw.strip().upper())
        except (AttributeError, ValueError):
            return cls.ANNUAL


class LeaveDayCountMode(str, Enum):
    """`ANNUAL_LEAVE_DAY_COUNT_MODE` — balansdan neçə gün çıxılır.

    ──────────────────────────────────────────────────────────────────────────
    İSTİRAHƏT/BAYRAM GÜNÜ SAYILIRMI — QƏRAR VƏ ƏSASLANDIRMASI
    ──────────────────────────────────────────────────────────────────────────
    DEFOLT `WORKING_DAYS`-dir: balansdan YALNIZ işçinin faktiki işləməli
    olduğu günlər çıxılır. Səbəb `migrations/037`-dəki `deducted_days`
    şərhidir — "təqvim günü deyil: istirahət günləri Shift Matrix-dən
    asılıdır". İşçi növbə cədvəlində onsuz da istirahət olan günü
    "məzuniyyət" kimi ödəməməlidir.

    AYRICA BAYRAM TƏQVİMİ CƏDVƏLİ YARADILMADI. Bu, unutqanlıq deyil: KompasOS-da
    "bu işçi həmin gün işləyirmi?" sualının TƏK mənbəyi Shift Matrix-dir
    (`shift_assignments`). İkinci mənbə (bayram kataloqu) qurulsaydı, iki
    cavab bir-birinə zidd ola bilərdi — matris "iş günü", kataloq "bayram" —
    və hansının üstün olduğu sualı hər hesablamada təkrar yaranardı. Bayram
    KompasOS-da artıq ifadə olunur: HR həmin günü matrisdə istirahət günü
    kimi işarələyir və o, avtomatik olaraq balansdan çıxılmır.

    `CALENDAR_DAYS` variantı isə qanuni tələb üçün saxlanılıb: Azərbaycan Əmək
    Məcəlləsi əsas məzuniyyəti TƏQVİM günü ilə ölçür. Hansı oxunuşun tətbiq
    olunacağı hüquqi qərardır, kod qərarı deyil — ona görə ROOT parametridir.
    """

    WORKING_DAYS = "WORKING_DAYS"
    CALENDAR_DAYS = "CALENDAR_DAYS"

    @classmethod
    def from_value(cls, raw: str) -> LeaveDayCountMode:
        """Naməlum dəyər → `WORKING_DAYS` (bax `AccrualPeriod.from_value`)."""
        try:
            return cls(raw.strip().upper())
        except (AttributeError, ValueError):
            return cls.WORKING_DAYS


@dataclass(frozen=True)
class AnnualLeaveRolloverInput:
    """İl dönümü işinin BİR işçi üçün girişi (SQL aqreqasiyasından sonra).

    `previous_available_days` KEÇƏN ilin qalığıdır (`entitled + carried_over -
    used`). Aqreqasiya SQL-də edilir: 235 işçinin balans sətrini yaddaşa
    gətirib Python-da çıxmaq gecə işi üçün mənasız yük olardı
    (`count_claims_in_month` ilə eyni qərar).
    """

    employee_id: object
    hire_date: date | None
    previous_available_days: Decimal


@dataclass(frozen=True)
class AnnualLeaveEntitlement:
    """Bir işçinin bir il üçün hesablanmış haqqı — izahı ilə birlikdə.

    İZAH SAHƏLƏRİ (`base_days`, `seniority_days`, `earned_fraction`) QƏSDƏN
    QAYTARILIR: "sənin haqqın 22.5 gündür" cümləsi mübahisədə heç nə sübut
    etmir; sübut edən "21 baza + 1 staj, işə qəbul 15 mart olduğu üçün ilin
    80%-i" izahıdır (`AttritionScore.factors` ilə eyni fəlsəfə).
    """

    year: int
    days: Decimal
    base_days: Decimal
    seniority_days: Decimal
    earned_fraction: Decimal


@dataclass(frozen=True)
class AnnualLeavePolicy:
    """İllik məzuniyyət siyasətinin ON ROOT parametri, tək obyektdə.

    SİNİFDƏ SABİT ƏDƏD YOXDUR — bax `defaults()`.
    """

    base_entitlement_days: Decimal
    seniority_period_years: int
    seniority_bonus_days: Decimal
    seniority_bonus_max_days: Decimal
    carryover_max_days: Decimal
    carryover_deadline_month: int
    carryover_deadline_day: int
    accrual_period: AccrualPeriod
    accrual_rate_days_per_period: Decimal
    day_count_mode: LeaveDayCountMode

    def __post_init__(self) -> None:
        # SIXMA, İSTİSNA DEYİL: `system_limits.set_value()` sərbəst mətn yazır
        # və mənfi dəyər ekranı AÇILMAZ etməməlidir (`root_limits._clamp` ilə
        # eyni fəlsəfə). Mənfi haqq isə mənfi balans deməkdir — bu, DB
        # `CHECK`-inin qadağan etdiyi vəziyyətdir.
        object.__setattr__(self, "base_entitlement_days", _non_negative(self.base_entitlement_days))
        object.__setattr__(self, "seniority_period_years", max(1, self.seniority_period_years))
        object.__setattr__(self, "seniority_bonus_days", _non_negative(self.seniority_bonus_days))
        object.__setattr__(
            self, "seniority_bonus_max_days", _non_negative(self.seniority_bonus_max_days)
        )
        object.__setattr__(self, "carryover_max_days", _non_negative(self.carryover_max_days))
        object.__setattr__(
            self, "carryover_deadline_month", _clamp_int(self.carryover_deadline_month, 1, 12)
        )
        object.__setattr__(
            self, "carryover_deadline_day", _clamp_int(self.carryover_deadline_day, 1, 31)
        )
        object.__setattr__(
            self, "accrual_rate_days_per_period", _non_negative(self.accrual_rate_days_per_period)
        )

    # ------------------------------- qurulma --------------------------------- #

    @classmethod
    def defaults(cls) -> AnnualLeavePolicy:
        """`DEFAULT_LIMITS` dəyərləri — YALNIZ fallback.

        HƏQİQİ MƏNBƏ `system_limits`-dir (migrations/040 seed edir); bu metod
        limit portu olmayan çağırış yollarında (saf qayda testi, önizləmə
        rejimi) işlədilir. Bu faylda ƏDƏDİ SABİT YOXDUR və olmamalıdır —
        `AttritionWeights.defaults()` ilə eyni qayda.
        """
        return cls.from_limits({})

    @classmethod
    def from_limits(cls, values: dict[str, str]) -> AnnualLeavePolicy:
        """`system_limits` sətirlərindən qurur; olmayan açar defolta düşür.

        Sözlük İMZASI seçilib (port deyil): saf domen modulu `SystemLimits`
        portunu TANIMAMALIDIR (bax modul başlığı) — tətbiq qatı `all_for()`
        nəticəsini ötürür (`LeaveAllowancePolicy.from_limits` ilə eyni naxış).
        """
        return cls(
            base_entitlement_days=_decimal_of(
                values, SystemLimitKey.ANNUAL_LEAVE_BASE_ENTITLEMENT_DAYS
            ),
            seniority_period_years=_int_of(
                values, SystemLimitKey.ANNUAL_LEAVE_SENIORITY_PERIOD_YEARS
            ),
            seniority_bonus_days=_decimal_of(
                values, SystemLimitKey.ANNUAL_LEAVE_SENIORITY_BONUS_DAYS
            ),
            seniority_bonus_max_days=_decimal_of(
                values, SystemLimitKey.ANNUAL_LEAVE_SENIORITY_BONUS_MAX_DAYS
            ),
            carryover_max_days=_decimal_of(values, SystemLimitKey.ANNUAL_LEAVE_CARRYOVER_MAX_DAYS),
            carryover_deadline_month=_int_of(
                values, SystemLimitKey.ANNUAL_LEAVE_CARRYOVER_DEADLINE_MONTH
            ),
            carryover_deadline_day=_int_of(
                values, SystemLimitKey.ANNUAL_LEAVE_CARRYOVER_DEADLINE_DAY
            ),
            accrual_period=AccrualPeriod.from_value(
                _raw(values, SystemLimitKey.ANNUAL_LEAVE_ACCRUAL_PERIOD)
            ),
            accrual_rate_days_per_period=_decimal_of(
                values, SystemLimitKey.ANNUAL_LEAVE_ACCRUAL_RATE_DAYS_PER_PERIOD
            ),
            day_count_mode=LeaveDayCountMode.from_value(
                _raw(values, SystemLimitKey.ANNUAL_LEAVE_DAY_COUNT_MODE)
            ),
        )

    # ------------------------------ hesablama -------------------------------- #

    def seniority_bonus(self, *, hire_date: date | None, as_of: date) -> Decimal:
        """`min(tavan, floor(staj / dövr) × dövr_başına_gün)`.

        `hire_date is None` → SIFIR, sıfır SABİT DEYİL, "məlum deyil"in
        cavabıdır: fərziyyə qurmaq (məs. "deməli bu il işə düşüb") işçinin
        ziyanına və ya xeyrinə uydurma olardı (`tenure_months` ilə eyni qərar).
        """
        if hire_date is None:
            return _ZERO
        completed_years = _completed_years(hire_date, as_of)
        periods = completed_years // self.seniority_period_years
        bonus = self.seniority_bonus_days * Decimal(periods)
        return quantize_days(min(bonus, self.seniority_bonus_max_days))

    def full_entitlement(self, *, hire_date: date | None, as_of: date) -> Decimal:
        """Tam illik haqq = baza + staj əlavəsi (proporsiya TƏTBİQ EDİLMİR)."""
        return quantize_days(
            self.base_entitlement_days + self.seniority_bonus(hire_date=hire_date, as_of=as_of)
        )

    def entitlement_for_year(
        self, *, year: int, hire_date: date | None, as_of: date
    ) -> AnnualLeaveEntitlement:
        """İşçinin `year` ili üçün QAZANDIĞI haqq.

        ──────────────────────────────────────────────────────────────────────
        AYIN ORTASINDA İŞƏ DÜŞƏN İŞÇİ
        ──────────────────────────────────────────────────────────────────────
        Proporsiya GÜN dəqiqliyindədir, AY dəqiqliyində yox: 15 martda işə
        düşən işçi ilin 292/365 hissəsini qazanır, "10 ay" yox. Ay
        yuvarlaqlaşdırması ayın 1-də və 28-də işə düşən iki işçiyə eyni haqqı
        verərdi — bu, real pul fərqidir və mübahisə mövzusudur.

        İL SƏRHƏDİ: `year`-dan ƏVVƏL işə düşən işçi üçün pəncərə 1 yanvarda
        başlayır, yəni keçən ilin heç bir günü bu ilin haqqına qatılmır. Bu,
        `annual_leave_balances`-ın "hər il AYRI sətirdir" qərarının hesablama
        tərəfidir (migrations/037).

        `as_of` GƏLƏCƏK İLİN sorğusunda da işləyir: hələ başlamamış il üçün
        `earned_fraction` sıfırdır (heç bir dövr keçməyib), yəni işçi növbəti
        ilin haqqını qabaqcadan xərcləyə bilmir.
        """
        base = self.base_entitlement_days
        seniority = self.seniority_bonus(hire_date=hire_date, as_of=as_of)
        full = quantize_days(base + seniority)

        year_start = date(year, 1, 1)
        year_end = date(year, 12, 31)
        eligible_start = year_start if hire_date is None else max(year_start, hire_date)
        if eligible_start > year_end:
            # İşçi bu ildən SONRA işə düşüb — haqq yoxdur.
            return AnnualLeaveEntitlement(
                year=year,
                days=_ZERO,
                base_days=base,
                seniority_days=seniority,
                earned_fraction=_ZERO,
            )

        fraction = self._earned_fraction(
            year=year, eligible_start=eligible_start, year_end=year_end, as_of=as_of
        )
        if self.accrual_period.is_front_loaded:
            days = quantize_days(full * fraction)
        else:
            rate = self._rate_per_period(full)
            days = quantize_days(rate * fraction * Decimal(self.accrual_period.periods_per_year))

        return AnnualLeaveEntitlement(
            year=year,
            days=days,
            base_days=base,
            seniority_days=seniority,
            earned_fraction=fraction,
        )

    def _rate_per_period(self, full_entitlement: Decimal) -> Decimal:
        """Dövr başına gün — açıq dəyər, yoxdursa illik haqq ÷ dövr sayı.

        `0` sentineli sənədləşdirilib (`SystemLimitKey` şərhi): defolt halda
        dərəcə baza haqqla HƏMİŞƏ uzlaşır, yəni Root 21-i 24-ə qaldıranda
        aylıq dərəcə də özü 2.00-ə qalxır və iki ədəd bir-birindən sürüşə
        bilmir.
        """
        if self.accrual_rate_days_per_period > 0:
            return self.accrual_rate_days_per_period
        return full_entitlement / Decimal(self.accrual_period.periods_per_year)

    def _earned_fraction(
        self, *, year: int, eligible_start: date, year_end: date, as_of: date
    ) -> Decimal:
        """İlin nə qədər hissəsi QAZANILIB (0–1)."""
        days_in_year = Decimal((year_end - date(year, 1, 1)).days + 1)
        if self.accrual_period.is_front_loaded:
            # Front-loaded: haqq işə qəbul günündən ilin sonuna qədərki
            # pəncərəyə görə verilir — `as_of` təsir ETMİR, çünki haqq
            # qabaqcadan açılır (bax `AccrualPeriod` şərhi).
            eligible_days = Decimal((year_end - eligible_start).days + 1)
            return eligible_days / days_in_year

        cutoff = min(as_of, year_end)
        earned = _ZERO
        for period_start, period_end in _period_bounds(year, self.accrual_period.periods_per_year):
            if period_end > cutoff:
                # Dövr HƏLƏ tamamlanmayıb — toplanan modeldə yarımçıq dövr
                # heç nə qazandırmır (bunun yeri front-loaded modeldir).
                continue
            span_start = max(period_start, eligible_start)
            if span_start > period_end:
                continue
            worked = Decimal((period_end - span_start).days + 1)
            total = Decimal((period_end - period_start).days + 1)
            # İşə qəbul dövrün ORTASINA düşürsə həmin dövr də proporsional
            # sayılır — əks halda ayın 2-də işə düşən işçi bütün ayı itirərdi.
            earned += worked / total
        return earned / Decimal(self.accrual_period.periods_per_year)

    # ------------------------------ köçürmə ---------------------------------- #

    def carry_over(self, *, unused_days: Decimal) -> Decimal:
        """Keçən ilin qalığından köçürülən gün — TAVAN AŞILDIQDA ARTIQ GÜN İTİR.

        İKİ SƏRHƏD, HƏR İKİSİ QƏSDƏN:
          * `min(qalıq, tavan)` — tavandan artığı İTİR. Bu, siyasətin ÖZÜDÜR:
            məhz "istifadə et ya itir" qaydası yığılan öhdəliyin qarşısını
            alır. Artıq günü növbəti ilə "borc" kimi yazmaq balansı mənfiyə
            salardı və `chk_annual_leave_balance_not_negative` DB-də bunu
            onsuz da rədd edərdi.
          * `max(0, ...)` — MƏNFİ qalıq heç vaxt köçürülmür. Nəzəri hal
            (əl ilə düzəliş, tarixi məlumat idxalı) real olsa da, ondan
            doğan mənfi köçürmə növbəti ilin haqqını sükutla azaldardı.
        """
        return quantize_days(max(_ZERO, min(unused_days, self.carryover_max_days)))

    def forfeited_days(self, *, unused_days: Decimal) -> Decimal:
        """Köçürmə tavanını aşdığı üçün İTƏN gün — audit/hesabat üçün.

        İtən gün AYRICA hesablanır ki, il dönümü işi "5 gün köçürüldü"
        deyəndə "və 3 gün itdi" faktı da izdə qalsın; əks halda işçi növbəti
        ildə fərqi görüb izah tapa bilməzdi.
        """
        return quantize_days(max(_ZERO, unused_days - self.carry_over(unused_days=unused_days)))

    def carryover_deadline(self, year: int) -> date:
        """ "İstifadə et ya itir" son tarixi — `year` ilində.

        AYIN UZUNLUĞUNA SIXILIR: Root "hər ayın 31-i" yazsa və ay fevral
        olsa, `date(year, 2, 31)` `ValueError` atardı və il dönümü işi HƏR
        GECƏ çökərdi. Sükutla ayın son gününə sıxmaq düzgün davranışdır —
        HR-ın nəzərdə tutduğu məna onsuz da "ayın sonu"dur.
        """
        last_day = calendar.monthrange(year, self.carryover_deadline_month)[1]
        return date(year, self.carryover_deadline_month, min(self.carryover_deadline_day, last_day))

    def is_carryover_expired(self, *, year: int, as_of: date) -> bool:
        """Köçürülmüş günlərin istifadə pəncərəsi BAĞLANIBMI.

        Son tarix DAXİLDİR: 31 martda hələ istifadə etmək olar, 1 apreldə yox.
        """
        return as_of > self.carryover_deadline(year)


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _period_bounds(year: int, periods_per_year: int) -> list[tuple[date, date]]:
    """Təqvim ilinin dövr sərhədləri (12 → ay, 4 → rüb, 1 → il).

    Sərhədlər TƏQVİMDƏN çıxarılır, sabit gün sayından yox: "30 günlük ay"
    fərziyyəsi fevralı və 31 günlük ayları sürüşdürər və ilin sonunda bir
    neçə gün ya iki dəfə sayılar, ya da heç sayılmazdı.
    """
    if periods_per_year <= 1:
        return [(date(year, 1, 1), date(year, 12, 31))]
    months_per_period = 12 // periods_per_year
    bounds: list[tuple[date, date]] = []
    for index in range(periods_per_year):
        first_month = index * months_per_period + 1
        last_month = first_month + months_per_period - 1
        last_day = calendar.monthrange(year, last_month)[1]
        bounds.append((date(year, first_month, 1), date(year, last_month, last_day)))
    return bounds


def _completed_years(hire_date: date, as_of: date) -> int:
    """TAM tamamlanmış iş ili sayı (ildönümü keçməyibsə sayılmır).

    Sadə `(as_of.year - hire_date.year)` yazsaydıq, 31 dekabr 2025-də işə
    düşən işçi 1 yanvar 2026-da "bir illik staj" qazanardı.
    """
    years = as_of.year - hire_date.year
    if (as_of.month, as_of.day) < (hire_date.month, hire_date.day):
        years -= 1
    return max(0, years)


def _non_negative(value: Decimal) -> Decimal:
    return value if value > 0 else _ZERO


def _clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _raw(values: dict[str, str], key: SystemLimitKey) -> str:
    return values.get(key.value, DEFAULT_LIMITS[key])


def _decimal_of(values: dict[str, str], key: SystemLimitKey) -> Decimal:
    """Sətri `Decimal`-a çevirir; yararsız dəyər defolta düşür.

    İSTİSNA ATILMIR (bax `AccrualPeriod.from_value`): Root panelinə əl ilə
    yazılmış "iyirmi bir" mətni bütün işçilərin balans kartını çökdürməməlidir.
    """
    raw = _raw(values, key)
    try:
        return Decimal(raw.strip().replace(",", "."))
    except (AttributeError, ArithmeticError, ValueError):
        return Decimal(DEFAULT_LIMITS[key])


def _int_of(values: dict[str, str], key: SystemLimitKey) -> int:
    return int(_decimal_of(values, key))


__all__ = [
    "DAY_QUANTUM",
    "AccrualPeriod",
    "AnnualLeaveEntitlement",
    "AnnualLeavePolicy",
    "AnnualLeaveRolloverInput",
    "LeaveDayCountMode",
    "quantize_days",
]
