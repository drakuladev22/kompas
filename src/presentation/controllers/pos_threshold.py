"""#7 POS Səlahiyyət Siyasətinin yazı yolu — `UsersScreen`-in "···" menyusu.

kompasos11.md struktur qərarı A: bu, YALNIZ sənədləşdirmə formasıdır. Heç bir
qapı burada TƏKRARLANMIR — `POSThresholdUseCase` daxilindədir:

    * `can_manage_pos_thresholds` yoxlaması   → `_require_permission()`
    * SELF-ESCALATION GUARD                    → `_require_not_self()`
    * Strict Hierarchy Guard                   → `_require_hierarchy()`
      (`Employee.outranks()` birbaşa çağırılır)
    * Audit (`POS_THRESHOLD_SET`/`_REVOKED`)    → `set_threshold()`/`revoke_threshold()`

Kontrollerin yeganə əlavəsi istisnanın İSTİFADƏÇİYƏ İZAH EDİLMƏSİDİR —
`permission_matrix.py`-dəki EYNİ qərar.

──────────────────────────────────────────────────────────────────────────────
NİYƏ "···" MENYUSUNUN QALAN MADDƏLƏRİ BURADA YOXDUR
──────────────────────────────────────────────────────────────────────────────
`reset_pin`, `reset_password`, `change_role`, `deactivate` bu faylın
ƏHATƏSİNDƏN KƏNARDIR — onlar AYRI kontrollerdə (`controllers/
user_lifecycle.py`) bağlıdır. Əvvəl (bu şərh yazılanda) heç birinə bağlı deyildilər
(`UsersScreen` heç vaxt `app.py::_attach_write_controller`-in cədvəlində
olmayıb) — bu, QA-FULL Faza 3-ün KRİTİK tapıntısı idi (admin "Deaktiv Et"
basırdı, HEÇ NƏ baş vermirdi) və `user_lifecycle.py`-da düzəldilib. Bu faylın
öz bəndini (`pos_threshold`) DƏYİŞMƏDƏN saxlaması ilə bağlı izah aşağıdadır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ İŞÇİ ADI İLƏ AXTARIŞ (FINE_ENTRY İLƏ EYNİ MƏHDUDİYYƏT)
──────────────────────────────────────────────────────────────────────────────
`UsersScreen.action_requested` domen ID-si deyil, GÖRÜNƏN adı ötürür (bax
ekranın "···" menyusu). `controllers/fine_entry.py`-dəki `_employee_names`
ilə EYNİ tanınmış məhdudiyyət: eyni tam adlı iki işçi olarsa axtarış
sonuncunu tapır. Bu, yeni bir problem DEYİL — mövcud naxışın təkrarıdır.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.value_objects.identifiers import EmployeeId
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_c import UsersScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: `UsersScreen.ACTIONS`-dəki açar — YALNIZ bu emal olunur.
POS_THRESHOLD_ACTION_KEY = "pos_threshold"


class UsersPOSThresholdController:
    """`UsersScreen`-in "POS Səlahiyyəti" bəndini `POSThresholdUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: UsersScreen) -> None:
        screen.action_requested.connect(lambda key, name: self._on_action(screen, key, name))

    def _on_action(self, screen: UsersScreen, key: str, full_name: str) -> None:
        if key != POS_THRESHOLD_ACTION_KEY:
            return
        self._open_dialog(screen, full_name)

    # -------------------------------- açılış ---------------------------------- #

    def _open_dialog(self, screen: UsersScreen, full_name: str) -> None:
        from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey  # noqa: PLC0415

        try:
            with self._context.session(user_id=self._actor.id) as session:
                employee_id = _find_employee_id(session, full_name)
                if employee_id is None:
                    screen.show_error(
                        title="İşçi tapılmadı",
                        message="Bu işçi artıq siyahıda deyil. Səhifəni yeniləyin.",
                    )
                    return
                existing = session.pos_threshold.get_threshold(
                    tenant_id=session.tenant_id, actor=self._actor, employee_id=employee_id
                )
                ceiling = session.limits.get_str(
                    session.tenant_id,
                    SystemLimitKey.POS_MAX_DISCOUNT_PCT_CEILING.value,
                    str(DEFAULT_LIMITS[SystemLimitKey.POS_MAX_DISCOUNT_PCT_CEILING]),
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="POS həddi açıla bilmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception("POS_THRESHOLD_LOAD_FAILED")
            screen.show_error(
                title="POS həddi açıla bilmədi",
                message="Məlumat yüklənmədi. Yenidən cəhd edin.",
            )
            return

        self._show_dialog(
            screen,
            employee_id=employee_id,
            full_name=full_name,
            existing=existing,
            ceiling=ceiling,
        )

    def _show_dialog(
        self,
        screen: UsersScreen,
        *,
        employee_id: EmployeeId,
        full_name: str,
        existing: Any,
        ceiling: str,
    ) -> None:
        from src.presentation.screens.group_c import PosThresholdDialog  # noqa: PLC0415

        dialog = PosThresholdDialog(
            screen.theme,
            employee_name=full_name,
            max_discount_pct=str(existing.max_discount_pct) if existing is not None else "0",
            can_void=existing.can_void if existing is not None else False,
            can_refund=existing.can_refund if existing is not None else False,
            note=(existing.note or "") if existing is not None else "",
            ceiling_pct=ceiling,
            has_existing=existing is not None and existing.is_active,
            parent=screen,
        )
        dialog.submitted.connect(
            lambda pct, void, refund, note: self._save(
                screen, employee_id=employee_id, pct=pct, void=void, refund=refund, note=note
            )
        )
        dialog.revoke_requested.connect(lambda: self._revoke(screen, employee_id=employee_id))
        dialog.exec()

    # -------------------------------- yazı yolu -------------------------------- #

    def _save(
        self,
        screen: UsersScreen,
        *,
        employee_id: EmployeeId,
        pct: str,
        void: bool,
        refund: bool,
        note: str,
    ) -> None:
        from src.application.use_cases.pos_threshold import POSThresholdDraft  # noqa: PLC0415

        try:
            parsed_pct = Decimal(pct.strip().replace(",", "."))
        except (InvalidOperation, ValueError):
            screen.show_error(
                title="Dəyər yanlışdır",
                message="Maksimum endirim faizi ədəd olmalıdır (məsələn 15 və ya 15.5).",
            )
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                subject = session.uow.employees.get(employee_id)
                if subject is None:
                    screen.show_error(
                        title="İşçi tapılmadı",
                        message="Bu işçi artıq siyahıda deyil. Səhifəni yeniləyin.",
                    )
                    return
                session.pos_threshold.set_threshold(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    subject=subject,
                    draft=POSThresholdDraft(
                        max_discount_pct=parsed_pct,
                        can_void=void,
                        can_refund=refund,
                        note=note or None,
                    ),
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="POS həddi yazılmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception(
                "POS_THRESHOLD_SET_FAILED", extra={"employee_id": str(employee_id)}
            )
            screen.show_error(
                title="POS həddi yazılmadı",
                message="Dəyişiklik saxlanmadı. Yenidən cəhd edin.",
            )
            return

        self._refresh(screen)

    def _revoke(self, screen: UsersScreen, *, employee_id: EmployeeId) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                subject = session.uow.employees.get(employee_id)
                if subject is None:
                    screen.show_error(
                        title="İşçi tapılmadı",
                        message="Bu işçi artıq siyahıda deyil. Səhifəni yeniləyin.",
                    )
                    return
                session.pos_threshold.revoke_threshold(
                    tenant_id=session.tenant_id, actor=self._actor, subject=subject
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="POS həddi geri alınmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception(
                "POS_THRESHOLD_REVOKE_FAILED", extra={"employee_id": str(employee_id)}
            )
            screen.show_error(
                title="POS həddi geri alınmadı",
                message="Dəyişiklik saxlanmadı. Yenidən cəhd edin.",
            )
            return

        self._refresh(screen)

    def _refresh(self, screen: UsersScreen) -> None:
        from src.presentation.controllers.screen_data import ScreenDataBinder  # noqa: PLC0415

        ScreenDataBinder(self._context, self._actor).populate("users", screen)


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _find_employee_id(session: Session, full_name: str) -> Any:
    """Görünən ad → `employee_id`. Tapılmasa `None` (bax modul başlığı)."""
    rows = session.uow.connection.execute(
        """
        SELECT id, first_name, last_name
          FROM employees
         WHERE tenant_id = %s AND is_active
         ORDER BY last_name, first_name
         LIMIT 500
        """,
        (session.tenant_id,),
    ).fetchall()
    needle = full_name.strip()
    for row in rows:
        if f"{row['first_name']} {row['last_name']}".strip() == needle:
            return row["id"]
    return None


__all__ = ["POS_THRESHOLD_ACTION_KEY", "UsersPOSThresholdController"]
