"""Vendor hesabı bootstrap skripti — TOTP və paketləmə zəmanətləri.

──────────────────────────────────────────────────────────────────────────────
NİYƏ RFC TEST VEKTORU İLƏ YOXLANILIR
──────────────────────────────────────────────────────────────────────────────
`generate_secret()` → `totp_code()` → `verify_code()` dövrəsi ÖZ-ÖZÜNƏ
uyğundur: səhv yazılmış alqoritm də bu dövrəni keçər (məsələn sayğac addımı
səhv olsa belə, hər iki tərəf eyni səhvi edər). Ona görə RFC 6238-in RƏSMİ
test vektoru işlədilir — o, bizim koddan asılı olmayan xarici həqiqətdir.
Uyğun gəlirsə, autentifikator tətbiqləri (Google Authenticator, Authy, 1Password)
də eyni kodu göstərəcək.

──────────────────────────────────────────────────────────────────────────────
PAKETLƏMƏ ZƏMANƏTİ
──────────────────────────────────────────────────────────────────────────────
Skript mərkəzi vendor bazasına YAZIR. Müştəriyə göndərilən `.exe`-də belə bir
yol olsaydı, konsol hesabı yaratmaq üçün lazım olan yeganə şey `.exe`-nin özü
olardı. `.spec` faylının bu skriptə istinad etmədiyi burada maşınla yoxlanılır
— sənəddəki vəd kifayət deyil, çünki sənəd sükutla köhnəlir.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Final

import pytest
from scripts.create_vendor_account import (
    MIN_PASSWORD_LENGTH,
    _prompt_email,
    generate_secret,
    provisioning_uri,
    totp_code,
    verify_code,
)

pytestmark = pytest.mark.unit

_REPO_ROOT: Final = Path(__file__).resolve().parents[2]

#: RFC 6238, Appendix B — SHA1 sətri "12345678901234567890" (ASCII).
#: Sənəd 8 rəqəmli kodları verir; bizim tətbiq 6 rəqəmlidir, ona görə son ALTI
#: rəqəm götürülür (kəsilmə eyni ədəddən aparılır).
_RFC_SECRET: Final = base64.b32encode(b"12345678901234567890").decode("ascii").rstrip("=")
_RFC_VECTORS: Final = (
    (59, "287082"),  # RFC: 94287082
    (1111111109, "081804"),  # RFC: 07081804
    (1111111111, "050471"),  # RFC: 14050471
    (1234567890, "005924"),  # RFC: 89005924
    (2000000000, "279037"),  # RFC: 69279037
)


@pytest.mark.parametrize(("moment", "expected"), _RFC_VECTORS)
def test_totp_matches_the_rfc_6238_vectors(moment: int, expected: str) -> None:
    """Xarici həqiqətlə uyğunluq — autentifikator tətbiqləri ilə eyni kod."""
    assert totp_code(_RFC_SECRET, at=moment) == expected


def test_a_generated_secret_is_base32_of_the_expected_length() -> None:
    """160 bit → base32-də 32 simvol (RFC 4226 tövsiyəsi)."""
    secret = generate_secret()
    assert len(secret) == 32
    assert set(secret) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
    # Padding-siz sirr də dekod oluna bilməlidir — `totp_code` onu bərpa edir.
    assert totp_code(secret)


def test_the_current_code_verifies_and_a_wrong_one_does_not() -> None:
    secret = generate_secret()
    assert verify_code(secret, totp_code(secret))
    assert not verify_code(secret, "000000")


def test_a_code_from_the_neighbouring_step_is_accepted() -> None:
    """±1 addım qəbul edilir — cihaz saatı bir neçə saniyə fərqlənə bilər.

    Pəncərə OLMASAYDI, saatı 5 saniyə geridə olan telefon HEÇ VAXT giriş edə
    bilməzdi və səbəb istifadəçiyə görünməzdi.
    """
    import time

    secret = generate_secret()
    previous = totp_code(secret, at=time.time() - 30)
    assert verify_code(secret, previous)


def test_a_far_away_code_is_rejected() -> None:
    """Pəncərə DAR olmalıdır — iki dəqiqə əvvəlki kod keçməməlidir."""
    import time

    secret = generate_secret()
    assert not verify_code(secret, totp_code(secret, at=time.time() - 120))


def test_the_provisioning_uri_carries_the_issuer_and_parameters() -> None:
    uri = provisioning_uri("ABCDEFGHIJKLMNOP", "vendor@kompas.az")
    assert uri.startswith("otpauth://totp/")
    assert "secret=ABCDEFGHIJKLMNOP" in uri
    assert "issuer=KompasOS%20Vendor" in uri
    assert "digits=6" in uri and "period=30" in uri


def test_an_invalid_email_stops_the_script() -> None:
    """Yararsız e-poçt HESAB YARADILMADAN dayandırır."""
    with pytest.raises(SystemExit):
        _prompt_email("bu-epoçt-deyil")


def test_the_password_floor_matches_the_application_policy() -> None:
    """Vendor hesabı müştəri hesabından ZƏİF ola bilməz."""
    from src.infrastructure.security.hashing import FALLBACK_MIN_PASSWORD_LENGTH

    assert MIN_PASSWORD_LENGTH >= FALLBACK_MIN_PASSWORD_LENGTH


def test_the_bootstrap_script_is_not_packaged_into_the_exe() -> None:
    """`.spec` bu skriptə İSTİNAD ETMİR — bax modul başlığı."""
    spec = (_REPO_ROOT / "src" / "KompasOS.spec").read_text(encoding="utf-8", errors="replace")
    assert "create_vendor_account" not in spec
    assert "scripts/" not in spec.replace("\\", "/")
