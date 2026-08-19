"""Açıq Növbə Bazarının YAZI yolu (#16, kompasos11.md Faza 6).

İki kontroller, iki ekran, BİR use case:

    `EmployeeOpenShiftController`  → İşçi Ana Ekranı (kiosk): siyahını oxuyur,
                                     `[Bu Növbəni Götür]` basılanda tutur.
    `ShiftMatrixOpenShiftController` → Növbə Planlama ekranı (admin): elan
                                     edir, ləğv edir, açıq siyahını göstərir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ ÖZ KONTROLLERİ VAR (CLAUDE.md §6)
──────────────────────────────────────────────────────────────────────────────
Hər iki ekran HƏM oxuyur, HƏM yazır və hər yazıdan sonra siyahı YENİDƏN
oxunmalıdır — tutulmuş elan siyahıda qalsaydı, işçi onu ikinci dəfə basar və
"bu növbəni artıq başqası götürüb" mesajını ÖZ tutduğu növbə üçün alardı.
Bu dövrə `populate()`-ın tək çağırışından uzun yaşayır, ona görə
`screen_data.py` bağlaması yararsızdır (`controllers/exceptions.py` ilə eyni
qərar).

SESSİYA SAXLANILMIR: hər əməliyyat üçün yeni sessiya açılır və commit edilir.
Növbə Planlama paneli saatlarla açıq qala bilər; uzun-ömürlü tranzaksiya bu
müddət boyu `open_shift_postings` sətirlərində kilid saxlayardı və `claim()`
axını (`SELECT ... FOR UPDATE`) tamamilə bloklanardı — yəni məhz #16-nın
qorumaq istədiyi şey sıradan çıxardı.

──────────────────────────────────────────────────────────────────────────────
KİOSKDA İSTİSNA EKRANA ÇIXMIR
──────────────────────────────────────────────────────────────────────────────
`controllers/kiosk.py` başlığındakı qayda burada da keçərlidir: kiosk PC-si
PAYLAŞILAN cihazdır və orada istisna ilə çökən ekran bütün mağazanı
bloklayardı. Ona görə işçi tərəfindəki hər nəticə — o cümlədən yarışı
uduzmaq — `screen.set_open_shift_message(...)` mətninə çevrilir.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import TYPE_CHECKING

from src.application.use_cases.open_shift_market import (
    FALLBACK_MAX_LEAD_DAYS,
)
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.identifiers import (
    OpenShiftPostingId,
    StoreId,
    WorkModeId,
)
from src.presentation.controllers.screen_data import _WEEKDAYS_AZ
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.application.use_cases.open_shift_market import OpenShiftView
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen
    from src.presentation.screens.group_c import ShiftPlanningScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Ləğv səbəbi dialoqunun mətni — səbəb domendə MƏCBURİDİR (`OpenShiftPosting.
#: cancel`), ona görə boş cavab yazı yoluna ümumiyyətlə göndərilmir.
_CANCEL_PROMPT = (
    "Elanın ləğv səbəbi (məcburi) — elanı görmüş işçilər üçün izahdır və audit jurnalına düşür:"
)


class EmployeeOpenShiftController:
    """İşçi Ana Ekranının "Açıq Növbələr" kartı."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: EmployeeHomeScreen) -> None:
        """Siqnalı bağlayır və kartı ilk dəfə doldurur."""
        screen.open_shift_claim_requested.connect(
            lambda posting_id: self._on_claim(screen, posting_id)
        )
        self.refresh(screen)

    def refresh(self, screen: EmployeeHomeScreen, *, message: str = "") -> None:
        """Uyğun açıq elanları bazadan yenidən oxuyur."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                views = session.open_shifts.list_for_employee(
                    tenant_id=session.tenant_id, employee=self._actor
                )
                rows = [_to_employee_row(session, view) for view in views]
        except Exception:
            # Kioskda siyahı oxunmaması ekranı SINDIRMAMALIDIR: işçinin əsas
            # axını (giriş/icazə/qayıdış) açıq növbədən asılı deyil.
            _error_log.exception("OPEN_SHIFT_LIST_FAILED")
            screen.set_open_shifts([])
            screen.set_open_shift_message("Açıq növbə siyahısı yüklənmədi.")
            return

        screen.set_open_shifts(rows)
        if message:
            screen.set_open_shift_message(message)

    def _on_claim(self, screen: EmployeeHomeScreen, posting_id: str) -> None:
        """`[Bu Növbəni Götür]` — nəticə HƏMİŞƏ mətnlə bildirilir."""
        try:
            parsed_id = OpenShiftPostingId(uuid.UUID(posting_id))
        except ValueError:
            screen.set_open_shift_message("Elan identifikatoru düzgün deyil.")
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.open_shifts.claim(
                    tenant_id=session.tenant_id,
                    employee=self._actor,
                    posting_id=parsed_id,
                )
                session.commit()
        except KompasOSError as error:
            # Yarışı uduzmaq da bura düşür (`OpenShiftAlreadyClaimedError`) —
            # mesaj domendən gəlir, burada YENİDƏN yazılmır.
            self.refresh(screen, message=error.user_message)
            return
        except Exception:
            _error_log.exception("OPEN_SHIFT_CLAIM_FAILED", extra={"posting_id": posting_id})
            self.refresh(screen, message="Növbə götürülmədi. Yenidən cəhd edin.")
            return

        # Yazıdan SONRA siyahı yenidən oxunur — tutulmuş elan artıq açıq
        # deyil və siyahıda qalması yalan olardı.
        self.refresh(screen, message="Növbə sizin adınıza yazıldı.")


class ShiftMatrixOpenShiftController:
    """Növbə Planlama ekranındakı "Açıq Növbə Bazarı" kartı (admin)."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: ShiftPlanningScreen) -> None:
        screen.open_shift_post_requested.connect(lambda: self._on_post(screen))
        screen.open_shift_cancel_requested.connect(
            lambda posting_id: self._on_cancel(screen, posting_id)
        )
        self.refresh(screen)

    def refresh(self, screen: ShiftPlanningScreen) -> None:
        """Açıq elanları yenidən oxuyur."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                views = session.open_shifts.list_active(
                    tenant_id=session.tenant_id, actor=self._actor
                )
                rows = [_to_admin_row(session, view) for view in views]
        except KompasOSError as error:
            # Səlahiyyəti olmayan istifadəçi bu ekranı ümumiyyətlə görməməli
            # idi (menyu flag-i), lakin görsə — kart sükutla boş qalmır.
            screen.set_open_shift_postings([])
            screen.show_error(title="Açıq növbələr oxunmadı", message=error.user_message)
            return
        except Exception:
            # QA-14 (dövrə 3 audit) — əvvəl bura DA sükutla boşaldırdı, LAKİN
            # `show_error()` çağırmırdı: baza əlaqəsi kəsiləndə admin BOŞ
            # kart görürdü, `KompasOSError` qolundan FƏRQLİ olaraq səbəb heç
            # yerdə görünmürdü. İki qol İNDİ SİMMETRİKDİR.
            _error_log.exception("OPEN_SHIFT_ADMIN_LIST_FAILED")
            screen.set_open_shift_postings([])
            screen.show_error(
                title="Açıq növbələr oxunmadı",
                message="Siyahı yüklənmədi. Yenidən cəhd edin.",
            )
            return

        screen.set_open_shift_postings(rows)

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_post(self, screen: ShiftPlanningScreen) -> None:
        """`[Açıq Növbə Elan Et]` — dialoq açılır, seçim use case-ə gedir."""
        from src.presentation.screens.open_shift import (  # noqa: PLC0415
            OpenShiftPostDialog,
        )

        try:
            with self._context.session(user_id=self._actor.id) as session:
                stores = _store_choices(session)
                modes = _work_mode_choices(session)
                days = _day_choices(_max_lead_days(session))
        except Exception:
            _error_log.exception("OPEN_SHIFT_DIALOG_DATA_FAILED")
            screen.show_error(
                title="Elan forması açılmadı",
                message="Mağaza və iş rejimi siyahısı oxunmadı. Yenidən cəhd edin.",
            )
            return

        dialog = OpenShiftPostDialog(
            screen.theme,
            stores=stores,
            days=days,
            work_modes=modes,
            parent=screen,
        )
        dialog.submitted.connect(
            lambda store_id, day, mode_id: self._submit(screen, store_id, day, mode_id)
        )
        dialog.exec()

    def _submit(self, screen: ShiftPlanningScreen, store_id: str, day: str, mode_id: str) -> None:
        try:
            parsed_store = StoreId(uuid.UUID(store_id))
            parsed_mode = WorkModeId(uuid.UUID(mode_id))
            parsed_day = date.fromisoformat(day)
        except ValueError:
            screen.show_error(
                title="Elan yaradılmadı",
                message="Seçilmiş dəyərlər düzgün deyil.",
            )
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.open_shifts.post_open_shift(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    store_id=parsed_store,
                    shift_date=parsed_day,
                    work_mode_id=parsed_mode,
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="Elan yaradılmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception("OPEN_SHIFT_POST_FAILED")
            screen.show_error(
                title="Elan yaradılmadı",
                message="Elan yazılmadı. Yenidən cəhd edin.",
            )
            return

        self.refresh(screen)

    def _on_cancel(self, screen: ShiftPlanningScreen, posting_id: str) -> None:
        """`[Ləğv Et]` — səbəb MƏCBURİDİR (domen qaydası)."""
        try:
            parsed_id = OpenShiftPostingId(uuid.UUID(posting_id))
        except ValueError:
            screen.show_error(
                title="Elan ləğv edilmədi",
                message="Elan identifikatoru düzgün deyil.",
            )
            return

        reason = self._ask_reason(screen)
        if reason is None:
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.open_shifts.cancel_posting(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    posting_id=parsed_id,
                    reason=reason,
                )
                session.commit()
        except KompasOSError as error:
            # Elan bu arada tutulubsa da bura düşür — admin AÇIQ cavab alır.
            screen.show_error(title="Elan ləğv edilmədi", message=error.user_message)
            self.refresh(screen)
            return
        except Exception:
            _error_log.exception("OPEN_SHIFT_CANCEL_FAILED", extra={"posting_id": posting_id})
            screen.show_error(
                title="Elan ləğv edilmədi",
                message="Dəyişiklik yazılmadı. Yenidən cəhd edin.",
            )
            return

        self.refresh(screen)

    @staticmethod
    def _ask_reason(screen: ShiftPlanningScreen) -> str | None:
        from PySide6.QtWidgets import QInputDialog  # noqa: PLC0415

        text, accepted = QInputDialog.getMultiLineText(screen, "Elanı ləğv et", _CANCEL_PROMPT)
        cleaned = text.strip()
        return cleaned if accepted and cleaned else None


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _to_employee_row(session: Session, view: OpenShiftView) -> dict[str, str]:
    """`OpenShiftView` → İşçi Ana Ekranının FAKTİKİ gözlədiyi açarlar."""
    return {
        "id": str(view.posting_id),
        "date": _day_label(view.shift_date),
        "work_mode": _work_mode_name(session, view.work_mode_id),
    }


def _to_admin_row(session: Session, view: OpenShiftView) -> dict[str, str]:
    """`OpenShiftView` → Növbə Planlama kartının FAKTİKİ gözlədiyi açarlar."""
    return {
        "id": str(view.posting_id),
        "date": _day_label(view.shift_date),
        "work_mode": _work_mode_name(session, view.work_mode_id),
        "store": _store_name(session, view.store_id),
    }


def _day_label(day: date) -> str:
    """«13.08.2026 · Çər» — həftə günü olmadan admin ritmi görə bilmir."""
    return f"{day.strftime('%d.%m.%Y')} · {_WEEKDAYS_AZ[day.weekday()]}"


def _day_choices(max_lead_days: int) -> list[tuple[str, str]]:
    """Dialoqdakı tarix siyahısı — YALNIZ icazəli günlər (bax ekran başlığı).

    Bugün DAXİLDİR: səhər növbəsi ləğv olunanda axşam növbəsini elə həmin gün
    elan etmək bazarın ən çox işlədiləcək halıdır.
    """
    today = date.today()  # noqa: DTZ011 — təqvim GÜNÜ, an deyil; `Clock` portu
    # domen qərarları üçündür, burada isə yalnız seçim siyahısı qurulur və
    # həqiqi hədd yoxlaması use case-dədir (`post_open_shift`).
    return [
        (day.isoformat(), _day_label(day))
        for day in (today + timedelta(days=offset) for offset in range(max_lead_days + 1))
    ]


def _max_lead_days(session: Session) -> int:
    """ROOT parametri — dialoq nə qədər irəli göstərsin.

    Ekranda hardcode ədəd YOXDUR: dəyər `system_limits`-dən oxunur, fallback
    isə use case ilə EYNİ mənbədəndir (`DEFAULT_LIMITS`).
    """
    value = int(
        session.limits.get_int(
            session.tenant_id,
            SystemLimitKey.OPEN_SHIFT_MAX_LEAD_DAYS.value,
            FALLBACK_MAX_LEAD_DAYS,
        )
    )
    return value if value > 0 else int(DEFAULT_LIMITS[SystemLimitKey.OPEN_SHIFT_MAX_LEAD_DAYS])


def _store_choices(session: Session) -> list[tuple[str, str]]:
    """Aktiv mağazalar — `tenant_id` şərti İKİNCİ TƏCRİD QATIDIR (CLAUDE.md §6)."""
    rows = session.uow.connection.execute(
        "SELECT id, name FROM stores WHERE tenant_id = %s AND is_active ORDER BY name",
        (session.tenant_id,),
    ).fetchall()
    return [(str(row["id"]), str(row["name"])) for row in rows]


def _work_mode_choices(session: Session) -> list[tuple[str, str]]:
    """Aktiv iş rejimləri — MÖVCUD kataloq use case-i ilə oxunur.

    `list_for_selection()` səlahiyyət TƏLƏB ETMİR (bax `catalog_management.py`):
    növbə planlayan `can_manage_work_modes` sahibi olmaya bilər, o, kataloqu
    dəyişmir — sadəcə şablon seçir.
    """
    modes = session.work_modes.list_for_selection(session.tenant_id)
    return [
        (str(mode.work_mode_id), f"{mode.name} · {mode.scheduled_start_label()}")
        for mode in modes
        if mode.work_mode_id is not None
    ]


def _work_mode_name(session: Session, work_mode_id: WorkModeId) -> str:
    """İş rejiminin adı — tapılmazsa ID-nin qısa forması.

    Rejim kataloqdan çıxarılsa (soft delete) elan yenə oxunmalıdır: sətri
    gizlətmək işçidən mövcud bir növbəni gizlətmək olardı.
    """
    mode = session.uow.repository("work_modes").get(work_mode_id)
    if mode is None:
        return f"#{str(work_mode_id)[:8]}"
    return f"{mode.name} · {mode.scheduled_start_label()}"


def _store_name(session: Session, store_id: StoreId) -> str:
    """Mağaza adı — `screen_data._store_name` ilə eyni qərar və eyni şərt."""
    row = session.uow.connection.execute(
        "SELECT name FROM stores WHERE id = %s AND tenant_id = %s",
        (store_id, session.tenant_id),
    ).fetchone()
    return str(row["name"]) if row else f"#{str(store_id)[:8]}"


__all__ = [
    "EmployeeOpenShiftController",
    "ShiftMatrixOpenShiftController",
]
