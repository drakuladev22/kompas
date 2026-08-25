"""Tarixi-nümunə təklifinin saxlama qatı (#13) — `staffing_pattern_suggestions`
+ `attendance_records`-dan mağaza-günü kadr sayı.

QAYDA (bölmə 2): 100% parameterləşdirilmiş SQL. RLS-Ə ƏLAVƏ İKİNCİ QAT: hər
sorğuda açıq `tenant_id` şərti var — layihənin bütün repo-larında eyni naxış
(bax `behavior_repositories.py` başlığı).

──────────────────────────────────────────────────────────────────────────────
NİYƏ `COUNT(DISTINCT employee_id)`
──────────────────────────────────────────────────────────────────────────────
Bir işçinin bir günündə İKİ davamiyyət sətri ola bilər (səhər girişi + qayıdış
təsdiqi ayrı sətirlərdə deyil, lakin manual düzəliş və yenidən-yaratma halları
mövcuddur). Sadə `COUNT(*)` həmin günü "iki işçi" kimi göstərər və təklif
səssizcə şişərdi. `DISTINCT` bu riski sxem səviyyəsində deyil, sorğu
səviyyəsində bağlayır — çünki `attendance_records`-a toxunmaq QADAĞANDIR
(migrations/019 başlığı).

──────────────────────────────────────────────────────────────────────────────
NİYƏ `check_in_status = 'VERIFIED'`
──────────────────────────────────────────────────────────────────────────────
"Faktiki işləmiş işçi" tərifi bölmə 4-dəki STEP C-dir: yalnız Kamera
Operatorunun təsdiqlədiyi giriş rəsmi sayılır (`verified_at` "günün RƏSMİ
başlama vaxtı"dır). Gözləyən/rədd edilmiş sətirləri saymaq "gəlmək istəyən"
ilə "gələn"i qarışdırardı — eyni tərif `PostgresCheckInHistoryProvider`-də də
işlədilir, yəni #8 və #13 EYNİ "işə çıxdı" anlayışını daşıyır.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.application.use_cases.campaign_periods import CampaignPeriod
from src.domain.entities.attendance_record import CheckInStatus
from src.domain.value_objects.identifiers import StoreId, TenantId
from src.domain.value_objects.staffing_signals import (
    StaffingPatternSuggestion,
    StoreDayHeadcount,
)
from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from datetime import date


class PostgresStaffingPatternRepository(_BaseRepository):
    """`staffing_pattern_suggestions` — mağaza + həftə günü = BİR sətir (#13)."""

    _SELECT = """
        SELECT tenant_id, store_id, weekday, avg_historical_headcount,
               campaign_adjusted_headcount, based_on_weeks, calculated_at
        FROM staffing_pattern_suggestions
    """

    def list_for_store(
        self, tenant_id: TenantId, store_id: StoreId
    ) -> list[StaffingPatternSuggestion]:
        rows = self._fetch_all(
            f"{self._SELECT} WHERE tenant_id = %s AND store_id = %s ORDER BY weekday",
            (tenant_id, store_id),
        )
        return [_row_to_suggestion(row) for row in rows]

    def save(self, suggestion: StaffingPatternSuggestion) -> None:
        """UPSERT — `ON CONFLICT (tenant_id, store_id, weekday)`.

        `id` sütunu SİYAHIDA YOXDUR: sətir tam törəmə olduğu üçün domen
        obyektinin öz identifikatoru yoxdur (bax `staffing_signals.py`
        başlığı) — ilk yazıda DB `gen_random_uuid()` defoltu işə düşür,
        yenidən-hesablamada isə mövcud `id` `ON CONFLICT` sayəsində TOXUNULMUR.

        `created_at` da SİYAHIDA YOXDUR və `DO UPDATE` onu yazmır: təklifin
        NƏ VAXT İLK DƏFƏ yarandığı ayrı fakt olaraq qalmalıdır, əks halda
        "bu mağaza üçün nümunə nə vaxtdan izlənir?" sualı cavabsız qalardı.
        """
        self._execute(
            """
            INSERT INTO staffing_pattern_suggestions
                (tenant_id, store_id, weekday, avg_historical_headcount,
                 campaign_adjusted_headcount, based_on_weeks, calculated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, store_id, weekday) DO UPDATE
                SET avg_historical_headcount    = EXCLUDED.avg_historical_headcount,
                    -- `NULL` DA YAZILIR (COALESCE YOXDUR): kampaniya dövrü
                    -- söndürüləndə köhnə çəkili rəqəm sətirdə qalsaydı, ekran
                    -- artıq mövcud olmayan bir kampaniyanın təklifini
                    -- göstərməyə davam edərdi (migrations/108).
                    campaign_adjusted_headcount = EXCLUDED.campaign_adjusted_headcount,
                    based_on_weeks              = EXCLUDED.based_on_weeks,
                    calculated_at               = EXCLUDED.calculated_at
            """,
            (
                suggestion.tenant_id,
                suggestion.store_id,
                suggestion.weekday,
                suggestion.avg_historical_headcount,
                suggestion.campaign_adjusted_headcount,
                suggestion.based_on_weeks,
                suggestion.calculated_at,
            ),
        )


class PostgresStaffingHistoryProvider(_BaseRepository):
    """Mağaza-günü kadr sayı — `attendance_records` üzərində (bax modul başlığı).

    1C-YƏ HEÇ BİR MÜRACİƏT YOXDUR: sorğuda nə `erp_*` cədvəli, nə `sales_*`
    sütunu var.
    """

    def headcount_by_day(
        self, tenant_id: TenantId, *, store_id: StoreId, since: date, until: date
    ) -> list[StoreDayHeadcount]:
        rows = self._fetch_all(
            """
            SELECT work_date, COUNT(DISTINCT employee_id) AS headcount
            FROM attendance_records
            WHERE tenant_id = %s
              AND store_id = %s
              AND check_in_status = %s
              AND work_date BETWEEN %s AND %s
            GROUP BY work_date
            ORDER BY work_date
            """,
            (tenant_id, store_id, CheckInStatus.VERIFIED.value, since, until),
        )
        return [
            StoreDayHeadcount(work_date=row["work_date"], headcount=int(row["headcount"]))
            for row in rows
        ]


class PostgresCampaignPeriodRepository(_BaseRepository):
    """`campaign_periods` — v2backlog.md Faza 6.4 (migrations/089 sxemi).

    Repo TƏKMİLDİR: ad/tarix yoxlamaları use case-də, `chk_campaign_period_
    dates` DB-də — burada yalnız oxu/yazı. Soft-delete (`is_active`) use
    case-in qərarıdır, silmə yoxdur (`catalogs.py` əsaslandırması).
    """

    def list_periods(self, tenant_id: TenantId, *, include_inactive: bool) -> list[CampaignPeriod]:
        extra = "" if include_inactive else " AND is_active"
        rows = self._fetch_all(
            # f-string yalnız İKİ sabit variantdan birini seçir — dinamik SQL
            # yoxdur, dəyərlər %s ilə bağlanır (CLAUDE.md §4).
            f"""
            SELECT id, name, start_date, end_date, is_active
            FROM campaign_periods
            WHERE tenant_id = %s{extra}
            ORDER BY start_date DESC, name
            """,  # noqa: S608 - şərtlər sabit siyahıdandır
            (tenant_id,),
        )
        return [
            CampaignPeriod(
                period_id=str(row["id"]),
                name=str(row["name"]),
                start_date=row["start_date"],
                end_date=row["end_date"],
                is_active=bool(row["is_active"]),
            )
            for row in rows
        ]

    def create(
        self,
        tenant_id: TenantId,
        *,
        name: str,
        start_date: date,
        end_date: date,
        created_by_id: object,
    ) -> CampaignPeriod:
        row = self._fetch_one(
            """
            INSERT INTO campaign_periods
                (tenant_id, name, start_date, end_date, created_by)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, name, start_date, end_date, is_active
            """,
            (tenant_id, name, start_date, end_date, created_by_id),
        )
        if row is None:  # pragma: no cover — RETURNING həmişə sətir qaytarır
            raise RuntimeError("campaign_periods INSERT nəticə vermədi")
        return CampaignPeriod(
            period_id=str(row["id"]),
            name=str(row["name"]),
            start_date=row["start_date"],
            end_date=row["end_date"],
            is_active=bool(row["is_active"]),
        )

    def deactivate(self, tenant_id: TenantId, period_id: str) -> bool:
        row = self._fetch_one(
            """
            UPDATE campaign_periods
               SET is_active = FALSE,
                   deactivated_at = now()
             WHERE tenant_id = %s AND id = %s AND is_active
            RETURNING id
            """,
            (tenant_id, period_id),
        )
        return row is not None


def _row_to_suggestion(row: dict[str, Any]) -> StaffingPatternSuggestion:
    return StaffingPatternSuggestion(
        tenant_id=TenantId(row["tenant_id"]),
        store_id=StoreId(row["store_id"]),
        weekday=int(row["weekday"]),
        # `NUMERIC` psycopg-dən `Decimal` gəlir; domen `float` işlədir (eyni
        # seçim `BehaviorBaseline`-dədir) — pul DEYİL, ona görə `Money`-nin
        # dəqiqlik tələbi burada tətbiq olunmur.
        avg_historical_headcount=float(row["avg_historical_headcount"]),
        # `None` QORUNUR — `float(None)` çökərdi, `float(row.get(...) or 0)` isə
        # "kampaniya günü olmayıb"ı "kampaniyada 0 nəfər"ə çevirərdi (bax
        # `staffing_signals.py`-dakı sahə şərhi).
        campaign_adjusted_headcount=(
            None
            if row.get("campaign_adjusted_headcount") is None
            else float(row["campaign_adjusted_headcount"])
        ),
        based_on_weeks=int(row["based_on_weeks"]),
        calculated_at=row["calculated_at"],
    )


__all__ = [
    "PostgresCampaignPeriodRepository",
    "PostgresStaffingHistoryProvider",
    "PostgresStaffingPatternRepository",
]
