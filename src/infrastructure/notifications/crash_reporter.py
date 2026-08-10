"""Anonim crash/xəta hesabatı klienti (bölmə 8) — Faza 3.12.

Spesifikasiya: *"Tətbiqdə baş verən handled/unhandled exception-lar və
crash-lər avtomatik, anonimləşdirilmiş şəkildə (heç bir PII, yalnız
stack-trace + versiya + anonim tenant ID) Developer Panelinə göndərilir və
tezliyə görə qruplaşdırılır. Bu, sizin bir bug-ı müştəri şikayət etməzdən
ƏVVƏL görməyinizi mümkün edir."*

──────────────────────────────────────────────────────────────────────────────
"HEÇ BİR PII" SADƏ BİR VƏD DEYİL — STACK-TRACE PII DAŞIYIR
──────────────────────────────────────────────────────────────────────────────
Adi Python trace-i ən azı üç yerdən şəxsi məlumat gətirir:

    1. FAYL YOLLARI — `C:\\Users\\Elvin\\...` istifadəçi adını açıq yazır.
    2. İSTİSNA MƏTNİ — `Employee 'Əliyev Elvin' not found`, e-poçt, telefon.
    3. SQL/URL PARAMETRLƏRİ — sorğu mətnində ID və ya ad qala bilər.

Ona görə hesabat OLDUĞU KİMİ göndərilmir: `scrub()` hər sətri təmizləyir.
Yanaşma "ağ siyahı" deyil, "aqressiv qara siyahı"dır — şübhəli fraqment
itirilir, çünki bir stack sətrinin oxunmaması bir işçi adının sızmasından
qat-qat ucuzdur.

──────────────────────────────────────────────────────────────────────────────
BARMAQ İZİ MƏTNDƏN DEYİL, ÇƏRÇİVƏLƏRDƏN HESABLANIR
──────────────────────────────────────────────────────────────────────────────
`fingerprint` eyni bug-ın təkrarlarını qruplaşdırmalıdır. İstisna MƏTNİ
istifadə edilsəydi, `Employee 42 not found` və `Employee 43 not found` iki
FƏRQLİ qrup yaradardı və panel eyni bug-ı yüzlərlə sətir kimi göstərərdi.
Ona görə barmaq izi yalnız (istisna tipi + fayl/funksiya/sətir zənciri)
üzərindən hesablanır — dəyərlər ona təsir etmir.

──────────────────────────────────────────────────────────────────────────────
SÜRƏT LİMİTİ — CRASH DÖVRÜ ŞƏBƏKƏNİ YIXMAMALIDIR
──────────────────────────────────────────────────────────────────────────────
Bir dövrə düşmüş xəta saniyədə yüzlərlə hesabat yarada bilər. Eyni barmaq izi
üçün sessiyada `MAX_REPORTS_PER_FINGERPRINT` hesabatdan sonra göndəriş dayanır
— bug artıq görünüb, təkrarların əlavə məlumat dəyəri yoxdur.
"""

from __future__ import annotations

import hashlib
import platform
import re
import threading
import traceback
from typing import TYPE_CHECKING, Any, Final

from src.domain.value_objects.licensing import CrashReport, anonymous_tenant_ref
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from types import TracebackType

    from src.domain.value_objects.identifiers import TenantId

_log = get_logger(__name__)
_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Eyni barmaq izi üçün bir sessiyada göndərilən maksimum hesabat.
MAX_REPORTS_PER_FINGERPRINT: Final[int] = 3
#: Barmaq izinə daxil olan ən dərin çərçivə sayı. Çox olsa, eyni bug fərqli
#: çağırış yollarından gəldikdə ayrı qruplara bölünərdi.
FINGERPRINT_FRAMES: Final[int] = 5
#: Göndərilən trace-in maksimum uzunluğu — DB sətrini şişirtməsin.
MAX_TRACE_CHARS: Final[int] = 8_000

_REDACTED: Final[str] = "<gizlədilib>"

#: İstifadəçi qovluğu: `C:\\Users\\Elvin\\`, `/home/elvin/`, `/Users/elvin/`.
_HOME_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"([A-Za-z]:[\\/]+Users[\\/]+)[^\\/\s\"']+", re.IGNORECASE),
    re.compile(r"(/home/)[^/\s\"']+"),
    re.compile(r"(/Users/)[^/\s\"']+"),
)
_EMAIL_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^\s<>\"']+@[^\s<>\"']+\.[A-Za-z]{2,}")
#: 4+ rəqəmli ardıcıllıq: PIN, telefon, kart, tabel nömrəsi.
_LONG_DIGITS: Final[re.Pattern[str]] = re.compile(r"\b\d{4,}\b")
#: UUID — tenant/işçi identifikatoru ola bilər.
_UUID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)


def scrub(text: str) -> str:
    """Mətndən şəxsi məlumatı çıxarır (bax modul başlığı)."""
    cleaned = text
    for pattern in _HOME_PATTERNS:
        cleaned = pattern.sub(rf"\1{_REDACTED}", cleaned)
    cleaned = _EMAIL_PATTERN.sub(_REDACTED, cleaned)
    cleaned = _UUID_PATTERN.sub(_REDACTED, cleaned)
    return _LONG_DIGITS.sub(_REDACTED, cleaned)


def fingerprint_of(exc_type: type[BaseException], tb: TracebackType | None) -> str:
    """Eyni bug-ın təkrarlarını qruplaşdıran sabit açar."""
    frames = traceback.extract_tb(tb)[-FINGERPRINT_FRAMES:] if tb else []
    parts = [exc_type.__name__]
    parts.extend(f"{_module_of(frame.filename)}:{frame.name}:{frame.lineno}" for frame in frames)
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def format_trace(
    exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
) -> str:
    """Təmizlənmiş, qısaldılmış stack-trace."""
    raw = "".join(traceback.format_exception(exc_type, exc, tb))
    cleaned = scrub(raw)
    if len(cleaned) <= MAX_TRACE_CHARS:
        return cleaned
    # Baş VƏ son hissə saxlanılır: səbəb yuxarıda, düşmə nöqtəsi aşağıdadır.
    head = cleaned[: MAX_TRACE_CHARS // 2]
    tail = cleaned[-MAX_TRACE_CHARS // 2 :]
    return f"{head}\n... [{len(cleaned) - MAX_TRACE_CHARS} simvol kəsildi] ...\n{tail}"


class CrashReporter:
    """Handled/unhandled istisnaları anonim hesabata çevirir və göndərir.

    `sink` — `report_crash(CrashReport)` metodu olan obyekt (adətən
    `LicenseClient`). Port kimi ayrıca `Protocol` yazılmır: tələb olunan səth
    tək metoddur və `LicenseGateway` onu artıq təyin edir.
    """

    def __init__(
        self,
        sink: Any,
        *,
        tenant_id: TenantId,
        app_version: str,
        enabled: bool = True,
        max_per_fingerprint: int = MAX_REPORTS_PER_FINGERPRINT,
    ) -> None:
        self._sink = sink
        self._reference = anonymous_tenant_ref(tenant_id)
        self._app_version = app_version
        self._enabled = enabled
        self._max_per_fingerprint = max_per_fingerprint
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}
        self._os_version = _os_label()

    @property
    def app_version(self) -> str:
        return self._app_version

    @property
    def sent_fingerprints(self) -> dict[str, int]:
        """Diaqnostika üçün — hansı barmaq izi neçə dəfə göndərilib."""
        with self._lock:
            return dict(self._counts)

    def build(
        self, exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
    ) -> CrashReport:
        """Hesabatı qurur (göndərmir) — testdə məzmunu yoxlamaq üçün."""
        return CrashReport(
            anonymous_tenant_ref=self._reference,
            app_version=self._app_version,
            exception_type=exc_type.__name__,
            stack_trace=format_trace(exc_type, exc, tb),
            fingerprint=fingerprint_of(exc_type, tb),
            os_version=self._os_version,
        )

    def report(
        self,
        exc_type: type[BaseException],
        exc: BaseException,
        tb: TracebackType | None,
    ) -> bool:
        """Hesabatı göndərir. Qaytarır: göndərildimi.

        HEÇ VAXT XƏTA ATMIR: bu funksiya qlobal istisna hook-undan çağırılır,
        yəni burada atılan istisna proqramın çökmə mesajını da uda bilərdi.
        """
        if not self._enabled:
            return False
        try:
            report = self.build(exc_type, exc, tb)
        except Exception as exc_build:
            _log.debug("CRASH_REPORT_BUILD_FAILED", extra={"error": str(exc_build)})
            return False

        if not self._allow(report.fingerprint):
            return False

        try:
            self._sink.report_crash(report)
        except Exception as exc_send:
            _log.debug("CRASH_REPORT_SEND_FAILED", extra={"error": str(exc_send)})
            return False

        _log.info(
            "CRASH_REPORT_SENT",
            extra={"fingerprint": report.fingerprint, "exception_type": report.exception_type},
        )
        return True

    def report_exception(self, exc: BaseException) -> bool:
        """Tutulmuş (handled) istisna üçün qısa yol."""
        return self.report(type(exc), exc, exc.__traceback__)

    def _allow(self, fingerprint: str) -> bool:
        with self._lock:
            seen = self._counts.get(fingerprint, 0)
            if seen >= self._max_per_fingerprint:
                return False
            self._counts[fingerprint] = seen + 1
            first_over_limit = seen + 1 == self._max_per_fingerprint
        if first_over_limit:
            _log.info(
                "CRASH_REPORT_RATE_LIMITED",
                extra={"fingerprint": fingerprint, "limit": self._max_per_fingerprint},
            )
        return True

    def as_hook(self) -> Any:
        """`install_global_exception_hook(on_crash=...)` üçün callable."""

        def _on_crash(
            exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
        ) -> None:
            self.report(exc_type, exc, tb)

        return _on_crash


def _module_of(filename: str) -> str:
    """Fayl yolunu layihəyə nisbi, PII-siz forma salır.

    Tam yol göndərilsəydi barmaq izi maşından maşına dəyişərdi (fərqli
    quraşdırma qovluqları) və eyni bug hər müştəridə ayrı qrup yaradardı.
    """
    normalized = filename.replace("\\", "/")
    marker = "/src/"
    if marker in normalized:
        return "src/" + normalized.split(marker, 1)[1]
    return normalized.rsplit("/", 1)[-1]


def _os_label() -> str:
    """PII-siz OS etiketi — versiya var, maşın/istifadəçi adı YOXDUR."""
    try:
        return f"{platform.system()} {platform.release()}"
    except Exception:
        return ""


def install_crash_reporting(reporter: CrashReporter) -> None:
    """Qlobal istisna hook-unu bu hesabatçıya bağlayır."""
    from src.shared.logger import install_global_exception_hook  # noqa: PLC0415

    install_global_exception_hook(on_crash=reporter.as_hook())
    _error_log.info("CRASH_REPORTING_INSTALLED", extra={"app_version": reporter.app_version})


__all__ = [
    "FINGERPRINT_FRAMES",
    "MAX_REPORTS_PER_FINGERPRINT",
    "MAX_TRACE_CHARS",
    "CrashReporter",
    "fingerprint_of",
    "format_trace",
    "install_crash_reporting",
    "scrub",
]
