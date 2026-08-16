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

(c) DEFOLT olaraq seçilib. `erp_servers` cədvəlindəki `host`/`port`/
`username`/`password` sahələri məhz bu model üçündür.

──────────────────────────────────────────────────────────────────────────────
NİYƏ ARTIQ ÜÇÜ DƏ VAR — SEÇİM KODDAN KONFİQURASİYAYA KEÇDİ (1c.md)
──────────────────────────────────────────────────────────────────────────────
Yuxarıdakı əsaslandırma BİR müştəri üçün doğru idi. Məhsul çox-müştərili
(multi-tenant) olduqda isə seçimin özü müştəridən-müştəriyə dəyişir: birində
1C-nin veb-serveri yayımlanıb (HTTP/OData), digərində yalnız COM komponenti
quraşdırılıb, üçüncüsü isə heç birini açmır və gecə ixracı ilə fayl verir.

Ona görə protokol artıq KODDA seçilmir — `erp_servers.connector_type`
sütununda saxlanılır və Root/CEO paneldən seçilir (`ConnectorType`). (a) və
(b) bəndlərindəki risklər YOX OLMADI, sadəcə onların qiymətini müştəri özü
verir:

    * COM hələ də YALNIZ Windows-dadır və 1C platformasının həmin PC-də
      quraşdırılmasını tələb edir — konnektor bunu açıq xəta ilə bildirir,
      sükutla çökmür (`ErpPlatformError`).
    * Fayl mübadiləsi real-vaxt DEYİL: dövrü `ERP_FILE_EXCHANGE_SYNC_
      INTERVAL_SECONDS` ilə idarə olunur və defolt gündə bir dəfədir.

DƏYİŞMƏYƏN HİSSƏ: hər üç yol EYNİ `OneCSaleRecord` axını qaytarır. Uyğunlaşma
(`matching.py`), kursor, təkrar qoruması və satış xalı üçün konnektorun tipi
GÖRÜNMÜR — yalnız gələn sənədin sahələri görünür.

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

#: HTTP və COM serverlərinin defolt sinxronizasiya dövrü (saniyə).
#:
#: BU, ROOT AÇARI DEYİL — `erp_servers.sync_interval_seconds` sütununun
#: `schema.sql`-dəki DEFAULT-u ilə eyni ədəddir və dövr HƏR SERVER üçün ayrıca
#: saxlanılır (bir mağaza kassa serverini tez-tez, mərkəzi anbarı seyrək
#: yoxlamaq istəyə bilər). Sabit burada təkrarlanır ki, sətir sihirbazdan
#: dövrsüz gəldikdə domen özü doğru dəyəri verə bilsin.
#:
#: Fayl mübadiləsi İSTİSNADIR: onun defoltu `system_limits`-dən oxunur, çünki
#: "gecədə bir dəfə" bir SİYASƏTdir və müəssisə onu dəyişə bilməlidir.
DEFAULT_SYNC_INTERVAL_SECONDS: Final[int] = 300

#: Fayl mübadiləsinin defolt dövrü — FALLBACK; HƏQİQİ MƏNBƏ
#: `system_limits.ERP_FILE_EXCHANGE_SYNC_INTERVAL_SECONDS` (seed:
#: migrations/050). Sətir oxuna bilmədikdə bu dəyər işə düşür.
FILE_EXCHANGE_SYNC_INTERVAL_SECONDS: Final[int] = int(
    DEFAULT_LIMITS[SystemLimitKey.ERP_FILE_EXCHANGE_SYNC_INTERVAL_SECONDS]
)

#: `erp_servers.sync_interval_seconds` sütununun DB CHECK-i (`>= 30`).
#: Domen həmin həddi TƏKRARLAYIR ki, sihirbaz sətri yazmazdan ƏVVƏL aydın
#: mesaj verə bilsin — DB-yə çatan pozuntu istifadəçiyə `psycopg` xətası kimi
#: görünərdi. Qayda İKİ yerdədir və hər ikisi dəyişəndə birlikdə dəyişməlidir
#: (CLAUDE.md bölmə 5 naxışı).
MIN_SYNC_INTERVAL_SECONDS: Final[int] = 30

#: Konfiqurasiya açarında bu parçalardan biri varsa dəyər SİRR sayılır və nə
#: `repr`-də, nə audit sətrində, nə də log-da görünmür (SEC-013).
#:
#: NİYƏ PARÇA-ƏSASLI QARA SİYAHI, NİYƏ AĞ SİYAHI DEYİL: konfiqurasiya
#: açarlarını BİZ təyin edirik (üç konnektorun `Settings` sinifləri), yəni
#: siyahı qapalıdır və yeni açar əlavə edən adamın onu ağ siyahıya yazmağı
#: unutması "sirr sızdı" deyil, "faydalı diaqnostika gizləndi" ilə nəticələnir.
#: Əks seçim (ağ siyahı) daha sərt görünür, lakin praktikada hər yeni açarın
#: gizlədilməsi diaqnostikanı tamamilə boşaldardı.
SECRET_CONFIG_KEY_MARKERS: Final[tuple[str, ...]] = (
    "password",
    "parol",
    "secret",
    "token",
    "credential",
)


def is_secret_config_key(key: str) -> bool:
    """Konfiqurasiya açarı sirr daşıyırmı (`SECRET_CONFIG_KEY_MARKERS`)."""
    lowered = key.lower()
    return any(marker in lowered for marker in SECRET_CONFIG_KEY_MARKERS)


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


class ErpPlatformError(ErpError):
    """Seçilmiş bağlantı növü bu əməliyyat sistemində mümkün deyil.

    Yalnız COM üçün baş verir: `V83.COMConnector` Windows-un COM/OLE
    infrastrukturuna bağlıdır. Xəta AÇIQ atılır və konnektor ÇÖKMÜR — əks
    halda Linux CI-da və ya inkişaf maşınında modul idxalı `ImportError` ilə
    dağılar, istifadəçi isə səbəbi görmədən "1C işləmir" nəticəsinə gələrdi.
    """

    user_message = (
        "Bu bağlantı növü yalnız Windows kompüterlərində işləyir. "
        "HTTP/OData və ya Fayl-Mübadiləsi növünü seçin."
    )


class ErpConfigurationError(ErpError):
    """Bağlantı növünün tələb etdiyi parametr(lər) boşdur və ya yararsızdır.

    `ErpProtocolError`-dan FƏRQLƏNİR: orada server cavab verib, cavab
    gözlənilməzdir; burada isə sorğu ümumiyyətlə göndərilə bilmir, çünki
    konfiqurasiya natamamdır. İkisini birləşdirsəydik, sihirbazdakı mesaj
    "serveri yoxlayın" deyərdi — halbuki problem istifadəçinin doldurmadığı
    sahədədir.
    """

    user_message = (
        "Bağlantı konfiqurasiyası natamamdır — sihirbazdakı sahələri yoxlayıb yenidən cəhd edin."
    )


class ConnectorType(str, Enum):
    """`erp_servers.connector_type` — 1C ilə əlaqənin ÜSULU (1c.md).

    Üç dəyər DB CHECK-i ilə eynidir (migrations/050). Sətir mətnləri
    (`label_az`, `card_description_az`) məhz burada saxlanılır, ekranda yox:
    eyni izah HƏM sihirbazın kartında, HƏM server siyahısının nişanında, HƏM
    də sağlamlıq diaqnozunda görünür — üç yerdə üç fərqli ifadə istifadəçidə
    "bunlar eyni şeydirmi?" sualı yaradardı.
    """

    HTTP = "HTTP"
    COM = "COM"
    FILE_EXCHANGE = "FILE_EXCHANGE"

    @property
    def label_az(self) -> str:
        """Server siyahısındakı qısa nişan mətni."""
        return _CONNECTOR_LABELS[self]

    @property
    def card_description_az(self) -> str:
        """Sihirbazın BİRİNCİ addımındakı kart izahı (1c.md UX tələbi 1)."""
        return _CONNECTOR_DESCRIPTIONS[self]

    @property
    def address_label_az(self) -> str:
        """«Ünvan» sahəsinin bu tip üçün MƏNASI.

        `erp_servers.host` sütunu üç tipdə üç fərqli şey saxlayır (bax
        `ErpServer.display_address`), ona görə formanın etiketi də dəyişməlidir
        — «Server ünvanı» yazan bir sahəyə qovluq yolu yazmaq istifadəçini
        çaşdırardı.
        """
        return _CONNECTOR_ADDRESS_LABELS[self]

    @property
    def uses_port(self) -> bool:
        """Şəbəkə portu bu tipdə mənalıdırmı.

        `False` olduqda `erp_servers.port` sentinel `0` saxlayır və ekranda
        GÖSTƏRİLMİR (bax `ErpServer.display_address`).
        """
        return self is ConnectorType.HTTP

    @property
    def requires_windows(self) -> bool:
        """Yalnız Windows-da işləyirmi (COM/OLE)."""
        return self is ConnectorType.COM

    @property
    def is_real_time(self) -> bool:
        """Məlumat sorğu anında gəlirmi.

        Fayl mübadiləsində gələn məlumat ixracın YAZILDIĞI andakı vəziyyətdir
        — yəni "indiki" deyil. Bu fərq istifadəçiyə göstərilməlidir, əks halda
        gecə ixracı olan mağazada "satış görünmür" şikayəti yaranar.
        """
        return self is not ConnectorType.FILE_EXCHANGE

    @property
    def requires_infobase(self) -> bool:
        """Aktivləşdirmək üçün baza adı (infobase) məcburidirmi.

        HTTP-də OData ünvanının, COM-da isə `Ref=` bağlantı sətrinin tərkib
        hissəsidir. Fayl mübadiləsində 1C bazası ilə HEÇ BİR birbaşa əlaqə
        yoxdur — orada məcburi olan qovluq yoludur (`host`).
        """
        return self is not ConnectorType.FILE_EXCHANGE

    @property
    def default_sync_interval_seconds(self) -> int:
        """Sihirbaz dövr göstərməyəndə tətbiq olunan dəyər.

        FALLBACK-dır: fayl mübadiləsi üçün HƏQİQİ MƏNBƏ
        `system_limits.ERP_FILE_EXCHANGE_SYNC_INTERVAL_SECONDS`-dir və canlı
        oxu `ErpConnectionWizardUseCase`-dədir. Domen DB-ni oxuya bilmədiyi
        üçün burada yalnız defolt cədvəldən gələn dəyər var.
        """
        if self is ConnectorType.FILE_EXCHANGE:
            return FILE_EXCHANGE_SYNC_INTERVAL_SECONDS
        return DEFAULT_SYNC_INTERVAL_SECONDS

    @property
    def latency_meaning_az(self) -> str:
        """Sağlamlıq monitorunda ölçülən müddətin MƏNASI (bax `health.py`).

        Fayl mübadiləsində şəbəkə gecikməsi anlayışı YOXDUR — ölçülən şey
        qovluğun oxunma müddətidir. Eyni sütuna iki fərqli məna yazıb izahsız
        buraxmaq monitoru yanıldıcı edərdi.
        """
        return _CONNECTOR_LATENCY_MEANINGS[self]

    @classmethod
    def parse(cls, raw: str | None) -> ConnectorType:
        """DB sətrini oxuyur; boş/naməlum dəyər `HTTP` sayılır.

        GERİYƏ UYĞUNLUQ: migrations/050-dən ƏVVƏL yaradılmış sətirlərdə sütun
        yoxdur (və ya `NULL`-dur) və onların hamısı OData konnektoru ilə
        qurulub. Belə sətri "naməlum tip" sayıb sinxronizasiyadan çıxarsaydıq,
        miqrasiya günü bütün mövcud satış axını sükutla dayanardı.
        """
        text = (raw or "").strip().upper()
        if not text:
            return cls.HTTP
        try:
            return cls(text)
        except ValueError:
            return cls.HTTP


#: Enum-un mətnləri AYRI cədvəllərdədir: `str, Enum` üzvünə `property` yazmaq
#: mümkündür, lakin sözlüklər mətnləri bir yerdə göstərir və tərcümə/redaktə
#: zamanı üç metodu ayrı-ayrı oxumaq lazım gəlmir.
_CONNECTOR_LABELS: Final[dict[ConnectorType, str]] = {
    ConnectorType.HTTP: "HTTP/OData",
    ConnectorType.COM: "COM",
    ConnectorType.FILE_EXCHANGE: "Fayl",
}

#: Mətnlər 1c.md-nin UX bölməsindən HƏRFƏN götürülüb — sihirbazın kartında
#: qeyri-texniki istifadəçiyə (CEO) izah kimi göstərilir.
_CONNECTOR_DESCRIPTIONS: Final[dict[ConnectorType, str]] = {
    ConnectorType.HTTP: (
        "Ən sürətli, real-vaxta yaxın seçim — 1C-də veb-servis yayımlanıbsa istifadə edin."
    ),
    ConnectorType.COM: ("Windows-a xas, 1C-nin öz COM komponentləri quraşdırılmışdırsa uyğundur."),
    ConnectorType.FILE_EXCHANGE: (
        "Ən sadə, amma real-vaxt DEYİL — hər gecə bir dəfə sinxronlaşır."
    ),
}

_CONNECTOR_ADDRESS_LABELS: Final[dict[ConnectorType, str]] = {
    ConnectorType.HTTP: "Server ünvanı (host:port)",
    ConnectorType.COM: "1C server adı və ya baza qovluğu",
    ConnectorType.FILE_EXCHANGE: "Mübadilə qovluğunun yolu",
}

_CONNECTOR_LATENCY_MEANINGS: Final[dict[ConnectorType, str]] = {
    ConnectorType.HTTP: "Şəbəkə cavab müddəti",
    ConnectorType.COM: "COM obyektinin qurulma müddəti",
    ConnectorType.FILE_EXCHANGE: "Qovluğun oxunma müddəti",
}


@dataclass(frozen=True)
class ConnectorConfig:
    """Bağlantı növünə XAS parametrlər — `erp_servers.connector_config_encrypted`.

    ──────────────────────────────────────────────────────────────────────
    NİYƏ SƏRBƏST SÖZLÜK, NİYƏ TİPLƏNMİŞ SAHƏLƏR DEYİL
    ──────────────────────────────────────────────────────────────────────
    Üç konnektorun parametr dəstləri KƏSİŞMİR: COM `server`/`baza`/`sorğu
    mətni` istəyir, fayl mübadiləsi isə `qovluq`/`format`/`sütun adları`.
    Onları bir dataclass-da birləşdirsəydik, hər sahə `None` ola bilən olardı
    və "hansı sahə hansı tipdə məcburidir?" sualının cavabı heç yerdə
    yazılmazdı. Sözlük isə TİP-ə xas oxunuşu konnektorun öz `Settings`
    sinfinə buraxır — məcburilik yoxlaması və Azərbaycanca xəta mesajı orada,
    bir yerdədir.

    ──────────────────────────────────────────────────────────────────────
    SİRR AÇIQ MƏTNDƏ SAXLANMIR
    ──────────────────────────────────────────────────────────────────────
    Sözlükdə şifrə də ola bilər (COM istifadəçisi, fayl-paylaşımı). Ona görə:
        * DB-də bütöv JSON AES-256-GCM ilə şifrələnir (`password_encrypted`
          naxışı, AAD = server ID-si);
        * `__repr__` və `auditable()` sirr açarlarını maskalayır (SEC-013).
    """

    values: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """DB-yə/backup-a yazılan TAM görünüş (sirlər DAXİL)."""
        return dict(self.values)

    def public_values(self) -> dict[str, Any]:
        """Sirr daşımayan açarlar — ekran, audit və log üçün."""
        return {key: value for key, value in self.values.items() if not is_secret_config_key(key)}

    def auditable(self) -> dict[str, Any]:
        """Audit sətrinin gördüyü görünüş.

        Sirrin DƏYƏRİ deyil, VERİLİB-VERİLMƏDİYİ yazılır — `_config_state`-dəki
        `credentials_supplied` ilə eyni əsaslandırma: yalnız şifrə dəyişəndə
        audit sətri əks halda "heç nə dəyişməyib" kimi görünərdi.
        """
        state: dict[str, Any] = self.public_values()
        secrets = sorted(key for key in self.values if is_secret_config_key(key))
        if secrets:
            state["gizli_sahələr"] = secrets
        return state

    def text(self, key: str, default: str = "") -> str:
        """Mətn dəyəri — kənar boşluqlar kəsilmiş."""
        raw = self.values.get(key)
        if raw is None:
            return default
        value = str(raw).strip()
        return value or default

    def flag(self, key: str, default: bool = False) -> bool:
        """Məntiqi dəyər. JSON-dan həm `true`, həm `"true"` gələ bilər."""
        raw = self.values.get(key)
        if raw is None:
            return default
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in ("true", "1", "bəli", "yes")

    def number(self, key: str, default: int = 0) -> int:
        """Tam ədəd. Yararsız dəyər SÜKUTLA 0 olmur — defolt qaytarılır."""
        raw = self.values.get(key)
        if raw is None:
            return default
        try:
            return int(str(raw).strip())
        except ValueError:
            return default

    def with_values(self, **overrides: Any) -> ConnectorConfig:
        """Üzərinə yazılmış nüsxə — sihirbazın addım-addım doldurması üçün."""
        merged = dict(self.values)
        merged.update(overrides)
        return ConnectorConfig(values=merged)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> ConnectorConfig:
        """Saxlanmış JSON-dan bərpa edir; boşdursa boş konfiqurasiya."""
        return cls(values=dict(raw)) if raw else cls()

    def __bool__(self) -> bool:
        return bool(self.values)

    def __repr__(self) -> str:
        # Obyekt xəta konteksti və debug çıxışı ilə log-a düşə bilər
        # (SEC-013) — sirr açarları DƏYƏRSİZ göstərilir.
        shown = ", ".join(
            f"{key}=***" if is_secret_config_key(key) else f"{key}={value}"
            for key, value in sorted(self.values.items())
        )
        return f"ConnectorConfig({shown})"


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
    #: `None` = dövr TİPİN defoltundan gəlir (bax
    #: `effective_sync_interval_seconds`). Açıq ədəd verilərsə O QALIR —
    #: istifadəçi onu sihirbazda bilərəkdən yazıb.
    sync_interval_seconds: int | None = None
    connector_type: ConnectorType = ConnectorType.HTTP
    #: Tipə xas parametrlər (COM bağlantı sətri, fayl sütun adları, …).
    #: HTTP üçün adətən BOŞDUR: onun bütün parametrləri sütunlardadır.
    connector_config: ConnectorConfig = field(default_factory=ConnectorConfig)

    def __post_init__(self) -> None:
        """Port yalnız HTTP-də mənalıdır — digər tiplərdə sentinel `0`.

        NİYƏ NORMALLAŞDIRMA, NİYƏ İSTİSNA DEYİL: 1c.md UX tələbi 2 sihirbazın
        bir tipdən digərinə keçəndə ƏVVƏLKİ dəyərləri yaddaşda saxlamasını
        tələb edir. Yəni HTTP portu doldurulub sonra «Fayl» kartı seçiləndə
        forma həmin portu hələ də daşıyır. Bunu istifadəçi səhvi sayıb sətri
        rədd etsəydik, qüsursuz doldurulmuş forma "port yararsızdır" xətası
        verərdi. Sentinel `0` isə DB CHECK-i ilə eynidir (migrations/050) və
        ekranda ümumiyyətlə göstərilmir.
        """
        if not self.connector_type.uses_port and self.port != 0:
            object.__setattr__(self, "port", 0)

    @property
    def effective_sync_interval_seconds(self) -> int:
        """DB-yə yazılacaq FAKTİKİ dövr.

        Aşağı hədd DB CHECK-i ilə eynidir (`>= 30`): sihirbazdan gələn kiçik
        dəyər burada qaldırılır, əks halda `INSERT` `psycopg` xətası ilə
        qırılar və istifadəçi anlaşılmaz mesaj görərdi.
        """
        requested = self.sync_interval_seconds
        if requested is None:
            requested = self.connector_type.default_sync_interval_seconds
        return max(MIN_SYNC_INTERVAL_SECONDS, requested)

    @property
    def display_address(self) -> str:
        """Ekranda göstərilən ünvan — port yalnız HTTP-də görünür."""
        return display_address_for(self.connector_type, self.host, self.port)

    def __repr__(self) -> str:
        return (
            f"ErpServerDraft(name={self.server_name}, type={self.connector_type.value}, "
            f"address={self.display_address})"
        )

    def auditable(self) -> dict[str, Any]:
        """Audit log-a yazılan görünüş — ŞİFRƏ DAXİL DEYİL."""
        return {
            "server_name": self.server_name,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "infobase": self.infobase,
            "use_https": self.use_https,
            "sync_interval_seconds": self.effective_sync_interval_seconds,
            "connector_type": self.connector_type.value,
            # Sirr açarları maskalanır — bax `ConnectorConfig.auditable`.
            "connector_config": self.connector_config.auditable(),
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
    """Saxlanmış server qeydinin oxu-modeli (ŞİFRƏ DAXİL DEYİL).

    `connector_config` DA DAXİL DEYİL və bu, unutqanlıq deyil: sözlük COM
    şifrəsi kimi sirr daşıya bilər, oxu-modeli isə siyahı sorğusu ilə hər
    ekran açılışında yaddaşa gəlir. `password_encrypted` üçün verilmiş qərar
    (bax `servers.ErpServerRepository._SELECT`) burada da qüvvədədir: sirr
    YALNIZ `credentials_for()` ilə, açıq şəkildə və `security.log`-a düşən bir
    çağırışla oxunur.
    """

    id: ErpServerId
    tenant_id: TenantId
    server_name: str
    host: str
    port: int
    username: str
    infobase: str
    status: ErpServerStatus
    use_https: bool = False
    #: DEFOLT `HTTP` — migrations/050-dən əvvəlki sətirlərdə sütun yoxdur və
    #: onların hamısı OData ilə qurulub (bax `ConnectorType.parse`).
    connector_type: ConnectorType = ConnectorType.HTTP
    mapping: OneCDocumentMapping = field(default_factory=OneCDocumentMapping)
    sync_interval_seconds: int = DEFAULT_SYNC_INTERVAL_SECONDS
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

    @property
    def display_address(self) -> str:
        """Server siyahısında göstərilən ünvan.

        ──────────────────────────────────────────────────────────────────
        NİYƏ DOMENDƏ, GUI-DƏ DEYİL
        ──────────────────────────────────────────────────────────────────
        `host` sütunu üç tipdə üç fərqli şey saxlayır: HTTP-də şəbəkə ünvanı,
        COM-da 1C server adı (və ya fayl bazasının yolu), fayl mübadiləsində
        isə mübadilə qovluğu. `port` isə YALNIZ HTTP-də mənalıdır və digər
        tiplərdə sentinel `0`-dır.

        Ekran sətri `f"{host}:{port}"` kimi qursaydı, fayl serveri
        «\\\\anbar\\1c_exchange:0» kimi görünərdi — yəni istifadəçiyə YANILDICI
        bir dəyər. Qayda mətnin özündə deyil, məhz burada saxlanılır ki, ekran,
        audit və sağlamlıq monitoru eyni cavabı versin.
        """
        return display_address_for(self.connector_type, self.host, self.port)

    def auditable(self) -> dict[str, Any]:
        return {
            "server_name": self.server_name,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "infobase": self.infobase,
            "use_https": self.use_https,
            "sync_interval_seconds": self.sync_interval_seconds,
            "connector_type": self.connector_type.value,
        }

    def __repr__(self) -> str:
        return (
            f"ErpServer(id={self.id}, name={self.server_name}, "
            f"type={self.connector_type.value}, address={self.display_address}, "
            f"status={self.status.value})"
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


def display_address_for(connector_type: ConnectorType, host: str, port: int) -> str:
    """Tipə uyğun ünvan mətni — `ErpServer`, `ErpServerDraft` və monitor üçün ORTAQ.

    İki dataclass-da iki nüsxə yazsaydıq, biri düzəldiləndə digəri arxada
    qalardı: sihirbazın göstərdiyi ünvan siyahıdakından fərqlənərdi.
    """
    address = host.strip() or "—"
    if connector_type.uses_port and port > 0:
        return f"{address}:{port}"
    return address


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "DEFAULT_SYNC_INTERVAL_SECONDS",
    "FILE_EXCHANGE_SYNC_INTERVAL_SECONDS",
    "MIN_SYNC_INTERVAL_SECONDS",
    "NAME_MATCH_THRESHOLD",
    "ONE_C_ODATA_PATH",
    "SECRET_CONFIG_KEY_MARKERS",
    "ConnectionTestResult",
    "ConnectorConfig",
    "ConnectorType",
    "ErpAuthenticationError",
    "ErpConfigurationError",
    "ErpConnectionError",
    "ErpError",
    "ErpPlatformError",
    "ErpProtocolError",
    "ErpServer",
    "ErpServerDraft",
    "ErpServerStatus",
    "MatchConfidence",
    "MatchResult",
    "OneCDocumentMapping",
    "OneCSaleRecord",
    "SyncCursor",
    "display_address_for",
    "is_secret_config_key",
]
