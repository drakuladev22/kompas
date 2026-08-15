"""Face Control (üz təsdiqi) domen/tətbiq qatının qapıları — `facecontrol.md` Faza 2.

BAZA VƏ KİTABXANA LAZIM DEYİL: bütün portlar sahtə obyektlərlə əvəz olunur və
`face_recognition` (Dlib) heç yerdə idxal edilmir. Bu, təsadüf deyil, dizayn
qərarıdır — anti-fraud məntiqi ağır bir kitabxananın quraşdırılmasından ASILI
OLMAMALIDIR, əks halda o məntiq yalnız həmin kitabxana qurulmuş maşında
yoxlanardı.

──────────────────────────────────────────────────────────────────────────────
NƏ QORUNUR — VƏ NİYƏ MƏHZ BUNLAR
──────────────────────────────────────────────────────────────────────────────
Aşağıdakı hər qapı `facecontrol.md`-nin bir bəndinin SÜKUTLA pozula bilən
tərəfini bağlayır:

  1. MISMATCH → İLK DƏFƏDƏN dərhal bildiriş (bənd 3). Həddi gözləmək
     "iki uyğunsuzluq HR-in xəbəri olmadan keçdi" deməkdir.
  2. NO_FACE_DETECTED heç bir sayğaca düşmür (bənd 3). Əks halda işıqsız
     dəhlizdə duran vicdanlı işçi kilidlənərdi.
  3. Hədd dolduqda MÖVCUD lockout mexanizmi işə düşür (bənd 4) — yeni
     mexanizm deyil, `evaluate_pin_attempt` + `PIN_LOCKOUT_MINUTES`.
  4. Kamera nasazlığı SƏSSİZ PIN-only rejimi YARATMIR (bənd 5) — mövcud
     eskalasiya kanalına düşür.
  5. İstisnalı işçinin HƏR təsdiqi MƏCBURİ dual-control-a düşür (bənd 14).
  6. Müddəti bitmiş istisna avtomatik ləğv olunur (bənd 14).
  7. Aşağı-etibar zolağı əməliyyatı KEÇİRİR, lakin qeydi nişanlayır (bənd 12).
  8. TƏRS hədd konfiqurasiyası FAIL-CLOSED emal olunur (iki `system_limits`
     sətri arasındakı invariant DB `CHECK`-i ilə ifadə edilə bilmir).
  9. İşçi deaktiv ediləndə vektor HƏM sətirdən, HƏM ARXİVDƏN silinir (bənd 8).
 10. Qeydiyyatı işçi ÖZÜ apara bilmir (bənd 1).
 11. İstisna üçün `can_manage_employees` KİFAYƏT ETMİR (bənd 14).

Əlavə olaraq ROOT parametrlərinin FAKTİKİ oxunduğu yoxlanılır: kadr sayı,
keyfiyyət həddi, liveness kataloqu, kilid həddi, saxlama müddəti. Parametrin
`system_limits`-də olması ilə ONUN OXUNMASI ayrı-ayrı şeylərdir — ikincisi
olmadan Root dəyəri dəyişir, sistem isə köhnə davranışı saxlayır.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest

from src.application.use_cases.authentication import AccountLockedError
from src.application.use_cases.face_control import (
    CAMERA_HEALTH_CATEGORY,
    DUAL_CONTROL_CATEGORY,
    ENROLLMENT_FLAG,
    ESCALATION_CATEGORY,
    MANAGE_EXEMPTIONS_FLAG,
    MISMATCH_CATEGORY,
    PERFORMANCE_HEALTH_CATEGORY,
    FaceCameraUnavailableError,
    FaceControlExemptionUseCase,
    FaceControlPermissionError,
    FaceEnrollmentUseCase,
    FaceGateOutcome,
    FaceMismatchExceptionRule,
    FaceReEnrollmentUseCase,
    FaceVerificationLogRetentionUseCase,
    FaceVerificationUseCase,
)
from src.application.use_cases.user_management import UserManagementUseCase
from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.position import Position
from src.domain.policies import DEFAULT_LIMITS, FeatureModule, SystemLimitKey
from src.domain.value_objects.authorization import PermissionEffect, RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.exception_signals import (
    FACE_MISMATCH_SOURCE,
    RuleEvaluationContext,
)
from src.domain.value_objects.face_recognition import (
    FaceControlError,
    FaceEmbedding,
    FaceExemption,
    FaceExemptionStatus,
    FaceFrame,
    FaceProfile,
    FaceSample,
    FaceToleranceBand,
    FaceTriggerContext,
    FaceVerificationLogEntry,
    FaceVerificationResult,
    LivenessGesture,
    add_months,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    StoreId,
    TenantId,
    new_face_exemption_id,
)
from tests.fixtures.fakes import (
    FakeCamera,
    FakeClock,
    FakeFaceMatcher,
    FakeFaceStoreScope,
    FakeFeatureToggles,
    FakeSystemLimits,
    InMemoryEmployees,
    InMemoryFaceExemptions,
    InMemoryFaceProfiles,
    InMemoryFaceVerificationLog,
    RecordingAudit,
    RecordingNotifier,
)

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
USE_CASES_DIR: Final = PROJECT_ROOT / "src" / "application" / "use_cases"

NOW: Final = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
TENANT: Final = TenantId(uuid.uuid4())
STORE: Final = StoreId(uuid.uuid4())
OTHER_STORE: Final = StoreId(uuid.uuid4())

#: İstinad vektoru. BİR ÖLÇÜLÜDÜR VƏ BU QƏSDƏNDİR: sahtə matcher həqiqi
#: Evklid məsafəsi hesablayır, ona görə `(0.55,)` namizədin məsafəsi düz
#: 0.55-dir — yəni "0.55 aşağı-etibar zolağındadır" iddiası uydurulmuş ədədə
#: deyil, `FaceToleranceBand`-ın FAKTİKİ hesablamasına baxır.
REFERENCE: Final = FaceEmbedding(values=(0.0,))
#: Defolt hədlərlə (0.50 / 0.60) üç zolağın nümayəndələri.
CLOSE_MATCH: Final = FaceEmbedding(values=(0.10,))
BORDERLINE: Final = FaceEmbedding(values=(0.55,))
STRANGER: Final = FaceEmbedding(values=(0.95,))


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _position(code: str, priority: RolePriority) -> Position:
    return Position(
        position_id=uuid.uuid4(),  # type: ignore[arg-type]
        code=code,
        name_az=code.title(),
        priority=priority,
        tenant_id=TENANT,
        is_system=True,
    )


def _employee(
    *,
    flags: tuple[str, ...] = (),
    code: str = "HR_ADMIN",
    priority: RolePriority = RolePriority.OPERATIONAL,
    store_id: StoreId | None = STORE,
    employee_id: EmployeeId | None = None,
) -> Employee:
    employee = Employee(
        employee_id=employee_id or EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=_position(code, priority),
        first_name="Aygün",
        last_name="Əliyeva",
        store_id=store_id,
        username=Username(f"u.{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )
    for flag in flags:
        employee.apply_override(
            PermissionOverride(
                flag_code=flag, effect=PermissionEffect.GRANT, granted_by=employee.id
            )
        )
    return employee


def _profile(
    employee: Employee,
    *,
    embedding: FaceEmbedding | None = REFERENCE,
    enrolled_at: datetime | None = NOW,
    mismatch_attempts: int = 0,
    locked_until: datetime | None = None,
) -> FaceProfile:
    return FaceProfile(
        employee_id=employee.id,
        tenant_id=TENANT,
        store_id=employee.store_id,
        embedding=embedding,
        enrolled_at=enrolled_at if embedding is not None else None,
        mismatch_attempts=mismatch_attempts,
        locked_until=locked_until,
    )


class _Gate:
    """Doğrulama use case-i + bütün sahtələri bir yerdə saxlayan test qurğusu."""

    def __init__(
        self,
        *,
        profiles: InMemoryFaceProfiles,
        camera: FakeCamera,
        matcher: FakeFaceMatcher,
        clock: FakeClock,
        limits: FakeSystemLimits,
        exemptions: InMemoryFaceExemptions,
        scope: FakeFaceStoreScope,
        toggles: FakeFeatureToggles,
    ) -> None:
        self.profiles = profiles
        self.camera = camera
        self.matcher = matcher
        self.clock = clock
        self.limits = limits
        self.exemptions = exemptions
        self.scope = scope
        self.toggles = toggles
        self.log = InMemoryFaceVerificationLog()
        self.audit = RecordingAudit()
        self.notifier = RecordingNotifier()
        self.use_case = FaceVerificationUseCase(
            profiles=profiles,
            verification_log=self.log,
            exemptions=exemptions,
            store_scope=scope,
            camera=camera,
            matcher=matcher,
            limits=limits,
            toggles=toggles,
            audit=self.audit,
            clock=clock,
            notifier=self.notifier,
        )

    def verify(
        self, employee: Employee, context: FaceTriggerContext = FaceTriggerContext.STEP_A
    ) -> Any:
        return self.use_case.verify(tenant_id=TENANT, employee=employee, trigger_context=context)


def _gate(
    *,
    employee: Employee,
    candidate: FaceEmbedding | None = CLOSE_MATCH,
    profiles: list[FaceProfile] | None = None,
    camera_available: bool = True,
    limits: dict[str, str] | None = None,
    exemptions: list[FaceExemption] | None = None,
    scope: set[StoreId] | None = None,
    disabled_modules: set[str] | None = None,
    liveness_confirmed: bool = True,
    quality: float = 0.9,
    delay_seconds: float = 0.0,
    profile: FaceProfile | None = None,
) -> _Gate:
    clock = FakeClock(NOW)
    repository = InMemoryFaceProfiles(
        profiles if profiles is not None else [profile or _profile(employee)]
    )
    sample = FaceSample(embedding=candidate, quality=quality, liveness_confirmed=liveness_confirmed)
    return _Gate(
        profiles=repository,
        camera=FakeCamera(available=camera_available, clock=clock, delay_seconds=delay_seconds),
        matcher=FakeFaceMatcher([sample], clock=clock),
        clock=clock,
        limits=FakeSystemLimits(limits),
        exemptions=InMemoryFaceExemptions(exemptions or []),
        scope=FakeFaceStoreScope(scope),
        toggles=FakeFeatureToggles(disabled_modules),
    )


def _exemption(
    employee: Employee,
    *,
    granted_at: datetime = NOW - timedelta(days=1),
    expires_at: datetime = NOW + timedelta(days=30),
    status: FaceExemptionStatus = FaceExemptionStatus.ACTIVE,
) -> FaceExemption:
    return FaceExemption(
        exemption_id=new_face_exemption_id(),
        tenant_id=TENANT,
        employee_id=employee.id,
        granted_by=EmployeeId(uuid.uuid4()),
        reason="Tibbi arayış — üz nahiyəsində sarğı var",
        granted_at=granted_at,
        expires_at=expires_at,
        status=status,
    )


# --------------------------------------------------------------------------- #
# 1. MISMATCH — İLK DƏFƏDƏN DƏRHAL BİLDİRİŞ (bənd 3)
# --------------------------------------------------------------------------- #


def test_a_mismatch_notifies_immediately_on_the_very_first_occurrence() -> None:
    """Bildiriş HƏDDİ GÖZLƏMİR — birinci uyğunsuzluqda göndərilir.

    Bənd 3 bunu açıq tələb edir. Bildirişi kilidə qədər saxlasaydıq, HR ilk
    iki cəhdi HEÇ VAXT görməzdi — halbuki uyğunsuzluğun ÖZÜ hadisədir və
    kilid yalnız onun təkrarlanmasının nəticəsidir.
    """
    worker = _employee()
    gate = _gate(employee=worker, candidate=STRANGER)

    decision = gate.verify(worker)

    assert decision.result is FaceVerificationResult.MISMATCH
    assert decision.outcome is FaceGateOutcome.BLOCKED
    assert not decision.allows_operation
    assert gate.notifier.categories().count(MISMATCH_CATEGORY) == 1
    assert gate.notifier.messages[0]["is_critical"] is True
    # Sayğac ARTIB, lakin kilid HƏLƏ YOXDUR — bildiriş ondan asılı deyil.
    assert gate.profiles.items[worker.id].mismatch_attempts == 1
    assert not decision.lockout_triggered


def test_a_mismatch_is_written_to_the_audit_trail_and_the_verification_log() -> None:
    worker = _employee()
    gate = _gate(employee=worker, candidate=STRANGER)

    gate.verify(worker, FaceTriggerContext.STEP_2)

    assert "FACE_MISMATCH" in gate.audit.actions()
    assert gate.log.results() == ["MISMATCH"]
    entry = gate.log.entries[0]
    assert entry.trigger_context is FaceTriggerContext.STEP_2
    assert entry.confidence_score is not None


def test_a_mismatch_cross_checks_only_colleagues_from_the_same_store() -> None:
    """Bənd 3 — cross-check MAĞAZA ilə məhdudlaşır.

    Bütün şəbəkə üzrə axtarış həm yavaşdır, həm də yalançı-müsbətə meyllidir:
    nəticə "PIN-i başqasına verib" ittihamıdır və zəif sübutla verilməməlidir.
    """
    worker = _employee()
    colleague = _employee(store_id=STORE)
    outsider = _employee(store_id=OTHER_STORE)
    gate = _gate(
        employee=worker,
        candidate=STRANGER,
        profiles=[
            _profile(worker),
            _profile(colleague, embedding=STRANGER),
            _profile(outsider, embedding=STRANGER),
        ],
    )

    decision = gate.verify(worker)

    assert decision.matched_other_employee_id == colleague.id
    assert gate.log.entries[0].matched_other_employee_id == colleague.id


def test_a_mismatch_without_a_matching_colleague_records_no_other_employee() -> None:
    worker = _employee()
    colleague = _employee(store_id=STORE)
    gate = _gate(
        employee=worker,
        candidate=STRANGER,
        profiles=[_profile(worker), _profile(colleague, embedding=CLOSE_MATCH)],
    )

    decision = gate.verify(worker)

    assert decision.matched_other_employee_id is None


# --------------------------------------------------------------------------- #
# 2. NO_FACE_DETECTED — HEÇ BİR SAYĞACA DÜŞMÜR (bənd 3)
# --------------------------------------------------------------------------- #


def test_no_face_detected_never_touches_the_pin_lockout_counter() -> None:
    """PIN sayğacı ilə üz sayğacı TAM AYRIDIR.

    Bunları birləşdirsəydik, işıqsız dəhlizdə duran vicdanlı işçi üç
    cəhddən sonra kilidlənərdi — sistem "təhlükəsiz" görünüb faktiki olaraq
    işi dayandırardı.
    """
    worker = _employee()
    gate = _gate(employee=worker, candidate=None)

    decision = gate.verify(worker)

    assert decision.result is FaceVerificationResult.NO_FACE_DETECTED
    assert decision.outcome is FaceGateOutcome.RETRY
    assert not decision.allows_operation
    # NƏ PIN sayğacı, NƏ üz sayğacı artmır.
    assert worker.pin_security.failed_attempts == 0
    assert worker.pin_security.locked_until is None
    assert gate.profiles.items[worker.id].mismatch_attempts == 0
    assert gate.notifier.categories() == []


def test_no_face_detected_is_logged_without_a_confidence_score() -> None:
    """Müqayisə aparılmayıbsa bal da yoxdur (`chk_face_log_no_face_has_no_score`).

    `0.00` yazmaq daha sadə olardı və "tamamilə fərqli üz" mənasına gələrdi —
    yəni hesabatda MISMATCH kimi oxunardı.
    """
    worker = _employee()
    gate = _gate(employee=worker, candidate=None)

    gate.verify(worker)

    assert gate.log.results() == ["NO_FACE_DETECTED"]
    assert gate.log.entries[0].confidence_score is None


def test_a_failed_liveness_check_is_a_retry_not_a_fraud_strike() -> None:
    """Canlılıq uğursuzluğu MISMATCH sayğacına DÜŞMÜR — lakin əməliyyat da KEÇMİR.

    Şəkil göstərən adam sonsuz cəhd edib heç nə əldə etmir (fail-closed),
    vicdanlı işçi isə zəif kamerada göz qırpması tutulmadığı üçün
    KİLİDLƏNMİR. İkisi eyni bucaqda: qoruma öz istifadəçisini cəzalandırmır.
    """
    worker = _employee()
    gate = _gate(employee=worker, candidate=CLOSE_MATCH, liveness_confirmed=False)

    decision = gate.verify(worker)

    assert decision.outcome is FaceGateOutcome.RETRY
    assert not decision.allows_operation
    assert gate.profiles.items[worker.id].mismatch_attempts == 0


def test_an_empty_capture_is_treated_as_no_face_not_as_a_camera_fault() -> None:
    """İşçi hərəkəti etmədi ≠ kamera xarabdır.

    Birincisi yenidən cəhddir, ikincisi eskalasiya. Onları eyni cavaba
    yığsaydıq, hər uğursuz cəhd HR-in manual təsdiq növbəsinə düşərdi.
    """
    worker = _employee()
    gate = _gate(employee=worker)
    gate.camera.frames = []

    decision = gate.verify(worker)

    assert decision.outcome is FaceGateOutcome.RETRY
    assert ESCALATION_CATEGORY not in gate.notifier.categories()


# --------------------------------------------------------------------------- #
# 3. LOCKOUT — MÖVCUD MEXANİZM ÇAĞIRILIR (bənd 4)
# --------------------------------------------------------------------------- #


def test_the_mismatch_counter_triggers_the_existing_lockout_at_the_root_threshold() -> None:
    """Hədd `FACE_MISMATCH_LOCKOUT_THRESHOLD`-dan, müddət `PIN_LOCKOUT_MINUTES`-dən.

    Yeni kilid mexanizmi YAZILMIR: `evaluate_pin_attempt` — PIN axınının
    işlətdiyi EYNİ saf funksiya — üz sayğacı və üz həddi ilə çağırılır.
    """
    worker = _employee()
    threshold = int(DEFAULT_LIMITS[SystemLimitKey.FACE_MISMATCH_LOCKOUT_THRESHOLD])
    lockout_minutes = int(DEFAULT_LIMITS[SystemLimitKey.PIN_LOCKOUT_MINUTES])
    gate = _gate(
        employee=worker,
        candidate=STRANGER,
        profile=_profile(worker, mismatch_attempts=threshold - 1),
    )

    decision = gate.verify(worker)

    assert decision.outcome is FaceGateOutcome.LOCKED
    assert decision.lockout_triggered
    assert decision.locked_until == NOW + timedelta(minutes=lockout_minutes)
    assert gate.profiles.items[worker.id].locked_until == decision.locked_until
    assert gate.log.entries[0].lockout_triggered is True


def test_a_locked_face_raises_the_existing_account_locked_error() -> None:
    """Kilid üçün YENİ istisna sinfi yaradılmır — mövcud `AccountLockedError`.

    Kiosk ekranı onu artıq tanıyır və mesajı Azərbaycancadır; ikinci sinif
    eyni vəziyyət üçün iki fərqli mətn deməkdir.
    """
    worker = _employee()
    gate = _gate(
        employee=worker,
        profile=_profile(worker, mismatch_attempts=3, locked_until=NOW + timedelta(minutes=5)),
    )

    with pytest.raises(AccountLockedError):
        gate.verify(worker)

    # Kilidli hesabda kamera BELƏ AÇILMIR — cəhd ümumiyyətlə başlamır.
    assert gate.camera.captures == []


def test_the_lockout_threshold_is_read_from_root_not_hardcoded() -> None:
    """Root həddi 1-ə salsa, İLK uyğunsuzluq kilidləməlidir."""
    worker = _employee()
    gate = _gate(
        employee=worker,
        candidate=STRANGER,
        limits={SystemLimitKey.FACE_MISMATCH_LOCKOUT_THRESHOLD.value: "1"},
    )

    decision = gate.verify(worker)

    assert decision.lockout_triggered


def test_a_successful_verification_resets_the_mismatch_counter() -> None:
    """Uğurlu doğrulama sayğacı sıfırlayır — mövcud PIN naxışının eynisi."""
    worker = _employee()
    gate = _gate(employee=worker, profile=_profile(worker, mismatch_attempts=2))

    decision = gate.verify(worker)

    assert decision.outcome is FaceGateOutcome.ALLOWED
    assert gate.profiles.items[worker.id].mismatch_attempts == 0


# --------------------------------------------------------------------------- #
# 4. KAMERA NASAZLIĞI — SƏSSİZ PIN-ONLY YOX (bənd 5)
# --------------------------------------------------------------------------- #


def test_a_camera_fault_escalates_instead_of_silently_falling_back_to_pin_only() -> None:
    """Bənd 5-in bütün mənası: nasazlıq İNSAN QƏRARINA yönləndirilir.

    `allows_operation` `False` olmalıdır — `True` qaytarsaydı, kameranı
    söndürmək üz qatını söndürməyin ən asan yoluna çevrilərdi.
    """
    worker = _employee()
    gate = _gate(employee=worker, camera_available=False)

    decision = gate.verify(worker)

    assert decision.outcome is FaceGateOutcome.MANUAL_APPROVAL_REQUIRED
    assert not decision.allows_operation
    assert ESCALATION_CATEGORY in gate.notifier.categories()
    assert CAMERA_HEALTH_CATEGORY in gate.notifier.categories()
    assert "FACE_VERIFICATION_ESCALATED" in gate.audit.actions()


def test_the_escalation_uses_the_existing_timeout_channel() -> None:
    """Kanal MÖVCUD `escalate_timeouts` mexanizminin kanalıdır.

    Mənbə mətnini oxuyuruq: sabit dəyişsə (və ya `leave_verification` başqa
    kateqoriyaya keçsə) iki siyahı SÜKUTLA ayrılardı — HR-in manual təsdiq
    qutusu isə eyni qalardı və nasazlıqlar ora düşməzdi.
    """
    source = (USE_CASES_DIR / "leave_verification.py").read_text(encoding="utf-8")
    assert f'category="{ESCALATION_CATEGORY}"' in source
    assert f'category="{DUAL_CONTROL_CATEGORY}"' in source


def test_a_missing_enrollment_also_escalates_instead_of_passing_silently() -> None:
    """Qeydiyyatsız işçi NƏ bloklanır, NƏ sükutla buraxılır.

    "Buraxaq" variantı üz qatını yan keçmək üçün qeydiyyatı ləğv etdirməyi
    kifayət edərdi; "bloklayaq" isə yeni işə götürüləni işə başlamağa
    qoymazdı. Doğru cavab bənd 5-in cavabıdır: insan qərarına yönləndir.
    """
    worker = _employee()
    gate = _gate(employee=worker, profile=_profile(worker, embedding=None))

    decision = gate.verify(worker)

    assert decision.outcome is FaceGateOutcome.MANUAL_APPROVAL_REQUIRED
    assert not decision.allows_operation
    assert ESCALATION_CATEGORY in gate.notifier.categories()
    # Kamera nasazlığı DEYİL — avadanlıq xəbərdarlığı göndərilmir.
    assert CAMERA_HEALTH_CATEGORY not in gate.notifier.categories()


# --------------------------------------------------------------------------- #
# 5. İSTİSNA — MƏCBURİ DUAL-CONTROL (bənd 14)
# --------------------------------------------------------------------------- #


def test_an_exempt_employee_falls_into_the_existing_dual_control_flow() -> None:
    """«Bir az diqqətli ol» tövsiyəsi DEYİL — MƏCBURİ ikinci təsdiq.

    `allows_operation` `False`-dur: istisna PIN-only yolu açır, kompensasiya
    isə həmin boşluğu KONKRET şəkildə əvəzləyir.
    """
    worker = _employee()
    gate = _gate(employee=worker, exemptions=[_exemption(worker)])

    decision = gate.verify(worker)

    assert decision.outcome is FaceGateOutcome.DUAL_CONTROL_REQUIRED
    assert decision.requires_dual_control
    assert not decision.allows_operation
    assert DUAL_CONTROL_CATEGORY in gate.notifier.categories()
    assert "FACE_EXEMPT_DUAL_CONTROL" in gate.audit.actions()
    # Kamera AÇILMIR: istisnalı işçidən üz tələb edilmir.
    assert gate.camera.captures == []


@pytest.mark.parametrize(
    "context",
    [FaceTriggerContext.STEP_A, FaceTriggerContext.STEP_1, FaceTriggerContext.STEP_2],
)
def test_every_single_confirmation_of_an_exempt_employee_requires_dual_control(
    context: FaceTriggerContext,
) -> None:
    """HƏR giriş/qayıdış təsdiqi — üç tətbiq nöqtəsinin hamısı."""
    worker = _employee()
    gate = _gate(employee=worker, exemptions=[_exemption(worker)])

    decision = gate.verify(worker, context)

    assert decision.requires_dual_control


def test_an_exemption_past_its_expiry_no_longer_applies_even_if_the_cron_lagged() -> None:
    """Sətir hələ `ACTIVE`-dir, lakin vaxt keçib — istisna İŞLƏMİR.

    Gecəlik iş işləməsə (terminal söndürülüb) və yalnız statusa baxsaydıq,
    üz təsdiqindən azadlıq cron-un işləməsindən asılı olardı.
    """
    worker = _employee()
    stale = _exemption(
        worker, granted_at=NOW - timedelta(days=40), expires_at=NOW - timedelta(days=1)
    )
    gate = _gate(employee=worker, exemptions=[stale])

    decision = gate.verify(worker)

    assert decision.outcome is FaceGateOutcome.ALLOWED
    assert not decision.requires_dual_control


# --------------------------------------------------------------------------- #
# 6. İSTİSNANIN İDARƏSİ — SƏLAHİYYƏT, TAVAN, MÜDDƏT-BİTMƏ (bənd 14)
# --------------------------------------------------------------------------- #


def _exemption_use_case(
    *, limits: dict[str, str] | None = None, exemptions: list[FaceExemption] | None = None
) -> tuple[FaceControlExemptionUseCase, InMemoryFaceExemptions, RecordingAudit, RecordingNotifier]:
    repository = InMemoryFaceExemptions(exemptions or [])
    audit = RecordingAudit()
    notifier = RecordingNotifier()
    use_case = FaceControlExemptionUseCase(
        exemptions=repository,
        limits=FakeSystemLimits(limits),
        audit=audit,
        clock=FakeClock(NOW),
        notifier=notifier,
    )
    return use_case, repository, audit, notifier


def test_can_manage_employees_is_not_enough_to_grant_an_exemption() -> None:
    """Bənd 14 — adi HR səlahiyyəti KİFAYƏT ETMİR.

    `can_manage_employees`-in `hardlock_level`-i 0-dır, yəni Root onu
    istənilən HR-səviyyəli admin-ə həvalə edə bilər. İstisna isə üz qatını
    söndürür — özü bir aldatma yoluna çevrilə bilər.
    """
    actor = _employee(flags=(ENROLLMENT_FLAG,))
    use_case, _repo, _audit, _notifier = _exemption_use_case()

    with pytest.raises(FaceControlPermissionError, match=MANAGE_EXEMPTIONS_FLAG):
        use_case.grant(
            tenant_id=TENANT,
            actor=actor,
            employee_id=EmployeeId(uuid.uuid4()),
            reason="Tibbi səbəb — üz nahiyəsində sarğı",
            expires_at=NOW + timedelta(days=10),
        )


def test_the_root_flag_holder_can_grant_an_exemption_with_audit_and_notice() -> None:
    root = _employee(flags=(MANAGE_EXEMPTIONS_FLAG,), code="ROOT", priority=RolePriority.ROOT)
    use_case, repository, audit, notifier = _exemption_use_case()
    worker = EmployeeId(uuid.uuid4())

    exemption = use_case.grant(
        tenant_id=TENANT,
        actor=root,
        employee_id=worker,
        reason="Tibbi arayış — üz nahiyəsində sarğı var",
        expires_at=NOW + timedelta(days=30),
    )

    assert exemption.status is FaceExemptionStatus.ACTIVE
    assert repository.active_for(worker, now=NOW) is not None
    assert "FACE_EXEMPTION_GRANTED" in audit.actions()
    assert "FACE_EXEMPTION_GRANTED" in notifier.categories()


def test_an_exemption_may_not_exceed_the_root_managed_ceiling() -> None:
    """`FACE_EXEMPTION_MAX_DAYS` — «müvəqqəti» istisna sükutla əbədi qalmamalıdır."""
    root = _employee(flags=(MANAGE_EXEMPTIONS_FLAG,), code="ROOT", priority=RolePriority.ROOT)
    max_days = int(DEFAULT_LIMITS[SystemLimitKey.FACE_EXEMPTION_MAX_DAYS])
    use_case, _repo, _audit, _notifier = _exemption_use_case()

    with pytest.raises(FaceControlError, match=str(max_days)):
        use_case.grant(
            tenant_id=TENANT,
            actor=root,
            employee_id=EmployeeId(uuid.uuid4()),
            reason="Uzunmüddətli tibbi hal",
            expires_at=NOW + timedelta(days=max_days + 1),
        )


def test_the_exemption_ceiling_follows_the_root_value() -> None:
    """Root tavanı 5 günə salsa, 10 günlük istisna RƏDD edilir."""
    root = _employee(flags=(MANAGE_EXEMPTIONS_FLAG,), code="ROOT", priority=RolePriority.ROOT)
    use_case, _repo, _audit, _notifier = _exemption_use_case(
        limits={SystemLimitKey.FACE_EXEMPTION_MAX_DAYS.value: "5"}
    )

    with pytest.raises(FaceControlError, match="5 günü"):
        use_case.grant(
            tenant_id=TENANT,
            actor=root,
            employee_id=EmployeeId(uuid.uuid4()),
            reason="Tibbi arayış — üz nahiyəsində sarğı",
            expires_at=NOW + timedelta(days=10),
        )


def test_an_exemption_requires_a_documented_reason() -> None:
    """«ok» kimi cavab sənəd sayılmır (`reason` CHECK-inin güzgüsü)."""
    root = _employee(flags=(MANAGE_EXEMPTIONS_FLAG,), code="ROOT", priority=RolePriority.ROOT)
    use_case, _repo, _audit, _notifier = _exemption_use_case()

    with pytest.raises(FaceControlError, match="simvol"):
        use_case.grant(
            tenant_id=TENANT,
            actor=root,
            employee_id=EmployeeId(uuid.uuid4()),
            reason="ok",
            expires_at=NOW + timedelta(days=5),
        )


def test_a_second_active_exemption_is_refused() -> None:
    """`ux_face_exemption_active` qismən unikal indeksinin kod tərəfi."""
    root = _employee(flags=(MANAGE_EXEMPTIONS_FLAG,), code="ROOT", priority=RolePriority.ROOT)
    worker = _employee()
    use_case, _repo, _audit, _notifier = _exemption_use_case(exemptions=[_exemption(worker)])

    with pytest.raises(FaceControlError, match="aktiv"):
        use_case.grant(
            tenant_id=TENANT,
            actor=root,
            employee_id=worker.id,
            reason="İkinci istisna cəhdi — tibbi",
            expires_at=NOW + timedelta(days=5),
        )


def test_an_expired_exemption_is_closed_automatically_by_the_nightly_job() -> None:
    """Bənd 14 — müddət bitdikdə istisna AVTOMATİK ləğv olunur.

    Aktor YOXDUR (`actor_id is None`): bu, planlaşdırılmış sistem işidir və
    ona süni "istifadəçi" uydurmaq audit izini yalanlaşdırardı.
    """
    worker = _employee()
    stale = _exemption(
        worker, granted_at=NOW - timedelta(days=40), expires_at=NOW - timedelta(days=1)
    )
    use_case, repository, audit, notifier = _exemption_use_case(exemptions=[stale])

    closed = use_case.expire_due(tenant_id=TENANT, now=NOW)

    assert closed == 1
    assert repository.items[stale.exemption_id].status is FaceExemptionStatus.EXPIRED
    assert "FACE_EXEMPTION_EXPIRED" in audit.actions()
    assert audit.entries[-1]["actor_id"] is None
    assert "FACE_EXEMPTION_EXPIRED" in notifier.categories()


def test_the_expiry_job_is_idempotent() -> None:
    """Planlayıcı at-least-once icra edir — ikinci icra heç nə etməməlidir."""
    worker = _employee()
    stale = _exemption(
        worker, granted_at=NOW - timedelta(days=40), expires_at=NOW - timedelta(days=1)
    )
    use_case, _repo, _audit, _notifier = _exemption_use_case(exemptions=[stale])

    assert use_case.expire_due(tenant_id=TENANT, now=NOW) == 1
    assert use_case.expire_due(tenant_id=TENANT, now=NOW) == 0


def test_a_revocation_records_who_and_why() -> None:
    """`REVOKED` İNSAN QƏRARIDIR — sahibi və səbəbi olmadan status dəyişmir."""
    root = _employee(flags=(MANAGE_EXEMPTIONS_FLAG,), code="ROOT", priority=RolePriority.ROOT)
    worker = _employee()
    existing = _exemption(worker)
    use_case, repository, audit, _notifier = _exemption_use_case(exemptions=[existing])

    revoked = use_case.revoke(
        tenant_id=TENANT,
        actor=root,
        exemption_id=existing.exemption_id,
        reason="Sarğı çıxarıldı, ehtiyac qalmadı",
    )

    assert revoked.status is FaceExemptionStatus.REVOKED
    assert revoked.revoked_by == root.id
    assert revoked.revoked_at == NOW
    assert repository.active_for(worker.id, now=NOW) is None
    assert "FACE_EXEMPTION_REVOKED" in audit.actions()


def test_an_extension_is_measured_from_the_original_grant_not_from_today() -> None:
    """Tavan TƏYİNAT anından ölçülür — əks halda istisna sonsuz uzanardı."""
    root = _employee(flags=(MANAGE_EXEMPTIONS_FLAG,), code="ROOT", priority=RolePriority.ROOT)
    worker = _employee()
    max_days = int(DEFAULT_LIMITS[SystemLimitKey.FACE_EXEMPTION_MAX_DAYS])
    existing = _exemption(
        worker,
        granted_at=NOW - timedelta(days=max_days - 5),
        expires_at=NOW + timedelta(days=5),
    )
    use_case, _repo, _audit, _notifier = _exemption_use_case(exemptions=[existing])

    with pytest.raises(FaceControlError, match=str(max_days)):
        use_case.extend(
            tenant_id=TENANT,
            actor=root,
            exemption_id=existing.exemption_id,
            new_expiry=NOW + timedelta(days=20),
        )


def test_listing_active_exemptions_requires_the_same_root_flag() -> None:
    """Siyahı «kim üz təsdiqindən azaddır» sualının cavabıdır — oxu da qorunur."""
    actor = _employee(flags=(ENROLLMENT_FLAG,))
    use_case, _repo, _audit, _notifier = _exemption_use_case()

    with pytest.raises(FaceControlPermissionError):
        use_case.list_active(tenant_id=TENANT, actor=actor)


# --------------------------------------------------------------------------- #
# 7. AŞAĞI-ETİBAR ZOLAĞI VƏ TƏRS KONFİQURASİYA (bənd 12)
# --------------------------------------------------------------------------- #


def test_a_borderline_score_passes_but_is_flagged_as_low_confidence() -> None:
    """Bənd 12 — nəticə BİNAR DEYİL: əməliyyat keçir, qeyd nişanlanır."""
    worker = _employee()
    gate = _gate(employee=worker, candidate=BORDERLINE)

    decision = gate.verify(worker)

    assert decision.outcome is FaceGateOutcome.ALLOWED_LOW_CONFIDENCE
    assert decision.allows_operation
    assert decision.is_low_confidence
    assert gate.log.entries[0].is_low_confidence is True
    assert gate.log.entries[0].result is FaceVerificationResult.SUCCESS


def test_a_clean_score_is_not_flagged() -> None:
    worker = _employee()
    gate = _gate(employee=worker, candidate=CLOSE_MATCH)

    decision = gate.verify(worker)

    assert decision.outcome is FaceGateOutcome.ALLOWED
    assert not decision.is_low_confidence


def test_an_inverted_threshold_pair_fails_closed_and_disables_the_band() -> None:
    """İKİ SƏTİRLİK İNVARİANT — DB `CHECK`-i ilə ifadə edilə bilmir.

    Root aşağı-etibar həddini bənzərlik həddindən BÖYÜK yazsa, zolaq tərsinə
    dönər və qəbul sərhədi genişlənərdi — üstəlik bu, ekranda "sərtləşdirdim"
    təəssüratı ilə edilərdi. Fail-closed cavab: zolaq söndürülür, qəbul
    sərhədi İKİSİNDƏN SƏRTİNƏ enir.
    """
    worker = _employee()
    gate = _gate(
        employee=worker,
        candidate=BORDERLINE,
        limits={
            SystemLimitKey.FACE_MATCH_TOLERANCE.value: "0.60",
            SystemLimitKey.FACE_LOW_CONFIDENCE_TOLERANCE.value: "0.90",
        },
    )

    decision = gate.verify(worker)

    assert decision.tolerance_inverted
    # Zolaq SÖNDÜ: 0.55 hələ də qəbul edilir (0.60-dan kiçikdir), lakin
    # «aşağı-etibarlı» nişanı YOXDUR — çünki zolaq mövcud deyil.
    assert decision.outcome is FaceGateOutcome.ALLOWED
    assert not decision.is_low_confidence


def test_an_inverted_pair_never_widens_the_acceptance_boundary() -> None:
    """Tərs cütdə 0.90-a qədər olan məsafə QƏBUL EDİLMİR.

    Bu, fail-closed-un ölçülə bilən tərəfidir: yanlış konfiqurasiya sistemi
    heç vaxt ZƏİFLƏTMİR, ən pis halda sərtləşdirir.
    """
    worker = _employee()
    gate = _gate(
        employee=worker,
        candidate=FaceEmbedding(values=(0.75,)),
        limits={
            SystemLimitKey.FACE_MATCH_TOLERANCE.value: "0.60",
            SystemLimitKey.FACE_LOW_CONFIDENCE_TOLERANCE.value: "0.90",
        },
    )

    decision = gate.verify(worker)

    assert decision.result is FaceVerificationResult.MISMATCH


def test_a_zero_width_band_is_reported_as_disabled() -> None:
    """İki hədd bərabərdirsə «aşağı-etibarlı» nəticə RİYAZİ olaraq mümkün deyil."""
    band = FaceToleranceBand.resolve(match_tolerance=0.6, low_confidence_tolerance=0.6)

    assert not band.band_enabled
    assert band.classify(0.6) == (FaceVerificationResult.SUCCESS, False)


def test_the_confidence_percent_is_a_human_projection_not_a_decision_input() -> None:
    """Faiz 0–100 aralığında qalır (`confidence_score` sütununun `CHECK`-i)."""
    assert FaceToleranceBand.confidence_percent(0.0) == 100.0
    assert FaceToleranceBand.confidence_percent(1.5) == 0.0
    assert FaceToleranceBand.confidence_percent(0.4) == pytest.approx(60.0)


# --------------------------------------------------------------------------- #
# 8. MAĞAZA ƏHATƏSİ VƏ MODUL QAPISI (bənd 15)
# --------------------------------------------------------------------------- #


def test_an_empty_store_scope_means_global_behaviour() -> None:
    """Boş siyahı = indiki davranış DƏYİŞMİR (bənd 15 defoltu)."""
    worker = _employee()
    gate = _gate(employee=worker)

    assert gate.verify(worker).outcome is FaceGateOutcome.ALLOWED


def test_a_store_outside_the_pilot_scope_is_not_checked() -> None:
    """Pilot-mərhələli yayım: yalnız seçilmiş mağazalarda aktivdir."""
    worker = _employee(store_id=OTHER_STORE)
    gate = _gate(employee=worker, scope={STORE})

    decision = gate.verify(worker)

    assert decision.outcome is FaceGateOutcome.NOT_APPLICABLE
    # Bu, "sükutla PIN-only" DEYİL: Root-un AÇIQ qərarıdır, ona görə axın
    # davam edir və jurnal sətri yazılmır (müqayisə aparılmayıb).
    assert decision.allows_operation
    assert gate.log.entries == []


def test_the_module_toggle_gate_reuses_the_existing_camera_verification_key() -> None:
    """YENİ `FeatureModule` açarı YARADILMIR (migrations/047 qərarı).

    Sətri olmayan modul açarı üçün `is_enabled()` `True` qaytarır və ROOT
    ekranında GÖRÜNMÜR — yəni yeni açar "parametr adı daşıyan hardcode dəyər"
    olardı. Üz təsdiqi onsuz da `CAMERA_VERIFICATION` axınlarının içindədir.
    """
    worker = _employee()
    gate = _gate(employee=worker, disabled_modules={FeatureModule.CAMERA_VERIFICATION.value})

    assert gate.verify(worker).outcome is FaceGateOutcome.NOT_APPLICABLE
    assert not any(key.value.startswith("FACE_CONTROL") for key in SystemLimitKey)


# --------------------------------------------------------------------------- #
# 9. QEYDİYYAT — NƏZARƏTLİ PROSES (bənd 1, 10, 11)
# --------------------------------------------------------------------------- #


def _enrollment(
    *,
    samples: list[FaceSample],
    profiles: list[FaceProfile],
    limits: dict[str, str] | None = None,
    camera_available: bool = True,
) -> tuple[FaceEnrollmentUseCase, InMemoryFaceProfiles, FakeCamera, RecordingAudit]:
    clock = FakeClock(NOW)
    repository = InMemoryFaceProfiles(profiles)
    camera = FakeCamera(available=camera_available)
    audit = RecordingAudit()
    use_case = FaceEnrollmentUseCase(
        profiles=repository,
        camera=camera,
        matcher=FakeFaceMatcher(samples, clock=clock),
        limits=FakeSystemLimits(limits),
        audit=audit,
        clock=clock,
    )
    return use_case, repository, camera, audit


def test_an_employee_cannot_enroll_their_own_face() -> None:
    """Bənd 1 — NƏZARƏTLİ proses, self-service DEYİL.

    Yalnız flag yoxlansaydı, `can_manage_employees` sahibi olan admin öz
    kioskunda tək qalıb istənilən üzü öz hesabına bağlaya bilərdi.
    """
    admin = _employee(flags=(ENROLLMENT_FLAG,))
    use_case, _repo, _camera, _audit = _enrollment(
        samples=[FaceSample(embedding=REFERENCE, quality=0.9)], profiles=[_profile(admin)]
    )

    with pytest.raises(FaceControlPermissionError, match="özü apara bilməz"):
        use_case.enroll(tenant_id=TENANT, actor=admin, subject_id=admin.id)


def test_enrollment_requires_the_manage_employees_flag() -> None:
    actor = _employee()
    worker = _employee()
    use_case, _repo, _camera, _audit = _enrollment(
        samples=[FaceSample(embedding=REFERENCE, quality=0.9)],
        profiles=[_profile(worker, embedding=None)],
    )

    with pytest.raises(FaceControlPermissionError, match=ENROLLMENT_FLAG):
        use_case.enroll(tenant_id=TENANT, actor=actor, subject_id=worker.id)


def test_enrollment_captures_the_root_managed_number_of_frames() -> None:
    """Bənd 11 — kadr sayı `FACE_ENROLLMENT_FRAME_COUNT`-dandır, sabit deyil."""
    admin = _employee(flags=(ENROLLMENT_FLAG,))
    worker = _employee()
    use_case, _repo, camera, _audit = _enrollment(
        samples=[FaceSample(embedding=REFERENCE, quality=0.9)],
        profiles=[_profile(worker, embedding=None)],
        limits={SystemLimitKey.FACE_ENROLLMENT_FRAME_COUNT.value: "3"},
    )

    use_case.enroll(tenant_id=TENANT, actor=admin, subject_id=worker.id)

    assert camera.captures[0][0] == 3


def test_the_stored_reference_is_the_mathematical_average_of_the_accepted_frames() -> None:
    """Bənd 11 — TƏK kadr deyil, ORTA vektor saxlanılır.

    Tək kadrın embedding-i istinad olsaydı, həmin anın təsadüfi işıq/açı
    xətası ƏBƏDİ istinad nöqtəsinə çevrilərdi.
    """
    admin = _employee(flags=(ENROLLMENT_FLAG,))
    worker = _employee()
    use_case, repository, _camera, _audit = _enrollment(
        samples=[
            FaceSample(embedding=FaceEmbedding(values=(0.0,)), quality=0.9),
            FaceSample(embedding=FaceEmbedding(values=(1.0,)), quality=0.9),
        ],
        profiles=[_profile(worker, embedding=None)],
        limits={SystemLimitKey.FACE_ENROLLMENT_FRAME_COUNT.value: "2"},
    )

    result = use_case.enroll(tenant_id=TENANT, actor=admin, subject_id=worker.id)

    assert result.accepted
    stored = repository.items[worker.id].embedding
    assert stored is not None
    assert stored.values == pytest.approx((0.5,))


def test_frames_below_the_quality_threshold_are_rejected_with_a_retake_message() -> None:
    """Bənd 1 — «[Yenidən Çək]» təklifi keyfiyyət həddindən doğur."""
    admin = _employee(flags=(ENROLLMENT_FLAG,))
    worker = _employee()
    use_case, repository, _camera, _audit = _enrollment(
        samples=[FaceSample(embedding=REFERENCE, quality=0.2)],
        profiles=[_profile(worker, embedding=None)],
        limits={SystemLimitKey.FACE_ENROLLMENT_FRAME_COUNT.value: "2"},
    )

    result = use_case.enroll(tenant_id=TENANT, actor=admin, subject_id=worker.id)

    assert not result.accepted
    assert result.retake_required
    assert "Yenidən Çək" in result.message_az
    assert result.accepted_frame_count == 0
    # Qeydiyyat YAZILMIR: yarımçıq vektor saxlamaqdansa heç nə saxlamamaq.
    assert repository.items[worker.id].embedding is None


def test_the_quality_threshold_is_read_from_root() -> None:
    """Root həddi aşağı salsa, EYNİ kadr QƏBUL edilir."""
    admin = _employee(flags=(ENROLLMENT_FLAG,))
    worker = _employee()
    use_case, _repo, _camera, _audit = _enrollment(
        samples=[FaceSample(embedding=REFERENCE, quality=0.2)],
        profiles=[_profile(worker, embedding=None)],
        limits={
            SystemLimitKey.FACE_ENROLLMENT_MIN_QUALITY.value: "0.10",
            SystemLimitKey.FACE_ENROLLMENT_FRAME_COUNT.value: "1",
        },
    )

    assert use_case.enroll(tenant_id=TENANT, actor=admin, subject_id=worker.id).accepted


def test_enrollment_refuses_to_overwrite_an_existing_registration() -> None:
    """Arxivsiz üstündən yazma bənd 2-nin qadağasıdır."""
    admin = _employee(flags=(ENROLLMENT_FLAG,))
    worker = _employee()
    use_case, _repo, _camera, _audit = _enrollment(
        samples=[FaceSample(embedding=REFERENCE, quality=0.9)], profiles=[_profile(worker)]
    )

    with pytest.raises(FaceControlError, match="artıq"):
        use_case.enroll(tenant_id=TENANT, actor=admin, subject_id=worker.id)


def test_enrollment_fails_loudly_when_the_camera_is_missing() -> None:
    """Qeydiyyat adminin NƏZARƏTLİ əməliyyatıdır — orada aydın xəta doğrudur."""
    admin = _employee(flags=(ENROLLMENT_FLAG,))
    worker = _employee()
    use_case, _repo, _camera, _audit = _enrollment(
        samples=[FaceSample(embedding=REFERENCE, quality=0.9)],
        profiles=[_profile(worker, embedding=None)],
        camera_available=False,
    )

    with pytest.raises(FaceCameraUnavailableError):
        use_case.enroll(tenant_id=TENANT, actor=admin, subject_id=worker.id)


def test_the_audit_row_of_an_enrollment_never_contains_the_vector() -> None:
    """Audit sətri İKİNCİ biometrik nüsxə olmamalıdır."""
    admin = _employee(flags=(ENROLLMENT_FLAG,))
    worker = _employee()
    use_case, _repo, _camera, audit = _enrollment(
        samples=[FaceSample(embedding=REFERENCE, quality=0.9)],
        profiles=[_profile(worker, embedding=None)],
    )

    use_case.enroll(tenant_id=TENANT, actor=admin, subject_id=worker.id)

    after = audit.entries[-1]["after_state"]
    assert "embedding" not in str(after).lower()
    assert after["frames_accepted"] >= 1


def test_re_enrollment_archives_the_previous_vector_before_writing_the_new_one() -> None:
    """Bənd 2 — köhnə vektor SİLİNMİR, `REPLACED` statusu ilə arxivlənir."""
    admin = _employee(flags=(ENROLLMENT_FLAG,))
    worker = _employee()
    clock = FakeClock(NOW)
    repository = InMemoryFaceProfiles([_profile(worker)])
    audit = RecordingAudit()
    enrollment = FaceEnrollmentUseCase(
        profiles=repository,
        camera=FakeCamera(),
        matcher=FakeFaceMatcher(
            [FaceSample(embedding=FaceEmbedding(values=(0.4,)), quality=0.9)], clock=clock
        ),
        limits=FakeSystemLimits(),
        audit=audit,
        clock=clock,
    )
    use_case = FaceReEnrollmentUseCase(
        enrollment=enrollment, profiles=repository, audit=audit, clock=clock
    )

    result = use_case.re_enroll(
        tenant_id=TENANT, actor=admin, subject_id=worker.id, reason="Eynək dəyişdi"
    )

    assert result.accepted
    assert result.archived_previous
    assert repository.archive_rows[0][1] == "REPLACED"
    assert repository.archive_rows[0][2] == REFERENCE
    assert "FACE_RE_ENROLLED" in audit.actions()


def test_re_enrollment_requires_a_reason() -> None:
    """Səbəbsiz təkrar qeydiyyat auditdə müdafiə oluna bilmir."""
    admin = _employee(flags=(ENROLLMENT_FLAG,))
    worker = _employee()
    clock = FakeClock(NOW)
    repository = InMemoryFaceProfiles([_profile(worker)])
    enrollment = FaceEnrollmentUseCase(
        profiles=repository,
        camera=FakeCamera(),
        matcher=FakeFaceMatcher([FaceSample(embedding=REFERENCE, quality=0.9)], clock=clock),
        limits=FakeSystemLimits(),
        audit=RecordingAudit(),
        clock=clock,
    )
    use_case = FaceReEnrollmentUseCase(
        enrollment=enrollment, profiles=repository, audit=RecordingAudit(), clock=clock
    )

    with pytest.raises(FaceControlError, match="səbəb"):
        use_case.re_enroll(tenant_id=TENANT, actor=admin, subject_id=worker.id, reason="   ")


# --------------------------------------------------------------------------- #
# 10. DEAKTİVASİYADA SİLİNMƏ (bənd 8)
# --------------------------------------------------------------------------- #


class _Credentials:
    """`CredentialWriter` sahtəsi — deaktivasiya yolunda çağırılmır."""

    def set_password(
        self, employee_id: EmployeeId, *, raw_password: str, must_change: bool
    ) -> None:
        raise AssertionError("deaktivasiya şifrəyə toxunmamalıdır")

    def set_pin(self, employee_id: EmployeeId, *, raw_pin: str) -> None:
        raise AssertionError("deaktivasiya PIN-ə toxunmamalıdır")

    def clear_pin_lockout(self, employee_id: EmployeeId) -> None:
        raise AssertionError("deaktivasiya kilidə toxunmamalıdır")


def test_deactivating_an_employee_purges_the_face_vector_and_leaves_a_purged_trace() -> None:
    """Bənd 8 — vektor HƏMİN ANDA silinir, İZ isə qalır.

    İki iddia birlikdə vacibdir: yalnız `employees.face_embedding`-i
    təmizləmək arxivdəki köhnə vektorları sağ saxlayardı — yəni qayda
    SÜKUTLA pozulardı.
    """
    root = _employee(flags=("can_manage_employees",), code="ROOT", priority=RolePriority.ROOT)
    worker = _employee(code="SATICI", priority=RolePriority.OPERATIONAL)
    faces = InMemoryFaceProfiles([_profile(worker)])
    faces.archive_rows.append((worker.id, "REPLACED", FaceEmbedding(values=(0.3,)), "köhnə"))
    audit = RecordingAudit()
    use_case = UserManagementUseCase(
        employees=InMemoryEmployees([root, worker]),
        credentials=_Credentials(),
        audit=audit,
        clock=FakeClock(NOW),
        face_embeddings=faces,
    )

    use_case.deactivate_employee(
        tenant_id=TENANT, actor=root, employee_id=worker.id, reason="İşdən çıxdı"
    )

    assert not worker.is_active
    assert faces.items[worker.id].embedding is None
    assert faces.items[worker.id].enrolled_at is None
    # Arxivdə vektor QALMIR, lakin sətir (iz) qalır.
    assert {row[1] for row in faces.archive_rows} == {"PURGED"}
    assert all(row[2] is None for row in faces.archive_rows)
    assert audit.entries[-1]["after_state"]["face_embedding_purged"] is True


def test_deactivation_still_works_when_face_control_is_not_installed() -> None:
    """Port qoşulmayıbsa deaktivasiya DAYANMIR, lakin audit bunu GÖSTƏRİR."""
    root = _employee(flags=("can_manage_employees",), code="ROOT", priority=RolePriority.ROOT)
    worker = _employee(code="SATICI", priority=RolePriority.OPERATIONAL)
    audit = RecordingAudit()
    use_case = UserManagementUseCase(
        employees=InMemoryEmployees([root, worker]),
        credentials=_Credentials(),
        audit=audit,
        clock=FakeClock(NOW),
    )

    use_case.deactivate_employee(
        tenant_id=TENANT, actor=root, employee_id=worker.id, reason="İşdən çıxdı"
    )

    assert audit.entries[-1]["after_state"]["face_embedding_purged"] is None


# --------------------------------------------------------------------------- #
# 11. LIVENESS — SERVERDƏ VƏ TƏSADÜFİ (bənd 6)
# --------------------------------------------------------------------------- #


def test_the_liveness_gesture_comes_from_the_root_catalog() -> None:
    """Root kataloqu bir hərəkətə endirsə, YALNIZ o hərəkət tələb olunur."""
    worker = _employee()
    gate = _gate(
        employee=worker,
        limits={SystemLimitKey.FACE_LIVENESS_ACTIONS.value: "SMILE"},
    )

    decision = gate.verify(worker)

    assert decision.liveness_action is LivenessGesture.SMILE
    assert gate.camera.captures[0][1] is LivenessGesture.SMILE


def test_an_empty_liveness_catalog_falls_back_instead_of_disabling_the_check() -> None:
    """BOŞ siyahı liveness qorumasını SÜKUTLA söndürə bilməz (bənd 6).

    Söndürmək istəyən Root modulun ÖZ Feature Toggle-ını işlətməlidir — bu,
    AÇIQ qərardır və ROOT ekranında görünür.
    """
    worker = _employee()
    gate = _gate(employee=worker, limits={SystemLimitKey.FACE_LIVENESS_ACTIONS.value: "   "})

    decision = gate.verify(worker)

    assert decision.liveness_action is not None
    assert decision.liveness_action in LivenessGesture.parse_catalog(
        DEFAULT_LIMITS[SystemLimitKey.FACE_LIVENESS_ACTIONS]
    )


def test_unknown_gestures_in_the_catalog_are_ignored_not_fatal() -> None:
    """Root-un yazı səhvi bütün doğrulama qatını çökdürməməlidir."""
    assert LivenessGesture.parse_catalog("BLINK,GOZ_QIRP,SMILE") == (
        LivenessGesture.BLINK,
        LivenessGesture.SMILE,
    )


# --------------------------------------------------------------------------- #
# 12. PERFORMANS MONİTORİNQİ — HEÇ NƏ ZƏİFLƏTMİR (bənd 18)
# --------------------------------------------------------------------------- #


def test_a_slow_verification_raises_a_health_warning() -> None:
    """`FACE_VERIFICATION_MAX_SECONDS` aşılarsa xəbərdarlıq yazılır."""
    worker = _employee()
    gate = _gate(employee=worker, delay_seconds=9)

    decision = gate.verify(worker)

    assert decision.duration_ms >= 9000
    assert PERFORMANCE_HEALTH_CATEGORY in gate.notifier.categories()
    # ƏMƏLİYYAT BLOKLANMIR: bu, diaqnostikadır, qapı deyil.
    assert decision.allows_operation


def test_a_fast_verification_does_not_warn() -> None:
    worker = _employee()
    gate = _gate(employee=worker, delay_seconds=1)

    gate.verify(worker)

    assert PERFORMANCE_HEALTH_CATEGORY not in gate.notifier.categories()


def test_the_performance_warning_never_weakens_a_quality_parameter() -> None:
    """⚠️ BƏND 18-in KRİTİK QAYDASI — mənbə mətni ilə qorunur.

    Kod bir gün "sürətləndirmək üçün kadr sayını azaldaq" məntiqini qazana
    bilər və nəticə "sistem sürətləndi" kimi görünərdi — faktiki olaraq isə
    tanınma dəqiqliyi sükutla enərdi. Ona görə qapı davranışı deyil, KODUN
    ÖZÜNÜ yoxlayır: performans yoxlamasının metodunda heç bir hədd/kadr
    parametrinə YAZI olmamalıdır.
    """
    source = (USE_CASES_DIR / "face_control.py").read_text(encoding="utf-8")
    match = re.search(r"def _check_performance\(.*?\n    def ", source, re.DOTALL)
    assert match is not None, "`_check_performance` metodu tapılmadı"
    # DOCSTRING VƏ ŞƏRHLƏR ÇIXARILIR: onlar qadağan olunan parametrlərin ADINI
    # QƏSDƏN çəkir («burada bunlara toxunulmur»). Onları saymasaydıq, qapı
    # yaxşı sənədləşməni cəzalandırardı (`test_face_control_schema.py`-dəki
    # sətir-sabitlərinin maskalanması ilə eyni qərar).
    body = re.sub(r'""".*?"""', "", match.group(0), flags=re.DOTALL)
    body = "\n".join(line for line in body.splitlines() if not line.strip().startswith("#"))
    for forbidden in (
        "FACE_ENROLLMENT_FRAME_COUNT",
        "FACE_MATCH_TOLERANCE",
        "FACE_ENROLLMENT_MIN_QUALITY",
        "FACE_LOW_CONFIDENCE_TOLERANCE",
    ):
        assert forbidden not in body, (
            f"Performans yoxlaması `{forbidden}` parametrinə toxunur — bənd 18 "
            "bunu AÇIQ qadağan edir (təhlükəsizlik güzəşti)."
        )


# --------------------------------------------------------------------------- #
# 13. SAXLAMA MÜDDƏTİ (bənd 17)
# --------------------------------------------------------------------------- #


def _log_entry(
    *, occurred_at: datetime, result: FaceVerificationResult
) -> FaceVerificationLogEntry:
    return FaceVerificationLogEntry(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        result=result,
        trigger_context=FaceTriggerContext.STEP_A,
        occurred_at=occurred_at,
        store_id=STORE,
        confidence_score=None if result is FaceVerificationResult.NO_FACE_DETECTED else 42.0,
    )


def test_the_retention_job_deletes_only_rows_older_than_the_root_window() -> None:
    """Bənd 17 — TAM SİLMƏ (anonimləşdirmə YOX: silinəcək həssas məzmun yoxdur)."""
    repository = InMemoryFaceVerificationLog()
    months = int(DEFAULT_LIMITS[SystemLimitKey.FACE_VERIFICATION_LOG_RETENTION_MONTHS])
    cutoff = add_months(NOW, -months)
    repository.record(
        _log_entry(occurred_at=cutoff - timedelta(days=1), result=FaceVerificationResult.SUCCESS)
    )
    repository.record(
        _log_entry(occurred_at=cutoff + timedelta(days=1), result=FaceVerificationResult.MISMATCH)
    )
    audit = RecordingAudit()
    use_case = FaceVerificationLogRetentionUseCase(
        verification_log=repository,
        limits=FakeSystemLimits(),
        audit=audit,
        clock=FakeClock(NOW),
    )

    removed = use_case.purge(tenant_id=TENANT, now=NOW)

    assert removed == 1
    assert len(repository.entries) == 1
    assert "FACE_VERIFICATION_LOG_PURGED" in audit.actions()
    assert audit.entries[-1]["actor_id"] is None


def test_the_retention_window_is_wider_than_the_behaviour_baseline_window() -> None:
    """Bənd 17-nin TƏHLÜKƏSİZLİK TƏSDİQİ: silmə baz xətti hesablamasını POZMUR."""
    retention_days = int(DEFAULT_LIMITS[SystemLimitKey.FACE_VERIFICATION_LOG_RETENTION_MONTHS]) * 28
    baseline_days = int(DEFAULT_LIMITS[SystemLimitKey.BEHAVIOR_BASELINE_WINDOW_DAYS])
    assert retention_days > baseline_days


def test_an_invalid_retention_value_purges_nothing() -> None:
    """Sıfır «dərhal sil» demək olardı və auditi tamamilə yox edərdi."""
    repository = InMemoryFaceVerificationLog()
    repository.record(
        _log_entry(occurred_at=NOW - timedelta(days=900), result=FaceVerificationResult.SUCCESS)
    )
    use_case = FaceVerificationLogRetentionUseCase(
        verification_log=repository,
        limits=FakeSystemLimits({SystemLimitKey.FACE_VERIFICATION_LOG_RETENTION_MONTHS.value: "0"}),
        audit=RecordingAudit(),
        clock=FakeClock(NOW),
    )

    assert use_case.purge(tenant_id=TENANT, now=NOW) == 0
    assert len(repository.entries) == 1


# --------------------------------------------------------------------------- #
# 14. İSTİSNA MOTORUNA BAĞLANTI (bənd 16)
# --------------------------------------------------------------------------- #


def test_the_mismatch_rule_produces_a_finding_per_logged_mismatch() -> None:
    """Motorun KODU dəyişmir — bu, sadəcə bir `ExceptionRule`-dur."""
    repository = InMemoryFaceVerificationLog()
    repository.record(
        _log_entry(occurred_at=NOW - timedelta(hours=2), result=FaceVerificationResult.MISMATCH)
    )
    repository.record(
        _log_entry(occurred_at=NOW - timedelta(hours=1), result=FaceVerificationResult.SUCCESS)
    )
    rule = FaceMismatchExceptionRule(verification_log=repository)

    findings = rule.evaluate(
        RuleEvaluationContext(
            tenant_id=TENANT, as_of=NOW, limits=FakeSystemLimits().all_for(TENANT)
        )
    )

    assert rule.source_code == FACE_MISMATCH_SOURCE
    assert len(findings) == 1
    # Ciddiyyət QƏSDƏN verilmir: motor onu mənbənin `default_severity`
    # sütunundan (CRITICAL) doldurur — dəyişmək üçün buraxılış lazım deyil.
    assert findings[0].severity is None
    assert findings[0].dedupe_key is not None


def test_the_mismatch_rule_does_not_replace_the_immediate_notification() -> None:
    """Bənd 16-nın təhlükəsizlik qeydi: iki kanal PARALEL işləyir.

    Uyğunsuzluq anında təcili bildiriş gedir (yuxarıdakı qapı), istisna sətri
    isə gecəlik motorla yaranır. Birləşdirsəydik, ən güclü fırıldaqçılıq
    siqnalı bir gecəlik gecikmə qazanardı.
    """
    worker = _employee()
    gate = _gate(employee=worker, candidate=STRANGER)

    gate.verify(worker)

    rule = FaceMismatchExceptionRule(verification_log=gate.log)
    findings = rule.evaluate(RuleEvaluationContext(tenant_id=TENANT, as_of=NOW, limits={}))

    assert MISMATCH_CATEGORY in gate.notifier.categories()
    assert len(findings) == 1


# --------------------------------------------------------------------------- #
# 15. BİOMETRİK MƏLUMATIN QORUNMASI
# --------------------------------------------------------------------------- #


def test_neither_the_frame_nor_the_vector_can_leak_through_repr() -> None:
    """Log/traceback/pytest diff-i biometrik məzmunu GÖSTƏRMƏMƏLİDİR."""
    frame = FaceFrame(payload=b"\x89PNG-oxsar-baytlar", width=640, height=480)
    embedding = FaceEmbedding(values=(0.11, 0.22, 0.33))

    assert "PNG" not in repr(frame)
    assert "0.11" not in repr(embedding)
    assert "dim=3" in repr(embedding)


def test_the_domain_layer_never_imports_the_recognition_library() -> None:
    """Qat sırası: `face_recognition` YALNIZ `infrastructure/` altında ola bilər.

    Bu faza onu ÜMUMİYYƏTLƏ idxal etmir (kitabxana Faza 3-dədir), lakin qapı
    indidən qoyulur: gələcək adapter səhvən domenə sızsa, testlər dərhal
    qırılacaq.
    """
    for path in (
        PROJECT_ROOT / "src" / "domain" / "value_objects" / "face_recognition.py",
        PROJECT_ROOT / "src" / "domain" / "interfaces" / "ports.py",
        USE_CASES_DIR / "face_control.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*import face_recognition", source, re.MULTILINE)
        assert not re.search(r"^\s*from face_recognition", source, re.MULTILINE)


def test_averaging_vectors_of_different_dimensions_is_refused() -> None:
    """Ölçü uyğunsuzluğu «işləyən, lakin heç kimi tanımayan» qeydiyyat yaradardı."""
    with pytest.raises(FaceControlError):
        FaceEmbedding.average([FaceEmbedding(values=(0.1, 0.2)), FaceEmbedding(values=(0.3,))])


def test_an_empty_vector_is_refused() -> None:
    with pytest.raises(FaceControlError):
        FaceEmbedding(values=())


# --------------------------------------------------------------------------- #
# 16. KÖHNƏLMİŞ QEYDİYYAT — TÖVSİYƏ, BLOKLAMA YOX (bənd 13)
# --------------------------------------------------------------------------- #


def test_a_stale_enrollment_is_only_a_recommendation() -> None:
    """Bənd 13 — xəbərdarlıq göstərilir, iş DAVAM EDİR."""
    worker = _employee()
    months = int(DEFAULT_LIMITS[SystemLimitKey.FACE_REENROLLMENT_REMINDER_MONTHS])
    old = add_months(NOW, -months) - timedelta(days=1)
    profile = _profile(worker, enrolled_at=old)

    assert profile.is_stale(now=NOW, reminder_months=months)

    gate = _gate(employee=worker, profile=profile)
    assert gate.verify(worker).outcome is FaceGateOutcome.ALLOWED


def test_the_stale_list_uses_the_root_managed_interval() -> None:
    admin = _employee(flags=(ENROLLMENT_FLAG,))
    worker = _employee()
    use_case, _repo, _camera, _audit = _enrollment(
        samples=[FaceSample(embedding=REFERENCE, quality=0.9)],
        profiles=[_profile(worker, enrolled_at=NOW - timedelta(days=200))],
        limits={SystemLimitKey.FACE_REENROLLMENT_REMINDER_MONTHS.value: "6"},
    )
    del admin

    stale = use_case.stale_enrollments(TENANT)

    assert [profile.employee_id for profile in stale] == [worker.id]


def test_a_fresh_enrollment_is_not_stale() -> None:
    worker = _employee()
    profile = _profile(worker, enrolled_at=NOW - timedelta(days=10))

    assert not profile.is_stale(now=NOW, reminder_months=12)


def test_add_months_keeps_calendar_semantics() -> None:
    """30 günlük təxmin RƏDD EDİLDİ: 12 «ay» onda 360 gün edərdi."""
    assert add_months(datetime(2026, 1, 31, tzinfo=UTC), 1) == datetime(2026, 2, 28, tzinfo=UTC)
    assert add_months(datetime(2026, 8, 15, tzinfo=UTC), 12) == datetime(2027, 8, 15, tzinfo=UTC)
    assert add_months(datetime(2026, 1, 15, tzinfo=UTC), -1) == datetime(2025, 12, 15, tzinfo=UTC)
