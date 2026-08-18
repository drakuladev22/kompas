"""Avtomatik baza quruluşunun NÜVƏSİ (RECOVERY-1 Faza 3).

──────────────────────────────────────────────────────────────────────────────
NƏYİ QORUYUR
──────────────────────────────────────────────────────────────────────────────
Bu modul MÜŞTƏRİNİN bazasında DDL icra edir — yəni səhvin qiyməti ən yüksək
olan yerdir. Üç zəmanət ölçülür:

    1. **ƏHATƏ** — yaradılacaq cədvəllərin siyahısı YALNIZ paketlənmiş
       miqrasiya fayllarından gəlir. Supabase-in öz sxemləri (`auth`,
       `storage`, `realtime`…) və müştərinin öz cədvəlləri siyahıda OLA
       BİLMƏZ; onlar «tanınmayan» kimi də işarələnmir — sadəcə görünmür.
    2. **QORUYUCU** — bazada məlumat varsa əməliyyat AVTOMATİK davam etmir;
       insanın açıq təsdiqi tələb olunur.
    3. **İDEMPOTENTLİK** — artıq tətbiq olunmuş miqrasiya təkrar icra
       edilmir (reyestr `kompasos.schema_migrations`).

Bu fayl BAZAYA QOŞULMUR: qoşulma qatı ayrıca, sahtə kursor ilə yoxlanılır —
ölçülən şey QƏRARdır, psycopg deyil.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# 1. Paketlənmiş miqrasiyalar
# --------------------------------------------------------------------------- #


def test_the_migration_set_is_discovered_and_ordered() -> None:
    """Sıra FAYL ADINDANdır: `067` `012`-dən sonra tətbiq olunmalıdır."""
    from src.infrastructure.persistence.provisioning import migration_scripts

    scripts = migration_scripts()

    assert scripts, "miqrasiya faylı tapılmadı — paketləmə qırılıb"
    names = [script.name for script in scripts]
    assert names == sorted(names)
    assert all(script.sql.strip() for script in scripts), "boş miqrasiya faylı"


def test_every_script_carries_its_checksum() -> None:
    """Reyestr checksum saxlayır — sonradan REDAKTƏ olunmuş fayl görünməlidir."""
    from src.infrastructure.persistence.provisioning import migration_scripts

    for script in migration_scripts():
        assert len(script.checksum) == 64, f"{script.name}: SHA-256 gözlənilir"


# --------------------------------------------------------------------------- #
# 2. ƏHATƏ — yalnız KompasOS-un öz cədvəlləri
# --------------------------------------------------------------------------- #


def test_expected_tables_come_only_from_the_packaged_sql() -> None:
    """Siyahı miqrasiya fayllarından çıxarılır, əl ilə YAZILMIR.

    Əl ilə yazılmış siyahı bir gün fayllardan geri qalar və «çatışan cədvəl»
    hesabatı SƏHV nəticə verərdi.
    """
    from src.infrastructure.persistence.provisioning import expected_tables

    tables = expected_tables()

    assert "employees" in tables
    assert "registered_devices" in tables
    assert "schema_migrations" in tables


@pytest.mark.parametrize(
    "foreign",
    ["users", "objects", "subscription", "test_xarici_cedvel", "buckets"],
)
def test_supabase_and_customer_tables_are_never_expected(foreign: str) -> None:
    """Supabase-in `auth.users`, `storage.objects` və müştərinin öz cədvəli.

    Bunlar siyahıya düşsəydi, «çatışır» kimi görünər və quruluş onları
    yaratmağa çalışardı — Supabase layihəsini sındıran ssenari.
    """
    from src.infrastructure.persistence.provisioning import expected_tables

    assert foreign not in expected_tables()


def test_unknown_tables_are_ignored_not_reported() -> None:
    """Tanımadığımız cədvəl haqqında HEÇ NƏ demirik — «artıq» da yazmırıq."""
    from src.infrastructure.persistence.provisioning import missing_tables

    missing = missing_tables(
        expected=frozenset({"employees", "fines"}),
        existing=frozenset({"employees", "test_xarici_cedvel", "musteri_cedveli"}),
    )

    assert missing == ("fines",)


# --------------------------------------------------------------------------- #
# 3. QORUYUCU — məlumat varsa avtomatik davam yoxdur
# --------------------------------------------------------------------------- #


def test_an_empty_database_needs_no_confirmation() -> None:
    """Boş bazada təsdiq tələb etmək istifadəçini əbəs yorardı."""
    from src.infrastructure.persistence.provisioning import DatabaseState

    state = DatabaseState(existing_tables=frozenset(), populated_tables=())

    assert state.is_empty
    assert not state.requires_confirmation


def test_a_partially_installed_database_only_adds_what_is_missing() -> None:
    """Mövcud cədvələ TOXUNULMUR — yalnız çatışan əlavə olunur."""
    from src.infrastructure.persistence.provisioning import DatabaseState

    state = DatabaseState(existing_tables=frozenset({"employees"}), populated_tables=())

    assert not state.is_empty
    assert not state.requires_confirmation, "boş cədvəllər təsdiq tələb etmir"


def test_a_database_with_rows_demands_an_explicit_word() -> None:
    """«QUR» sözü ƏL İLƏ yazılmalıdır — bir kliklə data itkisi olmasın."""
    from src.infrastructure.persistence.provisioning import (
        CONFIRMATION_WORD,
        DatabaseState,
    )

    state = DatabaseState(
        existing_tables=frozenset({"employees"}), populated_tables=(("employees", 42),)
    )

    assert state.requires_confirmation
    assert state.accepts(CONFIRMATION_WORD)
    # Yaxın, lakin FƏRQLİ cavab qəbul edilmir — «hə» refleks cavabıdır.
    assert not state.accepts("hə")
    assert not state.accepts("")
    assert not state.accepts("QURMA")


def test_the_confirmation_is_case_insensitive_but_not_empty() -> None:
    """İstifadəçi «qur» yazsa da qəbul edilir — söz TƏLƏBİ qalır."""
    from src.infrastructure.persistence.provisioning import DatabaseState

    state = DatabaseState(existing_tables=frozenset({"fines"}), populated_tables=(("fines", 3),))

    assert state.accepts("qur")
    assert state.accepts("  QUR  ")


# --------------------------------------------------------------------------- #
# 4. İDEMPOTENTLİK — reyestrdəki miqrasiya təkrar icra edilmir
# --------------------------------------------------------------------------- #


class _FakeCursor:
    """Reyestr sorğularına cavab verən minimal kursor."""

    def __init__(self, ledger: dict[str, str], tables: set[str]) -> None:
        self._ledger = ledger
        self._tables = tables
        self.executed: list[str] = []
        self._rows: list[Any] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append(sql)
        lowered = sql.lower()
        if "to_regclass" in lowered:
            self._rows = [("kompasos.schema_migrations",)] if self._ledger else [(None,)]
        elif "from kompasos.schema_migrations" in lowered:
            self._rows = list(self._ledger.items())
        elif "information_schema.tables" in lowered:
            self._rows = [(name,) for name in sorted(self._tables)]
        else:
            self._rows = []

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[Any]:
        return self._rows


def test_already_applied_migrations_are_skipped() -> None:
    """Təkrar işlədilmə data korlamamalıdır (db1.md: İDEMPOTENTLİK)."""
    from src.infrastructure.persistence.provisioning import (
        migration_scripts,
        pending_scripts,
    )

    scripts = migration_scripts()
    ledger = {scripts[0].name: scripts[0].checksum}
    cursor = _FakeCursor(ledger, set())

    pending = pending_scripts(cursor, scripts)

    assert scripts[0].name not in [script.name for script in pending]
    assert len(pending) == len(scripts) - 1


def test_an_edited_migration_is_applied_again() -> None:
    """Eyni ad, BAŞQA məzmun — reyestr checksum saxladığı üçün görünür."""
    from src.infrastructure.persistence.provisioning import (
        migration_scripts,
        pending_scripts,
    )

    scripts = migration_scripts()
    cursor = _FakeCursor({scripts[0].name: "0" * 64}, set())

    pending = pending_scripts(cursor, scripts)

    assert pending[0].name == scripts[0].name


# --------------------------------------------------------------------------- #
# 5. İCRA — addımlar, qoruyucu və hesabat
# --------------------------------------------------------------------------- #


class _RecordingCursor(_FakeCursor):
    """İcra edilən SQL-i və reyestr yazılarını toplayan kursor."""

    def __init__(
        self,
        ledger: dict[str, str] | None = None,
        tables: set[str] | None = None,
        *,
        rows: dict[str, int] | None = None,
        fail_on: str = "",
        ledger_exists: bool = True,
    ) -> None:
        super().__init__(ledger or {}, tables or set())
        self._rows_by_table = rows or {}
        self._fail_on = fail_on
        # Reyestr cədvəli `migrations/061`-də yaranır. Ondan ƏVVƏLKİ fayllar
        # tətbiq olunarkən o, hələ mövcud deyil və yazı SÜKUTLA keçir — bu,
        # `_record`-un sənədləşdirilmiş davranışıdır. Testlərin çoxu artıq
        # 061-dən sonrakı vəziyyəti modelləşdirir.
        self._ledger_exists = ledger_exists
        self.recorded: list[tuple[str, str]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        lowered = sql.lower()
        if self._fail_on and self._fail_on in sql:
            raise RuntimeError("sintaksis xətası")
        if "to_regclass" in lowered:
            self._rows = [("kompasos.schema_migrations",)] if self._ledger_exists else [(None,)]
            return
        if lowered.startswith("insert into kompasos.schema_migrations"):
            self.recorded.append((str(params[0]), str(params[1])))
            self._ledger[str(params[0])] = str(params[1])
            self._rows = []
            return
        if lowered.startswith("select count(*)"):
            table = sql.rsplit(".", 1)[-1].strip()
            self._rows = [(self._rows_by_table.get(table, 0),)]
            return
        super().execute(sql, params)
        # Sxem/miqrasiya icrası cədvəlləri "yaradır" — sonrakı yoxlama üçün.
        if "create table" in lowered:
            self._tables.update({"employees", "fines", "schema_migrations"})


def _cursor(**kwargs: Any) -> Any:
    return _RecordingCursor(**kwargs)


def test_provisioning_applies_pending_migrations_and_records_them() -> None:
    """Hər tətbiq olunan fayl reyestrə düşməlidir — yoxsa təkrar icra olunar."""
    from src.infrastructure.persistence.provisioning import migration_scripts, provision

    cursor = _cursor()
    scripts = migration_scripts()[:2]

    report = provision(cursor, scripts=scripts, schema_sql="CREATE TABLE employees ();")

    assert report.applied == tuple(s.name for s in scripts)
    assert [name for name, _ in cursor.recorded] == list(report.applied)


def test_provisioning_reports_progress_for_every_step() -> None:
    """«12/40 cədvəl quruldu…» — istifadəçi donmuş ekrana baxmamalıdır."""
    from src.infrastructure.persistence.provisioning import migration_scripts, provision

    seen: list[tuple[int, int]] = []
    scripts = migration_scripts()[:3]

    provision(
        _cursor(),
        scripts=scripts,
        schema_sql="",
        progress=lambda done, total, _name: seen.append((done, total)),
    )

    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_provisioning_refuses_to_touch_a_populated_database() -> None:
    """Təsdiq sözü YAZILMAYIBSA heç bir SQL icra olunmur."""
    from src.infrastructure.persistence.provisioning import migration_scripts, provision

    cursor = _cursor(tables={"employees"}, rows={"employees": 12})

    report = provision(cursor, scripts=migration_scripts()[:1], schema_sql="")

    assert not report.succeeded
    assert "QUR" in report.error
    assert cursor.recorded == [], "təsdiqsiz miqrasiya tətbiq olundu"


def test_the_confirmation_word_unlocks_the_operation() -> None:
    """İnsan açıq təsdiq verdikdə əməliyyat davam edir."""
    from src.infrastructure.persistence.provisioning import (
        CONFIRMATION_WORD,
        migration_scripts,
        provision,
    )

    cursor = _cursor(tables={"employees"}, rows={"employees": 12})

    report = provision(
        cursor,
        scripts=migration_scripts()[:1],
        schema_sql="",
        confirmation=CONFIRMATION_WORD,
    )

    assert report.applied, "təsdiqdən sonra da tətbiq olunmadı"


def test_the_ledger_write_is_skipped_before_migration_061_creates_it() -> None:
    """Reyestr cədvəli hələ yoxdursa yazı SÜKUTLA keçilir — çökmə yox.

    061-dən əvvəlki fayllar məhz belə tətbiq olunur; sonradan `--all` ilə
    qeyd edilirlər (`scripts/apply_migrations.py::_record` ilə eyni qayda).
    """
    from src.infrastructure.persistence.provisioning import migration_scripts, provision

    cursor = _cursor(ledger_exists=False)

    report = provision(cursor, scripts=migration_scripts()[:2], schema_sql="")

    assert len(report.applied) == 2
    assert cursor.recorded == []


def test_a_failing_migration_stops_the_run_and_reports_the_file() -> None:
    """Növbəti fayl əvvəlkindən ASILI ola bilər — icra dayanmalıdır."""
    from src.infrastructure.persistence.provisioning import MigrationScript, provision

    scripts = (
        MigrationScript(name="001_ok.sql", sql="CREATE TABLE employees ();", checksum="a" * 64),
        MigrationScript(name="002_pis.sql", sql="SINIQ SQL", checksum="b" * 64),
        MigrationScript(name="003_sonra.sql", sql="SELECT 1;", checksum="c" * 64),
    )
    cursor = _cursor(fail_on="SINIQ SQL")

    report = provision(cursor, scripts=scripts, schema_sql="")

    assert report.applied == ("001_ok.sql",)
    assert "002_pis.sql" in report.error
    assert "003_sonra.sql" not in report.applied
