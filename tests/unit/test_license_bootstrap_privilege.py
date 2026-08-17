"""Lisenziya sətrinin bootstrap icazəsi — SEC-023 qapısı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TEST VAR
──────────────────────────────────────────────────────────────────────────────
Paketlənmiş `.exe`-də İlk Quraşdırma Sihirbazı son addımda dayanırdı:

    InsufficientPrivilege: permission denied for table license_tenants

Səbəb `CLAUDE.md` §7-dəki naxışın təkrarı idi — eyni qayda İKİ yerdə, İKİ
fərqli cavabla. `schema.sql` §28 tətbiq rolundan yalnız `UPDATE, DELETE` geri
alır; miqrasiya 006 isə `INSERT`-i də geri alırdı. Nəticədə davranış
quraşdırma YOLUNDAN asılı idi: `schema.sql` ilə qurulan təmiz baza
işləyirdi, tam miqrasiya zənciri tətbiq olunmuş baza isə YOX.

Qüsuru nə lint, nə də 5084 test görürdü, çünki hamısı SAXTA repozitoriyalarla
işləyir — fake səlahiyyət yoxlamır. Ona görə qapı burada MƏTN səviyyəsində
qoyulur.

──────────────────────────────────────────────────────────────────────────────
MODEL: NƏ HESABLANIR
──────────────────────────────────────────────────────────────────────────────
Real bazada sıra belədir: əvvəlcə `schema.sql` §28 BÜTÜN cədvəllərə
`SELECT, INSERT, UPDATE, DELETE` verir, sonra ünvanlı `REVOKE`-lar gəlir,
sonra miqrasiyalar nömrə sırası ilə tətbiq olunur. Test məhz bunu təkrarlayır
və İKİ nəticəni müqayisə edir:

  * yalnız `schema.sql` ilə qurulan baza,
  * `schema.sql` + bütün miqrasiyalar tətbiq olunmuş baza.

İkisi FƏRQLƏNİRSƏ, qapı quraşdırma yolundan asılıdır — qüsur elə budur.

Şərh blokları ATILIR: hər miqrasiyanın sonunda `DOWN` bloku var və orada
`REVOKE INSERT ...` sətri ŞƏRH olaraq yazılıb. Onu saymaq testi sükutla
mənasız edərdi (ilk variant məhz bu səbəbdən "yaşıl" görünürdü).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.unit

_REPO: Final[Path] = Path(__file__).resolve().parents[2]
_SCHEMA: Final[Path] = _REPO / "database" / "schema.sql"
_MIGRATIONS: Final[Path] = _REPO / "database" / "migrations"

#: §28 hər cədvələ verdiyi başlanğıc dəst (`GRANT ... ON ALL TABLES`).
_BASELINE: Final[frozenset[str]] = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})

#: `license_tenants` üzərindəki hər ünvanlı GRANT/REVOKE.
_PRIVILEGE: Final = re.compile(
    r"(GRANT|REVOKE)\s+([A-Z, ]+?)\s+ON\s+license_tenants\s+(?:TO|FROM)", re.IGNORECASE
)

_LINE_COMMENT: Final = re.compile(r"--[^\n]*")


def _executable(text: str) -> str:
    """Şərhlərdən təmizlənmiş SQL — `DOWN` blokları sayılmır."""
    return _LINE_COMMENT.sub("", text)


def _apply(text: str, start: frozenset[str] | set[str]) -> set[str]:
    """Ünvanlı GRANT/REVOKE-ları SIRA İLƏ tətbiq edib son dəsti qaytarır."""
    granted = set(start)
    for match in _PRIVILEGE.finditer(_executable(text)):
        privileges = {p.strip().upper() for p in match.group(2).split(",")}
        if match.group(1).upper() == "GRANT":
            granted |= privileges
        else:
            granted -= privileges
    return granted


def _schema_only() -> set[str]:
    return _apply(_SCHEMA.read_text(encoding="utf-8"), _BASELINE)


def _after_migrations() -> set[str]:
    granted = _schema_only()
    for path in sorted(_MIGRATIONS.glob("*.sql")):
        granted = _apply(path.read_text(encoding="utf-8"), granted)
    return granted


def test_both_installation_paths_end_with_the_same_privileges() -> None:
    """Təmiz `schema.sql` və tam miqrasiya zənciri EYNİ nəticəyə gəlməlidir.

    Qüsurun ÖZ ssenarisi: 065-dən əvvəl zəncir `{SELECT}` verirdi, `schema.sql`
    isə `{SELECT, INSERT}` — yəni sihirbaz bir bazada işləyir, digərində yox.
    """
    schema = _schema_only()
    chain = _after_migrations()
    assert schema == chain, (
        "`license_tenants` hüquqları quraşdırma yolundan asılıdır: "
        f"schema.sql={sorted(schema)}, miqrasiyalardan sonra={sorted(chain)}"
    )


def test_the_application_may_create_the_row_but_never_change_it() -> None:
    """SEC-023-ün əsl zəmanəti: `INSERT` var, `UPDATE`/`DELETE` yoxdur.

    Yan keçmə ssenariləri məhz `UPDATE`/`DELETE`-dədir — dayandırılmış
    tenant-ı `AKTIV`-ə qaytarmaq, `expires_at`-i uzatmaq, sətri silib
    yenidən yazmaq. Sətrin İLK yaradılması bunların heç biri deyil.
    """
    for name, granted in (("schema.sql", _schema_only()), ("zəncir", _after_migrations())):
        assert "SELECT" in granted, f"{name}: tətbiq öz lisenziyasını oxuya bilmir"
        assert "INSERT" in granted, f"{name}: sihirbaz tenant sətrini yarada bilmir"
        assert "UPDATE" not in granted, f"{name}: `UPDATE` tətbiq roluna verilib"
        assert "DELETE" not in granted, f"{name}: `DELETE` tətbiq roluna verilib"


def test_the_gate_would_notice_the_original_defect() -> None:
    """Qapının ÖZÜ yoxlanılır: 065 olmasa nəticə fərqlənməlidir.

    Bu bənd olmasaydı test «hər şey qaydasındadır» deyə bilərdi, halbuki
    heç nə ölçməmiş olardı — ilk variantı məhz belə keçirdi (şərhdəki `DOWN`
    bloku son sözü deyirdi və iki tərəf də boş çıxırdı).
    """
    granted = _schema_only()
    for path in sorted(_MIGRATIONS.glob("*.sql")):
        if path.name.startswith("065_"):
            continue
        granted = _apply(path.read_text(encoding="utf-8"), granted)
    assert "INSERT" not in granted, "065 olmadan da `INSERT` qalır — deməli qapı 065-i ölçmür"


def test_the_insert_policy_is_narrow_in_both_directions() -> None:
    """`INSERT` siyasəti İKİ şərti birlikdə tələb edir.

    Qrant tək başına kifayət etmir: 006 `license_tenants`-a RLS qoyub və
    siyasəti olmayan əməliyyat qadağandır. Siyasətin DAR olması isə ayrı
    məsələdir — yalnız `tenant_id` şərti olsaydı, müştəri özünə vendor
    tərəfindən verilmiş kimi GÖRÜNƏN (real Argon2 hash-li) sətir uydura
    bilərdi; yalnız nişan şərti olsaydı, bir kirayəçi BAŞQASININ sətrini
    yarada bilərdi.
    """
    migration = (_MIGRATIONS / "065_self_hosted_tenant_bootstrap.sql").read_text(encoding="utf-8")
    body = _executable(migration)
    policy = body[body.index("CREATE POLICY tenant_bootstraps_own_license") :]
    policy = policy[: policy.index(";")]

    assert "FOR INSERT" in policy, "siyasət `INSERT` üçün deyil"
    assert "tenant_id = license_scope_tenant_id()" in policy, "öz-tenant şərti yoxdur"
    assert "SELF_HOSTED_NO_LICENSE_KEY" in policy, "özünə-host nişanı şərti yoxdur"


def test_the_marker_is_the_same_string_in_sql_and_python() -> None:
    """Nişan İKİ yerdədir və ikisi eyni sətir olmalıdır.

    SQL siyasəti həmin dəyəri TƏLƏB edir, Python isə onu YAZIR. Biri
    dəyişsəydi `INSERT` RLS-də sükutla dayanardı və səbəb yalnız canlı
    bazada görünərdi.
    """
    from src.infrastructure.persistence.config_repositories import (
        SELF_HOSTED_LICENSE_MARKER,
    )

    migration = (_MIGRATIONS / "065_self_hosted_tenant_bootstrap.sql").read_text(encoding="utf-8")
    assert f"'{SELF_HOSTED_LICENSE_MARKER}'" in _executable(migration), (
        f"miqrasiyada `{SELF_HOSTED_LICENSE_MARKER}` nişanı yoxdur"
    )
