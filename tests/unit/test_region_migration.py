"""Region köçürməsinin qapıları — `scripts/migrate_region.py`.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL VAR
──────────────────────────────────────────────────────────────────────────────
Köçürmə İLDƏ BİR DƏFƏ (bəlkə heç) işlədilən skriptdir — yəni qüsuru məhz
ONA EHTİYAC OLAN gün, müştəri bazası köçürülərkən üzə çıxardı. Ən bahalı
səhv sinfi budur, ona görə skriptin BAZASIZ yoxlana bilən hissələri
(uyğunsuzluq müqayisəsi, alət tapılması, DSN qapısı) burada kilidlənir.

Bazaya toxunan hissə (`pg_dump`/`psql`) burada SINANMIR — o, canlı bazaya
qarşı əl ilə yoxlanılıb (`docs/region_migration.md`, ölçü: 265 KB dump,
`pg_dump` 18 / server 17).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "migrate_region.py"
_spec = importlib.util.spec_from_file_location("migrate_region", _SCRIPT)
assert _spec is not None and _spec.loader is not None
migrate_region = importlib.util.module_from_spec(_spec)
sys.modules["migrate_region"] = migrate_region
_spec.loader.exec_module(migrate_region)


def test_identical_dsns_are_rejected_before_anything_is_touched() -> None:
    """Mənbə = hədəf: köçürüləcək yer YOXDUR, bazaya heç qoşulmuruq da."""
    code = migrate_region.main(
        [
            "--source-dsn",
            "postgresql://a:b@h:5432/postgres",
            "--target-dsn",
            "postgresql://a:b@h:5432/postgres",
        ]
    )
    assert code == 2


def test_row_count_mismatch_is_reported_table_by_table() -> None:
    """Bir sətrin itməsi CƏDVƏL ADI ilə görünməlidir — «uğursuz oldu» kifayət etmir."""
    problems = migrate_region.compare_counts(
        {"fines": 120, "employees": 18, "audit_logs": 900},
        {"fines": 119, "employees": 18},
    )

    assert any("fines: mənbə 120, hədəf 119" in line for line in problems)
    assert any("audit_logs" in line and "CƏDVƏL YOXDUR" in line for line in problems)
    assert not any("employees" in line for line in problems)  # uyğun cədvəl SƏSSİZDİR


def test_the_migration_ledger_is_excluded_from_the_comparison() -> None:
    """`schema_migrations` hədəfdə ÖZ icrasından yaranır — fərq QÜSUR DEYİL.

    Mənbə köhnə buraxılışda qalıbsa reyestrdəki sətir sayı fərqli olur;
    müqayisə bunu «məlumat itdi» kimi oxusaydı, hər köçürmə yalançı-qırmızı
    ilə bitərdi.
    """
    assert migrate_region.compare_counts({"schema_migrations": 82}, {"schema_migrations": 61}) == []


def test_tool_lookup_prefers_path_then_falls_back_to_install_dirs(tmp_path: Path) -> None:
    """Alət `PATH`-da yoxdursa standart quraşdırma yollarına baxılır."""
    fake = tmp_path / ("pg_dump.exe" if sys.platform == "win32" else "pg_dump")
    fake.write_text("", encoding="utf-8")

    found = migrate_region.find_pg_tool("pg_dump", extra_dirs=(str(tmp_path),))

    assert found is not None
    assert found.name.startswith("pg_dump")


def test_a_missing_tool_returns_none_instead_of_raising(tmp_path: Path) -> None:
    """Alət yoxdursa bu, texniki xəta deyil — quraşdırma addımıdır.

    `None` qaytarılır ki, çağıran tərəf İNSANA ünvanlanmış mesaj yaza bilsin
    (skriptdə: «PostgreSQL client alətlərini quraşdırın»).
    """
    assert migrate_region.find_pg_tool("pg_dump_yoxdur_bu_ad", extra_dirs=(str(tmp_path),)) is None


def test_the_ledger_is_never_dumped() -> None:
    """Reyestr KÖÇÜRÜLMÜR: hədəfdə «kim tətbiq etdi» yazısı ÖZ icrasından gəlir."""
    assert "kompasos.schema_migrations" in migrate_region._EXCLUDED_TABLES
