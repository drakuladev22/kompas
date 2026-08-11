"""Bildiriş panelinin OXU/oxundu-işarəsi repository-si (bölmə 7) — Faza 5/6.

──────────────────────────────────────────────────────────────────────────────
YAZI TƏRƏFİ BURADA DEYİL
──────────────────────────────────────────────────────────────────────────────
`notifications` sətrini `infrastructure/notifications/notifier.py` yaradır və o,
QƏSDƏN öz tranzaksiyasını açır ("outbox" naxışı: in-app bildiriş e-poçtdan
əvvəl commit olunur). Bu fayl isə YALNIZ oxu və "oxundu" işarəsidir və
istifadəçinin öz sessiyasında (`PostgresUnitOfWork`) işləyir — beləliklə panel
sorğusu RLS + açıq `tenant_id` şərti ilə qorunur (defense-in-depth, bax
`repositories.py` başlığı).

──────────────────────────────────────────────────────────────────────────────
KİMİN BİLDİRİŞİ GÖRÜNÜR
──────────────────────────────────────────────────────────────────────────────
Sətirlərin bir hissəsi konkret işçiyə ünvanlanıb (`recipient_id = <işçi>`), bir
hissəsi isə TENANT səviyyəsindədir (`recipient_id IS NULL`) — məs. "giriş
təsdiqi gecikir", "ödəniş xatırlatması". İkinci qrup use case-lərdə açıq
şərhlərlə belə yazılıb ("HR_Admin + Store Manager", "bütün adminlərə").

Panel HƏR İKİ NÖVÜ göstərir — şəxsi sətir HƏMİŞƏ, tenant səviyyəli sətir isə
AUDİTORİYASINA görə. Alternativ — yalnız şəxsi sətirləri göstərmək — rədd
edildi, çünki tenant səviyyəli bildirişlər tətbiq daxilində HEÇ KİMƏ
görünməzdi; bölmə 7 isə məhz onları "tətbiq daxilində göstərilir + e-poçt
ehtiyat kanalı" kimi təsvir edir.

Auditoriya cədvəli BURADA DEYİL, domendədir
(`value_objects/notifications.TENANT_NOTIFICATION_AUDIENCE`): "kim görməlidir"
iş qaydasıdır, SQL detalı deyil, və eyni sual gələcəkdə e-poçt marşrutunda da
veriləcək. Bu qat yalnız hazır dəsti şərtə çevirir. Cədvəldə olmayan
kateqoriya ƏVVƏLKİ KİMİ hamıya görünür (fail-open) — yeni modulun bildirişi
sükutla itməməlidir.

──────────────────────────────────────────────────────────────────────────────
"OXUNDU" SƏTRİN ÖZ SAHƏSİDİR, İSTİFADƏÇİ-BİLDİRİŞ CÜTÜNÜN YOX
──────────────────────────────────────────────────────────────────────────────
Sxemdə `read_at` bildiriş SƏTRİNDƏDİR (`schema.sql` §17), ayrıca
`notification_reads` cədvəli yoxdur. Deməli tenant səviyyəli bildirişi bir
admin oxuduqda o, hamı üçün oxunmuş sayılır. Bu, mövcud sxemin birbaşa
nəticəsidir; per-istifadəçi oxunma vəziyyəti YENİ cədvəl tələb edərdi və o,
sənədləşdirilməmiş bir qərar olardı.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from uuid import UUID

    from src.domain.value_objects.identifiers import EmployeeId

#: Panelin bir dəfəyə oxuduğu maksimum sətir. Bu, biznes HƏDDİ deyil — ekran
#: 620px hündürlükdədir və 50-dən sonrası onsuz da sürüşdürmə ilə açılmır.
#: Ona görə `system_limits`-də açarı YOXDUR (eyni məntiq `app.py`-dakı
#: `UPLOAD_POLL_INTERVAL_MS` üçün də seçilib).
PANEL_LIMIT = 50


@dataclass(frozen=True, slots=True)
class NotificationRow:
    """`notifications` sətrinin panelə lazım olan hissəsi.

    Domen entity-si DEYİL: bildirişin heç bir iş qaydası, keçidi və ya
    invariantı yoxdur — o, yazılan və oxunan bir qeyddir. Süni `Notification`
    entity-si yaratmaq domen qatını məzmunsuz bir siniflə yükləyərdi.
    """

    id: UUID
    category: str
    title_az: str
    body_az: str
    is_critical: bool
    created_at: datetime
    read_at: datetime | None

    @property
    def is_unread(self) -> bool:
        return self.read_at is None


class PostgresNotificationRepository(_BaseRepository):
    """Header zəngi + bildiriş panelinin məlumat mənbəyi."""

    _SELECT = """
        SELECT id, category, title_az, body_az, is_critical, created_at, read_at
        FROM notifications
    """

    #: Şəxsi sətir HƏMİŞƏ, tenant səviyyəli sətir isə auditoriyaya görə.
    #:
    #: Şərt "görünənlər" yox, "GİZLƏDİLƏNLƏR" üzərində qurulub (`<> ALL`):
    #: siyahıya salınmamış kateqoriya belə görünməyə davam edir. Tərsi
    #: (`= ANY(görünənlər)`) yeni kateqoriyanı domen cədvəlinə yazılana qədər
    #: sükutla gizlədərdi — bölmə 7-nin "gözdən qaçmasın" məqsədinin əksi.
    #:
    #: `::text[]` çevirməsi BOŞ siyahı üçün lazımdır: parametr boş massiv
    #: olduqda server tipi təyin edə bilmir və sorğu xəta verərdi.
    _AUDIENCE = "(recipient_id = %s OR (recipient_id IS NULL AND category <> ALL(%s::text[])))"

    def list_for_recipient(
        self,
        recipient_id: EmployeeId,
        *,
        hidden_categories: Sequence[str],
        limit: int = PANEL_LIMIT,
    ) -> list[NotificationRow]:
        """Ən yeni bildirişlər — oxunmuşlar da daxil.

        Oxunmuşlar SÜZÜLMÜR: panel onları solğun sətir kimi göstərir və
        istifadəçi "bayaq nə yazılmışdı" sualına cavab tapmalıdır. Yalnız
        oxunmamışları göstərsəydik, panel klikdən sonra boşalardı.

        Args:
            hidden_categories: Aktorun səlahiyyəti çatmayan tenant səviyyəli
                kateqoriyalar (`hidden_tenant_categories()` nəticəsi).
                Arqument MƏCBURİDİR və defolt dəyəri YOXDUR: defolt boş dəst
                olsaydı, çağırışı unutmaq süzgəci sükutla söndürərdi və qüsur
                yalnız istehsalatda görünərdi.
        """
        rows = self._fetch_all(
            f"""{self._SELECT}
            WHERE tenant_id = %s AND {self._AUDIENCE}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (self._tenant, recipient_id, list(hidden_categories), limit),
        )
        return [_hydrate(row) for row in rows]

    def mark_read(
        self, notification_id: UUID, recipient_id: EmployeeId, *, hidden_categories: Sequence[str]
    ) -> int:
        """Bir sətri oxunmuş edir. Qaytarır: dəyişən sətir sayı.

        `read_at IS NULL` şərti QƏSDƏNDİR: eyni sətrə ikinci klik ilk oxunma
        vaxtını sürüşdürməməlidir — "nə vaxt görüldü" sualının cavabı ilk
        baxışdır.

        Auditoriya şərti burada da var: `read_at` sətrin ÖZ sahəsidir (ayrıca
        `notification_reads` cədvəli yoxdur — bax modul başlığı), yəni
        görmədiyi sətri "oxundu" edən istifadəçi onu HƏQİQİ auditoriyanın
        gözündən də silərdi.
        """
        return self._execute(
            f"""
            UPDATE notifications SET read_at = now()
             WHERE id = %s AND tenant_id = %s AND read_at IS NULL AND {self._AUDIENCE}
            """,  # noqa: S608 — şərtlər sabit siyahıdandır
            (notification_id, self._tenant, recipient_id, list(hidden_categories)),
        )

    def mark_all_read(self, recipient_id: EmployeeId, *, hidden_categories: Sequence[str]) -> int:
        """«Hamısını oxunmuş et» — yalnız GÖRÜNƏN auditoriya üçün.

        Şərt `list_for_recipient` ilə eynidir: istifadəçi görmədiyi bir
        bildirişi "oxudum" edə bilməz.
        """
        return self._execute(
            f"""
            UPDATE notifications SET read_at = now()
             WHERE tenant_id = %s AND read_at IS NULL AND {self._AUDIENCE}
            """,  # noqa: S608 — şərtlər sabit siyahıdandır
            (self._tenant, recipient_id, list(hidden_categories)),
        )


def _hydrate(row: dict[str, Any]) -> NotificationRow:
    return NotificationRow(
        id=row["id"],
        category=str(row["category"]),
        title_az=str(row["title_az"]),
        body_az=str(row["body_az"]),
        is_critical=bool(row["is_critical"]),
        created_at=row["created_at"],
        read_at=row["read_at"],
    )


__all__ = ["PANEL_LIMIT", "NotificationRow", "PostgresNotificationRepository"]
