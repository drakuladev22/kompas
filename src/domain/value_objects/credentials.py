"""Kimlik/giriş value object-ləri: PIN, istifadəçi adı və e-poçt.

QAYDA: bu VO-lar sirrin ÖZÜNÜ daşıyır, ona görə:
    * `__repr__`/`__str__` maskalanıb — PIN heç vaxt log-a, traceback-ə və ya
      pytest diff-inə düşmür;
    * müqayisə sabit-vaxtlıdır (`secrets.compare_digest`);
    * validasiya konstruktorda baş verir — yararsız PIN heç vaxt yarana bilmir
      (bax spesifikasiya bölmə 2).

Zəif PIN siyahısı və format qaydası BURADA — tək həqiqət mənbəyi.
`infrastructure.security.hashing` bu VO-nu istifadə edir (infrastruktur
domendən asılı ola bilər, əksi YOX).
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Final

from src.shared.exceptions import KompasOSError

PIN_LENGTH: Final[int] = 4
MAX_EMAIL_LENGTH: Final[int] = 254  # RFC 5321
MIN_USERNAME_LENGTH: Final[int] = 3
MAX_USERNAME_LENGTH: Final[int] = 32

# DİQQƏT: `\d` YOX, `[0-9]`. Python-un `\d`-i defolt olaraq bütün Unicode
# rəqəmlərini tutur (ərəb-hind `١٢٣٤`, deva-naqari və s.) — belə PIN qəbul
# edilər, lakin kiosk-un rəqəm klaviaturası onu heç vaxt yarada bilməz.
# Nəticə: istifadəçi öz PIN-i ilə girə bilməzdi.
_PIN_PATTERN: Final[re.Pattern[str]] = re.compile(rf"^[0-9]{{{PIN_LENGTH}}}$")

# Azərbaycan hərflərini də qəbul edən sadə, praktik e-poçt naxışı.
# Tam RFC 5322 uyğunluğu qəsdən hədəflənmir — həddindən artıq mürəkkəb naxış
# real e-poçtları rədd etmə riskini artırır.
_EMAIL_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$", re.UNICODE)

# İstifadəçi adı: ASCII hərf/rəqəm ilə başlayır, sonra nöqtə/alt-xətt/defis də
# olar. DB-dəki `chk_employee_username` ilə EYNİ qayda.
#
# NİYƏ ASCII: giriş adı gündə onlarla dəfə yazılır və mağaza PC-lərində
# klaviatura düzümü Azərbaycan, rus və ya ingilis ola bilər. "şəbnəm" adlı
# hesab ingilis düzümündə yazıla bilməzdi. Ad-soyad üçün Azərbaycan hərfləri
# sərbəstdir — məhdudiyyət yalnız GİRİŞ identifikatorunadır.
_USERNAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"^[a-z0-9][a-z0-9._-]{{{MIN_USERNAME_LENGTH - 1},{MAX_USERNAME_LENGTH - 1}}}$"
)

#: Aşkar zəif PIN-lər: təkrarlanan, ardıcıl (irəli/geri) və klaviatura naxışları.
WEAK_PINS: Final[frozenset[str]] = frozenset(
    {f"{d}{d}{d}{d}" for d in "0123456789"}
    | {"0123", "1234", "2345", "3456", "4567", "5678", "6789", "7890"}
    | {"9876", "8765", "7654", "6543", "5432", "4321", "3210", "0987"}
    | {"1379", "2580", "0852", "1596", "1212", "2121", "1010", "2020"}
)


class InvalidPinError(KompasOSError):
    """PIN format və ya zəiflik siyasətinə uyğun deyil."""

    user_message = "PIN tələblərə cavab vermir."


class InvalidEmailError(KompasOSError):
    """E-poçt ünvanı yararsızdır."""

    user_message = "E-poçt ünvanı düzgün deyil."


class InvalidUsernameError(KompasOSError):
    """İstifadəçi adı format qaydasına uyğun deyil."""

    user_message = (
        "İstifadəçi adı 3–32 simvol olmalı, hərf və ya rəqəmlə başlamalı, "
        "yalnız ingilis hərfləri, rəqəm, nöqtə, alt-xətt və defis saxlamalıdır."
    )


@dataclass(frozen=True)
class Pin:
    """4 rəqəmli kiosk PIN-i (spesifikasiya bölmə 2, 4).

    Yalnız `Satıcı` və digər işçi rolları üçündür — admin panelə giriş üçün
    İSTİFADƏ OLUNMUR (`Kamera_Nəzarətçisi` daxil, bax bölmə 2).
    """

    value: str

    def __post_init__(self) -> None:
        if not _PIN_PATTERN.fullmatch(self.value):
            raise InvalidPinError(
                f"PIN dəqiq {PIN_LENGTH} rəqəmdən ibarət olmalıdır",
                user_message=f"PIN {PIN_LENGTH} rəqəm olmalıdır.",
            )

    @classmethod
    def parse(cls, raw: str, *, reject_weak: bool = True) -> Pin:
        """İstifadəçi girişindən PIN yaradır.

        Args:
            reject_weak: Yeni PIN TƏYİN EDİLƏRKƏN `True` olmalıdır. Mövcud
                PIN-i YOXLAYARKƏN `False` verilir — əks halda siyasət
                sərtləşdirilməzdən əvvəl yaradılmış PIN-lə heç kim girə bilməzdi.
        """
        pin = cls(raw.strip())
        if reject_weak and pin.is_weak:
            raise InvalidPinError(
                "PIN çox sadədir (ardıcıl/təkrarlanan rəqəmlər)",
                user_message="Bu PIN çox sadədir (məs. 1234, 0000). Başqasını seçin.",
            )
        return pin

    @property
    def is_weak(self) -> bool:
        return self.value in WEAK_PINS

    def equals(self, other: str) -> bool:
        """Sabit-vaxtlı müqayisə (timing hücumuna qarşı)."""
        return secrets.compare_digest(self.value, other)

    def __repr__(self) -> str:
        return "Pin(****)"

    __str__ = __repr__


@dataclass(frozen=True)
class Username:
    """Admin-tier GİRİŞ identifikatoru (spesifikasiya bölmə 2, qərar SEC-016).

    E-poçtu əvəz edir. Fərq təkcə formatda deyil:

        * Giriş adı DƏYİŞMİR — e-poçt isə işçinin şəxsi həyatı ilə dəyişirdi
          (evlilik, provayder dəyişikliyi), yəni identifikator sabit deyildi.
        * Sistem e-poçt göndərmə infrastrukturundan TAM ASILI DEYİL.
        * Mağaza işçisinin şəxsi e-poçtu olmaya bilər — giriş adı isə həmişə
          HR tərəfindən verilə bilir.

    Normallaşdırma: kənar boşluqlar silinir, kiçik hərfə salınır (DB-də
    `CITEXT` — "Rashad" və "rashad" EYNİ hesabdır).
    """

    value: str

    def __post_init__(self) -> None:
        if not _USERNAME_PATTERN.fullmatch(self.value):
            raise InvalidUsernameError(
                f"İstifadəçi adı qaydaya uyğun deyil: {self.value!r}",
                context={"value": self.value, "length": len(self.value)},
            )

    @classmethod
    def parse(cls, raw: str) -> Username:
        return cls(raw.strip().lower())

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class EmailAddress:
    """E-poçt ünvanı — YALNIZ bildiriş üçün (spesifikasiya bölmə 7).

    ARTIQ AUTENTİFİKASİYA İDENTİFİKATORU DEYİL (qərar SEC-016). Admin girişi
    `Username` + şifrə ilə aparılır; bu VO indi yalnız `notification_email`
    və tenant-səviyyəli əlaqə ünvanı üçün istifadə olunur.

    Normallaşdırma: kənar boşluqlar silinir, domen hissəsi kiçik hərfə salınır.
    Lokal hissə RFC-yə görə case-sensitive-dir, lakin praktikada bütün böyük
    provayderlər onu case-insensitive işlədir — DB-də `CITEXT` istifadə olunur,
    ona görə burada da tam kiçik hərfə salırıq (tutarlılıq üçün).
    """

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise InvalidEmailError("E-poçt boş ola bilməz")
        if len(self.value) > MAX_EMAIL_LENGTH:
            raise InvalidEmailError(
                f"E-poçt {MAX_EMAIL_LENGTH} simvoldan uzun ola bilməz",
                context={"length": len(self.value)},
            )
        if not _EMAIL_PATTERN.fullmatch(self.value):
            raise InvalidEmailError(
                f"E-poçt ünvanı yararsızdır: {self.value!r}",
                context={"value": self.value},
            )

    @classmethod
    def parse(cls, raw: str) -> EmailAddress:
        return cls(raw.strip().lower())

    @property
    def domain(self) -> str:
        return self.value.rsplit("@", 1)[1]

    @property
    def local_part(self) -> str:
        return self.value.rsplit("@", 1)[0]

    def __str__(self) -> str:
        return self.value


__all__ = [
    "MAX_EMAIL_LENGTH",
    "MAX_USERNAME_LENGTH",
    "MIN_USERNAME_LENGTH",
    "PIN_LENGTH",
    "WEAK_PINS",
    "EmailAddress",
    "InvalidEmailError",
    "InvalidPinError",
    "InvalidUsernameError",
    "Pin",
    "Username",
]
