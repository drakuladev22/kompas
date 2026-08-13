"""Performans Qiymətləndirməsi aqreqatı (#20, kompasos11.md Faza 8) — `performance_reviews`.

`migrations/020` başlığı: `ratings_json` QƏSDƏN sərt sütun siyahısı DEYİL —
KPI dəsti Root tərəfindən konfiqurasiya edilir (`system_limits.
PERFORMANCE_REVIEW_KPI_CATALOG`). Bu aqreqat KPI KODLARININ MƏNASINI tanımır
(hansı kod "keyfiyyət", hansı "məhsuldarlıq"dır — bunu yalnız use case/ekran
bilir) — o, YALNIZ ÜMUMİ FORMATI (kod → 1-5 bal) və İKİ struktur qaydanı
qoruyur: öz-özünü qiymətləndirmə bloku və dövr formatı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ QİYMƏT ŞKALASI (1–5) ROOT PARAMETRİ DEYİL
──────────────────────────────────────────────────────────────────────────────
CLAUDE.md §5 sualı: bu, sistem limiti/taymautu deyil, ÖLÇÜ VAHİDİDİR.
`overall_score` düsturu (aşağı bax) MİN/MAX-a RİYAZİ olaraq bağlıdır — şkala
dəyişsə, artıq YAZILMIŞ `overall_score` sətirləri YENİ şkala ilə uyğunsuz
qalardı (məs. "3/5" ilə "3/10" eyni faizə çevrilmir). Bunu konfiqurasiya edilə
bilən etmək köhnə qiymətləri geriyə dönük mənasız edərdi — `RolePriority`
kimi bu da struktur sabitdir, ROOT panelindən DƏYİŞDİRİLMİR.

──────────────────────────────────────────────────────────────────────────────
NİYƏ TƏKRAR GÖNDƏRİŞ YENİ SƏTİR YARATMIR
──────────────────────────────────────────────────────────────────────────────
`migrations/020`: `UNIQUE (tenant_id, employee_id, period)` — "bir işçi + bir
dövr = BİR qiymətləndirmə". `update_ratings()` MƏHZ bunun üçündür: eyni dövr
üçün ikinci qiymətləndirmə mövcud sətri YENİLƏYİR (reviewer də DƏYİŞƏ bilər —
son qiymətləndirən kimdirsə sətir ONUN adına keçir), dəyişiklik izi isə
`audit_logs`-dakı before/after snapshot-dadır (use case qatı).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from src.domain.entities.base import AggregateRoot, DomainRuleError
from src.domain.events import PerformanceReviewRecordedEvent
from src.domain.value_objects.identifiers import EmployeeId, PerformanceReviewId, TenantId
from src.domain.value_objects.scheduling import require_aware

#: `performance_reviews.period` CHECK-inin domen güzgüsü (migrations/020):
#: 'YYYY' (illik), 'YYYY-MM' (aylıq) və ya 'YYYY-Qn' (rüblük).
_PERIOD_PATTERN: Final = re.compile(r"^\d{4}(-(0[1-9]|1[0-2]|Q[1-4]))?$")

#: Likert şkalası sərhədləri — ROOT PARAMETRİ DEYİL (bax modul başlığı).
KPI_SCORE_MIN: Final = 1
KPI_SCORE_MAX: Final = 5

#: `overall_score` yuvarlama dəqiqliyi — `NUMERIC(5, 2)` sxem sütunu ilə eyni.
_SCORE_QUANTUM: Final = Decimal("0.01")


class SelfReviewNotAllowedError(DomainRuleError):
    """Vəzifə ayrılığı: qiymətləndirən özünü qiymətləndirə bilməz."""

    user_message = "Özünüzü qiymətləndirə bilməzsiniz."


class PerformanceReview(AggregateRoot):
    """Bir işçinin bir dövrə aid qiymətləndirmə sətri (`performance_reviews`)."""

    def __init__(
        self,
        *,
        review_id: PerformanceReviewId,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        reviewer_id: EmployeeId,
        period: str,
        ratings: Mapping[str, int],
        notes: str | None,
        created_at: datetime,
        updated_at: datetime,
        overall_score: Decimal | None = None,
        emit_created_event: bool = True,
    ) -> None:
        super().__init__()
        # `chk_review_not_self` güzgüsü (migrations/020) — DB TƏKRAR qoruyur,
        # metod ÜMUMİYYƏTLƏ yoxdur ki, ekranı yan keçən skript də tabe olsun.
        if employee_id == reviewer_id:
            raise SelfReviewNotAllowedError(
                "Qiymətləndirən özünü qiymətləndirə bilməz",
                context={"employee_id": str(employee_id)},
            )
        cleaned_period = period.strip()
        if not _PERIOD_PATTERN.match(cleaned_period):
            raise DomainRuleError(
                "Dövr formatı düzgün deyil (gözlənilən: YYYY, YYYY-MM və ya YYYY-Qn)",
                user_message="Dövr formatı düzgün deyil.",
                context={"period": period},
            )
        cleaned_ratings = _clean_ratings(ratings)
        if not cleaned_ratings:
            raise DomainRuleError(
                "Ən azı bir KPI qiymətləndirilməlidir",
                user_message="Ən azı bir göstərici üçün qiymət daxil edin.",
                context={"employee_id": str(employee_id)},
            )

        self.id = review_id
        self.tenant_id = tenant_id
        self.employee_id = employee_id
        self.reviewer_id = reviewer_id
        self.period = cleaned_period
        self.ratings = cleaned_ratings
        self.notes = notes.strip() if notes and notes.strip() else None
        self.created_at = require_aware(created_at, field="created_at")
        self.updated_at = require_aware(updated_at, field="updated_at")
        # BƏRPA yolunda `overall_score` DB-dən OLDUĞU KİMİ gəlir, YENİDƏN
        # HESABLANMIR — `migrations/020` şərhi: "hesablama BİR DƏFƏ, yazı
        # anında aparılır" (Root düsturu sonradan dəyişsə, köhnə sətirlər
        # KÖHNƏ hesablama ilə qalmalıdır, əks halda eyni ekranda iki fərqli
        # qayda ilə hesablanmış bal yan-yana görünərdi — `attrition_risk_
        # scores`-dəki bant qərarı ilə EYNİ əsaslandırma).
        self.overall_score = (
            overall_score if overall_score is not None else _compute_overall_score(cleaned_ratings)
        )

        if emit_created_event:
            self.record_event(
                PerformanceReviewRecordedEvent(
                    tenant_id=tenant_id,
                    actor_id=reviewer_id,
                    review_id=review_id,
                    employee_id=employee_id,
                    period=cleaned_period,
                    overall_score=self.overall_score,
                )
            )

    # -------------------------------- yazı yolu -------------------------------- #

    def update_ratings(
        self,
        *,
        reviewer_id: EmployeeId,
        ratings: Mapping[str, int],
        notes: str | None,
        now: datetime,
    ) -> None:
        """Eyni dövr üçün TƏKRAR qiymətləndirmə — mövcud sətri YENİLƏYİR (modul başlığı)."""
        if self.employee_id == reviewer_id:
            raise SelfReviewNotAllowedError(
                "Qiymətləndirən özünü qiymətləndirə bilməz",
                context={"employee_id": str(self.employee_id)},
            )
        cleaned_ratings = _clean_ratings(ratings)
        if not cleaned_ratings:
            raise DomainRuleError(
                "Ən azı bir KPI qiymətləndirilməlidir",
                user_message="Ən azı bir göstərici üçün qiymət daxil edin.",
                context={"employee_id": str(self.employee_id)},
            )
        self.reviewer_id = reviewer_id
        self.ratings = cleaned_ratings
        self.notes = notes.strip() if notes and notes.strip() else None
        self.overall_score = _compute_overall_score(cleaned_ratings)
        self.updated_at = require_aware(now, field="now")

    # -------------------------------- audit ------------------------------------ #

    def to_audit_state(self) -> dict[str, object]:
        return {
            "period": self.period,
            "reviewer_id": str(self.reviewer_id),
            "ratings": dict(self.ratings),
            "overall_score": str(self.overall_score) if self.overall_score is not None else None,
            "notes": self.notes,
        }

    def __repr__(self) -> str:
        return (
            f"PerformanceReview(id={self.id}, employee_id={self.employee_id}, "
            f"period={self.period}, overall_score={self.overall_score})"
        )


def _clean_ratings(ratings: Mapping[str, int]) -> dict[str, int]:
    """KPI kodlarını BÖYÜK hərfə normallaşdırır, hər balı 1-5 aralığında yoxlayır."""
    cleaned: dict[str, int] = {}
    for raw_code, score in ratings.items():
        code = raw_code.strip().upper()
        if not code:
            continue
        if isinstance(score, bool) or not isinstance(score, int):
            raise DomainRuleError(
                "KPI qiyməti tam ədəd olmalıdır",
                user_message="KPI qiyməti düzgün deyil.",
                context={"kpi": code, "score": repr(score)},
            )
        if score < KPI_SCORE_MIN or score > KPI_SCORE_MAX:
            raise DomainRuleError(
                f"KPI qiyməti {KPI_SCORE_MIN}-{KPI_SCORE_MAX} aralığında olmalıdır",
                user_message=f"KPI qiyməti {KPI_SCORE_MIN}-{KPI_SCORE_MAX} arasında olmalıdır.",
                context={"kpi": code, "score": score},
            )
        cleaned[code] = score
    return cleaned


def _compute_overall_score(ratings: Mapping[str, int]) -> Decimal:
    """KPI ballarının ORTA qiymətini 0-100 xalına xəritələndirir.

    Düstur: `(orta - MIN) / (MAX - MIN) * 100` — 1 bal → 0, 5 bal → 100.
    ÇƏKİLƏR BƏRABƏRDİR (sadə orta): tapşırıq YALNIZ "bir neçə KPI + qeyd"
    tələb edir, fərqli çəki spesifikasiyada YOXDUR — `#21`-in (Turnover Riski,
    Faza 9) hər amilin ÖZ çəkisi olan modelindən QƏSDƏN fərqlidir, çünki o,
    ayrı bir alqoritmdir (kompasos11.md #21). Çəki lazım olsa, gələcəkdə
    `PERFORMANCE_REVIEW_KPI_CATALOG` formatına "KOD:Ad:Çəki" kimi genişlənə
    bilər — bu, YENİ tələb gəlməzdən əvvəl spekulyativ mürəkkəblik olardı.
    """
    total = sum(ratings.values())
    average = Decimal(total) / Decimal(len(ratings))
    span = Decimal(KPI_SCORE_MAX - KPI_SCORE_MIN)
    scaled = (average - Decimal(KPI_SCORE_MIN)) / span * Decimal(100)
    return scaled.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP)


__all__ = [
    "KPI_SCORE_MAX",
    "KPI_SCORE_MIN",
    "PerformanceReview",
    "SelfReviewNotAllowedError",
]
