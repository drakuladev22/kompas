"""`AuditTrail` portunun PostgreSQL tətbiqi — `audit_logs` cədvəli.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU ADAPTER LAZIMDIR
──────────────────────────────────────────────────────────────────────────────
Spesifikasiya audit yazısını BİR NEÇƏ yerdə qeyd-şərtsiz tələb edir:

    bölmə 3  "Bütün rol/icazə yaratma, dəyişdirmə, silmə əməliyyatları
              `audit_logs`-da tam detallı qeyd olunur (kim, hansı flag, kimə,
              əvvəl/sonra)."
    bölmə 3  ROOT İdarə Mərkəzi: "Hər dəyişiklik (limit, toggle, yeni flag)
              `audit_logs`-da tam detallı qeyd olunur."
    bölmə 4  "Any «Manual Time Override» MUST trigger a mandatory log entry
              in `audit_logs` including operator ID, employee ID, system time,
              overridden time, mandatory reason text..."
    bölmə 7  Server əlavə/dəyişiklik/silmə əməliyyatları.

`AuditTrail` portu 11 use case tərəfindən işlədilir, lakin PostgreSQL
tətbiqi yox idi — yəni həmin `record()` çağırışlarının istehsalatda
yazacağı bir yer də yox idi.

──────────────────────────────────────────────────────────────────────────────
`audit.log` FAYLI İLƏ FƏRQİ (QARIŞDIRILMAMALIDIR)
──────────────────────────────────────────────────────────────────────────────
`main.py`-dakı hadisə dinləyicisi domen hadisələrini `audit.log` FAYLINA
yazır (bölmə 2 LOGGING) — bu, əməliyyat diaqnostikası üçündür və faylla
birlikdə itə bilər. Buradakı cədvəl isə HÜQUQİ izdir: cərimə mübahisəsində,
etiraz baxışında və müfəttiş yoxlamasında istinad edilən mənbədir. İkisi
bir-birini əvəz etmir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SƏHV AUDIT YAZISI ƏMƏLİYYATI DAYANDIRIR
──────────────────────────────────────────────────────────────────────────────
`record()` istisna udmur. Cəlbedici alternativ — "audit yazıla bilmədisə də
əsas əməliyyat davam etsin" — məhz audit-kritik anlarda (manual override,
icazə dəyişikliyi) izsiz əməliyyat yaradardı. Bölmə 4 audit yazısını
"MANDATORY" adlandırır; məcburi olan bir şeyin sükutla buraxılması onu
məcburi olmaqdan çıxarır. Çağıran tərəf eyni tranzaksiyada işlədiyi üçün
istisna bütün əməliyyatı geri qaytarır — istənilən nəticə budur.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from src.application.use_cases.audit_query import AuditEntry, AuditFilter

if TYPE_CHECKING:
    from psycopg import Connection

    from src.domain.value_objects.identifiers import EmployeeId, TenantId


def _escape_like(value: str) -> str:
    """İstifadəçi mətnindəki `ILIKE` joker simvollarını sadə hərfə çevirir.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ LAZIMDIR — SQL İNYEKSİYASI DEYİL, NAXIŞ POZULMASI
    ──────────────────────────────────────────────────────────────────────────
    Sorğu onsuz da parameterləşdirilib (`%s`), yəni sətir SQL kimi şərh
    olunmur. Lakin `%` və `_` `ILIKE` naxışının İÇİNDƏ xüsusi mənalıdır:
    istifadəçi audit axtarışına `%` yazsa, `'%' || '%' || '%'` naxışı bütün
    sətirlərə uyğun gəlir — süzgəc sükutla "hamısını göstər"ə çevrilir və
    milyonluq cədvəldə skan yaradır. `_` isə istənilən tək simvolu tutur,
    yəni `entity_id` axtarışı yanlış sətirlər qaytarır.

    Tərs kəsik ƏVVƏLCƏ əvəz olunur: sonra əlavə etdiyimiz qaçış simvollarını
    ikinci dəfə emal etməmək üçün sıra vacibdir.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _as_json(state: dict[str, object] | None) -> str | None:
    """`JSONB` sütunu üçün seriallaşdırma.

    `ensure_ascii=False` QƏSDƏNDİR: audit məzmunu Azərbaycan dilindədir və
    `\\u0259` kimi qaçış ardıcıllıqları bazada oxunmaz olardı — halbuki bu
    sətirlər birbaşa insan tərəfindən (etiraz baxışı, müfəttiş) oxunur.
    """
    if state is None:
        return None
    return json.dumps(state, ensure_ascii=False, default=str)


class PostgresAuditTrail:
    """`audit_logs`-a append-only yazır.

    Bağlantı KONSTRUKTORDA verilir, özü yaradılmır: audit yazısı onu doğuran
    əməliyyatla EYNİ tranzaksiyada olmalıdır. Ayrı bağlantı işlədilsəydi,
    əsas əməliyyat geri qaytarıldıqda audit yazısı qalar və heç vaxt baş
    verməmiş bir hadisəni "olmuş" kimi göstərərdi.

    Args:
        connection: Cari iş vahidinin (`UnitOfWork`) bağlantısı.
        machine_name: Sütun `machine_name` — hansı kassa/PC-dən gəldiyi.
        app_version: Sütun `app_version` — qüsur araşdırmasında versiya izi.
    """

    __slots__ = ("_app_version", "_connection", "_machine_name")

    def __init__(
        self,
        connection: Connection[dict[str, Any]],
        *,
        machine_name: str = "",
        app_version: str = "",
    ) -> None:
        self._connection = connection
        self._machine_name = machine_name
        self._app_version = app_version

    def record(
        self,
        *,
        tenant_id: TenantId,
        actor_id: EmployeeId | None,
        action: str,
        entity_type: str,
        entity_id: object | None = None,
        before_state: dict[str, object] | None = None,
        after_state: dict[str, object] | None = None,
        reason: str | None = None,
    ) -> None:
        """Bir audit sətri əlavə edir.

        `occurred_at` QƏSDƏN göndərilmir — sütunun `DEFAULT now()` dəyəri
        BAZANIN saatını işlədir. Tətbiq saatı göndərilsəydi, saatı dəyişdirilmiş
        bir kassa PC-si audit izini də təhrif edə bilərdi; halbuki bu iz məhz
        həmin manipulyasiyanı aşkarlamaq üçündür (bax bölmə 2 NTP qaydası).
        """
        with self._connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_logs
                    (tenant_id, actor_id, action, entity_type, entity_id,
                     before_state, after_state, reason, machine_name, app_version)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(tenant_id),
                    str(actor_id) if actor_id is not None else None,
                    action,
                    entity_type,
                    str(entity_id) if entity_id is not None else None,
                    _as_json(before_state),
                    _as_json(after_state),
                    reason,
                    self._machine_name or None,
                    self._app_version or None,
                ),
            )


class PostgresAuditReader:
    """`audit_logs` OXUMA tərəfi — Audit Log Viewer (bölmə 8, Faza 6.3).

    Yazma sinfindən ayrıdır (bax `AuditLogReader` port şərhi). Sorğular
    `append-only` cədvələ toxunmur: burada yalnız `SELECT` var və
    `enforce_append_only` trigger-i onsuz da `UPDATE`/`DELETE`-i bloklayır.
    """

    __slots__ = ("_connection",)

    def __init__(self, connection: Connection[dict[str, Any]]) -> None:
        self._connection = connection

    def query(self, tenant_id: TenantId, filters: AuditFilter) -> list[AuditEntry]:
        clauses, params = self._where(tenant_id, filters)
        rows = self._fetch(
            f"""
            SELECT a.id, a.occurred_at, a.actor_id, a.action, a.entity_type,
                   a.entity_id, a.reason, a.before_state, a.after_state,
                   a.machine_name, a.app_version,
                   COALESCE(e.first_name || ' ' || e.last_name, 'Sistem') AS actor_name
            FROM audit_logs a
            LEFT JOIN employees e ON e.id = a.actor_id
            WHERE {clauses}
            ORDER BY a.occurred_at DESC
            LIMIT %s OFFSET %s
            """,  # noqa: S608 — şərtlər sabit siyahıdandır, dəyərlər %s ilə bağlanır
            (*params, filters.limit, filters.offset),
        )
        return [
            AuditEntry(
                entry_id=row["id"],
                occurred_at=row["occurred_at"],
                actor_id=row["actor_id"],
                actor_name=row["actor_name"],
                action=row["action"],
                entity_type=row["entity_type"],
                entity_id=row["entity_id"],
                reason=row["reason"],
                before_state=row["before_state"],
                after_state=row["after_state"],
                machine_name=row["machine_name"],
                app_version=row["app_version"],
            )
            for row in rows
        ]

    def count(self, tenant_id: TenantId, filters: AuditFilter) -> int:
        clauses, params = self._where(tenant_id, filters)
        rows = self._fetch(
            f"SELECT count(*) AS total FROM audit_logs a WHERE {clauses}",  # noqa: S608
            params,
        )
        return int(rows[0]["total"]) if rows else 0

    def distinct_actions(self, tenant_id: TenantId) -> list[str]:
        rows = self._fetch(
            "SELECT DISTINCT action FROM audit_logs WHERE tenant_id = %s ORDER BY action",
            (str(tenant_id),),
        )
        return [row["action"] for row in rows]

    @staticmethod
    def _where(tenant_id: TenantId, filters: AuditFilter) -> tuple[str, tuple[Any, ...]]:
        """Süzgəcləri SQL şərtinə çevirir — şərt mətnləri SABİTDİR."""
        clauses = ["a.tenant_id = %s"]
        params: list[Any] = [str(tenant_id)]

        if filters.action:
            clauses.append("a.action = %s")
            params.append(filters.action)
        if filters.entity_type:
            clauses.append("a.entity_type = %s")
            params.append(filters.entity_type)
        if filters.actor_id is not None:
            clauses.append("a.actor_id = %s")
            params.append(str(filters.actor_id))
        if filters.since is not None:
            clauses.append("a.occurred_at >= %s")
            params.append(filters.since)
        if filters.until is not None:
            clauses.append("a.occurred_at <= %s")
            params.append(filters.until)
        if filters.search:
            # Səbəb mətni və entity ID-si üzrə sərbəst axtarış. `ILIKE`
            # seçildi (tam-mətn indeksi yox), çünki axtarış sahəsi qısa
            # sətirlərdir və indeks yükü faydasını üstələyərdi.
            #
            # `ESCAPE '\'` AÇIQ verilir: PostgreSQL-in defoltu onsuz da tərs
            # kəsikdir, lakin `standard_conforming_strings` söndürülmüş bir
            # bazada həmin defolt fərqli şərh olunur — davranışı server
            # ayarından ASILI qoymuruq.
            clauses.append("(a.reason ILIKE %s ESCAPE '\\' OR a.entity_id ILIKE %s ESCAPE '\\')")
            pattern = f"%{_escape_like(filters.search)}%"
            params.extend([pattern, pattern])

        return " AND ".join(clauses), tuple(params)

    def _fetch(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._connection.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())


__all__ = ["PostgresAuditReader", "PostgresAuditTrail"]
