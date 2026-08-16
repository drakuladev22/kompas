"""Növbə planlaması və dəyişmə sorğusu (spesifikasiya bölmə 3) — Faza 5.

──────────────────────────────────────────────────────────────────────────────
İKİ AXIN, BİR YENİLƏMƏ FUNKSİYASI
──────────────────────────────────────────────────────────────────────────────
Bölmə 3 açıq tələb qoyur: təsdiqlənmiş Shift Swap "avtomatik Shift Matrix-i
yeniləyir (yuxarıdakı admin-redaktə mexanizmi ilə **eyni yeniləmə
funksiyasından istifadə edərək — məntiq təkrarlanmır**)".

Ona görə `ShiftSwapUseCase` öz yazma məntiqini QURMUR — `ShiftPlanningUseCase`-i
asılılıq kimi alır və `apply_assignment()`-i çağırır. Bu, sadəcə "təmiz kod"
üstünlüyü deyil: iki ayrı yazma yolu olsaydı, biri konflikt yoxlamasını
edərdi, digəri etməzdi və hansının hansı olduğu yalnız problem çıxanda üzə
çıxardı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ HƏR DƏYİŞİKLİK LEAVE SORĞULARINI YENİDƏN QİYMƏTLƏNDİRİR
──────────────────────────────────────────────────────────────────────────────
Bölmə 3: "Manual shift dəyişikliyi mövcud Task Engine, Fine Management və
Timeout eskalasiya qaydaları ilə konflikt yaratmamalıdır — dəyişiklik anında
sistem həmin gün üçün aktiv/gözləyən leave sorğularını avtomatik yenidən
qiymətləndirir və lazım olduqda xəbərdarlıq göstərir."

Konkret təhlükə: işçinin BU GÜN açıq icazəsi (`🔵 Xaricdə`) var və admin həmin
günü istirahət gününə çevirir. O zaman gecikmə hesablamasının istinad nöqtəsi
(planlaşdırılmış başlanğıc) itir və cərimə səhv hesablana bilər. Biz dəyişikliyi
BLOKLAMIRIQ — admin öz işini bilir — amma xəbərdarlığı `ScheduleConflict`
kimi qaytarırıq və bildiriş göndəririk ki, qərar məlumatlı olsun.

──────────────────────────────────────────────────────────────────────────────
GÖRÜNMƏ SCOPİNQİ (bölmə 3, "CANLI GÖRÜNMƏ SCOPİNQİ")
──────────────────────────────────────────────────────────────────────────────
    İşçi (`Satıcı`)      → yalnız ÖZ təqvimi
    `Mağaza_Meneceri`    → yalnız öz filialı, YALNIZ-BAXIŞ (redaktə YOX)
    HR_Admin/Admin/CEO   → bütün şəbəkə, redaktə ilə

Redaktə hüququ `can_manage_shifts`-dədir; baxış hüququ isə rola görə
scoping-lə verilir. İkisini bir flag-ə bağlamaq olmazdı: işçinin öz növbəsini
görməsi üçün ona planlama səlahiyyəti vermək lazım gələrdi.

──────────────────────────────────────────────────────────────────────────────
#14 ƏMƏK QANUNU XƏBƏRDARLIĞI — NİYƏ YENİ KANAL YARADILMADI (Faza 6 əlavəsi)
──────────────────────────────────────────────────────────────────────────────
`ScheduleConflict` + `ShiftChangeResult.conflicts` ARTIQ mövcud xəbərdarlıq
kanalıdır və o, dəqiq bu məqsədlə qurulub: "BLOKLAYICI DEYİL — admin
dəyişikliyi yenə edə bilər" (bax `ScheduleConflict` docstring-i). #14-ün
tələbi eynidir, ona görə əmək qanunu pozuntuları YENİ mexanizmlə yox, HƏMİN
siyahıya ƏLAVƏ `kind` dəyərləri kimi gəlir (`LaborRuleKind.*`).

Bunun üç praktik nəticəsi var:

    1. Ekran tərəfi DƏYİŞMİR — `has_conflicts` və `conflicts` onsuz da
       göstərilir; yeni xəbərdarlıq növü avtomatik görünür.
    2. Audit izi DƏYİŞMİR — `after_state["conflicts"]` siyahısı artıq
       yazılırdı, indi əmək xəbərdarlıqları da oraya düşür, yəni "admin
       xəbərdarlıq edildi, buna baxmayaraq təyin etdi" faktı sübutludur.
    3. Faza 7 (#17 sənəd bloklaması) EYNİ kanalı təkrar istifadə edə bilər —
       kanal `kind` sətri ilə genişlənir, struktur dəyişikliyi tələb etmir.

Qayda MƏNTİQİ burada YAZILMIR: o, `domain/labor_rules.py`-dadır (saf, I/O-suz)
və məlumat yığımı `application/use_cases/labor_compliance.py`-da. Bu fayla
əlavə olunan yeganə şey `LaborComplianceAdvisor`-un İSTƏYƏ BAĞLI asılılığı və
onun nəticəsini mövcud siyahıya çevirən bir köməkçidir — mövcud təyinetmə
məntiqinin heç bir sətri dəyişmir.

──────────────────────────────────────────────────────────────────────────────
TƏSDİQLƏNMİŞ İLLİK MƏZUNİYYƏT — NİYƏ XƏBƏRDARLIQ, NİYƏ BLOKLAMA DEYİL
──────────────────────────────────────────────────────────────────────────────
`entities/annual_leave.py` başlığı qərarı açıq yazır: "Shift Matrix YALNIZ
OXUNUR — təsdiqlənmiş məzuniyyət növbə cədvəlini dəyişmir". Yəni matris
məzuniyyətdən XƏBƏRSİZ qalırdı və planlayıcı həmin günə iş günü təyin edə
bilirdi. Nəticə real zərərdir: işçi (haqlı olaraq) gəlmir, `detect_absences`
isə planlaşdırılmış iş gününü görüb "İcazəsiz Qayıb" yazır.

Boşluq bölmə 3-ün MÖVCUD tələbinin tam icrası ilə bağlanır — "dəyişiklik
anında sistem həmin gün üçün aktiv/gözləyən leave sorğularını avtomatik
yenidən qiymətləndirir və lazım olduqda xəbərdarlıq göstərir". Burada
qiymətləndirilən sorğu SİNFİ genişlənir (gündaxili icazə + illik məzuniyyət),
mexanizm isə eynidir: `ScheduleConflict`.

BLOKLAMA QƏSDƏN SEÇİLMƏDİ. Üç səbəb:
  1. Bu use case-də BÜTÜN qaydalar (icazə konflikti, #14 əmək qanunu, #17
     sənəd) məlumatlandırıcıdır — biri bloklasaydı, `ScheduleConflict`-in
     "BLOKLAYICI DEYİL" müqaviləsi ekranda yalan olardı.
  2. Fövqəladə hal real haldır: xəstələnmiş növbə üçün məzuniyyətdəki işçi
     ÖZ razılığı ilə çağırıla bilər. Sistem bunu fiziki qadağan etsəydi,
     planlayıcı təyinatı kağızda edərdi və matris HƏQİQƏTDƏN AYRILARDI —
     `domain/document_rules.py` başlığındakı eyni əsaslandırma.
  3. Xəbərdarlıq `after_state["conflicts"]`-ə düşür, yəni "xəbərdar edildi,
     buna baxmayaraq təyin etdi" faktı sübutlu qalır.

ƏKS İSTİQAMƏT BU FAYLDA DEYİL: "əvvəlcə növbə planlandı, SONRA məzuniyyət
təsdiqləndi" halında xəbərdar ediləcək şəxs ekran qarşısında deyil, ona görə
o, bildirişlə həll olunur — bax `annual_leave.py::_warn_planned_shifts`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING

from src.application.root_limits import fallback_int, limit_int
from src.domain.entities.shift import (
    ShiftAssignment,
    ShiftSource,
    ShiftSwapRequest,
    SwapStatus,
)
from src.domain.policies import FeatureModule, SystemLimitKey
from src.domain.value_objects.identifiers import (
    new_shift_assignment_id,
    new_shift_swap_request_id,
)
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.application.use_cases.document_compliance import DocumentComplianceAdvisor
    from src.application.use_cases.labor_compliance import LaborComplianceAdvisor
    from src.domain.document_rules import DocumentRuleFinding
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AnnualLeaveRequestRepository,
        AuditTrail,
        Clock,
        FeatureToggles,
        LeaveRequestRepository,
        Notifier,
        ShiftRepository,
        ShiftSwapRepository,
        SystemLimits,
    )
    from src.domain.labor_rules import LaborRuleFinding
    from src.domain.value_objects.identifiers import (
        EmployeeId,
        ShiftSwapRequestId,
        StoreId,
        TenantId,
        WorkModeId,
    )

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

MANAGE_SHIFTS_FLAG = "can_manage_shifts"
APPROVE_SWAP_FLAG = "can_approve_shift_swap"

#: `ScheduleConflict.kind` — təsdiqlənmiş illik məzuniyyət günü İŞ günü kimi
#: təyin edildi. `LaborRuleKind`/`DocumentRuleKind` ilə eyni üslub (SABİT sətir,
#: ekran süzgəci və audit `after_state["conflicts"]` bu dəyəri saxlayır), lakin
#: AYRI enum yaradılmır: burada YEGANƏ dəyər var və bir üzvlü enum oxunuşu
#: asanlaşdırmır, yalnız idxal zənciri uzadardı.
ANNUAL_LEAVE_CONFLICT_KIND = "APPROVED_ANNUAL_LEAVE_OVERLAP"

#: Sorğu neçə gün irəli üçün göndərilə bilər — keçmişə sorğu mənasızdır.
#:
#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`SystemLimitKey.SHIFT_SWAP_MAX_LEAD_DAYS`, seed: migrations/034). Pəncərənin
#: uzunluğu planlaşdırma üfüqü ilə bağlı BİZNES qərarıdır: rüblük qrafik quran
#: müəssisə 90 günü qısa, aylıq planlayan isə uzun sayır. Sinifdəki ədəd yalnız
#: ROOT sətri oxunmadıqda (port bağlanmayıb, baza əlçatmaz) işə düşür.
MAX_SWAP_LEAD_DAYS = fallback_int(SystemLimitKey.SHIFT_SWAP_MAX_LEAD_DAYS)


class ShiftPermissionError(KompasOSError):
    """Növbə planını dəyişdirmək səlahiyyəti yoxdur."""

    user_message = "Növbə planını dəyişdirmək səlahiyyətiniz yoxdur."


class ShiftRequestError(KompasOSError):
    """Növbə dəyişmə sorğusu yararsızdır."""

    user_message = "Bu sorğu göndərilə bilmədi."


class SwapNotFoundError(ShiftRequestError):
    user_message = "Sorğu tapılmadı."


@dataclass(frozen=True)
class ScheduleConflict:
    """Dəyişikliyin mövcud iş axınları ilə toqquşması (bölmə 3).

    BLOKLAYICI DEYİL — admin dəyişikliyi yenə edə bilər. Bu, məlumatlı qərar
    üçün xəbərdarlıqdır: susmaq daha pisdir, çünki nəticə cərimə hesabında
    üzə çıxardı.
    """

    employee_id: EmployeeId
    shift_date: date
    kind: str
    message_az: str


@dataclass
class ShiftChangeResult:
    """Bir günün dəyişdirilməsinin nəticəsi."""

    assignment: ShiftAssignment | None
    conflicts: list[ScheduleConflict] = field(default_factory=list)

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)


class ShiftPlanningUseCase:
    """Interactive Shift Matrix — admin-kontrollu növbə planlaması."""

    def __init__(
        self,
        *,
        shifts: ShiftRepository,
        leave_requests: LeaveRequestRepository,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier,
        labor: LaborComplianceAdvisor | None = None,
        documents: DocumentComplianceAdvisor | None = None,
        annual_leave: AnnualLeaveRequestRepository | None = None,
    ) -> None:
        """
        Args:
            labor: #14 əmək qanunu məsləhətçisi. İSTƏYƏ BAĞLIDIR və defolt
                `None`-dur — mövcud çağırış yerləri (Faza 5 testləri daxil)
                imzada heç nə dəyişmədən işləməyə davam edir. `None` olduqda
                xəbərdarlıq sadəcə üretilmir; təyinat AXINI DƏYİŞMİR, çünki
                bu qaydalar onsuz da bloklamır (fail-open — susan qayda
                admin-in işini dayandırmamalıdır).
            documents: #17 sənəd bloklama məsləhətçisi (Faza 7). EYNİ İSTƏYƏ
                BAĞLI naxış — `labor`-la eyni səbəb.
            annual_leave: #28 illik məzuniyyət sorğuları — YALNIZ OXUNUR
                (`find_overlapping_approved`). EYNİ İSTƏYƏ BAĞLI naxış.
                MƏSLƏHƏTÇİ SİNFİ (`LaborComplianceAdvisor` kimi) YARADILMADI
                VƏ BU, QƏSDLİDİR: məsləhətçi sinifləri qaydanın ÖZÜ qeyri-triv
                olduqda (saat hesablaması, bitmə tarixi süzgəci) mövcuddur.
                Burada qayda tək sualdan ibarətdir — "bu günü əhatə edən
                TƏSDİQLƏNMİŞ məzuniyyət varmı?" — və cavabı repository-nin
                mövcud metodu birbaşa verir. Ayrıca sinif yalnız bir ötürücü
                qat olardı; `_reassess_open_work` da eyni səbəbdən
                `LeaveRequestRepository`-ni BİRBAŞA işlədir.
        """
        self._shifts = shifts
        self._leave_requests = leave_requests
        self._audit = audit
        self._clock = clock
        self._notifier = notifier
        self._labor = labor
        self._documents = documents
        self._annual_leave = annual_leave

    # ------------------------------- baxış ----------------------------------- #

    def view_matrix(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        start: date,
        end: date,
        store_id: StoreId | None = None,
    ) -> list[ShiftAssignment]:
        """Təqvim görünüşü — SCOPİNQ tətbiq olunur (bölmə 3).

        Səlahiyyət yoxlaması burada YOXDUR, scoping var: hər kəs nəyisə görür,
        sadəcə hərə öz dairəsini. `can_manage_shifts` yalnız REDAKTƏ üçündür.
        """
        if end < start:
            raise ShiftRequestError(
                "Bitmə tarixi başlanğıcdan əvvəl ola bilməz",
                user_message="Tarix aralığı düzgün deyil.",
            )

        now = self._clock.now()
        if actor.has_permission(MANAGE_SHIFTS_FLAG, now=now):
            # Planlayıcı bütün şəbəkəni görür (istəyə görə mağazaya süzülmüş).
            return self._shifts.list_range(tenant_id, start=start, end=end, store_id=store_id)

        if actor.has_permission("can_fill_daily_attendance", now=now):
            # Store Manager — yalnız öz filialı, yalnız-baxış.
            return self._shifts.list_range(tenant_id, start=start, end=end, store_id=actor.store_id)

        # Satıcı və digər personel — yalnız öz təqvimi.
        return self._shifts.list_range(tenant_id, start=start, end=end, employee_ids=[actor.id])

    # ------------------------------ redaktə ---------------------------------- #

    def assign_work_day(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        employee_id: EmployeeId,
        shift_date: date,
        work_mode_id: WorkModeId,
    ) -> ShiftChangeResult:
        """İş günü təyin edir (İş Rejimi şablonu ilə)."""
        self._require_manage(actor)
        return self.apply_assignment(
            tenant_id=tenant_id,
            actor_id=actor.id,
            employee_id=employee_id,
            shift_date=shift_date,
            is_off_day=False,
            work_mode_id=work_mode_id,
            source=ShiftSource.ADMIN_MATRIX,
        )

    def assign_off_day(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        employee_id: EmployeeId,
        shift_date: date,
    ) -> ShiftChangeResult:
        """İstirahət günü (off-day) təyin edir."""
        self._require_manage(actor)
        return self.apply_assignment(
            tenant_id=tenant_id,
            actor_id=actor.id,
            employee_id=employee_id,
            shift_date=shift_date,
            is_off_day=True,
            work_mode_id=None,
            source=ShiftSource.ADMIN_MATRIX,
        )

    def clear_day(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        employee_id: EmployeeId,
        shift_date: date,
    ) -> ShiftChangeResult:
        """Planı tamamilə silir — gün "planlaşdırılmamış" olur.

        DİQQƏT: planlaşdırılmamış gün istirahət günü DEYİL. `is_off_day()`
        `False` qaytarır, yəni həmin gün üçün check-in olmasa "İcazəsiz Qayıb"
        yazılacaq. Bu, `PostgresShiftRepository.is_off_day` şərhindəki qəsdli
        seçimdir və burada təkrarlanır ki, ekranda xəbərdarlıq göstərilə bilsin.
        """
        self._require_manage(actor)
        previous = self._shifts.get_assignment(employee_id, shift_date)
        self._shifts.clear_assignment(employee_id, shift_date)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="SHIFT_CLEARED",
            entity_type="shift_assignments",
            entity_id=None,
            before_state=previous.to_audit_state() if previous else None,
            after_state={
                "employee_id": str(employee_id),
                "shift_date": shift_date.isoformat(),
                "planned": False,
            },
        )
        return ShiftChangeResult(assignment=None, conflicts=[])

    def assign_week(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        employee_id: EmployeeId,
        week_start: date,
        work_mode_id: WorkModeId,
        off_day_weekdays: frozenset[int] = frozenset(),
    ) -> list[ShiftChangeResult]:
        """Bütün həftəni bir şablonla planlaşdırır (bölmə 3).

        Args:
            off_day_weekdays: `date.weekday()` dəyərləri (0 = Bazar ertəsi).
        """
        self._require_manage(actor)
        results: list[ShiftChangeResult] = []
        for offset in range(7):
            day = week_start + timedelta(days=offset)
            if day.weekday() in off_day_weekdays:
                results.append(
                    self.assign_off_day(
                        tenant_id=tenant_id,
                        actor=actor,
                        employee_id=employee_id,
                        shift_date=day,
                    )
                )
            else:
                results.append(
                    self.assign_work_day(
                        tenant_id=tenant_id,
                        actor=actor,
                        employee_id=employee_id,
                        shift_date=day,
                        work_mode_id=work_mode_id,
                    )
                )
        return results

    # ------------------------- ORTAQ YENİLƏMƏ FUNKSİYASI --------------------- #

    def apply_assignment(
        self,
        *,
        tenant_id: TenantId,
        actor_id: EmployeeId,
        employee_id: EmployeeId,
        shift_date: date,
        is_off_day: bool,
        work_mode_id: WorkModeId | None,
        source: ShiftSource,
    ) -> ShiftChangeResult:
        """Shift Matrix-in YEGANƏ yazma nöqtəsi.

        Həm admin redaktəsi, həm təsdiqlənmiş Shift Swap bura gəlir (modul
        başlığına bax) — bölmə 3 "məntiq təkrarlanmır" tələbinin icrası budur.

        PUBLIC olması qəsdəndir: `ShiftSwapUseCase` onu çağırır. Səlahiyyət
        yoxlaması BURADA DEYİL, çağıranlardadır — swap axınında yoxlanılan
        flag `can_approve_shift_swap`-dır, `can_manage_shifts` deyil. Ona görə
        bu metodu birbaşa çağıran hər kəs əvvəlcə ÖZ qapısını yoxlamalıdır.
        """
        previous = self._shifts.get_assignment(employee_id, shift_date)
        assignment = ShiftAssignment(
            assignment_id=(
                previous.assignment_id if previous is not None else new_shift_assignment_id()
            ),
            tenant_id=tenant_id,
            employee_id=employee_id,
            shift_date=shift_date,
            is_off_day=is_off_day,
            work_mode_id=work_mode_id,
            assigned_by=actor_id,
            source=source,
        )
        self._shifts.save_assignment(assignment)

        conflicts = self._reassess_open_work(
            tenant_id=tenant_id,
            employee_id=employee_id,
            shift_date=shift_date,
            is_off_day=is_off_day,
        )
        # #14: əmək qanunu xəbərdarlıqları MÖVCUD siyahıya qoşulur (bax modul
        # başlığı). Auditdən ƏVVƏL əlavə olunur ki, `after_state["conflicts"]`
        # admin-in nə ilə xəbərdar edildiyini tam göstərsin.
        conflicts.extend(
            self._labor_conflicts(
                tenant_id=tenant_id,
                employee_id=employee_id,
                shift_date=shift_date,
                is_off_day=is_off_day,
                work_mode_id=work_mode_id,
            )
        )
        # #17: bloklayıcı sənəd bitibsə xəbərdarlıq — EYNİ kanal, EYNİ yer
        # (auditdən ƏVVƏL, `_labor_conflicts` ilə eyni əsaslandırma). BLOKLAMIR
        # (bax `document_compliance.py` başlığı) — son qərar admindədir.
        conflicts.extend(
            self._document_conflicts(
                tenant_id=tenant_id, employee_id=employee_id, shift_date=shift_date
            )
        )
        # #28: təsdiqlənmiş illik məzuniyyət günü — EYNİ kanal, EYNİ yer
        # (auditdən ƏVVƏL). Bax modul başlığı: "TƏSDİQLƏNMİŞ İLLİK MƏZUNİYYƏT".
        conflicts.extend(
            self._annual_leave_conflicts(
                tenant_id=tenant_id,
                employee_id=employee_id,
                shift_date=shift_date,
                is_off_day=is_off_day,
            )
        )

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="SHIFT_ASSIGNED",
            entity_type="shift_assignments",
            entity_id=assignment.assignment_id,
            before_state=previous.to_audit_state() if previous else None,
            after_state={
                **assignment.to_audit_state(),
                "employee_id": str(employee_id),
                "conflicts": [conflict.kind for conflict in conflicts],
            },
        )
        return ShiftChangeResult(assignment=assignment, conflicts=conflicts)

    def _reassess_open_work(
        self,
        *,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        shift_date: date,
        is_off_day: bool,
    ) -> list[ScheduleConflict]:
        """Həmin gün üçün açıq icazə sorğularını yenidən qiymətləndirir."""
        conflicts: list[ScheduleConflict] = []
        open_request = self._leave_requests.find_open_for_employee(employee_id)

        if (
            is_off_day
            and open_request is not None
            and open_request.requested_time.date() == shift_date
        ):
            conflicts.append(
                ScheduleConflict(
                    employee_id=employee_id,
                    shift_date=shift_date,
                    kind="OPEN_LEAVE_ON_OFF_DAY",
                    message_az=(
                        "Bu işçinin həmin gün üçün açıq icazə sorğusu var. Günü "
                        "istirahət kimi işarələmək gecikmə hesablamasının istinad "
                        "nöqtəsini itirir — sorğunu əvvəlcə bağlamaq tövsiyə olunur."
                    ),
                )
            )

        for conflict in conflicts:
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=None,
                category="SHIFT_CHANGE_CONFLICT",
                title_az="Növbə dəyişikliyi konflikt yaradır",
                body_az=conflict.message_az,
                is_critical=False,
            )
        return conflicts

    def _labor_conflicts(
        self,
        *,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        shift_date: date,
        is_off_day: bool,
        work_mode_id: WorkModeId | None,
    ) -> list[ScheduleConflict]:
        """#14 — əmək qanunu xəbərdarlıqlarını `ScheduleConflict`-ə çevirir.

        BİLDİRİŞ GÖNDƏRİLMİR (icazə konfliktindən fərqli olaraq): bu
        xəbərdarlıq məhz həmin an ekran qarşısında dayanan admin üçündür və
        onu bir də e-poçtla təkrarlamaq bildiriş kanalını hər növbə
        redaktəsində doldurardı. İcazə konflikti isə ÜÇÜNCÜ tərəfi (icazəni
        təsdiqləyəcək operatoru) maraqlandırır — ona görə orada bildiriş var,
        burada yox.

        MƏSLƏHƏTÇİ QOŞULMAYIBSA BOŞ SİYAHI: bax konstruktor şərhi (fail-open).
        """
        if self._labor is None:
            return []

        findings: list[LaborRuleFinding] = self._labor.review(
            tenant_id=tenant_id,
            employee_id=employee_id,
            shift_date=shift_date,
            is_off_day=is_off_day,
            work_mode_id=work_mode_id,
        )
        return [
            ScheduleConflict(
                employee_id=employee_id,
                shift_date=finding.shift_date,
                kind=finding.kind.value,
                message_az=finding.message_az,
            )
            for finding in findings
        ]

    def _document_conflicts(
        self, *, tenant_id: TenantId, employee_id: EmployeeId, shift_date: date
    ) -> list[ScheduleConflict]:
        """#17 — bloklayıcı sənəd xəbərdarlıqlarını `ScheduleConflict`-ə çevirir.

        `shift_date` YALNIZ YARLIQLAMA üçündür (bu konfliktin HANSI təyinatla
        birlikdə göstərildiyi) — qaydanın ÖZÜ isə `document_compliance.py`
        başlığında izah edildiyi kimi HAZIRKI günə (`Clock.now().date()`)
        istinad edir, `shift_date`-ə deyil.

        BİLDİRİŞ GÖNDƏRİLMİR: `_labor_conflicts`-lə EYNİ səbəb — bu, ekran
        qarşısında dayanan admin üçündür, üçüncü tərəf üçün deyil (sənədin
        bitmə xəbərdarlığı ARTIQ `notify_expiring_documents` gecəlik işi ilə
        gedir, bax `employee_documents.py`).

        MƏSLƏHƏTÇİ QOŞULMAYIBSA BOŞ SİYAHI: bax konstruktor şərhi (fail-open).
        """
        if self._documents is None:
            return []

        findings: list[DocumentRuleFinding] = self._documents.review(
            tenant_id=tenant_id, employee_id=employee_id
        )
        return [
            ScheduleConflict(
                employee_id=employee_id,
                shift_date=shift_date,
                kind=finding.kind.value,
                message_az=finding.message_az,
            )
            for finding in findings
        ]

    def _annual_leave_conflicts(
        self,
        *,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        shift_date: date,
        is_off_day: bool,
    ) -> list[ScheduleConflict]:
        """#28 — təsdiqlənmiş illik məzuniyyət günü İŞ günü kimi təyin edildi.

        YALNIZ İŞ GÜNÜ XƏBƏRDARLIQ DOĞURUR (`is_off_day=True` halında siyahı
        boşdur). Səbəb: məzuniyyət gününü matrisdə istirahət kimi işarələmək
        planlayıcının DOĞRU reaksiyasıdır — orada xəbərdarlıq göstərmək
        adamı düzgün əməliyyata görə "cəzalandırardı" və xəbərdarlıq kanalını
        səs-küyə çevirərdi. Zərər YALNIZ iş günü təyinatındadır: matris o günü
        gözləyir, işçi qanuni olaraq gəlmir, `detect_absences` isə
        `is_off_day` sorğusundan `False` alıb "İcazəsiz Qayıb" yazır.

        BİLDİRİŞ GÖNDƏRİLMİR: `_labor_conflicts`/`_document_conflicts` ilə
        EYNİ səbəb — bu, məhz həmin an ekran qarşısında dayanan planlayıcı
        üçündür. İşçinin ÖZÜNƏ də göndərilmir: təyinat onun məzuniyyətini
        NƏ LƏĞV EDİR, NƏ QISALDIR (`annual_leave_requests` sətrinə
        toxunulmur), yəni ona çatdırılacaq bir qərar yoxdur — çağırış qərarı
        verilərsə, o, insan tərəfindən ayrıca danışılır.

        REPOSITORY QOŞULMAYIBSA BOŞ SİYAHI: `labor`/`documents` ilə eyni
        fail-open (bax konstruktor şərhi).
        """
        if self._annual_leave is None or is_off_day:
            return []

        # Tək günlük aralıq: `find_overlapping_approved` `daterange(...,'[]')`
        # kəsişməsi ilə işləyir, yəni `start == end == shift_date` sorğusu
        # "bu günü əhatə edən təsdiqlənmiş məzuniyyət" deməkdir. Ayrıca
        # "gün üçün" metod ƏLAVƏ EDİLMƏDİ — port-a ikinci, demək olar eyni
        # sorğu qoymaq iki fərqli kəsişmə tərifinin yaranma riskidir.
        approved = self._annual_leave.find_overlapping_approved(
            employee_id, start=shift_date, end=shift_date
        )
        if approved is None:
            return []

        _audit_log.warning(
            "SHIFT_ASSIGNED_DURING_ANNUAL_LEAVE",
            extra={
                "tenant_id": str(tenant_id),
                "employee_id": str(employee_id),
                "shift_date": shift_date.isoformat(),
                "request_id": str(approved.id),
            },
        )
        return [
            ScheduleConflict(
                employee_id=employee_id,
                shift_date=shift_date,
                kind=ANNUAL_LEAVE_CONFLICT_KIND,
                message_az=(
                    "Bu işçinin həmin gün TƏSDİQLƏNMİŞ illik məzuniyyəti var "
                    f"({approved.start_date.isoformat()} – {approved.end_date.isoformat()}). "
                    "Təyinat bloklanmadı — qərar sizindir; lakin işçi gəlməzsə "
                    "həmin gün «İcazəsiz Qayıb» kimi yazılacaq. Ya günü istirahət "
                    "kimi işarələyin, ya da məzuniyyəti ləğv edin."
                ),
            )
        ]

    def _require_manage(self, actor: Employee) -> None:
        if not actor.has_permission(MANAGE_SHIFTS_FLAG, now=self._clock.now()):
            _audit_log.warning(
                "SHIFT_PERMISSION_DENIED",
                extra={"actor_id": str(actor.id), "flag": MANAGE_SHIFTS_FLAG},
            )
            raise ShiftPermissionError(
                f"«{MANAGE_SHIFTS_FLAG}» səlahiyyəti yoxdur",
                context={"actor_id": str(actor.id)},
            )


class ShiftSwapUseCase:
    """Növbə Dəyişmə Sorğusu — işçi-tərəfi self-service (bölmə 3)."""

    def __init__(
        self,
        *,
        swaps: ShiftSwapRepository,
        planning: ShiftPlanningUseCase,
        toggles: FeatureToggles,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier,
        limits: SystemLimits | None = None,
    ) -> None:
        """
        Args:
            limits: ROOT parametrlərinə (`SHIFT_SWAP_MAX_LEAD_DAYS`) açılan
                pəncərə. İSTƏYƏ BAĞLIDIR və defolt `None`-dur — `labor`/
                `documents` məsləhətçiləri ilə eyni naxış (bax
                `ShiftPlanningUseCase.__init__`): mövcud qurulma nöqtələri
                imzada heç nə dəyişmədən işləməyə davam edir və `None` halında
                davranış köçürmədən ƏVVƏLKİ ilə HƏRFƏN eynidir (fallback
                `DEFAULT_LIMITS`-dən gəlir).
        """
        self._swaps = swaps
        self._planning = planning
        self._toggles = toggles
        self._audit = audit
        self._clock = clock
        self._notifier = notifier
        self._limits = limits

    # ------------------------------- göndər ---------------------------------- #

    def submit(
        self,
        *,
        tenant_id: TenantId,
        employee: Employee,
        target_date: date,
        reason: str,
        requested_mode_id: WorkModeId | None = None,
    ) -> ShiftSwapRequest:
        """İşçi Ana Ekranından `[Növbə Dəyişmə Sorğusu]`.

        Təqvimə TOXUNULMUR — status `PENDING_APPROVAL` olur və işçi öz
        standart növbəsinə çıxmağa məcburdur (bölmə 3).
        """
        self._require_module(tenant_id)
        now = self._clock.now()

        if target_date < now.date():
            raise ShiftRequestError(
                "Keçmiş tarix üçün sorğu göndərilə bilməz",
                user_message="Keçmiş tarixə sorğu göndərmək olmaz.",
                context={"target_date": target_date.isoformat()},
            )
        # ÇAĞIRIŞ ANINDA oxunur: Root pəncərəni dəyişən kimi növbəti sorğu yeni
        # hədlə yoxlanmalıdır — proses yenidən başladılması tələb etmək
        # parametri faktiki olaraq buraxılışa bağlayardı.
        max_lead_days = limit_int(self._limits, tenant_id, SystemLimitKey.SHIFT_SWAP_MAX_LEAD_DAYS)
        if (target_date - now.date()).days > max_lead_days:
            raise ShiftRequestError(
                f"Sorğu ən çox {max_lead_days} gün irəli üçün göndərilə bilər",
                user_message=f"Ən çox {max_lead_days} gün irəli üçün sorğu göndərin.",
                context={"target_date": target_date.isoformat()},
            )
        if self._swaps.find_open_for_date(employee.id, target_date) is not None:
            raise ShiftRequestError(
                "Bu tarix üçün artıq gözləyən sorğunuz var",
                user_message="Bu tarix üçün artıq bir sorğunuz təsdiq gözləyir.",
                context={"target_date": target_date.isoformat()},
            )

        request = ShiftSwapRequest(
            request_id=new_shift_swap_request_id(),
            tenant_id=tenant_id,
            employee_id=employee.id,
            store_id=employee.store_id,
            target_date=target_date,
            requested_mode_id=requested_mode_id,
            reason=reason,
            created_at=now,
        )
        self._swaps.save(request)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=employee.id,
            action="SHIFT_SWAP_REQUESTED",
            entity_type="shift_swap_requests",
            entity_id=request.id,
            after_state={
                "target_date": target_date.isoformat(),
                "status": request.status.value,
            },
            reason=request.reason,
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=None,  # `can_approve_shift_swap` sahibləri
            category="SHIFT_SWAP_PENDING",
            title_az="Yeni növbə dəyişmə sorğusu",
            body_az=(
                f"{target_date.isoformat()} tarixi üçün növbə dəyişmə sorğusu "
                f"təsdiq gözləyir. Səbəb: {request.reason}"
            ),
            is_critical=False,
        )
        return request

    # ------------------------------- inbox ----------------------------------- #

    def pending_inbox(
        self, *, tenant_id: TenantId, actor: Employee, store_id: StoreId | None = None
    ) -> list[ShiftSwapRequest]:
        """`can_approve_shift_swap` sahibinin təsdiq növbəsi."""
        self._require_approver(actor)
        return self._swaps.list_pending(tenant_id, store_id=store_id)

    def my_requests(self, employee: Employee) -> list[ShiftSwapRequest]:
        """İşçinin öz sorğu tarixçəsi — səlahiyyət tələb olunmur.

        SƏHİFƏ ÖLÇÜSÜ ROOT-DANDIR: əvvəl repozitoriya metodunun defolt
        arqumenti (`limit: int = 50`) qüvvədə idi və bura ötürülmürdü — yəni
        50-dən çox sorğusu olan işçi tarixçəsinin qalanını heç bir yolla görə
        bilmirdi və bunun bir limitdən qaynaqlandığını da bilmirdi (DB-2
        hardcode auditi). Dəyər dəyişmir (50), sadəcə görünən yerə keçir.
        """
        page_size = limit_int(
            self._limits, employee.tenant_id, SystemLimitKey.SHIFT_SWAP_HISTORY_PAGE_SIZE
        )
        return self._swaps.list_for_employee(employee.id, limit=page_size)

    # ---------------------------- menecer qeydi ------------------------------ #

    def add_manager_note(
        self,
        *,
        tenant_id: TenantId,
        manager: Employee,
        request_id: ShiftSwapRequestId,
        note: str,
    ) -> ShiftSwapRequest:
        """Store Manager-in tövsiyəsi — TƏSDİQ DEYİL (bölmə 3).

        Səlahiyyət olaraq `can_fill_daily_attendance` yoxlanılır: bu, Store
        Manager-in öz mağazasına aid olduğunu göstərən mövcud flag-dir və
        ona təsdiq hüququ VERMİR.
        """
        request = self._require_request(request_id)
        if not manager.has_permission("can_fill_daily_attendance", now=self._clock.now()):
            raise ShiftPermissionError(
                "Menecer qeydi üçün səlahiyyət yoxdur",
                user_message="Bu sorğuya qeyd əlavə etmək səlahiyyətiniz yoxdur.",
                context={"actor_id": str(manager.id)},
            )

        request.attach_manager_note(manager_id=manager.id, note=note)
        self._swaps.save(request)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=manager.id,
            action="SHIFT_SWAP_MANAGER_NOTE",
            entity_type="shift_swap_requests",
            entity_id=request.id,
            after_state={"manager_note": request.manager_note},
        )
        return request

    # -------------------------------- qərar ---------------------------------- #

    def approve(
        self,
        *,
        tenant_id: TenantId,
        approver: Employee,
        request_id: ShiftSwapRequestId,
    ) -> ShiftChangeResult:
        """`[Təsdiqlə]` — Shift Matrix EYNİ funksiya ilə yenilənir."""
        self._require_approver(approver)
        request = self._require_request(request_id)
        now = self._clock.now()

        request.approve(approver_id=approver.id, decided_at=now)
        self._swaps.save(request)

        # Bölmə 3: təsdiqdən sonra təqvim yenilənir. Sorğuda iş rejimi
        # göstərilməyibsə bu, "həmin gün işləmək istəmirəm" deməkdir → off-day.
        if request.requested_mode_id is None:
            change = self._planning.apply_assignment(
                tenant_id=tenant_id,
                actor_id=approver.id,
                employee_id=request.employee_id,
                shift_date=request.target_date,
                is_off_day=True,
                work_mode_id=None,
                source=ShiftSource.SHIFT_SWAP,
            )
        else:
            change = self._planning.apply_assignment(
                tenant_id=tenant_id,
                actor_id=approver.id,
                employee_id=request.employee_id,
                shift_date=request.target_date,
                is_off_day=False,
                work_mode_id=request.requested_mode_id,
                source=ShiftSource.SHIFT_SWAP,
            )

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=approver.id,
            action="SHIFT_SWAP_APPROVED",
            entity_type="shift_swap_requests",
            entity_id=request.id,
            after_state={
                "status": request.status.value,
                "target_date": request.target_date.isoformat(),
            },
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=request.employee_id,
            category="SHIFT_SWAP_DECIDED",
            title_az="Növbə dəyişmə sorğunuz təsdiqləndi",
            body_az=f"{request.target_date.isoformat()} tarixi üçün sorğunuz təsdiqləndi.",
            is_critical=False,
        )
        return change

    def reject(
        self,
        *,
        tenant_id: TenantId,
        approver: Employee,
        request_id: ShiftSwapRequestId,
        reason: str,
    ) -> ShiftSwapRequest:
        """`[Rədd Et]` — işçiyə SƏBƏBLƏ bildiriş gedir (bölmə 3)."""
        self._require_approver(approver)
        request = self._require_request(request_id)

        request.reject(approver_id=approver.id, decided_at=self._clock.now(), reason=reason)
        self._swaps.save(request)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=approver.id,
            action="SHIFT_SWAP_REJECTED",
            entity_type="shift_swap_requests",
            entity_id=request.id,
            after_state={"status": request.status.value},
            reason=request.decision_reason,
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=request.employee_id,
            category="SHIFT_SWAP_DECIDED",
            title_az="Növbə dəyişmə sorğunuz rədd edildi",
            body_az=(
                f"{request.target_date.isoformat()} tarixi üçün sorğunuz rədd edildi. "
                f"Səbəb: {request.decision_reason}"
            ),
            # E-poçt fallback-ı ilə göndərilir: işçi tətbiqi açmaya bilər,
            # amma həmin gün işə çıxmalı olduğunu MÜTLƏQ bilməlidir.
            is_critical=True,
        )
        return request

    # ------------------------------- köməkçi --------------------------------- #

    def _require_request(self, request_id: ShiftSwapRequestId) -> ShiftSwapRequest:
        request = self._swaps.get(request_id)
        if request is None:
            raise SwapNotFoundError(
                "Növbə dəyişmə sorğusu tapılmadı",
                context={"request_id": str(request_id)},
            )
        return request

    def _require_approver(self, actor: Employee) -> None:
        if not actor.has_permission(APPROVE_SWAP_FLAG, now=self._clock.now()):
            _audit_log.warning(
                "SWAP_PERMISSION_DENIED",
                extra={"actor_id": str(actor.id), "flag": APPROVE_SWAP_FLAG},
            )
            raise ShiftPermissionError(
                f"«{APPROVE_SWAP_FLAG}» səlahiyyəti yoxdur",
                user_message="Növbə dəyişmə sorğusuna qərar vermək səlahiyyətiniz yoxdur.",
                context={"actor_id": str(actor.id)},
            )

    def _require_module(self, tenant_id: TenantId) -> None:
        """Feature Toggle: `SHIFT_SWAP` söndürülübsə yeni sorğu yaranmır.

        Bölmə 3 RETROAKTİV TƏSİR QAYDASI: mövcud gözləyən sorğular öz axınını
        normal tamamlayır — ona görə yoxlama YALNIZ `submit()`-dədir,
        `approve()`/`reject()`-də YOXDUR.
        """
        if not self._toggles.is_enabled(tenant_id, FeatureModule.SHIFT_SWAP.value):
            raise ShiftRequestError(
                "SHIFT_SWAP modulu deaktiv edilib",
                user_message="Növbə dəyişmə modulu hazırda aktiv deyil.",
                context={"module": FeatureModule.SHIFT_SWAP.value},
            )


__all__ = [
    "ANNUAL_LEAVE_CONFLICT_KIND",
    "APPROVE_SWAP_FLAG",
    "MANAGE_SHIFTS_FLAG",
    "MAX_SWAP_LEAD_DAYS",
    "ScheduleConflict",
    "ShiftChangeResult",
    "ShiftPermissionError",
    "ShiftPlanningUseCase",
    "ShiftRequestError",
    "ShiftSwapUseCase",
    "SwapNotFoundError",
    "SwapStatus",
]
