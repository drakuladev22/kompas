"""Satış xalları və mükafat value object-ləri (spesifikasiya bölmə 6).

──────────────────────────────────────────────────────────────────────────────
6 AYLIQ SIFIRLANMA — TARİXLƏR NİYƏ HARDCODE-DUR
──────────────────────────────────────────────────────────────────────────────
Bölmə 6: "Unused points hard-reset to 0 every 6 months (July 1 & Jan 1); reset
öncəsi işçilərə 14 gün əvvəldən bildiriş göndərilir."

1 Yanvar / 1 İyul TƏNZİMLƏNƏN limit DEYİL — spesifikasiya onları sabit təqvim
tarixi kimi verir və mühasibatlıq dövrü də bu iki nöqtəyə bağlıdır. `Root`
tərəfindən dəyişdirilə bilsəydi, bir tenant-da iyunda, digərində avqustda
sıfırlanma olardı və "xalım niyə itdi?" sualı hər tenant üçün fərqli cavab
tələb edərdi. Ona görə burada sabitdir; TƏNZİMLƏNƏN olan yalnız bildiriş
qabaqcadanlığıdır (14 gün defolt, `system_limits` ilə uzadıla bilər).

──────────────────────────────────────────────────────────────────────────────
SIFIRLANMA NİYƏ "HARD RESET"-dir, AMMA TARİXÇƏ SİLİNMİR
──────────────────────────────────────────────────────────────────────────────
Balans sıfırlanır, LAKİN `points_ledger` sətirləri qalır — bölmə 6-nın audit
qaydası ("orijinal əməliyyat qeydi silinmir") sıfırlanmaya da şamil olunur.
`PointsPeriod` məhz bunun üçün var: balans "bütün sətirlərin cəmi" deyil,
"CARİ DÖVRÜN sətirlərinin cəmi"dir. Beləliklə sıfırlanma bir `DELETE` deyil,
sadəcə dövrün dəyişməsidir — geri qaytarıla bilən, izlənə bilən əməliyyat.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Final

from src.domain.value_objects.scheduling import require_aware
from src.shared.exceptions import KompasOSError

#: Sıfırlanma ayları — 1 Yanvar və 1 İyul (bölmə 6).
RESET_MONTHS: Final[tuple[int, int]] = (1, 7)
#: Sıfırlanmadan neçə gün əvvəl işçiyə bildiriş gedir (bölmə 6).
DEFAULT_RESET_NOTICE_DAYS: Final[int] = 14
#: Xal etirazı üçün pəncərə — cərimə ilə EYNİ (bölmə 6: "eyni məntiqlə").
POINTS_DISPUTE_WINDOW_HOURS: Final[int] = 72

#: Neçə AZN brutto satış 1 xal qazandırır (defolt). ROOT İdarə Mərkəzindən
#: `POINTS_PER_CURRENCY_UNIT` limiti ilə dəyişdirilir.
#:
#: NİYƏ "hər N AZN-ə 1 xal", "hər satışa 1 xal" DEYİL: ikincisi satıcını
#: bir böyük satışı bir neçə çekə bölməyə həvəsləndirərdi və 1C-dəki sənəd
#: sayı süni şişərdi. Məbləğ-əsaslı qayda belə oyunu mənasız edir.
DEFAULT_CURRENCY_PER_POINT: Final[Decimal] = Decimal("100")


def points_for_amount(
    gross_amount: Decimal, *, currency_per_point: Decimal = DEFAULT_CURRENCY_PER_POINT
) -> int:
    """Brutto satış məbləğindən qazanılan xal.

    AŞAĞI YUVARLAQLAŞDIRMA (`//`) qəsdəndir: 99 AZN 0 xal verir. Yuxarı
    yuvarlaqlaşdırma 1 AZN-lik satışa da tam xal verərdi və xal sistemi
    satışın həcmini deyil, sayını mükafatlandırardı.
    """
    if gross_amount <= 0 or currency_per_point <= 0:
        return 0
    return int(gross_amount // currency_per_point)


class InvalidPointsError(KompasOSError):
    """Xal dəyəri və ya mükafat konfiqurasiyası yararsızdır."""

    user_message = "Xal məlumatı düzgün deyil."


class InsufficientPointsError(KompasOSError):
    """Mükafat üçün balans çatmır."""

    user_message = "Bu mükafat üçün xalınız kifayət etmir."


class PointsEntryStatus(str, Enum):
    """`points_ledger.status` — DB `points_entry_status` enum-u ilə EYNİ.

    Bölmə 6: "xal korreksiya oluna bilər, amma orijinal əməliyyat qeydi
    silinmir (yalnız «REVERSED»/«CORRECTED» statusu əlavə olunur)".

    ETİRAZ BURADA STATUS DEYİL: o, ayrıca `points_appeals` sətridir
    (`PointsAppealStatus`). Səbəb — cərimə modeli ilə eynilik: etiraz mətni,
    72 saatlıq pəncərə və qərar qeydi öz sətrində yaşayır, ledger sətri isə
    yalnız "nə qədər xal qüvvədədir" sualına cavab verir. Etirazı statusa
    çevirsək, EYNİ sətir üzərində iki fərqli tarixçə (xal + mübahisə)
    saxlamalı olardıq.
    """

    ACTIVE = "ACTIVE"
    #: Etiraz qəbul olundu, xal sayı DƏYİŞDİRİLDİ (sətir qalır).
    CORRECTED = "CORRECTED"
    #: Etiraz qəbul olundu, xal TAM ləğv edildi.
    REVERSED = "REVERSED"

    @property
    def counts_toward_balance(self) -> bool:
        """Balansa daxil edilirmi.

        Yalnız `REVERSED` çıxarılır; `CORRECTED` isə artıq düzəldilmiş
        dəyərlə sayılır. Etiraz GÖZLƏYƏN sətir də sayılır — işçini qərardan
        ƏVVƏL cəzalandırmaq düzgün deyil (cərimədəki eyni prinsip).
        """
        return self is not PointsEntryStatus.REVERSED


class PointsAppealStatus(str, Enum):
    """`points_appeals.status` — DB `appeal_status` enum-u ilə EYNİ."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    #: 72 saatlıq pəncərə qərarsız bağlandı.
    EXPIRED = "EXPIRED"

    @property
    def is_decided(self) -> bool:
        return self is not PointsAppealStatus.PENDING


class RedemptionStatus(str, Enum):
    """Mükafat mübadiləsinin vəziyyəti (bölmə 6, `can_manage_sales_points`).

    DB-də (`reward_redemptions`) bu dəyərlər migration 010 ilə əlavə olunur;
    ondan əvvəlki sxemdə yalnız `approved_at` var idi və "rədd edildi" ilə
    "hələ baxılmayıb" AYIRD EDİLƏ BİLMİRDİ — işçi sorğusunun nə olduğunu
    görə bilmirdi.
    """

    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    #: Mükafat işçiyə faktiki təhvil verildi — xal ARTIQ tutulub.
    FULFILLED = "FULFILLED"

    @property
    def holds_points(self) -> bool:
        """Xallar bu status altında bloklanırmı.

        `REQUESTED` və `APPROVED` bloklayır ki, işçi eyni xalı iki mükafata
        xərcləməsin. `REJECTED` xalı geri açır.
        """
        return self in (
            RedemptionStatus.REQUESTED,
            RedemptionStatus.APPROVED,
            RedemptionStatus.FULFILLED,
        )


@dataclass(frozen=True)
class PointsPeriod:
    """6 aylıq xal dövrü — `[start, end)` yarı-açıq aralıq.

    Yarı-açıq olması sərhəd səhvini bağlayır: 30 iyun 23:59-da qazanılan xal
    birinci dövrə, 1 iyul 00:00-da qazanılan isə ikinci dövrə düşür və heç bir
    an İKİ dövrə birdən aid olmur.
    """

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise InvalidPointsError("Dövrün bitməsi başlanğıcdan sonra olmalıdır")

    @classmethod
    def containing(cls, day: date) -> PointsPeriod:
        """Verilmiş günün aid olduğu dövr."""
        if day.month < RESET_MONTHS[1]:
            return cls(date(day.year, 1, 1), date(day.year, 7, 1))
        return cls(date(day.year, 7, 1), date(day.year + 1, 1, 1))

    @property
    def reset_on(self) -> date:
        """Bu dövrün xallarının sıfırlanacağı gün (növbəti dövrün başlanğıcı)."""
        return self.end

    def notice_on(self, *, notice_days: int = DEFAULT_RESET_NOTICE_DAYS) -> date:
        """Bildirişin göndərilməli olduğu gün — sıfırlanmadan 14 gün əvvəl."""
        if notice_days < 0:
            raise InvalidPointsError("Bildiriş qabaqcadanlığı mənfi ola bilməz")
        return self.end - timedelta(days=notice_days)

    def is_notice_due(self, day: date, *, notice_days: int = DEFAULT_RESET_NOTICE_DAYS) -> bool:
        """Həmin gün sıfırlanma xəbərdarlığı göndərilməlidirmi.

        Bərabər DEYİL, "böyük və ya bərabər" yoxlanılır: tətbiq bildiriş
        gününü offline/söndürülmüş vəziyyətdə buraxa bilər və o halda
        xəbərdarlıq TAMAMİLƏ itərdi. Gecikmiş bildiriş heç bildirişdən
        yaxşıdır.
        """
        return self.notice_on(notice_days=notice_days) <= day < self.end

    def contains(self, moment: datetime) -> bool:
        """An bu dövrə düşürmü (tz-aware tələb olunur)."""
        require_aware(moment, field="moment")
        return self.start <= moment.date() < self.end

    def next_period(self) -> PointsPeriod:
        return PointsPeriod.containing(self.end)

    def label_az(self) -> str:
        """İstifadəçiyə göstərilən dövr adı: `2026 I yarım` / `2026 II yarım`."""
        half = "I" if self.start.month == RESET_MONTHS[0] else "II"
        return f"{self.start.year} {half} yarım"

    def __str__(self) -> str:
        return self.label_az()


@dataclass(frozen=True)
class RewardItem:
    """Mükafat kataloqu sətri — `can_manage_sales_points` ilə idarə olunur."""

    name: str
    cost_points: int
    is_active: bool = True
    description: str = ""

    def __post_init__(self) -> None:
        cleaned = " ".join(self.name.split())
        if not cleaned:
            raise InvalidPointsError("Mükafat adı boş ola bilməz")
        object.__setattr__(self, "name", cleaned)
        if self.cost_points <= 0:
            raise InvalidPointsError(
                "Mükafat dəyəri müsbət olmalıdır — pulsuz mükafat xal sistemini mənasızlaşdırır"
            )

    def affordable_with(self, available_points: int) -> bool:
        return self.is_active and available_points >= self.cost_points

    def require_affordable(self, available_points: int) -> None:
        """Mübadilə cəhdini yoxlayır — çatmırsa açıq istisna atır."""
        if not self.is_active:
            raise InvalidPointsError(
                f"Mükafat aktiv deyil: {self.name}",
                user_message="Bu mükafat artıq mövcud deyil.",
            )
        if available_points < self.cost_points:
            raise InsufficientPointsError(
                f"{self.name} üçün {self.cost_points} xal lazımdır, mövcud: {available_points}",
                context={"required": self.cost_points, "available": available_points},
            )


@dataclass(frozen=True)
class PointsBalance:
    """Bir işçinin BİR dövr üzrə xal vəziyyəti.

    `held` — təsdiq gözləyən/təsdiqlənmiş mükafatlara bloklanmış xallar.
    `available` həmin bloklamanı çıxır ki, işçi eyni xalı iki dəfə xərcləməsin.
    """

    period: PointsPeriod
    earned: int = 0
    held: int = 0

    def __post_init__(self) -> None:
        if self.earned < 0:
            raise InvalidPointsError("Qazanılmış xal mənfi ola bilməz")
        if self.held < 0:
            raise InvalidPointsError("Bloklanmış xal mənfi ola bilməz")
        if self.held > self.earned:
            raise InvalidPointsError(
                "Bloklanmış xal qazanılmışdan çox ola bilməz — bu, ikiqat xərcləmə əlamətidir",
                context={"earned": self.earned, "held": self.held},
            )

    @property
    def available(self) -> int:
        """Mükafata xərclənə bilən xal."""
        return self.earned - self.held

    def days_until_reset(self, *, today: date) -> int:
        """Sıfırlanmaya qalan gün sayı — bildiriş mətnində göstərilir."""
        return max(0, (self.period.reset_on - today).days)


__all__ = [
    "DEFAULT_CURRENCY_PER_POINT",
    "DEFAULT_RESET_NOTICE_DAYS",
    "POINTS_DISPUTE_WINDOW_HOURS",
    "RESET_MONTHS",
    "InsufficientPointsError",
    "InvalidPointsError",
    "PointsAppealStatus",
    "PointsBalance",
    "PointsEntryStatus",
    "PointsPeriod",
    "RedemptionStatus",
    "RewardItem",
    "points_for_amount",
]
