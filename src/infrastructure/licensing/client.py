"""Lisenziya klienti — dövri yoxlama və məhdud-rejim vəziyyəti (bölmə 8).

Spesifikasiya: *"Lisenziya açarı mərkəzi lisenziya serverinə qarşı dövri (məs.
hər 24 saatda) yoxlanılır"* — yeni arxitekturada "mərkəzi server" mövcud
Supabase layihəsinin `license_tenants` cədvəlidir (bax `licensing.py` başlığı).

──────────────────────────────────────────────────────────────────────────────
İKİ QAT, İKİ MƏSULİYYƏT
──────────────────────────────────────────────────────────────────────────────
    `SupabaseLicenseGateway` — YALNIZ sorğu: sətri oxu, uğursuzluqda xəta at.
                               Heç bir qərar VERMİR.
    `LicenseClient`          — qərar verən qat: nə vaxt oxumalı, harada
                               saxlamalı, hansı məhdudiyyət aktivdir.

Ayrılığın səbəbi testdir: bütün sərhəd halları (qrace bitir, saat geri
çəkilir, müddət keçir, tenant deaktiv edilir) bazaya toxunmadan yoxlanılır —
`LicenseClient` sadəcə saxta gateway alır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ ARXA FON SAPI, `await` DEYİL
──────────────────────────────────────────────────────────────────────────────
Tətbiq PySide6-dır və UI sapı bloklanmamalıdır. Sutkada bir dəfə işləyən bir
sorğu üçün bütün tətbiqi asinxron etməyə dəyməz; NTP yoxlayıcısı
(`NtpDriftChecker`) da eyni nümunə ilə işləyir — iki fərqli konkurensiya
modeli saxlamaq oxunuşu çətinləşdirərdi.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.domain.policies import SystemLimitKey
from src.domain.value_objects.licensing import (
    CheckInRequest,
    LicenseLimits,
    LicenseNotFoundError,
    LicenseSnapshot,
    LicenseState,
    LicenseStatus,
    Telemetry,
    evaluate,
    payment_warning,
)
from src.infrastructure.config.limits import InfrastructureLimits
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.domain.interfaces.ports import LicenseGateway, LicenseStateStore
    from src.domain.value_objects.identifiers import TenantId
    from src.domain.value_objects.licensing import CrashReport

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)


class LicenseClient:
    """Dövri yoxlama + cari məhdud-rejim vəziyyəti.

    `current_state()` HƏMİŞƏ dərhal qayıdır (şəbəkə gözləmir) — UI hər
    çəkilişdə onu oxuya bilər.
    """

    def __init__(
        self,
        tenant_id: TenantId,
        gateway: LicenseGateway,
        store: LicenseStateStore,
        *,
        app_version: str,
        dev_mode: bool = False,
        limits: InfrastructureLimits | None = None,
        interval_seconds: float | None = None,
        retry_interval_seconds: float | None = None,
        blocked_interval_seconds: float | None = None,
        telemetry_source: Callable[[], Telemetry] | None = None,
        drift_source: Callable[[], float | None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._gateway = gateway
        self._store = store
        self._app_version = app_version
        self._dev_mode = dev_mode
        # ROOT PƏNCƏRƏSİ SAXLANILIR, DƏYƏR YOX: qrace bandı və xəbərdarlıq
        # günü HƏR `current_state()` çağırışında yenidən oxunur (aşağı bax),
        # üç RİTM isə burada bir dəfə oxunur — onlar arxa fon sapının
        # gözləmə cədvəlidir və sap yenidən başlayana qədər onsuz da dəyişə
        # bilməz. `limits=None` → `DEFAULT_LIMITS` fallback-ı, yəni davranış
        # köçürmədən ƏVVƏLKİ ilə eynidir.
        self._limits = limits or InfrastructureLimits()
        self._interval = self._seconds(
            interval_seconds, SystemLimitKey.LICENSE_CHECK_IN_INTERVAL_SECONDS
        )
        self._retry_interval = self._seconds(
            retry_interval_seconds, SystemLimitKey.LICENSE_RETRY_INTERVAL_SECONDS
        )
        self._blocked_interval = self._seconds(
            blocked_interval_seconds, SystemLimitKey.LICENSE_BLOCKED_RECHECK_INTERVAL_SECONDS
        )
        self._telemetry_source = telemetry_source
        self._drift_source = drift_source
        self._clock = clock or (lambda: datetime.now(UTC))

        self._lock = threading.Lock()
        self._snapshot: LicenseSnapshot | None = store.load()
        self._last_error: str = ""
        self._consecutive_failures = 0

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def _seconds(self, explicit: float | None, key: SystemLimitKey) -> float:
        """Açıq arqument → ROOT dəyəri → fallback (bu sıra ilə).

        Açıq arqument birinci gəlir, çünki onu VERƏN tərəf (test, xüsusi
        quraşdırma) niyyətini artıq bildirib; Root dəyərinin onu sükutla
        üstələməsi "niyə mənim dəyərim işləmir?" sualını doğurardı
        (`EncryptedLicenseStateStore` ilə eyni qayda).
        """
        return explicit if explicit is not None else self._limits.float_of(key)

    def _license_limits(self) -> LicenseLimits:
        """ROOT-un lisenziya bandı — HƏR ÇAĞIRIŞDA oxunur.

        Klient tətbiqin bütün ömrü boyu yaşayır; qrace bandını konstruktorda
        dondursaydıq, Root-un "offline qrace 14 günə qaldırılsın" qərarı
        yalnız proqram yenidən başladıqdan sonra işləyərdi — halbuki həmin
        qərar məhz şəbəkəsi kəsilmiş filial üçün TƏCİLİ verilir.
        """
        return LicenseLimits(
            min_offline_grace_days=self._limits.int_of(
                SystemLimitKey.LICENSE_MIN_OFFLINE_GRACE_DAYS
            ),
            max_offline_grace_days=self._limits.int_of(
                SystemLimitKey.LICENSE_MAX_OFFLINE_GRACE_DAYS
            ),
            default_offline_grace_days=self._limits.int_of(
                SystemLimitKey.LICENSE_DEFAULT_OFFLINE_GRACE_DAYS
            ),
            expiry_warning_days=self._limits.int_of(SystemLimitKey.LICENSE_EXPIRY_WARNING_DAYS),
            extension_days=self._limits.int_of(SystemLimitKey.LICENSE_EXTENSION_DAYS),
        )

    # ------------------------------ vəziyyət --------------------------------- #

    def current_state(self) -> LicenseState:
        """Cari məhdudiyyətlər — şəbəkə sorğusu YOXDUR, dərhal qayıdır."""
        now = self._clock()
        with self._lock:
            snapshot = self._snapshot
        return evaluate(
            snapshot,
            now=now,
            first_run_at=self._store.first_run_at(),
            clock_high_water=self._store.clock_high_water(),
            clock_rollback=self._store.clock_rollback_detected(now),
            time_drift_seconds=self._drift_source() if self._drift_source else None,
            dev_mode=self._dev_mode,
            limits=self._license_limits(),
        )

    def payment_banner(self) -> str:
        """Müddət xəbərdarlığı mətni; xəbərdarlıq lazım deyilsə boş sətir."""
        with self._lock:
            snapshot = self._snapshot
        return payment_warning(snapshot, now=self._clock(), limits=self._license_limits())

    @property
    def snapshot(self) -> LicenseSnapshot | None:
        with self._lock:
            return self._snapshot

    @property
    def status(self) -> dict[str, object]:
        """System Health Monitor sətri (bölmə 6)."""
        state = self.current_state()
        with self._lock:
            snapshot = self._snapshot
            failures = self._consecutive_failures
            error = self._last_error
        return {
            "license_status": snapshot.status.value if snapshot else None,
            "last_check_in_at": snapshot.checked_at.isoformat() if snapshot else None,
            "expires_at": snapshot.expires_at.isoformat()
            if snapshot and snapshot.expires_at
            else None,
            "license_days_left": state.license_days_left,
            "offline_grace_days_left": state.offline_grace_days_left,
            "restrictions": [item.kind.value for item in state.restrictions],
            "is_blocked": state.is_blocked,
            "consecutive_failures": failures,
            "last_error": error,
        }

    # ------------------------------- yoxlama --------------------------------- #

    def check_in(self) -> LicenseSnapshot | None:
        """Bir yoxlama dövrü. Uğursuzluqda `None` — XƏTA ATMIR.

        Çağıran tərəf (arxa fon sapı və ya "İndi Yoxla" düyməsi) uğursuzluğu
        idarə etməyə məcbur olmamalıdır: bu, dizayn üzrə normal haldır.
        """
        request = CheckInRequest(
            tenant_id=self._tenant_id,
            app_version=self._app_version,
            telemetry=self._telemetry_source() if self._telemetry_source else Telemetry(),
        )
        try:
            snapshot = self._gateway.check_in(request)
        except LicenseNotFoundError as exc:
            self._record_failure(str(exc))
            return None
        except Exception as exc:
            # `LicenseUnavailableError` və gözlənilməz istisnalar eyni
            # nəticəyə aparır: qrace işləyir, tətbiq bloklanmır.
            self._record_failure(str(exc))
            return None

        self._accept(snapshot)
        return snapshot

    def _accept(self, snapshot: LicenseSnapshot) -> None:
        with self._lock:
            previous = self._snapshot
            self._snapshot = snapshot
            self._consecutive_failures = 0
            self._last_error = ""
        self._store.save(snapshot)

        changed = (
            previous is None
            or previous.status is not snapshot.status
            or previous.expires_at != snapshot.expires_at
        )
        if changed:
            # Status/müddət dəyişməsi kommersiya hadisəsidir — həmişə qeydə alınır.
            log = (
                _security_log.critical
                if snapshot.status is LicenseStatus.DEAKTIV
                else _security_log.info
            )
            log(
                "LICENSE_STATUS_CHANGED",
                extra={
                    "previous": previous.status.value if previous else None,
                    "current": snapshot.status.value,
                    "expires_at": snapshot.expires_at.isoformat() if snapshot.expires_at else None,
                    "reason": snapshot.deactivation_reason or None,
                },
            )
        else:
            _log.debug("LICENSE_CHECK_IN_OK", extra={"status": snapshot.status.value})

    def _record_failure(self, message: str) -> None:
        with self._lock:
            self._consecutive_failures += 1
            self._last_error = message
            failures = self._consecutive_failures
            snapshot = self._snapshot
        _log.warning(
            "LICENSE_CHECK_IN_FAILED",
            extra={
                "consecutive_failures": failures,
                "error": message,
                "cached_status": snapshot.status.value if snapshot else None,
                "impact": "offline qrace işləyir — tətbiq bloklanmır",
            },
        )

    def report_crash(self, report: CrashReport) -> bool:
        """Crash hesabatını göndərir. Uğursuzluq sükutla udulur — hesabat
        göndərə bilməmək istifadəçinin işini pozmamalıdır."""
        try:
            self._gateway.report_crash(report)
        except Exception as exc:
            _log.debug("CRASH_REPORT_FAILED", extra={"error": str(exc)})
            return False
        return True

    # ---------------------------- arxa fon sapı ------------------------------ #

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="license-check-in", daemon=True)
        self._thread.start()
        _log.info("LICENSE_CLIENT_STARTED", extra={"interval_seconds": self._interval})

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        self._thread = None
        _log.info("LICENSE_CLIENT_STOPPED")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                success = self.check_in() is not None
            except Exception as exc:  # arxa fon sapı heç vaxt ölməməlidir
                success = False
                _log.error("LICENSE_LOOP_CRASHED", extra={"error": str(exc)})
            self._stop_event.wait(self._next_wait(success=success))

    def _next_wait(self, *, success: bool) -> float:
        """Növbəti yoxlamaya qədər gözləmə — üç fərqli ritm.

            uğursuzluq  → `retry_interval`  bərpa olunmuş şəbəkəni bir gün gec
                                            görmək qrace-i mənasız yerə yeyər
            BLOKLANMIŞ  → `blocked_interval` ödəniş edilib, panel uzadılıb —
                                            mağaza 24 saat gözləməməlidir
                                            ("Force Sync"in serversiz qarşılığı)
            normal      → `interval`        sutkada bir dəfə

        Vəziyyət `current_state()`-dən oxunur, yəni bloklanma səbəbi (müddət
        bitib, tenant deaktivdir, qrace tükənib) fərq etmir — hər üç halda
        həll YENİ MƏLUMATdır və o da yalnız yoxlama ilə gəlir.
        """
        if not success:
            return self._retry_interval
        return self._blocked_interval if self.current_state().is_blocked else self._interval


__all__ = ["LicenseClient"]
