"""JSON-formatlı, rotasiya edilən struktur loglama (spesifikasiya bölmə 2).

Dörd ayrı kanal:
    audit.log     — audit-kritik biznes hadisələri (override, cərimə, icazə dəyişikliyi)
    security.log  — autentifikasiya, PIN lockout, privilege dəyişiklikləri
    error.log     — handled/unhandled exception-lar, crash izləri
    app.log       — ümumi tətbiq axını, sync worker, health monitor

İstifadə::

    configure_logging()
    log = get_logger(__name__)
    log.info("Sync tamamlandı", extra={"server_id": 3, "rows": 120})

    audit = get_logger("kompasos.audit", channel=LogChannel.AUDIT)
    audit.info("MANUAL_TIME_OVERRIDE", extra={"operator_id": 7, "employee_id": 22})

PII QAYDASI: `REDACTED_KEYS` siyahısındakı açarlar avtomatik maskalanır — PIN,
şifrə, token, Fernet açarı heç vaxt log-a düşmür.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import threading
import traceback
from collections.abc import MutableMapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Final

from src.shared.data_paths import default_log_dir

# `exceptions.py` HEÇ NƏ idxal etmir (yalnız `typing`), ona görə dairəvi
# idxal riski YOXDUR — yoxlanıldı.
from src.shared.exceptions import KompasOSError

# --------------------------------------------------------------------------- #
# Konfiqurasiya sabitləri
# --------------------------------------------------------------------------- #

#: Log qovluğu FUNKSİYA ilə həll olunur, sabitlə yox — səbəb
#: `data_paths.default_log_dir()` docstring-indədir: idxal anında hesablanan
#: `Path.cwd()/logs` qısayoldan açılan `.exe`-də `System32\\logs` demək idi.

MAX_BYTES: Final[int] = 10 * 1024 * 1024  # 10 MB / fayl
BACKUP_COUNT: Final[int] = 10

#: Bu açarların dəyəri log-a yazılmır (case-insensitive substring uyğunluğu).
REDACTED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "pin",
        "pin_hash",
        "password",
        "password_hash",
        "passwd",
        "secret",
        "token",
        "totp_secret",
        "api_key",
        "apikey",
        "authorization",
        "fernet_key",
        "master_key",
        "encryption_key",
        "credential",
        "private_key",
    }
)

REDACTED_PLACEHOLDER: Final[str] = "***REDACTED***"

#: `extra` içində `LogRecord`-un qorunan sahə adı gələrsə bu prefiks əlavə olunur.
RESERVED_KEY_PREFIX: Final[str] = "ctx_"

#: `logging.LogRecord`-un öz standart sahələri — `extra` ayırd etmək üçün.
_RESERVED_RECORD_ATTRS: Final[frozenset[str]] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class LogChannel(str, Enum):
    """Ayrı-ayrı fayllara yazan log kanalları."""

    AUDIT = "audit"
    SECURITY = "security"
    ERROR = "error"
    APP = "app"

    @property
    def filename(self) -> str:
        return f"{self.value}.log"

    @property
    def logger_name(self) -> str:
        return f"kompasos.{self.value}"


# --------------------------------------------------------------------------- #
# Redaksiya (PII maskalama)
# --------------------------------------------------------------------------- #


def _should_redact(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in REDACTED_KEYS)


#: Rekursiv maskalamanın maksimum dərinliyi (sonsuz dövrə qarşı qoruma).
MAX_REDACT_DEPTH: Final[int] = 6


def redact(value: Any, _depth: int = 0) -> Any:
    """Həssas açarları rekursiv maskalayır."""
    if _depth > MAX_REDACT_DEPTH:
        return "<max-depth>"
    if isinstance(value, dict):
        return {
            key: (REDACTED_PLACEHOLDER if _should_redact(str(key)) else redact(val, _depth + 1))
            for key, val in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [redact(item, _depth + 1) for item in value]
    return value


# --------------------------------------------------------------------------- #
# JSON formatter
# --------------------------------------------------------------------------- #


class JsonFormatter(logging.Formatter):
    """Hər log sətrini tək sətirlik JSON obyektinə çevirir."""

    def __init__(self, *, channel: LogChannel, app_version: str = "0.0.0") -> None:
        super().__init__()
        self.channel = channel
        self.app_version = app_version

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "channel": self.channel.value,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "thread": record.threadName,
            "app_version": self.app_version,
        }

        # `extra=` ilə ötürülən istifadəçi sahələri
        custom = {
            key: val
            for key, val in record.__dict__.items()
            if key not in _RESERVED_RECORD_ATTRS and not key.startswith("_")
        }
        if custom:
            payload["context"] = redact(custom)

        if record.exc_info:
            exc_type, exc_value, exc_tb = record.exc_info
            payload["exception"] = {
                "type": exc_type.__name__ if exc_type else None,
                "message": str(exc_value) if exc_value else None,
                "stacktrace": "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
            }

        if record.stack_info:
            payload["stack_info"] = record.stack_info

        return json.dumps(payload, ensure_ascii=False, default=str)


# --------------------------------------------------------------------------- #
# Qurulum
# --------------------------------------------------------------------------- #

_configured: bool = False
_configure_lock = threading.Lock()


@dataclass(frozen=True)
class _LogDirFallback:
    """Log qovluğu dəyişdirildi — hansı yol istənmişdi və niyə alınmadı."""

    requested: str
    error: str


class LogSetupError(KompasOSError):
    """HEÇ BİR log qovluğu yaradıla bilmədi — açılış dayandırılmalıdır."""


def _usable_log_dir(requested: Path | None) -> tuple[Path, _LogDirFallback | None]:
    """Yazıla bilən log qovluğu tapır — TAPMASA aydın istisna atır.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ BU FUNKSİYA VAR — SƏSSİZ ÖLÜM HALI (dövrə 5 auditi)
    ──────────────────────────────────────────────────────────────────────────
    Əvvəl burada sadəcə `target_dir.mkdir(parents=True, exist_ok=True)` vardı.
    `configure_logging()` isə `main()`-də HƏM `install_global_exception_hook()`
    -dan, HƏM əsas `try/except`-dən ƏVVƏL çağırılır — yəni `mkdir` `OSError`
    atsaydı istisna XAM yüksəlirdi. Paketlənmiş `--windowed` `.exe`-də bunun
    nəticəsi ən pis formadır: **pəncərə yoxdur, mesaj yoxdur, `error.log`-da
    da heç nə yoxdur** — proses sadəcə yox olur. Digər açılış xətalarından
    fərqli olaraq geridə DİAQNOSTİK İZ QALMIR.

    Repro edilib: `%PROGRAMDATA%\\KompasOS\\logs` yolunda eyniadlı FAYL varsa
    `FileExistsError [WinError 183]` yüksəlir (icazə siyasəti və antivirus da
    eyni nəticəni verə bilər).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ ÇÖKMƏK YOX, GERİ ÇƏKİLMƏK
    ──────────────────────────────────────────────────────────────────────────
    Mağaza kassası üçün «log qovluğu yaradıla bilmədi» səbəbi ilə İŞƏ
    DÜŞMƏMƏK yanlış davranışdır: növbə başlayır, kassir işləməlidir, log isə
    ikinci dərəcəli məsələdir. Ona görə əvvəlcə `%TEMP%`-ə çəkilirik — o,
    praktiki olaraq HƏMİŞƏ yazıla biləndir.

    Geri çəkilmə SÜKUTLA olmur: çağıran tərəf `_LogDirFallback` alır və
    `configure_logging` bunu `LOG_DIR_FALLBACK` sətri ilə yazır. Üstəlik
    `main()`-in `KOMPOSOS_STARTING` sətrindəki `log_dir` sahəsi artıq FAKTİKİ
    qovluğu göstərir — yəni «loglar niyə boşdur?» sualı bir baxışda cavablanır.

    HƏR İKİSİ alınmasa istisna atılır, lakin bu dəfə `KompasOSError`
    törəməsidir — yəni `main()`-in mövcud `except KompasOSError` budağı onu
    tutur və istifadəçi `EXIT_STARTUP_ERROR` ilə AYDIN nəticə alır.
    """
    import tempfile

    primary = requested if requested is not None else default_log_dir()
    try:
        primary.mkdir(parents=True, exist_ok=True)
    except OSError as first_error:
        fallback = Path(tempfile.gettempdir()) / "KompasOS" / "logs"
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except OSError as second_error:
            raise LogSetupError(
                "Log qovluğu yaradıla bilmədi",
                user_message=(
                    "Proqram jurnal qovluğunu yarada bilmədi. Administratorunuzla əlaqə saxlayın."
                ),
                context={
                    "requested": str(primary),
                    "fallback": str(fallback),
                    "error": str(second_error),
                },
            ) from second_error
        return fallback, _LogDirFallback(requested=str(primary), error=str(first_error))
    return primary, None


def _console_stream() -> Any:
    r"""Konsol kanalının AXINI — yoxdursa `None` (o zaman handler QURULMUR).

    ──────────────────────────────────────────────────────────────────────────
    HANSI QÜSURU BAĞLAYIR — PAKETLƏNMİŞ `.exe`-DƏ REPRO EDİLİB
    ──────────────────────────────────────────────────────────────────────────
    `dist\KompasOS\KompasOS.exe --check` çıxışı belə idi:

        --- Logging error ---
        UnicodeEncodeError: 'charmap' codec can't encode character 'ı'

    Səbəb: `StreamHandler` axının ÖZ kodlaşdırmasını işlədir. Windows-da boru
    (pipe) və ya yönləndirilmiş çıxış `cp1252`-dir, layihənin HƏR log sətri isə
    Azərbaycan hərfləri daşıyır (bölmə 4: interfeys dili birdir). Nəticədə hər
    sətir `logging` daxilində istisna verirdi — mesaj FAYLA düşürdü (fayl
    handler-i `encoding="utf-8"`-dir), lakin stderr yığınla «Logging error»
    ilə dolurdu. Planlaşdırılmış işlər (`--run-scheduled-jobs`, Task Scheduler)
    məhz belə, yönləndirilmiş çıxışla işləyir.

    İKİ hal ayrıca emal olunur:

      1. `sys.stdout` YOXDUR (`--windowed` paket: PyInstaller onu `None` edir).
         `StreamHandler(None)` sükutla `sys.stderr`-ə keçir, o da `None`
         ola bilər — nəticədə HƏR log sətri istisna verər. Belə halda konsol
         handler-i ÜMUMİYYƏTLƏ qurulmur: fayl kanalı onsuz da yazır.
      2. Axın var, lakin kodlaşdırması UTF-8 DEYİL. `reconfigure()` ilə
         UTF-8-ə keçirilir və `errors="replace"` verilir — kodlaşdırma yenə
         uğursuz olsa sətir İTMİR, simvol əvəzlənir. `reconfigure` mümkün
         olmayan axınlarda (məs. test qoşquları) axın OLDUĞU KİMİ qaytarılır:
         itirilən şey yalnız konsol gözəlliyidir, fayl kanalı toxunulmazdır.
    """
    stream = sys.stdout
    if stream is None:
        return None
    encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
    if encoding not in {"utf8", "utf8sig"}:
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with suppress(Exception):
                reconfigure(encoding="utf-8", errors="replace")
    return stream


def configure_logging(
    *,
    log_dir: Path | None = None,
    level: int | str = logging.INFO,
    app_version: str = "0.0.0",
    console: bool = True,
    force: bool = False,
) -> Path:
    r"""Bütün log kanallarını qurur. Idempotent-dir (təkrar çağırış təsirsizdir).

    Args:
        log_dir: Log fayllarının qovluğu. Defolt: `KOMPASOS_LOG_DIR` və ya
            `%PROGRAMDATA%\KompasOS\logs` (`data_paths.default_log_dir`).
        level: Kök log səviyyəsi.
        app_version: Hər sətrə əlavə olunan tətbiq versiyası.
        console: `True` olduqda `app` kanalı həm də stdout-a yazır.
        force: `True` olduqda mövcud konfiqurasiyanı sıfırlayıb yenidən qurur.

    Returns:
        İstifadə olunan log qovluğunun yolu.
    """
    global _configured

    with _configure_lock:
        if _configured and not force:
            return log_dir or default_log_dir()

        target_dir, fallback_reason = _usable_log_dir(Path(log_dir) if log_dir else None)

        for channel in LogChannel:
            logger = logging.getLogger(channel.logger_name)
            logger.setLevel(level)
            # Kanallar bir-birinə "sızmasın" deyə propagate söndürülür.
            logger.propagate = False

            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()

            file_handler = logging.handlers.RotatingFileHandler(
                filename=target_dir / channel.filename,
                maxBytes=MAX_BYTES,
                backupCount=BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setFormatter(JsonFormatter(channel=channel, app_version=app_version))
            logger.addHandler(file_handler)

            if console and channel is LogChannel.APP:
                console_stream = _console_stream()
                if console_stream is not None:
                    stream_handler = logging.StreamHandler(stream=console_stream)
                    stream_handler.setFormatter(
                        JsonFormatter(channel=channel, app_version=app_version)
                    )
                    logger.addHandler(stream_handler)

        _configured = True

        if fallback_reason:
            # SÜKUT QADAĞANDIR: log qovluğunun DƏYİŞMƏSİ özü diaqnostik
            # faktdır. Bu sətir artıq qurulmuş kanala yazılır, yəni
            # `%TEMP%`-dəki fayla düşür və «loglar niyə boşdur?» sualının
            # cavabı elə orada olur.
            logging.getLogger(LogChannel.ERROR.logger_name).error(
                "LOG_DIR_FALLBACK",
                extra={
                    "requested": fallback_reason.requested,
                    "used": str(target_dir),
                    "error": fallback_reason.error,
                },
            )
        return target_dir


class _MergingLoggerAdapter(logging.LoggerAdapter):  # type: ignore[type-arg]
    """`extra`-nı BİRLƏŞDİRƏN adapter.

    Standart `logging.LoggerAdapter.process()` çağırış yerindəki `extra`-nı
    adapterin öz `extra`-sı ilə ƏVƏZ EDİR (Python < 3.13-də `merge_extra`
    parametri yoxdur). Bu, `log.info("X", extra={"server_id": 3})` yazısındakı
    kontekstin sükutla itməsi deməkdir — struktur loglama üçün qəbuledilməzdir.
    Ona görə birləşdirmə burada əl ilə edilir.
    """

    def process(
        self, msg: Any, kwargs: MutableMapping[str, Any]
    ) -> tuple[Any, MutableMapping[str, Any]]:
        call_extra = kwargs.get("extra") or {}
        merged = {**(self.extra or {}), **call_extra}
        # QORUYUCU: `logging` qorunan sahə adının (`message`, `module`, `name`,
        # `args`, ...) `extra` ilə üzərinə yazılmasına icazə vermir və
        # `KeyError` atır — bu, BÜTÜN TƏTBİQİ çökdürür. Loglama heç vaxt
        # tətbiqi dayandıra bilməz, ona görə belə açarlar səssizcə
        # `ctx_` prefiksi ilə adlandırılır (məlumat itmir).
        kwargs["extra"] = {
            (f"{RESERVED_KEY_PREFIX}{key}" if key in _RESERVED_RECORD_ATTRS else key): value
            for key, value in merged.items()
        }
        return msg, kwargs


def get_logger(name: str, *, channel: LogChannel = LogChannel.APP) -> _MergingLoggerAdapter:
    """Verilmiş kanala bağlı logger qaytarır.

    `configure_logging()` çağırılmayıbsa, avtomatik defolt konfiqurasiya ilə qurur
    ki, import sırasına görə log itkisi olmasın.
    """
    if not _configured:
        configure_logging()

    base = logging.getLogger(channel.logger_name)
    return _MergingLoggerAdapter(base, extra={"source": name})


def install_global_exception_hook(
    *, on_crash: Any = None
) -> None:  # pragma: no cover - proses səviyyəli
    """Tutulmamış istisnaları `error.log`-a yazan qlobal hook quraşdırır.

    Args:
        on_crash: İstəyə bağlı callable — Faza 3-dəki anonim Crash Reporting
            Client bura qoşulur (bax spesifikasiya bölmə 8).
    """
    error_log = get_logger("kompasos.global", channel=LogChannel.ERROR)

    def _hook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        error_log.critical("UNHANDLED_EXCEPTION", exc_info=(exc_type, exc, tb))
        if on_crash is not None:
            try:
                on_crash(exc_type, exc, tb)
            except Exception:
                error_log.exception("CRASH_REPORTER_FAILED")

    sys.excepthook = _hook
