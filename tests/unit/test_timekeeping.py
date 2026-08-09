"""Saat və NTP sürüşmə nəzarətçisi testləri (Faza 3.4)."""

from __future__ import annotations

import socket
import struct
import threading
import time
from contextlib import suppress
from datetime import UTC, datetime

import pytest

from src.infrastructure.timekeeping.clock import NtpCorrectedClock, SystemClock, to_baku
from src.infrastructure.timekeeping.ntp import (
    NTP_UNIX_DELTA,
    NtpDriftChecker,
    NtpError,
    NtpSample,
    SntpClient,
)

# --------------------------------------------------------------------------- #
# Sahtə SNTP klienti
# --------------------------------------------------------------------------- #


class FakeSntpClient:
    """Ölçmə nəticəsini testdən idarə etməyə imkan verir."""

    def __init__(self) -> None:
        self.offset = 0.0
        self.fail = False
        #: Ölçmənin süni yaşı — köhnəlmə testlərini `sleep()`-siz və
        #: deterministik edir (Windows-da `monotonic()` addımı ~15 ms-dir,
        #: qısa `sleep` heç bir fərq yaratmaya bilər).
        self.age_seconds = 0.0
        self.calls: list[str] = []

    def query(self, server: str, *, port: int = 123) -> NtpSample:
        self.calls.append(server)
        if self.fail:
            raise NtpError(f"{server}: sahtə nasazlıq")
        return NtpSample(
            server=server,
            offset_seconds=self.offset,
            delay_seconds=0.01,
            stratum=2,
            measured_at_monotonic=time.monotonic() - self.age_seconds,
        )


def make_checker(**kwargs: object) -> tuple[NtpDriftChecker, FakeSntpClient]:
    client = FakeSntpClient()
    checker = NtpDriftChecker(
        servers=("a.example", "b.example"),
        client=client,  # type: ignore[arg-type]
        max_drift_seconds=60.0,
        machine_name="TEST-PC",
        **kwargs,  # type: ignore[arg-type]
    )
    return checker, client


# --------------------------------------------------------------------------- #
# Clock
# --------------------------------------------------------------------------- #


def test_system_clock_is_timezone_aware_utc() -> None:
    """Naive datetime DB-də sükutla səhv qurşaqda şərh olunardı."""
    moment = SystemClock().now()
    assert moment.tzinfo is not None
    assert moment.utcoffset() is not None
    assert moment.utcoffset().total_seconds() == 0  # type: ignore[union-attr]


def test_to_baku_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="Naive"):
        to_baku(datetime(2026, 1, 1, 12, 0))  # noqa: DTZ001 - qəsdən naive


def test_to_baku_adds_four_hours() -> None:
    utc = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
    assert to_baku(utc).hour == 12


def test_ntp_corrected_clock_applies_offset() -> None:
    checker, client = make_checker()
    client.offset = 30.0
    checker.poll()

    corrected = NtpCorrectedClock(checker).now()
    raw = datetime.now(UTC)
    assert 25 < (corrected - raw).total_seconds() < 35


def test_ntp_corrected_clock_without_sample_is_plain_system_time() -> None:
    checker, client = make_checker()
    client.fail = True
    checker.poll()

    delta = NtpCorrectedClock(checker).now() - datetime.now(UTC)
    assert abs(delta.total_seconds()) < 1


# --------------------------------------------------------------------------- #
# Üç halın fərqləndirilməsi
# --------------------------------------------------------------------------- #


def test_never_measured_is_unverified_with_unknown_drift() -> None:
    """Ölçülməyib ≠ sürüşmə yoxdur — `drift=None` blok YARATMIR (bölmə 5)."""
    checker, _ = make_checker()
    _, verified = checker.verified_now()
    assert verified is False
    assert checker.drift_seconds() is None


def test_measurement_within_threshold_is_verified() -> None:
    checker, client = make_checker()
    client.offset = 5.0
    checker.poll()

    _, verified = checker.verified_now()
    assert verified is True
    assert checker.drift_seconds() == pytest.approx(5.0)


def test_measurement_beyond_threshold_blocks() -> None:
    checker, client = make_checker()
    client.offset = 95.0
    checker.poll()

    _, verified = checker.verified_now()
    assert verified is False
    assert checker.drift_seconds() == pytest.approx(95.0)


def test_negative_drift_beyond_threshold_also_blocks() -> None:
    """Saatı GERİ çəkmək gecikməni gizlədir — mütləq qiymətə baxılır."""
    checker, client = make_checker()
    client.offset = -95.0
    checker.poll()

    assert checker.verified_now()[1] is False
    assert checker.drift_seconds() == pytest.approx(-95.0)


# --------------------------------------------------------------------------- #
# Mandal (latch) — hücum ssenarisi
# --------------------------------------------------------------------------- #


def test_alarm_survives_ntp_becoming_unreachable() -> None:
    """Saatı dəyiş, sonra NTP-ni blokla → blok İTMƏMƏLİDİR."""
    checker, client = make_checker()
    client.offset = 300.0
    checker.poll()
    assert checker.drift_seconds() == pytest.approx(300.0)

    client.fail = True
    checker.poll()

    assert checker.verified_now()[1] is False
    assert checker.drift_seconds() == pytest.approx(300.0), "mandal açıldı — blok itdi"


def test_alarm_survives_sample_expiry() -> None:
    """Ölçmənin köhnəlməsi də mandalı açmır."""
    checker, client = make_checker(sample_ttl_seconds=60.0)
    client.offset = 300.0
    client.age_seconds = 3600.0
    checker.poll()

    assert checker.drift_seconds() == pytest.approx(300.0)
    assert checker.verified_now()[1] is False


def test_alarm_cleared_only_by_fresh_good_measurement() -> None:
    checker, client = make_checker()
    client.offset = 300.0
    checker.poll()
    assert checker.drift_seconds() == pytest.approx(300.0)

    client.offset = 1.0
    checker.poll()

    assert checker.verified_now()[1] is True
    assert checker.drift_seconds() == pytest.approx(1.0)


def test_stale_good_sample_is_unverified_but_not_blocking() -> None:
    """Köhnəlmiş YAXŞI ölçmə: təsdiq yoxdur, amma blok da yoxdur."""
    checker, client = make_checker(sample_ttl_seconds=60.0)
    client.offset = 1.0
    client.age_seconds = 3600.0
    checker.poll()

    assert checker.verified_now()[1] is False
    assert checker.drift_seconds() is None


# --------------------------------------------------------------------------- #
# Server sırası, hadisə, status
# --------------------------------------------------------------------------- #


def test_falls_back_to_second_server() -> None:
    client = FakeSntpClient()
    calls: list[str] = []

    def query(server: str, *, port: int = 123) -> NtpSample:
        calls.append(server)
        if server == "a.example":
            raise NtpError("ilk server düşüb")
        return NtpSample(server, 2.0, 0.01, 2, time.monotonic())

    client.query = query  # type: ignore[assignment,method-assign]
    checker = NtpDriftChecker(
        servers=("a.example", "b.example"),
        client=client,  # type: ignore[arg-type]
    )
    sample = checker.poll()

    assert calls == ["a.example", "b.example"]
    assert sample is not None
    assert sample.server == "b.example"


def test_drift_event_published_once_per_bad_sample() -> None:
    events: list[object] = []
    client = FakeSntpClient()
    client.offset = 120.0
    checker = NtpDriftChecker(
        servers=("a.example",),
        client=client,  # type: ignore[arg-type]
        on_drift=events.append,
    )
    checker.poll()

    assert len(events) == 1
    assert events[0].drift_seconds == pytest.approx(120.0)  # type: ignore[attr-defined]


def test_event_handler_failure_does_not_break_measurement() -> None:
    def boom(_event: object) -> None:
        raise RuntimeError("abunəçi çökdü")

    client = FakeSntpClient()
    client.offset = 120.0
    checker = NtpDriftChecker(
        servers=("a.example",),
        client=client,  # type: ignore[arg-type]
        on_drift=boom,
    )
    checker.poll()  # istisna kənara çıxmamalıdır

    assert checker.drift_seconds() == pytest.approx(120.0)


def test_threshold_is_updatable_from_system_limits() -> None:
    checker, client = make_checker()
    client.offset = 90.0
    checker.poll()
    assert checker.verified_now()[1] is False

    checker.set_max_drift_seconds(300.0)
    checker.poll()
    assert checker.verified_now()[1] is True


def test_status_row_for_health_monitor() -> None:
    checker, client = make_checker()
    client.fail = True
    checker.poll()
    checker.poll()

    status = checker.status
    assert status["consecutive_failures"] == 2
    assert status["is_fresh"] is False
    assert status["max_drift_seconds"] == 60.0


def test_background_thread_starts_and_stops() -> None:
    checker, client = make_checker(poll_interval_seconds=0.01)
    checker.start()
    checker.start()  # idempotent — ikinci sap yaranmamalıdır
    deadline = time.monotonic() + 2.0
    while not client.calls and time.monotonic() < deadline:
        time.sleep(0.01)
    checker.stop(timeout=2.0)

    assert client.calls, "arxa fon sapı heç bir ölçmə etmədi"
    assert not any(t.name == "ntp-drift-checker" for t in threading.enumerate())


# --------------------------------------------------------------------------- #
# Real SNTP protokol qatı (lokal sahtə server)
# --------------------------------------------------------------------------- #


class _FakeNtpServer:
    """48 baytlıq cavab qaytaran minimal UDP server."""

    def __init__(self, *, offset: float = 0.0, stratum: int = 2, mode: int = 4) -> None:
        self.offset = offset
        self.stratum = stratum
        self.mode = mode
        self.echo_originate = True
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.settimeout(2.0)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            data, addr = self._sock.recvfrom(256)
        except OSError:
            return
        now = time.time() + self.offset
        reply = bytearray(48)
        reply[0] = (0 << 6) | (4 << 3) | self.mode
        reply[1] = self.stratum
        # Originate = klientin transmit timestamp-ı (offset 40 → 24).
        reply[24:32] = data[40:48] if self.echo_originate else bytes(8)
        seconds = int(now) + NTP_UNIX_DELTA
        fraction = int((now - int(now)) * 4_294_967_296.0)
        struct.pack_into("!II", reply, 32, seconds, fraction)
        struct.pack_into("!II", reply, 40, seconds, fraction)
        with suppress(OSError):
            self._sock.sendto(bytes(reply), addr)

    def close(self) -> None:
        self._sock.close()


def test_sntp_client_parses_real_packet() -> None:
    server = _FakeNtpServer(offset=42.0)
    try:
        sample = SntpClient(timeout=2.0).query("127.0.0.1", port=server.port)
    finally:
        server.close()

    assert sample.stratum == 2
    assert sample.offset_seconds == pytest.approx(42.0, abs=1.0)
    assert sample.delay_seconds >= 0


def test_sntp_client_rejects_kiss_of_death_stratum_zero() -> None:
    """Stratum 0 = server imtina edir; bunu vaxt kimi qəbul etmək təhlükəlidir."""
    server = _FakeNtpServer(stratum=0)
    try:
        with pytest.raises(NtpError, match="stratum"):
            SntpClient(timeout=2.0).query("127.0.0.1", port=server.port)
    finally:
        server.close()


def test_sntp_client_rejects_mismatched_originate_timestamp() -> None:
    """Sorğumuza aid olmayan cavab = spoofing və ya köhnə paket."""
    server = _FakeNtpServer()
    server.echo_originate = False
    try:
        with pytest.raises(NtpError, match="originate"):
            SntpClient(timeout=2.0).query("127.0.0.1", port=server.port)
    finally:
        server.close()


def test_sntp_client_times_out_on_silent_server() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    try:
        with pytest.raises(NtpError):
            SntpClient(timeout=0.2).query("127.0.0.1", port=port)
    finally:
        sock.close()
