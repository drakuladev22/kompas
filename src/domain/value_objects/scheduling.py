"""Vaxt/növbə value object-ləri (spesifikasiya bölmə 4).

Bura İş Rejimi (`work_modes`) və gecikmə təyinetmə məntiqi daxildir.

VACİB: bütün `datetime` dəyərləri **tz-aware** olmalıdır. Naive datetime
QADAĞANDIR — mağazalar `Asia/Baku` zonasındadır, lakin serverlər UTC-də
işləyir və qarışıqlıq birbaşa yanlış cərimə hesablamasına gətirib çıxarır.
Ruff-un `DTZ` qaydası bunu CI-da qoruyur.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from src.shared.exceptions import KompasOSError

DEFAULT_TIMEZONE: Final[str] = "Asia/Baku"
MINUTES_PER_DAY: Final[int] = 24 * 60


class InvalidScheduleError(KompasOSError):
    """Növbə/vaxt konfiqurasiyası yararsızdır."""

    user_message = "Vaxt konfiqurasiyası düzgün deyil."


class NaiveDatetimeError(KompasOSError):
    """Vaxt zonası olmayan `datetime` verildi.

    Bu, proqramçı səhvidir və sükutla düzəldilməməlidir — səhv zona
    yanlış `Delay` hesablamasına, yəni yanlış cərimə məbləğinə çevrilir.
    """

    user_message = "Daxili vaxt xətası. Administratorla əlaqə saxlayın."


def require_aware(moment: datetime, *, field: str = "vaxt") -> datetime:
    """`datetime`-ın tz-aware olduğunu təmin edir."""
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise NaiveDatetimeError(
            f"{field} vaxt zonası olmadan verilib (naive datetime) — "
            f"UTC və ya mağaza zonası açıq göstərilməlidir",
            context={"field": field, "value": moment.isoformat()},
        )
    return moment


@dataclass(frozen=True)
class TimeRange:
    """Gün ərzində saat aralığı — İş Rejimi şablonu (`work_modes`).

    Gecə növbəsi (`22:00–06:00`) dəstəklənir: `end <= start` olduqda aralıq
    növbəti günə keçir və `is_overnight` `True` olur.
    """

    start: time
    end: time

    def __post_init__(self) -> None:
        if self.start == self.end:
            raise InvalidScheduleError("İş rejiminin başlanğıc və bitmə saatı eyni ola bilməz")

    @property
    def is_overnight(self) -> bool:
        return self.end <= self.start

    @property
    def duration(self) -> timedelta:
        start_minutes = self.start.hour * 60 + self.start.minute
        end_minutes = self.end.hour * 60 + self.end.minute
        span = end_minutes - start_minutes
        if span <= 0:
            span += MINUTES_PER_DAY
        return timedelta(minutes=span)

    def start_on(self, day: date, *, timezone_name: str = DEFAULT_TIMEZONE) -> datetime:
        """Verilmiş gün üçün növbənin başlanğıc anını qaytarır (tz-aware)."""
        return datetime.combine(day, self.start, tzinfo=ZoneInfo(timezone_name))

    def end_on(self, day: date, *, timezone_name: str = DEFAULT_TIMEZONE) -> datetime:
        """Bitmə anı — gecə növbəsində NÖVBƏTİ günə düşür."""
        end_day = day + timedelta(days=1) if self.is_overnight else day
        return datetime.combine(end_day, self.end, tzinfo=ZoneInfo(timezone_name))

    def covers(self, day: date, moment: datetime, *, timezone_name: str = DEFAULT_TIMEZONE) -> bool:
        """`moment` `day` üçün planlaşdırılan növbənin İÇİNDƏDİRMİ (D10).

        Yarı-açıq aralıq: `[start_on(day), end_on(day))`. Gecə növbəsi
        üçün `end_on()` artıq NÖVBƏTİ günə keçir — burada təkrar
        hesablanmır, sadəcə çağırılır (bax modul başlığı, `work_norm.py`
        eyni qərar).
        """
        require_aware(moment, field="moment")
        start = self.start_on(day, timezone_name=timezone_name)
        end = self.end_on(day, timezone_name=timezone_name)
        return start <= moment < end

    def format_az(self) -> str:
        return f"{self.start:%H:%M}–{self.end:%H:%M}"

    def __str__(self) -> str:
        return self.format_az()


@dataclass(frozen=True)
class LatenessAssessment:
    """Morning Check-in gecikmə qiymətləndirməsi (spesifikasiya bölmə 4).

    QAYDA: "İşçinin Morning Check-in `🟢 Verified` vaxtı, ona həmin gün üçün
    təyin edilmiş İş Rejiminin başlanğıc saatından gecdirsə, Gündəlik Tabeldə
    avtomatik «Gecikib» kimi işarələnir — bu, AYRICA CƏRİMƏ YARATMIR, sadəcə
    hesabat/məlumat xarakterlidir."
    """

    is_late: bool
    late_minutes: int
    tolerance_minutes: int
    scheduled_start: datetime | None

    @property
    def creates_fine(self) -> bool:
        """HƏMİŞƏ `False` — gecikmə özü cərimə yaratmır (bölmə 4)."""
        return False


def checkin_minutes_since_midnight(
    moment: datetime, *, timezone_name: str = DEFAULT_TIMEZONE
) -> float:
    """Bir anın MAĞAZANIN yerli gecəyarısından neçə dəqiqə sonra olduğu (#8).

    İşçi Davranış Baz Xətti (migrations/018, `employee_behavior_baseline`)
    `TIME` yox, dəqiqə saxlayır və DDL şərhi UTC damğasının YEREL zamana
    çevrildikdən SONRA yazılmasını tələb edir — server UTC-də işləsə də,
    "adət vaxtı" mağazanın yerli saatına aiddir (bax modul başlığı, DTZ
    qaydası). `astimezone()` YEREL TARİXƏ görə çevirir: saat qurşağı UTC-dən
    fərqli olanda (Bakı UTC+4 kimi) gecəyarını keçən anlar doğru günə düşür,
    ona görə bu funksiya birbaşa `moment.hour` YOX, çevrilmiş `local.hour`
    işlədir.

    QEYD (bilinən sadələşdirmə): nəticə XƏTTİ dəqiqədir (0–1440), DAİRƏVİ
    (circular) statistika DEYİL. Əksər növbələrdə giriş vaxtı sabit saata
    yaxın olduğu üçün bu, kifayət edir; yalnız gecə saat 00:00 ətrafında
    dəyişən nadir hallarda ədədi orta və standart kənarlaşma real yayılmanı
    bir qədər təhrif edə bilər — bu, gələcək təkmilləşdirmə üçün açıq qalır.
    """
    require_aware(moment, field="moment")
    local = moment.astimezone(ZoneInfo(timezone_name))
    return local.hour * 60 + local.minute + local.second / 60


def assess_lateness(
    *,
    verified_at: datetime,
    scheduled_start: datetime | None,
    tolerance_minutes: int = 0,
) -> LatenessAssessment:
    """Gecikməni hesablayır.

    Args:
        verified_at: Kamera Operatorunun təsdiqlədiyi FAKTİKİ giriş anı.
        scheduled_start: İş Rejiminə görə planlaşdırılmış başlanğıc.
            `None` (rejim təyin edilməyib) → gecikmə hesablanmır.
        tolerance_minutes: `system_limits.LATE_TOLERANCE_MINUTES` (defolt 15).
    """
    require_aware(verified_at, field="verified_at")
    if scheduled_start is None:
        return LatenessAssessment(False, 0, tolerance_minutes, None)

    require_aware(scheduled_start, field="scheduled_start")
    if tolerance_minutes < 0:
        raise InvalidScheduleError("Gecikmə tolerantlığı mənfi ola bilməz")

    delta = verified_at - scheduled_start
    raw_minutes = int(delta.total_seconds() // 60)
    late_minutes = max(0, raw_minutes - tolerance_minutes)

    return LatenessAssessment(
        is_late=late_minutes > 0,
        late_minutes=late_minutes,
        tolerance_minutes=tolerance_minutes,
        scheduled_start=scheduled_start,
    )


def resolve_work_date(
    at: datetime,
    *,
    schedules: Mapping[date, TimeRange],
    timezone_name: str = DEFAULT_TIMEZONE,
) -> date:
    """`at` anının HANSI İŞ GÜNÜNƏ aid olduğunu tapır (D10 audit tapıntısı).

    ──────────────────────────────────────────────────────────────────────────
    TAPILAN QÜSUR
    ──────────────────────────────────────────────────────────────────────────
    `MorningCheckInUseCase.start_day()`/`verify()` əvvəl `work_date or
    at.date()` yazırdı — gecə növbəsi (22:00–06:00) işçisi GECƏYARIDAN SONRA
    daxil olanda (`at.date()` artıq NÖVBƏTİ təqvim günüdür) `scheduled_start()`
    həmin YANLIŞ günə sorğu edirdi və növbə (əvvəlki günə yazılıb) HEÇ VAXT
    tapılmırdı — gecikmə qiymətləndirilmirdi, tabel sətri səhv günə yazılırdı.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ "GECƏYARIDAN SONRA ƏVVƏLKİ GÜNƏ BAX" KİMİ TƏXMİN İŞLƏDİLMİR
    ──────────────────────────────────────────────────────────────────────────
    Sadə saat-həddi ("00:00–10:00 arası əvvəlki günə bax") ERKƏN gələn GÜNDÜZ
    növbəsi işçisini YANLIŞLIQLA dünənki gecə növbəsinə bağlaya bilərdi. Bu
    funksiya ƏVƏZİNƏ DƏQİQ ƏHATƏ yoxlayır: çağıran İKİ namizəd günün
    (bugün, dünən) HƏLL OLUNMUŞ `TimeRange`-lərini (`ShiftRepository.
    schedules_for`) verir, seçim YALNIZ `TimeRange.covers()` əsasında olur.

    Qaydalar:
      1. YALNIZ dünənin `TimeRange`-i `at`-ı əhatə edirsə (gecə növbəsi,
         gecəyarıdan sonra giriş) → DÜNƏN qaytarılır.
      2. YALNIZ bugünün `TimeRange`-i əhatə edirsə (normal hal) → BUGÜN.
      3. HEÇ BİRİ əhatə etmirsə (planlaşdırılmamış giriş) → `at.date()`
         (MÖVCUD sükut davranışı DƏYİŞMİR — bu, HƏQİQƏTƏN gözlənilməyən
         girişdir, təxmin etməyə çalışmırıq).
      4. HƏR İKİSİ əhatə edirsə (üst-üstə düşən təyinat — normalda mümkün
         olmamalı məlumat qüsuru): DAHA GEC BAŞLAYAN namizəd seçilir (`at`-a
         ən yaxın başlanğıc) — sükutla ixtiyari seçim QALMIR. Səbəb: iki
         üst-üstə düşən növbədən işçinin faktiki olaraq HANSININ İÇİNDƏ
         olduğu sualının ən məntiqli cavabı "son başlanmış növbə"dir.

    `schedules`-də olmayan gün (istirahət / sabit saatı olmayan İş Rejimi)
    əhatə yoxlamasına DAXİL EDİLMİR — bax `ShiftRepository.schedules_for`.
    """
    require_aware(at, field="at")
    covering = [
        day
        for day, schedule in schedules.items()
        if schedule.covers(day, at, timezone_name=timezone_name)
    ]
    if not covering:
        return at.date()
    if len(covering) == 1:
        return covering[0]
    return max(
        covering,
        key=lambda day: schedules[day].start_on(day, timezone_name=timezone_name),
    )


__all__ = [
    "DEFAULT_TIMEZONE",
    "InvalidScheduleError",
    "LatenessAssessment",
    "NaiveDatetimeError",
    "TimeRange",
    "assess_lateness",
    "checkin_minutes_since_midnight",
    "require_aware",
    "resolve_work_date",
]
