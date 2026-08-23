"""Lisenziya sətrinin Supabase-dən oxunması (müştəri tərəfi) — Faza 3.11.

──────────────────────────────────────────────────────────────────────────────
YALNIZ OXUMA — VƏ BU, İKİ QATLA TƏMİN OLUNUR
──────────────────────────────────────────────────────────────────────────────
    1. SQL qatı  — bu faylda `license_tenants`-ə YAZAN heç bir sorğu yoxdur.
    2. Baza qatı — miqrasiya 006 tətbiq roluna `UPDATE/DELETE` vermir və RLS
                   siyasəti yalnız ÖZ sətrini görünən edir.

Tək qat kifayət etmirdi: kod qatı bir gün səhvən dəyişdirilə bilər, baza
qatı isə tək başına "hansı sətri görürəm" sualına cavab vermir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `last_check_in_at` BURADAN YAZILMIR
──────────────────────────────────────────────────────────────────────────────
Developer Paneli "son check-in" sütununu göstərməlidir, lakin müştəri
`license_tenants`-ə YAZA BİLMİR — tələb budur. İki uzlaşma yolu var idi:

    (a) `SECURITY DEFINER` funksiya ilə yalnız bir sütunu yeniləmək,
    (b) check-in-i AYRI cədvələ (`tenant_check_ins`) yazmaq və paneldə
        `MAX(checked_in_at)` hesablamaq.

(b) seçilib: (a) müştəriyə `license_tenants`-ə dolayı yazma yolu açır və
funksiyanın gövdəsindəki bir səhv bütün qorumanı sıfırlayardı. (b)-də
müştərinin `license_tenants` üzərində HEÇ BİR yazma yolu qalmır.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from src.domain.value_objects.licensing import (
    LicenseNotFoundError,
    LicenseSnapshot,
    LicenseUnavailableError,
)
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.value_objects.identifiers import TenantId
    from src.domain.value_objects.licensing import CheckInRequest, CrashReport
    from src.infrastructure.persistence.connection import Database

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

_SELECT_OWN_ROW: Final[str] = """
    SELECT tenant_id, tenant_name, status, expires_at,
           last_payment_date, next_payment_date,
           grace_period_days, offline_grace_days, deactivation_reason
      FROM license_tenants
     WHERE tenant_id = %s
"""


class SupabaseLicenseGateway:
    """`LicenseGateway` portunun tətbiqi — `license_tenants`-dən ÖZ sətri.

    Ayrıca lisenziya serveri, HTTP API və ya xidmət YOXDUR: mövcud Supabase
    layihəsi həm tətbiqin, həm də lisenziyanın bazasıdır.
    """

    def __init__(
        self,
        database: Database,
        *,
        vendor_contact: str = "",
    ) -> None:
        self._database = database
        # Təchizatçı əlaqəsi tenant-a görə dəyişmir, ona görə sütun kimi
        # saxlanılmır. (`company_contact_email` MÜŞTƏRİNİN öz ünvanıdır —
        # bloklama ekranında müştəriyə öz e-poçtunu göstərmək mənasızdır.)
        self._vendor_contact = vendor_contact

    def check_in(self, request: CheckInRequest) -> LicenseSnapshot:
        """Sətri oxuyur və telemetriyanı qeyd edir.

        Raises:
            LicenseNotFoundError: sətir yoxdur və ya RLS onu gizlədir.
            LicenseUnavailableError: bazaya çatmaq mümkün olmadı.
        """
        row = self._fetch_row(request.tenant_id)
        if row is None:
            _security_log.warning(
                "LICENSE_ROW_NOT_VISIBLE",
                extra={
                    "tenant_id": str(request.tenant_id),
                    "impact": "xəbərdarlıq — tətbiq bloklanmır",
                },
            )
            raise LicenseNotFoundError(
                "Lisenziya sətri tapılmadı",
                context={"tenant_id": str(request.tenant_id)},
            )

        self._record_check_in(request)
        payload = dict(row)
        payload["vendor_contact"] = self._vendor_contact
        return LicenseSnapshot.from_dict(payload, checked_at=datetime.now(UTC))

    def report_crash(self, report: CrashReport) -> None:
        """Anonim crash hesabatını `crash_reports`-a yazır (bölmə 8).

        `tenant_id` GÖNDƏRİLMİR — yalnız geri-çevrilməyən referans.
        """
        try:
            with (
                self._database.system_scope(tables=("crash_reports",)) as conn,
                conn.cursor() as cur,
            ):
                cur.execute(
                    """
                    INSERT INTO crash_reports
                        (anonymous_tenant_ref, app_version, exception_type,
                         stack_trace, fingerprint, os_version)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        report.anonymous_tenant_ref,
                        report.app_version,
                        report.exception_type,
                        report.stack_trace,
                        report.fingerprint,
                        report.os_version or None,
                    ),
                )
                conn.commit()
        except Exception as exc:
            raise LicenseUnavailableError(
                "Crash hesabatı yazıla bilmədi", context={"error": str(exc)}
            ) from exc

    # -------------------------------- sorğular -------------------------------- #

    def _fetch_row(self, tenant_id: TenantId) -> dict[str, Any] | None:
        try:
            with self._database.unit_of_work(tenant_id) as uow, uow.connection.cursor() as cur:
                cur.execute(_SELECT_OWN_ROW, (tenant_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as exc:
            # Bazaya çatmamaq NORMAL haldır (offline mağaza) — bloklamır.
            raise LicenseUnavailableError(
                "Lisenziya sətri oxuna bilmədi", context={"error": str(exc)}
            ) from exc

    def _record_check_in(self, request: CheckInRequest) -> None:
        """Telemetriya sətri. Uğursuzluq check-in-i POZMUR.

        Lisenziya statusu artıq oxunub; telemetriyanın yazıla bilməməsi
        (məs. `INSERT` icazəsi verilməyib) istifadəçinin işini dayandırmaq
        üçün səbəb deyil.
        """
        telemetry = request.telemetry
        try:
            with self._database.unit_of_work(request.tenant_id) as uow:
                with uow.connection.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO tenant_check_ins
                            (tenant_id, app_version, active_users, store_count,
                             erp_server_count, pending_sync_count)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            request.tenant_id,
                            request.app_version,
                            telemetry.active_users,
                            telemetry.store_count,
                            telemetry.erp_server_count,
                            telemetry.pending_sync_count,
                        ),
                    )
                uow.commit()
        except Exception as exc:
            _log.debug("LICENSE_TELEMETRY_WRITE_FAILED", extra={"error": str(exc)})


__all__ = ["SupabaseLicenseGateway"]
