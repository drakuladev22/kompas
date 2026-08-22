"""Kiosk körpüsü: PIN klaviaturası ↔ use case-lər (bölmə 4) — Faza 5.

`app.py` yalnız ekranları bağlayır; həqiqi PIN yoxlaması, status hesablaması
və `[İşə Başladım]`/`[İcazə İstəyirəm]`/`[Mən Qayıtdım]` əməliyyatları buradan
keçir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI KONTROLLER
──────────────────────────────────────────────────────────────────────────────
`auth.py`-dakı eyni səbəb: ekran Qt siqnalları ilə işləyir, use case isə saf
funksiyadır və domen istisnaları atır. Kiosk PC-si üstəlik PAYLAŞILAN cihazdır
— orada istisna ilə çökən ekran bütün mağazanı bloklayardı, ona görə hər
əməliyyat `KioskOutcome`-a çevrilir və istisna EKRANA ÇIXMIR.

──────────────────────────────────────────────────────────────────────────────
STATUS NİYƏ HƏR DƏFƏ YENİDƏN HESABLANIR
──────────────────────────────────────────────────────────────────────────────
Bölmə 3 (İŞÇİ ANA EKRANI) beş status və hər biri üçün TƏK bir aktiv düymə
tələb edir. Statusu keşləsək, Kamera Operatoru təsdiqlədikdən sonra işçinin
ekranı köhnə düyməni göstərərdi və o, "təsdiqlə" düyməsini basa bilməzdi.

──────────────────────────────────────────────────────────────────────────────
ÜZ QAPISI — BU MODUL KİOSK AXININ TƏK GİRİŞ NÖQTƏSİDİR (facecontrol.md Faza 4)
──────────────────────────────────────────────────────────────────────────────
`use_cases/face_control.py` başlığı öz qərarının ZƏİF NÖQTƏSİNİ açıq
sənədləşdirib: üz təsdiqi `start_day`/`request_leave`/`claim_return`
metodlarının İÇİNƏ yazılmayıb, ona görə həmin metodları BİRBAŞA çağıran hər
yol (skript, plugin, gələcək API) üz yoxlamasını atlaya bilər. Həmin başlıq
boşluğu bağlayacaq qatı da adlandırır: kiosk giriş nöqtəsi TƏK olmalıdır və
STEP A/1/2 yalnız oradan çağırılmalıdır.

O qat MƏHZ BU FAYLDIR. Struktur belədir:

    start_day / request_leave / claim_return
        └─ _guarded(...)              ← ÜZ QAPISI BURADADIR
             ├─ _face_gate(...)       ← `session.face_verification.verify`
             └─ _operation(...)       ← YALNIZ qapı buraxsa çağırılır

Üç ictimai metodun heç biri `_operation`-u BİRBAŞA çağırmır — hamısı
`_guarded`-dən keçir. Bu, üslub seçimi deyil, TƏHLÜKƏSİZLİK invariantıdır və
`tests/unit/test_face_control_screen.py::
test_kiosk_operations_never_bypass_the_face_gate` mənbə mətnini AST ilə oxuyub
onu qoruyur (naxış `test_root_control_parameter_parity`-dəndir): kimsə
gələcəkdə dördüncü əməliyyat əlavə edib `_operation`-u birbaşa çağırsa, test
qırılır — istehsalatda üz qatının sükutla yan keçilməsindən ƏVVƏL.

QƏRARI KONTROLLER VERMİR: istisnalı işçi (bənd 14), kamera nasazlığı (bənd 5),
mağaza əhatəsi (bənd 15) və kilid (bənd 4) hallarının HAMISI use case-in
içindədir. Burada yalnız «qapı buraxdımı?» sualı verilir — `FaceGateOutcome.
allows_operation`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

from src.application.use_cases.authentication import AccountLockedError
from src.application.use_cases.face_control import FaceGateOutcome
from src.application.use_cases.leave_verification import (
    ModuleDisabledError,
    OperationNotPermittedError,
    TimeDriftError,
)
from src.domain.policies import BreakKind
from src.domain.value_objects.face_recognition import FaceTriggerContext
from src.presentation.widgets.worker_status import WorkerStatus
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.application.use_cases.face_control import FaceGateDecision
    from src.domain.entities.employee import Employee
    from src.domain.policies import BreakAllowance
    from src.domain.value_objects.catalogs import LeaveType
    from src.domain.value_objects.identifiers import EmployeeId, LeaveTypeId, StoreId
    from src.domain.value_objects.machine_identity import MachineIdentityHash
    from src.presentation.composition import ApplicationContext, Session

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)
_log = get_logger(__name__)

#: PIN səhv olduqda göstərilən ÜMUMİ mesaj — hansı işçi olduğu açıqlanmır.
GENERIC_PIN_FAILURE = "PIN yanlışdır"

#: Üz qapısı GÖZLƏNİLMƏZ səbəbdən işləmədikdə göstərilən mətn.
#:
#: FAIL-CLOSED: qapı çökəndə əməliyyat DAVAM ETMİR. «Xəta oldu, buraxaq»
#: variantı bənd 5-in birbaşa qadağasıdır — texniki nasazlığın sükutla
#: "yalnız PIN" rejiminə çevrilməsi. Nasazlığın ÖZÜ isə gizlədilmir: mesaj
#: işçiyə nə etməli olduğunu deyir və `security.log`-a kritik sətir düşür.
FACE_GATE_UNAVAILABLE = (
    "Üz təsdiqi aparıla bilmədi. Giriş/qayıdış təsdiqiniz üçün mağaza rəhbərinizə "
    "və ya HR_Admin-ə müraciət edin."
)

#: Overlay YALNIZ bu nəticələrdə açılır.
#:
#: `ALLOWED` və `NOT_APPLICABLE` QƏSDƏN KƏNARDADIR: uğurlu üz təsdiqi gündə
#: onlarla dəfə baş verir və hər dəfə bağlanmalı modal göstərmək kiosk axınına
#: bir toxunuş ƏLAVƏ edərdi — nəticə isə onsuz da İşçi Ana Ekranındakı status
#: mesajında görünür. `ALLOWED_LOW_CONFIDENCE` də kənardadır: o nişan KAMERA
#: OPERATORU üçündür (bənd 12 — «operator daha diqqətli ola bilsin»), işçiyə
#: «üzünüz zəif tanındı» demək isə heç bir hərəkət təklif etmir.
BLOCKING_FACE_OUTCOMES: frozenset[str] = frozenset(
    {
        FaceGateOutcome.RETRY.value,
        FaceGateOutcome.BLOCKED.value,
        FaceGateOutcome.LOCKED.value,
        FaceGateOutcome.MANUAL_APPROVAL_REQUIRED.value,
        FaceGateOutcome.DUAL_CONTROL_REQUIRED.value,
    }
)


@dataclass(frozen=True)
class KioskOutcome:
    """Hər kiosk əməliyyatının nəticəsi — istisna ATMIR."""

    succeeded: bool
    message: str = ""
    status: WorkerStatus | None = None
    employee: Employee | None = None
    #: Üz qapısının nəticəsi — `FaceVerificationOverlay.set_result()` açarları.
    #: Boş sözlük = qapı ümumiyyətlə işləməyib (məs. PIN handshake nəticəsi).
    face: dict[str, str] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return not self.succeeded

    @property
    def requires_face_overlay(self) -> bool:
        """Üz təsdiqi overlay-i göstərilsinmi (bax `BLOCKING_FACE_OUTCOMES`)."""
        return self.face.get("outcome", "") in BLOCKING_FACE_OUTCOMES


@dataclass(frozen=True)
class FaceGate:
    """Üz qapısının bir çağırışının nəticəsi — kontrollerin daxili tipi.

    `FaceGateDecision`-dan FƏRQLİDİR və qəsdən: bu, artıq EKRAN üçün
    hazırlanmış sözlüyü daşıyır (`face`) və istisna hallarını da eyni formaya
    salır — use case ümumiyyətlə çağırıla bilmədikdə `FaceGateDecision`
    mövcud olmur, lakin işçi yenə də bir mesaj görməlidir.
    """

    allowed: bool
    message: str
    face: dict[str, str]


class KioskController:
    """İşçi Ana Ekranının arxa tərəfi."""

    def __init__(
        self,
        context: ApplicationContext,
        *,
        store_id: StoreId,
        machine_key: MachineIdentityHash,
    ) -> None:
        self._context = context
        self._store_id = store_id
        # SEC-01/SEC-05 (dövrə 3) — BİR DƏFƏ, KONSTRUKTORDA hesablanır (bax
        # `app.py::_build_kiosk_controller`, `store_id`-nin EYNİ naxışı):
        # maşın kimliyi sessiya ərzində DƏYİŞMİR, hər PIN cəhdində registry-
        # dən yenidən oxumaq lazımsız I/O olardı.
        self._machine_key = machine_key

    @property
    def store_id(self) -> StoreId:
        """Terminalın bağlı olduğu mağaza (DEEP-GAP U5).

        PIN ekranının başlıq sətri əvvəl SABİT mətn idi ("Bellona — 28 May")
        — `app.py::start_kiosk` mağaza adını heç yerdən oxumurdu, halbuki
        `_build_kiosk_controller` onu artıq `KOMPASOS_STORE_ID`-dən tapıb bu
        kontrollerə ötürüb. Xassə YALNIZ oxu üçündür: mağaza terminalın
        ÖMRÜ boyu dəyişmir (bax konstruktor şərhi).
        """
        return self._store_id

    # -------------------------------- PIN ------------------------------------ #

    def authenticate(self, pin: str) -> KioskOutcome:
        """PIN handshake — uğurlu olduqda işçi və onun cari statusu qaytarılır."""
        try:
            with self._context.session() as session:
                import socket  # noqa: PLC0415

                from src.application.use_cases.authentication import (  # noqa: PLC0415
                    PinHandshakeUseCase,
                )
                from src.infrastructure.security.hashing import (  # noqa: PLC0415
                    HashingService,
                )
                from src.infrastructure.timekeeping.clock import (  # noqa: PLC0415
                    SystemClock,
                )
                from src.shared.security_events import (  # noqa: PLC0415
                    FailSoftSecurityEventRecorder,
                )

                employees = session.uow.employees
                candidates = employees.find_by_pin_candidates(
                    self._context.tenant_id, self._store_id
                )
                pin_hashes = {}
                for candidate in candidates:
                    credentials = employees.credentials_for(candidate.id)
                    if credentials is not None and credentials.pin_hash:
                        pin_hashes[candidate.id] = (
                            credentials.pin_hash,
                            credentials.pepper_version,
                        )

                use_case = PinHandshakeUseCase(
                    employees=employees,
                    # `limits`: hash servisinin ROOT pəncərəsi. PIN siyasəti
                    # (cəhd sayı / bloklama) use case-in ÖZ `limits`-indən
                    # gəlir — burada ikinci mənbə yaranmır, sadəcə servis də
                    # ROOT-a bağlanır (şifrə uzunluğu siyasəti üçün).
                    hashing=HashingService(limits=self._context.infrastructure_limits()),
                    clock=SystemClock(),
                    limits=session.limits,
                    audit=session.uow.audit,
                    # SEC-7 — SARILMIŞ forma MƏCBURİDİR (bax `app.py::
                    # _SessionScopedLogin.login` eyni şərhi): xam repo
                    # bağlansaydı `security_events` yazı xətası PIN girişini
                    # DAYANDIRARDI — kassa növbəsində bu, DOĞRUDAN-DOĞRUYA
                    # xidmət kəsintisidir.
                    security_events=FailSoftSecurityEventRecorder(
                        session.uow.repository("security_events")
                    ),
                    # SEC-01 (dövrə 3) — XAM repo, SARILMIR: `security_events`-
                    # dən FƏRQLİ, terminal PIN throttle TƏHLÜKƏSİZLİK QAPISININ
                    # ÖZÜDÜR. Fail-soft bükücü onu `security_events` kimi
                    # "yazı uğursuz olsa keç" edərdi — nəticədə throttle
                    # sükutla söndürülmüş olardı, məhz SEC-7-nin qadağan
                    # etdiyi hal ("təhlükəsizlik qapısını fail-soft mənbədən
                    # qidalandırmaq olmaz").
                    pin_throttle=session.uow.repository("pin_throttle"),
                )
                result = use_case.authenticate(
                    tenant_id=self._context.tenant_id,
                    store_id=self._store_id,
                    # SEC-01/SEC-05 (dövrə 3) — konstruktorda BİR DƏFƏ oxunub
                    # (bax `__init__`, `_build_kiosk_controller`).
                    machine_key=self._machine_key,
                    pin=pin,
                    pin_hashes=pin_hashes,
                    # `ip_address` naməlum (masaüstü tətbiq, HTTP sorğusu
                    # yoxdur) — uydurmaqdansa `None`.
                    machine_name=socket.gethostname(),
                )
                # Uğursuz cəhdin sayğacı da yazılmalıdır (lockout, bölmə 2).
                session.commit()

                # `PinResult` YALNIZ uğurlu halda qayıdır — uğursuzluq
                # `AuthenticationError`/`AccountLockedError` ilə bildirilir
                # (aşağıdakı `except KompasOSError` onu tutur).
                employee = result.employee
                status = self._status_for(session, employee.id)
        except KompasOSError as exc:
            _security_log.info("KIOSK_PIN_REJECTED", extra=exc.to_dict())
            return KioskOutcome(succeeded=False, message=exc.user_message)
        except Exception:
            _log.exception("KIOSK_PIN_UNEXPECTED_ERROR")
            return KioskOutcome(
                succeeded=False,
                message="Sistem xətası. Bir az sonra yenidən cəhd edin.",
            )

        # ------------------------------------------------------------------ #
        # ÜZ QAPISI GİRİŞİN ÖZÜNDƏDİR (miqrasiya 057)
        # ------------------------------------------------------------------ #
        # PIN dörd rəqəmdir və kiosk mağaza zalındadır — yəni onu başqasına
        # vermək (və ya çiynin üstündən oxumaq) real ssenaridir. Qapı yalnız
        # ƏMƏLİYYATDA olsaydı, PIN-i bilən adam üçün ekran ONSUZ DA açılardı:
        # o, işçinin açıq tapşırıqlarını, xal balansını və cərimə tarixçəsini
        # görərdi. Yəni məlumat sızması «İşə Başladım» basılmasa belə baş
        # verirdi.
        #
        # SESSİYA BAĞLANDIQDAN SONRA çağırılır: `_face_gate` öz sessiyasını
        # açır və MISMATCH izini AYRICA commit edir (bax onun başlığı) — iç-içə
        # sessiya həmin izi girişin rollback-ı ilə birlikdə silərdi.
        gate = self._face_gate(employee, FaceTriggerContext.LOGIN)
        if not gate.allowed:
            _security_log.warning(
                "KIOSK_LOGIN_FACE_REJECTED",
                extra={"employee_id": str(employee.id), "outcome": gate.face.get("outcome", "")},
            )
            return KioskOutcome(succeeded=False, message=gate.message, face=gate.face)

        return KioskOutcome(succeeded=True, status=status, employee=employee, face=gate.face)

    def authenticate_by_face(self) -> KioskOutcome:
        """«Üzlə daxil ol» — PIN-siz giriş.

        ──────────────────────────────────────────────────────────────────────
        İKİ ADDIM: ƏVVƏLCƏ TANIMA, SONRA DOĞRULAMA
        ──────────────────────────────────────────────────────────────────────
        `identify_for_login` sualı «bu kimdir?» (1:N), `verify` sualı isə «bu,
        HƏQİQƏTƏN həmin adamdırmı?» (1:1). İkincisini atlamaq cazibədardır —
        kamera onsuz da bir dəfə işlədi — lakin ATLANMIR, çünki bütün
        anti-fraud yan təsirləri məhz `verify`-dadır: `face_verification_log`
        sətri, istisna qapısı, kilid sayğacı, aşağı-etibarlı işarəsi və
        MISMATCH bildirişi. Yalnız tanıma ilə keçsəydik, üzlə giriş auditdə
        GÖRÜNMƏZ bir yol olardı — yəni ən həssas giriş üsulu ən az izi
        buraxardı.

        İkinci kadrın qiyməti bir neçə saniyədir; izsiz giriş yolunun qiyməti
        isə mübahisə zamanı sübutsuzluqdur.
        """
        try:
            with self._context.session() as session:
                candidates = session.uow.employees.find_by_pin_candidates(
                    self._context.tenant_id, self._store_id
                )
                import socket  # noqa: PLC0415

                identified = session.face_verification.identify_for_login(
                    tenant_id=self._context.tenant_id,
                    store_id=self._store_id,
                    # T1 (DEEP-GAP Faza 4) — `authenticate_with_pin`-dəki EYNİ
                    # dəyər, EYNİ səbəb (SEC-01/SEC-05): açar konstruktorda BİR
                    # DƏFƏ oxunub, `store_id`-dən QURULMUR (admin hüququ
                    # olmadan dəyişdirilə bilər). `machine_name` terminalın
                    # bloklanma/təhlükəsizlik hadisəsində görünən addır — üzlə
                    # giriş yolu bunsuz «naməlum terminal» kimi qeydə düşərdi.
                    machine_key=self._machine_key,
                    candidates=candidates,
                    machine_name=socket.gethostname(),
                )
                # Tanıma cəhdi jurnal yazmır (bax use case başlığı), lakin
                # kamera/kadr vəziyyəti dəyişmiş ola bilər — commit ucuzdur və
                # sessiyanı təmiz bağlayır.
                session.commit()
                if identified is None:
                    return KioskOutcome(
                        succeeded=False,
                        message="Üz tanınmadı. PIN kodunuzu daxil edin.",
                    )
                status = self._status_for(session, identified.id)
        except KompasOSError as exc:
            _security_log.info("KIOSK_FACE_LOGIN_REJECTED", extra=exc.to_dict())
            return KioskOutcome(succeeded=False, message=exc.user_message)
        except Exception:
            _log.exception("KIOSK_FACE_LOGIN_UNEXPECTED_ERROR")
            return KioskOutcome(
                succeeded=False,
                message="Sistem xətası. PIN kodunuzu daxil edin.",
            )

        gate = self._face_gate(identified, FaceTriggerContext.LOGIN)
        if not gate.allowed:
            _security_log.warning(
                "KIOSK_FACE_LOGIN_GATE_REJECTED",
                extra={"employee_id": str(identified.id)},
            )
            return KioskOutcome(succeeded=False, message=gate.message, face=gate.face)

        return KioskOutcome(succeeded=True, status=status, employee=identified, face=gate.face)

    def face_login_available(self) -> bool:
        """Üzlə giriş düyməsi göstərilsinmi — modul + əhatə + kamera.

        Üçü də yoxlanılır, çünki hər biri AYRI səbəbdən söndürülə bilər və
        düyməni yalnız kameraya görə göstərsəydik, modulu bağlı olan mağazada
        işçi basar, «üz tanınmadı» görər və bunu nasazlıq sanardı.
        """
        try:
            with self._context.session() as session:
                return session.face_verification.login_available(
                    tenant_id=self._context.tenant_id, store_id=self._store_id
                )
        except Exception:
            _log.exception("KIOSK_FACE_AVAILABILITY_FAILED")
            return False

    # ----------------------------- əməliyyatlar ------------------------------ #

    def start_day(self, employee: Employee) -> KioskOutcome:
        """`[İşə Başladım]` — STEP A (bölmə 4), ÜZ QAPISINDAN sonra."""

        def run(session: Session) -> None:
            session.morning_check_in.start_day(
                tenant_id=self._context.tenant_id,
                employee_id=employee.id,
                store_id=self._store_id,
            )

        return self._guarded(
            employee,
            FaceTriggerContext.STEP_A,
            run,
            success="Giriş sorğunuz göndərildi.",
        )

    def request_leave(
        self, employee: Employee, *, leave_type_id: LeaveTypeId | None = None
    ) -> KioskOutcome:
        """`[İcazə İstəyirəm]` — STEP 1 (bölmə 4), ÜZ QAPISINDAN sonra."""

        def run(session: Session) -> None:
            session.leave_verification.request_leave(
                tenant_id=self._context.tenant_id,
                employee_id=employee.id,
                store_id=self._store_id,
                leave_type_id=leave_type_id,
                # STEP 1 yalnız `🟢 Mağazada` statusundan işə düşür — həmin
                # şərti use case özü yoxlaya bilsin deyə açıq ötürülür.
                employee_is_in_store=True,
            )

        return self._guarded(
            employee,
            FaceTriggerContext.STEP_1,
            run,
            success="İcazə sorğunuz qeydə alındı.",
        )

    def break_options(self, employee: Employee) -> list[dict[str, str]]:
        """Nahar/Çay seçimləri + həmin günkü sayğac (nahar.md GUI, bənd 2).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ `KioskController`-DƏ, AYRI KONTROLLERDƏ DEYİL
        ──────────────────────────────────────────────────────────────────────
        "Açıq Növbələr" (#16) və "İllik Məzuniyyət" (#28) kartları ÖZ
        kontrollerlərini aldı, çünki onlar günün axınından KƏNARDIR (gələcək
        günə aiddir, statusdan asılı deyil). Fasilə seçimi isə məhz günün
        axınının bir hissəsidir: `[İcazə İstəyirəm]` düyməsinin arqumentidir
        və hər STEP1-dən sonra yenilənməlidir. Ayrı kontrollerdə yaşasaydı,
        seçim ilə onu istifadə edən əməliyyat iki fərqli sahibə düşərdi.

        ──────────────────────────────────────────────────────────────────────
        XƏTA EKRANA ÇIXMIR
        ──────────────────────────────────────────────────────────────────────
        Modul başlığındakı qayda burada da qüvvədədir: kiosk PAYLAŞILAN
        cihazdır. Sayğac oxuna bilmirsə BOŞ siyahı qayıdır — kart gizlənir və
        işçi ümumi icazə ilə davam edir. Fasilə göstəricisinin olmaması
        `[İcazə İstəyirəm]` düyməsini bloklamamalıdır.
        """
        try:
            with self._context.session(user_id=employee.id) as session:
                types = session.uow.repository("leave_types").list_all(self._context.tenant_id)
                by_kind = {
                    entry.break_kind: entry for entry in types if entry.break_kind is not None
                }
                if not by_kind:
                    return []

                status = session.leave_verification.break_status(
                    tenant_id=self._context.tenant_id,
                    employee_id=employee.id,
                    on_date=date.today(),  # noqa: DTZ011 — `_status_for` ilə eyni yerli gün
                )
                # SIRA `BreakKind` ELANINDAN gəlir (LUNCH, TEA) — bazanın
                # qaytardığı əlifba sırası "Çay"-ı öndə göstərərdi, halbuki
                # nahar.md-də və ROOT ekranında sıra Nahar → Çay-dır.
                return [
                    self._break_option(by_kind[kind], status[kind])
                    for kind in BreakKind
                    if kind in by_kind and kind in status
                ]
        except KompasOSError as exc:
            _log.info("KIOSK_BREAK_OPTIONS_UNAVAILABLE", extra=exc.to_dict())
            return []
        except Exception:
            _log.exception("KIOSK_BREAK_OPTIONS_FAILED")
            return []

    @staticmethod
    def _break_option(entry: LeaveType, allowance: BreakAllowance) -> dict[str, str]:
        """Bir fasilə sətri — ekranın gözlədiyi düz mətn lüğəti.

        ETİKET KATALOQDAN, MÜDDƏT İSƏ ROOT-DAN gəlir və bu, qəsdidir:
        HR sətrin ADINI dəyişə bilər ("Nahar Fasiləsi" → "Nahar (uzun)"),
        müddət isə nahar.md-yə görə YALNIZ Root parametridir.
        """
        return {
            "leave_type_id": str(entry.leave_type_id),
            "label": entry.name,
            "detail": f"{allowance.duration_label_az()} · {allowance.usage_label_az()}",
            "warning": allowance.warning_az(),
        }

    def claim_return(self, employee: Employee) -> KioskOutcome:
        """`[Mən Qayıtdım]` — STEP 2 (bölmə 4), ÜZ QAPISINDAN sonra."""

        def run(session: Session) -> None:
            session.leave_verification.claim_return(
                tenant_id=self._context.tenant_id,
                employee_id=employee.id,
            )

        return self._guarded(
            employee,
            FaceTriggerContext.STEP_2,
            run,
            success="Qayıdışınız Kamera Operatoruna göndərildi.",
        )

    # ------------------------------ üz qapısı -------------------------------- #

    def _guarded(
        self,
        employee: Employee,
        trigger_context: FaceTriggerContext,
        action: Callable[[Session], None],
        *,
        success: str,
    ) -> KioskOutcome:
        """ÜZ QAPISI + əməliyyat — üç STEP-in YEGANƏ icra yolu.

        Bax modul başlığı: `start_day`/`request_leave`/`claim_return`
        `_operation`-u BİRBAŞA çağırmır, çünki o zaman üz təsdiqi metod-metod
        əlavə edilməli olardı və dördüncü əməliyyat yazan adam onu unudardı —
        yəni qoruma "yadda saxlamaq" məsələsinə çevrilərdi.

        SIRA DƏYİŞMƏZDİR: əvvəlcə üz, sonra əməliyyat. Tərsinə etsəydik,
        MISMATCH halında giriş sorğusu ARTIQ yaradılmış olardı və üz qapısı
        yalnız «sonradan xəbərdarlıq edən» bir jurnala çevrilərdi.
        """
        gate = self._face_gate(employee, trigger_context)
        if not gate.allowed:
            return KioskOutcome(
                succeeded=False,
                message=gate.message,
                employee=employee,
                face=gate.face,
            )
        outcome = self._operation(employee, action, success=success)
        return KioskOutcome(
            succeeded=outcome.succeeded,
            message=outcome.message,
            status=outcome.status,
            employee=outcome.employee,
            face=gate.face,
        )

    def _face_gate(self, employee: Employee, trigger_context: FaceTriggerContext) -> FaceGate:
        """`FaceVerificationUseCase.verify` — PIN-dən SONRA, əməliyyatdan ƏVVƏL.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ AYRI SESSİYA VƏ NİYƏ COMMIT
        ──────────────────────────────────────────────────────────────────────
        Doğrulama `face_verification_log` sətri, uyğunsuzluq sayğacı və (hədd
        aşılarsa) kilid YAZIR. Commit unudulsaydı, MISMATCH izi rollback
        olardı — yəni sistem uyğunsuzluğu görər, lakin heç yerdə saxlamazdı.
        Əməliyyatın ÖZ tranzaksiyasına salmaq da olmazdı: qapı BLOKLAYANDA
        həmin tranzaksiya geri qaytarılır və jurnal sətri onunla birlikdə
        itərdi — məhz bloklanan halda!

        ──────────────────────────────────────────────────────────────────────
        FAIL-CLOSED
        ──────────────────────────────────────────────────────────────────────
        Gözlənilməz istisna «buraxaq» ilə deyil, BLOKLAMA ilə bitir (bənd 5:
        nasazlıq sükutla "yalnız PIN" rejimi yaratmır). İşçi yönləndirici
        mesaj görür, hadisə isə `security.log`-a düşür.
        """
        try:
            with self._context.session(user_id=employee.id) as session:
                decision = session.face_verification.verify(
                    tenant_id=self._context.tenant_id,
                    employee=employee,
                    trigger_context=trigger_context,
                )
                # COMMIT YALNIZ YAZI OLDUQDA: `NOT_APPLICABLE` yolu (modul
                # söndürülüb və ya mağaza pilot əhatəsindən kənardadır) nə
                # jurnal sətri, nə audit yazır — bax `FaceVerificationUseCase.
                # _not_applicable`. Şərtsiz commit həmin mağazalarda HƏR kiosk
                # toxunuşuna bir boş tranzaksiya (şəbəkə gediş-gəlişi) əlavə
                # edərdi; paylaşılan kiosk PC-də bu, görünən gecikmədir.
                if decision.outcome is not FaceGateOutcome.NOT_APPLICABLE:
                    session.commit()
        except AccountLockedError as exc:
            # Üz kilidi (bənd 4) PIN kilidindən AYRIDIR, lakin ekran davranışı
            # eynidir: səbəb göstərilir, terminal söndürülmür (bax
            # `PinPadScreen.show_lockout` başlığı — kilid İŞÇİ-başınadır).
            _security_log.warning("KIOSK_FACE_LOCKED", extra=exc.to_dict())
            return FaceGate(
                allowed=False,
                message=exc.user_message,
                face={
                    "outcome": "LOCKED",
                    "message": exc.user_message,
                    "gesture": "",
                    "confidence": "",
                    "retry": "0",
                },
            )
        except KompasOSError as exc:
            _security_log.warning("KIOSK_FACE_GATE_REJECTED", extra=exc.to_dict())
            return FaceGate(
                allowed=False,
                message=exc.user_message,
                face={
                    "outcome": "BLOCKED",
                    "message": exc.user_message,
                    "gesture": "",
                    "confidence": "",
                    "retry": "0",
                },
            )
        except Exception:
            _security_log.critical("KIOSK_FACE_GATE_FAILED")
            return FaceGate(
                allowed=False,
                message=FACE_GATE_UNAVAILABLE,
                face={
                    "outcome": "MANUAL_APPROVAL_REQUIRED",
                    "message": FACE_GATE_UNAVAILABLE,
                    "gesture": "",
                    "confidence": "",
                    "retry": "0",
                },
            )

        return FaceGate(
            allowed=bool(decision.allows_operation),
            message=decision.message_az,
            face=face_result_row(decision),
        )

    # ------------------------------- köməkçi --------------------------------- #

    def _operation(
        self,
        employee: Employee,
        action: Callable[[Session], None],
        *,
        success: str,
    ) -> KioskOutcome:
        """Ortaq icra qabığı — istisna ekrana ÇIXMIR (modul başlığına bax)."""
        try:
            with self._context.session(user_id=employee.id) as session:
                action(session)
                session.commit()
                status = self._status_for(session, employee.id)
        except (TimeDriftError, ModuleDisabledError, OperationNotPermittedError) as exc:
            return KioskOutcome(succeeded=False, message=exc.user_message)
        except KompasOSError as exc:
            return KioskOutcome(succeeded=False, message=exc.user_message)
        except Exception:
            _log.exception("KIOSK_OPERATION_FAILED")
            return KioskOutcome(
                succeeded=False, message="Əməliyyat tamamlanmadı. Yenidən cəhd edin."
            )
        return KioskOutcome(succeeded=True, message=success, status=status, employee=employee)

    def status_for(self, employee_id: EmployeeId) -> WorkerStatus:
        """Ekranın yenilənməsi üçün cari status."""
        with self._context.session() as session:
            return self._status_for(session, employee_id)

    def _status_for(self, session: Session, employee_id: EmployeeId) -> WorkerStatus:
        """Davamiyyət + açıq icazə qeydlərini birləşmiş statusa çevirir.

        Çevirmə QAYDASI burada TƏKRARLANMIR — `WorkerStatus.from_domain()`
        onu artıq saxlayır (icazənin davamiyyəti üstələməsi daxil olmaqla).
        Bu metod yalnız iki qeydi oxuyur və ona ötürür.
        """
        uow = session.uow
        open_leave = uow.leave_requests.find_open_for_employee(employee_id)
        record = uow.attendance.get_for_day(employee_id, date.today())  # noqa: DTZ011
        return WorkerStatus.from_domain(
            record.status if record is not None else None,
            open_leave.status if open_leave is not None else None,
        )


def face_result_row(decision: FaceGateDecision) -> dict[str, str]:
    """`FaceGateDecision` → `FaceVerificationOverlay.set_result()` sözlüyü.

    Açarlar HƏM canlı yol (bu funksiya), HƏM maket
    (`preview_data.FACE_VERIFICATION_RESULTS`) üçün EYNİDİR — CLAUDE.md §6.
    İki ad məkanı qursaydıq, uyğunsuzluq maketdə görünməz qalar və yalnız
    istehsalatda, üzü tanınmayan işçinin qarşısında üzə çıxardı.

    HƏRƏKƏT MƏTNİ BURADA SEÇİLMİR (bənd 6): `decision.liveness_action`
    serverdə `secrets.choice` ilə seçilib və `prompt_az` onun Azərbaycanca
    qarşılığıdır. Ekran/kontroller heç bir hərəkət siyahısı saxlamır.

    BAL TAM ƏDƏDƏ YUVARLAQLAŞDIRILIR: `confidence_score` `NUMERIC(5,2)`-dir
    («84.37»), lakin kioskda duran işçi üçün iki onluq rəqəm heç bir məna
    daşımır — qərar onsuz da MƏSAFƏ üzərində verilib (`FaceToleranceBand`).
    """
    gesture = decision.liveness_action.prompt_az if decision.liveness_action is not None else ""
    confidence = (
        f"{decision.confidence_score:.0f}%" if decision.confidence_score is not None else ""
    )
    return {
        "outcome": decision.outcome.value,
        "message": decision.message_az,
        "gesture": gesture,
        "confidence": confidence,
        # YENİDƏN CƏHD YALNIZ `RETRY`-də: `BLOCKED`/`LOCKED` halında düymə
        # göstərmək işçini uyğunsuzluq sayğacını artırmağa dəvət etmək olardı.
        "retry": "1" if decision.outcome is FaceGateOutcome.RETRY else "0",
    }


__all__ = [
    "BLOCKING_FACE_OUTCOMES",
    "FACE_GATE_UNAVAILABLE",
    "GENERIC_PIN_FAILURE",
    "FaceGate",
    "KioskController",
    "KioskOutcome",
    "face_result_row",
]
