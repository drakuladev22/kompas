"""Export-öncəsi ƏL İLƏ düzəliş — HR-yaxşılaşdırması D (kompas1.md Faza 8).

Sxem: `database/migrations/037_field_reports_and_hr_operations.sql` §10
(`export_manual_corrections`). Bu modul həmin sətrin DOMEN görüntüsüdür —
cədvəl DƏYİŞMİR, yeni sütun əlavə edilmir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ ENTITY DEYİL, DƏYİŞMƏZ DƏYƏR OBYEKTİ
──────────────────────────────────────────────────────────────────────────────
`AggregateRoot`-dan miras alan entity-lərin ortaq xüsusiyyəti VƏZİYYƏT
DƏYİŞMƏSİDİR (`Fine.publish()`, `Position.deactivate()`). Bu sətrin isə
vəziyyəti YOXDUR və heç vaxt dəyişmir: `migrations/037` ondan həm `UPDATE`,
həm `DELETE` hüququnu GERİ ALIR — "düzəlişin özü düzəldilə bilsəydi, kim nəyi
nəyə dəyişdi izi geri yazıla bilərdi". Yenidən düzəliş YENİ sətirdir və
`old_value` əvvəlkinin `new_value`-su olur.

Ona görə burada nə `record_event()`, nə mutasiya metodu var — yalnız
konstruktor invariantları.

──────────────────────────────────────────────────────────────────────────────
`old_value`/`new_value` NİYƏ MƏTNDİR (TİPLİ SÜTUN DƏSTİ RƏDD EDİLDİ)
──────────────────────────────────────────────────────────────────────────────
Düzəlişə düşən sahələr fərqli tiplidir (gün sayı, saat, sərbəst qeyd).
`corrected_days INT`, `corrected_hours NUMERIC`, `corrected_note TEXT` kimi
tipli sütun dəsti hər yeni export sütunu üçün miqrasiya tələb edərdi və
sətirlərin çoxunda boş qalardı. Mətn saxlama isə audit sualına ("nə nəyə
çevrildi?") tam cavab verir; rəqəmə çevirmə YALNIZ tətbiq anındadır
(`application/use_cases/export_preflight.py`) və orada uğursuz çevrilmə sətri
SÜKUTLA ATLAMIR — düzəliş tətbiq olunmur, lakin siyahıda görünməyə davam edir.

──────────────────────────────────────────────────────────────────────────────
SƏBƏBİN MİNİMUM UZUNLUĞU BURADA YOXDUR — VƏ BU, QƏSDƏNDİR
──────────────────────────────────────────────────────────────────────────────
Burada YALNIZ "səbəb boş ola bilməz" invariantı var. Həqiqi minimum uzunluq
ROOT parametridir (`EXPORT_CORRECTION_REASON_MIN_LENGTH`, seed:
migrations/044) və use case-də tətbiq olunur — CLAUDE.md §5: sinifdəki sabit
yalnız fallback ola bilər. DB-dəki `char_length(trim(reason)) >= 10` yoxlaması
isə siyasət deyil, ABSURD cavabı ("ok", ".") kəsən DÖŞƏMƏDİR (migrations/037
şərhi).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from src.domain.value_objects.identifiers import new_export_correction_id
from src.domain.value_objects.scheduling import require_aware
from src.shared.exceptions import KompasOSError

if TYPE_CHECKING:
    from datetime import date, datetime

    from src.domain.value_objects.identifiers import (
        EmployeeId,
        ExportCorrectionId,
        TenantId,
    )

#: Davamiyyət export-unun növ açarı (`export_manual_corrections.export_type`).
#: `ReportRange.key`-dən FƏRQLİDİR: bu, HANSI FAYLIN düzəldildiyini bildirir,
#: hansı DÖVRÜN deyil — dövr `target_date` sütunundadır.
EXPORT_TYPE_ATTENDANCE: Final = "DAVAMIYYET"
#: Premiya & Cərimə export-unun növ açarı. Sxemdə sərt siyahı YOXDUR (yeni
#: export növü miqrasiya tələb etməməlidir), lakin KOD tərəfdə iki sabit var:
#: sətirlərin süzülməsi ("bu faylın düzəlişləri") məhz bu dəyərə görə işləyir
#: və sərbəst mətn yazılsaydı, bir yazı səhvi düzəlişi görünməz edərdi.
EXPORT_TYPE_BONUS_PENALTY: Final = "BONUS_CERIME"

#: Düzəldilə bilən export sütunları — kod → (Azərbaycanca ad, ədədidirmi).
#:
#: SABİT SİYAHI BURADA HAQLIDIR (rol filtri ilə ZİDD DEYİL): bunlar
#: `infrastructure/reporting/excel.py`-dakı FAYLIN ÖZ SÜTUNLARIDIR — sərbəst
#: sahə adı qəbul etsəydik, "TABEL_GUNU" kimi bir düzəliş heç bir sütuna
#: düşməz və HR "düzəltdim, amma rəqəm dəyişmədi" vəziyyətində qalardı.
#: Rol siyahısı isə əksinə, MƏLUMATDIR (kataloq sətri) və oradan oxunur.
#:
#: `QEYD` ədədi DEYİL: o, rəqəmi dəyişmir, yalnız Excel-in "Qeyd" sütununu
#: doldurur (kompas1.md Faza 8, bənd E). Ayrı "qeyd" cədvəli QƏSDƏN
#: yaradılmadı — ikinci sərbəst-mətn kanalı audit-siz qalardı, halbuki burada
#: hər qeyd səbəb + müəllif + vaxt ilə birlikdə yazılır.
CORRECTABLE_FIELDS: Final[dict[str, tuple[str, bool]]] = {
    "NORMA_GUN": ("Norma iş günləri", True),
    "FAKTIKI_GUN": ("Faktiki işlənilən gün", True),
    "OFF_DAY": ("Off-day sayı", True),
    "ICAZESIZ_QAYIB": ("İcazəsiz qayıb", True),
    "QEYD": ("Qeyd (sərbəst mətn)", False),
}

#: `CORRECTABLE_FIELDS`-in sərbəst-mətn sahəsi — Excel "Qeyd" sütununun mənbəyi.
NOTE_FIELD: Final = "QEYD"


class ExportCorrectionError(KompasOSError):
    """Düzəliş sətri qurula bilmədi."""

    user_message = "Export düzəlişi qeydə alınmadı."


@dataclass(frozen=True)
class ExportCorrection:
    """`export_manual_corrections` sətrinin dəyişməz domen görüntüsü."""

    tenant_id: TenantId
    export_type: str
    employee_id: EmployeeId
    target_date: date
    field: str
    old_value: str | None
    new_value: str | None
    reason: str
    corrected_by: EmployeeId
    corrected_at: datetime
    #: `default_factory` — `StoreTemplate.store_template_id`-dən FƏRQLİ olaraq
    #: BURADA `None` qalmır: sətrin İD-si audit `entity_id`-sidir və audit
    #: yazısı düzəliş DB-yə düşməzdən ƏVVƏL də doğru olmalıdır (CLAUDE.md §5 —
    #: audit istisna udmur). `None` buraxılsaydı, audit "hansı düzəliş?"
    #: sualına yalnız `INSERT`-dən SONRA cavab verə bilərdi.
    #:
    #: `dataclasses.field(...)` TAM ADLA yazılır: bu sinifdə `field` adlı SAHƏ
    #: var (`export_manual_corrections.field` sütunu) və o, sinif gövdəsində
    #: eyniadlı funksiyanı KÖLGƏLƏYİR — qısa `field(...)` çağırışı tip
    #: yoxlayıcısında "str çağırıla bilməz" xətası verir. Sütunu adlandırmaqla
    #: sxem arasındakı uyğunluq bu kiçik naxışdan vacibdir.
    correction_id: ExportCorrectionId = dataclasses.field(default_factory=new_export_correction_id)

    def __post_init__(self) -> None:
        export_type = self.export_type.strip().upper()
        if not export_type:
            raise ExportCorrectionError("Export növü boş ola bilməz")
        object.__setattr__(self, "export_type", export_type)

        field_code = self.field.strip().upper()
        if field_code not in CORRECTABLE_FIELDS:
            # Naməlum sahə SÜKUTLA qəbul edilmir: sətir yazılardı, lakin heç
            # bir export sütununa düşməzdi — yəni audit izi olan, təsirsiz
            # "düzəliş" yaranardı (ən çaşdırıcı hal).
            raise ExportCorrectionError(
                f"Düzəldilə bilməyən sahə: {field_code}",
                user_message="Bu sütun üçün düzəliş dəstəklənmir.",
                context={"field": field_code},
            )
        object.__setattr__(self, "field", field_code)

        reason = self.reason.strip()
        if not reason:
            raise ExportCorrectionError(
                "Düzəlişin səbəbi məcburidir",
                user_message="Düzəlişin səbəbini yazın — səbəbsiz düzəliş qeydə alınmır.",
            )
        object.__setattr__(self, "reason", reason)

        old_value = _clean(self.old_value)
        new_value = _clean(self.new_value)
        if old_value == new_value:
            # DB-də də eyni yoxlama var (`chk_export_correction_changes`), lakin
            # burada TƏKRARLANIR: ekranı yan keçən skript də ona tabe olmalıdır
            # və domen səviyyəsində rədd aydın mesaj verir, DB xətası isə yox.
            raise ExportCorrectionError(
                "Düzəliş heç nəyi dəyişmir",
                user_message="Yeni dəyər köhnə dəyərlə eynidir — düzəliş qeydə alınmadı.",
                context={"value": str(old_value)},
            )
        object.__setattr__(self, "old_value", old_value)
        object.__setattr__(self, "new_value", new_value)

        object.__setattr__(
            self, "corrected_at", require_aware(self.corrected_at, field="düzəliş anı")
        )

    @property
    def is_note(self) -> bool:
        """Bu sətir rəqəmi dəyişirmi, yoxsa yalnız «Qeyd» sütununu doldurur."""
        return self.field == NOTE_FIELD

    @property
    def is_numeric(self) -> bool:
        """Sahə export-un ƏDƏDİ sütunudur (tətbiq zamanı `int`-ə çevrilir)."""
        return CORRECTABLE_FIELDS[self.field][1]

    def field_label_az(self) -> str:
        """Ekranda və audit sətrində göstərilən sütun adı."""
        return CORRECTABLE_FIELDS[self.field][0]

    def summary_az(self) -> str:
        """«Nə nəyə çevrildi» — hazır Azərbaycan cümləsi.

        Mətn BURADA qurulur, ekranda yox: eyni cümlə həm düzəliş siyahısında,
        həm Excel-in «Qeyd» sütununda lazımdır və iki yerdə yazılsaydı biri
        yenilənəndə digəri fərqlənərdi (`BonusPenaltySelection.
        overlap_notice_az()` ilə eyni qərar).
        """
        if self.is_note:
            return f"{self.new_value or '—'}"
        before = self.old_value if self.old_value is not None else "boş"
        after = self.new_value if self.new_value is not None else "boş"
        return f"{self.field_label_az()}: {before} → {after}"


def _clean(value: str | None) -> str | None:
    """Boş sətri `None`-a çevirir.

    `''` və `NULL` fərqi auditdə MƏNASIZDIR ("sahə boş idi" hər iki halda),
    lakin `chk_export_correction_changes` üçün TƏHLÜKƏLİDİR: `'' IS DISTINCT
    FROM NULL` DOĞRUDUR, yəni heç nəyi dəyişməyən düzəliş DB-dən keçərdi.
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


__all__ = [
    "CORRECTABLE_FIELDS",
    "EXPORT_TYPE_ATTENDANCE",
    "EXPORT_TYPE_BONUS_PENALTY",
    "NOTE_FIELD",
    "ExportCorrection",
    "ExportCorrectionError",
]
