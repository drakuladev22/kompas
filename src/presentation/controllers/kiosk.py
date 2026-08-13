"""Kiosk körpüsü: PIN klaviaturası ↔ use case-lər (bölmə 4) — Faza 5.

`app.py` yalnız ekranları bağlayır; həqiqi PIN yoxlaması, status hesablaması
və `[İşə Başladım]`/`[İcazə İstəyirəm]`/`[Mən Qayıtdım]` əməliyyatları buradan
keçir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI KONTROLLER
──────────────────────────────────────────────────────────────────────────────
`auth.py`-dakı eyni səbəb: ekran Qt siqnalları ilə işləyir, use case isə saf
funksiyadır və domen istisnaları atır. Kiosk PC-si üstəlik PAYLAŞILAN cihazdır
— orada istisna ilə çökən ekran bütün mağazanı bloklayardı, ona görə hər
əməliyyat `KioskOutcome`-a çevrilir və istisna EKRANA ÇIXMIR.

──────────────────────────────────────────────────────────────────────────────
STATUS NİYƏ HƏR DƏFƏ YENİDƏN HESABLANIR
──────────────────────────────────────────────────────────────────────────────
Bölmə 3 (İŞÇİ ANA EKRANI) beş status və hər biri üçün TƏK bir aktiv düymə
tələb edir. Statusu keşləsək, Kamera Operatoru təsdiqlədikdən sonra işçinin
ekranı köhnə düyməni göstərərdi və o, "təsdiqlə" düyməsini basa bilməzdi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from src.application.use_cases.leave_verification import (
    ModuleDisabledError,
    OperationNotPermittedError,
    TimeDriftError,
)
from src.presentation.widgets.worker_status import WorkerStatus
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.domain.entities.employee import Employee
    from src.domain.value_objects.identifiers import EmployeeId, LeaveTypeId, StoreId
    from src.presentation.composition import ApplicationContext, Session

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)
_log = get_logger(__name__)

#: PIN səhv olduqda göstərilən ÜMUMİ mesaj — hansı işçi olduğu açıqlanmır.
GENERIC_PIN_FAILURE = "PIN yanlışdır"


@dataclass(frozen=True)
class KioskOutcome:
    """Hər kiosk əməliyyatının nəticəsi — istisna ATMIR."""

    succeeded: bool
    message: str = ""
    status: WorkerStatus | None = None
    employee: Employee | None = None

    @property
    def failed(self) -> bool:
        return not self.succeeded


class KioskController:
    """İşçi Ana Ekranının arxa tərəfi."""

    def __init__(self, context: ApplicationContext, *, store_id: StoreId) -> None:
        self._context = context
        self._store_id = store_id

    # -------------------------------- PIN ------------------------------------ #

    def authenticate(self, pin: str) -> KioskOutcome:
        """PIN handshake — uğurlu olduqda işçi və onun cari statusu qaytarılır."""
        try:
            with self._context.session() as session:
                from src.application.use_cases.authentication import (  # noqa: PLC0415
                    PinHandshakeUseCase,
                )
                from src.infrastructure.security.hashing import (  # noqa: PLC0415
                    HashingService,
                )
                from src.infrastructure.timekeeping.clock import (  # noqa: PLC0415
                    SystemClock,
                )

                employees = session.uow.employees
                candidates = employees.find_by_pin_candidates(
                    self._context.tenant_id, self._store_id
                )
                pin_hashes = {}
                for candidate in candidates:
                    credentials = employees.credentials_for(candidate.id)
                    if credentials is not None and credentials.pin_hash:
                        pin_hashes[candidate.id] = (
                            credentials.pin_hash,
                            credentials.pepper_version,
                        )

                use_case = PinHandshakeUseCase(
                    employees=employees,
                    # `limits`: hash servisinin ROOT pəncərəsi. PIN siyasəti
                    # (cəhd sayı / bloklama) use case-in ÖZ `limits`-indən
                    # gəlir — burada ikinci mənbə yaranmır, sadəcə servis də
                    # ROOT-a bağlanır (şifrə uzunluğu siyasəti üçün).
                    hashing=HashingService(limits=self._context.infrastructure_limits()),
                    clock=SystemClock(),
                    limits=session.limits,
                    audit=session.uow.audit,
                )
                result = use_case.authenticate(
                    tenant_id=self._context.tenant_id,
                    store_id=self._store_id,
                    pin=pin,
                    pin_hashes=pin_hashes,
                )
                # Uğursuz cəhdin sayğacı da yazılmalıdır (lockout, bölmə 2).
                session.commit()

                # `PinResult` YALNIZ uğurlu halda qayıdır — uğursuzluq
                # `AuthenticationError`/`AccountLockedError` ilə bildirilir
                # (aşağıdakı `except KompasOSError` onu tutur).
                employee = result.employee
                status = self._status_for(session, employee.id)
                return KioskOutcome(succeeded=True, status=status, employee=employee)
        except KompasOSError as exc:
            _security_log.info("KIOSK_PIN_REJECTED", extra=exc.to_dict())
            return KioskOutcome(succeeded=False, message=exc.user_message)
        except Exception:
            _log.exception("KIOSK_PIN_UNEXPECTED_ERROR")
            return KioskOutcome(
                succeeded=False,
                message="Sistem xətası. Bir az sonra yenidən cəhd edin.",
            )

    # ----------------------------- əməliyyatlar ------------------------------ #

    def start_day(self, employee: Employee) -> KioskOutcome:
        """`[İşə Başladım]` — STEP A (bölmə 4)."""

        def run(session: Session) -> None:
            session.morning_check_in.start_day(
                tenant_id=self._context.tenant_id,
                employee_id=employee.id,
                store_id=self._store_id,
            )

        return self._operation(employee, run, success="Giriş sorğunuz göndərildi.")

    def request_leave(
        self, employee: Employee, *, leave_type_id: LeaveTypeId | None = None
    ) -> KioskOutcome:
        """`[İcazə İstəyirəm]` — STEP 1 (bölmə 4)."""

        def run(session: Session) -> None:
            session.leave_verification.request_leave(
                tenant_id=self._context.tenant_id,
                employee_id=employee.id,
                store_id=self._store_id,
                leave_type_id=leave_type_id,
                # STEP 1 yalnız `🟢 Mağazada` statusundan işə düşür — həmin
                # şərti use case özü yoxlaya bilsin deyə açıq ötürülür.
                employee_is_in_store=True,
            )

        return self._operation(employee, run, success="İcazə sorğunuz qeydə alındı.")

    def claim_return(self, employee: Employee) -> KioskOutcome:
        """`[Mən Qayıtdım]` — STEP 2 (bölmə 4)."""

        def run(session: Session) -> None:
            session.leave_verification.claim_return(
                tenant_id=self._context.tenant_id,
                employee_id=employee.id,
            )

        return self._operation(employee, run, success="Qayıdışınız Kamera Operatoruna göndərildi.")

    # ------------------------------- köməkçi --------------------------------- #

    def _operation(
        self,
        employee: Employee,
        action: Callable[[Session], None],
        *,
        success: str,
    ) -> KioskOutcome:
        """Ortaq icra qabığı — istisna ekrana ÇIXMIR (modul başlığına bax)."""
        try:
            with self._context.session(user_id=employee.id) as session:
                action(session)
                session.commit()
                status = self._status_for(session, employee.id)
        except (TimeDriftError, ModuleDisabledError, OperationNotPermittedError) as exc:
            return KioskOutcome(succeeded=False, message=exc.user_message)
        except KompasOSError as exc:
            return KioskOutcome(succeeded=False, message=exc.user_message)
        except Exception:
            _log.exception("KIOSK_OPERATION_FAILED")
            return KioskOutcome(
                succeeded=False, message="Əməliyyat tamamlanmadı. Yenidən cəhd edin."
            )
        return KioskOutcome(succeeded=True, message=success, status=status, employee=employee)

    def status_for(self, employee_id: EmployeeId) -> WorkerStatus:
        """Ekranın yenilənməsi üçün cari status."""
        with self._context.session() as session:
            return self._status_for(session, employee_id)

    def _status_for(self, session: Session, employee_id: EmployeeId) -> WorkerStatus:
        """Davamiyyət + açıq icazə qeydlərini birləşmiş statusa çevirir.

        Çevirmə QAYDASI burada TƏKRARLANMIR — `WorkerStatus.from_domain()`
        onu artıq saxlayır (icazənin davamiyyəti üstələməsi daxil olmaqla).
        Bu metod yalnız iki qeydi oxuyur və ona ötürür.
        """
        uow = session.uow
        open_leave = uow.leave_requests.find_open_for_employee(employee_id)
        record = uow.attendance.get_for_day(employee_id, date.today())  # noqa: DTZ011
        return WorkerStatus.from_domain(
            record.status if record is not None else None,
            open_leave.status if open_leave is not None else None,
        )


__all__ = [
    "GENERIC_PIN_FAILURE",
    "KioskController",
    "KioskOutcome",
]
