"""İstifadəçi & Rol İdarəetməsi (spesifikasiya bölmə 3 və 5-ci faza, bənd 6).

──────────────────────────────────────────────────────────────────────────────
BU MODUL NƏYİ ƏHATƏ EDİR
──────────────────────────────────────────────────────────────────────────────
    * işçi yaratmaq / redaktə etmək / deaktiv etmək (`can_manage_employees`)
    * admin-vasitəçili şifrə yeniləmə `[Şifrəni Yenilə]` (`can_reset_password`)
    * PIN sıfırlama (`can_reset_pin`)
    * rol təyinatı (`can_manage_roles`)
    * Kamera Operatoru üçün ÇOX-SEÇİMLİ mağaza təyinatı (bölmə 4)

İcazə matrisi (`PermissionMatrix`) BU MODULDA DEYİL — o,
`PermissionHierarchyGuardUseCase`-in işidir və orada bütün iyerarxiya
qoruyucuları var. Burada onu təkrarlamaq həmin qoruyucuların ikinci, zəif
kopyasını yaradardı.

──────────────────────────────────────────────────────────────────────────────
İYERARXİYA QAYDASI BURADA DA TƏTBİQ OLUNUR
──────────────────────────────────────────────────────────────────────────────
Bölmə 3-ün Strict Hierarchy Guard-ı yalnız icazə dəyişikliyinə deyil, İŞÇİ
üzərindəki hər idarəetmə əməliyyatına aiddir: `HR_Admin` `CEO`-nun şifrəsini
sıfırlaya bilməməlidir, əks halda icazə iyerarxiyası şifrə sıfırlama yolu ilə
yan keçilərdi (aşağı rütbəli şəxs yuxarıdakının hesabını ələ keçirir).
`_assert_may_manage()` bunu hər əməliyyatda yoxlayır.

──────────────────────────────────────────────────────────────────────────────
ŞİFRƏ NİYƏ BURADA HASH-LƏNMİR
──────────────────────────────────────────────────────────────────────────────
Hash-ləmə `HashingService`-in (infrastruktur) işidir; bu use case yalnız
"kim kimə nə edə bilər" qaydasını qoruyur və nəticəni `CredentialWriter`
portuna ötürür. Beləliklə Argon2 parametrləri dəyişdikdə burada heç nə
dəyişmir.

──────────────────────────────────────────────────────────────────────────────
DEAKTİV ETMƏ ≠ SİLMƏ
──────────────────────────────────────────────────────────────────────────────
İşçi silinmir — `is_active = False` olur. Səbəb cərimə/xal/audit sətirlərinin
hamısının `employee_id`-yə bağlı olmasıdır: fiziki silmə keçmiş cərimənin
"kimə yazıldığı" sualını cavabsız qoyardı. Üstəlik Dual-Control Deadlock
qoruyucusu (bölmə 3) deaktivləşdirmədən ƏVVƏL işə düşür.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol

from src.domain.entities.employee import Employee
from src.domain.interfaces.ports import EmployeeRepository
from src.domain.value_objects.authorization import (
    DEADLOCK_CRITICAL_FLAGS,
    AuthorizationError,
    SystemRole,
)
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger
from src.shared.text import normalise_decision_text

if TYPE_CHECKING:
    from datetime import date, datetime

    from src.application.use_cases.dual_control_guard import (
        DualControlDeadlockGuardUseCase,
    )
    from src.domain.entities.position import Position
    from src.domain.interfaces.ports import (
        AuditTrail,
        CameraAssignmentRepository,
        Clock,
        FaceEmbeddingRepository,
        Notifier,
        PermissionFlagRepository,
    )
    from src.domain.value_objects.authorization import PermissionFlag
    from src.domain.value_objects.credentials import EmailAddress, Username
    from src.domain.value_objects.identifiers import EmployeeId, StoreId, TenantId

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)
_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

MANAGE_EMPLOYEES_FLAG = "can_manage_employees"
#: Bu, şifrənin ÖZÜ deyil, icazə flag-inin adıdır (ona görə `S105` susdurulur).
RESET_PASSWORD_FLAG = "can_reset_password"  # noqa: S105
RESET_PIN_FLAG = "can_reset_pin"
MANAGE_ROLES_FLAG = "can_manage_roles"

#: Hesabın aktivlik statusunu dəyişən qərarın izahı üçün minimum uzunluq.
#: Layihədəki bütün qərar izahları ilə eyni dəyər və eyni səbəb: «lazım
#: oldu» cümləsi aylar sonra heç nə izah etmir, halbuki bu sətir işçinin
#: sistemə çıxışını açır/bağlayır.
MIN_STATUS_CHANGE_REASON_LENGTH = 10

#: AUDİT MARKERİ — «bu qoruma İŞLƏMƏDİ, çünki portu bağlanmayıb» (AF-5).
#:
#: ──────────────────────────────────────────────────────────────────────────
#: NİYƏ `None` DEYİL
#: ──────────────────────────────────────────────────────────────────────────
#: Bu use case-in beş İSTƏYƏ BAĞLI portu var (`flags`, `deadlock_guard`,
#: `face_embeddings`, `fine_exposure`, `offboarding_signals`) və hər biri
#: `None` olanda müvafiq yoxlama APARILMIR. Nəticə audit sətrinə `None` (və
#: ya boş siyahı) kimi düşürdü — jurnalı oxuyan adam üçün bu, İKİ TAMAMİLƏ
#: FƏRQLİ halın eyni görünüşüdür:
#:     * «yoxlandı, tapılmadı»    — sistem işlədi, nəticə mənfidir;
#:     * «ümumiyyətlə yoxlanmadı» — qoruma həmin quraşdırmada YOX İDİ.
#: Birincisi normal iş, ikincisi isə audit tapıntısıdır. Onları ayırd edə
#: bilməmək fail-OPEN oxunuşudur: aylar sonra «üzü silinibmi?» sualına
#: baxan adam `None` görüb «deməli silinməyib» qərarına gəlir, halbuki
#: həqiqət «bilmirik»dir.
#:
#: Eyni prinsip layihədə artıq yazılıb — `recovery_console.may_open`:
#: NAMƏLUM səbəb ən az etibar edilən haldır və onu «hər şey qaydasındadır»
#: kimi oxumaq olmaz. Sükut deyil, GÖRÜNƏN iz seçilir.
#:
#: Marker MƏTNDİR, `False` DEYİL: `False` «yoxlandı, nəticə mənfi» deməkdir
#: və məhz qarışdırdığımız iki haldan birincisidir.
PORT_NOT_WIRED = "SKIPPED_NO_PORT"


def _audited(value: object, *, checked: bool) -> object:
    """Audit dəyəri: yoxlama aparılıbsa nəticə, aparılmayıbsa AÇIQ marker (AF-5).

    Kiçik köməkçidir, lakin AYRICA yazılır: `X if port is not None else
    PORT_NOT_WIRED` ifadəsi beş yerdə təkrarlanmalı olardı və birində
    unudulmuş şərt məhz AF-5-in şikayət etdiyi sükutu geri gətirərdi.
    """
    return value if checked else PORT_NOT_WIRED


class UserManagementError(KompasOSError):
    """İstifadəçi əməliyyatı qadağandır və ya yararsızdır."""

    user_message = "Bu əməliyyat icra edilə bilmədi."


class EmployeeNotFoundError(UserManagementError):
    user_message = "İşçi tapılmadı."


class CredentialWriter(Protocol):
    """Şifrə/PIN hash-larını yazan mənbə (`PostgresEmployeeRepository` ödəyir).

    Hash-lar `Employee` entity-sinə QOYULMUR (təsadüfən log-a düşməsin deyə),
    ona görə onları yazmaq üçün ayrıca port lazımdır.
    """

    def set_password(
        self, employee_id: EmployeeId, *, raw_password: str, must_change: bool
    ) -> None: ...

    def set_pin(self, employee_id: EmployeeId, *, raw_pin: str) -> None: ...

    def clear_pin_lockout(self, employee_id: EmployeeId) -> None: ...


class EmployeeWriter(EmployeeRepository, Protocol):
    """`EmployeeRepository` + YENİ sətir yaratma.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `save()` YETMİR — VƏ NİYƏ BU, DOMEN PORTUNA ƏLAVƏ EDİLMİR
    ──────────────────────────────────────────────────────────────────────────
    `save()` `UPDATE`-dir: olmayan sətir üçün SIFIR sətir dəyişdirir və heç bir
    xəta vermir. Yəni «Yeni İşçi» axını yaddaşdakı sahtələrdə işləyir, canlı
    bazada isə heç nə yazmırdı — nasazlıq yalnız növbəti xarici açar
    pozuntusunda (`audit_logs.actor_id`) üzə çıxırdı.

    `save()`-i upsert etmək də mümkün deyil: `chk_employee_auth` hər sətrin ən
    azı bir autentifikasiya vasitəsi (`pin_hash`, və ya `username` +
    `password_hash`) İLƏ YARANMASINI tələb edir, `Employee` entity-si isə
    hash saxlamır. Ona görə sətir və sirr BİR ifadədə yazılır — bu, `save()`-in
    genişlənməsi deyil, ayrı əməliyyatdır.

    Xam sirr port sərhədində qalır, heşləmə infrastrukturdadır — `CredentialWriter`
    ilə eyni naxış (yuxarıya bax).
    """

    def create(
        self,
        employee: Employee,
        *,
        raw_password: str | None = None,
        raw_pin: str | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class EmployeeDraft:
    """Yeni/redaktə olunan işçi forması — ekranın topladığı sahələr."""

    first_name: str
    last_name: str
    position: Position
    store_id: StoreId | None = None
    username: Username | None = None
    notification_email: EmailAddress | None = None
    hire_date: date | None = None
    date_of_birth: date | None = None
    profile_photo_url: str | None = None
    #: Kamera Operatoru üçün çox-seçimli mağaza təyinatı (bölmə 4).
    camera_store_ids: tuple[StoreId, ...] = ()


@dataclass(frozen=True)
class OpenFineExposure:
    """Deaktiv ediləcək işçinin AÇIQ maliyyə izi (DEEP-GAP D2).

    "Açıq" o deməkdir ki, sətir hələ SON hala çatmayıb: `PENDING_REVIEW`
    cərimə hələ nəşr olunmayıb (nəşrdən sonra `MonthlyFineReviewUseCase`
    artıq deaktiv işçini avtomatik saxlayır, bax `fine_review.py`), açıq
    etiraz isə HƏLƏ qərar verilməmiş deməkdir. İkisi bir dataclass-dadır,
    çünki hər ikisinin köküsü EYNİDİR: işçi girişsiz qalanda öz tərəfindən
    heç bir addım ata bilmir.
    """

    pending_review_fine_count: int
    open_appeal_count: int

    @property
    def has_any(self) -> bool:
        return self.pending_review_fine_count > 0 or self.open_appeal_count > 0


class OpenFineExposureReader(Protocol):
    """`fines`/`fine_appeals`-dan işçinin açıq sayını oxuyur (yalnız DEAKTİVASİYA ön-yoxlaması).

    `FineRepository`/`FineAppealRepository`-yə birbaşa metod əlavə etmək RƏDD
    EDİLDİ (CLAUDE.md §3-ün `ReportFactProvider` əsaslandırması ilə eyni):
    onları ödəyən HƏR sinif (test sahtələri daxil) dərhal uyğunsuz olardı,
    halbuki bu sual YALNIZ bu axına aiddir.
    """

    def count_open_for_employee(self, employee_id: EmployeeId) -> OpenFineExposure: ...


@dataclass(frozen=True)
class OffboardingSignals:
    """İşdən çıxma anında AÇIQ qalan bağlantılar (HR-4).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ TƏK SORĞU, NİYƏ ALTI AYRI PORT DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Bu siqnalların hamısı EYNİ ana aiddir («bu şəxs indi sistemdən çıxır») və
    hamısı BİR ekranda, BİR siyahıda göstərilir. Altı ayrı port olsaydı,
    deaktivasiya yolu altı ayrı `None` yoxlaması daşıyardı və birinin
    bağlanmaması SÜKUTLA siyahını natamam edərdi — halbuki natamam yoxlama
    siyahısı olmayandan daha təhlükəlidir (admin «hər şey təmizdir» oxuyur).

    `OpenFineExposure` (DEEP-GAP D2) AYRI QALIR və bura BİRLƏŞDİRİLMİR: o,
    ARTIQ mövcuddur, ARTIQ bağlıdır və onun sualı maliyyə izidir. İkisini
    birləşdirmək işləyən bir portu yenidən yazmaq olardı (CLAUDE.md qırmızı
    xətt 1).

    HEÇ BİRİ BLOKLAMIR — bax `OffboardingReview` şərhi.
    """

    #: Hələ bağlanmamış gündaxili icazə (🔵/🟡) — işçi «xaricdə» qalıb.
    open_leave_requests: int = 0
    #: Təhvil verilməmiş/qərar gözləyən tapşırıqlar.
    pending_tasks: int = 0
    #: Tutulmuş, lakin HƏLƏ BAŞ VERMƏMİŞ açıq növbələr — həmin günlər
    #: doldurulmamış qalacaq və heç kim xəbər tutmayacaq.
    upcoming_claimed_shifts: int = 0
    #: İstifadə olunmamış illik məzuniyyət günü (son haqq-hesabın girişi).
    unused_annual_leave_days: Decimal = Decimal("0")
    #: Qüvvədə olan sənəd/müqavilə qeydləri (müddəti bitməmiş).
    active_documents: int = 0
    #: Üz şablonu hələ silinməyibsə `True` (`facecontrol.md` bənd 8).
    has_face_template: bool = False

    @property
    def has_any(self) -> bool:
        return bool(
            self.open_leave_requests
            or self.pending_tasks
            or self.upcoming_claimed_shifts
            or self.unused_annual_leave_days > 0
            or self.active_documents
            or self.has_face_template
        )


class OffboardingSignalReader(Protocol):
    """İşdən çıxma siqnallarını BİR sorğuda oxuyur (HR-4).

    `OpenFineExposureReader` ilə EYNİ naxış və eyni əsaslandırma: mövcud
    repository protokollarına metod əlavə etmək onları ödəyən HƏR sinfi
    (test sahtələri daxil) uyğunsuz edərdi, halbuki bu sual YALNIZ
    deaktivasiya axınına aiddir.
    """

    def read_offboarding_signals(self, employee_id: EmployeeId) -> OffboardingSignals: ...


@dataclass(frozen=True)
class OffboardingReview:
    """Deaktivasiyanın TAM mənzərəsi — işçi + açıq bağlantılar (HR-4).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ BLOKLAMIR
    ──────────────────────────────────────────────────────────────────────────
    `_check_deadlock` və `_check_open_fine_exposure` ilə EYNİ qərar: işdən
    çıxarma HÜQUQİ faktdır və sistem onu «tapşırığın var» deyə dayandıra
    bilməz. Sistemin işi qərarı VERƏNƏ nəyin açıq qaldığını GÖSTƏRMƏKDİR —
    qərar isə insanındır.

    NƏ ÜÇÜN HƏM ƏVVƏL, HƏM SONRA ƏLÇATANDIR: `preview_offboarding()` qərardan
    ƏVVƏL çağırılır (siyahı məhz o zaman faydalıdır), `deactivate_employee()`
    isə eyni strukturu nəticə kimi qaytarır — deaktivasiya ekranı yan keçilib
    birbaşa çağırıla bilər (skript, toplu əməliyyat) və o yolda da siyahı
    audit sətrinə düşməlidir.
    """

    employee: Employee
    signals: OffboardingSignals
    #: `None` = `fine_exposure` portu qoşulmayıb (yoxlama APARILMAYIB).
    fine_exposure: OpenFineExposure | None = None
    #: `None` = deadlock qoruyucusu qoşulmayıb.
    deadlock: Any = None

    @property
    def requires_attention(self) -> bool:
        """Admin-in GÖRMƏLİ olduğu bir şey varmı."""
        if self.signals.has_any:
            return True
        return self.fine_exposure is not None and self.fine_exposure.has_any

    def checklist_az(self) -> tuple[str, ...]:
        """Ekranda sətir-sətir göstərilən yoxlama siyahısı.

        Mətnlər BURADA qurulur, ekranda yox: eyni siyahı həm GUI-də, həm
        audit `after_state`-ində, həm də bildirişdə görünür — üç yerdə üç
        fərqli ifadə ikinci ad məkanı yaradardı (`menu.py` başlığındakı
        qüsurun eynisi).
        """
        lines: list[str] = []
        signals = self.signals
        if signals.open_leave_requests:
            lines.append(f"Bağlanmamış icazə sorğusu: {signals.open_leave_requests}")
        if signals.pending_tasks:
            lines.append(f"Gözləyən tapşırıq: {signals.pending_tasks}")
        if signals.upcoming_claimed_shifts:
            lines.append(
                f"Tutulmuş gələcək açıq növbə: {signals.upcoming_claimed_shifts} "
                f"(həmin günlər boş qalacaq)"
            )
        if signals.unused_annual_leave_days > 0:
            lines.append(
                f"İstifadə olunmamış illik məzuniyyət: {signals.unused_annual_leave_days} gün"
            )
        if signals.active_documents:
            lines.append(f"Qüvvədə olan sənəd/müqavilə: {signals.active_documents}")
        if signals.has_face_template:
            lines.append("Üz şablonu hələ silinməyib")
        if self.fine_exposure is not None and self.fine_exposure.pending_review_fine_count:
            lines.append(f"Nəşr gözləyən cərimə: {self.fine_exposure.pending_review_fine_count}")
        if self.fine_exposure is not None and self.fine_exposure.open_appeal_count:
            lines.append(f"Qərar gözləyən cərimə etirazı: {self.fine_exposure.open_appeal_count}")
        return tuple(lines)


class UserManagementUseCase:
    """İşçi yaratma/redaktə, şifrə & PIN sıfırlama, mağaza təyinatı."""

    def __init__(
        self,
        *,
        employees: EmployeeWriter,
        credentials: CredentialWriter,
        audit: AuditTrail,
        clock: Clock,
        camera_assignments: CameraAssignmentRepository | None = None,
        flags: PermissionFlagRepository | None = None,
        notifier: Notifier | None = None,
        deadlock_guard: DualControlDeadlockGuardUseCase | None = None,
        face_embeddings: FaceEmbeddingRepository | None = None,
        fine_exposure: OpenFineExposureReader | None = None,
        offboarding_signals: OffboardingSignalReader | None = None,
    ) -> None:
        self._employees = employees
        self._credentials = credentials
        self._audit = audit
        self._clock = clock
        self._camera_assignments = camera_assignments
        # Flag kataloqu rol dəyişikliyində anti-fraud override-larını süzmək
        # üçündür (bax `Employee.change_position`). `None` olduqda süzgəc
        # TƏTBİQ EDİLMİR — bu, yalnız kataloqsuz test yollarıdır; istehsalat
        # qrafı onu HƏMİŞƏ ötürür (`composition.py`).
        self._flags = flags
        # PIN/şifrə sıfırlaması sahibinə bildiriş göndərir (bölmə 2, sətir 42).
        self._notifier = notifier
        # Dual-Control deadlock qoruyucusu (bölmə 3, sətir 56). Modul başlığı
        # onun deaktivləşdirmədən ƏVVƏL işə düşdüyünü iddia edirdi, lakin
        # çağırış YOX İDİ — sistemin son təsdiqçisini deaktiv etmək mümkün idi
        # və gözləyən override-lar sonsuza qədər təsdiqsiz qalardı.
        self._deadlock_guard = deadlock_guard
        # ────────────────────────────────────────────────────────────────────
        # `facecontrol.md` BƏND 8 — DEAKTİVASİYADA ÜZ VEKTORU SİLİNİR
        # ────────────────────────────────────────────────────────────────────
        # Sənəd bunu AÇIQ şəkildə "MÖVCUD deaktiv-etmə use case-inin İÇİNƏ
        # əlavə et" kimi tələb edir — ayrı bir təmizləmə işi (gecəlik cron)
        # variantı rədd edildi: onda biometrik məlumat işdən çıxarılmadan
        # SONRA saatlarla, terminal söndürülübsə günlərlə yaşayardı.
        #
        # PORT İSTƏYƏ BAĞLIDIR (`None` = təmizləmə yoxdur): mövcud testlər və
        # Face Control modulu qurulmamış quraşdırmalar bu use case-i portsuz
        # yaradır. `None` halı SÜKUTLA UDULMUR — `deactivate_employee` audit
        # sətrinə `face_embedding_purged` açarını `PORT_NOT_WIRED` markeri ilə
        # yazır (AF-5), yəni "təmizləmə cəhdi edilməyib" faktı jurnalda
        # `False` ("cəhd edildi, vektor yox idi") halından AYIRD EDİLİR.
        self._face_embeddings = face_embeddings
        # DEEP-GAP D2 — deaktivasiyadan ƏVVƏL açıq cərimə/etiraz sayını
        # yoxlayır (`_check_deadlock` ilə EYNİ yerdə, EYNİ "BLOKLAMIR, yalnız
        # görünən edir" fəlsəfəsi). `None` = köhnə kompozisiya, sükutla
        # UDULMUR — `deactivate_employee` audit sətrinə `open_fine_count`/
        # `open_appeal_count` açarlarını `None` kimi yazır.
        self._fine_exposure = fine_exposure
        # HR-4 — `fine_exposure` ilə EYNİ naxış: port yoxdursa siyahı BOŞ
        # gəlir və köhnə davranış DƏYİŞMİR. Boş siyahı «hər şey təmizdir»
        # DEMƏK DEYİL və `OffboardingReview` bunu `signals.has_any` ilə
        # ayırd edə bilir — ekran «yoxlanılmadı» halını göstərməlidir.
        self._offboarding_signals = offboarding_signals

    # ------------------------------- yaratma --------------------------------- #

    def create_employee(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        employee_id: EmployeeId,
        draft: EmployeeDraft,
        initial_password: str | None = None,
        initial_pin: str | None = None,
    ) -> Employee:
        """Yeni işçi — ən azı bir autentifikasiya vasitəsi ilə.

        `Employee` konstruktoru "PIN, VƏ YA istifadəçi adı + şifrə" invariantını
        özü yoxlayır; burada yalnız hansının veriləcəyi həll olunur.
        """
        now = self._clock.now()
        self._require(actor, MANAGE_EMPLOYEES_FLAG, now=now)
        self._assert_may_assign_position(actor, draft.position, now=now)

        employee = Employee(
            employee_id=employee_id,
            tenant_id=tenant_id,
            position=draft.position,
            first_name=draft.first_name,
            last_name=draft.last_name,
            store_id=draft.store_id,
            username=draft.username,
            notification_email=draft.notification_email,
            has_password=initial_password is not None,
            has_pin=initial_pin is not None,
            # Admin ilk şifrəni təyin edirsə, işçi onu DƏYİŞMƏLİDİR (bölmə 2).
            must_change_password=initial_password is not None,
            profile_photo_url=draft.profile_photo_url,
            hire_date=draft.hire_date,
            date_of_birth=draft.date_of_birth,
        )
        self._apply_camera_stores(employee, draft.camera_store_ids, actor=actor)
        # `save()` DEYİL: o, `UPDATE`-dir və olmayan sətri yaratmır — yeni işçi
        # canlı bazada SÜKUTLA yaranmırdı (bax `EmployeeWriter` başlığı).
        # `must_change_password` entity-dədir və `create()` onu yazır, yəni
        # köhnə `set_password(must_change=True)` çağırışı ilə eyni nəticə verir.
        self._employees.create(employee, raw_password=initial_password, raw_pin=initial_pin)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="EMPLOYEE_CREATED",
            entity_type="employee",
            entity_id=employee_id,
            after_state={
                "full_name": employee.full_name,
                "position": draft.position.code,
                "has_password": employee.has_password,
                "has_pin": employee.has_pin,
                "camera_stores": len(draft.camera_store_ids),
            },
        )
        return employee

    # ------------------------------- redaktə --------------------------------- #

    def update_employee(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        employee_id: EmployeeId,
        draft: EmployeeDraft,
    ) -> Employee:
        """Mövcud işçini yeniləyir — rol dəyişikliyi də daxil."""
        now = self._clock.now()
        self._require(actor, MANAGE_EMPLOYEES_FLAG, now=now)

        employee = self._load(employee_id)
        self._assert_may_manage(actor, employee, now=now)

        before: dict[str, object] = {
            "full_name": employee.full_name,
            "position": employee.position.code,
            "store_id": str(employee.store_id) if employee.store_id else None,
        }

        role_changed = employee.position.code != draft.position.code
        removed_overrides: list[str] = []
        if role_changed:
            self._require(actor, MANAGE_ROLES_FLAG, now=now)
            self._assert_may_assign_position(actor, draft.position, now=now)
            # ANTI-FRAUD İNVARİANTI: yeni rolda qadağan olan fərdi override
            # SİLİNİR. Əks halda HR_Admin ikən verilmiş
            # `can_approve_dual_control_override` işçi Mağaza_Menecerinə
            # keçiriləndə qüvvədə qalır və Dual-Control mexanizmi mənasız olur
            # (bax `Employee.change_position` docstring-i).
            removed_overrides = employee.change_position(
                draft.position, catalog=self._flag_catalog()
            )

        employee.first_name = draft.first_name.strip()
        employee.last_name = draft.last_name.strip()
        employee.store_id = draft.store_id
        employee.notification_email = draft.notification_email
        employee.hire_date = draft.hire_date
        employee.date_of_birth = draft.date_of_birth
        if draft.profile_photo_url is not None:
            employee.profile_photo_url = draft.profile_photo_url

        self._apply_camera_stores(employee, draft.camera_store_ids, actor=actor)
        self._employees.save(employee)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="EMPLOYEE_UPDATED",
            entity_type="employee",
            entity_id=employee_id,
            before_state=before,
            after_state={
                "full_name": employee.full_name,
                "position": employee.position.code,
                "store_id": str(employee.store_id) if employee.store_id else None,
                "role_changed": role_changed,
                # Silinən override-lar audit-də AÇIQ görünməlidir: bu, işçinin
                # səlahiyyətinin AZALMASIDIR və mübahisə halında nəyin nə vaxt
                # götürüldüyü sübut edilə bilməlidir.
                #
                # AF-5 — BOŞ SİYAHI BURADA ƏN TƏHLÜKƏLİ SÜKUT İDİ: kataloq
                # portu (`flags`) bağlanmayanda `_flag_catalog()` boş lüğət
                # qaytarır, `change_position` isə HEÇ BİR override-ı silmir və
                # nəticə `[]` olur — yəni «yeni rolda qadağan flag yox idi» ilə
                # «anti-fraud süzgəci ÜMUMİYYƏTLƏ işləmədi» eyni görünürdü.
                # İkincisi o deməkdir ki, HR_Admin ikən verilmiş
                # `can_approve_dual_control_override` Mağaza Menecerinə keçən
                # işçidə QÜVVƏDƏ QALIB — bu, struktur zəmanətin sükutla
                # pozulmasıdır və jurnalda görünməlidir.
                #
                # Rol DƏYİŞMƏYİBSƏ marker YAZILMIR: orada süzgəc «işləmədi»
                # deyil, TƏTBİQ EDİLMİR — boş siyahı düzgün cavabdır.
                "removed_overrides": _audited(
                    removed_overrides,
                    checked=not role_changed or self._flags is not None,
                ),
            },
        )
        if removed_overrides:
            _security_log.warning(
                "ANTI_FRAUD_OVERRIDES_REVOKED",
                extra={
                    "employee_id": str(employee_id),
                    "new_position": employee.position.code,
                    "flags": removed_overrides,
                },
            )
        return employee

    def preview_offboarding(self, *, actor: Employee, employee_id: EmployeeId) -> OffboardingReview:
        """Deaktivasiyadan ƏVVƏL açıq bağlantıların siyahısı (HR-4) — HEÇ NƏ DƏYİŞMİR.

        Siyahı məhz QƏRARDAN ƏVVƏL faydalıdır: «bu işçinin üç gözləyən
        tapşırığı və 12 gün istifadə olunmamış məzuniyyəti var» məlumatı
        deaktivasiyadan SONRA gəlsəydi, admin artıq geri dönüşü olmayan
        addımı atmış olardı.

        Səlahiyyət `deactivate_employee` ilə EYNİDİR (`can_manage_employees` +
        iyerarxiya): siyahı işçinin şəxsi məlumatını (məzuniyyət balansı,
        tapşırıq sayı) açır, yəni ondan zəif qapı arxasında dayana bilməz.
        """
        now = self._clock.now()
        self._require(actor, MANAGE_EMPLOYEES_FLAG, now=now)
        employee = self._load(employee_id)
        self._assert_may_manage(actor, employee, now=now)
        return OffboardingReview(
            employee=employee,
            signals=self._read_offboarding_signals(employee_id),
            fine_exposure=self._check_open_fine_exposure(employee_id),
        )

    def reactivate_employee(
        self, *, tenant_id: TenantId, actor: Employee, employee_id: EmployeeId, reason: str
    ) -> Employee:
        """Deaktiv edilmiş işçini YENİDƏN aktivləşdirir (HR-4) — səbəb MƏCBURİDİR.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ `deactivate_employee`-in TAM SİMMETRİYASI
        ──────────────────────────────────────────────────────────────────────
        Eyni səlahiyyət (`can_manage_employees`), eyni iyerarxiya qapısı, eyni
        audit forması. Fərqli bir qapı seçsəydik («yalnız CEO bərpa edə
        bilər» kimi), deaktivasiya ilə bərpa arasında asimmetriya yaranardı
        və praktikada bu, adminləri bazaya əl ilə müdaxiləyə qaytarardı —
        yəni qorumanı gücləndirmək əvəzinə tamamilə yan keçərdi.

        ÖZ HESABI İSTİSNASI BURADA YOXDUR (deaktivasiyadan fərqli olaraq):
        deaktiv işçi giriş edə bilmir, deməli öz hesabını özü bərpa etmək
        fiziki olaraq mümkün deyil və süni qapı əlavə etmək mənasız olardı.

        SƏBƏB MƏCBURİDİR: «niyə geri qayıtdı?» sualının cavabı yalnız audit
        sətrində qala bilər — `deactivate_employee`-in `reason` parametri ilə
        eyni əsaslandırma.
        """
        now = self._clock.now()
        self._require(actor, MANAGE_EMPLOYEES_FLAG, now=now)

        employee = self._load(employee_id)
        self._assert_may_manage(actor, employee, now=now)
        cleaned = normalise_decision_text(reason)
        if len(cleaned) < MIN_STATUS_CHANGE_REASON_LENGTH:
            raise UserManagementError(
                f"Bərpa səbəbi minimum {MIN_STATUS_CHANGE_REASON_LENGTH} simvol olmalıdır",
                user_message="Hesabın niyə bərpa olunduğunu ətraflı yazın.",
                context={"employee_id": str(employee_id)},
            )

        if not employee.activate():
            # İDEMPOTENT: artıq aktiv hesab XƏTA DEYİL, lakin audit sətri də
            # YAZILMIR — heç nə dəyişmədiyi halda «bərpa edildi» sətri
            # jurnalı yanıldardı (`Employee.activate` şərhi).
            return employee

        self._employees.save(employee)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="EMPLOYEE_REACTIVATED",
            entity_type="employee",
            entity_id=employee_id,
            before_state={"is_active": False},
            after_state={"is_active": True},
            reason=cleaned,
        )
        _security_log.info(
            "EMPLOYEE_REACTIVATED",
            extra={"actor_id": str(actor.id), "employee_id": str(employee_id)},
        )
        # ÜZ ŞABLONU BƏRPA OLUNMUR — deaktivasiyada SİLİNİB
        # (`facecontrol.md` bənd 8) və silinmiş biometrik məlumatı geri
        # gətirmək mümkün deyil. İşçi yenidən qeydiyyatdan keçməlidir; bu,
        # itki deyil, bəndin MƏQSƏDİDİR.
        self._notify_owner(
            tenant_id=tenant_id,
            employee_id=employee_id,
            title="Hesabınız bərpa edildi",
            body=(
                f"Hesabınız yenidən aktivləşdirildi. Səbəb: {cleaned}. "
                f"Üzlə giriş istifadə edirdinizsə, yenidən qeydiyyatdan keçməlisiniz."
            ),
        )
        return employee

    def deactivate_employee(
        self, *, tenant_id: TenantId, actor: Employee, employee_id: EmployeeId, reason: str
    ) -> OffboardingReview:
        """İşçini deaktiv edir — SİLMİR (modul başlığına bax).

        ──────────────────────────────────────────────────────────────────────
        İMZA DƏYİŞİKLİYİ (HR-4): `Employee` ƏVƏZİNƏ `OffboardingReview`
        ──────────────────────────────────────────────────────────────────────
        İşçinin özü `review.employee`-dədir, yəni məlumat İTMİR. Dəyişikliyin
        səbəbi budur: deaktivasiya altı ayrı açıq bağlantı yaradır (icazə,
        tapşırıq, tutulmuş növbə, məzuniyyət balansı, sənəd, üz şablonu) və
        onların HEÇ BİRİ soruşulmurdu. Nəticə real mağazada belə görünürdü —
        işçi çıxır, onun tutduğu növbə heç kimə keçmir, gözləyən tapşırığı
        əbədi «icrada» qalır, istifadə olunmamış məzuniyyəti son haqq-hesaba
        düşmür.

        BLOKLAMIR (bax `OffboardingReview` şərhi): siyahı göstərilir, qərar
        insanındır.
        """
        now = self._clock.now()
        self._require(actor, MANAGE_EMPLOYEES_FLAG, now=now)

        employee = self._load(employee_id)
        self._assert_may_manage(actor, employee, now=now)

        if employee.id == actor.id:
            raise UserManagementError(
                "İstifadəçi öz hesabını deaktiv edə bilməz — sistemin son adminini itirmək riski",
                user_message="Öz hesabınızı deaktiv edə bilməzsiniz.",
            )

        deadlock = self._check_deadlock(tenant_id, subject=employee)
        # DEEP-GAP D2 — `_check_deadlock` İLƏ EYNİ YERDƏ: hər ikisi
        # deaktivasiyanın "geri dönüşü olmayan" nəticələrini ƏVVƏLCƏDƏN
        # görünən edir. BLOKLAMIR: son haqq-hesab, əl ilə HR qərarı kimi
        # meşru yollar deaktivasiyanı gözləyə bilməz.
        exposure = self._check_open_fine_exposure(employee_id)
        # HR-4 — siqnallar MUTASİYADAN ƏVVƏL oxunur: `deactivate()`-dən sonra
        # oxusaydıq, «açıq icazə» sorğusu artıq bağlanmış ola bilərdi (repo
        # süzgəci `is_active`-ə baxa bilər) və siyahı boş görünərdi.
        signals = self._read_offboarding_signals(employee_id)
        employee.deactivate()
        self._employees.save(employee)
        purged = self._purge_face_embedding(actor=actor, employee_id=employee_id, reason=reason)
        review = OffboardingReview(
            employee=employee,
            # Üz şablonu ARTIQ silinibsə siyahıda görünməməlidir: `purged`
            # `True` olanda bağlantı BAĞLANIB, açıq qalmayıb.
            signals=(signals if not purged else replace(signals, has_face_template=False)),
            fine_exposure=exposure,
            deadlock=deadlock,
        )
        review_checklist = review.checklist_az()

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="EMPLOYEE_DEACTIVATED",
            entity_type="employee",
            entity_id=employee_id,
            before_state={"is_active": True},
            # AF-5 — HƏR İSTƏYƏ BAĞLI YOXLAMA ÖZ NƏTİCƏSİNİ AÇIQ YAZIR.
            # `None`/boş siyahı ARTIQ İŞLƏDİLMİR: bağlanmamış port
            # `PORT_NOT_WIRED` markeri buraxır, yəni «yoxlandı, tapılmadı»
            # ilə «yoxlanmadı» jurnalda ayırd edilə bilir (bax həmin sabitin
            # şərhi).
            after_state={
                "is_active": False,
                # Deadlock vəziyyəti audit-də görünməlidir: sonradan "niyə
                # override-lar təsdiqsiz qaldı" sualının cavabı budur.
                "dual_control_approvers_left": _audited(
                    deadlock.approver_count if deadlock is not None else None,
                    checked=deadlock is not None,
                ),
                # `facecontrol.md` bənd 8 — biometrik məlumatın silinməsi
                # auditdə GÖRÜNMƏLİDİR: "işçi çıxarıldı, üzü nə vaxt silindi?"
                # sualının yeganə cavabı budur.
                "face_embedding_purged": _audited(purged, checked=purged is not None),
                # DEEP-GAP D2 — "niyə bu cərimə etiraz edilə bilmədi" sualının
                # cavabı: deaktivasiya anında NEÇƏ sətir açıq idi.
                "open_fine_count": _audited(
                    exposure.pending_review_fine_count if exposure is not None else None,
                    checked=exposure is not None,
                ),
                "open_appeal_count": _audited(
                    exposure.open_appeal_count if exposure is not None else None,
                    checked=exposure is not None,
                ),
                # HR-4 — açıq bağlantılar audit sətrində QALIR: bildiriş uçur,
                # sətir qalır və «niyə həmin növbə boş qaldı?» sualının
                # cavabı aylar sonra da buradan oxunur. BOŞ SİYAHI BURADA
                # XÜSUSİLƏ YANILDICI İDİ — o, «heç nə açıq qalmayıb» kimi
                # oxunurdu, halbuki port bağlanmayanda siyahı HƏMİŞƏ boş olur.
                "offboarding_open_items": _audited(
                    list(review_checklist),
                    checked=self._offboarding_signals is not None,
                ),
            },
            reason=reason,
        )
        _security_log.info(
            "EMPLOYEE_DEACTIVATED",
            extra={"actor_id": str(actor.id), "employee_id": str(employee_id)},
        )
        if exposure is not None and exposure.has_any:
            self._notify_open_fine_exposure(
                tenant_id=tenant_id, employee=employee, exposure=exposure
            )
        if review.signals.has_any:
            self._notify_offboarding_items(
                tenant_id=tenant_id, employee=employee, checklist=review_checklist
            )
        return review

    def _read_offboarding_signals(self, employee_id: EmployeeId) -> OffboardingSignals:
        """`offboarding_signals` portu yoxdursa BOŞ siqnal — köhnə davranış (HR-4)."""
        if self._offboarding_signals is None:
            return OffboardingSignals()
        return self._offboarding_signals.read_offboarding_signals(employee_id)

    def _notify_offboarding_items(
        self, *, tenant_id: TenantId, employee: Employee, checklist: tuple[str, ...]
    ) -> None:
        """Açıq bağlantılar barədə xəbərdarlıq — `_notify_open_fine_exposure` naxışı.

        AYRI BİLDİRİŞDİR, cərimə sətrinə qatılmır: auditoriyaları FƏRQLİDİR.
        Cərimə xəbərdarlığı `can_publish_fines` sahibinə gedir (yalnız o,
        sətri bağlaya bilər), bu isə işçi idarəetməsinə — tapşırığı yenidən
        təyin edən, növbəni dolduran və son haqq-hesabı bağlayan tərəfə.
        """
        if self._notifier is None or not checklist:
            return
        lines = "\n".join(f"• {line}" for line in checklist)
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=None,
            category="EMPLOYEE_DEACTIVATED_WITH_OPEN_ITEMS",
            title_az="Deaktiv edilən işçinin açıq bağlantıları var",
            body_az=(f"{employee.full_name} deaktiv edildi. Bağlanmamış qalan sətirlər:\n{lines}"),
            is_critical=False,
        )

    def _check_open_fine_exposure(self, employee_id: EmployeeId) -> OpenFineExposure | None:
        """`fine_exposure` portu yoxdursa (`None`) YOXLAMA APARILMIR — köhnə davranış."""
        if self._fine_exposure is None:
            return None
        return self._fine_exposure.count_open_for_employee(employee_id)

    def _notify_open_fine_exposure(
        self, *, tenant_id: TenantId, employee: Employee, exposure: OpenFineExposure
    ) -> None:
        """`can_publish_fines` sahiblərinə bildiriş (auditoriya `value_objects/notifications.py`).

        BLOKLAMIR — `_check_deadlock`-un öz bildirişi ilə eyni fəlsəfə: sətrin
        özü audit-də onsuz da qalıcıdır, bildiriş yalnız gözdən qaçmamasına
        kömək edir.
        """
        if self._notifier is None:
            return
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=None,
            category="EMPLOYEE_DEACTIVATED_WITH_OPEN_FINES",
            title_az="Deaktiv edilən işçinin açıq cərimələri var",
            body_az=(
                f"{employee.first_name} {employee.last_name} deaktiv edildi. "
                f"{exposure.pending_review_fine_count} nəşr gözləyən cərimə və "
                f"{exposure.open_appeal_count} qərar gözləyən etiraz açıq qalıb — "
                f"əl ilə qərar tələb olunur."
            ),
            is_critical=True,
        )

    def _purge_face_embedding(
        self, *, actor: Employee, employee_id: EmployeeId, reason: str
    ) -> bool | None:
        """Üz vektorunu HƏMİN ANDA silir (`facecontrol.md` bənd 8).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ İSTİSNA UDULMUR
        ──────────────────────────────────────────────────────────────────────
        Burada `try/except` YOXDUR və bu, qəsdlidir: silmə uğursuz olarsa
        bütün deaktivasiya geri qayıtmalıdır (audit yazısının qaydası ilə eyni
        fəlsəfə, CLAUDE.md §5). Əks halda işçi "çıxarılmış" görünər, biometrik
        vektoru isə bazada qalardı — yəni məcburi olan bir şey sükutla
        buraxılmış olardı.

        SİLMƏ `save()`-DƏN SONRADIR: `is_active = FALSE` yazılmadan vektoru
        silmək, tranzaksiya sonra çöksə, "aktiv işçi, üzü silinmiş" vəziyyəti
        yaradardı. İkisi eyni tranzaksiyadadır (sessiya commit edir), yəni
        rollback halında heç biri baş vermir.

        Returns:
            `True/False` — silinəcək vektor var idimi; `None` = port
            qoşulmayıb (Face Control quraşdırılmayıb).
        """
        if self._face_embeddings is None:
            return None
        return self._face_embeddings.purge(
            employee_id,
            purged_by=actor.id,
            reason=f"İşçi deaktiv edildi: {reason}",
            purged_at=self._clock.now(),
        )

    # -------------------------- şifrə & PIN sıfırlama ------------------------ #

    def reset_password(
        self, *, tenant_id: TenantId, actor: Employee, employee_id: EmployeeId, new_password: str
    ) -> None:
        """ "[Şifrəni Yenilə]" — admin-vasitəçili sıfırlama (bölmə 2).

        Yeni şifrə HƏMİŞƏ `must_change=True` ilə yazılır: adminin bildiyi
        şifrə daimi qalsaydı, hesab faktiki olaraq iki nəfərə aid olardı və
        audit izi "kim etdi" sualına cavab verə bilməzdi.
        """
        now = self._clock.now()
        self._require(actor, RESET_PASSWORD_FLAG, now=now)
        self._assert_not_self(actor, employee_id, operation="şifrə")

        employee = self._load(employee_id)
        self._assert_may_manage(actor, employee, now=now)

        self._credentials.set_password(employee_id, raw_password=new_password, must_change=True)
        employee.has_password = True
        employee.must_change_password = True
        self._employees.save(employee)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="PASSWORD_RESET_BY_ADMIN",
            entity_type="employee",
            entity_id=employee_id,
            after_state={"must_change_password": True},
        )
        _security_log.warning(
            "PASSWORD_RESET_BY_ADMIN",
            extra={"actor_id": str(actor.id), "employee_id": str(employee_id)},
        )
        self._notify_owner(
            tenant_id=tenant_id,
            employee_id=employee_id,
            title="Şifrəniz sıfırlandı",
            body=(
                "Admin şifrənizi müvəqqəti şifrə ilə əvəz etdi və ilk girişdə "
                "onu dəyişməlisiniz. Bu, sizin xahişinizlə olmayıbsa dərhal "
                "rəhbərliyinizə məlumat verin."
            ),
        )

    def reset_pin(
        self, *, tenant_id: TenantId, actor: Employee, employee_id: EmployeeId, new_pin: str
    ) -> None:
        """PIN sıfırlama — YALNIZ HR_Admin/Root (bölmə 2).

        Lockout da təmizlənir: işçi 5 səhv cəhddən sonra bloklanıbsa, yeni PIN
        ona kömək etməzdi — 15 dəqiqə hələ də gözləməli olardı.
        """
        now = self._clock.now()
        self._require(actor, RESET_PIN_FLAG, now=now)
        self._assert_not_self(actor, employee_id, operation="PIN")

        employee = self._load(employee_id)
        self._assert_may_manage(actor, employee, now=now)

        self._credentials.set_pin(employee_id, raw_pin=new_pin)
        self._credentials.clear_pin_lockout(employee_id)
        employee.has_pin = True
        self._employees.save(employee)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="PIN_RESET_BY_ADMIN",
            entity_type="employee",
            entity_id=employee_id,
        )
        _security_log.warning(
            "PIN_RESET_BY_ADMIN",
            extra={"actor_id": str(actor.id), "employee_id": str(employee_id)},
        )
        self._notify_owner(
            tenant_id=tenant_id,
            employee_id=employee_id,
            title="PIN-iniz sıfırlandı",
            body=(
                "Admin PIN kodunuzu sıfırladı. Bu, sizin xahişinizlə olmayıbsa "
                "dərhal rəhbərliyinizə məlumat verin."
            ),
        )

    # ------------------------ kamera mağaza təyinatı ------------------------- #

    def assign_camera_stores(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        employee_id: EmployeeId,
        store_ids: tuple[StoreId, ...],
    ) -> Employee:
        """Kamera Operatoruna mağaza(lar) təyin edir (bölmə 4, çox-seçimli).

        BOŞ siyahı icazəlidir və mənası "heç nə görməsin"dir — fail-safe
        istiqamət budur (`CameraAssignmentRepository` izahına bax).
        """
        now = self._clock.now()
        self._require(actor, MANAGE_EMPLOYEES_FLAG, now=now)

        employee = self._load(employee_id)
        self._assert_may_manage(actor, employee, now=now)
        self._apply_camera_stores(employee, store_ids, actor=actor)
        self._employees.save(employee)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="CAMERA_STORES_ASSIGNED",
            entity_type="employee",
            entity_id=employee_id,
            after_state={"store_count": len(store_ids)},
        )
        return employee

    # ------------------------------- köməkçilər ------------------------------ #

    def _apply_camera_stores(
        self, employee: Employee, store_ids: tuple[StoreId, ...], *, actor: Employee
    ) -> None:
        """Təyinatı entity-yə və (varsa) repository-yə yazır."""
        if employee.position.effective_system_role is not SystemRole.CAMERA_OPERATOR:
            if store_ids:
                raise UserManagementError(
                    "Çox-mağazalı təyinat yalnız Kamera Nəzarətçisi üçündür",
                    user_message="Bu rol üçün çoxlu mağaza təyin edilə bilməz.",
                    context={"role": employee.position.code},
                )
            return

        for previous in employee.assigned_store_ids:
            employee.unassign_store(previous)
        for store_id in store_ids:
            employee.assign_store(store_id)
            if self._camera_assignments is not None:
                self._camera_assignments.assign(employee.id, store_id, assigned_by=actor.id)

    def _check_deadlock(self, tenant_id: TenantId, *, subject: Employee) -> Any:
        """Kritik səlahiyyətin SON daşıyıcısı itirilirsə XƏBƏRDARLIQ verir (bölmə 3, 56).

        BLOKLAMIR — spesifikasiya "xəbərdarlıq göstərilir" deyir, qadağa yox.
        Bloklamaq son HR_Admin-i işdən çıxaran şirkətdə istifadəçi silməyi
        tamamilə mümkünsüz edərdi; xəbərdarlıq isə problemi görünən edir.
        Bildirişi qoruyucunun özü göndərir (`Notifier` ona verilib).

        ──────────────────────────────────────────────────────────────────────
        AF-8 — NİYƏ ARTIQ ROL ADINA BAXMIR
        ──────────────────────────────────────────────────────────────────────
        Əvvəlki şərt `effective_system_role in (HR_ADMIN, CEO, ROOT)` idi.
        `effective_system_role` custom rolu PRİORİTETƏ görə xəritələyir, lakin
        nəticə həmişə həmin üç ENUM üzvündən biri OLMUR — CEO-nun yaratdığı
        «Filial Rəhbəri» tipli custom rol prioritet-3-də qalır və şərt onu
        GÖRMÜRDÜ. Nəticədə həmin rolda oturan YEGANƏ təsdiqçi deaktiv
        ediləndə heç bir xəbərdarlıq çıxmırdı.

        İndi sual ROL yox, SƏLAHİYYƏT üzərindən verilir: «bu şəxs hansı kritik
        flagları HAZIRDA daşıyır?». `has_permission()` rol-defoltunu və fərdi
        override-ı birlikdə həll etdiyi üçün custom rol da, fərdi `GRANT` da
        düzgün sayılır — yəni cavab flag kataloqunun ÖZÜNDƏN gəlir, kodda
        təkrarlanan rol siyahısından yox (CLAUDE.md §5: ikinci ad məkanı
        yaradılmır).
        """
        if self._deadlock_guard is None:
            return None
        now = self._clock.now()
        losing = [flag for flag in DEADLOCK_CRITICAL_FLAGS if subject.has_permission(flag, now=now)]
        return self._deadlock_guard.check_before_flag_loss(tenant_id, losing_flags=losing)

    @staticmethod
    def _assert_not_self(actor: Employee, employee_id: EmployeeId, *, operation: str) -> None:
        """Öz PIN/şifrəsini BU AXINLA sıfırlamaq qadağandır (bölmə 2, sətir 42).

        SEC-016 TOTP-ni çıxaranda onun yerini üç struktur qorunma tutdu və
        BİRİNCİSİ məhz budur: sıfırlamanı HƏMİŞƏ BAŞQA autentifikasiya olunmuş
        admin edir, yəni vəzifə ayrılığı qorunur. Əks halda `can_reset_pin`
        sahibi öz lockout-unu özü açardı (`clear_pin_lockout` bu axındadır) —
        yəni 5 səhv cəhd + 15 dəqiqəlik bloklama qaydası öz-özünə yan keçilərdi.

        Öz şifrəsini dəyişmək AYRI axındır (`CredentialResetUseCase`) və orada
        köhnə şifrənin bilinməsi tələb olunur.
        """
        if actor.id != employee_id:
            return
        _security_log.warning(
            "SELF_CREDENTIAL_RESET_BLOCKED",
            extra={"actor_id": str(actor.id), "operation": operation},
        )
        raise UserManagementError(
            f"İstifadəçi öz {operation} məlumatını bu axınla sıfırlaya bilməz "
            f"— sıfırlamanı başqa admin etməlidir (bölmə 2)",
            user_message=(
                f"Öz {operation} məlumatınızı bu ekrandan sıfırlaya bilməzsiniz. "
                f"Başqa admin müraciət etməlidir."
            ),
        )

    def _notify_owner(
        self, *, tenant_id: TenantId, employee_id: EmployeeId, title: str, body: str
    ) -> None:
        """Sıfırlamadan sahibin XƏBƏRİ olmalıdır (bölmə 2, sətir 42).

        Bildiriş uğursuz olarsa əməliyyat GERİ QAYTARILMIR: sıfırlama artıq baş
        verib və onu ləğv etmək işçini girişsiz qoyardı. Audit yazısından
        fərqi budur — audit məcburidir, bildiriş isə xəbərdarlıqdır.
        """
        if self._notifier is None:
            return
        try:
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=employee_id,
                category="CREDENTIAL_RESET",
                title_az=title,
                body_az=body,
                is_critical=True,
            )
        except Exception:
            _security_log.exception(
                "CREDENTIAL_RESET_NOTIFY_FAILED", extra={"employee_id": str(employee_id)}
            )

    def _flag_catalog(self) -> dict[str, PermissionFlag]:
        """`kod → PermissionFlag` — rol dəyişikliyində süzgəc üçün.

        Kataloq verilməyibsə BOŞ lüğət qaytarılır: `change_position` naməlum
        flag-ə toxunmur, yəni davranış əvvəlki kimi qalır. Bu, qəsdən
        fail-open-dur — kataloqa çatmamaq rol dəyişikliyini bloklamamalıdır,
        lakin istehsalat qrafı kataloqu HƏMİŞƏ verir.
        """
        if self._flags is None:
            return {}
        return {flag.code: flag for flag in self._flags.list_all()}

    def _load(self, employee_id: EmployeeId) -> Employee:
        employee = self._employees.get(employee_id)
        if employee is None:
            raise EmployeeNotFoundError(
                f"İşçi tapılmadı: {employee_id}", context={"employee_id": str(employee_id)}
            )
        return employee

    def _require(self, actor: Employee, flag: str, *, now: datetime) -> None:
        if not actor.has_permission(flag, now=now):
            _security_log.warning(
                "USER_MANAGEMENT_DENIED",
                extra={"actor_id": str(actor.id), "flag": flag},
            )
            raise UserManagementError(
                f"«{flag}» səlahiyyəti yoxdur",
                user_message="Bu əməliyyat üçün səlahiyyətiniz yoxdur.",
                context={"flag": flag},
            )

    @staticmethod
    def _assert_may_manage(actor: Employee, subject: Employee, *, now: datetime) -> None:
        """STRICT HIERARCHY GUARD — modul başlığındakı izaha bax.

        Öz-özünə tətbiq olunmur: istifadəçi öz profilini redaktə edə bilər
        (`EmployeeProfileUseCase`), lakin ora ayrı yoldur.
        """
        if actor.id == subject.id:
            return
        if not actor.outranks(subject):
            _security_log.warning(
                "USER_MANAGEMENT_HIERARCHY_BLOCKED",
                extra={
                    "actor_id": str(actor.id),
                    "actor_priority": actor.priority.value,
                    "subject_id": str(subject.id),
                    "subject_priority": subject.priority.value,
                },
            )
            raise AuthorizationError(
                "STRICT HIERARCHY GUARD: eyni və ya daha yüksək pillədəki "
                "istifadəçini idarə etmək olmaz (bölmə 3)",
                user_message="Bu istifadəçini idarə etmək səlahiyyətiniz yoxdur.",
                context={"subject_id": str(subject.id)},
            )

    @staticmethod
    def _assert_may_assign_position(actor: Employee, position: Position, *, now: datetime) -> None:
        """Aktor ÖZÜNDƏN yüksək (və ya bərabər) rol təyin edə bilməz.

        Bu, iyerarxiyanın "yaratma" tərəfindəki qapağıdır: onsuz `HR_Admin`
        yeni bir `Root` yaradıb həmin hesabla daxil ola bilərdi.
        """
        if not actor.position.outranks(position):
            _security_log.warning(
                "POSITION_ASSIGNMENT_BLOCKED",
                extra={"actor_id": str(actor.id), "position": position.code},
            )
            raise AuthorizationError(
                "Özündən yüksək və ya bərabər pilləli rol təyin edilə bilməz (bölmə 3)",
                user_message="Bu vəzifəni təyin etmək səlahiyyətiniz yoxdur.",
                context={"position": position.code},
            )


__all__ = [
    "MANAGE_EMPLOYEES_FLAG",
    "MANAGE_ROLES_FLAG",
    "PORT_NOT_WIRED",
    "RESET_PASSWORD_FLAG",
    "RESET_PIN_FLAG",
    "CredentialWriter",
    "EmployeeDraft",
    "EmployeeNotFoundError",
    "UserManagementError",
    "UserManagementUseCase",
]
