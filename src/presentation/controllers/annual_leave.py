"""İllik məzuniyyətin YAZI yolu — #28, kompas1.md Faza 4.

İki kontroller, iki ekran, BİR use case:

    `EmployeeAnnualLeaveController` → İşçi Ana Ekranı (kiosk): öz balansını
                                      oxuyur, `[Məzuniyyət Sorğusu]` göndərir.
    `AnnualLeaveInboxController`    → «Məzuniyyət Sorğuları» ekranı (HR):
                                      təsdiq növbəsi, `[Təsdiqlə]`/`[Rədd Et]`.

──────────────────────────────────────────────────────────────────────────────
NİYƏ ÖZ KONTROLLERİ VAR (CLAUDE.md §6)
──────────────────────────────────────────────────────────────────────────────
Hər iki ekran HƏM oxuyur, HƏM yazır və hər yazıdan sonra siyahı YENİDƏN
oxunmalıdır:

  * kioskda sorğu göndərildikdən sonra balans SƏTRİ yaranır (`_ensure_balance`)
    və "—" göstərən kart dərhal həqiqi rəqəmi göstərməlidir;
  * HR növbəsində qərar verilmiş sorğu `list_pending`-dən ÇIXIR — siyahıda
    qalsaydı, HR onu ikinci dəfə təsdiqləməyə çalışar və "artıq qərar
    verilib" istisnası ilə qarşılaşardı.

Bu dövrə `populate()`-ın tək çağırışından uzun yaşayır, ona görə
`screen_data.py` bağlaması yararsızdır (`controllers/announcements.py` və
`controllers/exceptions.py` ilə eyni qərar).

SESSİYA SAXLANILMIR: hər əməliyyat üçün yeni sessiya açılır və commit edilir.
HR paneli saatlarla açıq qala bilər; uzun-ömürlü tranzaksiya bu müddət boyu
`annual_leave_balances` sətirlərində kilid saxlayardı və `consume()`-un şərti
`UPDATE`-i (paralel təsdiqə qarşı yeganə qoruma) bloklanardı — yəni məhz
#28-in qorumaq istədiyi şey sıradan çıxardı.

──────────────────────────────────────────────────────────────────────────────
KİOSKDA İSTİSNA EKRANA ÇIXMIR
──────────────────────────────────────────────────────────────────────────────
`controllers/kiosk.py` başlığındakı qayda burada da keçərlidir: kiosk PC-si
PAYLAŞILAN cihazdır və orada istisna ilə çökən ekran bütün mağazanı
bloklayardı. İşçi tərəfindəki hər nəticə — balansın çatmaması, üst-üstə düşən
sorğu, keçmiş tarix — `screen.set_annual_leave_message(...)` mətninə çevrilir
və mətn HƏMİŞƏ `error.user_message`-dən gəlir: xam istisna sətri
(`str(error)`) daxili kontekst daşıyır və istifadəçiyə göstərilmir.

──────────────────────────────────────────────────────────────────────────────
BU, GÜNDAXİLİ İCAZƏ DEYİL
──────────────────────────────────────────────────────────────────────────────
`session.leave_verification` (STEP1/STEP2, DƏQİQƏ) və `session.shift_planning`
(Shift Matrix istirahət günü) BU FAYLDAN heç vaxt çağırılmır. Üçü də eyni
sessiyada yaşayır, lakin ayrı mexanizmlərdir (bax `Session.annual_leave`
şərhi) — bir kontrollerin ikisini birləşdirməsi həmin sərhədi silərdi.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import TYPE_CHECKING

from src.domain.value_objects.identifiers import AnnualLeaveRequestId
from src.presentation.controllers.screen_data import _WEEKDAYS_AZ
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from decimal import Decimal

    from src.application.use_cases.annual_leave import AnnualLeaveBalanceView
    from src.domain.entities.annual_leave import AnnualLeaveRequest
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.annual_leave import AnnualLeaveInboxScreen
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Rədd səbəbi dialoqunun mətni — səbəb domendə MƏCBURİDİR
#: (`AnnualLeaveRequest.reject`) və işçiyə gedən bildirişin İÇİNDƏ göstərilir,
#: ona görə boş cavab yazı yoluna ümumiyyətlə göndərilmir.
_REJECT_PROMPT = (
    "Rədd səbəbi (məcburi) — işçiyə göndərilən bildirişdə göstərilir və audit jurnalına düşür:"
)

#: Sorğu göndərildikdən sonrakı təsdiq mətni.
SUBMIT_CONFIRMATION = "Məzuniyyət sorğunuz təsdiq üçün göndərildi."

#: Balans oxunmadıqda kioskda göstərilən mətn — kart boş qalır, ekran çökmür.
BALANCE_READ_FAILED = "Məzuniyyət balansı yüklənmədi."


class EmployeeAnnualLeaveController:
    """İşçi Ana Ekranının "İllik Məzuniyyət" kartı."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: EmployeeHomeScreen) -> None:
        """Siqnalı bağlayır və kartı ilk dəfə doldurur."""
        screen.annual_leave_request_requested.connect(lambda: self._on_request(screen))
        self.refresh(screen)

    def refresh(self, screen: EmployeeHomeScreen, *, message: str = "") -> None:
        """Öz balansını bazadan yenidən oxuyur.

        `my_balance` SƏLAHİYYƏT TƏLƏB ETMİR — hər işçi öz haqqını görür (bax
        `AnnualLeaveUseCase.my_balance` başlığı). Ona görə burada flag
        yoxlaması YOXDUR: onu əlavə etmək işçini öz balansından kəsərdi.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                view = session.annual_leave.my_balance(
                    tenant_id=session.tenant_id, employee=self._actor
                )
                row = _to_balance_row(view)
        except KompasOSError as error:
            # Domen istisnası da kioskda MƏTNDİR — modal pəncərə açılmır.
            screen.set_annual_leave_balance({})
            screen.set_annual_leave_message(error.user_message)
            return
        except Exception:
            _error_log.exception("ANNUAL_LEAVE_BALANCE_READ_FAILED")
            screen.set_annual_leave_balance({})
            screen.set_annual_leave_message(BALANCE_READ_FAILED)
            return

        screen.set_annual_leave_balance(row)
        screen.set_annual_leave_message(message)

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_request(self, screen: EmployeeHomeScreen) -> None:
        """`[Məzuniyyət Sorğusu]` — dialoq açılır, seçim use case-ə gedir."""
        from src.presentation.screens.annual_leave import (  # noqa: PLC0415
            AnnualLeaveRequestDialog,
        )

        try:
            with self._context.session(user_id=self._actor.id) as session:
                view = session.annual_leave.my_balance(
                    tenant_id=session.tenant_id, employee=self._actor
                )
        except Exception:
            _error_log.exception("ANNUAL_LEAVE_DIALOG_DATA_FAILED")
            screen.set_annual_leave_message("Məzuniyyət forması açılmadı. Yenidən cəhd edin.")
            return

        days = _day_choices(year=view.year)
        if not days:
            # Müdafiə xətti: cari balans ili artıq keçibsə seçiləcək gün
            # qalmır. Boş dialoq açmaq işçini çıxılmaz vəziyyətdə qoyardı.
            screen.set_annual_leave_message("Seçilə bilən tarix yoxdur.")
            return

        dialog = AnnualLeaveRequestDialog(
            screen.theme,
            days=days,
            balance_hint=f"Balansınızda {_day_number(view.available_days)} gün qalıb.",
            parent=screen,
        )
        dialog.submitted.connect(lambda start, end: self._submit(screen, start, end))
        dialog.exec()

    def _submit(self, screen: EmployeeHomeScreen, start: str, end: str) -> None:
        try:
            start_date = date.fromisoformat(start)
            end_date = date.fromisoformat(end)
        except ValueError:
            screen.set_annual_leave_message("Seçilmiş tarixlər düzgün deyil.")
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.annual_leave.submit(
                    tenant_id=session.tenant_id,
                    employee=self._actor,
                    start_date=start_date,
                    end_date=end_date,
                )
                session.commit()
        except KompasOSError as error:
            # Balansın çatmaması, üst-üstə düşən məzuniyyət və keçmiş tarix
            # bura düşür — mesaj domendən gəlir, burada YENİDƏN yazılmır.
            self.refresh(screen, message=error.user_message)
            return
        except Exception:
            _error_log.exception("ANNUAL_LEAVE_SUBMIT_FAILED")
            self.refresh(screen, message="Sorğu göndərilmədi. Yenidən cəhd edin.")
            return

        # Yazıdan SONRA balans yenidən oxunur: sorğu balansı hələ AZALTMIR
        # (yalnız təsdiq azaldır), lakin ilk sorğu balans sətrini YARADIR və
        # "Balans məlumatı yoxdur" mətni artıq yalan olardı.
        self.refresh(screen, message=SUBMIT_CONFIRMATION)


class AnnualLeaveInboxController:
    """«Məzuniyyət Sorğuları» ekranı — `can_manage_leave_balances` (HR)."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: AnnualLeaveInboxScreen) -> None:
        screen.approve_requested.connect(lambda request_id: self._on_approve(screen, request_id))
        screen.reject_requested.connect(lambda request_id: self._on_reject(screen, request_id))
        screen.refresh_requested.connect(lambda: self.refresh(screen))
        self.refresh(screen)

    def refresh(self, screen: AnnualLeaveInboxScreen) -> None:
        """Təsdiq gözləyən sorğuları yenidən oxuyur."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                requests = session.annual_leave.pending_inbox(
                    tenant_id=session.tenant_id, actor=self._actor
                )
                rows = [_to_inbox_row(session, request) for request in requests]
        except KompasOSError as error:
            # Səlahiyyəti olmayan istifadəçi bu ekranı ümumiyyətlə görməməli
            # idi (menyu flag-i), lakin görsə — səbəb AÇIQ yazılır.
            screen.set_requests([])
            screen.show_error(title="Məzuniyyət sorğuları oxunmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception("ANNUAL_LEAVE_INBOX_LIST_FAILED")
            screen.set_requests([])
            screen.show_error(
                title="Məzuniyyət sorğuları oxunmadı",
                message="Siyahı oxuna bilmədi. Yenidən cəhd edin.",
            )
            return

        screen.set_requests(rows)

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_approve(self, screen: AnnualLeaveInboxScreen, request_id: str) -> None:
        """`[Təsdiqlə]` — balans DB qatında şərti `UPDATE` ilə azalır.

        `employee` arqumenti use case-in tələbidir (`hire_date` lazımdır) və
        BURADA, eyni sessiyada təzə oxunur — ekran sətrindən GƏTİRİLMİR.
        Səbəb: sətir bir neçə dəqiqə əvvəl oxunmuş ola bilər, işçinin işə
        qəbul tarixi isə bu arada HR tərəfindən düzəldilə bilər; köhnə dəyər
        haqqın SƏHV hesablanmasına gətirərdi.
        """
        parsed_id = _parse_request_id(request_id)
        if parsed_id is None:
            screen.show_error(
                title="Sorğu təsdiqlənmədi", message="Sorğu identifikatoru düzgün deyil."
            )
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                employee = _request_employee(session, parsed_id)
                if employee is None:
                    screen.show_error(
                        title="Sorğu təsdiqlənmədi",
                        message="Sorğunun sahibi olan işçi tapılmadı.",
                    )
                    return
                session.annual_leave.approve(
                    tenant_id=session.tenant_id,
                    approver=self._actor,
                    request_id=parsed_id,
                    employee=employee,
                )
                session.commit()
        except KompasOSError as error:
            # Paralel təsdiq, çatmayan balans və "artıq qərar verilib" halları
            # bura düşür — HR AÇIQ cavab alır və siyahı yenilənir.
            screen.show_error(title="Sorğu təsdiqlənmədi", message=error.user_message)
            self.refresh(screen)
            return
        except Exception:
            _error_log.exception("ANNUAL_LEAVE_APPROVE_FAILED", extra={"request_id": request_id})
            screen.show_error(
                title="Sorğu təsdiqlənmədi",
                message="Dəyişiklik yazılmadı. Yenidən cəhd edin.",
            )
            return

        self.refresh(screen)

    def _on_reject(self, screen: AnnualLeaveInboxScreen, request_id: str) -> None:
        """`[Rədd Et]` — səbəb MƏCBURİDİR (domen qaydası)."""
        parsed_id = _parse_request_id(request_id)
        if parsed_id is None:
            screen.show_error(
                title="Sorğu rədd edilmədi", message="Sorğu identifikatoru düzgün deyil."
            )
            return

        reason = self._ask_reason(screen)
        if reason is None:
            # İmtina edilmiş və ya BOŞ cavab: yazı yoluna ümumiyyətlə
            # girmirik — domen istisnası ilə "cəzalandırmaq" mənasızdır.
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.annual_leave.reject(
                    tenant_id=session.tenant_id,
                    approver=self._actor,
                    request_id=parsed_id,
                    reason=reason,
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="Sorğu rədd edilmədi", message=error.user_message)
            self.refresh(screen)
            return
        except Exception:
            _error_log.exception("ANNUAL_LEAVE_REJECT_FAILED", extra={"request_id": request_id})
            screen.show_error(
                title="Sorğu rədd edilmədi",
                message="Dəyişiklik yazılmadı. Yenidən cəhd edin.",
            )
            return

        self.refresh(screen)

    @staticmethod
    def _ask_reason(screen: AnnualLeaveInboxScreen) -> str | None:
        from PySide6.QtWidgets import QInputDialog  # noqa: PLC0415

        text, accepted = QInputDialog.getMultiLineText(
            screen, "Məzuniyyət sorğusunu rədd et", _REJECT_PROMPT
        )
        cleaned = text.strip()
        return cleaned if accepted and cleaned else None


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _to_balance_row(view: AnnualLeaveBalanceView) -> dict[str, str]:
    """`AnnualLeaveBalanceView` → kartın FAKTİKİ gözlədiyi açarlar.

    Açarlar `preview_data.ANNUAL_LEAVE_BALANCE` ilə EYNİDİR (CLAUDE.md §6) —
    burada öz sözlüyümüzü qursaydıq, maket və canlı yol fərqli ad məkanlarına
    düşərdi (`menu.py` başlığındakı tarixi qüsur).

    Rəqəmlər SƏTRƏ çevrilir, lakin FORMATLANMIR: "14/21" cümləsini ekran
    özü qurur (bax `AnnualLeaveBalanceView` docstring-i).
    """
    return {
        "year": str(view.year),
        "available": _day_number(view.available_days),
        "total": _day_number(view.total_days),
        "used": _day_number(view.used_days),
        "carried_over": _day_number(view.carried_over_days),
        "carryover_deadline": view.carryover_deadline.strftime("%d.%m.%Y"),
        "carryover_expired": "1" if view.carryover_expired else "0",
    }


def _to_inbox_row(session: Session, request: AnnualLeaveRequest) -> dict[str, str]:
    """`AnnualLeaveRequest` → HR növbəsinin FAKTİKİ gözlədiyi açarlar."""
    return {
        "id": str(request.id),
        "employee": _employee_name(session, request),
        "range_text": (
            f"{request.start_date.strftime('%d.%m.%Y')} – {request.end_date.strftime('%d.%m.%Y')}"
        ),
        # TƏQVİM günü göstərilir, balansdan çıxılacaq gün YOX: sonuncu Shift
        # Matrix-ə görə TƏSDİQ ANINDA hesablanır (`_deducted_days`) və indi
        # göstərilən rəqəm təsdiqə qədər dəyişə bilərdi — yəni ekran söz
        # verib saxlamadığı bir ədəd yazardı.
        "days_text": f"{request.calendar_days} təqvim günü",
        "submitted": request.created_at.astimezone().strftime("%d.%m.%Y %H:%M"),
    }


def _employee_name(session: Session, request: AnnualLeaveRequest) -> str:
    """İşçi adı — tapılmazsa ID-nin qısa forması.

    Sətri GİZLƏTMİRİK: işçi qeydi oxunmasa belə sorğu təsdiq gözləyir və HR
    onu görməlidir (`controllers/exceptions.py::_employee_name` ilə eyni qərar).
    """
    employee = session.uow.employees.get(request.employee_id)
    if employee is None:
        return f"#{str(request.employee_id)[:8]}"
    return str(employee.full_name)


def _request_employee(session: Session, request_id: AnnualLeaveRequestId) -> Employee | None:
    """Sorğunun sahibi — təsdiq üçün MƏCBURİ (`hire_date`).

    Sorğu tapılmasa `None` qaytarılır və use case ÇAĞIRILMIR; belə halda
    `approve` onsuz da `AnnualLeaveRequestNotFoundError` atardı, lakin biz o
    vaxta qədər səhv işçi obyektini ötürmüş olardıq.
    """
    request = session.uow.repository("annual_leave_requests").get(request_id)
    if request is None:
        return None
    employee: Employee | None = session.uow.employees.get(request.employee_id)
    return employee


def _parse_request_id(request_id: str) -> AnnualLeaveRequestId | None:
    try:
        return AnnualLeaveRequestId(uuid.UUID(request_id))
    except ValueError:
        return None


def _day_label(day: date) -> str:
    """«14.09.2026 · Ber» — həftə günü olmadan işçi ritmi görə bilmir."""
    return f"{day.strftime('%d.%m.%Y')} · {_WEEKDAYS_AZ[day.weekday()]}"


def _day_choices(*, year: int) -> list[tuple[str, str]]:
    """Dialoqdakı tarix siyahısı — bugündən CARİ BALANS İLİNİN sonunadək.

    ──────────────────────────────────────────────────────────────────────────
    HORİZONT NİYƏ MƏHZ 31 DEKABRDIR (VƏ NİYƏ YENİ ROOT PARAMETRİ DEYİL)
    ──────────────────────────────────────────────────────────────────────────
    `AnnualLeaveUseCase._charge_year` sorğunu BAŞLANĞIC tarixinin ilindən
    çıxır. Kart isə `my_balance`-ın qaytardığı İLİ göstərir. Siyahı gələn ilin
    tarixlərini də təklif etsəydi, işçi ekranda "14/21 gün qalıb" (cari il)
    görüb GƏLƏN ilin balansından çıxılan sorğu göndərərdi — ekran onda yalan
    danışardı. Yəni hədd ixtiyari bir ədəd DEYİL, kartda göstərilən rəqəmin
    özündən çıxan nəticədir; ona görə yeni `system_limits` açarı yaradılmır.

    Bugün DAXİLDİR: "sabahdan məzuniyyət" halı ən çox işlədiləcək haldır və
    keçmiş tarix qapısı (`submit`) onsuz da bugünə toxunmur.
    """
    today = date.today()  # noqa: DTZ011 — təqvim GÜNÜ, an deyil; `Clock` portu
    # domen qərarları üçündür (`AnnualLeaveUseCase._today` onu işlədir), burada
    # isə yalnız seçim siyahısı qurulur və HƏQİQİ tarix yoxlaması use case-dədir.
    last_day = date(year, 12, 31)
    if last_day < today:
        return []
    span = (last_day - today).days
    return [
        (day.isoformat(), _day_label(day))
        for day in (today + timedelta(days=offset) for offset in range(span + 1))
    ]


def _day_number(value: Decimal) -> str:
    """`Decimal("14.00")` → "14", `Decimal("14.50")` → "14.5".

    Balans `NUMERIC(5,2)`-dir və xam `str()` ekranda "14.00/21.00 gün qalıb"
    yazardı. Yarım gün İSTİFADƏ OLUNUR (`ANNUAL_LEAVE_ACCRUAL_RATE_DAYS_PER_
    PERIOD` kəsr ola bilər), ona görə kəsr hissə ATILMIR — yalnız mənasız
    sıfırlar kəsilir.
    """
    if value == value.to_integral_value():
        return str(value.to_integral_value())
    return format(value.normalize(), "f")


__all__ = [
    "BALANCE_READ_FAILED",
    "SUBMIT_CONFIRMATION",
    "AnnualLeaveInboxController",
    "EmployeeAnnualLeaveController",
]
