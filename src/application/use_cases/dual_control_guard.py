"""Dual-Control Deadlock Guard (spesifikasiya bölmə 3) — Faza 2.4.

PROBLEM (spesifikasiyadan):
    "Tenant setup zamanı (və istifadəçi silinərkən/rolu dəyişərkən) sistem
    yoxlayır ki, ikinci-təsdiq üçün lazım olan HR_Admin/CEO rolunda ən azı bir
    aktiv istifadəçi mövcuddur. Əks halda «[Diqqət: Manual override təsdiqi
    üçün ikinci istifadəçi tapılmadı]» xəbərdarlığı göstərilir ki, gözləyən
    override-lar sonsuza qədər təsdiqsiz qalmasın (bu, real mağazada iş
    dayanmasına və təcili dəstək zənginə səbəb ola bilər)."

TERMİN QEYDİ: yuxarıdakı sitat spesifikasiyanın HƏRFİ mətnidir və olduğu
kimi saxlanılır. Faktiki interfeys mətni (`WARNING_TITLE_AZ`) isə tam
Azərbaycanca terminologiyadadır — «manual override» əvəzinə «manual vaxt
düzəlişi». Sitatı dəyişmək spesifikasiyaya istinadı yalanlayardı.

DAVRANIŞ QƏRARI: bu guard əməliyyatı BLOKLAMIR, XƏBƏRDARLIQ verir.
Səbəb: tenant qurulmasının ilk anında (birinci istifadəçi yaradılarkən)
təsdiqçi hələ mövcud olmur — sərt bloklama quraşdırmanı tamamilə mümkünsüz
edərdi. Lakin xəbərdarlıq SÜKUTLA keçmir: `security.log`-a yazılır və
bildiriş kanalına düşür.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.interfaces.ports import EmployeeRepository, Notifier, SecurityEventRepository
from src.domain.value_objects.authorization import DUAL_CONTROL_APPROVAL_FLAG
from src.domain.value_objects.identifiers import TenantId
from src.shared.logger import LogChannel, get_logger

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

WARNING_TITLE_AZ = "Diqqət: manual vaxt düzəlişinin təsdiqi üçün ikinci istifadəçi tapılmadı"
WARNING_BODY_AZ = (
    "Hazırda `can_approve_dual_control_override` səlahiyyətinə malik aktiv "
    "istifadəçi yoxdur. 30 dəqiqədən çox fərq yaradan manual vaxt düzəlişləri "
    "təsdiqsiz qalacaq və mağazada iş dayana bilər. Ən azı bir HR_Admin və ya "
    "CEO hesabı aktivləşdirin."
)


@dataclass(frozen=True)
class DeadlockCheckResult:
    """Yoxlamanın nəticəsi."""

    approver_count: int
    is_healthy: bool
    warning_az: str | None = None

    @property
    def is_deadlocked(self) -> bool:
        return not self.is_healthy


class DualControlDeadlockGuardUseCase:
    """Dual-control təsdiqçisinin mövcudluğunu yoxlayır."""

    def __init__(
        self,
        employees: EmployeeRepository,
        notifier: Notifier | None = None,
        *,
        security_events: SecurityEventRepository | None = None,
    ) -> None:
        self._employees = employees
        self._notifier = notifier
        # `notifier` İLƏ EYNİ NAXIŞ (SEC-7) — bu sinfin çağırışları HƏMİŞƏ
        # REAL vəziyyət yoxlamasıdır (permission_guards.is_allowed()-dəki
        # kimi UI-probe DUALLIĞI YOXDUR), ona görə `check()` içində
        # QEYD-ŞƏRTSİZ yazılır — `notifier`in ÖZÜ də elə çağırılır.
        self._security_events = security_events

    def check(self, tenant_id: TenantId) -> DeadlockCheckResult:
        """Aktiv təsdiqçi sayını yoxlayır və lazım gələrsə xəbərdarlıq göndərir."""
        count = self._employees.count_active_with_flag(tenant_id, DUAL_CONTROL_APPROVAL_FLAG)
        if count > 0:
            return DeadlockCheckResult(approver_count=count, is_healthy=True)

        _security_log.warning(
            "DUAL_CONTROL_DEADLOCK_RISK",
            extra={
                "tenant_id": str(tenant_id),
                "flag": DUAL_CONTROL_APPROVAL_FLAG,
                "impact": "30+ dəqiqəlik vaxt düzəlişləri təsdiqsiz qalacaq",
            },
        )
        if self._security_events is not None:
            self._security_events.record(
                tenant_id=tenant_id,
                event_type="DUAL_CONTROL_DEADLOCK_RISK",
                details={
                    "flag": DUAL_CONTROL_APPROVAL_FLAG,
                    "impact": "30+ dəqiqəlik vaxt düzəlişləri təsdiqsiz qalacaq",
                },
            )
        if self._notifier is not None:
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=None,  # bütün adminlərə
                category="DUAL_CONTROL_DEADLOCK_RISK",
                title_az=WARNING_TITLE_AZ,
                body_az=WARNING_BODY_AZ,
                is_critical=True,
            )

        return DeadlockCheckResult(approver_count=0, is_healthy=False, warning_az=WARNING_BODY_AZ)

    def check_before_change(
        self, tenant_id: TenantId, *, removing_approver: bool
    ) -> DeadlockCheckResult:
        """İstifadəçi silinərkən/rolu dəyişərkən çağırılır (bölmə 3).

        Args:
            removing_approver: Dəyişiklik bir təsdiqçini itirəcəkmi.
        """
        result = self.check(tenant_id)
        if not removing_approver:
            return result
        if result.approver_count <= 1:
            # Bu dəyişiklikdən SONRA sıfır təsdiqçi qalacaq.
            _security_log.warning(
                "DUAL_CONTROL_LAST_APPROVER_REMOVED",
                extra={
                    "tenant_id": str(tenant_id),
                    "remaining_after_change": max(0, result.approver_count - 1),
                },
            )
            if self._security_events is not None:
                self._security_events.record(
                    tenant_id=tenant_id,
                    event_type="DUAL_CONTROL_LAST_APPROVER_REMOVED",
                    details={"remaining_after_change": max(0, result.approver_count - 1)},
                )
            return DeadlockCheckResult(
                approver_count=max(0, result.approver_count - 1),
                is_healthy=False,
                warning_az=WARNING_BODY_AZ,
            )
        return result


__all__ = [
    "WARNING_BODY_AZ",
    "WARNING_TITLE_AZ",
    "DeadlockCheckResult",
    "DualControlDeadlockGuardUseCase",
]
