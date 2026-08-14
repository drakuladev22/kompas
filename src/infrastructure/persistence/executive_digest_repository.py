"""`executive_digest_config` — #30 Planlaşdırılmış İcra Xülasəsi (kompas1.md Faza 6).

`ExecutiveDigestConfigRepository`-in Postgres tətbiqi (`domain/interfaces/
ports.py`). Sxem: `database/migrations/037_field_reports_and_hr_operations.sql`
§9 (`executive_digest_config` cədvəli — bu miqrasiya CƏDVƏLİ DƏYİŞMİR).

──────────────────────────────────────────────────────────────────────────────
`list_route_recipients` NİYƏ ÖZ NÜSXƏSİDİR (`FieldReportRepository`-i ÇAĞIRMIR)
──────────────────────────────────────────────────────────────────────────────
`field_report_repositories.PostgresFieldReportRepository.list_route_recipients`
EYNİ sorğunu (rol kodu → aktiv işçilər) artıq edir. Onu buradan ÇAĞIRMAQ
YERİNƏ 10 sətirlik SQL TƏKRARLANIB, çünki iki repo AYRI bounded-context-dir
(#26+#27 sahə hesabatları / #30 icra xülasəsi) və biri digərini çağırsaydı,
xülasənin marşrutlaması gələcəkdə sahə hesabatlarının kataloq dəyişikliyi ilə
sükutla təsirlənərdi (`multi_store_benchmark.py`-ın öz `active_stores`
sorğusunu saxlaması, `stores` cədvəlinin başqa modula bağlı OLMAMASI ilə eyni
qərar). `store_id` süzgəci YOXDUR: sahə hesabatının marşrutu HƏMİN filiala,
icra xülasəsi isə ŞƏBƏKƏYƏ aiddir.

──────────────────────────────────────────────────────────────────────────────
1C SƏRHƏDİ
──────────────────────────────────────────────────────────────────────────────
Bu fayl YALNIZ `executive_digest_config`/`employees`/`positions` cədvəllərinə
toxunur. Xam satış göstəricisi metrik hesablamasının bu faylla HEÇ BİR ƏLAQƏSİ
YOXDUR — o, `application/use_cases/executive_digest.py`-da mövcud `multi_store_
benchmark`/`exceptions` portlarını çağırır (statik `ast` qapısı: `tests/unit/
test_executive_digest.py`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.domain.value_objects.executive_digest import DigestFrequency, ExecutiveDigestConfig
from src.domain.value_objects.identifiers import EmployeeId, TenantId
from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from datetime import date, datetime

    from src.domain.value_objects.identifiers import ExecutiveDigestConfigId

_SELECT = """
    SELECT id, tenant_id, recipient_role, frequency, metrics_included,
           last_sent_at, is_active, deactivated_at, created_by
      FROM executive_digest_config
"""


class PostgresExecutiveDigestConfigRepository(_BaseRepository):
    """`ExecutiveDigestConfigRepository`-in Postgres tətbiqi."""

    def get(self, config_id: ExecutiveDigestConfigId) -> ExecutiveDigestConfig | None:
        row = self._fetch_one(_SELECT + " WHERE id = %s", (config_id,))
        return _hydrate(row) if row else None

    def list_for_tenant(
        self, tenant_id: TenantId, *, include_inactive: bool = False
    ) -> list[ExecutiveDigestConfig]:
        sql = _SELECT + " WHERE tenant_id = %s"
        if not include_inactive:
            sql += " AND is_active"
        rows = self._fetch_all(sql + " ORDER BY recipient_role, frequency", (tenant_id,))
        return [_hydrate(row) for row in rows]

    def save(self, entry: ExecutiveDigestConfig) -> ExecutiveDigestConfig:
        """UPSERT — `ON CONFLICT (tenant_id, recipient_role, frequency)`.

        `config_id=None` (yeni sətir) halında `id` sütunu `gen_random_uuid()`-a
        düşür — `work_modes.save()` ilə EYNİ naxış (`COALESCE(%s, gen_random_
        uuid())`). Konfiqurasiya YALNIZ `ExecutiveDigestUseCase.configure()`-dən
        (həmişə aktiv sətir) çağırılır — DEAKTİVASİYA `deactivate()`-in AYRI
        yoludur — ona görə UPSERT sətri HƏMİŞƏ `is_active = TRUE`-ya qaytarır:
        Root söndürülmüş konfiqurasiyanı YENİDƏN redaktə etsə, bu, "onu təzədən
        istəyirəm" deməkdir (reaktivasiya).
        """
        row = self._fetch_one(
            """
            INSERT INTO executive_digest_config
                (id, tenant_id, recipient_role, frequency, metrics_included,
                 is_active, created_by)
            VALUES (COALESCE(%s, gen_random_uuid()), %s, %s, %s, %s, TRUE, %s)
            ON CONFLICT (tenant_id, recipient_role, frequency)
            DO UPDATE SET metrics_included = EXCLUDED.metrics_included,
                          is_active         = TRUE,
                          deactivated_at    = NULL
            RETURNING id, tenant_id, recipient_role, frequency, metrics_included,
                      last_sent_at, is_active, deactivated_at, created_by
            """,
            (
                entry.config_id,
                entry.tenant_id,
                entry.recipient_role,
                entry.frequency.value,
                list(entry.metrics_included),
                entry.created_by,
            ),
        )
        # `RETURNING`-li INSERT həmişə sətir qaytarır (S101 layihə-üzrə susdurulub).
        assert row is not None
        return _hydrate(row)

    def deactivate(
        self, tenant_id: TenantId, config_id: ExecutiveDigestConfigId, *, changed_by: EmployeeId
    ) -> None:
        # `changed_by` İSTİFADƏ OLUNMUR: audit sətrini "kim" sualının cavabı use
        # case-dəki `AuditTrail.record` yazır, bu repo YALNIZ vəziyyəti dəyişir.
        del changed_by
        self._execute(
            """
            UPDATE executive_digest_config
               SET is_active = FALSE, deactivated_at = now()
             WHERE id = %s AND tenant_id = %s
            """,
            (config_id, tenant_id),
        )

    def mark_sent(
        self, tenant_id: TenantId, config_id: ExecutiveDigestConfigId, *, sent_at: datetime
    ) -> None:
        self._execute(
            "UPDATE executive_digest_config SET last_sent_at = %s WHERE id = %s AND tenant_id = %s",
            (sent_at, config_id, tenant_id),
        )

    def list_route_recipients(self, tenant_id: TenantId, *, role_code: str) -> list[EmployeeId]:
        """Bax modul başlığı — `FieldReportRepository`-nin QƏSDƏN AYRI nüsxəsi.

        Sıra DETERMİNİSTİKDİR (`last_name, first_name, id`) — eyni naxış
        `field_report_repositories.list_route_recipients` ilə, baxmayaraq ki,
        burada sıranın ÖZÜ əhəmiyyətsizdir (HAMISINA bildiriş gedir, "birinci
        nəfər" seçilmir) — determinizm YALNIZ testin təkrarlana bilməsi üçündür.
        """
        rows = self._fetch_all(
            "SELECT e.id AS id FROM employees e "
            "JOIN positions p ON p.id = e.position_id "
            "WHERE e.tenant_id = %s AND e.is_active AND upper(p.code) = %s "
            "ORDER BY e.last_name, e.first_name, e.id",
            (tenant_id, role_code.strip().upper()),
        )
        return [EmployeeId(row["id"]) for row in rows]

    # ---------------------------- `DigestFactProvider` ------------------------ #
    #
    # EYNİ SİNİFDƏ İKİNCİ PROTOKOL — `PostgresAttritionRepository`-nin
    # "attrition_signals"/"attrition_scores" naxışı ilə EYNİ qərar
    # (`connection.py::_build_repositories` başlığı): xülasə konfiqurasiyası
    # VƏ gecikən-check-in sayı EYNİ tranzaksiyada oxunur, ikinci bağlantı
    # açmağa ehtiyac yoxdur.

    def late_check_in_count(self, tenant_id: TenantId, *, start: date, end: date) -> int:
        """`[start, end)` aralığında `attendance_records.is_late` sayı.

        YENİ GECİKMƏ MƏNTİQİ YOXDUR — `is_late` sütununu Morning Check-in
        artıq yazır (`assess_lateness`, `schema.sql` §9 şərhi: "work_modes.
        start_time ilə müqayisə"). Bu sorğu YALNIZ SAYIR.
        """
        row = self._fetch_one(
            "SELECT COUNT(*) AS value FROM attendance_records "
            "WHERE tenant_id = %s AND work_date >= %s AND work_date < %s AND is_late",
            (tenant_id, start, end),
        )
        return int(row["value"]) if row else 0


def _hydrate(row: dict[str, Any]) -> ExecutiveDigestConfig:
    is_active = bool(row["is_active"])
    return ExecutiveDigestConfig(
        config_id=row["id"],
        tenant_id=TenantId(row["tenant_id"]),
        recipient_role=str(row["recipient_role"]),
        frequency=DigestFrequency(str(row["frequency"])),
        metrics_included=tuple(row["metrics_included"] or ()),
        last_sent_at=row.get("last_sent_at"),
        is_active=is_active,
        deactivated_at=None if is_active else row.get("deactivated_at"),
        created_by=None if row.get("created_by") is None else EmployeeId(row["created_by"]),
    )


__all__ = ["PostgresExecutiveDigestConfigRepository"]
