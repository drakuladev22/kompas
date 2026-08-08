"""İcazə gecikməsi cərimə düsturu (spesifikasiya bölmə 4, PENALTY LOGIC).

Spesifikasiyanın hərfi mətni::

    Delay = max(0, Verified_Actual_Time − Requested_Time)
    Total = Requested + 2 × Delay
    Delay mənfi ola bilməz.

──────────────────────────────────────────────────────────────────────────────
ŞƏRH QEYDİ (TƏSDİQİNİZ TƏLƏB OLUNUR — bax `docs/open_questions.md`)
──────────────────────────────────────────────────────────────────────────────
İki düstur hərfi oxunuşda bir-birinə uyğun gəlmir:

* Birinci sətir `Delay`-i "TAM keçən vaxt" kimi təyin edir
  (`actual − requested_time`).
* İkinci sətir isə `Total = Requested + 2 × Delay` deyir — burada `Requested`
  bir MÜDDƏT olmalıdır (dəqiqə), yoxsa toplama dimensional olaraq mənasızdır.

Yeganə DAXİLƏN TUTARLI oxunuş: `Requested` = icazə üçün ayrılmış müddət
(allowance), `Delay` isə həmin müddəti AŞAN hissə::

    elapsed = actual_return_time − requested_time
    delay   = max(0, elapsed − allowance)
    total   = allowance + 2 × delay

Yoxlama: 60 dəq. icazə, 90 dəq. sonra qayıdış → delay = 30, total = 120.
`allowance = 0` verildikdə düstur hərfi mətnə çevrilir: `delay = elapsed`,
`total = 2 × elapsed`.

`allowance_minutes` QƏSDƏN açıq parametrdir və defolt **0**-dır (ən sərt,
hərfi variant). Mənbəyi biznes qərarıdır: İcazə Növünün standart müddəti,
sabit sistem limiti, yoxsa 0. Bölmə 4 deyir ki, İcazə Növü seçimi "düsturu
DƏYİŞMİR" — bu, defolt 0 seçiminin əsasıdır.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from src.domain.value_objects.scheduling import require_aware
from src.shared.exceptions import KompasOSError


class InvalidPenaltyInputError(KompasOSError):
    """Cərimə hesablamasının girişi yararsızdır."""

    user_message = "Cərimə hesablana bilmədi — vaxt məlumatları düzgün deyil."


@dataclass(frozen=True)
class LeavePenalty:
    """İcazə gecikməsinin hesablanmış nəticəsi.

    Attributes:
        elapsed_minutes: Mağazadan kənarda keçirilən TAM vaxt.
        allowance_minutes: İcazə üçün ayrılmış müddət (`Requested`).
        delay_minutes: Ayrılmış müddəti aşan hissə — HEÇ VAXT mənfi.
        total_minutes: Aylıq icazə limitindən çıxılacaq yekun dəyər.
    """

    elapsed_minutes: int
    allowance_minutes: int
    delay_minutes: int
    total_minutes: int

    def __post_init__(self) -> None:
        if self.delay_minutes < 0:
            raise InvalidPenaltyInputError(f"Delay mənfi ola bilməz: {self.delay_minutes}")
        if self.total_minutes < 0:
            raise InvalidPenaltyInputError(f"Total mənfi ola bilməz: {self.total_minutes}")

    @property
    def is_late(self) -> bool:
        return self.delay_minutes > 0

    def to_dict(self) -> dict[str, int]:
        return {
            "elapsed_minutes": self.elapsed_minutes,
            "allowance_minutes": self.allowance_minutes,
            "delay_minutes": self.delay_minutes,
            "total_minutes": self.total_minutes,
        }


def calculate_leave_penalty(
    *,
    requested_time: datetime,
    actual_return_time: datetime,
    allowance_minutes: int = 0,
) -> LeavePenalty:
    """İcazə cərimə göstəricilərini hesablayır.

    KRİTİK (bölmə 4): hesablama YALNIZ Kamera Operatorunun təsdiqlədiyi
    FAKTİKİ qayıdış vaxtına əsaslanır — operatorun düyməni kliklədiyi vaxta
    YOX. Manual override halında `actual_return_time` override edilmiş vaxtdır.

    Args:
        requested_time: STEP 1-də NTP-yə qarşı yoxlanılmış sorğu anı.
        actual_return_time: STEP 3-də təsdiqlənmiş faktiki qayıdış anı.
        allowance_minutes: İcazə üçün ayrılmış müddət (yuxarıdakı şərh qeydinə
            bax). Defolt 0 — hərfi spesifikasiya davranışı.

    Raises:
        InvalidPenaltyInputError: Qayıdış sorğudan ƏVVƏLdirsə (bölmə 4,
            validasiya qaydası 1) və ya vaxtlar naive-dirsə.
    """
    require_aware(requested_time, field="requested_time")
    require_aware(actual_return_time, field="actual_return_time")

    if allowance_minutes < 0:
        raise InvalidPenaltyInputError(f"Ayrılmış müddət mənfi ola bilməz: {allowance_minutes}")

    if actual_return_time < requested_time:
        # Bölmə 4, validasiya 1: "Daxil edilən vaxt sorğu vaxtından əvvəl ola
        # bilməz." Bunu sükutla 0-a yuvarlaqlaşdırmaq TƏHLÜKƏLİDİR — belə
        # məlumat operator səhvini və ya saat sürüşməsini gizlədər.
        raise InvalidPenaltyInputError(
            "Qayıdış vaxtı sorğu vaxtından əvvəl ola bilməz",
            user_message="Qayıdış vaxtı icazə vaxtından əvvəl ola bilməz.",
            context={
                "requested_time": requested_time.isoformat(),
                "actual_return_time": actual_return_time.isoformat(),
            },
        )

    # Yuxarı yuvarlaqlaşdırma: 30 saniyəlik gecikmə də 1 dəqiqə sayılır.
    # DB-dəki `calculate_leave_penalty()` funksiyası ilə eyni (CEIL).
    elapsed_seconds = (actual_return_time - requested_time).total_seconds()
    elapsed_minutes = math.ceil(elapsed_seconds / 60)

    delay_minutes = max(0, elapsed_minutes - allowance_minutes)
    total_minutes = allowance_minutes + 2 * delay_minutes

    return LeavePenalty(
        elapsed_minutes=elapsed_minutes,
        allowance_minutes=allowance_minutes,
        delay_minutes=delay_minutes,
        total_minutes=total_minutes,
    )


__all__ = ["InvalidPenaltyInputError", "LeavePenalty", "calculate_leave_penalty"]
