"""Google Drive razılıq (OAuth consent) axını — masaüstü tətbiq naxışı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ LOOPBACK, "KODU KOPYALA-YAPIŞDIR" DEYİL
──────────────────────────────────────────────────────────────────────────────
Google `urn:ietf:wg:oauth:2.0:oob` (kodu ekranda göstər, istifadəçi yapışdırsın)
axınını 2022-də QAPADIB — yeni klientlərdə ümumiyyətlə işləmir. Quraşdırılmış
tətbiqlər üçün yeganə dəstəklənən yol `http://127.0.0.1:<port>` üzərinə
yönləndirmədir: brauzer razılıqdan sonra kodu birbaşa bizim müvəqqəti lokal
serverə göndərir.

Port SABİT DEYİL — 0 verilir və OS boş port seçir. Sabit port seçsəydik,
həmin portu tutan başqa proqram bağlantını tamamilə bloklayardı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ PKCE, HALBUKİ `client_secret` DƏ VAR
──────────────────────────────────────────────────────────────────────────────
Masaüstü tətbiqində `client_secret` ƏSLİNDƏ SİRR DEYİL — .exe-ni açan onu
görür (Google özü bunu sənədləşdirir). Müdafiə PKCE-dədir: `code_verifier`
yalnız cari prosesin yaddaşındadır və hər axında yenidən yaradılır, ona görə
loopback ünvanını dinləyən yerli zərərli proses kodu tutsa belə onu token-ə
dəyişə bilmir.

`state` isə CSRF üçündür: brauzerə göndərdiyimiz təsadüfi dəyər geri
qayıtmalıdır, əks halda cavab BAŞQA axına aiddir və rədd edilir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `poll()`, BLOKLAYAN `wait()` DEYİL
──────────────────────────────────────────────────────────────────────────────
Razılıq brauzerdə dəqiqələrlə çəkə bilər. Bloklayan gözləmə GUI sapını
dondurardı; ayrıca sap isə Qt siqnalları ilə əlaqə üçün əlavə sinxronizasiya
tələb edərdi. `poll()` isə ən çoxu `POLL_TIMEOUT_SECONDS` qədər gözləyir və
geri qayıdır — çağıran onu sadəcə taymerdən çağırır və bütün iş Qt hadisə
dövrəsində qalır.

──────────────────────────────────────────────────────────────────────────────
`access_type=offline` + `prompt=consent` NİYƏ MƏCBURİDİR
──────────────────────────────────────────────────────────────────────────────
Bizə `refresh_token` lazımdır (şəkillər aylarla, istifadəçi olmadan yüklənir).
Google onu YALNIZ `access_type=offline` ilə verir və eyni hesab üçün TƏKRAR
razılıqda ümumiyyətlə GÖNDƏRMİR — `prompt=consent` olmasa hesabı ikinci dəfə
qoşmaq "refresh_token gəlmədi" xətası ilə bitərdi.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING, Any, Final

import httpx

from src.domain.policies import SystemLimitKey
from src.domain.value_objects.storage import StorageError
from src.infrastructure.config.limits import fallback_float
from src.infrastructure.storage.drive_api import TOKEN_ENDPOINT, DriveApiError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.infrastructure.storage.drive_api import OAuthClient

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

AUTH_ENDPOINT: Final[str] = "https://accounts.google.com/o/oauth2/v2/auth"

#: `drive.file` — tətbiqin ÖZ yaratdığı fayllar. Bütöv `drive` scope-u
#: istifadəçinin bütün sənədlərinə giriş istəyərdi və Google-un yoxlama
#: prosesindən keçmək tələb olunardı; sübut şəkilləri üçün bu, həm lazımsız,
#: həm də müştəriyə izah edilə bilməyən bir səlahiyyət olardı.
#: `userinfo.email` yalnız qoşulan hesabın ünvanını göstərmək üçündür.
SCOPES: Final[tuple[str, ...]] = (
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/userinfo.email",
)

#: `poll()` bir çağırışda ən çox bu qədər gözləyir.
POLL_TIMEOUT_SECONDS: Final[float] = 0.05

#: Razılıq bu müddətdən çox çəkərsə axın ləğv edilir (server bağlanır).
#: Açıq qalan lokal port müddətsiz dinləməməlidir.
#:
#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`DRIVE_OAUTH_FLOW_TIMEOUT_SECONDS`, seed: migrations/032). 5 dəqiqə
#: Google hesabına ilk dəfə daxil olan (2FA, hesab seçimi) admin üçün az ola
#: bilər; müddət uzadıla bilməsə razılıq axını təkrar-təkrar başladılardı.
#:
#: AD SAXLANILIB (`FALLBACK_*` prefiksi ƏLAVƏ EDİLMƏYİB): sabiti
#: `presentation/controllers/drive_connection.py` idxal edir və təqdimat qatı
#: bu köçürmədə TOXUNULMUR — adı dəyişmək orada idxal xətası verərdi.
FLOW_TIMEOUT_SECONDS: Final[float] = fallback_float(SystemLimitKey.DRIVE_OAUTH_FLOW_TIMEOUT_SECONDS)

_HTML_OK: Final[str] = (
    "<html><head><meta charset='utf-8'><title>KompasOS</title></head>"
    "<body style='font-family:sans-serif;text-align:center;padding-top:80px'>"
    "<h2>Hesab qoşuldu</h2>"
    "<p>Bu səhifəni bağlaya və KompasOS-a qayıda bilərsiniz.</p>"
    "</body></html>"
)
_HTML_FAIL: Final[str] = (
    "<html><head><meta charset='utf-8'><title>KompasOS</title></head>"
    "<body style='font-family:sans-serif;text-align:center;padding-top:80px'>"
    "<h2>Bağlantı tamamlanmadı</h2>"
    "<p>KompasOS-a qayıdıb yenidən cəhd edin.</p>"
    "</body></html>"
)


class OAuthFlowError(StorageError):
    """Razılıq axını tamamlanmadı."""

    user_message = "Google hesabı qoşula bilmədi."


@dataclass(frozen=True)
class DriveCredentials:
    """Razılığın nəticəsi — bağlantı sətrini yaratmaq üçün lazım olan hər şey."""

    refresh_token: str
    account_email: str


class _CallbackHandler(BaseHTTPRequestHandler):
    """Yalnız `/` üzərindəki GET-i qəbul edir və nəticəni serverə yazır."""

    server: Any  # `_CallbackServer` — BaseHTTPRequestHandler-də `Any`-dir

    def do_GET(self) -> None:
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        code = params.get("code", [""])[0]
        state = params.get("state", [""])[0]
        error = params.get("error", [""])[0]

        ok = bool(code) and not error and state == self.server.expected_state
        self.server.result_code = code if ok else ""
        self.server.result_error = error or ("" if ok else "state_mismatch")

        body = (_HTML_OK if ok else _HTML_FAIL).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - API imzası
        """Standart stderr jurnalını söndürür — bizim öz jurnalımız var."""


class _CallbackServer(HTTPServer):
    """Tək sorğuluq lokal server + axının vəziyyəti."""

    expected_state: str = ""
    result_code: str = ""
    result_error: str = ""


@dataclass(frozen=True)
class AuthorizationRequest:
    """Brauzerdə açılacaq ünvan və onunla bağlı birdəfəlik sirlər."""

    url: str
    redirect_uri: str
    state: str
    code_verifier: str


class DriveOAuthFlow:
    """Razılıq axınının vəziyyət maşını: `start` → `poll`* → `exchange`.

    Bir obyekt BİR axın üçündür. Təkrar qoşulma yeni obyekt tələb edir —
    `code_verifier`-in təkrar istifadəsi PKCE-nin mənasını itirərdi.
    """

    def __init__(
        self,
        oauth: OAuthClient,
        *,
        transport: httpx.Client | None = None,
        scopes: tuple[str, ...] = SCOPES,
    ) -> None:
        self._oauth = oauth
        self._http = transport or httpx.Client(timeout=30.0)
        self._owns_transport = transport is None
        self._scopes = scopes
        self._server: _CallbackServer | None = None
        self._request: AuthorizationRequest | None = None
        self._lock = threading.Lock()

    # ------------------------------ başlanğıc -------------------------------- #

    def start(self) -> AuthorizationRequest:
        """Lokal serveri qaldırır və razılıq ünvanını qaytarır."""
        if self._server is not None:
            raise OAuthFlowError("Razılıq axını artıq başlayıb")

        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .decode("ascii")
            .rstrip("=")
        )

        # Port 0 → OS boş port seçir (bax modul başlığı).
        server = _CallbackServer(("127.0.0.1", 0), _CallbackHandler)
        server.timeout = POLL_TIMEOUT_SECONDS
        server.expected_state = state
        self._server = server

        redirect_uri = f"http://127.0.0.1:{server.server_address[1]}"
        query = urllib.parse.urlencode(
            {
                "client_id": self._oauth.client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(self._scopes),
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": state,
                # Bax modul başlığı: `refresh_token` üçün hər ikisi məcburidir.
                "access_type": "offline",
                "prompt": "consent",
            }
        )
        self._request = AuthorizationRequest(
            url=f"{AUTH_ENDPOINT}?{query}",
            redirect_uri=redirect_uri,
            state=state,
            code_verifier=verifier,
        )
        _security_log.info("DRIVE_OAUTH_STARTED", extra={"redirect_uri": redirect_uri})
        return self._request

    @staticmethod
    def open_browser(request: AuthorizationRequest) -> bool:
        """Sistem brauzerini açır — uğursuzluqda `False`.

        `False` fatal DEYİL: ekran ünvanı mətn kimi göstərir və istifadəçi onu
        özü aça bilər. Brauzerin açılmaması bağlantını qeyri-mümkün etməməlidir.
        """
        try:
            return bool(webbrowser.open(request.url))
        except Exception:
            _log.exception("DRIVE_OAUTH_BROWSER_FAILED")
            return False

    # ------------------------------ gözləmə ---------------------------------- #

    def poll(self) -> str | None:
        """Kod gəldisə qaytarır, gəlmədisə `None` (ən çoxu 50 ms gözləyir).

        Raises:
            OAuthFlowError: Google xəta qaytardısa və ya `state` uyğun gəlmədisə.
                Bu, sükutla "hələ gözlə" saymaqdan fərqlidir — istifadəçi
                razılığı RƏDD edibsə ona bunu demək lazımdır.
        """
        server = self._server
        if server is None:
            raise OAuthFlowError("Razılıq axını başlamayıb")

        with self._lock:
            server.handle_request()
            if server.result_error:
                error = server.result_error
                self.cancel()
                _security_log.warning("DRIVE_OAUTH_DENIED", extra={"error": error})
                raise OAuthFlowError(
                    f"Razılıq alınmadı: {error}",
                    user_message=(
                        "Google hesabına icazə verilmədi."
                        if error == "access_denied"
                        else "Razılıq cavabı yararsızdır. Yenidən cəhd edin."
                    ),
                    context={"error": error},
                )
            return server.result_code or None

    def cancel(self) -> None:
        """Serveri bağlayır — port sərbəst buraxılır."""
        if self._server is not None:
            self._server.server_close()
            self._server = None

    def close(self) -> None:
        self.cancel()
        if self._owns_transport:
            self._http.close()

    # ------------------------------ mübadilə --------------------------------- #

    def exchange(self, code: str) -> DriveCredentials:
        """Kodu `refresh_token`-ə dəyişir və hesabın e-poçtunu oxuyur."""
        request = self._request
        if request is None:
            raise OAuthFlowError("Razılıq axını başlamayıb")

        response = self._http.post(
            TOKEN_ENDPOINT,
            data={
                "client_id": self._oauth.client_id,
                "client_secret": self._oauth.client_secret,
                "code": code,
                "code_verifier": request.code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": request.redirect_uri,
            },
        )
        if response.status_code != httpx.codes.OK:
            # Cavab mətni LOGA YAZILMIR — orada token ola bilər (eyni qayda
            # `DriveApiClient._token`-dədir).
            _security_log.error(
                "DRIVE_OAUTH_EXCHANGE_FAILED",
                extra={"status_code": response.status_code},
            )
            raise OAuthFlowError(
                f"Kod token-ə dəyişilmədi (HTTP {response.status_code})",
                user_message="Google cavabı qəbul etmədi. Yenidən cəhd edin.",
            )

        payload = response.json()
        refresh_token = str(payload.get("refresh_token", ""))
        if not refresh_token:
            # Bax modul başlığı: `prompt=consent` olmadan bu hal təkrar
            # qoşulmada baş verir və səbəbi ekranda AÇIQ deyilməlidir.
            raise OAuthFlowError(
                "Google `refresh_token` göndərmədi",
                user_message=(
                    "Google uzunmüddətli icazə vermədi. Google hesabınızın "
                    "təhlükəsizlik ayarlarından KompasOS-un girişini ləğv edib "
                    "yenidən cəhd edin."
                ),
            )

        email = self._account_email(str(payload.get("access_token", "")))
        self.cancel()
        _security_log.warning("DRIVE_OAUTH_COMPLETED", extra={"account": email})
        return DriveCredentials(refresh_token=refresh_token, account_email=email)

    def _account_email(self, access_token: str) -> str:
        """Qoşulan hesabın ünvanı — tapılmasa boş sətir.

        Boş sətir axını DAYANDIRMIR: e-poçt yalnız GÖSTƏRİŞ üçündür, bağlantı
        isə `refresh_token` ilə işləyir. Bunun üçün qoşulmanı rədd etmək
        istifadəçini kosmetik səbəbdən bloklamaq olardı.
        """
        if not access_token:
            return ""
        try:
            response = self._http.get(
                "https://www.googleapis.com/drive/v3/about",
                params={"fields": "user(emailAddress)"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if response.status_code != httpx.codes.OK:
                return ""
            return str(response.json().get("user", {}).get("emailAddress", ""))
        except (httpx.HTTPError, DriveApiError, ValueError):
            _log.warning("DRIVE_OAUTH_EMAIL_UNAVAILABLE")
            return ""


__all__ = [
    "AUTH_ENDPOINT",
    "FLOW_TIMEOUT_SECONDS",
    "SCOPES",
    "AuthorizationRequest",
    "DriveCredentials",
    "DriveOAuthFlow",
    "OAuthFlowError",
]
