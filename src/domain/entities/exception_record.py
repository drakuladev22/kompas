"""İstisna sətri aqreqatı (#9, `exceptions` cədvəli) — Faza 3.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI AQREQAT — "TAPINTINI CƏRİMƏYƏ YAZAQ" NİYƏ RƏDD EDİLDİ
──────────────────────────────────────────────────────────────────────────────
İstisna CƏRİMƏ DEYİL və heç vaxt avtomatik cəriməyə çevrilmir. O, "buna insan
baxsın" siqnalıdır: davranış anomaliyasının izahı gec avtobus da ola bilər,
sui-istifadə də. Siqnalı `fines`-ə yazmaq həmin fərqi itirər və işçidən
avtomatik pul kəsilməsinə bir addım qalardı — layihənin BR-002 qərarı
(defolt dərəcə 0.00) məhz bu riskə qarşıdır.

Ona görə istisnanın ÖZ həyat dövrü var:

    OPEN ──mark_reviewed(qeyd?)──> REVIEWED   (baxıldı, tədbir görüldü)
      │
      └──dismiss(qeyd MƏCBURİ)──> DISMISSED   (baxıldı, əsassız sayıldı)

Hər iki keçid TERMİNALDIR: bağlanmış istisna yenidən açılmır. Səbəb
`exceptions.dedupe_key`-in mənasındadır — planlaşdırılmış aşkarlama hər gecə
işləyir və "bir dəfə rədd etdim" qərarı sabah təkzib edilməməlidir
(migrations/018, `uq_exceptions_dedupe` şərhi).

──────────────────────────────────────────────────────────────────────────────
NİYƏ `dismiss()` QEYD TƏLƏB EDİR, `mark_reviewed()` İSƏ YOX
──────────────────────────────────────────────────────────────────────────────
İki qərar eyni risk daşımır. `REVIEWED` "baxdım və lazım olanı etdim"
deməkdir — arxasında adətən başqa bir izlənə bilən əməliyyat (söhbət, cərimə,
növbə dəyişikliyi) durur. `DISMISSED` isə siqnalı SÖNDÜRÜR: eyni tapıntı
`dedupe_key` səbəbindən bir daha yaranmayacaq. Səbəbsiz söndürmə audit
baxımından "izsiz silmə" ilə eyni nəticəni verərdi, ona görə qeyd məcburidir.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Final

from src.domain.entities.base import (
    AggregateRoot,
    DomainRuleError,
    InvalidStateTransitionError,
)
from src.domain.events import ExceptionRaisedEvent, ExceptionReviewDecidedEvent
from src.domain.value_objects.exception_signals import (
    MIN_SOURCE_CODE_LENGTH,
    ExceptionFinding,
    ExceptionSeverity,
    ExceptionStatus,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    ExceptionId,
    StoreId,
    TenantId,
)
from src.domain.value_objects.scheduling import require_aware

#: `exceptions.detail` — DB `CHECK (char_length(trim(detail)) >= 5)` güzgüsü.
#: Bu, konfiqurasiya edilə bilən biznes həddi DEYİL, sxem məhdudiyyətidir:
#: dəyişdirilməsi miqrasiya tələb edir, ona görə `system_limits`-də yeri yoxdur.
MIN_EXCEPTION_DETAIL_LENGTH: Final = 5

#: Qərar qeydinin minimum uzunluğu üçün FALLBACK. HƏQİQİ MƏNBƏ
#: `system_limits.EXCEPTION_REVIEW_NOTE_MIN_LENGTH`-dir (Root dəyişdirir);
#: bu sabit yalnız limit ötürülməyən yollar (məs. repo-dan bərpa sonrası
#: birbaşa domen çağırışı) üçündür.
DEFAULT_MIN_REVIEW_NOTE_LENGTH: Final = 10


class ExceptionRecord(AggregateRoot):
    """Vahid İstisna Jurnalının bir sətri."""

    def __init__(
        self,
        *,
        exception_id: ExceptionId,
        tenant_id: TenantId,
        source: str,
        employee_id: EmployeeId,
        store_id: StoreId,
        detail: str,
        created_at: datetime,
        context: Mapping[str, object] | None = None,
        severity: ExceptionSeverity = ExceptionSeverity.MEDIUM,
        status: ExceptionStatus = ExceptionStatus.OPEN,
        dedupe_key: str | None = None,
        reviewed_by: EmployeeId | None = None,
        reviewed_at: datetime | None = None,
        review_note: str | None = None,
        emit_created_event: bool = True,
    ) -> None:
        super().__init__()
        cleaned_source = source.strip().upper()
        if len(cleaned_source) < MIN_SOURCE_CODE_LENGTH:
            raise DomainRuleError(
                f"Mənbə kodu minimum {MIN_SOURCE_CODE_LENGTH} simvol olmalıdır",
                user_message="İstisna mənbəyi düzgün deyil.",
                context={"source": source},
            )

        cleaned_detail = " ".join(detail.split())
        if len(cleaned_detail) < MIN_EXCEPTION_DETAIL_LENGTH:
            raise DomainRuleError(
                f"İstisna izahı minimum {MIN_EXCEPTION_DETAIL_LENGTH} simvol olmalıdır",
                user_message="İstisnanın izahı çox qısadır.",
                context={"length": len(cleaned_detail)},
            )

        # `chk_exception_review` güzgüsü: qərar statusu qərar verəni TƏLƏB EDİR.
        # Yoxlama DB-də də var, lakin burada təkrarlanır — repo-dan yararsız
        # sətir bərpa edilsəydi, ekran "baxılıb" yazar, kimin baxdığını isə
        # göstərə bilməzdi.
        if not status.is_open and (reviewed_by is None or reviewed_at is None):
            raise DomainRuleError(
                "Bağlanmış istisna qərar verəni və qərar anını tələb edir",
                user_message="İstisna qeydi natamamdır.",
                context={"status": status.value},
            )

        self.id = exception_id
        self.tenant_id = tenant_id
        self.source = cleaned_source
        self.employee_id = employee_id
        self.store_id = store_id
        self.detail = cleaned_detail
        self.context: dict[str, object] = dict(context or {})
        self.severity = severity
        self.status = status
        self.dedupe_key = dedupe_key
        self.reviewed_by = reviewed_by
        self.reviewed_at = (
            require_aware(reviewed_at, field="reviewed_at") if reviewed_at is not None else None
        )
        self.review_note = review_note
        self.created_at = require_aware(created_at, field="created_at")

        # Repository-dən BƏRPA hadisə YAYMIR (`emit_created_event=False`) —
        # əks halda hər oxu "yeni anomaliya aşkarlandı" bildirişi doğurardı.
        if emit_created_event and status.is_open:
            self.record_event(
                ExceptionRaisedEvent(
                    tenant_id=tenant_id,
                    actor_id=None,
                    exception_id=exception_id,
                    source=cleaned_source,
                    employee_id=employee_id,
                    store_id=store_id,
                    severity=severity.value,
                    dedupe_key=dedupe_key,
                )
            )

    # ------------------------------ yaradılma -------------------------------- #

    @classmethod
    def from_finding(
        cls,
        finding: ExceptionFinding,
        *,
        exception_id: ExceptionId,
        tenant_id: TenantId,
        source: str,
        severity: ExceptionSeverity,
        created_at: datetime,
    ) -> ExceptionRecord:
        """Qaydanın tapıntısını jurnal sətrinə çevirir.

        `severity` AÇIQ ötürülür (tapıntıdakı dəyər deyil): boş buraxılmış
        ciddiyyəti mənbənin ROOT-dan idarə olunan defoltu ilə doldurmaq
        MOTORUN işidir, aqreqatın yox — belə olduqda kataloqa çıxış tələbi
        domen entity-sinə sızmır.
        """
        return cls(
            exception_id=exception_id,
            tenant_id=tenant_id,
            source=source,
            employee_id=finding.employee_id,
            store_id=finding.store_id,
            detail=finding.detail,
            created_at=created_at,
            context=finding.context,
            severity=severity,
            dedupe_key=finding.dedupe_key,
        )

    # -------------------------------- qərar ---------------------------------- #

    def mark_reviewed(
        self,
        *,
        reviewed_by: EmployeeId,
        reviewed_at: datetime,
        note: str | None = None,
        min_note_length: int = DEFAULT_MIN_REVIEW_NOTE_LENGTH,
    ) -> None:
        """`[Nəzərdən Keçirildi]` — siqnala baxıldı və lazımi tədbir görüldü.

        Qeyd könüllüdür, LAKİN yazılıbsa minimum uzunluğa tabedir: "ok" kimi
        bir sətir qeyd sahəsini doldurulmuş göstərir, əslində isə heç nə izah
        etmir.
        """
        self._close(
            new_status=ExceptionStatus.REVIEWED,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
            note=note,
            min_note_length=min_note_length,
            note_required=False,
        )

    def dismiss(
        self,
        *,
        reviewed_by: EmployeeId,
        reviewed_at: datetime,
        note: str,
        min_note_length: int = DEFAULT_MIN_REVIEW_NOTE_LENGTH,
    ) -> None:
        """`[Rədd Et]` — tapıntı əsassız sayıldı. Qeyd MƏCBURİDİR."""
        self._close(
            new_status=ExceptionStatus.DISMISSED,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
            note=note,
            min_note_length=min_note_length,
            note_required=True,
        )

    def _close(
        self,
        *,
        new_status: ExceptionStatus,
        reviewed_by: EmployeeId,
        reviewed_at: datetime,
        note: str | None,
        min_note_length: int,
        note_required: bool,
    ) -> None:
        if not self.status.is_open:
            raise InvalidStateTransitionError(
                f"İstisna artıq bağlanıb: '{self.status.value}'",
                user_message="Bu istisna artıq emal edilib.",
                context={"status": self.status.value, "exception_id": str(self.id)},
            )

        cleaned = " ".join(note.split()) if note else None
        threshold = max(0, min_note_length)
        if note_required and (cleaned is None or len(cleaned) < threshold):
            raise DomainRuleError(
                f"Rədd qərarı minimum {threshold} simvolluq izah tələb edir",
                user_message="Rədd səbəbini ətraflı yazın.",
                context={"length": len(cleaned or "")},
            )
        if cleaned is not None and len(cleaned) < threshold:
            raise DomainRuleError(
                f"Qərar qeydi minimum {threshold} simvol olmalıdır",
                user_message="Qeydinizi bir az ətraflı yazın.",
                context={"length": len(cleaned)},
            )

        self.status = new_status
        self.reviewed_by = reviewed_by
        self.reviewed_at = require_aware(reviewed_at, field="reviewed_at")
        self.review_note = cleaned
        self.record_event(
            ExceptionReviewDecidedEvent(
                tenant_id=self.tenant_id,
                actor_id=reviewed_by,
                exception_id=self.id,
                source=self.source,
                employee_id=self.employee_id,
                status=new_status.value,
                decided_by=reviewed_by,
                note=cleaned,
            )
        )

    # ------------------------------ göstəricilər ------------------------------ #

    @property
    def is_open(self) -> bool:
        return self.status.is_open

    def age_hours(self, *, now: datetime) -> float:
        """Neçə saatdır cavab gözləyir — növbənin yaşı göstəricisi."""
        require_aware(now, field="now")
        return (now - self.created_at).total_seconds() / 3600

    def __repr__(self) -> str:
        return (
            f"ExceptionRecord(id={self.id}, source={self.source}, "
            f"status={self.status.value}, severity={self.severity.value})"
        )


__all__ = [
    "DEFAULT_MIN_REVIEW_NOTE_LENGTH",
    "MIN_EXCEPTION_DETAIL_LENGTH",
    "ExceptionRecord",
]
