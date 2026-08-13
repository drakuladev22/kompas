"""Yeniləmə paketinin doğrulanması: SHA-256 + Authenticode — Faza 3.13.

Spesifikasiya bölmə 1: *"`.exe` **Authenticode ilə imzalanmalıdır**"*.
Faza 3, bənd 6: *"yeni versiyanı yükləyib Authenticode imzasını doğrulayaraq
tətbiq edir"*.

──────────────────────────────────────────────────────────────────────────────
İKİ AYRI YOXLAMA, İKİ AYRI SUAL
──────────────────────────────────────────────────────────────────────────────
    SHA-256       "yüklənən baytlar kataloqdakı ilə eynidirmi?"
                  → yükləmə səhvini, kəsilmiş faylı tutur
    Authenticode  "bu faylı BİZ imzalamışıqmı?"
                  → əvəzlənmiş faylı, uydurma buraxılışı tutur

Yalnız SHA-256 kifayət DEYİL: kataloq sətrini dəyişdirə bilən hücumçu həm
faylı, həm də onun hash-ını eyni anda dəyişər. Authenticode isə xüsusi açar
tələb edir — kataloqa yazma icazəsi onu vermir.

Yalnız Authenticode da kifayət deyil: imza etibarlı, lakin fayl KÖHNƏ
buraxılış ola bilər (replay). Versiya + hash uyğunluğu bunu bağlayır.

──────────────────────────────────────────────────────────────────────────────
SIRA: ƏVVƏLCƏ HASH, SONRA İMZA
──────────────────────────────────────────────────────────────────────────────
Hash yoxlaması ucuzdur və xarici proses işə salmır. Kəsilmiş yükləməni orada
tutmaq, zədələnmiş baytları imza yoxlayıcısına ötürməkdən yaxşıdır.

──────────────────────────────────────────────────────────────────────────────
FAIL-CLOSED: YOXLAYA BİLMİRSƏNSƏ, TƏTBİQ ETMƏ
──────────────────────────────────────────────────────────────────────────────
PowerShell yoxdursa, əmr timeout-a düşürsə, cavab tanınmırsa — nəticə
"etibarlı" DEYİL, `SignatureRejectedError`-dur. Yenilənməmək təhlükəsiz
vəziyyətdir (köhnə versiya işləyir); doğrulanmamış `.exe` icra etmək isə
hər kassa PC-sində ixtiyari kod deməkdir.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from typing import TYPE_CHECKING, Final

from src.domain.policies import SystemLimitKey
from src.domain.value_objects.updates import (
    ChecksumMismatchError,
    SignatureRejectedError,
)
from src.infrastructure.config.limits import InfrastructureLimits, fallback_float
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

CHUNK_SIZE: Final[int] = 1024 * 1024
#: İmza yoxlaması bu müddətdən uzun çəkərsə uğursuz sayılır. Yoxlama yerli
#: əməliyyatdır; uzanması ancaq bir problem əlamətidir (məs. şəbəkə üzərindən
#: CRL sorğusunun asılıb qalması).
#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`UPDATE_VERIFY_TIMEOUT_SECONDS`, seed: migrations/032). Zəif kiosk PC-də
#: PowerShell-in soyuq başlanğıcı tək başına saniyələr çəkir.
FALLBACK_VERIFY_TIMEOUT_SECONDS: Final[float] = fallback_float(
    SystemLimitKey.UPDATE_VERIFY_TIMEOUT_SECONDS
)

#: `Get-AuthenticodeSignature` yalnız bu statusu etibarlı sayır.
VALID_STATUS: Final[str] = "Valid"

#: Yoxlanacaq fayl yolu ƏMR SƏTRİNDƏ DEYİL, mühit dəyişənində ötürülür.
#:
#: Səbəb: `powershell -Command "<skript>" <arqument>` çağırışında arqumentlər
#: `$args`-a DÜŞMÜR — powershell.exe onları əmr mətninə birləşdirir. Yolu
#: birbaşa skriptə yapışdırmaq isə sitat/kəsr problemi yaradır (Windows fayl
#: adında `'`, `$`, `` ` `` ola bilər). Mühit dəyişəni hər iki problemi
#: aradan qaldırır və inyeksiya səthini tamamilə bağlayır.
VERIFY_PATH_ENV: Final[str] = "KOMPASOS_VERIFY_PATH"

#: `-NoProfile` VACİBDİR: istifadəçi profili skript yükləyə və çıxışı poza bilər.
_PS_SCRIPT: Final[str] = (
    "$ErrorActionPreference='Stop';"
    "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
    "$s = Get-AuthenticodeSignature -LiteralPath $env:KOMPASOS_VERIFY_PATH;"
    "$subject = ''; $thumb = '';"
    "if ($null -ne $s.SignerCertificate) "
    "{ $subject = $s.SignerCertificate.Subject; $thumb = $s.SignerCertificate.Thumbprint };"
    "@{status=$s.Status.ToString(); subject=$subject; thumbprint=$thumb} | "
    "ConvertTo-Json -Compress"
)


def file_sha256(path: Path) -> str:
    """Faylın SHA-256 daycesti (böyük fayllar üçün hissə-hissə)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksum(path: Path, expected: str) -> None:
    """SHA-256 uyğunluğunu yoxlayır. Uyğunsuzluqda `ChecksumMismatchError`."""
    actual = file_sha256(path)
    if actual.lower() != expected.lower():
        _security_log.warning(
            "UPDATE_CHECKSUM_MISMATCH",
            extra={
                "expected": expected.lower(),
                "actual": actual,
                "file": path.name,
                "impact": "yenilənmə tətbiq edilmir",
            },
        )
        raise ChecksumMismatchError(
            "Yüklənən faylın SHA-256 dəyəri uyğun gəlmir",
            context={"expected": expected.lower(), "actual": actual},
        )


class AuthenticodeVerifier:
    """Windows Authenticode imzasını yoxlayır.

    Yanaşma: `powershell -NoProfile Get-AuthenticodeSignature`. Səbəb —
    `WinVerifyTrust` üçün `ctypes` ilə struktur qurmaq (WINTRUST_DATA,
    WINTRUST_FILE_INFO, GUID) onlarla sətir platformadan-asılı kod tələb edir
    və bir sahə səhvi SÜKUTLA "etibarlıdır" nəticəsi verə bilər. PowerShell
    cmdlet-i eyni API-ni çağırır, lakin nəticəni açıq, oxunaqlı statusla verir.

    `expected_subject` — naşirin sertifikat mövzusundan bir fraqment (məs.
    `"O=Kompas MMC"`). Bu OLMASA, İSTƏNİLƏN etibarlı imza qəbul edilərdi: bir
    hücumçu öz (tamamilə qanuni) kod-imzalama sertifikatı ilə imzalanmış faylı
    yerləşdirə bilərdi və yoxlama onu "Valid" sayardı.
    """

    def __init__(
        self,
        *,
        expected_subject: str = "",
        runner: Callable[[Sequence[str], Mapping[str, str]], subprocess.CompletedProcess[str]]
        | None = None,
        timeout_seconds: float | None = None,
        limits: InfrastructureLimits | None = None,
    ) -> None:
        """
        Args:
            timeout_seconds: AÇIQ üstünlük — verilərsə ROOT dəyəri OXUNMUR.
            limits: `system_limits`-ə açılan pəncərə; verilməzsə fallback.
        """
        self._expected_subject = expected_subject.strip()
        self._runner = runner
        self._explicit_timeout = timeout_seconds
        self._limits = limits or InfrastructureLimits()

    def _timeout(self) -> float:
        """Yoxlama taymautu — HƏR ÇAĞIRIŞDA oxunur (yoxlayıcı uzun ömürlüdür)."""
        if self._explicit_timeout is not None:
            return self._explicit_timeout
        return self._limits.float_of(SystemLimitKey.UPDATE_VERIFY_TIMEOUT_SECONDS)

    @property
    def is_supported(self) -> bool:
        """Bu platformada Authenticode ümumiyyətlə mövcuddurmu."""
        return self._runner is not None or platform.system() == "Windows"

    def verify(self, path: Path) -> str:
        """İmzanı yoxlayır və naşirin mövzusunu qaytarır.

        Raises:
            SignatureRejectedError: imza yoxdur, etibarsızdır, naşir
                gözlənilən deyil, VƏ YA yoxlama ümumiyyətlə icra edilə bilmədi.
        """
        if not self.is_supported:
            # Fail-closed: yoxlaya bilmirsənsə, tətbiq etmə (bax modul başlığı).
            raise SignatureRejectedError(
                "Authenticode yoxlaması bu platformada mümkün deyil",
                context={"platform": platform.system()},
            )

        payload = self._run(path)
        status = str(payload.get("status", "")).strip()
        subject = str(payload.get("subject", "")).strip()
        thumbprint = str(payload.get("thumbprint", "")).strip()

        if status != VALID_STATUS:
            self._reject(path, reason=f"status={status or 'naməlum'}", subject=subject)

        if self._expected_subject and self._expected_subject.lower() not in subject.lower():
            self._reject(path, reason="naşir gözlənilən deyil", subject=subject)

        _security_log.info(
            "UPDATE_SIGNATURE_VERIFIED",
            extra={"file": path.name, "subject": subject, "thumbprint": thumbprint},
        )
        return subject

    # ------------------------------- daxili ---------------------------------- #

    def _run(self, path: Path) -> dict[str, object]:
        command = ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_SCRIPT]
        environment = {**os.environ, VERIFY_PATH_ENV: str(path)}
        runner = self._runner or self._default_runner
        try:
            completed = runner(command, environment)
        except subprocess.TimeoutExpired as exc:
            self._reject(path, reason="yoxlama vaxtı bitdi", subject="", cause=exc)
        except OSError as exc:
            self._reject(path, reason="yoxlama icra edilə bilmədi", subject="", cause=exc)

        if completed.returncode != 0:
            self._reject(
                path,
                reason=f"yoxlayıcı xəta qaytardı (kod {completed.returncode})",
                subject="",
            )

        try:
            parsed = json.loads(completed.stdout or "{}")
        except ValueError as exc:
            self._reject(path, reason="yoxlayıcının cavabı oxunmadı", subject="", cause=exc)

        if not isinstance(parsed, dict):
            self._reject(path, reason="yoxlayıcının cavabı gözlənilən formatda deyil", subject="")
        return {str(key): value for key, value in parsed.items()}

    def _default_runner(
        self, command: Sequence[str], environment: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 — əmr TAM SABİTDİR; dəyişən yalnız env-dədir
            list(command),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self._timeout(),
            check=False,
            env=dict(environment),
        )

    def _reject(
        self,
        path: Path,
        *,
        reason: str,
        subject: str,
        cause: BaseException | None = None,
    ) -> None:
        _security_log.critical(
            "UPDATE_SIGNATURE_REJECTED",
            extra={
                "file": path.name,
                "reason": reason,
                "subject": subject,
                "expected_subject": self._expected_subject,
                "impact": "yenilənmə tətbiq edilmir — cari versiya qalır",
            },
        )
        error = SignatureRejectedError(
            f"Authenticode imzası qəbul edilmədi: {reason}",
            context={"file": path.name, "reason": reason, "subject": subject},
        )
        if cause is not None:
            raise error from cause
        raise error


def verify_package(
    path: Path,
    *,
    expected_sha256: str,
    verifier: AuthenticodeVerifier,
) -> str:
    """Tam doğrulama: əvvəlcə hash, sonra imza (bax modul başlığı)."""
    verify_checksum(path, expected_sha256)
    subject = verifier.verify(path)
    _log.info("UPDATE_PACKAGE_VERIFIED", extra={"file": path.name})
    return subject


__all__ = [
    "FALLBACK_VERIFY_TIMEOUT_SECONDS",
    "VALID_STATUS",
    "AuthenticodeVerifier",
    "file_sha256",
    "verify_checksum",
    "verify_package",
]
