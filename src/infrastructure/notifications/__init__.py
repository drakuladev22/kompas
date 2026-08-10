"""E-poçt fallback, in-app bildiriş, anonim crash reporting — Faza 3.12."""

from typing import TYPE_CHECKING

from src.infrastructure.notifications.crash_reporter import (
    MAX_REPORTS_PER_FINGERPRINT,
    CrashReporter,
    fingerprint_of,
    format_trace,
    install_crash_reporting,
    scrub,
)
from src.infrastructure.notifications.email import (
    EmailConfig,
    EmailError,
    EmailNotConfiguredError,
    OutgoingEmail,
    SmtpEmailSender,
)
from src.infrastructure.notifications.notifier import (
    BACKOFF_MINUTES,
    MAX_ATTEMPTS,
    EmailFallbackDispatcher,
    PostgresNotifier,
)

if TYPE_CHECKING:  # pragma: no cover
    # PORT UYĞUNLUĞUNUN STATİK YOXLAMASI — `erp/` və `licensing/` ilə eyni üsul.
    # `Protocol` structural typing olduğu üçün imza sürüşməsi işlək zamana
    # qədər gizli qalardı; bu funksiya HEÇ VAXT çağırılmır.
    from src.domain.interfaces.ports import Notifier

    def _assert_port_conformance(notifier: PostgresNotifier) -> None:
        _notifier: Notifier = notifier


__all__ = [
    "BACKOFF_MINUTES",
    "MAX_ATTEMPTS",
    "MAX_REPORTS_PER_FINGERPRINT",
    "CrashReporter",
    "EmailConfig",
    "EmailError",
    "EmailFallbackDispatcher",
    "EmailNotConfiguredError",
    "OutgoingEmail",
    "PostgresNotifier",
    "SmtpEmailSender",
    "fingerprint_of",
    "format_trace",
    "install_crash_reporting",
    "scrub",
]
