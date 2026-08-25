"""Vendor tərəfi baxım əməliyyatları — `v2backlog.md` Faza 9.

İKİ funksiyanın ortaq alətidir:

    * **Tam Data İxracı** (Faza 9.1) — bir tenant-ın bütün kirayəçi-cədvəlləri
      strukturlaşdırılmış JSON-da;
    * **Tier dəyişikliyi** (Faza 9.2) — `service_tier` sütununun yazılması və
      tier-əsaslı Feature Toggle defolt-dəstinin tətbiqi.

──────────────────────────────────────────────────────────────────────────────
NİYƏ ADMİN DSN BİRBAŞA İŞLƏDİLİR — SAAS-2 AĞ SİYAHIISI POZULMUR
──────────────────────────────────────────────────────────────────────────────
Tam ixrac TƏRİF etibarilə bütün kirayəçi cədvəllərini oxuyur — amma hansıların
«bütün» olduğunu kod siyahısı BİLMİR: hər yeni miqrasiya yeni cədvəl gətirir
və əl ilə saxlanılan siyahı məhz orada köhnəlirdi. Ona görə cədvəllər
`information_schema`-dan DINAMİK kəşf olunur.

Dinamik adlar isə `TenantDatabase.system_scope(...)` ağ siyahısına SİĞMIR:
həmin qapı statik bəyan tələb edir və bu, QƏSDƏN-dir — adi kod yollarında
RLS-siz oxunuş yalnız AÇIQ bəyan edilən cədvəllərdə mümkündür. İxrac isə baxım
ƏMƏLİYYATIDIR, adi kod yolu deyil: ona görə `scripts/apply_migrations.py`
pretsedenti kimi BAŞQA qapıdan gedir — owner/admin DSN (`DATABASE_ADMIN_URL`)
birbaşa bağlantı. Həmin DSN onsuz da RLS-sizdir; ağ siyahının qoruduğu şey
(tətbiq hovuzuna imtiyaz sızmaması) toxunulmaz qalır.

TƏHLÜKƏSİZLİK: modul YALNIZ developer-in yerli maşınından (`--developer-mode`
+ admin URL) işləyir; paketlənmiş `.exe`-yə DÜŞMÜR (`docs/build_and_release.md`).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

import psycopg

from src.domain.value_objects.licensing import (
    SERVICE_TIER_MODULE_DEFAULTS,
    VALID_SERVICE_TIERS,
)
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    pass

_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Admin bağlantısı üçün mühit açarı — `Database.admin_pool` ilə EYNİ ad.
ADMIN_URL_ENV: Final[str] = "DATABASE_ADMIN_URL"

#: Cədvəllərin kəşf edildiyi sxemlər. Sistem sxemləri istisnadır; `kompasos`
#: layihənin öz sxemidir (`connection.py::SCHEMA`).
_DISCOVERY_SQL: Final[str] = """
SELECT table_schema, table_name
  FROM information_schema.columns
 WHERE column_name = 'tenant_id'
   AND table_schema NOT IN ('pg_catalog', 'information_schema')
 ORDER BY table_schema, table_name
"""


class VendorMaintenanceError(KompasOSError):
    """Vendor baxım əməliyyatı icra edilə bilmədi."""

    user_message = "Baxım əməliyyatı alınmadı."


@contextmanager
def open_admin_connection() -> Iterator[Any]:
    """Admin DSN üzərindən TƏK bağlantı — ixrac/tier yazılarının qapısı.

    `DATABASE_ADMIN_URL` yoxdursa FAIL-CLOSED: boş URL ilə tətbiq hovuzuna
    düşmək RLS-ni yan keçməyə cəhd olardı və ya (tətbiq rolu ilə) yarımçıq,
    aldadıcı nəticə verərdi.
    """
    url = os.environ.get(ADMIN_URL_ENV, "").strip()
    if not url:
        raise VendorMaintenanceError(
            f"{ADMIN_URL_ENV} təyin edilməyib",
            user_message=(
                f"Tam ixrac və tier dəyişikliyi üçün admin bağlantısı ({ADMIN_URL_ENV}) lazımdır."
            ),
            context={"required_env": ADMIN_URL_ENV},
        )
    conn = psycopg.connect(url, row_factory=psycopg.rows.dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _quote_ident(schema: str, name: str) -> str:
    """Sxem.cədvəl identifikatorünü təhlükəsiz sitatlandırır.

    Adlar `information_schema`-dan gəlir (istifadəçi girişi DEYİL), lakin
    ehtiyat qaydası eynidir: `"` simvolu ikiqatlanmaqla identifikator
    sitatlanır — SQL-injeksiya səthi bağlanır (CLAUDE.md §4).
    """
    safe_schema = schema.replace('"', '""')
    safe_name = name.replace('"', '""')
    return f'"{safe_schema}"."{safe_name}"'


def discover_tenant_tables(conn: Any) -> list[tuple[str, str]]:
    """`tenant_id` sütunlu BÜTÜN cədvəllər — ixracın əhatəsi dinamikdir."""
    with conn.cursor() as cur:
        cur.execute(_DISCOVERY_SQL)
        return [(str(row["table_schema"]), str(row["table_name"])) for row in cur.fetchall()]


def export_tenant_json(conn: Any, tenant_id: str) -> dict[str, Any]:
    """Bir tenant-ın TAM datası — hər cədvəl ayrıca açar altında.

    JSON-un özü `json.dumps(..., default=_json_default)` ilə serializə
    olunur: `UUID`/`datetime`/`Decimal` tipləri ISO/str formada itmir.
    Cədvəlin OLMAMASI xəta deyil — miqrasiya hələ tətbiq olunmamış
    quraşdırmada boş siyahı düzgün nəticədir.
    """
    if not str(tenant_id).strip():
        raise VendorMaintenanceError(
            "İxrac üçün tenant boşdur",
            user_message="Müştəri seçilməyib.",
        )

    document: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "exported_at": datetime.now().astimezone().isoformat(),
        "tables": {},
    }
    for schema, table in discover_tenant_tables(conn):
        # f-string YALNIZ identifikatoru qurur — dəyər %s ilə bağlanır və
        # identifikator `_quote_ident` ilə sitatlanır (adlar information_
        # schema-dan gəlir, istifadəçi girişi deyil).
        qualified = _quote_ident(schema, table)
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM {qualified} WHERE tenant_id = %s",  # noqa: S608 - cədvəl adı kataloqdan sitatlı gəlir
                (tenant_id,),
            )
            rows = [dict(row) for row in cur.fetchall()]
        key = f"{schema}.{table}"
        document["tables"][key] = rows
        _log.info(
            "VENDOR_TENANT_EXPORT_TABLE",
            extra={"table": key, "rows": len(rows)},
        )
    return document


def dumps_export(document: dict[str, Any], *, indent: int | None = 2) -> str:
    """İxrac sənədinin fayla yazıla bilən mətni — tip çevirmələri ilə."""
    return json.dumps(document, ensure_ascii=False, indent=indent, default=_json_default)


def set_service_tier(conn: Any, *, tenant_id: str, tier: str) -> bool:
    """`license_tenants.service_tier`-i yeniləyir; sətir yoxdursa `False`."""
    if tier not in VALID_SERVICE_TIERS:
        raise VendorMaintenanceError(
            f"Naməlum tier: {tier}",
            user_message="Xidmət səviyyəsi «Əsas» və ya «Tam» ola bilər.",
            context={"tier": tier},
        )
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE license_tenants SET service_tier = %s WHERE tenant_id = %s RETURNING tenant_id",
            (tier, tenant_id),
        )
        return cur.fetchone() is not None


def apply_tier_toggle_defaults(conn: Any, *, tenant_id: str, tier: str) -> int:
    """Tier-in Feature Toggle defolt-dəstini YAZIR (spesifikasiya Faza 9.2).

    YALNIZ defolt söndürülən modullar UPSERT edilir — açıq modullara toxunmur,
    çünki onların DB-sətri yoxdursa «açığıdır» (fail-safe, bax
    `RootControlUseCase.list_modules`). Root sonrakı dəyişikliyi bu yazını
    ÜSTÜNƏ əvəz edir — tier dəsti başlanğıc vəziyyətidir, kilid deyil.
    """
    disabled = SERVICE_TIER_MODULE_DEFAULTS.get(tier)
    if disabled is None:
        raise VendorMaintenanceError(
            f"Naməlum tier üçün defolt dəst yoxdur: {tier}",
            user_message="Xidmət səviyyəsi «Əsas» və ya «Tam» ola bilər.",
            context={"tier": tier},
        )
    written = 0
    for module_key in sorted(disabled):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO feature_toggles (tenant_id, module_key, is_enabled)
                VALUES (%s, %s, FALSE)
                ON CONFLICT (tenant_id, module_key) DO NOTHING
                """,
                (tenant_id, module_key),
            )
            written += cur.rowcount
    return written


def _json_default(value: Any) -> str:
    """JSON-a düşməyən tiplərin ISO/mətn forması — data İTMİR.

    `UUID`-nin `isoformat()`-ı YOXDUR (yalnız `str`) — üç tip AYRI saxlanılır.
    """
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID | Decimal):
        return str(value)
    return str(value)


__all__ = [
    "ADMIN_URL_ENV",
    "VendorMaintenanceError",
    "apply_tier_toggle_defaults",
    "discover_tenant_tables",
    "dumps_export",
    "export_tenant_json",
    "open_admin_connection",
    "set_service_tier",
]
