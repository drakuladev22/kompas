"""İşçi sənədi/müqaviləsi aqreqatı (#17, `employee_documents`) — Faza 7.

`migrations/020` başlığı ilə EYNİ əsaslandırma: fiziki `DELETE` YOXDUR, çünki
müddəti bitmiş sənəd "lazımsız zibil" deyil — o, KEÇMİŞ növbə təyinatının niyə
icazəli olduğunu SÜBUT edir. Ona görə bu aqreqatda da `delete()` YOXDUR,
yalnız `deactivate()` (soft delete, `catalogs.py` naxışı).

──────────────────────────────────────────────────────────────────────────────
NİYƏ `doc_type` YARADILMADAN SONRA DƏYİŞMİR
──────────────────────────────────────────────────────────────────────────────
`update()` sənədin MƏZMUNUNU (nömrə, bitmə tarixi, bloklama işarəsi) yeniləyir,
lakin növü DƏYİŞMİR. Səbəb — `doc_type` sətrin İDENTİTİ hissəsidir: "bu sətir
MUQAVILE-dir" faktı yazıldıqdan sonra dəyişsəydi, köhnə auditdə "MUQAVILE
bitib" xəbərdarlığının həqiqətən müqaviləyə aid olduğuna zəmanət qalmazdı. Yeni
növ lazımdırsa, YENİ sətir yaradılır (migrations/020: "eyni növdən çox sənəd
normaldır").

──────────────────────────────────────────────────────────────────────────────
NİYƏ HADİSƏ YALNIZ YARADILMADA
──────────────────────────────────────────────────────────────────────────────
Bax `domain.events.EmployeeDocumentRecordedEvent` başlığı — YAGNI və
`POSPermissionThreshold`-la ardıcıllıq üçün redaktə/deaktivasiya hadisə
yaymır, audit isə hər halda MƏCBURİDİR (use case qatında).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Final

from src.domain.entities.base import (
    AggregateRoot,
    DomainRuleError,
    InvalidStateTransitionError,
)
from src.domain.events import EmployeeDocumentRecordedEvent
from src.domain.value_objects.identifiers import EmployeeDocumentId, EmployeeId, TenantId
from src.domain.value_objects.scheduling import require_aware

#: `employee_documents.doc_type` CHECK-inin güzgüsü (migrations/020:
#: `char_length(trim(doc_type)) >= 2`). Sxem sərhədi — dəyişmək miqrasiya tələb edir.
MIN_DOC_TYPE_LENGTH: Final = 2

#: Deaktivasiya səbəbinin minimum uzunluğu. Sərt DB `CHECK` YOXDUR (yalnız
#: `deactivated_at IS NOT NULL` tələb olunur), ona görə bu, domen qaydasıdır —
#: "sənəd niyə söndürülüb?" sualı "ok" kimi bir sözlə cavablanmamalıdır.
MIN_DEACTIVATION_REASON_LENGTH: Final = 5

#: `is_blocking` sahəsinin İNSAN üçün etiketi `domain/document_rules.py`-dadır
#: (`ATTENTION_FLAG_LABEL_AZ`) — sahə burada yaşasa da, onun NƏ ETDİYİNİ həmin
#: qayda modulu təyin edir və etiket davranışın adı olmalıdır, sütunun yox.


class EmployeeDocument(AggregateRoot):
    """Bir işçinin bir sənəd/müqavilə sətri — işçi başına ÇOX sətir ola bilər."""

    def __init__(
        self,
        *,
        document_id: EmployeeDocumentId,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        doc_type: str,
        doc_number: str | None,
        file_ref: str | None,
        expiry_date: date | None,
        is_blocking: bool,
        uploaded_by: EmployeeId | None,
        created_at: datetime,
        updated_at: datetime,
        is_active: bool = True,
        deactivated_at: datetime | None = None,
        deactivated_by: EmployeeId | None = None,
        deactivation_reason: str | None = None,
        emit_created_event: bool = True,
    ) -> None:
        super().__init__()
        cleaned_type = doc_type.strip().upper()
        if len(cleaned_type) < MIN_DOC_TYPE_LENGTH:
            raise DomainRuleError(
                f"Sənəd növü minimum {MIN_DOC_TYPE_LENGTH} simvol olmalıdır",
                user_message="Sənəd növü düzgün deyil.",
                context={"doc_type": doc_type},
            )
        # `chk_employee_document_deactivation` güzgüsü (migrations/020):
        # geri alınmış sətir HANSI ANDA, HANSI SƏBƏBLƏ sualını cavabsız
        # buraxa bilməz — repo-dan yararsız sətir bərpa edilsə belə.
        if not is_active and (
            deactivated_at is None or deactivated_by is None or not deactivation_reason
        ):
            raise DomainRuleError(
                "Deaktiv sənəd söndürülmə anını, şəxsini və səbəbini tələb edir",
                user_message="Sənəd qeydi natamamdır.",
                context={"employee_id": str(employee_id)},
            )

        self.id = document_id
        self.tenant_id = tenant_id
        self.employee_id = employee_id
        self.doc_type = cleaned_type
        self.doc_number = doc_number.strip() if doc_number and doc_number.strip() else None
        self.file_ref = file_ref.strip() if file_ref and file_ref.strip() else None
        self.expiry_date = expiry_date
        self.is_blocking = is_blocking
        self.uploaded_by = uploaded_by
        self.created_at = require_aware(created_at, field="created_at")
        self.updated_at = require_aware(updated_at, field="updated_at")
        self.is_active = is_active
        self.deactivated_at = (
            require_aware(deactivated_at, field="deactivated_at")
            if deactivated_at is not None
            else None
        )
        self.deactivated_by = deactivated_by
        self.deactivation_reason = deactivation_reason

        # Repository-dən BƏRPA hadisə YAYMIR (`emit_created_event=False`) —
        # əks halda hər oxu "yeni sənəd qeydə alındı" bildirişi doğurardı
        # (`ExceptionRecord.__init__` ilə eyni qoruma).
        if emit_created_event:
            self.record_event(
                EmployeeDocumentRecordedEvent(
                    tenant_id=tenant_id,
                    actor_id=uploaded_by,
                    document_id=document_id,
                    employee_id=employee_id,
                    doc_type=cleaned_type,
                    is_blocking=is_blocking,
                    uploaded_by=uploaded_by,
                )
            )

    # ------------------------------ yazı yolu --------------------------------- #

    def update(
        self,
        *,
        doc_number: str | None,
        expiry_date: date | None,
        is_blocking: bool,
        now: datetime,
    ) -> None:
        """Redaktə edilə bilən sahələri yeniləyir (`doc_type` DƏYİŞMİR — bax başlıq)."""
        self._require_active("Deaktiv sənəd redaktə edilə bilməz")
        self.doc_number = doc_number.strip() if doc_number and doc_number.strip() else None
        self.expiry_date = expiry_date
        self.is_blocking = is_blocking
        self.updated_at = require_aware(now, field="now")

    def attach_file(self, *, file_ref: str, now: datetime) -> None:
        """Skanı bağlayır. `file_ref` NULL-dan dolur — HR faylı sonra əlavə edə bilər."""
        self._require_active("Deaktiv sənədə fayl bağlana bilməz")
        cleaned = file_ref.strip()
        if not cleaned:
            raise DomainRuleError(
                "Fayl istinadı boş ola bilməz",
                user_message="Fayl seçilmədi.",
                context={"document_id": str(self.id)},
            )
        self.file_ref = cleaned
        self.updated_at = require_aware(now, field="now")

    def deactivate(
        self,
        *,
        reason: str,
        deactivated_by: EmployeeId,
        now: datetime,
        min_reason_length: int = MIN_DEACTIVATION_REASON_LENGTH,
    ) -> None:
        """Soft delete — sətir SİLİNMİR (`migrations/020` başlığı).

        Səbəb MƏCBURİDİR: sənəd qeydinin yoxa çıxması ("niyə bu sənəd artıq
        siyahıda deyil?") mübahisədə izahsız qala bilməz — `catalogs.py`-dakı
        eyni qayda.
        """
        if not self.is_active:
            raise InvalidStateTransitionError(
                "Bu sənəd artıq deaktivdir",
                user_message="Bu sənəd artıq deaktiv edilib.",
                context={"document_id": str(self.id)},
            )
        cleaned_reason = " ".join(reason.split())
        threshold = max(0, min_reason_length)
        if len(cleaned_reason) < threshold:
            raise DomainRuleError(
                f"Deaktivasiya səbəbi minimum {threshold} simvol olmalıdır",
                user_message="Söndürmə səbəbini ətraflı yazın.",
                context={"length": len(cleaned_reason)},
            )
        aware_now = require_aware(now, field="now")
        self.is_active = False
        self.deactivated_at = aware_now
        self.deactivated_by = deactivated_by
        self.deactivation_reason = cleaned_reason
        self.updated_at = aware_now

    def _require_active(self, message: str) -> None:
        if not self.is_active:
            raise InvalidStateTransitionError(
                message,
                user_message="Bu sənəd artıq deaktivdir.",
                context={"document_id": str(self.id)},
            )

    # ------------------------------ göstəricilər ------------------------------ #

    def is_expired_on(self, reference_date: date) -> bool:
        """`reference_date`-də sənəd artıq bitibmi.

        SƏRHƏD: bitmə tarixinin ÖZÜ hələ "bitmiş" sayılmır — sənəd o günün
        SONUNA qədər qüvvədədir (standart müqavilə konvensiyası). Yəni
        `expiry_date == reference_date` → HƏLƏ bitməyib, `< reference_date`
        olduqda bitib. `expiry_date IS NULL` (müddətsiz) həmişə `False`.
        """
        if self.expiry_date is None:
            return False
        return self.expiry_date < reference_date

    def __repr__(self) -> str:
        return (
            f"EmployeeDocument(id={self.id}, doc_type={self.doc_type}, "
            f"employee_id={self.employee_id}, is_blocking={self.is_blocking}, "
            f"active={self.is_active})"
        )


__all__ = [
    "MIN_DEACTIVATION_REASON_LENGTH",
    "MIN_DOC_TYPE_LENGTH",
    "EmployeeDocument",
]
