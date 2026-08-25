"""Developer Panelinin məlumat qatı — `service_role` tərəfi (bölmə 8).

──────────────────────────────────────────────────────────────────────────────
BU, TENANT İYERARXİYASININ PİLLƏSİ DEYİL — AYRI SİSTEMDİR
──────────────────────────────────────────────────────────────────────────────
Bu panel bəzən "Master" adlanır və bu ad bir yanlış təəssürat yaratmışdı:
guya tenant-ın `Root`-unun ÜSTÜNDƏ daha bir `Root` var. YOXDUR. İki AYRI
sistem var:

    * TENANT-DAXİLİ RBAC — `Root`(0) → `CEO`(1) → `Admin`(2) → operativ
      rollar(3) → `Satıcı`(4). Tenant-ın `Root`-u öz sistemində MÜTLƏQ,
      ETİRAZSIZ ən yuxarıdır; bu nərdivanın 0-dan yuxarısı YOXDUR.
    * SAAS ABUNƏ İDARƏETMƏSİ (bu fayl) — hansı tenant-ın ödənişi gəlib,
      lisenziyası nə vaxt bitir, hansı versiyaya keçməlidir. Burada HEÇ BİR
      `permission_flags` sətri oxunmur/yazılmır, heç bir işçi PII-si açılmır
      və tenant-ın DAXİLİNDƏ heç bir səlahiyyət yoxdur.

Yeganə toxunuş nöqtəsi lisenziyanın ÖZÜDÜR (aktiv/deaktiv) — yəni proqramın
işləyib-işləməməsi, kimin nəyə icazəsi olması yox. `active_admin_count()`
aşağıda məhz bu sərhədi göstərir: SAY oxunur, sətir məzmunu yox.

──────────────────────────────────────────────────────────────────────────────
BU FAYL MÜŞTƏRİYƏ GÖNDƏRİLƏN `.exe`-DƏ İŞLƏMİR
──────────────────────────────────────────────────────────────────────────────
`gateway.py` müştəri PC-sində işləyir və "mənim statusum nədir?" soruşur.
Buradakı kod isə CAVABI DƏYİŞDİRƏN tərəfdir — yalnız hazırlayıcının öz
kompüterində, `--developer-mode` ilə açılır və `service_role` açarı tələb
edir. Həmin açar HEÇ VAXT müştəri quraşdırmasına daxil edilmir.

Qoruma iki qatlıdır:

    1. AÇAR    — `service_role` yalnız developer-in yerli `.env`-indədir
                 (`.gitignore`-dadır, Git-ə düşmür). Müştəridəki `anon`
                 açar RLS-ə tabedir və `license_tenants`-ə yaza bilmir.
    2. KOD     — bu modul `DeveloperModeRequiredError` atmadan qurulmur;
                 tətbiqin adi kompozisiya kökü (`build_container`) onu
                 ümumiyyətlə idxal etmir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ "SON CHECK-IN" `tenant_check_ins`-DƏN HESABLANIR
──────────────────────────────────────────────────────────────────────────────
Müştəri `license_tenants`-ə yaza bilmədiyi üçün `last_check_in_at` sütununu
o yeniləyə bilmir. Ona görə panel həqiqi dəyəri `tenant_check_ins`-dəki
`MAX(checked_in_at)`-dən götürür; köhnə sütun geriyə uyğunluq üçün qalır və
`GREATEST(...)` ilə birləşdirilir.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, Final

from src.application.use_cases.developer_console import CrashRecord, TicketRecord
from src.domain.policies import SystemLimitKey
from src.domain.value_objects.authorization import RolePriority
from src.domain.value_objects.licensing import (
    SERVICE_TIER_ESAS,
    LicenseStatus,
    extend_by_month,
)
from src.domain.value_objects.updates import Version
from src.infrastructure.config.limits import InfrastructureLimits, fallback_int
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.infrastructure.persistence.connection_types import TenantDatabase

_log = get_logger(__name__)
_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

#: `service_role` açarının mühit dəyişəni — YALNIZ developer-in `.env`-ində.
SERVICE_ROLE_ENV: Final[str] = "KOMPASOS_SUPABASE_SERVICE_ROLE_KEY"
#: Developer rejimini açan mühit dəyişəni (bayraqla birlikdə tələb olunur).
DEVELOPER_MODE_ENV: Final[str] = "KOMPASOS_DEVELOPER_MODE"

#: Bu qədər gündür check-in etməyən quraşdırma "səssiz" sayılır — panel
#: sətri vurğulanır. 3 gün seçilib: bir uzun həftəsonu + bir iş günü.
#:
#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`DEVELOPER_DIRECTORY_STALE_DAYS`, seed: migrations/032). Mövsümi bağlanan
#: və ya həftədə bir neçə gün işləyən filialda 3 gün daimi "səssiz" nişanı
#: verərdi və panel öz siqnal dəyərini itirərdi.
FALLBACK_STALE_CHECK_IN_DAYS: Final[int] = fallback_int(
    SystemLimitKey.DEVELOPER_DIRECTORY_STALE_DAYS
)

_LIST_SQL: Final[str] = """
    SELECT t.tenant_id,
           t.tenant_name,
           t.status,
           t.expires_at,
           t.last_payment_date,
           t.next_payment_date,
           t.company_contact_email,
           t.company_contact_phone,
           t.app_version,
           t.service_tier,
           GREATEST(t.last_check_in_at, c.last_seen) AS last_check_in_at
      FROM license_tenants t
      LEFT JOIN (
            SELECT tenant_id, max(checked_in_at) AS last_seen
              FROM tenant_check_ins
             GROUP BY tenant_id
      ) c ON c.tenant_id = t.tenant_id
     ORDER BY t.tenant_name
"""


class DeveloperModeRequiredError(KompasOSError):
    """Developer Paneli konfiqurasiya edilmədən açılmağa çalışıldı."""

    user_message = (
        "Developer Paneli yalnız hazırlayıcının konfiqurasiya edilmiş kompüterində işə düşür."
    )


class TenantNotFoundError(KompasOSError):
    """Panel cədvəlində olmayan tenant üzərində əməliyyat cəhdi."""

    user_message = "Seçilmiş müştəri qeydi tapılmadı — siyahını yeniləyin."


@dataclass(frozen=True)
class TenantRow:
    """Panel cədvəlinin bir sətri."""

    tenant_id: str
    tenant_name: str
    status: LicenseStatus
    expires_at: datetime | None
    last_check_in_at: datetime | None
    company_contact_email: str = ""
    company_contact_phone: str = ""
    app_version: str = ""
    #: Xidmət səviyyəsi (`v2backlog.md` Faza 9.2, migrations/092). Yalnız OXU:
    #: dəyişikliyi `vendor_maintenance.set_service_tier` edir (admin DSN).
    service_tier: str = SERVICE_TIER_ESAS

    def days_left(self, now: datetime) -> int | None:
        """Qalan gün; müddət yoxdursa `None`, keçibsə mənfi."""
        if self.expires_at is None:
            return None
        return (self.expires_at - now).days

    def badge_az(self, now: datetime) -> str:
        """Status-nişanının mətni — panel cədvəlində göstərilir."""
        if self.status is LicenseStatus.DEAKTIV:
            return "Deaktiv"
        days = self.days_left(now)
        if days is None:
            return self.status.label_az
        if days < 0:
            return f"Bitib ({abs(days)} gün)"
        if days == 0:
            return "Bu gün bitir"
        return f"{days} gün qalıb"

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and now >= self.expires_at

    def needs_attention(
        self,
        now: datetime,
        *,
        warn_days: int = 7,
        limits: InfrastructureLimits | None = None,
    ) -> bool:
        """Sətir vurğulanmalıdırmı (bitib, bitir, və ya uzun müddət səssiz).

        `limits` verilməzsə "səssizlik" həddi fallback-dır. Developer Paneli
        MASTER bazaya (service_role) qoşulur, tenant-ın öz `system_limits`
        sətrinə deyil — ona görə həddi çağıran ötürür, sətir özü oxumur.
        """
        if self.status is LicenseStatus.DEAKTIV or self.is_expired(now):
            return True
        days = self.days_left(now)
        if days is not None and days <= warn_days:
            return True
        if self.last_check_in_at is None:
            return True
        stale_days = (limits or InfrastructureLimits()).int_of(
            SystemLimitKey.DEVELOPER_DIRECTORY_STALE_DAYS
        )
        return (now - self.last_check_in_at).days >= stale_days


@dataclass(frozen=True)
class TenantTelemetry:
    """Bir tenant-ın aqreqasiya edilmiş texniki mənzərəsi (bölmə 8).

    HEÇ BİR PII SAHƏSİ YOXDUR — yalnız saylar və zaman möhürləri.
    `tenant_name` şirkət adıdır, işçi məlumatı deyil.
    """

    tenant_id: str
    tenant_name: str
    active_users: int
    active_servers: int
    active_stores: int
    #: Təsdiqlənmiş və AKTİV cihaz sayı (DEVICE-1 Faza 5). Lisenziya
    #: ölçüsüdür: gələcək cihaz-əsaslı qiymətləndirmənin əsası budur.
    #: Gözləyən/bloklanmış cihazlar SAYILMIR — onlar yer tutmur.
    active_devices: int
    open_conflicts: int
    recent_crashes: int
    last_sync_at: datetime | None = None

    @property
    def needs_attention(self) -> bool:
        """Panelin sətri vurğulasınmı."""
        return self.open_conflicts > 0 or self.recent_crashes > 0 or self.active_servers == 0

    @property
    def summary_az(self) -> str:
        return (
            f"{self.active_users} istifadəçi · {self.active_stores} mağaza · "
            f"{self.active_servers} server · {self.active_devices} cihaz"
        )


@dataclass(frozen=True)
class ExtensionResult:
    """ "[1 Ay Uzat]" əməliyyatının nəticəsi — təsdiq modalından sonra göstərilir."""

    tenant_id: str
    tenant_name: str
    old_expires_at: datetime | None
    new_expires_at: datetime
    reactivated: bool


class DeveloperTenantDirectory:
    """Bütün tenant-ların siyahısı və `expires_at` idarəsi.

    `system_scope()` istifadə olunur: `license_tenants` tenant-a AİD OLMAYAN
    cədvəldir (`connection.py`-dakı siyahıya bax) — `app.tenant_id` təyin
    etmək burada mənasızdır. Panel `service_role` bağlantısı ilə işlədiyi
    üçün RLS onu məhdudlaşdırmır.

    BAĞLANTI TİPİ `TenantDatabase`-dir, `VendorDatabase` DEYİL (DB-4 Faza 1):
    sinif `license_tenants` ilə yanaşı `employees`, `stores`, `erp_servers`,
    `sync_conflicts` kimi TAMAMİLƏ tenant cədvəllərini də oxuyur (bax
    `active_admin_count` və `telemetry`). Yəni onu DB-3-ün ayrıca vendor
    bazasına yönəltmək sorğuların yarısını mövcud OLMAYAN cədvəllərə
    göndərərdi.
    """

    def __init__(self, database: TenantDatabase, *, require_developer_mode: bool = True) -> None:
        if require_developer_mode and not developer_mode_enabled():
            raise DeveloperModeRequiredError(
                f"`{DEVELOPER_MODE_ENV}` və `{SERVICE_ROLE_ENV}` təyin edilməyib",
                context={"required_env": [DEVELOPER_MODE_ENV, SERVICE_ROLE_ENV]},
            )
        self._database = database

    # -------------------------------- oxuma ---------------------------------- #

    def list_tenants(self, *, search: str = "") -> list[TenantRow]:
        """Bütün tenant-lar (istəyə görə ad/e-poçt üzrə süzgəc).

        Süzgəc SQL-də deyil, yaddaşda tətbiq olunur: tenant sayı onlarladır,
        `ILIKE` sorğusu isə paneldə hər hərf yazılışında bazaya gedərdi.
        """
        rows = [
            _row_from_record(record)
            for record in self._fetch_all(
                _LIST_SQL,
                (),
                tables=("license_tenants", "tenant_check_ins"),
                cross_tenant=True,
            )
        ]
        needle = search.strip().casefold()
        if not needle:
            return rows
        return [
            row
            for row in rows
            if needle in row.tenant_name.casefold()
            or needle in row.company_contact_email.casefold()
        ]

    def get(self, tenant_id: str) -> TenantRow | None:
        rows = self._fetch_all(
            _LIST_SQL.replace("ORDER BY t.tenant_name", "").rstrip() + " WHERE t.tenant_id = %s",
            (tenant_id,),
            tables=("license_tenants", "tenant_check_ins"),
            cross_tenant=True,
        )
        return _row_from_record(rows[0]) if rows else None

    # ------------------------------ dəyişdirmə -------------------------------- #

    def extend_one_month(self, tenant_id: str, *, now: datetime | None = None) -> ExtensionResult:
        """`expires_at`-i 30 gün uzadır və statusu `AKTIV`-ə qaytarır.

        Bir tranzaksiyada üç şey baş verir və üçü də ayrılmazdır:

            1. `expires_at` irəliləyir (`extend_by_month` — mənfi qalıq yığmır),
            2. status `AKTIV` olur (ödəniş alındı → proqram açılmalıdır),
            3. `license_audit_log`-a sətir düşür.

        (3) olmadan (1) izlənilməz olardı: "bu tenant-ı nə vaxt uzatmışdım?"
        sualına cavab qalmazdı və mübahisə halında sübut olmazdı.
        """
        moment = now or datetime.now(UTC)
        current = self.get(tenant_id)
        if current is None:
            msg = f"Tenant tapılmadı: {tenant_id}"
            raise TenantNotFoundError(msg, context={"tenant_id": tenant_id})

        new_expiry = extend_by_month(current.expires_at, now=moment)
        reactivated = current.status is not LicenseStatus.AKTIV

        with (
            self._database.system_scope(tables=("license_tenants", "license_audit_log")) as conn,
            conn.cursor() as cur,
        ):
            cur.execute(
                """
                UPDATE license_tenants
                   SET expires_at          = %s,
                       status              = 'AKTIV',
                       last_payment_date   = %s,
                       next_payment_date   = %s,
                       deactivation_reason = NULL,
                       deactivated_at      = NULL
                 WHERE tenant_id = %s
                """,
                (new_expiry, moment.date(), new_expiry.date(), tenant_id),
            )
            cur.execute(
                """
                INSERT INTO license_audit_log
                    (tenant_id, action, old_expires_at, new_expires_at, note)
                VALUES (%s, 'EXTEND_ONE_MONTH', %s, %s, %s)
                """,
                (
                    tenant_id,
                    current.expires_at,
                    new_expiry,
                    "Developer Paneli — [1 Ay Uzat]",
                ),
            )
            conn.commit()

        _audit_log.warning(
            "LICENSE_EXTENDED",
            extra={
                "tenant_id": tenant_id,
                "old_expires_at": current.expires_at.isoformat() if current.expires_at else None,
                "new_expires_at": new_expiry.isoformat(),
                "reactivated": reactivated,
            },
        )
        return ExtensionResult(
            tenant_id=tenant_id,
            tenant_name=current.tenant_name,
            old_expires_at=current.expires_at,
            new_expires_at=new_expiry,
            reactivated=reactivated,
        )

    def set_status(
        self,
        tenant_id: str,
        status: LicenseStatus,
        *,
        reason: str = "",
        now: datetime | None = None,
    ) -> TenantRow | None:
        """Tək `[Aktivləşdir / Deaktiv Et]` toggle-düyməsi (bölmə 8).

        Müştəri tərəfdən ÇAĞIRILA BİLMƏZ: bu sinif yalnız developer rejimində
        qurulur və `service_role` bağlantısı tələb edir. Tenant-ın öz
        `can_manage_license` flag-i bu koda heç bir yolla çatmır (bölmə 8 —
        "istisnasız olaraq yalnız Developer Panelinin səlahiyyətindədir").
        """
        moment = now or datetime.now(UTC)
        current = self.get(tenant_id)
        if current is None:
            return None

        with (
            self._database.system_scope(tables=("license_tenants", "license_audit_log")) as conn,
            conn.cursor() as cur,
        ):
            cur.execute(
                """
                UPDATE license_tenants
                   SET status = %s,
                       deactivation_reason = CASE WHEN %s = 'DEAKTIV' THEN %s ELSE NULL END,
                       deactivated_at = CASE WHEN %s = 'DEAKTIV' THEN %s ELSE NULL END
                 WHERE tenant_id = %s
                """,
                (status.value, status.value, reason or None, status.value, moment, tenant_id),
            )
            cur.execute(
                """
                INSERT INTO license_audit_log
                    (tenant_id, action, old_expires_at, new_expires_at, note)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    tenant_id,
                    f"SET_STATUS_{status.value}",
                    current.expires_at,
                    current.expires_at,
                    reason or None,
                ),
            )
            conn.commit()

        _audit_log.warning(
            "LICENSE_TENANT_STATUS_SET",
            extra={"tenant_id": tenant_id, "status": status.value, "reason": reason or None},
        )
        return self.get(tenant_id)

    def set_forced_version(
        self, tenant_id: str, version: str, *, now: datetime | None = None
    ) -> TenantRow | None:
        """Bu tenant üçün məcburi yenilənmə versiyası (bölmə 8).

        Boş sətir məcburiyyəti GÖTÜRÜR. Versiya formatı burada yoxlanılır ki,
        yazı səhvi (`1.2` və ya `son`) sükutla bazaya düşüb klient tərəfdə
        "heç nə olmur" kimi görünməsin — orada yararsız dəyər sadəcə
        `None`-a çevrilir və səbəb tapılmaz qalardı.
        """
        cleaned = version.strip()
        if cleaned and Version.try_parse(cleaned) is None:
            raise TenantNotFoundError(
                f"Versiya formatı tanınmadı: {cleaned!r}",
                user_message="Versiya «1.2.3» formatında olmalıdır.",
                context={"value": cleaned},
            )

        moment = now or datetime.now(UTC)
        current = self.get(tenant_id)
        if current is None:
            return None

        with (
            self._database.system_scope(tables=("license_tenants", "license_audit_log")) as conn,
            conn.cursor() as cur,
        ):
            cur.execute(
                "UPDATE license_tenants SET forced_update_version = %s WHERE tenant_id = %s",
                (cleaned or None, tenant_id),
            )
            cur.execute(
                """
                INSERT INTO license_audit_log
                    (tenant_id, action, old_expires_at, new_expires_at, note, performed_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    tenant_id,
                    "SET_FORCED_VERSION" if cleaned else "CLEAR_FORCED_VERSION",
                    current.expires_at,
                    current.expires_at,
                    cleaned or None,
                    moment,
                ),
            )
            conn.commit()

        _audit_log.warning(
            "LICENSE_FORCED_VERSION_SET",
            extra={"tenant_id": tenant_id, "version": cleaned or None},
        )
        return self.get(tenant_id)

    def crash_records(self, *, days: int = 30, limit: int = 2000) -> list[CrashRecord]:
        """Anonimləşdirilmiş çökmə hesabatları (bölmə 8).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ SORĞU QRUPLAŞDIRMIR
        ──────────────────────────────────────────────────────────────────────
        `GROUP BY fingerprint` SQL-də edilsəydi, "neçə fərqli quraşdırmada?"
        sualı da orada həll olunmalı olardı və prioritetləşdirmə qaydası
        (bax `developer_console.group_crashes`) SQL ilə Python arasında
        bölünərdi. Sətir sayı onsuz da məhduddur (`limit`), ona görə
        qruplaşdırma TAM ŞƏKİLDƏ oxu-modelin işidir.

        `tenant_id` QAYTARILMIR — cədvəldə o sütun ümumiyyətlə yoxdur, yalnız
        `anonymous_tenant_ref` hash-ı var (anonimlik qərarı Faza 3-dədir).
        """
        rows = self._fetch_all(
            """
            SELECT fingerprint, exception_type, app_version,
                   anonymous_tenant_ref, os_version, occurred_at
              FROM crash_reports
             WHERE occurred_at >= now() - make_interval(days => %s)
             ORDER BY occurred_at DESC
             LIMIT %s
            """,
            (days, limit),
            tables=("crash_reports",),
        )
        return [
            CrashRecord(
                fingerprint=str(row["fingerprint"]),
                exception_type=str(row["exception_type"]),
                app_version=str(row["app_version"]),
                anonymous_tenant_ref=str(row["anonymous_tenant_ref"]),
                occurred_at=_require_datetime(row["occurred_at"]),
                os_version=str(row.get("os_version") or ""),
            )
            for row in rows
        ]

    def support_tickets(self, *, limit: int = 200) -> list[TicketRecord]:
        """Bütün tenant-ların dəstək müraciətləri (bölmə 8).

        İlk cavab anı `support_messages`-dən hesablanır: hazırlayıcı tərəfin
        BİRİNCİ mesajı. `support_tickets.first_response_at` sütunu da var,
        lakin o, yalnız yazıldıqda doludur — hesablanmış dəyər həmişə
        həqiqətə uyğundur və `COALESCE` ilə birləşdirilir.
        """
        rows = self._fetch_all(
            """
            SELECT t.id,
                   COALESCE(lt.tenant_name, 'Naməlum')          AS tenant_name,
                   t.subject,
                   t.status,
                   t.created_at,
                   t.closed_at,
                   COALESCE(
                       t.first_response_at,
                       (SELECT MIN(m.created_at) FROM support_messages m
                         WHERE m.ticket_id = t.id AND m.is_from_developer)
                   )                                            AS first_response_at,
                   (SELECT COUNT(*) FROM support_messages m
                     WHERE m.ticket_id = t.id)                   AS message_count,
                   (SELECT MAX(m.created_at) FROM support_messages m
                     WHERE m.ticket_id = t.id)                   AS last_message_at
              FROM support_tickets t
              LEFT JOIN license_tenants lt ON lt.tenant_id = t.tenant_id
             ORDER BY t.created_at DESC
             LIMIT %s
            """,
            (limit,),
            tables=("support_tickets", "support_messages", "license_tenants"),
            cross_tenant=True,
        )
        return [
            TicketRecord(
                ticket_id=str(row["id"]),
                tenant_name=str(row["tenant_name"]),
                subject=str(row["subject"]),
                status=str(row["status"]),
                created_at=_require_datetime(row["created_at"]),
                first_response_at=_as_datetime(row.get("first_response_at")),
                closed_at=_as_datetime(row.get("closed_at")),
                message_count=int(row.get("message_count") or 0),
                last_message_at=_as_datetime(row.get("last_message_at")),
            )
            for row in rows
        ]

    def audit_trail(self, tenant_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Tenant üzrə lisenziya əməliyyatları tarixçəsi."""
        return self._fetch_all(
            """
            SELECT action, old_expires_at, new_expires_at, note, performed_at
              FROM license_audit_log
             WHERE tenant_id = %s
             ORDER BY performed_at DESC
             LIMIT %s
            """,
            (tenant_id, limit),
            tables=("license_audit_log",),
        )

    def active_admin_count(self, tenant_id: str) -> int:
        """Tenant-da qalan AKTİV admin-tier hesabların sayı (bölmə 2).

        Emergency Access Recovery-nin birinci qapısı budur: prosedur yalnız
        say SIFIR olduqda işə düşür. Sorğu qəsdən yalnız SAY qaytarır — ad,
        e-poçt, heç bir sətir məzmunu OXUNMUR. Bölmə 8 hazırlayıcı tərəf üçün
        "heç bir halda işçi PII-sinə uzaqdan çıxış YOXDUR" deyir; bir ədəd
        həmin sərhədi keçmir, lakin qapını yoxlamağa kifayət edir.

        HƏDD `RolePriority.ADMIN`-dir, ədəd isə ondan TÖRƏDİLİR. Əvvəllər
        burada sabit `1` yazılırdı və o, `Root`/`CEO` eyni pillədə (0) olduğu
        modelə bağlı idi. Root/CEO prioritet ayrılığından sonra `Admin` 2-yə
        sürüşdü — sabit qalsaydı, sorğu Admin-ləri sükutla saymazdı və tenant
        real admin-i olduğu halda "sıfır admin" görünərdi. Bu, Emergency
        Access Recovery-ni SƏHVƏN açardı, yəni say ən həssas qapının girişidir.
        """
        rows = self._fetch_all(
            """
            SELECT COUNT(*) AS total
              FROM employees e
              JOIN positions p ON p.id = e.position_id
             WHERE e.tenant_id = %s
               AND e.is_active
               AND p.priority <= %s
            """,
            (tenant_id, int(RolePriority.ADMIN)),
            tables=("employees", "positions"),
            cross_tenant=True,
        )
        return int(rows[0]["total"]) if rows else 0

    def telemetry(self, *, days: int = 7) -> list[TenantTelemetry]:
        """Tenant-üzrə AQREQASİYA edilmiş texniki göstəricilər (bölmə 8).

        ────────────────────────────────────────────────────────────────────
        BURADA HANSI MƏLUMAT VAR VƏ HANSI YOXDUR
        ────────────────────────────────────────────────────────────────────
        Bölmə 8: "Tenant-üzrə aqreqasiya edilmiş telemetriyaya (aktiv istifadəçi
        sayı, server sayı, sync sağlamlığı və s.) baxmaq — **heç bir halda işçi
        PII-sinə uzaqdan çıxış YOXDUR**."

        Ona görə hər sütun `COUNT(*)` və ya `MAX(timestamp)`-dır. Ad, e-poçt,
        istifadəçi adı, mağaza adı — heç biri seçilmir. Sorğunu genişləndirərkən
        həmin sərhəd qorunmalıdır: bir dənə `full_name` sütunu bu funksiyanı
        müqavilə pozuntusuna çevirər (bax `docs/contract_notes.md`).
        """
        rows = self._fetch_all(
            """
            SELECT t.tenant_id,
                   t.tenant_name,
                   (SELECT count(*) FROM employees e
                     WHERE e.tenant_id = t.tenant_id AND e.is_active)      AS active_users,
                   (SELECT count(*) FROM erp_servers s
                     WHERE s.tenant_id = t.tenant_id AND s.status = 'ACTIVE') AS active_servers,
                   (SELECT count(*) FROM stores st
                     WHERE st.tenant_id = t.tenant_id AND st.is_active)    AS active_stores,
                   -- DEVICE-1: qeydiyyatlı AKTİV cihazlar. `PENDING_APPROVAL`
                   -- sayılmır — o, lisenziya yeri tutmur və sayılsaydı sayğac
                   -- təsdiqlənməmiş qeydiyyatlarla şişirdilə bilərdi.
                   (SELECT count(*) FROM registered_devices d
                     WHERE d.tenant_id = t.tenant_id AND d.status = 'ACTIVE') AS active_devices,
                   (SELECT count(*) FROM sync_conflicts c
                     WHERE c.tenant_id = t.tenant_id AND c.resolved_at IS NULL)
                                                                           AS open_conflicts,
                   (SELECT max(s.last_successful_sync) FROM erp_servers s
                     WHERE s.tenant_id = t.tenant_id)                      AS last_sync_at,
                   (SELECT count(*) FROM crash_reports cr
                     WHERE cr.anonymous_tenant_ref = t.tenant_id::text
                       AND cr.occurred_at >= now() - make_interval(days => %s))
                                                                           AS recent_crashes
            FROM license_tenants t
            ORDER BY t.tenant_name
            """,
            (days,),
            tables=(
                "license_tenants",
                "employees",
                "erp_servers",
                "stores",
                "registered_devices",
                "sync_conflicts",
                "crash_reports",
            ),
            cross_tenant=True,
        )
        return [
            TenantTelemetry(
                tenant_id=str(row["tenant_id"]),
                tenant_name=row["tenant_name"],
                active_users=int(row["active_users"] or 0),
                active_servers=int(row["active_servers"] or 0),
                active_stores=int(row["active_stores"] or 0),
                active_devices=int(row["active_devices"] or 0),
                open_conflicts=int(row["open_conflicts"] or 0),
                recent_crashes=int(row["recent_crashes"] or 0),
                last_sync_at=_as_datetime(row["last_sync_at"]),
            )
            for row in rows
        ]

    # ------------------------------- köməkçilər ------------------------------ #

    def _fetch_all(
        self,
        sql: str,
        params: tuple[Any, ...],
        *,
        tables: tuple[str, ...],
        cross_tenant: bool = False,
    ) -> list[dict[str, Any]]:
        """SAAS-2: hər çağırış toxunduğu cədvəlləri BƏYAN EDİR.

        Bəyan `sql`-dən çıxarılmır (SQL təhlili rədd edildi — səbəb
        `Database.system_scope` docstring-indədir), çağıran metod onu AÇIQ
        yazır. `cross_tenant=True` yalnız kirayəçi cədvəllərini oxuyan
        panel sorğularındadır: təchizatçının çox-kirayəçi görünüşü
        sənədləşdirilmiş qərardır (CLAUDE.md §9), lakin o icazə bu faylın
        DİGƏR sorğularına sızmamalıdır.
        """
        with (
            self._database.system_scope(tables=tables, cross_tenant=cross_tenant) as conn,
            conn.cursor() as cur,
        ):
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def developer_mode_enabled() -> bool:
    """Developer rejimi konfiqurasiya edilibmi.

    HƏR İKİSİ tələb olunur: bayraq TƏK BAŞINA kifayət etsəydi, `service_role`
    açarı olmayan bir mühitdə panel açılıb sorğularda anlaşılmaz icazə
    xətaları verərdi.
    """
    flag = os.environ.get(DEVELOPER_MODE_ENV, "").strip().lower() in {"1", "true", "yes"}
    return flag and bool(os.environ.get(SERVICE_ROLE_ENV, "").strip())


def _row_from_record(record: dict[str, Any]) -> TenantRow:
    return TenantRow(
        tenant_id=str(record["tenant_id"]),
        tenant_name=str(record.get("tenant_name") or ""),
        status=_status_of(record.get("status")),
        expires_at=_as_datetime(record.get("expires_at")),
        last_check_in_at=_as_datetime(record.get("last_check_in_at")),
        company_contact_email=str(record.get("company_contact_email") or ""),
        company_contact_phone=str(record.get("company_contact_phone") or ""),
        app_version=str(record.get("app_version") or ""),
        # Sütun migrations/092 ilə gəldi — köhnə snapshot-da olmaya bilər;
        # defolt «Əsas»-dır (DB DEFAULT ilə eyni), yalan məlumat deyil.
        service_tier=str(record.get("service_tier") or SERVICE_TIER_ESAS),
    )


def _status_of(value: Any) -> LicenseStatus:
    try:
        return LicenseStatus(str(value))
    except ValueError:
        _log.warning("LICENSE_UNKNOWN_STATUS", extra={"value": str(value)})
        return LicenseStatus.ODENIS_GOZLENILIR


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    return None


def _require_datetime(value: Any) -> datetime:
    """`NOT NULL` vaxt sütunu üçün — yoxdursa proqramçı/sxem səhvidir.

    Sükutla `now()` qoymaq çökmənin və ya müraciətin yaşını YANLIŞ göstərərdi
    və SLA hesabatı da yanlış olardı.
    """
    moment = _as_datetime(value)
    if moment is None:
        raise TenantNotFoundError(
            "Gözlənilən vaxt dəyəri boşdur — sxem gözləniləndən fərqlidir",
            context={"value": repr(value)},
        )
    return moment


__all__ = [
    "DEVELOPER_MODE_ENV",
    "FALLBACK_STALE_CHECK_IN_DAYS",
    "SERVICE_ROLE_ENV",
    "DeveloperModeRequiredError",
    "DeveloperTenantDirectory",
    "ExtensionResult",
    "TenantNotFoundError",
    "TenantRow",
    "TenantTelemetry",
    "developer_mode_enabled",
]
