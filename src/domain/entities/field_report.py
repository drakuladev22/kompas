"""Sahə hesabatı aqreqatı (#26+#27, `field_reports`) — kompas1.md Faza 3.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BİR AQREQAT, İKİ ŞABLON — İKİ SİNİF YOX
──────────────────────────────────────────────────────────────────────────────
Mağaza auditi (#26) və insident bildirişi (#27) EYNİ axındır: forma →
(istəyə görə) foto → avtomatik düzəliş-tapşırığı → bağlanma. Fərq yalnız
FORMADADIR — auditdə checklist var, insidentdə yoxdur.

`StoreAudit` + `IncidentReport` kimi iki sinif yazsaydıq, hər ikisi eyni
`field_reports` sətrini idarə edərdi (Struktur Qərar A: cədvəl BİRDİR) və
statusun/foto qaydasının hər dəyişikliyi İKİ yerdə təkrarlanmalı olardı —
`migrations/037` başlığının açıq şəkildə qaçındığı vəziyyət. Üçüncü şablon
isə üçüncü sinif tələb edərdi, halbuki kataloq dizaynının bütün məqsədi yeni
şablonun BİR `INSERT` olmasıdır.

Ona görə burada TƏK aqreqat var və şablon fərqi MƏLUMATDADIR
(`FieldReportTemplate.requires_checklist`, kataloqdan oxunur). Bu faylda
`if report_type == "STORE_AUDIT"` NƏ VAR, NƏ DƏ OLMALIDIR.

──────────────────────────────────────────────────────────────────────────────
`photo_required` NİYƏ DB-DƏ DEYİL, DOMENDƏ MƏCBUR EDİLİR
──────────────────────────────────────────────────────────────────────────────
`migrations/037` bunu açıq yazır: yükləmə ASİNXRONDUR (lokal SQLite spool →
Drive), yəni istinad sətirdən SONRA gələ bilər; DB `CHECK`-i oflayn terminalda
checklist yazılmasını ÜMUMİYYƏTLƏ bloklayardı.

Domen qaydası isə daha dardır və məhz ona görə tətbiq edilə bilir: foto
bəndin CAVABLANMASI anında tələb olunur, sətrin YARANMASI anında yox.
Yəni `passed is None` (hələ yoxlanılmayıb) bənd fotosuz sərbəst yaradılır,
lakin "keçdi/keçmədi" yazılan anda `photo_ref` MÜTLƏQ olmalıdır — çünki
məhz həmin an sübutun mövcudluğunun yoxlanıla biləcəyi yeganə andır.
`photo_ref` növbənin lokal açarı da ola bilər (Drive istinadı sonra onu
əvəz edir, `attach_photo`) — vacib olan sübutun ÇƏKİLMİŞ olmasıdır,
şəbəkənin işləməsi yox.

──────────────────────────────────────────────────────────────────────────────
NİYƏ HADİSƏ YALNIZ TƏQDİMATDA
──────────────────────────────────────────────────────────────────────────────
Bax `domain.events.FieldReportSubmittedEvent` başlığı — bağlanma/redaktə
hadisə yaymır, audit isə hər halda MƏCBURİDİR (use case qatında).
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from src.domain.entities.base import (
    AggregateRoot,
    DomainRuleError,
    InvalidStateTransitionError,
)
from src.domain.events import FieldReportSubmittedEvent
from src.domain.value_objects.field_reports import FieldReportStatus
from src.domain.value_objects.identifiers import (
    EmployeeId,
    FieldReportId,
    FieldReportItemId,
    StoreId,
    TenantId,
)
from src.domain.value_objects.scheduling import require_aware

#: `field_reports.detail` CHECK-inin güzgüsü (migrations/037: `>= 5`).
#: Bu, DÖŞƏMƏDİR, siyasət DEYİL — miqrasiya başlığı bunu açıq yazır:
#: "buradakı ədədlər yalnız ABSURD dəyəri kəsən döşəmədir". Həqiqi minimum
#: `system_limits.FIELD_REPORT_MIN_DETAIL_LENGTH`-dədir və use case onu
#: `min_detail_length` arqumenti ilə ötürür.
SCHEMA_MIN_DETAIL_LENGTH: Final = 5

#: `field_report_checklist_items.item_text` CHECK-inin güzgüsü (`>= 3`).
SCHEMA_MIN_ITEM_TEXT_LENGTH: Final = 3

#: `photo_refs` massivinin defolt tavanı — FALLBACK-dır, həqiqi mənbə
#: `system_limits.FIELD_REPORT_MAX_PHOTOS`. Tavan ÜMUMİYYƏTLƏ niyə var:
#: `TEXT[]` massivi hədsiz böyüyə bilər və hər istinad Drive-da bir fayl
#: deməkdir — səhvən dövrəyə düşmüş yükləmə kvotanı bir hesabatla yandırardı.
FALLBACK_MAX_PHOTOS: Final = 10


class FieldReportChecklistItem:
    """Auditin BİR checklist bəndi — `field_report_checklist_items` sətri.

    `AggregateRoot` DEYİL: bəndin müstəqil həyat dövrü yoxdur, valideyn
    hesabatla birlikdə yaranır və onunla birlikdə yazılır (birləşmiş FK
    `(tenant_id, report_id)`, `ON DELETE CASCADE`). Hadisəni də valideyn
    yayır — bənd başına hadisə 40 bəndlik auditdə 40 hadisə deməkdir və
    heç bir abunəçi onları ayrı-ayrılıqda emal etmir (YAGNI).
    """

    def __init__(
        self,
        *,
        item_id: FieldReportItemId,
        tenant_id: TenantId,
        report_id: FieldReportId,
        position_no: int,
        item_text: str,
        created_at: datetime,
        updated_at: datetime,
        passed: bool | None = None,
        is_blocking: bool = False,
        photo_required: bool = False,
        photo_ref: str | None = None,
        note: str | None = None,
    ) -> None:
        cleaned_text = " ".join(item_text.split())
        if len(cleaned_text) < SCHEMA_MIN_ITEM_TEXT_LENGTH:
            raise DomainRuleError(
                f"Checklist bəndinin mətni minimum {SCHEMA_MIN_ITEM_TEXT_LENGTH} simvol olmalıdır",
                user_message="Checklist bəndinin mətni çox qısadır.",
                context={"item_text": item_text},
            )
        if position_no < 1:
            # `CHECK (position_no >= 1)` güzgüsü. Sıra 1-dən başlayır, çünki
            # ekran onu istifadəçiyə "1-ci bənd" kimi göstərir — 0-dan
            # başlayan sıra ekranda bir addım sürüşmə yaradardı.
            raise DomainRuleError(
                "Checklist bəndinin sırası 1-dən kiçik ola bilməz",
                user_message="Checklist sırası düzgün deyil.",
                context={"position_no": position_no},
            )

        self.id = item_id
        self.tenant_id = tenant_id
        self.report_id = report_id
        self.position_no = position_no
        self.item_text = cleaned_text
        self.is_blocking = is_blocking
        self.photo_required = photo_required
        self.photo_ref = _clean_optional(photo_ref)
        self.note = _clean_optional(note)
        self.created_at = require_aware(created_at, field="created_at")
        self.updated_at = require_aware(updated_at, field="updated_at")

        # Cavab ƏN SONDA verilir ki, foto qaydası artıq qurulmuş `photo_ref`
        # üzərində işləsin — əks halda konstruktor sırası qaydanı kor edərdi.
        self.passed: bool | None = None
        if passed is not None:
            self._apply_answer(passed)

    # ------------------------------ yazı yolu --------------------------------- #

    def answer(
        self,
        *,
        passed: bool,
        now: datetime,
        note: str | None = None,
        photo_ref: str | None = None,
    ) -> None:
        """Bəndi cavablayır (keçdi/keçmədi) — foto qaydası BURADA işləyir."""
        if photo_ref is not None:
            self.photo_ref = _clean_optional(photo_ref)
        if note is not None:
            self.note = _clean_optional(note)
        self._apply_answer(passed)
        self.updated_at = require_aware(now, field="now")

    def attach_photo(self, *, photo_ref: str, now: datetime) -> None:
        """Drive istinadını yazır — növbə yükləməni bitirdikdə çağırılır.

        Cavabı DƏYİŞMİR: bu, infrastruktur tamamlanmasıdır, yeni iş qərarı
        deyil (`EmployeeDocumentUseCase.attach_uploaded_file` ilə eyni ayrım).
        """
        cleaned = _clean_optional(photo_ref)
        if cleaned is None:
            raise DomainRuleError(
                "Foto istinadı boş ola bilməz",
                user_message="Şəkil istinadı boşdur.",
                context={"item_id": str(self.id)},
            )
        self.photo_ref = cleaned
        self.updated_at = require_aware(now, field="now")

    def _apply_answer(self, passed: bool) -> None:
        if self.photo_required and self.photo_ref is None:
            raise DomainRuleError(
                "Foto tələb edən bənd sübutsuz cavablana bilməz",
                user_message=(
                    f"«{self.item_text}» bəndi üçün foto-sübut məcburidir — şəkil əlavə edin."
                ),
                context={"item_id": str(self.id), "position_no": self.position_no},
            )
        self.passed = passed

    # ------------------------------ göstəricilər ------------------------------ #

    @property
    def is_answered(self) -> bool:
        """Bəndə cavab verilibmi (`count(passed)` SQL aqreqatının güzgüsü)."""
        return self.passed is not None

    @property
    def is_blocking_failure(self) -> bool:
        """Bu bənd düzəliş tapşırığı doğururmu.

        `passed is False` — `not self.passed` DEYİL: cavabsız bənd (`None`)
        uğursuz SAYILMIR. `migrations/037`-dəki qismən indeksin predikatı
        (`WHERE passed IS FALSE AND is_blocking`) məhz budur; iki tərəf
        fərqlənsəydi, indeks tapmadığı sətir üçün tapşırıq yaranardı.
        """
        return self.passed is False and self.is_blocking

    def __repr__(self) -> str:
        return (
            f"FieldReportChecklistItem(no={self.position_no}, "
            f"passed={self.passed}, blocking={self.is_blocking})"
        )


class FieldReport(AggregateRoot):
    """Bir sahə hesabatı — şablonu `report_type` sütununda yaşayır."""

    def __init__(
        self,
        *,
        report_id: FieldReportId,
        tenant_id: TenantId,
        report_type: str,
        category: str,
        store_id: StoreId,
        reported_by: EmployeeId,
        detail: str,
        created_at: datetime,
        updated_at: datetime,
        photo_refs: tuple[str, ...] = (),
        status: FieldReportStatus = FieldReportStatus.SUBMITTED,
        items: tuple[FieldReportChecklistItem, ...] = (),
        resolved_by: EmployeeId | None = None,
        resolved_at: datetime | None = None,
        resolution_note: str | None = None,
        min_detail_length: int = SCHEMA_MIN_DETAIL_LENGTH,
        emit_created_event: bool = True,
    ) -> None:
        super().__init__()
        cleaned_type = report_type.strip().upper()
        cleaned_category = category.strip().upper()
        cleaned_detail = " ".join(detail.split())
        # Döşəmə HƏMİŞƏ tətbiq olunur: Root `system_limits`-də 0 yazsa belə
        # sxem `CHECK`-i sətri rədd edərdi və ekran anlaşılmaz DB xətası
        # göstərərdi (`google_drive`-dakı "konfiqurasiya qorumanı söndürə
        # bilməz" qərarı ilə eyni ruh).
        threshold = max(SCHEMA_MIN_DETAIL_LENGTH, min_detail_length)
        if len(cleaned_detail) < threshold:
            raise DomainRuleError(
                f"Hesabatın təsviri minimum {threshold} simvol olmalıdır",
                user_message="Nə müşahidə etdiyinizi daha ətraflı yazın.",
                context={"length": len(cleaned_detail)},
            )
        if not cleaned_type or not cleaned_category:
            raise DomainRuleError(
                "Hesabatın şablonu və kateqoriyası boş ola bilməz",
                user_message="Hesabat növü və kateqoriya seçilməlidir.",
                context={"report_type": report_type, "category": category},
            )
        # `chk_field_report_resolution` güzgüsü: bağlanmış hesabat KİM və NƏ
        # VAXT sualını cavabsız buraxa bilməz — repo-dan yararsız sətir
        # bərpa edilsə belə.
        if status.is_terminal and (resolved_by is None or resolved_at is None):
            raise DomainRuleError(
                "Bağlanmış hesabat qərar sahibini və anını tələb edir",
                user_message="Hesabat qeydi natamamdır.",
                context={"report_id": str(report_id), "status": status.value},
            )

        self.id = report_id
        self.tenant_id = tenant_id
        self.report_type = cleaned_type
        self.category = cleaned_category
        self.store_id = store_id
        self.reported_by = reported_by
        self.detail = cleaned_detail
        self.photo_refs = _dedupe_refs(photo_refs)
        self.status = status
        self.items = items
        self.resolved_by = resolved_by
        self.resolved_at = (
            require_aware(resolved_at, field="resolved_at") if resolved_at is not None else None
        )
        self.resolution_note = _clean_optional(resolution_note)
        self.created_at = require_aware(created_at, field="created_at")
        self.updated_at = require_aware(updated_at, field="updated_at")

        # Repository-dən BƏRPA hadisə YAYMIR (`emit_created_event=False`) —
        # əks halda hər oxu "yeni hesabat təqdim edildi" bildirişi doğurar və
        # marşrutlanan rol eyni insidenti onlarla dəfə alardı.
        if emit_created_event:
            self.record_event(
                FieldReportSubmittedEvent(
                    tenant_id=tenant_id,
                    actor_id=reported_by,
                    report_id=report_id,
                    report_type=cleaned_type,
                    category=cleaned_category,
                    store_id=store_id,
                    reported_by=reported_by,
                    blocking_failures=len(self.blocking_failures),
                )
            )

    # ------------------------------ göstəricilər ------------------------------ #

    @property
    def blocking_failures(self) -> tuple[FieldReportChecklistItem, ...]:
        """Düzəliş tapşırığı doğuran bəndlər (Struktur Qərar B-nin girişi)."""
        return tuple(item for item in self.items if item.is_blocking_failure)

    @property
    def answered_count(self) -> int:
        return sum(1 for item in self.items if item.is_answered)

    @property
    def passed_count(self) -> int:
        return sum(1 for item in self.items if item.passed is True)

    @property
    def audit_score(self) -> float | None:
        """Cavablanmış bəndlərin neçə faizi keçib — Benchmark metrikinin domen tərəfi.

        `None` = heç bir bənd cavablanmayıb. SIFIR QAYTARMIR: "0% keçdi" ilə
        "hələ heç nə yoxlanılmayıb" tamamilə fərqli hallardır və birincisini
        ikincisi kimi göstərmək filialı əsassız olaraq reytinqin dibinə
        salardı (`benchmark_repository`-dəki "məlumatı olmayan filial dict-də
        YOXDUR" qərarının eynisi).
        """
        answered = self.answered_count
        if answered == 0:
            return None
        return 100.0 * self.passed_count / answered

    # -------------------------------- yazı ------------------------------------ #

    def add_photo(
        self, *, photo_ref: str, now: datetime, max_photos: int = FALLBACK_MAX_PHOTOS
    ) -> None:
        """Hesabata foto istinadı əlavə edir (təkrar istinad SÜKUTLA atılır).

        TƏKRAR NİYƏ İSTİSNA ATMIR: eyni yükləmə növbə tərəfindən iki dəfə
        təsdiqlənə bilər (icarəsi bitmiş işçi + yenisi) və bu, istifadəçinin
        səhvi DEYİL — infrastruktur təkrarıdır. İstisna atsaydıq, geri
        çağırış çökər və növbə elementi əbədi `PROCESSING`-də qalardı.
        """
        cleaned = _clean_optional(photo_ref)
        if cleaned is None:
            raise DomainRuleError(
                "Foto istinadı boş ola bilməz",
                user_message="Şəkil istinadı boşdur.",
                context={"report_id": str(self.id)},
            )
        if cleaned in self.photo_refs:
            return
        ceiling = max(1, max_photos)
        if len(self.photo_refs) >= ceiling:
            raise DomainRuleError(
                f"Bir hesabata maksimum {ceiling} şəkil əlavə edilə bilər",
                user_message=f"Bir hesabata ən çoxu {ceiling} şəkil əlavə edilə bilər.",
                context={"report_id": str(self.id), "max_photos": ceiling},
            )
        self.photo_refs = (*self.photo_refs, cleaned)
        self.updated_at = require_aware(now, field="now")

    def start_progress(self, *, now: datetime) -> None:
        """`SUBMITTED` → `IN_PROGRESS` — "bunu mən götürdüm" siqnalı."""
        if self.status is not FieldReportStatus.SUBMITTED:
            raise InvalidStateTransitionError(
                "Yalnız təzə təqdim edilmiş hesabat icraya götürülə bilər",
                user_message="Bu hesabat artıq icradadır və ya bağlanıb.",
                context={"report_id": str(self.id), "status": self.status.value},
            )
        self.status = FieldReportStatus.IN_PROGRESS
        self.updated_at = require_aware(now, field="now")

    def close(
        self,
        *,
        status: FieldReportStatus,
        closed_by: EmployeeId,
        note: str,
        now: datetime,
        min_note_length: int = SCHEMA_MIN_DETAIL_LENGTH,
    ) -> None:
        """`RESOLVED` və ya `DISMISSED` — TERMİNAL keçid.

        İKİ AYRI METOD (`resolve`/`dismiss`) YAZILMADI: hər ikisi eyni üç
        sütunu (`resolved_by`, `resolved_at`, `resolution_note`) eyni
        qaydalarla doldurur və yeganə fərq yazılan status dəyəridir — ayrı
        metodlar həmin qaydaları iki nüsxədə saxlayardı (bu faylın başlığındakı
        "iki sinif yox" qərarının kiçik miqyaslı təkrarı).

        QEYD MƏCBURİDİR: "həll edildi" sözünün sahibi olmalıdır. Əsassız
        sayılan hesabat üçün bu, daha da vacibdir — bildirən işçi niyə rədd
        edildiyini görməlidir, əks halda ikinci dəfə bildirməkdən çəkinər.
        """
        if status.is_open:
            raise InvalidStateTransitionError(
                "Bağlanma yalnız RESOLVED və ya DISMISSED ola bilər",
                user_message="Hesabat yalnız «həll edildi» və ya «əsassız» kimi bağlanır.",
                context={"status": status.value},
            )
        if self.status.is_terminal:
            raise InvalidStateTransitionError(
                "Bağlanmış hesabat yenidən bağlana bilməz",
                user_message="Bu hesabat artıq bağlanıb.",
                context={"report_id": str(self.id), "status": self.status.value},
            )
        cleaned_note = " ".join(note.split())
        threshold = max(SCHEMA_MIN_DETAIL_LENGTH, min_note_length)
        if len(cleaned_note) < threshold:
            raise DomainRuleError(
                f"Bağlanma qeydi minimum {threshold} simvol olmalıdır",
                user_message="Nə edildiyini (və ya niyə əsassız sayıldığını) yazın.",
                context={"length": len(cleaned_note)},
            )
        aware_now = require_aware(now, field="now")
        self.status = status
        self.resolved_by = closed_by
        self.resolved_at = aware_now
        self.resolution_note = cleaned_note
        self.updated_at = aware_now

    def __repr__(self) -> str:
        return (
            f"FieldReport(id={self.id}, type={self.report_type}, "
            f"category={self.category}, status={self.status.value}, "
            f"items={len(self.items)})"
        )


def _clean_optional(value: str | None) -> str | None:
    """Boş/yalnız-boşluqlu mətni `None`-a çevirir.

    `photo_refs`-in DB `CHECK (NOT ('' = ANY (photo_refs)))` şərti ilə eyni
    məqsəd: "şəkil var" kimi görünüb heç nəyə açılmayan istinad ən pis
    haldır — mübahisədə sübut gözlənilir, tapılmır.
    """
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _dedupe_refs(refs: tuple[str, ...]) -> tuple[str, ...]:
    """Boş elementləri atır və təkrarları BİRLƏŞDİRİR (sıra qorunur).

    Sıra qorunur, çünki şəkillər çəkilmə ardıcıllığı ilə göstərilir və
    `set` istifadə etsəydik, hesabat hər açılışda başqa sıra ilə görünərdi
    (`field_report_checklist_items.position_no` ilə eyni əsaslandırma).
    """
    seen: dict[str, None] = {}
    for ref in refs:
        cleaned = _clean_optional(ref)
        if cleaned is not None:
            seen.setdefault(cleaned, None)
    return tuple(seen)


__all__ = [
    "FALLBACK_MAX_PHOTOS",
    "SCHEMA_MIN_DETAIL_LENGTH",
    "SCHEMA_MIN_ITEM_TEXT_LENGTH",
    "FieldReport",
    "FieldReportChecklistItem",
]
