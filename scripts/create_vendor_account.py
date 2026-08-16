"""Vendor konsol hesabını yaradır (DB-3 FAZA 4) — YALNIZ təchizatçının maşınında.

──────────────────────────────────────────────────────────────────────────────
BU SKRİPT `.exe`-YƏ DAXİL EDİLMİR
──────────────────────────────────────────────────────────────────────────────
`src/KompasOS.spec` yalnız `src/main.py` giriş nöqtəsini paketləyir; `scripts/`
qovluğu ora ÜMUMİYYƏTLƏ daxil deyil. Bu, təsadüf deyil, tələbdir: skript
mərkəzi vendor bazasının DSN-ini oxuyur və `vendor_accounts`-a YAZIR. Müştəri
quraşdırmasında belə bir yol olsaydı, konsol hesabı yaratmaq üçün lazım olan
yeganə şey `.exe`-nin özü olardı.

`tests/unit/test_vendor_bootstrap.py` bunu maşınla yoxlayır — spec faylı bu
skriptə istinad edərsə test qırılır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ TOTP BURADA STDLIB İLƏ YAZILIR
──────────────────────────────────────────────────────────────────────────────
`pyotp` əlavə etmək bir asılılıq daha demək olardı (bax
`docs/dependency_policy.md`). RFC 6238 isə HMAC-SHA1 üzərində 20 sətirlik
hesablamadır və burada YALNIZ qurulma anında lazımdır — doğrulama sonradan
konsolun öz kodunda olacaq. Alqoritmi özümüz yazmaq kriptoqrafiya icad etmək
DEYİL: `hmac`/`hashlib` standart kitabxanadadır, biz yalnız sayğac formatını
qururuq.

──────────────────────────────────────────────────────────────────────────────
NİYƏ KOD DOĞRULANMADAN HESAB YAZILMIR
──────────────────────────────────────────────────────────────────────────────
Sirri göstərib dərhal yazsaydıq, autentifikatoru səhv qurmuş istifadəçi bunu
YALNIZ ilk girişdə — yəni artıq hesab yaranmış və bəlkə də yeganə hesab
olduqda — bilərdi. Skript əvvəlcə istifadəçidən 6 rəqəmli kodu istəyir və
yalnız uyğun gəldikdə `INSERT` edir.

──────────────────────────────────────────────────────────────────────────────
İSTİFADƏ
──────────────────────────────────────────────────────────────────────────────
    set KOMPASOS_VENDOR_DSN=postgresql://user:pass@host:5432/vendor_db
    .venv\\Scripts\\python.exe scripts/create_vendor_account.py

    # və ya DSN-i açıq ötürməklə
    .venv\\Scripts\\python.exe scripts/create_vendor_account.py --dsn "postgresql://…"
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import os
import re
import secrets
import struct
import sys
import time
from typing import Final
from urllib.parse import quote

#: Argon2 parametrləri tətbiqin öz servisindən gəlir — vendor hesabı ilə
#: müştəri hesabı EYNİ gücdə heşlənməlidir, əks halda "hansı daha zəifdir"
#: sualı yaranardı.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.infrastructure.security.hashing import (
    ARGON2_MEMORY_COST_KIB,
    ARGON2_PARALLELISM,
    ARGON2_TIME_COST,
)

DSN_ENV: Final = "KOMPASOS_VENDOR_DSN"
#: TOTP sirri 160 bit (RFC 4226 tövsiyəsi) — base32-də 32 simvol.
TOTP_SECRET_BYTES: Final = 20
TOTP_STEP_SECONDS: Final = 30
TOTP_DIGITS: Final = 6
#: Doğrulamada qəbul edilən sürüşmə: bir addım geri/irəli (saat fərqi).
TOTP_WINDOW: Final = 1
ISSUER: Final = "KompasOS Vendor"
MIN_PASSWORD_LENGTH: Final = 12

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --------------------------------------------------------------------------- #
# TOTP (RFC 6238)
# --------------------------------------------------------------------------- #


def generate_secret() -> str:
    """Base32 TOTP sirri — autentifikator tətbiqlərinin gözlədiyi format."""
    return base64.b32encode(secrets.token_bytes(TOTP_SECRET_BYTES)).decode("ascii").rstrip("=")


def totp_code(secret: str, *, at: int | None = None, step: int = TOTP_STEP_SECONDS) -> str:
    """Verilmiş anın 6 rəqəmli kodu.

    Padding bərpa olunur: `generate_secret()` `=` simvollarını atır (URI-də
    çirkin görünür), `b32decode` isə onları TƏLƏB edir.
    """
    padded = secret + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded, casefold=True)
    counter = int((at if at is not None else time.time()) // step)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10**TOTP_DIGITS)).zfill(TOTP_DIGITS)


def verify_code(secret: str, code: str) -> bool:
    """Kodu ±1 addım pəncərəsində yoxlayır — saat fərqi normaldır.

    Müqayisə `compare_digest` ilədir: adi `==` uyğun gəlməyən ilk simvolda
    dayanır və nəzəri olaraq vaxt sızması yaradır.
    """
    now = time.time()
    candidate = code.strip()
    return any(
        hmac.compare_digest(totp_code(secret, at=now + offset * TOTP_STEP_SECONDS), candidate)
        for offset in range(-TOTP_WINDOW, TOTP_WINDOW + 1)
    )


def provisioning_uri(secret: str, email: str) -> str:
    """`otpauth://` URI — QR generatoruna və ya autentifikatora birbaşa verilir."""
    label = quote(f"{ISSUER}:{email}", safe="")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}"
        f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_STEP_SECONDS}"
    )


# --------------------------------------------------------------------------- #
# Giriş yoxlamaları
# --------------------------------------------------------------------------- #


def _prompt_email(given: str | None) -> str:
    email = (given or input("E-poçt: ")).strip()
    if not _EMAIL.match(email):
        raise SystemExit(f"Yararsız e-poçt: {email!r}")
    return email


def _prompt_password() -> str:
    """Şifrə İKİ DƏFƏ soruşulur və ekranda göstərilmir.

    Uzunluq həddi tətbiqin öz siyasəti ilə eynidir (12) — vendor hesabı
    müştəri hesabından zəif ola bilməz.
    """
    while True:
        password = getpass.getpass("Şifrə: ")
        if len(password) < MIN_PASSWORD_LENGTH:
            print(f"  Ən azı {MIN_PASSWORD_LENGTH} simvol olmalıdır.")
            continue
        if password != getpass.getpass("Şifrə (təkrar): "):
            print("  Şifrələr uyğun gəlmədi.")
            continue
        return password


def _hash_password(password: str) -> str:
    from argon2 import PasswordHasher

    hasher = PasswordHasher(
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST_KIB,
        parallelism=ARGON2_PARALLELISM,
    )
    return hasher.hash(password)


# --------------------------------------------------------------------------- #
# Əsas axın
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="create_vendor_account",
        description="Mərkəzi vendor bazasında konsol hesabı yaradır (DB-3).",
    )
    parser.add_argument("--dsn", default="", help=f"Vendor bazasının DSN-i (defolt: ${DSN_ENV})")
    parser.add_argument("--email", default="", help="Hesabın e-poçtu (verilməzsə soruşulur)")
    args = parser.parse_args(argv)

    dsn = args.dsn.strip() or os.environ.get(DSN_ENV, "").strip()
    if not dsn:
        print(
            f"XƏTA: vendor bazasının DSN-i yoxdur. `{DSN_ENV}` mühit dəyişənini "
            "təyin edin və ya `--dsn` ötürün.",
            file=sys.stderr,
        )
        return 2

    import psycopg

    email = _prompt_email(args.email or None)
    password = _prompt_password()
    secret = generate_secret()

    print("\n--- TOTP QURULUŞU -------------------------------------------------")
    print("Aşağıdakı URI-ni autentifikator tətbiqinə əlavə edin (QR kimi də oxuna bilər):\n")
    print(f"  {provisioning_uri(secret, email)}\n")
    print(f"Əl ilə daxil etmək üçün sirr: {secret}")
    print("Sirr BİR DƏFƏ göstərilir — indi saxlayın.\n")

    if not verify_code(secret, input("Tətbiqin göstərdiyi 6 rəqəmli kod: ")):
        print(
            "XƏTA: kod uyğun gəlmədi — hesab YARADILMADI.\n"
            "Səbəb adətən saat fərqidir; cihazın vaxtını yoxlayıb yenidən cəhd edin.",
            file=sys.stderr,
        )
        return 1

    password_hash = _hash_password(password)

    with psycopg.connect(dsn, connect_timeout=15) as conn, conn.cursor() as cur:
        cur.execute("SET search_path TO vendor, public")
        cur.execute("SELECT 1 FROM vendor_accounts WHERE email = %s", (email,))
        if cur.fetchone() is not None:
            print(
                f"XƏTA: `{email}` üçün hesab ARTIQ mövcuddur. Mövcud hesabın sirrini "
                "dəyişmək ayrıca əməliyyatdır — bu skript üzərinə yazmır.",
                file=sys.stderr,
            )
            return 1
        cur.execute(
            """
            INSERT INTO vendor_accounts (email, password_hash, totp_secret)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (email, password_hash, secret),
        )
        row = cur.fetchone()
        conn.commit()

    print(f"\nHesab yaradıldı: {email} (id={row[0] if row else '?'})")
    print(
        "QEYD: konsol bağlantısı `BYPASSRLS` olmayan, `kompasos_vendor` üzvü bir "
        "rolla qurulmalıdır — `service_role` bütün RLS siyasətlərini yan keçir "
        "(bax `database/migrations/vendor/002_vendor_rls.sql`)."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI giriş nöqtəsi
    sys.exit(main())
