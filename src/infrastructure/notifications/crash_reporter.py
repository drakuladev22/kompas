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

from src.domain.policies import SystemLimitKey
from src.domain.value_objects.licensing import CrashReport, anonymous_tenant_ref
from src.infrastructure.config.limits import InfrastructureLimits, fallback_int
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from types import TracebackType

    from src.domain.value_objects.identifiers import TenantId

_log = get_logger(__name__)
_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Eyni barmaq izi üçün bir sessiyada göndərilən maksimum hesabat.
#:
#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`CRASH_MAX_REPORTS_PER_FINGERPRINT`, seed: migrations/032). Diaqnostika
#: dövründə hazırlayıcı eyni çökmənin daha çox nüsxəsini görmək istəyə bilər;
#: sabit 3 bunu yalnız yeni buraxılışla mümkün edərdi.
FALLBACK_MAX_REPORTS_PER_FINGERPRINT: Final[int] = fallback_int(
    SystemLimitKey.CRASH_MAX_REPORTS_PER_FINGERPRINT
)
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

# ─────────────────────────────────────────────────────────────────────────── #
# SEC-03 (dövrə 3 audit) — SIRR nümunələri, `security`-nin siyahısı
# ─────────────────────────────────────────────────────────────────────────── #
#
# NİYƏ AYRI QRUP: yuxarıdakı naxışlar İSTİFADƏÇİ (PII) məlumatını gizlədir —
# bunlar isə SİSTEM sirlərini (DSN parolu, bot token-i, OAuth açarı). Fərq
# sadəcə terminologiya deyil: PII sızması gizlilik pozuntusudur, sirr sızması
# isə DƏRHAL BAŞQA sistemlərə (baza, Telegram, Google) giriş deməkdir — ona
# görə bu qrup HƏMİŞƏ `_LONG_DIGITS`-dən (aşağıdakı `scrub()`) ƏVVƏL işə
# düşməlidir: Telegram bot token-i (`123456789:AAF...`) rəqəm PREFİKSİ ilə
# başlayır — `_LONG_DIGITS` birinci işləsəydi YALNIZ rəqəm hissəsini
# gizlədərdi, `:AAF...`-dən sonrakı 35 simvollıq HƏQİQİ sirr AÇIQ QALARDI.
#
# FERNET AÇARI QƏSDƏN BURADA YOXDUR: heç bir kod yolu onu mətnə interpolyasiya
# etmir (`EncryptionService` açarı yalnız bayt kimi, birbaşa `Fernet`/AESGCM
# konstruktoruna ötürür — `str()`/f-string-ə heç vaxt düşmür), yəni stack-trace
# ONU DAŞIYA BİLMƏZ; nümunə əlavə etmək YALANÇI TƏHLÜKƏSİZLİK hissi verərdi.
#
# BÜTÜN nümunələrdə YALNIZ SİRR hissəsi redaksiya olunur, ƏTRAF KONTEKST
# (host, sxem, "authorization:" prefiksi, açar adı) QALIR — `_redact_captured`
# HƏR pattern-in TƏK `(...)` qrupunu əvəz edir. Diaqnostik dəyər itməsin deyə:
# "hansı DSN-ə qoşulmağa çalışırdı" sualının cavabı (host/db) itməməlidir,
# yalnız "hansı PAROLLA" sualı cavabsız qalmalıdır.

#: 1 (ƏN VACİB): DSN-lərin ümumi forması — `postgresql://user:PAROL@host/db`.
_DSN_PASSWORD_PATTERN: Final[re.Pattern[str]] = re.compile(r"://[^/\s:@]+:([^@\s]+)@")
#: 2: libpq conninfo boşluqlu forması — `host=... password=PAROL sslmode=...`.
_LIBPQ_PASSWORD_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?i)password=(\S+)")
#: 3: Telegram bot token-i — `bot_id:secret` (SEC-028/029, `telegram.py`).
_TELEGRAM_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\b\d{6,10}:[A-Za-z0-9_-]{35}\b")
#: 4: Google OAuth (Drive inteqrasiyası, `storage/oauth_flow.py`) — access VƏ
#: refresh token formatları FƏRQLİDİR, ikisi də lazımdır.
_GOOGLE_ACCESS_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\bya29\.[0-9A-Za-z_-]+\b")
_GOOGLE_REFRESH_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\b1//[0-9A-Za-z_-]+\b")
#: 5: HTTP Authorization başlığı — Supabase/ERP REST çağırışlarında (bir çox
#: HTTP klienti istisna mətninə SORĞU başlıqlarını da qatır).
#:
#: `security`-nin verdiyi ilkin nümunə (`authorization:\s*\S+`) CANLI
#: sınaqda BUG çıxardı: "Authorization: Bearer eyJ...sig" mətnində `\S+`
#: YALNIZ "Bearer" sözünü tutur (boşluqdan SONRAKI həqiqi token TUTULMUR) —
#: nəticə "authorization: <gizlədilib> eyJ...sig" olurdu, yəni SIRRİN ÖZÜ
#: AÇIQ QALIRDI. Düzəliş: `.+` (sətir sonuna qədər) — "authorization:"-dan
#: sonra HƏR ZAMAN sirr gəlir, sxem sözü ilə token arasında xətt çəkməyin
#: MƏNASI yoxdur (aqressiv qara siyahı fəlsəfəsi). SIRA da MÜHÜMDÜR:
#: `_BEARER_TOKEN_PATTERN` BURADAN ƏVVƏL işləyir ki, "Bearer xyz" TƏK
#: uyğunluq kimi tutulsun — sonra bu pattern "authorization: <gizlədilib>"
#: qalığına dəyəndə artıq redaksiya olunmuş yer-tutucunu YENİDƏN
#: redaksiya edir (zərərsiz, no-op).
_AUTHORIZATION_HEADER_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?i)authorization:\s*(.+)")
_BEARER_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?i)\bBearer\s+([A-Za-z0-9\-_.]+)\b")
#: 6: ÜMUMİ açar=dəyər toru — yuxarıdakı XÜSUSİ formatların HEÇ BİRİNƏ
#: uymayan, amma açar ADINDAN sirr olduğu bəlli olan hallar üçün son sərhəd
#: (dict `repr()`-i, validasiya mesajı, s.). Açıq özəllik: "aqressiv qara
#: siyahı" fəlsəfəsinin (modul başlığı) HƏRFİ tətbiqidir.
_GENERIC_SECRET_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:password|pwd|secret|token|api[_-]?key|client_secret)\s*[:=]\s*(\S+)"
)
#: 7: Argon2id heşi (PIN/şifrə, `HashingService`) — pepper-lə qorunsa da,
#: heşin ÖZÜ leaked olanda offline hücumun BİRİNCİ girişi olur.
_ARGON2_HASH_PATTERN: Final[re.Pattern[str]] = re.compile(r"\$argon2id\$v=\d+\$\S+")

#: `(pattern, tam_uyğunluq_sirrdir_mi)` — İKİNCİ True olanda BÜTÜN uyğunluq
#: (`(...)` qrupu YOX) redaksiya olunur: bu nümunələrdə saxlanacaq "ətraf
#: kontekst" YOXDUR (bot ID-si tək başına mənasızdır, Argon2 prefiksi
#: "bura heş var" deməkdən başqa məlumat vermir).
_SECRET_PATTERNS: Final[tuple[tuple[re.Pattern[str], bool], ...]] = (
    (_DSN_PASSWORD_PATTERN, False),
    (_LIBPQ_PASSWORD_PATTERN, False),
    (_TELEGRAM_TOKEN_PATTERN, True),
    (_GOOGLE_ACCESS_TOKEN_PATTERN, True),
    (_GOOGLE_REFRESH_TOKEN_PATTERN, True),
    # `_BEARER_TOKEN_PATTERN` `_AUTHORIZATION_HEADER_PATTERN`-DƏN ƏVVƏL —
    # sıra ŞƏRTDİR, bax `_AUTHORIZATION_HEADER_PATTERN` şərhi.
    (_BEARER_TOKEN_PATTERN, False),
    (_AUTHORIZATION_HEADER_PATTERN, False),
    (_GENERIC_SECRET_PATTERN, False),
    (_ARGON2_HASH_PATTERN, True),
)


def _redact_captured(pattern: re.Pattern[str], text: str) -> str:
    """`pattern`-in TƏK `(...)` qrupunu `_REDACTED`-lə əvəz edir, QALANINI SAXLAYIR.

    Sadə `pattern.sub(_REDACTED, text)` BÜTÜN uyğunluğu (qrupdan KƏNAR
    kontekst daxil) itirərdi — DSN-də bu, host/sxem kimi DİAQNOSTİK dəyəri
    silərdi (həddindən artıq təmizləmə, modul başlığının xəbərdarlıq etdiyi
    ikinci qüsur növü). Mövqe əsaslı əvəzləmə (`str.replace` YOX) təkrarlanan
    alt-sətir problemi yaratmır.
    """

    def _replace(match: re.Match[str]) -> str:
        start, end = match.span(1)
        full = match.group(0)
        offset = match.start(0)
        return full[: start - offset] + _REDACTED + full[end - offset :]

    return pattern.sub(_replace, text)


def scrub(text: str) -> str:
    """Mətndən şəxsi məlumatı VƏ SİRRİ çıxarır (bax modul başlığı, SEC-03)."""
    cleaned = text
    # SİRRLƏR ƏVVƏLCƏ: `_LONG_DIGITS` rəqəm-prefiksli token-ləri (Telegram)
    # FRAQMENTLƏYƏRDİ (bax `_SECRET_PATTERNS` şərhi) — sıra TƏSADÜFİ deyil.
    for pattern, whole_match in _SECRET_PATTERNS:
        cleaned = (
            pattern.sub(_REDACTED, cleaned) if whole_match else _redact_captured(pattern, cleaned)
        )
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
        max_per_fingerprint: int | None = None,
        limits: InfrastructureLimits | None = None,
    ) -> None:
        """
        Args:
            max_per_fingerprint: AÇIQ üstünlük — verilərsə ROOT dəyəri OXUNMUR.
            limits: `system_limits`-ə açılan pəncərə; verilməzsə fallback.
        """
        self._sink = sink
        self._reference = anonymous_tenant_ref(tenant_id)
        self._app_version = app_version
        self._enabled = enabled
        self._explicit_max_per_fingerprint = max_per_fingerprint
        self._limits = limits or InfrastructureLimits()
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

    def _max_per_fingerprint(self) -> int:
        """Tavan — HƏR ÇÖKMƏDƏ oxunur (reporter tətbiqin ömrü boyu yaşayır)."""
        if self._explicit_max_per_fingerprint is not None:
            return self._explicit_max_per_fingerprint
        return self._limits.int_of(SystemLimitKey.CRASH_MAX_REPORTS_PER_FINGERPRINT)

    def _allow(self, fingerprint: str) -> bool:
        limit = self._max_per_fingerprint()
        with self._lock:
            seen = self._counts.get(fingerprint, 0)
            if seen >= limit:
                return False
            self._counts[fingerprint] = seen + 1
            first_over_limit = seen + 1 == limit
        if first_over_limit:
            _log.info(
                "CRASH_REPORT_RATE_LIMITED",
                extra={"fingerprint": fingerprint, "limit": limit},
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
    "FALLBACK_MAX_REPORTS_PER_FINGERPRINT",
    "FINGERPRINT_FRAMES",
    "MAX_TRACE_CHARS",
    "CrashReporter",
    "fingerprint_of",
    "format_trace",
    "install_crash_reporting",
    "scrub",
]
