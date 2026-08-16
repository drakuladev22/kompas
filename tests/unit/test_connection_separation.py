"""İki bazanın ayrılığı — tip səviyyəsində və mətn səviyyəsində (DB-4 Faza 1).

──────────────────────────────────────────────────────────────────────────────
NƏYİ QORUYURUQ
──────────────────────────────────────────────────────────────────────────────
Tenant və vendor bazaları AYRI Postgres instansiyalarıdır, lakin hər ikisi
eyni `Database` sinfi ilə açılır. Səhv obyekti ötürmək nə tip, nə də icra
xətası verir — sorğu sadəcə yanlış bazaya gedir və nəticə «sətir tapılmadı»
kimi görünür. Hər iki bazada oxşar adlı cədvəllər olduğuna görə
(`tenants` ↔ `license_tenants`, hər ikisində `crash_reports`,
`support_tickets`) səhv aylarla gizlənə bilər.

Ona görə iki qat yoxlanılır:
    1. TİP — `VendorDatabase` `TenantDatabase` DEYİL (və əksinə);
    2. MƏNBƏ — vendor DSN-i yalnız öz mühit dəyişənindən oxunur, tenant
       kodunda o dəyişənin adı ÜMUMİYYƏTLƏ keçmir.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

import pytest

from src.infrastructure.persistence.connection import Database
from src.infrastructure.persistence.connection_types import (
    VENDOR_DSN_ENV,
    TenantDatabase,
    VendorDatabase,
)

pytestmark = pytest.mark.unit

_REPO_ROOT: Final = Path(__file__).resolve().parents[2]


def test_the_two_databases_are_distinct_types() -> None:
    """Biri digərinin alt-sinfi DEYİL — yəni bir-birini əvəz edə bilmir."""
    assert not issubclass(VendorDatabase, TenantDatabase)
    assert not issubclass(TenantDatabase, VendorDatabase)
    # Hər ikisi ORTAQ tətbiqi paylaşır — kod təkrarlanmır.
    assert issubclass(TenantDatabase, Database)
    assert issubclass(VendorDatabase, Database)


def test_a_missing_vendor_dsn_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Müştəri quraşdırmasında vendor DSN-i YOXDUR — bu, normal haldır.

    İstisna atsaydıq, hər müştəri açılışı təchizatçının bazasının
    mövcudluğunu tələb edərdi (DB-3 qərarına zidd).
    """
    monkeypatch.delenv(VENDOR_DSN_ENV, raising=False)
    assert VendorDatabase.from_env() is None


def test_connecting_to_the_vendor_db_as_a_bypassrls_role_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`service_role` ilə qoşulma SÜKUTLA baş verməməlidir.

    Həmin rolda `BYPASSRLS` var: vendor bazasındakı bütün siyasətlər yan
    keçilir və qoruma serverdən klientə qayıdır (DB-3-ün əsas prinsipinin
    pozulması). Bloklamırıq — miqrasiyanı tətbiq edən skript məhz o rolla
    işləyir — lakin iz qalmalıdır.
    """
    from src.infrastructure.persistence import connection_types

    assert connection_types.VendorConnectionError is not None  # modul yüklənib
    monkeypatch.setenv(VENDOR_DSN_ENV, "postgresql://service_role:x@localhost:5432/vendor")
    with caplog.at_level("CRITICAL"):
        # `open_pool=False`: hovuz QURULUR, lakin qoşulmur — test şəbəkə
        # taymautu gözləməməlidir. Xəbərdarlıq onsuz da bağlantıdan ƏVVƏL
        # yazılır, yəni ölçdüyümüz davranış dəyişmir.
        assert VendorDatabase.from_env(open_pool=False) is not None

    assert any(
        "VENDOR_DB_CONNECTED_AS_BYPASSRLS_ROLE" in record.message for record in caplog.records
    )


def test_a_healthy_vendor_role_is_not_flagged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Düzgün rol xəbərdarlıq YARATMIR — qapı hər bağlantıda siqnal verməməlidir."""
    from src.infrastructure.persistence import connection_types

    assert connection_types.VENDOR_DSN_ENV == VENDOR_DSN_ENV
    monkeypatch.setenv(VENDOR_DSN_ENV, "postgresql://vendor_console:x@localhost:5432/vendor")
    with caplog.at_level("CRITICAL"):
        assert VendorDatabase.from_env(open_pool=False) is not None

    assert not any(
        "VENDOR_DB_CONNECTED_AS_BYPASSRLS_ROLE" in record.message for record in caplog.records
    )


def test_the_tenant_layer_never_mentions_the_vendor_dsn() -> None:
    """Vendor DSN-i YALNIZ ayırıcı modulda oxunur.

    Tenant qatının hər hansı faylı həmin dəyişəni oxusaydı, iki bazanın
    ayrılığı bir `os.environ` sətri ilə pozula bilərdi — və bu, kod
    baxışında görünməzdi.
    """
    # SİYAHI TƏK ELEMENTLİDİR VƏ BU, QƏSDLİDİR. Əvvəl burada `composition.py`
    # da vardı ("yalnız qurma yeri") — halbuki o fayl dəyişəni HEÇ VAXT
    # oxumurdu. İcazə siyahısındakı istifadə olunmayan sətir ən pis haldır:
    # o, gələcəkdə kiminsə vendor DSN-ini məhz həmin fayla yazmasını SÜKUTLA
    # qanuniləşdirərdi. DB-3 qərarı isə odur ki, müştəri quraşdırması vendor
    # bazasına ümumiyyətlə toxunmur.
    allowed = {Path("src/infrastructure/persistence/connection_types.py")}
    offenders: list[str] = []
    for path in sorted((_REPO_ROOT / "src").rglob("*.py")):
        relative = Path(path.relative_to(_REPO_ROOT).as_posix())
        if relative in {Path(p.as_posix()) for p in allowed}:
            continue
        if VENDOR_DSN_ENV in path.read_text(encoding="utf-8", errors="replace"):
            offenders.append(str(relative))

    assert not offenders, f"vendor DSN-i tenant qatında oxunur: {offenders}"


def test_the_vendor_dsn_is_documented_as_optional() -> None:
    """`.env.example` onu BOŞ ola bilən kimi izah etməlidir (CLAUDE.md §8)."""
    example = (_REPO_ROOT / ".env.example").read_text(encoding="utf-8", errors="replace")
    assert VENDOR_DSN_ENV in example
    block = example[example.find("--- Vendor") : example.find(VENDOR_DSN_ENV) + 40]
    assert "BOŞ OLA BİLƏR" in block.upper() or "BOŞ BURAXILA BİLƏR" in block.upper()


def test_the_environment_variable_name_is_stable() -> None:
    """Ad dəyişsə, quraşdırılmış müştərilər sükutla vendor bazasını itirər."""
    assert VENDOR_DSN_ENV == "KOMPASOS_VENDOR_DSN"
    assert os.environ.get(VENDOR_DSN_ENV) is None or True  # yalnız adın sabitliyi ölçülür


# --------------------------------------------------------------------------- #
# AYIRICI HƏQİQƏTƏN DİŞLƏYİRMİ — tiplərin MÖVCUDLUĞU kifayət etmir
# --------------------------------------------------------------------------- #
# İlk tətbiqdə `TenantDatabase`/`VendorDatabase` yazıldı, lakin heç bir
# istehsalat kodu onları İDXAL ETMİRDİ. Nəticə: mypy heç nə dayandıra bilmirdi,
# çünki qorunası imza yox idi — ayırıcı yalnız test faylında yaşayırdı. Qüsuru
# nə lint, nə mypy, nə də test tapdı; onu paketlənmiş `.exe`-nin İÇİNƏ baxmaq
# üzə çıxardı (`connection_types` PYZ arxivində ÜMUMİYYƏTLƏ yox idi).
#
# Aşağıdakı üç yoxlama məhz həmin boşluğu bağlayır: sərhəd imzalarının
# `TenantDatabase` tələb etdiyini və heç kimin ÇILPAQ `Database()` qurmadığını
# ölçür.


def test_the_application_context_requires_a_tenant_database() -> None:
    """`ApplicationContext` ümumi `Database` qəbul ETMİR.

    Bu, bütün iş qatının giriş qapısıdır: buradan aşağı axan hər repo, hər
    use case və hər ekran eyni obyekti alır. Səhv baza məhz burada girə bilər.
    """
    import inspect

    from src.presentation.composition import ApplicationContext

    annotation = inspect.signature(ApplicationContext.__init__).parameters["database"].annotation
    assert annotation == "TenantDatabase", annotation


def test_the_developer_directory_requires_a_tenant_database() -> None:
    """Lisenziya reyestri də TENANT bazasındadır (bax sinif başlığı).

    Sinif `license_tenants` ilə yanaşı `employees`/`stores`/`erp_servers`
    oxuyur — onu vendor bazasına yönəltmək sorğuların yarısını mövcud olmayan
    cədvəllərə göndərərdi. Tip bunu SƏNƏD deyil, QAYDA edir.
    """
    import inspect

    from src.infrastructure.licensing.developer_directory import DeveloperTenantDirectory

    parameters = inspect.signature(DeveloperTenantDirectory.__init__).parameters
    assert parameters["database"].annotation == "TenantDatabase"


def test_no_module_constructs_a_bare_database() -> None:
    """`Database()` birbaşa qurulmur — hər bağlantı NİYYƏTİNİ tiplə bildirir.

    `Database` sinfi SİLİNMİR (DB-4 qırmızı xətti: mövcud kod pozulmur) və o,
    hər iki tipin ortaq tətbiqi olaraq qalır. Lakin onu BİRBAŞA qurmaq
    "hansı baza?" sualını yenidən cavabsız qoyar — və bu sual məhz DB-4-ün
    bağladığı boşluqdur.

    Yoxlama qurma ANINA baxır, annotasiyalara yox: `Database` tipini QƏBUL
    etmək hələ də qanunidir (`ErpServerRepository` kimi daxili istehlakçılar
    obyekti sərhəddən alır və yanlışını ala bilməzlər).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `ast`, NİYƏ MƏTN AXTARIŞI DEYİL
    ──────────────────────────────────────────────────────────────────────────
    İlk variant sətir-sətir `Database\\s*\\(` axtarırdı və dərhal YALANÇI-MÜSBƏT
    verdi: `probe_dsn`-in docstring-ində «`Database()` qursaydıq…» cümləsi var
    və şərh filtri onu tutmadı (çoxsətirli sətrin ORTASINDA idi). Şərhi
    pozuntudan ayırmağın etibarlı yolu mətn deyil, sintaksis ağacıdır — və
    `ast` eyni zamanda `TenantDatabase`/`VendorDatabase` ayrımını da pulsuz
    verir, çünki düyün adı TAM addır.
    """
    import ast

    offenders: list[str] = []
    for path in sorted((_REPO_ROOT / "src").rglob("*.py")):
        relative = path.relative_to(_REPO_ROOT).as_posix()
        if relative == "src/infrastructure/persistence/connection_types.py":
            continue  # ayırıcının ÖZÜ — `cls(dsn, ...)` orada qurulur
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=relative)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            name = callee.id if isinstance(callee, ast.Name) else getattr(callee, "attr", "")
            if name == "Database":
                offenders.append(f"{relative}:{node.lineno}")

    assert not offenders, "çılpaq `Database()` qurulur: " + ", ".join(offenders)
