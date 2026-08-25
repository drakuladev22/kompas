"""Uzatılmış offline rejim nəzarəti — `v2backlog.md` Faza 5.1.

    "ROOT PARAMETRİ: «maksimum offline buferlənmə müddəti/say-həddi». Bu həddi
     aşanda, PIN/Face Control giriş DAVAM edir (mövcud offline-bufer), amma
     HR-ə «uzun-müddətli offline» xəbərdarlığı gedir."

──────────────────────────────────────────────────────────────────────────────
GİRİŞ HEÇ VAXT BLOKLANMIR — BU, MODULUN ƏSAS QAYDASIDIR
──────────────────────────────────────────────────────────────────────────────
Bu modul YALNIZ ÖLÇÜR və «xəbərdarlıq göndərilməlidirmi?» sualına cavab
verir. Heç bir yerdə girişi dayandıran, buferə yazmağı rədd edən və ya
əməliyyatı ləğv edən kod YOXDUR və olmamalıdır: offline rejimin bütün
mövcudluq səbəbi şəbəkə kəsiləndə mağazanın İŞLƏMƏYƏ DAVAM ETMƏSİDİR. Həddi
aşmaq «dayan» siqnalı deyil, «kiməsə xəbər ver» siqnalıdır.

──────────────────────────────────────────────────────────────────────────────
XƏBƏRDARLIQ NƏ VAXT ÇATIR
──────────────────────────────────────────────────────────────────────────────
Bildiriş `notifications` cədvəlinə yazılır, yəni BAZA ƏLÇATAN olanda çatır.
Bu, ziddiyyət kimi görünə bilər («offline olanda xəbər verilmir»), lakin
əslində iki ayrı hal var və hər ikisi əhatə olunur:
  * QISMİ nasazlıq — yazı yolu (bufer) dolur, oxu/bildiriş yolu isə işləyir
    (məs. yalnız bir servisin bağlantısı qopub): xəbərdarlıq DƏRHAL gedir.
  * TAM nasazlıq — bağlantı bərpa olunan kimi, planlayıcının ilk dövrəsində
    gedir və mətn FAKTİKİ yaşı göstərir («38 saatdır gözləyir»), yəni
    keçmiş nasazlıq gizlənmir.
Ölçmənin ÖZÜ isə offline-da da davam edir və nəticə `outbox_meta`-ya yazılır
— təkrar-susma pəncərəsi bağlantı kəsintisini «yeni nasazlıq» kimi
saymamalıdır.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from src.domain.policies import SystemLimitKey
from src.infrastructure.config.limits import InfrastructureLimits
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from src.infrastructure.offline.buffer import OfflineBuffer

_log = get_logger(__name__)

#: `outbox_meta` açarının prefiksi — kirayəçi ID-si sonuna əlavə olunur.
#:
#: Bufer faylı MAŞINA aiddir və içində birdən çox kirayəçinin sətri ola bilər
#: (`OfflineBuffer._tenant_clause` şərhi) — tək açar işlədilsəydi, bir
#: kirayəçiyə göndərilən xəbərdarlıq digərinin xəbərdarlığını susdurardı.
_ALERT_KEY_PREFIX: Final = "offline_backlog_alerted_at:"


@dataclass(frozen=True)
class BacklogAssessment:
    """Buferin bir anlıq ölçüsü və ondan çıxan qərar."""

    pending_count: int
    oldest_age_hours: float
    max_hours: int
    max_entries: int
    #: Hədlərdən HANSI(LAR)I aşılıb — bildiriş mətni bunu adbaad yazır.
    age_exceeded: bool
    count_exceeded: bool

    @property
    def is_exceeded(self) -> bool:
        return self.age_exceeded or self.count_exceeded

    @property
    def summary_az(self) -> str:
        """Bildiriş mətni — RƏQƏMLƏRLƏ, çünki «çox gözləyir» heç nə demir."""
        parts: list[str] = []
        if self.age_exceeded:
            parts.append(
                f"ən köhnə yazı {self.oldest_age_hours:.0f} saatdır gözləyir "
                f"(hədd: {self.max_hours} saat)"
            )
        if self.count_exceeded:
            parts.append(f"buferdə {self.pending_count} yazı toplanıb (hədd: {self.max_entries})")
        if not parts:
            return (
                f"Bufer normaldır: {self.pending_count} yazı, ən köhnəsi "
                f"{self.oldest_age_hours:.0f} saat."
            )
        return "Uzun-müddətli offline: " + ", ".join(parts) + "."


class OfflineBacklogMonitor:
    """Buferin yaşını/həcmini ölçür və təkrar-susma pəncərəsini idarə edir."""

    def __init__(
        self,
        buffer: OfflineBuffer,
        *,
        limits: InfrastructureLimits | None = None,
    ) -> None:
        self._buffer = buffer
        # `limits` verilməzsə fallback — monitorun ÖZÜ baza əlçatmazlığında
        # işləməlidir (`disk_metric`-in eyni əsaslandırması). Bu, xüsusilə
        # BURADA vacibdir: modulun mövzusu məhz baza əlçatmazlığıdır.
        self._limits = limits or InfrastructureLimits()

    def assess(
        self, *, tenant_id: str | None = None, now: datetime | None = None
    ) -> BacklogAssessment:
        """Ölçür — heç nə yazmır, heç nə göndərmir."""
        moment = now or datetime.now(UTC)
        max_hours = self._limits.int_of(SystemLimitKey.OFFLINE_BACKLOG_MAX_HOURS)
        max_entries = self._limits.int_of(SystemLimitKey.OFFLINE_BACKLOG_MAX_ENTRIES)

        counts = self._buffer.counts(tenant_id=tenant_id)
        pending = counts.get("PENDING", 0)
        oldest = self._buffer.oldest_pending_queued_at(tenant_id=tenant_id)
        age_hours = 0.0 if oldest is None else max(0.0, (moment - oldest).total_seconds() / 3600.0)

        return BacklogAssessment(
            pending_count=pending,
            oldest_age_hours=age_hours,
            max_hours=max_hours,
            max_entries=max_entries,
            # Sıfır sətirli buferdə YAŞ hədd sayılmır: `oldest is None` halında
            # yaş 0-dır, lakin açıq şərt olmasa Root həddi 0-a endirəndə
            # (aralıq bunu qadağan edir, yenə də) boş bufer «aşılmış» görünərdi.
            age_exceeded=pending > 0 and age_hours > max_hours,
            count_exceeded=pending > max_entries,
        )

    def should_alert(
        self,
        assessment: BacklogAssessment,
        *,
        tenant_id: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Hədd aşılıb VƏ təkrar-susma pəncərəsi bitibmi.

        Pəncərə `outbox_meta`-dadır (bax modul başlığı) — proses yenidən
        başlasa da susma qüvvədə qalır. Yaddaşda saxlansaydı, hər açılışda
        yenidən bildiriş gedərdi və uzun offline dövründə tətbiqin hər
        başlanğıcı bir bildiriş yaradardı.
        """
        if not assessment.is_exceeded:
            return False
        moment = now or datetime.now(UTC)
        cooldown = self._limits.int_of(SystemLimitKey.OFFLINE_BACKLOG_WARNING_COOLDOWN_HOURS)
        raw = self._buffer.read_meta(self._alert_key(tenant_id))
        if raw is None:
            return True
        try:
            last = datetime.fromisoformat(raw)
        except ValueError:
            # Zədələnmiş dəyər susqunluğa səbəb OLMAMALIDIR: naməlum vəziyyətdə
            # xəbərdarlıq göndərmək, göndərməməkdən yaxşıdır.
            _log.warning("OFFLINE_BACKLOG_META_UNREADABLE", extra={"value": raw})
            return True
        return moment - last >= timedelta(hours=cooldown)

    def mark_alerted(self, *, tenant_id: str | None = None, now: datetime | None = None) -> None:
        """Xəbərdarlıq GÖNDƏRİLDİKDƏN SONRA çağırılır.

        AYRI METOD QƏSDƏNDİR: `should_alert()` yazı etsəydi, bildiriş
        göndərilməsə belə (məs. `Notifier` istisna atsa) pəncərə bağlanardı
        və növbəti xəbərdarlıq saatlarla gecikərdi.
        """
        moment = now or datetime.now(UTC)
        self._buffer.write_meta(self._alert_key(tenant_id), moment.isoformat())

    @staticmethod
    def _alert_key(tenant_id: str | None) -> str:
        return f"{_ALERT_KEY_PREFIX}{tenant_id or 'ALL'}"


__all__ = ["BacklogAssessment", "OfflineBacklogMonitor"]
