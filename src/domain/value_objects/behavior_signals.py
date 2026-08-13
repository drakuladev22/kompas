"""İşçi Davranış Baz Xəttinin domen tipləri (#8, kompasos11.md Faza 5).

──────────────────────────────────────────────────────────────────────────────
NİYƏ `CheckInObservation` BAZ XƏTT VƏ ANOMALİYA QAYDASI ARASINDA PAYLAŞILIR
──────────────────────────────────────────────────────────────────────────────
`BehaviorBaselineUseCase` (gecəlik yenidən-hesablama) və `BehaviorAnomalyRule`
(Exception Engine-ə qoşulan qayda) EYNİ sualı iki fərqli anda verir: "bu işçi
nə vaxt təsdiqlənmiş giriş edib?". Əgər hər biri öz SQL-ini yazsaydı, "check-in
nədir?" tərifi (STEP A `requested_at` ya STEP C `verified_at`?) vaxtla iki
fərqli yerdə iki fərqli cavab ala bilərdi və baz xətt öz anomaliya qaydasıyla
səssizcə uyğunsuzlaşardı. Ona görə hər ikisi `CheckInHistoryProvider`
(`interfaces.ports`) portundan EYNİ tipi oxuyur.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `BehaviorBaseline`-IN AYRICA ID TİPİ YOXDUR
──────────────────────────────────────────────────────────────────────────────
`employee_behavior_baseline` (migrations/018) "tam törəmə məlumatdır" — heç
bir başqa cədvəl ona `FOREIGN KEY` ilə bağlanmır və sətir istənilən an
`attendance_records`-dan yenidən hesablana bilər. Sətir `(tenant_id,
employee_id)` cütü ilə TAM eyniləşdirilir (DB `UNIQUE`), ona görə
`ExceptionId`/`PosThresholdId` kimi ayrıca `NewType` yaratmaq YALNIZ istifadə
olunmayacaq bir soysummuş özəllik olardı.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from src.domain.entities.base import DomainRuleError
from src.domain.value_objects.identifiers import EmployeeId, StoreId, TenantId
from src.domain.value_objects.scheduling import require_aware

#: `employee_behavior_baseline.avg_checkin_minutes` CHECK-inin güzgüsü
#: (migrations/018: `>= 0 AND < 1440`). Sxem sərhədidir, ROOT parametri
#: DEYİL — dəyişdirilməsi miqrasiya tələb edir.
MAX_CHECKIN_MINUTES: Final = 1440


@dataclass(frozen=True)
class CheckInObservation:
    """Bir günün TƏSDİQLƏNMİŞ (STEP C, `verified_at`) giriş anı.

    STEP A (`requested_at`) yox, STEP C işlədilir: bölmə 4 `verified_at`-i
    açıq şəkildə "günün RƏSMİ başlama vaxtı" adlandırır (`attendance_record.
    verify()` docstring-i) və gecikmə hesablaması da elə bu sahədən istifadə
    edir — "check-in vaxtı" anlayışının sistemdəki YEGANƏ tərifi budur.
    """

    employee_id: EmployeeId
    store_id: StoreId
    checked_in_at: datetime
    #: `stores.timezone` (məs. "Asia/Baku") — dəqiqəyə çevirmə bu zona ÜZRƏ
    #: aparılır, DDL-in "yerli zamana çevrildikdən SONRA yaz" tələbinə görə.
    store_timezone: str

    def __post_init__(self) -> None:
        require_aware(self.checked_in_at, field="checked_in_at")


@dataclass(frozen=True)
class BehaviorBaseline:
    """`employee_behavior_baseline` sətrinin domen görünüşü (#8).

    Yoxlamalar DB `CHECK`-lərinin GÜZGÜSÜDÜR (`exception_record.py` ilə eyni
    prinsip): repo-dan yararsız sətir bərpa edilsə, xəta İSTİFADƏ ANINDA yox,
    OXU ANINDA üzə çıxsın.
    """

    tenant_id: TenantId
    employee_id: EmployeeId
    #: Orta check-in vaxtı — mağazanın yerli gecəyarısından keçən dəqiqə.
    avg_checkin_minutes: float
    #: Standart kənarlaşma (dəqiqə). Spesifikasiyadakı "variance" bunun
    #: kvadratıdır (migrations/018 şərhi) — kənarlaşma saxlanılır ki, ortanın
    #: vahidi ilə birbaşa müqayisə oluna bilsin.
    stddev_minutes: float
    #: Baz xəttin neçə günlük müşahidədən çıxdığı — az nümunədə anomaliya
    #: elan edilməməlidir (min. həddi `BehaviorAnomalyRule` yoxlayır).
    sample_size: int
    last_calculated_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.last_calculated_at, field="last_calculated_at")
        if not (0 <= self.avg_checkin_minutes < MAX_CHECKIN_MINUTES):
            raise DomainRuleError(
                "Orta check-in vaxtı 0–1440 dəqiqə arasında olmalıdır",
                context={"avg_checkin_minutes": self.avg_checkin_minutes},
            )
        if self.stddev_minutes < 0:
            raise DomainRuleError(
                "Standart kənarlaşma mənfi ola bilməz",
                context={"stddev_minutes": self.stddev_minutes},
            )
        if self.sample_size < 0:
            raise DomainRuleError(
                "Nümunə sayı mənfi ola bilməz",
                context={"sample_size": self.sample_size},
            )


__all__ = [
    "MAX_CHECKIN_MINUTES",
    "BehaviorBaseline",
    "CheckInObservation",
]
