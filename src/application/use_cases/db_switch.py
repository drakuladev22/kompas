"""Hibrid Baza Keçidi — Cloud ↔ Şəxsi Server (spesifikasiya bölmə 2).

──────────────────────────────────────────────────────────────────────────────
NİYƏ SAGA DEYİL, XƏTTİ ORKESTRATOR
──────────────────────────────────────────────────────────────────────────────
Layihədə çox-aqreqatlı əməliyyatlar üçün `SagaOrchestrator` var, lakin baza
keçidi ONA UYĞUN GƏLMİR: saga hər addım üçün kompensasiya funksiyası saxlayır
və onları tərs sırada icra edir. Burada isə kompensasiya HƏMİŞƏ EYNİDİR —
"köhnə bazaya qayıt". Yeddi ayrı kompensasiya yazmaq həmin bir əməliyyatın
yeddi kopyası olardı.

Üstəlik saga vəziyyəti DB-də saxlayır — halbuki bu əməliyyat məhz DB-ni
dəyişir. Miqrasiyanın ortasında saga vəziyyətinin hansı bazada olduğu sualı
cavabsız qalardı.

──────────────────────────────────────────────────────────────────────────────
AVTOMATİK ROLLBACK ŞƏRTLƏRİ
──────────────────────────────────────────────────────────────────────────────
Üç haldan biri geri qaytarma yaradır (bölmə 2: "avtomatik rollback"):

    1. barmaq izləri fərqlənir       → məlumat tam köçürülməyib;
    2. istənilən addım istisna atır  → vəziyyət naməlumdur;
    3. maintenance window vaxtı bitir → kəsinti planlaşdırılandan uzundur.

Hər üçündə nəticə eynidir: aktiv baza KÖHNƏSİ olaraq qalır və hadisə
`db_migration_events`-ə `ROLLED_BACK` kimi yazılır. "Qismən uğurlu keçid"
adlı vəziyyət MÖVCUD DEYİL.

──────────────────────────────────────────────────────────────────────────────
BUFER BOŞALMADAN KEÇİD BAŞLAMIR
──────────────────────────────────────────────────────────────────────────────
Bölmə 2: "pending offline buffer yazılarının TAM sinxronizasiyasını gözləyir".
Gözləmə müddəti aşılarsa keçid ÜMUMİYYƏTLƏ başlamır — sinxronlaşmamış yazı
ilə miqrasiya həmin yazının itməsi deməkdir. Bu, "gec olsun, düz olsun"
qərarıdır və qəsdən belədir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.domain.value_objects.authorization import SystemRole
from src.domain.value_objects.infrastructure import (
    ChecksumPair,
    MaintenanceWindow,
    MaintenanceWindowError,
    MigrationError,
    MigrationPhase,
    MigrationPlan,
    MigrationStatus,
)
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        Clock,
        DatabaseMigrator,
        MigrationEventLog,
        Notifier,
        OfflineBufferDrain,
        ReadOnlyModeController,
    )
    from src.domain.value_objects.identifiers import TenantId

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)
_error_log = get_logger(__name__, channel=LogChannel.ERROR)

SWITCH_DB_FLAG = "can_switch_db"


@dataclass
class MigrationReport:
    """Keçidin nəticəsi — ekranın göstərdiyi tam mənzərə."""

    plan: MigrationPlan
    status: MigrationStatus = MigrationStatus.IN_PROGRESS
    completed_phases: list[MigrationPhase] = field(default_factory=list)
    failed_phase: MigrationPhase | None = None
    checksums: ChecksumPair | None = None
    buffer_flushed: bool = False
    rollback_reason: str | None = None
    event_id: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status is MigrationStatus.COMPLETED

    @property
    def active_target_after(self) -> object:
        """Əməliyyatdan SONRA hansı baza aktivdir.

        Uğursuzluqda MƏNBƏ qalır — istifadəçi "indi hardayam?" sualının
        cavabını ekranda görməlidir.
        """
        return self.plan.destination if self.succeeded else self.plan.source

    def summary_az(self) -> str:
        done = len(self.completed_phases)
        total = len(MigrationPhase)
        if self.succeeded:
            return (
                f"Keçid tamamlandı ({done}/{total} addım). "
                f"Aktiv baza: {self.plan.destination.label_az}."
            )
        if self.failed_phase is not None:
            return (
                f"«{self.failed_phase.label_az}» addımında dayandı "
                f"({done}/{total}). Səbəb: {self.rollback_reason}. "
                f"Aktiv baza dəyişmədi: {self.plan.source.label_az}."
            )
        return f"Keçid icra edilmədi. Səbəb: {self.rollback_reason}"


class DatabaseSwitchUseCase:
    """`[İnfrastruktur Və Baza Ayarları]` panelinin arxasındakı orkestrator."""

    def __init__(
        self,
        *,
        read_only: ReadOnlyModeController,
        buffer: OfflineBufferDrain,
        migrator: DatabaseMigrator,
        events: MigrationEventLog,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier | None = None,
    ) -> None:
        self._read_only = read_only
        self._buffer = buffer
        self._migrator = migrator
        self._events = events
        self._audit = audit
        self._clock = clock
        self._notifier = notifier

    # ------------------------------ ön yoxlama ------------------------------- #

    def preflight(self, *, tenant_id: TenantId, actor: Employee, plan: MigrationPlan) -> list[str]:
        """Təsdiq modalından ƏVVƏL göstərilən xəbərdarlıqlar.

        Boş siyahı "hazırdır" deməkdir. Bu addım əməliyyatı bloklamır —
        istifadəçi nəyin gözlədiyini BİLƏRƏK davam etməlidir.
        """
        self._require_permission(actor, now=self._clock.now())

        warnings: list[str] = []
        pending = self._buffer.pending_count(tenant_id)
        if pending:
            warnings.append(
                f"{pending} sinxronlaşmamış offline yazı var — keçiddən əvvəl "
                f"onlar göndəriləcək (maks. {plan.drain_timeout_seconds} saniyə gözlənilir)."
            )
        if self._read_only.is_read_only(tenant_id):
            warnings.append(
                "Sistem ARTIQ yalnız-oxu rejimindədir — başqa bir texniki fasilə davam edə bilər."
            )
        return warnings

    # -------------------------------- icra ----------------------------------- #

    def execute(
        self, *, tenant_id: TenantId, actor: Employee, plan: MigrationPlan
    ) -> MigrationReport:
        """Keçidi icra edir — heç vaxt yarımçıq vəziyyət qoymur.

        `can_switch_db` YALNIZ Root/CEO-da ola bilər (bölmə 3); yoxlama
        həm flag, həm də rol səviyyəsindədir, çünki bu əməliyyat bütün
        tenant-ın məlumatına toxunur.
        """
        now = self._clock.now()
        self._require_permission(actor, now=now)

        report = MigrationReport(plan=plan)
        window = MaintenanceWindow(opened_at=now, max_minutes=plan.window_minutes)
        report.event_id = self._events.start(
            tenant_id=tenant_id,
            initiated_by=actor.id,
            source=plan.source,
            destination=plan.destination,
            window_start=now,
        )
        _security_log.warning(
            "DB_MIGRATION_STARTED",
            extra={
                "actor_id": str(actor.id),
                "source": plan.source.value,
                "destination": plan.destination.value,
            },
        )

        try:
            self._run_phases(tenant_id, plan, window, report)
        # Hər istisna rollback deməkdir — burada dar `except` yazmaq bir
        # gün naməlum xəta tipini süzgəcdən buraxıb yarımçıq keçid qoyardı.
        except Exception as exc:
            self._error(report, str(exc))
            self._rollback(tenant_id, plan, report)
        else:
            report.status = MigrationStatus.COMPLETED
        finally:
            # Yalnız-oxu rejimi HƏR HALDA açılır: uğursuzluqda da sistem
            # bloklu qalmamalıdır — əks halda bir səhv bütün mağazaları
            # işləməz vəziyyətdə saxlayardı.
            self._leave_read_only(tenant_id)
            self._finish(tenant_id, actor, report, window)

        return report

    def _run_phases(
        self,
        tenant_id: TenantId,
        plan: MigrationPlan,
        window: MaintenanceWindow,
        report: MigrationReport,
    ) -> None:
        """Yeddi addım — SIRA ilə, hər birindən sonra pəncərə yoxlanır."""
        # 1. Texniki fasilə açılır.
        report.failed_phase = MigrationPhase.OPEN_WINDOW
        self._read_only.enter_read_only(
            tenant_id, reason=f"Baza keçidi: {plan.source.value} → {plan.destination.value}"
        )
        self._done(report, MigrationPhase.OPEN_WINDOW, window)

        # 2. Offline bufer boşaldılır — TAM sinxronizasiya tələb olunur.
        report.failed_phase = MigrationPhase.DRAIN_BUFFER
        remaining = self._buffer.flush(tenant_id)
        if remaining:
            raise MigrationError(
                f"{remaining} offline yazı sinxronlaşdırıla bilmədi — keçid başlamır",
                user_message=(
                    "Sinxronlaşmamış yazılar qalıb. Şəbəkə bağlantısını yoxlayıb yenidən cəhd edin."
                ),
                context={"pending": remaining},
            )
        report.buffer_flushed = True
        self._done(report, MigrationPhase.DRAIN_BUFFER, window)

        # 3. Mənbənin barmaq izi — bufer boşaldıqdan SONRA (modul başlığına bax).
        report.failed_phase = MigrationPhase.PREFLIGHT_CHECKSUM
        preflight = self._migrator.checksum(plan.source)
        report.checksums = ChecksumPair(preflight=preflight)
        self._done(report, MigrationPhase.PREFLIGHT_CHECKSUM, window)

        # 4. Köçürmə.
        report.failed_phase = MigrationPhase.COPY_DATA
        self._migrator.copy(source=plan.source, destination=plan.destination)
        self._done(report, MigrationPhase.COPY_DATA, window)

        # 5. Hədəfin barmaq izi və müqayisə.
        report.failed_phase = MigrationPhase.POSTFLIGHT_CHECKSUM
        postflight = self._migrator.checksum(plan.destination)
        report.checksums = ChecksumPair(preflight=preflight, postflight=postflight)
        if not report.checksums.matched:
            raise MigrationError(
                "Pre-flight və post-flight barmaq izləri fərqlənir — məlumat tam köçürülməyib",
                user_message=(
                    "Yoxlama uğursuz oldu: köçürülmüş məlumat mənbə ilə üst-üstə "
                    "düşmür. Keçid geri qaytarıldı."
                ),
                context={"preflight": preflight, "postflight": postflight},
            )
        self._done(report, MigrationPhase.POSTFLIGHT_CHECKSUM, window)

        # 6. Bağlantının yönləndirilməsi — YALNIZ yoxlama uğurlu olduqdan sonra.
        report.failed_phase = MigrationPhase.SWITCH_CONNECTION
        self._migrator.switch_active(plan.destination)
        self._done(report, MigrationPhase.SWITCH_CONNECTION, window)

        # 7. Fasilə bağlanır.
        report.failed_phase = MigrationPhase.CLOSE_WINDOW
        self._done(report, MigrationPhase.CLOSE_WINDOW, window, check_window=False)
        report.failed_phase = None

    def _done(
        self,
        report: MigrationReport,
        phase: MigrationPhase,
        window: MaintenanceWindow,
        *,
        check_window: bool = True,
    ) -> None:
        """Addımı tamamlanmış sayır və pəncərənin vaxtını yoxlayır.

        Sonuncu addımda yoxlama APARILMIR: pəncərə məhz orada bağlanır və
        son saniyədə bitmiş vaxta görə uğurlu keçidi geri qaytarmaq mənasız
        olardı — məlumat artıq yerindədir.
        """
        report.completed_phases.append(phase)
        if check_window and window.is_expired(now=self._clock.now()):
            raise MaintenanceWindowError(
                f"Texniki fasilə vaxtı bitdi ({window.max_minutes} dəq) — "
                f"«{phase.label_az}» addımından sonra dayandırıldı",
                context={"phase": phase.value},
            )

    # ------------------------------ geri qaytarma ---------------------------- #

    def _rollback(self, tenant_id: TenantId, plan: MigrationPlan, report: MigrationReport) -> None:
        """Aktiv bazanı MƏNBƏYƏ qaytarır.

        Geri qaytarmanın özü uğursuz olarsa, hadisə `FAILED` kimi yazılır və
        istifadəçiyə açıq deyilir — sükutla "hər şey qaydasındadır" göstərmək
        ən pis nəticədir.
        """
        reason = report.rollback_reason or "Naməlum xəta"
        try:
            self._migrator.rollback(to=plan.source, reason=reason)
        except Exception as exc:
            report.status = MigrationStatus.FAILED
            report.rollback_reason = f"{reason} · GERİ QAYTARMA DA UĞURSUZ OLDU: {exc}"
            _error_log.critical(
                "DB_MIGRATION_ROLLBACK_FAILED",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )
            return

        report.status = MigrationStatus.ROLLED_BACK
        _security_log.warning(
            "DB_MIGRATION_ROLLED_BACK",
            extra={"tenant_id": str(tenant_id), "reason": reason},
        )

    def _error(self, report: MigrationReport, message: str) -> None:
        report.rollback_reason = message
        _error_log.error(
            "DB_MIGRATION_PHASE_FAILED",
            extra={
                "phase": report.failed_phase.value if report.failed_phase else None,
                "error": message,
            },
        )

    def _leave_read_only(self, tenant_id: TenantId) -> None:
        try:
            self._read_only.leave_read_only(tenant_id)
        except Exception:
            # Bu, ən pis haldır: sistem read-only qalır. Kritik səviyyədə
            # loglanır ki, dəstək dərhal müdaxilə edə bilsin.
            _error_log.critical("DB_MIGRATION_READ_ONLY_STUCK", extra={"tenant_id": str(tenant_id)})

    # -------------------------------- yekun ---------------------------------- #

    def _finish(
        self,
        tenant_id: TenantId,
        actor: Employee,
        report: MigrationReport,
        window: MaintenanceWindow,
    ) -> None:
        """Hadisəni `db_migration_events`-ə və audit jurnalına yazır."""
        now = self._clock.now()
        if report.event_id is not None:
            self._events.finish(
                report.event_id,
                status=report.status,
                checksums=report.checksums,
                buffer_flushed=report.buffer_flushed,
                rolled_back=report.status is MigrationStatus.ROLLED_BACK,
                rollback_reason=report.rollback_reason,
                window_end=now,
            )

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="DB_MIGRATION",
            entity_type="db_migration_event",
            entity_id=report.event_id,
            before_state={"active_target": report.plan.source.value},
            after_state={
                "active_target": (
                    report.plan.destination.value if report.succeeded else report.plan.source.value
                ),
                "status": report.status.value,
                "phases_completed": [phase.value for phase in report.completed_phases],
                "checksum_matched": (report.checksums.matched if report.checksums else False),
                "window_minutes": window.max_minutes,
            },
            reason=report.rollback_reason,
        )

        if self._notifier is not None and not report.succeeded:
            try:
                self._notifier.notify(
                    tenant_id=tenant_id,
                    recipient_id=actor.id,
                    category="TIMEOUT_ESCALATION",
                    title_az="Baza keçidi tamamlanmadı",
                    body_az=report.summary_az(),
                    is_critical=True,
                )
            except Exception:
                _error_log.exception("DB_MIGRATION_NOTIFY_FAILED")

    # ------------------------------- tarixçə --------------------------------- #

    def history(self, *, tenant_id: TenantId, actor: Employee) -> list[dict[str, object]]:
        """Keçid tarixçəsi — paneldəki jurnal cədvəli."""
        self._require_permission(actor, now=self._clock.now())
        return self._events.history(tenant_id)

    # ------------------------------ səlahiyyət ------------------------------- #

    def _require_permission(self, actor: Employee, *, now: datetime) -> None:
        """`can_switch_db` + Root/CEO rolu (bölmə 3).

        İKİ QAT: flag təsadüfən verilə bilər, rol isə tenant qurulanda təyin
        olunur. Bu əməliyyat bütün məlumata toxunduğu üçün hər iki şərt
        tələb olunur.
        """
        if not actor.has_permission(SWITCH_DB_FLAG, now=now):
            _security_log.warning("DB_SWITCH_DENIED_FLAG", extra={"actor_id": str(actor.id)})
            raise MigrationError(
                f"«{SWITCH_DB_FLAG}» səlahiyyəti yoxdur",
                user_message="Baza ayarlarını dəyişmək səlahiyyətiniz yoxdur.",
            )
        if actor.position.effective_system_role not in (SystemRole.ROOT, SystemRole.CEO):
            _security_log.warning(
                "DB_SWITCH_DENIED_ROLE",
                extra={"actor_id": str(actor.id), "role": actor.position.code},
            )
            raise MigrationError(
                "Baza keçidi YALNIZ Root/CEO tərəfindən icra edilə bilər (bölmə 3)",
                user_message="Bu əməliyyat yalnız Root və CEO üçündür.",
                context={"role": actor.position.code},
            )


__all__ = [
    "SWITCH_DB_FLAG",
    "DatabaseSwitchUseCase",
    "MigrationReport",
]
