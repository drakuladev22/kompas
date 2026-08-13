"""1C/ERP inteqrasiyasının domen tipləri (spesifikasiya bölmə 6, 7) — Faza 3.10.

──────────────────────────────────────────────────────────────────────────────
NİYƏ ODATA, COM DEYİL VƏ BİRBAŞA BAZA DEYİL
──────────────────────────────────────────────────────────────────────────────
1C:Enterprise ilə üç inteqrasiya yolu var:

    (a) COM konnektoru (`V83.COMConnector`)  — 1C KLİENTİ hər mağaza PC-sində
        quraşdırılmış olmalıdır və yalnız Windows-da işləyir. Bizim məhsul
        müstəqil, imzalanmış bir `.exe`-dir: müştəridən hər kassa PC-sinə 1C
        platforması quraşdırmağı tələb etmək bölmə 7-nin bütün "özünə-xidmət"
        prinsipini pozardı.
    (b) 1C-nin SQL bazasına birbaşa qoşulmaq — 1C-nin öz biznes məntiqini
        (posting, hesablama, hüquqlar) TAM yan keçir, sxem versiyalar arası
        sənədsiz dəyişir və 1C tərəfindən dəstəklənmir. Səhv oxunmuş bir
        sənəd birbaşa işçinin premiyasına düşür.
    (c) **OData (`/<infobase>/odata/standard.odata/`)** — 1C 8.3-ün STANDART,
        sənədləşmiş HTTP interfeysi. Şəbəkə üzərindən işləyir, autentifikasiya
        Basic-dir, heç bir lokal quraşdırma tələb etmir.

(c) seçilib. `erp_servers` cədvəlindəki `host`/`port`/`username`/`password`
sahələri məhz bu model üçündür.

──────────────────────────────────────────────────────────────────────────────
COMPOSITE MATCHING AÇARI
──────────────────────────────────────────────────────────────────────────────
Spesifikasiya bölmə 6: *"Əsas açar `(1C Unikal Satıcı ID + 1C Mağaza Kodu +
Server ID)` — mətn-əsaslı ad uyğunlaşdırması yalnız fallback kimi istifadə
olunur."*

`employees.one_c_seller_id` TƏK bir mətn sütunudur, halbuki serverlər
ÇOXSAYLIDIR — iki fərqli 1C bazasında eyni `"СотрудникID_42"` sətri fərqli
adamlar ola bilər. Açarın "Server ID" hissəsi ona görə DOLAYI yolla tətbiq
olunur: sənəddəki mağaza kodu ƏVVƏLCƏ `store_server_mapping` (server_id +
one_c_store_code) vasitəsilə real mağazaya çevrilir, işçi isə YALNIZ həmin
mağazanın işçiləri arasında axtarılır. Beləliklə server sərhədi keçilmir və
sxem dəyişikliyi lazım gəlmir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any, Final

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.identifiers import EmployeeId, ErpServerId, StoreId, TenantId
from src.shared.exceptions import KompasOSError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: 1C 8.3-ün standart OData kök yolu — infobase adından sonra gəlir.
#: ROOT PARAMETRİ DEYİL: 1C platformasının sənədləşmiş sabitidir, müəssisə
#: seçimi deyil (konfiqurasiyadan asılı adlar `OneCDocumentMapping`-dədir).
ONE_C_ODATA_PATH: Final[str] = "odata/standard.odata"

#: Bir sinxronizasiya dövründə bir serverdən gətirilən maksimum sənəd sayı.
#: Səbəb: ilk qoşulmada 1C bazasında illərlə sənəd ola bilər; hamısını bir
#: sorğuda çəkmək həm 1C serverini, həm də mağaza PC-sinin yaddaşını yıxar.
#: Növbəti dövr qaldığı yerdən davam edir (`sync_cursor`).
#: FALLBACK — HƏQİQİ MƏNBƏ `system_limits.ERP_SYNC_PAGE_SIZE`
#: (seed: migrations/033).
DEFAULT_PAGE_SIZE: Final[int] = int(DEFAULT_LIMITS[SystemLimitKey.ERP_SYNC_PAGE_SIZE])

#: Ad-əsaslı fallback uyğunlaşmasının qəbul edilməsi üçün minimum oxşarlıq.
#: `difflib.SequenceMatcher` nisbəti. 0.87 seçilib, çünki "Əliyev Elvin" ↔
#: "Aliyev Elvin" (transliterasiya fərqi) keçir, "Əliyev Elvin" ↔ "Əliyev
#: Elnur" (fərqli adam) keçmir. Keçən nəticə onsuz da LOW_CONFIDENCE_MATCH
#: kimi işarələnib insan nəzərdən keçirməsinə göndərilir.
#: FALLBACK — HƏQİQİ MƏNBƏ `system_limits.ERP_NAME_MATCH_THRESHOLD`; aşağı
#: hüdud miqrasiyada 0.70-də kilidlidir, çünki daha aşağı hədd satış xalını
#: SƏHV işçiyə yazardı (yuxarıdakı "Elvin/Elnur" nümunəsi).
NAME_MATCH_THRESHOLD: Final[float] = float(DEFAULT_LIMITS[SystemLimitKey.ERP_NAME_MATCH_THRESHOLD])


class ErpError(KompasOSError):
    """1C inteqrasiyası ilə bağlı ümumi xəta."""

    user_message = "1C serveri ilə əlaqədə problem yarandı."


class ErpConnectionError(ErpError):
    """Serverə çatmaq mümkün olmadı (şəbəkə, DNS, timeout).

    Bağlantı Sihirbazının `[Bağlantını Test Et]` düyməsi bu xətanı
    TEXNİKİ-OLMAYAN dildə göstərir (bölmə 7 tələbi).
    """

    user_message = (
        "1C serverinə qoşulmaq mümkün olmadı. Server ünvanını və portu yoxlayın, "
        "serverin işlək olduğuna əmin olun."
    )


class ErpAuthenticationError(ErpError):
    """İstifadəçi adı və ya şifrə yanlışdır."""

    user_message = "1C istifadəçi adı və ya şifrəsi yanlışdır."


class ErpProtocolError(ErpError):
    """Server cavab verdi, lakin cavab gözlənilən OData formatında deyil.

    Ən çox rast gəlinən səbəb: infobase adı səhvdir və server 1C-nin HTML
    xəta səhifəsini qaytarır — bu, "qoşuldu, amma məlumat yoxdur" kimi
    SÜKUTLA ötürülməməlidir.
    """

    user_message = (
        "1C serveri gözlənilməz cavab qaytardı. Baza adının (infobase) düzgün olduğunu yoxlayın."
    )


class ErpServerStatus(str, Enum):
    """`erp_servers.status` — DB enum-u ilə eyni dəyərlər."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ERROR = "ERROR"

    @property
    def is_syncable(self) -> bool:
        """`ERROR` da sinxronizasiya olunur — problem müvəqqəti ola bilər.

        Yalnız `INACTIVE` (admin tərəfindən qəsdən söndürülmüş) buraxılır.
        Əks halda bir şəbəkə kəsintisi serveri həmişəlik növbədən çıxarardı
        və admin əl ilə yenidən aktivləşdirməli olardı.
        """
        return self is not ErpServerStatus.INACTIVE


class MatchConfidence(str, Enum):
    """`sales_transactions.confidence` — DB enum-u ilə eyni dəyərlər."""

    EXACT_MATCH = "EXACT_MATCH"
    LOW_CONFIDENCE_MATCH = "LOW_CONFIDENCE_MATCH"
    MANUAL_MATCH = "MANUAL_MATCH"
    UNASSIGNED = "UNASSIGNED"

    @property
    def needs_review(self) -> bool:
        """ "Təyin Olunmamış / Şübhəli Uyğunlaşma" növbəsinə düşürmü (bölmə 6)."""
        return self in (MatchConfidence.LOW_CONFIDENCE_MATCH, MatchConfidence.UNASSIGNED)

    @property
    def awards_points(self) -> bool:
        """Satış xalı hesablanırmı.

        `LOW_CONFIDENCE_MATCH` xal QAZANDIRIR — əks halda düzgün uyğunlaşmış
        satışlar insan nəzərdən keçirənə qədər işçinin xalından itərdi. Səhv
        çıxarsa `points_ledger` REVERSED/CORRECTED ilə düzəlir (bölmə 6:
        orijinal qeyd silinmir) və işçinin 72 saatlıq etiraz hüququ var.
        """
        return self is not MatchConfidence.UNASSIGNED


@dataclass(frozen=True)
class OneCSaleRecord:
    """1C-dən oxunmuş XAM satış sənədi — hələ heç kimə bağlanmayıb.

    Bu, 1C-nin OData cavabının bizim tərəfimizdəki sabit formasıdır: sahə
    adlarının 1C konfiqurasiyasından asılı olması `one_c_connector` qatında
    bitir, ondan yuxarıda yalnız bu tip görünür.
    """

    document_id: str
    seller_id: str
    store_code: str
    gross_amount: Decimal
    #: Sənədin TAM vaxtı. Kursorun irəliləməsi buna əsaslanır — yalnız
    #: tarixlə (gün dəqiqliyi ilə) irəliləsəydi, eyni gündə səhifə həddindən
    #: çox sənəd olan mağazada sinxronizasiya sonsuz eyni günü oxuyardı.
    document_at: datetime
    #: 1C-dəki satıcı adı — YALNIZ fallback uyğunlaşması üçün.
    seller_name: str | None = None

    @property
    def transaction_date(self) -> date:
        """`sales_transactions.transaction_date` sütununa yazılan dəyər."""
        return self.document_at.date()

    def __post_init__(self) -> None:
        if not self.document_id.strip():
            # Sənəd ID-si `UNIQUE (server_id, one_c_document_id)` ilə təkrar
            # yükləmənin yeganə qarşısını alan sahədir — boş buraxılsa eyni
            # satış hər dövrdə yenidən xal qazandırardı.
            raise ErpProtocolError(
                "1C sənədində identifikator boşdur — təkrar sinxronizasiya qorunması işləməzdi",
                context={"seller_id": self.seller_id, "store_code": self.store_code},
            )
        if self.gross_amount < 0:
            raise ErpProtocolError(
                "Satış məbləği mənfi ola bilməz",
                context={"document_id": self.document_id, "amount": str(self.gross_amount)},
            )


@dataclass(frozen=True)
class SyncCursor:
    """Bir serverin harada qaldığı — növbəti dövr buradan davam edir.

    ──────────────────────────────────────────────────────────────────────
    NİYƏ `>=` VƏ SƏRHƏD SİYAHISI, SADƏCƏ `>` DEYİL
    ──────────────────────────────────────────────────────────────────────
    Sənədlər `Date` sahəsinə görə sıralanır. Kursor `>` ilə irəliləsəydi,
    son sənədlə EYNİ saniyədə yazılmış digər sənədlər həmişəlik atlanardı —
    pərakəndədə eyni saniyədə bir neçə çek adi haldır və atlanan satış
    işçinin premiyasından itərdi.

    Ona görə sorğu `>=` ilə gedir, sərhəddəki (son vaxt damğasına malik)
    sənədlərin ID-ləri isə burada saxlanılır və növbəti dövrdə süzülür.
    Beləliklə nə sənəd atlanır, nə də təkrar emal olunur. Əlavə qoruma
    qatı: `UNIQUE (server_id, one_c_document_id)`.
    """

    #: Emal edilmiş son sənədin vaxtı (server saatı ilə). `None` = ilk dövr.
    last_document_at: datetime | None = None
    #: `last_document_at` ilə EYNİ vaxta malik, artıq emal edilmiş sənədlər.
    #: Yalnız sərhəd saniyəsinə aiddir — ona görə kiçik qalır.
    boundary_document_ids: frozenset[str] = frozenset()
    #: Diaqnostika üçün — son dövrdə neçə sənəd gətirildi.
    last_batch_size: int = 0

    @property
    def is_initial(self) -> bool:
        return self.last_document_at is None

    def already_seen(self, record: OneCSaleRecord) -> bool:
        """Sənəd sərhəd saniyəsində artıq emal olunubmu."""
        return (
            self.last_document_at is not None
            and record.document_at == self.last_document_at
            and record.document_id in self.boundary_document_ids
        )

    def advanced(self, batch: Sequence[OneCSaleRecord]) -> SyncCursor:
        """Emal edilmiş partiyaya görə yeni kursor qaytarır.

        Boş partiya kursoru DƏYİŞMİR — əks halda "yeni sənəd yoxdur"
        vəziyyəti kursoru irəli sürüb sonradan gələn gec-yazılmış sənədləri
        atlaya bilərdi.
        """
        if not batch:
            return SyncCursor(
                last_document_at=self.last_document_at,
                boundary_document_ids=self.boundary_document_ids,
                last_batch_size=0,
            )
        newest = max(record.document_at for record in batch)
        boundary = frozenset(record.document_id for record in batch if record.document_at == newest)
        if newest == self.last_document_at:
            # Eyni sərhəd saniyəsində qaldıq — əvvəlki ID-lər UNUDULMAMALIDIR.
            boundary = boundary | self.boundary_document_ids
        return SyncCursor(
            last_document_at=newest,
            boundary_document_ids=boundary,
            last_batch_size=len(batch),
        )


@dataclass(frozen=True)
class OneCDocumentMapping:
    """Satış sənədinin OData adları — 1C KONFİQURASİYASINDAN asılı hissə.

    OData-nın özü standartdır, lakin sənəd və rekvizit adları konfiqurasiyaya
    görə dəyişir ("Розница", "Управление Торговлей", fərdi bazalar). Müştəri
    dörd brendlə işləyir və hər birinin öz bazası ola bilər — adları koda
    bərk-yazsaydıq, hər yeni baza üçün müştəri BİZƏ müraciət etməli olardı
    (bölmə 7-nin özünə-xidmət prinsipinin pozulması).

    `Ref_Key` və `Date` istisnadır: onlar 1C OData-nın PLATFORMA səviyyəli
    sahələridir və konfiqurasiyadan asılı deyil.
    """

    entity_name: str = "Document_RealizaciyaTovarovUslug"
    seller_field: str = "Otvetstvennyj_Key"
    store_field: str = "Sklad_Key"
    amount_field: str = "SummaDokumenta"
    #: İSTƏYƏ BAĞLI — yalnız ad-əsaslı fallback uyğunlaşması üçün.
    seller_name_field: str | None = "Otvetstvennyj"

    def selected_fields(self) -> str:
        """OData `$select` siyahısı — lazımsız rekvizitlər şəbəkəyə düşməsin."""
        names = ["Ref_Key", "Date", self.seller_field, self.store_field, self.amount_field]
        if self.seller_name_field:
            names.append(self.seller_name_field)
        return ",".join(names)

    def as_dict(self) -> dict[str, str | None]:
        return {
            "entity_name": self.entity_name,
            "seller_field": self.seller_field,
            "store_field": self.store_field,
            "amount_field": self.amount_field,
            "seller_name_field": self.seller_name_field,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> OneCDocumentMapping:
        """Saxlanmış adlandırmanı bərpa edir; boşdursa defolt qaytarır."""
        if not raw:
            return cls()
        allowed = set(cls().as_dict())
        unknown = set(raw) - allowed
        if unknown:
            # Naməlum açar SÜKUTLA atılmır: konfiqurasiya səhvi görünməlidir,
            # əks halda "niyə sahə tətbiq olunmur?" sualı yaranardı.
            raise ErpError(
                f"Server konfiqurasiyasında naməlum sahə: {sorted(unknown)}",
                user_message="Server konfiqurasiyası yararsızdır — sihirbazdan yenidən qurun.",
                context={"unknown": sorted(unknown)},
            )
        return cls(**dict(raw))


@dataclass(frozen=True)
class ErpServerDraft:
    """Sihirbazda doldurulan, hələ yadda saxlanmamış server konfiqurasiyası.

    `password` açıq mətndir və obyekt YALNIZ işlək yaddaşda mövcuddur —
    DB-yə yazılarkən AES-256-GCM ilə şifrələnir (`erp_servers.
    password_encrypted`). `__repr__` şifrəni gizlədir (SEC-013).
    """

    server_name: str
    host: str
    port: int
    username: str
    password: str
    infobase: str
    use_https: bool = False
    mapping: OneCDocumentMapping = field(default_factory=OneCDocumentMapping)
    sync_interval_seconds: int = 300

    def __repr__(self) -> str:
        return f"ErpServerDraft(name={self.server_name}, host={self.host}:{self.port})"

    def auditable(self) -> dict[str, Any]:
        """Audit log-a yazılan görünüş — ŞİFRƏ DAXİL DEYİL."""
        return {
            "server_name": self.server_name,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "infobase": self.infobase,
            "use_https": self.use_https,
            "sync_interval_seconds": self.sync_interval_seconds,
        }


@dataclass(frozen=True)
class ConnectionTestResult:
    """`[Bağlantını Test Et]` nəticəsi (bölmə 7).

    `message` TEXNİKİ-OLMAYAN dildədir — birbaşa sihirbazda göstərilir
    ("uğursuz olarsa aydın, texniki-olmayan dildə xəta göstərir").
    `detail` isə `app.log` üçün texniki səbəbdir.
    """

    ok: bool
    message: str
    detail: str = ""
    #: Serverdə doğrulanmış sənəd növü — uğurlu testin sübutu.
    entity_verified: str | None = None
    elapsed_ms: int = 0


@dataclass(frozen=True)
class ErpServer:
    """Saxlanmış server qeydinin oxu-modeli (ŞİFRƏ DAXİL DEYİL)."""

    id: ErpServerId
    tenant_id: TenantId
    server_name: str
    host: str
    port: int
    username: str
    infobase: str
    status: ErpServerStatus
    use_https: bool = False
    mapping: OneCDocumentMapping = field(default_factory=OneCDocumentMapping)
    sync_interval_seconds: int = 300
    last_successful_sync: datetime | None = None
    last_sync_started_at: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    consecutive_failures: int = 0
    cursor: SyncCursor = field(default_factory=SyncCursor)

    @property
    def is_syncable(self) -> bool:
        return self.status.is_syncable

    @property
    def has_verified_config(self) -> bool:
        """Konfiqurasiya heç olmasa bir dəfə işləyibmi.

        Backup yalnız belə konfiqurasiya üçün saxlanılır: əks halda "geri
        qaytar" düyməsi ikinci səhv konfiqurasiyanı bərpa edərdi.
        """
        return self.last_successful_sync is not None

    def auditable(self) -> dict[str, Any]:
        return {
            "server_name": self.server_name,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "infobase": self.infobase,
            "use_https": self.use_https,
            "sync_interval_seconds": self.sync_interval_seconds,
        }

    def __repr__(self) -> str:
        return (
            f"ErpServer(id={self.id}, name={self.server_name}, "
            f"host={self.host}:{self.port}, status={self.status.value})"
        )


@dataclass(frozen=True)
class MatchResult:
    """Bir 1C sənədinin işçi/mağazaya bağlanma nəticəsi."""

    record: OneCSaleRecord
    confidence: MatchConfidence
    employee_id: EmployeeId | None = None
    store_id: StoreId | None = None
    #: Nəyə görə bu nəticə alındı — "Şübhəli Uyğunlaşma" növbəsində HR_Admin
    #: sətri açmadan səbəbi görsün deyə (`sales_transactions.match_reason`).
    reason: str = ""

    @property
    def is_assigned(self) -> bool:
        return self.employee_id is not None


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "NAME_MATCH_THRESHOLD",
    "ONE_C_ODATA_PATH",
    "ConnectionTestResult",
    "ErpAuthenticationError",
    "ErpConnectionError",
    "ErpError",
    "ErpProtocolError",
    "ErpServer",
    "ErpServerDraft",
    "ErpServerStatus",
    "MatchConfidence",
    "MatchResult",
    "OneCDocumentMapping",
    "OneCSaleRecord",
    "SyncCursor",
]
