"""İşdən Çıxma Riski Balı — #21, kompasos11.md Faza 9.

Bu fayl İKİ şeyi birlikdə saxlayır (`behavior_baseline.py` ilə EYNİ qərar,
bax onun başlığı): (1) `AttritionRiskUseCase.recalculate_all` — gecəlik
planlaşdırılmış hesablama, (2) `list_for_tenant` — `can_view_attrition_risk`
sahibinin ekran oxu yolu. İkisi EYNİ `AttritionRiskScoreRepository`-ni
paylaşır və "bal necə hesablanır?" / "bal necə göstərilir?" sualları arasında
əlaqəni bir yerdə saxlamaq oxucuya faydalıdır.

──────────────────────────────────────────────────────────────────────────────
MƏNBƏ — YALNIZ KompasOS-un ÖZ DATASI, 1C-yə TOXUNMUR
──────────────────────────────────────────────────────────────────────────────
`kompasos11.md` #13-ün statik `ast` qapısı naxışı BURADA DA tətbiq olunur
(`tests/unit/test_attrition_risk.py`): bu modulda və `infrastructure.
persistence.attrition_repository`-də nə `erp`/`sales` idxalı, nə də
`SalesDataConnector`/`OneCSaleRecord` kimi 1C identifikatoru ola bilməz.
Bal YALNIZ mövcud cərimə/davamiyyət/staj/icazə datasından qidalanır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI PROTOKOL — `AttritionSignalProvider` NİYƏ `ports.py`-DA DEYİL
──────────────────────────────────────────────────────────────────────────────
`ReportFactProvider` naxışı (`reporting.py`): bu protokol `EmployeeAttritionSignals`
qaytarır və bu, TƏTBİQ qatının strukturudur (SQL aqreqasiyasının nəticəsi,
domen tipi deyil). Onu `ports.py`-a qoymaq domen → application asılılığı
yaradardı. `AttritionRiskScoreRepository` isə (saf domen tipi `AttritionRiskScore`
qaytarır) `ports.py`-dadır — eyni fayl daxilində iki fərqli qərar İKİSİ DƏ
qəsdəndir.

──────────────────────────────────────────────────────────────────────────────
BİLDİRİŞ SIRASI — ƏVVƏLCƏ STORE MANAGER, SONRA HR_ADMIN
──────────────────────────────────────────────────────────────────────────────
kompasos11.md #21-in açıq tələbi: mağazanın gündəlik idarəçisi (işçini FİZİKİ
görən, ilk reaksiya verə bilən şəxs) ƏVVƏLCƏ bilməlidir; HR_Admin sonra,
şirkət-miqyaslı tendensiyanı görür. `_notify_high_risk` bunu İKİ ARDICIL
`Notifier.notify()` çağırışı ilə həyata keçirir — YENİ bildiriş mexanizmi
YAZILMIR, mövcud `Notifier` portu iki dəfə (fərqli `recipient_id` ilə)
çağırılır. Store Manager `EmployeeRepository.find_by_pin_candidates` ilə
tapılır: YENİ repository metodu lazım deyil, çünki "mağazadakı aktiv, PIN-i
olan işçilər" sorğusu ARTIQ mağaza menecerini əhatə edir (`entities/employee.py`
başlığı: "Mağaza Meneceri daxil HƏR işçi rolunu əhatə edir").

──────────────────────────────────────────────────────────────────────────────
TƏKRAR BİLDİRİŞİN QARŞISI — ƏLAVƏ DB SÜTUNU YOXDUR
──────────────────────────────────────────────────────────────────────────────
`employee_documents.notify_expiring_documents` başlığındakı EYNİ qərar:
"artıq bildirildi" sütunu YARADILMIR (030 miqrasiyasının əhatəsi YALNIZ
`system_limits` seed-idir). Əvəzinə VƏZİYYƏT KEÇİDİ yoxlanır: yeni bal
hesablanmazdan ƏVVƏL işçinin ƏN SON (dünənki) balı oxunur; əgər o da CARİ
hədddən yuxarı idisə, işçi artıq "yüksək risk" vəziyyətindədir və YENİDƏN
bildiriş göndərilmir. Bildiriş yalnız hədddən AŞAĞIDAN YUXARIYA keçiddə
(və ya birinci dəfə hesablananda) gedir. Bu, `employee_documents`-in
"bərabərlik = təkrarsızlıq" trükündən daha ÜMUMİDİR: iş bir gün buraxılsa
(server dayanıqlığı) belə səhv salınmır, çünki müqayisə "dünənki gün"ə deyil,
"son BİLİNƏN vəziyyətə" əsaslanır.

Güzəşt: Root `ATTRITION_HIGH_RISK_THRESHOLD`-u DƏYİŞDİYİ gün bu müqayisə köhnə
sətri YENİ hədlə oxuyur (bant saxlanmadığı üçün başqa yol yoxdur, bax
`domain.attrition_rules` başlığı "Risk bandı saxlanılmır") — nadir hallarda
(məhz dəyişikliyin OLDUĞU gün) bir bildiriş buraxıla bilər. Bu, hər gecə min-
lərlə lazımsız təkrar bildiriş göndərməkdən daha ucuz güzəşt sayılıb.

──────────────────────────────────────────────────────────────────────────────
AUDİT — HƏM HESABLAMA, HƏM BAXIŞ
──────────────────────────────────────────────────────────────────────────────
Bu bal işçi haqqında PROQNOZDUR (səhv ola bilər) və HƏSSAS HR datasıdır — ona
görə həm `recalculate_all` (bir tənzimlənmiş cəmi audit sətri, 235 işçi üçün
235 ayrı sətir DEYİL — səs-küy yaratmadan "bu gecə nə baş verdi" sualını
cavablandırır), həm də `list_for_tenant` (kim, nə vaxt bu balları GÖRDÜ)
`AuditTrail`-ə yazılır. "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" (bölmə 3) prinsipi
bununla "GÖRMƏK = İZLƏNƏN" səviyyəsinə qədər genişlənir.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from src.domain.attrition_rules import (
    AttritionRiskScore,
    AttritionScoreResult,
    AttritionSignal,
    AttritionSignalInput,
    AttritionWeights,
    calculate_attrition_score,
    tenure_months,
)
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.authorization import AuthorizationError, SystemRole
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import date, datetime

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AttritionRiskScoreRepository,
        AuditTrail,
        Clock,
        EmployeeRepository,
        Notifier,
        SystemLimits,
    )
    from src.domain.value_objects.identifiers import EmployeeId, StoreId, TenantId

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)
_log = get_logger(__name__)

#: Faza 2-də kataloqa əlavə edilmiş flag (migrations/021).
VIEW_ATTRITION_RISK_FLAG = "can_view_attrition_risk"

#: `domain/value_objects/notifications.py::TENANT_NOTIFICATION_AUDIENCE`-də
#: qeydiyyatlı kateqoriya — HR_Admin broadcast-ı BU açarla süzülür.
ATTRITION_RISK_NOTIFICATION_CATEGORY = "ATTRITION_RISK_HIGH"

#: FALLBACK-lar — həqiqi mənbə `system_limits` (migrations/030 seed edir).
_FALLBACK_WEIGHTS: Final = AttritionWeights.defaults()
_FALLBACK_MONTHLY_LEAVE_LIMIT: Final = int(
    DEFAULT_LIMITS[SystemLimitKey.MONTHLY_LEAVE_MINUTES_LIMIT]
)


# --------------------------------------------------------------------------- #
# Xam siqnal mənbəyi — ReportFactProvider naxışı (bax modul başlığı)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EmployeeAttritionSignals:
    """Bir işçi üçün SQL aqreqasiyasından hazır gələn xam siqnallar.

    `full_name`/`store_name` BURADA YOXDUR — bu görünüş YALNIZ hesablama
    üçündür (`recalculate_all`); ekranın oxu yolu (`list_for_tenant`) adları
    AYRI, kontroller səviyyəsində (`controllers/attrition_risk.py`) əlavə
    edir — `performance_review.py::_eligible_employees` ilə eyni naxış.
    """

    employee_id: EmployeeId
    store_id: StoreId | None
    hire_date: date | None
    #: Pəncərənin sonuncu yarısındakı cərimə sayı.
    fine_count_recent_half: int
    #: Pəncərənin əvvəlki yarısındakı cərimə sayı.
    fine_count_prior_half: int
    unauthorized_absences: int
    #: Cari TƏQVİM AYININ təsdiqlənmiş icazə dəqiqələri cəmi
    #: (`LeaveRequestRepository.monthly_used_minutes` ilə EYNİ tərif).
    leave_minutes_used: int


@runtime_checkable
class AttritionSignalProvider(Protocol):
    """Bütün işçilər üçün xam siqnalların BİR SQL sorğusu ilə yığılması.

    NİYƏ TƏK-İŞÇİLİK repository metodları (`FineRepository.list_for_employee_
    month`, `LeaveRequestRepository.monthly_used_minutes`) İŞLƏDİLMİR: gecəlik
    iş YÜZLƏRLƏ işçini emal edir və hər biri üçün ayrı sorğu N+1 problemi
    yaradardı (`report_repositories.py` başlığı: "21 filialın bütün
    davamiyyət qeydlərini yaddaşa yükləmək" ilə eyni əsaslandırma).
    """

    def list_signals(
        self, tenant_id: TenantId, *, window_months: int, as_of: date
    ) -> list[EmployeeAttritionSignals]: ...


@dataclass(frozen=True)
class AttritionRecalculationReport:
    """Bir gecəlik icranın yekunu — audit/monitorinq sətri."""

    tenant_id: TenantId
    started_at: datetime
    window_months: int
    employees_updated: int = 0
    high_risk_count: int = 0
    notifications_sent: int = 0


@dataclass(frozen=True)
class AttritionRiskScoreView:
    """Ekranın oxuduğu düz görünüş.

    `is_high_risk` BURADA CARİ hədlə hesablanır (oxuma anında) — `domain.
    attrition_rules` başlığındakı "risk bandı saxlanılmır" qərarının GUI
    tərəfdəki əksi.
    """

    employee_id: EmployeeId
    score: float
    is_high_risk: bool
    factors: dict[str, dict[str, object]]
    score_date: date


class AttritionRiskUseCase:
    """Gecəlik hesablama + `can_view_attrition_risk` sahibinin oxu yolu."""

    def __init__(
        self,
        *,
        signals: AttritionSignalProvider,
        scores: AttritionRiskScoreRepository,
        employees: EmployeeRepository,
        limits: SystemLimits,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier,
    ) -> None:
        self._signals = signals
        self._scores = scores
        self._employees = employees
        self._limits = limits
        self._audit = audit
        self._clock = clock
        self._notifier = notifier

    # ------------------------------ planlanmış -------------------------------- #

    def recalculate_all(
        self, tenant_id: TenantId, *, now: datetime | None = None
    ) -> AttritionRecalculationReport:
        """Bütün işçilər üçün balı yenidən hesablayır (planlaşdırılmış iş).

        `behavior_baseline.recalculate_all`/`fine_management.expire_stale` ilə
        EYNİ naxış — YENİ planlayıcı mexanizmi YARADILMIR (bax
        `docs/scheduler_setup.md`).
        """
        as_of = now or self._clock.now()
        weights = self._load_weights(tenant_id)
        monthly_leave_limit = self._limits.get_int(
            tenant_id,
            SystemLimitKey.MONTHLY_LEAVE_MINUTES_LIMIT.value,
            _FALLBACK_MONTHLY_LEAVE_LIMIT,
        )

        raw_signals = self._signals.list_signals(
            tenant_id, window_months=weights.window_months, as_of=as_of.date()
        )

        updated = 0
        high_risk_count = 0
        notified = 0
        for signal in raw_signals:
            # DÜNƏNKİ (son bilinən) bal — YENİ sətir YAZILMAZDAN ƏVVƏL oxunur,
            # çünki `save()` UPSERT-dir və eyni günün təkrar icrasında "əvvəlki"
            # məhz bu andakı sətirdir (bax modul başlığı "Təkrar bildirişin qarşısı").
            previous = self._scores.get_latest_for_employee(tenant_id, signal.employee_id)

            result = calculate_attrition_score(
                AttritionSignalInput(
                    fine_count_recent_half=signal.fine_count_recent_half,
                    fine_count_prior_half=signal.fine_count_prior_half,
                    unauthorized_absences=signal.unauthorized_absences,
                    tenure_months=tenure_months(signal.hire_date, as_of.date()),
                    leave_usage_ratio=(
                        signal.leave_minutes_used / monthly_leave_limit
                        if monthly_leave_limit > 0
                        else 0.0
                    ),
                ),
                weights,
            )

            self._scores.save(
                AttritionRiskScore(
                    tenant_id=tenant_id,
                    employee_id=signal.employee_id,
                    score=result.score,
                    factors=result.factors_payload(),
                    score_date=as_of.date(),
                    calculated_at=as_of,
                )
            )
            updated += 1

            if result.is_high_risk:
                high_risk_count += 1
                already_notified = (
                    previous is not None and previous.score >= weights.high_risk_threshold
                )
                if not already_notified:
                    self._notify_high_risk(
                        tenant_id=tenant_id,
                        employee_id=signal.employee_id,
                        store_id=signal.store_id,
                        result=result,
                    )
                    notified += 1

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=None,
            action="ATTRITION_SCORES_RECALCULATED",
            entity_type="attrition_risk_scores",
            after_state={
                "yenilənən_işçi": updated,
                "yüksək_risk": high_risk_count,
                "bildiriş_göndərildi": notified,
                "pəncərə_ay": weights.window_months,
            },
            reason="Gecəlik planlaşdırılmış hesablama",
        )
        _log.info(
            "ATTRITION_SCORES_RECALCULATED",
            extra={
                "tenant_id": str(tenant_id),
                "yenilenen_isci": updated,
                "yuksek_risk": high_risk_count,
            },
        )
        return AttritionRecalculationReport(
            tenant_id=tenant_id,
            started_at=as_of,
            window_months=weights.window_months,
            employees_updated=updated,
            high_risk_count=high_risk_count,
            notifications_sent=notified,
        )

    # ---------------------------------- oxu ------------------------------------ #

    def list_for_tenant(
        self, *, tenant_id: TenantId, actor: Employee
    ) -> list[AttritionRiskScoreView]:
        """`can_view_attrition_risk` sahibinin "riskli işçilər" siyahısı.

        BAXIŞ AUDİT-LƏNİR (modul başlığı) — bu, "GÖRMƏK = SƏLAHİYYƏTİN
        OLMASI"nın (bölmə 3) təbii uzantısıdır: həssas proqnoz datasına kimin
        nə vaxt baxdığı da izlənməlidir.
        """
        self._require_view(actor, tenant_id)
        threshold = self._limits.get_int(
            tenant_id,
            SystemLimitKey.ATTRITION_HIGH_RISK_THRESHOLD.value,
            _FALLBACK_WEIGHTS.high_risk_threshold,
        )
        rows = self._scores.list_latest_for_tenant(tenant_id)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="ATTRITION_RISK_VIEWED",
            entity_type="attrition_risk_scores",
            after_state={"sətir_sayı": len(rows)},
        )
        return [
            AttritionRiskScoreView(
                employee_id=row.employee_id,
                score=row.score,
                is_high_risk=row.score >= threshold,
                factors={key: dict(value) for key, value in row.factors.items()},
                score_date=row.score_date,
            )
            for row in sorted(rows, key=lambda row: row.score, reverse=True)
        ]

    # ------------------------------- köməkçi -------------------------------- #

    def _load_weights(self, tenant_id: TenantId) -> AttritionWeights:
        """Yeddi ROOT parametrini oxuyur — hardcode ədəd YOXDUR."""
        return AttritionWeights(
            fine_trend_weight=self._limits.get_int(
                tenant_id,
                SystemLimitKey.ATTRITION_FINE_TREND_WEIGHT.value,
                _FALLBACK_WEIGHTS.fine_trend_weight,
            ),
            attendance_violation_weight=self._limits.get_int(
                tenant_id,
                SystemLimitKey.ATTRITION_ATTENDANCE_VIOLATION_WEIGHT.value,
                _FALLBACK_WEIGHTS.attendance_violation_weight,
            ),
            new_hire_risk_points=self._limits.get_int(
                tenant_id,
                SystemLimitKey.ATTRITION_NEW_HIRE_RISK_POINTS.value,
                _FALLBACK_WEIGHTS.new_hire_risk_points,
            ),
            new_hire_threshold_months=self._limits.get_int(
                tenant_id,
                SystemLimitKey.ATTRITION_NEW_HIRE_THRESHOLD_MONTHS.value,
                _FALLBACK_WEIGHTS.new_hire_threshold_months,
            ),
            leave_usage_weight=self._limits.get_int(
                tenant_id,
                SystemLimitKey.ATTRITION_LEAVE_USAGE_WEIGHT.value,
                _FALLBACK_WEIGHTS.leave_usage_weight,
            ),
            window_months=self._limits.get_int(
                tenant_id,
                SystemLimitKey.ATTRITION_WINDOW_MONTHS.value,
                _FALLBACK_WEIGHTS.window_months,
            ),
            high_risk_threshold=self._limits.get_int(
                tenant_id,
                SystemLimitKey.ATTRITION_HIGH_RISK_THRESHOLD.value,
                _FALLBACK_WEIGHTS.high_risk_threshold,
            ),
        )

    def _notify_high_risk(
        self,
        *,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        store_id: StoreId | None,
        result: AttritionScoreResult,
    ) -> None:
        """ƏVVƏLCƏ Store Manager-ə, SONRA HR_Admin-ə (bax modul başlığı).

        Sıra TEST OLUNUR (`test_attrition_risk.py`): sahtə `Notifier`
        çağırışları sırayla toplayır və test bu sıranı təsdiqləyir.
        """
        top_factor = max(
            (f for f in result.factors if f.signal is not AttritionSignal.SCORE_CAP),
            key=lambda f: f.points,
            default=None,
        )
        detail = top_factor.explanation_az if top_factor is not None else ""
        body = (
            f"İşçinin işdən çıxma riski balı {result.score:.0f} "
            f"(hədd: {result.high_risk_threshold}). Əsas amil: {detail}"
        )
        title = "İşçidə işdən çıxma riski yüksəkdir"

        # 1) STORE MANAGER — ŞƏXSİ sətir, mağazasının işçisi barədə.
        if store_id is not None:
            for manager in self._employees.find_by_pin_candidates(tenant_id, store_id):
                if manager.position.code != SystemRole.STORE_MANAGER.value:
                    continue
                if manager.id == employee_id:
                    continue  # işçinin özü menecerdirsə özünə bildiriş getmir
                self._notifier.notify(
                    tenant_id=tenant_id,
                    recipient_id=manager.id,
                    category=ATTRITION_RISK_NOTIFICATION_CATEGORY,
                    title_az=title,
                    body_az=body,
                    is_critical=False,
                )

        # 2) HR_ADMIN — tenant-broadcast, `TENANT_NOTIFICATION_AUDIENCE`-də
        # `can_view_attrition_risk` ilə süzülür (Root/CEO/HR_Admin görür).
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=None,
            category=ATTRITION_RISK_NOTIFICATION_CATEGORY,
            title_az=title,
            body_az=body,
            is_critical=False,
        )

    def _require_view(self, actor: Employee, tenant_id: TenantId) -> None:
        if actor.tenant_id != tenant_id:
            # Üçüncü izolyasiya qatı (RLS və repo `tenant_id` şərtindən sonra).
            raise AuthorizationError(
                "Aktor bu kirayəçiyə aid deyil",
                context={"actor_id": str(actor.id)},
            )
        now = self._clock.now()
        if not actor.has_permission(VIEW_ATTRITION_RISK_FLAG, now=now):
            _security_log.warning(
                "ATTRITION_RISK_VIEW_DENIED",
                extra={"actor_id": str(actor.id), "flag": VIEW_ATTRITION_RISK_FLAG},
            )
            raise AuthorizationError(
                f"«{VIEW_ATTRITION_RISK_FLAG}» səlahiyyəti yoxdur",
                user_message="Bu məlumata baxmaq səlahiyyətiniz yoxdur.",
                context={"flag": VIEW_ATTRITION_RISK_FLAG},
            )


__all__ = [
    "ATTRITION_RISK_NOTIFICATION_CATEGORY",
    "VIEW_ATTRITION_RISK_FLAG",
    "AttritionRecalculationReport",
    "AttritionRiskScoreView",
    "AttritionRiskUseCase",
    "AttritionSignalProvider",
    "EmployeeAttritionSignals",
]
