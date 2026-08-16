"""Miqrasiya reyestri — «tətbiq olunub?» sualının maşınla oxunan cavabı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU QAPI VAR
──────────────────────────────────────────────────────────────────────────────
DB-5 canlı bazaya qarşı işlədi və 60 miqrasiyadan **11-inin heç vaxt tətbiq
olunmadığını** tapdı — 32 cədvəl yox idi, tətbiq isə onlara yazmağa çalışırdı.
Qüsur aylarla görünmədi, çünki tətbiq olunanın qeydi HEÇ YERDƏ saxlanmırdı.

Reyestr (miqrasiya 061) və icraçı (`scripts/apply_migrations.py`) həmin
boşluğu bağlayır. Bu testlər isə İCRAÇININ ÖZÜNÜ qoruyur: o, bazasız
işlədilə bilməz, ona görə yoxlanılan hissə fayl-seçmə və `checksum`
məntiqidir — yəni «hansı fayl gözləyir» qərarı.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any, Final

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT: Final = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from apply_migrations import (  # noqa: E402 - yol yuxarıda qurulur
    LEDGER,
    _checksum,
    _migration_files,
)

_LEDGER_MIGRATION: Final = (
    _REPO_ROOT / "database" / "migrations" / "061_schema_migration_ledger.sql"
)


def test_the_ledger_migration_exists_and_creates_the_table() -> None:
    """Reyestr cədvəli miqrasiya ilə gəlir — əl ilə yaradılmır."""
    text = _LEDGER_MIGRATION.read_text(encoding="utf-8", errors="replace")
    assert "CREATE TABLE IF NOT EXISTS schema_migrations" in text
    assert "checksum" in text
    assert "applied_at" in text
    # İdempotentlik və DOWN bloku — CLAUDE.md §7 tələbi.
    assert "IF NOT EXISTS" in text
    assert "-- DOWN" in text


def test_the_runner_points_at_the_table_the_migration_creates() -> None:
    """İcraçının gözlədiyi ad ilə miqrasiyanın yaratdığı ad EYNİDİR.

    İkisi ayrı fayldadır: biri Python, digəri SQL. Ad fərqi heç bir qapıda
    görünməzdi — icraçı sadəcə «reyestr yoxdur» deyib SÜKUTLA qeyd aparmazdı.
    """
    assert LEDGER == "kompasos.schema_migrations"
    assert "schema_migrations" in _LEDGER_MIGRATION.read_text(encoding="utf-8", errors="replace")


def test_the_runner_sees_every_numbered_migration() -> None:
    """Fayl seçimi qovluqdan gəlir — sabit siyahı YOXDUR.

    Sabit siyahı ilk əlavə olunan miqrasiyada köhnələrdi və yeni fayl sükutla
    tətbiq olunmadan qalardı — yəni DB-5-in tapdığı qüsurun eynisi.
    """
    files = _migration_files(vendor=False)
    on_disk = sorted((_REPO_ROOT / "database" / "migrations").glob("[0-9][0-9][0-9]_*.sql"))

    assert files == on_disk
    assert len(files) >= 61
    assert files[-1].name.startswith("061") or files[-1].name > "061"


def test_the_vendor_set_is_separate() -> None:
    """Vendor miqrasiyaları AYRI dəstdir — tenant bazasına tətbiq olunmur."""
    tenant = {p.name for p in _migration_files(vendor=False)}
    vendor = {p.name for p in _migration_files(vendor=True)}

    assert vendor
    assert not (tenant & vendor)
    assert all(p.parent.name == "vendor" for p in _migration_files(vendor=True))


def test_the_checksum_changes_when_the_file_changes(tmp_path: Path) -> None:
    """`checksum` faylın SONRADAN redaktəsini tutur.

    Yalnız fayl adı saxlansaydı, tətbiq olunmuş miqrasiyanın dəyişməsi görünməz
    qalardı: reyestr «tətbiq olunub» deyər, məzmun isə artıq başqa olardı — iki
    quraşdırma eyni ad altında MÜXTƏLİF sxem daşıyardı.
    """
    target = tmp_path / "001_test.sql"
    target.write_text("SELECT 1;", encoding="utf-8")
    first = _checksum(target)

    target.write_text("SELECT 2;", encoding="utf-8")
    assert _checksum(target) != first
    assert first == hashlib.sha256(b"SELECT 1;").hexdigest()


def test_the_runner_requires_a_dsn(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """DSN yoxdursa icraçı AYDIN xəta ilə dayanır, sükutla «heç nə yoxdur» demir."""
    import apply_migrations

    monkeypatch.setattr(apply_migrations, "_load_dotenv", lambda: None)
    monkeypatch.delenv("DATABASE_ADMIN_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert apply_migrations.main([]) == 2
    assert "DATABASE_ADMIN_URL" in capsys.readouterr().err
