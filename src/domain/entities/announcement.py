"""Elan (Broadcast) aqreqatı (#19, kompasos11.md Faza 8) — `announcements`.

`migrations/020` başlığı ilə EYNİ əsaslandırma: fiziki `DELETE` YOXDUR —
işçilər elanı artıq görmüş ola bilər və "belə göstəriş heç vaxt olmayıb"
vəziyyəti mübahisədə zərərlidir. Geri çəkmə (`withdraw`) YENİ görüntülənməni
dayandırır, tarixi sətri yox.

──────────────────────────────────────────────────────────────────────────────
BU, DƏSTƏK ÇATI DEYİL — BİR-TƏRƏFLİDİR
──────────────────────────────────────────────────────────────────────────────
`SupportChatUseCase`/`support_chat.py` işçi ilə admin arasında İKİ-TƏRƏFLİ,
mesaj-mesaja yazışmadır (cavab, oxunma statusu, thread). Elan isə əksinədir:
BİR müəllif, ÇOX oxucu, CAVAB YOXDUR. Bu aqreqatda REPLY/THREAD/REACTION
sahəsi YOXDUR və ƏLAVƏ EDİLMİR — bu, spesifikasiyanın açıq tələbidir
(kompasos11.md Faza 8: "dəstək çat-dən FƏRQLİ, bir-tərəflidir, cavab yoxdur").

──────────────────────────────────────────────────────────────────────────────
ƏHATƏ (`scope`) ZİDDİYYƏTİ NİYƏ BURADA DA YOXLANIR (DB trigger-i ARTIQ VAR)
──────────────────────────────────────────────────────────────────────────────
`migrations/020`-dəki `enforce_announcement_target_scope()` yalnız
`announcement_targets`-ə YANLIŞ sətir yazılmasının qarşısını alır (ALL elana
hədəf ƏLAVƏ olunmasın). O, ƏKS tərəfi — "STORE_LIST-in ən azı bir hədəfi
olmalıdır" — MƏCBUR ETMİR (miqrasiya başlığı: bunu DEFERRABLE trigger ilə
etmək elanı hədəflərdən ƏVVƏL yazan hər normal axını sındırardı). Ona görə bu
qayda BURADA, konstruktorda yoxlanılır — "əhatə" strukturun invariantıdır,
istənilən çağıran (use case, gələcək skript) ona tabe olmalıdır.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Final

from src.domain.entities.base import AggregateRoot, DomainRuleError, InvalidStateTransitionError
from src.domain.events import AnnouncementBroadcastEvent
from src.domain.value_objects.identifiers import AnnouncementId, EmployeeId, StoreId, TenantId
from src.domain.value_objects.scheduling import require_aware

#: `announcements.title_az` CHECK-inin güzgüsü (migrations/020: `>= 3`).
MIN_TITLE_LENGTH: Final = 3
#: `announcements.message` CHECK-inin güzgüsü (migrations/020: `>= 5`).
MIN_MESSAGE_LENGTH: Final = 5


class AnnouncementScope(str, Enum):
    """`announcements.scope` — DB `CHECK`-i ilə EYNİ iki dəyər."""

    ALL = "ALL"
    STORE_LIST = "STORE_LIST"


@dataclass(frozen=True)
class AnnouncementDraft:
    """Yeni elan formasının məzmunu — use case bunu entity-yə çevirir."""

    title_az: str
    message: str
    scope: AnnouncementScope
    store_ids: frozenset[StoreId]


class Announcement(AggregateRoot):
    """Bir elan sətri (`announcements`) + hədəf mağaza dəsti."""

    def __init__(
        self,
        *,
        announcement_id: AnnouncementId,
        tenant_id: TenantId,
        created_by: EmployeeId,
        title_az: str,
        message: str,
        scope: AnnouncementScope,
        target_store_ids: frozenset[StoreId],
        created_at: datetime,
        updated_at: datetime,
        is_active: bool = True,
        deactivated_at: datetime | None = None,
        deactivated_by: EmployeeId | None = None,
        emit_created_event: bool = True,
    ) -> None:
        super().__init__()
        cleaned_title = title_az.strip()
        if len(cleaned_title) < MIN_TITLE_LENGTH:
            raise DomainRuleError(
                f"Elan başlığı minimum {MIN_TITLE_LENGTH} simvol olmalıdır",
                user_message="Başlığı ətraflı yazın.",
                context={"title_az": title_az},
            )
        # Çoxsaylı boşluqlar bir boşluğa endirilir — `EmployeeDocument.deactivate`
        # ilə eyni normallaşdırma (yalnız boşluqla doldurulmuş mətn keçməsin).
        cleaned_message = " ".join(message.split())
        if len(cleaned_message) < MIN_MESSAGE_LENGTH:
            raise DomainRuleError(
                f"Elan mətni minimum {MIN_MESSAGE_LENGTH} simvol olmalıdır",
                user_message="Elan mətnini ətraflı yazın.",
                context={"message": message},
            )
        # ƏHATƏ ZİDDİYYƏTİ — modul başlığındakı izah: DB trigger-i yalnız
        # YARIM qaydanı tutur, digər yarısı burada məcburidir.
        if scope is AnnouncementScope.STORE_LIST and not target_store_ids:
            raise DomainRuleError(
                "STORE_LIST əhatəsi ən azı bir mağaza tələb edir",
                user_message="Ən azı bir mağaza seçin.",
                context={"announcement_id": str(announcement_id)},
            )
        if scope is AnnouncementScope.ALL and target_store_ids:
            raise DomainRuleError(
                "ALL əhatəsinə mağaza hədəfi əlavə edilə bilməz",
                user_message="Bütün mağazalar seçildikdə ayrıca mağaza siyahısı olmamalıdır.",
                context={"announcement_id": str(announcement_id)},
            )
        # `chk_announcement_deactivation` güzgüsü (migrations/020).
        if not is_active and (deactivated_at is None or deactivated_by is None):
            raise DomainRuleError(
                "Geri çəkilmiş elan geri çəkilmə anını və şəxsini tələb edir",
                user_message="Elan qeydi natamamdır.",
                context={"announcement_id": str(announcement_id)},
            )

        self.id = announcement_id
        self.tenant_id = tenant_id
        self.created_by = created_by
        self.title_az = cleaned_title
        self.message = cleaned_message
        self.scope = scope
        self.target_store_ids = frozenset(target_store_ids)
        self.created_at = require_aware(created_at, field="created_at")
        self.updated_at = require_aware(updated_at, field="updated_at")
        self.is_active = is_active
        self.deactivated_at = (
            require_aware(deactivated_at, field="deactivated_at")
            if deactivated_at is not None
            else None
        )
        self.deactivated_by = deactivated_by

        # Repository-dən BƏRPA hadisə YAYMIR — əks halda hər siyahı oxunuşu
        # "yeni elan dərc olundu" bildirişi doğurardı (`EmployeeDocument`
        # ilə eyni qoruma, bax `emit_created_event` şərhi).
        if emit_created_event:
            self.record_event(
                AnnouncementBroadcastEvent(
                    tenant_id=tenant_id,
                    actor_id=created_by,
                    announcement_id=announcement_id,
                    scope=scope.value,
                    store_count=len(self.target_store_ids),
                )
            )

    # ------------------------------ oxu köməkçiləri --------------------------- #

    def visible_to_store(self, store_id: StoreId | None) -> bool:
        """Store-scoping qaydası: `ALL` HƏMİŞƏ görünür, `STORE_LIST` yalnız hədəfə uyğunsa.

        `store_id=None` (mərkəzi ofis rolu, mağazası təyin edilməyib) —
        `STORE_LIST` elanları GİZLƏNİR, `ALL` isə YENƏ görünür: "bütün
        mağazalar" ifadəsi mağazası olmayan işçini istisna etmir.
        """
        if self.scope is AnnouncementScope.ALL:
            return True
        return store_id is not None and store_id in self.target_store_ids

    def is_within_visibility_window(self, *, now: datetime, visibility_days: int) -> bool:
        """ROOT parametri `ANNOUNCEMENT_VISIBILITY_DAYS` — köhnə elan avtomatik gizlənir.

        Bu, `is_active`-dan MÜSTƏQİL bir ölçüdür: sətir SİLİNMİR/deaktiv
        EDİLMİR, yalnız YENİ görüntülənmə dayanır (modul başlığındakı soft
        delete ilə eyni ruh — geri çəkmə tarixi sübutu yox etmir).
        `visibility_days <= 0` — sərhədsiz görüntülənmə (Root limiti sıfırlasa
        belə sistem çökməməlidir).
        """
        aware_now = require_aware(now, field="now")
        if visibility_days <= 0:
            return True
        return self.created_at + timedelta(days=visibility_days) > aware_now

    # -------------------------------- yazı yolu -------------------------------- #

    def withdraw(self, *, deactivated_by: EmployeeId, now: datetime) -> None:
        """Admin elanı geri çəkir — sətir SİLİNMİR (modul başlığı)."""
        if not self.is_active:
            raise InvalidStateTransitionError(
                "Bu elan artıq geri çəkilib",
                user_message="Bu elan artıq geri çəkilib.",
                context={"announcement_id": str(self.id)},
            )
        aware_now = require_aware(now, field="now")
        self.is_active = False
        self.deactivated_at = aware_now
        self.deactivated_by = deactivated_by
        self.updated_at = aware_now

    # -------------------------------- audit ------------------------------------ #

    def to_audit_state(self) -> dict[str, object]:
        return {
            "title_az": self.title_az,
            "scope": self.scope.value,
            "store_count": len(self.target_store_ids),
            "is_active": self.is_active,
        }

    def __repr__(self) -> str:
        return (
            f"Announcement(id={self.id}, scope={self.scope.value}, "
            f"stores={len(self.target_store_ids)}, active={self.is_active})"
        )


__all__ = [
    "MIN_MESSAGE_LENGTH",
    "MIN_TITLE_LENGTH",
    "Announcement",
    "AnnouncementDraft",
    "AnnouncementScope",
]
