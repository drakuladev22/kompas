"""Sistem davamlılığı repository-ləri (`v2backlog.md` Faza 5.3/5.4) — migrations/099.

    PostgresShiftHandoffRepository — `shift_handoff_notes`
    PostgresBreakGlassRepository   — `break_glass_trustees` + `break_glass_grants`

──────────────────────────────────────────────────────────────────────────────
RLS-Ə ƏLAVƏ İKİNCİ QAT
──────────────────────────────────────────────────────────────────────────────
Hər sorğuda açıq `tenant_id` şərti var (`self._tenant`) — `hr_lifecycle_v2_
repositories.py` ilə eyni qayda. Break-glass üçün bu, adi «ikinci qat»dan
DAHA VACİBDİR: aktiv qrant sorğusu səlahiyyət qərarına çevrilir, yəni RLS
sıradan çıxsa BAŞQA kirayəçinin qrantı yerli səlahiyyət kimi oxuna bilərdi.

──────────────────────────────────────────────────────────────────────────────
NİYƏ İKİSİ BİR FAYLDA
──────────────────────────────────────────────────────────────────────────────
Hər ikisi EYNİ miqrasiyanın (099) məhsuludur və biri digərini çağırmır —
`hr_lifecycle_v2_repositories.py`-nin eyni əsaslandırması.

──────────────────────────────────────────────────────────────────────────────
`requested_at` INSERT-DƏ AÇIQ YAZILMIR (TIME-1)
──────────────────────────────────────────────────────────────────────────────
`break_glass_grants.requested_at` sütunu INSERT sütun siyahısında YOXDUR —
dəyər `DEFAULT now()` ilə SERVERDƏN gəlir. Səbəb migrations/099-un sonundakı
qeyddir: `enforce_server_created_at()` trigger-i `created_at` adlı sütuna
baxır, burada isə sütunun adı fərqlidir, ona görə «sütun adı INSERT-də açıq
çəkiləndə default yan keçilir» qüsuru (CLAUDE.md §5, TIME-1) BURADA sütunu
yazmamaqla bağlanır. Aqreqatın `requested_at` dəyəri isə `Clock` portundan
(yəni `ServerTimeService`-dən) gəlir və UPSERT-in `DO UPDATE` hissəsində DƏ
toxunulmur — iki mənbə bir-birini üzərinə yazmır.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.domain.entities.break_glass import (
    BreakGlassGrant,
    BreakGlassStatus,
    BreakGlassTrustee,
)
from src.domain.entities.shift_handoff import ShiftHandoffNote
from src.infrastructure.persistence.repositories import _BaseRepository
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.value_objects.identifiers import (
        BreakGlassGrantId,
        EmployeeId,
        ShiftHandoffNoteId,
        StoreId,
        TenantId,
    )

_log = get_logger(__name__)

#: Handoff qeydinin uzunluq həddi Root parametridir və REPO onu bilmir.
#:
#: `ShiftHandoffNote.__init__` `max_length` TƏLƏB EDİR (domen qaydası), lakin
#: BƏRPA edilən sətir üçün həmin yoxlama MƏNASIZDIR: mətn ARTIQ yazılıb və
#: Root həddi sonradan AŞAĞI SALSAYDI, köhnə sətirlərin oxunuşu istisna ilə
#: düşərdi — yəni Root bir dəyəri dəyişməklə keçmiş qeydləri OXUNMAZ edərdi.
#: Ona görə bərpa yolunda praktik olaraq sonsuz hədd ötürülür; yazı yolunda
#: isə həqiqi Root dəyəri use case-dən gəlir.
_RESTORE_MAX_LENGTH = 1_000_000


# --------------------------------------------------------------------------- #
# ShiftHandoffRepository
# --------------------------------------------------------------------------- #


class PostgresShiftHandoffRepository(_BaseRepository):
    """`shift_handoff_notes` (Faza 5.3)."""

    _SELECT = """
        SELECT id, tenant_id, store_id, author_employee_id, note, work_date,
               acknowledged_by, acknowledged_at, created_at
        FROM shift_handoff_notes
    """

    def get(self, note_id: ShiftHandoffNoteId) -> ShiftHandoffNote | None:
        row = self._fetch_one(
            f"{self._SELECT} WHERE id = %s AND tenant_id = %s",
            (note_id, self._tenant),
        )
        return _row_to_handoff(row) if row else None

    def list_open_for_store(
        self, tenant_id: TenantId, store_id: StoreId, *, limit: int
    ) -> list[ShiftHandoffNote]:
        """`idx_handoff_unacknowledged` qismən indeksinin DƏQİQ forması.

        Görünmə pəncərəsi BURADA SÜZÜLMÜR (ports.py kontraktı) — Root
        parametri tətbiq qatında tətbiq olunur.
        """
        rows = self._fetch_all(
            f"""{self._SELECT}
            WHERE tenant_id = %s AND store_id = %s AND acknowledged_at IS NULL
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (tenant_id, store_id, limit),
        )
        return [_row_to_handoff(row) for row in rows]

    def save(self, note: ShiftHandoffNote) -> None:
        """UPSERT — YALNIZ qəbul cütü yenilənir.

        `note`/`author_employee_id`/`work_date`/`created_at` YENİLƏMƏDƏ
        TOXUNULMUR: qeydin mətni yazıldığı anın faktıdır və sonradan
        dəyişdirilməsi «mən başqa şey yazmışdım» mübahisəsini mümkün edərdi
        (`PostgresEmployeeTransferRequestRepository.save` ilə eyni qərar).
        """
        self._execute(
            """
            INSERT INTO shift_handoff_notes
                (id, tenant_id, store_id, author_employee_id, note, work_date,
                 acknowledged_by, acknowledged_at, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
                SET acknowledged_by = EXCLUDED.acknowledged_by,
                    acknowledged_at = EXCLUDED.acknowledged_at
            """,
            (
                note.id,
                note.tenant_id,
                note.store_id,
                note.author_employee_id,
                note.note,
                note.work_date,
                note.acknowledged_by,
                note.acknowledged_at,
                note.created_at,
            ),
        )


def _row_to_handoff(row: dict[str, Any]) -> ShiftHandoffNote:
    return ShiftHandoffNote(
        note_id=row["id"],
        tenant_id=row["tenant_id"],
        store_id=row["store_id"],
        author_employee_id=row["author_employee_id"],
        note=row["note"],
        work_date=row["work_date"],
        created_at=row["created_at"],
        max_length=_RESTORE_MAX_LENGTH,
        acknowledged_by=row["acknowledged_by"],
        acknowledged_at=row["acknowledged_at"],
    )


# --------------------------------------------------------------------------- #
# BreakGlassRepository
# --------------------------------------------------------------------------- #


class PostgresBreakGlassRepository(_BaseRepository):
    """`break_glass_trustees` + `break_glass_grants` (Faza 5.4) — VAHİD port."""

    _TRUSTEE_SELECT = """
        SELECT id, tenant_id, employee_id, designated_by, designated_at,
               is_active, revoked_by, revoked_at
        FROM break_glass_trustees
    """
    _GRANT_SELECT = """
        SELECT id, tenant_id, requested_by, approved_by, reason, status,
               requested_at, approval_expires_at, approved_at, expires_at,
               revoked_at, revoked_by, vendor_synced_at
        FROM break_glass_grants
    """

    # ------------------------------ reyestr ---------------------------------- #

    def active_trustees(self, tenant_id: TenantId) -> list[BreakGlassTrustee]:
        rows = self._fetch_all(
            f"""{self._TRUSTEE_SELECT}
            WHERE tenant_id = %s AND is_active
            ORDER BY designated_at
            """,
            (tenant_id,),
        )
        return [_row_to_trustee(row) for row in rows]

    def find_trustee(
        self, tenant_id: TenantId, employee_id: EmployeeId
    ) -> BreakGlassTrustee | None:
        """`uq_break_glass_trustee_active` qismən unikal indeksinin forması."""
        row = self._fetch_one(
            f"""{self._TRUSTEE_SELECT}
            WHERE tenant_id = %s AND employee_id = %s AND is_active
            """,
            (tenant_id, employee_id),
        )
        return _row_to_trustee(row) if row else None

    def save_trustee(self, trustee: BreakGlassTrustee) -> None:
        """UPSERT — yalnız ləğv üçlüyü yenilənir (təyinat faktı toxunulmazdır)."""
        self._execute(
            """
            INSERT INTO break_glass_trustees
                (id, tenant_id, employee_id, designated_by, designated_at,
                 is_active, revoked_by, revoked_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
                SET is_active  = EXCLUDED.is_active,
                    revoked_by = EXCLUDED.revoked_by,
                    revoked_at = EXCLUDED.revoked_at
            """,
            (
                trustee.id,
                trustee.tenant_id,
                trustee.employee_id,
                trustee.designated_by,
                trustee.designated_at,
                trustee.is_active,
                trustee.revoked_by,
                trustee.revoked_at,
            ),
        )

    # ------------------------------ qrantlar --------------------------------- #

    def get_grant(self, grant_id: BreakGlassGrantId) -> BreakGlassGrant | None:
        row = self._fetch_one(
            f"{self._GRANT_SELECT} WHERE id = %s AND tenant_id = %s",
            (grant_id, self._tenant),
        )
        return _row_to_grant(row) if row else None

    def find_open_for_employee(
        self, tenant_id: TenantId, employee_id: EmployeeId
    ) -> BreakGlassGrant | None:
        """GÖZLƏYƏN VƏ YA AKTİV sətir — ən yenisi.

        `ORDER BY requested_at DESC LIMIT 1` MƏCBURİDİR: `request_access` bu
        metodla ikinci paralel sorğunu bloklayır, LAKİN tarixi məlumatda
        (miqrasiya edilmiş baza, əl ilə düzəliş) eyni işçinin iki açıq sətri
        qala bilər — sorğu o zaman istisna atmamalı, ƏN YENİSİNİ qaytarmalıdır,
        çünki `has_effective_root()` DƏ bu metodu çağırır və orada istisna
        səlahiyyət yoxlamasını çökdürərdi.
        """
        row = self._fetch_one(
            f"""{self._GRANT_SELECT}
            WHERE tenant_id = %s AND requested_by = %s
              AND status IN ('PENDING_APPROVAL', 'ACTIVE')
            ORDER BY requested_at DESC
            LIMIT 1
            """,
            (tenant_id, employee_id),
        )
        return _row_to_grant(row) if row else None

    def list_pending(self, tenant_id: TenantId) -> list[BreakGlassGrant]:
        rows = self._fetch_all(
            f"""{self._GRANT_SELECT}
            WHERE tenant_id = %s AND status = 'PENDING_APPROVAL'
            ORDER BY approval_expires_at
            """,
            (tenant_id,),
        )
        return [_row_to_grant(row) for row in rows]

    def list_active(self, tenant_id: TenantId) -> list[BreakGlassGrant]:
        rows = self._fetch_all(
            f"""{self._GRANT_SELECT}
            WHERE tenant_id = %s AND status = 'ACTIVE'
            ORDER BY expires_at
            """,
            (tenant_id,),
        )
        return [_row_to_grant(row) for row in rows]

    def count_since(self, tenant_id: TenantId, *, since: datetime) -> int:
        """HƏR statusu sayır (ports.py kontraktı) — «neçə dəfə İSTƏNİLDİ»."""
        row = self._fetch_one(
            """
            SELECT count(*) AS total
            FROM break_glass_grants
            WHERE tenant_id = %s AND requested_at >= %s
            """,
            (tenant_id, since),
        )
        return int(row["total"]) if row else 0

    def list_vendor_unsynced(self, tenant_id: TenantId, *, limit: int) -> list[BreakGlassGrant]:
        rows = self._fetch_all(
            f"""{self._GRANT_SELECT}
            WHERE tenant_id = %s AND vendor_synced_at IS NULL
            ORDER BY requested_at
            LIMIT %s
            """,
            (tenant_id, limit),
        )
        return [_row_to_grant(row) for row in rows]

    def save_grant(self, grant: BreakGlassGrant) -> None:
        """UPSERT. `requested_at` SÜTUNU YAZILMIR — bax modul başlığı (TIME-1).

        `requested_by`/`reason`/`approval_expires_at` də yenilənmir: üçü də
        sorğu ANININ faktıdır və sonradan dəyişdirilməsi audit sətrini yalan
        edərdi.
        """
        self._execute(
            """
            INSERT INTO break_glass_grants
                (id, tenant_id, requested_by, approved_by, reason, status,
                 approval_expires_at, approved_at, expires_at,
                 revoked_at, revoked_by, vendor_synced_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
                SET approved_by      = EXCLUDED.approved_by,
                    status           = EXCLUDED.status,
                    approved_at      = EXCLUDED.approved_at,
                    expires_at       = EXCLUDED.expires_at,
                    revoked_at       = EXCLUDED.revoked_at,
                    revoked_by       = EXCLUDED.revoked_by,
                    vendor_synced_at = EXCLUDED.vendor_synced_at
            """,
            (
                grant.id,
                grant.tenant_id,
                grant.requested_by,
                grant.approved_by,
                grant.reason,
                grant.status.value,
                grant.approval_expires_at,
                grant.approved_at,
                grant.expires_at,
                grant.revoked_at,
                grant.revoked_by,
                grant.vendor_synced_at,
            ),
        )


def _row_to_trustee(row: dict[str, Any]) -> BreakGlassTrustee:
    return BreakGlassTrustee(
        trustee_id=row["id"],
        tenant_id=row["tenant_id"],
        employee_id=row["employee_id"],
        designated_by=row["designated_by"],
        designated_at=row["designated_at"],
        is_active=row["is_active"],
        revoked_by=row["revoked_by"],
        revoked_at=row["revoked_at"],
    )


def _row_to_grant(row: dict[str, Any]) -> BreakGlassGrant:
    return BreakGlassGrant(
        grant_id=row["id"],
        tenant_id=row["tenant_id"],
        requested_by=row["requested_by"],
        reason=row["reason"],
        requested_at=row["requested_at"],
        approval_expires_at=row["approval_expires_at"],
        status=BreakGlassStatus(row["status"]),
        approved_by=row["approved_by"],
        approved_at=row["approved_at"],
        expires_at=row["expires_at"],
        revoked_by=row["revoked_by"],
        revoked_at=row["revoked_at"],
        vendor_synced_at=row["vendor_synced_at"],
        emit_created_event=False,
    )
