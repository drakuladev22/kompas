"""İki-nəfərlik fırıldaqçılıq aşkarlaması — `v2backlog.md` Faza 7.

    "Mövcud Exception Engine-ə YENİ bir qayda-mənbəyi: iki işçinin
     davranış-nümunələri arasında ROOT PARAMETRİ: korrelyasiya-həddi aşan
     uyğunluq (məs. həmişə eyni növbədə, bir-birinin qayıbını daim «örtmə»)
     aşkarlananda, Exception Engine-ə «davranış-cütü» tipli qeyd yazılır,
     HR_Admin-ə bildiriş."

──────────────────────────────────────────────────────────────────────────────
NAXIŞ — BehaviorAnomalyRule İLƏ EYNİ QAYDA MÜHƏRRİKİ
──────────────────────────────────────────────────────────────────────────────
Bu da `ExceptionRule`-un adi implementasiyasıdır: motor DƏYİŞMİR, yalnız
`register_rule(...)` ilə qoşulur. Qayda YAZMIR — tapıntı motorun öz axınına
düşür; təkrar-qapaq, ciddiyyət defoltu (kataloqdan, migrations/103), audit və
HR_Admin bildirişi motordadır (`exception_engine.py::_persist`). Bildirişin
işləməsi üçün kataloq ciddiyyəti `HIGH` seed olunub — motorun bildiriş həddi
(`EXCEPTION_NOTIFY_MIN_SEVERITY`) defolt HIGH-dır və spesifikasiyanın
«HR_Admin-ə bildiriş» sözü məhz buna bağlanır.

──────────────────────────────────────────────────────────────────────────────
METRİKA — NİYƏ GİRİŞ-SİNXRONLUĞU, KORRELYASIYA ƏMSALI YOX
──────────────────────────────────────────────────────────────────────────────
Pearson korrelyasiyası vaxt-silsiləri ÜZRƏDİR: iki işçinin giriş anlarını bir
oxda birləşdirmək riyazi olaraq mümkündür, amma nəticəni İZAHA ETMƏK OLMAZ —
HR-a "korrelyasiya 0.93" deyən sətir qərar daşıymır. Burada istifadə olunan
metrika sadə və auditoriya üçün oxunaqlıdır:

    sinxronluk % = |girişləri SYNC_MINUTES içində üst-üstə düşən ortaq iş
                   günləri| / |hər ikisinin EYNİ mağazada işlədiyi günlər|

Spesifikasiyanın hər iki misalı bu rəqəmin içindədir: «həmişə eyni növbədə» —
ortaq günlərin yüksək payı; «qayıbın örtülməsi» — biri gecikib girəndə digəri
dəqiqələr içində peyda olur. Hədd aşılırsa TAPINTI yazılır, AVTOMATİK HEÇ NƏ
ETMİR: eyni avtobusda gedən iki həmkar da bu həddi keçə bilər — qərar
araşdırmadadır, kodda deyil.

──────────────────────────────────────────────────────────────────────────────
PƏNCƏRƏ NİYƏ BEHAVIOR_BASELINE_WINDOW_DAYS-DƏN GƏLİR
──────────────────────────────────────────────────────────────────────────────
«Son N gün» sualına sistemin ARTIQ bir cavabı var (#8 baz xətti pəncərəsi).
Davranış-cüt ayrıca pəncərə açsaydı, iki xüsusiyyət fərqli tarix aralıqlarına
baxa bilərdi: anomaliya qaydası «son 30 günün adamı», cüt-qayda isə «son 14
günün adamı» haqqında danışardı. EYNI xam mənbəyi (`CheckInHistoryProvider`)
paylaşan iki qayda EYNI pəncərəni paylaşır — Root pəncərəni genişləndirəndə
hər iki sualın cavabı BİRLİKDƏ dəyişir.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.exception_signals import (
    BEHAVIOR_PAIR_SOURCE,
    ExceptionFinding,
    RuleEvaluationContext,
)
from src.domain.value_objects.scheduling import checkin_minutes_since_midnight

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.domain.interfaces.ports import CheckInHistoryProvider
    from src.domain.value_objects.behavior_signals import CheckInObservation
    from src.domain.value_objects.identifiers import EmployeeId, StoreId

#: Fallback dəyərlər — bax `policies.py`-dakı `SystemLimitKey.BEHAVIOR_PAIR_*`
#: şərhləri. HƏQİQİ MƏNBƏ `system_limits`-dir (migrations/103 seed edir); bu
#: sabitlər YALNIZ sətir hələ seed edilməyibsə işə düşür.
_FALLBACK_THRESHOLD: Final = int(DEFAULT_LIMITS[SystemLimitKey.BEHAVIOR_PAIR_CORRELATION_THRESHOLD])
_FALLBACK_MIN_SHARED_DAYS: Final = int(DEFAULT_LIMITS[SystemLimitKey.BEHAVIOR_PAIR_MIN_SHARED_DAYS])
_FALLBACK_SYNC_MINUTES: Final = int(DEFAULT_LIMITS[SystemLimitKey.BEHAVIOR_PAIR_SYNC_MINUTES])
_FALLBACK_WINDOW_DAYS: Final = int(DEFAULT_LIMITS[SystemLimitKey.BEHAVIOR_BASELINE_WINDOW_DAYS])

#: Cüt hesablamasına başlamaq üçün minimum işçi sayı — riyazi tələb
#: (bir işçidən cüt çıxmır), biznes həddi DEYİL.
_MIN_PAIRABLE_EMPLOYEES: Final = 2


class PairBehaviorCorrelationRule:
    """Faza 7 — davranış-nümunələri üst-üstə düşən işçi cütləri.

    ──────────────────────────────────────────────────────────────────────────
    SORĞU LAQEYDDİR — BehaviorAnomalyRule İLƏ EYNİ
    ──────────────────────────────────────────────────────────────────────────
    `CheckInHistoryProvider` yalnız `evaluate()` dedikdə çağırılır. N² cüt
    müqayisəsi kompozisiya anında işə düşsəydi, hər sessiya qurulanda bütün
    kirayəçinin giriş tarixçəsi tətbiq qatına daşınardı — PERF-1 büdcəsinə
    ziddir. Gecəlik motor bunu GÜNDƏ BİR DƏFƏ edir.
    """

    def __init__(self, *, checkins: CheckInHistoryProvider) -> None:
        self._checkins = checkins

    @property
    def source_code(self) -> str:
        return BEHAVIOR_PAIR_SOURCE

    @property
    def name_az(self) -> str:
        return "Davranış-cüt korrelyasiyası"

    def evaluate(self, context: RuleEvaluationContext) -> list[ExceptionFinding]:
        """Cüt-tapıntıları qaytarır — kiçik-ID subyektdir, böyük kontekstdədir.

        `dedupe_key` = cüt + gün (DuplicateFaceExceptionRule ilə eyni gündəlik
        ritm): yalnız gün seçilsəydi həll olunmamış cüt hər gecə yeni sətir
        açardı; yalnız cüt seçilsəydi HR bir dəfə rədd etsəydi şübhə susardı.
        """
        threshold_pct = context.limit_int(
            SystemLimitKey.BEHAVIOR_PAIR_CORRELATION_THRESHOLD.value,
            _FALLBACK_THRESHOLD,
        )
        min_shared = context.limit_int(
            SystemLimitKey.BEHAVIOR_PAIR_MIN_SHARED_DAYS.value,
            _FALLBACK_MIN_SHARED_DAYS,
        )
        sync_minutes = context.limit_int(
            SystemLimitKey.BEHAVIOR_PAIR_SYNC_MINUTES.value,
            _FALLBACK_SYNC_MINUTES,
        )
        window_days = context.limit_int(
            SystemLimitKey.BEHAVIOR_BASELINE_WINDOW_DAYS.value,
            _FALLBACK_WINDOW_DAYS,
        )

        # Pəncərə DÜNƏNlə bitir, BUGÜNÜ ehtiva ETMİR — #8 baz xətti ilə EYNİ
        # qərar: natamam bugünkü gün statistikanı təhrif etməməlidir.
        until = context.as_of.date() - timedelta(days=1)
        since = until - timedelta(days=max(0, window_days - 1))

        by_employee = _group_by_employee(
            self._checkins.list_checkins(context.tenant_id, since=since, until=until)
        )
        if len(by_employee) < _MIN_PAIRABLE_EMPLOYEES:
            return []

        today = context.as_of.date().isoformat()
        findings: list[ExceptionFinding] = []
        for left_id, right_id in itertools.combinations(sorted(by_employee), 2):
            match = _pair_match(
                by_employee[left_id], by_employee[right_id], sync_minutes=sync_minutes
            )
            if match is None or match.shared_days < min_shared:
                continue
            synchrony = 100.0 * match.sync_days / match.shared_days
            if synchrony < threshold_pct:
                continue

            findings.append(
                ExceptionFinding(
                    employee_id=left_id,
                    store_id=match.store_id,
                    detail=(
                        f"İki işçi son {window_days} gündə {match.shared_days} ortaq "
                        f"iş gününün {round(synchrony)}%-ində girişlərini "
                        f"{sync_minutes} dəqiqədən qısaca üst-üstə salır "
                        f"(median fərq {round(median(match.gaps), 1)} dəq). "
                        f"Korrelyasiya həddi {threshold_pct}% (Root parametri). "
                        "Cüt araşdırma obyektidir — avtomatik heç nə edilir."
                    ),
                    context={
                        "pair_employee_id": str(right_id),
                        "shared_days": match.shared_days,
                        "union_days": match.union_days,
                        "sync_days": match.sync_days,
                        "sync_share_percent": round(synchrony, 1),
                        "median_gap_minutes": round(median(match.gaps), 1),
                        "threshold_percent": threshold_pct,
                    },
                    dedupe_key=f"{left_id}:{right_id}:{today}",
                )
            )
        return findings


def _group_by_employee(
    observations: list[CheckInObservation],
) -> dict[EmployeeId, dict[date, tuple[StoreId, float]]]:
    """`işçi → gün → (mağaza, yerli-giriş-dəqiqəsi)` xəritəsi.

    GÜN mağazanın YERLİ tarixidir (`checked_in_at` zona ilə çevrilir):
    server UTC-də işləsə də Bakı səhər girişi yerli təqvimə aiddir —
    `.astimezone()` ARQUMENTSİZ çağırılsaydı gün SERVER zonasına görə seçilərdi
    və UTC+4-də gecəyarısı ətrafında yanlış gücə düşərdi. Dəqiqənin ÖZÜ isə
    `checkin_minutes_since_midnight`-dan gəlir — «giriş dəqiqəsi» tərifinin
    yeganə mənbəyi (#8 ilə eyni).
    """
    grouped: dict[EmployeeId, dict[date, tuple[StoreId, float]]] = {}
    for obs in observations:
        local_day = obs.checked_in_at.astimezone(ZoneInfo(obs.store_timezone)).date()
        minutes = checkin_minutes_since_midnight(
            obs.checked_in_at, timezone_name=obs.store_timezone
        )
        grouped.setdefault(obs.employee_id, {})[local_day] = (obs.store_id, minutes)
    return grouped


@dataclass(frozen=True)
class _PairStats:
    """Bir cütün hesablanmış statistikası — `dict` YOX, adlı sahələrlə.

    Sahələr tapıntının `context_json`-una HƏRFƏN keçir — adlar HR-ın oxuduğu
    rəqəmlərin adlarıdır və ekranda/maketdə eyni açarlarla göstərilir.
    """

    store_id: StoreId
    shared_days: int
    union_days: int
    sync_days: int
    gaps: list[float]


def _pair_match(
    left: Mapping[date, tuple[StoreId, float]],
    right: Mapping[date, tuple[StoreId, float]],
    *,
    sync_minutes: int,
) -> _PairStats | None:
    """İki işçinin ortaq günlərini hesablayır — ortaq gün yoxdursa `None`.

    ORTAQ GÜN = hər ikisinin EYNİ mağazada giriş etdiyi gün. Fərqli
    mağazaların üst-üstə düşməsi təsadüfüdür (bir işçi başqa filiala köməyə
    gedibsə) və «eyni növbə» demək deyil.
    """
    store_days: dict[StoreId, list[float]] = {}
    union_days = len(set(left) | set(right))
    for day, (left_store, left_minutes) in left.items():
        right_entry = right.get(day)
        if right_entry is None or right_entry[0] != left_store:
            continue
        store_days.setdefault(left_store, []).append(abs(left_minutes - right_entry[1]))
    if not store_days:
        return None

    # Ən çox ortaq günün olduğu mağaza cütün «ana» mağazasıdır — tapıntı
    # həmin mağazaya bağlanır (`exceptions.store_id` NOT NULL-dur).
    store_id, gaps = max(store_days.items(), key=lambda item: len(item[1]))
    return _PairStats(
        store_id=store_id,
        shared_days=len(gaps),
        union_days=union_days,
        sync_days=sum(1 for gap in gaps if gap <= sync_minutes),
        gaps=gaps,
    )


__all__ = [
    "BEHAVIOR_PAIR_SOURCE",
    "PairBehaviorCorrelationRule",
]
