"""Açıq Növbə elanı (#16, kompasos11.md Faza 6) — `open_shift_postings` aqreqatı.

──────────────────────────────────────────────────────────────────────────────
BU, SHIFT SWAP DEYİL — İKİ FƏRQLİ, PARALEL AXIN
──────────────────────────────────────────────────────────────────────────────
`ShiftSwapRequest` (bax `entities/shift.py`) İKİ TƏRƏFLİ bir sorğudur: KONKRET
işçi öz KONKRET gününü dəyişmək istəyir, `can_approve_shift_swap` sahibi isə
onu təsdiqləyir və ya rədd edir. Yəni orada "kim?" sualı elə əvvəldən
cavablanıb, açıq olan yalnız "icazə verilirmi?" sualıdır.

Açıq Növbə bunun ƏKSİDİR: admin DOLDURULMAMIŞ bir slotu (mağaza + tarix + iş
rejimi şablonu) elan edir, "kim?" sualı isə AÇIQ qalır — cavabı ilk basan
işçi verir. Təsdiq mərhələsi YOXDUR; qərar elanın açılması anında artıq
verilib ("bu slotu istənilən uyğun işçi tuta bilər").

Ona görə bu aqreqat `ShiftSwapRequest`-i GENİŞLƏNDİRMİR və onun statuslarını
(`PENDING_APPROVAL/APPROVED/REJECTED`) TƏKRAR İSTİFADƏ ETMİR — onları
paylaşsaydıq, "təsdiq gözləyən açıq növbə" kimi mənasız bir vəziyyət yaranardı
və hər iki axının qaydaları bir-birinə sızardı.

──────────────────────────────────────────────────────────────────────────────
"İLK BASAN QAZANIR" NİYƏ ENTITY-DƏ TAM HƏLL OLUNMUR
──────────────────────────────────────────────────────────────────────────────
`claim()` statusun `OPEN` olduğunu yoxlayır, lakin bu, YARIŞI ÖZÜ BAĞLAMIR:
iki paralel tranzaksiya obyekti oxuyanda HƏR İKİSİ `OPEN` görür. Yarışın
həqiqi qapağı DB-dədir — şərti `UPDATE ... WHERE status = 'OPEN'` + sətir
kilidi + status keçid trigger-i (`migrations/019`, üç qat). Entity yoxlaması
İKİNCİ qatdır: repository-siz istifadədə (test, plugin, gələcək skript) də
yararsız keçid mümkün olmasın.

Layihə qaydası budur — struktur zəmanət İKİ yerdə yaşayır (CLAUDE.md §5).

──────────────────────────────────────────────────────────────────────────────
NİYƏ `CANCELLED` VAR, `DELETE` YOX
──────────────────────────────────────────────────────────────────────────────
`migrations/019` şərhi ilə eyni səbəb: elanı görmüş işçi üçün "elan yoxa
çıxdı" izahsız qalmamalıdır. Ləğv QƏRARDIR — kim, nə vaxt və NİYƏ ləğv etdiyi
sətrin özündə saxlanılır.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from src.domain.entities.base import AggregateRoot, DomainRuleError, InvalidStateTransitionError

# Ləğv səbəbinin minimum uzunluğu növbə dəyişmə QƏRARI ilə EYNİ mənbədəndir:
# işçi üçün hər ikisi "növbəm dəyişdi — niyə?" sualıdır və iki fərqli hədd
# saxlamaq eyni sualın iki cür cavablanması demək olardı.
from src.domain.entities.shift import MIN_DECISION_REASON_LENGTH
from src.domain.events import OpenShiftClaimedEvent, OpenShiftPostedEvent
from src.domain.value_objects.identifiers import (
    EmployeeId,
    OpenShiftPostingId,
    StoreId,
    TenantId,
    WorkModeId,
)
from src.domain.value_objects.scheduling import require_aware
from src.shared.text import normalise_decision_text


class OpenShiftStatus(str, Enum):
    """`open_shift_postings.status` — DB `CHECK`-i ilə EYNİ üç dəyər.

    Keçid qrafı BİR İSTİQAMƏTLİDİR (DB trigger-i də bunu qoruyur):

        OPEN ──claim()───> CLAIMED    (terminal)
          │
          └──cancel()───> CANCELLED   (terminal)

    Geri keçid YOXDUR: tutulmuş növbəni "yenidən açmaq" işçinin artıq
    planlaşdırdığı günü əlindən almaq olardı, ləğv edilmiş elanı isə yenidən
    açmaq YENİ elandır (yeni sətir) — köhnəsinin tarixçəsi qorunur.
    """

    OPEN = "OPEN"
    CLAIMED = "CLAIMED"
    CANCELLED = "CANCELLED"

    @property
    def is_final(self) -> bool:
        """Qərar verilibmi — `OPEN`-dən çıxmış hər status terminaldır."""
        return self is not OpenShiftStatus.OPEN


@dataclass(frozen=True)
class OpenShiftSlot:
    """Elanın DOLDURULMAMIŞ slotu: mağaza + tarix + şablon.

    NİYƏ AYRICA DƏYƏR OBYEKTİ: bu üçlük "eyni slot üçün iki açıq elan
    olmamalıdır" qaydasının (DB: `uq_open_shift_one_open_per_slot`) domen
    tərəfidir. Üç sahəni ayrı-ayrı gəzdirsəydik, həmin qaydanı yoxlayan hər
    yer üç parametri düzgün SIRA ilə ötürməyə məcbur olardı — `StoreId` və
    `WorkModeId` fərqli tiplər olsa da, gələcəkdə bir sahə əlavə olunanda
    imza dəyişikliyi bütün çağırış yerlərinə yayılardı.
    """

    store_id: StoreId
    shift_date: date
    work_mode_id: WorkModeId


class OpenShiftPosting(AggregateRoot):
    """Bir açıq növbə elanı (`open_shift_postings` sətri)."""

    def __init__(
        self,
        *,
        posting_id: OpenShiftPostingId,
        tenant_id: TenantId,
        slot: OpenShiftSlot,
        # NİYƏ `None` OLA BİLƏR: DB-də sütun `ON DELETE SET NULL`-dır
        # (migrations/019) — elanı açan şəxsin qeydi silinsə elan SİLİNMİR,
        # sadəcə sahibsiz qalır. Tip bunu ETİRAF ETMƏLİDİR; əks halda
        # siyahının bərpası `None` dəyərdə çökər və BİR silinmiş istifadəçi
        # bütün bazarı görünməz edərdi.
        posted_by: EmployeeId | None,
        created_at: datetime,
        status: OpenShiftStatus = OpenShiftStatus.OPEN,
        claimed_by: EmployeeId | None = None,
        claimed_at: datetime | None = None,
        cancelled_by: EmployeeId | None = None,
        cancelled_at: datetime | None = None,
        cancel_reason: str | None = None,
        emit_created_event: bool = True,
    ) -> None:
        super().__init__()
        self.id = posting_id
        self.tenant_id = tenant_id
        self.slot = slot
        self.posted_by = posted_by
        self.created_at = require_aware(created_at, field="created_at")
        self.status = status
        self.claimed_by = claimed_by
        self.claimed_at = (
            None if claimed_at is None else require_aware(claimed_at, field="claimed_at")
        )
        self.cancelled_by = cancelled_by
        self.cancelled_at = (
            None if cancelled_at is None else require_aware(cancelled_at, field="cancelled_at")
        )
        self.cancel_reason = cancel_reason

        # DB `chk_open_shift_claim` / `chk_open_shift_cancel` məhdudiyyətlərinin
        # domen güzgüsü: yarımçıq "tutulmuş" və ya "ləğv edilmiş" sətir nə
        # bazadan bərpa oluna, nə də koddan qurula bilər.
        self._require_consistent_state()

        # Repository-dən BƏRPA hadisə YAYMIR — əks halda ekranın hər
        # yenilənməsi "yeni açıq növbə elan olundu" bildirişi doğurardı.
        # `posted_by is None` yalnız BƏRPA yolunda mümkündür (yuxarıdakı
        # şərhə bax), yəni bu şərt praktikada yeni elanı heç vaxt susdurmur.
        if emit_created_event and status is OpenShiftStatus.OPEN and posted_by is not None:
            self.record_event(
                OpenShiftPostedEvent(
                    tenant_id=tenant_id,
                    posting_id=posting_id,
                    store_id=slot.store_id,
                    shift_date=slot.shift_date,
                    work_mode_id=slot.work_mode_id,
                    posted_by=posted_by,
                )
            )

    # ------------------------------ oxu köməkçiləri --------------------------- #

    @property
    def shift_date(self) -> date:
        """Qısa yol — elanların böyük əksəriyyəti məhz tarixə görə süzülür."""
        return self.slot.shift_date

    @property
    def store_id(self) -> StoreId:
        return self.slot.store_id

    @property
    def work_mode_id(self) -> WorkModeId:
        return self.slot.work_mode_id

    @property
    def is_open(self) -> bool:
        return self.status is OpenShiftStatus.OPEN

    # -------------------------------- keçidlər -------------------------------- #

    def claim(self, *, employee_id: EmployeeId, claimed_at: datetime) -> None:
        """`[Bu Növbəni Götür]` — ilk basan qazanır.

        DİQQƏT: bu metod yarışın QALİBİNİ TƏYİN ETMİR. Qalibi DB-dəki şərti
        `UPDATE ... WHERE status = 'OPEN'` seçir; burada yalnız artıq
        qazanılmış nəticə obyektə yazılır (bax modul başlığı).
        """
        if self.status is not OpenShiftStatus.OPEN:
            raise InvalidStateTransitionError(
                f"«{self.status.value}» statusundakı elan tutula bilməz",
                user_message="Bu növbəni artıq başqası götürüb.",
                context={"posting_id": str(self.id), "status": self.status.value},
            )
        if employee_id == self.posted_by:
            # VƏZİFƏ AYRILIĞI: elanı açan onu özü tuta bilməz. Əks halda
            # "açıq bazar" formal olardı — hansı slotun açılacağına qərar
            # verən şəxs onu bir saniyə sonra özü götürüb bazarı bağlayardı.
            raise DomainRuleError(
                "Elanı açan şəxs onu özü tuta bilməz",
                user_message="Öz elan etdiyiniz növbəni özünüz götürə bilməzsiniz.",
                context={"posting_id": str(self.id), "employee_id": str(employee_id)},
            )

        self.status = OpenShiftStatus.CLAIMED
        self.claimed_by = employee_id
        self.claimed_at = require_aware(claimed_at, field="claimed_at")
        self.record_event(
            OpenShiftClaimedEvent(
                tenant_id=self.tenant_id,
                posting_id=self.id,
                employee_id=employee_id,
                store_id=self.slot.store_id,
                shift_date=self.slot.shift_date,
            )
        )

    def cancel(self, *, cancelled_by: EmployeeId, cancelled_at: datetime, reason: str) -> None:
        """Admin elanı geri çəkir — SƏBƏB MƏCBURİDİR."""
        if self.status is not OpenShiftStatus.OPEN:
            raise InvalidStateTransitionError(
                f"«{self.status.value}» statusundakı elan ləğv edilə bilməz",
                user_message="Bu elan artıq bağlanıb.",
                context={"posting_id": str(self.id), "status": self.status.value},
            )
        cleaned = normalise_decision_text(reason)
        if len(cleaned) < MIN_DECISION_REASON_LENGTH:
            raise DomainRuleError(
                f"Ləğv səbəbi minimum {MIN_DECISION_REASON_LENGTH} simvol olmalıdır",
                user_message="Ləğv səbəbini ətraflı yazın.",
                context={"length": len(cleaned)},
            )

        self.status = OpenShiftStatus.CANCELLED
        self.cancelled_by = cancelled_by
        self.cancelled_at = require_aware(cancelled_at, field="cancelled_at")
        self.cancel_reason = cleaned

    # -------------------------------- audit ----------------------------------- #

    def to_audit_state(self) -> dict[str, object]:
        """Audit `before_state`/`after_state` üçün düz sözlük."""
        return {
            "store_id": str(self.slot.store_id),
            "shift_date": self.slot.shift_date.isoformat(),
            "work_mode_id": str(self.slot.work_mode_id),
            "status": self.status.value,
            "claimed_by": str(self.claimed_by) if self.claimed_by else None,
            "cancel_reason": self.cancel_reason,
        }

    # -------------------------------- daxili ---------------------------------- #

    def _require_consistent_state(self) -> None:
        claimed = self.status is OpenShiftStatus.CLAIMED
        if claimed != (self.claimed_by is not None and self.claimed_at is not None):
            raise DomainRuleError(
                "Tutulma sahələri status ilə uyğun gəlmir",
                user_message="Açıq növbə qeydi oxunmadı.",
                context={"posting_id": str(self.id), "status": self.status.value},
            )
        cancelled = self.status is OpenShiftStatus.CANCELLED
        if cancelled != (self.cancelled_by is not None and self.cancelled_at is not None):
            raise DomainRuleError(
                "Ləğv sahələri status ilə uyğun gəlmir",
                user_message="Açıq növbə qeydi oxunmadı.",
                context={"posting_id": str(self.id), "status": self.status.value},
            )

    def __repr__(self) -> str:
        return (
            f"OpenShiftPosting(id={self.id}, date={self.slot.shift_date}, "
            f"status={self.status.value})"
        )


__all__ = [
    "OpenShiftPosting",
    "OpenShiftSlot",
    "OpenShiftStatus",
]
