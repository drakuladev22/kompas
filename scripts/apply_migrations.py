r"""Miqrasiya icraçısı — hansı faylın tətbiq olunduğunu REYESTRDƏ saxlayır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU SKRİPT LAZIM OLDU
──────────────────────────────────────────────────────────────────────────────
DB-5 canlı bazaya qarşı işlədi və 60 miqrasiyadan **11-inin heç vaxt tətbiq
olunmadığını** tapdı: 32 cədvəl bazada YOX idi, tətbiq isə onlara yazmağa
çalışırdı. Qüsur aylarla görünməmişdi, çünki tətbiq olunmuş miqrasiyaların
qeydi HEÇ YERDƏ saxlanmırdı — cavab yalnız sxemi mənbə ilə əl ilə müqayisə
etməklə tapılırdı və o müqayisə yalnız CƏDVƏL yaradan miqrasiyanı görür.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA ALƏT (ALEMBIC / SUPABASE CLI) GƏTİRİLMƏDİ
──────────────────────────────────────────────────────────────────────────────
Miqrasiyalar XAM SQL-dir və qəsdən belədir: onlar trigger funksiyaları, RLS
siyasətləri və `DO` blokları daşıyır — yəni ORM-in modelindən kənar şeylər.
Alembic belə faylları yalnız «icra et» adımı kimi görər, əvəzində isə bütün
layihəyə öz versiya ağacını, `env.py`-ını və asılılığını gətirərdi. Burada
lazım olan yeganə şey əskik idi: TƏTBİQ OLUNANIN QEYDİ. Otuz sətirlik cədvəl
onu verir.

──────────────────────────────────────────────────────────────────────────────
İDEMPOTENTLİK REYESTRİ ƏVƏZ ETMİR
──────────────────────────────────────────────────────────────────────────────
Hər miqrasiya idempotentdir (CLAUDE.md §7), yəni hamısını hər dəfə yenidən
tətbiq etmək TƏHLÜKƏSİZDİR — DB-1 Faza 4 bunu ayrıca sxemdə üç dəfə ardıcıl
tətbiqlə təsdiqlədi. Reyestr sürət üçün deyil, GÖRÜNÜRLÜK üçündür: hansı
faylın nə vaxt və kim tərəfindən tətbiq olunduğu sualının cavabı olmalıdır.
Ona görə `--all` bayrağı var: şübhə halında bütün zəncir yenidən işlədilir.

──────────────────────────────────────────────────────────────────────────────
İSTİFADƏ
──────────────────────────────────────────────────────────────────────────────
    python scripts/apply_migrations.py              # yalnız gözləyənlər
    python scripts/apply_migrations.py --all        # bütün zəncir (idempotent)
    python scripts/apply_migrations.py --dry-run    # nə tətbiq olunacaq
    python scripts/apply_migrations.py --vendor     # `migrations/vendor/` dəsti

DSN mənbəyi: `DATABASE_ADMIN_URL` (sahib rolu), yoxdursa `DATABASE_URL`.
Miqrasiya DDL yazır — tətbiq rolunun buna icazəsi olmamalıdır, ona görə sahib
DSN-i AYRICA dəyişəndədir.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from contextlib import suppress
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

#: Reyestr cədvəli `061`-də yaradılır. O tətbiq olunana qədər skript qeyd
#: APARA BİLMİR — bu, xəta deyil: birinci icra 061-i də tətbiq edir və
#: reyestr həmin andan işə düşür.
LEDGER = "kompasos.schema_migrations"


def _load_dotenv() -> None:
    """`.env`-i mühitə yükləyir — TƏTBİQ bunu etmir, yalnız bu skript edir.

    Səbəb `main.py::_check_dotenv` ilə eynidir: istehsalat maşınında `.env`
    ümumiyyətlə olmamalıdır. Skript isə inkişaf/quraşdırma alətidir və
    quraşdırıcının əlində məhz həmin fayl olur.
    """
    path = _REPO_ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _migration_files(*, vendor: bool) -> list[Path]:
    folder = _REPO_ROOT / "database" / "migrations"
    if vendor:
        return sorted((folder / "vendor").glob("*.sql"))
    return sorted(folder.glob("[0-9][0-9][0-9]_*.sql"))


def _ledger_state(cur: object) -> dict[str, str]:
    """`fayl adı → checksum`; reyestr hələ yoxdursa boş lüğət."""
    cursor = cur  # tip yalnız icra zamanı məlumdur (psycopg.Cursor)
    cursor.execute(f"SELECT to_regclass('{LEDGER}')")  # type: ignore[attr-defined]
    row = cursor.fetchone()  # type: ignore[attr-defined]
    if row is None or row[0] is None:
        return {}
    # `LEDGER` bu faylda təyin olunmuş SABİTdir, xarici giriş deyil.
    cursor.execute(f"SELECT filename, checksum FROM {LEDGER}")  # noqa: S608
    return dict(cursor.fetchall())  # type: ignore[attr-defined,no-any-return]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KompasOS miqrasiya icraçısı")
    parser.add_argument(
        "--all", action="store_true", help="reyestrdə olanları da yenidən tətbiq et"
    )
    parser.add_argument("--dry-run", action="store_true", help="yalnız siyahını göstər")
    parser.add_argument("--vendor", action="store_true", help="`migrations/vendor/` dəsti")
    args = parser.parse_args(argv)

    _load_dotenv()
    dsn = (
        os.environ.get("DATABASE_ADMIN_URL", "").strip()
        or os.environ.get("DATABASE_URL", "").strip()
    )
    if not dsn:
        sys.stderr.write("XƏTA: `DATABASE_ADMIN_URL` və ya `DATABASE_URL` təyin edilməyib.\n")
        return 2

    # İdxal funksiya daxilindədir: `--help` yolu psycopg olmadan da işləməlidir.
    import psycopg

    files = _migration_files(vendor=args.vendor)
    if not files:
        sys.stdout.write("Miqrasiya faylı tapılmadı.\n")
        return 0

    # `autocommit=True` MƏCBURİDİR: faylların ÖZ `BEGIN;`/`COMMIT;` cütü var.
    # Kənardan ikinci tranzaksiya açsaydıq, faylın `COMMIT`-i BİZİM
    # tranzaksiyanı bitirər və qalan ifadələr tranzaksiyadan KƏNARDA icra
    # olunardı — yəni uğursuzluqda yarımçıq nəticə qalardı.
    with psycopg.connect(dsn, connect_timeout=30, autocommit=True) as conn, conn.cursor() as cur:
        applied = _ledger_state(cur)
        pending: list[tuple[Path, str, str]] = []
        for path in files:
            digest = _checksum(path)
            known = applied.get(path.name)
            if known is None:
                pending.append((path, digest, "YENİ"))
            elif known != digest:
                # Tətbiqdən SONRA redaktə olunmuş fayl: eyni ad, başqa məzmun.
                pending.append((path, digest, "DƏYİŞİB"))
            elif args.all:
                pending.append((path, digest, "təkrar"))

        if not pending:
            sys.stdout.write(f"Gözləyən miqrasiya yoxdur ({len(applied)} qeyd).\n")
            return 0

        sys.stdout.write(f"{len(pending)} miqrasiya tətbiq olunacaq:\n")
        for path, _digest, reason in pending:
            sys.stdout.write(f"  [{reason}] {path.name}\n")
        if args.dry_run:
            return 0

        for path, digest, _reason in pending:
            started = time.monotonic()
            try:
                cur.execute(path.read_text(encoding="utf-8", errors="replace"))  # type: ignore[arg-type]
            except Exception as exc:  # icra dayanır: növbəti fayl əvvəlkindən asılı ola bilər
                # Tranzaksiya artıq bağlanmış ola bilər — `ROLLBACK` özü də
                # xəta verə bilər və o xəta ƏSAS səbəbi gizlətməməlidir.
                with suppress(Exception):
                    cur.execute("ROLLBACK")
                sys.stderr.write(f"\nXƏTA {path.name}: {exc}\n")
                return 1

            duration = int((time.monotonic() - started) * 1000)
            _record(cur, path.name, digest, duration)
            sys.stdout.write(f"  OK {path.name} ({duration} ms)\n")

    sys.stdout.write(f"\nBİTDİ: {len(pending)} miqrasiya.\n")
    return 0


def _record(cur: object, filename: str, digest: str, duration_ms: int) -> None:
    """Reyestrə yazır; cədvəl hələ yoxdursa SÜKUTLA keçir.

    Sükut burada haqlıdır: 061-dən ƏVVƏLKİ fayllar tətbiq olunarkən reyestr
    hələ mövcud deyil. Onlar 061-dən sonra `--all` ilə qeyd olunur.
    """
    cursor = cur
    cursor.execute(f"SELECT to_regclass('{LEDGER}')")  # type: ignore[attr-defined]
    row = cursor.fetchone()  # type: ignore[attr-defined]
    if row is None or row[0] is None:
        return
    # `LEDGER` bu modulda təyin olunmuş SABİTdir — xarici giriş deyil
    # (CLAUDE.md §4: dinamik `WHERE` yalnız sabit siyahıdan qurulur).
    statement = (
        f"INSERT INTO {LEDGER} (filename, checksum, duration_ms) "  # noqa: S608
        "VALUES (%s, %s, %s) "
        "ON CONFLICT (filename) DO UPDATE "
        "SET checksum = EXCLUDED.checksum, applied_at = now(), "
        "applied_by = current_user, duration_ms = EXCLUDED.duration_ms"
    )
    cursor.execute(statement, (filename, digest, duration_ms))  # type: ignore[attr-defined]


if __name__ == "__main__":  # pragma: no cover — CLI giriş nöqtəsi
    raise SystemExit(main())
