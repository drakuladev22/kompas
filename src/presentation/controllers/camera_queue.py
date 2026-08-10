"""Kamera Operatoru növbəsinin yazı yolu — `[Vaxtı Əllə Təyin Et]`.

──────────────────────────────────────────────────────────────────────────────
NİYƏ HƏDD EKRANA ÖTÜRÜLÜR
──────────────────────────────────────────────────────────────────────────────
Dual-Control həddi `system_limits.DUAL_CONTROL_THRESHOLD_MINUTES`-dədir və
Root onu dəyişə bilir (bölmə 3). Modal isə "Fərq 37 dəqiqədir (30 dəqiqədən
çox)" mətnini GÖSTƏRİR. İki tərəf ayrı mənbədən oxusaydı, Root həddi 45-ə
qaldırdıqda operator ekranda "ikinci təsdiq lazımdır" görər, sistem isə
düzəlişi dərhal tətbiq edərdi — ekranın YALAN danışması ən pis haldır.

Ona görə hədd BURADA oxunur və dialoqa ötürülür; qərarı isə yenə use case
verir (`apply_override` eyni limiti oxuyur). Ekran yalnız xəbərdarlıq edir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ YALNIZ İCAZƏ SORĞULARI
──────────────────────────────────────────────────────────────────────────────
Növbə iki mənbəni birləşdirir (giriş təsdiqi + qayıdış təsdiqi), lakin manual
vaxt düzəlişi YALNIZ icazə sorğusunda var — `MorningCheckInUseCase`-də belə
əməliyyat yoxdur, çünki səhər girişində "sistem vaxtı ilə həqiqi vaxt"
fərqi anlayışı yoxdur (işçi ya gəlib, ya gəlməyib). Açar icazə sorğusuna
uyğun gəlmirsə istifadəçiyə səbəb göstərilir, sükutla heç nə edilmir.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_b import OperatorQueueScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)


class CameraQueueController:
    """Növbə ekranının `adjust_requested` siqnalını use case-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: OperatorQueueScreen) -> None:
        screen.adjust_requested.connect(lambda request_id: self._on_adjust(screen, request_id))

    # ------------------------------ düzəliş ---------------------------------- #

    def _on_adjust(self, screen: OperatorQueueScreen, request_id: str) -> None:
        try:
            details = self._load(request_id)
        except KompasOSError as error:
            screen.show_error(title="Düzəliş açıla bilmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception("OVERRIDE_LOAD_FAILED", extra={"request_id": request_id})
            screen.show_error(
                title="Düzəliş açıla bilmədi",
                message="Sorğu məlumatı oxuna bilmədi. Yenidən cəhd edin.",
            )
            return

        if details is None:
            screen.show_error(
                title="Bu sətir üçün düzəliş yoxdur",
                message="Manual vaxt düzəlişi yalnız qayıdış təsdiqinə tətbiq olunur.",
            )
            return

        from src.presentation.screens.group_b import ManualTimeOverrideDialog  # noqa: PLC0415

        dialog = ManualTimeOverrideDialog(
            screen.theme,
            employee_name=details["employee_name"],
            store_name=details["store_name"],
            kind="Qayıdış Təsdiqi",
            system_time=details["system_time_text"],
            threshold_minutes=details["threshold_minutes"],
            parent=screen,
        )
        dialog.submitted.connect(
            lambda time_text, reason: self._submit(
                screen,
                request_id=request_id,
                time_text=time_text,
                reason=reason,
                reference=details["reference_time"],
            )
        )
        dialog.exec()

    def _load(self, request_id: str) -> dict[str, Any] | None:
        """Dialoq üçün lazım olan hər şey — TƏK sessiyada."""
        with self._context.session(user_id=self._actor.id) as session:
            request = session.uow.leave_requests.get(_leave_id(request_id))
            if request is None:
                return None

            # Sistem qeydi: qayıdış iddiası varsa o, yoxdursa sorğu anı.
            # Operator məhz bu möhürü düzəldir (bölmə 4, Option B).
            reference = request.return_claimed_time or request.requested_time
            key = SystemLimitKey.DUAL_CONTROL_THRESHOLD_MINUTES
            threshold = session.limits.get_int(
                session.tenant_id, key.value, int(DEFAULT_LIMITS[key])
            )
            return {
                "employee_name": _employee_name(session, request.employee_id),
                "store_name": _store_name(session, request.store_id),
                "system_time_text": reference.astimezone().strftime("%H:%M"),
                "reference_time": reference,
                "threshold_minutes": threshold,
            }

    def _submit(
        self,
        screen: OperatorQueueScreen,
        *,
        request_id: str,
        time_text: str,
        reason: str,
        reference: datetime,
    ) -> None:
        overridden = _combine(reference, time_text)
        if overridden is None:
            screen.show_error(title="Vaxt oxunmadı", message="Vaxt formatı SS:DD olmalıdır.")
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.leave_verification.apply_override(
                    tenant_id=session.tenant_id,
                    operator_id=self._actor.id,
                    request_id=_leave_id(request_id),
                    overridden_time=overridden,
                    reason=reason,
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="Düzəliş yazılmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception("OVERRIDE_SAVE_FAILED", extra={"request_id": request_id})
            screen.show_error(
                title="Düzəliş yazılmadı",
                message="Dəyişiklik saxlanmadı. Yenidən cəhd edin.",
            )
            return

        self._refresh(screen)

    def _refresh(self, screen: OperatorQueueScreen) -> None:
        """Növbəni yenidən oxuyur — düzəlişdən sonra sətir dəyişir."""
        from src.presentation.controllers.screen_data import ScreenDataBinder  # noqa: PLC0415

        ScreenDataBinder(self._context, self._actor).populate("live_queue", screen)


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _leave_id(raw: str) -> Any:
    from src.domain.value_objects.identifiers import LeaveRequestId  # noqa: PLC0415

    return LeaveRequestId(uuid.UUID(raw))


def _combine(reference: datetime, time_text: str) -> datetime | None:
    """ "SS:DD" mətnini sistem qeydinin GÜNÜ ilə birləşdirir.

    Gün DƏYİŞMİR. Düzəliş çox vaxt sistem qeydindən ƏVVƏLƏ olur ("işçi əslində
    13:40-da qayıtmışdı, 14:10-da yox") — ona görə "əvvəldirsə növbəti günə
    keçir" məntiqi burada YANLIŞ olardı: normal iş halını gecə yarısı hadisəsi
    kimi oxuyardı. Dialoqda yalnız saat sahəsi var, deməli operator onsuz da
    günü dəyişə bilmir.
    """
    try:
        parsed = datetime.strptime(time_text.strip(), "%H:%M")  # noqa: DTZ007 - yalnız SS:DD
    except ValueError:
        return None
    hour, minute = parsed.hour, parsed.minute

    local = reference.astimezone()
    combined = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return combined.astimezone(reference.tzinfo)


def _employee_name(session: Session, employee_id: Any) -> str:
    employee = session.uow.employees.get(employee_id)
    return f"#{str(employee_id)[:8]}" if employee is None else str(employee.full_name)


def _store_name(session: Session, store_id: Any) -> str:
    row = session.uow.connection.execute(
        "SELECT name FROM stores WHERE id = %s AND tenant_id = %s",
        (store_id, session.tenant_id),
    ).fetchone()
    return str(row["name"]) if row else f"#{str(store_id)[:8]}"


__all__ = ["CameraQueueController"]
