"""Export-öncəsi DOĞRULAMA qaydaları — SAF DOMEN (kompas1.md Faza 8, bənd A).

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA MODUL — VƏ NİYƏ DOMENDƏ
──────────────────────────────────────────────────────────────────────────────
`work_norm.py` ilə EYNİ əsaslandırma: burada verilən qərar birbaşa PULA
toxunur. «Aralıqdan çox iş günü» işarəsi tutulmasa, işçi 30 günlük aralıqda
34 gün işləmiş kimi ödəniş alar; «deaktiv işçi tabeldə» işarəsi tutulmasa,
işdən çıxmış adama maaş hesablanar. Ona görə qaydalar SQL-də, ekranda və ya
Excel yazıcısında deyil — bazasız, deterministik test oluna bilən saf
funksiyada yaşayır.

Modul I/O TANIMIR: repository, `Clock`, `datetime.now()` yoxdur. Ona HAZIR
`ExportRowFacts` görüntüsü verilir.

──────────────────────────────────────────────────────────────────────────────
BLOKLAMA YOXDUR — XƏBƏRDARLIQ VAR (STRUKTUR QƏRAR)
──────────────────────────────────────────────────────────────────────────────
Heç bir qayda istisna ATMIR və heç bir sətri siyahıdan ÇIXARMIR. Nəticə
`ExportValidationFinding` siyahısıdır, son qərar isə HR-dədir
("[Təsdiqlə və Export Et]").

ALTERNATİVİN RƏDDİ: bloklama seçilsəydi, HR ayın son günü, maaş hesablanmalı
olanda, düzəldə bilmədiyi bir anomaliyaya görə HEÇ BİR fayl çıxara bilməzdi —
və işi görmək üçün rəqəmi bazada əl ilə "düzəldərdi", yəni sistemdən KƏNARA
çıxardı. Eyni fəlsəfə Faza 6-nın `ScheduleConflict`-ində və `MonthlyLeaveUsage`
aylıq 240 dəqiqə həddində (CLAUDE.md §9) artıq seçilib.

──────────────────────────────────────────────────────────────────────────────
HƏDDLƏR NİYƏ ARQUMENTDİR, MODUL SABİTİ DEYİL
──────────────────────────────────────────────────────────────────────────────
«Anomal yüksək icazəsiz-qayıb» faizi quraşdırmadan asılıdır: mövsümi işçi ilə
işləyən şəbəkədə 15% adi, sabit heyətli mağazada 5% artıq təhlükə siqnalıdır.
Ona görə ədəd BURADA YAZILMIR — `ExportValidationThresholds` kimi ötürülür və
onun mənbəyi ROOT parametridir (`EXPORT_STORE_ABSENCE_ANOMALY_PCT`,
`EXPORT_STORE_ANOMALY_MIN_EMPLOYEES`; seed: migrations/044).

Qalan üç qaydanın həddi YOXDUR və olmamalıdır — onlar ZİDDİYYƏTdir, siyasət
deyil: 30 günlük aralıqda 34 iş günü riyazi olaraq mümkün deyil, deaktiv işçi
tabeldə ya var, ya yox. Onlara "hədd" vermək yanlışı konfiqurasiya ilə
gizlətmək imkanı yaradardı.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from src.domain.value_objects.identifiers import EmployeeId

#: Faiz hesablamasının dəqiqliyi — bir onluq. Daha dəqiq rəqəm ekranda
#: oxunmur ("18.3%" kifayətdir), daha kobudu isə 5% ilə 5.4%-i eyni göstərərdi.
_PCT_QUANTUM: Final = Decimal("0.1")
_HUNDRED: Final = Decimal("100")


class ExportValidationCode(str, Enum):
    """Doğrulama qaydasının açarı.

    `str, Enum` (StrEnum YOX) — CLAUDE.md §4: `str(X.A)` nəticəsi audit/log
    çıxışına düşür və dəyişməməlidir.
    """

    #: Aralığın təqvim günündən ÇOX faktiki iş günü — riyazi ziddiyyət.
    EXCESS_WORK_DAYS = "EXCESS_WORK_DAYS"
    #: Deaktiv işçi tabeldə görünür (faktiki gün və ya qayıb sətri var).
    INACTIVE_IN_SHEET = "INACTIVE_IN_SHEET"
    #: Planı var, lakin nə işləyib, nə də qayıb sayılıb — məlumat boşluğu.
    ZERO_ACTIVITY_CONFLICT = "ZERO_ACTIVITY_CONFLICT"
    #: Mağaza üzrə anomal yüksək icazəsiz-qayıb nisbəti.
    STORE_ABSENCE_ANOMALY = "STORE_ABSENCE_ANOMALY"


#: Qayda açarı → ekranda göstərilən qısa ad. Mətn DOMENDƏDİR, ekranda yox:
#: eyni ad həm pre-export cədvəlində, həm audit sətrində görünür.
RULE_LABELS_AZ: Final[dict[ExportValidationCode, str]] = {
    ExportValidationCode.EXCESS_WORK_DAYS: "Aralıqdan çox iş günü",
    ExportValidationCode.INACTIVE_IN_SHEET: "Deaktiv işçi tabeldə",
    ExportValidationCode.ZERO_ACTIVITY_CONFLICT: "0 gün / 0 qayıb ziddiyyəti",
    ExportValidationCode.STORE_ABSENCE_ANOMALY: "Mağazada anomal qayıb",
}


@dataclass(frozen=True)
class ExportValidationThresholds:
    """Konfiqurasiya edilə bilən həddlər — mənbə ROOT (bax modul başlığı)."""

    #: Mağazanın icazəsiz-qayıb nisbəti (qayıb ÷ norma gün) bu faizi AŞARSA
    #: anomaliya sayılır.
    store_absence_pct: Decimal
    #: Mağazada bu qədərdən AZ işçi varsa anomaliya HESABLANMIR — bir nəfərlik
    #: filialda tək işçinin xəstəliyi 100% verər və hər ay yalançı siqnal olardı.
    store_min_employees: int

    def __post_init__(self) -> None:
        if self.store_absence_pct <= 0 or self.store_min_employees <= 0:
            # Mənasız hədd (0 və ya mənfi) HƏR mağazanı işarələyərdi — yəni
            # ROOT-dakı bir yazı səhvi doğrulama ekranını yararsız edərdi
            # (`work_norm._usable_cap` ilə eyni müdafiə).
            raise ValueError("Hədd müsbət olmalıdır")


@dataclass(frozen=True)
class ExportRowFacts:
    """Bir export sətrinin doğrulama üçün lazım olan MİNİMUM görüntüsü.

    `AttendanceRow` BURADA İSTİFADƏ EDİLMİR və bu, qat sırasının nəticəsidir:
    `AttendanceRow` TƏTBİQ qatının strukturudur (`application/use_cases/
    reporting.py`), domen isə ondan asılı ola bilməz. Çevirmə use case-dədir.
    """

    employee_id: EmployeeId
    full_name: str
    store_name: str
    norm_work_days: int
    actual_worked_days: int
    unauthorized_absences: int
    #: İşçi HAZIRDA aktivdirmi (`employees.is_active`).
    is_active: bool = True


@dataclass(frozen=True)
class ExportValidationFinding:
    """Bir şübhəli sətir — ekranda QIRMIZI işarələnir.

    `employee_id` `None` ola bilər: mağaza-səviyyəli anomaliya konkret işçiyə
    aid deyil və onu təsadüfi bir işçiyə yazmaq həmin adamı əsassız olaraq
    şübhəli göstərərdi.
    """

    code: ExportValidationCode
    subject_az: str
    detail_az: str
    employee_id: EmployeeId | None = None

    def rule_label_az(self) -> str:
        return RULE_LABELS_AZ[self.code]


def validate_export_rows(
    rows: Iterable[ExportRowFacts],
    *,
    range_day_count: int,
    thresholds: ExportValidationThresholds,
) -> tuple[ExportValidationFinding, ...]:
    """Dörd qaydanı ardıcıl tətbiq edir və tapıntıları qaytarır.

    Sıra DETERMİNİSTİKDİR: əvvəlcə işçi-səviyyəli tapıntılar (giriş sırası ilə),
    sonra mağaza-səviyyəli anomaliyalar (mağaza adına görə). Determinizm
    olmadan eyni məlumat üçün ekran hər açılışda fərqli sıralanardı və HR
    "yeni problem yarandı?" deyə düşünərdi.

    Boş siyahı → boş nəticə (çökmür): rol filtri heç nə qaytarmasa da ekran
    işləməyə davam etməlidir.
    """
    materialized = list(rows)
    findings: list[ExportValidationFinding] = []
    for row in materialized:
        findings.extend(_employee_findings(row, range_day_count=range_day_count))
    findings.extend(_store_findings(materialized, thresholds=thresholds))
    return tuple(findings)


def _employee_findings(
    row: ExportRowFacts, *, range_day_count: int
) -> tuple[ExportValidationFinding, ...]:
    """Üç işçi-səviyyəli ziddiyyət — hər biri müstəqildir (biri digərini udmur)."""
    findings: list[ExportValidationFinding] = []

    if range_day_count > 0 and row.actual_worked_days > range_day_count:
        findings.append(
            ExportValidationFinding(
                code=ExportValidationCode.EXCESS_WORK_DAYS,
                subject_az=row.full_name,
                detail_az=(
                    f"{row.actual_worked_days} iş günü qeydə alınıb, aralıq isə "
                    f"cəmi {range_day_count} təqvim günüdür — davamiyyət qeydlərində "
                    f"təkrar sətir ola bilər."
                ),
                employee_id=row.employee_id,
            )
        )

    if not row.is_active and (row.actual_worked_days > 0 or row.unauthorized_absences > 0):
        # ŞƏRT NİYƏ SADƏCƏ `not is_active` DEYİL: deaktiv işçi aralığın bir
        # hissəsində qanuni işləyib çıxa bilər və onda sətir DOĞRUDUR. Şübhəli
        # olan HALLA — deaktiv statusla birlikdə hərəkət qeydinin olmasıdır.
        findings.append(
            ExportValidationFinding(
                code=ExportValidationCode.INACTIVE_IN_SHEET,
                subject_az=row.full_name,
                detail_az=(
                    f"İşçi DEAKTİVDİR, lakin tabeldə hərəkət var: "
                    f"{row.actual_worked_days} iş günü, "
                    f"{row.unauthorized_absences} icazəsiz qayıb. "
                    f"Deaktivləşdirmə tarixini yoxlayın."
                ),
                employee_id=row.employee_id,
            )
        )

    if row.norm_work_days > 0 and row.actual_worked_days == 0 and row.unauthorized_absences == 0:
        findings.append(
            ExportValidationFinding(
                code=ExportValidationCode.ZERO_ACTIVITY_CONFLICT,
                subject_az=row.full_name,
                detail_az=(
                    f"{row.norm_work_days} gün planlaşdırılıb, lakin nə bir iş günü, "
                    f"nə də icazəsiz qayıb qeydə alınıb — kamera təsdiqi və ya "
                    f"məzuniyyət qeydi çatışmır."
                ),
                employee_id=row.employee_id,
            )
        )

    return tuple(findings)


def _store_findings(
    rows: Sequence[ExportRowFacts], *, thresholds: ExportValidationThresholds
) -> tuple[ExportValidationFinding, ...]:
    """Mağaza üzrə anomal yüksək icazəsiz-qayıb.

    NİSBƏT NİYƏ `qayıb ÷ norma gün`, «qayıb ÷ işçi sayı» YOX: ikinci variant
    yarım-ştat işçisi çox olan mağazanı həmişə pis göstərərdi (az norma günü =
    az imkan). Nisbət planlaşdırılmış günə bölünəndə mağazalar öz iş həcminə
    görə müqayisə olunur.
    """
    absences: dict[str, int] = {}
    norms: dict[str, int] = {}
    headcount: dict[str, int] = {}
    for row in rows:
        store = row.store_name
        absences[store] = absences.get(store, 0) + row.unauthorized_absences
        norms[store] = norms.get(store, 0) + row.norm_work_days
        headcount[store] = headcount.get(store, 0) + 1

    findings: list[ExportValidationFinding] = []
    for store in sorted(absences):
        planned = norms[store]
        if planned <= 0 or headcount[store] < thresholds.store_min_employees:
            # Planı olmayan mağazada nisbət hesablanmır (sıfıra bölmə) — və
            # onsuz da hər işçisi «0 gün / 0 qayıb» qaydası ilə ayrıca
            # işarələnir, yəni siqnal İTMİR.
            continue
        ratio = (Decimal(absences[store]) / Decimal(planned) * _HUNDRED).quantize(_PCT_QUANTUM)
        if ratio <= thresholds.store_absence_pct:
            continue
        findings.append(
            ExportValidationFinding(
                code=ExportValidationCode.STORE_ABSENCE_ANOMALY,
                subject_az=store,
                detail_az=(
                    f"İcazəsiz qayıb nisbəti {ratio}% — ROOT həddi "
                    f"{thresholds.store_absence_pct}%. "
                    f"{absences[store]} qayıb / {planned} norma gün, "
                    f"{headcount[store]} işçi."
                ),
            )
        )
    return tuple(findings)


__all__ = [
    "RULE_LABELS_AZ",
    "ExportRowFacts",
    "ExportValidationCode",
    "ExportValidationFinding",
    "ExportValidationThresholds",
    "validate_export_rows",
]
