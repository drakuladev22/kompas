"""Google Drive razılıq (OAuth consent) axını — Faza 3.9 / miqrasiya 002.

Testlər REAL lokal server qaldırır və brauzerin edəcəyi GET sorğusunu `httpx`
ilə özləri göndərir. Google-a çıxış YOXDUR: token endpoint-i sahtə `httpx`
transportu ilə əvəz olunur.

Belə qurulub, çünki axının ən kövrək hissəsi məhz loopback hissəsidir
(port bağlama, `state` yoxlaması, kodun oxunması) — onu mock-larla əvəz etsək
test yalnız öz mock-larını yoxlayardı.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

import httpx
import pytest

from src.infrastructure.storage.drive_api import OAuthClient
from src.infrastructure.storage.oauth_flow import (
    AUTH_ENDPOINT,
    SCOPES,
    DriveOAuthFlow,
    OAuthFlowError,
)

pytestmark = pytest.mark.unit

OAUTH = OAuthClient(client_id="test-client", client_secret="test-secret")


def _transport(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)


def _token_handler(payload: dict[str, Any], *, status: int = 200) -> Any:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(status, json=payload)
        # `/about` — hesabın e-poçtu.
        return httpx.Response(200, json={"user": {"emailAddress": "mağaza@kompas.az"}})

    return handle


def _visit(flow: DriveOAuthFlow, url: str) -> None:
    """Brauzerin edəcəyi GET-i simulyasiya edir və `poll()`-u işə salır."""
    import threading

    result: list[Exception] = []

    def call() -> None:
        try:
            httpx.get(url, timeout=5.0)
        except Exception as exc:  # pragma: no cover - şəbəkə yoxdur, lokal soket
            result.append(exc)

    thread = threading.Thread(target=call)
    thread.start()
    try:
        # `poll()` bir sorğu emal edir; brauzer sapı cavabı gözləyir.
        for _ in range(200):
            code = flow.poll()
            if code is not None:
                break
    finally:
        thread.join(timeout=5.0)
    assert not result, result


# --------------------------------------------------------------------------- #
# Razılıq ünvanı
# --------------------------------------------------------------------------- #


def test_authorization_url_requests_offline_access_with_pkce() -> None:
    """`refresh_token` üçün `access_type=offline` + `prompt=consent` MƏCBURİDİR.

    Biri unudulsa hesabı ikinci dəfə qoşmaq "refresh_token gəlmədi" ilə
    bitər — bu, yalnız istehsalatda, hesab dəyişdirilərkən üzə çıxardı.
    """
    flow = DriveOAuthFlow(OAUTH, transport=_transport(_token_handler({})))
    try:
        request = flow.start()
        query = urllib.parse.parse_qs(urllib.parse.urlparse(request.url).query)

        assert request.url.startswith(AUTH_ENDPOINT)
        assert query["access_type"] == ["offline"]
        assert query["prompt"] == ["consent"]
        assert query["code_challenge_method"] == ["S256"]
        assert query["code_challenge"][0] and query["code_challenge"][0] != request.code_verifier
        assert query["redirect_uri"][0].startswith("http://127.0.0.1:")
        assert query["scope"] == [" ".join(SCOPES)]
    finally:
        flow.close()


def test_scope_is_limited_to_files_the_app_creates() -> None:
    """Bütöv `drive` scope-u istifadəçinin BÜTÜN sənədlərini açardı."""
    assert "https://www.googleapis.com/auth/drive.file" in SCOPES
    assert "https://www.googleapis.com/auth/drive" not in SCOPES


def test_each_flow_gets_a_fresh_verifier_and_state() -> None:
    """PKCE-nin mənası birdəfəlik sirrdədir — təkrar istifadə onu ləğv edərdi."""
    first = DriveOAuthFlow(OAUTH, transport=_transport(_token_handler({})))
    second = DriveOAuthFlow(OAUTH, transport=_transport(_token_handler({})))
    try:
        a, b = first.start(), second.start()
        assert a.code_verifier != b.code_verifier
        assert a.state != b.state
        assert a.redirect_uri != b.redirect_uri, "Hər axın öz portunu tutur"
    finally:
        first.close()
        second.close()


def test_starting_twice_is_rejected() -> None:
    flow = DriveOAuthFlow(OAUTH, transport=_transport(_token_handler({})))
    try:
        flow.start()
        with pytest.raises(OAuthFlowError, match="artıq başlayıb"):
            flow.start()
    finally:
        flow.close()


# --------------------------------------------------------------------------- #
# Loopback cavabı
# --------------------------------------------------------------------------- #


def test_poll_returns_none_until_the_browser_answers() -> None:
    flow = DriveOAuthFlow(OAUTH, transport=_transport(_token_handler({})))
    try:
        flow.start()
        assert flow.poll() is None
    finally:
        flow.close()


def test_code_is_captured_from_the_loopback_redirect() -> None:
    flow = DriveOAuthFlow(OAUTH, transport=_transport(_token_handler({})))
    try:
        request = flow.start()
        _visit(flow, f"{request.redirect_uri}/?code=auth-code-1&state={request.state}")
        assert flow.poll() == "auth-code-1"
    finally:
        flow.close()


def test_mismatched_state_is_rejected() -> None:
    """CSRF müdafiəsi: cavab BAŞQA axına aiddirsə qəbul edilmir."""
    flow = DriveOAuthFlow(OAUTH, transport=_transport(_token_handler({})))
    try:
        request = flow.start()
        with pytest.raises(OAuthFlowError, match="state_mismatch"):
            _visit(flow, f"{request.redirect_uri}/?code=auth-code-1&state=basqa-state")
    finally:
        flow.close()


def test_user_denial_is_reported_not_silently_ignored() -> None:
    """ "Hələ gözlə" ilə "istifadəçi rədd etdi" fərqli hallardır."""
    flow = DriveOAuthFlow(OAUTH, transport=_transport(_token_handler({})))
    try:
        request = flow.start()
        with pytest.raises(OAuthFlowError) as caught:
            _visit(flow, f"{request.redirect_uri}/?error=access_denied&state={request.state}")
        assert "icazə verilmədi" in caught.value.user_message
    finally:
        flow.close()


# --------------------------------------------------------------------------- #
# Token mübadiləsi
# --------------------------------------------------------------------------- #


def test_exchange_returns_refresh_token_and_account_email() -> None:
    payload = {"refresh_token": "refresh-1", "access_token": "access-1", "expires_in": 3600}
    flow = DriveOAuthFlow(OAUTH, transport=_transport(_token_handler(payload)))
    try:
        flow.start()
        credentials = flow.exchange("auth-code-1")
        assert credentials.refresh_token == "refresh-1"
        assert credentials.account_email == "mağaza@kompas.az"
    finally:
        flow.close()


def test_exchange_sends_the_verifier_and_redirect_uri() -> None:
    """PKCE yoxlaması serverdə yalnız `code_verifier` göndərilsə işləyir."""
    seen: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            seen.update(dict(urllib.parse.parse_qsl(request.content.decode())))
            return httpx.Response(200, json={"refresh_token": "r", "access_token": "a"})
        return httpx.Response(200, json={"user": {"emailAddress": "a@b.c"}})

    flow = DriveOAuthFlow(OAUTH, transport=_transport(handle))
    try:
        request = flow.start()
        flow.exchange("auth-code-1")
        assert seen["code_verifier"] == request.code_verifier
        assert seen["redirect_uri"] == request.redirect_uri
        assert seen["grant_type"] == "authorization_code"
    finally:
        flow.close()


def test_missing_refresh_token_explains_the_cause() -> None:
    """Google təkrar razılıqda `refresh_token` göndərməyə bilər (bax modul başlığı).

    Bu halda "naməlum xəta" göstərmək administratoru çıxılmaz vəziyyətdə
    qoyardı — həll yolu mesajın ÖZÜNDƏ olmalıdır.
    """
    flow = DriveOAuthFlow(OAUTH, transport=_transport(_token_handler({"access_token": "a"})))
    try:
        flow.start()
        with pytest.raises(OAuthFlowError) as caught:
            flow.exchange("auth-code-1")
        assert "təhlükəsizlik ayarlarından" in caught.value.user_message
    finally:
        flow.close()


def test_http_failure_does_not_leak_the_response_body() -> None:
    flow = DriveOAuthFlow(
        OAUTH, transport=_transport(_token_handler({"error": "invalid_grant"}, status=400))
    )
    try:
        flow.start()
        with pytest.raises(OAuthFlowError) as caught:
            flow.exchange("auth-code-1")
        assert "invalid_grant" not in str(caught.value)
        assert "HTTP 400" in str(caught.value)
    finally:
        flow.close()


def test_email_lookup_failure_does_not_block_the_connection() -> None:
    """E-poçt yalnız GÖSTƏRİŞ üçündür — onsuz da bağlantı işləyir."""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"refresh_token": "r", "access_token": "a"})
        return httpx.Response(500, json={})

    flow = DriveOAuthFlow(OAUTH, transport=_transport(handle))
    try:
        flow.start()
        credentials = flow.exchange("auth-code-1")
        assert credentials.refresh_token == "r"
        assert credentials.account_email == ""
    finally:
        flow.close()


def test_exchange_before_start_is_rejected() -> None:
    flow = DriveOAuthFlow(OAUTH, transport=_transport(_token_handler({})))
    try:
        with pytest.raises(OAuthFlowError, match="başlamayıb"):
            flow.exchange("code")
    finally:
        flow.close()


def test_cancel_releases_the_port() -> None:
    """Açıq qalan lokal port müddətsiz dinləməməlidir."""
    import socket

    flow = DriveOAuthFlow(OAUTH, transport=_transport(_token_handler({})))
    try:
        request = flow.start()
        port = int(request.redirect_uri.rsplit(":", 1)[1])
        flow.cancel()

        # Port sərbəstdirsə eyni ünvana yenidən bağlanmaq mümkündür.
        probe = socket.socket()
        try:
            probe.bind(("127.0.0.1", port))
        finally:
            probe.close()
    finally:
        flow.close()
