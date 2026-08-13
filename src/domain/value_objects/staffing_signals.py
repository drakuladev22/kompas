"""Tarixi-nümunə təklifinin domen tipləri (#13, kompasos11.md Faza 6).

──────────────────────────────────────────────────────────────────────────────
BU, TƏLƏB PROQNOZU DEYİL — 1C-YƏ TOXUNMUR
──────────────────────────────────────────────────────────────────────────────
kompasos11.md struktur qərar D: təklifin əvvəlki (satış həcminə əsaslanan)
dizaynı TAM ÇIXARILDI. Mənbə YALNIZ KompasOS-un ÖZ `attendance_records`
tarixçəsidir — "bu mağaza bu həftə günündə son N həftədə orta hesabla neçə
işçi ilə işləyib". Nə cədvəl adında, nə tipdə "demand"/"forecast" sözü var,
çünki bu, zəif siqnaldır: keçmişin təkrarı gələcəyin proqnozu deyil.

Praktik nəticə: bu tip HEÇ NƏ bloklamır, HEÇ NƏ təyin etmir. Ekranda
məsləhət kartıdır və admin onu görməzdən gələ bilər.

──────────────────────────────────────────────────────────────────────────────
HƏFTƏ GÜNÜ = ISO (1 = Bazar ertəsi … 7 = Bazar)
──────────────────────────────────────────────────────────────────────────────
migrations/019 bu konvensiyanı AÇIQ təsbit edir, çünki dörd fərqli
nömrələmə var: PostgreSQL `EXTRACT(DOW)` (0 = Bazar), `EXTRACT(ISODOW)`
(1 = B.e), Python `date.weekday()` (0 = B.e), `date.isoweekday()` (1 = B.e).
Səssiz seçim klassik "bir gün sürüşmə" qüsurudur. Python tərəfi
`date.isoweekday()` İŞLƏDİR — `weekday()` YOX.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA ID TİPİ YOXDUR
──────────────────────────────────────────────────────────────────────────────
`staffing_pattern_suggestions` tam törəmə cədvəldir (migrations/019: "istənilən
an yenidən hesablanır"); ona heç bir cədvəl `FOREIGN KEY` ilə bağlanmır və
sətir `(tenant_id, store_id, weekday)` üçlüyü ilə tam eyniləşdirilir. Ayrıca
`NewType` yalnız istifadə olunmayan bir özəllik olardı (eyni əsaslandırma
`behavior_signals.py`-dədir).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Final

from src.domain.entities.base import DomainRuleError
from src.domain.value_objects.scheduling import require_aware

if TYPE_CHECKING:
    from datetime import date

    from src.domain.value_objects.identifiers import StoreId, TenantId

#: `staffing_pattern_suggestions.weekday` CHECK-inin güzgüsü (1–7 ISO).
#: Sxem sərhədidir, ROOT parametri DEYİL — dəyişməsi miqrasiya tələb edir.
MIN_ISO_WEEKDAY: Final = 1
MAX_ISO_WEEKDAY: Final = 7

#: ISO həftə günü → Azərbaycanca tam ad (bölmə 9: yeganə interfeys dili).
#:
#: NİYƏ `strftime("%A")` DEYİL: onun nəticəsi ƏMƏLİYYAT SİSTEMİNİN lokalından
#: asılıdır və Windows-da ingiliscə qaytarır (eyni qüsur `screen_data.py`
#: `_WEEKDAYS_AZ` şərhində də sənədləşdirilib). Sabit cədvəl determinstikdir.
_WEEKDAY_NAMES_AZ: Final[dict[int, str]] = {
    1: "Bazar ertəsi",
    2: "Çərşənbə axşamı",
    3: "Çərşənbə",
    4: "Cümə axşamı",
    5: "Cümə",
    6: "Şənbə",
    7: "Bazar",
}


def weekday_name_az(iso_weekday: int) -> str:
    """ISO həftə gününün Azərbaycanca adı.

    MAKET VƏ CANLI YOL BUNU PAYLAŞIR (CLAUDE.md §6): `preview_screens` öz ad
    siyahısını qursaydı, iki tərəf bir gün sürüşməsini gizlədə bilərdi və
    fərq yalnız istehsalatda görünərdi.
    """
    if iso_weekday not in _WEEKDAY_NAMES_AZ:
        raise DomainRuleError(
            f"ISO həftə günü {MIN_ISO_WEEKDAY}–{MAX_ISO_WEEKDAY} aralığında olmalıdır",
            user_message="Həftə günü dəyəri düzgün deyil.",
            context={"weekday": iso_weekday},
        )
    return _WEEKDAY_NAMES_AZ[iso_weekday]


@dataclass(frozen=True)
class StoreDayHeadcount:
    """Bir mağazanın bir günündə FAKTİKİ işləmiş işçi sayı.

    "Faktiki" = həmin gün üçün təsdiqlənmiş girişi olan fərqli işçilər
    (`attendance_records`). Plan (`shift_assignments`) DEYİL: planlaşdırılıb
    gəlməyən işçi "işləmiş" sayılsaydı, təklif keçmiş kadr tərkibini deyil,
    keçmiş NİYYƏTİ təkrarlayardı.
    """

    work_date: date
    headcount: int

    def __post_init__(self) -> None:
        if self.headcount < 0:
            raise DomainRuleError(
                "İşçi sayı mənfi ola bilməz",
                context={"work_date": self.work_date.isoformat(), "headcount": self.headcount},
            )


@dataclass(frozen=True)
class StaffingPatternSuggestion:
    """`staffing_pattern_suggestions` sətrinin domen görünüşü (#13).

    Yoxlamalar DB `CHECK`-lərinin GÜZGÜSÜDÜR (`behavior_signals.py` ilə eyni
    prinsip): yararsız sətir bərpa ediləndə xəta İSTİFADƏ ANINDA yox, OXU
    ANINDA üzə çıxsın.
    """

    tenant_id: TenantId
    store_id: StoreId
    #: ISO həftə günü — 1 = Bazar ertəsi … 7 = Bazar.
    weekday: int
    #: Kəsr ola bilər: 8 həftənin 3-ündə 2, 5-ində 3 nəfər → 2.63.
    avg_historical_headcount: float
    #: Ortanın çıxdığı pəncərənin uzunluğu (həftə). Pəncərənin ÖZÜ ROOT
    #: parametridir; burada yalnız hesablama anındakı FAKTİKİ dəyər donur —
    #: Root sabah 8-i 12-yə çevirsə, köhnə sətrin izahı itməsin.
    based_on_weeks: int
    #: Sonuncu hesablama anı (tz-aware) — ekranda təklifin yaşı göstərilir,
    #: çünki 3 ay əvvəl hesablanmış "8 həftəlik nümunə" yanıldıcıdır.
    calculated_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.calculated_at, field="calculated_at")
        if not (MIN_ISO_WEEKDAY <= self.weekday <= MAX_ISO_WEEKDAY):
            raise DomainRuleError(
                f"ISO həftə günü {MIN_ISO_WEEKDAY}–{MAX_ISO_WEEKDAY} aralığında olmalıdır",
                context={"weekday": self.weekday},
            )
        if self.avg_historical_headcount < 0:
            raise DomainRuleError(
                "Orta işçi sayı mənfi ola bilməz",
                context={"avg_historical_headcount": self.avg_historical_headcount},
            )
        if self.based_on_weeks <= 0:
            raise DomainRuleError(
                "Tarixçə pəncərəsi ən azı 1 həftə olmalıdır",
                context={"based_on_weeks": self.based_on_weeks},
            )

    @property
    def weekday_label_az(self) -> str:
        """Modul funksiyasının qısa yolu. AD FƏRQLİDİR (`_label_` vs `_name_`),
        çünki eyni ad qlobal funksiyanı xüsusiyyətlə qarışdırar və oxuyan
        hansının çağırıldığını yalnız sahə axtarışı ilə tapardı."""
        return weekday_name_az(self.weekday)

    def headcount_label_az(self) -> str:
        """Ekranda göstərilən dəyər — "2.6 nəfər".

        Bir onluq rəqəm: "2.63 nəfər" saxta dəqiqlik təəssüratı yaradır,
        halbuki bu, zəif siqnaldır və yuvarlaqlaşdırılmış görünüş onun
        təxmini xarakterini oxucuya bildirir.
        """
        return f"{self.avg_historical_headcount:.1f} nəfər"


__all__ = [
    "MAX_ISO_WEEKDAY",
    "MIN_ISO_WEEKDAY",
    "StaffingPatternSuggestion",
    "StoreDayHeadcount",
    "weekday_name_az",
]
