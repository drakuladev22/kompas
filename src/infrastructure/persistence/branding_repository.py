"""Kirayəçi brendinqinin Postgres repozitoriyası (TENANT-1 Faza 2).

──────────────────────────────────────────────────────────────────────────────
SƏTİR YOXDURSA DEFOLT QAYTARILIR, `None` YOX
──────────────────────────────────────────────────────────────────────────────
Miqrasiya 064 hər mövcud və hər YENİ kirayəçi üçün boş sətir yaradır, yəni
normalda sətir HƏMİŞƏ var. Buradakı fallback həmin zəmanətə etibar ETMƏMƏK
üçündür: miqrasiya tətbiq olunmamış bir bazada (DB-5-in tapdığı vəziyyət)
sorğu boş qayıdır və o halda tətbiqin AÇILIŞ ekranı çökməməlidir.

`DEFAULT_BRANDING` «brendinq təyin edilməyib» halının DÜZGÜN cavabıdır —
`None` isə hər çağıran tərəfə bir yoxlama borcu qoyardı.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.domain.value_objects.branding import DEFAULT_BRANDING, TenantBranding
from src.infrastructure.persistence.repositories import _BaseRepository
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from src.domain.value_objects.identifiers import EmployeeId, TenantId

_log = get_logger(__name__)


class PostgresBrandingRepository(_BaseRepository):
    """`BrandingRepository` portunun implementasiyası."""

    def get(self, tenant_id: TenantId) -> TenantBranding:
        row = self._fetch_one(
            "SELECT company_name, logo_png, accent_color FROM tenant_branding WHERE tenant_id = %s",
            (str(tenant_id),),
        )
        if row is None:
            return DEFAULT_BRANDING

        logo = row["logo_png"]
        return TenantBranding(
            company_name=str(row["company_name"] or ""),
            # psycopg `BYTEA`-nı `memoryview` kimi qaytara bilir; domen tipi
            # `bytes` gözləyir və `dataclass` müqayisəsi ikisini FƏRQLİ sayardı.
            logo_png=bytes(logo) if logo is not None else None,
            accent_color=row["accent_color"] or None,
        )

    def save(
        self, tenant_id: TenantId, branding: TenantBranding, *, updated_by: EmployeeId
    ) -> None:
        """UPSERT — `_BaseRepository` naxışı.

        `created_at` UPDATE blokunda YOXDUR: brendinqin ilk qurulma anı bir
        dəfə baş verir və hər redaktədə yenidən yazmaq onu mənasız edərdi.
        """
        self._execute(
            """
            INSERT INTO tenant_branding
                (tenant_id, company_name, logo_png, accent_color, updated_by)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id) DO UPDATE SET
                company_name = EXCLUDED.company_name,
                logo_png     = EXCLUDED.logo_png,
                accent_color = EXCLUDED.accent_color,
                updated_by   = EXCLUDED.updated_by
            """,
            (
                str(tenant_id),
                branding.company_name,
                branding.logo_png,
                branding.accent_color,
                str(updated_by),
            ),
        )
        _log.info(
            "TENANT_BRANDING_SAVED",
            extra={
                "tenant_id": str(tenant_id),
                "has_logo": branding.has_custom_logo,
                "accent_color": branding.accent_color,
            },
        )


__all__ = ["PostgresBrandingRepository"]
