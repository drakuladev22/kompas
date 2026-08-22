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

from src.domain.entities.attendance_record import MIN_REJECT_REASON_LENGTH
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
        screen.approve_requested.connect(lambda request_id: self._on_approve(screen, request_id))
        screen.reject_requested.connect(lambda request_id: self._on_reject(screen, request_id))

    # ------------------------------- təsdiq ---------------------------------- #

    def _on_approve(self, screen: OperatorQueueScreen, request_id: str) -> None:
        """`[Təsdiqlə]` — STEP 3 (qayıdış) və ya STEP C (giriş).

        Növbə BİRLƏŞMİŞDİR (bölmə 4), ona görə açarın hansı mənbəyə aid
        olduğu ƏVVƏLCƏ müəyyən edilir: icazə sorğusu tapılmasa davamiyyət
        qeydi yoxlanılır. Səhv mənbəyə müraciət `KeyError` yox, aydın mesaj
        verməlidir.
        """
        self._run(
            screen,
            request_id=request_id,
            leave_action=self._verify_return,
            attendance_action=lambda session, record: session.morning_check_in.verify(
                tenant_id=session.tenant_id,
                operator_id=self._actor.id,
                employee_id=record.employee_id,
                work_date=record.work_date,
            ),
            failure_title="Təsdiq yazılmadı",
        )

    def _on_reject(self, screen: OperatorQueueScreen, request_id: str) -> None:
        """`[Rədd Et]` — səbəb MƏCBURİDİR (bölmə 4, STEP C düzəlişi).

        Rədd YALNIZ giriş təsdiqinə (Morning Check-in) aiddir: qayıdış
        təsdiqində "rədd" anlayışı yoxdur — orada operator ya təsdiqləyir,
        ya vaxtı əllə düzəldir (`[Vaxtı Əllə Təyin Et]`).
        """
        reason = self._ask_reason(screen)
        if reason is None:
            return

        self._run(
            screen,
            request_id=request_id,
            leave_action=None,
            attendance_action=lambda session, record: session.morning_check_in.reject(
                tenant_id=session.tenant_id,
                operator_id=self._actor.id,
                employee_id=record.employee_id,
                work_date=record.work_date,
                reason=reason,
            ),
            failure_title="Rədd yazılmadı",
        )

    @staticmethod
    def _ask_reason(screen: OperatorQueueScreen) -> str | None:
        """Səbəb dialoqu — QISA cavab yazı yoluna ÜMUMİYYƏTLƏ girmir.

        Hədd `10` əvvəl BURADA hərfi yazılmışdı və heç nə onu yoxlamırdı: mətn
        rəqəmi vəd edirdi, kod isə bir simvolu da buraxırdı. İki nəticəsi
        vardı — (a) operator qısa səbəb yazanda modal bağlanır, domen istisna
        atır və YAZILAN MƏTN İTİR; (b) `MIN_REJECT_REASON_LENGTH` domendə
        dəyişsəydi dialoq sükutla yalan rəqəm göstərərdi. İndi hədd domendən
        İDXAL olunur və dialoqun ÖZÜNDƏ yoxlanılır.

        ──────────────────────────────────────────────────────────────────────
        DEEP-GAP U9 — QISA CAVABDA YAZILAN MƏTN YENƏ İTİRDİ
        ──────────────────────────────────────────────────────────────────────
        Yuxarıdakı (a) düzəlişi istisnanı aradan qaldırdı, LAKİN mətn itkisini
        yox: xəbərdarlıqdan sonra `return None` edilirdi və `cleaned` heç yerə
        ötürülmürdü — operator "Girişi rədd et" dialoqunu YENİDƏN açanda BOŞ
        sahə görürdü, halbuki əvvəl yazdığı (sadəcə qısa) mətn hələ də
        etibarlı başlanğıc nöqtəsi idi. İndi dövrə YAZILAN MƏTNİ SAXLAYIR və
        dialoqu `value=` ilə YENİDƏN açır — operator sıfırdan yazmır, sadəcə
        əlavə edir.
        """
        from PySide6.QtWidgets import QInputDialog, QMessageBox  # noqa: PLC0415

        prompt = (
            f"Səbəb (məcburi, minimum {MIN_REJECT_REASON_LENGTH} simvol) — audit\n"
            "jurnalına düşür və HR_Admin ilə Mağaza Menecerinə bildiriş gedir:"
        )
        text = ""
        while True:
            text, accepted = QInputDialog.getMultiLineText(screen, "Girişi rədd et", prompt, text)
            if not accepted:
                return None
            cleaned = text.strip()
            if len(cleaned) >= MIN_REJECT_REASON_LENGTH:
                return cleaned
            # Modal, `show_error` DEYİL: növbənin qalan sətirləri etibarlıdır
            # və operator onları görməyə davam etməlidir.
            box = QMessageBox(screen)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Rədd yazılmadı")
            box.setText(f"Səbəb ən azı {MIN_REJECT_REASON_LENGTH} simvol olmalıdır.")
            box.exec()
            # `text` (XAM, budaqsız) burada QƏSDƏN SAXLANILIR — dövrə
            # `QInputDialog`-u `value=text` ilə yenidən açır.

    def _verify_return(self, session: Session, request: Any) -> None:
        """STEP 3 Saga-sı `async`-dir — GUI-də sinxron icra edilir.

        `asyncio.run` burada təhlükəsizdir, çünki Qt hadisə dövrəsində fəal
        `asyncio` dövrəsi yoxdur; use case isə Saga orkestratoruna görə
        `async` olaraq qalır (kompensasiya addımları belə tələb edir).
        """
        import asyncio  # noqa: PLC0415

        asyncio.run(
            session.leave_verification.verify_return(
                tenant_id=session.tenant_id,
                operator_id=self._actor.id,
                request_id=request.id,
            )
        )

    @staticmethod
    def _notify(screen: OperatorQueueScreen, *, title: str, message: str) -> None:
        """Bloklayan, LAKİN YIXICI OLMAYAN xəbərdarlıq (DEEP-GAP U8).

        ──────────────────────────────────────────────────────────────────────
        `screen.show_error()` NİYƏ İŞLƏDİLMİR
        ──────────────────────────────────────────────────────────────────────
        `Screen.show_error()` bütün ekranın MƏZMUNUNU bir sətrin uğursuzluğu
        ilə ƏVƏZ EDİR (bax `screens/base.py::ContentSwitcher._present`) —
        halbuki bu ekranda göstərilən DİGƏR növbə sətirləri etibarlıdır və
        operator onlarla işini davam etdirməlidir. Doqquz çağırış nöqtəsi
        (təsdiq/rədd/düzəliş yolları) məhz bu qaydanı pozurdu: 14 sətirlik
        növbədə YALNIZ 1 sətir uğursuz olanda operator qalan 13-ü İTİRİRDİ,
        `on_retry` da verilmədiyi üçün bərpa yolu yalnız başqa ekrana keçib
        qayıtmaq idi. Eyni qərar artıq `_ask_reason`-da var idi — bura o
        naxışı GENİŞLƏNDİRİR.

        `on_retry` YOXDUR: modalın ÖZÜ "OK" düyməsi ilə bağlanır, əməliyyatı
        təkrarlamaq üçün operator eyni sətrin düyməsinə YENİDƏN basa bilər —
        növbə silinmədiyi üçün bu mümkündür.
        """
        from PySide6.QtWidgets import QMessageBox  # noqa: PLC0415

        box = QMessageBox(screen)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText(message)
        box.exec()

    def _run(
        self,
        screen: OperatorQueueScreen,
        *,
        request_id: str,
        leave_action: Any,
        attendance_action: Any,
        failure_title: str,
    ) -> None:
        """Açarı düzgün mənbəyə yönləndirib əməliyyatı icra edir."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                request = session.uow.leave_requests.get(_leave_id(request_id))
                if request is not None:
                    if leave_action is None:
                        self._notify(
                            screen,
                            title="Bu sətir rədd edilə bilməz",
                            message=(
                                "Qayıdış təsdiqində rədd yoxdur — təsdiqləyin "
                                "və ya vaxtı əllə düzəldin."
                            ),
                        )
                        return
                    leave_action(session, request)
                else:
                    record = session.uow.attendance.get(_attendance_id(request_id))
                    if record is None:
                        self._notify(
                            screen,
                            title="Sorğu tapılmadı",
                            message="Bu sətir artıq emal edilib. Növbəni yeniləyin.",
                        )
                        return
                    attendance_action(session, record)
                session.commit()
        except KompasOSError as error:
            self._notify(screen, title=failure_title, message=error.user_message)
            return
        except Exception:
            _error_log.exception("QUEUE_ACTION_FAILED", extra={"request_id": request_id})
            self._notify(
                screen,
                title=failure_title,
                message="Əməliyyat tamamlanmadı. Yenidən cəhd edin.",
            )
            return

        self._refresh(screen)

    # ------------------------------ düzəliş ---------------------------------- #

    def _on_adjust(self, screen: OperatorQueueScreen, request_id: str) -> None:
        try:
            details = self._load(request_id)
        except KompasOSError as error:
            self._notify(screen, title="Düzəliş açıla bilmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception("OVERRIDE_LOAD_FAILED", extra={"request_id": request_id})
            self._notify(
                screen,
                title="Düzəliş açıla bilmədi",
                message="Sorğu məlumatı oxuna bilmədi. Yenidən cəhd edin.",
            )
            return

        if details is None:
            self._notify(
                screen,
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
            # DEEP-GAP U8 — eyni siyahının onuncu üzvü: format səhvi başqa
            # sətirlərin görünüşünü poza bilməz, ona görə `_notify` (bax
            # onun başlığı), `show_error` yox.
            self._notify(screen, title="Vaxt oxunmadı", message="Vaxt formatı SS:DD olmalıdır.")
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
            self._notify(screen, title="Düzəliş yazılmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception("OVERRIDE_SAVE_FAILED", extra={"request_id": request_id})
            self._notify(
                screen,
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


def _attendance_id(raw: str) -> Any:
    from src.domain.value_objects.identifiers import AttendanceRecordId  # noqa: PLC0415

    return AttendanceRecordId(uuid.UUID(raw))


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
