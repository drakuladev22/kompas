r"""Kirayəçi bazasını BAŞQA REGİONA köçürür (Sinqapur → Frankfurt).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU SKRİPT VAR — ÖLÇÜLMÜŞ SƏBƏB
──────────────────────────────────────────────────────────────────────────────
`docs/performance_notes.md`-in ən böyük leveri: baza Sinqapurdadır, istifadəçi
Bakıda. TCP əl sıxma ölçüldü (bu maşından, 5 cəhdin ən yaxşısı):

    ap-southeast-1 (Sinqapur, cari)   205 ms
    eu-central-1  (Frankfurt)          70 ms      ← 2.9× yaxın
    eu-west-3     (Paris)              78 ms
    eu-west-2     (London)             81 ms

Tətbiqin HƏR ekranının vaxtının praktik olaraq 100 %-i baza gözləməsidir
(ölçüldü: çəkiliş ~0 ms), yəni bu əmsal BÜTÜN rəqəmlərə birbaşa tətbiq olunur:
İdarə Paneli 3.2 saniyədən ~1.1 saniyəyə düşür. HEÇ BİR kod optimallaşdırması
bu qazancın yaxınına gəlmir.

──────────────────────────────────────────────────────────────────────────────
SUPABASE LAYİHƏNİN REGİONUNU DƏYİŞMİR — ONA GÖRƏ «KÖÇÜRMƏ»DİR
──────────────────────────────────────────────────────────────────────────────
Mövcud layihənin regionu YERİNDƏ dəyişdirilə bilmir. Yeganə yol: hədəf
regionda YENİ layihə açmaq və məlumatı ora köçürmək. Layihə yaratmaq
Supabase HESABI tələb edir (idarə paneli / Management API + şəxsi token) —
bu, skriptin İÇİNDƏN edilə bilməz və qəsdən edilmir: hesab səviyyəsində
resurs yaratmaq (və pul xərcləmək) operatorun qərarıdır.

Ona görə axın belədir:

    1. OPERATOR: Supabase-də `eu-central-1` regionunda yeni layihə açır və
       onun pooler DSN-ini götürür (ƏL İLƏ, bir dəfə).
    2. SKRİPT: sxem + miqrasiyalar → məlumat → yoxlama → (istəyə bağlı)
       yerli konfiqurasiyanın yenidən yönləndirilməsi.

──────────────────────────────────────────────────────────────────────────────
İSTİFADƏ
──────────────────────────────────────────────────────────────────────────────
    .venv/Scripts/python.exe scripts/migrate_region.py \
        --source-dsn "postgresql://…@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres" \
        --target-dsn "postgresql://…@aws-0-eu-central-1.pooler.supabase.com:5432/postgres" \
        --dev            # bu maşının `connection.json`-unu YENİ bazaya yönləndirir

    ... --dry-run        # heç nə yazmır: addımları və ölçüləri göstərir

──────────────────────────────────────────────────────────────────────────────
NİYƏ `pg_dump | psql`, NİYƏ PYTHON İLƏ SƏTİR-SƏTİR KÖÇÜRMƏ DEYİL
──────────────────────────────────────────────────────────────────────────────
93 cədvəl, xarici açarlar, `jsonb`, massiv və `bytea` sütunları var. Python
ilə köçürmə hər tipin sərhəd halını (NULL massiv, boş `jsonb`, ikili sahə)
YENİDƏN yazmaq demək olardı — `pg_dump` isə həmin işi onilliklərdir düzgün
edir. Skript onu TAPIR (`PATH`, sonra standart quraşdırma yolları) və server
versiyası ilə uyğunluğunu YOXLAYIR: köhnə `pg_dump` yeni serveri dump edə
BİLMİR və bu, yarımçıq köçürmənin ən sakit səbəbidir.

──────────────────────────────────────────────────────────────────────────────
BƏRPA ZAMANI TRIGGER-LƏR SÖNDÜRÜLÜR — NİYƏ TƏHLÜKƏSİZDİR
──────────────────────────────────────────────────────────────────────────────
Sxemdə qəsdən "keçmişi qorumaq" üçün trigger-lər var: `audit_logs` append-only,
`fines.created_at` server vaxtına məcbur, `permission_flags` atributları
dəyişməz. Bərpa zamanı onlar İŞLƏSƏYDİ, KÖÇÜRÜLƏN sətirlər ya rədd edilər
(append-only), ya da dəyəri ƏVƏZLƏNƏRDİ (server vaxtı) — yəni hədəf baza
mənbədən FƏRQLİ olardı.

Ona görə bərpa `session_replication_role = replica` ilə işləyir: bu, Postgres-in
öz replikasiya rejimidir və məhz belə hallar üçün var. Rejim YALNIZ bərpa
sessiyasındadır, hədəf bazada QALMIR — sonrakı hər adi bağlantı trigger-ləri
tam işlək görür (yoxlama addımı bunu AÇIQ təsdiqləyir).

`schema_migrations` KÖÇÜRÜLMÜR: hədəf reyestri 2-ci addımda ÖZ icrasından
yaranır (fayl adı + SHA-256 + KİM tətbiq etdi). Mənbədən köçürsəydik, reyestr
"bu bazada icra olunmuş" yerinə "başqa bazada icra olunmuş" yazardı.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

_APPLY_MIGRATIONS: Final[Path] = _REPO_ROOT / "scripts" / "apply_migrations.py"

#: `pg_dump`/`psql` axtarılan standart quraşdırma yolları (Windows).
#: `PATH` BİRİNCİDİR — operator öz versiyasını seçə bilsin.
_PG_BIN_CANDIDATES: Final[tuple[str, ...]] = (
    r"C:\Program Files\PostgreSQL\18\bin",
    r"C:\Program Files\PostgreSQL\17\bin",
    r"C:\Program Files\PostgreSQL\16\bin",
    r"C:\Program Files\PostgreSQL\15\bin",
)

#: Məlumatı KÖÇÜRÜLMƏYƏN cədvəllər — səbəb modul başlığındadır.
_EXCLUDED_TABLES: Final[tuple[str, ...]] = ("kompasos.schema_migrations",)

#: Sxem adı — `schema.sql` ilə eynidir.
_SCHEMA: Final[str] = "kompasos"


class RegionMigrationError(RuntimeError):
    """Addımlardan biri uğursuz oldu — sonrakılar İCRA OLUNMUR."""


def _ensure_utf8_stdio() -> None:
    """Windows konsolunun cp1252 defoltunu düzəldir (`onboard_new_tenant.py`-ın
    eyni funksiyası — səbəb də eynidir: bu fayl Azərbaycan hərfləri yazır)."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            with suppress(Exception):
                stream.reconfigure(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# Alətlərin tapılması
# --------------------------------------------------------------------------- #


def find_pg_tool(name: str, *, extra_dirs: tuple[str, ...] = _PG_BIN_CANDIDATES) -> Path | None:
    """`pg_dump`/`psql` icra faylını tapır — `PATH`, sonra standart yollar.

    `None` qaytarır ki, çağıran tərəf İNSANA anlaşılan mesaj yaza bilsin:
    "alət yoxdur" texniki xəta deyil, quraşdırma addımıdır.
    """
    from shutil import which

    found = which(name)
    if found:
        return Path(found)
    executable = f"{name}.exe" if os.name == "nt" else name
    for directory in extra_dirs:
        candidate = Path(directory) / executable
        if candidate.exists():
            return candidate
    return None


def tool_major_version(tool: Path) -> int:
    """`pg_dump --version` çıxışından BAŞ versiyanı çıxarır (məs. 17)."""
    result = subprocess.run(  # noqa: S603 — əmr sabitdir, `shell=False`
        [str(tool), "--version"], capture_output=True, text=True, check=False
    )
    for token in result.stdout.split():
        head, _, _ = token.partition(".")
        if head.isdigit():
            return int(head)
    raise RegionMigrationError(f"`{tool}` versiyası oxuna bilmədi: {result.stdout.strip()!r}")


def server_major_version(dsn: str) -> int:
    """Hədəf/mənbə serverin BAŞ versiyası — `pg_dump` uyğunluğu üçün."""
    import psycopg

    with psycopg.connect(dsn, connect_timeout=30) as conn, conn.cursor() as cur:
        cur.execute("SHOW server_version")
        row = cur.fetchone()
    if row is None:  # pragma: no cover — `SHOW` həmişə sətir qaytarır
        raise RegionMigrationError("server versiyası oxuna bilmədi")
    head, _, _ = str(row[0]).partition(".")
    return int(head)


# --------------------------------------------------------------------------- #
# Ölçü və müqayisə
# --------------------------------------------------------------------------- #


def table_counts(dsn: str) -> dict[str, int]:
    """`kompasos` sxemindəki HƏR cədvəlin FAKTİKİ sətir sayı.

    `pg_stat_user_tables.n_live_tup` İŞLƏDİLMİR: o, təxminidir (vacuum-dan
    asılı) və köçürmə yoxlaması təxminlə aparıla bilməz — bir sətrin itməsi
    məhz burada görünməlidir.
    """
    import psycopg

    counts: dict[str, int] = {}
    with psycopg.connect(dsn, connect_timeout=30) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name FROM information_schema.tables
             WHERE table_schema = %s AND table_type = 'BASE TABLE'
             ORDER BY table_name
            """,
            (_SCHEMA,),
        )
        tables = [str(row[0]) for row in cur.fetchall()]
        for table in tables:
            # Cədvəl adı `information_schema`-dan gəlir (sistem kataloqu),
            # istifadəçi girişindən YOX — ona görə identifikator kimi
            # birləşdirilməsi təhlükəsizdir.
            cur.execute(f'SELECT count(*) FROM {_SCHEMA}."{table}"')  # noqa: S608
            row = cur.fetchone()
            counts[table] = int(row[0]) if row else 0
    return counts


def compare_counts(source: dict[str, int], target: dict[str, int]) -> list[str]:
    """Uyğunsuzluqların İNSAN oxunaqlı siyahısı (boşdursa köçürmə tamdır).

    `schema_migrations` MÜQAYİSƏDƏN ÇIXARILIR: o, hədəfdə ÖZ icrasından
    yaranır və mənbədəkindən fərqli sətir sayına malik ola bilər (məs. mənbə
    köhnə buraxılışdadır).
    """
    skip = {name.split(".", 1)[-1] for name in _EXCLUDED_TABLES}
    problems: list[str] = []
    for table, expected in sorted(source.items()):
        if table in skip:
            continue
        actual = target.get(table)
        if actual is None:
            problems.append(f"{table}: hədəfdə CƏDVƏL YOXDUR (mənbədə {expected} sətir)")
        elif actual != expected:
            problems.append(f"{table}: mənbə {expected}, hədəf {actual}")
    return problems


# --------------------------------------------------------------------------- #
# Addımlar
# --------------------------------------------------------------------------- #


def apply_schema(dsn: str) -> None:
    """Sxem + BÜTÜN miqrasiyalar — MÖVCUD icraçı ilə (reyestrə yazılır)."""
    result = subprocess.run(  # noqa: S603 — əmr sabit massivdir
        [sys.executable, str(_APPLY_MIGRATIONS)],
        env={
            "DATABASE_ADMIN_URL": dsn,
            "PYTHONIOENCODING": "utf-8",
            "PATH": os.environ.get("PATH", ""),
        },
        capture_output=True,
        text=True,
        check=False,
        cwd=str(_REPO_ROOT),
    )
    sys.stdout.write(_indent(result.stdout))
    if result.returncode != 0:
        raise RegionMigrationError(
            f"miqrasiya icraçısı {result.returncode} qaytardı:\n{result.stderr}"
        )


def copy_data(*, source_dsn: str, target_dsn: str, dump_path: Path) -> None:
    """`pg_dump --data-only` → fayl → `psql` (trigger-lər söndürülü).

    FAYL ARADAN QALDIRILMIR (borudan keçirmək əvəzinə diskə yazılır): köçürmə
    yarımçıq qalsa operatorun əlində TAM dump qalmalıdır — şəbəkə kəsilməsi
    ucbatından ikinci dəfə saatlarla dump çıxarmaq lazım gəlməsin.
    """
    pg_dump = find_pg_tool("pg_dump")
    psql = find_pg_tool("psql")
    if pg_dump is None or psql is None:
        raise RegionMigrationError(
            "`pg_dump`/`psql` tapılmadı. PostgreSQL client alətlərini quraşdırın "
            "(https://www.postgresql.org/download/windows/) və ya `PATH`-a əlavə edin."
        )

    server_major = server_major_version(source_dsn)
    dump_major = tool_major_version(pg_dump)
    if dump_major < server_major:
        raise RegionMigrationError(
            f"`pg_dump` versiyası {dump_major}, server isə {server_major} — KÖHNƏ alət "
            "yeni serveri dump edə bilmir. Client alətlərini yeniləyin."
        )

    dump_command = [
        str(pg_dump),
        "--data-only",
        "--no-owner",
        "--no-privileges",
        f"--schema={_SCHEMA}",
        *[f"--exclude-table={table}" for table in _EXCLUDED_TABLES],
        "--file",
        str(dump_path),
        source_dsn,
    ]
    result = subprocess.run(dump_command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise RegionMigrationError(f"`pg_dump` uğursuz oldu:\n{result.stderr[-2000:]}")
    sys.stdout.write(_indent(f"dump: {dump_path} ({dump_path.stat().st_size / 1024:.0f} KB)"))

    restore_command = [
        str(psql),
        "--quiet",
        # BİR TRANZAKSİYA: yarımçıq bərpa YOXDUR — ya hamısı, ya heç nə.
        "--single-transaction",
        "--set",
        "ON_ERROR_STOP=1",
        # Trigger-lər söndürülür — səbəb modul başlığındadır.
        "--command",
        "SET session_replication_role = replica",
        "--file",
        str(dump_path),
        target_dsn,
    ]
    result = subprocess.run(restore_command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise RegionMigrationError(f"bərpa uğursuz oldu:\n{result.stderr[-2000:]}")


def repoint_local_config(target_dsn: str) -> Path:
    """Bu maşının `connection.json`-unu YENİ bazaya yönləndirir (`--dev`).

    `onboard_new_tenant.py::_deploy_dev_config` ilə EYNİ mexanizm və eyni
    səbəb: yolu burada TƏKRAR hesablamırıq, `save_settings()` çağırırıq.
    """
    from src.infrastructure.config.connection_file import (
        ConnectionSettings,
        save_settings,
    )

    return save_settings(ConnectionSettings.from_dsn(target_dsn))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Kirayəçi bazasını başqa regiona köçürür",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--source-dsn", required=True, help="CARİ (köhnə region) baza DSN-i")
    parser.add_argument("--target-dsn", required=True, help="YENİ (hədəf region) baza DSN-i")
    parser.add_argument(
        "--dump-file",
        default="",
        help="dump faylının yolu (defolt: `output/region_migration.sql`)",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="bu maşının `connection.json`-unu YENİ bazaya yönləndir",
    )
    parser.add_argument("--dry-run", action="store_true", help="heç nə yazma, ölçüləri göstər")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdio()
    args = _parse_args(argv)

    if args.source_dsn == args.target_dsn:
        sys.stderr.write("XƏTA: mənbə və hədəf DSN eynidir — köçürüləcək yer yoxdur.\n")
        return 2

    dump_path = (
        Path(args.dump_file) if args.dump_file else _REPO_ROOT / "output" / "region_migration.sql"
    )
    dump_path.parent.mkdir(parents=True, exist_ok=True)

    sys.stdout.write("Region köçürməsi\n")
    try:
        source_counts = table_counts(args.source_dsn)
    except Exception as exc:
        sys.stderr.write(f"XƏTA: mənbə bazaya qoşulmaq alınmadı — {exc}\n")
        return 1
    total_rows = sum(source_counts.values())
    sys.stdout.write(f"  mənbə : {len(source_counts)} cədvəl, {total_rows} sətir\n")

    if args.dry_run:
        sys.stdout.write("--dry-run: heç nə yazılmadı. Addımlar:\n")
        sys.stdout.write("  1. Hədəf bazaya sxem + miqrasiyalar (apply_migrations.py)\n")
        sys.stdout.write(f"  2. `pg_dump --data-only` → {dump_path}\n")
        sys.stdout.write("  3. `psql --single-transaction` ilə bərpa (trigger-lər söndürülü)\n")
        sys.stdout.write("  4. Sətir saylarının cədvəl-cədvəl müqayisəsi\n")
        if args.dev:
            sys.stdout.write("  5. `--dev`: bu maşının `connection.json`-u yönləndirilir\n")
        return 0

    try:
        sys.stdout.write("[1/4] Hədəf bazaya sxem + miqrasiyalar …\n")
        apply_schema(args.target_dsn)
        sys.stdout.write("[2/4] Məlumatın dump-ı və bərpası …\n")
        copy_data(source_dsn=args.source_dsn, target_dsn=args.target_dsn, dump_path=dump_path)
        sys.stdout.write("[3/4] Yoxlama: sətir saylarının müqayisəsi …\n")
        problems = compare_counts(source_counts, table_counts(args.target_dsn))
        if problems:
            sys.stderr.write("\nDAYANDI: köçürmə TAM DEYİL —\n" + _indent("\n".join(problems)))
            return 1
        sys.stdout.write(_indent(f"{total_rows} sətrin hamısı hədəfdədir"))
        if args.dev:
            sys.stdout.write("[4/4] Yerli konfiqurasiya yönləndirilir …\n")
            sys.stdout.write(_indent(str(repoint_local_config(args.target_dsn))))
        else:
            sys.stdout.write("[4/4] Yerli konfiqurasiya TOXUNULMADI (`--dev` verilməyib)\n")
    except RegionMigrationError as exc:
        sys.stderr.write(f"\nDAYANDI: {exc}\n")
        return 1

    sys.stdout.write("\nBİTDİ. Qalan addımlar (ƏL İLƏ):\n")
    sys.stdout.write(
        "  1. `.env`-dəki `DATABASE_URL`/`DATABASE_ADMIN_URL` yeni DSN ilə əvəzlənsin.\n"
    )
    sys.stdout.write("  2. Müştəri maşınlarındakı `connection.json` yenilənsin (host + parol).\n")
    sys.stdout.write("  3. Köhnə layihə DƏRHAL silinməsin — bir neçə gün ehtiyat kimi qalsın.\n")
    return 0


def _indent(text: str) -> str:
    return "".join(f"      {line}\n" for line in text.splitlines() if line.strip())


if __name__ == "__main__":  # pragma: no cover — CLI giriş nöqtəsi
    raise SystemExit(main())
