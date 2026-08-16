"""Face Control (Üz Təsdiqi) domen tipləri — `facecontrol.md` Faza 2.

Bu modul üz təsdiqi qatının DİLİNİ təyin edir: kadr nədir (`FaceFrame`),
vektor nədir (`FaceEmbedding`), müqayisənin nəticəsi hansı dəyərləri ala bilər
(`FaceVerificationResult`), hədd zolağı necə hesablanır (`FaceToleranceBand`)
və istisna (`FaceExemption`) hansı vəziyyətlərdən keçir.

──────────────────────────────────────────────────────────────────────────────
KİTABXANA BURADA YOXDUR VƏ OLMAYACAQ
──────────────────────────────────────────────────────────────────────────────
`face_recognition` (Dlib) İDXAL EDİLMİR. Domen qatı yalnız `FaceMatcher`
portunu (`interfaces/ports.py`) görür; alignment (bənd 10), landmark
aşkarlaması və məsafə hesablaması infrastruktur adapterinin işidir. Səbəb
CLAUDE.md §3-ün qat sırasıdır, lakin burada əlavə bir səbəb də var: biometrik
qaydaların (hədd zolağı, kilid sayğacı, istisna müddəti) testi ağır bir
kitabxananın quraşdırılmasından ASILI OLMAMALIDIR — əks halda anti-fraud
məntiqi yalnız `face_recognition` qurulmuş maşında yoxlanardı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ KADR VƏ VEKTOR `__repr__`-i MASKALANIB
──────────────────────────────────────────────────────────────────────────────
`migrations/047` başlığındakı dörd qaydadan biri "log-larda embedding, kadr,
ya da onların hissəsi GÖRÜNMÜR"dir. Python-da bu qayda ən çox TƏSADÜFƏN
pozulur: bir `logger.info(..., extra={"sample": sample})`, bir `pytest` diff-i
və ya `repr()` çağıran bir istisna izi vektoru mətn faylına tökər. Ona görə
qoruma sinifin ÖZÜNDƏDİR (`KeyMaterial.__repr__` ilə eyni qərar) — çağıran
tərəfin diqqətinə buraxılmır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `FaceExemption` DONMUŞ (`frozen`) DƏYƏR OBYEKTİDİR, AQREQAT DEYİL
──────────────────────────────────────────────────────────────────────────────
`AggregateRoot` (hadisə toplama, `collect_events`) yalnız hadisə YAYAN
aqreqatlar üçün lazımdır. İstisnanın hadisəsi yoxdur: onun bütün yan təsirləri
(audit sətri, bildiriş, dual-control tələbi) use case-dədir. Donmuş dəyər
obyekti isə bir şeyi struktur olaraq təmin edir — `status` sahəsini "əl ilə"
`REVOKED` etmək və `revoked_by`-ı boş qoymaq MÜMKÜN DEYİL: keçid yalnız
`revoked()`/`expired()` metodlarından keçir və hər ikisi DB `CHECK`-inin
(`chk_face_exemption_revocation`) tələb etdiyi sahələri birlikdə doldurur.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Final

from src.domain.value_objects.scheduling import require_aware
from src.shared.exceptions import KompasOSError

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from src.domain.value_objects.identifiers import (
        EmployeeId,
        FaceExemptionId,
        StoreId,
        TenantId,
    )

#: Bal 0–100 aralığında saxlanılır (`face_verification_log.confidence_score`
#: sütunu `NUMERIC(5,2)` + `CHECK (0..100)`). Bu, sxem məhdudiyyətinin
#: güzgüsüdür, biznes həddi DEYİL — ona görə `system_limits`-ə aid deyil
#: (`MIN_SOURCE_CODE_LENGTH` ilə eyni qərar).
MAX_CONFIDENCE_PERCENT: Final[float] = 100.0


class FaceControlError(KompasOSError):
    """Üz təsdiqi qatının domen qaydası pozulub."""

    user_message = "Üz təsdiqi əməliyyatı icra edilə bilmədi."


class FaceVerificationResult(str, Enum):
    """`face_verification_log.result` — sxem `CHECK` siyahısı ilə EYNİ.

    İKİ UĞURSUZLUQ REJİMİ QƏSDƏN AYRILIB (`facecontrol.md` bənd 3):

    * `NO_FACE_DETECTED` — kamera üzü görmədi. Bu, TEXNİKİ nasazlıqdır (işıq,
      bucaq, çirkli linza) və heç bir sayğaca düşmür.
    * `MISMATCH` — üz göründü, lakin PIN sahibinin qeydiyyatlı üzü ilə uyğun
      gəlmədi. Sistemdəki ƏN GÜCLÜ fırıldaqçılıq siqnalıdır.

    Onları birləşdirmək cazibədar görünürdü ("hər ikisi uğursuzluqdur"), lakin
    o zaman işıqsız dəhlizdə duran vicdanlı işçi üç cəhddən sonra kilidlənərdi
    — sistem "təhlükəsiz" görünüb faktiki olaraq işi dayandırardı.
    """

    SUCCESS = "SUCCESS"
    NO_FACE_DETECTED = "NO_FACE_DETECTED"
    MISMATCH = "MISMATCH"

    @property
    def is_fraud_signal(self) -> bool:
        """Bu nəticə MISMATCH sayğacını artırırmı."""
        return self is FaceVerificationResult.MISMATCH


class FaceTriggerContext(str, Enum):
    """`face_verification_log.trigger_context` — üz təsdiqinin tətbiq nöqtəsi.

    DƏYƏRLƏR MÖVCUD SÖZLÜKDƏNDİR: `morning_check_in.py` və
    `leave_verification.py` artıq `_verified_now(operation="STEP_A"/"STEP_1"/
    "STEP_2")` yazır. Yeni ad məkanı qurmaq (`MORNING_CHECK_IN_STEP_A` kimi)
    `menu.py` başlığındakı qüsurun eynisi olardı: iki siyahı bir müddət
    üst-üstə düşər, sonra sükutla ayrılardı.
    """

    STEP_A = "STEP_A"
    STEP_1 = "STEP_1"
    STEP_2 = "STEP_2"
    #: Kiosk GİRİŞİ — PIN uğurlu olduqdan sonra, İşçi Ana Ekranı AÇILMAZDAN
    #: ƏVVƏL (miqrasiya 057).
    #:
    #: `STEP_A` TƏKRAR İŞLƏDİLMİR: o, «bu gün işə başladı» hadisəsidir və
    #: davamiyyət hesabatının mənbəyidir. Girişi də ora yazsaydıq, gün ərzində
    #: kiosku beş dəfə açan işçi hesabatda beş dəfə «işə başlamış» görünərdi.
    LOGIN = "LOGIN"


class LivenessGesture(str, Enum):
    """Tələb oluna bilən canlılıq hərəkətləri (bənd 6).

    SİYAHI SƏRTDİR, LAKİN AKTİV DƏSTİ DEYİL: hansı hərəkətlərin İSTİFADƏ
    olunduğu `FACE_LIVENESS_ACTIONS` ROOT parametrindədir (vergüllü kataloq).
    Burada yalnız KODUN tanıya bildiyi hərəkətlər sadalanır — hər birinin
    arxasında adapterin ayrı bir aşkarlama alqoritmi durur, yəni yeni dəyər
    buraxılışsız mənasızdır (`ExceptionSeverity` ilə eyni qərar).
    """

    BLINK = "BLINK"
    HEAD_TURN = "HEAD_TURN"
    SMILE = "SMILE"

    @property
    def prompt_az(self) -> str:
        """Kioskda göstərilən göstəriş (interfeys dili Azərbaycancadır)."""
        return _GESTURE_PROMPTS[self]

    @classmethod
    def parse_catalog(cls, raw: str | None) -> tuple[LivenessGesture, ...]:
        """`FACE_LIVENESS_ACTIONS` vergüllü sətrini hərəkət dəstinə çevirir.

        NAMƏLUM DƏYƏR SÜKUTLA ATILIR, İSTİSNA ATMIR: Root sətri əl ilə redaktə
        edib yazı səhvi buraxsa, bütün doğrulama qatı dayanardı
        (`ExceptionSeverity.parse` ilə eyni fəlsəfə). Lakin BOŞ nəticə
        çağıranın işidir — bu metod boş dəst qaytara bilər və
        `FaceVerificationUseCase` onu fail-closed emal edir: liveness qoruması
        SÜKUTLA sönə bilməz.

        Sıra qorunur (`dict.fromkeys`): təsadüfi sıra jurnalda "randomlaşdırma
        işləyirmi?" sualını çətinləşdirərdi, çünki iki icranın hovuzu fərqli
        görünərdi.
        """
        if raw is None:
            return ()
        parsed: list[LivenessGesture] = []
        for token in raw.split(","):
            candidate = token.strip().upper()
            if not candidate:
                continue
            try:
                parsed.append(cls(candidate))
            except ValueError:
                continue
        return tuple(dict.fromkeys(parsed))


_GESTURE_PROMPTS: Final[dict[LivenessGesture, str]] = {
    LivenessGesture.BLINK: "Gözlərinizi qırpın",
    LivenessGesture.HEAD_TURN: "Başınızı yavaşca sağa çevirin",
    LivenessGesture.SMILE: "Gülümsəyin",
}


class FaceExemptionStatus(str, Enum):
    """`face_control_exemptions.status` — sxem `CHECK` siyahısı ilə EYNİ."""

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"

    @property
    def is_open(self) -> bool:
        return self is FaceExemptionStatus.ACTIVE


class FaceArchiveStatus(str, Enum):
    """`face_embedding_history.status` — arxiv sətrinin iki mənası.

    `REPLACED` — vektor SAXLANILIR (yenidən-qeydiyyat, bənd 2).
    `PURGED` — vektor SİLİNİB, yalnız kim/nə vaxt izi qalıb (bənd 8).

    Sxem bu ikisini `CHECK ((status = 'PURGED') = (face_embedding IS NULL))`
    ilə bağlayır: "silindi" deyib vektoru saxlamaq mümkün deyil.
    """

    REPLACED = "REPLACED"
    PURGED = "PURGED"


@dataclass(frozen=True)
class FaceFrame:
    """Kameradan alınmış TƏK kadr — YALNIZ YADDAŞDA yaşayır.

    DİSKƏ YAZILMIR VƏ ŞƏBƏKƏYƏ ÇIXMIR (migrations/047-nin birinci qaydası).
    Bu sinif ona görə var ki, `bytes` tipi bir emal zəncirindən keçəndə heç
    nə onun BİOMETRİK olduğunu xatırlatmır — adı və maskalanmış `__repr__`
    həmin xatırlatmanı struktur edir.
    """

    payload: bytes
    width: int = 0
    height: int = 0

    def __repr__(self) -> str:
        """Kadrın MƏZMUNU heç bir log/traceback/diff-ə düşmür."""
        return f"FaceFrame(bytes={len(self.payload)}, {self.width}x{self.height})"


@dataclass(frozen=True)
class FaceEmbedding:
    """Üzün riyazi təmsili — ŞƏKİL DEYİL və şəklə geri çevrilə bilmir.

    `values` `float` ardıcıllığıdır; ölçüsü kitabxanadan asılıdır (Dlib 128),
    ona görə burada SABİT ölçü YOXDUR — sabit yazsaydıq, kitabxananın
    versiyası dəyişəndə domen qatı da dəyişməli olardı.
    """

    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.values:
            raise FaceControlError(
                "Boş üz vektoru mənasızdır",
                user_message="Üz məlumatı oxuna bilmədi. Yenidən cəhd edin.",
            )

    @property
    def dimension(self) -> int:
        return len(self.values)

    def __repr__(self) -> str:
        """Vektorun ÖZÜ heç bir log/traceback/diff-ə düşmür."""
        return f"FaceEmbedding(dim={self.dimension})"

    @classmethod
    def average(cls, embeddings: Sequence[FaceEmbedding]) -> FaceEmbedding:
        """ÇOX-KADR ORTA ALMA (bənd 11) — enrollment-in istinad vektoru.

        Tək kadrın embedding-i istinad kimi saxlanılsaydı, həmin anın
        təsadüfi işıq/açı xətası ƏBƏDİ istinad nöqtəsinə çevrilərdi və hər
        gün hər doğrulama onunla müqayisə edilərdi. Orta vektor bu xətanı
        kadr sayı qədər azaldır.

        ÖLÇÜ UYĞUNSUZLUĞU SÜKUTLA UDULMUR: fərqli ölçülü vektorların ortası
        riyazi mənasızdır və nəticə "işləyən, lakin heç kimi tanımayan"
        qeydiyyat olardı — yəni qüsur yalnız aylar sonra, kilidlənmiş işçi
        şikayət edəndə görünərdi.
        """
        if not embeddings:
            raise FaceControlError(
                "Orta vektor üçün ən azı bir kadr lazımdır",
                user_message="Keyfiyyət həddini keçən kadr yoxdur. Yenidən çəkin.",
            )
        dimension = embeddings[0].dimension
        if any(item.dimension != dimension for item in embeddings):
            raise FaceControlError(
                "Fərqli ölçülü üz vektorlarının ortası hesablana bilməz",
                user_message="Üz məlumatı uyğunsuzdur. Yenidən çəkin.",
                context={"dimension": dimension, "count": len(embeddings)},
            )
        count = len(embeddings)
        return cls(
            values=tuple(
                sum(item.values[index] for item in embeddings) / count for index in range(dimension)
            )
        )


@dataclass(frozen=True)
class FaceSample:
    """`FaceMatcher.extract()`-in nəticəsi — BİR kadrdan çıxarılan məlumat.

    `embedding is None` = kadrda üz TAPILMADI. Bu hal istisna ilə DEYİL,
    dəyərlə ifadə olunur, çünki o, nasazlıq deyil — gündəlik, gözlənilən
    haldır (bənd 3: texniki problem kimi rəftar et, yenidən cəhd təklif et).
    """

    embedding: FaceEmbedding | None = None
    #: Kadrın keyfiyyət balı (0–1: aydınlıq/işıqlandırma) — `FACE_ENROLLMENT_
    #: MIN_QUALITY` ilə müqayisə olunur.
    quality: float = 0.0
    #: Tələb olunan liveness hərəkəti təsdiqləndimi. Hərəkət tələb
    #: edilməyibsə (enrollment) `True` gəlir — bax `FaceMatcher.extract`.
    liveness_confirmed: bool = True

    @property
    def has_face(self) -> bool:
        return self.embedding is not None

    def meets_quality(self, minimum: float) -> bool:
        return self.has_face and self.quality >= minimum


@dataclass(frozen=True)
class FaceToleranceBand:
    """İki ROOT həddindən qurulan qərar zolağı (bənd 7 + bənd 12).

    VAHİD MƏSAFƏDİR, FAİZ DEYİL (kiçik = daha oxşar) — `face_recognition`
    kitabxanasının öz vahidi. Faizə çevirmə YALNIZ insan üçün, jurnalın
    `confidence_score` sütununda olur; QƏRAR məsafə üzərində verilir ki,
    Root-un gördüyü ədədlə kitabxananın cavabı arasında gizli bir çevirmə
    sabiti oturmasın (migrations/047, `confidence_score` şərhi).

    ──────────────────────────────────────────────────────────────────────────
    TƏRS KONFİQURASİYA — NİYƏ FAIL-CLOSED
    ──────────────────────────────────────────────────────────────────────────
    `FACE_LOW_CONFIDENCE_TOLERANCE ≤ FACE_MATCH_TOLERANCE` şərti İKİ AYRI
    `system_limits` sətrindədir, yəni DB `CHECK`-i ilə ifadə edilə bilmir və
    Root tərs cüt yaza bilər (məs. aşağı-etibar 0.90, bənzərlik 0.60).

    Tərs cütdə "aşağı-etibarlı" zolaq TƏRSİNƏ dönərdi: qəbul sərhədi 0.60-dan
    0.90-a genişlənər və sistem PRAKTİKADA hər üzü qəbul edərdi — üstəlik bu,
    ekranda "sərtləşdirdim" təəssüratı ilə edilərdi. Ona görə burada zolaq
    SÖNDÜRÜLÜR və qəbul sərhədi İKİSİNDƏN SƏRTİNƏ (`min`) endirilir: yanlış
    konfiqurasiya sistemi heç vaxt ZƏİFLƏTMİR, ən pis halda sərtləşdirir.

    "Sükutla düzəlt" variantı (dəyərləri yerini dəyişmək) RƏDD EDİLDİ: Root
    ekranda 0.90 görər, sistem 0.60 tətbiq edərdi — konfiqurasiya ilə davranış
    arasında gizli fərq ən pis nasazlıq formasıdır. `is_inverted` bayrağı məhz
    ona görə var: use case onu log-a və audit-ə yazır.
    """

    match_tolerance: float
    low_confidence_tolerance: float
    #: Zolaq (aşağı-etibarlı təsdiq) FAKTİKİ olaraq işləyirmi.
    band_enabled: bool
    #: Root tərs cüt yazıb və zolaq fail-closed söndürülüb.
    is_inverted: bool = False

    @classmethod
    def resolve(
        cls, *, match_tolerance: float, low_confidence_tolerance: float
    ) -> FaceToleranceBand:
        """İki xam həddən qərar zolağı qurur.

        SIFIR ENLİ ZOLAQ (iki hədd bərabərdir) da söndürülmüş sayılır: orada
        "aşağı-etibarlı" nəticə RİYAZİ olaraq mümkün deyil və `is_low_
        confidence` sütunu heç vaxt `TRUE` olmazdı — bayrağı "işləyir" kimi
        göstərmək Kamera Operatorunda yanlış gözlənti yaradardı.
        """
        inverted = low_confidence_tolerance > match_tolerance
        effective_match = (
            min(match_tolerance, low_confidence_tolerance) if inverted else match_tolerance
        )
        return cls(
            match_tolerance=effective_match,
            low_confidence_tolerance=min(low_confidence_tolerance, effective_match),
            band_enabled=not inverted and low_confidence_tolerance < match_tolerance,
            is_inverted=inverted,
        )

    def classify(self, distance: float) -> tuple[FaceVerificationResult, bool]:
        """Məsafəni nəticə + «aşağı-etibarlı» nişanına çevirir.

        Sərhəd davranışı: `distance == match_tolerance` UYĞUNLUQ sayılır
        (kitabxananın `compare_faces` funksiyası da `<=` işlədir) — əks halda
        Root-un yazdığı ədəd faktiki olaraq bir addım sərt olardı.
        """
        if distance > self.match_tolerance:
            return FaceVerificationResult.MISMATCH, False
        if self.band_enabled and distance > self.low_confidence_tolerance:
            return FaceVerificationResult.SUCCESS, True
        return FaceVerificationResult.SUCCESS, False

    @staticmethod
    def confidence_percent(distance: float) -> float:
        """Məsafənin İNSAN üçün oxunan faiz proyeksiyası (0–100).

        BU ƏDƏD QƏRAR VERMİR — yalnız `face_verification_log.confidence_score`
        sütununa yazılır və ekranda göstərilir. Qərar `classify()`-dadır,
        məsafə üzərində; əks halda çevirmə düsturu özü gizli bir hədd olardı.
        """
        percent = (1.0 - distance) * MAX_CONFIDENCE_PERCENT
        return round(min(MAX_CONFIDENCE_PERCENT, max(0.0, percent)), 2)


@dataclass(frozen=True)
class FaceProfile:
    """İşçinin üz qeydiyyatının cari vəziyyəti (`employees` sətrinin üz sahələri).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `Employee` AQREQATINA SAHƏ ƏLAVƏ EDİLMƏDİ
    ──────────────────────────────────────────────────────────────────────────
    `Employee` sistemin ƏN ÇOX işlədilən aqreqatıdır: hər PIN handshake, hər
    ekran, hər icazə yoxlaması onu yükləyir. Ora `face_embedding` sahəsi
    əlavə etmək o deməkdir ki, şifrələnmiş biometrik vektor bu yolların
    HAMISINDAN keçər — və `repr()`/log/DTO-ya düşmə ehtimalı hər yeni
    ekranla artar. Eyni əsaslandırma layihədə artıq var: PIN/şifrə hash-ları
    da `Employee`-yə QOYULMUR (`user_management.CredentialWriter` başlığı).

    Ona görə üz məlumatı AYRI oxu-modelindədir və yalnız Face Control
    axınında yüklənir.
    """

    employee_id: EmployeeId
    tenant_id: TenantId
    store_id: StoreId | None = None
    embedding: FaceEmbedding | None = None
    enrolled_at: datetime | None = None
    mismatch_attempts: int = 0
    locked_until: datetime | None = None

    def __post_init__(self) -> None:
        if self.enrolled_at is not None:
            require_aware(self.enrolled_at, field="enrolled_at")
        if self.locked_until is not None:
            require_aware(self.locked_until, field="locked_until")

    @property
    def is_enrolled(self) -> bool:
        """Sxem `chk_employee_face_enrollment_pair` ilə eyni invariant."""
        return self.embedding is not None and self.enrolled_at is not None

    def is_locked(self, *, now: datetime) -> bool:
        """Üz kilidi hələ qüvvədədirmi.

        PIN kilidindən (`Employee.is_pin_locked`) TAM AYRIDIR: ikisi müstəqil
        qapıdır və hər ikisi keçilməlidir (migrations/047, `face_locked_until`
        şərhi).
        """
        require_aware(now, field="now")
        return self.locked_until is not None and now < self.locked_until

    def is_stale(self, *, now: datetime, reminder_months: int) -> bool:
        """Qeydiyyat «köhnəlib»mi (bənd 13) — YALNIZ TÖVSİYƏ, BLOKLAMIR.

        İnsan üzü zamanla dəyişir (saqqal, eynək, çəki), lakin bu, işçini
        işdən saxlamaq üçün əsas deyil — `MonthlyLeaveUsage` ilə eyni fəlsəfə:
        xəbərdarlıq göstərilir, iş davam edir.
        """
        require_aware(now, field="now")
        if self.enrolled_at is None or reminder_months <= 0:
            return False
        return now >= add_months(self.enrolled_at, reminder_months)


@dataclass(frozen=True)
class FaceExemption:
    """`face_control_exemptions` sətri — PIN-only istisnası (bənd 14).

    İstisna bir BOŞLUQ yaradır (üz təsdiqi olmadan giriş), ona görə hər sahəsi
    həmin boşluğu daraltmağa xidmət edir: `expires_at` məcburidir, `reason`
    boş ola bilməz, sətir heç vaxt SİLİNMİR.

    KOMPENSASİYA EDİCİ NƏZARƏT BU SİNİFDƏ DEYİL, use case-dədir: istisnalı
    işçinin hər təsdiqi MÖVCUD dual-control axınına düşür. Onu buraya
    yazsaydıq, qayda dəyər obyektinin oxunuşundan asılı olardı — halbuki o,
    axının özünə aiddir.
    """

    exemption_id: FaceExemptionId
    tenant_id: TenantId
    employee_id: EmployeeId
    granted_by: EmployeeId
    reason: str
    granted_at: datetime
    expires_at: datetime
    status: FaceExemptionStatus = FaceExemptionStatus.ACTIVE
    revoked_by: EmployeeId | None = None
    revoked_at: datetime | None = None
    revoke_reason: str | None = None

    def __post_init__(self) -> None:
        require_aware(self.granted_at, field="granted_at")
        require_aware(self.expires_at, field="expires_at")
        if self.revoked_at is not None:
            require_aware(self.revoked_at, field="revoked_at")
        if self.expires_at <= self.granted_at:
            # Sxemdəki `chk_face_exemption_window`-un güzgüsü: sıfır/mənfi
            # ömürlü istisna ekranda «aktiv» görünüb heç vaxt işləməzdi.
            raise FaceControlError(
                "İstisnanın bitmə anı təyinat anından sonra olmalıdır",
                user_message="İstisnanın müddəti düzgün deyil.",
            )

    def is_active_at(self, moment: datetime) -> bool:
        """Bu anda istisna QÜVVƏDƏDİRmi.

        STATUS TƏK BAŞINA KİFAYƏT ETMİR: gecəlik iş hələ işləməmiş ola bilər
        (terminal söndürülüb — `job_runner.py` "GECİKMİŞ İCRA" bölməsi) və
        sətir `ACTIVE` qalmış, faktiki müddəti isə bitmiş olardı. Vaxt şərti
        olmadan istisna "avtomatik ləğv olunur" vədi cron-un işləməsindən
        asılı qalardı — yəni söndürülmüş terminal qorumanı uzadardı.
        """
        require_aware(moment, field="moment")
        return self.status.is_open and moment < self.expires_at

    def is_due_for_expiry(self, moment: datetime) -> bool:
        """Gecəlik işin «bunu `EXPIRED` et» sualı."""
        require_aware(moment, field="moment")
        return self.status.is_open and moment >= self.expires_at

    def expired(self) -> FaceExemption:
        """Müddət bitməsi — AVTOMATİK keçid (insan qərarı deyil).

        `revoked_by` QƏSDƏN doldurulmur: `EXPIRED` halında qərar verən şəxs
        yoxdur və oraya "sistem" adlı süni bir işçi yazmaq audit izini
        yalanlaşdırardı.
        """
        return FaceExemption(
            exemption_id=self.exemption_id,
            tenant_id=self.tenant_id,
            employee_id=self.employee_id,
            granted_by=self.granted_by,
            reason=self.reason,
            granted_at=self.granted_at,
            expires_at=self.expires_at,
            status=FaceExemptionStatus.EXPIRED,
        )

    def revoked(
        self, *, revoked_by: EmployeeId, revoked_at: datetime, reason: str
    ) -> FaceExemption:
        """Vaxtından əvvəl ləğv — İNSAN QƏRARI, sahibi və səbəbi məcburidir."""
        require_aware(revoked_at, field="revoked_at")
        if not reason.strip():
            raise FaceControlError(
                "Ləğvin səbəbi boş ola bilməz",
                user_message="Ləğv üçün səbəb yazılmalıdır.",
            )
        return FaceExemption(
            exemption_id=self.exemption_id,
            tenant_id=self.tenant_id,
            employee_id=self.employee_id,
            granted_by=self.granted_by,
            reason=self.reason,
            granted_at=self.granted_at,
            expires_at=self.expires_at,
            status=FaceExemptionStatus.REVOKED,
            revoked_by=revoked_by,
            revoked_at=revoked_at,
            revoke_reason=reason.strip(),
        )

    def extended(self, *, new_expiry: datetime) -> FaceExemption:
        """Müddətin uzadılması — YENİ sətir yaratmır, mövcudu uzadır.

        İkinci `ACTIVE` sətir yaratmaq mümkün deyil (`ux_face_exemption_active`
        qismən unikal indeksi), ona görə uzatma məhz belə ifadə olunur.
        Maksimum ömür yoxlaması (`FACE_EXEMPTION_MAX_DAYS`) use case-dədir:
        hədd ROOT parametridir və dəyər obyektinə ötürülsəydi, o, hər
        çağırışda konfiqurasiya oxumalı olardı.
        """
        return FaceExemption(
            exemption_id=self.exemption_id,
            tenant_id=self.tenant_id,
            employee_id=self.employee_id,
            granted_by=self.granted_by,
            reason=self.reason,
            granted_at=self.granted_at,
            expires_at=new_expiry,
            status=self.status,
            revoked_by=self.revoked_by,
            revoked_at=self.revoked_at,
            revoke_reason=self.revoke_reason,
        )


@dataclass(frozen=True)
class FaceVerificationLogEntry:
    """`face_verification_log` sətri (bənd 9, 12, 18).

    CƏDVƏLDƏ NƏ VEKTOR, NƏ KADR VAR — bu sinifdə də yoxdur və olmamalıdır:
    hər cəhd ikinci bir biometrik nüsxə yaratsaydı, deaktivasiyada silmə
    qaydası (bənd 8) mənasız olardı.
    """

    employee_id: EmployeeId
    tenant_id: TenantId
    result: FaceVerificationResult
    trigger_context: FaceTriggerContext
    occurred_at: datetime
    store_id: StoreId | None = None
    matched_other_employee_id: EmployeeId | None = None
    lockout_triggered: bool = False
    confidence_score: float | None = None
    is_low_confidence: bool = False
    liveness_action: LivenessGesture | None = None
    duration_ms: int | None = None

    def __post_init__(self) -> None:
        require_aware(self.occurred_at, field="occurred_at")


@dataclass(frozen=True)
class FaceEnrollmentFrameOutcome:
    """Bir enrollment kadrının taleyi — «[Yenidən Çək]» mesajının mənbəyi.

    Operatora HANSI kadrın niyə rədd edildiyini demək lazımdır: "3 kadrdan
    2-si qaranlıq idi" ilə "heç bir kadr keçmədi" tamamilə fərqli
    əməliyyatlardır (birində işıq yandırılır, ikincidə kamera yoxlanılır).
    """

    index: int
    accepted: bool
    quality: float
    #: Rədd səbəbi (Azərbaycanca). Qəbul edilmiş kadrda `None`.
    reason_az: str | None = None


@dataclass(frozen=True)
class FaceStoreScope:
    """Face Control-un aktiv olduğu mağazalar (bənd 15).

    BOŞ DƏST = QLOBAL DAVRANIŞ (indiki vəziyyət dəyişmir). Bu, sxemin
    (`face_control_store_scope` cədvəli boş olduqda) qərarının kod tərəfidir
    və `covers()` metodunda TƏK yerdə yaşayır — hər çağırış nöqtəsində
    "siyahı boşdursa..." şərti təkrarlansaydı, biri unudulanda Face Control
    həmin axında SÜKUTLA sönərdi (fail-open, ən təhlükəli forma).
    """

    store_ids: frozenset[StoreId] = field(default_factory=frozenset)

    @property
    def is_global(self) -> bool:
        return not self.store_ids

    def covers(self, store_id: StoreId | None) -> bool:
        """Bu mağazada Face Control tətbiq olunurmu.

        `store_id is None` (mağazasız işçi — Root/CEO) DAR əhatədə KƏNARDA
        qalır: pilot mağaza siyahısı seçilibsə, siyahıya düşməyən heç kim üz
        təsdiqindən keçmir. Əks qərar (mağazasız işçini həmişə daxil etmək)
        pilotu idarəolunmaz edərdi.
        """
        if self.is_global:
            return True
        return store_id is not None and store_id in self.store_ids


def add_months(moment: datetime, months: int) -> datetime:
    """Tz-aware ana TƏQVİM ayları əlavə edir (30 günlük təxmin DEYİL).

    `timedelta(days=30 * months)` variantı RƏDD EDİLDİ: 12 "ay" onda 360 gün
    edir və "12 aydan sonra xatırlat" vədi hər il beş gün sürüşərdi. Saxlama
    müddəti (bənd 17) və yenidən-qeydiyyat xatırlatması (bənd 13) eyni
    funksiyanı işlədir ki, iki yerdə iki fərqli "ay" tərifi yaranmasın.

    Ayın son günü qorunur: 31 yanvar + 1 ay = 28/29 fevral (`monthrange`).
    """
    require_aware(moment, field="moment")
    total = moment.month - 1 + months
    year = moment.year + total // 12
    month = total % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def parse_tolerance(raw: str | None, *, fallback: float) -> float:
    """`system_limits`-dən onluq hədd oxuyur — yararsız mətn fallback-a düşür.

    Root-un yazı səhvi (boş sətir, vergüllü format) bütün üz təsdiqi qatını
    çökdürməməlidir — `BehaviorAnomalyRule._parse_float` ilə eyni fəlsəfə.
    Fallback isə `DEFAULT_LIMITS`-dən gəlir (çağıran ötürür), sinifdəki sabit
    ədəddən yox: həqiqi mənbə `system_limits`-dir.
    """
    if raw is None:
        return fallback
    try:
        return float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return fallback


def gesture_pool(
    raw: str | None, *, fallback: Iterable[LivenessGesture]
) -> tuple[LivenessGesture, ...]:
    """Aktiv liveness hovuzu — BOŞ QALA BİLMƏZ (bənd 6).

    Boş siyahı liveness qorumasını TAMAMİLƏ söndürərdi: kioskda tutulan bir
    fotoşəkil hər doğrulamadan keçərdi. Root siyahını boşaltsa (və ya hamısını
    səhv yazsa) qoruma sükutla yox olmamalıdır, ona görə burada
    `DEFAULT_LIMITS` hovuzuna qayıdılır — söndürmək istəyən Root modulun ÖZ
    Feature Toggle-ını işlətməlidir, bu, AÇIQ qərardır.
    """
    parsed = LivenessGesture.parse_catalog(raw)
    return parsed if parsed else tuple(dict.fromkeys(fallback))


__all__ = [
    "MAX_CONFIDENCE_PERCENT",
    "FaceArchiveStatus",
    "FaceControlError",
    "FaceEmbedding",
    "FaceEnrollmentFrameOutcome",
    "FaceExemption",
    "FaceExemptionStatus",
    "FaceFrame",
    "FaceProfile",
    "FaceSample",
    "FaceStoreScope",
    "FaceToleranceBand",
    "FaceTriggerContext",
    "FaceVerificationLogEntry",
    "FaceVerificationResult",
    "LivenessGesture",
    "add_months",
    "gesture_pool",
    "parse_tolerance",
]
