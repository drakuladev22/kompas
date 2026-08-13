"""İnfrastruktur sabitlərinin ROOT İdarə Mərkəzindən oxunması (Faza 10.2).

──────────────────────────────────────────────────────────────────────────────
BU MODUL NİYƏ VAR — MODUL SƏVİYYƏSİNDƏ DB OXUMAQ MÜMKÜN DEYİL
──────────────────────────────────────────────────────────────────────────────
`system_limits` sətri yalnız açıq bağlantı və `tenant_id` konteksti ilə oxuna
bilər (SEC-008: RLS). İnfrastruktur modullarının sabitləri isə İDXAL ANINDA
qiymətləndirilir — həmin anda nə bağlantı, nə də tenant məlumdur. Ona görə
naxış üç hissəlidir:

    1. `SystemLimitKey` + `DEFAULT_LIMITS` (domen) — açar və defolt.
    2. Modul sabiti `FALLBACK_*` adı ilə YERİNDƏ QALIR və dəyərini məhz
       `DEFAULT_LIMITS`-dən götürür (tək mənbə — iki yerdə ayrı ədəd saxlamaq
       onların bir gün ayrılmasını qaçılmaz edərdi).
    3. FAKTİKİ oxu ÇAĞIRIŞ ANINDA bu sinif vasitəsilə edilir; port yoxdursa
       və ya sorğu uğursuz olarsa fallback işləyir.

──────────────────────────────────────────────────────────────────────────────
KLAMP NİYƏ MƏCBURİDİR
──────────────────────────────────────────────────────────────────────────────
Bu açarların bir qismi tətbiqin İŞLƏMƏ QABİLİYYƏTİNƏ birbaşa təsir edir: DB
hovuzunun maksimumu `0` yazılsa heç bir sorğu icra oluna bilməz, NTP taymautu
`0` olsa saat heç vaxt yoxlanılmaz, `pg_dump` taymautu `0` olsa gecəlik nüsxə
həmişə uğursuz olar. `system_limits.set_value()` sərbəst mətn yazır — yəni
Root ekranından (və ya birbaşa SQL ilə) belə dəyər DÜŞƏ BİLƏR.

Ona görə hər açarın SƏRT aralığı var (`INFRA_LIMIT_BOUNDS`) və oxunan dəyər
həmin aralığa KLAMP edilir. Səhv konfiqurasiya "tətbiq açılmır" DEYİL,
"dəyər hüduda sıxıldı + xəbərdarlıq jurnalı" ilə nəticələnir — fail-safe
davranış, çünki alternativ (istisna atmaq) mağaza PC-sini tamamilə dayandırardı
və səbəbi yalnız DB-yə baxmaqla tapmaq olardı.

Aralıqlar migrations/032-dəki `min_value`/`max_value` sütunları ilə EYNİDİR;
`tests/unit/test_infrastructure_root_limits.py` bu pariteti qapı kimi yoxlayır
(iki mənbənin sükutla ayrılması ROOT ekranında "qəbul edilən" görünən, kodda
isə kəsilən dəyər deməkdir).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Final, Protocol

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from src.domain.value_objects.identifiers import TenantId

_log = get_logger(__name__)


#: Açar → (minimum, maksimum). migrations/032 ilə HƏRFƏN eyni dəyərlər.
#:
#: Siyahı-tipli açarlar (vergüllü cədvəllər) üçün aralıq HƏR ELEMENTƏ tətbiq
#: olunur — cədvəlin özünə deyil: "2,4,8" sətrində hər addım ayrıca gözləmə
#: müddətidir və mənasız olan məhz tək addımdır, cəm deyil.
INFRA_LIMIT_BOUNDS: Final[dict[SystemLimitKey, tuple[Decimal, Decimal]]] = {
    SystemLimitKey.PASSWORD_MIN_LENGTH: (Decimal(8), Decimal(128)),
    # Aşağı hüdud 30 — spesifikasiyanın "minimum 30 gün" tələbi burada
    # KİLİDLƏNİR: Root saxlama müddətini uzada bilər, qısalda BİLMƏZ.
    SystemLimitKey.BACKUP_MIN_RETENTION_DAYS: (Decimal(30), Decimal(3650)),
    SystemLimitKey.BACKUP_RETENTION_DAYS: (Decimal(30), Decimal(3650)),
    SystemLimitKey.BACKUP_DUMP_TIMEOUT_SECONDS: (Decimal(60), Decimal(86400)),
    SystemLimitKey.HEALTH_DISK_WARNING_PERCENT: (Decimal(50), Decimal(99)),
    SystemLimitKey.HEALTH_DISK_CRITICAL_PERCENT: (Decimal(55), Decimal(100)),
    SystemLimitKey.HEALTH_DB_PING_SLOW_MS: (Decimal(50), Decimal(60000)),
    SystemLimitKey.DRIVE_QUOTA_WARNING_RATIO: (Decimal("0.50"), Decimal("1.00")),
    SystemLimitKey.DRIVE_QUOTA_WARNING_COOLDOWN_DAYS: (Decimal(1), Decimal(90)),
    SystemLimitKey.NTP_POLL_INTERVAL_SECONDS: (Decimal(30), Decimal(86400)),
    SystemLimitKey.NTP_QUERY_TIMEOUT_SECONDS: (Decimal("1.0"), Decimal("30.0")),
    SystemLimitKey.NTP_SAMPLE_TTL_SECONDS: (Decimal(60), Decimal(86400)),
    SystemLimitKey.NTP_MAX_ROUND_TRIP_SECONDS: (Decimal("0.1"), Decimal("30.0")),
    SystemLimitKey.ERP_MATCH_AMBIGUITY_MARGIN: (Decimal("0.01"), Decimal("0.50")),
    SystemLimitKey.ERP_SYNC_MAX_PARALLEL_SERVERS: (Decimal(1), Decimal(32)),
    SystemLimitKey.ERP_SYNC_MAX_PAGES_PER_RUN: (Decimal(1), Decimal(1000)),
    SystemLimitKey.ERP_REQUEST_TIMEOUT_SECONDS: (Decimal("5.0"), Decimal("300.0")),
    # Aşağı hüdud 1-dir, 0 DEYİL: `range(max_retries)` CƏHD dövrüdür — 0
    # yazılsa serverə HEÇ BİR sorğu getməzdi və sinxronizasiya sükutla
    # dayanardı (eyni əsaslandırma `DRIVE_MAX_RETRIES` üçün də).
    SystemLimitKey.ERP_MAX_RETRIES: (Decimal(1), Decimal(10)),
    SystemLimitKey.KIOSK_RESTART_WINDOW_MINUTES: (Decimal(1), Decimal(1440)),
    SystemLimitKey.KIOSK_MAX_RESTARTS_PER_WINDOW: (Decimal(1), Decimal(100)),
    SystemLimitKey.KIOSK_RESTART_BACKOFF_SECONDS: (Decimal(1), Decimal(3600)),
    SystemLimitKey.DEVELOPER_DIRECTORY_STALE_DAYS: (Decimal(1), Decimal(365)),
    SystemLimitKey.NOTIFY_MAX_BATCH_SIZE: (Decimal(1), Decimal(500)),
    SystemLimitKey.NOTIFY_MAX_ATTEMPTS: (Decimal(1), Decimal(20)),
    SystemLimitKey.NOTIFY_RETRY_BACKOFF_MINUTES: (Decimal(1), Decimal(10080)),
    SystemLimitKey.NOTIFY_POLL_INTERVAL_SECONDS: (Decimal(5), Decimal(3600)),
    SystemLimitKey.EMAIL_SMTP_TIMEOUT_SECONDS: (Decimal("1.0"), Decimal("300.0")),
    SystemLimitKey.CRASH_MAX_REPORTS_PER_FINGERPRINT: (Decimal(1), Decimal(100)),
    SystemLimitKey.REALTIME_POLL_INTERVAL_SECONDS: (Decimal(5), Decimal(3600)),
    SystemLimitKey.REALTIME_RECONNECT_BACKOFF_SECONDS: (Decimal(1), Decimal(3600)),
    SystemLimitKey.OFFLINE_SYNC_BATCH_SIZE: (Decimal(1), Decimal(5000)),
    SystemLimitKey.OFFLINE_RETRY_BACKOFF_SECONDS: (Decimal(1), Decimal(86400)),
    SystemLimitKey.OFFLINE_SQLITE_TIMEOUT_SECONDS: (Decimal("1.0"), Decimal("120.0")),
    # Hovuzun minimumu 1-dən aşağı düşə BİLMƏZ: `0` yazılsa ilk sorğu yeni
    # bağlantı gözləyər və `timeout` bitənə qədər ekran donardı.
    SystemLimitKey.DB_POOL_MIN_SIZE: (Decimal(1), Decimal(32)),
    SystemLimitKey.DB_POOL_MAX_SIZE: (Decimal(1), Decimal(64)),
    SystemLimitKey.DB_CONNECT_TIMEOUT_SECONDS: (Decimal("1.0"), Decimal("300.0")),
    SystemLimitKey.DRIVE_TOKEN_REFRESH_MARGIN_SECONDS: (Decimal(10), Decimal(600)),
    SystemLimitKey.DRIVE_REQUEST_TIMEOUT_SECONDS: (Decimal("5.0"), Decimal("300.0")),
    SystemLimitKey.DRIVE_MAX_RETRIES: (Decimal(1), Decimal(10)),
    SystemLimitKey.DRIVE_OAUTH_FLOW_TIMEOUT_SECONDS: (Decimal("30.0"), Decimal("1800.0")),
    SystemLimitKey.EVIDENCE_JPEG_QUALITY: (Decimal(40), Decimal(100)),
    SystemLimitKey.UPLOAD_CLAIM_STALE_AFTER_SECONDS: (Decimal(60), Decimal(86400)),
    SystemLimitKey.IMAGE_CACHE_TTL_SECONDS: (Decimal(3600), Decimal(31536000)),
    SystemLimitKey.IMAGE_CACHE_MAX_BYTES: (Decimal(16777216), Decimal(8589934592)),
    SystemLimitKey.PLUGIN_SANDBOX_TIMEOUT_SECONDS: (Decimal("1.0"), Decimal("300.0")),
    SystemLimitKey.PLUGIN_SANDBOX_MAX_OUTPUT_BYTES: (Decimal(65536), Decimal(67108864)),
    SystemLimitKey.UPDATE_VERIFY_TIMEOUT_SECONDS: (Decimal("5.0"), Decimal("600.0")),
    SystemLimitKey.UPDATE_UPLOAD_TIMEOUT_SECONDS: (Decimal("30.0"), Decimal("7200.0")),
    SystemLimitKey.UPDATE_DOWNLOAD_TIMEOUT_SECONDS: (Decimal("30.0"), Decimal("7200.0")),
    SystemLimitKey.UPDATE_SIGNED_URL_TTL_SECONDS: (Decimal(60), Decimal(86400)),
    SystemLimitKey.UPDATE_CATALOG_FETCH_LIMIT: (Decimal(1), Decimal(500)),
    # ──────────────────────────────────────────────────────────────────────
    # BURADA OLMAYANLAR: `NTP_MAX_DRIFT_SECONDS`, `PIN_MAX_FAILED_ATTEMPTS`,
    # `PIN_LOCKOUT_MINUTES`.
    #
    # Onlar Faza 10.2-dən ƏVVƏL də ROOT parametri idi və `schema.sql` §24
    # onlara ARTIQ öz hüdudlarını (3–10 / 5–60 / 10–300) verir. Burada ikinci
    # aralıq elan etsəydik, İKİ FƏRQLİ hədd yaranardı: tətbiq qatı
    # (`morning_check_in`, `authentication`) dəyəri KLAMPSIZ oxuyur, yəni
    # infrastruktur onu sıxsaydı, System Health Monitor-un göstərdiyi hədd
    # bloklamanın FAKTİKİ həddindən fərqlənərdi — istifadəçi "ekran normal
    # deyir, amma sistem bloklayır" vəziyyətinə düşərdi.
    #
    # Ona görə bu üç açar üçün infrastruktur da klampsız oxuyur: davranış
    # tətbiq qatı ilə HƏRFƏN eynidir (aralığı olmayan açar toxunulmur).
    # ──────────────────────────────────────────────────────────────────────
}


class LimitReader(Protocol):
    """`system_limits`-in YALNIZ-OXU üzü — infrastrukturun gördüyü hissə.

    NİYƏ TAM `SystemLimits` PORTU DEYİL: həmin port `set_value()` də daşıyır və
    onu bura buraxsaydıq, istənilən infrastruktur modulu limiti YAZA bilərdi —
    audit sətri (`SYSTEM_LIMIT_CHANGED`) isə yalnız `RootControlUseCase`-də
    yazılır, yəni yazı yolu sükutla audit-siz qalardı. Dar protokol bu səhvi
    STRUKTUR olaraq mümkünsüz edir.

    `SystemLimits` tətbiqləri (Postgres repo-su, sahtələr) bu protokolu
    AVTOMATİK ödəyir — structural typing, miras tələb olunmur.
    """

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str: ...


def fallback_int(key: SystemLimitKey) -> int:
    """`DEFAULT_LIMITS`-dən tam ədəd fallback — modul sabitləri üçün.

    Modul sabiti ədədi TƏKRAR YAZMIR, bu funksiya ilə defoltdan götürür:
    əks halda "12" ədədi həm `policies.py`-da, həm modulda yaşayardı və biri
    dəyişəndə digəri sükutla köhnələrdi.
    """
    return int(Decimal(DEFAULT_LIMITS[key]))


def fallback_float(key: SystemLimitKey) -> float:
    """`DEFAULT_LIMITS`-dən onluq fallback."""
    return float(Decimal(DEFAULT_LIMITS[key]))


def fallback_int_tuple(key: SystemLimitKey) -> tuple[int, ...]:
    """`DEFAULT_LIMITS`-dəki vergüllü cədvəldən tam ədəd ardıcıllığı."""
    return _parse_int_list(DEFAULT_LIMITS[key])


def _parse_int_list(raw: str) -> tuple[int, ...]:
    """ "30,120,600" → (30, 120, 600). Yararsız element BURAXILIR, atılmır."""
    values: list[int] = []
    for chunk in raw.split(","):
        text = chunk.strip()
        if not text:
            continue
        try:
            values.append(int(Decimal(text)))
        except (InvalidOperation, ValueError):
            _log.warning("INFRA_LIMIT_LIST_ITEM_INVALID", extra={"raw_item": text})
    return tuple(values)


def _clamp(key: SystemLimitKey, value: Decimal) -> Decimal:
    """Dəyəri açarın SƏRT aralığına sıxır (aralığı olmayan açar toxunulmur)."""
    bounds = INFRA_LIMIT_BOUNDS.get(key)
    if bounds is None:
        return value
    low, high = bounds
    if value < low:
        _log.warning(
            "INFRA_LIMIT_CLAMPED",
            extra={"limit_key": key.value, "raw_value": str(value), "applied": str(low)},
        )
        return low
    if value > high:
        _log.warning(
            "INFRA_LIMIT_CLAMPED",
            extra={"limit_key": key.value, "raw_value": str(value), "applied": str(high)},
        )
        return high
    return value


class InfrastructureLimits:
    """İnfrastruktur modullarının `system_limits`-ə açılan pəncərəsi.

    Portsuz da qurula bilər (`InfrastructureLimits()`) — o halda hər oxu
    `DEFAULT_LIMITS` fallback-ını qaytarır. Bu, testlərin və offline/kiosk
    yollarının bağlantı olmadan işləməsi üçündür: konfiqurasiya oxumaq
    MƏCBURİ ola bilməz, çünki dəyər lazım olan anda baza əlçatmaz ola bilər
    (bax `composition._upload_limit` eyni əsaslandırma ilə).

    Obyekt VƏZİYYƏT SAXLAMIR (keş yoxdur): Root sürüşdürücünü tərpədən kimi
    növbəti çağırış yeni dəyəri görməlidir. Keş "niyə dəyişiklik tətbiq
    olunmur?" sualını doğurardı və onun cavabı yalnız prosesin yenidən
    başladılması olardı.
    """

    __slots__ = ("_limits", "_tenant_id")

    def __init__(
        self,
        *,
        limits: LimitReader | None = None,
        tenant_id: TenantId | None = None,
    ) -> None:
        # İkisindən biri yoxdursa oxu MÜMKÜN DEYİL: `system_limits` sətri
        # tenant-a bağlıdır və RLS kontekstsiz sorğu boş qaytarardı.
        self._limits = limits
        self._tenant_id = tenant_id

    @property
    def is_live(self) -> bool:
        """ROOT dəyərləri oxuna bilirmi (diaqnostika və test üçün)."""
        return self._limits is not None and self._tenant_id is not None

    def int_of(self, key: SystemLimitKey) -> int:
        """Tam ədəd limit — klamp edilmiş."""
        return int(_clamp(key, self._decimal(key)))

    def float_of(self, key: SystemLimitKey) -> float:
        """Onluq limit — klamp edilmiş."""
        return float(_clamp(key, self._decimal(key)))

    def int_tuple_of(self, key: SystemLimitKey) -> tuple[int, ...]:
        """Vergüllü cədvəl — hər elementi ayrıca klamp edilmiş.

        BOŞ NƏTİCƏ QAYTARILMIR: Root sətri təsadüfən boşaldarsa gözləmə
        cədvəli yox olardı və təkrar cəhd dövrü fasiləsiz fırlanardı (SMTP
        provayderi göndərəni bloklayardı). Belə halda defolt cədvəl işə düşür.
        """
        raw = self._raw(key)
        parsed = _parse_int_list(raw)
        if not parsed:
            parsed = fallback_int_tuple(key)
        return tuple(int(_clamp(key, Decimal(item))) for item in parsed)

    def _decimal(self, key: SystemLimitKey) -> Decimal:
        raw = self._raw(key)
        try:
            return Decimal(raw.strip().replace(",", "."))
        except (InvalidOperation, AttributeError):
            _log.warning(
                "INFRA_LIMIT_NOT_A_NUMBER",
                extra={"limit_key": key.value, "raw_value": raw},
            )
            return Decimal(DEFAULT_LIMITS[key])

    def _raw(self, key: SystemLimitKey) -> str:
        fallback = DEFAULT_LIMITS[key]
        if self._limits is None or self._tenant_id is None:
            return fallback
        try:
            return self._limits.get_str(self._tenant_id, key.value, fallback)
        except Exception as exc:
            # Oxu uğursuzluğu ƏMƏLİYYATI DAYANDIRMIR: verilməli cavab "işləsinmi"
            # deyil, "hansı hədlə" idi. Cavabsız qaldıqda fallback işləyir.
            _log.warning(
                "INFRA_LIMIT_READ_FAILED",
                extra={"limit_key": key.value, "error": str(exc), "fallback": fallback},
            )
            return fallback


__all__ = [
    "INFRA_LIMIT_BOUNDS",
    "InfrastructureLimits",
    "LimitReader",
    "fallback_float",
    "fallback_int",
    "fallback_int_tuple",
]
