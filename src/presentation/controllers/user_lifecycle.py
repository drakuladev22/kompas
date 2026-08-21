"""İşçi həyat dövrü — PIN/şifrə sıfırlama, rol dəyişikliyi, deaktivasiya.

──────────────────────────────────────────────────────────────────────────────
QA-FULL FAZA 3 — DÖRD "···" BƏNDİ ÖLÜ İDİ (KRİTİK TAPINTI)
──────────────────────────────────────────────────────────────────────────────
`UsersScreen.ACTIONS`-dakı ALTI bənddən dördü (`reset_pin`, `reset_password`,
`change_role`, `deactivate`) heç bir kontrollerə bağlı deyildi — `controllers/
pos_threshold.py`-nın köhnə başlığı bunu "bu partiyanın əhatəsindən kənardır"
deyə sənədləşdirirdi, lakin `e2e-test-engineer` REAL kliklə göstərdi ki, admin
"Deaktiv Et" (işdən çıxarma!) basanda HEÇ NƏ baş vermir — nə xəta, nə uğur, nə
audit izi. Bu fayl həmin dörd bəndi bağlayır; `pos_threshold`/`employee_
documents` ÖZ kontrollerlərini SAXLAYIR (`_on_action` onları görməzdən gəlir).

Backend HAZIR İDİ — heç nə YAZILMIR, yalnız BAĞLANIR:
    * `UserManagementUseCase.reset_pin`         → RESET_PIN_FLAG
    * `UserManagementUseCase.reset_password`    → RESET_PASSWORD_FLAG
    * `UserManagementUseCase.update_employee`   → MANAGE_EMPLOYEES_FLAG +
                                                    (rol dəyişəndə) MANAGE_ROLES_FLAG
    * `UserManagementUseCase.deactivate_employee` → MANAGE_EMPLOYEES_FLAG
Strict Hierarchy Guard (`_assert_may_manage`) və Self-Escalation Guard
(`_assert_not_self`) use case-lərin İÇİNDƏDİR — bu kontroller onları TƏKRAR
YAZMIR, yalnız istisnanı istifadəçiyə izah edir (`pos_threshold.py` ilə eyni
qərar).

──────────────────────────────────────────────────────────────────────────────
"GÖRMƏK = SƏLAHİYYƏTİN OLMASI" — MENYU ÖZÜ BURADA SÜZÜLMÜR
──────────────────────────────────────────────────────────────────────────────
Bu kontroller yazı yolunu bağlayır, LAKİN "···" menyusunun hansı bəndlərinin
GÖRÜNƏCƏYİNİ `screen_data.py::_users` həll edir (`UsersScreen.
set_permitted_actions()`). Səbəb: menyu bütün YAZAN kontrollerlərin (bu fayl,
`pos_threshold.py`, `employee_documents.py`) ÜÇÜNÜN də `refresh()`-i EYNİ
`ScreenDataBinder.populate("users", screen)` çağırışından keçir — süzgəc
TƏK yerdə saxlanılmasa, hər kontroller öz aktorunun icazəsini AYRI hesablayıb
bir-birini üstələyərdi.

──────────────────────────────────────────────────────────────────────────────
`change_role` NİYƏ ƏVVƏLCƏ İŞÇİNİ YÜKLƏYİR
──────────────────────────────────────────────────────────────────────────────
`UserManagementUseCase.update_employee` bütün `EmployeeDraft`-ı YAZIR — "yalnız
dəyişəni göndər" yoxdur. Draftı YALNIZ `position` sahəsi ilə qursaydıq, mağaza/
e-poçt/tarix sahələri BOŞ yazılardı (sükutlu məlumat itkisi). Ona görə
`_change_role` əvvəlcə cari `Employee`-ni oxuyur, draftı ONUN sahələri ilə
doldurur, YALNIZ `position`-u əvəzləyir (`ChangeRoleDialog` başlığı).

──────────────────────────────────────────────────────────────────────────────
`deactivate` NİYƏ ÖZ DİALOQU YOX, `QInputDialog.getMultiLineText`
──────────────────────────────────────────────────────────────────────────────
Geri qaytarıla bilməyən əməliyyat SƏBƏBSİZ icra oluna bilməz —
`deactivate_employee(..., reason: str)` onu MƏCBUR edir. Yeni təsdiq dialoqu
QURULMUR: `controllers/open_shift.py::_ask_reason` və `employee_documents.py::
_deactivate` ilə EYNİ naxış — səbəb yazmaq ÖZÜ təsdiqdir (İmtina = "yaz"
düyməsini basmamaq), sətir boşdursa əməliyyat baş TUTMUR.

Sessiya SAXLANMIR (CLAUDE.md §6): hər əməliyyat üçün yeni sessiya açılır və
commit edilir. `show_error(...)`-dan sonra `refresh()` ÇAĞIRILMIR
(`announcements.py::_on_withdraw`-da tapılan eyni qüsurdan qaçmaq üçün) —
yenidən yükləmə lazım olan yerdə `on_retry` ilə istifadəçinin qərarına
buraxılır.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.domain.value_objects.authorization import SystemRole
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.value_objects.identifiers import EmployeeId
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_c import UsersScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: `UsersScreen.ACTIONS`-dəki açarlar — bu kontroller YALNIZ bunları emal
#: edir (`pos_threshold`/`employee_documents` öz kontrollerlərindədir).
RESET_PIN_ACTION_KEY = "reset_pin"
RESET_PASSWORD_ACTION_KEY = "reset_password"  # noqa: S105
CHANGE_ROLE_ACTION_KEY = "change_role"
DEACTIVATE_ACTION_KEY = "deactivate"


class UserLifecycleController:
    """`UsersScreen`-in PIN/şifrə/rol/deaktivasiya bəndlərini `UserManagementUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: UsersScreen) -> None:
        screen.action_requested.connect(lambda key, name: self._on_action(screen, key, name))

    def _on_action(self, screen: UsersScreen, key: str, full_name: str) -> None:
        if key == RESET_PIN_ACTION_KEY:
            self._open_reset_pin(screen, full_name)
        elif key == RESET_PASSWORD_ACTION_KEY:
            self._open_reset_password(screen, full_name)
        elif key == CHANGE_ROLE_ACTION_KEY:
            self._open_change_role(screen, full_name)
        elif key == DEACTIVATE_ACTION_KEY:
            self._deactivate(screen, full_name)
        # `pos_threshold`/`employee_documents` BURADA DEYİL — modul başlığı.

    # -------------------------------- PIN ------------------------------------ #

    def _open_reset_pin(self, screen: UsersScreen, full_name: str) -> None:
        from src.presentation.screens.group_c import ResetPinDialog  # noqa: PLC0415

        dialog = ResetPinDialog(screen.theme, employee_name=full_name, parent=screen)
        dialog.submitted.connect(
            lambda new_pin: self._reset_pin(screen, full_name=full_name, new_pin=new_pin)
        )
        dialog.exec()

    def _reset_pin(self, screen: UsersScreen, *, full_name: str, new_pin: str) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                employee_id = _find_employee_id(session, full_name)
                if employee_id is None:
                    screen.show_error(
                        title="İşçi tapılmadı",
                        message="Bu işçi artıq siyahıda deyil. Səhifəni yeniləyin.",
                    )
                    return
                session.users.reset_pin(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    employee_id=employee_id,
                    new_pin=new_pin,
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="PIN sıfırlanmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception("USER_LIFECYCLE_RESET_PIN_FAILED")
            screen.show_error(
                title="PIN sıfırlanmadı", message="Dəyişiklik saxlanmadı. Yenidən cəhd edin."
            )
            return

        self._refresh(screen)

    # ------------------------------- şifrə ------------------------------------ #

    def _open_reset_password(self, screen: UsersScreen, full_name: str) -> None:
        from src.presentation.screens.group_c import ResetPasswordDialog  # noqa: PLC0415

        dialog = ResetPasswordDialog(screen.theme, employee_name=full_name, parent=screen)
        dialog.submitted.connect(
            lambda new_password: self._reset_password(
                screen, full_name=full_name, new_password=new_password
            )
        )
        dialog.exec()

    def _reset_password(self, screen: UsersScreen, *, full_name: str, new_password: str) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                employee_id = _find_employee_id(session, full_name)
                if employee_id is None:
                    screen.show_error(
                        title="İşçi tapılmadı",
                        message="Bu işçi artıq siyahıda deyil. Səhifəni yeniləyin.",
                    )
                    return
                session.users.reset_password(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    employee_id=employee_id,
                    new_password=new_password,
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="Şifrə yenilənmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception("USER_LIFECYCLE_RESET_PASSWORD_FAILED")
            screen.show_error(
                title="Şifrə yenilənmədi", message="Dəyişiklik saxlanmadı. Yenidən cəhd edin."
            )
            return

        self._refresh(screen)

    # -------------------------------- rol ------------------------------------- #

    def _open_change_role(self, screen: UsersScreen, full_name: str) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                employee_id = _find_employee_id(session, full_name)
                if employee_id is None:
                    screen.show_error(
                        title="İşçi tapılmadı",
                        message="Bu işçi artıq siyahıda deyil. Səhifəni yeniləyin.",
                    )
                    return
                current = session.uow.employees.get(employee_id)
                if current is None:
                    screen.show_error(
                        title="İşçi tapılmadı",
                        message="Bu işçi artıq siyahıda deyil. Səhifəni yeniləyin.",
                    )
                    return
                positions = _active_position_choices(session)
        except Exception:
            _error_log.exception("USER_LIFECYCLE_CHANGE_ROLE_DIALOG_DATA_FAILED")
            screen.show_error(
                title="Rol forması açılmadı",
                message="Vəzifə siyahısı oxunmadı. Yenidən cəhd edin.",
            )
            return

        from src.presentation.screens.group_c import ChangeRoleDialog  # noqa: PLC0415

        dialog = ChangeRoleDialog(
            screen.theme,
            employee_name=full_name,
            current_role=current.position.name_az,
            positions=positions,
            parent=screen,
        )
        dialog.submitted.connect(
            lambda position_id: self._change_role(
                screen, employee_id=employee_id, full_name=full_name, position_id=position_id
            )
        )
        dialog.exec()

    def _change_role(
        self, screen: UsersScreen, *, employee_id: EmployeeId, full_name: str, position_id: str
    ) -> None:
        from uuid import UUID  # noqa: PLC0415

        from src.application.use_cases.user_management import EmployeeDraft  # noqa: PLC0415
        from src.domain.value_objects.identifiers import PositionId  # noqa: PLC0415

        try:
            parsed_position_id = PositionId(UUID(position_id))
        except ValueError:
            screen.show_error(title="Rol dəyişmədi", message="Seçilmiş vəzifə düzgün deyil.")
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                employee = session.uow.employees.get(employee_id)
                if employee is None:
                    screen.show_error(
                        title="İşçi tapılmadı",
                        message="Bu işçi artıq siyahıda deyil. Səhifəni yeniləyin.",
                    )
                    return
                new_position = session.uow.positions.get(parsed_position_id)
                if new_position is None:
                    screen.show_error(
                        title="Rol dəyişmədi",
                        message="Seçilmiş vəzifə artıq mövcud deyil. Səhifəni yeniləyin.",
                    )
                    return

                # DRAFT MÖVCUD SAHƏLƏRLƏ DOLDURULUR (`ChangeRoleDialog`
                # başlığı) — yalnız `position` əvəzlənir. Kamera mağazaları
                # YALNIZ yeni rol kamera-tiplidirsə köçürülür:
                # `_apply_camera_stores` kamera-tipli OLMAYAN rolda boş-olmayan
                # siyahını RƏDD EDİR (`user_management.py`).
                camera_store_ids = (
                    tuple(employee.assigned_store_ids)
                    if new_position.effective_system_role is SystemRole.CAMERA_OPERATOR
                    else ()
                )
                draft = EmployeeDraft(
                    first_name=employee.first_name,
                    last_name=employee.last_name,
                    position=new_position,
                    store_id=employee.store_id,
                    notification_email=employee.notification_email,
                    hire_date=employee.hire_date,
                    date_of_birth=employee.date_of_birth,
                    profile_photo_url=employee.profile_photo_url,
                    camera_store_ids=camera_store_ids,
                )
                session.users.update_employee(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    employee_id=employee_id,
                    draft=draft,
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="Rol dəyişmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception(
                "USER_LIFECYCLE_CHANGE_ROLE_FAILED", extra={"employee_id": str(employee_id)}
            )
            screen.show_error(
                title="Rol dəyişmədi", message="Dəyişiklik saxlanmadı. Yenidən cəhd edin."
            )
            return

        self._refresh(screen)

    # ------------------------------ deaktivasiya ------------------------------- #

    def _deactivate(self, screen: UsersScreen, full_name: str) -> None:
        from PySide6.QtWidgets import QInputDialog  # noqa: PLC0415

        text, accepted = QInputDialog.getMultiLineText(
            screen,
            "İşçini deaktiv et",
            f"{full_name} niyə deaktiv edilir? GERİ QAYTARILA BİLMİR — "
            "yenidən işə götürülərsə yeni işçi kartı açılır.",
        )
        reason = text.strip()
        if not accepted or not reason:
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                employee_id = _find_employee_id(session, full_name)
                if employee_id is None:
                    screen.show_error(
                        title="İşçi tapılmadı",
                        message="Bu işçi artıq siyahıda deyil. Səhifəni yeniləyin.",
                    )
                    return
                session.users.deactivate_employee(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    employee_id=employee_id,
                    reason=reason,
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="İşçi deaktiv edilmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception("USER_LIFECYCLE_DEACTIVATE_FAILED")
            screen.show_error(
                title="İşçi deaktiv edilmədi", message="Dəyişiklik saxlanmadı. Yenidən cəhd edin."
            )
            return

        self._refresh(screen)

    # -------------------------------- oxuma ---------------------------------- #

    def _refresh(self, screen: UsersScreen) -> None:
        from src.presentation.controllers.screen_data import ScreenDataBinder  # noqa: PLC0415

        ScreenDataBinder(self._context, self._actor).populate("users", screen)


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _find_employee_id(session: Session, full_name: str) -> Any:
    """Görünən ad → `employee_id`. `pos_threshold.py`-dəki EYNİ funksiyanın təkrarı.

    İki kontroller arasında import bağı qurmaq əvəzinə hər biri öz nüsxəsini
    saxlayır (`employee_documents.py` başlığındakı EYNİ qərar).
    """
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


def _active_position_choices(session: Session) -> list[tuple[str, str]]:
    """Aktiv vəzifələr — `(id, ad)`. `user_admin.py::_position_choices` ilə EYNİ sorğu.

    Kamera-tipli bayraq burada LAZIM DEYİL (`user_admin.py`-dan fərqli): "Rolu
    Dəyiş" dialoqu hər zaman göstərilir, kamera sahəsi isə YOXDUR — kamera
    mağazaları köçürülməsi (`_change_role`) `Position.effective_system_role`-a
    görə AVTOMATİK həll olunur, admin ayrıca seçim etmir.
    """
    positions = session.uow.positions.list_for_tenant(session.tenant_id)
    return [(str(position.id), position.name_az) for position in positions if position.is_active]


__all__ = [
    "CHANGE_ROLE_ACTION_KEY",
    "DEACTIVATE_ACTION_KEY",
    "RESET_PASSWORD_ACTION_KEY",
    "RESET_PIN_ACTION_KEY",
    "UserLifecycleController",
]
