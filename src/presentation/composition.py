"""GUI kompozisiya kökü — obyekt qrafı (Faza 5/6 bağlantısı).

`app.py` PƏNCƏRƏ və EKRAN qrafını qurur; bu modul isə onların arxasındakı
USE CASE qrafını qurur. İkisinin ayrı olması qəsdəndir: `app.py` bazadan
tamamilə asılı olmadan (önizləmə rejimi, dizayn yoxlaması) işləyə bilməlidir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ USE CASE-LƏR HƏR ƏMƏLİYYATDA YENİDƏN QURULUR
──────────────────────────────────────────────────────────────────────────────
Repository-lər BAĞLANTIYA bağlıdır (`PostgresUnitOfWork._build_repositories`),
bağlantı isə tranzaksiya sərhədidir. Use case-i bir dəfə qurub saxlasaydıq, o,
artıq bağlanmış bir bağlantıya istinad edərdi.

Ona görə naxış belədir::

    with context.session() as session:
        session.leave_verification.claim_return(...)
        session.commit()

`session()` yeni `UnitOfWork` açır, use case-ləri onun repo-ları ilə qurur və
çıxışda bağlayır. Bu, "hər ekran əməliyyatı = bir tranzaksiya" qaydasını
struktur olaraq təmin edir.

──────────────────────────────────────────────────────────────────────────────
LİSENZİYA QAPISI
──────────────────────────────────────────────────────────────────────────────
Bölmə 8: `LICENSE_INACTIVE` vəziyyətində "tətbiq tam bağlanır (heç bir modul,
o cümlədən PIN handshake, işləmir)". `license_state()` həmin qərarı verir və
`app.py` ona görə ya `LicenseInactiveScreen`, ya da normal axını göstərir.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.infrastructure.timekeeping.clock import SystemClock
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from src.application.use_cases.audit_query import AuditQueryUseCase
    from src.application.use_cases.daily_attendance import DailyAttendanceSheetUseCase
    from src.application.use_cases.fine_management import (
        FineAppealUseCase,
        ManualFineUseCase,
    )
    from src.application.use_cases.first_run_setup import FirstRunSetupUseCase
    from src.application.use_cases.leave_verification import LeaveVerificationUseCase
    from src.application.use_cases.morning_check_in import MorningCheckInUseCase
    from src.application.use_cases.position_management import PositionManagementUseCase
    from src.application.use_cases.reporting import MonthlyReportUseCase
    from src.application.use_cases.root_control import RootControlUseCase
    from src.application.use_cases.sales_points import SalesPointsUseCase
    from src.application.use_cases.shift_scheduling import (
        ShiftPlanningUseCase,
        ShiftSwapUseCase,
    )
    from src.application.use_cases.support_chat import SupportChatUseCase
    from src.application.use_cases.sync_conflicts import SyncConflictUseCase
    from src.application.use_cases.task_workflow import TaskWorkflowUseCase
    from src.application.use_cases.user_management import UserManagementUseCase
    from src.domain.interfaces.ports import NtpVerifier
    from src.domain.value_objects.identifiers import EmployeeId, TenantId
    from src.infrastructure.licensing.client import LicenseClient
    from src.infrastructure.persistence.connection import Database, PostgresUnitOfWork

_log = get_logger(__name__)
_error_log = get_logger(__name__, channel=LogChannel.ERROR)


class _NullNtp:
    """Ölçmə mənbəyi olmayan `NtpVerifier` — bax `ApplicationContext.__init__`."""

    def verified_now(self) -> tuple[datetime, bool]:
        return datetime.now(UTC), False

    def drift_seconds(self) -> float | None:
        return None


class StartupError(KompasOSError):
    """Tətbiq işə düşə bilmədi — fatal başlanğıc ekranı göstərilir.

    Bölmə 8 (EHTİYAT DƏSTƏK KANALI): "hər fatal başlanğıc-xətası ekranında
    statik e-poçt ünvanı göstərilir" — çünki tətbiq açılmırsa müştəri
    tətbiq-daxili chat-ə çata bilmir.
    """

    user_message = "KompasOS işə düşə bilmədi."


@dataclass
class Session:
    """Bir tranzaksiya ərzində qurulmuş use case dəsti.

    Sahələr `Any`-dir: repo-lar Protocol-lara UYĞUNLAŞIR (miras almır) və
    hər birini konkret tiplə annotasiya etmək bu faylı 60 sətir `cast`-a
    çevirərdi. Tip təhlükəsizliyi use case-lərin ÖZ imzalarındadır.
    """

    uow: PostgresUnitOfWork
    tenant_id: TenantId

    leave_verification: LeaveVerificationUseCase
    morning_check_in: MorningCheckInUseCase
    shift_planning: ShiftPlanningUseCase
    shift_swaps: ShiftSwapUseCase
    daily_attendance: DailyAttendanceSheetUseCase
    manual_fines: ManualFineUseCase
    fine_appeals: FineAppealUseCase
    tasks: TaskWorkflowUseCase
    sales_points: SalesPointsUseCase
    reports: MonthlyReportUseCase
    audit_query: AuditQueryUseCase
    users: UserManagementUseCase
    positions: PositionManagementUseCase
    support: SupportChatUseCase
    sync_conflicts: SyncConflictUseCase
    setup: FirstRunSetupUseCase
    root_control: RootControlUseCase

    def commit(self) -> None:
        self.uow.commit()

    @property
    def preferences(self) -> Any:
        """`user_preferences` repo-su — tema və dashboard düzülüşü."""
        return self.uow.repository("preferences")

    @property
    def report_facts(self) -> Any:
        """Hesabat rəqəmlərinin SQL mənbəyi."""
        return self.uow.repository("report_facts")

    @property
    def limits(self) -> Any:
        return self.uow.repository("limits")

    @property
    def toggles(self) -> Any:
        return self.uow.repository("toggles")

    def max_upload_bytes(self) -> int:
        """`system_limits.MAX_UPLOAD_SIZE_BYTES` (bölmə 3, defolt 5 MB).

        `ApplicationContext.run_evidence_uploads()` hər dövrədə bunu oxuyur və
        `DriveProviderFactory`-yə ötürür ki, şəkil həddi koda deyil, ROOT
        Control Center-ə bağlı olsun. `google_drive.MAX_UPLOAD_BYTES` yalnız
        fallback-dır (limit mənbəyi olmayan yollar üçün).
        """
        key = SystemLimitKey.MAX_UPLOAD_SIZE_BYTES
        limit: int = self.limits.get_int(self.tenant_id, key.value, int(DEFAULT_LIMITS[key]))
        return limit


class ApplicationContext:
    """Tətbiqin canlı obyekt qrafı — `main.py --gui` bunu qurur."""

    def __init__(
        self,
        *,
        database: Database,
        tenant_id: TenantId,
        license_client: LicenseClient | None = None,
        ntp: NtpVerifier | None = None,
    ) -> None:
        self._database = database
        self._tenant_id = tenant_id
        self._license = license_client
        self._clock = SystemClock()
        # NTP yoxlayıcısı verilməyibsə `_NullNtp` işlədilir: o, HƏMİŞƏ
        # "təsdiqlənməyib" qaytarır, lakin sürüşmə ÖLÇÜLMƏYİB deyir. Nəticədə
        # `TIME_DRIFT_DETECTED` bloku işə DÜŞMÜR (ölçmə yoxdur, hədd
        # müqayisə edilə bilmir) — ölçə bilməmək əməliyyatı dayandırmamalıdır.
        self._ntp: NtpVerifier = ntp or _NullNtp()
        # Sübut yükləmə qatı TƏNBƏLdir: növbə SQLite faylı və Drive klienti
        # yalnız ilk cərimə/ilk dövrə zamanı yaradılır. Örtük açılışını
        # şəbəkəyə və diskə bağlamamaq üçün belədir.
        self._evidence_queue: Any = None
        self._drive_factory: Any = None
        self._drive_limit: int | None = None

    @property
    def database(self) -> Database:
        return self._database

    @property
    def tenant_id(self) -> TenantId:
        return self._tenant_id

    # ------------------------------ lisenziya -------------------------------- #

    def license_blocked(self) -> bool:
        """Tətbiq `LICENSE_INACTIVE` səbəbindən tam bağlanmalıdırmı (bölmə 8).

        Klient qoşulmayıbsa `False` — lisenziya yoxlanışının OLMAMASI tətbiqi
        bloklamamalıdır. Bu, qəsdən seçilmiş fail-open istiqamətidir: bölmə 8
        yalnız `expires_at` KEÇDİKDƏ bloklamağı tələb edir, "yoxlaya bilmədim"
        halı isə `LICENSE_UNVERIFIED` xəbərdarlığıdır (bloklamır).
        """
        if self._license is None:
            return False
        try:
            return bool(self._license.current_state().is_blocked)
        except Exception:
            _error_log.exception("LICENSE_CHECK_FAILED")
            return False

    def license_screen_text(self) -> tuple[str, str, str]:
        """`LicenseInactiveScreen` üçün başlıq/izah/əlaqə mətni (bölmə 8).

        Bölmə 8: ekran "ümumi/qeyri-müəyyən xəta mesajı OLMAMALIDIR — səbəbi,
        son ödəniş/borc tarixini və ödəniş üçün əlaqə vasitəsini açıq şəkildə
        göstərməlidir". Mətn `license_status.blocked_screen_text()`-dədir;
        burada yalnız cari vəziyyət ona ötürülür.
        """
        from src.application.use_cases.license_status import (  # noqa: PLC0415
            blocked_screen_text,
        )

        if self._license is None:
            return (
                "Lisenziya yoxlanıla bilmir",
                "Lisenziya klienti konfiqurasiya edilməyib.",
                "",
            )
        return blocked_screen_text(self._license.current_state())

    # --------------------------- ilk quraşdırma ------------------------------ #

    def complete_setup(self, payload: dict[str, object]) -> None:
        """Sihirbaz formasını use case-in gözlədiyi drafts-a çevirir və icra edir.

        Çevirmə BURADA edilir, ekranda YOX: ekran yalnız sahələri toplayır və
        domen tiplərini (`Username`, `EmailAddress`) tanımır. Validasiya həmin
        tiplərin öz konstruktorlarındadır — səhv format burada istisna atır və
        `app.py` onu istifadəçiyə göstərir.
        """
        from src.application.use_cases.first_run_setup import (  # noqa: PLC0415
            InviteDraft,
            RootAccountDraft,
            StoreDraft,
        )
        from src.domain.value_objects.credentials import (  # noqa: PLC0415
            EmailAddress,
            Username,
        )

        root_raw = _as_mapping(payload.get("root"))
        email_raw = str(root_raw.get("email", "")).strip()
        root = RootAccountDraft(
            first_name=str(root_raw.get("first_name", "")),
            last_name=str(root_raw.get("last_name", "")),
            username=Username.parse(str(root_raw.get("username", ""))),
            password=str(root_raw.get("password", "")),
            recovery_email=EmailAddress.parse(email_raw) if email_raw else None,
        )
        stores = [
            StoreDraft(
                code=str(item.get("code", "")),
                name=str(item.get("name", "")),
                brand=str(item.get("brand", "")),
                address=str(item.get("address", "")),
            )
            for item in _as_sequence(payload.get("stores"))
        ]
        invites = [
            InviteDraft(
                first_name=str(item.get("first_name", "")),
                last_name=str(item.get("last_name", "")),
                username=Username.parse(str(item.get("username", ""))),
                role_code=str(item.get("role_code", "HR_ADMIN")),
                temporary_password=str(item.get("temporary_password", "")),
            )
            for item in _as_sequence(payload.get("invites"))
        ]

        with self.session() as session:
            session.setup.complete(
                tenant_id=self._tenant_id,
                root=root,
                stores=stores,
                invites=invites,
            )
            session.commit()
        _log.info("FIRST_RUN_SETUP_COMPLETED", extra={"store_count": len(stores)})

    # --------------------------- sübut yükləməsi ----------------------------- #
    #
    # NİYƏ CƏRİMƏ DRIVE-I GÖZLƏMİR
    # ─────────────────────────────────────────────────────────────────────────
    # Bölmə 4: cərimə qeydi DƏRHAL yazılır, şəkil isə arxa planda yüklənir.
    # Ona görə ekran `evidence_queue()`-a yazır (lokal disk + SQLite indeks),
    # `run_evidence_uploads()` isə taymerlə çağırılır. Şəbəkə yoxdursa cərimə
    # yenə yaranır — bu, qəsdən seçilmiş sıradır.

    def evidence_queue(self) -> Any:
        """Sübut şəkillərinin lokal növbəsi (`EvidenceUploadQueue`)."""
        if self._evidence_queue is None:
            import os  # noqa: PLC0415
            from pathlib import Path  # noqa: PLC0415

            from src.infrastructure.storage.upload_queue import (  # noqa: PLC0415
                EvidenceUploadQueue,
            )

            raw = os.environ.get("KOMPASOS_EVIDENCE_QUEUE_PATH", "").strip()
            path = Path(raw) if raw else Path("./data/evidence_uploads.db")
            self._evidence_queue = EvidenceUploadQueue(path)
        return self._evidence_queue

    def drive_providers(self, *, max_upload_bytes: int) -> Any:
        """Aktiv Drive bağlantısı üçün provider fabriki — yoxdursa `None`.

        `max_upload_bytes` ROOT Control Center-dən gəlir və fabrik hər dəfə
        deyil, YALNIZ dəyər dəyişəndə yenidən qurulur: fabrik provider-ləri
        (HTTP klienti + token) keşləyir və hər dövrədə onu atmaq lazımsız
        token yeniləməsi deməkdir. Root sürüşdürücünü tərpədən kimi növbəti
        dövrə yeni həddi tətbiq edir.

        `None` qaytarır Google OAuth klient məlumatları təyin edilməyibsə —
        bu, xəta DEYİL: Drive qoşulmamış quraşdırmada cərimələr yenə yaranır,
        şəkillər isə növbədə gözləyir (bax `upload_queue` başlığı).
        """
        if self._drive_factory is not None and self._drive_limit == max_upload_bytes:
            return self._drive_factory

        import os  # noqa: PLC0415

        client_id = os.environ.get("KOMPASOS_GOOGLE_CLIENT_ID", "").strip()
        client_secret = os.environ.get("KOMPASOS_GOOGLE_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            return None

        from src.infrastructure.security.encryption import EncryptionService  # noqa: PLC0415
        from src.infrastructure.storage.connections import (  # noqa: PLC0415
            DriveConnectionRepository,
            DriveProviderFactory,
        )
        from src.infrastructure.storage.drive_api import OAuthClient  # noqa: PLC0415
        from src.infrastructure.storage.image_cache import ImageCache  # noqa: PLC0415

        self._drive_factory = DriveProviderFactory(
            repository=DriveConnectionRepository(self._database, self._tenant_id),
            encryption=EncryptionService(),
            oauth=OAuthClient(client_id=client_id, client_secret=client_secret),
            cache=ImageCache(),
            store_names=self._store_names(),
            max_upload_bytes=max_upload_bytes,
        )
        self._drive_limit = max_upload_bytes
        return self._drive_factory

    def invalidate_drive_providers(self) -> None:
        """Keşlənmiş fabriki atır — hesab dəyişəndə çağırılır.

        Fabrik provider-ləri (HTTP klienti + token) bağlantı ID-sinə görə
        keşləyir. Yeni hesab qoşulduqda köhnə keş həmin an KÖHNƏ hesaba yazmağa
        davam edərdi; bir sətir daşınmayan, lakin tapılması çətin qüsurdur.
        """
        self._drive_factory = None
        self._drive_limit = None

    def run_evidence_uploads(self) -> int:
        """Növbəni bir dəfə boşaldır — yüklənən şəkillərin sayını qaytarır.

        Taymerdən çağırılır və HEÇ VAXT istisna atmır: fon işi interfeysi
        çökdürməməlidir (bax `EvidenceUploadWorker.run_once` daxilindəki eyni
        prinsip — bir şəklin nasazlığı növbəni dayandırmır).
        """
        try:
            with self.session() as session:
                limit = session.max_upload_bytes()
            factory = self.drive_providers(max_upload_bytes=limit)
            if factory is None:
                return 0

            from src.infrastructure.storage.upload_queue import (  # noqa: PLC0415
                EvidenceUploadWorker,
            )

            worker = EvidenceUploadWorker(
                queue=self.evidence_queue(),
                provider_factory=factory,
                on_uploaded=self._attach_evidence,
            )
            return worker.run_once().uploaded
        except Exception:
            _error_log.exception("EVIDENCE_UPLOAD_RUN_FAILED")
            return 0

    def _attach_evidence(self, fine_id: str, reference: Any) -> None:
        """Yükləmə bitdikdən sonra `fines` sətrini yeniləyir."""
        import uuid  # noqa: PLC0415

        from src.domain.value_objects.identifiers import FineId  # noqa: PLC0415

        with self.session() as session:
            session.uow.fines.attach_drive_evidence(
                FineId(uuid.UUID(fine_id)),
                file_id=reference.file_id,
                connection_id=reference.connection_id,
            )
            session.commit()

    def _store_names(self) -> Any:
        """`store_id → ad` — Drive qovluq adları üçün (bax `StoreNameResolver`)."""
        from src.infrastructure.storage.google_drive import (  # noqa: PLC0415
            StoreNameResolver,
        )

        resolver = StoreNameResolver()
        try:
            with self._database.unit_of_work(self._tenant_id) as uow:
                rows = uow.connection.execute(
                    "SELECT id, name FROM stores WHERE tenant_id = %s",
                    (self._tenant_id,),
                ).fetchall()
        except Exception:
            # Adlar tapılmasa provider "Mağaza-xxxxxxxx" işlədir — qovluq adı
            # gözəl olmaz, lakin yükləmə DAYANMAMALIDIR.
            _error_log.exception("STORE_NAMES_LOAD_FAILED")
            return resolver
        for row in rows:
            resolver.register(row["id"], str(row["name"]))
        return resolver

    # ------------------------------- sessiya --------------------------------- #

    @contextmanager
    def session(self, *, user_id: EmployeeId | None = None) -> Iterator[Session]:
        """Bir tranzaksiya + onun üzərində qurulmuş use case dəsti."""
        with self._database.unit_of_work(self._tenant_id, user_id=user_id) as uow:
            yield self._build_session(uow)

    def _build_session(self, uow: PostgresUnitOfWork) -> Session:
        """Use case qrafını cari `UnitOfWork`-un repo-ları ilə qurur."""
        from src.application.use_cases.audit_query import AuditQueryUseCase  # noqa: PLC0415
        from src.application.use_cases.daily_attendance import (  # noqa: PLC0415
            DailyAttendanceSheetUseCase,
        )
        from src.application.use_cases.fine_management import (  # noqa: PLC0415
            FineAppealUseCase,
            ManualFineUseCase,
        )
        from src.application.use_cases.first_run_setup import (  # noqa: PLC0415
            FirstRunSetupUseCase,
        )
        from src.application.use_cases.leave_verification import (  # noqa: PLC0415
            LeaveVerificationUseCase,
        )
        from src.application.use_cases.morning_check_in import (  # noqa: PLC0415
            MorningCheckInUseCase,
        )
        from src.application.use_cases.position_management import (  # noqa: PLC0415
            PositionManagementUseCase,
        )
        from src.application.use_cases.reporting import MonthlyReportUseCase  # noqa: PLC0415
        from src.application.use_cases.root_control import (  # noqa: PLC0415
            RootControlUseCase,
        )
        from src.application.use_cases.sales_points import SalesPointsUseCase  # noqa: PLC0415
        from src.application.use_cases.shift_scheduling import (  # noqa: PLC0415
            ShiftPlanningUseCase,
            ShiftSwapUseCase,
        )
        from src.application.use_cases.support_chat import SupportChatUseCase  # noqa: PLC0415
        from src.application.use_cases.sync_conflicts import (  # noqa: PLC0415
            SyncConflictUseCase,
        )
        from src.application.use_cases.task_workflow import (  # noqa: PLC0415
            TaskWorkflowUseCase,
        )
        from src.application.use_cases.user_management import (  # noqa: PLC0415
            UserManagementUseCase,
        )
        from src.infrastructure.notifications.notifier import PostgresNotifier  # noqa: PLC0415
        from src.shared.saga_orchestrator import SagaOrchestrator  # noqa: PLC0415

        repo = uow.repository
        clock = self._clock
        ntp = self._ntp
        audit = uow.audit
        notifier = PostgresNotifier(self._database)

        planning = ShiftPlanningUseCase(
            shifts=repo("shifts"),
            leave_requests=uow.leave_requests,
            audit=audit,
            clock=clock,
            notifier=notifier,
        )

        return Session(
            uow=uow,
            tenant_id=self._tenant_id,
            leave_verification=LeaveVerificationUseCase(
                leave_requests=uow.leave_requests,
                fines=uow.fines,
                employees=uow.employees,
                leave_types=repo("leave_types"),
                camera_assignments=repo("camera_assignments"),
                clock=clock,
                ntp=ntp,
                limits=repo("limits"),
                toggles=repo("toggles"),
                saga=SagaOrchestrator(),
                audit=audit,
                notifier=notifier,
            ),
            morning_check_in=MorningCheckInUseCase(
                attendance=uow.attendance,
                shifts=repo("shifts"),
                employees=uow.employees,
                camera_assignments=repo("camera_assignments"),
                clock=clock,
                ntp=ntp,
                limits=repo("limits"),
                toggles=repo("toggles"),
                audit=audit,
                notifier=notifier,
            ),
            shift_planning=planning,
            shift_swaps=ShiftSwapUseCase(
                swaps=repo("shift_swaps"),
                planning=planning,
                toggles=repo("toggles"),
                audit=audit,
                clock=clock,
                notifier=notifier,
            ),
            daily_attendance=DailyAttendanceSheetUseCase(
                sheets=repo("sheets"),
                facts=repo("attendance_facts"),
                audit=audit,
                clock=clock,
                notifier=notifier,
            ),
            manual_fines=ManualFineUseCase(
                fines=uow.fines,
                fine_types=repo("fine_types"),
                camera_assignments=repo("camera_assignments"),
                limits=repo("limits"),
                toggles=repo("toggles"),
                audit=audit,
                clock=clock,
                notifier=notifier,
            ),
            fine_appeals=FineAppealUseCase(
                appeals=repo("appeals"),
                fines=uow.fines,
                audit=audit,
                clock=clock,
                notifier=notifier,
            ),
            tasks=TaskWorkflowUseCase(
                tasks=repo("tasks"),
                audit=audit,
                clock=clock,
                notifier=notifier,
                toggles=repo("toggles"),
            ),
            sales_points=SalesPointsUseCase(
                points=repo("sales_points"),
                rewards=repo("rewards"),
                audit=audit,
                clock=clock,
                notifier=notifier,
                toggles=repo("toggles"),
            ),
            reports=MonthlyReportUseCase(),
            audit_query=AuditQueryUseCase(
                reader=repo("audit_reader"),
                audit=audit,
                clock=clock,
            ),
            users=UserManagementUseCase(
                employees=uow.employees,
                credentials=uow.employees,
                audit=audit,
                clock=clock,
                camera_assignments=repo("camera_assignments"),
            ),
            positions=PositionManagementUseCase(
                positions=uow.positions,
                flags=repo("permission_flags"),
                audit=audit,
                clock=clock,
            ),
            support=SupportChatUseCase(
                tickets=repo("support"),
                toggles=repo("toggles"),
                clock=clock,
            ),
            sync_conflicts=SyncConflictUseCase(
                repository=repo("sync_conflicts"),
                audit=audit,
                clock=clock,
            ),
            setup=FirstRunSetupUseCase(
                employees=uow.employees,
                positions=uow.positions,
                stores=repo("stores"),
                credentials=uow.employees,
                audit=audit,
                clock=clock,
            ),
            root_control=RootControlUseCase(
                limits=repo("limits"),
                toggles=repo("toggles"),
                flags=repo("permission_flags"),
                audit=audit,
                clock=clock,
            ),
        )


def build_context(*, tenant_id_env: str = "KOMPASOS_TENANT_ID") -> ApplicationContext:
    """Mühit dəyişənlərindən canlı kontekst qurur.

    Raises:
        StartupError: Baza və ya tenant konfiqurasiyası yoxdursa. Xəta MESAJI
            istifadəçiyə göstərilir və orada əlaqə e-poçtu olur (bölmə 8) —
            "işə düşmədi" mesajı ilə kimsəsiz qalan müştəri ən pis haldır.
    """
    import os  # noqa: PLC0415
    import uuid  # noqa: PLC0415

    from src.domain.value_objects.identifiers import TenantId  # noqa: PLC0415
    from src.infrastructure.persistence.connection import Database  # noqa: PLC0415

    raw_tenant = os.environ.get(tenant_id_env, "").strip()
    if not raw_tenant:
        raise StartupError(
            f"`{tenant_id_env}` təyin edilməyib",
            user_message=(
                "Quraşdırma tamamlanmayıb: tenant identifikatoru təyin edilməyib. "
                "Quraşdırma sənədinə baxın və ya dəstəklə əlaqə saxlayın."
            ),
            context={"missing_env": tenant_id_env},
        )

    try:
        tenant_id = TenantId(uuid.UUID(raw_tenant))
    except ValueError as exc:
        raise StartupError(
            "Tenant identifikatoru düzgün UUID deyil",
            user_message="Quraşdırma faylındakı tenant identifikatoru yararsızdır.",
            context={"value": raw_tenant},
        ) from exc

    try:
        database = Database()
        database.open()
    except Exception as exc:
        _error_log.exception("DATABASE_OPEN_FAILED")
        raise StartupError(
            "Baza bağlantısı qurula bilmədi",
            user_message=(
                "Bazaya qoşulmaq mümkün olmadı. İnternet bağlantısını yoxlayın; "
                "problem davam edərsə dəstəklə əlaqə saxlayın."
            ),
        ) from exc

    _log.info("APPLICATION_CONTEXT_BUILT", extra={"tenant_id": str(tenant_id)})
    return ApplicationContext(database=database, tenant_id=tenant_id)


def _as_mapping(raw: object) -> dict[str, Any]:
    """Sihirbaz yükündən sözlük çıxarır — yararsız tip BOŞ sözlük olur.

    İstisna atmır: sahə yoxdursa draft konstruktorları onsuz da anlaşılan
    Azərbaycanca xəta verir ("Ad sahəsini doldurun"), halbuki `KeyError`
    istifadəçiyə heç nə demir.
    """
    return dict(raw) if isinstance(raw, dict) else {}


def _as_sequence(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, (list, tuple)):
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]


__all__ = ["ApplicationContext", "Session", "StartupError", "build_context"]
