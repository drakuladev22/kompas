"""Filiallar-arası köçürmə sorğusunun YAZI yolu — `v2backlog.md` Faza 3.3.

İki kontroller, iki ekran, BİR use case (`annual_leave.py` İLƏ EYNİ NAXIŞ,
bax həmin faylın başlığı):

    `EmployeeTransferController`  → İşçi Ana Ekranı (kiosk): "Filiallar-arası
                                     Köçürmə" kartı — sorğu göndərir, öz
                                     PENDING sorğusunu geri çəkir.
    `TransferRequestInboxController` → «Köçürmə Sorğuları» ekranı (HR_Admin,
                                     `can_approve_transfer_request`): təsdiq
                                     növbəsi.

──────────────────────────────────────────────────────────────────────────────
NİYƏ ÖZ KONTROLLERİ VAR (CLAUDE.md §6)
──────────────────────────────────────────────────────────────────────────────
Hər iki ekran HƏM oxuyur, HƏM yazır: sorğu göndərildikdən sonra kartın "cari
sorğu" sətri DƏRHAL yenilənməlidir, HR növbəsində qərar verilmiş sorğu
`pending_inbox`-dan ÇIXIR. `screen_data.py`-a bağlamaq YARARSIZDIR
(`controllers/annual_leave.py`/`controllers/announcements.py` ilə eyni qərar)
— bu dövrə `populate()`-ın tək çağırışından uzun yaşayır.

SESSİYA SAXLANILMIR: hər əməliyyat üçün yeni sessiya açılır və commit edilir.

──────────────────────────────────────────────────────────────────────────────
KİOSKDA İSTİSNA EKRANA ÇIXMIR
──────────────────────────────────────────────────────────────────────────────
`controllers/kiosk.py`/`controllers/annual_leave.py` ilə EYNİ qayda: kiosk PC-si
PAYLAŞILAN cihazdır, orada modal xəta bütün mağazanı bloklayardı. Hər nəticə
`screen.set_transfer_request_message(...)` mətninə çevrilir və mətn HƏMİŞƏ
`error.user_message`-dən gəlir.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from src.domain.value_objects.identifiers import TransferRequestId
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.entities.employee_transfer import EmployeeTransferRequest
    from src.domain.value_objects.identifiers import EmployeeId, StoreId
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen
    from src.presentation.screens.transfer_requests import TransferRequestInboxScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Rədd səbəbi dialoqunun mətni — səbəb domendə MƏCBURİDİR
#: (`EmployeeTransferRequest.reject`, minimum 10 simvol).
_REJECT_PROMPT = (
    "Rədd səbəbi (məcburi) — işçiyə göndərilən bildirişdə göstərilir və audit jurnalına düşür:"
)

SUBMIT_CONFIRMATION = "Köçürmə sorğunuz təsdiq üçün göndərildi."
WITHDRAW_CONFIRMATION = "Köçürmə sorğunuz geri çəkildi."

#: `TransferRequestUseCase.submit` `TransferRequestError` atır (məs. artıq
#: gözləyən sorğu var) — mesaj ORADAN gəlir, burada YENİDƏN yazılmır.
_DIALOG_DATA_FAILED = "Köçürmə forması açılmadı. Yenidən cəhd edin."
_NO_DESTINATION_STORES = "Seçilə bilən hədəf filial yoxdur."


class EmployeeTransferController:
    """İşçi Ana Ekranının "Filiallar-arası Köçürmə" kartı."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: EmployeeHomeScreen) -> None:
        screen.transfer_request_requested.connect(lambda: self._on_request(screen))
        screen.transfer_withdraw_requested.connect(lambda rid: self._on_withdraw(screen, rid))
        self.refresh(screen)

    def refresh(self, screen: EmployeeHomeScreen, *, message: str = "") -> None:
        """Öz sorğu tarixçəsini bazadan yenidən oxuyur — səlahiyyət TƏLƏB ETMİR.

        `my_requests` istənilən işçiyə açıqdır (bax use case başlığı: bu, öz
        tarixçəsini görməkdir, idarəetmə əməliyyatı deyil).
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                requests = session.transfer_requests.my_requests(self._actor)
                row = _to_status_row(session, requests[0]) if requests else {}
        except KompasOSError as error:
            screen.set_transfer_request({})
            screen.set_transfer_request_message(error.user_message)
            return
        except Exception:
            _error_log.exception("TRANSFER_REQUEST_STATUS_READ_FAILED")
            screen.set_transfer_request({})
            screen.set_transfer_request_message("Köçürmə sorğusu yüklənmədi.")
            return

        screen.set_transfer_request(row)
        screen.set_transfer_request_message(message)

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_request(self, screen: EmployeeHomeScreen) -> None:
        """`[Köçürmə Sorğusu]` — dialoq açılır, seçim use case-ə gedir."""
        from src.presentation.screens.transfer_requests import (  # noqa: PLC0415
            TransferRequestDialog,
        )

        try:
            with self._context.session(user_id=self._actor.id) as session:
                stores = _destination_choices(session, self._actor)
                current_store_name = (
                    _store_name(session, self._actor.store_id)
                    if self._actor.store_id is not None
                    else ""
                )
        except Exception:
            _error_log.exception("TRANSFER_REQUEST_DIALOG_DATA_FAILED")
            screen.set_transfer_request_message(_DIALOG_DATA_FAILED)
            return

        if not stores:
            screen.set_transfer_request_message(_NO_DESTINATION_STORES)
            return

        dialog = TransferRequestDialog(
            screen.theme, stores=stores, current_store_name=current_store_name, parent=screen
        )
        dialog.submitted.connect(lambda store_id, reason: self._submit(screen, store_id, reason))
        dialog.exec()

    def _submit(self, screen: EmployeeHomeScreen, store_id_text: str, reason: str) -> None:
        from src.domain.value_objects.identifiers import StoreId  # noqa: PLC0415

        try:
            to_store_id = StoreId(uuid.UUID(store_id_text))
        except ValueError:
            self.refresh(screen, message="Seçilmiş filial düzgün deyil.")
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.transfer_requests.submit(
                    tenant_id=session.tenant_id,
                    employee=self._actor,
                    to_store_id=to_store_id,
                    reason=reason,
                )
                session.commit()
        except KompasOSError as error:
            # Artıq gözləyən sorğu, cari filialı olmayan işçi və s. bura düşür.
            self.refresh(screen, message=error.user_message)
            return
        except Exception:
            _error_log.exception("TRANSFER_REQUEST_SUBMIT_FAILED")
            self.refresh(screen, message="Sorğu göndərilmədi. Yenidən cəhd edin.")
            return

        self.refresh(screen, message=SUBMIT_CONFIRMATION)

    def _on_withdraw(self, screen: EmployeeHomeScreen, request_id_text: str) -> None:
        """`[Sorğunu Geri Çək]` — YALNIZ göndərən (`TransferRequestUseCase.withdraw`)."""
        try:
            request_id = TransferRequestId(uuid.UUID(request_id_text))
        except ValueError:
            self.refresh(screen, message="Sorğu identifikatoru düzgün deyil.")
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.transfer_requests.withdraw(
                    tenant_id=session.tenant_id, employee=self._actor, request_id=request_id
                )
                session.commit()
        except KompasOSError as error:
            self.refresh(screen, message=error.user_message)
            return
        except Exception:
            _error_log.exception("TRANSFER_REQUEST_WITHDRAW_FAILED")
            self.refresh(screen, message="Sorğu geri çəkilmədi. Yenidən cəhd edin.")
            return

        self.refresh(screen, message=WITHDRAW_CONFIRMATION)


class TransferRequestInboxController:
    """«Köçürmə Sorğuları» ekranı — `can_approve_transfer_request` (HR_Admin)."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: TransferRequestInboxScreen) -> None:
        screen.approve_requested.connect(lambda request_id: self._on_approve(screen, request_id))
        screen.reject_requested.connect(lambda request_id: self._on_reject(screen, request_id))
        screen.refresh_requested.connect(lambda: self.refresh(screen))
        self.refresh(screen)

    def refresh(self, screen: TransferRequestInboxScreen) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                requests = session.transfer_requests.pending_inbox(
                    tenant_id=session.tenant_id, actor=self._actor
                )
                rows = [_to_inbox_row(session, request) for request in requests]
        except KompasOSError as error:
            # Səlahiyyəti olmayan istifadəçi bu ekranı görməməli idi (menyu
            # flag-i), lakin görsə — səbəb AÇIQ yazılır.
            screen.set_requests([])
            screen.show_error(title="Köçürmə sorğuları oxunmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception("TRANSFER_REQUEST_INBOX_LIST_FAILED")
            screen.set_requests([])
            screen.show_error(
                title="Köçürmə sorğuları oxunmadı",
                message="Siyahı oxuna bilmədi. Yenidən cəhd edin.",
            )
            return

        screen.set_requests(rows)

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_approve(self, screen: TransferRequestInboxScreen, request_id: str) -> None:
        parsed_id = _parse_request_id(request_id)
        if parsed_id is None:
            screen.show_error(
                title="Sorğu təsdiqlənmədi", message="Sorğu identifikatoru düzgün deyil."
            )
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.transfer_requests.approve(
                    tenant_id=session.tenant_id, approver=self._actor, request_id=parsed_id
                )
                session.commit()
        except KompasOSError as error:
            # `refresh()` BURADAN ÇAĞIRILMIR — `annual_leave.py::_on_approve`
            # ilə eyni səbəb: `set_requests()` xəta banner-inin ÜSTÜNDƏN yazardı.
            screen.show_error(
                title="Sorğu təsdiqlənmədi",
                message=error.user_message,
                on_retry=lambda: self.refresh(screen),
            )
            return
        except Exception:
            _error_log.exception(
                "TRANSFER_REQUEST_APPROVE_FAILED", extra={"request_id": request_id}
            )
            screen.show_error(
                title="Sorğu təsdiqlənmədi", message="Dəyişiklik yazılmadı. Yenidən cəhd edin."
            )
            return

        self.refresh(screen)

    def _on_reject(self, screen: TransferRequestInboxScreen, request_id: str) -> None:
        parsed_id = _parse_request_id(request_id)
        if parsed_id is None:
            screen.show_error(
                title="Sorğu rədd edilmədi", message="Sorğu identifikatoru düzgün deyil."
            )
            return

        reason = self._ask_reason(screen)
        if reason is None:
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.transfer_requests.reject(
                    tenant_id=session.tenant_id,
                    approver=self._actor,
                    request_id=parsed_id,
                    reason=reason,
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(
                title="Sorğu rədd edilmədi",
                message=error.user_message,
                on_retry=lambda: self.refresh(screen),
            )
            return
        except Exception:
            _error_log.exception("TRANSFER_REQUEST_REJECT_FAILED", extra={"request_id": request_id})
            screen.show_error(
                title="Sorğu rədd edilmədi", message="Dəyişiklik yazılmadı. Yenidən cəhd edin."
            )
            return

        self.refresh(screen)

    @staticmethod
    def _ask_reason(screen: TransferRequestInboxScreen) -> str | None:
        from PySide6.QtWidgets import QInputDialog  # noqa: PLC0415

        text, accepted = QInputDialog.getMultiLineText(
            screen, "Köçürmə sorğusunu rədd et", _REJECT_PROMPT
        )
        cleaned = text.strip()
        return cleaned if accepted and cleaned else None


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _to_inbox_row(session: Session, request: EmployeeTransferRequest) -> dict[str, str]:
    """`EmployeeTransferRequest` → HR növbəsinin FAKTİKİ gözlədiyi açarlar."""
    return {
        "id": str(request.id),
        "employee": _employee_name(session, request.employee_id),
        "from_store": _store_name(session, request.from_store_id),
        "to_store": _store_name(session, request.to_store_id),
        "reason": request.reason,
        "submitted": request.created_at.astimezone().strftime("%d.%m.%Y %H:%M"),
    }


def _to_status_row(session: Session, request: EmployeeTransferRequest) -> dict[str, str]:
    """`EmployeeTransferRequest` → kioskun "cari sorğu" sətrinin gözlədiyi açarlar.

    Açarlar `preview_data.TRANSFER_REQUEST_STATUS` (maket) ilə EYNİDİR
    (CLAUDE.md §6) — bax `group_a_kiosk.py::set_transfer_request`.
    """
    status_text = {
        "PENDING_APPROVAL": "Təsdiq gözləyir",
        "APPROVED": "Təsdiqləndi",
        "REJECTED": "Geri çəkildi" if request.is_withdrawn else "Rədd edildi",
    }.get(request.status.value, request.status.value)
    return {
        "id": str(request.id),
        "to_store": _store_name(session, request.to_store_id),
        "status": status_text,
        # Yalnız `PENDING_APPROVAL`-da "1" — `[Geri Çək]` düyməsi başqa
        # statusda görünməməlidir (görmək = səlahiyyət, kompasos-ui bənd 3).
        "withdrawable": "1" if not request.status.is_decided else "0",
        "decision_reason": request.decision_reason or "",
    }


def _employee_name(session: Session, employee_id: EmployeeId) -> str:
    """İşçi adı — tapılmazsa ID-nin qısa forması (`annual_leave.py` ilə eyni qərar)."""
    employee = session.uow.employees.get(employee_id)
    if employee is None:
        return f"#{str(employee_id)[:8]}"
    return str(employee.full_name)


def _store_name(session: Session, store_id: StoreId) -> str:
    """Mağaza adı — `controllers/screen_data.py::_store_name` ilə EYNİ sorğu."""
    row = session.uow.connection.execute(
        "SELECT name FROM stores WHERE id = %s", (store_id,)
    ).fetchone()
    return str(row["name"]) if row else "—"


def _destination_choices(session: Session, actor: Employee) -> list[tuple[str, str]]:
    """Aktiv filiallar, CARİ filial ÇIXARILMIŞ — `chk_transfer_store_diff` şərtinin GUI güzgüsü.

    `_store_choices` (`open_shift.py`) ilə EYNİ sorğu, YALNIZ `actor.store_id`
    süzgəci əlavədir: entity konstruktoru `from_store_id == to_store_id`-ni
    onsuz da rədd edir (`EmployeeTransferRequest.__init__`), lakin siyahıda
    saxlasaydıq işçi onu seçər, sonra domen istisnası ilə qarşılaşardı.
    """
    rows = session.uow.connection.execute(
        "SELECT id, name FROM stores WHERE tenant_id = %s AND is_active ORDER BY name",
        (session.tenant_id,),
    ).fetchall()
    return [(str(row["id"]), str(row["name"])) for row in rows if row["id"] != actor.store_id]


def _parse_request_id(request_id: str) -> TransferRequestId | None:
    try:
        return TransferRequestId(uuid.UUID(request_id))
    except ValueError:
        return None


__all__ = [
    "SUBMIT_CONFIRMATION",
    "WITHDRAW_CONFIRMATION",
    "EmployeeTransferController",
    "TransferRequestInboxController",
]
