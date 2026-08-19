"""Cərimə aqreqatı (spesifikasiya bölmə 4, 6).

İKİ MƏNBƏ:
    AUTO_DELAY    — 3-STEP axınından avtomatik (gecikmə düsturu).
    MANUAL_CAMERA — Kamera Operatorunun müşahidəsi (foto sübutu MƏCBURİ).

DƏYİŞMƏZLİK QAYDASI (bölmə 4): "orijinal qeyd heç vaxt silinmir (yalnız
«REVERSED» statusu əlavə olunur)".

──────────────────────────────────────────────────────────────────────────────
İKİ MƏRHƏLƏLİ GÖRÜNMƏ (qərar dəyişikliyi — migration 003)
──────────────────────────────────────────────────────────────────────────────
Cərimə YARADILDIĞI AN işçiyə GÖRÜNMÜR:

    PENDING_REVIEW → (Aylıq İcmal, "Bütün Filiallara Göndər") → PUBLISHED
                   → (etiraz və ya idarə qərarı)              → REVERSED/REDUCED

`PENDING_REVIEW` mərhələsində yalnız cəriməni QEYDƏ ALAN kamera operatoru
onu öz fəaliyyət siyahısında görür — işçi, mağaza meneceri və HR görmür.

──────────────────────────────────────────────────────────────────────────────
72 SAAT `published_at`-DAN HESABLANIR — ƏN VACİB DETAL
──────────────────────────────────────────────────────────────────────────────
Cərimə həftələrlə icmalda qala bilər. Sayğac yaradılışdan başlasaydı, işçi
cəriməni GÖRMƏMİŞ onun etiraz müddəti bitə bilərdi — bu, həm ədalətsizlik,
həm hüquqi risk olardı. Ona görə pəncərə `publish()` anında açılır.

EXPORT KİLİDİ (bölmə 6, HÜQUQİ RİSK) — DÖRD ŞƏRT: cərimə Premiya&Cərimə
hesabatına YALNIZ (a) statusu `PUBLISHED` olduqda, (b) etiraz pəncərəsi
`published_at`-dan hesablanaraq bağlandıqda, (c) əvvəllər export olunmadıqda
VƏ (d) ona qarşı QƏRAR VERİLMƏMİŞ etiraz olmadıqda düşür. `PENDING_REVIEW`
HEÇ VAXT export-a düşmür: işçi onu nə görüb, nə də etiraz hüququ alıb.

──────────────────────────────────────────────────────────────────────────────
DÖRDÜNCÜ ŞƏRT NİYƏ ƏLAVƏ OLUNDU (M-6)
──────────────────────────────────────────────────────────────────────────────
Əvvəl üç şərt var idi və aralarında bir boşluq gizlənirdi: işçi 71-ci saatda
etiraz göndərirdi, 72-ci saatda pəncərə bağlanırdı, HR isə hələ baxmamış
olurdu. Həmin an cərimə export-a "hazır" sayılırdı — yəni PUL KƏSİLİRDİ,
etiraza isə heç vaxt qərar verilməmişdi. `cron_close_expired_appeals`
funksiyasının şərhi bu davranışı hərfən yazırdı: "export kilidini açır".

HR-ın baxmaması işçinin günahı deyil. Ona görə pəncərənin bağlanması artıq
kilidi AÇMIR: qərarı gözləyən etiraz cəriməni MÜBAHİSƏLİ saxlayır və o,
qərar verilənə qədər hesabata düşmür. Kilid əbədi deyil — HR etirazı
təsdiqləyəndə və ya rədd edəndə açılır (bax `appeal.py`: müddəti bitmiş
etiraz da qərar ala bilər).

RƏDD EDİLƏN ALTERNATİV: "pəncərə bağlananda gözləyən etirazı avtomatik rədd
et" — bu, HR-ın süstlüyünü işçinin cibindən ödəyən qayda olardı.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID

from src.domain.entities.base import AggregateRoot, DomainRuleError
from src.domain.events import FineIssuedEvent, FineReversedEvent
from src.domain.value_objects.identifiers import (
    AppealId,
    EmployeeId,
    FineId,
    FineReviewBatchId,
    FineTypeId,
    LeaveRequestId,
    StoreId,
    TenantId,
)
from src.domain.value_objects.money import Money
from src.domain.value_objects.scheduling import require_aware

DEFAULT_APPEAL_WINDOW_HOURS = 72
MIN_REVERSAL_REASON_LENGTH = 10


class FineSource(str, Enum):
    AUTO_DELAY = "AUTO_DELAY"
    MANUAL_CAMERA = "MANUAL_CAMERA"


class FineStatus(str, Enum):
    """DB-dəki `fine_status` enum-u ilə eynidir.

    Köhnə `ACTIVE` dəyəri ÇIXARILIB: yeni modeldə onun mənası `PUBLISHED`
    ilə üst-üstə düşürdü və iki sinonim status sorğularda "hansını
    yoxlamalıyam?" sualı yaradardı (migration 003 mövcud sətirləri
    `ACTIVE` → `PUBLISHED` çevirir).
    """

    PENDING_REVIEW = "PENDING_REVIEW"
    PUBLISHED = "PUBLISHED"
    REVERSED = "REVERSED"
    REDUCED = "REDUCED"


#: Premiya&Cərimə export-una düşə bilən statuslar (bölmə 6).
#: `REDUCED` daxildir — bax `Fine.is_exportable` izahı.
EXPORTABLE_STATUSES = frozenset({FineStatus.PUBLISHED, FineStatus.REDUCED})


class Fine(AggregateRoot):
    """Cərimə qeydi."""

    def __init__(
        self,
        *,
        fine_id: FineId,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        store_id: StoreId,
        source: FineSource,
        amount: Money,
        issued_at: datetime,
        appeal_window_hours: int = DEFAULT_APPEAL_WINDOW_HOURS,
        fine_type_id: FineTypeId | None = None,
        leave_request_id: LeaveRequestId | None = None,
        issued_by: EmployeeId | None = None,
        photo_evidence_url: str | None = None,
        idempotency_key: UUID | None = None,
    ) -> None:
        super().__init__()
        require_aware(issued_at, field="issued_at")
        amount.require_non_negative(field="cərimə məbləği")

        # Mənbəyə görə məcburi sahələr (DB CHECK-ləri ilə eyni).
        if source is FineSource.MANUAL_CAMERA:
            if fine_type_id is None:
                raise DomainRuleError(
                    "Manual cərimə üçün Cərimə Növü seçilməlidir — operator "
                    "sərbəst məbləğ təyin edə bilməz (anti-fraud, bölmə 4)"
                )
            if not photo_evidence_url:
                raise DomainRuleError(
                    "Manual cərimə üçün foto sübutu MƏCBURİDİR (bölmə 4)",
                    user_message="Cərimə üçün foto şəkil sübutu əlavə edilməlidir.",
                )
            if issued_by is None:
                raise DomainRuleError("Manual cərimə üçün operator ID məcburidir")
        elif leave_request_id is None:
            raise DomainRuleError("AUTO_DELAY cəriməsi bir icazə sorğusuna bağlanmalıdır")

        self.id = fine_id
        self.tenant_id = tenant_id
        self.employee_id = employee_id
        self.store_id = store_id
        self.source = source
        self.amount = amount
        self.original_amount = amount
        self.issued_at = issued_at
        self.fine_type_id = fine_type_id
        self.leave_request_id = leave_request_id
        self.issued_by = issued_by
        self.photo_evidence_url = photo_evidence_url
        #: D7 audit tapıntısı — İKİQAT GÖNDƏRİŞ ZƏMANƏTİNİN DB YARISI. GUI
        #: FORMA AÇILANDA bir dəfə yaradır (`ManualFineUseCase.issue()`
        #: başlığı), hər klikdə YOX. `fines`-də QİSMƏN unikal indeks
        #: (`WHERE source='MANUAL_CAMERA' AND idempotency_key IS NOT NULL`)
        #: eyni açarla ikinci sətri REDD edir — `_find_recent_duplicate()`
        #: (application qatı) YALNIZ SÜRƏTLİ YOLDUR, ƏSAS zəmanət BURADAN,
        #: DB-dən gəlir (CLAUDE.md §5: hər qayda iki yerdə).
        self.idempotency_key = idempotency_key

        # Cərimə GÖRÜNMƏYƏN vəziyyətdə doğulur — `publish()` onu açır.
        self.status = FineStatus.PENDING_REVIEW
        self.appeal_window_hours = appeal_window_hours
        self.published_at: datetime | None = None
        self.reviewed_by: EmployeeId | None = None
        self.review_decision_reason: str | None = None
        #: Nəşrdən ƏVVƏL `None` — sayğac hələ başlamayıb.
        self.appeal_window_closes_at: datetime | None = None
        self.reversed_by: EmployeeId | None = None
        self.reversed_at: datetime | None = None
        self.reversal_reason: str | None = None
        self.exported_period: str | None = None
        #: Hansı Aylıq İcmal partiyasında qərar verildi (SEC-8 audit tapıntısı).
        #: `publish()`/`discard_in_review()` bunu doldurur; `PENDING_REVIEW`
        #: doğulan cərimədə HƏMİŞƏ `None`dur — icmaldan kənar qərar (Saga
        #: kompensasiyası, `leave_verification.undo_create_fine`) da `None`
        #: buraxır, çünki o, TOPLU nəşrin hissəsi deyil.
        self.review_batch_id: FineReviewBatchId | None = None

        # ────────────────────────────────────────────────────────────────────
        # NİYƏ `fines`-DƏ BELƏ BİR SÜTUN YOXDUR
        # ────────────────────────────────────────────────────────────────────
        # Bu bayraq `fine_appeals.status`-un TÖRƏMƏSİDİR: "bu cəriməyə qərar
        # verilməmiş etiraz varmı". Onu ayrıca sütun kimi saxlamaq iki mənbə
        # yaradardı və biri digərindən geri qalanda cərimə ya haqsız
        # bloklanardı, ya haqsız export olunardı. Ona görə dəyər SQL-də
        # `EXISTS (...)` ilə hesablanır (bax `repositories.py::_SELECT`) və
        # burada yalnız YADDAŞDA saxlanılır.
        #
        # Defolt `False` düzgündür: yenicə yaranmış cəriməyə hələ etiraz
        # göndərilə bilməz (o, `PENDING_REVIEW`-dur və işçi onu görmür).
        self.has_open_appeal = False

        self.record_event(
            FineIssuedEvent(
                fine_id=fine_id,
                employee_id=employee_id,
                store_id=store_id,
                source=source.value,
                amount=amount.amount,
                issued_by=issued_by,
                fine_type_id=fine_type_id,
                tenant_id=tenant_id,
                actor_id=issued_by,
            )
        )

    # ------------------------------- nəşr ----------------------------------- #

    @property
    def is_visible_to_employee(self) -> bool:
        """İşçi/mağaza meneceri/HR görünüşlərində göstərilə bilərmi.

        Kamera operatorunun ÖZ fəaliyyət siyahısı bu qaydadan İSTİSNADIR —
        orada cərimə statusundan asılı olmayaraq görünür (o, öz qeydidir).
        """
        return self.status is not FineStatus.PENDING_REVIEW

    def publish(
        self,
        *,
        reviewed_by: EmployeeId,
        published_at: datetime,
        appeal_window_hours: int | None = None,
        review_batch_id: FineReviewBatchId | None = None,
    ) -> None:
        """ "[Bütün Filiallara Göndər]" — cərimə işçiyə açılır.

        Etiraz pəncərəsi MƏHZ BURADA başlayır.

        Args:
            review_batch_id: Bu qərarın aid olduğu Aylıq İcmal partiyası
                (SEC-8). Verilmirsə (məs. gələcək "fərdi nəşr" yolu) `None`
                qalır — sahə MƏCBURİ DEYİL, çünki bütün `publish()` çağırışları
                HƏLƏLİK yalnız `MonthlyFineReviewUseCase.publish_batch()`-dandır.
            appeal_window_hours: Tenant-ın NƏŞR ANINDAKI
                `FINE_APPEAL_WINDOW_HOURS` limiti. Verilmədikdə obyektin
                yaradılışda dondurduğu dəyər işlədilir.

                NİYƏ BURADA DA QƏBUL EDİLİR — cərimə repository-dən BƏRPA
                ediləndə bu sahə sətirdən oxuna bilmir (`fines` cədvəlində
                belə sütun YOXDUR, yalnız hesablanmış `appeal_window_closes_at`
                var), yəni bərpa olunmuş obyektdə həmişə sinif defoltu (72)
                qalırdı. Nəticədə 48 saat təyin etmiş tenant-ın icmaldan
                nəşr etdiyi cərimə yenə 72 saatlıq pəncərə alırdı.

                Alternativ — `fines`-ə yeni sütun əlavə etmək — rədd edildi:
                dəyər NƏŞR anında onsuz da `appeal_window_closes_at`-a
                DONDURULUR (miqrasiya 016), yəni saxlanması təkrar məlumat
                olardı və iki mənbə arasında fərq riski yaradardı.

                Miqrasiya 016-dakı `trg_fine_appeal_window` trigger-i də eyni
                anda eyni limiti oxuyur — bu parametr həmin qaydanın domendəki
                EYNİSİDİR (CLAUDE.md §5: hər qayda iki yerdə eyni olmalıdır).
        """
        require_aware(published_at, field="published_at")
        if self.status is not FineStatus.PENDING_REVIEW:
            raise DomainRuleError(
                f"Yalnız icmal gözləyən cərimə nəşr edilə bilər, cari status: {self.status.value}",
                context={"fine_id": str(self.id), "status": self.status.value},
            )
        if appeal_window_hours is not None:
            if appeal_window_hours <= 0:
                # Sıfır/mənfi pəncərə cəriməni işçiyə göründüyü AN etiraz
                # hüququndan məhrum edərdi — `system_limits`-dəki `min_value`
                # (24 saat) onsuz da bunu bloklayır, lakin limit mənbəyi
                # əlçatmaz olduqda (fallback yolu) domen də susmamalıdır.
                raise DomainRuleError(
                    "Etiraz pəncərəsi müsbət saat olmalıdır",
                    context={"appeal_window_hours": appeal_window_hours},
                )
            self.appeal_window_hours = appeal_window_hours
        self.status = FineStatus.PUBLISHED
        self.published_at = published_at
        self.reviewed_by = reviewed_by
        self.appeal_window_closes_at = published_at + timedelta(hours=self.appeal_window_hours)
        if review_batch_id is not None:
            self.review_batch_id = review_batch_id

    def discard_in_review(
        self,
        *,
        reviewed_by: EmployeeId,
        reviewed_at: datetime,
        reason: str,
        review_batch_id: FineReviewBatchId | None = None,
    ) -> None:
        """İcmalda "Sil" seçimi — qeyd FİZİKİ SİLİNMİR, `REVERSED` olur.

        Bu, `reverse()`-dən fərqlidir: orada cərimə artıq işçiyə görünüb və
        etiraz nəticəsində ləğv olunur. Burada isə heç vaxt görünməyib.

        Args:
            review_batch_id: `publish()`-in eyni-adlı arqumenti ilə EYNİ
                naxış (SEC-8) — icmaldan kənar çağırış (Saga kompensasiyası,
                `leave_verification.undo_create_fine`) `None` buraxır.
        """
        require_aware(reviewed_at, field="reviewed_at")
        if self.status is not FineStatus.PENDING_REVIEW:
            raise DomainRuleError(
                f"Yalnız icmal gözləyən cərimə bu yolla ləğv edilə bilər, "
                f"cari status: {self.status.value}"
            )
        cleaned = reason.strip()
        if len(cleaned) < MIN_REVERSAL_REASON_LENGTH:
            raise DomainRuleError(
                f"Ləğv səbəbi minimum {MIN_REVERSAL_REASON_LENGTH} simvol olmalıdır"
            )
        self.status = FineStatus.REVERSED
        self.amount = Money.zero()
        self.reviewed_by = reviewed_by
        self.review_decision_reason = cleaned
        self.reversed_by = reviewed_by
        self.reversed_at = reviewed_at
        self.reversal_reason = cleaned
        if review_batch_id is not None:
            self.review_batch_id = review_batch_id

    # ------------------------------- etiraz --------------------------------- #

    def mark_appeal_opened(self) -> None:
        """İşçi etiraz göndərdi — cərimə MÜBAHİSƏLİ olur (M-6).

        Qərar verilənə qədər export-a düşmür; `is_appeal_window_open` isə
        toxunulmur, çünki pəncərə vaxt anlayışıdır, bu isə mübahisə faktıdır.
        """
        self.has_open_appeal = True

    def mark_appeal_decided(self) -> None:
        """Etiraza QƏRAR verildi (qəbul və ya rədd) — mübahisə bağlandı.

        Rədd halında da çağırılır: cərimə qüvvədə qalır və artıq export-a
        düşə bilər. Etirazın "cavabsız qalması" isə bu metoda ÇATMIR — məhz
        buna görə qərarsız cərimə hesabatda görünmür.
        """
        self.has_open_appeal = False

    @property
    def requires_payroll_correction(self) -> bool:
        """Export-dan SONRA ləğv/azaldılıb — maaşda düzəliş lazımdır (M-6).

        Bu hal nadirdir, lakin mümkündür: cərimə export olunub (pul kəsilib),
        sonra idarə qərarı ilə `reverse()` edilib. Hesabat faylı artıq
        göndərilib, ona görə düzəliş SİSTEMDƏN KƏNARDA aparılmalıdır və
        məsul şəxs bunu BİLMƏLİDİR — `FineAppealUseCase.approve` məhz bu
        xassəyə baxıb kritik bildiriş göndərir.

        `exported_period` QƏSDƏN SIFIRLANMIR: sətir hansı dövrdə tutulduğunu
        həmişəlik saxlamalıdır, əks halda növbəti export onu YENİDƏN tutardı
        (ikiqat kəsinti).
        """
        return self.exported_period is not None and self.status in (
            FineStatus.REVERSED,
            FineStatus.REDUCED,
        )

    def is_appeal_window_open(self, *, now: datetime) -> bool:
        """Nəşr olunmamış cərimənin pəncərəsi hələ AÇILMAYIB.

        `True` qaytarılır: "bağlanıb" demək export-a icazə vermək olardı.
        """
        require_aware(now, field="now")
        if self.appeal_window_closes_at is None:
            return True
        return now < self.appeal_window_closes_at

    def reverse(
        self,
        *,
        decided_by: EmployeeId,
        decided_at: datetime,
        reason: str,
        appeal_id: AppealId | None = None,
        new_amount: Money | None = None,
    ) -> None:
        """Etirazın nəticəsi: cərimə ləğv və ya azaldılır.

        Orijinal qeyd SİLİNMİR — `original_amount` saxlanılır və yalnız status
        dəyişir (bölmə 4).
        """
        require_aware(decided_at, field="decided_at")
        if self.status is not FineStatus.PUBLISHED:
            # Nəşr olunmamış cəriməyə etiraz ola bilməz — işçi onu görməyib.
            raise DomainRuleError(
                f"Yalnız nəşr olunmuş cərimə ləğv edilə bilər, cari status: {self.status.value}"
            )
        cleaned = reason.strip()
        if len(cleaned) < MIN_REVERSAL_REASON_LENGTH:
            raise DomainRuleError(
                f"Ləğv səbəbi minimum {MIN_REVERSAL_REASON_LENGTH} simvol olmalıdır"
            )

        # D-R2-01 audit tapıntısı: bu yoxlama ƏVVƏL `new_amount.is_positive`
        # budağının İÇİNDƏ idi — orada ÖLÜ QORUMA idi, çünki `is_positive`
        # artıq YALNIZ müsbət ədədləri buraxır və müsbət ədəd `require_
        # non_negative()`-i HEÇ VAXT poza bilməz. Nəticədə mənfi `new_amount`
        # (məs. UI-da səhvən `-` yazılması, ya da API-ni birbaşa çağıran
        # skript) `else` budağına düşüb SÜKUTLA "tam ləğv" kimi işlənirdi —
        # cərimə PUL kəsən əməliyyatdır, "azalt" niyyətinin izsiz "tam ləğv"ə
        # çevrilməsi bu layihənin öz fəlsəfəsini (bölmə 4: cərimə mübahisədə
        # SÜBUT edilə bilməlidir) pozardı. Ona görə yoxlama BUDAQDAN KƏNARA,
        # `new_amount is not None` yoxlanan kimi, ŞƏRTSİZ çıxarılıb.
        if new_amount is not None:
            new_amount.require_non_negative(field="yeni məbləğ")

        if new_amount is not None and new_amount.is_positive:
            if new_amount >= self.original_amount:
                raise DomainRuleError(
                    "Azaldılmış məbləğ orijinaldan kiçik olmalıdır",
                    context={
                        "original": str(self.original_amount),
                        "new": str(new_amount),
                    },
                )
            self.amount = new_amount
            self.status = FineStatus.REDUCED
        else:
            self.amount = Money.zero()
            self.status = FineStatus.REVERSED

        self.reversed_by = decided_by
        self.reversed_at = decided_at
        self.reversal_reason = cleaned

        self.record_event(
            FineReversedEvent(
                fine_id=self.id,
                appeal_id=appeal_id,
                decided_by=decided_by,
                new_amount=self.amount.amount,
                tenant_id=self.tenant_id,
                actor_id=decided_by,
            )
        )

    # ------------------------------- export --------------------------------- #

    def is_exportable(self, *, now: datetime) -> bool:
        """Premiya&Cərimə hesabatına düşə bilərmi (bölmə 6, LOCK MEXANİZMİ).

        Dörd şərt: nəşr olunub + pəncərə bağlıdır + əvvəllər export olunmayıb
        + qərarsız etirazı yoxdur (modul başlığı, M-6).

        `REDUCED` DAXİLDİR: etiraz qismən qəbul olunubsa işçi AZALDILMIŞ
        məbləği yenə ödəyir — onu export-dan çıxarmaq cərimənin sükutla
        sıfırlanması demək olardı. Yalnız tam ləğv (`REVERSED`) kənardadır.
        """
        require_aware(now, field="now")
        if self.status not in EXPORTABLE_STATUSES:
            # PENDING_REVIEW — işçi hələ görməyib; REVERSED — tam ləğv olunub.
            return False
        if self.exported_period is not None:
            return False
        if self.has_open_appeal:
            # MÜBAHİSƏLİ (M-6): etiraz göndərilib, qərar hələ yoxdur. Pul
            # kəsintisi mübahisənin nəticəsindən ƏVVƏL edilə bilməz.
            return False
        return not self.is_appeal_window_open(now=now)

    def mark_exported(self, *, period: str, now: datetime) -> None:
        """Export edilmiş kimi işarələyir (`YYYY-MM`) — təkrar tutulmanın qarşısını alır."""
        if not self.is_exportable(now=now):
            raise DomainRuleError(
                "Bu cərimə hələ export edilə bilməz — etiraz pəncərəsi açıqdır, "
                "qərarsız etiraz var, cərimə ləğv edilib və ya artıq export olunub",
                context={
                    "status": self.status.value,
                    "has_open_appeal": self.has_open_appeal,
                    "published_at": self.published_at.isoformat() if self.published_at else None,
                    "window_closes_at": (
                        self.appeal_window_closes_at.isoformat()
                        if self.appeal_window_closes_at
                        else None
                    ),
                    "already_exported": self.exported_period,
                },
            )
        self.exported_period = period

    def __repr__(self) -> str:
        return (
            f"Fine(id={self.id}, source={self.source.value}, "
            f"amount={self.amount}, status={self.status.value})"
        )


__all__ = [
    "DEFAULT_APPEAL_WINDOW_HOURS",
    # Export filtri infrastruktur qatında da bu DƏSTDƏN qurulur — siyahını
    # SQL-də əl ilə təkrar yazmaq iki mənbə yaradardı (bax `repositories.py`).
    "EXPORTABLE_STATUSES",
    "Fine",
    "FineSource",
    "FineStatus",
]
