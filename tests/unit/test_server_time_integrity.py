"""Server-lövbərli vaxt qapısı (TIME-1).

──────────────────────────────────────────────────────────────────────────────
NƏYİ QORUYUR
──────────────────────────────────────────────────────────────────────────────
Bu modulun qüsurları SÜKUTLUdur: saat yenə də ədəd qaytarır, ekran yenə də
işləyir, test dəsti yenə də yaşıl olur — sadəcə qeydlərin vaxtı manipulyasiya
oluna bilən mənbədən gəlir. Fərq YALNIZ sistem saatı dəyişdirildikdə üzə çıxır,
yəni məhz istehsalatda və məhz fırıldaqçılıq anında.

Ona görə burada dörd şey ölçülür:

    1. Sistem saatının dəyişməsi `now()`-a TƏSİR ETMİR (lövbər varkən);
    2. Lövbər köhnəldikcə etibarlılıq səviyyəsi PİLLƏ-PİLLƏ enir;
    3. Sinxronizasiya uğursuzluğu mövcud lövbəri SİLMİR;
    4. Lokal saat sürüşməsi bildirişi bir DƏFƏ göndərilir, hər dövrədə yox.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.identifiers import TenantId
from src.domain.value_objects.time_integrity import (
    NO_ANCHOR_STATUS,
    TimeIntegrityStatus,
    TimeTrustLevel,
)
from src.infrastructure.config.limits import InfrastructureLimits
from src.infrastructure.timekeeping.server_time import (
    FRESHNESS_INTERVAL_MULTIPLIER,
    ServerTimeService,
)
from tests.fixtures.fakes import FakeSystemLimits

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.UUID("22222222-2222-2222-2222-222222222222"))
SERVER_EPOCH: Final = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)

SYNC_INTERVAL: Final = 300.0
OFFLINE_TRUST: Final = 14400.0
MANIPULATION_THRESHOLD: Final = 60.0


class _FakeProbe:
    """Server vaxtını təqlid edir; nasazlıq və sürüşmə idarə oluna bilir."""

    def __init__(self, *, moment: datetime = SERVER_EPOCH) -> None:
        self.moment = moment
        self.fail = False
        self.calls = 0

    def read_server_time(self) -> datetime:
        self.calls += 1
        if self.fail:
            raise ConnectionError("server əlçatmazdır")
        return self.moment


class _FakeClock:
    """Fallback saat — lövbər yoxdursa istifadə olunur."""

    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def now(self) -> datetime:
        return self.moment


class _Timeline:
    """İdarə olunan `time.monotonic()` və divar saatı.

    İkisi AYRI-AYRI sürüşdürülə bilir və testin bütün mənası budur: sistem
    saatını irəli çəkmək monotonic saata TOXUNMUR.
    """

    def __init__(self, *, wall: datetime) -> None:
        self.monotonic = 1000.0
        self.wall = wall

    def advance(self, seconds: float) -> None:
        """Həqiqi vaxt axını — hər iki saat birlikdə irəliləyir."""
        self.monotonic += seconds
        self.wall += timedelta(seconds=seconds)

    def tamper_wall_clock(self, seconds: float) -> None:
        """İSTİFADƏÇİ Windows saatını dəyişdi — monotonic TOXUNULMUR."""
        self.wall += timedelta(seconds=seconds)


def _build(
    *,
    probe: _FakeProbe | None = None,
    timeline: _Timeline | None = None,
    on_manipulation: object = None,
) -> tuple[ServerTimeService, _FakeProbe, _Timeline]:
    real_probe = probe or _FakeProbe()
    line = timeline or _Timeline(wall=SERVER_EPOCH)
    service = ServerTimeService(
        probe=real_probe,
        fallback_clock=_FakeClock(line.wall),
        sync_interval_seconds=SYNC_INTERVAL,
        max_offline_trust_seconds=OFFLINE_TRUST,
        manipulation_threshold_seconds=MANIPULATION_THRESHOLD,
        machine_name="TEST-PC",
        on_manipulation=on_manipulation,  # type: ignore[arg-type]
        monotonic=lambda: line.monotonic,
        local_now=lambda: line.wall,
    )
    return service, real_probe, line


# --------------------------------------------------------------------------- #
# 1. Sistem saatının dəyişməsi vaxta təsir etmir
# --------------------------------------------------------------------------- #


def test_changing_the_windows_clock_does_not_move_the_reported_time() -> None:
    """TIME-1-in ƏSAS vədi: saatı iki saat irəli çək → vaxt DƏYİŞMİR."""
    service, _, line = _build()
    service.sync()
    before = service.now()

    line.tamper_wall_clock(2 * 3600)

    assert service.now() == before, (
        "Windows saatının dəyişməsi qeyd olunan vaxtı sürüşdürdü — "
        "lövbər monotonic saatla uzadılmır."
    )


def test_time_advances_with_real_elapsed_time() -> None:
    """Saat DONMUR: həqiqi axan müddət qədər irəliləyir."""
    service, _, line = _build()
    service.sync()
    before = service.now()

    line.advance(90)

    assert service.now() - before == timedelta(seconds=90)


def test_backwards_clock_change_is_also_ignored() -> None:
    """Saatı GERİ çəkmək də təsir etmir — gecikməni silmək cəhdi."""
    service, _, line = _build()
    service.sync()
    before = service.now()

    line.tamper_wall_clock(-45 * 60)

    assert service.now() == before


# --------------------------------------------------------------------------- #
# 2. Etibarlılıq səviyyəsi
# --------------------------------------------------------------------------- #


def test_without_an_anchor_the_status_is_untrusted() -> None:
    """Lövbərsiz vaxt sadəcə Windows saatıdır — `MONOTONIC_ESTIMATE` DEYİL.

    Fərq mühümdür: `MONOTONIC_ESTIMATE` «bir dəfə serverdən oxuduq, indi
    uzadırıq» deməkdir. Heç oxumamışıqsa dəqiqlik barədə HEÇ NƏ bilmirik.
    """
    service, _, _ = _build()
    assert service.status() == NO_ANCHOR_STATUS
    assert service.status().level is TimeTrustLevel.UNTRUSTED


def test_without_an_anchor_now_falls_back_to_the_injected_clock() -> None:
    """Vaxtsız qalmaq variant deyil — fallback saat işləyir."""
    service, _, line = _build()
    assert service.now() == line.wall


def test_a_fresh_anchor_is_server_verified() -> None:
    service, _, _ = _build()
    service.sync()
    assert service.status().level is TimeTrustLevel.SERVER_VERIFIED


def test_the_level_degrades_step_by_step_as_the_anchor_ages() -> None:
    """Üç səviyyə ARDICIL keçilir — «onlayn/oflayn» ikili bölgüsü deyil."""
    service, probe, line = _build()
    service.sync()
    probe.fail = True

    # Təzəlik pəncərəsinin İÇİ.
    line.advance(SYNC_INTERVAL * FRESHNESS_INTERVAL_MULTIPLIER - 1)
    assert service.status().level is TimeTrustLevel.SERVER_VERIFIED

    # Pəncərədən KƏNAR, lakin Root həddi daxilində.
    line.advance(2)
    assert service.status().level is TimeTrustLevel.MONOTONIC_ESTIMATE

    # Root həddindən KƏNAR.
    line.advance(OFFLINE_TRUST)
    assert service.status().level is TimeTrustLevel.UNTRUSTED


def test_approximate_levels_are_marked_as_such() -> None:
    """`is_approximate` iki səviyyəni əhatə edir, biri yox."""
    assert not TimeIntegrityStatus(
        level=TimeTrustLevel.SERVER_VERIFIED,
        anchor_age_seconds=1.0,
        local_clock_offset_seconds=0.0,
    ).is_approximate
    for level in (TimeTrustLevel.MONOTONIC_ESTIMATE, TimeTrustLevel.UNTRUSTED):
        assert TimeIntegrityStatus(
            level=level, anchor_age_seconds=1.0, local_clock_offset_seconds=0.0
        ).is_approximate


# --------------------------------------------------------------------------- #
# 3. Nasazlığa davamlılıq
# --------------------------------------------------------------------------- #


def test_a_failed_sync_keeps_the_previous_anchor() -> None:
    """Bir buraxılmış sorğu hələ nasazlıq deyil — lövbər SİLİNMİR.

    Silinsəydi, keçici şəbəkə kəsintisi tətbiqi dərhal `UNTRUSTED`-ə salardı
    və oflayn-first vədi mənasını itirərdi.
    """
    service, probe, _ = _build()
    service.sync()
    expected = service.now()

    probe.fail = True
    assert service.sync() is None
    assert service.now() == expected
    assert service.status().level is TimeTrustLevel.SERVER_VERIFIED


def test_the_round_trip_is_compensated_by_half() -> None:
    """Lövbər gediş-dönüşün YARISI qədər irəli sürüşdürülür (SNTP təxmini).

    Kompensasiya olmasaydı, lövbər həmişə cavabın GÖNDƏRİLMƏ anını göstərərdi
    və hər sinxronizasiya vaxtı bir qədər geri çəkərdi.
    """
    line = _Timeline(wall=SERVER_EPOCH)

    class _SlowProbe(_FakeProbe):
        def read_server_time(self) -> datetime:
            line.advance(4)  # 4 saniyəlik gediş-dönüş
            return SERVER_EPOCH

    service, _, _ = _build(probe=_SlowProbe(), timeline=line)
    anchor = service.sync()

    assert anchor is not None
    assert anchor.round_trip_seconds == pytest.approx(4.0)
    assert anchor.server_time == SERVER_EPOCH + timedelta(seconds=2)


# --------------------------------------------------------------------------- #
# 4. Manipulyasiya aşkarlaması
# --------------------------------------------------------------------------- #


def test_a_large_local_offset_triggers_the_callback_once() -> None:
    """Xəbərdarlıq BİR DƏFƏ gedir — saat düzələnə qədər təkrarlanmır.

    Hər sinxronizasiyada göndərilsəydi, 5 dəqiqəlik dövr HR_Admin-in gələn
    qutusuna gündə 288 eyni bildiriş yazardı və siqnal səs-küyə çevrilərdi.
    """
    calls: list[tuple[float, float]] = []
    line = _Timeline(wall=SERVER_EPOCH)
    service, probe, _ = _build(
        timeline=line, on_manipulation=lambda offset, threshold: calls.append((offset, threshold))
    )

    line.tamper_wall_clock(-30 * 60)  # PC-nin saatı 30 dəqiqə geri
    service.sync()
    assert len(calls) == 1
    offset, threshold = calls[0]
    assert offset == pytest.approx(30 * 60)
    assert threshold == MANIPULATION_THRESHOLD

    probe.moment = SERVER_EPOCH + timedelta(seconds=1)
    service.sync()
    assert len(calls) == 1, "eyni pozuntu üçün ikinci bildiriş göndərildi"


def test_the_callback_fires_again_after_the_clock_is_fixed() -> None:
    """Saat düzəlib yenidən pozulsa xəbərdarlıq TƏKRAR gedir — mandal açılır."""
    calls: list[tuple[float, float]] = []
    line = _Timeline(wall=SERVER_EPOCH)
    service, _, _ = _build(
        timeline=line, on_manipulation=lambda offset, threshold: calls.append((offset, threshold))
    )

    line.tamper_wall_clock(-30 * 60)
    service.sync()
    line.tamper_wall_clock(30 * 60)  # düzəldildi
    service.sync()
    line.tamper_wall_clock(-30 * 60)  # yenidən pozuldu
    service.sync()

    assert len(calls) == 2


def test_a_small_offset_is_not_reported() -> None:
    """Hədd daxilindəki fərq NORMALdır — kvars sürüşməsi manipulyasiya deyil."""
    calls: list[object] = []
    line = _Timeline(wall=SERVER_EPOCH)
    service, _, _ = _build(timeline=line, on_manipulation=lambda *_: calls.append(None))

    line.tamper_wall_clock(-int(MANIPULATION_THRESHOLD / 2))
    service.sync()

    assert calls == []


def test_a_failing_callback_does_not_break_the_sync() -> None:
    """Abunəçinin nasazlığı ölçməni pozmamalıdır (`ntp.py` ilə eyni qərar)."""

    def _explode(_offset: float, _threshold: float) -> None:
        raise RuntimeError("bildiriş qatı çökdü")

    line = _Timeline(wall=SERVER_EPOCH)
    service, _, _ = _build(timeline=line, on_manipulation=_explode)
    line.tamper_wall_clock(-30 * 60)

    assert service.sync() is not None


# --------------------------------------------------------------------------- #
# 5. ROOT parametrləri
# --------------------------------------------------------------------------- #


def test_the_interval_is_read_from_root_not_frozen_at_construction() -> None:
    """Root dəyəri dəyişəndə növbəti oxu YENİ dəyəri görməlidir.

    Konstruktorda dondurulsaydı, dəyişiklik yalnız tətbiq yenidən açılanda
    qüvvəyə minərdi — halbuki o, məhz uzun oflayn dövründə lazım olur.
    """
    limits_port = FakeSystemLimits()
    window = InfrastructureLimits(limits=limits_port, tenant_id=TENANT)
    line = _Timeline(wall=SERVER_EPOCH)
    service = ServerTimeService(
        probe=_FakeProbe(),
        fallback_clock=_FakeClock(line.wall),
        limits=window,
        monotonic=lambda: line.monotonic,
        local_now=lambda: line.wall,
    )
    service.sync()

    # Defolt aralıqla təzə lövbər.
    assert service.status().level is TimeTrustLevel.SERVER_VERIFIED

    default_interval = float(DEFAULT_LIMITS[SystemLimitKey.SERVER_TIME_SYNC_INTERVAL_SECONDS])
    line.advance(default_interval * FRESHNESS_INTERVAL_MULTIPLIER + 1)
    assert service.status().level is TimeTrustLevel.MONOTONIC_ESTIMATE

    # Root aralığı böyütdü → eyni lövbər yenidən "təzə" sayılır.
    limits_port.set(SystemLimitKey.SERVER_TIME_SYNC_INTERVAL_SECONDS, "3600")
    assert service.status().level is TimeTrustLevel.SERVER_VERIFIED


def test_every_new_key_has_a_default() -> None:
    """Dörd açarın hamısı `DEFAULT_LIMITS`-dədir — fallback yolu boş qalmasın."""
    for key in (
        SystemLimitKey.SERVER_TIME_SYNC_INTERVAL_SECONDS,
        SystemLimitKey.SERVER_TIME_MAX_OFFLINE_TRUST_SECONDS,
        SystemLimitKey.LOCAL_CLOCK_MANIPULATION_THRESHOLD_SECONDS,
        SystemLimitKey.LOCAL_CLOCK_MANIPULATION_NOTIFY,
    ):
        assert key in DEFAULT_LIMITS, f"`{key.value}` üçün defolt yoxdur"


def test_the_health_row_distinguishes_never_measured_from_zero() -> None:
    """`None` «sürüşmə yoxdur» DEMƏK DEYİL — `ntp.py` ilə eyni qayda."""
    service, _, _ = _build()
    assert service.health["anchor_age_seconds"] is None
    assert service.health["trust_level"] == TimeTrustLevel.UNTRUSTED.value

    service.sync()
    assert service.health["anchor_age_seconds"] == 0.0
    assert service.health["trust_level"] == TimeTrustLevel.SERVER_VERIFIED.value
