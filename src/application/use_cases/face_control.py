"""FACE CONTROL (Üz Təsdiqi) use case-ləri — `facecontrol.md` Faza 2.

Face Control PIN-i ƏVƏZ ETMİR: PIN «bilirsən» sualına, üz isə «kimsən»
sualına cavab verir. Bu modul həmin ikinci sualı verən qatdır və mövcud
axınların ÜSTÜNƏ qoyulur.

──────────────────────────────────────────────────────────────────────────────
QIRMIZI XƏTT — MÖVCUD AXINLAR TOXUNULMAZDIR
──────────────────────────────────────────────────────────────────────────────
`MorningCheckInUseCase.start_day` (STEP A), `LeaveVerificationUseCase.
request_leave` (STEP 1) və `claim_return` (STEP 2) İMZALARI VƏ MƏNTİQİ
DƏYİŞMİR. Üz təsdiqi onların İÇİNƏ yazılmır — `FaceVerificationUseCase.verify`
PIN uğurlu olduqdan SONRA, həmin metod çağırılmazdan ƏVVƏL işləyir və bir
QƏRAR (`FaceGateDecision`) qaytarır.

NİYƏ İÇƏRİDƏ DEYİL:
  * hər üç metodun imzasına kamera/matcher asılılığı əlavə etmək lazım
    gələrdi — yəni onların bütün mövcud testləri (və `preview` yolu) sahtə
    kamera tələb edərdi;
  * `verify_return` (STEP 3) Saga-dır; ora ikinci bir uğursuzluq mənbəyi
    salmaq kompensasiya zəncirini biometrik nasazlıqdan asılı edərdi;
  * üz təsdiqi bir MODULDUR (bənd 15: mağaza-səviyyəli açıla bilər) — onu
    struktur axının içinə tikmək həmin qərarı mümkünsüz edərdi.

⚠️ BU QƏRARIN ZƏİF NÖQTƏSİ (AÇIQ SƏNƏDLƏŞDİRİLİR)
──────────────────────────────────────────────────────────────────────────────
Orkestrasiya çağıran tərəfdədir (Faza 4-də kiosk kontrolleri). Deməli GUI-ni
YAN KEÇƏN bir yol — məsələn birbaşa `session.morning_check_in.start_day(...)`
çağıran skript, plugin, və ya gələcək bir API — üz təsdiqini ATLAYA BİLƏR.
Bu, real boşluqdur və gizlədilmir.

Boşluğu bağlayacaq qat: kiosk giriş nöqtəsi TƏK olmalıdır
(`presentation/controllers/kiosk*.py`) və `start_day`/`request_leave`/
`claim_return` yalnız oradan çağırılmalıdır. Faza 4-də həmin kontroller
yazılanda bu, qapı ilə (mənbə mətnini oxuyan test — bu layihədə mövcud naxış,
bax `test_root_control_parameter_parity`) bərkidilməlidir: "STEP A/1/2
çağırışı üz qapısından keçmədən görünürsə, test qırılır".

DB-səviyyəli qoruma (trigger) NİYƏ SEÇİLMƏDİ: trigger `attendance_records`
sətrinə "üz təsdiqlənibmi?" şərtini qoya bilərdi, lakin üz təsdiqi kamera
nasazlığında və istisnalı işçidə QANUNİ olaraq baş vermir — trigger həmin
halları da bloklayardı və mağaza işləməz olardı (fail-closed-un yanlış
tətbiqi: qoruma işi dayandırmamalıdır, onu YÖNLƏNDİRMƏLİDİR).

──────────────────────────────────────────────────────────────────────────────
MÖVCUD MEXANİZMLƏR ÇAĞIRILIR, TƏKRAR YAZILMIR
──────────────────────────────────────────────────────────────────────────────
| Lazım olan            | Nə çağırılır                                        |
|-----------------------|-----------------------------------------------------|
| Şifrələmə             | `EncryptionService` — `FaceEmbeddingRepository`-nin  |
|                       | içində (bax `infrastructure/persistence/face_       |
|                       | repository.py`); use case açıq vektorla işləyir     |
| Lockout MEXANİZMİ     | `evaluate_pin_attempt` + `PinPolicy` (`security/    |
|                       | hashing.py`) — `PinHandshakeUseCase` ilə EYNİ       |
|                       | funksiya, yalnız SAYĞAC və HƏDD ayrıdır             |
| Kilid müddəti         | `PIN_LOCKOUT_MINUTES` — yeni açar YARADILMIR        |
| Kilid istisnası       | `AccountLockedError` (`authentication.py`)          |
| Timeout eskalasiyası  | `VERIFICATION_TIMEOUT` bildiriş kanalı              |
|                       | (`leave_verification.escalate_timeouts` ilə eyni)   |
| Dual-control          | `DUAL_CONTROL_PENDING` kanalı +                     |
|                       | `DUAL_CONTROL_APPROVAL_FLAG` — təsdiqi mövcud       |
|                       | `LeaveVerificationUseCase.approve_dual_control`     |
|                       | verir, ikinci mexanizm yazılmır                     |
| İstisna motoru        | `FaceMismatchExceptionRule` → mövcud reyestr        |
|                       | (`ExceptionEngineUseCase.register_rule`), motorun   |
|                       | kodu DƏYİŞMİR                                       |
| Audit                 | `AuditTrail.record()` — istisna udmur                |
| Bildiriş              | `Notifier` portu                                    |

──────────────────────────────────────────────────────────────────────────────
NİYƏ SAGA YOXDUR
──────────────────────────────────────────────────────────────────────────────
`morning_check_in.py` başlığındakı meyar tətbiq olunur: Saga YALNIZ bir
əməliyyat BİR NEÇƏ AQREQATA toxunduqda lazımdır. Burada ən uzun zəncir
MISMATCH halıdır — sayğac (`employees` üz sütunları) + jurnal sətri, hər
ikisi EYNİ tranzaksiyada və hər ikisi YENİ yazı: uğursuzluqda rollback tam
bərpadır, geri qaytarılası ikinci EFFEKT yoxdur. Hər əməliyyatı Saga-ya
salmaq reconciliation növbəsini mənasız yükləyərdi (SEC-003).

──────────────────────────────────────────────────────────────────────────────
BİOMETRİK MƏLUMATIN QAYDALARI BU FAYLDA NECƏ QORUNUR
──────────────────────────────────────────────────────────────────────────────
  1. FOTO SAXLANMIR — `FaceFrame` yalnız yerli dəyişəndə yaşayır, heç bir
     repo metoduna ötürülmür və metod bitəndə zibil toplayıcıya gedir.
  2. VEKTOR AÇIQ MƏTN DEYİL — şifrələmə repo-nun içindədir (yuxarı bax).
  3. EMAL ON-DEVICE — bu faylda HEÇ BİR şəbəkə çağırışı yoxdur; `FaceMatcher`
     portunun adapteri (Faza 3) lokal kitabxanadır.
  4. LOG-DA VEKTOR YOXDUR — `FaceEmbedding.__repr__`/`FaceFrame.__repr__`
     maskalanıb, `extra={...}` sözlüklərinə isə yalnız nəticə və bal düşür.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import TYPE_CHECKING, Final

from src.application.use_cases.authentication import AccountLockedError
from src.domain.policies import (
    DEFAULT_LIMITS,
    FACE_EXEMPTION_COMPENSATING_MODULE,
    FeatureModule,
    SystemLimitKey,
)
from src.domain.value_objects.exception_signals import (
    FACE_MISMATCH_SOURCE,
    ExceptionFinding,
)
from src.domain.value_objects.face_recognition import (
    FaceControlError,
    FaceEmbedding,
    FaceEnrollmentFrameOutcome,
    FaceExemption,
    FaceProfile,
    FaceToleranceBand,
    FaceTriggerContext,
    FaceVerificationLogEntry,
    FaceVerificationResult,
    LivenessGesture,
    add_months,
    gesture_pool,
    parse_tolerance,
)
from src.domain.value_objects.identifiers import new_face_exemption_id
from src.infrastructure.security.hashing import PinPolicy, evaluate_pin_attempt
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        CameraCapture,
        Clock,
        FaceEmbeddingRepository,
        FaceExemptionRepository,
        FaceMatcher,
        FaceStoreScopeRepository,
        FaceVerificationLogRepository,
        FeatureToggles,
        Notifier,
        SystemLimits,
    )
    from src.domain.value_objects.exception_signals import RuleEvaluationContext
    from src.domain.value_objects.face_recognition import FaceFrame
    from src.domain.value_objects.identifiers import (
        EmployeeId,
        FaceExemptionId,
        StoreId,
        TenantId,
    )

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)


#: 1:N tanınmada ƏN YAXŞI ilə İKİNCİ arasındakı minimum məsafə fərqi.
#:
#: NİYƏ SABİT, NİYƏ ROOT PARAMETRİ: bu, iş qaydası deyil, tanınma alqoritminin
#: statistik təhlükəsizlik payıdır. ROOT-a versəydik, «giriş çətinləşdi»
#: şikayətindən sonra kimsə onu sıfıra endirər və 1:N girişi səssizcə
#: 1:1 dəqiqliyindən aşağı düşərdi — halbuki bütün fərq elə bu paydadır.
#: `match_tolerance` isə ROOT-dadır və qərarın ƏSAS həddini o verir.
_IDENTIFY_MARGIN: Final = 0.08

#: Qeydiyyat MÖVCUD flag ilə qorunur — yeni flag YARADILMIR (bənd 1: "YALNIZ
#: `can_manage_employees` sahibi (admin)"). İşçi bunu ÖZÜ edə bilməz və qayda
#: `_require_enrollment_permission`-dadır: aktor subyektin özüdürsə istisna
#: atılır, çünki `can_manage_employees` sahibi olan bir HR admini də ÖZ üzünü
#: qeydiyyata sala bilməməlidir (nəzarətli proses = ikinci insan).
ENROLLMENT_FLAG: Final = "can_manage_employees"

#: İstisna səlahiyyəti — `can_manage_employees` KİFAYƏT ETMİR (bənd 14).
#: Flag `hardlock_level = 2` ilə elan olunub (migrations/047), yəni onu yalnız
#: Root/CEO daşıya bilər; burada yalnız SAHİBLİK yoxlanılır, hardlock qaydası
#: mövcud `PermissionFlag.assert_grantable_to` + DB trigger-indədir.
MANAGE_EXEMPTIONS_FLAG: Final = "can_manage_face_exemptions"

#: MÖVCUD eskalasiya kanalı (`leave_verification.escalate_timeouts` və
#: `morning_check_in.escalate_timeouts` eyni sətri yazır). Kamera nasazlığında
#: YENİ kanal açmırıq: HR_Admin/CEO-nun «manual təsdiq gözləyir» qutusu ARTIQ
#: var və nasazlıq həmin qutuya düşməlidir — ikinci kanal o qutunun tam
#: olmadığı mənasına gələrdi. Dəyər `test_face_control.py`-də mövcud faylın
#: mətninə qarşı yoxlanılır ki, biri dəyişəndə digəri sükutla ayrılmasın.
ESCALATION_CATEGORY: Final = "VERIFICATION_TIMEOUT"

#: MÖVCUD dual-control kanalı (`leave_verification.apply_override` eyni sətri
#: yazır) — istisnalı işçinin MƏCBURİ ikinci təsdiqi (bənd 14).
DUAL_CONTROL_CATEGORY: Final = "DUAL_CONTROL_PENDING"

#: SEC-020 — kompensasiya edici nəzarətin İTDİYİ hal üçün audit əməliyyatı.
#:
#: NİYƏ AYRI AD: `FACE_EXEMPT_DUAL_CONTROL` sətri «kompensasiya İŞLƏDİ» deməkdir.
#: Kompensasiya ümumiyyətlə mövcud olmadıqda eyni adı yazsaydıq, audit jurnalı
#: iki tamamilə fərqli vəziyyəti eyni sözlə göstərərdi — yəni sonrakı araşdırma
#: «bu işçinin ikinci təsdiqi kim verdi?» sualına heç vaxt cavab tapa bilməzdi.
COMPENSATION_UNAVAILABLE_ACTION: Final = "FACE_EXEMPT_COMPENSATION_UNAVAILABLE"

#: Üz uyğunsuzluğunun TƏCİLİ kanalı (bənd 3: İLK DƏFƏDƏN dərhal bildiriş).
#: İstisna Motoru bunu ƏVƏZ ETMİR (bənd 16) — motorun siyahısı "sonra
#: baxaram" effekti yaradır, MISMATCH isə öz təcili kanalını itirməməlidir.
MISMATCH_CATEGORY: Final = "FACE_MISMATCH"

#: System Health Monitor kanalları (bənd 5, 18).
CAMERA_HEALTH_CATEGORY: Final = "FACE_CAMERA_UNAVAILABLE"
PERFORMANCE_HEALTH_CATEGORY: Final = "FACE_VERIFICATION_SLOW"

#: İstisna səbəbinin minimum uzunluğu — `face_control_exemptions.reason`
#: sütunundakı `CHECK (char_length(trim(reason)) >= 10)` GÜZGÜSÜDÜR, yəni
#: sxem məhdudiyyəti, biznes həddi DEYİL (`MIN_SOURCE_CODE_LENGTH` ilə eyni
#: qərar). Ona görə `system_limits`-ə aid deyil: onu Root-dan aşağı salmaq
#: bazanın rədd edəcəyi dəyər yazmağa icazə vermək olardı.
MIN_EXEMPTION_REASON_LENGTH: Final = 10

#: İstisna Motoru qaydasının geriyə baxış pəncərəsi (gün). ROOT PARAMETRİ
#: DEYİL VƏ BU, QƏSDLİDİR: pəncərənin genişlənməsi HEÇ BİR davranışı
#: dəyişmir — `dedupe_key` eyni uyğunsuzluğun ikinci istisnasını onsuz da
#: bloklayır (bax `FaceMismatchExceptionRule.evaluate`). Yəni bu ədəd siyasət
#: deyil, SORĞU HƏDDİDİR. Dar seçilsəydi isə real itki olardı: terminal iki
#: gün söndürülü qalsa, planlayıcı yalnız SON slotu icra edir (`job_runner.py`
#: — "BİR NEÇƏ GÜN GERİ QAYIDILMIR") və aradakı uyğunsuzluqlar HR-in vahid
#: siyahısına heç vaxt düşməzdi.
MISMATCH_LOOKBACK_DAYS: Final = 7


class FaceControlPermissionError(KompasOSError):
    """Üz təsdiqi əməliyyatı üçün səlahiyyət yoxdur."""

    user_message = "Bu əməliyyat üçün səlahiyyətiniz yoxdur."


class FaceCameraUnavailableError(KompasOSError):
    """Kamera əlçatmazdır — QEYDİYYAT axını üçün (bənd 1).

    DOĞRULAMA axınında bu istisna ATILMIR: orada nasazlıq eskalasiyaya
    çevrilir (bənd 5), çünki kioskda duran işçi xəta ekranı deyil, bir YOL
    gözləyir. Qeydiyyat isə admin-in nəzarətli əməliyyatıdır: orada aydın
    xəta mesajı doğru cavabdır.
    """

    user_message = "Kamera əlçatmazdır. Bağlantını yoxlayın və yenidən cəhd edin."


# --------------------------------------------------------------------------- #
# Tətbiq qatının strukturları
#
# Bunlar QƏSDƏN `ports.py`-da DEYİL: onları domenə qoymaq domen → tətbiq
# asılılığı yaradardı (`ReportFactProvider` / `ExceptionView` ilə eyni qayda,
# CLAUDE.md bölmə 3).
# --------------------------------------------------------------------------- #


class FaceGateOutcome(str, Enum):
    """Üz qapısının qərarı — kiosk kontrolleri (Faza 4) buna görə davranır."""

    #: Üz təsdiqləndi, əməliyyat davam edə bilər.
    ALLOWED = "ALLOWED"
    #: Təsdiqləndi, LAKİN bal aşağı-etibar zolağındadır (bənd 12). Əməliyyat
    #: DAVAM EDİR — qeyd yalnız nişanlanır ki, Kamera Operatoru iVMS
    #: yoxlamasında daha diqqətli olsun.
    ALLOWED_LOW_CONFIDENCE = "ALLOWED_LOW_CONFIDENCE"
    #: Üz görünmədi (texniki) — yenidən cəhd təklif olunur, HEÇ BİR sayğac
    #: artmır (bənd 3).
    RETRY = "RETRY"
    #: Üz uyğun gəlmədi — əməliyyat bloklanır, sayğac artır, dərhal bildiriş.
    BLOCKED = "BLOCKED"
    #: Sayğac həddə çatdı və mövcud lockout mexanizmi işə düşdü (bənd 4).
    LOCKED = "LOCKED"
    #: Kamera nasazdır və ya işçinin qeydiyyatı yoxdur — SƏSSİZ PIN-only YOX,
    #: mövcud eskalasiya kanalı ilə HR_Admin/CEO manual təsdiqinə (bənd 5).
    MANUAL_APPROVAL_REQUIRED = "MANUAL_APPROVAL_REQUIRED"
    #: İşçi Face Control istisnasındadır — MƏCBURİ dual-control (bənd 14).
    DUAL_CONTROL_REQUIRED = "DUAL_CONTROL_REQUIRED"
    #: Modul söndürülüb və ya mağaza pilot əhatəsindən kənardadır (bənd 15).
    NOT_APPLICABLE = "NOT_APPLICABLE"

    @property
    def allows_operation(self) -> bool:
        """Əməliyyat ƏLAVƏ İNSAN QƏRARI OLMADAN davam edə bilərmi.

        `MANUAL_APPROVAL_REQUIRED` və `DUAL_CONTROL_REQUIRED` burada `False`-dur
        və bu, bənd 5 və bənd 14-ün TAM MƏNASIDIR: hər ikisi "üz təsdiqi baş
        vermədi, deməli ikinci insan lazımdır" deməkdir. `True` qaytarsaydıq,
        kamera nasazlığı faktiki olaraq sükutla PIN-only rejimi olardı.
        """
        return self in (
            FaceGateOutcome.ALLOWED,
            FaceGateOutcome.ALLOWED_LOW_CONFIDENCE,
            FaceGateOutcome.NOT_APPLICABLE,
        )


@dataclass(frozen=True)
class FaceGateDecision:
    """Bir doğrulama cəhdinin tam nəticəsi (jurnala yazılan hər şey + qərar)."""

    employee_id: EmployeeId
    trigger_context: FaceTriggerContext
    outcome: FaceGateOutcome
    message_az: str
    result: FaceVerificationResult | None = None
    liveness_action: LivenessGesture | None = None
    confidence_score: float | None = None
    is_low_confidence: bool = False
    matched_other_employee_id: EmployeeId | None = None
    lockout_triggered: bool = False
    locked_until: datetime | None = None
    requires_dual_control: bool = False
    duration_ms: int = 0
    #: Root tərs hədd cütü yazıb və aşağı-etibar zolağı fail-closed söndürülüb.
    tolerance_inverted: bool = False

    @property
    def allows_operation(self) -> bool:
        return self.outcome.allows_operation


@dataclass(frozen=True)
class FaceEnrollmentResult:
    """Qeydiyyat/yenidən-qeydiyyat cəhdinin nəticəsi.

    Kadr-kadr detal SAXLANILIR, çünki operatorun növbəti addımı ondan asılıdır:
    "5 kadrdan 4-ü keçdi" ilə "heç biri keçmədi" fərqli əməliyyatlardır
    (birincidə heç nə, ikincidə işıq/kamera yoxlanılır).
    """

    employee_id: EmployeeId
    accepted: bool
    message_az: str
    frames: tuple[FaceEnrollmentFrameOutcome, ...] = ()
    enrolled_at: datetime | None = None
    #: Yenidən-qeydiyyatda köhnə vektor arxivləndimi (bənd 2).
    archived_previous: bool = False

    @property
    def accepted_frame_count(self) -> int:
        return sum(1 for frame in self.frames if frame.accepted)

    @property
    def retake_required(self) -> bool:
        """«[Yenidən Çək]» düyməsi göstərilsinmi (bənd 1)."""
        return not self.accepted


@dataclass(frozen=True)
class FaceExemptionView:
    """İstisna idarəetmə ekranının bir sətri (Faza 4 GUI-si bunu göstərir)."""

    exemption: FaceExemption
    #: Neçə gün qalıb — mənfi olmur (bitmiş sətir siyahıda görünmür).
    days_remaining: int


# --------------------------------------------------------------------------- #
# 1–2. Qeydiyyat və yenidən-qeydiyyat (bənd 1, 2, 10, 11)
# --------------------------------------------------------------------------- #


class FaceEnrollmentUseCase:
    """Nəzarətli üz qeydiyyatı — SELF-SERVICE DEYİL (bənd 1).

    ADDIM-ADDIM: `FACE_ENROLLMENT_FRAME_COUNT` kadr çəkilir → hər kadr
    alignment-dən keçir (bənd 10, `FaceMatcher.extract` içində) → keyfiyyət
    həddi (`FACE_ENROLLMENT_MIN_QUALITY`) yoxlanılır → KEÇƏNLƏRİN riyazi
    ortası TƏK istinad vektoru kimi saxlanılır (bənd 11).

    ŞİFRƏLƏMƏ BU SİNİFDƏ YOXDUR: `FaceEmbeddingRepository` onu öz içində edir
    (mövcud `EncryptionService`). Use case şifrələsəydi, tətbiq qatı
    infrastruktur sinfini birbaşa tanıyar və "hansı sütun şifrəlidir?" qərarı
    iki qatda yaşayardı.
    """

    def __init__(
        self,
        *,
        profiles: FaceEmbeddingRepository,
        camera: CameraCapture,
        matcher: FaceMatcher,
        limits: SystemLimits,
        audit: AuditTrail,
        clock: Clock,
    ) -> None:
        self._profiles = profiles
        self._camera = camera
        self._matcher = matcher
        self._limits = limits
        self._audit = audit
        self._clock = clock

    def enroll(
        self, *, tenant_id: TenantId, actor: Employee, subject_id: EmployeeId
    ) -> FaceEnrollmentResult:
        """İLK qeydiyyat. Mövcud qeydiyyat varsa RƏDD edilir (bax bənd 2).

        Mövcud vektoru sükutla üstündən yazmaq ən təhlükəli variant olardı:
        arxiv sətri yaranmaz, «bu işçinin üzü neçə dəfə dəyişdirilib?» sualı
        cavabsız qalar və tez-tez yenidən-qeydiyyat naxışı (aldatma əlaməti)
        görünməz olardı. Ona görə yenidən-qeydiyyat AYRI use case-dədir və
        səbəb tələb edir.
        """
        self.assert_may_enroll(actor, subject_id)
        existing = self._profiles.get_profile(subject_id)
        if existing is not None and existing.is_enrolled:
            raise FaceControlError(
                "İşçinin üz qeydiyyatı artıq var — dəyişdirmək üçün "
                "yenidən-qeydiyyat prosesi tələb olunur",
                user_message=(
                    "Bu işçinin üz qeydiyyatı artıq mövcuddur. Dəyişmək üçün "
                    "«Yenidən Qeydiyyat» əməliyyatını işlədin."
                ),
                context={"employee_id": str(subject_id)},
            )
        return self.capture_and_store(
            tenant_id=tenant_id,
            actor=actor,
            subject_id=subject_id,
            action="FACE_ENROLLED",
            reason=None,
            archived=False,
        )

    def stale_enrollments(self, tenant_id: TenantId) -> list[FaceProfile]:
        """«Üz-qeydiyyatı köhnəlib» siyahısı (bənd 13) — YALNIZ TÖVSİYƏ.

        BLOKLAMIR: nə doğrulama, nə giriş dayanır. Kəsim tarixi BURADA
        hesablanır, SQL-də yox — Root `FACE_REENROLLMENT_REMINDER_MONTHS`
        dəyərini dəyişəndə siyahı DƏRHAL yenilənməlidir
        (`break_overuse_for_day` ilə eyni əsaslandırma).
        """
        now = self._clock.now()
        months = self._limit_int(tenant_id, SystemLimitKey.FACE_REENROLLMENT_REMINDER_MONTHS)
        if months <= 0:
            return []
        cutoff = add_months(now, -months)
        return self._profiles.list_stale_enrollments(tenant_id, enrolled_before=cutoff)

    # --------------------- yenidən-qeydiyyat ilə PAYLAŞILAN ------------------ #
    #
    # Aşağıdakı iki metod QƏSDƏN açıqdır (alt xəttsiz): `FaceReEnrollmentUseCase`
    # onları çağırır. Şəxsi (`_`) saxlayıb `noqa: SLF001` ilə keçmək variantı
    # rədd edildi — həmin susdurma "bu, əslində ictimai müqavilədir" faktını
    # gizlədərdi. Kadr çəkilişi/keyfiyyət süzgəci/orta vektor məntiqi TƏK
    # yerdə qalmalıdır: iki nüsxə bir müddət üst-üstə düşər, sonra biri
    # dəyişəndə sükutla ayrılardı.

    def assert_may_enroll(self, actor: Employee, subject_id: EmployeeId) -> None:
        """Bənd 1: yalnız admin, VƏ İŞÇİ ÖZÜ ÜÇÜN YOX.

        SÜKUTLA "heç nə etmə" DEYİL — açıq istisna atılır (CLAUDE.md §6):
        operator düyməni basıb və nəticə gözləyir.

        ÖZÜNƏ-QEYDİYYAT QADAĞASI AYRICA YOXLANILIR: `can_manage_employees`
        sahibi olan HR admini də ÖZ üzünü qeydiyyata sala bilməməlidir, çünki
        bənd 1 prosesin NƏZARƏTLİ (ikinci insanın iştirakı ilə) olmasını tələb
        edir. Yalnız flag yoxlansaydı, admin öz kioskunda tək qalıb istənilən
        üzü öz hesabına bağlaya bilərdi — üz qatının bütün mənası itərdi.
        """
        now = self._clock.now()
        if not actor.has_permission(ENROLLMENT_FLAG, now=now):
            _security_log.warning(
                "FACE_ENROLLMENT_DENIED",
                extra={"actor_id": str(actor.id), "flag": ENROLLMENT_FLAG},
            )
            raise FaceControlPermissionError(
                f"'{ENROLLMENT_FLAG}' səlahiyyəti olmadan üz qeydiyyatı mümkün deyil",
                context={"actor_id": str(actor.id), "flag": ENROLLMENT_FLAG},
            )
        if actor.id == subject_id:
            _security_log.warning("FACE_SELF_ENROLLMENT_DENIED", extra={"actor_id": str(actor.id)})
            raise FaceControlPermissionError(
                "İşçi öz üz qeydiyyatını özü apara bilməz — bənd 1 nəzarətli prosesi tələb edir",
                user_message="Öz üz qeydiyyatınızı özünüz apara bilməzsiniz.",
                context={"actor_id": str(actor.id)},
            )

    def capture_and_store(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        subject_id: EmployeeId,
        action: str,
        reason: str | None,
        archived: bool,
    ) -> FaceEnrollmentResult:
        """Kadr çəkilişi → keyfiyyət süzgəci → orta vektor → yazı + audit.

        Həm ilk qeydiyyat, həm yenidən-qeydiyyat bu metoddan keçir (bax
        yuxarıdakı bölmə şərhi).
        """
        if not self._camera.is_available():
            raise FaceCameraUnavailableError(
                "Kamera əlçatmazdır — üz qeydiyyatı aparıla bilməz",
                context={"employee_id": str(subject_id)},
            )

        frame_count = self._limit_int(tenant_id, SystemLimitKey.FACE_ENROLLMENT_FRAME_COUNT)
        minimum_quality = self._limit_float(tenant_id, SystemLimitKey.FACE_ENROLLMENT_MIN_QUALITY)
        # LIVENESS TƏLƏB EDİLMİR: bənd 1-ə görə işçi FİZİKİ olaraq adminin
        # yanındadır — canlılıq artıq insan tərəfindən təsdiqlənib. Burada
        # hərəkət tələb etmək prosesi uzadar və heç bir yeni qoruma verməzdi.
        frames = self._camera.capture(count=frame_count)
        outcomes, accepted = _evaluate_frames(
            frames, matcher=self._matcher, minimum_quality=minimum_quality
        )

        if not accepted:
            _log.info(
                "FACE_ENROLLMENT_RETAKE",
                extra={
                    "employee_id": str(subject_id),
                    "frames": len(outcomes),
                    "minimum_quality": minimum_quality,
                },
            )
            return FaceEnrollmentResult(
                employee_id=subject_id,
                accepted=False,
                message_az=(
                    f"{len(outcomes)} kadrın heç biri keyfiyyət həddini "
                    f"({minimum_quality:.2f}) keçmədi. İşıqlandırmanı yaxşılaşdırın "
                    f"və [Yenidən Çək]."
                ),
                frames=outcomes,
            )

        # BƏND 11 — RİYAZİ ORTA: tək kadrın təsadüfi işıq/açı xətası əbədi
        # istinad nöqtəsinə çevrilməsin deyə.
        reference = FaceEmbedding.average(accepted)
        enrolled_at = self._clock.now()
        self._profiles.save_enrollment(subject_id, embedding=reference, enrolled_at=enrolled_at)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action=action,
            entity_type="employees",
            entity_id=subject_id,
            after_state={
                # VEKTOR AUDİTƏ YAZILMIR — yalnız onun HANSI ŞƏRTLƏRLƏ
                # yarandığı. Audit sətri biometrik nüsxə olmamalıdır.
                "enrolled_at": enrolled_at.isoformat(),
                "frames_captured": len(outcomes),
                "frames_accepted": len(accepted),
                "minimum_quality": minimum_quality,
                "archived_previous": archived,
            },
            reason=reason,
        )
        _log.info(
            "FACE_ENROLLMENT_STORED",
            extra={
                "employee_id": str(subject_id),
                "frames_accepted": len(accepted),
                "frames_captured": len(outcomes),
            },
        )
        return FaceEnrollmentResult(
            employee_id=subject_id,
            accepted=True,
            message_az=(
                f"Üz qeydiyyatı tamamlandı — {len(accepted)}/{len(outcomes)} kadrın "
                f"ortası istinad kimi saxlanıldı."
            ),
            frames=outcomes,
            enrolled_at=enrolled_at,
            archived_previous=archived,
        )

    def _limit_int(self, tenant_id: TenantId, key: SystemLimitKey) -> int:
        return self._limits.get_int(tenant_id, key.value, int(DEFAULT_LIMITS[key]))

    def _limit_float(self, tenant_id: TenantId, key: SystemLimitKey) -> float:
        raw = self._limits.get_str(tenant_id, key.value, DEFAULT_LIMITS[key])
        return parse_tolerance(raw, fallback=float(DEFAULT_LIMITS[key]))


class FaceReEnrollmentUseCase:
    """Mövcud qeydiyyatın dəyişdirilməsi (bənd 2) — EYNİ nəzarətli proses.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ AYRI USE CASE, NİYƏ `enroll(force=True)` DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Bayraq variantı RƏDD EDİLDİ: `force=True` bir gün defolt dəyər alar və ya
    ekranın bir yerində sükutla ötürülərdi — nəticədə arxivsiz üstündən yazma
    mümkün olardı. Ayrı use case həm SƏBƏBİ məcburi edir, həm də arxivləməni
    axının struktur hissəsinə çevirir: arxiv YAZILMADAN yeni vektor yazıla
    bilmir, çünki hər iki addım bu metodun içindədir.

    QEYDİYYAT MƏNTİQİ TƏKRARLANMIR: kadr çəkilişi, keyfiyyət süzgəci və orta
    vektor `FaceEnrollmentUseCase`-in metodundan çağırılır.
    """

    def __init__(
        self,
        *,
        enrollment: FaceEnrollmentUseCase,
        profiles: FaceEmbeddingRepository,
        audit: AuditTrail,
        clock: Clock,
    ) -> None:
        self._enrollment = enrollment
        self._profiles = profiles
        self._audit = audit
        self._clock = clock

    def re_enroll(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        subject_id: EmployeeId,
        reason: str,
    ) -> FaceEnrollmentResult:
        """Köhnə vektoru ARXİVLƏYİR (`REPLACED`), sonra yenisini yazır.

        SIRA VACİBDİR: əvvəlcə arxiv, sonra yeni yazı. Tərsinə etsəydik, arxiv
        addımı YENİ vektoru köçürərdi (çünki `employees.face_embedding` artıq
        dəyişmiş olardı) və köhnəsi izsiz itərdi. Hər iki yazı EYNİ
        tranzaksiyadadır (sessiya commit edir), yəni yarımçıq vəziyyət mümkün
        deyil.
        """
        self._enrollment.assert_may_enroll(actor, subject_id)
        if not reason.strip():
            raise FaceControlError(
                "Yenidən-qeydiyyatın səbəbi boş ola bilməz",
                user_message="Yenidən qeydiyyat üçün səbəb yazılmalıdır.",
            )

        profile = self._profiles.get_profile(subject_id)
        if profile is None or not profile.is_enrolled:
            raise FaceControlError(
                "Yenidən-qeydiyyat üçün mövcud qeydiyyat tapılmadı",
                user_message="Bu işçinin hələ üz qeydiyyatı yoxdur — əvvəlcə qeydiyyat aparın.",
                context={"employee_id": str(subject_id)},
            )

        archived_at = self._clock.now()
        archived = self._profiles.archive(
            subject_id,
            archived_by=actor.id,
            reason=reason.strip(),
            archived_at=archived_at,
        )
        result = self._enrollment.capture_and_store(
            tenant_id=tenant_id,
            actor=actor,
            subject_id=subject_id,
            action="FACE_RE_ENROLLED",
            reason=reason.strip(),
            archived=archived,
        )
        if not result.accepted:
            # KADRLAR KEÇMƏDİ: arxiv sətri artıq yazılıb, lakin yeni vektor
            # yazılmayıb. Bu, YARIMÇIQ VƏZİYYƏT DEYİL — arxiv `REPLACED`
            # sətri əməliyyat cəhdinin izidir və `employees.face_embedding`
            # hələ KÖHNƏ vektordur (arxivləmə onu təmizləmir), yəni işçi
            # doğrulanmağa davam edir. Çağıran tərəf tranzaksiyanı geri
            # qaytarırsa arxiv sətri də gedir; commit edirsə iz qalır.
            _log.info(
                "FACE_RE_ENROLLMENT_RETAKE",
                extra={"employee_id": str(subject_id), "archived": archived},
            )
        return result


# --------------------------------------------------------------------------- #
# 3. Doğrulama (bənd 3, 4, 5, 6, 7, 9, 12, 15, 18)
# --------------------------------------------------------------------------- #


class FaceVerificationUseCase:
    """PIN-dən SONRA işləyən üz qapısı — üç tətbiq nöqtəsi (STEP A/1/2).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ KADR PARAMETR KİMİ QƏBUL EDİLMİR
    ──────────────────────────────────────────────────────────────────────────
    `verify(..., frame=...)` imzası daha "sadə" görünürdü və rədd edildi. İki
    səbəb:

      1. LIVENESS HƏRƏKƏTİ SERVERDƏ SEÇİLMƏLİDİR (bənd 6). Kadr kənardan
         gəlsəydi, çağıran tərəf hansı hərəkətin tələb olunduğunu ÖZÜ bilməli
         (yəni seçməli) olardı — təsadüfilik kiosk maşınına köçər və
         video-təkrar hücumu üçün proqnozlaşdırıla bilən olardı.
      2. KAMERA NASAZLIĞI GÖRÜNMƏZ OLARDI (bənd 5). Kadr yoxdursa, use case
         "üz görünmədi" (texniki, sayğacsız) ilə "kamera ümumiyyətlə yoxdur"
         (eskalasiya tələb edən) hallarını ayıra bilməzdi.

    Ona görə kadr çəkilişi bu use case-in İÇİNDƏDİR və `CameraCapture` portu
    ilə edilir; testlər sahtə kamera ilə işləyir.
    """

    def __init__(
        self,
        *,
        profiles: FaceEmbeddingRepository,
        verification_log: FaceVerificationLogRepository,
        exemptions: FaceExemptionRepository,
        store_scope: FaceStoreScopeRepository,
        camera: CameraCapture,
        matcher: FaceMatcher,
        limits: SystemLimits,
        toggles: FeatureToggles,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier,
    ) -> None:
        self._profiles = profiles
        self._verification_log = verification_log
        self._exemptions = exemptions
        self._store_scope = store_scope
        self._camera = camera
        self._matcher = matcher
        self._limits = limits
        self._toggles = toggles
        self._audit = audit
        self._clock = clock
        self._notifier = notifier

    def verify(  # noqa: PLR0911
        self,
        *,
        tenant_id: TenantId,
        employee: Employee,
        trigger_context: FaceTriggerContext,
    ) -> FaceGateDecision:
        """Üz qapısı — PIN uğurlu olduqdan SONRA çağırılır.

        `employee` MÖVCUD PIN handshake-inin nəticəsidir (`PinResult.employee`)
        — bu use case PIN-i yenidən yoxlamır və yoxlamamalıdır: ikinci yoxlama
        eyni qaydanın ikinci nüsxəsi olardı.

        `PLR0911` (çox `return`) BURADA SUSDURULUB: metodun hər `return`-u
        AYRI bir anti-fraud qərarıdır (modul, əhatə, istisna, kilid, qeydiyyat,
        kamera, kadr, üz, canlılıq, uyğunluq) və hər biri fərqli yan təsirlə
        (audit/bildiriş/sayğac) bitir. Onları bir çıxışa yığmaq üçün nəticəni
        dəyişəndə saxlamaq lazım gələrdi — yəni "hansı şərtdən sonra hansı
        yan təsir baş verdi?" sualı bir neçə `if`-in arxasına gizlənərdi.
        Qapıların SIRASI isə təhlükəsizlik qərarıdır və burada yuxarıdan
        aşağıya oxunur.
        """
        started_at = self._clock.now()

        # 0. MODUL QAPISI — mövcud `CAMERA_VERIFICATION` toggle-ı.
        #
        # YENİ MODUL AÇARI YARADILMADI VƏ BU, ƏSASLANDIRILMIŞ QƏRARDIR:
        # `feature_toggles` sətri olmayan açar üçün `is_enabled()` `True`
        # qaytarır (bax `PostgresFeatureToggles.is_enabled` şərhi) və sətir
        # yalnız `schema.sql` seed-i ilə yaranır — migrations/047 isə həmin
        # cədvələ QƏSDƏN toxunmur (bənd 15: "qlobal toggle mexanizminə
        # TOXUNMADAN"). Yəni `FACE_CONTROL` açarı yaratsaydıq, o, ROOT
        # ekranında GÖRÜNMƏZ, həmişə AÇIQ və söndürülə bilməyən bir "parametr"
        # olardı — parametr adı daşıyan, faktiki olaraq hardcode dəyər.
        #
        # `CAMERA_VERIFICATION` isə düzgün valideyndir: üz təsdiqi məhz onun
        # axınlarının (STEP A/1/2) içindədir və o modul söndürüləndə həmin
        # axınlar onsuz da işləmir (`morning_check_in._require_module`).
        # Pilot-mərhələli yayım isə mağaza əhatəsi ilə edilir (aşağıda).
        if not self._toggles.is_enabled(tenant_id, FeatureModule.CAMERA_VERIFICATION.value):
            return self._not_applicable(
                employee,
                trigger_context,
                started_at,
                reason_az="Kamera Təsdiqi modulu deaktivdir",
            )

        # 1. MAĞAZA ƏHATƏSİ (bənd 15) — boş siyahı = qlobal davranış.
        scope = self._store_scope.active_scope(tenant_id)
        if not scope.covers(employee.store_id):
            return self._not_applicable(
                employee,
                trigger_context,
                started_at,
                reason_az="Bu mağaza Face Control əhatəsində deyil",
            )

        # 2. İSTİSNA (bənd 14) — PIN-only, LAKİN MƏCBURİ dual-control ilə.
        #    Kompensasiyanın MÖVCUDLUĞU da burada yoxlanılır (SEC-020).
        exemption = self._exemptions.active_for(employee.id, now=started_at)
        if exemption is not None:
            return self._exempt_employee_gate(
                tenant_id=tenant_id,
                employee=employee,
                trigger_context=trigger_context,
                exemption=exemption,
                started_at=started_at,
            )

        profile = self._profiles.get_profile(employee.id)

        # 3. KİLİD (bənd 4) — MÖVCUD lockout mexanizmi, mövcud istisna sinfi.
        if profile is not None and profile.is_locked(now=started_at):
            _security_log.warning(
                "FACE_LOCKED_ATTEMPT",
                extra={
                    "employee_id": str(employee.id),
                    "trigger_context": trigger_context.value,
                },
            )
            raise AccountLockedError(
                "Üz uyğunsuzluğuna görə hesab müvəqqəti bloklanıb",
                context={
                    "employee_id": str(employee.id),
                    "locked_until": profile.locked_until.isoformat()
                    if profile.locked_until
                    else None,
                },
            )

        # 4. QEYDİYYAT YOXDURSA — SƏSSİZ KEÇİD YOX, ESKALASİYA.
        #
        # "Qeydiyyatsız işçini sadəcə buraxaq" ən asan variant idi və ən
        # təhlükəlisi: onda üz qatını yan keçmək üçün qeydiyyatı ləğv etdirmək
        # kifayət edərdi. "Bloklayaq" variantı da yanlışdır — yeni işə
        # götürülən işçi qeydiyyatdan əvvəl işə başlaya bilməzdi. Doğru cavab
        # bənd 5-in cavabıdır: insan qərarına yönləndir.
        if profile is None or not profile.is_enrolled:
            return self._escalate(
                tenant_id=tenant_id,
                employee=employee,
                trigger_context=trigger_context,
                started_at=started_at,
                health_category=None,
                reason_az="İşçinin üz qeydiyyatı yoxdur",
                notice_az=(
                    "İşçinin üz qeydiyyatı olmadığı üçün giriş/qayıdış təsdiqi "
                    "manual olaraq HR_Admin və ya CEO tərəfindən verilməlidir."
                ),
            )

        # 5. KAMERA NASAZLIĞI (bənd 5) — SƏSSİZ "yalnız PIN" REJİMİ YOXDUR.
        if not self._camera.is_available():
            return self._escalate(
                tenant_id=tenant_id,
                employee=employee,
                trigger_context=trigger_context,
                started_at=started_at,
                health_category=CAMERA_HEALTH_CATEGORY,
                reason_az="Kiosk kamerası əlçatmazdır",
                notice_az=(
                    "Kiosk kamerası işləmir. Üz təsdiqi aparıla bilmədi — təsdiq "
                    "HR_Admin və ya CEO tərəfindən manual verilməlidir."
                ),
            )

        # 6. LIVENESS (bənd 6) — hərəkət SERVERDƏ, kriptoqrafik təsadüfi seçilir.
        #
        # `random.choice` DEYİL, `secrets.choice`: `random` modulu
        # proqnozlaşdırıla biləndir (Mersenne Twister) və bir neçə müşahidədən
        # sonra növbəti hərəkət hesablana bilər — video-təkrar hücumu üçün
        # məhz bu lazımdır.
        gesture = secrets.choice(self._gesture_pool(tenant_id))
        frames = self._camera.capture(count=1, gesture=gesture)
        if not frames:
            return self._no_face(
                tenant_id=tenant_id,
                employee=employee,
                trigger_context=trigger_context,
                gesture=gesture,
                started_at=started_at,
                message_az="Kadr alınmadı. Kameraya baxıb yenidən cəhd edin.",
            )

        sample = self._matcher.extract(frames[0], gesture=gesture)
        if not sample.has_face:
            return self._no_face(
                tenant_id=tenant_id,
                employee=employee,
                trigger_context=trigger_context,
                gesture=gesture,
                started_at=started_at,
                message_az="Üz aşkarlanmadı. İşığa tərəf dönüb yenidən cəhd edin.",
            )
        if not sample.liveness_confirmed:
            # LIVENESS UĞURSUZLUĞU NİYƏ MISMATCH SAYILMIR
            # ────────────────────────────────────────────────────────────────
            # Şəkil göstərmə cəhdi fırıldaqdır və "MISMATCH sayğacına yazaq"
            # variantı ciddi nəzərdən keçirildi. Rədd edildi, çünki eyni
            # nəticəni VİCDANLI işçi də alır: zəif kamerada göz qırpma bir
            # neçə cəhdə tutulmur və işçi üç cəhddən sonra KİLİDLƏNƏRDİ —
            # yəni qoruma öz istifadəçisini cəzalandırardı.
            #
            # Fail-closed xassəsi İTMİR: liveness təsdiqlənmədən əməliyyat
            # HEÇ VAXT davam etmir, yəni şəkil göstərən adam sonsuz sayda
            # cəhd edib heç nə əldə etmir. Naxış isə görünməz qalmır —
            # `security.log`-a ayrıca açarla yazılır.
            _security_log.warning(
                "FACE_LIVENESS_FAILED",
                extra={
                    "employee_id": str(employee.id),
                    "gesture": gesture.value,
                    "trigger_context": trigger_context.value,
                },
            )
            return self._no_face(
                tenant_id=tenant_id,
                employee=employee,
                trigger_context=trigger_context,
                gesture=gesture,
                started_at=started_at,
                message_az=(
                    f"Canlılıq yoxlaması tamamlanmadı ({gesture.prompt_az}). Yenidən cəhd edin."
                ),
            )

        # 7. MÜQAYİSƏ (bənd 7, 12) — qərar MƏSAFƏ üzərində verilir.
        assert sample.embedding is not None  # `has_face` yuxarıda yoxlanıldı
        assert profile.embedding is not None  # `is_enrolled` yuxarıda yoxlanıldı
        band = self._tolerance_band(tenant_id)
        distance = self._matcher.distance(profile.embedding, sample.embedding)
        result, is_low_confidence = band.classify(distance)
        confidence = FaceToleranceBand.confidence_percent(distance)

        if result is FaceVerificationResult.SUCCESS:
            return self._success(
                tenant_id=tenant_id,
                employee=employee,
                trigger_context=trigger_context,
                gesture=gesture,
                started_at=started_at,
                confidence=confidence,
                is_low_confidence=is_low_confidence,
                band=band,
            )
        return self._mismatch(
            tenant_id=tenant_id,
            employee=employee,
            profile=profile,
            trigger_context=trigger_context,
            gesture=gesture,
            started_at=started_at,
            confidence=confidence,
            candidate=sample.embedding,
            band=band,
        )

    def login_available(self, *, tenant_id: TenantId, store_id: StoreId) -> bool:
        """Üzlə giriş bu mağazada MÜMKÜNDÜRMÜ — düymənin görünmə şərti.

        `identify_for_login`-un İLK ÜÇ qapısı ilə eynidir və qəsdən belədir:
        düymə göstərilib sonra «üz tanınmadı» demək istifadəçini yanıldardı —
        o, nasazlıq sanıb təkrar-təkrar basardı. Şərtlər burada TƏKRAR
        YAZILMIR, eyni sıra ilə oxunur.
        """
        return bool(
            self._toggles.is_enabled(tenant_id, FeatureModule.CAMERA_VERIFICATION.value)
            and self._store_scope.active_scope(tenant_id).covers(store_id)
            and self._camera.is_available()
        )

    def identify_for_login(  # noqa: PLR0911 - hər `return` AYRI bir qapıdır
        self,
        *,
        tenant_id: TenantId,
        store_id: StoreId,
        candidates: Sequence[Employee],
    ) -> Employee | None:
        """Kioskda duran adamı MAĞAZA daxilində tanıyır (üzlə giriş).

        ──────────────────────────────────────────────────────────────────────
        BU, `verify()`-DAN FƏRQLİ BİR RİSKDİR
        ──────────────────────────────────────────────────────────────────────
        `verify()` 1:1-dir — «bu adam Rəşaddırmı?». Burada isə 1:N var — «bu
        adam kimdir?». İkincisi riyazi olaraq daha risklidir: 40 profil arasında
        ən yaxın qonşu TƏSADÜFƏN də yaxın düşə bilər və nəticə «başqasının
        adından giriş» olardı. Ona görə iki əlavə şərt qoyulur:

            1. Ən yaxşı uyğunluq `match_tolerance` daxilində olmalıdır
               (`verify()` ilə eyni ROOT həddi — ikinci mənbə yaranmır);
            2. İKİNCİ ən yaxşı uyğunluq ondan `_IDENTIFY_MARGIN` qədər UZAQ
               olmalıdır. Marja olmadan iki oxşar üzdən biri sükutla seçilərdi.

        Şərtlərdən biri pozulursa nəticə `None`-dur və işçi PIN yoluna
        qaytarılır — «bənzər üz tapıldı, keçir» kimi bir orta yol YOXDUR.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ YALNIZ MAĞAZA ƏHATƏSİ
        ──────────────────────────────────────────────────────────────────────
        `_cross_check` ilə eyni əsaslandırma: bütün şəbəkə üzrə axtarış həm
        yavaşdır, həm də yalançı-müsbətə meyllidir. Kiosk onsuz da bir
        mağazanın cihazıdır.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ JURNAL SƏTRİ YAZILMIR
        ──────────────────────────────────────────────────────────────────────
        `face_verification_log` bir İŞÇİNİN doğrulama tarixçəsidir və
        `employee_id` məcburidir. Tanınmamış cəhddə isə işçi YOXDUR — sətri
        «kimsə» adına yazmaq jurnalı korlayardı. Tanınma UĞURLU olduqda isə
        giriş onsuz da `verify()`-dan keçir (bax `KioskController`), yəni sətir
        orada yazılır və ikiqat qeyd yaranmır.
        """
        if not self._toggles.is_enabled(tenant_id, FeatureModule.CAMERA_VERIFICATION.value):
            return None
        if not self._store_scope.active_scope(tenant_id).covers(store_id):
            return None
        if not self._camera.is_available():
            return None

        gesture = secrets.choice(self._gesture_pool(tenant_id))
        frames = self._camera.capture(count=1, gesture=gesture)
        if not frames:
            return None

        sample = self._matcher.extract(frames[0], gesture=gesture)
        if not sample.has_face or not sample.liveness_confirmed or sample.embedding is None:
            return None

        band = self._tolerance_band(tenant_id)
        scored: list[tuple[float, Employee]] = []
        for candidate in candidates:
            profile = self._profiles.get_profile(candidate.id)
            if profile is None or profile.embedding is None:
                continue
            scored.append((self._matcher.distance(profile.embedding, sample.embedding), candidate))

        if not scored:
            return None
        scored.sort(key=lambda pair: pair[0])
        best_distance, best_employee = scored[0]
        if best_distance > band.match_tolerance:
            return None
        if len(scored) > 1 and scored[1][0] - best_distance < _IDENTIFY_MARGIN:
            # İKİ ÜZ BİR-BİRİNƏ ÇOX YAXINDIR — seçim etmirik.
            _security_log.warning(
                "FACE_LOGIN_AMBIGUOUS",
                extra={"store_id": str(store_id), "gap": round(scored[1][0] - best_distance, 4)},
            )
            return None
        return best_employee

    # --------------------------- nəticə yolları ------------------------------ #

    def _success(
        self,
        *,
        tenant_id: TenantId,
        employee: Employee,
        trigger_context: FaceTriggerContext,
        gesture: LivenessGesture,
        started_at: datetime,
        confidence: float,
        is_low_confidence: bool,
        band: FaceToleranceBand,
    ) -> FaceGateDecision:
        """Uğurlu doğrulama — sayğac SIFIRLANIR (mövcud PIN naxışının eynisi)."""
        self._profiles.save_security(employee.id, mismatch_attempts=0, locked_until=None)
        duration = self._duration_ms(started_at)
        self._verification_log.record(
            FaceVerificationLogEntry(
                employee_id=employee.id,
                tenant_id=tenant_id,
                result=FaceVerificationResult.SUCCESS,
                trigger_context=trigger_context,
                occurred_at=started_at,
                store_id=employee.store_id,
                confidence_score=confidence,
                is_low_confidence=is_low_confidence,
                liveness_action=gesture,
                duration_ms=duration,
            )
        )
        self._check_performance(tenant_id=tenant_id, duration_ms=duration, employee=employee)
        outcome = (
            FaceGateOutcome.ALLOWED_LOW_CONFIDENCE if is_low_confidence else FaceGateOutcome.ALLOWED
        )
        message = (
            "Üz təsdiqləndi (aşağı-etibarlı) — qeyd nişanlandı."
            if is_low_confidence
            else "Üz təsdiqləndi."
        )
        return FaceGateDecision(
            employee_id=employee.id,
            trigger_context=trigger_context,
            outcome=outcome,
            message_az=message,
            result=FaceVerificationResult.SUCCESS,
            liveness_action=gesture,
            confidence_score=confidence,
            is_low_confidence=is_low_confidence,
            duration_ms=duration,
            tolerance_inverted=band.is_inverted,
        )

    def _no_face(
        self,
        *,
        tenant_id: TenantId,
        employee: Employee,
        trigger_context: FaceTriggerContext,
        gesture: LivenessGesture,
        started_at: datetime,
        message_az: str,
    ) -> FaceGateDecision:
        """`NO_FACE_DETECTED` — TEXNİKİ hal (bənd 3).

        HEÇ BİR SAYĞACA TOXUNULMUR: nə PIN sayğacı (`pin_failed_attempts`),
        nə üz sayğacı (`face_mismatch_attempts`). Sətir jurnala yazılır ki,
        "bu kioskda üz niyə tez-tez görünmür?" sualı sonradan cavablana bilsin
        — lakin bu, işçinin əleyhinə heç bir nəticə doğurmur.
        """
        duration = self._duration_ms(started_at)
        self._verification_log.record(
            FaceVerificationLogEntry(
                employee_id=employee.id,
                tenant_id=tenant_id,
                result=FaceVerificationResult.NO_FACE_DETECTED,
                trigger_context=trigger_context,
                occurred_at=started_at,
                store_id=employee.store_id,
                # Bal YOXDUR: müqayisə ümumiyyətlə aparılmayıb. `0.00` yazmaq
                # "tamamilə fərqli üz" mənasına gələrdi (sxem `CHECK`-i bunu
                # struktur olaraq qadağan edir).
                confidence_score=None,
                liveness_action=gesture,
                duration_ms=duration,
            )
        )
        self._check_performance(tenant_id=tenant_id, duration_ms=duration, employee=employee)
        return FaceGateDecision(
            employee_id=employee.id,
            trigger_context=trigger_context,
            outcome=FaceGateOutcome.RETRY,
            message_az=message_az,
            result=FaceVerificationResult.NO_FACE_DETECTED,
            liveness_action=gesture,
            duration_ms=duration,
        )

    def _mismatch(
        self,
        *,
        tenant_id: TenantId,
        employee: Employee,
        profile: FaceProfile,
        trigger_context: FaceTriggerContext,
        gesture: LivenessGesture,
        started_at: datetime,
        confidence: float,
        candidate: FaceEmbedding,
        band: FaceToleranceBand,
    ) -> FaceGateDecision:
        """`MISMATCH` — ən güclü fırıldaqçılıq siqnalı (bənd 3, 4).

        ÜÇ ŞEY EYNİ ANDA BAŞ VERİR:
          1. cross-check — kioskda duran adam EYNİ MAĞAZANIN başqa işçisidirmi;
          2. sayğac + (lazım gələrsə) kilid — MÖVCUD lockout mexanizmi ilə;
          3. DƏRHAL bildiriş — İLK DƏFƏDƏN, həddi gözləmədən.

        Üçüncü bənd bənd 3-ün açıq tələbidir və qəsdən həddən ƏVVƏLDİR:
        uyğunsuzluq özü hadisədir; onu kilidə qədər saxlamaq HR-in ilk iki
        cəhdi heç vaxt görməməsi demək olardı.
        """
        matched = self._cross_check(
            tenant_id=tenant_id, employee=employee, candidate=candidate, band=band
        )

        # MÖVCUD LOCKOUT MEXANİZMİ — yeni funksiya yazılmır.
        # `evaluate_pin_attempt` SAF funksiyadır və `PinHandshakeUseCase` onu
        # PIN üçün işlədir; burada eyni funksiya ÜZ sayğacı və ÜZ həddi ilə
        # çağırılır. Kilidin MÜDDƏTİ isə eyni ROOT açarındandır
        # (`PIN_LOCKOUT_MINUTES`) — bənd 4 yeni müddət parametrini qadağan edir.
        policy = PinPolicy(
            max_attempts=self._limit_int(tenant_id, SystemLimitKey.FACE_MISMATCH_LOCKOUT_THRESHOLD),
            lockout_minutes=self._limit_int(tenant_id, SystemLimitKey.PIN_LOCKOUT_MINUTES),
        )
        decision = evaluate_pin_attempt(
            success=False,
            current_failed_attempts=profile.mismatch_attempts,
            current_locked_until=profile.locked_until,
            policy=policy,
            now=started_at,
        )
        self._profiles.save_security(
            employee.id,
            mismatch_attempts=decision.failed_attempts,
            locked_until=decision.locked_until,
        )

        duration = self._duration_ms(started_at)
        self._verification_log.record(
            FaceVerificationLogEntry(
                employee_id=employee.id,
                tenant_id=tenant_id,
                result=FaceVerificationResult.MISMATCH,
                trigger_context=trigger_context,
                occurred_at=started_at,
                store_id=employee.store_id,
                matched_other_employee_id=matched,
                lockout_triggered=decision.is_locked,
                confidence_score=confidence,
                liveness_action=gesture,
                duration_ms=duration,
            )
        )

        _security_log.critical(
            "FACE_MISMATCH",
            extra={
                "employee_id": str(employee.id),
                "trigger_context": trigger_context.value,
                "attempts": decision.failed_attempts,
                "lockout": decision.is_locked,
                "matched_other": str(matched) if matched else None,
                # BAL YAZILIR, VEKTOR YOX — jurnal biometrik nüsxə olmamalıdır.
                "confidence": confidence,
            },
        )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=None,  # aktor İDDİA edilən işçidir, faktiki isə naməlum
            action="FACE_MISMATCH",
            entity_type="face_verification_log",
            entity_id=employee.id,
            after_state={
                "trigger_context": trigger_context.value,
                "attempts": decision.failed_attempts,
                "lockout_triggered": decision.is_locked,
                "matched_other_employee_id": str(matched) if matched else None,
                "confidence_score": confidence,
            },
            reason="Kioskdakı şəxsin üzü PIN sahibinin qeydiyyatlı üzü ilə uyğun gəlmədi",
        )
        # İLK DƏFƏDƏN DƏRHAL BİLDİRİŞ (bənd 3) — hədd gözlənilmir.
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=None,  # HR_Admin + Mağaza Meneceri
            category=MISMATCH_CATEGORY,
            title_az="Üz uyğunsuzluğu aşkarlandı",
            body_az=(
                f"Kioskda PIN daxil edən şəxsin üzü həmin PIN-in sahibinin qeydiyyatlı "
                f"üzü ilə uyğun gəlmədi ({trigger_context.value}). "
                f"Ardıcıl uyğunsuzluq sayı: {decision.failed_attempts}."
                + (" Hesab bloklandı." if decision.is_locked else "")
                + (
                    " Diqqət: üz EYNİ MAĞAZANIN başqa işçisinə uyğun gəldi."
                    if matched is not None
                    else ""
                )
            ),
            is_critical=True,
        )
        if band.is_inverted:
            # Tərs konfiqurasiya SÜKUTLA keçmir: Root ROOT ekranında
            # "yumşaltdım" zənn edə bilər, sistem isə fail-closed işləyir.
            _log.warning(
                "FACE_TOLERANCE_INVERTED",
                extra={
                    "match_tolerance": band.match_tolerance,
                    "low_confidence_tolerance": band.low_confidence_tolerance,
                },
            )
        self._check_performance(tenant_id=tenant_id, duration_ms=duration, employee=employee)

        outcome = FaceGateOutcome.LOCKED if decision.is_locked else FaceGateOutcome.BLOCKED
        message = (
            "Üz uyğun gəlmədi. Hesab müvəqqəti bloklandı — rəhbərliyə müraciət edin."
            if decision.is_locked
            else "Üz uyğun gəlmədi. Əməliyyat dayandırıldı."
        )
        return FaceGateDecision(
            employee_id=employee.id,
            trigger_context=trigger_context,
            outcome=outcome,
            message_az=message,
            result=FaceVerificationResult.MISMATCH,
            liveness_action=gesture,
            confidence_score=confidence,
            matched_other_employee_id=matched,
            lockout_triggered=decision.is_locked,
            locked_until=decision.locked_until,
            duration_ms=duration,
            tolerance_inverted=band.is_inverted,
        )

    def _cross_check(
        self,
        *,
        tenant_id: TenantId,
        employee: Employee,
        candidate: FaceEmbedding,
        band: FaceToleranceBand,
    ) -> EmployeeId | None:
        """Kioskdakı şəxs EYNİ MAĞAZANIN başqa işçisidirmi (bənd 3).

        ƏHATƏ QƏSDƏN MAĞAZA İLƏ MƏHDUDDUR: bütün şəbəkə üzrə axtarış həm
        yavaşdır (235 müqayisə), həm də yalançı-müsbətə meyllidir — nəticə
        "PIN-i başqasına verib" ittihamıdır və zəif sübutla verilməməlidir.

        `employee.store_id is None` (mağazasız işçi) halında cross-check
        APARILMIR: "mağaza" anlayışı olmadan əhatə tərifsizdir və bütün
        kirayəçi üzrə axtarış yuxarıdakı qərara ziddir.
        """
        if employee.store_id is None:
            return None
        best_id: EmployeeId | None = None
        best_distance = band.match_tolerance
        for other in self._profiles.list_store_profiles(
            tenant_id, employee.store_id, exclude=employee.id
        ):
            if other.embedding is None:
                continue
            distance = self._matcher.distance(other.embedding, candidate)
            if distance <= best_distance:
                best_distance = distance
                best_id = other.employee_id
        return best_id

    def _exempt_employee_gate(
        self,
        *,
        tenant_id: TenantId,
        employee: Employee,
        trigger_context: FaceTriggerContext,
        exemption: FaceExemption,
        started_at: datetime,
    ) -> FaceGateDecision:
        """İstisnalı işçinin qapısı — SEC-020.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ BURADA TOGGLE OXUNUR
        ──────────────────────────────────────────────────────────────────────
        Bənd 14 istisnanı YALNIZ bir şərtlə icazə verir: PIN-only-nin açdığı
        boşluq MƏCBURİ ikinci-təsdiqlə əvəzlənir. Həmin ikinci təsdiq
        `FACE_EXEMPTION_COMPENSATING_MODULE` (`DUAL_CONTROL`) modulunun
        axınıdır. Modul söndürülübsə, kompensasiya FAKTİKİ OLARAQ YOXDUR —
        yəni istisna öz şərtini itirir.

        Anti-fraud auditinə qədər bu hal TƏRİF OLUNMAMIŞ idi: bu metod
        toggle-a heç vaxt baxmırdı və hər halda `DUAL_CONTROL_REQUIRED`
        qaytarırdı. Nəticə ölü-kilid olardı — təsdiqi verəcək axın söndürülüb,
        deməli istisnalı işçi HEÇ VAXT günə başlaya bilməzdi və heç bir mesaj
        səbəbi izah etmirdi.

        ⚠️ SÜKUTLA KEÇİRMƏK (fail-open) NİYƏ RƏDD EDİLDİ: o zaman modulu
        söndürmək istisnalı işçinin PIN-ini TAM-SƏLAHİYYƏTLİ açara çevirərdi
        — yəni bənd 14-ün bağlamaq istədiyi aldatma yolu bir toggle ilə
        yenidən açılardı.

        SEÇİLƏN İSTİQAMƏT — FAIL-CLOSED, LAKİN ÇIXIŞI OLAN: əməliyyat
        kompensasiyasız DAVAM ETMİR, əvəzində MÖVCUD manual təsdiq kanalına
        (`_escalate`, bənd 5) düşür. Həmin kanal `DUAL_CONTROL` toggle-ından
        ASILI DEYİL, yəni işçi qapalı qapı qarşısında qalmır: təsdiqi
        HR_Admin/CEO verir. Vəziyyətin ÖZÜ isə sükutla yaşamır — audit sətri,
        `security.log` yazısı və kritik bildiriş göndərilir.

        Bu vəziyyətə ekran yolu ilə DÜŞMƏK MÜMKÜN DEYİL: `RootControlUseCase.
        set_module_enabled` aktiv istisna varkən söndürməni rədd edir və
        `FaceControlExemptionUseCase.grant` modul sönükdürsə istisna vermir.
        Bura yalnız birbaşa SQL / köhnə konfiqurasiya ilə gəlinə bilər — məhz
        ona görə qayda İKİ yerdədir (CLAUDE.md §5) və üçüncü qat kimi bu
        runtime yoxlaması qalır.
        """
        if not self._toggles.is_enabled(tenant_id, FACE_EXEMPTION_COMPENSATING_MODULE.value):
            return self._compensation_unavailable(
                tenant_id=tenant_id,
                employee=employee,
                trigger_context=trigger_context,
                exemption=exemption,
                started_at=started_at,
            )
        return self._dual_control_required(
            tenant_id=tenant_id,
            employee=employee,
            trigger_context=trigger_context,
            exemption=exemption,
            started_at=started_at,
        )

    def _compensation_unavailable(
        self,
        *,
        tenant_id: TenantId,
        employee: Employee,
        trigger_context: FaceTriggerContext,
        exemption: FaceExemption,
        started_at: datetime,
    ) -> FaceGateDecision:
        """Kompensasiya edici nəzarət söndürülüb — MANUAL təsdiqə (SEC-020).

        AUDİT SƏTRİ ƏLAVƏ YAZILIR VƏ BU, TƏKRAR DEYİL: `_escalate` "üz təsdiqi
        aparıla bilmədi" faktını yazır (avadanlıq/qeydiyyat hadisəsi), bura isə
        KONFİQURASİYA pozuntusunu yazır ("istisna qüvvədədir, kompensasiyası
        yoxdur"). İkisini birləşdirsəydik, struktur zəmanətin pozulduğu an
        adi bir kamera nasazlığı kimi görünərdi.
        """
        _security_log.critical(
            "FACE_EXEMPTION_COMPENSATION_MISSING",
            extra={
                "employee_id": str(employee.id),
                "exemption_id": str(exemption.exemption_id),
                "module": FACE_EXEMPTION_COMPENSATING_MODULE.value,
                "trigger_context": trigger_context.value,
            },
        )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=None,  # sistem müşahidəsi — insan əməliyyatı deyil
            action=COMPENSATION_UNAVAILABLE_ACTION,
            entity_type="face_control_exemptions",
            entity_id=exemption.exemption_id,
            after_state={
                "employee_id": str(employee.id),
                "trigger_context": trigger_context.value,
                "module": FACE_EXEMPTION_COMPENSATING_MODULE.value,
                "module_enabled": False,
                "fallback": FaceGateOutcome.MANUAL_APPROVAL_REQUIRED.value,
            },
            reason=(
                "Face Control istisnası qüvvədədir, lakin onun kompensasiya edici "
                "nəzarəti (dual-control) söndürülüb — təsdiq manual axına yönləndirildi"
            ),
        )
        return self._escalate(
            tenant_id=tenant_id,
            employee=employee,
            trigger_context=trigger_context,
            started_at=started_at,
            health_category=None,
            reason_az="Üz təsdiqi istisnasının kompensasiya edici nəzarəti söndürülüb",
            notice_az=(
                "Bu işçi üz təsdiqi istisnasındadır, lakin istisnanın kompensasiyası "
                "olan cüt-nəzarət modulu söndürülüb. Təsdiq HR_Admin və ya CEO "
                "tərəfindən manual verilməlidir; daimi həll üçün Root cüt-nəzarət "
                "modulunu yenidən aktivləşdirməli və ya istisnanı ləğv etməlidir."
            ),
        )

    def _dual_control_required(
        self,
        *,
        tenant_id: TenantId,
        employee: Employee,
        trigger_context: FaceTriggerContext,
        exemption: FaceExemption,
        started_at: datetime,
    ) -> FaceGateDecision:
        """İstisnalı işçi — MƏCBURİ ikinci təsdiq (bənd 14).

        "Bir az diqqətli ol" kimi qeyri-müəyyən tövsiyə DEYİL: qərar
        `FaceGateOutcome.DUAL_CONTROL_REQUIRED`-dir və `allows_operation`
        `False` qaytarır, yəni əməliyyat ikinci təsdiq olmadan davam edə
        bilmir. Təsdiqin ÖZÜ mövcud mexanizmdədir
        (`LeaveVerificationUseCase.approve_dual_control` +
        `DUAL_CONTROL_APPROVAL_FLAG`) — ikinci təsdiq mexanizmi yazılmır.

        JURNAL SƏTRİ YAZILMIR: `face_verification_log` üz MÜQAYİSƏSİNİN
        jurnalıdır, burada isə müqayisə ümumiyyətlə aparılmayıb. Uydurma
        sətir (`NO_FACE_DETECTED`) statistikanı korlayardı — "bu kioskda üz
        niyə görünmür?" sualının cavabına istisnalı işçilər qarışardı.
        """
        duration = self._duration_ms(started_at)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=None,
            action="FACE_EXEMPT_DUAL_CONTROL",
            entity_type="face_control_exemptions",
            entity_id=exemption.exemption_id,
            after_state={
                "employee_id": str(employee.id),
                "trigger_context": trigger_context.value,
                "expires_at": exemption.expires_at.isoformat(),
            },
            reason="Face Control istisnası — kompensasiya edici ikinci təsdiq tələb olunur",
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=None,
            category=DUAL_CONTROL_CATEGORY,
            title_az="İstisnalı işçi üçün ikinci təsdiq tələb olunur",
            body_az=(
                f"İşçi Face Control istisnasındadır (səbəb: {exemption.reason}). "
                f"«{trigger_context.value}» addımı üz təsdiqi olmadan davam edə bilməz — "
                f"ikinci təsdiq tələb olunur."
            ),
            is_critical=True,
        )
        return FaceGateDecision(
            employee_id=employee.id,
            trigger_context=trigger_context,
            outcome=FaceGateOutcome.DUAL_CONTROL_REQUIRED,
            message_az=(
                "Üz təsdiqi istisnası qüvvədədir — əməliyyat ikinci təsdiqdən sonra davam edəcək."
            ),
            requires_dual_control=True,
            duration_ms=duration,
        )

    def _escalate(
        self,
        *,
        tenant_id: TenantId,
        employee: Employee,
        trigger_context: FaceTriggerContext,
        started_at: datetime,
        health_category: str | None,
        reason_az: str,
        notice_az: str,
    ) -> FaceGateDecision:
        """MÖVCUD eskalasiya kanalına yönləndirir (bənd 5).

        İKİ AYRI BİLDİRİŞ GÖNDƏRİLİR VƏ BU, TƏKRAR DEYİL:
          * `VERIFICATION_TIMEOUT` — ƏMƏLİYYAT haqqındadır ("bu işçinin
            təsdiqi manual verilməlidir") və HR_Admin/CEO-nun mövcud manual
            təsdiq qutusuna düşür;
          * `FACE_CAMERA_UNAVAILABLE` — AVADANLIQ haqqındadır ("bu kioskun
            kamerası xarabdır") və System Health Monitor-un diqqət sətridir.

        Birini digəri ilə əvəz etsəydik, ya kameranın xarab olduğu heç yerdə
        görünməzdi (bənd 5 açıq şəkildə "nasazlığı System Health Monitor-a
        yaz" deyir), ya da işçi manual təsdiq növbəsinə heç vaxt düşməzdi.
        """
        duration = self._duration_ms(started_at)
        _security_log.warning(
            "FACE_VERIFICATION_ESCALATED",
            extra={
                "employee_id": str(employee.id),
                "trigger_context": trigger_context.value,
                "reason": reason_az,
            },
        )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=None,
            action="FACE_VERIFICATION_ESCALATED",
            entity_type="employees",
            entity_id=employee.id,
            after_state={
                "trigger_context": trigger_context.value,
                "reason": reason_az,
                "store_id": str(employee.store_id) if employee.store_id else None,
            },
            reason=reason_az,
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=None,
            category=ESCALATION_CATEGORY,
            title_az="Üz təsdiqi aparıla bilmədi — manual təsdiq lazımdır",
            body_az=notice_az,
            is_critical=True,
        )
        if health_category is not None:
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=None,
                category=health_category,
                title_az="Kiosk kamerası əlçatmazdır",
                body_az=(
                    "Üz təsdiqi kameranı aça bilmədi. Kioskun kamera bağlantısını "
                    "yoxlayın — nasazlıq davam etdikcə hər təsdiq manual axına düşəcək."
                ),
                is_critical=True,
            )
        return FaceGateDecision(
            employee_id=employee.id,
            trigger_context=trigger_context,
            outcome=FaceGateOutcome.MANUAL_APPROVAL_REQUIRED,
            message_az=notice_az,
            duration_ms=duration,
        )

    def _not_applicable(
        self,
        employee: Employee,
        trigger_context: FaceTriggerContext,
        started_at: datetime,
        *,
        reason_az: str,
    ) -> FaceGateDecision:
        """Modul/əhatə kənarı — HEÇ NƏ yazılmır, axın olduğu kimi davam edir.

        Bu, "sükutla PIN-only" DEYİL: burada üz təsdiqi Root-un AÇIQ qərarı
        ilə tətbiq olunmur (modul söndürülüb və ya mağaza pilot əhatəsində
        deyil). Bənd 5-in qadağan etdiyi hal isə TEXNİKİ nasazlığın sükutla
        eyni nəticəyə gətirməsidir — o, `_escalate`-ə gedir.
        """
        _log.debug(
            "FACE_GATE_NOT_APPLICABLE",
            extra={
                "employee_id": str(employee.id),
                "trigger_context": trigger_context.value,
                "reason": reason_az,
            },
        )
        return FaceGateDecision(
            employee_id=employee.id,
            trigger_context=trigger_context,
            outcome=FaceGateOutcome.NOT_APPLICABLE,
            message_az=reason_az,
            duration_ms=self._duration_ms(started_at),
        )

    # ------------------------------ köməkçi --------------------------------- #

    def _check_performance(
        self, *, tenant_id: TenantId, duration_ms: int, employee: Employee
    ) -> None:
        """Doğrulama vaxtı monitorinqi (bənd 18).

        ⚠️ KRİTİK TƏHLÜKƏSİZLİK QAYDASI — BU METOD HEÇ NƏ ZƏİFLƏTMİR.
        Burada `FACE_ENROLLMENT_FRAME_COUNT`, alignment və ya hədd
        parametrlərinə TOXUNAN heç bir kod YOXDUR və olmamalıdır. "Sürəti
        artırmaq üçün kadr sayını avtomatik azaldaq" cazibədar görünür və
        məhz ona görə `facecontrol.md` bənd 18 onu AÇIQ qadağan edir: nəticə
        "sistem sürətləndi" kimi görünər, faktiki olaraq isə tanınma
        dəqiqliyi sükutla enərdi. Sürət problemi hardware/kod
        optimallaşdırması ilə həll olunur.
        """
        max_seconds = self._limit_int(tenant_id, SystemLimitKey.FACE_VERIFICATION_MAX_SECONDS)
        if max_seconds <= 0 or duration_ms <= max_seconds * 1000:
            return
        _log.warning(
            "FACE_VERIFICATION_SLOW",
            extra={
                "employee_id": str(employee.id),
                "duration_ms": duration_ms,
                "max_seconds": max_seconds,
            },
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=None,
            category=PERFORMANCE_HEALTH_CATEGORY,
            title_az="Üz təsdiqi gözləniləndən yavaş işləyir",
            body_az=(
                f"Doğrulama {duration_ms} ms çəkdi (gözlənilən hədd: {max_seconds} san). "
                f"Kiosk PC-nin gücü kifayət etməyə bilər. QEYD: bu xəbərdarlıq heç bir "
                f"keyfiyyət parametrini avtomatik dəyişmir — həll yolu avadanlıq və ya "
                f"kod optimallaşdırmasıdır."
            ),
            is_critical=False,
        )

    def _duration_ms(self, started_at: datetime) -> int:
        """Doğrulamanın davam etdiyi müddət — `Clock` portu ilə ölçülür.

        `time.perf_counter()` daha dəqiq olardı və rədd edildi: CLAUDE.md §4
        vaxtın `Clock` portundan gəlməsini tələb edir, əks halda bənd 18-in
        həddi determinstik test edilə bilməzdi (sahtə saat irəli sürülərək
        "yavaş doğrulama" ssenarisi qurulur). Millisaniyə dəqiqliyi bir
        performans XƏBƏRDARLIĞI üçün onsuz da artıqdır.
        """
        elapsed = (self._clock.now() - started_at).total_seconds()
        return max(0, int(elapsed * 1000))

    def _gesture_pool(self, tenant_id: TenantId) -> tuple[LivenessGesture, ...]:
        raw = self._limits.get_str(
            tenant_id,
            SystemLimitKey.FACE_LIVENESS_ACTIONS.value,
            DEFAULT_LIMITS[SystemLimitKey.FACE_LIVENESS_ACTIONS],
        )
        return gesture_pool(
            raw,
            fallback=LivenessGesture.parse_catalog(
                DEFAULT_LIMITS[SystemLimitKey.FACE_LIVENESS_ACTIONS]
            ),
        )

    def _tolerance_band(self, tenant_id: TenantId) -> FaceToleranceBand:
        """İki ROOT həddindən qərar zolağı — TƏRS CÜTDƏ FAIL-CLOSED.

        Yoxlamanın MƏHZ BURADA olması qəsdlidir: şərt iki AYRI `system_limits`
        sətrindədir, yəni DB `CHECK`-i onu ifadə edə bilmir və ROOT ekranı
        (Faza 4) da tək başına kifayət etmir — ekranı yan keçən bir skript
        (və ya birbaşa `UPDATE`) tərs cüt yaza bilər. Qərarın oxunduğu yerdə
        yoxlamaq yeganə tam qorumadır.
        """
        band = FaceToleranceBand.resolve(
            match_tolerance=self._limit_float(tenant_id, SystemLimitKey.FACE_MATCH_TOLERANCE),
            low_confidence_tolerance=self._limit_float(
                tenant_id, SystemLimitKey.FACE_LOW_CONFIDENCE_TOLERANCE
            ),
        )
        if band.is_inverted:
            _log.warning(
                "FACE_TOLERANCE_BAND_DISABLED",
                extra={
                    "effective_tolerance": band.match_tolerance,
                    "reason": "aşağı-etibar həddi bənzərlik həddindən böyükdür",
                },
            )
        return band

    def _limit_int(self, tenant_id: TenantId, key: SystemLimitKey) -> int:
        return self._limits.get_int(tenant_id, key.value, int(DEFAULT_LIMITS[key]))

    def _limit_float(self, tenant_id: TenantId, key: SystemLimitKey) -> float:
        raw = self._limits.get_str(tenant_id, key.value, DEFAULT_LIMITS[key])
        return parse_tolerance(raw, fallback=float(DEFAULT_LIMITS[key]))


# --------------------------------------------------------------------------- #
# 4. İstisna (exemption) yolu — bənd 14
# --------------------------------------------------------------------------- #


class FaceControlExemptionUseCase:
    """PIN-only istisnasının təyinatı/uzadılması/ləğvi — YALNIZ Root/CEO.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `can_manage_employees` KİFAYƏT ETMİR
    ──────────────────────────────────────────────────────────────────────────
    Həmin flag-in `hardlock_level`-i 0-dır, yəni Root onu istənilən
    HR-səviyyəli admin-ə həvalə edə bilər. İstisna isə üz qatını SÖNDÜRÜR —
    yəni özü bir aldatma yoluna çevrilə bilər. Ona görə ayrıca
    `can_manage_face_exemptions` flag-i var və o, `hardlock_level = 2`
    (`HardlockLevel.ROOT_CEO`) ilə elan olunub: mövcud hardlock mexanizmi
    (DB trigger-i + `PermissionFlag.assert_grantable_to`) onu AVTOMATİK olaraq
    yalnız Root/CEO rollarında buraxır — burada YENİ guard yazılmır.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `FeatureToggles` LAZIMDIR (SEC-020)
    ──────────────────────────────────────────────────────────────────────────
    İstisna yalnız kompensasiya edici nəzarətlə birlikdə müdafiə oluna bilər
    (bənd 14). Kompensasiya söndürülübsə, YENİ istisna vermək «boşluğu açıram,
    əvəzini isə heç nə ödəmir» deməkdir. Ona görə `grant`/`extend` modulun
    vəziyyətini yoxlayır. Bu, `RootControlUseCase.set_module_enabled`-dakı
    qapının SİMMETRİK yarısıdır: biri modulu istisnaya görə kilidləyir, digəri
    istisnanı modula görə. YALNIZ biri yazılsaydı, sıranı dəyişdirmək
    (əvvəlcə modulu söndür, sonra istisna ver) qapını yan keçərdi.
    """

    def __init__(
        self,
        *,
        exemptions: FaceExemptionRepository,
        limits: SystemLimits,
        toggles: FeatureToggles,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier,
    ) -> None:
        self._exemptions = exemptions
        self._limits = limits
        self._toggles = toggles
        self._audit = audit
        self._clock = clock
        self._notifier = notifier

    def grant(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        employee_id: EmployeeId,
        reason: str,
        expires_at: datetime,
    ) -> FaceExemption:
        """İstisna verir — müddət MƏCBURİDİR və tavanı aşa bilməz."""
        now = self._clock.now()
        self._require_permission(actor)
        cleaned = self._require_reason(reason)
        self._require_compensating_control(tenant_id, operation="verilə")
        self._require_within_ceiling(tenant_id, granted_at=now, expires_at=expires_at)

        existing = self._exemptions.active_for(employee_id, now=now)
        if existing is not None:
            # `ux_face_exemption_active` qismən unikal indeksinin kod tərəfi:
            # ikinci aktiv sətir yaranmamalıdır, əks halda biri ləğv edilər,
            # digəri sükutla qüvvədə qalardı.
            raise FaceControlError(
                "İşçinin artıq aktiv Face Control istisnası var",
                user_message=(
                    "Bu işçinin artıq aktiv istisnası var. Uzatmaq və ya ləğv etmək üçün "
                    "mövcud sətri işlədin."
                ),
                context={"employee_id": str(employee_id)},
            )

        exemption = FaceExemption(
            exemption_id=new_face_exemption_id(),
            tenant_id=tenant_id,
            employee_id=employee_id,
            granted_by=actor.id,
            reason=cleaned,
            granted_at=now,
            expires_at=expires_at,
        )
        self._exemptions.save(exemption)
        self._record(
            exemption,
            actor=actor,
            action="FACE_EXEMPTION_GRANTED",
            reason=cleaned,
            title_az="Face Control istisnası verildi",
            body_az=(
                f"İşçi {expires_at.date().isoformat()} tarixinə qədər üz təsdiqindən "
                f"azad edilib. Səbəb: {cleaned}. KOMPENSASİYA: həmin işçinin HƏR "
                f"giriş/qayıdış təsdiqi məcburi ikinci təsdiqdən keçəcək."
            ),
        )
        return exemption

    def extend(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        exemption_id: FaceExemptionId,
        new_expiry: datetime,
    ) -> FaceExemption:
        """Müddəti uzadır — tavan YENİDƏN yoxlanılır.

        TAVAN TƏYİNAT ANINDAN ÖLÇÜLÜR, uzatma anından yox: əks halda hər
        uzatmada "90 gün" yenidən başlayar və istisna sonsuz uzana bilərdi —
        yəni bənd 14-ün "müvəqqətidir, daimi deyil" qaydası mənasız olardı.
        """
        self._require_permission(actor)
        # UZATMA DA «YARADAN» ƏMƏLİYYATDIR (SEC-020): retroaktiv-təsirsizlik
        # qaydası (CLAUDE.md §5) mövcud qeydin öz axınını tamamlamasını qoruyur,
        # uzatma isə axını TAMAMLAMIR — kompensasiyasız pəncərəni UZADIR. Ona
        # görə yoxlama burada da var; `revoke`/`expire_due` isə TOXUNULMAZDIR,
        # çünki onlar boşluğu BAĞLAYIR və bloklansaydılar ölü-kilid yaranardı.
        self._require_compensating_control(tenant_id, operation="uzadıla")
        exemption = self._require_exemption(tenant_id, exemption_id)
        if not exemption.status.is_open:
            raise FaceControlError(
                "Yalnız aktiv istisnanın müddəti uzadıla bilər",
                user_message="Bu istisna artıq bağlanıb.",
                context={"status": exemption.status.value},
            )
        if new_expiry <= exemption.expires_at:
            raise FaceControlError(
                "Yeni müddət cari müddətdən sonra olmalıdır",
                user_message="Yeni bitmə tarixi mövcuddan gec olmalıdır.",
            )
        self._require_within_ceiling(
            tenant_id, granted_at=exemption.granted_at, expires_at=new_expiry
        )

        extended = exemption.extended(new_expiry=new_expiry)
        self._exemptions.save(extended)
        self._record(
            extended,
            actor=actor,
            action="FACE_EXEMPTION_EXTENDED",
            reason=extended.reason,
            title_az="Face Control istisnası uzadıldı",
            body_az=(
                f"İstisnanın müddəti {new_expiry.date().isoformat()} tarixinə qədər "
                f"uzadıldı. Məcburi ikinci təsdiq tələbi qüvvədə qalır."
            ),
        )
        return extended

    def revoke(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        exemption_id: FaceExemptionId,
        reason: str,
    ) -> FaceExemption:
        """Vaxtından əvvəl ləğv — İNSAN QƏRARI, səbəb məcburidir."""
        now = self._clock.now()
        self._require_permission(actor)
        cleaned = self._require_reason(reason)
        exemption = self._require_exemption(tenant_id, exemption_id)
        if not exemption.status.is_open:
            raise FaceControlError(
                "Yalnız aktiv istisna ləğv edilə bilər",
                user_message="Bu istisna artıq bağlanıb.",
                context={"status": exemption.status.value},
            )

        revoked = exemption.revoked(revoked_by=actor.id, revoked_at=now, reason=cleaned)
        self._exemptions.save(revoked)
        self._record(
            revoked,
            actor=actor,
            action="FACE_EXEMPTION_REVOKED",
            reason=cleaned,
            title_az="Face Control istisnası ləğv edildi",
            body_az=(
                f"İstisna vaxtından əvvəl ləğv olundu. Səbəb: {cleaned}. İşçi bundan "
                f"sonra normal üz təsdiqindən keçəcək."
            ),
        )
        return revoked

    def expire_due(self, *, tenant_id: TenantId, now: datetime | None = None) -> int:
        """Müddəti bitmiş istisnaları `EXPIRED`-ə keçirir — GECƏLİK İŞ (bənd 14).

        SƏLAHİYYƏT YOXLAMASI YOXDUR VƏ BU QƏSDƏNDİR: bu, istifadəçi əməliyyatı
        deyil, planlaşdırılmış sistem işidir; aktoru yoxdur
        (`audit.actor_id = None`). Eyni qərar `ExceptionEngineUseCase.run` və
        `JobRunner.run_due`-dadır — gecə işləyən dövrəyə süni "istifadəçi"
        uydurmaq lazım gələrdi.

        İDEMPOTENTDİR: ikinci icra artıq `EXPIRED` olan sətri görmür
        (`list_due_for_expiry` yalnız `ACTIVE` qaytarır) — planlayıcının
        at-least-once zəmanəti üçün məcburi şərt (`job_runner.py` başlığı).
        """
        moment = now or self._clock.now()
        expired = 0
        for exemption in self._exemptions.list_due_for_expiry(tenant_id, now=moment):
            closed = exemption.expired()
            self._exemptions.save(closed)
            expired += 1
            self._audit.record(
                tenant_id=tenant_id,
                actor_id=None,  # avtomatik keçid — insan qərarı deyil
                action="FACE_EXEMPTION_EXPIRED",
                entity_type="face_control_exemptions",
                entity_id=closed.exemption_id,
                before_state={"status": exemption.status.value},
                after_state={
                    "status": closed.status.value,
                    "employee_id": str(closed.employee_id),
                    "expires_at": closed.expires_at.isoformat(),
                },
                reason="Müddət bitdi — istisna avtomatik ləğv olundu",
            )
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=None,
                category="FACE_EXEMPTION_EXPIRED",
                title_az="Face Control istisnasının müddəti bitdi",
                body_az=(
                    "İstisnanın müddəti bitdi və avtomatik ləğv olundu. İşçi bundan "
                    "sonra üz təsdiqindən keçəcək; ehtiyac davam edirsə istisna "
                    "YENİDƏN əsaslandırılmalıdır."
                ),
                is_critical=False,
            )
        if expired:
            _log.info(
                "FACE_EXEMPTIONS_EXPIRED",
                extra={"tenant_id": str(tenant_id), "count": expired},
            )
        return expired

    def list_active(self, *, tenant_id: TenantId, actor: Employee) -> list[FaceExemptionView]:
        """Aktiv istisnalar — Root/CEO idarəetmə ekranının siyahısı.

        OXU DA EYNİ FLAG-LƏ QORUNUR: siyahı "kim üz təsdiqindən azaddır"
        sualının cavabıdır və bu, hücum planlaşdırmaq üçün birbaşa yararlı
        məlumatdır (`ExceptionEngineUseCase._require_view` ilə eyni qərar:
        oxu və qərar eyni flag-dədir).
        """
        self._require_permission(actor)
        now = self._clock.now()
        return [
            FaceExemptionView(
                exemption=exemption,
                days_remaining=max(0, (exemption.expires_at - now).days),
            )
            for exemption in self._exemptions.list_active(tenant_id, now=now)
        ]

    # ------------------------------ köməkçi --------------------------------- #

    def _require_permission(self, actor: Employee) -> None:
        if not actor.has_permission(MANAGE_EXEMPTIONS_FLAG, now=self._clock.now()):
            _security_log.warning(
                "FACE_EXEMPTION_PERMISSION_DENIED",
                extra={"actor_id": str(actor.id), "flag": MANAGE_EXEMPTIONS_FLAG},
            )
            raise FaceControlPermissionError(
                f"'{MANAGE_EXEMPTIONS_FLAG}' səlahiyyəti olmadan Face Control istisnası "
                f"idarə edilə bilməz (adi `{ENROLLMENT_FLAG}` KİFAYƏT ETMİR)",
                context={"actor_id": str(actor.id), "flag": MANAGE_EXEMPTIONS_FLAG},
            )

    def _require_compensating_control(self, tenant_id: TenantId, *, operation: str) -> None:
        """Kompensasiya edici nəzarət AÇIQ olmalıdır (SEC-020).

        SÜKUTLA "heç nə etmə" DEYİL — açıq istisna atılır (CLAUDE.md §6):
        Root/CEO düyməni basıb və nəticə gözləyir. Mesaj həm SƏBƏBİ, həm də
        NƏ ETMƏLİ olduğunu deyir, çünki "əməliyyat mümkün deyil" cavabı
        istifadəçini eyni düyməni yenidən basmağa göndərərdi.
        """
        if self._toggles.is_enabled(tenant_id, FACE_EXEMPTION_COMPENSATING_MODULE.value):
            return
        _security_log.warning(
            "FACE_EXEMPTION_BLOCKED_WITHOUT_COMPENSATION",
            extra={
                "tenant_id": str(tenant_id),
                "module": FACE_EXEMPTION_COMPENSATING_MODULE.value,
                "operation": operation,
            },
        )
        raise FaceControlError(
            f"«{FACE_EXEMPTION_COMPENSATING_MODULE.value}» modulu söndürülüb — "
            f"Face Control istisnası {operation} bilməz (bənd 14: istisnanın yeganə "
            f"kompensasiya edici nəzarəti həmin moduldur)",
            user_message=(
                "Cüt-nəzarət modulu söndürülüb. Üz təsdiqi istisnası yalnız məcburi "
                "ikinci təsdiqlə birlikdə verilə bilər — əvvəlcə ROOT İdarə Mərkəzindən "
                "«Cüt-nəzarətli əlavə təsdiq qatı» modulunu aktivləşdirin."
            ),
            context={"module": FACE_EXEMPTION_COMPENSATING_MODULE.value},
        )

    @staticmethod
    def _require_reason(reason: str) -> str:
        cleaned = reason.strip()
        if len(cleaned) < MIN_EXEMPTION_REASON_LENGTH:
            raise FaceControlError(
                f"İstisnanın səbəbi ən azı {MIN_EXEMPTION_REASON_LENGTH} simvol olmalıdır",
                user_message=(
                    f"Səbəb ən azı {MIN_EXEMPTION_REASON_LENGTH} simvol olmalıdır — "
                    f"sənədləşməmiş istisna auditdə müdafiə oluna bilmir."
                ),
                context={"length": len(cleaned)},
            )
        return cleaned

    def _require_within_ceiling(
        self, tenant_id: TenantId, *, granted_at: datetime, expires_at: datetime
    ) -> None:
        max_days = self._limit_int(tenant_id, SystemLimitKey.FACE_EXEMPTION_MAX_DAYS)
        if expires_at <= granted_at:
            raise FaceControlError(
                "İstisnanın bitmə anı təyinat anından sonra olmalıdır",
                user_message="Bitmə tarixi başlanğıcdan sonra olmalıdır.",
            )
        span_days = (expires_at - granted_at).days
        if span_days > max_days:
            raise FaceControlError(
                f"İstisnanın müddəti {max_days} günü aşa bilməz (tələb: {span_days} gün)",
                user_message=(
                    f"İstisna ən çox {max_days} gün ola bilər. Ehtiyac davam edərsə, "
                    f"müddət bitəndən sonra yenidən əsaslandırılmalıdır."
                ),
                context={"max_days": max_days, "requested_days": span_days},
            )

    def _require_exemption(
        self, tenant_id: TenantId, exemption_id: FaceExemptionId
    ) -> FaceExemption:
        exemption = self._exemptions.get(exemption_id)
        if exemption is None or exemption.tenant_id != tenant_id:
            # Tapılmayan və "başqa kirayəçinin" halı EYNİ mesajı verir: fərqli
            # mətn "bu ID mövcuddur, sadəcə sizin deyil" məlumatını sızdırardı
            # (`ExceptionEngineUseCase._require_record` ilə eyni qərar).
            raise FaceControlError(
                "İstisna tapılmadı",
                user_message="Bu istisna mövcud deyil.",
                context={"exemption_id": str(exemption_id)},
            )
        return exemption

    def _record(
        self,
        exemption: FaceExemption,
        *,
        actor: Employee,
        action: str,
        reason: str,
        title_az: str,
        body_az: str,
    ) -> None:
        """Audit + bildiriş — hər üç əməliyyat (təyinat/uzatma/ləğv) üçün eyni."""
        self._audit.record(
            tenant_id=exemption.tenant_id,
            actor_id=actor.id,
            action=action,
            entity_type="face_control_exemptions",
            entity_id=exemption.exemption_id,
            after_state={
                "employee_id": str(exemption.employee_id),
                "status": exemption.status.value,
                "granted_at": exemption.granted_at.isoformat(),
                "expires_at": exemption.expires_at.isoformat(),
            },
            reason=reason,
        )
        _security_log.warning(
            action,
            extra={
                "actor_id": str(actor.id),
                "employee_id": str(exemption.employee_id),
                "expires_at": exemption.expires_at.isoformat(),
            },
        )
        self._notifier.notify(
            tenant_id=exemption.tenant_id,
            recipient_id=exemption.employee_id,
            category=action,
            title_az=title_az,
            body_az=body_az,
            is_critical=True,
        )

    def _limit_int(self, tenant_id: TenantId, key: SystemLimitKey) -> int:
        return self._limits.get_int(tenant_id, key.value, int(DEFAULT_LIMITS[key]))


# --------------------------------------------------------------------------- #
# 4b. Üz kilidinin AÇILMASI (bənd 4-ün ödənilməmiş tərəfi)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FaceLockReleaseResult:
    """Kilid açılışının nəticəsi — ekran mətni buradan qurulur.

    `re_enrollment_recommended` AYRI SAHƏDİR, mətnin içində GİZLƏNMİR: Root/CEO
    ekranı ondan asılı olaraq «[Yenidən Qeydiyyat]» düyməsini göstərir və
    mətndən açar söz axtarmaq iki qatı bir-birinə bağlayardı.
    """

    employee_id: EmployeeId
    was_locked: bool
    cleared_attempts: int
    re_enrollment_recommended: bool
    message_az: str


class FaceLockReleaseUseCase:
    """Ardıcıl uyğunsuzluqdan doğan üz kilidini VAXTINDAN ƏVVƏL açır.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ LAZIMDIR — AVTOMATİK BİTMƏ TƏK BAŞINA CAVAB DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Kilid `PIN_LOCKOUT_MINUTES` keçdikdə ÖZÜ bitir (`FaceProfile.is_locked`
    vaxt müqayisəsidir) və uğurlu doğrulama sayğacı sıfırlayır (`_success`).
    Yəni ADİ hal onsuz da bağlıdır və bu use case ADİ yol DEYİL.

    Bağlanmayan hal budur: kilidli işçi `verify()`-dan `AccountLockedError`
    alır, yəni müddət bitənə qədər UĞURLU doğrulama da edə bilmir — sayğacı
    sıfırlamağın yeganə yolu GÖZLƏMƏKDİR. Root `PIN_LOCKOUT_MINUTES`-i
    böyütmüşsə (parametr PIN ilə ORTAQDIR — bənd 4 ayrı müddət açarını
    qadağan edir), gözləmə işçinin bütün növbəsini yeyə bilər və nəticə süni
    gecikmə/qayıb olar. Ona görə AÇIQ, izlənilən bir açar lazımdır.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `can_manage_face_exemptions`, NİYƏ HR SƏVİYYƏSİ DEYİL
    ──────────────────────────────────────────────────────────────────────────
    YENİ FLAG YARADILMADI: CLAUDE.md §5 cədvəli yeni icazə flag-inin yerini
    `permission_flags`-də (Root, GUI-dan) göstərir — kodda flag icad etmək
    həmin qərarı yan keçərdi.

    Mövcud kataloqdan seçim İKİ namizəd arasında idi:

      * `can_manage_employees` (hardlock 0) — praktik olardı (HR_Admin-də
        var), LAKİN RƏDD EDİLDİ: hardlock səviyyəsi 0 və `is_anti_fraud`
        FALSE olduğu üçün onu fərdi override ilə `Mağaza_Meneceri`-yə vermək
        STRUKTUR OLARAQ mümkündür. Öz mağazasının işçisinin üz kilidini açan
        mağaza meneceri isə anti-fraud vəzifə ayrılığının mənasını yox edərdi
        (CLAUDE.md §5) — qoruma "defolt verilmir" səviyyəsinə enərdi.
      * `can_manage_face_exemptions` (hardlock 2 = ROOT_CEO, migrations/047)
        — SEÇİLDİ. Səbəb: (a) hardlock strukturdur, yəni flag
        `Mağaza_Meneceri`/`Satıcı`-ya HEÇ BİR override ilə düşə bilməz;
        (b) semantik ailə eynidir — hər iki əməliyyat KONKRET işçi üçün üz
        qapısını yumşaldır; (c) miqrasiya/sxem dəyişikliyi tələb etmir.

    ƏMƏLİYYAT SÜRTÜNMƏSİ QƏBUL EDİLİR VƏ QƏSDLİDİR: gündəlik hal avtomatik
    bitmə ilə həll olunur, bu yol isə istisnadır və istisna nə qədər dar
    olsa, təkrarlanması bir o qədər görünəndir.

    ──────────────────────────────────────────────────────────────────────────
    AÇILIŞ TARİXÇƏNİ SİLMİR
    ──────────────────────────────────────────────────────────────────────────
    `face_verification_log` sətirlərinə TOXUNULMUR — yalnız `employees` üzərindəki
    SAYĞAC və KİLİD sıfırlanır. Səbəb: təkrarlanan açılış özü anomaliya
    siqnalıdır və `FaceMismatchExceptionRule` həmin jurnaldan qidalanır.
    Sayğacla birlikdə jurnalı da təmizləsəydik, "bu işçinin üzü ayda beş dəfə
    tanınmır" faktı hər açılışdan sonra sıfırdan başlayardı.
    """

    def __init__(
        self,
        *,
        profiles: FaceEmbeddingRepository,
        limits: SystemLimits,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier,
    ) -> None:
        self._profiles = profiles
        self._limits = limits
        self._audit = audit
        self._clock = clock
        self._notifier = notifier

    def release(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        subject_id: EmployeeId,
        reason: str,
    ) -> FaceLockReleaseResult:
        """Sayğacı sıfırlayır və kilidi götürür — SƏBƏB MƏCBURİDİR.

        SƏBƏBİN MİNİMUM UZUNLUĞU YOXDUR (yalnız "boş olmasın"): 10 simvol
        həddi `face_control_exemptions.reason` sütununun `CHECK` güzgüsüdür
        (bax `MIN_EXEMPTION_REASON_LENGTH`), kilid açılışının isə öz sütunu
        yoxdur — sxem məhdudiyyətini olmayan cədvələ tətbiq etmək onu biznes
        qaydası kimi göstərmək olardı. Mövcud analoq `FaceReEnrollmentUseCase.
        re_enroll` və `FaceExemption.revoked`-dır: hər ikisi məhz "boş ola
        bilməz" yoxlaması edir.
        """
        self._require_permission(actor)
        cleaned = _require_non_empty_reason(reason)
        if actor.id == subject_id:
            # VƏZİFƏ AYRILIĞI — `FaceEnrollmentUseCase.assert_may_enroll` ilə
            # EYNİ qayda və eyni səbəb: üz qapısına toxunan əməliyyat İKİNCİ
            # insan tələb edir. Flag sahibi (Root/CEO) öz kilidini özü açsaydı,
            # kilid onun üçün faktiki olaraq mövcud olmazdı.
            raise FaceControlPermissionError(
                "Öz üz kilidinizi özünüz aça bilməzsiniz — ikinci şəxs tələb olunur",
                user_message="Öz üz kilidinizi özünüz aça bilməzsiniz.",
                context={"actor_id": str(actor.id)},
            )

        now = self._clock.now()
        profile = self._profiles.get_profile(subject_id)
        if profile is None:
            raise FaceControlError(
                "İşçinin üz profili tapılmadı",
                user_message="Bu işçi tapılmadı.",
                context={"employee_id": str(subject_id)},
            )

        was_locked = profile.is_locked(now=now)
        if not was_locked and profile.mismatch_attempts == 0:
            # SÜKUTLA "heç nə etmə" QADAĞANDIR (CLAUDE.md §6): Root düyməni
            # basıb və nəticə gözləyir. Sükutla uğur qaytarsaydıq, ekranda
            # «açıldı» yazılar, faktiki problem isə (məs. PIN kilidi, ki
            # AYRI sütundur — `employees.pin_locked_until`) həll olunmamış
            # qalardı və növbəti cəhd yenə uğursuz olardı.
            raise FaceControlError(
                "Bu işçidə açılacaq üz kilidi və ya uyğunsuzluq sayğacı yoxdur",
                user_message=(
                    "Bu işçinin üz kilidi yoxdur. Giriş yenə mümkün deyilsə, səbəb "
                    "PIN kilidi ola bilər — o, ayrıca mexanizmdir."
                ),
                context={"employee_id": str(subject_id)},
            )

        cleared_attempts = profile.mismatch_attempts
        # MÖVCUD YAZI METODU — yeni repo metodu YAZILMIR. `_success` uğurlu
        # doğrulamada məhz bu cütü yazır (0 / None), yəni "kilid açıldı"
        # vəziyyəti sistemdə ARTIQ təyin olunub və ikinci tərifi yaratmırıq.
        self._profiles.save_security(subject_id, mismatch_attempts=0, locked_until=None)

        reminder_months = self._limit_int(
            tenant_id, SystemLimitKey.FACE_REENROLLMENT_REMINDER_MONTHS
        )
        re_enrollment_recommended = profile.is_stale(now=now, reminder_months=reminder_months)

        _security_log.warning(
            "FACE_LOCK_RELEASED",
            extra={
                "actor_id": str(actor.id),
                # KİMİN KİLİDİ: sətir PIN SAHİBİNƏ aiddir. Kilidi doğuran üz
                # isə tanınmamış üzdür və o, başqa adam ola bilər — məhz buna
                # görə uyğunsuzluq baş verib. İki fərqli şəxsin eyni açarla
                # yazılması araşdırmanı yanlış izə salardı.
                "locked_pin_owner_id": str(subject_id),
                "cleared_attempts": cleared_attempts,
                "was_locked": was_locked,
                "re_enrollment_recommended": re_enrollment_recommended,
            },
        )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="FACE_LOCK_RELEASED",
            entity_type="employees",
            entity_id=subject_id,
            before_state={
                "face_mismatch_attempts": cleared_attempts,
                "face_locked_until": (
                    profile.locked_until.isoformat() if profile.locked_until else None
                ),
            },
            after_state={
                "face_mismatch_attempts": 0,
                "face_locked_until": None,
                "re_enrollment_recommended": re_enrollment_recommended,
                # Audit oxucusuna AÇIQ deyilir ki, sətir PIN sahibinin qeydinə
                # aiddir — jurnalda "kim kilidlənmişdi?" sualı iki cavablıdır.
                "subject_role": "PIN_OWNER",
            },
            reason=cleaned,
        )
        message = (
            "Üz kilidi açıldı və uyğunsuzluq sayğacı sıfırlandı."
            if was_locked
            else "Uyğunsuzluq sayğacı sıfırlandı (aktiv kilid yox idi)."
        )
        if re_enrollment_recommended:
            # KİLİD SƏBƏBİ QEYDİYYAT PROBLEMİ OLA BİLƏR: köhnəlmiş istinad
            # vektoru (saqqal, eynək, çəki — bənd 13) hər doğrulamada
            # uyğunsuzluq doğurur və kilidi TƏKRAR-TƏKRAR qurur. Belə halda
            # açılış yalnız simptomu götürür, ona görə istifadəçi MÖVCUD
            # yenidən-qeydiyyat axınına yönləndirilir (`FaceReEnrollmentUseCase`)
            # — burada ikinci bir "düzəlt" mexanizmi yazılmır.
            message += (
                " Diqqət: bu işçinin üz qeydiyyatı köhnəlib — kilid təkrarlanarsa "
                "«Yenidən Qeydiyyat» aparın, təkrar açılış problemi həll etmir."
            )
        self._notifier.notify(
            tenant_id=tenant_id,
            # ŞƏXSİ SƏTİR (`recipient_id` dolu) — auditoriya süzgəcindən
            # asılı deyil (bax `value_objects/notifications.py` başlığı).
            # İşçi öz hesabına toxunulduğunu bilməlidir: kilid onun adına
            # qurulmuşdu və onun adına götürülür.
            recipient_id=subject_id,
            category="FACE_LOCK_RELEASED",
            title_az="Üz kilidiniz açıldı",
            body_az=(
                f"Üz uyğunsuzluğuna görə qurulmuş kilid {actor.full_name} tərəfindən "
                f"açıldı. Səbəb: {cleaned}"
            ),
            is_critical=True,
        )
        return FaceLockReleaseResult(
            employee_id=subject_id,
            was_locked=was_locked,
            cleared_attempts=cleared_attempts,
            re_enrollment_recommended=re_enrollment_recommended,
            message_az=message,
        )

    # ------------------------------ köməkçi --------------------------------- #

    def _require_permission(self, actor: Employee) -> None:
        if not actor.has_permission(MANAGE_EXEMPTIONS_FLAG, now=self._clock.now()):
            _security_log.warning(
                "FACE_LOCK_RELEASE_PERMISSION_DENIED",
                extra={"actor_id": str(actor.id), "flag": MANAGE_EXEMPTIONS_FLAG},
            )
            raise FaceControlPermissionError(
                f"'{MANAGE_EXEMPTIONS_FLAG}' səlahiyyəti olmadan üz kilidi açıla bilməz "
                f"(adi `{ENROLLMENT_FLAG}` KİFAYƏT ETMİR — bax sinif başlığı)",
                user_message="Üz kilidini açmaq səlahiyyətiniz yoxdur.",
                context={"actor_id": str(actor.id), "flag": MANAGE_EXEMPTIONS_FLAG},
            )

    def _limit_int(self, tenant_id: TenantId, key: SystemLimitKey) -> int:
        return self._limits.get_int(tenant_id, key.value, int(DEFAULT_LIMITS[key]))


def _require_non_empty_reason(reason: str) -> str:
    """Boş səbəb qadağandır — sənədləşməmiş açılış auditdə müdafiə olunmur."""
    cleaned = " ".join(reason.split())
    if not cleaned:
        raise FaceControlError(
            "Üz kilidinin açılma səbəbi boş ola bilməz",
            user_message="Kilidi açmaq üçün səbəb yazılmalıdır.",
        )
    return cleaned


# --------------------------------------------------------------------------- #
# 5. Saxlama müddəti (bənd 17) — gecəlik iş
# --------------------------------------------------------------------------- #


class FaceVerificationLogRetentionUseCase:
    """`face_verification_log` saxlama müddəti təmizləməsi (bənd 17).

    ANONİMLƏŞDİRMƏ YOX, TAM SİLMƏ: jurnalda foto və vektor onsuz da yoxdur
    (sxem bunu struktur olaraq təmin edir), yalnız nəticə, bal və kontekst
    var. Anonimləşdirmə həmin sətirləri hesabat üçün yararsız edər, lakin heç
    bir əlavə məxfilik qazandırmazdı.

    TƏHLÜKƏSİZLİK TƏSDİQİ (bənd 17-nin öz tələbi): 12 aylıq defolt mövcud
    Davranış Anomaliyası baz xəttinin pəncərəsindən (`BEHAVIOR_BASELINE_
    WINDOW_DAYS`, defolt 30 gün) qat-qat genişdir — silmə həmin hesablamanı
    POZMUR.
    """

    def __init__(
        self,
        *,
        verification_log: FaceVerificationLogRepository,
        limits: SystemLimits,
        audit: AuditTrail,
        clock: Clock,
    ) -> None:
        self._verification_log = verification_log
        self._limits = limits
        self._audit = audit
        self._clock = clock

    def purge(self, *, tenant_id: TenantId, now: datetime | None = None) -> int:
        """Saxlama müddətindən köhnə sətirləri silir və audit yazır.

        AQREQAT AUDİT SƏTRİ (hər silinən sətir üçün ayrıca yazı YOX): naxış
        `JobRunner._record_audit` ilə eynidir — minlərlə sətir üçün minlərlə
        audit yazısı `audit_logs`-u doldurar və HƏQİQİ insan qərarları həmin
        axında itərdi. Heç nə silinməyibsə audit sətri də yoxdur.
        """
        moment = now or self._clock.now()
        months = self._limit_int(tenant_id, SystemLimitKey.FACE_VERIFICATION_LOG_RETENTION_MONTHS)
        if months <= 0:
            # Sıfır/mənfi dəyər "dərhal sil" demək olardı və auditi tamamilə
            # yox edərdi. Sxem `min_value = 1` qoyur; kod tərəfi də eyni
            # fail-closed cavabı verir: təmizləmə APARILMIR.
            _log.warning(
                "FACE_LOG_RETENTION_INVALID",
                extra={"tenant_id": str(tenant_id), "months": months},
            )
            return 0

        cutoff = add_months(moment, -months)
        removed = self._verification_log.purge_older_than(tenant_id, cutoff=cutoff)
        if removed:
            self._audit.record(
                tenant_id=tenant_id,
                actor_id=None,  # planlaşdırılmış iş — aktoru yoxdur
                action="FACE_VERIFICATION_LOG_PURGED",
                entity_type="face_verification_log",
                after_state={
                    "removed_rows": removed,
                    "cutoff": cutoff.isoformat(),
                    "retention_months": months,
                },
                reason="Saxlama müddəti təmizləməsi (facecontrol.md bənd 17)",
            )
            _log.info(
                "FACE_VERIFICATION_LOG_PURGED",
                extra={"tenant_id": str(tenant_id), "removed": removed},
            )
        return removed

    def _limit_int(self, tenant_id: TenantId, key: SystemLimitKey) -> int:
        return self._limits.get_int(tenant_id, key.value, int(DEFAULT_LIMITS[key]))


# --------------------------------------------------------------------------- #
# 6. İstisna Motoruna qoşulma (bənd 16)
# --------------------------------------------------------------------------- #


class FaceMismatchExceptionRule:
    """MISMATCH hadisələrini mövcud İstisna Motoruna daşıyan qayda (bənd 16).

    ──────────────────────────────────────────────────────────────────────────
    MOTORUN KODU DƏYİŞMİR
    ──────────────────────────────────────────────────────────────────────────
    `ExceptionRule` Protokoluna strukturaldır (miras yoxdur) və motora
    `engine.register_rule(FaceMismatchExceptionRule(...))` ilə qoşulur —
    `BehaviorAnomalyRule` ilə tam eyni naxış. `FACE_MISMATCH` mənbəyi
    `exception_sources` kataloquna miqrasiya ilə seed edilib
    (`default_severity = 'CRITICAL'`), yəni motorda nə `if` şərti, nə yeni
    sahə lazımdır.

    ⚠️ BU QAYDA DƏRHAL-BİLDİRİŞİ ƏVƏZ ETMİR (bənd 16-nın təhlükəsizlik qeydi).
    `FaceVerificationUseCase._mismatch` uyğunsuzluq anında HR_Admin/Store
    Manager-ə TƏCİLİ bildiriş göndərir; bu qayda isə gecəlik motorla işləyir
    və HR-in VAHİD siyahısını doldurur. İkisini birləşdirsəydik (yalnız
    motor), ən yüksək-təhlükəli siqnal "sonra baxaram" siyahısına düşərdi və
    bir gecəlik gecikmə qazanardı.
    """

    def __init__(self, *, verification_log: FaceVerificationLogRepository) -> None:
        self._verification_log = verification_log

    @property
    def source_code(self) -> str:
        return FACE_MISMATCH_SOURCE

    @property
    def name_az(self) -> str:
        return "Üz Uyğunsuzluğu"

    def evaluate(self, context: RuleEvaluationContext) -> list[ExceptionFinding]:
        """Son `MISMATCH_LOOKBACK_DAYS` gündəki uyğunsuzluqları tapıntıya çevirir.

        `severity` QƏSDƏN VERİLMİR (`None`): motor onu mənbənin
        `default_severity` sütunundan (`CRITICAL`) doldurur — yəni ciddiyyəti
        dəyişmək üçün YENİ BURAXILIŞ lazım deyil, bir `UPDATE` kifayətdir
        (migrations/018-in bu sütunu əlavə etmə səbəbi).

        `dedupe_key` = işçi + cəhdin ANI. Motorun təkrar qapağı buna görə
        işləyir: eyni uyğunsuzluq iki gecə üst-üstə görünsə də ikinci istisna
        YARANMIR. Məhz bu səbəbdən geriyə baxış pəncərəsini geniş saxlamaq
        təhlükəsizdir (bax `MISMATCH_LOOKBACK_DAYS`).
        """
        since = context.as_of - timedelta(days=MISMATCH_LOOKBACK_DAYS)
        findings: list[ExceptionFinding] = []
        for entry in self._verification_log.list_mismatches_since(context.tenant_id, since=since):
            if entry.store_id is None:
                # `exceptions.store_id` `NOT NULL`-dur: mağazasız sətir üçün
                # istisna yaradıla bilməz. Belə sətir yalnız mağazası silinmiş
                # (`ON DELETE SET NULL`) tarixi qeydlərdə olur — onları
                # atlamaq, uydurma mağaza yazmaqdan doğrudur.
                continue
            findings.append(
                ExceptionFinding(
                    employee_id=entry.employee_id,
                    store_id=entry.store_id,
                    detail=(
                        f"Kioskda PIN daxil edən şəxsin üzü PIN sahibinin qeydiyyatlı "
                        f"üzü ilə uyğun gəlmədi ({entry.trigger_context.value})."
                        + (
                            " Üz EYNİ MAĞAZANIN başqa işçisinə uyğun gəldi."
                            if entry.matched_other_employee_id is not None
                            else ""
                        )
                    ),
                    context={
                        "trigger_context": entry.trigger_context.value,
                        "confidence_score": entry.confidence_score,
                        "lockout_triggered": entry.lockout_triggered,
                        "matched_other_employee_id": (
                            str(entry.matched_other_employee_id)
                            if entry.matched_other_employee_id is not None
                            else None
                        ),
                        "occurred_at": entry.occurred_at.isoformat(),
                    },
                    dedupe_key=f"{entry.employee_id}:{entry.occurred_at.isoformat()}",
                )
            )
        return findings


# --------------------------------------------------------------------------- #
# Modul səviyyəli köməkçi
# --------------------------------------------------------------------------- #


def _evaluate_frames(
    frames: Sequence[FaceFrame],
    *,
    matcher: FaceMatcher,
    minimum_quality: float,
) -> tuple[tuple[FaceEnrollmentFrameOutcome, ...], list[FaceEmbedding]]:
    """Hər kadrı alignment + keyfiyyət süzgəcindən keçirir (bənd 1, 10).

    KADR-KADR NƏTİCƏ SAXLANILIR: operatorun növbəti addımı "neçəsi keçdi"
    sualından asılıdır. Ümumi bir `bool` qaytarsaydıq, «[Yenidən Çək]» mesajı
    səbəbini deyə bilməzdi və operator kameranı, işığı və işçinin duruşunu
    təsadüfi qaydada yoxlamalı olardı.
    """
    outcomes: list[FaceEnrollmentFrameOutcome] = []
    accepted: list[FaceEmbedding] = []
    for index, frame in enumerate(frames, start=1):
        # `gesture=None` — enrollment-də liveness tələb edilmir (bax
        # `_capture_and_store` şərhi: işçi admin-in yanındadır).
        sample = matcher.extract(frame)
        if not sample.has_face:
            outcomes.append(
                FaceEnrollmentFrameOutcome(
                    index=index,
                    accepted=False,
                    quality=sample.quality,
                    reason_az="Kadrda üz aşkarlanmadı",
                )
            )
            continue
        if not sample.meets_quality(minimum_quality):
            outcomes.append(
                FaceEnrollmentFrameOutcome(
                    index=index,
                    accepted=False,
                    quality=sample.quality,
                    reason_az=(
                        f"Keyfiyyət balı {sample.quality:.2f} — tələb olunan {minimum_quality:.2f}"
                    ),
                )
            )
            continue
        outcomes.append(
            FaceEnrollmentFrameOutcome(index=index, accepted=True, quality=sample.quality)
        )
        assert sample.embedding is not None  # `has_face` yuxarıda yoxlanıldı
        accepted.append(sample.embedding)
    return tuple(outcomes), accepted


__all__ = [
    "CAMERA_HEALTH_CATEGORY",
    "COMPENSATION_UNAVAILABLE_ACTION",
    "DUAL_CONTROL_CATEGORY",
    "ENROLLMENT_FLAG",
    "ESCALATION_CATEGORY",
    "MANAGE_EXEMPTIONS_FLAG",
    "MIN_EXEMPTION_REASON_LENGTH",
    "MISMATCH_CATEGORY",
    "MISMATCH_LOOKBACK_DAYS",
    "PERFORMANCE_HEALTH_CATEGORY",
    "FaceCameraUnavailableError",
    "FaceControlExemptionUseCase",
    "FaceControlPermissionError",
    "FaceEnrollmentResult",
    "FaceEnrollmentUseCase",
    "FaceExemptionView",
    "FaceGateDecision",
    "FaceGateOutcome",
    "FaceLockReleaseResult",
    "FaceLockReleaseUseCase",
    "FaceMismatchExceptionRule",
    "FaceReEnrollmentUseCase",
    "FaceVerificationLogRetentionUseCase",
    "FaceVerificationUseCase",
]
