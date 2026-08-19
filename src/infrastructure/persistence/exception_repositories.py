"""Vahid İstisna Motorunun saxlama qatı (#9) — `exceptions` + `exception_sources`.

QAYDA (bölmə 2): 100% parameterləşdirilmiş SQL. Dinamik `WHERE` yalnız SABİT
sətir siyahısından qurulur, dəyərlər həmişə `%s` ilə bağlanır.

RLS-Ə ƏLAVƏ İKİNCİ QAT: hər sorğuda açıq `tenant_id` şərti var. Tətbiq
səhvən owner rolu ilə qoşulsa (RLS onda tətbiq olunmur), izolyasiya bu şərtlə
qalır — layihənin bütün repo-larında eyni naxış.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `delete()` YOXDUR
──────────────────────────────────────────────────────────────────────────────
Miqrasiya 018 hər iki cədvəldə `REVOKE DELETE` edir: istisna sətri (rədd
edilmiş olsa belə) "buna baxıldı" qərarının sübutudur, mənbə kataloqu isə
keçmiş sətirlərin mənasını daşıyır. Metodu yazıb DB-nin rədd etməsinə
buraxmaq "niyə işləmir?" sualı yaradardı — ona görə metod ÜMUMİYYƏTLƏ yoxdur.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from src.domain.entities.exception_record import ExceptionRecord
from src.domain.value_objects.exception_signals import (
    ExceptionSeverity,
    ExceptionSource,
    ExceptionStatus,
)
from src.domain.value_objects.identifiers import (
    ExceptionId,
    StoreId,
    TenantId,
)
from src.infrastructure.persistence.repositories import _BaseRepository
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from src.domain.value_objects.identifiers import EmployeeId

_log = get_logger(__name__)


class PostgresExceptionRepository(_BaseRepository):
    """`exceptions` — Vahid İstisna Jurnalı."""

    _SELECT = """
        SELECT id, tenant_id, source, employee_id, store_id, detail,
               context_json, severity, status, dedupe_key,
               reviewed_by, reviewed_at, review_note, created_at
        FROM exceptions
    """

    def get(self, exception_id: ExceptionId) -> ExceptionRecord | None:
        row = self._fetch_one(
            f"{self._SELECT} WHERE id = %s AND tenant_id = %s",
            (exception_id, self._tenant),
        )
        return _row_to_exception(row) if row else None

    def find_by_dedupe(
        self, tenant_id: TenantId, *, source: str, dedupe_key: str
    ) -> ExceptionRecord | None:
        """`uq_exceptions_dedupe` indeksinin oxu tərəfi.

        STATUS ŞƏRTİ QƏSDƏN YOXDUR: bağlanmış tapıntı da "artıq mövcuddur"
        sayılır — əks halda rədd edilmiş istisna növbəti gecə yenidən açılar
        və "bir dəfə rədd etdim" qərarı mənasını itirərdi.
        """
        row = self._fetch_one(
            f"""{self._SELECT}
            WHERE tenant_id = %s AND source = %s AND dedupe_key = %s
            """,
            (tenant_id, source, dedupe_key),
        )
        return _row_to_exception(row) if row else None

    def list_open(
        self,
        tenant_id: TenantId,
        *,
        store_ids: list[StoreId] | None = None,
        limit: int = 200,
    ) -> list[ExceptionRecord]:
        """`idx_exceptions_open` indeksinin sorğusu — ən yenisi əvvəldə."""
        # INF2-02: `tenant_id` arqumenti bağlantının ÖZ kontekstiylə (`self.
        # _tenant`) UYĞUN olmalıdır — uyğunsuzluqda GURULTULU xəta (bax
        # `_require_matching_tenant` şərhi).
        clauses = ["tenant_id = %s", "status = 'OPEN'"]
        params: list[Any] = [self._require_matching_tenant(tenant_id)]
        if store_ids is not None:
            if not store_ids:
                # BOŞ siyahı = "heç bir mağazaya çıxış yoxdur". `ANY('{}')`
                # onsuz da boş qaytarardı, lakin sorğunu ümumiyyətlə
                # göndərməmək daha ucuz və daha aydındır (fail-safe).
                return []
            clauses.append("store_id = ANY(%s)")
            params.append(list(store_ids))
        params.append(limit)

        # `clauses` SABİT sətir siyahısındandır (kənardan gələn mətn yoxdur),
        # bütün dəyərlər `%s` ilə bağlanır — bölmə 2-nin tələbi pozulmur.
        rows = self._fetch_all(
            f"""{self._SELECT}
            WHERE {" AND ".join(clauses)}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            tuple(params),
        )
        return [_row_to_exception(row) for row in rows]

    def save(self, record: ExceptionRecord) -> None:
        """UPSERT.

        `ON CONFLICT (id)` YALNIZ QƏRAR SÜTUNLARINI yeniləyir: `source`,
        `employee_id`, `detail` və `created_at` aşkarlama anının FAKTIDIR və
        sonradan dəyişdirilməməlidir — dəyişsəydi, qərar verən şəxsin gördüyü
        mətn ilə jurnalda qalan mətn fərqlənə bilərdi.
        """
        self._execute(
            """
            INSERT INTO exceptions
                (id, tenant_id, source, employee_id, store_id, detail,
                 context_json, severity, status, dedupe_key,
                 reviewed_by, reviewed_at, review_note, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
                SET status      = EXCLUDED.status,
                    severity    = EXCLUDED.severity,
                    reviewed_by = EXCLUDED.reviewed_by,
                    reviewed_at = EXCLUDED.reviewed_at,
                    review_note = EXCLUDED.review_note
            """,
            (
                record.id,
                record.tenant_id,
                record.source,
                record.employee_id,
                record.store_id,
                record.detail,
                json.dumps(record.context, ensure_ascii=False, default=str),
                record.severity.value,
                record.status.value,
                record.dedupe_key,
                record.reviewed_by,
                record.reviewed_at,
                record.review_note,
                record.created_at,
            ),
        )


class PostgresExceptionSourceCatalog(_BaseRepository):
    """`exception_sources` — mənbə kataloqu (#9 genişlənmə nöqtəsi).

    `tenant_id IS NULL` = SİSTEM mənbəyi (bütün kirayəçilər görür) — `positions`
    cədvəlindəki mövcud naxış. Ona görə hər sorğuda `OR tenant_id IS NULL`
    şərti var; onsuz `BEHAVIOR_ANOMALY` heç bir kirayəçiyə görünməzdi.
    """

    _SELECT = """
        SELECT code, name_az, description_az, default_severity, is_active
        FROM exception_sources
    """

    def get(self, tenant_id: TenantId, code: str) -> ExceptionSource | None:
        row = self._fetch_one(
            f"""{self._SELECT}
            WHERE code = %s AND (tenant_id = %s OR tenant_id IS NULL)
            """,
            (code.strip().upper(), tenant_id),
        )
        return _row_to_source(row) if row else None

    def list_all(
        self, tenant_id: TenantId, *, include_inactive: bool = False
    ) -> list[ExceptionSource]:
        clauses = ["(tenant_id = %s OR tenant_id IS NULL)"]
        params: list[Any] = [tenant_id]
        if not include_inactive:
            clauses.append("is_active")

        # `clauses` SABİT sətir siyahısındandır — bax `list_open` şərhi.
        rows = self._fetch_all(
            f"""{self._SELECT}
            WHERE {" AND ".join(clauses)}
            ORDER BY name_az
            """,
            tuple(params),
        )
        return [_row_to_source(row) for row in rows]


def _row_to_exception(row: dict[str, Any]) -> ExceptionRecord:
    return ExceptionRecord(
        exception_id=ExceptionId(row["id"]),
        tenant_id=TenantId(row["tenant_id"]),
        source=str(row["source"]),
        employee_id=row["employee_id"],
        store_id=row["store_id"],
        detail=str(row["detail"]),
        created_at=row["created_at"],
        context=_as_context(row["context_json"]),
        severity=ExceptionSeverity(row["severity"]),
        status=ExceptionStatus(row["status"]),
        dedupe_key=row["dedupe_key"],
        reviewed_by=_as_employee_id(row["reviewed_by"]),
        reviewed_at=row["reviewed_at"],
        review_note=row["review_note"],
        # Repository-dən BƏRPA hadisə YAYMIR — hər oxu "yeni anomaliya"
        # bildirişi doğurardı.
        emit_created_event=False,
    )


def _row_to_source(row: dict[str, Any]) -> ExceptionSource:
    return ExceptionSource(
        code=str(row["code"]),
        name_az=str(row["name_az"]),
        description_az=row["description_az"],
        default_severity=ExceptionSeverity.parse(
            row["default_severity"], fallback=ExceptionSeverity.MEDIUM
        ),
        is_active=bool(row["is_active"]),
    )


def _as_context(raw: Any) -> dict[str, object]:
    """`JSONB` sütununu lüğətə çevirir.

    Sürücü `jsonb`-i artıq Python obyekti kimi qaytarır, lakin köhnə yazılarda
    sətir də ola bilər — hər iki hal emal olunur ki, bir dəfəlik format fərqi
    ekranı sındırmasın (`preferences._as_key_list` ilə eyni qərar).

    POZULMUŞ DƏYƏR SÜKUTLA UDULMUR: boş lüğət qaytarılır (ekran işləməyə davam
    edir — bir yararsız sətrə görə bütün növbəni gizlətmək daha pisdir), lakin
    hadisə log-a düşür. Rəqəmlər qərarın əsasıdır; onların itməsi görünməz
    qalmamalıdır.
    """
    if isinstance(raw, str):
        try:
            value: Any = json.loads(raw)
        except (TypeError, ValueError):
            _log.warning("EXCEPTION_CONTEXT_UNREADABLE", extra={"raw_length": len(raw)})
            return {}
    else:
        value = raw
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _as_employee_id(raw: Any) -> EmployeeId | None:
    return None if raw is None else raw


__all__ = [
    "PostgresExceptionRepository",
    "PostgresExceptionSourceCatalog",
]
