"""Planlayıcının BAĞLANTI testləri: qeydiyyat, iki giriş nöqtəsi, çıxış kodu.

`test_job_runner.py` NÜVƏNİ yoxlayır (icarə, yarış, slot sərhədi). Bu fayl isə
nüvənin İSTİFADƏSİNİ yoxlayır və sualları tamamilə fərqlidir:

  * doğru işlər, DOĞRU SIRA ilə qeydiyyatdan keçirmi (baz xətti motordan əvvəl);
  * hər `handler` FAKTİKİ olaraq öz use case metodunu çağırırmı — yoxsa
    reyestrdə adı olan, lakin heç nə etməyən "boş" iş varmı;
  * GUI yolu ağır işi ATLAYIR, CLI yolu icra EDİR;
  * `QTimer` intervalı ROOT dəyərindən gəlirmi (kodda sabit YOXDUR);
  * bir iş çökəndə CLI çıxış kodu QEYRİ-SIFIR olurmu.

Sonuncu ən vacibidir: sükutla udulmuş nasazlıq Windows Task Scheduler-ə
"uğurlu" kimi görünərdi və gecə işlərinin dayandığı HEÇ VAXT aşkarlanmazdı.

SAHTƏLƏR BU FAYLDADIR (paylaşılan `tests/fixtures/fakes.py` dəyişdirilmir):
`_FakeDatabase` `_StandaloneLimits`/`_StandaloneAudit` körpülərinin HƏQİQİ
yolundan keçir — yəni limit oxusu və audit yazısı sahtə ilə əvəzlənmir,
yalnız bağlantı əvəzlənir.
"""

from __future__ import annotations

import ast
import inspect
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, ClassVar, Final

import pytest

from src.application.use_cases.job_runner import (
    JobCadence,
    JobExecutionContext,
    JobOutcome,
    JobOutcomeState,
    JobRunner,
    JobWeight,
    SchedulerRunReport,
)
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.identifiers import StoreId, TenantId
from src.presentation.composition import ApplicationContext
from src.shared.runtime import process_instance_id
from tests.fixtures.fakes import (
    FakeClock,
    FakeSystemLimits,
    RecordingAudit,
    RecordingNotifier,
)

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())
STORE_A: Final = StoreId(uuid.uuid4())
STORE_B: Final = StoreId(uuid.uuid4())
NOW: Final = datetime(2026, 8, 13, 9, 12, tzinfo=UTC)

#: Qeydiyyatın GÖZLƏNİLƏN tam siyahısı — açar, ritm, çəki və SIRA ilə.
#: Test bu cədvəli kodun ÖZÜNDƏN çıxarmır (əks halda hər dəyişikliyi sükutla
#: təsdiqləyərdi) — siyahı burada ƏL İLƏ yazılıb və dəyişiklik testi sındırır.
EXPECTED_JOBS: Final = (
    ("BEHAVIOR_BASELINE_RECALC", JobCadence.DAILY, JobWeight.LIGHT),
    ("EXCEPTION_ENGINE_RUN", JobCadence.DAILY, JobWeight.LIGHT),
    ("STAFFING_PATTERN_REFRESH", JobCadence.DAILY, JobWeight.LIGHT),
    ("EMPLOYEE_DOCUMENT_EXPIRY_NOTICE", JobCadence.DAILY, JobWeight.LIGHT),
    ("ATTRITION_RISK_RECALC", JobCadence.DAILY, JobWeight.LIGHT),
    # #26 (kompas1.md Faza 3) — audit tezliyi xatırlatması. `DAILY`, çünki
    # interval GÜN vahidlidir; `LIGHT`, çünki iş tək aqreqat sorğusu +
    # filial sayı qədər bildiriş sətridir.
    ("FIELD_REPORT_AUDIT_REMINDER", JobCadence.DAILY, JobWeight.LIGHT),
    # #28 (kompas1.md Faza 4) — illik məzuniyyət accrual-ı, köçürməsi və
    # "istifadə et ya itir" son tarixi. `DAILY`, "hər 1 yanvar" DEYİL:
    # terminal həmin gecə söndürülmüş ola bilər və şərt qoyulsaydı köçürmə
    # BÜTÜN İL üçün itərdi. Gündəlik icra zərərsizdir, çünki iş
    # İDEMPOTENTDİR (haqq TƏYİN edilir, artırılmır).
    ("ANNUAL_LEAVE_YEAR_ROLLOVER", JobCadence.DAILY, JobWeight.LIGHT),
    # CHAT-1 (tg1.md Faza 6) — «Həll olundu → Bağlandı» keçidi və
    # «Gözləmədə» xatırlatması. Müddətlər GÜN vahidlidir, ona görə `DAILY`.
    ("SUPPORT_STATUS_MAINTENANCE", JobCadence.DAILY, JobWeight.LIGHT),
    # `facecontrol.md` bənd 14 — Face Control istisnalarının müddət-bitməsi.
    # `DAILY`: müddət GÜN vahidlidir; `LIGHT`: bir indeksli sorğu + bitən sətir
    # qədər UPDATE. GECİKMƏ BOŞLUQ YARATMIR — `FaceExemption.is_active_at()`
    # həm statusa, həm `expires_at`-a baxır, yəni istisna öz tarixində faktiki
    # olaraq bitir və gecəlik iş yalnız statusu təmizləyir.
    ("FACE_EXEMPTION_EXPIRY", JobCadence.DAILY, JobWeight.LIGHT),
    # `facecontrol.md` bənd 17 — doğrulama jurnalının saxlama müddəti.
    # `DAILY` + `LIGHT`: tək indeksli `DELETE`. YENİ cron YAZILMIR — mövcud
    # planlayıcıya bir sətir qeydiyyat (`NIGHTLY_BACKUP` naxışı).
    ("FACE_LOG_RETENTION", JobCadence.DAILY, JobWeight.LIGHT),
    ("FINE_EXPIRE_STALE", JobCadence.HOURLY, JobWeight.LIGHT),
    # M-5 — dual-control təsdiq müddəti. `HOURLY`: hədd DƏQİQƏ vahidlidir
    # (`DUAL_CONTROL_APPROVAL_TIMEOUT_MINUTES`, defolt 480), gündəlik icra
    # ən pis halda 24 saatlıq xəta verərdi. `LIGHT`: bir indeksli sorğu +
    # ləğv olunan sətir qədər yazı.
    ("DUAL_CONTROL_OVERRIDE_TIMEOUT", JobCadence.HOURLY, JobWeight.LIGHT),
    # #30 (kompas1.md Faza 6) — planlaşdırılmış icra xülasəsi. `DAILY`:
    # `JobCadence`-də `WEEKLY` yoxdur, "bu gün DUE-dur?" sualını use case-in
    # `run()`-u özü verir (bax `executive_digest.py::_due_window`).
    ("EXECUTIVE_DIGEST_RUN", JobCadence.DAILY, JobWeight.LIGHT),
    # Faza 3.9 — Drive kvota nəzarəti. `DriveQuotaMonitor` yazılıb və test
    # edilib, LAKİN onu çağıran yol yox idi: 90% xəbərdarlığı və avtomatik
    # `QUOTA_EXCEEDED` keçidi heç vaxt baş vermirdi. `DAILY`, çünki
    # təkrar-susma müddəti GÜN vahidlidir (`DRIVE_QUOTA_WARNING_COOLDOWN_DAYS`);
    # `LIGHT`, çünki iş bir HTTP sorğusu + ən çoxu iki `UPDATE`-dir.
    ("DRIVE_QUOTA_CHECK", JobCadence.DAILY, JobWeight.LIGHT),
    # DEEP-GAP OP-1 — ÜÇ İŞ YAZILMIŞDI, LAKİN QEYDİYYATDA YOX İDİ.
    #
    # `detect_absences`, `escalate_overdue` və `block_inactive_devices` use
    # case-lərdə mövcud, testli və sənədli metodlardır (sonuncu ikisi öz modul
    # başlığında «planlayıcı çağırır» yazır) — HEÇ BİRİ isə çağırılmırdı.
    # Ən ağırı birincisidir: davamiyyət hesabatı `unauthorized_absence`
    # sütununu OXUYUR, onu YAZAN yol isə yox idi, yəni qayıb heç vaxt qeydə
    # alınmırdı.
    #
    # `MORNING_ABSENCE_DETECTION` — `DAILY`: qərar GÜN sonunda verilir və iş
    # DÜNƏNKİ günü emal edir (gecə yarısından sonra «bu gün» hələ başlamayıb).
    # `TASK_OVERDUE_ESCALATION` — `HOURLY`: son tarix saat dəqiqliyindədir,
    # gündəlik dövrə eskalasiyanı 23 saata qədər gecikdirərdi
    # (`FINE_EXPIRE_STALE` ilə eyni əsaslandırma).
    # `DEVICE_INACTIVITY_BLOCK` — `DAILY`: passivlik həddi GÜN vahidlidir.
    # Üçü də `LIGHT`: indeksli sorğu + tapılan sətir qədər yazı; `HEAVY`
    # yalnız `pg_dump` üçün ayrılıb.
    ("MORNING_ABSENCE_DETECTION", JobCadence.DAILY, JobWeight.LIGHT),
    ("TASK_OVERDUE_ESCALATION", JobCadence.HOURLY, JobWeight.LIGHT),
    ("DEVICE_INACTIVITY_BLOCK", JobCadence.DAILY, JobWeight.LIGHT),
    # DEEP-GAP OP-4 — tarixi keçmiş açıq elanlar əbədi `OPEN` qalırdı: ekran
    # süzgəci onları gizlədir, LAKİN «neçə açıq elan var?» sualı hesabatda
    # ildən-ilə böyüyən yalan rəqəm verirdi. `DAILY`, çünki elanın vahidi
    # GÜNdür; `LIGHT`: indeksli sorğu + şərtli `UPDATE`.
    ("OPEN_SHIFT_EXPIRY", JobCadence.DAILY, JobWeight.LIGHT),
    # DEEP-GAP OP-2 — 45 dəqiqəlik təsdiq həddi KAĞIZ ÜZƏRİNDƏ qalmışdı:
    # `escalate_timeouts()` yazılıb, testlidir, LAKİN çağıran yol yox idi.
    # `HOURLY`: hədd DƏQİQƏ vahidlidir (`FINE_EXPIRE_STALE` ilə eyni
    # əsaslandırma); `LIGHT`: indeksli sorğu + tapılan sətir qədər yazı.
    # YALNIZ QAYIDIŞ tərəfi — giriş təsdiqinin imzası `operator_id` tələb
    # edir və planlayıcıda aktor yoxdur (bax `composition.py` başlığı).
    ("VERIFICATION_TIMEOUT_ESCALATION", JobCadence.HOURLY, JobWeight.LIGHT),
    # SAAS-6 — saxlama müddəti. İKİ cədvəl (sübut növbəsi + həll edilmiş
    # sinxronizasiya konfliktləri) İNDİYƏ QƏDƏR yalnız BÖYÜYÜRDÜ. `DAILY`:
    # müddət GÜN vahidlidir (`EVIDENCE_UPLOAD_RETENTION_DAYS`); `LIGHT`:
    # iki indeksli `DELETE`. TƏK iş, çünki hər ikisi EYNİ sualın cavabıdır
    # və EYNİ Root açarından oxuyur (bax `composition.py::_job_retention_purge`).
    ("RETENTION_PURGE", JobCadence.DAILY, JobWeight.LIGHT),
    # `v2backlog.md` Faza 3.1/3.2/3.3 — HR lifecycle-in ÜÇ gecəlik işi
    # (`composition.py::_register_scheduled_jobs` şərhi ilə EYNİ əsaslandırma:
    # `DAILY`+`LIGHT`, hər üçü GÜN vahidli tarix müqayisəsi + tapılan sətir
    # qədər UPDATE-dir, xarici proses yoxdur). Sonuncu ikisi (deaktivasiya,
    # anonimləşdirmə) HAZIRDA HƏMİŞƏ `0` qaytarır — oxuyucu portları hələ
    # heç bir repo-da implementasiya olunmayıb (`composition.py`-dakı «QAPI
    # SINIĞI» qeydi) — bu, planlayıcı QEYDİYYATININ ÖZÜNÜN natamamlığı deyil.
    ("TRANSFER_REQUEST_SCHEDULED_APPLY", JobCadence.DAILY, JobWeight.LIGHT),
    ("EMPLOYEE_SCHEDULED_DEACTIVATION_RUN", JobCadence.DAILY, JobWeight.LIGHT),
    ("FORMER_EMPLOYEE_ANONYMIZATION_RUN", JobCadence.DAILY, JobWeight.LIGHT),
    ("NIGHTLY_BACKUP", JobCadence.DAILY, JobWeight.HEAVY),
)


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _Report:
    """Use case hesabatlarının ortaq sahtəsi — `handler` yalnız sahələri oxuyur.

    Sahə tipi `Any`-dir, `int` deyil: #28-in il dönümü hesabatı GÜN sahələrini
    `Decimal` kimi daşıyır (`NUMERIC(5,2)` ilə eyni tip, bax
    `annual_leave_rules.py` başlığı) və onları `int`-ə salmaq sahtəni real
    hesabatdan ayırardı.
    """

    def __init__(self, **fields: Any) -> None:
        for name, value in fields.items():
            setattr(self, name, value)


class _RecordingUseCase:
    """Çağırılan metodun adını və arqumentlərini yığır."""

    def __init__(self, calls: list[tuple[str, dict[str, Any]]], *, result: Any) -> None:
        self._calls = calls
        self._result = result

    def _record(self, name: str, **kwargs: Any) -> Any:
        self._calls.append((name, kwargs))
        return self._result


class _Baselines(_RecordingUseCase):
    def recalculate_all(self, tenant_id: TenantId, *, now: datetime) -> Any:
        return self._record("behavior_baselines.recalculate_all", tenant_id=tenant_id, now=now)


class _Exceptions(_RecordingUseCase):
    def run(self, *, tenant_id: TenantId, now: datetime) -> Any:
        return self._record("exceptions.run", tenant_id=tenant_id, now=now)


class _StaffingPattern(_RecordingUseCase):
    def recalculate_for_store(
        self, tenant_id: TenantId, *, store_id: StoreId, now: datetime
    ) -> Any:
        return self._record(
            "staffing_pattern.recalculate_for_store",
            tenant_id=tenant_id,
            store_id=store_id,
            now=now,
        )


class _Documents(_RecordingUseCase):
    def notify_expiring_documents(self, tenant_id: TenantId) -> Any:
        return self._record("employee_documents.notify_expiring_documents", tenant_id=tenant_id)


class _Attrition(_RecordingUseCase):
    def recalculate_all(self, tenant_id: TenantId, *, now: datetime) -> Any:
        return self._record("attrition_risk.recalculate_all", tenant_id=tenant_id, now=now)


class _Appeals(_RecordingUseCase):
    def expire_stale(self, tenant_id: TenantId) -> Any:
        return self._record("fine_appeals.expire_stale", tenant_id=tenant_id)


class _LeaveVerification(_RecordingUseCase):
    """M-5 — təsdiqsiz qalmış vaxt düzəlişlərinin ləğvi (saatlıq iş)."""

    def expire_pending_overrides(self, tenant_id: TenantId) -> Any:
        return self._record("leave_verification.expire_pending_overrides", tenant_id=tenant_id)

    def escalate_timeouts(self, tenant_id: TenantId) -> Any:
        """DEEP-GAP OP-2 — 45 dəqiqəlik qayıdış həddi.

        İmza POZİSİYALIDIR (`escalate_timeouts(tenant_id)`) — sahtə də elə
        qəbul edir ki, həqiqi imza dəyişəndə test sükutla keçməsin.
        """
        return self._record("leave_verification.escalate_timeouts", tenant_id=tenant_id)


class _OpenShifts(_RecordingUseCase):
    """DEEP-GAP OP-4 — tarixi keçmiş elanların gecəlik təmizliyi.

    İmza POZİSİYALIDIR (`expire_stale_postings(tenant_id)`) — sahtə də elə
    qəbul edir ki, həqiqi imza dəyişəndə test sükutla keçməsin.
    """

    def expire_stale_postings(self, tenant_id: TenantId) -> Any:
        return self._record("open_shifts.expire_stale_postings", tenant_id=tenant_id)


class _MorningCheckIn(_RecordingUseCase):
    """DEEP-GAP OP-1 — «İcazəsiz Qayıb» təyinetməsi (gecəlik iş).

    İmza POZİSİYALIDIR (`detect_absences(tenant_id, work_date)`), ona görə
    sahtə də pozisiyalı qəbul edir: açar-sözlə çağırsaydıq, həqiqi imza
    dəyişəndə test SÜKUTLA keçməyə davam edərdi.
    """

    def escalate_timeouts_for_tenant(self, tenant_id: TenantId) -> Any:
        """DEEP-GAP OP-2 — 45 dəqiqəlik GİRİŞ həddi (aktorsuz imza).

        İmza POZİSİYALIDIR və `operator_id` QƏBUL ETMİR — köhnə,
        operator-əsaslı metodun sükutla işə düşmədiyini yalnız bu göstərir.
        """
        return self._record("morning_check_in.escalate_timeouts_for_tenant", tenant_id=tenant_id)

    def detect_absences(self, tenant_id: TenantId, work_date: Any) -> Any:
        return self._record(
            "morning_check_in.detect_absences", tenant_id=tenant_id, work_date=work_date
        )


class _Tasks(_RecordingUseCase):
    def escalate_overdue(self, *, tenant_id: TenantId) -> Any:
        return self._record("tasks.escalate_overdue", tenant_id=tenant_id)


class _TransferRequests(_RecordingUseCase):
    """`v2backlog.md` Faza 3.3 — planlaşdırılmış filiallar-arası köçürmə tətbiqi."""

    def apply_scheduled_transfers(self, tenant_id: TenantId) -> Any:
        return self._record("transfer_requests.apply_scheduled_transfers", tenant_id=tenant_id)


class _UserLifecycle(_RecordingUseCase):
    """`v2backlog.md` Faza 3.1/3.2 — `UserManagementUseCase`-in İKİ gecəlik metodu.

    `_composition.py::_job_scheduled_employee_deactivation`/`_job_former_
    employee_anonymization` HƏR İKİSİ `session.users`-ə müraciət edir — bu
    sahtə HƏR İKİ metodu daşıyır (`_TransferRequests` ilə fərqli, çünki
    real `UserManagementUseCase` da iki metodu EYNİ obyektdə saxlayır).
    """

    def deactivate_scheduled_employees(self, tenant_id: TenantId) -> Any:
        return self._record("users.deactivate_scheduled_employees", tenant_id=tenant_id)

    def anonymize_former_employees(self, tenant_id: TenantId) -> Any:
        return self._record("users.anonymize_former_employees", tenant_id=tenant_id)


class _Devices(_RecordingUseCase):
    def block_inactive_devices(self, *, tenant_id: TenantId) -> Any:
        return self._record("devices.block_inactive_devices", tenant_id=tenant_id)


class _FieldReports(_RecordingUseCase):
    def notify_overdue_audits(self, tenant_id: TenantId) -> Any:
        return self._record("field_reports.notify_overdue_audits", tenant_id=tenant_id)


class _AnnualLeave(_RecordingUseCase):
    def run_year_rollover(self, *, tenant_id: TenantId, now: datetime) -> Any:
        return self._record("annual_leave.run_year_rollover", tenant_id=tenant_id, now=now)


class _SupportInbox(_RecordingUseCase):
    def run_maintenance(self, *, tenant_id: TenantId, now: datetime) -> Any:
        return self._record("support_inbox.run_maintenance", tenant_id=tenant_id, now=now)


class _ExecutiveDigest(_RecordingUseCase):
    def run(self, *, tenant_id: TenantId, now: datetime, scheduled_for: datetime) -> Any:
        return self._record(
            "executive_digest.run", tenant_id=tenant_id, now=now, scheduled_for=scheduled_for
        )


class _FaceExemptions(_RecordingUseCase):
    """`facecontrol.md` bənd 14 — istisnaların müddət-bitməsi (gecəlik iş)."""

    def expire_due(self, *, tenant_id: TenantId, now: datetime) -> Any:
        return self._record("face_exemptions.expire_due", tenant_id=tenant_id, now=now)


class _FaceLogRetention(_RecordingUseCase):
    """`facecontrol.md` bənd 17 — jurnalın saxlama müddəti təmizləməsi."""

    def purge(self, *, tenant_id: TenantId, now: datetime) -> Any:
        return self._record("face_log_retention.purge", tenant_id=tenant_id, now=now)


class _Benchmark:
    """`active_stores()` — kadr nümunəsi işinin mağaza siyahısı mənbəyi."""

    def __init__(self, stores: dict[StoreId, str]) -> None:
        self.stores = stores

    def active_stores(self, tenant_id: TenantId) -> dict[StoreId, str]:
        return dict(self.stores)


class _SyncConflicts:
    """SAAS-6 — `purge_resolved` sahtəsi (həll edilmiş konfliktlərin təmizliyi)."""

    def __init__(self) -> None:
        self.cutoffs: list[Any] = []

    def purge_resolved(self, *, cutoff: Any) -> int:
        self.cutoffs.append(cutoff)
        return 4


class _EvidenceQueue:
    """SAAS-6 — `purge_uploaded` sahtəsi (yüklənmiş sətirlərin təmizliyi)."""

    def __init__(self) -> None:
        self.cutoffs: list[Any] = []

    def purge_uploaded(self, *, older_than: Any) -> int:
        self.cutoffs.append(older_than)
        return 7


class _SessionLimits:
    """`session.limits.get_int` — iş saxlama müddətini ROOT-dan oxuyur.

    Sahtə HƏMİŞƏ fallback-i qaytarır (`DEFAULT_LIMITS`): testin ölçdüyü şey
    dəyərin ÖZÜ deyil, işin həmin açarı OXUMASI və kəsim anını ondan
    hesablamasıdır.
    """

    def __init__(self) -> None:
        self.keys: list[str] = []

    def get_int(self, _tenant_id: Any, key: str, fallback: int) -> int:
        self.keys.append(key)
        return fallback


class _SessionUow:
    def __init__(self, benchmark: _Benchmark, sync_conflicts: _SyncConflicts) -> None:
        self._benchmark = benchmark
        self._sync_conflicts = sync_conflicts

    def repository(self, name: str) -> Any:
        if name == "multi_store_benchmark":
            return self._benchmark
        if name == "sync_conflicts":
            return self._sync_conflicts
        raise KeyError(name)  # pragma: no cover - testdə başqa repo istənmir


class _FakeSession:
    """`Session` əvəzi — YALNIZ planlaşdırılmış işlərin toxunduğu sahələr."""

    def __init__(self, calls: list[tuple[str, dict[str, Any]]]) -> None:
        self.calls = calls
        self.commits = 0
        self.tenant_id = TENANT
        self.behavior_baselines = _Baselines(calls, result=_Report(employees_updated=235))
        self.exceptions = _Exceptions(
            calls, result=_Report(evaluated_rules=2, created_total=4, duplicate_total=1)
        )
        self.staffing_pattern = _StaffingPattern(calls, result=_Report(weekdays_updated=7))
        self.employee_documents = _Documents(calls, result=3)
        self.attrition_risk = _Attrition(
            calls,
            result=_Report(employees_updated=235, high_risk_count=4, notifications_sent=2),
        )
        self.fine_appeals = _Appeals(calls, result=5)
        self.leave_verification = _LeaveVerification(calls, result=2)
        # DEEP-GAP OP-4 — tarixi keçmiş elanların bağlanması.
        self.open_shifts = _OpenShifts(calls, result=3)
        self.field_reports = _FieldReports(calls, result=_Report(checked=2, overdue_count=1))
        # DEEP-GAP OP-1 — üç yeni iş üçün sahtələr.
        self.morning_check_in = _MorningCheckIn(calls, result=3)
        self.tasks = _Tasks(calls, result=_Report(escalated=2))
        self.devices = _Devices(calls, result=[object(), object()])
        # #28 — hesabat sahələri `_job_annual_leave_rollover`-in oxuduqları:
        # il, yazılan balans sayı, köçürülən və itən gün.
        self.annual_leave = _AnnualLeave(
            calls,
            result=_Report(
                year=2026,
                balances_written=235,
                carried_over_days=Decimal("412.50"),
                forfeited_days=Decimal("18.00"),
            ),
        )
        # CHAT-1 — iş `closed`/`reminded` açarlarını oxuyur, ona görə
        # nəticə SÖZLÜKdür (`_Report` deyil).
        self.support_inbox = _SupportInbox(calls, result={"closed": 2, "reminded": 1})
        self.executive_digest = _ExecutiveDigest(calls, result=_Report(evaluated=3, sent=2))
        # Face Control (facecontrol.md Faza 2) — hər ikisi SADƏ ədəd qaytarır
        # (bitən istisna sayı / silinən jurnal sətri), ona görə `_Report`
        # örtüyü lazım deyil.
        self.face_exemptions = _FaceExemptions(calls, result=2)
        self.face_log_retention = _FaceLogRetention(calls, result=140)
        # `v2backlog.md` Faza 3.1/3.2/3.3 — HR lifecycle-in ÜÇ gecəlik işi.
        self.transfer_requests = _TransferRequests(calls, result=1)
        self.users = _UserLifecycle(calls, result=0)
        # SAAS-6 — saxlama müddəti işi: limit oxusu + iki təmizləmə çağırışı.
        self.limits = _SessionLimits()
        self.evidence_queue = _EvidenceQueue()
        self.sync_conflicts = _SyncConflicts()
        self.uow = _SessionUow(
            _Benchmark({STORE_A: "Mağaza A", STORE_B: "Mağaza B"}), self.sync_conflicts
        )

    def max_upload_bytes(self) -> int:
        """Drive kvota işi fabriki ROOT həddi ilə qurur (`run_evidence_uploads` naxışı)."""
        return 5 * 1024 * 1024

    def commit(self) -> None:
        self.commits += 1

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _job_handler_session_call_sites(source: str) -> set[tuple[str, str]]:
    """`_job_*` metodlarının gövdəsindəki `session.<sahə>.<metod>(...)` cütləri.

    `test_field_report_screen.py`-dəki EYNİ naxış (bax həmin faylın modul-
    səviyyəli şərhi) — Protokolun/`Session`-un TAM səthi YOX, `_job_*`
    metodlarının FAKTİKİ çağırdığı cütlər. `composition.py`-da `session`
    dəyişən adı SABİTDİR (`with self.session() as session:`), ona görə
    əsas adı `"session"` ilə məhdudlaşdırmaq TƏHLÜKƏSİZDİR.
    """
    tree = ast.parse(source)
    calls: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name.startswith("_job_")):
            continue
        for call_node in ast.walk(node):
            if not isinstance(call_node, ast.Call):
                continue
            func = call_node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Attribute)
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id == "session"
            ):
                calls.add((func.value.attr, func.attr))
    return calls


def test_the_fake_session_implements_every_field_and_method_the_job_handlers_actually_call() -> (
    None
):
    """Bu gün İKİNCİ dəfə eyni qüsur sinfi: `composition.py`-a YENİ iş (`transfer_
    requests`/`users`) bağlandı, `_FakeSession`-da həmin SAHƏLƏR yox idi —
    `AttributeError`. `test_field_report_screen.py`-dəki EYNİ qapı naxışı,
    LAKİN İKİ SƏVİYYƏLİ (əvvəlcə `session.<sahə>`, sonra `<sahə>.<metod>`),
    çünki `_FakeSession` TƏK use case yox, BÜTÜN sessiya obyekt qrafını
    təqlid edir.
    """
    source = inspect.getsource(ApplicationContext)
    called = _job_handler_session_call_sites(source)
    session = _FakeSession([])

    missing_field = sorted({field for field, _method in called if not hasattr(session, field)})
    assert missing_field == [], (
        f"`_job_*` metodları `session.<sahə>` çağırır, lakin `_FakeSession`-da "
        f"bu sahələr YOXDUR: {missing_field}."
    )

    missing_method = sorted(
        f"{field}.{method}"
        for field, method in called
        if hasattr(session, field) and not hasattr(getattr(session, field), method)
    )
    assert missing_method == [], (
        f"`_job_*` metodları bu metodları çağırır, lakin `_FakeSession`-ın "
        f"sahtələrində YOXDUR: {missing_method}."
    )


class _FakeUow:
    """`PostgresUnitOfWork` əvəzi — limit repo-su və audit yazıcısı."""

    def __init__(self, limits: FakeSystemLimits, audit: RecordingAudit) -> None:
        self._limits = limits
        self.audit = audit
        self.committed = False

    def repository(self, name: str) -> Any:
        if name == "limits":
            return self._limits
        raise KeyError(name)  # pragma: no cover - başqa repo istənmir

    def commit(self) -> None:
        self.committed = True

    def __enter__(self) -> _FakeUow:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _FakeDatabase:
    """`Database` əvəzi — YALNIZ bağlantı qatını əvəzləyir.

    `_StandaloneLimits`/`_StandaloneAudit` körpüləri HƏQİQİ kodla işləyir:
    testlər onların qısa iş vahidi açıb commit etdiyini də ölçə bilir.
    """

    def __init__(self, limits: FakeSystemLimits, audit: RecordingAudit) -> None:
        self.limits = limits
        self.audit = audit
        self.opened: list[_FakeUow] = []

    def unit_of_work(self, tenant_id: TenantId, *, user_id: Any = None) -> _FakeUow:
        uow = _FakeUow(self.limits, self.audit)
        self.opened.append(uow)
        return uow


class _InMemoryRuns:
    """`ScheduledJobRepository` — icarə HƏMİŞƏ verilir (yarış nüvədə test olunub)."""

    def __init__(self) -> None:
        self.acquired: list[str] = []
        self.succeeded: list[tuple[str, str | None]] = []
        self.failed: list[tuple[str, str]] = []

    def acquire(self, *, job_key: str, **_: Any) -> bool:
        self.acquired.append(job_key)
        return True

    def mark_succeeded(self, *, job_key: str, result_detail: str | None = None, **_: Any) -> bool:
        self.succeeded.append((job_key, result_detail))
        return True

    def mark_failed(self, *, job_key: str, error: str, **_: Any) -> bool:
        self.failed.append((job_key, error))
        return True


class _FakeDriveConnection:
    """`drive_connections` sətrinin monitorun oxuduğu hissəsi."""

    def __init__(self, *, warning_sent_at: datetime | None = None) -> None:
        self.id = uuid.uuid4()
        self.google_account_email = "kompas@example.com"
        self.quota_warning_sent_at = warning_sent_at


class _FakeDriveConnections:
    """`DriveConnectionRepository` əvəzi — aktiv bağlantı və yazılar."""

    def __init__(self, connection: _FakeDriveConnection | None) -> None:
        self._connection = connection
        self.quota_updates: list[tuple[Any, bool]] = []
        self.warning_marked = 0
        self.errors: list[str] = []

    def get_active(self) -> _FakeDriveConnection | None:
        return self._connection

    def update_quota(
        self, connection_id: Any, quota: Any, *, now: Any = None, mark_exceeded: bool = False
    ) -> None:
        self.quota_updates.append((quota, mark_exceeded))

    def mark_quota_warning_sent(self, connection_id: Any, *, now: Any = None) -> None:
        self.warning_marked += 1

    def record_error(self, connection_id: Any, message: str) -> None:
        self.errors.append(message)


class _FakeDriveFactory:
    """`DriveProviderFactory` əvəzi — yalnız `quota()` lazımdır."""

    def __init__(self, quota: Any, *, error: Exception | None = None) -> None:
        self._quota = quota
        self._error = error
        self.max_upload_bytes: int | None = None

    def for_connection(self, connection_id: Any) -> _FakeDriveFactory:
        return self

    def quota(self) -> Any:
        if self._error is not None:
            raise self._error
        return self._quota


class _FakeBackupService:
    """`NightlyBackupService` əvəzi — `pg_dump` çağırmadan `create`/`prune`."""

    #: Qurulan nüsxələr — GUI yolunun xidməti ÜMUMİYYƏTLƏ qurmadığını
    #: yoxlamaq üçün sinif səviyyəsindədir (`ClassVar`, hər testdə təmizlənir).
    instances: ClassVar[list[_FakeBackupService]] = []

    def __init__(self, database: Any, *, limits: Any) -> None:
        self.database = database
        self.limits = limits
        self.created: list[TenantId] = []
        self.pruned: list[TenantId] = []
        _FakeBackupService.instances.append(self)

    def create(self, tenant_id: TenantId) -> Any:
        self.created.append(tenant_id)
        return _Report(size_bytes=4096)

    def prune(self, tenant_id: TenantId) -> int:
        self.pruned.append(tenant_id)
        return 2


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _context(
    *,
    limits: FakeSystemLimits | None = None,
    audit: RecordingAudit | None = None,
    session: _FakeSession | None = None,
) -> tuple[ApplicationContext, _FakeSession, _FakeDatabase]:
    """Həqiqi `ApplicationContext`, sahtə bağlantı və sahtə sessiya ilə."""
    database = _FakeDatabase(limits or FakeSystemLimits(), audit or RecordingAudit())
    context = ApplicationContext(database=database, tenant_id=TENANT)  # type: ignore[arg-type]
    fake_session = session or _FakeSession([])

    def _open_session(**_: Any) -> _FakeSession:
        return fake_session

    # Sessiya AÇIQ şəkildə əvəzlənir: işlərin hər biri ÖZ sessiyasını açır və
    # test məhz hansı use case metodunun çağırıldığını ölçür.
    context.session = _open_session  # type: ignore[method-assign, assignment]
    # SAAS-6 — `RETENTION_PURGE` LOKAL SQLite növbəsinə də toxunur; sahtəsiz
    # iş real faylı açmağa çalışardı (test mühitində yan təsir).
    context.evidence_queue = lambda: fake_session.evidence_queue  # type: ignore[method-assign, assignment]
    return context, fake_session, database


def _runner(
    context: ApplicationContext, database: _FakeDatabase
) -> tuple[JobRunner, _InMemoryRuns]:
    runs = _InMemoryRuns()
    runner = JobRunner(
        runs=runs,  # type: ignore[arg-type]
        limits=database.limits,  # type: ignore[arg-type]
        audit=database.audit,  # type: ignore[arg-type]
        clock=FakeClock(NOW),
        instance_id="TEST-TERMINAL#1",
    )
    context._register_scheduled_jobs(runner)
    return runner, runs


def _job_context(job_key: str) -> JobExecutionContext:
    return JobExecutionContext(tenant_id=TENANT, job_key=job_key, scheduled_for=NOW, now=NOW)


# --------------------------------------------------------------------------- #
# 1. QEYDİYYAT VƏ SIRA
# --------------------------------------------------------------------------- #


def test_all_scheduled_jobs_are_registered_with_the_expected_weight_and_cadence() -> None:
    """Yeddi iş, gözlənilən ritm və çəki ilə — cədvəl testdə ƏL İLƏ yazılıb."""
    context, _session, database = _context()
    runner, _runs = _runner(context, database)

    registered = [(job.key, job.cadence, job.weight) for job in runner._registry]

    assert registered == list(EXPECTED_JOBS)


def test_the_behaviour_baseline_is_registered_before_the_exception_engine() -> None:
    """SIRA İŞ QAYDASIDIR: motor baz xəttini oxuyur.

    Tərsinə olsaydı, motor həmişə DÜNƏNKİ baz xətti ilə müqayisə edərdi və hər
    anomaliya bir gün gecikərdi — istisna yenə yaranır, ona görə səhv testsiz
    görünməz qalardı.
    """
    context, _session, database = _context()
    runner, _runs = _runner(context, database)

    keys = list(runner.registered_jobs)

    assert keys.index("BEHAVIOR_BASELINE_RECALC") < keys.index("EXCEPTION_ENGINE_RUN")


def test_only_the_nightly_backup_is_heavy() -> None:
    """Ağır iş TƏKDİR — qalanları GUI axınında da işləyə bilməlidir."""
    context, _session, database = _context()
    runner, _runs = _runner(context, database)

    heavy = [job.key for job in runner._registry if job.is_heavy]

    assert heavy == ["NIGHTLY_BACKUP"]


def test_the_runner_is_a_single_instance_per_context() -> None:
    """İki nüsxə iki `instance_id` demək olardı — proses öz icarəsini itirərdi."""
    context, _session, _database = _context()

    assert context.job_runner() is context.job_runner()


# --------------------------------------------------------------------------- #
# 2. HƏR HANDLER ÖZ USE CASE METODUNU ÇAĞIRIR
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("job_key", "expected_call"),
    [
        ("BEHAVIOR_BASELINE_RECALC", "behavior_baselines.recalculate_all"),
        ("EXCEPTION_ENGINE_RUN", "exceptions.run"),
        ("EMPLOYEE_DOCUMENT_EXPIRY_NOTICE", "employee_documents.notify_expiring_documents"),
        ("ATTRITION_RISK_RECALC", "attrition_risk.recalculate_all"),
        ("ANNUAL_LEAVE_YEAR_ROLLOVER", "annual_leave.run_year_rollover"),
        ("SUPPORT_STATUS_MAINTENANCE", "support_inbox.run_maintenance"),
        ("FINE_EXPIRE_STALE", "fine_appeals.expire_stale"),
        ("DUAL_CONTROL_OVERRIDE_TIMEOUT", "leave_verification.expire_pending_overrides"),
        ("MORNING_ABSENCE_DETECTION", "morning_check_in.detect_absences"),
        ("TASK_OVERDUE_ESCALATION", "tasks.escalate_overdue"),
        ("DEVICE_INACTIVITY_BLOCK", "devices.block_inactive_devices"),
        ("EXECUTIVE_DIGEST_RUN", "executive_digest.run"),
    ],
)
def test_each_handler_calls_its_use_case_method(job_key: str, expected_call: str) -> None:
    """Reyestrdə adı olan, lakin heç nə etməyən "boş" iş olmamalıdır."""
    calls: list[tuple[str, dict[str, Any]]] = []
    context, session, database = _context(session=_FakeSession(calls))
    runner, _runs = _runner(context, database)

    job = runner._registry.get(job_key)
    assert job is not None
    detail = job.handler(_job_context(job_key))

    assert [name for name, _ in calls] == [expected_call]
    assert calls[0][1]["tenant_id"] == TENANT
    assert session.commits == 1, "Hər iş öz sessiyasını COMMIT etməlidir"
    assert detail, "Sağlamlıq ekranı üçün xülasə qaytarılmalıdır"


# --------------------------------------------------------------------------- #
# 2.1. DRIVE KVOTA NƏZARƏTİ (Faza 3.9) — job HEÇ VAXT işə düşmürdü
#
# Monitor sinfi yazılıb, test edilib və ixrac olunub, lakin onu ÇAĞIRAN yol yox
# idi: 90% xəbərdarlığı və avtomatik `ACTIVE → QUOTA_EXCEEDED` keçidi baş
# vermirdi. Drive-ın dolduğunu bildirən ilk siqnal növbəti yükləmənin
# `DriveQuotaExceededError` ilə çökməsi idi — söhbət cərimə SÜBUT şəkillərindən,
# yəni mübahisə halında cərimənin yeganə əsaslandırmasından gedir.
# --------------------------------------------------------------------------- #


def _quota_job(context: ApplicationContext, database: _FakeDatabase) -> Any:
    runner, _runs = _runner(context, database)
    job = runner._registry.get("DRIVE_QUOTA_CHECK")
    assert job is not None, "Kvota işi reyestrdə OLMALIDIR"
    return job


def _patch_drive(
    monkeypatch: pytest.MonkeyPatch,
    context: ApplicationContext,
    *,
    factory: _FakeDriveFactory | None,
    repository: _FakeDriveConnections | None = None,
) -> tuple[_FakeDriveConnections, RecordingNotifier]:
    """Drive qatını əvəzləyir; monitorun ÖZÜ həqiqi qalır (hədd məntiqi ölçülür)."""
    from src.infrastructure.notifications import notifier as notifier_module
    from src.infrastructure.storage import connections as connections_module

    connections = repository or _FakeDriveConnections(_FakeDriveConnection())
    notifier = RecordingNotifier()
    monkeypatch.setattr(
        connections_module, "DriveConnectionRepository", lambda database, tenant_id: connections
    )
    monkeypatch.setattr(notifier_module, "PostgresNotifier", lambda database, *, limits: notifier)
    monkeypatch.setattr(
        context,
        "drive_providers",
        lambda *, max_upload_bytes: factory,
    )
    return connections, notifier


def test_the_drive_quota_job_is_silent_when_drive_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Google açarları boşdursa iş SAKİT dayanır — istisna ATMIR.

    `.env.example`: `KOMPASOS_GOOGLE_CLIENT_ID/_SECRET` boş qala bilər və
    cərimələr normal yaranır. İstisna atsaydıq, Drive işlətməyən quraşdırmada
    gecəlik hesabat HƏR GÜN `FAILED` göstərərdi və əsl nasazlıqlar itərdi.
    """
    context, _session, database = _context()
    _patch_drive(monkeypatch, context, factory=None)

    detail = _quota_job(context, database).handler(_job_context("DRIVE_QUOTA_CHECK"))

    assert "konfiqurasiya edilməyib" in detail


def test_the_drive_quota_job_warns_once_the_root_threshold_is_crossed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """95% > `DRIVE_QUOTA_WARNING_RATIO` (0.90) → Root/CEO-ya xəbərdarlıq."""
    from src.domain.value_objects.storage import QuotaStatus

    context, _session, database = _context()
    connections, notifier = _patch_drive(
        monkeypatch,
        context,
        factory=_FakeDriveFactory(QuotaStatus(used_bytes=95, total_bytes=100)),
    )

    detail = _quota_job(context, database).handler(_job_context("DRIVE_QUOTA_CHECK"))

    assert len(notifier.messages) == 1
    assert notifier.messages[0]["category"] == "DRIVE_QUOTA"
    assert notifier.messages[0]["recipient_id"] is None, "Bildiriş TENANT səviyyəsindədir"
    assert connections.warning_marked == 1, "Təkrar xəbərdarlıq üçün an yazılmalıdır"
    assert "xəbərdarlıq göndərildi" in detail


def test_the_drive_quota_job_does_not_warn_below_the_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """89% < 90% — SƏRHƏD ALTINDA xəbərdarlıq YOXDUR (alarm yorğunluğu)."""
    from src.domain.value_objects.storage import QuotaStatus

    context, _session, database = _context()
    connections, notifier = _patch_drive(
        monkeypatch,
        context,
        factory=_FakeDriveFactory(QuotaStatus(used_bytes=89, total_bytes=100)),
    )

    detail = _quota_job(context, database).handler(_job_context("DRIVE_QUOTA_CHECK"))

    assert notifier.messages == []
    assert connections.warning_marked == 0
    assert connections.quota_updates[0][1] is False, "Dolu deyil — status DƏYİŞMİR"
    assert "kvota 89%" in detail


def test_the_drive_quota_job_marks_the_connection_as_exceeded_when_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """100% → `ACTIVE → QUOTA_EXCEEDED` + kritik bildiriş."""
    from src.domain.value_objects.storage import QuotaStatus

    context, _session, database = _context()
    connections, notifier = _patch_drive(
        monkeypatch,
        context,
        factory=_FakeDriveFactory(QuotaStatus(used_bytes=100, total_bytes=100)),
    )

    detail = _quota_job(context, database).handler(_job_context("DRIVE_QUOTA_CHECK"))

    assert connections.quota_updates[0][1] is True
    assert notifier.messages[0]["is_critical"] is True
    assert "QUOTA_EXCEEDED" in detail


def test_the_drive_quota_job_survives_a_network_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Şəbəkə/token nasazlığı işi ÇÖKDÜRMÜR — səbəb bağlantı sətrinə yazılır."""
    context, _session, database = _context()
    connections, notifier = _patch_drive(
        monkeypatch,
        context,
        factory=_FakeDriveFactory(None, error=RuntimeError("şəbəkə yoxdur")),
    )

    detail = _quota_job(context, database).handler(_job_context("DRIVE_QUOTA_CHECK"))

    assert "Kvota oxunmadı" in detail
    assert connections.errors, "Səbəb `drive_connections.last_error`-a yazılmalıdır"
    assert notifier.messages == []


def test_the_drive_quota_job_is_quiet_without_an_active_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hesab hələ qoşulmayıbsa yoxlanacaq bir şey yoxdur — xəta DEYİL."""
    context, _session, database = _context()
    _connections, notifier = _patch_drive(
        monkeypatch,
        context,
        factory=_FakeDriveFactory(None),
        repository=_FakeDriveConnections(None),
    )

    detail = _quota_job(context, database).handler(_job_context("DRIVE_QUOTA_CHECK"))

    assert "Aktiv Drive bağlantısı yoxdur" in detail
    assert notifier.messages == []


def test_the_staffing_pattern_job_covers_every_active_store() -> None:
    """Kadr nümunəsi MAĞAZA-səviyyəlidir — siyahı aktiv mağazalardan gəlir."""
    calls: list[tuple[str, dict[str, Any]]] = []
    context, session, database = _context(session=_FakeSession(calls))
    runner, _runs = _runner(context, database)

    job = runner._registry.get("STAFFING_PATTERN_REFRESH")
    assert job is not None
    detail = job.handler(_job_context("STAFFING_PATTERN_REFRESH"))

    assert [name for name, _ in calls] == [
        "staffing_pattern.recalculate_for_store",
        "staffing_pattern.recalculate_for_store",
    ]
    assert {call[1]["store_id"] for call in calls} == {STORE_A, STORE_B}
    assert "2 mağaza" in detail
    assert session.commits == 1


def test_the_handlers_use_the_scheduler_clock_not_wall_time() -> None:
    """Gecikmiş icrada hesablama FAKTİKİ ana bağlanır — `datetime.now()` YOX."""
    calls: list[tuple[str, dict[str, Any]]] = []
    context, _session, database = _context(session=_FakeSession(calls))
    runner, _runs = _runner(context, database)
    moment = NOW + timedelta(hours=6)

    job = runner._registry.get("BEHAVIOR_BASELINE_RECALC")
    assert job is not None
    job.handler(
        JobExecutionContext(
            tenant_id=TENANT,
            job_key="BEHAVIOR_BASELINE_RECALC",
            scheduled_for=NOW,
            now=moment,
        )
    )

    assert calls[0][1]["now"] == moment


def test_the_backup_job_creates_and_then_prunes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nüsxə ƏVVƏL yaradılır, təmizlik SONRA — tərsi son işlək nüsxəni riskə atardı."""
    import src.infrastructure.backup.service as backup_module

    _FakeBackupService.instances.clear()
    monkeypatch.setattr(backup_module, "NightlyBackupService", _FakeBackupService)
    context, _session, database = _context()
    runner, _runs = _runner(context, database)

    job = runner._registry.get("NIGHTLY_BACKUP")
    assert job is not None
    detail = job.handler(_job_context("NIGHTLY_BACKUP"))

    service = _FakeBackupService.instances[-1]
    assert service.created == [TENANT]
    assert service.pruned == [TENANT]
    assert "4096" in detail


# --------------------------------------------------------------------------- #
# 3. İKİ GİRİŞ NÖQTƏSİ — GUI ATLAYIR, CLI İCRA EDİR
# --------------------------------------------------------------------------- #


def test_the_gui_path_skips_the_heavy_backup(monkeypatch: pytest.MonkeyPatch) -> None:
    """`include_heavy=False`: `pg_dump` GUI axınında İCRA OLUNMUR."""
    import src.infrastructure.backup.service as backup_module

    _FakeBackupService.instances.clear()
    monkeypatch.setattr(backup_module, "NightlyBackupService", _FakeBackupService)
    calls: list[tuple[str, dict[str, Any]]] = []
    context, _session, database = _context(session=_FakeSession(calls))
    runner, runs = _runner(context, database)

    report = runner.run_due(tenant_id=TENANT, include_heavy=False)

    assert report.skipped_heavy == ("NIGHTLY_BACKUP",)
    assert _FakeBackupService.instances == [], "GUI yolu ehtiyat nüsxə xidmətini QURMAMALIDIR"
    # Atlanan iş İCARƏ də götürmür — əks halda CLI onu "tamamlanmış" sayardı.
    assert "NIGHTLY_BACKUP" not in runs.acquired


def test_the_cli_path_executes_the_heavy_backup(monkeypatch: pytest.MonkeyPatch) -> None:
    """`include_heavy=True`: eyni reyestr, lakin ağır iş də işləyir."""
    import src.infrastructure.backup.service as backup_module

    _FakeBackupService.instances.clear()
    monkeypatch.setattr(backup_module, "NightlyBackupService", _FakeBackupService)
    calls: list[tuple[str, dict[str, Any]]] = []
    context, _session, database = _context(session=_FakeSession(calls))
    runner, runs = _runner(context, database)

    report = runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert report.skipped_heavy == ()
    assert report.succeeded == len(EXPECTED_JOBS)
    assert _FakeBackupService.instances[-1].created == [TENANT]
    assert runs.acquired == [key for key, _c, _w in EXPECTED_JOBS]


def test_the_aggregate_audit_row_is_written_through_the_standalone_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit körpüsü öz QISA tranzaksiyasını açır və COMMIT edir."""
    import src.infrastructure.backup.service as backup_module

    monkeypatch.setattr(backup_module, "NightlyBackupService", _FakeBackupService)
    audit = RecordingAudit()
    context, _session, database = _context(audit=audit)
    from src.presentation.composition import _StandaloneAudit

    runner = JobRunner(
        runs=_InMemoryRuns(),  # type: ignore[arg-type]
        limits=database.limits,  # type: ignore[arg-type]
        audit=_StandaloneAudit(database),  # type: ignore[arg-type]
        clock=FakeClock(NOW),
        instance_id="TEST-TERMINAL#1",
    )
    context._register_scheduled_jobs(runner)

    runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert audit.actions() == ["SCHEDULED_JOBS_EXECUTED"]
    assert audit.entries[0]["actor_id"] is None
    assert any(uow.committed for uow in database.opened), "Audit sətri commit olunmadı"


# --------------------------------------------------------------------------- #
# 4. QİSMƏN UĞUR — BİR İŞ QALANLARI DAYANDIRMIR
# --------------------------------------------------------------------------- #


def test_one_failing_job_does_not_stop_the_registered_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ehtiyat nüsxə çöksə də qalan altı iş İCRA OLUNUR."""

    class _BrokenBackup(_FakeBackupService):
        def create(self, tenant_id: TenantId) -> Any:
            raise RuntimeError("pg_dump tapılmadı")

    import src.infrastructure.backup.service as backup_module

    monkeypatch.setattr(backup_module, "NightlyBackupService", _BrokenBackup)
    calls: list[tuple[str, dict[str, Any]]] = []
    context, _session, database = _context(session=_FakeSession(calls))
    runner, runs = _runner(context, database)

    report = runner.run_due(tenant_id=TENANT, include_heavy=True)

    assert report.failed_jobs == ("NIGHTLY_BACKUP",)
    assert report.succeeded == len(EXPECTED_JOBS) - 1
    assert runs.failed[0][0] == "NIGHTLY_BACKUP"
    assert "pg_dump tapılmadı" in runs.failed[0][1]


# --------------------------------------------------------------------------- #
# 5. QTIMER İNTERVALI — ROOT-DAN, SABİT DEYİL
# --------------------------------------------------------------------------- #


def test_the_timer_interval_follows_the_root_limit() -> None:
    """Root dəyəri dəyişəndə `QTimer` intervalı da dəyişir."""
    from src.presentation.app import KompasApplication

    limits = FakeSystemLimits()
    context, _session, _database = _context(limits=limits)

    class _Stub:
        """Metod üçün minimal `self` — Qt tələb etmir."""

        _context = context

    read = KompasApplication._scheduler_poll_interval_ms
    default_minutes = int(DEFAULT_LIMITS[SystemLimitKey.SCHEDULER_POLL_INTERVAL_MINUTES])
    assert read(_Stub()) == default_minutes * 60 * 1000  # type: ignore[arg-type]

    limits.set(SystemLimitKey.SCHEDULER_POLL_INTERVAL_MINUTES, "45")
    assert read(_Stub()) == 45 * 60 * 1000  # type: ignore[arg-type]

    # `0` dövrəni fasiləsiz işlədərdi — nüvədəki alt hədd (1 dəq.) bağlayır.
    limits.set(SystemLimitKey.SCHEDULER_POLL_INTERVAL_MINUTES, "0")
    assert read(_Stub()) == 60_000  # type: ignore[arg-type]


def test_the_timer_interval_falls_back_without_a_context() -> None:
    """Önizləmə/dizayn rejimində kontekst yoxdur — sabit ritm işləyir."""
    from src.presentation.app import (
        FALLBACK_SCHEDULER_POLL_INTERVAL_MS,
        KompasApplication,
    )

    class _Stub:
        _context = None

    assert (
        KompasApplication._scheduler_poll_interval_ms(_Stub())  # type: ignore[arg-type]
        == FALLBACK_SCHEDULER_POLL_INTERVAL_MS
    )


def test_a_cycle_failure_never_reaches_the_gui() -> None:
    """Fon dövrəsinin istisnası pəncərəni ÇÖKDÜRMÜR — udulur və loglanır."""
    from src.presentation.app import KompasApplication

    class _BrokenContext:
        def run_scheduled_jobs(self, *, include_heavy: bool) -> Any:
            raise RuntimeError("baza əlçatmazdır")

    class _Stub:
        _context = _BrokenContext()

    # İstisna atılsaydı Qt hadisə dövrəsi onu tutmadan tətbiqi bağlayardı.
    KompasApplication._run_scheduled_jobs(_Stub())  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 6. CLI ÇIXIŞ KODU
# --------------------------------------------------------------------------- #


def _report(*, failed: bool) -> SchedulerRunReport:
    outcomes = (
        JobOutcome(
            job_key="BEHAVIOR_BASELINE_RECALC",
            scheduled_for=NOW,
            state=JobOutcomeState.SUCCEEDED,
            detail="235 işçi",
        ),
        JobOutcome(
            job_key="NIGHTLY_BACKUP",
            scheduled_for=NOW,
            state=JobOutcomeState.FAILED if failed else JobOutcomeState.SUCCEEDED,
            error_az="İş icra edilə bilmədi: pg_dump yoxdur" if failed else None,
        ),
    )
    return SchedulerRunReport(
        tenant_id=TENANT, started_at=NOW, include_heavy=True, outcomes=outcomes
    )


class _CliContext:
    def __init__(self, report: SchedulerRunReport) -> None:
        self.report = report
        self.calls: list[bool] = []

    def run_scheduled_jobs(self, *, include_heavy: bool) -> SchedulerRunReport:
        self.calls.append(include_heavy)
        return self.report


def _patch_build_context(monkeypatch: pytest.MonkeyPatch, context: _CliContext) -> None:
    import src.presentation.composition as composition_module

    monkeypatch.setattr(composition_module, "build_context", lambda **_: context)


def test_the_cli_returns_zero_when_every_job_succeeds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Uğurlu gecə → çıxış kodu 0 və oxunaqlı stdout xülasəsi."""
    from src.main import _run_scheduled_jobs

    cli = _CliContext(_report(failed=False))
    _patch_build_context(monkeypatch, cli)

    code = _run_scheduled_jobs()

    assert code == 0
    assert cli.calls == [True], "CLI yolu AĞIR işləri də icra etməlidir"
    output = capsys.readouterr().out
    assert "Planlaşdırılmış işlər" in output
    assert "NIGHTLY_BACKUP" in output


def test_the_cli_returns_non_zero_when_a_job_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Çökən iş → qeyri-sıfır kod.

    Sıfır qaytarsaydıq, Windows Task Scheduler tarixçəsində gecə "uğurlu"
    görünərdi və ehtiyat nüsxənin aylarla alınmadığı yalnız bərpa anında —
    yəni ən pis anda — aşkarlanardı.
    """
    from src.main import _run_scheduled_jobs

    cli = _CliContext(_report(failed=True))
    _patch_build_context(monkeypatch, cli)

    code = _run_scheduled_jobs()

    assert code != 0
    assert "UĞURSUZ: NIGHTLY_BACKUP" in capsys.readouterr().out


def test_the_cli_flag_does_not_open_the_gui(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--run-scheduled-jobs` başsızdır — paketlənmiş rejimdə də pəncərə AÇMIR."""
    import src.main as main_module

    calls: list[str] = []
    monkeypatch.setattr(main_module, "_run_scheduled_jobs", lambda: calls.append("jobs") or 0)
    monkeypatch.setattr(main_module, "_run_gui", lambda _args: calls.append("gui") or 0)
    # Paketlənmiş rejimin defoltu GUI-dir — planlayıcı qolu ondan ƏVVƏL
    # gəlməlidir, əks halda Task Scheduler mağaza PC-sində pəncərə açardı.
    monkeypatch.setattr(main_module, "is_frozen", lambda: True)

    assert main_module.main(["--run-scheduled-jobs"]) == 0
    assert calls == ["jobs"]


# --------------------------------------------------------------------------- #
# 7. INSTANCE_ID — İKİ PROSES, İKİ AD
# --------------------------------------------------------------------------- #


def test_two_processes_get_two_different_instance_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Eyni maşında açılan iki nüsxə fərqli imzalayır (PID fərqi).

    Eyni identifikator daşısaydılar, `mark_succeeded`-in sahiblik şərti hər
    ikisi üçün doğru olardı və icarə diaqnostikası yalan danışardı.
    """
    import src.shared.runtime as runtime_module

    monkeypatch.setattr(runtime_module.socket, "gethostname", lambda: "MAGAZA3-KASSA1")
    monkeypatch.setattr(runtime_module.os, "getpid", lambda: 4212)
    first = process_instance_id()
    monkeypatch.setattr(runtime_module.os, "getpid", lambda: 5150)
    second = process_instance_id()

    assert first == "MAGAZA3-KASSA1#4212"
    assert first != second


def test_an_empty_hostname_still_produces_a_usable_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Boş maşın adı DB `CHECK`-inə düşərdi — görünən əvəz qoyulur."""
    import src.shared.runtime as runtime_module

    monkeypatch.setattr(runtime_module.socket, "gethostname", lambda: "   ")

    assert process_instance_id().startswith("TERMINAL#")


def test_the_runner_carries_the_process_instance_id() -> None:
    """Kompozisiya kökü YENİ identifikator icad etmir — `runtime`-dan alır."""
    context, _session, _database = _context()

    assert context.job_runner().instance_id == process_instance_id()


# --------------------------------------------------------------------------- #
# SAAS-6 — saxlama müddəti işi HƏR İKİ cədvələ toxunur
# --------------------------------------------------------------------------- #


def test_the_retention_job_purges_both_growing_tables_with_one_cutoff() -> None:
    """İki cədvəl, BİR kəsim anı, BİR Root açarı.

    İki ayrı iş olsaydı, biri sükutla söndürüləndə digəri «hər şey
    təmizlənir» təəssüratı yaradardı (bax `composition.py::
    _job_retention_purge` başlığı).
    """
    from src.domain.policies import SystemLimitKey

    context, session, database = _context()
    runner, _runs = _runner(context, database)
    job = runner._registry.get("RETENTION_PURGE")
    assert job is not None

    detail = job.handler(_job_context("RETENTION_PURGE"))

    assert session.limits.keys == [SystemLimitKey.EVIDENCE_UPLOAD_RETENTION_DAYS.value]
    # Kəsim HƏR İKİ çağırışda EYNİdir — «30 gün» iki cədvəl üçün bir mənadır.
    assert session.evidence_queue.cutoffs == session.sync_conflicts.cutoffs
    assert "7" in detail and "4" in detail
