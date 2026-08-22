"""POS Səlahiyyət Siyasəti aqreqatı (#7, `pos_permission_thresholds`) — Faza 4.

kompasos11.md struktur qərarı A: bu, YALNIZ sənədləşdirmə/siyasət qeydidir —
"bu işçiyə hansı endirim/ləğv/geri-qaytarma səlahiyyəti rəsmən verilib?"
sualının HR/audit cavabı. KompasOS-un öz kassa ekranı yoxdur, bu aqreqat heç
bir POS əməliyyatını yoxlamır, 1C-yə bağlı deyil və Vahid İstisna Motoruna
(#9) heç nə göndərmir — motor bu mənbəni ÜMUMİYYƏTLƏ tanımır (bax
`exception_engine.py` başlığı, struktur qərar A).

──────────────────────────────────────────────────────────────────────────────
NİYƏ İKİ AYRI HƏDD VAR: `MAX_DISCOUNT_PCT_HARD_CEILING` VƏ `ceiling_pct`
──────────────────────────────────────────────────────────────────────────────
`pos_permission_thresholds.max_discount_pct` sütununun DB `CHECK`-i 0–100
arasındadır (migrations/018) — bu, SXEM sərhədidir, dəyişməsi miqrasiya
tələb edir və domendə HEÇ VAXT yumşalmır (`MAX_DISCOUNT_PCT_HARD_CEILING`).

Bundan aşağı, Root ÖZ biznes siyasətini tətbiq edə bilər (məsələn "heç bir
işçiyə 40%-dən artıq endirim səlahiyyəti verilməsin") —
`system_limits.POS_MAX_DISCOUNT_PCT_CEILING` ilə (bölmə 3, defolt 100, yəni
sxem sərhədi ilə eyni — başlanğıcda əlavə məhdudiyyət yoxdur). Bu ikinci hədd
YALNIZ `set_threshold()`-da yoxlanır — repository-dən BƏRPA zamanı (`__init__`)
YOX, çünki Root sabah həddi aşağı salsa, DÜNƏNKİ qeydlər geriyə dönük
etibarsız/çökən olmamalıdır (bölmə 3-ün "Feature Toggle retroaktiv təsir
etmir" prinsipi ilə eyni məntiq: konfiqurasiya dəyişikliyi mövcud sətirləri
pozmur, yalnız YENİ yazını məhdudlaşdırır).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final

from src.domain.entities.base import (
    AggregateRoot,
    DomainRuleError,
    InvalidStateTransitionError,
)
from src.domain.value_objects.identifiers import EmployeeId, PosThresholdId, TenantId
from src.domain.value_objects.scheduling import require_aware
from src.shared.text import normalise_decision_text

#: `pos_permission_thresholds.max_discount_pct` CHECK-inin güzgüsü (sxem
#: sərhədi — migrations/018). ROOT-dan DƏYİŞMİR; dəyişmək miqrasiya tələb edir.
MAX_DISCOUNT_PCT_HARD_CEILING: Final = Decimal("100")
MIN_DISCOUNT_PCT: Final = Decimal("0")

#: `POS_MAX_DISCOUNT_PCT_CEILING` üçün FALLBACK. HƏQİQİ MƏNBƏ
#: `system_limits`-dir (Root dəyişdirir) — bax `policies.py`. Bu sabit yalnız
#: hədd ötürülməyən yollar (məs. birbaşa domen çağırışı) üçündür.
DEFAULT_DISCOUNT_PCT_CEILING: Final = Decimal("100")


class POSPermissionThreshold(AggregateRoot):
    """İşçinin rəsmi POS icazə həddi — bir işçiyə bir diri sətir (UPSERT)."""

    def __init__(
        self,
        *,
        threshold_id: PosThresholdId,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        max_discount_pct: Decimal,
        can_void: bool,
        can_refund: bool,
        note: str | None,
        updated_by: EmployeeId | None,
        created_at: datetime,
        updated_at: datetime,
        is_active: bool = True,
        deactivated_at: datetime | None = None,
        deactivated_by: EmployeeId | None = None,
    ) -> None:
        super().__init__()
        # Sxem sərhədi HƏMİŞƏ yoxlanır — bərpa zamanı da, çünki miqrasiyadan
        # kənar (əl ilə) yazılmış yararsız sətir sükutla qəbul edilməməlidir.
        _require_hard_bounds(max_discount_pct)
        # `chk_pos_threshold_deactivation` güzgüsü (migrations/018): geri
        # alınmış sətir kim/nə vaxt sualını CAVABSIZ buraxa bilməz.
        if not is_active and (deactivated_at is None or deactivated_by is None):
            raise DomainRuleError(
                "Geri alınmış POS həddi deaktivasiya anını və şəxsini tələb edir",
                user_message="POS səlahiyyət qeydi natamamdır.",
                context={"employee_id": str(employee_id)},
            )

        self.id = threshold_id
        self.tenant_id = tenant_id
        self.employee_id = employee_id
        self.max_discount_pct = max_discount_pct
        self.can_void = can_void
        self.can_refund = can_refund
        self.note = note
        self.updated_by = updated_by
        self.created_at = require_aware(created_at, field="created_at")
        self.updated_at = require_aware(updated_at, field="updated_at")
        self.is_active = is_active
        self.deactivated_at = (
            require_aware(deactivated_at, field="deactivated_at")
            if deactivated_at is not None
            else None
        )
        self.deactivated_by = deactivated_by

    # ------------------------------ yazı yolu --------------------------------- #

    def set_threshold(
        self,
        *,
        max_discount_pct: Decimal,
        can_void: bool,
        can_refund: bool,
        note: str | None,
        updated_by: EmployeeId,
        now: datetime,
        ceiling_pct: Decimal = DEFAULT_DISCOUNT_PCT_CEILING,
    ) -> None:
        """Həddi təyin edir/yeniləyir — YENİDƏN AKTİVLƏŞDİRİR (əvvəl geri alınıbsa).

        Reaktivasiya QƏSDƏNDİR: admin yeni hədd yazırsa niyyəti aydındır —
        "bu səlahiyyəti indi verirəm". Ayrıca "aktivləşdir" düyməsi tələb
        etmək eyni əməliyyatı iki kliklik edərdi.
        """
        _require_hard_bounds(max_discount_pct)
        # Root həddi sxem sərhədindən yuxarı ola bilməz — `min()` iki
        # tavanın ən sərtini seçir (Root ceiling səhvən 100-dən böyük
        # yazılsa belə sxem sərhədi qırılmır).
        effective_ceiling = min(ceiling_pct, MAX_DISCOUNT_PCT_HARD_CEILING)
        if max_discount_pct > effective_ceiling:
            raise DomainRuleError(
                f"Endirim faizi Root həddini ({effective_ceiling}%) aşır",
                user_message=f"Endirim faizi {effective_ceiling}%-dən çox ola bilməz.",
                context={
                    "requested": str(max_discount_pct),
                    "ceiling": str(effective_ceiling),
                },
            )

        self.max_discount_pct = max_discount_pct
        self.can_void = can_void
        self.can_refund = can_refund
        self.note = (normalise_decision_text(note) or None) if note else None
        self.updated_by = updated_by
        self.updated_at = require_aware(now, field="now")
        self.is_active = True
        self.deactivated_at = None
        self.deactivated_by = None

    def revoke(self, *, deactivated_by: EmployeeId, now: datetime) -> None:
        """Səlahiyyəti geri alır — soft delete, sətir SİLİNMİR (migrations/018).

        "O gün bu işçinin hansı POS səlahiyyəti var idi?" sualı HR/audit
        araşdırmasında cavabsız qalmamalıdır, ona görə fiziki `DELETE` YOXDUR.
        """
        if not self.is_active:
            raise InvalidStateTransitionError(
                "Bu POS səlahiyyəti artıq geri alınıb",
                user_message="Bu səlahiyyət artıq aktiv deyil.",
                context={"employee_id": str(self.employee_id)},
            )
        aware_now = require_aware(now, field="now")
        self.is_active = False
        self.deactivated_at = aware_now
        self.deactivated_by = deactivated_by
        self.updated_at = aware_now
        self.updated_by = deactivated_by

    def __repr__(self) -> str:
        return (
            f"POSPermissionThreshold(employee_id={self.employee_id}, "
            f"max_discount_pct={self.max_discount_pct}, active={self.is_active})"
        )


def _require_hard_bounds(max_discount_pct: Decimal) -> None:
    if max_discount_pct < MIN_DISCOUNT_PCT or max_discount_pct > MAX_DISCOUNT_PCT_HARD_CEILING:
        raise DomainRuleError(
            f"Endirim faizi {MIN_DISCOUNT_PCT}–{MAX_DISCOUNT_PCT_HARD_CEILING} arasında olmalıdır",
            user_message="Endirim faizi 0 ilə 100 arasında olmalıdır.",
            context={"value": str(max_discount_pct)},
        )


__all__ = [
    "DEFAULT_DISCOUNT_PCT_CEILING",
    "MAX_DISCOUNT_PCT_HARD_CEILING",
    "MIN_DISCOUNT_PCT",
    "POSPermissionThreshold",
]
