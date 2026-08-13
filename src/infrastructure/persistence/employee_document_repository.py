"""#17 İşçi Sənədləri saxlama qatı — `employee_documents` (Faza 7).

QAYDA (bölmə 2): 100% parameterləşdirilmiş SQL. RLS-Ə ƏLAVƏ İKİNCİ QAT: hər
sorğuda açıq `tenant_id` şərti var — tətbiq səhvən owner rolu ilə qoşulsa
(RLS onda tətbiq olunmur), izolyasiya bu şərtlə qalır (`pos_policy_repository.py`
ilə eyni naxış).

NİYƏ `delete()` YOXDUR: migrations/020 `REVOKE DELETE` edir — sənəd qeydi
(müddəti bitmiş olsa belə) keçmiş növbə təyinatının hüquqi əsasıdır. Metodu
yazıb DB-nin rədd etməsinə buraxmaq "niyə işləmir?" sualı yaradardı, ona görə
metod ÜMUMİYYƏTLƏ yoxdur (`exception_repositories.py` başlığı ilə eyni qərar).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.domain.entities.employee_document import EmployeeDocument
from src.domain.value_objects.identifiers import EmployeeDocumentId, EmployeeId, TenantId
from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from datetime import date


class PostgresEmployeeDocumentRepository(_BaseRepository):
    """`employee_documents` — işçi başına ÇOX sətir ola bilər (UPSERT `id` ilə)."""

    _SELECT = """
        SELECT id, tenant_id, employee_id, doc_type, doc_number, file_ref,
               expiry_date, is_blocking, uploaded_by, is_active,
               deactivated_at, deactivated_by, deactivation_reason,
               created_at, updated_at
        FROM employee_documents
    """

    def get(self, document_id: EmployeeDocumentId) -> EmployeeDocument | None:
        row = self._fetch_one(
            f"{self._SELECT} WHERE id = %s AND tenant_id = %s",
            (document_id, self._tenant),
        )
        return _row_to_document(row) if row else None

    def list_for_employee(
        self, tenant_id: TenantId, employee_id: EmployeeId, *, include_inactive: bool = False
    ) -> list[EmployeeDocument]:
        clauses = ["tenant_id = %s", "employee_id = %s"]
        params: list[Any] = [tenant_id, employee_id]
        if not include_inactive:
            clauses.append("is_active")
        # `clauses` SABİT sətir siyahısındandır — bölmə 2-nin S608 istisnası.
        rows = self._fetch_all(
            f"{self._SELECT} WHERE {' AND '.join(clauses)} ORDER BY created_at DESC",
            tuple(params),
        )
        return [_row_to_document(row) for row in rows]

    def list_blocking_for_employee(
        self, tenant_id: TenantId, employee_id: EmployeeId
    ) -> list[EmployeeDocument]:
        """`idx_employee_documents_blocking`-in oxu tərəfi.

        `expiry_date IS NOT NULL` BURADA SÜZÜLMÜR: `DocumentComplianceAdvisor`
        müddətsiz sətirləri özü kənarlaşdırır (bax onun başlığı) — sorğunu
        indeksin `WHERE is_active AND is_blocking` şərti ilə eyni saxlamaq
        Postgres-in indeksi TAM istifadə etməsini təmin edir.
        """
        rows = self._fetch_all(
            f"{self._SELECT} WHERE tenant_id = %s AND employee_id = %s "
            "AND is_active AND is_blocking",
            (tenant_id, employee_id),
        )
        return [_row_to_document(row) for row in rows]

    def list_expiring(self, tenant_id: TenantId, *, on_or_before: date) -> list[EmployeeDocument]:
        rows = self._fetch_all(
            f"{self._SELECT} WHERE tenant_id = %s AND is_active "
            "AND expiry_date IS NOT NULL AND expiry_date <= %s "
            "ORDER BY expiry_date",
            (tenant_id, on_or_before),
        )
        return [_row_to_document(row) for row in rows]

    def save(self, record: EmployeeDocument) -> None:
        """UPSERT — `ON CONFLICT (id)`.

        `doc_type`, `employee_id`, `tenant_id`, `uploaded_by`, `created_at`
        YENİLƏMƏDƏ TOXUNULMUR (`EXCLUDED`-dən çıxarılıb): bunlar sətrin
        İDENTİTİ/mənşə sahələridir (`EmployeeDocument.update()` başlığına
        bax) — `doc_type` domendə artıq dəyişməzdir, DB tərəfi bunu TƏKRAR
        qoruyur ki, ekranı yan keçən skript də eyni qaydaya tabe olsun.
        """
        self._execute(
            """
            INSERT INTO employee_documents
                (id, tenant_id, employee_id, doc_type, doc_number, file_ref,
                 expiry_date, is_blocking, uploaded_by, is_active,
                 deactivated_at, deactivated_by, deactivation_reason,
                 created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
                SET doc_number           = EXCLUDED.doc_number,
                    file_ref             = EXCLUDED.file_ref,
                    expiry_date          = EXCLUDED.expiry_date,
                    is_blocking          = EXCLUDED.is_blocking,
                    is_active            = EXCLUDED.is_active,
                    deactivated_at       = EXCLUDED.deactivated_at,
                    deactivated_by       = EXCLUDED.deactivated_by,
                    deactivation_reason  = EXCLUDED.deactivation_reason,
                    updated_at           = EXCLUDED.updated_at
            """,
            (
                record.id,
                record.tenant_id,
                record.employee_id,
                record.doc_type,
                record.doc_number,
                record.file_ref,
                record.expiry_date,
                record.is_blocking,
                record.uploaded_by,
                record.is_active,
                record.deactivated_at,
                record.deactivated_by,
                record.deactivation_reason,
                record.created_at,
                record.updated_at,
            ),
        )


def _row_to_document(row: dict[str, Any]) -> EmployeeDocument:
    return EmployeeDocument(
        document_id=EmployeeDocumentId(row["id"]),
        tenant_id=TenantId(row["tenant_id"]),
        employee_id=EmployeeId(row["employee_id"]),
        doc_type=row["doc_type"],
        doc_number=row["doc_number"],
        file_ref=row["file_ref"],
        expiry_date=row["expiry_date"],
        is_blocking=bool(row["is_blocking"]),
        uploaded_by=row["uploaded_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        is_active=bool(row["is_active"]),
        deactivated_at=row["deactivated_at"],
        deactivated_by=row["deactivated_by"],
        deactivation_reason=row["deactivation_reason"],
        # BƏRPA hadisə YAYMIR — əks halda hər oxu "yeni sənəd" bildirişi
        # doğurardı (`EmployeeDocument.__init__` başlığı).
        emit_created_event=False,
    )


__all__ = ["PostgresEmployeeDocumentRepository"]
