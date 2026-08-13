"""Avtomatik yenilənmənin domen tipləri (bölmə 1, 7, 8) — Faza 3.13.

Spesifikasiya: *"AVTOMATİK YENİLƏNMƏ: Təhlükəsizlik yamaqları müştərinin heç
bir əl əməyi olmadan arxa planda tətbiq olunur"*, *"`.exe` Authenticode ilə
imzalanmalıdır"*, *"Versiya məcburi yeniləməsini uzaqdan tetikləmək — bütün
tenant-lara və ya seçilmiş tenant-a"*.

──────────────────────────────────────────────────────────────────────────────
ARXİTEKTURA: YENƏ AYRICA SERVER YOXDUR — "PULL" MODELİ
──────────────────────────────────────────────────────────────────────────────
Lisenziya ilə eyni prinsip (bax `licensing.py`): buraxılış kataloqu mövcud
Supabase layihəsindəki `app_versions` cədvəlidir, quraşdırıcı faylın özü isə
`app-updates` (private) bucket-indədir. Nə CDN, nə update serveri, nə də
ayrıca domen lazımdır.

Paylanma İTƏLƏMƏ (push) deyil, DARTMA (pull) modelidir: hazırlayıcı BİR DƏFƏ
yükləyib kataloqa sətir əlavə edir, bütün tenant-lar isə öz növbəti
yoxlamalarında EYNİ mərkəzi cədvəldən özləri aşkar edir. Tenant-lara ayrıca
heç nə göndərilmir — 21 filiala 21 bildiriş göndərmək lazım gəlsəydi, biri
çatmayanda bunu heç kim bilməzdi; burada isə "çatmama" halı yoxdur, yalnız
"hələ yoxlamayıb" halı var və o da öz-özünə həll olunur.

──────────────────────────────────────────────────────────────────────────────
NİYƏ YENİLƏNMƏ LİSENZİYANIN ƏKSİNƏ "FAIL-CLOSED"-DUR
──────────────────────────────────────────────────────────────────────────────
Lisenziya qatının əsas qaydası fail-OPEN-dir: şübhə varsa BLOKLAMA, çünki
mağazanı dayandırmaq bahadır. Burada qayda TAM ƏKSİDİR: şübhə varsa TƏTBİQ
ETMƏ.

Fərqin səbəbi asimmetriyadır. Lisenziyada səhv qərar ən pisi bir günlük
ödənişsiz istifadədir. Burada isə səhv qərar — doğrulanmamış `.exe`-nin
icrası — 21 filialın hər kassa PC-sində ixtiyari kod icrası deməkdir. Ona görə:

    imza yoxlanıla bilmirsə  → yenilənmə TƏTBİQ EDİLMİR (köhnə versiya işləyir)
    checksum uyğun gəlmirsə  → fayl silinir, cəhd uğursuz sayılır
    versiya köhnəyə enirsə   → RƏDD EDİLİR (bax `decide`)

Yenilənməmək təhlükəsiz vəziyyətdir: proqram işləməyə davam edir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Final

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.shared.exceptions import KompasOSError

# --------------------------------------------------------------------------- #
# ROOT PARAMETRLƏRİNİN FALLBACK DƏYƏRLƏRİ (Faza 10.2)
# --------------------------------------------------------------------------- #
# Üç dəyərin HƏQİQİ MƏNBƏYİ `system_limits`-dir (`SystemLimitKey.UPDATE_*`,
# seed: migrations/033). Buradakı sabitlər yalnız fallback-dır və ədədi
# `DEFAULT_LIMITS`-dən oxuyur.
#
# DİQQƏT — FAIL-CLOSED QAYDASI PARAMETR DEYİL: imza/checksum/downgrade
# yoxlamaları (bax modul başlığı) heç bir limitlə söndürülmür. Konfiqurasiya
# edilən yalnız "nə vaxt yoxlayaq" və "nə qədər böyük faylı qəbul edək"dir.

#: Arxa fon yoxlaması aralığı — sutkada bir dəfə (lisenziya ilə eyni ritm).
DEFAULT_CHECK_INTERVAL_SECONDS: Final[float] = float(
    DEFAULT_LIMITS[SystemLimitKey.UPDATE_CHECK_INTERVAL_SECONDS]
)
#: Uğursuz cəhddən sonra gözləmə.
RETRY_INTERVAL_SECONDS: Final[float] = float(
    DEFAULT_LIMITS[SystemLimitKey.UPDATE_RETRY_INTERVAL_SECONDS]
)

#: Quraşdırıcının bucket-dəki sabit adı. Versiya QOVLUQ adındadır, fayl adında
#: DEYİL: `1.4.0/KompasOS-Setup.exe`. Belə olduqda köhnə buraxılışlar bir-birini
#: əvəz etmir (geri qaytarma üçün lazımdır) və eyni zamanda hər versiyanın yolu
#: təxmin edilə bilən qalır — dəstək zəngində "hansı fayl?" sualı yaranmır.
DEFAULT_PACKAGE_FILENAME: Final[str] = "KompasOS-Setup.exe"

#: Quraşdırıcının maksimum ölçüsü — gözlənilməz nəhəng fayl diski doldurmasın.
#: FALLBACK — HƏQİQİ MƏNBƏ `system_limits.UPDATE_MAX_PACKAGE_BYTES`.
MAX_PACKAGE_BYTES: Final[int] = int(DEFAULT_LIMITS[SystemLimitKey.UPDATE_MAX_PACKAGE_BYTES])

#: SHA-256 daycestinin onaltılıq uzunluğu.
SHA256_HEX_LENGTH: Final[int] = 64
_HEX_DIGITS: Final[frozenset[str]] = frozenset("0123456789abcdef")

_VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\s*v?(\d+)\.(\d+)\.(\d+)(?:[-+]([0-9A-Za-z.\-]+))?\s*$"
)


class UpdateError(KompasOSError):
    """Yenilənmə ilə bağlı ümumi xəta."""

    user_message = "Proqram yenilənməsi tamamlanmadı."


class UpdateUnavailableError(UpdateError):
    """Buraxılış kataloquna və ya fayla çatmaq mümkün olmadı.

    Bu, TƏTBİQİ POZMUR — mövcud versiya işləməyə davam edir və növbəti dövrdə
    yenidən cəhd edilir.
    """

    user_message = "Yeniləmə serverinə çatmaq mümkün olmadı. Proqram normal işləyir."


class ChecksumMismatchError(UpdateError):
    """Yüklənən faylın SHA-256-sı kataloqdakı dəyərlə uyğun gəlmir."""

    user_message = (
        "Yükləmə tamamlanmadı — fayl zədələnib. Yenilənmə tətbiq edilmədi, "
        "proqram cari versiyada işləməyə davam edir."
    )


class SignatureRejectedError(UpdateError):
    """Authenticode imzası yoxdur, etibarsızdır və ya naşir gözlənilən deyil.

    KRİTİK: bu xəta heç vaxt "xəbərdarlıqla davam et" kimi işlənmir
    (bax modul başlığındakı fail-closed izahı).
    """

    user_message = (
        "Yeniləmə faylının rəqəmsal imzası doğrulanmadı — təhlükəsizlik "
        "səbəbindən tətbiq edilmədi. Təchizatçı ilə əlaqə saxlayın."
    )


class InvalidVersionError(UpdateError):
    """Versiya sətri oxuna bilmədi."""

    user_message = "Versiya məlumatı oxuna bilmədi."


@dataclass(frozen=True, order=True)
class Version:
    """`MAJOR.MINOR.PATCH` semantik versiya.

    `order=True` sahə sırasına görə müqayisə verir: major → minor → patch →
    suffix. Suffiks (`-rc1`) MÜQAYİSƏYƏ DAXİLDİR, lakin sadə leksik qaydada —
    tam SemVer prerelease qaydası tətbiq edilmir, çünki bu layihədə yalnız
    `stable` və `beta` kanalları var və beta versiyalar ayrıca kanalda gedir.
    """

    major: int
    minor: int
    patch: int
    suffix: str = ""

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return f"{base}-{self.suffix}" if self.suffix else base

    @classmethod
    def parse(cls, raw: str) -> Version:
        match = _VERSION_PATTERN.match(raw or "")
        if match is None:
            raise InvalidVersionError(f"Versiya formatı tanınmadı: {raw!r}", context={"value": raw})
        major, minor, patch, suffix = match.groups()
        return cls(int(major), int(minor), int(patch), suffix or "")

    @classmethod
    def try_parse(cls, raw: str) -> Version | None:
        try:
            return cls.parse(raw)
        except InvalidVersionError:
            return None

    def is_newer_than(self, other: Version) -> bool:
        return self > other


class ReleaseChannel(str, Enum):
    """Buraxılış kanalı — müştərilər `STABLE`, daxili sınaq `BETA`."""

    STABLE = "STABLE"
    BETA = "BETA"


class UpdateAction(str, Enum):
    """`decide()` nəticəsi."""

    UP_TO_DATE = "UP_TO_DATE"
    #: İstifadəçi seçimi ilə tətbiq olunur.
    OPTIONAL = "OPTIONAL"
    #: Təhlükəsizlik yaması və ya Developer Panelindən məcburi edilib.
    MANDATORY = "MANDATORY"
    #: Kataloqda köhnə versiya göstərilib — RƏDD edilir.
    REFUSED_DOWNGRADE = "REFUSED_DOWNGRADE"


@dataclass(frozen=True)
class ReleaseInfo:
    """`app_versions` sətri — bir buraxılış.

    Sahə adları cədvəl sütunları ilə eynidir (`sha256` ↔ `sha256_hash` istisna
    olmaqla, bax `from_row`) ki, paneldə görünən dəyərlə bazadakı sətri
    tutuşdurmaq üçün tərcümə cədvəli lazım olmasın.
    """

    version: Version
    channel: ReleaseChannel
    #: Supabase Storage-dakı yol (bucket-daxili açar), məs. `1.4.0/KompasOS-Setup.exe`.
    storage_path: str
    sha256: str
    size_bytes: int = 0
    #: Developer Panelindəki "Məcburi Yeniləmədir" checkbox-u: bu buraxılışdan
    #: KÖHNƏ hər quraşdırma üçün məcburidir.
    is_mandatory: bool = False
    #: Məcburiliyin DAR variantı: yalnız bu versiyadan köhnələr üçün
    #: (məs. yalnız 1.3.x-də olan zəiflik). `None` = dar hədəf yoxdur.
    mandatory_below: Version | None = None
    release_notes: str = ""
    release_date: date | None = None
    published_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.storage_path.strip():
            msg = "storage_path boş ola bilməz."
            raise ValueError(msg)
        lowered = self.sha256.lower()
        if len(lowered) != SHA256_HEX_LENGTH or not _HEX_DIGITS.issuperset(lowered):
            msg = f"sha256 {SHA256_HEX_LENGTH} simvollu onaltılıq olmalıdır: {self.sha256!r}"
            raise ValueError(msg)
        if self.size_bytes < 0 or self.size_bytes > MAX_PACKAGE_BYTES:
            msg = f"size_bytes aralıqdan kənardır: {self.size_bytes}"
            raise ValueError(msg)

    @property
    def digest(self) -> str:
        return self.sha256.lower()

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ReleaseInfo:
        """DB sətrindən qurur; yararsız sətir `ValueError` verir.

        Köhnə (`version`/`sha256`/`release_notes_az`) adlar da qəbul edilir:
        miqrasiya 009 sütunları yenidən adlandırır, lakin hələ köçürülməmiş bir
        mühitdə klientin SÜKUTLA "yeni versiya yoxdur" deməsi ən pis nəticə
        olardı — təhlükəsizlik yaması çatmazdı və heç bir xəta görünməzdi.
        """
        return cls(
            version=Version.parse(str(_pick(row, "version_number", "version"))),
            channel=_channel_of(row.get("channel")),
            storage_path=str(row.get("storage_path") or ""),
            sha256=str(_pick(row, "sha256_hash", "sha256")),
            size_bytes=int(row.get("size_bytes") or 0),
            is_mandatory=bool(row.get("is_mandatory")),
            mandatory_below=Version.try_parse(str(row.get("mandatory_below") or "")),
            release_notes=str(_pick(row, "release_notes", "release_notes_az")),
            release_date=row.get("release_date"),
            published_at=row.get("published_at"),
        )


def storage_path_for(version: Version | str, *, filename: str = DEFAULT_PACKAGE_FILENAME) -> str:
    """Bucket-daxili yol: `{version}/{filename}`.

    Yolu TƏK bir yerdə hesablamaq vacibdir: yükləyən tərəf (Developer Paneli)
    və endirən tərəf (klient) fərqli düstur işlətsəydi, uyğunsuzluq yalnız
    istehsalatda — ilk yenilənmə cəhdində — üzə çıxardı.
    """
    return f"{version}/{filename}"


@dataclass(frozen=True)
class UpdateDecision:
    """Nə etməli — arxa fon klienti bunu icra edir, UI isə göstərir."""

    action: UpdateAction
    release: ReleaseInfo | None = None
    reason_az: str = ""

    @property
    def should_download(self) -> bool:
        return self.action in {UpdateAction.OPTIONAL, UpdateAction.MANDATORY}

    @property
    def is_mandatory(self) -> bool:
        return self.action is UpdateAction.MANDATORY


def decide(
    *,
    current: Version,
    latest: ReleaseInfo | None,
    forced_version: Version | None = None,
) -> UpdateDecision:
    """Cari versiya + kataloq + tenant üçün məcburi versiya → qərar.

    Saf funksiyadır — bütün sərhəd halları şəbəkəsiz test olunur.

    Args:
        current: Quraşdırılmış versiya.
        latest: Kanalın ən yeni buraxılışı; kataloq boşdursa `None`.
        forced_version: Developer Panelindən bu tenant üçün təyin edilmiş
            versiya (`license_tenants.forced_update_version`).
    """
    if latest is None:
        return UpdateDecision(UpdateAction.UP_TO_DATE, reason_az="Yeni buraxılış yoxdur.")

    if latest.version == current:
        return UpdateDecision(
            UpdateAction.UP_TO_DATE, release=latest, reason_az="Ən son versiya quraşdırılıb."
        )

    if current.is_newer_than(latest.version):
        # ENDİRMƏ RƏDD EDİLİR. Bazaya yazma imkanı ələ keçirən bir hücumçu
        # köhnə, məlum zəiflikli versiyanı "yeni buraxılış" kimi göstərə
        # bilərdi — bu yoxlama həmin yolu bağlayır. Şüurlu geri qaytarma
        # ayrıca, açıq `rollback()` əməliyyatıdır.
        return UpdateDecision(
            UpdateAction.REFUSED_DOWNGRADE,
            release=latest,
            reason_az=(
                f"Kataloqdakı versiya ({latest.version}) quraşdırılmışdan "
                f"({current}) köhnədir — tətbiq edilmir."
            ),
        )

    mandatory_reason = _mandatory_reason(current, latest, forced_version)
    if mandatory_reason:
        return UpdateDecision(UpdateAction.MANDATORY, release=latest, reason_az=mandatory_reason)

    return UpdateDecision(
        UpdateAction.OPTIONAL,
        release=latest,
        reason_az=f"Yeni versiya mövcuddur: {latest.version}.",
    )


def _mandatory_reason(current: Version, latest: ReleaseInfo, forced_version: Version | None) -> str:
    """Məcburilik səbəbi; məcburi deyilsə boş sətir.

    Üç ayrı mənbə var və üçü də EYNİ nəticəyə aparır:

        forced_version   bir tenant-a ünvanlanmış (Developer Paneli)
        is_mandatory     bütün quraşdırmalara — panel checkbox-u
        mandatory_below  yalnız müəyyən versiyadan köhnələrə

    Ayrı-ayrı saxlanılırlar, çünki "kim qərar verdi" sualının cavabı fərqlidir
    və mübahisəli halda (məs. "niyə mağaza yeniləndi?") audit izi məhz bu
    fərqi tələb edir — səbəb mətni `UpdateDecision`-a köçürülür.
    """
    if forced_version is not None and forced_version == latest.version:
        return "Bu yenilənmə təchizatçı tərəfindən məcburi edilib."
    if latest.is_mandatory:
        return "Bu buraxılış məcburi yeniləmə kimi işarələnib."
    if latest.mandatory_below is not None and current < latest.mandatory_below:
        return "Təhlükəsizlik yaması — yenilənmə məcburidir."
    return ""


def _channel_of(value: Any) -> ReleaseChannel:
    try:
        return ReleaseChannel(str(value).strip().upper())
    except ValueError:
        return ReleaseChannel.STABLE


def _pick(row: dict[str, Any], preferred: str, legacy: str) -> str:
    """Yeni sütun adı, yoxdursa köhnəsi (bax `from_row` izahı)."""
    value = row.get(preferred)
    if value in (None, ""):
        value = row.get(legacy)
    return str(value or "")


__all__ = [
    "DEFAULT_CHECK_INTERVAL_SECONDS",
    "DEFAULT_PACKAGE_FILENAME",
    "MAX_PACKAGE_BYTES",
    "RETRY_INTERVAL_SECONDS",
    "SHA256_HEX_LENGTH",
    "ChecksumMismatchError",
    "InvalidVersionError",
    "ReleaseChannel",
    "ReleaseInfo",
    "SignatureRejectedError",
    "UpdateAction",
    "UpdateDecision",
    "UpdateError",
    "UpdateUnavailableError",
    "Version",
    "decide",
    "storage_path_for",
]
