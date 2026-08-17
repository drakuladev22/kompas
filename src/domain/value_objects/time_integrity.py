"""Vaxt bütövlüyü — qeydin vaxt-möhürünə nə dərəcədə etibar edilə bilər (TIME-1).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU DOMEN ANLAYIŞIDIR, İNFRASTRUKTUR DETALI DEYİL
──────────────────────────────────────────────────────────────────────────────
«Serverdən vaxt almaq» texniki detaldır. Lakin «bu qeydin vaxtı təxminidir»
BİZNES faktıdır: gecikmə dəqiqələri cəriməyə çevrilir və mübahisə halında
işçi «o vaxt səhvdir» deyə bilər. Cavab verilə bilməsi üçün sistem hər
qeydin vaxtının HANSI mənbədən gəldiyini bilməli və saxlamalıdır.

Ona görə `TimeTrustLevel` domen tipidir və qeydin özü ilə birlikdə yazılır —
sonradan «yəqin onlayn idi» deyə təxmin etmək mümkün olmazdı.

──────────────────────────────────────────────────────────────────────────────
ÜÇ SƏVİYYƏ — VƏ NİYƏ İKİ DEYİL
──────────────────────────────────────────────────────────────────────────────
«Onlayn / oflayn» ikili bölgüsü kifayət etmirdi. Oflayn qalmağın ÖZÜ problem
deyil — tətbiq oflayn-first elan olunub. Problem oflayn qalmağın MÜDDƏTİdir:
monotonic saat da kvars dəqiqsizliyi ilə sürüşür (~ppm), yəni bir neçə saat
sonra fərq saniyələrlə, bir neçə gün sonra dəqiqələrlə ölçülür.

    SERVER_VERIFIED     — təzə server lövbəri var; vaxt sənəd kimi etibarlıdır
    MONOTONIC_ESTIMATE  — lövbər köhnəlib, LAKİN Root həddi daxilindədir;
                          qeyd yazılır və «təxmini» kimi işarələnir
    UNTRUSTED           — hədd aşılıb; qeyd YENƏ DƏ yazılır (işi dayandırmaq
                          daha böyük zərərdir), amma HR_Admin-ə «vaxt-dəqiqliyi
                          şübhəli» siyahısında görünür

Üçüncü səviyyə bloklamır. Bloklamaq mağazanı dayandırardı və işçinin
davamiyyəti ümumiyyətlə qeyd olunmazdı — yəni vaxtın təxmini olmasından daha
pis nəticə. Bu, `ntp.py`-dakı «ölçülməyib → icazə var, lakin qeydə alınır»
qərarı ilə eyni məntiqdir.

──────────────────────────────────────────────────────────────────────────────
LOKAL SAAT SÜRÜŞMƏSİ AYRICA SAXLANILIR
──────────────────────────────────────────────────────────────────────────────
`local_clock_offset_seconds` qeydin vaxtına TƏSİR ETMİR — vaxt onsuz da
server lövbərindən gəlir. O, MANİPULYASİYA göstəricisidir: bu PC-nin Windows
saatı server vaxtından nə qədər fərqlənir. Böyük fərq fırıldaqçılıq cəhdinin
siqnalıdır və audit-ə yazılır (bax `TIME-1` Faza 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

#: Lövbərin yaşı bu qədər olduqda `SERVER_VERIFIED` sayılmır — FALLBACK.
#: HƏQİQİ MƏNBƏ `system_limits.SERVER_TIME_SYNC_INTERVAL_SECONDS` (miqrasiya 062).
FALLBACK_ANCHOR_FRESH_SECONDS: Final[float] = 600.0


class TimeTrustLevel(str, Enum):
    """Vaxt-möhürünün mənbəyi və etibarlılıq dərəcəsi.

    `str, Enum` qəsdəndir (`CLAUDE.md` §4): dəyər audit sətrinə və DB sütununa
    olduğu kimi düşür, `StrEnum`-a keçid həmin çıxışı dəyişərdi.
    """

    #: Təzə server lövbəri — vaxt Postgres `clock_timestamp()`-dan törəyir.
    SERVER_VERIFIED = "SERVER_VERIFIED"
    #: Lövbər köhnəlib, monotonic saatla uzadılıb; Root həddi daxilində.
    MONOTONIC_ESTIMATE = "MONOTONIC_ESTIMATE"
    #: Oflayn müddət Root həddini aşıb — vaxt-dəqiqliyi şübhəlidir.
    UNTRUSTED = "UNTRUSTED"


#: Qeydin «təxmini vaxtlı» sayıldığı səviyyələr. Tək yerdə saxlanılır ki,
#: yeni səviyyə əlavə olunanda onu unudulmuş yerdə «dəqiq» saymaq mümkün olmasın.
APPROXIMATE_LEVELS: Final[frozenset[TimeTrustLevel]] = frozenset(
    {TimeTrustLevel.MONOTONIC_ESTIMATE, TimeTrustLevel.UNTRUSTED}
)


@dataclass(frozen=True)
class TimeIntegrityStatus:
    """Vaxt mənbəyinin cari vəziyyəti — ekranda və audit yazısında göstərilir."""

    level: TimeTrustLevel
    #: Son uğurlu server sorğusundan bəri keçən saniyə; heç alınmayıbsa `None`.
    anchor_age_seconds: float | None
    #: Server vaxtı − bu PC-nin Windows saatı. Müsbət → PC-nin saatı GERİ qalır.
    #: Ölçülməyibsə `None`. Qeydin vaxtına təsir ETMİR — manipulyasiya siqnalıdır.
    local_clock_offset_seconds: float | None
    #: Server sorğusunun gediş-dönüş vaxtı — lövbərin dəqiqlik payı.
    round_trip_seconds: float | None = None

    @property
    def is_approximate(self) -> bool:
        """Qeyd «təxmini vaxtlı» kimi işarələnməlidirmi."""
        return self.level in APPROXIMATE_LEVELS

    @property
    def is_server_verified(self) -> bool:
        return self.level is TimeTrustLevel.SERVER_VERIFIED

    def describe(self) -> str:
        """İstifadəçiyə göstərilən qısa izah (bölmə 9: yeganə interfeys dili)."""
        if self.level is TimeTrustLevel.SERVER_VERIFIED:
            return "Vaxt server ilə təsdiqlənib"
        if self.level is TimeTrustLevel.MONOTONIC_ESTIMATE:
            return "Server ilə əlaqə yoxdur — vaxt təxminidir"
        return "Vaxt dəqiqliyi şübhəlidir — server ilə uzun müddət əlaqə yoxdur"


#: Server heç vaxt oxunmayıb — tətbiq yeni açılıb və ya baza əlçatmazdır.
#: `UNTRUSTED` seçilir, `MONOTONIC_ESTIMATE` YOX: lövbərsiz vaxt sadəcə
#: Windows saatıdır və onun dəqiqliyi barədə HEÇ NƏ bilmirik.
NO_ANCHOR_STATUS: Final[TimeIntegrityStatus] = TimeIntegrityStatus(
    level=TimeTrustLevel.UNTRUSTED,
    anchor_age_seconds=None,
    local_clock_offset_seconds=None,
)


__all__ = [
    "APPROXIMATE_LEVELS",
    "FALLBACK_ANCHOR_FRESH_SECONDS",
    "NO_ANCHOR_STATUS",
    "TimeIntegrityStatus",
    "TimeTrustLevel",
]
