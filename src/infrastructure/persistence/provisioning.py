r"""Avtomatik baza quruluşu — boş Supabase layihəsindən işlək sistemə (RECOVERY-1).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU MODUL LAZIM OLDU
──────────────────────────────────────────────────────────────────────────────
Yeni müştəridə quraşdırma ardıcıllığı belə idi: Supabase layihəsi aç → SQL
Editor-u aç → `schema.sql`-i kopyala-yapışdır → 67 miqrasiya faylını BİR-BİR
yapışdır. Hər addım əl işidir və biri buraxıldıqda nəticə SÜKUTLUDUR: tətbiq
açılır, lakin mövcud olmayan cədvələ yazmağa çalışır (DB-5 auditinin canlı
bazada tapdığı fakt — 60 miqrasiyadan 11-i heç vaxt tətbiq olunmamışdı).

Burada eyni iş BİR DÜYMƏ ilə görülür və qərar verən yerlər açıq yazılır.

──────────────────────────────────────────────────────────────────────────────
ƏHATƏ — YALNIZ BİZİM CƏDVƏLLƏR (ƏN VACİB QAYDA)
──────────────────────────────────────────────────────────────────────────────
Yaradılacaq cədvəllərin siyahısı YALNIZ paketlənmiş SQL fayllarından çıxarılır.
Bunun iki nəticəsi var və hər ikisi qəsdlidir:

    * Supabase-in öz sxemləri (`auth`, `storage`, `realtime`, `extensions`,
      `graphql`, `vault`) siyahıya DÜŞMÜR — onlar Supabase-in idarəsindədir və
      toxunulsa layihə sınar;
    * müştərinin `public` sxemində öz məqsədi üçün yaratdığı cədvəl də
      düşmür — və o, hesabatda «artıq cədvəl» kimi İŞARƏLƏNMİR. Tanımadığımız
      cədvəl haqqında heç nə demirik, çünki bizim işimiz deyil.

Siyahını ƏL İLƏ yazmaq variantı rədd edildi: bir gün fayllardan geri qalar və
«çatışan cədvəl» hesabatı səssizcə yalan danışardı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `scripts/apply_migrations.py` TƏKRAR YAZILMIR — VƏ NİYƏ TAM DA ONU
ÇAĞIRMIRIQ
──────────────────────────────────────────────────────────────────────────────
Skript `scripts/` altındadır və QƏSDƏN paketə düşmür (hazırlayıcı aləti
müştəri paketində olmamalıdır — `dev_panel.py` ilə eyni qayda). Reyestr
məntiqi isə eynidir və İKİ YERDƏ FƏRQLƏNMƏMƏLİDİR, ona görə burada həmin
qaydalar TƏKRARLANIR, lakin bir fərqlə: mənbə fayl sistemi deyil, PAKETƏ
salınmış resursdur (`sys._MEIPASS`). Fərq sənədləşdirilib, çünki iki nüsxə
bir gün ayrıla bilər — ayrılmanı `tests/unit/test_database_provisioning.py`
tutur (sıra, checksum, idempotentlik).

──────────────────────────────────────────────────────────────────────────────
MƏLUMAT VARSA — İNSAN TƏSDİQİ
──────────────────────────────────────────────────────────────────────────────
Üç hal ayrılır və hər biri fərqli davranır:

    boş baza          → sual verilmir, quruluş başlayır;
    cədvəllər var,
    sətir yoxdur      → «qismən qurulub» — YALNIZ çatışanlar əlavə olunur;
    sətirlər var      → istifadəçi `QUR` sözünü ƏL İLƏ yazmalıdır.

Üçüncü hal üçün «Davam et?» düyməsi KİFAYƏT ETMİR: refleksə çevrilmiş bir
klik real məlumat üzərində icra oluna bilər. Söz yazmaq refleksi qırır.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from src.shared.logger import LogChannel, get_logger
from src.shared.runtime import bundle_root, deployment_root

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

_log = get_logger(__name__)
_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

#: Miqrasiya reyestrinin tam adı (`migrations/061`).
LEDGER: Final[str] = "kompasos.schema_migrations"

#: Bizim sxem — `information_schema` sorğusu YALNIZ ona baxır.
APP_SCHEMA: Final[str] = "kompasos"

#: Məlumatı olan bazada tələb olunan təsdiq sözü.
CONFIRMATION_WORD: Final[str] = "QUR"

#: Paketdə/repozitoriyada SQL faylların yeri.
_MIGRATIONS_DIR: Final[tuple[str, str]] = ("database", "migrations")
_SCHEMA_FILE: Final[tuple[str, str]] = ("database", "schema.sql")

#: `NNN_ad.sql` — vendor dəsti (`migrations/vendor/`) BURAYA DÜŞMÜR: o,
#: təchizatçının öz mərkəzi bazası üçündür və müştəri quraşdırmasında
#: yaradılsa, müştəri bazasında yad cədvəllər peyda olardı.
_MIGRATION_PATTERN: Final[str] = "[0-9][0-9][0-9]_*.sql"

#: `CREATE TABLE [IF NOT EXISTS] [sxem.]ad` — sxem prefiksi opsionaldır,
#: çünki fayllar `SET search_path TO kompasos` ilə başlayır.
_CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:(\w+)\.)?(\w+)", re.IGNORECASE
)

#: Sətir sayına baxılan cədvəllər — «bu bazada iş görülüb?» sualının cavabı.
#: HAMISINA baxmaq onlarla sorğu deməkdir; bunlar isə sistemin İLK dolan
#: cədvəlləridir, yəni biri boş deyilsə baza artıq işlənib.
_DATA_PROBE_TABLES: Final[tuple[str, ...]] = (
    "employees",
    "fines",
    "leave_requests",
    "attendance_records",
)


@dataclass(frozen=True)
class MigrationScript:
    """Bir miqrasiya faylı — adı, məzmunu və checksum-u."""

    name: str
    sql: str
    checksum: str


@dataclass(frozen=True)
class DatabaseState:
    """Quruluşdan ƏVVƏLKİ vəziyyət — qərar məhz buna görə verilir."""

    existing_tables: frozenset[str]
    #: `(cədvəl, sətir sayı)` — YALNIZ sıfırdan böyük olanlar.
    populated_tables: tuple[tuple[str, int], ...]

    @property
    def is_empty(self) -> bool:
        """Bizim heç bir cədvəlimiz yoxdur — təmiz quraşdırma."""
        return not self.existing_tables

    @property
    def requires_confirmation(self) -> bool:
        """Bazada MƏLUMAT var — bir kliklə davam etmək olmaz.

        Şərt cədvəlin MÖVCUDLUĞUNA yox, SƏTİRLƏRƏ baxır: boş cədvəllər
        yarımçıq quraşdırmanın normal nəticəsidir və orada təsdiq tələb etmək
        istifadəçini əbəs yorardı.
        """
        return bool(self.populated_tables)

    def accepts(self, answer: str) -> bool:
        """Yazılan söz təsdiq sayılırmı."""
        return answer.strip().upper() == CONFIRMATION_WORD


@dataclass(frozen=True)
class ProvisionReport:
    """Quruluşun nəticəsi — ekranda göstərilən yeganə həqiqət mənbəyi."""

    applied: tuple[str, ...]
    skipped: tuple[str, ...]
    missing_after: tuple[str, ...]
    error: str = ""

    @property
    def succeeded(self) -> bool:
        return not self.error and not self.missing_after


# --------------------------------------------------------------------------- #
# Paketlənmiş SQL resursları
# --------------------------------------------------------------------------- #


def _sql_root() -> Path | None:
    """`database/` qovluğunun kökü — əvvəlcə paketin İÇİ, sonra yanı.

    Sıra `widgets/brand_assets.py`-dakı ilə EYNİDİR və qəsdən: hər modul öz
    yolunu qursaydı, biri unudular və qüsur YALNIZ paketlənmiş buraxılışda
    üzə çıxardı.
    """
    for root in (bundle_root(), deployment_root()):
        if root is None:
            continue
        candidate = root / _MIGRATIONS_DIR[0]
        if candidate.is_dir():
            return candidate
    return None


def migration_scripts() -> tuple[MigrationScript, ...]:
    """Tətbiq olunacaq bütün miqrasiyalar — FAYL ADINA görə sıralı.

    Sıra əlifba sırasıdır və bu, kifayətdir: fayllar `NNN_` prefiksi ilə
    başlayır. Sıra pozulsaydı, sütun əlavə edən miqrasiya onu işlədən
    miqrasiyadan SONRA icra olunardı.
    """
    root = _sql_root()
    if root is None:
        return ()
    folder = root / _MIGRATIONS_DIR[1]
    if not folder.is_dir():
        return ()
    scripts: list[MigrationScript] = []
    for path in sorted(folder.glob(_MIGRATION_PATTERN)):
        raw = path.read_bytes()
        scripts.append(
            MigrationScript(
                name=path.name,
                sql=raw.decode("utf-8"),
                checksum=hashlib.sha256(raw).hexdigest(),
            )
        )
    return tuple(scripts)


def base_schema_sql() -> str:
    """`schema.sql` — bazis sxem (tək başına tam quraşdırma).

    Miqrasiyalardan ƏVVƏL tətbiq olunur: `CLAUDE.md` §7-yə görə schema.sql
    miqrasiya SÜTUNLARINI ehtiva etmir, yəni ikisi ARDICIL işləyir.
    """
    root = _sql_root()
    if root is None:
        return ""
    path = root / _SCHEMA_FILE[1]
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def expected_tables() -> frozenset[str]:
    """Paketlənmiş SQL-dən çıxarılan cədvəl adları (bax modul başlığı).

    Yalnız `kompasos` sxemi (və ya sxemsiz — fayllar `search_path` qurur)
    sayılır: `auth.users`, `storage.objects` kimi Supabase cədvəlləri açıq
    sxem prefiksi ilə yazılsaydı belə siyahıya DÜŞMÜR.
    """
    names: set[str] = set()
    for sql in (base_schema_sql(), *(script.sql for script in migration_scripts())):
        for schema, table in _CREATE_TABLE.findall(sql):
            if schema and schema.lower() != APP_SCHEMA:
                continue
            names.add(table.lower())
    return frozenset(names)


def missing_tables(*, expected: Iterable[str], existing: Iterable[str]) -> tuple[str, ...]:
    """Gözlənilən, lakin bazada olmayan cədvəllər — SIRALI.

    Tanımadığımız cədvəllər (müştərinin öz cədvəli, Supabase-in daxili
    obyektləri) nəticəyə HEÇ CÜR düşmür — nə «artıq», nə «naməlum» kimi.
    """
    present = {name.lower() for name in existing}
    return tuple(sorted(name for name in {n.lower() for n in expected} if name not in present))


# --------------------------------------------------------------------------- #
# Baza vəziyyəti
# --------------------------------------------------------------------------- #


def existing_tables(cursor: Any) -> frozenset[str]:
    """`information_schema`-dan YALNIZ bizim sxemin cədvəlləri.

    Sorğu `table_schema = 'kompasos'` ilə məhdudlaşır: `public` sxemə
    baxsaydıq, müştərinin öz cədvəlləri və Supabase obyektləri nəticəyə
    düşərdi (bax modul başlığı, «ƏHATƏ»).
    """
    cursor.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
        (APP_SCHEMA,),
    )
    return frozenset(str(row[0]).lower() for row in cursor.fetchall())


def inspect_database(cursor: Any) -> DatabaseState:
    """Quruluşdan əvvəlki vəziyyəti oxuyur (cədvəllər + sətir sayları)."""
    existing = existing_tables(cursor)
    populated: list[tuple[str, int]] = []
    for table in _DATA_PROBE_TABLES:
        if table not in existing:
            continue
        # Cədvəl adı SABİT siyahıdandır, istifadəçi mətni deyil.
        cursor.execute(f"SELECT COUNT(*) FROM {APP_SCHEMA}.{table}")  # noqa: S608
        row = cursor.fetchone()
        count = int(row[0]) if row else 0
        if count:
            populated.append((table, count))
    return DatabaseState(existing_tables=existing, populated_tables=tuple(populated))


def ledger_state(cursor: Any) -> dict[str, str]:
    """`fayl adı → checksum`; reyestr hələ yoxdursa boş lüğət."""
    cursor.execute(f"SELECT to_regclass('{LEDGER}')")
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return {}
    cursor.execute(f"SELECT filename, checksum FROM {LEDGER}")  # noqa: S608
    return {str(name): str(digest) for name, digest in cursor.fetchall()}


def pending_scripts(
    cursor: Any, scripts: Sequence[MigrationScript] | None = None
) -> tuple[MigrationScript, ...]:
    """Hələ tətbiq olunmamış (və ya SONRADAN redaktə olunmuş) miqrasiyalar.

    Checksum müqayisəsi qəsdəndir: eyni adlı, lakin məzmunu dəyişmiş fayl
    «tətbiq olunub» sayılsaydı, düzəliş müştəri bazasına heç vaxt çatmazdı.
    """
    applied = ledger_state(cursor)
    candidates = tuple(scripts) if scripts is not None else migration_scripts()
    return tuple(script for script in candidates if applied.get(script.name) != script.checksum)


def _record(cursor: Any, script: MigrationScript, duration_ms: int) -> None:
    """Reyestrə yazır; cədvəl hələ yoxdursa SÜKUTLA keçir.

    Sükut burada haqlıdır: reyestrin ÖZÜ `migrations/061`-də yaranır, yəni
    ondan əvvəlki fayllar tətbiq olunarkən cədvəl hələ mövcud deyil.
    """
    cursor.execute(f"SELECT to_regclass('{LEDGER}')")
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return
    statement = (
        f"INSERT INTO {LEDGER} (filename, checksum, duration_ms) "  # noqa: S608
        "VALUES (%s, %s, %s) "
        "ON CONFLICT (filename) DO UPDATE "
        "SET checksum = EXCLUDED.checksum, applied_at = now(), "
        "applied_by = current_user, duration_ms = EXCLUDED.duration_ms"
    )
    cursor.execute(statement, (script.name, script.checksum, duration_ms))


def provision(
    cursor: Any,
    *,
    scripts: Sequence[MigrationScript] | None = None,
    schema_sql: str | None = None,
    confirmation: str = "",
    progress: Callable[[int, int, str], None] | None = None,
) -> ProvisionReport:
    r"""Bazanı qurur: bazis sxem → gözləyən miqrasiyalar → yoxlama.

    ──────────────────────────────────────────────────────────────────────────
    KURSOR KƏNARDAN VERİLİR
    ──────────────────────────────────────────────────────────────────────────
    Bağlantını bu funksiya AÇMIR: çağıran tərəf `autocommit=True` ilə açır və
    səbəb `scripts/apply_migrations.py`-dakı ilə eynidir — fayllarda ÖZ
    `BEGIN;`/`COMMIT;` cütü var və kənardan ikinci tranzaksiya açsaq, faylın
    `COMMIT`-i BİZİM tranzaksiyanı bitirər, qalan ifadələr isə tranzaksiyadan
    KƏNARDA icra olunardı.

    ──────────────────────────────────────────────────────────────────────────
    UĞURSUZLUQDA İCRA DAYANIR
    ──────────────────────────────────────────────────────────────────────────
    Növbəti fayl əvvəlkinin yaratdığı sütundan asılı ola bilər. «Xətanı keç,
    davam et» davranışı yarımçıq sxem qoyar və nasazlıq aylar sonra, tamamilə
    başqa yerdə üzə çıxardı.

    Args:
        confirmation: Bazada MƏLUMAT varsa `QUR` sözü tələb olunur.
        progress: `(neçəsi, cəmi, fayl adı)` — hər tətbiqdən SONRA çağırılır.
    """
    import time  # noqa: PLC0415 — yalnız ölçmə üçün

    state = inspect_database(cursor)
    if state.requires_confirmation and not state.accepts(confirmation):
        rows = ", ".join(f"{table} ({count})" for table, count in state.populated_tables)
        return ProvisionReport(
            applied=(),
            skipped=(),
            missing_after=(),
            error=(
                f"Bu bazada artıq məlumat var: {rows}. Davam etmək data itkisinə "
                f"səbəb ola bilər — təsdiq üçün «{CONFIRMATION_WORD}» sözünü yazın."
            ),
        )

    # Bazis sxem YALNIZ tamamilə boş bazada tətbiq olunur: mövcud quraşdırmada
    # onu təkrar icra etmək `CREATE TABLE IF NOT EXISTS` sayəsində zərərsizdir,
    # lakin mənasız minlərlə ifadə deməkdir və `schema.sql` miqrasiya
    # sütunlarını ehtiva etmir (CLAUDE.md §7) — sıra pozulardı.
    base = base_schema_sql() if schema_sql is None else schema_sql
    if state.is_empty and base.strip():
        try:
            cursor.execute(base)
        except Exception as exc:
            return ProvisionReport(
                applied=(), skipped=(), missing_after=(), error=f"schema.sql: {exc}"
            )

    candidates = tuple(scripts) if scripts is not None else migration_scripts()
    pending = pending_scripts(cursor, candidates)
    skipped = tuple(s.name for s in candidates if s not in pending)

    applied: list[str] = []
    total = len(pending)
    for index, script in enumerate(pending, start=1):
        started = time.monotonic()
        try:
            cursor.execute(script.sql)
        except Exception as exc:
            _log.error("PROVISION_FAILED", extra={"file": script.name, "error": str(exc)})
            return ProvisionReport(
                applied=tuple(applied),
                skipped=skipped,
                missing_after=(),
                error=f"{script.name}: {exc}",
            )
        _record(cursor, script, int((time.monotonic() - started) * 1000))
        applied.append(script.name)
        if progress is not None:
            progress(index, total, script.name)

    missing = missing_tables(expected=expected_tables(), existing=existing_tables(cursor))
    _audit_log.info(
        "DATABASE_PROVISIONED",
        extra={"applied": len(applied), "skipped": len(skipped), "missing": len(missing)},
    )
    return ProvisionReport(applied=tuple(applied), skipped=skipped, missing_after=missing, error="")


__all__ = [
    "APP_SCHEMA",
    "CONFIRMATION_WORD",
    "LEDGER",
    "DatabaseState",
    "MigrationScript",
    "ProvisionReport",
    "base_schema_sql",
    "existing_tables",
    "expected_tables",
    "inspect_database",
    "ledger_state",
    "migration_scripts",
    "missing_tables",
    "pending_scripts",
    "provision",
]
