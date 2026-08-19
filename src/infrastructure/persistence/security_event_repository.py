"""`security_events` — giriş/icazə hadisələrinin YAZI qatı (SEC-7, `schema.sql` §16).

──────────────────────────────────────────────────────────────────────────────
BU SİNİF ÖZ UĞURSUZLUĞUNU UDMUR — QƏSDƏN
──────────────────────────────────────────────────────────────────────────────
`SecurityEventRepository` Protocol-unun (bax `ports.py`) başlığı açıq deyir:
istehsalatda YALNIZ `src.shared.security_events.FailSoftSecurityEventRecorder`
bağlanmalıdır, xam implementasiya BİRBAŞA use case-ə YOX. Fail-soft QƏRARI
(yazı uğursuz olsa istisnanı udub `security.log`-a `critical` yazmaq) O
sinifdədir, BURADA YOX — bu repo sadəcə DB-yə yazır və uğursuzluqda İSTİSNA
ATIR. Səbəb dekoratorun öz başlığındadır: əgər BU repo da udsaydı, İKİ qat
udma yaranardı və gələcəkdə kimsə xam repo-nu SƏHVƏN birbaşa bağlasa,
uğursuzluq HEÇ YERDƏ görünməzdi (nə istisna, nə log) — sükutla "yarım işləyən"
sistem. Udmaq TƏK yerdə, TƏK məsuliyyət kimi qalmalıdır.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from src.domain.value_objects.identifiers import EmployeeId, TenantId


class PostgresSecurityEventRepository(_BaseRepository):
    """`SecurityEventRepository` Protocol-una STRUCTURAL uyğun (miras YOX)."""

    def record(
        self,
        *,
        tenant_id: TenantId,
        event_type: str,
        employee_id: EmployeeId | None = None,
        username_attempt: str | None = None,
        ip_address: str | None = None,
        machine_name: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        # `tenant_id` DEYİL, `self._tenant` YAZILIR: bu, YENİ sətrin
        # AÇARIDIR (INSERT dəyəri), `WHERE` şərti deyil — `auth_session_
        # repository.py`/`fine_review_repository.py`-dəki EYNİ qərar. RLS
        # `WITH CHECK` bunun bağlantının ÖZ kirayəçisi ilə uyğun olmasını
        # MƏCBUR EDİR.
        #
        # `occurred_at` SİYAHIDA YOXDUR — sütun `DEFAULT now()` daşıyır və
        # sütun adı İNSERT-də AÇIQ ÇƏKİLMƏDİYİ üçün defolt YAN KEÇİLMİR
        # (CLAUDE.md §5-in TIME-1 xəbərdarlığı: problem YALNIZ sütun adı
        # açıq yazılanda yaranır). `now()` Postgres SERVERİNİN saatıdır —
        # client saatından asılı deyil, əlavə `Clock` çağırışına ehtiyac yoxdur.
        self._execute(
            """
            INSERT INTO security_events
                (tenant_id, event_type, employee_id, username_attempt,
                 ip_address, machine_name, details)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                self._tenant,
                event_type,
                employee_id,
                username_attempt,
                ip_address,
                machine_name,
                json.dumps(details, ensure_ascii=False, default=str)
                if details is not None
                else None,
            ),
        )


__all__ = ["PostgresSecurityEventRepository"]
