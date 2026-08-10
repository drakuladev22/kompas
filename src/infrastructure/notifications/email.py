"""E-poçt göndərişi (SMTP) — Faza 3.12.

Spesifikasiya bölmə 7: *"Kritik bildirişlər ... YALNIZ tətbiq daxilində
göstərilmir — tətbiq bağlı olduqda bu bildirişlər gözdən qaça bilər. Buna görə
həmin bildirişlər eyni zamanda qeydiyyatlı admin e-poçtuna da göndərilir."*

──────────────────────────────────────────────────────────────────────────────
NİYƏ STDLIB `smtplib`, XARİCİ SERVİS SDK-SI DEYİL
──────────────────────────────────────────────────────────────────────────────
SendGrid/Mailgun kimi SDK-lar həm yeni asılılıq (tədarük zənciri səthi), həm
də yeni abunə deməkdir. Müştəri onsuz da bir korporativ e-poçt qutusuna
malikdir; `smtplib` ondan istifadə etməyə imkan verir və heç nə əlavə
xərcləmir. Faza 3-ün lisenziya qərarı ilə eyni prinsip: mövcud infrastrukturu
işlət, yeni xidmət yaratma.

──────────────────────────────────────────────────────────────────────────────
ŞİFRƏLƏNMİŞ KANAL MƏCBURİDİR
──────────────────────────────────────────────────────────────────────────────
Bildiriş mətnində işçi adı və cərimə səbəbi ola bilər — yəni PII. Ona görə:

    port 465  → `SMTP_SSL` (implicit TLS)
    digər     → `SMTP` + `STARTTLS`, uğursuz olarsa GÖNDƏRİLMİR

STARTTLS-in sükutla ötürülməsi ("server dəstəkləmir, düz mətnlə göndərək")
QƏSDƏN yoxdur: şifrələnməmiş kanalda PII göndərmək bildirişi ümumiyyətlə
göndərməməkdən pisdir.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from email.utils import formataddr
from typing import TYPE_CHECKING, Final

from src.shared.exceptions import KompasOSError
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

_log = get_logger(__name__)

SMTP_HOST_ENV: Final[str] = "KOMPASOS_SMTP_HOST"
SMTP_PORT_ENV: Final[str] = "KOMPASOS_SMTP_PORT"
SMTP_USER_ENV: Final[str] = "KOMPASOS_SMTP_USER"
#: Şifrənin ÖZÜ deyil, onu daşıyan mühit dəyişəninin ADI.
SMTP_PASSWORD_ENV: Final[str] = "KOMPASOS_SMTP_PASSWORD"  # noqa: S105
SMTP_FROM_ENV: Final[str] = "KOMPASOS_SMTP_FROM"

DEFAULT_SMTP_PORT: Final[int] = 587
#: Bu portda TLS bağlantının ƏVVƏLİNDƏ başlayır (STARTTLS deyil).
IMPLICIT_TLS_PORT: Final[int] = 465
DEFAULT_TIMEOUT_SECONDS: Final[float] = 15.0
#: Göndərənin görünən adı — qutuda "KompasOS" kimi tanınsın.
SENDER_DISPLAY_NAME: Final[str] = "KompasOS"


class EmailError(KompasOSError):
    """E-poçt göndərilə bilmədi."""

    user_message = "Bildiriş e-poçtu göndərilə bilmədi."


class EmailNotConfiguredError(EmailError):
    """SMTP parametrləri təyin edilməyib.

    AYRI xəta tipidir, çünki reaksiya da fərqlidir: konfiqurasiya yoxdursa
    təkrar cəhd MƏNASIZDIR — növbədəki bildiriş sonsuza qədər "gözləyən"
    qalmamalı, açıq şəkildə "konfiqurasiya lazımdır" kimi işarələnməlidir.
    """

    user_message = (
        "E-poçt bildirişləri konfiqurasiya edilməyib. "
        "Ayarlar → İnfrastruktur bölməsindən SMTP parametrlərini doldurun."
    )


@dataclass(frozen=True)
class EmailConfig:
    """SMTP parametrləri.

    `__repr__` şifrəni GİZLƏDİR — konfiqurasiya obyekti log-a və ya xəta
    kontekstinə düşsə belə parol sızmasın.
    """

    host: str
    port: int = DEFAULT_SMTP_PORT
    username: str = ""
    password: str = ""
    sender: str = ""
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def __repr__(self) -> str:
        return (
            f"EmailConfig(host={self.host!r}, port={self.port}, "
            f"username={self.username!r}, sender={self.sender!r}, password=***)"
        )

    @property
    def uses_implicit_tls(self) -> bool:
        return self.port == IMPLICIT_TLS_PORT

    @classmethod
    def from_env(cls) -> EmailConfig | None:
        """Mühit dəyişənlərindən qurur; host yoxdursa `None`.

        `None` "nasazlıq" DEYİL — e-poçt fallback-ı istəyə bağlı bir kanaldır
        və konfiqurasiya edilməyən quraşdırmada tətbiq normal işləməlidir.
        """
        host = os.environ.get(SMTP_HOST_ENV, "").strip()
        if not host:
            return None
        raw_port = os.environ.get(SMTP_PORT_ENV, "").strip()
        try:
            port = int(raw_port) if raw_port else DEFAULT_SMTP_PORT
        except ValueError:
            port = DEFAULT_SMTP_PORT
        return cls(
            host=host,
            port=port,
            username=os.environ.get(SMTP_USER_ENV, "").strip(),
            password=os.environ.get(SMTP_PASSWORD_ENV, ""),
            sender=os.environ.get(SMTP_FROM_ENV, "").strip(),
        )


@dataclass(frozen=True)
class OutgoingEmail:
    """Göndəriləcək mesaj."""

    to: tuple[str, ...]
    subject: str
    body: str

    def __post_init__(self) -> None:
        if not self.to:
            msg = "Ən azı bir alıcı olmalıdır."
            raise ValueError(msg)
        if not self.subject.strip():
            msg = "Mövzu boş ola bilməz."
            raise ValueError(msg)


class SmtpEmailSender:
    """SMTP üzərindən e-poçt göndərir.

    Sinxron və sadədir — göndəriş arxa fon sapından çağırılır
    (`EmailFallbackDispatcher`), ona görə burada növbə/paralellik yoxdur.
    """

    def __init__(
        self,
        config: EmailConfig | None = None,
        *,
        transport: object = None,
    ) -> None:
        self._config = config
        # Testdə `smtplib.SMTP` əvəzinə saxta obyekt verilir — real şəbəkə
        # bağlantısı olmadan bütün axın (STARTTLS, login, send) yoxlanılır.
        self._transport = transport

    @property
    def is_configured(self) -> bool:
        return self._config is not None and bool(self._config.host)

    def send(self, message: OutgoingEmail) -> None:
        """Mesajı göndərir. Uğursuzluqda `EmailError`."""
        config = self._config
        if config is None or not config.host:
            raise EmailNotConfiguredError(
                "SMTP host təyin edilməyib", context={"env": SMTP_HOST_ENV}
            )

        mime = _build_mime(message, config)
        try:
            self._deliver(config, message.to, mime)
        except EmailError:
            raise
        except (smtplib.SMTPAuthenticationError, smtplib.SMTPNotSupportedError) as exc:
            # Autentifikasiya/imkan xətası təkrar cəhdlə düzəlmir.
            raise EmailNotConfiguredError(
                f"SMTP autentifikasiyası alınmadı: {exc.__class__.__name__}",
                context={"host": config.host, "port": config.port},
            ) from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailError(
                f"SMTP göndərişi alınmadı: {exc.__class__.__name__}",
                context={"host": config.host, "port": config.port, "error": str(exc)},
            ) from exc

        _log.info(
            "EMAIL_SENT",
            extra={
                "recipients": len(message.to),
                "subject": message.subject,
                "host": config.host,
            },
        )

    def _deliver(self, config: EmailConfig, recipients: Sequence[str], mime: MimeMessage) -> None:
        context = ssl.create_default_context()
        client = self._open(config, context)
        try:
            if not config.uses_implicit_tls:
                client.ehlo()
                # STARTTLS DƏSTƏKLƏNMİRSƏ GÖNDƏRMİRİK (bax modul başlığı).
                client.starttls(context=context)
                client.ehlo()
            if config.username:
                client.login(config.username, config.password)
            client.send_message(mime, to_addrs=list(recipients))
        finally:
            with _suppress_quit_errors():
                client.quit()

    def _open(self, config: EmailConfig, context: ssl.SSLContext) -> smtplib.SMTP:
        if self._transport is not None:
            return self._transport(config)  # type: ignore[operator, no-any-return]
        if config.uses_implicit_tls:
            return smtplib.SMTP_SSL(
                config.host, config.port, timeout=config.timeout_seconds, context=context
            )
        return smtplib.SMTP(config.host, config.port, timeout=config.timeout_seconds)


def _build_mime(message: OutgoingEmail, config: EmailConfig) -> MimeMessage:
    mime = MimeMessage()
    sender = config.sender or config.username or f"kompasos@{config.host}"
    mime["From"] = formataddr((SENDER_DISPLAY_NAME, sender))
    mime["To"] = ", ".join(message.to)
    mime["Subject"] = message.subject
    mime.set_content(message.body)
    return mime


class _suppress_quit_errors:  # noqa: N801 — kontekst meneceri, sinif adı deyil
    """`quit()` xətası GÖNDƏRİŞİ ləğv etməməlidir.

    Bəzi serverlər mesajı qəbul etdikdən sonra bağlantını dərhal kəsir;
    `quit()` orada `SMTPServerDisconnected` atır. Bunu ötürmək "göndərilmədi"
    kimi qeyd etsəydik, eyni bildiriş dəfələrlə göndərilərdi.
    """

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        if exc_type is None:
            return False
        _log.debug("SMTP_QUIT_FAILED", extra={"error": str(exc)})
        return True


__all__ = [
    "DEFAULT_SMTP_PORT",
    "IMPLICIT_TLS_PORT",
    "SMTP_HOST_ENV",
    "EmailConfig",
    "EmailError",
    "EmailNotConfiguredError",
    "OutgoingEmail",
    "SmtpEmailSender",
]
