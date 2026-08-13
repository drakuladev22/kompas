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
    ) -> None:
        self._history = history
        self._suggestions = suggestions
        self._limits = limits
        self._clock = clock

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

        updated = 0
        for weekday, headcounts in sorted(grouped.items()):
            suggestion = StaffingPatternSuggestion(
                tenant_id=tenant_id,
                store_id=store_id,
                weekday=weekday,
                avg_historical_headcount=_round_like_numeric(fmean(headcounts)),
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
