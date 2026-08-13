"""Əmək qanunu xəbərdarlığının MƏLUMAT YIĞIMI (#14, Faza 6).

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI SİNİF — `ShiftPlanningUseCase` NİYƏ ÖZÜ YIĞMIR
──────────────────────────────────────────────────────────────────────────────
`ShiftPlanningUseCase` Shift Matrix-in YEGANƏ yazma nöqtəsidir və Faza 5-dən
bəri işləyir. kompasos11.md Faza 6-nın qırmızı xətti odur ki, həmin əsas
təyinetmə məntiqi SİLİNMİR, YENİDƏN YAZILMIR, REFAKTOR EDİLMİR — yalnız əlavə
olunur. Ona görə #14-ün bütün yeni kodu BURADA yaşayır və planlama use
case-inə YALNIZ bir sətir (`self._labor.review(...)`) ilə qoşulur:

    * asılılıq İSTƏYƏ BAĞLIDIR (`labor: LaborComplianceAdvisor | None = None`),
      yəni mövcud çağırış yerləri və testlər imzada heç nə dəyişmədən işləyir;
    * qoşulmayıb → `apply_assignment` əvvəlki kimi davranır, xəbərdarlıq
      sadəcə olmur (fail-open — bu, BLOKLAMAYAN xəbərdarlıq üçün doğru
      yöndür: susan qayda təyinatı dayandırmamalıdır).

──────────────────────────────────────────────────────────────────────────────
NİYƏ PƏNCƏRƏ `max_consecutive_work_days`-DƏN GENİŞDİR
──────────────────────────────────────────────────────────────────────────────
Ardıcıl iş günü sayğacı yalnız GÖRDÜYÜ günləri saya bilir. Pəncərə həddə
bərabər olsaydı, sayğac heç vaxt həddi KEÇƏ bilməzdi və qayda praktik olaraq
susardı. Ona görə hər iki tərəfə `hədd + 1` gün götürülür: bu, "hədd
aşıldı" halını görməyə TAM YETƏRLİ minimum genişlikdir və 21 filiallıq
bazada da bir işçi üçün ~15 sətirlik oxu deməkdir.

──────────────────────────────────────────────────────────────────────────────
İŞ REJİMİ KEŞİ BİR ÇAĞIRIŞ ÜÇÜNDÜR
──────────────────────────────────────────────────────────────────────────────
Pəncərədəki 15 günün çoxu EYNİ iş rejiminə istinad edir; keşsiz oxu 15 ayrı
`work_modes.get()` sorğusu yaradardı. Keş metodun ÖMRÜ qədər yaşayır — sinifdə
saxlanılsaydı, Root iş rejiminin saatını dəyişdikdən sonra açıq qalmış panel
köhnə saatla xəbərdarlıq verərdi (kontroller sessiya saxlamır naxışı ilə eyni
səbəb, CLAUDE.md §6).
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Final

from src.domain.labor_rules import (
    LaborLimits,
    PlannedShift,
    evaluate_labor_rules,
)
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey

if TYPE_CHECKING:
    from datetime import date

    from src.domain.interfaces.ports import ShiftRepository, SystemLimits, WorkModeRepository
    from src.domain.labor_rules import LaborRuleFinding
    from src.domain.value_objects.catalogs import WorkMode
    from src.domain.value_objects.identifiers import EmployeeId, TenantId, WorkModeId
    from src.domain.value_objects.scheduling import TimeRange

#: Fallback dəyərlər — bax `policies.py`-dakı `SystemLimitKey.LABOR_*` şərhləri.
#: HƏQİQİ MƏNBƏ `system_limits`-dir (migrations/025 seed edir).
_FALLBACK_MIN_REST_HOURS: Final = int(DEFAULT_LIMITS[SystemLimitKey.LABOR_MIN_REST_HOURS])
_FALLBACK_BREAK_MINUTES: Final = int(DEFAULT_LIMITS[SystemLimitKey.LABOR_MANDATORY_BREAK_MINUTES])
_FALLBACK_BREAK_AFTER_HOURS: Final = int(
    DEFAULT_LIMITS[SystemLimitKey.LABOR_BREAK_REQUIRED_AFTER_HOURS]
)
_FALLBACK_MAX_CONSECUTIVE_DAYS: Final = int(
    DEFAULT_LIMITS[SystemLimitKey.LABOR_MAX_CONSECUTIVE_WORK_DAYS]
)

#: Pəncərəyə əlavə edilən ehtiyat gün (bax modul başlığı).
_WINDOW_MARGIN_DAYS: Final = 1


class LaborComplianceAdvisor:
    """Bir təyinatın ətrafındakı planı yığıb saf qaydalara verir.

    YAZMIR: nə repository-yə, nə audit-ə toxunur. Səbəb — xəbərdarlıq
    təyinatın NƏTİCƏSİ deyil, ONUN HAQQINDA fikirdir; onu ayrıca saxlamaq
    "xəbərdarlıq var, amma təyinat geri qaytarılıb" kimi uyğunsuz vəziyyət
    yaradardı. Audit izi isə onsuz da `apply_assignment`-in `after_state`
    sahəsindəki `conflicts` siyahısındadır.
    """

    def __init__(
        self,
        *,
        shifts: ShiftRepository,
        work_modes: WorkModeRepository,
        limits: SystemLimits,
    ) -> None:
        self._shifts = shifts
        self._work_modes = work_modes
        self._limits = limits

    def review(
        self,
        *,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        shift_date: date,
        is_off_day: bool,
        work_mode_id: WorkModeId | None,
    ) -> list[LaborRuleFinding]:
        """Verilmiş günü üç əmək qanunu qaydasına qarşı yoxlayır.

        Arqumentlər `ShiftAssignment` yox, AYRI sahələrdir: `apply_assignment`
        eyni dəyərləri onsuz da parametr kimi alır və aralıq obyekt qurmaq
        yalnız təyinat UĞURLA yazıldıqdan sonra yoxlama etmək məcburiyyəti
        yaradardı — halbuki gələcəkdə "yazmadan əvvəl göstər" ekranı da eyni
        metodu çağıra bilməlidir.
        """
        limits = self._load_limits(tenant_id)
        radius = max(limits.max_consecutive_work_days, 1) + _WINDOW_MARGIN_DAYS
        start = shift_date - timedelta(days=radius)
        end = shift_date + timedelta(days=radius)

        cache: dict[WorkModeId, WorkMode | None] = {}
        stored = self._shifts.list_range(
            tenant_id, start=start, end=end, employee_ids=[employee_id]
        )
        window = [
            PlannedShift(
                shift_date=assignment.shift_date,
                is_off_day=assignment.is_off_day,
                schedule=self._schedule_of(assignment.work_mode_id, cache),
            )
            # Başqa işçinin sətri pəncərəyə düşməməlidir: `list_range`
            # süzgəci verilib, lakin sahtə/keş implementasiyası onu görməzdən
            # gələ bilər və nəticə TAMAMİLƏ yanlış zəncir olardı.
            for assignment in stored
            if assignment.employee_id == employee_id
        ]

        target = PlannedShift(
            shift_date=shift_date,
            is_off_day=is_off_day,
            schedule=self._schedule_of(work_mode_id, cache),
        )
        return evaluate_labor_rules(target=target, window=window, limits=limits)

    # ------------------------------ köməkçilər ------------------------------- #

    def _load_limits(self, tenant_id: TenantId) -> LaborLimits:
        """Dörd ROOT parametrini oxuyur — hardcode ədəd YOXDUR."""
        return LaborLimits(
            min_rest_hours=self._limits.get_int(
                tenant_id,
                SystemLimitKey.LABOR_MIN_REST_HOURS.value,
                _FALLBACK_MIN_REST_HOURS,
            ),
            mandatory_break_minutes=self._limits.get_int(
                tenant_id,
                SystemLimitKey.LABOR_MANDATORY_BREAK_MINUTES.value,
                _FALLBACK_BREAK_MINUTES,
            ),
            break_required_after_hours=self._limits.get_int(
                tenant_id,
                SystemLimitKey.LABOR_BREAK_REQUIRED_AFTER_HOURS.value,
                _FALLBACK_BREAK_AFTER_HOURS,
            ),
            max_consecutive_work_days=self._limits.get_int(
                tenant_id,
                SystemLimitKey.LABOR_MAX_CONSECUTIVE_WORK_DAYS.value,
                _FALLBACK_MAX_CONSECUTIVE_DAYS,
            ),
        )

    def _schedule_of(
        self, work_mode_id: WorkModeId | None, cache: dict[WorkModeId, WorkMode | None]
    ) -> TimeRange | None:
        """İş rejiminin sabit saat aralığı — tapılmasa `None` (qayda susur)."""
        if work_mode_id is None:
            return None
        if work_mode_id not in cache:
            cache[work_mode_id] = self._work_modes.get(work_mode_id)
        mode = cache[work_mode_id]
        return mode.schedule if mode is not None else None


__all__ = ["LaborComplianceAdvisor"]
