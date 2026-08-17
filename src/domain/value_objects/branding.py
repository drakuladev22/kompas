"""Kirayəçinin vizual kimliyi (TENANT-1 Faza 2).

──────────────────────────────────────────────────────────────────────────────
BRENDİNQ YALNIZ VİZUAL QATDIR — QƏTİ SƏRHƏD
──────────────────────────────────────────────────────────────────────────────
Bu tipdə funksionallığa, təhlükəsizlik qaydalarına və ya RBAC-a təsir edən
HEÇ BİR sahə yoxdur. Səbəb `CLAUDE.md` §5-dədir: «müştəri istədi» hər struktur
zəmanətin yan keçilməsi üçün bəhanəyə çevrilərdi. Yeni sahə əlavə edən adam
əvvəlcə bu suala cavab verməlidir — «bu dəyər dəyişəndə hansısa qadağa
zəifləyirmi?» Cavab «bəli»dirsə, yeri burası DEYİL.

──────────────────────────────────────────────────────────────────────────────
VURĞU RƏNGİ KONTRAST QAPISINDAN KEÇMİR — ONA GÖRƏ BURADA YOXLANILIR
──────────────────────────────────────────────────────────────────────────────
`scripts/check_contrast.py` `tokens.py`-dakı SABİT palitranı ölçür və CI-da
işləyir. Müştərinin işə düşmə anında verdiyi rəng isə həmin qapının GÖRDÜYÜ
şey deyil: Root ekranından `#FFFF00` yazmaq mümkündür və nəticədə mətn ağ
fonda oxunmaz olardı.

Ona görə rəng BURADA — qəbul anında — yoxlanılır. Yoxlama sadə relativ
parlaqlıq hesabıdır (WCAG 2.1 düsturu) və qapının özünü TƏKRARLAMIR: qapı
CÜTLƏRİ ölçür, burada isə tək sual var — «bu rəng tünd mətnlə də, açıq mətnlə
də işlənə biləcək qədər ortadadırmı».

RƏDD ETMƏK ƏVƏZİNƏ XƏBƏRDARLIQ: uyğun olmayan rəng SAXLANILIR, lakin
`is_accessible` `False` qaytarır və ekran istifadəçiyə bunu deyir. Rədd
etsəydik, müştərinin rəsmi brend rəngi (ola bilsin həqiqətən açıqdır)
sistemə heç vaxt daxil edilə bilməzdi — halbuki qərar müştərinindir, bizim
deyil.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

#: `#RRGGBB` — miqrasiya 064-dəki `CHECK` ilə EYNİ qayda.
HEX_COLOR_PATTERN: Final = re.compile(r"^#[0-9A-Fa-f]{6}$")

#: Şirkət adının maksimum uzunluğu — miqrasiya 064-dəki `CHECK` ilə eyni.
#: 80 simvol NİYƏ: başlıq zolağı dardır və bundan uzun ad orada onsuz da
#: kəsilərdi; hədd yoxdursa isə export başlığı bir sətri tamamilə doldurardı.
MAX_COMPANY_NAME_CHARS: Final = 80

#: Loqonun maksimum həcmi — miqrasiya 064-dəki `CHECK` ilə eyni (256 KB).
MAX_LOGO_BYTES: Final = 262_144

#: PNG faylının imzası. Yalnız PNG qəbul edilir: `QPixmap` başqa formatları da
#: oxuya bilər, lakin format yoxlaması OLMASAYDI istifadəçi ixtiyari faylı
#: «loqo» kimi yükləyər və nəticə yalnız ekranda — boş kvadrat şəklində —
#: görünərdi.
PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"

#: Vurğu rəngi üçün qəbul edilən nisbi parlaqlıq aralığı.
#:
#: NİYƏ ROOT PARAMETRİ DEYİL: bu, WCAG 2.1 düsturunun tətbiqidir, biznes
#: siyasəti deyil. Root onu genişləndirsəydi, «oxunaqlılıq yoxlaması» adlı
#: mexanizm yalnız adı ilə qalardı.
MIN_ACCENT_LUMINANCE: Final = 0.06
MAX_ACCENT_LUMINANCE: Final = 0.62

#: WCAG 2.1 sRGB → xətti çevirmə sabitləri. Ədədlər STANDARTIN ÖZÜNDƏNDİR —
#: `scripts/check_contrast.py`-dakı eyni dəyərlərlə cütdür. Root parametri
#: deyil və ola bilməz: onları dəyişmək «WCAG hesabı» adlı funksiyanı adı ilə
#: qalan bir şeyə çevirərdi.
_SRGB_LINEAR_THRESHOLD: Final = 0.04045
_SRGB_LOW_DIVISOR: Final = 12.92
_SRGB_OFFSET: Final = 0.055
_SRGB_SCALE: Final = 1.055
_SRGB_EXPONENT: Final = 2.4
_LUMINANCE_RED: Final = 0.2126
_LUMINANCE_GREEN: Final = 0.7152
_LUMINANCE_BLUE: Final = 0.0722


class BrandingError(ValueError):
    """Brendinq dəyəri qəbul edilə bilməz (format/ölçü)."""


def relative_luminance(hex_color: str) -> float:
    """WCAG 2.1 nisbi parlaqlığı (0.0 = qara, 1.0 = ağ).

    Düstur `scripts/check_contrast.py`-dakı ilə EYNİDİR və qəsdən təkrarlanır:
    skript `scripts/` altındadır və domen qatı ondan İDXAL EDƏ BİLMƏZ
    (`CLAUDE.md` §3 qat sırası). Təkrarın riski var, lakin alternativ —
    domenin skript qovluğundan asılı olması — daha ağırdır.
    """
    if not HEX_COLOR_PATTERN.match(hex_color):
        raise BrandingError(f"Rəng `#RRGGBB` formatında olmalıdır: {hex_color!r}")

    channels = [int(hex_color[i : i + 2], 16) / 255.0 for i in (1, 3, 5)]
    linear = [_to_linear(channel) for channel in channels]
    return (
        _LUMINANCE_RED * linear[0] + _LUMINANCE_GREEN * linear[1] + _LUMINANCE_BLUE * linear[2]
    )


def _to_linear(srgb: float) -> float:
    """sRGB kanalını xətti sahəyə çevirir (WCAG 2.1).

    Ədədlərin adı `scripts/check_contrast.py::_channel_luminance` ilə
    eynidir — ikisi eyni standartın eyni bəndindəndir və birini dəyişmək
    digərini də dəyişməyi tələb edir.
    """
    if srgb <= _SRGB_LINEAR_THRESHOLD:
        return srgb / _SRGB_LOW_DIVISOR
    # `float(...)`: `**` operatorunun nəticəsi mypy üçün `Any`-dir (üstün
    # dəyər mənfi olduqda `complex` qaytara bilər). Burada mümkün deyil —
    # `srgb` 0..1 aralığındadır — lakin tip zəmanəti açıq saxlanılır.
    return float(((srgb + _SRGB_OFFSET) / _SRGB_SCALE) ** _SRGB_EXPONENT)


@dataclass(frozen=True)
class TenantBranding:
    """Bir kirayəçinin vizual kimliyi. Bütün sahələr İSTƏYƏ BAĞLIDIR."""

    #: Boş sətir = defolt davranış («KompasOS», əlavəsiz).
    company_name: str = ""
    #: `None` = defolt KompasOS loqosu.
    logo_png: bytes | None = None
    #: `None` = defolt Amber (`tokens.BRAND_AMBER`).
    accent_color: str | None = None

    def __post_init__(self) -> None:
        if len(self.company_name) > MAX_COMPANY_NAME_CHARS:
            raise BrandingError(
                f"Şirkət adı {MAX_COMPANY_NAME_CHARS} simvoldan uzun ola bilməz "
                f"(faktiki {len(self.company_name)})"
            )
        if self.logo_png is not None:
            _validate_logo(self.logo_png)
        if self.accent_color is not None and not HEX_COLOR_PATTERN.match(self.accent_color):
            raise BrandingError(f"Vurğu rəngi `#RRGGBB` olmalıdır: {self.accent_color!r}")

    # ------------------------------- görünüş --------------------------------- #

    def window_title(self, *, product: str = "KompasOS") -> str:
        """Başlıq zolağının mətni: «KompasOS — Yataş Group».

        Şirkət adı MƏHSUL ADINI ƏVƏZ ETMİR, ona ƏLAVƏ olunur. Səbəb dəstəkdir:
        müştəri zəng edəndə ekranda hansı proqramın işlədiyi görünməlidir —
        yalnız «Yataş Group» yazsaydıq, dəstək operatoru versiyanı da,
        məhsulu da soruşmalı olardı.
        """
        name = self.company_name.strip()
        return f"{product} — {name}" if name else product

    @property
    def has_custom_logo(self) -> bool:
        return self.logo_png is not None

    @property
    def is_accessible(self) -> bool:
        """Vurğu rəngi oxunaqlı aralıqdadırmı.

        Rəng verilməyibsə `True`: defolt palitra onsuz da kontrast qapısından
        keçib. Bax modul başlığı — uyğunsuz rəng RƏDD EDİLMİR, yalnız
        işarələnir.
        """
        if self.accent_color is None:
            return True
        luminance = relative_luminance(self.accent_color)
        return MIN_ACCENT_LUMINANCE <= luminance <= MAX_ACCENT_LUMINANCE

    def accessibility_warning(self) -> str:
        """İstifadəçiyə göstərilən xəbərdarlıq; problem yoxdursa boş sətir."""
        if self.is_accessible:
            return ""
        luminance = relative_luminance(self.accent_color or "#000000")
        if luminance > MAX_ACCENT_LUMINANCE:
            return (
                "Seçilmiş rəng çox açıqdır — onun üzərindəki ağ mətn oxunmaya bilər. "
                "Rəng saxlanıldı, lakin daha tünd variant tövsiyə olunur."
            )
        return (
            "Seçilmiş rəng çox tünddür — onun üzərindəki tünd mətn oxunmaya bilər. "
            "Rəng saxlanıldı, lakin daha açıq variant tövsiyə olunur."
        )


def _validate_logo(payload: bytes) -> None:
    if len(payload) > MAX_LOGO_BYTES:
        raise BrandingError(
            f"Loqo {MAX_LOGO_BYTES // 1024} KB-dan böyük ola bilməz "
            f"(faktiki {len(payload) // 1024} KB)"
        )
    if not payload.startswith(PNG_SIGNATURE):
        raise BrandingError("Loqo PNG formatında olmalıdır")


#: Brendinq təyin edilməmiş kirayəçi — defolt görünüş.
DEFAULT_BRANDING: Final[TenantBranding] = TenantBranding()


__all__ = [
    "DEFAULT_BRANDING",
    "HEX_COLOR_PATTERN",
    "MAX_ACCENT_LUMINANCE",
    "MAX_COMPANY_NAME_CHARS",
    "MAX_LOGO_BYTES",
    "MIN_ACCENT_LUMINANCE",
    "PNG_SIGNATURE",
    "BrandingError",
    "TenantBranding",
    "relative_luminance",
]
