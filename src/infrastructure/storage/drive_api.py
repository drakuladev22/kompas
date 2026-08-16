"""Google Drive API v3 üçün minimal klient — Faza 3.9.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `google-api-python-client` DEYİL
──────────────────────────────────────────────────────────────────────────────
Rəsmi kitabxana özü ilə `google-auth`, `google-api-core`, `protobuf`,
`googleapis-common-protos` və daha bir neçə paket gətirir — bu, imzalanmış
Windows `.exe` üçün ~20 MB artıq yük və xeyli genişlənmiş tədarük zənciri
səthi deməkdir. Bizə lazım olan cəmi 6 REST çağırışıdır və `httpx` onsuz da
layihənin asılılığıdır. Eyni əsaslandırma SNTP klientində də tətbiq olunub
(bax `timekeeping/ntp.py`).

──────────────────────────────────────────────────────────────────────────────
TOKEN İDARƏSİ
──────────────────────────────────────────────────────────────────────────────
Yalnız `refresh_token` saxlanılır (DB-də AES-256-GCM ilə şifrəli). Access
token yaddaşda, bitmə vaxtı ilə birlikdə keşlənir və 60 saniyə ehtiyatla
əvvəlcədən yenilənir — sorğunun ortasında bitməsin.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Final

import httpx

from src.domain.policies import SystemLimitKey
from src.domain.value_objects.storage import QuotaStatus, StorageError
from src.infrastructure.config.limits import (
    InfrastructureLimits,
    fallback_float,
    fallback_int,
)
from src.shared.logger import LogChannel, get_logger

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

# `noqa: S105` — bu, URL-dir, sirr deyil (linter adda "TOKEN" görür).
TOKEN_ENDPOINT: Final[str] = "https://oauth2.googleapis.com/token"  # noqa: S105
DRIVE_API: Final[str] = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_API: Final[str] = "https://www.googleapis.com/upload/drive/v3"
FOLDER_MIME: Final[str] = "application/vnd.google-apps.folder"

#: ÜÇÜ DƏ FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`DRIVE_TOKEN_REFRESH_MARGIN_SECONDS`, `DRIVE_REQUEST_TIMEOUT_SECONDS`,
#: `DRIVE_MAX_RETRIES`; seed: migrations/032). Mağazanın internet kanalı
#: (ADSL, mobil modem, korporativ proxy) bu üç dəyərin doğru seçimini təyin
#: edir — sabit ədədlər zəif kanalda hər sübut şəklinin yüklənməsini
#: uğursuz edərdi.
#:
#: Access token bitməmişdən bu qədər əvvəl yenilənir.
FALLBACK_TOKEN_REFRESH_MARGIN_SECONDS: Final[int] = fallback_int(
    SystemLimitKey.DRIVE_TOKEN_REFRESH_MARGIN_SECONDS
)
FALLBACK_TIMEOUT_SECONDS: Final[float] = fallback_float(
    SystemLimitKey.DRIVE_REQUEST_TIMEOUT_SECONDS
)
#: Drive API istifadəçi başına ~100 sorğu/100 saniyə verir; 429/5xx-də
#: eksponensial gözləmə ilə təkrar cəhd olunur. STATUS SİYAHISI KÖÇÜRÜLMÜR:
#: bunlar HTTP standart kodlarıdır, siyasət deyil.
RETRY_STATUS: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})
FALLBACK_MAX_RETRIES: Final[int] = fallback_int(SystemLimitKey.DRIVE_MAX_RETRIES)
HTTP_UNAUTHORIZED: Final[int] = 401
HTTP_NOT_FOUND: Final[int] = 404


class DriveApiError(StorageError):
    """Drive API çağırışı uğursuz oldu."""


class DriveQuotaExceededError(DriveApiError):
    """Hesabda yer qalmayıb."""

    user_message = "Google Drive hesabında yer qalmayıb — administratorla əlaqə saxlayın."


class DriveConsentRevokedError(DriveApiError):
    """İstifadəçi Google-da razılığı GERİ ALIB — refresh token artıq işləmir.

    NİYƏ AYRICA İSTİSNA: adi `DriveApiError` «şəbəkə/API problemi» deməkdir və
    ona qarşı düzgün reaksiya GÖZLƏMƏK, sonra yenidən cəhd etməkdir. Razılıq
    ləğvi isə heç vaxt öz-özünə keçmir — administrator hesabı YENİDƏN
    qoşmalıdır. İkisini bir istisnada birləşdirsəydik, sistem əbədi olaraq
    «bir azdan yenə cəhd edərəm» vəziyyətində qalar və ekranda bağlantı hələ də
    «Aktiv» görünərdi (bax `DriveConnectionStatus.REVOKED`).
    """

    user_message = (
        "Google Drive icazəsi ləğv edilib — Ayarlar → Drive Bağlantısı "
        "bölməsindən hesabı yenidən qoşun."
    )


#: Google OAuth token endpoint-inin razılıq-ləğvi kodu (RFC 6749 §5.2).
#: Eyni kod «token vaxtı bitib/silinib» halında da qayıdır — praktik nəticə
#: EYNİDİR: bu refresh token bir daha işləməyəcək.
OAUTH_REVOKED_ERROR_CODE: Final[str] = "invalid_grant"


@dataclass(frozen=True)
class OAuthClient:
    """Google Cloud layihəsinin OAuth klient məlumatları.

    Bunlar TENANT-a deyil, TƏTBİQƏ aiddir (bir Google Cloud layihəsi, hər
    tenant öz hesabı ilə razılıq verir) — ona görə DB-də deyil, mühit
    dəyişənlərində saxlanılır.
    """

    client_id: str
    client_secret: str


class DriveApiClient:
    """Bir Drive hesabı üçün nazik REST örtüyü. Thread-safe."""

    def __init__(
        self,
        *,
        oauth: OAuthClient,
        refresh_token: str,
        transport: httpx.Client | None = None,
        timeout: float | None = None,
        limits: InfrastructureLimits | None = None,
    ) -> None:
        """
        Args:
            timeout: AÇIQ üstünlük — verilərsə ROOT dəyəri OXUNMUR.
            limits: `system_limits`-ə açılan pəncərə; verilməzsə fallback-lar.

        HTTP taymautu BURADA həll olunur, çünki `httpx.Client` onu sonradan
        qəbul etmir. Klient Drive bağlantısı ilə birlikdə yenidən qurulur
        (`composition.drive_providers` dəyər dəyişəndə fabriki atır), yəni
        ROOT dəyişikliyi növbəti fabrikdə qüvvəyə minir. Token marjası və
        təkrar cəhd sayı isə HƏR SORĞUDA oxunur.
        """
        self._oauth = oauth
        self._refresh_token = refresh_token
        self._limits = limits or InfrastructureLimits()
        self._http = transport or httpx.Client(
            timeout=timeout
            if timeout is not None
            else self._limits.float_of(SystemLimitKey.DRIVE_REQUEST_TIMEOUT_SECONDS)
        )
        self._owns_transport = transport is None
        self._lock = threading.Lock()
        self._access_token: str | None = None
        self._expires_at: float = 0.0

    def close(self) -> None:
        if self._owns_transport:
            self._http.close()

    # ------------------------------- token ----------------------------------- #

    def _token(self) -> str:
        with self._lock:
            if self._access_token and time.monotonic() < self._expires_at:
                return self._access_token
            response = self._http.post(
                TOKEN_ENDPOINT,
                data={
                    "client_id": self._oauth.client_id,
                    "client_secret": self._oauth.client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            if response.status_code != httpx.codes.OK:
                # Token mətnini LOGA YAZMIRIQ — cavabda sirr ola bilər.
                _security_log.error(
                    "DRIVE_TOKEN_REFRESH_FAILED",
                    extra={"status_code": response.status_code},
                )
                # RAZILIQ LƏĞVİ AYRICA TANINIR: Google `invalid_grant` məhz
                # refresh token geri alındıqda (və ya silindikdə) qaytarır. Bu,
                # təkrar cəhdlə keçən bir nasazlıq DEYİL — bağlantı `REVOKED`
                # işarələnməli və administrator xəbərdar edilməlidir, əks halda
                # ekran «Aktiv» göstərməyə davam edər (bax `quota_monitor`).
                # Kod cavabın GÖVDƏSİNDƏDİR, status kodunda yox: Google onu
                # HTTP 400 ilə qaytarır, yəni yalnız statusa baxmaq kifayət etmir.
                if _is_revoked_grant(response):
                    raise DriveConsentRevokedError(
                        "Google razılığı geri alınıb (invalid_grant)",
                        context={"status_code": response.status_code},
                    )
                raise DriveApiError(
                    f"Access token alınmadı (HTTP {response.status_code})",
                    user_message="Google Drive bağlantısı bərpa edilməlidir.",
                )
            payload = response.json()
            self._access_token = str(payload["access_token"])
            self._expires_at = (
                time.monotonic()
                + int(payload.get("expires_in", 3600))
                - self._limits.int_of(SystemLimitKey.DRIVE_TOKEN_REFRESH_MARGIN_SECONDS)
            )
            return self._access_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}"}

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Token yeniləmə + 429/5xx üçün təkrar cəhd."""
        last_error = ""
        max_retries = self._limits.int_of(SystemLimitKey.DRIVE_MAX_RETRIES)
        for attempt in range(max_retries):
            headers = {**self._headers(), **kwargs.pop("headers", {})}
            response = self._http.request(method, url, headers=headers, **kwargs)

            if response.status_code == HTTP_UNAUTHORIZED:
                # Token vaxtından əvvəl etibarsız oldu (məs. istifadəçi
                # razılığı ləğv etdi və ya yenidən verdi) — bir dəfə yenilə.
                with self._lock:
                    self._access_token = None
                    self._expires_at = 0.0
                last_error = "401 — token etibarsızdır"
                continue

            if response.status_code in RETRY_STATUS:
                delay = 2**attempt
                last_error = f"HTTP {response.status_code}"
                _log.warning(
                    "DRIVE_API_RETRY",
                    extra={
                        "status_code": response.status_code,
                        "attempt": attempt + 1,
                        "delay_seconds": delay,
                    },
                )
                time.sleep(delay)
                continue

            if response.status_code >= httpx.codes.BAD_REQUEST:
                self._raise_for_response(response)
            return response

        raise DriveApiError(f"Drive API cavab vermədi ({last_error})")

    @staticmethod
    def _raise_for_response(response: httpx.Response) -> None:
        try:
            reason = response.json().get("error", {}).get("message", response.text[:200])
        except (ValueError, json.JSONDecodeError):
            reason = response.text[:200]
        if "quota" in reason.lower() or "storage" in reason.lower():
            raise DriveQuotaExceededError(
                f"Drive kvotası: {reason}", context={"status_code": response.status_code}
            )
        raise DriveApiError(
            f"Drive API xətası (HTTP {response.status_code}): {reason}",
            context={"status_code": response.status_code},
        )

    # ------------------------------ qovluqlar --------------------------------- #

    def find_folder(self, name: str, *, parent_id: str | None = None) -> str | None:
        """Ada görə qovluq axtarır. Tapılmazsa `None`."""
        escaped = name.replace("\\", "\\\\").replace("'", "\\'")
        clauses = [
            f"name = '{escaped}'",
            f"mimeType = '{FOLDER_MIME}'",
            "trashed = false",
        ]
        clauses.append(f"'{parent_id}' in parents" if parent_id else "'root' in parents")
        response = self._request(
            "GET",
            f"{DRIVE_API}/files",
            params={
                "q": " and ".join(clauses),
                "fields": "files(id, name)",
                "pageSize": 1,
                "spaces": "drive",
            },
        )
        files = response.json().get("files", [])
        return str(files[0]["id"]) if files else None

    def create_folder(self, name: str, *, parent_id: str | None = None) -> str:
        body: dict[str, Any] = {"name": name, "mimeType": FOLDER_MIME}
        if parent_id:
            body["parents"] = [parent_id]
        response = self._request("POST", f"{DRIVE_API}/files", json=body, params={"fields": "id"})
        folder_id = str(response.json()["id"])
        _log.info("DRIVE_FOLDER_CREATED", extra={"name": name, "folder_id": folder_id})
        return folder_id

    def ensure_folder(self, name: str, *, parent_id: str | None = None) -> str:
        """Varsa tapır, yoxdursa yaradır."""
        existing = self.find_folder(name, parent_id=parent_id)
        return existing if existing else self.create_folder(name, parent_id=parent_id)

    # -------------------------------- fayllar --------------------------------- #

    def upload_file(
        self, *, filename: str, content: bytes, parent_id: str, mime_type: str = "image/jpeg"
    ) -> str:
        """Multipart yükləmə. Fayl PRIVATE qalır — heç bir paylaşım verilmir."""
        metadata = json.dumps({"name": filename, "parents": [parent_id]}, ensure_ascii=False)
        files = {
            "metadata": ("metadata.json", metadata, "application/json; charset=UTF-8"),
            "file": (filename, content, mime_type),
        }
        response = self._request(
            "POST",
            f"{DRIVE_UPLOAD_API}/files",
            params={"uploadType": "multipart", "fields": "id"},
            files=files,
        )
        file_id = str(response.json()["id"])
        _log.info(
            "DRIVE_FILE_UPLOADED",
            extra={"file_id": file_id, "bytes": len(content), "parent_id": parent_id},
        )
        return file_id

    def download_file(self, file_id: str) -> bytes:
        response = self._request("GET", f"{DRIVE_API}/files/{file_id}", params={"alt": "media"})
        return response.content

    def delete_file(self, file_id: str) -> bool:
        try:
            self._request("DELETE", f"{DRIVE_API}/files/{file_id}")
        except DriveApiError as exc:
            context = exc.context or {}
            if context.get("status_code") == HTTP_NOT_FOUND:
                # Artıq yoxdur — məqsədə çatılıb, xəta saymırıq.
                return False
            raise
        return True

    # -------------------------------- kvota ----------------------------------- #

    def quota(self) -> QuotaStatus:
        response = self._request("GET", f"{DRIVE_API}/about", params={"fields": "storageQuota"})
        raw = response.json().get("storageQuota", {})
        limit = raw.get("limit")
        return QuotaStatus(
            used_bytes=int(raw.get("usage", 0)),
            total_bytes=int(limit) if limit is not None else None,
        )

    def account_email(self) -> str:
        response = self._request(
            "GET", f"{DRIVE_API}/about", params={"fields": "user(emailAddress)"}
        )
        return str(response.json().get("user", {}).get("emailAddress", ""))


def _is_revoked_grant(response: httpx.Response) -> bool:
    """Cavab «razılıq geri alınıb» deyirmi (`{"error": "invalid_grant"}`).

    GÖVDƏ OXUNA BİLMƏSƏ `False` QAYTARILIR: naməlum formatlı cavabı razılıq
    ləğvi saymaq bağlantını səhvən `REVOKED` edərdi və administrator işləyən
    hesabı yenidən qoşmağa məcbur olardı — yəni səhv istiqamətdə "təhlükəsiz"
    olardı. Şübhə halında adi `DriveApiError` daha az zərərlidir: o, təkrar
    cəhdlə keçir.
    """
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("error") == OAUTH_REVOKED_ERROR_CODE


__all__ = [
    "DRIVE_API",
    "FOLDER_MIME",
    "OAUTH_REVOKED_ERROR_CODE",
    "DriveApiClient",
    "DriveApiError",
    "DriveConsentRevokedError",
    "DriveQuotaExceededError",
    "OAuthClient",
]
