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

from collections.abc import Collection
from dataclasses import dataclass

from src.domain.interfaces.ports import EmployeeRepository, Notifier, SecurityEventRepository
from src.domain.value_objects.authorization import (
    DEADLOCK_CRITICAL_FLAGS,
    DUAL_CONTROL_APPROVAL_FLAG,
)
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
class FlagCoverage:
    """BİR kritik flagın tenant-dakı örtüyü (AF-1).

    `DeadlockCheckResult`-a ƏLAVƏDİR, onu əvəz ETMİR: mövcud çağıranlar
    `approver_count`/`is_healthy` oxumağa davam edir (bax həmin sinfin
    şərhi), bu sinif isə «hansı flag, neçə daşıyıcı, nəticəsi nədir»
    sualına cavab verir.
    """

    flag_code: str
    holder_count: int
    #: Flag itirildikdə NƏ dayanır — `DEADLOCK_CRITICAL_FLAGS`-dan gəlir,
    #: burada TƏKRAR YAZILMIR (ikinci ad məkanı yaranmasın).
    impact_az: str

    @property
    def is_healthy(self) -> bool:
        return self.holder_count > 0

    def warning_az(self) -> str:
        """İstifadəçiyə göstərilən xəbərdarlıq mətni."""
        return (
            f"Hazırda «{self.flag_code}» səlahiyyətinə malik aktiv istifadəçi yoxdur — "
            f"{self.impact_az}. Ən azı bir hesaba bu səlahiyyəti verin."
        )


@dataclass(frozen=True)
class DeadlockCheckResult:
    """Yoxlamanın nəticəsi.

    `approver_count`/`is_healthy` DUAL-CONTROL flagına aiddir və MƏNASI
    DƏYİŞMƏYİB — AF-1 genişlənməsi onları olduğu kimi saxladı, çünki mövcud
    çağıranlar (`user_management`, audit `after_state`, ekran) məhz həmin
    sayğacı oxuyur. Digər kritik flaglar `coverages`-dədir.
    """

    approver_count: int
    is_healthy: bool
    warning_az: str | None = None
    #: BÜTÜN kritik flagların örtüyü (AF-1). Boş tuple = genişləndirilmiş
    #: yoxlama aparılmayıb (köhnə çağırış yolu) — «hamısı sağlamdır» DEYİL.
    coverages: tuple[FlagCoverage, ...] = ()

    @property
    def is_deadlocked(self) -> bool:
        return not self.is_healthy

    @property
    def missing_flags(self) -> tuple[str, ...]:
        """Daşıyıcısı QALMAYAN kritik flaglar (dual-control DAXİL)."""
        return tuple(item.flag_code for item in self.coverages if not item.is_healthy)


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
        """BÜTÜN kritik flagların örtüyünü yoxlayır və boşluq üçün xəbərdarlıq verir.

        ──────────────────────────────────────────────────────────────────────
        AF-1 — NİYƏ BİR FLAGDAN SİYAHIYA
        ──────────────────────────────────────────────────────────────────────
        Əvvəl yalnız `can_approve_dual_control_override` sayılırdı. Boşluq
        MEXANİZMDƏ deyil, GİRİŞDƏ idi: eyni sükutlu deadlock digər qapılarda
        da mümkündür (bax `DEADLOCK_CRITICAL_FLAGS` şərhi) və heç biri
        Self-Escalation Guard-la tutulmurdu — o, yalnız səlahiyyət
        ARTIRMAĞI kəsir.

        DUAL-CONTROL YOLU HƏRFƏN QORUNUR: eyni log açarı, eyni
        `security_events` tipi, eyni bildiriş kateqoriyası və eyni mətn
        (`WARNING_BODY_AZ`). Yalnız YENİ flaglar üçün ümumi açar işlədilir —
        əks halda mövcud audit sorğuları və bildiriş auditoriyası sükutla
        dəyişərdi.
        """
        coverages = self._coverages(tenant_id)
        approver_count = next(
            (
                item.holder_count
                for item in coverages
                if item.flag_code == DUAL_CONTROL_APPROVAL_FLAG
            ),
            0,
        )
        missing = tuple(item for item in coverages if not item.is_healthy)
        for item in missing:
            self._record_gap(tenant_id, item)
        self._notify_gaps(tenant_id, missing)

        if approver_count > 0:
            return DeadlockCheckResult(
                approver_count=approver_count, is_healthy=True, coverages=coverages
            )
        return DeadlockCheckResult(
            approver_count=0,
            is_healthy=False,
            warning_az=WARNING_BODY_AZ,
            coverages=coverages,
        )

    def check_before_flag_loss(
        self, tenant_id: TenantId, *, losing_flags: Collection[str]
    ) -> DeadlockCheckResult:
        """Subyektin DAŞIDIĞI kritik flaglar itirilməzdən ƏVVƏL yoxlayır (AF-1/AF-8).

        `check_before_change` ROL-a görə tək bir sual verirdi («təsdiqçini
        itiririkmi?»). Bu metod isə FLAG siyahısı alır — deməli custom rol da
        düzgün sayılır (AF-8: `effective_system_role` custom rolu prioritetə
        xəritələsə də, ROLUN KODU heç vaxt `HR_ADMIN` olmur və köhnə yoxlama
        onu görmürdü).

        BLOKLAMIR — modul başlığındakı qərar dəyişməyib: xəbərdarlıq verilir,
        qərarı insan verir.

        Args:
            losing_flags: Dəyişiklikdən SONRA subyektin daşımayacağı kritik
                flaglar (adətən onun HAZIRDA daşıdıqları).
        """
        result = self.check(tenant_id)
        losing = {flag for flag in losing_flags if flag in DEADLOCK_CRITICAL_FLAGS}
        if not losing:
            return result

        emptied: list[FlagCoverage] = []
        for item in result.coverages:
            if item.flag_code not in losing or item.holder_count > 1:
                continue
            # Bu dəyişiklikdən SONRA sıfır daşıyıcı qalacaq.
            emptied.append(FlagCoverage(item.flag_code, 0, item.impact_az))
            self._raise_last_holder(tenant_id, item)

        if not emptied:
            return result

        drained = {item.flag_code for item in emptied}
        after = tuple(
            FlagCoverage(item.flag_code, 0, item.impact_az) if item.flag_code in drained else item
            for item in result.coverages
        )
        dual_lost = DUAL_CONTROL_APPROVAL_FLAG in drained
        return DeadlockCheckResult(
            approver_count=0 if dual_lost else result.approver_count,
            is_healthy=False,
            warning_az=WARNING_BODY_AZ if dual_lost else emptied[0].warning_az(),
            coverages=after,
        )

    # ------------------------------- köməkçilər ------------------------------ #

    def _coverages(self, tenant_id: TenantId) -> tuple[FlagCoverage, ...]:
        """Hər kritik flag üçün aktiv daşıyıcı sayı — SIRA SABİTDİR.

        `DEADLOCK_CRITICAL_FLAGS` lüğətinin sırası ilə gedilir ki, audit və
        ekran sətirləri hər icrada eyni ardıcıllıqda görünsün
        (`ExceptionRuleRegistry`-nin «NİYƏ SIRA QORUNUR» qərarı ilə eyni).
        """
        return tuple(
            FlagCoverage(
                flag_code=flag,
                holder_count=self._employees.count_active_with_flag(tenant_id, flag),
                impact_az=impact,
            )
            for flag, impact in DEADLOCK_CRITICAL_FLAGS.items()
        )

    def _record_gap(self, tenant_id: TenantId, item: FlagCoverage) -> None:
        """Daşıyıcısı OLMAYAN flag üçün İZ — bildiriş BURADA GÖNDƏRİLMİR.

        Jurnal və `security_events` HƏR flag üçün AYRICA yazılır (onlar
        sübutdur və birləşdirilsəydi «hansı flag nə vaxt boşaldı?» sualı
        cavabsız qalardı), bildiriş isə `_notify_gaps`-də TOPLANIR.
        """
        is_dual = item.flag_code == DUAL_CONTROL_APPROVAL_FLAG
        event_type = "DUAL_CONTROL_DEADLOCK_RISK" if is_dual else "PERMISSION_COVERAGE_GAP"
        _security_log.warning(
            event_type,
            extra={
                "tenant_id": str(tenant_id),
                "flag": item.flag_code,
                "impact": item.impact_az,
            },
        )
        if self._security_events is not None:
            self._security_events.record(
                tenant_id=tenant_id,
                event_type=event_type,
                details={"flag": item.flag_code, "impact": item.impact_az},
            )

    def _notify_gaps(self, tenant_id: TenantId, missing: tuple[FlagCoverage, ...]) -> None:
        """ƏN ÇOX İKİ bildiriş: dual-control (köhnə sətir) + qalanların TOPLUSU.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ HƏR FLAG ÜÇÜN AYRICA BİLDİRİŞ YOX
        ──────────────────────────────────────────────────────────────────────
        Yeni kirayəçinin ilk anında DÖRD flagın da daşıyıcısı yoxdur — hər
        biri üçün ayrıca kritik bildiriş göndərsəydik, quraşdırma sihirbazı
        işləyərkən panel dörd eyni məzmunlu xəbərdarlıqla dolardı və məhz
        `TENANT_NOTIFICATION_AUDIENCE` başlığının qadağan etdiyi hal yaranardı
        («həqiqi bildirişləri səs-küydə itirmək»).

        DUAL-CONTROL AYRICA QALIR: onun kateqoriyası, başlığı və mətni mövcud
        çağıranların gözlədiyi ilə HƏRFƏN eynidir (ekran, audit sorğusu,
        auditoriya cədvəli) — toplu sətrə qatsaydıq həmin bağlar sükutla
        qırılardı.
        """
        if self._notifier is None or not missing:
            return
        others = [item for item in missing if item.flag_code != DUAL_CONTROL_APPROVAL_FLAG]
        if len(others) < len(missing):
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=None,  # icazə paylaya bilən rollar (auditoriya cədvəli)
                category="DUAL_CONTROL_DEADLOCK_RISK",
                title_az=WARNING_TITLE_AZ,
                body_az=WARNING_BODY_AZ,
                is_critical=True,
            )
        if not others:
            return
        lines = "\n".join(f"• {item.flag_code} — {item.impact_az}" for item in others)
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=None,
            category="PERMISSION_COVERAGE_GAP",
            title_az="Diqqət: kritik səlahiyyətlərin daşıyıcısı qalmayıb",
            body_az=(
                f"Aşağıdakı səlahiyyətlərə malik aktiv istifadəçi yoxdur:\n{lines}\n"
                f"Ən azı bir hesaba hər bir səlahiyyəti verin."
            ),
            is_critical=True,
        )

    def _raise_last_holder(self, tenant_id: TenantId, item: FlagCoverage) -> None:
        """SON daşıyıcı itirilir — dəyişiklik hələ BAŞ VERMƏYİB."""
        is_dual = item.flag_code == DUAL_CONTROL_APPROVAL_FLAG
        event_type = (
            "DUAL_CONTROL_LAST_APPROVER_REMOVED" if is_dual else "PERMISSION_LAST_HOLDER_REMOVED"
        )
        _security_log.warning(
            event_type,
            extra={
                "tenant_id": str(tenant_id),
                "flag": item.flag_code,
                "remaining_after_change": 0,
            },
        )
        if self._security_events is not None:
            self._security_events.record(
                tenant_id=tenant_id,
                event_type=event_type,
                details={"flag": item.flag_code, "remaining_after_change": 0},
            )

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
    "FlagCoverage",
]
