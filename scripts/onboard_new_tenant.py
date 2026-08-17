r"""Yeni müştəri quraşdırması — bir əmrlə (TENANT-1 Faza 4).

──────────────────────────────────────────────────────────────────────────────
BU SKRİPT `.exe`-YƏ PAKETLƏNMİR
──────────────────────────────────────────────────────────────────────────────
`src/KompasOS.spec` yalnız `src/` altını yığır; `scripts/` ora düşmür. Bu,
təsadüf deyil: skript VENDOR bazasına YAZIR (`tenants` sətri yaradır) və
müştəri maşınında belə bir imkanın olması lisenziya qapısını mənasız edərdi —
istənilən adam özünə «AKTİV» sətir yaza bilərdi.

`tests/unit/test_packaging_credentials.py` `.spec`-in `scripts/`-i daxil
etmədiyini maşınla qoruyur.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SKRİPT — ƏL İLƏ ETMƏK NƏYİ POZURDU
──────────────────────────────────────────────────────────────────────────────
Yeni müştəri qurmaq beş addımdır və hər biri digərinin nəticəsindən asılıdır:
kimlik → vendor qeydi → sxem → seed → konfiqurasiya. Əl ilə görüləndə üçüncü
addımın buraxılması DB-5-in tapdığı vəziyyəti yaradır (32 cədvəl yox, tətbiq
onlara yazmağa çalışır) və qüsur aylarla görünmür.

Skript SIRA-nı kodda saxlayır: hər addım əvvəlkinin uğurunu yoxlayır və
uğursuzluqda DAYANIR. Yarımçıq quraşdırma «işləyir kimi görünən, əslində
pozuq» vəziyyətdən yaxşıdır.

──────────────────────────────────────────────────────────────────────────────
İKİ BAZA, İKİ DSN — QARIŞDIRMAQ MÜMKÜN DEYİL
──────────────────────────────────────────────────────────────────────────────
`--tenant-dsn` müştərinin ÖZ Supabase layihəsi, `--vendor-dsn` isə mərkəzi
lisenziya bazasıdır (DB-3/DB-4). İkisi AYRI arqumentdir və biri digərinin
defoltu DEYİL: eyni dəyəri təsadüfən iki yerə vermək bütün müştəriləri bir
bazaya yığmaq — yəni TENANT-1-in qəti qərarını pozmaq — olardı. Skript
bərabərliyi AÇIQ yoxlayır və dayanır.

──────────────────────────────────────────────────────────────────────────────
İSTİFADƏ
──────────────────────────────────────────────────────────────────────────────
    .venv/Scripts/python.exe scripts/onboard_new_tenant.py \
        --company "Embawood" \
        --tenant-dsn "postgresql://kompasos_app....@aws-0-eu.pooler.supabase.com:5432/postgres" \
        --vendor-dsn "postgresql://vendor....@aws-0-eu.pooler.supabase.com:5432/postgres" \
        --supabase-ref "abcdefghijklmnop" \
        --contact-email "it@embawood.az" \
        --out ./embawood

    # Nə ediləcəyini görmək (heç nə yazılmır):
    ... --dry-run
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
_APPLY_MIGRATIONS: Final[Path] = _REPO_ROOT / "scripts" / "apply_migrations.py"

#: Lisenziya açarının uzunluğu (bayt). `secrets.token_urlsafe(32)` ~43 simvol
#: verir — brute-force üçün praktiki olaraq əlçatmazdır və eyni zamanda
#: e-poçtla göndərilə biləcək qədər qısadır.
LICENSE_KEY_BYTES: Final[int] = 32

#: Vendor sətrinin başlanğıc statusu. `ODENIS_GOZLENILIR` — `AKTIV` DEYİL:
#: quraşdırma ilə ödəniş fərqli hadisələrdir və skriptin özünə ödəniş təsdiqi
#: səlahiyyəti vermək lisenziya qapısını yan keçmək olardı.
INITIAL_STATUS: Final[str] = "ODENIS_GOZLENILIR"


class OnboardingError(RuntimeError):
    """Addımlardan biri uğursuz oldu — sonrakılar İCRA OLUNMUR."""


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.tenant_dsn == args.vendor_dsn:
        sys.stderr.write(
            "XƏTA: `--tenant-dsn` ilə `--vendor-dsn` eynidir. Hər müştəri AYRI "
            "Supabase layihəsidir (TENANT-1 qəti qərarı) — vendor bazası isə "
            "mərkəzi və paylaşılandır.\n"
        )
        return 2

    tenant_id = uuid.uuid4()
    license_key = secrets.token_urlsafe(LICENSE_KEY_BYTES)

    sys.stdout.write(f"Yeni kirayəçi: {args.company}\n")
    sys.stdout.write(f"  tenant_id   : {tenant_id}\n")
    sys.stdout.write(f"  license_key : {license_key[:8]}… ({len(license_key)} simvol)\n")
    sys.stdout.write(f"  supabase_ref: {args.supabase_ref or '(verilməyib)'}\n\n")

    if args.dry_run:
        sys.stdout.write("--dry-run: heç nə yazılmadı.\n")
        _describe_steps(args)
        return 0

    try:
        _step(1, "Tenant bazasına miqrasiyalar", lambda: _apply_migrations(args.tenant_dsn))
        _step(
            2,
            "Vendor bazasına miqrasiyalar",
            lambda: _apply_migrations(args.vendor_dsn, vendor=True),
        )
        _step(
            3,
            "Kirayəçi sətri (tenant bazası)",
            lambda: _create_tenant_row(args, tenant_id, license_key),
        )
        _step(
            4,
            "Abunə sətri (vendor bazası)",
            lambda: _create_vendor_row(args, tenant_id, license_key),
        )
        _step(5, "Konfiqurasiya faylları", lambda: _write_config(args, tenant_id, license_key))
    except OnboardingError as exc:
        sys.stderr.write(f"\nDAYANDI: {exc}\n")
        return 1

    sys.stdout.write("\nBİTDİ. Növbəti addımlar:\n")
    sys.stdout.write(f"  1. «{args.out}» qovluğundakı faylları müştəri maşınına köçürün.\n")
    sys.stdout.write("  2. Tətbiqi açın — İlk Quraşdırma Sihirbazı Root hesabını yaradacaq.\n")
    sys.stdout.write("  3. Ödəniş alındıqdan sonra Vendor Konsolundan statusu AKTIV edin.\n")
    return 0


# --------------------------------------------------------------------------- #
# Addımlar
# --------------------------------------------------------------------------- #


def _step(number: int, title: str, action: object) -> None:
    sys.stdout.write(f"[{number}/5] {title} …\n")
    action()  # type: ignore[operator]
    sys.stdout.write(f"[{number}/5] {title} — OK\n")


def _apply_migrations(dsn: str, *, vendor: bool = False) -> None:
    """Miqrasiya icraçısını çağırır — SIFIRDAN yazılmır.

    İkinci bir tətbiq məntiqi yazmaq `schema_migrations` reyestrini iki
    fərqli yazıcıya bölərdi (migrations/061) və hansının yazdığı sual altında
    qalardı. Ona görə mövcud icraçı ALT PROSES kimi çağırılır və DSN mühit
    dəyişəni ilə ötürülür.
    """
    command = [sys.executable, str(_APPLY_MIGRATIONS)]
    if vendor:
        command.append("--vendor")
    result = subprocess.run(  # noqa: S603 — əmr SABİT massivdir, `shell=False`
        command,
        env={"DATABASE_ADMIN_URL": dsn, "PYTHONIOENCODING": "utf-8", "PATH": _path_env()},
        capture_output=True,
        text=True,
        check=False,
        cwd=str(_REPO_ROOT),
    )
    sys.stdout.write(_indent(result.stdout))
    if result.returncode != 0:
        raise OnboardingError(f"miqrasiya icraçısı {result.returncode} qaytardı:\n{result.stderr}")


def _create_tenant_row(args: argparse.Namespace, tenant_id: uuid.UUID, license_key: str) -> None:
    """`license_tenants` sətri + `seed_tenant_defaults()` — MÜŞTƏRİNİN bazasında.

    ──────────────────────────────────────────────────────────────────────────
    AÇAR PLAINTEXT SAXLANILMIR — `license_key_hash` ARGON2 GÖZLƏYİR
    ──────────────────────────────────────────────────────────────────────────
    Tenant bazasındakı sütunun adı `license_key`-dir DEYİL,
    `license_key_hash`-dir (schema.sql: «Argon2 hash, plaintext DEYİL»).
    Səbəb: müştəri bazası müştərinin əlindədir və oradan oxunan plaintext açar
    lisenziyanın özünü kopyalamağa imkan verərdi. PLAİNTEXT nüsxə YALNIZ
    VENDOR bazasındadır — orada o, buraxan tərəfin öz qeydidir.

    Hash `argon2.PasswordHasher()` ilə — BİBƏRSİZ (pepper YOX) — qurulur və
    bu, şüurlu seçimdir: `security/hashing.py::PasswordService` `KOMPASOS_HASH_
    PEPPER` tələb edir, həmin bibər isə MÜŞTƏRİNİN maşınına aiddir və bizim
    quraşdırma maşınımızda YOXDUR. Bibərli hash yazsaydıq, o, heç bir maşında
    yoxlana bilməzdi.

    QEYD (mövcud vəziyyət): kod bazasında `license_key_hash`-i YOXLAYAN yol
    hazırda YOXDUR — sütun yalnız yazılır (`PostgresTenantProvisioning` özünə-
    host halında ora `SELF_HOSTED_NO_LICENSE_KEY` nişanı qoyur). Yoxlama
    əlavə ediləndə o, məhz bu formatı — bibərsiz Argon2-ni — gözləməlidir.

    ──────────────────────────────────────────────────────────────────────────
    `company_contact_email` MƏCBURİDİR (migrations/059)
    ──────────────────────────────────────────────────────────────────────────
    Sütun `NOT NULL`-dur və CHECK ilə formatı yoxlanılır. O, Emergency Access
    Recovery-də kimlik təsdiqinin YEGANƏ mənbəyidir — ona görə skript
    `--contact-email` verilməyibsə DAYANIR, uydurma dəyər yazmır.

    `seed_tenant_defaults()` sətirdən SONRA çağırılır: `system_limits`,
    `feature_toggles` və rol şablonları oradan gəlir, əks halda ROOT paneli
    boş qalardı.
    """
    if not args.contact_email:
        raise OnboardingError(
            "`--contact-email` MƏCBURİDİR: `license_tenants.company_contact_email` "
            "`NOT NULL`-dur (migrations/059) və Emergency Access Recovery-də "
            "kimlik təsdiqinin yeganə mənbəyidir."
        )

    import psycopg
    from argon2 import PasswordHasher

    with psycopg.connect(args.tenant_dsn, connect_timeout=30) as conn, conn.cursor() as cur:
        cur.execute("SET search_path TO kompasos, public")
        cur.execute(
            """
            INSERT INTO license_tenants
                (tenant_id, tenant_name, license_key_hash, status, company_contact_email)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id) DO NOTHING
            """,
            (
                str(tenant_id),
                args.company,
                PasswordHasher().hash(license_key),
                INITIAL_STATUS,
                args.contact_email,
            ),
        )
        cur.execute("SELECT seed_tenant_defaults(%s)", (str(tenant_id),))
        conn.commit()


def _create_vendor_row(args: argparse.Namespace, tenant_id: uuid.UUID, license_key: str) -> None:
    """`tenants` sətri — MƏRKƏZİ vendor bazasında (DB-3)."""
    import psycopg

    with psycopg.connect(args.vendor_dsn, connect_timeout=30) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants
                (tenant_id, company_name, license_key, status, supabase_ref, contact_email)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id) DO NOTHING
            """,
            (
                str(tenant_id),
                args.company,
                license_key,
                INITIAL_STATUS,
                args.supabase_ref or None,
                args.contact_email or None,
            ),
        )
        conn.commit()


def _write_config(args: argparse.Namespace, tenant_id: uuid.UUID, license_key: str) -> None:
    r"""Müştəri maşınına köçürüləcək faylları hazırlayır.

    PAROL YAZILMIR. `connection.json`-dakı parol DPAPI ilə MAŞIN əhatəsində
    şifrələnir (DB-4 Faza 2) — yəni bizim maşında şifrələnən dəyər müştərinin
    maşınında AÇILA BİLMƏZ. Ona görə skript `connection.template.json`
    hazırlayır və parol quraşdırıcı tərəfindən «Bağlantı Ayarları» ekranından
    daxil edilir; həmin ekran onu YERİNDƏ şifrələyir.

    `installation.json` isə tam hazırdır: onun içində sirr yoxdur (SEC-021).
    """
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    (out / "installation.json").write_text(
        json.dumps(
            {"tenant_id": str(tenant_id), "is_licensed": True},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    host, port, database, username = _parse_dsn(args.tenant_dsn)
    (out / "connection.template.json").write_text(
        json.dumps(
            {
                "host": host,
                "port": port,
                "database": database,
                "username": username,
                "password_encrypted": "",
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    (out / "OXU-MƏNİ.txt").write_text(
        "KompasOS — quraşdırma təlimatı\n"
        "==============================\n\n"
        f"Müştəri     : {args.company}\n"
        f"tenant_id   : {tenant_id}\n"
        f"license_key : {license_key}\n\n"
        "1. `installation.json` faylını `%PROGRAMDATA%\\KompasOS\\` qovluğuna\n"
        "   köçürün.\n"
        "2. `connection.template.json` faylını eyni qovluğa `connection.json`\n"
        "   adı ilə köçürün.\n"
        "3. Tətbiqi açın. «Bağlantı Ayarları» ekranı parolu soruşacaq — parol\n"
        "   MƏHZ ORADA daxil edilməlidir, çünki o, bu kompüterə bağlı şəkildə\n"
        "   şifrələnir (başqa maşında şifrələnən dəyər burada açılmır).\n"
        "4. Bağlantı uğurlu olduqdan sonra İlk Quraşdırma Sihirbazı Root\n"
        "   hesabını yaradacaq.\n\n"
        "QEYD: lisenziya statusu `ODENIS_GOZLENILIR`-dir. Ödəniş alındıqdan\n"
        "sonra Vendor Konsolundan `AKTIV` edilməlidir.\n",
        encoding="utf-8",
    )
    sys.stdout.write(_indent(f"{out}/installation.json\n{out}/connection.template.json\n"))


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Yeni KompasOS müştərisi qurur (TENANT-1 Faza 4)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--company", required=True, help="şirkət adı, məs. «Embawood»")
    parser.add_argument("--tenant-dsn", required=True, help="MÜŞTƏRİNİN öz Supabase DSN-i")
    parser.add_argument("--vendor-dsn", required=True, help="MƏRKƏZİ vendor bazasının DSN-i")
    parser.add_argument("--supabase-ref", default="", help="müştəri layihəsinin ref-i")
    # MƏCBURİDİR (bax `_create_tenant_row`), lakin `required=True` DEYİL:
    # `--dry-run` yolunun onsuz da işləməsi lazımdır ki, quraşdırıcı
    # addımları əvvəlcədən görə bilsin.
    parser.add_argument(
        "--contact-email", default="", help="şirkət əlaqə ünvanı (yazma üçün MƏCBURİ)"
    )
    parser.add_argument("--out", default="./onboarding", help="konfiqurasiya qovluğu")
    parser.add_argument("--dry-run", action="store_true", help="heç nə yazma, addımları göstər")
    return parser.parse_args(argv)


def _describe_steps(args: argparse.Namespace) -> None:
    sys.stdout.write("Addımlar:\n")
    sys.stdout.write("  1. Tenant bazasına BÜTÜN miqrasiyalar (apply_migrations.py)\n")
    sys.stdout.write("  2. Vendor bazasına vendor miqrasiyaları (--vendor)\n")
    sys.stdout.write("  3. `license_tenants` sətri → seed trigger-ləri işə düşür\n")
    sys.stdout.write("  4. Vendor `tenants` sətri (status: ODENIS_GOZLENILIR)\n")
    sys.stdout.write(f"  5. Konfiqurasiya faylları → {args.out}\n")


def _parse_dsn(dsn: str) -> tuple[str, int, str, str]:
    from urllib.parse import unquote, urlparse

    parsed = urlparse(dsn)
    return (
        parsed.hostname or "",
        parsed.port or 5432,
        (parsed.path or "/").lstrip("/") or "postgres",
        unquote(parsed.username or ""),
    )


def _path_env() -> str:
    """Alt prosesə ötürülən `PATH`.

    Mühit TAMAMİLƏ əvəzlənir (DSN sızmasın deyə), lakin `PATH` olmadan
    Windows-da `python.exe` öz DLL-lərini tapa bilmir.
    """
    import os

    return os.environ.get("PATH", "")


def _indent(text: str) -> str:
    return "".join(f"      {line}\n" for line in text.splitlines() if line.strip())


if __name__ == "__main__":  # pragma: no cover — CLI giriş nöqtəsi
    raise SystemExit(main())
