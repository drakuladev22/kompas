"""Domen hadisələri — modullar-arası yeganə kommunikasiya vasitəsi.

Spesifikasiya bölmə 1 iki hadisəni açıq şəkildə adlandırır:
`LeaveVerifiedEvent` və `ManualTimeOverrideEvent`. Aşağıdakı qalan hadisələr
Faza 2-də yazılacaq use case-lərin ehtiyac duyacağı skeletlərdir — yalnız
hadisə müqaviləsi (contract) təyin olunur, biznes məntiqi Faza 2-dədir.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from src.shared.event_bus import DomainEvent

# --------------------------------------------------------------------------- #
# Morning Check-in (bölmə 4 — GÜNÜN BAŞLANĞICI)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class MorningCheckInRequestedEvent(DomainEvent):
    """STEP A: işçi Kiosk-da `[İşə Başladım]` basdı → status `🟡`."""

    attendance_record_id: uuid.UUID
    employee_id: uuid.UUID
    store_id: uuid.UUID
    requested_at: datetime
    ntp_verified: bool


@dataclass(frozen=True, kw_only=True)
class MorningCheckInVerifiedEvent(DomainEvent):
    """STEP C (Option A): Kamera Operatoru təsdiqlədi → status `🟢 Mağazada`."""

    attendance_record_id: uuid.UUID
    employee_id: uuid.UUID
    store_id: uuid.UUID
    verified_at: datetime
    operator_id: uuid.UUID
    is_late: bool
    work_mode_start: datetime | None


@dataclass(frozen=True, kw_only=True)
class MorningCheckInRejectedEvent(DomainEvent):
    """STEP C (Rədd yolu): uyğunsuzluq → status `⚪`, HR/Store Manager-ə bildiriş."""

    attendance_record_id: uuid.UUID
    employee_id: uuid.UUID
    store_id: uuid.UUID
    operator_id: uuid.UUID
    reason: str


@dataclass(frozen=True, kw_only=True)
class UnauthorizedAbsenceDetectedEvent(DomainEvent):
    """ "İCAZƏSİZ QAYIB" qaydası (bölmə 4) — gün sonunda avtomatik təyin olunur."""

    employee_id: uuid.UUID
    store_id: uuid.UUID
    absence_date: date


# --------------------------------------------------------------------------- #
# 3-Step Leave Verification (bölmə 4)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class LeaveRequestedEvent(DomainEvent):
    """STEP 1: `[İcazə İstəyirəm]` — `Requested_Time` rəsmi qeydə alındı."""

    leave_request_id: uuid.UUID
    employee_id: uuid.UUID
    store_id: uuid.UUID
    leave_type_id: uuid.UUID
    requested_time: datetime
    ntp_verified: bool


@dataclass(frozen=True, kw_only=True)
class LeaveReturnClaimedEvent(DomainEvent):
    """STEP 2: `[Mən Qayıtdım]` — status `🟡 Gözləyir (Kamera Təsdiqi)`."""

    leave_request_id: uuid.UUID
    employee_id: uuid.UUID
    claimed_at: datetime


@dataclass(frozen=True, kw_only=True)
class LeaveVerifiedEvent(DomainEvent):
    """STEP 3: Kamera Operatoru qayıdışı təsdiqlədi (spesifikasiya bölmə 1).

    `verified_actual_time` — cərimə düsturunun YEGANƏ mənbəyidir; operatorun
    düyməni kliklədiyi vaxt DEYİL (bax bölmə 4 PENALTY LOGIC).
    """

    leave_request_id: uuid.UUID
    employee_id: uuid.UUID
    operator_id: uuid.UUID
    requested_time: datetime
    verified_actual_time: datetime
    delay_minutes: int
    total_minutes: int
    was_manual_override: bool


@dataclass(frozen=True, kw_only=True)
class ManualTimeOverrideEvent(DomainEvent):
    """`[Vaxtı Əllə Təyin Et]` (spesifikasiya bölmə 1 və 4).

    30+ dəqiqəlik fərq `requires_dual_control=True` yaradır və HR_Admin/CEO
    təsdiqinə yönləndirilir.
    """

    leave_request_id: uuid.UUID
    employee_id: uuid.UUID
    operator_id: uuid.UUID
    system_time: datetime
    overridden_time: datetime
    delta_minutes: int
    reason: str
    requires_dual_control: bool


@dataclass(frozen=True, kw_only=True)
class DualControlApprovalRequestedEvent(DomainEvent):
    """İkinci təsdiq gözlənilir — e-poçt fallback kanalına düşür (bölmə 7)."""

    override_id: uuid.UUID
    leave_request_id: uuid.UUID
    operator_id: uuid.UUID
    delta_minutes: int


@dataclass(frozen=True, kw_only=True)
class DualControlDecisionEvent(DomainEvent):
    override_id: uuid.UUID
    approver_id: uuid.UUID
    approved: bool
    reason: str | None


@dataclass(frozen=True, kw_only=True)
class VerificationTimeoutEscalatedEvent(DomainEvent):
    """45 dəqiqəlik timeout — HR_Admin/Store Manager-ə eskalasiya (bölmə 4)."""

    subject_type: str  # "MORNING_CHECK_IN" | "LEAVE_RETURN"
    subject_id: uuid.UUID
    employee_id: uuid.UUID
    store_id: uuid.UUID
    waiting_minutes: int


# --------------------------------------------------------------------------- #
# Cərimələr (bölmə 4)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class FineIssuedEvent(DomainEvent):
    fine_id: uuid.UUID
    employee_id: uuid.UUID
    store_id: uuid.UUID
    source: str  # AUTO_DELAY | MANUAL_CAMERA
    amount: Decimal
    issued_by: uuid.UUID | None
    fine_type_id: uuid.UUID | None


@dataclass(frozen=True, kw_only=True)
class FineAppealSubmittedEvent(DomainEvent):
    appeal_id: uuid.UUID
    fine_id: uuid.UUID
    employee_id: uuid.UUID
    reason: str


@dataclass(frozen=True, kw_only=True)
class FineReversedEvent(DomainEvent):
    """Cərimə ləğv edildi — orijinal qeyd SİLİNMİR, yalnız `REVERSED` statusu."""

    fine_id: uuid.UUID
    appeal_id: uuid.UUID | None
    decided_by: uuid.UUID
    new_amount: Decimal


# --------------------------------------------------------------------------- #
# Növbə & Tabel (bölmə 3, 4)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class ShiftAssignmentChangedEvent(DomainEvent):
    employee_id: uuid.UUID
    shift_date: date
    old_work_mode_id: uuid.UUID | None
    new_work_mode_id: uuid.UUID | None
    changed_by: uuid.UUID


@dataclass(frozen=True, kw_only=True)
class ShiftSwapRequestedEvent(DomainEvent):
    request_id: uuid.UUID
    employee_id: uuid.UUID
    target_date: date
    reason: str


@dataclass(frozen=True, kw_only=True)
class ShiftSwapDecidedEvent(DomainEvent):
    request_id: uuid.UUID
    approver_id: uuid.UUID
    approved: bool
    reason: str | None


@dataclass(frozen=True, kw_only=True)
class AnnualLeaveRequestedEvent(DomainEvent):
    """#28: işçi İLLİK məzuniyyət sorğusu göndərdi.

    `LeaveRequestedEvent` İLƏ QARIŞDIRILMAMALIDIR: o, GÜNDAXİLİ icazənin
    (STEP1) hadisəsidir və dinləyiciləri dəqiqə/cərimə məntiqinə bağlıdır.
    Bu isə GÜN əsaslı, balansdan çıxan uzun-müddətli haqqdır. İki hadisə bir
    sinifdə birləşsəydi, nahar fasiləsi ilə iki həftəlik məzuniyyət eyni
    dinləyiciyə düşərdi (bax `entities/annual_leave.py` başlığı).
    """

    request_id: uuid.UUID
    employee_id: uuid.UUID
    start_date: date
    end_date: date


@dataclass(frozen=True, kw_only=True)
class AnnualLeaveDecidedEvent(DomainEvent):
    """#28: sorğu təsdiqləndi və ya rədd edildi (Shift Swap naxışı).

    `deducted_days` YALNIZ təsdiqdə doludur və TƏSDİQ ANINDA dondurulmuş
    dəyərdir — dinləyici onu yenidən hesablamamalıdır, çünki Shift Matrix
    sonradan dəyişə bilər (migrations/037 `deducted_days` şərhi).
    """

    request_id: uuid.UUID
    approver_id: uuid.UUID
    approved: bool
    reason: str | None
    deducted_days: str | None = None


@dataclass(frozen=True, kw_only=True)
class AnnualLeaveCancelledEvent(DomainEvent):
    """#28: TƏSDİQLƏNMİŞ məzuniyyət ləğv edildi, balans geri qaytarıldı.

    AYRICA HADİSƏDİR, `AnnualLeaveDecidedEvent(approved=False)` DEYİL:
    "menecer rədd etdi" ilə "təsdiq edilmiş plan ləğv olundu" işçi üçün
    tamamilə fərqli hadisələrdir — birincisində plan heç vaxt qurulmayıb,
    ikincisində isə işçi bilet almış ola bilər.
    """

    request_id: uuid.UUID
    employee_id: uuid.UUID
    cancelled_by: uuid.UUID
    restored_days: str


@dataclass(frozen=True, kw_only=True)
class AnnualLeaveEarlyReturnEvent(DomainEvent):
    """#28: işçi məzuniyyətdən ERKƏN qayıtdı — QALAN günlər balansa döndü.

    `AnnualLeaveCancelledEvent`-dən AYRIDIR və səbəb onunla eynidir (bax
    həmin sinfin şərhi): ləğvdə plan HEÇ VAXT icra olunmayıb və günlərin
    HAMISI qayıdır; erkən qayıdışda isə məzuniyyət BAŞLAYIB, bir hissəsi
    xərclənib və sətir `APPROVED` qalır. İki halı bir hadisə ilə ifadə
    etsəydik, abunəçi "neçə gün faktiki istifadə olundu?" sualına cavab
    verə bilməzdi — `restored_days` hər iki halda dolu olardı, `consumed_
    days` isə yalnız birində mənalıdır.
    """

    request_id: uuid.UUID
    employee_id: uuid.UUID
    returned_by: uuid.UUID
    return_date: date
    #: Faktiki xərclənmiş gün — sətrin YENİ `deducted_days` dəyəri.
    consumed_days: str
    restored_days: str


@dataclass(frozen=True, kw_only=True)
class OpenShiftReleasedEvent(DomainEvent):
    """#16 (OP-4): tutulmuş açıq növbə bazara GERİ QAYTARILDI.

    `OpenShiftClaimedEvent`-in əksi DEYİL, ONDAN AYRI hadisədir: tutma
    təqvimə YAZI əlavə edir, geri buraxma isə onu GERİ ALIR və slotu yenidən
    doldurulmalı edir. Abunəçi (məs. gələcək bildiriş kanalı) ikisini
    ayırd edə bilməsəydi, «növbə boşaldı, kimsə götürsün» siqnalı «növbə
    tutuldu» siqnalından fərqlənməzdi.

    `reason` hadisəyə DAXİLDİR: geri buraxmanın səbəbi elanı açan şəxsin
    bilməli olduğu YEGANƏ məlumatdır — o, slotu yenidən doldurmalıdır.
    """

    posting_id: uuid.UUID
    released_by: uuid.UUID
    store_id: uuid.UUID
    shift_date: date
    reason: str


@dataclass(frozen=True, kw_only=True)
class OpenShiftPostedEvent(DomainEvent):
    """#16: admin doldurulmamış slotu "açıq" elan etdi.

    Shift Swap hadisələrindən AYRIDIR: orada dəyişikliyin subyekti KONKRET
    işçidir (`employee_id`), burada isə slot HƏLƏ SAHİBSİZDİR — ona görə
    hadisədə işçi sahəsi yoxdur, mağaza və şablon var.
    """

    posting_id: uuid.UUID
    store_id: uuid.UUID
    shift_date: date
    work_mode_id: uuid.UUID
    posted_by: uuid.UUID


@dataclass(frozen=True, kw_only=True)
class OpenShiftClaimedEvent(DomainEvent):
    """#16: elanı İLK BASAN işçi tutdu — yarışın qalibi artıq bəllidir."""

    posting_id: uuid.UUID
    employee_id: uuid.UUID
    store_id: uuid.UUID
    shift_date: date


@dataclass(frozen=True, kw_only=True)
class DailyAttendanceSheetConfirmedEvent(DomainEvent):
    sheet_id: uuid.UUID
    store_id: uuid.UUID
    sheet_date: date
    confirmed_by: uuid.UUID
    mismatch_count: int


@dataclass(frozen=True, kw_only=True)
class DailyAttendanceSheetReopenedEvent(DomainEvent):
    """Təsdiqlənmiş tabelin imzası İKİ ŞƏXSİN qərarı ilə geri alındı.

    `DailyAttendanceSheetConfirmedEvent`-in əksi DEYİL, ONDAN AYRI hadisədir:
    təsdiq NORMAL axının addımıdır, açılış isə İSTİSNA — audit və hesabat
    tərəfi bu ikisini eyni saya bilməz. Sahələr də fərqlidir: burada
    «kim istədi», «kim təsdiqlədi» və «kimin imzası geri alındı» üç AYRI
    şəxsdir və üçü də saxlanmalıdır.
    """

    sheet_id: uuid.UUID
    store_id: uuid.UUID
    sheet_date: date
    requested_by: uuid.UUID
    approved_by: uuid.UUID
    #: Təsdiqi geri alınan şəxs. `None` ola bilər: sətir köhnə/idxal edilmiş
    #: məlumatdan gəlirsə `confirmed_by` boş qala bilər (sütun `NULL`
    #: qəbul edir) və o halı UYDURMAQ audit izini yalanlaşdırardı.
    previous_confirmed_by: uuid.UUID | None
    reason: str


# --------------------------------------------------------------------------- #
# Tapşırıqlar (bölmə 6)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class TaskAssignedEvent(DomainEvent):
    task_id: uuid.UUID
    assignee_id: uuid.UUID
    assigned_by: uuid.UUID
    deadline: datetime


@dataclass(frozen=True, kw_only=True)
class TaskEvidenceSubmittedEvent(DomainEvent):
    task_id: uuid.UUID
    assignee_id: uuid.UUID
    evidence_count: int


@dataclass(frozen=True, kw_only=True)
class TaskEvidenceReviewedEvent(DomainEvent):
    task_id: uuid.UUID
    reviewer_id: uuid.UUID
    approved: bool
    reason: str | None


@dataclass(frozen=True, kw_only=True)
class TaskDeadlineEscalatedEvent(DomainEvent):
    task_id: uuid.UUID
    assignee_id: uuid.UUID
    assigned_by: uuid.UUID
    overdue_minutes: int


# --------------------------------------------------------------------------- #
# İcazələr & Sistem (bölmə 3)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class PermissionChangedEvent(DomainEvent):
    """Rol-defolt və ya fərdi override dəyişikliyi — tam audit tələb edir."""

    subject_user_id: uuid.UUID | None
    position_id: uuid.UUID | None
    flag_code: str
    old_value: bool | None
    new_value: bool | None
    changed_by: uuid.UUID


@dataclass(frozen=True, kw_only=True)
class SystemLimitChangedEvent(DomainEvent):
    limit_key: str
    old_value: str
    new_value: str
    changed_by: uuid.UUID


@dataclass(frozen=True, kw_only=True)
class FeatureToggleChangedEvent(DomainEvent):
    module_key: str
    enabled: bool
    changed_by: uuid.UUID


# --------------------------------------------------------------------------- #
# Vahid İstisna Motoru (#9, kompasos11.md Faza 3)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class ExceptionRaisedEvent(DomainEvent):
    """Qayda anomaliya tapdı və `exceptions` sətri yarandı.

    `actor_id` `None`-dur və bu, qəsdəndir: istisnanı İNSAN yaratmır,
    planlaşdırılmış qayda yaradır. Süni olaraq işə salan operatoru aktor
    yazsaydıq, audit izində "bu tapıntını o adam elan etdi" kimi yanlış
    məsuliyyət yaranardı.
    """

    exception_id: uuid.UUID
    source: str
    employee_id: uuid.UUID
    store_id: uuid.UUID
    severity: str
    dedupe_key: str | None


@dataclass(frozen=True, kw_only=True)
class ExceptionReviewDecidedEvent(DomainEvent):
    """İstisna bağlandı: `REVIEWED` və ya `DISMISSED` (terminal keçid)."""

    exception_id: uuid.UUID
    source: str
    employee_id: uuid.UUID
    status: str
    decided_by: uuid.UUID
    note: str | None


# --------------------------------------------------------------------------- #
# İşçi sənədləri (#17, kompasos11.md Faza 7)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class EmployeeDocumentRecordedEvent(DomainEvent):
    """Yeni sənəd/müqavilə qeydi yaradıldı.

    YALNIZ YARADILMA hadisə yaradır — redaktə (`update`/`attach_file`) və
    deaktivasiya AYRI hadisə DEYİL, çünki hazırkı heç bir abunəçi onlara
    ehtiyac duymur (YAGNI) və audit izi bunlardan ASILI OLMADAN
    `audit_logs`-dadır (CLAUDE.md §5: audit istisna udmur, hadisə isə
    ƏLAVƏ kanaldır, yeganə deyil). `POSPermissionThreshold` da eyni
    qərarla YALNIZ audit yazır, heç bir hadisə yaymır — bu, ardıcıl naxışdır.
    """

    document_id: uuid.UUID
    employee_id: uuid.UUID
    doc_type: str
    is_blocking: bool
    uploaded_by: uuid.UUID | None


# --------------------------------------------------------------------------- #
# Sahə hesabatları (#26+#27, kompas1.md Faza 3)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class FieldReportSubmittedEvent(DomainEvent):
    """Sahə hesabatı (mağaza auditi VƏ YA insident) təqdim edildi.

    ŞABLON BAŞINA AYRI HADİSƏ YOXDUR — `report_type` sahə kimi daşınır.
    İki hadisə sinfi (`StoreAuditSubmittedEvent` + `IncidentReportedEvent`)
    Struktur Qərar A-nı pozardı: üçüncü şablon əlavə edən adam həm kataloqa
    `INSERT` etməli, həm də YENİ hadisə sinfi yazıb bütün abunəçiləri
    yeniləməli olardı — halbuki kataloq dizaynının bütün məqsədi məhz bunun
    qarşısını almaqdır.

    YALNIZ TƏQDİMAT hadisə yaradır — bağlanma (`resolve`/`dismiss`) AYRI
    hadisə DEYİL: audit izi ondan asılı olmadan `audit_logs`-dadır
    (`EmployeeDocumentRecordedEvent` ilə eyni qərar, CLAUDE.md §5).

    `blocking_failures` sayı hadisədə daşınır, çünki abunəçi üçün "bu
    hesabat düzəliş tapşırığı doğurdumu?" sualı hesabatın ÖZÜNDƏN daha
    vacibdir — cavabı almaq üçün checklist bəndlərini yenidən oxumaq
    lazım gəlməsin.
    """

    report_id: uuid.UUID
    report_type: str
    category: str
    store_id: uuid.UUID
    reported_by: uuid.UUID
    blocking_failures: int


# --------------------------------------------------------------------------- #
# Ünsiyyət və Performans (#19, #20, kompasos11.md Faza 8)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class AnnouncementBroadcastEvent(DomainEvent):
    """#19: yeni elan dərc olundu.

    YALNIZ YARADILMA hadisə yaradır — geri çəkmə (`withdraw`) AYRI hadisə
    DEYİL, çünki audit izi ondan asılı olmadan `audit_logs`-dadır
    (`EmployeeDocumentRecordedEvent` ilə eyni qərar, CLAUDE.md §5).
    """

    announcement_id: uuid.UUID
    scope: str
    store_count: int


@dataclass(frozen=True, kw_only=True)
class PerformanceReviewRecordedEvent(DomainEvent):
    """#20: qiymətləndirmə yazıldı — YENİ dövr VƏ YA eyni dövrün YENİLƏNMƏSİ.

    İkisi arasında fərq YARADILMIR (ayrı `...UpdatedEvent` yoxdur): hər iki
    halda nəticə eynidir — "bu dövr üçün indi bu qiymətlər qüvvədədir" — və
    fərqi bilməli olan yeganə tərəf `audit_logs`-dur (before/after snapshot).
    """

    review_id: uuid.UUID
    employee_id: uuid.UUID
    period: str
    overall_score: Decimal | None


# --------------------------------------------------------------------------- #
# İnfrastruktur & Lisenziya (bölmə 2, 5, 8)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class TimeDriftDetectedEvent(DomainEvent):
    """NTP fərqi 60 saniyəni keçdi → vaxt-kritik əməliyyatlar bloklanır."""

    drift_seconds: float
    ntp_server: str
    machine_name: str


@dataclass(frozen=True, kw_only=True)
class DeviceRegisteredEvent(DomainEvent):
    """Yeni PC özünü qeydiyyata saldı → admin təsdiqi gözlənilir (DEVICE-1)."""

    device_id: str
    machine_name: str
    device_type: str
    #: Telefonla söylənilən qısa kod — admin cihazı bu kodla tapır.
    short_code: str


@dataclass(frozen=True, kw_only=True)
class DeviceApprovedEvent(DomainEvent):
    """Cihaz təsdiqləndi və filiala təyin edildi (DEVICE-1)."""

    device_id: str
    store_id: str
    device_type: str
    #: `None` = AVTOMATİK təsdiq (`DEVICE_APPROVAL_REQUIRED = 0` + tək mağaza).
    #: Süni bir istifadəçi identifikatoru uydurmaq audit izini YALANLAŞDIRARDI:
    #: «kim təsdiqlədi?» sualının doğru cavabı «heç kim, sistem» ola bilər və
    #: tip bunu ifadə edə bilməlidir.
    approved_by: str | None


@dataclass(frozen=True, kw_only=True)
class DeviceBlockedEvent(DomainEvent):
    """Cihaz bloklandı — admin qərarı və ya passivlik həddi (DEVICE-1).

    `automatic` sahəsi AYRICA saxlanılır, `blocked_by is None` yoxlaması ilə
    kifayətlənilmir: audit oxuyan adam «kim etdi» sualına «heç kim» cavabını
    izah edə bilməlidir — «sistem avtomatik» ilə «məlumat itib» arasındakı
    fərq mübahisə halında əhəmiyyətlidir.
    """

    device_id: str
    reason: str
    blocked_by: str | None
    automatic: bool


@dataclass(frozen=True, kw_only=True)
class DeviceFingerprintChangedEvent(DomainEvent):
    """Cihazın aparat izi dəyişdi — BLOKLAMA YOX, xəbərdarlıq (DEVICE-1).

    Səbəb `entities/registered_device.py` başlığındadır: disk dəyişdirmək
    legitim təmirdir, `device_id` faylını köçürmək isə oğurluqdur — ikisini
    yalnız adam ayırd edə bilər.
    """

    device_id: str
    previous_fingerprint: str
    observed_fingerprint: str


@dataclass(frozen=True, kw_only=True)
class DeviceFingerprintAcceptedEvent(DomainEvent):
    """Admin yeni aparat izini QƏBUL etdi — xəbərdarlıq bağlandı (DEVICE-1).

    `DeviceFingerprintChangedEvent` xəbərdarlığı AÇIR, bu isə onu BAĞLAYIR.
    İkisi ayrı hadisədir və qəsdən: audit izində «kim, nə vaxt, hansı dəyəri»
    təsdiqlədiyi görünməlidir — dəyişikliyin özünü sükutla üstündən yazsaydıq,
    təmir ilə köçürməni sonradan ayırd etmək mümkün olmazdı.
    """

    device_id: str
    previous_fingerprint: str
    accepted_fingerprint: str
    accepted_by: str


@dataclass(frozen=True, kw_only=True)
class LocalClockManipulationDetectedEvent(DomainEvent):
    """PC saatı Postgres server vaxtından həddindən çox fərqlənir (TIME-1).

    `TimeDriftDetectedEvent`-DƏN FƏRQİ — və niyə ikisi birləşdirilmədi:

        TimeDriftDetected            → mənbə NTP; ölçmə UDP/123 tələb edir və
                                       mağaza şəbəkəsində tez-tez mümkün olmur.
                                       Nəticə: vaxt-kritik əməliyyat BLOKLANIR.
        LocalClockManipulationDetected → mənbə Postgres; onsuz da açıq olan
                                       bağlantıdan gəlir, yəni HƏMİŞƏ ölçülür.
                                       Nəticə: heç nə BLOKLANMIR.

    Bloklanmamağın səbəbi budur ki, qeydlərin vaxtı artıq serverdən gəlir —
    manipulyasiya onlara TƏSİR EDƏ BİLMİR. Yəni bloklamaq mağazanı
    dayandırardı və müqabilində heç nə qorumazdı. Hadisə isə fırıldaqçılıq
    NİYYƏTİNİN göstəricisidir: saatı dəyişməyə cəhd edən adamın kim olduğunu
    HR_Admin bilməlidir.
    """

    #: Server vaxtı − PC-nin Windows saatı. Müsbət → PC-nin saatı GERİ qalır.
    local_offset_seconds: float
    #: Qüvvədə olan hədd (`LOCAL_CLOCK_MANIPULATION_THRESHOLD_SECONDS`).
    threshold_seconds: float
    machine_name: str


@dataclass(frozen=True, kw_only=True)
class SyncConflictDetectedEvent(DomainEvent):
    """Audit-kritik cədvəldə konflikt → HR_Admin-ə manual həll üçün."""

    table_name: str
    record_id: uuid.UUID
    local_version: str
    remote_version: str


@dataclass(frozen=True, kw_only=True)
class LicenseStatusChangedEvent(DomainEvent):
    tenant_id_value: uuid.UUID
    old_status: str
    new_status: str


__all__ = [
    "AnnouncementBroadcastEvent",
    "AnnualLeaveCancelledEvent",
    "AnnualLeaveDecidedEvent",
    "AnnualLeaveEarlyReturnEvent",
    "AnnualLeaveRequestedEvent",
    "DailyAttendanceSheetConfirmedEvent",
    "DailyAttendanceSheetReopenedEvent",
    "DeviceApprovedEvent",
    "DeviceBlockedEvent",
    "DeviceFingerprintAcceptedEvent",
    "DeviceFingerprintChangedEvent",
    "DeviceRegisteredEvent",
    "DualControlApprovalRequestedEvent",
    "DualControlDecisionEvent",
    "EmployeeDocumentRecordedEvent",
    "ExceptionRaisedEvent",
    "ExceptionReviewDecidedEvent",
    "FeatureToggleChangedEvent",
    "FieldReportSubmittedEvent",
    "FineAppealSubmittedEvent",
    "FineIssuedEvent",
    "FineReversedEvent",
    "LeaveRequestedEvent",
    "LeaveReturnClaimedEvent",
    "LeaveVerifiedEvent",
    "LicenseStatusChangedEvent",
    "LocalClockManipulationDetectedEvent",
    "ManualTimeOverrideEvent",
    "MorningCheckInRejectedEvent",
    "MorningCheckInRequestedEvent",
    "MorningCheckInVerifiedEvent",
    "OpenShiftClaimedEvent",
    "OpenShiftPostedEvent",
    "OpenShiftReleasedEvent",
    "PerformanceReviewRecordedEvent",
    "PermissionChangedEvent",
    "ShiftAssignmentChangedEvent",
    "ShiftSwapDecidedEvent",
    "ShiftSwapRequestedEvent",
    "SyncConflictDetectedEvent",
    "SystemLimitChangedEvent",
    "TaskAssignedEvent",
    "TaskDeadlineEscalatedEvent",
    "TaskEvidenceReviewedEvent",
    "TaskEvidenceSubmittedEvent",
    "TimeDriftDetectedEvent",
    "UnauthorizedAbsenceDetectedEvent",
    "VerificationTimeoutEscalatedEvent",
]
