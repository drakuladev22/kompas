"""Sahə hesabatlarının saxlama qatı (#26+#27) — kompas1.md Faza 3.

`field_report_types`, `field_report_categories`, `field_reports` və
`field_report_checklist_items` (migrations/037).

QAYDA (bölmə 2): 100% parameterləşdirilmiş SQL. Dinamik `WHERE` yalnız SABİT
sətir siyahısından qurulur, dəyərlər həmişə `%s` ilə bağlanır.

RLS-Ə ƏLAVƏ İKİNCİ QAT: hər sorğuda açıq `tenant_id` şərti var. Tətbiq səhvən
owner rolu ilə qoşulsa (RLS onda tətbiq olunmur), izolyasiya bu şərtlə qalır —
layihənin bütün repo-larında eyni naxış.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `delete()` YOXDUR
──────────────────────────────────────────────────────────────────────────────
`migrations/037` dörd cədvəldə də `REVOKE DELETE` edir: insident hesabatı
mübahisədə SÜBUTDUR (rədd edilmiş olsa belə), kataloq sətri isə keçmiş
hesabatların mənasını daşıyır. Metodu yazıb DB-nin rədd etməsinə buraxmaq
"niyə işləmir?" sualı yaradardı — ona görə metod ÜMUMİYYƏTLƏ yoxdur
(`exception_repositories.py` ilə eyni qərar).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BƏNDLƏR AYRI PORTDA DEYİL
──────────────────────────────────────────────────────────────────────────────
`save()` hesabatı VƏ bəndlərini eyni tranzaksiyada yazır — aqreqat sərhədi
budur. İki repo olsaydı, hesabat yazılıb bəndləri yazılmayan sətir mümkün
olardı və `chk_field_report_resolution` kimi bütövlük qaydaları qismən
tətbiq edilərdi.

Bəndlər üçün `DELETE` NƏ VAR, NƏ DƏ OLA BİLƏR (yuxarı bax) — yəni draft-dan
bənd ÇIXARMAQ mümkün deyil. Bu, məhdudiyyət deyil, qərardır: audit bəndi
"yoxlandı, uğursuzdur" yazıldıqdan sonra silinməməlidir.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

from src.domain.entities.field_report import FieldReport, FieldReportChecklistItem
from src.domain.value_objects.field_reports import (
    FieldReportCategory,
    FieldReportStatus,
    FieldReportTemplate,
    StoreAuditGap,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    FieldReportId,
    FieldReportItemId,
    StoreId,
    TenantId,
)
from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from datetime import datetime

#: `stores_missing_audit` sorğusu.
#:
#: ŞABLON KODU SQL-Ə YAZILMIR (`fr.type = 'STORE_AUDIT'` YOXDUR): "audit"
#: tərifi kataloqdadır — `field_report_types.requires_checklist`. Beləliklə
#: gələcəkdə əlavə edilən checklist-li şablon (bir `INSERT`) avtomatik olaraq
#: bu sorğuya daxil olur və SQL DƏYİŞMİR (Struktur Qərar A).
#:
#: `LEFT JOIN` MƏCBURİDİR: heç vaxt auditə çəkilməmiş filial `INNER JOIN` ilə
#: nəticədən TAM DÜŞƏRDİ — halbuki o, məhz axtarılan haldır.
_STORES_MISSING_AUDIT_QUERY: Final = """
    SELECT s.id AS store_id,
           s.name AS store_name,
           MAX(fr.created_at) AS last_audit_at
      FROM stores s
      LEFT JOIN field_reports fr
             ON fr.store_id = s.id
            AND fr.tenant_id = s.tenant_id
            AND fr.type IN (SELECT code FROM field_report_types WHERE requires_checklist)
     WHERE s.tenant_id = %s AND s.is_active
     GROUP BY s.id, s.name
    HAVING MAX(fr.created_at) IS NULL OR MAX(fr.created_at) < %s
     ORDER BY s.name
"""


class PostgresFieldReportCatalog(_BaseRepository):
    """`field_report_types` + `field_report_categories` — genişlənmə nöqtəsi.

    `tenant_id IS NULL` = SİSTEM sətri (bütün kirayəçilər görür) — `positions`
    və `exception_sources` naxışı. Ona görə hər sorğuda `OR tenant_id IS NULL`
    şərti var; onsuz seed edilmiş `STORE_AUDIT`/`INCIDENT` heç bir kirayəçiyə
    görünməzdi.
    """

    _TEMPLATE_SELECT = """
        SELECT code, name_az, description_az, requires_checklist, is_active
        FROM field_report_types
    """
    _CATEGORY_SELECT = """
        SELECT code, report_type, name_az, description_az, route_to_role, is_active
        FROM field_report_categories
    """

    def get_template(self, tenant_id: TenantId, code: str) -> FieldReportTemplate | None:
        row = self._fetch_one(
            f"{self._TEMPLATE_SELECT} WHERE code = %s AND (tenant_id = %s OR tenant_id IS NULL)",
            (code.strip().upper(), tenant_id),
        )
        return _row_to_template(row) if row else None

    def list_templates(
        self, tenant_id: TenantId, *, include_inactive: bool = False
    ) -> list[FieldReportTemplate]:
        clauses = ["(tenant_id = %s OR tenant_id IS NULL)"]
        params: list[Any] = [tenant_id]
        if not include_inactive:
            clauses.append("is_active")
        # `clauses` SABİT sətir siyahısındandır — bölmə 2-nin S608 istisnası.
        rows = self._fetch_all(
            f"{self._TEMPLATE_SELECT} WHERE {' AND '.join(clauses)} ORDER BY name_az",
            tuple(params),
        )
        return [_row_to_template(row) for row in rows]

    def get_category(self, tenant_id: TenantId, code: str) -> FieldReportCategory | None:
        row = self._fetch_one(
            f"{self._CATEGORY_SELECT} WHERE code = %s AND (tenant_id = %s OR tenant_id IS NULL)",
            (code.strip().upper(), tenant_id),
        )
        return _row_to_category(row) if row else None

    def list_categories(
        self,
        tenant_id: TenantId,
        *,
        report_type: str | None = None,
        include_inactive: bool = False,
    ) -> list[FieldReportCategory]:
        """`idx_field_report_categories_type` indeksinin sorğusu."""
        clauses = ["(tenant_id = %s OR tenant_id IS NULL)"]
        params: list[Any] = [tenant_id]
        if report_type is not None:
            clauses.append("report_type = %s")
            params.append(report_type.strip().upper())
        if not include_inactive:
            clauses.append("is_active")
        # `clauses` SABİT sətir siyahısındandır — bax `list_templates`.
        rows = self._fetch_all(
            f"{self._CATEGORY_SELECT} WHERE {' AND '.join(clauses)} ORDER BY name_az",
            tuple(params),
        )
        return [_row_to_category(row) for row in rows]


class PostgresFieldReportRepository(_BaseRepository):
    """`field_reports` + `field_report_checklist_items` — VAHİD aqreqat."""

    _SELECT = """
        SELECT id, tenant_id, type, category, store_id, reported_by, detail,
               photo_refs, status, resolved_by, resolved_at, resolution_note,
               created_at, updated_at
        FROM field_reports
    """
    _ITEM_SELECT = """
        SELECT id, tenant_id, report_id, position_no, item_text, passed,
               is_blocking, photo_required, photo_ref, note,
               created_at, updated_at
        FROM field_report_checklist_items
    """

    # -------------------------------- oxuma ------------------------------------ #

    def get(self, report_id: FieldReportId) -> FieldReport | None:
        row = self._fetch_one(
            f"{self._SELECT} WHERE id = %s AND tenant_id = %s",
            (report_id, self._tenant),
        )
        if row is None:
            return None
        return self._hydrate([row])[0]

    def find_by_item(self, tenant_id: TenantId, item_id: FieldReportItemId) -> FieldReport | None:
        """Bəndin İD-si ilə VALİDEYN hesabatı tapır (asinxron foto geri-çağırışı)."""
        row = self._fetch_one(
            "SELECT report_id FROM field_report_checklist_items WHERE id = %s AND tenant_id = %s",
            (item_id, tenant_id),
        )
        if row is None:
            return None
        return self.get(FieldReportId(row["report_id"]))

    def list_open(
        self,
        tenant_id: TenantId,
        *,
        store_ids: list[StoreId] | None = None,
        report_type: str | None = None,
        limit: int = 200,
    ) -> list[FieldReport]:
        """`idx_field_reports_open` sorğusu — ən yenisi əvvəldə."""
        clauses = ["tenant_id = %s", "status IN ('SUBMITTED', 'IN_PROGRESS')"]
        params: list[Any] = [tenant_id]
        if store_ids is not None:
            if not store_ids:
                # BOŞ siyahı = "heç bir mağazaya çıxış yoxdur" (fail-safe,
                # `ExceptionRepository.list_open` ilə eyni qərar).
                return []
            clauses.append("store_id = ANY(%s)")
            params.append(list(store_ids))
        if report_type is not None:
            clauses.append("type = %s")
            params.append(report_type.strip().upper())
        params.append(limit)

        # `clauses` SABİT sətir siyahısındandır, dəyərlər `%s` ilə bağlanır.
        rows = self._fetch_all(
            f"{self._SELECT} WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT %s",
            tuple(params),
        )
        return self._hydrate(rows)

    def list_route_recipients(
        self, tenant_id: TenantId, *, role_code: str, store_id: StoreId | None = None
    ) -> list[EmployeeId]:
        """Rol kodunu AKTİV işçilərə çevirir (#27 marşrutu + düzəliş tapşırığı).

        `upper(p.code)` müqayisəsi: `route_to_role` CHECK-i onsuz da BÖYÜK
        hərf tələb edir, lakin `positions.code` üçün belə bir CHECK YOXDUR —
        kirayəçinin əl ilə yaratdığı rol kiçik hərflə yazıla bilər və
        marşrut sükutla heç kimə çatmazdı.

        SIRA DETERMİNİSTİKDİR (`last_name, first_name, id`): düzəliş tapşırığı
        siyahının BİRİNCİ nəfərinə verilir — sıra təsadüfi olsaydı, eyni
        auditin iki icrası tapşırığı fərqli adama yazardı.
        """
        clauses = ["e.tenant_id = %s", "e.is_active", "upper(p.code) = %s"]
        params: list[Any] = [tenant_id, role_code.strip().upper()]
        if store_id is not None:
            clauses.append("e.store_id = %s")
            params.append(store_id)

        rows = self._fetch_all(
            "SELECT e.id AS id FROM employees e "  # noqa: S608 — şərtlər sabit siyahıdandır
            "JOIN positions p ON p.id = e.position_id "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY e.last_name, e.first_name, e.id",
            tuple(params),
        )
        return [EmployeeId(row["id"]) for row in rows]

    def stores_missing_audit(
        self, tenant_id: TenantId, *, now: datetime, interval_days: int
    ) -> list[StoreAuditGap]:
        """Audit intervalı keçmiş (və ya heç vaxt auditə çəkilməmiş) filiallar."""
        threshold = now - timedelta(days=max(1, interval_days))
        rows = self._fetch_all(_STORES_MISSING_AUDIT_QUERY, (tenant_id, threshold))
        gaps: list[StoreAuditGap] = []
        for row in rows:
            last = row["last_audit_at"]
            gaps.append(
                StoreAuditGap(
                    store_id=StoreId(row["store_id"]),
                    store_name=str(row["store_name"]),
                    last_audit_at=last,
                    # `None` = heç vaxt auditə çəkilməyib — sıfır DEYİL
                    # (bax `StoreAuditGap` başlığı).
                    days_since=None if last is None else (now - last).days,
                )
            )
        return gaps

    # -------------------------------- yazı ------------------------------------- #

    def save(self, report: FieldReport) -> None:
        """UPSERT — hesabat, sonra bəndləri (aqreqat BİR tranzaksiyada).

        `type`, `category`, `store_id`, `reported_by`, `detail` və
        `created_at` YENİLƏMƏDƏ TOXUNULMUR (`EXCLUDED`-dən çıxarılıb):
        bunlar MÜŞAHİDƏ ANININ faktıdır. Sonradan dəyişsəydilər, qərar verən
        şəxsin gördüyü mətn ilə jurnalda qalan mətn fərqlənə bilərdi
        (`PostgresExceptionRepository.save` ilə eyni əsaslandırma).
        """
        self._execute(
            """
            INSERT INTO field_reports
                (id, tenant_id, type, category, store_id, reported_by, detail,
                 photo_refs, status, resolved_by, resolved_at, resolution_note,
                 created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
                SET photo_refs      = EXCLUDED.photo_refs,
                    status          = EXCLUDED.status,
                    resolved_by     = EXCLUDED.resolved_by,
                    resolved_at     = EXCLUDED.resolved_at,
                    resolution_note = EXCLUDED.resolution_note,
                    updated_at      = EXCLUDED.updated_at
            """,
            (
                report.id,
                report.tenant_id,
                report.report_type,
                report.category,
                report.store_id,
                report.reported_by,
                report.detail,
                list(report.photo_refs),
                report.status.value,
                report.resolved_by,
                report.resolved_at,
                report.resolution_note,
                report.created_at,
                report.updated_at,
            ),
        )
        for item in report.items:
            self._save_item(item)

    def _save_item(self, item: FieldReportChecklistItem) -> None:
        """Bəndin UPSERT-i.

        `item_text` YENİLƏMƏDƏ TOXUNULMUR: mətn şablondan KÖÇÜRÜLÜR
        (migrations/037 sütun şərhi) — şablon sonradan dəyişsə də, keçmiş
        auditdə NƏYİN yoxlandığı dəyişməməlidir.
        """
        self._execute(
            """
            INSERT INTO field_report_checklist_items
                (id, tenant_id, report_id, position_no, item_text, passed,
                 is_blocking, photo_required, photo_ref, note,
                 created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
                SET passed         = EXCLUDED.passed,
                    is_blocking    = EXCLUDED.is_blocking,
                    photo_required = EXCLUDED.photo_required,
                    photo_ref      = EXCLUDED.photo_ref,
                    note           = EXCLUDED.note,
                    updated_at     = EXCLUDED.updated_at
            """,
            (
                item.id,
                item.tenant_id,
                item.report_id,
                item.position_no,
                item.item_text,
                item.passed,
                item.is_blocking,
                item.photo_required,
                item.photo_ref,
                item.note,
                item.created_at,
                item.updated_at,
            ),
        )

    # ------------------------------- köməkçi ---------------------------------- #

    def _hydrate(self, rows: list[dict[str, Any]]) -> list[FieldReport]:
        """Sətirləri bəndləri ilə birlikdə aqreqata çevirir.

        BƏNDLƏR TƏK SORĞU İLƏ gətirilir (`report_id = ANY(...)`): hesabat
        başına ayrıca sorğu N+1 naxışı olardı və 200 sətirlik siyahı 201
        sorğuya çevrilərdi.
        """
        if not rows:
            return []
        report_ids = [row["id"] for row in rows]
        item_rows = self._fetch_all(
            f"{self._ITEM_SELECT} WHERE tenant_id = %s AND report_id = ANY(%s) "
            "ORDER BY report_id, position_no",
            (self._tenant, report_ids),
        )
        by_report: dict[Any, list[FieldReportChecklistItem]] = {}
        for item_row in item_rows:
            by_report.setdefault(item_row["report_id"], []).append(_row_to_item(item_row))
        return [_row_to_report(row, tuple(by_report.get(row["id"], ()))) for row in rows]


def _row_to_template(row: dict[str, Any]) -> FieldReportTemplate:
    return FieldReportTemplate(
        code=str(row["code"]),
        name_az=str(row["name_az"]),
        description_az=row["description_az"],
        requires_checklist=bool(row["requires_checklist"]),
        is_active=bool(row["is_active"]),
    )


def _row_to_category(row: dict[str, Any]) -> FieldReportCategory:
    return FieldReportCategory(
        code=str(row["code"]),
        report_type=str(row["report_type"]),
        name_az=str(row["name_az"]),
        description_az=row["description_az"],
        route_to_role=row["route_to_role"],
        is_active=bool(row["is_active"]),
    )


def _row_to_item(row: dict[str, Any]) -> FieldReportChecklistItem:
    return FieldReportChecklistItem(
        item_id=FieldReportItemId(row["id"]),
        tenant_id=TenantId(row["tenant_id"]),
        report_id=FieldReportId(row["report_id"]),
        position_no=int(row["position_no"]),
        item_text=str(row["item_text"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        # `passed` ÜÇ VƏZİYYƏTLİDİR — `bool(row[...])` YAZILA BİLMƏZ:
        # `bool(None)` `False` verər və "hələ yoxlanılmayıb" sükutla
        # "keçmədi"yə çevrilərdi (yəni cavabsız bənd tapşırıq yaradardı).
        passed=None if row["passed"] is None else bool(row["passed"]),
        is_blocking=bool(row["is_blocking"]),
        photo_required=bool(row["photo_required"]),
        photo_ref=row["photo_ref"],
        note=row["note"],
    )


def _row_to_report(row: dict[str, Any], items: tuple[FieldReportChecklistItem, ...]) -> FieldReport:
    return FieldReport(
        report_id=FieldReportId(row["id"]),
        tenant_id=TenantId(row["tenant_id"]),
        report_type=str(row["type"]),
        category=str(row["category"]),
        store_id=StoreId(row["store_id"]),
        reported_by=EmployeeId(row["reported_by"]),
        detail=str(row["detail"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        photo_refs=tuple(row["photo_refs"] or ()),
        status=FieldReportStatus(row["status"]),
        items=items,
        resolved_by=_as_employee_id(row["resolved_by"]),
        resolved_at=row["resolved_at"],
        resolution_note=row["resolution_note"],
        # BƏRPADA UZUNLUQ HƏDDİ TƏTBİQ EDİLMİR (`min_detail_length` defolt
        # sxem döşəməsində qalır): Root minimumu SONRADAN artırsa, köhnə
        # sətirlər oxunmaz olardı — yəni siyasət dəyişikliyi tarixi məhv
        # edərdi. Hədd YAZI yolundadır, oxu yolunda yox.
        emit_created_event=False,
    )


def _as_employee_id(raw: Any) -> EmployeeId | None:
    return None if raw is None else EmployeeId(raw)


__all__ = [
    "PostgresFieldReportCatalog",
    "PostgresFieldReportRepository",
]
