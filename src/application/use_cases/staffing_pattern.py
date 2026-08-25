"""Tarixi-nümunə əsaslı kadr təklifi (#13, kompasos11.md Faza 6).

──────────────────────────────────────────────────────────────────────────────
1C-YƏ TOXUNMUR — VƏ BU, TƏSADÜF DEYİL
──────────────────────────────────────────────────────────────────────────────
kompasos11.md struktur qərar D təklifin əvvəlki (1C satış həcminə əsaslanan)
dizaynını TAM ÇIXARIB. Bu modulda `SalesDataConnector`, `OneCSaleRecord` və
`erp_*` adlı heç nə YOXDUR və olmamalıdır: yeganə mənbə KompasOS-un ÖZ
davamiyyət tarixçəsidir (`StaffingHistoryProvider` portu →
`attendance_records`).

Nəticə etibarilə bu, TƏLƏB PROQNOZU deyil: "keçən 8 həftənin çərşənbələrində
orta hesabla 2.6 nəfər işləyib" cümləsi gələcək haqqında heç nə vəd etmir.
Ona görə:

    * heç nə BLOKLAMIR,
    * heç nəyi AVTOMATİK TƏYİN ETMİR (`ShiftPlanningUseCase`-ə çağırış YOXDUR),
    * ekranda "zəif siqnal" olduğu AÇIQ yazılır (bax `ShiftPlanningScreen.
      set_staffing_pattern` mətnləri).

──────────────────────────────────────────────────────────────────────────────
NİYƏ AUDİT YAZISI YOXDUR
──────────────────────────────────────────────────────────────────────────────
`audit_logs` İNSAN QƏRARLARININ izidir (kim nəyi dəyişdi). Burada isə heç bir
qərar verilmir və heç bir iş obyekti dəyişmir: sətir tam törəmə məlumatdır və
`attendance_records`-dan istənilən an yenidən hesablanır (migrations/019).
Eyni əsaslandırma `BehaviorBaselineUseCase.recalculate_all()`-dadır — o da
audit yazmır, yalnız jurnal sətri qoyur. Hesablamanı KİMİN işə saldığı sualı
planlayıcının öz jurnalındadır (`docs/scheduler_setup.md`).

──────────────────────────────────────────────────────────────────────────────
KAMPANİYA ÇƏKİSİ — İKİ RƏQƏM, BİR PƏNCƏRƏ (v2backlog.md Faza 6.4)
──────────────────────────────────────────────────────────────────────────────
Kampaniya (endirim aksiyası) günlərində mağaza daha çox işçi ilə işləyir. Adi
orta həmin günləri qalan günlərlə BƏRABƏR sayır, yəni növbəti kampaniyaya
hazırlıq üçün sistematik olaraq AZ göstərir.

Ona görə pəncərə İKİ dəfə oxunur: `avg_historical_headcount` toxunulmadan
qalır (mənası "faktiki orta"dır və dəyişməməlidir), `campaign_adjusted_
headcount` isə kampaniya günlərini `STAFFING_CAMPAIGN_WEIGHT_MULTIPLIER`
çarpanı ilə ağırlaşdıran ÇƏKİLİ ortadır.

Kampaniya günü olmayan pəncərədə ikinci rəqəm `None` qalır — çünki "çəkiləcək
bir şey yoxdur" ilə "kampaniyada sıfır işçi lazımdır" bir-birindən fərqli
cümlələrdir və ekran onları eyni göstərməməlidir.

`campaigns` portu İSTƏYƏ BAĞLIDIR (`None` = kampaniya oxunmur): planlayıcı və
testlərin mövcud çağırışları dəyişmədən işləməyə davam edir, port bağlanan
kimi isə ikinci rəqəm CANLI olur (`root_limits.py` başlığındakı eyni naxış).

──────────────────────────────────────────────────────────────────────────────
NİYƏ SAGA LAZIM DEYİL
──────────────────────────────────────────────────────────────────────────────
CLAUDE.md §3: Saga ÇOX-AQREQATLI əməliyyat üçündür. Burada tək aqreqat var
(`staffing_pattern_suggestions`), nə cərimə, nə status keçidi, nə bildiriş —
uğursuzluqda kompensasiya ediləcək ikinci yazı yoxdur, sadə rollback kifayətdir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import fmean
from typing import TYPE_CHECKING, Final

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.staffing_signals import StaffingPatternSuggestion
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from src.application.use_cases.campaign_periods import CampaignPeriodRepository
    from src.domain.interfaces.ports import (
        Clock,
        StaffingHistoryProvider,
        StaffingPatternRepository,
        SystemLimits,
    )
    from src.domain.value_objects.identifiers import StoreId, TenantId
    from src.domain.value_objects.staffing_signals import StoreDayHeadcount

_log = get_logger(__name__)

#: Fallback dəyər — bax `policies.py`-dakı `STAFFING_PATTERN_BASED_ON_WEEKS`
#: şərhi. HƏQİQİ MƏNBƏ `system_limits`-dir (migrations/025 seed edir); bu
#: sabit YALNIZ sətir hələ seed edilməyibsə işə düşür.
_FALLBACK_BASED_ON_WEEKS: Final = int(
    DEFAULT_LIMITS[SystemLimitKey.STAFFING_PATTERN_BASED_ON_WEEKS]
)

#: Kampaniya çarpanının fallback-ı — eyni qayda (həqiqi mənbə `system_limits`,
#: seed: migrations/108).
_FALLBACK_CAMPAIGN_MULTIPLIER: Final = float(
    DEFAULT_LIMITS[SystemLimitKey.STAFFING_CAMPAIGN_WEIGHT_MULTIPLIER]
)

#: Çarpanın neytral elementi — «çəki söndürülüb» (bax `APP_LIMIT_BOUNDS`).
_NEUTRAL_MULTIPLIER: Final = 1.0

#: Bir həftədəki gün sayı — təqvim faktı, biznes limiti DEYİL.
_DAYS_PER_WEEK: Final = 7

#: `staffing_pattern_suggestions.avg_historical_headcount` `NUMERIC(5, 2)`-dir.
_HEADCOUNT_QUANTUM: Final = Decimal("0.01")


@dataclass(frozen=True)
class StaffingPatternReport:
    """Bir mağaza üçün yenidən-hesablamanın yekunu (log/monitorinq sətri)."""

    tenant_id: TenantId
    store_id: StoreId
    based_on_weeks: int
    since: date
    until: date
    weekdays_updated: int = 0
    observed_days: int = 0


class StaffingPatternUseCase:
    """ "Bu mağaza bu həftə günündə orta hesabla neçə işçi ilə işləyib?"

    Metodlar səlahiyyət YOXLAMIR və bu, qəsdəndir: `recalculate_for_store()`
    aktoru olmayan planlaşdırılmış işdir, `suggestions_for()` isə Shift Matrix
    ekranının məsləhət kartıdır — matrisin öz görünmə scopinqi
    (`ShiftPlanningUseCase.view_matrix`) onsuz da kimin nəyi gördüyünü təyin
    edir. Buraya ikinci, fərqli bir qapı qoymaq iki yerdə saxlanan icazə
    məntiqi yaradardı.
    """

    def __init__(
        self,
        *,
        history: StaffingHistoryProvider,
        suggestions: StaffingPatternRepository,
        limits: SystemLimits,
        clock: Clock,
        campaigns: CampaignPeriodRepository | None = None,
    ) -> None:
        # `campaigns` İSTƏYƏ BAĞLIDIR — bax modul başlığı. `None` olanda
        # çəkili rəqəm hesablanmır (sətir `NULL` qalır), adi orta isə
        # ƏVVƏLKİ KİMİ yazılır: köhnə çağırışların davranışı DƏYİŞMİR.
        self._history = history
        self._suggestions = suggestions
        self._limits = limits
        self._clock = clock
        self._campaigns = campaigns

    # ------------------------------ hesablama -------------------------------- #

    def recalculate_for_store(
        self, tenant_id: TenantId, *, store_id: StoreId, now: datetime | None = None
    ) -> StaffingPatternReport:
        """Son N həftənin davamiyyətindən həftə-günü ortalarını yazır.

        PƏNCƏRƏ DÜNƏNLƏ BİTİR: bugünkü iş günü hələ bitməyib və yarımçıq gün
        ortanı süni şəkildə aşağı çəkərdi (səhər 10:00-da hesablansa, günün
        yalnız bir hissəsi görünür). Eyni səbəb `BehaviorBaselineUseCase`-də
        də var.

        MÜŞAHİDƏ OLMAYAN GÜN ORTAYA SIFIR KİMİ DAXİL EDİLMİR: mağazanın bağlı
        olduğu bazar günü "0 işçi lazımdır" demək deyil, sadəcə məlumat
        yoxdur. Sıfırla doldursaydıq, təklif bağlı günlərdə süni aşağı ədəd
        göstərər və admin onu "işçi azaldın" siqnalı kimi oxuya bilərdi.
        """
        as_of = now or self._clock.now()
        based_on_weeks = max(
            1,
            self._limits.get_int(
                tenant_id,
                SystemLimitKey.STAFFING_PATTERN_BASED_ON_WEEKS.value,
                _FALLBACK_BASED_ON_WEEKS,
            ),
        )
        until = as_of.date() - timedelta(days=1)
        since = until - timedelta(days=based_on_weeks * _DAYS_PER_WEEK - 1)

        observations = self._history.headcount_by_day(
            tenant_id, store_id=store_id, since=since, until=until
        )
        grouped = _group_by_iso_weekday(observations)
        campaign_dates = self._campaign_dates(tenant_id, since=since, until=until)
        multiplier = self._campaign_multiplier(tenant_id)

        updated = 0
        for weekday, headcounts in sorted(grouped.items()):
            suggestion = StaffingPatternSuggestion(
                tenant_id=tenant_id,
                store_id=store_id,
                weekday=weekday,
                avg_historical_headcount=_round_like_numeric(fmean(headcounts)),
                campaign_adjusted_headcount=_campaign_weighted_mean(
                    [
                        observation
                        for observation in observations
                        if observation.work_date.isoweekday() == weekday
                    ],
                    campaign_dates=campaign_dates,
                    multiplier=multiplier,
                ),
                based_on_weeks=based_on_weeks,
                calculated_at=as_of,
            )
            self._suggestions.save(suggestion)
            updated += 1

        report = StaffingPatternReport(
            tenant_id=tenant_id,
            store_id=store_id,
            based_on_weeks=based_on_weeks,
            since=since,
            until=until,
            weekdays_updated=updated,
            observed_days=len(observations),
        )
        _log.info(
            "STAFFING_PATTERN_RECALCULATED",
            extra={
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "pencere_hefte": based_on_weeks,
                "yenilenen_hefte_gunu": updated,
                "musahide_gun": len(observations),
            },
        )
        return report

    # --------------------------- kampaniya çəkisi ---------------------------- #

    def _campaign_dates(self, tenant_id: TenantId, *, since: date, until: date) -> frozenset[date]:
        """Pəncərəyə düşən AKTİV kampaniya günləri.

        DEAKTİV DÖVRLƏR SAYILMIR (`include_inactive=False`): Root bir dövrü
        söndürəndə onu "bu tarixlər səhv qeyd olunub" mənasında söndürür —
        səhv tarixi çəkidə saxlamaq söndürməni mənasız edərdi.

        Aralıq PƏNCƏRƏ İLƏ KƏSİŞDİRİLİR: kampaniya pəncərədən əvvəl başlayıb
        sonra bitə bilər, o zaman yalnız ortadakı günlər çəkiyə düşməlidir.

        Port yoxdursa BOŞ dəst qayıdır — çəki sükutla söndürülür (bax modul
        başlığı), istisna atılmır: bu, planlaşdırılmış işdir və kampaniya
        oxuna bilmədiyi üçün BÜTÜN təklifin yazılmaması daha pis nəticədir.
        """
        if self._campaigns is None:
            return frozenset()
        dates: set[date] = set()
        for period in self._campaigns.list_periods(tenant_id, include_inactive=False):
            first = max(period.start_date, since)
            last = min(period.end_date, until)
            current = first
            while current <= last:
                dates.add(current)
                current += timedelta(days=1)
        return frozenset(dates)

    def _campaign_multiplier(self, tenant_id: TenantId) -> float:
        """ROOT çarpanı — aralıqdan kənar dəyər NEYTRALA sıxılır.

        `SystemLimits` portu `get_int`/`get_str` səviyyəsindədir və bu dəyər
        ONLUQdur (1.5), ona görə mətn kimi oxunub çevrilir. Yararsız mətn
        (Root sətri əl ilə pozubsa) fallback-a qayıdır — çəkinin oxunmaması
        HESABLAMANI DAYANDIRMAMALIDIR.
        """
        raw = self._limits.get_str(
            tenant_id,
            SystemLimitKey.STAFFING_CAMPAIGN_WEIGHT_MULTIPLIER.value,
            str(_FALLBACK_CAMPAIGN_MULTIPLIER),
        )
        try:
            value = float(raw)
        except (TypeError, ValueError):
            _log.warning(
                "STAFFING_CAMPAIGN_MULTIPLIER_INVALID",
                extra={"tenant_id": str(tenant_id), "raw_value": raw},
            )
            return _FALLBACK_CAMPAIGN_MULTIPLIER
        # Aşağı hüdud `APP_LIMIT_BOUNDS` ilə eynidir; burada TƏKRAR yoxlanılır,
        # çünki bu use case `limit_decimal()` yolundan keçmir (port birbaşadır).
        return max(_NEUTRAL_MULTIPLIER, min(value, 5.0))

    # -------------------------------- oxu ------------------------------------ #

    def suggestions_for(
        self, tenant_id: TenantId, *, store_id: StoreId
    ) -> list[StaffingPatternSuggestion]:
        """Ekranın oxuduğu siyahı — həftə gününə görə sıralı (B.e → Bazar).

        Sıralama BURADA edilir, ekranda yox: eyni siyahı maket və canlı yolda
        eyni ardıcıllıqla görünməlidir, əks halda iki yol arasındakı fərq
        yalnız gözlə müqayisədə üzə çıxardı.
        """
        return sorted(
            self._suggestions.list_for_store(tenant_id, store_id),
            key=lambda suggestion: suggestion.weekday,
        )


def _campaign_weighted_mean(
    observations: list[StoreDayHeadcount],
    *,
    campaign_dates: frozenset[date],
    multiplier: float,
) -> float | None:
    """Kampaniya günləri ağırlaşdırılmış orta — kampaniya yoxdursa `None`.

    `None` ÜÇ HALDA qayıdır və üçü də eyni mənadadır: "bu pəncərədə çəkiləcək
    kampaniya günü yoxdur" — kampaniya siyahısı boşdur, kampaniya günləri bu
    HƏFTƏ GÜNÜNƏ düşmür, yaxud çarpan neytraldır (Root çəkini söndürüb).
    Sonuncu qəsdlidir: çarpan 1.0 olanda çəkili orta adi ortanın eynisi olardı
    və ekranda iki eyni rəqəm "çəki işləmir" təəssüratı yaradardı.

    Düstur adi çəkili ortadır — Σ(w·x)/Σw. Sadə "kampaniya günlərini iki dəfə
    say" yanaşması rədd edildi: o, yalnız TAM ədəd çarpanla işləyir, halbuki
    1.5 kimi kəsr dəyər məhz burada ən faydalıdır.
    """
    if multiplier <= _NEUTRAL_MULTIPLIER or not campaign_dates:
        return None
    weighted_sum = 0.0
    weight_total = 0.0
    campaign_days = 0
    for observation in observations:
        weight = multiplier if observation.work_date in campaign_dates else 1.0
        if weight != 1.0:
            campaign_days += 1
        weighted_sum += weight * observation.headcount
        weight_total += weight
    if campaign_days == 0 or weight_total == 0:
        return None
    return _round_like_numeric(weighted_sum / weight_total)


def _round_like_numeric(value: float) -> float:
    """Ortanı iki onluğa yuvarlaqlaşdırır — PostgreSQL `NUMERIC` KİMİ.

    NİYƏ DAXİLİ `round()` DEYİL: Python "banker" yuvarlaqlaşdırması edir və
    2.625 → 2.62 verir; PostgreSQL `NUMERIC(5, 2)` isə yarımdan yuxarı
    yuvarlaqlaşdırır və 2.63 saxlayır. Tətbiq öz variantını yazsaydı, EYNİ
    məlumat kod tərəfində 2.62, bazada isə 2.63 görünərdi — və hansının
    doğru olduğu sualı yalnız hesabat müqayisəsində üzə çıxardı.
    migrations/019 sütun şərhindəki nümunə (2.63) bazanın davranışıdır, ona
    görə tətbiq ona uyğunlaşır, əksinə yox.
    """
    return float(Decimal(str(value)).quantize(_HEADCOUNT_QUANTUM, rounding=ROUND_HALF_UP))


def _group_by_iso_weekday(observations: list[StoreDayHeadcount]) -> dict[int, list[int]]:
    """Günləri ISO həftə gününə görə qruplaşdırır (1 = Bazar ertəsi).

    `isoweekday()` işlədilir, `weekday()` YOX — migrations/019 sütun şərhinin
    açıq tələbi (SQL tərəfi `EXTRACT(ISODOW)`); iki nömrələməni qarışdırmaq
    klassik "bir gün sürüşmə" qüsurudur.
    """
    grouped: dict[int, list[int]] = {}
    for observation in observations:
        grouped.setdefault(observation.work_date.isoweekday(), []).append(observation.headcount)
    return grouped


__all__ = [
    "StaffingPatternReport",
    "StaffingPatternUseCase",
]
