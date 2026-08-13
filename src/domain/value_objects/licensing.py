"""Lisenziya və məhdud-rejim domen tipləri (spesifikasiya bölmə 8) — Faza 3.11.

──────────────────────────────────────────────────────────────────────────────
ARXİTEKTURA: AYRICA SERVER YOXDUR — HƏR ŞEY MÖVCUD SUPABASE ÜZƏRİNDƏDİR
──────────────────────────────────────────────────────────────────────────────
Lisenziya sistemi üçün NƏ ayrıca VPS, NƏ domen, NƏ hostinq, NƏ də HTTP API
var. İki tərəf, bir baza:

    MÜŞTƏRİ (.exe)      `license_tenants`-dəki ÖZ sətrini oxuyur — YALNIZ
                        SELECT. `anon` açar + RLS ilə başqa tenant-ın sətri
                        ümumiyyətlə görünmür, yazma hüququ yoxdur.
    DEVELOPER PANELİ    yalnız hazırlayıcının öz kompüterində işə düşən
                        yerli rejim (`--developer-mode`). `service_role`
                        açarı ilə bütün sətirləri görür və `expires_at`-i
                        yeniləyir. İNTERNETƏ HOST OLUNMUR.

Nəticə: server tərəfdə HEÇ BİR aktiv proses, cron və ya Edge Function tələb
olunmur. Avtomatik dayanma sadəcə TARİX MÜQAYİSƏSİDİR və müştərinin öz
kompüterində baş verir.

──────────────────────────────────────────────────────────────────────────────
ƏSAS İNVARİANT: TƏTBİQİ NƏ BAĞLAYIR, NƏ BAĞLAMIR
──────────────────────────────────────────────────────────────────────────────
    tətbiq TAM bağlanır  ⟺  status DEAKTIV-dir  VƏ YA  `expires_at` keçib

Hər iki səbəb DƏQİQ VƏ YOXLANILA BİLƏNDİR. Bunlardan başqa heç nə bağlamır:
şəbəkə kəsilməsi, Supabase-in əlçatmazlığı, DNS problemi, sorğu xətası —
HEÇ BİRİ. Səbəb kommersiyadır: 21 filialda 60+ işçinin davamiyyəti bu
proqramla qeyd olunur; bazanın bir saatlıq nasazlığı bütün şəbəkəni
dayandırsaydı, məhsul bir hadisədən sonra etibarını itirərdi.

──────────────────────────────────────────────────────────────────────────────
NİYƏ KEŞLƏNMİŞ "BAĞLIDIR" KÖHNƏLMİR
──────────────────────────────────────────────────────────────────────────────
Simmetrik görünən, lakin YANLIŞ olan qayda: "keşlənmiş cavab köhnəldikdə
xəbərdarlığa keçsin". Bu, blokdan qurtulmağın ən ucuz yolunu yaradardı —
şəbəkə kabelini çıxarmaq. Ona görə `AKTIV` köhnəlir (offline qrace bitir →
xəbərdarlıq), `DEAKTIV` və keçmiş `expires_at` isə KÖHNƏLMİR.

──────────────────────────────────────────────────────────────────────────────
SAAT MANİPULYASİYASI VƏ `expires_at`
──────────────────────────────────────────────────────────────────────────────
Müddət bitməsi divar saatı ilə yoxlanılır, yəni saatı geri çəkmək ən aydın
yan keçmə yoludur. Ona görə müqayisə `max(indi, indiyədək görülmüş ən böyük
an)` ilə aparılır: saat geri çəkilsə də "görülmüş" an geri qayıtmır və
müddəti bitmiş lisenziya yenidən açılmır.

──────────────────────────────────────────────────────────────────────────────
ÜÇ MƏHDUD-REJİM STATUSU (bölmə 8, "qarışdırılmamalıdır")
──────────────────────────────────────────────────────────────────────────────
    TIME_DRIFT_DETECTED   PC saatı NTP-dən 60 s+ fərqlənir (bölmə 2)
                          → YALNIZ vaxt-kritik əməliyyatlar (PIN handshake,
                            override) bloklanır, qalan hər şey işləyir
    LICENSE_UNVERIFIED    bazaya uzun müddət çatılmır
                          → yalnız XƏBƏRDARLIQ, heç nə bloklanmır
    LICENSE_INACTIVE      status DEAKTIV və ya müddət bitib
                          → tətbiq TAM bağlanır (PIN handshake daxil)

Üçü bir-birini əvəz etmir — eyni anda hamısı aktiv ola bilər və UI hər birini
öz mətni ilə göstərməlidir. Ona görə burada "tək status" deyil, ayrı-ayrı
məhdudiyyətlər çoxluğu modelləşdirilir.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any, Final

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.shared.exceptions import KompasOSError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.domain.value_objects.identifiers import TenantId

# --------------------------------------------------------------------------- #
# ROOT PARAMETRLƏRİNİN FALLBACK DƏYƏRLƏRİ (Faza 10.2)
# --------------------------------------------------------------------------- #
# Aşağıdakı doqquz sabitin HƏQİQİ MƏNBƏYİ `system_limits` cədvəlidir
# (`SystemLimitKey.LICENSE_*`, seed: migrations/033) — burada yalnız DB sətri
# oxunmadıqda (ilk işə düşmə, bağlantı yoxdur, sətir hələ seed edilməyib) işə
# düşən fallback saxlanılır və ədəd `DEFAULT_LIMITS`-dən gəlir, bu faylda
# YAZILMIR. Naxış `domain.labor_rules.LaborLimits.defaults()` ilə eynidir.
#
# NİYƏ LİSENZİYA RİTMİ KONFİQURASİYA EDİLİR, LAKİN İNVARİANT YOX: yoxlama
# TEZLİYİ kommersiya/şəbəkə qərarıdır; "nə vaxt bloklanır" qaydası (status
# DEAKTIV və ya `expires_at` keçib) isə yuxarıdakı əsas invariantdır və HEÇ
# BİR limitlə söndürülə bilməz.

#: Dövri yoxlama aralığı — spesifikasiya bölmə 8: "məs. hər 24 saatda".
DEFAULT_CHECK_IN_INTERVAL_SECONDS: Final[float] = float(
    DEFAULT_LIMITS[SystemLimitKey.LICENSE_CHECK_IN_INTERVAL_SECONDS]
)

#: Bazaya çatılmadıqda növbəti cəhdə qədər gözləmə. Sutkalıq intervaldan
#: KİÇİKDİR: qrace sayğacı işləyərkən hər saat yenidən cəhd etmək məntiqlidir,
#: 24 saat gözləmək isə bərpa olunmuş şəbəkəni bir gün gec görmək deməkdir.
RETRY_INTERVAL_SECONDS: Final[float] = float(
    DEFAULT_LIMITS[SystemLimitKey.LICENSE_RETRY_INTERVAL_SECONDS]
)

#: TƏTBİQ BLOKLANMIŞ vəziyyətdə yoxlama aralığı — "Force Sync"in serversiz
#: qarşılığı (bölmə 8).
#:
#: Developer Paneli `[1 Ay Uzat]`-a basanda dəyişiklik DƏRHAL Supabase-dədir,
#: lakin tenant onu yalnız öz növbəti yoxlamasında görür. Sutkalıq ritmlə bu,
#: ödənişi edib telefonda gözləyən müştəri üçün 24 saata qədər bağlı mağaza
#: deməkdir. Ona görə BLOKLANMIŞ vəziyyətdə ritm sıxlaşır: sorğu ucuzdur (bir
#: sətir oxunur) və yalnız artıq işləməyən quraşdırmalarda baş verir — yəni
#: normal iş rejiminə heç bir əlavə yük düşmür.
BLOCKED_RECHECK_INTERVAL_SECONDS: Final[float] = float(
    DEFAULT_LIMITS[SystemLimitKey.LICENSE_BLOCKED_RECHECK_INTERVAL_SECONDS]
)

#: `license_tenants.offline_grace_days` CHECK-i 7–14 aralığındadır (bölmə 8).
#: Root bandı YALNIZ DARALDA bilər — migrations/033-dəki `max_value` 14-də
#: kilidlidir, çünki sütunun öz CHECK-i onsuz da 14-dən böyüyünü qəbul etmir
#: və iki mənbənin fərqlənməsi "niyə saxlanmadı?" sualını doğurardı.
MIN_OFFLINE_GRACE_DAYS: Final[int] = int(
    DEFAULT_LIMITS[SystemLimitKey.LICENSE_MIN_OFFLINE_GRACE_DAYS]
)
MAX_OFFLINE_GRACE_DAYS: Final[int] = int(
    DEFAULT_LIMITS[SystemLimitKey.LICENSE_MAX_OFFLINE_GRACE_DAYS]
)
DEFAULT_OFFLINE_GRACE_DAYS: Final[int] = int(
    DEFAULT_LIMITS[SystemLimitKey.LICENSE_DEFAULT_OFFLINE_GRACE_DAYS]
)

#: "[1 Ay Uzat]" düyməsinin əlavə etdiyi gün sayı (Developer Paneli).
EXTENSION_DAYS: Final[int] = int(DEFAULT_LIMITS[SystemLimitKey.LICENSE_EXTENSION_DAYS])

#: Saatın geri çəkilməsi bu qədər fərqdən sonra "manipulyasiya" sayılır.
#: NTP düzəlişi, yay/qış saatı və ya adi sinxronizasiya bir neçə saniyə
#: geri sıçraya bilər — bunu manipulyasiya kimi qeyd etmək yalançı həyəcandır.
#:
#: BU AÇARIN TAVANI SƏRTDİR (migrations/033: 30–900 san). Səbəb: tolerantlıq
#: müddət bitməsinin yeganə ölçü qoruyucusudur — "6 saat" yazılsaydı, saatı
#: hər gün 6 saat geri çəkməklə bitmiş lisenziya süründürülə bilərdi, yəni
#: Root parametri qorumanı FAKTİKİ söndürərdi. 15 dəqiqəlik tavan yalançı
#: həyəcanı (NTP sıçrayışı saniyələrlə ölçülür) örtməyə kifayətdir.
CLOCK_ROLLBACK_TOLERANCE_SECONDS: Final[float] = float(
    DEFAULT_LIMITS[SystemLimitKey.LICENSE_CLOCK_ROLLBACK_TOLERANCE_SECONDS]
)

#: Müddətin bitməsinə bu qədər gün qalanda istifadəçiyə xatırladılır.
EXPIRY_WARNING_DAYS: Final[int] = int(DEFAULT_LIMITS[SystemLimitKey.LICENSE_EXPIRY_WARNING_DAYS])


@dataclass(frozen=True)
class LicenseLimits:
    """Lisenziya qaydalarının BEŞ ROOT parametri, bir dəfə oxunmuş halda.

    ────────────────────────────────────────────────────────────────────────
    NİYƏ PARAMETR OBYEKTİ, NİYƏ MODUL SABİTİ DEYİL
    ────────────────────────────────────────────────────────────────────────
    Yuxarıdakı sabitlər `DEFAULT_LIMITS`-dən qidalanır, yəni ROOT ekranında
    açar GÖRÜNÜR — lakin `evaluate()`/`payment_warning()` onları BİRBAŞA
    oxuduğu üçün Root dəyəri dəyişdirsə də heç nə baş vermirdi ("görünür,
    dəyişdirilir, təsirsiz" qüsuru). İndi funksiyalar dəyəri PARAMETR kimi
    alır; oxunu çağıran tərəf (infrastruktur klienti) edir, domen isə DB-yə
    toxunmur (CLAUDE.md §3). Naxış `labor_rules.LaborLimits.defaults()` və
    `attrition_rules.AttritionWeights.defaults()` ilə eynidir.

    ────────────────────────────────────────────────────────────────────────
    NİYƏ YARARSIZ DƏYƏR SƏSSİZCƏ DÜZƏLDİLİR
    ────────────────────────────────────────────────────────────────────────
    ROOT ekranı bandları ilə qoruyur, lakin ekranı yan keçən skript `0` və ya
    tərs aralıq (`min > max`) yaza bilər. Belə dəyər qrace hesabını sıfıra
    endirib bütün quraşdırmaları "lisenziya təsdiqlənməyib" xəbərdarlığına
    salardı — yəni bir səhv sətir bütün şəbəkəyə banner asardı. Ona görə
    dəyərlər burada normallaşdırılır (`LaborLimits.__post_init__` fəlsəfəsi).
    """

    min_offline_grace_days: int
    max_offline_grace_days: int
    default_offline_grace_days: int
    expiry_warning_days: int
    extension_days: int

    def __post_init__(self) -> None:
        low = max(1, self.min_offline_grace_days)
        # Tərs aralıqda tavan dibə çəkilir — `min(max, x)` sonra `max(min, ·)`
        # ardıcıllığı olmasaydı nəticə min-dən KİÇİK ola bilərdi.
        high = max(low, self.max_offline_grace_days)
        object.__setattr__(self, "min_offline_grace_days", low)
        object.__setattr__(self, "max_offline_grace_days", high)
        object.__setattr__(
            self, "default_offline_grace_days", max(low, min(high, self.default_offline_grace_days))
        )
        # SIFIR QƏBUL EDİLİR: "xəbərdarlıq istəmirəm" real seçimdir və onun
        # üçün ayrıca Feature Toggle yaratmaq lazım deyil (`LaborLimits`-də
        # "SIFIR = QAYDA SUSUR" ilə eyni əsaslandırma). Mənfi isə mənasızdır.
        object.__setattr__(self, "expiry_warning_days", max(0, self.expiry_warning_days))
        # Uzatma isə sıfır OLA BİLMƏZ: «[1 Ay Uzat]» düyməsi basılıb heç nə
        # etməsəydi, ödənişi edən müştəri hələ də bağlı qalar və dərhal zəng
        # gələrdi (bax `extend_by_month` başlığı).
        object.__setattr__(self, "extension_days", max(1, self.extension_days))

    @classmethod
    def defaults(cls) -> LicenseLimits:
        """`DEFAULT_LIMITS` dəyərləri — YALNIZ fallback.

        HƏQİQİ MƏNBƏ `system_limits`-dir (migrations/033 seed edir); bu metod
        limit portu olmayan çağırış yollarında (ilk işə düşmə, offline, saf
        qayda testi) işlədilir.
        """
        return cls(
            min_offline_grace_days=MIN_OFFLINE_GRACE_DAYS,
            max_offline_grace_days=MAX_OFFLINE_GRACE_DAYS,
            default_offline_grace_days=DEFAULT_OFFLINE_GRACE_DAYS,
            expiry_warning_days=EXPIRY_WARNING_DAYS,
            extension_days=EXTENSION_DAYS,
        )


class LicenseError(KompasOSError):
    """Lisenziya alt sistemi ilə bağlı ümumi xəta."""

    user_message = "Lisenziya yoxlanışında problem yarandı."


class LicenseUnavailableError(LicenseError):
    """Lisenziya sətrini oxumaq mümkün olmadı (şəbəkə, baza, RLS).

    BU XƏTA TƏTBİQİ BAĞLAMIR — yuxarıdakı əsas invariant. Offline qrace
    sayğacı işə düşür və istifadəçi işini davam etdirir.
    """

    user_message = "Lisenziya məlumatı oxuna bilmədi. Proqram normal işləməyə davam edir."


class LicenseNotFoundError(LicenseError):
    """Tenant sətri tapılmadı — səhv `tenant_id` və ya RLS bloku.

    Bu da bağlamır: quraşdırma zamanı bir hərf səhv yazılmış ID bütün
    şəbəkəni dayandırsaydı, ilk günün özü fəlakət olardı. Nəticə —
    `LICENSE_UNVERIFIED` xəbərdarlığı + təhlükəsizlik jurnalına yazı.
    """

    user_message = (
        "Lisenziya qeydi tapılmadı. Quraşdırma parametrlərini yoxlayın "
        "və ya təchizatçı ilə əlaqə saxlayın."
    )


class LicenseStatus(str, Enum):
    """`license_status` DB enum-u ilə eyni dəyərlər (bölmə 8).

    TƏLƏBDƏKİ AD UYĞUNLUĞU: yeni tələbdə status "ACTIVE/INACTIVE" kimi
    yazılıb. Mövcud baza enum-u üç dəyərlidir və DƏYİŞDİRİLMİR:

        ACTIVE   ≙ `AKTIV`
        INACTIVE ≙ `DEAKTIV`
        (əlavə)  `ODENIS_GOZLENILIR` — bölmə 8-dəki ödəniş-güzəşti vəziyyəti

    İki dəyərə endirmək mövcud sütunu, indeksləri və `cron_update_license_
    payment_status()` funksiyasını sındırardı, əvəzində isə heç nə
    qazandırmazdı: `ODENIS_GOZLENILIR` bloklamır, yalnız xəbərdarlıq verir.
    """

    AKTIV = "AKTIV"
    ODENIS_GOZLENILIR = "ODENIS_GOZLENILIR"
    DEAKTIV = "DEAKTIV"

    @property
    def blocks_application(self) -> bool:
        """Yalnız `DEAKTIV` tətbiqi bağlayır (müddət bitməsi ayrıca yoxlanılır)."""
        return self is LicenseStatus.DEAKTIV

    @property
    def label_az(self) -> str:
        return {
            LicenseStatus.AKTIV: "Aktiv",
            LicenseStatus.ODENIS_GOZLENILIR: "Ödəniş Gözlənilir",
            LicenseStatus.DEAKTIV: "Deaktiv",
        }[self]


class RestrictionKind(str, Enum):
    """Bölmə 8-dəki üç məhdud-rejim statusu."""

    TIME_DRIFT_DETECTED = "TIME_DRIFT_DETECTED"
    LICENSE_UNVERIFIED = "LICENSE_UNVERIFIED"
    LICENSE_INACTIVE = "LICENSE_INACTIVE"

    @property
    def blocks_everything(self) -> bool:
        """Tətbiqin TAMAMINI bağlayırmı (heç bir modul, PIN handshake daxil)."""
        return self is RestrictionKind.LICENSE_INACTIVE

    @property
    def blocks_time_critical(self) -> bool:
        """Vaxt-kritik əməliyyatları (PIN handshake, override) bloklayırmı."""
        return self in {
            RestrictionKind.TIME_DRIFT_DETECTED,
            RestrictionKind.LICENSE_INACTIVE,
        }


@dataclass(frozen=True)
class Restriction:
    """Bir aktiv məhdudiyyət — UI onu öz mətni ilə göstərir.

    `headline`/`detail` QƏSDƏN burada, domendə formalaşır: bölmə 8 ekranın
    məzmununu funksional tələb kimi yazır ("səbəbi, son ödəniş tarixini və
    əlaqə vasitəsini açıq göstərməlidir"), yəni bu mətn UI bəzəyi deyil.
    """

    kind: RestrictionKind
    headline_az: str
    detail_az: str
    #: `LICENSE_INACTIVE` ekranında göstərilən əlaqə (bölmə 8).
    contact_az: str = ""

    @property
    def blocks_everything(self) -> bool:
        return self.kind.blocks_everything

    @property
    def blocks_time_critical(self) -> bool:
        return self.kind.blocks_time_critical


@dataclass(frozen=True)
class Telemetry:
    """Check-in ilə yazılan AQREQASİYA göstəriciləri (bölmə 8).

    ────────────────────────────────────────────────────────────────────────
    NİYƏ BU SİNİF YALNIZ `int` SAXLAYIR
    ────────────────────────────────────────────────────────────────────────
    Spesifikasiya: *"heç bir halda işçi PII-sinə uzaqdan çıxış YOXDUR"*.
    Sahələri sərbəst `dict` kimi saxlamaq bir gün kiminsə ora ad/e-poçt
    əlavə etməsini yalnız kod-baxışının diqqətindən asılı edərdi. Tip
    səviyyəsində yalnız sayğac saxlamaqla bu, struktur olaraq mümkünsüz olur.
    """

    active_users: int = 0
    store_count: int = 0
    erp_server_count: int = 0
    pending_sync_count: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "active_users": self.active_users,
            "store_count": self.store_count,
            "erp_server_count": self.erp_server_count,
            "pending_sync_count": self.pending_sync_count,
        }


@dataclass(frozen=True)
class LicenseSnapshot:
    """`license_tenants`-dəki öz sətrinin son oxunuşu (yerli olaraq keşlənir).

    `checked_at` — sətrin OXUNDUĞU an (yerli saat). Offline qrace məhz
    bundan hesablanır.
    """

    status: LicenseStatus
    checked_at: datetime
    tenant_name: str = ""
    #: AVTOMATİK DAYANMANIN yeganə mənbəyi. `None` = müddət təyin edilməyib
    #: (yalnız `status` işləyir) — köhnə qeydlərlə uyğunluq üçün.
    expires_at: datetime | None = None
    last_payment_date: date | None = None
    next_payment_date: date | None = None
    grace_period_days: int = 7
    offline_grace_days: int = DEFAULT_OFFLINE_GRACE_DAYS
    deactivation_reason: str = ""
    #: Bloklama ekranında göstərilən TƏCHİZATÇI əlaqəsi (müştərinin öz
    #: `company_contact_email`-i DEYİL — müştəri özü-özünə yaza bilməz).
    vendor_contact: str = ""

    def __post_init__(self) -> None:
        if self.checked_at.tzinfo is None:
            msg = "checked_at tz-aware olmalıdır (UTC)."
            raise ValueError(msg)
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            msg = "expires_at tz-aware olmalıdır (UTC)."
            raise ValueError(msg)

    def offline_grace_days_within(self, limits: LicenseLimits) -> int:
        """ROOT bandına sıxılmış qrace — həqiqi mənbə `system_limits`."""
        return max(
            limits.min_offline_grace_days,
            min(limits.max_offline_grace_days, self.offline_grace_days),
        )

    @property
    def effective_offline_grace_days(self) -> int:
        """FALLBACK yolu: DB CHECK-i (7–14) ilə eyni aralığa sıxılmış qrace.

        Limit portu olmayan çağırışlar üçün qalır; Root bandını nəzərə alan
        yol `offline_grace_days_within(...)`-dir.
        """
        return self.offline_grace_days_within(LicenseLimits.defaults())

    def has_expired(self, now: datetime) -> bool:
        """Müddət bitibmi. Müddət yoxdursa HEÇ VAXT bitmir."""
        return self.expires_at is not None and now >= self.expires_at

    def days_remaining(self, now: datetime) -> int | None:
        """Müddətin bitməsinə qalan tam gün; müddət yoxdursa `None`.

        Keçmiş müddət üçün MƏNFİ qaytarılır — Developer Panelində "12 gün
        gecikib" kimi göstərmək üçün.
        """
        if self.expires_at is None:
            return None
        return (self.expires_at - now).days

    def age_at(self, now: datetime) -> timedelta:
        """Oxunuşun yaşı. Saat geri çəkilibsə mənfi ola bilər — qərarı
        `evaluate()` verir."""
        return now - self.checked_at

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "checked_at": self.checked_at.isoformat(),
            "tenant_name": self.tenant_name,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "last_payment_date": self.last_payment_date.isoformat()
            if self.last_payment_date
            else None,
            "next_payment_date": self.next_payment_date.isoformat()
            if self.next_payment_date
            else None,
            "grace_period_days": self.grace_period_days,
            "offline_grace_days": self.offline_grace_days,
            "deactivation_reason": self.deactivation_reason,
            "vendor_contact": self.vendor_contact,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], *, checked_at: datetime) -> LicenseSnapshot:
        """Baza sətrindən (və ya yerli keşdən) qurur.

        Naməlum status dəyəri `DEAKTIV` kimi OXUNMUR — `ODENIS_GOZLENILIR`-ə
        düşür. Səbəb: sxemanın gələcək versiyasının yeni status adı bütün
        quraşdırmaları bağlamamalıdır (yenə əsas invariant).
        """
        raw_status = str(payload.get("status", "")).strip().upper()
        try:
            status = LicenseStatus(raw_status)
        except ValueError:
            status = LicenseStatus.ODENIS_GOZLENILIR

        return cls(
            status=status,
            checked_at=_parse_moment(payload.get("checked_at")) or checked_at,
            tenant_name=str(payload.get("tenant_name") or ""),
            expires_at=_parse_moment(payload.get("expires_at")),
            last_payment_date=_parse_date(payload.get("last_payment_date")),
            next_payment_date=_parse_date(payload.get("next_payment_date")),
            grace_period_days=_parse_int(payload.get("grace_period_days"), default=7),
            offline_grace_days=_parse_int(
                payload.get("offline_grace_days"), default=DEFAULT_OFFLINE_GRACE_DAYS
            ),
            deactivation_reason=str(payload.get("deactivation_reason") or ""),
            vendor_contact=str(payload.get("vendor_contact") or ""),
        )


@dataclass(frozen=True)
class LicenseState:
    """Hesablanmış cari vəziyyət — UI və icazə yoxlamaları bunu oxuyur."""

    snapshot: LicenseSnapshot | None
    restrictions: tuple[Restriction, ...] = ()
    #: Offline qrace bitənə qədər qalan tam gün sayı; qrace işləmirsə `None`.
    offline_grace_days_left: int | None = None
    #: Lisenziya müddətinin bitməsinə qalan gün (mənfi = keçib); yoxdursa `None`.
    license_days_left: int | None = None
    #: Saatın geri çəkildiyi aşkarlanıbmı (müddət/qrace sui-istifadəsi cəhdi).
    clock_rollback_detected: bool = False

    @property
    def is_blocked(self) -> bool:
        """Tətbiq TAM bağlıdırmı."""
        return any(item.blocks_everything for item in self.restrictions)

    @property
    def time_critical_blocked(self) -> bool:
        """PIN handshake / override kimi əməliyyatlar bloklanıbmı."""
        return any(item.blocks_time_critical for item in self.restrictions)

    @property
    def blocking_restriction(self) -> Restriction | None:
        """Bloklama ekranında göstəriləcək məhdudiyyət."""
        return next((item for item in self.restrictions if item.blocks_everything), None)

    def has(self, kind: RestrictionKind) -> bool:
        return any(item.kind is kind for item in self.restrictions)


@dataclass(frozen=True)
class CheckInRequest:
    """Dövri yoxlama sorğusu — sətri oxuyur və `last_check_in_at`-i yeniləyir."""

    tenant_id: TenantId
    app_version: str
    telemetry: Telemetry = field(default_factory=Telemetry)


@dataclass(frozen=True)
class CrashReport:
    """Anonimləşdirilmiş crash hesabatı (bölmə 8).

    `anonymous_tenant_ref` — `tenant_id`-nin hash-ı, ID-nin ÖZÜ DEYİL
    (`crash_reports` cədvəlinin şərhi ilə eyni qayda).
    """

    anonymous_tenant_ref: str
    app_version: str
    exception_type: str
    stack_trace: str
    fingerprint: str
    os_version: str = ""


def anonymous_tenant_ref(tenant_id: TenantId) -> str:
    """`tenant_id` → sabit, geri-çevrilməyən referans.

    Developer Panelində crash-lər tenant-a görə qruplaşdırılmalıdır, lakin
    hesabatın özündə real ID getməməlidir. SHA-256 determinstikdir (eyni
    tenant həmişə eyni referans) və geri çevrilmir.
    """
    return hashlib.sha256(f"kompasos-tenant:{tenant_id}".encode()).hexdigest()[:32]


def extend_by_month(
    current_expires_at: datetime | None,
    *,
    now: datetime,
    limits: LicenseLimits | None = None,
) -> datetime:
    """ "[1 Ay Uzat]" düyməsinin hesablaması — defolt 30 gün.

    ────────────────────────────────────────────────────────────────────────
    NİYƏ SADƏCƏ `expires_at + 30` DEYİL
    ────────────────────────────────────────────────────────────────────────
    Müddət artıq keçibsə (müştəri gec ödəyib), sadə toplama "mənfi qalıq"
    yığardı: 40 gün gecikmiş tenant-a 30 gün əlavə etmək onu HƏLƏ DƏ bağlı
    saxlayardı və düymə "işləmirmiş" kimi görünərdi — sizə dərhal zəng gələrdi.
    Ona görə başlanğıc nöqtəsi `max(indi, cari müddət)`-dir.

    `limits` `None` olduqda `LICENSE_EXTENSION_DAYS`-in fallback dəyəri
    işləyir — davranış köçürmədən ƏVVƏLKİ ilə eynidir.
    """
    window = limits or LicenseLimits.defaults()
    base = current_expires_at if current_expires_at and current_expires_at > now else now
    return base + timedelta(days=window.extension_days)


# --------------------------------------------------------------------------- #
# Vəziyyət hesablanması — modulun məntiqi mərkəzi
# --------------------------------------------------------------------------- #


def evaluate(
    snapshot: LicenseSnapshot | None,
    *,
    now: datetime,
    first_run_at: datetime | None = None,
    clock_high_water: datetime | None = None,
    clock_rollback: bool = False,
    time_drift_seconds: float | None = None,
    dev_mode: bool = False,
    limits: LicenseLimits | None = None,
) -> LicenseState:
    """Keşlənmiş sətirdən + saat vəziyyətindən cari məhdudiyyətləri hesablayır.

    Saf funksiyadır (I/O yoxdur) — bütün sərhəd halları baza və şəbəkə
    olmadan test olunur.

    Args:
        snapshot: Son uğurlu oxunuş; heç vaxt olmayıbsa `None`.
        now: Cari an (tz-aware).
        first_run_at: Tətbiqin bu PC-də ilk işə düşməsi — `snapshot` `None`
            olduqda qrace bundan hesablanır.
        clock_high_water: İndiyədək görülmüş ən böyük an. Müddət müqayisəsi
            `max(now, clock_high_water)` ilə aparılır ki, saatı geri çəkməklə
            bitmiş lisenziya yenidən açılmasın.
        clock_rollback: Yerli saatın geri çəkildiyi aşkarlanıb.
        time_drift_seconds: NTP sürüşməsi hədd aşıbsa dəyəri, əks halda `None`.
        dev_mode: `KOMPASOS_ENV=DEV` — seed tenant (Faza 1) üçün lisenziya
            yoxlaması testləri dayandırmamalıdır.
        limits: ROOT-un offline qrace bandı. `None` = fallback (`DEFAULT_LIMITS`),
            yəni köçürmədən ƏVVƏLKİ davranışın eynisi.
    """
    window = limits or LicenseLimits.defaults()
    restrictions: list[Restriction] = []
    # Saat geri çəkilsə də "görülmüş" an geri qayıtmır (bax modul başlığı).
    effective_now = max(now, clock_high_water) if clock_high_water else now

    if time_drift_seconds is not None:
        restrictions.append(_time_drift_restriction(time_drift_seconds))

    if dev_mode:
        # DEV-də lisenziya heç vaxt bloklamır (bax Faza 1 seed tenant qeydi),
        # lakin NTP sürüşməsi qalır — saat məntiqinin özü DEV-də də test
        # olunmalıdır, əks halda səhv yalnız istehsalatda üzə çıxardı.
        return LicenseState(snapshot=snapshot, restrictions=tuple(restrictions))

    if snapshot is None:
        return _never_checked_in(
            restrictions,
            now=now,
            first_run_at=first_run_at,
            clock_rollback=clock_rollback,
            limits=window,
        )

    days_left = snapshot.days_remaining(effective_now)

    if snapshot.status.blocks_application or snapshot.has_expired(effective_now):
        # Keşlənmiş bloklama KÖHNƏLMİR (bax modul başlığı).
        restrictions.append(_inactive_restriction(snapshot, now=effective_now))
        return LicenseState(
            snapshot=snapshot,
            restrictions=tuple(restrictions),
            license_days_left=days_left,
            clock_rollback_detected=clock_rollback,
        )

    grace = timedelta(days=snapshot.offline_grace_days_within(window))
    age = snapshot.age_at(now)
    expired_grace = clock_rollback or age < timedelta(0) or age > grace

    if expired_grace:
        restrictions.append(_unverified_restriction(snapshot, age=age, rollback=clock_rollback))
        grace_left = 0
    else:
        grace_left = max(0, (grace - age).days)

    return LicenseState(
        snapshot=snapshot,
        restrictions=tuple(restrictions),
        offline_grace_days_left=grace_left,
        license_days_left=days_left,
        clock_rollback_detected=clock_rollback,
    )


def _never_checked_in(
    restrictions: list[Restriction],
    *,
    now: datetime,
    first_run_at: datetime | None,
    clock_rollback: bool,
    limits: LicenseLimits,
) -> LicenseState:
    """Heç vaxt uğurlu oxunuş olmayıb — quraşdırma günü və ya sınıq şəbəkə.

    Bloklamır (əsas invariant), lakin qrace ilk işə düşmə anından sayılır ki,
    "heç vaxt qoşulmamış" quraşdırma sonsuza qədər səssiz qalmasın.

    Burada `default_offline_grace_days` işlədilir, `min/max` bandı YOX:
    snapshot olmadığı üçün sıxılacaq dəyər də yoxdur.
    """
    grace = timedelta(days=limits.default_offline_grace_days)
    age = (now - first_run_at) if first_run_at is not None else timedelta(0)
    if clock_rollback or age > grace:
        restrictions.append(
            Restriction(
                kind=RestrictionKind.LICENSE_UNVERIFIED,
                headline_az="Lisenziya təsdiqlənməyib",
                detail_az=(
                    "Quraşdırmadan bəri lisenziya qeydini oxumaq mümkün olmayıb. "
                    "İnternet bağlantısını və quraşdırma parametrlərini yoxlayın. "
                    "Proqram işləməyə davam edir."
                ),
            )
        )
        days_left = 0
    else:
        days_left = max(0, (grace - age).days)
    return LicenseState(
        snapshot=None,
        restrictions=tuple(restrictions),
        offline_grace_days_left=days_left,
        clock_rollback_detected=clock_rollback,
    )


def _time_drift_restriction(drift_seconds: float) -> Restriction:
    return Restriction(
        kind=RestrictionKind.TIME_DRIFT_DETECTED,
        headline_az="Kompüterin saatı düzgün deyil",
        detail_az=(
            f"Saat dəqiq vaxtdan təxminən {abs(drift_seconds) / 60:.0f} dəqiqə fərqlənir. "
            "Giriş/çıxış qeydiyyatı və təsdiq əməliyyatları saat düzələnə qədər "
            "müvəqqəti dayandırılıb. Qalan bölmələr normal işləyir."
        ),
    )


def _unverified_restriction(
    snapshot: LicenseSnapshot, *, age: timedelta, rollback: bool
) -> Restriction:
    if rollback:
        detail = (
            "Kompüterin saatı geriyə çəkilib — lisenziya yoxlanışı bu vəziyyətdə "
            "etibarlı deyil. Saatı düzəldin və internet bağlantısını yoxlayın. "
            "Proqram işləməyə davam edir."
        )
    else:
        detail = (
            f"Lisenziya qeydi ilə son əlaqə {max(0, age.days)} gün əvvəl olub və "
            "icazə verilən müddət keçib. İnternet bağlantısını yoxlayın. "
            "Məlumat itkisi yoxdur, proqram işləməyə davam edir."
        )
    return Restriction(
        kind=RestrictionKind.LICENSE_UNVERIFIED,
        headline_az="Lisenziya təsdiqlənə bilmir",
        detail_az=detail,
        contact_az=snapshot.vendor_contact,
    )


def _inactive_restriction(snapshot: LicenseSnapshot, *, now: datetime) -> Restriction:
    """Bölmə 8: ekran ümumi xəta mesajı OLMAMALIDIR — səbəb + tarix + əlaqə."""
    if snapshot.has_expired(now):
        reason = "Lisenziya müddəti başa çatıb."
    else:
        reason = snapshot.deactivation_reason.strip() or "Aylıq ödəniş qeydə alınmayıb."

    parts = [reason]
    if snapshot.expires_at is not None:
        parts.append(f"Lisenziyanın bitmə tarixi: {snapshot.expires_at:%d.%m.%Y}.")
    if snapshot.last_payment_date is not None:
        parts.append(f"Son ödəniş tarixi: {snapshot.last_payment_date:%d.%m.%Y}.")
    parts.append("Məlumatlarınız qorunur — ödəniş qeydə alındıqdan sonra proqram dərhal açılır.")
    return Restriction(
        kind=RestrictionKind.LICENSE_INACTIVE,
        headline_az="Ödəniş tələb olunur",
        detail_az=" ".join(parts),
        contact_az=snapshot.vendor_contact,
    )


def payment_warning(
    snapshot: LicenseSnapshot | None,
    *,
    now: datetime,
    limits: LicenseLimits | None = None,
) -> str:
    """ "ÖDƏNİŞ TƏLƏB OLUNUR" xəbərdarlığı — bloklamır (bölmə 8).

    Müddət bitməzdən ƏVVƏL istifadəçi xəbərdar edilir ki, bağlanma
    "birdən-birə" görünməsin. Müddət artıq bitibsə bu funksiya boş qaytarır —
    o hal artıq `LICENSE_INACTIVE` ekranıdır, banner deyil.

    Neçə gün əvvəldən xəbərdarlıq veriləcəyi (`LICENSE_EXPIRY_WARNING_DAYS`)
    Root parametridir: mühasibatı bir həftə əvvəldən xəbərdar etmək istəyən
    şəbəkə ilə ödənişi son gün edən şəbəkə eyni ritmi istəmir.
    """
    if snapshot is None:
        return ""

    window = limits or LicenseLimits.defaults()
    days_left = snapshot.days_remaining(now)
    if days_left is not None and 0 <= days_left <= window.expiry_warning_days:
        assert snapshot.expires_at is not None
        if days_left == 0:
            return "Lisenziyanın müddəti bu gün bitir. Fasiləsiz iş üçün ödənişi tamamlayın."
        return (
            f"Lisenziyanın müddətinin bitməsinə {days_left} gün qalır "
            f"({snapshot.expires_at:%d.%m.%Y}). Ödənişi vaxtında tamamlayın."
        )

    if snapshot.status is not LicenseStatus.ODENIS_GOZLENILIR:
        return ""
    return "Aylıq ödəniş gözlənilir. Xidmətin fasiləsizliyi üçün ödənişi tamamlayın."


def _parse_moment(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _parse_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "BLOCKED_RECHECK_INTERVAL_SECONDS",
    "CLOCK_ROLLBACK_TOLERANCE_SECONDS",
    "DEFAULT_CHECK_IN_INTERVAL_SECONDS",
    "DEFAULT_OFFLINE_GRACE_DAYS",
    "EXPIRY_WARNING_DAYS",
    "EXTENSION_DAYS",
    "MAX_OFFLINE_GRACE_DAYS",
    "MIN_OFFLINE_GRACE_DAYS",
    "RETRY_INTERVAL_SECONDS",
    "CheckInRequest",
    "CrashReport",
    "LicenseError",
    "LicenseLimits",
    "LicenseNotFoundError",
    "LicenseSnapshot",
    "LicenseState",
    "LicenseStatus",
    "LicenseUnavailableError",
    "Restriction",
    "RestrictionKind",
    "Telemetry",
    "anonymous_tenant_ref",
    "evaluate",
    "extend_by_month",
    "payment_warning",
]
