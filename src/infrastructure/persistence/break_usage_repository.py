"""Nahar / Çay fasiləsinin gündəlik sayğacı (`daily_break_usage`) — nahar.md.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI FAYL, `config_repositories.py`-A ƏLAVƏ DEYİL
──────────────────────────────────────────────────────────────────────────────
`config_repositories.py` KONFİQURASİYA oxuyur — limitlər, modul açarları,
kataloqlar. Bu isə ƏMƏLİYYAT məlumatıdır: hər STEP1-də dəyişən, işçiyə aid
gündəlik sayğac. İkisini bir fayla yığmaq "konfiqurasiya" adı altında dəyişən
məlumat saxlamaq olardı və faylın öz başlığındakı "bunlar aqreqat deyil,
sadəcə konfiqurasiya oxuyurlar" izahını yalana çıxarardı.

──────────────────────────────────────────────────────────────────────────────
BU REPOSITORY HEÇ NƏ BLOKLAMIR
──────────────────────────────────────────────────────────────────────────────
nahar.md §MƏNTİQ, bənd 2 açıq göstərişdir: gündəlik say-həddi aşılanda sistem
əməliyyatı BLOKLAMIR, yalnız xəbərdarlıq göstərir. Ona görə burada nə hədd
arqumenti, nə `CHECK`, nə də "artıra bilərəmmi?" sualı var — sorğular yalnız
SAYIR. Həddin qiymətləndirilməsi domendədir (`BreakAllowance.is_exceeded`),
çünki hədd Root-un istənilən an dəyişdiyi `system_limits` sətridir; SQL-ə
yazılsaydı, dəyişiklik ancaq növbəti miqrasiyadan sonra təsir edərdi.

──────────────────────────────────────────────────────────────────────────────
ARTIRMA NİYƏ UPSERT-DİR, "OXU → ARTIR → YAZ" DEYİL
──────────────────────────────────────────────────────────────────────────────
Bir mağazada bir neçə kiosk terminalı var. İki terminal eyni saniyədə STEP1
göndərsə, tətbiq qatında oxunan `count_used` hər ikisində eyni olar və ikinci
yazı birincini üstələyərdi — yəni bir fasilə İZSİZ itərdi. `ON CONFLICT DO
UPDATE ... count_used + 1` artımı bazanın öz sətir kilidi altında edir və
`RETURNING` yeni dəyəri eyni gedişdə gətirir (ikinci `SELECT` aralığında
başqa terminal sayğacı yenidən artıra bilər).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.domain.policies import BreakKind
from src.infrastructure.persistence.repositories import _BaseRepository
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from datetime import date, datetime

    from src.domain.value_objects.identifiers import EmployeeId, TenantId

_log = get_logger(__name__)


class PostgresDailyBreakUsageRepository(_BaseRepository):
    """`daily_break_usage` — işçi × gün × fasilə növü sayğacı."""

    def record_use(
        self,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        *,
        kind: BreakKind,
        on_date: date,
        at: datetime,
    ) -> int:
        """Sayğacı bir vahid artırır və YENİ dəyəri qaytarır (atomik UPSERT)."""
        row = self._fetch_one(
            """
            INSERT INTO daily_break_usage
                (tenant_id, employee_id, usage_date, break_type, count_used, last_used_at)
            VALUES (%s, %s, %s, %s, 1, %s)
            ON CONFLICT (employee_id, usage_date, break_type)
            DO UPDATE SET count_used   = daily_break_usage.count_used + 1,
                          last_used_at = EXCLUDED.last_used_at
            RETURNING count_used
            """,
            (tenant_id, employee_id, on_date, kind.value, at),
        )
        # `RETURNING` UPSERT-də HƏMİŞƏ sətir verir (nə INSERT, nə UPDATE boşa
        # çıxa bilməz), lakin `_fetch_one` imzası `None` icazə verir — fallback
        # 1-dir, çünki bu nöqtəyə çatan hər çağırış ƏN AZI bir istifadə deməkdir.
        count = int(row["count_used"]) if row else 1
        _log.info(
            "BREAK_USE_RECORDED",
            extra={
                "employee_id": str(employee_id),
                "break_kind": kind.value,
                "usage_date": on_date.isoformat(),
                "count_used": count,
            },
        )
        return count

    def count_for_day(self, employee_id: EmployeeId, *, kind: BreakKind, on_date: date) -> int:
        """Tək növün sayğacı — sətir yoxdursa 0."""
        row = self._fetch_one(
            """
            SELECT count_used
            FROM daily_break_usage
            WHERE employee_id = %s AND usage_date = %s
              AND break_type = %s AND tenant_id = %s
            """,
            (employee_id, on_date, kind.value, self._tenant),
        )
        return int(row["count_used"]) if row else 0

    def usage_for_day(self, employee_id: EmployeeId, *, on_date: date) -> dict[BreakKind, int]:
        """Hər iki növ bir sorğuda.

        Ekran ikisini birlikdə göstərir; iki ayrı `count_for_day` çağırışı
        eyni cavabı iki gediş-gəlişlə gətirərdi və aralarında sayğac dəyişsə
        ekran öz-özü ilə ziddiyyətli iki rəqəm göstərərdi.
        """
        rows = self._fetch_all(
            """
            SELECT break_type, count_used
            FROM daily_break_usage
            WHERE employee_id = %s AND usage_date = %s AND tenant_id = %s
            """,
            (employee_id, on_date, self._tenant),
        )
        usage: dict[BreakKind, int] = dict.fromkeys(BreakKind, 0)
        for row in rows:
            kind = _break_kind_or_none(row.get("break_type"))
            if kind is not None:
                usage[kind] = int(row.get("count_used") or 0)
        return usage

    def usage_rows_for_day(
        self, tenant_id: TenantId, *, on_date: date
    ) -> list[tuple[EmployeeId, BreakKind, int]]:
        """HR panelinin gündəlik icmalı — kirayəçi üzrə BÜTÜN sətirlər.

        `count_used > 0` süzgəci qoyulur: sıfır dəyərli sətir praktikada
        yaranmır (UPSERT birbaşa 1-dən başlayır), lakin əl ilə düzəliş belə
        bir sətir buraxsa, o, "fasilə istifadə edilib" siyahısında görünməməli
        idi. HƏDD süzgəci isə BURADA YOXDUR — bax modul başlığı.
        """
        rows = self._fetch_all(
            """
            SELECT employee_id, break_type, count_used
            FROM daily_break_usage
            WHERE tenant_id = %s AND usage_date = %s AND count_used > 0
            ORDER BY count_used DESC
            """,
            (tenant_id, on_date),
        )
        result: list[tuple[EmployeeId, BreakKind, int]] = []
        for row in rows:
            kind = _break_kind_or_none(row.get("break_type"))
            if kind is None:
                continue
            result.append((row["employee_id"], kind, int(row.get("count_used") or 0)))
        return result


def _break_kind_or_none(raw: object) -> BreakKind | None:
    """`break_type` sütununu enum-a çevirir; naməlum dəyər SÜKUTLA atılır.

    `config_repositories._break_kind_or_none` ilə eyni qərar: gələcək
    miqrasiya üçüncü növ əlavə etsə, köhnə tətbiq həmin sətri görməzdən gəlib
    işləməyə davam etməlidir — HR panelinin bütövlükdə açılmaması qüsurun
    cəzasını istifadəçiyə verərdi.
    """
    if raw is None:
        return None
    try:
        return BreakKind(str(raw))
    except ValueError:
        return None


__all__ = ["PostgresDailyBreakUsageRepository"]
