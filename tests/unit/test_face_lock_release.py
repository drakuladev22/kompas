"""Üz kilidinin AÇILMA yolu (`FaceLockReleaseUseCase`) — facecontrol.md bənd 4.

──────────────────────────────────────────────────────────────────────────────
BU FAYL NİYƏ AYRIDIR (`test_face_control.py`-a əlavə edilmədi)
──────────────────────────────────────────────────────────────────────────────
`test_face_control.py` DOĞRULAMA axınını (kilidin QURULMASI) sınayır və orada
hər testin qurğusu kamera/matcher sahtələrindən keçir. Açılış isə kamerasız
əməliyyatdır — həmin qurğunu miras almaq testləri sınamadıqları bir
asılılığa bağlayardı.

──────────────────────────────────────────────────────────────────────────────
BURADA SINANAN QAYDALAR
──────────────────────────────────────────────────────────────────────────────
  1. Səlahiyyət `can_manage_face_exemptions`-dır (hardlock 2) — `can_manage_
     employees` KİFAYƏT ETMİR (bax `FaceLockReleaseUseCase` başlığı).
  2. Öz kilidini özü açmaq qadağandır (vəzifə ayrılığı).
  3. Səbəb məcburidir, audit + `security.log` + bildiriş yazılır.
  4. Sayğac sıfırlanır, LAKİN `face_verification_log` tarixçəsi TOXUNULMUR.
  5. Açılacaq heç nə yoxdursa — SÜKUT DEYİL, açıq istisna.
  6. Köhnəlmiş qeydiyyat halında yenidən-qeydiyyata YÖNLƏNDİRİLİR.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest

from src.application.use_cases.face_control import (
    FaceControlError,
    FaceControlPermissionError,
    FaceLockReleaseUseCase,
)
from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.position import Position
from src.domain.policies import SystemLimitKey
from src.domain.value_objects.authorization import PermissionEffect, RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.face_recognition import FaceEmbedding, FaceProfile
from src.domain.value_objects.identifiers import EmployeeId, StoreId, TenantId
from tests.fixtures.fakes import (
    FakeClock,
    FakeSystemLimits,
    InMemoryFaceProfiles,
    InMemoryFaceVerificationLog,
    RecordingAudit,
    RecordingNotifier,
)

pytestmark = pytest.mark.unit

NOW: Final = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
TENANT: Final = TenantId(uuid.uuid4())
STORE: Final = StoreId(uuid.uuid4())
REFERENCE: Final = FaceEmbedding(values=(0.0,))

MANAGE_EXEMPTIONS: Final = "can_manage_face_exemptions"
MANAGE_EMPLOYEES: Final = "can_manage_employees"
REASON: Final = "İşçi növbəyə çıxmalıdır, kilid səhvən qurulub"


def _employee(
    *,
    flags: tuple[str, ...] = (),
    code: str = "ROOT",
    priority: RolePriority = RolePriority.ROOT,
) -> Employee:
    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=Position(
            position_id=uuid.uuid4(),  # type: ignore[arg-type]
            code=code,
            name_az=code.title(),
            priority=priority,
            tenant_id=TENANT,
            is_system=True,
        ),
        first_name="Aygün",
        last_name="Əliyeva",
        store_id=STORE,
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


class _Harness:
    """Use case + bütün sahtələr — hər test öz nüsxəsini qurur."""

    def __init__(
        self,
        *,
        mismatch_attempts: int = 3,
        locked_until: datetime | None = NOW + timedelta(minutes=15),
        enrolled_at: datetime | None = NOW,
        limits: dict[str, str] | None = None,
    ) -> None:
        self.subject = _employee(code="SATICI", priority=RolePriority.STAFF)
        self.profile = FaceProfile(
            employee_id=self.subject.id,
            tenant_id=TENANT,
            store_id=STORE,
            embedding=REFERENCE,
            enrolled_at=enrolled_at,
            mismatch_attempts=mismatch_attempts,
            locked_until=locked_until,
        )
        self.profiles = InMemoryFaceProfiles([self.profile])
        self.verification_log = InMemoryFaceVerificationLog()
        self.clock = FakeClock(NOW)
        self.audit = RecordingAudit()
        self.notifier = RecordingNotifier()
        self.use_case = FaceLockReleaseUseCase(
            profiles=self.profiles,  # type: ignore[arg-type]
            limits=FakeSystemLimits(limits),  # type: ignore[arg-type]
            audit=self.audit,  # type: ignore[arg-type]
            clock=self.clock,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
        )

    def release(self, actor: Employee, *, reason: str = REASON) -> Any:
        return self.use_case.release(
            tenant_id=TENANT, actor=actor, subject_id=self.subject.id, reason=reason
        )

    def stored(self) -> FaceProfile:
        profile = self.profiles.get_profile(self.subject.id)
        assert profile is not None
        return profile  # type: ignore[no-any-return]


# --------------------------------------------------------------------------- #
# 1. Səlahiyyət — anti-fraud vəzifə ayrılığı
# --------------------------------------------------------------------------- #


def test_can_manage_employees_is_not_enough_to_release_a_face_lock() -> None:
    """HR-səviyyəli flag KİFAYƏT ETMİR — `can_manage_employees` hardlock 0-dır.

    Hardlock 0 və `is_anti_fraud = FALSE` olduğu üçün həmin flag fərdi
    override ilə `Mağaza_Meneceri`-yə verilə bilər; öz mağazasının işçisinin
    üz kilidini açan menecer isə anti-fraud ayrılığını mənasız edərdi.
    """
    harness = _Harness()
    actor = _employee(flags=(MANAGE_EMPLOYEES,), code="HR_ADMIN", priority=RolePriority.OPERATIONAL)

    with pytest.raises(FaceControlPermissionError, match=MANAGE_EXEMPTIONS):
        harness.release(actor)

    # Sayğac TOXUNULMADI — rədd edilən əməliyyat heç bir yan təsir buraxmır.
    assert harness.stored().mismatch_attempts == 3


def test_the_root_flag_holder_releases_the_lock_and_resets_the_counter() -> None:
    harness = _Harness()
    actor = _employee(flags=(MANAGE_EXEMPTIONS,))

    result = harness.release(actor)

    assert result.was_locked is True
    assert result.cleared_attempts == 3
    stored = harness.stored()
    assert stored.mismatch_attempts == 0
    assert stored.locked_until is None
    assert stored.is_locked(now=NOW) is False


def test_nobody_may_release_their_own_face_lock() -> None:
    """Vəzifə ayrılığı — `assert_may_enroll` ilə eyni qayda."""
    harness = _Harness()
    actor = _employee(flags=(MANAGE_EXEMPTIONS,))
    # Aktoru subyektlə EYNİ şəxs edirik.
    with pytest.raises(FaceControlPermissionError, match="Öz üz kilidinizi"):
        harness.use_case.release(tenant_id=TENANT, actor=actor, subject_id=actor.id, reason=REASON)


# --------------------------------------------------------------------------- #
# 2. Səbəb, audit və bildiriş
# --------------------------------------------------------------------------- #


def test_a_release_without_a_reason_is_rejected() -> None:
    harness = _Harness()
    actor = _employee(flags=(MANAGE_EXEMPTIONS,))

    with pytest.raises(FaceControlError, match="səbəbi boş ola bilməz"):
        harness.release(actor, reason="   ")

    assert harness.stored().mismatch_attempts == 3


def test_the_release_is_audited_with_the_reason_and_both_states() -> None:
    harness = _Harness()
    actor = _employee(flags=(MANAGE_EXEMPTIONS,))

    harness.release(actor)

    entry = next(e for e in harness.audit.entries if e["action"] == "FACE_LOCK_RELEASED")
    assert entry["actor_id"] == actor.id
    assert entry["entity_id"] == harness.subject.id
    assert entry["reason"] == REASON
    assert entry["before_state"]["face_mismatch_attempts"] == 3
    assert entry["after_state"]["face_mismatch_attempts"] == 0
    assert entry["after_state"]["face_locked_until"] is None
    # Audit oxucusu kilidin PIN SAHİBİNƏ aid olduğunu görməlidir: kilidi
    # doğuran üz başqa adamın üzü ola bilər (məhz ona görə uyğunsuzluq olub).
    assert entry["after_state"]["subject_role"] == "PIN_OWNER"


def test_the_employee_is_told_that_their_lock_was_released() -> None:
    harness = _Harness()
    actor = _employee(flags=(MANAGE_EXEMPTIONS,))

    harness.release(actor)

    message = next(m for m in harness.notifier.messages if m["category"] == "FACE_LOCK_RELEASED")
    # ŞƏXSİ sətir — auditoriya süzgəcindən asılı deyil.
    assert message["recipient_id"] == harness.subject.id
    assert message["is_critical"] is True
    assert REASON in str(message["body_az"])


# --------------------------------------------------------------------------- #
# 3. Tarixçə silinmir
# --------------------------------------------------------------------------- #


def test_the_release_never_erases_the_verification_history() -> None:
    """Təkrarlanan açılış özü anomaliya siqnalıdır — jurnal qalmalıdır.

    `FaceMismatchExceptionRule` məhz həmin jurnaldan qidalanır; açılışla
    birlikdə tarixçəni də təmizləsəydik, "bu işçinin üzü ayda beş dəfə
    tanınmır" faktı hər açılışdan sonra sıfırdan başlayardı.
    """
    harness = _Harness()
    actor = _employee(flags=(MANAGE_EXEMPTIONS,))
    before = len(harness.verification_log.entries)

    harness.release(actor)

    assert len(harness.verification_log.entries) == before


# --------------------------------------------------------------------------- #
# 4. Açılacaq heç nə yoxdursa — sükut YOX
# --------------------------------------------------------------------------- #


def test_releasing_a_lock_that_does_not_exist_raises_instead_of_silently_succeeding() -> None:
    """Sükutla uğur qaytarmaq ekranda «açıldı» yazar, problemi isə saxlayardı."""
    harness = _Harness(mismatch_attempts=0, locked_until=None)
    actor = _employee(flags=(MANAGE_EXEMPTIONS,))

    with pytest.raises(FaceControlError, match="açılacaq üz kilidi"):
        harness.release(actor)

    # Mesaj PIN kilidinin AYRI mexanizm olduğunu deyir — istifadəçi eyni
    # düyməni yenidən basmasın deyə.
    assert not harness.audit.entries


def test_an_expired_lock_with_a_pending_counter_can_still_be_cleared() -> None:
    """Kilid vaxtı bitib, sayğac isə 2/3-dədir — açılış YENƏ mənalıdır.

    Sayğac sıfırlanmasa, işçinin növbəti TƏK uyğunsuzluğu onu dərhal yenidən
    kilidləyərdi.
    """
    harness = _Harness(mismatch_attempts=2, locked_until=NOW - timedelta(minutes=1))
    actor = _employee(flags=(MANAGE_EXEMPTIONS,))

    result = harness.release(actor)

    assert result.was_locked is False
    assert result.cleared_attempts == 2
    assert harness.stored().mismatch_attempts == 0
    assert "aktiv kilid yox idi" in result.message_az


# --------------------------------------------------------------------------- #
# 5. Səbəb qeydiyyat problemidirsə — yenidən-qeydiyyata yönləndir
# --------------------------------------------------------------------------- #


def test_a_stale_enrollment_routes_the_operator_to_re_enrollment() -> None:
    """Köhnəlmiş istinad vektoru kilidi TƏKRAR-TƏKRAR qurur (bənd 13).

    Belə halda açılış yalnız simptomu götürür — mesaj MÖVCUD yenidən-qeydiyyat
    axınına yönləndirir, ikinci "düzəlt" mexanizmi yazılmır.
    """
    reminder_months = 12
    harness = _Harness(
        enrolled_at=NOW - timedelta(days=400),
        limits={SystemLimitKey.FACE_REENROLLMENT_REMINDER_MONTHS.value: str(reminder_months)},
    )
    actor = _employee(flags=(MANAGE_EXEMPTIONS,))

    result = harness.release(actor)

    assert result.re_enrollment_recommended is True
    assert "Yenidən Qeydiyyat" in result.message_az


def test_a_fresh_enrollment_does_not_suggest_re_enrollment() -> None:
    harness = _Harness(enrolled_at=NOW - timedelta(days=5))
    actor = _employee(flags=(MANAGE_EXEMPTIONS,))

    result = harness.release(actor)

    assert result.re_enrollment_recommended is False
    assert "Yenidən Qeydiyyat" not in result.message_az


def test_the_reminder_interval_comes_from_root_not_from_a_constant() -> None:
    """`FACE_REENROLLMENT_REMINDER_MONTHS` — hardcode DEYİL, ROOT parametridir."""
    limits_key = SystemLimitKey.FACE_REENROLLMENT_REMINDER_MONTHS.value
    strict = _Harness(enrolled_at=NOW - timedelta(days=40), limits={limits_key: "1"})
    lenient = _Harness(enrolled_at=NOW - timedelta(days=40), limits={limits_key: "60"})
    actor = _employee(flags=(MANAGE_EXEMPTIONS,))

    assert strict.release(actor).re_enrollment_recommended is True
    assert lenient.release(actor).re_enrollment_recommended is False


# --------------------------------------------------------------------------- #
# 6. Tanınmayan subyekt
# --------------------------------------------------------------------------- #


def test_an_unknown_employee_is_rejected_with_a_clear_message() -> None:
    harness = _Harness()
    actor = _employee(flags=(MANAGE_EXEMPTIONS,))

    with pytest.raises(FaceControlError, match="üz profili tapılmadı"):
        harness.use_case.release(
            tenant_id=TENANT,
            actor=actor,
            subject_id=EmployeeId(uuid.uuid4()),
            reason=REASON,
        )
