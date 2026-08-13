"""İşdən çıxma riski balı (#21, kompasos11.md Faza 9) — SAF QAYDA MODULU.

──────────────────────────────────────────────────────────────────────────────
BU BAL MƏSLƏHƏTDİR, HÖKM DEYİL
──────────────────────────────────────────────────────────────────────────────
Bura yazılan ədəd bir PROQNOZDUR və səhv ola bilər — insan davranışını
riyaziyyatla dəqiq proqnozlaşdırmaq mümkün deyil. Ona görə bu modul:
  * heç bir cəza/status dəyişikliyi TƏTBİQ ETMİR (nə cərimə yazır, nə icazəni
    məhdudlaşdırır, nə də hər hansı HR prosesini avtomatik başladır);
  * yalnız HR-ı "bu işçiyə diqqət yetir" siqnalı ilə məlumatlandırır
    (bax `application.use_cases.attrition_risk.AttritionRiskUseCase`);
  * `factors_json`-u HƏR ZAMAN doldurur — "78 baldır" cümləsi tək başına
    HEÇ bir HR qərarını (söhbət, əvəzedici axtarışı, işə son vermə) əsaslandıra
    bilməz, əsaslandıran "78-in 40-ı son 3 ayda cərimə artımından, 20-si
    davamiyyət pozuntusundan..." izahıdır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SAF DOMEN MODULU — I/O YOXDUR
──────────────────────────────────────────────────────────────────────────────
`labor_rules.py` (#14) ilə EYNİ bölgü: bu fayl repository/Clock/SystemLimits
TANIMIR — ona artıq YIĞILMIŞ `AttritionSignalInput` və `AttritionWeights`
verilir. Məlumat yığımı (SQL aqreqasiyası, `system_limits` oxuma) tətbiq
qatındadır (`application.use_cases.attrition_risk.AttritionRiskUseCase`) —
qayda testləri bazasız və deterministikdir.

──────────────────────────────────────────────────────────────────────────────
DÖRD SİQNAL — NİYƏ MƏHZ BUNLAR (kompasos11.md #21: "mövcud cərimə/davamiyyət/
staj datasından")
──────────────────────────────────────────────────────────────────────────────
  1. FINE_TREND — son `window_months` ayı iki yarıya bölüb sonuncu yarımdakı
     cərimə sayının əvvəlkindən NƏ QƏDƏR ARTDIĞINI ölçür (mütləq say yox,
     ARTIM). "Həmişə 2 cərimə alan işçi" ilə "son ayda birdən 5-ə qalxan
     işçi" fərqli risk səviyyəsindədir — mütləq say bunu göstərmir, artım
     göstərir. Azalma/sabit qalma HEÇ bal doğurmur (`max(0, ...)`).
  2. ATTENDANCE_VIOLATIONS — eyni pəncərədə icazəsiz davamiyyət pozuntusu
     sayı (`EmployeeAttendanceFacts.unauthorized_absences` ilə EYNİ mənbə,
     bax `infrastructure.persistence.report_repositories`).
  3. NEW_HIRE_TENURE — staj `new_hire_threshold_months`-dan azdırsa sabit bal.
     Sənaye statistikası: ilk aylarda işdən çıxma ehtimalı ən yüksəkdir
     ("onboarding riski").
  4. LEAVE_USAGE — cari ayın icazə istifadəsi aylıq limitə (mövcud
     `SystemLimitKey.MONTHLY_LEAVE_MINUTES_LIMIT`) nə qədər yaxındır. Tez-tez
     limitə dirənən işçi ya yorğunluqdan, ya da fəal iş axtarışından (müsahibə
     üçün icazə) əlamət verə bilər.

"GECİKMƏ TEZLİYİ" AYRICA SİQNAL DEYİL — NİYƏ: gecikmə artıq `AUTO_DELAY`
mənbəli cərimələr vasitəsilə FINE_TREND-ə daxildir (bax `DelayFinePolicy`,
`policies.py`). Onu ikinci dəfə saymaq eyni hadisəni İKİ dəfə çəkiləndirmək
olardı və Root iki fərqli açarı tənzimləyəndə (FINE_TREND vs LATE_FREQUENCY)
onların HANSI HADİSƏNİ ölçdüyü qarışardı.

──────────────────────────────────────────────────────────────────────────────
HƏR SİQNAL HƏMİŞƏ YAZILIR — sıfır bal olsa BELƏ
──────────────────────────────────────────────────────────────────────────────
`calculate_attrition_score` dörd amilin HAMISINI `factors`-a yazır, töhfəsi
sıfır olsa belə (`points=0`). Yalnız QEYRİ-SIFIR amilləri yazmaq "niyə bu işçi
0 baldır?" sualını cavabsız qoyardı VƏ `attrition_risk_scores.factors_json
<> '{}'` CHECK-ini (migrations/020) balı HƏQİQƏTƏN sıfır olan (yeni işə düşən,
sıfır siqnallı) işçidə pozardı.

──────────────────────────────────────────────────────────────────────────────
TAVAN DÜZƏLİŞİ (`SCORE_CAP`) — NİYƏ AYRICA İZAH AMİLİDİR
──────────────────────────────────────────────────────────────────────────────
Dörd amilin cəmi 100-ü keçə bilər (Root çəkiləri sərbəst təyin edir; bal
sütunu isə 0–100 `CHECK`-i daşıyır, migrations/020). Kəsilmə SƏSSİZCƏ
aparılmır: fərq `SCORE_CAP` amili kimi əlavə olunur ki, `sum(factor.points)
== score` İNVARİANTI HƏR HALDA doğru qalsın — əks halda "amillərin cəmi yekun
baldan fərqlənir" HR-ı çaşdırardı.

──────────────────────────────────────────────────────────────────────────────
RİSK BANDI SAXLANILMIR (migrations/020 qərarının domendəki əksi)
──────────────────────────────────────────────────────────────────────────────
`AttritionRiskScore` (DB sətrinin domen görünüşü) `is_high_risk` SAHƏSİ
DAŞIMIR — bant HƏMİŞƏ CARI hədlə hesablama/bildiriş ANINDA müəyyənləşir
(`AttritionScoreResult.is_high_risk`, YALNIZ TƏZƏ hesablamanın ömrü qədər
mövcuddur). Bant sütunda dondurulsaydı, Root həddi dəyişəndə köhnə sətirlər
köhnə təsnifatla qalardı və eyni ekranda iki fərqli qayda ilə hesablanmış
"YÜKSƏK" yan-yana görünərdi.

──────────────────────────────────────────────────────────────────────────────
HARDCODE ƏDƏD YOXDUR
──────────────────────────────────────────────────────────────────────────────
Yeddi parametrin (dörd çəki + pəncərə + yeni-işçi həddi + yüksək-risk həddi)
hamısı ROOT parametridir (`SystemLimitKey.ATTRITION_*`, seed: migrations/030).
`AttritionWeights.defaults()` yalnız DB sətri hələ seed edilməyibsə işə düşən
FALLBACK-dır — bu faylda ədədi sabit YOXDUR.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Final

from src.domain.entities.base import DomainRuleError
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.scheduling import require_aware

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.domain.value_objects.identifiers import EmployeeId, TenantId

#: Balın sxem sərhədi (migrations/020 `CHECK (score >= 0 AND score <= 100)`
#: güzgüsü) — ROOT parametri DEYİL, ölçü vahididir.
MIN_SCORE: Final = 0.0
MAX_SCORE: Final = 100.0

#: Bir təqvim ayının orta gün sayı — staj hesabı üçün kifayət qədər dəqiq
#: təxminidir (dəqiq təqvim ay riyaziyyatı bu risk balı üçün lazımsız
#: mürəkkəblikdir, `_format_duration` kimi digər yerlərdə də təqribi hesab
#: qəbul edilib).
_DAYS_PER_MONTH: Final = 30.0


class AttritionSignal(str, Enum):
    """`factors_json` açarları — `str, Enum` (CLAUDE.md §4: `.value` JSON-a düşür,
    `StrEnum`-a keçid saxlanmış keçmiş sətirləri sükutla dəyişərdi)."""

    FINE_TREND = "FINE_TREND"
    ATTENDANCE_VIOLATIONS = "ATTENDANCE_VIOLATIONS"
    NEW_HIRE_TENURE = "NEW_HIRE_TENURE"
    LEAVE_USAGE = "LEAVE_USAGE"
    #: Yalnız xam cəm 0–100 xaricinə çıxanda əlavə olunur (bax modul başlığı).
    SCORE_CAP = "SCORE_CAP"


@dataclass(frozen=True)
class AttritionWeights:
    """#21-in yeddi ROOT parametri, bir dəfə oxunmuş halda.

    Mənfi dəyər 0-a yuvarlaqlaşdırılır: Root ekranı `min_value` ilə qoruyur,
    lakin ekranı yan keçən skript mənfi yaza bilər və hesablama bu səbəbdən
    çökməməlidir (`LaborLimits.__post_init__` ilə eyni fəlsəfə).
    """

    fine_trend_weight: int
    attendance_violation_weight: int
    new_hire_risk_points: int
    new_hire_threshold_months: int
    leave_usage_weight: int
    window_months: int
    high_risk_threshold: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "fine_trend_weight", max(0, self.fine_trend_weight))
        object.__setattr__(
            self, "attendance_violation_weight", max(0, self.attendance_violation_weight)
        )
        object.__setattr__(self, "new_hire_risk_points", max(0, self.new_hire_risk_points))
        object.__setattr__(
            self, "new_hire_threshold_months", max(0, self.new_hire_threshold_months)
        )
        object.__setattr__(self, "leave_usage_weight", max(0, self.leave_usage_weight))
        object.__setattr__(self, "window_months", max(1, self.window_months))
        object.__setattr__(self, "high_risk_threshold", max(0, self.high_risk_threshold))

    @classmethod
    def defaults(cls) -> AttritionWeights:
        """`DEFAULT_LIMITS` dəyərləri — YALNIZ fallback (bax modul başlığı).

        HƏQİQİ MƏNBƏ `system_limits`-dir (migrations/030 seed edir); bu metod
        limit portu olmayan çağırış yollarında (məs. saf qayda testi) işlədilir.
        """
        return cls(
            fine_trend_weight=int(DEFAULT_LIMITS[SystemLimitKey.ATTRITION_FINE_TREND_WEIGHT]),
            attendance_violation_weight=int(
                DEFAULT_LIMITS[SystemLimitKey.ATTRITION_ATTENDANCE_VIOLATION_WEIGHT]
            ),
            new_hire_risk_points=int(DEFAULT_LIMITS[SystemLimitKey.ATTRITION_NEW_HIRE_RISK_POINTS]),
            new_hire_threshold_months=int(
                DEFAULT_LIMITS[SystemLimitKey.ATTRITION_NEW_HIRE_THRESHOLD_MONTHS]
            ),
            leave_usage_weight=int(DEFAULT_LIMITS[SystemLimitKey.ATTRITION_LEAVE_USAGE_WEIGHT]),
            window_months=int(DEFAULT_LIMITS[SystemLimitKey.ATTRITION_WINDOW_MONTHS]),
            high_risk_threshold=int(DEFAULT_LIMITS[SystemLimitKey.ATTRITION_HIGH_RISK_THRESHOLD]),
        )


@dataclass(frozen=True)
class AttritionSignalInput:
    """Bir işçi üçün artıq YIĞILMIŞ xam siqnallar (SQL aqreqasiyasından sonra)."""

    #: Pəncərənin SONUNCU yarısındakı cərimə sayı.
    fine_count_recent_half: int
    #: Pəncərənin ƏVVƏLKİ yarısındakı cərimə sayı.
    fine_count_prior_half: int
    unauthorized_absences: int
    #: `None` = işə qəbul tarixi məlum deyil — staj siqnalı SUSUR (fərziyyə
    #: qurulmur), `labor_rules.py`-dəki "iş rejimində sabit saat yoxdursa
    #: qayda susur" fəlsəfəsi ilə eynidir.
    tenure_months: float | None
    #: Artıq nisbətə çevrilmiş (0–1) — 1.0 = aylıq icazə limitinin tam
    #: istifadəsi. Mənfi/1-dən böyük dəyər `calculate_attrition_score`-da
    #: kəsilir.
    leave_usage_ratio: float


@dataclass(frozen=True)
class AttritionFactor:
    """Balın bir amili — `factors_json`-un bir açarı."""

    signal: AttritionSignal
    raw_value: float | None
    weight: float
    points: float
    explanation_az: str


@dataclass(frozen=True)
class AttritionScoreResult:
    """Bir hesablamanın TƏZƏ nəticəsi — DB-yə yazılmazdan ƏVVƏLKİ görünüş.

    `AttritionRiskScore`-dan (aşağı) FƏRQLİ olaraq bant məlumatını
    (`is_high_risk`) daşıyır — çünki bu obyekt yalnız HESABLAMA anında,
    keçici olaraq mövcuddur; DB-yə YAZILMIR (bax modul başlığı "Risk bandı
    saxlanılmır").
    """

    score: float
    factors: tuple[AttritionFactor, ...]
    high_risk_threshold: int

    @property
    def is_high_risk(self) -> bool:
        return self.score >= self.high_risk_threshold

    def factors_payload(self) -> dict[str, dict[str, object]]:
        """`factors_json` sütunu üçün JSON-a hazır görünüş (Azərbaycanca açarlar,
        CLAUDE.md bölmə 9 — log/JSON açarları Azərbaycan dilindədir)."""
        return {
            factor.signal.value: {
                "xam_deyer": factor.raw_value,
                "cəki": factor.weight,
                "bal": round(factor.points, 2),
                "izah": factor.explanation_az,
            }
            for factor in self.factors
        }


def tenure_months(hire_date: date | None, as_of: date) -> float | None:
    """İşə qəbul tarixindən `as_of`-a qədər staj (ay, təxmini).

    `hire_date is None` → `None` (naməlum) qaytarır — çağıran tərəf bunu
    "staj siqnalı susur" kimi oxumalıdır, "0 aylıq staj" (ən yüksək risk)
    KİMİ YOX. `hire_date` gələcəkdədirsə (məlumat səhvi) mənfi staj sıfıra
    kəsilir — mənfi ədəd "yeni işçi" testini yanlış işlədərdi.
    """
    if hire_date is None:
        return None
    days = (as_of - hire_date).days
    return max(0.0, days / _DAYS_PER_MONTH)


def calculate_attrition_score(
    signals: AttritionSignalInput, weights: AttritionWeights
) -> AttritionScoreResult:
    """Dörd siqnalı çəkiləndirib 0–100 bal və tam izahını qaytarır.

    Boş `factors` HEÇ VAXT qayıtmır (bax modul başlığı) — sıfır siqnallı işçi
    belə dörd amili sıfır balla göstərir.
    """
    factors: list[AttritionFactor] = []

    trend = max(0, signals.fine_count_recent_half - signals.fine_count_prior_half)
    factors.append(
        AttritionFactor(
            signal=AttritionSignal.FINE_TREND,
            raw_value=float(trend),
            weight=float(weights.fine_trend_weight),
            points=float(trend * weights.fine_trend_weight),
            explanation_az=(
                f"Son {weights.window_months} ayın yarımlarında cərimə sayı "
                f"{signals.fine_count_prior_half} → {signals.fine_count_recent_half} "
                f"(artım: {trend})."
            ),
        )
    )

    factors.append(
        AttritionFactor(
            signal=AttritionSignal.ATTENDANCE_VIOLATIONS,
            raw_value=float(signals.unauthorized_absences),
            weight=float(weights.attendance_violation_weight),
            points=float(signals.unauthorized_absences * weights.attendance_violation_weight),
            explanation_az=(
                f"Son {weights.window_months} ayda {signals.unauthorized_absences} icazəsiz "
                "davamiyyət pozuntusu qeydə alınıb."
            ),
        )
    )

    is_new_hire = (
        signals.tenure_months is not None
        and weights.new_hire_threshold_months > 0
        and signals.tenure_months < weights.new_hire_threshold_months
    )
    if signals.tenure_months is None:
        tenure_explanation = "İşə qəbul tarixi məlum deyil — staj siqnalı hesablanmadı."
    elif is_new_hire:
        tenure_explanation = (
            f"Staj {signals.tenure_months:.1f} ay — {weights.new_hire_threshold_months} aylıq "
            "yeni-işçi həddindən azdır (onboarding riski)."
        )
    else:
        tenure_explanation = (
            f"Staj {signals.tenure_months:.1f} ay — {weights.new_hire_threshold_months} aylıq "
            "yeni-işçi həddini keçib."
        )
    factors.append(
        AttritionFactor(
            signal=AttritionSignal.NEW_HIRE_TENURE,
            raw_value=signals.tenure_months,
            weight=float(weights.new_hire_risk_points),
            points=float(weights.new_hire_risk_points) if is_new_hire else 0.0,
            explanation_az=tenure_explanation,
        )
    )

    leave_ratio = max(0.0, min(1.0, signals.leave_usage_ratio))
    factors.append(
        AttritionFactor(
            signal=AttritionSignal.LEAVE_USAGE,
            raw_value=round(leave_ratio, 4),
            weight=float(weights.leave_usage_weight),
            points=leave_ratio * weights.leave_usage_weight,
            explanation_az=(f"Cari ay icazə istifadəsi aylıq limitin {leave_ratio * 100:.0f}%-i."),
        )
    )

    raw_total = sum(factor.points for factor in factors)
    score = max(MIN_SCORE, min(MAX_SCORE, raw_total))
    if score != raw_total:
        factors.append(
            AttritionFactor(
                signal=AttritionSignal.SCORE_CAP,
                raw_value=round(raw_total, 2),
                weight=0.0,
                points=score - raw_total,
                explanation_az=(
                    f"Xam cəm {raw_total:.2f} bal idi, şkala 0–100 daxilinə "
                    f"{'endirildi' if raw_total > MAX_SCORE else 'qaldırıldı'}."
                ),
            )
        )

    return AttritionScoreResult(
        score=round(score, 2),
        factors=tuple(factors),
        high_risk_threshold=weights.high_risk_threshold,
    )


@dataclass(frozen=True)
class AttritionRiskScore:
    """`attrition_risk_scores` sətrinin domen görünüşü (#21).

    Yoxlamalar DB `CHECK`-lərinin GÜZGÜSÜDÜR (`behavior_signals.BehaviorBaseline`
    ilə eyni prinsip): repo-dan yararsız sətir bərpa edilsə, xəta İSTİFADƏ
    ANINDA yox, OXU ANINDA üzə çıxsın.

    `is_high_risk` SAHƏSİ QƏSDƏN YOXDUR — bax modul başlığı "Risk bandı
    saxlanılmır". Ayrıca ID tipi YOXDUR — `BehaviorBaseline` başlığındakı EYNİ
    əsaslandırma: sətir `(tenant_id, employee_id, score_date)` üçlüyü ilə TAM
    eyniləşdirilir (DB `UNIQUE`, migrations/020) və `AttritionRiskScoreId`
    kimi ayrıca `NewType` istifadə olunmayacaq soysummuş özəllik olardı.
    """

    tenant_id: TenantId
    employee_id: EmployeeId
    score: float
    factors: Mapping[str, Mapping[str, object]]
    score_date: date
    calculated_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.calculated_at, field="calculated_at")
        if not (MIN_SCORE <= self.score <= MAX_SCORE):
            raise DomainRuleError(
                "Risk balı 0–100 aralığında olmalıdır", context={"score": self.score}
            )
        if not self.factors:
            raise DomainRuleError(
                "factors_json boş ola bilməz — bal həmişə izah edilməlidir",
                context={"employee_id": str(self.employee_id)},
            )


__all__ = [
    "MAX_SCORE",
    "MIN_SCORE",
    "AttritionFactor",
    "AttritionRiskScore",
    "AttritionScoreResult",
    "AttritionSignal",
    "AttritionSignalInput",
    "AttritionWeights",
    "calculate_attrition_score",
    "tenure_months",
]
