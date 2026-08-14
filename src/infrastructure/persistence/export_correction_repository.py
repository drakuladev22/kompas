"""`export_manual_corrections` + kadr vəziyyəti — kompas1.md Faza 8 (HR-D, A, G).

Sxem: `database/migrations/037_field_reports_and_hr_operations.sql` §10. Bu
modul CƏDVƏLİ DƏYİŞMİR — yalnız oxuyub yazır.

──────────────────────────────────────────────────────────────────────────────
BİR SİNİF, İKİ PROTOKOL
──────────────────────────────────────────────────────────────────────────────
Sinif həm `ExportCorrectionRepository` (domen portu), həm də
`ExportRosterProvider` (tətbiq portu) müqaviləsini ödəyir və `connection.py`-də
İKİ AÇARLA qeydiyyatdan keçir (`PostgresAttritionRepository` /
`PostgresExecutiveDigestConfigRepository` ilə EYNİ naxış).

NİYƏ İKİ AYRI SİNİF DEYİL: hər iki sorğu EYNİ ekranın EYNİ yüklənməsində,
EYNİ tranzaksiyada işləyir — düzəliş yazıldıqdan dərhal sonra doğrulama
yenidən qiymətləndirilir və o, hələ commit olunmamış sətri GÖRMƏLİDİR. Ayrı
bağlantıda yeni düzəliş "yoxa çıxardı" və HR onu ikinci dəfə yazardı.

NİYƏ EYNİ SİNİF `report_repositories.py`-a QOŞULMADI: `PostgresReportFact
Provider` PUL sətirlərinin (norma/faktiki gün, satış, xal) mənbəyidir və onun
sorğuları hesabat rəqəmini müəyyən edir. Buradakı iki sorğu isə METAdır (kim
aktivdir, kim nəyi düzəldib) — birinə edilən dəyişiklik digərinin nəticəsini
dəyişməməlidir.

──────────────────────────────────────────────────────────────────────────────
`UPDATE`/`DELETE` METODU YOXDUR — SXEM ONLARI QADAĞAN EDİR
──────────────────────────────────────────────────────────────────────────────
`migrations/037` tətbiq rolundan `UPDATE` və `DELETE` hüquqlarını AÇIQ geri
alır. Belə metod yazılsaydı, o, hər çağırışda icazə xətası ilə bitərdi — yəni
kod bir imkan VƏD EDƏRDİ, hansı ki mövcud deyil. Yenidən düzəliş YENİ sətirdir
(`old_value` = əvvəlkinin `new_value`-su).

──────────────────────────────────────────────────────────────────────────────
KADR SORĞUSU NİYƏ `LEFT JOIN positions`
──────────────────────────────────────────────────────────────────────────────
Rolu silinmiş/naməlum işçi sətirdən DÜŞMÜR (`INNER JOIN` onu gizlədərdi) —
`position_code` boş qayıdır və rol filtri onu seçim kimi göstərmir, lakin
"bütün rollar" görünüşündə sətir yerində qalır: HR həmin işçini export-da
GÖRMƏLİDİR, əks halda maaşı sükutla düşərdi.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.application.use_cases.export_preflight import EmployeeRosterStatus
from src.domain.value_objects.export_corrections import ExportCorrection
from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from datetime import date
    from typing import Any

    from src.domain.value_objects.identifiers import StoreId, TenantId


class PostgresExportCorrectionRepository(_BaseRepository):
    """`ExportCorrectionRepository` + `ExportRosterProvider` tətbiqi."""

    # ----------------------------- HR-D düzəlişləri --------------------------- #

    def save(self, entry: ExportCorrection) -> None:
        """Yeni düzəliş sətri — UPSERT DEYİL, sadə `INSERT`.

        `ON CONFLICT` YOXDUR VƏ OLMAMALIDIR: sətrin təbii açarı yalnız `id`-dir
        (surroqat) və eyni işçi/gün/sahə üçün TƏKRAR düzəliş QANUNİDİR — o,
        auditin özüdür ("əvvəlcə 20 yazdı, sonra 21-ə düzəltdi"). `ON CONFLICT
        DO UPDATE` həmin izi silərdi.
        """
        self._execute(
            """
            INSERT INTO export_manual_corrections
                (id, tenant_id, export_type, employee_id, target_date, field,
                 old_value, new_value, reason, corrected_by, corrected_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                entry.correction_id,
                entry.tenant_id,
                entry.export_type,
                entry.employee_id,
                entry.target_date,
                entry.field,
                entry.old_value,
                entry.new_value,
                entry.reason,
                entry.corrected_by,
                entry.corrected_at,
            ),
        )

    def list_for_range(
        self,
        tenant_id: TenantId,
        *,
        export_type: str,
        start: date,
        end: date,
    ) -> list[ExportCorrection]:
        """Aralığın düzəlişləri — `corrected_at` üzrə ARTAN sırada.

        Sıra port müqaviləsinin bir hissəsidir: `apply_corrections()` eyni
        sahəyə edilmiş SONUNCU düzəlişi qalib sayır. `id` ikinci açardır ki,
        eyni mikrosaniyədə yazılmış iki sətir də determinstik sıralansın
        (testin təkrarlana bilməsi üçün — `list_route_recipients` ilə eyni
        əsaslandırma).

        İndeks: `idx_export_corrections_lookup (tenant_id, export_type,
        target_date)` — sorğu məhz bu üç sütunla süzülür.
        """
        rows = self._fetch_all(
            """
            SELECT id, tenant_id, export_type, employee_id, target_date, field,
                   old_value, new_value, reason, corrected_by, corrected_at
              FROM export_manual_corrections
             WHERE tenant_id = %s
               AND export_type = %s
               AND target_date BETWEEN %s AND %s
             ORDER BY corrected_at, id
            """,
            (tenant_id, export_type.strip().upper(), start, end),
        )
        return [_hydrate(row) for row in rows]

    # ------------------------- kadr vəziyyəti (A + G) ------------------------- #

    def roster_status(
        self,
        tenant_id: TenantId,
        *,
        start: date,
        end: date,
        store_id: StoreId | None = None,
    ) -> list[EmployeeRosterStatus]:
        """İşçi → (aktivdirmi, rol kodu, rol adı).

        `start`/`end` QƏBUL EDİLİR, LAKİN SORĞUDA İŞLƏDİLMİR — və bu, qəsdli
        qərardır: `employees.is_active` CARİ vəziyyətdir, tarixə görə deyil.
        Aralıq parametri müqavilədə saxlanılır ki, `ReportFactProvider`/
        `PlanFactProvider` ilə EYNİ imza olsun (kontroller üçünü eyni cür
        çağırır) və gələcəkdə tarixli kadr tarixçəsi əlavə olunarsa çağırış
        yerləri DƏYİŞMƏSİN. Silinsəydi, hər çağırış yeri yenidən yazılmalı
        olardı.

        DEAKTİV İŞÇİ SÜZÜLMÜR (`WHERE e.is_active` YOXDUR) — bu, bənd A-nın
        "deaktiv, amma tabeldə görünən işçi" qaydasının BÜTÜN ƏSASIDIR: onları
        sorğuda kəssəydik, qayda heç vaxt işə düşməzdi.
        """
        del start, end  # bax docstring — imza uyğunluğu üçün saxlanılır
        rows = self._fetch_all(
            """
            SELECT e.id                       AS employee_id,
                   e.is_active                AS is_active,
                   COALESCE(p.code, '')       AS position_code,
                   COALESCE(p.name_az, '—')   AS position_name
              FROM employees e
              LEFT JOIN positions p ON p.id = e.position_id
             WHERE e.tenant_id = %s
               AND (%s::uuid IS NULL OR e.store_id = %s::uuid)
             ORDER BY e.last_name, e.first_name, e.id
            """,
            (tenant_id, store_id, store_id),
        )
        return [
            EmployeeRosterStatus(
                employee_id=row["employee_id"],
                is_active=bool(row["is_active"]),
                position_code=str(row["position_code"]),
                position_name=str(row["position_name"]),
            )
            for row in rows
        ]


def _hydrate(row: dict[str, Any]) -> ExportCorrection:
    """DB sətrini domen dəyər obyektinə çevirir.

    `__post_init__` invariantları BURADA DA işləyir (boş səbəb, dəyişməyən
    dəyər, naməlum sahə) — bu, təkrar deyil, İKİNCİ QAPIDIR: bazaya birbaşa
    `INSERT` edən köhnə skript sətri pozarsa, o, oxu anında aydın domen xətası
    verir, ekranda naməlum davranış yox.
    """
    return ExportCorrection(
        correction_id=row["id"],
        tenant_id=row["tenant_id"],
        export_type=str(row["export_type"]),
        employee_id=row["employee_id"],
        target_date=row["target_date"],
        field=str(row["field"]),
        old_value=row["old_value"],
        new_value=row["new_value"],
        reason=str(row["reason"]),
        corrected_by=row["corrected_by"],
        corrected_at=row["corrected_at"],
    )


__all__ = ["PostgresExportCorrectionRepository"]
