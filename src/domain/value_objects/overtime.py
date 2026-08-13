"""Norma üstü iş saatlarının domen tipləri (#15, kompasos11.md Faza 6).

Bu modul İKİ şeyi saxlayır:

    1. `WorkedSpan` — bir işçinin BİR gününün ölçülə bilən iş pəncərəsi
       (xam mənbə: növbə təyinatı + təsdiqlənmiş giriş + icazə dəqiqələri).
    2. `OvertimeEntry` — `overtime_log` sətrinin domen görünüşü
       (migrations/019, sətir 123–207).

──────────────────────────────────────────────────────────────────────────────
"FAKTİKİ SAAT" NİYƏ TƏYİN OLUNMUŞ NÖVBƏDƏN ÇIXIR, ÇIXIŞ QEYDİNDƏN YOX
──────────────────────────────────────────────────────────────────────────────
KompasOS-da "işdən çıxdım" düyməsi YOXDUR — `attendance_records` yalnız günün
BAŞLANĞICINI (`verified_at`, STEP C) qeyd edir. Ona görə günün uzunluğu üçün
yeganə etibarlı ölçü təyin edilmiş İş Rejiminin (`work_modes`) pəncərəsidir:

    faktiki saat = (növbənin bitməsi − faktiki başlama) − icazə dəqiqələri

Alternativ ("işçi 24 saat sistemdə görünür deyə gün 24 saat sayılsın" və ya
"norma qədər işləyib fərz edək") RƏDD EDİLDİ: birincisi absurd rəqəm, ikincisi
isə aşımı HEÇ VAXT göstərməzdi — yəni modulu mənasız edərdi.

Nəticə etibarilə aşım İKİ real səbəbdən yaranır və hər ikisi ölçülür:
    * admin normadan UZUN növbə təyin edib (məs. 08:00–20:00 = 12 saat);
    * işçi həftə ərzində NORMADAN ÇOX GÜN işləyib (6 × 7 saat = 42 saat).

──────────────────────────────────────────────────────────────────────────────
ERKƏN GƏLİŞ ƏLAVƏ SAAT SAYILMIR, GEC GƏLİŞ İSƏ AZALDIR
──────────────────────────────────────────────────────────────────────────────
Başlanğıc `max(növbənin başlanğıcı, təsdiqlənmiş giriş)` kimi götürülür.
Səbəb asimmetrikdir və qəsdəndir: növbədən 40 dəqiqə əvvəl gəlmək TAPŞIRILMIŞ
iş deyil (onu əlavə saat saymaq işçiyə "tez gəlib norma yığmaq" imkanı verərdi),
gec gəlmək isə həmin günün faktiki iş pəncərəsini REAL ŞƏKİLDƏ qısaldır.

Gecə növbəsi (`TimeRange.is_overnight`) avtomatik işləyir: `end_on()` bitmə
anını NÖVBƏTİ günə salır, ona görə 22:00–06:00 səkkiz saatdır, mənfi deyil.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Final

from src.domain.entities.base import DomainRuleError
from src.domain.value_objects.identifiers import EmployeeId, TenantId
from src.domain.value_objects.scheduling import (
    DEFAULT_TIMEZONE,
    TimeRange,
    require_aware,
)

#: `overtime_log` sütunları `NUMERIC(5, 2)`-dir (migrations/019) — kəsr hissəsi
#: iki rəqəmdir. Domen də EYNİ dəqiqliklə yuvarlaqlaşdırır ki, DB-yə yazılan
#: dəyər hesablanan dəyərdən fərqlənməsin (əks halda "2.505 → 2.51" fərqi
#: yalnız hesabatda üzə çıxardı).
HOURS_QUANTUM: Final = Decimal("0.01")

#: `NUMERIC(5, 2)` sxem tavanı. ROOT parametri DEYİL — dəyişdirilməsi miqrasiya
#: tələb edir, ona görə burada sabitdir.
MAX_LOGGED_HOURS: Final = Decimal("999.99")

_MINUTES_PER_HOUR: Final = Decimal(60)
_SECONDS_PER_HOUR: Final = Decimal(3600)


class OvertimeSource(str, Enum):
    """`overtime_log.source` — sətrin İDDİA SAHİBİ.

    DDL şərhi (migrations/019) bu ayrımı açıq tələb edir: avtomatik hesablanmış
    sətir sistemin, əl ilə yazılmış sətir isə insanın iddiasıdır. İkisini
    ayırmadan "sistem səhv sayır" mübahisəsi həll edilə bilmir.
    """

    AUTO_ATTENDANCE = "AUTO_ATTENDANCE"
    MANUAL_HR = "MANUAL_HR"


def to_hours(value: Decimal) -> Decimal:
    """Saatı `NUMERIC(5, 2)` dəqiqliyinə yuvarlaqlaşdırır (bank yuvarlağı YOX).

    `ROUND_HALF_UP` seçilib, çünki Python-un defolt `ROUND_HALF_EVEN`-i
    "7.125 → 7.12, 7.135 → 7.14" kimi insana izah edilməsi çətin nəticə verir;
    əmək saatı mübahisəsində rəqəmin necə alındığı İZAH EDİLƏ BİLƏN olmalıdır.
    """
    return value.quantize(HOURS_QUANTUM, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class WorkedSpan:
    """Bir işçinin bir gününün ölçülə bilən iş pəncərəsi (#15).

    `AttendanceFact` ilə QARIŞDIRILMAMALIDIR: o, tabelin STATUSUNU çıxarır
    (işdə/qayıb/istirahət), bu isə günün UZUNLUĞUNU. İki fərqli sual iki fərqli
    tipdir — birləşdirilsəydi, tabelin ön-doldurma sorğusu hər açılışda növbə
    saatlarını da gətirməli olardı və status hesablaması saat məlumatına
    ehtiyacı olmadığı halda ondan asılı görünərdi.
    """

    employee_id: EmployeeId
    work_date: date
    #: Həmin günə təyin edilmiş İş Rejimi. `None` = növbə təyinatı yoxdur.
    scheduled: TimeRange | None
    #: STEP C təsdiqlənmiş giriş anı (`attendance_records.verified_at`).
    #: `None` = işçi həmin gün təsdiqlənmiş girişi yoxdur (işə çıxmayıb).
    checked_in_at: datetime | None
    #: İcazə ilə mağazadan KƏNARDA keçən dəqiqələr (`leave_requests.total_minutes`).
    #: İş pəncərəsindən ÇIXILIR — əks halda 3 saatlıq icazə "işlənmiş saat"
    #: kimi sayılıb süni aşım yaradardı.
    leave_minutes: int = 0
    #: Mağazanın zonası (`stores.timezone`) — növbə saatları YEREL saatdır.
    store_timezone: str = DEFAULT_TIMEZONE

    def __post_init__(self) -> None:
        if self.checked_in_at is not None:
            require_aware(self.checked_in_at, field="checked_in_at")
        if self.leave_minutes < 0:
            raise DomainRuleError(
                "İcazə dəqiqələri mənfi ola bilməz",
                context={"leave_minutes": self.leave_minutes},
            )

    @property
    def is_measurable(self) -> bool:
        """Günün uzunluğu ÖLÇÜLƏ BİLİRMİ.

        Növbə təyinatı yoxdursa uzunluq NAMƏLUMDUR (bax modul başlığı) —
        "planlanmamış iş" faktı tabeldə görünür, lakin ona uydurulmuş saat
        yazmaq xəyali aşım yaradardı. Ona görə belə gün jurnala DÜŞMÜR.
        """
        return self.scheduled is not None and self.checked_in_at is not None

    @property
    def worked_hours(self) -> Decimal:
        """Faktiki işlənmiş saat (modul başlığındakı düstur)."""
        if self.scheduled is None or self.checked_in_at is None:
            return Decimal("0.00")

        shift_start = self.scheduled.start_on(self.work_date, timezone_name=self.store_timezone)
        shift_end = self.scheduled.end_on(self.work_date, timezone_name=self.store_timezone)
        # Erkən gəliş əlavə saat saymır, gec gəliş isə pəncərəni qısaldır.
        effective_start = max(shift_start, self.checked_in_at)
        if effective_start >= shift_end:
            # Növbə bitdikdən sonra təsdiqlənmiş giriş (məs. operator gec
            # təsdiqləyib) MƏNFİ saat verməməlidir — sıfır qalır.
            return Decimal("0.00")

        worked = Decimal(int((shift_end - effective_start).total_seconds())) / _SECONDS_PER_HOUR
        worked -= Decimal(self.leave_minutes) / _MINUTES_PER_HOUR
        return to_hours(max(Decimal(0), worked))


@dataclass(frozen=True)
class OvertimeEntry:
    """`overtime_log` sətrinin domen görünüşü (#15).

    Yoxlamalar DB `CHECK`-lərinin GÜZGÜSÜDÜR (`behavior_signals.py` ilə eyni
    prinsip): repo-dan yararsız sətir bərpa edilsə, xəta İSTİFADƏ ANINDA yox,
    OXU ANINDA üzə çıxsın.
    """

    tenant_id: TenantId
    employee_id: EmployeeId
    work_date: date
    #: Hesablama anında QÜVVƏDƏ OLAN norma — DONDURULUR (DDL şərhi): Root
    #: normanı sonradan dəyişsə, keçmiş sətrin izahı itməməlidir.
    norm_hours: Decimal
    actual_hours: Decimal
    #: 0.00 QANUNİDİR: yenidən hesablama aşımı sıfıra endirə bilər və sətri
    #: silmək "aşım heç vaxt olmayıb" təəssüratı yaradardı (DDL şərhi).
    hours_over_norm: Decimal
    source: OvertimeSource = OvertimeSource.AUTO_ATTENDANCE
    recorded_by: EmployeeId | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("norm_hours", self.norm_hours),
            ("actual_hours", self.actual_hours),
            ("hours_over_norm", self.hours_over_norm),
        ):
            if value < 0:
                raise DomainRuleError(
                    f"«{field_name}» mənfi ola bilməz",
                    context={field_name: str(value)},
                )
            if value > MAX_LOGGED_HOURS:
                raise DomainRuleError(
                    f"«{field_name}» sxem tavanını (NUMERIC(5,2)) aşır",
                    context={field_name: str(value)},
                )
        # `chk_overtime_manual_author` güzgüsü: əl ilə yazılan aşımın sahibi
        # olmalıdır, əks halda "bu rəqəmi kim yazdı?" sualı cavabsız qalır.
        if self.source is OvertimeSource.MANUAL_HR and self.recorded_by is None:
            raise DomainRuleError(
                "Əl ilə yazılan norma üstü saatın məsul şəxsi göstərilməlidir",
                user_message="Əl ilə yazılan aşım üçün məsul şəxs göstərilməlidir.",
                context={"work_date": self.work_date.isoformat()},
            )

    @property
    def has_overtime(self) -> bool:
        """Sətir FAKTİKİ aşım daşıyırmı (0.00 sətirlər hesabata düşmür)."""
        return self.hours_over_norm > 0


__all__ = [
    "HOURS_QUANTUM",
    "MAX_LOGGED_HOURS",
    "OvertimeEntry",
    "OvertimeSource",
    "WorkedSpan",
    "to_hours",
]
