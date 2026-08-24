"""Panel girişində «Üzlə daxil ol» — şifrənin ALTERNATİVİ (facecontrol.md).

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI KONTROLLER, KİOSKUNKU YARAMIR
──────────────────────────────────────────────────────────────────────────────
`KioskController.authenticate_by_face()` 1:N tanıma edir — «kameranın
qarşısındakı adam kimdir?» — və axtarışı BİR MAĞAZA ilə məhdudlaşdırır, çünki
kiosk PC-si mağazanın cihazıdır (`KOMPASOS_STORE_ID`).

Panel maşınında həmin şərt YOXDUR: idarəçi noutbukunun mağazası yoxdur, yəni
1:N axtarış bütün şəbəkə üzrə gedərdi. `identify_for_login` başlığı bu yolun
riyazi riskini açıq yazır: namizəd sayı artdıqca «ən yaxın qonşu» təsadüfən
yaxın düşə bilər. Üstəlik panel girişi CƏRİMƏ KƏSMƏK, İCAZƏ TƏSDİQLƏMƏK və
SƏLAHİYYƏT DƏYİŞMƏK deməkdir — yəni ən riskli tanıma üsulunu ən səlahiyyətli
qapıya qoymaq olmazdı.

Ona görə burada 1:1 DOĞRULAMA var: istifadəçi adını YAZIR (o sahə onsuz da
ekrandadır), sistem isə «bu, HƏQİQƏTƏN həmin adamdırmı?» sualına cavab verir.
Üz şifrəni əvəz edir, istifadəçi adını yox.

──────────────────────────────────────────────────────────────────────────────
`NOT_APPLICABLE` BURADA GİRİŞ VERMİR — KİOSKDAN ƏSAS FƏRQ
──────────────────────────────────────────────────────────────────────────────
Kioskda üz qapısı PIN-dən SONRA işləyir, yəni İKİNCİ amildir: modul söndürülüb
və ya mağaza pilot əhatəsindən kənardadırsa (`NOT_APPLICABLE`) axın haqlı
olaraq «yalnız PIN» rejiminə düşür — birinci amil onsuz da yoxlanılıb.

Burada isə üz TƏK amildir. Eyni yumşalmanı təkrarlasaydıq, modulu bağlı olan
kirayəçidə istifadəçi adını yazıb düyməni basmaq PANELƏ GİRMƏK üçün kifayət
edərdi — yəni şifrə sükutla ləğv olardı. Ona görə giriş YALNIZ `ALLOWED` və
`ALLOWED_LOW_CONFIDENCE` nəticələrində verilir; qalan hər şey (o cümlədən
`NOT_APPLICABLE`) istifadəçini şifrə sahəsinə qaytarır.

──────────────────────────────────────────────────────────────────────────────
ŞİFRƏ YOLUNUN QAPILARI TƏKRARLANIR, YAN KEÇİLMİR
──────────────────────────────────────────────────────────────────────────────
`assert_admin_login_allowed()` (deaktiv hesab, kamera-tipli rol) və
`must_change_password` — hər ikisi `AdminLoginUseCase.login`-dədir. Üz yolu
onları TƏKRAR yoxlayır: yoxlamasaydı, «üzlə daxil ol» deaktiv hesabı və ya
şifrəsi sıfırlanmış hesabı içəri buraxan gizli qapı olardı.

Audit yazısı da eyni hərəkət adı ilə gedir (`ADMIN_LOGIN`), lakin
`method="FACE"` ilə: giriş hesabatları tam qalır, baxan adam isə hansı yolla
girildiyini görür.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from src.application.use_cases.authentication import AccountLockedError
from src.application.use_cases.face_control import FaceGateOutcome
from src.domain.policies import FeatureModule
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.face_recognition import FaceTriggerContext
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Hesabın mövcudluğunu AÇIQLAMAYAN ümumi mesaj.
#:
#: `auth.py`-dakı `GENERIC_FAILURE_MESSAGE` ilə eyni məqsəd daşıyır və eyni
#: qalmalıdır: «bu istifadəçi adı yoxdur» ilə «üzünüz uyğun gəlmədi» fərqi
#: hesabları sadalamağa (user enumeration) imkan verərdi.
GENERIC_FACE_FAILURE: Final = "Üzlə giriş alınmadı. Şifrənizlə daxil olun."

#: Üzlə girişə İCAZƏ VERƏN yeganə iki nəticə (bax modul başlığı).
#:
#: `ALLOWED_LOW_CONFIDENCE` içəridədir, çünki o, RƏDD deyil: bal aşağı-etibar
#: zolağındadır və qeyd Kamera Operatoru üçün nişanlanır (bənd 12). Onu
#: bloklasaydıq, eynək taxmış və ya işığı zəif otaqda oturan istifadəçi
#: təsadüfi qaydada girişdən məhrum olardı.
GRANTING_OUTCOMES: frozenset[FaceGateOutcome] = frozenset(
    {FaceGateOutcome.ALLOWED, FaceGateOutcome.ALLOWED_LOW_CONFIDENCE}
)


@dataclass(frozen=True)
class FaceLoginOutcome:
    """Bir «üzlə daxil ol» cəhdinin nəticəsi — İSTİSNA ATMIR.

    `AuthOutcome` ilə eyni səbəbdən: giriş ekranında çökən kod istifadəçini
    tamamilə bloklayardı və şifrə yolu da onunla birlikdə ölərdi.
    """

    succeeded: bool
    message: str = ""
    employee: Employee | None = None
    #: `must_change_password` — ekran onu AYRI mesajla göstərir.
    must_change_password: bool = False

    @property
    def failed(self) -> bool:
        return not self.succeeded


class FaceLoginController:
    """`AdminLoginScreen`-in «Üzlə daxil ol» düyməsinin arxa tərəfi."""

    def __init__(self, context: ApplicationContext) -> None:
        self._context = context

    # ------------------------------ görünmə ---------------------------------- #

    def available(self) -> bool:
        """Düymə göstərilsinmi — modul + `cv2` kitabxanası, BİRLƏŞMİŞ CANLI yoxlama.

        ──────────────────────────────────────────────────────────────────────
        KAMERA BURADA AÇILMIR — KİOSKDAN FƏRQLİ QƏRAR
        ──────────────────────────────────────────────────────────────────────
        Kiosk `is_available()` çağırır və o, cihazı FAKTİKİ olaraq açır
        (`OpenCvCameraCapture._ensure_device`). Kioskda bu düzgündür: kamera
        həmin PC-də bu tətbiqə həsr olunub və üz düyməsi əsas yoldur.

        Panel maşınında isə eyni çağırış hər idarəçinin veb-kamerasını proqram
        açıq olduğu müddətcə tutulu saxlayardı — halbuki düymə burada
        ALTERNATİVDİR və şifrə sahəsi elə yanındadır. Ona görə yalnız ucuz
        yoxlama aparılır: modul açıqdırmı və `cv2` idxal olunurmu.

        Kamera əslində yoxdursa bu, basılan anda aydın mesajla bilinir və
        istifadəçi şifrə sahəsinə qayıdır — itki bir toxunuşdur, qazanc isə
        bütün ofis maşınlarında kameranın boş qalmasıdır.

        ──────────────────────────────────────────────────────────────────────
        BÜTÖV METOD YALNIZ PRELOAD-SUZ ÇAĞIRIŞ YERLƏRİNDƏ (PERF-6, `cv2` maddəsi)
        ──────────────────────────────────────────────────────────────────────
        `app.py::show_login()` startup yolunda bunu ARTIQ ÇAĞIRMIR —
        `module_enabled()`/`camera_available()` AYRI-AYRI, fərqli sap/anlarda
        işlədilir (bax onların başlığı: `cv2` idxalının giriş ekranından
        ƏVVƏL, splash arxasında baş verməsi ölçülüb, `docs/performance_
        notes.md` PERF-6 1a). Bu metod YALNIZ logout/sessiya-bitmə kimi
        preload-suz yollarda qalır — orada `cv2` artıq idxal olunub (proses
        keşi), ayrıca fon işi lazım deyil.
        """
        if not self.camera_available():
            return False
        return self.module_enabled()

    def module_enabled(self) -> bool:
        """YALNIZ toggle — `cv2` idxal ETMİR (PERF-6, `cv2` maddəsi).

        Splash arxasındakı fon işinə (`app.py::_compute_startup_preload`)
        DAXİL EDİLƏ BİLƏN YEGANƏ hissədir — DB oxusu ucuzdur (batch daxilində)
        və Qt-yə TOXUNMUR. `camera_available()`-in ƏKSİNƏ, giriş ekranını
        gecikdirmir.
        """
        try:
            with self._context.session() as session:
                enabled: bool = session.toggles.is_enabled(
                    session.tenant_id, FeatureModule.CAMERA_VERIFICATION.value
                )
                return enabled
        except Exception:
            _log.exception("FACE_LOGIN_AVAILABILITY_FAILED")
            return False

    def camera_available(self) -> bool:
        """YALNIZ `cv2` mövcudluğu — DB-yə TOXUNMUR (PERF-6, `cv2` maddəsi).

        `app.py::_probe_face_login_camera()` bunu giriş ekranı ARTIQ
        GÖRÜNDÜKDƏN SONRA, AYRI fon işində çağırır — idxalın ÖZÜ (soyuq
        keşdə 70–624 ms) heç bir sinxron yolu BLOKLAMASIN deyə.
        """
        from src.infrastructure.kiosk.camera import camera_available  # noqa: PLC0415

        return bool(camera_available())

    # ------------------------------- giriş ----------------------------------- #

    def authenticate(self, username: str) -> FaceLoginOutcome:
        """İstifadəçi adı + üz (1:1 doğrulama) ilə giriş."""
        raw = username.strip()
        if not raw:
            # Bu, təhlükəsizlik mesajı DEYİL — istifadəçi sadəcə sahəni boş
            # qoyub. Ümumi mesaj versəydik, o, nasazlıq sanardı.
            return FaceLoginOutcome(
                succeeded=False,
                message="Üzlə giriş üçün əvvəlcə istifadəçi adınızı yazın.",
            )

        employee = self._lookup(raw)
        if employee is None:
            return FaceLoginOutcome(succeeded=False, message=GENERIC_FACE_FAILURE)

        try:
            # Şifrə yolundakı EYNİ domen qapısı — deaktiv hesab, kamera-tipli
            # rol və s. Yan keçilsəydi, üz düyməsi həmin qapıların hamısını
            # açan gizli yol olardı.
            employee.assert_admin_login_allowed()
        except KompasOSError as exc:
            _security_log.warning("FACE_LOGIN_REJECTED", extra=exc.to_dict())
            return FaceLoginOutcome(succeeded=False, message=exc.user_message)

        if employee.must_change_password:
            # Şifrə dəyişdirilməlidirsə üz onu ƏVƏZ EDƏ BİLMƏZ: dəyişdirmə
            # məhz şifrə yolundadır və üzlə giriş onu sonsuza qədər təxirə
            # salardı.
            return FaceLoginOutcome(
                succeeded=False,
                message="Şifrəniz dəyişdirilməlidir. Admininizlə əlaqə saxlayın.",
                must_change_password=True,
            )

        return self._verify(employee)

    # ------------------------------- daxili ---------------------------------- #

    def _lookup(self, username: str) -> Employee | None:
        """İstifadəçi adına görə hesabı tapır — TAPILMADIQDA `None`.

        Səbəb açıqlanmır və log-a `username_attempt` düşür (şifrə yolu ilə
        eyni naxış): ekranda fərq görünsəydi, hesab siyahısı toplamaq olardı.
        """
        try:
            with self._context.session() as session:
                found: Employee | None = session.uow.employees.get_by_username(
                    session.tenant_id, Username(username)
                )
        except ValueError:
            # `Username` formatı yanlışdır — mövcud olmayan hesabla EYNİ cavab.
            return None
        except Exception:
            _log.exception("FACE_LOGIN_LOOKUP_FAILED")
            return None

        if found is None:
            _security_log.warning(
                "FACE_LOGIN_FAILED",
                extra={"username_attempt": username, "reason": "UNKNOWN_ACCOUNT"},
            )
        return found

    def _verify(self, employee: Employee) -> FaceLoginOutcome:
        """1:1 üz doğrulaması + audit — HAMISI BİR TRANZAKSİYADA.

        Commit MƏCBURİDİR: `verify` `face_verification_log` sətri, uyğunsuzluq
        sayğacı və (hədd aşılarsa) kilid yazır. Commit unudulsaydı, uğursuz
        cəhdin izi rollback olardı — yəni sistem uyğunsuzluğu görər, lakin
        heç yerdə saxlamazdı (`KioskController._face_gate` ilə eyni səbəb).
        """
        try:
            with self._context.session(user_id=employee.id) as session:
                decision = session.face_verification.verify(
                    tenant_id=session.tenant_id,
                    employee=employee,
                    trigger_context=FaceTriggerContext.LOGIN,
                )
                granted = decision.outcome in GRANTING_OUTCOMES
                if granted:
                    session.uow.audit.record(
                        tenant_id=employee.tenant_id,
                        actor_id=employee.id,
                        action="ADMIN_LOGIN",
                        entity_type="employees",
                        entity_id=employee.id,
                        after_state={"method": "FACE", "outcome": decision.outcome.value},
                    )
                # `NOT_APPLICABLE` heç nə yazmır (bax `_not_applicable`) — boş
                # tranzaksiyanı commit etmək hər toxunuşa bir şəbəkə
                # gediş-gəlişi əlavə edərdi.
                if decision.outcome is not FaceGateOutcome.NOT_APPLICABLE:
                    session.commit()
        except AccountLockedError as exc:
            # Üz kilidi (bənd 4) AÇIQ deyilir: istifadəçi nə qədər
            # gözləyəcəyini bilməlidir və şifrə yolu ona onsuz da açıqdır.
            _security_log.warning("FACE_LOGIN_LOCKED", extra=exc.to_dict())
            return FaceLoginOutcome(succeeded=False, message=exc.user_message)
        except KompasOSError as exc:
            _security_log.warning("FACE_LOGIN_GATE_REJECTED", extra=exc.to_dict())
            return FaceLoginOutcome(succeeded=False, message=exc.user_message)
        except Exception:
            # FAIL-CLOSED: nasazlıq «buraxaq»a çevrilmir. Şifrə yolu açıq
            # qaldığı üçün istifadəçi bloklanmır.
            _security_log.critical("FACE_LOGIN_GATE_FAILED")
            return FaceLoginOutcome(
                succeeded=False,
                message="Üz təsdiqi aparıla bilmədi. Şifrənizlə daxil olun.",
            )

        if not granted:
            _security_log.warning(
                "FACE_LOGIN_DENIED",
                extra={"employee_id": str(employee.id), "outcome": decision.outcome.value},
            )
            message = decision.message_az
            if decision.outcome is FaceGateOutcome.NOT_APPLICABLE:
                # `message_az` burada «tətbiq olunmur» deyir — istifadəçi üçün
                # bu, heç nə demir. Ona NƏ ETMƏLİ olduğu deyilir.
                message = "Bu hesab üçün üzlə giriş aktiv deyil. Şifrənizlə daxil olun."
            return FaceLoginOutcome(succeeded=False, message=message or GENERIC_FACE_FAILURE)

        _security_log.info(
            "LOGIN_SUCCESS",
            extra={
                "employee_id": str(employee.id),
                "role": employee.position.code,
                "method": "FACE",
            },
        )
        return FaceLoginOutcome(succeeded=True, employee=employee)


__all__ = [
    "GENERIC_FACE_FAILURE",
    "GRANTING_OUTCOMES",
    "FaceLoginController",
    "FaceLoginOutcome",
]
