"""İlk girişdə üz qeydiyyatı — nəzarətli proses (facecontrol.md bənd 1).

──────────────────────────────────────────────────────────────────────────────
NİYƏ QEYDİYYAT ANINDA DEYİL, İLK GİRİŞDƏ
──────────────────────────────────────────────────────────────────────────────
Hesab çox vaxt işçi gəlməmişdən əvvəl — kadr sənədləri ilə — açılır. Üz
çəkilişi isə işçinin ÖZÜNÜN orada olmasını tələb edir. İkisini bir anda
tələb etsəydik, hesab açmaq kameranın və işçinin hazır olmasından asılı
qalardı.

İlk giriş isə məhz işçinin ÖZÜ ilə baş verir — yəni çəkiliş üçün ən təbii an.

──────────────────────────────────────────────────────────────────────────────
NİYƏ ADMİN ŞİFRƏSİ TƏLƏB OLUNUR
──────────────────────────────────────────────────────────────────────────────
`FaceEnrollmentUseCase.assert_may_enroll` iki qapı qoyur: aktorda
`can_manage_employees` olmalıdır VƏ aktor subyektin ÖZÜ olmamalıdır. İkincisi
qəsdlidir: nəzarətsiz qeydiyyatda işçi istənilən üzü öz hesabına bağlaya
bilər.

Bu kontroller həmin qapını YAN KEÇMİR — əksinə, onun tələb etdiyi aktoru
gətirir: ekranda admin öz hesabı ilə təsdiqləyir, aktor həmin admin olur.

──────────────────────────────────────────────────────────────────────────────
CEO/ROOT İSTİSNADIR
──────────────────────────────────────────────────────────────────────────────
Tenant-ın İLK hesabı (CEO) yaranan an sistemdə ondan yuxarı heç kim yoxdur —
yəni onun üzünü təsdiqləyəcək aktor mövcud deyil. Ona görə tələb `Root`/`CEO`
pilləsinə TƏTBİQ EDİLMİR; onların üzü sonradan, ikinci admin göründükdə
qeydiyyata alınır (istifadəçi qərarı, bax `docs/security_decisions.md`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.domain.value_objects.authorization import SystemRole
from src.presentation.controllers.ui_feedback import flush_ui
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.face_control import FaceSetupRequiredScreen

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)
_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Üz qeydiyyatı TƏLƏB EDİLMƏYƏN pillələr (bax modul başlığı).
EXEMPT_ROLES: frozenset[SystemRole] = frozenset({SystemRole.ROOT, SystemRole.CEO})

#: Modul açarı — söndürülübsə tələb ümumiyyətlə qoyulmur.
FACE_MODULE = "CAMERA_VERIFICATION"


def is_enrollment_required(session: Session, employee: Employee) -> bool:
    """Bu işçi ilk girişdə üz qeydiyyatına düşməlidirmi?

    ÜÇ ŞƏRT BİRLİKDƏ:
      1. modul açıqdır (`CAMERA_VERIFICATION`);
      2. işçi `Root`/`CEO` deyil (bax modul başlığı);
      3. hələ qeydiyyatı yoxdur.

    UĞURSUZLUQDA `False` QAYTARILIR: sorğu alınmasa işçini giriş ekranında
    saxlamaq — yəni işini dayandırmaq — yanlış cavabdır. Üz qatı iş dayandıran
    nasazlığa çevrilməməlidir (eyni istiqamət `_enabled_modules`-da seçilib).
    """
    if employee.position.effective_system_role in EXEMPT_ROLES:
        return False
    try:
        if not session.toggles.is_enabled(session.tenant_id, FACE_MODULE):
            return False
        profile = session.uow.repository("face_embeddings").get_profile(employee.id)
    except Exception:
        _error_log.exception("FACE_SETUP_CHECK_FAILED")
        return False
    return profile is None or not profile.is_enrolled


class FaceSetupController:
    """«Üz qeydiyyatı tələb olunur» ekranını use case-lərə bağlayır.

    İKİ REJİM, İKİ FƏRQLİ USE CASE METODU:

        nəzarətli (defolt) — `enroll()`   : aktor YANINDAKI admindir
        bootstrap         — `enroll_first_account()` : aktor istifadəçinin ÖZÜ

    Bootstrap yalnız İlk Quraşdırma Sihirbazında işlədilir və şərti use
    case-də maşınla yoxlanılır (tenant-da yeganə admin) — kontroller onu
    «seçmir», sadəcə hansı metodun çağırıldığını bilir.
    """

    def __init__(
        self,
        context: ApplicationContext,
        subject: Employee,
        *,
        authenticate: object = None,
        bootstrap: bool = False,
    ) -> None:
        self._context = context
        self._subject = subject
        self._bootstrap = bootstrap
        # Admin girişi MÖVCUD yoldan keçir (`controllers/auth.py`): burada
        # ikinci autentifikasiya məntiqi YAZILMIR — şifrə yoxlaması, lockout
        # sayğacı və audit onsuz da orada var və təkrarı sükutla fərqlənərdi.
        self._authenticate = authenticate

    def attach(self, screen: FaceSetupRequiredScreen) -> None:
        screen.set_employee_name(self._subject.full_name)
        screen.enroll_requested.connect(
            lambda username, password: self._on_enroll(screen, username, password)
        )

    # ------------------------------ qeydiyyat -------------------------------- #

    def _on_enroll(self, screen: FaceSetupRequiredScreen, username: str, password: str) -> None:
        if self._bootstrap:
            self._enroll_bootstrap(screen)
            return

        if self._authenticate is None:  # pragma: no cover - kompozisiya qoruyucusu
            screen.set_error("Təsdiq yolu qoşulmayıb.")
            return
        outcome = self._authenticate(username, password)  # type: ignore[operator]
        admin = getattr(outcome, "employee", None)
        if admin is None:
            screen.set_error("Admin girişi uğursuz oldu — istifadəçi adı və ya şifrə yanlışdır.")
            return

        if admin.id == self._subject.id:
            # Qapı use case-də DƏ var; burada mesaj İSTİFADƏÇİ DİLİNDƏ verilir.
            _security_log.warning(
                "FACE_SELF_ENROLLMENT_ATTEMPT", extra={"employee_id": str(self._subject.id)}
            )
            screen.set_error(
                "Öz üzünüzü özünüz qeydiyyata sala bilməzsiniz — başqa bir "
                "adminin təsdiqi lazımdır."
            )
            return

        screen.set_busy(True)
        # Üz emalı bir neçə saniyə çəkir — «gözləyin» vəziyyəti
        # bloklamadan ƏVVƏL görünməlidir (UX-1).
        flush_ui()
        try:
            with self._context.session(user_id=admin.id) as session:
                session.face_enrollment.enroll(
                    tenant_id=session.tenant_id,
                    actor=admin,
                    subject_id=self._subject.id,
                )
                session.commit()
        except KompasOSError as error:
            screen.set_error(error.user_message)
            return
        except Exception:
            _error_log.exception("FACE_SETUP_ENROLL_FAILED")
            screen.set_error("Üz qeydiyyatı alınmadı. Kameranı yoxlayıb yenidən cəhd edin.")
            return
        finally:
            screen.set_busy(False)

        _log.info(
            "FACE_SETUP_COMPLETED",
            extra={"employee_id": str(self._subject.id), "actor_id": str(admin.id)},
        )
        screen.skipped.emit()  # ekranı bağlayan yol EYNİDİR — davam et

    def _enroll_bootstrap(self, screen: FaceSetupRequiredScreen) -> None:
        """SEC-025 — tenant-ın yeganə admini öz üzünü qeydiyyata salır.

        Şərt BURADA yoxlanılmır: `enroll_first_account()` tenant-da admin
        sayını özü sayır və birdən çox olduqda rədd edir. Yoxlamanı kontrollerə
        köçürsəydik, ekranı yan keçən hər yol onu itirərdi.
        """
        screen.set_busy(True)
        # Üz emalı bir neçə saniyə çəkir — «gözləyin» vəziyyəti
        # bloklamadan ƏVVƏL görünməlidir (UX-1).
        flush_ui()
        try:
            with self._context.session(user_id=self._subject.id) as session:
                session.face_enrollment.enroll_first_account(
                    tenant_id=session.tenant_id,
                    actor=self._subject,
                    subject_id=self._subject.id,
                )
                session.commit()
        except KompasOSError as error:
            screen.set_error(error.user_message)
            return
        except Exception:
            _error_log.exception("FACE_BOOTSTRAP_ENROLL_FAILED")
            screen.set_error("Üz qeydiyyatı alınmadı. Kameranı yoxlayıb yenidən cəhd edin.")
            return
        finally:
            screen.set_busy(False)

        _log.info("FACE_BOOTSTRAP_COMPLETED", extra={"employee_id": str(self._subject.id)})
        screen.skipped.emit()


__all__ = ["EXEMPT_ROLES", "FACE_MODULE", "FaceSetupController", "is_enrollment_required"]
