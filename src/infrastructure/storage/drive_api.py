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

from src.domain.value_objects.storage import QuotaStatus, StorageError
from src.shared.logger import LogChannel, get_logger

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

# `noqa: S105` — bu, URL-dir, sirr deyil (linter adda "TOKEN" görür).
TOKEN_ENDPOINT: Final[str] = "https://oauth2.googleapis.com/token"  # noqa: S105
DRIVE_API: Final[str] = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_API: Final[str] = "https://www.googleapis.com/upload/drive/v3"
FOLDER_MIME: Final[str] = "application/vnd.google-apps.folder"

#: Access token bitməmişdən bu qədər əvvəl yenilənir.
TOKEN_REFRESH_MARGIN_SECONDS: Final[int] = 60
DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
#: Drive API istifadəçi başına ~100 sorğu/100 saniyə verir; 429/5xx-də
#: eksponensial gözləmə ilə təkrar cəhd olunur.
RETRY_STATUS: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})
MAX_RETRIES: Final[int] = 3
HTTP_UNAUTHORIZED: Final[int] = 401
HTTP_NOT_FOUND: Final[int] = 404


class DriveApiError(StorageError):
    """Drive API çağırışı uğursuz oldu."""


class DriveQuotaExceededError(DriveApiError):
    """Hesabda yer qalmayıb."""

    user_message = "Google Drive hesabında yer qalmayıb — administratorla əlaqə saxlayın."


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
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._oauth = oauth
        self._refresh_token = refresh_token
        self._http = transport or httpx.Client(timeout=timeout)
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
                raise DriveApiError(
                    f"Access token alınmadı (HTTP {response.status_code})",
                    user_message="Google Drive bağlantısı bərpa edilməlidir.",
                )
            payload = response.json()
            self._access_token = str(payload["access_token"])
            self._expires_at = (
                time.monotonic()
                + int(payload.get("expires_in", 3600))
                - TOKEN_REFRESH_MARGIN_SECONDS
            )
            return self._access_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}"}

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Token yeniləmə + 429/5xx üçün təkrar cəhd."""
        last_error = ""
        for attempt in range(MAX_RETRIES):
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


__all__ = [
    "DRIVE_API",
    "FOLDER_MIME",
    "DriveApiClient",
    "DriveApiError",
    "DriveQuotaExceededError",
    "OAuthClient",
]
