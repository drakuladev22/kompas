"""`webhook_endpoints` (v2backlog.md Faza 12.2, migrations/091).

──────────────────────────────────────────────────────────────────────────────
ŞİFRƏLƏMƏ BURADADIR, USE CASE-DƏ YOX
──────────────────────────────────────────────────────────────────────────────
`WebhookRegistryUseCase` açıq mətnli imza açarı ilə işləyir; onun
`secret_encrypted` sütununa necə düşdüyünü BU sinif bilir — `telegram_
repositories.py` və `face_repository.py` ilə eyni naxış. Alternativ (tətbiq
qatında şifrələmək) rədd edildi: onda application qatı infrastruktur sinfini
birbaşa idxal edərdi (CLAUDE.md §3 qat sırası).

──────────────────────────────────────────────────────────────────────────────
AÇAR GERİ OXUNMUR — HƏLƏLİK YAZILIR VƏ SAXLANILIR
──────────────────────────────────────────────────────────────────────────────
Bu sinifdə `decrypt` çağırışı YOXDUR və bu, natamamlıq deyil: açarı oxuyacaq
YEGANƏ istifadəçi payload imzalayan ÇATDIRMA QATIdır, o isə sənədin öz tələbi
ilə («İNDİ konkret bir inteqrasiya YAZMA») hələ yazılmayıb. Açar indidən
şifrəli saxlanılır ki, çatdırma qatı gələndə köhnə sətirlər onsuz da uyğun
formatda olsun — sonradan «düz mətndən şifrəliyə» miqrasiya etmək həmin açarı
bir müddət jurnalda/ehtiyat nüsxədə açıq qoyardı.

AAD (kontekst) `webhook_endpoints:{tenant_id}`-dir — `telegram_config`-un eyni
qərarı: şifrəli dəyər ÖZ kirayəçisinə bağlanır, başqa kirayəçinin sətrinə
köçürülsə deşifrə uğursuz olur.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.application.use_cases.webhook_registry import WebhookEndpointView
from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from datetime import datetime
    from typing import Any

    from psycopg import Connection

    from src.domain.value_objects.identifiers import EmployeeId, TenantId
    from src.infrastructure.persistence.connection import TenantContext
    from src.infrastructure.security.encryption import EncryptionService


def _context_of(tenant_id: TenantId) -> str:
    return f"webhook_endpoints:{tenant_id}"


def _view_of(row: dict[str, Any]) -> WebhookEndpointView:
    """Sətir → ekran görünüşü. `secret_encrypted` SEÇİLMİR, ona görə düşmür."""
    first = str(row.get("first_name") or "").strip()
    last = str(row.get("last_name") or "").strip()
    return WebhookEndpointView(
        endpoint_id=str(row["id"]),
        event_type=str(row["event_type"]),
        target_url=str(row["target_url"]),
        is_active=bool(row["is_active"]),
        created_at=row.get("created_at"),
        created_by_name=f"{first} {last}".strip(),
    )


class PostgresWebhookEndpointRepository(_BaseRepository):
    """Kirayəçinin webhook hədəfləri.

    `tenant_id` ARQUMENTİ NƏTİCƏYƏ TƏSİR ETMİR — `self._tenant` əsas mənbədir
    (`PostgresTelegramConfigRepository`-nin eyni qərarı): RLS-ə ƏLAVƏ ikinci
    qat çağıranın ötürdüyü dəyərdən ASILI OLMAMALIDIR, əks halda səhvən başqa
    kirayəçinin ID-si ötürülsə qat öz mənasını itirərdi. Arqument imza
    uyğunluğu üçün qalır (`WebhookEndpointRepository` Protocol-u onu tələb
    edir).
    """

    def __init__(
        self,
        conn: Connection[Any],
        context: TenantContext,
        *,
        encryption: EncryptionService,
    ) -> None:
        """`encryption` DEFOLTSUZDUR — bax `telegram_repositories.py` başlığı."""
        super().__init__(conn, context)
        self._encryption = encryption

    def list_all(self, tenant_id: TenantId) -> list[WebhookEndpointView]:
        """AKTİVLƏR ƏVVƏL, sonra ad sırası.

        Sıralama ekranda deyil, BURADA edilir: maket və canlı yol eyni
        ardıcıllığı göstərməlidir (CLAUDE.md §6, `staffing_pattern`-in eyni
        əsaslandırması). Deaktivlərin sona düşməsi qəsdlidir — Root əvvəlcə
        QÜVVƏDƏ olanı görməlidir.
        """
        rows = self._fetch_all(
            """
            SELECT w.id, w.event_type, w.target_url, w.is_active, w.created_at,
                   e.first_name, e.last_name
            FROM webhook_endpoints w
            LEFT JOIN employees e ON e.id = w.created_by
            WHERE w.tenant_id = %s
            ORDER BY w.is_active DESC, w.event_type, w.target_url
            """,
            (self._tenant,),
        )
        return [_view_of(row) for row in rows]

    def add(
        self,
        tenant_id: TenantId,
        *,
        event_type: str,
        target_url: str,
        secret: str,
        created_by: EmployeeId,
        at: datetime,
    ) -> WebhookEndpointView:
        """UPSERT — TƏKRAR QEYDİYYAT SƏTRİ ARTIRMIR, MÖVCUDU YENİLƏYİR.

        Unikal açar `(tenant_id, event_type, target_url)`-dır. `ON CONFLICT`
        olmasaydı, Root eyni hədəfi ikinci dəfə əlavə edəndə (məs. açarı
        dəyişmək üçün) DB pozuntusu qayıdardı və yeganə çıxış yolu sətri
        silmək olardı — halbuki bu modul silmir (bax use case başlığı).
        Təkrar qeydiyyat indi «açarı yenilə + yenidən aktivləşdir» mənasını
        verir, ki bu da istifadəçinin niyyətidir.

        `created_at` YENİLƏNMİR: sətrin İLK yaranma anı tarixi faktdır.
        """
        sealed = self._encryption.encrypt(secret, context=_context_of(self._tenant))
        row = self._fetch_one(
            """
            INSERT INTO webhook_endpoints
                (tenant_id, event_type, target_url, secret_encrypted,
                 is_active, created_by, created_at)
            VALUES (%s, %s, %s, %s, TRUE, %s, %s)
            ON CONFLICT (tenant_id, event_type, target_url)
            DO UPDATE SET secret_encrypted = EXCLUDED.secret_encrypted,
                          is_active        = TRUE
            RETURNING id, event_type, target_url, is_active, created_at
            """,
            (self._tenant, event_type, target_url, sealed, created_by, at),
        )
        if not row:  # pragma: no cover — `RETURNING` həmişə sətir verir
            raise RuntimeError("webhook_endpoints INSERT nəticə vermədi")
        return _view_of(row)

    def set_active(self, tenant_id: TenantId, *, endpoint_id: str, is_active: bool) -> bool:
        """Açır/söndürür. Sətir yoxdursa `False` — use case «tapılmadı» deyir.

        `%s::uuid` AÇIQ ÇEVİRMƏDİR: `endpoint_id` ekran siqnalından MƏTN kimi
        gəlir (Qt siqnalı `dict[str, object]` daşıyır) və mətn parametri UUID
        sütunu ilə birbaşa müqayisə edilə bilmir. Yararsız mətn burada
        `DataError` verir — o da `False` deyil, XƏTA olaraq görünməlidir,
        çünki «tapılmadı» ilə «formatı pozuq» fərqli qüsurlardır
        (`report_repositories.py`-dakı eyni çevirmə naxışı).
        """
        row = self._fetch_one(
            """
            UPDATE webhook_endpoints
               SET is_active = %s
             WHERE id = %s::uuid AND tenant_id = %s
            RETURNING id
            """,
            (is_active, endpoint_id, self._tenant),
        )
        return bool(row)


__all__ = ["PostgresWebhookEndpointRepository"]
