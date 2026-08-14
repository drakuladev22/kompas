"""Export təcrübəsi — pre-export doğrulama, düzəliş, müqayisə, rol filtri.

kompas1.md Faza 8 (bəndlər A, D, E, F, G). Bu modul MÖVCUD hesabat mühərrikinin
ÜSTÜNDƏ oturur: `MonthlyReportUseCase` sətirləri necə hesablayırsa, ELƏ DƏ
qalır — burada nə norma, nə pro-rata, nə də cərimə seçimi YENİDƏN hesablanır
(`domain/work_norm.py` Faza 7-dən TOXUNULMAMIŞ qalır). Bu modul hazır sətirləri
QƏBUL EDİR və onların üzərində dörd yeni sual verir:

    A — hansı sətirlər ŞÜBHƏLİDİR?            → `domain/export_validation.py`
    D — hansı sətirlər ƏL İLƏ düzəldilib?     → `export_manual_corrections`
    F — keçən eyni-uzunluqda dövrlə fərq nə?  → `compare_periods()`
    G — yalnız hansı rol export edilsin?      → `filter_by_role()`

──────────────────────────────────────────────────────────────────────────────
DOĞRULAMA BLOKLAMIR — SON QƏRAR HR-DƏDİR
──────────────────────────────────────────────────────────────────────────────
`review()` heç bir halda istisna ATMIR (səlahiyyət yoxlamasından başqa) və heç
bir sətri siyahıdan ÇIXARMIR. Şübhəli sətirlər `findings`-də qayıdır, HR isə
"[Təsdiqlə və Export Et]" ilə davam edir. Əsaslandırma `domain/export_
validation.py` başlığındadır (Faza 6-nın `ScheduleConflict` fəlsəfəsi).

──────────────────────────────────────────────────────────────────────────────
DÜZƏLİŞ NİYƏ SƏTİRLƏRƏ TƏTBİQ OLUNUR, MƏNBƏ CƏDVƏLƏ YAZILMIR
──────────────────────────────────────────────────────────────────────────────
`record_correction()` `attendance_records`/`shift_assignments` cədvəllərinə
TOXUNMUR — yalnız `export_manual_corrections`-a sətir yazır. Səbəb: mənbə
cədvəllər KAMERA-TƏSDİQLİ FAKTdır (`report_repositories.py` başlığı) və HR-in
bir kliklə onları dəyişməsi həmin təsdiqin dəyərini sıfırlayardı — "faktiki
gün" sütunu artıq nəyin faktı olduğunu bildirməzdi.

Ona görə model belədir: **fakt qalır, düzəliş onun ÜSTÜNDƏ AYRICA sətirdir və
export anında tətbiq olunur.** Hər iki rəqəm (əvvəl/sonra) həmişə görünür,
düzəlişin müəllifi və səbəbi isə həmişə auditdədir.

──────────────────────────────────────────────────────────────────────────────
KEÇMİŞ DÖVR NİYƏ «EYNİ UZUNLUQDA», «KEÇƏN AY» YOX
──────────────────────────────────────────────────────────────────────────────
kompas1.md açıq şəkildə "keçən EYNİ-UZUNLUQDA dövr" deyir və bu, ixtiyari
aralıq seçimi (Faza 7) ilə birlikdə məcburi olur: 1–15 aprel ilə martın
TAMAMINI müqayisə etmək "icazəsiz qayıb iki dəfə az oldu" kimi YALAN nəticə
verərdi. `previous_range()` aralığın gün sayını saxlayır və başlanğıcdan BİR
GÜN əvvəl bitirir.

Tam ay xüsusi hal kimi DÜZGÜN işləyir: 31 günlük iyul üçün əvvəlki 31 gün
30 iyun–30 may olur, yəni «tam iyun» DEYİL. Bu, QƏSDƏNDİR — uzunluq bərabərliyi
təqvim adından vacibdir, çünki müqayisə olunan rəqəm (qayıb sayı) günlərin
sayına düz mütənasibdir.

──────────────────────────────────────────────────────────────────────────────
BU MODUL FAYL YAZMIR
──────────────────────────────────────────────────────────────────────────────
`.xlsx` yazma `infrastructure/reporting/excel.py`-dədir (`reporting.py` ilə
eyni sərhəd). Burada yalnız sətirlər hazırlanır və «Qeyd» sütununun məzmunu
(`notes_for()`) yığılır.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from src.application.use_cases.reporting import (
    EXPORT_REPORTS_FLAG,
    AttendanceRow,
    ReportPermissionError,
    ReportRange,
)
from src.domain.export_validation import (
    ExportRowFacts,
    ExportValidationFinding,
    ExportValidationThresholds,
    validate_export_rows,
)
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.export_corrections import (
    CORRECTABLE_FIELDS,
    EXPORT_TYPE_ATTENDANCE,
    ExportCorrection,
    ExportCorrectionError,
)
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        Clock,
        ExportCorrectionRepository,
        SystemLimits,
    )
    from src.domain.value_objects.identifiers import EmployeeId, StoreId, TenantId

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

#: Manual düzəliş səlahiyyəti (`migrations/038`). `can_export_reports`-dan
#: AYRIDIR VƏ QƏSDƏN: hesabatı çıxarmaq (oxu) ilə onun rəqəmini dəyişmək (yazı)
#: eyni məsuliyyət deyil — birincisi mühasibə də verilə bilər, ikincisi yox.
EXPORT_CORRECTIONS_FLAG = "can_manage_export_corrections"

#: FALLBACK-lar — HƏQİQİ MƏNBƏ `system_limits` (seed: migrations/044). Ədəd
#: BURADA YAZILMIR, `DEFAULT_LIMITS`-dən oxunur ki, kod və seed heç vaxt fərqli
#: defoltla işləməsin (`reporting.FALLBACK_RANGE_MAX_DAYS` ilə eyni naxış).
FALLBACK_STORE_ABSENCE_PCT: Decimal = Decimal(
    DEFAULT_LIMITS[SystemLimitKey.EXPORT_STORE_ABSENCE_ANOMALY_PCT]
)
FALLBACK_STORE_MIN_EMPLOYEES: int = int(
    DEFAULT_LIMITS[SystemLimitKey.EXPORT_STORE_ANOMALY_MIN_EMPLOYEES]
)
FALLBACK_SIGNIFICANT_DELTA: int = int(
    DEFAULT_LIMITS[SystemLimitKey.EXPORT_PERIOD_DELTA_SIGNIFICANT]
)
FALLBACK_REASON_MIN_LENGTH: int = int(
    DEFAULT_LIMITS[SystemLimitKey.EXPORT_CORRECTION_REASON_MIN_LENGTH]
)


class ExportCorrectionPermissionError(KompasOSError):
    """Manual düzəliş etmək səlahiyyəti yoxdur."""

    user_message = "Export düzəlişi etmək səlahiyyətiniz yoxdur."


class ExportCorrectionReasonError(KompasOSError):
    """Səbəb sahəsi boşdur və ya çox qısadır.

    AYRI SİNİF QƏSDƏNDİR (`ReportRangeTooLongError` ilə eyni əsaslandırma):
    istifadəçinin görəcəyi iş fərqlidir — burada düzəlişin ÖZÜ doğrudur, yalnız
    izah kifayət etmir. Ümumi istisna ilə göstərilsəydi, HR dəyəri dəyişməyə
    çalışıb heç nə əldə etməzdi.
    """

    user_message = "Düzəlişin səbəbini yazın — səbəbsiz düzəliş qeydə alınmır."


# --------------------------------------------------------------------------- #
# Portlar və giriş strukturları
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EmployeeRosterStatus:
    """Bir işçinin kadr vəziyyəti + rol kodu.

    NİYƏ `EmployeeAttendanceFacts`-ə QOŞULMUR: həmin struktur `ReportFact
    Provider` protokolunun MÜQAVİLƏSİDİR və ona sahə əlavə etmək onu ödəyən HƏR
    sinfi (test sahtələri daxil) dərhal uyğunsuz edərdi — məhz `PlanFact
    Provider` Faza 7-də AYRI protokol kimi doğulanda verilmiş qərar.

    `position_code` var, ÇÜNKİ ROL FİLTRİ AD-a görə İŞLƏMƏMƏLİDİR: rol adı
    (`positions.name_az`) Root panelindən dəyişdirilə bilər və filtr seçimi
    həmin an sükutla boşalardı. Kod isə sabitdir.
    """

    employee_id: EmployeeId
    is_active: bool
    position_code: str
    position_name: str


@runtime_checkable
class ExportRosterProvider(Protocol):
    """Kadr vəziyyətinin oxunma portu.

    NİYƏ `domain/interfaces/ports.py`-DA DEYİL: qaytardığı `EmployeeRoster
    Status` TƏTBİQ qatının strukturudur (`ReportFactProvider`/`PlanFactProvider`
    ilə EYNİ əsaslandırma) — onu domenə qoymaq domen → application asılılığı
    yaradardı.
    """

    def roster_status(
        self,
        tenant_id: TenantId,
        *,
        start: date,
        end: date,
        store_id: StoreId | None = None,
    ) -> list[EmployeeRosterStatus]: ...


@dataclass(frozen=True)
class RoleOption:
    """Rol filtri dropdown-unun bir sətri (bənd G)."""

    code: str
    name_az: str


@dataclass(frozen=True)
class MetricDelta:
    """Bir metrikin dövr-üzrə fərqi (bənd F)."""

    metric_key: str
    label_az: str
    current: int
    previous: int
    #: Keçən dövr üçün ÜMUMİYYƏTLƏ məlumat varmı. `False` olduqda `previous`
    #: 0-dır, lakin bu, "sıfır idi" DEMƏK DEYİL — "bilinmir" deməkdir və ekran
    #: fərqi göstərməməlidir (yalançı «−12» kimi oxunardı).
    has_baseline: bool = True
    #: ROOT həddini aşan fərq (`EXPORT_PERIOD_DELTA_SIGNIFICANT`).
    is_significant: bool = False

    @property
    def delta(self) -> int:
        return self.current - self.previous

    def delta_text_az(self) -> str:
        """«+3» / «−1» / «—» (baza yoxdursa) — hazır mətn.

        Mətn BURADA qurulur, ekranda yox: eyni ifadə həm pre-export kartında,
        həm audit sətrində lazımdır (`BonusPenaltySelection.overlap_notice_az()`
        ilə eyni qərar).
        """
        if not self.has_baseline:
            return "—"
        value = self.delta
        if value == 0:
            return "0"
        # ASCII `-` DEYİL, tipoqrafik minus: ekranda `+3`/`−1` cütü eyni
        # eni tutur və sütun sürüşmür.
        return f"+{value}" if value > 0 else f"−{abs(value)}"


@dataclass(frozen=True)
class ExportPreflightReview:
    """`review()`-in nəticəsi — ekranın göstərdiyi HƏR ŞEY.

    Tək struktur qaytarılır (dörd ayrı metod deyil), çünki dördü də EYNİ
    sətir dəstindən çıxır: rol filtri tətbiq olunduqdan SONRA doğrulama da,
    müqayisə də, «Qeyd» sütunu da həmin alt-çoxluğa aid olmalıdır. Ayrı-ayrı
    çağırışlar filtri birində tətbiq edib digərində unutmaq riskini yaradardı.
    """

    rows: list[AttendanceRow] = field(default_factory=list)
    findings: tuple[ExportValidationFinding, ...] = ()
    deltas: tuple[MetricDelta, ...] = ()
    role_options: tuple[RoleOption, ...] = ()
    corrections: tuple[ExportCorrection, ...] = ()
    notes: Mapping[EmployeeId, str] = field(default_factory=dict)
    #: Müqayisə üçün seçilmiş əvvəlki aralıq — ekranda AÇIQ göstərilir ki, HR
    #: hansı dövrlə müqayisə etdiyini bilsin ("keçən ay" fərziyyəsi etməsin).
    previous_range: ReportRange | None = None
    #: Rol filtri tətbiq olunmazdan ƏVVƏLKİ sətir sayı — "235-dən 48-i
    #: göstərilir" mətni üçün.
    total_row_count: int = 0

    @property
    def has_findings(self) -> bool:
        return bool(self.findings)

    def blocking_message_az(self) -> None:
        """QƏSDƏN `None` QAYTARIR — bloklayıcı mesaj YOXDUR.

        Metod mövcuddur ki, gələcəkdə kimsə "doğrulama nəyi bloklayır?" deyə
        axtaranda cavabı KODDA tapsın: heç nəyi. Bax modul başlığı.
        """
        return None


# --------------------------------------------------------------------------- #
# Use case
# --------------------------------------------------------------------------- #


class ExportPreflightUseCase:
    """Pre-export doğrulama ekranının arxa tərəfi.

    `Clock` portu ALINIR (`MonthlyReportUseCase`-dən FƏRQLİ olaraq) və bu, ona
    zidd deyil: orada "hansı an" sualı hesabatın RƏQƏMİNİ dəyişirdi (72 saatlıq
    pəncərə), ona görə görünən parametr olmalıydı. Burada isə vaxt yalnız
    düzəlişin YAZILMA anıdır — heç bir rəqəmi dəyişmir, lakin tz-aware və
    determinstik test oluna bilən olmalıdır (CLAUDE.md §4).
    """

    def __init__(
        self,
        *,
        corrections: ExportCorrectionRepository,
        roster: ExportRosterProvider,
        audit: AuditTrail,
        clock: Clock,
        limits: SystemLimits | None = None,
    ) -> None:
        self._corrections = corrections
        self._roster = roster
        self._audit = audit
        self._clock = clock
        self._limits = limits

    # ------------------------------ oxu yolu --------------------------------- #

    def review(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        rows: Sequence[AttendanceRow],
        report_range: ReportRange,
        previous_rows: Sequence[AttendanceRow] = (),
        role_code: str | None = None,
        export_type: str = EXPORT_TYPE_ATTENDANCE,
        store_id: StoreId | None = None,
    ) -> ExportPreflightReview:
        """Excel yaranmazdan ƏVVƏLKİ tam mənzərə.

        Ardıcıllıq ƏHƏMİYYƏTLİDİR və məhz bu sıradadır:
          1. kadr vəziyyəti oxunur (aktivlik + rol);
          2. rol filtri tətbiq olunur (bənd G) — sonrakı hər addım alt-çoxluğa
             aiddir;
          3. düzəlişlər tətbiq olunur (bənd D) — doğrulama DÜZƏLDİLMİŞ rəqəmə
             baxmalıdır, əks halda HR səhvi düzəltdikdən sonra da qırmızı
             xəbərdarlığı görməyə davam edərdi;
          4. doğrulama işləyir (bənd A);
          5. keçən dövrlə müqayisə (bənd F).

        Səlahiyyət: `can_export_reports`. Düzəliş flag-i BURADA TƏLƏB EDİLMİR —
        baxmaq və düzəltmək ayrı məsuliyyətdir (bax `EXPORT_CORRECTIONS_FLAG`).
        """
        now = self._clock.now()
        if not actor.has_permission(EXPORT_REPORTS_FLAG, now=now):
            _audit_log.warning(
                "EXPORT_PREFLIGHT_DENIED",
                extra={"actor_id": str(actor.id), "flag": EXPORT_REPORTS_FLAG},
            )
            raise ReportPermissionError(
                f"«{EXPORT_REPORTS_FLAG}» səlahiyyəti yoxdur",
                context={"actor_id": str(actor.id)},
            )

        roster = self._roster.roster_status(
            tenant_id, start=report_range.start, end=report_range.end, store_id=store_id
        )
        by_employee = {entry.employee_id: entry for entry in roster}
        options = _role_options(roster)

        selected = filter_by_role(rows, roster=by_employee, role_code=role_code)
        corrections = tuple(
            self._corrections.list_for_range(
                tenant_id,
                export_type=export_type,
                start=report_range.start,
                end=report_range.end,
            )
        )
        visible_ids = {row.employee_id for row in selected}
        scoped = tuple(item for item in corrections if item.employee_id in visible_ids)

        corrected = apply_corrections(selected, scoped)
        findings = validate_export_rows(
            _to_facts(corrected, roster=by_employee),
            range_day_count=report_range.day_count,
            thresholds=self._thresholds(tenant_id),
        )

        previous_selected = filter_by_role(previous_rows, roster=by_employee, role_code=role_code)
        deltas = compare_periods(
            corrected,
            previous_selected,
            significant_delta=self._significant_delta(tenant_id),
            has_baseline=bool(previous_rows),
        )

        _audit_log.info(
            "EXPORT_PREFLIGHT_REVIEWED",
            extra={
                "actor_id": str(actor.id),
                "period": report_range.key,
                "rows": len(corrected),
                "findings": len(findings),
                "corrections": len(scoped),
                "role_filter": role_code or "ALL",
            },
        )
        return ExportPreflightReview(
            rows=list(corrected),
            findings=findings,
            deltas=deltas,
            role_options=options,
            corrections=scoped,
            notes=notes_for(scoped),
            previous_range=self.previous_range(report_range) if previous_rows else None,
            total_row_count=len(rows),
        )

    @staticmethod
    def previous_range(report_range: ReportRange) -> ReportRange:
        """EYNİ UZUNLUQDA əvvəlki aralıq (bax modul başlığı).

        Bir günlük aralıq üçün "dünən" qaytarır — `day_count` HƏR İKİ ucu
        sayır, ona görə düstur `start − day_count` … `start − 1`-dir.
        """
        end = report_range.start - timedelta(days=1)
        start = end - timedelta(days=report_range.day_count - 1)
        return ReportRange(start, end)

    # ------------------------------ yazı yolu -------------------------------- #

    def record_correction(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        employee_id: EmployeeId,
        target_date: date,
        field_code: str,
        old_value: str | None,
        new_value: str | None,
        reason: str,
        export_type: str = EXPORT_TYPE_ATTENDANCE,
    ) -> ExportCorrection:
        """Manual düzəlişi yazır (bənd D) — SƏBƏB MƏCBURİDİR.

        Sıra CLAUDE.md §6-nın use case naxışıdır: səlahiyyət → domen qaydası →
        yazma → audit. Audit SONDADIR və istisna UDMUR — uğursuz olarsa bütün
        əməliyyat geri qayıdır (tranzaksiya sərhədi çağıran sessiyadadır).
        """
        now = self._clock.now()
        if not actor.has_permission(EXPORT_CORRECTIONS_FLAG, now=now):
            _audit_log.warning(
                "EXPORT_CORRECTION_DENIED",
                extra={"actor_id": str(actor.id), "flag": EXPORT_CORRECTIONS_FLAG},
            )
            raise ExportCorrectionPermissionError(
                f"«{EXPORT_CORRECTIONS_FLAG}» səlahiyyəti yoxdur",
                context={"actor_id": str(actor.id)},
            )

        minimum = self._reason_min_length(tenant_id)
        cleaned = reason.strip()
        if len(cleaned) < minimum:
            # SÜKUTLA rədd YOXDUR: mesaj həm faktiki, həm tələb olunan uzunluğu
            # göstərir ki, HR nə edəcəyini bilsin (`ReportRangeTooLongError`
            # ilə eyni naxış).
            raise ExportCorrectionReasonError(
                f"Səbəb {len(cleaned)} simvoldur, minimum {minimum} tələb olunur",
                user_message=(
                    f"Səbəb ən azı {minimum} simvol olmalıdır — indi {len(cleaned)} simvoldur. "
                    f"Düzəlişin NİYƏ edildiyini yazın: səbəbsiz düzəliş auditdə dəyərsizdir."
                ),
                context={"length": len(cleaned), "minimum": minimum},
            )

        entry = ExportCorrection(
            tenant_id=tenant_id,
            export_type=export_type,
            employee_id=employee_id,
            target_date=target_date,
            field=field_code,
            old_value=old_value,
            new_value=new_value,
            reason=cleaned,
            corrected_by=actor.id,
            corrected_at=now,
        )
        self._corrections.save(entry)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="EXPORT_CORRECTION_RECORDED",
            entity_type="export_manual_corrections",
            entity_id=entry.correction_id,
            before_state={"field": entry.field, "value": entry.old_value},
            after_state={
                "field": entry.field,
                "value": entry.new_value,
                "employee_id": str(entry.employee_id),
                "target_date": entry.target_date.isoformat(),
                "export_type": entry.export_type,
            },
            reason=entry.reason,
        )
        return entry

    def list_corrections(
        self,
        *,
        tenant_id: TenantId,
        report_range: ReportRange,
        export_type: str = EXPORT_TYPE_ATTENDANCE,
    ) -> tuple[ExportCorrection, ...]:
        """Aralığın düzəlişləri — `review()`-dən AYRI oxu yolu.

        Kontroller düzəliş yazdıqdan SONRA siyahını yenidən oxumaq üçün bunu
        çağırır: tam `review()` daha bahalıdır (kadr sorğusu + doğrulama) və
        düzəliş cədvəlinin özünü göstərmək üçün lazım deyil.
        """
        return tuple(
            self._corrections.list_for_range(
                tenant_id,
                export_type=export_type,
                start=report_range.start,
                end=report_range.end,
            )
        )

    # ------------------------------- köməkçilər ------------------------------ #

    def _thresholds(self, tenant_id: TenantId) -> ExportValidationThresholds:
        """ROOT həddləri; port yoxdursa və ya dəyər mənasızdırsa fallback."""
        pct = FALLBACK_STORE_ABSENCE_PCT
        minimum = FALLBACK_STORE_MIN_EMPLOYEES
        if self._limits is not None:
            raw = self._limits.get_str(
                tenant_id,
                SystemLimitKey.EXPORT_STORE_ABSENCE_ANOMALY_PCT.value,
                str(FALLBACK_STORE_ABSENCE_PCT),
            )
            pct = _decimal_or(raw, FALLBACK_STORE_ABSENCE_PCT)
            minimum = self._limits.get_int(
                tenant_id,
                SystemLimitKey.EXPORT_STORE_ANOMALY_MIN_EMPLOYEES.value,
                FALLBACK_STORE_MIN_EMPLOYEES,
            )
        return ExportValidationThresholds(
            # `<= 0` dəyər HƏR mağazanı işarələyərdi — ROOT-dakı bir yazı səhvi
            # doğrulama ekranını yararsız edərdi (`work_norm._usable_cap` ilə
            # eyni müdafiə).
            store_absence_pct=pct if pct > 0 else FALLBACK_STORE_ABSENCE_PCT,
            store_min_employees=minimum if minimum > 0 else FALLBACK_STORE_MIN_EMPLOYEES,
        )

    def _significant_delta(self, tenant_id: TenantId) -> int:
        if self._limits is None:
            return FALLBACK_SIGNIFICANT_DELTA
        value = self._limits.get_int(
            tenant_id,
            SystemLimitKey.EXPORT_PERIOD_DELTA_SIGNIFICANT.value,
            FALLBACK_SIGNIFICANT_DELTA,
        )
        return value if value > 0 else FALLBACK_SIGNIFICANT_DELTA

    def _reason_min_length(self, tenant_id: TenantId) -> int:
        """Səbəbin minimum uzunluğu — DB döşəməsindən AŞAĞI düşə bilməz.

        Root dəyəri 3-ə salsa belə, `INSERT` DB CHECK-inə (>= 10) dəyib xəta
        verərdi və HR "səbəb yazdım, yenə qəbul etmir" vəziyyətində qalardı.
        Ona görə döşəmə burada da tətbiq olunur — iki qat eyni cavabı verir.
        """
        if self._limits is None:
            return FALLBACK_REASON_MIN_LENGTH
        value = self._limits.get_int(
            tenant_id,
            SystemLimitKey.EXPORT_CORRECTION_REASON_MIN_LENGTH.value,
            FALLBACK_REASON_MIN_LENGTH,
        )
        return max(value, FALLBACK_REASON_MIN_LENGTH)


# --------------------------------------------------------------------------- #
# Saf funksiyalar — Qt/baza TƏLƏB ETMİR, birbaşa test oluna bilir
# --------------------------------------------------------------------------- #


def filter_by_role(
    rows: Sequence[AttendanceRow],
    *,
    roster: Mapping[EmployeeId, EmployeeRosterStatus],
    role_code: str | None,
) -> list[AttendanceRow]:
    """Rol filtri (bənd G) — boş nəticə QANUNİDİR.

    `role_code` `None`/boş olduqda HEÇ NƏ süzülmür. Kadr sətri tapılmayan işçi
    (məs. sonradan silinmiş rol) filtr AKTİV olduqda SİYAHIDAN DÜŞÜR — əks
    halda "yalnız Satıcı" seçimi naməlum rollu adamları da gətirərdi və filtr
    öz vədini pozardı.
    """
    wanted = (role_code or "").strip().upper()
    if not wanted:
        return list(rows)
    return [
        row
        for row in rows
        if (entry := roster.get(row.employee_id)) is not None
        and entry.position_code.upper() == wanted
    ]


def apply_corrections(
    rows: Sequence[AttendanceRow], corrections: Iterable[ExportCorrection]
) -> list[AttendanceRow]:
    """Manual düzəlişləri export sətirlərinə tətbiq edir (bənd D).

    QAYDALAR:
      * yalnız ƏDƏDİ sahələr rəqəmi dəyişir; `QEYD` sətri sətirlərə TOXUNMUR
        (onun yeri Excel-in «Qeyd» sütunudur, bax `notes_for`);
      * eyni sahəyə bir neçə düzəliş varsa SONUNCU qalib gəlir — port
        müqaviləsi siyahını `corrected_at` üzrə artan sırada verir
        (`ExportCorrectionRepository.list_for_range` başlığı);
      * çevrilə bilməyən dəyər (məs. "iyirmi") SƏTRİ POZMUR: düzəliş tətbiq
        olunmur, sətir toxunulmamış qalır. Alternativ — istisna atmaq — bir
        səhv yazıya görə BÜTÜN export-u dayandırardı, halbuki düzəliş sətri
        auditdə onsuz da görünür.
      * mənfi nəticə tətbiq edilmir: `AttendanceRow.__post_init__` onu rədd
        edərdi və ekran çökərdi.
    """
    updates: dict[EmployeeId, dict[str, int]] = {}
    for correction in corrections:
        if not correction.is_numeric:
            continue
        value = _as_int(correction.new_value)
        if value is None or value < 0:
            continue
        updates.setdefault(correction.employee_id, {})[correction.field] = value

    if not updates:
        return list(rows)

    result: list[AttendanceRow] = []
    for row in rows:
        changes = updates.get(row.employee_id)
        if not changes:
            result.append(row)
            continue
        result.append(
            replace(
                row,
                norm_work_days=changes.get("NORMA_GUN", row.norm_work_days),
                actual_worked_days=changes.get("FAKTIKI_GUN", row.actual_worked_days),
                off_days=changes.get("OFF_DAY", row.off_days),
                unauthorized_absences=changes.get("ICAZESIZ_QAYIB", row.unauthorized_absences),
            )
        )
    return result


def notes_for(corrections: Iterable[ExportCorrection]) -> dict[EmployeeId, str]:
    """Excel-in «Qeyd» sütununun məzmunu (bənd E).

    HƏR düzəliş qeydə düşür — həm sərbəst `QEYD` sətri, həm də ədədi düzəlişin
    "nə nəyə çevrildi" xülasəsi. Səbəb: faylı açan mühasib rəqəmin niyə
    dəyişdiyini FAYLIN İÇİNDƏ görməlidir; onu yalnız ekranda göstərmək
    faylı e-poçtla alan adamı məlumatsız qoyardı.

    Bir işçinin bir neçə düzəlişi « | » ilə birləşdirilir: ayırıcı vergüldən
    fərqli seçilib, çünki səbəb mətnində vergül OLA BİLƏR və sərhəd itərdi.
    """
    grouped: dict[EmployeeId, list[str]] = {}
    for correction in corrections:
        grouped.setdefault(correction.employee_id, []).append(correction.summary_az())
    return {employee_id: " | ".join(parts) for employee_id, parts in grouped.items()}


def compare_periods(
    current: Sequence[AttendanceRow],
    previous: Sequence[AttendanceRow],
    *,
    significant_delta: int,
    has_baseline: bool = True,
) -> tuple[MetricDelta, ...]:
    """Dövr-üzrə müqayisə (bənd F) — BOŞ keçmiş dövr ÇÖKMÜR.

    `has_baseline=False` olduqda fərq HESABLANMIR və `delta_text_az()` «—»
    qaytarır: keçmiş dövrün məlumatı yoxdursa, "−12" göstərmək YALAN olardı
    (sistem həmin ay işləməyib ola bilər).

    Metriklər sabitdir və bu, rol siyahısı ilə ZİDD DEYİL: bunlar faylın
    SÜTUNLARIDIR (`ATTENDANCE_HEADERS`), məlumat sətirləri deyil.
    """
    metrics = (
        ("unauthorized_absences", "İcazəsiz qayıb"),
        ("actual_worked_days", "Faktiki işlənilən gün"),
        ("norm_work_days", "Norma iş günləri"),
        ("off_days", "Off-day sayı"),
    )
    deltas: list[MetricDelta] = []
    for key, label in metrics:
        current_total = sum(int(getattr(row, key)) for row in current)
        previous_total = sum(int(getattr(row, key)) for row in previous) if has_baseline else 0
        deltas.append(
            MetricDelta(
                metric_key=key,
                label_az=label,
                current=current_total,
                previous=previous_total,
                has_baseline=has_baseline,
                is_significant=(
                    has_baseline and abs(current_total - previous_total) >= significant_delta
                ),
            )
        )
    return tuple(deltas)


def correctable_field_options() -> tuple[tuple[str, str], ...]:
    """Düzəliş dialoqunun sahə seçimi — (kod, Azərbaycanca ad).

    Kataloq DOMENDƏDİR (`CORRECTABLE_FIELDS`); bu funksiya yalnız onu ekranın
    gözlədiyi cütlər formasına çevirir ki, təqdimat qatı domen sözlüyünün
    daxili quruluşunu (dəyər `tuple`-dur) bilməsin.
    """
    return tuple((code, label) for code, (label, _numeric) in CORRECTABLE_FIELDS.items())


def _to_facts(
    rows: Iterable[AttendanceRow], *, roster: Mapping[EmployeeId, EmployeeRosterStatus]
) -> tuple[ExportRowFacts, ...]:
    """`AttendanceRow` (tətbiq) → `ExportRowFacts` (domen) çevrilməsi.

    Kadr sətri tapılmayan işçi AKTİV sayılır: onu "deaktiv" saymaq hər plansız
    işçini yalançı xəbərdarlıqla işarələyərdi, halbuki həqiqi səbəb məlumatın
    ÇATIŞMAMASIdır və o, «0 gün / 0 qayıb» qaydası ilə onsuz da görünür.
    """
    facts: list[ExportRowFacts] = []
    for row in rows:
        entry = roster.get(row.employee_id)
        facts.append(
            ExportRowFacts(
                employee_id=row.employee_id,
                full_name=row.full_name,
                store_name=row.store_name,
                norm_work_days=row.norm_work_days,
                actual_worked_days=row.actual_worked_days,
                unauthorized_absences=row.unauthorized_absences,
                is_active=True if entry is None else entry.is_active,
            )
        )
    return tuple(facts)


def _role_options(roster: Iterable[EmployeeRosterStatus]) -> tuple[RoleOption, ...]:
    """Rol seçimləri — MÖVCUD kataloqdan, SABİT SİYAHIDAN YOX.

    Mənbə `positions` cədvəlidir (kadr sorğusunun `JOIN`-u). Boş rol kodu
    ATLANIR: rolu olmayan işçi filtr seçimi yarada bilməz.
    """
    seen: dict[str, str] = {}
    for entry in roster:
        code = entry.position_code.strip().upper()
        if not code:
            continue
        seen.setdefault(code, entry.position_name)
    return tuple(RoleOption(code=code, name_az=seen[code]) for code in sorted(seen))


def _as_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _decimal_or(raw: object, fallback: Decimal) -> Decimal:
    try:
        return Decimal(str(raw).strip().replace(",", "."))
    except (InvalidOperation, ValueError, AttributeError):
        return fallback


__all__ = [
    "EXPORT_CORRECTIONS_FLAG",
    "FALLBACK_REASON_MIN_LENGTH",
    "FALLBACK_SIGNIFICANT_DELTA",
    "FALLBACK_STORE_ABSENCE_PCT",
    "FALLBACK_STORE_MIN_EMPLOYEES",
    "EmployeeRosterStatus",
    "ExportCorrectionError",
    "ExportCorrectionPermissionError",
    "ExportCorrectionReasonError",
    "ExportPreflightReview",
    "ExportPreflightUseCase",
    "ExportRosterProvider",
    "MetricDelta",
    "RoleOption",
    "apply_corrections",
    "compare_periods",
    "correctable_field_options",
    "filter_by_role",
    "notes_for",
]
