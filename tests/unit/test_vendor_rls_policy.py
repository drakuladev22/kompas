"""Vendor bazasının RLS zəmanətləri — SQL mənbəyindən yoxlanılır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ STATİK MƏTN ÜZƏRİNDƏ
──────────────────────────────────────────────────────────────────────────────
`database/tests/test_vendor_rls.sql` HƏQİQİ bazaya qarşı işləyir və beş
ssenarini icra edir (rol keçidi, imtiyaz rəddi, RPC sadalama qapısı). Lakin o,
yalnız baza əlçatan olduqda icra oluna bilir — adi `pytest` dəstində isə
PostgreSQL yoxdur.

Aradakı boşluq real risk daşıyır: kimsə vendor miqrasiyasına yeni cədvəl əlavə
edir, RLS sətrini əlavə etməyi unudur, testlər isə yaşıl qalır — çünki həmin
qatı heç kim yoxlamır. Bu modul məhz o boşluğu bağlayır: sual «siyasət hələ də
YAZILIBMI», cavab isə miqrasiya mətnindən oxunur.

──────────────────────────────────────────────────────────────────────────────
NƏ ÖLÇÜLMÜR
──────────────────────────────────────────────────────────────────────────────
Siyasətin FAKTİKİ davranışı (kimin nə gördüyü) burada ölçülmür — onu yalnız
canlı baza deyə bilər. Ona görə SQL testi ƏVƏZ EDİLMİR, tamamlanır.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT: Final = Path(__file__).resolve().parents[2]
_VENDOR_DIR: Final = _REPO_ROOT / "database" / "migrations" / "vendor"
_SQL_TEST: Final = _REPO_ROOT / "database" / "tests" / "test_vendor_rls.sql"


def _read(name: str) -> str:
    return (_VENDOR_DIR / name).read_text(encoding="utf-8", errors="replace")


def _vendor_tables() -> set[str]:
    schema = _read("001_vendor_schema.sql")
    return {
        match.group(1)
        for match in re.finditer(
            r"CREATE TABLE\s+(?:IF NOT EXISTS\s+)?([a-z_][a-z0-9_]*)", schema, re.IGNORECASE
        )
    }


def test_every_vendor_table_is_covered_by_the_rls_loop() -> None:
    """001-də yaradılan HƏR cədvəl 002-nin RLS siyahısında olmalıdır.

    Siyahı əl ilə yazılır (dinamik dövr onu oxuyur), yəni yeni cədvəl əlavə
    edən adam bir sətri unuda bilər. Unudulan cədvəl RLS-siz qalar və
    `PUBLIC`-ə verilmiş hər hansı gələcək imtiyaz onu tam açardı.
    """
    rls = _read("002_vendor_rls.sql")
    missing = sorted(table for table in _vendor_tables() if f"'{table}'" not in rls)
    assert not missing, f"RLS siyahısında olmayan cədvəl(lər): {missing}"


def test_rls_is_both_enabled_and_forced() -> None:
    """`ENABLE` tək başına KİFAYƏT ETMİR — sahib rolu onu yan keçir."""
    rls = _read("002_vendor_rls.sql")
    assert "ENABLE ROW LEVEL SECURITY" in rls
    assert "FORCE ROW LEVEL SECURITY" in rls, (
        "`FORCE` yoxdursa cədvəlin sahibi (miqrasiyanı tətbiq edən rol) bütün "
        "siyasətləri yan keçir və RLS yalnız kağız üzərində qalır"
    )


def test_policies_target_only_the_vendor_role() -> None:
    """Siyasət `TO kompasos_vendor`-dur; `anon`/`authenticated`/`PUBLIC` YOX."""
    rls = _read("002_vendor_rls.sql")
    policy_lines = [line for line in rls.splitlines() if "CREATE POLICY" in line]
    assert policy_lines, "heç bir siyasət tapılmadı"
    joined = " ".join(policy_lines) + rls[rls.find("CREATE POLICY") :]
    assert "TO kompasos_vendor" in joined
    for role in ("TO PUBLIC", "TO anon", "TO authenticated"):
        assert role not in joined, f"siyasət `{role}` üçün açılıb"


def test_no_table_privileges_are_granted_to_client_roles() -> None:
    """`anon`/`authenticated` CƏDVƏL imtiyazı ALMIR.

    Sxem `USAGE` və funksiya `EXECUTE` icazəsi VERİLİR (RPC üçün lazımdır) —
    onlar cədvəl məzmununa çıxış vermir. Cədvəl imtiyazı verilsəydi, RLS tək
    qat qalardı və qərar «müştəri vendor bazasına yazmır» pozulardı.
    """
    for name in ("002_vendor_rls.sql", "003_license_status_rpc.sql"):
        text = _read(name)
        for grant in re.finditer(
            r"GRANT\s+([^;]+?)\s+TO\s+([^;]+);", text, re.IGNORECASE | re.DOTALL
        ):
            what, whom = grant.group(1), grant.group(2)
            if "anon" not in whom and "authenticated" not in whom:
                continue
            allowed = "USAGE ON SCHEMA" in what.upper() or "EXECUTE ON FUNCTION" in what.upper()
            assert allowed, f"{name}: müştəri roluna icazəsiz imtiyaz — {what.strip()[:60]}"


def test_the_rpc_is_security_definer_with_a_pinned_search_path() -> None:
    """`SECURITY DEFINER` + sabit `search_path` — biri digərisiz təhlükəlidir.

    `search_path` sabitlənməsəydi, çağıran öz sxemində `tenants` adlı saxta
    cədvəl yaradıb funksiyanı onu oxumağa məcbur edə bilərdi (klassik
    SECURITY DEFINER zəifliyi).
    """
    rpc = _read("003_license_status_rpc.sql")
    assert "SECURITY DEFINER" in rpc
    assert re.search(r"SET\s+search_path\s*=\s*vendor,\s*pg_temp", rpc), (
        "`SET search_path = vendor, pg_temp` funksiyanın öz tərifində olmalıdır"
    )
    assert "REVOKE ALL ON FUNCTION" in rpc, "icra icazəsi əvvəlcə hamıdan alınmalıdır"


def test_the_rpc_never_writes() -> None:
    """RPC YALNIZ oxuyur — qərar: müştəri vendor bazasına yazmır."""
    rpc = _read("003_license_status_rpc.sql")
    body = rpc[rpc.find("CREATE OR REPLACE FUNCTION") : rpc.find("COMMENT ON FUNCTION")]
    for statement in ("INSERT", "UPDATE", "DELETE"):
        assert statement not in body.upper(), f"RPC gövdəsində `{statement}` var"


def test_the_sql_suite_covers_the_four_required_scenarios() -> None:
    """DB-3 FAZA 5-in dörd məcburi ssenarisi SQL testində mövcuddur."""
    suite = _SQL_TEST.read_text(encoding="utf-8", errors="replace")
    for marker in ("TEST 1", "TEST 2", "TEST 3", "TEST 4"):
        assert marker in suite, f"{marker} yoxdur"
    # MÜSBƏT nəzarət olmadan qalan üçü mənasızdır: hər şeyi bloklayan səhv
    # siyasət də onları keçərdi.
    assert "MÜSBƏT" in suite, "vendor rolunun İŞLƏDİYİNİ yoxlayan test yoxdur"


def test_the_sql_suite_leaves_no_data_behind() -> None:
    """Test tranzaksiyası geri qaytarılır — baza çirklənmir."""
    suite = _SQL_TEST.read_text(encoding="utf-8", errors="replace")
    assert suite.rstrip().endswith("ROLLBACK;")
