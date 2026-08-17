"""İnfrastruktur ROOT parametrlərinin qapısı (Faza 10.2).

──────────────────────────────────────────────────────────────────────────────
BU FAYL NƏYİ QORUYUR
──────────────────────────────────────────────────────────────────────────────
Faza 10.2 `src/infrastructure/` qatındakı 51 əməliyyat sabitini ROOT İdarə
Mərkəzinə köçürdü. Köçürmə DAVRANIŞ DƏYİŞİKLİYİ DEYİL — hər defolt köhnə
hardcode dəyərlə hərfən eyni olmalıdır. Bu fayl həmin bərabərliyi kod kimi
yazır: kimsə defoltu "yaxşılaşdırsa" (məs. taymautu 30-dan 60-a qaldırsa),
test dərhal qırılır və dəyişikliyin şüurlu qərar olduğunu tələb edir.

Üç ayrı qapı var:

  1. DEFOLT = KÖHNƏ HARDCODE — köçürmə davranışı dəyişmədi.
  2. ARALIQ PARİTETİ — `INFRA_LIMIT_BOUNDS` ilə seed miqrasiyalarındakı
     (`_MIGRATIONS`) `min_value`/`max_value` eyni olmalıdır. Ayrılsalar, ROOT
     ekranı "qəbul edilən" göstərən dəyəri kod sükutla kəsərdi.
  3. CANLI OXU — Root dəyəri dəyişdikdə kod YENİ dəyəri oxumalıdır (köhnəni
     keşləməməlidir), səhv dəyər isə tətbiqi işləməz vəziyyətə salmamalıdır.

`tests/unit/test_root_control_parameter_parity.py` ayrıca hər açarın həm
`DEFAULT_LIMITS`-də, həm də SQL seed-ində olmasını yoxlayır — burada onu
təkrarlamırıq.
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.identifiers import TenantId
from src.infrastructure.config.limits import (
    INFRA_LIMIT_BOUNDS,
    InfrastructureLimits,
    fallback_float,
    fallback_int,
    fallback_int_tuple,
)
from tests.fixtures.fakes import FakeSystemLimits

TENANT: Final = TenantId(uuid.UUID("11111111-1111-1111-1111-111111111111"))

_MIGRATIONS_DIR: Final[Path] = Path(__file__).resolve().parents[2] / "database" / "migrations"

#: İnfrastruktur limitlərini seed edən BÜTÜN miqrasiyalar.
#:
#: Əvvəl burada TƏK fayl (032) vardı və qapı «açar 032-dədir?» soruşurdu. Bu,
#: 032 yazılan gün doğru idi, lakin qaydanı faylın adına bağlamışdı: sonrakı
#: miqrasiya ilə gələn hər yeni infrastruktur açarı qapını POZURDU — halbuki
#: onun qüsuru yox idi, sadəcə başqa faylda yaşayırdı. Nəticədə qapı ya
#: yumşaldılmalı, ya da hər yeni açar 032-yə geri yazılmalı olardı; ikincisi
#: tətbiq olunmuş miqrasiyanı sonradan redaktə etmək deməkdir və `schema_
#: migrations` checksum-u ilə birbaşa ziddiyyətdədir (migrations/061).
#:
#: Ona görə siyahı FAYL DEYİL, DƏSTdir. Yeni infrastruktur açarı gətirən
#: miqrasiya buraya bir sətir əlavə edir.
_MIGRATIONS: Final[tuple[Path, ...]] = (
    _MIGRATIONS_DIR / "032_infrastructure_runtime_limits.sql",
    _MIGRATIONS_DIR / "062_server_time_integrity.sql",
)

#: Açar → Faza 10.2-dən ƏVVƏL kodda oturan HƏRFİ dəyər.
#:
#: Siyahı əl ilə yazılıb və məhz bu, onun dəyəridir: dəyərləri
#: `DEFAULT_LIMITS`-dən oxusaydıq test öz-özünü təsdiqləyər və heç nə
#: qorumazdı. Burada yazılan ədədlər auditin tapdığı sətirlərdən götürülüb.
_ORIGINAL_HARDCODES: Final[dict[SystemLimitKey, str]] = {
    SystemLimitKey.PASSWORD_MIN_LENGTH: "12",
    SystemLimitKey.BACKUP_MIN_RETENTION_DAYS: "30",
    SystemLimitKey.BACKUP_RETENTION_DAYS: "30",
    SystemLimitKey.BACKUP_DUMP_TIMEOUT_SECONDS: "3600",
    SystemLimitKey.HEALTH_DISK_WARNING_PERCENT: "85.0",
    SystemLimitKey.HEALTH_DISK_CRITICAL_PERCENT: "95.0",
    SystemLimitKey.HEALTH_DB_PING_SLOW_MS: "500",
    SystemLimitKey.DRIVE_QUOTA_WARNING_RATIO: "0.90",
    SystemLimitKey.DRIVE_QUOTA_WARNING_COOLDOWN_DAYS: "7",
    SystemLimitKey.NTP_POLL_INTERVAL_SECONDS: "300",
    SystemLimitKey.NTP_QUERY_TIMEOUT_SECONDS: "3.0",
    SystemLimitKey.NTP_SAMPLE_TTL_SECONDS: "1800",
    SystemLimitKey.NTP_MAX_ROUND_TRIP_SECONDS: "2.0",
    SystemLimitKey.ERP_MATCH_AMBIGUITY_MARGIN: "0.05",
    SystemLimitKey.ERP_SYNC_MAX_PARALLEL_SERVERS: "4",
    SystemLimitKey.ERP_SYNC_MAX_PAGES_PER_RUN: "10",
    SystemLimitKey.ERP_REQUEST_TIMEOUT_SECONDS: "30.0",
    SystemLimitKey.ERP_MAX_RETRIES: "3",
    SystemLimitKey.KIOSK_RESTART_WINDOW_MINUTES: "10",
    SystemLimitKey.KIOSK_MAX_RESTARTS_PER_WINDOW: "5",
    SystemLimitKey.KIOSK_RESTART_BACKOFF_SECONDS: "2,4,8,16,30",
    SystemLimitKey.DEVELOPER_DIRECTORY_STALE_DAYS: "3",
    SystemLimitKey.NOTIFY_MAX_BATCH_SIZE: "25",
    SystemLimitKey.NOTIFY_MAX_ATTEMPTS: "5",
    SystemLimitKey.NOTIFY_RETRY_BACKOFF_MINUTES: "1,5,15,60,240",
    SystemLimitKey.NOTIFY_POLL_INTERVAL_SECONDS: "120",
    SystemLimitKey.EMAIL_SMTP_TIMEOUT_SECONDS: "15.0",
    SystemLimitKey.CRASH_MAX_REPORTS_PER_FINGERPRINT: "3",
    SystemLimitKey.REALTIME_POLL_INTERVAL_SECONDS: "30",
    SystemLimitKey.REALTIME_RECONNECT_BACKOFF_SECONDS: "5,15,30,60",
    SystemLimitKey.OFFLINE_SYNC_BATCH_SIZE: "100",
    SystemLimitKey.OFFLINE_RETRY_BACKOFF_SECONDS: "30,120,600",
    SystemLimitKey.OFFLINE_SQLITE_TIMEOUT_SECONDS: "10.0",
    SystemLimitKey.DB_POOL_MIN_SIZE: "1",
    SystemLimitKey.DB_POOL_MAX_SIZE: "8",
    SystemLimitKey.DB_CONNECT_TIMEOUT_SECONDS: "15.0",
    SystemLimitKey.DRIVE_TOKEN_REFRESH_MARGIN_SECONDS: "60",
    SystemLimitKey.DRIVE_REQUEST_TIMEOUT_SECONDS: "30.0",
    SystemLimitKey.DRIVE_MAX_RETRIES: "3",
    SystemLimitKey.DRIVE_OAUTH_FLOW_TIMEOUT_SECONDS: "300.0",
    SystemLimitKey.EVIDENCE_JPEG_QUALITY: "85",
    SystemLimitKey.UPLOAD_CLAIM_STALE_AFTER_SECONDS: "600",
    SystemLimitKey.IMAGE_CACHE_TTL_SECONDS: "2592000",
    SystemLimitKey.IMAGE_CACHE_MAX_BYTES: "268435456",
    SystemLimitKey.PLUGIN_SANDBOX_TIMEOUT_SECONDS: "10.0",
    SystemLimitKey.PLUGIN_SANDBOX_MAX_OUTPUT_BYTES: "1048576",
    SystemLimitKey.UPDATE_VERIFY_TIMEOUT_SECONDS: "60.0",
    SystemLimitKey.UPDATE_UPLOAD_TIMEOUT_SECONDS: "600.0",
    SystemLimitKey.UPDATE_DOWNLOAD_TIMEOUT_SECONDS: "300.0",
    SystemLimitKey.UPDATE_SIGNED_URL_TTL_SECONDS: "3600",
    SystemLimitKey.UPDATE_CATALOG_FETCH_LIMIT: "20",
    # ----------------------------------------------------------------------- #
    # TIME-1 (migrations/062) — BUNLAR HEÇ VAXT HARDCODE OLMAYIB
    # ----------------------------------------------------------------------- #
    # Yuxarıdakı açarlar Faza 10.2 auditinin KÖÇÜRDÜYÜ sabitlərdir və dəyər
    # sütunu «əvvəl kodda nə yazılırdı» sualına cavab verir. Aşağıdakı dördü
    # isə YENİ funksiya ilə birlikdə doğulub — köçürüləcək köhnə sabit yox idi.
    #
    # Onlar yenə də bu siyahıya yazılır, çünki qapının İKİNCİ vəzifəsi
    # köçürmə tarixçəsi deyil, ƏHATƏdir: `INFRA_LIMIT_BOUNDS`-da aralığı olan
    # hər açar burada da görünməlidir (bax `test_every_infrastructure_key_...`).
    # Dəyər sütunu onlar üçün «modulun fallback sabiti» mənasını daşıyır —
    # `server_time.py`-dakı `FALLBACK_*` ilə eyni ədəd.
    SystemLimitKey.SERVER_TIME_SYNC_INTERVAL_SECONDS: "300",
    SystemLimitKey.SERVER_TIME_MAX_OFFLINE_TRUST_SECONDS: "14400",
    SystemLimitKey.LOCAL_CLOCK_MANIPULATION_THRESHOLD_SECONDS: "60",
    SystemLimitKey.LOCAL_CLOCK_MANIPULATION_NOTIFY: "1",
}


# --------------------------------------------------------------------------- #
# 1. Defolt = köhnə hardcode
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("key", sorted(_ORIGINAL_HARDCODES, key=lambda item: item.value))
def test_default_equals_the_value_that_was_hardcoded(key: SystemLimitKey) -> None:
    """Köçürmə idarəolunma dəyişikliyidir, davranış dəyişikliyi DEYİL."""
    assert DEFAULT_LIMITS[key] == _ORIGINAL_HARDCODES[key], (
        f"`{key.value}` defoltu köhnə hardcode dəyərdən fərqlidir — "
        "köçürmə davranışı dəyişdirmiş olur."
    )


def test_every_infrastructure_key_is_covered_by_this_gate() -> None:
    """`INFRA_LIMIT_BOUNDS` ilə bu qapı BİRE-BİR üst-üstə düşməlidir.

    İki istiqamət də qorunur:
      * Aralığı olub "köhnə dəyəri nə idi?" sualı cavabsız qalan açar qapını
        sükutla yan keçərdi;
      * Köçürülüb aralığı YAZILMAYAN açar isə klampsız qalardı — Root səhv
        dəyər yazanda tətbiq işləməz vəziyyətə düşərdi.
    """
    bounded = set(INFRA_LIMIT_BOUNDS)
    documented = set(_ORIGINAL_HARDCODES)
    assert bounded == documented, (
        "`INFRA_LIMIT_BOUNDS` ilə `_ORIGINAL_HARDCODES` fərqlənir: "
        f"yalnız aralıqda {sorted(k.value for k in bounded - documented)}, "
        f"yalnız qapıda {sorted(k.value for k in documented - bounded)}"
    )


def test_pre_existing_root_keys_are_not_clamped_by_infrastructure() -> None:
    """Faza 10.2-dən ƏVVƏL də ROOT parametri olan üç açar klampsız qalır.

    `schema.sql` §24 onlara artıq öz hüdudlarını verir və tətbiq qatı
    (`morning_check_in`, `authentication`) dəyəri KLAMPSIZ oxuyur. İnfrastruktur
    onları sıxsaydı, System Health Monitor-un göstərdiyi hədd bloklamanın
    faktiki həddindən fərqlənərdi.
    """
    for key in (
        SystemLimitKey.NTP_MAX_DRIFT_SECONDS,
        SystemLimitKey.PIN_MAX_FAILED_ATTEMPTS,
        SystemLimitKey.PIN_LOCKOUT_MINUTES,
    ):
        assert key not in INFRA_LIMIT_BOUNDS

    source = FakeSystemLimits()
    limits = InfrastructureLimits(limits=source, tenant_id=TENANT)
    source.set(SystemLimitKey.NTP_MAX_DRIFT_SECONDS, "900")
    assert limits.int_of(SystemLimitKey.NTP_MAX_DRIFT_SECONDS) == 900


def test_defaults_are_inside_their_own_bounds() -> None:
    """Defolt öz aralığından kənarda olsaydı, klamp onu DƏRHAL dəyişdirərdi.

    Yəni "defolt = köhnə hardcode" zəmanəti sükutla pozulardı: kod fallback
    kimi bir dəyər elan edər, işlədəndə isə başqasını görərdi.
    """
    for key, (low, high) in INFRA_LIMIT_BOUNDS.items():
        raw = DEFAULT_LIMITS[key]
        values = [Decimal(chunk.strip()) for chunk in raw.split(",") if chunk.strip()]
        for value in values:
            assert low <= value <= high, (
                f"`{key.value}` defoltu ({value}) [{low}; {high}] aralığından kənardadır"
            )


# --------------------------------------------------------------------------- #
# 2. Aralıq pariteti — kod ↔ miqrasiya
# --------------------------------------------------------------------------- #


def _seeding_body(path: Path) -> str:
    """Miqrasiyanın şərhsiz gövdəsi — DOWN blokunda yalnız açar adları var."""
    text = path.read_text(encoding="utf-8")
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))


def _migration_bounds() -> dict[str, tuple[Decimal, Decimal]]:
    """`_MIGRATIONS`-dəki `(limit_key, min_value, max_value)` üçlükləri.

    SQL parse edilmir — `VALUES` sətirləri sabit formatdadır və regex kifayət
    edir. Hər faylın İKİ bölməsində eyni siyahı var (mövcud kirayəçilər + yeni
    kirayəçi trigger-i); ikisi arasındakı fərq də aşağıda ayrıca yoxlanılır.
    """
    pattern = re.compile(
        r"\('(?P<key>[A-Z0-9_]+)',\s*'[^']*',\s*'(?:INTEGER|DECIMAL|TEXT)',\s*"
        r"'(?P<min>[0-9.]+)',\s*'(?P<max>[0-9.]+)'"
    )
    found: dict[str, tuple[Decimal, Decimal]] = {}
    for path in _MIGRATIONS:
        for match in pattern.finditer(_seeding_body(path)):
            key = match.group("key")
            bounds = (Decimal(match.group("min")), Decimal(match.group("max")))
            # Eyni açarın İKİ miqrasiyada fərqli hüdudla görünməsi sükutlu
            # qüsurdur: hansının qüvvədə olduğu tətbiq SIRASINDAN asılı olardı.
            assert found.get(key, bounds) == bounds, (
                f"`{key}` iki miqrasiyada fərqli hüdudlarla seed edilir: {found[key]} ≠ {bounds}"
            )
            found[key] = bounds
    return found


def test_code_bounds_match_the_migration() -> None:
    """Kod klampı ilə SQL-dəki hüdudlar AYRILA BİLMƏZ.

    Ayrılsalar, ROOT ekranı Root-un yazdığı dəyəri qəbul edər, kod isə onu
    sükutla kəsərdi — istifadəçi "niyə tətbiq olunmur?" sualına cavab tapmazdı.
    """
    sql_bounds = _migration_bounds()
    names = ", ".join(path.name for path in _MIGRATIONS)
    for key in _ORIGINAL_HARDCODES:
        assert key.value in sql_bounds, (
            f"`{key.value}` heç bir miqrasiyada ({names}) seed edilməyib"
        )
        assert sql_bounds[key.value] == INFRA_LIMIT_BOUNDS[key], (
            f"`{key.value}`: SQL {sql_bounds[key.value]} ≠ kod {INFRA_LIMIT_BOUNDS[key]}"
        )


def test_migration_seeds_both_existing_and_new_tenants_identically() -> None:
    """Hər açar HƏM mövcud kirayəçi INSERT-ində, HƏM trigger funksiyasında.

    Birində unudulsa, yeni kirayəçi parametrsiz qalar (və ya əksinə) — bu,
    yalnız aylar sonra "niyə bu mağazada ekran boşdur?" şəklində üzə çıxardı.
    """
    bodies = {path.name: _seeding_body(path) for path in _MIGRATIONS}
    for key in _ORIGINAL_HARDCODES:
        counts = {name: body.count(f"('{key.value}',") for name, body in bodies.items()}
        total = sum(counts.values())
        assert total == 2, (
            f"`{key.value}` miqrasiyalarda {total} dəfə görünür ({counts}) — "
            "hər açar həm mövcud, həm yeni kirayəçi bloklarında olmalıdır."
        )
        # Hər iki görünüş EYNİ faylda olmalıdır: açarı bir miqrasiyada mövcud
        # kirayəçilərə, digərində trigger-ə yazmaq həmin iki miqrasiya arasında
        # yaranan quraşdırmanı parametrsiz qoyardı.
        assert 2 in counts.values(), (
            f"`{key.value}` iki miqrasiyaya BÖLÜNÜB ({counts}) — "
            "mövcud kirayəçi INSERT-i və trigger bloku eyni faylda olmalıdır."
        )


# --------------------------------------------------------------------------- #
# 3. Canlı oxu və klamp
# --------------------------------------------------------------------------- #


def test_without_a_port_the_fallback_is_returned() -> None:
    """Portsuz qurulan pəncərə `DEFAULT_LIMITS`-i qaytarır (kiosk/offline yolu)."""
    limits = InfrastructureLimits()

    assert limits.is_live is False
    assert limits.int_of(SystemLimitKey.DB_POOL_MAX_SIZE) == 8
    assert limits.float_of(SystemLimitKey.ERP_REQUEST_TIMEOUT_SECONDS) == 30.0
    assert limits.int_tuple_of(SystemLimitKey.OFFLINE_RETRY_BACKOFF_SECONDS) == (30, 120, 600)


def test_root_value_is_read_at_call_time() -> None:
    """Root dəyəri dəyişdirdikdə NÖVBƏTİ oxu artıq yeni dəyəri görür."""
    source = FakeSystemLimits()
    limits = InfrastructureLimits(limits=source, tenant_id=TENANT)

    assert limits.int_of(SystemLimitKey.NOTIFY_MAX_BATCH_SIZE) == 25
    source.set(SystemLimitKey.NOTIFY_MAX_BATCH_SIZE, "40")
    assert limits.int_of(SystemLimitKey.NOTIFY_MAX_BATCH_SIZE) == 40, (
        "Dəyər keşlənib — Root dəyişikliyi yalnız yenidən başlatmadan sonra qüvvəyə minərdi."
    )


def test_out_of_range_root_value_is_clamped_not_obeyed() -> None:
    """Səhv konfiqurasiya tətbiqi işləməz vəziyyətə salmamalıdır."""
    source = FakeSystemLimits()
    limits = InfrastructureLimits(limits=source, tenant_id=TENANT)

    source.set(SystemLimitKey.DB_POOL_MAX_SIZE, "0")
    assert limits.int_of(SystemLimitKey.DB_POOL_MAX_SIZE) == 1

    source.set(SystemLimitKey.DB_POOL_MAX_SIZE, "100000")
    assert limits.int_of(SystemLimitKey.DB_POOL_MAX_SIZE) == 64

    source.set(SystemLimitKey.NTP_QUERY_TIMEOUT_SECONDS, "0")
    assert limits.float_of(SystemLimitKey.NTP_QUERY_TIMEOUT_SECONDS) == 1.0


def test_backup_retention_floor_cannot_be_lowered_below_the_specification() -> None:
    """Spesifikasiyanın "minimum 30 gün" tələbi Root-dan pozula bilməz."""
    source = FakeSystemLimits()
    limits = InfrastructureLimits(limits=source, tenant_id=TENANT)

    source.set(SystemLimitKey.BACKUP_MIN_RETENTION_DAYS, "1")
    source.set(SystemLimitKey.BACKUP_RETENTION_DAYS, "1")

    assert limits.int_of(SystemLimitKey.BACKUP_MIN_RETENTION_DAYS) == 30
    assert limits.int_of(SystemLimitKey.BACKUP_RETENTION_DAYS) == 30


def test_garbage_value_falls_back_instead_of_raising() -> None:
    """Rəqəm olmayan dəyər istisna ATMIR — əməliyyat dayanmamalıdır."""
    source = FakeSystemLimits()
    limits = InfrastructureLimits(limits=source, tenant_id=TENANT)

    source.set(SystemLimitKey.EVIDENCE_JPEG_QUALITY, "yüksək")
    assert limits.int_of(SystemLimitKey.EVIDENCE_JPEG_QUALITY) == 85


def test_empty_list_value_falls_back_to_the_default_schedule() -> None:
    """Boş cədvəl təkrar cəhd dövrünü fasiləsiz fırladardı."""
    source = FakeSystemLimits()
    limits = InfrastructureLimits(limits=source, tenant_id=TENANT)

    source.set(SystemLimitKey.NOTIFY_RETRY_BACKOFF_MINUTES, "   ")
    assert limits.int_tuple_of(SystemLimitKey.NOTIFY_RETRY_BACKOFF_MINUTES) == (1, 5, 15, 60, 240)


def test_list_items_are_clamped_individually() -> None:
    """Hüdud CƏDVƏLƏ deyil, HƏR ADDIMA aiddir (bax migrations/032 şərhi)."""
    source = FakeSystemLimits()
    limits = InfrastructureLimits(limits=source, tenant_id=TENANT)

    source.set(SystemLimitKey.KIOSK_RESTART_BACKOFF_SECONDS, "0,4,99999")
    assert limits.int_tuple_of(SystemLimitKey.KIOSK_RESTART_BACKOFF_SECONDS) == (1, 4, 3600)


def test_a_failing_port_does_not_break_the_caller() -> None:
    """Baza əlçatmaz olanda limit oxusu ƏMƏLİYYATI DAYANDIRMIR."""

    class BrokenLimits:
        def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
            raise RuntimeError("bağlantı yoxdur")

    limits = InfrastructureLimits(limits=BrokenLimits(), tenant_id=TENANT)  # type: ignore[arg-type]
    assert limits.int_of(SystemLimitKey.NOTIFY_MAX_ATTEMPTS) == 5


# --------------------------------------------------------------------------- #
# 4. Fallback köməkçiləri modul sabitlərini `DEFAULT_LIMITS`-ə bağlayır
# --------------------------------------------------------------------------- #


def test_module_fallbacks_read_from_default_limits() -> None:
    """Modul sabitləri ədədi TƏKRAR YAZMIR — tək mənbə `DEFAULT_LIMITS`-dir."""
    from src.infrastructure.backup.service import FALLBACK_MIN_RETENTION_DAYS
    from src.infrastructure.kiosk.watchdog import FALLBACK_RESTART_BACKOFF_SECONDS
    from src.infrastructure.persistence.connection import (
        FALLBACK_POOL_MAX,
        FALLBACK_POOL_MIN,
        FALLBACK_TIMEOUT_SECONDS,
    )
    from src.infrastructure.security.hashing import FALLBACK_MIN_PASSWORD_LENGTH

    assert fallback_int(SystemLimitKey.PASSWORD_MIN_LENGTH) == FALLBACK_MIN_PASSWORD_LENGTH == 12
    assert fallback_int(SystemLimitKey.BACKUP_MIN_RETENTION_DAYS) == FALLBACK_MIN_RETENTION_DAYS
    assert fallback_int(SystemLimitKey.DB_POOL_MIN_SIZE) == FALLBACK_POOL_MIN == 1
    assert fallback_int(SystemLimitKey.DB_POOL_MAX_SIZE) == FALLBACK_POOL_MAX == 8
    assert fallback_float(SystemLimitKey.DB_CONNECT_TIMEOUT_SECONDS) == FALLBACK_TIMEOUT_SECONDS
    assert (
        fallback_int_tuple(SystemLimitKey.KIOSK_RESTART_BACKOFF_SECONDS)
        == FALLBACK_RESTART_BACKOFF_SECONDS
        == (2, 4, 8, 16, 30)
    )


# --------------------------------------------------------------------------- #
# 5. Modullar dəyəri həqiqətən ÇAĞIRIŞ ANINDA oxuyurmu
# --------------------------------------------------------------------------- #
#
# Yuxarıdakı testlər pəncərənin ÖZÜNÜ yoxlayır; buradakılar isə hər modulun
# ona həqiqətən bağlandığını. Fərq mühümdür: pəncərə düzgün işləyə, modul isə
# dəyəri konstruktorda dondurub sükutla köhnə davranışı saxlaya bilər.


def test_watchdog_reads_the_backoff_schedule_from_root() -> None:
    from src.infrastructure.kiosk.watchdog import KioskWatchdog

    source = FakeSystemLimits()
    watchdog = KioskWatchdog(
        command=["dummy"],
        limits=InfrastructureLimits(limits=source, tenant_id=TENANT),
    )

    assert watchdog._backoff_for(0) == 2
    source.set(SystemLimitKey.KIOSK_RESTART_BACKOFF_SECONDS, "7,9")
    assert watchdog._backoff_for(0) == 7
    assert watchdog._max_restarts_value() == 5
    source.set(SystemLimitKey.KIOSK_MAX_RESTARTS_PER_WINDOW, "9")
    assert watchdog._max_restarts_value() == 9


def test_disk_metric_reads_thresholds_from_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Eyni disk mənzərəsi Root həddinə görə fərqli SƏVİYYƏ verməlidir.

    Real diskin doluluğu maşından-maşına dəyişir, ona görə `disk_usage`
    əvəzlənir: test hədləri yoxlayır, işlədiyi kompüteri yox.
    """
    import shutil
    from types import SimpleNamespace

    from src.infrastructure.erp.system_health import HealthLevel, disk_metric

    # 90% dolu: 85/95 defoltunda XƏBƏRDARLIQ, 99/100-də isə NORMAL.
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=100, used=90, free=10),
    )

    source = FakeSystemLimits()
    window = InfrastructureLimits(limits=source, tenant_id=TENANT)

    assert disk_metric(tmp_path, limits=window).level is HealthLevel.WARNING

    source.set(SystemLimitKey.HEALTH_DISK_WARNING_PERCENT, "99")
    source.set(SystemLimitKey.HEALTH_DISK_CRITICAL_PERCENT, "100")
    assert disk_metric(tmp_path, limits=window).level is HealthLevel.OK

    source.set(SystemLimitKey.HEALTH_DISK_WARNING_PERCENT, "50")
    source.set(SystemLimitKey.HEALTH_DISK_CRITICAL_PERCENT, "55")
    assert disk_metric(tmp_path, limits=window).level is HealthLevel.CRITICAL


def test_pool_settings_are_clamped_and_kept_consistent() -> None:
    """`min > max` cütü `psycopg_pool`-da istisna atardı — tətbiq açılmazdı."""
    from src.infrastructure.persistence.connection import _clamped_pool_settings

    assert _clamped_pool_settings(1, 8, 15.0) == (1, 8, 15.0)
    assert _clamped_pool_settings(0, 0, 0.0) == (1, 1, 1.0)
    assert _clamped_pool_settings(32, 4, 15.0) == (32, 32, 15.0)
    assert _clamped_pool_settings(999, 999, 99999.0) == (32, 64, 300.0)


def test_password_policy_length_comes_from_root() -> None:
    from src.infrastructure.security.hashing import HashingService, WeakSecretError

    source = FakeSystemLimits()
    service = HashingService(
        limits=InfrastructureLimits(limits=source, tenant_id=TENANT),
        time_cost=1,
        memory_cost=8,
        parallelism=1,
    )

    # 12 simvolluq şifrə DEFOLTDA keçir...
    service.hash_password("Güclü-Şifr1!")
    # ...Root həddi qaldıranda EYNİ şifrə rədd edilir.
    source.set(SystemLimitKey.PASSWORD_MIN_LENGTH, "24")
    with pytest.raises(WeakSecretError):
        service.hash_password("Güclü-Şifr1!")
