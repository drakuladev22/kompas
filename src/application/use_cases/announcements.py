"""Elan (Broadcast) — #19, kompasos11.md Faza 8.

`can_broadcast_announcements` sahibi mesaj yazır, əhatə seçir (bütün / seçilmiş
mağazalar). CLAUDE.md §6 use case naxışı: səlahiyyət → domen qaydası
(entity-də) → yazma → audit ardıcıllığı.

──────────────────────────────────────────────────────────────────────────────
STORE-SCOPING — MÖVCUD NAXIŞ TƏKRAR İSTİFADƏ OLUNUR, YENİDƏN QURULMUR
──────────────────────────────────────────────────────────────────────────────
`list_for_employee` `OpenShiftMarketUseCase.list_for_employee`-nin EYNİ
prinsipini işlədir: işçinin ÖZ `store_id`-si ilə süzgəc, `store_id is None`
olduqda FAIL-CLOSED (mağazası olmayan işçi `STORE_LIST` elanlarını görmür —
bax `Announcement.visible_to_store`). Fərq YALNIZ ondadır ki, elan `ALL`
əhatəsi ilə DƏ verilə bilər — bu halda mağaza yoxluğu maneə DEYİL, çünki
"bütün mağazalar" ifadəsi mərkəzi ofis rolunu da əhatə edir.

──────────────────────────────────────────────────────────────────────────────
BU, DƏSTƏK ÇATI DEYİL — CAVAB/THREAD/REAKSİYA YOXDUR
──────────────────────────────────────────────────────────────────────────────
kompasos11.md Faza 8-in açıq tələbi: "dəstək çat-dən FƏRQLİ, bir-tərəflidir,
cavab yoxdur". Bu use case-də `reply`/`mark_read`/`react` metodu YOXDUR və
ƏLAVƏ EDİLMİR — bu, scope pozuntusu olardı. Mövcud `SupportChatUseCase`
(`application/use_cases/support_chat.py`) bu fayldan çağırılmır və
genişləndirilmir; ikisi tamamilə ayrı axındır.

──────────────────────────────────────────────────────────────────────────────
BİLDİRİŞ (`Notifier`) NİYƏ İŞLƏDİLMİR
──────────────────────────────────────────────────────────────────────────────
`TENANT_NOTIFICATION_AUDIENCE` (`domain/value_objects/notifications.py`)
auditoriyanı YALNIZ icazə FLAG-i üzrə süzür — MAĞAZA üzrə süzgəc YOXDUR.
Elanı `notifier.notify(recipient_id=None, ...)` ilə göndərsək, ya BÜTÜN uyğun
işçilər mağazadan asılı olmadan görərdi, ya da hər mağaza üçün AYRI sətir
yazmaq lazım gələrdi — məhz `migrations/020`-in rədd etdiyi "100 nüsxə"
naxışının təkrarı (bax miqrasiya başlığı: "elanın MƏTNİ hər alıcı üçün
təkrarlanardı"). Ona görə çatdırılma YALNIZ bu cədvəlin ÖZÜ üzərindən,
store-scoping sorğusu ilə həll olunur; `Notifier` bu faylda İSTİFADƏ OLUNMUR.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from src.domain.entities.announcement import Announcement
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.authorization import AuthorizationError
from src.domain.value_objects.identifiers import new_announcement_id
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.announcement import AnnouncementDraft
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AnnouncementRepository,
        AuditTrail,
        Clock,
        SystemLimits,
    )
    from src.domain.value_objects.identifiers import AnnouncementId, TenantId

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Faza 2-də kataloqa əlavə edilmiş flag (migrations/021).
BROADCAST_ANNOUNCEMENTS_FLAG = "can_broadcast_announcements"

#: FALLBACK — həqiqi mənbə `system_limits.ANNOUNCEMENT_VISIBILITY_DAYS`
#: (migrations/029 seed edir) — bax `policies.py`.
_FALLBACK_VISIBILITY_DAYS: Final = int(DEFAULT_LIMITS[SystemLimitKey.ANNOUNCEMENT_VISIBILITY_DAYS])

#: FALLBACK — həqiqi mənbə `system_limits.ANNOUNCEMENT_LIST_PAGE_SIZE`
#: (migrations/034 seed edir). Admin siyahısının uzunluğu görüntülənmə
#: pəncərəsindən (`ANNOUNCEMENT_VISIBILITY_DAYS`) MÜSTƏQİL parametrdir:
#: yayımlanan elan pəncərədən çıxsa da siyahıda qalır (geri çəkilməyib) və
#: admin arxivi görmək istəyə bilər.
_FALLBACK_LIST_PAGE_SIZE: Final = int(DEFAULT_LIMITS[SystemLimitKey.ANNOUNCEMENT_LIST_PAGE_SIZE])

#: Görüntülənmə həddi söndürülüb (`<= 0`) olduqda SQL süzgəcinin aşağı sərhədi
#: — real `datetime.min` istifadə etmək DB tərəfində indeks axtarışını
#: pozmur, çünki `created_at` sütunu HƏMİŞƏ bundan sonrakı tarixdədir.
_UNBOUNDED_SINCE: Final = datetime.min.replace(tzinfo=UTC)


class AnnouncementError(KompasOSError):
    """Elan əməliyyatı yerinə yetirilə bilmədi."""

    user_message = "Elan əməliyyatı icra edilə bilmədi."


class AnnouncementNotFoundError(AnnouncementError):
    user_message = "Bu elan tapılmadı."


@dataclass(frozen=True)
class AnnouncementView:
    """Ekranların oxuduğu düz görünüş (admin siyahısı və İşçi Ana Ekranı)."""

    announcement_id: AnnouncementId
    title_az: str
    message: str
    scope: str
    store_ids: tuple[str, ...]
    created_at: datetime
    is_active: bool


class AnnouncementUseCase:
    """`can_broadcast_announcements` sahibi elan yazır/geri çəkir/oxuyur."""

    def __init__(
        self,
        *,
        announcements: AnnouncementRepository,
        limits: SystemLimits,
        audit: AuditTrail,
        clock: Clock,
    ) -> None:
        self._announcements = announcements
        self._limits = limits
        self._audit = audit
        self._clock = clock

    # -------------------------------- admin ------------------------------------ #

    def broadcast(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        draft: AnnouncementDraft,
    ) -> Announcement:
        """`[Yayımla]` — yeni elan yaradır (redaktə YOXDUR, yalnız geri çəkmə)."""
        self._require_permission(actor, tenant_id)
        now = self._clock.now()
        announcement = Announcement(
            announcement_id=new_announcement_id(),
            tenant_id=tenant_id,
            created_by=actor.id,
            title_az=draft.title_az,
            message=draft.message,
            scope=draft.scope,
            target_store_ids=draft.store_ids,
            created_at=now,
            updated_at=now,
        )
        self._announcements.post(announcement)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="ANNOUNCEMENT_BROADCAST",
            entity_type="announcements",
            entity_id=announcement.id,
            before_state=None,
            after_state=announcement.to_audit_state(),
        )
        return announcement

    def withdraw(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        announcement_id: AnnouncementId,
    ) -> Announcement:
        """`[Geri Çək]` — soft delete, sətir SİLİNMİR (`Announcement.withdraw` başlığı)."""
        self._require_permission(actor, tenant_id)
        announcement = self._require_announcement(tenant_id, announcement_id)
        before_state = announcement.to_audit_state()
        now = self._clock.now()
        # Domen qaydası ƏVVƏLCƏ yoxlanılır (artıq geri çəkilibsə aydın mesaj
        # verir) — DB-yə yararsız sorğu göndərməmək üçün.
        announcement.withdraw(deactivated_by=actor.id, now=now)
        applied = self._announcements.withdraw(
            tenant_id=tenant_id,
            announcement_id=announcement_id,
            deactivated_by=actor.id,
            deactivated_at=now,
        )
        if not applied:
            # Kilid olmadığı üçün nəzəri yarış mümkündür: iki admin eyni anda
            # geri çəkməyə çalışsa, ŞƏRTLİ UPDATE ikincini aydın xəbərdar edir.
            raise AnnouncementError(
                "Elan geri çəkilmədən əvvəl başqası tərəfindən geri çəkilib",
                user_message="Bu elan artıq geri çəkilib.",
                context={"announcement_id": str(announcement_id)},
            )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="ANNOUNCEMENT_WITHDRAWN",
            entity_type="announcements",
            entity_id=announcement.id,
            before_state=before_state,
            after_state=announcement.to_audit_state(),
        )
        return announcement

    def list_recent(
        self, *, tenant_id: TenantId, actor: Employee, limit: int | None = None
    ) -> list[AnnouncementView]:
        """Admin panelinin siyahısı — YARADAN görür, əhatədən ASILI OLMADAN.

        `limit=None` → ROOT parametri (`ANNOUNCEMENT_LIST_PAGE_SIZE`); açıq
        arqument onu əvəz edir (ekranın "daha çox göstər" vəziyyəti).
        """
        self._require_permission(actor, tenant_id)
        applied = self._list_page_size(tenant_id) if limit is None else limit
        return [
            _to_view(item) for item in self._announcements.list_recent(tenant_id, limit=applied)
        ]

    # -------------------------------- işçi ------------------------------------- #

    def list_for_employee(
        self, *, tenant_id: TenantId, employee: Employee
    ) -> list[AnnouncementView]:
        """İşçi Ana Ekranının "Elanlar" kartı.

        SƏLAHİYYƏT FLAG-İ TƏLƏB OLUNMUR — bu, işçinin öz ekranıdır
        (`OpenShiftMarketUseCase.list_for_employee` ilə eyni qərar: elanı
        görmək bir idarəetmə əməliyyatı deyil).
        """
        now = self._clock.now()
        visibility_days = self._visibility_days(tenant_id)
        created_after = (
            now - timedelta(days=visibility_days) if visibility_days > 0 else _UNBOUNDED_SINCE
        )
        rows = self._announcements.list_visible_for_store(
            tenant_id, employee.store_id, created_after=created_after
        )
        # İKİNCİ QAT: SQL-in özü artıq süzüb, lakin domen qaydası BURADA da
        # yoxlanılır (`CLAUDE.md` bölmə 6 — repo-suz istifadədə də etibarlı
        # qalması üçün, `OpenShiftPosting.claim` ilə eyni "iki qat" fəlsəfəsi).
        return [
            _to_view(item)
            for item in rows
            if item.visible_to_store(employee.store_id)
            and item.is_within_visibility_window(now=now, visibility_days=visibility_days)
        ]

    # ------------------------------- köməkçi ------------------------------------ #

    def _require_permission(self, actor: Employee, tenant_id: TenantId) -> None:
        if actor.tenant_id != tenant_id:
            # Üçüncü izolyasiya qatı (RLS və repo `tenant_id` şərtindən sonra).
            raise AuthorizationError(
                "Aktor bu kirayəçiyə aid deyil",
                context={"actor_id": str(actor.id)},
            )
        now = self._clock.now()
        if not actor.has_permission(BROADCAST_ANNOUNCEMENTS_FLAG, now=now):
            _security_log.warning(
                "ANNOUNCEMENT_PERMISSION_DENIED",
                extra={"actor_id": str(actor.id), "flag": BROADCAST_ANNOUNCEMENTS_FLAG},
            )
            raise AuthorizationError(
                f"«{BROADCAST_ANNOUNCEMENTS_FLAG}» səlahiyyəti yoxdur",
                context={"flag": BROADCAST_ANNOUNCEMENTS_FLAG},
            )

    def _require_announcement(
        self, tenant_id: TenantId, announcement_id: AnnouncementId
    ) -> Announcement:
        announcement = self._announcements.get(tenant_id, announcement_id)
        if announcement is None:
            raise AnnouncementNotFoundError(
                "Elan tapılmadı", context={"announcement_id": str(announcement_id)}
            )
        return announcement

    def _visibility_days(self, tenant_id: TenantId) -> int:
        """ROOT limiti — mənbə `system_limits`, sinifdəki sabit yalnız fallback."""
        value = self._limits.get_int(
            tenant_id, SystemLimitKey.ANNOUNCEMENT_VISIBILITY_DAYS.value, _FALLBACK_VISIBILITY_DAYS
        )
        return value if value >= 0 else _FALLBACK_VISIBILITY_DAYS

    def _list_page_size(self, tenant_id: TenantId) -> int:
        """ROOT limiti — mənbə `system_limits`, sinifdəki sabit yalnız fallback.

        `<= 0` dəyər fallback-a qaytarılır: sıfır səhifə ölçüsü siyahını HƏMİŞƏ
        boş göstərərdi və admin "elan yoxdur" ilə "limit sıfırdır" arasındakı
        fərqi ekranda görə bilməzdi.
        """
        value = self._limits.get_int(
            tenant_id, SystemLimitKey.ANNOUNCEMENT_LIST_PAGE_SIZE.value, _FALLBACK_LIST_PAGE_SIZE
        )
        return value if value > 0 else _FALLBACK_LIST_PAGE_SIZE


def _to_view(announcement: Announcement) -> AnnouncementView:
    return AnnouncementView(
        announcement_id=announcement.id,
        title_az=announcement.title_az,
        message=announcement.message,
        scope=announcement.scope.value,
        store_ids=tuple(str(store_id) for store_id in announcement.target_store_ids),
        created_at=announcement.created_at,
        is_active=announcement.is_active,
    )


__all__ = [
    "BROADCAST_ANNOUNCEMENTS_FLAG",
    "AnnouncementError",
    "AnnouncementNotFoundError",
    "AnnouncementUseCase",
    "AnnouncementView",
]
