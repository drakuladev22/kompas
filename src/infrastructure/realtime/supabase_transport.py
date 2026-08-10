"""Supabase Realtime nəqliyyatı — `RealtimeTransport` protokolunun tətbiqi.

`channel.py` keçid məntiqini (WebSocket ↔ polling) DB-siz və şəbəkəsiz test
edilə bilən saxlayır; bu modul isə faktiki WebSocket bağlantısını qurur.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI FAYL VƏ NİYƏ GEC İDXAL
──────────────────────────────────────────────────────────────────────────────
`supabase` paketi ağırdır və kiosk PC-də tətbiqin açılma müddətinə birbaşa
təsir edir. Kiosk rejimində Dashboard Builder heç vaxt açılmır, yəni realtime
də lazım deyil. Ona görə paket YALNIZ `connect()` çağırıldıqda idxal olunur —
modul səviyyəsində idxal hər işə düşməyə saniyələr əlavə edərdi.

──────────────────────────────────────────────────────────────────────────────
KONFİQURASİYA YOXDURSA — İSTİSNA, SÜKUT YOX
──────────────────────────────────────────────────────────────────────────────
`connect()` uğursuz olduqda `LiveUpdateChannel` onu tutub polling-ə keçir
(bax `channel.py` `RealtimeTransport` şərhi). Ona görə burada "konfiqurasiya
yoxdur" halı da İSTİSNA kimi bildirilir: sükutla "bağlandım" demək kanalı
əbədi olaraq yalançı `LIVE` vəziyyətdə saxlayardı və istifadəçi köhnə
məlumata canlı kimi baxardı.

──────────────────────────────────────────────────────────────────────────────
HANSI AÇARLA QOŞULUR
──────────────────────────────────────────────────────────────────────────────
`anon` açarı — müştəri `.exe`-sinin daxilindəki açar (bölmə 8). RLS həmin
açarı öz tenant-ının sətirləri ilə məhdudlaşdırır, yəni realtime axını da
avtomatik tenant-scoped olur. `service_role` BURADA HEÇ VAXT işlədilmir.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Final

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

_log = get_logger(__name__)
_error_log = get_logger(__name__, channel=LogChannel.ERROR)

SUPABASE_URL_ENV: Final = "KOMPASOS_SUPABASE_URL"
SUPABASE_ANON_KEY_ENV: Final = "KOMPASOS_SUPABASE_ANON_KEY"

#: Realtime hadisəsi kimi qəbul edilən PostgreSQL əməliyyatları.
WATCHED_EVENTS: Final[tuple[str, ...]] = ("INSERT", "UPDATE", "DELETE")


class RealtimeConfigError(KompasOSError):
    """Supabase ünvanı və ya `anon` açarı təyin edilməyib."""

    user_message = "Canlı yeniləmə konfiqurasiya edilməyib — dövri yeniləmə istifadə olunur."


class SupabaseRealtimeTransport:
    """`RealtimeTransport` — Supabase Realtime kanallarına abunə.

    Args:
        url: Supabase layihə ünvanı; boşdursa mühit dəyişənindən oxunur.
        anon_key: `anon` açarı; boşdursa mühit dəyişənindən oxunur.
        schema: İzlənən sxem — layihədə hər şey `kompasos` altındadır.
    """

    def __init__(
        self,
        *,
        url: str = "",
        anon_key: str = "",
        schema: str = "kompasos",
    ) -> None:
        self._url = url or os.environ.get(SUPABASE_URL_ENV, "").strip()
        self._anon_key = anon_key or os.environ.get(SUPABASE_ANON_KEY_ENV, "").strip()
        self._schema = schema
        self._client: Any | None = None
        self._channels: list[Any] = []

    @property
    def is_configured(self) -> bool:
        """Konfiqurasiya tamdırmı — `LiveUpdateChannel` qurulmazdan əvvəl yoxlanır."""
        return bool(self._url and self._anon_key)

    def connect(self, channels: Iterable[str], on_event: Callable[[str, Any], None]) -> None:
        """Verilmiş cədvəllərə abunə olur.

        `channels` cədvəl adlarıdır (`leave_requests`, `attendance_records`, ...)
        — hər biri üçün ayrıca Realtime kanalı açılır. Bir kanalda bir neçə
        cədvəli birləşdirmək mümkündür, lakin o zaman biri qırıldıqda hamısı
        qırılardı və hansının problem yaratdığı görünməzdi.
        """
        if not self.is_configured:
            raise RealtimeConfigError(
                "Supabase ünvanı və ya anon açarı təyin edilməyib",
                context={"missing_env": [SUPABASE_URL_ENV, SUPABASE_ANON_KEY_ENV]},
            )

        # Gec idxal — modul başlığına bax.
        from supabase import create_client  # noqa: PLC0415

        # `Any` QƏSDƏNDİR: `supabase` paketinin realtime API-si versiyalar
        # arasında ad dəyişdirir (`on_postgres_changes` ↔ `on`), lakin bu
        # modul onun yeganə istifadə nöqtəsidir. Tip yoxlamasını burada
        # zorlamaq paket yeniləndikdə bütün build-i sındırardı; əvəzində
        # bağlantı xətası işləmə zamanı tutulur və polling-ə keçilir.
        client: Any = create_client(self._url, self._anon_key)
        self._client = client
        opened: list[Any] = []
        try:
            for table in channels:
                channel: Any = client.channel(f"kompasos:{table}")
                for event in WATCHED_EVENTS:
                    channel = channel.on_postgres_changes(
                        event=event,
                        schema=self._schema,
                        table=table,
                        callback=_dispatcher(table, on_event),
                    )
                channel.subscribe()
                opened.append(channel)
        except Exception:
            # Yarımçıq abunəlik qalmamalıdır: bəziləri açıq, bəziləri bağlı
            # vəziyyət `is_connected()`-i yalançı `True` edərdi.
            for channel in opened:
                _safe_unsubscribe(channel)
            self._client = None
            raise

        self._channels = opened
        _log.info(
            "REALTIME_CONNECTED",
            extra={"channel_count": len(opened), "schema": self._schema},
        )

    def disconnect(self) -> None:
        """Bütün abunəlikləri bağlayır — istisna ATMIR.

        Bağlanma yolunda xəta atmaq tətbiqin bağlanmasını və ya polling-ə
        keçidi bloklayardı; halbuki hər iki halda artıq problem var.
        """
        for channel in self._channels:
            _safe_unsubscribe(channel)
        self._channels = []
        self._client = None
        _log.info("REALTIME_DISCONNECTED")

    def is_connected(self) -> bool:
        return bool(self._channels)


def _dispatcher(table: str, on_event: Callable[[str, Any], None]) -> Callable[[Any], None]:
    """Supabase geri-çağırışını kanalın gözlədiyi `(ad, yük)` formasına çevirir.

    Geri-çağırış içindəki istisna UDULUR: o, Realtime kitabxanasının öz
    axınında işləyir və orada qalxan xəta bütün abunəliyi sükutla öldürərdi.
    """

    def handle(payload: Any) -> None:
        try:
            on_event(table, payload)
        except Exception:
            _error_log.exception("REALTIME_CALLBACK_FAILED", extra={"table": table})

    return handle


def _safe_unsubscribe(channel: Any) -> None:
    try:
        channel.unsubscribe()
    except Exception:
        _log.warning("REALTIME_UNSUBSCRIBE_FAILED")


__all__ = [
    "SUPABASE_ANON_KEY_ENV",
    "SUPABASE_URL_ENV",
    "WATCHED_EVENTS",
    "RealtimeConfigError",
    "SupabaseRealtimeTransport",
]
